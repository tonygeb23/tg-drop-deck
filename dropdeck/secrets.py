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
import urllib.parse
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


#: The other kind of secret this app keeps. A vision key is not a stream key
#: and must not be filed as one: the whole point of using the credential
#: store is that somebody can open Credential Manager and see what is there
#: without taking this app's word for it, and a label that lies defeats that.
#: It is also billable, which a stream key is not.
VISION_PREFIX = "TG Drop Deck vision key: "

#: The third: an Icecast or SHOUTcast source password, one per station. It
#: lived in board.json until the major release after 3.10.1, while the guide
#: already said it was in Credential Manager. Anybody holding it can take
#: over the station's mount, so it is the same kind of secret as a stream key.
PASSWORD_PREFIX = "TG Drop Deck station password: "

#: What Credential Manager shows beside each one, so nobody has to guess.
_COMMENTS = {
    TARGET_PREFIX: "A live stream key. Safe to delete.",
    VISION_PREFIX: "A shot check key for an AI service. Safe to delete.",
    PASSWORD_PREFIX: "A radio station source password. Safe to delete.",
}

#: The user name every credential was written with through 3.10.1. A key
#: carrying it was kept before keys were tied to a server, so where it
#: belongs is not known.
_UNTIED = "stream"

#: In front of the server a credential belongs to, in its user name, which
#: Credential Manager shows: "for rtmps://a.rtmps.youtube.com/live2".
_TIED = "for "


def target_for(station, prefix=TARGET_PREFIX):
    return prefix + (station or "the current station")


def host_key(address):
    """An address in one spelling, for comparing two of them.

    Case is dropped from the scheme and the host name only, and a trailing
    slash goes, because those are the differences somebody retyping an
    address makes without meaning a different server.
    """
    text = str(address or "").strip().rstrip("/")
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError:
        return text.lower()
    if parts.scheme and parts.netloc:
        return urllib.parse.urlunsplit((parts.scheme.lower(),
                                        parts.netloc.lower(), parts.path,
                                        parts.query, ""))
    return text.lower()


def same_host(one, other):
    """Do two addresses name the same server. Two empty ones do not."""
    return bool(host_key(one)) and host_key(one) == host_key(other)


# The three things this module asks of Windows. Kept apart from everything
# that decides what to do, so a test can stand a dictionary in for them and
# never touch the user's real Credential Manager.

def _write(target, text, user, comment):
    """One credential written. True when Windows kept it."""
    dll = _advapi()
    if dll is None:
        return False
    blob = text.encode("utf-16-le")
    buffer = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    credential = _CREDENTIAL()
    credential.Flags = 0
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.Comment = comment
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(
        ctypes.pointer(buffer), ctypes.POINTER(ctypes.c_byte))
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.AttributeCount = 0
    credential.Attributes = None
    credential.TargetAlias = None
    credential.UserName = user
    try:
        dll.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
        dll.CredWriteW.restype = wintypes.BOOL
        return bool(dll.CredWriteW(ctypes.byref(credential), 0))
    except Exception:
        return False


def _read(target):
    """(text, user name) of one credential, or None. Never raises."""
    dll = _advapi()
    if dll is None:
        return None
    pointer = ctypes.POINTER(_CREDENTIAL)()
    try:
        dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                  wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
        dll.CredReadW.restype = wintypes.BOOL
        ok = dll.CredReadW(target, _CRED_TYPE_GENERIC, 0,
                           ctypes.byref(pointer))
        if not ok or not pointer:
            return None
        try:
            record = pointer.contents
            size = int(record.CredentialBlobSize)
            user = record.UserName or ""
            if size <= 0:
                return "", user
            raw = ctypes.string_at(record.CredentialBlob, size)
            return raw.decode("utf-16-le", "replace"), user
        finally:
            try:
                dll.CredFree.argtypes = [ctypes.c_void_p]
                dll.CredFree(pointer)
            except Exception:
                pass
    except Exception:
        return None


def _delete(target):
    """One credential removed. False only when Windows could not be asked."""
    dll = _advapi()
    if dll is None:
        return False
    try:
        dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                    wintypes.DWORD]
        dll.CredDeleteW.restype = wintypes.BOOL
        dll.CredDeleteW(target, _CRED_TYPE_GENERIC, 0)
    except Exception:
        return False
    return True


def store(station, key, prefix=TARGET_PREFIX, host=""):
    """Keep a key. True when it really went into the credential store.

    `host` is the server the key is for, and it is written beside the key.
    A board file is plain JSON that people send each other, and a station is
    found by NAME, so a board naming somebody's station could otherwise send
    their key wherever the board pointed. `key_for` hands a key only to the
    server it was kept for.
    """
    if not key:
        return forget(station, prefix)
    user = (_TIED + host_key(host)) if host_key(host) else _UNTIED
    return _write(target_for(station, prefix), key, user,
                  _COMMENTS.get(prefix, _COMMENTS[TARGET_PREFIX]))


def fetch(station, prefix=TARGET_PREFIX):
    """The key for one station, or an empty string. Never raises."""
    found = _read(target_for(station, prefix))
    return found[0] if found else ""


def tied_to(station, prefix=TARGET_PREFIX):
    """The server a kept key belongs to, or "" when nobody wrote one down."""
    found = _read(target_for(station, prefix))
    if not found or not str(found[1]).startswith(_TIED):
        return ""
    return str(found[1])[len(_TIED):]


#: Why `key_for` held a key back.
FOR_ANOTHER_HOST = "another host"
NOT_TIED = "not tied"


def key_for(station, host, prefix=TARGET_PREFIX, trusted=()):
    """The kept key for a station, if it may go to `host`.

    Returns (key, held, tied): the key to use, or "" when there is none or
    it was held back; why it was held back, `FOR_ANOTHER_HOST` or
    `NOT_TIED`, or ""; and the server it is tied to, "" when it is not.

    **A key goes only to the server it was kept for.** One kept before keys
    were tied (3.10.1 and earlier) goes only to an address in `trusted`,
    which is the platforms' own ingests, and the caller ties it there the
    first time it is used. Anywhere else it is held back until the user
    types it again for that server, because the board file asking is not
    the user asking.

    An empty station name is not a wildcard: it is one more name, and the
    key kept under it is tied to its server like any other.
    """
    key = fetch(station, prefix)
    if not key:
        return "", "", ""
    tied = tied_to(station, prefix)
    if tied:
        if same_host(tied, host):
            return key, "", tied
        return "", FOR_ANOTHER_HOST, tied
    if any(same_host(host, place) for place in trusted):
        return key, "", ""
    return "", NOT_TIED, ""


def forget(station, prefix=TARGET_PREFIX):
    """Remove a station's key. True when there is no longer one there."""
    if not _delete(target_for(station, prefix)):
        return False
    # Deleting something that was never there is a success, not a failure:
    # what was asked for was that no key is kept, and none is. Asked under
    # the SAME prefix: this checked for a stream key whatever was being
    # forgotten, so forgetting a vision key reported on something else.
    return not fetch(station, prefix)


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
