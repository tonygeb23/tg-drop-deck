# The Mac video pipeline, measured

Written 8 September 2026. Companion to
[MAC-VIDEO-PLAN.md](MAC-VIDEO-PLAN.md), which said what to build, and to
[VIDEO-STREAMING-PLAN.md](VIDEO-STREAMING-PLAN.md), which is what Windows
settled. This is the pipeline underneath both: what format a frame is in at
every step, what each step costs, and why.

**Every number below was measured on Tony's Mac on 8 September 2026 with
throwaway Swift programs, unless it is explicitly marked as coming from
documentation or as not measured.** Where a number contradicts an assumption
in the earlier plans, that is said plainly rather than quietly corrected.

The machine: MacBook Pro `Mac16,1`, Apple M4, 4 performance and 6 efficiency
cores, 16 GB, macOS 26.5.2 build 25F84, Xcode 26.2 with Swift 6.2.3. Every
spike was built with `swiftc -O -target arm64-apple-macos14.0`, the same
target `mac/build.sh` uses, so nothing here depends on a newer SDK than the
app already asks for.

---

## 0. The short version

| Question | Answer, measured |
|---|---|
| Can VideoToolbox meet what YouTube and Facebook ask for? | Yes, and one property does the work Windows needed three x264 options for |
| What does the picture cost at 720p30? | **1.6 to 2.8 per cent of one core** for the encoder, and 0.2 per cent more for the colour conversion when there is one |
| Headroom at 720p30 | **7.4 times real time** when the encoder is saturated, at 5 per cent of one core |
| Headroom at 1080p30 | **3.4 times real time**, at 3 per cent of one core |
| Encoder delay | **Zero frames.** The first packet arrives before the first `EncodeFrame` call returns |
| A still card at a 2500 kbps target | **2375 kbps with `ConstantBitRate`**, 329 kbps without it |
| Screen capture cost to us | **0.085 ms per frame**, and it never blocks the caller |
| Screen capture lateness | **median 5.0 ms**, p95 9.2 ms, against Windows' 16 to 33 ms blocking blit |
| Camera inset | **0.169 ms**, done entirely in the YUV planes with no colour conversion |
| Colour | VideoToolbox already converts at BT.709. The fault Windows had to correct **cannot happen here**, but not for the reason section 1 of the Mac plan assumed |
| The bitstream | **AVCC, four byte length prefixes.** FLV wants exactly that, so there is no conversion to write |
| RTMPS | `Network` reaches both ingests over **TLS 1.3** with no new dependency |

The one thing that is **not** measured is the camera's open time and
steady state latency, and section 4 says why and what to do about it.

The biggest hazard found is not in any of the above. It is that
**ScreenCaptureKit does not send a frame when the screen is not changing**,
which means the Windows staleness rule would declare a perfectly healthy
static screen dead after two seconds. Section 3 has it.

---

## 1. The encoder

### 1.1 The properties, and which ones are really taken

Every property below was set on a `VTCompressionSession` created with
`kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder`, and the
return status recorded. This is the settled list:

```swift
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_RealTime,                  value: kCFBooleanTrue)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_ProfileLevel,              value: kVTProfileLevel_H264_High_AutoLevel)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_AllowFrameReordering,      value: kCFBooleanFalse)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_H264EntropyMode,           value: kVTH264EntropyMode_CABAC)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_ExpectedFrameRate,         value: 30 as NSNumber)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_MaxKeyFrameInterval,       value: 60 as NSNumber)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_MaxKeyFrameIntervalDuration, value: 2.0 as NSNumber)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_ConstantBitRate,           value: 2_500_000 as NSNumber)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_ColorPrimaries,            value: kCVImageBufferColorPrimaries_ITU_R_709_2)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_TransferFunction,          value: kCVImageBufferTransferFunction_ITU_R_709_2)
VTSessionSetProperty(s, key: kVTCompressionPropertyKey_YCbCrMatrix,               value: kCVImageBufferYCbCrMatrix_ITU_R_709_2)
```

All eleven return `noErr` at 1280x720 and at 1920x1080.

**Two things are refused, and both matter.**

`kVTCompressionPropertyKey_MaxFrameDelayCount` is refused at every value
tried, 0, 1, 2 and `kVTUnlimitedFrameDelayCount`, all with `-12900`
`kVTPropertyNotSupportedErr`. It is nevertheless listed in
`VTSessionCopySupportedPropertyDictionary`, which is worth knowing before
somebody spends an afternoon on it: **the supported list is not a promise that
a value will be accepted.** It does not matter in the end, because section 1.4
shows the encoder holds no frames anyway, but it does mean the app has no knob
to force that behaviour if a future macOS changes it.

`kVTVideoEncoderSpecification_EnableLowLatencyRateControl` looks like exactly
what a live stream wants and is a trap. It is not in the supported property
dictionary at all; the session is created with it, and then
`ConstantBitRate` is refused, and, measured at exactly 30 fps for ten seconds,
**it delivered 44 of 300 frames at 720p and 43 of 300 at 1080p.** Eighty five
per cent of the picture thrown away, with no error anywhere. Do not enable it,
and this note is here so nobody tries it again.

### 1.2 The bitrate, which is the whole of the still card problem

Windows found that a station card compresses to almost nothing, sat far
underneath Facebook's published floor of 400 kbps, and needed
`nal-hrd=cbr` with `filler=1` to pad the stream up to the rate that was asked
for. `minrate` and `maxrate` alone did not do it.

The same test on the Mac, ten seconds fed at exactly 30 fps, once with a still
card and once with a moving screen full of text:

| Content | Rate control | Target | Delivered |
|---|---|---|---|
| Still card | `AverageBitRate` only | 2500 | **329 kbps, 13 per cent** |
| Still card | `AverageBitRate` + `DataRateLimits` | 2500 | **244 kbps, 10 per cent** |
| Still card | **`ConstantBitRate`** | 2500 | **2375 kbps, 95 per cent** |
| Busy screen | `AverageBitRate` only | 2500 | 2507 kbps, 100 per cent |
| Busy screen | `AverageBitRate` + `DataRateLimits` | 2500 | **1747 kbps, 70 per cent** |
| Busy screen | **`ConstantBitRate`** | 2500 | 2500 kbps, 100 per cent |

