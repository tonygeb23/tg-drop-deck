"""3.8.1: the picture belongs to the app, not to where Ctrl+B is pointed.

Tony, 12 September 2026: "when recording video, it should not send out a
still freeze frame of the radio show title, something seems off there... if
visual streaming is being done, it should default to what's being captured,
camera + screen, just camera, whatever is selected. none of this still frame
of a radio show. that is different. ice cast, shoucast, is not the same as
facebook and youtube."

He was right, and the audit that followed found twenty more. Every check
below is one of them, and every one of them was silent: the app said nothing
wrong because it said nothing at all.

    python tests/test_3_8_1.py

The end to end proof is `tools/check_record_picture.py`, which presses the
real key, records a real file and reads the PIXELS back, and
`tools/check_recording.py`, which measures sync off the decoded file. Nothing
in here can replace either: a check that calls a function directly proves the
function, not the program. Same lesson as `ID_STATION_BASE`, the crossfade
box and the COM apartment.
"""

import inspect
import os
import sys
import tempfile
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-381-test-")

import wx

from dropdeck import constants as C
from dropdeck import camera as cameras
from dropdeck import overlay, picture, picturefeed, preflight, streamout
from dropdeck import videorecord
from dropdeck import ui as uimod
from dropdeck.dialogs import VideoSourceDialog
from dropdeck.ui import DropDeckFrame

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" else ""))


app = wx.App(False)
frame = DropDeckFrame(None)
board = frame.board


# ---------------------------------------------------------------------------
print("\nThe fault Tony reported: a recording gets the picture, not a card")
# ---------------------------------------------------------------------------
# The capture threads live behind start(), and the record path never called
# it, so frame() answered None for ever and FallbackSource substituted the
# card. Measured against his own board: 175 frames in six seconds, mean pixel
# difference from a freshly drawn card ZERO.
src = inspect.getsource(uimod.DropDeckFrame._record_picture_run)
check("the record path does not build a source of its own",
      "picture.build" not in src, src[:0])
check("it pulls from the shared feed instead", "feed.frame(" in src)
check("and it waits for the capture before its first question",
      "wait_ready" in src)

feed_src = inspect.getsource(picturefeed.PictureFeed._open)
check("the feed STARTS what it builds, which is the whole fault",
      "source.start()" in feed_src)

# The overlay reached a recording through a method name that does not exist.
check("build_overlay is the name, and there is no _build_overlay",
      hasattr(frame, "build_overlay") and not hasattr(frame, "_build_overlay"))
check("the recording draws the overlay with draw_on, not draw",
      "draw_on" in src and "overlay_.draw(" not in src)

# _picture_settings supplies video_width, never width.
keys = set(frame._picture_settings())
check("the picture settings carry video_width, not width",
      "video_width" in keys and "width" not in keys, sorted(keys))
rec_src = inspect.getsource(uimod.DropDeckFrame.start_video_recording)
check("and the recorder asks for the keys that exist",
      'settings.get("video_width")' in rec_src
      and 'settings.get("width")' not in rec_src)


# ---------------------------------------------------------------------------
print("\nOne picture pipeline, reference counted")
# ---------------------------------------------------------------------------
built = []


def fake_settings():
    return {"picture": C.PICTURE_CARD, "name": "Test Station"}


made = picturefeed.PictureFeed(fake_settings)
check("nothing is open until somebody takes a hold", not made.running)
made.acquire(picturefeed.FOR_STREAM)
check("the first taker opens it", made.running)
first = made._source
made.acquire(picturefeed.FOR_RECORDING)
check("a second taker gets the SAME source, so one camera serves both",
      made._source is first)
check("and both are named", sorted(made.holders())
      == sorted([picturefeed.FOR_STREAM, picturefeed.FOR_RECORDING]))
made.release(picturefeed.FOR_RECORDING)
check("one letting go does not close it under the other", made.running)
made.release(picturefeed.FOR_STREAM)
check("the last one letting go closes it", not made.running)

# Holders are COUNTED. Two previews both call themselves "a preview", and a
# list of names de-duplicated them, so the first release closed the camera
# under the second.
made.acquire(picturefeed.FOR_PREVIEW)
made.acquire(picturefeed.FOR_PREVIEW)
made.release(picturefeed.FOR_PREVIEW)
check("two previews are two holds, not one", made.running)
made.release(picturefeed.FOR_PREVIEW)
check("and the second release closes it", not made.running)

