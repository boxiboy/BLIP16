"""Musical material for the radio: scales, instrument presets, genre definitions, chord naming."""
from .constants import NOTE


# ---------- radio: musical material ----------
SCALES = {'major': [0, 2, 4, 5, 7, 9, 11], 'dorian': [0, 2, 3, 5, 7, 9, 10], 'aeolian': [0, 2, 3, 5, 7, 8, 10]}


# instrument presets for radio voices (osc1, osc2 ratio/level, sub, ADSR, gain)
INST = {
    'keys':  dict(w1=3, w2=3, r2=2.0, l2=0.30, sub=0.0, atk=0.004, dec=0.9, sus=0.25, rel=0.35, gain=0.20),
    'stab':  dict(w1=1, w2=0, r2=2.003, l2=0.45, sub=0.0, atk=0.002, dec=0.18, sus=0.0, rel=0.06, gain=0.15),
    'pad':   dict(w1=0, w2=0, r2=1.006, l2=0.90, sub=0.0, atk=0.35, dec=1.2, sus=0.8, rel=0.9, gain=0.10),
    'sub':   dict(w1=3, w2=2, r2=1.0, l2=0.25, sub=0.0, atk=0.006, dec=0.35, sus=0.7, rel=0.07, gain=0.50),
    'hbass': dict(w1=2, w2=3, r2=2.0, l2=0.20, sub=0.3, atk=0.003, dec=0.12, sus=0.4, rel=0.05, gain=0.42),
    'obass': dict(w1=2, w2=0, r2=1.004, l2=0.35, sub=0.4, atk=0.003, dec=0.15, sus=0.5, rel=0.05, gain=0.30),
    'chip':  dict(w1=1, w2=1, r2=2.0, l2=0.25, sub=0.0, atk=0.001, dec=0.09, sus=0.2, rel=0.04, gain=0.12),
    'cbass': dict(w1=2, w2=1, r2=1.0, l2=0.15, sub=0.0, atk=0.001, dec=0.10, sus=0.6, rel=0.03, gain=0.40),
    'organ': dict(w1=3, w2=3, r2=3.0, l2=0.50, sub=0.6, atk=0.002, dec=0.25, sus=0.15, rel=0.08, gain=0.16),
}


# drum templates: X accent, x hit, digit = probability/10 ghost, . rest
STYLES = {
    'LOFI': dict(
        bpm=(70, 88), swing=(0.10, 0.18), modes=['major', 'major', 'dorian'], ninth=0.7,
        progs=[[1, 4, 0, 0], [3, 2, 1, 0], [0, 5, 1, 4], [3, 4, 2, 5], [5, 3, 0, 4], [1, 4, 2, 5], [0, 3, 2, 5]],
        chord='keys', bass='sub', density=0.2,
        lead=dict(wave=2, cut=.42, res=.2, env=.2, drv=.08, atk=.12, rel=.55, det=.15, sub=0.0, dly=.32),
        fx_on=[False, True, False, True, True], fx_amt=[0, .12, .3, .35, .35],
        vinyl=.8, dust=True, duck=.25, pcut=.55,
        drums={0: ["x......x..x.....", "x.....x...x..4..", "x......3.x......", "x.....x.x......."],
               1: ["....x.......x...", "....x.......x..2", "....x..2....x..."],
               2: ["................", "............3..."],
               3: ["x.x.x.x.x.x.x.x.", "x.x.x.x.x.x.x3x.", "x3x.x.x3x.x.x.x3"],
               4: ["................", "..............3.", "......3........."]},
        form=[('INTRO', 4, 'CH', .55, .15), ('VERSE', 8, 'KSHBC', 0, 0), ('HOOK', 8, 'KSHOBCL', 0, 0),
              ('BREAK', 4, 'CL', .45, .3), ('VERSE', 8, 'KSHBCL', 0, 0), ('HOOK', 8, 'KSHOBCL', 0, 0),
              ('DRIFT', 8, 'HBCL', .25, .25), ('VERSE', 8, 'KSHBC', 0, 0), ('HOOK', 8, 'KSHOBCL', 0, 0),
              ('HOOK', 8, 'KSHOBCL', 0, 0), ('OUTRO', 4, 'CH', .1, .6)]),
    'HOUSE': dict(
        bpm=(118, 124), swing=(0.0, 0.06), modes=['dorian', 'aeolian'], ninth=0.5,
        progs=[[0, 3], [0, 0, 3, 3], [0, 5, 2, 6], [0, 6, 5, 6], [0, 3, 6, 5]],
        chord='stab', bass='hbass', density=0.12,
        lead=dict(wave=1, cut=.5, res=.45, env=.55, drv=.2, atk=0.0, rel=.22, det=.3, sub=0.0, dly=.28),
        fx_on=[False, False, False, False, True], fx_amt=[0, 0, .35, 0, .25],
        vinyl=0.0, dust=False, duck=.55, pcut=.6,
        drums={0: ["x...x...x...x...", "x...x...x...x..3"],
               1: ["................", ".............3..", "...........2...."],
               2: ["....x.......x...", "....x.......x..3"],
               3: ["..x...x...x...x.", "3.x.3.x.3.x.3.x.", "x3x3x3x3x3x3x3x3"],
               4: ["..x...x...x...x.", "..............x.", "......x.......x."]},
        form=[('INTRO', 16, 'KH', .6, .05), ('BUILD', 8, 'KHOB', 0, 0), ('GROOVE', 16, 'KSHOBC', 0, 0),
              ('BREAK', 8, 'CL', .35, .1), ('DROP', 16, 'KSHOBCL', 0, 0), ('GROOVE', 16, 'KSHOBC', 0, 0),
              ('OUTRO', 16, 'KHB', 0, .6)]),
    'SYNTH': dict(
        bpm=(90, 104), swing=(0.0, 0.04), modes=['aeolian', 'aeolian', 'dorian'], ninth=0.4,
        progs=[[0, 5, 2, 6], [5, 6, 0, 0], [0, 6, 5, 6], [0, 2, 6, 5], [0, 5, 3, 4]],
        chord='pad', bass='obass', density=0.3,
        lead=dict(wave=0, cut=.55, res=.3, env=.4, drv=.15, atk=.04, rel=.45, det=.5, sub=.2, dly=.42),
        fx_on=[False, False, False, True, True], fx_amt=[0, 0, .3, .15, .5],
        vinyl=.15, dust=False, duck=.35, pcut=.45,
        drums={0: ["x.......x.x.....", "x...x...x...x...", "x.......x.x...3."],
               1: ["....x.......x...", "....x.......x..3"],
               2: ["....x.......x...", "................"],
               3: ["x.x.x.x.x.x.x.x.", "xxxxxxxxxxxxxxxx", "x.x.x.x.x.x.x3x3"],
               4: ["................", "......3.......5.", "..............x."]},
        form=[('INTRO', 8, 'C', .5, .1), ('VERSE', 16, 'KSHBC', 0, 0), ('CHORUS', 16, 'KSHOBCL', 0, 0),
              ('BRIDGE', 8, 'CL', .3, .3), ('CHORUS', 16, 'KSHOBCL', 0, 0), ('OUTRO', 8, 'CB', .1, .6)]),
}


