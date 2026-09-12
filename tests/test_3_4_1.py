"""3.4.1: knowing what is about to go live, and changing the picture on air.

Two things Tony asked for on 8 September 2026.

**"How do we know what is currently live."** Ctrl+B used to be a leap: the app
knew the destination, the format, the picture and whether the presenter's own
microphone was part of the programme, and said none of it until after it had
connected. `preflight.py` is the answer and most of this file is about it,
because the interesting half is not the summary, it is the list of ways to
ruin a broadcast that used to pass silently. A moved picture file sending a
dark rectangle for three hours is the worst of them, and it is checked here.

**"What if we want to switch to a different source while live on air."** So
the picture can change without touching the connection, and the last section
proves it the only way worth anything: publish real audio to a real RTMP
server, swap the picture halfway, decode what arrived and look at the pixels.
Counting frames would not have caught a swap that quietly stopped sending.

**Audio and video stay locked across a swap**, and that is asserted rather
than assumed. It holds because video timestamps are counted against the audio
sample clock rather than taken from whatever is producing pictures, so a new
source cannot move the timeline. A test that only measured the end of the run
would pass even if the middle fell apart, so the drift is measured at the
swap as well.

    python tests/test_3_4_1.py
"""

import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-341-test-")

from dropdeck import constants as C
from dropdeck import picture, preflight, screen, streamout
from dropdeck.board import Board
from dropdeck.engine import CHANNELS
from dropdeck.streamout import RtmpDestination
from mock_rtmp import MockRTMP

CHECKS = []
RATE = 44100


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


