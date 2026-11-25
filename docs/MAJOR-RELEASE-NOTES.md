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
  File, New also keeps "Send my microphone" as it was.
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
- Turning "Send my microphone" on or off in Preferences takes effect
  straight away, in the middle of a show. So does loading a saved station
  that turns it on or off, and the station's line then says "Your
  microphone goes out with this station" or "Your microphone is not sent
  with this station". Loading one inside Preferences says it too.
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
- Stream keys saved by 3.10.1 keep working, custom servers included, with
  nothing to retype. The first time this version starts, each key is tied
  to the server the board you have open names for it. For YouTube and
  Facebook that is their own secure address, and that is all. For any other
  server, the first Ctrl+B shows where the key will go, even if you have
  turned that question off, and Go live there confirms it for good.
- A key your board does not name still works with YouTube's and Facebook's
  own secure addresses. For any other server, Restream included, type it
  again once on the Video streaming page.
- Forgetting a saved station no longer deletes the stream key of the station
  you are using, so a show on the air keeps its key.
- Exporting a board with its sounds leaves out your passwords, any stream
  key, your recordings folder and the folders you last used. Your own
  picture goes with it, beside the sounds, and the voice plugin goes by its
  name alone: the computer that opens the board uses its own copy of that
  plugin. The confirmation says "Passwords and your own folders were left
  out."
- The Ask box in Check my shot never sends your screen unless you have
  agreed to it in that check. Before then it says "Check the shot first".
- Uninstalling removes Drop Deck and nothing else from its folder, on a copy
  updated from 3.10.1 too, and the installer no longer asks where to put
  it, so it cannot be pointed at a folder such as Documents.
- Recording to a NAS or other network folder works when you chose that
  folder in Preferences on this computer, and the one your board already
  records to keeps working after the update. When a board names a network
  or web folder you did not choose here, this computer records to your usual
  folder instead and says so once for that folder. The board keeps its own
  folder, so a board shared with another computer through Dropbox still
  records to that computer's NAS. Sounds kept on a network share work
  exactly as before.
- Where listeners connect has to be a web address starting with http or
  https, and a page that tries to send Drop Deck anywhere else is not
  followed. Addresses on your own network still work.
- Global hotkeys can no longer be any of these, because every other program
  needs them: Shift plus a letter or symbol; Ctrl plus A, C, V, X, Z, Y, S,
  F, N, O, P or W; Tab, Insert, Delete, Backspace, the arrows, Home, End,
  Page Up or Page Down with one modifier; Alt+F4, Alt+Tab, Ctrl+Tab and
  Alt+Space; and Ctrl+Alt plus a letter, digit or symbol, which Windows
  reads as AltGr and uses for characters such as @ and the euro sign. A
  combination with two keys besides the modifiers is refused too, and so is
  a symbol your keyboard types only with Shift. A board that already has one
  keeps it on the pad, but it is not used, and Drop Deck says which and why.
- If Windows will not keep your AI provider key, Drop Deck now says so
  instead of dropping it without a word.
- Going live to YouTube, Facebook or any rtmps server now checks that the
  server really is who it says it is before your stream key is sent. Before,
  anybody on the same network who could pretend to be YouTube could collect
  your key. If the check fails, nothing is sent, Drop Deck does not go on
  air, and it says "the server's certificate could not be checked, so
  nothing was sent and your stream key never left this machine".
- Check my stream key and Ctrl+B now use the same check, so a key that
  passes is one that will go out, and a server whose certificate fails is
  named as the problem rather than your key.
- Secure connections trust the root certificates Windows has and also the
  list Firefox uses, so a computer whose Windows has not yet fetched
  YouTube's or Facebook's root is not refused at the top of a show. Update
  checks use the same list.
- A video server that takes the connection and then never answers, plain
  rtmp such as Restream included, can no longer freeze Drop Deck. It is
  given up on after ten seconds with "did not answer", and pressing Ctrl+B
  again while it is connecting stops it at once, even while the server's
  name is still being looked up.
- If part of Drop Deck's streaming is missing from your copy, going live says
  so once and asks you to reinstall, instead of blaming your network and
  trying again all night.

## Sound

