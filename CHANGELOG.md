# Changelog

## 2.5.1 — 2 September 2026

**There is a user guide.** [tgstudios.app/drop-deck-guide](https://tgstudios.app/drop-deck-guide/),
and in the app under **Help, User guide**. Plain English, every key explained,
and written for somebody who has never opened the app. `F1` is still the key
list; the guide is the why.

It is on the web rather than in the app on purpose, so it can be put right the
day somebody finds it confusing rather than at the next release.
`tools/check_guide.py` checks it against the app it describes — every keystroke
it names, and every number it quotes.

**Save board as is Ctrl+F12**, not F12. A bare F12 is one keystroke away from
the volume and rename row and too easy to hit by accident for something that
opens a save dialog. Nothing else moved.

**The crossfade box says what it does.** It sits under the running order with
the explanation beside it: the next song starts that many seconds before the
one playing ends, so every start time in the list moves when you change it.

**And it is in Audio settings as well**, which is where somebody looking for
"how long do songs overlap" goes first. The two boxes are two views of one
number — set it in either and the other shows it.


## 2.5.0 — 2 September 2026

The biggest release since 2.0.0, and most of it is new ground rather than
fixes. Treat it as experimental: it has had a lot of tests and not a lot of
shows.

### A playlist, next to the soundboard

`Ctrl+Shift+P` goes to it, `Ctrl+Shift+S` comes back, and `Ctrl+Alt+Tab` swaps.
Paste songs in with **`Ctrl+V`** — as many at once as you like, straight from
File Explorer — or drag them in.

**Each song hands over to the next before it ends.** That overlap is the
crossfade and that handover point is the song's cue. The crossfade box sits
under the running order, and a single track can be given one of its own from
its right-click menu.

**Every track has a tick.** Unticked stays in the list, keeps its place, and is
stepped over — "play this, this and this, not that". `Enter` plays from the one
you are on, `Delete` takes it out, `Alt+Up` and `Alt+Down` move it, and the
Applications key opens a menu with all of it plus **Segue to this now**, which
crosses to a track at the crossfade length instead of waiting for the cue.

The playlist has its own fader on **`F7`** and **`F8`**, and it ducks under
sounds, drops and the microphone.

### Drops, and a drops library

Put a drop between two songs, or after every so many songs. Better: put the
idents you use over and over into the **drops library**, and **`Alt+D`** drops
one in at random wherever you are standing — never the same one twice running.

### A microphone

**`Ctrl+M`** opens and closes it. **`Ctrl+Shift+M`** is where you choose which
microphone, how much gain, which output you hear yourself on, and whether you
hear yourself at all.

**While the microphone is open, the beds and the playlist duck out of the way**,
and they come back the moment you close it. That happens because it is open,
not because you are talking — a gate that opens on your voice clips the first
word of every sentence.

Hearing yourself is off until you turn it on: on headphones it is how you know
you are live, on speakers it is a feedback loop. It can go to an output of its
own, so monitoring sits in your headphones and the show does not. Nothing opens
your microphone but you pressing `Ctrl+M`.

### Telling us things

**Help → Submit feedback.** Pick what kind of thing it is, write a sentence,
send. It shows you exactly what goes with it — the version, and your audio and
speech settings — and **never a file name, a sound name, a bank name or
anything from your running order**. If you are offline it is saved and goes out
next time; nothing is lost.

**Help → Donate.** Drop Deck is free and it is staying free. The app mentions
donating about once a week at the very most, never in your first week, and
there is a "do not ask me again" on that window.

### Save board as is now F12

`Ctrl+Shift+S` became "go to the soundboard" in this release, and it turned out
to beat the menu — so *Save board as* had quietly stopped working. It is
**`F12`** now, which is what Save As is in Word and Excel. Nothing else moved.

### Fixed

- The relink tool crashed the moment it repaired a track in the playlist.
- Dragging files onto the running order did nothing, because the drop target
  was on the panel the list covers.
- A track that would not decode was retried twenty times a second, forever, in
  silence. It now stops and says which one it was.
- Six pairs of menu items shared a keyboard letter, so Alt plus that letter
  cycled instead of choosing. Two of those pairs had been there for releases.
- Renaming a bank or a sound now hands you the old name selected, the way every
  other Windows rename does, and applies the change before the dialog closes so
  a screen reader cannot read you the old name on the way out. *Brian Hartgen.*


## 2.4.0 — 2 September 2026

Three requests and one bug that had been hiding since 2.1.2.

### Call the banks whatever your board needs them to be called

David Goldfield's, and it is a fair point: a board you built yourself is not
"Sound Effects" and "Dialog Drops". It is "Movie Clips" and "Sirens and
Alarms".

**`Ctrl+F2` renames the bank you are looking at**, and there is a new **Banks**
menu with rename and reset in it. The name saves with the board and appears on
the tab, in the search list and on the per-bank output rows in Audio settings.

**The name is all that changes.** Bank 3 is still the looping bank and bank 4
still takes your own hotkeys — those are what the keys do, not what the tab
says, and the app tells you so when you rename either of them. The number
stays on the tab too, because it is which `Ctrl+Tab` position you are on.

### One key, a whole folder, a different sound every press

Brian Hartgen's: a chart countdown has half a dozen jingles that all mean
"down the chart", and you do not care which one you get as long as one plays.

**Sounds → Assign a folder**, or the same item in the right-click menu. The
slot then plays a random sound from that folder every time you press it, and
**never the same one twice running** — which is the difference between random
and broken. It says which one it picked, so you always know what went out.

Drop another file into the folder and it joins in; nothing needs re-assigning.
A folder with nothing playable in it is refused when you assign it, rather
than becoming a key that does nothing on air. Relink handles folders too, and
will not quietly repair one with a file that happens to share its name.

### Play in the Find dialog no longer throws you out

Also Brian's. With several matches you want to hear which is which before you
commit, and being dropped out of the dialog on the first press made that four
keystrokes per guess.

**`Alt+P` now plays the match you are on and leaves the dialog open.** Enter
still jumps to the sound and closes. The results list is deliberately not
relabelled while you do this — rewriting a row under a screen reader restarts
the announcement on the row you are standing on, and you can hear the sound
anyway.

### The startup announcement works again

Since 2.1.2, the line the app speaks when it opens has been raising an error
inside its own timer and never arriving. Nothing reported it, because a timer
swallows what its callback raises.

So **"3 files missing. Use File, relink missing sounds" has not been spoken at
startup for three releases**, and neither has "audio could not start". Both are
back. The line is also wrapped now, so if it ever fails again it says so in the
status bar instead of vanishing.


## 2.3.0 — 2 September 2026

Both of these came from Brian Hartgen, who is customising a board heavily for
his own show.

### Music beds now start exactly where the file does

A bed used to ease in over about a third of a second. If you cue a bed on its
first beat, that is the beat it eats — and there was no way to ask for anything
else, because the fade was a fixed number in the code.

**Beds no longer fade in at all by default.** A bed is at full level on its
first sample and plays out as recorded. Stopping one still fades, over about
six tenths of a second, because a bed cut dead mid-phrase is a different and
much more obvious mistake.

**Audio settings, `Ctrl+P`, has both fades in seconds** if you want the old
behaviour, or something between. They travel with the board, so a board built
for one show keeps its own. Sounds and drops are untouched — they have never
faded.

### A button tells you the truth the moment you change it

Assign a file to an empty bed and the button went on saying "2. Empty, key
Alt+Ctrl+2" until you tabbed away and came back. Turn looping off and it still
said "loops". Every edit in the app was like this, which made it genuinely hard
to know whether anything had been applied.

**The button is relabelled as soon as you change it** — assigning, renaming,
looping, levels, either kind of hotkey, and opening a board.

What has *not* changed is the reason the delay was there. When a sound starts
or stops on the button you are standing on, the label still waits until you
move off it, because rewriting it there restarts your screen reader mid
sentence, on air. That was always the right call for the state; it was never
right for something you had just done deliberately.

## 2.2.1 — 30 August 2026

**Checking for updates now answers you in a window.** Before, the "you are up
to date" reply was spoken and nothing else — so if you had turned the app's
speech down, choosing Check for updates appeared to do nothing at all.

The answer sits in a read-only box you can arrow back through rather than a
message you hear once, it names the program so you know which one replied, and
release notes for a new version can be read properly before you decide.

## 2.2.0 — 30 August 2026

All of this came from David Goldfield and Brian Hartgen, who wrote in the same
morning after using 2.1.2.

### The function key row makes sense now

**F2 renames**, because that is what F2 does in every other Windows program.
The volume keys moved down one to make room:

| Key | What it does |
|---|---|
| `F2` | Rename the sound you are on |
| `F3` / `F4` | Sound volume down / up — banks 1, 2 and 4 |
| `F5` / `F6` | Bed volume down / up — bank 3 |

None of the number keys moved. `1`–`0` with Shift, Ctrl, Ctrl+Shift and
Alt+Ctrl are exactly where they have always been.

### Ctrl+F finds things

`Ctrl+F` is the key everyone reaches for, so that is what the menu says now.
**`Ctrl+E` still works** and always will — a key you have already learned does
not get taken away to tidy up a menu.

### Alt on its own is a modifier

Assigning `Alt+A` as a global hotkey was impossible: the dialog handed Alt plus
a letter to its own buttons instead of capturing it. It captures it now. Tab
still reaches every button and Delete still clears the key, so nothing became
unreachable.

`Alt+F4` is the one combination it will not take. That closes a window in every
Windows program, and a system-wide hotkey would take it away from all of them.

### Properties, on Alt+Enter

One dialog with everything about a sound in it: its name, its level in
decibels, whether a bed loops, its hotkey inside the app, and its global
hotkey. Cancel really does leave the board alone.

**The right-click menu now offers the global hotkey too**, and reads out what
it is currently set to. Before, that lived only in the Sounds menu — so the
menu people actually open did not offer the feature at all.

### The app talks less, if you want it to

**Audio settings** has a *Spoken feedback from the app* setting with three
levels:

- **Everything** — the default. Nothing changes.
- **Only what I cannot hear or read for myself** — no confirmations, no bank
  hints, no sound names. A missing file, a hotkey Windows refused, and the
  volume readouts still speak.
- **Nothing** — the app never speaks. Your screen reader carries on reading
  every control, and the status bar still shows all of it.

**The bank hint is now spoken once per bank, per session, instead of on every
tab change.** Your screen reader already says "Dialog Drops, tab selected";
twenty more words of help on top of that was two announcements for one
keystroke. The hint is still printed on the page and still in F1.

## 2.1.2 — 30 August 2026

Both of these came from Brian Hartgen, who wrote in after using the app.

### Send a bank to its own output

**Audio settings** now has an output for each of the four banks. Leave them on
the main output and nothing changes; set Music Beds to one sound card and
Dialog Drops to another and you can bring each up on its own channel of a
physical mixer.

That is for people who would rather set the balance themselves than let the app
duck automatically. Ducking is still there, still on by default, and **it still
works across outputs** — a drop on one card ducks a bed on another, because
turning ducking off by accident is not an acceptable side effect of routing.

Banks sharing an output share one audio stream, so the ordinary case of
everything on one card costs nothing.

If a remembered device is not there when you start — unplugged, or being held
by another program — that bank falls back to the main output and **says so**
rather than going quietly silent.

### Turn off the announcement when a sound starts

**Audio settings**, *Say the name when a sound starts or stops*. Turn it off if
you set the board up yourself, know where everything is, and can hear the sound
perfectly well without being told about it.

What it does not silence: anything you cannot hear. A missing file, a sound
that would not play, and stopping everything all still speak. The status bar
keeps showing the name either way — only the interruption is optional.

## 2.1.1 — 29 August 2026

**One copy at a time.** Opening Drop Deck when it is already running now brings
the copy you have back to the front instead of starting a second one.

Two soundboards open at once is not only clutter. They fight over the same
board file, and both hold the audio device, so the second can look perfectly
fine and make no sound at all.

A second launch reopens the first rather than just refusing, which matters if
you are not watching the screen: a launch that silently does nothing looks
exactly like the program failing to start.

## 2.1.0 — 29 August 2026

### Global hotkeys

Assign a key to any sound and it fires **while another program has focus**.
That is the point of a soundboard on a live show: you are in the DAW, the
browser or a call, and alt-tabbing to the board first is the whole problem.

Sounds menu, **Assign a global hotkey**, on any slot in any bank. **Ctrl+G**
arms and disarms the whole set, and disarming hands the combinations back to
the rest of the system.

Two things it deliberately will not do:

- **It never registers a bare key.** A system-wide hotkey with no modifier
  takes that key away from every other program on the machine, including the
  one you are typing into. Anything without Ctrl, Alt, Shift or Win is refused,
  and the refusal says why.
- **It never touches the map you already know.** The digits, the Shift and Ctrl
  layers, F2/F3 and F5/F6 are exactly as they were. A global hotkey is a
  second, separate key you assign on purpose. Ctrl+G is a new key, not a
  borrowed one.

A hotkey another program already owns is reported rather than swallowed — one
that silently does nothing is worse than one that says it is taken, because you
find out on air.

### It updates itself

2.0.0 shipped as a zip with no channel that could carry a new version, so this
release had to be a manual download. From here the app checks once a day in the
background, tells you when there is something new, and **always asks before it
downloads or installs anything**. The manifest is signed and the installer is
checked against a hash in that signed manifest before it runs.

This is now standard across every TG Studios program.

### Also

- **An installer**, per-user and with no administrator prompt, which is what
  the updater can actually run. The zip is still there for anyone who would
  rather unpack a folder.
- **A real app icon** in the title bar, the taskbar, the installer and
  Add/Remove Programs, instead of the Windows default.
- **No longer blurry.** The app now tells Windows it is DPI aware, so at 125%,
  150% or 200% it draws its own pixels instead of being scaled up from a
  smaller bitmap. That display scale is itself an accessibility setting, so the
  people it was worst for were the people most likely to need it.
- Builds now happen entirely outside Dropbox. `--clean` was failing on files
  Dropbox still had open.

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