# A hold taken while something else has it must not get a stale source.
wanted = {"picture": C.PICTURE_CARD, "name": "First"}
live = picturefeed.PictureFeed(lambda: dict(wanted))
live.acquire(picturefeed.FOR_PREVIEW)
was = live._source
wanted["name"] = "Second"
live.acquire(picturefeed.FOR_RECORDING)
check("a later hold rebuilds when the settings have moved on",
      live._source is not was)
live.close()
check("close lets go of everything at once", not live.running)

# frame() must not wait on the lock rebuild holds across a camera open.
frame_src = inspect.getsource(picturefeed.PictureFeed.frame)
check("frame takes no lock, because the audio thread calls it",
      "with self._lock" not in frame_src)

# A source already swapped out must not report on the live one.
noise = []
teller = picturefeed.PictureFeed(fake_settings, on_fallback=noise.append)
teller.acquire(picturefeed.FOR_STREAM)
teller._fell_back("the camera stopped", object())
check("a dying source cannot write a reason over the live one",
      teller.reason == "" and not noise, (teller.reason, noise))
teller._fell_back("the camera stopped", teller._source)
check("and the live one still can", teller.reason == "the camera stopped")
teller.close()


# ---------------------------------------------------------------------------
print("\nThe picture is not gated on where Ctrl+B is pointed")
# ---------------------------------------------------------------------------
for name in ("_on_video_sources", "_on_screen_text", "describe_screen"):
    text = inspect.getsource(getattr(uimod.DropDeckFrame, name))
    check("%s does not refuse a radio board" % name,
          "which sends no picture. Video streaming is in Preferences"
          not in text)

board.live_to = C.LIVE_TO_AUDIO
board.picture = C.PICTURE_SCREEN
answers = []
frame.announce_answer = lambda text: answers.append(text)
frame.describe_screen()
del frame.announce_answer
check("Ctrl+Shift+V does not answer 'Nothing' on a radio board",
      answers and not answers[-1].startswith("Nothing"), answers)

# A recording wants a picture whatever Ctrl+B is pointed at; a STREAM to a
# radio station still does not, because opening a camera for it would be a
# light on in the room for no reason.
check("a radio stream opens no picture",
      not picturefeed.wanted_for({"server": "icecast"}))
check("a video platform does", picturefeed.wanted_for({"server": "youtube"}))
build_src = inspect.getsource(uimod.DropDeckFrame._build_picture)
check("and the stream asks the question the feed documents",
      "picturefeed.wanted_for" in build_src)


# ---------------------------------------------------------------------------
print("\nWhat a blind presenter is told")
# ---------------------------------------------------------------------------
said = frame.what_is_in_the_recording()
check("a sound recording does not claim a picture", "Picture:" not in said,
      said)
board.picture = C.PICTURE_CARD
frame.video_recorder = type("R", (), {"running": True, "state": "recording",
                                      "fps": 30, "width": 1280,
                                      "height": 720})()
said = frame.what_is_in_the_recording(picture=True)
check("a picture recording names its picture", "Picture:" in said, said)
frame.video_recorder = None

# The fallback names WHO is showing the card.
fell = []
frame.picture_feed = picturefeed.PictureFeed(frame._picture_settings)
frame.picture_feed.acquire(picturefeed.FOR_RECORDING)
frame.announce = lambda text: fell.append(text)
frame._picture_failed("the camera stopped")
wx.Yield()
frame.announce = uimod.DropDeckFrame.announce.__get__(frame)
check("the card is blamed on the recording, not on a stream that is off",
      any("recording" in one.lower() for one in fell), fell)
frame.picture_feed.close()
frame.picture_feed = None

status = inspect.getsource(uimod.DropDeckFrame._update_status)
check("the status bar says a picture recording is running",
      "RECORDING PICTURE" in status)
check("and it asks recording_video, not recording",
      "self.recording_video()" in status)

# A preview is not a broadcast.
frame.picture_feed = picturefeed.PictureFeed(frame._picture_settings)
frame.picture_feed.acquire(picturefeed.FOR_PREVIEW)
check("a momentary preview does not make the app claim a picture is live",
      not frame._picture_live())
frame.picture_feed.acquire(picturefeed.FOR_RECORDING)
check("a recording does", frame._picture_live())
frame.picture_feed.close()
frame.picture_feed = None


