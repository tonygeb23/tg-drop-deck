"""3.8.2: one key per destination, and two destinations with two names.

Tony, 12 September 2026, reading the summary Ctrl+B put in front of him:

    Going to: Blindside Radio, on YouTube Live

"it says my ice cast source + my youtube live. that's untrue. better
separation." And: "ctrl b for sending broadcast out to video, alt ctrl B to
send out to audio."

Blindside Radio is his Icecast station. It was being printed as the name of
his YouTube channel because one field, `stream_name`, was doing both
destinations' jobs. That is the trap `stream_host` and `video_host` were
separated for, one release earlier, for the same reason.

    python tests/test_3_8_2.py

The key is pressed for real by `tools/check_video_key.py radio`. Nothing in
here can replace that: this file proves the wiring, not the keystroke.
"""

import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-382-test-")

import wx

from dropdeck import constants as C
from dropdeck import preflight
from dropdeck import ui as uimod
from dropdeck.board import Board
from dropdeck.ui import (DropDeckFrame, ID_STREAM_TOGGLE,
                         ID_STREAM_TOGGLE_AUDIO)

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" else ""))


app = wx.App(False)
frame = DropDeckFrame(None)
board = frame.board
board.stream_name = "Blindside Radio"
board.stream_server, board.stream_host = "icecast", "blindsideradio.com"
board.stream_mount = "/live"
board.video_server, board.video_host = "youtube", C.RTMP_INGEST["youtube"]


# ---------------------------------------------------------------------------
print("\nThe untruth: one name cannot serve two destinations")
# ---------------------------------------------------------------------------
board.live_to = C.LIVE_TO_VIDEO
going = frame.preflight().lines[0][1]
check("the video destination does NOT borrow the radio station's name",
      "Blindside Radio" not in going, going)
check("it names the platform instead", "YouTube" in going, going)

board.video_name = "Tony Gebhard"
going = frame.preflight().lines[0][1]
check("and uses the channel's own name once there is one",
      "Tony Gebhard" in going and "YouTube" in going, going)
check("still never the radio station's", "Blindside Radio" not in going, going)

board.live_to = C.LIVE_TO_AUDIO
going = frame.preflight().lines[0][1]
check("the radio destination still says the radio station",
      "Blindside Radio" in going and "blindsideradio.com" in going, going)
check("and never the video channel's name", "Tony Gebhard" not in going, going)

# A platform with one fixed address does not recite it; a custom one does.
fixed = preflight.where_it_goes(
    {"server": "youtube", "host": C.RTMP_INGEST["youtube"]}, video=True)
check("YouTube's single address is not read out, because it is not yours",
      "rtmps" not in fixed, fixed)
custom = preflight.where_it_goes(
    {"server": "rtmp", "host": "rtmp://stream.example.com/app"}, video=True)
check("a custom server's address is, because it is the useful fact",
      "example.com" in custom, custom)

# The board keeps them apart on disk as well as in the sentence.
saved = Board()
saved.stream_name, saved.video_name = "Blindside Radio", "Tony Gebhard"
back = Board.from_dict(saved.to_dict()) if hasattr(Board, "from_dict") else None
if back is not None:
    check("both names survive a save and a load",
          back.stream_name == "Blindside Radio"
          and back.video_name == "Tony Gebhard",
          (back.stream_name, back.video_name))
else:
    check("both names are written to the board file",
          "video_name" in saved.to_dict() and "stream_name" in saved.to_dict(),
          sorted(k for k in saved.to_dict() if "name" in k))


# ---------------------------------------------------------------------------
print("\nOne key per destination")
# ---------------------------------------------------------------------------
bar = frame.GetMenuBar()
video_item = bar.FindItemById(ID_STREAM_TOGGLE)
radio_item = bar.FindItemById(ID_STREAM_TOGGLE_AUDIO)
check("there are two go live commands, not one",
      video_item is not None and radio_item is not None)
