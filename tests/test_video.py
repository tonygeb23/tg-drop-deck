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
import threading
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
# It IS asked again, but rarely. Never retrying was the bug: one glitched
# frame meant the card for the rest of the show even after the camera
# recovered. Thirty frames a second of retries would be the opposite fault.
check("the failing source is retried, but not on every frame",
      1 <= broken.primary.calls <= 3, broken.primary.calls)
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
for name in (C.RTMP_VIDEO_ENCODER,):
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
      "youtube" in C.VIDEO_SERVER_ORDER and "facebook" in C.VIDEO_SERVER_ORDER)
# The two fixed ones are encrypted and must stay so: Facebook has refused
# plain RTMP since 2018 and YouTube asks for RTMPS. Restream's is only a
# suggestion and is whatever their dashboard hands the user.
check("the fixed platforms go out encrypted, which Facebook insists on",
      all(C.RTMP_INGEST[k].startswith("rtmps://")
          for k in C.RTMP_FIXED_ADDRESS), C.RTMP_INGEST)
check("Facebook is on port 443, to get through firewalls",
      ":443" in C.RTMP_INGEST["facebook"])
check("every RTMP server has a name for the Preferences box",
      all(streamout.server_label(k) and streamout.server_label(k) != k
          for k in ("youtube", "facebook", "rtmp")))
check("and every server in either list has one, which is how this broke before",
      all(streamout.server_label(k)
          for k in C.STREAM_SERVER_ORDER + C.VIDEO_SERVER_ORDER))
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
                         page=SettingsDialog.PAGE_VIDEO)


def pick_platform(kind):
    _dialog.video_server.SetSelection(C.VIDEO_SERVER_ORDER.index(kind))
    _dialog._apply_platform()


