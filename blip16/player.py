"""Plays a music file through the master effects, with optional vocal removal / isolation."""
import collections
import multiprocessing
import os
import re
import shutil
import subprocess
import threading
import time
import wave

import numpy as np

from .constants import SR


# ---------- file player: play a song through BLIP's radio effects, optionally without / only the vocals ----------
VOCAL_MODES = ['FULL MIX', 'NO VOCALS', 'VOCALS ONLY']


# name, fx on (filter, crush, stutter, tape, reverb), fx amounts, vinyl, AM-radio band
PLAYER_FX = [('CLEAN', [False] * 5, [0, 0, 0, 0, 0], 0.0, False),
             ('LOFI RADIO', [True, True, False, True, True], [.3, .12, .3, .35, .3], 0.7, False),
             ('AM RADIO', [False, True, False, True, False], [0, .18, .3, .15, 0], 0.5, True),
             ('SPACE', [False, False, False, True, True], [0, 0, .3, .15, .75], 0.0, False),
             ('UNDERWATER', [True, False, False, True, True], [.75, 0, .3, .3, .5], 0.0, False),
             ('CRUSHED', [False, True, False, False, False], [0, .6, .3, 0, 0], 0.0, False)]


def parse_path(raw):
    """A path as typed or dropped into a terminal: quotes and backslash escapes removed, ~ expanded."""
    return os.path.expanduser(re.sub(r'\\(.)', r'\1', raw.strip().strip('\'"')))


