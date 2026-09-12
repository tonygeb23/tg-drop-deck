# Changelog

## 3.8.2 for Windows, 12 September 2026

**One key per destination, and your radio station stops being printed as the
name of your YouTube channel.**

Tony, reading what Ctrl+B put in front of him before going live:

    Going to: Blindside Radio, on YouTube Live

Blindside Radio is an Icecast station. It has nothing to do with YouTube, and
the summary said otherwise because ONE field, the station name, was doing both
destinations' jobs. That is the same trap the streaming address was split in
two for: set one up and you silently changed the other.

### Two destinations, two names

There is a **Channel name** box on the Video streaming page now. It is
optional, and empty is the ordinary state: a platform with one address speaks
for itself, and inventing a name would only replace one untruth with another.

- With it empty: **YouTube Live**
- With it filled in: **Tony Gebhard, on YouTube Live**
- Your radio station: **Blindside Radio, blindsideradio.com/live**, as before

YouTube and Facebook no longer have their ingest address read out on the way
to air. There is one each, it is not yours to choose, and it tells you nothing
you can act on. A custom RTMP server still shows its address, because for that
one the address is the useful fact.

### Ctrl+B for video, Alt+Shift+B for radio

One key each. The summary you are shown before going live is now always for
the place you actually meant, rather than for whichever destination you last
picked in a menu.

Each key is a toggle for its own destination. Pressing the key for the place
you are not broadcasting to tells you where you actually are and does nothing
else: switching means dropping one connection and opening another, which is
not a thing to do to somebody mid show on a keypress that looks like a toggle.

**It is Alt+Shift+B and not the Alt+Ctrl+B that was asked for, and the reason
is Windows.** Windows turns Ctrl+Alt into AltGr, so Ctrl+Alt plus a letter is
a character rather than a shortcut. Measured with real keystrokes: Ctrl+B
arrives, Alt+Shift+B arrives, Alt+Ctrl+B fails three times out of three. The
menu would have shown the key and pressing it would have done nothing.

### Found while doing it

- **Two commands shared an id**, so the new key opened the send setup window
  instead of going live. The check that catches this has existed since 3.4.1
  and takes a second to run.
- **The menu mnemonic rule had become the thing stopping the menu growing.**
  It pooled a whole menu and its submenus into one namespace, stricter than
  Windows, and On air had 22 of 26 letters spoken for. It now matches how
  Windows really resolves a mnemonic: one namespace per open level.

## 3.8.1 for Windows, 12 September 2026

**A video recording now records what you are actually capturing.**

Tony, 12 September 2026: "when recording video, it should not send out a still
freeze frame of the radio show title... if visual streaming is being done, it
should default to what's being captured, camera + screen, just camera,
whatever is selected. none of this still frame of a radio show. that is
different. ice cast, shoucast, is not the same as facebook and youtube."

He was right, and the reason is the second half of that sentence. The picture
had quietly become a property of the video PLATFORM rather than a thing the
app owns, so a board set up to go live to a radio station recorded a card with
the station name on it, could not open the picture chooser at all, and was
told there was no picture when asked.

Measured against his own board before the fix: 175 frames in six seconds, mean
pixel difference from a freshly drawn card **zero**. Nothing anywhere reported
it, and a card is not a thing a blind presenter can see.

### What was wrong

**The capture was never started.** The recording built a picture source and
never called `start()`. Every capture runs on a thread behind that call, so
asking for a frame answered nothing for ever, and the card that stands in for
a failed camera stood in permanently.

**And a recording made while live built a SECOND pipeline.** The path meant to
share the frames the stream was already sending asked for an attribute that
does not exist, so it had never run once since it was written. A second
pipeline means a second camera, and a camera has one owner.

**The words on the picture had never once been drawn on a card.** On any path,
since 3.5.0. The card hands back a read only array, the overlay wrote in
place, and the error was swallowed on every frame. Measured off a real
stream: a lower third **1.33 grey levels** from a bare card, which is absent.
So anybody who set a lower third on the app's own default picture got a
picture with no words on it, while Ctrl+Shift+V read the words out.

### One picture, however many things are looking at it

There is now one picture pipeline, shared and reference counted. The stream,
the recording, the preview behind the shot check and the framing watcher all
take a hold on the same one, so there is one camera and one screen capture
however many of them are running. It starts when the first thing wants it and
closes when the last one lets go, so a preview can no longer close a camera
out from under a live show.

That is also what makes **Alt+Shift+V work during a recording**: the swap
happens inside the shared pipeline, so it reaches the file, the stream and the
shot check at once. It used to speak to the stream alone, so changing the
picture during a recording changed nothing in the file and said "next time you
go live".

### The picture stops belonging to Ctrl+B

Alt+Shift+V, Alt+Shift+T and Ctrl+Shift+V refused to work at all unless Ctrl+B
happened to be pointed at a video platform. A recording carries a picture
whatever Ctrl+B is pointed at, so all three are open now.

- **Alt+Shift+V** is titled **Picture** rather than Video source, its column
  says what is USING the picture rather than "On air", and it always offers
  the source you already have even if this machine cannot do it.
- **Ctrl+Shift+V** says which of the two it is describing, and names a
  recording rather than answering "Nothing".
- **Ctrl+Shift+W** now reads out the picture and what is using it, which is
  the one question nothing anywhere answered.
- The picture pre-flight runs for **Ctrl+Shift+R** as well as Ctrl+B, and its
  warnings name the recording rather than the stream. A stream you can
  restart; ninety minutes of a dark rectangle is gone.

### The file itself

**Every frame reaches it now.** The handover between the picture and the
encoder held one frame with no way to tell a new one from the one it already
had, and the two clocks beat against each other: measured by burning an index
into every frame and decoding the file back, **455 of 1800 pictures, 25.3 per
cent, never arrived**, with the same share of the file being duplicates. Six
of twelve single frame events vanished completely. Frozen frames in a real
recording are down from 14.4 per cent to **0.6 per cent**.

**And it is in sync.** Measured over a hundred seconds, decoded back with
every frame carrying its own capture time painted into the picture: offset
**2 ms**, drift **0.10 ms per minute**, delivered frame rate exactly 30.0000
with one distinct frame interval in the whole file.

**The encoder can keep up.** With a real moving picture to encode for the
first time, the old setting could not: 34.6 ms a frame against a 33.3 ms
budget, which backs the sound up and then deletes it. Measured across four
settings on a real recording, the new one is 17.9 ms a frame for a file about
one per cent larger.

**A recording that got no picture says so.** A file with nothing in the tap is
black, and every count in it is correct, so it reported itself as clean.

### Found on the way, all of them silent

- **No camera was ever offered to anybody who had not already chosen one.**
  The camera list raised an error into a swallowed except and answered "none",
  every time, for as long as it has existed. Only a board with a camera
  already saved in it hid the fault, which is why nobody saw it.
- **A failed picture recording tore down the sound recording.** One handler
  served both and knew about only one of them, so an ordinary disk fault on
  the MP4 abandoned the WAV mid write, said nothing about it, and left the
  show in neither file.
- **"The recording is losing audio" was worked out and thrown away.** It was
  only ever said at the end, which is an epitaph rather than a warning. The
  sound recorder never said it at all.
- **A stream dropping froze a recording's picture** for the whole outage, with
  every frame count, length and log still perfect.
- **A reconnect lost the shared frames** and would have frozen a recording's
  picture for the rest of the show.
- **A camera whose reader thread died could never come back**, so unplugging
  and replugging one, or another program letting go of it, left it dead for
  the session while the app politely retried a source that could not answer.
- **A camera that is not plugged in was blamed on another program**, so the
  advice was to close OBS over a camera that was not there.
- **The screen capture read its rectangle once**, so a monitor unplugged, a
  resolution change or a dock mid show kept capturing the old rectangle.
- **Moving the camera's corner rebuilt the whole pipeline**, closing and
  reopening the camera on every arrow key and freezing the window for up to a
  third of a second each time.
- **The shot check sent the whole desktop with no confirmation** whenever it
  was not on air, because it worked out camera or screen by looking at the
  live stream. A screen is confirmed every single time, and that is the rule
  it broke.
- **Compositing cost 41 ms a frame on the thread carrying the audio**, doing a
  resize that was not one: the picture already arrives at the size the encoder
  wants. It is 0.1 ms now.
- **The in app help named Ctrl+Shift+R twice where it meant Ctrl+Shift+W**, so
  following it started a video recording mid show.
- Both windows on the picture side now speak their detail as well as showing
  it, a short recording is no longer announced as "0 megabytes", and an audio
  only recording no longer claims to have a picture in it.

## 3.8.0 for Windows, 11 September 2026

**The cable can now be checked, and it tells you which device to pick at the
other end.**

Sending your show to another program means a virtual audio cable, and a cable
has two ends that Windows sets separately. Nothing in Windows keeps them in
step, nothing tells you when they disagree, and nothing anywhere will tell you
whether a single sample is actually arriving. All three of those are now
answered.

## Test the cable

A new button on the send page, Alt+Shift+O. It plays a tone down the cable,
records the other end of it, and tells you what came back.

That is the only question that matters and it is the one nothing could answer
before. A stream can look perfectly healthy and be losing audio: the fault
fixed in 3.6.0 was throwing away up to seven per cent of the show into a cable
while Windows reported no trouble at all, and it does not sound like dropouts,
it sounds like a slight change in pitch. Now you press a button and you get a
sentence.

Three things it can say. Nothing came back, and where to go and look. It came
back with holes in it, how much and how many. Or it is working, at this level,
listening on this device.

It refuses while you are on air or recording, because it would put a tone into
a call.

## Which device to choose in the other program

The two ends of a cable are named from the cable's point of view rather than
from yours, so the one called Input is a playback device and the one called
Output is a recording device, and everybody reads that backwards the first
time. Drop Deck now just says it:

> In the other program, choose CABLE Output as its input device.

On the send page while you are choosing the output, on Ctrl+Shift+O and on
Ctrl+Shift+W.

## When Windows has the two ends set differently

Both halves of a cable have their own sample rate and bit depth in Windows,
and nothing keeps them together. On this machine, in September, one end was
set to 48000 hertz 24 bit and the other to 192000 hertz 16 bit. It still
worked, because the driver converts, but it was converting twice for no reason
and carrying four times the data on the way back.

Drop Deck now notices and says so, with both numbers and where to change them.
Only for the device your show is going to: your headset has two ends as well,
and there is no reason on earth its two halves should match.

## Drop Deck Audio, on Windows, is coming

The Mac version of Drop Deck now installs a virtual audio cable of its own,
called Drop Deck Audio. Nothing to download, nothing to buy, one name in one
list.

**Windows will get it, and it is not in this release.** On a Mac a virtual
audio device is a plug in that lives in a folder. On Windows it is a kernel
driver, and a kernel driver has to be signed by Microsoft before Windows will
load it at all. That is a longer road than a release, and doing it badly is
how a free app starts tripping virus scanners.

So for now, Windows uses VB-CABLE, which is free and takes two minutes, and
everything above is about making that as painless as it can be. Drop Deck
Audio is coming to Windows.

## Also

- The send page now updates its advice as you change the output, rather than
  only when the page opens.
- Every check in the app runs against the real cable as well as against audio
  made by hand, which is what turned up the fault below.
- Fixed: the cable test could not open the sound card at all when it was run
  from the button, while the same measurement run any other way worked every
  time. Windows would not let a background job open a sound card without
  asking permission first, and reported it as an error about a completely
  different kind of driver.

## 3.8.0 for Mac, 11 September 2026

**Everything Windows gained between 3.6.0 and 3.7.1, and a virtual audio cable
Windows has not got.**

The Mac was four releases behind: 3.5.28 against 3.7.1. It is level now, and
it has one thing of its own.

