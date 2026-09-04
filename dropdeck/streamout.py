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
    """

    def __init__(self, samplerate, seconds=None):
        self.samplerate = int(samplerate)
        self.frames = int(self.samplerate * (seconds or C.AIR_RING_SECONDS))
        self._lock = threading.Lock()
        self._rings = {}
        #: Blocks thrown away because the encoder could not keep up. The
        #: presenter is told, because silent dropouts are how a stream lies.
        self.dropped = 0

    def _ring_for(self, key):
        ring = self._rings.get(key)
        if ring is None:
            ring = {"buf": np.zeros((self.frames, CHANNELS), dtype=np.float32),
                    "write": 0, "filled": 0}
            self._rings[key] = ring
        return ring

    def write(self, key, block):
        """Called from an audio callback. Must not block and must not raise."""
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

    def available(self):
        """Frames the thinnest ring can supply. What can be read right now."""
        with self._lock:
            if not self._rings:
                return 0
            return min(r["filled"] for r in self._rings.values())

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
        """Flush what the codec is holding and finish the container."""
        if self._closed:
            return
        try:
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

    def __init__(self, bus, settings, on_state=None, on_title=None):
        self.bus = bus
        self.settings = dict(settings)
        self.on_state = on_state or (lambda state, detail: None)
        self.state = OFF
        self.detail = ""
        self.error = ""

        self._thread = None
        self._stop = threading.Event()
        self._sink = None
        self._encoder = None
        self._resampler = None
        self._lock = threading.Lock()
        self._title = ""
        self._sent_title = None

        #: Numbers worth telling the user about, all read without a lock
        #: because they are only ever written here and only ever read for
        #: display.
        self.bytes_sent = 0
        self.started_at = 0.0
        self.attempts = 0
        self.reconnects = 0

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
    def on_air_for(self):
        """Seconds on air, or 0. What a presenter actually wants to know."""
        if self.state != ON_AIR or not self.started_at:
            return 0.0
        return time.monotonic() - self.started_at

    # -------------------------------------------------------------- titles --
    def set_title(self, title):
        """What is playing. Sent to the server when it changes, not before."""
        with self._lock:
            self._title = title or ""

    def _push_title(self):
        with self._lock:
            title = self._title
        if title == self._sent_title or self._sink is None:
            return
        # Marked as sent whether or not it worked. Retrying a title every pass
        # would be a request a second at the far end for as long as a server
        # is unhappy, and the next track will put it right anyway.
        self._sent_title = title
        try:
            self._sink.send_metadata(title)
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
        """Make the socket and the encoder. Raises with a sayable reason."""
        kind = self.settings.get("server", "icecast")
        label, factory = SERVERS.get(kind, SERVERS["icecast"])
        fmt = self.settings.get("format", "mp3")
        spec = FORMATS.get(fmt) or FORMATS["mp3"]
        bitrate = int(self.settings.get("bitrate", 128))

        encoder = Encoder(self._on_bytes, fmt=fmt,
                          samplerate=self.bus.samplerate, bitrate=bitrate)
        sink = factory(
            host=self.settings.get("host", ""),
            port=int(self.settings.get("port", 8000)),
            mount=self.settings.get("mount", "/live"),
            user=self.settings.get("user", "source"),
            password=self.settings.get("password", ""),
            content_type=spec["content_type"],
            name=self.settings.get("name", ""),
            description=self.settings.get("description", ""),
            genre=self.settings.get("genre", ""),
            url=self.settings.get("url", ""),
            bitrate=bitrate,
            samplerate=encoder.samplerate,
            public=bool(self.settings.get("public", False)),
        )
        sink.connect()
        self._sink = sink
        self._encoder = encoder
        self._resampler = _Resampler(self.bus.samplerate, encoder.samplerate)
        return sink

    def _on_bytes(self, data):
        """Called by the encoder, on this thread. Straight out of the door."""
        sink = self._sink
        if sink is None:
            return
        sink.write(data)
        self.bytes_sent += len(data)

    def _teardown(self):
        encoder, self._encoder = self._encoder, None
        sink, self._sink = self._sink, None
        # The encoder is closed first so its last packets have somewhere to
        # go, and the sink is dropped first inside _on_bytes if it has gone.
        if encoder is not None:
            self._sink = sink
            try:
                encoder.close()
            except Exception:
                pass
            self._sink = None
        if sink is not None:
            try:
                sink.close()
            except Exception:
                pass
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
            try:
                self._pump()
            except (SinkError, EncoderError) as exc:
                self.error = str(exc)
            except Exception as exc:                 # pragma: no cover
                self.error = "the stream stopped: %s" % exc
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
        """
        bad = ("password", "no mount point by that name")
        return not any(word in self.error for word in bad)

    def _describe(self):
        return "%d k %s to %s" % (int(self.settings.get("bitrate", 128)),
                                  FORMATS.get(self.settings.get("format", "mp3"),
                                              FORMATS["mp3"])["label"],
                                  self.settings.get("host", ""))

    def _pump(self):
        """Take what the sound card has made and send it, until told to stop."""
        chunk = max(256, int(self.bus.samplerate * C.STREAM_CHUNK_SECONDS))
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
            block = self.bus.read(chunk)
            block = self._resampler.feed(block)
            if len(block):
                self._encoder.feed(block)
            self._push_title()


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
