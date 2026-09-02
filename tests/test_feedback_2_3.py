"""Regressions for the 2.3.0 feedback, all of it Brian Hartgen's.

    python tests/test_feedback_2_3.py

Two things, both of which would be easy to undo by accident:

  * **The bed fades are a setting now, and zero is a supported answer.** A
    music bed cued on its first beat cannot ease in. It used to be a constant
    in ``constants.py`` and there was no way to ask for anything else.
  * **A pad tells the truth the moment you change it.** Assigning a file,
    renaming, turning looping off - all of them left the button reading what
    it read before, until you tabbed away and back. The deferral that caused
    it is still there and still right, but only for the "playing" word.

Both halves matter: the fix must NOT go so far as to rewrite the accessible
name every time a sound starts under the user's fingers, which is the thing
the deferral exists to prevent and which CLAUDE.md forbids.
"""

import os
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# APPDATA is redirected BEFORE the app is imported, so nothing here can read or
# write the real saved board - a DropDeckFrame both loads it and autosaves it.
import tempfile as _tempfile
os.environ["APPDATA"] = _tempfile.mkdtemp(prefix="dropdeck-test-appdata-")

import wx

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.dialogs import SettingsDialog
from dropdeck.mixer import Mixer, MixerGroup
from dropdeck.ui import DropDeckFrame

RATE = 48000
CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


def tone(path, seconds, rate=RATE, freq=220.0, amp=0.5):
    n = int(seconds * rate)
    t = np.arange(n, dtype=np.float32) / rate
    wave = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.tile(wave[:, None], (1, 2)), rate)
    return path


def peak(block):
    return float(np.max(np.abs(block))) if len(block) else 0.0


app = wx.App(redirect=False)
tmp = tempfile.mkdtemp(prefix="dropdeck-feedback-23-")
bed_file = tone(os.path.join(tmp, "bed.wav"), 2.0)
sfx_file = tone(os.path.join(tmp, "sfx.wav"), 0.5, freq=880)

# ---------------------------------------------------------------------------
print("The bed fades are a setting")

board = Board()
check("a new board carries the shipped fades",
      (board.bed_fade_in, board.bed_fade_out) == (C.FADE_IN_BED, C.FADE_OUT_BED),
      (board.bed_fade_in, board.bed_fade_out))
# Tony's call, 2 September: out of the box a bed starts where the file starts.
# A soundboard bed is nearly always cued on its downbeat, so the ramp is the
# thing you ask for rather than the thing you have to turn off.
check("and out of the box that means no fade in at all",
      C.FADE_IN_BED == 0.0, C.FADE_IN_BED)
check("but stopping a bed still fades, which is a different mistake",
      C.FADE_OUT_BED > 0.0, C.FADE_OUT_BED)

# Zero is the whole point of the feature and is exactly the value a careless
# `or` in save or load would swallow, so it is what the round trip uses.
board.bed_fade_in = 0.0
board.bed_fade_out = 0.0
saved = board.save(os.path.join(tmp, "zero.json"))
back = Board.load(saved)
check("no fade in survives a save and a load", back.bed_fade_in == 0.0,
      back.bed_fade_in)
check("no fade out survives a save and a load", back.bed_fade_out == 0.0,
      back.bed_fade_out)

board.bed_fade_in = 1.25
board.bed_fade_out = 2.5
back = Board.load(board.save(os.path.join(tmp, "some.json")))
check("a chosen fade survives too",
      (back.bed_fade_in, back.bed_fade_out) == (1.25, 2.5),
      (back.bed_fade_in, back.bed_fade_out))

older = os.path.join(tmp, "older.json")
with open(older, "w", encoding="utf-8") as handle:
    handle.write('{"app": "TG Drop Deck", "slots": []}')
carried = Board.load(older)
check("a board written before this release gets the old behaviour",
      (carried.bed_fade_in, carried.bed_fade_out)
      == (C.FADE_IN_BED, C.FADE_OUT_BED),
      (carried.bed_fade_in, carried.bed_fade_out))

