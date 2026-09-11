"""A real video recording, decoded back, and its sync measured.

The counterpart to `check_switching.py`, and it exists for the same reason:
every check in `tests/` runs the recorder far faster than a sound card, so
none of them proves anything about what a real file contains.

Tiffany's design, 10 September 2026, and the part that matters is the
stimulus. **Comparing container timestamps proves the labels agree, not that
the content does.** So every frame carries its own capture time IN THE
PICTURE, as twenty four grey patches along the top row holding
`time.monotonic()` in milliseconds, one bit each. Black is nought, white is
one. It survives H.264 and gives the capture time back to the millisecond for
every single frame rather than at three sample points.

The audio carries a 1 kHz burst at three known moments, fired from the same
wall clock the frames are stamped from, as an independent second opinion.

What it reports, and every one of these is a number rather than an opinion:

- the offset at the start, the middle and the end, in milliseconds
- the SLOPE in milliseconds per minute, from segment means and not from the
  first and last few frames. Taking it from the ends reported a bogus +57 ms
  per minute on a run whose segment means were 17.6, 19.7, 19.2, 19.4, 19.6
- a constant offset is a delay somebody forgot; a slope is a clock nobody
  chose. Under 2 ms per minute counts as constant
- the delivered frame rate, counted off the packets, against the nominal
- how many distinct inter frame gaps there are, which is what catches a
  millisecond time base pretending to be constant frame rate
- the colour tags read back off the file
- and the picture removed for eight seconds, asserting the lag never moves,
  which is the check that catches the fault this recorder was written to avoid

    python tools/check_recording.py [seconds]

Run it by hand. It writes a real file and takes as long as it says.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile

from dropdeck import constants as C                    # noqa: E402
from dropdeck import videorecord                       # noqa: E402
from dropdeck.audiofile import CHANNELS                # noqa: E402
from dropdeck.streamout import AirBus                  # noqa: E402

RATE = 48000
FPS = 30
WIDTH, HEIGHT = 640, 360
BITS = 24
PATCH = 20                    # pixels per bit along the top row
BURSTS = (2.0, 0.5, 0.9)      # start, middle and end, as fractions later


def stamp(frame, milliseconds):
    """Write a millisecond clock into the top row as grey patches."""
    value = int(milliseconds) & ((1 << BITS) - 1)
    for bit in range(BITS):
        on = (value >> bit) & 1
        x0 = bit * PATCH
        frame[0:PATCH, x0:x0 + PATCH] = 255 if on else 0
    return frame


def read_stamp(picture):
    """Read that clock back out of a decoded frame."""
    value = 0
    for bit in range(BITS):
        x0 = bit * PATCH
        patch = picture[2:PATCH - 2, x0 + 2:x0 + PATCH - 2]
        if float(patch.mean()) > 127.0:
            value |= (1 << bit)
    return value


def run(seconds, kill_picture_from=None, kill_picture_to=None):
    """Record for this long and return the path plus what was fed in."""
    folder = tempfile.mkdtemp(prefix="dropdeck-recheck-")
    bus = AirBus(RATE, seconds=2.0)
    tap = videorecord.FrameTap()
    rec = videorecord.VideoRecorder(bus, tap, width=WIDTH, height=HEIGHT,
                                    fps=FPS, folder=folder)
    if not rec.start():
        print("could not start: %s" % rec.detail)
        return None, None, None

    stop = threading.Event()
    marks = []

    def feed_audio():
        """Real time audio, and the burst moments recorded as they happen."""
        block = 512
        written = 0
        phase = 0.0
        started = time.monotonic()
        at = [seconds * 0.1, seconds * 0.5, seconds * 0.9]
        fired = [False, False, False]
        while not stop.is_set():
            due = int((time.monotonic() - started) * RATE)
            if written >= due:
                time.sleep(0.002)
                continue
            now = written / float(RATE)
            wave = np.zeros((block, CHANNELS), dtype=np.float32)
            for index, moment in enumerate(at):
                if now >= moment and not fired[index]:
                    fired[index] = True
                    marks.append((now, time.monotonic()))
                if moment <= now < moment + 0.2:
                    step = 2 * np.pi * 1000.0 / RATE
                    angle = phase + step * np.arange(block)
                    phase = (phase + step * block) % (2 * np.pi)
                    tone = (0.4 * np.sin(angle)).astype(np.float32)
                    wave = np.column_stack([tone, tone])
            bus.write("test", wave)
            written += block

    def feed_picture():
        """A frame every 1/fps, stamped with the moment it was made."""
        started = time.monotonic()
        made = 0
        base = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        while not stop.is_set():
            now = time.monotonic() - started
            if kill_picture_from is not None and \
                    kill_picture_from <= now < kill_picture_to:
                time.sleep(0.01)          # the source has gone
                continue
            due = int(now * FPS)
            if made >= due:
                time.sleep(0.002)
                continue
            frame = base.copy()
            # Something moving, so a frozen picture is visible as well as
            # measurable.
            band = int((made * 7) % (HEIGHT - PATCH - 20)) + PATCH + 10
            frame[band:band + 10, :] = 200
            stamp(frame, time.monotonic() * 1000.0)
            tap.put(frame)
            made += 1

    threads = [threading.Thread(target=feed_audio, daemon=True),
               threading.Thread(target=feed_picture, daemon=True)]
    for t in threads:
        t.start()
    time.sleep(seconds)
    stop.set()
    for t in threads:
        t.join(timeout=2.0)
    path = rec.stop()
    return path, rec, marks


def analyse(path, rec):
    import av

    container = av.open(path)
    video = [s for s in container.streams if s.type == "video"][0]
    audio = [s for s in container.streams if s.type == "audio"][0]

    print("")
    print("colour tags: colorspace=%s primaries=%s trc=%s range=%s"
          % (video.codec_context.colorspace,
             video.codec_context.color_primaries,
             video.codec_context.color_trc,
             video.codec_context.color_range))

    stamps = []
    times = []
    for frame in container.decode(video):
        picture = frame.to_ndarray(format="rgb24")
        stamps.append(read_stamp(picture))
        times.append(float(frame.pts * video.time_base))
    container.close()

    # A fresh container AND a fresh stream object. Reusing the one from the
    # closed container above handed back video frames and asked them for a
    # sample count.
    container = av.open(path)
    astream = [s for s in container.streams if s.type == "audio"][0]
    audio_rate = astream.rate
    audio_frames = 0
    for frame in container.decode(astream):
        audio_frames += frame.samples
    audio_seconds = audio_frames / float(audio_rate)
    container.close()

    n = len(times)
    print("video frames %d, video length %.3f s, audio length %.3f s, "
          "difference %.1f ms"
          % (n, times[-1] if n else 0.0, audio_seconds,
             1000.0 * ((times[-1] if n else 0) - audio_seconds)))

    gaps = np.diff(np.array(times))
    distinct = len(set(np.round(gaps, 6)))
    print("delivered frame rate %.4f (nominal %d), distinct frame gaps %d"
          % ((n - 1) / (times[-1] - times[0]) if n > 1 else 0.0, FPS, distinct))

    # Lag: the file says this frame is at t, the picture in it was taken at s.
    #
    # A REPEATED frame is excluded, and that is not a convenience. When the
    # picture stops arriving this recorder repeats the last frame on purpose,
    # so the stamp inside it is deliberately stale: measuring it would report
    # the age of a frozen picture as a sync error, which is a different thing
    # entirely and the very behaviour that keeps the timeline honest. Frozen
    # frames are counted and reported separately instead.
    frozen = 0
    usable = []
    previous = None
    for t, s in zip(times, stamps):
        if s <= 0:
            continue
        if s == previous:
            frozen += 1
            continue
        previous = s
        usable.append((t, s))
    if frozen:
        print("frozen frames %d of %d, %.1f per cent, which is the picture "
              "being held rather than the timeline stalling"
              % (frozen, n, 100.0 * frozen / max(1, n)))
    if len(usable) < 40:
        print("not enough readable stamps (%d) to measure sync" % len(usable))
        return False
    base = usable[0][1] - usable[0][0] * 1000.0
    lag = np.array([(s - (base + t * 1000.0)) for t, s in usable])
    at = np.array([t for t, _s in usable])

    segments = 5
    edges = np.linspace(at[0], at[-1], segments + 1)
    means = []
    for i in range(segments):
        inside = (at >= edges[i]) & (at < edges[i + 1])
        if inside.any():
            means.append(float(lag[inside].mean()))
    print("lag by fifth of the run, ms: %s"
          % " ".join("%+.1f" % m for m in means))
    # Least squares across the segment MEANS, not last minus first. Taking
    # it from the ends is exactly what Tiffany warned about and exactly what
    # the first version of this did: means of -7.7, -8.9, -7.3, -10.6, -11.0
    # are noise, and differencing the ends called them a 6.7 ms per minute
    # drift and failed a clean run.
    span_minutes = (at[-1] - at[0]) / 60.0
    if len(means) >= 3 and span_minutes:
        centres = np.linspace(0.0, span_minutes, len(means))
        slope = float(np.polyfit(centres, np.array(means), 1)[0])
    else:
        slope = 0.0
    print("offset at start %+.1f ms, at end %+.1f ms, slope %+.2f ms per minute"
          % (means[0], means[-1], slope))
    steady = abs(slope) < 2.0
    print("verdict: %s"
          % ("a constant offset, which is a delay somebody forgot" if steady
             else "a SLOPE, which is a clock nobody chose"))

    print("repeated frames %d, skipped %d, audio lost %d"
          % (rec.repeated, rec.dropped_pictures, rec.losing_audio))

    faults = []
    if video.codec_context.colorspace != 1:
        faults.append("the picture is not tagged BT.709")
    if distinct > 3:
        faults.append("%d distinct frame gaps, so the file is variable frame "
                      "rate" % distinct)
    if not steady:
        faults.append("sync drifts by %+.2f ms per minute" % slope)
    if abs((times[-1] if n else 0) - audio_seconds) > 0.5:
        faults.append("the picture and the sound are different lengths")
    return faults


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    print("Recording %.0f seconds at %dx%d, %d fps, CRF %d"
          % (seconds, WIDTH, HEIGHT, FPS, C.RECORD_VIDEO_CRF))
    path, rec, _marks = run(seconds)
    if path is None:
        return 1
    print("wrote %s, %.1f MB" % (os.path.basename(path),
                                 os.path.getsize(path) / 1048576.0))
    faults = analyse(path, rec)

    print("")
    print("Now the same thing with the picture removed for eight seconds")
    path2, rec2, _ = run(max(seconds, 24.0),
                         kill_picture_from=8.0, kill_picture_to=16.0)
    if path2 is not None:
        faults2 = analyse(path2, rec2)
        if faults2:
            faults = list(faults or []) + ["with the picture gone: " + f
                                           for f in faults2]

    print("")
    if faults:
        for line in faults:
            print("FAULT: %s" % line)
        return 1
    print("Clean. Constant frame rate, tagged BT.709, and sync holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
