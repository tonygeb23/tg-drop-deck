"""A stand in for Icecast, SHOUTcast and a Liquidsoap harbor.

Testing a stream against a real station means every mistake goes out to real
listeners. This speaks enough of both source protocols to be indistinguishable
from the far end as far as Drop Deck is concerned, keeps what it is sent, and
can be told to behave badly on purpose: refuse the password, hang up mid
sentence, or take the mount and then die.

It is deliberately not clever. Everything it does is what a real server would
do at the point where a bug would show up.
"""
from __future__ import annotations

import base64
import socket
import threading
import time


class MockServer:
    """One connection at a time, which is all a source ever needs."""

    def __init__(self, password="hackme", kind="icecast", accept=True,
                 drop_after=None, expect_mount="/live", stall_after=None,
                 stall_seconds=6.0, bytes_per_second=None):
        #: What it will accept.
        self.password = password
        self.kind = kind
        #: False makes every attempt fail, for testing what the user is told.
        self.accept = accept
        #: Bytes to take before hanging up, or None to stay up. This is how a
        #: dropped connection mid show is tested without unplugging anything.
        self.drop_after = drop_after
        #: Stop reading the socket after this many bytes, for this long, then
        #: carry on. A real network does this: a receiver whose window closes
        #: is not a disconnection, it is a pause, and the difference matters
        #: because a source that treats every pause as a drop reconnects all
        #: night.
        self.stall_after = stall_after
        self.stall_seconds = stall_seconds
        self.stalled = False
        #: Read no faster than this. A link that cannot carry the stream is a
        #: different failure from one that drops: the sender never catches up,
        #: and what it does about that is the thing worth testing.
        self.bytes_per_second = bytes_per_second
        self.expect_mount = expect_mount

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]

        #: What arrived, and what was claimed on the way in.
        self.body = bytearray()
        self.headers = {}
        self.method = None
        self.mount = None
        self.connections = 0
        self.metadata = []
        self.refusals = 0

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ lifetime --
    def close(self):
        self._stop.set()
        try:
            self.sock.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def wait_for_bytes(self, count, timeout=10.0):
        """Block until this much audio has arrived, or give up."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if len(self.body) >= count:
                return True
            time.sleep(0.02)
        return False

    # --------------------------------------------------------------- guts --
    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    def _handle(self, conn):
        try:
            if self.kind == "shoutcast":
                self._handle_shoutcast(conn)
            else:
                self._handle_icecast(conn)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _read_head(conn):
        conn.settimeout(5.0)
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 8192:
            chunk = conn.recv(1024)
            if not chunk:
                break
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        return head.decode("latin-1", "replace"), rest

    def _handle_icecast(self, conn):
        head, rest = self._read_head(conn)
        lines = head.split("\r\n")
        request = lines[0] if lines else ""
        parts = request.split()
        self.method = parts[0] if parts else ""
        self.mount = parts[1] if len(parts) > 1 else ""
        for line in lines[1:]:
            key, _, value = line.partition(":")
            self.headers[key.strip().lower()] = value.strip()

        # A metadata update arrives as an ordinary GET on the same port.
        if self.method == "GET" and "/admin/metadata" in self.mount:
            self.metadata.append(self.mount)
            conn.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
            return

        if not self._authorised() or not self.accept:
            self.refusals += 1
            conn.sendall(b"HTTP/1.0 401 Unauthorized\r\n\r\n")
            return
        if self.expect_mount and self.mount != self.expect_mount:
            self.refusals += 1
            conn.sendall(b"HTTP/1.0 404 Not Found\r\n\r\n")
            return

        conn.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
        self._drain(conn, rest)

    def _handle_shoutcast(self, conn):
        conn.settimeout(5.0)
        line = b""
        while b"\r\n" not in line and len(line) < 256:
            chunk = conn.recv(1)
            if not chunk:
                return
            line += chunk
        if line.decode("latin-1").strip() != self.password or not self.accept:
            self.refusals += 1
            conn.sendall(b"invalid password\r\n")
            return
        conn.sendall(b"OK2\r\nicy-caps:11\r\n\r\n")
        head, rest = self._read_head(conn)
        for entry in head.split("\r\n"):
            key, _, value = entry.partition(":")
            if key:
                self.headers[key.strip().lower()] = value.strip()
        self.method = "SHOUTCAST"
        self.mount = "/"
        self._drain(conn, rest)

    def _authorised(self):
        header = self.headers.get("authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:]).decode("utf-8")
        except Exception:
            return False
        _user, _, password = raw.partition(":")
        return password == self.password

    def _drain(self, conn, rest):
        started = time.monotonic()
        if rest:
            self.body.extend(rest)
        conn.settimeout(1.0)
        while not self._stop.is_set():
            if self.drop_after is not None and len(self.body) >= self.drop_after:
                return
            if (self.stall_after is not None and not self.stalled
                    and len(self.body) >= self.stall_after):
                # Stop reading, without closing. The kernel buffer fills, then
                # the sender's send() blocks. This is what a congested link
                # does to a source client.
                self.stalled = True
                time.sleep(self.stall_seconds)
            if self.bytes_per_second:
                # Pace the reader. The sender fills the kernel buffer and then
                # blocks, which is what a slow uplink feels like from inside.
                allowed = self.bytes_per_second * max(
                    1e-6, time.monotonic() - started)
                if len(self.body) > allowed:
                    time.sleep(0.05)
                    continue
            try:
                chunk = conn.recv(16384)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            self.body.extend(chunk)
