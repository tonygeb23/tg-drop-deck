"""Does streaming make the sound card stutter.

Users reported skips and stutters. The stream quality checker renders by hand
and found nothing, which rules out the encoder and the socket but not the one
thing it cannot see: a real sound card calls back into Python on a deadline,
and the encoder is a Python thread. If the encoder holds the interpreter when
the callback is due, the card runs dry and the presenter hears a click.

sounddevice reports that as a status flag on the callback, which the mixer
counts as an underrun. So this opens a REAL output stream and counts them,
first with nothing else running and then with a full stream going out, and
compares.

An underrun here is not a stream problem. It is a hole in what comes out of
the speakers, on air, in the room.

    python tools/check_glitches.py [seconds]

Makes noise. It plays a quiet tone through the default output.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="dd-glitch-"))

import numpy as np

from dropdeck import constants as C
from dropdeck import streamout
from dropdeck.engine import CHANNELS
from dropdeck.mixer import Mixer
from dropdeck.streamout import AirBus, Streamer
from mock_icecast import MockServer

FAILED = []


def say(label, ok, detail=""):
    if not ok:
        FAILED.append(label)
    print(("  ok   " if ok else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" else ""), flush=True)


def tone(frames, rate, freq=440.0, level=0.15):
    t = np.arange(frames) / float(rate)
    wave = (level * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.repeat(wave[:, None], CHANNELS, axis=1)


def measure(seconds, streaming, fmt="mp3", bitrate=128):
    """Underruns over a real output stream, with or without a stream going."""
    mixer = Mixer(open_stream=True)
    if mixer.stream is None:
        print("  no output device available, cannot measure")
        return None, None
    rate = mixer.samplerate
    server = streamer = bus = None
    if streaming:
        server = MockServer(password="hackme")
        bus = AirBus(rate)
        mixer.air_tap = bus
        streamer = Streamer(bus, {
            "server": "icecast", "host": "127.0.0.1", "port": server.port,
            "mount": "/live", "user": "source", "password": "hackme",
            "format": fmt, "bitrate": bitrate, "name": "Glitch check"})
        streamer.start()
        time.sleep(2)

    mixer.underruns = 0
    mixer.play_samples(0, tone(int(rate * (seconds + 2)), rate), bus=C.BUS_SFX)
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(0.05)
    underruns = mixer.underruns
    dropped = bus.dropped if bus is not None else 0
    state = streamer.state if streamer is not None else "off"

    if streamer is not None:
        streamer.stop()
    mixer.stop_all(fade_out=0.0)
    time.sleep(0.2)
    mixer.close()
    if server is not None:
        server.close()
    return underruns, (dropped, state)


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    print("Playing a quiet tone through the default output for %.0f seconds "
          "each way.\n" % seconds)

    print("Nothing streaming")
    quiet, _ = measure(seconds, streaming=False)
    if quiet is None:
        return 2
    say("the sound card keeps up on its own", quiet == 0,
        "%d underruns" % quiet)

    for fmt, bitrate in (("mp3", 128), ("mp3", 320), ("aac", 128),
                         ("opus", 128)):
        print("\nStreaming %s at %d" % (fmt, bitrate))
        loud, extra = measure(seconds, streaming=True, fmt=fmt,
                              bitrate=bitrate)
        dropped, state = extra
        say("it was actually on air while measuring", state == "on air", state)
        say("streaming %s does not make the card stutter" % fmt,
            loud <= quiet, "%d underruns, was %d with nothing streaming"
            % (loud, quiet))
        say("and nothing was dropped from the stream either", dropped == 0,
            "%d blocks" % dropped)

    print("\n%s" % ("FAILED %d" % len(FAILED) if FAILED else "all good"))
    for label in FAILED:
        print("  still wrong:", label)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
