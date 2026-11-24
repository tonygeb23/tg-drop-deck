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
  skip the air soft clip only while it is active. It holds while
  `DuckBus.loud`. Alt+Shift+P bypasses it for the session and is never
  saved. On for new boards, off for old ones."
- "Loudness is measured on the background pass, never on a press. A trim the
  user set wins. Nothing is boosted past its own peak headroom, because the
  presenter's output has no limiter."
- Layout: `loudness.py   BS.1770 loudness in numpy`.
- The duck while talking nuance: the open microphone is still the floor; the
  second stage only goes further down while the voice is above the threshold.
- tools/run_private.py is how tests run while somebody is at the machine;
  test_proccapture and test_sourcelist play a tone and are skipped by it.

## Mac pickup

- Audio step 1: items 1 to 8 and 10 probably apply (duck reset, preview
  routing, stop all ramp, two input mic, chain rate, send loop guard, monitor
  resample, ring fill, duck while talking). WASAPI does not apply.
- Audio step 2: the two leftovers (startup card line, mic on air refusal mid
  send), the program chain and loudness matching.
- Earlier steps (wiring, security, RTMPS): collect from the final audit.

## Open points

- Firm at -2 dBFS reaches -0.73 dBTP. Suggested: -3 when Firm is chosen, or
  a true peak ceiling.
- Preferences is eleven tabs now; the guide says ten.
