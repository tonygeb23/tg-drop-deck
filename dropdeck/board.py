"""A board: eighty slots, two volumes, and the settings that travel with them.

Boards are plain JSON. The old Tony Gebhard Show Soundboard files load without
conversion, that format is a subset of this one, so an existing bank opens and
keeps working.
"""

from __future__ import annotations

import json
import sys
import os

from . import constants as C
from .playlist import DropLibrary, Playlist
from .slot import Slot

FORMAT_VERSION = 2


#: What one saved station remembers. Everything the streamer needs plus a
#: name to pick it by.
STATION_FIELDS = (
    "stream_name", "stream_server", "stream_host", "stream_port",
    "stream_mount", "stream_user", "stream_password", "stream_format",
    "stream_bitrate", "stream_description", "stream_genre", "stream_url",
    "stream_public", "stream_mic", "stream_titles", "stream_stats_url",
)


def _stations(value):
    """Whatever was in the file, as a list of usable stations.

    A board file is not a trusted document, so anything that is not a dict
    with a name is dropped rather than allowed to become a station that
    explodes when you select it.
    """
    if not isinstance(value, list):
        return []
    out = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("stream_name") or "").strip():
            continue
        out.append({k: entry.get(k) for k in STATION_FIELDS if k in entry})
    return out


def _stream_port(value):
    """A port, or the default. A board file is not a trusted document."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return C.DEFAULT_STREAM_PORT
    return port if 1 <= port <= 65535 else C.DEFAULT_STREAM_PORT


def _stream_bitrate(value):
    """The nearest bitrate that is actually offered."""
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        return C.DEFAULT_STREAM_BITRATE
    return min(C.STREAM_BITRATES, key=lambda rate: abs(rate - wanted))


def _warn_seconds(value):
    """How long before the end to beep, off disk. Clamped, never rejected."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return C.DEFAULT_WARN_SECONDS
    if seconds != seconds:               # NaN
        return C.DEFAULT_WARN_SECONDS
    return max(C.MIN_WARN_SECONDS, min(C.MAX_WARN_SECONDS, seconds))


