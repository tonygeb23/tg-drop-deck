"""A board: eighty slots, two volumes, and the settings that travel with them.

Boards are plain JSON. The old Tony Gebhard Show Soundboard files load without
conversion, that format is a subset of this one, so an existing bank opens and
keeps working.
"""

from __future__ import annotations

import hashlib
import collections
import copy
import json
import sys
import os
import re
import threading
import time

from . import constants as C
from . import secrets
from .playlist import DropLibrary, Playlist
from .slot import Slot

FORMAT_VERSION = 2


#: What one saved station remembers. Everything the streamer needs plus a
#: name to pick it by.
STATION_FIELDS = (
    "stream_name", "video_name",
    "stream_server", "stream_host", "stream_port",
    "stream_mount", "stream_user", "stream_password", "stream_format",
    "stream_bitrate", "stream_description", "stream_genre", "stream_url",
    "stream_public", "stream_mic", "stream_titles", "stream_stats_url",
    # The video side and the picture belong to the station too: a YouTube
    # station needs them and the Icecast station on the same board does not.
    "video_server", "video_host", "video_key", "live_to",
    "picture", "picture_file", "picture_clock", "camera", "screen",
    "split_corner",
    "text_places", "colour_background", "colour_text", "colour_accent",
    "video_width", "video_height", "video_fps", "video_bitrate",
)


def _colour(raw, fallback):
    """A colour NAME out of a board file, whitelisted like everything else.

    An unknown name becomes the default rather than being carried forward as
    a string nothing will ever draw. A board written by a later version with
    more colours in it therefore opens and looks ordinary, instead of opening
    and drawing nothing.
    """
    from . import colours
    return raw if raw in colours.BY_NAME else fallback


def _text_places(raw):
    """What is on top of the picture, whitelisted out of a board file.

    A place whose kind is not one this build knows becomes "nothing" rather
    than raising, and rather than being carried forward as a string nothing
    will ever draw. Same rule as every other setting here.
    """
    out = {key: {"kind": C.TEXT_NONE, "words": "", "file": ""}
           for key in C.PLACES_ORDER}
    if not isinstance(raw, dict):
        return out
    for key, spot in raw.items():
        if key not in out or not isinstance(spot, dict):
            continue
        kind = spot.get("kind")
        out[key]["kind"] = kind if kind in C.TEXT_KINDS else C.TEXT_NONE
        out[key]["words"] = str(spot.get("words") or "")[:200]
        out[key]["file"] = str(spot.get("file") or "")
    return out


def _video_number(value, fallback, low, high):
    """A number out of a board file, clamped, or the default.

    Same shape as _stream_port and _stream_bitrate above it. A picture size of
    nought or a frame rate of a million is a crash at the moment somebody
    goes live, which is the worst moment this app has.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _rtmp_address(value):
    """An RTMP address out of a board file, or "" so the default is used.

    Everything else on this page is whitelisted and this was free text
    handed straight to FFmpeg, which writes to a file, an HTTP endpoint or a
    UDP socket as cheerfully as to an ingest. A board file is plain JSON,
    people send each other boards, and fb40 is a whole report about people
    opening ones they were given. One press of Ctrl+B on such a board would
    have sent a live microphone wherever its author chose, while the
    pre-flight read the address out as "Custom RTMP server".

    `RtmpDestination.url` refuses it too. This one keeps it out of the
    settings in the first place, so nothing downstream ever sees it and the
    address box does not show somebody a path they did not type.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        import urllib.parse
        scheme = urllib.parse.urlparse(text).scheme.lower()
    except Exception:
        return ""
    if scheme in ("rtmp", "rtmps"):
        return text
    # **An address with NO scheme is kept, and that is on purpose.** It is
    # what somebody typed who left the rtmp off, and erasing it means they
    # open the app to an empty box with nothing to correct. It cannot reach
    # the encoder either way: `RtmpDestination.url` is the hard gate and
    # refuses anything that is not rtmp or rtmps. What must never survive is
    # a scheme that names another kind of output, or a Windows path, because
    # those are the shapes that would have worked.
    if scheme or text.startswith("\\\\") or text[1:3] == ":\\" or \
            text.startswith("/"):
        return ""
    return text


def web_address(value):
    """Where listeners are counted, out of a board file: http or https only.

    It is handed to urllib, which opens `file:` and `ftp:` as readily as a
    web page, so a board could point it at a file on this computer or a
    server of its author's choosing. Nothing else was ever going to work in
    it anyway: a statistics page is a web page.
    """
    text = str(value or "").strip()
    try:
        import urllib.parse
        parts = urllib.parse.urlsplit(text)
    except Exception:
        return ""
    if parts.scheme.lower() in ("http", "https") and parts.netloc:
        return text
    return ""


def local_folder(value):
    """A folder on this computer, by its whole path, or "".

    For where recordings go. A board is plain JSON that people send each
    other, and a recording folder of `\\\\somebody.example@SSL\\DavWWWRoot`
    writes the show, microphone and all, to their server, and makes Windows
    offer them the user's sign in on the way. So a board may only name a
    drive letter folder here; a share, a WebDAV address or a relative path is
    dropped and the usual folder used. Sounds on a network share are a
    different matter and are left alone: people keep music on a NAS.
    """
    text = str(value or "").strip()
    if not text or text.startswith(("\\\\", "//")):
        return ""
    drive, rest = os.path.splitdrive(text)
    if not re.fullmatch(r"[A-Za-z]:", drive) or not rest.startswith(("\\", "/")):
        return ""
    return text


def network_folder(value):
    """A folder on a share, `\\\\server\\share\\...`, or "".

    Not the device namespaces `\\\\?\\` and `\\\\.\\`, which are not folders
    anybody records into.
    """
    text = str(value or "").strip()
    if not text.startswith(("\\\\", "//")) or text[2:3] in ("?", "."):
        return ""
    drive, _rest = os.path.splitdrive(text)
    if drive.replace("/", "\\").strip("\\").count("\\") < 1:
        return ""
    return text


#: Things about THIS computer that must never travel in a board file, kept
#: beside the board in the settings folder: the network folders recordings
#: were sent to from Preferences here, and whether the first start of this
#: version has tied the stream keys 3.10.1 kept. A board is sent to people;
#: this file is not, which is the whole of why these are not board fields.
MACHINE_FILE = "this computer.json"


