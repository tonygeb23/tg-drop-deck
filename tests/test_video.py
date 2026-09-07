"""Going out on YouTube and Facebook: the picture, and the RTMP that carries it.

Nothing here touches the internet. `tools/mock_rtmp.py` speaks enough of the
protocol for FFmpeg's client to publish to it, keeps every message, and rebuilds
them into an FLV. So these tests DECODE what arrived rather than counting bytes,
for the reason `test_stream.py` gives: a stream that connects and sends silence
looks perfect from the sending end.

    python tests/test_video.py
"""

import fractions
import io
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-video-test-")

import av

from dropdeck import constants as C
from dropdeck import picture, streamout
from dropdeck.engine import CHANNELS
from dropdeck.streamout import AirBus, RtmpDestination, Streamer
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


def dominant(pcm, rate=RATE):
    """The loudest frequency in a block, for proving it is the real audio."""
    n = min(len(pcm), rate)
    if n < 256:
        return 0.0
    spectrum = np.abs(np.fft.rfft(pcm[:n] * np.hanning(n)))
    return float(np.argmax(spectrum)) * rate / n


def ink(canvas):
    """How much of a card is not the background. Zero means nothing drawn."""
    background = np.asarray(C.CARD_BACKGROUND, dtype=np.uint8)
    return int(np.count_nonzero(np.any(canvas != background, axis=2)))


# ---------------------------------------------------------------------------
print("The card, which is what a radio show sends")
# ---------------------------------------------------------------------------

card = picture.CardSource(name="Tony Gebhard Show")
frame = card.frame(1280, 720)
check("it draws at the size asked for", frame.shape == (720, 1280, 3),
      frame.shape)
check("and it is 8 bit RGB, which is what the encoder wants",
      frame.dtype == np.uint8, frame.dtype)
check("the station name is actually on it", ink(frame) > 500, ink(frame))

blank = picture.CardSource(name="")
check("a card with no name still draws something",
      ink(blank.frame(640, 360)) > 0)

# The title
before = ink(card.frame(1280, 720))
card.set_title("Fleetwood Mac - Dreams")
after_frame = card.frame(1280, 720)
check("adding a title puts more on the card", ink(after_frame) > before,
      "%d then %d" % (before, ink(after_frame)))
check("and the card says what the title is", card.title == "Fleetwood Mac - Dreams")

# Caching, which is the whole reason this is cheap
card.redraws = 0
card.set_title("Cache Test")
for _ in range(50):
    card.frame(1280, 720)
check("the same card is drawn once, not fifty times", card.redraws == 1,
      card.redraws)
card.set_title("Something Else")
card.frame(1280, 720)
check("and a new title redraws it", card.redraws == 2, card.redraws)

# A long title must not run off the edge or raise
card.set_title("A" * 400)
long_frame = card.frame(1280, 720)
check("an absurdly long title still draws", long_frame.shape == (720, 1280, 3))
check("and stays inside the picture", ink(long_frame) > 0)

# Characters the font does not have
card.set_title("Sigur Ros - Hoppipolla üé你好")
odd = card.frame(640, 360)
check("a title with characters the font lacks does not raise",
      odd.shape == (360, 640, 3))

start = time.perf_counter()
fresh = picture.CardSource(name="Speed Test")
for i in range(30):
    fresh.set_title("Track %d" % i)
    fresh.frame(1280, 720)
cost = (time.perf_counter() - start) / 30 * 1000
check("drawing a fresh card costs under 40 ms", cost < 40, "%.1f ms" % cost)


# ---------------------------------------------------------------------------
print("\nText that has to fit")
# ---------------------------------------------------------------------------

check("width grows with the string",
      picture.text_width("AAAA", 2) > picture.text_width("AA", 2))
check("an empty string is no width", picture.text_width("", 3) == 0)
check("a big string gets a small scale",
      picture.fit_scale("A" * 100, 600, 8) < picture.fit_scale("AB", 600, 8))
check("shortening ends with a full stop rather than a hard cut",
      picture.shorten("A" * 200, 200, 2).endswith("..."))
check("and something that fits is left alone",
      picture.shorten("SHORT", 4000, 2) == "SHORT")


# ---------------------------------------------------------------------------
print("\nA picture file, and what happens when it is not one")
# ---------------------------------------------------------------------------