# ---------------------------------------------------------------------------
print("\nThe overlay, which had never once been drawn on a card")
# ---------------------------------------------------------------------------
# CardSource handed back np.asarray(PIL image), which is READ ONLY, and
# draw_on wrote in place, so it raised ValueError into a swallowed except on
# every frame. Measured off a real stream: a lower third 1.33 grey levels
# from a bare card, which is absent.
card = picture.build({"picture": C.PICTURE_CARD, "name": "Blindside Radio"})
card.start()
plain = card.frame(640, 360)
check("a card hands back a WRITABLE array", plain.flags.writeable)

marks = overlay.Overlay({"name": "Blindside Radio",
                         "text_lower": C.TEXT_WORDS,
                         "text_lower_words": "PROOF"})
if overlay.available():
    out = marks.draw_on(plain)
    check("the overlay really draws on a card",
          int(np.abs(out.astype(int) - plain.astype(int)).max()) > 20,
          int(np.abs(out.astype(int) - plain.astype(int)).max()))
    check("and it leaves the source's own array alone",
          np.array_equal(card.frame(640, 360), plain))
    locked = card.frame(640, 360).copy()
    locked.setflags(write=False)
    check("it can draw on a read only frame at all",
          marks.draw_on(locked) is not None)
else:
    check("the overlay is available to test", None, "Pillow missing")


# ---------------------------------------------------------------------------
print("\nStarting up is not the same as broken")
# ---------------------------------------------------------------------------
class Opening:
    """A capture that has not produced its first frame yet."""
    kind = C.PICTURE_CAMERA
    error = ""
    frames_read = 0

    def start(self):
        return self

    def frame(self, w, h):
        return None


class Stopped:
    """One that HAS produced frames and has now stopped."""
    kind = C.PICTURE_CAMERA
    error = ""
    frames_read = 42

    def start(self):
        return self

    def frame(self, w, h):
        return None


backup = picture.CardSource(name="Test")
told = []
opening = picture.FallbackSource(Opening(), backup, told.append)
opening.frame(320, 180)
check("a source that is still opening is not called broken",
      not opening.fallen_back and opening.starting and not told, told)

stopped = picture.FallbackSource(Stopped(), backup, told.append)
stopped.frame(320, 180)
check("a source that has stopped is reported at once",
      stopped.fallen_back and told, told)

blind = picture.FallbackSource(
    type("Mute", (), {"kind": "", "frame": lambda s, w, h: None,
                      "start": lambda s: s})(), backup, [].append)
blind.frame(320, 180)
check("a source that cannot say whether it has started gets no grace",
      blind.fallen_back)

retry_src = inspect.getsource(picture.FallbackSource.frame)
check("the retry starts the source again, so a dead reader can come back",
      "self.primary.start()" in retry_src)
check("and the sources let their thread go when it dies",
      "self._thread = None"
      in inspect.getsource(cameras.CameraSource._run))


# ---------------------------------------------------------------------------
print("\nThe file: every frame, once, in order")
# ---------------------------------------------------------------------------
tap = videorecord.FrameTap()
a = np.zeros((4, 4, 3), dtype=np.uint8)
b = np.ones((4, 4, 3), dtype=np.uint8)
tap.put(a)
tap.put(b)
seq_a, got_a = tap.take()
seq_b, got_b = tap.take()
check("the tap hands over BOTH frames, oldest first",
      got_a is a and got_b is b and seq_b == seq_a + 1)
check("and an empty tap answers nothing rather than the last one",
      tap.take() == (0, None))
check("it holds more than one, which is what stops a quarter being lost",
      videorecord.FrameTap.DEPTH >= 2)
for _ in range(10):
    tap.put(a)
check("but it is bounded, so a slow encoder cannot play stale pictures late",
      len(tap._frames) == videorecord.FrameTap.DEPTH and tap.dropped == 8,
      (len(tap._frames), tap.dropped))

check("the stamp lead pays for the tap's depth, and the sign is negative",
      C.RECORD_TAP_LEAD_FRAMES == -(videorecord.FrameTap.DEPTH - 1),
      C.RECORD_TAP_LEAD_FRAMES)
check("the preset is one a moving picture can be encoded at in real time",
      C.RECORD_VIDEO_PRESET in ("ultrafast", "superfast", "veryfast",
                                "faster"),
      C.RECORD_VIDEO_PRESET)
opts = inspect.getsource(videorecord.VideoRecorder._video_options)
check("and B frames are left alone, because the decoded file preferred them",
      '"bf"' not in opts)
start_src = inspect.getsource(videorecord.VideoRecorder.start)
check("the ring is emptied before the timeline starts",
      "self.bus.reset()" in start_src)
check("a black file says so rather than reporting itself clean",
      "NO PICTURE" in inspect.getsource(videorecord.VideoRecorder.picture_report))


