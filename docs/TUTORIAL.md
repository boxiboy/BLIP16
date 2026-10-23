# BLIP-16 Tutorial

A guided tour, from your first sound to your own beat. Each part takes a few minutes.
Press `?` at any time for the key list, and `Q` to quit.

> Make the terminal at least **100×28** characters. BLIP-16 asks for a bigger window when it starts, but
> some terminals ignore that. In that case, maximise the window or make the font smaller.

---

## 1. Listen to the radio

Start the app:

```bash
blip16
```

You land on the **radio**, which is already playing. What you see:

- **Top left:** `RADIO`, `● ON AIR` and the song counter. `◆ OPEN` opens a music file (part 5).
- **Top middle:** **TEMPO** and **VOICE** controls. **Top right:** a clock.
- **The big area** is the visualizer.
- **Underneath:**
  - the song title in pixel letters
  - its style, key, BPM and seed
  - the **song map**: intro, verse, hook... The bright block is the bar that's playing
  - elapsed and total time, the current section, and the chord now → next
  - the **DJ** line: when the next mix happens, or the crossfader while mixing
  - focus **NOISE** on the right

Try these:

| Do this | What happens |
|---|---|
| `>` | the DJ mixes into a fresh song over 4 bars, on the beat |
| `SPACE` | pause / resume |
| `=` a few times | the tempo goes up; your speed-up carries over to later songs |
| `/` | random tempo; `\` puts it back |
| `'` | AUTO: every new song gets its own random speed |
| `Shift+D` | DJ off: songs then hard-cut instead of mixing |

Songs come in 7 styles: LOFI, HOUSE, SYNTH, CHIP, DEEP, DREAM and FRENCH. The DJ picks the next one to fit
the current tempo and key, and switches genre about half the time.

## 2. Make it sing

Press **`V`**. A robot voice starts singing over the song, about once every four bars.

- **`M`** cycles the voice modes:
  - **VOCODER**: speech carried by a synth, the classic robot-funk sound
  - **TALKBOX**: formants that open like a mouth, plus grit
  - **AUTOTUNE**: snaps hard to the song's key, with the stair-step warble
  - **SINGER**: the most natural one, with breath and vibrato
- **`[` `]`** choose what it sings. `~ RANDOM LINES ~` (the default) writes new lines from a word bank and
  brings back a hook for each song. The other entries are fixed phrases.
- **`Shift+V`**, or click **TYPE TEXT**: type your own lyrics (English letters) and press `Enter`.

The line being sung scrolls under **VOICE**.

## 3. Play with the visuals

- **`B` / `Shift+B`** cycle the visualizers:

  | Visual | What it looks like |
  |---|---|
  | **LED EQ** | hi-fi LED spectrum with peak hold |
  | **SCOPE** | CRT oscilloscope with a phosphor trail |
  | **VECTOR** | a rotating XY vector display |
  | **OUTRUN** | synthwave sun and a grid that moves with the tempo |
  | **VU METER** | twin analogue needles |
  | **DITHER** | Bayer-dithered clouds |

- **`` ` ``** changes the colour theme. **`I`** inverts the visual. **`0`** makes it fullscreen.
- **Click inside the visual** to play a note: left-right is pitch, up-down opens and closes the filter.
- **Scroll** over the visual to change how strongly it reacts.

## 4. Build a beat in the studio

Press **`R`** to switch to the **studio**. It already holds a starter beat.

1. Press **`SPACE`** to start the sequencer. A dotted bar sweeps across under the visual.
2. Move with the **arrow keys**. **`ENTER`** turns the step under the cursor on or off. `/` accents it.
3. On the **SYNTH** row, `ENTER` drops in the last note you played. **`,` `.`** move that note up or down a semitone.
4. Play the synth from the keyboard like a piano: `A S D F G H J K L ;` are the white keys and
   `W E T Y U O P` the black ones. `Z` `X` change the octave.
5. **Loop recording:** press **`V`** and play. Your notes snap onto the nearest step of the loop.
6. **Shape the sound:** use `[` `]` to pick a parameter (CUT, RES, ENV, DRV, ATK, REL, DET, SUB, DLY...), then
   `-` `=` to change it. Or click a bar, or scroll over it. `1`-`4` switch the waveform.
7. **Arrange:** `TAB` goes to the next pattern (A-D). `\` copies this pattern into the next slot so you can vary it.
8. **Mix:** `M` mutes the row, `N` solos it, `C` clears it, `Shift+R` randomises it.
9. **Effects:** `5` filter, `6` crush, `7` stutter, `8` tape, `9` reverb. `FXA` sets how strong they are.

## 5. Play your own music

Press **`Shift+O`**, or click **◆ OPEN**, then **drag an audio file from Finder into the terminal**. That types its
path. Press `Enter`.

- **`SPACE`** pauses. **`←` `→`** jump 10 seconds; you can also click anywhere on the progress bar.
- **`[` `]`** cycle the FX presets:

  | Preset | Sound |
  |---|---|
  | LOFI RADIO | default: tape, vinyl, a touch of crush and filter |
  | AM RADIO | telephone band and drive |
  | SPACE | big reverb |
  | UNDERWATER | heavy filter |
  | CRUSHED | heavy bit-crush |
  | CLEAN | no effects |

  `5`-`9` still toggle single effects, and focus noise still works.
- **`V`** cycles the vocals: **FULL MIX** → **NO VOCALS** (karaoke) → **VOCALS ONLY**.
  This works best on stereo songs with the singer in the centre.
- **`M`** (or **◆ REMIX IT**) analyses the song and **rebuilds** it with BLIP's instruments. The rebuild keeps
  the song's tempo, beat, chords, arrangement and melody. The radio then mixes into it, and the extracted beat
  also lands in studio pattern **D**.
- **`R`** goes back to the radio.

`mp3`, `m4a`, `flac` and other formats need [ffmpeg](https://ffmpeg.org) installed. `wav` always works.

## 6. Focus mode

For long work sessions:

1. Stay on the radio and turn the voice off (`V`).
2. Pick a calm visual such as **DITHER** or **SCOPE**, and go fullscreen with `0`.
3. Add **rain** or **brown noise** with `Shift+W`, and set its level with `{` `}`.
4. Turn on `'` (AUTO tempo) if you want each song to feel a little different.

Enjoy. 🎛
