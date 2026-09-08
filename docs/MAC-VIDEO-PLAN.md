# The Mac catches up: 3.3.2 to 3.5.2

Written 8 September 2026, before any of it is built. Companion to
[VIDEO-STREAMING-PLAN.md](VIDEO-STREAMING-PLAN.md), whose section 8 parked the
Mac with the words "not started until Windows is proved". Tony took it off the
shelf on 8 September. This is the plan it asked for.

Everything in section 1 was measured on Tony's Mac on 8 September 2026, with a
throwaway Swift program, not assumed and not read off a web page.

## The standing instruction this plan obeys

`mac/CLAUDE.md` already wrote down what a Mac port may and may not decide for
itself, and it is worth repeating at the top because it settles most of the
arguments before they start:

> the Mac gets video once Windows is proven stable, and when it does it builds
> on what Windows established rather than inventing its own shape.

So: **every answer Windows arrived at with a measurement behind it is copied,
not reconsidered.** A Mac port that wants a different answer needs a Mac
measurement. Four of those answers matter more than the rest.

1. **One picture source at a time.** A card, an image, a camera, the screen, or
   the screen with the camera inset. No scenes, no layers, no canvas.
2. **Audio is the master clock and video is stamped against it.** Video
   timestamps count frames encoded against the audio sample counter, never a
   wall clock and never the camera's own timing. This is what lets a source be
   swapped mid stream without moving the timeline, and it is the single most
   important thing to carry across.
3. **Anything that blocks belongs on its own thread, and the caller takes the
   last frame it finished.** Never on the thread carrying the audio.
4. **The screen fills the frame and the camera goes in a corner**, because a
   1920x1080 desktop rendered 640 wide is unreadable. That is a fact about eyes
   and pixels, so it holds here too.

## 1. What was measured, on this Mac, on 8 September 2026

| Question | Answer |
|---|---|
| Will VideoToolbox make an H.264 encoder at 1280x720? | Yes, `VTCompressionSessionCreate` returns `noErr` |
| Real time, bitrate, keyframe interval and High profile? | All four set without complaint |
| Can the BT.709 tags that 3.5.0 fixed be set at the encoder? | Yes, and measured later: VideoToolbox converts at 709 whatever they say, so it writes the TAG only. The Windows fault cannot happen. The opposite one can: setting the matrix to 601 would ship 709 pixels labelled 601, which is invisible from the sending end. They are set to 709 and never touched |
| Does a frame actually encode? | Yes, and it gives back **2 parameter sets**, the SPS and PPS the FLV header needs |
| What cameras does this Mac see? | `MacBook Pro Camera` and `Tony's iPhone Camera`, the Continuity one, with no permission granted yet |
| Is screen recording permitted? | `CGPreflightScreenCaptureAccess` is already true |
| Are the frameworks in the SDK? | VideoToolbox, ScreenCaptureKit, Vision, CoreMedia, CoreVideo, CoreImage, CoreGraphics and Security, all present |

**The video half is proved.** Nothing below rests on a guess about whether
macOS can do this.

## 2. The gap, file by file

Twelve Windows modules arrived between 3.4.0 and 3.5.2, about 250 KB of Python.
Here is where each one lands.

| Windows | Mac | How |
|---|---|---|
| `preflight.py` | `Preflight.swift` | **Literal port.** Plain arithmetic over a settings dictionary, no wx, no network. The Windows notes single this out as the one piece portable almost line for line |
| `colours.py` | `Colours.swift` | **Literal port.** Contrast ratios, luminance, the ten schemes, the fringing rule and the even thickness rule. Pure arithmetic, and the numbers must come out identical |
| `health.py` | `Health.swift` | **Literal port.** Black and frozen detection, and the delay that stops a blink setting it off |
| `streamhelp.py` | `StreamHelp.swift` | **Literal port.** It is text, and the same text as the manual |
| `secrets.py` | `Secrets.swift` | Rewritten for **Keychain**. Same door, same two prefixes, same redaction |
| `picture.py` | `Picture.swift` | Core Graphics and Core Text. The card, image files, letterboxing, and the fallback that keeps a show up |
| `overlay.py` | `Overlay.swift` | Core Text. Four named places, the file poll, and the fits check |
| `camera.py` | `Camera.swift` | AVFoundation, on its own thread |
| `screen.py` | `Screen.swift` | ScreenCaptureKit, on its own thread, plus the camera inset |
| `framing.py` | `Framing.swift` | **Vision framework** in place of OpenCV. Same `Reading`, same bands, same three talkativeness levels |
| `vision.py` | `ShotCheck.swift` | URLSession to Anthropic, OpenAI or Google. Named for the feature because `Vision` is a framework |
| `streamout.py`, the RTMP half | `RTMP.swift`, `FLV.swift`, `VideoEncoder.swift` | **The one genuinely new thing.** Section 4 |

