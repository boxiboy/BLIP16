"""Small DSP building blocks: oscillators, state-variable filter, drum samples, dither + noise textures."""
import numpy as np

from .constants import NOTE, SR


def note_name(m):
    return f"{NOTE[m % 12]}{m // 12 - 1}"


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def make_drums():
    rng = np.random.default_rng(7)
    ts = lambda d: np.arange(int(SR * d)) / SR
    norm = lambda x, g: (x / np.abs(x).max() * g).astype(np.float32)

    t = ts(0.4)
    ph = 2 * np.pi * (45 * t + (110 / 28) * (1 - np.exp(-28 * t)))
    kick = np.sin(ph) * np.exp(-t * 7.5) + 0.5 * rng.standard_normal(len(t)) * np.exp(-t * 400)
    kick = norm(np.tanh(kick * 1.8), 0.9)

    t = ts(0.25)
    snare = rng.standard_normal(len(t)) * np.exp(-t * 18) * 0.7 + np.sin(2 * np.pi * 185 * t) * np.exp(-t * 22) * 0.6
    snare = norm(np.tanh(snare * 1.5), 0.8)

    t = ts(0.3)
    n = np.convolve(rng.standard_normal(len(t) + 2), [1, 2, 1], 'valid')[:len(t)]
    env = np.exp(-t * 20) * 0.5
    for off in (0.0, 0.011, 0.022):
        env += np.where(t >= off, np.exp(-np.clip(t - off, 0, None) * 220), 0)
    clap = norm(n * env, 0.8)

    t = ts(0.07)
    hat = norm(np.diff(rng.standard_normal(len(t) + 1)) * np.exp(-t * 70), 0.7)
    t = ts(0.35)
    ohat = norm(np.diff(rng.standard_normal(len(t) + 1)) * np.exp(-t * 12), 0.6)
    return [kick, snare, clap, hat, ohat]


def svf_run(x, f, q, st):
    low, band = st
    out = [0.0] * len(x)
    for i, s in enumerate(x.tolist()):
        low += f * band
        band += f * (s - low - q * band)
        out[i] = low
    return np.array(out), ([low, band] if abs(low) + abs(band) > 1e-6 else [0.0, 0.0])


def make_bayer(n=8):
    m = np.array([[0, 2], [3, 1]])
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return m


def make_cloud(n=256):
    """Tileable cloud texture: 1/f noise, rank-normalised to uniform 0..1."""
    rng = np.random.default_rng(3)
    F = np.fft.fft2(rng.standard_normal((n, n)))
    r = np.sqrt(np.fft.fftfreq(n)[:, None] ** 2 + np.fft.fftfreq(n)[None, :] ** 2)
    r[0, 0] = 1
    F = F / r ** 1.6
    F[0, 0] = 0
    t = np.fft.ifft2(F).real.ravel()
    return (t.argsort().argsort() / t.size).reshape(n, n)


def osc(wave, p):
    p = p % 1.0
    if wave == 0:
        return 2 * p - 1
    if wave == 1:
        return np.where(p < 0.5, 1.0, -1.0)
    if wave == 2:
        return 4 * np.abs(p - 0.5) - 1
    return np.sin(2 * np.pi * p)
