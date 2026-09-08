"""An RTMP server that accepts one publish, so a test never needs the internet.

The same idea as `mock_icecast.py`, and for the same reason. A stream that
connects and sends silence looks exactly like a working one from the sending
end, so the test has to DECODE what arrived. This keeps every audio and video
message it is sent and rebuilds them into an FLV, which PyAV can then open and
check frame by frame.

It speaks enough RTMP for FFmpeg's client to publish to it, which is less than
it sounds:

    handshake        C0/C1 in, S0/S1/S2 out, C2 in. The simple version, not
                     the signed one. FFmpeg is happy with it.
    connect          answered with _result, plus the three control messages a
                     client expects before it.
    releaseStream    answered, or ignored, depending on the client.
    FCPublish        the same.
    createStream     answered with _result and a stream id.
    publish          answered with onStatus NetStream.Publish.Start, after
                     which the audio and video arrive.

What it does NOT do is play anything back, handle more than one publisher, or
implement the parts of RTMP that only matter for playback. It is a test double
and it says so.

**It has to run in another PROCESS, not another thread, and that is not a
style choice.** Measured 7 September 2026: PyAV holds the GIL for the whole of
`mux()`, and writing the first packet is what makes FFmpeg's RTMP client
connect. So a server on a Python thread in the same process never gets a turn
to call `accept()`, the client waits for a server that cannot run, and the two
of them sit there until the test times out with no error and no output. It
looks exactly like a protocol fault and it is not one.

`mock_icecast.MockServer` runs happily on a thread because the Icecast sink is
Python sockets, which release the GIL. Nothing about this is transferable.

Use `MockRTMP.spawn()`, which handles the subprocess:

    with MockRTMP.spawn() as server:
        publish_to(server.url)
    result = server.result()          # counts, commands, and the FLV bytes

Run it on its own to watch a real encoder connect:

    python tools/mock_rtmp.py
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

#: RTMP's default, and what every client assumes until told otherwise.
DEFAULT_CHUNK_SIZE = 128

#: What we tell the client to use. Bigger chunks mean less framing overhead
#: for the video messages, and every client handles Set Chunk Size.
SERVER_CHUNK_SIZE = 4096

HANDSHAKE_SIZE = 1536

# Message type ids, the ones that matter here.
SET_CHUNK_SIZE = 1
ACK = 3
USER_CONTROL = 4
WINDOW_ACK_SIZE = 5
SET_PEER_BANDWIDTH = 6
AUDIO = 8
VIDEO = 9
DATA_AMF0 = 18
COMMAND_AMF0 = 20


# ---------------------------------------------------------------------------
# AMF0, the parts an RTMP handshake actually uses
# ---------------------------------------------------------------------------

def amf0_string(value):
    raw = value.encode("utf-8")
    return b"\x02" + struct.pack(">H", len(raw)) + raw


def amf0_number(value):
    return b"\x00" + struct.pack(">d", float(value))


def amf0_bool(value):
    return b"\x01" + (b"\x01" if value else b"\x00")


def amf0_null():
    return b"\x05"


def amf0_object(pairs):
    out = b"\x03"
    for key, value in pairs.items():
        raw = key.encode("utf-8")
        out += struct.pack(">H", len(raw)) + raw + _amf0_value(value)
    return out + b"\x00\x00\x09"


def _amf0_value(value):
    if isinstance(value, bool):
        return amf0_bool(value)
    if isinstance(value, (int, float)):
        return amf0_number(value)
    if isinstance(value, str):
        return amf0_string(value)
    if isinstance(value, dict):
        return amf0_object(value)
    if value is None:
        return amf0_null()
    raise TypeError("no AMF0 encoding for %r" % type(value))


def amf0_decode(data, offset=0):
    """One AMF0 value, and where it ended. Enough types for the commands."""
    marker = data[offset]
    offset += 1
    if marker == 0x00:                                   # number
        return struct.unpack_from(">d", data, offset)[0], offset + 8
    if marker == 0x01:                                   # boolean
        return bool(data[offset]), offset + 1
    if marker == 0x02:                                   # string
        length = struct.unpack_from(">H", data, offset)[0]
        offset += 2
        return data[offset:offset + length].decode("utf-8", "replace"), offset + length
    if marker in (0x03, 0x08):                           # object, ecma array
        out = {}
        if marker == 0x08:
            offset += 4                                  # associative count
        while offset < len(data):
            length = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            if length == 0:
                # The object end marker is a zero length key then 0x09.
                if offset < len(data) and data[offset] == 0x09:
                    offset += 1
                break
            key = data[offset:offset + length].decode("utf-8", "replace")
            offset += length
            value, offset = amf0_decode(data, offset)
            out[key] = value
        return out, offset
    if marker == 0x05 or marker == 0x06:                 # null, undefined
        return None, offset
    # Anything else is not something a publish handshake sends. Stop cleanly
    # rather than guessing, because a wrong guess desynchronises the parser.
    raise ValueError("AMF0 marker 0x%02x is not handled" % marker)


# ---------------------------------------------------------------------------
# One connection
# ---------------------------------------------------------------------------

class _Message:
    """A message being reassembled out of chunks."""

    __slots__ = ("type_id", "length", "timestamp", "stream_id", "data")

    def __init__(self):
        self.type_id = 0
        self.length = 0
        self.timestamp = 0
        self.stream_id = 0
        self.data = b""


class _Connection:
    """Parses one publisher, and keeps what it sends."""

    def __init__(self, sock, server):
        self.sock = sock
        self.server = server
        self.in_chunk_size = DEFAULT_CHUNK_SIZE
        self._partial = {}          # chunk stream id -> _Message being built
        self._previous = {}         # chunk stream id -> last header, for type 1/2/3
        self._buf = b""

    # ------------------------------------------------------------ plumbing --
    def _recv(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("publisher went away")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send(self, data):
        self.sock.sendall(data)

    def _send_message(self, type_id, payload, chunk_stream=3, stream_id=0,
                      timestamp=0):
        """One message, chunked at the size we told the client we would use."""
        header = (bytes([chunk_stream])
                  + struct.pack(">I", timestamp)[1:]
                  + struct.pack(">I", len(payload))[1:]
                  + bytes([type_id])
                  + struct.pack("<I", stream_id))
        out = header + payload[:SERVER_CHUNK_SIZE]
        rest = payload[SERVER_CHUNK_SIZE:]
        while rest:
            out += bytes([0xC0 | chunk_stream]) + rest[:SERVER_CHUNK_SIZE]
            rest = rest[SERVER_CHUNK_SIZE:]
        self._send(out)

    # ----------------------------------------------------------- handshake --
    def handshake(self):
        c0 = self._recv(1)
        if c0[0] != 3:
            raise ValueError("RTMP version %d is not supported" % c0[0])
        c1 = self._recv(HANDSHAKE_SIZE)
        # S0, then S1 (our own time and zeroes), then S2 (an echo of C1).
        s1 = struct.pack(">II", int(time.time()), 0) + bytes(HANDSHAKE_SIZE - 8)
        self._send(b"\x03" + s1 + c1)
        self._recv(HANDSHAKE_SIZE)          # C2, which we do not need to check
        return True

    # --------------------------------------------------------------- chunks --
    def read_chunk(self):
        """Read one chunk, and return a finished message or None."""
        first = self._recv(1)[0]
        fmt = first >> 6
        cs_id = first & 0x3F
        if cs_id == 0:
            cs_id = 64 + self._recv(1)[0]
        elif cs_id == 1:
            low, high = self._recv(2)
            cs_id = 64 + low + (high << 8)

        previous = self._previous.get(cs_id)
        if fmt == 0:
            raw = self._recv(11)
            timestamp = int.from_bytes(raw[0:3], "big")
            length = int.from_bytes(raw[3:6], "big")
            type_id = raw[6]
            stream_id = struct.unpack("<I", raw[7:11])[0]
        elif fmt == 1:
            raw = self._recv(7)
            timestamp = int.from_bytes(raw[0:3], "big")
            length = int.from_bytes(raw[3:6], "big")
            type_id = raw[6]
            stream_id = previous["stream_id"] if previous else 0
        elif fmt == 2:
            raw = self._recv(3)
            timestamp = int.from_bytes(raw[0:3], "big")
            length = previous["length"] if previous else 0
            type_id = previous["type_id"] if previous else 0
            stream_id = previous["stream_id"] if previous else 0
        else:
            timestamp = previous["timestamp_delta"] if previous else 0
            length = previous["length"] if previous else 0
            type_id = previous["type_id"] if previous else 0
            stream_id = previous["stream_id"] if previous else 0

        # An extended timestamp is signalled by 0xFFFFFF in the field above,
        # and it is present on fmt 3 too when the previous header used one.
        extended = timestamp == 0xFFFFFF
        if extended:
            timestamp = struct.unpack(">I", self._recv(4))[0]

        self._previous[cs_id] = {"length": length, "type_id": type_id,
                                 "stream_id": stream_id,
                                 "timestamp_delta": timestamp}

        message = self._partial.get(cs_id)
        if message is None or not message.data:
            message = _Message()
            message.type_id = type_id
            message.length = length
            message.stream_id = stream_id
            if fmt == 0:
                message.timestamp = timestamp
            else:
                base = getattr(self._partial.get(cs_id), "timestamp", 0)
                message.timestamp = base + timestamp
            self._partial[cs_id] = message

        want = min(self.in_chunk_size, message.length - len(message.data))
        message.data += self._recv(want)
        if len(message.data) >= message.length:
            self._partial[cs_id] = _Message()
            self._partial[cs_id].timestamp = message.timestamp
            return message
        return None

    # -------------------------------------------------------------- serving --
    def serve(self):
        self.handshake()
        while True:
            message = self.read_chunk()
            if message is None:
                continue
            if not self._handle(message):
                return

    def _handle(self, message):
        if message.type_id == SET_CHUNK_SIZE:
            self.in_chunk_size = struct.unpack(">I", message.data[:4])[0]
            return True
        if message.type_id in (AUDIO, VIDEO, DATA_AMF0):
            self.server.on_media(message)
            return True
        if message.type_id == COMMAND_AMF0:
            return self._command(message)
        return True

    def _command(self, message):
        try:
            name, offset = amf0_decode(message.data, 0)
            txn, offset = amf0_decode(message.data, offset)
        except Exception:
            return True
        self.server.commands.append(name)

        if name == "connect":
            self._send_message(WINDOW_ACK_SIZE, struct.pack(">I", 2500000), 2)
            self._send_message(SET_PEER_BANDWIDTH,
                               struct.pack(">I", 2500000) + b"\x02", 2)
            self._send_message(SET_CHUNK_SIZE,
                               struct.pack(">I", SERVER_CHUNK_SIZE), 2)
            self._send_message(COMMAND_AMF0, (
                amf0_string("_result") + amf0_number(txn)
                + amf0_object({"fmsVer": "FMS/3,5,7,7009",
                               "capabilities": 31.0})
                + amf0_object({"level": "status",
                               "code": "NetConnection.Connect.Success",
                               "description": "Connection succeeded."})))
            return True

        if name == "createStream":
            self._send_message(COMMAND_AMF0, (
                amf0_string("_result") + amf0_number(txn)
                + amf0_null() + amf0_number(1)))
            return True

        if name == "publish":
            self.server.publishing = True
            self._send_message(COMMAND_AMF0, (
                amf0_string("onStatus") + amf0_number(0) + amf0_null()
                + amf0_object({"level": "status",
                               "code": "NetStream.Publish.Start",
                               "description": "Start publishing"})),
                chunk_stream=5, stream_id=1)
            return True

        if name in ("deleteStream", "FCUnpublish", "closeStream"):
            return False

        if name in ("releaseStream", "FCPublish"):
            # Some clients want a _result, some do not care. Answering is
            # harmless and skipping it hangs FFmpeg on some versions.
            self._send_message(COMMAND_AMF0, (
                amf0_string("_result") + amf0_number(txn)
                + amf0_null() + amf0_null()))
            return True
        return True


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------

class MockRTMP:
    """Accepts one publisher and rebuilds what it sent into an FLV.

    Use it as a context manager, exactly like `mock_icecast.MockServer`:

        with MockRTMP() as server:
            ...publish to server.url...
        container = av.open(io.BytesIO(server.flv()))
    """

    def __init__(self, host="127.0.0.1", port=0, app="live", key="test"):
        self.host = host
        self.app = app
        self.key = key
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]

        self._lock = threading.Lock()
        self._tags = []
        self.commands = []
        self.publishing = False
        self.error = ""
        self._thread = None
        self._stop = threading.Event()

    @property
    def url(self):
        return "rtmp://%s:%d/%s/%s" % (self.host, self.port, self.app, self.key)

    # ------------------------------------------------------------- lifetime --
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.stop()
        return False

    def start(self):
        self._thread = threading.Thread(target=self._accept, daemon=True,
                                        name="mock-rtmp")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=3)

    def _accept(self):
        try:
            conn, _addr = self._sock.accept()
        except Exception:
            return
        conn.settimeout(15)
        try:
            _Connection(conn, self).serve()
        except (ConnectionError, OSError, socket.timeout):
            pass                      # a publisher hanging up is the normal end
        except Exception as exc:      # a parser fault is worth reporting
            self.error = "%s: %s" % (type(exc).__name__, exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ---------------------------------------------------------------- media --
    def on_media(self, message):
        with self._lock:
            self._tags.append((message.type_id, message.timestamp, message.data))

    @property
    def tag_count(self):
        with self._lock:
            return len(self._tags)

    def counts(self):
        """How many audio and video tags arrived. The first thing a test asks."""
        with self._lock:
            audio = sum(1 for t, _ts, _d in self._tags if t == AUDIO)
            video = sum(1 for t, _ts, _d in self._tags if t == VIDEO)
            data = sum(1 for t, _ts, _d in self._tags if t == DATA_AMF0)
        return {"audio": audio, "video": video, "data": data}

    def timestamps(self, type_id):
        with self._lock:
            return [ts for t, ts, _d in self._tags if t == type_id]

    def flv(self):
        """Everything that arrived, as an FLV that PyAV can open.

        The RTMP messages ARE the FLV tag bodies, which is the whole reason
        FLV is the container RTMP carries. So this is a header, and then each
        message written back out with its tag framing restored.
        """
        with self._lock:
            tags = list(self._tags)
        has_audio = any(t == AUDIO for t, _ts, _d in tags)
        has_video = any(t == VIDEO for t, _ts, _d in tags)
        flags = (0x04 if has_audio else 0) | (0x01 if has_video else 0)
        out = [b"FLV" + bytes([1, flags]) + struct.pack(">I", 9)
               + struct.pack(">I", 0)]
        for type_id, timestamp, data in tags:
            out.append(bytes([type_id])
                       + struct.pack(">I", len(data))[1:]
                       + struct.pack(">I", timestamp & 0xFFFFFF)[1:]
                       + bytes([(timestamp >> 24) & 0xFF])
                       + b"\x00\x00\x00"
                       + data)
            out.append(struct.pack(">I", len(data) + 11))
        return b"".join(out)


# ---------------------------------------------------------------------------
# Running it in another process, which is the only way a test can use it
# ---------------------------------------------------------------------------

class Result:
    """What the server saw, brought back from the subprocess."""

    def __init__(self, payload, flv):
        self.commands = payload.get("commands", [])
        self.publishing = bool(payload.get("publishing"))
        self.counts = payload.get("counts", {})
        self.error = payload.get("error", "")
        self.audio_timestamps = payload.get("audio_timestamps", [])
        self.video_timestamps = payload.get("video_timestamps", [])
        self.flv = flv

    @property
    def audio(self):
        return self.counts.get("audio", 0)

    @property
    def video(self):
        return self.counts.get("video", 0)

    def container(self):
        """The FLV as PyAV sees it. Decoding is the check that counts."""
        import av                                   # local: tests import it
        return av.open(io.BytesIO(self.flv))


class _Spawned:
    """A `MockRTMP` running in its own interpreter."""

    def __init__(self, port, seconds):
        self.port = port
        self.seconds = seconds
        self._proc = None
        self._dir = None
        self._result = None

    @property
    def url(self):
        return "rtmp://127.0.0.1:%d/live/test" % self.port

    def __enter__(self):
        self._dir = tempfile.mkdtemp(prefix="mock-rtmp-")
        self._flv = os.path.join(self._dir, "capture.flv")
        self._json = os.path.join(self._dir, "summary.json")
        self._proc = subprocess.Popen(
            [sys.executable, "-u", os.path.abspath(__file__), "--serve",
             "--port", str(self.port), "--seconds", str(self.seconds),
             "--flv", self._flv, "--summary", self._json],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        line = self._proc.stdout.readline().strip()
        if line != "READY":
            raise RuntimeError("mock RTMP server did not start: %r" % line)
        return self

    def __exit__(self, *_exc):
        self.finish()
        return False

    def finish(self, timeout=20):
        """Wait for the server to write its capture, and read it back."""
        if self._proc is None or self._result is not None:
            return self._result
        try:
            self._proc.wait(timeout=timeout)
        except Exception:
            self._proc.kill()
            self._proc.wait(timeout=5)
        payload = {}
        flv = b""
        try:
            with open(self._json, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            pass
        try:
            with open(self._flv, "rb") as handle:
                flv = handle.read()
        except Exception:
            pass
        self._result = Result(payload, flv)
        shutil.rmtree(self._dir, ignore_errors=True)
        return self._result

    def result(self):
        return self.finish()


def _free_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def spawn(port=None, seconds=20):
    """A mock RTMP server in its own process. See the note at the top."""
    return _Spawned(port or _free_port(), seconds)


MockRTMP.spawn = staticmethod(spawn)


def _serve(port, seconds, flv_path, summary_path):   # pragma: no cover - child
    server = MockRTMP(port=port)
    server.start()
    print("READY", flush=True)
    deadline = time.time() + seconds
    # Finish early once a publisher has been and gone, so a test is not held
    # up by the whole timeout after the stream has closed.
    seen = False
    while time.time() < deadline:
        time.sleep(0.1)
        if server.publishing:
            seen = True
        if seen and not server._thread.is_alive():
            break
    with open(flv_path, "wb") as handle:
        handle.write(server.flv())
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump({"commands": server.commands,
                   "publishing": server.publishing,
                   "counts": server.counts(),
                   "error": server.error,
                   "audio_timestamps": server.timestamps(AUDIO),
                   "video_timestamps": server.timestamps(VIDEO)}, handle)
    server.stop()


def main():                                    # pragma: no cover - by hand
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true",
                        help="run as a child process and write a capture")
    parser.add_argument("--port", type=int, default=1935)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--flv", default="")
    parser.add_argument("--summary", default="")
    args = parser.parse_args()

    if args.serve:
        _serve(args.port, args.seconds, args.flv, args.summary)
        return

    with MockRTMP(port=args.port) as server:
        print("listening on", server.url)
        print("publish to it with:")
        print("  ffmpeg -re -f lavfi -i testsrc -f lavfi -i sine "
              "-c:v libx264 -c:a aac -f flv", server.url)
        try:
            while True:
                time.sleep(1)
                counts = server.counts()
                if counts["audio"] or counts["video"]:
                    print("\r audio %(audio)5d  video %(video)5d" % counts,
                          end="", flush=True)
        except KeyboardInterrupt:
            print("\nstopping. commands seen:", server.commands)


if __name__ == "__main__":                     # pragma: no cover
    main()