- "System default" now plays through Windows' quick audio route, so a key on
  the default sound card sounds in about 22 milliseconds instead of about 180.
  If Windows will not open it that way, Drop Deck uses the older route and
  says so once. Your default microphone is opened the same way.
- A music bed started while your microphone is on now comes in already ducked.
  It used to start at full level and drop a moment later.
- Stop everything no longer clicks when "Fade out when stopping" is off. It
  stops in five milliseconds, the same as stopping one sound.
- With "What I listen on" set to another card, auditioning a sound plays there,
  not out of your main output, so nobody listening to your main output hears
  you choosing sounds.
- A microphone plugged into one input of a two input interface now comes
  through at its full level, without the other input's hiss. Drop Deck takes
  the side with the voice on it after about a second of the other being nearly
  silent, and the moment the quiet side carries sound again, a second person
  starting to talk, both come back within 50 milliseconds. Sources still mix
  both sides. In "Which channel the voice is on" this is "Both, the side with
  a voice on it", and a board that had "Both, mixed together" gets it.
- New: "Both, always mixed", in the same place, for two people on one
  interface, one on each input. Neither side is ever left out, so a voice no
  longer jumps 6 dB about a second into its turn. "Left only" and "Right
  only" are as they were.
- Your microphone processing stays right when your sound card runs at a
  different rate, such as 96 kHz. The low cut used to sit an octave too high
  and make the voice thin.
- Sources follow a change of sound card straight away, instead of playing at
  the wrong speed until they were restarted.
- When the card you listen on runs at a different rate from your main output,
  your microphone, your sources and the send you are checking now sound at the
  right pitch and without crackles.
- Your microphone and your sources no longer drift late or tick over a long
  show when two sound cards run at slightly different speeds. Drop Deck keeps
  the delay steady and makes any correction too small to hear. A sound card
  that is a few milliseconds late now and again is covered with a few
  milliseconds of what was just heard, rather than a gap.
- Hearing the send through Ctrl+Shift+H no longer has small gaps in it.
- Drop Deck refuses a setup that would feed your show back into itself: a send
  into a virtual cable while your microphone or a source listens to the other
  end of the same cable. It knows VB-Audio's CABLE and CABLE A to D,
  VoiceMeeter, Virtual Audio Cable, and a Loopback or Stereo Mix input on the
  card you send into, and it says which input to change. A real sound card's
  own microphone is never refused: sending into a headset's earphones while a
  guest talks into the same headset works.
- New, and off unless you turn it on: "Duck further while I am talking" on the
  Sounds and beds page of Preferences. The music still ducks when your
  microphone is on, as before, and goes a little further down while you are
  actually speaking, by the amount you set in "By how much further, in
  decibels".
- New: On air sound, a page of its own in Preferences next to Voice, turned
  on and off with "Process the on air sound". What goes to your stream, your
  recordings and the send is evened out, so a loud song and a quiet one
  arrive closer together, and nothing is ever louder than the ceiling you
  set, minus 2 dBFS to start with, measured between the samples as well.
  Firm starts at minus 3, because music limited hard all the time can still
  go a little over, and choosing Firm or going back says the ceiling it
  moved to. It never changes what you hear yourself, and it holds still only
  while the music really is ducked under your microphone or a drop; with
  ducking off it keeps evening out. "Even out the music" can be Off, Gentle
  or Firm. A glitched file can no longer silence the stream.
- Alt+Shift+P bypasses the on air sound for a moment, and puts it back, so
  you can compare. Drop Deck says "On air sound bypassed, in what goes out"
  and "On air sound back on", and fades between the two in a twentieth of a
  second. It changes only what goes out, never what you hear, so to hear the
  difference yourself, send the show to another program (Alt+Shift+O) and
  listen to what is being sent with Ctrl+Shift+H; at the full speech level
  the first compare of a session says so. It is not saved, so a show never
  starts with it off by accident. If a pad in bank 4 already has
  Alt+Shift+P, the pad keeps it: the compare is then on the On air menu
  only, and the menu and the startup line say so.
- New: "Match the loudness of songs and sounds, for you and on air", on the
  same page. Each song and sound is measured once, in the background, and
  played at a matching level, in what you hear as well as what goes out. A
  file you change under the same name is measured again. A level you set on
  a sound or a song yourself always wins, 0 dB included, which is how you
  keep one sound exactly as recorded. Quiet files are only turned up as far
  as they can go without distorting.