## Drop Deck Audio, a cable that belongs to the app

Tony, 11 September 2026: "would it be too ambitious to create a custom Drop
Deck audio cable device like loopback? So, it's a specific wire customized to
Drop Deck only that when set to its input on Team Talk, Zoom, Skype, it will
automatically pick up on the audio from Drop Deck."

It was not too ambitious. **On air, Drop Deck Audio** installs a virtual audio
cable that comes with the app. After that it is in every program's microphone
list, called Drop Deck Audio, and the send is already pointed at it. Nothing to
download, nothing to buy, nothing to work out.

**The name is the feature.** Every other virtual cable is named from the
cable's point of view rather than yours, so the thing called Input is a
playback device and the thing called Output is a recording one, and everybody
reads that backwards the first time. There is one name here and it is in both
lists.

**What it really is.** An AudioServerPlugIn: two channels of 32 bit float at
44100 and 48000, transport type virtual, living in
`/Library/Audio/Plug-Ins/HAL` and loaded by Core Audio into a sandboxed helper
of its own. It began as Apple's MIT licensed `NullAudio` sample, whose licence
is kept beside the source and inside the bundle. What is ours is the ring
buffer that makes it carry audio instead of throwing it away, a silence guard,
and a seed that really moves.

**Exactly two channels, and that is a decision.** Zoom sums any input wider
than two to mono whatever its stereo setting says, so a cable with more would
arrive in a call as one ear of the show.

**Proved rather than assumed.** `--check-send` drives the real send through the
real cable and records the far end:

| | 48000 Hz | 44100 Hz |
|---|---|---|
| Gaps in eight seconds | none | none |
| Tone out, tone back | 1000.0 against 1000.0 Hz | 1000.0 against 1000.0 |
| Blocks dropped | 0 | 0 |
| Rebuffers | 0 | 0 |
| Idle, with nothing playing | peak 0.000000 | peak 0.000000 |

**That last row is the one that matters most and is the easiest to miss.** With
nothing feeding it, a cable made the obvious way goes on handing out the last
fraction of a second it heard, over and over, for as long as anybody stays
connected. It is a buzz that never stops and appears nowhere in the app. The
guard against it is six lines and there is a check that listens for it.

**The pitch is the measurement, not the gap count.** Audio that goes missing
takes whole cycles with it, so a tone with holes in it reads LOW: Windows
measured 1 kHz coming back as 974 Hz through a path that was losing three per
cent, which Tony had already described as "a change in pitch, a little
choppiness". A number is easier to argue with than a description.

**Installing it needs your password and restarts Core Audio**, which stops
every sound on the Mac for a second or two, VoiceOver included. The app says
that in words BEFORE it asks, and offers to skip the restart and let the cable
appear at your next login instead. There is no version of this that does not
need a password: the folder belongs to the system.

## Sending the show to another program

**On air, Send this show to another program, or `Option+Shift+O`.** The whole
show out of a sound card, for TeamTalk, Zoom, Discord or OBS on this machine.
Pads, beds, running order at full level, your microphone with its processing,
and every source you are catching. It does not need you to be on air or
recording.

Until now the only way was to point the main output at a cable, and that sends
the pads and the beds and **nothing else**: your microphone and every captured
program live on the mix that only exists while something is live. So the show
and the send were two different mixes and the one going to the other program
was missing the presenter.

**It can leave one source out.** Broadcasting calls this mix minus. If you
capture TeamTalk as a source and you are sending to TeamTalk, a send carrying
everything hands TeamTalk its own audio back and everybody in the call hears
themselves a moment late. Choose the source to leave out and everything else
still goes. If that source is later renamed or removed, `Command+Shift+O` says
so in as many words rather than letting a call full of echo be a mystery.

**`Command+Shift+H` puts the send in your own headphones**, exactly as it is
being handed over. A radio desk calls this a confidence feed. It goes to your
monitor output only and can never find its way back into the send.

**`Command+Shift+O` says whether it is arriving.** Where it is going, what it
is leaving out, whether it has had to rebuffer, and whether your output is
keeping up.

**`Command+Shift+W` reads out where everything is going**, on or off air: which
card your sounds play from, which card you listen on and whether it carries
everything, where the show is being sent and what it is leaving out, and
anything that is wrong with the arrangement. Three separate questions, one
answer.

**A card doing two jobs is refused, out loud.** Sharing one between the
programme output and a bank means that card carries the show twice, which the
far end hears as a strange hollowness rather than as an obvious fault. One
sound card doing everything is still perfectly legal, because that is what
almost every setup is.

## Hear yourself through, which did nothing at all

**Preferences, Microphone, Hear yourself through has existed since the
microphone landed. It was saved, it was carried across a File Open, and
nothing anywhere read it.** Monitoring came out of the main card every time. A
setting that does nothing is worse than no setting, because somebody who
cannot see it has no way to tell.

It is a real output now. And with it real, **what you hear carries every
card**: put a bank on a sound card of its own and you still hear it, through a
bus that costs forty milliseconds on that one path and nothing at all on the
ordinary one card setup.

## Recording the picture, Command+Shift+R

`Command+R` still records the sound alone. **`Command+Shift+R` records the
picture and the sound together**, into one MP4, and neither needs you to be on
air. It takes the same picture that would go out: if you are already live it
uses the identical frames the stream is sending, which costs almost nothing
and, more to the point, does not open the camera a second time.

**The sound is the master clock and the picture is fitted to it**, counted in
samples written to the file and never from a wall clock. A camera running slow
has a frame repeated; one running fast has a frame skipped; neither can move
the timeline.

Three things in the streaming code are right for a socket and wrong for a
file, and all three are different here. Frames are stamped as FRAMES at a time
base of one over the frame rate, so the file is constant frame rate rather
than the 33.312, 33.313 and 33.375 millisecond intervals milliseconds would
give. A missing picture repeats the last frame rather than returning, because
in a file that stalls the video timeline while the sound runs on. And the rate
control is an AVERAGE bitrate rather than the constant one the stream uses,
because a platform publishes a bitrate floor to pad up to and a file has none.

**A crash costs the last second, not the recording.** The file is fragmented
as it goes, so a three hour show that stops unexpectedly opens.

## A .cue track list beside every recording

Tyler McClain asked Windows for this and it arrives here at the same time.
`Drop Deck Stream 004.mp3` now gets `Drop Deck Stream 004.cue` beside it,
listing every running order track that went out and the moment it started.
Both recording keys write one. Hand the pair to Mixcloud and the track list is
already done.

Timestamps come from the recording's own sample count, never a wall clock,
because a machine that stalls makes the file shorter than the clock says. It
is written and flushed as the show goes, so a show that stops unexpectedly
keeps the track list for everything it got through. And pads are deliberately
not in it: a track list with forty sound effects in it is not a track list.

The format detail everybody gets wrong: `INDEX` is `mm:ss:ff` where `ff` is
seventy fifths of a second, not hundredths, so half a second is 38 rather than
50. **Python rounds halves to even and Swift rounds them away from zero**, so
the Mac put a track one frame later than Windows did on every 150th of a
second until the cross check caught it on its first run.

## What is coming up, Command+Shift+C

Everything ticked in the running order, top to bottom, draining as the show
runs. `N` says the next three in one sentence. `Return` crosses into the track
you are on. Your pads and every other key still work while it is open.

**The row you are standing on never moves**, and that is the load bearing
rule: removing the row under the cursor moves the selection, which is exactly
the event a screen reader reads from, so it would stop mid sentence and read
out a track you never chose, on air, at the moment a song changes. That one
row is held until you arrow off it.

## Holding a source back

Darrell, a listener: "when using external audio sources, there is some lag
there ... in obs, we can adjust the offset for the source, so it does not lag
as much."

A delay per source, in milliseconds, up to two seconds. It says plainly what
it cannot do: it can only ever make a source **later**, so a card running
behind the others is fixed by holding the others back. OBS works the same way
and it surprises everybody once.

## Opening a board brought most of it, not all of it

**Not one of the twenty two video settings was carried across a File, Open.**
From the day video landed in 3.5.2, opening a board loaded its picture, its
colours, its platform and its stream size correctly and then threw every one
of them away: you kept the PREVIOUS board's shot and the previous board's
destination, and the only sign was on the air.

The check that replaces it cannot fall behind: it builds a board with every
property set to something that is not its default, copies it, and compares the
two as the files they save as. A property left out fails it without anybody
having to remember to add a line.

## Also

- **F1 had gone eight keys behind.** Every key the video work added in 3.5.0
  and 3.5.2 was missing from it, which is the same rot Windows found. The list
  is now half hand written chapters and half derived from the keys the app
  really binds, and a check refuses a build where anything bound is missing
  from it.
- An unknown recording format used to become `.wav` quietly, so the first MP4
  this app ever wrote would have gone into a file called `.wav`. Found by a new
  check on its first run.
- Both recording keys now say what is really in the file when they start,
  including anything you can hear that is NOT on the air and therefore not in
  it. Monitoring is what you hear; a recording takes the on air mix.
- A recording that is losing audio says so. Nothing ever read that counter.
- Changing any output device while sending would have stopped the other
  program receiving audio, permanently and silently. It is the fault Windows
  measured at 57.7 per cent of the audio missing, and it is fixed here before
  anybody met it.
- A send whose card has stopped no longer reports itself as running.
- A send that a board file turns on at launch is announced, because a board
  deciding to hand this machine's whole show to another program is not
  something to discover later.
- NaN or Infinity in a board file would have loaded as +24 dB, a sixteenfold
  boost into somebody's call. It loads as 0.
- A source you named "My microphone" no longer shadows the real one.
- Preferences, Output now says what that output is and is not, because it is
  the page somebody hunting for "how do I get Drop Deck into Zoom" reads first
  and the answer is not on it.
- `Command+Shift+A` and the rest are spelled Command before Shift everywhere
  now. The manual and F1 have always said it that way and the code said the
  other, which nothing noticed because the manual checker normalises both.

585 checks, 0 failed. Twelve cross checks against the real Windows modules,
byte for byte identical. `--check-send` is the proof of the cable, and
`--dump-help` prints the F1 list so the derived half can be read rather than
taken on trust.

## 3.7.1 for Windows, 11 September 2026

**A .cue track list beside every recording.**

Tyler McClain, clarifying a request after 3.7.0 had already shipped the live
cue sheet window, which turned out not to be what he meant: "i'm talking about
adding the ability to let it write a .cue file with the title, artist, and when
it was played ... where people can have a .cue sheet right in the recordings
folder with the same file name, like if they want to post it to mixcloud."

So `Drop Deck Stream 004.mp3` now gets `Drop Deck Stream 004.cue` beside it,
listing every running order track that went out and the moment it started.
Both `Ctrl+R` and `Ctrl+Shift+R` write one. Hand the pair to Mixcloud and the
track list is already done.

Three things about it worth knowing. **Timestamps come from the recording's own
sample count**, never a wall clock, because a machine that stalls makes the
file shorter than the clock says and a list timed against the wall drifts away
from the audio it describes. **It is written and flushed as the show goes**, so
a show that stops unexpectedly keeps the track list for everything it got
through. And **pads are deliberately not in it**: a track list with forty sound
effects in it is not a track list.

The format detail everybody gets wrong: `INDEX` is `mm:ss:ff` where `ff` is
seventy fifths of a second, not hundredths, so half a second is 38 rather than
50. Minutes are not wrapped at sixty, or a long show restarts its own clock.

41 suites, 2560 checks, 0 failing.

## 3.7.0 for Windows, 10 September 2026

**The picture gets recorded too, there is a cue sheet, and a source can be
held back.**

Tony asked for the first, Tyler for the second and Darrell for the third, all
on the same day.

## Recording the picture, Ctrl+Shift+R

