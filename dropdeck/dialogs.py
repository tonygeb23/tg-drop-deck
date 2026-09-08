"""The dialogs.

Every one of them is keyboard-complete and every control has a name, because a
dialog you cannot get out of without a mouse is worse than no dialog.
"""

from __future__ import annotations

import ctypes
import os
import socket
import ssl
import threading
import time
import urllib.parse
import webbrowser

import wx

from . import audiofile
from . import constants as C
from . import feedback
from . import dsp
from . import camera
from . import framing
from . import preflight
from . import proccapture
from . import screen
from . import secrets
from . import sources
from . import streamhelp
from . import streamout
from . import streamstats
from . import vst
from .micinput import input_devices
from .mixer import describe_device, output_devices
from .slot import format_duration

#: wx accelerator flags, which is also how custom hotkeys are stored on disk.
MOD_ALT = wx.ACCEL_ALT
MOD_CTRL = wx.ACCEL_CTRL
MOD_SHIFT = wx.ACCEL_SHIFT

_MODIFIER_KEYS = {wx.WXK_SHIFT, wx.WXK_CONTROL, wx.WXK_ALT,
                  wx.WXK_RAW_CONTROL, wx.WXK_WINDOWS_LEFT, wx.WXK_WINDOWS_RIGHT}

_NAMED_KEYS = {
    wx.WXK_SPACE: "Space", wx.WXK_RETURN: "Enter", wx.WXK_TAB: "Tab",
    wx.WXK_BACK: "Backspace", wx.WXK_DELETE: "Delete", wx.WXK_INSERT: "Insert",
    wx.WXK_HOME: "Home", wx.WXK_END: "End", wx.WXK_PAGEUP: "Page Up",
    wx.WXK_PAGEDOWN: "Page Down", wx.WXK_UP: "Up", wx.WXK_DOWN: "Down",
    wx.WXK_LEFT: "Left", wx.WXK_RIGHT: "Right",
}
for _n in range(1, 25):
    _NAMED_KEYS[getattr(wx, f"WXK_F{_n}")] = f"F{_n}"


class _Named(wx.Accessible):
    """An accessible object that exists to answer one question: what is this.

    Needed because SetName is NOT the accessible name on Windows. Measured,
    with deliberately different strings: a control with a static text in
    front of it reports the static text, and a control with only SetName
    reports nothing at all. See tools/check_labels.py.
    """

    def __init__(self, name):
        super().__init__()
        self._name = name

    def GetName(self, childId):
        # childId 0 is the control itself. Answering for every child would
        # make each part of a composite claim to be the whole thing, which is
        # how a list ends up reading every row as the name of the list.
        if childId == 0:
            return (wx.ACC_OK, self._name)
        return (wx.ACC_NOT_IMPLEMENTED, "")


def name_field(control, name):
    """Make a control say what it is, to a screen reader and not just to wx.

    A wx.SpinCtrlDouble is a native edit box and a pair of arrows inside a
    wrapper. Tab lands on the EDIT, and the edit has no static text in front
    of it inside that wrapper, so MSAA has nothing to offer and NVDA reads it
    as "edit" with no name at all. Tony, of the crossfade box beside the
    running order: "edit selected 3.0".

    So the edit gets an accessible object of its own.

    The object is stored on the control on purpose. wx does not take
    ownership, so an Accessible left as a local is collected the moment the
    function returns, and the control then reports an empty name: identical,
    from the outside, to never having been named. That cost an hour.
    """
    control.SetName(name)          # wx internal, for this codebase to read
    target = control
    for child in control.GetChildren():
        if isinstance(child, wx.TextCtrl):
            target = child
            break
    accessible = _Named(name)
    # Kept on the CONTROL, never on the child. GetChildren() hands back a
    # fresh Python wrapper every call, so an attribute set on the child is
    # set on a temporary that is discarded the moment this returns, and the
    # accessible goes with it. Same failure as leaving it in a local, one
    # level further down and twice as easy to miss.
    control._dropdeck_accessible = accessible
    target.SetAccessible(accessible)
    return control


def key_label(key_code, modifiers):
    """A readable name for a key combination, in the app's usual order."""
    if not key_code:
        return ""
    parts = []
    if modifiers & MOD_ALT:
        parts.append("Alt")
    if modifiers & MOD_CTRL:
        parts.append("Ctrl")
    if modifiers & MOD_SHIFT:
        parts.append("Shift")
    if key_code in _NAMED_KEYS:
        parts.append(_NAMED_KEYS[key_code])
    elif 32 < key_code < 127:
        parts.append(chr(key_code).upper())
    else:
        parts.append(f"key {key_code}")
    return "+".join(parts)


class AssignHotkeyDialog(wx.Dialog):
    """Press a combination; it becomes this slot's hotkey."""

    #: Keys this dialog will not capture, because binding one costs the user
    #: something they cannot get back from inside the app. Tab is the only way
    #: to move between buttons; Space and Enter are how you fire the focused
    #: one; Escape stops everything and closes dialogs.
    RESERVED = {wx.WXK_TAB, wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER,
                wx.WXK_ESCAPE}

    def __init__(self, parent, slot, taken=None, global_mode=False, initial=None):
        title = ("Assign global hotkey for %s" if global_mode
                 else "Assign hotkey for %s") % slot.display_name
        super().__init__(parent, title=title)
        self.global_mode = global_mode
        self._taken = taken or {}
        # `initial` overrides what the slot says, so the properties dialog can
        # open this twice and have the second visit remember the first. In
        # global mode it is the hotkey text; otherwise (key_code, modifiers).
        #
        # In global mode this is a *second*, separate key from the in-app one,
        # so it starts from the slot's global hotkey rather than its bank key.
        if global_mode:
            self._key_code, self._modifiers = None, 0
            current = (slot.global_hotkey if initial is None else initial) or "None"
        else:
            if initial is None:
                self._key_code = slot.key_code
                self._modifiers = slot.modifiers or 0
            else:
                self._key_code, self._modifiers = initial
            current = key_label(self._key_code, self._modifiers or 0) or "None"

        outer = wx.BoxSizer(wx.VERTICAL)
        if global_mode:
            explain = (
                "Press the key combination you want, then choose OK.\n"
                f"Current global hotkey: {current}\n\n"
                "A global hotkey fires this sound even when another program "
                "has focus, so it needs at least one modifier such as Ctrl or "
                "Alt. A key on its own would be taken away from everything "
                "else you are running.\n"
                "Alt counts as a modifier, so Alt plus a letter is fine. "
                "Press Delete to clear it. Tab reaches the buttons.")
        else:
            explain = ("Press the key combination you want, then choose OK.\n"
                       f"Current hotkey: {current}\n"
                       "Alt combinations are captured here, so use Tab to "
                       "reach the buttons. Press Delete to clear it.")
        outer.Add(wx.StaticText(self, label=explain), 0, wx.ALL, 10)

        # A real label in front of the readout. wx.SetName is not what MSAA
        # reads - the preceding static is - so without this the field the whole
        # dialog is about was announced with no name at all.
        outer.Add(wx.StaticText(self, label="Hotke&y"), 0,
                  wx.LEFT | wx.RIGHT, 10)
        self.readout = wx.TextCtrl(
            self, value=current, style=wx.TE_READONLY | wx.TE_CENTRE)
        outer.Add(self.readout, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.warning = wx.StaticText(self, label="")
        outer.Add(self.warning, 0, wx.ALL, 10)

        clear = wx.Button(self, label="&Clear hotkey")
        clear.SetToolTip("Remove the hotkey from this sound (Delete)")
        clear.Bind(wx.EVT_BUTTON, self._on_clear)
        outer.Add(clear, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        outer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)

        # CHAR_HOOK sees the keys before any control eats them, which is the
        # whole point here.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.readout.SetFocus()

    def _say(self, text):
        """Speak, because none of this dialog's feedback is in a control a
        screen reader announces on its own.

        The captured key goes into a read-only edit and the clash warning into
        a static text; neither fires an accessible event, so without this the
        dialog is silent about the only two things it has to tell you.
        """
        speaker = getattr(self.GetParent(), "speaker", None)
        if speaker is not None:
            speaker.say(text)

    def _on_key(self, event):
        code = event.GetKeyCode()
        if code in _MODIFIER_KEYS:
            return
        if code == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return

        # Whose keystroke this is. CHAR_HOOK sees everything before any
        # control does, which is what makes capturing hotkeys possible and
        # what made the buttons useless: Enter meant OK wherever you were
        # standing, so Enter on Cancel saved the hotkey you were cancelling,
        # and Space was refused as a reserved key so no button could be
        # pressed with it at all. On a button, Enter and Space belong to the
        # button.
        on_button = isinstance(wx.Window.FindFocus(), wx.Button)
        if on_button and code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER,
                                  wx.WXK_SPACE, wx.WXK_NUMPAD_SPACE):
            event.Skip()
            return

        modifiers = 0
        if event.AltDown():
            modifiers |= MOD_ALT
        if event.ControlDown():
            modifiers |= MOD_CTRL
        if event.ShiftDown():
            modifiers |= MOD_SHIFT

        # Let the dialog be worked with the keyboard. Nothing here swallowed
        # Tab or Alt before, which made Clear reachable only with a mouse - so
        # a hotkey, once set, could not be removed without one.
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not modifiers:
            self.EndModal(wx.ID_OK)
            return
        # Tab still reaches every button and Delete still clears, which is why
        # Alt no longer has to be handed to the buttons' mnemonics. It used to
        # be, and that made Alt+A - a perfectly good global hotkey - the one
        # combination this dialog could not capture. Alt is a modifier here.
        if code == wx.WXK_TAB:
            event.Skip()
            return
        if code in (wx.WXK_DELETE, wx.WXK_BACK) and not modifiers:
            self._on_clear(None)
            return
        # Alt+F4 closes a window in every Windows program. Taking it system-wide
        # would remove that from all of them, this app included.
        if (code == wx.WXK_F4 and event.AltDown()
                and not (event.ControlDown() or event.ShiftDown())):
            self.warning.SetLabel(
                "Alt+F4 closes a window in every program. Pick another "
                "combination, or press Escape to leave this one alone.")
            self._say(self.warning.GetLabel())
            return
        if code in self.RESERVED and not modifiers:
            self.warning.SetLabel(
                "%s on its own is needed to work the app. Add Ctrl, Alt or "
                "Shift." % key_label(code, 0))
            self._say(self.warning.GetLabel())
            return

        self._key_code = code
        self._modifiers = modifiers
        label = key_label(code, modifiers)
        self.readout.SetValue(label)

        if self.global_mode and modifiers == 0:
            self.warning.SetLabel(
                "A global hotkey needs a modifier. %s on its own would be "
                "taken from every other program." % label)
        else:
            clash = self._taken.get((code, modifiers))
            self.warning.SetLabel(
                f"Careful: {clash} already uses this." if clash else "")
        self._say((label + ". " + self.warning.GetLabel()).strip())

    def _on_clear(self, _event):
        self._key_code = None
        self._modifiers = 0
        self.readout.SetValue("None")
        self.warning.SetLabel("")
        self._say("Hotkey cleared.")

    @property
    def result(self):
        """(key_code, modifiers, label). label is None when cleared."""
        return self._key_code, self._modifiers, key_label(self._key_code, self._modifiers) or None

    def hotkey_text(self):
        """The combination as text, for a global hotkey.

        Global hotkeys are stored as a string rather than a wx key code and
        modifier mask, because Windows RegisterHotKey wants its own virtual key
        codes and the string is what survives a board file and reads out loud.
        """
        return key_label(self._key_code, self._modifiers) or ""


class SearchDialog(wx.Dialog):
    """Type a few letters, find the sound, jump to it or play it."""

    def __init__(self, parent, board, playing=(), on_play=None):
        super().__init__(parent, title="Search sounds",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.board = board
        self.playing = set(playing)
        self.chosen = None
        #: Kept as an attribute because callers used to read it. Nothing sets
        #: it True any more: playing happens through on_play, in place.
        self.play_now = False
        #: Called with a slot to play it without closing this dialog.
        self._on_play_slot = on_play

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label=(
            "Type to narrow the list. Down arrow moves into the results. "
            "Alt+P plays the one you are on and leaves this open, so you can "
            "try each match. Enter jumps to it and closes.")), 0, wx.ALL, 10)

        label = wx.StaticText(self, label="&Search")
        outer.Add(label, 0, wx.LEFT | wx.RIGHT, 10)
        self.query = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.query.SetName("Search")
        outer.Add(self.query, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        outer.Add(wx.StaticText(self, label="&Results"), 0, wx.LEFT | wx.RIGHT, 10)
        self.results = wx.ListBox(self, style=wx.LB_SINGLE)
        self.results.SetName("Results")
        outer.Add(self.results, 1, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.play_button = wx.Button(self, label="&Play")
        self.play_button.Bind(wx.EVT_BUTTON, self._on_play)
        row.Add(self.play_button, 0, wx.RIGHT, 6)
        jump = wx.Button(self, wx.ID_OK, "&Jump to it")
        # Bound explicitly. Without this, wxDialog's own ID_OK handler ends the
        # modal without recording a choice, so pressing Enter in the results
        # list - the way the instructions above tell you to use this dialog -
        # closed it and did nothing at all.
        jump.Bind(wx.EVT_BUTTON, lambda _e: self._accept(False))
        jump.SetDefault()
        row.Add(jump, 0, wx.RIGHT, 6)
        row.Add(wx.Button(self, wx.ID_CANCEL, "Cancel"), 0)
        outer.Add(row, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self.SetSizerAndFit(outer)
        self.SetSize((560, 460))

        self.query.Bind(wx.EVT_TEXT, self._on_filter)
        self.query.Bind(wx.EVT_TEXT_ENTER, lambda _e: self._accept(False))
        self.query.Bind(wx.EVT_KEY_DOWN, self._on_query_key)
        self.results.Bind(wx.EVT_LISTBOX_DCLICK, lambda _e: self._accept(False))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        self._matches = []
        self._refresh("")
        self.query.SetFocus()

    def _refresh(self, text, speak=False):
        self._matches = self.board.search(text)
        self.results.Set([s.search_label(s.index in self.playing) for s in self._matches])
        if self._matches:
            self.results.SetSelection(0)
        self.play_button.Enable(bool(self._matches))
        if speak:
            speaker = getattr(self.GetParent(), "speaker", None)
            if speaker is not None:
                # The count only ever appeared as a silently changing list, so
                # typing into this box gave a screen reader user nothing back -
                # and no matches at all was indistinguishable from a match.
                n = len(self._matches)
                speaker.say("No matches" if not n else
                            "%d match%s" % (n, "" if n == 1 else "es"),
                            interrupt=False)

    def _on_filter(self, _event):
        self._refresh(self.query.GetValue(), speak=True)

    def _on_query_key(self, event):
        if event.GetKeyCode() == wx.WXK_DOWN and self._matches:
            self.results.SetFocus()
            return
        event.Skip()

    def _on_char_hook(self, event):
        if event.AltDown() and event.GetKeyCode() in (ord("P"), ord("p")):
            self._on_play(None)
            return
        event.Skip()

    def _selected(self):
        index = self.results.GetSelection()
        if index == wx.NOT_FOUND or not self._matches:
            return None
        return self._matches[index]

    def _on_play(self, _event):
        """Play the highlighted match and stay put.

        The list is deliberately NOT relabelled afterwards. Its items carry the
        word "playing", and rewriting an item under a screen reader restarts
        the announcement on the row the user is standing on - the same trap as
        a pad's label. You can hear the sound; that is the feedback.
        """
        slot = self._selected()
        if slot is None or self._on_play_slot is None:
            return
        self._on_play_slot(slot)
        # Focus never left, but say so anyway: nothing visible changed, and a
        # button that appears to do nothing is the report this came from.
        self.results.SetFocus()

    def _accept(self, play_now=False):
        slot = self._selected()
        if slot is None:
            return
        self.chosen = slot
        self.play_now = bool(play_now)
        self.EndModal(wx.ID_OK)


class TrimDialog(wx.Dialog):
    """Level for one slot, so a single loud sound can be tamed on its own."""

    def __init__(self, parent, slot):
        super().__init__(parent, title=f"Level for {slot.display_name}")
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label=(
            "Adjust this one sound without touching the master volume.\n"
            "Zero leaves it as recorded.")), 0, wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="&Level in decibels"), 0, wx.LEFT, 10)
        self.slider = wx.Slider(self, value=int(round(slot.trim_db)), minValue=-24,
                                maxValue=12, style=wx.SL_HORIZONTAL)
        self.slider.SetName("Level in decibels")
        outer.Add(self.slider, 0, wx.EXPAND | wx.ALL, 10)

        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
                  0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)
        self.slider.SetFocus()


    @property
    def trim_db(self):
        return float(self.slider.GetValue())


