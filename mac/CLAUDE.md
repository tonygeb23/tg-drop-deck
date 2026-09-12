# TG Drop Deck for Mac, working notes

The Mac copy of TG Drop Deck. Native Swift and AppKit, VoiceOver first, no
runtime dependencies at all: no Python, no wxPython, nothing to install.

It lives inside the Windows product's own repository, at `mac/`, on purpose.
It is the same product on another platform, it reads and writes the same
`board.json`, and the version number is meant to stay in lockstep. A separate
repository would have let the two drift apart within a release.

Read [../CLAUDE.md](../CLAUDE.md) first. Every design rule in it still holds,
including the standing one about dashes. This file records only what is
different on a Mac, and why.

## Video, which arrived on 8 September 2026

**The Mac was deliberately a release behind, and then it was not.** Tony's
words on 8 September: the Mac gets video once Windows is proven stable, and
when it does it builds on what Windows established rather than inventing its
own shape. He took it off the shelf the same day, knowing Windows 3.5.2 had
shipped hours earlier. That is on the record in `docs/MAC-VIDEO-PLAN.md`
along with what the risk was and how it was mitigated.

Everything Windows gained between 3.4.0 and 3.5.2 is here, and the two copies
share a version number again.

**What Windows settled, and what the Mac therefore copied rather than
redesigned.** Every one of these was argued out with a measurement behind it:

- **One picture source at a time**, chosen from a card the app draws, an
  image, a camera, the screen, or the screen with the camera inset. No scenes,
  no layers. `Picture.swift` and `Screen.swift`.
- **Audio is the master clock and video is stamped against it.** Video
  timestamps count frames encoded against the audio sample counter, never a
  wall clock and never the camera's own timing. `VideoStream.swift`. Measured
  against the mock server: sound and picture finished 0 ms apart.
- **Anything that blocks belongs on its own thread, and the caller takes the
  last frame it finished.**
- **The screen fills the frame and the camera goes in a corner**, because a
  1920x1080 desktop rendered 640 wide is unreadable.
- **The pre-flight** is plain arithmetic over a settings value, so it is
  testable with nothing running. `Preflight.swift`.
- **Where Command B goes is a visible checked list**, not a hidden setting.

**What is genuinely different here, and it is less than expected.**

`RTMP.swift` and `FLV.swift` are the only new protocol work: a handshake, a
chunk layer, AMF0 and five commands, over TLS through `Network`. There is no
FFmpeg and there does not need to be. Everything else is a system framework:
VideoToolbox for H.264, AVFoundation for cameras, ScreenCaptureKit for the
screen, Core Text for real letters and Vision for face detection. **The Mac
therefore ships none of what Windows pays for**: no Pillow, no OpenCV, no
model file. The download grew by about a megabyte, which is the two Roboto
files, and those are shipped for a reason: a card made on a Mac and a card
made on a PC have to be the same card.

**Three measurements that changed the code, all made on this Mac on
8 September 2026.** `docs/MAC-VIDEO-PIPELINE.md` has the rest.

1. **`ConstantBitRate`, and never `AverageBitRate` or `DataRateLimits`.** On a
   static card at a 2500 kbps target, average gave 329 kbps and data rate
   limits gave 244; constant gave 2375. Both platforms publish bitrate FLOORS,
   so this is the same fault Windows chased down, reached by another road.
   `EnableLowLatencyRateControl` silently dropped 85 per cent of frames.
2. **ScreenCaptureKit sends no frame when the screen is not changing.** Six
   seconds of a static desktop gave 46 complete frames and 142 idle ones.
   Copying `screenStaleSeconds` across without a second clock would have
   declared a presenter's static slide dead mid show and put the card out
   instead. An idle frame is a HEARTBEAT: see `Screen.swift`.
3. **A screen capture that has not been allowed comes back BLACK**, not as an
   error, and `CGPreflightScreenCaptureAccess` still answers yes. Measured
   with a Developer ID signed build. The opening frames are looked at once and
   an all black start is called what it almost always is, because a silent
   black broadcast is the exact failure this app exists to prevent.

**The BT.709 tags are set and never touched.** VideoToolbox converts at 709
whatever they say, so it writes the tag only and the Windows fault cannot
happen. The opposite one can: setting the matrix to 601 would ship 709 pixels
labelled 601, which is invisible from the sending end.

**Two faults in the SHIPPED 3.3.2 were found while building this.** A modal
key claim reached past a box opened on top of it, so a source name with a
space in it could not be typed; and a read only text view swallowed Return, so
every panel that puts focus on what it has to say had a dead Return, including
the update panel. Both are fixed and both have checks.

## Drop Deck Audio, the cable, which arrived on 11 September 2026

`mac/driver/` is an **AudioServerPlugIn**: a virtual audio cable called Drop
Deck Audio that the app installs, so a presenter gets Drop Deck into TeamTalk,
Zoom or Skype with nothing to download and nothing to wire up. It is the one
thing this copy has that the Windows one does not.