art_dir = tempfile.mkdtemp(prefix="dropdeck-art-")
art_path = os.path.join(art_dir, "art.png")
with av.open(art_path, mode="w") as container:
    stream = container.add_stream("png", rate=1)
    stream.width, stream.height, stream.pix_fmt = 400, 200, "rgb24"
    block = np.zeros((200, 400, 3), dtype=np.uint8)
    block[:, :, 0] = 255                       # solid red, easy to recognise
    art_frame = av.VideoFrame.from_ndarray(block, format="rgb24")
    for packet in stream.encode(art_frame):
        container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)

image = picture.ImageSource(art_path)
shown = image.frame(1280, 720)
check("a picture file loads", shown.shape == (720, 1280, 3))
check("and it is not blank", ink(shown) > 1000, ink(shown))
reds = int(np.count_nonzero((shown[:, :, 0] > 200) & (shown[:, :, 1] < 60)))
check("the red really reaches the frame", reds > 10000, reds)
check("a 2:1 picture is letterboxed, not stretched",
      int(np.count_nonzero(np.all(shown == np.asarray(C.CARD_BACKGROUND),
                                  axis=2))) > 1000)

missing = picture.ImageSource(os.path.join(art_dir, "nope.png"))
mframe = missing.frame(640, 360)
check("a missing picture gives a frame rather than raising",
      mframe.shape == (360, 640, 3))
check("and says what went wrong", "not there" in missing.error, missing.error)

junk_path = os.path.join(art_dir, "junk.png")
with open(junk_path, "wb") as handle:
    handle.write(b"this is not a picture")
junk = picture.ImageSource(junk_path)
check("a file that is not a picture gives a frame too",
      junk.frame(320, 180).shape == (180, 320, 3))
check("and says so", bool(junk.error), junk.error)


# ---------------------------------------------------------------------------
print("\nA picture source that fails must not take the show off the air")
# ---------------------------------------------------------------------------

class Breaks(picture.PictureSource):
    kind = C.PICTURE_CAMERA

    def __init__(self):
        self.calls = 0

    def frame(self, width, height):
        self.calls += 1
        raise OSError("the camera was unplugged")

    def describe(self):
        return "a camera"


said = []
broken = picture.FallbackSource(Breaks(), picture.CardSource(name="Backup"),
                                on_fallback=said.append)
got = broken.frame(640, 360)
check("a camera that throws still gives a picture",
      got.shape == (360, 640, 3))
check("and the presenter is told once", len(said) == 1, said)
for _ in range(30):
    broken.frame(640, 360)
check("not once a frame, which would be thirty times a second",
      len(said) == 1, len(said))
check("the failing source is not asked again either",
      broken.primary.calls == 1, broken.primary.calls)
check("and it says it fell back", "card" in broken.describe(),
      broken.describe())


# ---------------------------------------------------------------------------
print("\nThe keyframe interval, which decides whether YouTube is happy")
# ---------------------------------------------------------------------------

def keyframes(encoder, fps=30, frames=150):
    """Where the keyframes land, on content that changes a lot."""
    buf = io.BytesIO()
    container = av.open(buf, mode="w", format="flv")
    stream = container.add_stream(encoder, rate=fps)
    stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"
    stream.bit_rate = 2_000_000
    stream.options = streamout._video_options(encoder, fps)
    found = []
    index = 0
    for i in range(frames):
        if i % 7 == 0:
            block = np.random.randint(0, 60, (360, 640, 3), dtype=np.uint8)
        else:
            block = np.full((360, 640, 3), (i * 3) % 255, dtype=np.uint8)
        video = av.VideoFrame.from_ndarray(block, format="rgb24")
        video = video.reformat(format="yuv420p")
        video.pts = i
        for packet in stream.encode(video):
            if packet.is_keyframe:
                found.append(index)
            index += 1
    for packet in stream.encode():
        if packet.is_keyframe:
            found.append(index)
        index += 1
    container.close()
    return found


want = C.RTMP_FPS * C.RTMP_KEYFRAME_SECONDS
for name in (C.RTMP_VIDEO_ENCODER, C.RTMP_VIDEO_ENCODER_FALLBACK):
    try:
        marks = keyframes(name)
    except Exception as exc:
        check("%s can encode at all" % name, False, exc)
        continue
    spacing = [b - a for a, b in zip(marks, marks[1:])]
    check("%s puts a keyframe every %d frames" % (name, want),
          spacing and all(gap == want for gap in spacing),
          "gaps %s" % spacing[:5])

