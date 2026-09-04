# TG Drop Deck

An accessible soundboard for podcasts, radio and live shows. Eighty sounds a
keypress away, built keyboard-first for screen reader users.

Free, MIT licensed, and it ships with forty sounds so it makes a noise the
moment you open it.

## Why

Every soundboard assumes you can see a grid and hit it with a mouse. This one
assumes you cannot, and it turns out that makes it faster for everybody: your
hand never leaves the number row.

## The keyboard

The whole app is the number row and four modifiers.

| Keys | What fires |
|---|---|
| `1`-`0` | Sound effects 1 to 10 |
| `Shift+1`-`0` | Sound effects 11 to 20 |
| `Ctrl+1`-`0` | Dialog drops 1 to 10 |
| `Ctrl+Shift+1`-`0` | Dialog drops 11 to 20 |
| `Alt+Ctrl+1`-`0` | Music beds 1 to 10, press again to stop |
| `Alt+Ctrl+Shift+1`-`0` | Music beds 11 to 20 |
| `Ctrl+Tab` | Next bank |

Two volumes, because a bed and a drop should never fight over one fader.

| Keys | What moves |
|---|---|
| `F3` / `F4` | Sound volume, banks 1, 2 and 4 |
| `F5` / `F6` | Bed volume, bank 3 |

And the rest:

| Keys | |
|---|---|
| `Escape` | Stop everything, with a short fade |
| `Ctrl+F` | Search every bank by name, `Ctrl+E` still works |
| `Ctrl+L` | What is playing right now |
| `Ctrl+D` | Ducking on or off |
| `F2` | Rename the sound you are on |
| `Alt+Enter` | Properties: name, level and both hotkeys, in one place |
| `Del` | Clear the slot you are on |
| `Shift+Del` | Take the slot off the board altogether |
| `F1` | Every shortcut, in a window you can read |
| `Ctrl+B` | Go live to your streaming server, and come off air |
| `Ctrl+Shift+B` | What the stream is doing |
| `Ctrl+N` `Ctrl+O` `Ctrl+S` | New, open, save a board |
| `Ctrl+P` | Preferences: output, sounds, playlist, microphone, streaming, speech |

## The four banks

Twenty slots each, and you can rename any of them, `Ctrl+F2`, or the Banks
menu. The name saves with the board. Renaming changes the name and nothing
else: bank 3 is still the looping bank and bank 4 still takes your own hotkeys.

1. **Sound effects**, stings, hits, transitions. Fire and forget.
2. **Dialog drops**, your own clips. Catchphrases, station IDs, callers.
3. **Music beds**, loop by default. A bed starts exactly where the file does,
   so one cued on its first beat gives you that beat, and fades out when you
   stop it rather than cutting dead. Both fades are set in `Ctrl+P`.
4. **Miscellaneous**, no fixed keys. Right-click a button to give it a hotkey
   of your own.

Sounds in banks 1, 2 and 4 overlap freely and never cut each other off. A bed
toggles: the same key starts it and stops it.

## A playlist, next to the soundboard

`Ctrl+Shift+P` goes to it and `Ctrl+Shift+S` comes back. Paste songs in with
`Ctrl+V`, a whole album at once if you like, and each one hands over to the
next before it ends. That overlap is the crossfade, and it is a box under the
running order rather than a setting you have to go looking for.

The running order shows the artist and the title out of each file's own tags,
in columns a screen reader reads one at a time, and every track has a tick your
screen reader announces. Unticked stays in the list and is skipped. Drops go
between songs, one at a time or after every so many, and a **drops library** on
`Alt+D` puts one in at random.

`Ctrl+L` says what is on air and how much of it is left, and `Ctrl+Shift+L`
takes you to it. The playlist has its own fader on `F7` and `F8`.

Save a show as an M3U from the Playlist menu and open it again later, or in
any other player.

**A beep before a track ends**, on in Preferences, at however many seconds
you like. The countdown clock a sighted presenter watches. It plays where you
hear yourself, so it stays out of the show.

It plays `wav`, `mp3`, `m4a`, `flac`, `ogg`, `wma`, `aac`, `opus` and more, so
an iTunes or Apple Music library goes straight in.

## Streaming to your own station

`Ctrl+B` sends everything you can hear to an Icecast server, a Liquidsoap
harbor or SHOUTcast, in MP3 or Ogg Opus. Set it up under **On air, Set up
streaming**; **Test the connection** proves it works before the show rather
than during it.