try:
    tabs = [_dialog.tabs.GetPageText(i)
            for i in range(_dialog.tabs.GetPageCount())]
    check("audio and video streaming are separate pages",
          "Audio streaming" in tabs and "Video streaming" in tabs, tabs)
    check("and the old single Streaming page is gone",
          "Streaming" not in tabs, tabs)

    # The whole reason for the split. On one page, everything RTMP was
    # disabled while the server said Icecast, and Windows leaves disabled
    # controls OUT of the tab order, so the stream key could not be tabbed to
    # at all. Tony hit exactly that and could not find the setting.
    check("the stream key can be reached without changing anything first",
          _dialog.video_key.IsEnabled())
    check("the audio page offers only audio servers",
          _dialog.stream_server.GetStrings()
          == ["Icecast, or Liquidsoap harbor", "SHOUTcast"],
          _dialog.stream_server.GetStrings())
    check("and the video page only video platforms",
          len(_dialog.video_server.GetStrings()) == len(C.VIDEO_SERVER_ORDER),
          _dialog.video_server.GetStrings())
    check("no server appears on both",
          not set(C.STREAM_SERVER_ORDER) & set(C.VIDEO_SERVER_ORDER))

    check("the picture settings are on the video page",
          hasattr(_dialog, "picture_kind"))
    # Every source the app knows about, rather than a number that has to be
    # edited each time one is added. 3.4.1 added the screen and the split.
    check("it offers every picture source",
          len(_dialog.picture_kind.GetStrings()) == len(C.PICTURE_SOURCES),
          _dialog.picture_kind.GetStrings())
    check("and a card is the default, not a camera",
          _dialog.picture_settings["picture"] == C.PICTURE_CARD)
    check("the boxes a card does not need are disabled, not hidden",
          not _dialog.picture_file.IsEnabled()
          and not _dialog.camera_choice.IsEnabled())

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

    pick_platform("youtube")
    check("YouTube fills its own address in",
          _dialog.video_host.GetValue() == C.RTMP_INGEST["youtube"],
          _dialog.video_host.GetValue())
    check("and it cannot be edited into something wrong",
          not _dialog.video_host.IsEnabled())
    check("there is a button to go and fetch the key",
          _dialog.video_key_page.IsEnabled())

    pick_platform("facebook")
    check("Facebook gets its own address",
          _dialog.video_host.GetValue() == C.RTMP_INGEST["facebook"],
          _dialog.video_host.GetValue())

    _dialog.video_host.SetValue("rtmp://my.own.server/live")
    pick_platform("youtube")
    check("switching to YouTube REPLACES an address it cannot use",
          _dialog.video_host.GetValue() == C.RTMP_INGEST["youtube"],
          _dialog.video_host.GetValue())

    pick_platform("rtmp")
    check("and a custom server does not inherit a platform's address",
          _dialog.video_host.GetValue() == "", _dialog.video_host.GetValue())
    check("a custom server has no key page to open",
          not _dialog.video_key_page.IsEnabled())
    check("but its address is the user's to type",
          _dialog.video_host.IsEnabled())

    _dialog.video_key.SetValue("secret-key-value")
    check("the key is a password box, so it is not on screen in full",
          _dialog.video_key.GetWindowStyle() & wx.TE_PASSWORD)
    check("and it comes back through video_settings",
          _dialog.video_settings["key"] == "secret-key-value")

    # A URL pasted from Restream must survive looking at another platform.
    pick_platform("restream")
    _dialog.video_host.SetValue("rtmp://live-lon.restream.io/live")
    pick_platform("youtube")
    check("a fixed platform still shows its own address",
          _dialog.video_host.GetValue() == C.RTMP_INGEST["youtube"])
    pick_platform("restream")
    check("and an address typed for another platform is not thrown away",
          _dialog.video_host.GetValue() == "rtmp://live-lon.restream.io/live",
          _dialog.video_host.GetValue())
    check("Restream's address is editable, because Restream hands it out",
          _dialog.video_host.IsEnabled())


    check("Ctrl+B goes to the radio station until told otherwise",
          not _dialog.video_settings["live"])
    _dialog.live_to_video.SetValue(True)
    check("and there is one switch that sends it here instead",
          _dialog.video_settings["live"])

    print("\nTesting a video connection, which must NEVER go live")

    # The bug Tony hit: the Test button used the ICECAST path for a YouTube
    # station, so it opened a raw socket to the URL "rtmps://a.rtmps..." on
    # the leftover Icecast port and said "getaddrinfo failed".
    pick_platform("youtube")
    _dialog.video_key.SetValue("")
    _dialog._on_test_video(None)
    said = _dialog.picture_result.GetValue()
    check("with no key it says so rather than dialling anything",
          "no stream key" in said.lower(), said)
    check("and never mentions a port, which RTMP does not use here",
          "8000" not in said and "8003" not in said, said)

    _dialog.video_key.SetValue("abcd-efgh-ijkl-mnop")
    _dialog._on_test_video(None)
    said = _dialog.picture_result.GetValue()
    check("with a key it reaches YouTube for real",
          "reachable" in said.lower(), said)
    # A test that completes an RTMP publish is what STARTS a broadcast, and a
    # presenter who cannot see their channel would never notice. So this is
    # deliberately reachability only, and it must not overclaim.
    check("it says plainly that nothing was broadcast",
          "nothing was broadcast" in said.lower(), said)
    check("and admits it cannot prove the key is right",
          "cannot" in said.lower(), said)
    check("the key is never quoted back in full",
          "abcd-efgh-ijkl-mnop" not in said, said)

    pick_platform("rtmp")
    _dialog.video_host.SetValue("rtmp://no-such-host-xyz123.invalid/live")
    _dialog.video_key.SetValue("k")
    _dialog._on_test_video(None)
    said = _dialog.picture_result.GetValue()
    check("a bad address is reported as a bad address",
          "could not find" in said.lower(), said)
    check("and never as an errno", "Errno" not in said, said)
finally:
    _dialog.Destroy()
    _frame.Destroy()


# ---------------------------------------------------------------------------

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



# ---------------------------------------------------------------------------
print("\nWhat the audit found, so none of it comes back")
# ---------------------------------------------------------------------------