**The route was decided by Apple, not by us.** AudioDriverKit needs
`com.apple.developer.driverkit.family.audio`, and Apple will not grant it for a
device with no hardware behind it: virtual devices are told, in as many words
and as recently as March 2025, to keep using the plug-in model. So this is the
supported road and the modern looking one is a dead end. An AudioServerPlugIn
needs **no entitlement at all** and any Developer ID account can ship one.

**It began as Apple's `NullAudio` sample, which is MIT.** `APPLE-LICENSE.txt`
is kept verbatim beside the source and inside the bundle, because the licence
requires it. That sample already advertises exactly what we want, two channels
of 32 bit float at 44100 and 48000 with transport type virtual, and its
`DoIOOperation` throws the audio away. **BlackHole is GPL-3.0 and was read and
not used**: this product is MIT and vendoring GPL code into it would change its
licence. Everything ours in that file is marked DROP DECK.

Three things we added, and each is the difference between working and not:

1. **The ring.** Both sides index one buffer by their own sample time. The HAL
   already schedules input behind output by the latency and safety offset the
   device advertises, so the delay comes out for free and computing an offset
   by hand is how this goes wrong.
2. **The silence guard.** Without it the input side goes on reading a ring
   nobody is refilling, so the far end of a call hears the last fraction of a
   second of the show over and over for as long as they stay connected. A buzz
   that never stops and appears nowhere in the app. Measured idle: peak
   0.000000.
3. **A seed that moves.** Apple's sample returns a hard coded 1 from
   `GetZeroTimeStamp`, which tells the HAL the timeline has never changed for
   the life of the process. It is bumped on `StartIO` and on a rate change.

**Exactly two channels, and it is a decision rather than a default.** Zoom sums
any input wider than two to mono whatever its stereo setting says, so a cable
with more would arrive in a call as one ear of the show.

**The ring is an exact multiple of the zero timestamp period.** That is what
keeps the modulo arithmetic coherent across a wrap, and it is why
`kDevice_RingBufferSize` was renamed `kDevice_ZeroTimeStampPeriod`: in Apple's
sample there was no ring at all and the number was only the period. Conflating
the two is what makes a cable click once per wrap.

**A crash here is smaller than the folklore says and a hang is worse.** Each
plug-in runs in its OWN sandboxed helper process, confirmed on this machine:
`Core Audio Driver (Drop Deck Audio.driver)` sits beside Zoom's and Rogue
Amoeba's under `_coreaudiod`. So a segfault takes out our driver's host rather
than the machine's audio. Wedging the real time thread does take the machine
down, which is why there is no allocation, no blocking lock and no logging in
the IO path.

**Installing it needs a password and there is no way round that**, because
`/Library/Audio/Plug-Ins/HAL` belongs to root. The app does it with one
`osascript` call so macOS asks once for the whole job. **The `chown` and
`chmod` in it are not tidiness**: the commonest real failure anywhere in this
area is a HAL folder left at the wrong mode, after which the driver is there,
nothing loads it, and no error appears anywhere a user could find.

**Core Audio has to be restarted, and that stops every sound on the Mac,
VoiceOver included.** It is said in words BEFORE the password box, and skipping
it is offered: the cable appears at the next login either way.
`sudo launchctl kickstart` is NOT an alternative, it has been refused under
System Integrity Protection since macOS 14.4. `killall -9` is what works, and
the `-9` matters because coreaudiod traps SIGTERM.

**A signed `.pkg` is Apple's own recommendation and is not available yet.** It
needs a Developer ID *Installer* certificate, which this account does not have
and only the Account Holder can create. Tony chose the password prompt for now,
11 September 2026. The `.pkg` route is the upgrade when that certificate exists.

**The driver is universal and the app is not, and that is deliberate.**
`coreaudiod` runs natively on an Intel Mac even under Rosetta, so an arm64 only
driver would be invisible there however the app was built.

`build.sh` builds the driver and copies it into `Contents/Resources`, signed,
before the app is sealed around it: codesign works inside out and notarytool
checks every nested Mach-O, so one notarization covers both.

**`--check-send [seconds] [uid]` is the proof, and it is the only thing that
can be.** Every layer of a send can report itself healthy while nothing
arrives; that is exactly what Windows found. It drives the real `Send` through
the real `AirBus` out of the real card and records that card's input side.
Measured 11 September 2026, eight seconds at 48000 and five at 44100: no gaps,
1000.0 Hz against 1000.0, nothing dropped, nothing rebuffered, and peak
0.000000 with nothing playing.

**The first three runs of that check failed, and all of it was the harness.**
It stopped feeding the bus, waited, then closed both ends, so the recording
ended with the ring draining into silence and the send counting a rebuffer for
a ring nobody was filling. It reported one 188 ms gap and a tone at 968 Hz,
which is indistinguishable from the real fault it exists to catch. A show does
not stop feeding its send and then ask whether the send is keeping up: the
feeder runs on its own thread and the health is read BEFORE anything closes.

