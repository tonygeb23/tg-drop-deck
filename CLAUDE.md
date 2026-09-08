# TG Drop Deck, working notes

An accessible soundboard. wxPython, screen-reader first, free and MIT licensed,
released under the TG Studios name alongside [TG Model Master](../TG%20Model%20Master/CLAUDE.md)
and [TG Chord Caller](../TG%20Chord%20Caller/CLAUDE.md).

Rebuilt August 2026 from The Tony Gebhard Show Soundboard 1.2. That app had no
surviving source, only a frozen executable. The class layout, the bank
structure and the whole keyboard map were recovered out of the binary before a
line was written, which is why they match exactly.

## Standing rules

- **No em dashes or en dashes. Anywhere.** Tony's rule, 2 September 2026:
  code comments, docstrings, commit messages, the changelog, the website, the
  user guide, spoken strings, all of it. Use a full stop, a comma, a colon or
  brackets, and write "1 to 0" rather than a range with a dash. An em dash is
  one of the loudest tells that a machine wrote something, and a screen reader
  either skips it or says "em dash", neither of which is the sentence.
  `python tools/nodashes.py` reports them and `--fix` removes them, but **read
  the diff afterwards**: a dash swapped for a comma leaves comma splices, and
  the tool cannot tell a good comma from a bad one.

Inherited from the other TG Studios apps, and not negotiable here either:

- **wxPython only.** Never tkinter.
- **Every user-facing change gets tested with NVDA actually running.**
- Do not rewrite a control's accessible `Name` on **value** change. Rewriting
  it on an **edit** is required, see the two halves of `SoundButton.refresh`.
- Runs on the **global** Python 3.13.5, no venv, same as the other apps.

And specific to this one:

- **The bank NAMES are the user's; the bank BEHAVIOUR is not.**
  `board.bank_names` is a `{bank: name}` dict shared by reference with every
  `Slot`, which is why renaming a bank is one assignment and eighty labels
  follow. Renaming must stay purely cosmetic: bank 3 is the looping bank and
  bank 4 takes custom hotkeys because of `C.LOOPING_BANK` and `C.BANK_MISC`,
  never because of what the tab says. `_set_bank_name` says so out loud when
  you rename either of them, and `tests/test_feedback_2_4.py` asserts it.
  David Goldfield asked for this; do not let a later feature key off the name.
- **A slot may hold a folder instead of a file**, and then plays a random one
  of its sounds per press, Brian Hartgen's chart-countdown case. `is_folder`
  is `os.path.isdir(filepath)`, so there is no second kind of slot to keep in
  sync. Two rules: **the scan never happens on the trigger path** (the cache
  warmer and the assign dialog do it; a press uses the last scan), and
  **`pick_file` never returns the same file twice running** when there is
  anything else to pick, because that is the difference between random and
  broken.
- **The playlist runs on two decks and a cue point.** Every item says how
  long before its end the next one starts; that number is the crossfade, and
  a crossfade is the outgoing voice riding down while the incoming one comes
  up on the other deck. `PLAYLIST_DECK_A`/`_B` are slot indices above the
  eighty pads, so the mixer needs no special case for any of it. The cue
  arithmetic runs on the **ticked** items only - an unticked track keeps its
  place in the list and is stepped over.
- **A crossfade is measured from where the MUSIC stops, not where the file
  does.** `Track.playable_end` is the duration less `tail_silence`, measured
  once by `audiofile.tail_silence` on the background pass and saved with the
  board. This is the whole of Brian Hartgen's "the song is playing out in
  full and the second one is fading in": an MP3 carries a second or two of
  digital silence on the end, so cueing three seconds from the last sample
  put most of the crossfade inside that silence. Nothing on the cue path may
  go back to using `duration` directly.
- **The incoming track comes in AT LEVEL and the outgoing one rides down.**
  `C.SEGUE_FADE_IN` is thirty milliseconds and exists only so the first
  sample cannot click. Both tracks ramping is a DJ blend, not a radio segue,
  and it is what made a crossfade sound like a hole. And every handover gets
  at least `C.SEGUE_LEAD`, a fifth of a second, even with the crossfade at
  zero: waiting for a drop's last sample means waiting for a tick to notice
  and then for the next file to open, and you hear both.
