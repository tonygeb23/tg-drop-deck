"""Sending the show out: encode the program mix and push it to a server.

Drop Deck already knows how to make a show. This is the part that puts it on
the internet, so a presenter can go live to their own station without a second
program in the chain.

How it fits together
--------------------

    audio callback  ->  AirBus  ->  Streamer thread  ->  Encoder  ->  Sink
    (real time)         (ring)      (its own clock)      (PyAV)      (socket)

**Nothing here runs in the audio callback.** The callback's only job is to drop
a copy of the block into a ring and return. Encoding takes milliseconds and a
socket can block for seconds, and either one inside the callback is a gap in
the sound coming out of the speakers. So the ring is the wall between the show
and the network: if the network stalls, the ring overflows and the STREAM
loses audio while the show carries on untouched. That is the right way round.
A listener hearing a glitch is a shame; the presenter's own monitoring
breaking up mid sentence is the show falling over.

**The encoder is FFmpeg, through PyAV, which is already here** for reading m4a
and the rest. Its build has libmp3lame, libopus and aac in it, so nothing new
has to be downloaded or bundled. Measured, not assumed: see tests/test_stream.py.

**The protocols are written out longhand** rather than pulled from a library.
Icecast source is a dozen lines of HTTP, SHOUTcast is fewer, and both are
frozen in time. A library for this would be more code to install and more to
go wrong than the thing it replaces.
"""
from __future__ import annotations

import base64
import fractions
import io
import socket
import threading
import time
import urllib.parse
import urllib.request

import numpy as np
import soxr

try:
    import av
except Exception:      # pragma: no cover - PyAV missing is a real state
    av = None

from . import constants as C
from .engine import CHANNELS


# ---------------------------------------------------------------------------
# What the audio callback writes into
# ---------------------------------------------------------------------------

class AirBus:
    """A ring per sound card, summed on the way out.

    One ring would do if there were only ever one output. A bank can be sent
    to its own card though, and everything the presenter can hear should be
    what goes out, so each mixer gets a ring of its own and they are summed
    when the encoder asks.

    The rings are the drift absorber. Two sound cards are never quite the same
    speed, and neither is quite the speed of the clock the encoder runs on, so
    over an hour they slide by a few milliseconds. A ring that is running
    behind gives silence for the frames it does not have; one that is running
    ahead has its oldest frames dropped. Both are inaudible at these sizes and
    neither accumulates.

    Drift is not the same thing as a different RATE, and this used to confuse
    the two. A bank sent to a card that will only open at 44100, while the
    main output runs at 48000, delivers 44100 frames a second into a ring the
    encoder drains 48000 times a second. That is not a few milliseconds an
    hour: it is four thousand frames a minute, so the ring runs dry, that
    card gets nothing but gaps, and the ring being read at the pace of the
    slowest one leaves the faster ring overflowing and dropping. Each card is
    converted to the bus rate as it arrives instead, which is the same thing
    the microphone does and for the same reason.
    """

    def __init__(self, samplerate, seconds=None):
        self.samplerate = int(samplerate)
        self.frames = int(self.samplerate * (seconds or C.AIR_RING_SECONDS))
        self._lock = threading.Lock()
        self._rings = {}
        #: One per card that is not already at the bus rate, kept because
        #: resampling each block on its own would click at every boundary.
        self._rates = {}
        #: How long a ring may stay empty before it stops holding the stream
        #: up. One ring length, which is a lifetime for a scheduling hiccup
        #: and nothing at all to a listener.
        self._patience = float(seconds or C.AIR_RING_SECONDS)
        #: Blocks thrown away because the encoder could not keep up. The
        #: presenter is told, because silent dropouts are how a stream lies.
        self.dropped = 0

    def _ring_for(self, key):
        ring = self._rings.get(key)
        if ring is None:
            ring = {"buf": np.zeros((self.frames, CHANNELS), dtype=np.float32),
                    "write": 0, "filled": 0, "seen": time.monotonic()}
            self._rings[key] = ring
        return ring

    def write(self, key, block, rate=None):
        """Called from an audio callback. Must not block and must not raise.

        ``rate`` is the rate this card is actually running at. Left out, it is
        taken to be the bus rate, which is what a single output always is.
        """
        block = self._at_bus_rate(key, block, rate)
        n = len(block)
        if not n:
            return
        with self._lock:
            ring = self._ring_for(key)
            buf = ring["buf"]
            if n >= self.frames:
                buf[:] = block[-self.frames:]
                ring["write"] = 0
                ring["filled"] = self.frames
                self.dropped += 1
                return
            end = ring["write"] + n
            if end <= self.frames:
                buf[ring["write"]:end] = block
            else:
                first = self.frames - ring["write"]
                buf[ring["write"]:] = block[:first]
                buf[:n - first] = block[first:]
            ring["write"] = end % self.frames
            was = ring["filled"]
            ring["filled"] = min(self.frames, was + n)
            if was + n > self.frames:
                self.dropped += 1

    def _at_bus_rate(self, key, block, rate):
        """Convert a card running at its own rate into the bus's.

        Outside the lock on purpose: soxr allocates, and this is an audio
        callback that another card may be waiting behind. The resamplers are
        looked up by key and only ever touched by that card's own callback.
        """
        if not rate or int(rate) == self.samplerate:
            if key in self._rates:
                del self._rates[key]
            return block
        rate = int(rate)
        held = self._rates.get(key)
        if held is None or held[0] != rate:
            held = (rate, soxr.ResampleStream(rate, self.samplerate, CHANNELS,
                                              dtype="float32"))
            self._rates[key] = held
        try:
            return held[1].resample_chunk(block)
        except Exception:
            return block[:0]

    def available(self):
        """How much can be read right now.

        The thinnest ring that is still ALIVE, not the thinnest ring. A card
        that has stopped writing, because it was unplugged or because a
        device change replaced its mixer, would otherwise pin this at nought
        for ever: the live ring keeps filling, overflows, and the whole
        stream goes silent on account of a card nobody is listening to.

        A ring counts as alive until it has been empty for longer than the
        ring is long, which is far more than any ordinary scheduling hiccup
        and far less than a listener would sit through.
        """
        now = time.monotonic()
        with self._lock:
            if not self._rings:
                return 0
            alive = []
            for ring in self._rings.values():
                if ring["filled"]:
                    ring["seen"] = now
                    alive.append(ring["filled"])
                elif now - ring.get("seen", now) <= self._patience:
                    alive.append(0)
            return min(alive) if alive else 0

    def read(self, frames):
        """Take a block, summing every card. Short rings contribute silence."""
        out = np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            for ring in self._rings.values():
                have = min(frames, ring["filled"])
                if not have:
                    continue
                start = (ring["write"] - ring["filled"]) % self.frames
                end = start + have
                buf = ring["buf"]
                if end <= self.frames:
                    out[:have] += buf[start:end]
                else:
                    first = self.frames - start
                    out[:first] += buf[start:]
                    out[first:have] += buf[:have - first]
                ring["filled"] -= have
        return out

    def reset(self):
        with self._lock:
            self._rings = {}
            self.dropped = 0
        self._rates = {}


class Taps:
    """One tap, several buses.

    A mixer writes the on air mix to exactly one place. Once recording exists
    there are two places it might go, and they cannot share a bus: reading one
    takes the audio out of it, so a stream and a recording reading the same
    ring would each get half a show.

    So each gets a bus of its own and this writes to both. It is deliberately
    tiny and deliberately silent about failure: it runs inside an audio
    callback, where an exception silences a sound card.
    """

    def __init__(self, *buses):
        self.buses = [bus for bus in buses if bus is not None]

    def __bool__(self):
        return bool(self.buses)

    def __len__(self):
        return len(self.buses)

    def write(self, key, block, rate=None):
        for bus in self.buses:
            try:
                bus.write(key, block, rate)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Turning float blocks into something a listener's player understands
# ---------------------------------------------------------------------------

