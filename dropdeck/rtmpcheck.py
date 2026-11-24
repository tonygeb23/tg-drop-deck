"""Asking a platform whether a stream key is right, without broadcasting.

Joshua, 20 September 2026: "pressing ctrl B it says it's going live to youtube
but nothing shows on my channel, i have the stream key and channel name in the
settings like it said to do."

Until this file existed, Drop Deck could not answer that. **Test the
connection** checked that the address resolved, that the port accepted a
socket and that TLS completed, and then said so in as many words: it "cannot
tell you whether the key itself is right". So the one thing a presenter needs
to know before a show was the one thing the button could not say, and the only
way to find out was to go on the air and look at a page they cannot see.

Why this is a separate RTMP client and not two lines of PyAV
------------------------------------------------------------

`RtmpDestination.connect` already proves a key: a wrong one is refused there.
It cannot be borrowed, because FFmpeg does the whole of the RTMP session
inside `container.start_encoding()` and then, in the same call and with no way
to stop in between, writes the FLV header, onMetaData and both codec sequence
headers. That is data on the wire.

**And the entire safety argument rests on sending no data.** YouTube's API
reference defines a stream as `active` when "the user is receiving data via
the stream", and a broadcast cannot be transitioned to testing or live while
the stream it is bound to is inactive: "The requested transition is not
allowed when the stream that is bound to the broadcast is inactive." Auto
start is that same transition. So a publish carrying no media never makes the
stream active, never starts a broadcast, creates no watch page, notifies
nobody and leaves nothing on the channel. **What nobody publishes is whether
YouTube counts an FLV header and two sequence headers as data.** So they are
not sent. Not one byte after the publish command.

Facebook is safe for a plainer reason: nothing is posted there until somebody
presses Go Live Now, which is what the app's help has said all along.

So this speaks RTMP as far as the publish response and stops:

    handshake     C0/C1 out, S0/S1/S2 in, C2 out. The simple version.
    connect       and read the _result.
    releaseStream and FCPublish, which the video platforms expect and which
                  a smaller server ignores. Neither is waited for.
    createStream  and read the stream id out of the _result.
    publish       and read the onStatus. THAT is the answer.
    deleteStream  and hang up.

The counterpart is `tools/mock_rtmp.py`, which is the same protocol from the
other end and is what the checks in `tests/test_3_8_4.py` talk to, so none of
this needs the internet or anybody's channel to be tested.

**Nothing here raises.** Every failure is a `Result` naming what happened in
words a presenter can act on, the same rule `secrets.py` follows and for the
same reason: somebody who cannot see the screen cannot read a traceback out
of a status bar.
"""
from __future__ import annotations

import os
import random
import socket
import ssl
import struct
import time
import urllib.parse

from . import constants as C

#: The largest RTMP message this will hold for a server. A command is a few
#: hundred bytes; the field it is declared in is three bytes wide, so a
#: server can ask for sixteen megabytes and trickle it.
MAX_MESSAGE = 64 * 1024

#: How much of a server's own wording may end up in a spoken sentence. The
#: far end chooses the length and a screen reader has to read it.
SAY_LIMIT = 200

#: RTMP version 3. There has never been another one in the wild.
VERSION = 3
HANDSHAKE_SIZE = 1536

#: What a client must assume until the server says otherwise, and what this
#: sends with. Never raised: the biggest thing sent here is a connect command
#: of a few hundred bytes, and chunking it is four lines.
DEFAULT_CHUNK_SIZE = 128

SET_CHUNK_SIZE = 1
ABORT = 2
ACK = 3
USER_CONTROL = 4
WINDOW_ACK_SIZE = 5
SET_PEER_BANDWIDTH = 6
COMMAND_AMF0 = 20

#: How long the whole conversation may take. Ten seconds is generous: the
#: measured answer from YouTube and Facebook is under one.
TIMEOUT = getattr(C, "STREAM_TIMEOUT", 10)

#: What the app calls itself to a server. Some RTMP servers log it, and one
#: that refuses an unknown client is a server whose owner should be told
#: which program is knocking.
FLASH_VER = "FMLE/3.0 (compatible; %s/%s)" % (C.APP_NAME.replace(" ", ""),
                                              C.APP_VERSION)


