# Video streaming to YouTube and Facebook, the groundwork

Written 7 September 2026, before any of it is built. Companion to
[STREAMING-PLAN.md](STREAMING-PLAN.md), which was the groundwork for the
Icecast encoder that now ships. That document parked RTMP as "not urgent".
This one takes it off the shelf.

Nothing here is implemented. Everything in section 1 was measured on Tony's
machine on 7 September 2026, not assumed.

**Windows first.** The concept gets proved and nailed down on Windows, tested
offline before anything is installed, pushed or deployed. The Mac copy is not
touched until that is done, and then by the Mac side. Section 8 says what that
will cost when it comes.

---

## 1. What was measured

The single most useful finding: **almost everything needed is already in the
build.** PyAV is bundled for m4a decoding, and the FFmpeg behind it can do the
whole job.

| Question | Answer, measured |
|---|---|
| PyAV version | 17.1.0, libavcodec 62.28.101 |
| RTMP protocol | **Registered.** A bogus scheme raises `ProtocolNotFoundError`; `rtmp://` raises a connection error, which is the protocol working |
| RTMPS protocol | **Registered.** TLS is compiled in, through Windows schannel, so there is no OpenSSL DLL to ship |
| Reachability | TLS 1.3 to `a.rtmps.youtube.com:443` and `live-api-s.facebook.com:443`, certificates valid |
| SRT | **Not compiled in.** Not available and not worth chasing |
| H.264 encoders | `libx264`, `h264_mf` (Media Foundation), `h264_amf` all work here. `h264_nvenc` and `h264_qsv` are absent on this machine |
| Speed, 720p30 | 11x realtime |
| Speed, 1080p30 | 5x realtime |
| A still card, 720p30 | **64 kbps and 6 per cent of one core** |
| Camera present | HP HD Camera, maximum 1280x720 yuyv422 at 30 fps. Also an OBS Virtual Camera |
| Camera capture | 30.4 fps sustained at 720p, first frame 0.58 seconds after opening |
| Per frame cost | 4.0 ms to convert to yuv420p, which the encoder needs every frame. Budget at 30 fps is 33.3 ms |
| Face detector | OpenCV 5.0 is installed but **has removed Haar cascades**. `FaceDetectorYN` is there and needs a model file that does not ship with it |

Two failures worth writing down, because both are the kind that waste an
afternoon.

**Device enumeration arrives in fragments.** `av.logging.Capture` gets the
DirectShow device list, but FFmpeg emits it as partial lines: `'"HP HD
Camera"'`, then `' (video'`, then `')'`, then `'\n'` as four separate records.
A per record regex matches nothing and returns an empty camera list, silently.
Join every record into one string, then split on newlines, then parse.

**A camera is exclusive, and the error says nothing.** With OBS running, the
device opened, negotiated 1280x720 correctly, and then every read failed with
`OSError: [Errno 5] I/O error`. Twenty seven attempts, no recovery. Camera
privacy consent was `Allow` at both user and machine level, so permission was
never the problem. The app has to translate that error, because "I/O error"
tells a presenter nothing and the real answer is "another program has the
camera". Check the obvious suspects by name and say so.

---

## 2. The architecture change, which is real but contained

Today the show reaches a server like this:

```
audio callback -> AirBus -> Streamer thread -> Encoder -> on_bytes -> Sink -> socket
```

`Encoder` produces bytes. `IcecastSink` owns the socket and writes them. The
split works because Icecast is a dumb pipe: open an HTTP connection, push MP3
at it forever.

**RTMP inverts that.** RTMP is a session protocol with a handshake, chunk
streams and AMF commands, and FFmpeg implements all of it. So PyAV opens the
network itself:

```python
container = av.open("rtmps://a.rtmps.youtube.com/live2/KEY", mode="w", format="flv")
```

There is no byte callback and no socket of ours. `_CallbackFile` and the whole
`Sink` layer are bypassed.

So the shape to add is **a destination that owns both encoding and transport**,
beside the existing pair rather than instead of it:

```python
class Destination:
    """One place the show goes. Owns its encoder and its transport."""
    def connect(self): ...
    def feed_audio(self, block): ...
    def feed_video(self, frame): ...   # RTMP only
    def close(self): ...
```

`IcecastDestination` wraps today's `Encoder` plus `IcecastSink` unchanged.
`RtmpDestination` is a single `av.open` on the URL. `Streamer` keeps its retry
loop, its backlog watching and its state machine, and stops caring which it is
holding. **That refactor is worth doing on its own**, before any video, because
it is the piece that makes everything after it small.

### The two clocks, which is the hard part

Today there is one clock: the sound card. `_pump` reads whatever the `AirBus`
has and encodes it, so the stream runs at exactly the speed audio is really
produced.

A camera is a second clock, and it is not the same speed. A webcam claiming 30
fps delivers something near it, drifting against the sound card all night.
Video and audio timestamps have to stay locked or lips and sound part company,
and a stream that drifts is one that gets progressively worse over a three hour
show rather than being visibly broken at the start.

**The audio stays the master.** It already is, and it is the half a listener
notices. Video is stamped against audio time, not against the camera's own
delivery:

```
audio_time = frames_encoded / samplerate        # the master clock
video_pts  = round(audio_time * 1000)           # FLV runs on a 1/1000 timebase
```

A frame that arrives late is stamped late. A camera running slow duplicates the
last frame to fill; one running fast has a frame dropped. Both are invisible at
these sizes and neither accumulates, which is the same bargain the `AirBus`
already makes for sound cards that are not quite the same speed.

**This was validated, not assumed.** Five seconds of 44.1k audio and a wall
clock 30 fps video, muxed to FLV on this design: 150 video packets, 216 audio
packets, exactly 30.06 fps measured, and **2 ms of drift at the end**. The
target for lip sync is under 100 ms. There is a lot of room.

### Where the camera runs

Its own thread, like everything else here. Not the audio callback, not the UI
thread. A camera that stalls must cost the video and nothing else: the rule
that a dead network cannot touch the show applies exactly the same way to a
camera that has been unplugged. A stalled camera holds its last frame and the
audio carries on, because a stream that keeps talking with a frozen picture is
a working show and a stream that stops is not.

---

## 3. Framing a shot you cannot see

This is the part with no prior art, and it is the reason this feature is worth
Drop Deck building rather than telling people to use OBS.

OBS solves framing with a preview window. That is not a solution, it is the
problem restated. A blind presenter going live on YouTube has no way to know
whether they are in shot, centred, lit, or whether they wandered out of frame
twenty minutes ago and have been broadcasting an empty chair.

**So the app says it.** Tony's ask, 7 September: a detector that can tell you
when your face is in view, or centred, with the announcements switchable so
they do not become repetitive.

### What it can say

From one face rectangle you get all of it:

| Reading | Spoken as |
|---|---|
| Nothing found | "No face in shot" |
| Centre x outside 0.4 to 0.6 | "Left of shot" / "Right of shot" |
| Centre y outside 0.3 to 0.65 | "High in shot" / "Low in shot" |
| Width over 0.35 of frame | "Very close" |
| Width under 0.15 | "Far away" |
| Mean luminance under about 60 | "The picture is dark" |

Measured on the real camera: mean luminance 119 of 255 in Tony's room, which is
well lit, so the dark threshold has real headroom under it.

### Not repetitive, which is the whole design

The rule this app already follows is that a screen reader must not be talked
over, and framing is the worst possible offender: a face wobbles, so a naive
detector announces "centred, left, centred, left" forever. Three things stop
that, and all three are needed:

1. **Say changes, never states.** Nothing is spoken while the reading is what
   it was. This alone removes almost all of it.
2. **Hysteresis on every threshold.** A face on the boundary must cross a wider
   band to change the answer than it did to set it, or it chatters.
3. **A floor between announcements.** Several seconds minimum, and the counter
   resets on speech, not on detection.

And it is off by default. **Nothing opens the camera except the user**, the
same rule the microphone already has.

### Three levels, matching the app

The three speech channels already exist, so this uses them rather than adding a
fourth idea:

- **Off.** No framing speech at all. The check still runs, so the state is
  there when asked for.
- **Problems only.** Speaks when you leave shot, come back, or go dark. Silent
  while the shot is good. **This is the default**, and it is the setting a
  presenter actually wants: a show is three hours and you need to know about
  the twenty seconds that went wrong.
- **Everything.** Every change, for setting the shot up before going live.

Plus a key that answers on demand, which is the one that matters most. `Ctrl+L`
already answers "what is playing". Framing wants the same: press it, hear "face
centred, a good distance, well lit", say nothing otherwise. **On demand is the
primary interface here and the announcements are the backstop**, because a
presenter setting up a shot wants to ask repeatedly for ten seconds and then
never again.

### The detector

OpenCV 5.0 is installed on this machine but **has removed `CascadeClassifier`**,
so the old Haar route is gone. What is left is `FaceDetectorYN`, which is
better anyway: a small neural detector that handles angles and glasses, where
Haar wanted a square-on face in good light.

It needs `face_detection_yunet_2023mar.onnx`, about 337 KB, from the OpenCV
Zoo. **That file has to be downloaded and bundled**, and it is the one new asset
this feature needs. It sits beside the exe with the demo pack rather than
inside the bundle, for the same reason.

Cost is not a concern. Detection runs on a 320x180 grey copy two or three times
a second, not on every frame. Converting to grey is 5.7 ms and the resize is
0.2 ms; YuNet at that size is single digit milliseconds. Call it 20 ms three
times a second, which is six per cent of one core.

**OpenCV is a new dependency and it is not small**, roughly 40 to 90 MB
installed depending on the wheel. The download is already 60 MB for the
installer, mostly FFmpeg. This is the second cost of that size and it needs
Tony's explicit yes, exactly as the FFmpeg one did. `opencv-python-headless` is
the wheel to use: the normal one drags in Qt for GUI windows this app will
never open.

---

## 4. The licence question, which needs answering before a line is written

**PyAV's wheels bundle a GPL FFmpeg.** `av.libs` contains
`libx264-165-*.dll` and `libx265-*.dll`, and both are GPL only. PyAV's own build
repository confirms it: FFmpeg configured with `--enable-gpl --enable-libx264`,
and the resulting binaries are **GPL version 3 or later**.

Drop Deck is MIT.

**This is already true today** and video does not create it. It has shipped in
every release since PyAV went in for m4a support. But it becomes prominent the
moment the app is doing H.264, and it is worth settling now rather than after
somebody asks.

The position is not alarming. MIT is GPL compatible, so the combination is
lawful. What it means in practice:

- The MIT source stays MIT. Anyone can take Drop Deck's code under MIT terms.
- **The distributed binary carries GPLv3 obligations**, because it contains
  GPLv3 libraries. That means shipping the GPL text and offering the
  corresponding source for the FFmpeg build, not only for Drop Deck.
- Drop Deck's source is already public, so most of this is already satisfied.
  What is missing is naming the FFmpeg build and linking its source.

Three ways forward:

1. **Accept it and document it.** Add the GPLv3 text, and an About box line
   naming the FFmpeg build with a link to `PyAV-Org/pyav-ffmpeg`. This is the
   same thing the Mac copy already does for LAME, and that page is written and
   good. Cheapest and honest.
2. **Move to LGPL wheels.** The `pyav` package on PyPI, from BasswoodAV, ships
   LGPLv3 wheels rather than upstream's GPLv3. Needs checking that it keeps
   `h264_mf`, since it will not have libx264.
3. **Use `h264_mf` only and still ship the GPL DLLs.** This does not help. The
   obligation attaches to distributing the library, not to calling it.

**Worth flagging beyond this app:** if any paid TG Studios product bundles
PyAV, the same reasoning applies there and matters more. Drop Deck is free and
open, which makes GPLv3 nearly free to comply with. A paid closed product is a
different conversation.

Note that `h264_mf` is still worth using as the **default encoder** regardless
of how the licence lands, for a different reason: it is Windows' own encoder,
it hands work to hardware where there is any, and it measured 11x realtime at
720p. `libx264` stays as the fallback for a machine where Media Foundation
misbehaves.

