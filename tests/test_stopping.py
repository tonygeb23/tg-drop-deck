"""Stopping a sound, and stopping the show.

    python tests/test_stopping.py

Chris Cooke, 5 September 2026, who had never used a soundboard before:

    "I'm wondering if it's possible to map the spacebar to stop something from
    playing. I have a rather long sound file that I may only wanna play a
    little bit of, but it takes an extra second or so to press the escape key
    four times to completely stop it."

    "I think an abrupt stop is better because if someone is running a mixer,
    they'll either fade it out themselves or more likely adjust it in their
    DAW."

Three answers, and the one that matters most is the one he did not ask for:
until now there was NO way to stop a single sound. Only beds toggled off, so
the panic key was his only option for a problem that was not a panic.

The thing to be careful about is what must NOT change. Effects and drops
piling up is the point of a soundboard, and a laugh landing on top of a sting
is a feature rather than an accident, so none of this may take that away by
default.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-stop-")

import wx

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.slot import Slot
from dropdeck.ui import ID_STOP_LATEST, DropDeckFrame

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name
          + (("  " + str(detail)) if detail != "" else ""))


app = wx.App(redirect=False)


def pump(ms=250):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.Yield()
        time.sleep(0.01)


frame = DropDeckFrame()
frame.Show()
app.Yield()

said = []
frame.announce = lambda text, **kw: said.append(text)
frame.announce_playback = lambda text, **kw: said.append(text)


print("Stopping the last sound, and only that one")

frame.trigger(0)
pump(200)
frame.trigger(1)
pump(200)
frame.trigger(2)
pump(200)
check("three sounds are playing at once, which is the point of a soundboard",
      frame.mixer.voice_count() == 3, frame.mixer.voice_count())

said.clear()
frame.stop_latest()
pump(200)
check("Ctrl+Space stops one of them", frame.mixer.voice_count() == 2,
      frame.mixer.voice_count())
check("and says which, because you cannot see it",
      said and said[-1].startswith("Stopped "), said[-1] if said else None)
newest = frame.board[2].display_name
check("the one it stopped is the one started last",
      said and newest in said[-1], (newest, said[-1] if said else None))

said.clear()
frame.stop_latest()
pump(200)
check("pressing it again unwinds the one before that",
      frame.mixer.voice_count() == 1
      and frame.board[1].display_name in said[-1],
      said[-1] if said else None)
frame.stop_latest()
pump(200)
check("and again leaves nothing", frame.mixer.voice_count() == 0,
      frame.mixer.voice_count())

said.clear()
frame.stop_latest()
check("with nothing playing it says so rather than doing nothing quietly",
      said and "Nothing is playing" in said[-1], said[-1] if said else None)

# It has to reach the key, not only the method.
entries = frame._build_accelerators()
space = [e for e in entries if e.GetKeyCode() == wx.WXK_SPACE
         and e.GetFlags() == wx.ACCEL_CTRL]
check("Ctrl+Space is really in the keyboard map", len(space) == 1, len(space))
check("and points at stopping the last sound",
      space and space[0].GetCommand() == ID_STOP_LATEST)


print()
print("A slot can be told to stop itself, and by default is not")

slot = frame.board[0]
check("a slot does not toggle to begin with", not slot.toggle_stop)

frame.trigger(0)
pump(200)
frame.trigger(0)
pump(200)
check("so pressing its key twice plays it twice, as it always has",
      frame.mixer.voice_count() == 2, frame.mixer.voice_count())
frame.stop_all()
pump(200)

slot.toggle_stop = True
said.clear()
frame.trigger(0)
pump(250)
check("with the toggle on it starts", frame.mixer.is_playing(0))
frame.trigger(0)
pump(250)
check("and the second press stops it", not frame.mixer.is_playing(0))
check("saying so", said and "Stopped" in said[-1], said[-1] if said else None)
slot.toggle_stop = False

# A bed has always worked this way and still must.
bed = next((s for s in frame.board.slots if s.is_bed and s.is_assigned), None)
if bed is not None:
    frame.trigger(bed.index)
    pump(300)
    playing = frame.mixer.is_playing(bed.index)
    frame.trigger(bed.index)
    pump(300)
    check("a bed still toggles without being asked to",
          playing and not frame.mixer.is_playing(bed.index))
frame.stop_all()
pump(200)

# And it survives the board file.
board = Board()
board[3].toggle_stop = True
written = os.path.join(tempfile.mkdtemp(), "board.json")
board.save(written)
back = Board.load(written)
check("the setting is remembered with the board", back[3].toggle_stop is True)
check("and the slots that were not set are not set",
      not back[4].toggle_stop)
check("a slot built from nothing does not toggle",
      Slot.from_dict(0, {}).toggle_stop is False)


print()
print("How many presses of Escape, and whether it fades")

check("two by default, not three", C.DEFAULT_STOP_PRESSES == 2,
      C.DEFAULT_STOP_PRESSES)
check("and one is allowed for anybody who wants it back",
      C.MIN_STOP_PRESSES == 1)

stopped = []
real_stop_all = frame.stop_all
frame.stop_all = lambda: stopped.append(1)

for wanted in (1, 2, 3, 4):
    frame.board.stop_presses = wanted
    stopped.clear()
    frame._escapes = 0
    frame._escape_at = 0.0
    for press in range(wanted - 1):
        frame._escape_pressed()
    check("at %d, the first %d press%s do not stop the show"
          % (wanted, wanted - 1, "" if wanted == 2 else "es"), not stopped)
    frame._escape_pressed()
    check("  and number %d does" % wanted, len(stopped) == 1, stopped)

frame.board.stop_presses = 2
stopped.clear()
frame._escapes = 0
frame._escape_at = 0.0
said.clear()
frame._escape_pressed()
check("it says how many are left, or a press looks like a dead key",
      said and "more time" in said[-1], said[-1] if said else None)
frame.stop_all = real_stop_all

# Fading or cutting.
frame.board.stop_fade = True
check("it fades by default", frame._stop_fade() is None)
frame.board.stop_fade = False
check("and cuts when asked to, which is what a mixer wants",
      frame._stop_fade() == 0.0)

# A cut really is instant, not a shorter fade.
frame.trigger(0)
pump(250)
check("a sound is playing", frame.mixer.voice_count() >= 1)
frame.stop_all()
pump(60)
check("stopping abruptly leaves nothing behind almost at once",
      frame.mixer.voice_count() == 0, frame.mixer.voice_count())

frame.board.stop_fade = True
frame.trigger(0)
pump(250)
frame.stop_all()
check("while a fade is still audible for a moment after",
      frame.mixer.voice_count() >= 1, frame.mixer.voice_count())
pump(500)
check("and gone shortly after that", frame.mixer.voice_count() == 0,
      frame.mixer.voice_count())

board = Board()
board.stop_presses = 4
board.stop_fade = False
board.save(written)
back = Board.load(written)
check("both settings survive the board file",
      back.stop_presses == 4 and back.stop_fade is False)
import json
data = json.load(open(written, encoding="utf-8"))
data["stop_presses"] = "lots"
json.dump(data, open(written, "w", encoding="utf-8"))
check("and nonsense in the file falls back rather than breaking it",
      Board.load(written).stop_presses == C.DEFAULT_STOP_PRESSES)

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
