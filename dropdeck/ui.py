"""The window.

Four tabs, twenty buttons each, and a keyboard map that has not changed since
the app this one replaces. Everything you can do with the mouse has a key, and
everything that happens says so out loud.
"""

from __future__ import annotations

import os

import wx

from . import constants as C
from .board import Board, default_board_path, demo_board_path
from .dialogs import (AssignHotkeyDialog, SearchDialog, SettingsDialog,
                      TrimDialog, audio_file_dialog, key_label)
from .engine import probe
from .mixer import Mixer, describe_device, output_devices
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


class SoundButton(wx.Button):
    """One slot. Its label is the whole story, which is what a screen reader
    reads when you land on it."""

    def __init__(self, parent, slot, frame):
        super().__init__(parent, label=slot.button_label())
        self.slot = slot
        self.frame = frame
        self._last_label = self.GetLabel()
        self.Bind(wx.EVT_BUTTON, self._on_activate)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)

    def refresh(self, playing=False):
        label = self.slot.button_label(playing)
        if label != self._last_label:
            self._last_label = label
            self.SetLabel(label)

    def _on_activate(self, _event):
        self.frame.trigger(self.slot.index)

    def _on_context_menu(self, _event):
        self.frame.show_slot_menu(self.slot, self)


class BankPage(wx.Panel):
    """Twenty buttons and a line telling you what the keys are."""

    def __init__(self, parent, frame, bank):
        super().__init__(parent)
        self.bank = bank
        outer = wx.BoxSizer(wx.VERTICAL)

        hint = wx.StaticText(self, label=C.BANK_HINTS[bank])
        outer.Add(hint, 0, wx.ALL, 8)

        grid = wx.GridSizer(rows=5, cols=4, gap=wx.Size(6, 6))
        self.buttons = []
        for slot in frame.board.bank_slots(bank):
            button = SoundButton(self, slot, frame)
            self.buttons.append(button)
            grid.Add(button, 0, wx.EXPAND)
        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(outer)