# ---------------------------------------------------------------------------
print("\nThe two recorders are separate files with separate faults")
# ---------------------------------------------------------------------------
failed_src = inspect.getsource(uimod.DropDeckFrame._record_failed)
check("a failure works out WHICH recorder died",
      "video_recorder" in failed_src and "videorecord.FAILED" in failed_src)
check("and does not drop the other one's bus blindly",
      failed_src.count("self.record_bus = None") == 1)
state_src = inspect.getsource(uimod.DropDeckFrame._on_record_state)
check("a warning that is not a failure is spoken rather than dropped",
      "wx.CallAfter(self.announce, detail)" in state_src)
check("the sound recorder can say when it lost audio",
      hasattr(__import__("dropdeck.recorder", fromlist=["Recorder"]).Recorder,
              "losing_audio"))


# ---------------------------------------------------------------------------
print("\nThe tap survives a reconnect, and a drop hands the picture back")
# ---------------------------------------------------------------------------
sync_src = inspect.getsource(uimod.DropDeckFrame._sync_record_picture)
check("a destination takes its tap at construction",
      "frame_tap" in inspect.signature(streamout.destination_for).parameters)
check("the streamer holds it, so a rebuild carries it across",
      "frame_tap=self.frame_tap" in inspect.getsource(streamout.Streamer._build))
check("and there is a way to set it that survives a reconnect",
      hasattr(streamout.Streamer, "set_frame_tap"))
# Stated as BEHAVIOUR, not as a word search. The first version of this
# grepped ui.py for `getattr(streamer, "destination"` and matched the
# docstrings that explain the fault, which is the same mistake
# test_shotcheck made about the word "remember": it measures the prose.
check("a Streamer has no public destination to attach a tap to",
      not hasattr(streamout.Streamer, "destination"))
check("so the tap goes through set_frame_tap, which survives a rebuild",
      "set_frame_tap" in sync_src and "frame_tap =" not in sync_src)
check("the stream only fills the tap while it is really ON AIR",
      "streamout.ON_AIR" in sync_src)
check("and a change of stream state re-decides who fills it",
      "_sync_record_picture()"
      in inspect.getsource(uimod.DropDeckFrame._say_stream_state))


# ---------------------------------------------------------------------------
print("\nThe pre-flight, and the things that cost nothing to say")
# ---------------------------------------------------------------------------
notes = preflight.picture_notes(
    {"picture": C.PICTURE_CAMERA, "camera": ""}, board,
    consumer=preflight.FOR_RECORDING)
check("a recording is warned about a camera it has not chosen",
      any("camera" in note.text for note in notes), [n.text for n in notes])
check("and the warning names the RECORDING, not the stream",
      all("the stream" not in note.text for note in notes),
      [n.text for n in notes])
notes = preflight.picture_notes(
    {"picture": C.PICTURE_CAMERA, "camera": ""}, board,
    consumer=preflight.FOR_STREAM)
check("the stream's own warning still says the stream",
      any("the stream" in note.text for note in notes),
      [n.text for n in notes])
check("and the record key runs them",
      "picture_notes"
      in inspect.getsource(uimod.DropDeckFrame._picture_warnings))

check("known_cameras really enumerates, which it never did",
      "from . import camera"
      in inspect.getsource(uimod.DropDeckFrame.known_cameras))

window = VideoSourceDialog(frame, board, live=False)
check("the picture window is called Picture, not Video source",
      window.GetTitle() == "Picture", window.GetTitle())
check("its column says what is USING the picture",
      window.list.GetColumn(1).GetText() == "Using")
check("the chosen source is always offered, even if it cannot work here",
      board.picture in window.kinds(), (board.picture, window.kinds()))
window.Destroy()

check("the camera corner moves without reopening the camera",
      hasattr(picturefeed.PictureFeed, "set_corner"))
check("and Ctrl+Shift+W answers about the picture",
      "picture_report" in inspect.getsource(uimod.DropDeckFrame.routing_report))

# The letterbox no longer resizes a picture that is already the right size.
same = np.random.randint(0, 255, (180, 320, 3), dtype=np.uint8)
canvas = np.empty((180, 320, 3), dtype=np.uint8)
began = time.perf_counter()
for _ in range(20):
    picture._letterbox(same, canvas)
cost = (time.perf_counter() - began) / 20.0 * 1000.0
check("the letterbox is nearly free when nothing needs scaling",
      cost < 2.0 and np.array_equal(canvas, same), "%.3f ms" % cost)

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
