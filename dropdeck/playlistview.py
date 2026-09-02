"""The playlist view: a running order you can paste into.

Deliberately a ``wx.CheckListBox`` rather than anything cleverer. A list box is
the one control every screen reader reads without argument, arrows through
without surprises, and reports a position in. The whole row is the text, the
same way a pad's whole label is its accessible name — and the tick beside it is
whether that item goes out, so a running order can be "play this, this and
this, not that" without anything having to leave the list and lose its place.

**The rows never say "playing".** They carry the running order — position,
name, whether it is a song or a drop, how long, its cue — and none of that
changes while the show is on. Rewriting the row that has focus would restart a
screen reader mid sentence at exactly the moment a song changes, which is the
trap `SoundButton.refresh` exists to avoid. What is on air is *spoken* when it
changes, and `Ctrl+L` answers it on demand.
"""

from __future__ import annotations

import os

import wx

from . import constants as C
from .plids import (ID_PL_ROW_ADD, ID_PL_ROW_DOWN, ID_PL_ROW_DROP,
                    ID_PL_ROW_FADE, ID_PL_ROW_PLAY, ID_PL_ROW_RANDOM,
                    ID_PL_ROW_REMOVE, ID_PL_ROW_SEGUE, ID_PL_ROW_STOP,
                    ID_PL_ROW_TICK, ID_PL_ROW_TO_LIBRARY, ID_PL_ROW_UP)
from .slot import format_duration