`Ctrl+R` still records the sound alone. **`Ctrl+Shift+R` records the picture
and the sound together**, into one MP4, and neither needs you to be on air. It
takes the same picture that would go out: if you are already live it uses the
identical frames the stream is sending, so it costs almost nothing.

**On sync, which is the whole feature, and which Tony cannot check by
watching.** The sound is the master clock and the picture is fitted to it.
Measured over three minutes of real recording, decoded back frame by frame
with each frame carrying its own capture time in the picture:

| | Clean | Camera unplugged for 8 seconds |
|---|---|---|
| Offset | 4.5 to 5.3 ms | 3.8 to 5.2 ms |
| Drift | **0.10 ms per minute** | 0.43 ms per minute |
| Delivered frame rate | 30.0000, one distinct gap | 30.0000, one distinct gap |
| Colour | BT.709, tagged | BT.709, tagged |

**Three things in the streaming code are right for a socket and wrong for a
file, and all three were caught before any of this shipped.**

The stream stamps frames in milliseconds because that is what its container
carries. In an MP4 that gives frame gaps of 33.312, 33.313 and 33.375 ms: a
variable frame rate file, which is a nuisance in an editor. Counting frames
instead gave 1348 of 1349 gaps exactly identical.

The stream pads to a bitrate because platforms publish floors. A file has no
floor. The same ten seconds: 7.62 MB padded, **2.20 MB at constant quality**,
and the smaller one looks better.

And the stream returns without sending anything when a frame is missing, which
is correct when a missed frame is simply not sent. In a file it stalls the
video timeline while the sound runs on. Measured on an eight second camera
outage: **the picture ended up 6.48 seconds ahead of the sound**, was still
0.48 seconds out sixteen seconds later, and nothing was dropped, no gap
appeared, every count was correct and nothing was logged anywhere. Here a
missing picture repeats the last frame, which is also cheaper.

**A crash costs the last second, not the recording.** Measured with the writer
killed outright eight seconds in: a plain MP4 survived 0.0 seconds and would
not open at all; this survives 7.0 of 8.0 and opens. It costs nothing in size.

**And the one that nearly shipped.** The first version of this drained audio a
quarter of a second at a time, copied from the audio recorder. That puts the
sound **257 milliseconds late in every single file**, against a detectability
threshold of 125 ms, and it survives every check the app has: the lengths
match, nothing is dropped, nothing is announced and the file plays. It only
shows up when somebody who can see watches it. Draining a frame at a time
instead brought it to the five milliseconds above.

## The cue sheet, Ctrl+Shift+C

Tyler: "almost a dialog list that shows what song is coming up next, from top
to bottom. songs will disappear after 10 seconds of instantly playing."

Everything ticked in the running order, top to bottom, draining as the show
runs. `N` says the next three in one sentence. `Enter` crosses into the track
you are on. Your pads and every other key still work while it is open, which
took carrying the whole keyboard map into the window.

**The row you are standing on never moves**, and that is the load bearing
rule. Removing a row above or below the cursor is completely silent. Removing
the row **under** it makes NVDA say a bare "not selected", then read out a
track you never chose, and "not selected" then sticks to every announcement
until you arrow again. That was measured with a live accessibility hook and
then confirmed against NVDA's own recorded speech. So that one row is held
until you move off it.

Two things it shows that the running order does not: a ticked track whose file
has gone is listed and marked rather than silently left out, and the last row
always says the running order ends.

## Holding a source back

Darrell: "when using external audio sources, there is some lag there ... in
obs, we can adjust the offset for the source, so it does not lag as much."

A delay per source, in milliseconds, up to two seconds. It says plainly what
it cannot do: it can only ever make a source **later**, so a card running
behind the others is fixed by holding the others back. OBS works the same way
and it surprises everybody once.

## And what Darrell actually ran into

He ticked "Hear it yourself" and his source was not in the recording.
Monitoring is what **you** hear; a recording takes the on air mix. That is the
right design and nothing anywhere said so. **Both recording keys now name what
is really in the file when they start**, including anything you can hear that
is not on the air.

## Also

- `Where is everything going` moved from `Ctrl+Shift+R` to **`Ctrl+Shift+W`**,
  so recording could have the key that pairs with `Ctrl+R`.
- An unknown recording format used to become `.mp3` quietly, so the first
  video recording wrote an MP4 into a file called `.mp3`. Found by the new
  check on its first run.
- A recording that is losing audio says so. Nothing ever read that counter.
- F1 was missing every key added since 3.5.0 and is now derived from the
  menus rather than hand kept.

41 suites, 2537 checks, 0 failing. `tools/check_recording.py` is the proof:
a real recording, decoded back, sync measured at five points across the run.

Designed by Tiffany and Jackson working the same problem from the picture and
the sound, and by Jessica, who disassembled NVDA's own shipped code to settle
what a screen reader really does when a list changes underneath somebody.

## 3.6.1 for Windows, source complete 10 September 2026, NOT YET RELEASED

**Where your audio goes, made into one idea, and three faults that were
destroying it in silence.**

Tony, 10 September 2026: "program out to the cable. build that."

**The main output is not your programme, and that is the whole of the
confusion.** It carries your pads, your beds and your running order. Your
microphone and every source you catch are not on it. Measured with the banks
on one card and the monitor on another: the banks' card carried the pads and
no microphone, and the monitor carried the microphone and no pads. **Neither
output had the whole show.** So pointing the main output at a cable gives the
other program a soundboard with no voice on it, and leaves you unable to hear
your own soundboard.

**`Ctrl+Shift+R` reads the whole routing out**, on or off air: which card your
sounds play from, which card you listen on and whether it carries everything,
where the show is being sent and what it is leaving out, and anything that is
wrong with the arrangement. Three separate questions, one answer.

**What you hear now carries every card.** Put a bank on a sound card of its
own and you still hear it, through a bus that costs forty milliseconds on
that one path and nothing at all on the ordinary one card setup.

**A card doing two jobs is refused, out loud.** Sharing one between the
programme output and a bank means that card carries the show twice, which the
far end hears as a strange hollowness rather than as an obvious fault. One
sound card doing everything is still perfectly legal, because that is what
almost every setup is.

## The three faults

**Any output device change killed the send, permanently, and said nothing.**
Change a device in Preferences while sending, and the other program stopped
receiving audio and never got it back until the send was switched off and on.
Two causes at once: the system default output was given a new bus name on
every rebuild, orphaning its buffer, and a buffer was marked alive whenever
anybody LOOKED at it rather than when audio was written to it, so an orphan
holding a part block stayed alive for ever with a number too small to serve.
Recorded off a real cable: 57.7 per cent of the audio missing, one gap 8.4
seconds long and still going. It also leaked about 1.15 MB per device change,
and it reached the recorder the same way. After the fix, the same test: zero
gaps.

**Muting or soloing anything while sending took your voice off the send.**
Every Mute and Solo asked whether something was live or recording. A send is
neither. So one press of Space in Source Control during a call removed the
presenter, and unmuting did not put them back.

**A monitor output that would not open sent your microphone wherever bank 1
was pointed.** With bank 1 on a cable, that is into the call. The message said
your audio had gone to the default output, which was not where it went.

## Also

- A send whose card has stopped no longer reports itself as running.
- A send that starts at launch is announced, because a board file decides it.
- `Ctrl+Shift+O` moved to the channel that speaks at every speech level. It
  has no other effect, so it was a dead key for anyone who had turned the
  talking down.
- The On air menu shows whether you are sending and whether you are hearing it.
- With no virtual cable on the machine, the send no longer quietly picks a
  loudspeaker and calls that success.
- NaN or Infinity in a board file loaded as +24 dB, a sixteenfold boost into
  somebody's call. It loads as 0 now.
- A source you named "My microphone" no longer shadows the real one.
- The Output preferences page said "Pick a virtual cable here to feed a stream
  while you keep listening on your own speakers." That was false of the
  control it sat under. So did GETTING-STARTED.txt, under the exact heading
  somebody hunting for this feature would read first.
- F1 was missing eight keys the menus advertise, including everything added
  since 3.5.0, and taught the pre 3.6.0 wiring. That list is now derived from
  the menus rather than hand kept, so it cannot fall behind again.

40 suites, 2492 checks, 0 failing. Found by Jackson, Mark and Ryder, who were
pointed at the routing and told to break it.

## 3.6.0 for Windows, source complete 9 September 2026, NOT YET RELEASED

**Your show, out to another program on the same machine.**

**On air, Send this show to another program, or `Alt+Shift+O`.** Point it at a
virtual audio cable and set TeamTalk, Zoom, Discord or OBS to take the other
end of that cable as its microphone. It sends the whole show: the pads, the
beds, the running order at full level, your microphone with its processing,
and every source Drop Deck is catching. Your speakers keep working, because
the send is an output of its own rather than a re-routing of the one you
listen on, and it does not need you to be on air or recording.

Until now the only way to do this was to point the main output at a cable,
and that sends the pads and the beds and **nothing else**: the microphone and
every captured program live on the mix that only exists while something is
live. So the show and the send were two different mixes, and the one going to
the other program was missing the presenter.

**It can leave one source out.** Broadcasting calls this mix minus, and it is
the setting that matters most. If you capture TeamTalk as a source and you are
sending to TeamTalk, a send that carried everything would hand TeamTalk its
own audio back and everybody in the call would hear themselves a moment late.
Choose the source to leave out and everything else still goes. If that source
is later renamed or removed, `Ctrl+Shift+O` says so in as many words, rather
than letting a call full of echo be a mystery.

**`Ctrl+Shift+H` puts the send in your own headphones**, exactly as it is
being handed over. A radio desk calls this a confidence feed. It goes to your
monitor output only and can never find its way back into the send.

**`Ctrl+Shift+O` says whether it is arriving.** Where it is going, what it is
leaving out, whether it has had to rebuffer, and whether your ordinary output
is keeping up.

**And the fault that made all of this worth doing.** Every output this app has
ever opened asked its sound card for a fixed block of 512 frames. On a real
sound card that is fine. Into a virtual audio cable it loses audio, and it
does it silently.

Measured on a real cable, ten runs at each size, counting how much of a tone
never reached the far end:

| Output buffer | Runs that lost audio | Median lost | Worst |
|---|---|---|---|
| 512, what shipped | 7 of 10 | 2.67 per cent | 7.39 per cent |
| 1024 | 6 of 10 | 0.06 per cent | 0.74 per cent |
| 2048 | 0 of 10 | none | none |
| Let the card choose | 0 of 10 | none | none |

About six gaps a second, four milliseconds each, and a 1 kHz tone came back
reading 974 Hz on a cycle count. Reported by Tony as "a change in pitch, a
little choppiness" going into TeamTalk, which is exactly what a few per cent
of missing audio sounds like.

**PortAudio reported a perfectly healthy stream throughout**, which is why
nothing ever said so. Outputs now ask the card for whatever suits it, which
costs no extra latency at all, and Drop Deck times its own callback rather
than taking the driver's word for it.

**If the pitch still wanders, check both ends of your cable.** CABLE Input
under Playback and CABLE Output under Recording are separate settings in
Windows and it does not keep them in step. Set both to the same sample rate.

`tools/check_send.py` is the proof: a real send into a real cable, recorded
off the other end. Twenty seconds, no gaps at all, and the excluded source
107.7 dB down.

39 suites, 2454 checks, and the only one failing is a webcam brightness
check that wants the room lit.

Source complete and every check that does not need a lit room passes. Not built, not signed and not
released: `APP_VERSION` stays at 3.5.2 until the installer exists, because
an app claiming a version the feed cannot serve answers "you have the newest
one" for ever. `tests/test_version_separation.py` is what enforces that, and
it is what caught the bump being made too early here.

## 3.5.28 for Mac, 8 September 2026

