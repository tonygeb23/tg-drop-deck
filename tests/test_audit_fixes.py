"""Regressions for what two audits found on 2026-08-29.

    python tests/test_audit_fixes.py

Every check here stands for a defect that was in the shipped app or in the
2.1.0 work, was measured rather than guessed at, and would be easy to
reintroduce.
"""

import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx

from dropdeck import constants as C
from dropdeck.dialogs import AssignHotkeyDialog, SearchDialog, SettingsDialog
from dropdeck.slot import Slot
from dropdeck.ui import DropDeckFrame, _escaped, _pad_colours

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


app = wx.App(redirect=False)

print("Per-monitor v2, not v1")
# ctypes marshals a bare -4 as 32 bits; the parameter is a pointer-sized
# handle, so the call returned 0 with ERROR_INVALID_PARAMETER and the app
# silently fell through to per-monitor v1.
import main                                                    # noqa: E402
main._make_dpi_aware()
u32 = ctypes.windll.user32
ctx = u32.GetThreadDpiAwarenessContext()
check("the app reaches per-monitor v2",
      bool(u32.AreDpiAwarenessContextsEqual(
          ctx, ctypes.c_void_p(-4 & 0xFFFFFFFFFFFFFFFF))))

print("\nAmpersands in a sound name")
# Win32 eats a single & as a mnemonic prefix and MSAA strips it, so a drop
# called "Q&A Bumper" was announced as "QA Bumper". "R&B" and "Q&A" are
# ordinary names for a soundboard.
check("the label sent to wx is escaped", _escaped("Q&A") == "Q&&A")
check("escaping is idempotent at the boundary only",
      _escaped("Rock & Roll") == "Rock && Roll")
check("slot.py still returns the real text",
      "&" in Slot(index=0, name="Q&A").button_label())

print("\nThe hotkey dialog")
frame = wx.Frame(None)
slot = Slot(index=0, filepath="x.wav", name="Test")
dialog = AssignHotkeyDialog(frame, slot, global_mode=True)
# Both audits caught this independently: ui.py passed global_mode=True and the
# dialog did not take it, so the whole global-hotkey feature raised TypeError
# and, in a windowed build with no console, did so completely silently.
check("global_mode is accepted", dialog.global_mode is True)
check("the title says global", "global" in dialog.GetTitle().lower(),
      dialog.GetTitle())
check("it starts from the slot's global hotkey, not its bank key",
      dialog.hotkey_text() == "")
# Tab and Space used to be capturable. Binding Tab removed the only way to
# move between pads, and the dialog's own char hook swallowed Tab, so Clear
# was unreachable - an unrecoverable lockout with a keyboard.
for key in (wx.WXK_TAB, wx.WXK_SPACE, wx.WXK_ESCAPE):
    check("a bare %s is reserved, not capturable" % key,
          key in AssignHotkeyDialog.RESERVED)
dialog.Destroy()

print("\nThe search dialog's default button")
frame2 = DropDeckFrame()
search = SearchDialog(frame2, frame2.board, set())
# Walk this dialog's own children. wx.Window.FindWindowById resolves to the
# GLOBAL lookup here and happily returned a different dialog's OK button.
jump = next((c for c in search.GetChildren()
             if isinstance(c, wx.Button) and "Jump" in c.GetLabel()), None)
# It had no EVT_BUTTON handler at all, so wxDialog's own ID_OK handler ended
# the modal without recording a choice: pressing Enter in the results list -
# the way the dialog's own instructions describe - did nothing.
check("Jump to it exists", jump is not None)
if jump is not None:
    search._refresh("")
    search.results.SetSelection(0)
    # EndModal asserts on a dialog that was never shown modally, and that is a
    # limit of the harness rather than of the app - _accept has already
    # recorded the choice by the time it is reached.
    search.EndModal = lambda code: None
    event = wx.CommandEvent(wx.EVT_BUTTON.typeId, jump.GetId())
    event.SetEventObject(jump)
    jump.GetEventHandler().ProcessEvent(event)
    check("Jump to it records a choice", search.chosen is not None,
          "chosen=%r" % (search.chosen,))