class SlotPropertiesDialog(wx.Dialog):
    """Everything about one sound in one place, on Alt+Enter.

    Name, level, looping and both hotkeys. Before this they were four menu
    items and four separate dialogs, so "what is this pad actually set to"
    took four trips and never showed you two answers at once.

    Nothing is written to the slot here. The frame applies `result`, which is
    what makes Cancel genuinely leave the board alone.
    """

    def __init__(self, parent, slot, taken=None):
        super().__init__(parent, title="Properties for %s" % slot.display_name)
        self.slot = slot
        self._taken = taken or {}
        # The nested hotkey dialog speaks through its parent, and its parent
        # is this dialog rather than the frame. Without this it is silent
        # about the only thing it has to tell you - the key you just pressed.
        self.speaker = getattr(parent, "speaker", None)

        self._key_code = slot.key_code
        self._modifiers = slot.modifiers or 0
        self._global_hotkey = slot.global_hotkey or ""

        outer = wx.BoxSizer(wx.VERTICAL)

        def caption(text):
            # A real static in front of every control. wx.SetName is not what
            # MSAA reads - the preceding static is.
            outer.Add(wx.StaticText(self, label=text), 0,
                      wx.LEFT | wx.RIGHT | wx.TOP, 10)

        where = "%s, button %d." % (slot.bank_title, slot.number)
        if slot.hotkey_label:
            where += " Plays on %s." % slot.hotkey_label
        outer.Add(wx.StaticText(self, label=where), 0, wx.ALL, 10)

        caption("&Name")
        self.name_field = wx.TextCtrl(self, value=slot.display_name)
        self.name_field.SetName("Name")
        outer.Add(self.name_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        caption("&Level in decibels")
        self.level = wx.Slider(self, value=int(round(slot.trim_db)),
                               minValue=-24, maxValue=12, style=wx.SL_HORIZONTAL)
        self.level.SetName("Level in decibels")
        outer.Add(self.level, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Beds already toggle and always will, so this is offered to
        # everything else: the long file somebody only plays a bit of.
        self.toggle_box = None
        if not slot.is_bed:
            self.toggle_box = wx.CheckBox(
                self, label="Pressing its key &again stops it")
            self.toggle_box.SetValue(bool(slot.toggle_stop))
            self.toggle_box.SetToolTip(
                "Off, sounds pile up: press the key twice and you hear it "
                "twice, which is what a soundboard is for. On, the second "
                "press stops it, which is what you want for a long file you "
                "only play a bit of. Music beds always work this way.")
            outer.Add(self.toggle_box, 0, wx.ALL, 10)

        self.loop_box = None
        if slot.is_bed:
            self.loop_box = wx.CheckBox(self, label="Loop this &bed")
            self.loop_box.SetValue(bool(slot.loop))
            outer.Add(self.loop_box, 0, wx.ALL, 10)

        self.hotkey_readout = None
        if slot.bank == C.BANK_MISC:
            caption("Hotke&y, inside this app")
            self.hotkey_readout = self._readout(
                outer, key_label(self._key_code, self._modifiers) or "None",
                "Hotkey, inside this app")
            self._button(outer, "C&hoose a hotkey...", self._on_change_hotkey)

        caption("&Global hotkey, which works from any program")
        self.global_readout = self._readout(
            outer, self._global_hotkey or "None",
            "Global hotkey, which works from any program")
        self._button(outer, "Cho&ose a global hotkey...", self._on_change_global)

        caption("&File")
        self.file_readout = self._readout(outer, self._file_text(), "File")

        # Taking the slot off the board. Here as well as in the two menus,
        # because properties is where somebody looks for what a pad is and
        # whether it should be there at all. It is a request rather than the
        # deed: the frame does it, the same as everything else on this dialog,
        # which is what keeps Cancel meaning what it says.
        self.remove_wanted = False
        remove = wx.Button(self, label="Re&move this slot from the board")
        remove.SetToolTip(
            "Take this pad off the board. It keeps its sound and its keys, "
            "nothing else moves, and Sounds, Put a removed slot back brings "
            "it again.")
        remove.Bind(wx.EVT_BUTTON, self._on_remove)
        outer.Add(remove, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
                  0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)
        self.name_field.SetFocus()
        self.name_field.SelectAll()

    def _on_remove(self, _event):
        self.remove_wanted = True
        self.EndModal(wx.ID_OK)

    # ------------------------------------------------------------ building --
    def _readout(self, sizer, value, name=""):
        """A read-only field, so a screen reader can read a value it cannot
        otherwise reach and a mouse user can see one that would not fit.

        Named as well as captioned. The caption in front is what MSAA reads
        and it does work; the name is the belt to its braces, so tabbing onto
        this can never land on a box that says nothing at all.
        """
        ctrl = wx.TextCtrl(self, value=value, style=wx.TE_READONLY)
        if name:
            ctrl.SetName(name)
        sizer.Add(ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        return ctrl

    def _button(self, sizer, label, handler):
        button = wx.Button(self, label=label)
        button.Bind(wx.EVT_BUTTON, handler)
        sizer.Add(button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        return button

    def _file_text(self):
        if not self.slot.filepath:
            return "No sound assigned yet."
        text = self.slot.filepath
        if self.slot.is_missing:
            return text + "   (missing)"
        if self.slot.is_folder:
            n = self.slot.folder_count or 0
            return text + "   (folder, %s, one at random each press)" % (
                "1 sound" if n == 1 else "%d sounds" % n)
        duration = format_duration(self.slot.duration)
        return text + ("   (%s)" % duration if duration else "")

    def _say(self, text):
        if self.speaker is not None:
            self.speaker.say(text)

    # ------------------------------------------------------------- hotkeys --
    def _on_change_hotkey(self, _event):
        with AssignHotkeyDialog(self, self.slot, self._taken,
                                initial=(self._key_code, self._modifiers)) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self._key_code, self._modifiers, label = dialog.result
        self.hotkey_readout.SetValue(label or "None")
        self._say("Hotkey %s" % (label or "cleared"))

    def _on_change_global(self, _event):
        with AssignHotkeyDialog(self, self.slot, global_mode=True,
                                initial=self._global_hotkey) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self._global_hotkey = dialog.hotkey_text()
        self.global_readout.SetValue(self._global_hotkey or "None")
        self._say("Global hotkey %s" % (self._global_hotkey or "cleared"))

    # -------------------------------------------------------------- result --
    @property
    def result(self):
        """What the user chose, for the frame to apply."""
        return {
            "name": self.name_field.GetValue().strip(),
            "trim_db": float(self.level.GetValue()),
            "loop": None if self.loop_box is None else bool(self.loop_box.GetValue()),
            "toggle_stop": (None if self.toggle_box is None
                            else bool(self.toggle_box.GetValue())),
            "key_code": self._key_code,
            "modifiers": self._modifiers,
            "custom_hotkey": key_label(self._key_code, self._modifiers) or None,
            "global_hotkey": self._global_hotkey or None,
        }


class SettingsDialog(wx.Dialog):
    """Everything you can set, on seven tabs.

    It was one long column: output, routing, speech, ducking, bed fades,
    crossfade, and then the end of track beep on the end of that. Every
    setting the app has, in the order they happened to be added, with no way
    to find the one you came for except to read past all the others. The
    microphone had a dialog of its own on a different key, which meant two
    places to look and two things to remember.

    Tabs, and one dialog. `Ctrl+P` opens it on Output and `Ctrl+Shift+M` opens
    it on Microphone; they are the same window. Ctrl+Tab moves between the
    tabs, and a screen reader reads a tab name when you land on it, which is
    the whole reason this is a notebook rather than seven group boxes.
    """

    #: The tabs, in order. Named rather than numbered at the call sites, so
    #: adding one in the middle does not open the wrong page somewhere else.
    (PAGE_OUTPUT, PAGE_SOUND, PAGE_PLAYLIST, PAGE_MIC, PAGE_VOICE,
     PAGE_STREAM, PAGE_VIDEO, PAGE_RECORD, PAGE_SPEECH) = range(9)

    def __init__(self, parent, board, mixer, mic=None, page=None):
        super().__init__(parent, title="Preferences")
        self.board = board
        self.mixer = mixer
        self.mic = mic
        self.devices = output_devices()
        self.mic_devices = input_devices()

        outer = wx.BoxSizer(wx.VERTICAL)
        self.tabs = wx.Notebook(self)
        self.tabs.SetName("Settings")
        self._build_output_tab()
        self._build_sound_tab()
        self._build_playlist_tab()
        self._build_mic_tab()
        self._build_voice_tab()
        self._build_stream_tab()
        self._build_picture_tab()
        self._build_record_tab()
        self._build_speech_tab()
        outer.Add(self.tabs, 1, wx.EXPAND | wx.ALL, 8)

        self.status = wx.StaticText(self, label=self._status_text())
        outer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
                  0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)

        if page is not None:
            self.tabs.SetSelection(page)
        # Focus the first control on whichever tab opened, not the tab strip.
        # Landing on the tabs means one more keystroke before you can do the
        # thing you opened the window for.
        first = self._first_control()
        if first is not None:
            first.SetFocus()

    # ------------------------------------------------------------- helpers --
    def _page(self, title):
        """One tab: a panel, its sizer, and the tab added to the notebook."""
        panel = wx.Panel(self.tabs)
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(sizer)
        self.tabs.AddPage(panel, title)
        return panel, sizer

    @staticmethod
    def _label(panel, sizer, text):
        sizer.Add(wx.StaticText(panel, label=text), 0, wx.LEFT | wx.TOP, 10)

    @staticmethod
    def _note(panel, sizer, text):
        sizer.Add(wx.StaticText(panel, label=text), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 10)

    def _first_control(self):
        return {self.PAGE_OUTPUT: self.device,
                self.PAGE_SOUND: self.duck_on,
                self.PAGE_PLAYLIST: self.crossfade_ctrl,
                self.PAGE_MIC: self.mic_device,
                self.PAGE_VOICE: self.voice_list,
                self.PAGE_STREAM: self.stream_server,
                self.PAGE_VIDEO: self.video_server,
                self.PAGE_RECORD: self.record_format,
                self.PAGE_SPEECH: self.speech_choice}.get(
                    self.tabs.GetSelection())

    # ---------------------------------------------------------- the tabs ----
    def _build_output_tab(self):
        panel, sizer = self._page("Output")

        self._label(panel, sizer, "&Output device")
        self.choices = ["System default"] + [
            f"{d['name']}, {d['hostapi']}" for d in self.devices]
        self.device = wx.Choice(panel, choices=self.choices)
        self.device.SetName("Output device")
        self.device.SetSelection(self._current_selection())
        sizer.Add(self.device, 0, wx.EXPAND | wx.ALL, 10)

        self._note(panel, sizer,
                   "Pick a virtual cable here to feed a stream or a recorder\n"
                   "while you keep listening on your own speakers.")

        # Per-bank outputs.
        #
        # Sending beds to one card and drops to another lets a broadcaster
        # ride the balance on a physical desk instead of relying on the
        # automatic ducking. Both stay available; this is for people who would
        # rather decide the levels themselves.
        self._label(panel, sizer, "Send a bank to its own output")
        self._note(panel, sizer,
                   "Leave a bank on the main output unless you want it on a\n"
                   "separate channel of your mixer. Ducking still works\n"
                   "across outputs.")

        self.bank_choices = {}
        grid = wx.FlexGridSizer(C.BANK_COUNT, 2, 6, 10)
        grid.AddGrowableCol(1, 1)
        for bank in range(1, C.BANK_COUNT + 1):
            title = self.board.bank_name(bank)
            # The label is built BEFORE the choice, and the order matters.
            # MSAA gives a screen reader the static text that precedes a
            # control in creation order, so building the choice first labelled
            # every bank with the name of the bank above it: Dialog Drops
            # announced itself as "Sound Effects".
            grid.Add(wx.StaticText(panel, label=title), 0,
                     wx.ALIGN_CENTER_VERTICAL)
            choice = wx.Choice(panel, choices=["Main output"] + self.choices[1:])
            # Named for the screen reader, because four identical unlabelled
            # dropdowns in a column are indistinguishable by ear.
            choice.SetName(f"{title} output")
            choice.SetSelection(self._bank_selection(bank))
            self.bank_choices[bank] = choice
            grid.Add(choice, 1, wx.EXPAND)
        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

    def _build_sound_tab(self):
        panel, sizer = self._page("Sounds and beds")

        self.duck_on = wx.CheckBox(
            panel, label="&Duck the music beds under sounds and drops")
        self.duck_on.SetValue(bool(self.board.ducking))
        sizer.Add(self.duck_on, 0, wx.ALL, 10)

        self._label(panel, sizer, "&Presses of Escape to stop everything")
        self.stop_presses = wx.SpinCtrl(
            panel, min=C.MIN_STOP_PRESSES, max=C.MAX_STOP_PRESSES,
            initial=int(getattr(self.board, "stop_presses",
                                C.DEFAULT_STOP_PRESSES)))
        name_field(self.stop_presses, "Presses of Escape to stop everything")
        self.stop_presses.SetToolTip(
            "More than one, because a single key that silences a live show is "
            "a single key away from silencing it by accident. One is allowed "
            "if you would rather. Ctrl+Space stops only the last sound, and "
            "always takes one press.")
        sizer.Add(self.stop_presses, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.stop_fade = wx.CheckBox(
            panel, label="Fade out &when stopping, instead of cutting")
        self.stop_fade.SetValue(bool(getattr(self.board, "stop_fade", True)))
        self.stop_fade.SetToolTip(
            "A quarter of a second, so a stop does not click. Turn it off for "
            "an instant cut, which is what you want if you are riding a mixer "
            "or a fader in a DAW.")
        sizer.Add(self.stop_fade, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self._label(panel, sizer, "Duck depth in de&cibels")
        self.duck_db = wx.Slider(panel, value=int(round(self.board.duck_db)),
                                 minValue=-24, maxValue=0,
                                 style=wx.SL_HORIZONTAL)
        self.duck_db.SetName("Duck depth in decibels")
        sizer.Add(self.duck_db, 0, wx.EXPAND | wx.ALL, 10)

        # The slider was fully draggable while ducking was switched off: a
        # control that looks alive and does nothing.
        self.duck_db.Enable(self.duck_on.GetValue())
        self.duck_on.Bind(
            wx.EVT_CHECKBOX,
            lambda e: (self.duck_db.Enable(e.IsChecked()), e.Skip()))

        # How a bed enters and leaves.
        #
        # Brian Hartgen, on 2.2.1: a bed that eases in cannot be used on air.
        # He cues a bed on its first beat, and 350 ms of ramp eats exactly the
        # thing he cued. It was a constant; it is a setting now, zero
        # included, because "play it as it was recorded" is a legitimate
        # answer and there was no way to ask for it.
        self._label(panel, sizer, "Music bed fades, in seconds")
        self._note(panel, sizer,
                   "Zero starts and stops a bed exactly where the file does.\n"
                   "Sounds and drops are unaffected; they have never faded.")

        grid = wx.FlexGridSizer(2, 2, 6, 10)
        self.fade_in_ctrl = self._fade_spin(
            panel, grid, "Fade beds &in, seconds", "Bed fade in, seconds",
            getattr(self.board, "bed_fade_in", C.FADE_IN_BED),
            "How long a bed takes to reach full level. Zero means it starts "
            "at full level on its first sample.")
        self.fade_out_ctrl = self._fade_spin(
            panel, grid, "Fade beds ou&t, seconds", "Bed fade out, seconds",
            getattr(self.board, "bed_fade_out", C.FADE_OUT_BED),
            "How long a bed takes to fall away when you stop it. Escape "
            "still stops everything quickly, whatever this says.")
        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

    def _build_playlist_tab(self):
        panel, sizer = self._page("Playlist")

        # The crossfade also has a box under the running order, where it is
        # used most, but somebody looking for "how long do songs overlap"
        # looks in settings. Two views of one number.
        self._label(panel, sizer, "Crossfade")
        self._note(panel, sizer,
                   "How long one song overlaps the next. The next song starts\n"
                   "this many seconds before the one playing ends, so every\n"
                   "start time in the running order moves when you change it.\n"
                   "Zero means each song plays right out before the next.")

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(panel, label="Cross&fade, seconds"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.crossfade_ctrl = wx.SpinCtrlDouble(
            panel, min=0.0, max=C.MAX_CROSSFADE, inc=0.5,
            initial=float(getattr(self.board.playlist, "crossfade",
                                  C.DEFAULT_CROSSFADE)))
        self.crossfade_ctrl.SetDigits(1)
        name_field(self.crossfade_ctrl, "Playlist crossfade, seconds")
        self.crossfade_ctrl.SetToolTip(
            "The same box that sits under the running order. A single track "
            "can be given a crossfade of its own from its right-click menu.")
        row.Add(self.crossfade_ctrl, 0)
        sizer.Add(row, 0, wx.ALL, 10)

        # The end of track cue. A sighted presenter watches a clock count
        # down; this is that clock, for anybody who cannot.
        self._label(panel, sizer, "Before a track ends")
        self._note(panel, sizer,
                   "A short beep to tell you a playlist track is nearly over,\n"
                   "so you know when to be ready. You hear it wherever you\n"
                   "hear yourself, set on the Microphone tab, so with\n"
                   "headphones set up there it stays out of the show.")

        self.warn_on = wx.CheckBox(
            panel, label="&Beep before a playlist track ends")
        self.warn_on.SetName("Beep before a playlist track ends")
        self.warn_on.SetValue(bool(getattr(self.board, "warn_before_end",
                                           C.DEFAULT_WARN_BEFORE_END)))
        sizer.Add(self.warn_on, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        warn_row = wx.BoxSizer(wx.HORIZONTAL)
        warn_row.Add(wx.StaticText(panel, label="How &many seconds before"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.warn_seconds_ctrl = wx.SpinCtrl(
            panel, min=int(C.MIN_WARN_SECONDS), max=int(C.MAX_WARN_SECONDS),
            initial=int(round(getattr(self.board, "warn_seconds",
                                      C.DEFAULT_WARN_SECONDS))))
        name_field(self.warn_seconds_ctrl, "Seconds before the end to beep")
        self.warn_seconds_ctrl.SetToolTip(
            "How long before a track's music stops the beep sounds. Ten is a "
            "usual answer. Nothing shorter than this plus a second gets one, "
            "so a short ident does not beep the moment it starts.")
        warn_row.Add(self.warn_seconds_ctrl, 0)
        sizer.Add(warn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Which sound, and how loud. Both play as you change them, because
        # the only useful answer to "is this loud enough over a song" is
        # hearing it, and a picker you have to close the window to audition
        # is a picker nobody adjusts twice.
        sound_row = wx.BoxSizer(wx.HORIZONTAL)
        sound_row.Add(wx.StaticText(panel, label="Which s&ound"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.cue_sound = wx.Choice(
            panel, choices=[label for _key, label in C.CUE_SOUNDS])
        name_field(self.cue_sound, "Which sound")
        current = getattr(self.board, "cue_sound", C.DEFAULT_CUE_SOUND)
        self.cue_sound.SetSelection(
            C.CUE_SOUND_KEYS.index(current)
            if current in C.CUE_SOUND_KEYS else 0)
        self.cue_sound.SetToolTip(
            "Each one is a different shape rather than a different note, so "
            "you can tell them apart over music. You hear each as you "
            "choose it.")
        self.cue_sound.Bind(wx.EVT_CHOICE, self._on_cue_changed)
        sound_row.Add(self.cue_sound, 1, wx.EXPAND | wx.RIGHT, 8)
        try_it = wx.Button(panel, label="&Hear it")
        try_it.Bind(wx.EVT_BUTTON, self._on_cue_changed)
        sound_row.Add(try_it, 0)
        sizer.Add(sound_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self._label(panel, sizer, "How &loud the warning is, in decibels")
        # No SL_LABELS. That style builds the slider's own min, max and value
        # statics as children, and MSAA hands a screen reader the last static
        # created before the control: with it on, this announced itself as
        # "-6". The value is read out as you move it anyway, which is the
        # part that matters.
        self.cue_level = wx.Slider(
            panel, value=int(round(getattr(self.board, "cue_level_db",
                                           C.CUE_LEVEL_DB))),
            minValue=int(C.MIN_CUE_LEVEL_DB), maxValue=int(C.MAX_CUE_LEVEL_DB),
            style=wx.SL_HORIZONTAL)
        self.cue_level.SetName("How loud the warning is, in decibels")
        self.cue_level.SetToolTip(
            "Zero is as loud as it goes. The warning is a cue for you, not "
            "part of the show, so it never reaches the stream.")
        self.cue_level.Bind(wx.EVT_SCROLL_CHANGED, self._on_cue_changed)
        self.cue_level.Bind(wx.EVT_SLIDER, self._on_cue_changed)
        sizer.Add(self.cue_level, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                  10)

        for control in (self.warn_seconds_ctrl, self.cue_sound, try_it,
                        self.cue_level):
            control.Enable(self.warn_on.GetValue())
        self._warn_controls = (self.warn_seconds_ctrl, self.cue_sound, try_it,
                               self.cue_level)
        self.warn_on.Bind(wx.EVT_CHECKBOX, self._on_warn_toggled)

    def _on_warn_toggled(self, event):
        for control in getattr(self, "_warn_controls", ()):
            control.Enable(event.IsChecked())
        event.Skip()

    @property
    def cue_sound_key(self):
        return C.CUE_SOUND_KEYS[max(0, self.cue_sound.GetSelection())]

    @property
    def cue_level_db(self):
        return float(self.cue_level.GetValue())

    def _on_cue_changed(self, event=None):
        """Play the cue as it is chosen, out of the monitor, as it will be."""
        mixer = getattr(self.GetParent(), "mixer", None)
        if mixer is not None:
            try:
                mixer.play_cue(self.cue_sound_key, self.cue_level_db)
            except Exception:
                pass
        if event is not None:
            event.Skip()

    def _build_mic_tab(self):
        panel, sizer = self._page("Microphone")

        self._label(panel, sizer, "&Microphone")
        self.mic_choices = ["System default"] + [
            "%s - %s" % (d["name"], d["hostapi"]) for d in self.mic_devices]
        self.mic_device = wx.Choice(panel, choices=self.mic_choices)
        self.mic_device.SetName("Microphone")
        self.mic_device.SetSelection(self._mic_selection())
        sizer.Add(self.mic_device, 0, wx.EXPAND | wx.ALL, 10)

        self._note(panel, sizer,
                   "Ctrl+M turns the microphone on and off. While it is on,\n"
                   "the beds and the playlist duck out of the way, and they\n"
                   "come back up the moment you turn it off.")

        # Which side of a stereo input the voice is on. A headset is mono
        # and this never matters; a hardware mixer feeding a line input puts
        # the voice on one channel, and taking the other one is silence.
        # JamminJerry, 4 September 2026: "I can't get my microphone from my
        # mixer on the air though."
        self._label(panel, sizer, "Which &channel the voice is on")
        self.mic_channel = wx.Choice(
            panel, choices=["Both, mixed together", "Left only", "Right only"])
        name_field(self.mic_channel, "Which channel the voice is on")
        self.mic_channel.SetSelection(
            {"mix": 0, "left": 1, "right": 2}.get(
                getattr(self.board, "mic_channel", "mix"), 0))
        self.mic_channel.SetToolTip(
            "Only matters for a stereo input, such as a hardware mixer on a "
            "line in. If you can see the level moving but hear nothing, this "
            "is usually why.")
        sizer.Add(self.mic_channel, 0, wx.EXPAND | wx.ALL, 10)

        self._label(panel, sizer, "&Gain in decibels")
        self.mic_gain = wx.Slider(
            panel, value=int(round(self.board.mic_gain_db)),
            minValue=int(C.MIN_MIC_GAIN_DB), maxValue=int(C.MAX_MIC_GAIN_DB),
            style=wx.SL_HORIZONTAL)
        self.mic_gain.SetName("Microphone gain in decibels")
        self.mic_gain.SetToolTip(
            "Zero is the microphone as Windows gives it to us. Raise it for a "
            "quiet headset, lower it for a hot one.")
        sizer.Add(self.mic_gain, 0, wx.EXPAND | wx.ALL, 10)

        self._label(panel, sizer, "Hear yourself thr&ough")
        self.monitor_choices = ["Same as the soundboard"] + [
            "%s - %s" % (d["name"], d["hostapi"]) for d in self.devices]
        self.mic_output = wx.Choice(panel, choices=self.monitor_choices)
        # The same words as the label in front of it, which is what a
        # screen reader actually reads. Two names for one control is
        # how a codebase loses track of what a listener hears.
        self.mic_output.SetName("Hear yourself through")
        self.mic_output.SetSelection(self._monitor_selection())
        self.mic_output.SetToolTip(
            "Put monitoring on your headphones and leave the show on the main "
            "output. The beep before a track ends comes out here too.")
        sizer.Add(self.mic_output, 0, wx.EXPAND | wx.ALL, 10)

        self.mic_monitor = wx.CheckBox(
            panel, label="&Hear yourself through the output (headphones only)")
        self.mic_monitor.SetValue(bool(self.board.mic_monitor))
        self.mic_monitor.SetToolTip(
            "On headphones this is how you know you are live. On speakers it "
            "is a feedback loop, which is why it is off to begin with.")
        sizer.Add(self.mic_monitor, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        sizer.Add(wx.StaticText(panel, label=self._mic_status_text()), 0,
                  wx.ALL, 10)

    def _build_voice_tab(self):
        """The microphone chain, as a list rather than a wall of knobs.

        Every processor here has four or five numbers, and laid out as
        controls that is thirty boxes to tab past to reach the one you want.
        As a list it is one thing to arrow down and one thing to arrow across,
        which is both faster to use and far less to hear.

        The same list shows a VST3 plugin's parameters, because a plugin
        describes its knobs in exactly the same terms. A plugin whose window
        no screen reader can read becomes a list that any screen reader can.
        """
        panel, sizer = self._page("Voice")
        self.chain = getattr(self.mic, "chain", None) if self.mic else None
        # Everything on this tab changes the chain that is RUNNING, because a
        # compressor you cannot hear while you set it is a compressor set by
        # guesswork. That makes Cancel a promise this has to keep, so the
        # whole state is written down here and put back if Cancel is what
        # gets pressed.
        self._voice_before = None
        if self.chain is not None:
            self._voice_before = {
                "settings": dict(self.chain.settings),
                "enabled": bool(self.chain.enabled),
                "plugin": self.chain.plugin,
                "plugin_path": self.chain.plugin_path,
                "plugin_values": self.chain.plugin_values(),
            }

        if not dsp.available():
            self._note(panel, sizer,
                       "Voice processing is not installed in this copy.")
            self.voice_list = wx.ListCtrl(panel, style=wx.LC_REPORT)
            self.voice_list.SetName("Voice processing")
            sizer.Add(self.voice_list, 1, wx.EXPAND | wx.ALL, 10)
            return

        self.voice_on = wx.CheckBox(
            panel, label="Process the &microphone")
        self.voice_on.SetValue(bool(self.chain.enabled) if self.chain else True)
        self.voice_on.SetToolTip(
            "Off passes your voice through untouched. The quickest way to "
            "hear what the chain is doing is to turn it off and on while you "
            "talk.")
        # Live, like everything else on this tab. It used to wait for OK,
        # which made the one control whose whole purpose is an A against a B
        # the one control you could not hear.
        self.voice_on.Bind(wx.EVT_CHECKBOX, self._on_voice_enabled)
        sizer.Add(self.voice_on, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self._label(panel, sizer, "&Settings")
        self.voice_list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
            size=(-1, 260))
        self.voice_list.SetName("Voice processing settings")
        self.voice_list.InsertColumn(0, "Setting", width=260)
        self.voice_list.InsertColumn(1, "Value", width=140)
        self.voice_list.SetToolTip(
            "Up and down to choose a setting, left and right to change it. "
            "Hold shift with left or right for a bigger step.")
        self.voice_list.Bind(wx.EVT_KEY_DOWN, self._on_voice_key)
        sizer.Add(self.voice_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self._note(panel, sizer,
                   "Left and right change the setting you are on. Hold shift "
                   "for a bigger step.")

        row = wx.BoxSizer(wx.HORIZONTAL)
        self._label(panel, sizer, "&Plugin")
        self._plugin_paths = [None] + [path for _name, path in vst.installed()]
        names = ["None"] + [name for name, _path in vst.installed()]
        self.voice_plugin = wx.Choice(panel, choices=names)
        name_field(self.voice_plugin, "Plugin")
        # By PATH, not by name. Two plugins can share a name, and the one that
        # is loaded is the one on disk at that path.
        loaded = getattr(self.chain, "plugin_path", None) if self.chain else None
        self.voice_plugin.SetSelection(
            self._plugin_paths.index(loaded)
            if loaded in self._plugin_paths else 0)
        self.voice_plugin.SetToolTip(
            "A VST3 effect, added after the compressor and before the "
            "limiter. Its own window is never opened; its settings appear in "
            "the list above.")
        self.voice_plugin.Bind(wx.EVT_CHOICE, self._on_voice_plugin)
        row.Add(self.voice_plugin, 1, wx.EXPAND | wx.RIGHT, 8)
        save = wx.Button(panel, label="Save prese&t...")
        save.Bind(wx.EVT_BUTTON, self._on_voice_save_preset)
        row.Add(save, 0, wx.RIGHT, 8)
        load = wx.Button(panel, label="Open p&reset...")
        load.Bind(wx.EVT_BUTTON, self._on_voice_load_preset)
        row.Add(load, 0)
        sizer.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self._refresh_voice()

    # ------------------------------------------------------------- voice --
    def _voice_parameters(self):
        """The chain's own settings, then the plugin's, in one list."""
        if self.chain is None:
            return []
        params = list(self.chain.parameters())
        # Through the chain, so every read and write of a plugin parameter is
        # taken under the same lock the audio thread uses.
        params.extend(self.chain.plugin_parameters())
        return params

    def _refresh_voice(self, keep=0):
        if self.chain is None:
            return
        self._voice_params = self._voice_parameters()
        self.voice_list.DeleteAllItems()
        for row, param in enumerate(self._voice_params):
            self.voice_list.InsertItem(row, param.label)
            self.voice_list.SetItem(row, 1, param.spoken())
        if self._voice_params:
            keep = max(0, min(keep, len(self._voice_params) - 1))
            self.voice_list.Select(keep)
            self.voice_list.Focus(keep)

    def _on_voice_key(self, event):
        """Left and right adjust; everything else is the list's own."""
        key = event.GetKeyCode()
        # Page up and page down are left alone, because in a list of sixty
        # settings they are how you get around, and taking them to mean
        # "bigger step" costs more than it gives. Shift with an arrow is the
        # bigger step instead, on the same axis as the ordinary one.
        steps = {wx.WXK_LEFT: -1, wx.WXK_RIGHT: 1}.get(key)
        if steps is None:
            event.Skip()
            return
        if event.ShiftDown():
            steps *= 10
        row = self.voice_list.GetFirstSelected()
        if row < 0 or row >= len(getattr(self, "_voice_params", [])):
            event.Skip()
            return
        param = self._voice_params[row]
        param.nudge(steps)
        self.voice_list.SetItem(row, 1, param.spoken())
        # Spoken as an answer, because the list will not say a value that
        # changed under it and this is the whole point of the screen.
        self._say_voice(param.describe())

    def _on_voice_enabled(self, _event):
        if self.chain is None:
            return
        self.chain.enabled = self.voice_on.GetValue()
        self._say_voice("Processing on" if self.chain.enabled
                        else "Processing off. The settings below are kept.")

    def _say_voice(self, text):
        frame = self.GetParent()
        speak = getattr(frame, "announce_answer", None)
        if speak is not None:
            speak(text)

    def _on_voice_plugin(self, _event):
        """Load, or unload, the VST3 in the chain."""
        if self.chain is None:
            return
        picked = self.voice_plugin.GetSelection()
        choice = self.voice_plugin.GetStringSelection()
        path = (self._plugin_paths[picked]
                if 0 <= picked < len(self._plugin_paths) else None)
        if path is None:
            self.chain.set_plugin(None)
            self._refresh_voice()
            self._say_voice("No plugin")
            return
        wx.BeginBusyCursor()
        try:
            plugin = vst.load(path)
        except vst.LoadFailed as exc:
            self._say_voice(str(exc))
            self.voice_plugin.SetSelection(0)
            return
        finally:
            wx.EndBusyCursor()
        self.chain.set_plugin(plugin, path)
        self._refresh_voice()
        self._say_voice("%s loaded, %d settings"
                        % (choice, len(self.chain.plugin_parameters())))

    def _on_voice_save_preset(self, _event):
        plugin = getattr(self.chain, "plugin", None) if self.chain else None
        if plugin is None:
            self._say_voice("Load a plugin first")
            return
        with wx.FileDialog(self, "Save this plugin's settings",
                           wildcard="Drop Deck preset (*.json)|*.json",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            vst.save_preset(plugin, path, lock=self.chain._lock)
        except OSError as exc:
            self._say_voice("Could not save it: %s" % exc)
            return
        self._say_voice("Saved")

    def _on_voice_load_preset(self, _event):
        plugin = getattr(self.chain, "plugin", None) if self.chain else None
        if plugin is None:
            self._say_voice("Load a plugin first")
            return
        with wx.FileDialog(self, "Open a preset",
                           wildcard="Drop Deck preset (*.json)|*.json",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            restored = vst.load_preset(plugin, path,
                                       lock=self.chain._lock)
        except (OSError, ValueError) as exc:
            self._say_voice("Could not open it: %s" % exc)
            return
        self._refresh_voice(self.voice_list.GetFirstSelected())
        self._say_voice("%d settings restored" % restored)

    def restore_stream(self):
        """Put the board's live stream settings back, as Cancel promises."""
        before = getattr(self, "_stream_before", None)
        if not before:
            return False
        changed = any(getattr(self.board, field) != value
                      for field, value in before.items())
        for field, value in before.items():
            setattr(self.board, field, value)
        return changed

    def restore_voice(self):
        """Put the voice chain back the way this window found it.

        Called when the window is cancelled. Every other tab collects its
        answers and hands them over on OK, so cancelling them costs nothing;
        this one has been changing the live chain all along so that the
        presenter can hear what they are doing, and without this Cancel meant
        "keep the changes but do not save them", which is the worst of both.
        """
        before = getattr(self, "_voice_before", None)
        if before is None or self.chain is None:
            return False
        changed = (dict(self.chain.settings) != before["settings"]
                   or bool(self.chain.enabled) != before["enabled"]
                   or self.chain.plugin is not before["plugin"])
        self.chain.enabled = before["enabled"]
        self.chain.update(before["settings"])
        if self.chain.plugin is not before["plugin"]:
            self.chain.set_plugin(before["plugin"], before["plugin_path"])
        if before["plugin"] is not None and before["plugin_values"]:
            try:
                vst.apply(before["plugin"], before["plugin_values"],
                          self.chain._lock)
            except Exception:
                pass
        return changed

    def _build_stream_tab(self):
        """Where the show goes, and a button that proves it before air.

        Every field here is one somebody has to be told by whoever runs the
        server, so the labels use the words a station uses rather than the
        words the protocol uses. The Test button exists because the only
        moment a broadcaster finds out a password is wrong should not be the
        moment the show starts.
        """
        panel, sizer = self._page("Audio streaming")

        # More than one station, because Tony runs two and retyping an
        # address, a mount and a password to move between them is the kind of
        # friction that means you stop bothering.
        self._label(panel, sizer, "&Saved stations")
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.stream_picker = wx.Choice(panel, choices=self._station_choices())
        self.stream_picker.SetName("Saved stations")
        self.stream_picker.SetToolTip(
            "Pick one to load its settings. Save this station remembers "
            "whatever is in the boxes below under the station name.")
        self.stream_picker.Bind(wx.EVT_CHOICE, self._on_pick_station)
        row.Add(self.stream_picker, 1, wx.EXPAND | wx.RIGHT, 8)
        save = wx.Button(panel, label="Sa&ve this station")
        save.Bind(wx.EVT_BUTTON, self._on_save_station)
        row.Add(save, 0, wx.RIGHT, 8)
        forget = wx.Button(panel, label="For&get it")
        forget.Bind(wx.EVT_BUTTON, self._on_forget_station)
        row.Add(forget, 0)
        sizer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        grid = wx.FlexGridSizer(2, 8, 12)
        grid.AddGrowableCol(1, 1)

        def field(label, build, name, tip=""):
            """A labelled box. The LABEL IS BUILT FIRST, and that matters.

            MSAA gives a screen reader the static text that precedes a control
            in creation order, which is the order things were constructed and
            not the order they were added to the sizer. Building the control
            first and the label after labels every field with the one above
            it: NVDA read this tab's password box as "User name" and its
            format box as "Password".

            It takes a function rather than a finished control so that it
            cannot be called the wrong way round again.
            """
            grid.Add(wx.StaticText(panel, label=label), 0,
                     wx.ALIGN_CENTER_VERTICAL)
            control = build()
            # name_field rather than SetName: a spin control's edit box needs
            # an accessible object of its own, and SetName is not the
            # accessible name on Windows.
            name_field(control, name)
            if tip:
                control.SetToolTip(tip)
            grid.Add(control, 0, wx.EXPAND)
            return control

        self.stream_server = field(
            "Se&rver",
            lambda: wx.Choice(panel, choices=[
                streamout.server_label(key) for key in C.STREAM_SERVER_ORDER]),
            "Server type",
            "Icecast covers almost everything, including the Liquidsoap "
            "harbor a station puts in front of it so a presenter can take "
            "over from the automation.")
        self.stream_server.SetSelection(
            C.STREAM_SERVER_ORDER.index(self.board.stream_server)
            if self.board.stream_server in C.STREAM_SERVER_ORDER else 0)

        self.stream_host = field(
            "A&ddress",
            lambda: wx.TextCtrl(panel, value=self.board.stream_host),
            "Address",
            "The name of the server, with no http in front of it.")

        self.stream_port = field(
            "&Port",
            lambda: wx.SpinCtrl(panel, min=1, max=65535,
                                initial=int(self.board.stream_port)),
            "Port",
            "The port listeners use. For SHOUTcast this is still the "
            "listening port; the app adds the one it needs for a source.")

        self.stream_mount = field(
            "&Mount point",
            lambda: wx.TextCtrl(panel, value=self.board.stream_mount),
            "Mount point",
            "The part after the address, such as /live. SHOUTcast does not "
            "use one.")

        self.stream_user = field(
            "&User name",
            lambda: wx.TextCtrl(panel, value=self.board.stream_user),
            "User name",
            "Almost always source. SHOUTcast ignores it.")

        self.stream_password = field(
            "Pass&word",
            lambda: wx.TextCtrl(panel, value=self.board.stream_password,
                                style=wx.TE_PASSWORD),
            "Password",
            "The source password for the server, not your listener password.")

        self.stream_format = field(
            "&Format",
            lambda: wx.Choice(panel, choices=[
                streamout.FORMATS[key]["label"]
                for key in C.STREAM_FORMAT_ORDER]),
            "Format",
            "MP3 plays everywhere. AAC sounds better for the same bandwidth "
            "and is what a lot of stations use. Ogg Opus is better again, if "
            "your server and your listeners take it.")
        self.stream_format.SetSelection(
            C.STREAM_FORMAT_ORDER.index(self.board.stream_format)
            if self.board.stream_format in C.STREAM_FORMAT_ORDER else 0)

        self.stream_bitrate = field(
            "&Bitrate",
            lambda: wx.Choice(panel, choices=[
                "%d kbps" % rate for rate in C.STREAM_BITRATES]),
            "Bitrate",
            "128 is plenty for speech and music together. Higher costs your "
            "listeners more data and your server more bandwidth.")
        self.stream_bitrate.SetSelection(
            C.STREAM_BITRATES.index(self.board.stream_bitrate)
            if self.board.stream_bitrate in C.STREAM_BITRATES else 2)

        self.stream_name = field(
            "Statio&n name",
            lambda: wx.TextCtrl(panel, value=self.board.stream_name),
            "Station name",
            "What listeners see as the name of the stream.")

        self.stream_stats = field(
            "Where listeners &connect",
            lambda: wx.TextCtrl(panel,
                                value=self.board.stream_stats_url),
            "Where listeners connect",
            "Only if your listeners are somewhere other than the address "
            "above, which they are whenever you stream into automation. "
            "Leave it empty and Drop Deck looks in the usual places.")

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        # Check boxes carry their own label, so nothing above can steal it.
        # Their access keys still have to be unique: i did two jobs here.
        self.stream_mic = wx.CheckBox(
            panel, label="Put the m&icrophone on air")
        self.stream_mic.SetValue(bool(self.board.stream_mic))
        self.stream_mic.SetToolTip(
            "Separate from hearing yourself. With this on you go out live "
            "whenever the microphone is open, whether or not you are "
            "monitoring, which is the normal way to work on speakers.")
        sizer.Add(self.stream_mic, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # The dialog itself carries a "do not ask again", so without this
        # that would be a one way door: no way back to the summary short of
        # editing the board file.
        self.ask_before_live = wx.CheckBox(
            panel, label="S&ay what is going out before Ctrl+B goes live")
        self.ask_before_live.SetValue(bool(self.board.ask_before_live))
        self.ask_before_live.SetToolTip(
            "Ctrl+B says where the show is going, what it is sending and "
            "whether your microphone is on the air, and waits for Enter. "
            "Turn it off and Ctrl+B goes straight on the air; Ctrl+Shift+B "
            "still answers at any time.")
        sizer.Add(self.ask_before_live, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.stream_titles = wx.CheckBox(
            panel, label="Send the track &title to the server")
        self.stream_titles.SetValue(bool(self.board.stream_titles))
        self.stream_titles.SetToolTip(
            "Listeners see the artist and title of whatever the playlist is "
            "playing, taken from the file.")
        sizer.Add(self.stream_titles, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.playlist_monitor_only = wx.CheckBox(
            panel, label="F7 and F8 change what I &hear, not what goes out")
        self.playlist_monitor_only.SetValue(
            bool(self.board.playlist_monitor_only))
        self.playlist_monitor_only.SetToolTip(
            "On, the playlist fader is a monitor control: turn the music down "
            "to hear your screen reader and listeners still get it at full "
            "level. Off, it is an ordinary fader and what you hear is what "
            "goes out.")
        sizer.Add(self.playlist_monitor_only, 0, wx.LEFT | wx.RIGHT | wx.TOP,
                  10)

        self.stream_public = wx.CheckBox(
            panel, label="&List this stream in public directories")
        self.stream_public.SetValue(bool(self.board.stream_public))
        sizer.Add(self.stream_public, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        test = wx.Button(panel, label="T&est the connection")
        test.SetToolTip(
            "Connects, says what happened, and disconnects again. Nothing is "
            "broadcast.")
        test.Bind(wx.EVT_BUTTON, self._on_test_stream)
        sizer.Add(test, 0, wx.ALL, 10)

        self._label(panel, sizer, "Test result")
        self.stream_result = wx.TextCtrl(
            panel, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 60),
            value="Not tested yet.")
        self.stream_result.SetName("Test result")
        # Choosing a saved station fills these boxes by loading it INTO the
        # board, so without this Cancel left the board on whichever station
        # was last clicked. Saving or forgetting a station is a deliberate
        # act and stays; which one is current does not.
        # What Cancel restores. The picture fields are in here as well as the
        # stream ones, because picking a station assigns ALL of
        # STATION_FIELDS: without them, clicking a station and then Cancel
        # said "Nothing changed" and left the board pointing at another
        # station's camera, which the next Ctrl+B would then open.
        self._stream_before = {field: getattr(self.board, field)
                               for field in self._stream_controls()}
        self._stream_before.update({
            field: getattr(self.board, field)
            for field in ("picture", "picture_file", "picture_clock",
                          "camera", "video_width", "video_height",
                          "video_fps", "video_bitrate", "video_server",
                          "video_host", "video_key", "live_to")})
        sizer.Add(self.stream_result, 0, wx.EXPAND | wx.LEFT | wx.RIGHT
                  | wx.BOTTOM, 10)
        self._refresh_stations()

    # ------------------------------------------------- RTMP and Icecast --
    def _current_server(self):
        return C.STREAM_SERVER_ORDER[max(0, self.stream_server.GetSelection())]

    def _loaded_key(self):
        """The saved stream key for the current station, if there is one."""
        try:
            return secrets.fetch(self.board.stream_name or "")
        except Exception:
            return ""

    # ------------------------------------------------------ the video side --
    def _current_platform(self):
        return C.VIDEO_SERVER_ORDER[max(0, self.video_server.GetSelection())]

    def _on_platform_changed(self, event):
        if event is not None:
            event.Skip()
        self._apply_platform()

    def _apply_platform(self):
        """Follow the platform choice.

        YouTube and Facebook have exactly one ingest address each and there is
        nothing to be gained by making somebody type it, so it is filled in
        and locked. A custom RTMP server is the one where the address really
        is the user's.

        A platform's address is ALWAYS set, never merely defaulted. The box is
        disabled for YouTube and Facebook, so anything left in it from before
        is an address the user cannot correct and the platform will not
        accept. Going the other way, a platform address is cleared rather than
        left sitting there as if it were the user's own server.
        """
        kind = self._current_platform()
        self.video_key_page.Enable(kind in C.RTMP_KEY_PAGE)
        self._say_bitrate_advice(kind)
        warning = getattr(self, "live_warning", None)
        if warning is not None:
            if C.RTMP_GOES_LIVE_AT_ONCE.get(kind):
                warning.SetLabel(
                    "Careful: pressing Ctrl+B puts you live on YouTube "
                    "straight away. There is no preview. Your subscribers "
                    "are notified and the stream is saved to your channel.")
            elif kind == "facebook":
                warning.SetLabel(
                    "Facebook shows you a preview first. Nothing is posted "
                    "until you press Go Live Now in Live Producer.")
            elif kind == "restream":
                warning.SetLabel(
                    "Create the RTMP stream on the Restream website first, "
                    "then copy BOTH the address and the key it gives you: "
                    "the address here is only the usual one and yours may "
                    "differ. Restream passes the stream on to whichever "
                    "channels you have switched on there, so with them all "
                    "off nothing leaves Restream.")
            else:
                warning.SetLabel(
                    "What happens when you connect is up to whoever runs "
                    "the server.")
            warning.Wrap(560)
            warning.GetParent().Layout()
        # Each platform's address is remembered separately for as long as the
        # window is open. Without this, pasting the URL Restream gave you and
        # then looking at the YouTube entry threw your URL away, because
        # coming back found YouTube's address in the box and replaced it with
        # Restream's default. Typed work is not something a dropdown gets to
        # discard.
        previous = getattr(self, "_last_platform", None)
        if previous is not None and previous != kind:
            self._hosts[previous] = self.video_host.GetValue().strip()
        self._last_platform = kind

        remembered = self._hosts.get(kind, "")
        ingest = C.RTMP_INGEST.get(kind)
        if kind in C.RTMP_FIXED_ADDRESS:
            # Exactly one ingest, and it is not the user's to get wrong.
            self.video_host.SetValue(ingest)
        elif remembered:
            self.video_host.SetValue(remembered)
        elif ingest:
            self.video_host.SetValue(ingest)
        else:
            self.video_host.SetValue("")
        self.video_host.Enable(kind not in C.RTMP_FIXED_ADDRESS)

    def _say_bitrate_advice(self, kind=None):
        """Warn about a bitrate the platform will not like, before air.

        Facebook publishes real bounds and says missing them can end a
        broadcast. Finding that out mid show, unable to see the dashboard, is
        the situation this exists to prevent.
        """
        advice = getattr(self, "bitrate_advice", None)
        if advice is None:
            return
        try:
            settings = self.picture_settings
        except Exception:
            return
        text = streamout.bitrate_advice(
            kind or self._current_platform(),
            settings["video_width"], settings["video_height"],
            settings["video_fps"], settings["video_bitrate"])
        advice.SetLabel(text)
        advice.Wrap(560)
        advice.GetParent().Layout()

    def _on_how_to(self, _event):
        with StreamHelpDialog(self, self._current_platform()) as box:
            box.ShowModal()

    def _on_open_key_page(self, _event):
        kind = self._current_platform()
        url = C.RTMP_KEY_PAGE.get(kind)
        if not url:
            self._say_video("A custom server has no page to open. Your key "
                            "comes from whoever runs it.")
            return
        try:
            webbrowser.open(url)
        except Exception:
            self._say_video("The page could not be opened. It is %s" % url)
            return
        self._say_video(
            "Opened the %s page in your browser. Copy the stream key from "
            "there and paste it into Stream key."
            % streamout.server_label(kind))

    #: The boxes a saved station fills in, and what reads and writes each.
    def _stream_controls(self):
        return {
            "stream_server": (self.stream_server, "choice",
                              C.STREAM_SERVER_ORDER),
            "stream_host": (self.stream_host, "text", None),
            "stream_port": (self.stream_port, "spin", None),
            "stream_mount": (self.stream_mount, "text", None),
            "stream_user": (self.stream_user, "text", None),
            "stream_password": (self.stream_password, "text", None),
            "stream_format": (self.stream_format, "choice",
                              C.STREAM_FORMAT_ORDER),
            "stream_bitrate": (self.stream_bitrate, "index",
                               C.STREAM_BITRATES),
            "stream_name": (self.stream_name, "text", None),
            "stream_stats_url": (self.stream_stats, "text", None),
            "stream_public": (self.stream_public, "check", None),
            "stream_mic": (self.stream_mic, "check", None),
            "stream_titles": (self.stream_titles, "check", None),
        }

    def _station_choices(self):
        names = self.board.station_names()
        return names or ["No stations saved yet"]

    def _fill_stream_fields(self):
        """Put the board's live settings into the boxes."""
        for field, (control, kind, order) in self._stream_controls().items():
            value = getattr(self.board, field)
            if kind == "text":
                control.SetValue(value or "")
            elif kind == "spin":
                control.SetValue(int(value))
            elif kind == "check":
                control.SetValue(bool(value))
            elif kind == "choice":
                control.SetSelection(order.index(value) if value in order else 0)
            elif kind == "index":
                control.SetSelection(order.index(value) if value in order
                                     else len(order) // 2)

    def _on_pick_station(self, _event):
        name = self.stream_picker.GetStringSelection()
        if not self.board.load_station(name):
            return
        self._fill_stream_fields()
        # The key does not live in the station, so it is fetched by name.
        self.video_key.SetValue(secrets.fetch(name))
        self.video_server.SetSelection(
            C.VIDEO_SERVER_ORDER.index(self.board.video_server)
            if self.board.video_server in C.VIDEO_SERVER_ORDER else 0)
        self.video_host.SetValue(self.board.video_host or "")
        self.live_to_video.SetValue(self.board.live_to == C.LIVE_TO_VIDEO)
        self._fill_picture_fields()
        self._apply_platform()
        self._say_test("Loaded %s." % name)

    def _on_save_station(self, _event):
        """Remember what is in the boxes, under the station name."""
        settings = self.stream_settings
        if not settings["name"]:
            self._say_test("Give the station a name first, in Station name.")
            self.stream_name.SetFocus()
            return
        video = self.video_settings
        for field, value in (("video_server", video["server"]),
                             ("video_host", video["host"]),
                             ("live_to", C.LIVE_TO_VIDEO if video["live"]
                              else C.LIVE_TO_AUDIO),
                             ("stream_server", settings["server"]),
                             ("stream_host", settings["host"]),
                             ("stream_port", settings["port"]),
                             ("stream_mount", settings["mount"]),
                             ("stream_user", settings["user"]),
                             ("stream_password", settings["password"]),
                             ("stream_format", settings["format"]),
                             ("stream_bitrate", settings["bitrate"]),
                             ("stream_name", settings["name"]),
                             ("stream_public", settings["public"]),
                             ("stream_mic", self.stream_mic.GetValue()),
                             ("stream_titles", self.stream_titles.GetValue())):
            setattr(self.board, field, value)
        for field, value in self.picture_settings.items():
            if field != "framing_level":     # app wide, not per station
                setattr(self.board, field, value)
        self.board.save_station()
        self._refresh_stations(settings["name"])
        note = self._keep_key(settings["name"], video["key"])
        self._say_test("Saved %s.%s" % (settings["name"], note))

    def _keep_key(self, station, key):
        """Put the stream key somewhere better than the board file.

        Returns what to add to the spoken confirmation, because a key that
        could NOT be kept safely is something the user has to be told: it
        stays in the board file then, the way it always did, and a board file
        travels.
        """
        if not key:
            secrets.forget(station)
            return ""
        if secrets.store(station, key):
            return " The stream key is in Windows Credential Manager."
        return (" The stream key could NOT be stored safely, so it is in "
                "your board file. Do not send that file to anybody.")

    def _on_forget_station(self, _event):
        name = self.stream_picker.GetStringSelection()
        if not self.board.forget_station(name):
            self._say_test("There is nothing saved by that name.")
            return
        # A forgotten station must not leave its key behind in the credential
        # store, where nothing would ever clean it up.
        secrets.forget(name)
        self._refresh_stations()
        self._say_test("Forgot %s." % name)

    def _refresh_stations(self, select=None):
        names = self._station_choices()
        self.stream_picker.Set(names)
        wanted = select or self.stream_name.GetValue().strip()
        self.stream_picker.SetSelection(
            names.index(wanted) if wanted in names else 0)

    def _on_test_stream(self, _event):
        """Connect, say what happened, disconnect. Never broadcasts anything.

        Written into a read only box as well as spoken, because a result you
        can only hear once is a result you cannot check, and this is the
        answer to the question "will it work tonight".
        """
        settings = self.stream_settings
        if not settings["host"]:
            self._say_test("Fill in the address first.")
            return
        self._say_test("Connecting...")
        wx.BeginBusyCursor()
        try:
            _label, factory = streamout.SERVERS.get(
                settings["server"], streamout.SERVERS["icecast"])
            spec = streamout.FORMATS.get(settings["format"],
                                          streamout.FORMATS["mp3"])
            sink = factory(host=settings["host"], port=settings["port"],
                           mount=settings["mount"], user=settings["user"],
                           password=settings["password"],
                           content_type=spec["content_type"],
                           name=settings["name"],
                           bitrate=settings["bitrate"])
            sink.connect()
            sink.close()
        except streamout.SinkError as exc:
            self._say_test("It did not connect: %s" % exc)
            return
        except Exception as exc:
            self._say_test("It did not connect: %s" % exc)
            return
        finally:
            wx.EndBusyCursor()
        self._say_test("Connected, and disconnected again. It will work.")

    def _on_test_video(self, _event):
        self._test_rtmp(self.video_settings)

    def _test_rtmp(self, settings):
        """Check a YouTube or Facebook station WITHOUT going live.

        **This deliberately does not complete an RTMP handshake**, and that is
        the whole point of it being separate from the Icecast test above.

        An Icecast source connection is inert: you connect, the server waits
        for audio, you hang up, and nothing has happened. RTMP to YouTube or
        Facebook is not inert. A publish is what STARTS a broadcast, and a
        presenter who cannot see their channel has no way to notice that a
        connection test put them on the air, however briefly. Getting that
        wrong once, on somebody's real channel, is worse than every problem
        this button was meant to catch.

        So it checks everything that can be checked from outside:

            the address is one we recognise and is shaped like a URL
            the name really resolves
            the port really accepts a connection
            TLS really completes, which is most of what goes wrong on 443
            a key is present and looks like a key

        What it cannot tell you is whether the KEY is right. Nothing can,
        short of going live, so it says so plainly rather than implying a
        pass it has not earned.
        """
        host = settings["host"].strip()
        key = settings.get("key", "").strip()
        parsed = urllib.parse.urlparse(host)
        if not parsed.scheme or not parsed.hostname:
            self._say_video(
                "That does not look like a server address. It should start "
                "with rtmp or rtmps.")
            return
        if not key:
            self._say_video(
                "There is no stream key. Get my stream key opens the page "
                "where yours is.")
            self.video_key.SetFocus()
            return

        port = parsed.port or (443 if parsed.scheme == "rtmps" else 1935)
        self._say_video("Checking...")
        wx.BeginBusyCursor()
        try:
            try:
                socket.getaddrinfo(parsed.hostname, port,
                                   proto=socket.IPPROTO_TCP)
            except OSError:
                self._say_video(
                    "Could not find %s. Check the address, and that you are "
                    "online." % parsed.hostname)
                return
            try:
                sock = socket.create_connection((parsed.hostname, port),
                                                C.STREAM_TIMEOUT)
            except OSError as exc:
                self._say_video(
                    "Could not reach %s on port %d: %s. Something may be "
                    "blocking it."
                    % (parsed.hostname, port, exc.strerror or exc))
                return
            try:
                if parsed.scheme == "rtmps":
                    context = ssl.create_default_context()
                    with context.wrap_socket(
                            sock, server_hostname=parsed.hostname) as secure:
                        secure.version()
            except Exception as exc:
                self._say_video(
                    "Reached %s but the secure connection failed: %s"
                    % (parsed.hostname, exc))
                return
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
        finally:
            wx.EndBusyCursor()

        self._say_video(
            "%s is reachable and your stream key is %s. The key itself cannot "
            "be checked without going live, so this does not prove it is "
            "right. Nothing was broadcast."
            % (parsed.hostname, secrets.redact(key)))

    def _say_test(self, text):
        self.stream_result.SetValue(text)
        frame = self.GetParent()
        speak = getattr(frame, "announce_answer", None)
        if speak is not None:
            speak(text)

    @property
    def stream_settings(self):
        """Everything the streamer needs, as it stands in the boxes."""
        return {
            "server": C.STREAM_SERVER_ORDER[
                max(0, self.stream_server.GetSelection())],
            "host": self.stream_host.GetValue().strip(),
            "port": int(self.stream_port.GetValue()),
            "mount": self.stream_mount.GetValue().strip() or "/",
            "user": self.stream_user.GetValue().strip() or "source",
            "password": self.stream_password.GetValue(),
            "format": C.STREAM_FORMAT_ORDER[
                max(0, self.stream_format.GetSelection())],
            "bitrate": C.STREAM_BITRATES[
                max(0, self.stream_bitrate.GetSelection())],
            "name": self.stream_name.GetValue().strip(),
            "stats_url": self.stream_stats.GetValue().strip(),
            "public": self.stream_public.GetValue(),
        }

    def _build_picture_tab(self):
        """Going out on YouTube, Facebook or any RTMP server.

        A page of its own, beside Audio streaming rather than folded into it.
        They looked like one job and are not: no mount point, no port, no
        format, a stream key instead of a password, and a picture, which the
        audio side has no concept of at all. One page that changed half its
        fields depending on a dropdown meant most of it was disabled most of
        the time, and Windows leaves disabled controls OUT OF THE TAB ORDER,
        so the stream key box could not be reached at all until you had
        already found and changed the server. Tony hit exactly that.

        A card is the default picture and a camera is not. Most people using
        this are running a radio show and have no reason to be on camera.
        """
        panel, sizer = self._page("Video streaming")

        note = wx.StaticText(panel, label=(
            "YouTube and Facebook will not take sound on its own, so a "
            "picture goes out with it. A card costs almost nothing."))
        note.Wrap(560)
        sizer.Add(note, 0, wx.ALL, 10)

        # The single most important thing on this page, and the one a
        # presenter cannot find out any other way. The two platforms behave
        # OPPOSITELY: YouTube's own documentation says that ingesting to a
        # stream key creates the watch page, puts you live, notifies your
        # subscribers and archives the result, with no preview and nothing to
        # confirm. Facebook posts nothing until somebody clicks Go Live Now.
        # Somebody who cannot see either page would learn this afterwards.
        self.live_warning = wx.StaticText(panel, label="")
        self.live_warning.Wrap(560)
        sizer.Add(self.live_warning, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.bitrate_advice = wx.StaticText(panel, label="")
        self.bitrate_advice.Wrap(560)
        sizer.Add(self.bitrate_advice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        grid = wx.FlexGridSizer(2, 8, 12)
        grid.AddGrowableCol(1, 1)

        def field(label, build, name, tip=""):
            # The label first, always. See the note in _build_stream_tab.
            grid.Add(wx.StaticText(panel, label=label), 0,
                     wx.ALIGN_CENTER_VERTICAL)
            control = build()
            name_field(control, name)
            if tip:
                control.SetToolTip(tip)
            grid.Add(control, 0, wx.EXPAND)
            return control

        self.video_server = field(
            "&Platform",
            lambda: wx.Choice(panel, choices=[
                streamout.server_label(k) for k in C.VIDEO_SERVER_ORDER]),
            "Platform",
            "Where the video goes. YouTube and Facebook fill their own "
            "address in; a custom server is any other RTMP receiver.")
        self.video_server.SetSelection(
            C.VIDEO_SERVER_ORDER.index(self.board.video_server)
            if self.board.video_server in C.VIDEO_SERVER_ORDER else 0)
        self.video_server.Bind(wx.EVT_CHOICE, self._on_platform_changed)

        self.video_host = field(
            "A&ddress",
            lambda: wx.TextCtrl(panel, value=self.board.video_host),
            "Address",
            "The RTMP address to send to. YouTube and Facebook set their "
            "own and it cannot be edited, because there is only one each and "
            "it is not yours to get wrong. For Restream or your own server, "
            "paste the address they give you, and prefer an rtmps one if "
            "they offer it: a plain rtmp address sends your key unencrypted.")

        self.video_key = field(
            "Stream &key",
            lambda: wx.TextCtrl(panel, value=self._loaded_key(),
                                style=wx.TE_PASSWORD),
            "Stream key",
            "The key from YouTube or Facebook. It is kept in Windows "
            "Credential Manager rather than in your board file, because "
            "anybody who has it can broadcast to your channel.")

        #: One remembered address per platform, for this window's lifetime.
        self._hosts = {}
        if self.board.video_server in C.VIDEO_SERVER_ORDER:
            self._hosts[self.board.video_server] = self.board.video_host or ""
        self._last_platform = None

        self._picture_kinds = list(C.PICTURE_SOURCES)
        self.picture_kind = field(
            "&Show",
            lambda: wx.Choice(panel, choices=[
                C.PICTURE_LABELS[k] for k in self._picture_kinds]),
            "What to show",
            "A card is drawn by the app and shows your station name and what "
            "is playing. A picture is your own artwork. A camera is a camera.")
        self.picture_kind.SetSelection(
            self._picture_kinds.index(self.board.picture)
            if self.board.picture in self._picture_kinds else 0)
        self.picture_kind.Bind(wx.EVT_CHOICE, self._on_picture_kind)

        self.picture_file = field(
            "Picture &file",
            lambda: wx.TextCtrl(panel, value=self.board.picture_file),
            "Picture file",
            "A PNG or a JPEG. It is fitted inside the frame without being "
            "stretched out of shape.")

        self._cameras = []
        self.camera_choice = field(
            "&Camera",
            lambda: wx.Choice(panel, choices=["Looking for cameras..."]),
            "Camera",
            "Which camera to use. The list is whatever Windows can see.")

        self._screens = screen.screens()
        self.screen_choice = field(
            "&Which screen",
            lambda: wx.Choice(panel, choices=(
                [label for _v, label, _w, _h in self._screens]
                or ["No screen can be captured"])),
            "Which screen",
            "What goes out when the picture is your screen. Everything on "
            "your screens sends all of them side by side; the main screen "
            "sends only the one Windows calls the main one.")

        self._sizes = [(1280, 720), (1920, 1080), (854, 480), (640, 360)]
        self.video_size = field(
            "Si&ze",
            lambda: wx.Choice(panel, choices=[
                camera.describe_size(w, h) for w, h in self._sizes]),
            "Picture size",
            "720p is the sensible answer and what most cameras do. 1080p "
            "costs more upload for very little at this kind of bitrate.")

        self.video_bitrate = field(
            "Picture &quality",
            lambda: wx.Choice(panel, choices=[
                "%d kbps" % rate for rate in C.RTMP_VIDEO_BITRATES]),
            "Picture quality",
            "How much of your upload the picture gets. A card needs almost "
            "none of this; a camera wants 2500 or more at 720p.")

        self._framing_levels = list(framing.FRAMING_LEVELS)
        self.framing_level = field(
            "&Tell me about the shot",
            lambda: wx.Choice(panel, choices=[
                framing.FRAMING_LEVEL_LABELS[k]
                for k in self._framing_levels]),
            "Tell me about the shot",
            "Whether the app says when you are out of shot, off to one side "
            "or in the dark. Ctrl+Shift+F answers whatever this is set to.")
        self.framing_level.SetSelection(
            self._framing_levels.index(self.board.framing_level)
            if self.board.framing_level in self._framing_levels else 1)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        self.live_to_video = wx.CheckBox(
            panel, label="Go live &here when I press Ctrl+B")
        self.live_to_video.SetValue(self.board.live_to == C.LIVE_TO_VIDEO)
        self.live_to_video.SetToolTip(
            "Ctrl+B sends the show to one place at a time. Turn this on to "
            "send it here instead of to your radio station. The same choice "
            "is on the On air menu under Streaming location, where you can "
            "see which one is ticked without opening this window.")
        sizer.Add(self.live_to_video, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.picture_clock = wx.CheckBox(
            panel, label="Put a clock &on the card")
        self.picture_clock.SetValue(bool(self.board.picture_clock))
        sizer.Add(self.picture_clock, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        # Finding a stream key means going into a video web app and hunting
        # for it, which is the worst part of setting this up with a screen
        # reader and the one part the app can make easy. It is also the ONLY
        # part: everything else is one paste and then never again.
        howto = wx.Button(panel, label="How do I set this &up?")
        howto.SetToolTip(
            "Step by step for whichever platform is picked above, without "
            "leaving the app.")
        howto.Bind(wx.EVT_BUTTON, self._on_how_to)
        row.Add(howto, 0, wx.RIGHT, 8)

        self.video_key_page = wx.Button(panel, label="Get my stream ke&y")
        self.video_key_page.SetToolTip(
            "Opens the page on YouTube or Facebook where your stream key is, "
            "so you do not have to go looking for it.")
        self.video_key_page.Bind(wx.EVT_BUTTON, self._on_open_key_page)
        row.Add(self.video_key_page, 0, wx.RIGHT, 8)

        video_test = wx.Button(panel, label="T&est the connection")
        video_test.SetToolTip(
            "Checks the address is reachable without going live. It cannot "
            "check the key itself, and nothing is broadcast.")
        video_test.Bind(wx.EVT_BUTTON, self._on_test_video)
        row.Add(video_test, 0, wx.RIGHT, 8)

        look = wx.Button(panel, label="&Look through the camera now")
        look.SetToolTip(
            "Opens the camera, says what it can see, and closes it again. "
            "Nothing is broadcast.")
        look.Bind(wx.EVT_BUTTON, self._on_look)
        row.Add(look, 0, wx.RIGHT, 8)
        refresh = wx.Button(panel, label="Look for cameras a&gain")
        refresh.Bind(wx.EVT_BUTTON, lambda _e: self._refresh_cameras(True))
        row.Add(refresh, 0)
        sizer.Add(row, 0, wx.ALL, 10)

        self._label(panel, sizer, "What happened")
        self.picture_result = wx.TextCtrl(
            panel, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 60),
            value="Nothing tried yet.")
        self.picture_result.SetName("What happened")
        sizer.Add(self.picture_result, 0,
                  wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self._fill_video_size()
        self._refresh_cameras()
        self._on_picture_kind(None)
        self.video_size.Bind(wx.EVT_CHOICE,
                             lambda _e: self._say_bitrate_advice())
        self.video_bitrate.Bind(wx.EVT_CHOICE,
                                lambda _e: self._say_bitrate_advice())
        self._apply_platform()

    def _fill_picture_fields(self):
        """Put the board's picture settings into the boxes.

        Needed because loading a station assigns every one of STATION_FIELDS,
        picture included, and without this the page went on showing the
        previous station's answers and OK wrote them back over the loaded one.
        """
        self.picture_kind.SetSelection(
            self._picture_kinds.index(self.board.picture)
            if self.board.picture in self._picture_kinds else 0)
        self.picture_file.SetValue(self.board.picture_file or "")
        self.picture_clock.SetValue(bool(self.board.picture_clock))
        if self.board.camera in self._cameras:
            self.camera_choice.SetSelection(
                self._cameras.index(self.board.camera))
        self._fill_video_size()
        self._fill_screens()
        self._on_picture_kind(None)

    def _fill_screens(self):
        values = [value for value, _l, _w, _h in self._screens]
        if self.board.screen in values:
            self.screen_choice.SetSelection(values.index(self.board.screen))
        elif values:
            self.screen_choice.SetSelection(0)

    def _fill_video_size(self):
        want = (int(self.board.video_width), int(self.board.video_height))
        if want not in self._sizes:
            self._sizes.append(want)
            self.video_size.Append(camera.describe_size(*want))
        self.video_size.SetSelection(self._sizes.index(want))
        rates = list(C.RTMP_VIDEO_BITRATES)
        closest = min(rates, key=lambda r: abs(r - int(self.board.video_bitrate)))
        self.video_bitrate.SetSelection(rates.index(closest))

    def _refresh_cameras(self, say=False):
        """Ask Windows what cameras there are, off the UI thread.

        Enumeration opens DirectShow, which takes long enough to be felt, and
        a Preferences box that freezes while it opens is a Preferences box
        that looks broken.
        """
        def work():
            try:
                found = camera.cameras()
            except Exception:
                found = []
            wx.CallAfter(self._cameras_found, found, say)

        threading.Thread(target=work, daemon=True,
                         name="dropdeck-camera-list").start()

    def _cameras_found(self, found, say=False):
        if not self:                       # the box was closed while looking
            return
        self._cameras = found
        choices = found or ["No cameras found"]
        self.camera_choice.Set(choices)
        wanted = self.board.camera
        self.camera_choice.SetSelection(
            found.index(wanted) if wanted in found else 0)
        if say:
            self._say_picture(
                "Found %d camera%s." % (len(found), "" if len(found) == 1 else "s")
                if found else "No cameras found.")

    def _on_picture_kind(self, event):
        """Enable what this kind of picture needs. Nothing is hidden."""
        if event is not None:
            event.Skip()
        kind = self._picture_kinds[max(0, self.picture_kind.GetSelection())]
        self.picture_file.Enable(kind == C.PICTURE_IMAGE)
        # The split wants both a camera and a screen, so it is not the
        # same test as "is this the camera source" any more.
        self.camera_choice.Enable(kind in C.PICTURE_NEEDS_CAMERA)
        self.framing_level.Enable(kind in C.PICTURE_NEEDS_CAMERA)
        self.screen_choice.Enable(kind in C.PICTURE_NEEDS_SCREEN
                                  and bool(self._screens))
        self.picture_clock.Enable(kind == C.PICTURE_CARD)

    #: The video page has one result box and two things that report into it,
    #: the connection check and the camera, so they share a name.
    def _say_video(self, text):
        return self._say_picture(text)

    def _say_picture(self, text):
        self.picture_result.SetValue(text)
        frame = self.GetParent()
        speak = getattr(frame, "announce_answer", None)
        if speak is not None:
            speak(text)

    def _on_look(self, _event):
        """Open the camera, say what it sees, close it. Broadcasts nothing.

        This is the button somebody presses before a show, and it answers the
        question they actually have, which is not "does the camera work" but
        "am I in it".
        """
        settings = self.picture_settings
        if settings["picture"] != C.PICTURE_CAMERA:
            self._say_picture("Set Show to a camera first.")
            return
        if not settings["camera"]:
            self._say_picture("There is no camera to look through.")
            return
        self._say_picture("Opening the camera...")
        wx.BeginBusyCursor()
        try:
            source = camera.CameraSource(settings["camera"],
                                         settings["video_width"],
                                         settings["video_height"],
                                         settings["video_fps"])
            try:
                source.start()
                if not source.wait_ready(C.CAMERA_OPEN_TIMEOUT):
                    self._say_picture(source.error or
                                      "The camera gave no picture.")
                    return
                watcher = framing.Framer(level=framing.FRAMING_OFF)
                reading = watcher.measure(source.latest())
                if watcher.error:
                    self._say_picture(
                        "The camera works: %s. %s"
                        % (source.describe(), watcher.error))
                    return
                self._say_picture("%s. %s." % (source.describe(),
                                               reading.sentence()))
            finally:
                source.close()
        except camera.CameraError as exc:
            self._say_picture(str(exc))
        except Exception as exc:
            self._say_picture(camera.explain(exc, settings["camera"]))
        finally:
            wx.EndBusyCursor()

    @property
    def video_settings(self):
        """The video side, as it stands in the boxes."""
        return {
            "server": self._current_platform(),
            "host": self.video_host.GetValue().strip(),
            # Stripped hard: a key pasted off a web page routinely carries a
            # trailing newline or a space, and that is one of the commonest
            # reasons a key that LOOKS right is refused.
            "key": "".join(self.video_key.GetValue().split()),
            "live": bool(self.live_to_video.GetValue()),
        }

    @property
    def picture_settings(self):
        """Everything the picture needs, as it stands in the boxes."""
        kind = self._picture_kinds[max(0, self.picture_kind.GetSelection())]
        width, height = self._sizes[max(0, self.video_size.GetSelection())]
        chosen = self.camera_choice.GetStringSelection()
        return {
            "picture": kind,
            "picture_file": self.picture_file.GetValue().strip(),
            "picture_clock": bool(self.picture_clock.GetValue()),
            "camera": chosen if chosen in self._cameras else "",
            "screen": (self._screens[self.screen_choice.GetSelection()][0]
                       if 0 <= self.screen_choice.GetSelection()
                       < len(self._screens) else C.SCREEN_ALL),
            "video_width": width,
            "video_height": height,
            "video_fps": int(self.board.video_fps or C.RTMP_FPS),
            "video_bitrate": C.RTMP_VIDEO_BITRATES[
                max(0, self.video_bitrate.GetSelection())],
            "framing_level": self._framing_levels[
                max(0, self.framing_level.GetSelection())],
        }

    def _build_record_tab(self):
        """Where a recording goes and what it is written as.

        Its own tab rather than a corner of Streaming, because recording is
        not a kind of streaming: you record a show whether or not anybody is
        listening to it live, and switching station does not change it.
        """
        from . import recorder as recording

        panel, sizer = self._page("Recording")
        self._note(panel, sizer,
                   "Ctrl+R starts and stops recording. It records the same "
                   "mix that goes on air, including your microphone if that "
                   "is set to go out, and it does not need you to be on air. "
                   "The cue before a track ends and previews are never in it.")

        self._label(panel, sizer, "&Record as")
        self.record_format = wx.Choice(
            panel, choices=[label for _key, label in recording.FORMATS])
        name_field(self.record_format, "Record as")
        current = getattr(self.board, "record_format", "mp3")
        self.record_format.SetSelection(
            recording.FORMAT_KEYS.index(current)
            if current in recording.FORMAT_KEYS else 0)
        self.record_format.SetToolTip(
            "WAV is uncompressed, which is what you want if the recording is "
            "going into an editor. MP3 plays everywhere and takes about a "
            "tenth of the space.")
        self.record_format.Bind(wx.EVT_CHOICE, self._on_record_format)
        sizer.Add(self.record_format, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self._label(panel, sizer, "&Bitrate")
        self.record_bitrate = wx.Choice(
            panel, choices=["%d kbps" % rate for rate in C.STREAM_BITRATES])
        name_field(self.record_bitrate, "Bitrate")
        rate = int(getattr(self.board, "record_bitrate", 192))
        self.record_bitrate.SetSelection(
            C.STREAM_BITRATES.index(rate) if rate in C.STREAM_BITRATES
            else len(C.STREAM_BITRATES) // 2)
        self.record_bitrate.SetToolTip(
            "How much space a minute takes, and how good it sounds. 192 is "
            "plenty for a show. WAV ignores this, because it compresses "
            "nothing.")
        sizer.Add(self.record_bitrate, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.record_bitrate.Enable(current != "wav")

        self._label(panel, sizer, "Save recordings &in")
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.record_folder = wx.TextCtrl(
            panel, value=(getattr(self.board, "record_folder", "")
                          or recording.default_folder()))
        name_field(self.record_folder, "Save recordings in")
        self.record_folder.SetToolTip(
            "Files are named Drop Deck Stream 001 and count up, so nothing "
            "you have already recorded is ever written over.")
        row.Add(self.record_folder, 1, wx.EXPAND | wx.RIGHT, 8)
        browse = wx.Button(panel, label="C&hoose...")
        browse.Bind(wx.EVT_BUTTON, self._on_record_folder)
        row.Add(browse, 0)
        sizer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.record_next = wx.StaticText(panel, label="")
        sizer.Add(self.record_next, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self._show_next_recording()

    def _on_record_format(self, event):
        self.record_bitrate.Enable(self.record_format_key != "wav")
        self._show_next_recording()
        event.Skip()

    def _on_record_folder(self, _event):
        with wx.DirDialog(self, "Where should recordings go?",
                          defaultPath=self.record_folder.GetValue(),
                          style=wx.DD_DEFAULT_STYLE) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.record_folder.SetValue(dialog.GetPath())
                self._show_next_recording()

    def _show_next_recording(self):
        """Say what the next file will be called, so it is not a surprise."""
        from . import recorder as recording
        try:
            path = recording.next_path(self.record_folder.GetValue().strip()
                                       or recording.default_folder(),
                                       self.record_format_key)
            self.record_next.SetLabel("The next one will be %s"
                                      % os.path.basename(path))
        except Exception:
            self.record_next.SetLabel("")

    @property
    def record_format_key(self):
        from . import recorder as recording
        return recording.FORMAT_KEYS[max(0, self.record_format.GetSelection())]

    @property
    def record_bitrate_value(self):
        return C.STREAM_BITRATES[max(0, self.record_bitrate.GetSelection())]

    @property
    def record_folder_path(self):
        return self.record_folder.GetValue().strip()

    def _build_speech_tab(self):
        panel, sizer = self._page("Speech")

        # How much the app says out loud. A screen reader is already reading
        # every control; this is only about what the app adds on top, which
        # for somebody who knows the board is mostly repetition.
        self._label(panel, sizer, "Spo&ken feedback from the app")
        self.speech_choice = wx.Choice(panel, choices=list(C.SPEECH_LABELS))
        self.speech_choice.SetName("Spoken feedback from the app")
        level = getattr(self.board, "speech_level", C.DEFAULT_SPEECH_LEVEL)
        self.speech_choice.SetSelection(
            C.SPEECH_LEVELS.index(level) if level in C.SPEECH_LEVELS else 0)
        self.speech_choice.SetToolTip(
            "Everything is the default. The middle setting drops confirmations "
            "and the bank hints and keeps anything you could not otherwise "
            "know. Nothing leaves the running commentary to your screen reader "
            "and the status bar, and still answers a key you press to ask a "
            "question, such as Ctrl+L for what is playing.")
        self.speech_choice.Bind(wx.EVT_CHOICE, self._on_speech_level)
        sizer.Add(self.speech_choice, 0, wx.EXPAND | wx.ALL, 10)

        self.announce_playback = wx.CheckBox(
            panel, label="&Say the name when a sound starts or stops")
        self.announce_playback.SetValue(
            bool(getattr(self.board, "announce_playback", True)))
        self.announce_playback.SetToolTip(
            "Turn this off if you can hear the sound and do not need to be "
            "told about it. Problems, such as a missing file, are always "
            "announced unless you have chosen Nothing above.")
        sizer.Add(self.announce_playback, 0, wx.ALL, 10)
        self._on_speech_level(None)

    def _fade_spin(self, panel, grid, label, name, value, tip):
        grid.Add(wx.StaticText(panel, label=label), 0,
                 wx.ALIGN_CENTER_VERTICAL)
        spin = wx.SpinCtrlDouble(panel, min=0.0, max=C.MAX_BED_FADE, inc=0.05,
                                 initial=float(value))
        spin.SetDigits(2)
        name_field(spin, name)
        spin.SetToolTip(tip)
        grid.Add(spin, 0)
        return spin

    # -------------------------------------------------------- what it says --
    @property
    def bed_fade_in(self):
        return round(float(self.fade_in_ctrl.GetValue()), 2)

    @property
    def bed_fade_out(self):
        return round(float(self.fade_out_ctrl.GetValue()), 2)

    @property
    def crossfade(self):
        return round(float(self.crossfade_ctrl.GetValue()), 2)

    @property
    def warn_before_end(self):
        return bool(self.warn_on.GetValue())

    @property
    def warn_seconds(self):
        return float(self.warn_seconds_ctrl.GetValue())

    @property
    def mic_gain_db(self):
        return float(self.mic_gain.GetValue())

    @property
    def mic_monitoring(self):
        return bool(self.mic_monitor.GetValue())

    def _on_speech_level(self, _event):
        """The checkbox only means anything at the chattiest level.

        Below it the app is not naming sounds whatever the box says, and a
        live control that does nothing is worse than one plainly greyed out.
        """
        self.announce_playback.Enable(self.speech_level == C.SPEECH_ALL)

    @property
    def speech_level(self):
        index = self.speech_choice.GetSelection()
        if index < 0:
            return C.DEFAULT_SPEECH_LEVEL
        return C.SPEECH_LEVELS[index]

    def _status_text(self):
        # A MixerGroup has no single stream, so ask it how many outputs are
        # actually running rather than reaching for `.stream`.
        count = getattr(self.mixer, "distinct_device_count", None)
        if count is not None and count() > 1:
            return (f"Playing through {count()} outputs, "
                    f"main is {describe_device(self.mixer.device)}.")
        if getattr(self.mixer, "last_error", None) and not self._audio_running():
            return f"Audio is not running. {self.mixer.last_error}".strip()
        return (f"Playing through {describe_device(self.mixer.device)} "
                f"at {self.mixer.samplerate} hertz.")

    def _mic_status_text(self):
        if self.mic is None:
            return "The microphone is off."
        if self.mic.is_open:
            return "The microphone is ON, through %s." % self.mic.describe()
        if self.mic.last_error:
            return "It would not open last time. %s" % self.mic.last_error
        return "The microphone is off. Ctrl+M turns it on."

    def _audio_running(self):
        return bool(getattr(self.mixer, "is_running", False))

    def _current_selection(self):
        if not self.board.device_name:
            return 0
        for position, dev in enumerate(self.devices, start=1):
            if (dev["name"] == self.board.device_name
                    and dev["hostapi"] == self.board.device_hostapi):
                return position
        return 0

    def _bank_selection(self, bank):
        """0 means "whatever the main output is", not "system default"."""
        spec = (self.board.bank_devices or {}).get(bank)
        if not spec or not spec.get("name"):
            return 0
        for position, dev in enumerate(self.devices, start=1):
            if (dev["name"] == spec.get("name")
                    and dev["hostapi"] == spec.get("hostapi")):
                return position
        # The remembered device is not here today. Show it on the main output
        # rather than pointing at some other card that happens to sit at the
        # same position in the list.
        return 0

    def _mic_selection(self):
        return self._match(self.mic_devices, self.board.mic_device_name,
                           self.board.mic_device_hostapi)

    def _monitor_selection(self):
        return self._match(self.devices, self.board.mic_output_name,
                           self.board.mic_output_hostapi)

    @staticmethod
    def _match(devices, name, hostapi):
        """Where a remembered device sits in the list, or 0 for the default.

        Name and host API first, then name alone: a card that has moved from
        WASAPI to MME between launches is still the card somebody chose, and
        falling all the way back to the default would silently pick another.
        """
        if not name:
            return 0
        for position, device in enumerate(devices, start=1):
            if device["name"] == name and device["hostapi"] == hostapi:
                return position
        for position, device in enumerate(devices, start=1):
            if device["name"] == name:
                return position
        return 0

    @property
    def chosen_device(self):
        """(index, name, hostapi). index is None for the system default."""
        return self._chosen(self.devices, self.device)

    @property
    def chosen_mic_device(self):
        """(index, name, hostapi) for the microphone that was picked."""
        return self._chosen(self.mic_devices, self.mic_device)

    @property
    def chosen_monitor_output(self):
        """(index, name, hostapi) for the output monitoring should use."""
        return self._chosen(self.devices, self.mic_output)

    @staticmethod
    def _chosen(devices, control):
        selection = control.GetSelection()
        if selection <= 0:
            return None, None, None
        device = devices[selection - 1]
        return device["index"], device["name"], device["hostapi"]

    @property
    def chosen_bank_devices(self):
        """bank -> {"name", "hostapi"} for every bank not on the main output."""
        chosen = {}
        for bank, choice in self.bank_choices.items():
            selection = choice.GetSelection()
            if selection <= 0:
                continue
            dev = self.devices[selection - 1]
            chosen[bank] = {"name": dev["name"], "hostapi": dev["hostapi"]}
        return chosen


class DropsLibraryDialog(wx.Dialog):
    """The drops you use over and over, in one place.

    Nothing here plays anything: it is a list you build once so that Alt+D has
    something to reach for. The list is the whole control, the same way the
    running order is - a plain list box, read without argument by everything.
    """

    def __init__(self, parent, library):
        super().__init__(parent, title="Drops library",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.library = library

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label=(
            "The idents and stingers you reach for over and over. Once they "
            "are in here,\n"
            "Alt+D puts one in the running order at random, wherever you are, "
            "and never\n"
            "the same one twice running.")), 0, wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="&Drops"), 0, wx.LEFT | wx.RIGHT, 10)
        self.list = wx.ListBox(self, style=wx.LB_SINGLE)
        self.list.SetName("Drops")
        outer.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        self.summary = wx.StaticText(self, label="")
        outer.Add(self.summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        add = wx.Button(self, label="&Add drops...")
        add.SetToolTip("Choose files, or a whole folder of them")
        add.Bind(wx.EVT_BUTTON, self._on_add)
        row.Add(add, 0, wx.RIGHT, 6)
        self.remove = wx.Button(self, label="&Remove")
        self.remove.SetToolTip("Take this one out of the library")
        self.remove.Bind(wx.EVT_BUTTON, self._on_remove)
        row.Add(self.remove, 0, wx.RIGHT, 6)
        outer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        outer.Add(self.CreateStdDialogButtonSizer(wx.OK), 0,
                  wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)
        self.SetSize((560, 420))

        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self._refresh()
        self.list.SetFocus()

    def _say(self, text):
        speaker = getattr(self.GetParent(), "speaker", None)
        if speaker is not None:
            speaker.say(text)

    def _refresh(self, keep=None):
        previous = self.list.GetSelection() if keep is None else keep
        self.list.Set([self.library.label(i) for i in range(len(self.library))])
        count = len(self.library)
        if count:
            if previous == wx.NOT_FOUND or previous is None or previous >= count:
                previous = count - 1
            self.list.SetSelection(max(0, previous))
        missing = len(self.library.missing)
        if not count:
            self.summary.SetLabel(
                "Nothing in the library yet. Add some, and Alt+D will start "
                "reaching for them.")
        else:
            text = "%d drop%s" % (count, "" if count == 1 else "s")
            if missing:
                text += ".  %d file%s missing" % (missing,
                                                  "" if missing == 1 else "s")
            self.summary.SetLabel(text)
        self.remove.Enable(bool(count))

    def _on_add(self, _event):
        with wx.FileDialog(self, "Add drops to the library",
                           wildcard=C.AUDIO_WILDCARD,
                           style=wx.FD_OPEN | wx.FD_MULTIPLE
                           | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            paths = dialog.GetPaths()
        added = self.library.add(paths)
        self._refresh(keep=len(self.library) - len(added) if added else None)
        if not added:
            self._say("Those are already in the library")
        else:
            self._say("%d added" % len(added))

    def _on_remove(self, _event):
        index = self.list.GetSelection()
        if index == wx.NOT_FOUND:
            return
        gone = self.library.remove(index)
        self._refresh(keep=min(index, len(self.library) - 1))
        if gone:
            self._say("Removed %s"
                      % os.path.splitext(os.path.basename(gone))[0])

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_DELETE:
            self._on_remove(None)
            return
        event.Skip()


class TrackCrossfadeDialog(wx.Dialog):
    """How long THIS track overlaps the next one.

    Most tracks want the playlist's own crossfade, which is why the default is
    a tick box rather than a number: "same as the rest" is a different answer
    from "three seconds", and a board that cannot tell them apart would freeze
    every track at whatever the playlist happened to be set to on the day.
    """

    def __init__(self, parent, track, default_seconds):
        super().__init__(parent, title="Crossfade for one track")
        self.track = track
        self.default_seconds = default_seconds

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label=(
            "How long should %s overlap the track after it?"
            % track.display_name)), 0, wx.ALL, 10)

        self.use_default = wx.CheckBox(
            self, label="Use the &playlist's crossfade (%g seconds)"
            % default_seconds)
        self.use_default.SetValue(track.crossfade is None)
        outer.Add(self.use_default, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label="&Seconds for this one"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        start = (track.crossfade if track.crossfade is not None
                 else track.crossfade_seconds(default_seconds))
        self.seconds = wx.SpinCtrlDouble(
            self, min=0.0, max=C.MAX_CROSSFADE, inc=0.5, initial=float(start))
        self.seconds.SetDigits(1)
        name_field(self.seconds, "Crossfade for this track, seconds")
        self.seconds.SetToolTip(
            "Zero means it plays right out and the next one starts after it, "
            "which is what a drop does unless you say otherwise.")
        row.Add(self.seconds, 0)
        outer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.use_default.Bind(
            wx.EVT_CHECKBOX,
            lambda e: (self.seconds.Enable(not e.IsChecked()), e.Skip()))
        self.seconds.Enable(track.crossfade is not None)

        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
                  0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)
        self.use_default.SetFocus()

    @property
    def result(self):
        """Seconds for this track, or None meaning the playlist's own."""
        if self.use_default.GetValue():
            return None
        return round(float(self.seconds.GetValue()), 2)


def ask_text(parent, prompt, title, value=""):
    """A text prompt whose existing text is selected, ready to be typed over.

    Brian Hartgen, on 2.4.0: renaming a bank put the current name in the box
    and left the caret at the end of it, so you had to clear it yourself.
    Every other Windows rename hands you the old name selected - F2 in
    Explorer, in the registry editor, anywhere - and typing replaces it.

    wx.TextEntryDialog does not expose its text control, so the control is
    found among the dialog's children. If it ever cannot be, the dialog still
    works exactly as it did; only the convenience is lost.
    """
    dialog = wx.TextEntryDialog(parent, prompt, title, value)
    for child in dialog.GetChildren():
        if isinstance(child, wx.TextCtrl):
            child.SetSelection(-1, -1)
            child.SetFocus()
            break
    return dialog


class NativePreview:
    """Preview inside the Windows file window, which cannot be asked to help.

    Tony, 4 September 2026: "searching with windows with that open file dialog
    is very native and people understand that layout much more. just need that
    preview function to work better." He is right, and the first answer to
    this was wrong: the reason given for not doing it, that Windows will not
    say what is highlighted, came from a test where nothing was ever
    highlighted, so an empty answer looked like a broken one.

    Three measured facts hold this up, and if any of them stops being true the
    feature stops rather than misbehaves:

    - **A wx.Timer keeps firing while the native dialog is up.** That is the
      only way to run any code at all during somebody else's modal window.
    - **GetCurrentlySelectedFilename really does report the highlighted file**,
      as a full path, on Windows.
    - **GetAsyncKeyState remembers a press.** Its low bit means "this key went
      down since you last asked", so asking eight times a second catches a
      press however brief, which plain "is it down now" polling did not.

    The switch was a registered hotkey first, and that was wrong. A hotkey is
    system wide: it takes Alt+P off every other program for as long as the
    window is open, and it swallows the key rather than passing it on, so
    ignoring it when we are not in front would not have given it back. Tony
    found that within minutes of getting it: "i just tried it to do another
    function with a different program, and it triggered the drop deck preview
    while it wasn't in focus." This app already refuses to register a bare
    global hotkey for that reason, and a preview switch has even less business
    owning a key across the whole machine.

    So nothing is registered anywhere. The keyboard is read, and a press only
    counts while a window of this process is the one in front. Alt+P in
    somebody else's program stays theirs.
    """

    #: Windows virtual key for either Alt.
    VK_MENU = 0x12
    #: GetAsyncKeyState: high bit is down now, low bit is went down since the
    #: last time this thread asked.
    DOWN_NOW = 0x8000
    PRESSED_SINCE = 0x0001

    def __init__(self, dialog, frame, on=False):
        self.dialog = dialog
        self.frame = frame
        self.mixer = getattr(frame, "mixer", None)
        self.board = getattr(frame, "board", None)
        self.on = bool(on)
        self._selected = None
        self._changed_at = 0.0
        self._played = None
        self._started_at = 0.0
        self._timer = None
        #: Files that would not play. Kept so a broken one is mentioned once
        #: rather than retried every tenth of a second in silence.
        self._refused = set()
        #: What switches it. Read from the keyboard rather than registered, so
        #: it is only ours while a window of ours is in front.
        self.key_label = "Alt+P"

    # ------------------------------------------------------------ lifetime --
    def start(self):
        """Begin watching. Call before ShowModal."""
        if self.frame is None or self.mixer is None:
            return self
        self._timer = wx.Timer(self.frame)
        self.frame.Bind(wx.EVT_TIMER, self._tick, self._timer)
        self._timer.Start(C.NATIVE_POLL_MS)
        # Throw away anything pressed before now, so a P typed a moment ago
        # does not arrive as the first thing this sees.
        self._pressed_since_last_look()
        self._say_hello()
        return self

    def _say_hello(self):
        """Say what does it, because nothing in the window can.

        A native dialog has no room for a label of ours, so a switch nobody is
        told about is a switch nobody finds.
        """
        self.frame.announce_help(
            "The Windows file window. %s plays each sound as you reach it%s"
            % (self.key_label, ", and it is on" if self.on else ""))

    @staticmethod
    def ours_is_in_front():
        """Is the window in front one of ours.

        A key pressed in somebody else's program is somebody else's business.
        Asked by process rather than by window, because the window in front
        while this runs is the Windows file dialog, which is ours but is not
        any wx window there would be something to compare against.
        """
        try:
            user32 = ctypes.windll.user32
            handle = user32.GetForegroundWindow()
            if not handle:
                return False
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            return pid.value == os.getpid()
        except Exception:
            return False

    def _pressed_since_last_look(self):
        """Has Alt+P gone down since the last time this asked.

        Alt counts as held if it is down now or if it went down in the same
        breath, because a quick press can be over before the next look.

        Always asked, in front or not, because the latch has to be cleared
        either way. Left set, it would fire a preview the moment the app came
        back in front, off a keypress meant for another program.
        """
        try:
            user32 = ctypes.windll.user32
            alt = user32.GetAsyncKeyState(self.VK_MENU)
            letter = user32.GetAsyncKeyState(ord("P"))
        except Exception:
            return False
        if not letter & self.PRESSED_SINCE:
            return False
        return bool(alt & (self.DOWN_NOW | self.PRESSED_SINCE))

    def _check_key(self):
        pressed = self._pressed_since_last_look()
        if pressed and self.ours_is_in_front():
            self.toggle()

    def stop(self):
        """Stop watching and silence anything auditioning. Safe twice."""
        if self._timer is not None:
            self._timer.Stop()
            try:
                self.frame.Unbind(wx.EVT_TIMER, source=self._timer)
            except Exception:
                pass
            self._timer = None
        self._silence()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.stop()
        return False

    # ---------------------------------------------------------------- work --
    def _say(self, text):
        speaker = getattr(self.frame, "speaker", None)
        if speaker is not None:
            speaker.say(text)

    def _silence(self):
        self._played = None
        if self.mixer is not None:
            try:
                self.mixer.stop_preview()
            except Exception:
                pass

    def _tick(self, _event):
        self._check_key()
        selected = self._selection()
        if selected != self._selected:
            self._selected = selected
            self._changed_at = time.monotonic()
            # Whatever is playing belongs to the file you have just left.
            self._silence()
        if not self.on or not selected or self._played == selected:
            self._stop_when_long_enough()
            return
        # The wait is the whole reason this is not instant: the screen reader
        # is saying the file name at the moment you arrow onto it, and a sound
        # on top of that takes the name away.
        if (time.monotonic() - self._changed_at) * 1000.0 < C.PREVIEW_DELAY_MS:
            return
        if selected in self._refused:
            return
        if not audiofile.is_supported(selected):
            self._refused.add(selected)
            self._say("%s will not play here"
                      % os.path.basename(selected))
            return
        try:
            self.mixer.play_preview(selected)
        except Exception as exc:
            # Said, and remembered. This used to return in silence and then
            # try the same broken file again on the next tick, so arrowing
            # onto a damaged sound was a preview that simply stopped working
            # with no reason given.
            self._refused.add(selected)
            self._say("%s would not play: %s"
                      % (os.path.basename(selected), exc))
            return
        self._played = selected
        self._started_at = time.monotonic()

    def _stop_when_long_enough(self):
        """Nobody wants four minutes of a song while they look for the next."""
        if (self._played
                and time.monotonic() - self._started_at > C.PREVIEW_MAX_SECONDS):
            self._silence()

    def _selection(self):
        try:
            selected = self.dialog.GetCurrentlySelectedFilename()
        except Exception:
            return None
        return selected or None

    def toggle(self):
        self.on = not self.on
        if self.board is not None:
            self.board.preview_sounds = self.on
        if not self.on:
            self._silence()
        else:
            # Play what is already highlighted rather than waiting for a move.
            self._changed_at = 0.0
            self._played = None
        if self.frame is not None:
            # Spoken, not written: the status bar is behind a modal window
            # nobody can see past, and this is the answer to a key just
            # pressed. Same reasoning as Ctrl+L.
            self.frame.announce_answer(
                "Preview on" if self.on else "Preview off")
        return self.on


class SoundBrowserDialog(wx.Dialog):
    """Find a sound by listening to it rather than by reading its name.

    Tony, 4 September 2026: "could I press alt P P to turn on preview mode,
    so, when I arrow to a sound, it plays it once... just making it easier to
    be exact with finding sounds". Anybody who has a folder called Stings with
    forty files in it knows why: the names do not tell you which is which, and
    assigning, pressing, hearing, clearing and assigning again is four steps
    per guess.

    It is this app's own browser rather than the Windows one, and not for
    want of trying. The native dialog cannot report what is highlighted:
    wxPython does not expose SetExtraControlCreator, and without it
    GetCurrentlySelectedFilename returns an empty string on Windows every time
    it is asked. Measured, not assumed. **Browse with Windows** is still on
    this dialog for typing a path or reaching a network share.

    The preview waits a moment before it plays. The screen reader is saying
    the file name at the instant you arrow onto it, and a sound landing on top
    of that takes the name away, which is the opposite of the point.
    """

    #: Column numbers, so nothing here counts on its fingers.
    COL_NAME, COL_KIND = 0, 1

    def __init__(self, parent, start_dir="", title="Choose a sound",
                 frame=None):
        super().__init__(parent, title=title,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame
        self.board = getattr(frame, "board", None)
        self.mixer = getattr(frame, "mixer", None)
        self.chosen = None
        self._rows = []
        self.folder = start_dir if os.path.isdir(start_dir) else _home_folder()

        outer = wx.BoxSizer(wx.VERTICAL)

        outer.Add(wx.StaticText(self, label=(
            "Arrow through the list. Enter opens a folder or chooses a sound.\n"
            "Backspace goes up one folder. Turn on preview and each sound "
            "plays as you reach it.")), 0, wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="&Folder"), 0, wx.LEFT | wx.TOP, 10)
        self.folder_box = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.folder_box.SetName("Folder")
        self.folder_box.SetToolTip(
            "Type a folder and press Enter to go there.")
        outer.Add(self.folder_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        outer.Add(wx.StaticText(self, label="&Sounds and folders"), 0,
                  wx.LEFT | wx.TOP, 10)
        self.list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
            size=self.FromDIP(wx.Size(520, 300)))
        self.list.SetName("Sounds and folders")
        self.list.InsertColumn(self.COL_NAME, "Name", width=self.FromDIP(340))
        self.list.InsertColumn(self.COL_KIND, "Type", width=self.FromDIP(140))
        outer.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # The preview switch. A real check box, so it has a mnemonic, a state
        # a screen reader reads back, and somewhere obvious to find it.
        self.preview = wx.CheckBox(
            self, label="&Play each sound as I reach it")
        self.preview.SetName("Play each sound as I reach it")
        self.preview.SetValue(bool(getattr(self.board, "preview_sounds", False)))
        self.preview.SetToolTip(
            "Alt+P. Each sound plays once when you land on it, and stops when "
            "you move on. It comes out of your ordinary output at the sound "
            "volume, so it sounds the way the pad will sound.")
        outer.Add(self.preview, 0, wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler, tip in (
                ("&Up one folder", self._on_up, "Go to the folder above this one"),
                ("&Browse with Windows...", self._on_native,
                 "Open the ordinary Windows file window, for typing a path or "
                 "reaching a network drive")):
            button = wx.Button(self, label=label)
            button.SetToolTip(tip)
            button.Bind(wx.EVT_BUTTON, handler)
            row.Add(button, 0, wx.RIGHT, 6)
        outer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
                  0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)

        # Landing on a row starts the clock; the clock is what plays it.
        self._preview_timer = wx.Timer(self)
        self._stop_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_preview_due, self._preview_timer)
        self.Bind(wx.EVT_TIMER, self._on_preview_over, self._stop_timer)

        self.list.Bind(wx.EVT_LIST_ITEM_FOCUSED, self._on_moved)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_moved)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._activate())
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.folder_box.Bind(wx.EVT_TEXT_ENTER, self._on_typed_folder)
        self.preview.Bind(wx.EVT_CHECKBOX, self._on_preview_toggled)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._fill()
        self.list.SetFocus()

    # -------------------------------------------------------------- filling --
    def _fill(self, land_on=None):
        """Read the folder into the list. Folders first, then sounds."""
        self._stop_preview()
        folders, files = [], []
        try:
            for name in sorted(os.listdir(self.folder), key=str.lower):
                full = os.path.join(self.folder, name)
                if os.path.isdir(full):
                    folders.append((name, full, True))
                elif audiofile.is_supported(name):
                    files.append((name, full, False))
        except OSError as exc:
            wx.MessageBox("That folder cannot be read.\n\n%s" % exc,
                          "Cannot open the folder", wx.OK | wx.ICON_ERROR, self)

        rows = []
        parent = os.path.dirname(self.folder.rstrip("\\/"))
        if parent and parent != self.folder and os.path.isdir(parent):
            # A row rather than only a button: going up is the commonest move
            # in here and it should be reachable without leaving the list.
            rows.append(("Up one folder", parent, True))
        rows.extend(folders)
        rows.extend(files)
        self._rows = rows

        self.list.Freeze()
        try:
            self.list.DeleteAllItems()
            for index, (name, full, is_dir) in enumerate(rows):
                self.list.InsertItem(index, name)
                self.list.SetItem(index, self.COL_KIND,
                                  "Folder" if is_dir else
                                  os.path.splitext(full)[1].lstrip(".").upper()
                                  + " sound")
        finally:
            self.list.Thaw()

        self.folder_box.ChangeValue(self.folder)
        if rows:
            where = 0
            if land_on:
                for index, (_n, full, _d) in enumerate(rows):
                    if os.path.normcase(full) == os.path.normcase(land_on):
                        where = index
                        break
            self.list.Select(where)
            self.list.Focus(where)
        self._say_count(len(folders), len(files))

    def _say_count(self, folders, files):
        if self.frame is None:
            return
        self.frame.announce_help(
            "%s. %d sound%s, %d folder%s"
            % (os.path.basename(self.folder.rstrip("\\/")) or self.folder,
               files, "" if files == 1 else "s",
               folders, "" if folders == 1 else "s"))

    # ---------------------------------------------------------- the cursor --
    def _current(self):
        """(name, path, is_folder) for the row the cursor is on, or None."""
        index = self.list.GetFocusedItem()
        if index == wx.NOT_FOUND or not (0 <= index < len(self._rows)):
            return None
        return self._rows[index]

    def _on_moved(self, event):
        event.Skip()
        # Whatever was playing belongs to the row you have just left.
        self._stop_preview()
        if not self.preview.GetValue():
            return
        current = self._current()
        if current is None or current[2]:
            return
        self._preview_timer.Start(C.PREVIEW_DELAY_MS, oneShot=True)

    def _on_preview_due(self, _event):
        current = self._current()
        if current is None or current[2] or self.mixer is None:
            return
        try:
            self.mixer.play_preview(current[1])
        except Exception:
            return                  # a file that will not open is not a crash
        self._stop_timer.Start(int(C.PREVIEW_MAX_SECONDS * 1000), oneShot=True)

    def _on_preview_over(self, _event):
        self._stop_preview()

    def _stop_preview(self):
        self._preview_timer.Stop()
        self._stop_timer.Stop()
        if self.mixer is not None:
            try:
                self.mixer.stop_preview()
            except Exception:
                pass

    def _on_preview_toggled(self, event):
        event.Skip()
        if self.board is not None:
            self.board.preview_sounds = bool(self.preview.GetValue())
        if self.preview.GetValue():
            self._on_moved(_Dummy())
        else:
            self._stop_preview()

    # --------------------------------------------------------------- input --
    def _on_key(self, event):
        code = event.GetKeyCode()
        if code == wx.WXK_BACK or (event.AltDown() and code == wx.WXK_UP):
            self._on_up(None)
            return
        event.Skip()

    def _activate(self):
        """Enter, or a double click. Open a folder, or take a sound."""
        current = self._current()
        if current is None:
            return
        if current[2]:
            self._go(current[1], land_on=self.folder)
            return
        self._choose(current[1])

    def _go(self, folder, land_on=None):
        if not os.path.isdir(folder):
            return
        self.folder = os.path.abspath(folder)
        self._fill(land_on=land_on)
        self.list.SetFocus()

    def _on_up(self, _event):
        parent = os.path.dirname(self.folder.rstrip("\\/"))
        if parent and parent != self.folder and os.path.isdir(parent):
            self._go(parent, land_on=self.folder)
        elif self.frame is not None:
            self.frame.announce("That is the top of this drive")

    def _on_typed_folder(self, event):
        event.Skip()
        typed = self.folder_box.GetValue().strip().strip('"')
        if os.path.isdir(typed):
            self._go(typed)
        elif os.path.isfile(typed) and audiofile.is_supported(typed):
            self._choose(typed)
        elif self.frame is not None:
            self.frame.announce("There is no folder called that")

    def _on_ok(self, event):
        current = self._current()
        if current is not None and current[2]:
            # OK on a folder means open it, which is what pressing Enter on it
            # does. Closing the dialog with a folder as the answer would hand
            # the caller something it cannot play.
            self._activate()
            return
        if current is None:
            event.Skip()
            return
        self._choose(current[1])

    def _choose(self, path):
        self._stop_preview()
        self.chosen = path
        self.EndModal(wx.ID_OK)

    def _on_native(self, _event):
        """The ordinary Windows window, which previews too.

        Tony prefers this layout and so do most people: it is the window they
        already know. Alt+P switches previewing on and off in there, because a
        native dialog has nowhere to put a check box of ours.
        """
        self._stop_preview()
        current = self._current()
        with wx.FileDialog(self, "Choose a sound", wildcard=C.AUDIO_WILDCARD,
                           defaultDir=self.folder,
                           defaultFile=(os.path.basename(current[1])
                                        if current and not current[2] else ""),
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            with NativePreview(dialog, self.frame,
                               on=self.preview.GetValue()) as preview:
                chosen = dialog.ShowModal() == wx.ID_OK
                still_on = preview.on
            # Alt+P in there is the same switch as the box out here.
            if still_on != self.preview.GetValue():
                self.preview.SetValue(still_on)
            if chosen:
                self._choose(dialog.GetPath())

    def _on_close(self, event):
        self._stop_preview()
        event.Skip()

    def EndModal(self, code):
        self._stop_preview()
        return super().EndModal(code)


class _Dummy:
    """A stand-in for an event, for the one place that calls a handler."""

    def Skip(self):
        pass


def _home_folder():
    for candidate in (os.path.expanduser("~\\Music"), os.path.expanduser("~")):
        if os.path.isdir(candidate):
            return candidate
    return os.getcwd()


def audio_file_dialog(parent, start_dir="", title="Choose a sound", frame=None):
    """Shared open dialog, remembering where the user was last time.

    This app's own browser, so a sound can be auditioned while you look for
    it. Falls back to the Windows one if anything at all goes wrong building
    it: choosing a file is not something to lose over a preview.
    """
    try:
        with SoundBrowserDialog(parent, start_dir, title,
                                frame=frame or parent) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            return dialog.chosen
    except Exception:
        holder = frame or parent
        with wx.FileDialog(parent, title, wildcard=C.AUDIO_WILDCARD,
                           defaultDir=start_dir if os.path.isdir(start_dir) else "",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            with NativePreview(dialog, holder,
                               on=bool(getattr(getattr(holder, "board", None),
                                               "preview_sounds", False))):
                if dialog.ShowModal() != wx.ID_OK:
                    return None
            return dialog.GetPath()


class FeedbackDialog(wx.Dialog):
    """Say what happened, pick what kind of thing it is, send it.

    Two controls and a read-back. The read-back is the part that matters: it
    shows exactly what will leave the machine, because a window that says
    "diagnostics are attached" and does not say which is asking to be trusted
    rather than earning it.
    """

    def __init__(self, parent, frame=None):
        super().__init__(parent, title="Submit feedback",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = frame

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label=(
            "Tell us what happened, or what would make this better.\n"
            "It goes straight to the person who wrote the app.")),
            0, wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="What &kind of feedback"), 0,
                  wx.LEFT | wx.RIGHT, 10)
        self.kind = wx.Choice(self, choices=[label for _key, label
                                             in feedback.TYPES])
        self.kind.SetName("What kind of feedback")
        self.kind.SetSelection(0)
        self.kind.Bind(wx.EVT_CHOICE, lambda _e: self._refresh())
        outer.Add(self.kind, 0, wx.EXPAND | wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="&Your message"), 0,
                  wx.LEFT | wx.RIGHT, 10)
        self.message = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.message.SetName("Your message")
        self.message.Bind(wx.EVT_TEXT, lambda _e: self._refresh())
        outer.Add(self.message, 1, wx.EXPAND | wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="What will be &sent"), 0,
                  wx.LEFT | wx.RIGHT, 10)
        self.preview = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        self.preview.SetName("What will be sent")
        outer.Add(self.preview, 1, wx.EXPAND | wx.ALL, 10)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.submit = self.FindWindowById(wx.ID_OK)
        if self.submit is not None:
            self.submit.SetLabel("&Submit")
            self.submit.Enable(False)
        cancel = self.FindWindowById(wx.ID_CANCEL)
        if cancel is not None:
            cancel.SetLabel("Cancel")
        outer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self.SetSizerAndFit(outer)
        self.SetSize((640, 560))
        self._refresh()
        self.kind.SetFocus()

    @property
    def feedback_type(self):
        index = self.kind.GetSelection()
        if index < 0:
            return feedback.TYPES[0][0]
        return feedback.TYPES[index][0]

    @property
    def text(self):
        return self.message.GetValue().strip()

    def _refresh(self):
        """Keep the read-back honest as the message is typed."""
        report = feedback.build(self.feedback_type, self.text, self.frame)
        self.preview.SetValue(feedback.readable(report))
        if self.submit is not None:
            # Nothing to send is not a thing to send. An empty report is
            # refused by the server anyway, and would sit in the queue for
            # ever being retried.
            self.submit.Enable(bool(self.text))


class SourceControlDialog(wx.Dialog):
    """Mute, solo, rename or remove a source, while the show is going out.

    Tony asked for this twice, and the second shape is the one that is here.

    5 September 2026: "a running source list that has a mute or solo option
    next to each one... arrow up and down to read the individual sources that
    are enabled and left and right arrow to cycle between mute, solo, rename,
    or delete." That shipped, and left and right cycling an action is a MODE:
    something to remember, and something the window has to keep announcing
    because nothing on screen says which of the four you are on.

    8 September 2026: "can you turn mute and solo actions into checkboxes,
    checked for soloed or muted... and the rename and delete functions are
    buttons." Which is right, and it is right for a reason worth keeping.
    **Mute and solo are STATES and rename and remove are ACTIONS.** A check
    box is what a state looks like in Windows: it reads out "checked" or "not
    checked" when you arrive on it without being asked, and Space toggles it
    the way Space toggles every check box anywhere. A button is what an
    action looks like. The mode is gone.

    **Two check boxes below the list, rather than ticks inside it.** A
    wx.ListCtrl has one check box per ROW, not per column, so it could carry
    mute or solo but never both. The list goes on saying both as columns,
    which is what a screen reader reads while arrowing, and the check boxes
    act on whichever row the cursor is on.

    Every source keeps a number, and it is the position in the list rather
    than anything to do with the name. Renaming one does not renumber it, and
    the number is what you say out loud when you are telling somebody which
    fader you mean.
    """


    def __init__(self, parent):
        super().__init__(parent, title="Source control",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = parent
        self.changed = False
        #: True while the check boxes are being set to match the selected
        #: row. Without it, SetValue raises EVT_CHECKBOX, the handler applies
        #: that value straight back to the source, and arrowing down a list
        #: silently mutes everything it touches.
        self._syncing = False

        outer = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(
            self, label="Up and down choose a source. Tab to the boxes and "
                        "buttons for what to do with it.")
        note.Wrap(self.FromDIP(520))
        outer.Add(note, 0, wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="&Sources"), 0,
                  wx.LEFT | wx.RIGHT, 10)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
                                size=(540, 190))
        self.list.SetName("Sources")
        self.list.InsertColumn(0, "Number", width=70)
        self.list.InsertColumn(1, "Source", width=210)
        self.list.InsertColumn(2, "Muted", width=70)
        self.list.InsertColumn(3, "Solo", width=60)
        self.list.InsertColumn(4, "On air", width=70)
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_row)
        outer.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        # The two states. Their labels never change, because a control's
        # accessible name must not be rewritten on a VALUE change: it is the
        # tick that carries the value, and rewriting the name restarts the
        # announcement mid sentence.
        states = wx.BoxSizer(wx.HORIZONTAL)
        self.muted = wx.CheckBox(self, label="&Muted")
        self.muted.SetToolTip("This source stops going out, and stops being "
                              "recorded. You go on hearing everything else.")
        self.muted.Bind(wx.EVT_CHECKBOX, self._on_muted)
        states.Add(self.muted, 0, wx.RIGHT, 18)
        self.soloed = wx.CheckBox(self, label="S&olo")
        self.soloed.SetToolTip("Only the soloed sources go out. Everything "
                               "else is silent until nothing is soloed.")
        self.soloed.Bind(wx.EVT_CHECKBOX, self._on_soloed)
        states.Add(self.soloed, 0)
        outer.Add(states, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.doing = wx.StaticText(self, label="")
        outer.Add(self.doing, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # The two actions, beside the Close button rather than inside the
        # standard sizer: neither is an OK or a Cancel, and Windows moves
        # anything put in there to where it thinks it belongs.
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.rename = wx.Button(self, label="&Rename...")
        self.rename.Bind(wx.EVT_BUTTON, lambda _e: self._do_rename())
        row.Add(self.rename, 0, wx.RIGHT, 8)
        self.remove = wx.Button(self, label="Remo&ve...")
        self.remove.Bind(wx.EVT_BUTTON, lambda _e: self._do_remove())
        row.Add(self.remove, 0)
        row.AddStretchSpacer()
        close = wx.Button(self, wx.ID_CANCEL, "&Close")
        row.Add(close, 0)
        outer.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizerAndFit(outer)
        self.SetEscapeId(wx.ID_CANCEL)
        self.refresh(0)
        self.list.SetFocus()

    # --------------------------------------------------------------- rows --
    def rows(self):
        return self.frame.source_rows()

    def refresh(self, keep=None):
        if keep is None:
            keep = max(0, self.list.GetFirstSelected())
        self.list.DeleteAllItems()
        soloed = self.frame.anything_soloed()
        for at, (kind, label, holder) in enumerate(self.rows()):
            number = "Mic" if kind == "mic" else str(at)
            self.list.InsertItem(at, number)
            self.list.SetItem(at, 1, label)
            self.list.SetItem(at, 2, "yes" if holder.muted else "no")
            self.list.SetItem(at, 3, "yes" if holder.soloed else "no")
            if kind == "mic":
                live = bool(getattr(holder, "on_air", False))
            else:
                live = holder.wants_air(soloed)
            self.list.SetItem(at, 4, "yes" if live else "no")
        if self.list.GetItemCount():
            keep = max(0, min(keep, self.list.GetItemCount() - 1))
            self.list.Select(keep)
            self.list.Focus(keep)
        self._show_action()

    def _selected(self):
        at = self.list.GetFirstSelected()
        rows = self.rows()
        return rows[at] if 0 <= at < len(rows) else None

    def _show_action(self, speak=False):
        """Point the check boxes and buttons at the row the cursor is on.

        `_syncing` is not optional. SetValue raises EVT_CHECKBOX in wx, so
        without it every arrow keypress would run the handler and write the
        newly displayed value straight back onto the source, which on a list
        of eight would look like arrowing down muted everything it touched.
        """
        chosen = self._selected()
        self._syncing = True
        try:
            if chosen is None:
                self.doing.SetLabel("")
                for control in (self.muted, self.soloed, self.rename,
                                self.remove):
                    control.Enable(False)
                return
            kind, label, holder = chosen
            self.muted.Enable(True)
            self.soloed.Enable(True)
            self.muted.SetValue(bool(holder.muted))
            self.soloed.SetValue(bool(holder.soloed))
            # The microphone is not one of the user's sources: it has its own
            # settings and Ctrl+M. Disabled, not hidden, so the reason can be
            # read rather than guessed at from an absence.
            self.rename.Enable(kind != "mic")
            self.remove.Enable(kind != "mic")
            self.doing.SetLabel(
                "%s. The boxes and buttons below act on this one." % label
                if kind != "mic" else
                "%s. It cannot be renamed or removed; Ctrl+M turns it off."
                % label)
        finally:
            self._syncing = False
        if speak and chosen is not None:
            self._speak(chosen[1])

    # ---------------------------------------------------- the two states --
    def _on_muted(self, _event=None):
        if self._syncing:
            return
        chosen = self._selected()
        if chosen is None:
            return
        _kind, label, holder = chosen
        holder.muted = bool(self.muted.GetValue())
        self.frame.apply_source_mixing()
        self.changed = True
        self._speak("%s %s" % (label, "muted" if holder.muted else "unmuted"))
        self.refresh(self.list.GetFirstSelected())

    def _on_soloed(self, _event=None):
        if self._syncing:
            return
        chosen = self._selected()
        if chosen is None:
            return
        _kind, label, holder = chosen
        holder.soloed = bool(self.soloed.GetValue())
        self.frame.apply_source_mixing()
        self.changed = True
        if holder.soloed:
            self._speak("%s soloed. Everything else is silent." % label)
        else:
            self._speak("%s no longer soloed%s"
                        % (label, "" if self.frame.anything_soloed()
                           else ". Everything is back"))
        self.refresh(self.list.GetFirstSelected())

    # --------------------------------------------------- the two actions --
    def _do_rename(self):
        chosen = self._selected()
        if chosen is None:
            return
        kind, _label, holder = chosen
        if kind == "mic":
            self._speak("The microphone is always called the microphone")
            return
        at = self.list.GetFirstSelected()
        self._rename(holder)
        self.refresh(at)
        self.list.SetFocus()

    def _do_remove(self):
        chosen = self._selected()
        if chosen is None:
            return
        kind, label, holder = chosen
        if kind == "mic":
            self._speak("The microphone cannot be removed. "
                        "Ctrl+M turns it off.")
            return
        at = self.list.GetFirstSelected()
        self._remove(holder, label)
        # The row that was removed is gone, so the cursor lands on the one
        # that took its place rather than off the end of the list.
        self.refresh(min(at, max(0, self.list.GetItemCount() - 2)))
        self.list.SetFocus()

    # --------------------------------------------------------------- keys --
    def _on_row(self, event):
        self._show_action()
        event.Skip()

    def _on_key(self, event):
        code = event.GetKeyCode()
        # F2 renames and Delete removes, the same two keys as everywhere else
        # in this app and in Windows. They are shortcuts to the buttons rather
        # than a second way of doing it.
        if code == wx.WXK_F2:
            self._do_rename()
            return
        if code in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
            self._do_remove()
            return
        # A digit jumps to that source, which is what the numbers are for.
        if ord("1") <= code <= ord("8"):
            at = code - ord("1") + 1
            if at < self.list.GetItemCount():
                self.list.Select(at)
                self.list.Focus(at)
            return
        if code == ord("0") and self.list.GetItemCount():
            self.list.Select(0)
            self.list.Focus(0)
            return
        event.Skip()

    def _rename(self, source):
        name = ask_text(self, "What should this source be called?",
                        "Rename a source", source.name)
        if name is None:
            self._speak("Left as %s" % source.name)
            return
        name = name.strip()
        if not name or name == source.name:
            return
        source.name = name
        self._save()
        self.changed = True
        self._speak("Renamed to %s" % name)

    def _remove(self, source, label):
        if wx.MessageBox("Remove %s?\n\nIt stops going out and its settings "
                         "are forgotten." % label, "Remove a source",
                         wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                         self) != wx.YES:
            self._speak("Kept")
            return
        try:
            source.close()
        except Exception:
            pass
        self.frame.sources = [s for s in self.frame.sources if s is not source]
        self.frame.source_group.sources = self.frame.sources
        self._save()
        self.frame.apply_source_mixing()
        self.changed = True
        self._speak("Removed %s" % label)

    def _save(self):
        self.frame.board.sources = [s.to_dict() for s in self.frame.sources]
        self.frame._touch()

    def _speak(self, text):
        speaker = getattr(self.frame, "announce_answer", None)
        if speaker is not None:
            speaker(text)


class SourcesDialog(wx.Dialog):
    """Other things to put on the air besides your own voice.

    Tony, 5 September 2026: "Add sources to a running stream, so in addition
    to the microphone, it also can catch the audio from teamtalk.exe or,
    Google Chrome chrome.exe."

    A list, and the settings for whichever row you are on underneath it. Not a
    row of little windows: with a screen reader, one list you arrow down and
    one set of controls that follow it is far less to hear than a separate
    dialog per source, and it is the same shape as the Voice tab.
    """

    CHANNELS = [("mix", "Both, mixed together"), ("left", "Left only"),
                ("right", "Right only")]

    def __init__(self, parent, entries=None):
        super().__init__(parent, title="Audio sources",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.entries = [dict(entry) for entry in (entries or [])]
        self.devices = sources.available_inputs()
        self._loading = False

        outer = wx.BoxSizer(wx.VERTICAL)
        self._say(outer,
                  "Other things to put on the air besides your own voice. A "
                  "source can be a sound card or a cable, or it can be one "
                  "program: Windows hands over exactly what that program is "
                  "playing and nothing else, with no setting up in the "
                  "program itself. Your screen reader is in the list too, so "
                  "you can put it on air.")

        outer.Add(wx.StaticText(self, label="&Sources"), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
                                size=(560, 150))
        self.list.SetName("Sources")
        self.list.InsertColumn(0, "Name", width=140)
        self.list.InsertColumn(1, "Kind", width=80)
        self.list.InsertColumn(2, "Taking from", width=210)
        self.list.InsertColumn(3, "On air", width=70)
        self.list.InsertColumn(4, "You hear it", width=90)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_pick)
        outer.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        add = wx.Button(self, label="&Add a source")
        add.Bind(wx.EVT_BUTTON, self._on_add)
        buttons.Add(add, 0, wx.RIGHT, 8)
        self.remove = wx.Button(self, label="&Remove this one")
        self.remove.Bind(wx.EVT_BUTTON, self._on_remove)
        buttons.Add(self.remove, 0)
        outer.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        grid = wx.FlexGridSizer(0, 2, 8, 8)
        grid.AddGrowableCol(1, 1)

        def field(label, make, name):
            text = wx.StaticText(self, label=label)
            grid.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
            control = make()
            name_field(control, name)
            grid.Add(control, 1, wx.EXPAND)
            return control

        self.name = field("Call&ed", lambda: wx.TextCtrl(self), "Called")
        self.name.Bind(wx.EVT_TEXT, self._on_edit)

        self.kind = field(
            "&Take audio from",
            lambda: wx.Choice(self, choices=["A sound card or cable",
                                             "One program"]),
            "Take audio from")
        self.kind.Bind(wx.EVT_CHOICE, self._on_kind)

        self.device = field(
            "&Device",
            lambda: wx.Choice(self, choices=["Nothing chosen"] + [
                "%s - %s" % (d["name"], d["hostapi"]) for d in self.devices]),
            "Device")
        self.device.Bind(wx.EVT_CHOICE, self._on_edit)

        self.program = field(
            "&Program",
            lambda: wx.Choice(self, choices=["Nothing chosen"]),
            "Program")
        self.program.Bind(wx.EVT_CHOICE, self._on_edit)
        self._program_names = [""]
        self._refresh_programs()

        self.channel = field(
            "Which &channel",
            lambda: wx.Choice(self, choices=[t for _k, t in self.CHANNELS]),
            "Which channel")
        self.channel.Bind(wx.EVT_CHOICE, self._on_edit)

        self.gain = field(
            "&Gain in decibels",
            lambda: wx.Slider(self, value=0, minValue=int(C.MIN_MIC_GAIN_DB),
                              maxValue=int(C.MAX_MIC_GAIN_DB),
                              style=wx.SL_HORIZONTAL),
            "Gain in decibels")
        self.gain.Bind(wx.EVT_SLIDER, self._on_edit)
        outer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.on_air = wx.CheckBox(self, label="Put this on the a&ir")
        self.on_air.Bind(wx.EVT_CHECKBOX, self._on_edit)
        outer.Add(self.on_air, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.monitor = wx.CheckBox(self, label="&Hear it yourself")
        self.monitor.SetToolTip(
            "Off, it goes out and you do not hear it, which is right when the "
            "sound is already coming out of your speakers from the program "
            "itself. On, it comes back through your monitor output.")
        self.monitor.Bind(wx.EVT_CHECKBOX, self._on_edit)
        outer.Add(self.monitor, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.StdDialogButtonSizer()
        ok = wx.Button(self, wx.ID_OK)
        ok.SetDefault()
        row.AddButton(ok)
        row.AddButton(wx.Button(self, wx.ID_CANCEL))
        row.Realize()
        outer.Add(row, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self.SetSizerAndFit(outer)
        self._refresh(0)
        self.list.SetFocus()

    def _programs(self):
        """What can be captured, refreshed every time the picker is opened.

        Programs with a window, anything that has audio open, and every screen
        reader that is running whether it is speaking or not. Asked for again
        each time, because the whole point is to catch a program that was
        opened a minute ago.
        """
        return proccapture.running_programs()

    def _say(self, sizer, text):
        note = wx.StaticText(self, label=text)
        note.Wrap(self.FromDIP(540))
        sizer.Add(note, 0, wx.ALL, 10)

    # -------------------------------------------------------------- rows --
    @property
    def result(self):
        return [dict(entry) for entry in self.entries]

    def _selected(self):
        index = self.list.GetFirstSelected()
        return index if 0 <= index < len(self.entries) else None

    def _refresh(self, keep=None):
        self.list.DeleteAllItems()
        for row, entry in enumerate(self.entries):
            self.list.InsertItem(row, entry.get("name") or "Source")
            self._write_row(row)
        if self.entries:
            keep = max(0, min(keep if keep is not None else 0,
                              len(self.entries) - 1))
            self.list.Select(keep)
            self.list.Focus(keep)
        self._load()

    def _load(self):
        """Put the selected source into the controls underneath."""
        index = self._selected()
        on = index is not None
        for control in (self.name, self.device, self.channel, self.gain,
                        self.on_air, self.monitor, self.remove):
            control.Enable(on)
        self._loading = True
        try:
            entry = self.entries[index] if on else {}
            self.name.SetValue(entry.get("name", "") if on else "")
            self.kind.SetSelection(
                1 if entry.get("kind") == sources.Source.PROGRAM else 0)
            wanted = entry.get("device_name", "")
            found = 0
            for at, device in enumerate(self.devices):
                if device["name"] == wanted:
                    found = at + 1
                    break
            self.device.SetSelection(found if on else 0)
            keys = [key for key, _text in self.CHANNELS]
            channel = entry.get("channel", "mix")
            self.channel.SetSelection(keys.index(channel)
                                      if channel in keys else 0)
            self.gain.SetValue(int(round(float(entry.get("gain_db", 0.0) or 0))))
            self.on_air.SetValue(bool(entry.get("on_air", True)))
            self.monitor.SetValue(bool(entry.get("monitor", False)))
            self._show_for_kind(entry.get("program", "") if on else "")
        finally:
            self._loading = False

    def _on_pick(self, event):
        self._load()
        event.Skip()

    def _refresh_programs(self, wanted=""):
        """Rebuild the program list, keeping whatever was chosen."""
        found = self._programs()
        self._program_names = [""] + [entry["name"] for entry in found]
        labels = ["Nothing chosen"] + [self._program_label(entry)
                                       for entry in found]
        # A program that was chosen and has since been closed stays in the
        # list, or choosing it again would mean starting it first.
        if wanted and wanted not in self._program_names:
            self._program_names.append(wanted)
            labels.append("%s, not running" % wanted)
        self.program.Set(labels)
        self.program.SetSelection(self._program_names.index(wanted)
                                  if wanted in self._program_names else 0)

    @staticmethod
    def _program_label(entry):
        """One line in the picker, saying what it is and why it is there.

        A program with no window needs the second half of that. "obs64.exe"
        on its own reads like something has gone wrong; "obs64.exe, has audio
        open" reads like an answer.
        """
        name = entry.get("name") or ""
        title = entry.get("title") or ""
        kind = entry.get("kind") or "window"
        if kind == "reader":
            return "%s, %s screen reader" % (name, title or name)
        if title:
            return "%s, %s" % (name, title)
        if kind == "audio":
            return "%s, has audio open" % name
        return name

    def _on_kind(self, event):
        """A source is either a device or a program, never both."""
        index = self._selected()
        if index is not None and not self._loading:
            entry = self.entries[index]
            entry["kind"] = (sources.Source.PROGRAM
                             if self.kind.GetSelection() == 1
                             else sources.Source.DEVICE)
            self._load()
            self._write_row(index)
        event.Skip()

    def _show_for_kind(self, program):
        on = self.kind.GetSelection() == 1
        self.program.Enable(on)
        self.device.Enable(not on)
        self.channel.Enable(not on)
        if on:
            self._refresh_programs(program)

    def _on_edit(self, event):
        """Write the controls back into the row as they are changed."""
        if not self._loading:
            index = self._selected()
            if index is not None:
                entry = self.entries[index]
                entry["name"] = self.name.GetValue().strip() or "Source"
                at = self.device.GetSelection() - 1
                if 0 <= at < len(self.devices):
                    entry["device_name"] = self.devices[at]["name"]
                    entry["device_hostapi"] = self.devices[at]["hostapi"]
                else:
                    entry["device_name"] = ""
                    entry["device_hostapi"] = ""
                picked = self.program.GetSelection()
                entry["program"] = (self._program_names[picked]
                                    if 0 <= picked < len(self._program_names)
                                    else "")
                entry["channel"] = self.CHANNELS[
                    max(0, self.channel.GetSelection())][0]
                entry["gain_db"] = float(self.gain.GetValue())
                entry["on_air"] = self.on_air.GetValue()
                entry["monitor"] = self.monitor.GetValue()
                self._write_row(index)
        event.Skip()

    def _write_row(self, index):
        """Update the list, and only the columns.

        Rewriting the whole row moves the cursor, and moving the cursor under
        somebody who is still typing a name is how a list makes a screen
        reader start the row again mid word.
        """
        entry = self.entries[index]
        program = entry.get("kind") == sources.Source.PROGRAM
        self.list.SetItem(index, 0, entry.get("name") or "Source")
        self.list.SetItem(index, 1, "Program" if program else "Device")
        self.list.SetItem(index, 2,
                          (entry.get("program") if program
                           else entry.get("device_name")) or "nothing chosen")
        self.list.SetItem(index, 3, "yes" if entry.get("on_air") else "no")
        self.list.SetItem(index, 4, "yes" if entry.get("monitor") else "no")

    def _on_add(self, _event):
        if len(self.entries) >= sources.MAX_SOURCES:
            self._speak("That is as many sources as this will take")
            return
        self.entries.append({"name": "Source %d" % (len(self.entries) + 1),
                             "kind": sources.Source.DEVICE,
                             "device_name": "", "device_hostapi": "",
                             "program": "", "gain_db": 0.0, "channel": "mix",
                             "on_air": True, "monitor": False})
        self._refresh(len(self.entries) - 1)
        self.name.SetFocus()
        self.name.SelectAll()
        self._speak("Added. Choose what it takes audio from.")

    def _on_remove(self, _event):
        index = self._selected()
        if index is None:
            return
        gone = self.entries.pop(index)
        self._refresh(min(index, len(self.entries) - 1) if self.entries else None)
        self._speak("Removed %s" % (gone.get("name") or "it"))

    def _speak(self, text):
        speaker = getattr(self.GetParent(), "announce_answer", None)
        if speaker is not None:
            speaker(text)


class StreamStatsDialog(wx.Dialog):
    """Who is listening, and to what.

    Two things a presenter wants mid show and cannot get from the app
    otherwise: how many people are out there, and whether what the server
    thinks is playing matches what actually is.

    Everything here is asked of the server on a thread, because a station
    that has gone away takes seconds to say so and this window must not be
    one of the things that freezes when it does.

    The list is the whole window on purpose. A summary line that has to be
    hunted for is a summary line nobody reads, so it is also spoken, and it is
    spoken again only when the number CHANGES: a window that says "nobody is
    listening" every fifteen seconds is a window you close.
    """

    #: How often it asks again. Icecast counts a listener the moment they
    #: connect, so this is about how fresh the number feels rather than about
    #: catching anything.
    REFRESH_MS = 15000

    def __init__(self, parent, settings, on_air=False):
        super().__init__(parent, title="Who is listening",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.settings = dict(settings or {})
        self.on_air = bool(on_air)
        self._said = None
        self._busy = False

        outer = wx.BoxSizer(wx.VERTICAL)

        # A real label in front of it. SetName is not what a screen reader
        # reads on Windows; the static text before the control is.
        outer.Add(wx.StaticText(self, label="&What the server says"), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.summary = wx.TextCtrl(
            self, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 66),
            value="Asking the server...")
        self.summary.SetName("What the server says")
        outer.Add(self.summary, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        outer.Add(wx.StaticText(self, label="&Streams"), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(560, 200))
        self.list.SetName("Streams")
        self.list.InsertColumn(0, "Stream", width=190)
        self.list.InsertColumn(1, "Listening", width=90)
        self.list.InsertColumn(2, "Most at once", width=100)
        self.list.InsertColumn(3, "Playing", width=250)
        self.list.SetToolTip(
            "Every stream on the server, not only yours. A station running "
            "automation has its listeners on the output rather than on the "
            "feed you are sending.")
        outer.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        self.note = wx.StaticText(self, label="")
        outer.Add(self.note, 0, wx.LEFT | wx.RIGHT, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        again = wx.Button(self, label="&Ask again")
        again.Bind(wx.EVT_BUTTON, lambda _e: self.ask())
        row.Add(again, 0, wx.RIGHT, 8)
        row.AddStretchSpacer()
        close = wx.Button(self, wx.ID_CANCEL, "&Close")
        row.Add(close, 0)
        outer.Add(row, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizerAndFit(outer)
        self.SetEscapeId(wx.ID_CANCEL)
        self.list.SetFocus()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self.ask(quiet=True), self._timer)
        self._timer.Start(self.REFRESH_MS)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.ask()

    # ------------------------------------------------------------- asking --
    def ask(self, quiet=False):
        """Off the interface thread, always. A dead server takes seconds."""
        if self._busy:
            return
        self._busy = True
        settings = dict(self.settings)

        def work():
            stats = streamstats.fetch(settings)
            wx.CallAfter(self._arrived, stats, quiet)

        threading.Thread(target=work, daemon=True).start()

    def _arrived(self, stats, quiet):
        self._busy = False
        if not self:
            return                      # the window closed while it was asking
        self.summary.SetValue(stats.summary())
        self.note.SetLabel("Answered by %s" % stats.source if stats.source
                           else "")
        keep = self.list.GetFirstSelected()
        self.list.DeleteAllItems()
        for row, mount in enumerate(stats.mounts):
            name = mount.name or mount.mount or "A stream"
            if mount.ours:
                name += " (yours)"
            self.list.InsertItem(row, name)
            self.list.SetItem(row, 1, str(mount.listeners))
            self.list.SetItem(row, 2, str(mount.peak) if mount.peak else "")
            self.list.SetItem(row, 3, mount.title or "")
        if self.list.GetItemCount():
            keep = max(0, min(keep, self.list.GetItemCount() - 1))
            self.list.Select(keep)
            self.list.Focus(keep)

        # Spoken only when it has changed. Every fifteen seconds otherwise,
        # which would make the window unusable with a screen reader running.
        said = stats.summary()
        if said != self._said:
            self._said = said
            if not quiet or self.IsShown():
                speak = getattr(self.GetParent(), "announce_answer", None)
                if speak is not None:
                    speak(said)

    def _on_close(self, event):
        self._timer.Stop()
        event.Skip()


class DonateDialog(wx.Dialog):
    """The occasional word about donating. Never more than a word.

    A read-only box rather than a message box, so the whole thing can be
    arrowed back through at whatever pace suits - and so a screen reader user
    gets the same text as everybody else rather than a sentence spoken once.
    """

    MESSAGE = (
        "TG Drop Deck is free, and it will carry on being free.\n"
        "\n"
        "Donations go into development, server costs, and new products for "
        "TG Studios users. If you enjoy using Drop Deck and you would like to "
        "be part of the team, please consider a small contribution of "
        "whatever size suits you.\n"
        "\n"
        "If you would like it to be, your name goes on a public contributors "
        "list. And if you would rather not, you are a rockstar either way.\n"
        "\n"
        "This asks about once a week at most, and never in your first week. "
        "Help, Donate, is here whenever you want it.")

    def __init__(self, parent, message=None):
        super().__init__(parent, title="Drop Deck is free",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(wx.StaticText(self, label="&About donating"), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.text = wx.TextCtrl(
            self, value=message or self.MESSAGE,
            style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.text.SetName("About donating")
        outer.Add(self.text, 1, wx.EXPAND | wx.ALL, 10)

        self.never = wx.CheckBox(self, label="Do not ask me about this a&gain")
        self.never.SetToolTip(
            "Help, Donate, still opens the page whenever you want it.")
        outer.Add(self.never, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        donate = wx.Button(self, wx.ID_OK, "&Donate")
        donate.SetToolTip("Opens the TG Studios donate page in your browser")
        donate.SetDefault()
        row.Add(donate, 0, wx.RIGHT, 6)
        row.Add(wx.Button(self, wx.ID_CANCEL, "&No thank you"), 0)
        outer.Add(row, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self.SetSizerAndFit(outer)
        self.SetSize((560, 420))
        self.text.SetFocus()
        self.text.SetInsertionPoint(0)

    @property
    def never_again(self):
        return bool(self.never.GetValue())


class StreamHelpDialog(wx.Dialog):
    """How to set up each platform, in the app rather than only on the web.

    The manual is on the website so a confusing sentence can be fixed the same
    day. That is right for the manual and wrong for this: setting up streaming
    is the one job somebody does with the app open, one field at a time, and
    telling them to go and find a web page mid task is telling them to lose
    their place.

    So the steps live here too, and both come from `streamhelp.py` so they
    cannot drift apart.

    **A read only multiline box, not a web view and not a list.** A screen
    reader user can arrow through it line by line, read a word at a time, and
    copy a piece out, which is exactly what somebody following instructions
    needs. It also means the text can be as long as it needs to be.
    """

    def __init__(self, parent, platform=None):
        super().__init__(parent, title="Setting up streaming",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._platforms = list(streamhelp.ORDER)
        outer = wx.BoxSizer(wx.VERTICAL)

        # The label is built before the control, the same rule as everywhere
        # else: MSAA hands a screen reader the static text that PRECEDES a
        # control in creation order.
        outer.Add(wx.StaticText(self, label="&Which platform"), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.picker = wx.Choice(self, choices=[
            streamout.server_label(key) for key in self._platforms]
            + ["All of them, and what to do when it goes wrong"])
        name_field(self.picker, "Which platform")
        self.picker.Bind(wx.EVT_CHOICE, self._on_pick)
        outer.Add(self.picker, 0, wx.EXPAND | wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="&Instructions"), 0,
                  wx.LEFT | wx.RIGHT, 10)
        self.text = wx.TextCtrl(
            self, style=wx.TE_READONLY | wx.TE_MULTILINE | wx.TE_RICH2,
            size=(640, 420))
        name_field(self.text, "Instructions")
        outer.Add(self.text, 1, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        guide = wx.Button(self, label="Open the full &manual")
        guide.SetToolTip("Opens the whole manual on the website, which covers "
                         "everything else the app does.")
        guide.Bind(wx.EVT_BUTTON,
                   lambda _e: webbrowser.open(C.USER_GUIDE_URL))
        row.Add(guide, 0, wx.RIGHT, 8)
        row.Add(wx.Button(self, wx.ID_CLOSE, "&Close"), 0)
        outer.Add(row, 0, wx.ALL, 10)
        self.Bind(wx.EVT_BUTTON, lambda _e: self.EndModal(wx.ID_CLOSE),
                  id=wx.ID_CLOSE)
        self.SetEscapeId(wx.ID_CLOSE)

        self.SetSizerAndFit(outer)
        wanted = platform if platform in self._platforms else self._platforms[0]
        self.picker.SetSelection(self._platforms.index(wanted))
        self._on_pick(None)
        # Focus lands on the instructions rather than the picker, because
        # reading them is what this window is for.
        self.text.SetFocus()

    def _on_pick(self, event):
        if event is not None:
            event.Skip()
        index = max(0, self.picker.GetSelection())
        if index >= len(self._platforms):
            self.text.SetValue(streamhelp.everything())
        else:
            self.text.SetValue(streamhelp.as_text(self._platforms[index]))
        self.text.SetInsertionPoint(0)


# ---------------------------------------------------------------------------
# Going live, and knowing what that means
# ---------------------------------------------------------------------------

class GoLiveDialog(wx.Dialog):
    """What Ctrl+B is about to send, shown before it sends it.

    Tony, 8 September 2026: "I think it's a little confusing when pressing
    ctrl B to start streaming, how do we know what is currently live."

    The honest answer was that you could not. The app connected and told you
    afterwards, so the one moment a presenter could still change their mind
    was the one moment it said nothing. A sighted broadcaster glances at a
    rack of settings; there is no glance here, so the app has to say it.

    **Ctrl+B then Enter is still the whole gesture.** Go live is the default
    button, so the muscle memory costs one extra keypress and the presenter
    hears the destination, the format, the picture and whether their own
    microphone is on the air on the way past. Somebody who does not want it
    ticks the box and gets the old behaviour back for ever.

    A problem that would stop the broadcast disables Go live rather than
    hiding it, and Put it right opens the page that fixes it, because the
    alternative is a disabled button and no route onward.
    """

    def __init__(self, parent, report):
        super().__init__(parent, title="Go live",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.report = report
        self.fix = ""
        self.remember = False

        outer = wx.BoxSizer(wx.VERTICAL)

        # The label is built before the control, always: MSAA gives a screen
        # reader the static text preceding a control in CREATION order.
        outer.Add(wx.StaticText(self, label="&What will go out"), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 10)
        summary = "\r\n".join("%s: %s" % (label, value)
                              for label, value in report.lines)
        self.what = wx.TextCtrl(self, style=wx.TE_READONLY | wx.TE_MULTILINE,
                                size=(560, 96), value=summary)
        self.what.SetName("What will go out")
        outer.Add(self.what, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        if report.notes:
            outer.Add(wx.StaticText(self, label="Worth &knowing first"), 0,
                      wx.LEFT | wx.RIGHT | wx.TOP, 10)
            # Whatever is STOPPING the broadcast goes at the top, whatever
            # order the checks happened to run in. Reading two warnings
            # before the one sentence that says why Go live is greyed out is
            # the wrong way round, and it is the first line somebody hears.
            trouble = "\r\n".join(
                ("%s %s" % ("Stop:" if note.level == preflight.STOP
                            else "Warning:", note.text))
                for note in report.stops + report.warnings)
            self.trouble = wx.TextCtrl(
                self, style=wx.TE_READONLY | wx.TE_MULTILINE,
                size=(560, 84), value=trouble)
            self.trouble.SetName("Worth knowing first")
            outer.Add(self.trouble, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        else:
            self.trouble = None

        self.again = wx.CheckBox(
            self, label="&Do not ask again, just go live")
        self.again.SetToolTip("Ctrl+B goes straight on the air. Ctrl+Shift+B "
                              "still says what is going out, and you can turn "
                              "this back on in Preferences.")
        outer.Add(self.again, 0, wx.ALL, 10)

        row = wx.StdDialogButtonSizer()
        self.go = wx.Button(self, wx.ID_OK, "&Go live")
        row.AddButton(self.go)
        cancel = wx.Button(self, wx.ID_CANCEL, "&Stay off air")
        row.AddButton(cancel)
        row.Realize()
        # Outside the standard sizer: it is not an OK or a Cancel, and adding
        # it to a StdDialogButtonSizer moves it somewhere Windows chooses.
        fixes = [note for note in report.notes if note.fix]
        if fixes:
            self.putright = wx.Button(self, label="&Put it right...")
            self.putright.Bind(wx.EVT_BUTTON,
                               lambda _e: self._on_fix(fixes[0].fix))
            outer.Add(self.putright, 0, wx.LEFT | wx.BOTTOM, 10)
        outer.Add(row, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self.SetSizerAndFit(outer)
        self.SetEscapeId(wx.ID_CANCEL)
        if report.blocked:
            self.go.Enable(False)
            self.go.SetToolTip("Something below has to be put right first.")
            cancel.SetDefault()
        else:
            self.go.SetDefault()
        # Focus lands on the summary, not the button. It is the thing this
        # window exists to say, and a screen reader reads a read only edit box
        # when focus arrives on it. Landing on Go live would announce the
        # button and leave the answer unread.
        self.what.SetFocus()
        self.what.SetInsertionPoint(0)

    def _on_fix(self, page):
        self.fix = page
        self.EndModal(wx.ID_APPLY)

    def EndModal(self, code):
        # Read before the window goes, because the checkbox is gone by the
        # time the caller looks.
        try:
            self.remember = bool(self.again.GetValue())
        except Exception:
            pass
        super().EndModal(code)


class VideoSourceDialog(wx.Dialog):
    """What the stream is showing, and what to show instead. Alt+Shift+V.

    Tony, 8 September 2026: "what if we want to switch to a different source
    while live on air... a way to go from camera feed, to, picture, or ...
    show full screen of what's on the computer screen, or even better ... a
    split screen."

    So this is a switcher rather than a settings page, and the difference is
    that it applies at once. Up and down read the choices, Enter or Space puts
    one on the air. There is no OK: a list you have to arrow through and then
    Tab out of to confirm is not something anybody uses mid link.

    On air, the change reaches the encoder without touching the connection.
    Off air, it is remembered for the next time. Both cases save it to the
    board, so the picture is the same one next week.

    The list says which one is live, and what each one costs, because the one
    thing a presenter cannot do here is look at a preview to find out.
    """

    def __init__(self, parent, board, live=False):
        super().__init__(parent, title="Video source",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.frame = parent
        self.board = board
        self.live = bool(live)
        self.chosen = ""

        outer = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(
            self, label=("Up and down read the choices. Enter puts one on "
                         "the air." if live else
                         "Up and down read the choices. Enter picks one for "
                         "the next time you go live."))
        note.Wrap(self.FromDIP(560))
        outer.Add(note, 0, wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="&Video sources"), 0,
                  wx.LEFT | wx.RIGHT, 10)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
                                size=(580, 190))
        self.list.SetName("Video sources")
        # The name is column 0 because that is what first letter navigation
        # searches, and no "on air" marker goes in front of it for the same
        # reason. Same rule as the running order.
        self.list.InsertColumn(0, "Source", width=250)
        self.list.InsertColumn(1, "On air", width=70)
        self.list.InsertColumn(2, "What it sends", width=250)
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _e: self._apply())
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _e: self._describe())
        outer.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)

        self.doing = wx.StaticText(self, label="")
        # Room for two lines reserved BEFORE the window is fitted. The sizer
        # measures an empty label as nothing, and _describe then wraps a
        # sentence into two lines that the window has no height for, so the
        # second one is simply not there. Wrap inserts real newlines; it does
        # not make the control grow.
        self.doing.SetMinSize((-1, self.doing.GetTextExtent("Ay")[1] * 2 + 4))
        outer.Add(self.doing, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.StdDialogButtonSizer()
        close = wx.Button(self, wx.ID_CANCEL, "&Close")
        row.AddButton(close)
        row.Realize()
        outer.Add(row, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self.SetSizerAndFit(outer)
        self.SetEscapeId(wx.ID_CANCEL)
        self.refresh()
        self.list.SetFocus()

    # --------------------------------------------------------------- rows --
    def kinds(self):
        """Every source, with the ones that cannot work here left out.

        A machine with no camera is not offered a camera, and one that cannot
        be captured is not offered its screen. An entry that would always
        fail is worse than a shorter list.
        """
        out = []
        cameras = self.frame.known_cameras()
        can_screen = screen.available()
        for kind in C.PICTURE_SOURCES:
            if kind in C.PICTURE_NEEDS_CAMERA and not cameras:
                continue
            if kind in C.PICTURE_NEEDS_SCREEN and not can_screen:
                continue
            out.append(kind)
        return out

    def refresh(self, keep=None):
        if keep is None:
            keep = max(0, self.list.GetFirstSelected())
        self.list.DeleteAllItems()
        rows = self.kinds()
        for at, kind in enumerate(rows):
            self.list.InsertItem(at, C.PICTURE_LABELS.get(kind, kind))
            self.list.SetItem(at, 1, "yes" if kind == self.board.picture
                              else "no")
            self.list.SetItem(at, 2, C.PICTURE_DESCRIPTIONS.get(kind, ""))
        if rows:
            if self.board.picture in rows and not self.list.GetFirstSelected() > 0:
                keep = rows.index(self.board.picture)
            keep = max(0, min(keep, len(rows) - 1))
            self.list.Select(keep)
            self.list.Focus(keep)
        self._describe()

    def _selected(self):
        at = self.list.GetFirstSelected()
        rows = self.kinds()
        return rows[at] if 0 <= at < len(rows) else ""

    def _describe(self):
        kind = self._selected()
        if not kind:
            self.doing.SetLabel("")
            return
        label = C.PICTURE_LABELS.get(kind, kind).lower()
        if kind == self.board.picture:
            said = ("This is the one going out now." if self.live
                    else "This is the one chosen.")
        elif self.live:
            said = "Enter puts %s on the air." % label
        else:
            said = "Enter picks %s." % label
        # The full sentence, under the list. The column shows it truncated
        # with an ellipsis because the text is longer than any sensible
        # column, and a sighted reader has nowhere else to find the rest.
        # A screen reader always gets the whole cell, so this is the half of
        # the window that was only wrong to look at.
        detail = C.PICTURE_DESCRIPTIONS.get(kind, "")
        self.doing.SetLabel("%s  %s" % (said, detail) if detail else said)
        self.doing.Wrap(self.FromDIP(600))

    # ---------------------------------------------------------------- keys --
    def _on_key(self, event):
        code = event.GetKeyCode()
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            self._apply()
            return
        event.Skip()

    def _apply(self):
        kind = self._selected()
        if not kind:
            return
        said = self.frame.set_video_source(kind)
        self.chosen = kind
        self.refresh()
        if said:
            self.doing.SetLabel(said)
