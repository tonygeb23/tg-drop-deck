"""Review 2026-11-24, Area 2: going live over RTMPS checks the certificate.

Mark, 24 November 2026: the live stream to an rtmps address never checked the
server's certificate. PyAV opens the output with `avio_open` and no options,
and FFmpeg's TLS does not check unless told, so a local server holding a
certificate made up on the spot completed the handshake and received the
stream, key and all. Check my stream key DID check, so a key that passed gave
false confidence about the very server it was about to be sent to.

Everything here is local. The servers are `tools/mock_rtmp.py` in TLS mode,
in processes of their own, with certificates from a throwaway authority made
in a temp folder. That authority is trusted only by the SSL context this file
hands the app through `rtmpcheck.tls_context`, never by Windows. Nothing here
connects to YouTube, Facebook or anything else.

What is proved, in the order of the brief:

- a certificate that does not check out (made up, for another name, expired)
  is refused, and the server receives NOTHING after the TLS handshake: no
  RTMP handshake, no connect, no key; said once, not retried, never on air;
- the same refusal through Ctrl+B, the key the user really presses;
- Check my stream key and Ctrl+B agree about the same server;
- a trusted server receives, byte for byte after the handshake, what FFmpeg
  sends it directly today, including the two keys whose length makes FFmpeg
  compress the next header differently;
- a minute of real time media at 720p and 2500 kbps, a dropped connection
  coming back by itself, and nothing left behind afterwards;
- the relay listens on 127.0.0.1 only, takes one connection, closes its
  listener, and a slow server neither freezes the app nor holds up Stop;
- plain rtmp is not touched.
"""
import datetime
import ipaddress
import os
import socket
import ssl
import sys
import tempfile
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-rtmps-")

from dropdeck import constants as C                    # noqa: E402
from dropdeck import rtmpcheck                         # noqa: E402
from dropdeck import streamout                         # noqa: E402
from dropdeck.engine import CHANNELS                   # noqa: E402
import mock_rtmp                                       # noqa: E402

try:
    from dropdeck import rtmpsrelay                    # noqa: E402
except ImportError:
    rtmpsrelay = None

try:
    import psutil
except ImportError:                                    # pragma: no cover
    psutil = None

RATE = 48000
passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  ok   %s" % name)
    else:
        failed += 1
        print("  FAIL %s %s" % (name, detail))


def heading(text):
    print("\n" + text)


def tone(frames, start=0, freq=440.0, level=0.3):
    t = (np.arange(start, start + frames) / float(RATE))
    wave = (level * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.repeat(wave[:, None], CHANNELS, axis=1)


# ---------------------------------------------------------------------------
# A certificate authority that exists only in a temp folder
# ---------------------------------------------------------------------------

from cryptography import x509                                    # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec          # noqa: E402
from cryptography.x509.oid import NameOID                         # noqa: E402

CERTS = tempfile.mkdtemp(prefix="dropdeck-test-ca-")
NOW = datetime.datetime.now(datetime.timezone.utc)
DAY = datetime.timedelta(days=1)


def _name(text):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, text)])


def _write(path, data):
    with open(path, "wb") as handle:
        handle.write(data)
    return path


CA_KEY = ec.generate_private_key(ec.SECP256R1())
CA = (x509.CertificateBuilder()
      .subject_name(_name("Drop Deck test authority, temporary"))
      .issuer_name(_name("Drop Deck test authority, temporary"))
      .public_key(CA_KEY.public_key())
      .serial_number(x509.random_serial_number())
      .not_valid_before(NOW - DAY).not_valid_after(NOW + DAY)
      .add_extension(x509.BasicConstraints(ca=True, path_length=0),
                     critical=True)
      .add_extension(x509.KeyUsage(
          digital_signature=True, key_cert_sign=True, crl_sign=True,
          content_commitment=False, key_encipherment=False,
          data_encipherment=False, key_agreement=False, encipher_only=False,
          decipher_only=False), critical=True)
      # Python 3.13 checks strictly (VERIFY_X509_STRICT), which wants both
      # key identifiers. A real authority's certificates carry them.
      .add_extension(x509.SubjectKeyIdentifier.from_public_key(
          CA_KEY.public_key()), critical=False)
      .sign(CA_KEY, hashes.SHA256()))
CA_FILE = _write(os.path.join(CERTS, "authority.pem"),
                 CA.public_bytes(serialization.Encoding.PEM))


def leaf(tag, names, addresses=(), signed=True, start=-DAY, end=DAY):
    key = ec.generate_private_key(ec.SECP256R1())
    alt = ([x509.DNSName(n) for n in names]
           + [x509.IPAddress(ipaddress.ip_address(a)) for a in addresses])
    subject = _name((list(names) + list(addresses))[0])
    builder = (x509.CertificateBuilder().subject_name(subject)
               .issuer_name(CA.subject if signed else subject)
               .public_key(key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(NOW + start).not_valid_after(NOW + end)
               .add_extension(x509.SubjectAlternativeName(alt),
                              critical=False)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(
                   key.public_key()), critical=False))
    if signed:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                CA_KEY.public_key()), critical=False)
    cert = builder.sign(CA_KEY if signed else key, hashes.SHA256())
    return (_write(os.path.join(CERTS, tag + ".pem"),
                   cert.public_bytes(serialization.Encoding.PEM)),
            _write(os.path.join(CERTS, tag + ".key"),
                   key.private_bytes(serialization.Encoding.PEM,
                                     serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())))


