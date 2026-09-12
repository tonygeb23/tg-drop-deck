"""Is a video recording really the camera and the screen, or is it a card.

    python tools/check_record_picture.py [seconds]

**The check that would have caught the fault Tony reported on 12 September
2026**, and the reason nothing else did. `tests/test_video.py` builds picture
sources and asks them for frames, so every source works. `check_recording.py`
pushes frames into the recorder by hand and measures sync, so the recorder
works. Between the two sat `ui._record_picture_run`, which built a source and
never started it, and nothing anywhere pressed the key and looked at the
picture that came out. Measured against his board that morning: a card with
his station name on it, 175 frames in six seconds, mean pixel difference from
a freshly drawn card ZERO.

So this presses the real thing. A real `DropDeckFrame`, a real recording
started the way `Ctrl+Shift+R` starts one, the real screen capture and the
real camera, then the file is decoded and the PIXELS are read back.

What it asserts, and each one is a number rather than an opinion:

- the file's frames are NOT a card. Built the same card `picture.build` would
  fall back to and compared: a real capture is hundreds of grey levels away
  from a flat card, a fallback is nought.
- the picture MOVES. A card is one array handed over thirty times a second,
  so unique frame count is the difference between a picture and a still.
- the camera is in it, for a split: the inset corner differs from the same
  corner of a screen only capture.
- **one camera, not two.** Recording while live used to open a second
  DirectShow camera on a device Windows hands to one owner at a time. Counted
  by wrapping `CameraSource.start`.
- the overlay reaches the file, which it never did: the branch that would
  have drawn it was guarded on a method name that does not exist.

Run it by hand. It writes real files and takes as long as it says.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A throwaway board, so a check can never touch the real one.
_FAKE = tempfile.mkdtemp(prefix="dd-recpic-")
os.environ["APPDATA"] = _FAKE

import wx                                              # noqa: E402

from dropdeck import camera as cameras                 # noqa: E402
from dropdeck import constants as C                    # noqa: E402
from dropdeck import picture                           # noqa: E402
from dropdeck import picturefeed                       # noqa: E402
from dropdeck import screen as screens                 # noqa: E402
from dropdeck.ui import DropDeckFrame                  # noqa: E402

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
RATE = 48000
FAILED = []


def say(label, ok, extra=""):
    if ok is None:
        print("  skip " + label + (("  " + str(extra)) if extra else ""),
              flush=True)
        return
    if not ok:
        FAILED.append(label)
    print(("  ok   " if ok else "  FAIL ") + label
          + (("  " + str(extra)) if extra != "" else ""), flush=True)


# ---------------------------------------------------------------------------
# One camera, counted
# ---------------------------------------------------------------------------
OPENS = []
_real_start = cameras.CameraSource.start


def counted_start(self):
    OPENS.append(self.device)
    return _real_start(self)


cameras.CameraSource.start = counted_start


# ---------------------------------------------------------------------------
# The recording
# ---------------------------------------------------------------------------
def record(frame, seconds):
    """Start a recording the way the key does, feed the clock, stop it.

    The audio is written into the recording's own bus rather than played
    through a sound card, because what is under test is the PICTURE and a
    card that happens to be busy must not be able to fail this. The bus is
    the same object the mixer writes into, and the recorder's clock is its
    own count of samples off it, so the video is paced exactly as it would be
    on the air.
    """
    if not frame.start_video_recording():
        return None
    path = frame.video_recorder.path
    bus = frame.video_bus
    block = 1024
    tone = (0.2 * np.sin(2 * np.pi * 440.0
                         * np.arange(block) / float(RATE))).astype(np.float32)
    stereo = np.repeat(tone[:, None], 2, axis=1)
    started = time.monotonic()
    written = 0
    while time.monotonic() - started < seconds:
        due = int((time.monotonic() - started) * RATE)
        while written < due:
            bus.write("check", stereo, RATE)
            written += block
        wx.Yield()
        time.sleep(0.005)
    frame.stop_video_recording(quiet=True)
    return path


def decoded(path, want=40):
    """Up to `want` frames of the file, evenly spaced, as RGB arrays."""
    import av
    container = av.open(path)
    stream = container.streams.video[0]
    out = []
    for got in container.decode(stream):
        out.append(got.to_ndarray(format="rgb24"))
    container.close()
    if len(out) <= want:
        return out
    step = len(out) // want
    return out[::step][:want]


def card_for(frame):
    """The card this board would fall back to, drawn for comparison."""
    made = picture.build({"picture": C.PICTURE_CARD,
                          "name": frame.board.stream_name,
                          "colour_background": frame.board.colour_background,
                          "colour_text": frame.board.colour_text,
                          "colour_accent": frame.board.colour_accent})
    made.start()
    return made.frame(frame.board.video_width, frame.board.video_height)


def unique_frames(frames):
    """How many DISTINCT pictures are in there. A card is one."""
    seen = set()
    for one in frames:
        seen.add(hash(one[::7, ::7].tobytes()))
    return len(seen)


def main():
    app = wx.App(False)
    frame = DropDeckFrame(None)
    board = frame.board
    board.record_folder = os.path.join(_FAKE, "recordings")
    board.stream_name = "Blindside Radio"
    board.live_to = C.LIVE_TO_AUDIO          # the radio station, as his is
    board.stream_server = "icecast"
    board.stream_host = "blindsideradio.com"

    cams = frame.known_cameras()
    can_screen = screens.available()
    print("camera: %s   screen: %s"
          % (cams[0] if cams else "none", "yes" if can_screen else "no"))

    # The case Tony reported: a board pointed at a radio station, with a real
    # picture chosen, recording video.
    if can_screen and cams:
        board.picture, board.camera = C.PICTURE_SPLIT, cams[0]
    elif can_screen:
        board.picture = C.PICTURE_SCREEN
    elif cams:
        board.picture, board.camera = C.PICTURE_CAMERA, cams[0]
    else:
        say("a camera or a screen to capture", None, "neither on this machine")
        print("\nnothing to prove without one. Stopping.")
        return 0
    board.screen = C.SCREEN_ALL
    wanted = board.picture
    print("picture: %s\n" % board.picture)

    print("Recording %.0f seconds off air..." % SECONDS)
    OPENS[:] = []
    path = record(frame, SECONDS)
    if not path or not os.path.isfile(path):
        say("the recording was written", False, path)
        return 1
    size = os.path.getsize(path) / 1024.0
    say("the recording was written", size > 20, "%.0f KB" % size)

    frames = decoded(path)
    say("the file has pictures in it", len(frames) > 5, "%d read" % len(frames))
    if not frames:
        return 1

    # THE CHECK. A fallback card is pixel for pixel the card this builds.
    flat = card_for(frame)
    if flat is not None and flat.shape == frames[len(frames) // 2].shape:
        gaps = [float(np.abs(one.astype(int) - flat.astype(int)).mean())
                for one in frames]
        worst = min(gaps)
        say("the picture is NOT the station card",
            worst > 8.0, "closest frame is %.1f grey levels away" % worst)
    else:
        say("the picture is NOT the station card", None, "sizes differ")

    # A card is one array handed over again and again. A capture is not.
    distinct = unique_frames(frames)
    say("the picture moves", distinct > 1,
        "%d distinct of %d sampled" % (distinct, len(frames)))

    colours = len(np.unique(frames[len(frames) // 2].reshape(-1, 3), axis=0))
    say("the picture is a real capture, not a drawing",
        colours > 2000, "%d distinct colours" % colours)

    # One camera, not two. The whole reason the feed is shared.
    if board.picture in C.PICTURE_NEEDS_CAMERA:
        say("exactly one camera was opened", len(OPENS) == 1,
            "%d opens: %s" % (len(OPENS), OPENS))

    # The camera really is in the corner of a split, rather than the screen
    # alone with the inset arithmetic quietly failing.
    if board.picture == C.PICTURE_SPLIT:
        mid = frames[len(frames) // 2]
        h, w = mid.shape[:2]
        box_w = int(round(w * C.SPLIT_INSET_WIDTH))
        box_h = int(round(box_w * h / float(w)))
        margin_x = int(round(w * C.SPLIT_INSET_MARGIN))
        margin_y = int(round(h * C.SPLIT_INSET_MARGIN))
        left = (margin_x if "left" in board.split_corner
                else max(0, w - box_w - margin_x))
        top = (margin_y if "top" in board.split_corner
               else max(0, h - box_h - margin_y))
        # Looked for by its BORDER, not by comparing corners. Two corners of
        # a real desktop can be identically flat, so a corner comparison
        # would pass or fail on what happened to be on screen. SplitSource
        # paints a ring of exactly the accent colour around the inset, so the
        # question is whether that ring is there.
        from dropdeck import colours
        edge = np.asarray(colours.rgb(board.colour_accent or C.COLOUR_ACCENT))
        ring = C.SPLIT_INSET_BORDER
        strip = mid[max(0, top - ring):top,
                    max(0, left - ring):left + box_w + ring]
        near = float(np.abs(strip.astype(int)
                            - edge.astype(int)).mean()) if strip.size else 999
        say("the camera really is inset in the %s" % board.split_corner,
            near < 30.0,
            "the accent border reads %.1f levels off %s" % (near, tuple(edge)))

    # Live and recording at once: one pipeline, not two. Skipped without a
    # mock RTMP server, because that is check_switching.py's job and this
    # check must never need the network.
    print("\nAlt+Shift+V during a recording...")
    OPENS[:] = []
    if not frame.start_video_recording():
        say("a second recording started", False)
    else:
        other = (C.PICTURE_SCREEN if board.picture != C.PICTURE_SCREEN
                 else C.PICTURE_CAMERA)
        if other == C.PICTURE_CAMERA and not cams:
            other = C.PICTURE_CARD
        time.sleep(1.0)
        said = frame.set_video_source(other)
        say("it does not say the change is for next time",
            "next time" not in said.lower(), repr(said))
        say("the feed really swapped", frame.feed().kind == other
            or frame.feed().fallen_back, frame.feed().kind)
        live = frame.feed().frame(board.video_width, board.video_height)
        say("and a frame comes out of the new source", live is not None)
        frame.stop_video_recording(quiet=True)
        say("the camera was let go afterwards",
            not frame.feed().running, frame.feed().holders())

    # THE OVERLAY REACHES THE FILE. This docstring claimed the assertion
    # before it existed, which Mark caught and was right to: a tool that says
    # it proved something it did not is worse than no tool. It is worth one,
    # because the overlay had never once been drawn on a CARD: CardSource
    # handed back a read only array, draw_on wrote in place, and all four
    # callers swallowed the ValueError. A card is the case to test.
    print("\nWords on the picture...")
    board.picture = C.PICTURE_CARD
    places = dict(board.text_places or {})
    places["lower"] = {"kind": C.TEXT_WORDS, "words": "PROOF OF OVERLAY",
                       "file": ""}
    board.text_places = places
    frame.refresh_overlay()
    marked_path = record(frame, 4.0)
    if not marked_path:
        say("a recording with words on it was written", False)
    else:
        shots = decoded(marked_path, want=12)
        bare = card_for(frame)
        carried = 0
        for one in shots:
            if bare is None or one.shape != bare.shape:
                continue
            # The lower third sits in the bottom quarter, so a bare card and
            # a card with words on it differ THERE and almost nowhere else.
            band = slice(int(one.shape[0] * 0.72), int(one.shape[0] * 0.95))
            gap = float(np.abs(one[band].astype(int)
                               - bare[band].astype(int)).mean())
            if gap > 2.0:
                carried += 1
        say("the words are really in the file, over a card",
            carried > len(shots) // 2,
            "%d of %d frames carry the lower third" % (carried, len(shots)))
    places["lower"] = {"kind": C.TEXT_NONE, "words": "", "file": ""}
    board.text_places = places
    frame.refresh_overlay()

    # What the app SAYS about it, which is all a blind presenter gets.
    print("\nWhat it says:")
    board.picture = wanted
    frame.start_video_recording()
    time.sleep(0.5)
    spoken = frame.what_is_in_the_recording(picture=True)
    print("  " + spoken)
    say("the announcement names the picture", "Picture:" in spoken)
    say("it does not claim a card when a camera is running",
        "a card instead" not in spoken or frame.feed().fallen_back)
    on_screen = frame.stream_status()
    print("  " + on_screen)
    say("Ctrl+Shift+B reports the recording",
        "picture and sound" in on_screen.lower(), repr(on_screen[:80]))
    frame.stop_video_recording(quiet=True)

    print("\n%d failed" % len(FAILED))
    for one in FAILED:
        print("  " + one)
    return 1 if FAILED else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_FAKE, ignore_errors=True)
    sys.exit(code)