- File, New and the demo pack turn On air sound and loudness matching on,
  and so does a first start. A board you already have keeps the sound it had
  until you turn them on, and the first time this version starts, Drop Deck
  says so once, after its startup line: "New in this version: On air sound,
  on its own page in Preferences, is off on this board until you turn it on.
  Put the microphone on air is now Send my microphone, on the Microphone
  page".
- Drop Deck now says at startup when a sound card your board uses would not
  open, or is not plugged in, instead of quietly playing through the Windows
  default.
- Turning on "Send my microphone" while you are sending, with your
  microphone set to the other end of the cable you are sending into, is
  refused and Drop Deck says why, the same as Ctrl+M. Loading a saved
  station that would turn it on is refused the same way.

## Speech and keys

- Ctrl+M and Alt+Shift+M now say "Mic on" and "Mic off" (feedback 48). The
  microphone is named only the first time, when it is a different one, or
  when it came in another way, and "music ducked" is said only when ducking
  is on.
- If your microphone opens while you stream, record or send and it does not
  reach any of them, Ctrl+M says so first, and why: "Mic on, but nobody else
  hears it: Send my microphone is off", or "you are muted in Source control",
  or "a source is soloed", with "Music ducked" after it when ducking is on.
- After a dropped connection comes back, Drop Deck says "Back on air"
  instead of the whole going live line and the server address again. The
  first time it says "On air" with your station or platform name.
- Delete on the playlist track that is playing no longer stops the music at
  once. The first Delete says "is on the air. Press Delete again to remove it
  and stop the music", and a second Delete on the same track within five
  seconds does that, with no window in front of the pads. Moving to another
  track, or waiting, starts again. Deleting any other track is still
  instant. Both are said even at the middle speech level.
- Choosing your radio station in Streaming location now says Alt+Shift+B
  goes live there, which is what really happens. If you press Ctrl+B with
  no video set up and a radio station that is, Drop Deck tells you to press
  Alt+Shift+B for your radio station.
- The Stop everything button says how many presses of Escape your board
  really needs, twice unless you changed it, and changes when you change it
  in Preferences or open another board.
- With "F7 and F8 change what I hear, not what goes out" on, F7 and F8 now
  say "what you hear only" while you record or send, not only while you
  stream.
- Alt+Enter on a playlist track opens its crossfade, as the guide says.
- Assign a global hotkey says "Move to a sound button first" when you are
  not on one, instead of nothing.
- Answers such as Ctrl+L, and the names of sounds you start from a menu, are
  no longer cut off by the screen reader reading where the menu left you.
- Swapping between the soundboard and the playlist says only where you are,
  "Playlist" or "Soundboard" and the bank. The playlist summary is still
  there when you press the key for the view you are already in.
- Search sounds says how many match once you stop typing, rather than after
  every letter, and says nothing at the speech level None. The hotkey,
  Properties and drops library windows follow the speech level too.
- No two items on one menu share a letter any more. While you are live, the
  On air menu reads "Go off air from video", letter G, or "Go off air from
  radio", letter D: the same letter that put you on air. Open the recordings
  folder keeps F. Stopping the send is I, the same letter as starting it.
- On a playlist track's menu, Move to the top is now O and Stop the playlist
  Y. Insert a random drop keeps the R it had in 3.10.1, and Remove from the
  running order is now M. On a bed's menu, Loop this bed is O. In Submit
  feedback, What will be sent is W; in Check my shot, Close is L; in the
  colour picker, Cancel is A.
- A letter that is one item's alone acts the moment you press it, without
  Enter, so these now act at once. While you are live, F opens the
  recordings folder and G or D takes you off air. While you are sending, D
  goes live on your radio station and I stops the send. On a track's menu, R
  inserts a random drop and M removes the track. In Submit feedback, Alt+S
  submits.
- The microphone item on the On air menu is now called "Microphone", ticked
  while it is on, so it no longer reads as "Microphone on, not checked".
  Ctrl+M and the M are unchanged.