GOOD = leaf("good", ["localhost"], ["127.0.0.1"])
WRONG_NAME = leaf("wrong-name", ["not-this-server.example"])
EXPIRED = leaf("expired", ["localhost"], ["127.0.0.1"], start=-10 * DAY,
               end=-DAY)
MADE_UP = leaf("made-up", ["localhost"], ["127.0.0.1"], signed=False)

#: The trust the app really uses, kept so it can be put back, and the same
#: trust with the test authority added. Only ever the test's own context:
#: the Windows store is not touched.
REAL_TRUST = getattr(rtmpcheck, "tls_context", ssl.create_default_context)


def trusting_test_authority():
    context = REAL_TRUST()
    context.load_verify_locations(cafile=CA_FILE)
    return context


def trust(test_authority):
    rtmpcheck.tls_context = (trusting_test_authority if test_authority
                             else REAL_TRUST)


KEY = "abcd-efgh-ijkl-mnop"
SMALL = {"bitrate": 128, "video_width": 320, "video_height": 180,
         "video_fps": 30, "video_bitrate": 600}


def settings(host, key=KEY, **extra):
    out = {"server": "rtmp", "host": host, "password": key}
    out.update(SMALL)
    out.update(extra)
    return out


def send_two_seconds(destination):
    """The same audio, and so the same pictures, every time it is called."""
    block = RATE // 30
    for index in range(60):
        destination.feed(tone(block, start=index * block))


def publish(host, cert, key=KEY, direct=False, port=None, seconds=2.0,
            **spawn):
    """One RtmpDestination to one mock. `direct` is the old path: PyAV hands
    the address straight to FFmpeg, which checks nothing, holding the GIL.
    `cert` None is a plain RTMP mock."""
    keep = getattr(streamout.RtmpDestination, "_target", None)
    if direct and keep is not None:
        streamout.RtmpDestination._target = lambda self, url: url
    error = ""
    took = 0.0
    try:
        with mock_rtmp.spawn(port=port, seconds=30,
                             cert=cert[0] if cert else None,
                             key=cert[1] if cert else None,
                             **spawn) as server:
            address = host % server.port if "%d" in host else host
            destination = streamout.RtmpDestination(settings(address, key),
                                                    RATE)
            started = time.monotonic()
            try:
                destination.connect()
                if seconds:
                    send_two_seconds(destination)
            except Exception as exc:
                error = str(exc)
            finally:
                took = time.monotonic() - started
                destination.close()
    finally:
        if keep is not None:
            streamout.RtmpDestination._target = keep
    return error, took, server.result()


def relay_threads():
    return [t for t in threading.enumerate()
            if t.name == "dropdeck-rtmps-relay" and t.is_alive()]


def connections_to(port):
    """This process's TCP connections to one port, or to it as ours."""
    if psutil is None:
        return []
    return [c for c in psutil.Process().net_connections(kind="tcp")
            if (c.raddr and c.raddr.port == port)
            or (c.laddr and c.laddr.port == port)]


# ===========================================================================
heading("A certificate that does not check out sends nothing")
# ===========================================================================

trust(True)
for label, cert, host in (
        ("made up on the spot", MADE_UP, "rtmps://127.0.0.1:%d/live"),
        ("for another name", WRONG_NAME, "rtmps://localhost:%d/live"),
        ("expired", EXPIRED, "rtmps://127.0.0.1:%d/live")):
    error, took, result = publish(host, cert)
    seen = result.connections[0] if result.connections else {}
    check("a certificate %s is refused" % label,
          "certificate could not be checked" in error, error)
    check("  and the server got nothing after the TLS handshake",
          seen.get("received") == 0 and not seen.get("calls")
          and str(seen.get("tls", "")).startswith("refused"),
          "%s, %s bytes, %s" % (seen.get("tls"), seen.get("received"),
                                result.commands))
    check("  so the key never reached it",
          not any(KEY in str(call) for call in result.calls), result.calls)
    check("  and it says so in one plain sentence",
          error.count(". ") == 0 and chr(8212) not in error
          and chr(8211) not in error and KEY not in error, error)

if rtmpsrelay is not None:
    check("the sentence says the key is not what is wrong",
          "stream key never left this machine" in rtmpsrelay.CERT_REFUSED,
          rtmpsrelay.CERT_REFUSED)

trust(False)
error, took, result = publish("rtmps://127.0.0.1:%d/live", GOOD)
check("a certificate from an authority Windows does not trust is refused "
      "too", "certificate could not be checked" in error, error)
check("  with nothing sent", result.connections
      and result.connections[0]["received"] == 0, result.connections)


# ===========================================================================
heading("Said once, not retried, never on air")
# ===========================================================================

with mock_rtmp.spawn(seconds=30, cert=MADE_UP[0], key=MADE_UP[1]) as server:
    bus = streamout.AirBus(RATE)
    states = []
    streamer = streamout.Streamer(
        bus, settings("rtmps://127.0.0.1:%d/live" % server.port),
        on_state=lambda state, detail: states.append((state, detail)))
    streamer.start()
    deadline = time.time() + 15
    pushed = 0
    while time.time() < deadline and streamer.running:
        bus.write("main", tone(2048, start=pushed))
        pushed += 2048
        time.sleep(0.02)
    still = streamer.running
    streamer.stop()