## Why not the Python

The obvious plan was to run the existing wxPython app on macOS. It was rejected
after checking, not after guessing:

- **`wx.Accessible` is Windows only.** The whole accessibility layer of the
  Windows app, `name_field` and the `_Named` bridge in `dialogs.py`, is MSAA
  and has no macOS implementation at all. The app's most important quality
  would have been the first thing lost.
- **`accessible_output2` is an NVDA and JAWS bridge.** There is no VoiceOver
  in it.
- The MSAA rule that a control inherits the accessible name of whichever
  static text was **created** before it, which most of `dialogs.py` is shaped
  around, is a Windows quirk that does not exist on macOS and would have left
  every field unlabelled.

So the audio and the model are ports, and the interface is written natively.
On AppKit the label is a property of the control, which is why `Panels.swift`
is a fraction of the size of `dialogs.py` and does the same job better.

## The one thing that had to change: the digit map

The map is frozen and it stayed frozen in shape. What moved is which key sits
under the thumb, and there was no way around it.

| Windows | Mac |
|---|---|
| `1` to `0` | `1` to `0` |
| `Shift+digit` | `Shift+digit` |
| `Ctrl+digit` | `Command+digit` |
| `Ctrl+Shift+digit` | `Command+Shift+digit` |
| `Alt+Ctrl+digit` | `Option+Command+digit` |
| `Alt+Ctrl+Shift+digit` | `Option+Command+Shift+digit` |

**Control plus Option is VoiceOver's own modifier.** The literal translation of
the beds bank, `Alt+Ctrl+digit`, is `VO+digit`, which VoiceOver has already
bound to its Hot Spots: `VO+1` to `VO+0` jump to a hot spot and `VO+Shift+digit`
assigns one. VoiceOver takes those in the accessibility layer, above the
application, so the app receives nothing at all. Handing the looping bank to
VoiceOver was not a trade worth making.

**`Control+digit` is contested too**, and by macOS rather than VoiceOver:
symbolic hotkey 118 and up are Mission Control's "Switch to Desktop N". They
are switched off on Tony's machine and on by default everywhere else.

The Windows combinations are still **accepted as aliases** wherever the system
leaves them free, because a key somebody has already learned does not get taken
away. `Preferences, Keyboard` offers the literal Windows map for anyone who has
moved VoiceOver's modifier to Caps Lock, and says there what it will cost.

`Help, Check the keyboard` is the instrument for all of this: it reports every
key that really arrives and names the ones that never did. It exists for the
same reason `tools/check_keyboard.py` does on Windows. Some things can only be
tested with a real keystroke, and no documentation anywhere can tell you what
one user's VoiceOver settings will let through.

Two other keys had to move, both for the system rather than for VoiceOver:

- `Ctrl+Space` (stop the last sound) became **`Option+Space`**. `Command+Space`
  is Spotlight and `Control+Space` is the input source switcher.
- `Alt+Enter` (properties) is joined by **`Command+I`**, which is Get Info
  everywhere on a Mac. `Option+Return` still works, because it is the TG
  Studios convention.

`F1` to `F8` are unchanged and only arrive when the user has switched on "Use
F1, F2, etc. as standard function keys". The app reads `com.apple.keyboard.fnState`
at launch and says so once if it is off, because a fader key that does nothing
looks like a fault. Every one of them is also a menu item.

## What replaced the accelerator table swap

Nothing, and that is the point.

The Windows app swaps its whole accelerator table whenever a text box takes
focus, driven by `EVT_CHILD_FOCUS` **and** `EVT_IDLE`, the second only because
focus moving into a `wx.SpinCtrlDouble` raises no child focus event at all.
That machinery exists because a wx accelerator table on a frame is consulted
BEFORE the control with focus.

Cocoa asks in the other order. A single `NSEvent` local monitor in
`AppDelegate.installKeyMonitor` reads the first responder **at the instant of
the keystroke**: if it is an `NSTextView`, which is what the field editor is
for every text field, search field and combo box in the app, a bare digit is
handed straight on. There is no state to keep in step and no focus event that
can be missed. The composite control bug has no analogue here.

The one deliberate difference from Windows: **`Shift+digit` also stands down
while a text box has focus.** On Windows it stays armed, so typing `!` into the
crossfade box fires pad 11. That is a bug rather than a feature and it was not
carried across.

## The audio, which is a literal port

`Engine.swift` and `Mixer.swift` know nothing about AppKit, exactly as
`engine.py` and `mixer.py` know nothing about wx, and for the same reason: the
self test renders the whole mixer and inspects the samples with no sound card
present.

Three numbers in it are easy to "tidy" into being wrong, and the self test
asserts all three:

