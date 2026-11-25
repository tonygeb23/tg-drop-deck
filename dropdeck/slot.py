"""One slot on the board, and how it describes itself to a screen reader."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field

from . import constants as C


def bank_for_index(index: int) -> int:
    """1-based bank number for a 0-based global slot index."""
    return index // C.SLOTS_PER_BANK + 1


def position_in_bank(index: int) -> int:
    """1-based position of a slot within its own bank."""
    return index % C.SLOTS_PER_BANK + 1


def _maybe_int(value):
    """An int off disk, or None. A folder count is derived and never trusted."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def format_duration(seconds: float | None) -> str:
    """A spoken-friendly duration. No bare colons for a screen reader to trip on."""
    if not seconds or seconds <= 0:
        return ""
    seconds = int(round(seconds))
    minutes, secs = divmod(seconds, 60)
    if minutes and secs:
        return f"{minutes} min {secs} sec"
    if minutes:
        return f"{minutes} min"
    return f"{secs} sec"


@dataclass
class Slot:
    """A single button's worth of state.

    ``index`` is the 0-based global position, 0 to 79. Everything else is either
    what the user assigned or what we measured when they assigned it.
    """

    #: Bank number -> the name the user gave that bank, shared with the Board
    #: that owns this slot. Deliberately NOT a dataclass field: it is the
    #: board's state rather than the slot's, it must never reach to_dict, and a
    #: slot built on its own in a test falls back to the shipped names.
    bank_names = None

    index: int
    filepath: str | None = None
    name: str | None = None
    duration: float | None = None
    custom_hotkey: str | None = None
    key_code: int | None = None
    modifiers: int | None = None
    #: A system-wide hotkey, which fires this slot while another window has
    #: focus. Separate from custom_hotkey, which only works inside the app.
    #: Always needs a modifier - see globalhotkeys.parse.
    global_hotkey: str | None = None
    loop: bool = field(default=False)
    #: Per-slot trim in decibels, so one loud sound can be tamed on its own.
    trim_db: float = 0.0
    #: The user set that trim, so it wins over loudness matching even at
    #: exactly 0 dB, which is how a pad is kept as recorded. A board saved
    #: before this existed reads it as "any trim but nought", which is what
    #: its trim meant then.
    trim_set: bool = False
    #: Taken off the board. The slot keeps everything it had, including its
    #: sound and its hotkeys, and can be put back; it simply is not shown and
    #: its key does nothing. Removing one NEVER renumbers the others, because
    #: the digit map is muscle memory: take slot 5 away and 6 is still on the
    #: 6 key.
    hidden: bool = False
    #: Pressing this slot's key again stops it, instead of playing a second
    #: copy on top of the first.
    #:
    #: Chris Cooke, 5 September 2026: "I have a rather long sound file that I
    #: may only wanna play a little bit of, but it takes an extra second or so
    #: to press the escape key four times to completely stop it."
    #:
    #: Off by default, and deliberately. Effects and drops overlapping is the
    #: thing a soundboard is FOR: a laugh landing on top of a sting is the
    #: point, and making every key a toggle would take that away from everyone
    #: to help the one slot that needed it. Beds have always toggled and go on
    #: doing so whatever this says.
    toggle_stop: bool = False
    #: How many playable sounds are in this slot's folder, when ``filepath`` is
    #: a folder rather than a file. Saved so the label is right before the first
    #: scan, which then corrects it. ``None`` for an ordinary slot.
    folder_count: int | None = None
    #: How loud the file is (BS.1770 integrated, LUFS) and its loudest
    #: sample (dBFS), measured once on the background pass for loudness
    #: matching. See loudness.trim_for. None until measured, and loudness
    #: stays None for a file too short to have an answer.
    loudness: float | None = None
    peak_db: float | None = None

    def __post_init__(self):
        #: The folder's contents, scanned. Never saved: it is what is on disk
        #: right now, and the point of a folder slot is that you can drop
        #: another jingle in without touching the app.
        self._folder_files: list = []
        self._folder_stamp = None
        #: Which file the loudness above belongs to. Never saved: a board
        #: file carries the numbers and no path, so an export names nobody's
        #: folders, and on load they belong to the file the slot names. A
        #: pad given another sound no longer matches it and is measured
        #: again; nothing uses a number for the wrong file.
        self.loudness_for = None
        #: The file's size and modification time when it was measured, and
        #: whether that has been checked against the file on this run. See
        #: loudness_due.
        self.loudness_stamp = None
        self.loudness_verified = False
        self._last_pick = None
        self._built = True

    def __setattr__(self, name, value):
        # Setting a trim on a pad that exists is the user setting it,
        # whichever dialog or path it came through, so no way in can forget
        # to say so. See trim_set.
        object.__setattr__(self, name, value)
        if name == "trim_db" and self.__dict__.get("_built"):
            object.__setattr__(self, "trim_set", True)

    # ------------------------------------------------------------- identity --
    @property
    def bank(self) -> int:
        return bank_for_index(self.index)

    @property
    def bank_title(self) -> str:
        """What this slot's bank is called - the user's name for it, if any."""
        return (self.bank_names or {}).get(self.bank) or C.BANK_TITLES[self.bank]

    @property
    def bank_short(self) -> str:
        """The same, short, for lists that span every bank.

        A renamed bank has no short form and inventing one would be guesswork,
        so the name the user typed is used whole. "SFX" is only a contraction
        of a name they did not choose.
        """
        return (self.bank_names or {}).get(self.bank) or C.BANK_SHORT[self.bank]

    @property
    def number(self) -> int:
        return position_in_bank(self.index)

    @property
    def is_bed(self) -> bool:
        return self.bank == C.LOOPING_BANK

    @property
    def hotkey_label(self) -> str:
        """The key that fires this slot, fixed by bank or chosen by the user."""
        if self.bank == C.BANK_MISC:
            return self.custom_hotkey or ""
        return C.BANK_HOTKEY_LABELS[self.bank][self.number - 1]

    # -------------------------------------------------------------- content --
    @property
    def is_assigned(self) -> bool:
        return bool(self.filepath)

    @property
    def is_folder(self) -> bool:
        """This slot holds a folder, and plays a different sound every press.

        Brian Hartgen's: a chart countdown has half a dozen "down the chart"
        jingles and you do not care which one you get, only that one plays. So
        the slot points at the folder and picks for you.
        """
        return bool(self.filepath) and os.path.isdir(self.filepath)

    @property
    def is_missing(self) -> bool:
        """Assigned, but the file is not where it used to be."""
        return bool(self.filepath) and not os.path.exists(self.filepath)

    def needs_loudness(self) -> bool:
        """On the background pass: a file to measure for loudness matching.
        A folder pad plays a different file each press, so it has no one
        loudness to match. See loudness_due."""
        return loudness_due(self)

    def measure_loudness(self, stop=None) -> bool:
        """Measure, on the background pass. True if anything changed."""
        return measure_into(self, stop)

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.filepath:
            return os.path.splitext(os.path.basename(self.filepath))[0]
        return "Empty"

    def _state_words(self, playing: bool) -> list:
        state = []
        if self.is_missing:
            state.append("folder missing" if self.folder_count is not None
                         else "file missing")
        elif self.is_assigned:
            if playing:
                state.append("playing")
            if self.loop:
                state.append("loops")
            if self.is_folder:
                # A count, not a length. Every press is a different file, so a
                # duration here would be a different lie each time.
                n = self.folder_count
                state.append("folder, " + ("empty" if n == 0 else
                                           "1 sound" if n == 1 else
                                           "%d sounds" % n if n else
                                           "not counted yet"))
            else:
                dur = format_duration(self.duration)
                if dur:
                    state.append(dur)
        return state

    def button_label(self, playing: bool = False) -> str:
        """What the button says, and therefore what a screen reader reads.

        Name first, because that is what you are hunting for when you arrow
        along a row. The bank is not repeated here, the tab already said it.
        """
        parts = [f"{self.number}. {self.display_name}"]
        if self.hotkey_label:
            parts.append(f"key {self.hotkey_label}")
        if self.global_hotkey:
            parts.append(f"global {self.global_hotkey}")
        parts.extend(self._state_words(playing))
        return ", ".join(parts)

    def search_label(self, playing: bool = False) -> str:
        """Same idea, but for lists that span every bank, so name the bank."""
        parts = [self.display_name, f"{self.bank_short} {self.number}"]
        if self.hotkey_label:
            parts.append(f"key {self.hotkey_label}")
        if self.global_hotkey:
            parts.append(f"global {self.global_hotkey}")
        parts.extend(self._state_words(playing))
        return ", ".join(parts)

    # -------------------------------------------------------------- folders --
    def scan_folder(self, force: bool = False) -> int:
        """Re-read the folder if it has changed. Returns how many sounds it holds.

        Cheap to call often: it compares the folder's own timestamp and does
        nothing when nobody has touched it. It is never called between a
        keypress and a sound, the trigger path uses whatever the last scan
        found, and the cache warmer does the scanning at startup.
        """
        if not self.is_folder:
            self._folder_files = []
            return 0
        try:
            stamp = os.stat(self.filepath).st_mtime_ns
        except OSError:
            return len(self._folder_files)
        if not force and stamp == self._folder_stamp and self._folder_files:
            return len(self._folder_files)
        try:
            names = sorted(os.listdir(self.filepath))
        except OSError:
            return len(self._folder_files)
        self._folder_files = [
            os.path.join(self.filepath, name) for name in names
            if os.path.splitext(name)[1].lower() in C.AUDIO_EXTENSIONS
            and os.path.isfile(os.path.join(self.filepath, name))]
        self._folder_stamp = stamp
        self.folder_count = len(self._folder_files)
        return self.folder_count

    @property
    def folder_files(self) -> list:
        return list(self._folder_files)

    def pick_file(self) -> str | None:
        """One file out of the folder, at random, avoiding an instant repeat.

        Two presses in a row giving the same jingle is what makes a random
        stinger sound broken rather than random, so the last one is excluded
        whenever there is anything else to choose from.
        """
        if not self._folder_files:
            return None
        choices = self._folder_files
        if len(choices) > 1 and self._last_pick in choices:
            choices = [p for p in choices if p != self._last_pick]
        self._last_pick = random.choice(choices)
        return self._last_pick

    def playable_path(self) -> str | None:
        """What a press should play. A folder picks one; a file is itself."""
        if self.is_folder:
            return self.pick_file()
        return self.filepath

    # ----------------------------------------------------------- conversion --
    def to_dict(self) -> dict:
        return {
            "filepath": self.filepath,
            "name": self.name,
            "duration": self.duration,
            "custom_hotkey": self.custom_hotkey,
            "global_hotkey": self.global_hotkey,
            "key_code": self.key_code,
            "modifiers": self.modifiers,
            "loop": bool(self.loop),
            "trim_db": float(self.trim_db),
            "trim_set": bool(self.trim_set),
            "folder_count": self.folder_count,
            "hidden": bool(self.hidden),
            "toggle_stop": bool(self.toggle_stop),
            **_loudness_fields(self),
        }

    @classmethod
    def from_dict(cls, index: int, data: dict | None) -> "Slot":
        data = data or {}
        return cls(
            index=index,
            filepath=data.get("filepath") or None,
            name=data.get("name") or None,
            duration=data.get("duration"),
            custom_hotkey=data.get("custom_hotkey") or None,
            global_hotkey=data.get("global_hotkey") or None,
            key_code=data.get("key_code"),
            modifiers=data.get("modifiers"),
            loop=bool(data.get("loop", bank_for_index(index) == C.LOOPING_BANK)),
            trim_db=float(data.get("trim_db", 0.0) or 0.0),
            trim_set=trim_was_set(data),
            folder_count=_maybe_int(data.get("folder_count")),
            hidden=bool(data.get("hidden", False)),
            toggle_stop=bool(data.get("toggle_stop", False)),
        )._take_loudness(data)

    def _take_loudness(self, data):
        take_loudness(self, data)
        return self

    def clear(self) -> None:
        """Empty the slot but keep any custom hotkey the user set up."""
        self.filepath = None
        self.name = None
        self.duration = None
        self.trim_db = 0.0
        self.trim_set = False          # after the trim: emptied, not chosen
        forget_loudness(self)
        self.folder_count = None
        self._folder_files = []
        self._folder_stamp = None
        self._last_pick = None
        self.loop = self.is_bed


