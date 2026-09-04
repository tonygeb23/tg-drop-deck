"""Tony's two requests, 4 September 2026.

    python tests/test_feedback_2_7.py

**Preview while you browse.** "could I press alt P P to turn on preview mode,
so, when I arrow to a sound, it plays it once... just making it easier to be
exact with finding sounds."

**Fewer slots.** "adding the ability to remove slots entirely, so, if someone
only wants 10 slots, they can have only 10 instead of 20. making it less
cluster... under properties of each slot, remove slot."

The one rule the second must never break is that removing a slot does not
renumber the others. The digit map is years of muscle memory: take slot 5 away
and 6 has to stay on the 6 key.
"""

import os
import shutil
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-27-appdata-")

import wx

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.dialogs import SlotPropertiesDialog, SoundBrowserDialog
from dropdeck.mixer import Mixer
from dropdeck.ui import (ID_REMOVE_SLOT, ID_RESTORE_ALL_SLOTS,
                         ID_RESTORE_SLOT, DropDeckFrame)

RATE = 44100
CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


def tone(path, freq, seconds=1.0):
    n = int(seconds * RATE)
    t = np.arange(n, dtype=np.float32) / RATE
    wave = (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.tile(wave[:, None], (1, 2)), RATE)
    return path


def level_of(block, freq):
    n = len(block)
    if not n:
        return 0.0
    t = np.arange(n) / float(RATE)
    mono = block[:, 0].astype(np.float64)
    return 2.0 * np.hypot(mono @ np.cos(2 * np.pi * freq * t),
                          mono @ np.sin(2 * np.pi * freq * t)) / n


app = wx.App(redirect=False)
tmp = tempfile.mkdtemp(prefix="dropdeck-27-")
os.makedirs(os.path.join(tmp, "Stings"))
sounds = [tone(os.path.join(tmp, "s%d.wav" % i), 300 + 200 * i)
          for i in range(3)]
tone(os.path.join(tmp, "Stings", "inside.wav"), 1500)
with open(os.path.join(tmp, "notes.txt"), "w", encoding="utf-8") as handle:
    handle.write("not audio")

frame = DropDeckFrame()

# ---------------------------------------------------------------------------
print("Previewing a sound while you look for it")

browser = SoundBrowserDialog(frame, tmp, "Choose a sound", frame=frame)
rows = [browser.list.GetItemText(i, 0)
        for i in range(browser.list.GetItemCount())]
check("the folder lists its sounds", "s0.wav" in rows and "s2.wav" in rows, rows)
check("folders come first, and going up is a row you can arrow to",
      rows[0] == "Up one folder" and rows[1] == "Stings", rows[:2])
check("anything this app cannot play is left out",
      not any("notes" in name for name in rows), rows)
check("every row says what it is",
      browser.list.GetItemText(rows.index("s0.wav"), 1) == "WAV sound"
      and browser.list.GetItemText(1, 1) == "Folder")
check("the preview switch is named and carries Alt+P",
      browser.preview.GetName() == "Play each sound as I reach it"
      and "&P" in browser.preview.GetLabel(), browser.preview.GetLabel())
check("and it starts off, because it is off on a new board",
      browser.preview.GetValue() is False)

sting = rows.index("Stings")
browser.list.Select(sting)
browser.list.Focus(sting)
browser._activate()
check("Enter opens a folder",
      os.path.basename(browser.folder) == "Stings", browser.folder)
browser._on_up(None)
check("and coming back up lands on the folder you came out of",
      browser.list.GetItemText(browser.list.GetFocusedItem(), 0) == "Stings",
      browser.list.GetItemText(browser.list.GetFocusedItem(), 0))

where = [browser.list.GetItemText(i, 0)
         for i in range(browser.list.GetItemCount())].index("s1.wav")
browser.list.Select(where)
browser.list.Focus(where)
current = browser._current()
check("the cursor knows which file it is on",
      current is not None and os.path.basename(current[1]) == "s1.wav"
      and current[2] is False, current)
check("the pause before a preview leaves room for the screen reader to say "
      "the name first", C.PREVIEW_DELAY_MS >= 200, C.PREVIEW_DELAY_MS)
browser.Destroy()

# The preview itself, measured through the mixer rather than assumed.
box = Mixer(open_stream=False, samplerate=RATE)
box.ducking = True
box.bed_gain = 1.0
box.play(0, tone(os.path.join(tmp, "bed.wav"), 200, 3.0), is_bed=True, loop=True)
for _ in range(40):
    box.render(512)
before = level_of(box.render(4096), 200)
box.play_preview(sounds[2])                      # 700 Hz
for _ in range(20):
    box.render(512)
block = box.render(4096)
check("a preview is audible", level_of(block, 700) > 0.1, level_of(block, 700))
check("at the sound volume, so it sounds like the pad will",
      abs(box.bus_gain(C.BUS_PREVIEW) - box.sfx_gain) < 1e-9)
check("and it does NOT duck the beds, because you are choosing a sound "
      "rather than playing one out",
      level_of(block, 200) >= before * 0.95,
      (before, level_of(block, 200)))
