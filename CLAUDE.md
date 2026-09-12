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

- **Mac work does not touch Windows files, and Windows work does not touch
  Mac files.** Tony's rule, 8 September 2026: "if we're on mac, you do not
  modify a single windows code. you can look at it for an analysis, but, no
  modifications." The two apps mirror one another in FEATURES. They are
  separate code, separate operating systems and **separate version numbers**.
  Read across the line freely, write across it never.

  This was not a tidiness rule when he made it. `tools/release_mac.py` read
  its version out of `dropdeck/constants.py`, so eight Mac releases bumped
  the WINDOWS app's version from 3.5.2 to 3.5.28 while the newest Windows
  installer in existence was 3.5.2. A Windows build claiming a version above
  anything the feed can serve answers "you have the newest one" for ever, so
  no Windows fix could ever have reached him again. One line, no Windows code
  changed at all, and the update channel was off the air.
  `tests/test_version_separation.py` asserts each build cuts its own version.

Inherited from the other TG Studios apps, and not negotiable here either:

- **wxPython only.** Never tkinter.
- **Every user-facing change gets tested with NVDA actually running.**
- Do not rewrite a control's accessible `Name` on **value** change. Rewriting
  it on an **edit** is required, see the two halves of `SoundButton.refresh`.
- Runs on the **global** Python 3.13.5, no venv, same as the other apps.

And specific to this one:

- **An output stream asks the sound card for NOTHING, and that is load
  bearing.** `C.OUTPUT_BLOCKSIZE` is zero, which means PortAudio calls back
  with however many frames the card is ready for. Every output shipped with a
  fixed 512 until 3.6.0 and on a virtual audio cable that quietly destroyed
  the sound.

  Measured 9 September 2026, Drop Deck's own mixer playing a 1 kHz tone into
  VB-CABLE with the far end of the cable recorded and analysed, ten runs at
  each size, counting how much of the tone never arrived:

  | Output buffer | Runs that lost audio | Median lost | Worst |
  |---|---|---|---|
  | 512 | 7 of 10 | 2.67 per cent | 7.39 per cent |
  | 1024 | 6 of 10 | 0.06 per cent | 0.74 per cent |
  | 2048 | 0 of 10 | none | none |
  | 0 | 0 of 10 | none | none |

  **Zero is not a trade of latency for reliability**, which is the reason it
  is zero rather than 2048: PortAudio reported the same 22 ms with zero as
  with 512, and 85 ms with 2048. A soundboard cannot spend 85 ms on the way
  to a pad.

  What it sounded like: about six gaps a second, four milliseconds each, so a
  1 kHz tone read 974 Hz on a cycle count. Tony, 9 September 2026: "a change
  in pitch, a little choppiness" going into TeamTalk.

  **PortAudio reported no underrun at all throughout**, which is why nothing
  ever said so, and why `Mixer._callback` now times itself against
  `C.LATE_BLOCK_FACTOR` rather than taking the driver's word for it. Do not
  put a number back here without repeating that measurement.
  `C.BLOCKSIZE` is a different thing and is still 512: it is the microphone's
  input stream and the size every test renders by hand.

  **Zero is not worse anywhere**, which was checked and not assumed.
  PortAudio's reported output latency: the system default output 209 ms at
  512 and 180 ms at zero, the same speakers under WASAPI 23 ms and 22 ms,
  the cable 22 ms either way.

  **And that measurement found a separate thing worth knowing: the Windows
  system default output goes through MME, and MME is about two hundred
  milliseconds however it is asked.** The same sound card chosen explicitly
  under WASAPI is twenty two. On a soundboard, whose whole promise is that
  nothing goes between a keypress and a sound, that is a ninefold difference
  sitting behind the word "default". `output_devices()` already lists WASAPI
  first. Whether the app should stop resolving "system default" through
  PortAudio's default host API is an open question and Tony's to answer.

