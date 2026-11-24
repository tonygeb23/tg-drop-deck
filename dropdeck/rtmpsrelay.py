"""Going live over RTMPS with the server's certificate checked.

Mark, 24 November 2026: the live stream to an rtmps address never checked the
server's certificate. A local server holding a certificate made up on the
spot completed the handshake and was handed the whole stream, key and all, so
anybody able to answer for a.rtmps.youtube.com on the same network (one
redirected DNS lookup is enough) collected the stream key. Check my stream key
did check, so a key that had just passed gave false confidence.

Why FFmpeg is not simply told to check
--------------------------------------

FFmpeg's TLS checks when it is given `tls_verify`, and nothing in PyAV 17.1
can give it. `OutputContainer.start_encoding` opens the output with
`avio_open(pb, name, AVIO_FLAG_WRITE)`, which takes no options at all, and
`options=` on `av.open` goes to the encoders and to `avformat_write_header`,
both of them past the moment the connection is made. Measured: `tls_verify`
changes nothing. This build's FFmpeg also does TLS through Windows itself
(schannel, no OpenSSL in it), which cannot be pointed at a test authority
without putting one in the machine's certificate store, so it could not have
been proved either.

So Python makes the connection
------------------------------

    PyAV (FLV)  ->  FFmpegLink  ->  FFmpeg's own RTMP client
                ->  127.0.0.1, one port, one connection
                ->  Relay  ->  TLS, checked by Python  ->  the real server

`rtmpcheck.tls_context()` decides, the same function Check my stream key
uses, so the button and Ctrl+B cannot disagree about a server. **The TLS
handshake is finished before FFmpeg is allowed anywhere near the relay**, so a
certificate that does not check out means not one byte of RTMP leaves the
machine, and the key with it.

**FFmpeg still writes every byte of RTMP**, so the server receives what it
received before. One field cannot survive the detour: FFmpeg builds the
connect command's `tcUrl` from the address it was given, which is now the
loopback, so the relay reads the connect off the wire, puts back the tcUrl
FFmpeg would have written for the real server, and chunks it again at the
same size. Everything after that goes through untouched.
`tests/test_review_rtmps.py` compares what a server receives this way with
what FFmpeg sends it directly, command by command.

Why FFmpeg is driven through ctypes
-----------------------------------

PyAV calls `avio_open` with the GIL HELD, for the whole of the RTMP handshake
and publish. A relay on a Python thread can therefore never answer it.
Measured: the whole process froze, every thread, until it was killed (it is
the same fault that makes `tools/mock_rtmp.py` run in a process of its own).
ctypes lets go of the GIL around a foreign call, so FFmpeg's own `avio_open2`,
out of the very DLL PyAV loaded, called through ctypes, leaves the relay free
to run. PyAV writes its FLV into `FFmpegLink`, a Python file object, and the
link hands every byte straight to FFmpeg's RTMP client, exactly as the muxer
would have written it there itself.

**Plain rtmp goes through `FFmpegLink` as well, with no relay and no TLS.**
It has no certificate to check, but the GIL fault was its fault too: a
server that took the connection and never answered froze every thread in the
app, the window included, for as long as it liked. Through the link the GIL
is free, and FFmpeg's interrupt callback gives the attempt a deadline and
hears Stop.
"""
from __future__ import annotations

import ctypes
import errno
import glob
import os
import select
import socket
import ssl
import struct
import sys
import threading
import time

try:
    import av
    import av.error
except Exception:      # pragma: no cover - PyAV missing is a real state
    av = None

from . import constants as C
from . import rtmpcheck

#: Said, after "Could not go on air.", when the certificate does not check
#: out. One sentence, and it says the KEY is not the problem, because a
#: refusal next to a stream key otherwise reads as a wrong key. It contains
#: "certificate could not be checked", which `streamout.REFUSED` lists, so
#: it is said once and not retried: a server that cannot prove who it is
#: will not prove it on the next attempt either.
CERT_REFUSED = ("the server's certificate could not be checked, so nothing "
                "was sent and your stream key never left this machine")

#: C0 and C1, then C2: everything the client sends before its first chunk.
#: The relay passes these through as they are.
HANDSHAKE = 1 + 1536 + 1536

#: What every RTMP client assumes until it says otherwise.
DEFAULT_CHUNK = 128
SET_CHUNK_SIZE = 1
COMMAND_AMF0 = 20

#: How long one wait may last before the relay looks at its flags again. It
#: is the slowest a stop can be noticed, and it costs nothing while data
#: flows, because a select returns as soon as there is something to do.
SLICE = 0.2

#: How much the relay will hold for a server that is not keeping up before
#: it stops reading from FFmpeg. Small on purpose: a slow link has to reach
#: the encoder as back pressure, the way it did over a direct connection, or
#: the "not keeping up" warning would come late by however much is held here.
HOLD = 64 * 1024

#: Between starting a connection to one address and trying the next one in
#: parallel. FFmpeg's own TCP does the same (100 ms, `ff_connect_parallel`),
#: and without it a network whose IPv6 is broken waits out the whole timeout
#: on an address that will never answer before it tries the one that would.
NEXT_ADDRESS = 0.1

AVIO_FLAG_WRITE = 2
_WOULD_BLOCK = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EAGAIN,
                getattr(errno, "WSAEWOULDBLOCK", 10035)}


