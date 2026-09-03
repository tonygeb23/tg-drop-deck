"""Regressions for the 2.4.0 feedback.

    python tests/test_feedback_2_4.py

Three things, from two people:

  * **David Goldfield, rename the banks.** A board you built yourself is not
    "Sound Effects" and "Dialog Drops", it is "Movie Clips" and "Sirens and
    Alarms". The name is the only thing that changes: bank three is still the
    looping bank and bank four still takes custom hotkeys, because those are
    what the keys do rather than what the tab says.
  * **Brian Hartgen, Play in the Find dialog should not throw you out.** With
    several matches you want to hear which is which before you commit.
  * **Brian Hartgen, a folder on one key.** Six jingles that all mean "down
    the chart"; you do not care which one plays, only that one does.
"""

import os
import shutil
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
from dropdeck.dialogs import SearchDialog, SettingsDialog, SlotPropertiesDialog
from dropdeck.slot import Slot
from dropdeck.ui import DropDeckFrame

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


def tone(path, seconds=0.25, rate=48000, freq=440.0):
    n = int(seconds * rate)
    t = np.arange(n, dtype=np.float32) / rate
    wave = (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.tile(wave[:, None], (1, 2)), rate)
    return path


app = wx.App(redirect=False)
tmp = tempfile.mkdtemp(prefix="dropdeck-feedback-24-")

# A modal message box with nobody to click it blocks for ever, and this file
# drives a code path that raises one on purpose: assigning an empty folder is
# refused, and the refusal is a message box. The test hung roughly one run in
# three, after every check had passed, which shows up only as an exit code.
#
# Standing in for it makes the run deterministic AND makes the check stronger:
# it can now assert that the user was actually told, rather than only that the
# folder was not assigned.
MESSAGES = []


def _no_modal(message, caption="", style=0, parent=None):
    MESSAGES.append((caption, message))
    return wx.OK if style & wx.OK else wx.YES


wx.MessageBox = _no_modal

# A folder of jingles, plus one file that is not audio and must be ignored.
jingles = os.path.join(tmp, "Chart Drops")
os.makedirs(jingles)
for i in range(4):
    tone(os.path.join(jingles, "down%d.wav" % i), freq=300 + 60 * i)
with open(os.path.join(jingles, "notes.txt"), "w", encoding="utf-8") as handle:
    handle.write("not a sound")
empty_dir = os.path.join(tmp, "Empty Folder")
os.makedirs(empty_dir)
single = os.path.join(tmp, "Just One")
os.makedirs(single)
tone(os.path.join(single, "only.wav"))
lone_file = tone(os.path.join(tmp, "sting.wav"))

# ---------------------------------------------------------------------------
print("David Goldfield: the banks can be renamed")

board = Board()
check("a bank starts with the name it shipped with",
      board.bank_name(1) == "Sound Effects", board.bank_name(1))
check("and is not marked as renamed", not board.is_bank_renamed(1))

board.rename_bank(1, "Movie Clips")
check("renaming a bank takes", board.bank_name(1) == "Movie Clips",
      board.bank_name(1))
check("and it is marked as renamed", board.is_bank_renamed(1))
# The slots share the mapping by reference, which is the whole point: one
# assignment and eighty labels follow without anything being rebuilt.
check("every slot in that bank hears about it at once",
      board[0].bank_title == "Movie Clips" and board[19].bank_title == "Movie Clips",
      board[0].bank_title)
check("a slot in another bank is untouched",
      board[20].bank_title == "Dialog Drops", board[20].bank_title)
check("the short form becomes the name, rather than a made-up contraction",
      board[0].bank_short == "Movie Clips", board[0].bank_short)
check("so the search list names the bank the user chose",
      "Movie Clips 1" in board[0].search_label(), board[0].search_label())

board.rename_bank(1, "")
check("an empty name puts the shipped one back",
      board.bank_name(1) == "Sound Effects" and not board.is_bank_renamed(1))
