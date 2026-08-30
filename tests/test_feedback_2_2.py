"""Regressions for the 2.2.0 listener feedback.

    python tests/test_feedback_2_2.py

Everything here stands for something a user wrote in about after 2.1.2, and
every one of them is a thing that would be easy to undo by accident:

  * David Goldfield - F2 should rename, the volume keys should move down one,
    Alt on its own should be a usable modifier for a global hotkey, the global
    hotkey should be on the right-click menu, Alt+Enter should open properties,
    and Ctrl+F should be the find key.
  * Brian Hartgen - the app should be able to stop talking over the screen
    reader, and the bank hint should not be read out on every tab change.
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx

from dropdeck import constants as C
from dropdeck import globalhotkeys
from dropdeck.board import Board
from dropdeck.dialogs import (AssignHotkeyDialog, SettingsDialog,
                              SlotPropertiesDialog, key_label)
from dropdeck.ui import (ID_GLOBAL_HOTKEY, ID_PROPERTIES, ID_RENAME, ID_SEARCH,
                         ID_VOL_SFX_DOWN, ID_VOL_SFX_UP, DropDeckFrame)

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


class FakeKey:
    """Enough of a wx key event for _on_key, which is where the Alt bug was.

    The dialog cannot be driven with real keystrokes from a test, and the
    defect was entirely in this handler's branching, so this is where the
    regression has to be caught.
    """

    def __init__(self, code, alt=False, ctrl=False, shift=False):
        self._code, self._alt = code, alt
        self._ctrl, self._shift = ctrl, shift
        self.skipped = False

    def GetKeyCode(self):
        return self._code

    def AltDown(self):
        return self._alt

    def ControlDown(self):
        return self._ctrl

    def ShiftDown(self):
        return self._shift

    def Skip(self):
        self.skipped = True


app = wx.App(redirect=False)
tmp = tempfile.mkdtemp(prefix="dropdeck-feedback-")

# ---------------------------------------------------------------------------
print("Alt on its own is a modifier")

# parse always accepted it. The capture dialog was the thing that would not
# let you type it: Alt plus a printable character was handed to the dialog's
# own button mnemonics, so Alt+A could be pressed but never captured.
check("Alt+A parses as a global hotkey", globalhotkeys.parse("Alt+A") is not None)
mods, key = globalhotkeys.parse("Alt+A")
check("Alt+A carries the Alt modifier", mods & globalhotkeys.MOD_ALT)
check("Alt+A does not carry Ctrl", not mods & globalhotkeys.MOD_CONTROL)
check("a bare key is still refused", globalhotkeys.parse("A") is None)

frame = DropDeckFrame()
frame.board = Board()
frame.board.path = os.path.join(tmp, "board.json")
slot = frame.board[0]
slot.filepath = os.path.join(tmp, "nothing.wav")
slot.name = "test drop"

dialog = AssignHotkeyDialog(frame, slot, global_mode=True)
event = FakeKey(ord("A"), alt=True)
dialog._on_key(event)
check("Alt+A is captured, not passed to a mnemonic", not event.skipped)
check("Alt+A reads back as Alt+A", dialog.hotkey_text() == "Alt+A",
      dialog.hotkey_text())
check("Alt+A raises no modifier warning", dialog.warning.GetLabel() == "",
      dialog.warning.GetLabel())

event = FakeKey(wx.WXK_TAB)
dialog._on_key(event)
check("Tab still reaches the buttons", event.skipped)
check("Tab is not captured as a hotkey", dialog.hotkey_text() == "Alt+A",
      dialog.hotkey_text())

# Alt+F4 closes a window in every Windows program. Registering it system-wide
# would take that away from all of them, this app included.
event = FakeKey(wx.WXK_F4, alt=True)
dialog._on_key(event)
check("Alt+F4 is refused", dialog.hotkey_text() == "Alt+A", dialog.hotkey_text())
check("Alt+F4 says why", "closes a window" in dialog.warning.GetLabel(),
      dialog.warning.GetLabel())

# Ctrl+Alt+F4 is a different key and perfectly registrable.
event = FakeKey(wx.WXK_F4, alt=True, ctrl=True)
dialog._on_key(event)
check("Ctrl+Alt+F4 is allowed", dialog.hotkey_text() == "Alt+Ctrl+F4",
      dialog.hotkey_text())

event = FakeKey(ord("B"), alt=True)
dialog._on_key(event)
check("a bare key still warns in global mode", dialog.hotkey_text() == "Alt+B")
event = FakeKey(ord("B"))
dialog._on_key(event)
check("no modifier at all is still called out",
      "needs a modifier" in dialog.warning.GetLabel(), dialog.warning.GetLabel())
dialog.Destroy()

# ---------------------------------------------------------------------------
print("\nThe function key row")

entries = frame._build_accelerators()
by_key = {}
for entry in entries:
    by_key[(entry.GetFlags(), entry.GetKeyCode())] = entry.GetCommand()

check("F2 renames", by_key.get((wx.ACCEL_NORMAL, wx.WXK_F2)) == ID_RENAME)
check("F3 lowers the sound volume",
      by_key.get((wx.ACCEL_NORMAL, wx.WXK_F3)) == ID_VOL_SFX_DOWN)
check("F4 raises the sound volume",
      by_key.get((wx.ACCEL_NORMAL, wx.WXK_F4)) == ID_VOL_SFX_UP)
check("F2 is no longer a volume key",
      by_key.get((wx.ACCEL_NORMAL, wx.WXK_F2)) not in
      (ID_VOL_SFX_DOWN, ID_VOL_SFX_UP))

check("Ctrl+F searches", by_key.get((wx.ACCEL_CTRL, ord("F"))) == ID_SEARCH)
# Ctrl+E was the search key for two releases. Taking a key back off someone
# who has already learned it is not a fix, so it still works.
check("Ctrl+E still searches", by_key.get((wx.ACCEL_CTRL, ord("E"))) == ID_SEARCH)
check("Alt+Enter opens properties",
      by_key.get((wx.ACCEL_ALT, wx.WXK_RETURN)) == ID_PROPERTIES)
check("Alt+numpad Enter opens properties too",
      by_key.get((wx.ACCEL_ALT, wx.WXK_NUMPAD_ENTER)) == ID_PROPERTIES)

# The digit map is the muscle memory. None of this was allowed to touch it.
digit_keys = [cmd for (flags, key_code), cmd in by_key.items()
              if ord("0") <= key_code <= ord("9")]
check("all sixty digit hotkeys survive", len(digit_keys) == 60, len(digit_keys))

# ---------------------------------------------------------------------------
print("\nProperties, on one dialog instead of four")

taken = frame._hotkey_map(exclude=slot.index)
props = SlotPropertiesDialog(frame, slot, taken)
check("the name field starts on the current name",
      props.name_field.GetValue() == "test drop", props.name_field.GetValue())
check("the level slider is named",
      props.level.GetName() == "Level in decibels")
check("the level slider covers the same range as the level dialog",
      props.level.GetMin() == -24 and props.level.GetMax() == 12)
check("bank one has no hotkey field of its own", props.hotkey_readout is None)
check("every slot has a global hotkey field", props.global_readout is not None)
check("the global hotkey reads None when unset",
      props.global_readout.GetValue() == "None", props.global_readout.GetValue())
check("the file is shown, not just hinted at",
      slot.filepath in props.file_readout.GetValue())
check("a bed gets a loop box, bank one does not", props.loop_box is None)

props.name_field.SetValue("renamed in properties")
props.level.SetValue(-6)
props._global_hotkey = "Alt+A"
result = props.result
check("the result carries the new name",
      result["name"] == "renamed in properties", result["name"])
check("the result carries the new level", result["trim_db"] == -6.0)
check("the result carries the global hotkey", result["global_hotkey"] == "Alt+A")
check("the dialog writes nothing to the slot itself",
      slot.name == "test drop" and slot.trim_db == 0.0,
      "%s / %s" % (slot.name, slot.trim_db))
props.Destroy()

bed = frame.board[C.SLOTS_PER_BANK * 2]     # first slot of bank three
bed.filepath = os.path.join(tmp, "bed.wav")
bed.name = "test bed"
bed_props = SlotPropertiesDialog(frame, bed)
check("a bed does get a loop box", bed_props.loop_box is not None)
check("the loop box reflects the bed", bed_props.loop_box.GetValue() is True)
bed_props.Destroy()

misc = frame.board[C.SLOTS_PER_BANK * 3]    # first slot of bank four
misc.filepath = os.path.join(tmp, "misc.wav")
misc.name = "test misc"
misc_props = SlotPropertiesDialog(frame, misc)
check("bank four does get its own hotkey field",
      misc_props.hotkey_readout is not None)
misc_props.Destroy()

# ---------------------------------------------------------------------------
print("\nThe right-click menu offers the global hotkey")

built = []

#: The real class, held before wx.Menu is rebound below. Calling wx.Menu.Append
#: from inside the subclass would resolve back to the subclass once the name is
#: swapped, and recurse until the stack runs out.
_REAL_MENU = wx.Menu


class RecordingMenu(_REAL_MENU):
    """Records what show_slot_menu puts on the menu, and is otherwise a menu."""

    def Append(self, ident, text="", *args, **kwargs):
        built.append(text)
        return _REAL_MENU.Append(self, ident, text, *args, **kwargs)

    def AppendCheckItem(self, ident, text="", *args, **kwargs):
        built.append(text)
        return _REAL_MENU.AppendCheckItem(self, ident, text, *args, **kwargs)


button = frame._button_for(slot)
button.slot = slot
real_menu = _REAL_MENU
had_own_popup = "PopupMenu" in type(button).__dict__
real_popup = type(button).__dict__.get("PopupMenu")
try:
    wx.Menu = RecordingMenu
    # A real PopupMenu blocks until something is chosen. Only the construction
    # is under test, so it is stubbed out.
    type(button).PopupMenu = lambda self, menu, position=None: None
    frame.show_slot_menu(slot, button)
finally:
    wx.Menu = real_menu
    if had_own_popup:
        type(button).PopupMenu = real_popup
    else:
        del type(button).PopupMenu

joined = " | ".join(built)
check("the right-click menu offers a global hotkey",
      any("Global hotkey" in text for text in built), joined)
check("it reads out the current global hotkey",
      any("now none" in text for text in built if "Global" in text), joined)
# "P&roperties" - the mnemonic sits inside the word, so match past it.
check("the right-click menu offers properties",
      any("roperties" in text for text in built), joined)
check("rename in the right-click menu says F2",
      any("F2" in text for text in built if "name" in text), joined)

# ---------------------------------------------------------------------------
print("\nHow much the app says out loud")

frame.board.speech_level = C.SPEECH_ALL
frame.speaker.last_message = ""
frame.announce_help("a confirmation")
check("everything speaks at the chatty level",
      frame.speaker.last_message == "a confirmation", frame.speaker.last_message)

frame.speaker.last_message = ""
frame.board.speech_level = C.SPEECH_ESSENTIAL
frame.announce_help("a confirmation")
check("confirmations go quiet at the middle level",
      frame.speaker.last_message == "", frame.speaker.last_message)
check("but the status bar still has it",
      frame.status.GetStatusText(1) == "a confirmation",
      frame.status.GetStatusText(1))

frame.announce("a file is missing")
check("a failure still speaks at the middle level",
      frame.speaker.last_message == "a file is missing", frame.speaker.last_message)

frame.speaker.last_message = ""
frame.announce_playback("Playing something")
check("playback names are quiet at the middle level",
      frame.speaker.last_message == "", frame.speaker.last_message)

frame.board.speech_level = C.SPEECH_NONE
frame.speaker.last_message = ""
frame.announce("a file is missing")
check("nothing speaks at the silent level",
      frame.speaker.last_message == "", frame.speaker.last_message)
check("the status bar is still written at the silent level",
      frame.status.GetStatusText(1) == "a file is missing",
      frame.status.GetStatusText(1))
frame.board.speech_level = C.SPEECH_ALL

# ---------------------------------------------------------------------------
print("\nThe bank hint is not read out twenty times a show")


class FakeBankEvent:
    def __init__(self, index):
        self._index = index

    def GetSelection(self):
        return self._index

    def Skip(self):
        pass


frame._hinted_banks = set()
frame.speaker.last_message = ""
frame._on_bank_changed(FakeBankEvent(1))        # bank two
check("the hint is spoken the first time you land on a bank",
      "Dialog Drops" in frame.speaker.last_message, frame.speaker.last_message)

frame.speaker.last_message = ""
frame._on_bank_changed(FakeBankEvent(1))
check("and not the second time", frame.speaker.last_message == "",
      frame.speaker.last_message)

frame.speaker.last_message = ""
frame._on_bank_changed(FakeBankEvent(2))        # bank three
check("a different bank is still introduced once",
      "Music Beds" in frame.speaker.last_message, frame.speaker.last_message)

check("the hint is still printed on the page",
      frame.pages[2].hint.GetLabel() == C.BANK_HINTS[2],
      frame.pages[2].hint.GetLabel())

# ---------------------------------------------------------------------------
print("\nThe setting survives a save, and an old board is carried across")

frame.board.speech_level = C.SPEECH_ESSENTIAL
frame.board.save(frame.board.path)
reread = Board.load(frame.board.path)
check("the speech level round trips", reread.speech_level == C.SPEECH_ESSENTIAL,
      reread.speech_level)

old = os.path.join(tmp, "old-board.json")
with open(old, "w", encoding="utf-8") as handle:
    json.dump({"announce_playback": False, "slots": []}, handle)
carried = Board.load(old)
check("a 2.1.2 board with playback speech off lands on the quieter level",
      carried.speech_level == C.SPEECH_ESSENTIAL, carried.speech_level)

with open(old, "w", encoding="utf-8") as handle:
    json.dump({"announce_playback": True, "slots": []}, handle)
carried = Board.load(old)
check("a 2.1.2 board that never touched it keeps everything",
      carried.speech_level == C.SPEECH_ALL, carried.speech_level)

with open(old, "w", encoding="utf-8") as handle:
    json.dump({"speech_level": "nonsense", "slots": []}, handle)
carried = Board.load(old)
check("a level this build does not know is not trusted",
      carried.speech_level in C.SPEECH_LEVELS, carried.speech_level)

settings = SettingsDialog(frame, frame.board, frame.mixer)
check("audio settings offers all three levels",
      settings.speech_choice.GetCount() == 3, settings.speech_choice.GetCount())
check("it opens on the board's level",
      settings.speech_level == frame.board.speech_level, settings.speech_level)
settings.speech_choice.SetSelection(0)
settings._on_speech_level(None)
check("the playback checkbox is live at the chatty level",
      settings.announce_playback.IsEnabled())
settings.speech_choice.SetSelection(1)
settings._on_speech_level(None)
check("and greyed below it, rather than lying",
      not settings.announce_playback.IsEnabled())
check("the choice reads back as a level string",
      settings.speech_level == C.SPEECH_ESSENTIAL, settings.speech_level)
settings.Destroy()

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