It sends the program: sounds, beds, the playlist and the microphone. Not a
preview and not the end of track beep, because those are yours.

The microphone goes out whenever it is open, whether or not you are hearing
yourself. Those are different questions, and a presenter on speakers monitors
nothing and is still on air.

`F7` and `F8` become a monitor fader while you are on air: turn the playlist
down to hear your screen reader and your listeners still get it at full level.
The other faders change both, because a drop fired at half level was meant to
be at half level.

Encoding and the network run on their own thread, so a bad connection costs
the stream and never your own audio. It reconnects by itself, `Ctrl+Shift+B`
says what it is doing, and listeners see the artist and title from your
playlist.

Nothing goes out until you press `Ctrl+B`.

## A microphone

`Ctrl+M` opens and closes it; `Ctrl+Shift+M` sets it up. While it is open the
beds and the playlist duck out of the way, and they come back when you close
it. You can hear yourself through an output of its own, so monitoring sits in
your headphones and the show does not.

Nothing opens your microphone but you pressing `Ctrl+M`.

## Finding a sound by ear

The window that opens when you assign a sound has a **Play each sound as I
reach it** box on it, `Alt+P`. Every sound plays once as you arrow onto it and
stops when you move on, so you can find the right one by listening instead of
by reading forty file names.

**Browse with Windows** opens the ordinary Windows file window, and `Alt+P`
previews in there too, while Drop Deck is the program in front.

## Twenty slots, or fewer

A bank ships with twenty. **`Shift+Delete`** takes the one you are on off, and
removing one never moves the others: take slot 5 away and 6 is still on the 6
key. Nothing is lost, and Put a removed slot back brings it again. `Delete`
still just clears the sound.

## A folder on one key

**Sounds → Assign a folder** points a slot at a whole folder instead of one
file. Every press plays a different sound from it, never the same one twice
running, and the app says which one it picked.

That is for the six jingles that all mean "down the chart", one key, and you
do not care which of them goes out. Drop another file into the folder and it
joins in.

## Ducking

When you fire a sound effect or a drop, the music beds drop about nine decibels
and slide back up when it finishes. That is the thing radio does that makes a
show sound produced rather than assembled.

`Ctrl+D` turns it off. `Ctrl+P` sets how far it ducks.

## Output device

`Ctrl+P` picks where the sound goes, including a virtual cable, so you can
feed a stream or a recorder while you keep listening on your own speakers. The
device is remembered by name rather than by number, so unplugging something
else does not silently move your audio somewhere unexpected.

## The demo pack

Forty pieces of audio ship with the app: twenty sound effects in bank 1 and
twenty looping music beds in bank 3. They load automatically the first time you
run it.

**Everything in the demo pack was generated with AI**, ElevenLabs, via
`tools/make_demo_pack.py`. Nothing is recorded, sampled, or taken from a
commercial sound library, which is what makes it safe to give away with a free
app. The beds are trimmed to an exact loop and crossfaded so they run forever
without a click, and every effect is normalised so nothing clips when two fire
at once.

**File → New board** empties all eighty slots when you want to start from
scratch. **File → Load the demo pack** brings it back.

## Your own sounds

Land on any button and press `Space`. An empty slot opens a file browser; a
full one plays. Right-click, or press the Applications key, for rename, level,
looping, hotkey and clear.

WAV, MP3, M4A, FLAC, OGG, WMA and more all work. Files are referenced where
they sit, nothing is copied, so if you later move your sound library, **File → Relink
missing sounds** points a whole board at the new folder in one go.

Coming from The Tony Gebhard Show Soundboard? **File → Import an old soundboard
bank** reads those `.json` banks as they are.

## Running it

```bash
pip install -r requirements.txt
python main.py
```

Python 3.11 or newer. `accessible_output2` is optional but worth having on
Windows, it adds speech and braille for the things a screen reader cannot know
on its own, like a bed starting or the volume moving.

## Where things are saved

Your board lives in `%APPDATA%\TG Studios\TG Drop Deck\board.json` and saves
itself when you change something and when you quit.

## Tests

```bash
python tests/test_engine.py
python tests/test_board.py
python tests/test_audiopost.py
python tests/test_ui.py
```

The engine tests run with no sound card, they render the mixer by hand and
check the samples, including that ducking actually ducks by the amount it says.

## Licence

MIT. See `LICENSE`.
