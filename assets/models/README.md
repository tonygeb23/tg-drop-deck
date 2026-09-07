# The face detection model, and where it came from

`face_detection_yunet_2023mar.onnx`, 232,589 bytes,
sha256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`.

## What it is for

Telling a presenter who cannot see the screen whether they are in shot.
Centred or off to one side, close or far, lit or dark. See
[docs/VIDEO-STREAMING-PLAN.md](../../docs/VIDEO-STREAMING-PLAN.md) section 3
for why that is the part of camera streaming worth building, and
`dropdeck/framing.py` for what it says out loud.

## Where it came from

[OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet),
the March 2023 release of YuNet, by Wu Wei, Peng Hanyang and Yu Shiqi. The
training code is at
[ShiqiYu/libfacedetection.train](https://github.com/ShiqiYu/libfacedetection.train).

## The licence, which is the easy one for once

**MIT**, the same as Drop Deck and the same as OpenCV Zoo upstream. So unlike
the FFmpeg question in the plan, and unlike LAME on the Mac, there is nothing
to arrange here beyond saying where it came from, which this file does.

## Why this version and not the newest

There is a `2026may` model in the Zoo now, with a dynamic input shape. It is
not used here, on purpose:

- The detector is fed a **fixed 320 by 180** greyscale copy, because that size
  is what makes it cost three milliseconds. A dynamic shape buys nothing when
  the shape never changes.
- The March 2023 model was measured on this machine on 7 September 2026
  against a real camera: **a face found in 36 of 36 checks, 3.0 ms on average
  and 12.6 ms at worst**, confidence around 0.93. That is a fifth of the
  budget for checking three times a second.

If it is ever swapped, measure both numbers again rather than assuming a newer
model is faster. OpenCV 5.0 prints
`Targets are not supported by the new graph engine for now` when the detector
is created. It is a warning about hardware acceleration, not an error, and the
model runs correctly on the CPU regardless.

## Replacing it

`cv2.FaceDetectorYN` is the only thing that reads this file, and it is created
in one place. **OpenCV 5.0 removed `CascadeClassifier`**, so the old Haar
cascade route no longer exists and there is no fallback if this file is
missing: the framing announcements simply turn themselves off and say so.
Streaming is unaffected, which is the right way round.
