"""The singing voice: English text -> syllables, a formant singer, and vocoder / talkbox / autotune
treatments. Rendering runs in a separate process so it can never stall the audio thread."""
import multiprocessing
import os
import queue
import random
import re
import threading

import numpy as np

from .constants import SR
from .dsp import mtof


# ---------- voice: formant singer + vocoder / talkbox / autotune treatments ----------
FORMANTS = {'a': (730, 1090, 2440), 'e': (530, 1840, 2480), 'i': (270, 2290, 3010),
            'o': (570, 840, 2410), 'u': (300, 870, 2240)}


VOWEL_DIGRAPHS = {'ee': 'i', 'ea': 'i', 'oo': 'u', 'ou': 'o', 'ow': 'o', 'ai': 'e', 'ay': 'e', 'oa': 'o',
                  'ie': 'i', 'ey': 'e', 'au': 'o', 'aw': 'o', 'oy': 'o', 'ue': 'u', 'ui': 'u'}


CONS_DIGRAPHS = {'sh': 'SH', 'ch': 'SH', 'th': 'F', 'ph': 'F', 'ng': 'N', 'ck': 'P', 'wh': 'W', 'gh': ''}


CONS_KIND = {'s': 'S', 'z': 'S', 'x': 'S', 'c': 'P', 'f': 'F', 'v': 'F', 'h': 'H',
             'p': 'P', 't': 'P', 'k': 'P', 'q': 'P', 'b': 'B', 'd': 'B', 'g': 'B',
             'm': 'N', 'n': 'N', 'l': 'L', 'r': 'R', 'w': 'W', 'j': 'J', 'y': 'J'}


# noise consonants: (centre Hz or None for flat, log-width, seconds, level)
NOISE_CONS = {'S': (6200, 0.35, 0.085, 0.45), 'SH': (3000, 0.45, 0.095, 0.5), 'F': (None, 0, 0.07, 0.18),
              'H': ('vowel', 0, 0.06, 0.3)}


# voiced consonants glide into / out of the vowel from these formant targets
GLIDE_CONS = {'N': (250, 1100, 2300), 'L': (360, 1300, 2600), 'R': (420, 1250, 1650),
              'W': (300, 700, 2200), 'J': (280, 2200, 2900)}


FUNCTION_WORDS = {'the', 'a', 'an', 'in', 'on', 'to', 'of', 'my', 'with', 'and', 'it', 'is', 'at', 'for',
                  'your', 'our', 'into', 'me', 'you', 'we', 'i', 'so', 'let'}


VOICE_HOOKS = ('HOOK', 'CHORUS', 'DROP')


VOICE_MODES = ['VOCODER', 'TALKBOX', 'AUTOTUNE', 'SINGER']


VOICE_MODE_INFO = ["16-BAND VOCODER: SPEECH ON A SAW CARRIER", "TALKBOX: SLIDING FORMANTS + DRIVE",
                   "AUTOTUNE: HARD PITCH SNAP TO THE SONG'S KEY", "SINGER: NATURAL VOICE, BREATH + VIBRATO"]


RANDOM_LINES = '~ RANDOM LINES ~'


# original lines and a small word bank written for this project (not lyrics from any real song)
VOICE_PHRASES = ["signal received", "we glow in the dark", "lights on, bass down", "power on, all systems go",
                 "dance in the machine", "electric heart beating", "the night belongs to us",
                 "pulse and static", "robots dream in neon", "feel the circuit sing"]


W_NOUN = ['night', 'light', 'signal', 'heart', 'city', 'sky', 'dream', 'fire', 'star', 'wave', 'rhythm',
          'motion', 'neon', 'echo', 'satellite', 'machine', 'dancefloor', 'sunrise', 'shadow', 'circuit',
          'body', 'music', 'sound', 'moon', 'ocean', 'engine', 'summer', 'window', 'memory', 'feeling']


W_VERB = ['move', 'glow', 'shine', 'feel', 'dance', 'fly', 'run', 'burn', 'rise', 'spin', 'drift', 'groove',
          'hold', 'fall', 'breathe', 'shake', 'turn', 'light up']


W_ADJ = ['electric', 'golden', 'endless', 'digital', 'silver', 'wild', 'slow', 'bright', 'cosmic',
         'midnight', 'neon', 'gentle', 'brand new', 'crystal']


W_ADV = ['tonight', 'forever', 'again', 'together', 'all night', 'higher', 'closer', 'slowly', 'right now']