At 1080p with a 4500 kbps target the shape is identical: 506, 400 and 4274
kbps on the card, and 4524, 3150 and 4503 on the moving screen.

Two conclusions, and neither is obvious from the documentation.

**`kVTCompressionPropertyKey_ConstantBitRate` is the answer, and it is the
exact counterpart of x264's `nal-hrd=cbr filler=1`.** It is the only setting
that meets a floor. Windows got 2467 of 2500 on a card; the Mac gets 2375 of
2500. Both are an order of magnitude clear of Facebook's 400.

**`DataRateLimits` is worse than useless here and must not be set.** It is a
cap, so it cannot lift a card off the floor, and on moving content it cost
thirty per cent of the bitrate that was asked for and paid for. A stream at 70
per cent of its target is a visibly softer picture for nothing.

`ConstantBitRate` was accepted on every hardware session tried here, and it is
the only rate control property in the list that was ever refused by anything
(the low latency session in section 1.1 turns it down). **This machine has
only the one encoder, so what an older Intel Mac does with it is not measured
and should not be assumed.** The code should read the return status, fall back
to `AverageBitRate` alone if it is refused, and say in the pre-flight that it
has had to, because that is the difference between a card at 2375 kbps and a
card at 329.

### 1.3 Keyframes, profile and entropy

**The keyframe interval behaves.** With `MaxKeyFrameInterval` at 60 and
`MaxKeyFrameIntervalDuration` at 2.0, every run produced exactly 5 keyframes
in 10 seconds, on still content and on content that changed completely every
frame. **VideoToolbox does not insert extra keyframes on a scene change**,
which is the whole reason Windows had to add `sc_threshold=0` and `keyint_min`
to libx264 after measuring a keyframe every seven frames on changing content.
Cutting from the card to the camera is exactly that case, and here it costs
nothing. Both properties are set anyway, because the frame count is what the
platforms police and the duration is what protects it if the frame rate is
ever changed.

**Profile and level, measured from the SPS that comes back:**

| Asked for | profile_idc | level_idc |
|---|---|---|
| 720p30 2500k, High AutoLevel | 100 (High) | 31, level 3.1 |
| 1080p30 4500k, High AutoLevel | 100 (High) | 40, level 4.0 |
| 1080p30 6000k, High AutoLevel | 100 (High) | 40, level 4.0 |
| 720p30 2500k, Main AutoLevel | 77 (Main) | 31, level 3.1 |

High profile at level 3.1 and 4.0 is inside what both platforms take, and
`AutoLevel` picks correctly without being told. There is no reason to pin a
level, and pinning `kVTProfileLevel_H264_High_4_0` at 720p just declares 4.0
for a picture that needs 3.1, which helps nobody.

**CABAC, not CAVLC**, and there is a number for it: with everything else
identical and a 2500 kbps target, CAVLC delivered 3400 kbps of the same
picture where CABAC delivered 2460. That is about 38 per cent more bits for
the same thing. CABAC needs Main profile or better, which High is.

**No B frames.** `AllowFrameReordering` set to `false` is not a preference,
it is what makes the timestamps simple, and this was checked rather than
assumed. With reordering **on**, the presentation timestamps genuinely go
backwards, 14 times in 30 frames, and the decode timestamps become valid and
different. With it **off**, `CMSampleBufferGetDecodeTimeStamp` returns an
invalid `CMTime` on every single frame. That is exactly what is wanted: an
invalid DTS means there is nothing to reorder, so the FLV composition time
offset is zero and the FLV timestamp is the presentation timestamp. Section 7
depends on this.

### 1.4 What it costs, and what delay it adds

Fed at exactly 30 fps for ten seconds, which is what the app really does:

| Size | Rate control | CPU, of one core | `EncodeFrame` median | p95 | worst seen |
|---|---|---|---|---|---|
| 1280x720 | ConstantBitRate | **2.8 per cent** | 0.49 ms | 0.76 ms | 18.2 ms |
| 1280x720 | AverageBitRate | 1.6 per cent | 0.34 ms | 0.77 ms | 17.9 ms |
| 1920x1080 | ConstantBitRate | **2.9 per cent** | 0.54 ms | 0.95 ms | 21.6 ms |
| 1920x1080 | AverageBitRate | 3.0 per cent | 0.57 ms | 0.97 ms | 20.7 ms |

**The encoder holds no frames.** At real time pacing the output callback fired
*inside* the first `VTCompressionSessionEncodeFrame` call, before it returned,
on every configuration tried. That is zero frames of added delay. For
comparison, Windows measured `h264_mf` holding sixteen frames, which is 533 ms
added to every broadcast, and libx264 holding none. VideoToolbox is in the
libx264 camp and there is nothing to work around.

That zero is only true when frames arrive at the rate they claim. Fed as fast
as the loop could go, the first output came after three or four frames had
been submitted, which is the queue applying back pressure rather than the
encoder delaying anything. Worth knowing because a catch up burst will look
like latency and is not.

**Saturated throughput**, feeding 600 frames of text heavy moving content as
fast as the encoder would take them:

- 1280x720: **221 fps, 7.4 times real time**, at 5 per cent of one core.
- 1920x1080: **103 fps, 3.4 times real time**, at 3 per cent of one core.

The CPU figures are the point. The limit is the media engine, not the
processor, so the encoder can be saturated and the app is still doing
essentially nothing. Windows measured 11 times real time at 720p and 5 times
at 1080p with libx264 on a different machine, so raw throughput is a little
lower here, but libx264 buys that throughput with real CPU where this does
not. On simpler content the same test reached 465 fps at 720p, so treat 221
as the conservative figure and 7.4 times real time as the headroom to design
against.

**One outlier is worth recording rather than smoothing away.** In one run of
300 frames, a single `VTCompressionSessionEncodeFrame` call took 101 ms. It
was one call in 300 and the p95 was under 1 ms, but it is a real measurement
and it is the reason the encode call must never be anywhere near the audio
callback. Section 6 says where it does go and why 101 ms is survivable there.

### 1.5 Colour, and a correction to the Mac plan