# how each style comps chords, plays bass, fills, and how long a DJ mix into the next song lasts
STYLES['LOFI'].update(fill='lofi', comp='keys', bassline='lofi', mix=8)


STYLES['HOUSE'].update(fill='house', comp='stabs', bassline='house', mix=16)


STYLES['SYNTH'].update(fill='synth', comp='pad', bassline='octave', mix=8, lfo=True)


STYLES.update({
    'CHIP': dict(
        bpm=(124, 132), swing=(0.0, 0.02), modes=['major', 'dorian'], ninth=0.2,
        progs=[[0, 4, 5, 3], [5, 3, 0, 4], [0, 5, 3, 4], [3, 4, 0, 0]],
        chord='chip', bass='cbass', density=0.45,
        lead=dict(wave=1, cut=.7, res=.2, env=.3, drv=.1, atk=0.0, rel=.12, det=.05, sub=0.0, dly=.2),
        fx_on=[False, True, False, False, True], fx_amt=[0, .25, .3, 0, .2],
        vinyl=0.0, dust=False, duck=.45, pcut=.8,
        drums={0: ["x...x...x...x...", "x...x...x...x.x."], 1: ["....x.......x...", "....x.......x.xx"],
               2: ["................"], 3: ["x.x.x.x.x.x.x.x.", "xxxxxxxxxxxxxxxx"],
               4: ["..x...x...x...x.", "................"]},
        form=[('INTRO', 8, 'KH', .5, 0), ('LEVEL 1', 16, 'KSHBC', 0, 0), ('BOSS', 16, 'KSHOBCL', 0, 0),
              ('BONUS', 8, 'CL', .3, .1), ('LEVEL 2', 16, 'KSHOBCL', 0, 0), ('OUTRO', 8, 'KHB', 0, .5)],
        fill='synth', comp='stabs', bassline='octave', mix=8),
    'DEEP': dict(
        bpm=(116, 122), swing=(0.04, 0.09), modes=['dorian', 'aeolian'], ninth=0.9,
        progs=[[0, 3], [0, 6, 5, 3], [0, 0, 5, 5], [3, 0, 6, 0]],
        chord='keys', bass='hbass', density=0.1,
        lead=dict(wave=3, cut=.5, res=.2, env=.2, drv=.05, atk=.08, rel=.5, det=.1, sub=0.0, dly=.4),
        fx_on=[False, False, False, True, True], fx_amt=[0, 0, .3, .12, .4],
        vinyl=.2, dust=True, duck=.4, pcut=.5,
        drums={0: ["x...x...x...x..."], 1: [".......3.......2", "................"],
               2: ["....x.......x..."], 3: ["..x...x...x...x.", "3.x.3.x.3.x.3.x."],
               4: ["..x...x...x...x.", "......x.......x."]},
        form=[('INTRO', 16, 'KH', .5, .1), ('GROOVE', 16, 'KSHBC', 0, 0), ('DEEP', 16, 'KSHOBCL', 0, 0),
              ('BREAK', 8, 'CL', .4, .2), ('GROOVE', 16, 'KSHOBC', 0, 0), ('OUTRO', 16, 'KHB', 0, .6)],
        fill='house', comp='keys', bassline='house', mix=16),
    'DREAM': dict(
        bpm=(80, 92), swing=(0.04, 0.1), modes=['major', 'dorian'], ninth=0.8,
        progs=[[0, 5, 3, 4], [3, 0, 4, 5], [0, 2, 3, 4], [5, 3, 0, 0]],
        chord='pad', bass='sub', density=0.14,
        lead=dict(wave=2, cut=.4, res=.15, env=.15, drv=0.0, atk=.2, rel=.7, det=.2, sub=0.0, dly=.5),
        fx_on=[False, False, False, True, True], fx_amt=[0, 0, .3, .2, .6],
        vinyl=.3, dust=True, duck=.15, pcut=.4,
        drums={0: ["x.........x.....", "x.......x......."], 1: ["........x......."],
               2: ["................"], 3: ["x...x...x...x...", "x.x.x.x.x.x.x.x."],
               4: ["................"]},
        form=[('INTRO', 8, 'C', .5, .2), ('DRIFT', 16, 'CHB', 0, 0), ('FLOAT', 16, 'KSHBCL', 0, 0),
              ('AIR', 8, 'CL', .3, .3), ('FLOAT', 16, 'KSHOBCL', 0, 0), ('OUTRO', 8, 'C', .1, .6)],
        fill='lofi', comp='pad', bassline='lofi', mix=8, lfo=True),
})


