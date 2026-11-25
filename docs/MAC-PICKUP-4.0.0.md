# Mac pickup for Drop Deck for Windows 4.0.0

What the Windows major release of 24 November 2026 changed that the Mac copy
probably needs. Written on Windows, which does not touch `mac/`: every line
here is for whoever next works on the Mac, to judge against the Mac's own
code. The Windows detail of each item is in `docs/MAJOR-RELEASE-NOTES.md`.

## First: the board file, because Windows and the Mac share it

A board saved on one copy and opened on the other must keep what the first
one wrote. These are the fields 4.0.0 added or changed.

- **`mic_channel`.** Windows now has four values. `mix` is the plain
  average, the Mac's own meaning, and what an existing board keeps. `voice`
  is new: it picks the side with a voice on it, and is the default for the
  demo and a first start. The Mac must read `voice` and write it back
  rather than turning it into `mix`.
- **`stream_title_format`.** Windows reads the Mac's two keys and adds a
  third, `artist_title_album`. The Mac treats an unknown value as its
  default and writes `title_by_artist` back over it, so a board shared
  through Dropbox loses the choice. Keep unknown values, or learn the third.
- **`never_named`.** True only for a board Drop Deck made and nobody has
  named yet, kept in the settings folder. Windows honours it only for a file
  in its own settings folder. A Mac Save As must not copy `true` into the
  named file.
- **`trim_set`.** A trim the user set wins over loudness matching, 0 dB
  included. A board from before it reads any trim but 0 as set.
- **Loudness fields** on pads and tracks: `loudness`, `peak_db`,
  `loudness_checked` and `loudness_stamp` (size and modification time).
  Numbers without a stamp are measured again. Keep them if the Mac does not
  use them.
- **`album`** on tracks, always text.
- **On air sound fields:** `onair_on`, `onair_even` (off, gentle, firm) and
  `onair_ceiling_db`. Firm's default ceiling is -3, the others -2.
- **`match_loudness`**, `talk_duck` and `talk_duck_db`.

## Sound

- Duck reset: a bed started under an open microphone comes in already ducked.
- Preview routing: auditioning plays on the card you listen on.
- Stop everything ramps over 5 ms with fading off, so it never clicks.
- Two input microphone: the `voice` channel, its quick rejoin when a second
  person talks, and `mix` staying the plain average.
- The microphone chain follows the card's rate (a 96 kHz card made the low
  cut an octave high).
- The send's loop guard goes by the cable's own name, never by the card a
  headset shares, and it also holds for a station loaded inside Preferences.
- The monitor resampler, the ring that covers a short read with a repeat,
  and duck further while talking.
- On air sound: the leveller holds only while the music is really ducked,
  the ceiling is aimed at the true peak, every block is made finite first,
  Alt+Shift+P bypasses it with a 50 ms crossfade and yields to a pad.
- Loudness matching, measured once in the background, tied to the file's
  size and time, cut only from numbers not yet checked.
- Startup says when a card the board uses would not open.

## Speech and keys

- Ctrl+M says "Mic on" and "Mic off", the device only when it is news, and
  "Mic on, but nobody else hears it" first, with the reason, when a mute, a
  solo or Send my microphone keeps it out. The go live summary and the
  status bar say the same.
- Back on air after a reconnect.
- Delete on the track on air takes a second press within ten seconds,
  never a box: "Name is on air. Delete again removes it and stops the
  music".
- The radio hint in the preflight stop, F7 and F8 saying what you hear
  only for a recording or the send, Alt+Enter on a row, the global hotkey
  sentence off a pad, the search count after typing stops.
- Refused global hotkeys said grouped, one sentence per reason.
- Menu letters: no two items on one level share one, and the letters a
  user learned keep their first item. Menus say Delete, not Del.
- The first start note, once a machine.

## Where things are

- Send my microphone to streams, recordings and other programs, on the
  Microphone page. What I listen on. Hear my own voice there. Duck the music
  under sounds, drops and the microphone. Say what is going out before going
  live. Process the on air sound.
- The cue sheet on the Playlist menu, and Add songs to the end on a key that
  yields to a pad already holding it.
- The status bar: state first, read whole.
- Command S on a board never named asks where to save it.
- Send song titles as, with the album read alongside the other tags.

## Security, from the earlier steps

- A stream key goes only to the server it was saved for; YouTube and
  Facebook always to their own address.
- rtmps checks the server's certificate before the key is sent.
- A board can load only an installed voice plugin.
- Exports leave out passwords, stream keys and the user's own folders.
- A board cannot make this machine record to a network folder it did not
  choose here.
- Where listeners connect must be an http or https address.
- The shot check's Ask box never sends a screen before a yes in that check.
- A video server that never answers is given up on after ten seconds.

## Tools

- Check whether `mac/check_guide.py` reaches outside the way the Windows one
  did: the credential store, the default output, the update check and every
  installed plugin. The Windows one stands all of them in now.
- The Mac guide: the Every key labels need headings, the chapter links need
  their names, and each feature above as the Mac gets it.
