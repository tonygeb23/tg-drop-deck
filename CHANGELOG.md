# Changelog

## 2.0.0 — 26 August 2026

First release under the TG Drop Deck name. A rebuild of The Tony Gebhard Show
Soundboard 1.2, which had no surviving source — the keyboard map was recovered
from the shipped binary so that nothing about the way it plays had to change.

**The keyboard is identical to 1.2.** Same banks, same digits, same modifiers,
same two volume masters. If you used the old one, you already know this one.

### New

- **A real mixer.** sounddevice and soundfile instead of pygame, so playback is
  sample accurate, sample rates are converted properly, and MP3, FLAC, OGG,
  WAV and AIFF all play.
- **Output device picker** (`Ctrl+P`), including virtual cables — feed a stream
  or a recorder while you keep listening on your own speakers. Remembered by
  device name rather than by index, so unplugging something else does not move
  your audio somewhere unexpected.
- **Ducking.** Music beds drop about nine decibels while a sound effect or drop
  plays and slide back when it ends. `Ctrl+D` to turn off, `Ctrl+P` to set how
  far.
- **Fades.** Beds fade in and out instead of snapping, and `Escape` fades
  everything rather than cutting it.
- **Long files stream from disk.** Twenty music beds no longer mean a gigabyte
  of memory.
- **Missing files are handled.** A slot whose file has moved says "file
  missing" rather than failing silently, and **File → Relink missing sounds**
  repairs a whole board against a folder in one pass.
- **A demo pack**, forty pieces of audio, loaded automatically on a first run.
  Twenty sound effects and twenty looping music beds, all generated with
  ElevenLabs AI — nothing recorded, nothing sampled from a commercial library.
- **Per-slot level trim**, so one loud sound can be tamed without moving the
  master.
- **Ctrl+L** says what is playing.
- **Ctrl+N** starts an empty board; **File → Load the demo pack** brings the
  demo back.
- Boards can store paths relative to themselves, which is how the demo pack
  works wherever the app is installed.
- Saves are atomic — a crash mid-save cannot leave a half-written board where
  the real one was.

### Kept

- Four banks of twenty. Sound effects, dialog drops, music beds, miscellaneous.
- `1`–`0`, `Shift`, `Ctrl`, `Ctrl+Shift`, `Alt+Ctrl`, `Alt+Ctrl+Shift`.
- `F2`/`F3` for sounds, `F5`/`F6` for beds — two independent masters.
- `F4` rename, `Ctrl+E` search, `Escape` stop everything, `F1` help.
- Custom hotkeys on bank 4 via right-click.
- Sounds overlap and never cut each other off; beds toggle.
- Old `.json` banks load through **File → Import an old soundboard bank**.

### Tests

170 checks across four suites. The engine tests open no sound card — they
render the mixer by hand and measure the samples, including that ducking ducks
by the depth it claims and that every shipped bed loops without a click.
