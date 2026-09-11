"""What is coming up next, and the rules about when a row may leave.

Tyler, a listener, 10 September 2026: "almost a dialog list that shows what
song is coming up next, from top to bottom. songs will disappear after 10
seconds of instantly playing, this is a separate dialog list than the playlist
order, so, a key command to bring up the cue of what is checked in the
playlist running order."

`Ctrl+Shift+C` opens it. It is built from the TICKED items in the running
order, it drains from the top as the show runs, and it never touches the
running order itself.

**This module imports no wx**, which is what makes every rule below testable
one at a time rather than by opening a window and watching. Same reason
`preflight.py` and `routing.py` are built that way.

## The one rule everything else hangs off

Jessica measured what NVDA actually does when a `wx.ListCtrl` row is removed,
with a live MSAA hook on a real control, 10 September 2026:

- a row deleted **above** the focused one: one DESTROY event, no focus event,
  the cursor keeps its track and its selection. **Silent.**
- a row deleted **below** it: DESTROY only. **Silent.**
- the **focused** row deleted: DESTROY, then SELECTIONREMOVE, then a FOCUS
  event on a different item, and `GetFirstSelected()` returns -1. A focus
  event is the thing NVDA acts on, so it stops mid sentence and reads out a
  track the presenter did not choose, on air, at the moment a song changes.

So: **every row may leave except the one the user is standing on.** A removal
that would take the focused row is held until they arrow off it, at which
point it is a row above or below the cursor and therefore silent. That is the
same rule `SoundButton.refresh` already follows for a pad, for the same
reason, and it is why this can drain live at all instead of freezing while
the window is open.

## The trap inside Tyler's ten seconds

A drop shorter than the grace period hands over before its own row is due to
go, so two rows would both claim to be on air. **The grace only ever applies
to the most recently started item**: when something new starts, every earlier
row goes at once, grace or no grace. A nine second station ident is an
ordinary thing here, so this would have happened in week one.
"""
from __future__ import annotations

from . import constants as C

#: What a row is doing. The status cell is EMPTY for anything ordinary, and
#: that is deliberate: NVDA skips an empty cell entirely when it builds the
#: row it reads aloud, so an empty status costs nothing on any row and a
#: filled one says its piece only where it matters.
ON_AIR = "On air"
MISSING = "File missing"

#: The row that is always last, so "the playlist stops after this" is a fact
#: somebody has before it happens rather than after.
END_ROW = "End of the running order"

#: And what an empty cue says, as one row rather than an empty control. The
#: same trick the running order already uses.
EMPTY_ROW = ("Nothing else is ticked. Ctrl+Shift+P goes to the running order")


class Row:
    """One line of the cue sheet."""

    def __init__(self, title="", artist="", kind="", seconds=0.0,
                 status="", index=None, missing=False):
        self.title = title
        self.artist = artist
        self.kind = kind
        self.seconds = float(seconds or 0.0)
        self.status = status
        #: Where this is in the running order, so Enter can act on it.
        self.index = index
        self.missing = bool(missing)

    @property
    def length(self):
        return said_length(self.seconds)

    def cells(self):
        return (self.title, self.artist, self.kind, self.length, self.status)

    def __repr__(self):                                # pragma: no cover
        return "<Row %r %s>" % (self.title, self.status or "-")