refused = server.result()
names = [state for state, _detail in states]
check("the stream ends in FAILED", streamout.FAILED in names, states)
check("after exactly one attempt", streamer.attempts == 1, streamer.attempts)
check("and the thread stopped by itself", not still)
check("it never said it was on air", streamout.ON_AIR not in names, names)
check("and never said it was trying again",
      streamout.RECONNECTING not in names, names)
failure = [detail for state, detail in states if state == streamout.FAILED]
check("the reason is the certificate",
      failure and "certificate could not be checked" in failure[0], failure)
check("and _retryable agrees, whichever attempt it is on",
      not streamer._retryable(), streamer.error)
streamer.attempts = 5
check("  including a reconnect", not streamer._retryable(), streamer.error)
check("and the server was offered nothing",
      refused.connections and refused.connections[0]["received"] == 0
      and not refused.calls, refused.connections)


# ===========================================================================
heading("Ctrl+B says it, and nothing claims to be on air")
# ===========================================================================

import wx                                                       # noqa: E402

from dropdeck import ui as uimod                                # noqa: E402

app = wx.App(redirect=False)
frame = uimod.DropDeckFrame()
said = []
frame.announce = lambda text, *a, **k: said.append(text)

with mock_rtmp.spawn(seconds=30, cert=EXPIRED[0], key=EXPIRED[1]) as server:
    trust(True)
    board = frame.board
    board.stream_name = "RTMPS test station %d" % os.getpid()
    board.video_server = "rtmp"
    board.video_host = "rtmps://127.0.0.1:%d/live" % server.port
    board.video_key = KEY
    board.ask_before_live = False
    board.live_to = C.LIVE_TO_VIDEO
    # Through the binding, the way the key arrives, not the handler.
    frame.GetEventHandler().ProcessEvent(
        wx.CommandEvent(wx.wxEVT_MENU, uimod.ID_STREAM_TOGGLE))
    deadline = time.time() + 15
    while time.time() < deadline and not any(
            "Could not go on air" in s for s in said):
        wx.Yield()
        time.sleep(0.02)
    for _ in range(20):
        wx.Yield()
        time.sleep(0.02)
    live_anyway = frame.streaming()
    if live_anyway:
        frame.stop_stream(quiet=True)
spoken = [s for s in said if "Could not go on air" in s]
check("Ctrl+B says it could not go on air",
      len(spoken) == 1, said)
check("  because the certificate could not be checked",
      spoken and "certificate could not be checked" in spoken[0], spoken)
check("  and nothing said it was on air",
      not any(s.startswith("On air") for s in said), said)
check("  and the app is off air afterwards", not live_anyway)
check("  and Ctrl+Shift+B agrees",
      "On air" not in frame.stream_status()
      or "Off air" in frame.stream_status(), frame.stream_status())
check("  and the server got nothing after the handshake",
      server.result().connections
      and server.result().connections[0]["received"] == 0,
      server.result().connections)


# ===========================================================================
heading("Check my stream key and Ctrl+B agree about one server")
# ===========================================================================

prefs = None
try:
    from dropdeck.dialogs import SettingsDialog                 # noqa: E402
    prefs = SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic,
                           page=SettingsDialog.PAGE_VIDEO)
except Exception as exc:                                        # pragma: no cover
    print("  (no Preferences: %r)" % exc)

for trusted, cert, label in ((True, MADE_UP, "made up"),
                             (True, GOOD, "trusted"),
                             (False, GOOD, "not trusted by Windows")):
    trust(trusted)
    with mock_rtmp.spawn(seconds=30, cert=cert[0], key=cert[1]) as server:
        answer = rtmpcheck.verify("rtmps://127.0.0.1:%d/live" % server.port,
                                  KEY)
    check_ok = answer.outcome == rtmpcheck.ACCEPTED
    error, _took, _result = publish("rtmps://127.0.0.1:%d/live", cert,
                                    seconds=0)
    live_ok = not error
    check("%s: the check and going live give the same answer" % label,
          check_ok == live_ok,
          "check %s, live %r" % (answer.outcome, error))
    if not check_ok:
        check("  and the check calls it the certificate, not the network",
              answer.outcome == getattr(rtmpcheck, "BAD_CERT", "?"),
              answer.outcome)
        if prefs is not None:
            verdict = prefs._key_verdict(answer, "rtmp", "Custom RTMP server",
                                         "127.0.0.1", KEY)
            check("  and its sentence says so, and that the key may be fine",
                  "certificate could not be checked" in verdict
                  and "key may be fine" in verdict, verdict)
if prefs is not None:
    prefs.Destroy()
trust(True)


# ===========================================================================
heading("A trusted server receives what FFmpeg sends it directly")
# ===========================================================================

port = mock_rtmp._free_port()
base = "rtmps://127.0.0.1:%d/live"
direct_error, _t, direct = publish(base, GOOD, direct=True, port=port)
relay_error, _t, relayed = publish(base, GOOD, port=port)
check("today's path still works against the same server",
      not direct_error and direct.publishing, direct_error)
check("the checked path connects and publishes", not relay_error
      and relayed.publishing, relay_error)