**Two things a source could still get away with.**

**A source set to capture a program that is not running says so before you go
live.** From macOS 26 the capture for a program can be made before that
program has started, and it waits for it. That is the right behaviour, and it
is also a brand new way for a source to pass every check in the app and still
send nothing: the capture is healthy, the program simply is not there. Every
other kind of silent source is now caught, so this one is too.

**The channel popup no longer lies to a screen reader.** For a captured
program it sat dimmed on "Both, mixed together (a microphone)". Dimmed does
not read as "does not apply" to somebody hearing it aloud, it reads as the
setting in force, and since 3.5.27 that is the opposite of what happens: a
captured program is always kept in stereo. It says stereo now. The choice the
source has as a device is left untouched underneath, so switching it back to
a device brings the real one straight back instead of quietly becoming
stereo.

498 checks, 0 failed. All nine cross checks against the Windows modules remain
byte for byte identical.

## 3.5.27 for Mac, 8 September 2026

**A captured program goes out in stereo.**

Reported by Tony: "Logic's audio was in mono when coming through YouTube."

All of it was. Every captured program, for everybody, and the panel would not
let you change it, because the channel popup is switched off for a program.

The board's channel setting is meant for a device. A microphone on one leg of
a stereo interface has to be mixed or picked, and the default is "both,
mixed together", which is right for a microphone and wrong for everything
else. It was being applied to captured programs as well, so a stereo mix
arrived flat.

There is nothing to choose for a program. The tap is already a stereo mixdown
of that program's own output, so both channels are exactly what it is
playing. They are kept as they are.

**This is what Windows does too, though it gets there by accident.** Its
channel setting only ever reaches a device input, because a program source
uses a different capture class that has no channel attribute at all. The Mac
applied it to both.

A capture with more than two channels is now read frame by frame rather than
as if it were interleaved stereo, which an aggregate device clocked by a
multi channel interface would have handed over as noise.

**Help, Check my audio sources now says whether each source is really in
stereo.** A level meter cannot show you that: mono is two identical numbers
and looks exactly like a healthy signal. Measured on Tony's Mac, Logic Pro
now reads "in stereo, the two channels differ" and VoiceOver reads "the same
in both ears", which is correct, because VoiceOver speech is mono unless its
3D sounds are switched on. Nothing folds it any more, so when they are on it
goes out in stereo.

496 checks, 0 failed. All nine cross checks against the Windows modules remain
byte for byte identical.

## 3.5.26 for Mac, 8 September 2026

**Your stream key is remembered again.**

Reported by Tony: "seems like I have to go get a new stream key every single
time."

The key was filed in the keychain under the radio station's name. That is the
wrong name for it. A station name can be changed, and loading a saved setup
could clear it, and once it was cleared the key was still sitting there with
nothing able to find it. From outside, that is indistinguishable from the app
forgetting the key, and the only way back on air is to go to the platform and
fetch a fresh one.

On Tony's own machine the key was under "Tony's Tunes" while the board's
station name had become empty, so the app was looking under "youtube" and
finding nothing.

It is now filed under the platform. YouTube and Facebook each keep their own
key, and moving between them brings the right one back instead of overwriting
one with the other. A key left under an old station name is carried across the
first time it is needed, and the old entry tidied away.

**It is never guessed at.** A key the board does not name is left alone, even
when it is the only one there. Adopting it would mean somebody who switches
from YouTube to Facebook has their YouTube key silently become their Facebook
one, and the original deleted. A guess that moves a key is a guess that can
lose one.

488 checks, 0 failed. All nine cross checks against the Windows modules remain
byte for byte identical.

## 3.5.25 for Mac, 8 September 2026

**Your extra audio sources really go on the air now. They never could.**

Reported by Tony, who added two sources, VoiceOver and Logic Pro, went live,
listened to the stream on his phone and heard neither of them. Only the
built in microphone was there.

**The capture was never made.** A source set to capture a program asked Core
Audio for a tap. Core Audio answered `noErr`, success, and handed back tap
object zero. Nothing threw, nothing was logged, the source reported itself
running, its On air box was ticked, and it sent silence. From where the
presenter sits this is invisible, because they go on hearing the program in
their own ears whether or not it is going out.

The way the tap was being asked for was the problem. A `CATapDescription` was
made empty and the program set on it afterwards. That form is refused, and
refused silently. Measured on the machine rather than reasoned about, by
building every form there is and reporting which ones make a tap and which
ones actually carry sound:

    init(stereoMixdownOfProcesses:)                  tap, sound
    init(stereoMixdownOfProcesses:) + bundleIDs      tap, sound
    init(stereoMixdownOfProcesses: []) + bundleIDs   tap, sound
    CATapDescription() then set bundleIDs            NO TAP
    CATapDescription() then set processes            NO TAP

The last two are what shipped. It is now asked the way that works, and both
of Tony's sources are proven on the air on his own machine: **VoiceOver at
minus 25 decibels, Logic Pro at minus 12**, measured through the app's own
path with a second independent tap running alongside to confirm the numbers.

**Three more faults of the same shape went with it.**

Adding a second source no longer inherits the program the source above it
uses. The program list only ever set itself when a source already had a
program, so a new one silently kept the previous row's choice and then saved
it. That is how one of Tony's two sources came to point at the wrong program.
There is a "not chosen" entry now, exactly as the device list has always had.

A program a board names stays in the list even when it is not running, so
opening the panel and pressing OK can no longer throw that choice away.

A source whose interface is unplugged now says so instead of quietly opening
the built in microphone instead. Falling back to the default input is right
for the microphone and wrong for a source: a source pointed at a mixer on a
desk would become the laptop lid, sound perfectly healthy, and put the wrong
thing on the air. Windows has always refused this, in the same words.

Two copies of Drop Deck no longer stop each other capturing the same program.
The capture device was named after the source, so the second copy collided
with the first and got `kAudioHardwareIllegalOperationError` with no
explanation.

**And nothing was watching.** The reason a silent source survived a whole
broadcast is that the only place in the app that ever asked whether a source
had started was the sources panel, and only on the way out of it. Now:

- Sources that will not open are said out loud when the app opens, when a
  saved setup is loaded, and again in the going live check. Windows has said
  this since it had sources; the Mac never did.
- A source that is not ready is tried again every few seconds, so a program
  you start after going on air comes on by itself and says so.
- **Help, Check my audio sources** listens for six seconds and tells you in
  words whether each source is really putting sound out, and if not, which
  kind of nothing it is: a program that is not playing, or audio arriving and
  being lost. It reads meters rather than the audio itself, so it is safe to
  run in the middle of a show.
- `--check-sources` and `--tap-probe` do the same from a terminal, with the
  measurements printed.

Guarded by a self test that creates a real tap on this machine and fails if
Core Audio hands back nothing, and by one that checks the refused form is
still refused, so if a future macOS starts accepting it we find out rather
than the knowledge going stale. 480 checks, 0 failed. All nine cross checks
against the Windows modules remain byte for byte identical.

## 3.5.24 for Mac, 8 September 2026

**It has stopped telling you your picture has frozen when it has not.**

Reported by Tony, on the air, being told every forty five seconds that the
picture was stuck on one frame while it was perfectly fine.

**A screen that is not changing is not a broken screen.** The check that
notices a dead picture works by comparing each frame with the one before it
and calling them being the same a fault. That is exactly right for a camera,
where identical frames mean something has stopped. It is exactly wrong for a
desktop, where identical frames mean nobody has moved the mouse.

Measured on Tony's own setup, which is his screen with the camera in the
corner: the average difference between one frame and the next was **0.000**,
and every single sample read as frozen.

So a screen is no longer judged by its pixels. A capture that has really
stopped is noticed the way it always was, by the capture itself going quiet,
which is a separate and reliable signal.

**The camera is still watched, on its own.** On a shared screen the camera is
about a sixteenth of the picture, so asking the whole frame whether anything
moved gets the answer "no" whatever the camera is doing. It now has its own
watcher looking at the camera alone, and it says "the camera has frozen"
rather than "the picture has frozen", because when only the inset has stopped
the second one is not true.

**A black picture is still reported from any source**, because a black picture
going out is a black picture going out, whatever is making it.

Nothing else changed.

## 3.5.23 for Mac, 8 September 2026

**Going live to YouTube works. It could not, and it sat there saying
"connecting" for ever.**

Reported by Tony, who pasted his stream key in and pressed Command B.

Two faults, both found by pointing the app at YouTube's real ingest instead of
at the test server.

**RTMP does not put a message on the wire in one piece.** It cuts it into
chunks and puts a header byte in front of every piece after the first, and
until the server says otherwise those pieces are 128 bytes long. So YouTube's
answer to a connection, `NetConnection.Connect.Success`, arrives as
`NetConnection.Conne`, then a header byte, then `ct.Success`. The app was
looking for that name in the bytes as they arrived, which finds it only when a
reply is short enough to fit in one chunk. The test server's replies are.
YouTube's are not. So the app connected perfectly well, YouTube said yes, and
the app never saw the yes.

**And YouTube never says the stream has started.** Not before the metadata,
not after an audio header, not at all: measured, twelve seconds of silence.
The app was waiting for it, so even once it could read the reply it would have
waited for a message that was never coming. Restream does send it, which is
why that one would have worked and the other two never could.

Both are fixed the way a real encoder does it: the chunks are put back
together properly, and saying "publish" is followed by SENDING rather than by
waiting for permission. A platform that refuses still refuses, and the app
notices and comes off air, because it now listens for that on every pass
rather than once at the start.

**There is a new check that talks to the real thing.**
`mac/tools/check_ingests.py` reaches YouTube, Facebook and Restream with a
deliberately fake key and proves each one answers, sending nothing
broadcastable. The old check, which decodes a whole broadcast frame by frame,
passed throughout: a test server behaves like the code that was written to
talk to it, and that is exactly what it cannot catch.

**Also:** when the screen comes back black the app now names both causes, the
permission and the VoiceOver screen curtain, rather than only the first.

## 3.5.22 for Mac, 8 September 2026

**Drop Deck now asks for the permissions it needs, which it never did.**

Reported by Tony, who went to System Settings to allow the camera by hand and
could not find Drop Deck in the list.

He was not looking in the wrong place. **An app does not appear under Camera,
or under Screen and System Audio Recording, until it has ASKED**, and Drop
Deck never asked. It only ever looked: it read whether it was allowed, which
prompts nobody and registers nothing. So the prompt never came, the app was
never listed, and there was nothing to switch on.

Now it asks, in the two places that matter.

**When you first use one.** Choosing a camera as your picture asks for the
camera. Choosing your screen asks for the screen. That is the moment somebody
has actually asked for the thing, which is when a system dialog makes sense.

**And on the way in.** If your board is set to go to a video platform and its
picture is a camera or your screen, Drop Deck asks at launch, once, so the
answer is settled while nobody is waiting. A board pointed at a radio station
with a card for a picture is asked nothing, which is most boards.

**Help, What Drop Deck is allowed to do** is the third way. It lists the
microphone, the camera and screen recording with what each is for and whether
it is allowed, asks for any of them on Return, and opens System Settings at
the right pane. It says the whole state out loud as it opens.

**And it no longer believes macOS over its own eyes.** There is a system call
that says whether the screen may be captured, and it can answer yes while
every captured pixel is black, which happens when the grant was recorded
against an older build of the app. Drop Deck now trusts what it actually
captured: one blank capture and it says the screen is not allowed, puts itself
in the list, and tells you where the switch is.

Two things worth knowing, both of them macOS rather than this app. **It only
ever asks once**, so anything already refused has to be turned on in System
Settings. And **screen recording needs the app quit and opened again** after
you switch it on.

Nothing else changed.

## 3.5.21 for Mac, 8 September 2026

