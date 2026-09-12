"""The window.

Four tabs, twenty buttons each, and a keyboard map that has not changed since
the app this one replaces. Everything you can do with the mouse has a key, and
everything that happens says so out loud.
"""

from __future__ import annotations

import ctypes
import datetime
import os
import threading
import time

import wx

import webbrowser

from . import appicon
from . import constants as C
from . import dsp
from . import endpoints
from . import feedback
from . import framing
from . import health
from . import overlay
from . import picture
from . import secrets
from . import sources
from . import preflight
from . import cuefile
from . import cuesheet
from . import routing
from . import screen
from . import picturefeed
from . import videorecord
from . import send as sendout
from . import streamout
from . import vst
from . import globalhotkeys
from . import m3u
from .board import Board, default_board_path, demo_board_path
from . import updatedialog
from .dialogs import (ColoursDialog, CueSheetDialog, GoLiveDialog,
                      ScreenTextDialog,
                      ShotCheckDialog,
                      VideoSourceDialog,AssignHotkeyDialog, DonateDialog, DropsLibraryDialog,
                      FeedbackDialog, SearchDialog,
                      SettingsDialog, SlotPropertiesDialog,
                      SendDialog,
                      SourceControlDialog, SourcesDialog, StreamHelpDialog,
                      StreamStatsDialog,
                      TrackCrossfadeDialog, TrimDialog, ask_text,
                      audio_file_dialog, key_label)
from .engine import probe
from .micinput import MicInput, describe_input, resolve_input
from .playlist import PlaylistPlayer
from .plids import (ID_PL_ROW_ADD, ID_PL_ROW_DOWN, ID_PL_ROW_DROP,
                    ID_PL_ROW_FADE, ID_PL_ROW_PLAY, ID_PL_ROW_RANDOM,
                    ID_PL_ROW_BOTTOM, ID_PL_ROW_REMOVE, ID_PL_ROW_SEGUE,
                    ID_PL_ROW_STOP, ID_PL_ROW_TOP,
                    ID_PL_ROW_TICK, ID_PL_ROW_TO_LIBRARY, ID_PL_ROW_UP)
from .playlistview import PlaylistPanel
from .mixer import (Mixer, MixerGroup, describe_device, device_spec,
                    output_devices, resolve_device)
from .slot import Slot, format_duration
from .speech import Speaker, percent

ID_STREAM_TOGGLE = wx.ID_HIGHEST + 401
#: Going live to the RADIO station, beside Ctrl+B for the video platform.
#: One key per destination, asked for on 12 September 2026, because one key
#: plus a remembered setting meant the summary in front of you was for
#: whichever destination you last chose rather than the one you meant.
#:
#: **Alt+Shift+B, and NOT the Alt+Ctrl+B that was asked for.** Two separate
#: faults sat on top of each other here on 12 September 2026 and the second
#: one was invisible until the first was fixed.
#:
#: First, this id was ID_HIGHEST+420, which is ID_SEND_SETUP. Two handlers
#: bound for one id means the last one bound wins, so the key opened the send
#: setup window and `toggle_stream` never ran whatever chord was on it. That
#: is the ID_STATION_BASE fault again, and `tests/test_3_4_1.py` catches it
#: in one second: it was not run between adding the id and pressing the key.
#:
#: Second, and only measurable once the id was right: **Windows turns Ctrl+Alt
#: into AltGr**, so Ctrl+Alt plus a letter is a character rather than a
#: shortcut. Measured with real synthesised keystrokes, all with the correct
#: id and the same handler: Ctrl+B reaches the app, Alt+Shift+B reaches it,
#: and Alt+Ctrl+B fails three times out of three. wx builds the accelerator
#: quite happily (flags 3, keycode 66) and Windows simply never delivers it,
#: which is the worst shape of key: one that looks right in every menu and
#: does nothing. Alt+Ctrl+Shift+S escapes it only because Shift takes the
#: chord back out of AltGr territory.
#:
#: Alt+Shift+B is free, verified against the table the frame really builds,
#: and it is the family this app already uses for the things you go and do:
#: Alt+Shift+S, V, T, C, D and O. `tools/check_video_key.py radio` presses
#: it for real.
ID_STREAM_TOGGLE_AUDIO = wx.ID_HIGHEST + 426
ID_STREAM_STATUS = wx.ID_HIGHEST + 402
#: Who is listening. Ctrl+Shift+A for audience, next to the pair above.
ID_STREAM_STATS = wx.ID_HIGHEST + 404
#: What the camera can see. Ctrl+Shift+F, next to the pair above, and a NEW
#: key: nothing on the frozen digit map moved for it.
ID_SHOT = wx.ID_HIGHEST + 411
#: Setting streaming up, in the app. No accelerator: it is a thing you read
#: once while setting up, not a thing you reach for mid show.
ID_STREAM_HELP = wx.ID_HIGHEST + 412
#: The two places a show can go: the radio station on the Audio streaming
#: page, and the platform on the Video streaming page. One id each, because
#: they are a choice rather than a list, and they sit with the saved locations
#: under On air, Streaming location.
#: What sits on top of the picture. Alt+Shift+T, beside Alt+Shift+V for the
#: picture itself and Alt+Shift+S for the audio sources. T for text.
ID_SCREEN_TEXT = wx.ID_HIGHEST + 416
#: The brand: what sits underneath, what the words are, and the accent.
#: Alt+Shift+C, in the same family as the other two Alt+Shift keys.
ID_COLOURS = wx.ID_HIGHEST + 418
#: The shot check. D for describe, and in the same Alt+Shift family as the
#: other three things that are about the picture.
ID_SHOT_CHECK = wx.ID_HIGHEST + 419
#: And the key that answers what is on screen right now, which is the thing
#: no other broadcast tool does. Ctrl+Shift+V, beside Ctrl+Shift+F for the
#: camera and Ctrl+Shift+B for the stream.
ID_ON_SCREEN = wx.ID_HIGHEST + 417

#: The send: this show, out of a sound card, for another program on this
#: machine. Three ids and three NEW keys, none of them anywhere near the
#: frozen digit map.
#:
#: Alt+Shift+O sets it up, which is the family that already holds Alt+Shift+S
#: for audio sources and Alt+Shift+V for the picture: things you go and
#: change. Ctrl+Shift+O asks how it is doing, which is the family that holds
#: Ctrl+Shift+B for the stream and Ctrl+Shift+F for the camera: things that
#: answer a question. Ctrl+Shift+H turns the confidence feed on and off,
#: because hearing it is a thing you do mid show and not a thing you set up.
ID_SEND_SETUP = wx.ID_HIGHEST + 420
ID_SEND_STATUS = wx.ID_HIGHEST + 421
ID_SEND_MONITOR = wx.ID_HIGHEST + 422
#: Where is everything going. Ctrl+Shift+W, and the only command in the app
#: that answers the whole routing question in one go.
ID_ROUTING = wx.ID_HIGHEST + 423
#: Recording the picture as well as the sound. Ctrl+Shift+R, beside Ctrl+R,
#: which is the pairing Tony asked for and the same shape as Ctrl+B and
#: Ctrl+Shift+B.
ID_VIDEO_RECORD = wx.ID_HIGHEST + 424
#: What is coming up next. Ctrl+Shift+C, C for cue, which is Tyler's own
#: word. In the Ctrl+Shift "tell me" family beside Ctrl+Shift+B, Ctrl+Shift+O
#: and Ctrl+Shift+W, and next to Ctrl+Shift+P which goes to the running order
#: this is built from.
ID_CUE_SHEET = wx.ID_HIGHEST + 425

ID_LIVE_TO_AUDIO = wx.ID_HIGHEST + 414
ID_LIVE_TO_VIDEO = wx.ID_HIGHEST + 415

#: What the stream is showing, and what to show instead. Alt+Shift+V, beside
#: Alt+Shift+S for audio sources: same gesture, the other half of the show.
#: A NEW key, and it goes nowhere near the frozen digit map, which uses only
#: the digits and never Alt+Shift.
ID_VIDEO_SOURCES = wx.ID_HIGHEST + 413
#: Recording, which is its own thing and not a kind of streaming: you record
#: a show whether or not anybody is listening to it live.
ID_RECORD = wx.ID_HIGHEST + 405
ID_RECORD_FOLDER = wx.ID_HIGHEST + 406
#: Stop the sound you started last, without stopping the show.
ID_STOP_LATEST = wx.ID_HIGHEST + 407
#: Other inputs besides the microphone.
ID_SOURCES = wx.ID_HIGHEST + 408
#: The live one: mute, solo, rename, remove, while the show is going out.
ID_SOURCE_CONTROL = wx.ID_HIGHEST + 409
ID_STREAM_SETUP = wx.ID_HIGHEST + 403
#: One id per saved station on the On air menu. Twenty is more stations than
#: anyone has.
#:
#: **MOVED IN 3.4.1, AND THE OLD PLACE WAS A REAL BUG.** This block used to
#: start at 410, and the comment here used to claim a fixed block kept it
#: clear of every other id. It did not: 410 to 429 swallowed ID_SHOT at 411
#: and ID_STREAM_HELP at 412, both added later in the 400s without anybody
#: noticing they were inside it. Two handlers bound for one id on one window
#: means the LAST one bound wins, `_on_pick_station` is bound after both of
#: them and never calls Skip, so Ctrl+Shift+F reached the station picker
#: instead of the camera and did nothing at all.
#:
#: It survived every test because a test calls the handler by hand. Only a
#: real keystroke, through the real accelerator table, goes near the binding
#: that was wrong. `tools/check_video_key.py` is what found it and
#: `tests/test_3_4_1.py` now asserts no two ids collide, so a third one
#: cannot be quietly parked on top of this block.
ID_STATION_BASE = wx.ID_HIGHEST + 700
MAX_STATIONS = 20

ID_SLOT_BASE = wx.ID_HIGHEST + 500

ID_VOL_SFX_DOWN = wx.ID_HIGHEST + 1
ID_VOL_SFX_UP = wx.ID_HIGHEST + 2
ID_VOL_BED_DOWN = wx.ID_HIGHEST + 3
ID_VOL_BED_UP = wx.ID_HIGHEST + 4
ID_RENAME = wx.ID_HIGHEST + 5
ID_CLEAR_FOCUSED = wx.ID_HIGHEST + 6
ID_STOP_ALL = wx.ID_HIGHEST + 7
#: Escape, which needs three presses. Its own id so that the menu item and
#: the button, which are deliberate on their own, still stop immediately.
ID_STOP_ALL_KEY = wx.ID_HIGHEST + 58
ID_SEARCH = wx.ID_HIGHEST + 8
ID_DUCK = wx.ID_HIGHEST + 9
ID_WHATS_PLAYING = wx.ID_HIGHEST + 10
ID_SETTINGS = wx.ID_HIGHEST + 11
ID_RELINK = wx.ID_HIGHEST + 12
ID_ASSIGN = wx.ID_HIGHEST + 13
ID_HOTKEY = wx.ID_HIGHEST + 14
ID_TRIM = wx.ID_HIGHEST + 15
ID_LOOP = wx.ID_HIGHEST + 16
ID_SHORTCUTS = wx.ID_HIGHEST + 17
ID_IMPORT = wx.ID_HIGHEST + 18
ID_SAVE_AS = wx.ID_HIGHEST + 19
ID_DEMO = wx.ID_HIGHEST + 20
ID_GLOBAL_HOTKEY = wx.ID_HIGHEST + 21
ID_GLOBAL_TOGGLE = wx.ID_HIGHEST + 22
ID_CHECK_UPDATES = wx.ID_HIGHEST + 23
ID_PROPERTIES = wx.ID_HIGHEST + 24
ID_RENAME_BANK = wx.ID_HIGHEST + 25
ID_RESET_BANK = wx.ID_HIGHEST + 26
ID_ASSIGN_FOLDER = wx.ID_HIGHEST + 27
ID_VIEW_BOARD = wx.ID_HIGHEST + 28
ID_VIEW_PLAYLIST = wx.ID_HIGHEST + 29
ID_VIEW_NEXT = wx.ID_HIGHEST + 30
ID_PL_PASTE = wx.ID_HIGHEST + 31
ID_PL_ADD = wx.ID_HIGHEST + 32
ID_PL_DROP = wx.ID_HIGHEST + 33
ID_PL_DROP_EVERY = wx.ID_HIGHEST + 34
ID_PL_PLAY = wx.ID_HIGHEST + 35
ID_PL_STOP = wx.ID_HIGHEST + 36
ID_PL_NEXT = wx.ID_HIGHEST + 37
ID_PL_PREV = wx.ID_HIGHEST + 38
ID_PL_CROSSFADE = wx.ID_HIGHEST + 39
ID_PL_CLEAR = wx.ID_HIGHEST + 40
ID_VOL_PL_DOWN = wx.ID_HIGHEST + 41
ID_VOL_PL_UP = wx.ID_HIGHEST + 42
ID_PL_CHECK_ALL = wx.ID_HIGHEST + 43
ID_PL_UNCHECK_ALL = wx.ID_HIGHEST + 44
ID_MIC_TOGGLE = wx.ID_HIGHEST + 45
ID_MIC_SETTINGS = wx.ID_HIGHEST + 46
ID_PL_DROP_RANDOM = wx.ID_HIGHEST + 47
ID_PL_LIBRARY = wx.ID_HIGHEST + 48
ID_FEEDBACK = wx.ID_HIGHEST + 49
ID_DONATE = wx.ID_HIGHEST + 50
ID_USER_GUIDE = wx.ID_HIGHEST + 51
ID_PL_GOTO_PLAYING = wx.ID_HIGHEST + 52
ID_PL_SAVE = wx.ID_HIGHEST + 53
ID_PL_OPEN = wx.ID_HIGHEST + 54
ID_REMOVE_SLOT = wx.ID_HIGHEST + 55
ID_RESTORE_SLOT = wx.ID_HIGHEST + 56
ID_RESTORE_ALL_SLOTS = wx.ID_HIGHEST + 57

#: The two things this window can be showing.
VIEW_BOARD, VIEW_PLAYLIST = 0, 1

#: Controls somebody types into. The frame's bare-key hotkeys stand down
#: while one of these has focus, because a pad firing instead of a digit
#: landing in the box means the box cannot be used at all.
TEXT_ENTRY_CONTROLS = (wx.TextCtrl, wx.SpinCtrl, wx.SpinCtrlDouble,
                       wx.ComboBox, wx.SearchCtrl)


def _is_text_entry(window):
    """Is this a control a keystroke belongs to rather than to the board.

    Walks up a couple of levels, because several of these are composites on
    Windows - a spin control is an edit box with a pair of arrows beside it,
    and which of the three answers FindFocus is not something to rely on.
    """
    for _ in range(3):
        if window is None:
            return False
        if isinstance(window, TEXT_ENTRY_CONTROLS):
            return True
        window = window.GetParent()
    return False


def _is_typed_key(code):
    """Is this key code something somebody types into a box.

    Printable ASCII and the number pad digits. Deliberately not Escape,
    Delete, Tab, Return or the function keys: those are commands wherever you
    are, and stopping everything with Escape has to work from inside a text
    box as much as anywhere else.
    """
    if 32 <= code <= 126:
        return True
    return wx.WXK_NUMPAD0 <= code <= wx.WXK_NUMPAD9


#: Which slot each fixed hotkey fires, as (modifiers, key_code, slot_index).
def fixed_accelerators():
    entries = []
    for bank, mods in ((C.BANK_SFX, (0, wx.ACCEL_SHIFT)),
                       (C.BANK_DROPS, (wx.ACCEL_CTRL,
                                       wx.ACCEL_CTRL | wx.ACCEL_SHIFT)),
                       (C.BANK_BEDS, (wx.ACCEL_ALT | wx.ACCEL_CTRL,
                                      wx.ACCEL_ALT | wx.ACCEL_CTRL | wx.ACCEL_SHIFT))):
        start = (bank - 1) * C.SLOTS_PER_BANK
        for half, modifier in enumerate(mods):
            for position, digit in enumerate(C.DIGITS):
                entries.append((modifier, ord(digit),
                                start + half * 10 + position))
    return entries


def _escaped(label):
    """Double every ampersand, for a label going onto a wx.Button.

    Win32 treats a single & as a mnemonic prefix and swallows it, and MSAA
    strips it too - so a drop called "Q&A Bumper" was read out as "QA Bumper".
    "R&B", "Rock & Roll" and "Q&A" are ordinary names for a soundboard, and the
    name is the whole label, which is the whole thing a screen reader reads.

    Escaping happens here, at the wx boundary, and nowhere else. slot.py keeps
    returning the real text, so search labels, announcements and the tests are
    all unaffected.
    """
    return label.replace("&", "&&")


class SoundButton(wx.Button):
    """One slot, drawn rather than left to the native button.

    A native wx.Button centres its label and hard-clips the overflow at BOTH
    ends with no ellipsis, and the label here is a sentence: number, name,
    hotkey, global hotkey, loop, duration. Measured on the shipped demo pack at
    the default window size, 19 of 40 pads were losing text - the slot number
    off the left and the duration off the right, so "13. playful quirky, key
    Alt+Ctrl+Shift+3, loops, 30 sec" showed as "playful quirky, key
    Alt+Ctrl+Shift+3, loops, 30".

    So the face is painted in three zones that each get their own space, and
    the state is shown as colour and a bar rather than as one more clause in
    the sentence. For a live soundboard "which pads are firing right now" is
    the question the screen has to answer, and before this it was answerable
    only by reading the word "playing" out of the middle of a line that was
    often clipped away.

    The window label is still the full unclipped string, so the accessible name
    is byte-identical to what it was and a screen reader loses nothing. Colour
    is never the only cue: every state painted here is also a word in that
    label.
    """

    def __init__(self, parent, slot, frame):
        super().__init__(parent, label=_escaped(slot.button_label()),
                         style=wx.BORDER_NONE)
        self.slot = slot
        self.frame = frame
        self._last_label = slot.button_label()
        #: The label with the transient "playing" word left out. Comparing
        #: against this is how refresh tells a change the user just made from
        #: the state the mixer is reporting. See refresh.
        self._last_content = slot.button_label(False)
        self._playing = False
        self._hover = False
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_BUTTON, self._on_activate)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_hover(False))
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_focus)
        self._update_tooltip()

    def _set_hover(self, value):
        self._hover = value
        self.Refresh()

    def _on_focus(self, event):
        # A label deferred while focused (see refresh) is applied on the way
        # out, so the accessible name never goes stale.
        if not self.HasFocus():
            wx.CallAfter(self.refresh, self._playing)
        self.Refresh()
        event.Skip()

    def set_slot(self, slot):
        """Point this pad at another slot, as loading a board does.

        The label is rewritten unconditionally, focus or no focus. The pad
        under the cursor is now a different sound and saying otherwise is the
        one thing worse than saying it twice.
        """
        self.slot = slot
        self._playing = False
        self._last_label = slot.button_label()
        self._last_content = slot.button_label(False)
        self.SetLabel(_escaped(self._last_label))
        self._update_tooltip()
        self.Refresh()

    def _update_tooltip(self):
        """The full label plus the file, for the mouse.

        There was not one tooltip on any of the eighty pads, so a mouse user
        had no way to recover text the button had clipped.
        """
        tip = self.slot.button_label(self._playing)
        if self.slot.filepath:
            tip += "\n" + self.slot.filepath
        elif not self.slot.is_assigned:
            tip += "\nClick to choose a sound for this slot."
        self.SetToolTip(tip)

    def refresh(self, playing=False):
        """Bring the label back in line with the slot.

        There are two quite different reasons the label can be out of date and
        they get opposite treatment.

        **The mixer started or stopped this slot.** That is a value change, and
        rewriting the accessible Name for it restarts the screen reader mid
        sentence - on air, on the pad the user is standing on, at the exact
        moment they pressed a key. So while this button has focus that change
        is deferred; _on_focus applies it on the way out. The paint below still
        shows it immediately, and announce_playback has already said it.

        **The user just changed the slot** - assigned a file, renamed it,
        turned looping off, set a hotkey. That is not a value arriving on its
        own, it is the answer to something they did, and it has to be true the
        moment the dialog closes. Deferring it meant the pad still read
        "2. Empty, key Alt+Ctrl+2" after a file had been put in it, and only
        told the truth once you tabbed away and back - Brian Hartgen's report,
        and the reason the rest of the app looked like it was ignoring edits.

        Which one it is, is decided by comparing the label with the "playing"
        word left out. Compared unescaped, set escaped: comparing the escaped
        form against slot.button_label() would differ on every ampersand and
        rewrite the label forever.
        """
        label = self.slot.button_label(playing)
        content = self.slot.button_label(False)
        changed = playing != self._playing
        edited = content != self._last_content
        self._playing = playing
        if label != self._last_label and (edited or not self.HasFocus()):
            self._last_label = label
            self._last_content = content
            self.SetLabel(_escaped(label))
            self._update_tooltip()
        if changed:
            self.Refresh()

    def _on_activate(self, _event):
        self.frame.trigger(self.slot.index)

    def _on_context_menu(self, event):
        # Use where the event says, not where the mouse happens to be. With no
        # position PopupMenu falls back to the cursor, so pressing the
        # Applications key on a focused pad opened its menu wherever the
        # pointer had been left - possibly on another monitor.
        position = event.GetPosition()
        if position == wx.DefaultPosition or tuple(position) == (-1, -1):
            size = self.GetSize()
            position = self.ClientToScreen(wx.Point(size.x // 2, size.y // 2))
        self.frame.show_slot_menu(self.slot, self, self.ScreenToClient(position))

    # ------------------------------------------------------------- painting --
    def _on_paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self)
        width, height = self.GetClientSize()
        slot = self.slot
        pad = self.FromDIP(8)

        face, edge, ink, sub, accent = _pad_colours(slot, self._playing,
                                                    self._hover)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            return
        gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
        radius = self.FromDIP(5)
        gc.SetBrush(gc.CreateBrush(wx.Brush(face)))
        if not slot.is_assigned:
            # A dashed outline and no fill, so an empty slot is obviously
            # empty. Before this, empty, loaded and broken pads were three
            # identical white cards.
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(edge).Width(1)
                                   .Style(wx.PENSTYLE_SHORT_DASH)))
        else:
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(edge).Width(
                2 if (self.HasFocus() or self._playing) else 1)))
        gc.DrawRoundedRectangle(0.5, 0.5, width - 1, height - 1, radius)

        if accent is not None:
            # The state bar. Colour, but never the only cue - the same state is
            # a word inside this button's label, which is what is read aloud.
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(gc.CreateBrush(wx.Brush(accent)))
            gc.DrawRoundedRectangle(1, 1, self.FromDIP(4), height - 2,
                                    self.FromDIP(2))

        base = self.GetFont()
        name_font = base.Scaled(1.25).Bold()
        small = base.Scaled(0.88)
        left = pad + (self.FromDIP(4) if accent is not None else 0)
        avail = max(self.FromDIP(20), width - left - pad)

        # Zone one: number and name, the thing you are actually hunting for.
        dc.SetFont(name_font)
        dc.SetTextForeground(ink)
        title = "%d. %s" % (slot.number, slot.display_name)
        dc.DrawText(wx.Control.Ellipsize(title, dc, wx.ELLIPSIZE_END, avail),
                    left, pad)
        title_height = dc.GetCharHeight()

        # Zone two: the keys, right where a performer looks for them.
        dc.SetFont(small)
        dc.SetTextForeground(sub)
        keys = []
        if slot.hotkey_label:
            keys.append(slot.hotkey_label)
        if slot.global_hotkey:
            keys.append("global " + slot.global_hotkey)
        if keys:
            text = "   ".join(keys)
            dc.DrawText(wx.Control.Ellipsize(text, dc, wx.ELLIPSIZE_END, avail),
                        left, pad + title_height + self.FromDIP(4))

        # Zone three: state, along the bottom.
        words = slot._state_words(self._playing)
        if words:
            text = ", ".join(words)
            dc.SetTextForeground(accent if accent is not None else sub)
            dc.DrawText(wx.Control.Ellipsize(text, dc, wx.ELLIPSIZE_END, avail),
                        left, height - dc.GetCharHeight() - pad)


def _pad_colours(slot, playing, hover):
    """(face, edge, ink, sub, accent) for one pad.

    In high contrast, and under a dark system theme, everything comes from the
    system palette and the accent bar is dropped. This app has never hardcoded
    a colour, which is exactly why high contrast works today; it is not going
    to start by breaking the one mode where getting it wrong is unreadable.
    """
    sys_get = wx.SystemSettings.GetColour
    window = sys_get(wx.SYS_COLOUR_WINDOW)
    text = sys_get(wx.SYS_COLOUR_WINDOWTEXT)
    grey = sys_get(wx.SYS_COLOUR_GRAYTEXT)
    face3d = sys_get(wx.SYS_COLOUR_BTNFACE)
    dark = (window.Red() + window.Green() + window.Blue()) < 384

    if dark or _high_contrast():
        accent = sys_get(wx.SYS_COLOUR_HOTLIGHT) if playing else None
        if slot.is_missing:
            accent = sys_get(wx.SYS_COLOUR_HIGHLIGHT)
        return (face3d if hover else window), text, text, grey, accent

    if slot.is_missing:
        return (wx.Colour("#fdf3f2"), wx.Colour("#c4a3a0"),
                wx.Colour("#8a1c1c"), wx.Colour("#8a1c1c"), wx.Colour("#a8201c"))
    if not slot.is_assigned:
        return window, wx.Colour("#b4b4b4"), grey, grey, None
    if playing:
        colour = wx.Colour("#1c7a3e") if slot.loop else wx.Colour("#a8201c")
        tint = wx.Colour("#eef7f1") if slot.loop else wx.Colour("#fdf0ef")
        return tint, colour, text, wx.Colour("#4a4a4a"), colour
    return ((wx.Colour("#f5f5f3") if hover else window),
            wx.Colour("#c8c8c4"), text, wx.Colour("#5a5a5a"), None)


def _high_contrast():
    """Ask Windows directly; wx has no wrapper for it."""
    try:
        class HC(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                        ("lpszDefaultScheme", ctypes.c_void_p)]
        hc = HC()
        hc.cbSize = ctypes.sizeof(HC)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x0042, ctypes.sizeof(HC), ctypes.byref(hc), 0)
        return bool(ok) and bool(hc.dwFlags & 0x01)
    except Exception:
        return False


class BankPage(wx.Panel):
    """Twenty buttons and a line telling you what the keys are."""

    def __init__(self, parent, frame, bank):
        super().__init__(parent)
        self.bank = bank
        outer = wx.BoxSizer(wx.VERTICAL)

        self.hint = wx.StaticText(self, label=C.BANK_HINTS[bank])
        outer.Add(self.hint, 0, wx.ALL, 8)

        # All twenty are built, and the removed ones are hidden rather than
        # left out. Two reasons: `buttons` stays twenty long, so a slot's
        # number is still its position in it, and putting one back is showing
        # a button rather than rebuilding the page under the user's fingers.
        self.grid = wx.GridSizer(rows=5, cols=4, gap=wx.Size(6, 6))
        self.buttons = []
        for slot in frame.board.bank_slots(bank):
            button = SoundButton(self, slot, frame)
            self.buttons.append(button)
            self.grid.Add(button, 0, wx.EXPAND)
        outer.Add(self.grid, 1, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)
        self.refresh_visibility()

        # wx.StaticText never wraps unless told to. Bank 3's hint needs about
        # 1400 px and does not get it even maximised, so the end of the
        # sentence was simply cut off.
        self.Bind(wx.EVT_SIZE, self._on_size)

    def refresh_visibility(self):
        """Show the slots that are on the board and hide the rest.

        Hidden through the SIZER as well as the window, or the grid keeps a
        hole where the button was and the ones after it do not move up.
        """
        for button in self.buttons:
            wanted = not button.slot.hidden
            if button.IsShown() != wanted:
                button.Show(wanted)
            self.grid.Show(button, wanted, recursive=True)
        self.Layout()

    def first_visible(self):
        """A button somebody can actually land on, or None if the bank is empty."""
        for button in self.buttons:
            if not button.slot.hidden:
                return button
        return None

    def _on_size(self, event):
        width = self.GetClientSize().width - self.FromDIP(20)
        if width > self.FromDIP(120):
            # Reset before wrapping: Wrap() inserts newlines into the label, so
            # wrapping an already-wrapped label keeps every old break.
            self.hint.SetLabel(C.BANK_HINTS[self.bank])
            self.hint.Wrap(width)
            self.Layout()
        event.Skip()