- **The running order is a wx.ListCtrl with EnableCheckBoxes, and it has to
  stay one.** A wxCheckListBox on Windows is an owner drawn list box with a
  tick painted on it: MSAA never knows the tick is there, so a screen reader
  announced nothing when you arrowed and nothing when you pressed Space. That
  was the deal-breaker in Brian's report. A list view has real check boxes,
  real columns, and it receives Return, which a list box on a frame never
  does. Three consequences that are easy to undo by accident: **the title is
  column 0** because that is what first letter navigation searches, **no
  running order number goes in front of it** for the same reason, and
  **Space raises ITEM_ACTIVATED as well as toggling the tick**, which
  `_space_pressed` in `playlistview` is there to tell apart.
- **The frame's bare-key hotkeys stand down while a text box has focus.**
  An accelerator table on a frame is consulted BEFORE the control with
  focus, so every digit typed into the crossfade box fired a pad and the box
  could not be typed into at all. Vetoing it in `wxEVT_CHAR_HOOK` does not
  work: measured on wx 4.2.5, the hook runs first and the accelerator fires
  anyway. So the table itself is swapped, in `_apply_accelerators`. Two
  things it has to be driven by, not one: `EVT_CHILD_FOCUS` for speed, and
  `EVT_IDLE` because **focus moving into a wx.SpinCtrlDouble raises no child
  focus event at all** - it is a composite and the focus lands on the edit
  box inside it. Also measured. And `_focused_action` refuses while a text
  box has focus, because Delete and F2 come from the menu bar's own
  accelerators, which no swapping of this table can reach.
- **Playlist rows never say "playing", and pads never relabel under focus.**
  Same rule, two places. What is on air is *spoken* (`_playlist_moved`) and
  answered on demand by `Ctrl+L`. Rewriting the row a screen reader is
  standing on, at the moment a song changes, is the thing this app does not
  do.
- **The microphone ducks by being OPEN.** Not by level, not through a gate:
  `MicInput._publish` puts a flag on the shared `DuckBus` when it opens and
  takes it off when it closes, which is why it ducks a bed playing out of a
  different sound card. A gate that opens on your voice clips the first
  syllable of every sentence; one that hangs open ducks the bed when you
  cough. **Monitoring is added after the duck** in `Mixer.render`, or the
  voice would duck itself, and a monitor that starves or throws returns
  silence rather than stalling the output callback.
- **Nothing opens a microphone except a keypress.** Not startup, not loading
  a board. `mic_monitor`, the device and the gain are saved; whether it was
  ON is deliberately not, and there is a test that says so.
- **The digit map is frozen.** `1`-`0`, `Shift`, `Ctrl`, `Ctrl+Shift`,
  `Alt+Ctrl`, `Alt+Ctrl+Shift` across four banks of twenty. It is muscle
  memory built over years. A new feature gets a new key; it never takes one
  of these. Global hotkeys in 2.1.0 took `Ctrl+G` and nothing else.
- **The function key row moved once, in 2.2.0, and Tony signed it off.**
  `F2` renames, `F3`/`F4` are the sound volume, `F5`/`F6` are still the beds.
  It was `F2`/`F3` volume and `F4` rename, inherited from Soundboard 1.2,
  until David Goldfield pointed out that `F2` renames in every other Windows
  program. Do not "restore" it: `tests/test_feedback_2_2.py` asserts the new
  layout, and the digit map above was not touched.
- **`Ctrl+F` searches, and `Ctrl+E` still does too.** `Ctrl+E` was the search
  key for two releases. A key someone has already learned does not get taken
  away to tidy up; both are registered and both are documented.
- **A global hotkey always needs a modifier.** `globalhotkeys.parse` refuses a
  bare key and there is a test for it. RegisterHotKey on a bare key takes that
  key away from every other program on the machine, including whatever the user
  is typing into.
