"""The dialogs.

Every one of them is keyboard-complete and every control has a name, because a
dialog you cannot get out of without a mouse is worse than no dialog.
"""

from __future__ import annotations

import ctypes
import os
import time

import wx

from . import audiofile
from . import constants as C
from . import feedback
from . import streamout
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
        outer.Add(self.name_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        caption("&Level in decibels")
        self.level = wx.Slider(self, value=int(round(slot.trim_db)),
                               minValue=-24, maxValue=12, style=wx.SL_HORIZONTAL)
        self.level.SetName("Level in decibels")
        outer.Add(self.level, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.loop_box = None
        if slot.is_bed:
            self.loop_box = wx.CheckBox(self, label="Loop this &bed")
            self.loop_box.SetValue(bool(slot.loop))
            outer.Add(self.loop_box, 0, wx.ALL, 10)

        self.hotkey_readout = None
        if slot.bank == C.BANK_MISC:
            caption("Hotke&y, inside this app")
            self.hotkey_readout = self._readout(
                outer, key_label(self._key_code, self._modifiers) or "None")
            self._button(outer, "C&hoose a hotkey...", self._on_change_hotkey)

        caption("&Global hotkey, which works from any program")
        self.global_readout = self._readout(outer, self._global_hotkey or "None")
        self._button(outer, "Cho&ose a global hotkey...", self._on_change_global)

        caption("&File")
        self.file_readout = self._readout(outer, self._file_text())

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
    def _readout(self, sizer, value):
        """A read-only field, so a screen reader can read a value it cannot
        otherwise reach and a mouse user can see one that would not fit."""
        ctrl = wx.TextCtrl(self, value=value, style=wx.TE_READONLY)
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
            "key_code": self._key_code,
            "modifiers": self._modifiers,
            "custom_hotkey": key_label(self._key_code, self._modifiers) or None,
            "global_hotkey": self._global_hotkey or None,
        }


class SettingsDialog(wx.Dialog):
    """Everything you can set, on six tabs.

    It was one long column: output, routing, speech, ducking, bed fades,
    crossfade, and then the end of track beep on the end of that. Every
    setting the app has, in the order they happened to be added, with no way
    to find the one you came for except to read past all the others. The
    microphone had a dialog of its own on a different key, which meant two
    places to look and two things to remember.

    Tabs, and one dialog. `Ctrl+P` opens it on Output and `Ctrl+Shift+M` opens
    it on Microphone; they are the same window. Ctrl+Tab moves between the
    tabs, and a screen reader reads a tab name when you land on it, which is
    the whole reason this is a notebook rather than six group boxes.
    """

    #: The tabs, in order. Named rather than numbered at the call sites, so
    #: adding one in the middle does not open the wrong page somewhere else.
    (PAGE_OUTPUT, PAGE_SOUND, PAGE_PLAYLIST, PAGE_MIC, PAGE_STREAM,
     PAGE_SPEECH) = range(6)

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
        self._build_stream_tab()
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
                self.PAGE_STREAM: self.stream_server,
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
            choice = wx.Choice(panel, choices=["Main output"] + self.choices[1:])
            # Named for the screen reader, because four identical unlabelled
            # dropdowns in a column are indistinguishable by ear.
            choice.SetName(f"{title} output")
            choice.SetSelection(self._bank_selection(bank))
            self.bank_choices[bank] = choice
            grid.Add(wx.StaticText(panel, label=title), 0,
                     wx.ALIGN_CENTER_VERTICAL)
            grid.Add(choice, 1, wx.EXPAND)
        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

    def _build_sound_tab(self):
        panel, sizer = self._page("Sounds and beds")

        self.duck_on = wx.CheckBox(
            panel, label="&Duck the music beds under sounds and drops")
        self.duck_on.SetValue(bool(self.board.ducking))
        sizer.Add(self.duck_on, 0, wx.ALL, 10)

        self._label(panel, sizer, "Duck &depth in decibels")
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
        self.crossfade_ctrl.SetName("Playlist crossfade, seconds")
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
        self.warn_seconds_ctrl.SetName("Seconds before the end to beep")
        self.warn_seconds_ctrl.SetToolTip(
            "How long before a track's music stops the beep sounds. Ten is a "
            "usual answer. Nothing shorter than this plus a second gets one, "
            "so a short ident does not beep the moment it starts.")
        warn_row.Add(self.warn_seconds_ctrl, 0)
        sizer.Add(warn_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.warn_seconds_ctrl.Enable(self.warn_on.GetValue())
        self.warn_on.Bind(
            wx.EVT_CHECKBOX,
            lambda e: (self.warn_seconds_ctrl.Enable(e.IsChecked()), e.Skip()))

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
        self.mic_output.SetName("Monitor output")
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

    def _build_stream_tab(self):
        """Where the show goes, and a button that proves it before air.

        Every field here is one somebody has to be told by whoever runs the
        server, so the labels use the words a station uses rather than the
        words the protocol uses. The Test button exists because the only
        moment a broadcaster finds out a password is wrong should not be the
        moment the show starts.
        """
        panel, sizer = self._page("Streaming")

        grid = wx.FlexGridSizer(2, 8, 12)
        grid.AddGrowableCol(1, 1)

        def row(label, control, tip=""):
            grid.Add(wx.StaticText(panel, label=label), 0,
                     wx.ALIGN_CENTER_VERTICAL)
            if tip:
                control.SetToolTip(tip)
            grid.Add(control, 0, wx.EXPAND)
            return control

        self.stream_server = wx.Choice(
            panel, choices=[label for label, _cls
                            in (streamout.SERVERS[key]
                                for key in C.STREAM_SERVER_ORDER)])
        self.stream_server.SetName("Server type")
        self.stream_server.SetSelection(
            C.STREAM_SERVER_ORDER.index(self.board.stream_server)
            if self.board.stream_server in C.STREAM_SERVER_ORDER else 0)
        row("Ser&ver", self.stream_server,
            "Icecast covers almost everything, including the Liquidsoap "
            "harbor a station puts in front of it so a presenter can take "
            "over from the automation.")

        self.stream_host = wx.TextCtrl(panel, value=self.board.stream_host)
        self.stream_host.SetName("Address")
        row("A&ddress", self.stream_host,
            "The name of the server, with no http in front of it.")

        self.stream_port = wx.SpinCtrl(panel, min=1, max=65535,
                                       initial=int(self.board.stream_port))
        self.stream_port.SetName("Port")
        row("&Port", self.stream_port,
            "The port listeners use. For SHOUTcast this is still the "
            "listening port; the app adds the one it needs for a source.")

        self.stream_mount = wx.TextCtrl(panel, value=self.board.stream_mount)
        self.stream_mount.SetName("Mount point")
        row("&Mount point", self.stream_mount,
            "The part after the address, such as /live. SHOUTcast does not "
            "use one.")

        self.stream_user = wx.TextCtrl(panel, value=self.board.stream_user)
        self.stream_user.SetName("User name")
        row("&User name", self.stream_user,
            "Almost always source. SHOUTcast ignores it.")

        self.stream_password = wx.TextCtrl(panel,
                                           value=self.board.stream_password,
                                           style=wx.TE_PASSWORD)
        self.stream_password.SetName("Password")
        row("Pass&word", self.stream_password,
            "The source password for the server, not your listener password.")

        self.stream_format = wx.Choice(
            panel, choices=[streamout.FORMATS[key]["label"]
                            for key in C.STREAM_FORMAT_ORDER])
        self.stream_format.SetName("Format")
        self.stream_format.SetSelection(
            C.STREAM_FORMAT_ORDER.index(self.board.stream_format)
            if self.board.stream_format in C.STREAM_FORMAT_ORDER else 0)
        row("&Format", self.stream_format,
            "MP3 plays everywhere. Ogg Opus sounds better for the same "
            "bandwidth, if your server and your listeners take it.")

        self.stream_bitrate = wx.Choice(
            panel, choices=["%d kbps" % rate for rate in C.STREAM_BITRATES])
        self.stream_bitrate.SetName("Bitrate")
        self.stream_bitrate.SetSelection(
            C.STREAM_BITRATES.index(self.board.stream_bitrate)
            if self.board.stream_bitrate in C.STREAM_BITRATES else 2)
        row("&Bitrate", self.stream_bitrate,
            "128 is plenty for speech and music together. Higher costs your "
            "listeners more data and your server more bandwidth.")

        self.stream_name = wx.TextCtrl(panel, value=self.board.stream_name)
        self.stream_name.SetName("Station name")
        row("Station &name", self.stream_name,
            "What listeners see as the name of the stream.")

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        self.stream_mic = wx.CheckBox(
            panel, label="Put the m&icrophone on air")
        self.stream_mic.SetValue(bool(self.board.stream_mic))
        self.stream_mic.SetToolTip(
            "Separate from hearing yourself. With this on you go out live "
            "whenever the microphone is open, whether or not you are "
            "monitoring, which is the normal way to work on speakers.")
        sizer.Add(self.stream_mic, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.stream_titles = wx.CheckBox(
            panel, label="Send the &track title to the server")
        self.stream_titles.SetValue(bool(self.board.stream_titles))
        self.stream_titles.SetToolTip(
            "Listeners see the artist and title of whatever the playlist is "
            "playing, taken from the file.")
        sizer.Add(self.stream_titles, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.stream_public = wx.CheckBox(
            panel, label="&List this stream in public directories")
        self.stream_public.SetValue(bool(self.board.stream_public))
        sizer.Add(self.stream_public, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        test = wx.Button(panel, label="&Test the connection")
        test.SetToolTip(
            "Connects, says what happened, and disconnects again. Nothing is "
            "broadcast.")
        test.Bind(wx.EVT_BUTTON, self._on_test_stream)
        sizer.Add(test, 0, wx.ALL, 10)

        self.stream_result = wx.TextCtrl(
            panel, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 60),
            value="Not tested yet.")
        self.stream_result.SetName("Test result")
        sizer.Add(self.stream_result, 0, wx.EXPAND | wx.LEFT | wx.RIGHT
                  | wx.BOTTOM, 10)

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
            "public": self.stream_public.GetValue(),
        }

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
        spin.SetName(name)
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
        self.seconds.SetName("Crossfade for this track, seconds")
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
        if not audiofile.is_supported(selected):
            return
        try:
            self.mixer.play_preview(selected)
        except Exception:
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