def _number(value):
    """A finite number off disk, or None. A board file is not trusted."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def trim_was_set(data):
    """Whether a saved pad's or song's trim was set by the user.

    A board from before ``trim_set`` existed had no way to say "nought, and
    I mean it", so there a trim of nought was matching's and anything else
    the user's: it loads meaning exactly what it meant.
    """
    value = data.get("trim_set")
    if isinstance(value, bool):
        return value
    try:
        return float(data.get("trim_db", 0.0) or 0.0) != 0.0
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------- loudness stamp --
# Loudness numbers belong to one version of one file: its path, its size and
# its modification time. Mark, 24 November 2026: a jingle re-rendered louder
# under the same name kept the +6 dB measured on the quiet one, and played
# with its peaks at +5.9 dBFS. Everything here that touches the disk runs on
# the background pass, never between a keypress and a sound, because a stat
# on a network share that has gone away can hang for half a minute.

def file_stamp(path):
    """(size, modification time in ns) of a file, or None for a file that is
    not there or is a folder. Background pass only."""
    import stat
    try:
        info = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    if stat.S_ISDIR(info.st_mode):
        return None
    return (int(info.st_size), int(info.st_mtime_ns))


def forget_loudness(item):
    """Drop a pad's or a song's loudness, so it plays as it is."""
    item.loudness_for = None
    item.loudness = item.peak_db = None
    item.loudness_stamp = None
    item.loudness_verified = False


def loudness_due(item):
    """On the background pass: does ``item`` need measuring.

    Numbers already held are checked against the file as it is now. If the
    file has changed since, they are dropped at once, so the pad plays as
    recorded rather than at a trim measured on something else, and it is
    measured again. If it has not, they are marked as checked on this run,
    which is what lets a trim from them bring a sound UP (see
    loudness.trim_for).
    """
    path = item.filepath
    if not path:
        return False
    stamp = file_stamp(path)
    if stamp is None:
        return False
    if (item.loudness_for == path
            and getattr(item, "loudness_stamp", None) == stamp):
        item.loudness_verified = True
        return False
    if item.loudness_for is not None:
        forget_loudness(item)
    return True


def measure_into(item, stop=None):
    """Measure ``item``'s file, on the background pass. True if it changed.

    ``stop`` (a threading.Event) ends it within one 100 ms piece, and a
    measurement that was stopped is not kept: it is taken again next time.
    """
    from . import audiofile
    path = item.filepath
    if (not path or (item.loudness_for == path
                     and getattr(item, "loudness_verified", False))):
        return False
    stamp = file_stamp(path)
    if stamp is None:
        return False
    level, peak = audiofile.measure_loudness(path, stop=stop)
    if stop is not None and stop.is_set():
        return False
    item.loudness, item.peak_db = level, peak
    item.loudness_stamp = stamp
    item.loudness_verified = True
    # Last, so a press on another thread never pairs this path with the
    # numbers of the file it held before.
    item.loudness_for = path
    return True


def _plausible(level, peak):
    """Could these two numbers have come out of measure_loudness.

    BS.1770 gates everything under -70 LUFS away, so an integrated loudness
    below that cannot be measured; a file that has a loudness has a peak; and
    a programme cannot be more than about 7 dB louder than its own loudest
    sample (a full scale square wave in both channels, K weighted, reads
    about +6). Anything else in a board file is not a measurement.
    """
    if peak is not None and not -100.0 <= peak <= 12.0:
        return False
    if level is None:
        return True
    if not -70.0 <= level <= 10.0 or peak is None:
        return False
    return level - peak <= 8.0


def _loudness_fields(item):
    """The loudness a pad or a song saves: its numbers and the stamp of the
    file they were measured on, only if they are for the file it holds now,
    and never a path."""
    stamp = getattr(item, "loudness_stamp", None)
    if (item.loudness_for is None or item.loudness_for != item.filepath
            or stamp is None):
        return {}
    return {"loudness": item.loudness, "peak_db": item.peak_db,
            "loudness_checked": True, "loudness_stamp": list(stamp)}


def take_loudness(item, data):
    """Put saved loudness back on a pad or a song, for the file it names.

    A board file is not trusted. Numbers that could not have been measured
    count as not measured at all; numbers without the stamp of the file
    they were taken from are measured again; and numbers that are taken stay
    unchecked until the background pass has compared that stamp with the
    file on this machine. Until then they may only bring a sound down.
    """
    if not isinstance(data, dict) or data.get("loudness_checked") is not True:
        return
    stamp = data.get("loudness_stamp")
    if (not isinstance(stamp, (list, tuple)) or len(stamp) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool)
                       and v >= 0 for v in stamp)):
        return
    level = _number(data.get("loudness"))
    peak = _number(data.get("peak_db"))
    if (level is None) != (data.get("loudness") is None) or (
            peak is None) != (data.get("peak_db") is None):
        return
    if not _plausible(level, peak):
        return
    item.loudness, item.peak_db = level, peak
    item.loudness_stamp = (int(stamp[0]), int(stamp[1]))
    item.loudness_verified = False
    item.loudness_for = item.filepath