box.play(1, tone(os.path.join(tmp, "drop.wav"), 900))
for _ in range(30):
    box.render(512)
check("while a real drop still ducks them",
      level_of(box.render(4096), 200) < before * 0.6)
box.stop_preview()
for _ in range(20):
    box.render(512)
check("stopping a preview leaves everything else alone", box.is_playing(0))
box.close()

frame.board.preview_sounds = True
saved = os.path.join(tmp, "board.json")
frame.board.save(saved)
check("the board remembers the setting, so it is on next time too",
      Board.load(saved).preview_sounds is True)
frame.board.preview_sounds = False

# ---------------------------------------------------------------------------
print("\nTaking slots off the board")

page = frame.pages[C.BANK_SFX]
check("a bank starts with twenty", len(frame.board.visible_slots(1)) == 20)
check("and shows twenty buttons",
      sum(1 for b in page.buttons if b.IsShown()) == 20)

slot = frame.board[4]                                    # SFX 5
check("removing one works", frame.remove_slot(slot))
check("it is off the board",
      slot.hidden and len(frame.board.visible_slots(1)) == 19)
check("its button is hidden rather than left blank",
      not frame._button_for(slot).IsShown())
check("and the app says how many are left",
      "19 slots left" in frame.speaker.last_message, frame.speaker.last_message)

# The rule everything else hangs on.
check("NOTHING is renumbered: 6 is still 6",
      [s.number for s in frame.board.visible_slots(1)][:8]
      == [1, 2, 3, 4, 6, 7, 8, 9],
      [s.number for s in frame.board.visible_slots(1)][:8])
frame.trigger(5)
check("so slot 6 still fires on its own key", frame.mixer.is_playing(5))
frame.mixer.stop_all(fade_out=0.0)

frame.note("nothing yet")
frame.trigger(4)
check("a removed slot's key does nothing at all", not frame.mixer.is_playing(4))
check("and says why, rather than looking like a broken key",
      "removed from the board" in frame.status.GetStatusText(1),
      frame.status.GetStatusText(1))

frame.board[4].name = "a unique findable name"
check("search does not offer a slot you cannot press",
      frame.board.search("unique findable") == [])

# Nothing is lost, which is why nothing asks whether you are sure.
check("the slot keeps its sound and its name while it is off the board",
      frame.board[4].name == "a unique findable name")
check("it comes back", frame._restore(slot) and not slot.hidden)
check("with everything it had", frame.board[4].name == "a unique findable name")
check("and its button is shown again", frame._button_for(slot).IsShown())
frame.board[4].name = None

# Ten instead of twenty, which is what Tony asked for.
for number in range(11, 21):
    frame.remove_slot(frame.board[number - 1])
check("a bank can be cut down to ten",
      len(frame.board.visible_slots(1)) == 10,
      len(frame.board.visible_slots(1)))
check("and the ten left are 1 to 10, on the keys they always were",
      [s.number for s in frame.board.visible_slots(1)] == list(range(1, 11)),
      [s.number for s in frame.board.visible_slots(1)])
check("put them all back in one go", frame.restore_all_slots(1) == 10)
check("and the bank is whole again", len(frame.board.visible_slots(1)) == 20)

# The last one cannot go: a bank with nothing in it has nothing to come back to.
for number in range(2, 21):
    frame.remove_slot(frame.board[number - 1])
check("the last slot in a bank will not go",
      frame.remove_slot(frame.board[0]) is False
      and len(frame.board.visible_slots(1)) == 1)
check("and it says why", "last slot" in frame.speaker.last_message,
      frame.speaker.last_message)
frame.restore_all_slots(1)

frame.board[2].hidden = True
frame.board.save(saved)
back = Board.load(saved)
check("a removed slot stays removed after a save",
      back[2].hidden and len(back.visible_slots(1)) == 19)
check("and a board written before this existed has all twenty",
      len(Board().visible_slots(1)) == 20)
frame.board[2].hidden = False
frame.pages[1].refresh_visibility()

# Where you can ask for it.
dialog = SlotPropertiesDialog(frame, frame.board[2])
labels = [c.GetLabel().replace("&", "")
          for c in dialog.GetChildren() if isinstance(c, wx.Button)]
check("properties offers it, which is where Tony asked for it",
      any("Remove this slot" in label for label in labels), labels)
check("and it does not do it itself, so Cancel still means cancel",
      dialog.remove_wanted is False)
dialog.Destroy()

bar = frame.GetMenuBar()
sounds_menu = bar.GetMenu(bar.FindMenu("Sounds"))
ids = {item.GetId() for item in sounds_menu.GetMenuItems()}
check("and so does the Sounds menu, all three of them",
      {ID_REMOVE_SLOT, ID_RESTORE_SLOT, ID_RESTORE_ALL_SLOTS} <= ids)

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
shutil.rmtree(tmp, ignore_errors=True)

failed = [n for n, ok in CHECKS if not ok]
print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