- **A Voice fade normalises its step to the distance it has to cover**, so a
  half second fade takes half a second from any starting level.
- **The duck ramp deliberately does not.** It travels one gain unit per span,
  so at minus nine decibels the attack really takes about 77 ms and the release
  about 452 ms. Writing "reach the target in DUCK_ATTACK seconds" would make
  the duck half as fast and change how a show sounds.
- **The ceiling is a curve, not a corner.** Above 0.85 the top of the wave is
  bent with `tanh` rather than clipped.

**The limiter is hand written and must stay hand written.** Apple's
`kAudioUnitSubType_PeakLimiter` has no threshold and no ceiling parameter at
all: it limits at full scale and you drive it with pre-gain. "Never louder than
minus one" has to be a promise, so the Windows `dsp.Ceiling` recurrence is what
gets ported when the microphone chain lands.

`AVAudioUnitEQ` does cover the high pass and the three band equaliser exactly.
Apple's `DynamicsProcessor` has **no ratio parameter**, so the compressor and
the gate are hand written too.

## Devices

One `Mixer` per distinct sound card, each on its own AUHAL output unit, sharing
one `DuckBus`. Banks sharing a device share a mixer, so the common case of one
output is still one stream. Verified: three engines on three different cards in
one process.

A device is saved by its **Core Audio UID**, which is stable across reboots and
replugs, rather than by the name plus host API the Windows copy has to match
on. The name is saved alongside it, for the Windows copy and for a person
reading the file.

**Do not open a sound card on the main thread during
`applicationDidFinishLaunching`.** `AudioComponentInstanceNew` sends a
synchronous message to `coreaudiod` and waits, and doing that while AppKit is
still inside the launch Apple Event deadlocks the process before it draws
anything. It hangs every single time and produces no crash report, so it looks
like the app simply failing to open. `MainWindow.startAudio` is called from a
`DispatchQueue.main.async` after the window is up, and the cards are then left
open for the life of the app so no keypress ever pays to open one.

## Speech, and the one line that made all of it silent

Four channels became five in 3.3.0, and the reason is worth keeping.

**An announcement is only honoured on an NSWindow or on NSApp.** Until 3.3.0
`Speaker.say` posted `.announcementRequested` to `window.contentView`, and
VoiceOver said nothing at all. Every channel also writes the status line, so the
app looked like it was working: Command D really did toggle the ducking and the
words really did appear at the bottom of the window. They were simply never
spoken. Post to `NSApp.keyWindow`, which is also what puts a line spoken from
inside an NSAlert into that alert rather than behind it. Chat Grid had this
right all along, in `Announcer.say(_:in:)`, which is where the shape came from.

**`announceState` is the fifth channel.** A switch you pressed and cannot see
speaks at every level, including "none", for the same reason an answer does:
"none" means stop narrating, not stop answering. Ducking, the microphone, the
stream, the recorder, global hotkeys, source mute and solo and the three faders
are on it. Windows classes these as `announce`, which is right there because
NVDA is not the app; here the app IS the only thing that says so.

## Escape, and who owns a key while a dialog is up

`AppDelegate.installKeyMonitor` runs before AppKit dispatches anything, so
whatever it claims, nothing else can have. It was claiming Escape unconditionally
and handing it to the stop counter, which meant **no dialog in the app could be
closed with Escape**, Preferences included. It now claims Escape only when there
is no modal session and the key window is the main window.

`ModalKeys` is the other half. A panel that drives itself from the keyboard used
to install a second local monitor and hope it was asked first; AppKit promises no
order between monitors, and the source control panel's digits, which are the
whole point of it mid link, were sometimes losing to the digit map and firing
pads. A panel now sets `ModalKeys.current` for the length of its `runModal` and
the window's monitor asks it first. `SourceControlPanel`, `HotkeyPanel` and
`KeyboardCheckPanel` all use it.

## Two commands on one key is not an error anything reports

`.viewBoard` and `.sourceControl` were both on Option+Command+Shift+S. AppKit
gives the key to whichever menu item it reaches first in the menu bar and says
nothing at all, so Source control was unreachable from the keyboard from 3.2.2
until 3.3.0. It is the same shape as the Windows bug where a frame accelerator
took Ctrl+Shift+S off Save board as. `SelfTest.testKeyMap` now refuses a build
with two commands on one key, comparing `KeyMap.identity` rather than
`KeyMap.spell`: `spell` is written for a person and calls both the forward
delete and Backspace "Delete".

**Every binding after the first is an alias, and until 3.3.0 nothing dispatched
one.** A menu item carries one key equivalent, so Command E, Command P, Option
Return, Command Shift bracket and Backspace were declared in `KeyMap.bindings`
and reached nowhere. `KeyMap.aliasCommand(for:)` resolves them and the monitor
sends them to the same selector the menu item uses, through the `actions` table
that `item(_:_:_:)` fills in as the menus are built, so the two cannot drift
apart. An alias that is some other command's real menu key is never claimed.

