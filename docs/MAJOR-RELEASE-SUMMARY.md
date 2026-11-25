# TG Drop Deck for Windows, the major release

VERSION, released DATE

A major release of Drop Deck for Windows. Your board, your sounds and your
settings are all kept when you update.

## Before your first show

- **On air sound is off on your board.** A board you already have keeps the
  sound it had until you turn it on: Preferences, On air sound, Process the
  on air sound. Drop Deck says so once, the first time it starts. File, New,
  the demo pack and a first start have it on.
- **Send my microphone has moved.** Put the microphone on air is now Send my
  microphone to streams, recordings and other programs, on the Microphone
  page of Preferences. Its letter is still I, and your setting is kept.
- **Some global hotkeys stop firing.** A global hotkey can no longer be a key
  every other program needs, such as Shift with a letter, Ctrl+C, Alt+Tab, or
  Ctrl+Alt with a letter, which Windows reads as AltGr. A pad that has one
  keeps it, but it no longer fires, and Drop Deck says which and why. A
  function key with Ctrl or Alt is the safest choice.
- **You may need to type a Restream or custom stream key once.** Each key is
  now tied to its server. YouTube and Facebook keys carry on. Any other key
  carries on if the board you open first after updating has its station, and
  the first Ctrl+B shows where it will go. If not, type it again on the Video
  streaming page.
- **Delete takes two presses on the track on air.** The first says the track
  is on air, and a second Delete within ten seconds removes it and stops the
  music. Any other track still goes at once.
- **One microphone on a two input interface?** Choose Both, the side with a
  voice on it, under Which channel the voice is on, for its full level
  without the other input's hiss. Your board keeps Both, always mixed, which
  is what Both, mixed together always did, so it sounds as it did until you
  choose.

## What moved

- **Ctrl+B is always your video platform, and Alt+Shift+B always your radio
  station.** Nothing tells you to switch Ctrl+B over any more, and the status
  bar names the key for where your show goes.
- New names that say what they do: Hear yourself through is **What I listen
  on**, with the box **Hear my own voice there (headphones only)**; Duck the
  music beds under sounds and drops is **Duck the music under sounds, drops
  and the microphone**; Say what is going out before Ctrl+B goes live is
  **Say what is going out before going live**; and Microphone on, on the On
  air menu, is **Microphone**, ticked while it is on.
- The cue sheet is on the Playlist menu, and Add songs to the end has a key,
  Alt+Shift+A. A pad that already had Alt+Shift+A or Alt+Shift+P keeps it.
- The status bar starts with what matters: your microphone, whether you are
  on air, recording or sending. With your microphone open and not going out,
  it says Mic ON, not going out.
- No two items on one menu share a letter, and a letter that is one item's
  alone acts at once. The guide lists the letters that changed. Menus say
  Delete, not Del.

## What is new

- **On air sound**, a page of its own in Preferences. What goes to your
  stream, your recordings and the send is evened out, so a loud song and a
  quiet one arrive closer together, and kept under the ceiling in Never louder
  than. With Even out the music on Gentle or Firm, ordinary music stays
  under it; with it Off, or with hard material such as noise, the loudest
  moments can still come out up to about a decibel over. It never
  changes what you hear yourself.
- **Quick compare, Alt+Shift+P**, bypasses the on air sound for a moment. To
  hear the difference, record a minute with Ctrl+R, or send the show with
  Alt+Shift+O and press Ctrl+Shift+H. While it is bypassed, the go live window
  warns "On air sound is bypassed. Alt+Shift+P puts it back", and
  Ctrl+Shift+B and the status bar say so too.
- **Match the loudness of songs and sounds**, for you and on air, each file
  measured once in the background. A level you set on a pad always wins.
- **Duck further while I am talking**: the music goes a little further down
  while you are actually speaking. Off unless you turn it on.
- **Send song titles as**: title by artist, or artist and title the other way
  round, with or without the album.
- **System default takes Windows' quick route** where Windows allows it, so a
  key on your default sound card sounds far sooner.
- **The go live window says when a mute or a solo keeps your microphone
  out**: "Microphone: NOT going out, you are muted in Source control", or "a
  source is soloed", where it used to say on the air.
- **The first Ctrl+S on a new board asks where to keep it.**
- **A send that would hear itself is refused**, with the input to change.

## What is safer

- A stream key goes only to the server it was saved for, and YouTube and
  Facebook always go to their own secure address, whatever a board file says.
- Going live to YouTube, Facebook or any rtmps server checks the server's
  certificate before your key is sent. If it fails, nothing is sent.
- A board can only use a voice plugin installed on your own computer.
- Exporting a board leaves out your passwords, any stream key and your own
  folders.
- A board you were sent cannot make you record to a network folder you did
  not choose on this computer.
- Where listeners connect has to be a web address.
- Check my shot's question box never sends your screen before you have said
  yes in that check.
- A video server that never answers can no longer freeze Drop Deck.
- Uninstalling removes Drop Deck and nothing else, and the installer no
  longer asks where to put it.

## What is fixed

- **Opening a board brings all of it with it**: its sound cards, the card you
  listen on, its sources, global hotkeys, bank names, hidden pads and
  streaming choices. A send or a recording carries on, and while you are on
  air, opening another board is refused.
- File, New, the demo pack and importing an old bank keep your sound cards,
  your microphone, the send and your sources.
- A music bed started while your microphone is on comes in already ducked.
- Your microphone processing stays right on a card running at another rate,
  such as 96 kHz.
- Your microphone, sources and the send you are checking keep the right
  pitch when the card you listen on runs at another rate, and no longer
  drift late over a long show.
- Hearing the send with Ctrl+Shift+H no longer has gaps.
- Auditioning a sound plays on What I listen on, not your main output.
- Drop Deck says at startup when a sound card your board uses is missing or
  would not open.

### Also fixed

- Rename in Source control works again, with F2 and the button.
- Every pad and key works while the cue sheet has focus.
- Send my microphone takes effect at once, mid show.
- A folder pad works as soon as its board opens.
- Stop everything no longer clicks with fading off.
- Look through the camera now, in Preferences, works again.
- Answers such as Ctrl+L are no longer cut off after a menu.
- Alt+Enter on a playlist track opens its crossfade.
- With Send the track title off, going live sends no title.
- Changing the picture while live or recording changes it at once.
- Cancel in Preferences puts back what a saved station changed.
- A board that cannot be saved mid show is said once, not put in a box.

**If you also use the Mac copy:** saving a board on the Mac before the Mac
catches up drops Both, the side with a voice on it, and the album title
format from that board.

The manual covers all of it, with every key: tgstudios.app/drop-deck-guide.

## For the update window

Drop Deck VERSION for Windows is a major release. On air sound, which is new,
evens out the music your listeners get. It is off on a board you already
have until you turn it on in Preferences, On air sound. Put the microphone
on air is now Send my microphone, on the Microphone page. Global hotkeys
every other program needs no longer fire. A Restream or custom stream key
may need typing again once. Delete on the track on air takes two presses.
One microphone on a two input interface? Choose Both, the side with a voice
on it. Your board and settings are kept.
