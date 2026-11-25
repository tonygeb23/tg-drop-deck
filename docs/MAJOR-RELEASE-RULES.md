# Rules for everyone working on the major release (from 3.10.1)

The work list is `docs/REVIEW-2026-11-24.md`. Tony's order, 24 November 2026:
"do it all into one major release, one thing at a time, with verified checks
ensuring a good audit." Windows only.

## Hard rules

- **Read `CLAUDE.md` in this folder first.** Every standing rule there holds.
  The ones most likely to be broken by accident: no em dashes or en dashes
  anywhere (code, comments, strings, docs); the digit map is frozen; a key
  users learned is never taken away; nothing goes between a keypress and a
  sound; nothing opens a microphone except a keypress; the mic ducks by being
  OPEN; OUTPUT_BLOCKSIZE stays zero; mix minus is a subtraction off one read;
  Ctrl+Alt plus a letter is AltGr and never arrives (new keys go in Alt+Shift
  or Ctrl+Shift); run `tests/test_3_4_1.py` the moment you add an id.
- **Do not touch `mac/`.** Not one file. If the Mac needs the same fix, write
  it down in your report and it goes in a pickup doc.
- **Tony is at this machine with NVDA running.** So:
  - Run tests ONLY through `python tools/run_private.py tests/test_x.py ...`.
    It starts each file on a private desktop and silences speech. Never run a
    test file directly with python: it would put windows on Tony's screen and
    speak through NVDA.
  - Never send keystrokes or mouse input: no SendInput, no
    wx.UIActionSimulator, no AttachThreadInput, no SetForegroundWindow, and do
    not run `tools/check_keyboard.py`, `tools/check_video_key.py` or any other
    tool that presses keys.
  - Do not launch the app itself (`main.py`, `launch.pyw`, the built exe).
  - Do not play sound through the speakers. Offline renders with
    `open_stream=False` are fine, as the existing tests do.
- The runner skips `test_proccapture` and `test_sourcelist` (they play a
  tone) and `test_framing` (it opens a real camera). Never force them.
- **Do not commit, push, build, bump the version or edit CHANGELOG.md.** The
  lead does those after checking your work.
- **Do not touch the website or the server.** The guide edits happen in their
  own step.

## How to work

- One item at a time, smallest correct change, in the style of the code
  around it. The codebase explains WHY in its comments; keep new comments to
  the reason a future reader would otherwise undo the change.
- Every fix gets a check that FAILS on the old code and passes on the new.
  Put them in the test file your brief names, in the style of
  `tests/test_3_10_1.py` (a `check(name, cond)` counter, a final
  "N/M checks passed" line, a non-zero exit on any failure).
- Prove the thing the user does, not the function you changed. A key or menu
  item is proved through its BINDING (post the command event to the window
  that really receives it), never by calling the handler directly: that is
  the lesson of `ID_STATION_BASE` in CLAUDE.md.
- Before reporting, run your new file AND the existing files that cover the
  code you touched, through `tools/run_private.py`. Known to fail on a private
  desktop for reasons that are the desktop, not the code (they also fail on
  untouched 3.10.1): `test_3_4_1` (screen capture checks only), `test_3_5_1`,
  `test_feedback_2_7`, `test_proccapture`, `test_stopping` (fade check),
  and `test_playlist` can hang at teardown
  after every check passed. Compare against the baseline in your brief rather
  than assuming.
- `python tools/nodashes.py` on every file you changed.
- Write the user-facing change, one or two plain sentences each, no jargon,
  at the end of `docs/MAJOR-RELEASE-NOTES.md` under your area's heading.

## Your report

Under 700 words, headings and bulleted lists, no tables, no dashes:

- Each item: done or not, file:line, and the check that proves it.
- Test results: file by file, passed or failed, with the counts, and any
  failure compared with the baseline.
- Anything you found that was wrong in the review itself, or a new defect you
  noticed and did not fix.
- Anything the Mac copy probably needs too.
