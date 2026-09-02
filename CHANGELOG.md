# Changelog

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