Section 1 of `MAC-VIDEO-PLAN.md` records that the BT.709 tags are settable as
encoder properties, and concludes "so the fault Windows had to correct by hand
cannot happen here". **The conclusion is right and the reasoning is wrong, and
the difference matters.**

The test: encode four flat colour bands, decode the H.264 back to 420v, and
read the luma. BT.709 at limited range wants red at Y=63, green at 173, blue
at 32 and mid grey at 126. BT.601 wants red at 81, green at 145 and blue at
41. Windows measured swscale producing 81 and 41, which is a standard
definition matrix on a high definition picture, and had to force it.

| What was set | red Y | green Y | blue Y |
|---|---|---|---|
| BGRA handed straight to VideoToolbox, all three properties set to 709 | **63** | **173** | 32 |
| vImage converted to 420v at 709 first, then encoded | **63** | **173** | 32 |
| BGRA in, **no colour properties set at all** | **63** | **173** | 33 |
| BGRA in, `YCbCrMatrix` deliberately set to **601** | **63** | **173** | 33 |

Read the last two rows again. **The property does not choose the conversion.
It only writes the tag.** VideoToolbox converts RGB at BT.709 for these sizes
whatever it is told, so the good news is that the default is already correct
and the Windows fault genuinely cannot happen. The bad news is the trap it
creates: setting `YCbCrMatrix` to 601 produced a stream whose pixels are 709
and whose **tag says 601**, and the tag really does travel. The SPS changed
from `27 64 00 1f ac 56 80 50 05 ba 6a 02 02 02 04` to
`... 02 02 0c 04`, one byte in the VUI, and every player downstream would then
apply the wrong matrix to correct pixels. That is a worse bug than the one
Windows had, because the picture would be wrong on other people's screens and
right on the sender's.

**So: set all three to 709, because that is what the encoder is doing anyway,
and treat them as documentation of a fact rather than as a control.** Never
offer them as a setting.

This also confirms the Windows note that "an FLV carries no colour metadata of
its own, so the H.264 sequence header is the ONLY place the tag can travel".
It travels in the SPS VUI, automatically, and there is nothing to write.

---

## 2. The pixel path

### 2.1 The rule

**A frame should be `kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange`, IOSurface
backed, at exactly the encoder's size, from as early in its life as
possible.** Everything below is the evidence for that sentence.

Both real sources can produce it natively:

- **ScreenCaptureKit** delivers 420v, IOSurface backed, scaled to whatever
  size is asked for, at no cost to us. Section 3.
- **AVCaptureVideoDataOutput** lists `420v` in
  `availableVideoPixelFormatTypes`, and every format the built in camera
  offers is already 420v. Section 4.

So for the screen and the camera there is **no colour conversion anywhere in
the pipeline**. The only source that has to be converted is the one the app
draws itself, and drawing is a Core Graphics job which means BGRA.

### 2.2 What each conversion costs

BGRA to 420v at limited range with the BT.709 matrix, median of 200 runs:

| Route | 1280x720 | 1920x1080 |
|---|---|---|
| **vImage** `vImageConvert_ARGB8888To420Yp8_CbCr8` | **0.061 ms** | **0.120 ms** |
| vImage, source not IOSurface backed | 0.088 ms | 0.126 ms |
| `VTPixelTransferSession` | 0.418 ms | 0.777 ms |
| Core Image, GPU context | 0.563 ms | 0.980 ms |
| Core Image, software context | 0.567 ms | 0.983 ms |

**vImage wins by seven to sixteen times and it is not close.** Core Image is
the same speed with the GPU as without, which says the cost is the round trip
rather than the arithmetic, and `VTPixelTransferSession` is a real option that
buys nothing here. The conversion matrix is generated once with
`vImageConvert_ARGBToYpCbCr_GenerateConversion` using
`kvImage_ARGBToYpCbCrMatrix_ITU_R_709_2` and a limited range
`vImage_YpCbCrPixelRange` of 16 to 235 for luma and 16 to 240 for chroma, and
kept for the life of the session, because generating it per frame would cost
more than the conversion.

Note the channel map. A `kCVPixelFormatType_32BGRA` buffer is BGRA in memory,
and `vImageConvert_ARGB8888To420Yp8_CbCr8` wants ARGB, so the permute map is
`[3, 2, 1, 0]`. Getting that wrong swaps red and blue and produces a picture
that looks deliberate.

### 2.3 Does VideoToolbox convert BGRA internally, and what does that cost?

Yes, and the cost is not visible. Feeding the same 300 frames as BGRA and as
420v, the mean `EncodeFrame` call was 4.56 ms against 4.66 ms, which is
inside the noise, and the colour comes out identical (section 1.5).

So handing the encoder BGRA is a legitimate option and it is **not** the one to
take, for two reasons that are not about speed.

First, it moves the conversion somewhere the app cannot see, measure or tag.
Second, the encoder produced a slightly different bitrate from the two inputs,
2567 kbps against 2469 for the same target, which means the internal path is
not bit identical to the vImage one. Doing it ourselves at 0.061 ms means one
conversion, in one place, with one matrix, that a self check can inspect.

### 2.4 IOSurface, and the encoder's own pool

`VTCompressionSessionGetPixelBufferPool` hands out **420v, IOSurface backed,
with a stride of 1280 for a width of 1280**, so no row padding at 720p. That
is the encoder telling you exactly what it wants.

Whether the buffer actually comes from that pool turns out not to matter for
speed. Encoding 300 frames from IOSurface backed buffers took 0.66 s against
0.69 s from plain malloc backed ones, with a median `EncodeFrame` of 2.164 ms
against 2.194 ms. **IOSurface backing is not a throughput requirement.**

It is still what the design should use, because it is a requirement for
everything else: ScreenCaptureKit and AVFoundation both deliver IOSurface
backed buffers, and a pipeline that keeps them that way can hand the same
buffer from the capture callback to the encoder with no copy at all. The
buffers the app draws itself should be created with
`kCVPixelBufferIOSurfacePropertiesKey` set to an empty dictionary so they
behave the same way as the ones that arrive.

### 2.5 Scaling