- **A source is read ONCE per callback, so mix minus is a SUBTRACTION.**
  `SourceGroup.read_air_minus` returns the air sum and the same sum less one
  member, off the single read everything else already does. Reading a source
  takes the audio away from it, so summing twice would give each sum half a
  voice, and that is not an optimisation to undo: it is the only way both
  sums can be right. Everything upstream of `_soft_clip` is a plain addition,
  which is what makes the subtraction exact, so **the two sums must both be
  finished before either is soft clipped** and a shared array must never be
  clipped twice.

- **The confidence feed cannot loop, and the reason is one method.**
  `send.Confidence.read_air` returns zeros. `SourceGroup` sums `read` into
  what the presenter hears and `read_air` into what goes out, so a member
  that answers nothing to the second one is heard and never sent. That is why
  it is an `extras` member of the group rather than anything cleverer, and it
  is why hearing the send cannot put the send inside itself.

- **A mix minus that is not happening must never look like one that is.**
  `board.send_minus` names a source, by NAME, because a list gets reordered
  and an index would silently start excluding somebody else. A name matching
  nothing means everything goes out, and `DropDeckFrame.send_report` says so
  in as many words. Without that sentence, a source renamed on a Tuesday is a
  call full of echo on a Wednesday with nothing anywhere to explain it.

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
- **A colour is chosen by NAME and judged by NUMBER, never by a swatch.**
  `colours.py` offers a short list of named colours and scores every pair
  with the WCAG contrast ratio, and the picker says the score as you arrow:
  "gold, easy to read, 8.6 to 1". A colour wheel is not an answer for
  somebody who cannot see it, it is the question restated.
  **The number happens to be the right one for video too, and that was
  measured rather than assumed.** 4:2:0 stores colour at half the resolution
  of brightness, so a pair whose contrast is carried by HUE has nothing left
  after encoding: measured 8 September 2026 through the real encoder, the
  pure primaries red and blue have a greyscale edge of 0.0 before encoding,
  and the palette's own red on blue has one twentieth of a good pair's and
  comes back as chroma bleed. WCAG contrast is a brightness ratio, so it
  condemns exactly those pairs without knowing anything about video.
  `tests/test_colours.py` runs the real encoder to prove it, and asserts
  every shipped preset clears the target. **A preset that ships unreadable
  is worse than no presets**, because somebody who cannot check it has no
  reason to doubt it.
- **The picture goes out as BT.709, limited range, and SAYS SO.** Both
  halves were wrong until 8 September 2026 and neither raised anything.
  Measured: `frame.reformat(format="yuv420p")` converts with the **BT.601**
  matrix, so pure red left this app as Y=81 and pure blue as Y=41, where
  BT.709 wants 63 and 32. Every player assumes BT.709 for anything 720p or
  larger, so the app was sending standard definition colour weights on a
  high definition picture. And nothing was tagged, which is the failure that
  actually reaches a viewer: a player that has to guess the range guesses
  wrong, and that is what "washed out" and "crushed" look like.
  `dst_colorspace=C.RTMP_COLOURSPACE` fixes the conversion and `_tag_colour`
  plus the x264 parameters fix the label. **The x264 parameters are not belt
  and braces: an FLV carries no colour metadata of its own, so for an RTMP
  stream the H.264 sequence header is the only place a tag can travel.**
  `tests/test_colours.py` encodes a real FLV, reads the tags back and checks
  white, red and blue land on 235, 63 and 32.
- **Contrast and fraying are two questions, and one number answers one of
  them.** The first version of this said the WCAG ratio caught "both the
  unreadable and the unencodable", and that was too strong. Contrast is a
  brightness ratio and brightness is the half of the picture 4:2:0 keeps
  intact, so it does predict what a viewer can READ. It is blind to the
  edges: a strongly coloured letter keeps its shape and frays at its border
  however good its ratio, and measured at 1 Mbps and 6 Mbps the error on a
  red letter was **the same**, because subsampling and not bitrate is what
  does it. So `fringing()` is a second score with a different repair. Gold on
  navy is the case that proves they are separate: 8.6 to 1, easy to read,
  and 83 per cent saturated. The picker shows them in two columns for that
  reason, and **no shipped preset uses a fraying colour for the WORDS**,
  which is asserted rather than intended.
