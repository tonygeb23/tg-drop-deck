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

## Formats

The extension list is **asked of Core Audio at runtime** rather than typed out,
the same rule as the Windows build: nothing is offered that would then fail at
the moment somebody pressed a key.

Measured on macOS 26, this Mac reads wav, mp3, ogg, opus, flac, aiff, w64, au,
m4a, m4b, mp4, aac, ac3 and amr. That is everything the Windows build plays
except **wma, webm, mka, ape and wv**, which are refused honestly. The demo
pack is FLAC and Ogg Vorbis and plays untouched.

**There is no MP3 encoder on macOS**, in AudioToolbox or anywhere else. It is
decode only, measured three ways. So `C.recordFormatKeys` offers WAV, AAC,
Opus and FLAC rather than the Windows WAV, MP3, AAC and Opus. When streaming
lands, AAC in ADTS is the format that needs nothing vendored; MP3 would mean
LAME and a licensing decision, and Ogg would mean writing the muxer, because
Apple's own `afconvert` cannot produce an Ogg file either.

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
```

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

294 checks and they run against the **built app**, not the source, because the
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
- The canonical bytes test holds Python's own `json.dumps(sort_keys=True,
  separators=(",", ":"))` output for a string full of awkward characters. Get
  one escape wrong and every update manifest is "signed by the wrong key" for
  ever, with nothing anywhere reporting why.

Two other switches on the binary: `--dump-keys` prints every key the app
binds, for `mac/check_guide.py`, and `--verify-manifest <file>` verifies a
staged update manifest with the key baked into that build, for
`tools/release_mac.py rehearse`.

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

The first Mac release, 3.2.2, was published on 6 September 2026: zip, manifest
and the download button on `drop-deck.md`, and the installed app confirmed the
feed with `--check-updates`. Version numbers stay in lockstep with Windows.

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

**Notarization is the one step left**, and it needs a notarytool keychain
profile called `TGStudios`, which only Tony can make because Apple wants an
app-specific password from his account: `mac/notarize-login.sh` does the whole
thing in one paste. Until then `spctl --assess` says "Unnotarized Developer
ID", a copy downloaded in a browser needs Open Anyway once, and the manual and
the product page say so. Updates installed from inside the app never needed
notarization, because nothing the app downloads itself is quarantined. Once the
profile exists, `release_mac.py build` notarizes and staples on its own, and
the sentence about Open Anyway comes out of the manual and the product page.

## Still to do

- **Notarisation**, above: the notarytool profile, then republish, then take
  the Open Anyway sentence out of the manual and the product page.
- **Hosting Audio Units in the voice chain**, the Mac's answer to the Windows
  VST3 hosting. The entitlement for it is already in place
  (`disable-library-validation`), the parameter list the chain uses is the
  shape a hosted plugin's parameters would take, and the manual says plugins
  are not hosted yet.
- **An Intel build.** `build.sh` targets arm64 only. A universal binary is a
  second `-target` and a `lipo`, and nothing in the code is architecture
  specific, but it has not been built or tested.
