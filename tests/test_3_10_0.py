"""3.10.0: a board that takes another's place never takes its file.

    python tests/test_3_10_0.py

Siena Trigiani and Rob Castrogiovanni, 15 November 2026:

    "We press CTRL+F12 to save as ... add in the sounds ... press CTRL+S to
    save the board. We create a new board with CTRL+N ... We then press
    CTRL+O and call up the previous sound board. What happens often for Rob,
    and has happened quite a few times for me as well, is that the sounds
    from said board have disappeared, leaving us with a blank board."

File, New board kept the old board's FILE, so the two second autosave wrote
eighty empty slots over the board they had just saved. Load demo pack did the
same with the demo, Import wrote over board.json, and Open dropped whatever
had been changed in the last two seconds. Mark reproduced all five before a
line of the fix was written, and what each check below asserts is his list:
the file that was open is byte for byte what it was, after the save timer AND
after closing.

Also here: a board that is all running order opens on the running order (Ali
Moosa, 16 October 2026), one swap key that arrives (Siena, 25 October 2026),
and a name of your own for an exported board (in-app feedback, 17 October).
"""

import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-3100-test-")

import numpy as np
import soundfile as sf
import wx

from dropdeck import board as boardmod
from dropdeck import constants as C
from dropdeck import ui as uimod
from dropdeck.board import Board
from dropdeck.playlist import Track

CHECKS = []
RATE = 48000


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" and not condition else ""))


def heading(text):
    print("\n" + text)