check("which is two seconds, the number both platforms ask for",
      C.RTMP_KEYFRAME_SECONDS == 2)
check("and libx264 is told to stop scene cutting, or it ignores the interval",
      streamout._video_options("libx264", 30).get("sc_threshold") == "0")
check("while Media Foundation needs no such thing",
      "sc_threshold" not in streamout._video_options("h264_mf", 30))


# ---------------------------------------------------------------------------
print("\nThe ingest addresses")
# ---------------------------------------------------------------------------

check("YouTube and Facebook are both offered",
      "youtube" in C.STREAM_SERVER_ORDER and "facebook" in C.STREAM_SERVER_ORDER)
check("both go out encrypted, which Facebook insists on",
      all(url.startswith("rtmps://") for url in C.RTMP_INGEST.values()),
      C.RTMP_INGEST)
check("Facebook is on port 443, to get through firewalls",
      ":443" in C.RTMP_INGEST["facebook"])
check("every RTMP server has a name for the Preferences box",
      all(streamout.server_label(k) and streamout.server_label(k) != k
          for k in ("youtube", "facebook", "rtmp")))
check("and every server in the list has one, which is how this broke before",
      all(streamout.server_label(k) for k in C.STREAM_SERVER_ORDER))
check("Icecast is still not an RTMP destination",
      not streamout.is_rtmp("icecast") and streamout.is_rtmp("youtube"))

settings = {"server": "youtube", "host": C.RTMP_INGEST["youtube"],
            "password": "abcd-1234", "bitrate": 128}
dest = streamout.destination_for(settings, RATE)
check("a YouTube station builds an RTMP destination",
      isinstance(dest, RtmpDestination))
check("and the key is put on the end of the address",
      dest.url() == C.RTMP_INGEST["youtube"] + "/abcd-1234", dest.url())
check("an Icecast station still builds the old one",
      isinstance(streamout.destination_for({"server": "icecast"}, RATE),
                 streamout.IcecastDestination))

for missing, word in (({"server": "youtube", "host": "", "password": "k"},
                       "server address"),
                      ({"server": "youtube", "host": "rtmps://x",
                        "password": ""}, "stream key")):
    try:
        streamout.destination_for(missing, RATE).url()
        check("a station with no %s is refused" % word, False)
    except streamout.SinkError as exc:
        check("a station with no %s says so" % word, word in str(exc), exc)

check("the spoken description never contains the key",
      "abcd-1234" not in dest.describe(), dest.describe())
check("and names the platform instead",
      "youtube" in dest.describe(), dest.describe())


# ---------------------------------------------------------------------------
print("\nEnd to end: a real publish to a real RTMP server, then decoded")
# ---------------------------------------------------------------------------

SECONDS = 4

with MockRTMP.spawn(seconds=40) as server:
    live = picture.CardSource(name="Test Station", title="The First Track")
    destination = RtmpDestination(
        {"server": "rtmp", "host": server.url.rsplit("/", 1)[0],
         "password": server.url.rsplit("/", 1)[1], "bitrate": 128,
         "video_width": 640, "video_height": 360, "video_fps": 30,
         "video_bitrate": 1200},
        RATE, video_source=live)
    destination.connect()
    block = int(RATE * 0.25)
    sent = 0
    while sent < RATE * SECONDS:
        destination.feed(tone(block, freq=440.0, start=sent))
        sent += block
        if sent == RATE * 2:
            live.set_title("The Second Track")
    destination.close()

result = server.result()
check("the server saw a publish", result.publishing, result.commands)
check("the whole RTMP command sequence happened",
      all(c in result.commands
          for c in ("connect", "createStream", "publish")), result.commands)
check("the server parsed everything without complaining",
      not result.error, result.error)
check("audio arrived", result.audio > 100, result.audio)
check("and so did video", result.video > 50, result.video)

opened = result.container()
kinds = sorted(s.type for s in opened.streams)
check("what arrived has both a video and an audio stream",
      "video" in kinds and "audio" in kinds, kinds)
video_stream = opened.streams.video[0]
check("the video is H.264", video_stream.codec_context.name == "h264",
      video_stream.codec_context.name)