## Formats

The extension list is **asked of Core Audio at runtime** rather than typed out,
the same rule as the Windows build: nothing is offered that would then fail at
the moment somebody pressed a key.

Measured on macOS 26, this Mac reads wav, mp3, ogg, opus, flac, aiff, w64, au,
m4a, m4b, mp4, aac, ac3 and amr. That is everything the Windows build plays
except **wma, webm, mka, ape and wv**, which are refused honestly. The demo
pack is FLAC and Ogg Vorbis and plays untouched.

**There is still no MP3 encoder on macOS**, in AudioToolbox or anywhere else. It
is decode only, measured three ways and again in 3.3.0: asked directly,
`kAudioFormatProperty_Encoders` returns nothing for `.mp3` while returning
`appl/aac`, `appl/opus`, `appl/flac` and `appl/alac`, and `AVAudioConverter` to
MP3 is nil at every rate. `afconvert -hf` lists MP3 because it can READ it, which
is the trap.

**So from 3.3.1 MP3 comes from LAME**, in `mac/vendor/`, dynamically linked and
shipped as its own file in `Contents/Frameworks`. `mac/vendor/README.md` is the
licensing reasoning and `mac/vendor/build-lame.sh` reproduces the library from
published source, refusing to build anything whose sha256 is not LAME 3.100's.
Three things about it are not obvious:

- **LAME has two float entry points one letter apart and they use different
  scales.** `lame_encode_buffer_ieee_float` wants plus or minus ONE, which is
  what the mixer works in. `lame_encode_buffer_float` wants plus or minus 32768.
  Feeding the second scale to the first multiplies everything by 32768 and ships
  a stream that is nothing but clipping, AND IT STILL FRAMES AND DECODES AS A
  PERFECTLY VALID MP3. The first cut of this shipped that way for an hour. The
  only thing that can tell the difference is listening, so the self test now
  decodes each format back with macOS, which decodes everything it cannot
  encode, and asserts the level. That check was verified by putting the bug back
  and watching it fail at peak 1.000.
- **The Info tag is for files only.** `lame_set_bWriteVbrTag(1)` makes LAME
  reserve a blank frame at the start which `lame_get_lametag_frame` later fills
  in, written back over offset zero. A socket has no offset zero, so a stream
  sets it to 0; leaving it on sends the blank placeholder as the first thing a
  listener hears and some players call it a zero length track and refuse it.
- **The dylib is signed separately, before the bundle.** Notarization refuses a
  bundle with anything unsigned inside it, and codesign has to work inside out
  or it seals a copy it will then call modified.

**The Ogg muxer is ours.** `OggStream` in `StreamOut.swift` writes the pages,
because Apple encodes Opus perfectly well and then has nowhere to put it. Two
things in it cannot be eyeballed and are checked by the self test instead: the
CRC is the Ogg variant, polynomial 0x04c11db7 with no reflection and no final
xor rather than the one in zlib, and the granule position is counted in 48 kHz
samples whatever the card is doing. Opus does not run at 44.1 kHz at all, so the
same `AVAudioConverter` resamples and encodes in one step. Verified with
`ffprobe` against the bytes the self test writes to
`$TMPDIR/dropdeck-selftest/stream-sample.opus`.

So `C.streamFormatKeys` is MP3, AAC in ADTS, Opus in Ogg and WAV, with MP3 the
default because it is what most mounts want; `C.recordFormatKeys` is WAV, MP3,
AAC and FLAC. Recording has no Opus, and not for MP3's reason: the streamer
writes Ogg pages going forwards, and a FILE has to be right at the end too,
which is a different job.

## The board file

The same `board.json`, read and written by both copies.

**Anything this build does not recognise is kept and written straight back
out.** A board saved on the Mac must never lose the streaming server or the
microphone chain just because the Mac has not reached those features yet. Both
`Slot` and `Board` keep an `unknown` dictionary for it and the self test proves
the round trip.

Where a value cannot mean the same thing on both platforms it gets a key of its
own rather than overwriting: `key_code` and `modifiers` are wx's and are
carried through untouched, and `mac_key_code` and `mac_modifiers` sit beside
them. Same for `mac_device_uid` and `mac_bank_scheme`.

## Building

```
./build.sh              build and install into /Applications
./build.sh --no-copy    build only

DROPDECK_ADHOC_SIGN=1 ./build.sh --no-copy    seconds rather than minutes
```

**Two things turn a one minute build into a ten minute one, and both look
exactly like a hung compiler.** `--timestamp` is a round trip to
timestamp.apple.com and blocks when that server is slow;
`DROPDECK_NO_TIMESTAMP=1` drops it. Signing with Developer ID needs the private
key out of the login keychain, and if macOS decides to ask permission the dialog
sits on screen and `codesign` waits for it for ever, with nothing on stderr;
`DROPDECK_ADHOC_SIGN=1` signs ad hoc and needs no key at all. `release_mac.py`
sets neither and a release always has both. If a build seems stuck, look for a
`codesign` process at nought per cent and a running `SecurityAgent`.

