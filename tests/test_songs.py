import pytest

from blip16.constants import SYN
from blip16.song import Song
from blip16.styles import STYLES, chord_name, key_dist


@pytest.mark.parametrize("style", sorted(STYLES))
def test_every_style_writes_a_whole_song(style):
    s = Song(7, style)
    assert 60 <= s.bpm <= 200 and s.total >= 32
    bars_with_kick = bars_with_lead = 0
    for _ in range(s.total):
        s.next_bar()
        bars_with_kick += any(s.pat.rows[0])
        bars_with_lead += any(s.pat.rows[SYN])
        assert s.chord_now
    assert bars_with_kick > s.total // 3
    assert bars_with_lead > 0


def test_songs_are_reproducible_from_their_seed():
    a, b = Song(42, "LOFI"), Song(42, "LOFI")
    assert (a.title, a.bpm, a.key, a.progA) == (b.title, b.bpm, b.key, b.progA)


def test_chord_names_and_key_distance():
    assert chord_name([60, 64, 67, 71]) == "Cmaj7"
    assert chord_name([57, 60, 64, 67, 71]) == "Am9"
    assert key_dist(0, 7) == 1 and key_dist(0, 6) == 6