junk = os.path.join(tmp, "junk.json")
with open(junk, "w", encoding="utf-8") as handle:
    handle.write('{"app": "TG Drop Deck", "bed_fade_in": 900,'
                 ' "bed_fade_out": "soon", "slots": []}')
rescued = Board.load(junk)
check("an absurd fade is clamped rather than honoured",
      rescued.bed_fade_in == C.MAX_BED_FADE, rescued.bed_fade_in)
check("and nonsense falls back instead of stopping the board opening",
      rescued.bed_fade_out == C.FADE_OUT_BED, rescued.bed_fade_out)

# ---------------------------------------------------------------------------
print("What the mixer does with it")

mix = Mixer(open_stream=False, samplerate=RATE)
mix.bed_gain = 1.0
mix.sfx_gain = 1.0
mix.ducking = False

mix.bed_fade_in = 0.0
mix.play(40, bed_file, is_bed=True, loop=False, name="bed")
first = mix.render(C.BLOCKSIZE).copy()
check("with no fade in the bed is at full level on its first block",
      peak(first) > 0.45, f"peak {peak(first):.4f}")
mix.stop_all(fade_out=0.0)
mix.render(C.BLOCKSIZE)

mix.bed_fade_in = 0.5
mix.play(40, bed_file, is_bed=True, loop=False, name="bed")
ramped = mix.render(C.BLOCKSIZE).copy()
check("with a fade in it starts quiet, as it always did",
      peak(ramped) < peak(first) * 0.2,
      f"flat {peak(first):.4f} ramped {peak(ramped):.4f}")
mix.stop_all(fade_out=0.0)
mix.render(C.BLOCKSIZE)

# Sounds and drops have never faded in and this setting must not reach them.
mix.bed_fade_in = 2.0
mix.play(0, sfx_file, is_bed=False, name="sfx")
sfx_first = mix.render(C.BLOCKSIZE).copy()
check("a sound effect still starts flat out, whatever the bed fade says",
      peak(sfx_first) > 0.45, f"peak {peak(sfx_first):.4f}")
mix.stop_all(fade_out=0.0)

# An explicit fade still wins, which is what the panic stop and the tests rely on.
mix.bed_fade_in = 1.0
voice = mix.play(41, bed_file, is_bed=True, fade_in=0.0, name="override")
check("an explicit fade still overrides the setting",
      peak(mix.render(C.BLOCKSIZE)) > 0.45)
mix.stop_all(fade_out=0.0)
mix.close()

group = MixerGroup(bank_devices={C.BANK_BEDS: None}, open_stream=False)
group.bed_fade_in = 0.0
group.bed_fade_out = 0.0
check("the group hands the fades to every mixer it holds",
      all(m.bed_fade_in == 0.0 and m.bed_fade_out == 0.0 for m in group.mixers))
group.set_bank_devices({C.BANK_BEDS: None})
check("and keeps them when a bank is re-routed",
      group.bed_fade_in == 0.0 and group.bed_fade_out == 0.0,
      (group.bed_fade_in, group.bed_fade_out))
group.close()

# ---------------------------------------------------------------------------
print("The setting is reachable, and the frame honours it")

frame = DropDeckFrame()
frame.board.path = os.path.join(tmp, "live.json")

frame.board.bed_fade_in = 0.0
frame.board.bed_fade_out = 0.15
frame._adopt(frame.board)
check("loading a board pushes its fades into the mixer",
      (frame.mixer.bed_fade_in, frame.mixer.bed_fade_out) == (0.0, 0.15),
      (frame.mixer.bed_fade_in, frame.mixer.bed_fade_out))

settings = SettingsDialog(frame, frame.board, frame.mixer)
check("audio settings opens on the board's fades",
      (settings.bed_fade_in, settings.bed_fade_out) == (0.0, 0.15),
      (settings.bed_fade_in, settings.bed_fade_out))
