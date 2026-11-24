# Major release notes, draft

Plain sentences for the changelog and the release post, added by each step.

## Opening boards and settings

- Opening a board now brings all of it with it: its sound cards, the card you
  listen on, its sources, its global hotkeys, its bank names, its hidden pads
  and its streaming choices. Before, only the pads changed and everything
  else stayed as the last board left it.
- A send that is running is never stopped by opening another board, so a call
  carried by it does not drop, and the Loaded line says it carries on. With no
  send running, a board whose send is on starts it, as it does when Drop Deck
  starts, and says so.
- Muting and soloing a source survive opening another board and File, New.
  File, New also keeps "Put the microphone on air" as it was.
- The Loaded line now says, without being cut off, which sound cards the board
  names that are not plugged in, which sources would not open, and whether the
  board turned global hotkeys on. Two pads sharing one global hotkey are said
  as the board's own doing, not blamed on another program, and none of this
  puts up a box.
- A source with no input chosen no longer opens your default microphone when
  its board opens. Drop Deck says it has no input chosen instead.
- A folder pad works the moment its board is opened. It used to say it was an
  empty folder until Preferences had been opened once (feedback 42).
- File, New, Load the demo pack and importing an old bank keep the sound
  cards, the microphone, the send and the sources you were already using, so
  the show does not jump to another card or drop a call.
- While you are on air, opening another board is refused with "Come off air
  first". A recording or a send carries on as you change boards.
- Rename in Source control works again, with F2 and with the button.
- Every pad and every key works while the cue sheet (Ctrl+Shift+C) has focus.
  Escape there only closes the cue sheet.
- Turning "Put the microphone on air" on or off in Preferences takes effect
  straight away, in the middle of a show.
- If you switch to another microphone in Preferences while yours is on and the
  new one will not open, Drop Deck now says so and Microphone on is unticked.
- While you are on air, Preferences will not change where Ctrl+B goes or load
  a saved station. It says "Come off air first" instead, the same as the On
  air menu.
- Cancel in Preferences now puts back everything a saved station changed,
  including the screen, the camera corner, the words on the picture and the
  colours. A station saved or forgotten before Cancel shows on the On air
  menu at once.
- A saved station keeps its own on screen words and colours. Editing the board
  afterwards no longer changes the saved station too.
- Changing the picture in Preferences while you are live or recording changes
  the picture going out straight away. A new size or quality is said to start
  the next time you go live or record.
- Turning sound preview on or off is now saved with the board.
- A bank four hotkey can no longer take one of Drop Deck's own keys, such as
  Ctrl+S or F5, a menu's Alt letter, F10, Shift+F10, the Applications key or
  Ctrl+Page Up and Page Down. The hotkey window says what that key already
  does.
- The cue sheet keeps up when another board is opened while it is open.
- Test the cable is refused while the send is running, because the tone would
  go down the cable to the call.
- A board changed on disk is never reloaded underneath an open Preferences
  window, so OK cannot write the old window's settings over it.
- Buttons that take a moment, such as Check the shot and Test the cable, no
  longer throw you onto the next button while they work. Pressing one again
  says it is still working.
- Look through the camera now, in Preferences, works again.
- If the board cannot be saved in the middle of a show, Drop Deck says so once
  instead of putting a box in front of the pads.

## Security and privacy

- A board can only use a voice plugin that is installed on your computer. A
  board asking for one from anywhere else, such as a network share, opens
  with the voice running without it, and Drop Deck says so.
- A board can no longer send your stream key to a server of its own. YouTube
  and Facebook always go to their own address, whatever the board says, and
  each stream key now goes only to the server it was saved for. A board
  pointing somewhere else is stopped before it goes live, with a sentence
  saying why, and the go live summary names the server whenever it is not
  the platform's own.
- Stream keys saved by 3.10.1 keep working, custom servers included. The
  first time this version starts, each key is tied to the server your own
  board names for it, with nothing to retype. A key your board does not name
  still works with YouTube, Facebook and Restream; for any other server, type
  it again once on the Video streaming page.
- Your Icecast or SHOUTcast password now lives in Windows Credential Manager,
  one per station, like the stream key, and leaves the board file. If Windows
  will not keep it, it stays in the board file and Drop Deck says so once.
- Exporting a board with its sounds leaves out your passwords, any stream
  key, your recordings folder and the folders you last used. Your own
  picture goes with it, beside the sounds, and the voice plugin goes by its
  name alone: the computer that opens the board uses its own copy of that
  plugin. The confirmation says "Passwords and your own folders were left
  out."
- The Ask box in Check my shot never sends your screen unless you have
  agreed to it in that check. Before then it says "Check the shot first".
- Uninstalling removes Drop Deck and nothing else from its folder, and the
  installer no longer asks where to put it, so it cannot be pointed at a
  folder such as Documents.
- Recording to a NAS or other network folder works when you chose that
  folder in Preferences on this computer, and the one your board already
  records to keeps working after the update. A board from somebody else
  naming a network or web folder records to your usual folder instead, and
  Drop Deck says so once. Sounds kept on a network share work exactly as
  before.
- Where listeners connect has to be a web address starting with http or
  https.
- Global hotkeys can no longer be Shift plus a letter or symbol, or Ctrl plus
  A, C, V, X, Z, Y, S, F, N, O, P or W, because every other program needs
  those keys. A board that already has one keeps it on the pad, but it is not
  used, and Drop Deck says which and why.
- If Windows will not keep your AI provider key, Drop Deck now says so
  instead of dropping it without a word.

## Sound

## Speech and keys

## Where things are

## Help and the guide