def certificate_bundle():
    """certifi's list of root authorities, or "" if this copy has none."""
    try:
        import certifi
        path = certifi.where()
    except Exception:
        return ""
    return path if path and os.path.isfile(path) else ""


def trust_context(system=True, bundle=""):
    """A context that checks the chain and the name, from the Windows store,
    a bundle file, or both: a root in EITHER is trusted.

    Apart from `tls_context` so a test can build one with the Windows side
    left out and prove the bundle alone is enough.
    """
    if not system:
        if not bundle:
            raise ValueError("there is nothing to take root authorities from")
        return ssl.create_default_context(cafile=bundle)
    context = ssl.create_default_context()
    if bundle:
        context.load_verify_locations(cafile=bundle)
    return context


def tls_context():
    """What counts as a server we may hand a stream key to.

    **One function, asked by this check, by going live** (`rtmpsrelay.Relay`)
    **and by the update check**, so they can never disagree about a server:
    a key this passes is a key Ctrl+B sends, and a certificate this refuses
    is one Ctrl+B refuses too. Until the relay existed the live stream
    checked nothing at all, so a check that passed said nothing about the
    broadcast.

    **The Windows store AND certifi.** Windows fills its store with roots on
    demand, and only when something asks Windows itself to check a
    certificate. Chrome and Firefox carry their own lists and never ask, so a
    machine used only through them may simply not have YouTube's or
    Facebook's root yet, and Python reads the store as it stands: it cannot
    make Windows go and fetch one. That would be a refusal at the top of a
    show, on a server that is perfectly genuine. certifi is Mozilla's list,
    so a root in either is trusted. The Windows side stays because it holds
    what a company or an antivirus program has added on purpose. The name is
    still checked against the address either way.
    """
    return trust_context(system=True, bundle=certificate_bundle())


# --------------------------------------------------------------------- AMF0

def _amf_string(value):
    raw = value.encode("utf-8")
    return b"\x02" + struct.pack(">H", len(raw)) + raw


def _amf_number(value):
    return b"\x00" + struct.pack(">d", float(value))


def _amf_bool(value):
    return b"\x01" + (b"\x01" if value else b"\x00")


def _amf_null():
    return b"\x05"


def _amf_object(pairs):
    out = b"\x03"
    for name, value in pairs:
        raw = name.encode("utf-8")
        out += struct.pack(">H", len(raw)) + raw + _amf_value(value)
    return out + b"\x00\x00\x09"


def _amf_value(value):
    if value is None:
        return _amf_null()
    if isinstance(value, bool):
        return _amf_bool(value)
    if isinstance(value, (int, float)):
        return _amf_number(value)
    if isinstance(value, str):
        return _amf_string(value)
    if isinstance(value, dict):
        return _amf_object(list(value.items()))
    return _amf_null()


class _Reader:
    """AMF0 out of a bytes buffer. Unknown types stop it rather than guess."""

    def __init__(self, data):
        self.data = data
        self.at = 0

    def _take(self, n):
        if self.at + n > len(self.data):
            raise ValueError("short")
        out = self.data[self.at:self.at + n]
        self.at += n
        return out

    def _string(self):
        length = struct.unpack(">H", self._take(2))[0]
        return self._take(length).decode("utf-8", "replace")

    def value(self):
        marker = self._take(1)[0]
        if marker == 0x00:
            return struct.unpack(">d", self._take(8))[0]
        if marker == 0x01:
            return self._take(1)[0] != 0
        if marker == 0x02:
            return self._string()
        if marker == 0x03:
            return self._object()
        if marker in (0x05, 0x06):
            return None
        if marker == 0x08:                        # ECMA array
            self._take(4)                         # the count, which lies
            return self._object()
        if marker == 0x0A:                        # strict array
            count = struct.unpack(">I", self._take(4))[0]
            return [self.value() for _ in range(min(count, 1000))]
        if marker == 0x0B:                        # date
            when = struct.unpack(">d", self._take(8))[0]
            self._take(2)
            return when
        if marker == 0x0C:                        # long string
            length = struct.unpack(">I", self._take(4))[0]
            return self._take(length).decode("utf-8", "replace")
        raise ValueError("amf type %d" % marker)

    def _object(self):
        out = {}
        while True:
            length = struct.unpack(">H", self._take(2))[0]
            name = self._take(length).decode("utf-8", "replace")
            if not name and self.data[self.at:self.at + 1] == b"\x09":
                self.at += 1
                return out
            out[name] = self.value()

    def all(self):
        out = []
        while self.at < len(self.data):
            try:
                out.append(self.value())
            except (ValueError, struct.error, IndexError):
                break
        return out


