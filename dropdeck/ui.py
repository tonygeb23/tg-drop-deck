"""The window.

Four tabs, twenty buttons each, and a keyboard map that has not changed since
the app this one replaces. Everything you can do with the mouse has a key, and
everything that happens says so out loud.
"""

from __future__ import annotations

import ctypes
import os
import threading

import wx

from . import appicon
from . import constants as C
from . import globalhotkeys
from .board import Board, default_board_path, demo_board_path
from .dialogs import (AssignHotkeyDialog, SearchDialog, SettingsDialog,
                      TrimDialog, audio_file_dialog, key_label)
from .engine import probe
from .mixer import (Mixer, MixerGroup, describe_device, device_spec,
                    output_devices, resolve_device)
from .slot import format_duration
from .speech import Speaker, percent

ID_SLOT_BASE = wx.ID_HIGHEST + 500

ID_VOL_SFX_DOWN = wx.ID_HIGHEST + 1
ID_VOL_SFX_UP = wx.ID_HIGHEST + 2
ID_VOL_BED_DOWN = wx.ID_HIGHEST + 3
ID_VOL_BED_UP = wx.ID_HIGHEST + 4
ID_RENAME = wx.ID_HIGHEST + 5
ID_CLEAR_FOCUSED = wx.ID_HIGHEST + 6
ID_STOP_ALL = wx.ID_HIGHEST + 7
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
        label = self.slot.button_label(playing)
        changed = playing != self._playing
        self._playing = playing
        # Compared unescaped, set escaped. Comparing the escaped form against
        # slot.button_label() would differ on every ampersand and rewrite the
        # label forever.
        #
        # The label is NOT rewritten while this button has focus. On MSW a
        # button's accessible Name is its label, so changing it under a screen
        # reader restarts the announcement - which happens exactly when a sound
        # starts, on air, on the control the user is standing on. CLAUDE.md
        # forbids it. The paint below still shows the new state immediately.
        if label != self._last_label and not self.HasFocus():
            self._last_label = label
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

        grid = wx.GridSizer(rows=5, cols=4, gap=wx.Size(6, 6))
        self.buttons = []
        for slot in frame.board.bank_slots(bank):
            button = SoundButton(self, slot, frame)
            self.buttons.append(button)
            grid.Add(button, 0, wx.EXPAND)
        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)

        # wx.StaticText never wraps unless told to. Bank 3's hint needs about
        # 1400 px and does not get it even maximised, so the end of the
        # sentence was simply cut off.
        self.Bind(wx.EVT_SIZE, self._on_size)

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
        self.SetIcons(appicon.bundle())

        self.speaker = Speaker()
        # Set on close. The cache warmer decodes audio on a daemon thread, and
        # a daemon thread killed part way through a C call at interpreter
        # shutdown segfaults - which it did, intermittently, about one run in
        # three. It checks this between files instead.
        self._closing = threading.Event()
        self._warm_thread = None
        self._context_slot = None
        self._loaded_demo = False
        self.board = self._load_startup_board()
        self.mixer = MixerGroup(bank_devices=self._resolve_bank_devices(),
                                open_stream=True)
        self.mixer.set_sfx_gain(self.board.sfx_volume)
        self.mixer.set_bed_gain(self.board.bed_volume)
        self.mixer.ducking = self.board.ducking
        self.mixer.duck_db = self.board.duck_db
        # set_device clears the decode cache, so the whole board just went
        # cold. Warm it again rather than making the next key pay for it.
        self.warm_cache()

        self._build_menu()
        self._build_ui()
        self._build_accelerators()

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
        self._size_window()
        # Deferred: this ran before the window was shown, so a screen reader's
        # own announcement of the new window arrived on top of it and the
        # important lines - files missing, audio did not start - were the ones
        # that got cut.
        wx.CallLater(500, self._announce_startup)
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

        paths = [s.filepath for s in self.board.slots
                 if s.filepath and not s.is_missing
                 and (s.duration or 0) <= C.PRELOAD_SECONDS]
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
        bits = [f"{C.APP_NAME} ready"]
        if self._loaded_demo:
            bits.append(f"demo pack loaded, {self.board.assigned_count} sounds "
                        "and beds. File, new board starts you from scratch")
        else:
            bits.append(f"{self.board.assigned_count} sounds loaded")
        missing = len(self.board.missing_slots)
        if missing:
            bits.append(f"{missing} files missing. Use File, relink missing sounds")
        if self.mixer.stream is None:
            bits.append(f"Audio could not start. {self.mixer.last_error or ''}")
        self.announce(". ".join(bits))

    # ------------------------------------------------------------------ ui ---
    def _tab_title(self, bank):
        """Nothing on the tab strip said which banks hold anything."""
        n = sum(1 for slot in self.board.bank_slots(bank) if slot.is_assigned)
        return "%d. %s (%d)" % (bank, C.BANK_TITLES[bank], n)

    def _on_bank_changed(self, event):
        bank = event.GetSelection() + 1
        if bank in C.BANK_TITLES:
            self.announce("%s. %s" % (C.BANK_TITLES[bank], C.BANK_HINTS[bank]))
        event.Skip()

    def _refresh_tab_titles(self):
        for bank in range(1, C.BANK_COUNT + 1):
            self.notebook.SetPageText(bank - 1, self._tab_title(bank))

    def _build_ui(self):
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        self.notebook = wx.Notebook(panel)
        self.notebook.SetName("Banks")
        self.pages = {}
        for bank in range(1, C.BANK_COUNT + 1):
            page = BankPage(self.notebook, self, bank)
            self.notebook.AddPage(page, self._tab_title(bank))
            self.pages[bank] = page
        # Say which bank you landed in. The tab is a sibling of the page in the
        # accessibility tree, not an ancestor of the buttons, so a screen
        # reader announces the button and never the bank - and the button label
        # deliberately leaves the bank out because "the tab already said it".
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_bank_changed)
        outer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 6)

        stop = wx.Button(panel, ID_STOP_ALL, "Stop everything  (Escape)")
        stop.SetFont(stop.GetFont().Bold())
        stop.SetMinSize(wx.Size(-1, self.FromDIP(38)))
        stop.SetToolTip("Stop every sound and bed, with a short fade (Escape)")
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
        file_menu.Append(ID_SAVE_AS, "Save board &as...\tCtrl+Shift+S",
                         "Save this board to a file of its own")
        file_menu.Append(wx.ID_OPEN, "&Open board...\tCtrl+O", "Open a saved board")
        file_menu.Append(ID_IMPORT, "&Import an old soundboard bank...",
                         "Load a bank from The Tony Gebhard Show Soundboard")
        file_menu.Append(ID_DEMO, "Load the &demo pack",
                         "The twenty sounds and twenty beds that ship with the app")
        file_menu.AppendSeparator()
        file_menu.Append(ID_RELINK, "&Relink missing sounds...",
                         "Find moved files and point the board at them")
        file_menu.Append(ID_SETTINGS, "Audio se&ttings...\tCtrl+P",
                         "Output device and ducking")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4")
        bar.Append(file_menu, "&File")

        sounds = wx.Menu()
        sounds.Append(ID_ASSIGN, "&Assign a sound file...", "Put a sound in this slot")
        sounds.Append(ID_RENAME, "Re&name\tF4", "Rename the sound you are on")
        sounds.Append(ID_TRIM, "&Level for this sound...", "Trim one slot on its own")
        sounds.Append(ID_HOTKEY, "Assign a &hotkey...", "Bank four only")
        sounds.Append(ID_GLOBAL_HOTKEY, "Assign a &global hotkey...",
                      "A key that fires this sound even when another window "
                      "has focus")
        sounds.Append(ID_LOOP, "Toggle &looping", "Bank three only")
        sounds.Append(ID_CLEAR_FOCUSED, "&Clear this slot\tDel")
        sounds.AppendSeparator()
        sounds.Append(ID_SEARCH, "&Search sounds...\tCtrl+E", "Find a sound by name")
        sounds.Append(ID_WHATS_PLAYING, "&What is playing\tCtrl+L")
        sounds.Append(ID_DUCK, "&Ducking on or off\tCtrl+D")
        sounds.Append(ID_STOP_ALL, "Stop &everything\tEscape")
        sounds.AppendSeparator()
        # A check item, so the menu itself says whether global hotkeys are
        # armed. While they are on, this app owns those combinations across the
        # whole machine, so "is it on right now" has to be answerable without
        # pressing anything.
        self.global_item = sounds.AppendCheckItem(
            ID_GLOBAL_TOGGLE, "&Global hotkeys\tCtrl+G",
            "Let assigned hotkeys fire this board from any program")
        bar.Append(sounds, "&Sounds")

        help_menu = wx.Menu()
        help_menu.Append(ID_SHORTCUTS, "&Keyboard shortcuts\tF1")
        help_menu.Append(ID_CHECK_UPDATES, "Check for &updates")
        help_menu.Append(wx.ID_ABOUT, "&About")
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
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("rename"), id=ID_RENAME)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("trim"), id=ID_TRIM)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("hotkey"), id=ID_HOTKEY)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("loop"), id=ID_LOOP)
        self.Bind(wx.EVT_MENU, lambda _e: self._focused_action("clear"), id=ID_CLEAR_FOCUSED)
        self.Bind(wx.EVT_MENU, self._on_search, id=ID_SEARCH)
        self.Bind(wx.EVT_MENU, self._on_whats_playing, id=ID_WHATS_PLAYING)
        self.Bind(wx.EVT_MENU, self._on_toggle_duck, id=ID_DUCK)
        self.Bind(wx.EVT_MENU, lambda _e: self.stop_all(), id=ID_STOP_ALL)
        self.Bind(wx.EVT_MENU, self._on_shortcuts, id=ID_SHORTCUTS)
        self.Bind(wx.EVT_MENU, self._on_about, id=wx.ID_ABOUT)

        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("sfx", -1), id=ID_VOL_SFX_DOWN)
        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("sfx", +1), id=ID_VOL_SFX_UP)
        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("bed", -1), id=ID_VOL_BED_DOWN)
        self.Bind(wx.EVT_MENU, lambda _e: self._nudge("bed", +1), id=ID_VOL_BED_UP)

    def _build_accelerators(self):
        """The whole keyboard map, rebuilt whenever a custom hotkey changes."""
        entries = [
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F2, ID_VOL_SFX_DOWN),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F3, ID_VOL_SFX_UP),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F5, ID_VOL_BED_DOWN),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F6, ID_VOL_BED_UP),
            # Ctrl+G is a new key, not one taken from the frozen map.
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("G"), ID_GLOBAL_TOGGLE),
        ]
        for modifiers, key_code, index in fixed_accelerators():
            entries.append(wx.AcceleratorEntry(modifiers or wx.ACCEL_NORMAL,
                                               key_code, ID_SLOT_BASE + index))
        for slot in self.board.bank_slots(C.BANK_MISC):
            if slot.key_code:
                entries.append(wx.AcceleratorEntry(slot.modifiers or wx.ACCEL_NORMAL,
                                                   slot.key_code,
                                                   ID_SLOT_BASE + slot.index))
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

        self.Bind(wx.EVT_MENU, self._on_slot_hotkey,
                  id=ID_SLOT_BASE, id2=ID_SLOT_BASE + C.TOTAL_SLOTS)

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
            self.announce("Global hotkey %s for %s."
                          % (text, slot.display_name) if text
                          else "Global hotkey removed from %s." % slot.display_name)
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
        self.announce("Checking for a new version.")

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
        if available and info:
            self._offer_update(info)
        else:
            self.announce(message or "You have the newest version.")

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
        text = "Version %s of %s is available. You have %s." % (
            version, C.APP_NAME, C.APP_VERSION)
        if notes:
            text += "\n\n" + notes
        text += "\n\nDownload and install it now?"
        if wx.MessageBox(text, "Update available",
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            self.announce("Update skipped. Help, check for updates when you "
                          "are ready.")
            return
        # On a worker thread. This is an HTTPS download of a 40 MB installer;
        # inline it froze the window with only a busy cursor for company.
        import threading
        self.announce("Downloading. This may take a moment.")
        wx.BeginBusyCursor()

        def work():
            try:
                got = appupdate.download(info)
            except Exception as exc:
                got = (None, "Download failed. %s" % exc)
            wx.CallAfter(self._download_done, *got)

        threading.Thread(target=work, daemon=True, name="dropdeck-dl").start()

    def _download_done(self, path, message):
        from . import appupdate
        wx.EndBusyCursor()
        if not path:
            self.announce(message)
            wx.MessageBox(message, "Update failed", wx.OK | wx.ICON_WARNING, self)
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

    # -------------------------------------------------------------- speaking --
    def announce_playback(self, text):
        """A confirmation for something the user can already hear.

        Speech here is optional, because the sound itself is the feedback.
        The status bar is written either way, so the information is still
        on screen and still reachable - only the interruption is optional.

        Failures never come through here. "File missing" and "could not
        play" are exactly the cases you cannot hear, so they always speak.
        """
        if getattr(self.board, "announce_playback", True):
            self.speaker.say(text)
        self.status.SetStatusText(text, 1)

    def announce(self, text):
        self.speaker.say(text)
        # A status bar cannot show a sentence and these are sentences, so the
        # field was reweighted to take most of the bar. No tooltip is set here:
        # wxSTB_SHOW_TIPS is on by default and shows the full text on hover
        # whenever a field is truncated, and setting one manually asserts.
        self.status.SetStatusText(text, 1)

    def _update_status(self):
        self.status.SetStatusText(
            f"Sound {percent(self.mixer.sfx_gain)} (F2, F3)   "
            f"Beds {percent(self.mixer.bed_gain)} (F5, F6)   "
            f"Ducking {'on' if self.mixer.ducking else 'off'} (Ctrl+D)", 0)

    # ------------------------------------------------------------ transport --
    def trigger(self, index):
        """Fire a slot. This is what every hotkey and every button ends up at."""
        if not 0 <= index < C.TOTAL_SLOTS:
            return
        slot = self.board[index]

        if not slot.is_assigned:
            self.assign_sound(slot)
            return
        if slot.is_missing:
            self.announce(f"{slot.display_name}, file missing. "
                          "Use File, relink missing sounds")
            return

        if slot.is_bed:
            if self.mixer.is_playing(index):
                self.mixer.stop_slot(index)
                self.announce_playback(f"Stopped bed, {slot.display_name}")
                self._sync_button(slot, playing=False)
                return
            voice = self.mixer.play(index, slot.filepath, is_bed=True,
                                   loop=slot.loop, trim_db=slot.trim_db,
                                   name=slot.display_name, duration=slot.duration)
            if voice is None:
                self.announce(f"Could not play {slot.display_name}")
                return
            tail = " looping" if slot.loop else ""
            self.announce_playback(f"Playing bed, {slot.display_name}{tail}")
            self._sync_button(slot, playing=True)
            return

        voice = self.mixer.play(index, slot.filepath, is_bed=False, loop=False,
                                trim_db=slot.trim_db, name=slot.display_name,
                                duration=slot.duration)
        if voice is None:
            self.announce(f"Could not play {slot.display_name}")
            return
        length = format_duration(slot.duration)
        self.announce_playback(
            f"{slot.display_name}{', ' + length if length else ''}")

    def stop_all(self):
        count = self.mixer.stop_all()
        self.announce("Everything stopped" if count else "Nothing was playing")

    # -------------------------------------------------------------- volumes --
    def _nudge(self, which, direction):
        step = C.VOLUME_STEP * direction
        if which == "sfx":
            self.mixer.set_sfx_gain(self.mixer.sfx_gain + step)
            self.board.sfx_volume = self.mixer.sfx_gain
            self.announce(f"Sound volume {percent(self.mixer.sfx_gain)}")
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
        indices = self.mixer.playing_slots()
        if not indices:
            self.announce("Nothing is playing")
            return
        names = ", ".join(self.board[i].display_name for i in indices)
        self.announce(f"{len(indices)} playing. {names}")

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

    def _focused_action(self, action):
        slot = self._focused_slot()
        if slot is None:
            self.announce("Move to a sound button first")
            return
        {"assign": self.assign_sound, "rename": self.rename_slot,
         "trim": self.trim_slot, "hotkey": self.assign_hotkey,
         "loop": self.toggle_loop, "clear": self.clear_slot}[action](slot)

    def assign_sound(self, slot):
        path = audio_file_dialog(self, self.board.last_sound_dir,
                                 f"Choose a sound for {slot.bank_short} {slot.number}")
        if not path:
            self.announce("Nothing chosen")
            return
        self._apply_file(slot, path)

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
        self.announce(f"{slot.display_name} assigned to {slot.bank_short} {slot.number}")
        self._touch()

    def rename_slot(self, slot):
        if not slot.is_assigned:
            self.announce("That slot is empty")
            return
        with wx.TextEntryDialog(self, "Name for this sound",
                                "Rename", slot.display_name) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.GetValue().strip()
        if not name:
            return
        slot.name = name
        self._sync_button(slot)
        self.announce(f"Renamed to {name}")
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
        self.announce(f"{slot.display_name} level {slot.trim_db:+.0f} decibels")
        self._touch()

    def toggle_loop(self, slot):
        if not slot.is_bed:
            self.announce("Looping is for the music beds in bank three")
            return
        slot.loop = not slot.loop
        self._sync_button(slot)
        self.announce(f"Loop {'on' if slot.loop else 'off'} for {slot.display_name}")
        self._touch()

    def clear_slot(self, slot):
        if not slot.is_assigned:
            self.announce("That slot is already empty")
            return
        name = slot.display_name
        if wx.MessageBox(f"Clear {name} from {slot.bank_short} {slot.number}?",
                         "Clear slot", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        self.mixer.stop_slot(slot.index, fade_out=0.05)
        slot.clear()
        self._sync_button(slot, playing=False)
        self.announce(f"{name} cleared")
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
        self.announce(f"Hotkey {label or 'cleared'} for {slot.display_name}")
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
        if slot.is_assigned:
            menu.Append(ID_RENAME, "Re&name...\tF4")
            menu.Append(ID_TRIM, f"&Level... (now {slot.trim_db:+.0f} decibels)")
        if slot.is_bed:
            item = menu.AppendCheckItem(ID_LOOP, "&Loop this bed")
            item.Check(bool(slot.loop))
        if slot.bank == C.BANK_MISC:
            menu.Append(ID_HOTKEY,
                        f"&Hotkey... (now {slot.custom_hotkey or 'none'})")
        if slot.is_assigned:
            menu.AppendSeparator()
            menu.Append(ID_CLEAR_FOCUSED, "&Clear slot")

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
            self.announce(f"Saved to {os.path.basename(saved)}")

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
        self.announce("New board, eighty empty slots")
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
        for bank in range(1, C.BANK_COUNT + 1):
            for button, slot in zip(self.pages[bank].buttons,
                                    board.bank_slots(bank)):
                button.slot = slot
                button.refresh(False)
        self._playing = set()
        self._build_accelerators()
        self._update_status()

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
        missing = self.board.missing_slots
        if not missing:
            self.announce("Nothing is missing")
            wx.MessageBox("Every sound on this board was found.", "Nothing to relink",
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        with wx.DirDialog(self, f"Where should I look for the {len(missing)} "
                          "missing sounds?", style=wx.DD_DIR_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            folder = dialog.GetPath()

        import threading
        self.announce("Looking through %s. This may take a moment." % folder)
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
            self._relink_finished(result.get("repaired") or [],
                                  len(missing))

        threading.Thread(target=work, daemon=True, name="dropdeck-relink").start()

    def _relink_finished(self, repaired, asked):
        for slot in repaired:
            self._sync_button(slot)
        still = len(self.board.missing_slots)
        self.announce(f"Relinked {len(repaired)} of {asked}. "
                      f"{still} still missing" if still
                      else f"Relinked all {len(repaired)}")
        if repaired:
            self._touch()

    def _on_settings(self, _event):
        with SettingsDialog(self, self.board, self.mixer) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            index, name, hostapi = dialog.chosen_device
            bank_devices = dialog.chosen_bank_devices
            self.board.ducking = dialog.duck_on.GetValue()
            self.board.duck_db = float(dialog.duck_db.GetValue())
            self.board.announce_playback = dialog.announce_playback.GetValue()

        self.mixer.ducking = self.board.ducking
        self.mixer.duck_db = self.board.duck_db

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
                self.announce(self._routing_summary())
        else:
            self.warm_cache()
            self.announce("Audio settings saved")
        self._update_status()
        self._touch()

    def _routing_summary(self):
        """What the outputs are now, in one spoken sentence."""
        extra = self.board.bank_devices or {}
        if not extra:
            return f"Everything playing through {describe_device(self.mixer.device)}"
        parts = [f"{C.BANK_TITLES[bank]} through {spec['name']}"
                 for bank, spec in sorted(extra.items())]
        return (f"Main output {describe_device(self.mixer.device)}. "
                + ". ".join(parts))

    # --------------------------------------------------------------- search --
    def _on_search(self, _event):
        if self.board.assigned_count == 0:
            self.announce("There are no sounds to search yet")
            return
        with SearchDialog(self, self.board, self.mixer.playing_slots()) as dialog:
            if dialog.ShowModal() != wx.ID_OK or dialog.chosen is None:
                return
            slot, play_now = dialog.chosen, dialog.play_now
        self.notebook.SetSelection(slot.bank - 1)
        button = self._button_for(slot)
        button.SetFocus()
        if play_now:
            self.trigger(slot.index)
        else:
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
        now = set(self.mixer.playing_slots())
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
        self._closing.set()
        if self._warm_thread is not None:
            self._warm_thread.join(timeout=3.0)
            self._warm_thread = None

    def Destroy(self):
        self.stop_background_work()
        return super().Destroy()

    def _on_close(self, event):
        self._refresh_timer.Stop()
        self._save_timer.Stop()
        self.stop_background_work()
        # Give every global combination back to the rest of the system.
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        try:
            self.board.save()
        except Exception:
            pass
        self.mixer.close()
        event.Skip()
