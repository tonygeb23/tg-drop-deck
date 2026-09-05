"""What a screen reader will actually say, asked of Windows rather than of wx.

Tony, 4 September 2026, tabbing the Streaming tab with NVDA:

    Address   edit  Alt+d  selected 8001
    Password  combo box  MP3  collapsed  Alt+w

Every field announced the PREVIOUS field's label with its own value. And of
the crossfade box beside the running order:

    edit  selected 3.0

no label at all. Both shipped, and an earlier version of this file passed
both, because it asked wx what each control was called and wx is not who a
screen reader asks.

Measured here, with deliberately different strings so the answer could not be
a coincidence:

    static text before it, plus SetName   ->  the static text
    static text before it, no SetName     ->  the static text
    SetName only, no static text          ->  nothing at all

**SetName is not the accessible name on Windows.** It is a wx internal
identifier. MSAA hands a screen reader the static text that PRECEDES the
control in creation order, and creation order is the order things were built,
not the order they were added to a sizer. Build a control before its label and
it inherits the label of the row above it, which is exactly what happened.

So this asks Windows. It builds every dialog for real, walks the controls in
tab order and calls IAccessible::get_accName on each, which is the question
NVDA asks. A control that answers with nothing, or with its own class name, is
a control somebody has to identify by counting Tabs from the top of the window.

    python tools/check_labels.py

It does not replace listening with NVDA running. It replaces having to find
one silent box in a window of twenty by ear.
"""
import ctypes
import os
import re
import sys
import tempfile
from ctypes import POINTER, byref

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="dd-labels-"))

import comtypes
import comtypes.client
import wx

comtypes.client.GetModule("oleacc.dll")
from comtypes.gen.Accessibility import IAccessible          # noqa: E402
from comtypes.automation import VARIANT                     # noqa: E402

FAILED = []
CHECKED = [0]

#: The client area of a window, which is the object a screen reader lands on.
OBJID_CLIENT = 0xFFFFFFFC

#: Answers that mean nobody named it. wx hands out its own class name when it
#: has nothing better, and a class name is not a label.
NOT_A_NAME = re.compile(r"^(wx[A-Za-z]*)?$")

#: Controls that carry their own words: a button says its label, a check box
#: says its label. Nothing to associate, so nothing to lose.
SPEAKS_FOR_ITSELF = (wx.Button, wx.ToggleButton, wx.CheckBox, wx.RadioButton,
                     wx.StaticText, wx.Notebook, wx.BitmapButton)

#: Controls that are a blank box until something names them.
NEEDS_A_NAME = (wx.TextCtrl, wx.Choice, wx.ComboBox, wx.SpinCtrl,
                wx.SpinCtrlDouble, wx.ListCtrl, wx.ListBox, wx.CheckListBox,
                wx.Slider)


#: Names wx hands out when nobody chose one. Comparing against these would
#: be comparing against noise, so a control wearing one is only checked for
#: being silent, not for being right.
WX_DEFAULT_NAMES = {
    "", "panel", "text", "textctrl", "choice", "combobox", "combo",
    "spinctrl", "spinctrldouble", "listctrl", "listbox", "checklistbox",
    "slider", "control", "window", "staticbox", "scrolledpanel",
}


def tidy(name):
    """Two ways of writing the same label, reduced to one.

    Access keys, trailing colons, capitals and runs of space are all
    differences in typography rather than in what a person hears.
    """
    name = (name or "").replace("&", "").strip().rstrip(":").strip()
    return " ".join(name.lower().split())


def intended(control):
    """What this codebase says the control is, or nothing if it never said.

    wx.SetName is not what a screen reader reads, which is the whole reason
    this file exists. It IS a statement of intent though, written by whoever
    built the control, and comparing intent against what Windows actually
    says is the only way to catch a name that is present, unique, and wrong:
    the Address box announcing "Port" passed every other check here.
    """
    try:
        name = control.GetName() or ""
    except Exception:
        return ""
    return "" if tidy(name) in WX_DEFAULT_NAMES else name


def agree(wanted, spoken):
    """Whether the codebase and Windows are talking about the same control.

    Not equality. A visible label sits under a heading and inside a tab, so
    it is often the short form of the name the code uses: the Output tab says
    "Music Beds" where the code says "Music Beds output", and a listener has
    both the tab and the heading for the rest. One containing the other is
    the same control described at two lengths.

    Two DIFFERENT controls almost never do that, which is what this is for.
    "Address" against "Port", or "Mount point" against "User name", fails on
    sight, and so does every off by one: adjacent fields are adjacent because
    they ask different questions.
    """
    wanted, spoken = tidy(wanted), tidy(spoken)
    if not wanted or not spoken:
        return True
    return wanted in spoken or spoken in wanted


