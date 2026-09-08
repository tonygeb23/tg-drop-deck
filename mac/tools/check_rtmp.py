"""A real broadcast to a real RTMP server, decoded frame by frame.

The counterpart to the Windows `tools/check_switching.py`, and the reason the
Mac's RTMP client could be written at all without touching anybody's channel.

**A stream that connects and sends silence looks exactly like a working one
from the sending end.** So this does not check that bytes left the machine. It
publishes to `tools/mock_rtmp.py`, which keeps every message it is sent and
rebuilds them into an FLV, and then DECODES that FLV and looks at the pixels
and the samples. Nothing here touches the internet.

    python3 mac/tools/check_rtmp.py

What it proves, and each of these has been wrong at least once somewhere:

  * the handshake and the five commands a publisher has to send, in order;
  * that the server accepts the publish rather than merely the connection;
  * that the H.264 is High profile at the size asked for, which is what
    YouTube and Facebook require and what Windows' Media Foundation encoder
    could not emit;
  * that the AAC is real AAC at the right rate, with the ADTS header stripped;
  * that the first video frame is a keyframe, so a viewer joining at the top
    sees a picture rather than grey;
  * that the picture is not black and the sound is not silence;
  * and that video and audio finish together, which is the whole point of
    stamping video against the audio sample counter.

Needs the cross check interpreter, because decoding wants PyAV. See
mac/tools/cross_check.py for what that is and how to make one.
"""
import io
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))

TARGET = "arm64-apple-macos14.0"
FRAMEWORKS = ["AppKit", "AVFoundation", "AudioToolbox", "CoreAudio", "Accelerate",
              "UniformTypeIdentifiers", "Network", "Carbon", "Security", "CoreText",
              "CoreGraphics", "CoreMedia", "CoreVideo", "CoreImage", "VideoToolbox",
              "ScreenCaptureKit", "Vision", "ImageIO"]


def build(work):
    """The app's own sources, plus the publisher, as one binary."""
    sources = [os.path.join(ROOT, "mac", "Sources", name)
               for name in sorted(os.listdir(os.path.join(ROOT, "mac", "Sources")))
               if name.endswith(".swift") and name != "main.swift"]
    # swiftc only allows top level statements in a file called main.swift.
    main = os.path.join(work, "main.swift")
    with open(os.path.join(HERE, "rtmp_publish.swift"), "r", encoding="utf-8") as handle:
        body = handle.read()
    with open(main, "w", encoding="utf-8") as handle:
        handle.write(body)

    # LAME is unsigned in the repository and dyld will not load an unsigned
    # library, so this gets its own ad hoc signed copy. build.sh signs the one
    # that ships.
    vendor = os.path.join(ROOT, "mac", "vendor")
    dylib = os.path.join(work, "libmp3lame.dylib")
    import shutil
    shutil.copy(os.path.join(vendor, "libmp3lame.dylib"), dylib)
    subprocess.run(["codesign", "--force", "--sign", "-", dylib],
                   capture_output=True, text=True)

    binary = os.path.join(work, "publish")
    flags = ["swiftc", "-O", "-target", TARGET,
             "-import-objc-header", os.path.join(ROOT, "mac", "Sources", "LAMEBridge.h"),
             "-I", os.path.join(vendor, "include"), "-L", vendor, "-lmp3lame",
             "-Xlinker", "-rpath", "-Xlinker", work, "-o", binary]
    for framework in FRAMEWORKS:
        flags += ["-framework", framework]
    made = subprocess.run(flags + sources + [main], capture_output=True, text=True)
    if made.returncode:
        raise SystemExit("the publisher did not compile:\n" + made.stderr)
    return binary


def main():
    import mock_rtmp
    problems = []

    def check(name, condition, detail=""):
        print("  %s  %s%s" % ("ok  " if condition else "FAIL", name,
                              "" if not detail else "  " + str(detail)))
        if not condition:
            problems.append(name)

    with tempfile.TemporaryDirectory() as work:
        print("Building the publisher out of the app's own sources...")
        binary = build(work)
        with mock_rtmp.spawn(seconds=40) as server:
            print("Publishing to %s" % server.url)
            out = subprocess.run([binary, server.url], capture_output=True,
                                 text=True, timeout=180)
            for line in out.stdout.strip().splitlines():
                print("   ", line)
            if out.returncode:
                print(out.stderr.strip()[:2000])
                raise SystemExit("the publisher failed")
            result = server.finish()

    print("")
    print("What the server received, decoded:")
    check("the five publisher commands arrived in order",
          result.commands == ["connect", "releaseStream", "FCPublish",
                              "createStream", "publish"], result.commands)
    check("the server accepted the publish", result.publishing)
    check("it reported no error", not result.error, result.error)
    check("something arrived", len(result.flv) > 10000, "%d bytes" % len(result.flv))
    if not result.flv:
        raise SystemExit(1)

    import av
    import numpy as np
    container = av.open(io.BytesIO(result.flv))
    kinds = {}
    for stream in container.streams:
        if stream.codec_context is not None:
            kinds[stream.type] = stream.codec_context
    video = kinds.get("video")
    audio = kinds.get("audio")
    check("there is a video stream", video is not None)
    check("there is an audio stream", audio is not None)
    if video is not None:
        check("the video is H.264", video.name == "h264", video.name)
        # Constrained Baseline is what both platforms refuse.
        check("at High profile, which is what the platforms ask for",
              video.profile == "High", video.profile)
        check("at the size that was asked for",
              (video.width, video.height) == (640, 360),
              "%dx%d" % (video.width, video.height))
    if audio is not None:
        check("the audio is AAC", audio.name == "aac", audio.name)
        check("at the sample rate that was asked for",
              audio.sample_rate == 44100, audio.sample_rate)

    vframes = aframes = 0
    first_key = None
    luma, levels, vpts, apts = [], [], [], []
    container = av.open(io.BytesIO(result.flv))
    for packet in container.demux():
        if packet.stream.type not in ("video", "audio"):
            continue
        if packet.dts is None and packet.pts is None:
            continue
        for frame in packet.decode():
            if type(frame).__name__ == "VideoFrame":
                vframes += 1
                if first_key is None and frame.key_frame:
                    first_key = vframes
                if frame.pts is not None:
                    vpts.append(float(frame.pts * packet.time_base))
                if vframes % 20 == 0:
                    luma.append(float(np.asarray(
                        frame.to_ndarray(format="gray")).mean()))
            elif type(frame).__name__ == "AudioFrame":
                aframes += 1
                if frame.pts is not None:
                    apts.append(float(frame.pts * packet.time_base))
                arr = np.asarray(frame.to_ndarray())
                if arr.size:
                    levels.append(float(np.abs(arr).max()))

    check("every video frame decoded", vframes >= 85, vframes)
    check("every audio frame decoded", aframes >= 85, aframes)
    check("the stream opens on a keyframe", first_key == 1, first_key)
    check("the picture is not black", bool(luma) and all(v > 5 for v in luma),
          [round(v, 1) for v in luma])
    check("the sound is not silence", bool(levels) and max(levels) > 0.05,
          round(max(levels), 4) if levels else None)
    if vpts and apts:
        drift = abs(max(vpts) - max(apts)) * 1000
        # The whole reason video is stamped against the audio sample counter.
        check("sound and picture finish together", drift < 100,
              "%.0f ms apart" % drift)

    print("")
    if problems:
        print("%d check%s failed." % (len(problems), "" if len(problems) == 1 else "s"))
        return 1
    print("Everything checked out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
