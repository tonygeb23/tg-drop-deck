"""The dialogs.

Every one of them is keyboard-complete and every control has a name, because a
dialog you cannot get out of without a mouse is worse than no dialog.
"""

from __future__ import annotations

import os

import wx

from . import constants as C
from . import feedback
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

        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
                  0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)
        self.name_field.SetFocus()
        self.name_field.SelectAll()

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
    """Where the sound comes out, and how hard the beds duck."""

    def __init__(self, parent, board, mixer):
        super().__init__(parent, title="Audio settings")
        self.board = board
        self.mixer = mixer
        self.devices = output_devices()

        outer = wx.BoxSizer(wx.VERTICAL)

        outer.Add(wx.StaticText(self, label="&Output device"), 0, wx.LEFT | wx.TOP, 10)
        self.choices = ["System default"] + [
            f"{d['name']}, {d['hostapi']}" for d in self.devices]
        self.device = wx.Choice(self, choices=self.choices)
        self.device.SetName("Output device")
        self.device.SetSelection(self._current_selection())
        outer.Add(self.device, 0, wx.EXPAND | wx.ALL, 10)

        note = wx.StaticText(self, label=(
            "Pick a virtual cable here to feed a stream or a recorder while you\n"
            "keep listening on your own speakers."))
        outer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Per-bank outputs.
        #
        # Sending beds to one card and drops to another lets a broadcaster ride
        # the balance on a physical desk instead of relying on the automatic
        # ducking below. Both approaches stay available; this is for people who
        # would rather decide the levels themselves.
        outer.Add(wx.StaticText(self, label="Send a bank to its own output"),
                  0, wx.LEFT | wx.TOP, 10)
        bank_note = wx.StaticText(self, label=(
            "Leave a bank on the main output unless you want it on a separate\n"
            "channel of your mixer. Ducking still works across outputs."))
        outer.Add(bank_note, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.bank_choices = {}
        bank_grid = wx.FlexGridSizer(C.BANK_COUNT, 2, 6, 10)
        bank_grid.AddGrowableCol(1, 1)
        for bank in range(1, C.BANK_COUNT + 1):
            title = board.bank_name(bank)
            label = wx.StaticText(self, label=f"{title}")
            choice = wx.Choice(self, choices=["Main output"] + self.choices[1:])
            # Named for the screen reader, because four identical unlabelled
            # dropdowns in a column are indistinguishable by ear.
            choice.SetName(f"{title} output")
            choice.SetSelection(self._bank_selection(bank))
            self.bank_choices[bank] = choice
            bank_grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            bank_grid.Add(choice, 1, wx.EXPAND)
        outer.Add(bank_grid, 0, wx.EXPAND | wx.ALL, 10)

        # How much the app says out loud. A screen reader is already reading
        # every control; this is only about what the app adds on top, which
        # for someone who knows the board is mostly repetition.
        outer.Add(wx.StaticText(self, label="Spo&ken feedback from the app"),
                  0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.speech_choice = wx.Choice(self, choices=list(C.SPEECH_LABELS))
        self.speech_choice.SetName("Spoken feedback from the app")
        level = getattr(board, "speech_level", C.DEFAULT_SPEECH_LEVEL)
        self.speech_choice.SetSelection(
            C.SPEECH_LEVELS.index(level) if level in C.SPEECH_LEVELS else 0)
        self.speech_choice.SetToolTip(
            "Everything is the default. The middle setting drops confirmations "
            "and the bank hints and keeps anything you could not otherwise "
            "know. Nothing leaves the running commentary to your screen reader "
            "and the status bar, and still answers a key you press to ask a "
            "question, such as Ctrl+L for what is playing.")
        self.speech_choice.Bind(wx.EVT_CHOICE, self._on_speech_level)
        outer.Add(self.speech_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Speech about playback.
        self.announce_playback = wx.CheckBox(
            self, label="&Say the name when a sound starts or stops")
        self.announce_playback.SetValue(bool(getattr(board, "announce_playback", True)))
        self.announce_playback.SetToolTip(
            "Turn this off if you can hear the sound and do not need to be told "
            "about it. Problems, such as a missing file, are always announced "
            "unless you have chosen Nothing above.")
        outer.Add(self.announce_playback, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self._on_speech_level(None)

        self.duck_on = wx.CheckBox(self, label="&Duck the music beds under sounds and drops")
        self.duck_on.SetValue(bool(board.ducking))
        outer.Add(self.duck_on, 0, wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="Duck &depth in decibels"), 0, wx.LEFT, 10)
        self.duck_db = wx.Slider(self, value=int(round(board.duck_db)), minValue=-24,
                                 maxValue=0, style=wx.SL_HORIZONTAL)
        self.duck_db.SetName("Duck depth in decibels")
        outer.Add(self.duck_db, 0, wx.EXPAND | wx.ALL, 10)

        # The slider was fully draggable while ducking was switched off - a
        # control that looks alive and does nothing.
        self.duck_db.Enable(self.duck_on.GetValue())
        self.duck_on.Bind(
            wx.EVT_CHECKBOX,
            lambda e: (self.duck_db.Enable(e.IsChecked()), e.Skip()))

        # How a bed enters and leaves.
        #
        # Brian Hartgen, on 2.2.1: a bed that eases in cannot be used on air.
        # He cues a bed on its first beat, and 350 ms of ramp eats exactly the
        # thing he cued. It was a constant; it is a setting now, zero included,
        # because "play it as it was recorded" is a legitimate answer and there
        # was no way to ask for it.
        outer.Add(wx.StaticText(self, label="Music bed fades, in seconds"),
                  0, wx.LEFT | wx.TOP, 10)
        fade_note = wx.StaticText(self, label=(
            "Zero starts and stops a bed exactly where the file does. Sounds and\n"
            "drops are unaffected - they have never faded."))
        outer.Add(fade_note, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        fade_grid = wx.FlexGridSizer(2, 2, 6, 10)
        self.fade_in_ctrl = self._fade_spin(
            fade_grid, "Fade beds &in, seconds", "Bed fade in, seconds",
            getattr(board, "bed_fade_in", C.FADE_IN_BED),
            "How long a bed takes to reach full level. Zero means it starts at "
            "full level on its first sample.")
        self.fade_out_ctrl = self._fade_spin(
            fade_grid, "Fade beds ou&t, seconds", "Bed fade out, seconds",
            getattr(board, "bed_fade_out", C.FADE_OUT_BED),
            "How long a bed takes to fall away when you stop it. Escape still "
            "stops everything quickly, whatever this says.")
        outer.Add(fade_grid, 0, wx.EXPAND | wx.ALL, 10)

        # The playlist crossfade. It also has a box under the running order,
        # where it is used most - but somebody looking for "how long do songs
        # overlap" looks in Audio settings, so it is in both and they are two
        # views of one number.
        outer.Add(wx.StaticText(self, label="Playlist crossfade"), 0,
                  wx.LEFT | wx.TOP, 10)
        crossfade_note = wx.StaticText(self, label=(
            "How long one song in the playlist overlaps the next. The next\n"
            "song starts this many seconds before the one playing ends, so\n"
            "every start time in the running order moves when you change it.\n"
            "Zero means each song plays right out before the next begins."))
        outer.Add(crossfade_note, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        cross_row = wx.BoxSizer(wx.HORIZONTAL)
        cross_row.Add(wx.StaticText(self, label="Cross&fade, seconds"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.crossfade_ctrl = wx.SpinCtrlDouble(
            self, min=0.0, max=C.MAX_CROSSFADE, inc=0.5,
            initial=float(getattr(board.playlist, "crossfade",
                                  C.DEFAULT_CROSSFADE)))
        self.crossfade_ctrl.SetDigits(1)
        self.crossfade_ctrl.SetName("Playlist crossfade, seconds")
        self.crossfade_ctrl.SetToolTip(
            "The same box that sits under the running order. A single track "
            "can be given a crossfade of its own from its right-click menu.")
        cross_row.Add(self.crossfade_ctrl, 0)
        outer.Add(cross_row, 0, wx.ALL, 10)

        self.status = wx.StaticText(self, label=self._status_text())
        outer.Add(self.status, 0, wx.ALL, 10)

        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
                  0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)
        self.device.SetFocus()

    @property
    def crossfade(self):
        return round(float(self.crossfade_ctrl.GetValue()), 2)

    def _fade_spin(self, grid, label, name, value, tip):
        """One labelled fade box, in seconds.

        A spin control rather than a slider because these are numbers a
        broadcaster types - "zero" and "one" are the answers, not a position -
        and because a screen reader reads a spin control's value back exactly.
        """
        grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        spin = wx.SpinCtrlDouble(self, min=0.0, max=C.MAX_BED_FADE, inc=0.05,
                                 initial=float(value))
        spin.SetDigits(2)
        spin.SetName(name)
        spin.SetToolTip(tip)
        grid.Add(spin, 0)
        return spin

    @property
    def bed_fade_in(self):
        return round(float(self.fade_in_ctrl.GetValue()), 2)

    @property
    def bed_fade_out(self):
        return round(float(self.fade_out_ctrl.GetValue()), 2)

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

    @property
    def chosen_device(self):
        """(index, name, hostapi). index is None for the system default."""
        selection = self.device.GetSelection()
        if selection <= 0:
            return None, None, None
        dev = self.devices[selection - 1]
        return dev["index"], dev["name"], dev["hostapi"]

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


class MicSettingsDialog(wx.Dialog):
    """Which microphone, how loud, and whether you hear yourself."""

    def __init__(self, parent, board, mic):
        super().__init__(parent, title="Microphone settings")
        self.board = board
        self.mic = mic
        self.devices = input_devices()

        outer = wx.BoxSizer(wx.VERTICAL)

        outer.Add(wx.StaticText(self, label="&Microphone"), 0,
                  wx.LEFT | wx.TOP, 10)
        self.choices = ["System default"] + [
            "%s - %s" % (d["name"], d["hostapi"]) for d in self.devices]
        self.device = wx.Choice(self, choices=self.choices)
        self.device.SetName("Microphone")
        self.device.SetSelection(self._current_selection())
        outer.Add(self.device, 0, wx.EXPAND | wx.ALL, 10)

        note = wx.StaticText(self, label=(
            "Ctrl+M turns the microphone on and off. While it is on, the beds\n"
            "and the playlist duck out of the way, and they come back up the\n"
            "moment you turn it off."))
        outer.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        outer.Add(wx.StaticText(self, label="&Gain in decibels"), 0, wx.LEFT, 10)
        self.gain = wx.Slider(self, value=int(round(board.mic_gain_db)),
                              minValue=int(C.MIN_MIC_GAIN_DB),
                              maxValue=int(C.MAX_MIC_GAIN_DB),
                              style=wx.SL_HORIZONTAL)
        self.gain.SetName("Microphone gain in decibels")
        self.gain.SetToolTip(
            "Zero is the microphone as Windows gives it to us. Raise it for a "
            "quiet headset, lower it for a hot one.")
        outer.Add(self.gain, 0, wx.EXPAND | wx.ALL, 10)

        outer.Add(wx.StaticText(self, label="Hear yourself thr&ough"), 0,
                  wx.LEFT, 10)
        self.output_choices = ["Same as the soundboard"] + [
            "%s - %s" % (d["name"], d["hostapi"]) for d in output_devices()]
        self.output = wx.Choice(self, choices=self.output_choices)
        self.output.SetName("Monitor output")
        self.output.SetSelection(self._output_selection())
        self.output.SetToolTip(
            "Put monitoring on your headphones and leave the show on the main "
            "output. Everything an encoder picks up is unaffected by this.")
        outer.Add(self.output, 0, wx.EXPAND | wx.ALL, 10)

        self.monitor = wx.CheckBox(
            self, label="&Hear yourself through the output (headphones only)")
        self.monitor.SetValue(bool(board.mic_monitor))
        self.monitor.SetToolTip(
            "On headphones this is how you know you are live. On speakers it "
            "is a feedback loop, which is why it is off to begin with.")
        outer.Add(self.monitor, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.status = wx.StaticText(self, label=self._status_text())
        outer.Add(self.status, 0, wx.ALL, 10)

        outer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL),
                  0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizerAndFit(outer)
        self.device.SetFocus()

    def _status_text(self):
        if self.mic is None:
            return "The microphone is off."
        if self.mic.is_open:
            return "The microphone is ON, through %s." % self.mic.describe()
        if self.mic.last_error:
            return "It would not open last time. %s" % self.mic.last_error
        return "The microphone is off. Ctrl+M turns it on."

    def _current_selection(self):
        if not self.board.mic_device_name:
            return 0
        for position, device in enumerate(self.devices):
            if (device["name"] == self.board.mic_device_name
                    and device["hostapi"] == self.board.mic_device_hostapi):
                return position + 1
        for position, device in enumerate(self.devices):
            if device["name"] == self.board.mic_device_name:
                return position + 1
        return 0

    @property
    def chosen_device(self):
        """(index, name, hostapi) for the microphone that was picked."""
        position = self.device.GetSelection()
        if position <= 0:
            return None, None, None
        device = self.devices[position - 1]
        return device["index"], device["name"], device["hostapi"]

    def _output_selection(self):
        if not self.board.mic_output_name:
            return 0
        outputs = output_devices()
        for position, device in enumerate(outputs):
            if (device["name"] == self.board.mic_output_name
                    and device["hostapi"] == self.board.mic_output_hostapi):
                return position + 1
        for position, device in enumerate(outputs):
            if device["name"] == self.board.mic_output_name:
                return position + 1
        return 0

    @property
    def chosen_output(self):
        """(index, name, hostapi) for the output monitoring should use."""
        position = self.output.GetSelection()
        if position <= 0:
            return None, None, None
        device = output_devices()[position - 1]
        return device["index"], device["name"], device["hostapi"]

    @property
    def gain_db(self):
        return float(self.gain.GetValue())

    @property
    def monitoring(self):
        return bool(self.monitor.GetValue())


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


def audio_file_dialog(parent, start_dir="", title="Choose a sound"):
    """Shared open dialog, remembering where the user was last time."""
    with wx.FileDialog(parent, title, wildcard=C.AUDIO_WILDCARD,
                       defaultDir=start_dir if os.path.isdir(start_dir) else "",
                       style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
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