# ------------------------------------------------------------------ the URL

def split_url(base):
    """A base RTMP address as (scheme, host, port, app), or None.

    ``base`` is what the user has in the Address box, WITHOUT the key:
    "rtmps://a.rtmps.youtube.com/live2". The app is the path, which is what
    every encoder calls the Server, and the key is what goes after it.
    """
    parsed = urllib.parse.urlparse((base or "").strip())
    if parsed.scheme not in ("rtmp", "rtmps") or not parsed.hostname:
        return None
    port = parsed.port or (443 if parsed.scheme == "rtmps" else 1935)
    app = (parsed.path or "").strip("/")
    return parsed.scheme, parsed.hostname, port, app


# ---------------------------------------------------------------- the answer

#: What happened, as something the caller can branch on rather than a string
#: it has to read. The sentence is separate, in `said`, because the same
#: outcome is worded differently for a platform that puts you live at once
#: and one that shows a preview.
ACCEPTED = "accepted"
REFUSED = "refused"
NO_SERVER = "no-server"
NO_ROUTE = "no-route"
NO_TLS = "no-tls"
#: The secure connection was made and the server's certificate did not check
#: out: not trusted, for another name, or expired. Apart from NO_TLS because
#: it is not the network being in the way, it is something answering for the
#: platform that cannot prove it is the platform, and the key was not sent.
BAD_CERT = "bad-certificate"
NO_ANSWER = "no-answer"
BAD_ADDRESS = "bad-address"
NO_KEY = "no-key"


class TimedOut(Exception):
    """The conversation took longer than it was allowed to."""


class Result:
    """What the far end said, and whether it said yes."""

    def __init__(self, outcome, server_said="", detail=""):
        self.outcome = outcome
        #: The platform's OWN words, when it gave any. Worth repeating
        #: verbatim: "Publish Rejected: Invalid URL" is YouTube's way of
        #: saying the key is wrong, and paraphrasing it would lose the one
        #: thing somebody could search for.
        self.server_said = server_said or ""
        self.detail = detail or ""

    @property
    def ok(self):
        return self.outcome == ACCEPTED

    def __repr__(self):                              # pragma: no cover
        return "Result(%r, %r)" % (self.outcome, self.server_said)


# ------------------------------------------------------------ the conversation