def tone_file(folder, name):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    sf.write(path, np.zeros((RATE // 10, 2), dtype=np.float32), RATE)
    return path


def digest(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as handle:
        return hashlib.sha1(handle.read()).hexdigest()


def sounds_in(path):
    with open(path, encoding="utf-8") as handle:
        return sum(1 for slot in json.load(handle)["slots"]
                   if slot.get("filepath"))


app = wx.App(False)
BOXES = []
ANSWER = {"box": wx.OK}


def fake_box(message, caption="", style=0, parent=None, *rest, **kw):
    BOXES.append((caption, message, style))
    return ANSWER["box"]


wx.MessageBox = fake_box

HOME = tempfile.mkdtemp(prefix="dropdeck-3100-boards-")
SOUNDS = [tone_file(os.path.join(HOME, "sounds"), "s%d.wav" % n)
          for n in range(6)]
SETTINGS = boardmod.config_dir()
DEFAULT = boardmod.default_board_path()


def said(frame):
    return frame.status.GetStatusText(0) + " " + frame.status.GetStatusText(1)


def spoken(frame):
    """Everything the frame announces from now on, in order."""
    heard = []
    real = frame.announce

    def listen(text, *a, **kw):
        heard.append(text)
        return real(text, *a, **kw)

    frame.announce = listen
    frame.announce_help = listen
    return heard


def named_board(frame, name, count=3):
    """Ctrl+F12 with a name, some sounds, Ctrl+S: the steps in the email."""
    path = os.path.join(HOME, name + ".json")
    frame._save(path=path)
    for n in range(count):
        frame.board.slots[n].filepath = SOUNDS[n]
    frame._touch()
    frame._save()
    return path


def empty_start():
    """A frame on an empty board of its own, so counts below are exact."""
    frame = uimod.DropDeckFrame(None)
    blank = Board()
    blank.claim_path(os.path.join(HOME, "scratch %d.json" % len(CHECKS)))
    frame._adopt(blank)
    return frame


def after_timer_and_close(frame):
    """Both things that write without being asked."""
    frame._autosave()
    frame._save_for_close()


# ===========================================================================
heading("File, New board: the steps from Siena and Rob's email")

frame = empty_start()
first = named_board(frame, "First show")
before = digest(first)
default_before = digest(DEFAULT)
remembered_before = boardmod.remembered_board_path()
check("the board saved with Ctrl+S holds its three sounds",
      sounds_in(first) == 3, sounds_in(first))
heard = spoken(frame)
BOXES.clear()
frame._on_new(None)
check("it asks before stopping every sound", len(BOXES) == 1, BOXES)
check("and the question says the board you had is safe, by name",
      BOXES and "First show is saved first" in BOXES[0][1]
      and "Clear all" not in BOXES[0][1], BOXES)
check("with OK and Cancel, so Escape answers it",
      BOXES and BOXES[0][2] & wx.CANCEL and BOXES[0][2] & wx.OK)
check("the new board is NOT in the old board's file",
      not boardmod.same_path(frame.board.path, first), frame.board.path)
check("it has a file of its own, in the settings folder",
      frame.board.path
      and os.path.dirname(frame.board.path) == SETTINGS
      and os.path.basename(frame.board.path) == "New board.json",
      frame.board.path)
check("which nothing has written yet", not os.path.exists(frame.board.path))
check("no save is waiting", not frame._save_timer.IsRunning())
check("what is spoken says the old board is untouched and how to name this",
      heard and "First show is saved and untouched" in heard[-1]
      and "Ctrl+F12" in heard[-1] and "New board" in heard[-1], heard)
check("and never says dot json", heard and ".json" not in heard[-1], heard)
check("what became of the old board is said before the empty slots",
      heard and heard[-1].index("untouched") < heard[-1].index("Eighty"),
      heard)
import time as _time
check("and it waits for the screen reader to finish with the window coming "
      "back, as speech after a menu does",
      frame._menu_closed_at is not None
      and _time.monotonic() - frame._menu_closed_at < 5)
after_timer_and_close(frame)
check("after the save timer and closing, First show is byte for byte the same",
      digest(first) == before)
check("board.json is untouched", digest(DEFAULT) == default_before)
check("an untouched new board leaves no file behind",
      not os.path.exists(frame.board.path))
check("and the board that opens next time is still the one last saved",
      boardmod.same_path(boardmod.remembered_board_path(), remembered_before),
      boardmod.remembered_board_path())

heading("Then the new board is used")
frame.board.slots[0].filepath = SOUNDS[4]
frame._touch()
frame._save(quiet=True)
new_home = frame.board.path
check("a change is saved to the new board's own file",
      os.path.exists(new_home) and sounds_in(new_home) == 1)
check("First show still has its three", digest(first) == before)
check("and the new board is the one that opens next time",
      boardmod.same_path(boardmod.remembered_board_path(), new_home))

heading("Ctrl+F12 gives it a name, and leaves no twin behind")
second = os.path.join(HOME, "Second show.json")


class FakeFileDialog:
    """Stands in for wx.FileDialog and answers with PICK."""
    PICK = None

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ShowModal(self):
        return wx.ID_OK

    def GetPath(self):
        return FakeFileDialog.PICK


real_file_dialog = wx.FileDialog
wx.FileDialog = FakeFileDialog
FakeFileDialog.PICK = second
frame._on_save_as(None)
check("the board is now Second show",
      boardmod.same_path(frame.board.path, second) and sounds_in(second) == 1)
check("the file it was kept in until it had a name is gone",
      not os.path.exists(new_home))
check("First show is still untouched", digest(first) == before)

heading("A file at that path that is NOT ours is never removed")
frame._on_new(None)
frame.board.slots[0].filepath = SOUNDS[5]
frame._touch()
frame._save(quiet=True)
home = frame.board.path
with open(home, "w", encoding="utf-8") as handle:
    handle.write('{"slots": [], "somebody": "else"}')
third = os.path.join(HOME, "Third show.json")
FakeFileDialog.PICK = third
frame._on_save_as(None)
check("a file changed by somebody else since we wrote it is left alone",
      os.path.exists(home) and "somebody" in open(home).read())
os.remove(home)

heading("Ctrl+N twice, and Ctrl+N then straight out")
frame._open_board(first)
frame._on_new(None)
frame._on_new(None)
check("twice running is still one new board and no file",
      os.path.basename(frame.board.path) == "New board.json"
      and not os.path.exists(frame.board.path), frame.board.path)
frame._save_for_close()
check("closing inside two seconds writes nothing over First show",
      digest(first) == before)
frame.Destroy()

# ===========================================================================
heading("Cancel means nothing happened at all")
frame = empty_start()
kept = named_board(frame, "Kept")
ANSWER["box"] = wx.CANCEL
frame._on_new(None)
check("the board is still the one that was open",
      boardmod.same_path(frame.board.path, kept)
      and frame.board.assigned_count == 3)
ANSWER["box"] = wx.OK
frame.Destroy()

# ===========================================================================
heading("A board that is all running order is not an empty board")
frame = empty_start()
only_tracks = os.path.join(HOME, "Only tracks.json")
frame._save(path=only_tracks)
frame.board.playlist.tracks.append(Track(filepath=SOUNDS[0]))
frame._touch()
BOXES.clear()
heard = spoken(frame)
frame._on_new(None)
check("File, New asks about it too", len(BOXES) == 1, BOXES)
check("and says it is saved and untouched",
      heard and "Only tracks is saved and untouched" in heard[-1], heard)
with open(only_tracks, encoding="utf-8") as handle:
    check("and its track was written before it was put away",
          len(json.load(handle)["playlist"]["tracks"]) == 1)
frame.Destroy()

# ===========================================================================
heading("A change made in the last two seconds survives File, New")
frame = empty_start()
show = named_board(frame, "Late edit")
frame.board.slots[3].filepath = SOUNDS[3]
frame._touch()                       # the timer has NOT fired
frame._on_new(None)
check("the fourth sound was written before the board was put away",
      sounds_in(show) == 4, sounds_in(show))
after_timer_and_close(frame)
check("and is still there after the timer and the close",
      sounds_in(show) == 4)
frame.Destroy()

# ===========================================================================
heading("File, Open board keeps what was changed in the board being left")
frame = empty_start()
left = named_board(frame, "Left behind")
other = os.path.join(HOME, "Other.json")
b = Board()
b.slots[0].filepath = SOUNDS[0]
b.save(other)
other_before = digest(other)
frame.board.slots[3].filepath = SOUNDS[3]
frame._touch()
frame._open_board(other)
check("the board being left holds its last change",
      sounds_in(left) == 4, sounds_in(left))
check("no save is waiting to land on the board that arrived",
      not frame._save_timer.IsRunning())
left_before = digest(left)
after_timer_and_close(frame)
check("neither file is changed by the timer or the close",
      digest(left) == left_before and sounds_in(other) == 1)
frame.Destroy()

# ===========================================================================
heading("Load demo pack never lands in the board you had")
frame = empty_start()
mine = named_board(frame, "Mine")
mine_before = digest(mine)
default_before = digest(DEFAULT)
BOXES.clear()
frame._on_load_demo(None)
loaded_demo = os.path.exists(boardmod.demo_board_path())
check("the demo pack is there to load", loaded_demo)
check("the question says the board you had is safe",
      BOXES and "Mine is saved first" in BOXES[0][1], BOXES)
check("the demo is in a file of its own",
      os.path.basename(frame.board.path) == "Demo board.json",
      frame.board.path)
after_timer_and_close(frame)
check("Mine is byte for byte the same after the timer and the close",
      digest(mine) == mine_before)
check("board.json too", digest(DEFAULT) == default_before)
check("and a demo nobody changed leaves no file",
      not os.path.exists(frame.board.path))
frame.Destroy()

# ===========================================================================
heading("Import has a file of its own, not board.json")
with open(DEFAULT, "w", encoding="utf-8") as handle:
    json.dump(Board().to_dict(), handle)
default_before = digest(DEFAULT)
frame = empty_start()
mine = named_board(frame, "Before import")
mine_before = digest(mine)
bank = os.path.join(HOME, "Old bank.json")
b = Board()
b.slots[0].filepath = SOUNDS[0]
b.save(bank)
bank_before = digest(bank)
check("the import went in", frame._import_board(bank) is True)
check("the imported board is named after the bank, in the settings folder",
      os.path.basename(frame.board.path) == "Old bank.json"
      and os.path.dirname(frame.board.path) == SETTINGS, frame.board.path)
check("its path is never None, which used to mean board.json",
      bool(frame.board.path))
after_timer_and_close(frame)
check("board.json is untouched", digest(DEFAULT) == default_before)
check("the bank that was imported FROM is untouched",
      digest(bank) == bank_before)
check("the board that was open is untouched", digest(mine) == mine_before)
check("and the import itself was kept",
      os.path.exists(frame.board.path) and sounds_in(frame.board.path) == 1)
frame.Destroy()

# ===========================================================================
heading("A board pinned earlier in the session does not outrank a new one")
frame = empty_start()
named_board(frame, "Pinned case")
frame._pinned_board = os.path.join(HOME, "Gone away.json")
frame._on_new(None)
check("the pin is dropped", frame._pinned_board is None)
frame.board.slots[0].filepath = SOUNDS[0]
frame._touch()
frame._save(quiet=True)
check("so the new board is what opens next time",
      boardmod.same_path(boardmod.remembered_board_path(), frame.board.path),
      boardmod.remembered_board_path())
os.remove(frame.board.path)
frame.Destroy()

# ===========================================================================
heading("A board that cannot be saved: the choice is yours, and No is safe")
frame = empty_start()
stuck = named_board(frame, "Stuck")
frame.board.slots[3].filepath = SOUNDS[3]
frame._touch()
real_save = Board.save


def refusing(self, path=None):
    raise OSError("The media is write protected")


Board.save = refusing
BOXES.clear()
ANSWER["box"] = wx.NO
went = frame._put_away()
check("it does not go on", went is False)
check("it says the board by name and what would be lost",
      any("Stuck could not be saved" in box[1] for box in BOXES), BOXES)
check("and No is the default button",
      any(box[2] & wx.NO_DEFAULT for box in BOXES if "Stuck" in box[1]))
check("the board is still open and still holds the change",
      boardmod.same_path(frame.board.path, stuck)
      and frame.board.assigned_count == 4)
ANSWER["box"] = wx.YES
check("Yes goes on, because being locked out for good is worse",
      frame._put_away() is True)
Board.save = real_save
ANSWER["box"] = wx.OK
frame.board.dirty = False
frame.Destroy()

# ===========================================================================
heading("A clean board whose file changed outside is not a failed save")
frame = empty_start()
clean = named_board(frame, "Clean")
with open(clean, "a", encoding="utf-8") as handle:
    handle.write("\n")
BOXES.clear()
check("it goes on without asking anything",
      frame._put_away() is True and not BOXES, BOXES)
frame.Destroy()

# ===========================================================================
heading("The first run demo is not promised a save it does not get")
frame = uimod.DropDeckFrame(None)
# The demo as a first run has it: loaded from the pack, pointed at a board
# file that is not there, and not changed.
demo = Board.load(boardmod.demo_board_path())
demo.claim_path(os.path.join(HOME, "never written.json"))
frame._adopt(demo)
words = frame._kept_words()
check("the question says the demo pack comes back, not that it is saved",
      "Load demo pack" in words and "saved" not in words, words)
heard = spoken(frame)
frame._on_new(None)
check("and nothing afterwards claims it was saved",
      heard and "saved" not in heard[-1], heard)
frame._open_board(os.path.join(HOME, "First show.json"))
frame.board._disk = None         # what a load leaves when the stat fails
words = frame._kept_words()
check("a board that was READ from a file is never called the demo pack",
      "First show is saved first" in words, words)
frame.Destroy()

# ===========================================================================
heading("A board that is all running order opens on the running order")

frame = empty_start()
tracks_only = os.path.join(HOME, "Ali show.json")
b = Board()
for n in range(3):
    b.playlist.tracks.append(Track(filepath=SOUNDS[n]))
b.save(tracks_only)
pads_only = os.path.join(HOME, "Pads.json")
b = Board()
b.slots[0].filepath = SOUNDS[0]
b.slots[1].filepath = SOUNDS[1]
b.save(pads_only)
both = os.path.join(HOME, "Both.json")
b = Board()
b.slots[0].filepath = SOUNDS[0]
b.playlist.tracks.append(Track(filepath=SOUNDS[1]))
b.save(both)

heard = spoken(frame)
frame._open_board(tracks_only)
check("it opens on the playlist view",
      frame.views.GetSelection() == uimod.VIEW_PLAYLIST)
check("and says so in ONE sentence, tracks counted",
      heard[-1] == "Loaded Ali show, 3 playlist tracks, now in the playlist",
      heard[-1])
check("nothing else was announced on top of it",
      sum(1 for line in heard if "Ali show" in line or "Playlist." in line) == 1,
      heard)
frame.show_view(uimod.VIEW_BOARD)
frame._open_board(both)
check("a board with pads AND tracks stays where you are",
      frame.views.GetSelection() == uimod.VIEW_BOARD)
check("and counts both", heard[-1] == "Loaded Both, 1 sound, 1 playlist track",
      heard[-1])
frame._open_board(pads_only)
check("pads alone reads as it always did", heard[-1] == "Loaded Pads, 2 sounds",
      heard[-1])

heading("A file changing on disk never moves you to another view")
frame._open_board(pads_only)
frame.show_view(uimod.VIEW_BOARD)
fresh = Board.load(tracks_only)
frame._load_into(tracks_only, board=fresh)
check("the reload path loads it but leaves the view alone",
      frame.views.GetSelection() == uimod.VIEW_BOARD)
frame.board.dirty = False
frame.Destroy()

heading("And it starts there too")
boardmod.remember_board_path(tracks_only)
frame = uimod.DropDeckFrame(None)
# Not called by hand: the window has to arrange it itself.
for _ in range(5):
    app.ProcessPendingEvents()
    wx.SafeYield()
check("the remembered board that is all playlist starts on the playlist",
      boardmod.same_path(frame.board.path, tracks_only)
      and frame.views.GetSelection() == uimod.VIEW_PLAYLIST)
heard = spoken(frame)
frame._startup_line()
check("and the startup line counts its tracks",
      heard and "3 playlist tracks" in heard[-1], heard)
frame.Destroy()

# ===========================================================================
heading("One swap key that arrives")
frame = empty_start()
entries = frame._build_accelerators()
found = {(e.GetFlags(), e.GetKeyCode()): e.GetCommand() for e in entries}
check("Alt+Shift+W is in the table the window really installs",
      found.get((wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("W")))
      == uimod.ID_VIEW_NEXT)
check("and exactly once",
      sum(1 for e in entries if (e.GetFlags(), e.GetKeyCode())
          == (wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("W"))) == 1)
labels = []


def walk(menu):
    for item in menu.GetMenuItems():
        labels.append(item.GetItemLabel())
        if item.GetSubMenu():
            walk(item.GetSubMenu())


for at in range(frame.GetMenuBar().GetMenuCount()):
    walk(frame.GetMenuBar().GetMenu(at))
swap = [label for label in labels if "wap between" in label]
check("the menu names Alt+Shift+W for the swap",
      swap and swap[0].endswith("\tAlt+Shift+W"), swap)
check("no menu advertises Ctrl+Alt+Tab, which Windows keeps",
      not any("Ctrl+Alt+Tab" in label for label in labels))
check("Alt+Shift+W is on the menu once only",
      sum(1 for label in labels if label.endswith("\tAlt+Shift+W")) == 1)
check("the two keys people already know are still on it",
      any(label.endswith("\tCtrl+Shift+S") for label in labels)
      and any(label.endswith("\tCtrl+Shift+P") for label in labels))
check("F1 help names it", "Alt+Shift+W" in C.KEYBOARD_HELP)
frame.show_view(uimod.VIEW_BOARD)
frame.show_view(None)
there = frame.views.GetSelection()
frame.show_view(None)
check("the command behind it goes there and back",
      there == uimod.VIEW_PLAYLIST
      and frame.views.GetSelection() == uimod.VIEW_BOARD)

# ===========================================================================
heading("An exported board is called what you call it")
check("what Windows refuses in a name is taken out",
      uimod._file_words('  My: Show?  ') == "My Show",
      uimod._file_words('  My: Show?  '))
check("a name typed with .json means the name",
      uimod._file_words("Friday.json") == "Friday")
check("slashes cannot make a path of it",
      "\\" not in uimod._file_words("..\\..\\up") and "/" not in
      uimod._file_words("a/b"), uimod._file_words("..\\..\\up"))
check("nothing but dots and spaces is no name at all",
      uimod._file_words(" .. ") == "")


class FakeText:
    VALUE = ""
    SEEN = []

    def __init__(self, parent, message, caption="", value="", *a, **kw):
        FakeText.SEEN.append((message, caption, value))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ShowModal(self):
        return wx.ID_OK

    def GetValue(self):
        return FakeText.VALUE

    def GetChildren(self):
        return []


class FakeDir(FakeFileDialog):
    pass


out = tempfile.mkdtemp(prefix="dropdeck-3100-export-")
real_text, real_dir = wx.TextEntryDialog, wx.DirDialog
wx.TextEntryDialog, wx.DirDialog = FakeText, FakeDir
FakeFileDialog.PICK = out
frame._open_board(pads_only)
ran = []
frame._run_export = lambda target, name: ran.append((target, name))
FakeText.VALUE = "Friday: night?"
frame._on_export()
check("it asks for a name, offering the board's own",
      FakeText.SEEN and FakeText.SEEN[-1][2] == "Pads", FakeText.SEEN)
check("the folder and the board take the name that was typed",
      ran and ran[-1] == (os.path.join(out, "Friday night"), "Friday night"),
      ran)
FakeText.VALUE = "   "
frame._on_export()
check("a name left empty falls back to the board's own",
      ran[-1] == (os.path.join(out, "Pads"), "Pads"), ran[-1])
wx.TextEntryDialog, wx.DirDialog = real_text, real_dir
wx.FileDialog = real_file_dialog
frame.board.dirty = False
frame.Destroy()

# ===========================================================================
heading("Work that finishes after its board has been put away (Mark)")
import threading

frame = empty_start()
relink_me = os.path.join(HOME, "Relink me.json")
frame._save(path=relink_me)
frame.board.slots[0].filepath = os.path.join(HOME, "was here", "s0.wav")
frame.board.slots[1].filepath = SOUNDS[1]
frame._touch()
frame._save()
old = frame.board
check("the board has one sound missing", old.missing_count == 1,
      old.missing_count)
gate = threading.Event()
real_relink = Board.relink


def slow_relink(self, folder):
    gate.wait(10)
    return real_relink(self, folder)


Board.relink = slow_relink
FakeFileDialog.PICK = os.path.join(HOME, "sounds")
real_dir = wx.DirDialog
wx.DirDialog = FakeFileDialog
real_busy, real_end = wx.BeginBusyCursor, wx.EndBusyCursor
wx.BeginBusyCursor = wx.EndBusyCursor = lambda *a, **k: None
frame._on_relink(None)
frame._on_new(None)                      # while the relink is still looking
fresh_path = frame.board.path
gate.set()
for _ in range(100):
    app.ProcessPendingEvents()
    wx.SafeYield()
    if old.missing_count == 0 and not old.dirty:
        break
    wx.MilliSleep(50)
Board.relink = real_relink
wx.DirDialog = real_dir
wx.BeginBusyCursor, wx.EndBusyCursor = real_busy, real_end
with open(relink_me, encoding="utf-8") as handle:
    saved_path = json.load(handle)["slots"][0]["filepath"]
check("a relink that finishes after File, New is saved in ITS board",
      "was here" not in saved_path, saved_path)
check("the new board is not marked as changed by it",
      not frame.board.dirty and not frame._save_timer.IsRunning())
after_timer_and_close(frame)
check("so no empty New board file is written",
      not os.path.exists(fresh_path))
check("and Relink me is still what opens next time",
      boardmod.same_path(boardmod.remembered_board_path(), relink_me),
      boardmod.remembered_board_path())

heading("The playlist's tag pass, the same way")
frame._open_board(relink_me)
old = frame.board
frame._on_new(None)
frame._playlist_metadata_ready(old)      # a pass for the board that left
check("a pass for a board that has gone does not touch the one that is open",
      not frame.board.dirty and not frame._save_timer.IsRunning())
# Since the final audit of the major release, a pass for a new board nobody
# has touched marks nothing and writes nothing: it is measured again next
# time (tests/test_review_final.py, item 1). One with changes of its own is
# still saved shortly, measurements and all.
frame._playlist_metadata_ready(frame.board)
check("a pass for the open board, new and untouched, writes nothing",
      not frame.board.dirty and not frame._save_timer.IsRunning()
      and not os.path.exists(frame.board.path))
frame.board.dirty = True
frame._playlist_metadata_ready(frame.board)
check("a pass for the open board with changes of its own still saves it "
      "shortly", frame._save_timer.IsRunning())
frame.board.dirty = False
frame._save_timer.Stop()

heading("A board copied in over New board is not ours to remove")
frame._on_new(None)
home = frame.board.path
b = Board()
b.slots[0].filepath = SOUNDS[0]
b.save(home)                             # somebody copies a board in there
frame._load_into(home, board=Board.load(home))    # the reload from disk
wx.FileDialog = FakeFileDialog
FakeFileDialog.PICK = os.path.join(HOME, "Copied in, named.json")
frame._on_save_as(None)
wx.FileDialog = real_file_dialog
check("Save board as leaves the copied in file where it was",
      os.path.exists(home))
os.remove(home)

heading("An imported bank never takes one of the app's own file names")
for own in ("last_board", "donate", "install", "feedback_queue", "board"):
    made = uimod.DropDeckFrame._new_home(own)
    check("%s becomes Imported %s" % (own, own),
          os.path.basename(made).startswith("Imported " + own), made)
check("and a name Windows would refuse is made safe",
      os.path.basename(uimod.DropDeckFrame._new_home("a<b>c")) == "a b c.json",
      uimod.DropDeckFrame._new_home("a<b>c"))
frame.board.dirty = False
frame.Destroy()

# ===========================================================================
print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
