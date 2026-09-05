"""Who is listening, and to what.

Tony, 5 September 2026: "add support to provide a stats window for the
current stream being sent audio to, how many are listening, what track is
playing."

The awkward part is that the server you SEND to is often not the server
people LISTEN to. Tony's own setup is the ordinary one for a station that
runs automation: Drop Deck connects to a Liquidsoap harbor on port 8001,
Liquidsoap decides what goes out and hands that to Icecast on port 8000, and
the audience is on 8000. Asking the harbor how many people are listening
would always answer nought, correctly and uselessly.

So this looks in more than one place, in the order most likely to be right,
and says which one answered. A station can also be told exactly where to look
if none of the guesses fit.

Nothing here needs a password. Icecast publishes its own statistics at
``/status-json.xsl`` and SHOUTcast at ``/stats``, and both are the same
information a listener sees on the server's home page. A stats window that
asked for an admin password would be a stats window nobody set up.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from . import constants as C

#: How long to wait for a server that is not answering. Short: this runs on a
#: timer behind a window somebody is reading, and a stale number now beats a
#: correct one after twenty seconds.
TIMEOUT = 6.0

#: The standard Icecast port, tried when the streaming port is something else.
#: A station sending to a harbor on 8001 or 8003 almost always has its
#: listeners on 8000, which is the whole reason this file guesses at all.
ICECAST_PORT = 8000


class Mount:
    """One stream on a server, and what is happening on it."""

    def __init__(self, mount="", name="", listeners=0, peak=None, title="",
                 bitrate=None, kind="", ours=False):
        self.mount = mount or ""
        self.name = name or ""
        self.listeners = int(listeners or 0)
        self.peak = int(peak) if peak not in (None, "") else None
        self.title = title or ""
        self.bitrate = bitrate
        self.kind = kind or ""
        #: Whether this is the mount Drop Deck itself is feeding.
        self.ours = bool(ours)

    def describe(self):
        """One line, written to be read aloud rather than looked at."""
        people = ("%d listening" % self.listeners if self.listeners != 1
                  else "1 listening")
        parts = [self.name or self.mount or "A stream", people]
        if self.peak:
            parts.append("most at once %d" % self.peak)
        if self.title:
            parts.append("playing %s" % self.title)
        if self.ours:
            parts.append("this is the one you are sending to")
        return ", ".join(parts)


class Stats:
    """What a server said, or why it said nothing."""

    def __init__(self, mounts=None, source="", error="", total=None):
        self.mounts = list(mounts or [])
        #: The address that answered, so somebody can check it themselves.
        self.source = source
        self.error = error or ""
        self._total = total

    def __bool__(self):
        return not self.error

    @property
    def listeners(self):
        """Everybody on the server, which is what a station wants to know."""
        if self._total is not None:
            return int(self._total)
        return sum(m.listeners for m in self.mounts)

    @property
    def ours(self):
        for mount in self.mounts:
            if mount.ours:
                return mount
        return None

    def summary(self):
        """The whole thing in a sentence, for the status line and for speech."""
        if self.error:
            return self.error
        if not self.mounts:
            return "The server answered, but nothing is streaming on it"
        people = self.listeners
        mine = self.ours
        if not people:
            said = "Nobody is listening"
        else:
            said = "%d listening" % people if people != 1 else "1 listening"
            if mine is not None and len(self.mounts) > 1:
                said += ", %d of them to yours" % mine.listeners
        if len(self.mounts) > 1:
            said += ", across %d streams" % len(self.mounts)
        mine = mine or (self.mounts[0] if len(self.mounts) == 1 else None)
        if mine is not None and mine.title:
            said += ". Playing %s" % mine.title
        return said


# ---------------------------------------------------------------------------
# Where to look
# ---------------------------------------------------------------------------
def candidates(settings):
    """Every address worth asking, best guess first.

    A station that has been told where its listeners are is asked there and
    nowhere else. Otherwise: the server it streams to, then the same host on
    Icecast's own port, which is where a harbor based setup keeps them.
    """
    told = (settings.get("stats_url") or "").strip()
    if told:
        return [told]
    host = (settings.get("host") or "").strip()
    if not host:
        return []
    port = int(settings.get("port") or ICECAST_PORT)
    kind = settings.get("server", "icecast")
    if kind == "shoutcast":
        # The port in the settings is the LISTENING port for SHOUTcast, which
        # is also where its statistics live.
        return ["http://%s:%d" % (host, port)]
    seen, out = set(), []
    for guess in ("http://%s:%d" % (host, port),
                  "http://%s:%d" % (host, ICECAST_PORT),
                  "https://%s" % host):
        if guess not in seen:
            seen.add(guess)
            out.append(guess)
    return out


def _get(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "%s/%s" % (C.APP_NAME, C.APP_VERSION),
        "Accept": "application/json, text/plain, */*"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
        return reply.read().decode("utf-8", "replace")


def _as_list(value):
    """Icecast emits one source as an object and several as an array."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _icecast(base, mount_wanted, name_wanted=""):
    body = _get(base.rstrip("/") + "/status-json.xsl")
    data = json.loads(body).get("icestats") or {}
    mounts = []
    for source in _as_list(data.get("source")):
        if not isinstance(source, dict):
            continue
        mount = source.get("mount") or ""
        if not mount:
            # Older Icecast leaves the mount out and only gives listenurl.
            listen = source.get("listenurl") or ""
            mount = urllib.parse.urlparse(listen).path or ""
        mounts.append(Mount(
            mount=mount,
            name=source.get("server_name") or "",
            listeners=source.get("listeners") or 0,
            peak=source.get("listener_peak"),
            title=(source.get("title") or source.get("yp_currently_playing")
                   or ""),
            bitrate=source.get("bitrate"),
            kind=source.get("server_type") or "",
            ours=bool(mount_wanted) and mount == mount_wanted))
    # A station streaming into automation sends to /live and its audience is
    # on /radio, so the mount never matches and nothing was marked as yours.
    # The station NAME does match, because it is the same station, and that
    # is what "yours" was asking about in the first place.
    if name_wanted and not any(m.ours for m in mounts):
        wanted = name_wanted.strip().lower()
        for mount in mounts:
            if mount.name.strip().lower() == wanted:
                mount.ours = True
                break
    total = data.get("listeners")
    return Stats(mounts, source=base,
                 total=total if isinstance(total, int) else None)