- **A pad's label is rewritten the instant the user edits the slot, and never
  while it is only the mixer talking.** `SoundButton.refresh` decides which it
  is by comparing `slot.button_label(False)`, the label with the "playing"
  word left out, against `_last_content`. An edit lands immediately, focus or
  no focus, because a screen reader has to answer "did that apply?" without
  the user tabbing away and back; that was Brian Hartgen's 2.3.0 report and it
  made every edit in the app look ignored. A sound starting is still deferred
  until focus leaves, because rewriting the Name under the user's fingers
  restarts the announcement mid sentence, on air. `set_slot` is the third
  case: a pad now pointing at a different slot is relabelled unconditionally.
  `tests/test_feedback_2_3.py` asserts all three.
- **The bed fades are settings, not constants.** `board.bed_fade_in` and
  `board.bed_fade_out`, pushed onto the mixer in `__init__`, `_adopt` and
  `_on_settings`, defaulting to `C.FADE_IN_BED` / `C.FADE_OUT_BED`. **Zero is
  a supported value and means the bed plays exactly as recorded**, a bed cued
  on its first beat cannot ease in. Nothing on the path may use `or` to
  default them; `Board._fade` clamps to `0`-`C.MAX_BED_FADE` and falls back
  only on something that is not a number. Sound effects never faded and this
  setting does not reach them.
- **No two commands may share an id, and a `_BASE` is a RANGE.**
  `ID_STATION_BASE` sat at `wx.ID_HIGHEST + 410` with twenty stations behind
  it, so it ran to 429 and swallowed `ID_SHOT` at 411 and `ID_STREAM_HELP` at
  412, both added later in the 400s by somebody reading the list as single
  numbers. Two handlers bound for one id on one window means **the last one
  bound wins**, `_on_pick_station` is bound after both and never calls
  `Skip`, so `Ctrl+Shift+F` reached the station picker and did nothing. It is
  at 700 now, above the slot block, and `tests/test_3_4_1.py` expands every
  `_BASE` by its span and asserts nothing overlaps.
  **Every test passed for the whole time it was broken**, because they all
  call the handler directly and the fault was in the binding. This is the
  same lesson as the crossfade box and Enter on a playlist row: a key is only
  really tested by pressing it. `tools/check_video_key.py` does that, and it
  runs a KNOWN GOOD key first as a control, so "the simulator could not
  deliver it" is never mistaken for "the app ignored it".
- **A STATE is a check box and an ACTION is a button.** Source control shipped
  in 3.4.0 with a mode: left and right cycled Mute, Solo, Rename, Remove and
  Space did whichever you had landed on. Tony asked for the mode on
  5 September and asked for it to go on the 8th, and he was right both times.
  A mode has to be remembered and announced, because nothing on screen says
  which of the four you are on. A check box says what it is the moment focus
  lands on it, and Space toggles it the way Space toggles every check box in
  Windows. **A wx.ListCtrl has one check box per ROW, not per column**, so
  mute and solo could never both be ticks in the list: they are two check
  boxes under it and the list keeps saying both as text columns.
  **`SetValue` raises `EVT_CHECKBOX`**, so syncing the boxes to the selected
  row must be guarded (`_syncing`) or arrowing down the list writes the
  displayed value back onto every source it passes, silently muting them.
  There is a check for exactly that.
- **Where Ctrl+B sends the show is a menu, not a checkbox.** `board.live_to`
  picks between the radio station and the video platform, and until 3.4.2 its
  only control was one box on the **Video** streaming page reading "Go live
  here when I press Ctrl+B". So the answer to "where does my show go" lived on
  the page for one of the two answers, and a board with both set up gave no
  sign a choice existed. It is **On air, Streaming location** now, one radio
  group, one dot. The checkbox stays and the two move together, because a
  control someone has already learned does not get taken away.
  **A separator starts a NEW radio group in wx**, so the saved setups cannot
  live in that menu after one: they kept a tick of their own and the menu
  showed two dots at once. They are a submenu, which is also honest, because
  loading a setup overwrites both Preferences pages rather than choosing
  between them.
  **And the menu says the station's NAME.** `server_label` returns "Icecast,
  or Liquidsoap harbor", which is right in the Preferences dropdown where
  somebody is working out which entry covers their server, and nine words to
  say "Blindside Radio" on the way to air. `preflight.where_it_goes` leads
  with the user's own name and falls back to the software only when there is
  none. Tony asked for this in those words.
