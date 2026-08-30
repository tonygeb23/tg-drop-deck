# TG Drop Deck — working notes

An accessible soundboard. wxPython, screen-reader first, free and MIT licensed,
released under the TG Studios name alongside [TG Model Master](../TG%20Model%20Master/CLAUDE.md)
and [TG Chord Caller](../TG%20Chord%20Caller/CLAUDE.md).

Rebuilt August 2026 from The Tony Gebhard Show Soundboard 1.2. That app had no
surviving source — only a frozen executable. The class layout, the bank
structure and the whole keyboard map were recovered out of the binary before a
line was written, which is why they match exactly.

## Standing rules

Inherited from the other TG Studios apps, and not negotiable here either:

- **wxPython only.** Never tkinter.
- **Every user-facing change gets tested with NVDA actually running.**
- Do not rewrite a control's accessible `Name` on value change.
- Runs on the **global** Python 3.13.5, no venv — same as the other apps.

And specific to this one:

- **The keyboard map is frozen.** `1`–`0`, `Shift`, `Ctrl`, `Ctrl+Shift`,
  `Alt+Ctrl`, `Alt+Ctrl+Shift` across four banks of twenty; `F2`/`F3` for
  sounds and `F5`/`F6` for beds. It is muscle memory built over years. A new
  feature gets a new key; it never takes one of these. Global hotkeys in 2.1.0
  took `Ctrl+G` and nothing else.
- **A global hotkey always needs a modifier.** `globalhotkeys.parse` refuses a
  bare key and there is a test for it. RegisterHotKey on a bare key takes that
  key away from every other program on the machine, including whatever the user
  is typing into.
- **Nothing goes between a keypress and a sound.** No confirmation, no
  animation, no lazy decode on the hot path. Short sounds are decoded into
  memory at assignment time precisely so the key is instant.
- **Sounds in banks 1, 2 and 4 overlap and never cut each other off.** Beds
  toggle. That is the whole interaction model.
- **A bank may be routed to its own sound card**, so `MixerGroup` can hold
  several `Mixer`s. Banks sharing a device share a mixer - the common case
  of one output is still one stream. Ducking is shared through a `DuckBus`
  precisely so routing the beds elsewhere does not silently disable it.
- **Speech about playback is optional; speech about failure is not.**
  `announce_playback()` is gated by a setting and always writes the status
  bar; `announce()` always speaks. A missing file must never be silent.

## Layout

```
dropdeck/
  constants.py   banks, hotkey labels, fades, help text — one source of truth
  slot.py        one button's state, and how it describes itself out loud
  engine.py      voices: memory playback, disk streaming, gain envelopes
  mixer.py       output streams, per-bank routing, ducking, the two masters
  board.py       eighty slots on disk, legacy import, relinking
  speech.py      accessible_output2, with a fallback to doing nothing
  dialogs.py     hotkey capture, search, level, audio settings
  ui.py          the frame, the four tabs, the accelerator table
  globalhotkeys.py  Windows RegisterHotKey, on its own listener thread
  singleinstance.py one copy at a time; identical to the Prompt Vault's copy
  appupdate.py   signed update manifest; identical in shape to the Prompt Vault
  appicon.py     the drawn mark, and the .ico the build stamps in
tools/
  audiopost.py       levels and seamless loops for generated audio
  make_demo_pack.py  the forty-piece demo pack, via ElevenLabs
```

`engine.py` and `mixer.py` know nothing about wx. That is deliberate — it is
why `tests/test_engine.py` can render the entire mixer and inspect the samples
with no sound card present.

## Things that will bite

- **A wx.CallAfter with no wx.App raises**, and inside the hotkey listener
  thread that killed the thread *before it reached the message loop* — leaving
  every combination registered with Windows, firing nothing, and unavailable to
  every other program until the process died. Unregistering now happens in a
  `finally`, and the hop to the UI thread is guarded. A test asserts the thread
  is still alive after registering.
- **Do not point PyInstaller's `--distpath` inside Dropbox.** `--clean` dies on
  "cannot access the file because it is being used by another process" every
  time. The whole build goes to `%LOCALAPPDATA%\TG Studios Build\drop-deck`
  and only the zip and the installer are copied back.
- **A daemon thread inside libsndfile at interpreter shutdown segfaults.** The
  cache warmer decodes on a background thread, and tearing the process down
  under it crashed on exit about one run in three - after every check had
  passed, so it only showed as an exit code. `stop_background_work()` is called
  from **both** `_on_close` and `Destroy`, because **Destroy does not raise
  EVT_CLOSE** and the tests tear frames down that way.
- **The selftest must close the mixer.** An open audio stream keeps the process
  alive after the report is printed, so a selftest that forgets looks exactly
  like one that hung.

- **libsndfile's Vorbis encoder kills the process** on a one-shot write of more
  than a few seconds. No exception, no traceback — the interpreter just exits.
  Write OGG in blocks through `sf.SoundFile`, which `audiopost._write_chunked`
  does. This cost an afternoon; do not "simplify" it back to `sf.write`.
- **Dropbox holds a newly created file open** long enough to break
  `os.replace`. Every atomic write here retries.
- **The ElevenLabs music endpoint ignores `output_format`** and returns MP3 at
  48 kHz whatever you ask for. It also returns slightly more audio than you
  asked for — MP3 encoder padding — so beds are requested two seconds long and
  trimmed to an exact loop.
- **A test renders far faster than real time**, so a streaming voice starves
  purely because its reader thread never gets a turn. `test_engine` waits on
  `Voice.buffered_frames`; the sound card does that pacing in the real app.
- Duck depth, fades and the preload threshold all live in `constants.py`. The
  tests assert against those constants, so changing one does not silently
  invalidate a test.

## The demo pack

Forty files in `demo/`, about 8 MB, generated by `tools/make_demo_pack.py`.

**Always run `--check` first and tell Tony the credit cost before generating.**
The tool skips anything already on disk, so it is safe to re-run after a
failure. Effects are peak-normalised to −1 dBFS; beds are loudness-matched to
−20 dBFS RMS with a limiter rather than by turning the whole track down, then
crossfaded into an exact thirty-second loop.

Two beds sit a couple of decibels under the rest on purpose — `dark_tension`
and `suspense_pulse` are sparse and high-crest, and flattening them to match
would ruin what they are for.

**The demo pack is disclosed as AI generated** in the README, the About box and
the board file itself. That disclosure is the licensing position: nothing in it
is recorded or sampled from a commercial library, which is what makes it safe
to bundle with a free app. Do not add any sound to the pack that did not come
out of the generator.

## Boards

`%APPDATA%\TG Studios\TG Drop Deck\board.json`. Saved on change (two second
debounce) and on exit, atomically.

A board may store paths relative to itself — that is how the shipped demo
resolves wherever the app lands. Absolute paths are used for everything the
user assigns. `Board.load` resolves relative paths against the board's own
folder, so both work without a flag.

Tony's old bank from the 1.2 app is parked in `boards/TG Show bank.json`. Many
of its files no longer exist — the E: drive is gone and a Dropbox folder was
renamed — which is what **File → Relink missing sounds** is for.