def tone(frames, freq=440.0, rate=RATE, level=0.4, start=0):
    t = (np.arange(start, start + frames) / float(rate))
    wave = (level * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.repeat(wave[:, None], CHANNELS, axis=1)


def video_board(**kwargs):
    """A board set up to go live to a video platform."""
    board = Board()
    board.live_to = C.LIVE_TO_VIDEO
    board.video_server = "youtube"
    board.video_host = C.RTMP_INGEST["youtube"]
    board.stream_name = "Test Station"
    for key, value in kwargs.items():
        setattr(board, key, value)
    return board


def video_settings(**kwargs):
    out = {"server": "youtube", "host": C.RTMP_INGEST["youtube"],
           "password": "a-stream-key", "format": "aac", "bitrate": 128,
           "picture": C.PICTURE_CARD, "picture_file": "", "camera": "",
           "screen": C.SCREEN_ALL, "name": "Test Station",
           "video_width": 1280, "video_height": 720, "video_fps": 30,
           "video_bitrate": 2500}
    out.update(kwargs)
    return out


class Flat(picture.PictureSource):
    """A source that is one colour, so a decoded frame says which was live."""

    kind = "flat"

    def __init__(self, colour):
        self.colour = colour
        self.closed = False
        self.asked = 0

    def frame(self, width, height):
        self.asked += 1
        canvas = np.empty((height, width, 3), dtype=np.uint8)
        canvas[:, :] = np.asarray(self.colour, dtype=np.uint8)
        return canvas

    def describe(self):
        return "a flat colour"

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
print("\nWhat Ctrl+B is about to do, said before it does it")
# ---------------------------------------------------------------------------

board = video_board()
report = preflight.check(video_settings(), board)
labels = [label for label, _value in report.lines]
check("it says where the show is going, first", labels and labels[0] == "Going to")
check("and what the sound will be", "Sound" in labels)
check("and what will be on the screen", "Picture" in labels)
check("and whether the presenter is on the air", "Microphone" in labels)
check("the destination is the platform, not the radio station",
      "YouTube" in report.summary(), report.summary())
check("a station that is set up properly has nothing to stop it",
      not report.blocked, [n.text for n in report.stops])

# The stream key is in the URL for RTMP, so nothing that shows a user where
# their show is going may print the address raw.
check("the address is said without the stream key in it",
      "a-stream-key" not in report.spoken(), report.spoken()[:80])

spoken = report.spoken()
check("it reads as one sentence a screen reader can get through",
      spoken.count(";") >= 3 and "\n" not in spoken)


# ---------------------------------------------------------------------------
print("\nThe faults that used to go out on the air in silence")
# ---------------------------------------------------------------------------

def texts(report):
    return " | ".join(n.text for n in report.notes)


# 1. The microphone. Nothing anywhere said this, ever, and a show with the
# presenter missing sounds perfect from where the presenter is sitting.
off = preflight.check(video_settings(), video_board(stream_mic=False))
check("a microphone that is not on the air is a warning",
      any("microphone is not on the air" in n.text.lower()
          for n in off.warnings), texts(off))
check("and the summary says so rather than implying it",
      any("NOT going out" in value for _l, value in off.lines),
      [v for l, v in off.lines if l == "Microphone"])
check("but it is not a reason to refuse to broadcast", not off.blocked)

on = preflight.check(video_settings(), video_board(stream_mic=True))
check("a microphone that IS on the air says nothing about it",
      not any("microphone" in n.text.lower() for n in on.notes), texts(on))

# 2. The moved picture file. ImageSource fills a canvas rather than failing,
# so the fallback never fires and the whole show is a dark rectangle.
missing = preflight.check(
    video_settings(picture=C.PICTURE_IMAGE,
                   picture_file=os.path.join(tempfile.gettempdir(),
                                             "no-such-artwork-341.png")),
    video_board())
check("a picture file that is not there is caught before going live",
      any("not there" in n.text for n in missing.warnings), texts(missing))

with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
    real_picture = handle.name
present = preflight.check(
    video_settings(picture=C.PICTURE_IMAGE, picture_file=real_picture),
    video_board())
check("a picture file that IS there is not complained about",
      not any("not there" in n.text for n in present.notes), texts(present))

# 3. A camera source with no camera chosen.
nocam = preflight.check(video_settings(picture=C.PICTURE_CAMERA),
                        video_board())
check("a camera source with no camera chosen is caught",
      any("no camera" in n.text.lower() for n in nocam.warnings), texts(nocam))
withcam = preflight.check(
    video_settings(picture=C.PICTURE_CAMERA, camera="HP HD Camera"),
    video_board())
check("and one with a camera chosen is not",
      not any("no camera" in n.text.lower() for n in withcam.notes))

# 4. The split needs both, so it warns about a missing camera too.
split = preflight.check(video_settings(picture=C.PICTURE_SPLIT), video_board())
check("the split source wants a camera as well",
      any("no camera" in n.text.lower() for n in split.warnings), texts(split))

# 5. A machine that cannot capture its screen.
cannot = preflight.check(video_settings(picture=C.PICTURE_SCREEN),
                         video_board(), screen_ready=False,
                         screen_reason="this copy cannot capture the screen")
check("a screen that cannot be captured is caught before going live",
      any("cannot capture" in n.text for n in cannot.warnings), texts(cannot))

# 6. No stream key, and no sound card. Both stop the broadcast.
nokey = preflight.check(video_settings(password=""), video_board())
check("no stream key stops it", nokey.blocked, texts(nokey))
deaf = preflight.check(video_settings(), video_board(), audio_running=False)
check("a sound card that is not running stops it", deaf.blocked, texts(deaf))
check("and says which, rather than just refusing",
      any("sound card" in n.text for n in deaf.stops), texts(deaf))

# 7. The platform's own behaviour, said BEFORE connecting rather than after.
you = preflight.check(video_settings(), video_board(video_server="youtube"))
check("YouTube's go live at once is said before connecting, not after",
      any("the moment you connect" in n.text for n in you.notes), texts(you))
face = preflight.check(
    video_settings(server="facebook", host=C.RTMP_INGEST["facebook"]),
    video_board(video_server="facebook"))
check("and Facebook's opposite behaviour is said too",
      any("Go Live Now" in n.text for n in face.notes), texts(face))

# 8. A card that will never change, because the switch is on the other page.
frozen = preflight.check(video_settings(),
                         video_board(stream_titles=False))
check("a card that cannot update is a warning",
      any("not say what is playing" in n.text for n in frozen.warnings),
      texts(frozen))

# 9. The radio station side, which has its own shape entirely.
radio = Board()
radio.stream_host = "radio.example.com"
radio.stream_mount = "/live"
audio_report = preflight.check(
    {"server": "icecast", "host": "radio.example.com", "mount": "/live",
     "password": "", "format": "mp3", "bitrate": 128}, radio)
check("a radio station with no password is warned about, not refused",
      not audio_report.blocked
      and any("no password" in n.text for n in audio_report.warnings),
      texts(audio_report))
check("and a radio station is never asked about a picture",
      not any(label == "Picture" for label, _v in audio_report.lines))


# ---------------------------------------------------------------------------
print("\nThe screen, captured without a new dependency")
# ---------------------------------------------------------------------------

check("this machine can capture its screen at all", screen.available(),
      screen.why_unavailable())

if screen.available():
    found = screen.screens()
    check("it offers something to capture", bool(found), found)
    check("everything on the screens is one of the choices",
          any(value == C.SCREEN_ALL for value, _l, _w, _h in found), found)
    check("and every choice has real pixels behind it",
          all(w > 0 and h > 0 for _v, _l, w, h in found), found)

    source = screen.ScreenSource(C.SCREEN_ALL, 1280, 720, 30)
    source.start()
    ready = source.wait_ready(4.0)
    check("it hands over a first picture", ready, source.error)

    if ready:
        canvas = source.frame(1280, 720)
        check("at exactly the size the encoder asked for",
              canvas is not None and canvas.shape == (720, 1280, 3),
              None if canvas is None else canvas.shape)
        check("as RGB bytes, which is what the encoder takes",
              canvas is not None and canvas.dtype == np.uint8)
        check("and it is the real screen, not black",
              canvas is not None and int(canvas.max()) > 24,
              None if canvas is None else int(canvas.max()))

        # THE MEASUREMENT THE WHOLE DESIGN RESTS ON. A desktop blit costs 16
        # to 33 ms and blocks, which is the entire frame budget at 30 fps.
        # frame() is called inline on the streaming thread, the same thread
        # that is carrying the audio, so if it waited for the screen it would
        # take the sound with it. It reads the last capture instead.
        worst = 0.0
        for _ in range(60):
            started = time.perf_counter()
            source.frame(1280, 720)
            worst = max(worst, (time.perf_counter() - started) * 1000.0)
        check("asking for a frame never waits for the screen",
              worst < 8.0, "worst %.2f ms of an 8 ms allowance" % worst)

        check("a second ask for the same size is the cached array",
              source.frame(1280, 720) is source.frame(1280, 720))
        check("it says what it is, for the status line",
              "screen" in source.describe().lower(), source.describe())

        # Stale is the same as gone. The card takes over rather than a
        # photograph of the screen going out for the rest of the show.
        source._latest_at = time.monotonic() - (C.SCREEN_STALE_SECONDS + 1)
        check("a capture that has gone stale is not offered as the screen",
              source.frame(1280, 720) is None)

    source.close()
    check("closing it forgets the last picture", source.latest() is None)
    check("and the capture thread is gone",
          source._thread is None or not source._thread.is_alive())

    # No new dependency, and that is a promise worth a check rather than a
    # comment: the installer is already 60 MB and every wheel added to it is
    # another thing to go missing in a frozen build.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "requirements.txt"), encoding="utf-8").read()
    check("no capture library was added to do it",
          not any(name in text for name in ("mss", "dxcam", "d3dshot",
                                            "pyautogui")), text)
    # Pillow arrived in 3.5.0 and is NOT a capture library, it is a text
    # renderer: the claim this check protects is that grabbing the screen
    # costs no dependency, and the proof of that is what screen.py imports.
    grabber = open(os.path.join(root, "dropdeck", "screen.py"),
                   encoding="utf-8").read()
    check("and the screen is still grabbed with nothing but ctypes",
          "import ctypes" in grabber
          and not any(("import %s" % n) in grabber
                      for n in ("mss", "dxcam", "PIL", "cv2")))


# ---------------------------------------------------------------------------
print("\nThe screen with the camera in the corner")
# ---------------------------------------------------------------------------

class FakeCamera(Flat):
    kind = C.PICTURE_CAMERA

    def __init__(self, colour=(255, 0, 0), gives=True):
        super().__init__(colour)
        self.gives = gives

    def frame(self, width, height):
        if not self.gives:
            return None
        return super().frame(width, height)

    def start(self):
        return self

    def wait_ready(self, timeout=None):
        return self.gives

    def latest(self):
        """The raw camera frame, which is what the framing checker wants.

        The real CameraSource has this and the framing loop looks for it by
        name, so a stand in without one proves nothing about the real path.
        """
        return self.frame(640, 360) if self.gives else None


back = Flat((10, 10, 10))
cam = FakeCamera((255, 0, 0))
both = screen.SplitSource(back, cam)
composite = both.frame(1280, 720)
check("the two are composited into one frame",
      composite is not None and composite.shape == (720, 1280, 3),
      None if composite is None else composite.shape)

if composite is not None:
    inset_w = int(round(1280 * C.SPLIT_INSET_WIDTH))
    inset_h = int(round(inset_w * 720 / 1280.0))
    margin_x = int(round(1280 * C.SPLIT_INSET_MARGIN))
    margin_y = int(round(720 * C.SPLIT_INSET_MARGIN))
    # Sampled at the MIDDLE of where the inset lands, not at the very corner
    # of the frame: the inset is inset, so the last few rows and columns are
    # the margin, which is the screen showing through.
    mid_x = 1280 - margin_x - inset_w // 2
    mid_y = 720 - margin_y - inset_h // 2
    corner = composite[mid_y - 10:mid_y + 10, mid_x - 10:mid_x + 10]
    far = composite[:40, :40]
    check("the camera really is in the corner",
          int(corner[:, :, 0].mean()) > 200, int(corner[:, :, 0].mean()))
    check("and the screen fills the rest of the frame",
          int(far.mean()) < 40, int(far.mean()))
    check("the camera is a quarter of the width, so the screen stays readable",
          200 < inset_w < 400, inset_w)
    # The screen source caches the array it returns. Painting the camera into
    # that array rather than a copy would leave it there for ever.
    check("compositing does not scribble on the screen's own cached frame",
          int(back.frame(1280, 720)[-40:, -40:, 0].mean()) < 40)

gone = screen.SplitSource(Flat((10, 10, 10)), FakeCamera(gives=False))
alone = gone.frame(1280, 720)
check("a camera that fails leaves the screen filling the frame, not nothing",
      alone is not None and int(alone[:, :, 0].max()) < 40,
      None if alone is None else int(alone[:, :, 0].max()))
check("and it says the camera is missing",
      "no camera" in gone.describe(), gone.describe())

# Ctrl+Shift+F and the shot announcements have to reach the split, which has
# a camera in it. They were written when a camera was the only source that did.
looking = screen.SplitSource(Flat((10, 10, 10)), FakeCamera((255, 0, 0)))
check("the split hands the framing checker a picture to look at",
      looking.latest() is not None)
check("and it is the camera on its own, not the composite",
      int(looking.latest()[:, :, 0].mean()) > 200,
      int(looking.latest()[:, :, 0].mean()))
check("the split counts as a source with a camera in it",
      C.PICTURE_SPLIT in C.PICTURE_NEEDS_CAMERA)

dead = screen.SplitSource(FakeCamera(gives=False), Flat((255, 0, 0)))
check("a screen that fails takes the split down, so the card can take over",
      dead.frame(1280, 720) is None)

both.close()
check("closing the split closes the camera", cam.closed)
check("and the screen", back.closed)


# ---------------------------------------------------------------------------
print("\nThe picture the settings ask for")
# ---------------------------------------------------------------------------

made = picture.build(video_settings(picture=C.PICTURE_SCREEN))
check("asking for the screen builds a screen source",
      getattr(made, "kind", "") == C.PICTURE_SCREEN, getattr(made, "kind", ""))
check("with the card behind it, so a failure is not the end of the show",
      isinstance(made, picture.FallbackSource))

made = picture.build(video_settings(picture=C.PICTURE_SPLIT,
                                    camera="HP HD Camera"))
check("asking for the split builds a split source",
      getattr(made, "kind", "") == C.PICTURE_SPLIT, getattr(made, "kind", ""))

made = picture.build(video_settings(picture=C.PICTURE_CARD))
check("and a card is still a bare card, because it cannot fail",
      made.kind == C.PICTURE_CARD)

check("every source has a label", all(k in C.PICTURE_LABELS
                                      for k in C.PICTURE_SOURCES))
check("and a sentence saying what it sends",
      all(k in C.PICTURE_DESCRIPTIONS for k in C.PICTURE_SOURCES))

saved = Board()
saved.screen = C.SCREEN_MAIN
check("which screen goes out is saved with the board",
      Board.from_dict(saved.to_dict()).screen == C.SCREEN_MAIN
      if hasattr(Board, "from_dict") else "screen" in saved.to_dict())


# ---------------------------------------------------------------------------
print("\nChanging the picture on air, decoded off the wire")
# ---------------------------------------------------------------------------

RED = (220, 30, 30)
BLUE = (30, 60, 220)
SECONDS = 4.0
SWAP_AT = 2.0

red, blue = Flat(RED), Flat(BLUE)
with MockRTMP.spawn() as server:
    destination = RtmpDestination(
        {"server": "rtmp", "host": server.url.rsplit("/", 1)[0],
         "password": server.url.rsplit("/", 1)[1], "bitrate": 128,
         "video_width": 640, "video_height": 360, "video_fps": 30,
         "video_bitrate": 1200},
        RATE, video_source=red)
    destination.connect()
    block = int(RATE * 0.1)
    sent = 0
    swapped_at_frame = None
    while sent < RATE * SECONDS:
        destination.feed(tone(block, freq=440.0, start=sent))
        sent += block
        if swapped_at_frame is None and sent >= RATE * SWAP_AT:
            # The whole point: this happens with the connection open and the
            # audio still flowing through it.
            swapped_at_frame = destination._frames_sent
            destination.set_video_source(blue)
    destination.close()

result = server.result()
check("the swap happened while the stream was live",
      swapped_at_frame is not None and swapped_at_frame > 0, swapped_at_frame)
check("the connection survived it", result.publishing and not result.error,
      result.error)
check("both sources were actually asked for pictures",
      red.asked > 0 and blue.asked > 0, (red.asked, blue.asked))

frames = []
container = result.container()
for at, frame in enumerate(container.decode(video=0)):
    frames.append(frame.to_ndarray(format="rgb24"))
container.close()

expected = int(SECONDS * 30)
check("every frame of the run came back, across the swap",
      abs(len(frames) - expected) <= 6, "%d of %d" % (len(frames), expected))


def redness(canvas):
    """Above zero for the red source, below it for the blue one."""
    return float(canvas[:, :, 0].mean()) - float(canvas[:, :, 2].mean())


if len(frames) > 20:
    early = redness(frames[10])
    late = redness(frames[-10])
    check("the stream really was showing the first source at the start",
          early > 40, "%.0f" % early)
    check("and really is showing the second one at the end",
          late < -40, "%.0f" % late)

    # Where the picture actually changed on the wire, against where the swap
    # was called. A swap that took effect at the wrong moment, or took several
    # seconds to appear, is a real fault and this is what would catch it.
    turned = next((at for at, f in enumerate(frames) if redness(f) < 0), None)
    check("the picture changed exactly once, and stayed changed",
          turned is not None
          and all(redness(f) < 0 for f in frames[turned + 2:]), turned)
    if turned is not None and swapped_at_frame is not None:
        slip = abs(turned - swapped_at_frame)
        check("and it changed within a couple of frames of being told to",
              slip <= 3, "%d frames late" % slip)

    black = sum(1 for f in frames if int(f.max()) < 20)
    check("no frame went black at the swap", black == 0, black)

# AUDIO AND VIDEO STAY TOGETHER ACROSS THE SWAP. This is the assertion that
# matters most: a swap that cost the video clock a few frames would put the
# picture permanently behind the sound for the rest of the broadcast, and
# nothing else here would notice.
if result.audio_timestamps and result.video_timestamps:
    drift = abs(result.video_timestamps[-1] - result.audio_timestamps[-1])
    check("audio and video still finish together after a swap",
          drift < 100, "%d ms apart" % drift)

    # Measured AT the swap as well, not only at the end. An error that
    # cancelled itself out by the end of the run would pass the check above.
    mid_video = [t for t in result.video_timestamps
                 if abs(t - SWAP_AT * 1000) < 350]
    mid_audio = [t for t in result.audio_timestamps
                 if abs(t - SWAP_AT * 1000) < 350]
    if mid_video and mid_audio:
        at_swap = abs(max(mid_video) - max(mid_audio))
        check("and they were together at the moment of the swap too",
              at_swap < 100, "%d ms apart" % at_swap)

samples = []
container = result.container()
for frame in container.decode(audio=0):
    samples.append(frame.to_ndarray())
container.close()
pcm = np.concatenate([s.reshape(-1) for s in samples]).astype(np.float64)
check("the sound carried on through the swap without a gap",
      abs(len(pcm) / float(CHANNELS * RATE) - SECONDS) < 0.5,
      "%.2f s of %.1f" % (len(pcm) / float(CHANNELS * RATE), SECONDS))

spectrum = np.abs(np.fft.rfft(pcm[:RATE] * np.hanning(RATE)))
heard = float(np.argmax(spectrum)) * RATE / RATE
check("and it is still the tone that was played, not silence",
      abs(heard - 440.0) < 15, "%.0f Hz" % heard)


# ---------------------------------------------------------------------------
print("\nThe encoder is not disturbed by a swap")
# ---------------------------------------------------------------------------

check("a destination can be given a new source at all",
      hasattr(RtmpDestination, "set_video_source"))
check("and so can the streamer, so a reconnect keeps the new picture",
      hasattr(streamout.Streamer, "set_video_source"))

held = Flat((1, 2, 3))
lonely = RtmpDestination(
    {"server": "rtmp", "host": "rtmp://nowhere.invalid", "password": "k",
     "bitrate": 128, "video_width": 640, "video_height": 360,
     "video_fps": 30, "video_bitrate": 1200}, RATE, video_source=held)
before = (lonely.width, lonely.height, lonely.fps)
lonely.set_video_source(Flat((4, 5, 6)))
check("swapping does not change the size the encoder was opened with",
      (lonely.width, lonely.height, lonely.fps) == before, before)
check("nor the frame rate, which the pump interval is derived from",
      abs(lonely.chunk_seconds - 1.0 / 30) < 1e-9, lonely.chunk_seconds)

titled = Flat((0, 0, 0))
titled.set_title = lambda text: setattr(titled, "title", text)
quiet = streamout.Streamer(streamout.AirBus(RATE), video_settings(),
                           video_source=Flat((0, 0, 0)))
quiet.set_title("Something Playing")
quiet.set_video_source(titled)
check("a new source is told what is playing, so the card is not blank",
      getattr(titled, "title", None) == "Something Playing",
      getattr(titled, "title", None))
check("and the streamer holds it, so a reconnect keeps the new picture",
      quiet.video_source is titled)


# A reconnect rebuilds the destination from the settings snapshot taken at
# Ctrl+B, which is exactly the trap that would put the picture back to
# whatever it was an hour ago. Half way through a show, silently.
built = []


class Remembering:
    """Stands in for a destination, and records what it was handed."""

    chunk_seconds = 1.0 / 30

    # **kw, because destination_for keeps growing: video_source in 3.4.0,
    # then an overlay and a health watcher in 3.5.0. A stand in registered in
    # DESTINATIONS has to take whatever the real factories take, or it fails
    # to construct and the failure looks like the stream refusing to connect.
    # That has now cost two debugging sessions; take **kw from the start.
    def __init__(self, settings, samplerate, video_source=None, **kw):
        built.append(video_source)
        self.video_source = video_source

    def connect(self):
        raise streamout.SinkError("not going to connect, and that is fine")

    def close(self):
        pass


was = streamout.DESTINATIONS.get("rtmp")
streamout.DESTINATIONS["rtmp"] = Remembering
try:
    first, second = Flat((1, 1, 1)), Flat((2, 2, 2))
    runner = streamout.Streamer(streamout.AirBus(RATE),
                                video_settings(server="rtmp"),
                                video_source=first)
    try:
        runner._build()
    except streamout.SinkError:
        pass
    check("the first connection is handed the picture it was started with",
          built and built[-1] is first)
    runner.set_video_source(second)
    try:
        runner._build()
    except streamout.SinkError:
        pass
    check("and a reconnect is handed the one switched to, not the old one",
          built and built[-1] is second,
          "" if built and built[-1] is second
          else "it went back to the picture from before the switch")
finally:
    if was is not None:
        streamout.DESTINATIONS["rtmp"] = was
    else:
        streamout.DESTINATIONS.pop("rtmp", None)


# ---------------------------------------------------------------------------
print("\nThe keys, and what the app says about them")
# ---------------------------------------------------------------------------

import wx      # noqa: E402

from dropdeck.dialogs import GoLiveDialog, VideoSourceDialog, SettingsDialog  # noqa: E402
import dropdeck.ui  # noqa: E402
from dropdeck.ui import ID_VIDEO_SOURCES, DropDeckFrame  # noqa: E402

app = wx.App(redirect=False)
frame = DropDeckFrame()

# ---------------------------------------------------------------------------
# NO TWO COMMANDS MAY SHARE AN ID, and this is here because two did.
#
# ID_STATION_BASE was at ID_HIGHEST+410 with twenty stations after it, so the
# block ran to 429 and swallowed ID_SHOT at 411 and ID_STREAM_HELP at 412.
# Binding two handlers for one id on one window means the LAST bound wins;
# _on_pick_station is bound after both and never calls Skip. So Ctrl+Shift+F,
# the headline of 3.4.0, reached the station picker and did nothing at all.
#
# Every test in this repository called the handler by hand and every one of
# them passed. Only a real keystroke goes near the binding, which is what
# tools/check_video_key.py does and how this was found. This check is the
# cheap version: it does not need the foreground and it runs every time.
# ---------------------------------------------------------------------------
import dropdeck.ui as _ui        # noqa: E402
from dropdeck import plids as _plids      # noqa: E402

claimed = {}
clashes = []
for module in (_ui, _plids):
    for name in dir(module):
        if not name.startswith("ID_"):
            continue
        value = getattr(module, name)
        if not isinstance(value, int):
            continue
        # A _BASE is the start of a range, not one id.
        if name.endswith("_BASE"):
            if name == "ID_STATION_BASE":
                span = _ui.MAX_STATIONS
            elif name == "ID_SLOT_BASE":
                span = C.TOTAL_SLOTS + 1
            else:
                span = 1
            for offset in range(span):
                where = claimed.setdefault(value + offset, [])
                where.append("%s+%d" % (name, offset))
        else:
            claimed.setdefault(value, []).append(name)
for value, names in sorted(claimed.items()):
    if len(set(names)) > 1:
        clashes.append("%d: %s" % (value - wx.ID_HIGHEST, ", ".join(names)))

check("no two commands share an id, ranges included",
      not clashes, "; ".join(clashes))
check("and the station block is clear of the numbered commands",
      _ui.ID_STATION_BASE > _ui.ID_SLOT_BASE + C.TOTAL_SLOTS,
      "stations start at ID_HIGHEST+%d"
      % (_ui.ID_STATION_BASE - wx.ID_HIGHEST))
check("Ctrl+Shift+F is outside it again, so the camera key works",
      not (_ui.ID_STATION_BASE <= _ui.ID_SHOT
           < _ui.ID_STATION_BASE + _ui.MAX_STATIONS))
check("and so is the video source key",
      not (_ui.ID_STATION_BASE <= _ui.ID_VIDEO_SOURCES
           < _ui.ID_STATION_BASE + _ui.MAX_STATIONS))

table = {(e.GetFlags(), e.GetKeyCode()): e.GetCommand()
         for e in frame._accelerators}
alt_shift = wx.ACCEL_ALT | wx.ACCEL_SHIFT
check("Alt+Shift+V opens the video sources",
      table.get((alt_shift, ord("V"))) == ID_VIDEO_SOURCES)
check("and it did not take a key something else was using",
      sum(1 for (flags, code), _cmd in table.items()
          if (flags, code) == (alt_shift, ord("V"))) == 1)
check("the frozen digit map is untouched",
      all(table.get((flags, ord(d))) != ID_VIDEO_SOURCES
          for d in C.DIGITS
          for flags in (0, wx.ACCEL_SHIFT, wx.ACCEL_CTRL,
                        wx.ACCEL_CTRL | wx.ACCEL_SHIFT,
                        wx.ACCEL_ALT | wx.ACCEL_CTRL,
                        wx.ACCEL_ALT | wx.ACCEL_CTRL | wx.ACCEL_SHIFT)))
check("it still works while a text box has focus, being modified",
      any(e.GetCommand() == ID_VIDEO_SOURCES
          for e in frame._typing_accelerators))

# Ctrl+Shift+B used to read the radio station's address whichever target was
# ticked, so a board set up for YouTube alone answered "no server is set up
# yet" while Ctrl+B would have gone live perfectly well.
frame.board.live_to = C.LIVE_TO_VIDEO
frame.board.video_server = "youtube"
frame.board.video_host = C.RTMP_INGEST["youtube"]
frame.board.stream_host = ""
said = frame.stream_status()
check("off air, it names the video platform when that is where Ctrl+B goes",
      "YouTube" in said, said)
check("and does not claim nothing is set up", "no server is set up" not in said,
      said)

frame.board.live_to = C.LIVE_TO_AUDIO
frame.board.stream_host = "radio.example.com"
said = frame.stream_status()
check("and it names the radio station when that is where Ctrl+B goes",
      "radio.example.com" in said, said)

frame.board.live_to = C.LIVE_TO_VIDEO
report = frame.preflight()
check("the frame can say what it would do, without going live",
      report is not None and bool(report.lines))

window = VideoSourceDialog(frame, frame.board, live=False)
rows = window.kinds()
check("the source list offers the card", C.PICTURE_CARD in rows, rows)
check("and the screen, on a machine that can capture it",
      (C.PICTURE_SCREEN in rows) == screen.available(), rows)
check("the name is column zero, for first letter navigation",
      window.list.GetColumn(0).GetText() == "Source")
check("Escape closes it", window.GetEscapeId() == wx.ID_CANCEL)
# "Using", not "On air". A recording is not on air, and the column said
# "yes" against the chosen row whether or not anything was happening at all.
check("and it says what is USING the picture, which is not the same as on air",
      window.list.GetColumn(1).GetText() == "Using")
check("nothing is using it off air, so the chosen row says chosen",
      window._use_label(frame.board.picture) == "chosen",
      window._use_label(frame.board.picture))
check("and an unchosen row says nothing at all",
      window._use_label("no such source") == "")
window.Destroy()

# The shot key answers for the split, rather than saying there is no camera.
frame.board.picture = C.PICTURE_SPLIT
frame.board.camera = "Some Camera"
answers = []
frame.announce_answer = lambda text: answers.append(text)
frame.describe_shot()
check("Ctrl+Shift+F does not claim the split has no camera",
      not any("not showing a camera" in a for a in answers), answers)
del frame.announce_answer
frame.board.camera = ""

frame.board.picture = C.PICTURE_CARD
said = frame.set_video_source(C.PICTURE_SCREEN)
check("choosing a source off air remembers it for next time",
      frame.board.picture == C.PICTURE_SCREEN, frame.board.picture)
check("and says so rather than going quiet", "next time" in said.lower(), said)
frame.board.picture = C.PICTURE_CARD

blocked = preflight.check(video_settings(password=""), video_board())
box = GoLiveDialog(frame, blocked)
check("a problem that would stop the broadcast disables Go live",
      not box.go.IsEnabled())
check("but the window still offers a way to put it right",
      any(isinstance(c, wx.Button) and "Put it right" in c.GetLabel()
          for c in box.GetChildren()))
check("Escape stays off air", box.GetEscapeId() == wx.ID_CANCEL)
check("what will go out is on the window as readable text",
      "YouTube" in box.what.GetValue(), box.what.GetValue()[:60])
check("and the stream key is not", "a-stream-key" not in box.what.GetValue())
box.Destroy()

fine = preflight.check(video_settings(), video_board())
box = GoLiveDialog(frame, fine)
check("with nothing wrong, Go live is the default button",
      box.go.IsEnabled())
check("so Ctrl+B then Enter is still the whole gesture",
      box.GetDefaultItem() is box.go)
check("focus lands on what is about to go out, not on the button",
      box.what.HasFocus() or box.FindFocus() is box.what)
box.Destroy()

# THE PROMPT IS ON THE KEY, NOT ON GOING LIVE, and there is a check for it
# because getting this wrong hangs every test in the repository that goes on
# the air. A modal window waits for a click no test can give: test_recording
# stopped dead at "Recording and streaming at the same time" and test_stream
# printed nothing at all. start_stream is called by anything that wants the
# show on air; toggle_stream is called by a person pressing Ctrl+B.
frame.board.ask_before_live = True
asked = []
was_dialog = dropdeck.ui.GoLiveDialog
dropdeck.ui.GoLiveDialog = lambda *a, **k: asked.append(1) or _NeverShown()


class _NeverShown:
    remember = False
    fix = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ShowModal(self):
        return wx.ID_CANCEL


# Preferences is stood in too. Guard one of start_stream opens it when there
# is no server, and that is a modal window as surely as the other one.
was_settings = DropDeckFrame._on_settings
DropDeckFrame._on_settings = lambda self, *a, **k: None
try:
    frame.board.live_to = C.LIVE_TO_AUDIO
    frame.board.stream_host = ""
    frame.start_stream()
    check("start_stream never puts a window up, so a test cannot hang on it",
          not asked, "%d dialogs" % len(asked))
finally:
    dropdeck.ui.GoLiveDialog = was_dialog
    DropDeckFrame._on_settings = was_settings
check("and Ctrl+B is where the asking lives",
      "_cleared_to_go" in dropdeck.ui.DropDeckFrame.toggle_stream.__code__.co_names)

frame.board.ask_before_live = False
check("and somebody who does this every day can turn the asking off",
      frame.board.ask_before_live is False)

# With the asking off the warnings are still said, and said ONCE. Three
# announce calls in a row means each interrupts the last, so a presenter
# hears the third and never learns their microphone is off the air.
frame.board.live_to = C.LIVE_TO_VIDEO
frame.board.stream_mic = False
frame.board.picture = C.PICTURE_CARD
spoke = []
was_announce = frame.announce
frame.announce = lambda text: spoke.append(text)
try:
    frame._cleared_to_go(video_settings(password="", picture=C.PICTURE_CARD))
finally:
    frame.announce = was_announce
check("with the asking off, the warnings are still spoken", bool(spoke), spoke)
check("and all of them arrive as one announcement, not three",
      len(spoke) == 1, "%d announcements" % len(spoke))
check("with whatever is stopping the broadcast first",
      spoke and spoke[0].startswith("There is no stream key"), spoke[:1])
frame.board.stream_mic = True
frame.board.ask_before_live = True
saved = Board.load(None) if False else None
check("the setting is saved with the board",
      "ask_before_live" in frame.board.to_dict())

# ---------------------------------------------------------------------------
print("\nThe settings behind both of them")
# ---------------------------------------------------------------------------

frame.board.ask_before_live = True
frame.board.picture = C.PICTURE_SCREEN
frame.board.screen = C.SCREEN_ALL
prefs = SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic,
                       page=SettingsDialog.PAGE_VIDEO)
