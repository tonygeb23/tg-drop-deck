"""Dark mode, through accessible-wxpython-darkmode.

    https://github.com/alexoloopios/accessible-wxpython-darkmode

One door, the same shape as `speech.py`: if the library is not installed the
app runs exactly as it did before and says so if anybody asks. Nothing here
raises, and nothing here is on the path between a keypress and a sound.

**Why a library rather than a pile of SetBackgroundColour calls.** The obvious
way to get a dark check box on Windows is to give it a colour, and wxMSW
honours that by switching the control to owner drawn. An owner drawn Win32
BUTTON reports ROLE_SYSTEM_PUSHBUTTON whatever it used to be, so every check
box in Preferences would have been announced as "button" with no checked
state. That is the whole reason this app has never hardcoded a colour. The
library points real controls at the OS's own dark theme classes instead, and
refuses outright on a Windows too old to have them, which is the right answer:
a light window that reads correctly beats a dark one that does not.

**Follow the system setting, Light or Dark, and it defaults to Follow.**
`board.appearance`, on the Appearance page of Preferences. The default is the
right one and it is the reason the other two are only a dropdown rather than a
key: somebody who wants a dark computer has already said so once, in Windows
Settings, and an app that ignores that is an app they have to tell twice. The
two overrides exist for the case that one switch cannot express, a studio
where the room is dark and the rest of the machine is not, or the reverse.
**A Windows High Contrast theme still beats all three**, because that is an
assistive setting the user chose deliberately and this app does not know
better. It took no keystroke: the digit map is frozen and this is a setting,
not a performance.

**It cannot reach the Mac copy.** `mac/` is native Swift and AppKit with no
Python in it at all, and this is a Windows only library besides. AppKit
follows the system appearance on its own.

Two things in the window the library cannot do, and both are here: the eighty
pads, which paint their own face and are told by `palette()`, and the status
bar, which is a native control that ignores every colour. See
`_DarkStatusBar`. `ui` is the only caller of either.
"""

import json

import wx

from . import constants as C

try:
    import wxdarkmode
except Exception as exc:                      # pragma: no cover
    wxdarkmode = None
    _import_error = exc
else:
    _import_error = None

#: Roles read off the library's theme. They are its public vocabulary, so
#: naming them here keeps every other file free of the library entirely.
_ROLES = ("window", "surface", "surface_alt", "text", "text_secondary",
          "text_disabled", "border", "border_subtle", "accent", "accent_text",
          "selection", "selection_text", "error")


def available():
    """Whether the library is here at all."""
    return wxdarkmode is not None


def why_unavailable():
    """One sentence naming the thing to go and install, or an empty string."""
    if wxdarkmode is not None:
        return ""
    return ("accessible-wxpython-darkmode is not installed, so the window "
            "stays light: %r" % (_import_error,))


def saved_mode():
    """The user's Appearance choice, read straight off the board file.

    This has to answer BEFORE `wx.App` exists, and the board is not loaded
    until the frame is being built, so it peeks at the JSON rather than
    waiting for a `Board`. Enabling dark mode after the first window exists
    means the window appears light and then flips, which is exactly what
    somebody sensitive to brightness does not want to be shown.

    Anything unreadable, missing or unrecognised is "system", which is both
    the default and the safe answer.
    """
    try:
        from .board import default_board_path
        with open(default_board_path(), encoding="utf-8") as handle:
            look = json.load(handle).get("appearance")
        return look if look in C.APPEARANCE_MODES else C.DEFAULT_APPEARANCE
    except Exception:
        return C.DEFAULT_APPEARANCE


def enable(mode=None):
    """Turn dark mode on for the whole app. Returns True if it is in force.

    `mode` is one of `constants.APPEARANCE_MODES`, defaulting to whatever is
    saved. "system" follows the machine and keeps following it, so flipping
    the Windows switch while the app is open re-themes it.

    Called before `wx.App` exists on purpose. The library applies the process
    wide part of the opt-in immediately, which is what stops the first frame
    appearing light and then flipping.

    Returns False, quietly, for all five of the reasons it legitimately can:
    the library is not installed, Windows is older than 10 1809 and has no
    dark theme classes, the machine is in High Contrast, the user chose Light,
    or they chose Follow the system on a machine set to light. None of those
    is a fault and none of them is worth a message.
    """
    if wxdarkmode is None:
        return False
    if mode not in C.APPEARANCE_MODES:
        mode = saved_mode()
    try:
        return bool(wxdarkmode.enable(
            # "system" is the library's "auto". Named differently here
            # because "Follow the system setting" is what the box says and
            # "auto" is not a word that tells anybody what it will do.
            mode="auto" if mode == C.APPEARANCE_SYSTEM else mode,
            on_change=_repaint_everything))
    except Exception:
        # A theming library is not worth losing the app over.
        return False