LINE_TEMPLATES = ["{v} {adv}", "{adj} {n}", "we {v} in the {n}", "feel the {n}", "{v} with me {adv}",
                  "{adj} {n}, {adj} {n}", "{v}, {v}, {v}", "never stop the {n}", "{n} in my {n}",
                  "here comes the {n}", "let the {n} {v}", "you and me {adv}", "{v} into the {n}",
                  "lost in the {n}", "{n} of the {n}", "{adj} {n} {adv}"]


def make_line(rng):
    pick = lambda xs: rng.choice(xs)
    t = pick(LINE_TEMPLATES)
    while '{' in t:
        t = (t.replace('{n}', pick(W_NOUN), 1).replace('{v}', pick(W_VERB), 1)
             .replace('{adj}', pick(W_ADJ), 1).replace('{adv}', pick(W_ADV), 1))
    return t


def text_to_syllables(text):
    """Crude English letters -> syllables: onset consonants, vowel, coda consonants, stress, word end."""
    syls = []
    for word in re.findall(r"[a-z]+", text.lower()):
        has_v = any(c in 'aeiou' for c in word)
        toks, i = [], 0
        while i < len(word):
            two, c = word[i:i + 2], word[i]
            if two in VOWEL_DIGRAPHS:
                toks.append(('V', VOWEL_DIGRAPHS[two]))
                i += 2
            elif two in CONS_DIGRAPHS:
                if CONS_DIGRAPHS[two]:
                    toks.append(('C', CONS_DIGRAPHS[two]))
                i += 2
            elif c in 'aeiou' or (c == 'y' and (not has_v or (i == len(word) - 1 and toks and toks[-1][0] == 'C'))):
                toks.append(('V', 'i' if c == 'y' else c))
                i += 1
            elif c in CONS_KIND:
                toks.append(('C', CONS_KIND[c]))
                i += 1
            else:
                i += 1
        if (len(toks) >= 3 and word.endswith('e') and toks[-1] == ('V', 'e') and toks[-2][0] == 'C'
                and any(t[0] == 'V' for t in toks[:-2])):
            toks.pop()          # silent final e
        vi = [k for k, t in enumerate(toks) if t[0] == 'V']
        start, first = 0, len(syls)
        for n_, k in enumerate(vi):
            nxt = vi[n_ + 1] if n_ + 1 < len(vi) else None
            end = len(toks) if nxt is None else k + 1 + (1 if nxt - k - 1 >= 2 else 0)
            seg, kk = toks[start:end], k - start
            syls.append(dict(on=[t[1] for t in seg[:kk]], v=seg[kk][1], co=[t[1] for t in seg[kk + 1:]],
                             stress=(n_ == 0 and word not in FUNCTION_WORDS), end=(nxt is None)))
            start = end
        if len(syls) > first and len(vi) == 1 and word in FUNCTION_WORDS:
            syls[first]['stress'] = False
    if syls and not any(s['stress'] for s in syls):
        syls[0]['stress'] = True
    return syls


def _res(F, B, f):
    """Magnitude of one formant resonance at frequency f (cascade formant synthesiser style)."""
    return F * F / np.sqrt((F * F - f * f) ** 2 + (B * f) ** 2)


def _shaped_noise(rng, n, centre, width, formants=None):
    w = rng.standard_normal(n)
    W = np.fft.rfft(w)
    f = np.maximum(np.fft.rfftfreq(n, 1 / SR), 1.0)
    if formants is not None:
        mask = _res(formants[0], 90, f) * _res(formants[1], 110, f) * _res(formants[2], 160, f)
    elif centre is None:
        mask = np.clip(f / 1500, 0, 1)
    else:
        mask = np.exp(-(np.log2(f / centre) / width) ** 2)
    x = np.fft.irfft(W * mask, n)
    return x / max(1e-9, x.std())