#: What a user can pick, and what each one needs at the far end. The content
#: type is what Icecast is told the stream is; get it wrong and players that
#: trust it play nothing.
FORMATS = {
    "mp3": {"label": "MP3", "codec": "libmp3lame", "container": "mp3",
            "content_type": "audio/mpeg",
            # No Xing header and no ID3: both belong to a file with a
            # beginning and an end, and a live stream has neither. Icecast
            # passes them through to listeners, who join in the middle.
            "muxer": {"write_xing": "0", "id3v2_version": "0"}},
    "opus": {"label": "Ogg Opus", "codec": "libopus", "container": "ogg",
             "content_type": "audio/ogg", "muxer": {}},
    # Brian Hartgen, 4 September 2026: "you may want to consider streaming
    # using AAC, which is what we do." ADTS rather than a bare stream, because
    # ADTS puts a header on every frame, which is what lets a listener joining
    # halfway through work out the rate and channels. Icecast has carried
    # AAC this way for years.
    "aac": {"label": "AAC", "codec": "aac", "container": "adts",
            "content_type": "audio/aac", "muxer": {}},
}

#: Bitrates offered, in kbps. 128 is the honest default for speech and music
#: together; Tony's own station runs 320.
BITRATES = (64, 96, 128, 160, 192, 256, 320)


class EncoderError(RuntimeError):
    """Raised when the encoder cannot be built, with a sayable reason."""


class Encoder:
    """Float blocks in, encoded bytes out, through PyAV.

    PyAV wants to write to a file. A live stream is not a file, so it is given
    an object that looks like one and hands everything written straight to a
    callback. That is also why the muxer options above turn off the headers
    that assume seeking: there is nowhere to seek back to.

    Opus only runs at 48k, and MP3 will not encode every rate a sound card
    might be at, so the caller is told what rate came out and resamples to it
    if it differs from the mixer's.
    """

    def __init__(self, on_bytes, fmt="mp3", samplerate=44100, bitrate=128):
        if av is None:
            raise EncoderError(
                "the encoder is missing, so this copy cannot stream")
        spec = FORMATS.get(fmt)
        if spec is None:
            raise EncoderError("%s is not a format this can send" % fmt)
        self.spec = spec
        self.format = fmt
        self.bitrate = int(bitrate)
        self.content_type = spec["content_type"]
        self._on_bytes = on_bytes
        self._pts = 0
        self._closed = False

        # Opus is a 48k codec. Anything else is resampled to 48k inside the
        # encoder anyway, so asking for it up front keeps the rate honest.
        self.samplerate = 48000 if fmt == "opus" else int(samplerate)

        sink = _CallbackFile(self._write)
        try:
            self._container = av.open(sink, mode="w", format=spec["container"],
                                      options=dict(spec["muxer"]))
            self._stream = self._container.add_stream(spec["codec"],
                                                      rate=self.samplerate)
            self._stream.bit_rate = self.bitrate * 1000
            self._stream.layout = "stereo"
        except Exception as exc:
            raise EncoderError("the %s encoder would not start: %s"
                               % (spec["label"], exc)) from exc

        #: How many frames the codec wants at a time. Everything is gathered
        #: into whole frames of this size, because a codec handed a short
        #: block pads it with silence and you hear the gaps.
        self.frame_size = int(self._stream.codec_context.frame_size or 1152)
        self._pending = np.zeros((0, CHANNELS), dtype=np.float32)

    def _write(self, data):
        if not self._closed:
            self._on_bytes(data)

    def feed(self, block):
        """Encode what whole frames this makes, and keep the remainder."""
        if self._closed:
            return
        if len(self._pending):
            block = np.concatenate((self._pending, block))
        n = self.frame_size
        whole = (len(block) // n) * n
        for start in range(0, whole, n):
            self._encode(block[start:start + n])
        self._pending = block[whole:].copy()

    def _encode(self, chunk):
        # PyAV wants planar float, one row per channel.
        planar = np.ascontiguousarray(chunk.T.astype(np.float32))
        frame = av.AudioFrame.from_ndarray(planar, format="fltp",
                                           layout="stereo")
        frame.rate = self.samplerate
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, self.samplerate)
        self._pts += len(chunk)
        for packet in self._stream.encode(frame):
            self._container.mux(packet)

    def close(self):
        """Flush what the codec is holding and finish the container.

        The remainder is padded out to a whole frame and encoded rather than
        dropped. A codec only takes whole frames, so up to one frame of audio
        was being thrown away at the end of every broadcast: the last fraction
        of a second before you came off air, which is exactly the moment
        somebody is likely to still be talking.
        """
        if self._closed:
            return
        try:
            if len(self._pending):
                tail = np.zeros((self.frame_size, CHANNELS), dtype=np.float32)
                tail[:len(self._pending)] = self._pending
                self._pending = np.zeros((0, CHANNELS), dtype=np.float32)
                self._encode(tail)
            for packet in self._stream.encode(None):
                self._container.mux(packet)
            self._container.close()
        except Exception:
            pass
        finally:
            self._closed = True


class _CallbackFile(io.RawIOBase):
    """A file that is really a function. What PyAV writes, the socket sends."""

    def __init__(self, on_write):
        self._on_write = on_write

    def writable(self):
        return True

    def write(self, data):
        self._on_write(bytes(data))
        return len(data)


# ---------------------------------------------------------------------------
# The far end
# ---------------------------------------------------------------------------

class SinkError(RuntimeError):
    """A connection that failed, carrying words worth saying out loud."""


def _basic(user, password):
    raw = ("%s:%s" % (user or "source", password or "")).encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _status_line(reply):
    line = reply.split(b"\r\n", 1)[0].decode("latin-1", "replace").strip()
    return line or "no answer at all"


def _explain(line):
    """Turn a status line into something a presenter can act on.

    A stream that will not connect is the worst thing this feature can do, so
    the failures that actually happen get named rather than left as a number
    the user has to go and look up.
    """
    low = line.lower()
    if "401" in low or "unauthorized" in low or "invalid password" in low:
        return "the server did not accept that password"
    if "403" in low or "forbidden" in low or "in use" in low:
        return ("the server refused the mount point, which usually means "
                "something else is already connected to it")
    if "404" in low or "not found" in low:
        return "the server has no mount point by that name"
    if "405" in low or "not allowed" in low:
        return "the server refused the way this tried to connect"
    return "the server said: %s" % line


