import numpy as np

from blip16.constants import SR
from blip16.player import VocalSplit, parse_path


def _stereo(seconds=8):
    n = seconds * SR
    t = np.arange(n) / SR
    rng = np.random.default_rng(0)
    # "vocal": dead centre, pitch moving every 0.4 s, with vibrato
    f = 220 * 2 ** (np.repeat(rng.integers(0, 7, n // int(0.4 * SR) + 1), int(0.4 * SR))[:n] / 12)
    voc = np.sin(2 * np.pi * np.cumsum(f * (1 + 0.004 * np.sin(2 * np.pi * 5 * t))) / SR) * 0.3
    pad = sum(np.sin(2 * np.pi * fr * t) for fr in (130.8, 164.8, 196.0)) * 0.1
    left, right = voc + pad * 0.9, voc + pad * 0.2              # the accompaniment is panned
    return np.stack([left, right], 1).astype(np.float32), voc, pad


def _run(x, mode):
    sp = VocalSplit()
    y = np.concatenate([sp.process(x[i:i + 16384], mode) for i in range(0, len(x), 16384)])
    lag = VocalSplit.N - VocalSplit.H
    return y[lag:]


def _share(y, a, b):
    n = len(y)
    coef, *_ = np.linalg.lstsq(np.stack([a[:n], b[:n]], 1), y, rcond=None)
    return coef


def test_no_vocals_and_vocals_only():
    x, voc, pad = _stereo()
    v_kept, _ = _share(_run(x, 1), voc, pad * 0.55)
    v_iso, p_iso = _share(_run(x, 2), voc, pad * 0.55)
    assert abs(v_kept) < 0.25          # vocal mostly gone
    assert v_iso > 0.7 and abs(p_iso) < 0.4


def test_dropped_paths_are_unescaped():
    assert parse_path(r"/tmp/my\ song\ \(live\).mp3") == "/tmp/my song (live).mp3"
    assert parse_path("'/tmp/a b.wav'") == "/tmp/a b.wav"
