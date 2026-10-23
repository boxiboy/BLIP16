# How BLIP-16 works

BLIP-16 is plain Python with **numpy** for DSP, **sounddevice** (PortAudio) for audio output and **curses** for
the interface. There are no samples, no ML models and no pre-made songs: every sound is computed.

## Audio engine (`engine.py`)

- One audio callback at **44.1 kHz** with 512-sample blocks (about 11.6 ms).
- The **sequencer clock** runs inside the callback with sample accuracy. Each block is split at step boundaries,
  so a note starts on the exact sample its step begins. Swing lengthens even steps and shortens odd ones.
- **Buses:** lead synth, chords, bass, drums, voice. The lead goes through a resonant **state-variable filter**
  (Chamberlin topology) with an envelope, then drive, then a tempo-synced dotted-eighth **delay**.
  Chords have their own filter. Chords and bass are **sidechain-ducked** by the kick.
- **Master FX chain:** beat-repeat stutter (captures 1-1/8 of a step), tape wobble (a fractional delay line
  modulated at 0.7 Hz and 6 Hz), bit-crusher (sample-and-hold plus quantisation), DJ low-pass, and a 4-comb reverb.
  A `tanh` soft limiter sits at the end.
- **Drums** are synthesised once at start-up: a pitch-swept sine kick, a noise-plus-tone snare,
  a three-burst clap and high-passed noise hats.
- Heavy jobs run in **separate processes**, so they can never hold Python's GIL while the audio thread needs it.
  Those jobs are voice rendering, file decoding plus separation, and remix analysis.

## Generated songs (`styles.py`, `song.py`)

A `Song` is fully defined by a **seed** and a **style**. The style supplies:

- tempo and swing ranges, modes (major / dorian / aeolian) and a list of chord progressions (as scale degrees)
- drum templates. `x` is a hit, `X` an accent and a digit a probability, so every bar comes out a little different
- instrument presets for chords and bass, lead synth settings and FX
- an **arrangement**: sections such as `INTRO 8 bars, layers CH, filter 0.55 → 0.15`

Songs are written **one bar ahead**:

- **Chords:** diatonic sevenths, with a ninth on some degrees. They are voiced in a single octave so voice
  leading stays smooth. Each style comps them differently: lo-fi keys strum, house stabs, synth pads hold.
- **Bass:** follows the root with a pattern per style: lo-fi root and approach note, house off-beats, or synth octaves.
- **Melody:** a 2-bar **motif** on the pentatonic scale, varied every 4 bars. Notes on strong beats snap to chord tones.
- **Fills** on the last bar of each section: snare rolls, kick drops, open hats. In house, a stutter build lands before the drop.

## Radio and DJ (`radio.py`)

Two decks. Near the end of a song, the DJ generates candidate songs (10 of a new genre about half the time,
otherwise 24 of any genre). It scores them on tempo distance, key distance (circle of fifths) and recent genres,
and picks the best. During the 8- or 16-bar mix:

- both songs run on the **same clock**, so they are beat-matched by construction
- the **tempo glides** from song A to song B along a smoothstep curve
- the **crossfade** is equal-power, using cos/sin gains
- at the midpoint, **kick and bass swap** to the incoming song and its sound settings load

Your tempo control is stored as a ratio, so it carries over through mixes. AUTO mode gives each new song
a random ratio between 0.8 and 1.3.

## Voice (`voice.py`)

1. **Text → syllables.** Graphemes, with vowel and consonant digraphs, become syllables that each have an onset,
   a vowel and a coda. Function words are unstressed. A silent final *e* is dropped.
2. **Lyrics.** In random mode, lines come from templates and an original word bank. Each song keeps a hook line,
   and sometimes a word is chopped and repeated.
3. **Flow.** Stressed syllables go on beats, sometimes pushed a 16th early for syncopation. Unstressed syllables
   fill the 8ths and 16ths in between. The line's last note is held.