#: What the list shows when there is nothing in it. A row, not an empty
#: control: a list box with no items reads as nothing at all.
EMPTY_ROW = "Empty. Paste songs with Ctrl+V, or use Add files"


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

        outer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(self, label=(
            "Paste files here with Ctrl+V, or drag them in - as many at "
            "once as you like. Each song hands over to the next before "
            "it ends.\n"
            "Space ticks or unticks a track: unticked stays in the list "
            "and is skipped. Enter plays from the one you are on.\n"
            "Delete removes it. Alt+Up and Alt+Down move it."))
        outer.Add(intro, 0, wx.ALL, 8)

        # A real label in front of the control: on MSW the accessible name of a
        # list box comes from the static before it, not from SetName alone.
        outer.Add(wx.StaticText(self, label="&Running order"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        # Space toggles a tick, which is what this control does natively and
        # therefore what a screen reader already announces without help.
        self.list = wx.CheckListBox(self, style=wx.LB_SINGLE)
        self.list.SetName("Running order")
        outer.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)

        # The crossfade lives HERE, next to the running order it applies to,
        # rather than only in a menu. It is the number people reach for most
        # while building a show and the one they want to hear change.
        fade_row = wx.BoxSizer(wx.HORIZONTAL)
        fade_row.Add(wx.StaticText(self, label="&Crossfade, seconds"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.crossfade = wx.SpinCtrlDouble(
            self, min=0.0, max=C.MAX_CROSSFADE, inc=0.5,
            initial=float(self.playlist.crossfade))
        self.crossfade.SetDigits(1)
        self.crossfade.SetName("Crossfade between tracks, seconds")
        self.crossfade.SetToolTip(
            "How long one song overlaps the next. Zero means each one plays "
            "right out before the next starts. A track can be given a "
            "crossfade of its own from its right-click menu.")
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
            "Zero means each song plays right out first. A single track can "
            "have its own from\n"
            "its right-click menu, and this box is in Audio settings too.")),
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

        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_play)
        self.list.Bind(wx.EVT_CHECKLISTBOX, self._on_ticked)
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.crossfade.Bind(wx.EVT_SPINCTRLDOUBLE, self._on_crossfade)
        self.crossfade.Bind(wx.EVT_TEXT_ENTER, self._on_crossfade)
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
        the words "Empty" and not a track.
        """
        if self.is_empty:
            return None
        index = self.list.GetSelection()
        return None if index == wx.NOT_FOUND else index

    def focus_crossfade(self):
        """Put the user on the crossfade box, for the menu item that says so.

        No text selection: wx.SpinCtrlDouble does not offer one here, and a
        spin control is worked with the arrow keys anyway.
        """
        self.crossfade.SetFocus()

    def _on_crossfade(self, _event=None):
        """The crossfade moved. Apply it, relabel the cues, say the number.

        Every row carries its cue and its start time, so all of them change
        when this does - which is exactly why the rows are rebuilt here and
        the control is left alone.
        """
        seconds = round(float(self.crossfade.GetValue()), 2)
        if seconds == self.playlist.crossfade:
            return
        self.playlist.crossfade = seconds
        keep = self.list.GetSelection()
        self.refresh(keep=keep if keep != wx.NOT_FOUND else 0)
        self.frame.announce(
            "Crossfade %s" % (format_duration(seconds)
                              or "off, each song plays right out"))
        self.frame.playlist_changed(relabel=False)

    def focus_list(self):
        self.list.SetFocus()
        if self.list.GetCount() and self.list.GetSelection() == wx.NOT_FOUND:
            self.list.SetSelection(0)

    def refresh(self, keep=None):
        """Rebuild every row. The rows are static text; nothing here speaks."""
        playlist = self.playlist
        cues = playlist.cue_points()
        rows = [track.label(index + 1, playlist.crossfade, cue=cues[index])
                for index, track in enumerate(playlist)]
        previous = self.list.GetSelection() if keep is None else keep
        if not rows:
            # One row saying so, rather than an empty control. Arrowing into a
            # list with nothing in it gives a screen reader nothing to read,
            # which sounds exactly like a list that failed to load.
            self.list.Set([EMPTY_ROW])
            self.list.SetSelection(0)
            if abs(self.crossfade.GetValue() - playlist.crossfade) > 1e-9:
                self.crossfade.SetValue(float(playlist.crossfade))
            self._update_summary()
            return
        self.list.Set(rows)
        for index, track in enumerate(playlist):
            self.list.Check(index, bool(track.enabled))
        if abs(self.crossfade.GetValue() - playlist.crossfade) > 1e-9:
            # Loading a board brings its own crossfade with it.
            self.crossfade.SetValue(float(playlist.crossfade))
        if rows:
            if previous == wx.NOT_FOUND or previous is None or previous >= len(rows):
                previous = len(rows) - 1
            self.list.SetSelection(max(0, previous))
        self._update_summary()

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
        """Put files in, say what happened, and leave the list on the first."""
        playable = self.playlist.playable(paths)
        if not playable:
            self.frame.announce(
                "Nothing there this app can play. It takes %s files."
                % ", ".join(e.lstrip(".") for e in C.AUDIO_EXTENSIONS))
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
        """The user toggled a tick. Move it into the model and say what it means.

        The row's own text is left alone. The control has already said
        "checked" or "not checked", and rewriting the row underneath that
        would read the whole line again over the top of it - the same reason a
        pad does not relabel itself while it has focus.
        """
        index = event.GetSelection()
        if self.is_empty:
            # The only row is the word Empty. Put its tick straight back.
            self.list.Check(index, False)
            return
        track = self.playlist.set_enabled(index, self.list.IsChecked(index))
        if track is None:
            return
        self._update_summary()
        self.frame.announce_help(
            "%s %s" % (track.display_name,
                       "will play" if track.enabled else "will be skipped"))
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

    def _on_key(self, event):
        code = event.GetKeyCode()
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._on_play(None)
            return
        if code == wx.WXK_DELETE:
            self.remove_selected()
            return
        if event.AltDown() and code in (wx.WXK_UP, wx.WXK_DOWN):
            self.move_selected(-1 if code == wx.WXK_UP else 1)
            return
        event.Skip()

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
        self.list.Check(index, bool(track.enabled))
        self.refresh(keep=index)
        self.frame.announce_help(
            "%s %s" % (track.display_name,
                       "will play" if track.enabled else "will be skipped"))
        self.frame.playlist_changed(relabel=False)

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
        self.refresh(keep=target)
        self.list.SetSelection(target)
        self.frame.announce_help("Moved to %d" % (target + 1))
        self.frame.playlist_changed()