- **Ctrl+B asks; a pad never does.** `board.ask_before_live` puts a summary
  in front of going live, and that is not a breach of the rule below it: a
  pad is muscle memory in the middle of a show and going live is a decision
  taken once, at the top of one. `GoLiveDialog` makes Go live the default
  button so `Ctrl+B` then Enter is still the whole gesture, and the checkbox
  inside it turns the question off for good. **The way back on is in
  Preferences**, on the Audio streaming page, because a "do not ask again"
  with no way back is a one way door.
- **The asking lives in `toggle_stream`, NOT in `start_stream`**, and that is
  load bearing. `start_stream` is called by anything that wants the show on
  the air; `toggle_stream` is called by a person pressing a key, and only a
  person can answer a question. Putting the dialog in `start_stream` hung
  every test in the repository that goes live, for ever, on a window nothing
  could click: `test_recording` stopped dead at "Recording and streaming at
  the same time" and `test_stream` printed nothing at all. It is the same
  trap as the `wx.MessageBox` one below, in a new place, and
  `tests/test_3_4_1.py` now asserts `start_stream` opens no window.
- **`preflight.py` imports no wx and touches no network**, which is what
  makes every warning testable one at a time rather than by going on the air.
  Anything it needs about the running app is passed in. A new warning goes
  there, not into `start_stream`, and it gets a check in
  `tests/test_3_4_1.py` next to the others.
- **A source that fills a canvas rather than failing cannot fall back**, and
  that is why the pre-flight exists at all. `ImageSource.frame` returns a
  background-filled rectangle for a file that has been moved, so
  `FallbackSource` never fires, `on_fallback` never fires, and the whole
  broadcast is a dark rectangle that looks deliberate. Warn before the air,
  because nothing downstream will.
- **The picture can be changed while live, and the reason it is safe is
  worth keeping.** Size, pixel format and frame rate go on the codec context
  once, inside `RtmpDestination.connect`, before the FLV header and the H.264
  sequence header go out. `_pump_video` asks every source for
  `frame(self.width, self.height)`, so a source is TOLD the size and never
  chooses it. Video PTS counts `_frames_sent` against the audio sample clock,
  so a swap cannot move the timeline: no keyframe is forced and no session is
  renegotiated. `Streamer.set_video_source` holds the new source as well as
  handing it on, because a reconnect rebuilds the destination from the
  settings snapshot and would otherwise put the picture back to whatever it
  was at `Ctrl+B`. **The new source goes on the air before the old one is
  closed**, or a camera's half second to first frame is half a second of card.
- **An `--exclude-module` beats a `--collect-all`, and the loser says
  nothing.** `PIL` had been excluded from the build since it was a tools-only
  dependency, so the first 3.5.0 build shipped every Pillow `.py` file and
  **not one of its native modules**. Nothing raised. Pillow imports fine
  without `_imaging`, the text renderer answers None, the card falls back to
  its blocky font and the overlay draws nothing, all silently, and the
  selftest passed. **The selftest now opens a font and draws a tile and
  checks the pixels**, which is the only check that would have caught it.
  The lesson generalises: for a bundled library, prove it WORKS in the
  frozen build, never that it imports. It also cost a wrong number in
  the changelog: the broken build was 3 MB smaller than the working
  one, so "the download barely grew" was measured against a build
  with the feature missing. **A size taken from a build you have not
  proved is a size for a different program.**
- **Named places, never a canvas.** `overlay.py` offers four fixed spots that
  cannot overlap, and there is no way to put something at an arbitrary
  position. That is not a shortcut, it is the feature: the research in
  `docs/VISUALS-PLAN.md` could not find one account, anywhere, of a blind
  person laying out a stream independently, because every tool offers a
  canvas and a canvas cannot be checked without looking. Four places can be,
  because "what is on screen" is four lines long and `Ctrl+Shift+V` reads it
  out. **`tests/test_visuals.py` asserts they do not overlap at four
  different frame sizes.** Adding a fifth place means proving the same.
