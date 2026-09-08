"""3.5.1: everything Tony found by actually using 3.5.0.

Five reports, 8 September 2026, and four of them are the same shape: a thing
that LOOKED like it worked and did not say otherwise.

  1. "i should be able to check before going live." The shot check read
     `video_source`, which exists only once Ctrl+B has been pressed, so the
     answer to "how does my shot look" was "go on air and find out".
  2. Worse, and found while fixing 1: with `live_to` set to a radio station,
     `_stream_settings` returns the AUDIO dict, which has no `picture` key at
     all, so `picture.build` handed back a card. Not an error. A confident
     description of a picture nobody had chosen.
  3. "can you display an accessible progress bar." `download` had accepted a
     `progress` callback since the day it was written and never called it.
  4. "the program also does not reopen like it says it does once updated."
     It said so in as many words and could not: the installer's [Run] entry
     carries `skipifsilent` and the app installs with /SILENT.
  5. The AI page: a tab name, a model box that was a blank edit field, and a
     picture path somebody was expected to type from memory.

    python tests/test_3_5_1.py
"""

import inspect
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-351-test-")

import wx

from dropdeck import appupdate, constants as C, picture, ui, updatedialog
from dropdeck import vision
from dropdeck.dialogs import SettingsDialog

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


def head(title):
    print(os.linesep + title + os.linesep)


app = wx.App()
frame = ui.DropDeckFrame(None)

# ---------------------------------------------------------------------------
head("The shot can be checked BEFORE going live")

check("nothing is streaming", getattr(frame, "video_source", None) is None)
frame.board.picture = C.PICTURE_CARD
shot, note = frame.preview_picture()
check("and there is still a picture to look at", shot is not None)
check("it is the size the stream would send",
      shot.shape == (frame.board.video_height, frame.board.video_width, 3),
      None if shot is None else shot.shape)
check("and it says it is a preview rather than the live picture",
      note == "what would go out", note)

head("The picture settings are the PICTURE's, not the destination's")

frame.board.live_to = C.LIVE_TO_AUDIO
settings = frame._picture_settings()
check("a board pointed at the radio station still knows its picture",
      settings.get("picture") == C.PICTURE_CARD, settings.get("picture"))
check("and its artwork", "picture_file" in settings)
check("and its camera", "camera" in settings)
check("and its brand", settings.get("colour_text") == frame.board.colour_text)
# The bug in one line: the destination dict simply has no such key.
audio = frame._stream_settings()
check("where the audio destination dict has no picture at all, which is why "
      "asking it returned a card", audio.get("picture") is None,
      audio.get("picture"))

head("Choosing the screen really gets the screen, not a card standing in")

frame.board.picture = C.PICTURE_CARD
card, _ = frame.preview_picture()
frame.board.picture = C.PICTURE_SCREEN
grabbed, _ = frame.preview_picture()
if grabbed is None:
    check("the screen could not be captured here, so this is skipped", True,
          "skipped")
else:
    check("the screen frame is not simply the card",
          not np.array_equal(card, grabbed))
    colours_in = len(np.unique(grabbed.reshape(-1, 3), axis=0))
    check("and it has the detail of a real desktop", colours_in > 400,
          "%d distinct colours" % colours_in)
frame.board.picture = C.PICTURE_CARD

head("A camera preview waits for the camera, not for the card behind it")

check("a fallback source can be asked to wait",
      hasattr(picture.FallbackSource, "wait_ready"))
source = picture.build({"picture": C.PICTURE_CARD, "name": "Test"})
check("and waiting on something with no camera is safe, not a hang",
      getattr(source, "wait_ready", lambda _t: True)(0.1) in (True, False))
try:
    source.close()
except Exception:
    pass

head("What is on top of the picture is in the checked picture")

# The overlay is drawn by the DESTINATION, so a frame taken from the source
# has none of it. A shot check that offers to say whether the lower third
# covers your face cannot do it from a picture the lower third is not in.
check("the preview goes through the overlay",
      "_with_overlay" in inspect.getsource(ui.DropDeckFrame.preview_picture))
check("and the overlay is built from the picture settings too",
      "_picture_settings" in inspect.getsource(
          ui.DropDeckFrame._with_overlay))

head("The download says how it is going")

source = inspect.getsource(appupdate._fetch)
check("it reads in blocks rather than one call", "CHUNK" in source)
check("and calls the progress callback", "progress(" in source)
check("the block size is sane", 32768 <= appupdate.CHUNK <= 4194304,
      appupdate.CHUNK)
check("and download passes its callback down, which it never used to",
      "progress=progress" in inspect.getsource(appupdate.download))

seen = []


def fake_read(self=None):
    pass


class _Resp:
    """A response in two blocks, to prove the loop reports and stops."""

    headers = {"Content-Length": "8"}

    def __init__(self):
        self._left = [b"abcd", b"efgh"]

    def read(self, _n):
        return self._left.pop(0) if self._left else b""

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