def probe_duration(path):
    if shutil.which('ffprobe'):
        try:
            r = subprocess.run(['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                               capture_output=True, text=True, timeout=20)
            return float(r.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        with wave.open(path) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, OSError, EOFError):
        return None


def _pcm_chunks(path, start, n=16384):
    """Stereo float32 chunks at SR from `start` seconds: ffmpeg for any format, wave module as fallback."""
    if shutil.which('ffmpeg'):
        p = subprocess.Popen(['ffmpeg', '-v', 'quiet', '-ss', f'{start:.2f}', '-i', path, '-f', 'f32le', '-ac', '2',
                              '-ar', str(SR), '-'], stdout=subprocess.PIPE)
        try:
            while True:
                raw = p.stdout.read(n * 8)
                if not raw:
                    return
                yield np.frombuffer(raw[:len(raw) // 8 * 8], '<f4').reshape(-1, 2)
        finally:
            p.kill()
    else:
        with wave.open(path) as w:
            ch, sw, fs = w.getnchannels(), w.getsampwidth(), w.getframerate()
            w.setpos(min(w.getnframes(), int(start * fs)))
            while True:
                raw = w.readframes(n)
                if not raw:
                    return
                if sw == 2:
                    a = np.frombuffer(raw, '<i2') / 32768.0
                elif sw == 4:
                    a = np.frombuffer(raw, '<i4') / 2.0 ** 31
                else:
                    a = (np.frombuffer(raw, 'u1').astype(float) - 128) / 128.0
                a = a[:len(a) // ch * ch].reshape(-1, ch)
                a = np.repeat(a, 2, axis=1) if ch == 1 else a[:, :2]
                if fs != SR:
                    t = np.arange(int(len(a) * SR / fs)) * fs / SR
                    a = np.stack([np.interp(t, np.arange(len(a)), a[:, c]) for c in range(2)], 1)
                yield a.astype(np.float32)


class VocalSplit:
    """Streaming vocal separation for stereo mixes (STFT 4096 / hop 1024, sqrt-Hann).

    A frequency bin is treated as 'voice' when it is centre-panned, phase-coherent between L and R,
    steady over the last frames (a drum hit is not) and inside the voice band. NO VOCALS keeps the rest
    plus the side channel; VOCALS ONLY keeps the masked centre. Mono files have no L/R difference, so
    only the steady-vs-percussive part of the test can work there."""
    N, H = 4096, 1024

    def __init__(self):
        N = self.N
        self.win = np.sqrt(np.hanning(N + 1)[:N]).astype(np.float32)
        self.inb = np.zeros((N, 2), np.float32)
        self.outb = np.zeros(N, np.float32)
        self.pending = np.zeros((0, 2), np.float32)
        f = np.fft.rfftfreq(N, 1 / SR)
        self.band = (np.clip((f - 120) / 80, 0, 1) * np.clip((8000 - f) / 1500, 0, 1)).astype(np.float32)
        self.hist = collections.deque(maxlen=9)

    def process(self, x, mode):
        self.pending = np.vstack([self.pending, x])
        N, H, out = self.N, self.H, []
        while len(self.pending) >= H:
            self.inb = np.vstack([self.inb[H:], self.pending[:H]])
            self.pending = self.pending[H:]
            F = np.fft.rfft(self.inb * self.win[:, None], axis=0)
            L, R = F[:, 0], F[:, 1]
            aL, aR = np.abs(L), np.abs(R)
            M, S = (L + R) / 2, (L - R) / 2
            pan = (aL - aR) / (aL + aR + 1e-9)
            coh = np.clip(np.real(L * np.conj(R)) / (aL * aR + 1e-9), 0, 1)
            aM = np.abs(M)
            self.hist.append(aM)
            steady = np.clip(np.median(np.array(self.hist), axis=0) / (aM + 1e-9), 0, 1) ** 0.15
            mask = np.clip(np.exp(-(pan / 0.25) ** 2) * coh * steady * self.band * 2.0, 0, 1)
            Y = M * (1 - mask) + S * 0.8 if mode == 1 else M * mask
            self.outb += np.fft.irfft(Y, N).astype(np.float32) * self.win
            out.append(self.outb[:H] * 0.5)          # sqrt-Hann in and out at 75% overlap sums to 2
            self.outb = np.r_[self.outb[H:], np.zeros(H, np.float32)]
        return np.concatenate(out) if out else np.zeros(0, np.float32)


def _player_proc(path, start, vmode, conn):
    """Decodes (and separates) in its own process and streams mono float32 to the app."""
    sep = VocalSplit() if vmode else None
    try:
        for x in _pcm_chunks(path, start):
            y = (x[:, 0] + x[:, 1]) * 0.5 if sep is None else sep.process(x, vmode)
            conn.send_bytes(y.astype(np.float32).tobytes())
        conn.send_bytes(b'')
    except (BrokenPipeError, EOFError, OSError, ValueError):
        pass


class FilePlayer:
    """Buffers audio streamed from _player_proc. Seeking or changing the vocal mode restarts the stream."""

    def __init__(self, path):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.dur = probe_duration(path)
        self.vmode, self.paused, self.gen, self.proc = 0, False, 0, None
        self.lock = threading.Lock()
        self.chunks = collections.deque()
        self.avail = 0
        self.start_at(0.0)

    def start_at(self, t):
        self.close()
        ctx = multiprocessing.get_context('spawn')
        rx, tx = ctx.Pipe(duplex=False)
        self.proc = ctx.Process(target=_player_proc, args=(self.path, t, self.vmode, tx), daemon=True)
        self.proc.start()
        tx.close()
        with self.lock:
            self.chunks.clear()
            self.avail = 0
        self.t0, self.played, self.eof, self.ended = t, 0, False, False
        self.gen += 1
        threading.Thread(target=self._reader, args=(self.gen, rx), daemon=True).start()

    def _reader(self, g, rx):
        try:
            while g == self.gen:
                if self.avail > 8 * SR:
                    time.sleep(0.05)
                    continue
                data = rx.recv_bytes()
                if not data:
                    break
                arr = np.frombuffer(data, np.float32)
                with self.lock:
                    if g != self.gen:
                        break
                    self.chunks.append(arr)
                    self.avail += len(arr)
        except (EOFError, OSError):
            pass
        finally:
            if g == self.gen:
                self.eof = True
            rx.close()

    def read(self, n):
        out = np.zeros(n, np.float32)
        if self.paused:
            return out
        got = 0
        with self.lock:
            while got < n and self.chunks:
                c = self.chunks[0]
                k = min(n - got, len(c))
                out[got:got + k] = c[:k]
                if k == len(c):
                    self.chunks.popleft()
                else:
                    self.chunks[0] = c[k:]
                got += k
            self.avail -= got
        self.played += got
        if got < n and self.eof and not self.chunks:
            self.ended = True
        return out

    @property
    def time(self):
        return self.t0 + self.played / SR

    @property
    def buffering(self):
        return not self.paused and not self.ended and self.avail == 0

    def seek(self, t):
        end = self.dur if self.dur else t + 1
        self.start_at(max(0.0, min(t, end - 1)))

    def close(self):
        self.gen += 1
        if self.proc is not None and self.proc.is_alive():
            self.proc.terminate()
