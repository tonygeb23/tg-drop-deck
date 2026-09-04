"""The playlist view: a running order you can paste into.

A ``wx.ListCtrl`` in report view, with real check boxes turned on. It was a
``wx.CheckListBox`` until September 2026 and that was the wrong control, for
one reason that mattered more than everything else about it: on Windows a
wxCheckListBox is an owner drawn list box with a tick painted on it, and MSAA
has no idea the tick is there. So a screen reader read every row and never
said whether the item was checked, and pressing Space said nothing at all.

Brian Hartgen: "The most critical issue is that a screen-reader does not
announce whether an item is checked or not... Noone can move forward with this
part of the app unless they know this information so it's a bit of a
deal-breaker."

A list view with ``EnableCheckBoxes`` is a native SysListView32 with real
check boxes in it, which every screen reader on Windows has read for twenty
years. It brings three more things with it:

- **Columns.** Title, artist, kind, length, start time and crossfade, each one
  a cell a screen reader can read on its own, instead of one comma separated
  sentence per row.
- **Enter.** A list box on a frame never sees Return: the dialog message loop
  takes it first, which is why Enter did nothing here. A list view raises
  ``wxEVT_LIST_ITEM_ACTIVATED`` for it.
- **First letter navigation.** Which works on the first column, and is why
  the running order number is no longer glued to the front of every row.

**The rows still never say "playing".** They carry the running order and none
of it changes while the show is on. Rewriting the row that has focus would
restart a screen reader mid sentence at exactly the moment a song changes,
which is the trap ``SoundButton.refresh`` exists to avoid. What is on air is
*spoken* when it changes, ``Ctrl+L`` answers it on demand, and Ctrl+Shift+L
takes you to it.
"""

from __future__ import annotations

import os

import wx

from . import constants as C
from .dialogs import name_field
from . import m3u
from .plids import (ID_PL_ROW_ADD, ID_PL_ROW_DOWN, ID_PL_ROW_DROP,
                    ID_PL_ROW_FADE, ID_PL_ROW_PLAY, ID_PL_ROW_RANDOM,
                    ID_PL_ROW_REMOVE, ID_PL_ROW_SEGUE, ID_PL_ROW_STOP,
                    ID_PL_ROW_TICK, ID_PL_ROW_TO_LIBRARY, ID_PL_ROW_UP)
from .slot import format_duration

#: What the list shows when there is nothing in it. A row, not an empty
#: control: a list box with no items reads as nothing at all.
EMPTY_ROW = "Empty. Paste songs with Ctrl+V, or use Add files"

#: The columns, and how wide each one starts. The title is first because that
#: is what first letter navigation searches, and because it is the thing
#: anybody is looking for when they go hunting in a three hour running order.
COLUMNS = (("Title", 260), ("Artist", 180), ("Kind", 90), ("Length", 100),
           ("Starts", 110), ("Crossfade", 100))