---

## 5. What the two platforms actually require

### YouTube

- **RTMPS**, `rtmps://a.rtmps.youtube.com/live2/STREAM-KEY`. Plain RTMP on
  `a.rtmp.youtube.com` still works and is not worth offering.
- **H.264 video and AAC audio.**
- **A video track is mandatory.** YouTube rejects audio-only ingest. This is
  the whole reason a picture is needed at all, and section 6 is the answer for
  a presenter who does not want to be on camera.
- **Keyframe every 2 seconds**, 4 seconds maximum. At 30 fps that is `g=60`.
  Getting this wrong is the classic "the stream connects and then YouTube says
  it is unhealthy".
- **CBR.** A live ingest expects a steady rate.
- AAC 128 kbps mono to 256 kbps stereo.

### Facebook

- **RTMPS only**, `rtmps://live-api-s.facebook.com:443/rtmp/STREAM-KEY`.
  Unencrypted RTMP has been rejected since 2018. Port 443 is deliberate: it
  gets through firewalls that block 1935.
- **Two account gates that have nothing to do with the app**: the account must
  be at least 60 days old, and the page or professional profile needs at least
  100 followers. A presenter who does not meet these cannot go live however
  good the encoder is, and the app should say so rather than let them chase a
  connection error.
- Stream keys are single use by default. A persistent key is available in Live
  Producer and is the one to use with saved stations.

### Stream keys, not OAuth. Decided 7 September 2026

Tony's call, and it should not be quietly reversed later because OAuth looks
more modern. Connecting a YouTube or Facebook account through OAuth would let
the app create the broadcast, set its title and read its health back. It is
also a trap, for three measured reasons:

- **YouTube's `youtube.force-ssl` is a sensitive scope.** An unverified app is
  capped at **100 users for the lifetime of the project**, and that cap cannot
  be reset. User 101 is refused for ever unless the app passes Google
  verification, which for a free app means filming a demo and waiting.
- **The quota is per project, not per user.** 10,000 units a day, shared by
  everybody using the app. One go live is roughly 150 to 200 units across
  `liveStreams.insert`, `liveBroadcasts.insert`, the bind and the status polls,
  so one project covers about 50 to 65 broadcasts a day for the whole user
  base. More needs a compliance audit.
- **Facebook wants App Review and Business Verification** for `publish_video`,
  and Meta has been narrowing Live API access for years.

A stream key has none of that. Unlimited users, no gatekeeper, nothing that can
be withdrawn by a third party.

**The accessibility argument for OAuth is weaker than it looks**, which is what
settles it. Both platforms have persistent keys: YouTube's Stream tab key does
not change, and Facebook has a persistent key option in Live Producer. So the
key is a **one time setup per platform**, not an errand before every show, and
after that going live is one keystroke either way.

What the app owes the user instead is making that one time as painless as
possible: a command that opens the right page, a paste field, validation before
going live rather than a failure at air time, and the key kept somewhere
sensible.

**Viewer count is the one real loss.** `streamstats.py` reports Icecast
listeners today and there is no way to get the YouTube equivalent without the
API. Out of scope. If it is ever wanted, it is an optional extra on top of
keys, never a replacement for them.

### The key is not a password, and the board file is the wrong place

Today `stream_password` is a `STATION_FIELDS` entry and goes into the board
file, which is plain JSON that a user can save anywhere with `Ctrl+F12` and
send to somebody.

An Icecast source password is bad enough there. **A YouTube stream key is
worse**: anyone holding it can broadcast to that channel, and it is not obvious
from looking at a board file that it is in there. The original streaming plan
said to keep credentials out of the board file and that has not happened yet.

This feature is the moment to fix it. Windows Credential Manager, or the config
directory, keyed by station name, with the board file holding only the name.
There is a migration for anyone who already has a saved station.

---

## 6. The still card, which is the feature for most of the audience

Measured: a static 720p30 card costs **64 kbps and six per cent of one core.**

