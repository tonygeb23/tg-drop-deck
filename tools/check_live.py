"""Connect to a real station and prove the whole chain, once.

Everything else about streaming is tested against a mock. This is the one run
that talks to a real server, because a mock cannot prove that a real Icecast
or a real Liquidsoap harbor accepts what we send.

It streams REAL AUDIO, a music bed out of the demo pack, rather than a test
tone. On a station whose live mount takes over from the automation, whatever
this sends is what listeners hear, and thirty seconds of sine wave is a worse
thing to do to an audience than thirty seconds of music.

    set DROPDECK_STREAM_HOST=radio.example.com
    set DROPDECK_STREAM_PORT=8001
    set DROPDECK_STREAM_MOUNT=/live
    set DROPDECK_STREAM_PASSWORD=...
    python tools/check_live.py [seconds]

The password only ever comes from the environment. Nothing here writes it
anywhere, prints it, or puts it in a URL that could end up in a log.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="dd-live-"))

import numpy as np

from dropdeck import audiofile
from dropdeck import constants as C
from dropdeck import streamout
from dropdeck.engine import CHANNELS
from dropdeck.mixer import Mixer

RATE = 44100
FAILED = []


def say(label, ok, extra=None):
    if not ok:
        FAILED.append(label)
    print(("  ok   " if ok else "  FAIL ") + label
          + (("  " + str(extra)) if extra is not None else ""), flush=True)


def demo_audio(seconds):
    """A music bed from the demo pack, so listeners get music not a tone."""
    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "demo")
    for folder, _dirs, files in os.walk(root):
        for name in sorted(files):
            if not audiofile.is_supported(os.path.join(folder, name)):
                continue
            try:
                data, rate = audiofile.read_all(os.path.join(folder, name))
            except Exception:
                continue
            if data is None or not len(data):
                continue
            if data.ndim == 1:
                data = np.repeat(data[:, None], CHANNELS, axis=1)
            if rate != RATE:
                # The mixer here runs at 44.1k, so anything else would go out
                # at the wrong speed. Linear is fine for a connection test.
                want = int(len(data) * RATE / float(rate))
                idx = np.linspace(0, len(data) - 1, want)
                data = np.stack([np.interp(idx, np.arange(len(data)), data[:, c])
                                 for c in range(data.shape[1])], axis=1
                                ).astype(np.float32)
            want = int(RATE * seconds)
            while len(data) < want:
                data = np.concatenate((data, data))
            return data[:want], name
    return None, None


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    host = os.environ.get("DROPDECK_STREAM_HOST", "")
    password = os.environ.get("DROPDECK_STREAM_PASSWORD", "")
    if not host or not password:
        print("Set DROPDECK_STREAM_HOST and DROPDECK_STREAM_PASSWORD first.")
        return 2

    settings = {
        "server": os.environ.get("DROPDECK_STREAM_SERVER", "icecast"),
        "host": host,
        "port": int(os.environ.get("DROPDECK_STREAM_PORT", "8000")),
        "mount": os.environ.get("DROPDECK_STREAM_MOUNT", "/live"),
        "user": os.environ.get("DROPDECK_STREAM_USER", "source"),
        "password": password,
        "format": os.environ.get("DROPDECK_STREAM_FORMAT", "mp3"),
        "bitrate": int(os.environ.get("DROPDECK_STREAM_BITRATE", "128")),
        "name": "TG Drop Deck",
    }
    print("Streaming %s to %s:%d%s for %.0f seconds"
          % (settings["format"], settings["host"], settings["port"],
             settings["mount"], seconds), flush=True)

    audio, name = demo_audio(seconds + 2)
    say("there is real audio to send, rather than a test tone",
        audio is not None, name)
    if audio is None:
        return 1

    mixer = Mixer(open_stream=False, samplerate=RATE)
    bus = streamout.AirBus(RATE)
    mixer.air_tap = bus
    states = []
    streamer = streamout.Streamer(
        bus, settings, on_state=lambda s, d: states.append((s, d)))
    streamer.start()

    mixer.play_samples(0, audio, bus=C.BUS_SFX)
    started = time.time()
    made = [0]

    def pace(until):
        """Render at exactly the speed a sound card would.

        This matters more than it looks. Rendering in a tight loop produces
        audio faster than real time, the encoder faithfully encodes all of it,
        and the stream goes out at several times the bitrate that was asked
        for. The first run of this test sent 321 kbps when it had been told
        128, which was the harness running fast and not the app: in the app
        the sound card is the clock and there is no way to run ahead of it.
        """
        while time.time() < until:
            want = int((time.time() - started) * RATE) - made[0]
            if want >= 512:
                block = min(want, 4096) // 512 * 512
                mixer.render(block)
                made[0] += block
            else:
                time.sleep(0.002)

    while time.time() - started < 4 and streamer.state == streamout.CONNECTING:
        pace(time.time() + 0.05)
    say("the real server accepted the connection",
        streamer.state == streamout.ON_AIR,
        streamer.state if streamer.state == streamout.ON_AIR
        else "%s: %s" % (streamer.state, streamer.error))
    if streamer.state != streamout.ON_AIR:
        streamer.stop()
        mixer.close()
        return 1

    # The title, checked rather than assumed. A real Liquidsoap harbor
    # answers "Updated metadatas for mount /live" to this; a server that does
    # not take metadata at all says so here rather than silently doing
    # nothing, which is how a station ends up showing the wrong track all
    # night.
    streamer.set_title("TG Drop Deck - connection test")
    pace(started + min(seconds, 4))
    sink = streamer._sink
    say("the server took the track title, so listeners see what is playing",
        sink is not None and sink.send_metadata("TG Drop Deck - on air"))
    pace(started + seconds)

    say("it stayed on air for the whole run",
        streamer.state == streamout.ON_AIR, streamer.state)
    say("audio really went out",
        streamer.bytes_sent > 1000 * seconds,
        "%.0f kB in %.0f s" % (streamer.bytes_sent / 1000.0, seconds))
    expected = settings["bitrate"] * 1000 / 8.0 * seconds
    say("at about the bitrate that was asked for, which is also the proof "
        "that it runs at real time rather than as fast as it can",
        0.75 * expected < streamer.bytes_sent < 1.25 * expected,
        "%.0f kbps" % (streamer.bytes_sent * 8 / seconds / 1000.0))
    say("and it sent about the right amount of audio for the time it ran",
        abs(made[0] / float(RATE) - seconds) < 1.0,
        "%.1f s of audio in %.0f s" % (made[0] / float(RATE), seconds))
    say("nothing was dropped, so listeners heard it whole",
        bus.dropped == 0, bus.dropped)
    say("and it never had to reconnect", streamer.reconnects == 0,
        streamer.reconnects)

    streamer.stop()
    mixer.stop_all(fade_out=0.0)
    mixer.close()
    say("coming off air is clean", streamer.state == streamout.OFF,
        streamer.state)
    print("  states:", [s for s, _d in states], flush=True)
    print(("FAILED %d" % len(FAILED)) if FAILED else "all good", flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