`vImageScale_ARGB8888` from 1920x1080 to 1280x720 costs 0.827 ms with
`kvImageHighQualityResampling` and 0.819 ms without, so **the high quality
flag is free and should always be on**. That is the opposite of the Windows
finding, where `HALFTONE` and `COLORONCOLOR` had to be weighed against
`cv2.INTER_AREA`; here there is nothing to trade.

It is also mostly unnecessary. ScreenCaptureKit scales on its own side for
free, and the camera is asked for the exact format it will deliver, so a
vImage scale is only needed for an image file the user supplied and for the
camera inset.

### 2.6 The whole path, end to end

| Pipeline | Cost | Share of a 33.3 ms frame |
|---|---|---|
| Draw the card with Core Graphics into BGRA, then vImage to 420v | **0.120 ms** | 0.4 per cent |
| Screen arrives as 420v, copied into the frame | **0.017 ms** | 0.05 per cent |
| Screen 420v with the camera inset composited in | **0.169 ms** | 0.5 per cent |

Drawing the card itself is 0.054 ms at 720p and 0.116 ms at 1080p, so the
`Picture.swift` work Core Text and Core Graphics will do is not a budget
concern at any plausible complexity.

---

## 3. The screen

### 3.1 The configuration

```swift
let cfg = SCStreamConfiguration()
cfg.width  = 1280                      // pixels, and SCK scales for us
cfg.height = 720
cfg.pixelFormat = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
cfg.minimumFrameInterval = CMTime(value: 1, timescale: 30)
cfg.queueDepth = 3
cfg.showsCursor = true
cfg.scalesToFit = true
cfg.colorSpaceName = CGColorSpace.itur_709
cfg.capturesAudio = false
```

`pixelFormat` set to 420v works, and the delivered buffers are 420v, IOSurface
backed, at exactly the requested size, on every run. **That is the single most
useful fact in this document**, because it means a shared screen reaches the
encoder without one byte being touched by the CPU.

`queueDepth = 3` is the minimum and it is the right choice, for a reason
section 3.3 measures. `colorSpaceName` is set to 709 so what arrives matches
what the encoder will tag.

Every one of those is set on purpose, and the defaults are worth knowing
because three of them are wrong for this job. Read off a fresh
`SCStreamConfiguration`:

| Property | Default | What we set, and why |
|---|---|---|
| `pixelFormat` | `420v` | 420v, and the default is already right |
| `width`, `height` | 1920x1080 | the stream's size, which is the app's setting |
| `minimumFrameInterval` | 1/60 | 1/30, because twice the frames is twice the work for a 30 fps stream |
| `queueDepth` | **8** | **3**, and section 3.3 has the measurement |
| `scalesToFit` | **false** | **true**, so a 1512 point wide display arrives at exactly 1280x720 |
| `preservesAspectRatio` | true | left alone: letterboxing is right, cropping the presenter's screen is not |
| `showsCursor` | true | left alone |
| `capturesAudio` | false | left alone: the audio is the programme bus, never the machine |

The default `queueDepth` of 8 is the one to be deliberate about. It is not a
buffer that smooths anything out for us; it is eight frames of backlog waiting
to become latency the moment the consumer is slow.

`SCContentFilter(display:excludingApplications:exceptingWindows:)` is the
whole screen. Per window and per application capture exist and are
deliberately not offered, for the reason `screen.py` already gives: a
presenter who cannot see the screens cannot be asked which of "monitor 2" and
"monitor 3" they meant.

Note that `SCDisplay` reports **points, not pixels**: this display reports
1512x982 while the panel is far denser. So the capture size is the app's
choice and must come from the stream settings, never from the display. The
aspect ratios also differ, 1.54:1 against 720p's 1.78:1, so `scalesToFit`
letterboxes and `SCStreamConfiguration.backgroundColor` decides what the bars
are. Set it, or the bars are whatever the default happens to be.

### 3.2 What it costs, on a screen that is really moving

The first run of this test flattered itself, because a mostly still desktop
gives the capture almost nothing to do. So the spike put an animated window on
screen redrawing at 60 Hz for the length of the run. Six seconds each:

| Configuration | Delivered | Gap median | Gap p95 | Lateness median | Lateness p95 | Our handler |
|---|---|---|---|---|---|---|
| 420v 1280x720 at 30 | **30.3 fps** | 33.9 ms | 36.2 ms | **5.03 ms** | 9.16 ms | 0.085 ms |
| BGRA 1280x720 at 30 | 30.5 fps | 33.8 ms | 36.2 ms | 3.98 ms | 9.01 ms | 0.074 ms |
| 420v 1920x1080 at 30 | 29.5 fps | 34.0 ms | 35.3 ms | 4.44 ms | 8.96 ms | 0.086 ms |

Lateness is the time from the frame's own `SCStreamFrameInfo.displayTime`,
converted through `CMClockMakeHostTimeFromSystemUnits`, to the moment our
callback ran.

**Against the Windows number this is the good news of the whole port.** A
Windows desktop blit costs 16 to 33 ms and **blocks the caller**, which is the
entire 30 fps budget on the thread carrying the audio. Here the frame arrives
5 ms after it was composited, on a queue of our choosing, and holding onto it
costs 0.085 ms. Full 1080p capture costs the same as 720p.

Enumerating the shareable content takes 23 to 44 ms, `startCapture` returns in
31 to 51 ms, and the first frame arrives 40 to 92 ms after that. Windows
allows `SCREEN_OPEN_TIMEOUT = 3.0` seconds; the Mac needs a fraction of it,
but the constant should stay generous because it costs nothing to wait for a
machine under load.

### 3.3 Queue depth, and what a slow consumer does

The handler is meant to do nothing but keep the last finished frame. To find
out what happens if it ever does more, the spike deliberately spent 40 ms in
the callback:

| Queue depth | Delivered | Gap median | Lateness median |
|---|---|---|---|
| 5 | 23.5 fps | 44.8 ms | **171.3 ms** |
| 3 | 23.2 fps | 44.4 ms | **83.8 ms** |

**The queue depth multiplies the latency of a slow consumer**, almost exactly:
five deep is roughly five frame periods of backlog, three deep is three, and
the default of 8 would be worse again. For a live stream that only ever wants
the newest frame, a deep queue buys nothing and costs delay, so
`queueDepth = 3`. Depth 8 was also tried with a fast handler and made no
difference at all, which is the trap: the default looks harmless right up to
the moment the machine is busy.