check("at the size that was asked for",
      (video_stream.width, video_stream.height) == (640, 360),
      (video_stream.width, video_stream.height))
check("the audio is AAC", opened.streams.audio[0].codec_context.name == "aac")
opened.close()

# Decoding, which is the only check that proves it is not silence and black.
decoded_video = 0
seen = []
container = result.container()
for frame in container.decode(video=0):
    decoded_video += 1
    if decoded_video in (10, 100):
        seen.append(frame.to_ndarray(format="rgb24"))
container.close()

expected = SECONDS * 30
check("about %d video frames come back out" % expected,
      abs(decoded_video - expected) <= 6, decoded_video)
check("and they are the card, not black",
      seen and ink(seen[0]) > 500, ink(seen[0]) if seen else 0)

samples = []
container = result.container()
for frame in container.decode(audio=0):
    samples.append(frame.to_ndarray())
container.close()
pcm = np.concatenate([s.reshape(-1) for s in samples]).astype(np.float64)
check("the audio that comes back is the tone that was sent",
      abs(dominant(pcm) - 440.0) < 15, "%.0f Hz" % dominant(pcm))
check("and there is roughly the right amount of it",
      abs(len(pcm) / float(CHANNELS * RATE) - SECONDS) < 0.5,
      "%.2f s" % (len(pcm) / float(CHANNELS * RATE)))

if result.audio_timestamps and result.video_timestamps:
    drift = abs(result.video_timestamps[-1] - result.audio_timestamps[-1])
    check("audio and video finish together, inside a hundred milliseconds",
          drift < 100, "%d ms apart" % drift)


# ---------------------------------------------------------------------------
print("\nThe Streamer drives it, exactly as it drives Icecast")
# ---------------------------------------------------------------------------

with MockRTMP.spawn(seconds=40) as server:
    bus = AirBus(RATE)
    host, key = server.url.rsplit("/", 1)
    streamer = Streamer(bus, {"server": "rtmp", "host": host, "password": key,
                              "bitrate": 128, "video_width": 320,
                              "video_height": 180, "video_fps": 30,
                              "video_bitrate": 600})
    streamer.start()
    deadline = time.time() + 15
    while time.time() < deadline and streamer.state != streamout.ON_AIR:
        bus.write("card", tone(2048))
        time.sleep(0.01)
    check("it goes on air", streamer.state == streamout.ON_AIR,
          "%s %s" % (streamer.state, streamer.detail))

    pushed = 0
    while pushed < RATE * 2:
        bus.write("card", tone(2048, start=pushed))
        pushed += 2048
        time.sleep(0.02)
    time.sleep(0.5)
    check("and the byte counter moves while it is still on air",
          streamer.bytes_sent > 0, streamer.bytes_sent)
    check("the spoken description says where it is going, not the key",
          key not in streamer._describe(), streamer._describe())
    streamer.stop()
    check("stopping comes off air", streamer.state == streamout.OFF,
          streamer.state)

after = server.result()
check("the server got the show through the Streamer",
      after.audio > 20 and after.video > 10,
      "%s audio, %s video" % (after.audio, after.video))


# ---------------------------------------------------------------------------
print("\nA server that is not there")
# ---------------------------------------------------------------------------

bus = AirBus(RATE)
dead = Streamer(bus, {"server": "rtmp", "host": "rtmp://127.0.0.1:9",
                      "password": "nokey", "bitrate": 128})
dead.start()
deadline = time.time() + 20
while time.time() < deadline and dead.state not in (streamout.RECONNECTING,
                                                    streamout.FAILED):
    bus.write("card", tone(2048))
    time.sleep(0.05)
check("a dead server does not hang the app",
      dead.state in (streamout.RECONNECTING, streamout.FAILED), dead.state)
check("and the reason is worth hearing, not an errno",
      dead.error and "Errno" not in dead.error, dead.error)
dead.stop()
check("and it stops cleanly", not dead.running)


# ---------------------------------------------------------------------------
print("\nPicking a picture source")
# ---------------------------------------------------------------------------

plain = picture.build({"picture": C.PICTURE_CARD, "name": "My Station"})
check("a card is just a card, with nothing behind it",
      isinstance(plain, picture.CardSource), type(plain).__name__)
check("and it takes the station name", plain.name == "My Station")