class RelayError(Exception):
    """Why the relay could not carry the stream, as a sentence to say."""

    def __init__(self, sentence, certificate=False):
        super().__init__(sentence)
        self.sentence = sentence
        #: True when the certificate itself was refused, which is the one
        #: failure that is never worth trying again.
        self.certificate = certificate


# ---------------------------------------------------------------- FFmpeg ---

class _AVIOContext(ctypes.Structure):
    """The head of FFmpeg's public AVIOContext, as far as `write_flag`.

    `avio_write` returns nothing. A failed write is written into `error` and
    every write after it is silently dropped, so this field is the only way
    to know the connection has gone. These fields have stood in this order
    since FFmpeg 4, and `FFmpegLink` checks them on every open rather than
    trusting that.
    """

    _fields_ = [("av_class", ctypes.c_void_p),
                ("buffer", ctypes.c_void_p),
                ("buffer_size", ctypes.c_int),
                ("buf_ptr", ctypes.c_void_p),
                ("buf_end", ctypes.c_void_p),
                ("opaque", ctypes.c_void_p),
                ("read_packet", ctypes.c_void_p),
                ("write_packet", ctypes.c_void_p),
                ("seek", ctypes.c_void_p),
                ("pos", ctypes.c_int64),
                ("eof_reached", ctypes.c_int),
                ("error", ctypes.c_int),
                ("write_flag", ctypes.c_int)]


#: The libavformat major versions whose AVIOContext starts as above.
KNOWN_AVFORMAT = range(58, 63)

_lib = None
_lib_lock = threading.Lock()


def _loaded_avformat():
    """Where the avformat DLL PyAV itself loaded is, asked of Windows.

    Asked rather than worked out, because the file name carries a hash and
    its folder differs between a source run (site-packages/av.libs) and the
    frozen build (_internal/av.libs). Whatever PyAV loaded is the one whose
    log callback and allocator everything else is using.
    """
    if sys.platform != "win32":
        return ""
    from ctypes import wintypes
    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.EnumProcessModules.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetModuleFileNameW.argtypes = [wintypes.HMODULE,
                                            wintypes.LPWSTR, wintypes.DWORD]
    process = kernel32.GetCurrentProcess()
    size = 1024
    while True:
        modules = (wintypes.HMODULE * size)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcessModules(process, modules,
                                        ctypes.sizeof(modules),
                                        ctypes.byref(needed)):
            return ""
        count = needed.value // ctypes.sizeof(wintypes.HMODULE)
        if count <= size:
            break
        size = count + 64
    name = ctypes.create_unicode_buffer(1024)
    for index in range(count):
        if kernel32.GetModuleFileNameW(modules[index], name, 1024):
            base = os.path.basename(name.value).lower()
            if base.startswith("avformat-") and base.endswith(".dll"):
                return name.value
    return ""


def _ffmpeg():
    """FFmpeg's avformat, bound once. Raises RuntimeError with a reason."""
    global _lib
    with _lib_lock:
        if _lib is not None:
            return _lib
        if av is None:
            raise RuntimeError("the encoder is missing")
        path = _loaded_avformat()
        if not path:
            near = glob.glob(os.path.join(
                os.path.dirname(os.path.dirname(av.__file__)), "av.libs",
                "avformat-*.dll"))
            path = near[0] if near else ""
        if not path:
            raise RuntimeError("FFmpeg's avformat library could not be found")
        lib = ctypes.CDLL(path)
        lib.avformat_version.restype = ctypes.c_uint
        major = lib.avformat_version() >> 16
        if major not in KNOWN_AVFORMAT:
            raise RuntimeError("libavformat %d is not one this was checked "
                               "against" % major)
        pointer = ctypes.POINTER(ctypes.c_void_p)
        lib.avio_open2.argtypes = [pointer, ctypes.c_char_p, ctypes.c_int,
                                   ctypes.c_void_p, ctypes.c_void_p]
        lib.avio_open2.restype = ctypes.c_int
        lib.avio_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                   ctypes.c_int]
        lib.avio_write.restype = None
        lib.avio_flush.argtypes = [ctypes.c_void_p]
        lib.avio_flush.restype = None
        lib.avio_closep.argtypes = [pointer]
        lib.avio_closep.restype = ctypes.c_int
        _lib = lib
        return lib


#: FFmpeg's AVIOInterruptCB: a function it calls whenever it is waiting on
#: the network (every 100 ms of a wait, and on every read and write), and
#: gives up with AVERROR_EXIT when it answers 1.
_INTERRUPT = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)


class _AVIOInterruptCB(ctypes.Structure):
    _fields_ = [("callback", _INTERRUPT), ("opaque", ctypes.c_void_p)]