board.rename_bank(2, C.BANK_TITLES[2])
check("and so does typing that bank's own shipped name",
      not board.is_bank_renamed(2), board.bank_names)
# Another bank's shipped name is still a name somebody chose, so it stands.
board.rename_bank(2, C.BANK_TITLES[1])
check("but another bank's name is a choice, and is kept",
      board.bank_name(2) == C.BANK_TITLES[1], board.bank_name(2))
board.rename_bank(2, "")

board.rename_bank(3, "Under The Show")
board.rename_bank(4, "Sirens and Alarms")
back = Board.load(board.save(os.path.join(tmp, "named.json")))
check("bank names survive a save and a load",
      (back.bank_name(3), back.bank_name(4))
      == ("Under The Show", "Sirens and Alarms"),
      back.bank_names)
check("and the reloaded slots see them too",
      back[40].bank_title == "Under The Show", back[40].bank_title)
# Renaming is cosmetic. If it ever stops being cosmetic, this is the check
# that says so.
check("renaming bank three leaves it the looping bank",
      back[40].is_bed and C.LOOPING_BANK == 3)
check("renaming bank three does not move a single hotkey",
      back[40].hotkey_label == "Alt+Ctrl+1", back[40].hotkey_label)
check("renaming bank four leaves it the one with custom hotkeys",
      back[60].hotkey_label == "" and C.BANK_MISC == 4)

junk = os.path.join(tmp, "junkbanks.json")
with open(junk, "w", encoding="utf-8") as handle:
    handle.write('{"app": "TG Drop Deck", "bank_names":'
                 ' {"1": "Fine", "nine": "x", "7": "out of range", "2": 5,'
                 ' "3": "   "}, "slots": []}')
rescued = Board.load(junk)
check("a good name in a messy file still loads",
      rescued.bank_name(1) == "Fine", rescued.bank_name(1))
check("and the unusable ones are dropped rather than crashing the load",
      set(rescued.bank_names) == {1}, rescued.bank_names)

long_name = "x" * 200
capped = Board()
capped.rename_bank(1, long_name)
back = Board.load(capped.save(os.path.join(tmp, "long.json")))
check("an absurd name is capped on the way back in",
      len(back.bank_name(1)) == C.MAX_BANK_NAME, len(back.bank_name(1)))

# ---------------------------------------------------------------------------
print("Brian Hartgen: a folder on one key")

slot = Slot(index=0, filepath=jingles)
check("a slot pointing at a folder knows it", slot.is_folder)
count = slot.scan_folder(force=True)
check("scanning counts only the sounds", count == 4, count)
check("the text file was not counted",
      all(p.endswith(".wav") for p in slot.folder_files), slot.folder_files)
check("the label says folder and how many",
      "folder, 4 sounds" in slot.button_label(), slot.button_label())
check("and never claims a duration, because every press is a different one",
      "sec" not in slot.button_label(), slot.button_label())

picks = [slot.pick_file() for _ in range(40)]
check("every pick is a real file in the folder",
      all(p in slot.folder_files for p in picks))
check("all four come up over forty presses", len(set(picks)) == 4,
      len(set(picks)))
# The thing that makes a random stinger sound broken rather than random.
check("the same one never comes up twice running",
      all(a != b for a, b in zip(picks, picks[1:])))

one = Slot(index=1, filepath=single)
one.scan_folder(force=True)
check("a folder holding one sound says so in the singular",
      "folder, 1 sound" in one.button_label(), one.button_label())
check("and that one is what plays, every time",
      one.pick_file() == one.pick_file() != None)

none = Slot(index=2, filepath=empty_dir)
check("an empty folder counts zero", none.scan_folder(force=True) == 0)
check("and says so rather than looking assigned and working",
      "folder, empty" in none.button_label(), none.button_label())
check("an empty folder has nothing to play", none.pick_file() is None)

