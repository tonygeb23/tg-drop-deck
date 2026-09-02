"""The window: every control built, every control named, every key mapped.

This builds the real frame. It never shows it and it never opens a modal, so it
finishes on its own. A control with no accessible name is a failure here,
because a control with no name is a control a screen reader cannot describe.

    python tests/test_ui.py
"""

import os
import sys
import tempfile

import numpy as np
import soundfile as sf
import wx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# APPDATA is redirected BEFORE the app is imported, so nothing here can read or
# write the real saved board. board.config_dir() reads the variable every call,
# and a real DropDeckFrame both loads the board and autosaves it. A test run on
# 2026-08-30 left the live board set to silent speech by exactly this route.
import tempfile as _tempfile
os.environ["APPDATA"] = _tempfile.mkdtemp(prefix="dropdeck-test-appdata-")


from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.dialogs import SearchDialog, TrimDialog, key_label
from dropdeck.ui import DropDeckFrame, SoundButton, fixed_accelerators

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append((label, bool(condition), detail))
    if not condition:
        print(f"  FAIL  {label}   {detail}")


def silent_file(path, seconds=0.3, rate=48000):
    sf.write(path, np.zeros((int(seconds * rate), 2), dtype=np.float32), rate)
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="dropdeck-ui-")
    sound = silent_file(os.path.join(tmp, "beep.wav"))

    app = wx.App(redirect=False)

    print("The keyboard map")
    entries = fixed_accelerators()
    check("sixty fixed hotkeys", len(entries) == 60, f"{len(entries)}")
    by_slot = {index: (mods, code) for mods, code, index in entries}
    check("1 fires sound effect 1", by_slot[0] == (0, ord("1")))
    check("0 fires sound effect 10", by_slot[9] == (0, ord("0")))
    check("Shift+1 fires sound effect 11",
          by_slot[10] == (wx.ACCEL_SHIFT, ord("1")))
    check("Ctrl+1 fires drop 1", by_slot[20] == (wx.ACCEL_CTRL, ord("1")))
    check("Ctrl+Shift+1 fires drop 11",
          by_slot[30] == (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("1")))
    check("Alt+Ctrl+1 fires bed 1",
          by_slot[40] == (wx.ACCEL_ALT | wx.ACCEL_CTRL, ord("1")))
    check("Alt+Ctrl+Shift+0 fires bed 20",
          by_slot[59] == (wx.ACCEL_ALT | wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("0")))
    check("bank four has no fixed keys",
          not any(i >= 60 for i in by_slot), "misc should be user assigned")
    check("every hotkey is unique", len(set(by_slot.values())) == 60)
    check("key labels read back", key_label(ord("1"), wx.ACCEL_CTRL) == "Ctrl+1",
          key_label(ord("1"), wx.ACCEL_CTRL))
    check("modifier order is Alt, Ctrl, Shift",
          key_label(ord("5"), wx.ACCEL_ALT | wx.ACCEL_CTRL | wx.ACCEL_SHIFT)
          == "Alt+Ctrl+Shift+5")

    print("Building the window")
    frame = DropDeckFrame()
    # Work on a scratch board so the test never touches the real saved one.
    frame.board = Board()
    frame.board.path = os.path.join(tmp, "test-board.json")
    for bank in range(1, C.BANK_COUNT + 1):
        for button, slot in zip(frame.pages[bank].buttons,
                                frame.board.bank_slots(bank)):
            button.slot = slot
            button.refresh(False)

    check("four banks", frame.notebook.GetPageCount() == 4)
    titles = [frame.notebook.GetPageText(i) for i in range(4)]
    # The tab now carries how many slots in that bank hold a sound - nothing
    # on the strip said which banks had anything in them.
    check("banks are named in order",
          [t.split(" (")[0] for t in titles] ==
          ["1. Sound Effects", "2. Dialog Drops",
           "3. Music Beds", "4. Miscellaneous"], str(titles))
    check("each tab shows how many sounds it holds",
          all(t.endswith(")") and " (" in t for t in titles), str(titles))

    buttons = [b for bank in frame.pages.values() for b in bank.buttons]
    check("eighty buttons", len(buttons) == C.TOTAL_SLOTS, f"{len(buttons)}")
    check("every button has a label", all(b.GetLabel().strip() for b in buttons))
    check("every button knows its slot",
          all(isinstance(b, SoundButton) and b.slot is not None for b in buttons))
    check("buttons are reachable by keyboard",
          all(b.AcceptsFocusFromKeyboard() for b in buttons))
    check("empty slots say so, and still name their key",
          buttons[0].GetLabel() == "1. Empty, key 1", buttons[0].GetLabel())
    check("bed buttons carry their key",
          "Alt+Ctrl+1" in frame.pages[C.BANK_BEDS].buttons[0].GetLabel(),
          frame.pages[C.BANK_BEDS].buttons[0].GetLabel())

    print("Names for the screen reader")
    unnamed = []
    def walk(window, depth=0):
        for child in window.GetChildren():
            if isinstance(child, (wx.TextCtrl, wx.ListBox, wx.Choice, wx.Slider,
                                  wx.CheckBox, wx.Notebook)):
                name = child.GetName()
                if not name or name == "control":
                    unnamed.append(f"{type(child).__name__} at depth {depth}")
            walk(child, depth + 1)
    walk(frame)
    check("no unnamed controls in the main window", not unnamed, "; ".join(unnamed))
    check("the notebook is named", frame.notebook.GetName() == "Banks")
    check("there is a status bar", frame.status is not None)

    print("Assigning, renaming and trimming without a mouse")
    slot = frame.board[0]
    frame._apply_file(slot, sound)
    check("assigning stores the path", slot.filepath == sound)
    check("assigning measures the length", slot.duration and slot.duration > 0.2)
    check("assigning names it from the filename", slot.name == "beep")
    check("the button label updates", "beep" in buttons[0].GetLabel(),
          buttons[0].GetLabel())
    check("assigning says what happened", "assigned" in frame.speaker.last_message,
          frame.speaker.last_message)
    check("assigning remembers the folder", frame.board.last_sound_dir == tmp)

    slot.name = "test beep"
    frame._sync_button(slot)
    check("renaming shows on the button", "test beep" in buttons[0].GetLabel())

    print("Playing, ducking and stopping")
    frame.trigger(0)
    check("triggering an assigned slot plays it", frame.mixer.voice_count() >= 1)
    check("playing announces the name", "test beep" in frame.speaker.last_message,
          frame.speaker.last_message)
    frame.stop_all()
    check("stop all announces", frame.speaker.last_message == "Everything stopped",
          frame.speaker.last_message)
    frame.stop_all()
    check("stop all with nothing playing says so",
          frame.speaker.last_message == "Nothing was playing",
          frame.speaker.last_message)

    bed = frame.board[40]
    frame._apply_file(bed, sound)
    check("beds default to looping", bed.loop)
    frame.trigger(40)
    check("a bed starts", frame.mixer.is_playing(40))
    check("starting a bed says looping", "looping" in frame.speaker.last_message,
          frame.speaker.last_message)
    frame.trigger(40)
    check("the same key stops the bed", "Stopped bed" in frame.speaker.last_message,
          frame.speaker.last_message)

    print("Volume, both masters, independently")
    before_sfx, before_bed = frame.mixer.sfx_gain, frame.mixer.bed_gain
    frame._nudge("sfx", -1)
    check("F3 lowers the sound volume",
          abs(frame.mixer.sfx_gain - (before_sfx - C.VOLUME_STEP)) < 1e-6)
    check("lowering the sound volume leaves the beds alone",
          frame.mixer.bed_gain == before_bed)
    check("volume is announced as a percentage",
          "percent" in frame.speaker.last_message, frame.speaker.last_message)
    frame._nudge("bed", +1)
    check("F6 raises the bed volume",
          abs(frame.mixer.bed_gain - (before_bed + C.VOLUME_STEP)) < 1e-6)
    for _ in range(30):
        frame._nudge("sfx", -1)
    check("volume stops at silence", frame.mixer.sfx_gain == 0.0)
    for _ in range(40):
        frame._nudge("sfx", +1)
    check("volume stops at full", frame.mixer.sfx_gain == 1.0)

    was = frame.mixer.ducking
    frame._on_toggle_duck(None)
    check("Ctrl+D toggles ducking", frame.mixer.ducking is (not was))
    check("ducking change is announced",
          "Ducking" in frame.speaker.last_message, frame.speaker.last_message)
    frame._on_toggle_duck(None)

    print("Missing files are handled, not crashed on")
    gone = frame.board[1]
    gone.filepath = os.path.join(tmp, "not-here.wav")
    gone.name = "ghost"
    check("a missing file is detected", gone.is_missing)
    frame._sync_button(gone)
    check("the button says the file is missing",
          "file missing" in buttons[1].GetLabel(), buttons[1].GetLabel())
    frame.trigger(1)
    check("triggering a missing file explains itself",
          "missing" in frame.speaker.last_message, frame.speaker.last_message)
    check("triggering a missing file plays nothing",
          not frame.mixer.is_playing(1))

    print("Search")
    dialog = SearchDialog(frame, frame.board, frame.mixer.playing_slots())
    dialog._refresh("test")
    check("search finds the sound", dialog.results.GetCount() == 1,
          f"{dialog.results.GetCount()}")
    dialog._refresh("beep")
    check("search spans every bank", dialog.results.GetCount() == 2,
          f"{dialog.results.GetCount()}, the effect and the bed both match")
    dialog._refresh("test")
    check("search names the bank in its results",
          "SFX 1" in dialog.results.GetString(0), dialog.results.GetString(0))
    dialog._refresh("zzz")
    check("search can find nothing", dialog.results.GetCount() == 0)
    dialog._refresh("")
    check("an empty search lists everything assigned",
          dialog.results.GetCount() == frame.board.assigned_count)
    check("the search box is named", dialog.query.GetName() == "Search")
    dialog.Destroy()

    trim = TrimDialog(frame, frame.board[0])
    check("the level slider is named",
          trim.slider.GetName() == "Level in decibels")
    check("the level slider covers a useful range",
          trim.slider.GetMin() == -24 and trim.slider.GetMax() == 12)
    trim.Destroy()

    print("Help text covers the keys it promises")
    for phrase in ("Shift+1 to 0", "Ctrl+Shift+1 to 0", "Alt+Ctrl+1 to 0",
                   "F3 / F4", "F5 / F6", "Escape", "Ctrl+F", "Ctrl+E",
                   "Alt+Enter", "Ctrl+Tab"):
        check(f"help mentions {phrase}", phrase in C.KEYBOARD_HELP)

    print("Saving")
    frame.board.save(frame.board.path)
    reread = Board.load(frame.board.path)
    check("the board round trips", reread[0].name == "test beep")
    check("saving clears the dirty flag", frame.board.dirty is False)

    frame.mixer.close()
    frame.Destroy()
    app.Destroy()

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
