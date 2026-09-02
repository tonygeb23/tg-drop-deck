# Changelog

## 2.5.1, 2 September 2026

**There is a user guide.** [tgstudios.app/drop-deck-guide](https://tgstudios.app/drop-deck-guide/),
and in the app under Help, User guide. Plain English, every key explained. `F1`
is still the key list; the guide is the why.

**Save board as is `Ctrl+F12`**, not a bare `F12`. F12 sat one key from the
volume row and was too easy to hit by accident. Nothing else moved.

**The crossfade box now says what it does.** It sits under the running order
with the explanation beside it. It is also in Audio settings, which is where
most people look first. Set it in either and the other shows it.

## 2.5.0, 2 September 2026

The biggest release since 2.0.0. Treat it as experimental: plenty of tests, not
many shows yet.

### A playlist

`Ctrl+Shift+P` goes to it, `Ctrl+Shift+S` comes back.

Paste songs in with `Ctrl+V`, straight from File Explorer, as many at once as
you like. You can drag them in too.

Each song hands over to the next before it ends. That overlap is the crossfade,
three seconds to start with.

Every track has a tick. Unticked stays in the list, keeps its place, and is
skipped. `Enter` plays from the track you are on, `Delete` removes it,
`Alt+Up` and `Alt+Down` move it. The Applications key opens a menu with all of
it, plus Segue to this now for getting out of a track early.

The playlist has its own fader on `F7` and `F8`.

### Drops, and a drops library

Put a drop between two songs, or after every so many songs.

Better: put the idents you use over and over into the drops library, and
`Alt+D` puts one in at random wherever you are standing. Never the same one
twice running.

### A microphone

`Ctrl+M` opens and closes it. `Ctrl+Shift+M` sets it up: which microphone, how
much gain, which output you hear yourself on, and whether you hear yourself at
all.

While the microphone is open, the beds and the playlist duck out of the way.
They come back the moment you close it. That happens because it is open, not
because you are talking. A gate that opens on your voice clips the first word
of every sentence.

Hearing yourself is off until you turn it on. On headphones it is how you know
you are live. On speakers it is a feedback loop. It can go to an output of its
own, so monitoring sits in your headphones and the show does not.

Nothing opens your microphone except you pressing `Ctrl+M`.

### Telling us things

Help, Submit feedback goes straight to the person who wrote the app. It shows
you exactly what goes with your message, which is the version and your audio
and speech settings. Never a file name, a sound name, a bank name, or anything
from your running order. Offline, it is saved and goes out next time.

Help, Donate. Drop Deck is free and it is staying free.

### Fixed

- Relink crashed the moment it repaired a track in the playlist.
- Dragging files onto the running order did nothing.
- A track that would not decode was retried twenty times a second, forever, in
  silence. It stops now and says which one it was.
- Six pairs of menu items shared a keyboard letter, so Alt plus that letter
  cycled instead of choosing. Two of those pairs had been there for releases.
- Renaming a bank or a sound now hands you the old name selected, the way every
  other Windows rename does, and applies the change before the dialog closes so
  a screen reader cannot read you the old name on the way out. Brian Hartgen.

## 2.4.0, 2 September 2026

### Rename the banks

David Goldfield's, and a fair point: a board you built yourself is not "Sound
Effects" and "Dialog Drops". It is "Movie Clips" and "Sirens and Alarms".

`Ctrl+F2` renames the bank you are looking at, and there is a Banks menu with
rename and reset. The name saves with the board.

The name is all that changes. Bank 3 is still the looping bank and bank 4 still
takes your own hotkeys, and the app says so when you rename either.

### A folder on one key

Brian Hartgen's: a chart countdown has half a dozen jingles that all mean "down
the chart", and you do not care which one you get.

Sounds, Assign a folder. The slot then plays a random sound from that folder
every press, never the same one twice running, and says which one it picked.
Drop another file into the folder and it joins in.

### Play in the Find dialog no longer throws you out

Also Brian's. `Alt+P` plays the match you are on and leaves the dialog open, so
you can work down a list of hits. `Enter` still jumps and closes.

### The startup announcement works again

Since 2.1.2 it had been failing silently inside its own timer, so "3 files
missing" and "audio could not start" were never spoken at startup. Both are
back.

## 2.3.0, 2 September 2026

Both from Brian Hartgen.

### Music beds start exactly where the file does

A bed used to ease in over about a third of a second. If you cue a bed on its
first beat, that is the beat it ate.

Beds no longer fade in at all. Stopping one still fades, because a bed cut dead
mid phrase is a more obvious mistake. Both fades are in Audio settings if you
want the old behaviour.

### A button tells you what you changed

Assign a file to an empty bed and the button used to go on saying "Empty" until
you tabbed away and came back. Turn looping off and it still said "loops".
Every edit behaved like this. It does not any more.

When a sound starts or stops on the button you are standing on, the label still
waits until you move off it. Rewriting it there restarts your screen reader mid
sentence, on air.

## 2.2.1, 30 August 2026

Checking for updates now answers in a window. Before, the "you are up to date"
reply was spoken and nothing else, so with the app's speech turned down it
appeared to do nothing at all.

The answer sits in a read only box you can arrow back through, it names the
program, and release notes can be read properly before you decide.

## 2.2.0, 30 August 2026

All from David Goldfield and Brian Hartgen, who wrote in the same morning.

### The function key row makes sense

`F2` renames, because that is what F2 does in every other Windows program. The
volume keys moved down one: `F3` and `F4` for sounds, `F5` and `F6` for beds.

No number key moved.

### Ctrl+F finds things

`Ctrl+F` is the key everyone reaches for. `Ctrl+E` still works and always will.
A key you have already learned does not get taken away to tidy up a menu.

### Alt on its own is a modifier

Assigning `Alt+A` as a global hotkey was impossible: the dialog handed Alt plus
a letter to its own buttons instead of capturing it. It captures it now.

`Alt+F4` is the one combination it will not take. That closes a window in every
Windows program.

### Properties, on Alt+Enter

One dialog with everything about a sound in it: name, level, whether a bed
loops, and both hotkeys. Cancel really does leave the board alone.

The right-click menu offers the global hotkey too, and reads out its current
value.

### The app talks less, if you want

Audio settings has a Spoken feedback setting with three levels: everything,
only what you cannot hear or read for yourself, or nothing at all.

The bank hint is spoken once per bank per session rather than on every tab
change. Your screen reader already says "Dialog Drops, tab selected".

## 2.1.2, 30 August 2026

Both from Brian Hartgen.

### Send a bank to its own output

Audio settings has an output for each of the four banks. Set Music Beds to one
sound card and Dialog Drops to another and you can bring each up on its own
channel of a physical mixer.

Ducking still works across outputs. A drop on one card ducks a bed on another.

Banks sharing an output share one audio stream, so the ordinary case costs
nothing.

### Turn off the announcement when a sound starts

Audio settings, Say the name when a sound starts or stops. For when you built
the board and can hear the sound perfectly well. Anything you cannot hear, such
as a missing file, always speaks.

## 2.1.1, 29 August 2026

Opening the app when it is already running brings the copy you have back to the
front, instead of starting a second one that fights it for the audio device.

## 2.1.0, 29 August 2026

### Global hotkeys

Assign a key to any sound and it fires while another program has focus. You can
be in your DAW, your browser or on a call and still hit the sting.

Sounds menu, Assign a global hotkey, on any slot in any bank. It needs at least
one modifier such as Ctrl or Alt. A key on its own would be taken away from
every other program on your machine, so the app refuses it.

`Ctrl+G` arms and disarms the whole set, and disarming hands the keys back.

None of the keys you already know changed.

### It updates itself

2.0.0 shipped with no way to send you a new version. From here it tells you
when there is one and asks before it does anything.

## 2.0.0, 26 August 2026

The first release. A rebuild of The Tony Gebhard Show Soundboard, whose source
was lost.

Eighty sounds on the number row across four banks, two independent volumes,
music beds that duck themselves, and forty sounds included so it makes a noise
the first time you open it.

The keyboard map is the one from the old app, recovered from the only surviving
copy, because years of muscle memory should not be thrown away.

Free, and staying free.