plain = Slot(index=3, filepath=lone_file)
check("an ordinary file is not a folder", not plain.is_folder)
check("and plays itself", plain.playable_path() == lone_file)

# A folder slot must survive the round trip as a folder slot, so that a board
# loaded from disk does not quietly become a one-shot pointing at a directory.
b = Board()
b[5].filepath = jingles
b[5].scan_folder(force=True)
back = Board.load(b.save(os.path.join(tmp, "folders.json")))
check("a folder slot is still a folder slot after a save and a load",
      back[5].is_folder and back[5].folder_count == 4, back[5].folder_count)
check("and the count is there before anything has rescanned",
      "4 sounds" in back[5].button_label(), back[5].button_label())
check("the board can list its folder slots", len(back.folder_slots) == 1)

# Relink has to keep a folder a folder. A file that happens to share the name
# would silently turn a random-pick slot into a one-shot.
moved = os.path.join(tmp, "moved")
os.makedirs(moved)
shutil.copytree(jingles, os.path.join(moved, "Chart Drops"))
tone(os.path.join(moved, "Chart Drops.wav"))     # the decoy
lost = Board()
lost[6].filepath = os.path.join(tmp, "gone", "Chart Drops")
lost[6].folder_count = 4
check("a folder that is not there reads as missing", lost[6].is_missing)
check("and says folder missing, not file missing",
      "folder missing" in lost[6].button_label(), lost[6].button_label())
repaired = lost.relink(moved)
check("relink finds a moved folder", len(repaired) == 1, len(repaired))
check("and repairs it with the folder, not the file of the same name",
      lost[6].is_folder and lost[6].folder_count == 4, lost[6].filepath)

# ---------------------------------------------------------------------------
print("The app end of all three")

frame = DropDeckFrame()
blank = Board()
blank.path = os.path.join(tmp, "live.json")
frame._adopt(blank)

frame.notebook.SetSelection(0)
app.Yield()
check("the frame knows which bank you are looking at",
      frame._current_bank() == 1, frame._current_bank())

# Found while writing this file, and older than any of it. The startup line
# asked a MixerGroup for a `stream` it has never had, so from 2.1.2 to 2.3.0 it
# raised inside its wx.CallLater and the app said nothing at all at startup -
# including "3 files missing" and "audio could not start". Nothing reported it
# because a timer swallows what its callback raises.
check("a mixer can say whether audio is actually running",
      hasattr(frame.mixer, "is_running")
      and isinstance(frame.mixer.is_running, bool), frame.mixer.is_running)
frame.speaker.last_message = ""
frame._startup_line()
check("and the startup line gets all the way out",
      C.APP_NAME in frame.speaker.last_message
      or C.APP_NAME in frame.status.GetStatusText(1),
      frame.speaker.last_message)
frame._announce_startup()
check("the wrapper around it cannot take the app down either",
      True)

frame._set_bank_name(1, "Movie Clips")
check("renaming puts the name on the tab, with the number kept",
      frame.notebook.GetPageText(0).startswith("1. Movie Clips"),
      frame.notebook.GetPageText(0))
check("the count on the tab survives the rename",
      frame.notebook.GetPageText(0).endswith("(0)"),
      frame.notebook.GetPageText(0))
check("and the confirmation says what happened",
      "Movie Clips" in frame.speaker.last_message, frame.speaker.last_message)

frame._set_bank_name(3, "Under The Show")
check("renaming the looping bank says it is still the looping bank",
      "looping" in frame.speaker.last_message.lower(), frame.speaker.last_message)
frame._set_bank_name(4, "My Keys")
check("and renaming bank four says it still takes your own hotkeys",
      "hotkey" in frame.speaker.last_message.lower(), frame.speaker.last_message)

frame._set_bank_name(1, "")
check("resetting puts the shipped name back on the tab",
      frame.notebook.GetPageText(0).startswith("1. Sound Effects"),
      frame.notebook.GetPageText(0))