`swiftc` straight to a bundle, no Xcode project, the same shape as Chat Grid.
The build goes to `~/Library/Application Support/TG Studios Build/drop-deck-mac`
and **never inside Dropbox**, for the same reason the Windows build does not.

`NSPrincipalClass` is required in `Info.plist`. Without it the app does not
activate and does not appear properly in the Dock, and nothing says why.

**Do not sandbox.** Of the 634 effect Audio Units on Tony's machine only 73 are
sandbox safe, so sandboxing would hide 88 per cent of his plugin collection.
The board also references sound files all over his drives and never copies
them.

## The checks

```
"/Applications/TG Drop Deck.app/Contents/MacOS/TGDropDeck" --selftest
```

Over three hundred checks and they run against the **built app**, not the source, because the
source passing tells you nothing about whether the shipped bundle can find its
demo pack or open a sound card. The last section opens a real output device and
renders a quarter second of silence through it, so a dead audio backend shows
up here rather than on the first keypress. `tools/release_mac.py build` refuses
to zip a bundle that does not pass them.

Several of the checks are there because they have already caught a real fault:

- `hotkeyLabel` indexed the ten digit row with the twenty slot bank size, which
  crashed on every slot above ten, and the label test found it.
- The handover test drives the real transport with no sound card and no clock,
  rendering blocks by hand and calling `tick()` the way the timer would: the
  cue point arithmetic says WHEN a handover should happen, and only this says
  that it does.
- The drops library was being written under `files` while the Windows copy
  reads `paths`, so a board's idents vanished on a round trip through the Mac.
  The library test now asserts the Windows key, and the loader still reads the
  old one for the handful of boards this build wrote that way.
- Two commands on one key, which nothing else reports. See above.
- The stream encoders are driven for real: two seconds of a tone through each
  of the three, then the bytes are read the way a server would read them, every
  Ogg page's CRC checked, and each stream written out beside the other scratch
  files so it can be opened in a player when something is argued about.
- The canonical bytes test holds Python's own `json.dumps(sort_keys=True,
  separators=(",", ":"))` output for a string full of awkward characters. Get
  one escape wrong and every update manifest is "signed by the wrong key" for
  ever, with nothing anywhere reporting why.

Four other switches on the binary: `--dump-keys` prints every key the app
binds, for `mac/check_guide.py`; `--dump-help` prints the F1 list exactly as
the app shows it, so the half of it that is derived can be read rather than
taken on trust; `--check-send` is the cable proof described above; and
`--verify-manifest <file>` verifies a staged update manifest with the key baked
into that build, for `tools/release_mac.py rehearse`.

Three checks added in 3.8.0 are there because they caught something on their
first run:

- **`Recorder.fileExtension` fell through to `.wav` for anything it did not
  know**, so the first MP4 this app ever wrote would have gone into a file
  called `.wav`. That is the same fault Windows found the first time it
  recorded a picture.
- **F1 was eight keys behind**, missing every key the video work added in
  3.5.0 and 3.5.2. It is now half hand written chapters and half derived from
  `KeyMap.bindings`, and the check refuses a build where anything bound is
  missing from the text.
- **`Board.replaceContents` was missing all twenty two video properties**, so
  File, Open loaded a board's picture, colours, platform and stream size and
  then discarded them. The replacement check cannot fall behind: it sets every
  property to a non default, copies, and compares the two boards as the
  dictionaries they save as.

## Boards from elsewhere, and the file menu

`MainWindow.adopt(_:path:)` is the one way another board becomes the live one:
File, Open, the demo pack, an old bank and a new board all go through it. It
copies **every** stored property across (`Board.replaceContents`), including
the running order, the drops library, the stations and the microphone chain,
and then rewires everything that was reading the old values. The first cut of
the Mac copied only the slots and the volumes, so opening a board silently kept
the previous playlist and then saved it over the file. A property missing from
`replaceContents` is that bug again, and the self test asserts the ones that
were lost.

File, Open makes the opened file the live board, saved to from then on, which
is what the Windows copy does. The demo pack and an import are copied into
your own board file instead.

## Running orders, the library and stations

`M3U.swift` writes and reads the same extended M3U as `dropdeck/m3u.py`, CRLF
line ends and `#DROPDECK:` comments included, so a running order moves between
the two copies. It decodes UTF-8, then Windows-1252, then Latin-1, turns
backslashes into slashes only when a path has no forward slash at all, and
strips a byte order mark from text as well as from bytes: the test that fed it
a string with a BOM found that the header line became a track.

Dropping files on the running order ADDS them and dropping an M3U adds its
contents; Playlist, Open a running order REPLACES. Same as Windows.

