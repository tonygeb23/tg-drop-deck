# Major release, pending for the release candidate step

Things agents handed back for the lead to apply at the end. Not user facing.

## CLAUDE.md text to apply

- Replace "Whether the app should stop resolving ... Tony's to answer." with:
  "Since the major release, System default opens Windows' default card
  through WASAPI shared mode, never exclusive, with MME only as a fall back
  said once (`mixer.wasapi_default`). Measured 24 November 2026: 180.3 ms
  before, 22.0 after. The default microphone goes the same way. PortAudio
  fixes every default when it starts, MME's included, so a Windows default
  changed mid session is not followed until restart, as before."
- "The on air sound shapes what goes out, never what the presenter hears.
  `dsp.ProgramChain` runs once each in the stream, both recorders and the
  send, after their bus sums the cards, each with its own state. The mixers
  skip the air soft clip only while it is active. The leveller holds only
  while `DuckBus.music_down`, a mixer's duck gain really below unity, never
  merely because a microphone is open. The ceiling is a true peak ceiling
  (`dsp.TruePeakCeiling`, 1.2 ms of lookahead on the program path only);
  Firm starts at -3. Every block is made finite first: one inf used to
  silence the stream for the session. Alt+Shift+P crossfades over 50 ms,
  is never saved, and a bank 4 pad that already has the key keeps it. On
  for new boards, off for old ones."
- "**The send's loop guard goes by the cable's own name, never by the
  registry.** Windows pairs a device's two ends by the card, so a headset's
  speakers and microphone look like a loop and a guest gets taken off the
  air. Only a known virtual cable's other end, or a Loopback or Stereo Mix
  input on the card being sent into, is refused (`routing.loops_back`). A
  false refusal is worse than a missed loop (Mark, 24 November 2026)."
- "Loudness is measured on the background pass, never on a press, and the
  numbers belong to one version of one file: path, size and modification
  time, checked on every pass and when the window comes back. Numbers from a
  board file may only cut until checked here. A trim the user set wins,
  0 dB included (`trim_set`). Nothing is boosted past its own peak headroom, because the
  presenter's output has no limiter."
- Layout: `loudness.py   BS.1770 loudness in numpy`.
- The duck while talking nuance: the open microphone is still the floor; the
  second stage only goes further down while the voice is above the threshold.
- tools/run_private.py is how tests run while somebody is at the machine;
  test_proccapture and test_sourcelist play a tone and test_framing opens
  a real camera, so it skips all three unless --with-sound or
  --with-camera.

## Mac pickup

- Audio step 1: items 1 to 8 and 10 probably apply (duck reset, preview
  routing, stop all ramp, two input mic, chain rate, send loop guard, monitor
  resample, ring fill, duck while talking). WASAPI does not apply.
- Audio step 2: the two leftovers (startup card line, mic on air refusal mid
  send), the program chain and loudness matching.
- Audio step 3: the loop guard by cable name, the second talker coming back
  at once, sanitising NaN and inf in the program chain and the resampler,
  music_down for the leveller, loudness stamps and board value checks, the
  stop event for measuring, the compare key yielding to a pad, the 50 ms
  compare crossfade, the true peak ceiling, the ring rescue, trim_set.
- Earlier steps (wiring, security, RTMPS): collect from the final audit.
- Speech and keys (15785c8): the short mic lines (MainWindowAir.swift:56 and
  :111, menu title AppDelegate.swift:511), Back on air, the Delete question
  on the track on air, the radio hint in Preflight.swift, F7 and F8 saying
  what you hear only for a recording or the send, Alt+Enter on a row, the
  global hotkey sentence off a pad, the search count delay
  (Panels.swift:206). The Escape count and the Streaming location sentence
  are already right on the Mac.
- Where options live (9061234): the Command B wording, the cue sheet on the
  Playlist menu, an Add songs key that yields to a pad, the mic box moved
  and renamed, What I listen on, the ducking label, the status order, the
  Command S rule for a board never named. MOST IMPORTANT: the third title
  value `artist_title_album` and the album tag. The Mac treats that value
  as its default and writes `title_by_artist` back over it, so a board
  shared through Dropbox loses the choice.
- Review fixes (23de026): the Mac reads the new mic channel `average` as
  `mix` and saves `mix` back, so "Both, always mixed" is lost after a Mac
  save. The Mac keeps `never_named` as an unknown key, so a Mac Save As
  copies `true` into the named file: it should honour the flag on Cmd+S and
  clear it on Save As. Also the wording (the Ctrl+M reason first, the
  compare and its Ctrl+Shift+H hint, the Firm ceiling line, the station mic
  sentence, the first start note, the pad held labels, the label renames),
  Delete twice on the track on air instead of any box, and the status bar
  read whole if AppKit truncates it.

## Open points

- Firm at -2 reached -0.73 dBTP: fixed in step 3 (true peak ceiling, Firm
  at -3). AAC 128k on a brickwalled master can still decode over full scale,
  which no ceiling before the encoder can promise.
- Preferences is eleven tabs now; the guide says ten.
- Noticed in Area 5, not fixed: with titles off, the video card gets the
  first song at go live and never updates; after a restart a board that was
  never named is not recognised as one, so Ctrl+S saves it in place; "Saved
  to X.json" still says the extension after Save as.