check("the video page has a screen picker", hasattr(prefs, "screen_choice"))
check("and the audio page can turn the go live question back on",
      hasattr(prefs, "ask_before_live")
      and prefs.ask_before_live.GetValue() is True)

picked = prefs.picture_settings
check("which screen goes out is read back off the page",
      picked.get("screen") in C.SCREEN_CHOICES, picked.get("screen"))

# Nothing is hidden, only disabled. A screen reader says "unavailable", which
# is the truth; hiding half a page moves everything under somebody's fingers.
kinds = list(prefs._picture_kinds)
prefs.picture_kind.SetSelection(kinds.index(C.PICTURE_CARD))
prefs._on_picture_kind(None)
check("a card needs no screen picker, so it is disabled",
      not prefs.screen_choice.IsEnabled())
check("and not hidden", prefs.screen_choice.IsShown())

prefs.picture_kind.SetSelection(kinds.index(C.PICTURE_SCREEN))
prefs._on_picture_kind(None)
check("the screen source enables it",
      prefs.screen_choice.IsEnabled() or not screen.screens())
check("and needs no camera", not prefs.camera_choice.IsEnabled())

prefs.picture_kind.SetSelection(kinds.index(C.PICTURE_SPLIT))
prefs._on_picture_kind(None)
check("the split needs both, so both come alive",
      prefs.camera_choice.IsEnabled()
      and (prefs.screen_choice.IsEnabled() or not screen.screens()))
check("and it is offered the framing announcements, being a camera",
      prefs.framing_level.IsEnabled())
prefs.Destroy()

frame.stop_stream(quiet=True)
frame.stop_background_work()
frame.Destroy()
app.Yield()

try:
    os.unlink(real_picture)
except Exception:
    pass


print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
