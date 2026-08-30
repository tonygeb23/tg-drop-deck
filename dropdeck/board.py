"""A board: eighty slots, two volumes, and the settings that travel with them.

Boards are plain JSON. The old Tony Gebhard Show Soundboard files load without
conversion — that format is a subset of this one, so an existing bank opens and
keeps working.
"""

from __future__ import annotations

import json
import sys
import os

from . import constants as C
from .slot import Slot

FORMAT_VERSION = 2


def config_dir():
    """Where settings live. Alongside the other TG Studios apps."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, C.VENDOR, C.APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def default_board_path():
    return os.path.join(config_dir(), "board.json")


def app_dir():
    """The folder the app was installed or checked out into.

    Frozen, that is the folder holding the executable — which is where the demo
    pack sits, deliberately outside the bundle so it can be opened, replaced or
    added to like any other folder of sounds.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def demo_board_path():
    """The demo pack that ships with the app, if it is present."""
    return os.path.join(app_dir(), "demo", "demo-board.json")


class Board:
    """Everything the user can save, and the rules for loading it back."""

    def __init__(self):
        self.slots = [Slot(index=i, loop=(i // C.SLOTS_PER_BANK + 1) == C.LOOPING_BANK)
                      for i in range(C.TOTAL_SLOTS)]
        self.sfx_volume = C.DEFAULT_SFX_VOLUME
        self.bed_volume = C.DEFAULT_BED_VOLUME
        self.ducking = True
        self.duck_db = C.DEFAULT_DUCK_DB
        #: Whether system-wide hotkeys are armed. Off by default: while they
        #: are on this app owns those combinations across the whole machine,
        #: so it has to be something the user turned on deliberately.
        self.global_hotkeys_on = False
        self.last_sound_dir = ""
        #: Devices are remembered by name, because indices move around when
        #: something is plugged in or unplugged.
        self.device_name = None
        self.device_hostapi = None
        #: bank number -> {"name", "hostapi"}, or absent for the default
        #: output. Stored by name for the same reason as the main device:
        #: indices move when hardware is plugged in or unplugged.
        self.bank_devices = {}
        #: Whether the screen reader speaks when a slot starts or stops.
        #: On by default so nobody's setup changes under them. Off is for
        #: people who can hear the sound and do not need to be told about
        #: it - errors are always spoken either way.
        self.announce_playback = True
        self.path = None
        self.dirty = False

    # ------------------------------------------------------------ accessors --
    def __getitem__(self, index):
        return self.slots[index]

    def bank_slots(self, bank):
        start = (bank - 1) * C.SLOTS_PER_BANK
        return self.slots[start:start + C.SLOTS_PER_BANK]

    @property
    def assigned_count(self):
        return sum(1 for s in self.slots if s.is_assigned)

    @property
    def missing_slots(self):
        return [s for s in self.slots if s.is_missing]

    def search(self, query):
        """Slots whose name or filename contains ``query``, in board order."""
        needle = (query or "").strip().lower()
        if not needle:
            return [s for s in self.slots if s.is_assigned]
        found = []
        for slot in self.slots:
            if not slot.is_assigned:
                continue
            haystack = f"{slot.display_name} {os.path.basename(slot.filepath or '')}".lower()
            if needle in haystack:
                found.append(slot)
        return found

    def find_by_hotkey(self, key_code, modifiers):
        """The Miscellaneous slot bound to this key, if any."""
        for slot in self.bank_slots(C.BANK_MISC):
            if slot.key_code == key_code and (slot.modifiers or 0) == (modifiers or 0):
                return slot
        return None

    # ------------------------------------------------------------- relinking --
    def relink(self, folder, recursive=True):
        """Point missing slots at matching filenames under ``folder``.

        Matching is by filename, then by name with any extension. Returns the
        list of slots that were repaired.
        """
        index = {}
        walker = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
        for root, _dirs, files in walker:
            for name in files:
                index.setdefault(name.lower(), os.path.join(root, name))
                stem, ext = os.path.splitext(name)
                if ext.lower() in C.AUDIO_EXTENSIONS:
                    index.setdefault(stem.lower(), os.path.join(root, name))

        repaired = []
        for slot in self.missing_slots:
            base = os.path.basename(slot.filepath)
            stem = os.path.splitext(base)[0]
            found = index.get(base.lower()) or index.get(stem.lower())
            if found:
                slot.filepath = found
                repaired.append(slot)
        if repaired:
            self.dirty = True
        return repaired

    # ------------------------------------------------------------------- io --
    def to_dict(self):
        return {
            "app": C.APP_NAME,
            "format": FORMAT_VERSION,
            "sfx_volume": self.sfx_volume,
            "bed_volume": self.bed_volume,
            "ducking": self.ducking,
            "duck_db": self.duck_db,
            "global_hotkeys_on": bool(self.global_hotkeys_on),
            "device_name": self.device_name,
            "device_hostapi": self.device_hostapi,
            "bank_devices": {str(k): v for k, v in self.bank_devices.items()},
            "announce_playback": bool(self.announce_playback),
            "last_sound_dir": self.last_sound_dir,
            "slots": [s.to_dict() for s in self.slots],
        }

    def save(self, path=None):
        path = path or self.path or default_board_path()
        payload = json.dumps(self.to_dict(), indent=2)
        # Write beside the target then swap, so a crash mid-save cannot leave a
        # half-written board where the real one used to be.
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temp, path)
        self.path = path
        self.dirty = False
        return path

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        board = cls()
        board.path = path
        board.sfx_volume = float(data.get("sfx_volume", C.DEFAULT_SFX_VOLUME))
        board.bed_volume = float(data.get("bed_volume", C.DEFAULT_BED_VOLUME))
        board.ducking = bool(data.get("ducking", True))
        board.duck_db = float(data.get("duck_db", C.DEFAULT_DUCK_DB))
        board.global_hotkeys_on = bool(data.get("global_hotkeys_on", False))
        board.last_sound_dir = data.get("last_sound_dir") or ""
        board.device_name = data.get("device_name")
        board.device_hostapi = data.get("device_hostapi")
        board.announce_playback = bool(data.get("announce_playback", True))

        # Keys arrive as strings out of JSON and are used as ints everywhere
        # else. Anything unparseable is dropped rather than crashing a load,
        # because a board that will not open is worse than one output going
        # to the wrong card.
        raw_devices = data.get("bank_devices") or {}
        for key, spec in raw_devices.items():
            try:
                bank = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(spec, dict) and spec.get("name"):
                board.bank_devices[bank] = {"name": spec.get("name"),
                                           "hostapi": spec.get("hostapi")}

        raw = data.get("slots") or []
        # A board may store paths relative to itself, which is how the shipped
        # demo pack works — it has to resolve wherever the app is installed.
        base = os.path.dirname(os.path.abspath(path))
        for index in range(C.TOTAL_SLOTS):
            entry = raw[index] if index < len(raw) else None
            slot = Slot.from_dict(index, entry)
            if slot.filepath and not os.path.isabs(slot.filepath):
                slot.filepath = os.path.normpath(os.path.join(base, slot.filepath))
            board.slots[index] = slot
        board.dirty = False
        return board

    @property
    def is_legacy_source(self):
        return False

    @staticmethod
    def describe_source(path):
        """Whether a file on disk is one of ours or an old soundboard bank."""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return None
        if data.get("app") == C.APP_NAME:
            return "drop deck"
        if "slots" in data and "sfx_volume" in data:
            return "legacy soundboard"
        return None
