"""The real-time audio engine: sequencer clock, synth voices, buses, master effects, noise, mixing."""
import collections
import math
import time

import numpy as np

from .constants import FFT_N, NAMES, NT, SR, STEPS, SYN
from .dsp import make_drums, mtof, note_name, osc, svf_run
from .styles import INST
from .song import Pattern
from .voice import VoiceBox
from .player import FilePlayer, PLAYER_FX
from .radio import Radio


class SynthVoice:
    __slots__ = ('f', 'age', 'gate', 'vel', 'p1', 'p2', 'p3', 'p', 'bus')

    def __init__(self, midi, gate, vel, p=None, bus=0, delay=0):
        self.f = mtof(midi)
        self.age = -delay
        self.gate = gate
        self.vel = vel
        self.p1 = self.p2 = self.p3 = 0.0
        self.p = p
        self.bus = bus


class Engine:
    SNAP = ['bpm', 'swing', 'wave', 'cut', 'res', 'env', 'drv', 'atk', 'rel', 'det', 'sub', 'dly', 'fxa']

    def __init__(self):
        self.samples = make_drums()
        self.vox_on, self.voicebox, self.vvoices = False, VoiceBox(), []
        self.player, self.pset, self.band, self.psnap = None, 1, False, None
        self.bst1, self.bst2 = [0.0, 0.0], [0.0, 0.0]
        self.gains = [0.9, 0.7, 0.5, 0.35, 0.3]
        self.pats = [Pattern() for _ in range(4)]
        self.pi = 0
        self.pats[0].seed(
            ["X...x...x...x...", "....x.......x...", "............x...",
             "X.x.x.x.X.x.x.x.", "..............x."],
            {0: 45, 3: 52, 6: 57, 8: 48, 10: 55, 12: 52, 14: 60}, accents=(0, 8))
        self.pats[1].seed(
            ["X..x..x...x..x..", "....x.......x..x", "....x.......x...",
             "xxxxxxxxxxxxxxxx", "..x...x...x...x."],
            {0: 45, 2: 45, 3: 57, 6: 52, 8: 48, 10: 48, 11: 55, 14: 60}, accents=(0, 3, 8))
        self.pats[2].seed(
            ["X.........x.....", "........x.......", "........x.......",
             "x.x.x.x.x.x.x.xx", "......x.......x."],
            {0: 41, 4: 48, 7: 53, 10: 56, 12: 60}, accents=(0, 7))
        self.radio = None
        self.snap = None
        self.muted = [False] * NT
        self.solo = set()
        self.bpm = 112
        self.swing = 0.0
        self.wave = 0
        self.cut, self.res, self.env, self.drv = 0.5, 0.35, 0.45, 0.15
        self.atk, self.rel, self.det, self.sub = 0.05, 0.35, 0.3, 0.3
        self.dly, self.vol = 0.25, 0.8
        self.oct = 3
        self.playing = False
        self.rec = False
        self.cur = 0
        self.disp = -1
        self.countdown = 0.0
        self.tick = 0
        self.elapsed = 0.0
        self.last_note = 57
        self.pending = []
        self.voices = []
        self.dvoices = []  # [track, pos, gain mult]
        self.svf = [0.0, 0.0]
        self.psvf = [0.0, 0.0]
        self.pcut = 0.6
        self.cut_s = self.cut
        self.fenv = 0.0
        self.duck, self.duck_depth = 0.0, 0.0
        self.vinyl, self.dust = 0.0, False
        self.dz = np.zeros(4)
        self.rng = np.random.default_rng()
        self.dbuf = np.zeros(2 * SR, dtype=np.float32)
        self.wi = 0
        self.level = 0.0
        self.tl = [0.0] * NT
        self.ring = np.zeros(FFT_N, dtype=np.float32)
        self.cpu = 0.0
        self.clip_t = 0.0
        self.log = collections.deque(maxlen=200)
        self.fx = [False] * 5   # filter, crush, stutter, tape, reverb
        self.fxa = 0.5
        self.rfx_amt = [0.5] * 5
        self.hist = np.zeros(16384, dtype=np.float32)
        self.stut, self.spos = None, 0
        self.tbuf, self.tw, self.tph = np.zeros(8192, dtype=np.float32), 0, 0.0
        self.fst, self.ffc = [0.0, 0.0], 7000.0
        self.cd = [1557, 1617, 1491, 1422]
        self.cbuf = [np.zeros(d, dtype=np.float32) for d in self.cd]
        self.cw = [0] * 4
        self.noise, self.noise_lvl, self.ng, self.nkind = 0, 0.35, 0.0, 1
        self.nst = [0.0, 0.0, 0.0, 0.0]
        t = np.arange(90) / SR
        self.drip = (np.sin(2 * np.pi * 2600 * t) * np.exp(-t * 900)).astype(np.float32)
        self.dtail = np.zeros(89)

    @property
    def cur_pat(self):
        return self.radio.main.pat if self.radio else self.pats[self.pi]

    @property
    def pat(self):
        return self.cur_pat.rows

    @property
    def acc(self):
        return self.cur_pat.acc

    @property
    def vel(self):
        return self.cur_pat.vel

    def audible(self, t):
        return not self.muted[t] and (not self.solo or t in self.solo)

    def base(self):
        return 60.0 / self.bpm / 4 * SR

    def step_len(self, i):
        return self.base() * (1 + self.swing if i % 2 == 0 else 1 - self.swing)

    def play(self):
        self.playing = True
        self.cur = 0
        self.countdown = 0.0
        self.tick = 0
        self.elapsed = 0.0

    def stop(self):
        self.playing = False
        self.disp = -1
        for v in self.voices:
            v.gate = min(v.gate, max(v.age, 0))

    # ---------- radio ----------
    def radio_on(self):
        self.snap = {k: getattr(self, k) for k in self.SNAP}
        self.snap['fx'] = self.fx[:]
        self.snap['muted'], self.snap['solo'] = self.muted[:], set(self.solo)
        self.muted, self.solo = [False] * NT, set()
        self.stop()
        self.radio = Radio(self)
        self.play()

    def player_on(self, path):
        if self.radio:
            self.radio_off()
        self.stop()
        if self.player is None:
            self.psnap = (self.fx[:], list(self.rfx_amt), self.vinyl, self.dust, self.duck_depth)
        else:
            self.player.close()
        self.player = FilePlayer(path)
        self.set_preset(self.pset)

    def player_off(self):
        if self.player is None:
            return
        self.player.close()
        self.player = None
        self.band = False
        fx, amt, self.vinyl, self.dust, self.duck_depth = self.psnap
        self.fx[:], self.rfx_amt = fx, amt

    def set_preset(self, i):
        self.pset = i % len(PLAYER_FX)
        _, on, amt, vinyl, band = PLAYER_FX[self.pset]
        self.fx[:], self.rfx_amt, self.vinyl, self.band = list(on), list(amt), vinyl, band
        self.dust, self.duck_depth = False, 0.0

    def am_radio(self, x):
        """Telephone/AM band (≈320 Hz - 3.2 kHz) with a little drive."""
        y1, self.bst1 = svf_run(x, 2 * math.sin(math.pi * 3200 / SR), 1.0, self.bst1)
        y2, self.bst2 = svf_run(y1, 2 * math.sin(math.pi * 320 / SR), 1.0, self.bst2)
        return np.tanh((y1 - y2) * 2.2) * 0.8

    def radio_off(self):
        self.radio = None
        self.stop()
        for k in self.SNAP:
            setattr(self, k, self.snap[k])
        self.fx[:] = self.snap['fx']
        self.muted, self.solo = self.snap['muted'], self.snap['solo']
        self.vinyl, self.dust, self.duck_depth = 0.0, False, 0.0

    # ---------- triggering ----------
    def trig_note(self, m, gate, acc=False):
        self.voices.append(SynthVoice(m, gate, 1.15 if acc else 0.8))
        self.fenv = max(self.fenv, 1.5 if acc else 1.0)
        if len(self.voices) > 28:
            self.voices.pop(0)

    def trig_inst(self, m, gate, preset, bus, delay=0, vel=1.0):
        self.voices.append(SynthVoice(m, gate, vel, INST[preset], bus, delay))
        if len(self.voices) > 28:
            self.voices.pop(0)

    def record(self, m):
        el = self.step_len(self.disp) - self.countdown
        tgt = self.disp if el < self.step_len(self.disp) / 2 else self.cur
        self.pat[SYN][tgt] = m

    def fire(self, i):
        if self.radio:
            self.radio.on_step(i)
            layers = self.radio.layers()
        else:
            layers = [(self.cur_pat, 1.0, True, True)]
        names = []
        for P, g, low, lead in layers:
            for t in range(SYN):
                if P.rows[t][i] and self.audible(t) and (low or t != 0):
                    self.dvoices.append([t, 0, (1.3 if P.acc[t][i] else 1.0) * P.vel[t][i] * g])
                    names.append(NAMES[t] + ("!" if P.acc[t][i] else ""))
                    if t == 0:
                        self.duck = max(self.duck, g)
            m = P.rows[SYN][i]
            if lead and m and self.audible(SYN):
                self.trig_note(m, int(self.step_len(i) * P.glen[SYN][i]), bool(P.acc[SYN][i]))
                names.append(note_name(m))
        if names:
            self.log.append(f"{self.tick:04d} S{i + 1:02d} " + " ".join(names))

    # ---------- synthesis ----------
    def vrel(self, v):
        rel = v.p['rel'] if v.p else 0.02 + self.rel ** 2 * 0.9
        return (rel * 1.8 + 0.05) * SR

    def voice_block(self, v, n):
        p = v.p
        if p is None:
            w1 = w2 = self.wave
            r2, l2, sub = 1 + self.det * 0.02, 0.7, self.sub
            atk, dec, sus = 0.002 + self.atk ** 2 * 0.4, 0.12, 0.55
            rel, gain = 0.02 + self.rel ** 2 * 0.9, 0.5
        else:
            w1, w2, r2, l2, sub = p['w1'], p['w2'], p['r2'], p['l2'], p['sub']
            atk, dec, sus, rel, gain = p['atk'], p['dec'], p['sus'], p['rel'], p['gain']
        ar = np.arange(1, n + 1) / SR
        p1 = v.p1 + v.f * ar
        p2 = v.p2 + v.f * r2 * ar
        p3 = v.p3 + v.f * 0.5 * ar
        v.p1, v.p2, v.p3 = p1[-1] % 1.0, p2[-1] % 1.0, p3[-1] % 1.0
        tt = (v.age + np.arange(n)) / SR
        env = np.clip(tt / atk, 0.0, 1.0) * (sus + (1 - sus) * np.exp(-np.maximum(tt - atk, 0) / dec))
        env *= np.exp(-np.maximum(tt - v.gate / SR, 0) / (rel / 4))
        v.age += n
        o = osc(w1, p1) + l2 * osc(w2, p2)
        if sub:
            o = o + sub * 1.2 * osc(2, p3)
        return o * env * v.vel * gain

    def run_svf(self, x):
        self.cut_s += (self.cut - self.cut_s) * 0.25
        cs = min(1.0, self.cut_s + self.env * 0.55 * self.fenv)
        fc = min(100 * 60 ** cs, 7000)
        y, self.svf = svf_run(x, 2 * math.sin(math.pi * fc / SR), 2 * (1 - self.res * 0.92), self.svf)
        return y

    def tape(self, x, n, amt):
        L = len(self.tbuf)
        wp = self.tw + np.arange(n)
        self.tbuf[wp % L] = x
        tt = self.tph + np.arange(n) / SR
        d = np.maximum(400 + amt * 260 * (np.sin(2 * np.pi * 0.7 * tt) + 0.3 * np.sin(2 * np.pi * 6.1 * tt)), 2)
        r = wp - d
        i0 = np.floor(r).astype(np.int64)
        fr = r - i0
        y = self.tbuf[i0 % L] * (1 - fr) + self.tbuf[(i0 + 1) % L] * fr
        self.tw = (self.tw + n) % L
        self.tph += n / SR
        return np.tanh(y * 1.4) * 0.85

    def vinyl_noise(self, n):
        r = self.rng
        hiss = np.convolve(r.standard_normal(n + 2), [0.25, 0.5, 0.25], 'valid') * 0.006
        crackle = (r.random(n) < 0.0012) * r.standard_normal(n) * 0.22
        return (hiss + crackle) * self.vinyl

    def noise_block(self, n):
        """Focus noise layered on top of the music. Fades in/out instead of clicking."""
        target = self.noise_lvl if self.noise else 0.0
        if target == 0 and self.ng < 1e-4:
            self.ng = 0.0
            return None
        if self.noise:
            self.nkind = self.noise
        g = np.linspace(self.ng, target, n)
        self.ng = target
        w = self.rng.standard_normal(n)
        kind = self.nkind
        if kind == 1:
            y = w * 0.12
        else:
            b0, b1, b2, br = self.nst
            out = [0.0] * n
            if kind == 3:
                for k, x in enumerate(w.tolist()):
                    br = (br + 0.02 * x) / 1.02
                    out[k] = br * 1.2
            else:
                for k, x in enumerate(w.tolist()):
                    b0 = 0.99765 * b0 + x * 0.0990460
                    b1 = 0.96300 * b1 + x * 0.2965164
                    b2 = 0.57000 * b2 + x * 1.0526913
                    out[k] = (b0 + b1 + b2 + x * 0.1848) * 0.05
            self.nst = [b0, b1, b2, br]
            y = np.array(out)
            if kind == 4:   # rain: soft pink bed + random droplets
                imp = (self.rng.random(n) < 0.004) * self.rng.uniform(-0.7, 0.7, n)
                z = np.convolve(imp, self.drip)
                z[:len(self.dtail)] += self.dtail
                self.dtail = z[n:].copy()
                y = y * 0.55 + z[:n]
        return y * g

    def master_fx(self, x, n):
        f = self.fx
        a = self.rfx_amt if (self.radio or self.player is not None) else [self.fxa] * 5
        ar = np.arange(n)
        self.hist[:-n] = self.hist[n:]
        self.hist[-n:] = x
        if f[2]:
            if self.stut is None:
                L = max(64, int(self.base() * (1, 0.5, 0.25, 0.125)[min(3, int(a[2] * 4))]))
                self.stut, self.spos = self.hist[-L:].copy(), 0
            x = self.stut[(self.spos + ar) % len(self.stut)]
            self.spos = (self.spos + n) % len(self.stut)
        else:
            self.stut = None
        if f[3]:
            x = self.tape(x, n, a[3])
        if f[1]:
            k = 1 + int(a[1] * 14)
            q = 2.0 ** (round(16 - a[1] * 12) - 1)
            y = np.repeat(x[::k], k)[:n] if k > 1 else x
            x = np.round(y * q) / q
        if f[0] and a[0] > 0.05:
            fc = 7000 * 0.03 ** max(0.0, (a[0] - 0.15) / 0.85)
            self.ffc += (fc - self.ffc) * 0.3
            y, self.fst = svf_run(x, 2 * math.sin(math.pi * self.ffc / SR), 1.1, self.fst)
            x = x + (y - x) * min(1.0, (a[0] - 0.05) / 0.2)
        feed = x * 0.3 if f[4] else 0.0
        fb = 0.78 + 0.15 * a[4]
        wet = np.zeros(n)
        for k, D in enumerate(self.cd):
            idx = (self.cw[k] + ar) % D
            y = self.cbuf[k][idx]
            self.cbuf[k][idx] = feed + y * fb
            self.cw[k] = (self.cw[k] + n) % D
            wet += y
            if not f[4]:
                self.cbuf[k][np.abs(self.cbuf[k]) < 1e-7] = 0.0
        return x + wet * 0.35

    def cb(self, out, frames, tinfo, status):
        t0 = time.perf_counter()
        while self.pending:
            kind, v = self.pending.pop(0)
            if kind == 'd':
                self.dvoices.append([v, 0, 1.0])
            else:
                self.trig_note(v, int(0.28 * SR))
        self.tl = [x * 0.88 for x in self.tl]
        bus = [np.zeros(frames), np.zeros(frames), np.zeros(frames)]  # lead/synth, chords, bass
        dr = np.zeros(frames)
        vx = np.zeros(frames)
        dk = np.ones(frames)
        tau = 0.11 * SR
        pos = 0
        while pos < frames:
            if self.playing and self.countdown <= 0:
                self.disp = self.cur
                self.fire(self.cur)
                sl = self.step_len(self.cur)
                self.countdown += sl
                self.elapsed += sl / SR
                self.tick += 1
                self.cur = (self.cur + 1) % STEPS
            seg = frames - pos
            if self.playing:
                seg = min(seg, max(1, math.ceil(self.countdown)))
            for v in self.voices:
                bus[v.bus][pos:pos + seg] += self.voice_block(v, seg)
            for dv in self.dvoices:
                s = self.samples[dv[0]][dv[1]:dv[1] + seg]
                g = self.gains[dv[0]] * dv[2]
                dr[pos:pos + len(s)] += s * g
                if len(s):
                    self.tl[dv[0]] = max(self.tl[dv[0]], float(np.abs(s).max()) * g)
                dv[1] += seg
            self.dvoices = [d for d in self.dvoices if d[1] < len(self.samples[d[0]])]
            for vv in self.vvoices:            # [buffer, position (negative = still waiting), gain]
                buf, p0, g = vv
                off = max(0, -p0)
                if off < seg:
                    st = max(0, p0)
                    k = min(seg - off, len(buf) - st)
                    if k > 0:
                        vx[pos + off:pos + off + k] += buf[st:st + k] * g
                vv[1] = p0 + seg
            self.vvoices = [vv for vv in self.vvoices if vv[1] < len(vv[0])]
            self.voices = [v for v in self.voices if v.age - v.gate < self.vrel(v)]
            if self.duck_depth > 0 and self.duck > 1e-3:
                dk[pos:pos + seg] = 1 - self.duck_depth * self.duck * np.exp(-np.arange(seg) / tau)
                self.duck *= math.exp(-seg / tau)
            if self.playing:
                self.countdown -= seg
            pos += seg
        sy, pd, bs = bus
        if any(self.svf) or np.any(sy):
            sy = self.run_svf(sy)
        if any(self.psvf) or np.any(pd):
            fc = min(100 * 60 ** self.pcut, 7000)
            pd, self.psvf = svf_run(pd, 2 * math.sin(math.pi * fc / SR), 1.4, self.psvf)
        self.fenv *= math.exp(-frames / SR / 0.18)
        sy = np.tanh(sy * (1 + self.drv * 5)) / (1 + self.drv * 1.2)
        self.tl[SYN] = max(self.tl[SYN], float(np.abs(sy).max()) * 0.45)
        ar = np.arange(frames)
        d = int(min(max(3 * self.base(), frames), len(self.dbuf) - 1))
        wet = self.dbuf[(self.wi - d + ar) % len(self.dbuf)]
        self.dbuf[(self.wi + ar) % len(self.dbuf)] = sy + vx * 0.7 + wet * 0.45
        self.wi = (self.wi + frames) % len(self.dbuf)
        sy = sy + wet * self.dly
        if self.dust:
            z = np.concatenate([self.dz, dr])
            self.dz = dr[-4:].copy()
            dr = np.convolve(z, np.array([1, 2, 3, 2, 1]) / 9, 'valid') * 0.9
        x = np.tanh(sy * 0.45 + (pd + bs) * dk + dr + vx * 0.9)
        if self.player is not None:
            x = x + self.player.read(frames) * 0.85
            if self.band:
                x = self.am_radio(x)
        if self.vinyl > 0:
            x = x + self.vinyl_noise(frames)
        mix = np.tanh(self.master_fx(x, frames)) * self.vol   # soft limiter
        nz = self.noise_block(frames)
        if nz is not None:
            mix = mix + nz
        out[:, 0] = mix
        out[:, 1] = mix
        pk = float(np.abs(mix).max())
        self.level = max(self.level * 0.92, pk)
        if pk > 0.97:
            self.clip_t = time.time()
        self.ring[:-frames] = self.ring[frames:]
        self.ring[-frames:] = mix
        self.cpu = self.cpu * 0.9 + (time.perf_counter() - t0) / (frames / SR) * 0.1