class IcecastSink:
    """Icecast, and anything that speaks its source protocol.

    That includes the input.harbor in Liquidsoap, which is what a lot of
    stations put in front of Icecast so a presenter can take over from the
    automation for a live show.

    Two ways in, tried in that order:

    - **SOURCE**, which every Icecast 2 and every harbor understands.
    - **PUT**, which Icecast 2.4 added and some hosted providers now insist on.

    SOURCE goes first because it is the one that works everywhere. A refusal
    that might be the method rather than the password gets one try at PUT
    before the user is told anything discouraging, so a provider that has
    turned SOURCE off still connects without anybody having to know why.
    """

    def __init__(self, host, port, mount, user, password, content_type,
                 name="", description="", genre="", url="", bitrate=128,
                 samplerate=44100, public=False, timeout=None):
        self.host = host
        self.port = int(port)
        self.mount = mount if mount.startswith("/") else "/" + mount
        self.user = user or "source"
        self.password = password or ""
        self.content_type = content_type
        self.name = name
        self.description = description
        self.genre = genre
        self.url = url
        self.bitrate = int(bitrate)
        self.samplerate = int(samplerate)
        self.public = bool(public)
        self.timeout = timeout or C.STREAM_TIMEOUT
        self.sock = None
        self.method = None

    # ---------------------------------------------------------- connecting --
    def _headers(self):
        return [
            ("Authorization", _basic(self.user, self.password)),
            ("User-Agent", "TG Drop Deck/%s" % C.APP_VERSION),
            ("Content-Type", self.content_type),
            ("Ice-Public", "1" if self.public else "0"),
            ("Ice-Name", self.name or "TG Drop Deck"),
            ("Ice-Description", self.description or ""),
            ("Ice-Genre", self.genre or ""),
            ("Ice-URL", self.url or ""),
            ("Ice-Audio-Info",
             "ice-samplerate=%d;ice-bitrate=%d;ice-channels=%d"
             % (self.samplerate, self.bitrate, CHANNELS)),
        ]

    def _request(self, method):
        protocol = "HTTP/1.1" if method == "PUT" else "ICE/1.0"
        head = ["%s %s %s" % (method, self.mount, protocol)]
        if method == "PUT":
            head.append("Host: %s:%d" % (self.host, self.port))
        for key, value in self._headers():
            head.append("%s: %s" % (key, value))
        if method == "PUT":
            head.append("Expect: 100-continue")
        return ("\r\n".join(head) + "\r\n\r\n").encode("utf-8")

    @staticmethod
    def _read_reply(sock):
        sock.settimeout(C.STREAM_REPLY_TIMEOUT)
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 4096:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
        return data

    def _try(self, method):
        """Returns None when connected, or the status line that refused it."""
        try:
            sock = socket.create_connection((self.host, self.port),
                                            self.timeout)
        except OSError as exc:
            raise SinkError("could not reach %s on port %d: %s"
                            % (self.host, self.port, exc.strerror or exc))
        try:
            sock.sendall(self._request(method))
            reply = self._read_reply(sock)
        except socket.timeout:
            # A harbor that likes the request sometimes says nothing at all
            # and simply waits for audio. Silence here is consent.
            sock.settimeout(self.timeout)
            self.sock = sock
            self.method = method
            return None
        except OSError as exc:
            sock.close()
            raise SinkError("the server hung up: %s" % (exc.strerror or exc))
        line = _status_line(reply)
        if " 200" in line or line.startswith("ICY 200") or "100 Continue" in line:
            sock.settimeout(self.timeout)
            self.sock = sock
            self.method = method
            return None
        sock.close()
        return line

    def connect(self):
        refused = self._try("SOURCE")
        if refused is None:
            return self
        second = self._try("PUT")
        if second is None:
            return self
        raise SinkError(_explain(refused))

    # ------------------------------------------------------------- sending --
    def write(self, data):
        if self.sock is None:
            raise SinkError("not connected")
        try:
            self.sock.sendall(data)
        except OSError as exc:
            raise SinkError("the connection to the server dropped: %s"
                            % (exc.strerror or exc))

    def close(self):
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    # ------------------------------------------------------------ metadata --
    def metadata_url(self, title):
        query = urllib.parse.urlencode({"mount": self.mount,
                                        "mode": "updinfo",
                                        "song": title,
                                        "charset": "UTF-8"})
        return "http://%s:%d/admin/metadata?%s" % (self.host, self.port, query)

    def send_metadata(self, title):
        """Tell the server what is playing, so listeners see the title.

        Its own short lived HTTP request, which is how Icecast has always
        taken this. Failing is not worth interrupting a show over, so it
        returns whether it worked and otherwise says nothing.
        """
        if not title:
            return False
        request = urllib.request.Request(self.metadata_url(title))
        request.add_header("Authorization", _basic(self.user, self.password))
        request.add_header("User-Agent", "TG Drop Deck/%s" % C.APP_VERSION)
        try:
            with urllib.request.urlopen(
                    request, timeout=C.STREAM_META_TIMEOUT) as reply:
                return 200 <= reply.status < 300
        except Exception:
            return False


class ShoutcastSink(IcecastSink):
    """SHOUTcast, which is older and does it differently.

    Three differences, all of them things a user would otherwise have to
    discover by failing:

    - **The source port is the listening port plus one.** Somebody told their
      stream is on 8000 has to connect a source to 8001, and that is the most
      common reason a SHOUTcast source will not connect. The port set here is
      the listening one and the plus one happens inside, so nobody has to know.
    - **The password comes first**, on a line of its own, before any headers.
    - **Metadata goes to admin.cgi on the listening port**, not to the source
      port and not to /admin/metadata.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: What a listener connects to. Kept, because metadata goes there.
        self.listen_port = self.port
        self.port = self.listen_port + 1

    def connect(self):
        try:
            sock = socket.create_connection((self.host, self.port),
                                            self.timeout)
        except OSError as exc:
            raise SinkError("could not reach %s on port %d, the source port "
                            "for a stream listened to on %d: %s"
                            % (self.host, self.port, self.listen_port,
                               exc.strerror or exc))
        sock.settimeout(C.STREAM_REPLY_TIMEOUT)
        try:
            sock.sendall((self.password + "\r\n").encode("utf-8"))
            reply = sock.recv(64)
        except OSError as exc:
            sock.close()
            raise SinkError("the server hung up while checking the password: "
                            "%s" % (exc.strerror or exc))
        text = reply.decode("latin-1", "replace").strip()
        if not text.upper().startswith("OK"):
            sock.close()
            raise SinkError("the server did not accept that password"
                            if text else "the server said nothing back")
        head = [
            "icy-name:%s" % (self.name or "TG Drop Deck"),
            "icy-genre:%s" % (self.genre or ""),
            "icy-url:%s" % (self.url or ""),
            "icy-pub:%d" % (1 if self.public else 0),
            "icy-br:%d" % self.bitrate,
            "content-type:%s" % self.content_type,
        ]
        try:
            sock.sendall(("\r\n".join(head) + "\r\n\r\n").encode("utf-8"))
        except OSError as exc:
            sock.close()
            raise SinkError("the server hung up: %s" % (exc.strerror or exc))
        sock.settimeout(self.timeout)
        self.sock = sock
        self.method = "SHOUTCAST"
        return self

    def metadata_url(self, title):
        query = urllib.parse.urlencode({"pass": self.password,
                                        "mode": "updinfo",
                                        "song": title})
        return "http://%s:%d/admin.cgi?%s" % (self.host, self.listen_port,
                                              query)

    def send_metadata(self, title):
        if not title:
            return False
        request = urllib.request.Request(self.metadata_url(title))
        request.add_header("User-Agent", "TG Drop Deck/%s" % C.APP_VERSION)
        try:
            with urllib.request.urlopen(
                    request, timeout=C.STREAM_META_TIMEOUT) as reply:
                return 200 <= reply.status < 300
        except Exception:
            return False


#: What the user picks from, and what each one builds.
SERVERS = {
    "icecast": ("Icecast, or Liquidsoap harbor", IcecastSink),
    "shoutcast": ("SHOUTcast", ShoutcastSink),
}


# ---------------------------------------------------------------------------
# Destinations: one place the show goes, and everything it takes to get there
# ---------------------------------------------------------------------------

class Destination:
    """One place the show goes. Owns its encoder AND its transport.

    Icecast and RTMP divide the work differently, and that is the whole reason
    this layer exists.

    With Icecast the encoder makes bytes and something else owns the socket,
    which is why `Encoder` takes an `on_bytes` callback and `IcecastSink` does
    the writing. RTMP is not a pipe you push bytes down: it is a session with a
    handshake, chunk streams and AMF commands, and FFmpeg implements all of it.
    So for RTMP, PyAV opens the network itself and there is no byte callback to
    hook and no socket of ours to hold.

    Rather than teach `Streamer` about both, it holds one of these and asks it
    for what it needs. What `Streamer` still owns is the part that is the same
    either way: the retry loop, the backlog watching and the spoken state.
    """

    #: Whether this destination needs pictures as well as sound. An RTMP one
    #: does, and not because we want video: YouTube REFUSES an audio only
    #: ingest, so something has to be on the screen even for a radio show.
    wants_video = False

    #: The rate the encoder settled on, which the caller resamples to.
    samplerate = 44100

    #: How much audio the pump gathers before handing it over. A quarter of a
    #: second is fine for Icecast, which is a pipe: bytes arrive when they
    #: arrive and a listener's player has seconds of buffer.
    chunk_seconds = C.STREAM_CHUNK_SECONDS

    def connect(self):
        """Open it. Raises SinkError or EncoderError with a sayable reason."""
        raise NotImplementedError

    def feed(self, block):
        """A block of float32 audio, shaped (frames, CHANNELS)."""
        raise NotImplementedError

    def send_metadata(self, title):
        """Tell the far end what is playing. False when it will not take it."""
        return False

    def describe(self):
        """One short line for the status bar and for speech."""
        return ""

    def close(self):
        raise NotImplementedError


class IcecastDestination(Destination):
    """The path that already worked: an `Encoder` feeding a `Sink`.

    This is a wrapper and deliberately nothing more. Every decision inside it
    was made and tested before this class existed, so it delegates rather than
    reimplementing, and `SERVERS` stays the registry it always was. A test that
    puts its own sink in `SERVERS` still works, which is the point.
    """

    def __init__(self, settings, bus_samplerate):
        self.settings = dict(settings)
        self.bus_samplerate = int(bus_samplerate)
        self.encoder = None
        self.sink = None
        kind = self.settings.get("server", "icecast")
        self._label, self._factory = SERVERS.get(kind, SERVERS["icecast"])
        self.format = self.settings.get("format", "mp3")
        self.spec = FORMATS.get(self.format) or FORMATS["mp3"]
        self.bitrate = int(self.settings.get("bitrate", 128))
        self.bytes_sent = 0

    def connect(self):
        # Built first, because the sink has to be told the rate the encoder
        # settled on. Everything after this point is inside a try, because a
        # server that is down or a password that is wrong raises out of
        # connect() and an encoder that is never assigned is never closed:
        # a FFmpeg codec context and its buffers, leaked once per attempt,
        # and the reconnect loop attempts every few seconds all night.
        encoder = Encoder(self._write, fmt=self.format,
                          samplerate=self.bus_samplerate, bitrate=self.bitrate)
        try:
            sink = self._factory(
                host=self.settings.get("host", ""),
                port=int(self.settings.get("port", 8000)),
                mount=self.settings.get("mount", "/live"),
                user=self.settings.get("user", "source"),
                password=self.settings.get("password", ""),
                content_type=self.spec["content_type"],
                name=self.settings.get("name", ""),
                description=self.settings.get("description", ""),
                genre=self.settings.get("genre", ""),
                url=self.settings.get("url", ""),
                bitrate=self.bitrate,
                samplerate=encoder.samplerate,
                public=bool(self.settings.get("public", False)),
            )
            sink.connect()
        except Exception:
            try:
                encoder.close()
            except Exception:
                pass
            raise
        self.sink = sink
        self.encoder = encoder
        self.samplerate = encoder.samplerate
        return self

    def _write(self, data):
        """The encoder's bytes, straight out of the door."""
        sink = self.sink
        if sink is None:
            return
        sink.write(data)
        self.bytes_sent += len(data)

    def feed(self, block):
        if self.encoder is not None:
            self.encoder.feed(block)

    def send_metadata(self, title):
        if self.sink is None:
            return False
        return self.sink.send_metadata(title)

    def describe(self):
        return "%d k %s to %s" % (self.bitrate, self.spec["label"],
                                  self.settings.get("host", ""))

    def close(self):
        encoder, self.encoder = self.encoder, None
        sink, self.sink = self.sink, None
        # The encoder is closed first so its last packets have somewhere to
        # go, so the sink is put back for the length of that call.
        if encoder is not None:
            self.sink = sink
            try:
                encoder.close()
            except Exception:
                pass
            self.sink = None
        if sink is not None:
            try:
                sink.close()
            except Exception:
                pass


