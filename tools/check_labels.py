"""Walk every dialog the way a screen reader does, and check it says something.

Tony, 4 September 2026: "make sure field labels are correct with NVDA on the
program as well, when tabbing and shift tabbing through dialogs."

The failure this catches is the quiet one. A text box with no name is not
broken, does not throw, and looks perfectly fine on screen next to its label.
Tab onto it with NVDA and you hear "edit, blank": the label beside it is a
separate control and a screen reader has no reason to connect the two. Every
box you cannot name is a box somebody has to fill in by counting Tabs from
the top of the window and remembering.

So this builds each dialog for real, walks the controls in tab order the way
Tab and Shift+Tab do, and asks of each one: if I landed here and heard only
what this control offers, would I know what it is for?

    python tools/check_labels.py

It does not replace listening to it with NVDA running. It replaces having to
notice, by ear, one silent box in a window of twenty.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="dd-labels-"))

import wx

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.slot import Slot

FAILED = []
CHECKED = [0]

#: What wxWidgets calls a control when nobody has named it. Hearing one of
#: these is hearing the class name, not the field.
WX_DEFAULTS = {
    "text", "textctrl", "choice", "combobox", "combo", "spinctrl",
    "spinctrldouble", "listctrl", "listbox", "checklistbox", "checkbox",
    "button", "panel", "dialog", "staticText", "statictext", "slider",
    "notebook", "radiobutton", "radiobox", "gauge", "scrollbar", "window",
    "item", "control", "",
}

#: Controls that carry their own words. A button says its label, a check box
#: says its label; there is nothing to connect and nothing to miss.
SPEAKS_FOR_ITSELF = (
    wx.Button, wx.ToggleButton, wx.CheckBox, wx.RadioButton, wx.StaticText,
    wx.Notebook, wx.BitmapButton,
)

#: Controls that are a blank box until something names them.
NEEDS_A_NAME = (
    wx.TextCtrl, wx.Choice, wx.ComboBox, wx.SpinCtrl, wx.SpinCtrlDouble,
    wx.ListCtrl, wx.ListBox, wx.CheckListBox, wx.Slider,
)


def say(label, ok, detail=""):
    CHECKED[0] += 1
    if not ok:
        FAILED.append(label)
    print(("  ok   " if ok else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""), flush=True)


def tab_order(window):
    """Every focusable control, depth first, which is how Tab walks them."""
    found = []
    for child in window.GetChildren():
        if isinstance(child, (wx.Panel, wx.Notebook)) or child.GetChildren():
            found.extend(tab_order(child))
        if child.AcceptsFocusFromKeyboard():
            found.append(child)
    return found


def spoken_name(control):
    """What a screen reader has to go on for this control."""
    name = (control.GetName() or "").strip()
    label = ""
    try:
        label = (control.GetLabel() or "").strip()
    except Exception:
        pass
    return name, label


def audit(title, window):
    """Every control that needs naming has one, and none is a class name."""
    controls = tab_order(window)
    say("%s: has controls to tab through" % title, bool(controls), len(controls))

    unnamed, generic = [], []
    for control in controls:
        if isinstance(control, SPEAKS_FOR_ITSELF):
            continue
        if not isinstance(control, NEEDS_A_NAME):
            continue
        name, label = spoken_name(control)
        heard = name or label
        if not heard:
            unnamed.append(type(control).__name__)
        elif heard.lower() in WX_DEFAULTS:
            generic.append("%s named %r" % (type(control).__name__, heard))

    say("%s: every box a screen reader lands on has a name" % title,
        not unnamed, ", ".join(unnamed))
    say("%s: and none of them is just the class name" % title,
        not generic, ", ".join(generic))

    duplicates = {}
    for control in controls:
        if not isinstance(control, NEEDS_A_NAME):
            continue
        # A spin control and the text box inside it deliberately share a
        # name: they are one field, and the inner box is the half that Tab
        # reaches. Counting them as a collision would be counting the fix.
        parent = control.GetParent()
        if (isinstance(control, wx.TextCtrl)
                and isinstance(parent, (wx.SpinCtrl, wx.SpinCtrlDouble))):
            continue
        heard = (control.GetName() or "").strip()
        if heard and heard.lower() not in WX_DEFAULTS:
            duplicates.setdefault(heard, 0)
            duplicates[heard] += 1
    repeated = [n for n, count in duplicates.items() if count > 1]
    say("%s: no two boxes answer to the same name" % title,
        not repeated, ", ".join(repeated))


def main():
    app = wx.App(redirect=False)
    from dropdeck.dialogs import (AssignHotkeyDialog, DonateDialog,
                                  DropsLibraryDialog, FeedbackDialog,
                                  SearchDialog, SettingsDialog,
                                  SlotPropertiesDialog, SoundBrowserDialog,
                                  TrackCrossfadeDialog, TrimDialog)
    from dropdeck.playlist import Track
    from dropdeck.ui import DropDeckFrame

    frame = DropDeckFrame()
    board = frame.board
    slot = board[0]
    if not slot.name:
        slot.name = "A sound"

    print("\nThe main window")
    audit("Main window", frame)

    print("\nEvery tab of Preferences")
    prefs = SettingsDialog(frame, board, frame.mixer, mic=frame.mic)
    for page in range(prefs.tabs.GetPageCount()):
        prefs.tabs.SetSelection(page)
        audit("Preferences, %s" % prefs.tabs.GetPageText(page),
              prefs.tabs.GetPage(page))
    prefs.Destroy()

    print("\nThe rest of the dialogs")
    made = [
        ("Slot properties", lambda: SlotPropertiesDialog(frame, slot)),
        ("Assign a hotkey", lambda: AssignHotkeyDialog(frame, slot)),
        ("Search", lambda: SearchDialog(frame, board)),
        ("Level for one slot", lambda: TrimDialog(frame, slot)),
        ("Drops library", lambda: DropsLibraryDialog(frame, board.drops)),
        ("Crossfade for one track",
         lambda: TrackCrossfadeDialog(frame, Track(""), 4.0)),
        ("Sound browser", lambda: SoundBrowserDialog(frame)),
        ("Submit feedback", lambda: FeedbackDialog(frame, frame)),
        ("Donate", lambda: DonateDialog(frame)),
    ]
    for title, build in made:
        try:
            dialog = build()
        except Exception as exc:
            say("%s: opens at all" % title, False, "%s: %s"
                % (type(exc).__name__, exc))
            continue
        audit(title, dialog)
        dialog.Destroy()

    frame.stop_background_work()
    frame.Destroy()
    app.Yield()

    print("\n%d checks, %d problems" % (CHECKED[0], len(FAILED)))
    for label in FAILED:
        print("  still wrong:", label)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