- **A coloured rule is an even number of pixels high.** Colour is stored one
  sample per two by two block, so an odd-height coloured line straddles two
  of them and shares each with whatever is beside it. Measured: a one pixel
  red rule lost 57 levels of colour, two pixels lost 12, and **three pixels
  lost 17, worse than two**. `height // 240` is 3 at 720p, so the app was
  drawing the worst case at the commonest size. `colours.even()` now rounds
  it, and never below 2.
- **The shot check ASKS; everything else here MEASURES. It is a second
  opinion and it is never load bearing.** `vision.py` sends one still of the
  picture going out to Claude, ChatGPT or Gemini on the user's own key and
  reads the answer back. Three rules, and all three are checks in
  `tests/test_shotcheck.py`. **It is never on the path to air**: it has its
  own key, its own thread, and `toggle_stream` and `start_stream` do not
  mention it, which is asserted by reading their source. **It never raises**,
  because somebody who cannot see the screen cannot debug a traceback in a
  status bar, so every failure is a sentence naming the thing to go and
  change and an HTTP code is never shown. **And a screen is never sent
  without asking, EVERY time.** Not once, not remembered: a yes given about
  one screen is not a yes about the next one, and the person answering
  cannot look at the frame to see what is in it. That asymmetry, that the
  reason the feature exists is the reason its user cannot vet what it
  uploads, is the whole argument for the repeated prompt. Tony chose it on
  8 September 2026 when it was put to him.
  **The key goes in Credential Manager under its own prefix**, never in
  `board.json`: a vision key is billable, so a board sent to somebody else
  would hand them a bill. **The picture described is the one GOING OUT**,
  overlay and all, rather than the camera queried separately, which is
  simpler and more honest: it catches the card still being on air when you
  thought the camera was.
  **Speed is part of the model choice and was measured**, not assumed. Same
  picture, same prompt: `gemini-flash-latest` 66.8 seconds,
  `gemini-3.6-flash` 3.2, `gemini-flash-lite-latest` 1.1, all three usable.
  The slowest was better written and not sixty seconds better. **Defaults are
  moving aliases where a provider publishes one**, because `gemini-2.0-flash`
  was already a 404 and `gemini-2.5-flash` answered "no longer available to
  new users" on a live key the day this was written. And a thinking model
  spends `maxOutputTokens` on thinking FIRST: without a ceiling one returned
  the eighteen characters "There is no camera" and stopped mid sentence.
- **Ctrl+Alt plus a letter is AltGr, and Windows never delivers it.** Asked
  for as Alt+Ctrl+B on 12 September 2026 and it cannot work. Measured with
  real synthesised keystrokes, same handler, same id, one variable: Ctrl+B
  arrives, Alt+Shift+B arrives, **Alt+Ctrl+B fails three times out of three**.
  wx builds the accelerator quite happily (flags 3, keycode 66) and Windows
  simply never sends it, so the menu advertises a key that does nothing, which
  is the worst shape a key can have. Alt+Ctrl+Shift+S escapes it only because
  Shift takes the chord back out of AltGr territory. **Alt+Ctrl is for the
  frozen digit map and nothing else.** New keys go in the Alt+Shift or
  Ctrl+Shift families, which are measured to work.

- **Run `tests/test_3_4_1.py` the moment you add an id, before you touch
  anything else.** `ID_STREAM_TOGGLE_AUDIO` was given ID_HIGHEST+420, which is
  `ID_SEND_SETUP`, so the new key opened the send window and the handler never
  ran whatever chord was on it. The overlap check has existed since 3.4.1,
  catches it in one second, and was not run: instead the failure was chased
  through three different key combinations and blamed on Windows, which was
  only half true. A guard you do not run is a guard you do not have.

- **A menu mnemonic namespace is one per open LEVEL, which is what Windows
  does.** `tests/test_menus.py` used to pool a top level menu with all its
  submenus, deliberately stricter, and by 3.8.2 that strictness was the
  binding constraint rather than a protection: On air had 22 of 26 letters
  spoken for and the four spare ones (j, q, x, z) appear in no label anybody
  would write, so the menu could not accept another item at all. Within one
  level the rule is unchanged, and that is the half that matters: two items
  you can see at once must never answer the same key.

