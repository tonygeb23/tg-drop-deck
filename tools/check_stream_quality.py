"""Does the outgoing stream actually arrive whole.

Users reported skips and stutters. "It connects and audio arrives" is not the
same claim as "every sample that was played reached the listener in order",
and only the second one is worth anything on a live show.

So this plays a known continuous tone at REAL TIME through the real mixer,
streams it through the real encoder and socket, then decodes what the server
received and asks two questions that a dropout cannot survive:

  * **Is it all there?** Count the decoded samples against the samples played.
    A quarter second dropped on the way out is eleven thousand samples that
    never arrive, and no amount of "the bitrate looked right" hides that.

  * **Is it in one piece?** A sine fitted to the first second predicts every
    sample after it. Drop a block and everything downstream shifts phase, the
    prediction stops matching, and the error stays high for the rest of the
    run. Codec noise moves this a little; a dropout moves it off the scale.

Real time matters. Rendering in a tight loop produces audio faster than a
sound card would, the encoder faithfully encodes all of it, and everything
downstream looks fine while measuring nothing.

    python tools/check_stream_quality.py            the full sweep
    python tools/check_stream_quality.py --quick    one format, for iterating
"""
import os
import io
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="dd-quality-"))

import av
import numpy as np

from dropdeck import constants as C
from dropdeck import streamout
from dropdeck.engine import CHANNELS
from dropdeck.mixer import Mixer
from dropdeck.streamout import AirBus, Streamer
from mock_icecast import MockServer

RATE = 44100
TONE = 440.0
FAILED = []
CONTAINER = {"mp3": "mp3", "aac": "adts", "opus": "ogg"}


def say(label, ok, detail=""):
    if not ok:
        FAILED.append(label)
    print(("    ok   " if ok else "    FAIL ") + label
          + (("  " + str(detail)) if detail != "" else ""), flush=True)


def tone(frames, start=0, rate=RATE, level=0.4):
    t = (np.arange(start, start + frames) / float(rate))
    wave = (level * np.sin(2 * np.pi * TONE * t)).astype(np.float32)
    return np.repeat(wave[:, None], CHANNELS, axis=1)


def decode(data, container):
    try:
        with av.open(io.BytesIO(bytes(data)), format=container) as inp:
            rate = inp.streams.audio[0].codec_context.sample_rate
            out = [f.to_ndarray().T.astype(np.float32)
                   for f in inp.decode(audio=0)]
        if not out:
            return np.zeros((0, CHANNELS), dtype=np.float32), 0
        samples = np.concatenate(out)
        if samples.ndim == 1:
            samples = samples[:, None]
        return samples, rate
    except Exception as exc:
        print("      decode failed: %s" % exc)
        return np.zeros((0, CHANNELS), dtype=np.float32), 0