check("Ctrl+B is the video platform",
      video_item.GetAccel() and video_item.GetAccel().ToString() == "Ctrl+B",
      video_item.GetAccel().ToString() if video_item.GetAccel() else "none")
check("and the radio station has a key of its own",
      radio_item.GetAccel() and radio_item.GetAccel().ToString() == "Alt+Shift+B",
      radio_item.GetAccel().ToString() if radio_item.GetAccel() else "none")

# THE FAULT THAT HID THE OTHER ONE. ID_STREAM_TOGGLE_AUDIO was ID_HIGHEST+420,
# which is ID_SEND_SETUP, so the key opened the send window and toggle_stream
# never ran whatever chord was on it. tests/test_3_4_1.py catches this in one
# second and was not run between adding the id and pressing the key.
ids = {}
for name in dir(uimod):
    if not name.startswith("ID_") or name.endswith("_BASE"):
        continue
    value = getattr(uimod, name)
    if isinstance(value, int):
        ids.setdefault(value, []).append(name)
check("the two go live ids are different numbers",
      ID_STREAM_TOGGLE != ID_STREAM_TOGGLE_AUDIO)
check("and neither shares an id with anything else",
      len(ids.get(ID_STREAM_TOGGLE, [])) == 1
      and len(ids.get(ID_STREAM_TOGGLE_AUDIO, [])) == 1,
      (ids.get(ID_STREAM_TOGGLE), ids.get(ID_STREAM_TOGGLE_AUDIO)))

# Alt+Ctrl+B was what was asked for and it cannot work: Windows turns Ctrl+Alt
# into AltGr, so the chord is a character rather than a shortcut. Measured
# with real keystrokes once the id above was fixed: Ctrl+B arrives,
# Alt+Shift+B arrives, Alt+Ctrl+B fails three times out of three.
labels = []
for ident in (ID_STREAM_TOGGLE, ID_STREAM_TOGGLE_AUDIO):
    labels.append(bar.FindItemById(ident).GetItemLabel())
check("no go live key is built on Ctrl+Alt plus a letter",
      not any("Alt+Ctrl+" in one and "Shift" not in one for one in labels),
      labels)


# ---------------------------------------------------------------------------
print("\nThe key is the choice, and it is written down before anything reads it")
# ---------------------------------------------------------------------------
asked = []
frame._cleared_to_go = lambda *a, **kw: asked.append(frame.board.live_to) or False

board.live_to = C.LIVE_TO_AUDIO
frame.toggle_stream(to=C.LIVE_TO_VIDEO)
check("pressing the video key points the board at video before the pre-flight",
      asked and asked[-1] == C.LIVE_TO_VIDEO, asked)
check("and it stays there", board.live_to == C.LIVE_TO_VIDEO, board.live_to)

frame.toggle_stream(to=C.LIVE_TO_AUDIO)
check("pressing the radio key points it at the radio station",
      asked[-1] == C.LIVE_TO_AUDIO, asked)

source = inspect.getsource(uimod.DropDeckFrame.toggle_stream)
check("the wrong key while live names where you ARE rather than switching",
      "comes off air" in source and "stop_stream" in source)
check("and switching destinations is never done quietly under a live show",
      source.count("self.stop_stream()") == 1)


# ---------------------------------------------------------------------------
print("\nWhat it says")
# ---------------------------------------------------------------------------
check("each destination has words of its own",
      frame._destination_words(C.LIVE_TO_VIDEO)
      != frame._destination_words(C.LIVE_TO_AUDIO))
check("and a key of its own to name",
      frame._destination_key(C.LIVE_TO_VIDEO) == "Ctrl+B"
      and frame._destination_key(C.LIVE_TO_AUDIO) == "Alt+Shift+B",
      (frame._destination_key(C.LIVE_TO_VIDEO),
       frame._destination_key(C.LIVE_TO_AUDIO)))

help_text = C.KEYBOARD_HELP
check("F1 names both keys", "Ctrl+B" in help_text and "Alt+Shift+B" in help_text)
check("and does not still promise the one that cannot work",
      "Alt+Ctrl+B" not in help_text)

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