- **Two destinations need two of everything that NAMES them.** `stream_name`
  was the radio station and was also printed as the video channel, so the go
  live summary said "Blindside Radio, on YouTube Live" about an Icecast
  station and a YouTube channel that have nothing to do with each other.
  `video_name` exists for this and is allowed to be empty, because a platform
  with one address speaks for itself and an invented name is a new untruth in
  place of the old one. The address fields were split in two for exactly this
  reason one release earlier; the name is the same trap wearing a different
  hat, and `stream_bitrate` is still shared and still waiting to bite.

- **The picture belongs to the APP, not to where Ctrl+B is pointed.** Tony,
  12 September 2026: "ice cast, shoucast, is not the same as facebook and
  youtube." Since 3.7.0 a recording carries a picture, so `board.live_to` is
  the wrong question for every picture key, and three of them refused to work
  at all on a radio board: Alt+Shift+V would not open, Alt+Shift+T would not
  open, and Ctrl+Shift+V answered "Nothing" while a picture was being written
  to a file. **Nothing on the picture side may gate on `live_to` again.** The
  one place that question is still right is `_build_picture`, because a
  stream to an Icecast station genuinely has nowhere to put a picture and
  opening a camera for it is a light on in the room for nothing;
  `picturefeed.wanted_for` is that question and it is asked in one place.

- **One picture pipeline, reference counted, because a camera has ONE
  owner.** `picturefeed.PictureFeed`. Four things want the picture (the RTMP
  stream, the file recording, the preview behind the shot check, and the
  framing watcher) and each of them used to build its own with
  `picture.build`. That is not a performance problem, it is a correctness
  one: measured 12 September 2026, a second `CameraSource` on one device
  kills the first one's reader thread **for good**, `start()` will not
  relaunch it, and the app then blames another program for a camera Drop Deck
  is holding itself. `picture.build` has exactly one caller now and it must
  stay that way. Start on the first taker, close on the LAST, and put a new
  source in before taking the old one out.

- **`start()` is where a capture lives, and a source that was never started
  looks perfectly healthy.** This is the whole of the fault Tony reported.
  `ui._record_picture_run` built a source and did not start it, so every
  `frame()` answered None, `FallbackSource` substituted the card, and a
  recording of a card with his station name on it was written with every
  count correct and nothing said. Measured: 175 frames in six seconds, mean
  pixel difference from a freshly drawn card **zero**.

- **"Not yet" and "broken" are different answers.** `FallbackSource` treated
  the first None as a failure, latched onto the card for
  `PICTURE_RETRY_SECONDS` and announced that the picture had stopped, about a
  camera that was still opening. Measured: five of the first eight seconds of
  a split screen recording, and a spoken sentence that was false in the
  alarming direction. `_starting()` tells them apart, and the grace is **opt
  in**: only a source that counts its own `frames_read` can claim it, so a
  stand-in with neither an error nor a frame count keeps the old behaviour
  and the checks in `tests/test_video.py` still describe something real.

- **`Overlay.draw_on` never writes the array it is given, and that is not
  tidiness.** Two silent faults lived in the in-place version. `CardSource`
  hands back `np.asarray(pil_image)`, which is READ ONLY, so it raised
  `ValueError` into a swallowed except and **the overlay had never once been
  drawn on a card, on any path, since 3.5.0**: measured off a real stream, a
  lower third 1.33 grey levels from a bare card, which is absent, while
  Ctrl+Shift+V read the words out. And every source hands back its own
  CACHED array, so drawing in place drew into the cache: changed words piled
  up, and repeated blending converged a panel to fully opaque within four
  passes. A copy is about a millisecond at 720p against a 33 ms budget.

- **More stamp lead puts the content LATER, not earlier.** The name says the
  opposite and it cost two wrong guesses. Swept 12 September 2026 with
  `tools/check_recording.py`, one variable, sixteen seconds a run: lead -2
  gave +1.1 ms, **-1 gave +0.6 ms**, 0 gave -30.0, +1 gave -65.4, +2 gave
  -98.6. Exactly 33 ms a frame and monotonic. `RECORD_TAP_LEAD_FRAMES` is
  -1 because `FrameTap.take` hands over the oldest of two. **Sweep it, do
  not reason about it**, and if `FrameTap.DEPTH` changes, sweep it again.

