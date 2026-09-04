"""Running orders on disk, as M3U.

A board is a show's furniture: eighty pads, the drops library, the settings. A
running order is the show itself, and people want to keep those. Last
Tuesday's, the Christmas one, the two hours you had ready before the guest
cancelled. Tony, 3 September 2026: "in the event people need to save playlists
of their shows".

M3U rather than a format of this app's own, because a running order is worth
more if other things can read it. Every player, every phone and every other
playout system opens an M3U, so a show saved here can be checked in VLC,
handed to a co-presenter or loaded into the studio machine without this app
being anywhere near it.

Three decisions worth knowing about:

- **It is an extended M3U**, so each track carries its length and its
  "Artist - Title" on an `#EXTINF` line. That is what makes the file readable
  rather than a column of paths.
- **What M3U cannot say is said in comments.** Whether an item is a drop,
  whether it is ticked, and whether it has a crossfade of its own all go on a
  `#DROPDECK` line, which every other player ignores and this one reads back.
  So a running order round trips through here without losing anything, and is
  still an ordinary M3U everywhere else.
- **Paths under the playlist's own folder are written relative.** Save a show
  into the folder its music lives in and the whole folder can be moved, or
  copied to another machine, and still work. Anything outside is written in
  full, because a relative path out of a folder you have moved is worse than
  no path at all.

Like ``playlist.py``, nothing here knows what wx is.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

from . import constants as C

EXTENSIONS = (".m3u", ".m3u8")

#: What the file dialogs offer. m3u8 first only in the sense that it is named:
#: both are written as UTF-8, because a running order full of Motorhead and
#: Bjork is not something to hand to a system codepage.
WILDCARD = ("Playlists (*.m3u;*.m3u8)|*.m3u;*.m3u8|"
            "M3U playlist (*.m3u)|*.m3u|"
            "M3U8 playlist (*.m3u8)|*.m3u8|"
            "All files (*.*)|*.*")

HEADER = "#EXTM3U"
#: Our own line. Anything else reading this file sees a comment.
MARK = "#DROPDECK:"


def is_playlist_file(path):
    return os.path.splitext(path or "")[1].lower() in EXTENSIONS


def _extinf_title(track):
    """"Artist - Title", or just the title. What every other player shows."""
    artist = (track.artist or "").strip()
    title = track.title_text
    return "%s - %s" % (artist, title) if artist else title


def _relative_if_under(path, folder):
    """A path relative to ``folder``, but only if it really is under it.

    os.path.relpath will happily answer "..\\..\\..\\Music\\x.mp3", which is a
    path that breaks the moment the playlist is moved, which is the one thing
    a relative path was supposed to survive.
    """
    if not folder:
        return path
    try:
        relative = os.path.relpath(path, folder)
    except ValueError:
        return path                     # a different drive on Windows
    if relative.startswith(".."):
        return path
    return relative


def _fields(track):
    """The bits of a track that M3U has no way of saying."""
    found = []
    if track.is_drop:
        found.append("kind=drop")
    if not track.enabled:
        found.append("enabled=0")
    if track.crossfade is not None:
        found.append("crossfade=%g" % track.crossfade)
    return found


def dumps(playlist, folder=None):
    """The whole running order as M3U text.

    ``folder`` is where the file is going, which is what decides whether a
    path can be written relative.
    """
    lines = [HEADER,
             "#PLAYLIST:%s running order" % C.APP_NAME,
             "%scrossfade=%g" % (MARK, playlist.crossfade)]
    for track in playlist:
        seconds = int(round(track.duration)) if track.duration else -1
        lines.append("#EXTINF:%d,%s" % (seconds, _extinf_title(track)))
        fields = _fields(track)
        if fields:
            lines.append(MARK + " ".join(fields))
        lines.append(_relative_if_under(track.filepath, folder)
                     .replace("/", os.sep))
    return "\n".join(lines) + "\n"


def save(path, playlist):
    """Write the running order to ``path``. Returns how many items went in.

    UTF-8 with no byte order mark, for both extensions. A BOM makes some
    older players read the first path as though it began with three junk
    characters, and UTF-8 is what every player written this century assumes
    when it does not find one.
    """
    text = dumps(playlist, folder=os.path.dirname(os.path.abspath(path)))
    with open(path, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(text)
    return len(playlist)


# ------------------------------------------------------------------ reading --
def _decode(raw):
    """Text out of bytes, however the thing that wrote it felt about encoding.

    UTF-8 first, with a byte order mark stripped if there is one. Then
    Windows-1252, which is what an M3U written before about 2010 will be, and
    which cannot fail, so there is always an answer.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


def _parse_fields(text):
    found = {}
    for piece in text.split():
        if "=" not in piece:
            continue
        key, _, value = piece.partition("=")
        found[key.strip().lower()] = value.strip()
    return found


def _resolve(entry, folder):
    """One line of a playlist turned into a path on this machine.

    Handles the three things that turn up: an ordinary path, a path with
    forward slashes in it because it was written on a Mac or by a web player,
    and a file:// URL, which several players write and which is a perfectly
    good way of saying the same thing.
    """
    entry = entry.strip().strip('"')
    if not entry:
        return None
    lowered = entry.lower()
    if lowered.startswith("file:"):
        parsed = urlparse(entry)
        entry = unquote(parsed.path)
        if parsed.netloc:
            entry = "//%s%s" % (parsed.netloc, entry)
        # file:///C:/x turns into /C:/x, which is not a path anybody wants.
        if len(entry) > 2 and entry[0] == "/" and entry[2] == ":":
            entry = entry[1:]
    elif "://" in entry[:8]:
        return None               # http and the rest: not something we play
    entry = entry.replace("/", os.sep)
    if not os.path.isabs(entry) and folder:
        entry = os.path.join(folder, entry)
    return os.path.normpath(entry)


def loads(text, folder=None):
    """Parse M3U text. Returns ``(entries, crossfade)``.

    An entry is a dict of what the file said about one item. Whatever wrote
    the file, the path is the only thing that has to be there; everything
    else is filled in from the file itself once it is loaded.
    """
    entries = []
    crossfade = None
    pending = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(MARK):
            fields = _parse_fields(line[len(MARK):])
            if not entries and "crossfade" in fields and not pending:
                try:
                    crossfade = float(fields["crossfade"])
                except ValueError:
                    crossfade = None
                continue
            pending.update(fields)
            continue
        if line.upper().startswith("#EXTINF:"):
            info = line.split(":", 1)[1]
            length, _, title = info.partition(",")
            try:
                seconds = float(length.split(",")[0])
            except ValueError:
                seconds = -1.0
            if seconds > 0:
                pending["duration"] = seconds
            title = title.strip()
            if title:
                artist, sep, rest = title.partition(" - ")
                if sep and rest.strip():
                    pending["artist"] = artist.strip()
                    pending["title"] = rest.strip()
                else:
                    pending["title"] = title
            continue
        if line.startswith("#"):
            continue                    # somebody else's comment
        path = _resolve(line, folder)
        if path:
            pending["filepath"] = path
            entries.append(pending)
        pending = {}
    return entries, crossfade


def load(path):
    """Read a playlist file. Returns ``(entries, crossfade)``."""
    with open(path, "rb") as handle:
        raw = handle.read()
    folder = os.path.dirname(os.path.abspath(path))
    return loads(_decode(raw), folder=folder)