STYLES['FRENCH'] = dict(
    bpm=(120, 126), swing=(0.0, 0.03), modes=['dorian', 'aeolian', 'major'], ninth=0.6,
    progs=[[0, 3, 6, 3], [0, 5, 3, 4], [0, 6, 0, 5], [3, 0, 4, 5]],
    chord='stab', bass='hbass', density=0.14,
    lead=dict(wave=0, cut=.5, res=.5, env=.6, drv=.3, atk=0.0, rel=.2, det=.4, sub=0.0, dly=.3),
    fx_on=[True, False, False, False, True], fx_amt=[0, 0, .35, 0, .22],
    vinyl=0.0, dust=False, duck=.65, pcut=.7,
    drums={0: ["x...x...x...x..."],
           1: ["................", "...............3"],
           2: ["....x.......x...", "....x.......x..3"],
           3: ["x3x3x3x3x3x3x3x3", "3.x.3.x.3.x.3.x."],
           4: ["..x...x...x...x."]},
    form=[('INTRO', 16, 'KH', .75, .05), ('BUILD', 16, 'KSHBC', .5, 0), ('GROOVE', 16, 'KSHOBCL', 0, 0),
          ('BREAK', 8, 'CL', .55, .1), ('GROOVE', 16, 'KSHOBCL', .05, .0), ('SWEEP', 8, 'KSHOBCL', 0, .6),
          ('OUTRO', 16, 'KHB', 0, .75)],
    fill='house', comp='stabs', bassline='octave', mix=16)


WORDS_A = ['SOFT', 'NIGHT', 'LATE', 'PALE', 'SLOW', 'BLUE', 'WARM', 'STATIC', 'GLASS', 'QUIET',
           'NEON', 'RAINY', 'LOST', 'HAZY', 'GOLDEN', 'PAPER', 'VELVET', 'EARLY', 'DISTANT', 'FADED']


WORDS_B = ['CIRCUIT', 'RAIN', 'TAPE', 'SIGNAL', 'WINDOW', 'BUS', 'GARDEN', 'ORBIT', 'CITY', 'MEMORY',
           'STATION', 'DRIFT', 'SUNDAY', 'STUDY', 'PIXEL', 'HALLWAY', 'LIGHTS', 'ROOM', 'COFFEE', 'TRAIN']


def chord_name(tones):
    r = tones[0]
    q = ((tones[1] - r) % 12, (tones[2] - r) % 12, (tones[3] - r) % 12)
    nine = len(tones) > 4
    name = {(4, 7, 11): 'maj9' if nine else 'maj7', (3, 7, 10): 'm9' if nine else 'm7',
            (4, 7, 10): '9' if nine else '7', (3, 6, 10): 'm7b5'}.get(q, '')
    return NOTE[r % 12] + name


def key_dist(a, b):
    """Distance between two keys on the circle of fifths."""
    d = abs((a * 7) % 12 - (b * 7) % 12)
    return min(d, 12 - d)