import urllib.request as _ur          # noqa: E402
_real = _ur.urlopen
_ur.urlopen = lambda *_a, **_k: _Resp()
try:
    got = appupdate._fetch("https://example.invalid/x", limit=1000,
                           progress=lambda d, t: seen.append((d, t)))
    check("every block is reported", len(seen) == 2, seen)
    check("with the real total from the server", seen[0][1] == 8, seen[0])
    check("and the bytes are all there", got == b"abcdefgh", got)

    stopped = []

    def stopper(done, _total):
        stopped.append(done)
        raise appupdate.Stopped()

    _ur.urlopen = lambda *_a, **_k: _Resp()
    try:
        appupdate._fetch("https://example.invalid/x", limit=1000,
                         progress=stopper)
        check("Stop really stops the download", False, "it kept going")
    except appupdate.Stopped:
        check("Stop really stops the download", True)
    check("and it stopped on the FIRST block, not at the end",
          len(stopped) == 1, stopped)

    # And an ordinary broken progress bar must not lose a good download.
    _ur.urlopen = lambda *_a, **_k: _Resp()

    def broken(_d, _t):
        raise ValueError("the bar fell over")

    got = appupdate._fetch("https://example.invalid/x", limit=1000,
                           progress=broken)
    check("but a progress bar that raises anything else is ignored",
          got == b"abcdefgh", got)
finally:
    _ur.urlopen = _real

head("And the app really does reopen, which it said and did not do")

iss = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools", "dropdeck.iss"),
    encoding="utf-8").read()
check("the installer has a run entry that survives a silent install",
      "Check: WantsRestart" in iss)
check("and a WantsRestart to decide it", "function WantsRestart" in iss)
check("which reads the flag the app sends", "restartapp" in iss)
check("the app sends it",
      "/restartapp=1" in inspect.getsource(appupdate.run_installer))
check("the old entry is still there for somebody running it by hand",
      "skipifsilent" in iss)

head("The progress bar can be heard, not only seen")

box = updatedialog.DownloadProgressDialog(frame, frame, "version 9.9.9")
said = []
box._say = lambda text: said.append(text)
check("there is a real gauge", isinstance(box.bar, wx.Gauge))
check("and it is named for a screen reader",
      box.bar.GetName() == "Download progress", box.bar.GetName())
for done in (100000, 2000000, 4000000, 6000000, 9000000, 10000000):
    box._show(done, 10000000)
check("the percentage is spoken as it climbs", len(said) >= 4, said)
check("and not once per block, which would interrupt itself for ever",
      len(said) <= 10, len(said))
check("it counts up rather than jumping about",
      said == sorted(said, key=lambda t: int(t.split()[0])), said)
check("the words say what they mean", said and said[-1].endswith("percent"),
      said[-1] if said else "")
box._show(500000, 0)
check("a server that will not say the size does not lie about the percentage",
      "MB so far" in box.what.GetLabel(), box.what.GetLabel())
check("Stop is what has focus, being the only thing to do here",
      box.FindFocus() in (box.stop, None))
box.Destroy()

head("The AI page says what it is and can be used without sight")

prefs = SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic)
names = [prefs.tabs.GetPageText(i) for i in range(prefs.tabs.GetPageCount())]
check("the tab is called AI Provider", "AI Provider" in names, names[-2:])
check("and Shot check is gone", "Shot check" not in names)
check("the model is a combo box, not an empty edit field",
      isinstance(prefs.vision_model, wx.ComboBox),
      type(prefs.vision_model).__name__)
check("it starts with real names in it", prefs.vision_model.GetCount() > 0,
      prefs.vision_model.GetCount())
check("and can still be typed into, because a list goes stale",
      not (prefs.vision_model.GetWindowStyle() & wx.CB_READONLY))
check("there is a way to ask the service what it really has",
      hasattr(prefs, "vision_models_get"))
check("the picture has a browse button rather than a path to type",
      hasattr(prefs, "picture_browse"))
check("and it is only alive when a picture is what is being shown",
      not prefs.picture_browse.IsEnabled()
      if frame.board.picture != C.PICTURE_IMAGE else True)
check("every provider offers some models to start from",
      all(vision.KNOWN_MODELS.get(p) for p in vision.PROVIDERS))
check("and the default is among them",
      all(vision.DEFAULT_MODELS[p] in vision.KNOWN_MODELS[p]
          for p in vision.PROVIDERS))
prefs.Destroy()

head("Asking a service for its models")

ok, said = vision.list_models("nonsense", "k")
check("an unknown service is a sentence", not ok and "know" in said, said)
ok, said = vision.list_models("google", "")
check("and no key is too", not ok and "key" in said.lower(), said)
for name in vision.PROVIDERS:
    check("%s knows where to ask" % name, name in vision._MODEL_LISTS)

frame.stop_background_work()
frame.Destroy()

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