**You can paste again. You could not paste at all, anywhere, and that is not
an exaggeration.**

Reported by Tony within minutes of 3.5.2 going out, trying to put a stream key
into the box that asks for one.

**The app had no Edit menu**, and on a Mac that menu is not decoration. It is
what supplies `Command+V`, and `Command+C`, and `Command+X`, and
`Command+A`, and `Command+Z`. A text field does not implement those keys
itself: it implements paste and waits to be sent it, and the only thing that
sends it is a menu item carrying that key. With no Edit menu there was nothing
to send it, so nothing in the whole app could be pasted into. Not the stream
key, not a station name, not a password, not a track title, not a source name.

It has been that way since the Mac copy was written. It went unnoticed because
everything before this release could be typed, and a stream key is the first
thing this app has ever asked for that nobody types by hand.

`Command+V` was doing something else entirely: it was wired straight to
**Paste songs from the clipboard**, so pressing it in a text box tried to add
files to your running order.

Now there is an Edit menu with Undo, Redo, Cut, Copy, Paste, Delete and Select
All, and every one of them goes to whatever has the focus. In a box, they
work on the text. **Pasting songs still answers to `Command+V`** when the
running order has the focus, which is how a Mac is supposed to behave: the
same key, and what it does depends on where you are.

Nothing else changed.

## 3.5.2 for Mac, 8 September 2026

**The Mac catches up. Everything Windows gained between 3.4.0 and 3.5.2
arrives at once, and the two copies share a version number again.**

**Your show goes out on YouTube, Facebook, Restream or any RTMP server.**
Pick a platform on the new Video streaming page, paste your stream key, press
`Command+B`. Your radio station is still on its own page and `Command+B` goes
to whichever one you tick, which you can now see and change on the On air
menu under Streaming location.

**Something has to be on the screen**, because YouTube will not take sound on
its own. A card with your station name and whatever is playing is the default.
Your own artwork, a camera, your screen, and your screen with the camera in
the corner are the others. `Option+Shift+V` changes it, on air, without
dropping the stream, and the camera corner is yours to choose.

**Things can go on top of the picture.** `Option+Shift+T` gives you four
named places: a top strip, a corner, a lower third and a clock. Each can show
nothing, your station name, what is playing, the time, your own words, or a
text file that is re-read a second after it changes, so anything else on this
Mac that writes a text file can drive your screen.

There is no canvas and there are no coordinates, and that is the point. Four
places that are already the right size and cannot land on top of each other
can be checked without looking, because the answer to "what is on screen" is
four lines long.

**`Command+Shift+V` says what is on screen.** The picture, and everything on
top of it, in words. On air or off.

**`Command+Shift+F` says what the camera can see.** In shot or not, centred,
close enough, lit. It says changes rather than states, so it is not a running
commentary, and it answers whether or not the announcements are turned on.

**`Option+Shift+D` asks something that can see.** One still of the picture
going out, to Claude, ChatGPT or Gemini, on your own account, and it reads
back what a sighted person would have noticed: framing, whether the top of
your head is cut off, whether the light behind you is brighter than your face,
what is behind you, and whether the words on screen are sitting across your
chin. There is a question box under the answer, and it remembers the
conversation.

On a screen share it looks for anything private, and says where it is.

Three things it does not do. **It is never needed to go live, and going live
never waits for it. It never sends a picture of your screen without asking,
and it asks every single time.** And it never fails loudly.

**`Option+Shift+C` is your own colours, chosen without having to see them.**
The background, the words, and an accent for the rule and the edges. Ten
ready-made looks, every one checked against the numbers rather than picked by
eye, and every colour says how it will read: "gold, easy to read, 8.6 to 1".
Nobody is asked to imagine a swatch.

There is also a **This look** box that says the whole brand at once, and a
button that asks a model what your branding actually looks like to a sighted
viewer. That is the only question in this app that arithmetic genuinely
cannot answer.

**`Command+B` says what it is about to do, and waits.** Where the show is
going, what it is sending, what will be on the screen, and whether your
microphone is on the air. Then Return puts you live. It also checks, and that
is the half worth having: a microphone left off the air, a picture file you
have moved, no camera chosen, a bitrate the platform will refuse, track
titles turned off, or the wrong one of the two destinations ticked. A box
turns the asking off for good, and Preferences turns it back on.

**Source control works the way a Mac works.** Muted and Solo are check boxes,
Rename and Remove are buttons, and the old left and right mode is gone.

**Your stream key is kept in your keychain**, not in the board file. Anybody
holding a YouTube key can broadcast to your channel, and a board file is
plain JSON that people send each other.

**Two faults found and fixed while building this, both of which shipped in
3.3.2.** Renaming a source was broken: the source control panel went on
claiming the keyboard while its own rename box was open, so a digit typed
into a name jumped the list behind it and Space opened a second box, which
meant a name with a space in it could not be typed at all. And Return did
nothing in every panel that puts your focus on what it has to say, which
includes the update panel, where Return was supposed to mean Update.

**The download grew by about one megabyte**, which is the two font files. The
picture, the camera, the screen, the encoder and the face detection are all
macOS itself. For contrast, OBS is 390 MB.

Nothing about the soundboard, the running order, the keyboard or your radio
station streaming has changed. The digit map is untouched.

## 3.5.2, 8 September 2026

**The camera can go in any corner.** When your screen is what is going out,
**Alt+Shift+V** now has a **Camera corner** choice: bottom right, bottom left,
top right or top left. It moves while you are live, and it is worth having
because your screen has its own furniture and some platforms put a chat panel
over one corner.

**You can ask questions about your shot.** The shot check window has a
question box under the answer. Ask "is the plant behind me distracting", or
"can you read the lower third", and it answers about the same picture it just
described. It remembers the conversation, so "what about the other side" means
something.

**And the colours window can tell you what your branding actually looks
like.** Two new things there. **This look** is a box you can tab to and read a
line at a time, saying the whole brand at once rather than one row of it.
And **What does this look like to a sighted viewer?** asks a model to look at
a rendered sample and give you a real opinion: warm or cold, deliberate or
accidental, what kind of station it would suit and what it would suit badly.

That last one is the only question in this app that arithmetic genuinely
cannot answer. Contrast numbers tell you a pair can be read. They cannot tell
you it looks like a 1990s news broadcast. There is a question box there too.

## 3.5.1, 8 September 2026

**You can check your shot before you go live, which is when checking is any
use.** `Alt+Shift+D` used to need the stream already running, so the answer to
"how does my shot look" was "go on air and find out". It now builds the
picture, looks at it, and puts it away again.

**And it looks at the right picture.** If Ctrl+B was pointed at your radio
station rather than a video platform, the check quietly described a card
instead of whatever you had chosen. It never said so. Both are fixed, and what
it describes now includes your station name and the other words on screen, the
way a viewer sees them.

**The update has a progress bar, and it talks.** It says the percentage as it
climbs rather than only drawing a bar nobody can see, and there is a Stop
button that really stops.

**And the app reopens after an update, which it has been promising and not
doing.** The installer was told to skip the "open the app" step whenever it
ran without a wizard, which is exactly how the app installs its own updates.

**The AI page is easier to fill in.** It is called **AI Provider** now. The
model is a list you can arrow through instead of an empty box, with a **Get
the list** button that asks your service what it can really see, because model
names change faster than this app ships. And your own artwork gets a **Browse**
button rather than a path you were expected to type from memory.

## 3.5.0, 8 September 2026

**Things can go on top of the picture now, and the app will tell you what is
on screen.**

**`Alt+Shift+T`, or On air, Screen text.** Four named places, and each one can
show nothing, your station name, what is playing, the time, your own words, or
a text file:

| Place | Where it is |
|---|---|
| Top strip | across the top |
| Corner | top right |
| Lower third | bottom left |
| Clock | bottom right |

Up and down read them, Enter chooses what one shows, Delete empties it. It
changes while you are on air.

**A text file is re-read a second after it changes**, which is exactly how OBS
does it, so anything else on your computer that writes a text file can drive
your screen.

**There is no canvas and there are no coordinates, and that is the point.**
Putting something at an exact position is the easy half. Knowing whether it
looks right is the half that needs eyes, and it is why every guide for blind
streamers ends with "get a sighted person to lay it out once". Four places
that are already the right size and cannot land on top of each other can be
checked without looking, because the answer to "what is on screen" is four
lines long.

**`Ctrl+Shift+V` says what is on screen.** The picture, and everything on top
of it, in words. On air or off. Nothing else in broadcasting does this: OBS's
preview is a graphics surface with no accessibility information at all, on any
platform, so there is nothing anywhere that will tell the person making a
stream what is currently in it.

**It tells you when the picture dies.** Camera unplugged, screen gone black,
capture stuck on one frame. It says so once, after a few seconds so a blink
does not set it off, and says when it comes back. OBS has never had this and
people have asked for it on their forums for years.

**Going live checks the text fits.** A title too long for the lower third is
said before you connect rather than discovered by somebody watching.

**Check my shot: ask something that can see.**

`Alt+Shift+D`, or On air, Check my shot. It sends one still of the picture
going out to Claude, ChatGPT or Gemini, on **your own account**, and reads
back what a sighted person would have noticed. Framing, whether the top of
your head is cut off, whether the light behind you is brighter than your
face, whether your shirt blends into the wall, what is behind you, and
whether the words on screen are sitting across your chin.

It answers with a verdict first, then the details worst first, then one line
saying the single most useful thing to change.

**On a screen share it looks for anything private**: an inbox, a password
manager, a notification, somebody's address. It says where it is so you can
close it.

Three things it deliberately does not do. **It is never needed to go live,
and going live never waits for it.** **It never sends a picture of your
screen without asking, and it asks every single time**, because a yes about
one screen is not a yes about the next. **And it never fails loudly**: if
the service is down or the key is wrong it says so in a sentence and the
show carries on regardless.

Set it up in Preferences, Shot check: choose who to ask and paste your key.
The key is kept in Windows Credential Manager, not in your board file, so a
board you send to somebody else does not carry it.

**And your own colours, chosen without having to see them.**

`Alt+Shift+C`, or On air, Colours. Three things: the **background everything
sits on**, the **words**, and an **accent** for the rule under your station
name and the line round the camera inset. Ten ready-made looks are offered
first, and every one was checked against the numbers rather than picked by
eye.

**Every colour tells you how it will read.** Arrow through the list and each
one says what it does against what it will sit on: "gold, easy to read, 8.6
to 1", or "light green, too close together to read, 2.2 to 1". Nobody is
asked to imagine a swatch.

That number is not decoration, and it turns out to matter more for video than
for anything else. Measured through the real encoder: **the colour pairs that
H.264 destroys are exactly the pairs that score badly.** Video stores colour
at half the resolution of brightness, so a pair whose difference is all hue
has nothing left after encoding. Red on blue came back as coloured mush, and
it had no brightness difference to begin with. One number catches both the
unreadable and the unencodable.

**The background really does sit under everything**: the card, the panels
behind the words, and the bars either side of a camera or a screen that does
not fill the frame. Those bars were a fixed dark grey before, which is the
difference between a letterboxed shot looking deliberate and looking broken.

**And a colour fault that has been going out on every stream.**

Two things were wrong in how the picture was converted and labelled, and
neither of them raised anything. The picture was being converted with the
**standard definition** colour formula and then sent at high definition, so
reds and blues were shifted from what they should have been. And it carried
no label saying what it was, which left every viewer's player to guess. A
wrong guess is what makes a stream look washed out, or too dark and heavy.

Both are fixed and both are now checked by encoding a real stream and reading
the colours back out of it. **Nothing needs to be set. Streams will simply
look right**, and closer to what the colours above promise.

**Coloured lines are drawn a touch differently too.** A coloured line an odd
number of pixels high straddles the blocks video stores colour in, and loses
about a third more of its colour than an even one. The rule under your
station name was landing on the worst case at the commonest picture size.

