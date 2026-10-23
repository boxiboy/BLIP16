import numpy as np

from blip16.constants import NOISES
from blip16.engine import Engine

from conftest import render


def test_studio_pattern_plays_cleanly():
    e = Engine()
    e.play()
    x = render(e, 4)
    assert np.isfinite(x).all()
    assert 0.05 < np.abs(x).max() <= 1.0
    assert e.tick > 0


def test_every_master_effect_is_stable():
    e = Engine()
    e.play()
    for k in range(5):
        e.fx = [i == k for i in range(5)]
        x = render(e, 1.5)
        assert np.isfinite(x).all() and np.abs(x).max() <= 1.0


def test_noise_types_have_similar_levels():
    e = Engine()
    levels = []
    for kind in range(1, len(NOISES)):
        e.noise = kind
        render(e, 0.5)
        levels.append(np.std(e.noise_block(4096)))
    assert all(0.01 < lv < 0.1 for lv in levels), levels


def test_radio_mixes_into_the_next_song_on_the_beat():
    e = Engine()
    e.radio_on()
    r = e.radio
    first = r.a.title
    r.skip = True                     # with DJ on this starts a 4-bar mix on the next bar
    render(e, 1)
    assert r.b is not None and r.T == 4
    render(e, 12)
    assert r.b is None and r.a.title != first
    assert 60 <= e.bpm <= 200


def test_radio_tempo_control_survives_song_changes():
    e = Engine()
    e.radio_on()
    r = e.radio
    render(e, 1)
    target = r.set_tempo(r.a.bpm + 20)
    assert e.bpm == target
    r.skip = True
    render(e, 14)
    assert abs(r.mul - target / r.a.bpm) < 0.5        # the speed-up carries over as a ratio
    assert r.set_tempo(10) == 60 and r.set_tempo(999) == 200