class DropDeckFrame(wx.Frame):
    def __init__(self, parent=None):
        super().__init__(parent, title=C.APP_NAME)
        #: What the title says when nothing is on air. The playing track goes
        #: in front of it, see _update_title.
        self._base_title = C.APP_NAME
        self.SetIcons(appicon.bundle())

        self.speaker = Speaker()
        # Set on close. The cache warmer decodes audio on a daemon thread, and
        # a daemon thread killed part way through a C call at interpreter
        # shutdown segfaults - which it did, intermittently, about one run in
        # three. It checks this between files instead.
        self._closing = threading.Event()
        self._warm_thread = None
        self._metadata_thread = None
        self._context_slot = None
        self._loaded_demo = False
        #: Banks whose hint has been spoken this session. See _on_bank_changed.
        self._hinted_banks = set()
        self.board = self._load_startup_board()
        self.mixer = MixerGroup(bank_devices=self._resolve_bank_devices(),
                                open_stream=True,
                                monitor_device=self._resolve_monitor_device())
        self.mixer.set_sfx_gain(self.board.sfx_volume)
        self.mixer.set_bed_gain(self.board.bed_volume)
        self.mixer.set_playlist_gain(self.board.playlist_volume)
        self.mixer.playlist_monitor_only = self.board.playlist_monitor_only
        self.mixer.ducking = self.board.ducking
        self.mixer.duck_db = self.board.duck_db
        # The microphone shares the mixers' duck bus, which is what makes
        # opening it duck a bed playing out of a completely different sound
        # card. It is created closed: nothing here opens a microphone except
        # somebody pressing the key for it.
        self.mic = MicInput(duck_bus=self.mixer.duck_bus,
                            samplerate=self.mixer.samplerate,
                            device=resolve_input(self._mic_spec()),
                            gain_db=self.board.mic_gain_db,
                            monitor=self.board.mic_monitor)
        # Gate, equaliser, compressor and limiter. Built even when the
        # processing library is missing, because a chain that does nothing is
        # simpler for everything downstream than a chain that is None.
        self.mic.channel = self.board.mic_channel
        if dsp.available():
            self.mic.chain = dsp.MicChain(self.mixer.samplerate,
                                          self.board.voice_settings)
            self.mic.chain.enabled = bool(self.board.voice_on)
            # The plugin the board asked for, on a thread, because it takes
            # over a second and the window should be up before then.
            wx.CallAfter(self._restore_voice_plugin)

        #: Everything else you want on the air: a second microphone, a games
        #: call, a browser through a virtual cable. The mixer takes one object
        #: for monitoring and one for the air mix, so the group looks like one
        #: input and sums the rest behind it.
        self.sources = [sources.Source.from_dict(entry, self.mixer.samplerate)
                        for entry in (self.board.sources or [])]
        self.source_group = sources.SourceGroup(self.mic, self.sources)
        self.mixer.monitor_source = self.source_group

        #: This show, out of a sound card, so another program on this machine
        #: can take it. None until the board asks for one. Unlike the stream
        #: it IS restored on startup: a send is a piece of wiring rather than
        #: a broadcast, and nothing goes out of it that was not going out of
        #: the speakers anyway. See send.py.
        self.send = None

        #: Why the send is not running, when the board asked for one. Empty
        #: when there is nothing wrong. `board.send_on` is the intent and
        #: survives a failure, so these two together answer both halves of
        #: "should there be a send" and "is there one".
        self.send_failed = ""

        #: The stream, once there is one. None is off air, and off air is
        #: where this starts every single time: a program that could begin
        #: broadcasting by itself is not one to leave near a microphone.
        self.streamer = None
        self.air_bus = None
        self.mixer.bed_fade_in = self.board.bed_fade_in
        self.mixer.bed_fade_out = self.board.bed_fade_out
        # set_device clears the decode cache, so the whole board just went
        # cold. Warm it again rather than making the next key pay for it.
        self.warm_cache()

        self._start_player()
        # The board that just loaded may be a running order nobody has read
        # the tags of yet: boards saved before 2.6.0 have none.
        wx.CallAfter(self.scan_playlist_metadata)

        self._build_menu()
        self._build_ui()
        self._build_accelerators()

        if self.board.send_on:
            # Quiet, because the startup line says it. A card that has been
            # unplugged since the board was saved turns the send off and is
            # reported there rather than in a box nobody asked for.
            self._start_send(quiet=True)

        self._playing = set()
        self._refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_refresh_tick, self._refresh_timer)
        self._refresh_timer.Start(250)

        self._save_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self._save(quiet=True), self._save_timer)

        # System-wide hotkeys. Off until the user turns them on, because while
        # they are on this app owns those combinations across the whole machine.
        self.hotkeys = globalhotkeys.GlobalHotkeys(
            on_fire=self.trigger, on_problem=self._on_hotkey_problem)
        self._sync_global_hotkeys()
        if self.board.global_hotkeys_on:
            self.hotkeys.start()
        self.global_item.Check(self.hotkeys.enabled)

        self.Bind(wx.EVT_CLOSE, self._on_close)
        # Focus moving anywhere in the window decides which keyboard map is
        # installed: the full one, or the one that keeps its hands off a text
        # box. See _apply_accelerators.
        self.Bind(wx.EVT_CHILD_FOCUS, self._on_child_focus)
        self.Bind(wx.EVT_IDLE, self._on_idle)
        self._size_window()
        # Deferred: this ran before the window was shown, so a screen reader's
        # own announcement of the new window arrived on top of it and the
        # important lines - files missing, audio did not start - were the ones
        # that got cut.
        wx.CallLater(500, self._announce_startup)
        # The folder the last update was unpacked into. The copy that did the
        # replacing was running from inside it and could not delete the ground
        # it was standing on; this one can.
        wx.CallLater(3000, self._clean_update_staging)
        # Opening a sound card takes a moment each, and a source that is not
        # plugged in has to time out before it says so. Neither belongs in
        # front of the window appearing.
        wx.CallLater(1200, self.start_sources)
        # Anything queued from last time goes out on its own, and the word
        # about donating comes well after the app has said hello - the first
        # thing it says to somebody is about their board, never about money.
        feedback.flush_in_background()
        wx.CallLater(4000, self._maybe_ask_about_donating)
        self._start_update_check()
        self.warm_cache()

    def warm_cache(self):
        """Decode every short sound in the background, so no key is the first.

        Measured before this existed: the first press of a bed cost 87.5 ms on
        the UI thread and the first press of an effect 7.6 ms, against 0.6 ms
        once warm. That is a frozen message pump sitting exactly between the
        keypress and the sound - and between the keypress and the
        announcement. Mixer.set_device clears the cache, so the whole board
        goes cold again after any audio-device change; this is called there too.
        """
        import threading

        # Folder slots are counted here rather than on the trigger path. The
        # scan is a listdir, which is fast, but "fast" is not the standard
        # between a keypress and a sound.
        folders = self.board.scan_folders()
        paths = [s.filepath for s in self.board.slots
                 if s.filepath and not s.is_missing and not s.is_folder
                 and (s.duration or 0) <= C.PRELOAD_SECONDS]
        for slot in folders:
            paths.extend(slot.folder_files)
        if folders:
            wx.CallAfter(self._folders_counted, folders)
        if not paths:
            return

        def work():
            for path in paths:
                if self._closing.is_set():
                    return
                try:
                    self.mixer._cached(path)
                except Exception:
                    pass          # a bad file is the trigger path's problem

        self._warm_thread = threading.Thread(target=work, daemon=True,
                                             name="dropdeck-warm")
        self._warm_thread.start()

    def scan_playlist_metadata(self):
        """Fill in artists, titles and run outs, in the background.

        Two things come out of this, and both of them have to be measured
        rather than guessed:

        - **The artist and the title**, out of the file's own tags, so a
          running order reads "Dancing Queen, Abba" and not "03 Track 3".
        - **The run out**, the silence on the end of the file, which is what
          the cue point is taken from. An MP3 routinely carries a second or
          two of it; cueing from the last sample put most of a three second
          crossfade inside that silence, and what you heard was one song
          ending and the next one creeping up on its own.

        On a thread, because measuring a run out means decoding, and pasting
        an album must not stop the app. Rows are written back on the UI thread
        in one go at the end, cell by cell, so a screen reader standing on a
        row is not read the whole list again.
        """
        import threading

        running = self._metadata_thread
        if running is not None and running.is_alive():
            # One pass at a time. Whatever arrived while it was working is
            # picked up when it finishes; see _playlist_metadata_ready.
            return None
        pending = self.board.playlist.needs_metadata()
        if not pending:
            return None

        def work():
            changed = False
            for track in pending:
                if self._closing.is_set():
                    return
                try:
                    changed = track.read_metadata() or changed
                except Exception:
                    pass          # a broken file is the trigger path's problem
            if changed and not self._closing.is_set():
                wx.CallAfter(self._playlist_metadata_ready)

        thread = threading.Thread(target=work, daemon=True,
                                  name="dropdeck-playlist-tags")
        self._metadata_thread = thread
        thread.start()
        return thread

    def _playlist_metadata_ready(self):
        """The background pass found something. Show it, quietly."""
        if self._closing.is_set():
            return
        try:
            self.playlist_panel.refresh(keep=self.playlist_panel.selection())
            self._touch()
        except Exception:
            pass
        self._metadata_thread = None
        # Anything pasted while that pass was running.
        self.scan_playlist_metadata()

    def _size_window(self):
        """Size in DIP, then clamp to the screen.

        The old fixed 1000x700 was in physical pixels. That was harmless while
        the app was DPI-unaware and Windows scaled the whole window; once it
        started drawing its own pixels, the fonts grew and the window did not,
        and button labels lost their first characters - "3. audience laugh"
        came out as "audience laugh". Sizing in DIP scales the window with the
        text it has to hold.
        """
        size = self.FromDIP(wx.Size(1040, 720))
        index = wx.Display.GetFromWindow(self)
        client = wx.Display(index if index != wx.NOT_FOUND else 0).GetClientArea()
        size.width = min(size.width, client.width - self.FromDIP(20))
        size.height = min(size.height, client.height - self.FromDIP(20))
        self.SetSize(size)
        self.SetMinSize(self.FromDIP(wx.Size(820, 560)))
        self.Centre()

    # ------------------------------------------------------------- start up --
    def _load_startup_board(self):
        """Your board if you have one, otherwise the demo pack.

        A first run should make a noise, not present eighty empty buttons. The
        demo board is loaded but its path is not kept, so the first save writes
        to your own config and never back over the shipped pack.
        """
        path = default_board_path()
        if os.path.exists(path):
            try:
                return Board.load(path)
            except Exception:
                pass
        demo = demo_board_path()
        if os.path.exists(demo):
            try:
                board = Board.load(demo)
                board.path = path
                self._loaded_demo = True
                return board
            except Exception:
                pass
        return Board()

    def _resolve_device(self):
        """Turn the remembered device name back into an index, if it is still
        there. Names survive replugging; indices do not."""
        return resolve_device({"name": self.board.device_name,
                               "hostapi": self.board.device_hostapi})

    def _resolve_bank_devices(self):
        """Every bank's output, as live indices.

        A bank with no entry, or one whose device is not plugged in today,
        resolves to None and plays through the main output. That is a
        deliberate silent fallback HERE - the group reports a real problem
        separately when a stream refuses to open, which is the case worth
        telling somebody about.
        """
        main = self._resolve_device()
        devices = {bank: main for bank in range(1, C.BANK_COUNT + 1)}
        for bank, spec in (self.board.bank_devices or {}).items():
            index = resolve_device(spec)
            if index is not None:
                devices[bank] = index
        return devices

    def _announce_startup(self):
        # Wrapped, because this runs inside a wx.CallLater: anything raised
        # here is swallowed by the timer and the user simply never hears the
        # line. That is exactly how the MixerGroup.stream bug survived three
        # releases. A failure to speak must not also be a failure to notice.
        try:
            self._startup_line()
        except Exception as exc:                        # pragma: no cover
            self.status.SetStatusText("Startup announcement failed: %s" % exc, 1)

    def _startup_line(self):
        bits = [f"{C.APP_NAME} ready"]
        if self._loaded_demo:
            bits.append(f"demo pack loaded, {self.board.assigned_count} sounds "
                        "and beds. File, new board starts you from scratch")
        else:
            bits.append(f"{self.board.assigned_count} sounds loaded")
        missing = len(self.board.missing_slots)
        if missing:
            bits.append(f"{missing} files missing. Use File, relink missing sounds")
        if not self.mixer.is_running:
            bits.append(f"Audio could not start. {self.mixer.last_error or ''}")
        # A send the board asked for and did not get. _start_send is called
        # quietly at startup with a comment saying this line would say so,
        # and this line had no send branch at all, so a cable that had been
        # unplugged since yesterday was silent in every single place.
        send_failed = bool(self.board.send_on) and not self.sending()
        if send_failed:
            bits.append(getattr(self, "send_failed", "")
                        or "The send could not start, so nothing is going to "
                           "another program. Alt+Shift+O to set it up again")
        elif self.sending():
            # Said out loud every time, on the channel that is not silenced.
            # A board file decides this, and a board file quietly putting the
            # microphone out of a sound card is not something to find out
            # about later.
            bits.append("Sending your whole show to %s for another program "
                        "to pick up" % self.send.describe())
        for line in self._routing_conflicts():
            # A saved board can restore a routing that collides. It used to
            # be checked only when somebody opened the send window.
            bits.append(line)
        # "40 sounds loaded" is a pleasantry. "3 files missing" and "audio
        # could not start" are not, so the same line changes channel when it
        # is carrying one of them.
        wrong = (bool(missing) or not self.mixer.is_running or send_failed
                 or bool(self._routing_conflicts()))
        (self.announce if wrong else self.announce_help)(". ".join(bits))

    # ------------------------------------------------------------------ ui ---
    def _tab_title(self, bank):
        """Nothing on the tab strip said which banks hold anything."""
        n = sum(1 for slot in self.board.bank_slots(bank) if slot.is_assigned)
        # The number stays whatever the tab is called. It is which Ctrl+Tab
        # position you are on and which modifier fires it, and renaming a bank
        # does not move either of those.
        return "%d. %s (%d)" % (bank, self.board.bank_name(bank), n)

    def _on_bank_changed(self, event):
        bank = event.GetSelection() + 1
        # Once per bank per session, then never again. A screen reader already
        # says "Dialog Drops, tab selected", so twenty words of help on top of
        # that is two announcements for one keystroke - which is exactly what
        # Brian Hartgen wrote in about. The hint is still printed on the page
        # and still in F1, so nothing has been taken away.
        if bank in C.BANK_TITLES and bank not in self._hinted_banks:
            self._hinted_banks.add(bank)
            # The hint describes what the keys do, which renaming does not
            # change, so it is the shipped text either way - said after the
            # user's own name for the bank rather than instead of it.
            self.announce_help("%s. %s"
                               % (self.board.bank_name(bank), C.BANK_HINTS[bank]))
        event.Skip()

    def _refresh_tab_titles(self):
        for bank in range(1, C.BANK_COUNT + 1):
            self.notebook.SetPageText(bank - 1, self._tab_title(bank))

    def _build_ui(self):
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        # Two views in one window: the soundboard, and the playlist. A
        # Simplebook rather than another notebook, because nesting a tab strip
        # inside a tab strip gives a screen reader two levels of "tab" to walk
        # and Ctrl+Tab two meanings. The view is changed by key and by menu,
        # and announced when it changes - see show_view.
        self.views = wx.Simplebook(panel)
        self.views.SetName("View")

        board_page = wx.Panel(self.views)
        board_sizer = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Notebook(board_page)
        self.notebook.SetName("Banks")
        self.pages = {}
        for bank in range(1, C.BANK_COUNT + 1):
            page = BankPage(self.notebook, self, bank)
            self.notebook.AddPage(page, self._tab_title(bank))
            self.pages[bank] = page
        board_sizer.Add(self.notebook, 1, wx.EXPAND)
        board_page.SetSizer(board_sizer)

        self.playlist_panel = PlaylistPanel(self.views, self)
        self.views.AddPage(board_page, "Soundboard")
        self.views.AddPage(self.playlist_panel, "Playlist")
        self.views.SetSelection(VIEW_BOARD)
        # Say which bank you landed in. The tab is a sibling of the page in the
        # accessibility tree, not an ancestor of the buttons, so a screen
        # reader announces the button and never the bank - and the button label
        # deliberately leaves the bank out because "the tab already said it".
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_bank_changed)
        outer.Add(self.views, 1, wx.EXPAND | wx.ALL, 6)

        stop = wx.Button(panel, ID_STOP_ALL,
                         "Stop everything  (Escape three times)")
        stop.SetFont(stop.GetFont().Bold())
        stop.SetMinSize(wx.Size(-1, self.FromDIP(38)))
        stop.SetToolTip("Stop every sound and bed, with a short fade. "
                        "This button does it at once; Escape needs three "
                        "presses, so a stray one cannot take the show off")
        stop.Bind(wx.EVT_BUTTON, lambda _e: self.stop_all())
        outer.Add(stop, 0, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(outer)

        self.status = self.CreateStatusBar(2)
        # The announcement needs the room; the volume readout is short and
        # fixed. This was the other way round, so every message was cut.
        self.status.SetStatusWidths([-2, -5])
        self._update_status()

    def _build_menu(self):
        bar = wx.MenuBar()

        file_menu = wx.Menu()
        file_menu.Append(wx.ID_NEW, "&New board\tCtrl+N", "Start with eighty empty slots")
        file_menu.Append(wx.ID_SAVE, "&Save board\tCtrl+S", "Save this board")
        # F12, not Ctrl+Shift+S. 2.5.0 gave Ctrl+Shift+S to the soundboard
        # view, and a frame accelerator beats a menu one - so Save board as
        # quietly stopped working and nothing said a word about it. F12 is
        # what Save As is on in Word and Excel, so it is not an invention.
        file_menu.Append(ID_SAVE_AS, "Save board &as...\tCtrl+F12",
                         "Save this board to a file of its own")
        file_menu.Append(wx.ID_OPEN, "&Open board...\tCtrl+O", "Open a saved board")
        file_menu.Append(ID_IMPORT, "&Import an old soundboard bank...",
                         "Load a bank from The Tony Gebhard Show Soundboard")
        file_menu.Append(ID_DEMO, "Load the &demo pack",
                         "The twenty sounds and twenty beds that ship with the app")
        file_menu.AppendSeparator()
        file_menu.Append(ID_RELINK, "&Relink missing sounds...",
                         "Find moved files and point the board at them")
        file_menu.Append(ID_SETTINGS, "&Preferences...\tCtrl+P",
                         "Output, sounds, playlist, microphone and speech")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4")
        bar.Append(file_menu, "&File")

        sounds = wx.Menu()
        sounds.Append(ID_ASSIGN, "&Assign a sound file...", "Put a sound in this slot")
        sounds.Append(ID_RENAME, "Re&name\tF2", "Rename the sound you are on")
        sounds.Append(ID_TRIM, "&Level for this sound...", "Trim one slot on its own")
        sounds.Append(ID_HOTKEY, "Assign a &hotkey...", "Bank four only")
        sounds.Append(ID_GLOBAL_HOTKEY, "Assign a &global hotkey...",
                      "A key that fires this sound even when another window "
                      "has focus")
        sounds.Append(ID_LOOP, "Toggle loo&ping", "Bank three only")
        sounds.Append(ID_PROPERTIES, "P&roperties...\tAlt+Enter",
                      "Name, level and both hotkeys for this sound, in one place")
        sounds.Append(ID_CLEAR_FOCUSED, "&Clear this slot\tDel")
        sounds.AppendSeparator()
        # Twenty slots a bank is what it ships with, not what everybody wants.
        # Removing one keeps its sound and its keys and simply takes it off
        # the board, and it never renumbers anything else.
        sounds.Append(ID_REMOVE_SLOT,
                      "Re&move this slot from the board	Shift+Del",
                      "Take this pad off the board. Nothing else moves, and "
                      "you can put it back")
        sounds.Append(ID_RESTORE_SLOT, "Put a remo&ved slot back...",
                      "Choose one of the slots you have taken off this bank")
        sounds.Append(ID_RESTORE_ALL_SLOTS, "Put this bank's sl&ots back")
        sounds.AppendSeparator()
        sounds.Append(ID_SEARCH, "&Search sounds...\tCtrl+F", "Find a sound by name")
        sounds.Append(ID_WHATS_PLAYING, "&What is playing\tCtrl+L")
        sounds.Append(ID_DUCK, "&Ducking on or off\tCtrl+D")
        sounds.Append(ID_STOP_LATEST, "Stop the las&t sound" + chr(9)
                      + "Ctrl+Space",
                      "Stops the most recent sound and leaves everything else "
                      "playing. Press it again for the one before that")
        sounds.Append(ID_STOP_ALL, "Stop &everything",
                      "Stops every sound, bed and the running order. "
                      "Escape three times does it from the keyboard")
        sounds.AppendSeparator()
        # A check item, so the menu itself says whether global hotkeys are
        # armed. While they are on, this app owns those combinations across the
        # whole machine, so "is it on right now" has to be answerable without
        # pressing anything.
        self.global_item = sounds.AppendCheckItem(
            ID_GLOBAL_TOGGLE, "Glo&bal hotkeys\tCtrl+G",
            "Let assigned hotkeys fire this board from any program")
        sounds.Insert(1, ID_ASSIGN_FOLDER, "Assign a &folder...",
                      "Play a different sound from this folder every press")
        bar.Append(sounds, "&Sounds")

        # Banks get a menu of their own. Renaming one is not a thing you do to
        # a sound, and burying it in the Sounds menu would put it where nobody
        # would look for it.
        banks = wx.Menu()
        banks.Append(ID_RENAME_BANK, "Re&name this bank...\tCtrl+F2",
                     "Call this bank whatever your board needs it to be called")
        banks.Append(ID_RESET_BANK, "&Reset this bank's name",
                     "Put the shipped name back")
        bar.Append(banks, "&Banks")

        # The playlist. Everything it can do is here, because a view you reach
        # with a key still has to be findable by somebody who does not know
        # the key yet.
        pl = wx.Menu()
        pl.Append(ID_VIEW_PLAYLIST, "Go to the &playlist\tCtrl+Shift+P")
        pl.Append(ID_VIEW_BOARD, "Go to the &soundboard\tCtrl+Shift+S")
        pl.Append(ID_VIEW_NEXT, "S&wap between the two\tCtrl+Alt+Tab",
                  "Windows may take this key for its own task switcher; the "
                  "two above always work")
        pl.AppendSeparator()
        pl.Append(ID_PL_PASTE, "Paste son&gs from the clipboard\tCtrl+V",
                  "Copy files in File Explorer, then paste them in here")
        pl.Append(ID_PL_ADD, "&Add songs to the end...")
        pl.Append(ID_PL_DROP_RANDOM, "Insert a &random drop\tAlt+D",
                  "One from your drops library, never the same one twice "
                  "running")
        pl.Append(ID_PL_DROP, "Insert a drop from a f&ile...\tCtrl+Shift+D",
                  "Put a particular file in front of the item you are on")
        pl.Append(ID_PL_LIBRARY, "Drops li&brary...",
                  "The idents and stingers Alt+D reaches for")
        pl.Append(ID_PL_DROP_EVERY, "Insert a drop every so man&y songs...")
        pl.AppendSeparator()
        pl.Append(ID_PL_CHECK_ALL, "Tic&k every track",
                  "Everything in the running order will play. "
                  "Shift+A in the list does it too")
        pl.Append(ID_PL_UNCHECK_ALL, "&Untick every track",
                  "Nothing plays until you tick it again. Space toggles one, "
                  "Shift+U in the list unticks the lot")
        pl.AppendSeparator()
        pl.Append(ID_PL_PLAY, "Play &from here\tCtrl+Shift+Enter")
        pl.Append(ID_PL_GOTO_PLAYING, "Go to w&hat is on air\tCtrl+Shift+L",
                  "Put the cursor on the track that is playing")
        pl.Append(ID_PL_NEXT, "&Next track")
        pl.Append(ID_PL_PREV, "Pre&vious track")
        pl.Append(ID_PL_STOP, "Stop the play&list")
        pl.AppendSeparator()
        pl.Append(ID_PL_CROSSFADE, "&Crossfade between tracks",
                  "Go to the crossfade box in the playlist view")
        pl.AppendSeparator()
        # A show is worth keeping. M3U rather than a format of our own, so
        # the file opens in VLC, on a phone, or in whatever the studio runs.
        pl.Append(ID_PL_SAVE, "Sav&e the running order...",
                  "Write this running order to an M3U playlist file")
        pl.Append(ID_PL_OPEN, "&Open a running order...",
                  "Load an M3U playlist file in place of this one")
        pl.AppendSeparator()
        pl.Append(ID_PL_CLEAR, "Clear the running or&der")
        pl.AppendSeparator()
        self.mic_item = pl.AppendCheckItem(
            ID_MIC_TOGGLE, "&Microphone on\tCtrl+M",
            "While it is on, the beds and the playlist duck out of the way")
        pl.Append(ID_MIC_SETTINGS, "Microphone se&ttings...\tCtrl+Shift+M",
                  "Which microphone, how much gain, which output you hear it "
                  "on, and whether you hear it at all")
        bar.Append(pl, "P&laylist")

        help_menu = wx.Menu()
        help_menu.Append(ID_SHORTCUTS, "&Keyboard shortcuts\tF1")
        help_menu.Append(ID_USER_GUIDE, "User &manual...",
                         "Opens the full manual at tgstudios.app in your "
                         "browser")
        # In the app rather than only on the web, because setting streaming up
        # is done with the app open, one field at a time, and sending somebody
        # to a browser mid task loses them their place.
        help_menu.Append(ID_STREAM_HELP, "Se&tting up streaming...",
                         "Step by step for YouTube, Facebook, Restream and "
                         "your own server, without leaving the app")
        help_menu.Append(ID_CHECK_UPDATES, "Check for &updates")
        help_menu.AppendSeparator()
        help_menu.Append(ID_FEEDBACK, "&Submit feedback...",
                         "Tell us what happened, or what would make this "
                         "better")
        help_menu.Append(ID_DONATE, "&Donate...",
                         "Drop Deck is free. Donations go into development, "
                         "server costs and new products")
        help_menu.AppendSeparator()
        help_menu.Append(wx.ID_ABOUT, "&About")
        air = wx.Menu()
        # TWO ITEMS, because there are two destinations and they are not
        # the same broadcast. The old single item went wherever Streaming
        # location happened to be pointed, so the summary in front of you
        # before going live was for a destination you had chosen on another
        # day. Now the key says which.
        self.stream_item = air.Append(
            ID_STREAM_TOGGLE, "&Go live on video\tCtrl+B",
            "Send the show to your video platform, and stop sending it")
        self.stream_audio_item = air.Append(
            ID_STREAM_TOGGLE_AUDIO, "Go live on ra&dio\tAlt+Shift+B",
            "Send the show to your radio station, and stop sending it")
        air.Append(ID_STREAM_STATUS, "&What the stream is doing\tCtrl+Shift+B",
                   "Whether it is on air, for how long, and whether anything "
                   "has been lost")
        air.Append(ID_STREAM_STATS, "Who is &listening...\tCtrl+Shift+A",
                   "How many people are on the stream, and what the server "
                   "thinks is playing")
        # Alt+M for caMera. Not Alt+S: Station already has it on this menu,
        # and two items sharing a mnemonic means the first one wins and the
        # second is unreachable by keyboard. tests/test_menus.py caught it.
        air.Append(ID_SHOT, "What the ca&mera can see\tCtrl+Shift+F",
                   "Whether you are in shot, centred and lit. It answers "
                   "whether or not you are on air")
        air.AppendSeparator()
        self.record_item = air.Append(
            ID_RECORD, "Start &recording\tCtrl+R",
            "Record the show to a file. It does not need you to be on air")
        self.video_record_item = air.Append(
            ID_VIDEO_RECORD, "R&ecord picture and sound" + chr(9)
            + "Ctrl+Shift+R",
            "Record the picture as well as the sound, to one MP4. It does "
            "not need you to be on air")
        air.Append(ID_SOURCE_CONTROL,
                   "Source &control..." + chr(9) + "Alt+Ctrl+Shift+S",
                   "Mute, solo, rename or remove a source while you are on "
                   "air")
        # Alt+N, not the obvious Alt+W: "What the stream is doing" already
        # holds W on this menu, and tests/test_menus.py treats a menu and
        # its submenus as one mnemonic namespace.
        air.Append(ID_ON_SCREEN, "What is o&n screen\tCtrl+Shift+V",
                   "Everything the audience can see right now: the picture, "
                   "and anything on top of it")
        air.Append(ID_SHOT_CHECK,
                   "C&heck my shot..." + chr(9) + "Alt+Shift+D",
                   "Ask Claude, ChatGPT or Gemini to look at the picture "
                   "going out and say what is wrong with it. Never needed to "
                   "go live, and going live never waits for it")
        air.Append(ID_COLOURS, "C&olours..." + chr(9) + "Alt+Shift+C",
                   "Your brand: the background everything sits on, the "
                   "colour of the words, and the accent. Every choice says "
                   "how well it will read")
        air.Append(ID_SCREEN_TEXT,
                   "Screen &text..." + chr(9) + "Alt+Shift+T",
                   "Your station name, what is playing, a clock or your own "
                   "words, in named places on the picture")
        air.Append(ID_VIDEO_SOURCES,
                   "&Video source..." + chr(9) + "Alt+Shift+V",
                   "What the stream is showing: a card, your artwork, a "
                   "camera, your screen. It can be changed while you are on "
                   "air")
        air.Append(ID_SOURCES, "&Audio sources..." + chr(9) + "Alt+Shift+S",
                   "Other inputs to put on the air: a second microphone, a "
                   "mixer, or one program's audio"),
        air.AppendSeparator()
        # The send. This menu is nearly out of mnemonics: A, C, D, F, G, H,
        # L, M, N, O, P, R, S, T, U, V and W are all spoken for, so these
        # three are worded around the letters that are left rather than the
        # other way round. tests/test_menus.py is what enforces it, and it
        # counts a submenu HEADER as no mnemonic at all.
        self.send_item = air.Append(
            ID_SEND_SETUP,
            "Send th&is show to another program..." + chr(9)
                   + "Alt+Shift+O",
                   "Your whole show out of a sound card, so TeamTalk, Zoom or "
                   "anything else on this machine can take it. It does not "
                   "need you to be on air")
        self.send_monitor_item = air.AppendCheckItem(
            ID_SEND_MONITOR, "Hear what is &being sent" + chr(9)
            + "Ctrl+Shift+H",
            "Listen to exactly what the other program is being handed. It "
            "goes to your monitor output and never back into the send")
        air.Append(ID_ROUTING,
                   "Where is ever&ything going" + chr(9) + "Ctrl+Shift+W",
                   "Every output at once: your sounds, what you hear, and "
                   "what another program is being sent")
        air.Append(ID_SEND_STATUS,
                   "Is the send &keeping up" + chr(9) + "Ctrl+Shift+O",
                   "Where it is going, what it is leaving out, and whether it "
                   "is arriving without gaps")
        air.AppendSeparator()
        air.Append(ID_RECORD_FOLDER, "Open the recordings &folder",
                   "Where your recordings are saved")
        air.AppendSeparator()
        # Switching station without going through Preferences, because on a
        # show you want it on a menu, not four keystrokes into a dialog.
        # "Station" said what the entries were and not what the menu is FOR.
        # This is the menu that answers "where does Ctrl+B send the show", so
        # it is named after the question.
        self.station_menu = wx.Menu()
        air.AppendSubMenu(self.station_menu, "Streaming &location")
        self._rebuild_station_menu()
        air.Append(ID_STREAM_SETUP, "Set &up streaming...",
                   "The address, the mount point and the password for your "
                   "server")
        bar.Append(air, "&On air")

        bar.Append(help_menu, "&Help")

        self.SetMenuBar(bar)

        self.Bind(wx.EVT_MENU, self._on_new, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, lambda _e: self._save(), id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self._on_save_as, id=ID_SAVE_AS)
        self.Bind(wx.EVT_MENU, self._on_open, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self._on_import, id=ID_IMPORT)
        self.Bind(wx.EVT_MENU, self._on_load_demo, id=ID_DEMO)
        self.Bind(wx.EVT_MENU, self._on_relink, id=ID_RELINK)
        self.Bind(wx.EVT_MENU, self._on_assign_global_hotkey, id=ID_GLOBAL_HOTKEY)
        self.Bind(wx.EVT_MENU, self._on_global_toggle, id=ID_GLOBAL_TOGGLE)
        self.Bind(wx.EVT_MENU, self._on_check_updates, id=ID_CHECK_UPDATES)
        self.Bind(wx.EVT_MENU, self._on_settings, id=ID_SETTINGS)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("assign"), id=ID_ASSIGN)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("folder"),
                  id=ID_ASSIGN_FOLDER)
        self.Bind(wx.EVT_MENU, self._on_rename_bank, id=ID_RENAME_BANK)
        self.Bind(wx.EVT_MENU, lambda _e: self.show_view(VIEW_BOARD),
                  id=ID_VIEW_BOARD)
        self.Bind(wx.EVT_MENU, lambda _e: self.show_view(VIEW_PLAYLIST),
                  id=ID_VIEW_PLAYLIST)
        self.Bind(wx.EVT_MENU, lambda _e: self.show_view(None), id=ID_VIEW_NEXT)
        self.Bind(wx.EVT_MENU, self._on_playlist_paste, id=ID_PL_PASTE)
        self.Bind(wx.EVT_MENU, lambda _e: self.add_playlist_files(), id=ID_PL_ADD)
        self.Bind(wx.EVT_MENU, lambda _e: self.insert_playlist_drop(), id=ID_PL_DROP)
        self.Bind(wx.EVT_MENU, lambda _e: self.insert_random_drop(),
                  id=ID_PL_DROP_RANDOM)
        self.Bind(wx.EVT_MENU, lambda _e: self.insert_random_drop(),
                  id=ID_PL_ROW_RANDOM)
        self.Bind(wx.EVT_MENU, self._on_drops_library, id=ID_PL_LIBRARY)
        self.Bind(wx.EVT_MENU, lambda _e: self.add_selected_to_library(),
                  id=ID_PL_ROW_TO_LIBRARY)
        self.Bind(wx.EVT_MENU, self._on_drop_every, id=ID_PL_DROP_EVERY)
        self.Bind(wx.EVT_MENU, self._on_playlist_play, id=ID_PL_PLAY)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.playlist_panel.go_to_playing(),
                  id=ID_PL_GOTO_PLAYING)
        self.Bind(wx.EVT_MENU, lambda _e: self.playlist_next(), id=ID_PL_NEXT)
        self.Bind(wx.EVT_MENU, lambda _e: self.playlist_previous(), id=ID_PL_PREV)
        self.Bind(wx.EVT_MENU, lambda _e: self.stop_playlist(), id=ID_PL_STOP)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self._all_ticked(True), id=ID_PL_CHECK_ALL)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self._all_ticked(False), id=ID_PL_UNCHECK_ALL)
        # The row menu. Its items are raised on the list, which is a
        # descendant of this frame, so the events arrive here on their own.
        self.Bind(wx.EVT_MENU, self._on_playlist_play, id=ID_PL_ROW_PLAY)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.playlist_panel.segue_to_selected(),
                  id=ID_PL_ROW_SEGUE)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.playlist_panel.toggle_selected(),
                  id=ID_PL_ROW_TICK)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.playlist_panel.move_selected(-1),
                  id=ID_PL_ROW_UP)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.playlist_panel.move_selected(1),
                  id=ID_PL_ROW_DOWN)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.playlist_panel.move_to_end(True),
                  id=ID_PL_ROW_TOP)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.playlist_panel.move_to_end(False),
                  id=ID_PL_ROW_BOTTOM)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.playlist_panel.crossfade_selected(),
                  id=ID_PL_ROW_FADE)
        self.Bind(wx.EVT_MENU, lambda _e: self.insert_playlist_drop(),
                  id=ID_PL_ROW_DROP)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.playlist_panel.remove_selected(),
                  id=ID_PL_ROW_REMOVE)
        self.Bind(wx.EVT_MENU, lambda _e: self.add_playlist_files(),
                  id=ID_PL_ROW_ADD)
        self.Bind(wx.EVT_MENU, lambda _e: self.stop_playlist(), id=ID_PL_ROW_STOP)
        self.Bind(wx.EVT_MENU, lambda _e: self.toggle_mic(), id=ID_MIC_TOGGLE)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self.toggle_stream(to=C.LIVE_TO_AUDIO),
                  id=ID_STREAM_TOGGLE_AUDIO)
        self.Bind(wx.EVT_MENU, lambda _e: self.toggle_stream(to=C.LIVE_TO_VIDEO),
                  id=ID_STREAM_TOGGLE)
        self.Bind(wx.EVT_MENU, lambda _e: self.say_stream_status(),
                  id=ID_STREAM_STATUS)
        self.Bind(wx.EVT_MENU, self._on_stream_stats, id=ID_STREAM_STATS)
        self.Bind(wx.EVT_MENU, self.describe_shot, id=ID_SHOT)
        self.Bind(wx.EVT_MENU, self._on_stream_help, id=ID_STREAM_HELP)
        self.Bind(wx.EVT_MENU, lambda _e: self.toggle_recording(), id=ID_RECORD)
        self.Bind(wx.EVT_MENU, lambda _e: self._open_recordings(),
                  id=ID_RECORD_FOLDER)
        self.Bind(wx.EVT_MENU, self._on_sources, id=ID_SOURCES)
        self.Bind(wx.EVT_MENU, self._on_send_setup, id=ID_SEND_SETUP)
        self.Bind(wx.EVT_MENU, self._on_send_monitor, id=ID_SEND_MONITOR)
        self.Bind(wx.EVT_MENU, self._on_send_status, id=ID_SEND_STATUS)
        self.Bind(wx.EVT_MENU, self._on_routing, id=ID_ROUTING)
        self.Bind(wx.EVT_MENU, self.toggle_video_recording,
                  id=ID_VIDEO_RECORD)
        self.Bind(wx.EVT_MENU, self._on_cue_sheet, id=ID_CUE_SHEET)
        self.Bind(wx.EVT_MENU, self._on_video_sources, id=ID_VIDEO_SOURCES)
        self.Bind(wx.EVT_MENU, self._on_screen_text, id=ID_SCREEN_TEXT)
        self.Bind(wx.EVT_MENU, self._on_colours, id=ID_COLOURS)
        self.Bind(wx.EVT_MENU, self._on_shot_check, id=ID_SHOT_CHECK)
        self.Bind(wx.EVT_MENU, self.describe_screen, id=ID_ON_SCREEN)
        self.Bind(wx.EVT_MENU, self._on_live_to, id=ID_LIVE_TO_AUDIO)
        self.Bind(wx.EVT_MENU, self._on_live_to, id=ID_LIVE_TO_VIDEO)
        self.Bind(wx.EVT_MENU, self._on_source_control, id=ID_SOURCE_CONTROL)
        self.Bind(wx.EVT_MENU,
                  lambda _e: self._on_settings(page=SettingsDialog.PAGE_STREAM),
                  id=ID_STREAM_SETUP)
        for offset in range(MAX_STATIONS):
            self.Bind(wx.EVT_MENU, self._on_pick_station,
                      id=ID_STATION_BASE + offset)
        self.Bind(wx.EVT_MENU, self._on_mic_settings, id=ID_MIC_SETTINGS)
        self.Bind(wx.EVT_MENU, self._on_crossfade, id=ID_PL_CROSSFADE)
        self.Bind(wx.EVT_MENU, lambda _e: self.save_playlist_file(),
                  id=ID_PL_SAVE)
        self.Bind(wx.EVT_MENU, lambda _e: self.open_playlist_file(),
                  id=ID_PL_OPEN)
        self.Bind(wx.EVT_MENU, self._on_clear_playlist, id=ID_PL_CLEAR)
        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("playlist", -1),
                  id=ID_VOL_PL_DOWN)
        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("playlist", +1),
                  id=ID_VOL_PL_UP)
        self.Bind(wx.EVT_MENU, self._on_reset_bank_name, id=ID_RESET_BANK)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("rename"), id=ID_RENAME)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("trim"), id=ID_TRIM)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("hotkey"), id=ID_HOTKEY)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("loop"), id=ID_LOOP)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("clear"), id=ID_CLEAR_FOCUSED)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("properties"),
                  id=ID_PROPERTIES)
        self.Bind(wx.EVT_MENU, lambda _e: self.remove_slot(), id=ID_REMOVE_SLOT)
        self.Bind(wx.EVT_MENU, lambda _e: self.restore_slot(),
                  id=ID_RESTORE_SLOT)
        self.Bind(wx.EVT_MENU, lambda _e: self.restore_all_slots(),
                  id=ID_RESTORE_ALL_SLOTS)
        self.Bind(wx.EVT_MENU, self._on_search, id=ID_SEARCH)
        self.Bind(wx.EVT_MENU, self._on_whats_playing, id=ID_WHATS_PLAYING)
        self.Bind(wx.EVT_MENU, self._on_toggle_duck, id=ID_DUCK)
        self.Bind(wx.EVT_MENU, lambda _e: self.stop_all(), id=ID_STOP_ALL)
        self.Bind(wx.EVT_MENU, lambda _e: self._escape_pressed(),
                  id=ID_STOP_ALL_KEY)
        self.Bind(wx.EVT_MENU, lambda _e: self.stop_latest(),
                  id=ID_STOP_LATEST)
        self.Bind(wx.EVT_MENU, self._on_shortcuts, id=ID_SHORTCUTS)
        self.Bind(wx.EVT_MENU, self._on_about, id=wx.ID_ABOUT)
        self.Bind(wx.EVT_MENU, self._on_user_guide, id=ID_USER_GUIDE)
        self.Bind(wx.EVT_MENU, self._on_feedback, id=ID_FEEDBACK)
        self.Bind(wx.EVT_MENU, self._on_donate, id=ID_DONATE)

        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("sfx", -1), id=ID_VOL_SFX_DOWN)
        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("sfx", +1), id=ID_VOL_SFX_UP)
        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("bed", -1), id=ID_VOL_BED_DOWN)
        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("bed", +1), id=ID_VOL_BED_UP)

    def _build_accelerators(self):
        """The whole keyboard map, rebuilt whenever a custom hotkey changes."""
        entries = [
            # F2 renames, because that is what F2 does everywhere else in
            # Windows. The volume keys moved down one to make room: F3 and F4
            # for sounds, F5 and F6 for beds, which is the pairing people
            # expect once F2 is out of the way.
            # Escape, counted rather than acted on. See _escape_pressed.
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_ESCAPE,
                                ID_STOP_ALL_KEY),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F2, ID_RENAME),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F3, ID_VOL_SFX_DOWN),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F4, ID_VOL_SFX_UP),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F5, ID_VOL_BED_DOWN),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F6, ID_VOL_BED_UP),
            # F7 and F8 continue the pattern for the third fader. New keys,
            # not taken off anything.
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F7, ID_VOL_PL_DOWN),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F8, ID_VOL_PL_UP),
            # The two views.
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("P"),
                                ID_VIEW_PLAYLIST),
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("S"),
                                ID_VIEW_BOARD),
            # Save board as. It has to be in the table rather than left to the
            # menu, so that this file is the one place the keyboard map lives
            # and a clash like the one above shows up in the menu sweep.
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_F12, ID_SAVE_AS),
            # Asked for, and bound. Windows reserves Ctrl+Alt+Tab for its own
            # persistent task switcher and usually takes it before any
            # application sees it, which is why the menu says so and why the
            # two keys above exist.
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_ALT, wx.WXK_TAB,
                                ID_VIEW_NEXT),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("V"), ID_PL_PASTE),
            # Ctrl+M opens and closes the microphone, Ctrl+Shift+M sets it up.
            # Both new; nothing on the frozen digit map moved for them.
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("M"), ID_MIC_TOGGLE),
            # Ctrl+B goes live, Ctrl+Shift+B says what the stream is
            # doing, the same shape as the microphone pair above.
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("B"), ID_STREAM_TOGGLE),
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("B"),
                                ID_STREAM_STATUS),
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("A"),
                                ID_STREAM_STATS),
            # Ctrl+Shift+F answers "what can the camera see". F for framing,
            # and it is the key somebody uses over and over while setting a
            # shot up and then never again.
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("F"),
                                ID_SHOT),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("R"), ID_RECORD),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_SPACE, ID_STOP_LATEST),
            # Alt+Shift+S manages sources, whatever kind they are: a sound
            # card, a cable, or a program.
            wx.AcceleratorEntry(wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("S"),
                                ID_SOURCES),
            # And Alt+Shift+O sets up the send, in the same "go and change
            # it" family. Ctrl+Shift+O asks how it is doing, beside
            # Ctrl+Shift+B for the stream. Ctrl+Shift+H turns the confidence
            # feed on and off, because Hearing it is a thing you do during a
            # show. All three are new keys and the digit map is untouched.
            wx.AcceleratorEntry(wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("O"),
                                ID_SEND_SETUP),
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("O"),
                                ID_SEND_STATUS),
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("H"),
                                ID_SEND_MONITOR),
            # Ctrl+Shift+W reads the whole routing out. W for Where.
            #
            # It was Ctrl+Shift+R for one day. Tony took that key back for
            # recording the picture on 10 September 2026, and he was right to:
            # Ctrl+R records audio, so Ctrl+Shift+R recording the picture as
            # well is the same pair as Ctrl+B and Ctrl+Shift+B, and Ctrl+M and
            # Ctrl+Shift+M. A key that has been in the world for one day and
            # in one person's hands is not a key somebody has learned, which
            # is the only reason this was allowed to move at all.
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("W"),
                                ID_ROUTING),
            # Ctrl+R takes the sound, Ctrl+Shift+R takes the picture as well.
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("R"),
                                ID_VIDEO_RECORD),
            # Ctrl+Shift+C is the cue sheet. Tyler asked for it and C is his
            # word for it. A new key; the frozen digit map is untouched.
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("C"),
                                ID_CUE_SHEET),
            # And Alt+Shift+V for the video source, which is the same idea for
            # the other half of the show. Deliberately reachable while live.
            wx.AcceleratorEntry(wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("V"),
                                ID_VIDEO_SOURCES),
            # T for text, in the same family.
            wx.AcceleratorEntry(wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("T"),
                                ID_SCREEN_TEXT),
            # And C for colours, which is the third of the same idea.
            wx.AcceleratorEntry(wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("C"),
                                ID_COLOURS),
            # D for describe. The fourth and last of the picture keys.
            wx.AcceleratorEntry(wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("D"),
                                ID_SHOT_CHECK),
            # Ctrl+Shift+V answers what is on screen. It sits with the other
            # two "tell me" keys rather than with the two "change it" ones.
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("V"),
                                ID_ON_SCREEN),
            wx.AcceleratorEntry(wx.ACCEL_ALT | wx.ACCEL_CTRL | wx.ACCEL_SHIFT,
                                ord("S"), ID_SOURCE_CONTROL),
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("M"),
                                ID_MIC_SETTINGS),
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("D"),
                                ID_PL_DROP),
            # Alt+D drops a random one in from the library. A new key; nothing
            # on the frozen digit map moved for it.
            wx.AcceleratorEntry(wx.ACCEL_ALT, ord("D"), ID_PL_DROP_RANDOM),
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, wx.WXK_RETURN,
                                ID_PL_PLAY),
            # Ctrl+F2 renames the bank, next to the F2 that renames a sound.
            # A new key, not one taken off the frozen digit map.
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_F2, ID_RENAME_BANK),
            # Ctrl+G is a new key, not one taken from the frozen map.
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("G"), ID_GLOBAL_TOGGLE),
            # Ctrl+F is the standard find key and is what the menu advertises.
            # Ctrl+E was it for two releases, so it still works and always
            # will - taking a key back off someone who learned it is not a fix.
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("F"), ID_SEARCH),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("E"), ID_SEARCH),
            # Alt+Enter opens properties, the same as it does in Explorer.
            wx.AcceleratorEntry(wx.ACCEL_ALT, wx.WXK_RETURN, ID_PROPERTIES),
            wx.AcceleratorEntry(wx.ACCEL_ALT, wx.WXK_NUMPAD_ENTER, ID_PROPERTIES),
        ]
        for modifiers, key_code, index in fixed_accelerators():
            entries.append(wx.AcceleratorEntry(modifiers or wx.ACCEL_NORMAL,
                                               key_code, ID_SLOT_BASE + index))
        for slot in self.board.bank_slots(C.BANK_MISC):
            if slot.key_code:
                entries.append(wx.AcceleratorEntry(slot.modifiers or wx.ACCEL_NORMAL,
                                                   slot.key_code,
                                                   ID_SLOT_BASE + slot.index))
        self._accelerators = entries
        # The same map with every bare printable key taken out, for while
        # somebody is typing into a box. See _apply_accelerators.
        self._typing_accelerators = [
            e for e in entries
            if e.GetFlags() != wx.ACCEL_NORMAL or not _is_typed_key(e.GetKeyCode())]
        # Forget which table is installed, so a rebuilt map is always put on
        # rather than skipped because the last one was the same shape.
        self._accelerators_typing = None
        self._apply_accelerators()

        self.Bind(wx.EVT_MENU, self._on_slot_hotkey,
                  id=ID_SLOT_BASE, id2=ID_SLOT_BASE + C.TOTAL_SLOTS)
        # Returned so a test can read the whole map back. wx gives no way to
        # inspect an accelerator table once it is set, and the map is the one
        # thing in this app people have in their fingers.
        return entries

    def _apply_accelerators(self, focus=None):
        """Install the keyboard map that suits where focus is.

        The pads are on bare digits, 1 to 0, and an accelerator table on a
        frame is looked at BEFORE the control with focus gets the key. So
        every digit typed into the crossfade box fired a sound instead of
        going into the box, and the box could not be typed into at all.
        Brian Hartgen: "When focusing upon the crossfade edit field, you
        cannot type a value into there."

        Vetoing it in a key handler does not work: on Windows the char hook
        runs first but the accelerator fires anyway. So the map itself is
        swapped. While a text box has focus the bare printable keys are not
        in it, and every combination with a modifier still is - Ctrl+V still
        pastes, Escape still stops everything, the function keys still work.
        """
        if not getattr(self, "_accelerators", None):
            return
        if focus is None:
            focus = wx.Window.FindFocus()
        if focus is None:
            # Nobody in this process has focus, which happens while the window
            # is not the active one. That is not an answer, and acting on it
            # would put the pads back on under a crossfade box that still has
            # the caret in it, ready for the first digit typed after an
            # Alt+Tab back.
            return
        typing = _is_text_entry(focus)
        entries = self._typing_accelerators if typing else self._accelerators
        if getattr(self, "_accelerators_typing", None) == typing:
            return
        self._accelerators_typing = typing
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

    def _on_child_focus(self, event):
        """Focus moved. Which map is installed follows it.

        The window is taken from the event rather than from FindFocus: this
        event can arrive a moment before Windows has finished moving focus,
        and asking who has it then gives the window that is losing it. Getting
        that backwards leaves the pads switched off, or the crossfade box
        untypeable, until the next time focus moves.

        The CallAfter is the belt to that brace: whatever order the messages
        arrive in, once they have all been handled the map is checked again.
        """
        event.Skip()
        self._apply_accelerators(event.GetWindow())
        wx.CallAfter(self._apply_accelerators)

    def _on_idle(self, event):
        """The map, checked once more whenever there is nothing else to do.

        Focus moving into a wx.SpinCtrlDouble raises NO child focus event at
        all: the control is a composite and the focus lands on the edit box
        inside it, which the frame is never told about. Measured, not
        guessed. So the crossfade box would sometimes still be under the
        pads' keyboard map when the first digit arrived, and that digit fired
        a sound instead of going into the box - which is the whole bug.

        Idle is the reliable one, because it runs whenever the loop has
        nothing left to dispatch, which is always before the next keystroke.
        _apply_accelerators returns immediately unless the answer changed, so
        this costs one FindFocus.
        """
        event.Skip()
        self._apply_accelerators()

    def _on_slot_hotkey(self, event):
        self.trigger(event.GetId() - ID_SLOT_BASE)

    # ------------------------------------------------------ global hotkeys --
    #
    # These fire while another program has focus. They are a second, separate
    # key per slot that the user assigns on purpose - the frozen in-app map is
    # untouched, and nothing here can register a bare key, because a bare
    # system-wide hotkey would take that key away from every other program on
    # the machine.

    def _sync_global_hotkeys(self):
        self.hotkeys.set_bindings({s.index: s.global_hotkey
                                   for s in self.board.slots if s.global_hotkey})

    def _on_hotkey_problem(self, message):
        """A hotkey Windows would not give us. Say so rather than swallow it.

        A hotkey that silently does nothing is worse than one that says it is
        taken: the user presses it on air and gets nothing, with no clue why.
        """
        self.announce(message)
        wx.MessageBox(message, "Global hotkeys", wx.OK | wx.ICON_INFORMATION, self)

    def _on_global_toggle(self, _event=None):
        on = self.hotkeys.toggle()
        self.board.global_hotkeys_on = on
        self.global_item.Check(on)
        self._touch()
        if on:
            count = self.hotkeys.count()
            self.announce(
                "Global hotkeys on. %d %s active."
                % (count, "hotkey" if count == 1 else "hotkeys") if count
                else "Global hotkeys on. None assigned yet. Use Sounds, "
                     "assign a global hotkey.")
        else:
            self.announce("Global hotkeys off. Other programs have those keys "
                          "back.")

    def _on_assign_global_hotkey(self, _event=None):
        slot = self._focused_slot()
        if slot is None:
            return
        dialog = AssignHotkeyDialog(self, slot, global_mode=True)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            text = dialog.hotkey_text()
            if text and globalhotkeys.parse(text) is None:
                self._on_hotkey_problem(globalhotkeys.describe(text))
                return
            slot.global_hotkey = text or None
            self._sync_global_hotkeys()
            self._sync_button(slot)
            self._touch()
            self.announce_help("Global hotkey %s for %s."
                               % (text, slot.display_name) if text
                               else "Global hotkey removed from %s."
                               % slot.display_name)
        finally:
            dialog.Destroy()

    # ------------------------------------------------------------- updates --
    def _start_update_check(self):
        """Look for a new version in the background, throttled to once a day.

        On a worker thread: a slow or unreachable server must never freeze a
        window someone is about to press a key on. Silent unless something is
        actually there.
        """
        import threading

        def work():
            from . import appupdate
            try:
                available, info, _message = appupdate.auto_check(
                    os.path.dirname(default_board_path()))
            except Exception:
                return
            if available and info:
                wx.CallAfter(self._offer_update, info)

        threading.Thread(target=work, daemon=True, name="dropdeck-update").start()

    def _on_check_updates(self, _event=None):
        """Same check, but say something either way because the user asked."""
        import threading
        self.announce_help("Checking for a new version.")

        def work():
            from . import appupdate
            try:
                available, info, message = appupdate.auto_check(
                    os.path.dirname(default_board_path()), force=True)
            except Exception as exc:
                available, info, message = False, None, "Could not check. %s" % exc
            wx.CallAfter(self._update_check_done, available, info, message)

        threading.Thread(target=work, daemon=True, name="dropdeck-update").start()

    def _update_check_done(self, available, info, message):
        """The user asked a question, so answer it in a window either way.

        This used to only speak when there was no update, which meant anybody
        who had turned the app's speech down got silence in reply to choosing
        Check for updates - indistinguishable from the feature being broken.
        """
        if available and info:
            self._offer_update(info)
            return
        problem = ""
        if message and "newest" not in message.lower():
            problem = message          # a real failure, not "you are current"
        self.announce_help(message or "You have the newest version.")
        updatedialog.ask_about_update(self, C.APP_NAME, C.APP_VERSION,
                                      problem=problem)

    def _offer_update(self, info):
        """Ask before downloading, always.

        An app that replaces its own executable without asking is
        indistinguishable from malware, and an installer appearing unannounced
        while the app vanishes underneath it is worse than no update at all for
        someone listening rather than looking. Doubly so on a live show.
        """
        from . import appupdate
        version = info.get("version", "a new version")
        notes = (info.get("notes") or "").strip()
        choice = updatedialog.ask_about_update(
            self, C.APP_NAME, C.APP_VERSION, new_version=version, notes=notes)
        if choice != updatedialog.UPDATE:
            self.announce_help("Update skipped. Help, check for updates when you "
                          "are ready.")
            return
        # A copy running from the zip must never be handed an installer. It
        # would install a SECOND copy somewhere else and leave this one on the
        # old version, silently, which is what happened to HarmonicaPlayer.
        portable = appupdate.is_portable()
        # On a worker thread. This is an HTTPS download of a 40 MB installer;
        # inline it froze the window with only a busy cursor for company.
        import threading
        self.announce_help("Downloading version %s."
                           % info.get("version", "the update"))
        # A real bar, and one that speaks. The busy cursor that used to be
        # here told a sighted user something and a screen reader user
        # nothing at all, for however long 86 MB takes.
        box = updatedialog.DownloadProgressDialog(
            self, self, "version %s" % info.get("version", "the update"))
        box.Show()
        self._update_box = box

        def work():
            try:
                got = appupdate.download(info, progress=_step,
                                         portable=portable)
            except appupdate.Stopped:
                got = (None, "The download was stopped. Nothing was changed.")
            except Exception as exc:
                got = (None, "Download failed. %s" % exc)
            wx.CallAfter(self._download_done, got[0], got[1], info,
                         portable)

        def _step(done, total):
            # Raising out of the progress callback is how the Stop button
            # reaches a download already in flight. appupdate swallows
            # exceptions from progress on purpose, so this uses an error it
            # re-raises for: see the check in _fetch.
            if box.cancelled:
                raise appupdate.Stopped()
            box.step(done, total)

        threading.Thread(target=work, daemon=True, name="dropdeck-dl").start()

    def _download_done(self, path, message, info=None, portable=False):
        from . import appupdate
        box = getattr(self, "_update_box", None)
        if box is not None:
            try:
                box.Destroy()
            except Exception:
                pass
            self._update_box = None
        if not path:
            self.announce(message)
            wx.MessageBox(message, "Update failed", wx.OK | wx.ICON_WARNING, self)
            return
        if portable:
            self._finish_portable_update(path, info or {})
            return
        # Stop the audio device first. The installer replaces the executable
        # underneath a stream that is still running otherwise.
        try:
            self.mixer.close()
        except Exception:
            pass
        ok, message = appupdate.run_installer(path)
        self.announce(message)
        if not ok:
            wx.MessageBox(message, "Update failed", wx.OK | wx.ICON_WARNING, self)

    def _finish_portable_update(self, path, info):
        """Replace this portable copy with the one just downloaded.

        Tony, 5 September 2026: "portable comes with the intended purpose of
        replacing with the new executable that's downloaded."

        Windows will not let a running executable be overwritten, so the new
        copy does the writing: it is unpacked beside this one, started with
        --finish-update, and it waits for this process to disappear before
        replacing the folder and starting the app again from the same path.
        From the outside it is one restart, and the folder keeps its name.

        A copy on a read only share cannot be replaced at all, and there the
        old behaviour is the right one: unpack beside, and say where.
        """
        from . import appupdate
        version = info.get("version", "")
        if appupdate.can_replace():
            self._replace_this_copy(path, version)
            return
        try:
            folder = appupdate.unpack_beside(path, version)
        except Exception as exc:
            message = ("The download was fine but it could not be unpacked. "
                       "%s" % exc)
            self.announce(message)
            wx.MessageBox(message, "Update failed", wx.OK | wx.ICON_WARNING,
                          self)
            return
        message = ("This folder cannot be written to, so version %s has been "
                   "unpacked next to it instead, in %s. Close this copy and "
                   "run TG Drop Deck from that folder. Your board and "
                   "settings are shared, so everything is where you left it."
                   % (version or "the new one", folder))
        self.announce(message)
        answer = wx.MessageBox(
            message + "\n\nOpen that folder now?", "Update ready",
            wx.YES_NO | wx.ICON_INFORMATION, self)
        if answer == wx.YES:
            try:
                os.startfile(folder)          # noqa: S606 - a folder, not input
            except Exception:
                pass

    def _replace_this_copy(self, path, version):
        """Unpack beside, hand over to the new copy, and close."""
        from . import appupdate
        try:
            staging = appupdate.unpack_staging(path, version)
        except Exception as exc:
            message = ("The download was fine but it could not be unpacked. "
                       "%s" % exc)
            self.announce(message)
            wx.MessageBox(message, "Update failed", wx.OK | wx.ICON_WARNING,
                          self)
            return
        here = appupdate.app_folder()
        message = ("Version %s is ready. Drop Deck will close and open again "
                   "on the new version, in the same folder. Your board and "
                   "settings are untouched." % (version or "the new one"))
        if wx.MessageBox(message + "\n\nUpdate now?", "Update ready",
                         wx.YES_NO | wx.ICON_INFORMATION, self) != wx.YES:
            self.announce("Update left for later. The download is kept.")
            return
        if not appupdate.start_swap(staging, here, os.getpid()):
            failed = ("The new copy would not start, so nothing has been "
                      "changed. It is unpacked in %s." % staging)
            self.announce(failed)
            wx.MessageBox(failed, "Update failed", wx.OK | wx.ICON_WARNING,
                          self)
            return
        # It is waiting for this process to end, so end it. The board is
        # saved on the way out by the ordinary close path.
        self.announce("Updating. Drop Deck will open again in a moment.")
        self.Close()

    # -------------------------------------------------------------- speaking --
    #
    # Three channels, because "how much should this app say" has three honest
    # answers and a screen reader is already doing most of the work.
    #
    #   announce()          what you cannot otherwise know - a file that is
    #                       missing, a key Windows would not give us, a number
    #                       you just asked for. Silent only at "none".
    #   announce_help()     confirmations of something you just did, and hints
    #                       you have already read. Silent below "all".
    #   announce_playback() the name of a sound you can hear starting anyway.
    #
    # All three write the status bar at every level, so nothing this app has
    # to say is ever only spoken.

    def _speech_level(self):
        return getattr(self.board, "speech_level", C.DEFAULT_SPEECH_LEVEL)

    def announce_help(self, text):
        """A confirmation, or a hint. Off for anyone who has done their homework.

        Brian Hartgen's point, and it is a fair one: pressing Escape and being
        told everything stopped is the app talking over a screen reader that
        was about to say something useful.
        """
        if self._speech_level() == C.SPEECH_ALL:
            self.speaker.say(text)
        self.status.SetStatusText(text, 1)

    def announce_playback(self, text):
        """A confirmation for something the user can already hear.

        Speech here is optional, because the sound itself is the feedback.
        The status bar is written either way, so the information is still
        on screen and still reachable - only the interruption is optional.

        Failures never come through here. "File missing" and "could not
        play" are exactly the cases you cannot hear, so they always speak.
        """
        if (self._speech_level() == C.SPEECH_ALL
                and getattr(self.board, "announce_playback", True)):
            self.speaker.say(text)
        self.status.SetStatusText(text, 1)

    def announce(self, text):
        if self._speech_level() != C.SPEECH_NONE:
            self.speaker.say(text)
        # A status bar cannot show a sentence and these are sentences, so the
        # field was reweighted to take most of the bar. No tooltip is set here:
        # wxSTB_SHOW_TIPS is on by default and shows the full text on hover
        # whenever a field is truncated, and setting one manually asserts.
        self.status.SetStatusText(text, 1)

    def announce_answer(self, text):
        """A direct answer to a question the user has just asked. Always spoken.

        The fourth channel, and the only one that speaks at every level
        including "none". "None" means the app does not volunteer anything and
        leaves the running commentary to the screen reader, which is the right
        default for somebody who knows the app. It cannot mean that a key
        whose ONLY job is to answer a question does nothing at all: Ctrl+L has
        no other effect, so silent Ctrl+L is a broken key rather than a quiet
        one. Tony, 3 September 2026, with speech set to none: "ctrl L does not
        announce anything while a track is playing."

        Keep this for keys that exist purely to be asked. Anything you can
        hear for yourself, or that a screen reader will read off the control,
        belongs on one of the other three.
        """
        self.speaker.say(text)
        self.note(text)

    def note(self, text):
        """Write the status bar and say nothing.

        For the handful of things a screen reader has already announced
        itself. Ticking a track is the case: the list says "checked" without
        any help, and the app saying "will be skipped" over the top of it is
        two announcements for one keypress. The words are still there to be
        read, which is the rule every other channel here follows.
        """
        # getattr, because the playlist panel is built before the status bar
        # is, and its very first refresh comes through here on the way past.
        status = getattr(self, "status", None)
        if status is not None:
            status.SetStatusText(text, 1)

    def _update_status(self):
        self.status.SetStatusText(
            f"Sound {percent(self.mixer.sfx_gain)} (F3, F4)   "
            f"Beds {percent(self.mixer.bed_gain)} (F5, F6)   "
            f"Playlist {percent(self.mixer.playlist_gain)} (F7, F8)   "
            f"Ducking {'on' if self.mixer.ducking else 'off'} (Ctrl+D)   "
            f"Mic {'ON' if self._mic_open() else 'off'} (Ctrl+M)   "
            f"{self._air_label()} (Ctrl+B)"
            + ("   RECORDING (Ctrl+R)" if self.recording() else "")
            + ("   RECORDING PICTURE (Ctrl+Shift+R)"
               if self.recording_video() else "")
            + self._send_label(), 0)

    def _send_label(self):
        """What the status bar says about the send, or nothing at all.

        Nothing at all when there is no send, because a status bar that names
        every feature you are not using is a status bar nobody reads. Once
        there is one it is worth a word: it is going out of this machine and
        the only other sign of it is on a key.
        """
        send = getattr(self, "send", None)
        if send is None:
            return ""
        ok, _why = send.keeping_up()
        return "   SENDING%s (Alt+Shift+O)" % ("" if ok else ", losing audio")

    def _keep_beds_off_the_playlist(self):
        """A bed and a playlist track are both music, so never both.

        Tony, 4 September 2026: "music beds can not play at the same time as
        tracks in the playlist. if a bed is playing, and a track is clicked
        on, the music bed should fade out and the playlist track should cross
        fade in."

        The playlist wins, and the bed leaves on its own fade rather than
        being cut, so the handover sounds deliberate. Checked here rather than
        where a track is started because a track also starts on its own at
        the end of the one before it, and that never comes through the frame.
        """
        if not self.player.playing:
            return
        gone = self._stop_other_beds(None)
        if gone:
            self.announce_playback("Playlist started, faded out bed %s" % gone)

    def _stop_other_beds(self, keep):
        """Take down every bed but this one. Returns the name of the last.

        Bank 3 is the bed bank, so "is it a bed" is a question about the slot
        rather than about the voice, which is why this reads the board.
        """
        stopped = ""
        for index in list(self.mixer.playing_slots()):
            if index == keep or not 0 <= index < C.TOTAL_SLOTS:
                continue
            # keep=None means every bed, which is what the playlist wants.
            other = self.board[index]
            if not other.is_bed:
                continue
            self.mixer.stop_slot(index)
            self._sync_button(other, playing=False)
            stopped = other.display_name
        return stopped

    def _air_label(self):
        streamer = getattr(self, "streamer", None)
        if streamer is None or not streamer.running:
            return "Off air"
        if streamer.state == streamout.ON_AIR:
            return "ON AIR"
        return streamer.state.capitalize()

    # ------------------------------------------------------------ transport --
    def trigger(self, index):
        """Fire a slot. This is what every hotkey and every button ends up at."""
        if not 0 <= index < C.TOTAL_SLOTS:
            return
        slot = self.board[index]
        if slot.hidden:
            # Taken off the board. Its key does nothing, which is the point of
            # having taken it off, but silence with no explanation reads as a
            # broken key.
            self.note("%s %d has been removed from the board"
                      % (slot.bank_short, slot.number))
            return

        if not slot.is_assigned:
            self.assign_sound(slot)
            return
        if slot.is_missing:
            self.announce(f"{slot.display_name}, "
                          f"{'folder' if slot.folder_count is not None else 'file'}"
                          " missing. Use File, relink missing sounds")
            return

        # A folder slot picks one of its files. The pick uses the last scan,
        # not a fresh listdir: nothing goes between a keypress and a sound.
        path = slot.playable_path()
        if path is None:
            self.announce(f"{slot.display_name} is an empty folder. "
                          "Put some sounds in it, or assign a file instead")
            return
        # A file whose duration we know is a file we can decode instantly. A
        # folder's pick was measured by the warmer, not stored on the slot.
        duration = None if slot.is_folder else slot.duration

        # A slot set to toggle stops itself rather than playing a second copy
        # on top. Beds do this always and are handled below; this is the same
        # behaviour, offered to any slot that wants it, for the long file
        # somebody only ever plays a bit of.
        if (slot.toggle_stop and not slot.is_bed
                and self.mixer.is_playing(index)):
            self.mixer.stop_slot(index, fade_out=self._stop_fade())
            self._forget_recent(index)
            self.announce_playback("Stopped %s" % slot.display_name)
            self._sync_button(slot, playing=False)
            return

        if slot.is_bed:
            if self.mixer.is_playing(index):
                self.mixer.stop_slot(index)
                self.announce_playback(f"Stopped bed, {slot.display_name}")
                self._sync_button(slot, playing=False)
                return
            if self.player.playing:
                # Refused rather than allowed to fight the playlist, and
                # refused rather than stopping the show: taking the playlist
                # off air because somebody leaned on a bed key would be a
                # worse surprise than being told no.
                self.announce("The playlist is playing. Stop it first, or "
                              "this would be two pieces of music at once")
                return
            # One bed at a time. Two music beds running together is two
            # pieces of music fighting, which is a mistake rather than a
            # texture, and on a live show it is a mistake you make by leaning
            # on the wrong key. Starting a bed takes the previous one down
            # with its own fade, so it sounds like a change and not a fault.
            replaced = self._stop_other_beds(index)
            voice = self.mixer.play(index, path, is_bed=True,
                                   loop=slot.loop, trim_db=slot.trim_db,
                                   name=slot.display_name, duration=duration)
            if voice is None:
                self.announce(f"Could not play {slot.display_name}")
                return
            tail = " looping" if slot.loop else ""
            swapped = ", replacing %s" % replaced if replaced else ""
            self.announce_playback(
                f"Playing bed, {slot.display_name}{tail}{swapped}")
            self._sync_button(slot, playing=True)
            return

        voice = self.mixer.play(index, path, is_bed=False, loop=False,
                                trim_db=slot.trim_db, name=slot.display_name,
                                duration=duration)
        if voice is None:
            self.announce(f"Could not play {slot.display_name}")
            return
        # So Ctrl+Space knows which one to take back off again.
        self._remember_played(index)
        if slot.is_folder:
            # Which one you got. The whole feature is that you did not choose,
            # so the app has to say what it chose for you.
            self.announce_playback(
                f"{slot.display_name}, {os.path.splitext(os.path.basename(path))[0]}")
            return
        length = format_duration(slot.duration)
        self.announce_playback(
            f"{slot.display_name}{', ' + length if length else ''}")

    #: How long the presses have to arrive within, in milliseconds. Long
    #: enough to be comfortable, short enough that an Escape now and one in a
    #: minute are not read as the same gesture.
    ESCAPE_WINDOW_MS = 2000

    def _remember_played(self, index):
        """Keep the order things were started in, for Ctrl+Space.

        The mixer knows what is playing but not what was started last, and
        adding a clock to every voice to find out would be work in the audio
        path for the benefit of one key. The frame already knows: it started
        them.
        """
        recent = getattr(self, "_recent", None)
        if recent is None:
            recent = self._recent = []
        if index in recent:
            recent.remove(index)
        recent.append(index)
        del recent[:-C.TOTAL_SLOTS]

    def _forget_recent(self, index):
        recent = getattr(self, "_recent", None)
        if recent and index in recent:
            recent.remove(index)

    def stop_latest(self):
        """Stop the most recent sound that is still playing, and say which.

        Chris Cooke, 5 September 2026: "Is there a way to stop a sound sooner
        than pressing the escape key four times?"

        This is that, without taking overlapping away from everybody: press it
        again and the one before that stops, so a stack of sounds unwinds in
        the order it was built.
        """
        recent = list(getattr(self, "_recent", []))
        while recent:
            index = recent.pop()
            if not self.mixer.is_playing(index):
                self._forget_recent(index)
                continue
            slot = self.board[index]
            self.mixer.stop_slot(index, fade_out=self._stop_fade())
            self._forget_recent(index)
            self._sync_button(slot, playing=False)
            self.announce("Stopped %s" % slot.display_name)
            return True
        # Nothing of ours, but the running order may still be going, and
        # somebody pressing this wants something to stop.
        if self.player.playing:
            self.stop_playlist()
            return True
        self.announce("Nothing is playing")
        return False

    def _stop_fade(self):
        """Nought when the board says stop abruptly, otherwise the usual fade.

        Chris Cooke: "I think an abrupt stop is better because if someone is
        running a mixer, they'll either fade it out themselves or more likely
        adjust it in their DAW."
        """
        return None if self.board.stop_fade else 0.0

    def _escape_pressed(self):
        """Escape, which takes three to stop the show.

        One key that silences everything is one key away from silencing
        everything by accident, and Escape is the key people press when a
        dialog did not close, when a screen reader is talking, or out of
        habit. Three presses in a couple of seconds is unmistakably meant.

        The count is spoken, because a key that appears to do nothing twice
        is a key you assume is broken.
        """
        wanted = max(C.MIN_STOP_PRESSES,
                     min(C.MAX_STOP_PRESSES, int(self.board.stop_presses)))
        now = time.monotonic()
        if now - getattr(self, "_escape_at", 0.0) > self.ESCAPE_WINDOW_MS / 1000.0:
            self._escapes = 0
        self._escape_at = now
        self._escapes = getattr(self, "_escapes", 0) + 1
        if self._escapes < wanted:
            left = wanted - self._escapes
            self.announce("Escape %s more time%s to stop everything"
                          % (("one", "two", "three")[min(2, left - 1)],
                             "" if left == 1 else "s"))
            return
        self._escapes = 0
        self.stop_all()

    def stop_all(self):
        # Asked BEFORE anything is stopped. The playlist is stopped first, so
        # by the time the mixer counted what it had silenced the playlist's
        # voices were already gone, and stopping a song mid show announced
        # "Nothing was playing".
        #
        # Tony, 5 September 2026: "it says 'nothing was playing' when I hit
        # escape 3 times, and yes, something was playing. lol."
        was_playing = bool(self.player.playing)
        # The playlist is part of "everything". Stopping its voices without
        # telling the player would leave it convinced it was still on air.
        self.player.stop(fade_out=None, quiet=True)
        self._player_timer.Stop()
        count = self.mixer.stop_all(fade_out=self._stop_fade())
        self._recent = []
        self.announce_help("Stopping playback" if (count or was_playing)
                           else "Nothing was playing")

    # -------------------------------------------------------------- volumes --
    def _nudge(self, which, direction):
        step = C.VOLUME_STEP * direction
        if which == "sfx":
            self.mixer.set_sfx_gain(self.mixer.sfx_gain + step)
            self.board.sfx_volume = self.mixer.sfx_gain
            self.announce(f"Sound volume {percent(self.mixer.sfx_gain)}")
        elif which == "playlist":
            self.mixer.set_playlist_gain(self.mixer.playlist_gain + step)
            self.board.playlist_volume = self.mixer.playlist_gain
            said = f"Playlist volume {percent(self.mixer.playlist_gain)}"
            if self.streaming() and self.board.playlist_monitor_only:
                # Worth saying while live. Turning the music down and not
                # knowing whether the listeners heard it is the sort of
                # doubt that ruins a show.
                said += ", what you hear only"
            self.announce(said)
        else:
            self.mixer.set_bed_gain(self.mixer.bed_gain + step)
            self.board.bed_volume = self.mixer.bed_gain
            self.announce(f"Bed volume {percent(self.mixer.bed_gain)}")
        self._update_status()
        self._touch()

    def _on_toggle_duck(self, _event):
        self.mixer.ducking = not self.mixer.ducking
        self.board.ducking = self.mixer.ducking
        self.announce("Ducking on" if self.mixer.ducking else "Ducking off")
        self._update_status()
        self._touch()

    def _on_whats_playing(self, _event):
        # Playlist first: it is the bed the whole show sits on, and its deck
        # indices are not board slots, so they have to be named separately.
        parts = []
        track = self.player.current if self.player.playing else None
        if track is not None:
            # Where it is in the running order and how much of it is left.
            # Brian Hartgen: "We do not know how much time remains in the
            # song." It is the question a presenter asks most often, and the
            # player already knows the answer.
            remaining = format_duration(self.player.remaining)
            parts.append("Playlist, %d of %d, %s%s"
                         % (self.player.index + 1, len(self.board.playlist),
                            track.display_name,
                            ", %s left" % remaining if remaining else ""))
        indices = [i for i in self.mixer.playing_slots() if i < C.TOTAL_SLOTS]
        if indices:
            parts.append("%d playing. %s" % (
                len(indices),
                ", ".join(self.board[i].display_name for i in indices)))
        # announce_answer, not announce: this key exists only to be asked,
        # and at speech level "none" announce says nothing, which made Ctrl+L
        # a key that did nothing whatsoever.
        self.announce_answer(". ".join(parts) if parts else "Nothing is playing")

    # ------------------------------------------------------- slot editing ----
    def _focused_slot(self):
        """The slot a command applies to.

        A right-click does not move focus, so while a context menu is up the
        slot it was opened on wins over whatever happens to be focused.
        """
        if self._context_slot is not None:
            return self._context_slot
        window = wx.Window.FindFocus()
        return window.slot if isinstance(window, SoundButton) else None

    def _button_for(self, slot):
        page = self.pages[slot.bank]
        return page.buttons[slot.number - 1]

    def _sync_button(self, slot, playing=None):
        button = self._button_for(slot)
        if playing is None:
            playing = self.mixer.is_playing(slot.index)
        button.refresh(playing)

    # ------------------------------------------------ how many slots there are
    #
    # Twenty a bank is what the app ships with, not what everybody wants. Tony,
    # 4 September 2026: "if someone only wants 10 slots, they can have only 10
    # instead of 20. making it less cluster."
    #
    # Removing one hides it and NEVER renumbers the rest. That is the whole
    # design: the digit map is years of muscle memory, so taking slot 5 away
    # has to leave 6 on the 6 key. The slot keeps its sound, its name and both
    # its hotkeys, and putting it back brings all of that with it, which is
    # why nothing here asks whether you are sure.

    def remove_slot(self, slot=None):
        """Take one pad off the board. Nothing is lost and nothing moves."""
        if slot is None and _is_text_entry(wx.Window.FindFocus()):
            # Shift+Delete comes from the menu bar's own accelerator, which no
            # swapping of the frame's table can stand down, and it must not
            # reach past a box somebody is typing in.
            return False
        slot = slot or self._focused_slot()
        if slot is None:
            if self.views.GetSelection() == VIEW_PLAYLIST:
                self.announce("That one is for the soundboard. "
                              "Ctrl+Shift+S goes back to it")
            else:
                self.announce("Move to a sound button first")
            return False
        if slot.hidden:
            return False
        if len(self.board.visible_slots(slot.bank)) <= 1:
            self.announce("That is the last slot in this bank. A bank with "
                          "nothing in it would have nothing to come back to")
            return False
        # Move off it first: focus on a window about to be hidden goes
        # nowhere, and a screen reader is then standing on nothing.
        following = self._neighbour_of(slot)
        slot.hidden = True
        self.mixer.stop_slot(slot.index, fade_out=C.FADE_OUT_SFX)
        page = self.pages[slot.bank]
        page.refresh_visibility()
        if following is not None:
            following.SetFocus()
        self.announce_help(
            "%s %d removed. %d slot%s left in %s"
            % (slot.bank_short, slot.number,
               len(self.board.visible_slots(slot.bank)),
               "" if len(self.board.visible_slots(slot.bank)) == 1 else "s",
               self.board.bank_name(slot.bank)))
        self._touch()
        return True

    def _neighbour_of(self, slot):
        """The button to land on once ``slot`` goes. The next one, or the one
        before it if it was the last."""
        page = self.pages[slot.bank]
        others = [button for button in page.buttons
                  if not button.slot.hidden and button.slot is not slot]
        if not others:
            return None
        after = [b for b in others if b.slot.number > slot.number]
        return after[0] if after else others[-1]

    def restore_slot(self, bank=None):
        """Put one back, chosen from the ones taken off this bank."""
        bank = bank or self._current_bank()
        gone = self.board.hidden_slots(bank)
        if not gone:
            self.announce("No slots have been removed from %s"
                          % self.board.bank_name(bank))
            return False
        labels = ["%d. %s" % (slot.number, slot.display_name) for slot in gone]
        with wx.SingleChoiceDialog(
                self, "Which slot would you like back?\n\n"
                "It comes back where it was, with whatever was on it.",
                "Put a slot back", labels) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Nothing changed")
                return False
            slot = gone[dialog.GetSelection()]
        return self._restore(slot)

    def _restore(self, slot):
        slot.hidden = False
        page = self.pages[slot.bank]
        page.refresh_visibility()
        self._sync_button(slot)
        self._button_for(slot).SetFocus()
        self.announce_help("%s %d is back" % (slot.bank_short, slot.number))
        self._touch()
        return True

    def restore_all_slots(self, bank=None):
        """Put every removed slot in this bank back."""
        bank = bank or self._current_bank()
        gone = self.board.hidden_slots(bank)
        if not gone:
            self.announce("Every slot in %s is already on the board"
                          % self.board.bank_name(bank))
            return 0
        for slot in gone:
            slot.hidden = False
        self.pages[bank].refresh_visibility()
        for slot in gone:
            self._sync_button(slot)
        self.announce_help("%d slot%s back in %s"
                           % (len(gone), "" if len(gone) == 1 else "s",
                              self.board.bank_name(bank)))
        self._touch()
        return len(gone)

    def _focused_action(self, action):
        # Not while somebody is typing. Delete and F2 reach here from the menu
        # bar's own accelerators, which no swapping of the frame's table can
        # stand down, and Delete inside the crossfade box meant "remove the
        # track I am not even looking at".
        if _is_text_entry(wx.Window.FindFocus()):
            return
        # Delete means "remove this item" in the playlist and "clear this pad"
        # on the board. One key, the thing in front of you.
        if (self.views.GetSelection() == VIEW_PLAYLIST
                and self._view_focused(VIEW_PLAYLIST)):
            if action == "clear":
                self.playlist_panel.remove_selected()
                return
            self.announce("That one is for the soundboard. "
                          "Ctrl+Shift+S goes back to it")
            return
        slot = self._focused_slot()
        if slot is None:
            self.announce("Move to a sound button first")
            return
        {"assign": self.assign_sound, "rename": self.rename_slot,
         "trim": self.trim_slot, "hotkey": self.assign_hotkey,
         "loop": self.toggle_loop, "clear": self.clear_slot,
         "folder": self.assign_folder,
         "properties": self.slot_properties}[action](slot)

    def assign_sound(self, slot):
        path = audio_file_dialog(
            self, self.board.last_sound_dir,
            f"Choose a sound for {slot.bank_short} {slot.number}", frame=self)
        if not path:
            self.announce_help("Nothing chosen")
            return
        self._apply_file(slot, path)

    def assign_folder(self, slot):
        """Point a slot at a folder, so every press plays a different sound.

        Brian Hartgen's chart-countdown case: half a dozen "down the chart"
        jingles, one keystroke, and you do not care which one you get.
        """
        start = slot.filepath if slot.is_folder else self.board.last_sound_dir
        with wx.DirDialog(self, "Choose a folder of sounds for "
                          f"{self.board.bank_short_name(slot.bank)} {slot.number}",
                          defaultPath=start or "",
                          style=wx.DD_DIR_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Nothing chosen")
                return
            path = dialog.GetPath()
        self._apply_folder(slot, path)

    def _apply_folder(self, slot, path):
        # Counted here, in a dialog, rather than on the trigger path. An empty
        # folder is refused now instead of being a key that does nothing later.
        probe_slot = Slot(index=slot.index, filepath=path)
        count = probe_slot.scan_folder(force=True)
        if not count:
            wx.MessageBox(
                "There are no sounds in that folder.\n\n%s\n\n"
                "It needs at least one %s file." % (
                    path, C.AUDIO_FORMATS_SPOKEN),
                "Nothing to play", wx.OK | wx.ICON_ERROR, self)
            self.announce("That folder has no sounds in it")
            return
        was_folder = slot.is_folder
        slot.filepath = path
        slot.duration = None
        slot.folder_count = count
        slot.scan_folder(force=True)
        if not slot.name or (not was_folder and slot.name == slot.display_name):
            slot.name = os.path.basename(path.rstrip("\\/")) or path
        self.board.last_sound_dir = os.path.dirname(path.rstrip("\\/")) or path
        self._sync_button(slot)
        self.announce_help(
            "%s assigned to %s %d. %d sounds, one at random each press" % (
                slot.display_name, self.board.bank_short_name(slot.bank),
                slot.number, count))
        self._touch()
        self.warm_cache()

    def _folders_counted(self, folders):
        """The warmer has been round the folder slots; relabel what it changed."""
        for slot in folders:
            try:
                self._sync_button(slot)
            except Exception:
                pass

    def _apply_file(self, slot, path):
        try:
            duration = probe(path)[0]
        except Exception as exc:
            wx.MessageBox(f"That file could not be read.\n\n{exc}",
                          "Cannot use this file", wx.OK | wx.ICON_ERROR, self)
            self.announce("That file could not be read")
            return
        slot.filepath = path
        slot.duration = duration
        if not slot.name:
            slot.name = os.path.splitext(os.path.basename(path))[0]
        self.board.last_sound_dir = os.path.dirname(path)
        self._sync_button(slot)
        self.announce_help(f"{slot.display_name} assigned to "
                           f"{slot.bank_short} {slot.number}")
        self._touch()

    def rename_slot(self, slot):
        if not slot.is_assigned:
            self.announce("That slot is empty")
            return
        with ask_text(self, "Name for this sound",
                      "Rename", slot.display_name) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.GetValue().strip()
            if not name:
                return
            # Inside the dialog, for the same reason as the bank rename: the
            # pad has to carry its new label before focus lands back on it.
            slot.name = name
            self._sync_button(slot)
        self.announce_help(f"Renamed to {name}")
        self._touch()

    def trim_slot(self, slot):
        if not slot.is_assigned:
            self.announce("That slot is empty")
            return
        with TrimDialog(self, slot) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            slot.trim_db = dialog.trim_db
        self._sync_button(slot)
        self.announce_help(f"{slot.display_name} level {slot.trim_db:+.0f} decibels")
        self._touch()

    def slot_properties(self, slot):
        """Name, level, looping and both hotkeys, in one dialog.

        Every one of these has its own menu item too. This exists because
        answering "what is this pad actually set to" meant opening four
        dialogs in turn, and because Alt+Enter is where a Windows user looks.

        The dialog writes nothing. Everything is applied here, which is what
        makes its Cancel button mean what it says.
        """
        taken = self._hotkey_map(exclude=slot.index)
        with SlotPropertiesDialog(self, slot, taken) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Properties closed, nothing changed")
                return
            chosen = dialog.result
            remove_wanted = dialog.remove_wanted
        if remove_wanted:
            # Everything else on the dialog is moot: the pad is coming off.
            self.remove_slot(slot)
            return

        changes = []
        name = chosen["name"]
        if name and name != slot.display_name:
            slot.name = name
            changes.append("named %s" % name)
        if chosen["trim_db"] != slot.trim_db:
            slot.trim_db = chosen["trim_db"]
            changes.append("level %+.0f decibels" % slot.trim_db)
        if chosen["loop"] is not None and chosen["loop"] != slot.loop:
            slot.loop = chosen["loop"]
            changes.append("loop %s" % ("on" if slot.loop else "off"))
        if (chosen["toggle_stop"] is not None
                and chosen["toggle_stop"] != slot.toggle_stop):
            slot.toggle_stop = chosen["toggle_stop"]
            changes.append("pressing again %s"
                           % ("stops it" if slot.toggle_stop
                              else "plays it again"))

        # Only bank four has a hotkey of its own. The other three are fixed by
        # the bank and the dialog does not offer to change them.
        if (slot.bank == C.BANK_MISC
                and chosen["custom_hotkey"] != slot.custom_hotkey):
            slot.key_code = chosen["key_code"]
            slot.modifiers = chosen["modifiers"]
            slot.custom_hotkey = chosen["custom_hotkey"]
            self._build_accelerators()
            changes.append("hotkey %s" % (slot.custom_hotkey or "cleared"))

        if chosen["global_hotkey"] != slot.global_hotkey:
            text = chosen["global_hotkey"]
            if text and globalhotkeys.parse(text) is None:
                self._on_hotkey_problem(globalhotkeys.describe(text))
            else:
                slot.global_hotkey = text
                self._sync_global_hotkeys()
                changes.append("global hotkey %s" % (text or "cleared"))

        if not changes:
            self.announce_help("Nothing changed")
            return
        self._sync_button(slot)
        self.announce_help("%s. %s" % (slot.display_name, ", ".join(changes)))
        self._touch()

    def toggle_loop(self, slot):
        if not slot.is_bed:
            self.announce("Looping is for the music beds in bank three")
            return
        slot.loop = not slot.loop
        self._sync_button(slot)
        self.announce_help(f"Loop {'on' if slot.loop else 'off'} "
                           f"for {slot.display_name}")
        self._touch()

    def clear_slot(self, slot):
        if not slot.is_assigned:
            self.announce("That slot is already empty")
            return
        name = slot.display_name
        what = "folder" if slot.is_folder else "sound"
        if wx.MessageBox(f"Clear this {what}, {name}, "
                         f"from {slot.bank_short} {slot.number}?",
                         "Clear slot", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self.mixer.stop_slot(slot.index, fade_out=0.05)
        slot.clear()
        self._sync_button(slot, playing=False)
        self.announce_help(f"{name} cleared")
        self._touch()

    def assign_hotkey(self, slot):
        if slot.bank != C.BANK_MISC:
            self.announce(f"{slot.bank_title} already has fixed hotkeys. "
                          "Custom hotkeys are for bank four")
            return
        taken = self._hotkey_map(exclude=slot.index)
        with AssignHotkeyDialog(self, slot, taken) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            key_code, modifiers, label = dialog.result
        slot.key_code = key_code
        slot.modifiers = modifiers
        slot.custom_hotkey = label
        self._build_accelerators()
        self._sync_button(slot)
        self.announce_help(f"Hotkey {label or 'cleared'} for {slot.display_name}")
        self._touch()


    # =====================================================================
    # The playlist
    #
    # The soundboard fires what you choose. The playlist runs itself: each
    # song cues the next before it ends, and the overlap is the crossfade.
    # PlaylistPlayer does the arithmetic and owns the two decks; everything
    # here is the app end of it - saying what happened, and keeping the list
    # and the timer honest.
    # =====================================================================

    def _start_player(self):
        self.player = PlaylistPlayer(self.mixer, self.board.playlist,
                                     on_change=self._playlist_moved,
                                     on_warning=self._playlist_warning)
        self._sync_warning()
        # Only runs while something is playing. A fiftieth of a second is
        # inaudible on a crossfade; the 250 ms pad timer would have put a
        # handover a quarter of a second out.
        self._player_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_player_tick, self._player_timer)

    def _on_player_tick(self, _event):
        # The title is pushed from here rather than from a track change hook,
        # because set_title only sends when it differs. Saying it every tick
        # costs nothing and cannot miss a change.
        self._push_stream_title()
        self._keep_beds_off_the_playlist()
        try:
            self.player.tick()
        except Exception as exc:              # pragma: no cover
            self.status.SetStatusText("Playlist stopped: %s" % exc, 1)
            self._player_timer.Stop()
        if not self.player.playing:
            self._player_timer.Stop()

    def _sync_warning(self):
        """Push the end of track cue setting onto the player."""
        player = getattr(self, "player", None)
        if player is None:
            return
        player.warn_seconds = (float(self.board.warn_seconds)
                               if self.board.warn_before_end else 0.0)

    def _playlist_warning(self):
        """A track is nearly over. Pip, and put it in the status bar.

        Out of the monitor output, which is the presenter's headphones when
        one is set and the ordinary output when it is not. It is a cue for the
        person running the show, so it has no business on the stream.

        Not spoken. The whole point of a pip is that it lands in a gap between
        words without taking one, which a sentence read out over the song
        would not.
        """
        if not self.board.warn_before_end:
            return
        try:
            self.mixer.play_cue(self.board.cue_sound, self.board.cue_level_db)
        except Exception as exc:                  # pragma: no cover
            self.note("The end of track cue would not play: %s" % exc)
            return
        track = self.player.current
        self.note("%d seconds left%s"
                  % (int(round(self.board.warn_seconds)),
                     " of %s" % track.display_name if track else ""))

    def _playlist_moved(self):
        """The player changed item. Say what is on, do NOT rewrite the rows.

        The rows carry the running order and never the word "playing", so a
        song change cannot restart a screen reader on the row the user is
        standing on. What went to air is spoken instead, which is the thing
        somebody actually wants told to them.
        """
        track = self.player.current
        if self.player.playing and track is not None:
            length = format_duration(track.duration)
            self.announce_playback(
                "%s%s" % (track.display_name, ", " + length if length else ""))
            # The one place that knows a handover happened, so the one place
            # the track lists are written from. Tyler McClain's request.
            self.note_track_on_air(track)
        self._update_title()
        self._update_status()

    def _update_title(self):
        """Put what is on air in the window title.

        Brian Hartgen: "There is no way of telling from the window title or by
        pressing a key to focus upon the song that is playing." A title is not
        focused, so writing it interrupts nothing, and it is what a screen
        reader reads when you come back to the window from somewhere else.
        """
        track = self.player.current if self.player.playing else None
        if track is None:
            self.SetTitle(self._base_title)
            return
        self.SetTitle("%s - %s" % (track.display_name, self._base_title))

    def show_view(self, view=None):
        """Swap between the soundboard and the playlist.

        Announced and focused explicitly. A Simplebook has no tab strip for a
        screen reader to read, which is the price of not nesting two of them -
        so the app says where you are and puts focus somewhere useful.
        """
        current = self.views.GetSelection()
        if view is None:
            view = VIEW_PLAYLIST if current == VIEW_BOARD else VIEW_BOARD
        if view == current and self._view_focused(view):
            # Already here. Say so rather than appearing to do nothing.
            self.announce_help(self._view_summary(view))
            return
        self.views.SetSelection(view)
        if view == VIEW_PLAYLIST:
            self.playlist_panel.focus_list()
        else:
            # The first slot of the bank may have been taken off the board,
            # and focus on a hidden window goes nowhere at all.
            button = self.pages[self._current_bank()].first_visible()
            if button is not None:
                button.SetFocus()
        self.announce(self._view_summary(view))

    def show_view_playlist(self):
        """Bring the playlist up without announcing anything.

        show_view says where you are, which is right when you asked to move
        and wrong when moving is only half of what you asked for.
        """
        if self.views.GetSelection() != VIEW_PLAYLIST:
            self.views.SetSelection(VIEW_PLAYLIST)

    def _view_focused(self, view):
        window = wx.Window.FindFocus()
        if window is None:
            return False
        page = self.views.GetPage(view)
        while window is not None:
            if window is page:
                return True
            window = window.GetParent()
        return False

    def _view_summary(self, view):
        if view == VIEW_PLAYLIST:
            return "Playlist. " + self.playlist_panel.describe()
        return "Soundboard. %s, %d sounds" % (
            self.board.bank_name(self._current_bank()),
            sum(1 for s in self.board.bank_slots(self._current_bank())
                if s.is_assigned))

    def playlist_changed(self, relabel=True):
        """The running order was edited: relabel, and save shortly.

        ``relabel`` is False when the panel has already brought itself up to
        date - ticking a box is the case, and rebuilding the rows underneath a
        screen reader that has just said "checked" would read the row again on
        top of it.
        """
        if relabel:
            self.playlist_panel.refresh()
        # Tags and run outs for anything new. Returns straight away when
        # there is nothing to look at, which is every call but the first
        # after files go in.
        self.scan_playlist_metadata()
        self._touch()

    # ------------------------------------------------------------ editing --
    def _on_playlist_paste(self, _event=None):
        """Ctrl+V from anywhere, because that is where people press it.

        Copy in Explorer, come back to the app, paste. Making that work only
        while the playlist already had focus would mean learning two keys to
        do one thing.
        """
        self.views.SetSelection(VIEW_PLAYLIST)
        added = self.playlist_panel.paste()
        self.playlist_panel.focus_list()
        return added

    def add_playlist_files(self):
        with wx.FileDialog(self, "Add songs to the running order",
                           defaultDir=self.board.last_sound_dir or "",
                           wildcard=C.AUDIO_WILDCARD,
                           style=wx.FD_OPEN | wx.FD_MULTIPLE
                           | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Nothing chosen")
                return []
            paths = dialog.GetPaths()
        if paths:
            self.board.last_sound_dir = os.path.dirname(paths[0])
        self.views.SetSelection(VIEW_PLAYLIST)
        added = self.playlist_panel.add_paths(paths)
        self.playlist_panel.focus_list()
        return added

    def _choose_drop(self, title):
        """A file for a drop. Returns a path, or None."""
        return audio_file_dialog(self, self.board.last_sound_dir, title,
                                 frame=self)

    def insert_playlist_drop(self):
        """One drop, in front of whatever the list is sitting on."""
        path = self._choose_drop("Choose a drop to put in the running order")
        if not path:
            self.announce_help("Nothing chosen")
            return None
        at = self.playlist_panel.selection()
        track = self.board.playlist.insert_drop(path, at=at)
        if track is None:
            self.announce("That file could not be read")
            return None
        self.board.last_sound_dir = os.path.dirname(path)
        if self.player.index >= (at if at is not None else len(self.board.playlist)):
            self.player.index += 1
        self.views.SetSelection(VIEW_PLAYLIST)
        self.playlist_panel.refresh(keep=at if at is not None
                                    else len(self.board.playlist) - 1)
        self.playlist_panel.focus_list()
        self.announce_help("%s put in at %d" % (
            track.display_name,
            (at if at is not None else len(self.board.playlist) - 1) + 1))
        self.playlist_changed()
        return track

    def insert_random_drop(self, _event=None):
        """Alt+D. A drop from the library, wherever you are in the order.

        The point of the library: building a show means reaching for an ident
        every few songs, and going and finding the file every single time is
        the part that wears thin. Never the same one twice running, for the
        same reason a folder slot does not repeat itself.
        """
        library = self.board.drops
        if not len(library):
            self.announce(
                "Your drops library is empty. Playlist menu, Drops library, "
                "puts some in - then Alt+D reaches for them")
            return None
        path = library.pick()
        if path is None:
            self.announce("Every drop in the library is missing. "
                          "Use File, relink missing sounds")
            return None
        at = self.playlist_panel.selection()
        track = self.board.playlist.insert_drop(path, at=at)
        if track is None:
            self.announce("That drop could not be read")
            return None
        landed = at if at is not None else len(self.board.playlist) - 1
        if self.player.index >= landed:
            self.player.index += 1
        self.show_view(VIEW_PLAYLIST)
        self.playlist_panel.refresh(keep=landed)
        self.playlist_panel.focus_list()
        self.announce_help("%s put in at %d" % (track.display_name, landed + 1))
        self.playlist_changed(relabel=False)
        return track

    def add_selected_to_library(self):
        """Put the drop you are on into the library, so Alt+D can find it."""
        index = self.playlist_panel.selection()
        if index is None:
            self.announce("There is nothing in the running order yet")
            return
        track = self.board.playlist[index]
        added = self.board.drops.add([track.filepath])
        if not added:
            self.announce("%s is already in your drops library"
                          % track.display_name)
            return
        self.announce_help(
            "%s added to your drops library, which now holds %d"
            % (track.display_name, len(self.board.drops)))
        self._touch()

    def _on_drops_library(self, _event=None):
        before = len(self.board.drops)
        with DropsLibraryDialog(self, self.board.drops) as dialog:
            dialog.ShowModal()
        count = len(self.board.drops)
        self.announce(
            "Drops library, %d drop%s. Alt+D puts one in at random"
            % (count, "" if count == 1 else "s") if count
            else "Drops library is empty")
        if count != before:
            self._touch()

    def _on_drop_every(self, _event=None):
        """The same drop after every so many songs, in one go."""
        if not len(self.board.playlist):
            self.announce("Put some songs in the running order first")
            return
        with wx.TextEntryDialog(
                self, "Put a drop in after every how many songs?\n\n"
                "Two means one drop between every second song. Drops already "
                "in the order are left where they are.",
                "A drop every so often", "2") as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Nothing changed")
                return
            try:
                every = int(dialog.GetValue().strip())
            except ValueError:
                self.announce("That is not a number")
                return
        if every < 1:
            self.announce("It has to be one song or more")
            return
        path = self._choose_drop("Choose the drop to put in every %d songs" % every)
        if not path:
            self.announce_help("Nothing chosen")
            return
        count = self.board.playlist.insert_drop_every(path, every)
        self.board.last_sound_dir = os.path.dirname(path)
        self.views.SetSelection(VIEW_PLAYLIST)
        self.playlist_panel.refresh(keep=0)
        self.playlist_panel.focus_list()
        if not count:
            self.announce("There was nowhere to put one")
            return
        self.announce_help("%d drop%s put in, one after every %d songs"
                           % (count, "" if count == 1 else "s", every))
        self.playlist_changed()

    def _on_crossfade(self, _event=None):
        """Take the user to the crossfade box rather than asking in a dialog.

        The control lives in the playlist view, beside the running order it
        applies to. One place for the value, and a menu item that says where
        it is - a second dialog asking for the same number would be a second
        place for it to be wrong.
        """
        self.show_view(VIEW_PLAYLIST)
        self.playlist_panel.focus_crossfade()
        self.announce(
            "Crossfade %s. Up and down arrows change it"
            % (format_duration(self.board.playlist.crossfade)
               or "off, each song plays right out"))

    def set_track_crossfade(self, index):
        """Give one track a crossfade of its own, or hand it back the default.

        Most tracks want the playlist's, which is why this can say "the same
        as the rest" rather than only a number - see TrackCrossfadeDialog.
        """
        playlist = self.board.playlist
        if not (0 <= index < len(playlist)):
            return
        track = playlist[index]
        with TrackCrossfadeDialog(self, track, playlist.crossfade) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Nothing changed")
                return
            chosen = dialog.result
        if chosen == track.crossfade:
            self.announce_help("Nothing changed")
            return
        track.crossfade = chosen
        self.playlist_panel.refresh(keep=index)
        self.playlist_panel.focus_list()
        if chosen is None:
            self.announce_help(
                "%s uses the playlist's crossfade, %s"
                % (track.display_name,
                   format_duration(playlist.crossfade) or "which is off"))
        else:
            self.announce_help(
                "%s crossfades %s into the next one"
                % (track.display_name,
                   format_duration(chosen) or "not at all"))
        self.playlist_changed(relabel=False)

    # --------------------------------------------------- running orders ----
    #
    # A board is the show's furniture and saves itself. A running order is the
    # show, and people want to keep those: last Tuesday's, the Christmas one,
    # the two hours that were ready before the guest cancelled. They go out as
    # M3U so the file is worth something outside this app as well as inside
    # it, and so a co-presenter can open one without installing anything.

    def _playlist_file_dialog(self, saving):
        """The Open or Save dialog for a running order. Returns a path or None."""
        style = (wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) if saving else (
            wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        default = ""
        if saving:
            # Dated, because the thing people save is "the show I have just
            # built", and the date is what tells two of them apart a month
            # later. Colons are not allowed in a file name, so no time.
            default = "Running order %s.m3u" % datetime.date.today().isoformat()
        with wx.FileDialog(
                self,
                "Save the running order" if saving else "Open a running order",
                defaultDir=self.board.last_playlist_dir or "",
                defaultFile=default, wildcard=m3u.WILDCARD,
                style=style) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Nothing saved" if saving
                                   else "Nothing opened")
                return None
            return dialog.GetPath()

    def save_playlist_file(self):
        """Write the running order out as an M3U."""
        if not len(self.board.playlist):
            self.announce("There is nothing in the running order to save")
            return False
        path = self._playlist_file_dialog(saving=True)
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += ".m3u"
        try:
            count = m3u.save(path, self.board.playlist)
        except OSError as exc:
            wx.MessageBox("That running order could not be saved.\n\n%s" % exc,
                          "Could not save", wx.OK | wx.ICON_ERROR, self)
            self.announce("Could not save the running order")
            return False
        self.board.last_playlist_dir = os.path.dirname(path)
        self._touch()
        self.announce("Saved %d %s to %s"
                      % (count, "item" if count == 1 else "items",
                         os.path.basename(path)))
        return True

    def open_playlist_file(self, path=None):
        """Load an M3U in place of the running order.

        Replaces rather than appends, the same way File, Open does with a
        board. Dragging or pasting a playlist file onto the list adds to the
        end instead, because that is what dragging things onto a list means.
        """
        existing = len(self.board.playlist)
        if existing and wx.MessageBox(
                "Replace the running order with the one in this file?\n\n"
                "The %d %s in it now will be taken out. Save it first if you "
                "want to keep it."
                % (existing, "item" if existing == 1 else "items"),
                "Open a running order", wx.YES_NO | wx.ICON_QUESTION,
                self) != wx.YES:
            self.announce_help("Nothing opened")
            return False
        if path is None:
            path = self._playlist_file_dialog(saving=False)
        if not path:
            return False
        entries, crossfade = self._read_playlist_file(path)
        if entries is None:
            return False
        self.stop_playlist(quiet=True)
        self.board.playlist.clear()
        self.player.index = -1
        added = self.board.playlist.add_entries(entries)
        if crossfade is not None:
            self.board.playlist.crossfade = crossfade
        self.board.last_playlist_dir = os.path.dirname(path)
        self.playlist_panel.refresh(keep=0)
        self.show_view(VIEW_PLAYLIST)
        self.playlist_panel.focus_list()
        self._say_opened(path, added)
        self.playlist_changed()
        return True

    def _read_playlist_file(self, path):
        """Parse one, and say so rather than failing quietly. (None, None) on
        anything that will not open."""
        try:
            return m3u.load(path)
        except OSError as exc:
            wx.MessageBox("That playlist could not be opened.\n\n%s" % exc,
                          "Could not open", wx.OK | wx.ICON_ERROR, self)
            self.announce("Could not open that playlist")
            return None, None

    def _say_opened(self, path, added):
        """What came in, and what did not. Missing files are the usual case
        with a playlist somebody else wrote, and relink is what fixes them."""
        if not added:
            self.announce(
                "Nothing in %s this app can play" % os.path.basename(path))
            return
        missing = sum(1 for t in added if t.is_missing)
        self.announce(
            "Opened %s. %d %s%s"
            % (os.path.basename(path), len(added),
               "item" if len(added) == 1 else "items",
               ". %d file%s missing, File then Relink missing sounds will look "
               "for them" % (missing, "" if missing == 1 else "s")
               if missing else ""))

    def _on_clear_playlist(self, _event=None):
        count = len(self.board.playlist)
        if not count:
            self.announce("The running order is already empty")
            return
        if wx.MessageBox("Take all %d items out of the running order?" % count,
                         "Clear the playlist",
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self.stop_playlist(quiet=True)
        self.board.playlist.clear()
        self.player.index = -1
        self.playlist_panel.refresh()
        self.announce_help("Running order cleared")
        self.playlist_changed()

    def _all_ticked(self, value):
        if not len(self.board.playlist):
            self.announce("There is nothing in the running order yet")
            return
        self.views.SetSelection(VIEW_PLAYLIST)
        self.playlist_panel.set_all_ticked(value)
        self.playlist_panel.focus_list()

    # ---------------------------------------------------------- transport --
    def _on_playlist_play(self, _event=None):
        self.play_playlist(self.playlist_panel.selection())

    def play_playlist(self, index=None):
        if not len(self.board.playlist):
            self.announce("There is nothing in the running order yet")
            return False
        asked = index
        if not self.player.play(index):
            self.announce("Could not start the playlist. %s"
                          % (self.player.last_error or ""))
            return False
        if asked is not None and self.player.index != asked:
            # It walked past something unticked or missing. Say so, or the
            # wrong song appears to have started for no reason.
            self.announce_help(
                "%s was skipped, starting at %s"
                % (self.board.playlist[asked].display_name,
                   self.player.current.display_name))
        self._player_timer.Start(C.PLAYLIST_TICK_MS)
        self._update_status()
        return True

    def stop_playlist(self, quiet=False):
        stopped = self.player.stop(fade_out=C.FADE_OUT_BED, quiet=True)
        self._player_timer.Stop()
        if not quiet:
            self.announce_playback("Playlist stopped" if stopped
                                   else "The playlist was not playing")
        self._update_title()
        self._update_status()
        return stopped

    # ====================================================================
    # Feedback, and the occasional word about donating
    # ====================================================================

    def _on_user_guide(self, _event=None):
        """The full manual, on the site. F1 is the keys; this is everything.

        On the web rather than in the app on purpose: it can be corrected the
        day somebody finds it confusing, without waiting for a release, and it
        is one page a screen reader can search.
        """
        if webbrowser.open(C.USER_GUIDE_URL):
            self.announce("Opening the user manual in your browser")
        else:
            self.announce("Could not open a browser. The manual is at %s"
                          % C.USER_GUIDE_URL)

    def _on_feedback(self, _event=None):
        """Say what happened, from inside the app, at the moment it happened.

        Queued to disk before it is sent, so a report survives no network, a
        server restart, or the app being closed on the way out of a venue.
        """
        with FeedbackDialog(self, self) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Feedback closed, nothing sent")
                return None
            kind, text = dialog.feedback_type, dialog.text
        if not text:
            self.announce("There was nothing written to send")
            return None
        delivered, queued = feedback.submit(kind, text, self)
        if delivered:
            message = ("Thank you. That has been sent."
                       if not queued else
                       "Thank you. That has been sent, and %d earlier one%s "
                       "went with it." % (queued, "" if queued == 1 else "s"))
        else:
            # NOT an error. It is on disk and it will go on its own.
            message = ("Thank you. That is saved and will be sent the next "
                       "time this machine is online. Nothing has been lost.")
        self.announce(message)
        wx.MessageBox(message, "Feedback", wx.OK | wx.ICON_INFORMATION, self)
        return delivered

    def _on_donate(self, _event=None):
        """Help, Donate. The same window the weekly one uses, on demand."""
        return self._show_donate(mark=False)

    def _show_donate(self, mark=True):
        with DonateDialog(self) as dialog:
            answer = dialog.ShowModal()
            never = dialog.never_again
        if never:
            feedback.mark_never(True)
        if answer == wx.ID_OK:
            feedback.mark_donated()
            if webbrowser.open(feedback.DONATE_URL):
                self.announce("Opening the donate page in your browser. "
                              "Thank you")
            else:
                self.announce("Could not open a browser. The page is %s"
                              % feedback.DONATE_URL)
            return True
        if mark:
            feedback.mark_asked()
        self.announce_help(
            "No problem. Help, Donate, is there if you change your mind"
            if not never else
            "Right you are, that will not come up again")
        return False

    def _maybe_ask_about_donating(self):
        """Once a week at the very most, and never in the first week.

        Deferred behind the startup announcement on purpose: the first thing
        the app says to somebody must be about their board, never about money.
        """
        try:
            if not feedback.should_ask_about_donating():
                return False
        except Exception:                       # pragma: no cover
            return False
        self._show_donate(mark=True)
        return True

    # ====================================================================
    # The microphone
    #
    # Opening it ducks the music. Not because the level went up - because it
    # is OPEN. A gate that opens on your voice clips the first syllable of
    # every sentence, and one that hangs open ducks the bed when you cough.
    # DuckBus already carried "something loud is happening" across sound
    # cards, so the microphone publishes onto it under a key of its own.
    # ====================================================================

    def _mic_open(self):
        mic = getattr(self, "mic", None)
        return bool(mic is not None and mic.is_open)

    def _mic_spec(self):
        return {"name": self.board.mic_device_name,
                "hostapi": self.board.mic_device_hostapi}

    def _resolve_monitor_device(self):
        """Which output a monitored microphone comes out of, as a live index."""
        return resolve_device({"name": self.board.mic_output_name,
                               "hostapi": self.board.mic_output_hostapi})

    def toggle_mic(self, _event=None):
        """Ctrl+M. Open or close the microphone, and say which it now is.

        Announced on the essential channel, never the confirmation one. "Am I
        live" is not a pleasantry, and somebody who has turned the app's
        chattiness down has not asked to stop being told that.
        """
        if self._mic_open():
            self.mic.stop()
            self.mic_item.Check(False)
            self.announce("Microphone off. Music back up")
        else:
            if not self.mic.start(device=resolve_input(self._mic_spec())):
                self.mic_item.Check(False)
                self.announce("The microphone would not open. %s"
                              % (self.mic.last_error or ""))
                self._update_status()
                return False
            self.mic_item.Check(True)
            self.announce("Microphone on, %s. Music ducked"
                          % describe_input(self.mic.device))
        self._update_status()
        return self._mic_open()

    def _on_mic_settings(self, _event=None):
        """Ctrl+Shift+M. The same window as Ctrl+P, opened on its tab.

        There were two settings dialogs on two keys, which meant two places to
        look for one thing. One window with tabs is simpler to describe and
        simpler to find your way round.
        """
        self._on_settings(page=SettingsDialog.PAGE_MIC)

    def _apply_mic_settings(self, dialog):
        """Move what the Microphone tab says onto the board and the mic."""
        index, name, hostapi = dialog.chosen_mic_device
        out_index, out_name, out_hostapi = dialog.chosen_monitor_output
        gain_db = dialog.mic_gain_db
        monitoring = dialog.mic_monitoring

        changed_input = ((name, hostapi) != (self.board.mic_device_name,
                                             self.board.mic_device_hostapi))
        changed_output = ((out_name, out_hostapi)
                          != (self.board.mic_output_name,
                              self.board.mic_output_hostapi))
        self.board.mic_device_name = name
        self.board.mic_device_hostapi = hostapi
        self.board.mic_output_name = out_name
        self.board.mic_output_hostapi = out_hostapi
        self.board.mic_gain_db = gain_db
        self.board.mic_monitor = monitoring
        self.mic.gain_db = gain_db
        channel = ["mix", "left", "right"][
            max(0, dialog.mic_channel.GetSelection())]
        if channel != self.mic.channel:
            self.board.mic_channel = channel
            self.mic.channel = channel
        self.mic.monitor = monitoring
        self.mic.device = index

        if changed_output:
            # Moving the monitor to another card rebuilds the group, which
            # stops everything and empties the decode caches - so warm them.
            self.mixer.set_monitor_device(out_index)
            self.mixer.monitor_source = getattr(self, "source_group", self.mic)
            self.warm_cache()
        if changed_input and self._mic_open():
            self.mic.start(device=index)

        return ("Microphone %s, gain %+.0f decibels, monitoring %s%s"
                % (describe_input(index), gain_db,
                   "on" if monitoring else "off",
                   ", through " + describe_device(out_index)
                   if monitoring else ""))

    def segue_playlist(self, index):
        """Bring one track up and take what is on air down under it.

        The manual version of what a cue point does on its own: the same
        crossfade length, at the moment you ask for it rather than at the end
        of the song. This is how you get out of a track early.
        """
        if not len(self.board.playlist):
            self.announce("There is nothing in the running order yet")
            return False
        if not self.player.playing:
            # Nothing to fade out of, so this is simply a start.
            return self.play_playlist(index)
        if not self.board.playlist.will_play(index):
            self.announce("%s is unticked, so it will not play. "
                          "Press Space to tick it"
                          % self.board.playlist[index].display_name)
            return False
        going = self.player.current
        if not self.player.segue_to(index):
            self.announce("Could not play that one. %s"
                          % (self.player.last_error or ""))
            return False
        self._player_timer.Start(C.PLAYLIST_TICK_MS)
        self.announce_playback(
            "Segue to %s%s" % (self.player.current.display_name,
                               ", out of %s" % going.display_name if going else ""))
        return True

    def playlist_next(self):
        if not self.player.playing:
            self.announce("The playlist is not playing")
            return False
        if not self.player.next():
            self.announce_playback("That was the last one")
            self._player_timer.Stop()
            return False
        return True

    def playlist_previous(self):
        if not self.player.playing:
            self.announce("The playlist is not playing")
            return False
        if not self.player.previous():
            self.announce("That is the first one")
            return False
        return True

    # ----------------------------------------------------------- banks ----
    def _current_bank(self):
        """The bank the user is looking at, which is the one a command means."""
        return self.notebook.GetSelection() + 1

    def _on_rename_bank(self, _event=None):
        bank = self._current_bank()
        if not 1 <= bank <= C.BANK_COUNT:
            return
        current = self.board.bank_name(bank)
        with ask_text(
                self,
                "Name for bank %d.\n\n"
                "This changes what the tab is called and nothing else - the "
                "keys, the looping and the hotkeys all stay exactly as they "
                "are. Leave it empty to go back to %s."
                % (bank, C.BANK_TITLES[bank]),
                "Rename bank", current) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Nothing changed")
                return
            name = dialog.GetValue().strip()[:C.MAX_BANK_NAME]
            # Applied while the dialog is still alive, so the tab already
            # carries the new name by the time focus goes back to it. Doing it
            # after the dialog was destroyed meant a screen reader read the
            # OLD tab on the way out - Brian Hartgen, on 2.4.0, and the same
            # stale-name bug 2.3.0 fixed for the pads, in a new place.
            self._set_bank_name(bank, name)

    def _on_reset_bank_name(self, _event=None):
        bank = self._current_bank()
        if not 1 <= bank <= C.BANK_COUNT:
            return
        if not self.board.is_bank_renamed(bank):
            self.announce("Bank %d is already called %s" % (bank, C.BANK_TITLES[bank]))
            return
        self._set_bank_name(bank, "")

    def _set_bank_name(self, bank, name):
        """Apply a bank name and say what did and did not change.

        Renaming bank three does not stop it being the looping bank, and
        renaming bank four does not stop it taking custom hotkeys. Those are
        what the keys do, not what the tab says - so the confirmation says so
        rather than leaving somebody to find out.
        """
        applied = self.board.rename_bank(bank, name)
        self._refresh_tab_titles()
        # The pads name their bank in the search list, and the tab title is a
        # different control from the pages, so both have to be brought up to
        # date - the same "an edit must land at once" rule as a slot label.
        for slot in self.board.bank_slots(bank):
            self._sync_button(slot)
        note = ""
        if bank == C.LOOPING_BANK:
            note = ". Still the looping bank"
        elif bank == C.BANK_MISC:
            note = ". Still the bank that takes your own hotkeys"
        # announce, not announce_help. A tab a screen reader may have read out
        # with its old name has to be corrected at every speech level bar
        # silence; a confirmation you can switch off is not good enough here.
        self.announce("Bank %d is now %s%s" % (bank, applied, note))
        self._touch()

    def _hotkey_map(self, exclude=None):
        """Every key already spoken for, so the dialog can warn about clashes."""
        taken = {}
        for modifiers, key_code, index in fixed_accelerators():
            slot = self.board[index]
            taken[(key_code, modifiers)] = f"{slot.bank_short} {slot.number}"
        for slot in self.board.bank_slots(C.BANK_MISC):
            if slot.key_code and slot.index != exclude:
                taken[(slot.key_code, slot.modifiers or 0)] = slot.display_name
        return taken

    def show_slot_menu(self, slot, button, position=None):
        menu = wx.Menu()
        playing = self.mixer.is_playing(slot.index)

        if slot.is_assigned:
            menu.Append(ID_SLOT_BASE + slot.index,
                        "Stop this &bed" if (slot.is_bed and playing) else "&Play")
        menu.Append(ID_ASSIGN, "Re&assign sound file..." if slot.is_assigned
                    else "&Assign sound file...")
        menu.Append(ID_ASSIGN_FOLDER,
                    "Assign a &folder... (now %d sounds)" % (slot.folder_count or 0)
                    if slot.is_folder else "Assign a &folder...")
        if slot.is_assigned:
            menu.Append(ID_RENAME, "Re&name...\tF2")
            menu.Append(ID_TRIM, f"&Level... (now {slot.trim_db:+.0f} decibels)")
        if slot.is_bed:
            item = menu.AppendCheckItem(ID_LOOP, "&Loop this bed")
            item.Check(bool(slot.loop))
        if slot.bank == C.BANK_MISC:
            menu.Append(ID_HOTKEY,
                        f"&Hotkey... (now {slot.custom_hotkey or 'none'})")
        if slot.is_assigned:
            # The global hotkey lived only in the Sounds menu, which meant the
            # menu people actually open did not offer the feature at all. It
            # reads out its current value, like the two items above it.
            menu.Append(ID_GLOBAL_HOTKEY,
                        f"&Global hotkey... (now {slot.global_hotkey or 'none'})")
            menu.AppendSeparator()
            menu.Append(ID_PROPERTIES, "P&roperties...\tAlt+Enter")
            menu.Append(ID_CLEAR_FOCUSED, "&Clear slot")
        menu.AppendSeparator()
        menu.Append(ID_REMOVE_SLOT,
                    "Re&move this slot from the board	Shift+Del")
        if self.board.hidden_slots(slot.bank):
            menu.Append(ID_RESTORE_SLOT, "Put a remo&ved slot back...")

        self._context_slot = slot
        try:
            # A position, so the Applications key opens the menu on the pad it
            # belongs to. With none, wx falls back to the mouse pointer, which
            # for a keyboard user is wherever it was last left.
            button.PopupMenu(menu, position or wx.DefaultPosition)
        finally:
            self._context_slot = None
        menu.Destroy()

    # ---------------------------------------------------------------- files --
    def _touch(self):
        """Something changed. Save shortly, so a crash cannot cost the board."""
        self.board.dirty = True
        self._save_timer.Start(2000, oneShot=True)

    def _save(self, quiet=False, path=None):
        try:
            saved = self.board.save(path)
        except Exception as exc:
            wx.MessageBox(f"The board could not be saved.\n\n{exc}",
                          "Save failed", wx.OK | wx.ICON_ERROR, self)
            return
        if not quiet:
            self.announce_help(f"Saved to {os.path.basename(saved)}")

    def _on_save_as(self, _event):
        with wx.FileDialog(self, "Save board as", wildcard="Boards (*.json)|*.json",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self._save(path=dialog.GetPath())

    def _on_new(self, _event):
        if self.board.assigned_count and wx.MessageBox(
                f"Clear all {self.board.assigned_count} sounds and start over?\n\n"
                "Save the current board first if you want to keep it.",
                "New board", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self.mixer.stop_all(fade_out=0.05)
        fresh = Board()
        fresh.path = self.board.path
        fresh.device_name = self.board.device_name
        fresh.device_hostapi = self.board.device_hostapi
        self._adopt(fresh)
        self.announce_help("New board, eighty empty slots")
        self._touch()

    def _on_load_demo(self, _event):
        demo = demo_board_path()
        if not os.path.exists(demo):
            wx.MessageBox("The demo pack is not installed alongside the app.",
                          "No demo pack", wx.OK | wx.ICON_INFORMATION, self)
            return
        if self.board.assigned_count and wx.MessageBox(
                "Replace the current board with the demo pack?\n\n"
                "Save the current board first if you want to keep it.",
                "Load demo pack", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        keep = self.board.path
        self._load_into(demo, keep_path=False)
        self.board.path = keep
        self._touch()

    def _on_open(self, _event):
        with wx.FileDialog(self, "Open board", wildcard="Boards (*.json)|*.json",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        self._load_into(path)

    def _on_import(self, _event):
        with wx.FileDialog(self, "Import an old soundboard bank",
                           wildcard="Soundboard banks (*.json)|*.json",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        kind = Board.describe_source(path)
        if kind is None:
            wx.MessageBox("That file is not a soundboard bank.", "Cannot import",
                          wx.OK | wx.ICON_ERROR, self)
            return
        self._load_into(path, keep_path=False)

    def _adopt(self, board):
        """Make ``board`` the live one: rewire every button and every hotkey."""
        self.board = board
        self.mixer.set_sfx_gain(board.sfx_volume)
        self.mixer.set_bed_gain(board.bed_volume)
        self.mixer.ducking = board.ducking
        self.mixer.duck_db = board.duck_db
        self.mixer.set_playlist_gain(board.playlist_volume)
        self.mixer.playlist_monitor_only = board.playlist_monitor_only
        self.mixer.bed_fade_in = board.bed_fade_in
        self.mixer.bed_fade_out = board.bed_fade_out
        self._sync_warning()
        self.stop_playlist(quiet=True)
        self.player.playlist = board.playlist
        self.player.index = -1
        for bank in range(1, C.BANK_COUNT + 1):
            for button, slot in zip(self.pages[bank].buttons,
                                    board.bank_slots(bank)):
                button.set_slot(slot)
        self._apply_board_voice(board)
        self._playing = set()
        self._build_accelerators()
        if getattr(self, "playlist_panel", None) is not None:
            self.playlist_panel.refresh(keep=0)
        self._update_status()

    # ------------------------------------------------------------- sources --
    def source_rows(self):
        """Everything the source control list shows, microphone first.

        The microphone is in it because solo has to mean something: soloing a
        games call has to take your voice down too, or it is not a solo.
        """
        rows = [("mic", "Microphone", self.mic)]
        for at, source in enumerate(getattr(self, "sources", []), start=1):
            rows.append(("source", "Source %d, %s" % (at, source.name), source))
        return rows

    def anything_soloed(self):
        return any(holder.soloed for _kind, _label, holder in self.source_rows()
                   if holder is not None)

    def apply_source_mixing(self):
        """Push mute and solo onto the inputs. Called after either changes.

        Nothing here touches what a source is SET to, only what it is doing
        at this moment, so unmuting puts back exactly what was there before.
        """
        soloed = self.anything_soloed()
        mic = getattr(self, "mic", None)
        if mic is not None:
            # A SEND counts, and it used not to. Every Mute and every Solo
            # in Source Control comes through here, and this asked only
            # whether something was live or recording, so pressing Space on
            # any source's Mute during a TeamTalk call took the presenter's
            # voice off the send and unmuting did not put it back. Found by
            # Mark, 10 September 2026, reproduced every time.
            wants = bool(self.board.stream_mic) and self.going_anywhere()
            if mic.muted or (soloed and not mic.soloed):
                mic.on_air = False
            else:
                mic.on_air = wants
            mic.monitor = (bool(self.board.mic_monitor)
                           and not mic.muted
                           and (mic.soloed or not soloed))
        for source in getattr(self, "sources", []):
            source.input.on_air = source.wants_air(soloed)
            source.input.monitor = source.wants_monitor(soloed)
        self._update_status()

    def streaming_or_recording(self):
        return bool(getattr(self, "air_bus", None)
                    or getattr(self, "record_bus", None)
                    or getattr(self, "video_bus", None))

    def recording_video(self):
        """Is the picture being taped as well as the sound."""
        rec = getattr(self, "video_recorder", None)
        return rec is not None and rec.running

    def going_anywhere(self):
        """Is the on air mix wanted by ANYBODY: a stream, a recording, a send.

        The question every mute, solo and source change has to ask. Asking
        the narrower one took the microphone off a send that nothing else
        was reading.
        """
        return (self.streaming_or_recording() or self.sending()
                or self.recording_video())

    def start_sources(self):
        """Open every source that is wanted, and say what would not open.

        Said once, quietly, and only about the ones that failed. A source that
        is not plugged in is an ordinary thing on a laptop that moves between
        desks, and it must not turn into a dialog in front of a show.
        """
        missing = []
        for source in getattr(self, "sources", []):
            if not source.start(self.mixer.samplerate):
                if source.wanted_on_air or source.wanted_monitor:
                    missing.append(source.name)
        if missing:
            self.announce_help("These sources would not open: %s"
                               % ", ".join(missing))
        self._sync_air_taps()
        self._update_status()
        return not missing

    def stop_sources(self):
        for source in getattr(self, "sources", []):
            try:
                source.close()
            except Exception:
                pass

    def apply_sources(self, entries):
        """Replace the list of sources with what the dialog came back with."""
        self.stop_sources()
        self.board.sources = [dict(entry) for entry in entries]
        self.sources = [sources.Source.from_dict(entry, self.mixer.samplerate)
                        for entry in self.board.sources]
        group = getattr(self, "source_group", None)
        if group is None:
            group = self.source_group = sources.SourceGroup(self.mic,
                                                            self.sources)
        else:
            group.sources = self.sources
        self.mixer.monitor_source = group
        self.start_sources()
        self._touch()

    def _on_source_control(self, _event=None):
        """The live one. Opens whether or not anything is set up, because
        the microphone is always in it."""
        with SourceControlDialog(self) as dialog:
            dialog.ShowModal()
        self._update_status()

    def _on_sources(self, _event=None):
        entries = [source.to_dict() for source in getattr(self, "sources", [])]
        with SourcesDialog(self, entries) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.announce_help("Nothing changed")
                return
            chosen = dialog.result
        self.apply_sources(chosen)
        self.announce_help("%d source%s" % (len(chosen),
                                            "" if len(chosen) == 1 else "s"))

    def _clean_update_staging(self):
        from . import appupdate
        try:
            appupdate.clean_staging()
        except Exception:
            pass

    def _apply_board_voice(self, board):
        """Move a newly opened board's microphone settings onto the live one.

        Without this, opening a board left the microphone and the voice chain
        on the PREVIOUS board's settings, and the next time Preferences was
        okayed those stale values were written back over what the new board
        had saved. The board you opened quietly became the board you left.
        """
        mic = getattr(self, "mic", None)
        if mic is None:
            return
        mic.gain_db = board.mic_gain_db
        mic.channel = board.mic_channel
        mic.monitor = bool(board.mic_monitor)
        chain = getattr(mic, "chain", None)
        if chain is None:
            return
        chain.update(board.voice_settings or {})
        chain.enabled = bool(board.voice_on)
        wanted = (board.voice_settings or {}).get("plugin") or None
        if wanted != chain.plugin_path:
            chain.set_plugin(None)
            chain.wanted_plugin = wanted
            chain.wanted_plugin_values = dict(
                (board.voice_settings or {}).get("plugin_values") or {})
            self._restore_voice_plugin()

    def _restore_voice_plugin(self):
        """Load the plugin the board asked for, without holding the app up.

        A VST3 takes over a second to load and runs its own start up code, so
        this happens on a thread of its own and drops the plugin into the
        chain when it is ready. set_plugin takes the chain's lock, so the
        microphone can be live throughout.
        """
        chain = getattr(getattr(self, "mic", None), "chain", None)
        if chain is None or not getattr(chain, "wanted_plugin", None):
            return
        path = chain.wanted_plugin
        values = dict(getattr(chain, "wanted_plugin_values", {}) or {})

        def work():
            try:
                plugin = vst.load(path)
            except Exception as exc:
                wx.CallAfter(self._voice_plugin_failed, path, exc)
                return
            if values:
                try:
                    vst.apply(plugin, values, chain._lock)
                except Exception:
                    pass
            wx.CallAfter(self._voice_plugin_ready, chain, plugin, path)

        threading.Thread(target=work, daemon=True).start()

    def _voice_plugin_ready(self, chain, plugin, path):
        if chain is not getattr(getattr(self, "mic", None), "chain", None):
            return                    # the board moved on while it was loading
        chain.set_plugin(plugin, path)
        chain.wanted_plugin = None
        chain.wanted_plugin_values = {}

    def _voice_plugin_failed(self, path, exc):
        """Say so once, in the status line, and leave the rest alone.

        A plugin that has been uninstalled, or a board carried to another
        machine, is an ordinary thing rather than an error worth a dialog.
        The setting is kept, so plugging the machine back in brings it back.
        """
        self.announce_help("The plugin %s could not be loaded: %s"
                           % (os.path.basename(path), exc))

    def _load_into(self, path, keep_path=True):
        try:
            board = Board.load(path)
        except Exception as exc:
            wx.MessageBox(f"That board could not be opened.\n\n{exc}",
                          "Open failed", wx.OK | wx.ICON_ERROR, self)
            return
        self.mixer.stop_all(fade_out=0.05)
        if not keep_path:
            board.path = None
        self._adopt(board)

        missing = len(board.missing_slots)
        tail = f", {missing} files missing" if missing else ""
        self.announce(f"Loaded {os.path.basename(path)}, "
                      f"{board.assigned_count} sounds{tail}")

    def _on_relink(self, _event):
        # The playlist counts too: one walk of the folder repairs both, so a
        # board whose pads are fine but whose running order is not still has
        # something to relink.
        missing = self.board.missing_slots
        asked = len(missing) + len(self.board.playlist.missing)
        if not asked:
            self.announce_help("Nothing is missing")
            wx.MessageBox("Every sound on this board was found.", "Nothing to relink",
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        with wx.DirDialog(self, f"Where should I look for the {asked} "
                          "missing sounds?", style=wx.DD_DIR_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            folder = dialog.GetPath()

        import threading
        self.announce_help("Looking through %s. This may take a moment." % folder)
        wx.BeginBusyCursor()

        result = {}

        def work():
            try:
                result["repaired"] = self.board.relink(folder)
            except Exception as exc:
                result["error"] = exc
            wx.CallAfter(done)

        def done():
            wx.EndBusyCursor()
            if "error" in result:
                self.announce("Could not search that folder. %s" % result["error"])
                return
            self._relink_finished(result.get("repaired") or [], asked)

        threading.Thread(target=work, daemon=True, name="dropdeck-relink").start()

    def _relink_finished(self, repaired, asked):
        """Bring the board and the playlist back in line with what was found.

        ``repaired`` holds Slots AND playlist Tracks - one walk of the folder
        repairs both, which is the whole reason they share it. Only a Slot has
        a pad behind it; handing a Track to _sync_button asked it for a bank
        that a Track has never had, and took the relink down with it.
        """
        for item in repaired:
            if isinstance(item, Slot):
                self._sync_button(item)
        if any(not isinstance(item, Slot) for item in repaired):
            self.playlist_panel.refresh()
        still = len(self.board.missing_slots) + len(self.board.playlist.missing)
        self.announce(f"Relinked {len(repaired)} of {asked}. "
                      f"{still} still missing" if still
                      else f"Relinked all {len(repaired)}")
        if repaired:
            self._touch()

    # ----------------------------------------------------------- on air --
    def streaming(self):
        """On air, connecting or trying to get back. Not merely configured."""
        streamer = getattr(self, "streamer", None)
        return streamer is not None and streamer.running

    def toggle_stream(self, _event=None, to=None):
        """Go live to one named destination, or come off air.

        `Ctrl+B` is the video platform and `Alt+Shift+B` is the radio station.
        Asked for on 12 September 2026, and the reason is what the summary
        used to say: one key plus a remembered `live_to` meant the destination
        was whichever you last picked, so the page in front of you before
        going live could be for the other one entirely.

        **Each key is a toggle for ITS OWN destination.** Pressing the key for
        the place you are not broadcasting to names where you actually are
        and does nothing else. It does not quietly switch: switching means
        dropping one connection and opening another, which is not something to
        do to somebody mid show on a keypress that looks like a toggle.

        **The summary is asked for HERE rather than inside start_stream, and
        that is not a detail.** start_stream is called by anything that wants
        the show on the air; this is called by a person pressing a key. A
        modal window on the first one hung every test that goes live, for
        ever, on a dialog nothing could click. The keys and the On air menu
        both come through here, so a user is asked either way, and nothing
        else in the app or the tests is.
        """
        if to is None:
            # Nobody said, so honour what is set up. The menu items and the
            # keys always say; this covers anything older that does not.
            to = self.board.live_to
        if self.streaming():
            if self.board.live_to != to:
                said = ("You are on air to %s. %s comes off air."
                        % (self._destination_words(self.board.live_to),
                           self._destination_key(self.board.live_to)))
                self.announce_answer(said)
                return False
            self.stop_stream()
            return False
        if to != self.board.live_to:
            # The key IS the choice, so it is written down before anything
            # reads it. Everything downstream asks the board which
            # destination this is, and it now gets the answer the user just
            # gave rather than one from last week.
            self.board.live_to = to
            self._touch()
            self._rebuild_station_menu()
        if not self._cleared_to_go():
            return False
        return self.start_stream()

    def _set_air_labels(self, live):
        """Both items, every time, because only one of them can be on air.

        The item for the destination that is live says "come off air"; the
        other keeps its own wording, so the menu never offers to take you off
        air from a place you are not.
        """
        video = getattr(self, "stream_item", None)
        radio = getattr(self, "stream_audio_item", None)
        on_video = live and self.board.live_to == C.LIVE_TO_VIDEO
        if video is not None:
            video.SetItemLabel(("Come o&ff air" if on_video
                                else "&Go live on video") + chr(9) + "Ctrl+B")
        if radio is not None:
            radio.SetItemLabel(("Come o&ff air" if (live and not on_video)
                                else "Go live on ra&dio")
                               + chr(9) + "Alt+Shift+B")

    def _destination_words(self, which):
        """"your video platform" or "your radio station". For a sentence."""
        return ("your video platform" if which == C.LIVE_TO_VIDEO
                else "your radio station")

    def _destination_key(self, which):
        return "Ctrl+B" if which == C.LIVE_TO_VIDEO else "Alt+Shift+B"

    def start_stream(self):
        """Open the tap and start the thread. Says why if it cannot.

        The tap goes on EVERY mixer, not just the first one, because a bank
        sent to its own sound card is still part of the show and a listener
        should hear it.
        """
        if self.streaming():
            return True
        video = self.board.live_to == C.LIVE_TO_VIDEO
        page = SettingsDialog.PAGE_VIDEO if video else SettingsDialog.PAGE_STREAM
        if not (self.board.video_host if video else self.board.stream_host):
            self.announce("There is no %s set up yet. Set up streaming is on "
                          "the On air menu"
                          % ("video platform" if video else "server"))
            self._on_settings(page=page)
            return False

        settings = self._stream_settings()
        # Refused HERE rather than at the far end. A missing key comes back
        # from YouTube as a bare I/O error several seconds into going live,
        # which is the worst moment and the least useful message.
        if streamout.is_rtmp(settings["server"]) and not settings["password"]:
            self.announce("There is no stream key for this station. Put one "
                          "in on the Video streaming page")
            self._on_settings(page=page)
            return False

        self.air_bus = streamout.AirBus(self.mixer.samplerate)
        self._sync_air_taps()

        self.video_source = self._build_picture(settings)
        self.overlay = self.build_overlay(settings)
        # A new watcher per broadcast, so a fault in yesterday's show is not
        # still being remembered in today's.
        # A recording may already have one, and going live to a RADIO
        # station builds no picture at all, so this used to replace the
        # recording's watcher with None and switch the black and frozen
        # picture watch off mid recording. Keep whichever is wanted.
        if self.video_source is not None or self.recording_video():
            if self.watcher is None:
                self.watcher = health.Watcher(
                    on_say=self._on_picture_trouble)
        else:
            self.watcher = None
        self.streamer = streamout.Streamer(
            self.air_bus, settings, overlay_=self.overlay,
            watcher=self.watcher,
            on_state=self._on_stream_state,
            on_trouble=self._on_stream_trouble,
            video_source=self.video_source)
        self.streamer.set_title(self._now_playing_title())
        self.streamer.start()
        self._start_framing()
        # A recording already running now takes the stream's own frames
        # instead of pulling them itself, so one camera serves both.
        self._sync_record_picture()
        self._set_air_labels(True)
        return True

    # ----------------------------------------------------------- recording --
    def recording(self):
        rec = getattr(self, "recorder", None)
        return rec is not None and rec.running

    def toggle_recording(self):
        if self.recording():
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        """Begin taping the show. Nothing about this needs you to be on air."""
        from . import recorder as recording
        if self.recording():
            return True
        self.record_bus = streamout.AirBus(self.mixer.samplerate)
        self._sync_air_taps()
        self.recorder = recording.Recorder(
            self.record_bus,
            fmt=self.board.record_format,
            bitrate=self.board.record_bitrate,
            folder=self.board.record_folder or None,
            on_state=self._on_record_state)
        if not self.recorder.start():
            detail = self.recorder.detail
            self.recorder = None
            self.record_bus = None
            self._sync_air_taps()
            self.announce(detail or "Recording would not start")
            wx.MessageBox(detail or "Recording would not start.",
                          "Recording failed", wx.OK | wx.ICON_WARNING, self)
            return False
        self.audio_cue = cuefile.CueFile(self.recorder.path)
        # Whatever is already on the air belongs at 0:00, or the first track
        # of the show is missing from its own tracklist.
        self._note_current_track()
        self._set_record_label(True)
        self.announce("Recording to %s. %s"
                      % (os.path.basename(self.recorder.path or ""),
                         self.what_is_in_the_recording()))
        self._update_status()
        return True

    # --------------------------------------------------- video recording --
    def toggle_video_recording(self, _event=None):
        """Ctrl+Shift+R. Tape the picture as well as the sound."""
        if self.recording_video():
            self.stop_video_recording()
        else:
            self.start_video_recording()

    def start_video_recording(self):
        """Begin taping picture and sound. Nothing here needs you on air."""
        if self.recording_video():
            return True
        settings = self._picture_settings()
        # THE PICTURE FIRST, and waited for. The recorder's timeline begins
        # the moment it starts, and `_emit_one` writes black while nothing
        # has arrived: measured at 20 black frames, 0.67 s, with a camera
        # that takes 0.70 s to open. Acquiring here, before the recorder
        # exists, means the first frame in the file is a picture.
        #
        # It blocks the key press for as long as the camera takes. That is
        # the right trade for this key and not for Ctrl+B: a recording key
        # is pressed once and the first second of the file is permanent,
        # where going live has a fallback card covering it and a presenter
        # waiting to talk.
        self.feed().acquire(picturefeed.FOR_RECORDING,
                            ready_timeout=picturefeed.READY_SECONDS)
        self.video_bus = streamout.AirBus(self.mixer.samplerate)
        self.video_tap = videorecord.FrameTap()
        self._sync_air_taps()
        # video_width, not width. _picture_settings has never held a "width"
        # key, so all three of these read None and fell through to the board
        # by luck the same values, which is why it went unnoticed. A
        # settings dict that is asked for keys it does not have is a bug
        # waiting for the day the fallback stops matching.
        self.video_recorder = videorecord.VideoRecorder(
            self.video_bus, self.video_tap,
            width=int(settings.get("video_width") or self.board.video_width),
            height=int(settings.get("video_height") or self.board.video_height),
            fps=int(settings.get("video_fps") or self.board.video_fps),
            bitrate=self.board.record_bitrate,
            folder=self.board.record_folder or None,
            on_state=self._on_record_state)
        if not self.video_recorder.start():
            detail = self.video_recorder.detail
            self.video_recorder = None
            self.video_bus = None
            self.video_tap = None
            self._sync_air_taps()
            # The feed was taken before the recorder was built, so it has to
            # be handed back or the camera light stays on for a recording
            # that never happened.
            self.feed().release(picturefeed.FOR_RECORDING)
            self.announce(detail or "Recording would not start")
            return False
        self.video_cue = cuefile.CueFile(self.video_recorder.path)
        self._note_current_track()
        # The feed was taken above, before the recorder, so the first
        # frame in the file is a real picture rather than black. A recording
        # wants a picture whatever Ctrl+B is pointed at, which is the fault
        # Tony reported on 12 September: the picture belonged to the video
        # PLATFORM, so a board set up for a radio station recorded a card
        # with the station name on it.
        self.refresh_overlay()
        self._sync_record_picture()
        # The same two watches the air gets. A camera that goes black or
        # freezes rather than failing outright is invisible to
        # FallbackSource, which is the whole reason health.Watcher exists,
        # and a presenter recording themselves needs to know they are in
        # shot at least as much as one who is live.
        if self.watcher is None:
            self.watcher = health.Watcher(on_say=self._on_picture_trouble)
        self._start_framing()
        self._set_video_record_label(True)
        self.announce("Recording picture and sound to %s. %s%s"
                      % (os.path.basename(self.video_recorder.path or ""),
                         self.what_is_in_the_recording(picture=True),
                         self._picture_warnings()))
        self._update_status()
        return True

    def _picture_warnings(self):
        """What is wrong with the picture, said once, as it starts.

        Spoken rather than a dialog. Ctrl+B can afford to stop and ask
        because going live is a decision; Ctrl+Shift+R is pressed in the
        middle of a show and must never block. But the warnings have to
        arrive: a picture fault in a recording is permanent, and this is the
        only chance to mention it before ninety minutes of it exist.
        """
        try:
            settings = self._picture_settings()
            ready, reason = True, ""
            if settings.get("picture") in C.PICTURE_NEEDS_SCREEN:
                ready = screen.available()
                reason = screen.why_unavailable()
            notes = preflight.picture_notes(
                settings, self.board, screen_ready=ready,
                screen_reason=reason, consumer=preflight.FOR_RECORDING)
        except Exception:
            return ""
        said = [note.text for note in notes]
        return (" " + ". ".join(said) + ".") if said else ""

    def stop_video_recording(self, quiet=False):
        """Finish the file and say where it is and what went wrong."""
        rec, self.video_recorder = getattr(self, "video_recorder", None), None
        self._stop_record_picture()
        feed = getattr(self, "picture_feed", None)
        if feed is not None:
            feed.release(picturefeed.FOR_RECORDING)
        if not self.streaming():
            self._stop_framing()
            self.watcher = None
        # STOPPED FIRST, then asked. `bytes_written` is the handle's own
        # position, so reporting before the muxer has written its last
        # fragment understated the file: measured, "0 megabytes" for a file
        # that is 0.39 MB on disk with six seconds of picture in it.
        if rec is not None:
            rec.stop()
        said = rec.report() if rec is not None else ""
        cue, self.video_cue = getattr(self, "video_cue", None), None
        if cue is not None and cue.describe():
            said = "%s %s." % (said, cue.describe())
        self.video_bus = None
        self.video_tap = None
        self._sync_air_taps()
        self._set_video_record_label(False)
        if rec is not None and not quiet:
            self.announce(said)
        self._update_status()
        return rec.path if rec is not None else None

    def _note_current_track(self):
        """Whatever is on air right now, at the top of a fresh tracklist."""
        player = getattr(self, "player", None)
        if player is not None and getattr(player, "playing", False):
            self.note_track_on_air(getattr(player, "current", None))

    def what_is_in_the_recording(self, picture=False):
        """Name what is really in it, and what is NOT. Darrell's question.

        Darrell, 10 September 2026: "when I did my audio recording, the only
        thing I heard was my voice, even though I checked the box that told
        me that I would hear it myself."

        He had ticked "Hear it yourself", which is monitoring, and a
        recording takes the ON AIR mix. That is the right design and nothing
        anywhere said so, so the recording appeared to lose his source. The
        same rule the mix minus sentence already follows: something that is
        NOT in it must never look as though it is.
        """
        inside, outside = [], []
        mic = getattr(self, "mic", None)
        if mic is not None:
            if mic.on_air:
                inside.append("your microphone")
            elif not self.board.stream_mic:
                outside.append("your microphone, which is switched off on the "
                               "Audio streaming page")
            elif mic.muted:
                outside.append("your microphone, which is muted")
        soloed = self.anything_soloed()
        for source in getattr(self, "sources", []):
            if source.wants_air(soloed):
                inside.append(source.name)
            elif source.wants_monitor(soloed):
                outside.append("%s, which you can hear but is not on the air"
                               % source.name)
        inside.append("your sounds and running order")
        said = "In it: %s." % ", ".join(inside)
        if outside:
            said += " NOT in it: %s." % ", ".join(outside)
        if picture:
            # Only the file that HAS one. Ctrl+R while a picture recording
            # is running used to announce "Recording to Drop Deck Stream
            # 002.wav. ... Picture: everything on my screens at 1280 by
            # 720", and there is no picture in a WAV. Exactly the rule this
            # method exists for: something that is NOT in it must never look
            # as though it is.
            said += self._picture_in_the_recording()
        return said

    def _picture_in_the_recording(self):
        """What the PICTURE of a video recording is, named out loud.

        The audio half of this sentence has existed since 3.7.0 and the
        picture half never did, which is how a recording of a card with the
        station name on it went unnoticed: everything the app said about the
        file was true, and none of it was about the picture. A blind
        presenter cannot see a freeze frame. This is the only thing that will
        ever tell them.
        """
        if not self.recording_video():
            return ""
        feed = getattr(self, "picture_feed", None)
        chosen = C.PICTURE_LABELS.get(self.board.picture,
                                      self.board.picture).lower()
        if feed is None or not feed.running:
            return " Picture: %s." % chosen
        if not feed.frames_asked:
            # Nothing has looked through it yet, so there is no fallback to
            # report and describing one would be a guess. Say what is set up.
            return " Picture: %s." % chosen
        try:
            said = feed.describe()
        except Exception:
            said = ""
        if feed.fallen_back:
            return (" Picture: a card instead of %s%s."
                    % (chosen, (", because %s" % feed.reason)
                       if feed.reason else ""))
        return " Picture: %s." % (said or chosen)

    def _sync_record_picture(self):
        """Decide who fills the recording's tap, and re-decide on every change.

        Two ways a file can get its picture, and the choice has to be made
        again whenever either side moves, which is why this is a sync rather
        than a start: going live DURING a recording, or coming off air during
        one, swaps which of them is right.

        **While live to a video platform the stream fills the tap**, so the
        file carries the identical composited frame the encoder is sending,
        overlay and all, for no extra work and, far more importantly, with
        no second camera. Otherwise this thread pulls from the shared feed.

        The tap now goes to the STREAMER rather than to its destination. The
        destination is rebuilt from scratch on every reconnect, and a tap
        attached to the old object was silently dropped by the first
        reconnect: the recording then repeated one frame for the rest of the
        show with every count, length and log still perfect. And
        `getattr(streamer, "destination")` never answered anything at all,
        because the attribute is `_destination`, so this whole branch had
        never once run since it was written, and every recording made while
        live was quietly building a second pipeline of its own.
        """
        streamer = getattr(self, "streamer", None)
        tap = getattr(self, "video_tap", None)
        if tap is None or not self.recording_video():
            self._stop_record_picture()
            return
        # ON AIR, not merely streaming. `streaming()` is true while
        # connecting and while reconnecting, and during both there is no
        # destination to fill the tap: `set_frame_tap` remembers it and
        # returns False, and nothing puts a frame anywhere. So the app's own
        # thread keeps the job until the picture is really going out.
        if (streamer is not None and self.streaming()
                and streamer.wants_video()
                and getattr(streamer, "state", "") == streamout.ON_AIR):
            self._stop_record_thread()
            streamer.set_frame_tap(tap)
            return
        if streamer is not None:
            streamer.set_frame_tap(None)
        if getattr(self, "_record_picture_thread", None) is not None:
            return                      # already ours, and already running
        self._record_picture_stop = threading.Event()
        self._record_picture_thread = threading.Thread(
            target=self._record_picture_run, daemon=True,
            name="dropdeck-record-picture")
        self._record_picture_thread.start()

    def _record_picture_run(self):
        """One frame every 1/fps into the tap. Never touches the audio.

        It PULLS FROM THE SHARED FEED and does not build a source of its own.
        The version that did build its own never called `start()`, so the
        capture threads behind `frame()` never ran, every call answered None,
        and `FallbackSource` substituted the card: a recording of a card with
        the station name on it, which is the fault Tony reported. Measured
        against his board, 12 September 2026: 175 frames in six seconds, mean
        pixel difference from a freshly drawn card ZERO.

        `time.monotonic` here is pacing, not timing, and that distinction is
        load bearing. Nothing in the file is stamped from it: the recorder
        counts frames against its own audio sample clock and repeats or drops
        to fit, so a slow pass costs a repeated frame and can never move the
        timeline. See videorecord.py.
        """
        feed = self.feed()
        # BEFORE the first question. Asking a capture that has not produced a
        # frame yet gets None, and None sends FallbackSource to the card for
        # PICTURE_RETRY_SECONDS: measured at five of the first eight seconds
        # of a split screen recording. This thread is not the UI's, so
        # waiting here costs the user nothing at all.
        feed.wait_ready(picturefeed.READY_SECONDS)
        rec = getattr(self, "video_recorder", None)
        fps = rec.fps if rec is not None else 30
        width = rec.width if rec is not None else 1280
        height = rec.height if rec is not None else 720
        stop = self._record_picture_stop
        while not stop.is_set():
            started = time.monotonic()
            try:
                frame = feed.frame(width, height)
                if frame is not None:
                    # Read every pass, not captured once, so an edit to a
                    # tile or a track change reaches the file.
                    overlay_ = getattr(self, "record_overlay", None)
                    if overlay_ is not None:
                        # draw_on, not draw, and it is reached at all now.
                        # The overlay was guarded on
                        # hasattr(self, "_build_overlay") and the method is
                        # build_overlay, so a recording made off air has
                        # never carried the words the stream carries.
                        try:
                            frame = overlay_.draw_on(frame)
                        except Exception:
                            pass
                    tap = getattr(self, "video_tap", None)
                    if tap is not None:
                        tap.put(frame)
                    # LAST, and on the composite, for the same reason
                    # RtmpDestination._picture looks last: what it is asked
                    # to notice is whether anybody watching would see
                    # anything, and what they see is the whole frame.
                    watch = getattr(self, "watcher", None)
                    if watch is not None:
                        try:
                            watch.look(frame,
                                       moving=(feed.kind
                                               in C.PICTURE_NEEDS_CAMERA))
                        except Exception:
                            pass
            except Exception:
                pass
            left = (1.0 / float(fps or 30)) - (time.monotonic() - started)
            if left > 0:
                stop.wait(left)

    def _stop_record_thread(self):
        """Stop our own picture thread, leaving the stream's tap alone."""
        stop = getattr(self, "_record_picture_stop", None)
        if stop is not None:
            stop.set()
        thread = getattr(self, "_record_picture_thread", None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._record_picture_thread = None
        self._record_picture_stop = None

    def _stop_record_picture(self):
        """Nobody is filling the tap any more, whichever way it was filled."""
        self._stop_record_thread()
        streamer = getattr(self, "streamer", None)
        if streamer is not None:
            streamer.set_frame_tap(None)

    def _set_video_record_label(self, on):
        item = getattr(self, "video_record_item", None)
        if item is not None:
            # Alt+E, because this menu has spent every other letter. On air
            # now holds A C D F G H I K L M N O P R S T U V W and Y.
            item.SetItemLabel(("Stop r&ecording picture" if on
                               else "R&ecord picture and sound")
                              + chr(9) + "Ctrl+Shift+R")

    def stop_recording(self, quiet=False):
        """Finish the file and say where it is."""
        rec, self.recorder = getattr(self, "recorder", None), None
        cue, self.audio_cue = getattr(self, "audio_cue", None), None
        path = rec.stop() if rec is not None else None
        self.record_bus = None
        # Streaming may still be going and wants the mix it always had.
        self._sync_air_taps()
        self._set_record_label(False)
        if rec is not None and not quiet:
            minutes, seconds = divmod(int(rec.elapsed), 60)
            size = rec.bytes_written / (1024.0 * 1024.0)
            said = ("Recording saved as %s, %d minutes %d seconds, "
                    "%.1f megabytes"
                    % (os.path.basename(path or ""), minutes, seconds, size))
            lost = getattr(rec, "losing_audio", 0)
            if lost:
                # Said, at last. A sound recording whose ring overflowed
                # reported itself as clean, which is the shape of fault this
                # whole release is about.
                said += (". It lost audio %d times, so there are gaps in it"
                         % lost)
            if cue is not None and cue.describe():
                said += ". %s" % cue.describe()
            self.announce(said)
        self._update_status()
        return path

    def _set_record_label(self, on):
        item = getattr(self, "record_item", None)
        if item is not None:
            item.SetItemLabel(("Stop &recording\tCtrl+R" if on
                               else "Start &recording\tCtrl+R"))

    # ------------------------------------------------------- track list --
    def _cue_files(self):
        """Every tracklist currently being written. Nought, one or two.

        Two when sound and picture are both being recorded, because they are
        two files and each wants its own list beside it.
        """
        return [cue for cue in (getattr(self, "audio_cue", None),
                                getattr(self, "video_cue", None))
                if cue is not None]

    def note_track_on_air(self, track):
        """A running order item went out. Put it in every tracklist.

        Called from `_playlist_moved`, which is the one place that knows a
        handover happened. Pads are deliberately not in here: Tyler asked for
        what the PLAYLIST played, and a tracklist with forty sound effects in
        it is not a tracklist.
        """
        if track is None:
            return
        title = (getattr(track, "title_text", None)
                 or getattr(track, "title", None)
                 or getattr(track, "display_name", "") or "")
        performer = (getattr(track, "artist_text", None)
                     or getattr(track, "artist", "") or "")
        for cue, rec in ((getattr(self, "audio_cue", None),
                          getattr(self, "recorder", None)),
                         (getattr(self, "video_cue", None),
                          getattr(self, "video_recorder", None))):
            if cue is None or rec is None:
                continue
            # The RECORDING's own clock, never a wall clock. Both recorders
            # count frames written, so a machine that stalled reports where
            # the audio really is rather than how long we waited.
            try:
                cue.add(title, performer, float(getattr(rec, "elapsed", 0.0)))
            except Exception:
                pass

    def _on_record_state(self, state, detail):
        """Either recorder reporting. WHICH ONE has to be part of the answer.

        Mark found this on 12 September 2026 and it is the worst thing in
        the picture work: `_on_record_state` was handed to BOTH recorders as
        their `on_state`, and `videorecord.FAILED` is the same string as
        `recorder.FAILED`, so a VIDEO failure ran `_record_failed`, which
        dropped `self.recorder` and `self.record_bus`. An ordinary disk
        fault on the MP4 therefore abandoned the sound recording mid write
        with its thread still alive, reset the Ctrl+R menu label, said
        nothing whatever about it, and left the video side inconsistent: the
        camera still open, the picture thread still spinning, the status bar
        still claiming a picture recording. The show ended up in neither
        file, and the only thing spoken was about the wrong recording.
        """
        from . import recorder as recording
        if state != recording.FAILED:
            # "The recording is losing audio. The machine cannot keep up
            # with the picture." was computed by `_check_backlog` on every
            # such recording and thrown away here, because only FAILED was
            # handled. It is the sentence that tells somebody to stop and
            # fix it while the show can still be saved; said at the end, it
            # is an epitaph. `_check_backlog` only fires on a change, so
            # this cannot chatter.
            if detail:
                wx.CallAfter(self.announce, detail)
            return
        wx.CallAfter(self._record_failed, detail)

    def _record_failed(self, detail):
        """Said out loud, because a recording that stopped by itself is the
        kind of thing you find out about afterwards otherwise.

        It works out WHICH recorder died by asking each one, rather than
        assuming. Both are checked, because a disk that fills takes both.
        """
        from . import recorder as recording
        video = getattr(self, "video_recorder", None)
        audio = getattr(self, "recorder", None)
        said = detail or "The recording stopped"
        if video is not None and video.state == videorecord.FAILED:
            # Down the ordinary path, so the feed is released, the picture
            # thread is stopped, the label is right and the cue file is
            # closed. Quiet, because the reason is spoken below.
            self.stop_video_recording(quiet=True)
            said = "The picture recording stopped. %s" % said
            if audio is not None and audio.running:
                said += " Your sound recording is still going."
        if audio is not None and audio.state == recording.FAILED:
            self.recorder = None
            self.record_bus = None
            self._sync_air_taps()
            self._set_record_label(False)
            if video is not None and video.running:
                said += " Your picture recording is still going."
        self.announce(said)
        self._update_status()

    def _open_recordings(self):
        from . import recorder as recording
        folder = self.board.record_folder or recording.default_folder()
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)              # noqa: S606 - a folder we made
        except Exception as exc:
            self.announce("Could not open %s. %s" % (folder, exc))

    def _sync_air_taps(self):
        """Point the mixers at whoever wants the on air mix, or at nobody.

        Streaming and recording both want it and cannot share one bus: reading
        a bus takes the audio out of it, so two readers on one ring would each
        get half a show. They get a bus each and the mixers write to both.

        Every start and stop of either goes through here rather than setting
        the tap itself. Setting it in two places is how the tap got lost on a
        device change in 3.0, and that was one caller, not two.
        """
        buses = [bus for bus in (getattr(self, "air_bus", None),
                                 getattr(self, "record_bus", None),
                                 getattr(self, "video_bus", None))
                 if bus is not None]
        tap = None
        if len(buses) == 1:
            tap = buses[0]
        elif buses:
            tap = streamout.Taps(*buses)
        for mixer in self.mixer.mixers:
            mixer.air_tap = tap
            mixer.air_source = None
        # The send is a THIRD reader of the same mix, and the one that does
        # not need anything to be live. It has its own bus for the same
        # reason the recorder does: reading a bus takes the audio out of it.
        send = getattr(self, "send", None)
        sending = send is not None and send.is_running
        self.mixer.send_tap = send.bus if sending else None
        self.mixer.send_minus = self._send_minus_source() if sending else None
        mic = getattr(self, "mic", None)
        if mic is None:
            return
        # The microphone goes out whether or not you can hear yourself. They
        # are different questions and this is the one about the listener. It
        # is recorded on the same terms, and sent on the same terms.
        soloed = self.anything_soloed()
        wanted = bool(buses) or sending
        mic.on_air = (wanted and bool(self.board.stream_mic)
                      and not mic.muted and (mic.soloed or not soloed))
        # The group goes on air whenever anything in it is wanted there. A
        # source is on air on its own terms: somebody putting a games call out
        # has not necessarily got their microphone open.
        extras = getattr(self, "sources", [])
        for source in extras:
            source.input.on_air = source.wants_air(soloed)
            source.input.monitor = source.wants_monitor(soloed)
        if wanted and (mic.on_air or any(s.wants_air(soloed) for s in extras)):
            self.mixer.primary.air_source = getattr(self, "source_group", mic)

    # ------------------------------------------------------------- send --
    def _resolve_send_device(self):
        """The saved send output as a live index, or None for the default."""
        return resolve_device({"name": self.board.send_device_name,
                               "hostapi": self.board.send_device_hostapi})

    def _send_minus_source(self):
        """The one source the send leaves out, or None.

        Found by NAME, because that is what the board stores: a source list
        gets reordered and an index would quietly start excluding somebody
        else. A name that matches nothing returns None, which sends
        everything, and `send_report` says so rather than letting a mix minus
        that is not happening look like one that is.
        """
        wanted = (self.board.send_minus or "").strip().lower()
        if not wanted:
            return None
        # A real source is looked for FIRST. The microphone label used to win,
        # so somebody with a second microphone on a cable named "My
        # microphone" had the real microphone taken out of the send and that
        # source left in it, which is the exact echo this is here to prevent.
        for source in getattr(self, "sources", []):
            if source.name.strip().lower() == wanted:
                return source
        if wanted == SendDialog.MIC_LABEL.lower():
            return getattr(self, "mic", None)
        return None

    def sending(self):
        """Is the show going out of a sound card to another program."""
        send = getattr(self, "send", None)
        return send is not None and send.is_running

    def _start_send(self, quiet=False):
        """Open the send. True if audio is really going out of it."""
        self._stop_send(quiet=True)
        device = self._resolve_send_device()
        # **board.send_on is INTENT and is never cleared by a failure.**
        #
        # It used to be switched off here, and it is saved with the board, so
        # one launch with the card missing wrote "no send" to disk. Plug the
        # card back in, restart, and the send did not come back and nothing
        # said why, because the startup line reads the same field that had
        # just been overwritten. One variable was answering two questions:
        # "do you want a send" and "is one running". Found by Jackson,
        # 11 September 2026. `sending()` answers the second one.
        if self.board.send_device_name and device is None:
            self.send_failed = ("%s is not here at the moment, so the show is "
                                "not going to another program. It will start "
                                "again by itself when the card is back."
                                % self.board.send_device_name)
            if not quiet:
                self.announce(self.send_failed)
            return False
        send = sendout.Send(device=device, gain_db=self.board.send_gain_db)
        if not send.is_running:
            send.close()
            self.send_failed = ("The send could not be opened. %s"
                                % (send.last_error or "No reason was given."))
            if not quiet:
                self.announce(self.send_failed)
            return False
        self.send_failed = ""
        self.send = send
        self.board.send_on = True
        # The confidence feed is an EXTRA on the source group, which is what
        # makes it impossible for it to loop: the group sums extras into what
        # the presenter hears and leaves them out of what goes out.
        group = getattr(self, "source_group", None)
        if group is not None and send.confidence not in group.extras:
            group.extras.append(send.confidence)
        if self.board.send_monitor:
            send.confidence.start()
        self._sync_air_taps()
        self._sync_send_menu()
        self.start_sources()
        if not quiet:
            self.announce("Sending to %s." % send.describe())
        self._update_status()
        return True

    def _stop_send(self, quiet=False):
        """Close the send and put everything back. Safe to call twice."""
        send, self.send = getattr(self, "send", None), None
        if send is None:
            return False
        group = getattr(self, "source_group", None)
        if group is not None and send.confidence in group.extras:
            group.extras.remove(send.confidence)
        try:
            send.close()
        except Exception:
            pass
        self._sync_air_taps()
        self._sync_send_menu()
        if not quiet:
            self.announce("The send is off.")
        self._update_status()
        return True

    def _sync_send_menu(self):
        """Put the On air menu in step with what the send is actually doing.

        A state has to be visible where the state is changed, and the menu is
        where somebody looks. `stream_item` and `record_item` have flipped
        their labels since 3.0; the send shipped without it, so opening the
        menu could not tell you whether your show was going out of this
        machine.
        """
        item = getattr(self, "send_item", None)
        if item is not None:
            item.SetItemLabel(
                ("Stop sen&ding this show" if self.sending()
                 else "Send th&is show to another program...")
                + chr(9) + "Alt+Shift+O")
        item = getattr(self, "send_monitor_item", None)
        if item is not None:
            send = getattr(self, "send", None)
            item.Enable(send is not None)
            item.Check(bool(send is not None and send.confidence.on))

    def _on_send_setup(self, _event=None):
        """Alt+Shift+O. Where the show goes, and what it leaves out."""
        dialog = SendDialog(self, self.board)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            chosen = dialog.result()
        finally:
            dialog.Destroy()
        for field, value in chosen.items():
            setattr(self.board, field, value)
        self._touch()
        if not self.board.send_on:
            self._stop_send()
            return
        if self._start_send():
            trouble = self._routing_conflicts()
            if trouble:
                self.announce(" ".join(trouble))
            else:
                self.announce(self.send_report())

    def _on_send_monitor(self, _event=None):
        """Ctrl+Shift+H. Hear what the other program is being handed."""
        send = getattr(self, "send", None)
        if send is None:
            self.announce("Nothing is being sent. Alt+Shift+O sets a send up.")
            return
        if send.confidence.on:
            send.confidence.stop()
            self.board.send_monitor = False
            self._sync_send_menu()
            self.announce("You are no longer hearing the send.")
        else:
            send.confidence.start()
            self.board.send_monitor = True
            self._sync_send_menu()
            where = ("your monitor output" if self.mixer.monitor_device is not None
                     else "your main output, because you have no separate "
                          "monitor output set")
            self.announce("You are hearing the send, through %s. It arrives "
                          "about a quarter of a second late, so it is for "
                          "checking rather than for talking over." % where)
        self._update_status()

    def _on_send_status(self, _event=None):
        """Ctrl+Shift+O. Is the send arriving clean.

        On announce_answer, not announce. This key has no other effect
        whatsoever, so at speech level "none" on the ordinary channel it
        would be a dead key. Same rule as Ctrl+L and Ctrl+Shift+B.
        """
        self.announce_answer(self.send_report())

    def _on_cue_sheet(self, _event=None):
        """Ctrl+Shift+C. What is coming up, from the ticked items.

        Opens it, or brings it to the front and puts the cursor back in the
        list. It never CLOSES it: a toggle whose state you cannot see is a
        coin flip, and Escape closes it like every other window here.
        """
        window = getattr(self, "cue_window", None)
        if window:
            try:
                window.Raise()
                window.list.SetFocus()
                return
            except Exception:
                self.cue_window = None
        self.cue_window = CueSheetDialog(self)
        self.cue_window.Bind(wx.EVT_WINDOW_DESTROY,
                             lambda e: setattr(self, "cue_window", None)
                             or e.Skip())
        self.cue_window.Show()

    def cue_clock_line(self):
        """What is on air and how long is left, for the cue sheet's clock.

        The one moving number, and it lives OUTSIDE the list on purpose: a
        counting cell inside a row is a name change every second, and a name
        change on the focused row makes a screen reader start again.
        """
        player = getattr(self, "player", None)
        if player is None or not getattr(player, "playing", False):
            return "Nothing is playing from the running order."
        said = []
        name = getattr(player, "current_title", "") or "the current track"
        left = float(getattr(player, "remaining", 0.0) or 0.0)
        said.append("On air, %s%s" % (name, (", %s left"
                                             % cuesheet.said_length(left))
                                      if left > 0 else ""))
        until = float(getattr(player, "until_handover", 0.0) or 0.0)
        nxt = getattr(player, "next_title", "") or ""
        if nxt:
            said.append("Next, %s%s" % (nxt, (", in %s"
                                              % cuesheet.said_length(until))
                                        if until > 0 else ""))
        return ".  ".join(said) + "."

    def _on_routing(self, _event=None):
        """Ctrl+Shift+W. Where every single thing is going, in one go.

        The one command somebody who cannot see a routing page actually
        needs. Everything in it is derived from the board and the mixer at
        the moment it is asked, so it can never drift from what is really
        happening. On announce_answer for the reason above.
        """
        self.announce_answer(self.routing_report())

    def routing_report(self):
        """Main output, banks, monitor, programme output, sources, faults."""
        parts = [routing.describe_routing(
            bank_devices=self._live_bank_devices(),
            monitor_device=self.mixer.monitor_device,
            program_device=(self.send.device if self.send is not None
                            else None),
            program_on=self.sending(),
            monitor_everything=self.mixer.monitor_everything,
            describe=describe_device,
            bank_names=self.board.bank_names)]
        if self.sending():
            parts.append(self.send_report())
        elif self.board.send_device_name:
            parts.extend(self._cable_lines())
        ok, why = self.mixer.keeping_up()
        if not ok:
            parts.append("One of your outputs is not keeping up: %s." % why)
        for line in self._routing_conflicts():
            parts.append(line)
        parts.append(self.picture_report())
        return " ".join(p for p in parts if p)

    def picture_report(self):
        """What the picture is, and what is using it. One paragraph.

        There was nowhere in the app that answered this. Ctrl+Shift+V is per
        moment and describes what is live; the settings are split across a
        page called Video streaming and one called Recording; and the
        question a presenter actually has is "what picture have I got, and
        what does it apply to". Four things can consume one now, so it is
        worth a sentence naming them.
        """
        board = self.board
        chosen = C.PICTURE_LABELS.get(board.picture, board.picture).lower()
        said = ["Your picture is %s, %d by %d."
                % (chosen, board.video_width, board.video_height)]
        feed = getattr(self, "picture_feed", None)
        using = feed.describe_holders() if feed is not None else ""
        if using:
            said.append("%s %s it."
                        % (using.capitalize(),
                           "are using" if " and " in using else "is using"))
        elif board.live_to == C.LIVE_TO_VIDEO:
            said.append("Nothing is using it yet. It goes out when you press "
                        "Ctrl+B, and into the file when you press "
                        "Ctrl+Shift+R.")
        else:
            # The sentence Tony's report was asking for. His radio station
            # takes no picture, and that is not a reason for him to have no
            # picture: it is a reason to say which of the two this is for.
            said.append("Nothing is using it yet. Ctrl+B goes to your radio "
                        "station, which sends no picture, so this is for "
                        "Ctrl+Shift+R until you switch Ctrl+B over.")
        if feed is not None and feed.running and feed.fallen_back:
            said.append("A card is standing in%s."
                        % ((", because %s" % feed.reason) if feed.reason
                           else ""))
        marks = self.overlay if self._showing() else self.build_overlay()
        if marks is not None:
            try:
                said.append("On top of it: %s." % marks.describe())
            except Exception:
                pass
        return " ".join(said)

    def _live_bank_devices(self):
        """The bank routing as device indices, which is what routing wants."""
        return {bank: self.mixer.bank_devices.get(bank)
                for bank in range(1, C.BANK_COUNT + 1)}

    def _routing_conflicts(self):
        """Anything wrong with where things are pointed. Sentences, or none."""
        return routing.conflicts(
            bank_devices=self._live_bank_devices(),
            monitor_device=self.mixer.monitor_device,
            program_device=(self.send.device if self.send is not None
                            else self._resolve_send_device()),
            program_on=self.board.send_on,
            describe=describe_device)

    def send_report(self):
        """The whole answer to "how is the send doing", as one spoken line.

        Written here rather than in send.py because two of the three things
        worth saying are the frame's: which source is being left out, and
        whether the name on the board still matches one.
        """
        send = getattr(self, "send", None)
        if send is None:
            return ("Nothing is being sent. Alt+Shift+O sets up a send to "
                    "another program on this machine.")
        parts = [send.report()]
        if not self.board.stream_mic:
            # The same rule as the mix minus sentence below: something that
            # is NOT in the send must never be described as though it were.
            # board.stream_mic is a checkbox on the Audio streaming page and
            # somebody who does not stream would reasonably turn it off, and
            # then the call cannot hear them and nothing says why.
            parts.append("Your microphone is switched off on the Audio "
                         "streaming page, so your voice is not in it.")
        wanted = (self.board.send_minus or "").strip()
        if not wanted:
            parts.append("Everything is in it.")
        elif self._send_minus_source() is None:
            # A mix minus that is not happening must never look like one that
            # is. This is the sentence that stops a call full of echo being a
            # mystery.
            parts.append("It is set to leave out %s, and there is nothing by "
                         "that name any more, so everything is going out."
                         % wanted)
        else:
            parts.append("It leaves out %s." % wanted)
        ok, why = self.mixer.keeping_up()
        if not ok:
            parts.append("Your output is not keeping up: %s." % why)
        parts.extend(self._cable_lines())
        return " ".join(parts)

    def _cable_lines(self):
        """What the other program should pick up, and whether Windows agrees.

        Both halves of this come off the Windows registry rather than out of
        PortAudio, because PortAudio cannot see either one: it knows what it
        can open, not what the endpoint is SET to and not which capture
        device is the far end of the same cable.

        Reading the registry is allowed to fail for any reason at all and
        must never cost anybody a send, so it is wrapped. A missing sentence
        is a worse report; a raised exception in a status line is a broken
        program.
        """
        name = self.board.send_device_name
        lines = []
        try:
            found = endpoints.endpoints()
            partner = endpoints.partner_of(name, found)
            if partner:
                lines.append("In the other program, choose %s as its input "
                             "device." % partner)
            said = endpoints.mismatch_for(name, found)
            if said:
                lines.append(said)
        except Exception:
            pass
        return lines

    def stop_stream(self, quiet=False):
        """Come off air and put everything back the way it was."""
        streamer, self.streamer = getattr(self, "streamer", None), None
        if streamer is not None:
            streamer.stop()
        self._stop_framing()
        self.video_source = None
        # The overlay and the health watch belong to one broadcast. Left
        # behind, the watcher would still be remembering yesterday's fault.
        self.overlay = None
        self.watcher = None
        # LET GO, do not close. A camera left open after a show is a light on
        # in the room, but a recording still running wants the same picture
        # and closing it here would have taken the recording's camera with
        # it. The feed shuts the device down when the LAST holder lets go.
        feed = getattr(self, "picture_feed", None)
        if feed is not None:
            feed.release(picturefeed.FOR_STREAM)
        self.air_bus = None
        # Recording may still be going, and it wants the same mix. One place
        # decides who is listening to the mixers, so coming off air cannot
        # take a recording down with it.
        self._sync_air_taps()
        # The stream was filling a recording's tap. It is not any more, so
        # the recording has to start pulling for itself or its picture would
        # freeze on the last frame that went out, with every frame count,
        # length and log still perfect.
        self._sync_record_picture()
        # And a recording that is still running keeps its watches. The
        # teardown above is unconditional, which took the framing and the
        # black picture watch off a recording that had nothing to do with
        # the stream. stop_video_recording already gets the mirror of this
        # right.
        if self.recording_video():
            if self.watcher is None:
                self.watcher = health.Watcher(
                    on_say=self._on_picture_trouble)
            self._start_framing()
        self._set_air_labels(False)
        if not quiet:
            self.announce("Off air")
        self._update_status()

    # ------------------------------------------------------------ picture --
    #: The one picture pipeline. Everything that wants a frame (the stream,
    #: a recording, a preview, the framing watcher) takes a hold on this
    #: rather than building its own, because a camera has ONE owner and
    #: because a source swap has to reach all of them at once. Made on first
    #: use so a board of WAVs never touches it. See picturefeed.py.
    picture_feed = None

    def feed(self):
        """The shared picture pipeline, made the first time anything asks."""
        made = getattr(self, "picture_feed", None)
        if made is None:
            made = picturefeed.PictureFeed(
                self._picture_settings,
                on_fallback=self._picture_failed,
                on_change=self._picture_changed)
            self.picture_feed = made
        return made

    def _picture_changed(self):
        """The feed swapped its source under everybody. Follow it.

        The framing watcher reads the source object, so it has to be rebuilt
        on both the way in and the way out: a camera arriving needs watching
        and a camera going away needs the watch stopped.
        """
        wx.CallAfter(self._refollow_picture)

    def _refollow_picture(self):
        self._stop_framing()
        self._start_framing()
        self._update_status()

    def _build_picture(self, settings):
        """What goes on the screen for a destination that insists on one.

        Taken only when the destination needs it. An Icecast station opening a
        camera would be a light on in the room for no reason at all. But a
        RECORDING wants one whatever Ctrl+B is pointed at, which is why this
        gate lives here and not inside the feed.
        """
        if not picturefeed.wanted_for(settings):
            return None
        return self.feed().acquire(picturefeed.FOR_STREAM)

    def preview_picture(self, timeout=None):
        """One frame of what WOULD go out, whether or not we are live.

        Tony, 8 September 2026: "i should be able to check before going
        live." He is right, and the first version of the shot check could
        not: it read `video_source`, which only exists once `Ctrl+B` has
        been pressed, so the answer to "how does my shot look" was "go on
        air and find out".

        **Never call this on the UI thread.** Opening a camera is about six
        tenths of a second and a screen grab blocks on the compositor.

        Returns `(frame, note)`. The note says whether this was the real
        live picture or one built to look at, because those are different
        claims and the person reading cannot tell them apart by looking.
        """
        width = self.board.video_width
        height = self.board.video_height
        feed = self.feed()
        # Whatever already holds the picture, look through THAT rather than
        # opening a second one. A preview that built its own source would ask
        # Windows for a camera the stream or the recording already has, and
        # DirectShow gives a device to one owner at a time.
        if feed.running:
            picture_ = feed.frame(width, height)
            where = ("what is going out now" if self._showing()
                     else "what is being captured now")
            return self._with_overlay(picture_), where
        # Nothing holds it. Take a hold of our own, look once, let go.
        # Deliberately NOT gated on the destination being RTMP the way
        # _build_picture is: somebody set up to go to their radio station may
        # still want to see the picture before they switch over, and they may
        # be recording it.
        try:
            feed.acquire(picturefeed.FOR_PREVIEW,
                         ready_timeout=(picturefeed.READY_SECONDS
                                        if timeout is None else timeout))
            picture_ = feed.frame(width, height)
            if picture_ is None and feed.reason:
                return None, feed.reason
            return self._with_overlay(picture_), "what would go out"
        except Exception as exc:
            return None, str(exc)
        finally:
            # Always, and it is a RELEASE rather than a close: if the stream
            # or a recording took a hold while we were looking, the device
            # stays open for them. A camera left open by a preview is a light
            # on in the room and a device another program cannot have.
            feed.release(picturefeed.FOR_PREVIEW)

    def _with_overlay(self, picture_):
        """The frame with the words on it, the way a viewer would see it.

        The overlay is drawn by the DESTINATION, not by the source, so a
        frame taken straight from `video_source` has none of it. The shot
        check offers to tell you whether the lower third sits across your
        face, and it cannot do that from a picture the lower third is not in.
        """
        if picture_ is None:
            return None
        try:
            marks = self.build_overlay(self._picture_settings())
            return marks.draw_on(picture_) if marks is not None else picture_
        except Exception:
            return picture_

    def _picture_failed(self, reason):
        """Said once, from whatever thread noticed, never once a frame.

        It names WHAT is showing the card. "The stream is showing a card
        instead" is simply untrue when nothing is streaming and the card is
        going into a file, and a message that is wrong about which of the two
        it means is worse than no message: the presenter checks the wrong
        thing. The feed knows who is holding it.
        """
        feed = getattr(self, "picture_feed", None)
        who = feed.describe_holders() if feed is not None else ""
        if "is back" in (reason or "").lower():
            said = "%s. %s has the picture again." % (
                reason, (who or "The picture").capitalize())
        else:
            said = "%s. %s is showing a card instead." % (
                reason, (who or "The stream").capitalize())
        wx.CallAfter(self.announce, said)

    # ------------------------------------------------------------ framing --
    def _start_framing(self):
        """Watch the shot while on air, on a thread of its own.

        Not on the UI thread and not on the streaming thread. The streaming
        thread is carrying the audio, and five milliseconds of face detection
        has no business anywhere near it.
        """
        self._stop_framing()
        feed = getattr(self, "picture_feed", None)
        # Anything with a camera in it, not just the camera source. The split
        # has one and a presenter using it needs to know they are in shot at
        # least as much, because they are small in the corner of it.
        #
        # Asked of the FEED, so the shot is watched while a recording is
        # being made off air. It used to read video_source, which only exists
        # once Ctrl+B has been pressed, so a presenter recording video got no
        # framing help at all.
        if feed is None or not feed.running:
            return
        # ASKED OF THE BOARD, not of the live source. `feed.kind` reports
        # "card" while a camera is still opening and whenever it has fallen
        # back, and a camera is 0.79 s to its first frame, so starting the
        # framing watch right after acquiring the feed always saw a card and
        # never started at all. The question is what the user CHOSE.
        if self.board.picture not in C.PICTURE_NEEDS_CAMERA:
            return
        level = self.board.framing_level
        if level not in framing.FRAMING_LEVELS:
            level = framing.FRAMING_PROBLEMS
        self.framer = framing.Framer(level=level, on_say=self._say_framing)
        if self.framer.error:
            # Worth saying ONCE, because somebody who turned this on and hears
            # nothing would reasonably think it was working.
            self.announce(self.framer.error)
            return
        self._framing_stop = threading.Event()
        self._framing_thread = threading.Thread(
            target=self._framing_loop, daemon=True, name="dropdeck-framing")
        self._framing_thread.start()

    def _framing_loop(self):
        stop = self._framing_stop
        while not stop.is_set():
            feed = getattr(self, "picture_feed", None)
            framer = getattr(self, "framer", None)
            if feed is None or framer is None or not feed.running:
                return
            try:
                if framer.due():
                    # The feed answers with the raw camera frame, through the
                    # fallback and through a split's composite, because what
                    # a face detector wants is the camera and not the card
                    # standing in for it.
                    framer.look(feed.latest())
            except Exception:
                pass          # never let looking at a picture end a broadcast
            if stop.wait(C.FACE_CHECK_SECONDS / 2.0):
                return

    def _stop_framing(self):
        stop = getattr(self, "_framing_stop", None)
        if stop is not None:
            stop.set()
        thread = getattr(self, "_framing_thread", None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._framing_thread = None
        self.framer = None

    def _say_framing(self, text):
        wx.CallAfter(self.announce, text)

    def describe_shot(self, _event=None):
        """Ctrl+Shift+F. What the camera can see, on demand.

        Answers at every setting INCLUDING off, and whether or not you are on
        air, because a key that does nothing is broken rather than quiet. This
        is the one people will actually use: setting a shot up means asking
        over and over for ten seconds and then never again.
        """
        framer = getattr(self, "framer", None)
        feed = getattr(self, "picture_feed", None)
        if framer is not None and feed is not None and feed.running:
            self.announce_answer(framer.describe())
            return
        if self.board.picture not in C.PICTURE_NEEDS_CAMERA:
            self.announce_answer(
                "Your picture is not set to a camera. Picture settings are "
                "in Preferences, or press Alt+Shift+V")
            return
        if not self.board.camera:
            self.announce_answer("No camera has been chosen yet")
            return
        # Nothing holds the picture, so look once rather than refusing.
        # Through the FEED, because building a second CameraSource while the
        # feed holds the device is the two owner case this release exists to
        # remove: Tiffany measured the first owner's reader thread dying for
        # good and the app then blaming another program for it.
        self.announce_answer("Looking through the camera...")
        threading.Thread(target=self._look_once, daemon=True,
                         name="dropdeck-look").start()

    def _look_once(self):
        """Look through the shared feed once. Off the UI thread, always.

        THROUGH THE FEED, not a camera of its own. It used to build its own
        `CameraSource`, and Tiffany measured what a second owner does to the
        first: the original reader thread dies for good, `start()` refuses to
        relaunch it, and `FallbackSource` then asks a corpse for a frame
        every five seconds while the app announces that another program is
        probably using the camera. The other program was Drop Deck. So
        pressing Ctrl+Shift+F during a show could take the camera off the
        air permanently, and Preferences has a button that does the same.
        """
        from . import camera as cameras
        feed = self.feed()
        held = feed.running
        try:
            if not held:
                feed.acquire(picturefeed.FOR_PREVIEW,
                             ready_timeout=picturefeed.READY_SECONDS)
            raw = feed.latest()
            if raw is None:
                wx.CallAfter(self.announce_answer,
                             feed.reason or "The camera gave no picture")
                return
            watcher = framing.Framer(level=framing.FRAMING_OFF)
            reading = watcher.measure(raw)
            wx.CallAfter(self.announce_answer,
                         watcher.error or reading.sentence())
        except Exception as exc:
            wx.CallAfter(self.announce_answer, cameras.explain(
                exc, self.board.camera))
        finally:
            if not held:
                try:
                    feed.release(picturefeed.FOR_PREVIEW)
                except Exception:
                    pass

    def _on_stream_help(self, _event=None, platform=None):
        """How to set up a platform, without leaving the app."""
        with StreamHelpDialog(self, platform or self.board.video_server) as box:
            box.ShowModal()

    def live_to_labels(self):
        """What each of the two destinations is set to, in that order.

        The settings only. The menu adds "My radio station: " and "My video
        platform: " itself, because the mnemonic has to live in the fixed
        part of a label and never inside a name the user chose.

        An unset one answers "not set up yet" rather than nothing. A choice
        you cannot see is the whole complaint this menu exists to answer, so
        an absent line would be the same fault in a smaller place.
        """
        station = (self.board.stream_name or self.board.stream_host
                   or "not set up yet")
        if self.board.stream_host and self.board.stream_name:
            station = "%s, %s" % (self.board.stream_name, self.board.stream_host)
        platform = (streamout.server_label(self.board.video_server)
                    if self.board.video_host else "not set up yet")
        return (station, platform)

    def _rebuild_station_menu(self):
        """Where Ctrl+B sends the show, with a dot beside the one it uses.

        Every entry answers the same question, which is why they are one
        radio group rather than two ideas in one menu: the two destinations
        are what is typed into the two Preferences pages, and a saved
        location is a whole configuration including which of the two it is.
        Picking any of them is picking where the show goes.
        """
        menu = getattr(self, "station_menu", None)
        if menu is None:
            return
        for item in list(menu.GetMenuItems()):
            menu.Delete(item)
        video = self.board.live_to == C.LIVE_TO_VIDEO
        audio_label, video_label = self.live_to_labels()
        # Alt+D and Alt+P rather than the obvious R and V: tests/test_menus.py
        # treats a whole top level menu and its submenus as ONE mnemonic
        # namespace, and On air already spends R on Start recording and V on
        # Video source. Windows would let a submenu have its own, but a
        # screen reader user arrowing a menu tree hears them all the same.
        # The mnemonic sits in the fixed part of the label, never in the
        # station name, which is the user's text.
        first = menu.AppendRadioItem(
            ID_LIVE_TO_AUDIO, "My ra&dio station: " + _escaped(audio_label),
            "Send the show to your radio server: Icecast, Liquidsoap or "
            "SHOUTcast. Set it up on the Audio streaming page")
        second = menu.AppendRadioItem(
            ID_LIVE_TO_VIDEO, "My video &platform: " + _escaped(video_label),
            "Send the show to YouTube, Facebook, Restream or any RTMP "
            "server, with a picture. Set it up on the Video streaming page")
        # Checked AFTER both exist. Appending a radio item checks the first
        # of a run by default, so checking as you go leaves both ticked.
        (second if video else first).Check(True)

        names = self.board.station_names()[:MAX_STATIONS]
        menu.AppendSeparator()
        if names:
            # A submenu, not more entries here, and that is not tidiness.
            # wx begins a NEW radio group after a separator, so a saved run
            # in this menu keeps a tick of its own and two dots show at once.
            # They are also a different question: these overwrite BOTH
            # Preferences pages, where the two above only choose between them.
            saved = wx.Menu()
            for offset, name in enumerate(names):
                item = saved.AppendRadioItem(
                    ID_STATION_BASE + offset, _escaped(name),
                    "Load this saved setup, and send the show wherever it "
                    "was saved to go")
                if name == self.board.stream_name:
                    item.Check(True)
            menu.AppendSubMenu(saved, "Load a saved set&up")
        menu.Append(ID_STREAM_SETUP, "&Set these up...",
                    "The address, mount point and password for a server, or "
                    "the platform and stream key for video")

    def _on_live_to(self, event):
        """Point Ctrl+B at the radio station or at the video platform."""
        want = (C.LIVE_TO_VIDEO if event.GetId() == ID_LIVE_TO_VIDEO
                else C.LIVE_TO_AUDIO)
        if want == self.board.live_to:
            return
        if self.streaming():
            # The same rule as changing station: swapping the destination
            # under a live stream is not a thing to do quietly.
            self.announce("Come off air first, %s, then change where it "
                          "goes" % self._destination_key(self.board.live_to))
            self._rebuild_station_menu()
            return
        self.board.live_to = want
        self._touch()
        report = self.preflight()
        if report is not None and report.blocked:
            self.announce("Ctrl+B now goes to your %s. %s"
                          % ("video platform" if want == C.LIVE_TO_VIDEO
                             else "radio station", report.stops[0].text))
        else:
            self.announce("Ctrl+B now goes to %s"
                          % (report.summary() if report is not None
                             else "your " + ("video platform"
                                             if want == C.LIVE_TO_VIDEO
                                             else "radio station")))
        self._rebuild_station_menu()
        self._update_status()

    def _on_pick_station(self, event):
        """Load a saved station. Not while it is broadcasting, though."""
        offset = event.GetId() - ID_STATION_BASE
        names = self.board.station_names()
        if not 0 <= offset < len(names):
            return
        name = names[offset]
        if name == self.board.stream_name:
            return
        if self.streaming():
            # Swapping the server under a live stream mid sentence is not a
            # thing to do quietly. Come off air first, deliberately.
            self.announce("Come off air first, Ctrl+B, then change station")
            self._rebuild_station_menu()
            return
        if self.board.load_station(name):
            self._touch()
            # Where it goes, not just what was loaded. A saved setup carries
            # its own destination, so loading one can move the show from the
            # radio station to the video platform without anything saying so.
            report = self.preflight()
            self.announce("%s. Ctrl+B goes to %s"
                          % (name, report.summary() if report is not None
                             else self.board.stream_host))
        self._rebuild_station_menu()
        self._update_status()

    def _on_stream_stats(self, _event=None):
        """Who is listening. Opens whether or not you are on air.

        Off air is a perfectly good time to ask: a station that runs
        automation is playing to an audience all day and Drop Deck is only
        one of the things that feeds it.
        """
        # A video platform does not publish listener numbers anywhere this can
        # read. Asked anyway, it used to build a URL out of an RTMP address
        # ("http://rtmps://a.rtmps.youtube.com/live2:8003/status-json.xsl"),
        # fail three DNS lookups, and then read that gibberish out and tell
        # the user to fix a box that is not even on the video page. Saying
        # there is no answer is the honest reply.
        if self.board.live_to == C.LIVE_TO_VIDEO:
            self.announce(
                "%s does not publish a viewer count that Drop Deck can read. "
                "It is on the platform's own page"
                % streamout.server_label(self.board.video_server))
            return
        if not self.board.stream_host:
            self.announce("No streaming server is set up yet")
            self._on_settings(page=SettingsDialog.PAGE_STREAM)
            return
        with StreamStatsDialog(self, self._stream_settings(),
                               on_air=self.streaming()) as dialog:
            dialog.ShowModal()

    def _picture_settings(self):
        """Everything about the PICTURE, whatever Ctrl+B is pointed at.

        `_stream_settings` answers for the destination, so when `live_to` is
        the radio station it returns the audio dict, which has no `picture`
        key at all. Anything that wants the picture and asks that question
        gets `None` and `picture.build` quietly hands back a card.

        That is exactly what the shot check did on 8 September 2026: Tony set
        a picture source, pressed Alt+Shift+D, and would have been told about
        a card he had not chosen. A silent wrong answer, not an error.
        """
        board = self.board
        return {"name": board.stream_name,
                "picture": board.picture,
                "picture_file": board.picture_file,
                "picture_clock": board.picture_clock,
                "camera": board.camera,
                "screen": board.screen,
                "split_corner": board.split_corner,
                "colour_background": board.colour_background,
                "colour_text": board.colour_text,
                "colour_accent": board.colour_accent,
                "video_width": board.video_width,
                "video_height": board.video_height,
                "video_fps": board.video_fps}

    def _stream_settings(self):
        """What the board holds, in the shape the streamer wants.

        Audio and video are two separate sets of settings on two separate
        pages, and `board.live_to` says which one Ctrl+B uses. They are kept
        apart rather than shared because they looked shareable and are not: an
        Icecast address is a host name and an RTMP one is a whole URL, so one
        board could not hold a radio station AND a YouTube channel while they
        shared `stream_host`. Setting up one silently destroyed the other.

        The stream key is the one thing NOT read from the board. It lives in
        Windows Credential Manager under the station's name, and it is fetched
        here so nothing else in the app has to know that. A board saved before
        keys moved still works: whatever is in stream_password is used when
        the credential store has nothing.
        """
        board = self.board
        if board.live_to == C.LIVE_TO_VIDEO:
            key = secrets.fetch(board.stream_name or "") or board.video_key
            return {"server": board.video_server, "host": board.video_host,
                    "port": 0, "mount": "", "user": "", "password": key,
                    "format": "aac", "bitrate": board.stream_bitrate,
                    "name": board.stream_name,
                    # The CHANNEL, which is not the radio station. Kept as a
                    # key of its own rather than overwriting "name", because
                    # "name" is what the card on the picture says and that is
                    # his station identity either way.
                    "video_name": board.video_name,
                    "description": board.stream_description,
                    "genre": board.stream_genre, "url": board.stream_url,
                    "stats_url": "", "public": False,
                    "picture": board.picture,
                    "picture_file": board.picture_file,
                    "picture_clock": board.picture_clock,
                    "camera": board.camera,
                    "screen": board.screen,
                    "split_corner": board.split_corner,
                    "colour_background": board.colour_background,
                    "colour_text": board.colour_text,
                    "colour_accent": board.colour_accent,
                    "video_width": board.video_width,
                    "video_height": board.video_height,
                    "video_fps": board.video_fps,
                    "video_bitrate": board.video_bitrate}
        return {"server": board.stream_server, "host": board.stream_host,
                "port": board.stream_port, "mount": board.stream_mount,
                "user": board.stream_user, "password": board.stream_password,
                "format": board.stream_format, "bitrate": board.stream_bitrate,
                "name": board.stream_name,
                "description": board.stream_description,
                "genre": board.stream_genre, "url": board.stream_url,
                "stats_url": board.stream_stats_url,
                "public": board.stream_public}

    def _on_stream_trouble(self, message):
        """The connection is not keeping up. Said, not written.

        A stream falling behind sounds perfect in the room and skips at the
        other end, so the only way a presenter finds out is being told.
        """
        wx.CallAfter(self.announce, message)

    def _on_stream_state(self, state, detail):
        """Called from the streaming thread. Nothing here touches wx.

        Everything is handed to the main thread, because a screen reader
        announcement raised from a socket thread is a crash waiting for a bad
        night.
        """
        wx.CallAfter(self._say_stream_state, state, detail)

    def _going_live_warning(self):
        """What pressing Ctrl+B is about to do, when that is not obvious.

        YouTube and Facebook behave OPPOSITELY and a presenter has to know
        which they are on. Pushing to a YouTube stream key creates the watch
        page, puts you live publicly and notifies your subscribers, with no
        preview and nothing to confirm. Facebook shows a preview in Live
        Producer and posts nothing until somebody clicks Go Live Now.

        Somebody who cannot see either page has no other way to find this out,
        and finding it out afterwards is finding it out too late.
        """
        if self.board.live_to != C.LIVE_TO_VIDEO:
            return ""
        if C.RTMP_GOES_LIVE_AT_ONCE.get(self.board.video_server):
            return ("You are live on YouTube now. Your subscribers have been "
                    "notified and the stream will be saved to your channel")
        if self.board.video_server == "facebook":
            return ("Facebook has the stream. Nothing is posted until you "
                    "press Go Live Now in Live Producer")
        return ""

    def _say_stream_state(self, state, detail):
        if not self:
            return
        if state == streamout.ON_AIR:
            self.announce("On air, %s" % detail if detail else "On air")
            warning = self._going_live_warning()
            if warning:
                self.announce(warning)
        elif state == streamout.CONNECTING:
            self.announce_help("Connecting to the server")
        elif state == streamout.RECONNECTING:
            self.announce("Off air, trying again. %s" % detail)
        elif state == streamout.FAILED:
            self.announce("Could not go on air. %s" % detail)
            self.stop_stream(quiet=True)
        # WHO FILLS A RECORDING'S TAP depends on whether the stream is
        # actually on air, and `streaming()` stays True right through
        # RECONNECTING. Measured by Mark: a server that went away at seven
        # seconds froze the recording's picture for the remaining eleven,
        # `tap.puts` stopped dead, 145 of 261 frames repeated, and the app
        # said "Off air, trying again" about the stream and nothing at all
        # about the file. A two minute Wi-Fi gap is two minutes of freeze
        # frame in a ninety minute recording.
        self._sync_record_picture()
        self._update_status()

    def say_stream_status(self, _event=None):
        """Ctrl+Shift+B. The answer to "am I actually on air".

        Spoken as an answer rather than as news, so it works with the app's
        speech turned all the way down. Same reasoning as Ctrl+L.
        """
        self.announce_answer(self.stream_status())

    # ----------------------------------------------------- going live --
    def preflight(self):
        """What Ctrl+B would do right now, or None when it cannot tell."""
        try:
            return self._report_for(self._stream_settings())
        except Exception:
            return None

    def _report_for(self, settings):
        """The pre-flight for one set of settings, with the live facts added.

        Whether the screen can be captured is only asked when the picture
        needs it, because the answer costs a Windows call and a card does not
        care.
        """
        ready, reason = True, ""
        if settings.get("picture") in C.PICTURE_NEEDS_SCREEN:
            ready = screen.available()
            reason = screen.why_unavailable()
        return preflight.check(
            settings, self.board,
            audio_running=bool(getattr(self.mixer, "is_running", True)),
            mic_open=self._mic_open(), screen_ready=ready,
            screen_reason=reason)

    def _cleared_to_go(self, settings=None):
        """Say what is about to go out, and let the presenter change it.

        True means carry on to the air. The dialog is the default because the
        whole complaint was not knowing what was live; the checkbox inside it
        turns this back into the single keystroke it used to be, for somebody
        who does this every day and knows their own settings.
        """
        try:
            report = (self.preflight() if settings is None
                      else self._report_for(settings))
            if report is None:
                return True
        except Exception:
            # Never let the check itself be what stops a broadcast.
            return True
        if not self.board.ask_before_live:
            # Still said, just not asked. A warning nobody has to dismiss is
            # the point of turning the dialog off, not a warning nobody hears.
            #
            # ONE announcement, not one per note. Three calls in a row means
            # the second interrupts the first and the third interrupts that,
            # so a presenter hears the last one and never learns their
            # microphone is off the air. Whatever is STOPPING the broadcast
            # leads, for the same reason it leads in the dialog.
            said = ". ".join(note.text for note in
                             report.stops + report.warnings)
            if said:
                self.announce(said)
            return not report.blocked
        while True:
            with GoLiveDialog(self, report) as box:
                answer = box.ShowModal()
                remember = box.remember
                fix = box.fix
            if remember:
                self.board.ask_before_live = False
                self._touch()
            if answer == wx.ID_OK:
                return True
            if answer != wx.ID_APPLY:
                self.announce("Staying off air")
                return False
            self._on_settings(page=(SettingsDialog.PAGE_VIDEO
                                    if fix == C.FIX_VIDEO
                                    else SettingsDialog.PAGE_STREAM))
            report = self.preflight()
            if report is None:
                return False

    # ------------------------------------------------- the video source --
    def known_cameras(self):
        """Camera names, looked up once and remembered.

        Enumeration opens DirectShow and takes a moment, so it is never done
        on a keystroke. A camera already chosen counts even when the list
        cannot be read, or unplugging a hub would silently remove the option
        to put it back.
        """
        found = list(getattr(self, "_cameras_seen", []) or [])
        if not found:
            # Imported HERE, and the import is the whole fix. ui.py never
            # imported camera at all, so this line raised NameError into the
            # except below and this method answered "no cameras" for every
            # user, every time, for as long as it has existed. Nobody could
            # see it: `board.camera` is added back two lines down, so anybody
            # who had ALREADY chosen a camera still saw theirs, and only a
            # user who had never chosen one was quietly told they had none.
            # That is Alt+Shift+V offering no camera and no split screen to
            # every new user with a working webcam.
            from . import camera as cameras
            try:
                found = list(cameras.cameras())
            except Exception:
                found = []
            self._cameras_seen = found
        if self.board.camera and self.board.camera not in found:
            found = found + [self.board.camera]
        return found

    # ------------------------------------------- what is on the picture --
    #: There is no show yet, so there is nothing on top of a picture and
    #: nothing watching one. Set here rather than left to getattr, because
    #: two keys read them before anything has ever gone live.
    overlay = None
    watcher = None

    def build_overlay(self, settings=None):
        """What goes on top of the picture, from the board.

        Returns None when there is nothing to draw, so the frame path stays
        exactly as it was for anybody who has not set any of this up.
        """
        if not overlay.available():
            return None
        if settings is None:
            settings = self._stream_settings()
        wanted = {"name": settings.get("name") or self.board.stream_name,
                  "colour_background": self.board.colour_background,
                  "colour_text": self.board.colour_text,
                  "colour_accent": self.board.colour_accent}
        anything = False
        for key, held in (self.board.text_places or {}).items():
            kind = held.get("kind", C.TEXT_NONE)
            wanted["text_%s" % key] = kind
            wanted["text_%s_words" % key] = held.get("words", "")
            wanted["text_%s_file" % key] = held.get("file", "")
            if kind != C.TEXT_NONE:
                anything = True
        if not anything:
            return None
        made = overlay.Overlay(wanted)
        made.set_title(self._now_playing_title())
        return made

    def refresh_overlay(self):
        """Rebuild it and put it on the air, if there is a show running.

        `record_overlay` is read afresh by the recording's picture thread on
        every frame, so editing a tile mid recording reaches the file. It
        used to be built once before that loop and never replaced, so a
        "what is playing" tile in a recording was frozen on whatever was on
        at Ctrl+Shift+R.
        """
        self.overlay = self.build_overlay()
        self.record_overlay = self.build_overlay(self._picture_settings())
        streamer = getattr(self, "streamer", None)
        if streamer is not None and self.streaming():
            try:
                streamer.set_overlay(self.overlay)
            except Exception:
                pass
        self._update_status()

    def refresh_brand(self):
        """Put a changed brand on the air at once, picture and words alike.

        The colours reach the card, the letterbox bars, the panels behind the
        overlay and the line round the camera inset, so a change has to rebuild
        BOTH the picture source and the overlay. Rebuilding only one of them
        would leave a navy card behind cream panels, which is worse than
        either on its own.
        """
        self.refresh_overlay()
        feed = getattr(self, "picture_feed", None)
        if feed is None or not feed.running:
            return
        # Whatever is holding the picture, the stream or a recording or both,
        # gets the new colours. This used to ask _build_picture with the
        # DESTINATION's settings, so on a board pointed at a radio station it
        # returned None and a brand change reached nothing at all.
        try:
            feed.rebuild()
            feed.set_title(self._now_playing_title())
        except Exception:
            return
        self._stop_framing()
        self._start_framing()

    def _on_shot_check(self, _event=None):
        """Ask a model that can see. Never on the way to air, always aside."""
        with ShotCheckDialog(self, self) as box:
            box.ShowModal()

    def _on_colours(self, _event=None):
        with ColoursDialog(self, self.board, live=self._showing()) as box:
            box.ShowModal()

    def _on_screen_text(self, _event=None):
        """Alt+Shift+T. Words on the picture, wherever the picture is going.

        Ungated for the same reason as Alt+Shift+V: a recording carries the
        overlay too, so a radio station in Ctrl+B is not a reason to refuse.
        """
        if not overlay.available():
            self.announce_answer(overlay.why_unavailable())
            return
        with ScreenTextDialog(self, self.board,
                              live=self._picture_live()) as box:
            box.ShowModal()

    def describe_screen(self, _event=None):
        """Ctrl+Shift+V. Everything the audience can see, right now.

        The thing no other broadcast tool does. OBS's preview is a GPU
        surface with no accessibility tree at all, on any platform, so there
        is nothing anywhere that will tell the person producing a stream what
        is currently in it. This does.

        It answers off air as well as on, describing what WOULD go out, for
        the same reason Ctrl+Shift+F answers off air: a key that only works
        during a broadcast is a key you cannot practise with.
        """
        parts = []
        showing = self._showing()
        feed = getattr(self, "picture_feed", None)
        live = self._picture_live()
        if live:
            # WHERE it is going, first, because that is the thing the answer
            # used to get wrong: a board pointed at a radio station said
            # "Nothing" while a picture was being written to a file.
            going = []
            if showing:
                going.append("going out")
            if self.recording_video():
                going.append("being recorded")
            try:
                said = feed.describe() or "a picture"
            except Exception:
                said = "a picture"
            parts.append("%s, %s" % (said, " and ".join(going) if going
                                     else "open"))
        elif self.recording_video():
            parts.append("%s, once the picture starts"
                         % C.PICTURE_LABELS.get(self.board.picture,
                                                self.board.picture).lower())
        else:
            parts.append("%s, once you go live or start recording the picture"
                         % C.PICTURE_LABELS.get(self.board.picture,
                                                self.board.picture).lower())
        marks = self.overlay if showing else self.build_overlay()
        if marks is not None:
            try:
                parts.append(marks.describe())
            except Exception:
                pass
        else:
            parts.append("nothing on top of it")
        watch = getattr(self, "watcher", None)
        if showing and watch is not None and watch.state != health.OK:
            parts.append(watch.describe())
        self.announce_answer(". ".join(p for p in parts if p))

    def _on_picture_trouble(self, text):
        """The health watch found something. It runs on the streaming thread."""
        wx.CallAfter(self.announce, text)

    def _on_video_sources(self, _event=None):
        """Alt+Shift+V. What the picture is, whatever Ctrl+B is pointed at.

        It used to refuse unless `live_to` was the video platform. Since
        3.7.0 a recording carries a picture, so refusing meant a presenter
        set up for a radio station could not choose the picture going into
        their own file, and the picture they got was the default card with
        the station name on it. Ctrl+B's destination is not this question.
        """
        with VideoSourceDialog(self, self.board,
                               live=self._picture_live()) as box:
            box.ShowModal()

    def _picture_live(self):
        """Whether a change to the picture takes effect THIS INSTANT.

        Two things can be holding it: the stream and a video recording. A
        dialog asking "is this live" means this, not `_showing`, which is
        about the air alone. Getting those two confused is what made Alt+Shift+V
        tell a presenter their change would apply "next time you go live"
        while it was going into a file as they read it.
        """
        feed = getattr(self, "picture_feed", None)
        if feed is None or not feed.running:
            return False
        # THE STREAM OR A RECORDING, not merely "somebody has it open". A
        # shot check or Ctrl+Shift+F holds the feed for a second or two, and
        # during that second Alt+Shift+V would have answered "Now showing
        # what is on my screen" when nothing was showing anywhere and
        # nothing was being recorded. A preview is invisible to the user and
        # must not change what the app claims.
        return (feed.held_by(picturefeed.FOR_STREAM)
                or feed.held_by(picturefeed.FOR_RECORDING))

    def _showing(self):
        """Whether a picture is going out right now.

        getattr, because video_source is only set by start_stream and a frame
        that has never gone live does not have the attribute at all. The same
        guard stop_stream already uses, and for the same reason.
        """
        return bool(self.streaming()
                    and getattr(self, "video_source", None) is not None)

    def set_video_source(self, kind):
        """Put a different picture on the air. Returns what to say about it.

        On air this reaches the encoder without touching the connection: the
        size and the frame rate are locked at connect and nothing here
        changes either, and video timestamps are counted against the audio
        clock rather than taken from the source, so the swap does not move
        the timeline. See RtmpDestination.set_video_source.

        Off air it is only remembered. Either way it is saved, because a
        picture chosen mid show is still the one wanted next week.
        """
        if kind not in C.PICTURE_SOURCES:
            return ""
        was = self.board.picture
        self.board.picture = kind
        self._touch()
        label = C.PICTURE_LABELS.get(kind, kind).lower()
        feed_now = getattr(self, "picture_feed", None)
        if feed_now is not None and feed_now.running:
            # Something has the picture open, even if it is only a preview,
            # so the source is swapped under it. Two separate questions: the
            # swap follows whoever holds it, and the SENTENCE follows
            # whether that is the air or a recording.
            try:
                feed_now.rebuild()
            except Exception:
                pass
        if not self._picture_live():
            # Nothing that matters is holding the picture. This used to ask
            # `_showing`, which is about the air alone, so a presenter
            # changing the picture during a video recording was told "next
            # time you go live" while the file went on carrying the old one.
            # A recording is a consumer of the picture and a change has to
            # reach it.
            said = ("Next time you go live or record the picture: %s" % label)
            self.announce(said)
            return said
        # ONE rebuild, inside the shared feed, and every consumer follows:
        # the stream, a recording in progress, the framing watcher and the
        # next preview. It used to build a source and hand it to the streamer
        # alone, so changing the picture during a video recording changed
        # nothing in the file. The feed puts the new source in BEFORE closing
        # the old one, because a camera is about six tenths of a second to
        # its first frame and closing first would put a card on the air for
        # that six tenths.
        try:
            self.feed().rebuild()
        except Exception as exc:
            self.board.picture = was
            said = "That did not work: %s. Still showing %s" % (
                exc, C.PICTURE_LABELS.get(was, was).lower())
            self.announce(said)
            return said
        feed = self.feed()
        feed.set_title(self._now_playing_title())
        # Framing follows the picture: it only looks through a camera, and it
        # reads the source object rather than the board, so it has to be
        # rebuilt on both the way in and the way out.
        self._stop_framing()
        self._start_framing()
        # SAID OFF THE RESULT, not off the request. A camera that will not
        # open comes back as the card through FallbackSource, which is not an
        # exception and not a None: the swap succeeded and the picture is
        # still not what was asked for. Announcing the request would have
        # said "Now showing a camera" to somebody looking at a card, which is
        # the same class of fault as the one this release exists to fix.
        if feed.fallen_back or (feed.kind and feed.kind != kind):
            said = ("Asked for %s, and a card is showing instead%s"
                    % (label, (": %s" % feed.reason) if feed.reason else ""))
        else:
            said = "%s %s" % (self._picture_verb(), label)
        self.announce(said)
        self._update_status()
        return said

    def _picture_verb(self):
        """"Now showing", or the truth when it is going into a file.

        A recording is not "showing" anything to anybody, and a presenter who
        is not on air being told something is "showing" reasonably wonders
        where.
        """
        if self._showing() and self.recording_video():
            return "On air and recording:"
        if self.recording_video():
            return "Now recording:"
        return "Now showing"

    def recording_line(self):
        """One sentence about a picture recording, or nothing at all.

        Appended to the air report rather than given a key of its own,
        because "am I recording" and "am I on air" are the same question
        asked in a hurry. VideoRecorder.describe has existed since 3.7.0 and
        nothing in the app ever called it.
        """
        rec = getattr(self, "video_recorder", None)
        if rec is None or not rec.running:
            return ""
        try:
            said = rec.describe()
        except Exception:
            return ""
        return "%s.%s" % (said, self._picture_in_the_recording())

    def stream_status(self):
        streamer = getattr(self, "streamer", None)
        if streamer is None or not streamer.running:
            # ASKED OF THE TARGET THAT IS ACTUALLY TICKED. This read
            # board.stream_host whichever way live_to was set, so a board set
            # up for YouTube and nothing else answered "no server is set up
            # yet" while Ctrl+B would have gone live perfectly well, and a
            # board with both named the radio station as the destination when
            # the show was going to the video platform. It is the one
            # question this key exists to answer.
            taping = self.recording_line()
            tail = (" %s" % taping) if taping else ""
            report = self.preflight()
            if report is None:
                return "Off air, and no server is set up yet." + tail
            if report.blocked:
                # Both halves. Where it WOULD go is still the answer to the
                # question, and a reason on its own leaves somebody guessing
                # which of the two destinations is the one complaining.
                return "Off air. Ctrl+B would go to %s, but %s.%s" % (
                    report.summary(), report.stops[0].text[0].lower()
                    + report.stops[0].text[1:], tail)
            return "Off air. Ctrl+B goes live to %s.%s" % (report.summary(),
                                                           tail)
        if streamer.state != streamout.ON_AIR:
            return "%s. %s" % (streamer.state.capitalize(),
                               streamer.detail or streamer.error or "")
        # Asked of the DESTINATION, not assembled from the board. A YouTube
        # stream is AAC and H.264 whatever the audio format box says, and the
        # board's answer was "128 kbps MP3" while the app sent neither.
        described = ""
        destination = getattr(streamer, "_destination", None)
        if destination is not None:
            try:
                described = destination.describe()
            except Exception:
                described = ""
        parts = ["On air for %s" % format_duration(streamer.on_air_for)]
        if described:
            parts.append(described)
        else:
            parts.append("%d kbps %s" % (
                self.board.stream_bitrate,
                streamout.FORMATS.get(self.board.stream_format,
                                      streamout.FORMATS["mp3"])["label"]))
            parts.append("to %s" % self.board.stream_host)
        dropped = self.air_bus.dropped if self.air_bus is not None else 0
        if dropped:
            parts.append("%d blocks lost, so listeners have heard gaps"
                         % dropped)
        if streamer.backlog > C.STREAM_BEHIND_SECONDS:
            parts.append("running %d seconds behind, so the connection is not "
                         "keeping up" % int(streamer.backlog))
        if streamer.reconnects:
            parts.append("reconnected %d times" % streamer.reconnects)
        said = ", ".join(parts)
        taping = self.recording_line()
        return ("%s. %s" % (said, taping)) if taping else said

    def _now_playing_title(self):
        track = self.player.current if self.player.playing else None
        return track.display_name if track is not None else ""

    def _push_stream_title(self):
        """Tell the server what is playing, if it is wanted and has changed."""
        streamer = getattr(self, "streamer", None)
        if streamer is None or not self.board.stream_titles:
            return
        streamer.set_title(self._now_playing_title())

    def _on_settings(self, _event=None, page=None):
        """Preferences. One window, five tabs, two keys into it.

        ``page`` is which tab it opens on: Ctrl+P lands on Output and
        Ctrl+Shift+M on Microphone. Everything is applied on OK whichever tab
        you were looking at, because a settings window that only saves the
        page you happen to be on is a settings window that loses your work.
        """
        with SettingsDialog(self, self.board, self.mixer, mic=self.mic,
                            page=page) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                # The Voice tab has been changing the live chain all the while,
                # so "nothing changed" is only true once it is put back.
                undone = dialog.restore_voice()
                dialog.restore_stream()
                self.announce_help("Voice settings put back"
                                   if undone else "Nothing changed")
                # A station saved on the Streaming tab is a deliberate act and
                # survives Cancel, so the board still has to reach the disk.
                if self.board.dirty:
                    self._save_timer.Start(2000, oneShot=True)
                return
            index, name, hostapi = dialog.chosen_device
            mic_said = self._apply_mic_settings(dialog)
            bank_devices = dialog.chosen_bank_devices
            self.board.ducking = dialog.duck_on.GetValue()
            self.board.duck_db = float(dialog.duck_db.GetValue())
            self.board.announce_playback = dialog.announce_playback.GetValue()
            self.board.speech_level = dialog.speech_level
            self.board.bed_fade_in = dialog.bed_fade_in
            self.board.bed_fade_out = dialog.bed_fade_out
            self.board.warn_before_end = dialog.warn_before_end
            self.board.warn_seconds = dialog.warn_seconds
            self.board.cue_sound = dialog.cue_sound_key
            self.board.cue_level_db = dialog.cue_level_db
            shot = dialog.vision_settings
            self.board.vision_provider = shot["provider"]
            self.board.vision_model = shot["model"]
            # Only when something was typed. An empty box means "leave the
            # key I already have", which is what the label under it says,
            # and is the difference between tabbing past a field and wiping
            # a credential.
            if shot["key"]:
                secrets.store(shot["provider"], shot["key"],
                              secrets.VISION_PREFIX)
            self.board.record_format = dialog.record_format_key
            self.board.record_bitrate = dialog.record_bitrate_value
            self.board.record_folder = dialog.record_folder_path
            self.board.stop_presses = int(dialog.stop_presses.GetValue())
            self.board.stop_fade = dialog.stop_fade.GetValue()
            self.board.playlist.crossfade = dialog.crossfade
            stream = dialog.stream_settings
            self.board.stream_server = stream["server"]
            self.board.stream_host = stream["host"]
            self.board.stream_port = stream["port"]
            self.board.stream_mount = stream["mount"]
            self.board.stream_user = stream["user"]
            self.board.stream_password = stream["password"]
            self.board.stream_format = stream["format"]
            self.board.stream_bitrate = stream["bitrate"]
            self.board.stream_name = stream["name"]
            self.board.stream_public = stream["public"]
            video = dialog.video_settings
            self.board.video_server = video["server"]
            self.board.video_name = video["name"]
            self.board.video_host = video["host"]
            self.board.live_to = (C.LIVE_TO_VIDEO if video["live"]
                                  else C.LIVE_TO_AUDIO)
            # The stream key goes to the credential store, never to the board.
            # Only when it CANNOT be stored does it fall back to the board
            # file, and the dialog has already said so out loud by then.
            # The key goes to the credential store, and NEVER into
            # stream_password. That is the Icecast source password, and
            # borrowing it meant that merely looking at the video page and
            # pressing OK wiped a user's radio station password.
            key = video.get("key", "")
            if not key:
                self.board.video_key = ""
                secrets.forget(stream["name"] or "")
            elif secrets.store(stream["name"] or "", key):
                self.board.video_key = ""
            else:
                self.board.video_key = key
            picture_settings = dialog.picture_settings
            self.board.picture = picture_settings["picture"]
            self.board.picture_file = picture_settings["picture_file"]
            self.board.picture_clock = picture_settings["picture_clock"]
            self.board.camera = picture_settings["camera"]
            self.board.screen = picture_settings["screen"]
            self.board.video_width = picture_settings["video_width"]
            self.board.video_height = picture_settings["video_height"]
            self.board.video_fps = picture_settings["video_fps"]
            self.board.video_bitrate = picture_settings["video_bitrate"]
            self.board.framing_level = picture_settings["framing_level"]
            self.board.stream_mic = dialog.stream_mic.GetValue()
            self.board.stream_titles = dialog.stream_titles.GetValue()
            self.board.ask_before_live = (dialog.ask_before_live.GetValue())
            self.board.playlist_monitor_only = (
                dialog.playlist_monitor_only.GetValue())
            chain = getattr(self.mic, "chain", None)
            if chain is not None and hasattr(dialog, "voice_on"):
                chain.enabled = dialog.voice_on.GetValue()
                self.board.voice_on = chain.enabled
                self.board.voice_settings = chain.to_dict()

        self.mixer.ducking = self.board.ducking
        self.mixer.duck_db = self.board.duck_db
        self.mixer.playlist_monitor_only = self.board.playlist_monitor_only
        self._rebuild_station_menu()
        # The overlay is built FROM these settings, so it has to be rebuilt
        # after them. A place showing "my station name" would otherwise go on
        # showing the old one, live, until the next time the show went on air.
        self.refresh_overlay()
        # Beds already in flight keep the fade they started with - a voice owns
        # its envelope - so this takes effect from the next press.
        self.mixer.bed_fade_in = self.board.bed_fade_in
        self.mixer.bed_fade_out = self.board.bed_fade_out
        self._sync_warning()
        # The crossfade has two boxes now - one here and one under the running
        # order - and they are two views of one number. Whichever was used, the
        # other has to show it, or the app has two answers to one question.
        self.playlist_panel.refresh()

        routing_changed = (bank_devices != (self.board.bank_devices or {}))
        device_changed = ((name, hostapi)
                          != (self.board.device_name, self.board.device_hostapi))

        self.board.device_name = name
        self.board.device_hostapi = hostapi
        self.board.bank_devices = bank_devices

        if device_changed or routing_changed:
            # Re-routing stops everything and clears every decode cache, because
            # cached audio was resampled for the old device's rate. Warm it again
            # rather than making the next key press pay for it.
            self.mixer.set_bank_devices(self._resolve_bank_devices())
            # AFTER the mixers have actually moved. Asking before meant
            # handing the microphone the old primary's rate, which is the one
            # it already had, so the call did nothing and the microphone kept
            # monitoring and broadcasting at the wrong speed.
            mic = getattr(self, "mic", None)
            if mic is not None:
                mic.set_output_rate(self.mixer.samplerate)
            self.warm_cache()

            if self.mixer.problems:
                # A bank that fell back to the default output has to say so.
                # Silently playing out of the wrong card is the failure mode
                # this whole feature exists to avoid.
                detail = "\n\n".join(self.mixer.problems)
                self.announce(self.mixer.problems[0])
                wx.MessageBox(detail, "Output not available",
                              wx.OK | wx.ICON_WARNING, self)
                self.board.bank_devices = {
                    bank: spec for bank, spec in self.board.bank_devices.items()
                    if resolve_device(spec) is not None}
            else:
                self.announce_help(self._routing_summary())
        else:
            self.warm_cache()
            self.announce_help("Preferences saved. " + mic_said)
        self._update_status()
        self._touch()

    def _routing_summary(self):
        """What the outputs are now, in one spoken sentence."""
        extra = self.board.bank_devices or {}
        if not extra:
            return f"Everything playing through {describe_device(self.mixer.device)}"
        parts = [f"{self.board.bank_name(bank)} through {spec['name']}"
                 for bank, spec in sorted(extra.items())]
        return (f"Main output {describe_device(self.mixer.device)}. "
                + ". ".join(parts))

    # --------------------------------------------------------------- search --
    def _on_search(self, _event):
        if self.board.assigned_count == 0:
            self.announce("There are no sounds to search yet")
            return
        # Play now fires from inside the dialog and leaves it open, so you can
        # work down a list of matches and sample each one. Brian Hartgen: with
        # several hits you want to hear which is which before you commit, and
        # being thrown out of the dialog on the first press made that four
        # keystrokes per guess.
        with SearchDialog(self, self.board, self.mixer.playing_slots(),
                          on_play=lambda slot: self.trigger(slot.index)) as dialog:
            if dialog.ShowModal() != wx.ID_OK or dialog.chosen is None:
                return
            slot = dialog.chosen
        self.notebook.SetSelection(slot.bank - 1)
        button = self._button_for(slot)
        button.SetFocus()
        self.announce(f"{slot.display_name}, {slot.bank_title}, "
                      f"slot {slot.number}")

    # ----------------------------------------------------------------- help --
    def _on_shortcuts(self, _event):
        dialog = wx.Dialog(self, title="Keyboard shortcuts",
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        outer = wx.BoxSizer(wx.VERTICAL)
        # A real label in front of the field. On MSW the accessible name comes
        # from the preceding static, not from SetName, so this dialog's only
        # control had no name at all.
        outer.Add(wx.StaticText(dialog, label="&Shortcuts"), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 10)
        text = wx.TextCtrl(dialog, value=C.KEYBOARD_HELP,
                           style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        # The columns in KEYBOARD_HELP are aligned with spaces. In the default
        # proportional font the second column started at a different place on
        # nearly every row, which is what made this the most "unstyled dump"
        # screen in the app.
        mono = wx.Font(wx.FontInfo(text.GetFont().GetPointSize())
                       .Family(wx.FONTFAMILY_TELETYPE))
        for face in ("Cascadia Mono", "Consolas", "Courier New"):
            if face in set(wx.FontEnumerator.GetFacenames()):
                mono.SetFaceName(face)
                break
        text.SetFont(mono)
        outer.Add(text, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(dialog.CreateStdDialogButtonSizer(wx.OK), 0,
                  wx.ALL | wx.ALIGN_RIGHT, 10)
        dialog.SetSizerAndFit(outer)
        dialog.SetSize((640, 620))
        text.SetInsertionPoint(0)
        text.SetFocus()
        dialog.ShowModal()
        dialog.Destroy()

    def _on_about(self, _event):
        from wx.adv import AboutBox, AboutDialogInfo
        info = AboutDialogInfo()
        info.SetName(C.APP_NAME)
        info.SetVersion(C.APP_VERSION)
        info.SetDescription(
            f"{C.TAGLINE}\n\n"
            "Eighty slots across four banks: twenty sound effects, twenty dialog "
            "drops, twenty looping music beds and twenty of your own.\n\n"
            "Sounds overlap and never cut each other off. Beds duck out of the "
            "way while a sound plays, then come back.\n\n"
            "Free, and built keyboard-first for screen reader users.\n\n"
            "The forty sounds and beds in the demo pack were generated with "
            "ElevenLabs AI. Nothing in it is recorded or sampled from a "
            "commercial sound library.")
        info.SetCopyright("(C) 2026 Tony Gebhard. MIT licensed.")
        info.SetWebSite("https://tgstudios.app/drop-deck/")
        AboutBox(info, self)

    # --------------------------------------------------------------- timers --
    def _on_refresh_tick(self, _event):
        """Repaint only the buttons whose playing state actually changed, so a
        screen reader is not told the same thing four times a second."""
        # Board slots only. The playlist's two decks are slot indices above
        # the eighty pads, which is what keeps the mixer from needing a
        # special case for them - and they came through here as well, so
        # board[80] raised IndexError on the first playlist handover and went
        # on raising it, from inside a timer, every quarter of a second. From
        # then on no pad was ever relabelled again.
        now = {index for index in self.mixer.playing_slots()
               if 0 <= index < C.TOTAL_SLOTS}
        if now == self._playing:
            return
        for index in now ^ self._playing:
            slot = self.board[index]
            self._button_for(slot).refresh(index in now)
        self._playing = now

    def stop_background_work(self):
        """Bring the worker threads to a halt and wait for them.

        Called from both the close handler and Destroy, because Destroy does
        NOT raise EVT_CLOSE - so a frame torn down programmatically (the tests
        do exactly this) would otherwise close the mixer while the cache warmer
        was still inside libsndfile, and the process would segfault on the way
        out. It did, about one run in three.
        """
        # EVERY timer, not just the player's. A wx.Timer belongs to the frame
        # and goes on firing after Destroy, and a timer callback on a
        # destroyed window is an access violation rather than an exception:
        # the process simply goes. _on_close stops the refresh timer, but
        # Destroy does not raise EVT_CLOSE, so a frame torn down
        # programmatically kept a 250 ms timer pointed at nothing.
        for name in ("_player_timer", "_refresh_timer", "_save_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.Stop()
        # The recording is finished first, so the file has its header and
        # will open. A recording thread left running would also go on reading
        # a mixer that is being closed.
        if getattr(self, "recorder", None) is not None:
            try:
                self.stop_recording(quiet=True)
            except Exception:
                pass
        # An open MP4 left unfinished is a file that may not open, and the
        # picture thread holds a camera nobody else can have.
        if getattr(self, "video_recorder", None) is not None:
            try:
                self.stop_video_recording(quiet=True)
            except Exception:
                pass
        # Every extra input is a sound card being read on a thread, and one
        # left open would go on reading a mixer that is being closed.
        try:
            self.stop_sources()
        except Exception:
            pass
        # The send owns an output stream of its own, and an open output
        # stream keeps the process alive after the window has gone.
        try:
            self._stop_send(quiet=True)
        except Exception:
            pass
        # Off air before anything else is torn down. A streaming thread left
        # running would go on reading a mixer that is being closed.
        if getattr(self, "streamer", None) is not None:
            try:
                self.stop_stream(quiet=True)
            except Exception:
                pass
        mic = getattr(self, "mic", None)
        if mic is not None:
            # An open input stream keeps the process alive after the window
            # has gone, exactly the way an open output stream does.
            mic.close()
        self._closing.set()
        for name in ("_warm_thread", "_metadata_thread"):
            thread = getattr(self, name, None)
            if thread is not None:
                thread.join(timeout=3.0)
                setattr(self, name, None)

    def Destroy(self):
        self.stop_background_work()
        return super().Destroy()

    def _on_close(self, event):
        # Saved FIRST, and before anything is torn down, because if it fails
        # the answer might be not to close at all. This used to be a bare try
        # and pass at the end of the shutdown: a full disk, a read only folder
        # or a file Dropbox had locked took the whole evening's work with it
        # and said nothing whatsoever.
        # Finished FIRST, so the file is closed properly and playable. A
        # recording is somebody's show and an unfinished one may not open.
        if self.recording():
            self.stop_recording(quiet=True)
        try:
            self.board.save()
        except Exception as exc:
            answer = wx.MessageBox(
                "The board could not be saved, so anything you have changed "
                "this session would be lost.\n\n%s\n\nClose anyway?" % exc,
                "Save failed", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_ERROR, self)
            if answer != wx.YES and event.CanVeto():
                event.Veto()
                self.announce("The board was not saved. Try File then Save as.")
                return

        self._refresh_timer.Stop()
        self._save_timer.Stop()
        self.stop_background_work()
        # Give every global combination back to the rest of the system.
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        self.mixer.close()
        event.Skip()