- Nothing says Ctrl+B about your radio station any more, because Ctrl+B is
  always your video platform and Alt+Shift+B your radio station. Ctrl+Shift+B
  off air says "Off air. Alt+Shift+B goes live to" your station, and Ctrl+B
  only for your video platform.
- Loading a saved station from the On air menu says the key for where that
  station goes, and if you are live it names the key that takes you off air.
- Ctrl+Shift+W no longer says Ctrl+B goes to your radio station "until you
  switch Ctrl+B over". It says your radio station, on Alt+Shift+B, takes no
  picture, and that the picture goes out with Ctrl+B to your video platform
  and into the file with Ctrl+Shift+R.
- The status bar names Alt+Shift+B beside Off air or ON AIR when your show
  goes to your radio station, and Ctrl+B when it goes to your video platform.
- The box in Preferences that asks before going live is now "Say what is
  going out before going live", letter A as before, because it covers
  Alt+Shift+B as well as Ctrl+B, which it always did. The go live window's
  "Do not ask again" says so in its tooltip.
- What Drop Deck says as Preferences closes is no longer cut off by the
  screen reader reading the main window coming back: it waits for that
  reading and follows it.
- The Stop everything button is no longer read out again every time
  Preferences closes or a board opens with the same number of Escapes.

## Where things are

- The cue sheet is on the Playlist menu now, as "Cue sheet, what is coming
  up", letter T, with its key, Ctrl+Shift+C.
- "Add songs to the end" on the Playlist menu has a key: Alt+Shift+A
  (feedback 51). If a pad in bank 4 already has Alt+Shift+A, the pad keeps
  it, the same as Alt+Shift+P: Add songs is then on the menu only, and the
  menu says which pad has the key, such as "Alt+Shift+A plays Applause". A
  pad emptied with its key still on it is named by its bank and number,
  "Alt+Shift+A is kept by Misc 3, which is empty", and the startup line says
  to clear that pad's hotkey to free the key. A pad name with an ampersand
  in it, such as Q&A, now reads as it is written there.
- "Put the microphone on air" has moved from Audio streaming to the
  Microphone page, and is now called "Send my microphone to streams,
  recordings and other programs", because it decides all three. Its letter
  is still I, and a saved station still remembers it. Audio streaming says
  "Whether your microphone goes out is on the Microphone page" where the box
  used to be. On the go live window, Put it right on "Your microphone is not
  on the air" opens that page with that box ready to tick.
- "Hear yourself through", on the Microphone page, is now "What I listen
  on", because it also chooses where you hear the beep before a track ends,
  the sounds you audition and, on a card of its own, the whole show. Its
  letter is still O. The box under it is now "Hear my own voice there
  (headphones only)", letter H as before.
- The ducking box on Sounds and beds now says what it does: "Duck the music
  under sounds, drops and the microphone". Its letter is still D, and Ctrl+D
  is unchanged.
- The status bar starts with what matters most: whether your microphone is
  on, whether you are on air, recording or sending. The three volumes and
  ducking come after, so the state is no longer cut off or read last. And
  your screen reader now reads both parts of it whole, where a narrow window
  cut each one short with three dots.
- Ctrl+S on a board that has never had a name, one from File, New, the demo
  pack, an import or a first start, now asks where to save it, as Save board
  as does, and still does after Drop Deck is restarted. It used to save "New
  board.json" in the settings folder and say so, dot json and all. Save board
  as starts in the folder you last saved a board in, or in Documents, with a
  name ready in the box, and then says "Saved as" the name, "in" the folder,
  with no dot json. A board you have named or opened saves where it is, as
  before.
- With a setting off, the letters of the boxes that depend on it, such as
  Even out the music while On air sound is off, no longer jump to whatever
  box comes next.
- New: "Send song titles as", on the Audio streaming page under "Send the
  track title" (feedback 39). Title by Artist, as before, Artist - Title, or
  Artist - Title - Album, each read out with an example. Anything a song's
  file does not say, such as its album, is left out with no hyphen left
  hanging. The album is read with the artist and the title, once, when a
  song goes in, and songs already in a running order have it read once in
  the background.
- With "Send the track title" off, going live no longer sends your station
  the title of the song that is playing at that moment.

## Help and the guide