### 3.4 The hazard: a still screen sends nothing

This is the one that would have shipped as a bug.

On a mostly still desktop, six seconds at 30 fps produced **46 frames with
status `complete` and 142 with status `idle`**. ScreenCaptureKit delivers a
sample buffer on schedule, but when nothing on screen has changed it carries
no image and its `SCStreamFrameInfo.status` is `.idle`. Real frames arrived at
7.7 fps, not 30.

Windows has no equivalent. A GDI blit always returns the current desktop
whether or not it changed, which is why `screen.py` can say
`SCREEN_STALE_SECONDS = 2.0` and mean it: no frame for two seconds really does
mean the capture has died.

**Copy that constant literally onto the Mac and a presenter showing a static
slide for three seconds has their screen source declared dead and replaced by
the station card.** That is a broadcast fault, in the middle of a show, caused
by nothing being wrong.

The rule the Mac needs instead:

- `.complete` is a new picture. Keep it and stamp the time.
- **`.idle` is a heartbeat.** The source is alive and the picture is
  unchanged, so refresh the liveness clock without replacing the frame.
- `.blank` and `.suspended` are real trouble and should count against
  staleness, because the viewer is genuinely seeing nothing.
- **No callback at all** for longer than the timeout is the only thing that
  should take the source down, and that is what `didStopWithError` and a
  watchdog are for.

So the Mac keeps two clocks where Windows keeps one: when the picture last
changed, and when the capture last said anything. Only the second one decides
whether the source is dead. The first one is still useful, because it is what
`Health.swift` needs to tell a frozen picture from a still one.

---

## 4. The camera

### 4.1 What was measured

Enumeration needs no permission and was measured properly.
`AVCaptureDevice.DiscoverySession` with device types `.builtInWideAngleCamera`,
`.external`, `.continuityCamera` and `.deskViewCamera` takes **176 to 180 ms**
and finds four devices on this machine:

| Name | Type |
|---|---|
| MacBook Pro Camera | `builtInWideAngleCamera` |
| MacBook Pro Desk View Camera | `deskViewCamera` |
| Tony's iPhone Desk View Camera | `deskViewCamera` |
| Tony's iPhone Camera | `external`, the Continuity one |

Two notes for the source list. **Desk View cameras should not be offered**:
they are a downward facing crop of the same sensor, they are not what anybody
means by "my camera", and offering four entries for two physical cameras is
exactly the kind of list that is worse for being complete. **The Continuity
camera arrives as `external`**, not as `.continuityCamera`, so filtering by
device type would silently drop it.

Every format the built in camera offers is **420v**, which is the format the
encoder wants:

```
1920x1080 up to 30 fps    1760x1328 up to 30 fps    1552x1552 up to 30 fps
1328x1760 up to 30 fps    1280x720  up to 30 fps    1080x1920 up to 30 fps
 640x480  up to 30 fps
```

`AVCaptureVideoDataOutput.availableVideoPixelFormatTypes` reports `2vuy`,
`yuvs`, `420v`, `420f` and `BGRA`. Asking for `420v` therefore costs nothing:
it is what the device produces and what the encoder consumes.

### 4.2 The configuration

No preview layer is involved anywhere. A preset is deliberately not used
either, because a preset picks its own size and the encoder is locked to one
size from the moment the FLV header goes out:

```swift
session.beginConfiguration()
session.addInput(try AVCaptureDeviceInput(device: device))
let out = AVCaptureVideoDataOutput()
out.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String:
                     kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange]
out.alwaysDiscardsLateVideoFrames = true          // we only want the newest
out.setSampleBufferDelegate(sink, queue: cameraQueue)
session.addOutput(out)
try device.lockForConfiguration()
device.activeFormat = chosenFormat                 // exact size, chosen by us
device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 30)
device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 30)
device.unlockForConfiguration()
session.commitConfiguration()
```

`alwaysDiscardsLateVideoFrames` is the AVFoundation spelling of the rule the
whole pipeline follows: the caller takes the last frame that finished, and an
old one is of no use to anybody.

### 4.3 What was NOT measured, and why

**Open time and steady state latency could not be measured.** Frame delivery
needs the camera TCC grant, and macOS would not give one to a throwaway spike:
`AVCaptureDevice.requestAccess(for: .video)` never called back and the
authorisation status stayed `notDetermined` from a plain command line binary,
from an ad hoc signed `.app` in a temporary directory, and from the same
bundle in `~/Applications` running with a `.regular` activation policy and an
`NSCameraUsageDescription` in its `Info.plist`. No prompt was ever presented.
Nothing was done to the privacy database and nothing should be.

**So those two numbers have to come from inside the real signed
`TG Drop Deck.app`**, which is already in `/Applications` and already
Developer ID signed. The right place for it is a self check: open the camera,
time `startRunning` to the first sample buffer, run for a few seconds and
report the gap and lateness distributions in the same shape as the screen
table above. That has value beyond this document, because "how long does my
camera take to wake up" is a thing a presenter genuinely wants answered before
a show.

Until then, the Windows figure stands as the placeholder it is: 0.58 seconds
from open to first frame on a USB webcam, which is why `CAMERA_OPEN_TIMEOUT`
is 5.0 seconds. A built in Mac camera has no USB enumeration to do and should
be quicker, but that is a reasonable expectation and not a measurement, and it
should be labelled as one until somebody runs the check.

### 4.4 A gotcha found on the way

`AVCaptureDevice.requestAccess(for: .video)` takes a completion handler, and
**blocking the calling thread waiting for it means the prompt can never
appear.** The permission sheet is presented on the main run loop, so a
`DispatchSemaphore.wait()` on the main thread deadlocks the very thing that
would signal it. The completion handler has to return to the run loop. This
cost time here and it will cost it again in `Camera.swift` if it is not
written down.

### 4.5 Two cameras at once

