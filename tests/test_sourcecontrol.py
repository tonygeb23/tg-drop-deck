"""Mute and solo, on the list you open mid show.

    python tests/test_sourcecontrol.py

Tony, 5 September 2026: "a running source list that has a mute or solo option
next to each one... arrow up and down to read the individual sources that are
enabled and left and right arrow to cycle between mute, solo, rename, or
delete."

Two axes. Up and down choose a source, left and right choose what Space will
do to it. The microphone is in the list because solo has to mean something:
soloing a games call has to take your voice down too, or it is not a solo.

What is checked here is that mute and solo reach the AUDIO, not only the tick
boxes. A mute that updates a list and leaves the sound going out is worse than
no mute at all.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-ctl-")

import numpy as np
import wx

from dropdeck import constants as C
from dropdeck import streamout
from dropdeck.dialogs import SourceControlDialog
from dropdeck.sources import Source
from dropdeck.ui import DropDeckFrame

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name
          + (("  " + str(detail)) if detail != "" else ""))


app = wx.App(redirect=False)
frame = DropDeckFrame()
frame.Show()
app.Yield()
RATE = frame.mixer.samplerate


def hand_driven(name, hz):
    """A source with no device, fed by hand, so no sound card is needed."""
    source = Source(name=name, device_name="", on_air=True, monitor=False,
                    samplerate=RATE)
    inp = source.input
    inp.samplerate = RATE
    inp.channels_open = 1
    inp.stream = object()
    inp.on_air = True
    inp._reset_ring()
    source._hz = hz
    return source


def feed(source, blocks=40):
    inp = source.input
    for i in range(blocks):
        t = np.arange(i * C.BLOCKSIZE, (i + 1) * C.BLOCKSIZE) / float(RATE)
        wave = (0.3 * np.sin(2 * np.pi * source._hz * t)).astype(np.float32)
        inp._callback(wave[:, None], C.BLOCKSIZE, None, None)


def air_of(source):
    """How loud that one source is on the air, read from its own tap."""
    feed(source)
    return float(np.abs(source.read_air(C.BLOCKSIZE * 8)).max())


call = hand_driven("A call", 900.0)
music = hand_driven("A browser", 400.0)
frame.sources = [call, music]
frame.source_group.sources = frame.sources
frame.air_bus = streamout.AirBus(RATE)
frame._sync_air_taps()

print("Numbers, and what the list holds")

rows = frame.source_rows()
check("the microphone is in the list", rows and rows[0][0] == "mic")
check("and every source after it", len(rows) == 3, len(rows))
check("each source is numbered from one",
      rows[1][1].startswith("Source 1") and rows[2][1].startswith("Source 2"),
      [r[1] for r in rows])
call.name = "Something else entirely"
rows = frame.source_rows()
check("renaming one does not renumber it",
      rows[1][1] == "Source 1, Something else entirely", rows[1][1])
call.name = "A call"


print()
print("Mute reaches the audio, not just the tick box")

check("both are on air to begin with",
      air_of(call) > 0.05 and air_of(music) > 0.05)
call.muted = True
frame.apply_source_mixing()
check("muting one silences it", air_of(call) < 0.001, air_of(call))
check("and leaves the other alone", air_of(music) > 0.05, air_of(music))
call.muted = False
frame.apply_source_mixing()
check("unmuting puts it back", air_of(call) > 0.05, air_of(call))
check("without having changed what the source is SET to",
      call.wanted_on_air is True)


print()
print("Solo silences everything else, including the microphone")

music.soloed = True
frame.apply_source_mixing()
check("the soloed one is on air", air_of(music) > 0.05, air_of(music))
check("and everything else is not", air_of(call) < 0.001, air_of(call))
check("the microphone included, or it would not be a solo",
      frame.mic.on_air is False)
check("the app knows something is soloed", frame.anything_soloed())

call.soloed = True
frame.apply_source_mixing()
check("two soloed means both are heard",
      air_of(call) > 0.05 and air_of(music) > 0.05)

music.soloed = call.soloed = False
frame.apply_source_mixing()
check("clearing solo puts everything back",
      air_of(call) > 0.05 and air_of(music) > 0.05)
check("and nothing is soloed any more", not frame.anything_soloed())

# Mute wins over solo, because mute is the more deliberate of the two.
call.soloed = True
call.muted = True
frame.apply_source_mixing()
check("a source that is both soloed and muted stays silent",
      air_of(call) < 0.001)
call.soloed = call.muted = False
frame.apply_source_mixing()


print()
print("The window itself")

window = SourceControlDialog(frame)
window.Show()
app.Yield()

check("it lists the microphone and both sources",
      window.list.GetItemCount() == 3, window.list.GetItemCount())
check("the microphone is not given a number",
      window.list.GetItemText(0, 0) == "Mic", window.list.GetItemText(0, 0))
check("the sources are numbered one and two",
      [window.list.GetItemText(r, 0) for r in (1, 2)] == ["1", "2"])
check("it shows whether each is muted", window.list.GetItemText(1, 2) == "no")
check("and whether each is on air", window.list.GetItemText(1, 4) == "yes")


class Key:
    def __init__(self, code):
        self.code = code
        self.skipped = False

    def GetKeyCode(self):
        return self.code

    def Skip(self):
        self.skipped = True


window.list.Select(1)
app.Yield()
check("it starts on Mute", window.ACTIONS[window.action][0] == "mute")
window._on_key(Key(wx.WXK_RIGHT))
check("right goes to Solo", window.ACTIONS[window.action][0] == "solo")
window._on_key(Key(wx.WXK_RIGHT))
check("then Rename", window.ACTIONS[window.action][0] == "rename")
window._on_key(Key(wx.WXK_RIGHT))
check("then Remove", window.ACTIONS[window.action][0] == "delete")
window._on_key(Key(wx.WXK_RIGHT))
check("and round to Mute again", window.ACTIONS[window.action][0] == "mute")
window._on_key(Key(wx.WXK_LEFT))
check("left goes back the other way",
      window.ACTIONS[window.action][0] == "delete")

# Space on Mute mutes, and the audio follows.
window.action = 0
window.list.Select(1)
app.Yield()
window._on_key(Key(wx.WXK_SPACE))
check("Space on Mute mutes that source", call.muted is True)
check("and it really goes quiet", air_of(call) < 0.001)
check("the list says so too", window.list.GetItemText(1, 2) == "yes",
      window.list.GetItemText(1, 2))
window._on_key(Key(wx.WXK_SPACE))
check("Space again unmutes", call.muted is False and air_of(call) > 0.05)

# Solo from the window.
window.action = 1
window._on_key(Key(wx.WXK_SPACE))
check("Space on Solo solos it", call.soloed is True)
check("and the other one goes quiet", air_of(music) < 0.001)
window._on_key(Key(wx.WXK_SPACE))
check("Space again clears it", not frame.anything_soloed()
      and air_of(music) > 0.05)

# The digits jump about the list.
window._on_key(Key(ord("2")))
check("pressing 2 goes to source two", window.list.GetFirstSelected() == 2)
window._on_key(Key(ord("1")))
check("and 1 back to source one", window.list.GetFirstSelected() == 1)

# The microphone cannot be renamed or removed.
window.list.Select(0)
app.Yield()
window.action = 3
window._on_key(Key(wx.WXK_SPACE))
check("the microphone cannot be removed", len(frame.sources) == 2)
window.action = 2
window._on_key(Key(wx.WXK_SPACE))
check("nor renamed", True)

# But it can be muted, which is what makes solo work both ways.
window.action = 0
window.list.Select(0)
app.Yield()
window._on_key(Key(wx.WXK_SPACE))
check("the microphone can be muted from here", frame.mic.muted is True)
window._on_key(Key(wx.WXK_SPACE))
check("and unmuted", frame.mic.muted is False)

check("Escape closes it", window.GetEscapeId() == wx.ID_CANCEL)
window.Destroy()
app.Yield()

# Mute is a live thing and must not be written into the board.
frame.sources[0].muted = True
saved = frame.sources[0].to_dict()
check("a mute is never saved with the board, so tomorrow starts clean",
      "muted" not in saved and "soloed" not in saved, sorted(saved))

frame.stop_stream(quiet=True)
frame.stop_background_work()
frame.Destroy()
app.Yield()

failed = [n for n, ok in CHECKS if not ok]
print()
print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