if direct.calls and relayed.calls:
    connect_a, connect_b = direct.calls[0][2], relayed.calls[0][2]
    for field in ("tcUrl", "app", "flashVer", "type"):
        check("same %s: %s" % (field, connect_b.get(field)),
              connect_a.get(field) == connect_b.get(field),
              "%r against %r" % (connect_a.get(field),
                                 connect_b.get(field)))
    check("and the tcUrl is the real server, not the loopback relay",
          connect_b.get("tcUrl") == "rtmps://127.0.0.1:%d/live" % port,
          connect_b.get("tcUrl"))
    publish_a = [c for c in direct.calls if c[0] == "publish"]
    publish_b = [c for c in relayed.calls if c[0] == "publish"]
    check("same publish name", publish_a and publish_b
          and publish_a[0][3] == publish_b[0][3] == KEY,
          (publish_a, publish_b))
check("every command the same, in the same order, with the same values",
      direct.calls == relayed.calls, (direct.calls, relayed.calls))
check("the same media tag counts", direct.counts == relayed.counts
      and direct.audio > 50 and direct.video > 30,
      (direct.counts, relayed.counts))
a = direct.connections[0] if direct.connections else {}
b = relayed.connections[0] if relayed.connections else {}
check("and byte for byte the same after the handshake (%s bytes)"
      % b.get("stream_bytes"),
      a.get("stream_sha256") and a.get("stream_sha256")
      == b.get("stream_sha256")
      and a.get("stream_bytes") == b.get("stream_bytes"),
      "%s/%s bytes" % (a.get("stream_bytes"), b.get("stream_bytes")))
check("over TLS that Python checked", b.get("tls") == "completed",
      b.get("tls"))

# The two keys whose length makes FFmpeg compress the next header differently
# from the way the server would read it: a releaseStream exactly as long as
# the REAL connect, and exactly as long as the one FFmpeg sent the relay.
lengths = dict((name, size) for name, size in a.get("lengths", []))
if "connect" in lengths and "releaseStream" in lengths:
    real_connect = lengths["connect"]
    fixed = lengths["releaseStream"] - len(KEY)
    # The relay's port has five digits as well, so the loopback connect is
    # exactly one byte shorter: "rtmp" against "rtmps".
    for label, size in (("the real connect", real_connect),
                        ("the connect FFmpeg sent the relay",
                         real_connect - 1)):
        key = "k" * (size - fixed)
        e1, _t, one = publish(base, GOOD, key=key, direct=True, port=port)
        e2, _t, two = publish(base, GOOD, key=key, port=port)
        x = one.connections[0] if one.connections else {}
        y = two.connections[0] if two.connections else {}
        check("a key making releaseStream as long as %s still matches "
              "byte for byte" % label,
              not e1 and not e2 and x.get("stream_sha256")
              and x.get("stream_sha256") == y.get("stream_sha256")
              and one.calls == two.calls,
              "%r %r %s %s" % (e1, e2, x.get("lengths", [])[:2],
                               y.get("lengths", [])[:2]))
    # And the control, which shows the check above can fail: the same key
    # with the header refit switched off.
    if rtmpsrelay is not None:
        def as_ffmpeg_sent_it(self, basic, ts, length, kind, extended):
            fmt = basic[0] >> 6
            fields = (ts.to_bytes(3, "big") + length.to_bytes(3, "big")
                      + bytes([kind]) if fmt == 1
                      else ts.to_bytes(3, "big") if fmt == 2 else b"")
            return basic + fields + extended

        keep = rtmpsrelay.ConnectRewrite._refit
        keep_timeout = C.STREAM_TIMEOUT
        rtmpsrelay.ConnectRewrite._refit = as_ffmpeg_sent_it
        # The server loses its place, so FFmpeg waits for an answer that
        # never comes; the relay's own deadline ends it.
        C.STREAM_TIMEOUT = 3.0
        try:
            key = "k" * (real_connect - 1 - fixed)
            e3, _t, broken = publish(base, GOOD, key=key, port=port)
        finally:
            rtmpsrelay.ConnectRewrite._refit = keep
            C.STREAM_TIMEOUT = keep_timeout
        z = broken.connections[0] if broken.connections else {}
        check("(control: without the refit that key does NOT match)",
              z.get("stream_sha256") != x.get("stream_sha256")
              or broken.calls != one.calls, z.get("lengths"))
else:
    check("the server kept the command lengths", False, a)

# The default port. FFmpeg writes it into the tcUrl even when the address
# leaves it out; measured on plain rtmp, where it is 1935.
probe = socket.socket()
try:
    probe.bind(("127.0.0.1", 443))
    free = True
except OSError:
    free = False
probe.close()
if free:
    e1, _t, one = publish("rtmps://127.0.0.1/live", GOOD, direct=True,
                          port=443)
    e2, _t, two = publish("rtmps://127.0.0.1/live", GOOD, port=443)
    tc1 = one.calls[0][2].get("tcUrl") if one.calls else e1
    tc2 = two.calls[0][2].get("tcUrl") if two.calls else e2
    check("an address with no port gets the same tcUrl: %s" % tc2,
          tc1 == tc2 == "rtmps://127.0.0.1:443/live", (tc1, tc2))
else:
    print("  (port 443 is in use here, so the default port was checked by "
          "the address tests below only)")