class _Session:
    """One RTMP conversation, as far as the publish response and no further."""

    def __init__(self, scheme, host, port, app, key, timeout=TIMEOUT):
        self.scheme, self.host, self.port = scheme, host, port
        self.app, self.key = app, key
        self.timeout = timeout
        #: **When the whole conversation has to be over.** The socket
        #: timeout is per recv, which bounds nothing: a server that sends a
        #: control message every second keeps this reading for ever, because
        #: every control message is a `continue`. Measured against a server
        #: doing exactly that: still going at thirty seconds against a
        #: documented ten, with the button disabled for the rest of the
        #: session because the answer never came back. A deadline is the
        #: only thing that bounds it, and it lives here rather than in a
        #: loop counter because the loops are nested.
        self.deadline = time.monotonic() + timeout
        self.sock = None
        self.in_chunk = DEFAULT_CHUNK_SIZE
        self.transaction = 0
        #: Half read messages, by chunk stream, and the last header seen on
        #: each. RTMP's compressed headers mean a continuation carries none
        #: of its own, so the previous one IS the format.
        self._partial = {}
        self._last = {}

    # ------------------------------------------------------------- plumbing
    def open(self):
        self.sock = socket.create_connection((self.host, self.port),
                                             self.timeout)
        self.sock.settimeout(self.timeout)
        if self.scheme == "rtmps":
            context = tls_context()
            self.sock = context.wrap_socket(self.sock,
                                            server_hostname=self.host)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    def _recv(self, n):
        out = b""
        while len(out) < n:
            self._still_time()
            block = self.sock.recv(n - len(out))
            if not block:
                raise ConnectionError("the server closed the connection")
            out += block
        return out

    def _still_time(self):
        """Raise once the conversation has taken longer than it may."""
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise TimedOut("it did not answer in time")
        # The socket may not wait longer than the whole conversation may.
        try:
            self.sock.settimeout(min(self.timeout, max(0.05, left)))
        except OSError:
            pass

    def _send(self, data):
        self.sock.sendall(data)

    # ------------------------------------------------------------- handshake
    def handshake(self):
        """C0/C1 out, S0/S1/S2 in, C2 out. The simple one, not the signed one.

        The signed handshake exists for Flash DRM and no publishing ingest
        has ever required it. Measured against YouTube, Facebook and
        tools/mock_rtmp.py.
        """
        c1 = struct.pack(">II", 0, 0) + bytes(
            random.getrandbits(8) for _ in range(HANDSHAKE_SIZE - 8))
        self._send(bytes([VERSION]) + c1)
        version = self._recv(1)[0]
        if version != VERSION:
            raise ConnectionError("the server speaks RTMP version %d"
                                  % version)
        s1 = self._recv(HANDSHAKE_SIZE)
        self._recv(HANDSHAKE_SIZE)                   # S2, not checked
        self._send(s1)                               # C2 echoes S1

    # --------------------------------------------------------------- writing
    def send_message(self, type_id, payload, chunk_stream=3, stream_id=0):
        """One RTMP message, chunked. Always a full type 0 header first.

        Compressed headers save bytes on a video stream sending thirty
        messages a second. Nothing here sends more than five messages in
        its life, so the simple form is the right one.
        """
        header = (bytes([chunk_stream])
                  + struct.pack(">I", 0)[1:]          # timestamp, 3 bytes
                  + struct.pack(">I", len(payload))[1:]
                  + bytes([type_id])
                  + struct.pack("<I", stream_id))
        out = header + payload[:DEFAULT_CHUNK_SIZE]
        at = DEFAULT_CHUNK_SIZE
        while at < len(payload):
            out += bytes([0xC0 | chunk_stream]) + payload[at:at
                                                          + DEFAULT_CHUNK_SIZE]
            at += DEFAULT_CHUNK_SIZE
        self._send(out)

    def command(self, name, *args, chunk_stream=3, stream_id=0,
                transaction=None):
        """An AMF0 command. Returns the transaction id it was sent under."""
        if transaction is None:
            self.transaction += 1
            transaction = self.transaction
        payload = _amf_string(name) + _amf_number(transaction)
        for arg in args:
            payload += _amf_value(arg)
        self.send_message(COMMAND_AMF0, payload, chunk_stream=chunk_stream,
                          stream_id=stream_id)
        return transaction

    # --------------------------------------------------------------- reading
    def read_message(self):
        """The next whole message, as (type_id, payload). Blocks.

        Chunk reassembly is the only fiddly part of RTMP and it is fiddly in
        one place: a continuation chunk carries no length and no type, so
        both have to be remembered per chunk stream from the last full
        header that came in on it.
        """
        while True:
            first = self._recv(1)[0]
            fmt = first >> 6
            chunk_stream = first & 0x3F
            if chunk_stream == 0:
                chunk_stream = 64 + self._recv(1)[0]
            elif chunk_stream == 1:
                low, high = self._recv(2)
                chunk_stream = 64 + low + (high << 8)

            self._still_time()
            last = self._last.get(chunk_stream,
                                  {"length": 0, "type": 0, "stream": 0,
                                   "timestamp": 0, "extended": False})
            if fmt == 0:
                raw = self._recv(11)
                timestamp = int.from_bytes(raw[0:3], "big")
                length = int.from_bytes(raw[3:6], "big")
                type_id = raw[6]
                stream = struct.unpack("<I", raw[7:11])[0]
            elif fmt == 1:
                raw = self._recv(7)
                timestamp = int.from_bytes(raw[0:3], "big")
                length = int.from_bytes(raw[3:6], "big")
                type_id = raw[6]
                stream = last["stream"]
            elif fmt == 2:
                timestamp = int.from_bytes(self._recv(3), "big")
                length, type_id = last["length"], last["type"]
                stream = last["stream"]
            else:
                timestamp = last["timestamp"]
                length, type_id = last["length"], last["type"]
                stream = last["stream"]
            # **Whether the four extra bytes are there is a property of the
            # MESSAGE, not of this chunk.** A type 3 chunk carries no
            # timestamp field, so the 0xFFFFFF marker cannot appear in it,
            # and the decoded value remembered from the last header can
            # never equal the marker either. Reading the flag off `last`
            # rather than off the value is what keeps a continuation chunk
            # of an extended-timestamp message from being read four bytes
            # short, which desynchronises everything after it.
            extended = (timestamp == 0xFFFFFF if fmt != 3
                        else bool(last.get("extended")))
            if extended:
                timestamp = struct.unpack(">I", self._recv(4))[0]
            # A length is three bytes, so a server may declare 16 MB, and a
            # chunk stream id goes to 65599. Nothing here should ever see a
            # message bigger than a command, so anything larger is a server
            # asking us to hold memory for it.
            if length > MAX_MESSAGE:
                raise ConnectionError("the server sent something too large")
            self._last[chunk_stream] = {"length": length, "type": type_id,
                                        "stream": stream,
                                        "timestamp": timestamp,
                                        "extended": extended}

            held = self._partial.get(chunk_stream, b"")
            want = min(self.in_chunk, length - len(held))
            held += self._recv(want) if want > 0 else b""
            if len(held) < length:
                self._partial[chunk_stream] = held
                continue
            self._partial.pop(chunk_stream, None)
            if type_id == SET_CHUNK_SIZE and len(held) >= 4:
                # Ignoring this is how a reader silently desynchronises and
                # then blames the server for sending nonsense.
                self.in_chunk = max(1, struct.unpack(">I", held[:4])[0]
                                    & 0x7FFFFFFF)
                continue
            if type_id in (ABORT, ACK, USER_CONTROL, WINDOW_ACK_SIZE,
                           SET_PEER_BANDWIDTH):
                if type_id == WINDOW_ACK_SIZE and len(held) >= 4:
                    # Answered, because a server that asked and got nothing
                    # may stop sending. It costs one message.
                    try:
                        self.send_message(WINDOW_ACK_SIZE, held[:4],
                                          chunk_stream=2)
                    except OSError:
                        pass
                continue
            return type_id, held

    def read_command(self, wanted):
        """Read until one of ``wanted`` arrives. Returns (name, args).

        Commands are not guaranteed to arrive in the order they were asked
        for, and the video platforms send several of their own in between
        (onBWDone, onFCPublish), so this looks for a name rather than
        counting replies. It is bounded by the session deadline, not by a
        count: a count of iterations bounds nothing when a hostile server
        can make each iteration free.
        """
        while True:
            self._still_time()
            type_id, payload = self.read_message()
            if type_id != COMMAND_AMF0:
                continue
            values = _Reader(payload).all()
            if not values or not isinstance(values[0], str):
                continue
            if values[0] in wanted:
                return values[0], values[1:]