Windows has a whole error path for this, because DirectShow makes a camera
exclusive and then reports the failure as `OSError: [Errno 5] I/O error`,
which tells a presenter nothing. macOS does not behave that way: a camera can
be opened by more than one process, so the OBS case that broke Windows does
not arise. It could not be confirmed here for the permission reason above, so
`Camera.swift` should still translate whatever `AVCaptureDeviceInput(device:)`
throws rather than showing it raw, and the "another program has the camera"
wording should only be used if that is actually what happened.

---

## 5. The camera in the corner

The rule is inherited and not up for redesign: the screen fills the frame and
the camera goes in a corner, because a 1920x1080 desktop rendered 640 wide is
not small text, it is no text. `SPLIT_INSET_WIDTH` is a quarter of the frame,
so 320x180 inside 1280x720, with a 2 pixel border and a 2.5 per cent margin.

Three ways to do it, all measured at 1280x720 with a 320x180 inset:

| Route | Cost | Notes |
|---|---|---|
| **vImage, in the 420v planes** | **0.169 ms** | `vImageScale_Planar8` on luma, `vImageScale_CbCr8` on chroma, then a `memcpy` per row into each plane |
| Core Graphics | 0.149 ms | 0.130 ms for `CGContext.makeImage` from the camera buffer plus 0.019 ms to draw it, in BGRA only |
| Core Image, GPU | 0.707 ms | `composited(over:)` then `CIContext.render` straight to a 420v buffer |

Core Graphics is nominally the fastest and it was checked rather than trusted,
because 0.019 ms for a scaled draw looked too good: the destination pixel at
the inset really does change from 20 to 200 while the middle of the frame
stays 20, so the draw is real and Core Graphics is using Accelerate underneath.

**Use the vImage route in the YUV planes anyway**, and the reason is not the
0.02 ms. It is that both halves already arrive as 420v, so this route never
leaves the encoder's own colour space. The Core Graphics route would mean
converting the camera to BGRA, drawing, and converting the composite back,
which is two conversions at 0.061 ms each plus the draw, and a second chance
to get a matrix wrong. Core Image is four times the cost and buys nothing.

The arithmetic that follows from working in 420 rather than in RGB, and it is
the part that will produce an off by one bug if it is not written down:
**every coordinate must be even.** The chroma plane is half resolution in both
directions, so the inset's left edge, top edge, width and height all have to
be even numbers or the chroma block lands half a pixel out of step with the
luma and the inset gets a coloured fringe down one side. Round the margin and
the box down to even before using them, in one place, and say so in the
comment.

The border is drawn by filling the chroma plane with the accent colour's Cb
and Cr and the luma plane with its Y, which is two `memset` runs per row
rather than one, and is still nothing.

Either half may fail on its own, exactly as on Windows: a camera that refuses
leaves the screen filling the frame, which is a working show, and the screen
failing is what takes the source down to the card.

---

## 6. The audio master clock

### 6.1 The rule, restated

Video PTS counts frames encoded against the audio sample counter, never a
wall clock and never the camera's own timing. This is what lets a source be
swapped mid stream without moving the timeline. Windows validated it at 2 ms
of drift over five seconds against a 100 ms lip sync target.

### 6.2 Where the counter goes

`Streamer.run(rate:)` in `mac/Sources/StreamOut.swift` is already the right
shape for this, and better placed than the Windows equivalent was, because the
Mac already owns its own socket. The loop reads `chunk = encoder.frameSize`
frames from the `AirBus` and encodes them. For AAC, `AACEncoder.frameSize` is
**1024**.

The counter is one line: every time a chunk is successfully taken from the bus
and encoded, add `chunk` to a `framesEncoded` running total. Then

```
audioSeconds = Double(framesEncoded) / rate
```

and that is the master clock. It is deliberately the count of samples
**handed to the encoder**, not the count the sound card produced, because that
is the number the stream's own timeline is built from and it cannot drift
against itself.

Both timestamps come off it:

```
videoPTS(ms) = lround(Double(videoFramesSent) * 1000.0 / Double(fps))
audioPTS(ms) = lround(Double(framesEncodedBeforeThisPacket) * 1000.0 / rate)
```

on FLV's 1/1000 timebase. The same `videoPTS` is what goes into the
`CMTime(value:timescale: 1000)` handed to `VTCompressionSessionEncodeFrame`,
so the encoder, the muxer and the wire all agree by construction rather than
by arithmetic done twice.

### 6.3 The pacing, and why the Mac needs less catching up than Windows

Windows had a problem the Mac does not have. `RtmpDestination.chunk_seconds`
had to be set to `1.0 / RTMP_FPS` because the pump interval **is** the video
pacing: at a quarter of a second, eight frames were muxed back to back and
then nothing left for 200 ms, and the median gap between frames was 11 ms with
a p95 of 192 ms even though the average was a perfect 33 ms.

On the Mac the pump interval is already the AAC packet size, and it is finer
than a video frame:

| Bus rate | 1024 frames is | Video frame period at 30 fps |
|---|---|---|
| 44100 | 23.22 ms | 33.3 ms |
| 48000 | 21.33 ms | 33.3 ms |

So the loop comes round 43 times a second and needs to emit 30 frames a
second. **The pacing problem does not arise**, and `C.streamPollSeconds` at
0.02 already matches. Nothing has to change about the loop's rhythm to add
video to it.

### 6.4 The catch up rule, ported

`_pump_video` in `streamout.py`, in Swift, called once per audio chunk with
the seconds of audio just handed over:

```swift
func pumpVideo(justFed seconds: Double) {
    let due    = Int(audioSeconds * Double(fps))
    let earned = Int(seconds * Double(fps)) + 1
    let limit  = min(due, videoFramesSent + max(C.rtmpCatchupFrames, earned))
    while videoFramesSent < limit {
        guard let picture = source?.frame(width: w, height: h) else { return }
        encode(picture, pts: lround(Double(videoFramesSent) * 1000.0 / Double(fps)))
        videoFramesSent += 1
    }
}
```

The cap being relative to what was just fed, rather than a flat number, is the
part worth preserving: Windows found that a flat cap either turned a stall
into a burst or let the picture fall permanently behind the sound, and could
not do both.

With `C.rtmpCatchupFrames = 2` and 1024 frames at 44100, `earned` works out at
1 and the cap is 2, which is never binding in the steady state because 43
chunks a second carrying at most 2 frames each is 86 frames of allowance for
30 frames of demand. It binds only after a stall, which is what it is for.

