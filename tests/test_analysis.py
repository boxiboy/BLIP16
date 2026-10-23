import numpy as np

from blip16.analysis import ASR, analyze_audio, song_from_analysis
from blip16.dsp import mtof


def _track(bpm=120, bars=24, sr=ASR):
    """Four-on-the-floor kick, a C minor progression and a simple sine melody."""
    bar = int(sr * 240 / bpm)
    step = bar // 16
    prog = [[60, 63, 67], [65, 68, 72], [67, 70, 74], [63, 67, 70]]
    melody = [(0, 72), (4, 75), (8, 79), (12, 77)]
    t = np.arange(bar) / sr
    out = []
    for k in range(bars):
        y = sum(np.sin(2 * np.pi * mtof(m) * t) for m in prog[k % 4]) * 0.15
        for st, m in melody:
            tt = np.arange(step * 3) / sr
            y[st * step:st * step + len(tt)] += np.sin(2 * np.pi * mtof(m) * tt) * np.exp(-tt * 3) * 0.5
        for q in range(4):
            tk = np.arange(5000) / sr
            y[q * bar // 4:q * bar // 4 + 5000] += np.sin(2 * np.pi * (50 * tk + 15 * (1 - np.exp(-30 * tk)))) * np.exp(-tk * 12)
        out.append(y)
    return np.concatenate(out).astype(np.float32)


def test_tempo_beat_and_kick_pattern():
    an = analyze_audio(_track(bpm=120))
    assert abs(an["bpm"] - 120) < 1.0
    assert an["drums"][0] == "x...x...x...x..."
    assert an["bars"] >= 20


def test_key_and_melody():
    an = analyze_audio(_track(bpm=118))
    scale = {(an["key"] + d) % 12 for d in (0, 2, 3, 5, 7, 8, 10)} if an["mode"] != "major" else \
            {(an["key"] + d) % 12 for d in (0, 2, 4, 5, 7, 9, 11)}
    assert {0, 3, 7, 5, 8} <= scale                       # C minor / E-flat major family
    notes = [m % 12 for bar in an["melody"].values() for _, m, _ in bar]
    assert len(notes) > 20
    assert np.mean([n in (0, 3, 7, 5) for n in notes]) > 0.7


def test_remix_song_plays_the_extracted_melody():
    an = analyze_audio(_track())
    an["name"] = "test track"
    s = song_from_analysis(an, 1)
    assert s.style == "REMIX" and s.title.startswith("REMIX")
    first = min(an["melody"])
    for _ in range(first + 1):
        s.next_bar()
    played = [(i, m) for i, m in enumerate(s.pat.rows[-1]) if m]
    assert played == [(st, m) for st, m, _ in an["melody"][first]]