class _Dropped(wx.FileDropTarget):
    """Files dragged onto the list from Explorer."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def OnDropFiles(self, x, y, filenames):
        self.panel.add_paths(list(filenames), where="dropped")
        return True


class PlaylistPanel(wx.Panel):
    """The running order, its buttons, and the keys that work inside it."""

    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        #: Set while Space is being handled. A list view raises ITEM_ACTIVATED
        #: for Space as well as for Return once check boxes are on, and one
        #: keypress must not both tick a track and put it on the air.
        self._space_pressed = False
        #: Set while the ticks are being written FROM the model. CheckItem
        #: raises the same event a keypress does, and treating that as the
        #: user having ticked something means every refresh writes the status
        #: bar and marks the board unsaved. Worse, the first refresh happens
        #: while the frame is still being built and has no status bar yet.
        self._syncing = False

        outer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(self, label=(
            "Paste files here with Ctrl+V, or drag them in - as many at "
            "once as you like. Each song hands over to the next before "
            "it ends.\n"
            "Space ticks or unticks a track: unticked stays in the list "
            "and is skipped. Enter plays from the one you are on.\n"
            "Delete removes it. Alt+Up and Alt+Down move it. "
            "Ctrl+Shift+L goes to whatever is on air."))
        outer.Add(intro, 0, wx.ALL, 8)

        # A real label in front of the control: on MSW the accessible name of
        # a list comes from the static before it, not from SetName alone.
        outer.Add(wx.StaticText(self, label="&Running order"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES)
        self.list.SetName("Running order")
        for index, (heading, width) in enumerate(COLUMNS):
            self.list.InsertColumn(index, heading, width=self.FromDIP(width))
        # Real check boxes, which is the whole reason this is a list view.
        # Space toggles one and Windows announces it, with no help from here.
        self.list.EnableCheckBoxes(True)
        outer.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)

        # The crossfade lives HERE, next to the running order it applies to,
        # rather than only in a menu. It is the number people reach for most
        # while building a show and the one they want to hear change.
        fade_row = wx.BoxSizer(wx.HORIZONTAL)
        fade_row.Add(wx.StaticText(self, label="&Crossfade, seconds"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.crossfade = wx.SpinCtrlDouble(
            self, min=0.0, max=C.MAX_CROSSFADE, inc=0.5,
            initial=float(self.playlist.crossfade),
            style=wx.SP_ARROW_KEYS | wx.TE_PROCESS_ENTER)
        self.crossfade.SetDigits(1)
        name_field(self.crossfade, "Crossfade between tracks, seconds")
        self.crossfade.SetToolTip(
            "How long one song overlaps the next. Type a number or use the "
            "arrow keys. Zero means each one plays right out before the next "
            "starts. A track can be given a crossfade of its own from its "
            "right-click menu.")
        fade_row.Add(self.crossfade, 0)
        outer.Add(fade_row, 0, wx.LEFT | wx.RIGHT, 8)

        # What the number actually does, in words, next to it. A spin box
        # labelled "Crossfade, seconds" tells somebody the units and nothing
        # about what happens - and this is the one number in the app that
        # changes where every other item in the list starts.
        outer.Add(wx.StaticText(self, label=(
            "How long one song overlaps the next. The next song starts this "
            "many seconds before\n"
            "the one playing ends, so every start time in the list moves when "
            "you change it.\n"
            "Type a value or use the arrow keys. Zero means each song plays "
            "right out first. A single\n"
            "track can have its own from its right-click menu, and this box "
            "is in Preferences too.")),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.summary = wx.StaticText(self, label="")
        outer.Add(self.summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler, tip in (
                ("&Play from here", self._on_play,
                 "Start the playlist at the item you are on"),
                ("S&top playlist", self._on_stop,
                 "Take the playlist off the air. Sounds and beds keep playing"),
                ("&Add files...", self._on_add, "Choose songs to put at the end"),
                ("&Insert a drop...", self._on_drop,
                 "Put a drop in front of the item you are on"),
                ("&Remove", self._on_remove, "Take this item out of the order")):
            button = wx.Button(self, label=label)
            button.SetToolTip(tip)
            button.Bind(wx.EVT_BUTTON, handler)
            row.Add(button, 0, wx.RIGHT, 6)
        outer.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(outer)

        # Enter and a double click both land on ITEM_ACTIVATED. So does Space
        # once check boxes are on, which _on_activated has to allow for.
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activated)
        self.list.Bind(wx.EVT_LIST_ITEM_CHECKED, self._on_ticked)
        self.list.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._on_ticked)
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.list.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.crossfade.Bind(wx.EVT_SPINCTRLDOUBLE, self._on_crossfade)
        self.crossfade.Bind(wx.EVT_TEXT_ENTER, self._on_crossfade)
        self.crossfade.Bind(wx.EVT_KILL_FOCUS, self._on_crossfade_leave)
        # BOTH, because the list covers nearly all of the panel and a child
        # window without a drop target of its own simply refuses the drop -
        # so "drag them in" worked everywhere except the obvious place.
        self.SetDropTarget(_Dropped(self))
        self.list.SetDropTarget(_Dropped(self))

        self.refresh()

    # ------------------------------------------------------------- helpers --
    @property
    def playlist(self):
        return self.frame.board.playlist

    @property
    def player(self):
        return self.frame.player

    @property
    def is_empty(self):
        return not len(self.playlist)

    def selection(self):
        """Which track the user is on, or None.

        None while the list is empty, because the single row showing then is
        the word "Empty" and not a track. Focus rather than selection: with
        the arrow keys they are the same thing, and after a rebuild focus is
        the one that survives.
        """
        if self.is_empty:
            return None
        index = self.list.GetFirstSelected()
        if index == wx.NOT_FOUND:
            index = self.list.GetFocusedItem()
        return None if index == wx.NOT_FOUND else index

    def select(self, index):
        """Put the cursor on a row, both halves of it."""
        if not (0 <= index < self.list.GetItemCount()):
            return
        self.list.Select(index)
        self.list.Focus(index)
        self.list.EnsureVisible(index)

    def row_count(self):
        """How many rows the control is showing, empty message included."""
        return self.list.GetItemCount()

    def row_text(self, index):
        """One row's cells, joined. What the row amounts to, in one string."""
        if not (0 <= index < self.list.GetItemCount()):
            return ""
        cells = [self.list.GetItemText(index, column)
                 for column in range(len(COLUMNS))]
        return ", ".join(c for c in cells if c)

    def cell(self, index, column):
        """One cell, by column number. COLUMNS says which is which."""
        if not (0 <= index < self.list.GetItemCount()):
            return ""
        return self.list.GetItemText(index, column)

    def is_ticked(self, index):
        """Is the box beside this row ticked."""
        if not (0 <= index < self.list.GetItemCount()):
            return False
        return bool(self.list.IsItemChecked(index))

    def focus_crossfade(self):
        """Put the user on the crossfade box, for the menu item that says so."""
        self.crossfade.SetFocus()

    def _on_crossfade(self, event=None):
        """The crossfade moved. Apply it, relabel the cues, say the number.

        Every row carries its cue and its start time, so all of them change
        when this does - which is exactly why the rows are rebuilt here and
        the control is left alone.
        """
        if event is not None:
            event.Skip()
        seconds = round(float(self.crossfade.GetValue()), 2)
        if abs(seconds - self.playlist.crossfade) < 1e-9:
            return
        self.playlist.crossfade = seconds
        self.refresh(keep=self.selection())
        self.frame.announce(
            "Crossfade %s" % (format_duration(seconds)
                              or "off, each song plays right out"))
        self.frame.playlist_changed(relabel=False)

    def _on_crossfade_leave(self, event):
        """Typed digits are only a value once something commits them.

        A spin control holds what you typed as text until it is asked. Leaving
        the box is asking: without this, typing 6 and tabbing away left the
        box reading 6 and the playlist still on 3.
        """
        event.Skip()
        self._on_crossfade(None)

    def focus_list(self):
        self.list.SetFocus()
        if self.list.GetItemCount() and self.selection() is None:
            self.select(0)

    # -------------------------------------------------------------- rows ----
    def _rows(self):
        playlist = self.playlist
        cues = playlist.cue_points()
        return [track.columns(playlist.crossfade, cue=cues[index])
                for index, track in enumerate(playlist)]

    def refresh(self, keep=None):
        """Bring every row up to date. The rows are text; nothing here speaks.

        Cells are written one at a time when the number of rows has not
        changed, and only where the text is actually different. That matters:
        deleting and rebuilding a list view moves focus and selection, and a
        screen reader reads the row again every time it does. The background
        pass that fills in artists and start times comes through here, and it
        must not read the list out from under somebody who is arrowing it.
        """
        rows = self._rows()
        previous = self.selection() if keep is None else keep
        if not rows:
            # One row saying so, rather than an empty control. Arrowing into a
            # list with nothing in it gives a screen reader nothing to read,
            # which sounds exactly like a list that failed to load.
            rows = [[EMPTY_ROW] + [""] * (len(COLUMNS) - 1)]
            previous = 0
        self._write_rows(rows)
        if previous is None or previous < 0 or previous >= len(rows):
            previous = len(rows) - 1
        self.select(max(0, previous))
        self._sync_crossfade_box()
        self._update_summary()

    def _write_rows(self, rows):
        """Put ``rows`` into the control, changing as little as possible."""
        count = self.list.GetItemCount()
        if count != len(rows):
            self.list.Freeze()
            try:
                self.list.DeleteAllItems()
                for index, cells in enumerate(rows):
                    self.list.InsertItem(index, cells[0])
                    for column in range(1, len(COLUMNS)):
                        self.list.SetItem(index, column, cells[column])
            finally:
                self.list.Thaw()
        else:
            for index, cells in enumerate(rows):
                for column in range(len(COLUMNS)):
                    if self.list.GetItemText(index, column) != cells[column]:
                        self.list.SetItem(index, column, cells[column])
        self._sync_ticks()

    def _sync_ticks(self):
        """The tick beside each row, from the model, without churning it.

        CheckItem raises a checked event, and one that arrives while the model
        is already correct is harmless but noisy, so nothing is written unless
        it differs.
        """
        self._syncing = True
        try:
            if self.is_empty:
                if self.list.GetItemCount() and self.list.IsItemChecked(0):
                    self.list.CheckItem(0, False)
                return
            for index, track in enumerate(self.playlist):
                if index >= self.list.GetItemCount():
                    break
                if self.list.IsItemChecked(index) != bool(track.enabled):
                    self.list.CheckItem(index, bool(track.enabled))
        finally:
            self._syncing = False

    def _sync_crossfade_box(self):
        # Loading a board brings its own crossfade with it.
        if abs(self.crossfade.GetValue() - self.playlist.crossfade) > 1e-9:
            self.crossfade.SetValue(float(self.playlist.crossfade))

    def _update_summary(self):
        playlist = self.playlist
        count = len(playlist)
        if not count:
            self.summary.SetLabel(
                "Nothing in the running order yet. Copy some files in "
                "Explorer and press Ctrl+V here.")
            return
        songs = sum(1 for t in playlist if not t.is_drop)
        drops = count - songs
        missing = len(playlist.missing)
        skipped = sum(1 for t in playlist if not t.enabled)
        bits = ["%d item%s" % (count, "" if count == 1 else "s"),
                "%d song%s" % (songs, "" if songs == 1 else "s")]
        if drops:
            bits.append("%d drop%s" % (drops, "" if drops == 1 else "s"))
        if skipped:
            # The length below counts only what is ticked, so say what is not.
            bits.append("%d unticked" % skipped)
        bits.append(format_duration(playlist.total_duration) or "no length known")
        bits.append("crossfade %s" % format_duration(playlist.crossfade)
                    if playlist.crossfade else "no crossfade")
        if missing:
            bits.append("%d file%s missing" % (missing, "" if missing == 1 else "s"))
        self.summary.SetLabel(".  ".join(bits))

    def describe(self):
        """One spoken sentence about the whole running order."""
        return self.summary.GetLabel()

    # --------------------------------------------------------------- input --
    def add_paths(self, paths, where="added", at=None):
        """Put files in, say what happened, and leave the list on the first.

        A playlist file among them is expanded rather than refused: dragging
        an M3U onto the running order means "put that show in", and there is
        no reading of it that means anything else.
        """
        playlists = [p for p in paths if m3u.is_playlist_file(p)]
        if playlists:
            return self.add_from_playlist_files(playlists, at=at)
        playable = self.playlist.playable(paths)
        if not playable:
            self.frame.announce(
                "Nothing there this app can play. It takes %s files."
                % C.AUDIO_FORMATS_SPOKEN)
            return []
        added = self.playlist.add(playable, at=at)
        first = at if at is not None else len(self.playlist) - len(added)
        self.refresh(keep=first)
        # Several at once is the normal case, not the exception: people select
        # a whole album in Explorer and paste the lot.
        self.frame.announce_help(
            "%d %s %s. %s" % (
                len(added), "track" if len(added) == 1 else "tracks", where,
                added[0].display_name if len(added) == 1
                else "First is %s, last is %s"
                % (added[0].display_name, added[-1].display_name)))
        self.frame.playlist_changed()
        return added

    def add_from_playlist_files(self, paths, at=None):
        """Put the contents of one or more M3U files in, at ``at``.

        Adds rather than replaces. Playlist menu, Open a running order, is the
        one that replaces; dropping a file onto a list has always meant add.
        """
        added = []
        for path in paths:
            entries, _crossfade = self.frame._read_playlist_file(path)
            if not entries:
                continue
            landed = self.playlist.add_entries(
                entries, at=None if at is None else at + len(added))
            added.extend(landed)
        if not added:
            self.frame.announce("Nothing in that playlist this app can play")
            return []
        first = at if at is not None else len(self.playlist) - len(added)
        self.refresh(keep=first)
        missing = sum(1 for t in added if t.is_missing)
        self.frame.announce_help(
            "%d %s added from the playlist%s"
            % (len(added), "track" if len(added) == 1 else "tracks",
               ". %d file%s missing" % (missing, "" if missing == 1 else "s")
               if missing else ""))
        self.frame.playlist_changed()
        return added

    def clipboard_paths(self):
        """Every path on the clipboard, however it got there.

        Explorer puts a file list on the clipboard - as many files as were
        selected - which is what a wx.FileDataObject reads, and pasting a whole
        album at once is the normal case rather than the exception. Text is
        accepted as well, because some file managers and every terminal copy a
        path as text, and somebody who has just copied a path does not care
        which of those happened.

        Its own method so it can be stood in for: Windows will not let an
        application put a real CF_HDROP on its own clipboard, so this is the
        one part of pasting a test cannot drive end to end.
        """
        if not wx.TheClipboard.Open():
            self.frame.announce("The clipboard would not open")
            return []
        try:
            files = wx.FileDataObject()
            if wx.TheClipboard.GetData(files) and files.GetFilenames():
                return list(files.GetFilenames())
            text = wx.TextDataObject()
            if wx.TheClipboard.GetData(text):
                return [line.strip().strip(chr(34))
                        for line in text.GetText().splitlines() if line.strip()]
        finally:
            wx.TheClipboard.Close()
        return []

    def paste(self):
        """Ctrl+V: whatever was copied in File Explorer."""
        paths = self.clipboard_paths()
        if not paths:
            self.frame.announce("There is nothing on the clipboard to paste")
            return []
        return self.add_paths(paths, where="pasted")

    def _on_ticked(self, event):
        """The tick changed. Move it into the model and leave the row alone.

        Nothing is spoken here. The control has already said "checked" or
        "not checked" - that is the entire point of using a list view - and
        saying "will be skipped" over the top of it is two announcements for
        one keystroke. It goes in the status bar, which every level shows.
        """
        event.Skip()
        if self._syncing:
            # Written from the model, not by the user. Putting it back into
            # the model would be a no-op; saying it out loud and marking the
            # board unsaved would not.
            return
        index = event.GetIndex()
        if self.is_empty:
            # The only row is the word Empty. Put its tick straight back.
            self.list.CheckItem(index, False)
            return
        track = self.playlist.set_enabled(index, self.list.IsItemChecked(index))
        if track is None:
            return
        self._update_summary()
        self.frame.note("%s %s" % (track.display_name,
                                   "will play" if track.enabled
                                   else "will be skipped"))
        self.frame.playlist_changed(relabel=False)

    def set_all_ticked(self, value):
        """Tick or untick everything, for a running order you want all of."""
        changed = self.playlist.set_all_enabled(value)
        if not changed:
            self.frame.announce("They are all %s already"
                                % ("ticked" if value else "unticked"))
            return 0
        self.refresh()
        self.frame.announce_help("%d %s" % (changed,
                                            "ticked" if value else "unticked"))
        self.frame.playlist_changed()
        return changed

    def _on_left_down(self, event):
        # A click can activate a row, and it must not be mistaken for the
        # activation Space produces. See _on_activated.
        self._space_pressed = False
        event.Skip()

    def _on_key(self, event):
        code = event.GetKeyCode()
        # Space toggles the tick natively, and ALSO raises ITEM_ACTIVATED on
        # a list view with check boxes. Remembering that the key was Space is
        # what stops one press both ticking a track and putting it on air.
        self._space_pressed = code == wx.WXK_SPACE
        if code == wx.WXK_DELETE:
            self.remove_selected()
            return
        if event.AltDown() and code in (wx.WXK_UP, wx.WXK_DOWN):
            self.move_selected(-1 if code == wx.WXK_UP else 1)
            return
        event.Skip()

    def _on_activated(self, event):
        """Enter, or a double click. Not Space, which only ticks."""
        if self._space_pressed:
            self._space_pressed = False
            return
        event.Skip()
        self._on_play(None)

    def _on_context_menu(self, event):
        """The Applications key, or a right-click, on a track.

        Everything the playlist can do to one item, in the menu people
        actually open. The same reasoning as the pads: a feature that lives
        only behind a keystroke is a feature most users never find.
        """
        menu = wx.Menu()
        index = self.selection()
        track = self.playlist[index] if index is not None else None

        if track is not None:
            menu.Append(ID_PL_ROW_PLAY, "&Play from here	Enter")
            # Tony's "play this and fade out what is on": a segue, done by
            # hand, at the crossfade length rather than as a hard cut.
            if self.player.playing:
                menu.Append(ID_PL_ROW_SEGUE,
                            "&Segue to this now, fading out what is on")
            item = menu.AppendCheckItem(
                ID_PL_ROW_TICK, "&Ticked to play	Space")
            item.Check(bool(track.enabled))
            menu.AppendSeparator()
            menu.Append(ID_PL_ROW_UP, "Move &up	Alt+Up")
            menu.Append(ID_PL_ROW_DOWN, "Move &down	Alt+Down")
            menu.Append(ID_PL_ROW_FADE,
                        "&Crossfade out of this one... (now %s)"
                        % (format_duration(
                            track.crossfade_seconds(self.playlist.crossfade))
                           or "none"))
            menu.Append(ID_PL_ROW_RANDOM,
                        "Insert a &random drop from the library\tAlt+D")
            menu.Append(ID_PL_ROW_DROP, "&Insert a drop before this...")
            if track.is_drop:
                menu.Append(ID_PL_ROW_TO_LIBRARY,
                            "Add this drop to the &library")
            menu.AppendSeparator()
            menu.Append(ID_PL_ROW_REMOVE, "&Remove from the running order	Del")
            menu.AppendSeparator()

        menu.Append(ID_PL_ROW_ADD, "&Add files to the end...")
        if self.player.playing:
            menu.Append(ID_PL_ROW_STOP, "S&top the playlist")

        position = event.GetPosition()
        if position == wx.DefaultPosition or tuple(position) == (-1, -1):
            # The Applications key gives no position, and wx then falls back
            # to wherever the mouse was last left - possibly another monitor.
            size = self.list.GetSize()
            position = self.list.ClientToScreen(wx.Point(size.x // 3, 20))
        self.list.PopupMenu(menu, self.list.ScreenToClient(position))
        menu.Destroy()

    def toggle_selected(self):
        """Tick or untick the row, for the menu. Space does it in the control."""
        index = self.selection()
        if index is None:
            return
        track = self.playlist.set_enabled(index, not self.playlist[index].enabled)
        # Written to the control, which raises the checked event, which is
        # what puts it in the status bar and updates the summary.
        self.list.CheckItem(index, bool(track.enabled))
        self.frame.announce_help(
            "%s %s" % (track.display_name,
                       "will play" if track.enabled else "will be skipped"))

    def crossfade_selected(self):
        """Give one track a crossfade of its own, or put it back on the
        playlist's."""
        index = self.selection()
        if index is None:
            self.frame.announce("There is nothing in the running order yet")
            return
        self.frame.set_track_crossfade(index)

    def segue_to_selected(self):
        """Bring this track up and take the one on air down under it."""
        index = self.selection()
        if index is None:
            self.frame.announce("There is nothing in the running order yet")
            return
        self.frame.segue_playlist(index)

    def go_to_playing(self):
        """Put the cursor on whatever is on the air.

        Brian Hartgen: "when a song is playing midway through the list, we do
        not know which song that is. There is no way of telling from the
        window title or by pressing a key to focus upon the song that is
        playing."
        """
        if not self.player.playing or self.player.current is None:
            # An answer, not a comment, so it is said at every speech level.
            # A key that is only ever a question has to reply to it.
            self.frame.announce_answer("The playlist is not playing")
            return False
        index = self.player.index
        if not (0 <= index < self.list.GetItemCount()):
            return False
        already = (self.selection() == index
                   and self.list.HasFocus())
        self.frame.show_view_playlist()
        self.list.SetFocus()
        self.select(index)
        if already:
            # Moving the cursor is the answer, because a screen reader reads
            # the row it lands on. Standing on it already is not, so say it.
            self.frame.announce_answer(
                "Already on it. %s" % self.player.current.display_name)
        return True

    # ------------------------------------------------------------ commands --
    def _on_play(self, _event):
        index = self.selection()
        if index is None:
            self.frame.announce("There is nothing in the running order yet")
            return
        self.frame.play_playlist(index)

    def _on_stop(self, _event):
        self.frame.stop_playlist()

    def _on_add(self, _event):
        self.frame.add_playlist_files()

    def _on_drop(self, _event):
        self.frame.insert_playlist_drop()

    def _on_remove(self, _event):
        self.remove_selected()

    def remove_selected(self):
        index = self.selection()
        if index is None:
            self.frame.announce("There is nothing to remove")
            return
        track = self.playlist.remove(index)
        if track is None:
            return
        # Removing what is on air would leave the player pointing at a
        # different song from the one you can hear, so it is taken off first.
        if self.player.playing and self.player.index == index:
            self.frame.stop_playlist(quiet=True)
        elif self.player.index > index:
            self.player.index -= 1
        self.refresh(keep=min(index, len(self.playlist) - 1))
        self.frame.announce_help("Removed %s" % track.display_name)
        self.frame.playlist_changed()

    def move_selected(self, delta):
        index = self.selection()
        if index is None:
            return
        target = self.playlist.move(index, delta)
        if target is None:
            self.frame.announce("That is already at the %s"
                                % ("top" if delta < 0 else "bottom"))
            return
        # The player follows the track it is playing rather than the position
        # it was at, or moving a song under the one on air would leave it
        # convinced it is playing whatever took its place.
        if self.player.index == index:
            self.player.index = target
        elif self.player.index == target:
            self.player.index = index
        self.refresh(keep=target)
        self.frame.announce_help("Moved to %d" % (target + 1))
        self.frame.playlist_changed()