def _video_options(encoder, fps, bitrate=0):
    """Encoder options that give the keyframe interval the platforms want.

    A keyframe every two seconds is what YouTube asks for and what Facebook
    expects, and four seconds is the most either will take. Getting it wrong
    is the classic "it connects and then the platform calls the stream
    unhealthy", so it is worth being exact rather than hopeful.

    **The two encoders need different arguments for it, which was measured on
    7 September 2026 and is not obvious.** `h264_mf` honours a plain `g` and
    puts keyframes exactly where it is told. `libx264` does NOT: `g` is only a
    maximum, and its scene cut detector inserts extra keyframes whenever the
    picture changes a lot. Measured with `preset=veryfast tune=zerolatency
    g=60`, libx264 emitted a keyframe every SEVEN frames on changing content,
    which is most of the bitrate spent on keyframes. `tune=zerolatency` does
    not turn that off; only `sc_threshold=0` does, with `keyint_min` to stop
    it going the other way.

    Cutting between a card and a camera is exactly the kind of change that
    triggers it, so this is not a theoretical case for this app.
    """
    interval = int(fps * C.RTMP_KEYFRAME_SECONDS)
    options = {"g": str(interval)}
    if encoder == "libx264":
        options.update({
            "preset": "veryfast",
            "tune": "zerolatency",
            # No B frames: they need reordering and a live FLV has nowhere to
            # reorder into.
            "bf": "0",
            "keyint_min": str(interval),
            "sc_threshold": "0",
        })
        if bitrate:
            # TRUE CBR, WITH FILLER, and this is not a nicety.
            #
            # A still card compresses to almost nothing: asked for 2500 kbps
            # it really sent 62. Both platforms publish bitrate floors and
            # Facebook's is 400 kbps even at 360p, so a radio show sending a
            # station card sat an order of magnitude underneath it. YouTube
            # raises "bitrate lower than recommended" for the same reason and
            # asks for CBR anyway.
            #
            # minrate and maxrate alone do NOT do it: measured, they left the
            # card at 62 kbps. nal-hrd=cbr with filler is what actually pads
            # the stream to the rate that was asked for, and it took it to
            # 2467 of 2500. It is also what OBS does for CBR.
            rate = "%dk" % int(bitrate)
            # A half second buffer rather than a whole one. Measured with a
            # one second VBV, a cut from the card to the camera dipped to
            # 1016 kbps and peaked at 4210, either side of the 1500 to 4000
            # Facebook publishes for 720p30. Halving it holds the swing in.
            options.update({"minrate": rate, "maxrate": rate,
                            "bufsize": "%dk" % int(bitrate * C.RTMP_VBV_SECONDS),
                            "x264-params": "nal-hrd=cbr:filler=1"})
    return options


