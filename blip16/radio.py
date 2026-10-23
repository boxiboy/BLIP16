"""The radio host: picks songs, beat-matches and crossfades them (DJ mode), tempo control, voice timing."""
import math
import random

from .constants import SR, STEPS
from .styles import STYLES, key_dist
from .song import Song
from .voice import VOICE_HOOKS, text_to_syllables


class Radio:
    """Two-deck radio host. With DJ on, the next song is beat-matched and crossfaded in over the
    last bars of the current one: tempo glides, equal-power fade, kick + bass swap at the midpoint."""

    def __init__(self, eng):
        self.e = eng
        self.skip = False
        self.songs = 0
        self.dj = True
        self.vcount = 0   # bar counter used to line pre-rendered syllables up with bars
        self.forced = None   # a song (e.g. a remix) to play next instead of a generated one
        self.mul, self.mul_b, self.auto, self.nominal = 1.0, 1.0, False, 100.0   # listener's tempo control
        self.b, self.tbar, self.T, self.p, self.swapped = None, 0, 8, 0.0, False
        self.decks = []
        self.history = []
        self.a = self.pick(None)
        self.a.apply(eng)
        self.nominal = self.a.bpm
        self.announce(self.a, "ON AIR")

    def __getattr__(self, name):          # song info (title, bar, sections...) comes from deck A
        if name == 'a':
            raise AttributeError(name)
        return getattr(self.a, name)

    @property
    def main(self):
        return self.b if self.b is not None and self.p >= 0.5 else self.a

    def queue_song(self, song):
        """Mix into this song on the next bar (DJ on) or cut to it (DJ off)."""
        self.forced = song
        self.skip = True

    def pick(self, near):
        if self.forced is not None:
            s, self.forced = self.forced, None
            return s
        if near is None:
            return Song(random.randrange(1 << 16))
        # a DJ picks something that mixes well (close tempo, related key) but keeps the genres moving
        if random.random() < 0.45:
            style = random.choice([st for st in STYLES if st != near.style])
            cands = [Song(random.randrange(1 << 16), style) for _ in range(10)]
        else:
            cands = [Song(random.randrange(1 << 16)) for _ in range(24)]
        recent = self.history[-2:]
        return min(cands, key=lambda s: abs(s.bpm - near.bpm) + 3 * key_dist(s.key, near.key)
                   + (12 if s.style in recent else 0) + random.uniform(0, 10))

    def roll_mul(self, nominal):
        """AUTO tempo: every new song gets its own random speed (kept inside 60..200 BPM)."""
        lo, hi = max(0.8, 60.0 / nominal), min(1.3, 200.0 / nominal)
        return random.uniform(lo, max(lo, hi))

    def announce(self, s, what):
        self.songs += 1
        self.history.append(s.style)
        self.e.log.append(f"{what}: {s.title} / {s.style} {s.keyname()} {s.bpm}BPM")

    def mix_len(self, s):
        return s.S['mix']

    def bars_to_mix(self):
        a = self.a
        return a.total - a.bar - 1 - self.mix_len(a)

    def next_bar(self):
        e, a = self.e, self.a
        if self.b is not None:
            self.tbar += 1
            if self.tbar >= self.T or self.skip:
                self.skip = False
                self.a, self.b = self.b, None
                self.mul = self.mul_b
                self.a.apply(e)
                e.log.append(f"MIX DONE >> {self.a.title}")
                self.a.next_bar()
            else:
                a.next_bar()
                self.b.next_bar()
        elif self.dj and (self.skip or a.total - a.bar - 1 <= self.mix_len(a)):
            self.T = 4 if self.skip else self.mix_len(a)
            self.skip = False
            self.b, self.tbar, self.swapped = self.pick(a), 0, False
            self.mul_b = self.roll_mul(self.b.bpm) if self.auto else self.mul
            self.announce(self.b, "MIXING IN")
            a.next_bar()
            self.b.next_bar()
        elif self.skip or a.bar + 1 >= a.total:
            self.skip = False
            self.a = self.pick(a)
            self.a.apply(e)
            if self.auto:
                self.mul = self.mul_b = self.roll_mul(self.a.bpm)
            self.announce(self.a, "ON AIR")
            self.a.next_bar()
        else:
            a.next_bar()
        self.p = self.tbar / self.T if self.b is not None else 0.0
        m = self.main
        e.fx[0] = self.b is None and m.filt > 0.05
        e.rfx_amt[0] = m.filt
        e.fx[2] = False
        e.pcut = m.pcut_now
        self.plan_voice()

    def plan_voice(self):
        """At the end of each 4-bar cycle, write the next sung line: words, flow on the grid, a melody that
        follows the chords. Syllables go to the worker one bar before they are needed."""
        e = self.e
        self.vcount += 1
        if not e.vox_on:
            return
        s, vb = self.main, e.voicebox
        nb = s.bar + 1
        if nb >= s.total - 1 or nb % 2 != 0:
            return
        R = vb.rng
        sec, _ = s.section_at(nb)
        # a line on bars 1-2 of each 4-bar cycle, sometimes an answer on bars 3-4, sometimes silence
        chance = (0.85 if nb % 4 == 0 else 0.45) * (0.6 if sec['name'] in ('INTRO', 'OUTRO') else 1.0)
        if R.random() > chance:
            return
        line, chop = vb.next_line(s)
        syls = text_to_syllables(line)
        if not syls:
            return
        pos = vb.flow(syls, R, chop)
        pcs = tuple(sorted({(s.key + d) % 12 for d in s.scale}))
        contour = R.choice(['arch', 'fall', 'rise', 'chant'])
        i0, N = R.randint(3, 6), max(1, len(syls) - 1)
        jobs, prev_v = [], None
        for k, (syl, p) in enumerate(zip(syls, pos)):
            if contour == 'arch':
                idx = i0 + round(2 * math.sin(math.pi * k / N))
            elif contour == 'fall':
                idx = i0 + 2 - round(3 * k / N)
            elif contour == 'rise':
                idx = i0 - 1 + round(3 * k / N)
            else:
                idx = i0
            if not chop and R.random() < 0.25:
                idx += R.choice([-1, 1])
            m = s.lead_note(max(1, min(8, idx)))
            if syl['stress'] or p % 4 == 0 or k == len(syls) - 1:
                sec_b, bb = s.section_at(min(nb + p // 16, s.total - 1))
                _, tones, _ = s.chord((s.progB if sec_b['name'] in VOICE_HOOKS else s.progA)[bb % 4])
                m = s.snap(m, tones)
            nxt = pos[k + 1] if k + 1 < len(pos) else min(p + R.choice([4, 6, 8]), 32)
            n = int(e.base() * max(1, nxt - p) * 0.95)
            jobs.append((self.vcount + 1 + p // 16, p % 16, (m, syl, n, vb.mode, pcs, prev_v)))
            prev_v = syl['v']
        vb.submit(jobs)

    def on_step(self, i):
        e = self.e
        if i == 0:
            self.next_bar()
        if self.b is not None:
            p = self.p = (self.tbar + i / STEPS) / self.T
            s = p * p * (3 - 2 * p)
            self.nominal = self.a.bpm + (self.b.bpm - self.a.bpm) * s
            mul = self.mul + (self.mul_b - self.mul) * s
            e.swing = self.a.swing + (self.b.swing - self.a.swing) * s
            if p >= 0.5 and not self.swapped:
                self.swapped = True
                self.b.apply(e, tempo=False)
                e.log.append("DJ: BASS SWAP")
            ga, gb = math.cos(p * math.pi / 2), math.sin(p * math.pi / 2)
            self.decks = [(self.a, ga, p < 0.5), (self.b, gb, p >= 0.5)]
        else:
            self.decks = [(self.a, 1.0, True)]
            self.nominal, mul = self.a.bpm, self.mul
        e.bpm = max(60, min(200, int(round(self.nominal * mul))))
        for song, g, low in self.decks:
            for ev in song.events.get(i, ()):
                if ev[0] == 'chord':
                    _, notes, gate, strum = ev
                    for k, m in enumerate(notes):
                        e.trig_inst(m, int(gate * e.base()), song.S['chord'], 1, int(k * strum * SR), g)
                elif ev[0] == 'bass' and low:
                    e.trig_inst(ev[1], int(ev[2] * e.base()), song.S['bass'], 2)
                elif ev[0] == 'stut' and self.b is None:
                    e.fx[2] = True
        if e.vox_on:
            # syllables start one step early, delayed so the vowel (not the consonant) lands on the grid
            nk, ns = (self.vcount, i + 1) if i + 1 < STEPS else (self.vcount + 1, 0)
            item = e.voicebox.take(nk, ns)
            if item is not None:
                buf, pre = item
                e.vvoices.append([buf, -max(0, int(e.step_len(i)) - pre), 0.4])

    def set_tempo(self, bpm):
        bpm = max(60, min(200, int(bpm)))
        self.mul = self.mul_b = bpm / max(1.0, self.nominal)
        self.e.bpm = bpm
        return bpm

    def layers(self):
        """(pattern, gain, kick allowed, lead allowed) for each audible deck."""
        m = self.main
        return [(s.pat, g, low, s is m) for s, g, low in self.decks]