def _shoutcast(base, mount_wanted, name_wanted=""):
    """SHOUTcast, which answers a different question at a different place."""
    body = _get(base.rstrip("/") + "/stats?json=1")
    data = json.loads(body)
    mount = Mount(
        mount=mount_wanted or "/",
        name=data.get("servertitle") or "",
        listeners=data.get("currentlisteners") or 0,
        peak=data.get("peaklisteners"),
        title=data.get("songtitle") or "",
        bitrate=data.get("bitrate"),
        ours=True)
    return Stats([mount], source=base)


def fetch(settings):
    """Ask, and come back with either numbers or a reason. Never raises.

    ``settings`` is the streaming settings dict: host, port, mount, server,
    and optionally stats_url. Call it off the interface thread; it waits on a
    socket.
    """
    places = candidates(settings)
    if not places:
        return Stats(error="No server is set up yet, so there is nobody to ask")
    mount_wanted = (settings.get("mount") or "").strip()
    if mount_wanted and not mount_wanted.startswith("/"):
        mount_wanted = "/" + mount_wanted
    read = _shoutcast if settings.get("server") == "shoutcast" else _icecast
    name_wanted = (settings.get("name") or "").strip()

    reasons = []
    for base in places:
        try:
            return read(base, mount_wanted, name_wanted)
        except urllib.error.HTTPError as exc:
            reasons.append("%s said %s" % (base, exc.code))
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            reasons.append("%s did not answer" % base)
        except (ValueError, KeyError, TypeError):
            # It answered with something that was not statistics. Usually a
            # web page, which is what a server behind a proxy gives you.
            reasons.append("%s answered with something else" % base)
    return Stats(error=_explain(reasons, settings))


def _explain(reasons, settings):
    """Why nothing came back, and what to do about it.

    Written out rather than shortened to "failed", because the fix is almost
    always one specific thing: the listeners are on another port, or the
    server has no statistics file, and neither is guessable from the word
    failed.
    """
    where = ", ".join(reasons) if reasons else "nowhere to ask"
    if settings.get("server") == "shoutcast":
        return ("No statistics from the server. %s. SHOUTcast publishes them "
                "at /stats on the listening port." % where)
    return ("No statistics from the server. %s. Icecast publishes them at "
            "/status-json.xsl; if yours is missing that file, or your "
            "listeners are on a different address from the one you stream "
            "to, put the right one in Where listeners connect on the "
            "Streaming tab." % where)