- **Read the pixels, not the boxes.** The container says a recording's video
  starts 66.7 ms after its audio, and with `empty_moov` there is no edit list
  to correct the reorder delay, so from the headers the sound leads the
  picture by more than a viewer tolerates. Setting `bf=0` fixes the headers
  and **moved real sync 20 ms the wrong way**, measured off the decoded file
  against the decoded audio, for 14 per cent more bytes. The decoder applies
  the offset consistently. Same rule as the BT.601 colour fault, from the
  other direction: the file's numbers are the answer and its headers are not.

- **A one slot handover between two independent clocks loses a quarter of the
  frames.** The producer runs at 30 Hz and the recorder is clocked by the
  audio, so they beat: measured by burning a decodable index into every
  produced frame and decoding the file back, **455 of 1800 pictures (25.3 per
  cent) never arrived** at 640x360, with the same share of the file being
  duplicates, and six of twelve single frame events vanished completely.
  `FrameTap.DEPTH` is 2 and `take()` hands over the OLDEST, which is what
  makes the file carry the motion that was captured. Deliberately not deeper:
  a deep queue lets a slow encoder play stale pictures late, which the
  original one slot design was right to avoid.

- **A card is cheap to encode and a real picture is not, so a static picture
  proves nothing about the encoder.** `RECORD_VIDEO_PRESET` was "medium" and
  had always been encoding a card. Measured with real screen capture: medium
  is 34.57 ms a frame against a 33.33 ms budget, so it cannot sustain 30 fps,
  the ring backs up and the file **deletes audio**. veryfast is 17.85 ms for
  a file about one per cent larger. Any change here needs the measurement
  repeated with a MOVING picture.

- **Two recorders are two files with two faults.** `_on_record_state` was
  handed to both, and `videorecord.FAILED` is the same string as
  `recorder.FAILED`, so a disk fault on the MP4 ran the audio recorder's
  teardown: the WAV was abandoned mid write with its thread still alive, the
  menu label reset, nothing was said about it, and the show ended up in
  neither file. Anything given to both recorders has to work out which one it
  is talking about.

- **`_stream_settings` answers for the DESTINATION, so it is the wrong place
  to ask about the picture.** When `live_to` is the radio station it returns
  the audio dict, which has no `picture` key at all, and `picture.build` on a
  dict with no picture quietly returns a card. The shot check asked it and
  described a card Tony had not chosen, confidently, with no error anywhere.
  `_picture_settings` exists for this and everything about the picture must
  use it. **A missing key that defaults to something plausible is worse than
  a crash**, because nothing ever reports it.
- **Anything that shows the picture must work OFF air.** Tony, 8 September
  2026: "i should be able to check before going live." `preview_picture`
  builds the source, waits for it, draws the overlay on it and closes it
  again, and it is not gated on the destination being RTMP the way
  `_build_picture` is. Two things it must keep doing: **wait**, because a
  webcam is 0.58 seconds to first frame and `FallbackSource` hands back the
  card until then, so a preview that does not wait photographs the card; and
  **close**, because a camera left open by a preview is a light on in the
  room and a device no other program can have.
  **The overlay is drawn by the DESTINATION, not the source**, so any frame
  taken from a source has none of it. A shot check that offers to say whether
  the lower third covers your face cannot do it from a picture the lower
  third is not in.
- **An update that cannot be heard is an update that has hung.**
  `download` accepted a `progress` callback from the day it was written and
  `_fetch` read the whole file in one call, so nothing ever called it: the
  update was a busy cursor and a silence. It reads in blocks now. **The
  percentage is SPOKEN at ten per cent steps**, because a gauge nobody
  focuses is silent and a gauge that speaks four times a second never
  finishes a sentence. A progress callback that raises is ignored, except
  `appupdate.Stopped`, which is how the Stop button reaches a download
  already in flight.
