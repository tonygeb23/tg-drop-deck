"""One slot on the board, and how it describes itself to a screen reader."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import constants as C


def bank_for_index(index: int) -> int:
    """1-based bank number for a 0-based global slot index."""
    return index // C.SLOTS_PER_BANK + 1


def position_in_bank(index: int) -> int:
    """1-based position of a slot within its own bank."""
    return index % C.SLOTS_PER_BANK + 1


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

    # ------------------------------------------------------------- identity --
    @property
    def bank(self) -> int:
        return bank_for_index(self.index)

    @property
    def bank_title(self) -> str:
        return C.BANK_TITLES[self.bank]

    @property
    def bank_short(self) -> str:
        return C.BANK_SHORT[self.bank]

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
            state.append("file missing")
        elif self.is_assigned:
            if playing:
                state.append("playing")
            if self.loop:
                state.append("loops")
            dur = format_duration(self.duration)
            if dur:
                state.append(dur)
        return state

    def button_label(self, playing: bool = False) -> str:
        """What the button says, and therefore what a screen reader reads.

        Name first, because that is what you are hunting for when you arrow
        along a row. The bank is not repeated here — the tab already said it.
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
        )

    def clear(self) -> None:
        """Empty the slot but keep any custom hotkey the user set up."""
        self.filepath = None
        self.name = None
        self.duration = None
        self.trim_db = 0.0
        self.loop = self.is_bed
