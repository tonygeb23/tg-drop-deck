"""A radio playlist: a running order, its cue points, and the two decks.

The soundboard fires sounds you choose, one press at a time. A playlist is the
other half of a show, songs queued up, each one cueing the next before it has
finished, with station drops sitting between them.

Two ideas do all the work here.

**A cue point.** Every item says how long before its end the next item starts.
That single number is the crossfade: the outgoing track has `crossfade` seconds
left when the incoming one begins, and both are audible for exactly that long.
A drop's cue defaults to zero, so it plays out and then hands over.

**Two decks.** Real playout systems have an A deck and a B deck, and a
crossfade is the two of them overlapping. So does this: `PLAYLIST_DECK_A` and
`PLAYLIST_DECK_B` are slot indices above the eighty pads, and the player
alternates between them. That is why a crossfade needs no special case in the
mixer at all, it is one voice fading out while another fades in, which the
mixer has always been able to do.

Like `engine.py` and `mixer.py`, **nothing here knows what wx is.** The player
is driven by calling `tick()`, which the app does from a timer and the tests do
by hand after rendering a known number of samples. That is what makes a
crossfade something you can measure rather than something you have to listen to.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field

from . import audiofile
from . import constants as C
from .engine import probe
from .slot import format_duration


def format_cue(seconds):
    """A start time, which is a different thing from a length.

    ``format_duration`` answers "nothing" for zero, because a sound with no
    length has none worth saying. A cue of zero is not nothing: it is the top
    of the running order, and the first item in every playlist has one. Saying
    "starts at" and then stopping is what a screen reader was doing, and Brian
    Hartgen heard it as a value that had failed to arrive.
    """
    if seconds is None:
        return ""
    # Under a second is the top of the show. So is anything format_duration
    # rounds away to nothing, or to "0 sec", which is a start time nobody
    # means and a screen reader reads as a number that went wrong.
    if seconds < 1.0:
        return "at the top"
    text = format_duration(seconds)
    return "at the top" if text in ("", "0 sec") else text


def _clean_crossfade(value, fallback=None):
    """Seconds, clamped, or ``fallback`` when it is not a number."""
    if value is None:
        return fallback
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return fallback
    if seconds != seconds:                      # NaN
        return fallback
    return max(0.0, min(C.MAX_CROSSFADE, seconds))


@dataclass
class Track:
    """One item in the running order: a song, or a drop between two songs."""

    filepath: str
    name: str | None = None
    duration: float | None = None
    kind: str = C.TRACK_SONG
    #: How long before this track ends the next one starts. ``None`` means
    #: "whatever the playlist says", which is the case for almost every song.
    crossfade: float | None = None
    trim_db: float = 0.0
    #: Ticked or not. An unticked track stays in the running order, keeps its
    #: place and can be ticked again, but the player walks straight past it.
    #: Tony: "play this, this and this, don't play that."
    enabled: bool = True
    #: Out of the file's own tags. ``None`` means nobody has looked yet;
    #: an empty string means we looked and the file does not say.
    artist: str | None = None
    title: str | None = None
    #: Seconds of silence on the end of the file, measured once. This is what
    #: the cue point is taken from, so a crossfade lands on the song and not
    #: on the run out after it. ``None`` means not measured yet.
    tail_silence: float | None = None

    @property
    def is_drop(self) -> bool:
        return self.kind == C.TRACK_DROP

    @property
    def is_missing(self) -> bool:
        return bool(self.filepath) and not os.path.exists(self.filepath)

    @property
    def filename(self) -> str:
        return os.path.splitext(os.path.basename(self.filepath or ""))[0] or "Untitled"

    @property
    def title_text(self) -> str:
        """What this track is called: what you renamed it, its tag, its file.

        In that order, because a name the user typed beats a tag and a tag
        beats a file name. Never empty, because an empty row in a list is a
        row a screen reader reads as nothing at all.
        """
        if self.name:
            return self.name
        if self.title:
            return self.title
        return self.filename

    @property
    def artist_text(self) -> str:
        """The artist, or an empty string. Empty is a column that says nothing
        rather than a column that says "unknown"."""
        return self.artist or ""

    @property
    def has_metadata(self) -> bool:
        """Have the tags been read. Empty strings count: they mean we looked."""
        return self.artist is not None and self.title is not None

    @property
    def display_name(self) -> str:
        """One spoken name for this track, artist included when it has one."""
        if self.name:
            return self.name
        if self.title and self.artist:
            return "%s by %s" % (self.title, self.artist)
        return self.title or self.filename

    @property
    def playable_end(self) -> float:
        """Where the music really stops, in seconds from the start.

        The file's length less whatever silence is on the end of it. Cueing
        the next item from the last SAMPLE rather than from here is what put
        two of a three second crossfade inside the run out of an MP3.
        """
        duration = float(self.duration or 0.0)
        if not duration:
            return 0.0
        tail = float(self.tail_silence or 0.0)
        return max(0.0, duration - max(0.0, min(tail, duration)))

    def read_metadata(self):
        """Fill in artist, title and the run out. Safe to call twice.

        Returns True if anything changed. Never raises: a file with broken
        tags still plays, and a file that will not open is somebody else's
        problem to report.
        """
        changed = False
        if not self.has_metadata:
            found = {}
            if not self.is_missing:
                try:
                    found = audiofile.tags(self.filepath)
                except Exception:
                    found = {}
            self.artist = found.get("artist") or ""
            self.title = found.get("title") or ""
            changed = True
        if self.tail_silence is None:
            measured = 0.0
            if not self.is_missing:
                try:
                    measured = audiofile.tail_silence(self.filepath, self.duration)
                except Exception:
                    measured = 0.0
            self.tail_silence = float(measured)
            changed = True
        return changed

    def crossfade_seconds(self, default):
        """This track's cue, in seconds, resolved against the playlist default.

        A drop that has never been given one does not crossfade: it is a
        station ident, and half of it fading under the next song is not what
        anybody meant by "put a drop between them".
        """
        if self.crossfade is not None:
            return self.crossfade
        return 0.0 if self.is_drop else default

    def columns(self, default_crossfade, cue=None):
        """The cells of one row, in the order the list shows them.

        The title comes first because that is what first letter navigation
        looks at, and a running order is something you search by name. The
        number used to be there and is not any more: a row starting "17." is
        a row you cannot jump to by pressing its first letter, and in a three
        hour playlist that is the only way to find anything. The position is
        still announced, because a list item always announces its position.

        Blank means "this cell has nothing to add", not "unknown": a screen
        reader reading a column with nothing in it is one more thing said per
        arrow press, and there are six columns.
        """
        kind = "Drop" if self.is_drop else "Song"
        if self.is_missing:
            return [self.title_text, self.artist_text, kind + ", file missing",
                    "", "", ""]
        fade = self.crossfade_seconds(default_crossfade)
        return [
            self.title_text,
            self.artist_text,
            kind,
            format_duration(self.duration),
            format_cue(cue) if cue is not None else "",
            # Only when this track has been given one of its own. Every other
            # row would otherwise repeat the playlist's crossfade, which is in
            # the box under the list and does not need saying fifty times.
            (format_duration(fade) or "none") if self.crossfade is not None else "",
        ]

    def label(self, position, default_crossfade, playing=False, cue=None):
        """One spoken sentence about this track. Not what the row shows.

        The row is columns now, which is what lets a screen reader read them
        one at a time. This is the whole thing said in one go, for the key
        that asks and for the announcement when something starts.
        """
        parts = ["%d. %s" % (position, self.display_name)]
        parts.append("drop" if self.is_drop else "song")
        if not self.enabled:
            parts.append("skipped")
        if self.is_missing:
            parts.append("file missing")
        else:
            if playing:
                parts.append("playing")
            length = format_duration(self.duration)
            if length:
                parts.append(length)
            fade = self.crossfade_seconds(default_crossfade)
            if fade > 0:
                parts.append("crossfade %s" % format_duration(fade))
            if cue is not None:
                parts.append("starts %s" % format_cue(cue))
        return ", ".join(parts)

    def to_dict(self):
        return {"filepath": self.filepath, "name": self.name,
                "duration": self.duration, "kind": self.kind,
                "crossfade": self.crossfade, "trim_db": float(self.trim_db),
                "enabled": bool(self.enabled),
                "artist": self.artist, "title": self.title,
                "tail_silence": self.tail_silence}

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        kind = data.get("kind")
        tail = data.get("tail_silence")
        try:
            tail = None if tail is None else max(0.0, float(tail))
        except (TypeError, ValueError):
            tail = None
        return cls(
            filepath=data.get("filepath") or "",
            name=data.get("name") or None,
            duration=data.get("duration"),
            kind=kind if kind in (C.TRACK_SONG, C.TRACK_DROP) else C.TRACK_SONG,
            crossfade=_clean_crossfade(data.get("crossfade")),
            trim_db=float(data.get("trim_db", 0.0) or 0.0),
            enabled=bool(data.get("enabled", True)),
            artist=data.get("artist"),
            title=data.get("title"),
            tail_silence=tail,
        )


class Playlist:
    """The running order, and the arithmetic of where each item lands."""

    def __init__(self, crossfade=None):
        self.tracks: list = []
        self.crossfade = _clean_crossfade(crossfade, C.DEFAULT_CROSSFADE)

    # ----------------------------------------------------------- container --
    def __len__(self):
        return len(self.tracks)

    def __getitem__(self, index):
        return self.tracks[index]

    def __iter__(self):
        return iter(self.tracks)

    @property
    def missing(self):
        return [t for t in self.tracks if t.is_missing]

    @property
    def enabled_tracks(self):
        """What will actually go out: ticked, and the file still there."""
        return [t for t in self.tracks if t.enabled and not t.is_missing]

    def will_play(self, index):
        if not (0 <= index < len(self.tracks)):
            return False
        track = self.tracks[index]
        return bool(track.enabled) and not track.is_missing

    def set_enabled(self, index, value):
        if 0 <= index < len(self.tracks):
            self.tracks[index].enabled = bool(value)
            return self.tracks[index]
        return None

    def set_all_enabled(self, value):
        """Tick or untick the lot. Returns how many actually changed."""
        changed = 0
        for track in self.tracks:
            if bool(track.enabled) != bool(value):
                track.enabled = bool(value)
                changed += 1
        return changed

    def _next_playing(self, index):
        """The next item after ``index`` that will actually go out."""
        for following in range(index + 1, len(self.tracks)):
            if self.will_play(following):
                return following
        return None

    # ------------------------------------------------------------ building --
    @staticmethod
    def playable(paths):
        """The audio files out of a mixed bag of paths, folders expanded.

        Pasting from File Explorer hands over whatever was selected, which for
        an album is usually the folder. Taking the folder's contents is what
        somebody who selected it meant; taking nothing is not.
        """
        found = []
        for path in paths:
            if os.path.isdir(path):
                for name in sorted(os.listdir(path)):
                    full = os.path.join(path, name)
                    if (os.path.isfile(full)
                            and os.path.splitext(name)[1].lower() in C.AUDIO_EXTENSIONS):
                        found.append(full)
            elif (os.path.isfile(path)
                    and os.path.splitext(path)[1].lower() in C.AUDIO_EXTENSIONS):
                found.append(path)
        return found

    @staticmethod
    def _make(path, kind=C.TRACK_SONG, crossfade=None):
        """One Track, with its length measured. None if the file will not open.

        Durations are taken once, here, because that is what the cue points
        are made of - and because measuring them later would mean measuring
        them while the show is on.
        """
        if not Playlist.playable([path]):
            return None
        try:
            duration = probe(path)[0]
        except Exception:
            duration = None
        # The tags are read here too, because the file is already open in
        # every practical sense and reading them costs about a millisecond.
        # The run out is NOT: measuring it means decoding, and pasting an
        # album should not stop the app for two seconds. It is filled in on
        # a background pass afterwards.
        try:
            found = audiofile.tags(path)
        except Exception:
            found = {}
        return Track(filepath=path, duration=duration, kind=kind,
                     crossfade=crossfade,
                     artist=found.get("artist") or "",
                     title=found.get("title") or "")

    def add(self, paths, at=None, kind=C.TRACK_SONG, crossfade=None):
        """Put files into the running order. Returns the tracks that went in.

        Durations are measured here, once, because that is what the cue points
        are made of - and because doing it later would mean doing it while the
        show is on.
        """
        added = []
        for path in self.playable(paths):
            track = self._make(path, kind=kind, crossfade=crossfade)
            if track is not None:
                added.append(track)
        if not added:
            return []
        if at is None or at >= len(self.tracks):
            self.tracks.extend(added)
        else:
            at = max(0, at)
            self.tracks[at:at] = added
        return added

    def add_entries(self, entries, at=None):
        """Put items in from a playlist file. Returns the tracks that went in.

        Not ``add``, and deliberately: ``add`` throws away anything that is
        not a playable file on this machine right now, which is what you want
        from a paste and exactly what you do not want from a saved running
        order. A show whose music has moved has to come back with its missing
        tracks still in it, in the right order, so File, Relink missing sounds
        can go and find them. Dropping them silently would leave somebody
        rebuilding a two hour order by hand.
        """
        added = []
        for entry in entries:
            path = (entry.get("filepath") or "").strip()
            if not path:
                continue
            here = os.path.exists(path)
            if here and not self.playable([path]):
                continue          # a real file, but not one this app can play
            kind = (C.TRACK_DROP if str(entry.get("kind", "")).lower() == "drop"
                    else C.TRACK_SONG)
            track = Track(filepath=path, kind=kind,
                          crossfade=_clean_crossfade(entry.get("crossfade")),
                          enabled=str(entry.get("enabled", "1")) != "0")
            if here:
                # Measured, because the file is the truth and the number in a
                # playlist file was written by something else.
                try:
                    track.duration = probe(path)[0]
                except Exception:
                    track.duration = None
                try:
                    found = audiofile.tags(path)
                except Exception:
                    found = {}
                # The file's own tags first, then whatever the playlist file
                # said. An M3U exported by something with a better library
                # than the file itself has is worth keeping.
                track.artist = found.get("artist") or entry.get("artist") or ""
                track.title = found.get("title") or entry.get("title") or ""
            else:
                # Nothing to measure. Keep what the file said so the row can
                # still be read out and recognised.
                try:
                    track.duration = float(entry["duration"])
                except (KeyError, TypeError, ValueError):
                    track.duration = None
                track.artist = entry.get("artist") or ""
                track.title = entry.get("title") or ""
            added.append(track)
        if not added:
            return []
        if at is None or at >= len(self.tracks):
            self.tracks.extend(added)
        else:
            at = max(0, at)
            self.tracks[at:at] = added
        return added

    def insert_drop(self, path, at=None):
        """One drop, at a position. Returns the track, or None if unplayable."""
        added = self.add([path], at=at, kind=C.TRACK_DROP)
        return added[0] if added else None

    def insert_drop_every(self, path, every):
        """A drop after every ``every`` songs. Returns how many went in.

        Counted in songs, not in items, so running it twice does not start
        counting the drops it put in last time as though they were music.
        Never appended to the very end: a drop after the last song is a drop
        playing to an empty studio.
        """
        if every < 1:
            return 0
        template = self._make(path, kind=C.TRACK_DROP)
        if template is None:
            return 0
        # Built into a new list rather than spliced into the one being walked.
        original = list(self.tracks)
        rebuilt = []
        songs = 0
        inserted = 0
        for index, track in enumerate(original):
            rebuilt.append(track)
            if track.is_drop:
                continue
            songs += 1
            if songs % every:
                continue
            rest = original[index + 1:]
            if not rest or all(t.is_drop for t in rest):
                continue          # a drop after the last song plays to nobody
            if rest[0].is_drop:
                continue          # there is already one here
            rebuilt.append(Track(**template.to_dict()))
            inserted += 1
        self.tracks = rebuilt
        return inserted

    def insert_drops_every(self, library, every):
        """A drop after every ``every`` songs, a different one each time.

        The library version of insert_drop_every. Same placement rules; the
        difference is that each gap gets its own pick, so a countdown does not
        play the same ident five times.
        """
        if every < 1 or not len(library):
            return 0
        original = list(self.tracks)
        rebuilt = []
        songs = 0
        inserted = 0
        for index, track in enumerate(original):
            rebuilt.append(track)
            if track.is_drop:
                continue
            songs += 1
            if songs % every:
                continue
            rest = original[index + 1:]
            if not rest or all(t.is_drop for t in rest):
                continue
            if rest[0].is_drop:
                continue
            path = library.pick()
            if path is None:
                break
            drop = self._make(path, kind=C.TRACK_DROP)
            if drop is None:
                continue
            rebuilt.append(drop)
            inserted += 1
        self.tracks = rebuilt
        return inserted

    def remove(self, index):
        if 0 <= index < len(self.tracks):
            return self.tracks.pop(index)
        return None

    def move(self, index, delta):
        """Shuffle one item up or down. Returns where it ended up, or None."""
        target = index + delta
        if not (0 <= index < len(self.tracks)) or not (0 <= target < len(self.tracks)):
            return None
        self.tracks[index], self.tracks[target] = self.tracks[target], self.tracks[index]
        return target

    def move_to(self, index, target):
        """Take one item out and put it back at ``target``. Where it ended up.

        Not a swap. Alt+Home means "this goes first and everything else shifts
        down", not "this and whatever is first change places", which would
        reorder two tracks rather than one.
        """
        if not (0 <= index < len(self.tracks)):
            return None
        target = max(0, min(int(target), len(self.tracks) - 1))
        if target == index:
            return None
        track = self.tracks.pop(index)
        self.tracks.insert(target, track)
        return target

    def clear(self):
        count = len(self.tracks)
        self.tracks = []
        return count

    # --------------------------------------------------------------- cues ---
    def crossfade_for(self, index):
        """The crossfade of item ``index``: how long it overlaps the next one.

        The last item has none, because there is nothing to hand over to. A
        crossfade longer than the music is clamped to the music, so a three
        second cue on a two second drop starts the next item at the drop's
        beginning rather than before it.
        """
        if not (0 <= index < len(self.tracks)):
            return 0.0
        # An unticked item is not in the running order as far as timing goes,
        # and the last item that IS has nothing to hand over to.
        if not self.will_play(index) or self._next_playing(index) is None:
            return 0.0
        track = self.tracks[index]
        fade = track.crossfade_seconds(self.crossfade)
        playable = track.playable_end
        if playable:
            fade = min(fade, playable)
        return max(0.0, fade)

    def handover_at(self, index):
        """How early the next item really starts, in seconds before this one
        stops being music.

        The crossfade, or a fifth of a second, whichever is longer. That floor
        is what closes the hole between a spot and the song behind it: waiting
        until the drop's very last sample means waiting for a tick to notice
        and then for the next file to open, and both of those are audible.
        Zero for the last item, which has nothing to hand over to.
        """
        if not (0 <= index < len(self.tracks)):
            return 0.0
        if not self.will_play(index) or self._next_playing(index) is None:
            return 0.0
        overlap = max(self.crossfade_for(index), C.SEGUE_LEAD)
        playable = self.tracks[index].playable_end
        if playable:
            overlap = min(overlap, playable)
        return max(0.0, overlap)

    def cue_points(self):
        """When each item starts, in seconds from the top of the playlist.

        This is the timeline: item n starts when item n-1 has its handover
        left, so the overlaps accumulate backwards through the list. It is
        measured against where each track's music stops, not its last sample,
        which is why a running order of MP3s with silence on the end no longer
        reads a few seconds long.
        """
        points = []
        clock = 0.0
        for index, track in enumerate(self.tracks):
            if not self.will_play(index):
                # No start time, because it has none: it is being skipped.
                points.append(None)
                continue
            points.append(clock)
            clock += max(0.0, track.playable_end - self.handover_at(index))
        return points

    @property
    def total_duration(self):
        """How long the whole running order takes, crossfades included."""
        playing = [i for i in range(len(self.tracks)) if self.will_play(i)]
        if not playing:
            return 0.0
        points = self.cue_points()
        last = playing[-1]
        return points[last] + (self.tracks[last].playable_end
                               or self.tracks[last].duration or 0.0)

    # ------------------------------------------------------------ metadata --
    def needs_metadata(self):
        """The tracks whose tags or run out have never been looked at."""
        return [t for t in self.tracks
                if not t.is_missing
                and (not t.has_metadata or t.tail_silence is None)]

    # ----------------------------------------------------------- relinking --
    def relink(self, index):
        """Point missing tracks at matching filenames under ``index``.

        ``index`` is a {lowercased filename: full path} mapping, built once by
        the caller so a playlist and a board can be repaired in one walk.
        """
        repaired = []
        for track in self.missing:
            base = os.path.basename(track.filepath)
            found = index.get(base.lower())
            if found:
                track.filepath = found
                repaired.append(track)
        return repaired

    # ------------------------------------------------------------------ io --
    def to_dict(self):
        return {"crossfade": self.crossfade,
                "tracks": [t.to_dict() for t in self.tracks]}

    @classmethod
    def from_dict(cls, data, base_dir=None):
        data = data or {}
        playlist = cls(crossfade=data.get("crossfade"))
        for entry in data.get("tracks") or []:
            track = Track.from_dict(entry)
            if not track.filepath:
                continue
            if base_dir and not os.path.isabs(track.filepath):
                track.filepath = os.path.normpath(
                    os.path.join(base_dir, track.filepath))
            playlist.tracks.append(track)
        return playlist


class PlaylistPlayer:
    """Runs the playlist across two decks, crossfading at each cue.

    Driven by ``tick()``. Nothing is scheduled on a thread and nothing sleeps:
    every decision is "has the running track reached its cue point yet", asked
    often enough that the answer is never more than a tick late.
    """

    def __init__(self, mixer, playlist, on_change=None, on_warning=None):
        self.mixer = mixer
        self.playlist = playlist
        #: Called with no arguments whenever the playing item changes, so a UI
        #: can relabel. Never called from inside the audio callback.
        self.on_change = on_change
        #: Called once per track, this many seconds before its music stops.
        #: A sighted presenter watches a clock; this is that clock. The player
        #: does the arithmetic and says when; what it sounds like is somebody
        #: else's business.
        self.on_warning = on_warning
        self.warn_seconds = 0.0
        self._warned = False
        self.index = -1
        self.playing = False
        self.last_error = None
        # Flipped on the first _next_deck, so the first thing to play is on
        # deck A. Nothing depends on it; a log that says B first is confusing.
        self._deck = 1
        self._voice = None

    # ------------------------------------------------------------ transport --
    @property
    def current(self):
        if 0 <= self.index < len(self.playlist):
            return self.playlist[self.index]
        return None

    @property
    def position(self):
        """How far into the running track we are, in seconds, or None."""
        if not self.playing or self._voice is None:
            return None
        return float(self._voice.position_seconds)

    @property
    def remaining(self):
        """How much of the running track is left, in seconds, or None.

        Measured to where the music stops rather than to the last sample, so
        it agrees with when the next track will actually start. Brian
        Hartgen: "We do not know how much time remains in the song."
        """
        track = self.current
        if track is None or not self.playing or self._voice is None:
            return None
        end = track.playable_end or float(track.duration or 0.0)
        if not end:
            return None
        return max(0.0, end - float(self._voice.position_seconds))

    def _next_deck(self):
        self._deck = 1 - self._deck
        return C.PLAYLIST_DECKS[self._deck]

    def _start(self, index, fade_in=None):
        """Put item ``index`` on the next free deck. Returns its Voice."""
        track = self.playlist[index]
        voice = self.mixer.play(
            self._next_deck(), track.filepath,
            bus=C.BUS_PLAYLIST, loop=False, trim_db=track.trim_db,
            name=track.display_name, duration=track.duration,
            # A hair of a fade in, never a ramp. Long enough that the first
            # sample cannot click, short enough that the song starts where
            # the song starts.
            fade_in=fade_in if fade_in is not None else C.SEGUE_FADE_IN,
            fade_out=self.playlist.handover_at(index))
        if voice is None:
            self.last_error = getattr(self.mixer, "last_error", None)
            return None
        self.index = index
        self._voice = voice
        self.playing = True
        self._warned = False
        if self.on_change:
            self.on_change()
        return voice

    def play(self, index=None):
        """Start, or start from a particular item. Returns True if it began."""
        if not len(self.playlist):
            return False
        if index is None:
            index = self.index if 0 <= self.index < len(self.playlist) else 0
        if not (0 <= index < len(self.playlist)):
            return False
        # Skip forward over anything whose file has gone, rather than stopping
        # dead in the middle of a show on a track somebody moved last week.
        index = self._first_playable(index)
        if index is None:
            self.last_error = ("nothing from here is ticked to play, "
                               "or the files have gone")
            return False
        self.stop(fade_out=0.05, quiet=True)
        return self._start(index) is not None

    def _first_playable(self, index):
        """The first item from here that will actually go out.

        Skips both the unticked and the missing. An explicit "play from here"
        on an item you have unticked lands on the next one you have not,
        rather than playing something you said not to play.
        """
        while index < len(self.playlist):
            if self.playlist.will_play(index):
                return index
            index += 1
        return None

    def stop(self, fade_out=None, quiet=False):
        """Take the playlist off the air. Leaves the board's sounds alone."""
        stopped = 0
        for deck in C.PLAYLIST_DECKS:
            # also_releasing, because stopping in the middle of a crossfade has
            # to take the outgoing song down too. It is releasing over the
            # whole crossfade and would otherwise play on for seconds after
            # somebody pressed stop.
            stopped += self.mixer.stop_slot(deck, fade_out=fade_out,
                                            also_releasing=True)
        self.playing = False
        self._voice = None
        if not quiet and self.on_change:
            self.on_change()
        return stopped

    def next(self):
        """Hand over now, at the cue length, exactly as the cue point would."""
        if not len(self.playlist):
            return False
        following = self._first_playable(self.index + 1)
        if following is None:
            self.stop(fade_out=C.FADE_OUT_BED)
            return False
        return self._hand_over(following)

    def segue_to(self, index):
        """Cross to any item, now, at the crossfade length. Manual handover."""
        if not (0 <= index < len(self.playlist)):
            return False
        if not self.playing or self._voice is None:
            return self.play(index)
        return self._hand_over(index)

    def previous(self):
        if self.index <= 0:
            return False
        target = self.index - 1
        while target >= 0 and not self.playlist.will_play(target):
            target -= 1
        if target < 0:
            return False
        self.stop(fade_out=0.05, quiet=True)
        return self._start(target) is not None

    def _check_warning(self, end, voice):
        """Fire the end of track cue, once, when the time comes.

        Nothing is warned about that is barely longer than the warning: a nine
        second ident with a ten second warning would beep the moment it
        started, which tells the presenter nothing and is just a noise.
        """
        if self._warned or not self.on_warning:
            return
        seconds = float(self.warn_seconds or 0.0)
        if seconds <= 0 or not end or end <= seconds + 1.0:
            return
        if voice.position_seconds < end - seconds:
            return
        self._warned = True
        try:
            self.on_warning()
        except Exception:
            pass          # a cue that fails must not stop the show

    def _hand_over(self, following):
        """Start the next item and let the current one ride down under it.

        The incoming track comes up at full level, near enough instantly. The
        outgoing one fades out across the whole overlap. That is what a
        crossfade is on the radio, and it is not what this used to do: both
        of them ramped, so on a file with any silence on its end the outgoing
        song finished while the incoming one was still a quarter of the way
        up, and what you heard was one song stopping and another creeping in.

        Brian Hartgen, September 2026: "The song is playing out in full and
        the second one is fading in. That is not crossfading."
        """
        overlap = self.playlist.handover_at(self.index)
        if overlap <= 0:
            # Nothing to hand over to, which is the case when somebody segues
            # by hand out of the last item in the order. Use the playlist's
            # crossfade rather than cutting the outgoing song dead.
            overlap = max(float(self.playlist.crossfade or 0.0), C.SEGUE_LEAD)
        outgoing = self._voice
        started = self._start(following, fade_in=C.SEGUE_FADE_IN)
        if started is None:
            return False
        if outgoing is not None and outgoing is not started:
            outgoing.release(overlap)
        return True

    # ---------------------------------------------------------------- tick --
    def tick(self):
        """Has the running track reached its cue point. Call often.

        Returns True if something changed, which is only ever "the next item
        started" or "the playlist ended".
        """
        if not self.playing:
            return False
        voice = self._voice
        if voice is None:
            return False

        track = self.current
        if track is None:
            self.stop()
            return True

        if voice.finished:
            # It ran out on its own. Either there is more, or that was the show.
            following = self._first_playable(self.index + 1)
            if following is None:
                self.playing = False
                self._voice = None
                if self.on_change:
                    self.on_change()
                return True
            if self._start(following) is not None:
                return True
            # The next one would not open - a truncated download, a codec
            # nothing here reads. Without this the player would keep the
            # finished voice, come back in fifty milliseconds and try the same
            # broken file again, forever, in silence and with nothing said.
            self.last_error = "%s would not play" % (
                self.playlist[following].display_name)
            self.stop()
            return True

        # Where the music stops, which is not the same as where the file
        # stops. A track nobody has measured yet behaves as it always did.
        end = track.playable_end
        self._check_warning(end, voice)
        if not end:
            return False
        overlap = self.playlist.handover_at(self.index)
        if overlap <= 0:
            return False
        if voice.position_seconds < end - overlap:
            return False
        following = self._first_playable(self.index + 1)
        if following is None:
            return False
        return self._hand_over(following)