if rtmpsrelay is not None:
    for url, prefix, local in (
            ("rtmps://a.rtmps.youtube.com/live2/K",
             "rtmps://a.rtmps.youtube.com:443", "rtmp://127.0.0.1:%d/live2/K"),
            ("rtmps://live-api-s.facebook.com:443/rtmp/K",
             "rtmps://live-api-s.facebook.com:443",
             "rtmp://127.0.0.1:%d/rtmp/K"),
            ("rtmps://b.rtmps.youtube.com:443/live2?backup=1/K",
             "rtmps://b.rtmps.youtube.com:443",
             "rtmp://127.0.0.1:%d/live2?backup=1/K"),
            ("rtmps://[::1]:8443/app/K", "rtmps://[::1]:8443",
             "rtmp://127.0.0.1:%d/app/K"),
            ("rtmps://Mixed.Case.Example/app/K",
             "rtmps://Mixed.Case.Example:443", "rtmp://127.0.0.1:%d/app/K")):
        _host, _port, real, loop = rtmpsrelay.split_address(url)
        check("%s is read the way FFmpeg reads it" % url.split("/")[2],
              real == prefix and loop == local, (real, loop))
    for bad in ("rtmps://host:notaport/app", "rtmps:///app", "rtmp://x/a"):
        try:
            rtmpsrelay.split_address(bad)
            refused = False
        except rtmpsrelay.RelayError:
            refused = True
        check("%r is refused rather than guessed at" % bad, refused)
else:
    check("the relay exists", False)


# ===========================================================================
heading("The relay: the loopback only, one connection, then no listener")
# ===========================================================================

if rtmpsrelay is not None:
    with mock_rtmp.spawn(seconds=30, cert=GOOD[0], key=GOOD[1],
                         stall=True) as server:
        relay = rtmpsrelay.Relay("rtmps://127.0.0.1:%d/live/%s"
                                 % (server.port, KEY), timeout=8).start()
        listening = relay.wait_ready()
        address = relay._listener.getsockname() if relay._listener else None
        check("it listens on 127.0.0.1 and nowhere else",
              address == ("127.0.0.1", listening), address)
        check("only after the certificate was checked",
              relay.handshake_done, relay.detail)
        first = socket.create_connection(("127.0.0.1", listening), 3)
        deadline = time.time() + 3
        while time.time() < deadline and relay._listener is not None:
            time.sleep(0.02)
        check("its listener is closed the moment one connection arrives",
              relay._listener is None)
        if psutil is not None:
            check("  and Windows agrees nothing is listening there",
                  not [c for c in connections_to(listening)
                       if c.status == psutil.CONN_LISTEN])
        second = socket.socket()
        second.settimeout(3)
        try:
            second.connect(("127.0.0.1", listening))
            taken = True
        except OSError:
            taken = False
        second.close()
        check("so a second connection is refused", not taken)
        first.close()
        relay.close()
        check("and closing it leaves no thread", not relay.running)


# ===========================================================================
heading("A slow server neither freezes the app nor holds up Stop")
# ===========================================================================

class NoRelay(Exception):
    pass


keep_timeout = C.STREAM_TIMEOUT
C.STREAM_TIMEOUT = 3.0
try:
    if rtmpsrelay is None:
        # Not run without the relay, because it does not fail, it hangs:
        # PyAV holds the GIL through FFmpeg's handshake, so every thread in
        # the process stops until the server answers, which a stalled one
        # never does. Measured: killed after thirty seconds, no output.
        raise NoRelay()
    for label, spawn in (("takes the connection and never starts TLS",
                          dict(stall=True)),
                         ("finishes TLS and never answers RTMP",
                          dict(stall=True, cert=GOOD[0], key=GOOD[1]))):
        with mock_rtmp.spawn(seconds=30, **spawn) as server:
            destination = streamout.RtmpDestination(
                settings("rtmps://127.0.0.1:%d/live" % server.port), RATE)
            ticks = []
            ticking = [True]

            def tick():
                while ticking[0]:
                    ticks.append(time.monotonic())
                    time.sleep(0.02)

            ticker = threading.Thread(target=tick, daemon=True)
            ticker.start()
            started = time.monotonic()
            try:
                destination.connect()
                error = ""
            except Exception as exc:
                error = str(exc)
            took = time.monotonic() - started
            ticking[0] = False
            ticker.join()
            destination.close()
        worst = max((b - a for a, b in zip(ticks, ticks[1:])), default=9)
        check("a server that %s is given up on in time (%.1f s)"
              % (label, took), took < C.STREAM_TIMEOUT + 2
              and "did not answer" in error, error)
        check("  and every other thread ran throughout (worst gap %.0f ms)"
              % (worst * 1000), worst < 0.5, worst)

    for label, spawn in (("TLS handshake", dict(stall=True)),
                         ("RTMP handshake inside FFmpeg",
                          dict(stall=True, cert=GOOD[0], key=GOOD[1]))):
        with mock_rtmp.spawn(seconds=30, **spawn) as server:
            bus = streamout.AirBus(RATE)
            streamer = streamout.Streamer(
                bus, settings("rtmps://127.0.0.1:%d/live" % server.port))
            heard = []
            streamer.on_state = lambda state, detail: heard.append(state)
            streamer.start()
            time.sleep(1.0)
            started = time.monotonic()
            streamer.stop()
            took = time.monotonic() - started
            alive = streamer._thread is not None or any(
                t.name == "dropdeck-stream" and t.is_alive()
                for t in threading.enumerate())
            time.sleep(0.6)
        check("Stop during a slow %s comes back at once (%.2f s)"
              % (label, took), took < 1.0 and not alive, (took, alive))
        check("  and says nothing about a failure",
              streamout.FAILED not in heard, heard)
        check("  and leaves no relay running", not relay_threads(),
              relay_threads())
