"""Shared constants: audio format, track layout, synth parameters, pixel font, colour themes, key maps."""



SR = 44100


BLOCK = 512


STEPS = 16


FFT_N = 4096


NAMES = ['KICK', 'SNARE', 'CLAP', 'HAT', 'OHAT', 'SYNTH']


NT = len(NAMES)


SYN = NT - 1


WAVES = ['SAW', 'SQR', 'TRI', 'SIN']


WAVE_ART = ['⣀⠤⠒⠉⣀⠤⠒⠉', '⠉⠉⣀⣀⠉⠉⣀⣀', '⣀⠤⠒⠉⠉⠒⠤⣀', '⠤⠒⠉⠒⠤⣀⣀⠤']


NOISES = ['OFF', 'WHITE', 'PINK', 'BROWN', 'RAIN']


NOTE = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


PIANO = {'a': 0, 'w': 1, 's': 2, 'e': 3, 'd': 4, 'f': 5, 't': 6, 'g': 7, 'y': 8,
         'h': 9, 'u': 10, 'j': 11, 'k': 12, 'o': 13, 'l': 14, 'p': 15, ';': 16}


# Persian keyboard layouts -> the QWERTY key at the same position, so shortcuts work in any layout
FA_KEYS = dict(zip(
    "ضصثقفغعهخحجچشسیبلاتنمکگظطزرذدپو؟۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يكئ،÷",
    "qwertyuiop[]asdfghjkl;'zxcvbnm,?01234567890123456789dkm,`"))


PENTA = [0, 3, 5, 7, 10]


PTN_NAMES = 'ABCD'


FX_NAMES = ['FILTER', 'CRUSH', 'STUTTER', 'TAPE', 'REVERB']


VIZ_NAMES = ['LED EQ', 'SCOPE', 'VECTOR', 'OUTRUN', 'VU METER', 'DITHER']


TAGLINES = ['Every Frequency Counts', 'Cathode Ray Signal', 'Vector Graphics Display', 'Drive Into The Sun',
            'Needles In The Red', 'Noise Becomes Form']


# label, engine attr, lo, hi, step
PARAMS = [
    ('CUT', 'cut', 0, 1, 0.03), ('RES', 'res', 0, 1, 0.04), ('ENV', 'env', 0, 1, 0.04),
    ('DRV', 'drv', 0, 1, 0.04), ('ATK', 'atk', 0, 1, 0.04), ('REL', 'rel', 0, 1, 0.04),
    ('DET', 'det', 0, 1, 0.04), ('SUB', 'sub', 0, 1, 0.04), ('DLY', 'dly', 0, 0.8, 0.04),
    ('VOL', 'vol', 0, 1, 0.04), ('SWG', 'swing', 0, 0.3, 0.015), ('WAV', 'wave', 0, 3, 1),
    ('BPM', 'bpm', 60, 200, 2), ('OCT', 'oct', 0, 7, 1), ('FXA', 'fxa', 0, 1, 0.05),
]


# 3x5 pixel font, row-major
FONT = {
    ' ': "000000000000000", 'A': "010101111101101", 'B': "110101110101110", 'C': "011100100100011",
    'D': "110101101101110", 'E': "111100110100111", 'F': "111100110100100", 'G': "011100101101011",
    'H': "101101111101101", 'I': "111010010010111", 'J': "001001001101010", 'K': "101101110101101",
    'L': "100100100100111", 'M': "101111111101101", 'N': "110101101101101", 'O': "010101101101010",
    'P': "111101111100100", 'Q': "010101101110011", 'R': "111101110101101", 'S': "011100010001110",
    'T': "111010010010010", 'U': "101101101101111", 'V': "101101101101010", 'W': "101101111111101",
    'X': "101101010101101", 'Y': "101101010010010", 'Z': "111001010100111",
    '0': "111101101101111", '1': "010110010010111", '2': "111001111100111", '3': "111001111001111",
    '4': "101101111001001", '5': "111100111001111", '6': "111100111101111", '7': "111001010010010",
    '8': "111101111101111", '9': "111101111001111", '-': "000000111000000", '.': "000000000000010",
    ':': "000010000010000", '/': "001001010100100", '#': "101111101111101", "'": "010010000000000",
    '!': "010010010000010", '?': "110001010000010", '+': "000010111010000", '&': "010101010101011",
}


DW = 100           # design width


PX, PW = 2, 96     # content x / width


THEME_ORDER = ['WHITE', 'GREEN', 'AMBER', 'RED', 'CYAN', 'VIOLET']


THEMES = {
    'GREEN':  dict(hi=157, txt=120, md=46,  lo=34,  dim=22,  acc=196, base=2),
    'AMBER':  dict(hi=230, txt=222, md=214, lo=172, dim=94,  acc=196, base=3),
    'RED':    dict(hi=231, txt=252, md=196, lo=124, dim=52,  acc=231, base=1),
    'CYAN':   dict(hi=195, txt=159, md=51,  lo=37,  dim=23,  acc=213, base=6),
    'VIOLET': dict(hi=225, txt=219, md=201, lo=133, dim=53,  acc=51,  base=5),
    'WHITE':  dict(hi=255, txt=250, md=255, lo=245, dim=238, acc=196, base=7),
}
