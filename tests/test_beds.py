"""One music bed at a time.

Tony, 4 September 2026: "disable the ability to play multiple beds at the same
time in Drop Deck. Only 1 at a time."

Two beds running together is two pieces of music fighting, which is a mistake
rather than a texture, and on a live show it is the mistake you make by
leaning on the wrong key. Sound effects and drops still overlap, because a
laugh landing on top of a sting is the whole point of a soundboard.

Its own file rather than a block inside test_ui.py, because that one closes
its mixer partway through and anything after that has nothing to play with.

    python tests/test_beds.py
"""

import os
import sys
import tempfile

import numpy as np
import soundfile as sf
import wx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-beds-test-")

from dropdeck import constants as C
from dropdeck.ui import DropDeckFrame

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


def settle(ms=180):
    wx.MilliSleep(ms)
    wx.Yield()


app = wx.App(redirect=False)
frame = DropDeckFrame()
tmp = tempfile.mkdtemp()

BEDS = (C.BANK_BEDS - 1) * C.SLOTS_PER_BANK
for offset, hz in enumerate((220, 330, 440)):
    path = os.path.join(tmp, "bed%d.wav" % offset)
    seconds = np.arange(44100 * 8) / 44100.0
    sf.write(path, np.tile(
        (0.4 * np.sin(2 * np.pi * hz * seconds)).astype(np.float32)[:, None],
        (1, 2)), 44100)
    slot = frame.board[BEDS + offset]
    slot.filepath = path
    slot.name = "Bed %d" % (offset + 1)
    slot.hidden = False
    slot.loop = True


def beds_playing():
    return [i for i in frame.mixer.playing_slots()
            if 0 <= i < C.TOTAL_SLOTS and frame.board[i].is_bed]


def names():
    return [frame.board[i].name for i in beds_playing()]


print("\nOnly one bed at a time")

frame.trigger(BEDS)
settle()
check("a bed starts", len(beds_playing()) == 1, names())

frame.trigger(BEDS + 1)
settle()
check("starting a second one takes the first down rather than stacking",
      len(beds_playing()) == 1, names())
check("and it is the new one that is left playing", names() == ["Bed 2"],
      names())

frame.trigger(BEDS + 2)
settle()
check("a third replaces the second", names() == ["Bed 3"], names())

frame.trigger(BEDS + 2)
settle()
check("the same key still stops the bed that is playing",
      beds_playing() == [], names())

frame.trigger(BEDS)
settle()
frame.trigger(BEDS)
settle()
check("and starting and stopping the same one still works",
      beds_playing() == [], names())

print("\nEverything else still overlaps")

# Bank 1 is sound effects. A laugh landing on top of a sting is the point.
for index in (0, 1):
    frame.board[index].filepath = os.path.join(tmp, "bed%d.wav" % index)
    frame.board[index].name = "Effect %d" % (index + 1)
    frame.board[index].hidden = False
frame.trigger(0)
frame.trigger(1)
settle()
check("two sound effects play together, because they always did",
      len([i for i in frame.mixer.playing_slots() if i in (0, 1)]) == 2,
      list(frame.mixer.playing_slots()))

frame.trigger(BEDS)
settle()
check("and a bed does not stop them on its way in",
      len([i for i in frame.mixer.playing_slots() if i in (0, 1)]) == 2
      and len(beds_playing()) == 1,
      list(frame.mixer.playing_slots()))

frame.mixer.stop_all(fade_out=0.0)
settle(100)
check("stop everything still stops everything",
      frame.mixer.playing_slots() == [], frame.mixer.playing_slots())

frame.stop_background_work()
frame.Destroy()
app.Yield()

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
