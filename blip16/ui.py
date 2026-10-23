"""Terminal user interface (curses): studio, radio and player screens, visualizer, input handling."""
import curses
import locale
import math
import multiprocessing
import os
import queue
import random
import re
import sys
import time

import numpy as np

from .constants import (
    BLOCK,
    DW,
    FA_KEYS,
    FFT_N,
    FONT,
    FX_NAMES,
    NAMES,
    NOISES,
    NT,
    PARAMS,
    PENTA,
    PIANO,
    PTN_NAMES,
    PW,
    PX,
    SR,
    STEPS,
    SYN,
    TAGLINES,
    THEMES,
    THEME_ORDER,
    VIZ_NAMES,
    WAVES,
    WAVE_ART,
)
from .dsp import make_bayer, make_cloud, note_name
from .styles import chord_name
from .voice import RANDOM_LINES, VOICE_MODES, VOICE_MODE_INFO
from .analysis import _analyze_proc, song_from_analysis
from .player import PLAYER_FX, VOCAL_MODES, parse_path
from .engine import Engine


def dbar(v, n):
    """Dotted bitmap bar with half-cell resolution."""
    e = int(round(max(0.0, min(1.0, v)) * n * 2))
    s = '⣿' * (e // 2) + ('⡇' if e % 2 else '')
    return s + '⣀' * (n - len(s))


class App:
    def __init__(self, scr, eng):
        self.s = scr
        self.e = eng
        self.cy, self.cx = 0, 0
        self.sel = 0
        self.pressed = {}
        self.ox = 0
        self.hits = []
        self.msg, self.msg_t = "", 0.0
        self.theme_i = 0
        self.vmode, self.inv, self.full, self.help = 1, False, False, False
        self.typing, self.tbuf, self.tfor = False, '', 'voice'
        self.remix = None   # analysis running in a background process
        self.vgain, self.vu, self.ripples, self.viz_labels = 1.0, [0.0, 0.0], [], []
        self.pers, self.thr_cache, self.last_my = {}, {}, 0
        self.stars = np.random.default_rng(11).random((60, 2))
        self.spec = np.zeros(28)
        self.peak = np.zeros(28)
        self.win = np.hanning(FFT_N)
        edges = np.geomspace(40, 16000, 29)
        self.bins = np.maximum((edges / (SR / FFT_N)).astype(int), 1)
        self.tilt = 3.0 * np.log2(np.sqrt(edges[:-1] * edges[1:]) / 1000.0)
        self.bayer = make_bayer(8)
        self.cloud = make_cloud(256)
        self.rowrand = np.random.default_rng(5).random(512)
        self.wts = np.array([[1, 8], [2, 16], [4, 32], [64, 128]])
        self.apply_theme()
        self.s.bkgd(' ', curses.color_pair(1))
        for line in ("BLIP-16 FW 2.1 BOOT", "AUDIO OUT 44100HZ OK", "RADIO START"):
            self.e.log.append(line)

    def apply_theme(self):
        th = THEMES[THEME_ORDER[self.theme_i]]
        rich = curses.COLORS >= 256
        c = (lambda n: n) if rich else (lambda n: th['base'])
        bk = 16 if rich else 0   # 16 is pure #000000; 0 follows the terminal theme and can be grey
        cp = curses.init_pair
        for pid, key in ((1, 'txt'), (2, 'lo'), (3, 'dim'), (4, 'acc'), (5, 'md'), (8, 'hi'), (40, 'md')):
            cp(pid, c(th[key]), bk)
        cp(41, bk, c(th['md']))
        cp(42, bk, c(th['md']))
        for k, name in enumerate(THEME_ORDER):
            cp(50 + k, c(THEMES[name]['md']) if rich else THEMES[name]['base'], bk)

    def set_theme(self, k):
        self.theme_i = k % len(THEME_ORDER)
        self.apply_theme()
        self.toast(f"THEME {THEME_ORDER[self.theme_i]}")

    # ---------- primitives ----------
    def put(self, y, x, txt, pair=1, attr=0):
        try:
            self.s.addstr(y, x + self.ox, txt, curses.color_pair(pair) | attr)
        except curses.error:
            pass

    def hit(self, y0, y1, x0, x1, fn):
        self.hits.append((y0, y1, x0, x1, fn))

    def pix(self, y, x, text, pair, attr=0):
        """3x5 pixel font drawn with half blocks: 4 cols x 3 rows per glyph."""
        for gi, ch in enumerate(text.upper()):
            g = FONT.get(ch, FONT[' '])
            for r in range(3):
                top = g[r * 6:r * 6 + 3]
                bot = g[r * 6 + 3:r * 6 + 6] if r < 2 else "000"
                s = ''.join(' ▀▄█'[(a == '1') + 2 * (b == '1')] for a, b in zip(top, bot))
                self.put(y + r, x + gi * 4, s, pair, attr)
        return len(text) * 4

    def hints(self, y, x, items, right=False):
        if right:
            x -= sum(len(k) + len(d) + 3 for k, d in items) - 2
        for k, d in items:
            self.put(y, x, k, 5, curses.A_BOLD)
            self.put(y, x + len(k) + 1, d, 3)
            x += len(k) + len(d) + 3

    def toast(self, msg):
        self.msg, self.msg_t = msg, time.time()
        self.e.log.append(":: " + msg)

    # ---------- params ----------
    def pval(self, i):
        lab, attr, lo, hi, _ = PARAMS[i]
        return getattr(self.e, attr), (getattr(self.e, attr) - lo) / (hi - lo)

    def ptext(self, i):
        lab, attr, lo, hi, _ = PARAMS[i]
        v, n = self.pval(i)
        if attr == 'wave':
            return WAVES[v]
        if attr in ('bpm', 'oct'):
            return str(v)
        return f"{int(round(n * 100))}"

    def set_param(self, i, v):
        lab, attr, lo, hi, step = PARAMS[i]
        v = min(hi, max(lo, v))
        setattr(self.e, attr, int(round(v)) if isinstance(step, int) else round(v, 4))
        self.toast(f"{lab} {self.ptext(i)}")

    def adjust(self, i, d):
        lab, attr, lo, hi, step = PARAMS[i]
        self.set_param(i, getattr(self.e, attr) + d * step)

    # ---------- actions ----------
    def toggle(self, t, i):
        e = self.e
        if t < SYN:
            e.pat[t][i] ^= 1
            e.acc[t][i] = 0
            if e.pat[t][i]:
                e.pending.append(('d', t))
        elif e.pat[t][i]:
            e.pat[t][i] = 0
            e.acc[t][i] = 0
        else:
            e.pat[t][i] = e.last_note
            e.pending.append(('n', e.last_note))

    def click_cell(self, t, i):
        self.cy, self.cx = t, i
        self.toggle(t, i)

    def switch_pattern(self, p):
        self.e.pi = p % 4
        self.toast(f"PATTERN {PTN_NAMES[self.e.pi]}")

    def randomize(self, t):
        e = self.e
        row, acc = e.pat[t], e.acc[t]
        for i in range(STEPS):
            p = {0: 0.9 if i % 4 == 0 else 0.12, 1: 0.9 if i in (4, 12) else 0.08, 2: 0.1,
                 3: 0.7 if i % 2 == 0 else 0.25, 4: 0.12}.get(t, 0.45)
            on = random.random() < p
            row[i] = (1 if t < SYN else 45 + 12 * random.randint(0, 1) + random.choice(PENTA)) if on else 0
            acc[i] = 1 if on and random.random() < 0.2 else 0
        self.toast(f"{NAMES[t]} RANDOMIZED")

    def toggle_fx(self, k):
        self.e.fx[k] = not self.e.fx[k]
        self.toast(f"FX {FX_NAMES[k]} {'ON' if self.e.fx[k] else 'OFF'}")

    def toggle_dj(self):
        r = self.e.radio
        if not r:
            self.toast("DJ MIX WORKS IN RADIO MODE (R)")
            return
        r.dj = not r.dj
        self.toast("DJ AUTO-MIX " + ("ON" if r.dj else "OFF"))

    def radio_tempo_key(self, k):
        r = self.e.radio
        if k in '-_':
            self.toast(f"TEMPO {r.set_tempo(self.e.bpm - 2)} BPM")
        elif k in '=+':
            self.toast(f"TEMPO {r.set_tempo(self.e.bpm + 2)} BPM")
        elif k == 'v':
            self.toggle_voice()
        elif k == 'm':
            vb = self.e.voicebox
            vb.mode = (vb.mode + 1) % len(VOICE_MODES)
            self.toast(VOICE_MODE_INFO[vb.mode])
        elif k in '[]':
            vb = self.e.voicebox
            vb.select(vb.i + (1 if k == ']' else -1))
            self.toast(f"VOICE: {vb.text.upper()}")
        elif k == '/':
            self.toast(f"RANDOM TEMPO {r.set_tempo(random.randint(70, 150))} BPM")
        elif k == '\\':
            r.mul = r.mul_b = 1.0
            self.toast("TEMPO RESET TO THE SONG'S OWN")
        else:
            r.auto = not r.auto
            self.toast("AUTO RANDOM TEMPO " + ("ON: EVERY NEW SONG GETS ITS OWN SPEED" if r.auto else "OFF"))

    def toggle_voice(self):
        e = self.e
        if not e.radio:
            self.toast("THE VOICE IS A RADIO FEATURE (PRESS R)")
            return
        e.vox_on = not e.vox_on
        self.toast("VOICE " + ("ON: SINGING OVER THE SONG" if e.vox_on else "OFF"))

    def start_typing(self, purpose='voice'):
        if purpose == 'voice' and not self.e.radio:
            self.toast("THE VOICE IS A RADIO FEATURE (PRESS R)")
            return
        self.typing, self.tbuf, self.tfor = True, '', purpose

    def commit_typing(self):
        self.typing = False
        if self.tfor in ('remix', 'open'):
            if self.tbuf.strip():
                (self.start_remix if self.tfor == 'remix' else self.open_file)(self.tbuf)
            return
        text = self.tbuf.strip().lower()
        if text:
            vb = self.e.voicebox
            vb.set_custom(text)
            self.e.vox_on = True
            self.toast(f"VOICE: {len(vb.syls)} SYLLABLES" if vb.syls else "NO ENGLISH LETTERS TO PRONOUNCE")

    def type_char(self, c):
        if c in '\r\n':
            self.commit_typing()
        elif c == '\x1b':
            self.typing = False
        elif c in '\x7f\b':
            self.tbuf = self.tbuf[:-1]
        elif c.isprintable() and len(self.tbuf) < 400:
            self.tbuf += c

    def type_key(self, ch):
        if ch in (10, 13, curses.KEY_ENTER):
            self.commit_typing()
        elif ch == 27:
            self.typing = False
        elif ch in (127, 8, curses.KEY_BACKSPACE):
            self.tbuf = self.tbuf[:-1]
        return True

    # ---------- remix ----------
    def open_file(self, raw):
        path = parse_path(raw)
        if not os.path.isfile(path):
            self.toast("FILE NOT FOUND - DRAG THE FILE INTO THE TERMINAL OR TYPE ITS PATH")
            return
        self.e.player_on(path)
        self.e.log.append(f"PLAYER: {os.path.basename(path)}")
        self.toast(f"NOW PLAYING · FX {PLAYER_FX[self.e.pset][0]} · V = VOCALS")

    def stop_player(self):
        self.e.player_off()

    def player_key(self, ch):
        """Keys that mean something different while a file is playing. Returns True when handled."""
        e, pl = self.e, self.e.player
        c = chr(ch).lower() if 0 < ch < 256 else ''
        if c == ' ':
            pl.paused = not pl.paused
            self.toast("PAUSED" if pl.paused else "PLAY")
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
            pl.seek(pl.time + (10 if ch == curses.KEY_RIGHT else -10))
            self.toast(f"SEEK {int(pl.time // 60):02d}:{int(pl.time % 60):02d}")
        elif c == 'v':
            pl.vmode = (pl.vmode + 1) % len(VOCAL_MODES)
            pl.seek(pl.time)
            self.toast("VOCALS: " + VOCAL_MODES[pl.vmode] + ("  (WORKS BEST ON STEREO FILES)" if pl.vmode else ""))
        elif c in '[]':
            e.set_preset(e.pset + (1 if c == ']' else -1))
            self.toast("FX PRESET " + PLAYER_FX[e.pset][0])
        elif c == 'm':
            self.start_remix(pl.path)
        elif c == 'r':
            self.stop_player()
            e.radio_on()
            self.toast("RADIO ON")
        else:
            return False
        return True

    def start_remix(self, raw):
        path = parse_path(raw)
        if not os.path.isfile(path):
            self.toast("FILE NOT FOUND - DRAG THE FILE INTO THE TERMINAL OR TYPE ITS PATH")
            return
        if self.remix:
            self.toast("ALREADY ANALYSING A FILE")
            return
        ctx = multiprocessing.get_context('spawn')
        q = ctx.Queue()
        proc = ctx.Process(target=_analyze_proc, args=(path, q), daemon=True)
        proc.start()
        name = os.path.splitext(os.path.basename(path))[0]
        self.remix = dict(q=q, proc=proc, name=name, t0=time.time())
        self.e.log.append(f"REMIX: analysing {name}")

    def poll_remix(self):
        r = self.remix
        if not r:
            return
        try:
            res = r['q'].get_nowait()
        except queue.Empty:
            if r['proc'].is_alive() or time.time() - r['t0'] < 3:
                return
            try:
                res = r['q'].get(timeout=1)
            except queue.Empty:
                self.remix = None
                self.toast("ANALYSIS FAILED")
                return
        self.remix = None
        if 'error' in res:
            self.toast("CAN'T REMIX: " + res['error'].upper()[:60])
            return
        e = self.e
        song = song_from_analysis(res, random.randrange(1 << 16))
        if e.player is not None:
            self.stop_player()
        mel = res.get('melody') or {}
        first = next((b for b in sorted(mel) if len(mel[b]) >= 3), None)
        e.pats[3].seed(res['drums'], {st: m for st, m, _ in mel.get(first, [])})
        if first is not None:
            for st, m, ln in mel[first]:
                e.pats[3].glen[SYN][st] = max(0.5, ln - 0.15)
        if not e.radio:
            e.radio_on()
        e.radio.queue_song(song)
        chords = ' '.join(chord_name(song.chord(d)[1]) for d in song.progA)
        nn = sum(len(v) for v in mel.values())
        self.toast(f"REMIX READY: {song.bpm} BPM · {song.keyname()} · {nn} MELODY NOTES")
        e.log.append(f"REMIX {res['name']}: {song.bpm}BPM {song.keyname()} loop {chords}")
        e.log.append("REMIX beat: " + ' '.join(res['drums'][:2]) + "  (also in studio pattern D)")

    def draw_voice(self, y, x, now):
        e = self.e
        vb, on = e.voicebox, e.vox_on
        self.put(y, x, "VOICE", 3)
        self.put(y, x + 6, "■" if on else "□", 8 if on else 3, curses.A_BOLD)
        self.hit(y, y, x, x + 6, lambda mx, ev: ev == 'click' and self.toggle_voice())
        self.put(y, x + 8, VOICE_MODES[vb.mode], 5, curses.A_BOLD)
        self.hit(y, y, x + 8, x + 15, lambda mx, ev: ev == 'click' and self.radio_tempo_key('m'))
        txt = (vb.line if vb.text == RANDOM_LINES and vb.line else vb.text).upper()
        if len(txt) > 11:
            pad = txt + "   "
            o = int(now * 3) % len(pad)
            txt = (pad + pad)[o:o + 11]
        self.put(y + 1, x, "◀", 8, curses.A_BOLD)
        self.put(y + 1, x + 2, f"{txt:<11}", 8 if on else 2)
        self.put(y + 1, x + 14, "▶", 8, curses.A_BOLD)
        self.hit(y + 1, y + 1, x, x + 1, lambda mx, ev: ev == 'click' and self.radio_tempo_key('['))
        self.hit(y + 1, y + 1, x + 14, x + 15, lambda mx, ev: ev == 'click' and self.radio_tempo_key(']'))
        self.hit(y + 1, y + 1, x + 2, x + 12, lambda mx, ev: ev == 'click' and self.toggle_voice())
        self.put(y + 2, x, "TYPE TEXT", 5, curses.A_BOLD)
        self.hit(y + 2, y + 2, x, x + 8, lambda mx, ev: ev == 'click' and self.start_typing('voice'))

    def draw_tempo(self, y, x):
        """Radio tempo control: nudge, random, auto-random, reset. Wheel over it also nudges."""
        e, r = self.e, self.e.radio
        k = lambda key: self.radio_tempo_key(key)
        self.put(y, x, "TEMPO", 3)
        self.put(y + 1, x, "◀", 8, curses.A_BOLD)
        self.put(y + 1, x + 2, f"{e.bpm:3d} BPM", 8, curses.A_BOLD)
        self.put(y + 1, x + 10, "▶", 8, curses.A_BOLD)
        off = int(round((r.mul - 1) * 100))
        self.put(y, x + 8, f"{off:+d}%" if off else "", 2)
        self.hit(y + 1, y + 1, x, x + 1, lambda mx, ev: ev == 'click' and k('-'))
        self.hit(y + 1, y + 1, x + 10, x + 11, lambda mx, ev: ev == 'click' and k('='))
        self.hit(y, y + 1, x + 2, x + 9, lambda mx, ev: k('=' if ev == 'up' else '-') if ev in ('up', 'down') else k('/'))
        self.put(y + 2, x, "RND", 5, curses.A_BOLD)
        self.hit(y + 2, y + 2, x, x + 2, lambda mx, ev: ev == 'click' and k('/'))
        self.put(y + 2, x + 5, ("■" if r.auto else "□") + " AUTO", 8 if r.auto else 3, curses.A_BOLD if r.auto else 0)
        self.hit(y + 2, y + 2, x + 5, x + 11, lambda mx, ev: ev == 'click' and k("'"))
        self.put(y + 2, x + 13, "RESET", 3)
        self.hit(y + 2, y + 2, x + 13, x + 17, lambda mx, ev: ev == 'click' and k('\\'))

    def cycle_noise(self, d):
        e = self.e
        e.noise = (e.noise + d) % len(NOISES)
        self.toast(f"NOISE {NOISES[e.noise]}")

    def noise_level(self, d):
        e = self.e
        e.noise_lvl = round(max(0.0, min(1.0, e.noise_lvl + d * 0.05)), 2)
        self.toast(f"NOISE LEVEL {int(e.noise_lvl * 100)}")

    def draw_noise(self, y, x):
        """NOISE <type> <level>: click cycles the type, wheel sets the level. Returns width."""
        e = self.e
        on = e.noise > 0
        self.put(y, x, "NOISE", 3)
        self.put(y, x + 6, f"{NOISES[e.noise]:<5}", 8 if on else 3, curses.A_BOLD if on else 0)
        self.put(y, x + 12, dbar(e.noise_lvl, 6), 5 if on else 3)

        def fn(mx, ev):
            if ev == 'click':
                self.cycle_noise(1)
            else:
                self.noise_level(1 if ev == 'up' else -1)
        self.hit(y, y, x, x + 17, fn)
        return 18

    def toggle_radio(self):
        if self.e.radio:
            self.e.radio_off()
            self.toast("RADIO OFF")
        else:
            self.e.radio_on()
            self.toast("RADIO ON")

    def play_key(self, k):
        e = self.e
        m = 12 * (e.oct + 1) + PIANO[k]
        e.pending.append(('n', m))
        e.last_note = m
        self.pressed[k] = time.time()
        self.ripples.append((PIANO[k] / 16 * 0.9 + 0.05, 0.5, time.time()))
        e.log.append(f"     KEY {note_name(m)}")
        if e.rec and e.playing:
            e.record(m)

    def toggle_mute(self, t):
        self.e.muted[t] = not self.e.muted[t]
        self.toast(f"{NAMES[t]} {'MUTED' if self.e.muted[t] else 'ON'}")

    def toggle_solo(self, t):
        e = self.e
        e.solo ^= {t}
        self.toast(f"SOLO {', '.join(NAMES[x] for x in sorted(e.solo)) or 'OFF'}")

    def mouse(self):
        try:
            _, mx, my, _, bs = curses.getmouse()
        except curses.error:
            return
        mx -= self.ox
        ev = None
        if bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
            ev = 'click'
        elif bs & getattr(curses, 'BUTTON4_PRESSED', 0):
            ev = 'up'
        elif bs & getattr(curses, 'BUTTON5_PRESSED', 0):
            ev = 'down'
        if not ev:
            return
        for y0, y1, x0, x1, fn in reversed(self.hits):
            if y0 <= my <= y1 and x0 <= mx <= x1:
                self.last_my = my
                fn(mx, ev)
                break

    def key(self, ch):
        e = self.e
        if self.typing:
            return self.type_key(ch)
        if self.help and ch not in (-1, curses.KEY_MOUSE):
            self.help = False
            return True
        if e.player is not None and ch != curses.KEY_MOUSE and self.player_key(ch):
            return True
        if ch == curses.KEY_MOUSE:
            self.mouse()
        elif ch == curses.KEY_UP:
            self.cy = (self.cy - 1) % NT
        elif ch == curses.KEY_DOWN:
            self.cy = (self.cy + 1) % NT
        elif ch == curses.KEY_LEFT:
            self.cx = (self.cx - 1) % STEPS
        elif ch == curses.KEY_RIGHT:
            self.cx = (self.cx + 1) % STEPS
        elif ch in (10, 13, curses.KEY_ENTER):
            self.toggle(self.cy, self.cx)
        elif ch == 9:
            self.switch_pattern(e.pi + 1)
        elif ch == curses.KEY_BTAB:
            self.switch_pattern(e.pi - 1)
        elif ch == ord('V'):
            self.start_typing('voice')
        elif ch == ord('O'):
            self.start_typing('open')
        elif ch == ord('D'):
            self.toggle_dj()
        elif ch == ord('W'):
            self.cycle_noise(1)
        elif ch in (ord('{'), ord('}')):
            self.noise_level(1 if ch == ord('}') else -1)
        elif ch == ord('B'):
            self.cycle_viz(-1)
        elif ch == ord('R'):
            self.randomize(self.cy)
        elif ch == ord('?'):
            self.help = True
        elif ch == ord('>'):
            if e.radio:
                e.radio.skip = True
                self.toast("NEXT SONG ON THE NEXT BAR")
        elif 0 < ch < 256:
            k = chr(ch).lower()
            if e.radio and k in "-_=+/\\'v[]m":
                self.radio_tempo_key(k)
            elif k == ' ':
                e.stop() if e.playing else e.play()
            elif k == 'q':
                return False
            elif k in PIANO:
                self.play_key(k)
            elif k == 'r':
                self.toggle_radio()
            elif k == 'v':
                e.rec = not e.rec
                if e.rec and not e.playing:
                    e.play()
                self.toast("LOOP REC " + ("ARMED" if e.rec else "OFF"))
            elif k == 'm':
                self.toggle_mute(self.cy)
            elif k == 'n':
                self.toggle_solo(self.cy)
            elif k == 'c':
                e.pat[self.cy] = [0] * STEPS
                e.acc[self.cy] = [0] * STEPS
                self.toast(f"{NAMES[self.cy]} CLEARED")
            elif k == '/':
                if not e.pat[self.cy][self.cx]:
                    self.toggle(self.cy, self.cx)
                e.acc[self.cy][self.cx] ^= 1
            elif k == '\\':
                nxt = (e.pi + 1) % 4
                e.pats[nxt].copy_from(e.pats[e.pi])
                self.toast(f"COPIED {PTN_NAMES[e.pi]} > {PTN_NAMES[nxt]}")
                e.pi = nxt
            elif k == 'z':
                self.set_param(13, e.oct - 1)
            elif k == 'x':
                self.set_param(13, e.oct + 1)
            elif k == '[':
                self.sel = (self.sel - 1) % len(PARAMS)
                self.toast(f"SELECT {PARAMS[self.sel][0]}")
            elif k == ']':
                self.sel = (self.sel + 1) % len(PARAMS)
                self.toast(f"SELECT {PARAMS[self.sel][0]}")
            elif k in '-_':
                self.adjust(self.sel, -1)
            elif k in '=+':
                self.adjust(self.sel, 1)
            elif k == 'b':
                self.cycle_viz(1)
            elif k == 'i':
                self.inv = not self.inv
                self.toast("VISUAL " + ("INVERTED" if self.inv else "NORMAL"))
            elif k == '0':
                self.full = not self.full
            elif k == '`':
                self.set_theme(self.theme_i + 1)
            elif k in '56789':
                self.toggle_fx(int(k) - 5)
            elif k in '1234':
                self.set_param(11, int(k) - 1)
            elif k in ',.' and self.cy == SYN and e.pat[SYN][self.cx]:
                m = e.pat[SYN][self.cx] + (1 if k == '.' else -1)
                e.pat[SYN][self.cx] = max(24, min(96, m))
                e.last_note = e.pat[SYN][self.cx]
                e.pending.append(('n', e.last_note))
        return True

    # ---------- visuals ----------
    def update_spectrum(self):
        mag = np.abs(np.fft.rfft(self.e.ring * self.win)) / (FFT_N / 8)
        v = np.array([mag[self.bins[b]:max(self.bins[b + 1], self.bins[b] + 1)].max() for b in range(28)])
        db = 20 * np.log10(v + 1e-6) + self.tilt
        n = np.clip((db + 75) / 60, 0, 1)
        self.spec = np.maximum(n, self.spec * 0.82)
        self.peak = np.maximum(self.spec, self.peak - 0.012)

    # ---------- 80s visualizer ----------
    def _thr(self, Hd, Wd):
        key = (Hd, Wd)
        if key not in self.thr_cache:
            self.thr_cache[key] = (self.bayer[(np.arange(Hd) % 8)[:, None], (np.arange(Wd) % 8)[None, :]] + 0.5) / 64
        return self.thr_cache[key]

    def _pers(self, name, Hd, Wd, decay):
        """Phosphor persistence buffer: last frame fades out like a CRT."""
        p = self.pers.get(name)
        if p is None or p.shape != (Hd, Wd):
            p = self.pers[name] = np.zeros((Hd, Wd))
        p *= decay
        return p

    @staticmethod
    def _line(C, x0, y0, x1, y1, v0=1.0, v1=None):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 2
        xs = np.linspace(x0, x1, n).round().astype(int)
        ys = np.linspace(y0, y1, n).round().astype(int)
        vs = np.linspace(v0, v0 if v1 is None else v1, n)
        m = (xs >= 0) & (xs < C.shape[1]) & (ys >= 0) & (ys < C.shape[0])
        C[ys[m], xs[m]] = np.maximum(C[ys[m], xs[m]], vs[m])

    def viz(self, w, h, now):
        """Draws the current mode into a dot canvas, dithers it and packs it into braille rows.

        Returns [(text, colour pair)] per text row; labels to print on top go to self.viz_labels."""
        e = self.e
        Wd, Hd = w * 2, h * 4
        C = np.zeros((Hd, Wd))
        X, Y = np.arange(Wd)[None, :], np.arange(Hd)[:, None]
        g = self.vgain
        sp = np.clip(self.spec * g, 0, 1)
        kick = min(1.0, e.tl[0] * 1.2)
        rows = [5] * h
        self.viz_labels = []
        m = self.vmode
        if m == 0:      # LED spectrum, like a hi-fi graphic EQ
            nb = max(8, min(32, w // 3))
            grid = np.linspace(0, 27, nb)
            bands = np.interp(grid, np.arange(28), sp)
            peaks = np.interp(grid, np.arange(28), np.clip(self.peak * g, 0, 1))
            bw, seg = Wd / nb, 4
            nseg = Hd // seg
            band = np.minimum((X / bw).astype(int), nb - 1)
            inbar = (X - band * bw) >= 2
            segi = (Hd - 1 - Y) // seg
            inseg = ((Hd - 1 - Y) % seg) < seg - 1
            lit = np.round(bands * nseg)[band]
            pk = np.round(peaks * nseg)[band]
            on = inbar & inseg & ((segi < lit) | ((segi == pk - 1) & (pk > 0)))
            C = np.where(on, 1.0, np.where(inbar & inseg, 0.12, 0.0))
            rows = [4 if 1 - (r + 0.5) / h > 0.8 else (8 if 1 - (r + 0.5) / h > 0.55 else 5) for r in range(h)]
        elif m == 1:    # oscilloscope with graticule and phosphor trail
            sx, sy = max(2, Wd // 10), max(2, Hd // 8)
            grid = (((X % sx) == 0) & (Y % 3 == 0)) | (((Y % sy) == 0) & (X % 3 == 0))
            axis = ((X == Wd // 2) & (Y % 2 == 0)) | ((Y == Hd // 2) & (X % 2 == 0))
            s = e.ring[-2600:]
            zc = np.flatnonzero((s[:1400] < 0) & (s[1:1401] >= 0))
            i0 = int(zc[0]) if len(zc) else 0
            span = 1100
            seg_ = s[i0:i0 + span]
            col = np.minimum((np.arange(len(seg_)) * Wd // span), Wd - 1)
            ys = Hd / 2 - seg_ * g * Hd * 0.7
            starts = np.flatnonzero(np.r_[True, col[1:] != col[:-1]])
            lo = np.full(Wd, Hd / 2)
            hi = np.full(Wd, Hd / 2)
            lo[col[starts]] = np.minimum.reduceat(ys, starts)
            hi[col[starts]] = np.maximum.reduceat(ys, starts)
            lo = np.minimum(lo, np.r_[lo[:1], hi[:-1]])
            hi = np.maximum(hi, np.r_[hi[:1], lo[:-1]])
            trace = (Y >= lo[None, :] - 0.6) & (Y <= hi[None, :] + 0.6)
            glow = (Y >= lo[None, :] - 2) & (Y <= hi[None, :] + 2)
            P = self._pers('scope', Hd, Wd, 0.55)
            np.maximum(P, np.where(trace, 1.0, np.where(glow, 0.3, 0.0)), out=P)
            C = np.maximum(P, (grid | axis) * 1.0)
            self.viz_labels.append((h - 1, 1, f"{span * 1000 // SR}ms/DIV  {g:.1f}x", 2))
        elif m == 2:    # rotating XY vector display
            s = e.ring[-2048:] * g * 1.4
            dl = 24
            ang = now * 0.45
            xv, yv = s[dl:], s[:-dl]
            xr = xv * math.cos(ang) - yv * math.sin(ang)
            yr = xv * math.sin(ang) + yv * math.cos(ang)
            R = min(Wd, Hd) * 0.45
            px = (Wd / 2 + xr * R).astype(int)
            py = (Hd / 2 - yr * R).astype(int)
            ok = (px >= 0) & (px < Wd) & (py >= 0) & (py < Hd)
            P = self._pers('vector', Hd, Wd, 0.7)
            P[py[ok], px[ok]] = 1.0
            ring = (np.abs(np.hypot(X - Wd / 2, Y - Hd / 2) - R * 1.05) < 0.6) & ((X + Y) % 3 == 0)
            cross = ((np.abs(X - Wd / 2) < 0.5) | (np.abs(Y - Hd / 2) < 0.5)) & ((X + Y) % 4 == 0)
            C = np.maximum(P, (ring | cross) * 1.0)
        elif m == 3:    # outrun: striped sun over a perspective grid
            yh = int(Hd * 0.5)
            st = self.stars
            tw = np.sin(now * 3 + np.arange(len(st)) * 1.7) > -0.2
            sxs = (st[:, 0] * (Wd - 1)).astype(int)
            sys_ = (st[:, 1] * yh * 0.85).astype(int)
            C[sys_[tw], sxs[tw]] = 1.0
            bass = sp[:7].mean()
            r = Hd * 0.36 * (0.9 + 0.18 * bass + 0.1 * kick)
            cx = Wd / 2
            v = (yh - Y) / r
            gap = ((yh - Y) % 6) < 6 * np.clip((0.6 - v) / 0.6, 0, 1) * 0.85
            sun = (np.hypot(X - cx, Y - yh) < r) & (Y < yh) & ~gap
            C = np.where(sun, 0.5 + 0.5 * np.clip(v, 0, 1), C)
            speed = e.bpm / 60 * 0.5 if e.playing else 0.12
            ph = (now * speed) % 1
            for k in range(10):
                p = (k + ph) / 10
                yy = int(yh + (Hd - 1 - yh) * p ** 2.2)
                C[yy, :] = np.maximum(C[yy, :], min(1.0, 0.3 + 0.7 * p + 0.3 * kick))
            for i in range(-7, 8):
                self._line(C, cx + i * Wd * 0.012, yh, cx + i * Wd * 0.13, Hd - 1, 0.3, 1.0)
            C[yh, :] = 1.0
            rows = [4 if (r_ + 1) * 4 <= yh else (8 if r_ * 4 <= yh else 5) for r_ in range(h)]
        elif m == 4:    # twin analogue VU meters
            tg = [sp[:8].mean(), sp[12:].mean()]
            for i, lab in enumerate(("LOW", "HIGH")):
                self.vu[i] += (min(1.08, tg[i] * 1.1) - self.vu[i]) * 0.22
                cx, cy = Wd * (0.25 + 0.5 * i), Hd * 0.9
                R = min(Hd * 0.8, Wd * 0.22)
                a = np.radians(np.linspace(-55, 55, 260))
                ax, ay = (cx + R * np.sin(a)).astype(int), (cy - R * np.cos(a)).astype(int)
                C[ay, ax] = 1.0
                red = a > np.radians(22)
                C[(cy - R * 0.95 * np.cos(a[red])).astype(int), (cx + R * 0.95 * np.sin(a[red])).astype(int)] = 1.0
                for k in range(11):
                    t = math.radians(-55 + 11 * k)
                    r0 = 0.82 if k % 5 == 0 else 0.9
                    self._line(C, cx + R * r0 * math.sin(t), cy - R * r0 * math.cos(t),
                               cx + R * math.sin(t), cy - R * math.cos(t))
                t = math.radians(-55 + 110 * self.vu[i])
                self._line(C, cx, cy, cx + R * 0.97 * math.sin(t), cy - R * 0.97 * math.cos(t))
                C[(np.hypot(X - cx, Y - cy) < 2.5)] = 1.0
                lc = int(cx / 2)
                self.viz_labels.append((min(h - 1, int(cy / 4) - 2), lc - 1, "VU", 2))
                self.viz_labels.append((h - 1, lc - len(lab) // 2, lab, 8))
                if self.vu[i] > 0.92:
                    self.viz_labels.append((1, int((cx + R * 0.7) / 2), "● PEAK", 4))
        else:           # dither clouds
            lvl = min(1.0, e.level * g)
            T = self.cloud[np.ix_((np.arange(Hd) + int(now * 3)) % 256, (np.arange(Wd) + int(now * 9)) % 256)]
            C = np.clip((T - (0.72 - 0.30 * lvl - 0.2 * kick)) * 2.6, 0, 1)
        # ripples from pad clicks and played notes
        keep = []
        for rx, ry, t0 in self.ripples:
            age = now - t0
            if age < 0.7:
                keep.append((rx, ry, t0))
                d = np.hypot(X - rx * Wd, Y - ry * Hd)
                C = np.maximum(C, (np.abs(d - age * Wd * 0.22) < 1.1) * (1 - age / 0.7) * 1.4)
        self.ripples = keep
        d = (C > self._thr(Hd, Wd)).reshape(h, 4, w, 2)
        code = (d * self.wts[None, :, None, :]).sum(axis=(1, 3)) + 0x2800
        return [(''.join(map(chr, r)), rows[i]) for i, r in enumerate(code.tolist())]

    def pad_click(self, xf, yf):
        """The visualizer doubles as an XY pad: x picks a pentatonic note, y sets the filter."""
        e = self.e
        idx = int(max(0.0, min(0.999, xf)) * 10)
        m = 12 * (e.oct + 1) + 12 * (idx // 5) + PENTA[idx % 5]
        e.cut = round(1 - max(0.0, min(1.0, yf)), 3)
        e.pending.append(('n', m))
        e.last_note = m
        self.ripples.append((xf, yf, time.time()))
        self.toast(f"PAD {note_name(m)}  CUT {int(e.cut * 100)}")

    def cycle_viz(self, d):
        self.vmode = (self.vmode + d) % len(VIZ_NAMES)
        self.toast(f"VISUAL {VIZ_NAMES[self.vmode]}")

    def draw_viz(self, y, x, w, h, now):
        for r, (line, pair) in enumerate(self.viz(w, h, now)):
            self.put(y + r, x, line, 41 if self.inv else pair)

        def fn(mx, ev):
            if ev == 'click':
                self.pad_click((mx - x) / w, (self.last_my - y) / h)
            else:
                self.vgain = max(0.3, min(4.0, self.vgain * (1.15 if ev == 'up' else 1 / 1.15)))
                self.toast(f"VISUAL GAIN {self.vgain:.1f}x")
        self.hit(y, y + h - 1, x, x + w - 1, fn)
        for r, c, txt, pair in self.viz_labels:
            self.put(y + r, x + c, txt, pair)
        name = VIZ_NAMES[self.vmode]
        self.put(y, x + 1, "◀", 8, curses.A_BOLD)
        self.put(y, x + 3, name, 8, curses.A_BOLD)
        self.put(y, x + 4 + len(name), "▶", 8, curses.A_BOLD)
        self.hit(y, y, x, x + 2, lambda mx, ev: ev == 'click' and self.cycle_viz(-1))
        self.hit(y, y, x + 4 + len(name), x + 5 + len(name), lambda mx, ev: ev == 'click' and self.cycle_viz(1))
        gtxt = f"GAIN {dbar(self.vgain / 4, 6)}"
        self.put(y, x + w - len(gtxt) - 1, gtxt, 2)

    # ---------- studio view ----------
    def draw_head(self, y, now):
        e = self.e
        self.pix(y, PX, "BLIP-16", 8)
        self.pix(y, 34, f"{e.bpm:3d}", 5)
        self.put(y + 2, 47, "BPM", 3)
        x = 58
        self.put(y, x, "▶ PLAY" if e.playing else "■ STOP", 8 if e.playing else 2, curses.A_BOLD)
        self.hit(y, y, x, x + 5, lambda mx, ev: ev == 'click' and (e.stop() if e.playing else e.play()))
        blink = int(now * 2) % 2 == 0
        self.put(y, x + 8, ("● REC" if blink else "○ REC") if e.rec else "○ REC", 4 if e.rec else 3)
        m, sec = divmod(e.elapsed, 60)
        self.put(y, x + 30, f"{int(m):02d}:{sec:04.1f}", 2)
        self.put(y + 1, x, "PTN", 3)
        for p in range(4):
            sel = p == e.pi
            self.put(y + 1, x + 4 + p * 2, PTN_NAMES[p], 8 if sel else 3, curses.A_BOLD if sel else 0)
            self.hit(y + 1, y + 1, x + 4 + p * 2, x + 4 + p * 2, lambda mx, ev, p=p: ev == 'click' and self.switch_pattern(p))
        self.put(y + 1, x + 14, "BAR", 3)
        bar_, bt = e.tick // 16 + 1, (e.tick % 16) // 4 + 1
        self.put(y + 1, x + 18, f"{bar_:03d}.{bt}" if e.tick else "000.0", 1)
        self.put(y + 2, x, "OUT", 3)
        clip = now - e.clip_t < 1.0
        self.put(y + 2, x + 4, dbar(min(1.0, e.level), 8), 4 if clip else 5)
        for k in range(len(THEME_ORDER)):
            sel = k == self.theme_i
            self.put(y + 2, x + 18 + k * 3, "██" if sel else "▀▀", 50 + k)
            self.hit(y + 2, y + 2, x + 18 + k * 3, x + 19 + k * 3, lambda mx, ev, k=k: ev == 'click' and self.set_theme(k))

    def draw_line(self, y, frac, live):
        p = max(0, min(PW - 1, int(frac * PW)))
        self.put(y, PX, '⣤' * p, 5)
        self.put(y, PX + p, '⣿', 8 if live else 3)
        self.put(y, PX + p + 1, '⣀' * (PW - p - 1), 3)

    def step_frac(self):
        e = self.e
        if not (e.playing and e.disp >= 0):
            return 0.0, False
        frac = 1 - max(0.0, min(1.0, e.countdown / max(1.0, e.step_len(e.disp))))
        return (e.disp + frac) / STEPS, True

    def draw_seq(self, y0):
        e = self.e
        gx = 12
        cx = lambda i: gx + i * 4 + i // 4
        self.put(y0, PX, "SEQ", 3)
        self.put(y0, PX + 4, PTN_NAMES[e.pi], 5, curses.A_BOLD)
        for i in range(0, STEPS, 4):
            self.put(y0, cx(i), str(i // 4 + 1), 2)
        self.put(y0, 86, "LEVEL", 3)
        for t in range(NT):
            y = y0 + 1 + t
            on = e.audible(t)
            self.put(y, PX, f"{NAMES[t]:<5}", 8 if self.cy == t else (2 if on else 3),
                     curses.A_BOLD if self.cy == t else 0)
            if e.muted[t]:
                self.put(y, PX + 6, "M", 4)
            elif t in e.solo:
                self.put(y, PX + 6, "S", 8)
            self.hit(y, y, PX, PX + 6, lambda mx, ev, t=t: ev == 'click' and self.toggle_mute(t))
            for i in range(STEPS):
                x = cx(i)
                v, a = e.pat[t][i], e.acc[t][i]
                head = e.playing and i == e.disp
                if v and t == SYN:
                    txt = (note_name(v) + ("!" if a else " ")).ljust(3)[:3]
                    self.put(y, x, txt, 42 if on else 3, curses.A_BOLD if head else 0)
                elif v:
                    self.put(y, x, "▀▀▀", (8 if head or a else 5) if on else 2, curses.A_BOLD if head else 0)
                else:
                    self.put(y, x, "▀▀▀", 2 if head else 3)
                if self.cy == t and self.cx == i:
                    self.put(y, x - 1, "[", 8, curses.A_BOLD)
                    self.put(y, x + 3, "]", 8, curses.A_BOLD)
                self.hit(y, y, x, x + 2, lambda mx, ev, t=t, i=i: ev == 'click' and self.click_cell(t, i))
            self.put(y, 86, dbar(e.tl[t] * 1.1, 6), 4 if e.tl[t] > 0.9 else 5)

    def draw_params(self, y0):
        for i, (lab, attr, lo, hi, step) in enumerate(PARAMS):
            y, x = y0 + i // 5, PX + (i % 5) * 19
            sel = i == self.sel
            self.put(y, x, lab, 42 if sel else 2, curses.A_BOLD if sel else 0)
            v, n = self.pval(i)
            self.put(y, x + 4, WAVE_ART[v] if attr == 'wave' else dbar(n, 8), 8 if sel else 5)
            self.put(y, x + 13, f"{self.ptext(i):>3}", 8 if sel else 1)

            def fn(mx, ev, i=i, x=x):
                if ev == 'click':
                    self.sel = i
                    _, attr_, lo_, hi_, _ = PARAMS[i]
                    if attr_ == 'wave':
                        self.adjust(i, 1)
                    elif x + 4 <= mx <= x + 11:
                        self.set_param(i, lo_ + (mx - (x + 4) + 0.5) / 8 * (hi_ - lo_))
                else:
                    self.adjust(i, 1 if ev == 'up' else -1)
            self.hit(y, y, x, x + 16, fn)

    def draw_fx(self, y):
        e = self.e
        self.put(y, PX, "FX", 3)
        x = PX + 4
        for k, nm in enumerate(FX_NAMES):
            on = e.fx[k]
            s = f"{'■' if on else '□'} {nm}"
            self.put(y, x, s, 8 if on else 3, curses.A_BOLD if on else 0)
            self.hit(y, y, x, x + len(s) - 1, lambda mx, ev, k=k: ev == 'click' and self.toggle_fx(k))
            x += len(s) + 4
        self.draw_noise(y, PX + PW - 18)

    def draw_status(self, y, now):
        if self.typing:
            self.draw_prompt(y - 1, now)
            return
        if self.remix and not (now - self.msg_t < 1.6):
            self.draw_remix_status(y, now)
        elif now - self.msg_t < 1.6:
            self.put(y, PX, f"› {self.msg}"[:60], 8, curses.A_BOLD)
        elif self.e.log:
            self.put(y, PX, ("› " + self.e.log[-1])[:60], 3)
        self.hints(y, PX + PW, [("shift-O", "play a file"), ("R", "radio"), ("?", "help"), ("Q", "quit")], right=True)

    def draw_studio(self, H, now):
        vh = min(18, H - 21)
        y = max(0, (H - 21 - vh) // 2)
        self.draw_head(y, now)
        self.draw_viz(y + 4, PX, PW, vh, now)
        y += 4 + vh
        frac, live = self.step_frac()
        self.draw_line(y, frac, live)
        self.draw_seq(y + 2)
        self.draw_params(y + 10)
        self.draw_fx(y + 14)
        self.draw_status(y + 16, now)

    # ---------- radio view ----------
    def draw_radio(self, H, now):
        e, r = self.e, self.e.radio
        vh = min(22, H - 16)
        y = max(0, (H - 16 - vh) // 2)
        self.pix(y, PX, "RADIO", 5)
        self.draw_tempo(y, 42)
        self.draw_voice(y, 62, now)
        self.put(y, 25, "BLIP-16 FM", 2)
        blink = int(now * 1.5) % 2 == 0
        if e.playing:
            self.put(y + 1, 25, "● ON AIR" if blink else "○ ON AIR", 4 if blink else 3)
        else:
            self.put(y + 1, 25, "‖ PAUSED", 3)
        self.put(y + 2, 25, f"#{r.songs:03d}", 3)
        self.put(y + 2, 31, "◆ OPEN", 5, curses.A_BOLD)
        self.hit(y + 2, y + 2, 31, 36, lambda mx, ev: ev == 'click' and self.start_typing('open'))
        self.pix(y, PX + PW - 20, time.strftime("%H:%M"), 2)
        self.draw_viz(y + 4, PX, PW, vh, now)
        yb = y + 5 + vh
        self.pix(yb, PX, r.title, 8)
        self.put(yb + 3, PX, f"{r.style}  ·  {r.keyname()}  ·  {e.bpm} BPM  ·  SEED {r.seed:04X}", 2)
        # song structure
        cols, x = [], PX
        for si, sec in enumerate(r.sections):
            w = round(sec['bars'] / r.total * PW) if si < len(r.sections) - 1 else PX + PW - x
            cols.append((x, w))
            x += w
        start = 0
        for si, (sec, (x, w)) in enumerate(zip(r.sections, cols)):
            cur = si == r.sec_i
            if w > len(sec['name']):
                self.put(yb + 5, x, sec['name'], 8 if cur else 3, curses.A_BOLD if cur else 0)
            for c in range(w - 1 if si < len(cols) - 1 else w):
                b = start + int(c * sec['bars'] / max(1, w - 1))
                pair = 5 if b < r.bar else (8 if b == r.bar else 3)
                self.put(yb + 6, x + c, '█' if b == r.bar else '▀', pair)
            start += sec['bars']
        bar_s = 240.0 / e.bpm
        frac, _ = self.step_frac()
        el, tot = (max(0, r.bar) + frac) * bar_s, r.total * bar_s
        self.put(yb + 7, PX, f"{int(el // 60):02d}:{int(el % 60):02d} / {int(tot // 60):02d}:{int(tot % 60):02d}", 2)
        sec = r.sections[r.sec_i]
        self.put(yb + 7, 40, f"{sec['name']} {r.bs + 1}/{sec['bars']}", 3)
        ch = f"{r.chord_now}  →  {r.chord_next}"
        self.put(yb + 7, PX + PW - len(ch), ch, 5, curses.A_BOLD)
        self.draw_dj(yb + 8, bar_s, frac)
        self.draw_noise(yb + 8, PX + PW - 18)
        if now - self.msg_t < 1.6 and not self.typing:
            self.put(yb + 9, PX, f"› {self.msg}"[:50], 8, curses.A_BOLD)
        if self.typing:
            self.draw_prompt(yb + 9, now)
        else:
            self.draw_remix_status(yb + 9, now)
            self.hints(yb + 10, PX + PW, [("- =", "tempo"), ("/", "rnd bpm"), ("'", "auto"), ("V", "voice"),
                                          ("M", "mode"), ("shift-V", "type"), (">", "next"), ("SPACE", "pause"),
                                          ("R", "studio"), ("?", "help")], right=True)

    def draw_player(self, H, now):
        e, pl = self.e, self.e.player
        vh = min(22, H - 16)
        y = max(0, (H - 16 - vh) // 2)
        self.pix(y, PX, "PLAYER", 5)
        self.put(y, 29, "BLIP-16 FM", 2)
        blink = int(now * 1.5) % 2 == 0
        st = ("■ END" if pl.ended else "‖ PAUSED" if pl.paused else "◌ LOADING" if pl.buffering
              else ("● PLAYING" if blink else "○ PLAYING"))
        self.put(y + 1, 29, st, 4 if st.endswith("PLAYING") and blink else 3)
        self.put(y + 2, 29, "◆ OPEN", 5, curses.A_BOLD)
        self.hit(y + 2, y + 2, 29, 34, lambda mx, ev: ev == 'click' and self.start_typing('open'))
        self.pix(y, PX + PW - 20, time.strftime("%H:%M"), 2)
        self.draw_viz(y + 4, PX, PW, vh, now)
        yb = y + 5 + vh
        latin = re.sub(r'[^A-Za-z0-9 \-]', '', pl.name).strip().upper()
        self.pix(yb, PX, (latin or "NOW PLAYING")[:24], 8)
        self.put(yb + 3, PX, pl.name[:PW], 1, curses.A_BOLD)
        dur = pl.dur or 0
        t = pl.time
        frac = min(1.0, t / dur) if dur else 0.0
        p = int(frac * (PW - 1))
        self.put(yb + 5, PX, '▀' * p, 5)
        self.put(yb + 5, PX + p, '█', 8)
        self.put(yb + 5, PX + p + 1, '▀' * (PW - p - 1), 3)
        if dur:
            self.hit(yb + 5, yb + 5, PX, PX + PW - 1,
                     lambda mx, ev: ev == 'click' and pl.seek((mx - PX) / (PW - 1) * dur))
        tot = f"{int(dur // 60):02d}:{int(dur % 60):02d}" if dur else "--:--"
        self.put(yb + 6, PX, f"{int(t // 60):02d}:{int(t % 60):02d} / {tot}", 2)
        vm = "VOCALS " + VOCAL_MODES[pl.vmode]
        self.put(yb + 6, 30, vm, 8 if pl.vmode else 2, curses.A_BOLD)
        self.hit(yb + 6, yb + 6, 30, 30 + len(vm), lambda mx, ev: ev == 'click' and self.player_key(ord('v')))
        fx = "FX " + PLAYER_FX[e.pset][0]
        self.put(yb + 6, 56, fx, 5, curses.A_BOLD)
        self.hit(yb + 6, yb + 6, 56, 56 + len(fx), lambda mx, ev: ev == 'click' and self.player_key(ord(']')))
        self.put(yb + 6, PX + PW - 10, "◆ REMIX IT", 5)
        self.hit(yb + 6, yb + 6, PX + PW - 10, PX + PW - 1, lambda mx, ev: ev == 'click' and self.player_key(ord('m')))
        self.draw_fx(yb + 8)
        if self.typing:
            self.draw_prompt(yb + 9, now)
        else:
            if now - self.msg_t < 1.6:
                self.put(yb + 9, PX, f"› {self.msg}"[:60], 8, curses.A_BOLD)
            else:
                self.draw_remix_status(yb + 9, now)
            self.hints(yb + 10, PX + PW, [("SPACE", "pause"), ("← →", "seek"), ("V", "vocals"), ("[ ]", "fx preset"),
                                          ("5-9", "fx"), ("M", "remix it"), ("shift-O", "open"), ("R", "radio"),
                                          ("?", "help")], right=True)

    def draw_prompt(self, y, now):
        label = "MUSIC FILE › " if self.tfor in ('remix', 'open') else "VOICE TEXT › "
        shown = self.tbuf[-(PW - len(label) - 2):]
        self.put(y, PX, label + shown, 8, curses.A_BOLD)
        if int(now * 2) % 2 == 0:
            self.put(y, PX + len(label) + len(shown), "█", 5)
        hint = (f"DRAG A SONG INTO THE TERMINAL (OR TYPE ITS PATH)  ·  ENTER = {'PLAY' if self.tfor == 'open' else 'ANALYSE'}  ·  ESC = CANCEL"
                if self.tfor in ('remix', 'open') else "ENGLISH LETTERS  ·  ENTER = SING IT  ·  ESC = CANCEL")
        self.put(y + 1, PX, hint, 3)

    def draw_remix_status(self, y, now):
        if self.remix and not (now - self.msg_t < 1.6):
            spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(now * 10) % 10]
            self.put(y, PX, f"{spin} ANALYSING {self.remix['name'].upper()[:40]}  ·  TEMPO · BEAT · KEY · CHORDS", 5)

    def draw_dj(self, y, bar_s, frac):
        r = self.e.radio
        self.put(y, PX, "DJ", 8 if r.dj else 3, curses.A_BOLD)
        self.hit(y, y, PX, PX + 1, lambda mx, ev: ev == 'click' and self.toggle_dj())
        if r.b is not None:
            n = 20
            k = min(n - 1, int(r.p * n))
            fader = '━' * k + '●' + '─' * (n - 1 - k)
            self.put(y, PX + 3, "MIXING", 4, curses.A_BOLD)
            self.put(y, PX + 10, f"{r.a.title[:14]}", 2)
            x = PX + 11 + min(14, len(r.a.title))
            self.put(y, x, fader, 5)
            self.put(y, x + n + 1, f"{r.b.title[:14]}  {r.a.bpm}→{r.b.bpm}", 8)
        elif r.dj:
            left = max(0.0, (r.bars_to_mix() + 1 - frac) * bar_s)
            self.put(y, PX + 3, f"AUTO-MIX ON · NEXT MIX IN {int(left // 60):02d}:{int(left % 60):02d}", 2)
        else:
            self.put(y, PX + 3, "AUTO-MIX OFF · HARD CUT BETWEEN SONGS", 3)

    # ---------- overlays ----------
    def draw_help(self, H):
        w, items = 96, [
            ("SPACE", "play / pause"), ("R", "radio <-> studio"), (">", "next radio song"),
            ("ARROWS", "move cursor"), ("ENTER", "toggle step"), ("/", "accent step"),
            ("A-;  W E T Y U O P", "play notes"), ("Z X", "octave down / up"), ("V", "loop record (studio)"),
            (", .", "change step note"), ("TAB", "next pattern"), ("\\", "copy pattern to next"),
            ("M  N", "mute / solo row"), ("C  shift-R", "clear / randomize row"),
            ("[ ]  - =", "select / adjust param"), ("1-4", "waveform"), ("5-9", "master fx"),
            ("B  shift-B", "next / prev visual"), ("I  0", "invert / fullscreen"), ("`", "colour theme"),
            ("click / wheel viz", "XY pad / visual gain"),
            ("shift-D", "DJ auto-mix on / off"), ("shift-W  { }", "noise type / level"),
            ("radio  - =  /", "tempo -/+ / random"), ("radio  \\  '", "tempo reset / auto"),
            ("radio  V  M  [ ]", "voice / mode / phrase"), ("radio  shift-V", "type your own lyrics"),
            ("shift-O  ◆ OPEN", "play a music file"), ("player  V", "vocals: full/none/only"),
            ("player  [ ]  ← →", "fx preset / seek 10 s"), ("player  M", "remix the file"),
            ("?", "this help"), ("Q", "quit")]
        half = (len(items) + 1) // 2
        h = half + 6
        y0, x0 = max(0, (H - h) // 2), (DW - w) // 2
        for r in range(h):
            self.put(y0 + r, x0, ' ' * w, 1)
        self.put(y0, x0, '⣿' * w, 3)
        self.put(y0 + h - 1, x0, '⣿' * w, 3)
        self.pix(y0 + 1, x0 + 2, "HELP", 8)
        self.put(y0 + 2, x0 + 22, "any key closes this", 3)
        for i, (k, d) in enumerate(items):
            col, row = divmod(i, half)
            x, y = x0 + 2 + col * 47, y0 + 5 + row
            self.put(y, x, k[:19], 5, curses.A_BOLD)
            self.put(y, x + 20, d[:26], 2)

    def draw_full(self, H, W, now):
        e = self.e
        self.ox, self.hits = 0, []
        pair = 41 if self.inv else 40
        hh = 5
        for y in list(range(hh)) + [H - 1]:
            self.put(y, 0, ' ' * W, pair)
        tag = e.radio.title if e.radio else TAGLINES[self.vmode]
        self.put(1, 3, tag, pair, curses.A_BOLD)
        self.put(2, 3, f"{VIZ_NAMES[self.vmode]} / {e.bpm} BPM / {THEME_ORDER[self.theme_i]}", pair)
        if now - self.msg_t < 1.6:
            self.put(3, 3, f"› {self.msg}", pair)
        if W >= 60:
            self.pix(1, W - 31, "BLIP-16", pair)
        for r, (line, rp) in enumerate(self.viz(W, H - hh - 1, now)):
            self.put(hh + r, 0, line, pair if self.inv else rp)
        for r, c, txt, lp in self.viz_labels:
            self.put(hh + r, c, txt, lp)
        hint = "0 EXIT  B MODE  I INVERT  ` THEME  SPACE PLAY"
        self.put(H - 1, max(0, W - len(hint) - 2), hint, pair)

    def draw(self):
        self.poll_remix()
        s = self.s
        H, W = s.getmaxyx()
        s.erase()
        now = time.time()
        self.hits = []
        self.update_spectrum()
        if self.full and W >= 40 and H >= 12:
            self.draw_full(H, W, now)
        elif W < DW or H < 27:
            self.ox = 0
            self.put(1, 1, f"ENLARGE TERMINAL TO {DW}x27 (now {W}x{H})", 4)
        else:
            self.ox = (W - DW) // 2
            if self.e.player is not None:
                self.draw_player(H, now)
            elif self.e.radio:
                self.draw_radio(H, now)
            else:
                self.draw_studio(H, now)
            if self.help:
                self.draw_help(H)
        s.noutrefresh()

    def run(self):
        curses.curs_set(0)
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        if hasattr(curses, 'set_escdelay'):
            curses.set_escdelay(25)   # so ESC cancels text entry immediately
        curses.mouseinterval(0)   # report presses immediately instead of waiting to build a "click"
        self.s.timeout(30)
        self.s.keypad(True)
        while True:
            self.draw()
            curses.doupdate()
            try:
                ch = self.s.get_wch()
            except curses.error:
                ch = -1
            if isinstance(ch, str) and self.typing:
                self.type_char(ch)
                continue
            if isinstance(ch, str):
                c = FA_KEYS.get(ch, ch)
                if len(c) != 1 or ord(c) > 255:
                    self.toast(f"KEY {c} IS NOT MAPPED - SWITCH KEYBOARD TO ENGLISH")
                    continue
                ch = ord(c)
            if ch == curses.KEY_RESIZE:
                continue
            if ch != -1 and not self.key(ch):
                break


def main(scr):
    sys.setswitchinterval(0.001)   # let the audio thread win the GIL quickly when the voice worker is busy
    eng = Engine()
    import sounddevice as sd   # imported here so the package imports without PortAudio (tests, CI)
    with sd.OutputStream(samplerate=SR, channels=2, blocksize=BLOCK, latency='low',
                         dtype='float32', callback=eng.cb):
        app = App(scr, eng)
        eng.radio_on()   # radio is the default mode
        app.run()


def cli():
    """Entry point for the `blip16` command and `python -m blip16`."""
    locale.setlocale(locale.LC_ALL, '')
    sys.stdout.write("\x1b[8;40;104t")  # ask the terminal for a bigger window
    sys.stdout.flush()
    time.sleep(0.15)
    curses.wrapper(main)