# Audio settings labels each bank's output row. Those have to follow the names
# too, or the dialog names a bank that no longer exists on the tab strip.
frame._set_bank_name(2, "Sirens and Alarms")
settings = SettingsDialog(frame, frame.board, frame.mixer)
check("the per-bank output rows use the names the user chose",
      settings.bank_choices[2].GetName() == "Sirens and Alarms output",
      settings.bank_choices[2].GetName())
settings.Destroy()
frame._set_bank_name(2, "")

# Folder assignment, through the frame rather than the dialog.
target = frame.board[7]
frame._apply_folder(target, jingles)
check("assigning a folder takes", target.is_folder and target.folder_count == 4,
      target.folder_count)
check("the pad names it and says how many",
      "folder, 4 sounds" in frame._button_for(target).GetLabel(),
      frame._button_for(target).GetLabel())
check("and it is named after the folder",
      target.display_name == "Chart Drops", target.display_name)

before = frame.board[8].filepath
MESSAGES.clear()
frame._apply_folder(frame.board[8], empty_dir)
check("an empty folder is refused at assignment, not at showtime",
      frame.board[8].filepath == before, frame.board[8].filepath)
check("and the user is told why, rather than left with a dead key",
      MESSAGES and "no sounds in that folder" in MESSAGES[0][1],
      MESSAGES)
check("said out loud too, for anybody who has the app's speech turned down",
      "no sounds in it" in frame.speaker.last_message,
      frame.speaker.last_message)

properties = SlotPropertiesDialog(frame, target, {})
check("properties says it is a folder and how many are in it",
      "folder, 4 sounds" in properties._file_text(), properties._file_text())
properties.Destroy()

target.scan_folder(force=True)
frame.trigger(target.index)
app.Yield()
check("pressing a folder slot plays something",
      frame.mixer.is_playing(target.index) or frame.speaker.last_message,
      frame.speaker.last_message)
check("and says which one it picked",
      "Chart Drops" in frame.speaker.last_message
      and "down" in frame.speaker.last_message.lower(),
      frame.speaker.last_message)
frame.mixer.stop_all(fade_out=0.0)

target.filepath = empty_dir
target.scan_folder(force=True)
frame.trigger(target.index)
check("a folder emptied behind your back says so rather than doing nothing",
      "empty folder" in frame.speaker.last_message, frame.speaker.last_message)
frame._apply_folder(target, jingles)

# The Find dialog: Play must not close it.
frame.board[9].filepath = lone_file
frame.board[9].name = "Sting One"
frame.board[10].filepath = lone_file
frame.board[10].name = "Sting Two"
played = []
search = SearchDialog(frame, frame.board, (), on_play=lambda s: played.append(s))
search._refresh("sting")
check("the search finds both", search.results.GetCount() == 2,
      search.results.GetCount())
search.results.SetSelection(0)
search._on_play(None)
check("Play fires the sound", len(played) == 1, played)
check("and does NOT record a choice, because the dialog is still open",
      search.chosen is None, search.chosen)
check("nor ask the frame to close it", not search.play_now)
search.results.SetSelection(1)
search._on_play(None)
check("so you can work down the matches and try each one",
      len(played) == 2 and played[0] is not played[1], played)
check("focus stays in the results list", search.results.HasFocus()
      or wx.Window.FindFocus() is None)
search.results.SetSelection(0)
# EndModal asserts on a dialog that was never shown modally, and this one was
# built directly so the Play button could be driven. Stubbing it is the only
# way to reach the line that records the choice.
search.EndModal = lambda _code: None
search._accept()
check("Enter still records the choice and closes",
      search.chosen is not None and search.chosen.display_name == "Sting One",
      search.chosen)
check("and jumping does not also play it",
      len(played) == 2, len(played))
search.Destroy()

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