class DropDeckFrame(wx.Frame):
    def __init__(self, parent=None):
        super().__init__(parent, title=C.APP_NAME, size=(1000, 700))

        self.speaker = Speaker()
        self._context_slot = None
        self._loaded_demo = False
        self.board = self._load_startup_board()
        self.mixer = Mixer(device=self._resolve_device(), open_stream=True,
                           samplerate=None)
        self.mixer.set_sfx_gain(self.board.sfx_volume)
        self.mixer.set_bed_gain(self.board.bed_volume)
        self.mixer.ducking = self.board.ducking
        self.mixer.duck_db = self.board.duck_db

        self._build_menu()
        self._build_ui()
        self._build_accelerators()

        self._playing = set()
        self._refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_refresh_tick, self._refresh_timer)
        self._refresh_timer.Start(250)

        self._save_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self._save(quiet=True), self._save_timer)

        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Centre()
        self._announce_startup()

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
        if not self.board.device_name:
            return None
        for dev in output_devices():
            if (dev["name"] == self.board.device_name
                    and dev["hostapi"] == self.board.device_hostapi):
                return dev["index"]
        return None

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
    def _build_ui(self):
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        self.notebook = wx.Notebook(panel)
        self.notebook.SetName("Banks")
        self.pages = {}
        for bank in range(1, C.BANK_COUNT + 1):
            page = BankPage(self.notebook, self, bank)
            self.notebook.AddPage(page, f"{bank}. {C.BANK_TITLES[bank]}")
            self.pages[bank] = page
        outer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 6)

        stop = wx.Button(panel, ID_STOP_ALL, "Stop everything  (Escape)")
        stop.Bind(wx.EVT_BUTTON, lambda _e: self.stop_all())
        outer.Add(stop, 0, wx.EXPAND | wx.ALL, 6)

        panel.SetSizer(outer)

        self.status = self.CreateStatusBar(2)
        self.status.SetStatusWidths([-3, -2])
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
        sounds.Append(ID_LOOP, "Toggle &looping", "Bank three only")
        sounds.Append(ID_CLEAR_FOCUSED, "&Clear this slot\tDel")
        sounds.AppendSeparator()
        sounds.Append(ID_SEARCH, "&Search sounds...\tCtrl+E", "Find a sound by name")
        sounds.Append(ID_WHATS_PLAYING, "&What is playing\tCtrl+L")
        sounds.Append(ID_DUCK, "&Ducking on or off\tCtrl+D")
        sounds.Append(ID_STOP_ALL, "Stop &everything\tEscape")
        bar.Append(sounds, "&Sounds")

        help_menu = wx.Menu()
        help_menu.Append(ID_SHORTCUTS, "&Keyboard shortcuts\tF1")
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

    # -------------------------------------------------------------- speaking --
    def announce(self, text):
        self.speaker.say(text)
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
                self.announce(f"Stopped bed, {slot.display_name}")
                self._sync_button(slot, playing=False)
                return
            voice = self.mixer.play(index, slot.filepath, is_bed=True,
                                   loop=slot.loop, trim_db=slot.trim_db,
                                   name=slot.display_name, duration=slot.duration)
            if voice is None:
                self.announce(f"Could not play {slot.display_name}")
                return
            tail = " looping" if slot.loop else ""
            self.announce(f"Playing bed, {slot.display_name}{tail}")
            self._sync_button(slot, playing=True)
            return

        voice = self.mixer.play(index, slot.filepath, is_bed=False, loop=False,
                                trim_db=slot.trim_db, name=slot.display_name,
                                duration=slot.duration)
        if voice is None:
            self.announce(f"Could not play {slot.display_name}")
            return
        length = format_duration(slot.duration)
        self.announce(f"{slot.display_name}{', ' + length if length else ''}")

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

    def show_slot_menu(self, slot, button):
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
            menu.Append(ID_LOOP, f"Looping is {'on' if slot.loop else 'off'}")
        if slot.bank == C.BANK_MISC:
            menu.Append(ID_HOTKEY,
                        f"&Hotkey... (now {slot.custom_hotkey or 'none'})")
        if slot.is_assigned:
            menu.AppendSeparator()
            menu.Append(ID_CLEAR_FOCUSED, "&Clear slot")

        self._context_slot = slot
        try:
            button.PopupMenu(menu)
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

        wx.BeginBusyCursor()
        try:
            repaired = self.board.relink(folder)
        finally:
            wx.EndBusyCursor()

        for slot in repaired:
            self._sync_button(slot)
        still = len(self.board.missing_slots)
        self.announce(f"Relinked {len(repaired)} of {len(missing)}. "
                      f"{still} still missing" if still
                      else f"Relinked all {len(repaired)}")
        if repaired:
            self._touch()

    def _on_settings(self, _event):
        with SettingsDialog(self, self.board, self.mixer) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            index, name, hostapi = dialog.chosen_device
            self.board.ducking = dialog.duck_on.GetValue()
            self.board.duck_db = float(dialog.duck_db.GetValue())

        self.mixer.ducking = self.board.ducking
        self.mixer.duck_db = self.board.duck_db
        if (name, hostapi) != (self.board.device_name, self.board.device_hostapi):
            self.board.device_name = name
            self.board.device_hostapi = hostapi
            if self.mixer.set_device(index):
                self.announce(f"Now playing through {describe_device(index)}")
            else:
                self.announce(f"That device would not open. {self.mixer.last_error}")
                wx.MessageBox(f"That output could not be opened.\n\n"
                              f"{self.mixer.last_error}\n\nFalling back to the "
                              "system default.", "Device not available",
                              wx.OK | wx.ICON_WARNING, self)
                self.board.device_name = self.board.device_hostapi = None
                self.mixer.set_device(None)
        else:
            self.announce("Audio settings saved")
        self._update_status()
        self._touch()

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
        text = wx.TextCtrl(dialog, value=C.KEYBOARD_HELP,
                           style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        text.SetName("Keyboard shortcuts")
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

    def _on_close(self, event):
        self._refresh_timer.Stop()
        self._save_timer.Stop()
        try:
            self.board.save()
        except Exception:
            pass
        self.mixer.close()
        event.Skip()