4. **Melody.** A contour (arch, fall, rise or chant) over the song's pentatonic scale. Stressed notes snap to the chord of their bar.
5. **Synthesis** (cascade formant synthesiser):
   - The voiced source is a harmonic series rolling off at -6 dB/octave. It passes through three resonances,
     *F1–F3*, whose frequencies move over time: they glide in from the previous vowel or from the consonant.
   - Formant-shaped **breath noise** is added.
   - **Consonants:** spectrally shaped noise for *s* / *sh* / *f* / *h*; a burst plus aspiration for *p t k*;
     a soft burst for *b d g*; formant glides for *m n l r w y*.
6. **Modes:**
   - *VOCODER*: a 16-band channel vocoder. Envelope followers on the speech drive the same bands of a detuned saw
     carrier, and a sibilance bypass keeps consonants clear.
   - *TALKBOX*: narrow formants opening from a closed shape, plus drive.
   - *AUTOTUNE*: a human-like pitch curve (scoop, vibrato, drift) is snapped to the song's scale with about
     6 ms of retune, which gives the stair-step warble.
   - *SINGER*: the natural curve with jitter and delayed vibrato.
7. **Vowel on the beat.** Each syllable reports where its vowel starts. Playback begins one step early and is
   delayed so the vowel lands exactly on the step.

## Visualizers (`ui.py`)

Each visual is drawn into a float canvas at **braille-dot resolution**, 2×4 dots per character. It is then
thresholded with an **8×8 Bayer matrix** (ordered dithering) and packed into braille characters.

- **SCOPE** and **VECTOR** keep a decaying *persistence* buffer, like a CRT phosphor. SCOPE triggers on rising zero crossings.
- **LED EQ** draws segmented bars with dim "unlit" segments and falling peak dots.
- **OUTRUN** is a striped sun over a perspective grid that scrolls at the song's tempo.
- **VU METER** has ballistic needles on arcs.
- **DITHER** thresholds a tileable 1/f noise texture (made with an FFT) by loudness.

The spectrum comes from a 4096-point FFT of the output, in 28 log-spaced bands, with a slight tilt to make it look even.

## File player (`player.py`)

- A worker process streams the file through **ffmpeg** (or Python's `wave` module) as stereo float32.
  It optionally separates the vocals and sends mono blocks back through a pipe.
  The app buffers up to 8 seconds and feeds the master FX chain.
- **Vocal separation** is a streaming STFT: 4096-point frames, 1024 hop, sqrt-Hann windows with perfect
  reconstruction. A bin counts as *voice* when it is all of these:
  centre-panned (`|L| ≈ |R|`), phase-coherent between left and right, steady compared with the median of the
  last 9 frames (drum hits are not), and inside the 120 Hz - 8 kHz band.
  - *NO VOCALS* = mid × (1 − mask) + side
  - *VOCALS ONLY* = mid × mask

## Remix analysis (`analysis.py`)

| Step | Method |
|---|---|
| Onsets | log-spectral flux over STFT frames at 22.05 kHz |
| Tempo | autocorrelation picks the ballpark, then a beat-comb search over ±3 % refines tempo and phase. The result is folded into 70-160 BPM |
| Downbeat | the beat offset where the harmony changes most, falling back to where the kick is strongest |
| Drums | onset strength in the kick (35-130 Hz), snare (1.8-5 kHz) and hat (7-11 kHz) bands, sampled at every 16th of every loud bar and averaged into a pattern |
| Pitch content | harmonic-only spectrum (median over time), with the noise floor removed. Harmonic summation turns it into pitch salience, which is folded into chroma |
| Key and chords | for each of 24 keys, fit every bar with that key's diatonic seventh chords and keep the key that explains the song best (a Krumhansl profile breaks ties). The most common 4-bar loops become the progressions |
| Arrangement | 8-bar blocks are labelled by loudness and kick presence: intro, groove, hook, break, outro |
| Melody | pitch salience on a 4096-point spectrum. Each harmonic counts only up to the fundamental's energy, which prevents octave-down errors. Sustained pads are subtracted, the upper line is favoured, and a Viterbi path is found. Octaves are cleaned up, then notes are quantised to the 16th grid with their lengths |