**And the card got real letters.** It was drawn in a hand-made font of five by
seven blocks, capitals only, because that needed no font file. It is Roboto
now, and so is everything above.

The download grew by about three megabytes. For contrast, OBS is 390 MB, and
275 MB of that is a complete copy of Chrome, which is what every animated
overlay in that world actually is. None of it is here.

Nothing about the soundboard, the running order, the keyboard or the sound
going out has changed. The digit map is untouched.

## 3.4.3, 8 September 2026

**Source control works the way Windows works.**

`Alt+Ctrl+Shift+S` still opens it and up and down still choose a source.
What changed is everything after that.

**Muted and Solo are check boxes now.** Ticked means muted, or soloed;
unticked means it is going out. A check box says what it is the moment you
land on it, without being asked, and Space toggles it the way Space toggles
every check box in Windows.

**Rename and Remove are buttons.** Rename opens a box with the current name
ready to type over. Remove asks whether you are sure before anything goes.
`F2` and `Delete` do the same two things from the list, as they do everywhere
else in the app.

The old left and right arrows cycled between the four, and Space did whichever
one you had landed on. That is a mode: something to remember, and something
the window had to keep telling you because nothing on screen said which of the
four you were on. It is gone.

The microphone's buttons are unavailable rather than missing, and the line
under the list says why: it cannot be renamed or removed, and `Ctrl+M` turns
it off. It can still be muted and soloed from here, which is what makes solo
work in both directions.

## 3.4.2, 8 September 2026

**You can see where Ctrl+B is going to send the show, and change it.**

**On air, Streaming location** lists both places with a dot beside the one
`Ctrl+B` will use:

- **My radio station**, with its name and address
- **My video platform**, with the platform name

Pick one and it says where `Ctrl+B` now goes. That is the whole feature, and
it should have been there when video arrived.

Until now the choice was a single box on the Video streaming page of
Preferences, reading "Go live here when I press Ctrl+B". So the answer to
"where does my show go" lived on the page for one of the two answers, and a
board with a radio station and a YouTube channel both set up gave no sign
anywhere that there was a choice to make. The box is still there and still
works; the two move together.

**And it stopped saying "Icecast, or Liquidsoap harbor" every time.**

That string exists so the Server list in Preferences can tell you which entry
covers your server, which is the right thing to say there. On the way to air
it was nine words to say "Blindside Radio". It uses the name you gave your
station now, and only falls back to the software when you have not named it.

**Saved setups moved into Load a saved setup**, inside the same menu. They
are a different question from the two above: a saved setup carries both
Preferences pages and where it goes, so loading one can move the show from
your radio station to your video platform. It says so when it does, which it
did not before.

**A setup saved before 3.4.0 no longer blanks your destination.** Those were
saved before there were two places to send a show, so they carry no answer to
the question, and loading one was copying that nothing over the top of your
choice. Now it keeps what you picked.

Nothing about the soundboard, the running order, the keyboard or what goes out
has changed. The digit map is untouched.

## 3.4.1, 8 September 2026

**Ctrl+B tells you what it is about to do, and waits.**

Where the show is going, what it is sending, what will be on the screen, and
whether your microphone is on the air. Then Enter puts you live, so it is one
extra keypress and you hear all of it on the way past. A box in the window
turns the asking off for good if you would rather not have it, and Preferences
turns it back on.

It also checks, and this is the half worth having. Nearly every way of getting
a broadcast wrong survives the connection and ruins the show quietly:

- **your microphone left off the air.** Nothing anywhere said so, and it sounds
  perfect from where you are sitting, because you go on hearing yourself either
  way. Every listener gets a show with the presenter missing;
- **a picture file you have moved.** It went out as a flat dark rectangle for
  the whole broadcast and nothing noticed;
- **no camera chosen, or a camera another program has taken**;
- **a bitrate outside what the platform will accept.** The app has known these
  numbers since 3.4.0 and only ever showed them in Preferences;
- **track titles turned off**, which quietly freezes the card so it goes on
  saying whatever was playing when you went live;
- **the wrong one of the two destinations ticked.**

What YouTube and Facebook do the moment you connect is now said **before** you
connect, which is the only side of that decision it is any use on.

**Ctrl+Shift+B was wrong about where Ctrl+B goes, and is not any more.** It
always read the radio station's address, whichever destination was ticked. A
board set up for YouTube and nothing else answered "Off air, and no server is
set up yet" while Ctrl+B would have gone live perfectly well, and a board with
both named the radio station when the show was going to YouTube. It is the one
question that key exists to answer.

**Alt+Shift+V changes the picture, on air, without dropping the stream.**

Up and down read the choices, Enter puts one out. It sits beside Alt+Shift+S,
which does the same job for audio sources.

**Two new things to point it at.**

- **Your screen.** What you are doing, for a demonstration or a walkthrough.
- **Your screen with the camera in the corner**, small, so the screen stays
  readable.

The corner rather than side by side is a measured decision, not a preference.
A 1280 wide picture split down the middle leaves your screen 640 across, and a
1920x1080 desktop at 640 across is not small text, it is no text: ordinary
writing turns to a grey smear. At the full width the same screen reads
perfectly. A screen nobody can read is not worth sending, so the screen gets
the frame and the camera gets the corner.

Nothing was added to the download for any of this. The screen capture is
Windows' own, the same way the app already takes sound out of another program.

**Sound and picture stay locked together through a switch**, and that is
checked rather than assumed: `tools/check_switching.py` runs a real broadcast
at real speed with the real screen capture attached, changes the picture three
times, and then decodes what the server received. Over a minute on the air the
sound and the picture finished 21 ms apart, they were never more than 5 ms
apart at a switch, no gap between frames went over 100 ms, and no frame went
black at any of them.

**Ctrl+Shift+F works again. It has not worked since 3.4.0.**

Found while testing the new key, and only because that test presses a real
key rather than calling the code behind it.

Saved stations get a block of twenty internal numbers on the On air menu, and
that block had quietly grown over the top of two other commands: **what the
camera can see**, which was the headline of 3.4.0, and **Set up streaming** on
the Help menu. When two commands share a number the last one wins, so
`Ctrl+Shift+F` was reaching the station picker and doing nothing at all.

Every test in the app passed the whole time, because they all call the code
directly and the fault was in what Windows does with the key first. There is a
check now that no two commands can share a number, and a tool that presses the
key for real.

Nothing about the soundboard, the running order, the keyboard or your radio
station streaming has changed. The digit map is untouched.

## 3.4.0, 7 September 2026

**Drop Deck goes out on YouTube, Facebook and Restream.**

Pick a platform on the new Video streaming page, paste your stream key,
press Ctrl+B. Your radio station is still on its own page and Ctrl+B goes to
whichever one you tick.

**Something has to be on the screen**, because YouTube will not take sound on
its own. A card with your station name and whatever is playing is the default
and costs about 64 kbps. Your own artwork and a camera are the other two.

**Ctrl+Shift+F says what the camera can see.** In shot or not, centred, close
enough, lit. You cannot look at a preview window, so the app tells you instead.
It says changes rather than states, so it is not a running commentary: at the
most talkative setting, six seconds in front of a camera produced one sentence.
Off, problems only, or everything, and the key answers at all three.

**Your stream key does not go in the board file.** It goes in Windows
Credential Manager. Anybody holding a YouTube key can broadcast to your
channel, and a board file is plain JSON that people send each other.

**Setting up streaming is in the app**, on Help, and on a button beside the
platform picker. Step by step for each of the four, the same text as the
manual.

Two things worth knowing before your first broadcast, because they are
opposite:

- **YouTube puts you live the moment you connect.** It makes the watch page,
  tells your subscribers and saves the video. Set it to Private first.
- **Facebook shows you a preview** and posts nothing until you press Go Live
  Now.

Restream is the one to practise on. Turn every channel off there and the
stream reaches Restream and goes nowhere.

**Also fixed while building this:** the picture used to stutter, because
frames left in bunches of eight with a fifth of a second of nothing between
them. And if your connection died without saying so, the app went on
reporting ON AIR with nothing leaving the machine. It notices now, says so,
and reconnects.

Nothing about the soundboard, the running order or your radio station
streaming has changed.

## 3.3.2 for Mac, 7 September 2026

**The app now tells you when your microphone is not reaching the air.**

**Put the microphone on the air**, on the Streaming tab, is on by default and
always has been. What was wrong is that turning it off was invisible: you go on
hearing yourself either way, so a stream with no presenter on it sounds exactly
like a good one from where you are sitting, and nothing anywhere said
otherwise. Reported by Kyle Smith, who had exactly that and worked out why
himself.

It was also mislabelled. It used to say "Send the microphone as well", and it
does more than that: it governs the programme, which is the recording as much
as the stream, so with it off your voice was missing from every recording too.

Opening the microphone while live or recording now says so out loud, and so
does going live or starting a recording with the microphone already open.
`Command+Shift+B` reports it, and the status line says `Mic on, NOT on air`
rather than a "Mic on" that is true and misleading.

The stream status also stopped claiming AAC, now that there are four formats to
choose from.

## 3.3.1 for Mac, 7 September 2026

**MP3.** You can stream in MP3 and record in MP3.

It is the format a great many Icecast mounts and every SHOUTcast v1 server
want, and until now a Mac could not send it. macOS has no MP3 encoder of its
own, at any layer: it decodes MP3 everywhere and writes it nowhere. So this one
comes from LAME, which is included with the app as a separate library under its
own licence. Help, About says where it comes from and links to the source, and
`mac/vendor/README.md` in the repository has the whole reasoning.

MP3 is now the default for a new station, because it is the safe answer when
you are not sure what your mount wants. AAC, Opus in Ogg and WAV are all still
there, and a station saved on Windows as MP3 stays MP3 here instead of being
quietly moved to AAC.

**Recording gets MP3 too**, alongside WAV, AAC and FLAC.

Nothing else changed.

## 3.3.0 for Mac, 7 September 2026

A Mac only release. Nothing on Windows changed.

**VoiceOver can hear the app again.** Every spoken line was being posted to the
window's content view, and an announcement request is only honoured on a window
or on the application, so VoiceOver said nothing at all and the words landed
only in the status bar. Command D changed the ducking in silence; Command Shift
B answered into a box at the bottom of the screen. Announcements now go to
whichever window is in front, which also puts them inside a dialog rather than
behind it.

**Switches say what they did, at every speech level.** Ducking, the microphone,
going live, the recorder, global hotkeys and the three faders are on a channel
of their own now. "None" means stop narrating, not stop answering: a switch you
pressed that then says nothing is not quiet, it is a switch you have to go and
look up.

**Escape closes a dialog again.** The main window was claiming Escape for the
stop counter before any dialog could see it, so Preferences, and every other
window in the app, could only be left with the mouse or by finding Cancel.
Escape now belongs to whatever is in front, and only the main window's own
Escape stops the show. The keyboard check, which reports Escape rather than
acting on it, says to press it twice to leave.

**Preferences is laid out like VoiceOver Utility.** The eight tabs are a
category list down the left with that category's settings beside them. A list
says where you are the moment you arrow onto it, where a tab view has to be
interacted with before its tabs exist at all.

**Source control has a key of its own.** It was on Option Command Shift S, and
so was Go to the soundboard; AppKit gives a shared key to whichever menu item it
reaches first and says nothing, so Source control could only be opened with the
mouse. It is Option Command C now. Option Command M mutes every source at once
and Option Command S solos the microphone, both without opening anything, and
the status line carries SOLO and SOURCES MUTED while they are on. The self test
now refuses a build with two commands on one key.

