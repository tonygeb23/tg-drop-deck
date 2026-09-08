# TG Drop Deck

An accessible soundboard and playout desk for podcasts, radio and live shows.
Eighty sounds a keypress away, a playlist that crossfades, a processed
microphone, and a stream to your own station. Keyboard first, screen reader
first.

Free, MIT licensed. Windows, and a native Mac copy for VoiceOver in `mac/`,
both reading the same board file.

- **Download:** [tgstudios.app/drop-deck](https://tgstudios.app/drop-deck/)
- **The manual:** [tgstudios.app/drop-deck-guide](https://tgstudios.app/drop-deck-guide/)
  covers every feature and every key. This page is the short version.
- **The Mac manual:** [tgstudios.app/drop-deck-guide-mac](https://tgstudios.app/drop-deck-guide-mac/),
  where `Ctrl` below is `Command` and `Alt+Ctrl` is `Option+Command`.

## Why

Every other soundboard assumes you can see a grid and hit it with a mouse.
This one assumes you cannot, and that turns out to be faster for everybody:
your hand never leaves the number row.

## The keyboard

Four banks of twenty, all on the number row.

| Keys | What fires |
|---|---|
| `1`-`0` | Sound effects 1 to 10 |
| `Shift+1`-`0` | Sound effects 11 to 20 |
| `Ctrl+1`-`0` | Dialog drops 1 to 10 |
| `Ctrl+Shift+1`-`0` | Dialog drops 11 to 20 |
| `Alt+Ctrl+1`-`0` | Music beds 1 to 10, press again to stop |
| `Alt+Ctrl+Shift+1`-`0` | Music beds 11 to 20 |

Bank 4 takes hotkeys of your own instead of fixed keys. `Ctrl+Tab` moves
between banks.

Three faders, because a bed, a drop and a song should never fight over one:
`F3`/`F4` for sounds, `F5`/`F6` for beds, `F7`/`F8` for the playlist.

| | |
|---|---|
| `Escape` | Stop everything. Two presses by default, one to four in Preferences |
| `Ctrl+Space` | Stop only the sound you started last, and again for the one before |
| `Ctrl+F` | Search every bank by name |
| `Ctrl+L` | What is playing right now |
| `Ctrl+B` | Go live, and come off air |
| `Alt+Shift+V` | Change what the stream is showing, on air or off |
| `Ctrl+R` | Start and stop recording |
| `Ctrl+M` | Microphone on and off |
| `Ctrl+D` | Ducking on or off |
| `Alt+Enter` | Properties: name, level and both hotkeys in one place |
| `F1` | Every shortcut, in a window you can read |

## What it does

**Eighty slots, four banks.** Effects and drops overlap freely and never cut
each other off. Beds loop, toggle on the same key, and only one plays at a
time. Land on any slot and press `Space`: empty opens a file browser, full
plays it. Point a slot at a folder instead of a file and every press plays a
different sound from it, never the same one twice running, which is the six
jingles that all mean "down the chart" on one key. Files are referenced where
they sit and never copied, so **Relink missing sounds** repoints a whole board
when your library moves.

**A playlist beside the soundboard.** `Ctrl+Shift+P` to it, `Ctrl+Shift+S`
back. Paste in a whole album, and each track hands over to the next before it
ends. That overlap is the crossfade, and it is a box under the running order
rather than a setting to go hunting for. Artist and title come from each
file's own tags, in columns a screen reader reads one at a time, and every
track has a tick. A beep before a track ends is the countdown clock a sighted
presenter watches; it plays where you hear yourself, so it stays out of the
show. Save a running order as M3U and open it anywhere.

**Streaming to your own station.** `Ctrl+B` sends the programme to Icecast, a
Liquidsoap harbor or SHOUTcast, in MP3 or Ogg Opus. Sounds, beds, playlist and
microphone go out; your preview and your end of track beep do not, because
those are yours. Encoding and the network run on their own thread, so a bad
connection costs the stream and never your own audio, and it reconnects by
itself. `F7` and `F8` become a monitor fader on air, so you can turn the music
down to hear your screen reader while listeners still get it at full level.
`Ctrl+Shift+A` says who is listening, and handles the awkward case that is
really the common one: when the server you send to is not the server people
listen on.

**And to YouTube, Facebook or Restream.** Those will not take sound on its own, so something has to be on the screen: a card with your station name and whatever is playing, which costs about 64 kbps, your own artwork, a camera, your screen, or your screen with the camera small in the corner. `Alt+Shift+V` changes it while you are on air without dropping the connection. `Ctrl+Shift+F` says what the camera can see, in shot or not, centred, close enough, lit, because you cannot look at a preview window.

**`Ctrl+B` says what it is about to send** and waits for Enter: where the show is going, what it is sending, what is on the screen, and whether your microphone is on the air. It also says what would spoil the broadcast without stopping it, which is the half worth having. Turn the question off if you would rather it did not ask.

Nothing goes out until you press `Ctrl+B`.

**A microphone with a real chain.** A gate, a high pass filter, a three band
equaliser, a compressor and a true peak limiter, in that order, plus VST3
effects. Every parameter is a row in a list, in plain words with real units,
read out as you change it, so a plugin whose own window no screen reader can
read becomes a list any screen reader can. Beds and the playlist duck while
the microphone is open and come back when you close it, and you can hear
yourself through an output of its own.

Nothing opens your microphone but you pressing `Ctrl+M`.

**Recording.** `Ctrl+R`. The same mix that goes on air, to Documents, in WAV,
MP3, AAC or Ogg Opus. It does not need you to be on air, it does not fight
with the stream, and closing the app finishes the file first so a recording
always opens.

**Other audio on the air with you.** `Alt+Shift+S`. Anything Windows offers as
an input: a co-host's microphone, a hardware mixer. Or one single program,
captured straight from it with no cable in the middle and nothing to install,
the same thing OBS calls Application Audio Capture (Windows 10 build 20348 or
later). **Your screen reader is in that list**, NVDA, JAWS, Narrator and the
rest, so a demonstration or a tutorial goes out the way any other program
does. `Alt+Ctrl+Shift+S` mutes, solos, renames or removes any of them mid
show, from a list you drive with the arrow keys.

**Ducking.** Fire an effect or a drop and the beds drop about nine decibels
and slide back up when it finishes. That is the thing radio does that makes a
show sound produced rather than assembled.

## The demo pack

Forty pieces of audio load the first time you run it: twenty sound effects in
bank 1 and twenty looping beds in bank 3, so the app makes a noise the moment
you open it. They are generated by ElevenLabs through
`tools/make_demo_pack.py`, not recorded and not taken from a commercial sound
library. The beds are trimmed to an exact loop and crossfaded so they run
without a click, and every effect is normalised so nothing clips when two fire
at once.

**File → New board** empties all eighty slots. **File → Load the demo pack**
brings it back.

## Running it

```bash
pip install -r requirements.txt
python main.py
```

Python 3.11 or newer. `accessible_output2` is optional and worth having: it
adds speech and braille for the things a screen reader cannot know on its own,
like a bed starting or a fader moving.

Your board lives in `%APPDATA%\TG Studios\TG Drop Deck\board.json` and saves
itself as you change it and when you quit.

## Tests

Each file is a script, so run them individually or all at once:

```bash
for f in tests/test_*.py; do python "$f" || echo "FAILED $f"; done
```

Twenty eight files, and they run with no sound card: the engine tests render
the mixer by hand and check the samples, including that ducking really ducks
by the amount it claims.

## Licence

MIT. See `LICENSE`.