with_art = picture.build({"picture": C.PICTURE_IMAGE,
                          "picture_file": art_path, "name": "S"})
check("a picture file gets the card behind it",
      isinstance(with_art, picture.FallbackSource), type(with_art).__name__)
check("and still reports itself as a picture",
      with_art.kind == C.PICTURE_IMAGE, with_art.kind)

cam = picture.build({"picture": C.PICTURE_CAMERA, "camera": "Nothing At All",
                     "name": "S", "video_width": 640, "video_height": 360})
check("a camera gets the card behind it too",
      isinstance(cam, picture.FallbackSource))
cam.start()
fell = cam.frame(640, 360)
check("a camera that does not exist still gives a picture",
      fell.shape == (360, 640, 3), fell.shape)
check("and that picture is the card", ink(fell) > 0)
cam.close()

titled = picture.build({"picture": C.PICTURE_IMAGE, "picture_file": art_path,
                        "name": "S"})
titled.set_title("A Song")
check("a title reaches the card behind a failed source",
      titled.backup.title == "A Song", titled.backup.title)

unknown = picture.build({"picture": "something new"})
check("a picture kind nobody has heard of falls back to a card",
      isinstance(unknown, picture.CardSource))


# ---------------------------------------------------------------------------
print("\nThe title reaches the picture, not just the server")
# ---------------------------------------------------------------------------

live_card = picture.CardSource(name="Station")
bus = AirBus(RATE)
teller = Streamer(bus, {"server": "rtmp", "host": "rtmp://127.0.0.1:9",
                        "password": "k"}, video_source=live_card)
teller.set_title("Kate Bush - Cloudbusting")
check("what is playing goes to the card, because RTMP carries no title",
      live_card.title == "Kate Bush - Cloudbusting", live_card.title)
check("and an RTMP destination says plainly that it cannot send one",
      streamout.RtmpDestination({"host": "rtmps://x", "password": "k"},
                                RATE).send_metadata("Anything") is False)

teller.video_source = object()          # something with no set_title
try:
    teller.set_title("Still fine")
    check("a picture source with no title setter is not a crash", True)
except Exception as exc:
    check("a picture source with no title setter is not a crash", False, exc)


# ---------------------------------------------------------------------------
print("\nWhere a stream key is kept, which is not the board file")
# ---------------------------------------------------------------------------

from dropdeck import secrets

check("the board file's station fields are still the old ones",
      "stream_password" in __import__("dropdeck.board", fromlist=["board"]
                                      ).STATION_FIELDS)
check("a key is never shown in full", "abcdefghijkl" not in
      secrets.redact("abcdefghijkl"), secrets.redact("abcdefghijkl"))
check("but enough of it to recognise",
      secrets.redact("abcdefghijkl").endswith("ijkl"),
      secrets.redact("abcdefghijkl"))
check("and no key at all says so", secrets.redact("") == "not set")
check("a very short key is not half shown", secrets.redact("ab") == "set")

if secrets.available():
    station = "zz drop deck test station"
    key = "live-abcd-1234-wxyz"
    check("a key can be kept outside the board file",
          secrets.store(station, key))
    check("and read back exactly", secrets.fetch(station) == key)
    check("a key with unicode in it survives",
          secrets.store(station, "key-éü") and
          secrets.fetch(station) == "key-éü")
    check("forgetting one really removes it",
          secrets.forget(station) and secrets.fetch(station) == "")
    check("forgetting one twice is not a failure", secrets.forget(station))
    check("and an unknown station reads as empty rather than raising",
          secrets.fetch("zz no such station here") == "")
else:
    print("  skipped: no credential store on this machine")


# ---------------------------------------------------------------------------
print("\nThe camera, without needing one")
# ---------------------------------------------------------------------------

from dropdeck import camera

check("a camera in use is explained, not reported as an errno",
      "another program" in camera.explain(OSError("[Errno 5] I/O error"),
                                          "HP HD Camera").lower(),
      camera.explain(OSError("[Errno 5] I/O error"), "HP HD Camera"))
check("a camera Windows refuses points at Privacy settings",
      "privacy" in camera.explain(OSError("Permission denied"), "C").lower())
check("a camera that has gone says it may be unplugged",
      "unplugged" in camera.explain(OSError("Could not find video device"),
                                    "C").lower())
