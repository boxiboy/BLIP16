"""Reads a music file and extracts tempo, beat grid, drum pattern, key, chords, arrangement and melody,
then builds a BLIP song from them (the "remix" feature)."""
import collections
import os
import re
import shutil
import subprocess
import wave

import numpy as np

from .styles import SCALES
from .song import Song


# ---------- remix: analyse a music file, keep its groove / harmony / arrangement, rebuild it ----------
# What is taken from the file: tempo, beat grid, drum pattern, key, chords per bar, energy curve.
# What is NOT taken: melody and vocals - the rebuilt song writes its own lead over the same chords.
KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])


KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


ASR, AHOP, ANFFT = 22050, 512, 2048


def decode_audio(path, sr=ASR, max_s=360):
    """Mono float32 at sr. ffmpeg reads anything (mp3, m4a, flac...); without it only .wav works."""
    if shutil.which('ffmpeg'):
        try:
            r = subprocess.run(['ffmpeg', '-v', 'quiet', '-i', path, '-t', str(max_s), '-f', 'f32le', '-ac', '1',
                                '-ar', str(sr), '-'], capture_output=True, timeout=180)
            a = np.frombuffer(r.stdout, '<f4')
            if len(a) > sr * 5:
                return a.astype(np.float32)
        except (OSError, subprocess.SubprocessError):
            pass
    if path.lower().endswith('.wav'):
        with wave.open(path) as w:
            ch, sw, fs = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(min(w.getnframes(), fs * max_s))
        if sw == 2:
            a = np.frombuffer(raw, '<i2') / 32768.0
        elif sw == 3:
            b = np.frombuffer(raw, 'u1').reshape(-1, 3).astype(np.int32)
            v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            a = np.where(v >= 1 << 23, v - (1 << 24), v) / float(1 << 23)
        elif sw == 4:
            a = np.frombuffer(raw, '<i4') / 2.0 ** 31
        else:
            a = (np.frombuffer(raw, 'u1').astype(float) - 128) / 128.0
        a = a[:len(a) // ch * ch].reshape(-1, ch).mean(1)
        if fs != sr:
            a = np.interp(np.arange(int(len(a) * sr / fs)) * fs / sr, np.arange(len(a)), a)
        return a.astype(np.float32)
    raise ValueError("can't read this file - install ffmpeg for mp3/m4a/flac (brew install ffmpeg)")


def _novelty(x):
    m = np.convolve(x, np.ones(16) / 16, 'same')
    y = np.maximum(x - m, 0)
    return y / max(1e-9, np.percentile(y, 99))


MEL_LO, MEL_HI = 52, 88          # MIDI range searched for the lead melody


def extract_melody(a, sr, grid, env):
    """Predominant melody -> notes on the song's 16th grid.

    Pitch salience by harmonic summation on a fine (4096-point) spectrum, a Viterbi path that prefers
    smooth lines and the vocal/lead register, octave clean-up, then each grid step takes the pitch most
    of its frames agree on. Returns {bar: [(step, midi, length_in_steps), ...]}."""
    N = 4096
    nfr = 1 + (len(a) - N) // AHOP
    if nfr < 16:
        return {}
    freqs = np.fft.rfftfreq(N, 1 / sr)
    band = (freqs > 120) & (freqs < 5000)
    lo_sem, n_sem = MEL_LO - 2, (MEL_HI + 30) - (MEL_LO - 2)
    mf = 12 * np.log2(freqs[band] / 440.0) + 69 - lo_sem
    i0, fr_ = np.floor(mf).astype(int), mf - np.floor(mf)
    ok = (i0 >= 0) & (i0 < n_sem - 1)
    M = np.zeros((band.sum(), n_sem), np.float32)
    M[np.arange(band.sum())[ok], i0[ok]] += 1 - fr_[ok]
    M[np.arange(band.sum())[ok], i0[ok] + 1] += fr_[ok]
    M /= np.maximum(1e-9, M.sum(0, keepdims=True))
    npit = MEL_HI - MEL_LO + 1
    base = MEL_LO - lo_sem
    win, off = np.hanning(N).astype(np.float32), np.arange(N)
    sal = np.zeros((nfr, npit), np.float32)
    for s in range(0, nfr, 512):
        idx = np.arange(s, min(nfr, s + 512))
        S = np.abs(np.fft.rfft(a[idx[:, None] * AHOP + off[None, :]] * win, axis=1))[:, band].astype(np.float32)
        S = np.sqrt(S)
        S = np.maximum(S - np.median(S, axis=1, keepdims=True), 0)       # drop the noise floor
        with np.errstate(all='ignore'):    # numpy 2.0 + Apple Accelerate raise false FP flags in matmul
            X = S @ M
        F0 = X[:, base:base + npit]
        # each harmonic only counts up to the fundamental's own energy, so a lower "phantom" note can't
        # collect the real melody's partials (the classic octave-down error)
        sal[idx] = F0 + sum(w * np.minimum(F0, X[:, base + h:base + h + npit])
                            for h, w in ((12, 0.8), (19, 0.6), (24, 0.5), (28, 0.4)))
    # held pads and drones sit still for bars; a melody moves. Remove each pitch's slow (~1.2 s) average
    # so notes that start and stop stand out over sustained accompaniment.
    W = max(4, int(1.2 * sr / AHOP))
    c = np.cumsum(np.vstack([np.zeros((1, npit), np.float32), sal]), axis=0)
    lo_i = np.clip(np.arange(nfr) - W // 2, 0, nfr)
    hi_i = np.clip(np.arange(nfr) + W // 2, 0, nfr)
    slow = (c[hi_i] - c[lo_i]) / np.maximum(1, hi_i - lo_i)[:, None]
    sal = np.maximum(sal - 0.8 * slow, 0) + 0.25 * sal
    # emission: salience vs. the track's typical level, favouring the singing register
    ref = max(1e-9, np.percentile(sal.max(1), 90))
    pitches = np.arange(MEL_LO, MEL_HI + 1)
    # a lead usually rides on top: lean towards the higher of two strong lines (bass lives below)
    em = sal / ref * np.clip((pitches - 48) / 20.0, 0.25, 1.3)[None, :]
    silent = np.full(nfr, 0.45, np.float32)
    # Viterbi: states = npit pitches + 1 silence; jumps cost by size, voicing changes cost a little
    jump = 0.12 * np.minimum(np.abs(pitches[:, None] - pitches[None, :]), 12)
    score = np.r_[em[0], silent[0]]
    back = np.zeros((nfr, npit + 1), np.int16)
    for f in range(1, nfr):
        sp, ss = score[:npit], score[npit]
        cand = sp[:, None] - jump                          # from pitch i to pitch j
        bi = np.argmax(cand, axis=0)
        bv = cand[bi, np.arange(npit)]
        from_sil = ss - 0.15
        to_p = np.where(bv >= from_sil, bv, from_sil)
        back[f, :npit] = np.where(bv >= from_sil, bi, npit)
        bp_ = int(np.argmax(sp))
        to_s = max(sp[bp_] - 0.15, ss)
        back[f, npit] = bp_ if sp[bp_] - 0.15 > ss else npit
        score = np.r_[to_p + em[f], to_s + silent[f]]
    path = np.empty(nfr, np.int32)
    path[-1] = int(np.argmax(score))
    for f in range(nfr - 1, 0, -1):
        path[f - 1] = back[f, path[f]]
    pitch = np.where(path < npit, pitches[np.minimum(path, npit - 1)], -1)
    # octave clean-up against the local median of the line
    voiced = pitch > 0
    if voiced.sum() < 20:
        return {}
    vp = pitch[voiced].astype(float)
    k = 60
    med = np.array([np.median(vp[max(0, i - k):i + k]) for i in range(0, len(vp))])
    vp = vp - 12 * np.round((vp - med) / 12)
    pitch[voiced] = vp.astype(int)
    # grid steps: the 2048-window grid is 2 frames behind the 4096-window frames
    gf = grid - (N - ANFFT) / (2 * AHOP)
    nb = grid.shape[0]
    out, cur = {}, None
    for b in range(nb):
        for st in range(16):
            f0 = int(round(gf[b, st]))
            f1 = int(round(gf[b, st + 1])) if st < 15 else (int(round(gf[b + 1, 0])) if b + 1 < nb else f0 + 4)
            seg = pitch[max(0, f0):max(f0 + 1, min(nfr, f1))]
            seg = seg[seg > 0]
            if len(seg) * 2 < max(1, f1 - f0):
                cur = None
                continue
            vals, cnt = np.unique(seg, return_counts=True)
            m = int(vals[np.argmax(cnt)])
            onset = env[min(len(env) - 1, max(0, int(round(grid[b, st]))))] > 0.5
            if cur is not None and cur[2] == m and not onset:
                out[cur[0]][cur[1]][2] += 1                  # same note keeps sounding
            else:
                out.setdefault(b, []).append([st, m, 1])
                cur = (b, len(out[b]) - 1, m)
    # flatten, and only move the register if it is outside what the lead synth plays well
    notes = [(b, n) for b in sorted(out) for n in out[b]]
    allp = [n[1] for _, n in notes]
    if not allp:
        return {}
    med = float(np.median(allp))
    shift = 0 if 55 <= med <= 82 else 12 * round((67 - med) / 12)   # keep the original octave if playable
    res = {}
    for b, (st, m, ln) in notes:
        res.setdefault(int(b), []).append((int(st), int(m + shift), int(ln)))
    return res


def analyze_audio(a, sr=ASR):
    if len(a) < sr * 10:
        raise ValueError('the file is shorter than 10 seconds')
    a = a / max(1e-6, np.abs(a).max())
    nfr = 1 + (len(a) - ANFFT) // AHOP
    fr = sr / AHOP
    win = np.hanning(ANFFT).astype(np.float32)
    freqs = np.fft.rfftfreq(ANFFT, 1 / sr)
    masks = {'kick': (freqs >= 35) & (freqs < 130), 'snare': (freqs >= 1800) & (freqs < 5000),
             'hat': (freqs >= 7000) & (freqs < 11000)}
    # chroma: each bin is split between its two nearest pitch classes, and every class is averaged over
    # its own bins, so classes that happen to own more FFT bins don't win by default
    # semitone spectrum MIDI 52..103 (each bin split between its two nearest semitones, averaged per semitone)
    cm = (freqs > 190) & (freqs < 4200)
    mf = 12 * np.log2(freqs[cm] / 440.0) + 69 - 52
    lo_, fr_ = np.floor(mf).astype(int), mf - np.floor(mf)
    C = np.zeros((cm.sum(), 52), np.float32)
    ok_ = (lo_ >= 0) & (lo_ < 51)
    C[np.arange(cm.sum())[ok_], lo_[ok_]] += 1 - fr_[ok_]
    C[np.arange(cm.sum())[ok_], lo_[ok_] + 1] += fr_[ok_]
    C /= np.maximum(1e-9, C.sum(0, keepdims=True))
    PC = np.zeros((28, 12), np.float32)
    PC[np.arange(28), (52 + np.arange(28)) % 12] = 1
    flux = np.zeros(nfr, np.float32)
    bfl = {k: np.zeros(nfr, np.float32) for k in masks}
    chroma = np.zeros((nfr, 12), np.float32)
    loud = np.zeros(nfr, np.float32)
    prev, off = None, np.arange(ANFFT)
    for s in range(0, nfr, 1024):                     # STFT in slices to keep memory small
        idx = np.arange(s, min(nfr, s + 1024))
        S = np.abs(np.fft.rfft(a[idx[:, None] * AHOP + off[None, :]] * win, axis=1)).astype(np.float32)
        L = np.log1p(100 * S)
        d = np.maximum(np.diff(np.vstack([L[:1] if prev is None else prev, L]), axis=0), 0)
        prev = L[-1:]
        flux[idx] = d.sum(1)
        for k, mk in masks.items():
            bfl[k][idx] = d[:, mk].sum(1)
        # harmonic part only: a median over time keeps sustained tones and drops drum hits,
        # then each frame's spectral floor is removed so only real pitch peaks count
        T = np.sqrt(S[:, cm])
        H = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(T, ((4, 4), (0, 0)), 'edge'), 9, axis=0), axis=2)
        H = np.maximum(H - np.median(H, axis=1, keepdims=True) * 1.5, 0)
        with np.errstate(all='ignore'):
            X = H @ C
        # harmonic summation: a real note owns its octave, twelfth and double octave, an overtone doesn't
        sal = X[:, :28] + 0.6 * X[:, 12:40] + 0.45 * X[:, 19:47] + 0.3 * X[:, 24:52]
        with np.errstate(all='ignore'):
            chroma[idx] = sal @ PC
        loud[idx] = S.sum(1)
    env = _novelty(flux)
    frames = np.arange(len(env))

    # tempo: autocorrelation picks the ballpark, a beat-comb search refines tempo and phase
    n2 = 1 << int(np.ceil(np.log2(len(env) * 2)))
    E = np.fft.rfft(env - env.mean(), n2)
    ac = np.fft.irfft(np.abs(E) ** 2, n2)[:len(env)]
    lags = np.arange(int(60 * fr / 200), int(60 * fr / 60) + 1)
    bp = 60 * fr / lags
    bpm0 = bp[np.argmax(ac[lags] * np.exp(-0.5 * (np.log2(bp / 120) / 0.9) ** 2))]

    def comb(bpm):
        P = 60 * fr / bpm
        k = np.arange(int((len(env) - 1 - P) / P))
        best = (-1.0, 0.0)
        for ph in np.linspace(0, P, 24, endpoint=False):
            v = np.interp(ph + k * P, frames, env).mean()
            if v > best[0]:
                best = (v, ph)
        return best

    cands = np.arange(bpm0 * 0.97, bpm0 * 1.03, 0.05)
    res = [comb(b) for b in cands]
    i = int(np.argmax([r[0] for r in res]))
    bpm, phase = float(cands[i]), res[i][1]
    while bpm > 160:
        bpm /= 2
    while bpm < 70:
        bpm *= 2
    P = 60 * fr / bpm

    # bars: the beat (of 4) with the most kick is the downbeat
    kenv, senv, henv = _novelty(bfl['kick']), _novelty(bfl['snare']), _novelty(bfl['hat'])
    # downbeat: chords change on the "1", so prefer the beat offset where the harmony changes most;
    # fall back to the beat with the most kick when the harmony is too static to tell
    beats = phase + np.arange(int((len(env) - phase) / P)) * P
    kb = np.interp(beats, frames, kenv)
    bch = np.array([chroma[int(t0):int(t0 + P)].sum(0) for t0 in beats])
    bch /= np.maximum(1e-9, np.linalg.norm(bch, axis=1, keepdims=True))
    chg = np.r_[0.0, 1 - (bch[1:] * bch[:-1]).sum(1)]
    hscore = np.array([chg[j::4].mean() for j in range(4)])
    kscore = np.array([kb[j::4].mean() for j in range(4)])
    if hscore.max() > 1.5 * np.median(hscore) and hscore.max() > 0.05:
        o = int(np.argmax(hscore + 0.1 * kscore / max(1e-9, kscore.max())))
    else:
        o = int(np.argmax(kscore))
    bar0 = phase + o * P
    bar0 -= int(bar0 // (4 * P)) * 4 * P
    nb = int((len(env) - 1 - bar0) // (4 * P))
    if nb < 4:
        raise ValueError('could not find enough bars')
    grid = bar0 + np.arange(nb)[:, None] * 4 * P + np.arange(16)[None, :] * P / 4

    def at(x):
        mx = np.maximum(np.maximum(x, np.r_[x[1:], 0]), np.r_[0, x[:-1]])
        return np.interp(grid, frames, mx)

    K, Sn, Hh = at(kenv), at(senv), at(henv)
    bar_loud = np.array([loud[int(b0):int(b0 + 4 * P)].mean() for b0 in grid[:, 0]])
    busy = bar_loud >= np.median(bar_loud)

    def pattern(M, ghost=True):
        s = M[busy].mean(0)
        if s.max() < 0.08 or s.max() < 1.6 * np.median(s):
            return '.' * 16                                # no clear repeating hits in this band
        s = s / s.max()
        return ''.join('x' if v >= 0.55 else (str(min(9, int(v * 10))) if ghost and v >= 0.3 else '.') for v in s)

    kick, snare, hat = pattern(K, ghost=False), pattern(Sn), pattern(Hh)
    if 'x' not in kick:
        kick = 'x...x...x...x...' if bpm >= 110 else 'x.......x.x.....'
    clap = ''.join('x' if c == 'x' else '.' for c in snare)
    hs = Hh[busy].mean(0)
    ohat = ''.join('x' if i % 4 == 2 else '.' for i in range(16)) if hs[2::4].mean() > 1.4 * hs[0::4].mean() else '.' * 16
    drums = [kick, snare, clap, hat, ohat]

    # key + chords: for every key, fit each bar with that key's diatonic seventh chords and keep the key
    # that explains the bars best (Krumhansl profiles only break ties between relative major/minor)
    bc = np.array([chroma[int(b0):int(b0 + 4 * P)].sum(0) for b0 in grid[:, 0]])
    bc = bc / np.maximum(1e-9, np.linalg.norm(bc, axis=1, keepdims=True))
    tot = bc.sum(0)
    best = None
    for r in range(12):
        for mode, prof in (('major', KS_MAJOR), ('aeolian', KS_MINOR)):
            sc_ = SCALES[mode]
            tmpl = np.zeros((7, 12))
            for d in range(7):
                for kk, wt in ((0, 1.0), (2, 0.8), (4, 0.6), (6, 0.25)):
                    tmpl[d, (r + sc_[(d + kk) % 7]) % 12] += wt
            tmpl /= np.linalg.norm(tmpl, axis=1, keepdims=True)
            fit = bc @ tmpl.T
            score = fit.max(1).sum() + 0.5 * np.corrcoef(np.roll(prof, r), tot)[0, 1]
            if best is None or score > best[0]:
                best = (score, r, mode, list(np.argmax(fit, axis=1)))
    _, key, mode, degs = best

    # arrangement: 8-bar blocks labelled by loudness and whether the kick is playing
    blocks = [(i, min(nb, i + 8)) for i in range(0, nb, 8)]
    be = np.array([bar_loud[a_:b_].mean() for a_, b_ in blocks])
    be = (be - be.min()) / max(1e-9, be.max() - be.min())
    bk = np.array([K[a_:b_].mean() for a_, b_ in blocks])
    secs, bar_sec = [], []
    for i, ((a_, b_), e_, kv) in enumerate(zip(blocks, be, bk)):
        ko = kv >= 0.45 * bk.max()
        if i == 0 and (e_ < 0.5 or not ko):
            sec = ('INTRO', 'KH' if ko else 'CH', .5, .05)
        elif i == len(blocks) - 1 and e_ < 0.6:
            sec = ('OUTRO', 'KHB' if ko else 'CH', 0, .6)
        elif not ko or e_ < 0.3:
            sec = ('BREAK', 'CL', .4, .15)
        elif e_ >= 0.7:
            sec = ('HOOK', 'KSHOBCL', 0, 0)
        else:
            sec = ('GROOVE', 'KSHBC', 0, 0)
        bars = b_ - a_
        if secs and (bars < 4 or (secs[-1]['name'] == sec[0] and sec[0] in ('HOOK', 'GROOVE', 'BREAK'))):
            secs[-1]['bars'] += bars
        else:
            secs.append(dict(name=sec[0], bars=bars, layers=sec[1], f0=sec[2], f1=sec[3]))
        bar_sec += [secs[-1]['name']] * bars

    def common_loop(names):
        grams = collections.Counter(tuple(degs[i:i + 4]) for i in range(0, nb - 3, 4) if bar_sec[i] in names)
        return list(grams.most_common(1)[0][0]) if grams else None

    progA = common_loop(('GROOVE', 'BREAK', 'INTRO', 'OUTRO')) or common_loop(('HOOK',)) or degs[:4]
    progB = common_loop(('HOOK',)) or progA
    melody = extract_melody(a, sr, grid, env)
    return dict(bpm=bpm, key=int(key), mode=mode, drums=drums, progA=[int(x) for x in progA],
                progB=[int(x) for x in progB], sections=secs, bars=nb, degs=[int(x) for x in degs],
                melody=melody)


def song_from_analysis(an, seed):
    """A BLIP song with the file's tempo, key, chords, drum groove and arrangement, in BLIP's own sounds."""
    bpm = an['bpm']
    if bpm >= 115:
        base = 'FRENCH' if an['mode'] == 'major' else 'HOUSE'
    elif bpm >= 98:
        base = 'SYNTH'
    else:
        base = 'LOFI' if an['mode'] == 'major' else 'DREAM'
    s = Song(seed, base)
    s.style = 'REMIX'
    s.S = dict(s.S, drums={t: [an['drums'][t]] for t in range(5)})
    s.bpm = int(round(bpm))
    s.key, s.mode = an['key'], an['mode']
    s.scale = SCALES[s.mode]
    s.progA, s.progB = list(an['progA']), list(an['progB'])
    s.sections = [dict(x) for x in an['sections']]
    s.total = sum(x['bars'] for x in s.sections)
    s.title = re.sub(r'[^A-Z0-9 \-]', ' ', ('REMIX ' + an.get('name', '').upper()))[:17].strip()
    s.source = an
    s.melody = an.get('melody') or None
    return s


def _analyze_proc(path, q):
    try:
        res = analyze_audio(decode_audio(path))
        res['name'] = os.path.splitext(os.path.basename(path))[0]
        q.put(res)
    except Exception as ex:
        q.put({'error': str(ex)[:120]})
