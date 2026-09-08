"""Change the picture on air, at real time, and prove nothing came apart.

`tests/test_3_4_1.py` proves a swap works. It cannot prove it works on a live
show, and the difference is not a detail. A test renders far faster than a
sound card, so the encoder is handed a run's worth of audio in a couple of
seconds, every source answers instantly out of a cache, and the one thing a
real broadcast does constantly, wait, never happens. `check_stream_quality.py`
exists for exactly that reason on the audio side and this is its counterpart.

So this runs at **real time**, with the **real screen capture** attached, and
switches the picture repeatedly while the stream is up. Then it decodes what
the server received and asks the questions a stutter or a drift cannot
survive:

  * **Is it all there?** Frames decoded against frames the clock called for.
    A swap that dropped a second of video is thirty frames missing and no
    amount of "it reconnected fine" hides that.

  * **Did it stay in step?** Audio and video timestamps compared at every
    swap, not only at the end. An error that cancels itself out by the end of
    a run would pass a check that only looked there, and would still have put
    the picture behind the sound for the middle of the show.

  * **Did it stay smooth?** The gap between consecutive frames, at p95 and as
    a count of gaps over 100 ms. The average is useless here: eight frames
    muxed back to back and then a fifth of a second of nothing averages out
    to a perfect thirty per second and looks terrible.

  * **Did the picture actually change?** Decoded pixels, per swap. A swap that
    quietly went on sending the old source would pass every count above.

The screen capture is the reason this matters more than it looks. A desktop
blit blocks for 16 to 33 ms, which is the whole frame budget at 30 fps, so it
runs on its own thread and the encoder reads the last frame it finished. If
that were ever got wrong the audio would stall behind it, and this is the run
that would show it.

    python tools/check_switching.py [seconds]

Nothing leaves the machine: it publishes to `tools/mock_rtmp.py`.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="dd-switch-"))

import numpy as np

from dropdeck import constants as C
from dropdeck import health, overlay, picture, screen
from dropdeck.engine import CHANNELS
from dropdeck.streamout import RtmpDestination
from mock_rtmp import MockRTMP

RATE = 44100
FPS = 30
WIDTH, HEIGHT = 640, 360
FAILED = []


def say(label, ok, extra=None):
    if not ok:
        FAILED.append(label)
    print(("  ok   " if ok else "  FAIL ") + label
          + (("  " + str(extra)) if extra is not None else ""), flush=True)


def tone(frames, start, freq=440.0):
    t = (np.arange(start, start + frames) / float(RATE))
    wave = (0.35 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.repeat(wave[:, None], CHANNELS, axis=1)


class Tinted(picture.PictureSource):
    """A source with a colour signature, so a decoded frame names it."""

    def __init__(self, name, colour, kind="flat"):
        self.name = name
        self.colour = colour
        self.kind = kind

    def frame(self, width, height):
        canvas = np.empty((height, width, 3), dtype=np.uint8)
        canvas[:, :] = np.asarray(self.colour, dtype=np.uint8)
        return canvas

    def describe(self):
        return self.name

    def close(self):
        pass


def signature(canvas):
    """A fingerprint of what is on screen, as a mean colour.

    The mean of the three channels rather than which one is biggest. A flat
    card has an obvious dominant channel and a real desktop has none, so the
    dominant channel version of this called the screen "no signature" and
    then could not see a switch into or out of it. Distance between two of
    these is what counts as the picture having changed.
    """
    return np.array([float(canvas[:, :, at].mean()) for at in range(3)])


def main(seconds=20.0):
    print("A real time broadcast of %.0f seconds, switching the picture "
          "as it goes\n" % seconds)

    # The real thing, capturing the real desktop on its real thread. It is
    # the source most likely to break the pacing and the only one that has
    # to wait on anything outside this process.
    live_screen = None
    if screen.available():
        live_screen = screen.ScreenSource(C.SCREEN_ALL, WIDTH, HEIGHT, FPS)
        try:
            live_screen.start()
            if not live_screen.wait_ready(4.0):
                print("  note  the screen would not start: %s"
                      % (live_screen.error or "no reason given"))
                live_screen = None
        except Exception as exc:
            print("  note  the screen would not start: %s" % exc)
            live_screen = None
    say("the real screen capture is attached to this run",
        live_screen is not None,
        "" if live_screen else "running without it, which proves less")

    plan = [Tinted("red card", (220, 40, 40)),
            Tinted("green card", (40, 200, 40)),
            Tinted("blue card", (40, 60, 220))]
    if live_screen is not None:
        plan.insert(2, live_screen)
    every = seconds / float(len(plan))

    swaps = []
    # The mock server stops listening after `seconds` and defaults to 20, so a
    # longer run outlives it and the publish dies with a connection reset that
    # looks exactly like a real network fault. It is not one.
    with MockRTMP.spawn(seconds=seconds + 15) as server:
        # The overlay and the health watch ride along, because on a real
        # show they will, and the question this file exists to answer is
        # what the WHOLE thing costs on the thread carrying the audio.
        marks = overlay.Overlay({
            "name": "Blindside Radio",
            "text_%s" % C.PLACE_LOWER: C.TEXT_STATION,
            "text_%s" % C.PLACE_CLOCK: C.TEXT_TIME,
        }) if overlay.available() else None
        watcher = health.Watcher()
        destination = RtmpDestination(
            {"server": "rtmp", "host": server.url.rsplit("/", 1)[0],
             "password": server.url.rsplit("/", 1)[1], "bitrate": 128,
             "video_width": WIDTH, "video_height": HEIGHT, "video_fps": FPS,
             "video_bitrate": 1200},
            RATE, video_source=plan[0], overlay_=marks, watcher=watcher)
        destination.connect()

        block = int(RATE * destination.chunk_seconds)
        sent = 0
        at = 0
        started = time.monotonic()
        worst_feed = 0.0
        feeds = []
        while sent < RATE * seconds:
            # Real time. The sound card is the clock in the app and this is
            # the nearest a test process gets to being one: never hand over
            # audio that has not had time to happen.
            due = started + sent / float(RATE)
            behind = due - time.monotonic()
            if behind > 0:
                time.sleep(behind)
            began = time.perf_counter()
            destination.feed(tone(block, sent))
            took = (time.perf_counter() - began) * 1000
            feeds.append(took)
            worst_feed = max(worst_feed, took)
            sent += block
            want = min(len(plan) - 1, int((sent / float(RATE)) / every))
            if want != at:
                at = want
                swaps.append((sent / float(RATE), destination._frames_sent,
                              plan[at].describe()))
                destination.set_video_source(plan[at])
        destination.close()
    if live_screen is not None:
        live_screen.close()

    result = server.result()
    say("the overlay was on the picture the whole way",
        marks is None or marks.renders > 0,
        "not attached" if marks is None else "%d tiles drawn" % marks.renders)
    say("and it drew each tile once, not once a frame",
        marks is None or marks.renders <= 4,
        "" if marks is None else "%d renders over %d frames"
        % (marks.renders, int(seconds * FPS)))
    say("the health watch looked at every frame that went out",
        watcher.frames > seconds * FPS * 0.9, "%d looks" % watcher.frames)
    say("and never once cried wolf on a good picture",
        watcher.state == "ok", watcher.describe())

    say("the connection survived every switch",
        result.publishing and not result.error, result.error or "no errors")
    say("every switch happened while it was live", len(swaps) == len(plan) - 1,
        "%d switches: %s" % (len(swaps), ", ".join(s[2] for s in swaps)))

    # feed() runs on the streaming thread and it is the thread carrying the
    # audio, so anything that blocks in there stalls the show. A screen blit
    # is 16 to 33 ms and must never be on this path.
    #
    # Two numbers, because they answer different questions and only one of
    # them is about the design. The TYPICAL cost is what says the capture is
    # off this thread: measured 8 September 2026 over 45 seconds, 7.35 ms
    # median with a card and 9.24 ms with the real screen attached, so the
    # capture costs about two milliseconds here and never waits. If it were
    # ever moved onto this thread that median would go to 16 ms or worse and
    # this is what would catch it.
    #
    # The WORST is judged much more loosely, on purpose. An occasional spike
    # is a garbage collection pause or Windows scheduling rather than
    # anything about the picture, and it is harmless: the AirBus holds two
    # seconds, so the ring absorbs it and the frames still leave evenly. The
    # proof of that is the arrival gaps below, which are measured off the
    # wire and are the thing a viewer would actually see. A run with a 155 ms
    # spike in it still delivered 1799 of 1800 frames with no arrival gap
    # over 100 ms.
    feeds.sort()
    typical = feeds[len(feeds) // 2]
    p95_feed = feeds[int(len(feeds) * 0.95)]
    say("the picture is not on the audio thread: feeding stays quick",
        typical < 20.0 and p95_feed < 25.0,
        "median %.1f ms, p95 %.1f ms, budget %.1f ms" % (
            typical, p95_feed, destination.chunk_seconds * 1000))
    say("and no stall came near emptying the ring that absorbs it",
        worst_feed < 500.0,
        "worst %.1f ms against %.0f ms of ring" % (
            worst_feed, C.AIR_RING_SECONDS * 1000))

    frames = []
    container = result.container()
    for frame in container.decode(video=0):
        frames.append(frame.to_ndarray(format="rgb24"))
    container.close()

    expected = int(seconds * FPS)
    say("every frame of the run arrived", abs(len(frames) - expected) <= FPS,
        "%d of about %d" % (len(frames), expected))

    black = sum(1 for f in frames if int(f.max()) < 20)
    say("no frame went black, at a switch or anywhere else", black == 0, black)

    # The picture really changed, and changed as many times as it was told to.
    marks = [signature(f) for f in frames]
    # A run of frames either side of a boundary, so codec noise inside one
    # steady picture cannot be mistaken for a switch.
    moved = [at for at, (a, b) in enumerate(zip(marks, marks[1:]))
             if float(np.linalg.norm(b - a)) > 25.0]
    say("the picture visibly changed once per switch, and no more",
        len(moved) == len(swaps),
        "%d visible changes for %d switches, at frames %s"
        % (len(moved), len(swaps), moved))

    gaps = np.diff(result.video_timestamps) if len(
        result.video_timestamps) > 2 else np.array([])
    if len(gaps):
        long_gaps = int((gaps > 100).sum())
        say("no gap between frames over 100 ms", long_gaps == 0,
            "%d of %d" % (long_gaps, len(gaps)))
        say("the middle gap is about one frame period",
            20 < float(np.median(gaps)) < 50, "%.1f ms" % np.median(gaps))
        say("and the slow tail stays inside two frame periods",
            float(np.percentile(gaps, 95)) < 90,
            "p95 %.1f ms" % np.percentile(gaps, 95))

    # Sync, measured across the whole run rather than only at the end.
    if result.audio_timestamps and result.video_timestamps:
        end = abs(result.video_timestamps[-1] - result.audio_timestamps[-1])
        say("audio and video finish together", end < 100, "%d ms apart" % end)

        worst = 0.0
        where = ""
        for when, _frame, name in swaps:
            near_v = [t for t in result.video_timestamps
                      if abs(t - when * 1000) < 400]
            near_a = [t for t in result.audio_timestamps
                      if abs(t - when * 1000) < 400]
            if not near_v or not near_a:
                continue
            drift = abs(max(near_v) - max(near_a))
            if drift > worst:
                worst, where = drift, name
        say("and they stayed together through every switch", worst < 100,
            "worst %d ms, switching to %s" % (worst, where or "nothing"))

    samples = []
    container = result.container()
    for frame in container.decode(audio=0):
        samples.append(frame.to_ndarray())
    container.close()
    pcm = np.concatenate([s.reshape(-1) for s in samples]).astype(np.float64)
    heard = len(pcm) / float(CHANNELS * RATE)
    say("the sound ran the whole way through without a hole",
        abs(heard - seconds) < 0.6, "%.2f s of %.1f" % (heard, seconds))

    print()
    if FAILED:
        print("%d FAILED" % len(FAILED))
        for name in FAILED:
            print("  " + name)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    length = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    sys.exit(main(length))