def set_mode(mode):
    """Change the appearance while the app is running. Returns is_dark().

    Preferences calls this, and the window has to change as the OK is
    pressed: a setting that needs the app restarted to take effect is a
    setting people report as broken.
    """
    was = is_dark()
    now = bool(enable(mode))
    if now != was:
        _repaint_everything(now)
    return now


def is_dark():
    """Whether dark styling is actually being applied right now."""
    if wxdarkmode is None:
        return False
    try:
        return bool(wxdarkmode.is_dark())
    except Exception:
        return False


def is_high_contrast():
    """Whether a Windows High Contrast theme is on.

    Preferences says so out loud, because High Contrast beats all three
    choices and somebody who has it on would otherwise pick Dark, get their
    own scheme, and reasonably conclude the setting is broken.
    """
    if wxdarkmode is None:
        return False
    try:
        return bool(wxdarkmode.is_high_contrast())
    except Exception:
        return False


def palette():
    """`{role: wx.Colour}` while dark mode is on, or None when it is not.

    None is the answer for a light window, for High Contrast and for a machine
    with no library installed, so a caller that checks for None has covered
    every case without asking three questions.
    """
    if not is_dark():
        return None
    try:
        theme = wxdarkmode.current_theme()
        return {role: wx.Colour(getattr(theme, role)) for role in _ROLES}
    except Exception:
        return None