`due` is derived from `audioSeconds`, so a camera running slow simply has its
last frame sent again and one running fast has a frame dropped, and neither
accumulates. That is the same bargain the `AirBus` already makes for two sound
cards that are not quite the same speed, and it is why swapping the source mid
stream moves nothing: the next frame is stamped where it would have been
anyway.

### 6.5 Which thread, and why 101 ms is survivable

Everything that blocks is already off the audio callback by construction.
`AirBus.write` is what the callback touches, and it stays exactly as it is.
The capture callbacks run on their own dispatch queues, provided by us, and do
nothing but keep the last finished buffer at 0.085 ms a time.

The encode call goes on the existing `dropdeck-stream` thread, beside the AAC
encode and the socket write, exactly as Windows keeps it on one thread and one
clock. The worst `EncodeFrame` call seen was 101 ms in 300, and that thread
can absorb it because the `AirBus` ring is `C.airRingSeconds = 2.0` seconds
deep. A 101 ms hiccup is five per cent of the ring, and `behindSeconds`
already reports how full it is, so it would show up in the health line rather
than as a dropout.

What must not happen is the encode moving onto the main thread to be near the
UI, or the picture being pulled from inside `AirBus.read`. Both would work in
testing and fail on a busy machine.

### 6.6 Swapping the source mid stream

`set_video_source` on Windows is safe for reasons that hold here word for
word: the encoder is locked to one size and one frame rate from the moment the
header goes out, the source is told the size rather than choosing it, and the
timestamps were never the source's to give. The Swift version is one property
protected by the same lock the rest of `Streamer` uses, read into a local
before use, so the pump gets the old source or the new one and never a half
swapped pair.

One Mac specific addition: a `CVPixelBuffer` handed out by a source must be
retained for as long as the encoder holds it. `VTCompressionSessionEncodeFrame`
retains it itself, so handing over the same buffer twice is safe, but a source
that reuses one buffer and paints into it while the encoder is reading would
tear. Sources should hand out the buffer they just finished and start the next
frame in a different one, which is what both capture APIs do naturally.

---

## 7. RTMP and FLV

### 7.1 What VideoToolbox already gives us

Measured from a real encode, so none of this is read off a specification:

- **Two parameter sets.** SPS 15 bytes,
  `27 64 00 1f ac 56 80 50 05 ba 6a 02 02 02 04`, `nal_unit_type` 7. PPS 4
  bytes, `28 ee 3c b0`, `nal_unit_type` 8.
- **`NALUnitHeaderLength` is 4.** FLV's `AVCDecoderConfigurationRecord` stores
  that minus one in the low two bits of `lengthSizeMinusOne`, so the byte is
  `0xFF`.
- `profile_idc` 100, constraint flags `0x00`, `level_idc` 31.
  **The record's bytes 1 to 3 are exactly those three**, which is the whole of
  the "AVCProfileIndication, profile_compatibility, AVCLevelIndication" field.
- **The bitstream is AVCC, four byte big endian length prefixes.** The first
  sample began `00 00 00 3a` and the total was 57659 bytes, so the first NAL is
  58 bytes and the rest follow it. **FLV wants precisely this form**, so there
  is no Annex B conversion to write, no start code scanning and no
  `CMBlockBuffer` rewriting. This is the single biggest saving in section 7.

The record is therefore assembled directly:

```
01 <profile_idc> <constraints> <level_idc> FF E1 <SPS len:2> <SPS> 01 <PPS len:2> <PPS>
```

and goes out once, in an FLV video tag with frame type 1, codec 7,
`AVCPacketType` 0 and a composition time of 0, before any picture.

Every picture after that is frame type 1 for a keyframe or 2 otherwise,
`AVCPacketType` 1, **composition time 0**, and then the sample's data buffer
copied through unchanged. Composition time is zero because reordering is off
and the decode timestamp is invalid, which section 1.3 measured rather than
assumed.

### 7.2 The AAC side, and a trap in it

FLV's audio tag needs an `AudioSpecificConfig` in its sequence header. The
obvious source is `AVAudioConverter.magicCookie`, and **the obvious source is
wrong**. The cookie is 39 bytes and is an MPEG-4 ES descriptor:

```
44100: 03 80 80 80 22 00 00 00 04 80 80 80 14 40 14 00 18 00 00 01 f4 00 00 01 f4 00 05 80 80 80 02 12 10 06 80 80 80 01 02
48000: 03 80 80 80 22 00 00 00 04 80 80 80 14 40 14 00 18 00 00 01 f4 00 00 01 f4 00 05 80 80 80 02 11 90 06 80 80 80 01 02
```

Passing that whole thing into the sequence header produces a stream nothing
can decode. The `AudioSpecificConfig` is the payload of the descriptor with
tag `0x05`, which is **two bytes**: `12 10` at 44100 and `11 90` at 48000.
Either walk the descriptor to find tag `0x05`, or build the two bytes from the
sample rate index directly. Both were done in the spike and they agree
exactly, which is the cross check worth keeping in a self test.

The second trap is closer to home. `AACEncoder.encode` in
`mac/Sources/StreamOut.swift` prepends a **seven byte ADTS header** to every
packet, because Icecast needs the stream to be self framing. **FLV must not
have it.** RTMP carries raw AAC frames after a one byte header of `AF 01`, and
an ADTS header inside that is 7 bytes of garbage in the middle of every frame.
So the AAC encoder needs a mode that returns the raw packets, or the RTMP
destination needs its own path into the same `AVAudioConverter`. The former is
smaller and keeps one encoder, and it is a two line change to a method that
already loops over `compressed.packetDescriptions`.

### 7.3 The transport

`Network` reaches both ingests with no new dependency, measured with no data
sent and no key involved:

| Endpoint | Result |
|---|---|
| `a.rtmps.youtube.com:443`, TLS | ready in 228 ms, **TLS 1.3** |
| `live-api-s.facebook.com:443`, TLS | ready in 237 ms, **TLS 1.3** |
| `live.restream.io:1935`, plain | ready in 105 ms |
| `a.rtmp.youtube.com:1935`, plain | ready in 121 ms |