A saved station is kept as a raw dictionary of the Windows `stream_*` keys, so
the list moves between the copies untouched. A Windows station naming MP3 or
Ogg is moved to AAC when it is loaded here, for the reason under Formats. The
Streaming tab's Save and Forget buttons mark the board dirty on the spot and
survive Cancel, because a password somebody has just typed in is not something
to lose to a reflex.

## Feedback and updates

`Feedback.swift` posts to the same endpoint as Windows, in the same shape,
through the same on-disk queue (`feedback_queue.json` in the support folder),
and never a name or a path. `AppUpdate.swift` reads
`tgstudios.app/updates/drop-deck-mac.json`, a second manifest beside the
Windows one, ed25519 signed. Four things about it are not obvious:

- **The app trusts two keys**, `publicKeyB64` and `macPublicKeyB64`, and a
  manifest signed by either is accepted. The first is the shared TG Studios
  update key every Windows app carries, whose private half lives on the
  Windows machine. The second was made on this Mac on 6 September 2026
  (`~/.tgstudios/update-private-key-mac.pem`) so a Mac release never needs
  both machines. Neither key may change once shipped. **Back the Mac key up**:
  lose it and Mac manifests can only be signed with the Windows key, which
  still works because the app trusts both, but only from that machine.

- **The signed bytes are rebuilt from the parsed manifest** exactly as Python
  serialises them: sorted keys, no spaces, and everything outside space to
  tilde escaped as `\uXXXX` with lower case hex. `AppUpdate.canonical` is that,
  and the self test proves it against Python's output byte for byte.
- **The running copy replaces itself.** Windows cannot overwrite a running
  executable, so there the new copy does the swap after the old one exits.
  macOS can rename a running bundle freely, so the old copy moves itself
  aside as `TG Drop Deck.app.replaced`, moves the new one in, strips
  quarantine, schedules `open` through a detached shell that waits a second,
  and quits. The wait is for the single instance check: the new copy would
  otherwise find this one still quitting and hand straight back to it. The new
  copy removes `.replaced` and the staging folder on its first launch.
- **Only a copy under Applications is offered a replacement of itself**, which
  is the Mac's version of the Windows `is_frozen` rule. A build sitting in the
  build folder is the developer's.

An update is never installed while the stream or the recorder is running, and
the daily check stays silent unless there is something.

**`TGDropDeck --check-updates` is how a release is proved.** The installed app
itself fetches the live manifest, verifies the signature and compares
versions, and prints what it concluded. Run it after every publish. The self
test also rehearses the swap itself on scratch bundles: a zip of the running
app is unpacked the way a download is and put in place of a copy standing in
for the installed one, because the arithmetic of an update is nothing and the
swap is the part that has to work on a Tuesday night.

`NSAppTransportSecurity` allows arbitrary loads. Who is listening asks an
Icecast server for `status-json.xsl`, and Icecast is almost always plain http
on port 8000; the default address the app builds is plain http too. Without
the exception every one of those requests failed silently. The stream itself
is a raw socket and never went through ATS.

## The manual, and the checker that keeps it honest

`Websites/tgstudios.app/content/pages/drop-deck-guide-mac.md`, published at
tgstudios.app/drop-deck-guide-mac, and opened from Help, User manual through
`C.userGuideURL`. It is the Mac's own manual rather than the Windows one with
the keys swapped, because half the Windows chapters name things a Mac cannot
do (VST3, WMA, MP3 out) and the Mac has things Windows does not (VoiceOver as
a source that survives a restart, a keyboard check).

**Run `python3 mac/check_guide.py` whenever a key changes.** It asks the built
app for every key it binds (`--dump-keys`) and checks each backticked key in
the guide against that list, and the other way round. Keys the guide names on
purpose that the app does not bind, such as `Command+Space`, are listed in
`EXPLAINED` with the reason, so an unexplained miss is a real miss. Then
deploy the site with `python3 deploy.py` from the site folder.

## Releasing

```
python3 tools/release_mac.py build     # build, self test, zip
python3 tools/release_mac.py publish   # stage, rehearse, upload zip and manifest
```

The zip is made with `ditto --keepParent`, which is what the app itself unpacks
with. `release_mac.py` is standalone on purpose: it reads the version and the
keys out of the source as text rather than importing `dropdeck/`, which needs
numpy and wx that a Mac does not have. It signs with the Mac key when that is
present and the shared Windows key otherwise, refuses a key the app does not
trust, and the rehearsal runs the built app's own verifier on the staged
manifest before anything is uploaded. `build` also notarizes and staples when
the bundle is Developer ID signed and a `TGStudios` notarytool profile exists,
and says plainly when it is skipping that.

