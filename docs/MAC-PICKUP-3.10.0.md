# Mac pickup: what Windows 3.10.0 changed, and the Mac reports since October

Written on Windows, 16 November 2026. **Nothing under `mac/` was touched**
(the platform rule in CLAUDE.md). This is the list for the next Mac session,
done on the Mac. Windows details: CHANGELOG.md, 3.10.0 for Windows, and
`tests/test_3_10_0.py`. Everything in `docs/MAC-PICKUP-3.9.0.md` is still
open too; this file adds to it and does not replace it.

Do them in this order. Item 1 is losing people's boards today.

## 1. File, New board writes over the board you had. Same bug as Windows

Siena Trigiani and Rob Castrogiovanni, 15 November 2026. Siena broadcasts
from the Mac, so this is hers first. Steps: save a board under a name, add
sounds, save, Command+N, then build the next board. Open the first one
later: empty.

Read from the Mac source, not run:

- `MainWindowActions.swift`, `newBoard()` calls `adopt(fresh, path: nil)`.
  In `adopt`, a nil path means "keep the path the board object already has",
  so the empty board stays on the OLD board's file. `claimIfUnknown()` then
  does nothing, because that file is known. The next `touch()` (the first
  sound added to the new board) or `saveForClose()` on quit writes the new
  board over the saved one. The comment above `claimIfUnknown` describes
  exactly the decision that causes this.
- `loadDemoPack()` and `importOldBank()` both call
  `loadInto(path, keepPath: false)`, which is the same nil path, so the demo
  and an imported bank also land in whatever board was open.
- `openBoard()` goes straight to `loadInto` with a save timer possibly still
  pending, so a change made in the last two seconds is dropped, and the timer
  then fires on the board that arrived.

What Windows does now, to mirror (`dropdeck/ui.py`):

- `_put_away()`: before ANY board replaces the open one, stop the save timer
  and save a dirty board to its own file. If that save fails, ask (keep the
  changes: No, then Save board as; Yes goes on and loses them; No is the
  default).
- `_give_new_home()` / `_new_home()`: New, Load demo and Import each get a
  file of their OWN in the settings folder: "New board", "New board 2",
  "Demo board", or the imported bank's own name. Never an existing file,
  never one of the app's own files there (`_SETTINGS_OWN`), claimed as
  nothing there, and **not written until something changes**.
- The save timer writes only a dirty board (`_autosave`). The save on the way
  out skips a new board nobody touched (`_save_for_close`), so no empty file
  is left and the board that opens next time is still the one last saved.
- Save board as from a not yet named board removes the "New board" file it
  was kept in, but only if this session made it, this board wrote it, and it
  has not changed on disk since (`_leftover_home`).
- Work that comes back from a thread after its board has gone (relink, the
  playlist tag pass) is saved to the board it was done to, not credited to
  the live one (`_still_open`). Check the Mac's relink and metadata passes
  for the same late `board` read. On the Mac the board OBJECT is reused
  (`replaceContents`), which makes this harder to see, not safer.
- The box: title "New board", "Start a new, empty board?" then "NAME is saved
  first and stays exactly as it is. File, Open board brings it back." OK and
  Cancel. Asked when the board holds pads OR a running order. For the
  unsaved demo pack the second sentence is "The demo pack comes back with
  File, Load demo pack."
- Spoken after, at every level but none: "New board. NAME is saved and
  untouched. Eighty empty slots. Ctrl+F12 gives this one a name" (use the
  Mac's own Save as key in the sentence). The default board is called "Your
  board". The status before the description, because it is the half somebody
  is waiting to hear.
- Speech straight after a box or a file panel closes is deferred and queued,
  the way speech after a menu is. Measure what VoiceOver needs.

The regression test must assert what Mark's list says: for each of New, Load
demo, Import and Open, the outgoing file is byte for byte unchanged after the
autosave AND after quitting, the default board file is unchanged, and no new
file exists until something is edited.

**Tell Siena and Rob plainly:** a board already overwritten cannot be brought
back by an update. Their sound files are untouched; the board has to be
rebuilt.

## 2. Suno files will not play (in-app feedback 46, Mac 3.8.4, 21 October)

"I have loaded songs from suno one in mp3 and one in m4a format but they
won't play. I can provide the songs for you if it'd help." This is Raymond
(the same sender as the camera permission reports); his address is in
feedback row 41 on the licence server.

Not reproduced: nobody here has his files. Ask him for the two files first.
`AudioFile.swift` opens everything with `AVAudioFile(forReading:)` and has no
second decoder. Windows has two (libsndfile, then FFmpeg through PyAV), which
is why a file Core Audio refuses can still play there. Things to look at once
the files are in hand: an MP3 with a very large ID3 tag or embedded artwork
in front of the audio, and an M4A whose brand or codec AVAudioFile will not
open. A fallback through `AVAssetReader` covers most of what `AVAudioFile`
refuses. Also check what the app SAYS when a file will not decode: "they
won't play" suggests it said nothing useful.

## 3. Preferences, Recordings has no Browse button (Ali Moosa, 17 October)

"I see there is a path to enter a location, but there isn't a browse button,
where a location can be selected in Finder." The video page already has one
(`Preferences.swift`, `browseButton`, about line 503). Give the recordings
folder the same.

## 4. A board that is all running order opens on the running order

Ali Moosa, 16 October (he uses JAWS on Windows and VoiceOver on the Mac):
opening a board that held only a playlist landed on eighty empty pads.

Windows now: on File, Open and at startup, a board with no pads and at least
one track moves to the playlist view with focus in the list, silently, and
the Loaded line says it in one sentence: "Loaded NAME, 12 playlist tracks,
now in the playlist". With both: "Loaded NAME, 20 sounds, 12 playlist
tracks". Never on the reload after a file changes on disk, which must not
move focus. The Mac's Loaded line also reads the file name with its
extension (`lastPathComponent`); Windows drops the ".json".

## 5. Export asks for a name (in-app feedback 45, 17 October)

When the Mac gets Export board with its sounds (still open from the 3.9.0
pickup), ask what to call it first, prefilled with the board's name and
selected. The folder and the board inside take that name. Windows strips
what a file name cannot hold and a typed ".json".

## 6. Nothing to do on the Mac

- **The swap key.** Windows gained Alt+Shift+W because its menu advertised
  Ctrl+Alt+Tab, which Windows keeps for itself, and an NVDA add-on
  (Clipboard Announcer) takes Ctrl+Shift+S. Neither applies on the Mac.
  Worth one check that the Mac's own view keys do not collide with a
  VoiceOver or system command.
- **The cable test and the muted cable** (each end at its own rate; a cable
  muted in Windows is said). Windows only. If the Mac's `CableTest.swift`
  assumes one rate for both ends of a virtual device, the same fault may
  exist there; BlackHole and Loopback keep one rate, so probably not.

## Not built anywhere, waiting on Tony

- Ali Moosa: record every source to its own file. Its own design session.
- In-app feedback 44: duck the music while talking, not only while the
  microphone is open. This is against the standing rule (the microphone ducks
  by being OPEN) and was not built.
- A Recent boards list on the File menu, for Ali's three shows.
- Raymond's earlier requests (feedback 41): duck another program as a source,
  and take picture plus sound from a browser for reaction videos.

## People to answer once the Mac build is out

Siena (boards, and she asked to meet; a call is booked through Calendly for
17 November), Rob Castrogiovanni (boards; and yes, Facebook Live works
already: Preferences, Video streaming, Facebook), Ali (running order, Browse
button), Raymond (Suno files, once reproduced).