**Keys that were declared and went nowhere.** Every binding after a command's
first one is an alias, and the menu can only carry one key each, so none of them
were dispatched anywhere: Command E did not search, Command P did not open
Preferences, Option Return did not open properties, Command Shift bracket did
not change bank, and Delete on a laptop keyboard did not clear a slot, because
the menu carries the forward delete and a Mac's Delete key sends Backspace. All
of them work.

**Streaming in Opus and WAV, beside AAC.** Opus in Ogg is what Icecast
recommends now and it is what an Ogg mount expects; the Ogg pages are written by
the app because macOS cannot write one. WAV is uncompressed PCM for a relay or
for feeding another encoder, and Preferences says plainly that it is not for an
audience. MP3 is still not offered: macOS has no MP3 encoder at any layer, and
the Streaming tab now says so rather than leaving somebody to wonder.

**A stereo microphone.** A microphone input is not always a microphone. Set to
"Keep it in stereo" it no longer folds a loopback device, a desk feed or a
mixer's main output down to mono.

**Every running program is in Audio sources.** The list came from Core Audio,
which only knows about programs that have already opened audio, so Spotify
sitting paused was not in it. Everything that is running is listed now, marked
as playing now, has played, or running.

## 3.2.2 for Mac, 6 September 2026

**TG Drop Deck runs on a Mac.** The same soundboard, written natively for
VoiceOver rather than ported: the four banks on the number row, the running
order with its crossfades, drops library and M3U files, the microphone and
its voice chain, other programs on the air including VoiceOver itself,
recording, streaming with saved stations, global hotkeys, feedback and signed
updates. It reads and writes the same board file as the Windows copy, so a
show built on one machine opens on the other, and the two copies share a
version number from here on.

**One key moved, for a reason.** On a Mac, Control plus Option is VoiceOver's
own modifier, so the drops are on Command and the beds on Option plus Command
rather than the Windows Control keys. Everything else is the Windows key with
Command where Windows has Ctrl, the Windows Control keys still work where the
system leaves them free, and the Keyboard tab offers the literal Windows map.

**What a Mac cannot do.** It sends AAC rather than MP3 or Ogg, because macOS
has no MP3 encoder and cannot write an Ogg container; it cannot read WMA; and
it does not host VST3 plugins in the voice chain yet. The Mac manual, at
tgstudios.app/drop-deck-guide-mac, says so wherever it matters.

## 3.2.2, 6 September 2026

**Your screen reader can go on the air.** NVDA, JAWS, Narrator, ZoomText,
Fusion, MAGic, SuperNova and System Access are in Audio sources now, and
capturing one gives you its speech, so a tutorial or a demonstration goes out
the same way any other program does.

They were missing because the list was built from visible windows, and a
screen reader does not have one. It is built from three directions now:
programs with a window, anything that has audio open, and every screen reader
that is running whether it happens to be speaking or not. That last part
matters, because the reader you are looking for is exactly the one that will
be silent at the moment you go looking.

**Programs with no window, generally.** The same change lists anything that
has opened the sound card, so a game running full screen, a player sitting in
the tray or a browser playing in the background are all there without a
virtual cable. On the machine this was written on that is nine entries where
the window list found five, against three hundred and twenty two processes.
A list of three hundred and twenty two is not a list anybody reads, which is
why it is not simply all of them.

**The picker says why something is in the list.** "obs64.exe" on its own reads
like something has gone wrong. "obs64.exe, has audio open" reads like an
answer, and a screen reader is named as one.

## 3.2.1, 5 September 2026

**A source can be one program now, with no cable in the middle.** Pick Google
Chrome, or TeamTalk, or a game, and Windows hands over exactly what that
program is playing and nothing else. There is nothing to set up in the program
itself and no driver to install. It is the same thing OBS calls Application
Audio Capture.

Programs are listed by their window, so you see the names you recognise rather
than four hundred services, and the list is refreshed every time you open it.
A source remembers the program by name, never by its process number: that
number is different every time a program starts, so a board that saved one
would capture nothing next week.

If the program is not running when Drop Deck opens, the source says so instead
of sitting there quietly. If you close the program mid show, the capture
notices within a couple of seconds and tells you, instead of going silent and
looking fine.

Needs Windows 10 build 20348 or later. On anything older the option is still
there and says it cannot be done, and the virtual cable route works as before.

**Alt+Shift+S** opens Audio sources, whichever kind you are after: a sound
card, a cable, or a program.

**Source control, for while you are on air.** `Alt+Ctrl+Shift+S`. A list you
work without leaving the keyboard: up and down choose a source, left and right
choose what to do to it, and `Space` does it. Mute, solo, rename or remove.

Your microphone is in that list too, because soloing a games call has to take
your voice down with everything else or it is not a solo. It can be muted from
there, and not renamed or removed.

Every source keeps a number, and the number is its position rather than
anything to do with its name, so renaming one does not renumber it. Pressing a
digit jumps straight to that source. A mute is never saved with the board:
coming back tomorrow to a source that is quiet for reasons you cannot remember
is worse than having to press it again.

**Some of the changelog was rewritten.** Not what any release did, only how it
read: five "rather than" and six "which is" inside three entries is one voice
with one move, and it showed.


## 3.2.0, 5 September 2026

**Record the show.** `Ctrl+R` starts and stops it. It records the same mix that
goes on air, in WAV, MP3, AAC or Ogg Opus, to Documents as `Drop Deck Stream
001` and counting up, so nothing you have already recorded is written over. It
does not need you to be on air, and recording and streaming can run together
without either taking audio from the other. Closing the app finishes the file
first, so a recording always opens.

**Other things on the air.** On air menu, Audio sources. Anything Windows
offers as an input can go out with you: a second microphone for a co-host, a
hardware mixer, or another program entirely.

For another program you need a virtual audio cable: a free driver that looks
like a speaker to one program and a microphone to another. Point TeamTalk,
Chrome or a game at the cable in its own settings, then choose the cable here.
That is all there is to it, and it works for anything without Drop Deck
needing to know what the program is.

Each source has a name, a gain, which channel to take, whether it goes on the
air and whether you hear it yourself. Sources are never ducked and never go
through the voice processing, because both of those belong to your microphone.

**Stop one sound without stopping the show.** `Ctrl+Space` stops the sound you
started last and leaves everything else playing, and pressing it again unwinds
the one before that. It says which, by name.

Until now there was no way to stop a single sound at all: only music beds
toggled off, so the panic key was the only option for something that was not a
panic. Chris Cooke found that, having never used a soundboard before: "I have
a rather long sound file that I may only wanna play a little bit of."

A slot can also be told that **pressing its key again stops it**, in its
properties. Off by default, because effects and drops piling up is what a
soundboard is for and a laugh landing on top of a sting is the point.

**How many presses of Escape is up to you.** One to four, in Preferences,
Sounds and beds. It used to be three and now starts at two. You can also have
it cut instantly instead of fading, which is what a mixer or a DAW fader
wants.

**Feeding OBS.** Nothing new was needed and the guide now says how: send a
bank to a virtual cable in Preferences, Output, and add that cable in OBS as
an Audio Input Capture. Allen Sale asked.

**The user guide has a contents**, grouped by what you are actually doing:
getting going, running a show, your voice, on air, and everything else.


## 3.1.0, 5 September 2026

**Portable copies replace themselves now.** A portable copy is meant to be
the new executable, not a second folder next to the old one, so that is what
it does: it downloads the zip, and because Windows will not let a running
program overwrite itself, the new copy does the writing. It waits for the old
one to close, replaces the folder it came from, and starts the app again from
the same path. The folder keeps its name, so every shortcut still works, and
anything you put in there yourself is left alone.

A swap that cannot finish puts the old copy straight back, so the folder is
never left half written and the app still starts. On a read only location,
where nothing can be replaced at all, it unpacks beside as before and says
so.

**Ctrl+Shift+A opened Preferences.** Two commands had been given the same
number, so the key reached whichever handler was wired last. Escape had the
same fault, sharing with Search. Both fixed, and there is now a check that no
two commands can share a number again.

**Escape now takes three presses.** A single key that silences a live show is
a single key away from silencing it by accident, and Escape is the key
everybody presses out of habit. It counts, says how many are left, and forgets the count
after a couple of seconds. The Stop everything button still does it in one,
because pressing a button called Stop everything is not something you do by
mistake.

**Stopping says it is stopping.** The playlist was stopped before the mixer
counted what it had silenced, so stopping a song that was playing on its own
announced "Nothing was playing". It says "Stopping playback" now, and says
nothing was playing only when nothing was.

**Alt+Home and Alt+End** send the track you are on to the top of the running
order or to the end. Alt+Up thirty times was not a way to move a song, and
counting the presses to know where you had got to was worse.

**Shift+Enter crosses into the track you are on**, fading out whatever is on
air at the crossfade length. It is how you get out of a song early. The right
click menu has always had it; now it has a key.

**Shift+A ticks every track, Shift+U unticks them all**, from inside the
running order. Plain letters still jump to a track by name.

**Six warning sounds, and a louder one by default.** The beep before a track
ends sat at minus fourteen. That is fine in a quiet room and no use at all
over the song it is warning you about, so it is at minus six now, with a
volume of its own, and there are six to choose from:
a pip, a double pip, a chime, a bell, three ticks and a rising sweep. Each
plays as you choose it. They are different shapes, not different notes: over
music a bell and a sweep are told apart at once, where two tones a third apart
are not. All six sit at the same loudness, so changing your mind never changes
how loud your warning is.

**Who is listening.** `Ctrl+Shift+A`, or the On air menu. It shows every
stream on your server, how many people are on each, and what the server thinks
is playing, and it keeps itself up to date while it is open. It works off air
too, which matters if your station carries on without you.

It handles the awkward case, and the awkward case is the common one: if you
stream into automation, the server you send to is not the server people listen
to. Drop Deck looks in the usual places and says which one answered. If your
listeners are somewhere else entirely, there is a box for that on the
Streaming tab.

Nothing here needs a password. Icecast and SHOUTcast both publish their own
listener counts, and that is what this reads.


## 3.0.0, 4 September 2026

**Your voice, properly processed.** A gate, a high pass filter, a three band
equaliser, a compressor and a true peak limiter, on the microphone, in that
order. Every setting is a row in a list: up and down to choose one, left and
right to change it, and it says the new value as you go. Hold `Shift` for a
bigger step. Nothing opens a window you cannot read.

The limiter is a real ceiling, not a loudness maximiser. Set it to minus one
and nothing leaves at minus nought point nine. That is the promise a broadcast
limiter has to keep, and it costs no delay at all, because a few milliseconds
between your mouth and your headphones sounds like a barrel.

**VST3 effects, read out loud.** Load a vocal effect and its own knobs appear
in the same list, in plain words with real units. Presets save and open. The
plugin's own window is never opened, so a plugin no screen reader can read
becomes a list any screen reader can. Instruments are refused: an instrument
in a voice chain would replace your voice instead of changing it.

Your plugin and its settings are remembered with the board.

**Preferences opens on the tab you asked for and Cancel really cancels.**
Everything on the Voice tab changes the microphone you are listening to while
you set it, and that is deliberate. Cancel now puts all of it back.

**A board brings its microphone with it.** Opening a board applies its gain,
its channel and its whole voice chain. It used to leave the microphone on the
last board's settings and then write those back over the new one.

**The portable copy updates itself.** Checking for updates from the zip used
to download the installer, install a second copy somewhere else and leave a
desktop shortcut pointing at that one, while the copy you were running stayed
on the old version and said nothing. It now downloads a zip, unpacks it in a
folder beside the one you are running and tells you where. HarmonicaPlayer
found this.

**Sound cards that do not run at the same speed.** A bank sent to a card that
will only open at 44100, beside a main output at 48000, was being summed as
though they matched: the stream started dropping audio fourteen seconds in.
Each card is converted properly now.