def say(label, ok, detail=""):
    CHECKED[0] += 1
    if not ok:
        FAILED.append(label)
    print(("  ok   " if ok else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" else ""), flush=True)


def accessible_name(window):
    """What Windows tells a screen reader this control is called."""
    try:
        acc = POINTER(IAccessible)()
        ctypes.oledll.oleacc.AccessibleObjectFromWindow(
            ctypes.c_void_p(window.GetHandle()), OBJID_CLIENT,
            byref(IAccessible._iid_), byref(acc))
        which = VARIANT()
        which.value = 0                      # CHILDID_SELF
        return acc.accName(which) or ""
    except Exception:
        return ""


def focus_target(control):
    """The window Tab actually lands on.

    A spin control is a wrapper around a native edit box and a pair of
    arrows. Focus goes to the edit, so the edit is the thing whose name has
    to be right; naming the wrapper names something nobody visits.
    """
    if isinstance(control, (wx.SpinCtrl, wx.SpinCtrlDouble)):
        for child in control.GetChildren():
            if isinstance(child, wx.TextCtrl):
                return child
    return control


def tab_order(window):
    """Every focusable control, depth first, which is how Tab walks them."""
    found = []
    for child in window.GetChildren():
        if isinstance(child, (wx.Panel, wx.Notebook)) or child.GetChildren():
            found.extend(tab_order(child))
        if child.AcceptsFocusFromKeyboard():
            found.append(child)
    return found


def all_children(window):
    found = []
    for child in window.GetChildren():
        found.append(child)
        found.extend(all_children(child))
    return found


def audit(title, window):
    controls = tab_order(window)
    say("%s: has controls to tab through" % title, bool(controls), len(controls))

    silent, wrong, heard = [], [], {}
    seen = set()
    for control in controls:
        if isinstance(control, SPEAKS_FOR_ITSELF):
            continue
        if not isinstance(control, NEEDS_A_NAME):
            continue
        # A spin control turns up twice: once as itself and once as the edit
        # box inside it, which is the same Tab stop. Counting it twice would
        # report every correctly named spin as a duplicate name.
        target = focus_target(control)
        handle = target.GetHandle()
        if handle in seen:
            continue
        seen.add(handle)
        spoken = accessible_name(target).strip()
        if NOT_A_NAME.match(spoken):
            silent.append("%s says %r" % (type(control).__name__, spoken))
        else:
            heard.setdefault(spoken, 0)
            heard[spoken] += 1
            wanted = intended(control)
            if wanted and not agree(wanted, spoken):
                wrong.append("%s should be %r, Windows says %r"
                             % (type(control).__name__, wanted, spoken))

    say("%s: every box says what it is, asked of Windows" % title,
        not silent, "; ".join(silent))

    # The one an earlier version of this file could not see. A control whose
    # accessible name is present and unique can still be the WRONG name: a
    # box built before its own label inherits the label of the row above, so
    # every field on the tab announces the previous field. Both audits missed
    # it; NVDA did not.
    say("%s: and says the right one, not the one above it" % title,
        not wrong, "; ".join(wrong))

    repeated = [n for n, count in heard.items() if count > 1]
    say("%s: and no two of them say the same thing" % title,
        not repeated, ", ".join(repeated))

    keys = {}
    for control in all_children(window):
        try:
            label = control.GetLabel() or ""
        except Exception:
            continue
        match = re.search(r"&(\w)", label)
        if match:
            keys.setdefault(match.group(1).lower(), []).append(
                label.replace("&", ""))
    clashes = ["Alt+%s: %s" % (k, " / ".join(v))
               for k, v in keys.items() if len(v) > 1]
    say("%s: no two controls share an Alt key" % title,
        not clashes, "; ".join(clashes))


def main():
    app = wx.App(redirect=False)
    from dropdeck.dialogs import (AssignHotkeyDialog, DonateDialog,
                                  DropsLibraryDialog, FeedbackDialog,
                                  SearchDialog, SettingsDialog,
                                  SlotPropertiesDialog, SoundBrowserDialog,
                                  SourcesDialog, StreamStatsDialog,
                                  TrackCrossfadeDialog, TrimDialog)
    from dropdeck.playlist import Track
    from dropdeck.ui import DropDeckFrame

    frame = DropDeckFrame()
    # Shown, because a window that was never realised has no accessible
    # object behind it and every answer would be an empty string.
    frame.Show()
    app.Yield()
    board = frame.board
    slot = board[0]
    if not slot.name:
        slot.name = "A sound"

    print("\nThe main window")
    audit("Main window", frame)

    print("\nEvery tab of Preferences")
    prefs = SettingsDialog(frame, board, frame.mixer, mic=frame.mic)
    prefs.Show()
    app.Yield()
    for page in range(prefs.tabs.GetPageCount()):
        prefs.tabs.SetSelection(page)
        app.Yield()
        audit("Preferences, %s" % prefs.tabs.GetPageText(page),
              prefs.tabs.GetPage(page))
    prefs.Destroy()

    print("\nThe rest of the dialogs")
    for title, build in [
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
        # It asks a server on a thread, so it opens with an empty list and
        # names everything before any answer arrives, which is the state the
        # names have to be right in.
        ("Who is listening",
         lambda: StreamStatsDialog(frame, frame._stream_settings())),
        # With a source in it, because the controls underneath the list are
        # disabled and unnamed until something is selected.
        ("Audio sources",
         lambda: SourcesDialog(frame, [{"name": "A source",
                                        "device_name": "", "on_air": True}])),
    ]:
        try:
            dialog = build()
            dialog.Show()
            app.Yield()
        except Exception as exc:
            say("%s: opens at all" % title, False,
                "%s: %s" % (type(exc).__name__, exc))
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