def said_length(seconds):
    """A length worth hearing read out. Empty for nothing."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return ""
    minutes, seconds = divmod(seconds, 60)
    if not minutes:
        return "%d sec" % seconds
    return "%d min %d sec" % (minutes, seconds)


def build(tracks, playing_index=None, played_for=0.0, grace=None):
    """The rows, top to bottom, from the ticked items in the running order.

    ``tracks`` is every item in the running order, in order, each with
    ``title``, ``artist``, ``kind``, ``duration``, ``ticked`` and ``missing``.
    ``playing_index`` is which of them is on air, or None. ``played_for`` is
    how long it has been on air, in seconds, which is what Tyler's ten second
    grace is measured against.

    **A ticked track whose file has gone is shown, marked, and kept in the
    list.** `Playlist.enabled_tracks` and `will_play` both leave it out, so a
    cue built the obvious way simply omits it with nothing anywhere to say
    so. A cue sheet that silently drops an item is worse than no cue sheet.
    """
    grace = C.CUE_GRACE if grace is None else float(grace)
    rows = []
    for index, track in enumerate(tracks):
        if not getattr(track, "ticked", True):
            continue
        live = (index == playing_index)
        if live and played_for >= grace:
            # Its ten seconds are up. Tyler's whole request.
            continue
        if not live and playing_index is not None and index < playing_index:
            # Already gone by. The grace belongs to the newest item only, so
            # an earlier one leaves the moment something else starts, however
            # short it was. See this module's note about a nine second ident.
            continue
        missing = bool(getattr(track, "missing", False))
        rows.append(Row(
            title=getattr(track, "title", "") or "",
            artist=getattr(track, "artist", "") or "",
            kind=getattr(track, "kind", "") or "",
            seconds=getattr(track, "duration", 0.0) or 0.0,
            status=(ON_AIR if live else (MISSING if missing else "")),
            index=index, missing=missing))
    if not rows:
        return [Row(title=EMPTY_ROW)]
    rows.append(Row(title=END_ROW))
    return rows


def summary(tracks, rows):
    """One line under the list: how much is coming, and what is wrong.

    The unticked count is here because it answers "why is my song not in this
    list", which is otherwise unanswerable from this window.
    """
    coming = [r for r in rows if r.title not in (END_ROW, EMPTY_ROW)]
    total = sum(r.seconds for r in coming if not r.missing)
    unticked = sum(1 for t in tracks if not getattr(t, "ticked", True))
    missing = sum(1 for r in coming if r.missing)
    parts = ["%d coming up" % len(coming)]
    if total:
        parts.append(said_length(total))
    if unticked:
        parts.append("%d unticked" % unticked)
    if missing:
        parts.append("%d %s missing"
                     % (missing, "file" if missing == 1 else "files"))
    return ".  ".join(parts) + "."


def next_few(rows, how_many=3):
    """"Next X. Then Y. Then Z." One sentence, for the key that asks.

    A presenter plans a link out of what is coming. Arrowing three rows means
    three announcements and losing your place in the list.
    """
    coming = [r for r in rows
              if r.status != ON_AIR and r.title not in (END_ROW, EMPTY_ROW)]
    if not coming:
        return "Nothing else is coming up."
    said = []
    for position, row in enumerate(coming[:how_many]):
        name = row.title
        if row.artist:
            name += " by %s" % row.artist
        if row.missing:
            name += ", whose file is missing"
        said.append(("Next, %s" if position == 0 else "Then %s") % name)
    return ". ".join(said) + "."


def apply_changes(shown, wanted, focused_title=None):
    """Which rows may really leave, given where the cursor is standing.

    ``shown`` is what the list is displaying, ``wanted`` is what it should
    display, both as lists of `Row`. ``focused_title`` is the title of the row
    the user is on, or None when the window does not have focus.

    Returns the list to display now. **A row that would have to be removed or
    rewritten under the cursor is kept exactly as it is**, and comes out the
    moment the user arrows off it. Everything else is applied at once, which
    Jessica measured as completely silent.
    """
    if focused_title is None:
        return list(wanted)
    by_title = {}
    for row in wanted:
        by_title.setdefault(row.title, row)
    if focused_title in by_title:
        # Still wanted. Keep the ROW OBJECT that is already displayed, so a
        # rewrite of its cells does not land under the cursor either.
        out = []
        for row in wanted:
            if row.title == focused_title:
                held = next((r for r in shown if r.title == focused_title),
                            row)
                out.append(held)
            else:
                out.append(row)
        return out
    # The focused row is on its way out. Hold it where it is, and let
    # everything around it change.
    out = list(wanted)
    at = next((i for i, r in enumerate(shown) if r.title == focused_title),
              None)
    held = shown[at] if at is not None else None
    if held is None:
        return out
    out.insert(min(at, len(out)), held)
    return out