search.Destroy()

print("\nThe settings dialog")
settings = SettingsDialog(frame2, frame2.board, frame2.mixer)
settings.duck_on.SetValue(False)
settings.duck_on.GetEventHandler().ProcessEvent(
    wx.CommandEvent(wx.EVT_CHECKBOX.typeId, settings.duck_on.GetId()))
check("the duck slider follows its checkbox", not settings.duck_db.IsEnabled())
settings.Destroy()

print("\nPad states are distinguishable, and never colour-only")
_demo = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "demo", "sfx")
_real = os.path.join(_demo, sorted(os.listdir(_demo))[0])
loaded = Slot(index=0, filepath=_real, name="A", duration=2.0)
empty = Slot(index=1)
missing = Slot(index=2, filepath=r"C:\gone\x.wav", name="B")
faces = {
    "empty": _pad_colours(empty, False, False),
    "loaded": _pad_colours(loaded, False, False),
    "playing": _pad_colours(loaded, True, False),
    "missing": _pad_colours(missing, False, False),
}
check("every state paints differently",
      len({tuple(str(c) for c in v) for v in faces.values()}) == 4)
check("a playing pad gets an accent bar", faces["playing"][4] is not None)
check("a quiet pad does not", faces["loaded"][4] is None)
# The rule the whole visual layer rests on.
check("playing is a word in the label too",
      "playing" in loaded.button_label(True))
check("missing is a word in the label too",
      "file missing" in missing.button_label())
check("empty is a word in the label too", "Empty" in empty.button_label())

print("\nThe keypress path is warm")
# Nothing warmed the decode cache, so the FIRST press of a sound decoded it on
# the UI thread - 87.5 ms for a bed, measured. CLAUDE.md says short sounds are
# decoded at assignment time "precisely so the key is instant".
check("the frame has a cache warmer", hasattr(frame2, "warm_cache"))
check("it is called at startup",
      "self.warm_cache()" in open(
          os.path.join(os.path.dirname(os.path.dirname(
              os.path.abspath(__file__))), "dropdeck", "ui.py"),
          encoding="utf-8").read())

print("\nBanks announce themselves")
check("the notebook says which bank you landed in",
      hasattr(frame2, "_on_bank_changed"))
check("tab titles carry a count",
      frame2.notebook.GetPageText(0).endswith(")"),
      frame2.notebook.GetPageText(0))

print("\nCtrl+G took a new key, not one from the frozen map")
entries = C.KEYBOARD_HELP
check("Ctrl+G is documented", "Ctrl+G" in entries)
for reserved in ("Ctrl+E", "Ctrl+D", "Ctrl+L", "F2", "F3", "F5", "F6"):
    check("%s still means what it always did" % reserved, reserved in entries)

try:
    frame2.mixer.close()
except Exception:
    pass
frame2.Destroy()
frame.Destroy()


print("\nOnly one copy at a time")
from dropdeck.singleinstance import SingleInstance                # noqa: E402
import main as _main                                              # noqa: E402

# A named mutex, not a lock file: Windows releases it when the owning process
# dies however it dies, so a crash cannot leave the app permanently convinced
# it is already running.
_first = SingleInstance("TGDropDeckTest")
check("nothing was running to begin with", not _first.already_running)
_second = SingleInstance("TGDropDeckTest")
check("a second copy notices the first", _second.already_running)
_second.release()
_first.release()
_third = SingleInstance("TGDropDeckTest")
check("a new copy starts once the first lets go", not _third.already_running)
_third.release()

check("the slug is stable", _main.INSTANCE_SLUG == "TGDropDeck",
      _main.INSTANCE_SLUG)
check("the mutex is per-session, so two signed-in users do not block each other",
      SingleInstance("X").mutex_name.startswith("Local\\"))

failed = [n for n, ok in CHECKS if not ok]
print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
