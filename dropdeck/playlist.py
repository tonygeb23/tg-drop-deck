"""A radio playlist: a running order, its cue points, and the two decks.

The soundboard fires sounds you choose, one press at a time. A playlist is the
other half of a show — songs queued up, each one cueing the next before it has
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
mixer at all — it is one voice fading out while another fades in, which the
mixer has always been able to do.

Like `engine.py` and `mixer.py`, **nothing here knows what wx is.** The player
is driven by calling `tick()`, which the app does from a timer and the tests do
by hand after rendering a known number of samples. That is what makes a
crossfade something you can measure rather than something you have to listen to.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import constants as C
from .engine import probe
from .slot import format_duration


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

    @property
    def is_drop(self) -> bool:
        return self.kind == C.TRACK_DROP

    @property
    def is_missing(self) -> bool:
        return bool(self.filepath) and not os.path.exists(self.filepath)

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        return os.path.splitext(os.path.basename(self.filepath or ""))[0] or "Untitled"

    def crossfade_seconds(self, default):
        """This track's cue, in seconds, resolved against the playlist default.

        A drop that has never been given one does not crossfade: it is a
        station ident, and half of it fading under the next song is not what
        anybody meant by "put a drop between them".
        """
        if self.crossfade is not None:
            return self.crossfade
        return 0.0 if self.is_drop else default

    def label(self, position, default_crossfade, playing=False, cue=None):
        """What the list row says, and therefore what a screen reader reads."""
        parts = ["%d. %s" % (position, self.display_name)]
        parts.append("drop" if self.is_drop else "song")
        if not self.enabled:
            # The tick box says checked or not; this says what that means, for
            # anyone reading the row rather than listening to the control.
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
                parts.append("starts at %s" % format_duration(cue))
        return ", ".join(parts)

    def to_dict(self):
        return {"filepath": self.filepath, "name": self.name,
                "duration": self.duration, "kind": self.kind,
                "crossfade": self.crossfade, "trim_db": float(self.trim_db),
                "enabled": bool(self.enabled)}

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        kind = data.get("kind")
        return cls(
            filepath=data.get("filepath") or "",
            name=data.get("name") or None,
            duration=data.get("duration"),
            kind=kind if kind in (C.TRACK_SONG, C.TRACK_DROP) else C.TRACK_SONG,
            crossfade=_clean_crossfade(data.get("crossfade")),
            trim_db=float(data.get("trim_db", 0.0) or 0.0),
            enabled=bool(data.get("enabled", True)),
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
        return Track(filepath=path, duration=duration, kind=kind,
                     crossfade=crossfade)

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

    def clear(self):
        count = len(self.tracks)
        self.tracks = []
        return count

    # --------------------------------------------------------------- cues ---
    def crossfade_for(self, index):
        """The cue of item ``index``: how early the next one starts.

        The last item has no cue, because there is nothing to hand over to.
        A crossfade longer than the track is clamped to the track, so a three
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
        if track.duration:
            fade = min(fade, track.duration)
        return max(0.0, fade)

    def cue_points(self):
        """When each item starts, in seconds from the top of the playlist.

        This is the timeline: item n starts when item n-1 has `crossfade`
        seconds left, so the overlaps accumulate backwards through the list.
        """
        points = []
        clock = 0.0
        for index, track in enumerate(self.tracks):
            if not self.will_play(index):
                # No start time, because it has none: it is being skipped.
                points.append(None)
                continue
            points.append(clock)
            clock += max(0.0, (track.duration or 0.0) - self.crossfade_for(index))
        return points

    @property
    def total_duration(self):
        """How long the whole running order takes, crossfades included."""
        playing = [i for i in range(len(self.tracks)) if self.will_play(i)]
        if not playing:
            return 0.0
        points = self.cue_points()
        last = playing[-1]
        return points[last] + (self.tracks[last].duration or 0.0)

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

    def __init__(self, mixer, playlist, on_change=None):
        self.mixer = mixer
        self.playlist = playlist
        #: Called with no arguments whenever the playing item changes, so a UI
        #: can relabel. Never called from inside the audio callback.
        self.on_change = on_change
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
            fade_in=fade_in if fade_in is not None else 0.0,
            fade_out=self.playlist.crossfade_for(index))
        if voice is None:
            self.last_error = getattr(self.mixer, "last_error", None)
            return None
        self.index = index
        self._voice = voice
        self.playing = True
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

    def _hand_over(self, following):
        """Start the next item and let the current one fade under it."""
        fade = self.playlist.crossfade_for(self.index)
        outgoing = self._voice
        started = self._start(following, fade_in=fade)
        if started is None:
            return False
        if outgoing is not None and outgoing is not started:
            outgoing.release(fade)
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

        duration = track.duration
        if not duration:
            return False
        fade = self.playlist.crossfade_for(self.index)
        if fade <= 0:
            return False
        if voice.position_seconds < duration - fade:
            return False
        following = self._first_playable(self.index + 1)
        if following is None:
            return False
        return self._hand_over(following)