- **Three measurements hold the overlay up, and each is one line from being
  undone.** Render a tile only when its text changes (about 2 ms, against
  redrawing 30 times a second for nothing); blend the tile's RECTANGLE, not
  the frame (about 2 ms against 30 ms, which is the whole budget); and use
  integer maths (float is 42 ms). All three have a check. The end to end
  proof is `tools/check_switching.py`, which now carries the overlay: 3 tiles
  drawn over 900 frames, and the overlay costs 0.2 ms on the streaming
  thread because it is cached.
- **A DESTINATIONS factory stand-in must take `**kw`.** `destination_for`
  gained `video_source` in 3.4.0 and an overlay and a health watcher in
  3.5.0, and each time a test double with a fixed signature failed to
  construct. The failure does not look like a signature error: the stream
  reports "failed" and the test looks like a broken feature. Two debugging
  sessions have gone on this. Take `**kw` from the start.
- **`Image.alpha_composite` holds the GIL and `Image.paste` does not.**
  Measured 8 September 2026 against a simulated 10 ms audio wake-up: with
  `alpha_composite` on a render thread the audio thread was late by up to
  **16.9 ms**, as bad as a pure Python busy loop, and it is 2.01x slower on
  two threads where `paste` is 1.00x. Nothing anywhere near the streaming
  thread may call it. This is not yet reachable code, Pillow is not bundled,
  but it is written here because the day it is bundled is the day somebody
  reaches for the obvious function. See docs/VISUALS-PLAN.md.
- **Screen capture is GDI through ctypes, and it must stay on its own
  thread.** Measured 8 September 2026: a desktop blit costs 16 to 33 ms and
  BLOCKS, because the Desktop Window Manager paces it to the display's
  refresh. The whole frame budget at 30 fps is 33.3 ms, and `_picture()` is
  called inline on the streaming thread, which is the thread carrying the
  audio. A capture on that thread would stall the sound, not just the
  picture. `ScreenSource` reads on `dropdeck-screen` and `frame()` hands back
  the last completed capture, exactly as `camera.py` does.
  `tools/check_switching.py` measures the feed time and would catch a
  regression; it was 15.9 ms against a 33.3 ms budget when this shipped.
  The cost is the same at any destination size, so `StretchBlt` scales on the
  GDI side and the frame arrives at the size the encoder wants.
- **The screen fills the frame and the camera goes in the corner. That was
  measured, not chosen.** A 1280 wide picture split in half leaves the screen
  640 across, and a 1920x1080 desktop at 640 across is not small text, it is
  no text: body copy is a grey smear and headings are shapes. At the full
  1280 the same screen reads perfectly. Side by side needs a 1920 wide
  stream, where each half is 960 and the text survives. Do not "improve" this
  into a 50/50 split at 720p.
- **Nothing goes between a keypress and a sound.** No confirmation, no
  animation, no lazy decode on the hot path. Short sounds are decoded into
  memory at assignment time precisely so the key is instant.
- **Sounds in banks 1, 2 and 4 overlap and never cut each other off.** Beds
  toggle. That is the whole interaction model.
- **A bank may be routed to its own sound card**, so `MixerGroup` can hold
  several `Mixer`s. Banks sharing a device share a mixer - the common case
  of one output is still one stream. Ducking is shared through a `DuckBus`
  precisely so routing the beds elsewhere does not silently disable it.
- **Three speech channels, and the user picks how many of them talk.**
  `board.speech_level` is `all`, `essential` or `none` - see
  `constants.SPEECH_LEVELS`.
  - `announce()` is what you cannot otherwise know: a missing file, a key
    Windows refused, a number you asked for. Silent only at `none`.
  - `announce_help()` is a confirmation of something you just did, or a hint
    you have read before. Silent below `all`.
  - `announce_playback()` is the name of a sound you can hear anyway.
  **All three write the status bar at every level**, so nothing this app has
  to say is ever only spoken. `none` is opt-in and is labelled as silencing
  everything; that is Brian Hartgen's request and it was deliberate.