Six windows and three Preferences pages come with them:

| Window | Key |
|---|---|
| Video source | `Option+Shift+V` |
| Screen text | `Option+Shift+T` |
| Check my shot | `Option+Shift+D` |
| Colours, and the colour picker inside it | `Option+Shift+C` |
| Going live, the thing `Command+B` now asks first | on the way to air |
| Setting up streaming | Help menu |

Source control also gets its 3.4.3 rebuild: check boxes for muted and solo,
buttons for rename and remove, and the mode gone.

## 3. What the Mac gets free, and what it therefore must not import

Three of Windows' costs do not exist here, and the port should not carry them
across out of habit.

- **Real letters cost nothing.** Windows needed Pillow for a glyph on a pixel,
  and the download grew by about three megabytes. Core Text is already in the
  process. The Mac's download should grow by **almost nothing**, and the block
  font that 3.5.0 replaced should never be written here in the first place.
- **Face detection costs nothing.** Windows needed `opencv-python-headless`.
  `VNDetectFaceRectanglesRequest` is in the SDK, it is better at the job, and
  it removes the "framing turns itself off and says so" branch that exists on
  Windows only because a wheel might be missing.
- **H.264 is hardware here.** Windows ships libx264 and picks AMF, NVENC or QSV
  when it can find them. VideoToolbox is hardware by default on an M series
  Mac, so the encoder list on the Video streaming page has nothing to choose
  between and should not be shown.

The rule that follows: **no new vendored dependency for any of this.** LAME is
in `mac/vendor/` because macOS genuinely has no MP3 encoder at any layer. There
is no second gap of that kind here.

## 3a. The one place the numbers may not match, and why that is right

`overlay.fits` answers "will this title be cut short in the lower third", and
it is the one ported number that **cannot** be made identical, for a reason
worth writing down before somebody tries.

**Measured on this Mac, 8 September 2026.** The same Roboto Bold file, the
same pixel sizes, fifteen strings including the awkward ones. Pillow's
`textlength` against Core Text:

| measured how | worst disagreement |
|---|---|
| Core Text, kerned and shaped | 18.3 px |
| glyph advances summed, unkerned | 18.3 px |
| the same, rounded per glyph | 16.0 px |

The worst case is sixteen letter i's at 66 px, where Pillow says 288 and the
Mac says 272. It is not a bug on either side. **Pillow measures through
FreeType with hinting on**, which snaps stems to the pixel grid and widens a
narrow glyph to keep it drawable; Core Text measures unhinted subpixel
advances. A run of narrow letters is where the two diverge most, which is
exactly what the worst case is.

**So the two copies must not be forced to agree here, because they do not
DRAW the same either.** Windows draws that string 288 px wide and the Mac
draws it 272 px wide. `fits` is a prediction about what THIS machine is about
to render, so a Mac that answered with Windows' number would be wrong about
its own picture in order to agree with another computer.

What must match is the promise, not the arithmetic: **nothing is cut short
without being told first.** That is checked on the Mac the strong way instead,
by rendering the string and measuring the pixels it actually occupies, which
is a better check than either platform's prediction agreeing with the other's.
`fits` is therefore excluded from the cross check by design, and the self test
carries the real assertion.

## 4. RTMP, which is the whole of the risk

Everything above is either arithmetic being retyped or a system framework doing
its job. This is the part nothing does for us.

An RTMP client and an FLV muxer in Swift, over TLS: the C0/C1/C2 handshake, the
chunk stream layer with its four header formats and its timestamp deltas, AMF0
encoding, and the `connect`, `releaseStream`, `FCPublish`, `createStream`,
`publish` sequence. Then FLV tags: an `AVCDecoderConfigurationRecord` built
from the SPS and PPS that section 1 proved come back, AVC NALUs in length
prefixed form, and AAC in an `AudioSpecificConfig` plus raw frames. Call it two
thousand lines.