def _fade(value, fallback):
    """A bed fade off disk, in seconds, or ``fallback`` if it is not a number.

    Clamped rather than rejected. A hand-edited board asking for a minute-long
    fade is a typo, and a board that will not open is worse than one that opens
    with a sensible number in it.
    """
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return fallback
    if seconds != seconds:               # NaN
        return fallback
    return max(0.0, min(C.MAX_BED_FADE, seconds))


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

    Frozen, that is the folder holding the executable, which is where the demo
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
        #: Bank number -> the name the user gave it. Absent means the shipped
        #: name. Shared by reference with every Slot, so renaming a bank is one
        #: assignment and eighty labels follow - see Slot.bank_names.
        #:
        #: David Goldfield: a board you built yourself is not "Sound Effects"
        #: and "Dialog Drops", it is "Movie Clips" and "Sirens and Alarms".
        #: Renaming changes the name and nothing else - bank three is still the
        #: looping bank and bank four still takes custom hotkeys, because those
        #: are what the keys do, not what the tab says.
        self.bank_names = {}
        self.slots = [Slot(index=i, loop=(i // C.SLOTS_PER_BANK + 1) == C.LOOPING_BANK)
                      for i in range(C.TOTAL_SLOTS)]
        self._adopt_slots()
        self.sfx_volume = C.DEFAULT_SFX_VOLUME
        self.bed_volume = C.DEFAULT_BED_VOLUME
        self.ducking = True
        self.duck_db = C.DEFAULT_DUCK_DB
        #: How long a bed takes to reach full level, and to fall away when it
        #: is stopped. Zero means it plays exactly as recorded: a bed cued for
        #: its downbeat cannot ease in, which is Brian Hartgen's point and is
        #: why these are settings rather than the constants they used to be.
        self.bed_fade_in = C.FADE_IN_BED
        self.bed_fade_out = C.FADE_OUT_BED
        #: A third fader, for the playlist. Separate from the beds because a
        #: song under a presenter and a bed under a link are different jobs
        #: and never want the same level.
        self.playlist_volume = C.DEFAULT_PLAYLIST_VOLUME
        #: The running order. Saved with the board, because a board IS a show.
        self.playlist = Playlist()
        #: The drops you reach for over and over. Alt+D takes one at random.
        self.drops = DropLibrary()
        #: The microphone. Remembered by name, like every other device.
        #: Whether it was ON is deliberately NOT remembered: nothing opens a
        #: microphone except somebody pressing the key for it.
        self.mic_device_name = None
        self.mic_device_hostapi = None
        self.mic_gain_db = C.DEFAULT_MIC_GAIN_DB
        self.mic_monitor = False
        #: Which OUTPUT the monitored microphone comes out of. Separate from
        #: the banks' outputs on purpose: monitoring belongs in the
        #: presenter's headphones, and the show does not.
        self.mic_output_name = None
        self.mic_output_hostapi = None
        #: Whether system-wide hotkeys are armed. Off by default: while they
        #: are on this app owns those combinations across the whole machine,
        #: so it has to be something the user turned on deliberately.
        self.global_hotkeys_on = False
        #: The end of track cue: whether it beeps, and how long before the
        #: end. Off until somebody asks for it, because a beep nobody asked
        #: for turning up in a live show is not a feature.
        self.warn_before_end = C.DEFAULT_WARN_BEFORE_END
        self.warn_seconds = C.DEFAULT_WARN_SECONDS
        #: Whether the sound browser auditions each file as you reach it.
        #: Remembered, because somebody who wants it wants it every time.
        self.preview_sounds = False

        # Streaming. Off until it is set up, and it never turns itself on: a
        # program that could start broadcasting on its own is a program you
        # cannot trust in a room with a microphone in it.
        self.stream_server = "icecast"
        self.stream_host = ""
        self.stream_port = C.DEFAULT_STREAM_PORT
        self.stream_mount = C.DEFAULT_STREAM_MOUNT
        self.stream_user = C.DEFAULT_STREAM_USER
        self.stream_password = ""
        self.stream_format = "mp3"
        self.stream_bitrate = C.DEFAULT_STREAM_BITRATE
        self.stream_name = ""
        self.stream_description = ""
        self.stream_genre = ""
        self.stream_url = ""
        #: Where the LISTENERS are, when that is not where the audio is sent.
        #: A station running automation streams into a harbor and its
        #: audience is on the Icecast behind it, so the two are different
        #: addresses. Empty means work it out; see streamstats.candidates.
        self.stream_stats_url = ""
        #: Recording. Not part of a station, because you record the show
        #: rather than the server: switching station does not change it.
        self.record_format = "mp3"
        self.record_bitrate = 192
        self.record_folder = ""
        #: How many presses of Escape stop the show, and whether it fades.
        #:
        #: Chris Cooke, 5 September 2026: "I think an abrupt stop is better
        #: because if someone is running a mixer, they'll either fade it out
        #: themselves or more likely adjust it in their DAW."
        #:
        #: Two rather than three. Three shipped in 3.1 and the first person to
        #: use it counted four, because the first two presses only ANNOUNCE
        #: and a press that appears to do nothing reads as a press that did
        #: not land.
        self.stop_presses = C.DEFAULT_STOP_PRESSES
        self.stop_fade = True
        #: Extra inputs besides the microphone: a second mic, a games call,
        #: a browser through a virtual cable. Saved as plain dicts so an old
        #: build opening a new board ignores them rather than falling over.
        self.sources = []
        self.stream_public = False
        #: Put the microphone out on the stream. On by default, because a
        #: broadcast with no presenter in it is not what anybody meant, and
        #: separate from monitoring, which is only about hearing yourself.
        self.stream_mic = True
        #: Send the playlist's artist and title to the server, so listeners
        #: see what is playing.
        self.stream_titles = True
        #: Which half of a stereo input carries the voice. A hardware
        #: mixer feeding a line input puts it on one side, and taking the
        #: wrong one is silence.
        self.mic_channel = "mix"

        #: The microphone chain: gate, equaliser, compressor, limiter.
        #: Empty means the defaults, which are chosen for a spoken voice.
        #: Which of the warning shapes, and how loud. See C.CUE_SOUNDS.
        self.cue_sound = C.DEFAULT_CUE_SOUND
        self.cue_level_db = C.CUE_LEVEL_DB
        self.voice_on = True
        self.voice_settings = {}

        #: Every station this board knows, newest last. The live settings
        #: above are whichever one is loaded; this is the shelf they came off.
        self.stream_stations = []

        #: F7 and F8 change what you hear and not what goes out. On, because
        #: that is what a fader on a desk does and it is the only way to turn
        #: the music down to hear a screen reader without taking it off air.
        self.playlist_monitor_only = True
        self.last_sound_dir = ""
        #: Where running orders were last saved or opened. Its own, because a
        #: show's M3U and a show's sounds are rarely in the same folder.
        self.last_playlist_dir = ""
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
        #: How much the app says out loud - see constants.SPEECH_LEVELS. This
        #: supersedes announce_playback, which is still written to the file so
        #: an older build opening a newer board keeps behaving sensibly.
        self.speech_level = C.DEFAULT_SPEECH_LEVEL
        self.path = None
        self.dirty = False

    # ------------------------------------------------------------ accessors --
    def _adopt_slots(self):
        """Hand every slot this board's bank names, by reference."""
        for slot in self.slots:
            slot.bank_names = self.bank_names

    def bank_name(self, bank):
        """What bank ``bank`` is called: the user's name, or the shipped one."""
        return self.bank_names.get(bank) or C.BANK_TITLES[bank]

    def bank_short_name(self, bank):
        """The short form, for lists that span every bank."""
        return self.bank_names.get(bank) or C.BANK_SHORT[bank]

    def is_bank_renamed(self, bank):
        return bool(self.bank_names.get(bank))

    def rename_bank(self, bank, name):
        """Name a bank, or reset it with an empty name. Returns the name in use.

        The mapping is mutated rather than replaced, because every slot holds a
        reference to this one dict.
        """
        name = (name or "").strip()
        if name and name != C.BANK_TITLES[bank]:
            self.bank_names[bank] = name
        else:
            self.bank_names.pop(bank, None)
        self.dirty = True
        return self.bank_name(bank)

    def scan_folders(self, force=False):
        """Count what is in every folder slot. Returns the slots that hold one."""
        folders = [s for s in self.slots if s.is_folder]
        for slot in folders:
            slot.scan_folder(force=force)
        return folders

    def __getitem__(self, index):
        return self.slots[index]

    def bank_slots(self, bank):
        start = (bank - 1) * C.SLOTS_PER_BANK
        return self.slots[start:start + C.SLOTS_PER_BANK]

    def visible_slots(self, bank):
        """The slots in this bank that are still on the board."""
        return [slot for slot in self.bank_slots(bank) if not slot.hidden]

    def hidden_slots(self, bank=None):
        """The slots that have been taken off, in one bank or the whole board."""
        slots = self.bank_slots(bank) if bank else self.slots
        return [slot for slot in slots if slot.hidden]

    @property
    def assigned_count(self):
        return sum(1 for s in self.slots if s.is_assigned)

    @property
    def missing_slots(self):
        return [s for s in self.slots if s.is_missing]

    @property
    def folder_slots(self):
        return [s for s in self.slots if s.is_folder]

    def search(self, query):
        """Slots whose name or filename contains ``query``, in board order."""
        needle = (query or "").strip().lower()
        if not needle:
            return [s for s in self.slots if s.is_assigned and not s.hidden]
        found = []
        for slot in self.slots:
            # A removed slot is not offered. Jumping to a pad that is not on
            # the board lands the cursor nowhere.
            if not slot.is_assigned or slot.hidden:
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
        # Folders are indexed separately from files. A slot that held a folder
        # must be repaired with a folder: pointing it at a file that happens to
        # share the name would silently turn a random-pick slot into a one-shot.
        folders = {}
        walker = os.walk(folder) if recursive else [
            (folder, os.listdir(folder), os.listdir(folder))]
        for root, dirs, files in walker:
            for name in dirs:
                full = os.path.join(root, name)
                if os.path.isdir(full):
                    folders.setdefault(name.lower(), full)
            for name in files:
                full = os.path.join(root, name)
                if not os.path.isfile(full):
                    continue
                index.setdefault(name.lower(), full)
                stem, ext = os.path.splitext(name)
                if ext.lower() in C.AUDIO_EXTENSIONS:
                    index.setdefault(stem.lower(), full)

        repaired = []
        # The playlist is repaired out of the same walk. Two separate hunts
        # through a music library for the same folder is one hunt too many.
        repaired.extend(self.playlist.relink(index))
        self.drops.relink(index)
        for slot in self.missing_slots:
            base = os.path.basename(slot.filepath.rstrip("\\/"))
            stem = os.path.splitext(base)[0]
            if slot.folder_count is not None:
                found = folders.get(base.lower())
            else:
                found = index.get(base.lower()) or index.get(stem.lower())
            if found:
                slot.filepath = found
                slot.scan_folder(force=True)
                repaired.append(slot)
        if repaired:
            self.dirty = True
        return repaired

    # ------------------------------------------------------------------- io --
    # ------------------------------------------------------------ stations --
    def station_settings(self):
        """The station that is set up right now, as a saved station would be."""
        return {field: getattr(self, field) for field in STATION_FIELDS}

    def station_names(self):
        return [s.get("stream_name", "") for s in self.stream_stations]

    def load_station(self, name):
        """Put a saved station into the live settings. True if there was one."""
        for station in self.stream_stations:
            if station.get("stream_name") == name:
                for field in STATION_FIELDS:
                    if field in station:
                        setattr(self, field, station[field])
                self.stream_port = _stream_port(self.stream_port)
                self.stream_bitrate = _stream_bitrate(self.stream_bitrate)
                return True
        return False

    def save_station(self, name=None):
        """Remember the current settings under their own name.

        Saving over a station of the same name replaces it in place rather
        than adding a second one, because two stations called the same thing
        is a list nobody can use.
        """
        name = (name or self.stream_name or "").strip()
        if not name:
            return None
        self.stream_name = name
        entry = self.station_settings()
        # Worth saving. Without this a station saved in Preferences and
        # then cancelled out of was gone by the next launch, which is a
        # password somebody has to go and find again.
        self.dirty = True
        for index, station in enumerate(self.stream_stations):
            if station.get("stream_name") == name:
                self.stream_stations[index] = entry
                return entry
        self.stream_stations.append(entry)
        return entry

    def forget_station(self, name):
        before = len(self.stream_stations)
        self.stream_stations = [s for s in self.stream_stations
                                if s.get("stream_name") != name]
        gone = len(self.stream_stations) != before
        if gone:
            self.dirty = True
        return gone

    def to_dict(self):
        return {
            "app": C.APP_NAME,
            "format": FORMAT_VERSION,
            "sfx_volume": self.sfx_volume,
            "bed_volume": self.bed_volume,
            "ducking": self.ducking,
            "duck_db": self.duck_db,
            "bed_fade_in": self.bed_fade_in,
            "bed_fade_out": self.bed_fade_out,
            "bank_names": {str(k): v for k, v in self.bank_names.items()},
            "playlist_volume": self.playlist_volume,
            "mic_device_name": self.mic_device_name,
            "mic_device_hostapi": self.mic_device_hostapi,
            "mic_gain_db": self.mic_gain_db,
            "mic_monitor": bool(self.mic_monitor),
            "mic_output_name": self.mic_output_name,
            "mic_output_hostapi": self.mic_output_hostapi,
            "playlist": self.playlist.to_dict(),
            "drops": self.drops.to_dict(),
            "global_hotkeys_on": bool(self.global_hotkeys_on),
            "device_name": self.device_name,
            "device_hostapi": self.device_hostapi,
            "bank_devices": {str(k): v for k, v in self.bank_devices.items()},
            "announce_playback": bool(self.announce_playback),
            "speech_level": self.speech_level,
            "warn_before_end": bool(self.warn_before_end),
            "warn_seconds": float(self.warn_seconds),
            "preview_sounds": bool(self.preview_sounds),
            "stream_server": self.stream_server,
            "stream_host": self.stream_host,
            "stream_port": int(self.stream_port),
            "stream_mount": self.stream_mount,
            "stream_user": self.stream_user,
            "stream_password": self.stream_password,
            "stream_format": self.stream_format,
            "stream_bitrate": int(self.stream_bitrate),
            "stream_name": self.stream_name,
            "stream_description": self.stream_description,
            "stream_genre": self.stream_genre,
            "stream_url": self.stream_url,
            "stream_stats_url": self.stream_stats_url,
            "record_format": self.record_format,
            "record_bitrate": int(self.record_bitrate),
            "record_folder": self.record_folder,
            "stop_presses": int(self.stop_presses),
            "stop_fade": bool(self.stop_fade),
            "sources": [dict(entry) for entry in self.sources],
            "stream_public": bool(self.stream_public),
            "stream_mic": bool(self.stream_mic),
            "stream_titles": bool(self.stream_titles),
            "playlist_monitor_only": bool(self.playlist_monitor_only),
            "stream_stations": list(self.stream_stations),
            "mic_channel": self.mic_channel,
            "cue_sound": str(self.cue_sound),
            "cue_level_db": float(self.cue_level_db),
            "voice_on": bool(self.voice_on),
            "voice_settings": dict(self.voice_settings),
            "last_sound_dir": self.last_sound_dir,
            "last_playlist_dir": self.last_playlist_dir,
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
        board.playlist_volume = float(
            data.get("playlist_volume", C.DEFAULT_PLAYLIST_VOLUME))
        board.mic_device_name = data.get("mic_device_name")
        board.mic_device_hostapi = data.get("mic_device_hostapi")
        try:
            board.mic_gain_db = max(C.MIN_MIC_GAIN_DB,
                                    min(C.MAX_MIC_GAIN_DB,
                                        float(data.get("mic_gain_db", 0.0))))
        except (TypeError, ValueError):
            board.mic_gain_db = C.DEFAULT_MIC_GAIN_DB
        board.mic_monitor = bool(data.get("mic_monitor", False))
        board.mic_output_name = data.get("mic_output_name")
        board.mic_output_hostapi = data.get("mic_output_hostapi")
        board.bed_fade_in = _fade(data.get("bed_fade_in"), C.FADE_IN_BED)
        board.bed_fade_out = _fade(data.get("bed_fade_out"), C.FADE_OUT_BED)

        # Bank names. Keys arrive as strings out of JSON and are ints
        # everywhere else; anything unparseable or out of range is dropped
        # rather than crashing a load, because a board that will not open is
        # worse than a tab with its original name on it.
        for key, value in (data.get("bank_names") or {}).items():
            try:
                bank = int(key)
            except (TypeError, ValueError):
                continue
            if 1 <= bank <= C.BANK_COUNT and isinstance(value, str) and value.strip():
                board.bank_names[bank] = value.strip()[:C.MAX_BANK_NAME]
        board.global_hotkeys_on = bool(data.get("global_hotkeys_on", False))
        board.warn_before_end = bool(data.get("warn_before_end",
                                              C.DEFAULT_WARN_BEFORE_END))
        board.warn_seconds = _warn_seconds(data.get("warn_seconds"))
        board.preview_sounds = bool(data.get("preview_sounds", False))
        board.stream_server = (data.get("stream_server") or "icecast")
        board.stream_host = data.get("stream_host") or ""
        board.stream_port = _stream_port(data.get("stream_port"))
        board.stream_mount = data.get("stream_mount") or C.DEFAULT_STREAM_MOUNT
        board.stream_user = data.get("stream_user") or C.DEFAULT_STREAM_USER
        board.stream_password = data.get("stream_password") or ""
        board.stream_format = (data.get("stream_format") or "mp3")
        board.stream_bitrate = _stream_bitrate(data.get("stream_bitrate"))
        board.stream_name = data.get("stream_name") or ""
        board.stream_description = data.get("stream_description") or ""
        board.stream_genre = data.get("stream_genre") or ""
        board.stream_url = data.get("stream_url") or ""
        board.stream_stats_url = data.get("stream_stats_url") or ""
        fmt = data.get("record_format")
        board.record_format = fmt if fmt in C.RECORD_FORMAT_KEYS else "mp3"
        board.record_bitrate = _stream_bitrate(data.get("record_bitrate", 192))
        board.record_folder = data.get("record_folder") or ""
        try:
            board.stop_presses = max(C.MIN_STOP_PRESSES,
                                     min(C.MAX_STOP_PRESSES,
                                         int(data.get("stop_presses",
                                                      C.DEFAULT_STOP_PRESSES))))
        except (TypeError, ValueError):
            board.stop_presses = C.DEFAULT_STOP_PRESSES
        board.stop_fade = bool(data.get("stop_fade", True))
        found = data.get("sources")
        board.sources = ([entry for entry in found if isinstance(entry, dict)]
                         if isinstance(found, list) else [])
        board.stream_public = bool(data.get("stream_public", False))
        board.stream_mic = bool(data.get("stream_mic", True))
        board.stream_titles = bool(data.get("stream_titles", True))
        board.playlist_monitor_only = bool(
            data.get("playlist_monitor_only", True))
        channel = data.get("mic_channel")
        board.mic_channel = channel if channel in ("mix", "left", "right") else "mix"
        sound = data.get("cue_sound")
        board.cue_sound = (sound if sound in C.CUE_SOUND_KEYS
                           else C.DEFAULT_CUE_SOUND)
        try:
            board.cue_level_db = max(C.MIN_CUE_LEVEL_DB,
                                     min(C.MAX_CUE_LEVEL_DB,
                                         float(data.get("cue_level_db",
                                                        C.CUE_LEVEL_DB))))
        except (TypeError, ValueError):
            board.cue_level_db = C.CUE_LEVEL_DB
        board.voice_on = bool(data.get("voice_on", True))
        settings = data.get("voice_settings")
        board.voice_settings = dict(settings) if isinstance(settings, dict) else {}
        board.stream_stations = _stations(data.get("stream_stations"))
        # A board written before stations existed still has one set up, and
        # losing it on upgrade would be the worst kind of small betrayal.
        if not board.stream_stations and board.stream_host:
            board.stream_stations = [board.station_settings()]
        board.last_sound_dir = data.get("last_sound_dir") or ""
        board.last_playlist_dir = data.get("last_playlist_dir") or ""
        board.device_name = data.get("device_name")
        board.device_hostapi = data.get("device_hostapi")
        board.announce_playback = bool(data.get("announce_playback", True))
        # A board written before 2.2.0 has no speech_level. Someone who had
        # already turned playback speech off was asking for a quieter app, so
        # they are carried straight to the level that means exactly that.
        level = data.get("speech_level")
        if level not in C.SPEECH_LEVELS:
            level = (C.SPEECH_ALL if board.announce_playback
                     else C.SPEECH_ESSENTIAL)
        board.speech_level = level

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

        base_dir = os.path.dirname(os.path.abspath(path))
        board.playlist = Playlist.from_dict(data.get("playlist"), base_dir=base_dir)
        board.drops = DropLibrary.from_dict(data.get("drops"), base_dir=base_dir)

        raw = data.get("slots") or []
        # A board may store paths relative to itself, which is how the shipped
        # demo pack works, it has to resolve wherever the app is installed.
        base = os.path.dirname(os.path.abspath(path))
        for index in range(C.TOTAL_SLOTS):
            entry = raw[index] if index < len(raw) else None
            slot = Slot.from_dict(index, entry)
            if slot.filepath and not os.path.isabs(slot.filepath):
                slot.filepath = os.path.normpath(os.path.join(base, slot.filepath))
            board.slots[index] = slot
        board._adopt_slots()
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