def _status_of(args):
    """The info object out of an _result or onStatus, whatever shape it took."""
    for arg in args:
        if isinstance(arg, dict) and ("code" in arg or "level" in arg):
            return arg
    return {}


def verify(base_url, key, timeout=TIMEOUT):
    """Does this server accept this stream key. Nothing is broadcast.

    Returns a `Result`. It never raises, and it never sends a single byte of
    audio, video or FLV: the conversation stops at the answer to `publish`.
    """
    if not (key or "").strip():
        return Result(NO_KEY)
    parts = split_url(base_url)
    if parts is None:
        return Result(BAD_ADDRESS)
    scheme, host, port, app = parts
    key = key.strip()

    # A key with a path in it, which Restream and some servers hand out as
    # "app/key". The publish name is everything after the app.
    session = _Session(scheme, host, port, app, key, timeout)
    try:
        socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return Result(NO_SERVER, detail=str(exc))
    try:
        try:
            session.open()
        except ssl.SSLCertVerificationError as exc:
            return Result(BAD_CERT, detail=exc.verify_message or str(exc))
        except ssl.SSLError as exc:
            return Result(NO_TLS, detail=str(exc))
        except OSError as exc:
            return Result(NO_ROUTE, detail=exc.strerror or str(exc))

        # How far the conversation got, because **the answer to a wrong key
        # is not the same shape on the two platforms**. Measured 20
        # September 2026 with a made up key: Facebook replies with an
        # onStatus saying "Publish Rejected: Invalid URL", and YouTube
        # simply CLOSES THE CONNECTION and says nothing at all. Both of
        # those are a refusal, and a dropped socket only means a refusal
        # once the publish has gone out: the same drop during the handshake
        # is a network problem and telling somebody their key is wrong over
        # one would send them hunting for a key that was fine.
        stage = "handshake"
        try:
            session.handshake()
            stage = "connect"
            tc_url = "%s://%s:%d/%s" % (scheme, host, port, app)
            session.command("connect", {
                "app": app,
                "type": "nonprivate",
                "flashVer": FLASH_VER,
                "tcUrl": tc_url,
                "fpad": False,
                "capabilities": 15.0,
                "audioCodecs": 4071.0,
                "videoCodecs": 252.0,
                "videoFunction": 1.0,
            })
            name, args = session.read_command(("_result", "_error"))
            if name == "_error":
                info = _status_of(args)
                return Result(REFUSED, server_said=_said(info))

            # Both are what a publishing client is expected to send and both
            # are ignored by servers that do not care. Neither is waited
            # for: FCPublish is answered with onFCPublish by some and with
            # nothing at all by others, and waiting on it hung against
            # mock_rtmp.
            stage = "createStream"
            session.command("releaseStream", None, key)
            session.command("FCPublish", None, key)
            session.command("createStream", None)
            name, args = session.read_command(("_result", "_error"))
            if name == "_error":
                return Result(REFUSED, server_said=_said(_status_of(args)))
            stream_id = 1
            for arg in args:
                if isinstance(arg, (int, float)):
                    stream_id = int(arg)

            # THE question. Chunk stream 4 and the stream id the server just
            # handed out, which is what every encoder does and what some
            # servers insist on.
            stage = "publish"
            session.command("publish", None, key, "live", chunk_stream=4,
                            stream_id=stream_id)
            name, args = session.read_command(("onStatus", "_error"))
            info = _status_of(args)
            code = str(info.get("code") or "")
            level = str(info.get("level") or "")
            if name == "onStatus" and (code == "NetStream.Publish.Start"
                                       or level == "status"):
                outcome = ACCEPTED
            else:
                outcome = REFUSED

            # Undone politely, so the ingest does not sit waiting for a
            # publisher that has gone. Best effort: the answer is already in
            # hand and nothing here may turn a good answer into a bad one.
            try:
                session.command("FCUnpublish", None, key)
                session.command("deleteStream", None, float(stream_id))
            except OSError:
                pass
            return Result(outcome, server_said=_said(info),
                          detail=str(info.get("code") or ""))
        except TimedOut as exc:
            return _gave_up(stage, str(exc))
        except ConnectionError as exc:
            return _gave_up(stage, str(exc))
        except socket.timeout:
            return _gave_up(stage, "it did not answer in time")
        except OSError as exc:
            return _gave_up(stage, exc.strerror or str(exc))
        except Exception as exc:                     # pragma: no cover
            return _gave_up(stage, str(exc))
    finally:
        session.close()


def _gave_up(stage, detail):
    """A conversation that stopped early, read according to where it stopped.

    Only after the publish command does a silence mean the key. YouTube says
    nothing at all there and simply hangs up; anywhere earlier, the same
    silence is the network and must be reported as the network.
    """
    if stage == "publish":
        return Result(REFUSED, detail=detail)
    return Result(NO_ANSWER, detail=detail)


def _said(info):
    """The platform's own SENTENCE out of a status object, or nothing.

    `description` only. `code` is "NetStream.Publish.BadName", which is a
    machine's name for the thing and is read out by a screen reader dot by
    dot; the caller already has a plain sentence for a refusal that came
    with no words, and that is the better answer. The code still goes into
    `Result.detail`, where a support question can find it.

    Capped, because this is interpolated into a spoken line and a server on
    the other end of the internet chooses its length.
    """
    value = info.get("description")
    if not isinstance(value, str) or not value.strip():
        return ""
    value = " ".join(value.split())
    return value[:SAY_LIMIT - 1] + "." if len(value) > SAY_LIMIT else value
