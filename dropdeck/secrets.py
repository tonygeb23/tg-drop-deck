"""Where a stream key is kept, which is not the board file.

`stream_password` has always been a `STATION_FIELDS` entry, so it went into
`board.json` along with the eighty pads. That was already the wrong place for
an Icecast source password. **It is a much worse place for a YouTube or
Facebook stream key**, for a reason that is easy to miss: anybody holding that
key can broadcast to the channel it belongs to. A board file is plain JSON, a
user can write one anywhere with Ctrl+F12, and boards get sent to people. There
is nothing about a file full of sound names that suggests a broadcast
credential is in it.

So keys live in **Windows Credential Manager**, under one target name per
station, and the board file keeps only the station's name. `docs/VIDEO-STREAMING-PLAN.md`
says this and the original streaming plan said it before that.

Everything here is `advapi32` through ctypes. No new dependency, and the same
store every other Windows program uses, so a user can see and remove what the
app has kept without taking Drop Deck's word for it.

**Nothing here is allowed to raise.** A machine with a locked down credential
store, or a copy running somewhere that is not Windows, must fall back rather
than stop a show. `store` returns whether it worked, and the caller decides
what to do about it, which for the moment means keeping the key in the board
file the way it always was and saying so.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

#: One target per station, so removing a station removes its key and a user
#: reading Credential Manager can tell what each entry is for.
TARGET_PREFIX = "TG Drop Deck stream key: "

_CRED_TYPE_GENERIC = 1
#: Kept for this user on this machine, and NOT roamed to other machines. A
#: broadcast key following somebody onto a shared PC is not a kindness.
_CRED_PERSIST_LOCAL_MACHINE = 2

_WINDOWS = sys.platform == "win32"


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _advapi():
    if not _WINDOWS:
        return None
    try:
        return ctypes.WinDLL("advapi32", use_last_error=True)
    except Exception:
        return None


def available():
    """Whether keys can be kept out of the board file on this machine."""
    return _advapi() is not None


def target_for(station):
    return TARGET_PREFIX + (station or "the current station")


def store(station, key):
    """Keep a key. True when it really went into the credential store."""
    dll = _advapi()
    if dll is None:
        return False
    if not key:
        return forget(station)
    blob = key.encode("utf-16-le")
    buffer = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    credential = _CREDENTIAL()
    credential.Flags = 0
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = target_for(station)
    credential.Comment = "A live stream key. Safe to delete."
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(
        ctypes.pointer(buffer), ctypes.POINTER(ctypes.c_byte))
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.AttributeCount = 0
    credential.Attributes = None
    credential.TargetAlias = None
    credential.UserName = "stream"
    try:
        dll.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
        dll.CredWriteW.restype = wintypes.BOOL
        return bool(dll.CredWriteW(ctypes.byref(credential), 0))
    except Exception:
        return False


def fetch(station):
    """The key for one station, or an empty string. Never raises."""
    dll = _advapi()
    if dll is None:
        return ""
    pointer = ctypes.POINTER(_CREDENTIAL)()
    try:
        dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                  wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
        dll.CredReadW.restype = wintypes.BOOL
        ok = dll.CredReadW(target_for(station), _CRED_TYPE_GENERIC, 0,
                           ctypes.byref(pointer))
        if not ok or not pointer:
            return ""
        try:
            record = pointer.contents
            size = int(record.CredentialBlobSize)
            if size <= 0:
                return ""
            raw = ctypes.string_at(record.CredentialBlob, size)
            return raw.decode("utf-16-le", "replace")
        finally:
            try:
                dll.CredFree.argtypes = [ctypes.c_void_p]
                dll.CredFree(pointer)
            except Exception:
                pass
    except Exception:
        return ""


def forget(station):
    """Remove a station's key. True when there is no longer one there."""
    dll = _advapi()
    if dll is None:
        return False
    try:
        dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                    wintypes.DWORD]
        dll.CredDeleteW.restype = wintypes.BOOL
        dll.CredDeleteW(target_for(station), _CRED_TYPE_GENERIC, 0)
    except Exception:
        return False
    # Deleting something that was never there is a success, not a failure:
    # what was asked for was that no key is kept, and none is.
    return not fetch(station)


def redact(key):
    """A key as it may be shown or logged: enough to recognise, not to use.

    Never put a whole key on screen, in a status bar or in a spoken line. A
    presenter checking they pasted the right one needs the last few characters
    and nothing else.
    """
    key = (key or "").strip()
    if not key:
        return "not set"
    if len(key) <= 4:
        return "set"
    return "set, ending %s" % key[-4:]