check("and the camera is named, so the user knows which one",
      "HP HD Camera" in camera.explain(OSError("x"), "HP HD Camera"))
check("no errno ever reaches the user",
      "Errno" not in camera.explain(OSError("[Errno 5] I/O error"), "C"))

check("sizes are said as people say them",
      camera.describe_size(1280, 720) == "720p", camera.describe_size(1280, 720))
check("including the rate when there is one",
      "30 frames" in camera.describe_size(1280, 720, 30))
check("and an odd size is still said, not hidden",
      camera.describe_size(1234, 567) == "1234 by 567")

found = camera.cameras()
check("enumerating cameras returns a list, even with none attached",
      isinstance(found, list), found)
if found:
    check("the fragmented device list is parsed into real names",
          all(isinstance(n, str) and n and '"' not in n for n in found), found)
    sizes = camera.capabilities(found[0])
    check("and a camera reports what sizes it can do",
          isinstance(sizes, list) and (not sizes or len(sizes[0]) == 3), sizes[:2])
    check("biggest first, so the default is the best it can do",
          len(sizes) < 2 or sizes[0][0] * sizes[0][1] >= sizes[1][0] * sizes[1][1])
else:
    print("  (no camera attached, so the parsing checks are skipped)")


# ---------------------------------------------------------------------------
print("\nThe Preferences box, driven for real")
# ---------------------------------------------------------------------------

import wx

from dropdeck.board import Board
from dropdeck.dialogs import SettingsDialog
from dropdeck.mixer import Mixer

_app = wx.App()
_frame = wx.Frame(None)
_board = Board()
_dialog = SettingsDialog(_frame, _board, Mixer(open_stream=False),
                         page=SettingsDialog.PAGE_PICTURE)


def pick_server(kind):
    _dialog.stream_server.SetSelection(C.STREAM_SERVER_ORDER.index(kind))
    _dialog._apply_server_kind()


try:
    check("there is a Picture page", hasattr(_dialog, "picture_kind"))
    check("it offers a card, a picture and a camera",
          len(_dialog.picture_kind.GetStrings()) == 3,
          _dialog.picture_kind.GetStrings())
    check("and a card is the default, not a camera",
          _dialog.picture_settings["picture"] == C.PICTURE_CARD)
    check("the boxes a card does not need are disabled, not hidden",
          not _dialog.picture_file.IsEnabled()
          and not _dialog.camera_choice.IsEnabled())
    check("and a clock is offered, because a card can have one",
          _dialog.picture_clock.IsEnabled())

    _dialog.picture_kind.SetSelection(
        _dialog._picture_kinds.index(C.PICTURE_CAMERA))
    _dialog._on_picture_kind(None)
    check("picking a camera enables the camera box",
          _dialog.camera_choice.IsEnabled())
    check("and the framing setting, which only a camera uses",
          _dialog.framing_level.IsEnabled())
    check("framing offers three levels, not a switch",
          len(_dialog.framing_level.GetStrings()) == 3)
    check("and problems only is the default",
          _dialog.picture_settings["framing_level"] == "problems")

    check("every server in the list has a label, none raising",
          len(_dialog.stream_server.GetStrings()) == len(C.STREAM_SERVER_ORDER),
          _dialog.stream_server.GetStrings())

    pick_server("icecast")
    check("Icecast wants a password and not a stream key",
          _dialog.stream_password.IsEnabled() and not _dialog.stream_key.IsEnabled())
    check("and its mount point and port are usable",
          _dialog.stream_mount.IsEnabled() and _dialog.stream_port.IsEnabled())

    pick_server("youtube")
    check("YouTube wants a stream key and not a password",
          _dialog.stream_key.IsEnabled() and not _dialog.stream_password.IsEnabled())
    check("its mount point and port are put out of the way",
          not _dialog.stream_mount.IsEnabled() and not _dialog.stream_port.IsEnabled())
    check("the address is filled in, because there is only one",
          _dialog.stream_host.GetValue() == C.RTMP_INGEST["youtube"],
          _dialog.stream_host.GetValue())
    check("and it cannot be edited into something wrong",
          not _dialog.stream_host.IsEnabled())
    check("there is a button to go and fetch the key",
          _dialog.stream_key_page.IsEnabled())

    pick_server("facebook")
    check("Facebook gets its own address",
          _dialog.stream_host.GetValue() == C.RTMP_INGEST["facebook"],
          _dialog.stream_host.GetValue())

    _dialog.stream_host.SetValue("rtmp://my.own.server/live")
    pick_server("youtube")
    check("switching to YouTube REPLACES an address it cannot use",
          _dialog.stream_host.GetValue() == C.RTMP_INGEST["youtube"],
          _dialog.stream_host.GetValue())

    pick_server("rtmp")
    check("and a custom server does not inherit a platform's address",
          _dialog.stream_host.GetValue() == "", _dialog.stream_host.GetValue())
    check("a custom server has no key page to open",
          not _dialog.stream_key_page.IsEnabled())
    check("but its address is the user's to type",
          _dialog.stream_host.IsEnabled())

    _dialog.stream_key.SetValue("secret-key-value")
    check("the key is a password box, so it is not on screen in full",
          _dialog.stream_key.GetWindowStyle() & wx.TE_PASSWORD)
    check("and it comes back through stream_settings",
          _dialog.stream_settings["key"] == "secret-key-value")