**Changing an output while on air no longer takes you off it.** The stream
went silent and said "reconnecting" forever, and only coming off air and back
fixed it. A sound card that stops responding no longer stops the broadcast
either, and one sound that will not play can no longer silence a whole card
for the rest of the show.

**Smaller things.** Enter on Cancel in the hotkey window did what OK does, and
`Space` did nothing on any button. A station saved in Preferences was gone by
the next launch. A board that could not be saved on the way out was lost
without a word; it now asks. A sound that will not decode says so instead of
quietly stopping the preview. `Page up` and `Page down` belong to the settings
list again.

Thanks to Jerry, Shane and Brian, who all found something in this one.


## 2.9.1, 4 September 2026

**Fields say what they are.** Tabbing the Streaming tab with NVDA announced
every field with the label of the one above it, so the password box called
itself "User name", and the crossfade box beside the running order had no
label at all. Both are fixed, along with the same fault in the per bank
outputs and four Alt keys that each did two jobs.

The cause is worth writing down: `SetName` is not the accessible name on
Windows. A screen reader is given the static text that precedes a control in
creation order, so building a control before its label labels it with the row
above. Spin controls needed an accessible object of their own, because focus
lands on the edit box inside them and that box has no label in front of it.

**Nothing is lost coming off air.** A codec only takes whole frames, so up to
a quarter of a second was thrown away at the end of every broadcast: the last
moment before you pressed Ctrl+B, which is exactly when somebody is still
talking. The remainder is now sent.

**A connection that cannot keep up says so.** A stream falling behind sounds
perfect in the room and skips at the other end. Drop Deck now watches how far
behind it is and tells you, once, rather than quietly losing audio. If it has
already lost some it says that too, and `Ctrl+Shift+B` reports both.


## 2.9.0, 4 September 2026

**AAC.** Stream in AAC as well as MP3 and Ogg Opus. Brian Hartgen asked for
it: "you may want to consider streaming using AAC, which is what we do."

**More than one station.** Save as many servers as you like. Preferences has
a picker with Save this station and Forget it, and the On air menu lists them
under Station, so switching is one menu rather than four boxes of retyping.
Switching is refused while you are on air; come off first.

**Only one music bed at a time.** Starting a bed takes the one before it down
with its own fade, and says which it replaced. Two beds together is two
pieces of music fighting. Sound effects and drops still overlap.

**And a bed never plays under the playlist.** Both are music. Starting a
playlist track fades the bed out, and a bed will not start over a running
playlist; stop the playlist first.

**Every box in every dialog says what it is.** Slot properties had four text
boxes with no name at all, and every spin control was named on its wrapper
rather than on the box Tab actually lands on, so a screen reader landing
there heard "edit". Both fixed, and `tools/check_labels.py` now walks every
dialog in tab order so it cannot come back.


## 2.8.0, 4 September 2026

### Put the show on the internet

`Ctrl+B` sends everything you can hear to your own streaming server. Icecast,
a Liquidsoap harbor or SHOUTcast, in MP3 or Ogg Opus, at whatever bitrate you
pick. Set it up under On air, Set up streaming, and Test the connection proves
it works before the show rather than during it.

`Ctrl+Shift+B` says what the stream is doing: on air, for how long, and
whether anything has been lost.

**It sends the program, not your headphones.** Sounds, beds, the playlist and
the microphone go out. Previewing a sound and the beep before a track ends do
not, because those are yours.

**The microphone goes out whenever it is open**, whether or not you are
hearing yourself. Being heard and hearing yourself were the same switch
before, and they are not the same question: a presenter on speakers monitors
nothing and is still on air.

**The playlist fader is a monitor fader.** While you are on air, `F7` and
`F8` change what you hear and not what goes out, so you can pull the music
right down to hear your screen reader and navigate while listeners carry on
hearing it at full level. The other faders change both. There is a switch in
Set up streaming if you want the old behaviour.

**The show comes first.** Encoding and the network run on their own thread. If
the connection cannot keep up, the stream loses audio and what you hear does
not, which is the right way round. Ctrl+Shift+B tells you if it happened.

**It reconnects on its own** and says so, rather than handing you a dead
stream mid sentence. A wrong password stops instead, because retrying that
forever only looks like it might still work.

Listeners see the artist and title from your playlist.

Nothing goes out until you press Ctrl+B, and it is never on when the app
opens.

Preferences has a Streaming tab, and is now six tabs rather than five.


## 2.7.1, 4 September 2026

**Preview works in the Windows file window too.** Press `Alt+P` in there and
each sound plays as you arrow onto it, the same as in the app's own browser.
It only listens while Drop Deck is the program in front, so Alt+P in anything
else stays that program's key.

2.7.0 said this could not be done because Windows will not say which file is
highlighted. That was wrong. It says so perfectly well; the test that decided
otherwise never managed to highlight anything, so an empty answer looked like
a broken one.


## 2.7.0, 4 September 2026

### Find a sound by listening to it

The window that opens when you assign a sound is this app's own now, with a
**Play each sound as I reach it** box on it, `Alt+P`. Turn it on and every
sound plays once as you arrow onto it, and stops the moment you move on. It
waits a beat first so your screen reader gets the name out before the sound
starts.

Enter opens a folder or takes the sound you are on, Backspace goes up one, and
**Browse with Windows** opens the ordinary file window for typing a path or
reaching a network drive.

**Browse with Windows** opens the ordinary Windows file window, and 2.7.1 made
`Alt+P` preview in there too.

### A bank does not have to have twenty slots

**`Shift+Delete` takes the slot you are on off the board.** Also in the Sounds
menu, the right-click menu, and as a button in Properties. Delete clears the
sound; Shift+Delete removes the slot. Want ten instead of twenty? Remove 11 to
20.

Removing one never moves the others. Take slot 5 away and 6 is still on the 6
key, because that map is years of muscle memory. The slot keeps its sound, its
name and both its hotkeys while it is off the board, so nothing asks whether
you are sure. Put a removed slot back, or Put this bank's slots back, both in
the Sounds menu.

The last slot in a bank will not go. A bank with nothing in it has nothing to
come back to.


## 2.6.0, 3 September 2026

The playlist, rebuilt around Brian Hartgen's report. All eight of his points.

### The running order

**Your screen reader says whether a track is ticked.** That was the
deal-breaker. The old control was a wxCheckListBox, which on Windows is a list
box with a tick painted on it: MSAA never knew the tick was there. It is a list
view with real check boxes now.

**Six columns**: title, artist, song or drop, length, when it starts, and its
own crossfade if you have given it one. Each is a cell a screen reader reads on
its own.

**Artist and title come from the file's tags**, not the file name.

**No numbers in front of the rows, so first letter navigation works.** Press T
and you land on the next title starting with T.

**Enter plays from the item you are on.** It never did: a list box on a frame
never receives Return.

**"Starts at" always has a value.** The first track said "starts at" and then
stopped. It says "at the top".

**A row no longer says "skipped".** The tick box says it.

### The crossfade

**You can type into the crossfade box.** The pads are on bare digits and a
frame's keyboard map is read before the control with focus, so every digit went
to a pad. The pad keys stand down while a text box has focus. Everything with a
modifier still works.

**The crossfade is a crossfade.** The cue used to be taken from the file's last
sample, and an MP3 carries a second or two of silence there, so most of a three
second crossfade happened inside it. The end of the music is measured now, once,
in the background. And the incoming track came up from nothing; it comes in at
level and the outgoing one rides down under it.

**Spots butt up against the song behind them.** A fifth of a second of overlap,
always, even with the crossfade at zero.

**The output rounds off instead of clipping square** where two songs sum past
full scale.

### Knowing what is on air

- The window title carries the playing track.
- `Ctrl+L` says which of how many, and how much is left. It answers at every
  speech level, including Nothing, because a key that only answers questions
  has to answer them.
- `Ctrl+Shift+L` puts the cursor on the track that is on air.

### A beep before a track ends

**Preferences, Ctrl+P.** Turn it on, set how many seconds, ten by default.
A short pip tells you a playlist track is nearly over. It is the countdown
clock a sighted presenter watches.

It plays out of the monitor output, the one Microphone settings picks, so with
headphones set up there it stays out of the show. It is not ducked and it
ducks nothing, because the moment you most need it is while you are talking.
Off until you turn it on, and a track shorter than the warning does not get
one.

### Saving a show

**Playlist menu, Save the running order.** It writes an M3U, so the file opens
in VLC, on a phone, or in whatever the studio runs. Open a running order loads
one back. Drops, ticks and per track crossfades are kept in comments this app
reads and other players ignore.

Paths in the playlist's own folder are written relative, so the folder can be
moved. A track whose file has gone comes back in its place, marked missing, for
File, Relink missing sounds.

Dragging an M3U onto the running order adds it to the end instead of replacing.

### m4a

**The app takes m4a files.** It took none before: libsndfile has no MPEG-4
support. FFmpeg is bundled now and picks up `m4a`, `m4b`, `mp4`, `aac`, `wma`,
`opus`, `webm` and more. About 26 MB bigger for it.

### Preferences, on tabs

**Audio settings is Preferences now**, still `Ctrl+P`, and it has five tabs:
Output, Sounds and beds, Playlist, Microphone, Speech. It was one long column
of every setting the app has, in the order they were added.

Microphone settings is one of those tabs rather than a window of its own.
`Ctrl+Shift+M` still works and opens the same window on that tab. Two keys,
one place to look.

### Also fixed

Writing the tick boxes from the running order counted as you ticking them, so
every refresh wrote the status bar and marked the board unsaved. The first
refresh happens before the window has a status bar: five errors a launch.

The pad labels stopped being refreshed the moment the playlist went on air. The
refresh walked every playing slot, and the playlist's decks are numbered above
the eighty pads, so it raised from inside a timer every quarter second.

Delete pressed inside the crossfade box removed a track. It does nothing now.


## 2.5.2, 2 September 2026

Text only. Nothing you press has changed.

Every em dash and en dash is gone from the app, the `F1` help, the dialogs, the
About box, the changelog and the whole website. A screen reader either skips a
dash or says the words "em dash", and neither is what the sentence meant.

`tools/nodashes.py` finds them and removes them. Read its diff afterwards: a
dash swapped for a comma leaves comma splices, and no tool can tell a good
comma from a bad one.

Also corrected: the website said F4 renames a sound. That stopped being true in
2.2.0, when the volume keys moved down one and F2 took over. It had been wrong
for five releases.


## 2.5.1, 2 September 2026

**There is a user guide.** [tgstudios.app/drop-deck-guide](https://tgstudios.app/drop-deck-guide/),
and in the app under Help, User guide. Plain English, every key explained. `F1`
is still the key list; the guide is the why.

**Save board as is `Ctrl+F12`**, not a bare `F12`. F12 sat one key from the
volume row and was too easy to hit by accident. Nothing else moved.

**The crossfade box now says what it does.** It sits under the running order
with the explanation beside it. It is also in Preferences, which is where
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
mid phrase is a more obvious mistake. Both fades are in Preferences if you
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

Preferences has a Spoken feedback setting with three levels: everything,
only what you cannot hear or read for yourself, or nothing at all.

The bank hint is spoken once per bank per session rather than on every tab
change. Your screen reader already says "Dialog Drops, tab selected".

## 2.1.2, 30 August 2026

Both from Brian Hartgen.

### Send a bank to its own output

Preferences has an output for each of the four banks. Set Music Beds to one
sound card and Dialog Drops to another and you can bring each up on its own
channel of a physical mixer.

Ducking still works across outputs. A drop on one card ducks a bed on another.

Banks sharing an output share one audio stream, so the ordinary case costs
nothing.

### Turn off the announcement when a sound starts

Preferences, Say the name when a sound starts or stops. For when you built
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