# A refused stream key used to retry for ever: every RTMP wording matched none
# of the Icecast ones in _retryable, so the state never reached FAILED, the app
# never came off air, and the reason was spoken exactly once and then never
# again all night.
for message in ("a.rtmps.youtube.com would not take the stream key. Check it "
                "has been copied in full and has not expired",
                "could not find no-such.invalid. Check the server address",
                "there is no stream key for this station",
                "there is no server address for this station"):
    quitter = Streamer(AirBus(RATE), {"server": "rtmp"})
    quitter.error = message
    check("a refused key stops rather than retrying for ever",
          not quitter._retryable(), message[:44])

for message in ("could not reach a.rtmps.youtube.com. Check the address",
                "a.rtmps.youtube.com did not answer"):
    keeper = Streamer(AirBus(RATE), {"server": "rtmp"})
    keeper.error = message
    check("but a server that is merely down is retried", keeper._retryable(),
          message[:44])

# The video key must never be written into the Icecast source password. It was,
# and merely opening the video page and pressing OK wiped a radio station's
# password.
_probe = Board()
check("the board keeps a stream key apart from the Icecast password",
      hasattr(_probe, "video_key") and _probe.video_key == "")
check("and they are two different fields",
      "video_key" in _probe.to_dict() and "stream_password" in _probe.to_dict())

# The audio and video sides must not share an address.
_probe.stream_host = "myradio.example.com"
_probe.video_host = C.RTMP_INGEST["youtube"]
check("a board can hold a radio station AND a video platform at once",
      _probe.stream_host != _probe.video_host)

# A board file is not a trusted document, and these were the two stream
# settings that were not whitelisted on the way in.
_junk_path = os.path.join(art_dir, "junk-board.json")
with open(_junk_path, "w", encoding="utf-8") as handle:
    import json as _json
    _json.dump({"stream_server": "twitch", "stream_format": "flac",
                "live_to": "everywhere", "video_server": "myspace"}, handle)
_junk = Board.load(_junk_path)
check("a server nobody has heard of falls back to Icecast",
      _junk.stream_server == "icecast", _junk.stream_server)
check("and a format nobody has heard of falls back to MP3",
      _junk.stream_format == "mp3", _junk.stream_format)
check("and a live_to nobody has heard of goes to the radio station",
      _junk.live_to == C.LIVE_TO_AUDIO, _junk.live_to)
check("and an unknown platform falls back to YouTube",
      _junk.video_server == "youtube", _junk.video_server)

# The stream description must come from the destination, not the board: RTMP
# is always AAC and H.264 whatever the audio format box happens to say.
_dest = RtmpDestination({"server": "youtube",
                         "host": C.RTMP_INGEST["youtube"],
                         "password": "k", "bitrate": 128}, RATE)
said = _dest.describe()
check("an RTMP destination describes itself as video and audio",
      "video" in said and "audio" in said, said)
check("and never as MP3, which it never sends", "MP3" not in said, said)

# The bus rate is used rather than a hard wired 44100.
_at48 = RtmpDestination({"server": "rtmp", "host": "rtmp://x", "password": "k"},
                        48000)
check("an RTMP destination runs at the rate the bus really is",
      _at48.samplerate == 48000, _at48.samplerate)

# FFmpeg throws away the only useful thing it knows. Check we read it back.
class _FakeLog:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


check("the server's own words are preferred to a guess",
      "not authorised" in streamout._explain_rtmp(
          OSError("[Errno 5] I/O error"), {"host": "rtmps://x/y"},
          streamout._server_error(_FakeLog(
              "[rtmp @ 0] Server error: not authorised\n"))).lower(),
      streamout._explain_rtmp(OSError("x"), {"host": "rtmps://x/y"},
                              "not authorised"))
check("a bad publish name is explained as a stream key",
      "stream key" in streamout._explain_rtmp(
          OSError("x"), {"host": "rtmps://x/y"},
          "NetStream.Publish.BadName").lower())
