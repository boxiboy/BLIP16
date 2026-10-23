import random

import numpy as np
import pytest

from blip16.constants import SR
from blip16.voice import VOICE_MODES, VoiceBox, make_line, render_syllable, text_to_syllables


def test_syllables_and_stress():
    syls = text_to_syllables("dance in the machine")
    assert [s["v"] for s in syls] == ["a", "i", "e", "a", "i"]
    assert syls[0]["stress"] and not syls[1]["stress"]       # "in" is a function word
    assert text_to_syllables("1234 !!") == []


def test_random_lines_are_varied():
    rng = random.Random(3)
    lines = {make_line(rng) for _ in range(30)}
    assert len(lines) > 20


def test_flow_puts_stressed_syllables_on_the_beat():
    rng = random.Random(5)
    hits = []
    for _ in range(40):
        syls = text_to_syllables(make_line(rng))
        for s, p in zip(syls, VoiceBox.flow(syls, rng)):
            if s["stress"]:
                hits.append(p % 4 in (0, 3))       # on the beat, or pushed a 16th early
    assert np.mean(hits) > 0.9


def _low_high_ratio(y):
    sp = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    f = np.fft.rfftfreq(len(y), 1 / SR)
    return sp[(f > 600) & (f < 1400)].sum() / sp[(f > 2000) & (f < 3200)].sum()


@pytest.mark.parametrize("mode", range(len(VOICE_MODES)))
def test_every_voice_mode_keeps_vowels_apart(mode):
    n = int(0.3 * SR)
    a, pre = render_syllable(57, dict(on=["S"], v="a", co=[], stress=True, end=True), n, mode)
    i, _ = render_syllable(57, dict(on=[], v="i", co=[], stress=True, end=True), n, mode)
    assert np.isfinite(a).all() and 0 < pre < n // 2       # the vowel starts after the "s"
    assert _low_high_ratio(a) > 1.5 * _low_high_ratio(i)