class DropLibrary:
    """The drops you use over and over, kept in one place.

    Building a running order means reaching for a station ident every few
    songs, and picking the same file out of the same folder every time is the
    part that wears thin. So the drops go in here once and `Alt+D` takes one at
    random - never the same one twice running, for the same reason a folder
    slot does not repeat itself: two identical idents in a row is what makes
    random sound broken.

    It travels with the board, because a board is a show and a show has its own
    idents. Opening somebody else's board brings theirs.
    """

    def __init__(self):
        self.paths: list = []
        self._last = None

    def __len__(self):
        return len(self.paths)

    def __iter__(self):
        return iter(self.paths)

    def __getitem__(self, index):
        return self.paths[index]

    @property
    def missing(self):
        return [p for p in self.paths if not os.path.exists(p)]

    @property
    def available(self):
        """The ones still on disk. A pick never offers a file that has gone."""
        return [p for p in self.paths if os.path.exists(p)]

    def add(self, paths):
        """Put files in. Returns what was actually added.

        Folders are expanded and anything already in the library is skipped,
        so adding the same folder twice does not double every ident in it.
        """
        added = []
        for path in Playlist.playable(paths):
            full = os.path.normpath(os.path.abspath(path))
            if any(os.path.normcase(full) == os.path.normcase(p)
                   for p in self.paths):
                continue
            self.paths.append(full)
            added.append(full)
        return added

    def remove(self, index):
        if 0 <= index < len(self.paths):
            return self.paths.pop(index)
        return None

    def clear(self):
        count = len(self.paths)
        self.paths = []
        self._last = None
        return count

    def pick(self):
        """One drop, at random, never the same one twice running."""
        choices = self.available
        if not choices:
            return None
        if len(choices) > 1 and self._last in choices:
            choices = [p for p in choices if p != self._last]
        self._last = random.choice(choices)
        return self._last

    def label(self, index):
        """One row, for the library list."""
        path = self.paths[index]
        name = os.path.splitext(os.path.basename(path))[0]
        if not os.path.exists(path):
            return "%d. %s, file missing" % (index + 1, name)
        return "%d. %s" % (index + 1, name)

    def relink(self, index):
        """Repair moved drops out of the same walk everything else uses."""
        repaired = []
        for position, path in enumerate(self.paths):
            if os.path.exists(path):
                continue
            found = index.get(os.path.basename(path).lower())
            if found:
                self.paths[position] = found
                repaired.append(found)
        return repaired

    def to_dict(self):
        return {"paths": list(self.paths)}

    @classmethod
    def from_dict(cls, data, base_dir=None):
        library = cls()
        for path in (data or {}).get("paths") or []:
            if not isinstance(path, str) or not path.strip():
                continue
            if base_dir and not os.path.isabs(path):
                path = os.path.normpath(os.path.join(base_dir, path))
            library.paths.append(path)
        return library