check("and with no server message it still falls back sensibly",
      "could not connect" in streamout._explain_rtmp(
          OSError("something new"), {"host": "rtmps://x/y"}).lower())

# The two platforms behave OPPOSITELY on connect and a presenter has to know.
check("YouTube is recorded as going live the moment you connect",
      C.RTMP_GOES_LIVE_AT_ONCE["youtube"] is True)
check("and Facebook as not", C.RTMP_GOES_LIVE_AT_ONCE["facebook"] is False)
check("the YouTube key page is the redirect that always works",
      "live_dashboard" in C.RTMP_KEY_PAGE["youtube"],
      C.RTMP_KEY_PAGE["youtube"])
check("and there is a backup ingest recorded for YouTube",
      C.RTMP_INGEST_BACKUP["youtube"].startswith("rtmps://b."),
      C.RTMP_INGEST_BACKUP["youtube"])

# Restream is the one place a full end to end test can go nowhere at all,
# because it only passes the stream on to channels the user has switched on.
check("Restream is offered as a platform of its own",
      "restream" in C.VIDEO_SERVER_ORDER)
check("and it is named, not left as a custom server",
      streamout.server_label("restream") == "Restream")
check("with an ingest suggested for it",
      "restream.io" in C.RTMP_INGEST["restream"], C.RTMP_INGEST["restream"])
# Restream hands out the URL WITH the key and it can differ by account and
# region, so unlike YouTube and Facebook its address stays the user's to edit.
check("whose address is the user's to change, unlike the fixed two",
      "restream" not in C.RTMP_FIXED_ADDRESS
      and "youtube" in C.RTMP_FIXED_ADDRESS
      and "facebook" in C.RTMP_FIXED_ADDRESS)
check("it builds an RTMP destination like the others",
      isinstance(streamout.destination_for(
          {"server": "restream", "host": C.RTMP_INGEST["restream"],
           "password": "k"}, RATE), RtmpDestination))
check("and whether it goes live is recorded as depending on the user",
      C.RTMP_GOES_LIVE_AT_ONCE["restream"] is None)


# ---------------------------------------------------------------------------
print("\nPacing, which is what made the picture choppy")
# ---------------------------------------------------------------------------

# The bug: video is pumped from feed(), so the pump interval IS the video
# pacing. At a quarter of a second, eight frames were muxed back to back and
# then nothing went out for over 200 ms. The AVERAGE gap was a perfect 33 ms
# the whole time, which is why an average is the wrong thing to measure and
# why this test looks at the p95 and the long gaps instead.

check("an RTMP destination pumps once per frame period, not once a quarter "
      "second",
      abs(RtmpDestination({"server": "rtmp", "host": "rtmp://x",
                           "password": "k", "video_fps": 30},
                          RATE).chunk_seconds - 1 / 30.0) < 0.001)
check("and it follows the frame rate actually chosen",
      abs(RtmpDestination({"server": "rtmp", "host": "rtmp://x",
                           "password": "k", "video_fps": 15},
                          RATE).chunk_seconds - 1 / 15.0) < 0.001)
check("while Icecast keeps the quarter second, being a pipe",
      streamout.IcecastDestination({"server": "icecast"},
                                   RATE).chunk_seconds
      == C.STREAM_CHUNK_SECONDS)
check("catching up is capped at a couple of frames, not a whole second of them",
      C.RTMP_CATCHUP_FRAMES <= 4, C.RTMP_CATCHUP_FRAMES)

_paced = []
_orig_mux = RtmpDestination._mux


def _timed_mux(self, packet):
    _paced.append((time.perf_counter(), getattr(packet.stream, "type", "?")))
    return _orig_mux(self, packet)