- **`skipifsilent` is why the app never reopened after updating itself.**
  The `[Run]` entry that opens the app carried it, and the app installs with
  `/SILENT`, so the step was skipped by definition while the dialog said
  "the app will close and reopen". `RestartApplications=yes` did not cover
  it either: the Restart Manager only restarts what it closed itself and a
  PyInstaller build does not register with it. There is a second `[Run]`
  entry now, guarded on `WantsRestart`, and the app passes `/restartapp=1`.
- **The shot check ASKS, so it may as well be asked more than once.**
  `AskPanel` is one class used by the shot check and the colours window,
  because it is the same thing in both: a question, a thread, an answer.
  Two rules. A follow-up asks about **the picture that was described**, not
  a fresh one, or "is the plant still there" is answered about a frame taken
  while the presenter was moving. And `vision.converse` sends **one message
  carrying the picture and the conversation as text**, rather than a real
  multi turn exchange: the three providers shape multi turn differently and
  this app does not need the difference, so one shape that works everywhere
  beats three that each work in one place.
- **The colours window answers a question contrast cannot.** WCAG says a
  pair can be READ. It cannot say the look is dated, or that the accent has
  a hazard-tape feel, and those are real things a sighted viewer sees and
  Tony cannot. So the brand is RENDERED to a real frame and sent, rather
  than described as a list of names: a model cannot judge what three names
  look like together any better than the person asking can. The prompt says
  the reader already knows the contrast, tells it to be willing to say the
  thing looks bad, and says outright that a compliment they cannot check is
  worth nothing.
- **A word search is not a check.** `test_shotcheck` asserted "nothing in
  here remembers a consent" by grepping vision.py for "remember", and broke
  the moment `converse` gained a docstring about remembering what was
  already SAID. The property is now asserted as behaviour. Any check that
  greps source for an English word is measuring the prose, not the code.
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
  vision.py      asking a model that can see what the shot looks like
  colours.py     the brand, by name, and whether a pair can actually be read
  health.py      noticing the picture has gone black or frozen, and saying so
  send.py        the on air mix out of a sound card, for another program here
tools/
  audiopost.py       levels and seamless loops for generated audio
  make_demo_pack.py  the forty-piece demo pack, via ElevenLabs
  check_guide.py     fact-checks the published user guide against the app
  check_keyboard.py  real keystrokes into the real window. Run it by hand
  check_switching.py a real time broadcast that changes picture, then decodes
                     what arrived. The counterpart to check_stream_quality
  check_send.py      a real send into a real virtual cable, recorded off the
                     other end and counted for gaps. The only check that can
                     prove the thing 3.6.0 was built to fix
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
- **A worker thread with no COM apartment cannot open a WASAPI stream, and
  the error names the wrong thing entirely.** Measured 11 September 2026,
  with a wx dialog on screen and the cable test on a background thread,
  opening a device that had resolved correctly to WASAPI:

      Error starting stream: Unanticipated host error [PaErrorCode -9999]:
      'GetNameFromCategory: usbTerminalGUID = 7D1E ' [Windows WDM-KS error]

  A WDM-KS error, for a WASAPI device, meaning neither. The same call from
  the main thread worked every single time, and the same call on a worker
  thread with no dialog open also worked, which is exactly the shape of
  fault that gets written off as flaky and left in. Three runs out of three
  failed with the dialog up; three out of three passed with
  `CoInitializeEx` on the worker, in either apartment model.
  `cabletest._Apartment` is it, MULTITHREADED because an apartment threaded
  worker owes a message loop and a two second measurement has no window.
  **It never uninitialises an apartment it did not open**, because on the UI
  thread the one that opened it is wx.
  Nothing else in this app opens a stream off the UI thread, which was
  checked rather than assumed. Anything that starts to, needs this.
  **And the only reason it was found is that `tools/check_cable.py` presses
  the real button**: `tests/test_cabletest.py` checks every verdict against
  audio made by hand and passed throughout, because it calls the measurement
  directly. Same lesson as `ID_STATION_BASE` and the crossfade box.

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