- **The bank hint is spoken once per bank per session.** A screen reader
  already announces the tab, so speaking twenty words of help on top of that
  every time was two announcements for one keystroke. `_hinted_banks` on the
  frame is what makes it once.

## The Mac copy

`mac/` is the same product on macOS: native Swift and AppKit for VoiceOver,
reading and writing the same `board.json`, versioned in lockstep with this
one. Read [mac/CLAUDE.md](mac/CLAUDE.md) before touching it. Every porting
decision and its reason is there, including why the wxPython app could not
simply be run on a Mac and why one key on the frozen digit map had to move.
The Mac manual is a page of its own, tgstudios.app/drop-deck-guide-mac, kept
honest by `mac/check_guide.py` the way `tools/check_guide.py` keeps this one.
Releasing either copy is [../RELEASING.md](../RELEASING.md): the Windows
steps are the numbered sections and the Mac steps are the section near the
end, run by `tools/release_mac.py`. Both end with `release_mac.py feeds`,
which proves both platforms' update feeds the way the apps read them.

## Layout

```
dropdeck/
  constants.py   banks, hotkey labels, fades, help text, one source of truth
  audiofile.py   the two decoders behind one door, tags, and the run out
  slot.py        one button's state, how it describes itself, folder picking
  playlist.py    the running order, its cue points, and the two decks
  playlistview.py the list, its tick boxes and its row menu
  micinput.py    the microphone: capture, gain, monitoring, ducking
  plids.py       command ids the row menu and the frame both need
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
  preflight.py   what Ctrl+B is about to do, and what is wrong with it
  screen.py      the desktop as a picture source, and the camera in its corner
  overlay.py     four named places on top of the picture, and what is in them
  health.py      noticing the picture has gone black or frozen, and saying so
tools/
  audiopost.py       levels and seamless loops for generated audio
  make_demo_pack.py  the forty-piece demo pack, via ElevenLabs
  check_guide.py     fact-checks the published user guide against the app
  check_keyboard.py  real keystrokes into the real window. Run it by hand
  check_switching.py a real time broadcast that changes picture, then decodes
                     what arrived. The counterpart to check_stream_quality
  check_video_key.py real Alt+Shift+V into the real window, with a known good
                     key first as a control. Run it by hand
  shot_golive.py     pictures of the two 3.4.1 windows, and a layout audit
```

**Two decoders, one door.** `audiofile.py` tries libsndfile and falls back to
FFmpeg through PyAV, which is what makes `m4a`, `m4b`, `aac`, `wma` and `opus`
play at all. Three rules there: the extension list is what the decoders can
really decode, so nothing is offered that would then fail at the moment
somebody presses a key; PyAV is imported lazily, because it loads sixty
megabytes of FFmpeg and a board of WAVs must not pay for that at startup; and
tags are read with mutagen, which decodes nothing, so a file with broken tags
still plays. The build needs `--collect-all av`, or the whole family is
silently refused in the release and works fine from source.

`engine.py` and `mixer.py` know nothing about wx. That is deliberate, it is
why `tests/test_engine.py` can render the entire mixer and inspect the samples
with no sound card present.

## Where this is going

Tony's direction, 2 September 2026, deliberately **slow and steady**, none of
it is scheduled and none of it displaces a listener request:

**Drop Deck should eventually handle live streaming**, taking influence from
Station Playlist rather than copying it:

- an **encoder**, so the board can feed a live stream directly;
- a **microphone input**: an input device picker beside the existing output
  one, with gain, and the fade options the beds already have;
- which means the mixer grows a capture side. `MixerGroup` already holds
  several output `Mixer`s and a shared `DuckBus`; an input is a new kind of
  source into the same sum, and ducking a bed under a live mic is the same
  mechanism as ducking it under a drop.

**Done as of 2.5.0:** the input device, its gain, monitoring with an output
of its own, and ducking everything musical while the microphone is open.