RtmpDestination._mux = _timed_mux
try:
    with MockRTMP.spawn(seconds=40) as server:
        host, key = server.url.rsplit("/", 1)
        bus = AirBus(RATE)
        paced = Streamer(bus, {"server": "rtmp", "host": host,
                               "password": key, "bitrate": 128,
                               "video_width": 640, "video_height": 360,
                               "video_fps": 30, "video_bitrate": 1200},
                         video_source=picture.CardSource(name="Pacing"))
        paced.start()
        # Fed at REAL TIME, the way a sound card does it. Feeding as fast as
        # the loop will go hides the whole problem.
        deadline = time.time() + 6
        pushed = 0
        block = 2048
        nxt = time.perf_counter()
        while time.time() < deadline:
            bus.write("main", tone(block, start=pushed))
            pushed += block
            nxt += block / float(RATE)
            wait = nxt - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
        paced.stop()
finally:
    RtmpDestination._mux = _orig_mux

_video = [t for t, kind in _paced if kind == "video"]
check("frames really went out", len(_video) > 100, len(_video))
if len(_video) > 100:
    gaps = np.diff(_video) * 1000.0
    long_gaps = int((gaps > 100).sum())
    check("no gap between frames over 100 ms", long_gaps == 0,
          "%d of %d" % (long_gaps, len(gaps)))
    check("the middle frame arrives about a frame period after the last",
          20 < float(np.median(gaps)) < 50, "%.1f ms" % np.median(gaps))
    # The measure that actually caught this: the average was always fine.
    check("and the slow tail stays inside two frame periods",
          float(np.percentile(gaps, 95)) < 90,
          "p95 %.1f ms" % np.percentile(gaps, 95))


# ---------------------------------------------------------------------------
print("\nThe encoder, and why it is not the obvious one")
# ---------------------------------------------------------------------------

check("libx264 is the default, not Media Foundation",
      C.RTMP_VIDEO_ENCODER == "libx264", C.RTMP_VIDEO_ENCODER)
# h264_mf was the default until it was measured. On 720p moving content at a
# 2500 kbps target it sent 23,412 kbps, ignored every rate control option, and
# emitted Constrained Baseline where both platforms want Main or High. A
# fallback that saturates the uplink and is then refused is worse than none.
check("Media Foundation is not in the fallback chain at all",
      "h264_mf" not in C.RTMP_VIDEO_ENCODERS, C.RTMP_VIDEO_ENCODERS)
check("and the chain starts with the one that was verified",
      C.RTMP_VIDEO_ENCODERS[0] == C.RTMP_VIDEO_ENCODER)
check("the rate may only swing half a second's worth",
      C.RTMP_VBV_SECONDS <= 0.5)
check("which is what keeps a cut to camera inside Facebook's band",
      streamout._video_options("libx264", 30, 2500)["bufsize"] == "1250k",
      streamout._video_options("libx264", 30, 2500)["bufsize"])


def encoder_latency(name, frames=90, fps=30, w=640, h=360):
    """Frames handed in before the first packet comes out."""
    buf = io.BytesIO()
    container = av.open(buf, mode="w", format="flv")
    stream = container.add_stream(name, rate=fps)
    stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
    stream.bit_rate = 1_200_000
    stream.options = streamout._video_options(name, fps, 1200)
    given = 0
    for i in range(frames):
        block = np.full((h, w, 3), (i * 3) % 255, dtype=np.uint8)
        picture_frame = av.VideoFrame.from_ndarray(block, format="rgb24")
        picture_frame = picture_frame.reformat(format="yuv420p")
        picture_frame.pts = i
        given += 1
        if list(stream.encode(picture_frame)):
            container.close()
            return given
    container.close()
    return given


_lat = encoder_latency(C.RTMP_VIDEO_ENCODER)
check("the default encoder adds no meaningful delay", _lat <= 2,
      "%d frames = %d ms" % (_lat, _lat / 30.0 * 1000))
# Media Foundation holds sixteen frames and cannot be told not to, which is
# 533 ms added to every broadcast. That is why it is not the default.
try:
    _mf = encoder_latency("h264_mf")
    check("Media Foundation really is the slow one this measured",
          _mf > _lat, "%d frames vs %d" % (_mf, _lat))
