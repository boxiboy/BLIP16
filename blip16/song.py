"""Patterns (what the sequencer plays) and generated songs (one bar at a time)."""
import collections
import math
import random

from .constants import NOTE, NT, PENTA, STEPS, SYN
from .styles import SCALES, STYLES, WORDS_A, WORDS_B, chord_name


class Pattern:
    def __init__(self):
        self.rows = [[0] * STEPS for _ in range(NT)]
        self.acc = [[0] * STEPS for _ in range(NT)]
        self.vel = [[1.0] * STEPS for _ in range(NT)]
        self.glen = [[0.85] * STEPS for _ in range(NT)]   # note length in steps (synth row)

    def copy_from(self, o):
        self.rows = [r[:] for r in o.rows]
        self.acc = [r[:] for r in o.acc]
        self.vel = [r[:] for r in o.vel]
        self.glen = [r[:] for r in o.glen]

    def seed(self, drums, notes, accents=()):
        for t, spec in enumerate(drums):
            for i, c in enumerate(spec):
                self.rows[t][i] = 1 if c in 'xX' else 0
                self.acc[t][i] = 1 if c == 'X' else 0
        for i, m in notes.items():
            self.rows[SYN][i] = m
            self.acc[SYN][i] = 1 if i in accents else 0


class Song:
    """One generated song. Writes one bar at a time into its own pattern + event list."""

    def __init__(self, seed, style=None):
        self.seed = seed
        R = self.r = random.Random(seed)
        self.style = style or R.choice(list(STYLES))
        S = self.S = STYLES[self.style]
        self.key = R.randrange(12)
        self.mode = R.choice(S['modes'])
        self.scale = SCALES[self.mode]
        self.bpm = R.randint(*S['bpm'])
        self.swing = round(R.uniform(*S['swing']), 3)
        self.progA = (R.choice(S['progs']) * 4)[:4]
        self.progB = (R.choice(S['progs']) * 4)[:4]
        self.ninth = {d: R.random() < S['ninth'] for d in range(7)}
        self.sections = []
        for name, bars, layers, f0, f1 in S['form']:
            if bars >= 8 and R.random() < 0.25:
                bars *= 2
            self.sections.append(dict(name=name, bars=bars, layers=layers, f0=f0, f1=f1))
        self.total = sum(s['bars'] for s in self.sections)
        self.title = f"{R.choice(WORDS_A)} {R.choice(WORDS_B)}"
        self.bar, self.sec_i, self.bs = -1, 0, 0
        self.chord_now = self.chord_next = ''
        self.motif = self.mvar = None
        self.drum_sel = {}
        self.stab_rhythm = R.choice([[3, 6, 11], [2, 6, 10, 14], [0, 3, 6, 10, 13]])
        self.bass_rhythm = R.choice([[2, 6, 10, 14], [0, 3, 6, 10, 14], [2, 5, 10, 13]])
        self.pat = Pattern()
        self.events = {}
        self.filt, self.pcut_now = 0.0, S['pcut']

    def keyname(self):
        return f"{NOTE[self.key]} {'MAJOR' if self.mode == 'major' else 'MINOR'}"

    def section_at(self, bar):
        for sec in self.sections:
            if bar < sec['bars']:
                return sec, bar
            bar -= sec['bars']
        return self.sections[-1], 0

    def apply(self, e, tempo=True):
        """Load this song's sound settings into the engine."""
        S = self.S
        if tempo:
            e.bpm, e.swing = self.bpm, self.swing
        for k, v in S['lead'].items():
            setattr(e, k, v)
        e.fx[:] = S['fx_on']
        e.rfx_amt = list(S['fx_amt'])
        e.vinyl, e.dust, e.duck_depth, e.pcut = S['vinyl'], S['dust'], S['duck'], S['pcut']

    def chord(self, deg):
        sc = self.scale
        ks = (0, 2, 4, 6, 8) if self.ninth[deg % 7] else (0, 2, 4, 6)
        tones = [48 + self.key + sc[(deg + k) % 7] + 12 * ((deg + k) // 7) for k in ks]
        voiced = sorted(53 + (t - 53) % 12 for t in tones)
        return tones[0], tones, voiced

    def lead_note(self, idx):
        pent = [0, 2, 4, 7, 9] if self.mode == 'major' else PENTA
        base = 60 + self.key
        if base > 66:
            base -= 12
        return base + 12 * (idx // 5) + pent[idx % 5]

    def snap(self, m, tones):
        pcs = {t % 12 for t in tones}
        for d in (0, -1, 1, -2, 2):
            if (m + d) % 12 in pcs:
                return m + d
        return m

    def make_motif(self):
        R, dens = self.r, self.S['density']
        steps = [s for s in range(0, 32, 2) if R.random() < dens * 2]
        steps += [s for s in range(1, 32, 2) if R.random() < dens * 0.4]
        steps = sorted(set(steps)) or [0, 8]
        idx, mot = R.randint(4, 6), []
        for s in steps:
            idx = max(1, min(8, idx + R.choice([-2, -1, -1, 0, 1, 1, 2])))
            mot.append((s, idx))
        return mot

    def vary(self, mot):
        R, out = self.r, []
        for s, idx in mot:
            if R.random() < 0.12:
                continue
            if R.random() < 0.25:
                idx = max(1, min(8, idx + R.choice([-1, 1])))
            out.append((s, idx))
        return out

    def fill(self, rows, vel, sec, nxt):
        R, kind = self.r, self.S['fill']
        if kind == 'lofi':
            for i in (13, 14, 15):
                if R.random() < 0.5:
                    rows[1][i], vel[1][i] = 1, R.uniform(0.35, 0.6)
            if R.random() < 0.5:
                for i in range(12, 16):
                    rows[0][i] = 0
        elif kind == 'house':
            if 'K' in nxt['layers'] and sec['name'] in ('BUILD', 'BREAK', 'INTRO'):
                for i in range(8, 16):
                    rows[1][i], vel[1][i] = 1, 0.3 + 0.7 * (i - 8) / 7
            else:
                rows[4][14] = 1
        else:
            for k, i in enumerate((12, 13, 14, 15)):
                rows[1][i], vel[1][i] = 1, 0.5 + k * 0.17

    def next_bar(self):
        self.bar = min(self.bar + 1, self.total - 1)   # a deck mixed out early just holds its outro
        b, si = self.bar, 0
        while b >= self.sections[si]['bars']:
            b -= self.sections[si]['bars']
            si += 1
        sec = self.sections[si]
        self.sec_i, self.bs = si, b
        nxt = self.sections[si + 1] if si + 1 < len(self.sections) else None
        R, S, L = self.r, self.S, sec['layers']
        if b == 0:
            self.drum_sel = {t: R.choice(S['drums'][t]) for t in range(5)}
            if 'L' in L and (self.motif is None or R.random() < 0.5):
                self.motif = self.make_motif()
            if S['comp'] == 'stabs':
                self.stab_rhythm = R.choice([[3, 6, 11], [2, 6, 10, 14], [0, 3, 6, 10, 13]])
        if b % 4 == 0 and self.motif:
            self.mvar = self.vary(self.motif)
        prog = self.progB if sec['name'] in ('HOOK', 'CHORUS', 'DROP') else self.progA
        root, tones, voiced = self.chord(prog[b % 4])
        nroot, ntones, _ = self.chord(prog[(b + 1) % 4])
        self.chord_now, self.chord_next = chord_name(tones), chord_name(ntones)

        rows, acc, vel = self.pat.rows, self.pat.acc, self.pat.vel
        for t in range(5):
            on = 'KSSHO'[t] in L
            tpl = self.drum_sel[t]
            for i in range(STEPS):
                c, hit, a, v = tpl[i], False, 0, 1.0
                if on and c in 'xX':
                    hit, a, v = True, int(c == 'X'), (R.uniform(0.75, 1.0) if t >= 3 else 1.0)
                elif on and c.isdigit():
                    hit, v = R.random() < int(c) / 10, R.uniform(0.4, 0.65)
                rows[t][i], acc[t][i], vel[t][i] = int(hit), a, v
        if nxt is not None and b == sec['bars'] - 1:
            self.fill(rows, vel, sec, nxt)
        elif b % 4 == 3 and 'O' in L and R.random() < 0.4:
            rows[4][14] = 1
        for i in range(STEPS):
            rows[SYN][i], acc[SYN][i], self.pat.glen[SYN][i] = 0, 0, 0.85
        melody = getattr(self, 'melody', None)
        if melody is not None:                 # remix: the original's melody, note for note
            for st, m, ln in melody.get(self.bar, ()):
                rows[SYN][st] = m
                self.pat.glen[SYN][st] = max(0.5, ln - 0.15)
        elif 'L' in L and self.mvar:
            for s, idx in self.mvar:
                if s // 16 == b % 2:
                    m = self.lead_note(idx)
                    rows[SYN][s % 16] = self.snap(m, tones) if s % 8 == 0 else m

        ev = self.events = collections.defaultdict(list)
        if 'C' in L:
            if S['comp'] == 'keys':
                if R.random() < 0.35:
                    ev[0].append(('chord', voiced, 9.5, 0.018))
                    ev[10].append(('chord', voiced, 6, 0.012))
                else:
                    ev[0].append(('chord', voiced, 15, 0.02))
            elif S['comp'] == 'stabs':
                for s in self.stab_rhythm:
                    ev[s].append(('chord', voiced, 1.2, 0.0))
            else:
                ev[0].append(('chord', voiced, 16.5, 0.0))
        if 'B' in L:
            br = 31 + (root - 31) % 12
            if S['bassline'] == 'lofi':
                ev[0].append(('bass', br, 6))
                if R.random() < 0.6:
                    ev[10].append(('bass', R.choice([br, br + 7, br + 12]), 3))
                if R.random() < 0.3:
                    ev[14].append(('bass', 31 + (nroot - 31) % 12 - 1, 1.5))
            elif S['bassline'] == 'house':
                for s in self.bass_rhythm:
                    ev[s].append(('bass', br + (12 if s >= 13 and R.random() < 0.3 else 0), 1.5))
            else:
                for s in range(0, 16, 2):
                    ev[s].append(('bass', br + (12 if (s // 2) % 2 else 0), 1.6))
        self.filt = sec['f0'] + (sec['f1'] - sec['f0']) * (b / max(1, sec['bars'] - 1))
        if (S['fill'] == 'house' and nxt is not None and b == sec['bars'] - 1
                and 'K' in nxt['layers'] and sec['name'] in ('BUILD', 'BREAK')):
            ev[12].append(('stut', 1, 0))
        if S.get('lfo'):
            self.pcut_now = S['pcut'] + 0.15 * math.sin(2 * math.pi * self.bar / 16)