except NoRelay:
    check("a slow server is given up on without freezing the app", False,
          "there is no relay")
finally:
    C.STREAM_TIMEOUT = keep_timeout


# ===========================================================================
heading("A dropped connection comes back, and Stop leaves nothing behind")
# ===========================================================================

with mock_rtmp.spawn(seconds=60, cert=GOOD[0], key=GOOD[1], connections=2,
                     drop_after=200) as server:
    bus = streamout.AirBus(RATE)
    states = []
    streamer = streamout.Streamer(
        bus, settings("rtmps://127.0.0.1:%d/live" % server.port),
        on_state=lambda state, detail: states.append(state))
    streamer.start()
    deadline = time.time() + 30
    pushed = 0
    nxt = time.perf_counter()
    while time.time() < deadline:
        bus.write("main", tone(1024, start=pushed))
        pushed += 1024
        nxt += 1024 / float(RATE)
        wait = nxt - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        if streamer.reconnects and streamer.state == streamout.ON_AIR \
                and time.time() > deadline - 26 and pushed > RATE * 4:
            break
    for _ in range(int(RATE * 1.5 / 1024)):
        bus.write("main", tone(1024, start=pushed))
        pushed += 1024
        time.sleep(1024 / float(RATE))
    mock_port = server.port
    during = len(relay_threads())
    streamer.stop()
    time.sleep(0.5)
    left = relay_threads()
    sockets = connections_to(mock_port)
back = server.result()
check("on air, then trying again, then on air again",
      states.count(streamout.ON_AIR) >= 2
      and streamout.RECONNECTING in states, states)
check("through the existing reconnect path (one reconnect)",
      streamer.reconnects == 1, streamer.reconnects)
check("both connections were checked TLS",
      [c["tls"] for c in back.connections] == ["completed", "completed"],
      [c["tls"] for c in back.connections])
check("and the second one published again",
      len(back.connections) == 2 and back.connections[1]["publishing"]
      and back.connections[1]["counts"]["audio"] > 20,
      back.connections[1:] and back.connections[1]["counts"])
check("one relay while it ran", during == 1, during)
check("none after Stop", not left, left)
if psutil is not None:
    check("and no socket of ours left to that server",
          not [c for c in sockets if c.status != psutil.CONN_TIME_WAIT],
          sockets)
else:
    print("  (psutil is not installed, so sockets were not listed)")


# ===========================================================================
heading("A minute of real time, at 720p and 2500 kbps, through the relay")
# ===========================================================================