except Exception as _exc:
    # Reported rather than swallowed. Media Foundation not opening is itself
    # worth knowing: it shares hardware with the camera, and it declining
    # after the camera tests have run is exactly the sort of thing that would
    # leave a fallback encoder unavailable on a real machine mid show.
    print("  (Media Foundation would not open here: %s: %s)"
          % (type(_exc).__name__, str(_exc)[:70]))


def static_card_bitrate(name, kbps, seconds=4, fps=30, w=1280, h=720):
    """What a STILL picture really sends. This is the case that undershoots."""
    buf = io.BytesIO()
    container = av.open(buf, mode="w", format="flv")
    stream = container.add_stream(name, rate=fps)
    stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
    stream.bit_rate = kbps * 1000
    stream.options = streamout._video_options(name, fps, kbps)
    still = np.zeros((h, w, 3), dtype=np.uint8)
    still[:, :, 2] = 40
    still[300:420, :, :] = 200
    for i in range(fps * seconds):
        picture_frame = av.VideoFrame.from_ndarray(still, format="rgb24")
        picture_frame = picture_frame.reformat(format="yuv420p")
        picture_frame.pts = i
        for packet in stream.encode(picture_frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return len(buf.getvalue()) * 8 / seconds / 1000.0


# A still card compresses to almost nothing. Both platforms publish bitrate
# floors and Facebook's is 400 kbps even at 360p, so without true CBR a radio
# show sending a station card sat an order of magnitude underneath it.
for _want in (600, 2500):
    _got = static_card_bitrate(C.RTMP_VIDEO_ENCODER, _want)
    check("a still card really sends the %d kbps it was asked for" % _want,
          _got > _want * 0.85, "%.0f kbps (%.0f%%)" % (_got, _got / _want * 100))

check("which needs nal-hrd, not merely minrate and maxrate",
      "nal-hrd=cbr" in streamout._video_options("libx264", 30, 2500)
      .get("x264-params", ""),
      streamout._video_options("libx264", 30, 2500).get("x264-params"))
check("and no CBR options are forced when no bitrate is known",
      "x264-params" not in streamout._video_options("libx264", 30))


# ---------------------------------------------------------------------------
print("\nTelling somebody their settings are outside the platform's range")
# ---------------------------------------------------------------------------

_low = streamout.bitrate_advice("facebook", 1280, 720, 30, 600)
check("Facebook's published floor is quoted back when you are under it",
      "1500" in _low and "600" in _low, _low)
check("and it says what the consequence is", "ended" in _low, _low)
check("Facebook's ceiling is quoted too",
      "4000" in streamout.bitrate_advice("facebook", 1280, 720, 30, 5000))
check("a sensible Facebook setting says nothing",
      streamout.bitrate_advice("facebook", 1280, 720, 30, 2500) == "")
check("YouTube gets a gentler wording, having published no bounds",
      "should still go out"
      in streamout.bitrate_advice("youtube", 1280, 720, 30, 600))
check("and a sensible YouTube setting says nothing",
      streamout.bitrate_advice("youtube", 1280, 720, 30, 2500) == "")
check("Restream has no published range, so nothing is invented for it",
      streamout.bitrate_advice("restream", 1280, 720, 30, 100) == "")
check("Facebook's audio ceiling is checked as well",
      "256" in streamout.bitrate_advice("facebook", 1280, 720, 30, 2500, 320))
check("and the eight hour limit is written down",
      C.FACEBOOK_MAX_HOURS == 8)


# ---------------------------------------------------------------------------
print("\nA camera that dies mid show, which is the one that was invisible")
# ---------------------------------------------------------------------------

class _Dies(picture.PictureSource):
    kind = C.PICTURE_CAMERA

    def __init__(self):
        self.alive = True
        self.asks = 0

    def frame(self, width, height):
        self.asks += 1
        if not self.alive:
            return None
        return np.full((height, width, 3), 7, dtype=np.uint8)

    def describe(self):
        return "a camera"


_told = []
_dying = _Dies()
_chain = picture.FallbackSource(_dying, picture.CardSource(name="Backup"),
                                on_fallback=_told.append)
check("a live camera is what goes out",
      _chain.frame(320, 180)[0, 0, 0] == 7)
_dying.alive = False
check("a camera that dies falls back to the card",
      _chain.frame(320, 180)[0, 0, 0] != 7)
check("and the presenter is told, once", len(_told) == 1, _told)
_before = _dying.asks
for _ in range(20):
    _chain.frame(320, 180)
check("a dead camera is not asked thirty times a second",
      _dying.asks - _before <= 2, "%d asks in 20 frames" % (_dying.asks - _before))

# The first version could never recover: its recovery branch sat inside
# "if not fallen_back" where it was unreachable. One glitched frame meant the
# card for the rest of a three hour show.
_dying.alive = True
_chain._tried_at = 0.0
check("a camera that comes back is used again",
      _chain.frame(320, 180)[0, 0, 0] == 7)
check("and that is said too", "back" in _told[-1].lower(), _told)
check("and the chain no longer reports itself as fallen back",
      not _chain.fallen_back)

# A frozen frame is not a camera feed. _latest used to be set once and never
# cleared, so an unplugged camera handed back the same picture for hours.
_stale = camera.CameraSource("nothing at all", 320, 180, 30)
_stale._latest = np.zeros((180, 320, 3), dtype=np.uint8)
_stale._latest_at = time.monotonic()
check("a fresh frame is handed over", _stale.frame(320, 180) is not None)
_stale._latest_at = time.monotonic() - (C.CAMERA_STALE_SECONDS + 1)
check("a stale one is not, so the fallback can do its job",
      _stale.frame(320, 180) is None)
check("and it says what happened", "stopped sending" in _stale.error,
      _stale.error)
check("closing a camera forgets its last picture", True)
_stale.close()
check("and really clears it", _stale.latest() is None)
check("a staleness limit is set at all", C.CAMERA_STALE_SECONDS > 0)


# ---------------------------------------------------------------------------
print("\nA connection that wedges, which used to say ON AIR for ever")
# ---------------------------------------------------------------------------

# PyAV installs FFmpeg's interrupt callback on INPUT containers only, so the
# timeout passed to av.open does nothing on the way out: mux() can block until
# Windows gives up on the socket, which is minutes, or for ever on a zero
# window. Wi-Fi going away without a clean disconnect is exactly that. The
# pump cannot report on itself while it is stuck, so a watchdog does it.

class _Wedges(streamout.Destination):
    wants_video = False
    chunk_seconds = 0.05

    def __init__(self, *args, **kwargs):
        self.samplerate = RATE
        self.bytes_sent = 0
        self.fed = 0
        self.released = threading.Event()

    def connect(self):
        return self

    def feed(self, block):
        self.fed += 1
        if self.fed > 4:
            self.released.wait(120)

    def describe(self):
        return "a wedged destination"

    def close(self):
        self.released.set()


streamout.DESTINATIONS["zzwedge"] = lambda s, r, video_source=None: _Wedges()
try:
    _said = []
    _states = []
    _bus = AirBus(RATE)
    _wedged = Streamer(_bus, {"server": "zzwedge"}, on_trouble=_said.append,
                       on_state=lambda s, d: _states.append(s))
    _wedged.start()
    _deadline = time.time() + C.STREAM_STALL_SECONDS + 6
    _pushed = 0
    while time.time() < _deadline:
        _bus.write("main", tone(2048, start=_pushed))
        _pushed += 2048
        time.sleep(0.046)
    check("a wedged connection still reaches on air first",
          streamout.ON_AIR in _states, _states)
    check("and then the watchdog notices it has stopped going out",
          streamout.RECONNECTING in _states, _states)
    check("the presenter is told, in words that say what to expect",
          any("not getting through" in line for line in _said), _said)
    _wedged.stop()
finally:
    del streamout.DESTINATIONS["zzwedge"]

check("the stall limit is generous enough not to drop a working stream",
      C.STREAM_STALL_SECONDS >= 10, C.STREAM_STALL_SECONDS)

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