**What is left is the encoder, and it has one architectural constraint that
must not be designed away.** Tony, 2 September 2026:

> everything will still go to the streaming, regardless of what output device
> it's sent to, the encoder picks up on all channels. however, if someone is
> streaming live to an encoder, but also doing a live show that includes
> output channels to go specific places, it will do that too.

So there are two quite different things and the encoder is not one of the
outputs:

- **Physical routing is per channel.** A bank can go to its own sound card,
  monitoring can go to the presenter's headphones, and those exist so a
  broadcaster can ride levels on a desk. `MixerGroup` already holds one
  `Mixer` per distinct device for exactly this.
- **The encoder takes the PROGRAM: the sum of everything, whatever it was
  routed to.** A drop sent to a separate card is still part of the show and
  still has to reach the stream. A `MixerGroup` today has no such sum - each
  `Mixer` renders only its own voices - so the encoder needs a program bus:
  every `Mixer.render` also adding its block into a shared program buffer
  that the encoder drains, in the same non-blocking "silence rather than a
  stall" way `MicInput.read` already works.

Monitoring is the one thing that must NOT be in the program sum. The
presenter hearing themselves in their headphones is not part of what the
audience hears, and putting it in the stream would send the voice twice.

The order to do the rest in is the order that keeps a working app at every
step: the program bus first, with a test that proves a bank on a second card
still reaches it, then the encoder on top. Nothing here justifies breaking the
frozen digit map or the "nothing between a keypress and a sound" rule, both of
which get harder, not easier, with a live stream attached.

## The user guide lives on the website

`Websites/tgstudios.app/content/pages/drop-deck-guide.md`, published at
tgstudios.app/drop-deck-guide, and opened from **Help, User guide** via
`C.USER_GUIDE_URL`. On the web rather than in the app so a confusing sentence
can be fixed the same day rather than at the next release.

**Run `python tools/check_guide.py` whenever a key changes.** Documentation
that lives in another repository is the kind that goes stale in silence, so it
is checked rather than remembered: it pulls every backticked keystroke out of
the guide, checks each against the accelerator table the app really builds, and
checks the numbers the guide quotes against `constants.py`. Keys handled
somewhere other than the table are listed in it **with the reason**, so an
unexplained miss is a real miss.

One trap, and it caught me: the guide is hard-wrapped markdown, so any quoted
phrase longer than a few words straddles a newline. The checker normalises
whitespace before matching. Without that it reports the guide as wrong for
being wrapped - which is the checker being wrong, and the sort of "fix" that
would have had me editing correct prose.

## Things that will bite

- **A timer swallows whatever its callback raises.** `_announce_startup` runs
  inside a `wx.CallLater` and asked a `MixerGroup` for a `stream` attribute it
  has never had. From 2.1.2 to 2.3.0 that raised on every single launch, so the
  app said nothing at startup at all, including "3 files missing" and "audio
  could not start", and nothing anywhere reported it. It is `is_running` now,
  answered by both `Mixer` and `MixerGroup`, and `_announce_startup` wraps
  `_startup_line` so a future failure lands in the status bar instead of
  vanishing. **Anything you put in a timer callback needs the same treatment.**
- **A wx.CallAfter with no wx.App raises**, and inside the hotkey listener
  thread that killed the thread *before it reached the message loop*, leaving
  every combination registered with Windows, firing nothing, and unavailable to
  every other program until the process died. Unregistering now happens in a
  `finally`, and the hop to the UI thread is guarded. A test asserts the thread
  is still alive after registering.
- **A text tool that rewrites code it was not asked to rewrite is worse than
  no tool.** The first `nodashes.py` ran tidy-up regexes over whole files to
  clean up after its own replacements. One of them, `,\s*\)` to `)`, turned
  `("",) * SLOTS_PER_BANK` into `("") * SLOTS_PER_BANK`: bank four's hotkey
  labels became an empty string rather than a tuple of twenty, and the app
  would have raised the moment anybody opened bank four. It was caught by
  reading the diff, which is the only reason it is not in a release. The tool
  now edits nothing but the dash character on lines that contain one.
