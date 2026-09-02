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
    #: How many playable sounds are in this slot's folder, when ``filepath`` is
    #: a folder rather than a file. Saved so the label is right before the first
    #: scan, which then corrects it. ``None`` for an ordinary slot.
    folder_count: int | None = None

    def __post_init__(self):
        #: The folder's contents, scanned. Never saved: it is what is on disk
        #: right now, and the point of a folder slot is that you can drop
        #: another jingle in without touching the app.
        self._folder_files: list = []
        self._folder_stamp = None
        self._last_pick = None

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
            "folder_count": self.folder_count,
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
            folder_count=_maybe_int(data.get("folder_count")),
        )

    def clear(self) -> None:
        """Empty the slot but keep any custom hotkey the user set up."""
        self.filepath = None
        self.name = None
        self.duration = None
        self.trim_db = 0.0
        self.folder_count = None
        self._folder_files = []
        self._folder_stamp = None
        self._last_pick = None
        self.loop = self.is_bed