`python3 tools/release_mac.py feeds` checks BOTH platforms' live feeds the way
the apps do: signature against the key that app carries, version, and that
every download named is really there at the size it says. `--download` hashes
them too. The site's `deploy.py` runs the same check on every deploy and fails
the deploy if either feed is broken, so a site deploy can never quietly leave
an installed copy cut off from its next update.

**Uploading goes to the `tonyserver` ssh alias**, which is where the key is.
`tony@server.tonygebhard.me` is the same machine with the same host key and no
identity file configured, so it fails at scp after the build, the notarization
and the rehearsal have all passed. `release_mac.py` now picks the alias itself
when `~/.ssh/config` has it, and `RELEASE_SERVER` still overrides.

The first Mac release, 3.2.2, was published on 6 September 2026: zip, manifest
and the download button on `drop-deck.md`, and the installed app confirmed the
feed with `--check-updates`.

**The two copies can be on different versions, and 3.3.0 is the first time they
are.** `release_mac.py` reads the version out of `dropdeck/constants.py` and
refuses a bundle that disagrees, so a Mac only release bumps both constants and
leaves the WINDOWS FEED where it is until Windows is next built on the PC.
`feeds` notes the difference rather than failing, and the site's `deploy.py`
checks each platform's feed against that platform's own download link on the
page rather than against one "Version x.y.z" in the prose, which cannot tell
which platform it belongs to.

## Signing

`build.sh` signs with the first identity it finds, preferring Developer ID and
falling back to Apple Development, and only then to ad hoc. Since 6 September
2026 this Mac has a **Developer ID Application** certificate for Tony's paid
team, R85F5PGU87, valid to September 2031, made from a signing request whose
private key is `~/.tgstudios/developer-id-application.key` (the certificate is
beside it, and both are the backup Apple asks you to keep). The earlier Apple
Development certificate belongs to a different team, GFK2728D9X, so the first
build signed with Developer ID changed the app's designated requirement once:
macOS asked for the microphone again, and will not again after that.

**Notarized since 6 September 2026.** The notarytool keychain profile
`TGStudios` exists on this Mac (made with `mac/notarize-login.sh` and an
app-specific password of Tony's), so `release_mac.py build` submits every
build to Apple, waits, staples the ticket into the bundle and asks Gatekeeper
to assess it before anything is zipped. The first submission took about forty
minutes; later ones are usually minutes. A downloaded copy now opens like any
other app, and the manual and the product page say so. Updates installed from
inside the app never needed notarization, because nothing the app downloads
itself is quarantined.

## Three traps found on 11 September 2026

**Python's `round` is banker's rounding and Swift's `.rounded()` is not.** A
`.cue` timestamp lands on exactly half a frame every 150th of a second, and the
Mac put those one frame later than Windows on every one of them.
`.rounded(.toNearestOrEven)` is the fix and `cross_check.py` found it on the
first run of the new case. Anywhere a port rounds, this is waiting.

**`KeyMap.spell` put Shift before Command and every sentence in the product
puts Command first.** The manual has said `Command+Shift+B` since it was
written and so has F1, and nothing noticed for six months because
`check_guide.py` normalises the modifier order before comparing. F1 does not:
it matches a derived key against a hand written chapter as plain text, so the
moment the F1 list was derived, every key in it appeared twice.

**"Hear yourself through" was saved, carried across a File Open, and read by
nothing.** Monitoring came out of the main card whatever the board said, from
the day the microphone landed. `MixerGroup.monitorMixer` returned `primary`
unconditionally while its own doc comment described the behaviour it did not
have. A setting that does nothing is worse than no setting.

## Still to do

- **A real broadcast to YouTube and Facebook.** The RTMP client is proved end
  to end against `tools/mock_rtmp.py`, which decodes what arrived frame by
  frame, and it has not yet been pointed at a real platform. Restream with
  every channel switched off is the place to start: the stream reaches
  Restream and goes nowhere.
- **The camera has not been opened by the real app yet.** Enumeration is
  proved and the permission is in the Info.plist, but nothing has yet shown
  Tony the system prompt, which is his to answer.
- **Hosting Audio Units in the voice chain**, the Mac's answer to the Windows
  VST3 hosting. The entitlement for it is already in place
  (`disable-library-validation`), the parameter list the chain uses is the
  shape a hosted plugin's parameters would take, and the manual says plugins
  are not hosted yet.
- **An Intel build of the APP.** `build.sh` targets arm64 only. A universal
  binary is a second `-target` and a `lipo`, and nothing in the code is
  architecture specific, but it has not been built or tested. The DRIVER is
  already universal, and has to be: see the note under Drop Deck Audio.
- **A signed `.pkg` for the cable**, once a Developer ID Installer certificate
  exists. It is Apple DTS's own recommendation over the password prompt, and
  Installer.app is well trodden ground with VoiceOver.
- **The cable has not been through a real call yet.** It is proved with a tone
  and a recording at both rates; nobody has yet put Drop Deck into TeamTalk and
  asked the far end how it sounds.