**It does not need the internet to be built, and that is the important part.**
`tools/mock_rtmp.py` already exists. It speaks enough RTMP to accept a publish,
it keeps every audio and video message it is sent, and it **rebuilds them into
an FLV and decodes it frame by frame**, because a stream that connects and
sends silence looks perfect from the sending end. It was written for the
Windows client and it does not care what language the client is in. So the
Swift RTMP client can be developed and proved against a local server, offline,
before a byte goes to YouTube.

That mock server is the single reason this is a fortnight and not a month.

## 5. The keys

Five new commands, and they form one family with the source key already there.
`Option+Shift` and then a letter, which is the Mac's answer to Windows'
`Alt+Shift`:

| Windows | Mac | What |
|---|---|---|
| `Alt+Shift+S` | `Option+Shift+S` | Audio sources, already shipped |
| `Alt+Shift+V` | `Option+Shift+V` | Video source |
| `Alt+Shift+T` | `Option+Shift+T` | Screen text |
| `Alt+Shift+D` | `Option+Shift+D` | Check my shot |
| `Alt+Shift+C` | `Option+Shift+C` | Colours |
| `Ctrl+Shift+F` | `Command+Shift+F` | What the camera can see |
| `Ctrl+Shift+V` | `Command+Shift+V` | Say what is on screen |
| `Alt+Ctrl+Shift+S` | `Option+Command+C` | Source control, already shipped with the Windows key as an alias |

All seven were checked against the existing table and none is taken. The
frozen digit map is not touched, and neither is any key on it.

**`SelfTest` already refuses a build with two commands on one key**, which is
the guard Windows had to add after `Ctrl+Shift+F` was silently unreachable for
a release. The Mac inherited it early and that check must stay green through
all of this.

## 6. Build order, so there is a working app at every step

Each stage ends in something that can be proved by the app's own checks. No
stage leaves the app unable to open a board or go on the air.

1. **The arithmetic.** `Colours`, `Preflight`, `Health`, `StreamHelp`,
   `Secrets`. No UI, no pixels, no network. Ends with self checks whose numbers
   are compared against the Windows tests, not merely against themselves.
2. **The board.** The twenty new keys read and written, defaults matching
   Windows exactly. The unknown key passthrough already in `Board.swift` means
   a Windows board survives today; this makes the Mac understand it.
3. **The picture, off air.** `Picture`, `Overlay`, and a way to render one
   frame to a PNG so a check can look at it. Nothing is streamed yet.
4. **Camera and screen.** `Camera`, `Screen`, the inset and the corner, each on
   its own thread with the last finished frame handed out.
5. **The encoder.** `VideoEncoder` around VideoToolbox, with the BT.709 tags,
   and the audio sample counter promoted to the master clock in `AirBus`.
6. **RTMP against the mock.** `FLV`, `RTMP`, and `tools/mock_rtmp.py` as the
   far end. Decoded and checked frame by frame before anything is real.
7. **The windows and the keys.** All six, the three Preferences pages, the
   menu, and the source control rebuild.
8. **Framing and the shot check.** Vision framework, then the AI providers.
9. **A real broadcast**, to Restream first because every channel can be turned
   off there and the stream reaches Restream and goes nowhere. Then YouTube
   private, then Facebook.
10. **The manual, the checks and the release.** `mac/check_guide.py` keeps the
    Mac page honest and it will fail loudly until the page is written.

## 7. What this is not

The Windows list in section 9 of the other plan holds here without change: no
scenes, no layers, no window capture, no compositing, no multi destination, no
SRT. Adding any of them on the Mac would be the port inventing its own shape,
which is the one thing it was told not to do.

## 8. The version, and the thing worth saying out loud

This lands as **3.5.2 on the Mac**, matching Windows, and the two copies share
a version number again for the first time since 3.3.2.

Worth recording, because the earlier plan asked for it to be decided rather
than discovered: **Windows 3.5.2 shipped the same day this was started, and
3.5.1 was fixing faults in a 3.5.0 that was hours old.** The original condition
was "not started until Windows has been quiet for a while", and it has not been
quiet. Tony's call, made knowingly. The mitigation is in the build order: the
arithmetic is ported from the Windows source as it stands today and checked
against the Windows tests' own numbers, so if Windows corrects one of those
numbers later the Mac's check fails rather than the Mac quietly disagreeing.