`NWParameters.tls` for RTMPS and `.tcp` for plain RTMP is the whole of the
difference, which means the existing `Streamer.connect()` shape carries over.
Set the minimum TLS version to 1.2 explicitly rather than relying on the
default, so a future macOS lowering it does not silently weaken the stream.

### 7.4 The module structure

Six files, none of them touching `Streamer`'s retry loop or its state machine:

| File | What it is | Rough size |
|---|---|---|
| `AMF0.swift` | Numbers, strings, booleans, objects and arrays out; enough decoding to read `_result` and `onStatus` back | 200 lines |
| `RTMPChunk.swift` | The chunk layer: four header formats, timestamp deltas, extended timestamps, chunk size negotiation, message assembly | 350 lines |
| `RTMPClient.swift` | C0/C1/C2, then `connect`, `releaseStream`, `FCPublish`, `createStream`, `publish`; window acknowledgement size, set peer bandwidth, and sending acknowledgements when asked | 500 lines |
| `FLV.swift` | The `AVCDecoderConfigurationRecord`, video tags, the AAC sequence header and audio tags, `@setDataFrame`/`onMetaData` | 250 lines |
| `VideoEncoder.swift` | The `VTCompressionSession` wrapper: the property list from section 1.1, the output callback, parameter set extraction | 300 lines |
| `RTMPDestination.swift` | Owns the two encoders and the client, holds the sample counter and the pump from section 6 | 400 lines |

Two thousand lines, which is what the plan estimated, and the estimate now has
the encoder half proved rather than assumed.

`tools/mock_rtmp.py` is the far end for all of it and it does not care that
the client is Swift. It binds port 0 and reports what it got, keeps every
audio and video message, rebuilds them into an FLV and decodes it frame by
frame, which is the only way to tell a working stream from one that connects
and sends silence.

**One gap in the mock, and it should be closed before it bites.** It speaks
plain RTMP only, so the TLS wrapper is the one part of the transport that gets
no offline test at all and is first exercised against a real platform. That is
the wrong place to find a certificate or ALPN problem. Either add a TLS
listener to the mock, or put `stunnel` in front of it in the test harness. It
is an hour either way and it moves a whole class of failure off the live path.

### 7.5 A shape that follows the Mac rather than Windows

Windows had to invert its architecture, because PyAV opens the network itself
and there is no byte callback and no socket of ours. **The Mac has no such
problem**: `StreamOut.swift` already writes Icecast and SHOUTcast by hand over
`Network`, so the socket is already ours and the `Destination` split is a
smaller change here than it was there.

`Streamer` keeps its retry loop, its backoff, its `behindSeconds` and its
state machine, and stops caring what it is holding. `IcecastDestination` wraps
today's `StreamEncoder` plus the existing `connect`/`send` pair with no
behaviour change, so the existing checks pass untouched.
`RTMPDestination` is the new one, and it is the only thing that knows about
video.

---

## 8. Risks and gotchas

In the order they would hurt.

1. **The still screen staleness rule.** Section 3.4. Copying
   `SCREEN_STALE_SECONDS = 2.0` from Windows literally would drop a healthy
   static screen off the air mid show. This is the one that would have
   shipped, and it is the reason to port behaviour rather than constants.

2. **The camera is unmeasured.** Section 4.3. Open time and steady state
   latency need the real signed app, so the numbers in `constants` for the
   camera are currently Windows numbers wearing a Mac badge. Write the self
   check before writing the timeouts.

3. **`DataRateLimits` looks right and costs 30 per cent of the picture.** It
   is the property whose name most suggests "keep the bitrate where I asked",
   and setting it alongside `AverageBitRate` delivered 1747 kbps of a 2500
   target on moving content. `ConstantBitRate` alone is the answer.

4. **The low latency rate control mode drops 85 per cent of frames**, silently.
   Section 1.1.

5. **Setting `YCbCrMatrix` to anything but 709 ships a lie.** Section 1.5. The
   pixels do not change and the tag does, which is worse than the Windows bug
   because it is invisible from the sending end.

6. **The AAC magic cookie is not an `AudioSpecificConfig`** and the existing
   AAC encoder adds ADTS headers RTMP must not have. Section 7.2. Both are the
   kind of fault that produces a stream a platform accepts and then reports as
   unhealthy, which is the hardest kind to chase.

7. **`VTCompressionSessionEncodeFrame` blocked for 101 ms once in 300 calls.**
   Rare, real, and the reason nothing about the encoder goes near the audio
   callback. The `AirBus` ring absorbs it at 2 seconds deep.

8. **`MaxFrameDelayCount` is listed as supported and refused at every value.**
   Section 1.1. The supported property dictionary is not a promise.

9. **`requestAccess` deadlocks if the caller blocks the main thread.**
   Section 4.4.

10. **Chroma coordinates must be even.** Section 5. An odd inset origin gives a
    coloured fringe down one edge of the camera box, which is exactly the sort
    of fault nobody in this app's audience can see and report.

11. **The mock RTMP server has no TLS**, so RTMPS is first exercised against a
    real platform. Section 7.4.

12. **`SCDisplay` reports points, not pixels**, and the aspect ratio will not
    match 16:9 on a laptop panel. Set `backgroundColor` or accept whatever the
    letterbox bars default to.

13. **Desk View cameras are in the device list** and are not cameras anybody
    means, and the Continuity camera arrives typed as `external`. Section 4.1.

---

## 9. What this settles, and what it does not

Settled, with measurements behind them: the encoder configuration, the rate
control mode, the colour handling, the pixel format end to end, the screen
capture configuration and its real cost, the compositing route, where the
master clock lives, and the exact form the FLV muxer will be handed.

Not settled: the camera's timings, which need the signed app; the RTMP client
itself, which is the two thousand lines nothing does for us; and the real
broadcast, which is still the first point anything leaves the machine and
still belongs on Restream with every channel switched off before it belongs
anywhere else.

Nothing here changes a decision the Windows copy made. Two of them it
strengthens with a Mac number, one of them it corrects on the reasoning while
agreeing with the conclusion, and one of them, the staleness rule, it says
plainly must not be copied.