- **Do not point PyInstaller's `--distpath` inside Dropbox.** `--clean` dies on
  "cannot access the file because it is being used by another process" every
  time. The whole build goes to `%LOCALAPPDATA%\TG Studios Build\drop-deck`
  and only the zip and the installer are copied back.
- **Some things can only be tested with a real keystroke.** Two of the eight
  faults in Brian Hartgen's September 2026 report were invisible to every
  test in `tests/`, because both were about what Windows does with a key
  BEFORE any of this app's code sees it: Enter never reaching a list box on a
  frame, and the accelerator table eating a digit before the crossfade box
  got it. Calling the handler by hand proved nothing in either case.
  `tools/check_keyboard.py` drives the real window with `wx.UIActionSimulator`
  and it is in tools rather than tests on purpose: it needs the foreground,
  and on a desktop somebody is using it does not always get it. It says
  "skipped" rather than reporting a failure it cannot stand behind. It must
  run inside `MainLoop`; keystrokes dispatched outside an event loop get no
  accelerator translation at all, which is the very thing being tested.
- **A modal message box in a test hangs it for ever.** `wx.MessageBox` waits
  for a click that a test cannot give, and `test_feedback_2_4` drives a path
  that raises one on purpose: assigning an empty folder is refused with a
  message box. It hung about one run in three, always after every check had
  passed, so it showed only as an exit code. That file stands `wx.MessageBox`
  in now, which also lets it assert that the user was told rather than only
  that the folder was refused. **Any test that reaches a modal path needs the
  same stub.**
- **There is still an intermittent hang at frame teardown, roughly one run in
  many.** Seen twice, in different suites, always with every check already
  passed. `test_playlist` runs in 3 seconds normally and then occasionally
  does not finish at all. Every background thread the frame starts is
  `daemon=True`, so none of them holds the interpreter, and the modal box
  above was a different cause with the same symptom. Not yet found. If you
  are chasing it, `faulthandler.dump_traceback_later(45, exit=True)` around
  `runpy.run_path` is what located the modal one.
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
  than a few seconds. No exception, no traceback, the interpreter just exits.
  Write OGG in blocks through `sf.SoundFile`, which `audiopost._write_chunked`
  does. This cost an afternoon; do not "simplify" it back to `sf.write`.
- **Dropbox holds a newly created file open** long enough to break
  `os.replace`. Every atomic write here retries.
- **The ElevenLabs music endpoint ignores `output_format`** and returns MP3 at
  48 kHz whatever you ask for. It also returns slightly more audio than you
  asked for, MP3 encoder padding, so beds are requested two seconds long and
  trimmed to an exact loop.
- **A test renders far faster than real time**, so a streaming voice starves
  purely because its reader thread never gets a turn. `test_engine` waits on
  `Voice.buffered_frames`; the sound card does that pacing in the real app.
- Duck depth, the fade defaults and the preload threshold all live in
  `constants.py`. The tests assert against those constants, so changing one
  does not silently invalidate a test. The bed fades are only *defaults*
  there now, the live values are on the board.

## The demo pack

Forty files in `demo/`, about 8 MB, generated by `tools/make_demo_pack.py`.

**Always run `--check` first and tell Tony the credit cost before generating.**
The tool skips anything already on disk, so it is safe to re-run after a
failure. Effects are peak-normalised to −1 dBFS; beds are loudness-matched to
−20 dBFS RMS with a limiter rather than by turning the whole track down, then
crossfaded into an exact thirty-second loop.

Two beds sit a couple of decibels under the rest on purpose, `dark_tension`
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

A board may store paths relative to itself, that is how the shipped demo
resolves wherever the app lands. Absolute paths are used for everything the
user assigns. `Board.load` resolves relative paths against the board's own
folder, so both work without a flag.

Tony's old bank from the 1.2 app is parked in `boards/TG Show bank.json`. Many
of its files no longer exist, the E: drive is gone and a Dropbox folder was
renamed, which is what **File → Relink missing sounds** is for.