finally:
    _dialog.Destroy()
    _frame.Destroy()


# ---------------------------------------------------------------------------
print("\nThe app itself, built for real")
# ---------------------------------------------------------------------------

from dropdeck import ui

_live = ui.DropDeckFrame()
try:
    bar = _live.GetMenuBar()
    shot = None
    for i in range(bar.GetMenuCount()):
        for item in bar.GetMenu(i).GetMenuItems():
            if item.GetId() == ui.ID_SHOT:
                shot = (bar.GetMenuLabelText(i), item.GetItemLabel())
    # A key with no menu item behind it is a key nobody finds. This one was
    # exactly that for a while: the accelerator was wired and the Append
    # silently did not apply, so the feature worked and was invisible.
    check("what the camera can see is ON the menu, not only on a key",
          shot is not None, shot)
    if shot:
        check("on the On air menu, with the other broadcast answers",
              shot[0] == "On air", shot[0])
        check("and it names its key", "Ctrl+Shift+F" in shot[1], shot[1])

    check("the frame can answer about the shot", hasattr(_live, "describe_shot"))
    check("and answering off air does not raise",
          _live.describe_shot() is None)

    _live.board.picture = C.PICTURE_CAMERA
    _live.board.camera = ""
    check("with a camera chosen but none picked, it still answers",
          _live.describe_shot() is None)

    # Going live with no key must be refused HERE, not several seconds later
    # by YouTube with an I/O error.
    _live.board.stream_server = "youtube"
    _live.board.stream_host = C.RTMP_INGEST["youtube"]
    _live.board.stream_password = ""
    _live.board.stream_name = "zz station with no key at all"
    opened = []
    _live._on_settings = lambda *a, **k: opened.append(k.get("page"))
    check("going live with no stream key is refused before it connects",
          _live.start_stream() is False)
    check("and Preferences is opened at the page that fixes it",
          opened == [SettingsDialog.PAGE_STREAM], opened)
    check("nothing was left running", not _live.streaming())
finally:
    _live.stop_background_work()
    _live.Destroy()


# ---------------------------------------------------------------------------
print("\nFFmpeg's errors, turned into something a presenter can act on")
# ---------------------------------------------------------------------------

where = {"host": "rtmps://live-api-s.facebook.com:443/rtmp"}
cases = [
    ("[Errno 138] Error number -138 occurred", "could not reach"),
    ("[Errno 5] I/O error", "stream key"),
    ("Connection timed out", "did not answer"),
    ("something nobody has seen before", "could not connect"),
]
for raw, want in cases:
    said = streamout._explain_rtmp(OSError(raw), where)
    check("%r is explained, not repeated" % raw[:28], want in said, said)
    check("  and the errno is not read out", "Errno" not in said, said)

check("the host is named so the user knows which station failed",
      "facebook.com" in streamout._explain_rtmp(OSError("x"), where))

try:
    streamout._resolve("no-such-host-xyz123.invalid", 1935)
    check("a hostname that does not exist is caught before FFmpeg", False)
except streamout.SinkError as exc:
    check("a hostname that does not exist is caught before FFmpeg",
          "server address" in str(exc), exc)
try:
    streamout._resolve("127.0.0.1", 1935)
    check("and a real one is not", True)
except streamout.SinkError as exc:
    check("and a real one is not", False, exc)


print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