class _DarkStatusBar(wx.StatusBar):
    """A status bar that is dark, and is still a status bar.

    Measured 9 September 2026, and this is the one thing in the window the
    library cannot theme. A native Windows status bar draws its own text and
    ignores both `SetForegroundColour` and `SetBackgroundColour`, so it came
    back BLACK on `#202020`: 1.3 to 1, which is not low contrast, it is
    invisible. Clearing the theme with `SetWindowTheme(hwnd, "", "")` makes
    the text appear again by turning the whole bar light grey, which is worse.

    That matters more here than a status bar usually would. Every one of the
    three speech channels writes this bar at every speech level, deliberately,
    so that nothing the app has to say is ever only spoken. A user on `none`,
    or with the speech library missing, has this bar and nothing else.

    So the pixels are drawn here and NOTHING ELSE IS TOUCHED. The window is
    still the native `msctls_statusbar32`, `SetStatusText` still sends
    `SB_SETTEXT` to it, and the strings are still in the control for anything
    that asks. Measured against MSAA directly, a plain `wx.StatusBar` and this
    one both answer `ROLE_SYSTEM_STATUSBAR` with the same child text, which is
    the whole reason this is allowed to exist next to a library whose first
    rule is never to owner-draw a control. Painting over a native control is
    not the same as replacing one, and the difference is exactly what MSAA
    reports. `tests/test_darkmode.py` asserts it rather than trusting it.

    It is built only when dark styling is actually in force. In light mode the
    frame gets an ordinary `CreateStatusBar` and none of this runs.
    """

    def __init__(self, parent, shades):
        super().__init__(parent, style=wx.STB_DEFAULT_STYLE)
        self._face = shades["window"]
        self._ink = shades["text_secondary"]
        self._rule = shades["border_subtle"]
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        # The native control erases with its own brush, which would flash
        # light behind every repaint.
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _on_size(self, event):
        # The fields move, so the whole bar is repainted rather than the
        # newly exposed strip alone.
        self.Refresh()
        event.Skip()

    def _on_paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self._face))
        dc.Clear()
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(self._ink)
        height = self.GetClientSize().height
        top = max(0, (height - dc.GetCharHeight()) // 2)
        for field in range(self.GetFieldsCount()):
            try:
                rect = self.GetFieldRect(field)
            except Exception:
                continue
            if field:
                dc.SetPen(wx.Pen(self._rule))
                dc.DrawLine(rect.x - 2, 3, rect.x - 2, height - 3)
            text = self.GetStatusText(field)
            if not text:
                continue
            dc.SetClippingRegion(rect)
            dc.DrawText(wx.Control.Ellipsize(text, dc, wx.ELLIPSIZE_END,
                                             max(8, rect.width - 4)),
                        rect.x + 2, top)
            dc.DestroyClippingRegion()


def status_bar(frame, fields):
    """The frame's status bar, dark if dark mode is on and plain if it is not.

    Returns whatever `CreateStatusBar` would have, so the caller carries no
    branch and the light path is byte for byte what it was.
    """
    shades = palette()
    if shades is None:
        return frame.CreateStatusBar(fields)
    try:
        bar = _DarkStatusBar(frame, shades)
        bar.SetFieldsCount(fields)
        frame.SetStatusBar(bar)
        return bar
    except Exception:
        # Never lose the status bar over the colour of it.
        return frame.CreateStatusBar(fields)


def restyle_status_bar(frame, fields, widths):
    """Swap the frame's status bar for the right kind, if it is the wrong one.

    Changing Appearance while the app is open has to change the status bar as
    well as everything else, and this is the one control that cannot simply be
    recoloured: dark means the painted one and light means the native one, and
    they are different classes. Returns the bar to use, which is the existing
    one when nothing needed doing.

    The TEXT is carried across, because the bar usually has the last thing the
    app said in it and that is not something to drop on the floor while
    somebody is on air.
    """
    old = frame.GetStatusBar()
    wants_dark = palette() is not None
    if old is not None and isinstance(old, _DarkStatusBar) == wants_dark:
        return old
    said = []
    if old is not None:
        said = [old.GetStatusText(f) for f in range(old.GetFieldsCount())]
        frame.SetStatusBar(None)
        old.Destroy()
    bar = status_bar(frame, fields)
    if widths:
        bar.SetStatusWidths(list(widths))
    for field, text in enumerate(said[:bar.GetFieldsCount()]):
        bar.SetStatusText(text, field)
    return bar


def selfcheck():
    """Prove dark mode really works here. Returns (ok, one sentence).

    For the selftest, and it forces `mode="dark"` on a throwaway frame rather
    than reading whatever the machine happens to be set to. Two reasons.

    A frozen build that lost the library is the silent failure this is here
    to catch: nothing raises, the window is simply light for ever and looks
    deliberate. That has happened once already in this app with Pillow, and
    the lesson written down afterwards was to prove a bundled library WORKS
    rather than that it imports. Importing `wxdarkmode` proves nothing,
    because the part that does the work is a set of undocumented uxtheme
    ordinals it looks up at run time.

    And a check that only runs when the tester's own machine is in dark mode
    is a check that passes by accident on most machines.

    The frame is never shown and the state is put back afterwards, so this
    leaves nothing behind for the rest of the selftest to trip over.
    """
    if wxdarkmode is None:
        return False, why_unavailable()
    frame = None
    try:
        if wxdarkmode.is_high_contrast():
            # It stands down in front of High Contrast on purpose, so there
            # is nothing here to prove and nothing wrong.
            return True, "dark mode: standing down, High Contrast is on"
        frame = wx.Frame(None, title="dark mode check")
        panel = wx.Panel(frame)
        if not wxdarkmode.enable(mode="dark"):
            return False, ("dark mode: the theme classes are not available on "
                           "this Windows, so the window would stay light")
        wxdarkmode.apply(frame)
        want = wx.Colour(wxdarkmode.current_theme().window)
        got = panel.GetBackgroundColour()
        if (got.Red(), got.Green(), got.Blue()) != (want.Red(), want.Green(),
                                                    want.Blue()):
            return False, ("dark mode: the library is here but no colour "
                           "reached the window, %s rather than %s"
                           % (got.GetAsString(wx.C2S_HTML_SYNTAX),
                              want.GetAsString(wx.C2S_HTML_SYNTAX)))
        return True, ("dark mode: working, %s, and %s"
                      % (wxdarkmode.current_theme().name,
                         "following the system" if
                         wxdarkmode.system_uses_dark_mode()
                         else "the system is set to light"))
    except Exception as exc:
        return False, "dark mode raised in this build: %r" % (exc,)
    finally:
        try:
            wxdarkmode.disable()
        except Exception:
            pass
        if frame is not None:
            try:
                frame.Destroy()
            except Exception:
                pass


def _repaint_everything(_dark):
    """Repaint the windows the library cannot, when the OS switch is flipped.

    The library re-themes every native control by itself. The pads are painted
    by this app, so they only change when something asks them to, and the
    switch can be flipped while the app is open.

    `Refresh` and nothing else. It marks the window for repainting; it does
    not touch a label, so no accessible Name changes and no screen reader is
    interrupted mid sentence. Rewriting a Name here would be the exact thing
    `SoundButton.refresh` exists to avoid.
    """
    def repaint():
        for window in wx.GetTopLevelWindows():
            try:
                window.Refresh(True)
            except Exception:
                pass
    try:
        wx.CallAfter(repaint)
    except Exception:
        pass
