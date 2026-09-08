"""Dark mode: that it is on, that it reaches the pads, and what it must not do.

Added 9 September 2026. Preferences, Appearance offers Follow the system
setting, Light and Dark, and follows the system by default, through
accessible-wxpython-darkmode. It is a library rather than a pile of
SetBackgroundColour calls for one reason: on wxMSW, giving a colour to a check
box makes wxWidgets owner-draw it, and an owner-drawn Win32 BUTTON reports
ROLE_SYSTEM_PUSHBUTTON whatever it used to be. Every check box in Preferences
would have been announced as "button" with no checked state.

So the checks here are mostly about what dark mode is NOT allowed to cost.

The one thing this file cannot see is the app as somebody runs it, because
nothing in tests/ goes through main and main is what calls darkmode.enable.
tools/shot_darkmode.py photographs that.

    python tests/test_darkmode.py
"""

import ctypes
import inspect
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-dark-test-")

import wx

from dropdeck import constants as C
from dropdeck import darkmode, ui
from dropdeck.board import Board
from dropdeck.dialogs import SettingsDialog
from dropdeck.slot import Slot

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


def head(title):
    print(os.linesep + title + os.linesep)


def contrast(one, two):
    """WCAG 2.1 contrast ratio between two wx.Colours."""
    def channel(value):
        value = value / 255.0
        return value / 12.92 if value <= 0.03928 else (
            (value + 0.055) / 1.055) ** 2.4

    def luminance(colour):
        return (0.2126 * channel(colour.Red())
                + 0.7152 * channel(colour.Green())
                + 0.0722 * channel(colour.Blue()))

    lighter, darker = sorted((luminance(one), luminance(two)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


#: What Windows should be calling a status bar, whoever painted it.
ROLE_SYSTEM_STATUSBAR = 23
_OBJID_CLIENT = 0xFFFFFFFC
_IID_IACCESSIBLE = "{618736E0-3C3D-11CF-810C-00AA00389B71}"


def window_class(window):
    """The Win32 class name behind a wx window. The thing MSAA reads."""
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(int(window.GetHandle()), buf, 256)
    return buf.value


def msaa(window):
    """(role, what its children say) straight out of MSAA.

    Asked of Windows rather than of wx, because the whole question here is
    what a screen reader is told, and a screen reader asks Windows.
    """
    import comtypes
    import comtypes.client
    comtypes.client.GetModule("oleacc.dll")
    from comtypes.gen import Accessibility

    pointer = ctypes.POINTER(Accessibility.IAccessible)()
    ctypes.oledll.oleacc.AccessibleObjectFromWindow(
        int(window.GetHandle()), _OBJID_CLIENT,
        ctypes.byref(comtypes.GUID(_IID_IACCESSIBLE)),
        ctypes.byref(pointer))
    said = []
    for child in range(1, pointer.accChildCount + 1):
        try:
            said.append(pointer.accName(child))
        except Exception:
            pass
    return pointer.accRole(0), said


def _round_trips(dialog, mode):
    """Choosing a mode in the dropdown reads back as that same mode."""
    dialog.appearance_choice.SetSelection(C.APPEARANCE_MODES.index(mode))
    return dialog.appearance == mode


def _first_on(dialog, page):
    """What gets focus when Preferences opens on ``page``."""
    dialog.tabs.SetSelection(page)
    return dialog._first_control()


def main():
    app = wx.App(redirect=False)

    head("The library is here and it actually themes a window")

    check("the library imports", darkmode.available(),
          darkmode.why_unavailable())
    ok, said = darkmode.selfcheck()
    check("selfcheck passes", ok, said)
    print("       " + said)

    head("palette() answers None unless dark styling is really in force")

    # Nothing has called enable() in this test, so nothing is themed.
    check("no palette before enable", darkmode.palette() is None)
    check("is_dark is False before enable", not darkmode.is_dark())

    head("The pads follow it, because they paint their own face")

    slot = Slot(index=0)
    slot.filepath = os.path.abspath(__file__)
    slot.name = "a drop"

    light = ui._pad_colours(slot, False, False)
    check("a light pad has a light face",
          sum(light[0].Get()[:3]) > 384, light[0].GetAsString())

    # Force it rather than reading whatever this machine is set to, so the
    # check means the same thing on a light desk and a dark one.
    import wxdarkmode
    try:
        forced = wxdarkmode.enable(mode="dark")
        shades = darkmode.palette()
        check("dark mode can be forced on", forced)
        check("palette answers once dark is on", shades is not None)

        if shades is not None:
            face, edge, ink, sub, accent = ui._pad_colours(slot, False, False)
            check("a pad's face goes dark", sum(face.Get()[:3]) < 384,
                  face.GetAsString())
            check("the face is the theme's, not an invented colour",
                  face.Get()[:3] == shades["window"].Get()[:3])
            check("the ink is not left black on it",
                  sum(ink.Get()[:3]) > 384, ink.GetAsString())

            # The whole argument for a palette with contrast repair baked in
            # is that these pairs cannot quietly go unreadable. Assert it
            # rather than trust it: this is the one mode where getting it
            # wrong is unreadable and the user cannot check.
            check("name text clears WCAG AA on the face",
                  contrast(ink, face) >= 4.5,
                  "%.1f to 1" % contrast(ink, face))
            check("the hotkey line clears WCAG AA too",
                  contrast(sub, face) >= 4.5,
                  "%.1f to 1" % contrast(sub, face))
            check("the border clears 3 to 1", contrast(edge, face) >= 3.0,
                  "%.1f to 1" % contrast(edge, face))
            check("nothing is playing, so there is no accent bar",
                  accent is None)

            playing = ui._pad_colours(slot, True, False)
            check("a playing pad gets an accent bar", playing[4] is not None)
            check("the accent clears 3 to 1 against the face",
                  contrast(playing[4], playing[0]) >= 3.0,
                  "%.1f to 1" % contrast(playing[4], playing[0]))

            missing = Slot(index=1)
            missing.filepath = os.path.join(os.path.dirname(__file__),
                                            "no-such-sound.wav")
            missing.name = "gone"
            check("a missing sound is still marked",
                  ui._pad_colours(missing, False, False)[4] is not None)

            empty = ui._pad_colours(Slot(index=2), False, False)
            check("an empty slot's text is the disabled role",
                  empty[2].Get()[:3] == shades["text_disabled"].Get()[:3])

            hovered = ui._pad_colours(slot, False, True)
            check("hover is still a different face",
                  hovered[0].Get()[:3] != face.Get()[:3])

        head("What dark mode is not allowed to cost")

        # The reason this is a library and not a pile of colour assignments.
        # A wx.CheckBox that has been given a colour on wxMSW is owner drawn,
        # and an owner drawn BUTTON is announced as "button" with no checked
        # state. So the check box must come back from theming with its
        # colours untouched.
        frame = wx.Frame(None, title="roles")
        panel = wx.Panel(frame)
        box = wx.CheckBox(panel, label="Ask before going live")
        button = wx.Button(panel, label="Go live")
        before = (box.GetBackgroundColour().Get(),
                  box.GetForegroundColour().Get(),
                  button.GetBackgroundColour().Get(),
                  button.GetForegroundColour().Get())
        wxdarkmode.apply(frame)
        after = (box.GetBackgroundColour().Get(),
                 box.GetForegroundColour().Get(),
                 button.GetBackgroundColour().Get(),
                 button.GetForegroundColour().Get())
        check("no colour is put on a check box or a button", before == after,
              "%s then %s" % (before, after))
        check("the panel around them did go dark",
              panel.GetBackgroundColour().Get()[:3]
              == shades["window"].Get()[:3])

        # A pad is a wx.Button, so the same rule protects it, and it paints
        # its whole client area itself in any case.
        pad_frame = wx.Frame(None, title="pads")
        pad_panel = wx.Panel(pad_frame)
        wxdarkmode.apply(pad_frame)
        check("a themed panel is what a pad clears itself to",
              sum(pad_panel.GetBackgroundColour().Get()[:3]) < 384)
        pad_frame.Destroy()

        head("The status bar, which is the one thing the library cannot do")

        # Measured 9 September 2026: a native Windows status bar draws its own
        # text and ignores SetForegroundColour entirely, so it came back BLACK
        # on #202020, about 1.3 to 1. Every one of the three speech channels
        # writes this bar at every speech level, so a user on "none" has this
        # bar and nothing else. darkmode._DarkStatusBar paints it instead.
        bar_frame = wx.Frame(None, title="status")
        bar = darkmode.status_bar(bar_frame, 2)
        bar.SetStatusText("TG Drop Deck ready. 40 sounds loaded", 1)
        check("dark mode gets the painted status bar",
              isinstance(bar, darkmode._DarkStatusBar))
        check("its text clears WCAG AA on its face",
              contrast(bar._ink, bar._face) >= 4.5,
              "%.1f to 1" % contrast(bar._ink, bar._face))

        # And the reason painting it is allowed at all, next to a library
        # whose first rule is never to owner-draw a control: the window is
        # still the native one, so MSAA still calls it a status bar and the
        # text is still in it. Painting over a native control is not the same
        # as replacing one. Asked of MSAA directly rather than assumed.
        plain_frame = wx.Frame(None, title="plain status")
        plain = plain_frame.CreateStatusBar(2)
        plain.SetStatusText("TG Drop Deck ready. 40 sounds loaded", 1)
        for frame_ in (bar_frame, plain_frame):
            frame_.Show()
        for _ in range(15):
            wx.Yield()

        check("it is still the native status bar window",
              window_class(bar) == window_class(plain) == "msctls_statusbar32",
              "%s and %s" % (window_class(bar), window_class(plain)))
        painted, ordinary = msaa(bar), msaa(plain)
        check("MSAA still calls it a status bar",
              painted[0] == ordinary[0] == ROLE_SYSTEM_STATUSBAR, painted[0])
        check("and it still says the same thing",
              painted[1] == ordinary[1] and painted[1], painted[1])
        bar_frame.Destroy()
        plain_frame.Destroy()

        # The rule from CLAUDE.md, in a new place: what is on air is spoken,
        # and a repaint must never rewrite an accessible Name under focus.
        source = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "dropdeck", "darkmode.py"),
            encoding="utf-8").read()
        check("nothing here sets a label", "SetLabel" not in source)
        check("nothing here sets an accessible name",
              "SetName" not in source and "set_accessible_name" not in source)
        check("the repaint is a Refresh and nothing else",
              "Refresh(" in source)

        frame.Destroy()
    finally:
        wxdarkmode.disable()

    head("It stays out of the way of everything else")

    check("dark mode is off again after disable", not darkmode.is_dark())
    check("and the pads go back to the light palette",
          ui._pad_colours(slot, False, False)[0].Get()[:3]
          == light[0].Get()[:3])

    head("Follow the system setting, Light, or Dark")

    board = Board()
    check("a new board follows the system",
          board.appearance == C.APPEARANCE_SYSTEM, board.appearance)
    check("that is the documented default",
          C.DEFAULT_APPEARANCE == C.APPEARANCE_SYSTEM)
    check("there are exactly three choices, and a label for each",
          len(C.APPEARANCE_MODES) == len(C.APPEARANCE_LABELS) == 3)

    # It survives a save and a load, which is the whole point of it being a
    # setting rather than a switch you flip every launch.
    path = os.path.join(tempfile.mkdtemp(prefix="dd-look-"), "board.json")
    board.appearance = C.APPEARANCE_DARK
    board.save(path)
    check("it is written to the board file",
          json.load(open(path, encoding="utf-8")).get("appearance") == "dark")
    check("and read back", Board.load(path).appearance == C.APPEARANCE_DARK)

    # A board file is not a trusted document, and neither is one written by a
    # later version with more choices in it. Same rule as every other setting
    # in board.py: fall back, never raise.
    data = json.load(open(path, encoding="utf-8"))
    data["appearance"] = "midnight-neon"
    json.dump(data, open(path, "w", encoding="utf-8"))
    check("something unrecognised falls back to following the system",
          Board.load(path).appearance == C.APPEARANCE_SYSTEM)

    # Older boards predate the setting entirely.
    del data["appearance"]
    json.dump(data, open(path, "w", encoding="utf-8"))
    check("an older board follows the system too",
          Board.load(path).appearance == C.APPEARANCE_SYSTEM)

    # saved_mode reads the file directly, because it has to answer before
    # wx.App exists and long before any Board has been built.
    check("saved_mode never raises without a board file",
          darkmode.saved_mode() in C.APPEARANCE_MODES,
          darkmode.saved_mode())

    head("The dropdown that sets it")

    # A real dialog, because a Choice with the wrong number of entries or a
    # selection that does not map back is the kind of fault that only shows
    # up when somebody opens the window.
    deck = ui.DropDeckFrame()
    with SettingsDialog(deck, deck.board, deck.mixer, mic=deck.mic) as dialog:
        choice = dialog.appearance_choice
        check("the dropdown offers all three",
              choice.GetCount() == 3, choice.GetCount())
        check("it opens on what the board says",
              C.APPEARANCE_MODES[choice.GetSelection()]
              == C.DEFAULT_APPEARANCE)
        check("it has an accessible name",
              bool(choice.GetName()) and choice.GetName() != "choice",
              choice.GetName())
        # A screen reader reads the label as well as the name, and the
        # ampersand is the access key. Neither is optional here.
        check("and it reads back what was chosen",
              all(_round_trips(dialog, mode) for mode in C.APPEARANCE_MODES))
        check("the Appearance page is its own tab",
              dialog.tabs.GetPageText(dialog.PAGE_APPEARANCE) == "Appearance",
              dialog.tabs.GetPageText(dialog.PAGE_APPEARANCE))
        check("landing on it lands on the dropdown, not the tab strip",
              _first_on(dialog, dialog.PAGE_APPEARANCE) is choice)

        # And it goes on to the board, live, rather than only at next launch.
        choice.SetSelection(C.APPEARANCE_MODES.index(C.APPEARANCE_DARK))
        deck.board.appearance = dialog.appearance
        deck._apply_appearance()
        check("choosing Dark applies it to the open window",
              darkmode.is_dark() and deck.board.appearance == "dark")
        check("and the status bar is swapped for the painted one",
              isinstance(deck.status, darkmode._DarkStatusBar))
        check("the frame's status bar IS that one",
              deck.GetStatusBar() is deck.status)
        check("with its two fields intact", deck.status.GetFieldsCount() == 2)

        choice.SetSelection(C.APPEARANCE_MODES.index(C.APPEARANCE_LIGHT))
        deck.board.appearance = dialog.appearance
        said = deck.status.GetStatusText(1)
        deck._apply_appearance()
        check("choosing Light applies that too", not darkmode.is_dark())
        check("and the plain status bar comes back",
              not isinstance(deck.status, darkmode._DarkStatusBar))
        check("the last thing the app said survived the swap",
              deck.status.GetStatusText(1) == said, deck.status.GetStatusText(1))
        check("the pads are light again",
              sum(ui._pad_colours(slot, False, False)[0].Get()[:3]) > 384)
    try:
        deck.mixer.close()
    except Exception:
        pass
    deck.Destroy()

    ui_source = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "dropdeck", "ui.py"),
        encoding="utf-8").read()

    # It took no keystroke, which is the rule the digit map lives by: a new
    # feature gets a new key, and this is not a feature you perform, it is a
    # setting you choose once. So it took none. A menu item carries its key
    # after a tab in its own label, which is what this looks for.
    check("dark mode took no keystroke",
          not [line for line in ui_source.splitlines()
               if "\\t" in line and "appearance" in line.lower()])
    check("and the frozen digit map still has its twenty keys a bank",
          all(len(C.BANK_HOTKEY_LABELS[bank]) == C.SLOTS_PER_BANK
              for bank in C.BANK_HOTKEY_LABELS))

    # Dark mode reaches the frame in exactly four places. Two are the things
    # the library cannot theme by itself: the pads, which paint their own
    # face, and the status bar, which is a native control that ignores every
    # colour. The other two are the Appearance setting being applied to the
    # open window. Everything else here is a real native control and gets its
    # dark appearance from the OS. A fifth caller wants reading rather than
    # assuming.
    asked = sorted(set(re.findall(r"darkmode\.(\w+)\(", ui_source)))
    check("the frame asks dark mode four questions and no more",
          asked == ["palette", "restyle_status_bar", "set_mode",
                    "status_bar"], asked)
    check("the first is the pad painter",
          "darkmode.palette()" in inspect.getsource(ui._pad_colours))
    check("the frame does not enable it, main.py does",
          "darkmode.enable" not in ui_source)

    head("Result")
    failed = CHECKS.count(False)
    print("  %d checks, %d failed" % (len(CHECKS), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