That number decides a lot. It means "go live on YouTube with no camera" is
nearly free, and it is what most of this app's users will want. A blind
presenter running a radio show has no reason to be on camera and every reason
to be on YouTube, where the audience is.

So the picture is a **source**, and a camera is only one kind:

- **A card.** Station name, artist and title, a clock. Drop Deck already knows
  all of it: `PlaylistPlayer._playlist_moved` is where the now playing title is
  pushed today, and it can redraw a card at the same moment. This is the
  default.
- **An image file.** The user's own artwork, scaled and letterboxed.
- **A camera.** Everything in section 3.

It is also the honest failure mode for a camera. A camera that fails or gets
taken by another program falls back to the card and says so once, rather than
taking the stream down. A presenter mid show needs the show to continue.

---

## 7. Build order, so there is a working app at every step

Each of these leaves something shippable, and the early ones are worth having
even if the later ones never happen.

1. **The `Destination` refactor.** Icecast and SHOUTcast move behind it, no
   behaviour changes, existing tests keep passing. Nothing user visible.
2. **`RtmpDestination`, audio plus a black frame, to a local RTMP server.**
   Proves handshake, FLV muxing and timestamps with nothing riding on it. This
   is where a local server earns its keep, the way `tools/mock_icecast.py`
   already does for Icecast.
3. **The card renderer.** Text on a background, redrawn when the title changes.
   Testable with no network: render, encode, decode, assert the picture.
4. **Offline end to end on Windows.** Card plus real programme audio to a local
   server, checked for A/V sync over a long run. **Nothing is installed, pushed
   or deployed before this passes.**
5. **YouTube for real**, with a test broadcast on an unlisted stream. This is
   the first point anything leaves the machine.
6. **Facebook**, which is the same code and a different URL.
7. **Camera capture**, with the fallback to the card and the in use error
   translated.
8. **Framing announcements**, the detector, the three levels and the key.
9. **The UI and the settings**, once the shape is known rather than guessed.

Steps 1 to 4 are all offline. That is deliberate and it matches what Tony asked
for: prove it on Windows, offline, before anything ships.

---

## 8. The Mac, which is not in this

`mac/` has **no FFmpeg at all.** It is native AVFoundation and AudioToolbox,
and `StreamOut.swift` writes the Icecast and SHOUTcast protocols by hand over
`Network`. That was the right call for audio and it is why the Mac copy is
small.

RTMP on that footing means writing an **RTMP client and an FLV muxer in Swift**:
the C0/C1/C2 handshake, chunk streams, AMF0, and the `connect`, `releaseStream`,
`FCPublish`, `createStream`, `publish` sequence, over TLS. Video itself is the
easy half, because VideoToolbox does H.264 and AVFoundation does cameras, both
natively and both royalty free.

Call it a fortnight of Swift, and it is not started until Windows is proved.
**The two copies have shared a version number since 3.2.2 and this breaks
that.** Either the Mac stays a release behind for a while, or Windows ships
this as a Windows only version and says so plainly in the notes. Worth deciding
before the release rather than during it.

---

## 9. What this is not

- **Not a replacement for OBS.** No scenes, no overlays, no window capture, no
  compositing. One picture source and the programme audio.
- **Not multi destination.** Icecast and YouTube at the same time is two
  encoders and roughly twice the upload. It falls out of the `Destination`
  refactor almost free later, but it is not step one.
- **Not Twitch**, though Twitch is the same RTMP code and a different URL, so
  it costs about an hour once YouTube works.
- **Not SRT.** Not compiled into this FFmpeg build.

---

## Sources

- [YouTube live encoder settings](https://support.google.com/youtube/answer/2853702)
- [Go live on Facebook using streaming software](https://www.facebook.com/help/587160588142067)
- [PyAV FFmpeg binary builds](https://github.com/PyAV-Org/pyav-ffmpeg)
- [BasswoodAV, the LGPL wheels](https://github.com/basswood-io/BasswoodAV)
- [FFmpeg licensing](https://ffmpeg.org/legal.html)
- [OpenCV FaceDetectorYN](https://docs.opencv.org/4.x/df/d20/classcv_1_1FaceDetectorYN.html)