def machine_state():
    """What MACHINE_FILE holds, or {}. Never raises."""
    try:
        with open(os.path.join(config_dir(), MACHINE_FILE), "r",
                  encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_machine_state(data):
    """Write MACHINE_FILE. True when it landed. Never raises."""
    path = os.path.join(config_dir(), MACHINE_FILE)
    temp = path + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        _replace(temp, path)
        return True
    except Exception:
        try:
            os.remove(temp)
        except OSError:
            pass
        return False


def _folder_key(path):
    """A folder in one spelling, from the string alone: never by asking a
    share, which could be anybody's server."""
    return os.path.normcase(os.path.normpath(str(path).strip()))


def picked_record_folder(value):
    """A network folder chosen in Preferences on this computer, or "".

    The one way a share is accepted as a board's recording folder. People
    record to a NAS, and a folder picked here is the user's own; a share
    arriving in a board file from somebody else is accepted only if it is
    one the user picked here themselves.
    """
    text = network_folder(value)
    if not text:
        return ""
    wanted = _folder_key(text)
    picked = machine_state().get("record_folders") or []
    if any(isinstance(p, str) and _folder_key(p) == wanted for p in picked):
        return text
    return ""


def usable_record_folder(value):
    """The board's recording folder if THIS computer may record there, else "".

    A folder on this computer, or a share picked in Preferences here. Anything
    else, a share or a web folder named by a board from somebody else, or a
    relative path, is not used here and the usual folder is: the show,
    microphone and all, would otherwise go to whatever server the board's
    author named. The board's own field is never changed for it.
    """
    return local_folder(value) or picked_record_folder(value)


def record_folder_said(value):
    """Has this computer already said it will not record to that folder."""
    key = _folder_key(value)
    return any(isinstance(p, str) and _folder_key(p) == key
               for p in machine_state().get("record_folders_said") or [])


def note_record_folder_said(value):
    """Write down that it was said, so it is said once per folder."""
    state = machine_state()
    said = [p for p in state.get("record_folders_said") or []
            if isinstance(p, str)]
    if not any(_folder_key(p) == _folder_key(value) for p in said):
        said.append(str(value))
        state["record_folders_said"] = said
        return save_machine_state(state)
    return True


def remember_record_folder(value):
    """Note a network folder chosen in Preferences, so boards may use it."""
    text = network_folder(value)
    if not text:
        return False
    state = machine_state()
    picked = [p for p in state.get("record_folders") or []
              if isinstance(p, str)]
    if not any(_folder_key(p) == _folder_key(text) for p in picked):
        picked.append(text)
        state["record_folders"] = picked
        return save_machine_state(state)
    return True


def for_export(data):
    """A board's dict with what is the user's own left out, for an export.

    An export is made to be handed to somebody. The Icecast password and a
    stream key the credential store refused are in a board's own file so the
    board works; in an export they would let whoever receives it broadcast as
    the user. The recording folder and the last folders sounds and running
    orders came from are paths with the user's name in them and mean nothing
    on another computer. The words on the picture read from a file are a
    path on this computer for the same reason. Every saved station is cleaned
    the same way, because each one carries its own copy.
    """
    out = copy.deepcopy(data)

    def clean(entry):
        for field in ("stream_password", "video_key"):
            if field in entry:
                entry[field] = ""
        for spot in (entry.get("text_places") or {}).values():
            if isinstance(spot, dict):
                spot["file"] = ""

    clean(out)
    for field in ("record_folder", "last_sound_dir", "last_playlist_dir"):
        out[field] = ""
    # The plugin by its file name alone: its folder can be under the user's
    # own AppData, with their Windows name in it. The receiving computer
    # finds its own copy by that name (ui._resolve_plugin_name).
    voice = out.get("voice_settings")
    if isinstance(voice, dict) and voice.get("plugin"):
        voice["plugin"] = _basename(str(voice["plugin"]))
    for station in out.get("stream_stations") or []:
        if isinstance(station, dict):
            clean(station)
    return out


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


def _talk_db(value):
    """How much further duck while talking goes, off disk, in decibels.

    Clamped into what Preferences offers; anything that is not a number is
    the default. Said as a positive number of decibels DOWN.
    """
    try:
        db = abs(float(value))
    except (TypeError, ValueError):
        return C.DEFAULT_TALK_DUCK_DB
    if db != db:                         # NaN
        return C.DEFAULT_TALK_DUCK_DB
    return max(C.MIN_TALK_DUCK_DB, min(C.MAX_TALK_DUCK_DB, db))


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


#: The folder a portable copy keeps its settings in, beside the program.
#:
#: HarmonicaPlayer, 20 September 2026, running the zip: "since I am running
#: the portable copy of TG Drop Deck, why don't it make a folder called
#: userdata inside of application directory instead of writing the data in a
#: folder called TG Studios in %appdata% on hard drive?"
#:
#: He is right, and it is not only tidiness. A portable copy is a folder you
#: can move, copy to a stick or keep on a second drive, and a portable copy
#: that leaves its board behind in AppData is portable in name only: take the
#: folder somewhere else and the program is empty. His own use is the plain
#: one - he wants the whole program in one place he can delete.
PORTABLE_DATA_DIR = "userdata"

#: Set this to a folder and everything goes there instead. It exists so the
#: portable path can be tested without a frozen build, and it is the escape
#: hatch for anybody who wants their settings on a different drive.
DATA_ENV = "TGDROPDECK_DATA"

#: What happened to the settings folder at startup, for the frame to say once
#: it has a window to say it in. `config_dir` runs before wx exists - it runs
#: before the error log is installed - so it cannot speak for itself.
data_note = ""

_resolved = None
_resolved_why = ""
_resolved_for = None

#: How each answer reads in a diagnostic, in plain words rather than a path.
#: A path carries the user's name and the shape of their disk, and the
#: feedback promise is that neither is ever sent. Which KIND of folder it is
#: answers every support question the path would have.
DATA_KINDS = {
    "beside": "beside the program",
    "portable": "beside the program",
    "named": "a folder of your own",
    "named-refused": "in AppData, because the folder you named refused",
    "portable-refused": "in AppData, because this folder is read only",
    "appdata": "in AppData",
}


def data_kind():
    """Which settings folder this copy is using, in words. Never a path."""
    config_dir()
    return DATA_KINDS.get(_resolved_why, "in AppData")


def legacy_config_dir():
    """Where settings lived before there was anywhere else: %APPDATA%.

    Still the answer for an installed copy, which is most people. An installed
    program's folder is not the user's to write in as a rule, it is replaced
    wholesale by the installer, and the uninstaller would carry the board away
    with it.
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, C.VENDOR, C.APP_NAME)


def _is_portable_copy():
    """Is this the zip, unpacked wherever somebody put it.

    Asked of `appupdate`, which already had to answer it for a different
    reason and answers it the way that cannot be fooled by a path: Inno Setup
    leaves an uninstaller beside what it installed and nothing puts one in a
    zip. Imported here rather than at the top because this module is imported
    by almost everything and that one is not.
    """
    try:
        from . import appupdate
        return bool(appupdate.is_portable())
    except Exception:
        return False


def _usable(path):
    """Can we really write there. Asked by writing, not by reading rights."""
    probe = os.path.join(path, ".dropdeck-write-test")
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def _choose_config_dir():
    """Work out where settings go, once, in order of who asked loudest.

    1. `TGDROPDECK_DATA`, when somebody has named a folder outright.
    2. A `userdata` folder that is ALREADY beside the program. Making that
       folder by hand is how an installed copy opts in, and it is the one
       instruction that fits in a sentence.
    3. A portable copy makes that folder for itself, because that is what
       portable is supposed to mean.
    4. Otherwise %APPDATA%, which is where it has always been.

    Any of the first three that cannot be written to falls through to the
    next, so a zip unpacked into Program Files, or run from a read only
    stick, still starts and still keeps its settings. Falling over because
    a folder is read only is not an option: this runs before the app has a
    window to apologise in.
    """
    named = (os.environ.get(DATA_ENV) or "").strip()
    if named:
        if _usable(named):
            return os.path.abspath(named), "named"
        # Said out loud later. Silently ignoring a folder somebody asked for
        # by name is how settings end up in two places.
        return legacy_config_dir(), "named-refused"
    beside = os.path.join(app_dir(), PORTABLE_DATA_DIR)
    if os.path.isdir(beside) and _usable(beside):
        return os.path.abspath(beside), "beside"
    if _is_portable_copy():
        if _usable(beside):
            return os.path.abspath(beside), "portable"
        return legacy_config_dir(), "portable-refused"
    return legacy_config_dir(), "appdata"


def _cache_key():
    """Everything the answer depends on that could conceivably change.

    In a running app, none of it does. In the tests several of them do:
    `test_3_8_3` moves `APPDATA` mid-run and expects the board to follow it.
    Keying the cache on the inputs rather than caching outright keeps that
    true and still costs one probe per distinct answer, which matters
    because a portable copy proves the folder is writable BY WRITING and
    `config_dir` is called on every save and every logged fault.
    """
    try:
        here = app_dir()
    except Exception:
        here = ""
    return (os.environ.get("APPDATA"), os.environ.get(DATA_ENV), here)


def config_dir():
    """Where settings live. Beside a portable copy, or in %APPDATA%.

    Worked out once and remembered, because it must not change underneath a
    running app: the board is autosaved to `default_board_path()` and the
    last-board note is written beside it, and two different answers in one
    session would leave them in two different folders.
    """
    global _resolved, _resolved_why, _resolved_for, data_note
    key = _cache_key()
    if _resolved is None or key != _resolved_for:
        _resolved_for = key
        try:
            path, why = _choose_config_dir()
        except Exception:
            # Wrapped as a whole rather than step by step, because the rule
            # is about the outcome and not about any one step: this runs
            # before wx exists and before the error log is installed, so
            # anything raised here is a program that does not start. There
            # is always an answer, and it is the one it has always been.
            path, why = legacy_config_dir(), "appdata"
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            path = legacy_config_dir()
            os.makedirs(path, exist_ok=True)
            why = "appdata"
        _resolved = path
        _resolved_why = why
        try:
            data_note = _settle_in(path, why)
        except Exception:
            data_note = ""
    return _resolved


def _forget_config_dir():
    """Testing only. There is no way to change this from inside the app."""
    global _resolved, _resolved_why, _resolved_for, data_note
    _resolved = None
    _resolved_why = ""
    _resolved_for = None
    data_note = ""


#: Written into the new folder when settings are brought over, so a second
#: run does not do it again and support can see it happened and when.
MOVED_NOTE = "moved-from-appdata.txt"


def _settle_in(path, why):
    """Bring the old settings over the first time, and say what happened.

    Copied, never moved. The old folder is left exactly as it was, so a
    portable copy that turns out to be a bad idea is undone by deleting one
    folder, and nobody loses a board to a feature they did not ask for. The
    user is told they may now delete it, which is the part HarmonicaPlayer
    actually wanted: "then I can delete the TG studios folder on HD to free
    space".
    """
    if why == "named-refused":
        # No environment variable name and no path: both are read out
        # character by character by a screen reader and neither is something
        # the person hearing it can act on in the moment.
        return ("The folder you set Drop Deck to keep its settings in could "
                "not be written to, so they are in the usual place instead")
    if why == "portable-refused":
        return ("Drop Deck cannot write to its own folder, so settings are "
                "in AppData rather than beside the program")
    if why in ("appdata",):
        return ""
    old = legacy_config_dir()
    if same_path(old, path):
        return ""
    if os.path.exists(os.path.join(path, MOVED_NOTE)):
        return ""
    if os.path.exists(os.path.join(path, "board.json")):
        # Already somebody's settings folder. Copying over the top of it is
        # the one thing that could lose work here.
        return ""
    brought = _copy_settings(old, path)
    if not brought:
        return ""
    try:
        with open(os.path.join(path, MOVED_NOTE), "w",
                  encoding="utf-8") as handle:
            handle.write(
                "TG Drop Deck copied these settings out of\n"
                "    %s\non %s, and changed nothing there.\n\n"
                "That folder can now be deleted.\n\n"
                "Stream keys are in neither folder. Windows Credential "
                "Manager keeps those, for this user on this machine, so a "
                "copy of this folder taken to another machine or another "
                "sign-in will ask for the stream key again.\n\n"
                "What was brought over:\n%s\n"
                % (old, time.strftime("%Y-%m-%d %H:%M"),
                   "\n".join("    " + name for name in sorted(brought))))
    except OSError:
        pass
    # Short on purpose. It is spoken at startup, once ever, at the end of a
    # line that already has several things in it, and the whole explanation
    # is in the file above for anybody who wants it. No trailing full stop:
    # the startup line joins with ". " and two in a row is heard.
    #
    # **And it must not say "beside the program" when it is not.** Measured
    # with TGDROPDECK_DATA pointed elsewhere: the app said the settings were
    # in the userdata folder beside the program, which was untrue, in the
    # one sentence that tells somebody it is safe to delete the old folder.
    where = ("the %s folder beside the program" % PORTABLE_DATA_DIR
             if why in ("beside", "portable") else "the folder you asked for")
    # **The permission to delete is conditional on the board arriving.**
    # `_copy_settings` skips a file it cannot read, which is a real state on
    # this machine: a board.json held open by Dropbox mid sync, or by a
    # virus scanner. Saying "can be deleted" over a board that did not come
    # across is telling somebody to delete their only copy of it.
    if "board.json" in brought or not os.path.exists(
            os.path.join(old, "board.json")):
        return ("Your settings are now in %s, and the old copy in AppData "
                "can be deleted" % where)
    return ("Your settings are now in %s, but your board could not be "
            "copied, so do NOT delete the old folder in AppData yet. Close "
            "anything that may be holding the file and start Drop Deck "
            "again" % where)


def _copy_settings(old, new):
    """Copy one settings folder into another. Returns what was brought.

    Never raises and never overwrites. A file that will not copy is skipped
    rather than stopping the rest: half the settings is better than none, and
    the original is still there either way.
    """
    import shutil
    brought = []
    try:
        entries = sorted(os.listdir(old))
    except OSError:
        return brought
    for entry in entries:
        source = os.path.join(old, entry)
        target = os.path.join(new, entry)
        if os.path.exists(target):
            continue
        try:
            if os.path.isdir(source):
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
                # copy2 brings the read only bit with it, and a read only
                # board.json is an app that cannot autosave, silently, for
                # the rest of its life. The copy is the user's working file
                # now; the original keeps whatever it had.
                try:
                    os.chmod(target, os.stat(target).st_mode | 0o200)
                except OSError:
                    pass
            brought.append(entry)
        except (OSError, shutil.Error):
            continue
    # **Whenever there IS one, not only when this copied it.** A
    # `last_board.json` already sitting in the new folder is skipped by the
    # loop above, so it never appears in `brought`, so it was never
    # repointed, and it went on naming a board in the folder the user has
    # just been told they may delete.
    if os.path.exists(os.path.join(new, LAST_BOARD_FILE)):
        _repoint_last_board(old, new)
    return brought


def _repoint_last_board(old, new):
    """Follow the remembered board into its new home.

    `last_board.json` holds an ABSOLUTE path, and the one thing it usually
    points at is `board.json` in the old settings folder. Copied across
    untouched it would send the app straight back to the folder the user has
    just been told they can delete - and then deleting it would lose the
    board after all, which is the exact fault fb40 was about.
    """
    try:
        with open(os.path.join(new, LAST_BOARD_FILE), "r",
                  encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return
    path = data.get("path") if isinstance(data, dict) else None
    if not isinstance(path, str) or not path.strip():
        return
    inside = os.path.normcase(os.path.abspath(old)) + os.sep
    if not os.path.normcase(os.path.abspath(path)).startswith(inside):
        return
    moved = os.path.join(new, os.path.relpath(os.path.abspath(path),
                                              os.path.abspath(old)))
    if not os.path.exists(moved):
        return
    try:
        with open(os.path.join(new, LAST_BOARD_FILE), "w",
                  encoding="utf-8") as handle:
            json.dump({"path": moved}, handle)
    except OSError:
        pass


def default_board_path():
    return os.path.join(config_dir(), "board.json")


#: Which board was open last, so the next start opens that one again.
#:
#: fb40, 19 September 2026, on 3.8.2: "if I rename, move or copy the json
#: file, it acts as if it was never set up." Every start opened board.json in
#: the settings folder and nothing else, whichever board had been in use. A
#: board opened with Ctrl+O, or saved somewhere with Save board as, was
#: autosaved where it lived all session and then forgotten at the next start,
#: so the streaming set up in it seemed to have vanished.
LAST_BOARD_FILE = "last_board.json"


def remembered_board_path():
    """The board that was open last time, or None if none was remembered."""
    try:
        with open(os.path.join(config_dir(), LAST_BOARD_FILE), "r",
                  encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    path = data.get("path") if isinstance(data, dict) else None
    return path if isinstance(path, str) and path.strip() else None


def same_path(a, b):
    """Two paths naming the same file, as Windows compares them."""
    if not a or not b:
        return False
    return (os.path.normcase(os.path.abspath(a))
            == os.path.normcase(os.path.abspath(b)))


def remember_board_path(path):
    """Write down which board is open. True if it is now remembered.

    Called on every save, so it writes only when the answer changes.
    """
    if not path:
        return False
    path = os.path.abspath(path)
    if same_path(remembered_board_path(), path):
        return True
    target = os.path.join(config_dir(), LAST_BOARD_FILE)
    temp = target + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump({"path": path}, handle)
        _replace(temp, target)
        return True
    except Exception:
        return False


def _replace(source, target, attempts=5):
    """os.replace, retried. Dropbox and virus scanners hold new files open.

    Not retried when the target is marked read only: that is a setting, not
    a moment, and waiting a second for it froze the window on every save.
    """
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            read_only = (os.path.exists(target)
                         and not os.access(target, os.W_OK))
            if read_only or attempt == attempts - 1:
                raise
            time.sleep(0.1 * (attempt + 1))


#: What a board remembers about a file it did not read. See claim_path.
#: NOTHING_THERE: there was no file, so one appearing is somebody else's.
#: UNREADABLE: there was one it could not read, so it is never written over.
NOTHING_THERE = "nothing there"
UNREADABLE = "could not be read"


def _stamp_of(handle, raw):
    info = os.fstat(handle.fileno())
    return (info.st_size, info.st_mtime_ns, hashlib.sha1(raw).hexdigest())


def _disk_stamp(path):
    """(size, modified, content hash) of a file, or None if it cannot be read.

    Size and time are the quick question. The hash is the real one, asked
    only when those two differ, so something that touched the file without
    changing it does not count as somebody else's edit. Size and time come
    from the OPEN handle, so they describe exactly the bytes that were read:
    a separate stat could see a write that landed in between, and that write
    would then never be noticed and would be saved over.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
            return _stamp_of(handle, raw)
    except OSError:
        return None


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


# ------------------------------------------------- paths that travel well --
def _basename(path):
    """The last part of a path written on EITHER system.

    A board made on the Mac holds "/Users/..." and one made here holds
    "G:\\My Drive\\...". Both have to give up their file name on both, or a
    relink compares a whole foreign path against file names and matches
    nothing, which is exactly what Siena saw on the Mac on 12 October 2026:
    "16 sounds still missing" with every one of them in the folder she chose.
    """
    return re.split(r"[\\/]", (path or "").rstrip("\\/"))[-1]


def _portable(path, base):
    """``path`` relative to ``base`` if it is under it, with forward slashes.

    Forward slashes because the Mac reads them and Windows reads both. A path
    anywhere else, on another drive or not a full path at all, is handed back
    as it came.
    """
    if not path or not base or not os.path.isabs(path):
        return path
    try:
        full = os.path.abspath(path)
        if (os.path.normcase(os.path.commonpath([full, base]))
                != os.path.normcase(os.path.abspath(base))):
            return path
        return os.path.relpath(full, base).replace("\\", "/")
    except ValueError:
        # A different drive, or a mix of absolute and relative. Not ours to
        # shorten.
        return path


def _map_sound_paths(data, change):
    """Rewrite every sound path in a board dict with ``change``. In place."""
    for entry in data.get("slots") or []:
        if entry and entry.get("filepath"):
            entry["filepath"] = change(entry["filepath"])
    for entry in (data.get("playlist") or {}).get("tracks") or []:
        if entry and entry.get("filepath"):
            entry["filepath"] = change(entry["filepath"])
    drops = data.get("drops") or {}
    if drops.get("paths"):
        drops["paths"] = [change(p) for p in drops["paths"]]
    return data


def _index_folder(folder, recursive=True, depth=None, seconds=None,
                  entries=None, stems=True):
    """{lowercased name: full path} for files, and the same for folders.

    Matching is by file name and, with ``stems``, by name without its
    extension for sound files. Folders are indexed separately: a slot that
    held a folder must be repaired with a folder, or a random pick slot
    silently becomes a one shot.

    **Breadth first, so where a name appears twice the SHALLOWER one wins.**
    `os.walk` is depth first, which handed `a\\b\\c\\x.wav` back ahead of
    `z\\x.wav` (Mark, 16 October 2026). ``depth``, ``seconds`` and
    ``entries`` bound it and are checked at every entry, not only between
    folders; left out, it is the whole tree, which is what a relink the user
    asked for has always done.
    """
    index, folders = {}, {}
    folder = os.path.abspath(folder)
    deadline = None if seconds is None else time.monotonic() + seconds
    seen = 0
    queue = collections.deque([(folder, 0)])
    while queue:
        root, level = queue.popleft()
        try:
            listing = list(os.scandir(root))
        except OSError:
            continue
        for entry in sorted(listing, key=lambda e: e.name.lower()):
            seen += 1
            if entries is not None and seen > entries:
                return index, folders
            if deadline is not None and time.monotonic() > deadline:
                return index, folders
            name = entry.name
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                folders.setdefault(name.lower(), entry.path)
                if recursive and (depth is None or level + 1 < depth):
                    queue.append((entry.path, level + 1))
                continue
            index.setdefault(name.lower(), entry.path)
            stem, ext = os.path.splitext(name)
            if stems and ext.lower() in C.AUDIO_EXTENSIONS:
                index.setdefault(stem.lower(), entry.path)
    return index, folders


def _is_relative(path):
    """True for a path written relative to its board, on either system.

    `os.path.isabs` alone is not enough here: on Python 3.13 under Windows a
    Mac path such as "/Users/siena/intro.mp3" is NOT absolute, so it was
    joined onto the board's drive and saved back as "C:\\Users\\siena\\...",
    which no Mac can read again. A path starting with a slash of either kind
    is somebody's absolute path and is kept exactly as written.
    """
    return bool(path) and not os.path.isabs(path) and path[0] not in "/\\"


class ExportStopped(Exception):
    """Raised by an export's progress callback to stop it part way."""


def _copy_file(source, dest, done, total, progress, block=1024 * 1024):
    """Copy one file in blocks, reporting the running total. Returns it."""
    if progress is not None:
        progress(done, total)
    temp = dest + ".part"
    try:
        with open(source, "rb") as src, open(temp, "wb") as out:
            while True:
                chunk = src.read(block)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
        _replace(temp, dest)
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise
    try:
        stat = os.stat(source)
        os.utime(dest, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    except OSError:
        pass
    return done


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
        #: Duck while talking (feedback 44): the music a little further down
        #: while the processed voice is above the gate threshold, on top of
        #: the open microphone's duck. Off unless somebody turns it on, which
        #: is also what every board saved before it existed gets.
        self.talk_duck = False
        self.talk_duck_db = C.DEFAULT_TALK_DUCK_DB
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
        #: How many missing sounds `load` found beside the board by itself.
        self.found_beside = 0
        #: What `find_beside` repaired, {(kind, which): (guess, the path the
        #: file had)}.
        #: Saved back as the original, because a guess is not a fact.
        self._guessed = {}
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
        # Sending the show to another program on this machine. Off until it
        # is set up. See send.py: this is the on air mix out of a sound card,
        # rather than one more place the pads can be routed to.
        self.send_on = False
        self.send_device_name = None
        self.send_device_hostapi = None
        self.send_gain_db = 0.0
        #: The NAME of the one source the send leaves out. Mix minus: the
        #: send to TeamTalk must not carry the TeamTalk capture, or everybody
        #: in the call hears themselves. By name rather than by index,
        #: because a source list gets reordered and an index would silently
        #: start excluding somebody else.
        self.send_minus = ""
        #: Whether the presenter is listening to the send. Not saved as ON:
        #: it is a confidence check you do during a show, like a mute, and
        #: coming back tomorrow to a second copy of everything in your
        #: headphones is worse than pressing the key again.
        self.send_monitor = False
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
        #: What the VIDEO platform's channel is called, which is not the same
        #: thing as the radio station's name and must never be printed as
        #: though it were. `stream_name` is "Blindside Radio", an Icecast
        #: station; a YouTube channel is a different thing with a different
        #: name, and the go live summary used to say "Blindside Radio, on
        #: YouTube Live", which Tony read on 12 September 2026 and correctly
        #: called untrue.
        #:
        #: Empty is the ordinary state and means "just say the platform".
        #: Nothing is invented: a name nobody typed is not a name.
        self.video_name = ""
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

        #: What goes on the screen when the destination insists on a picture.
        #: YouTube refuses an audio only ingest, so a radio show still has to
        #: send SOMETHING, and a card is what that something is by default.
        #: A camera is offered and is not the default: most people using this
        #: are running a radio show and have no reason to be on camera.
        #: The video side, kept apart from the audio side above rather than
        #: sharing its fields. They looked shareable and are not: an Icecast
        #: address is a host name and an RTMP one is a whole URL with a
        #: scheme, so one board cannot hold a radio station AND a YouTube
        #: channel if they share stream_host. Setting up one would silently
        #: destroy the other.
        self.video_server = "youtube"
        self.video_host = C.RTMP_INGEST["youtube"]
        #: A stream key ONLY when Windows Credential Manager refused to keep
        #: it, which is rare and is said out loud when it happens. It has a
        #: field of its own rather than borrowing stream_password: that is the
        #: Icecast source password, and putting a YouTube key in it wiped a
        #: user's radio station password every time they looked at the video
        #: page. Two different secrets, two different places.
        self.video_key = ""
        #: Which of the two Ctrl+B goes to. One at a time for now.
        self.live_to = C.LIVE_TO_AUDIO

        self.picture = C.PICTURE_CARD
        self.picture_file = ""
        self.picture_clock = False
        self.camera = ""

        #: Which screen goes out when the picture is the screen. Not a
        #: monitor number: see C.SCREEN_CHOICES for why.
        self.screen = C.SCREEN_ALL

        #: The brand, as three NAMES rather than three numbers, because a
        #: name can be read out and a hex triplet cannot. See colours.py for
        #: why the app scores every pair rather than showing a swatch.
        self.colour_background = C.COLOUR_BACKGROUND
        self.colour_text = C.COLOUR_TEXT
        self.colour_accent = C.COLOUR_ACCENT

        #: The shot check: which model looks at the picture before a show.
        #: **Not a STATION field.** Everything above about the picture
        #: belongs to a station because a YouTube station and an Icecast one
        #: want different answers. Who describes the shot does not change
        #: with where the show goes, and putting it in a station would mean
        #: setting it up again for every one.
        #:
        #: **And the KEY IS NOT HERE.** It goes in Windows Credential
        #: Manager through secrets.py, under its own prefix, for the reason
        #: that module already gives about stream keys, and one more: a
        #: vision key is billable, so a board file passed to somebody else
        #: would be handing them a bill.
        #: Which corner the camera sits in when the screen is on air.
        self.split_corner = C.SPLIT_CORNER

        self.vision_provider = C.VISION_PROVIDER
        self.vision_model = ""

        #: What sits on top of the picture. One entry per named place: what
        #: it is showing, the words when that is "my own words", and the file
        #: when it is "a text file". Four places and no coordinates anywhere,
        #: which is the whole design: see dropdeck/overlay.py.
        self.text_places = {key: {"kind": C.TEXT_NONE, "words": "", "file": ""}
                            for key in C.PLACES_ORDER}
        self.video_width = C.RTMP_WIDTH
        self.video_height = C.RTMP_HEIGHT
        self.video_fps = C.RTMP_FPS
        self.video_bitrate = C.RTMP_VIDEO_BITRATE
        #: How much the app says about what the camera can see. Problems only
        #: by default: quiet while the shot is good. See framing.py for why
        #: this is three levels rather than a switch.
        self.framing_level = "problems"
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

        #: Whether Ctrl+B says what it is about to send and waits for a
        #: yes. On by default: not knowing what was live is the thing
        #: this answers, and Enter is still the next keystroke. Somebody
        #: who goes live every day turns it off inside the dialog.
        self.ask_before_live = True
        #: What the file at `path` looked like when this board last read or
        #: wrote it. See changed_on_disk.
        self._disk = None
        self.path = None
        self.dirty = False

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, value):
        # A board pointed at a different file knows nothing about that file,
        # so what it remembered about the old one must not be compared with
        # the new one. The demo loaded over a board used to be exactly that:
        # the demo's fingerprint held against somebody's own board.json.
        if not same_path(value, getattr(self, "_path", None)):
            self._disk = None
        self._path = value

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
        list of slots and playlist tracks that were repaired.
        """
        index, folders = _index_folder(folder, recursive=recursive)
        # The user chose this, so what it finds is no longer a guess and is
        # written down like any other path.
        self._guessed.clear()
        return self._relink_from(index, folders)

    @property
    def missing_count(self):
        """Every sound this board cannot find: pads, running order and drops.

        "Loaded, 20 sounds" used to count the pads only, so a board whose whole
        running order was missing opened without a word about it. That is how
        Ali Moosa's playlist went missing in silence.
        """
        return (len(self.missing_slots) + len(self.playlist.missing)
                + len(self.drops.missing))

    def find_beside(self):
        """Repair what is missing out of the board's own folder, in memory.

        A board carried to another computer in Google Drive, Dropbox or
        OneDrive arrives with every path pointing at the computer it came
        from, and its sounds are usually right beside it. So before anybody
        is asked to relink by hand, the board looks next to itself.

        Three rules, all from Mark's audit of 16 October 2026:

        **It is a guess, so it is never written down.** `save` puts the
        original path back for anything repaired here, and the board is not
        marked changed. Marking it changed stopped a synced board reloading
        when the other computer saved it, and left a sidecar copy beside it
        on every close; and writing the guess down replaced a real path on a
        drive that was only unplugged today with a same named file that
        happened to be nearby. Each computer looks again when it opens the
        board, which costs at most `C.BESIDE_SEARCH_SECONDS`.

        **Exact file names only.** No name without its extension, which
        turned a missing applause.wav into a different applause.flac, and no
        file for a folder.

        **The window is never held longer than the bound**, whatever the
        disk does: the look runs on a thread of its own and is abandoned if
        it has not answered in time, because one folder on a sleeping network
        drive can take most of a minute to list and the clock inside the walk
        cannot interrupt that.
        """
        if not self.path or not self.missing_count:
            return []
        folder = os.path.dirname(os.path.abspath(self.path))
        found = {}

        def look():
            try:
                found["index"] = _index_folder(
                    folder, depth=C.BESIDE_SEARCH_DEPTH,
                    seconds=C.BESIDE_SEARCH_SECONDS,
                    entries=C.BESIDE_SEARCH_ENTRIES, stems=False)
            except Exception:
                pass

        worker = threading.Thread(target=look, daemon=True,
                                  name="dropdeck-beside")
        worker.start()
        worker.join(C.BESIDE_SEARCH_SECONDS + 0.5)
        if "index" not in found:
            return []
        index, _folders = found["index"]
        was_dirty = self.dirty
        before = {id(s): s.filepath for s in self.slots}
        before.update({id(t): t.filepath for t in self.playlist.tracks})
        drops_before = list(self.drops.paths)
        try:
            repaired = self._relink_from(index, {}, files_for_folders=False)
        except Exception:
            return []
        # Remembered PER ITEM, not per found file: one file beside the board
        # can stand in for a playlist track written on a Mac and a drop
        # written here, and each must get its own path back.
        for item in repaired:
            self._guessed[("item", id(item))] = (item.filepath,
                                                 before.get(id(item)))
        for at, (old, new) in enumerate(zip(drops_before, self.drops.paths)):
            if old != new:
                self._guessed[("drop", at)] = (new, old)
        self.dirty = was_dirty
        return repaired

    def _restore_guesses(self, data):
        """Put the board file's own paths back over `find_beside`'s guesses.

        Only where the item still holds the guess: anything the user has
        reassigned or relinked since is theirs and is written as it is.
        """
        if not self._guessed:
            return data
        pairs = ([("item", s, e) for s, e in zip(self.slots,
                                                 data.get("slots") or [])]
                 + [("item", t, e) for t, e in zip(
                     self.playlist.tracks,
                     (data.get("playlist") or {}).get("tracks") or [])])
        for kind, item, entry in pairs:
            held = self._guessed.get((kind, id(item)))
            if held and entry and entry.get("filepath") == held[0] and held[1]:
                entry["filepath"] = held[1]
        drops = (data.get("drops") or {}).get("paths") or []
        for at, path in enumerate(drops):
            held = self._guessed.get(("drop", at))
            if held and path == held[0] and held[1]:
                drops[at] = held[1]
        return data

    def _relink_from(self, index, folders, files_for_folders=True):
        repaired = []
        # The playlist is repaired out of the same walk. Two separate hunts
        # through a music library for the same folder is one hunt too many.
        repaired.extend(self.playlist.relink(index))
        drops = self.drops.relink(index)
        for slot in self.missing_slots:
            base = _basename(slot.filepath)
            stem = os.path.splitext(base)[0]
            if slot.folder_count is not None:
                found = folders.get(base.lower())
            elif files_for_folders:
                found = index.get(base.lower()) or index.get(stem.lower())
            else:
                # Exact names only. A pad saved with no folder count may have
                # been a folder, so a name with no extension is not matched
                # to a file at all.
                found = (index.get(base.lower())
                         if os.path.splitext(base)[1] else None)
            if found:
                slot.filepath = found
                slot.scan_folder(force=True)
                repaired.append(slot)
        if repaired or drops:
            self.dirty = True
        return repaired

    # -------------------------------------------------------------- export --
    def sound_paths(self):
        """Every file or folder this board plays, once each, in board order."""
        seen, out = set(), []
        for path in ([s.filepath for s in self.slots if s.filepath]
                     + [t.filepath for t in self.playlist.tracks if t.filepath]
                     + list(self.drops.paths)):
            key = os.path.normcase(os.path.abspath(path))
            if key not in seen:
                seen.add(key)
                out.append(path)
        return out

    def export_with_sounds(self, target, name=None, progress=None,
                           data=None, paths=None):
        """Copy this board and every sound it uses into ``target``.

        The board file written there points at the copies by paths RELATIVE
        to itself, with forward slashes, so the folder opens on any computer
        and on the Mac as it is: carried in Google Drive, on a USB stick or in
        a zip. Ali Moosa, 14 October 2026: a board saved to Google Drive
        reopened without its playlist, because a board only ever held the
        addresses of its sounds on the computer it was made on.

        The live board is not changed. ``progress(done_bytes, total_bytes)``
        is called as the copy goes, and may raise `ExportStopped` to stop it.
        ``data`` and ``paths`` are the board as it was when the export was
        asked for, taken on the window's thread by the caller: read here, on
        a worker, a pad added during a long copy went into the board without
        its sound. A sound that cannot be read is counted as missing and the
        rest carry on. Returns a dict: ``board`` (the file written),
        ``copied``, ``missing`` (the paths that could not be found or read,
        left pointing where they were) and ``bytes``.
        """
        if data is None:
            data = self.to_dict()
        if paths is None:
            paths = self.sound_paths()
        # Here, and not left to the caller, so no export can carry them.
        data = for_export(data)
        target = os.path.abspath(target)
        stem = name or os.path.splitext(_basename(self.path or ""))[0] \
            or "Drop Deck board"
        board_file = os.path.join(target, stem + ".json")
        if os.path.exists(board_file):
            raise FileExistsError("there is already a board called %s there"
                                  % os.path.basename(board_file))
        sounds = os.path.join(target, C.EXPORT_SOUNDS_FOLDER)
        os.makedirs(sounds, exist_ok=True)
        plan, missing, taken = [], [], set()

        def destination(name_wanted, folder=False):
            stem, ext = (name_wanted, "") if folder else os.path.splitext(name_wanted)
            candidate, count = name_wanted, 2
            while candidate.lower() in taken:
                candidate = "%s (%d)%s" % (stem, count, ext)
                count += 1
            taken.add(candidate.lower())
            return os.path.join(sounds, candidate)

        mapping = {}
        for path in paths:
            key = os.path.normcase(os.path.abspath(path))
            if os.path.isdir(path):
                dest_dir = destination(_basename(path), folder=True)
                mapping[key] = dest_dir
                try:
                    names = sorted(os.listdir(path))
                except OSError:
                    names = []
                for item in names:
                    full = os.path.join(path, item)
                    if (os.path.splitext(item)[1].lower() in C.AUDIO_EXTENSIONS
                            and os.path.isfile(full)):
                        plan.append((full, os.path.join(dest_dir, item)))
                os.makedirs(dest_dir, exist_ok=True)
            elif os.path.isfile(path):
                dest = destination(_basename(path))
                mapping[key] = dest
                plan.append((path, dest))
            else:
                missing.append(path)

        # The picture travels the way a sound does, beside the sounds, so the
        # export does not carry a path from this computer. One that is not
        # there is left out rather than carried as somebody's folder.
        pictures = {}
        for entry in [data] + [s for s in data.get("stream_stations") or []
                               if isinstance(s, dict)]:
            path = entry.get("picture_file") or ""
            if not path:
                continue
            key = os.path.normcase(os.path.abspath(path))
            if key not in pictures:
                if os.path.isfile(path):
                    pictures[key] = destination(_basename(path))
                    plan.append((path, pictures[key]))
                else:
                    pictures[key] = ""
        picture_copies = {dest for dest in pictures.values() if dest}

        total = 0
        for source, _dest in plan:
            try:
                total += os.path.getsize(source)
            except OSError:
                pass
        done = 0
        copied = 0
        for source, dest in plan:
            try:
                size = os.path.getsize(source)
            except OSError:
                size = 0
            try:
                done = _copy_file(source, dest, done, total, progress)
                if dest not in picture_copies:
                    copied += 1
            except ExportStopped:
                raise
            except OSError:
                done += size
                if dest in picture_copies:
                    for key, moved in list(pictures.items()):
                        if moved == dest:
                            pictures[key] = ""
                    continue
                # Gone or unreadable since the plan was made. One sound must
                # not cost the whole export: it is counted as missing and
                # the board keeps its original path for it.
                missing.append(source)
                for key, moved in list(mapping.items()):
                    if moved == dest:
                        del mapping[key]

        def carried(path):
            moved = mapping.get(os.path.normcase(os.path.abspath(path)), path)
            return _portable(moved, target)

        out = _map_sound_paths(copy.deepcopy(data), carried)
        for entry in [out] + [s for s in out.get("stream_stations") or []
                              if isinstance(s, dict)]:
            if entry.get("picture_file"):
                moved = pictures.get(
                    os.path.normcase(os.path.abspath(entry["picture_file"])), "")
                entry["picture_file"] = _portable(moved, target) if moved else ""
        payload = json.dumps(out, indent=2)
        temp = board_file + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(payload)
        _replace(temp, board_file)
        return {"board": board_file, "copied": copied, "missing": missing,
                "bytes": total}

    # ------------------------------------------------------------------- io --
    # ------------------------------------------------------------ stations --
    def station_settings(self):
        """The station that is set up right now, as a saved station would be.

        Copies. `text_places` is a dict of dicts, so a station saved by
        reference went on changing every time the words on the picture were
        edited, and the board changed with it whenever the station did.
        """
        return {field: copy.deepcopy(getattr(self, field))
                for field in STATION_FIELDS}

    def station_names(self):
        return [s.get("stream_name", "") for s in self.stream_stations]

    def load_station(self, name):
        """Put a saved station into the live settings. True if there was one."""
        for station in self.stream_stations:
            if station.get("stream_name") == name:
                for field in STATION_FIELDS:
                    if field not in station:
                        continue
                    value = station[field]
                    # A None means the field did not exist when this was
                    # saved, not that it should be set to nothing. Stations
                    # saved before live_to was added carry live_to: null, and
                    # copying that across left the board with a destination
                    # that was neither of the two, which then silently
                    # behaved as audio whatever the user had chosen.
                    if value is None:
                        continue
                    # A copy, for the reason in station_settings.
                    setattr(self, field, copy.deepcopy(value))
                self.stream_port = _stream_port(self.stream_port)
                self.stream_bitrate = _stream_bitrate(self.stream_bitrate)
                if self.live_to not in C.LIVE_TO:
                    self.live_to = C.LIVE_TO_AUDIO
                # `Board.load` whitelists these and a station bypassed every
                # one of them, because this is a plain setattr per field.
                # So a board file that could not smuggle an address in
                # through video_host could smuggle it in through a saved
                # station, and the pre-flight then read a file path out
                # loud as "Custom RTMP server". Nothing escaped, because
                # `RtmpDestination.url` refuses it, but the app was
                # describing somebody's path as a server.
                self.video_host = _rtmp_address(self.video_host)
                if self.video_server not in C.VIDEO_SERVER_ORDER:
                    self.video_server = "youtube"
                # For the reason in `load`: a saved station is the same
                # JSON, and it must not be the way round that rule.
                if self.video_server in C.RTMP_FIXED_ADDRESS:
                    self.video_host = C.RTMP_INGEST[self.video_server]
                self.stream_stats_url = web_address(self.stream_stats_url)
                if self.picture not in C.PICTURE_SOURCES:
                    self.picture = C.PICTURE_CARD
                return True
        return False

    def tie_kept_keys(self):
        """Tie each stream key kept by 3.10.1 to the server this board names
        for its station. Returns how many were tied.

        For the first start of this version only, on the board that opens at
        startup (ui._trust_own_board_once). 3.10.1 kept keys by station name
        alone, so a key saved for a custom server, Mixcloud through somebody's
        own RTMP relay for instance, has nothing written down to say where it
        goes, and holding it back would refuse a working show at the top of
        the first one after updating. The board open at startup is the best
        witness there is to where each key belongs, but not a perfect one, so
        a custom server is tied provisionally (see below). A key already tied
        is left alone, and the live station is asked before its saved copies.
        """
        tied = 0
        seen = set()
        entries = [(self.stream_name, self.video_server, self.video_host)]
        entries += [(s.get("stream_name"),
                     s.get("video_server") or self.video_server,
                     s.get("video_host") or self.video_host)
                    for s in self.stream_stations]
        for name, server, host in entries:
            name = name or ""
            if name in seen:
                continue
            seen.add(name)
            # YouTube and Facebook are pinned to their own secure ingest, and
            # that is final. Anything else is only as trustworthy as this
            # board, which may be one somebody sent, so it waits for a person
            # to confirm it at the first go live (ui._cleared_to_go).
            pinned = server in C.RTMP_FIXED_ADDRESS
            address = C.RTMP_INGEST[server] if pinned else _rtmp_address(host)
            if not address:
                continue
            key = secrets.fetch(name)
            if key and not secrets.tied_to(name) and secrets.store(
                    name, key, host=address, confirmed=pinned):
                tied += 1
        return tied

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
            "talk_duck": bool(self.talk_duck),
            "talk_duck_db": _talk_db(self.talk_duck_db),
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
            "send_on": bool(self.send_on),
            "send_device_name": self.send_device_name,
            "send_device_hostapi": self.send_device_hostapi,
            "send_gain_db": float(self.send_gain_db),
            "send_minus": self.send_minus or "",
            "global_hotkeys_on": bool(self.global_hotkeys_on),
            "device_name": self.device_name,
            "device_hostapi": self.device_hostapi,
            "bank_devices": {str(k): v for k, v in self.bank_devices.items()},
            "announce_playback": bool(self.announce_playback),
            "speech_level": self.speech_level,
            "ask_before_live": bool(self.ask_before_live),
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
            "video_name": self.video_name,
            "stream_description": self.stream_description,
            "stream_genre": self.stream_genre,
            "stream_url": self.stream_url,
            "stream_stats_url": self.stream_stats_url,
            "video_server": self.video_server,
            "video_host": self.video_host,
            "video_key": self.video_key,
            "live_to": self.live_to,
            "picture": self.picture,
            "picture_file": self.picture_file,
            "picture_clock": bool(self.picture_clock),
            "camera": self.camera,
            "screen": self.screen,
            "text_places": {k: dict(v) for k, v in self.text_places.items()},
            "colour_background": self.colour_background,
            "colour_text": self.colour_text,
            "colour_accent": self.colour_accent,
            "split_corner": self.split_corner,
            "vision_provider": self.vision_provider,
            "vision_model": self.vision_model,
            "video_width": int(self.video_width),
            "video_height": int(self.video_height),
            "video_fps": int(self.video_fps),
            "video_bitrate": int(self.video_bitrate),
            "framing_level": self.framing_level,
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
        # A sound kept in the board's own folder, or under it, is written
        # relative to the board, so a board and its sounds kept together in a
        # cloud folder open on every computer that folder reaches, the Mac
        # included. Anything elsewhere keeps its full path, as it always did.
        base = os.path.dirname(os.path.abspath(path))
        payload = json.dumps(
            _map_sound_paths(self._restore_guesses(self.to_dict()),
                             lambda p: _portable(p, base)),
            indent=2)
        # Write beside the target then swap, so a crash mid-save cannot leave a
        # half-written board where the real one used to be.
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(payload)
        try:
            _replace(temp, path)
        except Exception:
            # Never leave the half of a save that did not land lying beside
            # somebody's board.
            try:
                os.remove(temp)
            except OSError:
                pass
            raise
        self.path = path
        self.dirty = False
        self._disk = _disk_stamp(path)
        return path

    def claim_path(self, path, unreadable=False):
        """Point this board at a file it did NOT load, remembering what is there.

        The demo at first run, a new board, the demo loaded over a board: each
        takes a path without reading it. Knowing nothing about that file is
        not the same as owning it. Mark found the first run case on 19
        September 2026: with nothing remembered, a board copied into the
        settings folder while the demo was open was written over on close,
        which is fb40 exactly. So what is there NOW is written down, and
        anything different later is somebody else's.

        `unreadable` is a file that could not be read or even copied aside.
        That one is never written over at all.
        """
        self.path = path
        if not path:
            return
        if unreadable:
            self._disk = UNREADABLE
        elif os.path.exists(path):
            self._disk = _disk_stamp(path) or UNREADABLE
        else:
            self._disk = NOTHING_THERE

    def changed_on_disk(self):
        """Has something other than this app changed the board's file?

        Closing the app saved the board over its file unconditionally, so a
        board somebody copied into place while Drop Deck was open was
        overwritten the moment they closed it to pick the new one up, and
        the streaming set up in that copy was gone before it was ever read.
        fb40 again: "copy the json file, it acts as if it was never set up."

        A file that is not there is not a change: saving puts it back, which
        is what always happened.
        """
        if not self.path or self._disk is None:
            return False
        if self._disk in (NOTHING_THERE, UNREADABLE):
            # Nothing was there and something is now, or what was there was
            # never ours to write over in the first place.
            return os.path.exists(self.path)
        try:
            info = os.stat(self.path)
        except OSError:
            return False
        if (info.st_size, info.st_mtime_ns) == self._disk[:2]:
            return False
        now = _disk_stamp(self.path)
        return now is not None and now[2] != self._disk[2]

    def disk_now(self):
        """What the board's file holds at this moment, for telling apart one
        change from the next. None when there is nothing readable there."""
        return _disk_stamp(self.path) if self.path else None

    def sidecar_path(self):
        """Where to keep this board when its own file belongs to somebody else.

        Beside the original, with the time in the name, so both are found in
        the same place and neither is ever written over.
        """
        path = self.path or default_board_path()
        stem, ext = os.path.splitext(path)
        stamp = time.strftime("%Y-%m-%d %H%M")
        candidate = "%s (Drop Deck copy %s)%s" % (stem, stamp, ext or ".json")
        count = 2
        while os.path.exists(candidate):
            candidate = "%s (Drop Deck copy %s, %d)%s" % (stem, stamp, count,
                                                          ext or ".json")
            count += 1
        return candidate

    @classmethod
    def load(cls, path):
        with open(path, "rb") as handle:
            raw = handle.read()
            try:
                stamp = _stamp_of(handle, raw)
            except OSError:
                stamp = None
        data = json.loads(raw.decode("utf-8-sig"))
        board = cls()
        board.path = path
        board._disk = stamp
        board.sfx_volume = float(data.get("sfx_volume", C.DEFAULT_SFX_VOLUME))
        board.bed_volume = float(data.get("bed_volume", C.DEFAULT_BED_VOLUME))
        board.ducking = bool(data.get("ducking", True))
        board.duck_db = float(data.get("duck_db", C.DEFAULT_DUCK_DB))
        board.talk_duck = data.get("talk_duck", False) is True
        board.talk_duck_db = _talk_db(data.get("talk_duck_db",
                                               C.DEFAULT_TALK_DUCK_DB))
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
        board.send_on = bool(data.get("send_on", False))
        board.send_device_name = data.get("send_device_name")
        board.send_device_hostapi = data.get("send_device_hostapi")
        try:
            gain = float(data.get("send_gain_db", 0.0))
            # NaN clamps to the MAXIMUM, not to zero: every comparison with
            # NaN is False, so min(24.0, nan) is 24.0. A corrupt board file
            # with NaN or Infinity in it therefore loaded as +24 dB, a
            # sixteenfold boost into somebody's call, silently. Found by
            # Mark, 10 September 2026.
            if gain != gain or gain in (float("inf"), float("-inf")):
                raise ValueError("not a real number")
            board.send_gain_db = max(C.MIN_MIC_GAIN_DB,
                                     min(C.MAX_MIC_GAIN_DB, gain))
        except (TypeError, ValueError):
            board.send_gain_db = 0.0
        minus = data.get("send_minus")
        board.send_minus = minus if isinstance(minus, str) else ""
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
        server = data.get("stream_server")
        board.stream_server = (server if server in C.STREAM_SERVER_ORDER
                               else "icecast")
        board.stream_host = data.get("stream_host") or ""
        board.stream_port = _stream_port(data.get("stream_port"))
        board.stream_mount = data.get("stream_mount") or C.DEFAULT_STREAM_MOUNT
        board.stream_user = data.get("stream_user") or C.DEFAULT_STREAM_USER
        board.stream_password = data.get("stream_password") or ""
        fmt_in = data.get("stream_format")
        board.stream_format = (fmt_in if fmt_in in C.STREAM_FORMAT_ORDER
                               else "mp3")
        board.stream_bitrate = _stream_bitrate(data.get("stream_bitrate"))
        board.stream_name = data.get("stream_name") or ""
        board.video_name = data.get("video_name") or ""
        board.stream_description = data.get("stream_description") or ""
        board.stream_genre = data.get("stream_genre") or ""
        board.stream_url = data.get("stream_url") or ""
        board.stream_stats_url = web_address(data.get("stream_stats_url"))
        # A board file is not a trusted document, so every one of these falls
        # back rather than becoming a setting that explodes at air time.
        board.video_server = (data.get("video_server")
                              if data.get("video_server") in C.VIDEO_SERVER_ORDER
                              else "youtube")
        board.video_host = data.get("video_host") or ""
        board.video_key = data.get("video_key") or ""
        board.live_to = (data.get("live_to")
                         if data.get("live_to") in C.LIVE_TO else C.LIVE_TO_AUDIO)
        # A board written by the first build of this feature put the platform
        # in stream_server, where the audio settings live. Move it, rather
        # than leaving a board that says its radio station is "youtube" and
        # then tries to open a mount point on it.
        if data.get("stream_server") in C.VIDEO_SERVER_ORDER:
            board.video_server = data["stream_server"]
            board.video_host = data.get("stream_host") or ""
            board.live_to = C.LIVE_TO_VIDEO
            board.stream_server = "icecast"
            board.stream_host = ""
        board.video_host = _rtmp_address(board.video_host)
        # YouTube and Facebook have ONE ingest each, and the address box is
        # locked to it in Preferences. The file's own address was kept all
        # the same, so a board saying "youtube" with somebody's server in
        # video_host sent the stream key there while the go live summary
        # said YouTube Live (Mark, 24 November 2026). Never from the file.
        if board.video_server in C.RTMP_FIXED_ADDRESS:
            board.video_host = C.RTMP_INGEST[board.video_server]
        if not board.video_host:
            board.video_host = C.RTMP_INGEST.get(board.video_server, "")
        picture = data.get("picture")
        board.picture = picture if picture in C.PICTURE_SOURCES else C.PICTURE_CARD
        board.picture_file = data.get("picture_file") or ""
        board.picture_clock = bool(data.get("picture_clock", False))
        board.camera = data.get("camera") or ""
        screen = data.get("screen")
        board.screen = screen if screen in C.SCREEN_CHOICES else C.SCREEN_ALL
        board.text_places = _text_places(data.get("text_places"))
        board.colour_background = _colour(data.get("colour_background"),
                                          C.COLOUR_BACKGROUND)
        board.colour_text = _colour(data.get("colour_text"), C.COLOUR_TEXT)
        board.colour_accent = _colour(data.get("colour_accent"),
                                      C.COLOUR_ACCENT)
        # Whitelisted the same way a colour name is: a board file is plain
        # JSON that a user can write, and this one ends up in a URL.
        corner = data.get("split_corner")
        board.split_corner = (corner if corner in C.SPLIT_CORNERS
                              else C.SPLIT_CORNER)
        provider = data.get("vision_provider")
        if provider not in C.VISION_PROVIDERS:
            # Nobody has chosen. Take the one that has a key on this machine
            # rather than the first in the list, so a board saved before this
            # feature existed opens on something that will actually work.
            from . import vision as _vision
            provider = _vision.best_provider(C.VISION_PROVIDER)
        board.vision_provider = provider
        model = data.get("vision_model")
        board.vision_model = model.strip()[:80] if isinstance(model, str) else ""
        board.video_width = _video_number(data.get("video_width"),
                                          C.RTMP_WIDTH, 160, 3840)
        board.video_height = _video_number(data.get("video_height"),
                                           C.RTMP_HEIGHT, 120, 2160)
        board.video_fps = _video_number(data.get("video_fps"), C.RTMP_FPS,
                                        1, 60)
        board.video_bitrate = _video_number(data.get("video_bitrate"),
                                            C.RTMP_VIDEO_BITRATE, 200, 20000)
        level = data.get("framing_level")
        board.framing_level = level if level in ("off", "problems",
                                                 "everything") else "problems"
        fmt = data.get("record_format")
        board.record_format = fmt if fmt in C.RECORD_FORMAT_KEYS else "mp3"
        board.record_bitrate = _stream_bitrate(data.get("record_bitrate", 192))
        # Kept exactly as the file has it, whatever this computer can do with
        # it: a board shared through Dropbox records to the NAS on the other
        # computer, and rewriting the field here took that away from it.
        # Whether THIS computer may record there is `usable_record_folder`.
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
        # An exported board carries its picture beside its sounds, written
        # relative to itself the way the sounds are.
        picture_base = os.path.dirname(os.path.abspath(path))

        def beside(held):
            if isinstance(held, str) and _is_relative(held):
                return os.path.normpath(os.path.join(picture_base, held))
            return held

        board.picture_file = beside(board.picture_file)
        for entry in board.stream_stations:
            if entry.get("picture_file"):
                entry["picture_file"] = beside(entry["picture_file"])
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
        board.ask_before_live = bool(data.get("ask_before_live", True))

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
            if slot.filepath and _is_relative(slot.filepath):
                slot.filepath = os.path.normpath(os.path.join(base, slot.filepath))
            board.slots[index] = slot
        board._adopt_slots()
        board.dirty = False
        # Counted as what stopped being missing, so the drops library, which
        # repairs strings rather than slots or tracks, is counted too.
        before = board.missing_count
        if before:
            board.find_beside()
            board.found_beside = before - board.missing_count
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