class RtmpDestination(Destination):
    """YouTube, Facebook, Twitch, or any RTMP server, with a picture.

    **A picture is not optional.** YouTube refuses an ingest with no video
    track, so even a radio show going out on YouTube has to send something.
    That is what the card is for: a still image costs about 64 kbps and six
    per cent of one core, measured, so a show with no camera pays almost
    nothing for the picture it is obliged to send.

    **The audio is the master clock and the video is stamped against it.** A
    camera is a second clock and it is never quite the same speed as the sound
    card, so a video frame is timestamped by where the AUDIO has got to rather
    than by when the frame turned up. A camera running slow repeats a frame,
    one running fast has a frame dropped, and neither drifts. Measured over
    five seconds of this design: two milliseconds apart at the end, where lip
    sync wants to be inside a hundred.

    Video is pulled, never pushed. `feed` is called with audio from the
    `Streamer` thread and asks the picture source for whatever frames that
    audio has now paid for, so everything stays on one thread and one clock.
    """

    wants_video = True

    #: MUCH smaller than the Icecast one, and this is what stops the picture
    #: stuttering. Video frames are pumped from feed(), so the pump interval
    #: IS the video pacing: at a quarter of a second, eight frames were muxed
    #: back to back and then nothing went out for two hundred milliseconds.
    #: Measured 7 September 2026 at 720p30: median gap between frames 11 ms,
    #: p95 192 ms, 36 gaps over 100 ms in ten seconds. The average was a
    #: perfect 33 ms and the picture was choppy anyway, which is why an
    #: average is the wrong thing to look at here.
    #:
    #: One frame period is the right size: the pump then carries at most one
    #: or two frames each time round and they leave evenly.
    chunk_seconds = 1.0 / C.RTMP_FPS

    def __init__(self, settings, bus_samplerate, video_source=None):
        if av is None:
            raise EncoderError(
                "the encoder is missing, so this copy cannot stream")
        self.settings = dict(settings)
        self.bus_samplerate = int(bus_samplerate)
        self.video_source = video_source
        # The rate the bus is really at. It used to be hard wired to 44100,
        # which quietly resampled every block of a 48k show for no reason, on
        # the thread that is also carrying the audio.
        self.samplerate = int(settings.get("samplerate")
                              or bus_samplerate or 44100)
        self.bitrate = int(self.settings.get("bitrate", 128))
        self.video_bitrate = int(self.settings.get("video_bitrate",
                                                   C.RTMP_VIDEO_BITRATE))
        self.width = int(self.settings.get("video_width", C.RTMP_WIDTH))
        self.height = int(self.settings.get("video_height", C.RTMP_HEIGHT))
        self.fps = int(self.settings.get("video_fps", C.RTMP_FPS))
        # The pump interval IS the video pacing, so it follows the real frame
        # rate rather than the default one. At 15 fps a 33 ms pump would be
        # twice as often as it needs to be; at 60 it would be half.
        self.chunk_seconds = 1.0 / max(1, self.fps)
        self.encoder_name = self.settings.get("video_encoder",
                                              C.RTMP_VIDEO_ENCODER)
        self._container = None
        self._audio = None
        self._video = None
        self._apts = 0
        self._frames_sent = 0
        self._pending = np.zeros((0, CHANNELS), dtype=np.float32)
        self.bytes_sent = 0

    # ------------------------------------------------------------------ url --
    def url(self):
        """Where this goes. A saved server plus the key, or a whole URL.

        The key is kept apart from the URL everywhere else in the app, because
        it is a credential and the URL is not. They only meet here.
        """
        base = (self.settings.get("host") or "").strip()
        key = (self.settings.get("password") or "").strip()
        if not base:
            raise SinkError("there is no server address for this station")
        if not key:
            raise SinkError("there is no stream key for this station")
        return base.rstrip("/") + "/" + key

    # -------------------------------------------------------------- opening --
    def connect(self):
        url = self.url()
        parsed = urllib.parse.urlparse(self.settings.get("host", ""))
        if parsed.hostname:
            _resolve(parsed.hostname, parsed.port)
        try:
            # No rtmp_live here: it is an INPUT option, for playing a stream
            # rather than publishing one, and FFmpeg says "Some options were
            # not used" if it is passed on the way out.
            container = av.open(url, mode="w", format="flv",
                                timeout=C.STREAM_TIMEOUT)
        except Exception as exc:
            raise SinkError(_explain_rtmp(exc, self.settings)) from exc
        try:
            video = self._add_video(container)
            audio = container.add_stream("aac", rate=self.samplerate)
            audio.bit_rate = self.bitrate * 1000
            audio.layout = "stereo"
            audio.time_base = fractions.Fraction(1, self.samplerate)
        except Exception as exc:
            try:
                container.close()
            except Exception:
                pass
            raise EncoderError("the video encoder would not start: %s"
                               % exc) from exc

        # **av.open does NOT connect.** Measured 7 September 2026: opening an
        # RTMP URL for writing succeeds against a server that is not running,
        # because FFmpeg does not touch the network until the header is
        # written. Without this line a dead server, a wrong address or a
        # refused key all got as far as ON AIR and only then dropped, so the
        # app told a presenter they were live when nothing was listening.
        # start_encoding() writes the header, which is what makes the
        # handshake happen, so the failure lands here where the retry loop
        # expects it and the state is honest.
        try:
            with _ffmpeg_log() as log:
                container.start_encoding()
        except Exception as exc:
            try:
                container.close()
            except Exception:
                pass
            raise SinkError(_explain_rtmp(exc, self.settings,
                                          _server_error(log))) from exc

        self._container = container
        self._audio = audio
        self._video = video
        self.frame_size = int(audio.codec_context.frame_size or 1024)
        return self

    def _add_video(self, container):
        """The video stream, falling back if the chosen encoder will not open.

        The fallback existed as a constant and was never used, so a machine
        where libx264 would not open had no video at all rather than the
        slower encoder Windows always has.
        """
        tried = []
        last = None
        for name in (self.encoder_name,) + tuple(C.RTMP_VIDEO_ENCODERS):
            if not name or name in tried:
                continue
            tried.append(name)
            try:
                video = container.add_stream(name, rate=self.fps)
                video.width = self.width
                video.height = self.height
                video.pix_fmt = "yuv420p"
                video.bit_rate = self.video_bitrate * 1000
                video.time_base = fractions.Fraction(1, 1000)
                video.options = _video_options(name, self.fps,
                                               self.video_bitrate)
                self.encoder_name = name
                return video
            except Exception as exc:
                last = exc
        raise EncoderError(
            "no video encoder on this machine would start, so the picture "
            "cannot be sent: %s" % last)

    # -------------------------------------------------------------- feeding --
    def feed(self, block):
        """Audio in. Video is pulled to match, so this drives both."""
        if self._container is None:
            return
        if len(self._pending):
            block = np.concatenate((self._pending, block))
        n = self.frame_size
        whole = (len(block) // n) * n
        for start in range(0, whole, n):
            self._encode_audio(block[start:start + n])
        self._pending = block[whole:].copy()
        # How many frames THIS much audio is worth. The cap below is relative
        # to that, not an absolute: a caller handing over a quarter of a
        # second at a time is entitled to seven frames for it, and capping at
        # two made the video fall permanently behind the sound.
        self._pump_video(len(block) / float(self.samplerate or 1))

    def _encode_audio(self, chunk):
        planar = np.ascontiguousarray(chunk.T.astype(np.float32))
        frame = av.AudioFrame.from_ndarray(planar, format="fltp",
                                           layout="stereo")
        frame.rate = self.samplerate
        frame.pts = self._apts
        frame.time_base = fractions.Fraction(1, self.samplerate)
        self._apts += len(chunk)
        for packet in self._audio.encode(frame):
            self._mux(packet)

    @property
    def audio_seconds(self):
        """Where the master clock has got to."""
        return self._apts / float(self.samplerate or 1)

    def _pump_video(self, audio_seconds=0.0):
        """Send whatever frames the audio clock has now paid for.

        ``audio_seconds`` is how much audio was just handed over. The cap is
        relative to it, so this keeps up with whatever size the caller uses
        while still refusing to dump an unbounded burst after a stall. A flat
        cap does one or the other and not both: too high and a stall becomes
        a burst, too low and the picture silently falls behind the sound for
        ever, which is what a first attempt at this did.
        """
        if self._video is None:
            return
        due = int(self.audio_seconds * self.fps)
        earned = int(audio_seconds * self.fps) + 1
        due = min(due, self._frames_sent + max(C.RTMP_CATCHUP_FRAMES, earned))
        while self._frames_sent < due:
            picture = self._picture()
            if picture is None:
                return
            frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
            frame = frame.reformat(format="yuv420p")
            frame.pts = int(round(self._frames_sent * 1000.0 / self.fps))
            frame.time_base = fractions.Fraction(1, 1000)
            self._frames_sent += 1
            for packet in self._video.encode(frame):
                self._mux(packet)

    def set_video_source(self, source):
        """Point the encoder at a different picture, mid stream.

        Safe while live, and it is worth being exact about why, because the
        things that would make it unsafe are all avoided rather than absent.

        The encoder is locked to one size and one frame rate from the moment
        `connect()` writes the FLV header: width, height, pixel format and
        rate go on the codec context there and the H.264 sequence header has
        already gone out. Nothing here touches any of them. `_pump_video`
        asks every source for `frame(self.width, self.height)`, so a new
        source is told the size rather than choosing it.

        Timestamps survive because they were never the source's to give.
        Video PTS counts `_frames_sent` against the audio clock, so a swap is
        invisible to the timeline: the next frame is stamped where it would
        have been anyway. There is no keyframe to force and no session to
        renegotiate.

        The assignment is one attribute and `_picture` reads it into a local
        before using it, so the streaming thread either gets the old source
        or the new one and never a half swapped pair.
        """
        self.video_source = source

    def _picture(self):
        """The next picture, or black when there is no source yet."""
        source = self.video_source
        if source is None:
            return np.zeros((self.height, self.width, 3), dtype=np.uint8)
        try:
            return source.frame(self.width, self.height)
        except Exception:
            # A picture source that throws must not take the stream down. The
            # show carries on with the last thing that worked, or with black.
            return np.zeros((self.height, self.width, 3), dtype=np.uint8)

    def _mux(self, packet):
        # PyAV owns the socket here, so there is no write to count. The size
        # of what is handed to the muxer is close enough, and what it is for
        # is proving the stream is alive rather than billing anybody.
        self.bytes_sent += packet.size or 0
        try:
            self._container.mux(packet)
        except Exception as exc:
            # Through the sanitiser like every other RTMP failure. PyAV's
            # exception text can carry the URL it was opened with, and that
            # URL has the stream key on the end of it. This is the only path
            # that used to interpolate it raw into a line the screen reader
            # then reads out.
            raise SinkError("the connection dropped. %s"
                            % _explain_rtmp(exc, self.settings)) from exc

    # ------------------------------------------------------------- the rest --
    def send_metadata(self, title):
        """RTMP carries no title the way Icecast does.

        YouTube and Facebook take the title from the broadcast set up on their
        own site, not from the stream, so there is nothing to send and saying
        so here is better than a silent no-op somebody later calls a bug.
        """
        return False

    def describe(self):
        return "%dk video, %dk audio to %s" % (
            self.video_bitrate, self.bitrate,
            _host_of(self.settings.get("host", "")))

    def close(self):
        container, self._container = self._container, None
        if container is None:
            return
        try:
            if self._video is not None:
                for packet in self._video.encode(None):
                    container.mux(packet)
            if self._audio is not None:
                for packet in self._audio.encode(None):
                    container.mux(packet)
        except Exception:
            pass
        try:
            container.close()
        except Exception:
            pass
        self._audio = None
        self._video = None


def bitrate_advice(server, width, height, fps, video_kbps, audio_kbps=128):
    """What is wrong with these settings, in the platform's own numbers.

    Said BEFORE going live rather than discovered after. Facebook publishes
    real lower and upper bounds per resolution and says plainly that missing
    them can end a broadcast; YouTube publishes one recommended figure for
    H.264 and no bounds at all, so it gets a gentler wording.
    """
    key = (int(width), int(height), int(fps))
    notes = []
    if server == "facebook":
        span = C.FACEBOOK_BITRATES.get(key)
        if span:
            low, high = span
            if video_kbps < low:
                notes.append(
                    "Facebook asks for at least %d kbps at this size and you "
                    "have %d. Below their range a broadcast can be ended."
                    % (low, video_kbps))
            elif video_kbps > high:
                notes.append(
                    "Facebook asks for no more than %d kbps at this size and "
                    "you have %d." % (high, video_kbps))
        if audio_kbps > 256:
            notes.append("Facebook will not take audio above 256 kbps.")
    elif server == "youtube":
        want = C.YOUTUBE_RECOMMENDED.get(key)
        if want and video_kbps < want / 2:
            notes.append(
                "YouTube recommends about %d kbps at this size and you have "
                "%d, so it may call the stream low quality. It should still "
                "go out." % (want, video_kbps))
    return " ".join(notes)


def _host_of(url):
    """Just the host, for saying out loud. A URL with a key in it is not."""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.hostname or url
    except Exception:
        return url


def host_label(url):
    """The host, safe to say out loud and safe to put on the screen.

    The public name for `_host_of`. An RTMP address has the stream key in the
    path, so anything that shows a user where their stream is going has to go
    through this rather than printing the URL.
    """
    return _host_of(url)


def _resolve(host, port):
    """Look the server up before FFmpeg does, so a typo says it is a typo.

    This exists because of what FFmpeg gives back otherwise. Measured on
    7 September 2026 against a real RTMP client:

        a port nothing listens on   [Errno 138] Error number -138 occurred
        a host that does not exist  [Errno 5] I/O error
        an address off the network  [Errno 138] Error number -138 occurred

    "Error number -138 occurred" is not something to say to a presenter, and
    `Errno 5` is worse than useless because it is ALSO what the platform
    returns for a stream key it will not take. Two completely different
    problems, one meaningless message, and the fix for each is different.

    Resolving here separates them: a name that will not resolve is reported as
    a name that will not resolve, and after this an I/O error really is the
    server refusing us, which is nearly always the key.
    """
    try:
        socket.getaddrinfo(host, port or None, proto=socket.IPPROTO_TCP)
    except OSError:
        raise SinkError(
            "could not find %s. Check the server address" % host) from None


class _ffmpeg_log:
    """Collect FFmpeg's own log for the length of one call.

    FFmpeg knows exactly why a publish was refused and throws the answer away
    on the way out. `rtmpproto.c` logs `Server error: <description>` with the
    server's own AMF message, and then returns AVERROR_UNKNOWN, which is what
    surfaces as a meaningless "I/O error". So the log is the only place the
    real reason exists, and this is what reads it.
    """

    def __init__(self):
        self.records = []
        self._capture = None

    def __enter__(self):
        try:
            av.logging.set_level(av.logging.INFO)
            self._capture = av.logging.Capture(local=False)
            self.records = self._capture.__enter__()
        except Exception:
            self._capture = None
            self.records = []
        return self

    def __exit__(self, *exc):
        if self._capture is not None:
            try:
                self._capture.__exit__(*exc)
            except Exception:
                pass
        return False

    def text(self):
        try:
            # Joined THEN split: FFmpeg emits partial lines as separate
            # records, so anything parsed per record matches nothing.
            return "".join(message for _l, _n, message in self.records)
        except Exception:
            return ""


def _server_error(log):
    """What the far end actually said, if it said anything."""
    if log is None:
        return ""
    for line in log.text().splitlines():
        line = line.strip()
        marker = "Server error:"
        if marker in line:
            return line.split(marker, 1)[1].strip()
    return ""


def _explain_rtmp(exc, settings, server_said=""):
    """Turn FFmpeg's RTMP errors into something worth hearing."""
    text = str(exc)
    host = _host_of(settings.get("host", ""))
    lowered = text.lower()

    # The platform's own words beat any guess of ours, when there are any.
    if server_said:
        said = server_said.strip().rstrip(".")
        if "publish" in said.lower() and "bad" in said.lower():
            return ("%s would not take the stream key. Check it has been "
                    "copied in full and has not expired" % host)
        return "%s said: %s" % (host, said)
    if "timed out" in lowered or "timeout" in lowered:
        return "%s did not answer" % host
    if "-138" in text or "Errno 138" in text or "refused" in lowered:
        return ("could not reach %s. Check the address and the port, and that "
                "nothing is blocking it" % host)
    if "Errno 5" in text or "I/O error" in lowered or "Immediate exit" in text:
        # DNS was checked before this, so a refusal here is the far end saying
        # no, and the key is what it says no to.
        return ("%s would not take the stream key. Check it has been copied "
                "in full and has not expired" % host)
    if "Errno 13" in text or "denied" in lowered:
        return "%s refused the connection" % host
    # Anything unmatched still names the host and drops the errno, because a
    # number nobody can act on is not worth the words it takes to say.
    return "could not connect to %s" % host


#: Which destination a saved server uses. Anything not named here is an
#: Icecast family server, which keeps `SERVERS` the registry it always was and
#: means a test can still put its own sink in there.
DESTINATIONS = {
    "youtube": RtmpDestination,
    "facebook": RtmpDestination,
    "restream": RtmpDestination,
    "rtmp": RtmpDestination,
}

#: What the RTMP ones are called on screen. `SERVERS` cannot hold these: it
#: maps a name to a SINK CLASS, and an RTMP destination has no sink because
#: FFmpeg owns the socket.
RTMP_LABELS = {
    "youtube": "YouTube Live",
    "facebook": "Facebook Live",
    "restream": "Restream",
    "rtmp": "Custom RTMP server",
}


def server_label(key):
    """What one server is called, whichever kind it is.

    The Streaming tab needs a label for every entry in STREAM_SERVER_ORDER,
    and those now come from two registries. Asking here rather than indexing
    SERVERS directly is what stops a new destination raising KeyError in the
    Preferences box, which is exactly how this broke the first time.
    """
    if key in SERVERS:
        return SERVERS[key][0]
    return RTMP_LABELS.get(key, key)


def is_rtmp(key):
    """Whether this server wants a stream key and a picture."""
    return key in DESTINATIONS


def destination_for(settings, bus_samplerate, video_source=None):
    """The right destination for what the user picked."""
    kind = settings.get("server", "icecast")
    factory = DESTINATIONS.get(kind)
    if factory is None:
        return IcecastDestination(settings, bus_samplerate)
    return factory(settings, bus_samplerate, video_source=video_source)


# ---------------------------------------------------------------------------
# The thread that joins the ring to the socket
# ---------------------------------------------------------------------------

#: What a stream can be doing. The words are the ones spoken to the user, so
#: they are short and they say what is true rather than what is technical.
OFF = "off"
CONNECTING = "connecting"
ON_AIR = "on air"
RECONNECTING = "reconnecting"
FAILED = "failed"


class Streamer:
    """Runs the stream on a thread of its own, and keeps it up.

    **It is clocked by the sound card, not by a timer.** The loop takes
    whatever the audio callbacks have put in the ring and encodes that, so the
    stream runs at exactly the speed the audio is really being produced. A
    timer would be a second clock, slightly wrong, drifting against the first
    one all night.

    **It reconnects on its own.** A dropped connection on a live show is not
    something to hand back to the presenter mid sentence; it is something to
    fix quietly and mention. Attempts back off so a server that is down does
    not get hammered, and every change of state is spoken once.

    **It never lets the network touch the show.** Everything here is off the
    audio thread. The worst a dead server can do is fill the ring, and a full
    ring drops stream audio, not the sound coming out of the speakers.
    """

    def __init__(self, bus, settings, on_state=None, on_title=None,
                 on_trouble=None, video_source=None):
        self.bus = bus
        self.settings = dict(settings)
        #: What goes on the screen, for a destination that needs a picture.
        #: Built by the caller, because the card wants the station name and
        #: a camera wants a device, and neither is this class's business.
        self.video_source = video_source
        self.on_state = on_state or (lambda state, detail: None)
        self.state = OFF
        self.detail = ""
        self.error = ""

        self._thread = None
        self._stop = threading.Event()
        self._destination = None
        self._resampler = None
        self._lock = threading.Lock()
        self._title = ""
        self._sent_title = None

        #: Numbers worth telling the user about, all read without a lock
        #: because they are only ever written here and only ever read for
        #: display.
        #: Bytes from destinations that have already closed. The live one is
        #: added in the property below, because a counter that only updates
        #: when the stream ENDS reads as a dead stream for the whole show.
        self._bytes_closed = 0
        self.started_at = 0.0
        self.attempts = 0
        self.reconnects = 0

        #: Said once when the connection stops keeping up, because a stream
        #: that is quietly falling behind sounds fine at this end and skips at
        #: the other. Measured 4 September 2026: a link at half the needed
        #: speed drops nothing for half a minute and puts the listener half a
        #: minute late, and only then starts losing audio.
        self.on_trouble = on_trouble or (lambda message: None)
        #: How far behind the encoder is, in seconds of audio waiting.
        self.backlog = 0.0
        self._worried_at = 0.0
        self._said_dropping = False
        #: When the pump last got all the way round. A WATCHDOG reads this,
        #: because the pump cannot report on itself while it is stuck.
        #:
        #: PyAV installs FFmpeg's interrupt callback on INPUT containers only,
        #: so the timeout passed to av.open does nothing on the way out and
        #: mux() can block until Windows gives up on the socket, which is
        #: minutes, or for ever on a zero window. Wi-Fi going away without a
        #: clean disconnect is exactly that. Without this the app went on
        #: saying ON AIR with nothing leaving the machine, which is the worst
        #: thing it can do to somebody who cannot see a dashboard.
        self._beat = 0.0
        self._watchdog = None
        self._stalled = False

    # ------------------------------------------------------------- lifetime --
    def start(self):
        if self._thread is not None:
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dropdeck-stream",
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self, wait=True):
        """Come off air. Safe to call twice and safe to call from anywhere."""
        self._stop.set()
        thread = self._thread
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=C.STREAM_STOP_TIMEOUT)
        self._thread = None
        self._set_state(OFF, "")

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def bytes_sent(self):
        """How much has gone out, including the connection running now."""
        live = getattr(self._destination, "bytes_sent", 0) or 0
        return self._bytes_closed + live

    @property
    def on_air_for(self):
        """Seconds on air, or 0. What a presenter actually wants to know."""
        if self.state != ON_AIR or not self.started_at:
            return 0.0
        return time.monotonic() - self.started_at

    # ------------------------------------------------------------ pictures --
    def set_video_source(self, source):
        """Change what the stream is showing, on air or off.

        Held here as well as handed on, because a reconnect rebuilds the
        destination from scratch and would otherwise put the picture back to
        whatever it was when Ctrl+B was pressed. That is the same trap the
        settings dict already carries: it is a snapshot, and anything changed
        after going live has to be kept somewhere the rebuild will look.
        """
        self.video_source = source
        # What is playing goes to the new source at once, or a card would go
        # out blank until the next track change, which on a long album track
        # is a quarter of an hour of a stream saying nothing.
        with self._lock:
            title = self._title
        setter = getattr(source, "set_title", None)
        if setter is not None and title:
            try:
                setter(title)
            except Exception:
                pass
        destination = self._destination
        swap = getattr(destination, "set_video_source", None)
        if swap is None:
            return False
        try:
            swap(source)
        except Exception:
            return False
        return True

    # -------------------------------------------------------------- titles --
    def set_title(self, title):
        """What is playing. Sent to the server when it changes, not before.

        It also goes to the picture. On Icecast the server shows the title to
        listeners; on RTMP there is nowhere to send one, so the card IS where
        somebody watching finds out what is on. Same call, both covered.
        """
        with self._lock:
            self._title = title or ""
        setter = getattr(self.video_source, "set_title", None)
        if setter is not None:
            try:
                setter(title or "")
            except Exception:
                pass

    def _push_title(self):
        with self._lock:
            title = self._title
        if title == self._sent_title or self._destination is None:
            return
        # Marked as sent whether or not it worked. Retrying a title every pass
        # would be a request a second at the far end for as long as a server
        # is unhappy, and the next track will put it right anyway.
        self._sent_title = title
        try:
            self._destination.send_metadata(title)
        except Exception:
            pass

    # --------------------------------------------------------------- state --
    def _set_state(self, state, detail=""):
        if state == self.state and detail == self.detail:
            return
        self.state = state
        self.detail = detail
        try:
            self.on_state(state, detail)
        except Exception:
            pass

    # ---------------------------------------------------------------- work --
    def _build(self):
        """Make the destination. Raises with a sayable reason."""
        destination = destination_for(self.settings, self.bus.samplerate,
                                      video_source=self.video_source)
        destination.connect()
        self._destination = destination
        self._resampler = _Resampler(self.bus.samplerate,
                                     destination.samplerate)
        return destination

    # `_encoder` and `_sink` were attributes before destinations existed, and
    # the tests and the UI still read them. They are answers about the live
    # destination now rather than state of their own, so there is only one
    # place a connection is remembered.
    @property
    def _encoder(self):
        return getattr(self._destination, "encoder", None)

    @property
    def _sink(self):
        return getattr(self._destination, "sink", None)

    def _teardown(self):
        destination, self._destination = self._destination, None
        if destination is not None:
            try:
                destination.close()
            except Exception:
                pass
            self._bytes_closed += getattr(destination, "bytes_sent", 0) or 0
        self._sent_title = None

    def _run(self):
        delay = C.STREAM_RETRY_FIRST
        while not self._stop.is_set():
            self.attempts += 1
            first = self.attempts == 1
            self._set_state(CONNECTING if first else RECONNECTING,
                            self.error if not first else "")
            try:
                self._build()
            except (SinkError, EncoderError) as exc:
                self.error = str(exc)
                self._teardown()
                if first and not self._retryable():
                    self._set_state(FAILED, self.error)
                    return
                self._set_state(RECONNECTING, self.error)
                if self._stop.wait(delay):
                    break
                delay = min(delay * 2, C.STREAM_RETRY_MAX)
                continue
            except Exception as exc:                 # pragma: no cover
                self.error = "the stream could not start: %s" % exc
                self._teardown()
                self._set_state(FAILED, self.error)
                return

            delay = C.STREAM_RETRY_FIRST
            self.error = ""
            self.started_at = time.monotonic()
            self.bus.reset()
            self._set_state(ON_AIR, self._describe())
            self._start_watchdog()
            try:
                self._pump()
            except (SinkError, EncoderError) as exc:
                self.error = str(exc)
            except Exception as exc:                 # pragma: no cover
                self.error = "the stream stopped: %s" % exc
            self._drain()
            self._teardown()
            if self._stop.is_set():
                break
            self.reconnects += 1
            self._set_state(RECONNECTING, self.error)
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, C.STREAM_RETRY_MAX)
        self._teardown()
        self._set_state(OFF, "")

    def _retryable(self):
        """A wrong password is worth stopping for; a missing server is not.

        Retrying a bad password forever would sit there looking like it might
        still work, which is worse than being told once that it will not.

        **The RTMP wordings have to be in here too**, and leaving them out was
        a real fault: every message `_explain_rtmp` produces is RTMP worded and
        matched none of the Icecast ones, so a wrong or expired YouTube key
        retried for ever. The state never reached FAILED, so the app never came
        off air, the menu still said "Come off air", and because `_set_state`
        drops a repeat of the same state and detail the presenter heard the
        reason exactly ONCE and then nothing at all, all night.
        """
        bad = ("password",
               "no mount point by that name",
               # RTMP: the far end said no, and saying it again will not help.
               "stream key",
               "could not find",
               "there is no stream key",
               "there is no server address")
        return not any(word in self.error.lower() for word in bad)

    def _describe(self):
        if self._destination is not None:
            return self._destination.describe()
        return "%d k %s to %s" % (int(self.settings.get("bitrate", 128)),
                                  FORMATS.get(self.settings.get("format", "mp3"),
                                              FORMATS["mp3"])["label"],
                                  self.settings.get("host", ""))

    def _drain(self):
        """Send whatever is still in the ring before closing.

        Coming off air should not cost the last quarter second of the show.
        The ring holds up to one chunk that the pump had not reached yet, and
        the encoder holds a partial frame; both are worth the moment it takes
        to push them out.
        """
        try:
            left = self.bus.available()
            if left and self._destination is not None:
                block = self._resampler.feed(self.bus.read(left))
                if len(block):
                    self._destination.feed(block)
        except Exception:
            pass          # never let tidying up raise on the way out

    def _watch_backlog(self):
        """Notice when the link stops keeping up, and say so once.

        Two different failures, and a presenter needs to hear about both:
        audio waiting in the ring means the far end is slower than the show,
        and dropped blocks mean it has been slower for long enough that
        listeners have now missed something.
        """
        waiting = self.bus.available() / float(self.bus.samplerate)
        self.backlog = waiting
        now = time.monotonic()
        if waiting > C.STREAM_BEHIND_SECONDS:
            if not self._worried_at:
                self._worried_at = now
            elif now - self._worried_at > C.STREAM_BEHIND_FOR:
                self._worried_at = now + C.STREAM_BEHIND_AGAIN
                self.on_trouble(
                    "The connection is not keeping up. Listeners are %d "
                    "seconds behind. A lower bitrate would fix it"
                    % int(waiting))
        else:
            self._worried_at = 0.0
        if self.bus.dropped and not self._said_dropping:
            self._said_dropping = True
            self.on_trouble("The stream is losing audio. Listeners are "
                            "hearing gaps")

    def _start_watchdog(self):
        """Watch the pump from outside, because it cannot watch itself."""
        self._beat = time.monotonic()
        self._stalled = False
        if self._watchdog is not None and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(target=self._watch, daemon=True,
                                          name="dropdeck-stream-watchdog")
        self._watchdog.start()

    def _watch(self):
        while not self._stop.is_set():
            if self._stop.wait(C.STREAM_WATCHDOG_POLL):
                return
            if self.state != ON_AIR:
                continue
            since = time.monotonic() - (self._beat or time.monotonic())
            if since > C.STREAM_STALL_SECONDS and not self._stalled:
                self._stalled = True
                # Said, and then the connection is dropped so the ordinary
                # reconnect can rebuild it. Waiting for a socket that is
                # never going to answer is not a plan.
                self.on_trouble(
                    "The stream has stopped going out and the app is not "
                    "getting through. Trying to reconnect")
                self._set_state(RECONNECTING,
                                "the connection stopped responding")
                destination = self._destination
                if destination is not None:
                    # Closing under the blocked write is what unblocks it.
                    try:
                        destination.close()
                    except Exception:
                        pass

    def _pump(self):
        """Take what the sound card has made and send it, until told to stop."""
        seconds = getattr(self._destination, "chunk_seconds",
                          C.STREAM_CHUNK_SECONDS)
        chunk = max(256, int(self.bus.samplerate * seconds))
        idle = 0.0
        while not self._stop.is_set():
            if self.bus.available() < chunk:
                # Nothing ready. The sound card is the clock, so this waits on
                # it rather than running ahead on a timer of its own.
                if self._stop.wait(C.STREAM_POLL_SECONDS):
                    return
                idle += C.STREAM_POLL_SECONDS
                if idle > C.STREAM_SILENCE_TIMEOUT:
                    raise SinkError("the audio stopped arriving")
                continue
            idle = 0.0
            self._beat = time.monotonic()
            self._watch_backlog()
            block = self.bus.read(chunk)
            block = self._resampler.feed(block)
            if len(block):
                self._destination.feed(block)
            self._push_title()
            self._beat = time.monotonic()


class _Resampler:
    """Rate conversion, only when the format insists on a different one.

    Opus is a 48k codec. A sound card running at 44.1k has to be converted or
    everything goes out four per cent sharp, so this uses the resampler that
    came with the decoder rather than anything hand rolled, and does nothing
    at all when the rates already match.
    """

    def __init__(self, source_rate, target_rate):
        self.source_rate = int(source_rate)
        self.target_rate = int(target_rate)
        self.needed = self.source_rate != self.target_rate
        self._resampler = None
        self._pts = 0
        if self.needed and av is not None:
            self._resampler = av.audio.resampler.AudioResampler(
                format="fltp", layout="stereo", rate=self.target_rate)

    def feed(self, block):
        if not self.needed or self._resampler is None:
            return block
        frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(block.T.astype(np.float32)),
            format="fltp", layout="stereo")
        frame.rate = self.source_rate
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, self.source_rate)
        self._pts += len(block)
        out = []
        for resampled in self._resampler.resample(frame):
            out.append(resampled.to_ndarray().T.astype(np.float32))
        if not out:
            return np.zeros((0, CHANNELS), dtype=np.float32)
        return np.concatenate(out)