def continuity(samples, rate):
    """How well a sine fitted to the start predicts the rest.

    Returns the worst normalised error found in any later window. A stream
    that arrived whole tracks its own prediction all the way through; one
    with a block missing shifts phase at the gap and never recovers.
    """
    mono = samples[:, 0]
    if len(mono) < rate * 2:
        return 1.0
    # Skip the codec's priming samples at the very start.
    head = mono[rate // 2:rate + rate // 2]
    n = np.arange(len(head))
    # Least squares fit of a sine at the known frequency: solve for the
    # in-phase and quadrature amplitudes, which gives amplitude and phase.
    w = 2 * np.pi * TONE / rate
    basis = np.stack([np.cos(w * n), np.sin(w * n)], axis=1)
    coeffs, *_ = np.linalg.lstsq(basis, head, rcond=None)
    amplitude = float(np.hypot(*coeffs))
    if amplitude < 1e-3:
        return 1.0
    start = rate // 2
    worst = 0.0
    window = rate // 2
    for begin in range(start, len(mono) - window, window):
        idx = np.arange(begin - start, begin - start + window)
        predicted = (coeffs[0] * np.cos(w * idx) + coeffs[1] * np.sin(w * idx))
        actual = mono[begin:begin + window]
        error = float(np.sqrt(np.mean((actual - predicted) ** 2))) / amplitude
        worst = max(worst, error)
    return worst


def run(fmt, bitrate, seconds, slow_after=None, label=None):
    """One real time run, start to finish, and everything it can be asked."""
    title = label or "%s at %d kbps" % (streamout.FORMATS[fmt]["label"], bitrate)
    print("\n  %s" % title, flush=True)
    with MockServer(password="hackme", stall_after=slow_after) as server:
        mixer = Mixer(open_stream=False, samplerate=RATE)
        bus = AirBus(RATE)
        mixer.air_tap = bus
        streamer = Streamer(bus, {
            "server": "icecast", "host": "127.0.0.1", "port": server.port,
            "mount": "/live", "user": "source", "password": "hackme",
            "format": fmt, "bitrate": bitrate, "name": "Quality check"})
        streamer.start()
        mixer.play_samples(0, tone(int(RATE * (seconds + 3))), bus=C.BUS_SFX)

        started = time.time()
        made = [0]

        def pace(until):
            """Exactly the rate a sound card would produce, no faster."""
            while time.time() < until:
                want = int((time.time() - started) * RATE) - made[0]
                if want >= 512:
                    block = min(want, 4096) // 512 * 512
                    mixer.render(block)
                    made[0] += block
                else:
                    time.sleep(0.002)

        while time.time() - started < 5 and streamer.state == streamout.CONNECTING:
            pace(time.time() + 0.05)
        if streamer.state != streamout.ON_AIR:
            say("%s: connects" % title, False, streamer.error)
            streamer.stop(); mixer.close()
            return
        pace(started + seconds)
        played = made[0]
        streamer.stop()
        mixer.stop_all(fade_out=0.0)
        mixer.close()

        samples, rate = decode(server.body, CONTAINER[fmt])
        # Opus runs at 48k, so compare in seconds rather than samples.
        sent_seconds = played / float(RATE)
        got_seconds = len(samples) / float(rate) if rate else 0.0
        missing = sent_seconds - got_seconds

        say("%s: nothing was dropped on the way out" % title,
            bus.dropped == 0, "%d blocks" % bus.dropped)
        say("%s: it never had to reconnect" % title,
            streamer.reconnects == 0, streamer.reconnects)
        say("%s: every second played arrived" % title,
            abs(missing) < 0.12,
            "played %.2fs, received %.2fs, missing %.3fs"
            % (sent_seconds, got_seconds, missing))
        kbps = server_kbps = len(server.body) * 8 / max(0.01, got_seconds) / 1000
        say("%s: at the bitrate asked for" % title,
            0.7 * bitrate < kbps < 1.4 * bitrate, "%.0f kbps" % server_kbps)
        worst = continuity(samples, rate)
        say("%s: and it arrived in one piece" % title,
            worst < 0.45, "worst window error %.3f" % worst)


def main():
    quick = "--quick" in sys.argv
    print("Every run is paced to real time. A sweep takes a few minutes.")

    print("\n=== Formats, at the default bitrate ===")
    for fmt in (("mp3",) if quick else ("mp3", "aac", "opus")):
        run(fmt, 128, 12)

    if not quick:
        print("\n=== MP3 across every bitrate offered ===")
        for bitrate in C.STREAM_BITRATES:
            run("mp3", bitrate, 8)

        print("\n=== A longer run, for anything that only shows up with time ===")
        run("mp3", 192, 45, label="MP3 192, 45 seconds")

        print("\n=== A server that stops reading part way through ===")
        run("mp3", 128, 25, slow_after=40000,
            label="MP3 128 with a stalled receiver")

    print("\n%s" % ("FAILED %d" % len(FAILED) if FAILED else "all good"))
    for label in FAILED:
        print("  still wrong:", label)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