check("the fade boxes are named for a screen reader",
      settings.fade_in_ctrl.GetName() == "Bed fade in, seconds"
      and settings.fade_out_ctrl.GetName() == "Bed fade out, seconds")
check("zero is inside the range the box allows",
      settings.fade_in_ctrl.GetMin() == 0.0, settings.fade_in_ctrl.GetMin())
settings.fade_in_ctrl.SetValue(0.75)
check("and the box reads back what was typed into it",
      settings.bed_fade_in == 0.75, settings.bed_fade_in)
settings.Destroy()

# ---------------------------------------------------------------------------
print("A pad tells the truth the moment you change it")

# A blank board, not the demo one the frame loads when there is nothing saved.
blank = Board()
blank.path = os.path.join(tmp, "blank.json")
frame._adopt(blank)

pad = frame.pages[C.BANK_BEDS].buttons[1]
slot = pad.slot
pad.SetFocus()
frame.Show()
app.Yield()
focused = pad.HasFocus()

before = pad.GetLabel()
check("an empty bed says so to start with", "Empty" in before, before)

slot.name = "Waxing Lyrical"
slot.filepath = bed_file
slot.duration = 90.0
frame._sync_button(slot)
after = pad.GetLabel()
check("assigning a file renames the pad at once, without tabbing away",
      "Waxing Lyrical" in after and "Empty" not in after,
      f"focused={focused} label={after!r}")
check("and the length is in there too", "1 min 30 sec" in after, after)

slot.loop = True
frame._sync_button(slot)
check("turning looping on shows on the pad at once",
      "loops" in pad.GetLabel(), pad.GetLabel())
slot.loop = False
frame._sync_button(slot)
check("and turning it off takes the word away again",
      "loops" not in pad.GetLabel(), pad.GetLabel())

slot.name = "Renamed"
frame._sync_button(slot)
check("a rename lands straight away", "Renamed" in pad.GetLabel(), pad.GetLabel())

check("the tooltip is not left behind either",
      "Renamed" in (pad.GetToolTipText() or ""), pad.GetToolTipText())

# The other half of the rule, and the one that is easy to break while fixing
# the first: a sound starting is not an edit, and must not restart the screen
# reader on the pad the user is standing on.
steady = pad.GetLabel()
pad.refresh(True)
check("but a sound starting does NOT rewrite the name under the user",
      pad.GetLabel() == steady, pad.GetLabel())
check("even though the pad knows it is playing", pad._playing)
pad.refresh(False)
check("and the deferred label is still the right one",
      pad.GetLabel() == steady, pad.GetLabel())

# Deferred once the pad is left, which is what _on_focus does.
pad.refresh(True)
frame.pages[C.BANK_BEDS].buttons[2].SetFocus()
app.Yield()
pad.refresh(True)
check("once focus leaves, the playing state is allowed onto the label",
      "playing" in pad.GetLabel(), pad.GetLabel())
pad.refresh(False)

# Loading a whole board replaces what every pad points at. Focus or no focus,
# a pad that now holds a different sound cannot go on naming the old one.
pad.SetFocus()
app.Yield()
fresh = Board()
fresh.slots[C.SLOTS_PER_BANK * (C.BANK_BEDS - 1) + 1].name = "From The Board"
fresh.slots[C.SLOTS_PER_BANK * (C.BANK_BEDS - 1) + 1].filepath = bed_file
frame._adopt(fresh)
check("opening a board relabels even the pad that has focus",
      "From The Board" in frame.pages[C.BANK_BEDS].buttons[1].GetLabel(),
      frame.pages[C.BANK_BEDS].buttons[1].GetLabel())

# ---------------------------------------------------------------------------
try:
    frame.stop_background_work()
except Exception:
    pass
try:
    frame.mixer.close()
except Exception:
    pass
frame.Destroy()

failed = [n for n, ok in CHECKS if not ok]
print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