class FFmpegLink:
    """What PyAV writes its FLV into, with FFmpeg's own RTMP client behind it.

    Plain rtmp uses it too, pointed at the server itself rather than at the
    relay, for the GIL: through PyAV's own `avio_open` a server that took the
    connection and never answered held the GIL for as long as it liked, and
    every thread in the app stopped with it, window and all.

    A file object as far as PyAV is concerned: `write` and nothing else, so
    it is not seekable, which is what the FLV muxer was told about the RTMP
    output before and why it writes the same bytes now. The connection is
    made on the FIRST write, which comes from inside `start_encoding` after
    the encoders have opened, the same moment `avio_open` used to make it.
    An encoder that will not start therefore still touches no RTMP.

    **FFmpeg is given an interrupt callback, which PyAV never gave it on the
    way out.** Until `established`, it ends the attempt at `timeout` and at a
    stop; after that only `abort` ends it, which is how a watchdog lets out a
    write stuck behind a dead connection. A stop while live must NOT
    interrupt: closing sends FCUnpublish, and that should reach the server.

    **No name with the key in it.** PyAV puts a container's name into its
    error messages, and the address this opens ends in the stream key.
    """

    name = "rtmp"

    def __init__(self, url, stop=None, timeout=None):
        self._url = url
        self._ctx = ctypes.c_void_p()
        self._head = None
        self._lock = threading.Lock()
        self._opened = False
        self._closed = False
        self.stop = stop
        self.timeout = float(timeout if timeout is not None
                             else C.STREAM_TIMEOUT)
        self._deadline = 0.0
        self._established = False
        self._aborted = False
        #: Why FFmpeg was interrupted, so the caller can say it in the right
        #: words: FFmpeg itself only ever reports "Immediate exit requested",
        #: which the RTMP explainer would read as a refused key.
        self.timed_out = False
        self.stopped = False
        # Held for as long as FFmpeg holds the pointer to them.
        self._callback = _INTERRUPT(self._interrupted)
        self._interrupt = _AVIOInterruptCB(self._callback, None)
        #: True while a write is inside FFmpeg. Read by `close` from another
        #: thread, so a watchdog can tell that a write is stuck in there.
        self.busy = False
        self.bytes_written = 0

    def _interrupted(self, _opaque):
        try:
            if self._aborted:
                return 1
            if self._established:
                return 0
            if self.stop is not None and self.stop.is_set():
                self.stopped = True
                return 1
            if self._deadline and time.monotonic() > self._deadline:
                self.timed_out = True
                return 1
        except Exception:
            pass
        return 0

    def established(self):
        """The publish was answered: from here only `abort` interrupts."""
        self._established = True

    def abort(self):
        """Interrupt FFmpeg wherever it is waiting, for good."""
        self._aborted = True

    def _failed(self, code):
        """Raise for an FFmpeg error, in words that say what really happened."""
        if self.timed_out:
            raise TimeoutError("timed out")
        if self.stopped:
            raise OSError(errno.ECANCELED, "stopped")
        av.error.err_check(code)            # what PyAV itself would raise

    def _open(self):
        lib = _ffmpeg()
        self._deadline = time.monotonic() + self.timeout
        # The GIL is let go for this call, which is the whole point.
        code = lib.avio_open2(ctypes.byref(self._ctx),
                              self._url.encode("utf-8"), AVIO_FLAG_WRITE,
                              ctypes.byref(self._interrupt), None)
        if code < 0:
            self._ctx = ctypes.c_void_p()
            self._failed(code)
        head = _AVIOContext.from_address(self._ctx.value)
        if head.write_flag != 1 or head.buffer_size <= 0 or head.error:
            lib.avio_closep(ctypes.byref(self._ctx))
            raise RuntimeError("FFmpeg's connection is not laid out the way "
                               "this copy expects")
        self._head = head

    def write(self, data):
        with self._lock:
            if self._closed:
                raise OSError(errno.EPIPE, "the connection has been closed")
            self.busy = True
            try:
                if not self._opened:
                    self._opened = True
                    self._open()
                if self._head is None:
                    raise OSError(errno.ENOTCONN, "the connection never opened")
                lib = _ffmpeg()
                lib.avio_write(self._ctx, bytes(data), len(data))
                lib.avio_flush(self._ctx)
                if self._head.error < 0:
                    self._failed(self._head.error)
            finally:
                self.busy = False
        self.bytes_written += len(data)
        return len(data)

    def close(self):
        """Close FFmpeg's side, which sends FCUnpublish and deleteStream.

        Under the same lock as `write`, so it can never free the connection
        out from under a write in progress on the streaming thread.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._ctx:
                try:
                    _ffmpeg().avio_closep(ctypes.byref(self._ctx))
                except Exception:
                    pass
            self._head = None


# ------------------------------------------------------------ the address --

def split_address(url):
    """An rtmps URL as the pieces the relay needs, the way FFmpeg reads it.

    (host to connect to, port, the tcUrl prefix FFmpeg would write for it,
    and the loopback URL with the port left as %d). The authority ends at
    the first of "/?#", exactly where `av_url_split` ends it, and everything
    after it is handed to FFmpeg as it stands, so the app and the key are
    read from the very same characters either way.
    """
    scheme, sep, rest = url.partition("://")
    if not sep or scheme.lower() != "rtmps":
        raise RelayError("that server address is not an RTMPS one")
    end = len(rest)
    for mark in "/?#":
        at = rest.find(mark)
        if at != -1:
            end = min(end, at)
    authority, tail = rest[:end], rest[end:]
    userinfo = ""
    if "@" in authority:
        userinfo, authority = authority.rsplit("@", 1)
    port_text = ""
    if authority.startswith("[") and "]" in authority:
        host = authority[1:authority.index("]")]
        after = authority[authority.index("]") + 1:]
        if after.startswith(":"):
            port_text = after[1:]
    elif ":" in authority:
        host, port_text = authority.rsplit(":", 1)
    else:
        host = authority
    if not host:
        raise RelayError("there is no server name in that address")
    try:
        port = int(port_text) if port_text else 443
    except ValueError:
        raise RelayError("the port in that server address is not a number") \
            from None
    if not 0 < port < 65536:
        raise RelayError("the port in that server address is not a real one")
    # FFmpeg's ff_url_join: the host as it was written, in brackets only if
    # it is a numeric IPv6 address, and the port ALWAYS, the default too.
    # Measured: rtmp://127.0.0.1/live2 goes out as tcUrl
    # rtmp://127.0.0.1:1935/live2.
    shown = "[%s]" % host if ":" in host else host
    real_prefix = "rtmps://%s:%d" % (shown, port)
    # FFmpeg reads a user name and password for its own login schemes, so
    # they go to FFmpeg as they were; the tcUrl never carries them.
    local = "rtmp://%s127.0.0.1:%%d%s" % (
        (userinfo + "@").replace("%", "%%") if userinfo else "",
        tail.replace("%", "%%"))
    return host, port, real_prefix, local


# ----------------------------------------------------- the connect command --

class _Walk:
    """Steps over AMF0 without decoding it, so a value can be replaced in
    place and every other byte stays exactly as FFmpeg wrote it."""

    def __init__(self, data):
        self.data = data
        self.at = 0

    def take(self, n):
        if self.at + n > len(self.data):
            raise ValueError("short")
        out = self.data[self.at:self.at + n]
        self.at += n
        return out

    def u16(self):
        return struct.unpack(">H", self.take(2))[0]

    def u32(self):
        return struct.unpack(">I", self.take(4))[0]

    def skip(self, depth=0):
        if depth > 32:
            raise ValueError("too deep")
        marker = self.take(1)[0]
        if marker == 0x00:
            self.take(8)
        elif marker == 0x01:
            self.take(1)
        elif marker == 0x02:
            self.take(self.u16())
        elif marker == 0x03:
            self.properties(depth)
        elif marker in (0x05, 0x06):
            pass
        elif marker == 0x08:
            self.take(4)
            self.properties(depth)
        elif marker == 0x0A:
            for _ in range(self.u32()):
                self.skip(depth + 1)
        elif marker == 0x0B:
            self.take(10)
        elif marker == 0x0C:
            self.take(self.u32())
        else:
            raise ValueError("amf type %d" % marker)

    def properties(self, depth, visit=None):
        while True:
            name = self.take(self.u16())
            if not name and self.data[self.at:self.at + 1] == b"\x09":
                self.at += 1
                return
            if visit is not None and visit(name):
                continue
            self.skip(depth + 1)


def rewrite_tcurl(payload, local_prefix, real_prefix):
    """(the connect with its tcUrl put back, old tcUrl, new tcUrl), or None
    when the command is not a connect at all.

    Only the tcUrl string changes. Raises ValueError for a connect whose
    tcUrl is missing, doubled, not a string, or not the loopback address the
    relay gave FFmpeg, because sending a connect the relay could not account
    for is not something to do with somebody's stream key in the next message.
    """
    walk = _Walk(bytes(payload))
    if walk.take(1) != b"\x02" or walk.take(walk.u16()) != b"connect":
        return None
    if walk.take(1) != b"\x00":
        raise ValueError("connect has no transaction number")
    walk.take(8)
    if walk.take(1) != b"\x03":
        raise ValueError("connect has no command object")
    found = []

    def visit(name):
        if name != b"tcUrl":
            return False
        start = walk.at
        if walk.take(1) != b"\x02":
            raise ValueError("tcUrl is not a string")
        value = walk.take(walk.u16()).decode("utf-8")
        found.append((start, walk.at, value))
        return True

    walk.properties(0, visit)
    if len(found) != 1:
        raise ValueError("connect carries %d tcUrls" % len(found))
    start, end, value = found[0]
    if not value.startswith(local_prefix):
        raise ValueError("connect carries an unexpected tcUrl")
    real = real_prefix + value[len(local_prefix):]
    new = real.encode("utf-8")
    if len(new) > 0xFFFF:
        raise ValueError("tcUrl too long")
    return (bytes(payload[:start]) + b"\x02" + struct.pack(">H", len(new))
            + new + bytes(payload[end:]), value, real)


class ConnectRewrite:
    """FFmpeg's side of the conversation, with the tcUrl put back in it.

    Reads chunks only as far as it must. The handshake goes through as it
    is; chunks are reassembled, honouring any Set Chunk Size FFmpeg sends,
    until the connect command is complete; that one is rewritten and chunked
    again at the size in force; and after ONE more header everything is
    passed through untouched for the rest of the session.

    **That one more header is the subtle part.** FFmpeg compresses a chunk
    header against the last message on the same chunk stream: a message the
    same length and type as the one before it gets a four or one byte header
    that leaves the length out (`ff_rtmp_packet_write`). The connect is now a
    different length at the server than FFmpeg thinks it is, so the first
    message after it on that chunk stream is given the header FFmpeg WOULD
    have chosen against the real length, by FFmpeg's own rule. With a key of
    the wrong length the server would otherwise read releaseStream at the
    connect's length and lose its place in the stream for good.
    """

    def __init__(self, local_prefix, real_prefix):
        self.local_prefix = local_prefix
        self.real_prefix = real_prefix
        self.done = False
        self.fault = ""
        self.old_tcurl = ""
        self.new_tcurl = ""
        self._buf = bytearray()
        self._skip = HANDSHAKE
        self._chunk = DEFAULT_CHUNK
        self._last = {}
        self._held = {}
        self._raw = {}
        self._after = None

    def feed(self, data):
        """Bytes from FFmpeg in, the bytes the server should get out."""
        if self.done:
            return bytes(data)
        self._buf += data
        out = bytearray()
        if self._skip:
            take = min(self._skip, len(self._buf))
            out += self._buf[:take]
            del self._buf[:take]
            self._skip -= take
            if self._skip:
                return bytes(out)
        try:
            while not self.done:
                piece = self._chunk_out()
                if piece is None:
                    break
                out += piece
        except (ValueError, struct.error, IndexError, UnicodeDecodeError) \
                as exc:
            self.fault = str(exc) or "unreadable"
            self.done = True
            return b""
        if self.done:
            out += self._buf
            self._buf.clear()
        return bytes(out)

    def _chunk_out(self):
        """One whole chunk off the front, as what to send on. None if short."""
        b = self._buf
        if not b:
            return None
        fmt, cs, at = b[0] >> 6, b[0] & 0x3F, 1
        if cs == 0:
            if len(b) < 2:
                return None
            cs, at = 64 + b[1], 2
        elif cs == 1:
            if len(b) < 3:
                return None
            cs, at = 64 + b[1] + (b[2] << 8), 3
        size = (11, 7, 3, 0)[fmt]
        if len(b) < at + size:
            return None
        last = self._last.get(cs)
        if last is None and fmt != 0:
            raise ValueError("a chunk stream began without a full header")
        if fmt == 0:
            ts = int.from_bytes(b[at:at + 3], "big")
            length = int.from_bytes(b[at + 3:at + 6], "big")
            kind = b[at + 6]
            stream = struct.unpack("<I", bytes(b[at + 7:at + 11]))[0]
        elif fmt == 1:
            ts = int.from_bytes(b[at:at + 3], "big")
            length = int.from_bytes(b[at + 3:at + 6], "big")
            kind, stream = b[at + 6], last["stream"]
        elif fmt == 2:
            ts = int.from_bytes(b[at:at + 3], "big")
            length, kind, stream = last["length"], last["type"], last["stream"]
        else:
            ts = last["ts"]
            length, kind, stream = last["length"], last["type"], last["stream"]
        extended = ts == 0xFFFFFF if fmt != 3 else last["extended"]
        head = at + size + (4 if extended else 0)
        starting = cs not in self._held
        have = len(self._held.get(cs, b""))
        want = min(self._chunk, length - have)
        if len(b) < head + want:
            return None
        header, payload = bytes(b[:head]), bytes(b[head:head + want])
        del b[:head + want]
        # What FFmpeg's own headers mean, always: the implicit fields of a
        # compressed header are relative to what FFmpeg sent, not to the
        # rewritten connect, so this keeps FFmpeg's lengths.
        if fmt != 3:
            self._last[cs] = {"length": length, "type": kind,
                              "stream": stream, "ts": ts,
                              "extended": extended}
        out = header + payload

        if starting and self._after is not None and cs == self._after["cs"]:
            if fmt != 0:
                out = self._refit(header[:at], ts, length, kind,
                                  header[at + size:]) + payload
            self._after = None
            self.done = True
            return out

        held = self._held.get(cs, bytearray()) + payload
        if kind == COMMAND_AMF0 and not self.new_tcurl:
            # Held back until the whole command is in, because the connect
            # cannot be rewritten a chunk at a time: its length is in the
            # first header.
            self._raw[cs] = self._raw.get(cs, b"") + out
            out = b""
        if len(held) < length:
            self._held[cs] = held
            return out
        self._held.pop(cs, None)
        if kind == SET_CHUNK_SIZE and len(held) >= 4:
            # Ignoring this is how a reader silently loses its place.
            self._chunk = max(1, struct.unpack(">I", bytes(held[:4]))[0]
                              & 0x7FFFFFFF)
        if cs in self._raw:
            original = self._raw.pop(cs)
            return out + self._connect(cs, original, bytes(held), ts)
        return out

    def _connect(self, cs, original, payload, ts):
        """The first command, rewritten if it is the connect."""
        answer = rewrite_tcurl(payload, self.local_prefix, self.real_prefix)
        if answer is None:
            return original
        rewritten, self.old_tcurl, self.new_tcurl = answer
        if cs >= 64 or ts == 0xFFFFFF or original[0] >> 6 != 0:
            # FFmpeg sends its connect on chunk stream 3, at time 0, with a
            # full header. Anything else is not FFmpeg and is not guessed at.
            raise ValueError("connect is not framed the way FFmpeg frames it")
        header = bytearray(original[:12])
        header[4:7] = len(rewritten).to_bytes(3, "big")
        out = bytearray(header) + rewritten[:self._chunk]
        at = self._chunk
        while at < len(rewritten):
            out += bytes([0xC0 | cs]) + rewritten[at:at + self._chunk]
            at += self._chunk
        self._after = {"cs": cs, "real": len(rewritten),
                       "type": COMMAND_AMF0, "ts": ts}
        return bytes(out)

    def _refit(self, basic, ts, length, kind, extended):
        """The header FFmpeg would have written against the real connect.

        FFmpeg's rule, from `ff_rtmp_packet_write`: on a chunk stream it has
        used, with the same message stream and a timestamp no earlier, it
        sends the timestamp as a delta; and the same type AND the same length
        as the last message leaves the length out (four bytes), and the same
        delta as well leaves everything out (one byte). Anything else is the
        eight byte header. Only the length comparison changes here, against
        the connect the SERVER saw.
        """
        after = self._after
        if kind == after["type"] and length == after["real"]:
            mode = 3 if ts == after["ts"] else 2
        else:
            mode = 1
        first = bytes([(mode << 6) | (basic[0] & 0x3F)]) + basic[1:]
        if mode == 3:
            fields = b""
        elif mode == 2:
            fields = ts.to_bytes(3, "big")
        else:
            fields = (ts.to_bytes(3, "big") + length.to_bytes(3, "big")
                      + bytes([kind]))
        return first + fields + extended


# --------------------------------------------------------------- the relay --

class Relay:
    """One connection: the checked TLS one out, the loopback one in.

    Lives on a thread of its own, `dropdeck-rtmps-relay`, and never on the
    audio thread. The streaming thread waits for it in `wait_ready`, which
    gives up on a stop at once, so a slow handshake cannot hold Stop up.
    **Every wait has a deadline.** Until the session is established (the
    destination says so once FFmpeg's publish has been answered) the whole
    conversation must finish inside `timeout`, because a socket timeout bounds
    one read and not a conversation. After that the server may legitimately
    say nothing for minutes, so what is bounded is a write that cannot get
    out, by `C.STREAM_STALL_SECONDS`, the app's own definition of stuck.
    """

    def __init__(self, url, stop=None, timeout=None):
        self.host, self.port, self.real_prefix, self._local = \
            split_address(url)
        self.timeout = float(timeout if timeout is not None
                             else C.STREAM_TIMEOUT)
        self.stop = stop
        #: Why it ended, when it ended badly. A sentence.
        self.fault = ""
        self.certificate_refused = False
        #: The certificate's own complaint, for a test or a support question.
        #: Never spoken: "unable to get local issuer certificate" is not
        #: something a presenter can act on.
        self.detail = ""
        self.local_port = 0
        self.rewrite = None
        self.peer = None
        self.handshake_done = False
        self._ready = threading.Event()
        self._established = False
        self._closing = False
        self._deadline = 0.0
        self._raw = None
        self._listener = None
        self._local_sock = None
        self._tls = None
        self._in = self._out = None
        self._thread = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------- the outside
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dropdeck-rtmps-relay")
        self._thread.start()
        return self

    def wait_ready(self):
        """Block until FFmpeg may connect. Raises RelayError with a reason.

        Waits in slices so a stop is noticed straight away, and gives up a
        moment after the relay's own deadline in case its thread died.
        """
        limit = time.monotonic() + self.timeout + 2 * SLICE
        while not self._ready.wait(SLICE / 4):
            if self.stop is not None and self.stop.is_set():
                self.close()
                raise RelayError("stopped")
            if time.monotonic() > limit:
                self.close()
                raise RelayError("%s did not answer" % self.host)
        if self.fault:
            self.close()
            raise RelayError(self.fault, self.certificate_refused)
        return self.local_port

    @property
    def local_url(self):
        """Where FFmpeg is pointed: the loopback, then the real path and key."""
        return self._local % self.local_port

    @property
    def local_prefix(self):
        return "rtmp://127.0.0.1:%d" % self.local_port

    def established(self):
        """The publish was answered. From here a quiet server is not a fault."""
        self._established = True

    def abort(self):
        """Drop both connections now, which unblocks a stuck FFmpeg write."""
        self._closing = True
        for sock in (self._local_sock, self._raw, self._listener):
            _hard_close(sock)

    def close(self, wait=C.STREAM_STOP_TIMEOUT / 2):
        """Finish, and do not leave a thread or a socket behind.

        **Once FFmpeg has its connection, it is let finish first.** Closing
        FFmpeg's side sends FCUnpublish and deleteStream and then a TLS
        goodbye has to follow them out, so a relay told to stop the moment
        FFmpeg let go would drop the last thing a server hears. Before that
        there is nothing in flight and it stops at once.
        """
        thread = self._thread
        here = thread is threading.current_thread()
        if thread is not None and not here and self._local_sock is not None:
            thread.join(wait)
        self._closing = True
        if thread is not None and not here:
            thread.join(wait)
            if thread.is_alive():
                self.abort()
                thread.join(wait)
        self._shut()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------ the inside
    def _run(self):
        try:
            self._deadline = time.monotonic() + self.timeout
            self._secure()
            self._listen()
        except RelayError as exc:
            self.fault = exc.sentence
            self.certificate_refused = exc.certificate
            self._ready.set()
            self._shut()
            return
        except Exception as exc:                  # pragma: no cover
            self.fault = "the secure connection to %s failed" % self.host
            self.detail = repr(exc)
            self._ready.set()
            self._shut()
            return
        # A fresh allowance for FFmpeg's own handshake and publish, which
        # only starts once the streaming thread has been told it may.
        self._deadline = time.monotonic() + self.timeout
        self._ready.set()
        try:
            self._accept()
            self._pump()
        except RelayError as exc:
            self.fault = self.fault or exc.sentence
        except Exception as exc:
            self.fault = self.fault or ("the connection to %s dropped"
                                        % self.host)
            self.detail = self.detail or repr(exc)
        finally:
            self._shut()

    def _stopping(self):
        if self._closing:
            return True
        if not self._established:
            if self.stop is not None and self.stop.is_set():
                return True
            if time.monotonic() > self._deadline:
                raise RelayError("%s did not answer" % self.host)
        return False

    def _left(self):
        return max(0.0, self._deadline - time.monotonic())

    def _connect_tcp(self):
        """A TCP connection to the server, trying addresses in parallel."""
        try:
            found = socket.getaddrinfo(self.host, self.port,
                                       type=socket.SOCK_STREAM)
        except OSError:
            raise RelayError("could not find %s. Check the server address"
                             % self.host) from None
        # Alternate the families, as FFmpeg and every browser do.
        six = [a for a in found if a[0] == socket.AF_INET6]
        four = [a for a in found if a[0] != socket.AF_INET6]
        order = []
        while six or four:
            for group in (six, four) if found[0][0] == socket.AF_INET6 \
                    else (four, six):
                if group:
                    order.append(group.pop(0))
        trying = []
        next_at = 0.0
        refused = False
        try:
            while True:
                if self._stopping():
                    raise RelayError("stopped")
                now = time.monotonic()
                if order and (not trying or now >= next_at):
                    family, kind, proto, _name, address = order.pop(0)
                    sock = socket.socket(family, kind, proto)
                    sock.setblocking(False)
                    code = sock.connect_ex(address)
                    if code == 0:
                        trying.append(sock)
                        winner = sock
                        break
                    if code in _WOULD_BLOCK:
                        trying.append(sock)
                    else:
                        refused = True
                        sock.close()
                    next_at = now + NEXT_ADDRESS
                    continue
                if not trying and not order:
                    raise RelayError(
                        "could not reach %s. Check the address and the port, "
                        "and that nothing is blocking it" % self.host
                        if refused else "%s did not answer" % self.host)
                wait = min(SLICE, self._left())
                if order:
                    wait = min(wait, max(0.0, next_at - now))
                _r, done, failed = select.select([], trying, trying, wait)
                winner = None
                for sock in set(done) | set(failed):
                    code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if code == 0 and sock in done:
                        winner = sock
                        break
                    refused = True
                    trying.remove(sock)
                    sock.close()
                    next_at = 0.0
                if winner is not None:
                    break
        except BaseException:
            for sock in trying:
                sock.close()
            raise
        for sock in trying:
            if sock is not winner:
                sock.close()
        return winner

    def _secure(self):
        """TCP, then TLS, then the certificate. Nothing else is sent."""
        self._raw = self._connect_tcp()
        context = rtmpcheck.tls_context()
        self._in, self._out = ssl.MemoryBIO(), ssl.MemoryBIO()
        self._tls = context.wrap_bio(self._in, self._out,
                                     server_hostname=self.host)
        while True:
            try:
                self._tls.do_handshake()
                break
            except ssl.SSLWantReadError:
                pass
            except ssl.SSLCertVerificationError as exc:
                self.detail = exc.verify_message or str(exc)
                try:
                    self._send_now(self._out.read())     # the alert, politely
                except RelayError:
                    pass
                raise RelayError(CERT_REFUSED, certificate=True) from None
            except ssl.SSLError as exc:
                self.detail = str(exc)
                raise RelayError("the secure connection to %s failed"
                                 % self.host) from None
            self._send_now(self._out.read())
            data = self._recv_now()
            if data:
                self._in.write(data)
            else:
                self._in.write_eof()
        self._send_now(self._out.read())
        self.handshake_done = True

    def _send_now(self, data):
        """All of it, before the deadline. Only used before the pump starts."""
        view = memoryview(data)
        while view:
            if self._stopping():
                raise RelayError("stopped")
            _r, ready, _x = select.select([], [self._raw], [],
                                          min(SLICE, self._left()))
            if not ready:
                continue
            try:
                sent = self._raw.send(view)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                raise RelayError("the connection to %s dropped"
                                 % self.host) from None
            view = view[sent:]

    def _recv_now(self):
        while True:
            if self._stopping():
                raise RelayError("stopped")
            ready, _w, _x = select.select([self._raw], [], [],
                                          min(SLICE, self._left()))
            if not ready:
                continue
            try:
                return self._raw.recv(65536)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                raise RelayError("the connection to %s dropped"
                                 % self.host) from None

    def _listen(self):
        """The loopback only, a port of Windows' choosing, one at a time."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.setblocking(False)
        except OSError:
            listener.close()
            raise RelayError("the secure connection could not be set up on "
                             "this machine") from None
        self._listener = listener
        self.local_port = listener.getsockname()[1]
        self.rewrite = ConnectRewrite(self.local_prefix, self.real_prefix)

    def _accept(self):
        """One connection, and the listener is closed straight after it."""
        while True:
            if self._stopping():
                raise RelayError("stopped")
            ready, _w, _x = select.select([self._listener], [], [],
                                          min(SLICE, self._left()))
            if not ready:
                continue
            try:
                sock, self.peer = self._listener.accept()
            except (BlockingIOError, InterruptedError):
                continue
            break
        listener, self._listener = self._listener, None
        listener.close()
        sock.setblocking(False)
        self._local_sock = sock

    def _pump(self):
        """Both ways until either end has finished. One thread, no blocking."""
        local, raw, tls = self._local_sock, self._raw, self._tls
        to_server, to_local = bytearray(), bytearray()
        local_done = server_done = False
        stuck_since = 0.0
        while True:
            if self._stopping():
                return
            if local_done and not to_server:
                return
            if server_done and not to_local:
                # The server has finished, so FFmpeg reads the end of the
                # stream, exactly as it would have read it from the server.
                try:
                    local.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                return
            reading, writing = [], []
            if not local_done and len(to_server) < HOLD:
                reading.append(local)
            if not server_done and len(to_local) < HOLD:
                reading.append(raw)
            if to_server:
                writing.append(raw)
            if to_local:
                writing.append(local)
            wait = SLICE if self._established else min(SLICE, self._left())
            readable, writable, _x = select.select(reading, writing, [], wait)

            if local in readable:
                try:
                    data = local.recv(65536)
                except (BlockingIOError, InterruptedError):
                    data = None
                except OSError:
                    data = b""
                if data == b"":
                    local_done = True
                    try:
                        tls.unwrap()              # close_notify, as FFmpeg did
                    except (ssl.SSLWantReadError, ssl.SSLError):
                        pass
                    to_server += self._out.read()
                elif data:
                    data = self.rewrite.feed(data)
                    if self.rewrite.fault:
                        self.fault = ("the connection to %s could not be "
                                      "prepared" % self.host)
                        self.detail = self.rewrite.fault
                        return
                    if data:
                        tls.write(data)
                        to_server += self._out.read()

            if raw in readable:
                try:
                    data = raw.recv(65536)
                except (BlockingIOError, InterruptedError):
                    data = None
                except OSError:
                    # A reset from the server is passed on as a reset, so
                    # FFmpeg reads what it would have read on its own.
                    _hard_close(local)
                    return
                if data == b"":
                    self._in.write_eof()
                elif data:
                    self._in.write(data)
                if data is not None:
                    while True:
                        try:
                            plain = tls.read(65536)
                        except ssl.SSLWantReadError:
                            break
                        except (ssl.SSLZeroReturnError, ssl.SSLEOFError):
                            server_done = True
                            break
                        except ssl.SSLError:
                            _hard_close(local)
                            return
                        if not plain:
                            server_done = True
                            break
                        to_local += plain
                    pending = self._out.read()      # a key update, say
                    if pending:
                        to_server += pending

            if raw in writable and to_server:
                try:
                    sent = raw.send(to_server)
                    del to_server[:sent]
                    stuck_since = 0.0
                except (BlockingIOError, InterruptedError):
                    pass
                except OSError:
                    _hard_close(local)
                    return
            if local in writable and to_local:
                try:
                    sent = local.send(to_local)
                    del to_local[:sent]
                except (BlockingIOError, InterruptedError):
                    pass
                except OSError:
                    local_done = True
                    to_local.clear()

            if to_server:
                now = time.monotonic()
                if not stuck_since:
                    stuck_since = now
                elif now - stuck_since > C.STREAM_STALL_SECONDS:
                    self.fault = ("the connection to %s stopped getting "
                                  "through" % self.host)
                    _hard_close(local)
                    return

    def _shut(self):
        with self._lock:
            listener, self._listener = self._listener, None
            local, self._local_sock = self._local_sock, None
            raw, self._raw = self._raw, None
        for sock in (listener, local, raw):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


def _hard_close(sock):
    """Close with a reset rather than a goodbye, which is what a drop is."""
    if sock is None:
        return
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                        struct.pack("hh", 1, 0))
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def selftest():
    """For `main.py --selftest`: prove FFmpeg can be driven from here.

    The frozen build is where this could fail quietly: the DLL in a
    different folder, a different FFmpeg with a different layout. So it
    finds the DLL the way going live does, writes a file through FFmpegLink
    the way going live writes a stream, reads it back, and checks the
    certificate store the check and the relay both use is not empty.
    Returns a line for the report; raises with the reason.
    """
    import tempfile
    folder = tempfile.mkdtemp(prefix="dropdeck-rtmps-")
    path = os.path.join(folder, "probe.bin")
    link = FFmpegLink("file:" + path.replace("\\", "/"))
    try:
        link.write(b"rtmps probe " * 100)
    finally:
        link.close()
    with open(path, "rb") as handle:
        back = handle.read()
    try:
        os.remove(path)
        os.rmdir(folder)
    except OSError:
        pass
    if back != b"rtmps probe " * 100:
        raise RuntimeError("FFmpeg did not write what it was given")
    bundle = rtmpcheck.certificate_bundle()
    if not bundle:
        raise RuntimeError("certifi's root certificates are not in this "
                           "build, so a computer whose Windows store has not "
                           "fetched a platform's root would be refused")
    authorities = rtmpcheck.tls_context().cert_store_stats().get("x509_ca", 0)
    windows = rtmpcheck.trust_context().cert_store_stats().get("x509_ca", 0)
    if not authorities:
        raise RuntimeError("no certificate authorities are loaded, so no "
                           "secure server could be checked")
    lib = _ffmpeg()
    version = lib.avformat_version()
    return ("secure streaming: FFmpeg %d.%d driven directly, %d certificate "
            "authorities, %d of them from Windows, certifi bundle found "
            "(%s, %d KB)" % (version >> 16, (version >> 8) & 0xFF,
                             authorities, windows,
                             os.path.basename(bundle),
                             os.path.getsize(bundle) // 1024))
