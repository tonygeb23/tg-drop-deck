# Mac pickup: what Windows 3.9.0 changed, and Siena's Mac report

**Mac status:** Items 1 to 4 done on the Mac in Mac 3.10.0, 16 November 2026 (item 5 needed nothing). The pause key is Option+Shift+R. Ali's record-every-source request is still not started anywhere.

Written on Windows, 16 October 2026. **Nothing under `mac/` was touched** (the
platform rule in CLAUDE.md). This is the list for the next Mac session, done
on the Mac. Windows details: CHANGELOG.md, 3.9.0 for Windows, and
`tests/test_3_9_0.py`.

## 1. Relink fails on a board made on Windows. A real Mac bug, Siena's report

Siena, 12 October 2026: board made on Windows, saved to Google Drive; relinked
fine on another Windows laptop; on the Mac, File, Relink missing sounds, chose
the Drive folder, got "16 sounds still missing".

Cause, read from the Mac source: `relinkFinished` in
`MainWindowActions.swift`, `Playlist.relink(using:)` and
`DropLibrary.relink(using:)` in `Playlist.swift` all take the file name with
`(path as NSString).lastPathComponent`. On macOS a backslash is not a
separator, so for `G:\My Drive\SienaT Radio\intro.mp3` that returns the
WHOLE string, which matches no file name in the index. Every Windows path
fails, every time.

Fix: take the last part after either `/` or `\` (Windows now does exactly this
in `board._basename`). Also worth matching by name without its extension for
sound files, which Windows has always done for pads. Add a selftest with a
Windows path.

Also: `Board.from(dict:relativeTo:)` joins any path that is not
`isAbsolutePath` onto the board's folder. A Windows absolute path is not
absolute on the Mac, so it becomes `<board folder>/G:\My Drive\...`. Harmless
once relink can read it, but worth treating `X:\` and `\\server\` as absolute.

## 2. Boards that travel (Ali Moosa's report, Windows has it in 3.9.0)

- **Look beside the board on open.** Windows `Board.find_beside`: when
  anything is missing, index the board's own folder, 3 levels deep, 2
  seconds, 20000 entries at most, relink from it, and say "Found N missing
  sounds in the board's own folder".
- **Save relative.** A sound under the board's folder is written relative,
  with forward slashes. The Mac already READS relative paths; it should
  write them too, or a Mac save turns a portable board back into a Mac only
  one.
- **File, Export board with its sounds.** One folder: `<Board>.json` plus
  `Sounds/`, every pad, folder pad (its sound files, as a folder), playlist
  track and drop copied once, duplicate names get " (2)", paths written
  relative with forward slashes, missing ones left as they were and counted.
  Spoken progress at 10 per cent steps over 50 MB.
- **Count everything missing** when a board opens: pads, playlist and drops.

## 3. Recording speech (Siena: "it doesn't actually announce")

On Windows the cause was the file's full path being read out straight after
the sentence and cutting it off. The Mac does not do that: it says "Recording
to Drop Deck Stream 004.mp3" through `announceState`, at every level. So on
the Mac the likely causes are the other two Windows found:

- **The words.** It never says "started". Lead with "Recording started",
  then the detail; "Recording stopped", then "Saved as ...".
- **The menu.** Siena chooses it with VO+M. When the menu closes VoiceOver
  reads where focus lands, and that can talk over the announcement. Windows
  waits 400 ms after a menu closes before speaking. Measure what VoiceOver
  needs before copying the number.

Worth asking Siena whether she used the key or the menu.

## 4. Pause and resume

Windows: Alt+Shift+R, On air, "Pause recording" / "Resume recording". Pauses
the sound and picture recorders together (if either is paused the key
resumes both), reads and discards the mix while paused so the ring never
fills, takes and drops waiting pictures, and notes the current track in the
cue file on resume. Says "Recording paused, N minutes N seconds so far" and
"Recording resumed". Mac key to be chosen on the Mac (Option+Shift+R is the
obvious mirror; check VoiceOver and the system first).

## 5. Microphone menu

Nothing to do: the Mac already has both items on On Air. Windows moved to
match it in 3.9.0.

## Not started anywhere

Ali Moosa's request to record every source, the soundboard and the playlist
to separate files, with gaps filled with silence. A design of its own; see
the session proposed for it.