def _speech(syl, n, fc, rng, prev_v=None, talkbox=False, breath=0.06, twin=True):
    """One sung syllable. fc = per-sample pitch (Hz). Returns (signal, vowel_onset_index).

    Voiced part: glottal-like source (-6 dB/oct) through three time-varying formant resonances that glide
    in from the previous vowel or from the onset consonant (coarticulation), plus breath noise.
    Consonants: shaped noise for s/sh/f/h, burst + aspiration for p/t/k, soft burst for b/d/g,
    formant glides for m/n/l/r/w/y."""
    out = np.zeros(n)
    cap = int(n * 0.35)                       # consonants never eat more than a third of the note
    s0 = 0
    glide_on = None
    hard = False
    for k in syl['on']:
        if k in NOISE_CONS:
            cen, wid, d, lv = NOISE_CONS[k]
            ln = min(int(d * SR), max(0, cap - s0))
            if ln > 8:
                fm_ = FORMANTS[syl['v']] if cen == 'vowel' else None
                x = _shaped_noise(rng, ln, None if cen == 'vowel' else cen, wid, fm_)
                tt = np.arange(ln) / SR
                out[s0:s0 + ln] += x * lv * 0.3 * np.clip(tt / 0.015, 0, 1) * np.clip((ln / SR - tt) / 0.02, 0, 1)
                s0 += ln
        elif k in ('P', 'B'):
            ln = min(int((0.012 if k == 'B' else 0.018) * SR), max(0, cap - s0))
            if ln > 8:
                tt = np.arange(ln) / SR
                out[s0:s0 + ln] += _shaped_noise(rng, ln, 2500, 1.0) * np.exp(-tt * 180) * (0.25 if k == 'B' else 0.45)
                s0 += ln
            if k == 'P':                          # aspiration before voicing
                ln = min(int(0.04 * SR), max(0, cap - s0))
                if ln > 8:
                    tt = np.arange(ln) / SR
                    out[s0:s0 + ln] += _shaped_noise(rng, ln, None, 0, FORMANTS[syl['v']]) * 0.12 * np.exp(-tt * 40)
                    s0 += ln
            hard = True
        elif k in GLIDE_CONS:
            glide_on = GLIDE_CONS[k]
    tail = []
    for k in syl['co']:
        if k in NOISE_CONS:
            tail.append((k, min(int(NOISE_CONS[k][2] * SR * 0.8), n // 5)))
        elif k in ('P', 'B'):
            tail.append((k, min(int(0.02 * SR), n // 6)))
    glide_co = next((GLIDE_CONS[k] for k in syl['co'] if k in GLIDE_CONS), None)
    e0 = max(s0 + int(0.05 * SR), n - sum(ln for _, ln in tail))
    nv = e0 - s0
    pre = s0
    if nv > 16:
        x = np.arange(nv) / SR
        L = nv / SR
        V = np.array(FORMANTS[syl['v']], float)
        if glide_on is not None:
            start, tg = np.array(glide_on, float), 0.055
            pre = s0 + int(0.03 * SR)
        elif talkbox:
            start, tg = np.array((300.0, 900.0, 2300.0)), 0.06
        elif prev_v is not None:
            start, tg = np.array(FORMANTS[prev_v], float), 0.05
        else:
            start, tg = V, 0.05
        a = np.clip(x / tg, 0, 1)[None, :]
        Ft = start[:, None] + (V - start)[:, None] * (a * a * (3 - 2 * a))
        if glide_co is not None:
            b = np.clip((x - (L - 0.07)) / 0.07, 0, 1)[None, :]
            Ft = Ft + (np.array(glide_co, float)[:, None] - Ft) * b
        Bw = (60, 80, 110) if talkbox else (80, 100, 150)
        fv = fc[s0:e0]
        fm = float(fv.mean())
        h = np.arange(1, max(3, int(min(30, 5000 / fm))) + 1)
        ph = 2 * np.pi * np.cumsum(fv) / SR

        def layer(phase):
            acc = np.zeros(nv)
            for k in range(0, len(h), 6):
                hs = h[k:k + 6]
                hf = hs[:, None] * fm
                amp = _res(Ft[0], Bw[0], hf) * _res(Ft[1], Bw[1], hf) * _res(Ft[2], Bw[2], hf) / hs[:, None]
                acc += (amp * np.sin(hs[:, None] * phase[None, :])).sum(0)
            return acc

        voiced = layer(ph) + (0.6 * layer(ph * 1.005) if twin else 0)
        voiced /= max(1e-9, np.abs(voiced).max())
        if breath:
            voiced += _shaped_noise(rng, nv, None, 0, tuple(V)) * breath
        att = 0.006 if hard else 0.018
        env = np.clip(x / att, 0, 1) * np.clip((L - x) / 0.05, 0, 1) * (1 - 0.25 * x / max(L, 1e-3))
        if glide_on is not None and glide_on == GLIDE_CONS['N']:
            env *= 0.45 + 0.55 * np.clip((x - 0.03) / 0.04, 0, 1)
        if glide_co is not None and glide_co == GLIDE_CONS['N']:
            env *= 1 - 0.5 * np.clip((x - (L - 0.07)) / 0.07, 0, 1)
        out[s0:e0] += voiced * env * 0.85
    c0 = e0
    for k, ln in tail:
        ln = min(ln, n - c0)
        if ln <= 8:
            continue
        tt = np.arange(ln) / SR
        if k in NOISE_CONS:
            cen, wid, d, lv = NOISE_CONS[k]
            x_ = _shaped_noise(rng, ln, None if cen == 'vowel' else cen, wid, FORMANTS[syl['v']] if cen == 'vowel' else None)
            out[c0:c0 + ln] += x_ * lv * 0.3 * np.clip(tt / 0.01, 0, 1) * np.clip((ln / SR - tt) / 0.025, 0, 1)
        else:
            out[c0:c0 + ln] += _shaped_noise(rng, ln, 2500, 1.0) * np.exp(-tt * 200) * 0.2
        c0 += ln
    return out, pre


def singer_curve(m, n, rng):
    """Natural pitch: small scoop into the note, delayed vibrato, a little jitter."""
    t = np.arange(n) / SR
    jit = np.convolve(rng.standard_normal(n // 64 + 2), np.ones(3) / 3, 'same')
    jit = np.interp(np.arange(n) / 64, np.arange(len(jit)), jit) * 0.05
    pitch = (m - 0.5 * np.exp(-t / 0.05) + 0.28 * np.clip((t - 0.18) / 0.15, 0, 1)
             * np.sin(2 * np.pi * 5.3 * t + rng.uniform(0, 6.28)) + jit)
    return 440.0 * 2 ** ((pitch - 69) / 12)


def autotune_curve(m, n, pcs, rng):
    """A 'human' contour (scoop, vibrato, drift) hard-snapped to the key: the stair-step warble.
    Empty pcs = no snapping (raw contour)."""
    t = np.arange(n) / SR
    pitch = m - 1.1 * np.exp(-t / 0.07) + 0.35 * np.clip(t / 0.15, 0, 1) * np.sin(
        2 * np.pi * 5.6 * t + rng.uniform(0, 6.28)) + 0.12 * np.sin(2 * np.pi * 1.7 * t + rng.uniform(0, 6.28))
    if pcs:
        notes = np.array([x for x in range(36, 100) if x % 12 in pcs], float)
        snapped = np.empty(n)
        for a in range(0, n, 2000):
            snapped[a:a + 2000] = notes[np.abs(pitch[a:a + 2000, None] - notes[None, :]).argmin(1)]
        k = max(2, int(0.006 * SR))
        pitch = np.convolve(np.pad(snapped, (k, k), 'edge'), np.ones(k) / k, 'same')[k:-k]
    return 440.0 * 2 ** ((pitch - 69) / 12)


def vocode(mod, carrier, bands=16):
    """Classic channel vocoder: each band's envelope from the speech drives the same band of the carrier."""
    n = len(mod)
    X, C = np.fft.rfft(mod), np.fft.rfft(carrier)
    f = np.maximum(np.fft.rfftfreq(n, 1 / SR), 1.0)
    k = max(2, int(0.006 * SR))
    out = np.zeros(n)
    for fc in np.geomspace(140, 7000, bands):
        w = np.exp(-(np.log2(f / fc) / 0.3) ** 2)
        a = np.abs(np.fft.irfft(X * w, n))
        c = np.cumsum(np.r_[0.0, a])
        env = np.r_[np.full(k // 2, c[k] / k), (c[k:] - c[:-k]) / k, np.full(n - (len(c) - k) - k // 2, c[-1] / k)][:n]
        out += np.fft.irfft(C * w, n) * env * 2.2
    hp = np.fft.irfft(X * (f > 4200), n)                 # sibilance bypass so s/t/sh stay intelligible
    return out + hp * 0.5


def _carrier(f0, n):
    t = np.arange(n) / SR
    saw = lambda f: 2 * ((f * t) % 1.0) - 1
    return (saw(f0) + 0.8 * saw(f0 * 1.007) + 0.6 * saw(f0 * 0.994)
            + 0.5 * np.where(((f0 / 2 * t) % 1.0) < 0.5, 1.0, -1.0))


def render_syllable(m, syl, n, mode=0, pcs=(), prev_v=None):
    """One syllable at MIDI pitch m in one of VOICE_MODES -> (float32 buffer, vowel onset index)."""
    rng = np.random.default_rng(int(m * 10) + n)
    f0 = mtof(m)
    if mode == 2:
        out, pre = _speech(syl, n, autotune_curve(m, n, pcs, rng), rng, prev_v, breath=0.03)
    elif mode == 1:
        out, pre = _speech(syl, n, np.full(n, f0), rng, prev_v, talkbox=True, breath=0.0, twin=False)
        out = out * 1.3            # the shared soft-clip below adds the talkbox grit
    elif mode == 0:
        mod, pre = _speech(syl, n, np.full(n, 150.0), rng, prev_v, breath=0.04, twin=False)
        out = vocode(mod, _carrier(f0, n))
    else:
        out, pre = _speech(syl, n, singer_curve(m, n, rng), rng, prev_v, breath=0.08)
    out = np.tanh(out * 1.4) / 1.2
    return (out / max(1e-6, np.abs(out).max()) * 0.9).astype(np.float32), int(pre)


def _voice_proc(jobs, results):
    """Runs in its own process so heavy rendering can never stall the audio thread (no shared GIL)."""
    parent = os.getppid()
    while True:
        try:
            item = jobs.get(timeout=2)
        except queue.Empty:
            if os.getppid() != parent:      # the app is gone: don't linger as an orphan
                return
            continue
        if item is None:
            return
        key, st, args = item
        try:
            results.put((key, st, render_syllable(*args)))
        except Exception:
            pass


class VoiceBox:
    """What to sing (random lines, a fixed phrase or your text), how it flows over the beat,
    and a worker process that renders syllables ahead of time."""

    def __init__(self):
        self.phrases = [RANDOM_LINES] + list(VOICE_PHRASES)
        self.i, self.mode = 0, 0
        self.rng = random.Random()
        self.line = ''          # the line being sung right now (shown in the UI)
        self.hooks = {}         # one recurring hook line per song
        self.ready = {}
        try:
            if os.environ.get('BLIP_VOICE_THREAD'):
                raise RuntimeError('thread mode requested')
            ctx = multiprocessing.get_context('spawn')
            self.jobs, self.res = ctx.Queue(), ctx.Queue()
            self.proc = ctx.Process(target=_voice_proc, args=(self.jobs, self.res), daemon=True)
            self.proc.start()
            threading.Thread(target=self._collect, daemon=True).start()
        except Exception:               # fall back to a worker thread if processes are unavailable
            self.jobs = queue.Queue()
            threading.Thread(target=self._work, daemon=True).start()

    @property
    def text(self):
        return self.phrases[self.i]

    @property
    def syls(self):
        return text_to_syllables(self.line or self.text)

    def select(self, i):
        self.i = i % len(self.phrases)
        self.line = '' if self.text == RANDOM_LINES else self.text
        self.ready.clear()

    def set_custom(self, text):
        if text not in self.phrases:
            self.phrases.append(text)
        self.select(self.phrases.index(text))

    def next_line(self, song):
        """Random mode: the song's hook comes back about half the time, otherwise a fresh line;
        sometimes the hook's first word is chopped and repeated."""
        R = self.rng
        if self.text != RANDOM_LINES:
            self.line = self.text
            return self.line, False
        hook = self.hooks.setdefault(id(song), make_line(R))
        r = R.random()
        if r < 0.15:
            word = hook.replace(',', '').split()[0]
            self.line = ' '.join([word] * R.choice([3, 4]))
            return self.line, True
        self.line = hook if r < 0.6 else make_line(R)
        return self.line, False

    @staticmethod
    def flow(syls, rng, chop=False):
        """Grid positions (16ths, up to 2 bars) for each syllable: stressed ones on the beat, now and then
        pushed a 16th early; unstressed ones fill the 8ths/16ths in between."""
        if chop:
            gap = rng.choice([2, 3, 4])
            return [k * gap for k in range(len(syls))]
        fast = len(syls) > 9
        step, pos = (rng.choice([0, 0, 0, 2]) if len(syls) <= 6 else 0), []
        for s in syls:
            if s['stress']:
                t = step if step % 4 == 0 else step + (4 - step % 4)
                if t - step > 2:
                    t = step + (step % 2)
                if t % 4 == 0 and t > step and rng.random() < 0.22:
                    t -= 1
            else:
                t = step
            pos.append(t)
            step = t + (1 if fast and not s['stress'] else 2)
        if pos[-1] > 30:
            pos = [int(p * 30 / pos[-1]) for p in pos]
            for k in range(1, len(pos)):
                pos[k] = max(pos[k], pos[k - 1] + 1)
        return pos

    def submit(self, jobs):
        if jobs:
            low = min(j[0] for j in jobs)
            for k in [k for k in list(self.ready) if k[0] < low - 1]:
                self.ready.pop(k, None)
        for key, st, args in jobs:
            self.jobs.put((key, st, args))

    def _collect(self):
        while True:
            key, st, item = self.res.get()
            self.ready[(key, st)] = item

    def _work(self):
        while True:
            key, st, args = self.jobs.get()
            try:
                self.ready[(key, st)] = render_syllable(*args)
            except Exception:       # a bad syllable must never kill the worker
                pass

    def take(self, key, st):
        return self.ready.pop((key, st), None)