class Moving:
    """A picture that keeps changing, so the encoder really spends the
    bitrate. A card costs 64 kbps and proves nothing about a camera."""

    kind = C.PICTURE_CAMERA

    def __init__(self, width=1280, height=720, count=24):
        rng = np.random.default_rng(7)
        small = rng.integers(0, 256, (count, height // 8, width // 8, 3),
                             dtype=np.uint8)
        self.frames = [np.ascontiguousarray(
            np.repeat(np.repeat(f, 8, axis=0), 8, axis=1)) for f in small]
        self.at = 0

    def frame(self, width, height):
        self.at += 1
        return self.frames[self.at % len(self.frames)]

    def start(self):
        return self

    def close(self):
        pass


MINUTE = 62.0
with mock_rtmp.spawn(seconds=MINUTE + 40, cert=GOOD[0], key=GOOD[1]) as server:
    bus = streamout.AirBus(RATE)
    trouble = []
    states = []
    streamer = streamout.Streamer(
        bus, {"server": "rtmp",
              "host": "rtmps://127.0.0.1:%d/live" % server.port,
              "password": KEY, "bitrate": 128, "video_width": 1280,
              "video_height": 720, "video_fps": 30, "video_bitrate": 2500},
        video_source=Moving(), on_trouble=trouble.append,
        on_state=lambda state, detail: states.append(state))
    streamer.start()
    started = time.time()
    pushed = 0
    block = 1024
    nxt = time.perf_counter()
    worst_backlog = 0.0
    on_air_at = None
    while time.time() - started < MINUTE + 15:
        bus.write("main", tone(block, start=pushed))
        pushed += block
        nxt += block / float(RATE)
        wait = nxt - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        if streamer.state == streamout.ON_AIR:
            if on_air_at is None:
                on_air_at = time.time()
            worst_backlog = max(worst_backlog, streamer.backlog)
            if time.time() - on_air_at >= MINUTE:
                break
    sent = streamer.bytes_sent
    streamer.stop()
minute = server.result()
seconds_of_audio = minute.audio * 1024 / float(RATE)
check("on air the whole time", states.count(streamout.ON_AIR) == 1
      and streamout.RECONNECTING not in states, states)
check("a minute of audio arrived (%.1f s)" % seconds_of_audio,
      seconds_of_audio >= 60.0, minute.counts)
check("and the pictures to go with it (%d)" % minute.video,
      minute.video >= 60 * 30 - 30, minute.counts)
stream_bytes = minute.connections[0]["stream_bytes"] \
    if minute.connections else 0
rate = stream_bytes * 8 / 1000.0 / max(1.0, seconds_of_audio)
check("at a realistic bitrate (%.0f kbps)" % rate, 1800 < rate < 3400, rate)
check("the link never fell behind (worst backlog %.2f s)" % worst_backlog,
      worst_backlog < C.STREAM_BEHIND_SECONDS and not trouble,
      (worst_backlog, trouble))
arrivals = np.array(minute.video_arrivals)
if len(arrivals) > 100:
    gaps = np.diff(arrivals) * 1000.0
    check("the pictures arrived evenly: middle gap %.1f ms"
          % np.median(gaps), 20 < float(np.median(gaps)) < 50,
          np.median(gaps))
    check("  slow tail p95 %.1f ms" % np.percentile(gaps, 95),
          float(np.percentile(gaps, 95)) < 90, np.percentile(gaps, 95))
    check("  worst %.0f ms" % gaps.max(), float(gaps.max()) < 400,
          gaps.max())
try:
    container = minute.container()
    decoded = sum(1 for _ in container.decode(video=0))
    container.close()
except Exception as exc:
    decoded = "%r" % exc
check("and the server can decode what it got (%s frames)" % decoded,
      isinstance(decoded, int) and decoded >= 60 * 30 - 30, decoded)


# ===========================================================================
heading("Root certificates: the Windows store AND certifi")
# ===========================================================================

#: Windows fills its store with roots on demand, and only for programs that
#: ask Windows itself to check a certificate; Chrome and Firefox never ask.
#: Python reads the store as it stands, so a root Windows has not fetched
#: yet is a refusal at the top of a show. On this machine GTS Root R4, one
#: of YouTube's, is exactly such a root: in certifi, not in the store.
import certifi                                                  # noqa: E402

trust(False)


def subjects(context):
    return {tuple(sorted(dict(part[0] for part in ca["subject"]).items()))
            for ca in context.get_ca_certs()}


in_bundle = subjects(ssl.create_default_context(cafile=certifi.where()))
in_store = subjects(ssl.create_default_context())
trusted = subjects(rtmpcheck.tls_context())
check("certifi is here, %d roots" % len(in_bundle), len(in_bundle) > 100,
      certifi.where())
check("every root in certifi is trusted (%d missing from Windows here)"
      % len(in_bundle - in_store), in_bundle <= trusted,
      len(in_bundle - trusted))
check("and every root in the Windows store still is", in_store <= trusted,
      len(in_store - trusted))
context = rtmpcheck.tls_context()
check("the name is still checked against the address",
      context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED)

builder = getattr(rtmpcheck, "trust_context", None)
if builder is not None:
    # The Windows side left out entirely, and the test authority standing in
    # for certifi: a root that is ONLY in the bundle must be enough, through
    # the real check and the real Ctrl+B path.
    rtmpcheck.tls_context = lambda: builder(system=False, bundle=CA_FILE)
    try:
        for label, cert, host, ok in (
                ("a server whose root is only in the bundle", GOOD,
                 "rtmps://127.0.0.1:%d/live", True),
                ("a self signed server", MADE_UP,
                 "rtmps://127.0.0.1:%d/live", False),
                ("the bundle's own server under another name", WRONG_NAME,
                 "rtmps://localhost:%d/live", False)):
            with mock_rtmp.spawn(seconds=30, cert=cert[0],
                                 key=cert[1]) as server:
                answer = rtmpcheck.verify(host % server.port, KEY)
            error, _took, result = publish(host, cert, seconds=0)
            check("%s: %s by the check and by going live"
                  % (label, "trusted" if ok else "refused"),
                  (answer.outcome == rtmpcheck.ACCEPTED) == ok
                  and (not error) == ok,
                  "check %s, live %r" % (answer.outcome, error))
            if not ok:
                check("  with nothing sent after the handshake",
                      result.connections
                      and result.connections[0]["received"] == 0,
                      result.connections)
    finally:
        trust(False)
else:
    check("a context can be built from a bundle with no Windows side", False,
          "there is no trust_context")

from dropdeck import appupdate                                  # noqa: E402

seen = []


def no_network(request, timeout=None, context=None):
    seen.append(context)
    raise OSError("not fetched: this is a test")


keep_urlopen = appupdate.urllib.request.urlopen
appupdate.urllib.request.urlopen = no_network
try:
    appupdate._fetch("https://updates.invalid/manifest.json")
except OSError:
    pass
finally:
    appupdate.urllib.request.urlopen = keep_urlopen
check("the update check trusts the same roots, certifi's included",
      seen and seen[0] is not None and subjects(seen[0]) == trusted
      and in_bundle <= subjects(seen[0]),
      seen and seen[0] is not None and len(subjects(seen[0])))
if rtmpsrelay is not None:
    try:
        line = rtmpsrelay.selftest()
    except Exception as exc:
        line = "raised %r" % exc
    check("the frozen build's selftest says the bundle was found: %s" % line,
          "certifi bundle found" in line, line)
    trust(True)
else:
    check("the frozen build's selftest says the bundle was found", False)


# ===========================================================================
heading("Plain rtmp: the same bytes, and the app never freezes")
# ===========================================================================

made, links = [], []
if rtmpsrelay is not None:
    real_relay, real_link = rtmpsrelay.Relay, rtmpsrelay.FFmpegLink

    class Spy(real_relay):
        def __init__(self, *args, **kwargs):
            made.append(args)
            super().__init__(*args, **kwargs)

    class LinkSpy(real_link):
        def __init__(self, url, *args, **kwargs):
            links.append(url)
            super().__init__(url, *args, **kwargs)

    rtmpsrelay.Relay, rtmpsrelay.FFmpegLink = Spy, LinkSpy
try:
    port = mock_rtmp._free_port()
    old_error, _t, old = publish("rtmp://127.0.0.1:%d/live", None,
                                 direct=True, port=port)
    links.clear()
    new_error, _t, new = publish("rtmp://127.0.0.1:%d/live", None, port=port)
finally:
    if rtmpsrelay is not None:
        rtmpsrelay.Relay, rtmpsrelay.FFmpegLink = real_relay, real_link
through_link = bool(links) and links[0].startswith("rtmp://127.0.0.1:")
check("a plain rtmp address makes no relay", not made, made)
check("and goes through FFmpeg's own client with the GIL let go",
      through_link, links)
x = old.connections[0] if old.connections else {}
y = new.connections[0] if new.connections else {}
check("it publishes as before", not old_error and not new_error
      and new.publishing and new.audio > 50, (old_error, new_error))
check("every command the same", old.calls == new.calls
      and new.calls and new.calls[0][2].get("tcUrl")
      == "rtmp://127.0.0.1:%d/live" % port, new.calls[:1])
check("and byte for byte the same after the handshake (%s bytes)"
      % y.get("stream_bytes"),
      x.get("stream_sha256") and x.get("stream_sha256")
      == y.get("stream_sha256"),
      "%s/%s" % (x.get("stream_bytes"), y.get("stream_bytes")))

# In a process of its own, because on the old path this does not fail, it
# freezes every thread in the process, the one that would report it too.
CHILD = r'''
import os, sys, threading, time
sys.path[:0] = [sys.argv[2]]
os.environ["APPDATA"] = sys.argv[3]
from dropdeck import constants as C, streamout
C.STREAM_TIMEOUT = 3.0
destination = streamout.RtmpDestination(
    {"server": "rtmp", "host": "rtmp://127.0.0.1:%s/live" % sys.argv[1],
     "password": "abcd", "bitrate": 128, "video_width": 320,
     "video_height": 180, "video_bitrate": 600}, 48000)
said = []
def go():
    try:
        destination.connect()
        said.append("connected")
    except Exception as exc:
        said.append(str(exc))
    destination.close()
worker = threading.Thread(target=go, daemon=True)
started = time.monotonic()
worker.start()
ticks = []
while worker.is_alive() and time.monotonic() - started < 20:
    ticks.append(time.monotonic())
    time.sleep(0.02)
worst = max(b - a for a, b in zip(ticks, ticks[1:])) if len(ticks) > 1 else 9
print("RESULT|%.2f|%.3f|%s" % (time.monotonic() - started, worst,
                               said[0] if said else "still connecting"),
      flush=True)
'''
child = os.path.join(tempfile.mkdtemp(prefix="dropdeck-rtmp-child-"),
                     "child.py")
with open(child, "w", encoding="utf-8") as handle:
    handle.write(CHILD)
import subprocess                                               # noqa: E402

with mock_rtmp.spawn(seconds=40, stall=True) as server:
    try:
        ran = subprocess.run(
            [sys.executable, "-I", child, str(server.port), HERE,
             tempfile.mkdtemp(prefix="dropdeck-rtmp-child-data-")],
            capture_output=True, text=True, timeout=25)
        lines = [l for l in ran.stdout.splitlines() if l.startswith("RESULT|")]
        report = lines[0].split("|", 3) if lines else None
    except subprocess.TimeoutExpired:
        report = None
check("a plain rtmp server that never answers leaves every thread running",
      report is not None and float(report[2]) < 0.5,
      report or "the whole process froze and was killed after 25 s")
check("  and is given up on after the timeout (%s s)"
      % (report[1] if report else "never"),
      report is not None and float(report[1]) < 3.0 + 2,
      report)
check("  with the existing sentence",
      report is not None and report[3] == "127.0.0.1 did not answer",
      report)

if through_link:
    for label, spawn in (("never answers", dict(stall=True)),):
        with mock_rtmp.spawn(seconds=30, **spawn) as server:
            bus = streamout.AirBus(RATE)
            heard = []
            streamer = streamout.Streamer(
                bus, settings("rtmp://127.0.0.1:%d/live" % server.port),
                on_state=lambda state, detail: heard.append(state))
            streamer.start()
            time.sleep(1.0)
            started = time.monotonic()
            streamer.stop()
            took = time.monotonic() - started
            alive = any(t.name == "dropdeck-stream" and t.is_alive()
                        for t in threading.enumerate())
        check("Stop while a plain rtmp server %s comes back at once (%.2f s)"
              % (label, took), took < 1.0 and not alive, (took, alive))
        check("  and says nothing about a failure",
              streamout.FAILED not in heard, heard)
else:
    check("Stop while a plain rtmp server never answers comes back", False,
          "not tried: on PyAV's own path it freezes the process")


trust(False)
frame.Destroy()
app.Yield()
print()
print("%d/%d checks passed" % (passed, passed + failed))
sys.exit(1 if failed else 0)
