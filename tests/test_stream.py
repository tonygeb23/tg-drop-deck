"""Streaming the show to an Icecast or SHOUTcast server.

Tony, 4 September 2026: "how do we add the ability to stream audio from the
program as a whole to an encoder for ogg or mp3 for ice cast, custom rmtp or
whatever it's called".

Nothing here talks to a real station. `tools/mock_icecast.py` speaks both
source protocols and keeps what it is sent, so a test can go and DECODE what
arrived and check it is the audio that was played, rather than checking that
some bytes moved. A stream that connects and sends silence is the failure that
matters, and only decoding catches it.

No sound card is opened. Mixer takes ``open_stream=False`` and render() is
called by hand, which is also how the audio callback would call it.

    python tests/test_stream.py
"""

import io
import json
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-stream-test-")

import av

from dropdeck import constants as C
from dropdeck import streamout
from dropdeck.engine import CHANNELS
from dropdeck.micinput import MicInput
from dropdeck.mixer import Mixer
from dropdeck.streamout import AirBus, Encoder, Streamer
from mock_icecast import MockServer

CHECKS = []
RATE = 44100


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


def tone(frames, freq=440.0, rate=RATE, level=0.4, start=0):
    t = (np.arange(start, start + frames) / float(rate))
    wave = (level * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.repeat(wave[:, None], CHANNELS, axis=1)


def goertzel(samples, freq, rate=RATE):
    """How much of one frequency is in a block. Cheap and exact enough.

    Used rather than a full FFT because the question is only ever "is the note
    that was played the note that came out", and this answers precisely that.
    """
    n = len(samples)
    if not n:
        return 0.0
    k = int(0.5 + n * freq / rate)
    w = 2.0 * np.pi * k / n
    coeff = 2.0 * np.cos(w)
    s_prev = s_prev2 = 0.0
    for sample in samples:
        s = sample + coeff * s_prev - s_prev2
        s_prev2, s_prev = s_prev, s
    power = s_prev2 ** 2 + s_prev ** 2 - coeff * s_prev * s_prev2
    return float(np.sqrt(max(0.0, power)) / n)


def decode(data, container="mp3"):
    """Turn what the server received back into samples."""
    try:
        with av.open(io.BytesIO(bytes(data)), format=container) as inp:
            out = []
            for frame in inp.decode(audio=0):
                out.append(frame.to_ndarray().T.astype(np.float32))
            if not out:
                return np.zeros((0, CHANNELS), dtype=np.float32), 0
            samples = np.concatenate(out)
            if samples.ndim == 1:
                samples = samples[:, None]
            return samples, inp.streams.audio[0].codec_context.sample_rate
    except Exception as exc:
        print("     decode failed:", exc)
        return np.zeros((0, CHANNELS), dtype=np.float32), 0


def settings(port, **extra):
    base = {"server": "icecast", "host": "127.0.0.1", "port": port,
            "mount": "/live", "user": "source", "password": "hackme",
            "format": "mp3", "bitrate": 128, "name": "Test"}
    base.update(extra)
    return base


def pump(mixer, bus, seconds, block=512, rate=RATE):
    """Run the audio callback by hand, as a sound card would."""
    for _ in range(int(rate * seconds / block)):
        mixer.render(block)


# ---------------------------------------------------------------------------
print("\nThe encoder")
# ---------------------------------------------------------------------------

got = bytearray()
enc = Encoder(got.extend, fmt="mp3", samplerate=RATE, bitrate=128)
for i in range(80):
    enc.feed(tone(1024, 440.0, start=i * 1024))
enc.close()
check("MP3 comes out of it", len(got) > 4000, "%d bytes" % len(got))
check("as raw frames, with no ID3 tag and no file header",
      bytes(got[:2]) != b"ID", bytes(got[:4]))
samples, rate = decode(got)
check("and it decodes back to audio", len(samples) > 20000, len(samples))
check("at the rate it was given", rate == RATE, rate)
check("and it is the note that went in",
      goertzel(samples[RATE // 2:RATE // 2 + 4096, 0], 440.0) > 0.05,
      round(goertzel(samples[RATE // 2:RATE // 2 + 4096, 0], 440.0), 4))
check("and not one that did not",
      goertzel(samples[RATE // 2:RATE // 2 + 4096, 0], 1500.0) < 0.01,
      round(goertzel(samples[RATE // 2:RATE // 2 + 4096, 0], 1500.0), 4))

got_opus = bytearray()
enc = Encoder(got_opus.extend, fmt="opus", samplerate=RATE, bitrate=128)
check("Ogg Opus asks for 48k, because that is the only rate it has",
      enc.samplerate == 48000, enc.samplerate)
for i in range(60):
    enc.feed(tone(960, 440.0, rate=48000, start=i * 960))
enc.close()
check("and Ogg comes out", bytes(got_opus[:4]) == b"OggS", bytes(got_opus[:4]))

# ---------------------------------------------------------------------------
print("\nThe ring between the sound card and the encoder")
# ---------------------------------------------------------------------------

bus = AirBus(RATE, seconds=0.5)
bus.write("card", tone(1024))
check("what goes in comes out", bus.available() == 1024, bus.available())
back = bus.read(1024)
check("with the samples intact", np.allclose(back, tone(1024), atol=1e-6))
check("and reading takes it away", bus.available() == 0)

bus.write("a", tone(512, 440.0))
bus.write("b", tone(512, 440.0))
summed = bus.read(512)
check("two sound cards are summed, so a bank sent elsewhere still goes out",
      np.allclose(summed, tone(512) * 2, atol=1e-6))

bus.reset()
for _ in range(200):
    bus.write("card", tone(1024))
check("a ring that overflows drops audio rather than blocking the callback",
      bus.dropped > 0, bus.dropped)
check("and it never grows past its size",
      bus.available() <= int(RATE * 0.5), bus.available())

short = AirBus(RATE, seconds=0.5)
short.write("a", tone(1024))
mixed = short.read(1024)
check("a card that has not ticked yet contributes silence, not a stall",
      mixed.shape == (1024, CHANNELS))

# ---------------------------------------------------------------------------
print("\nWhat actually goes on air")
# ---------------------------------------------------------------------------

mixer = Mixer(open_stream=False, samplerate=RATE)
bus = AirBus(RATE)
mixer.air_tap = bus
mixer.play_samples(0, tone(RATE * 2, 440.0), bus=C.BUS_SFX)
mixer.render(1024)
check("a sound effect reaches the stream", bus.available() > 0, bus.available())

bus.reset()
mixer.stop_all(fade_out=0.0)
mixer.render(1024)
bus.reset()
mixer.play_samples(C.PREVIEW_SLOT, tone(RATE, 880.0), bus=C.BUS_PREVIEW)
mixer.render(1024)
heard = bus.read(1024)
check("previewing a sound does NOT, because that is the presenter hunting "
      "for one and a listener should not hear it",
      float(np.abs(heard).max()) < 1e-6, float(np.abs(heard).max()))

bus.reset()
mixer.stop_all(fade_out=0.0)
mixer.render(1024)
bus.reset()
mixer.play_samples(C.CUE_SLOT, tone(RATE, 1000.0), bus=C.BUS_CUE)
mixer.render(1024)
heard = bus.read(1024)
check("nor does the pip that warns a track is ending",
      float(np.abs(heard).max()) < 1e-6, float(np.abs(heard).max()))

mixer.stop_all(fade_out=0.0)
mixer.render(1024)
bus.reset()
mixer.play_samples(1, tone(RATE, 440.0), bus=C.BUS_SFX)
mixer.play_samples(C.PREVIEW_SLOT, tone(RATE, 880.0), bus=C.BUS_PREVIEW)
out = mixer.render(4096)
air = bus.read(4096)
check("with both playing, the speakers get the preview",
      goertzel(out[:4096, 0], 880.0) > 0.02,
      round(goertzel(out[:4096, 0], 880.0), 4))
check("and the stream gets only the sound effect",
      goertzel(air[:4096, 0], 440.0) > 0.02
      and goertzel(air[:4096, 0], 880.0) < 0.005,
      (round(goertzel(air[:4096, 0], 440.0), 4),
       round(goertzel(air[:4096, 0], 880.0), 4)))
mixer.stop_all(fade_out=0.0)
mixer.close()

# ---------------------------------------------------------------------------
print("\nThe microphone, which was never in the mix before")
# ---------------------------------------------------------------------------

mic = MicInput(samplerate=RATE)
check("hearing yourself and being heard start as separate things",
      mic.monitor is False and mic.on_air is False)


class FakeMic:
    """Stands in for a microphone, because a test cannot open one."""

    def __init__(self):
        self.monitor_reads = 0
        self.air_reads = 0

    def read(self, frames):
        self.monitor_reads += 1
        return tone(frames, 300.0)

    def read_air(self, frames):
        self.air_reads += 1
        return tone(frames, 300.0)


mixer = Mixer(open_stream=False, samplerate=RATE)
bus = AirBus(RATE)
fake = FakeMic()
mixer.air_tap = bus
mixer.air_source = fake
mixer.render(2048)
air = bus.read(2048)
check("the microphone goes out on the stream",
      goertzel(air[:2048, 0], 300.0) > 0.02,
      round(goertzel(air[:2048, 0], 300.0), 4))
check("read through a tap of its own, not the monitor's",
      fake.air_reads > 0 and fake.monitor_reads == 0,
      (fake.air_reads, fake.monitor_reads))
mixer.close()

mic = MicInput(samplerate=RATE)
mic.monitor = False
mic.on_air = True
check("with monitoring off, the air tap still asks for audio",
      mic.read_air(512).shape == (512, CHANNELS))
check("and the monitor gives silence, because nobody is listening",
      float(np.abs(mic.read(512)).max()) == 0.0)

# ---------------------------------------------------------------------------
print("\nEnd to end, against a server that keeps what it is sent")
# ---------------------------------------------------------------------------

with MockServer(password="hackme") as server:
    mixer = Mixer(open_stream=False, samplerate=RATE)
    bus = AirBus(RATE)
    mixer.air_tap = bus
    states = []
    streamer = Streamer(bus, settings(server.port),
                        on_state=lambda s, d: states.append(s))
    streamer.start()
    mixer.play_samples(0, tone(RATE * 6, 440.0), bus=C.BUS_SFX)
    deadline = time.time() + 12
    while time.time() < deadline and len(server.body) < 24000:
        mixer.render(512)
        time.sleep(0.004)
    check("it connects", streamer.state == streamout.ON_AIR,
          "%s %s" % (streamer.state, streamer.error))
    check("using the SOURCE method, which every Icecast understands",
          server.method == "SOURCE", server.method)
    check("to the mount it was given", server.mount == "/live", server.mount)
    check("saying what the audio is, so players know what to do with it",
          server.headers.get("content-type") == "audio/mpeg",
          server.headers.get("content-type"))
    check("and audio arrives", len(server.body) > 8000, len(server.body))

    streamer.set_title("Tony Gebhard - Test Track")
    time.sleep(0.6)
    for _ in range(80):
        mixer.render(512)
        time.sleep(0.004)
    check("the title reaches the server, so listeners see what is playing",
          any("updinfo" in m for m in server.metadata), server.metadata[:1])

    streamer.stop()
    check("stopping comes off air", streamer.state == streamout.OFF,
          streamer.state)
    mixer.stop_all(fade_out=0.0)
    mixer.close()

    samples, rate = decode(server.body)
    check("what the server received decodes back to audio",
          len(samples) > RATE, len(samples))
    check("at the right rate", rate == RATE, rate)
    middle = samples[len(samples) // 3:len(samples) // 3 + 8192, 0]
    check("and it is the sound that was played, not silence",
          goertzel(middle, 440.0) > 0.02, round(goertzel(middle, 440.0), 4))
    check("the states said out loud are the ones that happened",
          states[0] == streamout.CONNECTING and streamout.ON_AIR in states,
          states)

# ---------------------------------------------------------------------------
print("\nSHOUTcast, which does it differently")
# ---------------------------------------------------------------------------

with MockServer(password="hackme", kind="shoutcast") as server:
    # A SHOUTcast source connects one above the listening port, so the port
    # given here is deliberately one BELOW where the server is listening.
    mixer = Mixer(open_stream=False, samplerate=RATE)
    bus = AirBus(RATE)
    mixer.air_tap = bus
    streamer = Streamer(bus, settings(server.port - 1,
                                      server="shoutcast"))
    streamer.start()
    mixer.play_samples(0, tone(RATE * 4, 660.0), bus=C.BUS_SFX)
    deadline = time.time() + 12
    while time.time() < deadline and len(server.body) < 16000:
        mixer.render(512)
        time.sleep(0.004)
    check("the listening port plus one is worked out for the user",
          streamer.state == streamout.ON_AIR,
          "%s %s" % (streamer.state, streamer.error))
    check("the headers go in the older style",
          server.headers.get("icy-br") == "128", server.headers.get("icy-br"))
    check("and audio arrives", len(server.body) > 8000, len(server.body))
    streamer.stop()
    mixer.stop_all(fade_out=0.0)
    mixer.close()
    samples, _rate = decode(server.body)
    middle = samples[len(samples) // 3:len(samples) // 3 + 8192, 0]
    check("and it decodes back to what was played",
          goertzel(middle, 660.0) > 0.02, round(goertzel(middle, 660.0), 4))

# ---------------------------------------------------------------------------
print("\nWhen it goes wrong, which is the part that matters")
# ---------------------------------------------------------------------------

with MockServer(password="right") as server:
    bus = AirBus(RATE)
    streamer = Streamer(bus, settings(server.port,
                                      password="wrong"))
    streamer.start()
    deadline = time.time() + 10
    while time.time() < deadline and streamer.state not in (streamout.FAILED,):
        time.sleep(0.05)
    check("a wrong password stops rather than retrying forever",
          streamer.state == streamout.FAILED, streamer.state)
    check("and says so in words, not a number",
          "password" in streamer.error, streamer.error)
    streamer.stop()

bus = AirBus(RATE)
streamer = Streamer(bus, settings(9))     # nothing listens on 9
streamer.start()
deadline = time.time() + 8
while time.time() < deadline and streamer.state != streamout.RECONNECTING:
    time.sleep(0.05)
check("a server that is not there is retried, because it might come back",
      streamer.state == streamout.RECONNECTING, streamer.state)
check("and the reason names the host and the port",
      "could not reach" in streamer.error, streamer.error)
streamer.stop()
check("and stopping while it is retrying still stops",
      streamer.state == streamout.OFF and not streamer.running)

with MockServer(password="hackme", drop_after=6000) as server:
    mixer = Mixer(open_stream=False, samplerate=RATE)
    bus = AirBus(RATE)
    mixer.air_tap = bus
    streamer = Streamer(bus, settings(server.port))
    streamer.start()
    mixer.play_samples(0, tone(RATE * 8, 440.0), bus=C.BUS_SFX)
    # The backoff means the second connection is a couple of seconds after
    # the drop is noticed, so this waits for the connection rather than for
    # the counter, which was a race the first time it was written.
    deadline = time.time() + 25
    while time.time() < deadline and server.connections < 2:
        mixer.render(512)
        time.sleep(0.004)
    check("a connection that drops mid show comes back on its own",
          streamer.reconnects >= 1, streamer.reconnects)
    check("and the server really saw it connect again",
          server.connections >= 2, server.connections)
    check("without anybody having to press anything",
          streamer.state in (streamout.ON_AIR, streamout.RECONNECTING),
          streamer.state)
    streamer.stop()
    mixer.stop_all(fade_out=0.0)
    mixer.close()

# ---------------------------------------------------------------------------
print("\nThe show comes first")
# ---------------------------------------------------------------------------

mixer = Mixer(open_stream=False, samplerate=RATE)
bus = AirBus(RATE, seconds=0.2)
mixer.air_tap = bus
mixer.play_samples(0, tone(RATE * 3, 440.0), bus=C.BUS_SFX)
# Nothing is draining the ring, which is what a dead network looks like.
blocks = [mixer.render(1024) for _ in range(60)]
check("a stream nobody is draining fills up and drops",
      bus.dropped > 0, bus.dropped)
check("and the audio going to the speakers is untouched by that",
      all(float(np.abs(b).max()) > 0.05 for b in blocks[:40]))
check("every block is still full length",
      all(len(b) == 1024 for b in blocks))
mixer.stop_all(fade_out=0.0)
mixer.close()

mixer = Mixer(open_stream=False, samplerate=RATE)
mixer.play_samples(0, tone(1024, 440.0), bus=C.BUS_SFX)
plain = mixer.render(1024)
check("with no stream at all, render costs nothing extra and still works",
      mixer.air_tap is None and float(np.abs(plain).max()) > 0.05)
mixer.stop_all(fade_out=0.0)
mixer.close()


class BadTap:
    def write(self, key, block):
        raise RuntimeError("the tap exploded")


mixer = Mixer(open_stream=False, samplerate=RATE)
mixer.air_tap = BadTap()
mixer.play_samples(0, tone(1024, 440.0), bus=C.BUS_SFX)
out = mixer.render(1024)
check("and a tap that throws does not take the show down",
      float(np.abs(out).max()) > 0.05)
mixer.stop_all(fade_out=0.0)
mixer.close()



# ---------------------------------------------------------------------------
print("\nThe playlist fader is a monitor fader")
# ---------------------------------------------------------------------------

# Tony, 4 September 2026: "if I adjust playlist volume, can you only have it
# adjust like a monitor, it still plays out at 100% to the stream. just so we
# can adjust our volume for output for the program so we can hear our screen
# readers and navigate."
#
# This is what a fader on a desk does, and it is the only way to turn the
# music down enough to hear a screen reader without taking it off the air.


def settle(mixer, bus, frames=8192, block=1024):
    """Run past the glide, then measure a block. The fader walks to its new
    level over VOLUME_GLIDE rather than jumping, so measuring the first block
    after a change measures the ramp and not the level."""
    for _ in range(frames // block):
        mixer.render(block)
    bus.reset()
    out = mixer.render(block)
    return out, bus.read(block)


mixer = Mixer(open_stream=False, samplerate=RATE)
bus = AirBus(RATE)
mixer.air_tap = bus
mixer.set_playlist_gain(1.0)
mixer.play_samples(C.PLAYLIST_SLOT if hasattr(C, "PLAYLIST_SLOT") else 70,
                   tone(RATE * 30, 440.0), bus=C.BUS_PLAYLIST)
heard, air = settle(mixer, bus)
full_heard = float(np.abs(heard).max())
full_air = float(np.abs(air).max())
check("at full, what you hear and what goes out are the same",
      abs(full_heard - full_air) < 0.01, (round(full_heard, 3),
                                          round(full_air, 3)))

mixer.set_playlist_gain(0.25)
heard, air = settle(mixer, bus)
quiet_heard = float(np.abs(heard).max())
quiet_air = float(np.abs(air).max())
check("turning it down turns down what you hear",
      quiet_heard < full_heard * 0.4, round(quiet_heard, 3))
check("and does NOT turn down what goes out",
      abs(quiet_air - full_air) < 0.01, round(quiet_air, 3))
check("the ratio is the fader, so it is the fader doing it and not a fade",
      0.2 < quiet_heard / max(1e-9, quiet_air) < 0.3,
      round(quiet_heard / max(1e-9, quiet_air), 3))

# The case that rules out the lazy implementation. Scaling the on air block
# back up by one over the fader looks equivalent and is not: at zero there is
# nothing left to scale.
mixer.set_playlist_gain(0.0)
heard, air = settle(mixer, bus)
check("with the fader shut, you hear nothing",
      float(np.abs(heard).max()) < 1e-4, float(np.abs(heard).max()))
check("and the listener still gets it at full level",
      abs(float(np.abs(air).max()) - full_air) < 0.01,
      round(float(np.abs(air).max()), 3))
check("which is the whole point: turn the music right down, stay on air",
      goertzel(air[:1024, 0], 440.0) > 0.02,
      round(goertzel(air[:1024, 0], 440.0), 4))

mixer.set_playlist_gain(0.8)
mixer.playlist_monitor_only = False
heard, air = settle(mixer, bus)
check("turned off, it goes back to an ordinary fader",
      abs(float(np.abs(heard).max()) - float(np.abs(air).max())) < 0.01,
      (round(float(np.abs(heard).max()), 3), round(float(np.abs(air).max()), 3)))
mixer.playlist_monitor_only = True
mixer.stop_all(fade_out=0.0)
mixer.render(512)

# It is only the playlist. A sound effect fader is a real fader, because a
# drop you fire at half level is one you meant to fire at half level.
bus.reset()
mixer.set_sfx_gain(0.3)
mixer.play_samples(0, tone(RATE * 5, 660.0), bus=C.BUS_SFX)
heard, air = settle(mixer, bus)
check("the sound effects fader still changes both, as it always did",
      abs(float(np.abs(heard).max()) - float(np.abs(air).max())) < 0.01,
      (round(float(np.abs(heard).max()), 3), round(float(np.abs(air).max()), 3)))
mixer.stop_all(fade_out=0.0)
mixer.render(512)
mixer.close()

# And with nothing streaming at all, the fader behaves exactly as before.
mixer = Mixer(open_stream=False, samplerate=RATE)
mixer.set_playlist_gain(1.0)
mixer.play_samples(70, tone(RATE * 10, 440.0), bus=C.BUS_PLAYLIST)
for _ in range(8):
    mixer.render(1024)
loud = float(np.abs(mixer.render(1024)).max())
mixer.set_playlist_gain(0.25)
for _ in range(8):
    mixer.render(1024)
soft = float(np.abs(mixer.render(1024)).max())
check("off air, F7 and F8 turn the playlist down the way they always have",
      soft < loud * 0.4, (round(loud, 3), round(soft, 3)))
mixer.stop_all(fade_out=0.0)
mixer.close()

# The setting is remembered.
from dropdeck.board import Board            # noqa: E402

board = Board()
check("it is on out of the box, because that is what a desk does",
      board.playlist_monitor_only is True)
board.playlist_monitor_only = False
kept = os.path.join(tempfile.mkdtemp(), "fader.json")
board.save(kept)
check("and turning it off survives a save and a load",
      Board.load(kept).playlist_monitor_only is False)


# ---------------------------------------------------------------------------
print("\nAnd the same thing, all the way to the server")
# ---------------------------------------------------------------------------

# The check above proves the ring gets full level audio. This one takes the
# fader down to nothing halfway through a real encode and decodes what the
# server received, because the ring is not the thing listeners hear.

with MockServer(password="hackme") as server:
    mixer = Mixer(open_stream=False, samplerate=RATE)
    bus = AirBus(RATE)
    mixer.air_tap = bus
    mixer.set_playlist_gain(1.0)
    streamer = Streamer(bus, settings(server.port))
    streamer.start()
    mixer.play_samples(70, tone(RATE * 20, 440.0), bus=C.BUS_PLAYLIST)

    deadline = time.time() + 12
    while time.time() < deadline and len(server.body) < 12000:
        mixer.render(512)
        time.sleep(0.004)
    up_to = len(server.body)
    check("audio is arriving with the fader up", up_to > 8000, up_to)

    # All the way down, which is what you do to hear a screen reader.
    mixer.set_playlist_gain(0.0)
    heard = []
    deadline = time.time() + 12
    while time.time() < deadline and len(server.body) < up_to + 12000:
        heard.append(float(np.abs(mixer.render(512)).max()))
        time.sleep(0.004)
    check("the room goes quiet", max(heard[20:] or [1.0]) < 0.01,
          round(max(heard[20:] or [1.0]), 4))

    streamer.stop()
    mixer.stop_all(fade_out=0.0)
    mixer.close()

    samples, _rate = decode(server.body)
    check("and the server still received audio the whole time",
          len(samples) > RATE, len(samples))
    half = len(samples) // 2
    early = goertzel(samples[half // 2:half // 2 + 8192, 0], 440.0)
    late = goertzel(samples[-16384:-8192, 0], 440.0)
    check("at the same level before the fader moved and after it",
          early > 0.02 and late > 0.02 and abs(early - late) < early * 0.5,
          (round(early, 4), round(late, 4)))


# ---------------------------------------------------------------------------
print("\nAAC, because that is what broadcasters use")
# ---------------------------------------------------------------------------

# Brian Hartgen, 4 September 2026: "you may want to consider streaming using
# AAC, which is what we do."

check("AAC is on the list of formats", "aac" in streamout.FORMATS)
check("and it is offered in Preferences", "aac" in C.STREAM_FORMAT_ORDER,
      C.STREAM_FORMAT_ORDER)
got_aac = bytearray()
enc = Encoder(got_aac.extend, fmt="aac", samplerate=RATE, bitrate=128)
for i in range(120):
    enc.feed(tone(1024, 440.0, start=i * 1024))
enc.close()
check("it encodes", len(got_aac) > 8000, "%d bytes" % len(got_aac))
check("as ADTS, so a listener joining halfway through knows the rate",
      got_aac[0] == 0xFF and (got_aac[1] & 0xF0) == 0xF0,
      (hex(got_aac[0]), hex(got_aac[1])))
check("and it is announced to the server as audio/aac",
      streamout.FORMATS["aac"]["content_type"] == "audio/aac")
aac_samples, aac_rate = decode(got_aac, container="adts")
check("it decodes back to audio at the right rate",
      len(aac_samples) > RATE and aac_rate == RATE, (len(aac_samples), aac_rate))
mid = aac_samples[len(aac_samples) // 3:len(aac_samples) // 3 + 8192, 0]
check("and it is the sound that went in",
      goertzel(mid, 440.0) > 0.02 and goertzel(mid, 1500.0) < 0.01,
      (round(goertzel(mid, 440.0), 4), round(goertzel(mid, 1500.0), 4)))

with MockServer(password="hackme") as server:
    mixer = Mixer(open_stream=False, samplerate=RATE)
    bus = AirBus(RATE)
    mixer.air_tap = bus
    streamer = Streamer(bus, settings(server.port, format="aac"))
    streamer.start()
    mixer.play_samples(0, tone(RATE * 6, 440.0), bus=C.BUS_SFX)
    deadline = time.time() + 12
    while time.time() < deadline and len(server.body) < 16000:
        mixer.render(512)
        time.sleep(0.004)
    check("a whole AAC stream reaches a server",
          streamer.state == streamout.ON_AIR and len(server.body) > 8000,
          (streamer.state, len(server.body)))
    check("told it is AAC, not MP3",
          server.headers.get("content-type") == "audio/aac",
          server.headers.get("content-type"))
    streamer.stop()
    mixer.stop_all(fade_out=0.0)
    mixer.close()
    heard, _r = decode(server.body, container="adts")
    part = heard[len(heard) // 3:len(heard) // 3 + 8192, 0]
    check("and it decodes back to what was played",
          goertzel(part, 440.0) > 0.02, round(goertzel(part, 440.0), 4))

# ---------------------------------------------------------------------------
print("\nMore than one station")
# ---------------------------------------------------------------------------

# Tony now runs two: his own, and Blindside Radio. Retyping an address, a
# mount and a password to move between them is the friction that stops you
# bothering.

board = Board()
check("a fresh board knows about no stations", board.station_names() == [])
board.stream_name = "Tony Gebhard Radio"
board.stream_host = "radio.tonygebhard.me"
board.stream_port = 8001
board.stream_password = "one"
board.save_station()
board.stream_name = "Blindside Radio"
board.stream_host = "blindsideradio.com"
board.stream_port = 8003
board.stream_format = "aac"
board.stream_bitrate = 192
board.stream_password = "two"
board.save_station()
check("two are remembered, in the order they were saved",
      board.station_names() == ["Tony Gebhard Radio", "Blindside Radio"],
      board.station_names())

board.load_station("Tony Gebhard Radio")
check("loading one brings back every field, not just the address",
      (board.stream_host, board.stream_port, board.stream_format,
       board.stream_password)
      == ("radio.tonygebhard.me", 8001, "mp3", "one"),
      (board.stream_host, board.stream_port, board.stream_format))
board.load_station("Blindside Radio")
check("and the other one comes back whole too",
      (board.stream_host, board.stream_port, board.stream_format,
       board.stream_bitrate, board.stream_password)
      == ("blindsideradio.com", 8003, "aac", 192, "two"),
      (board.stream_host, board.stream_port, board.stream_format))

board.save_station("Blindside Radio")
check("saving over one replaces it rather than making a second",
      board.station_names().count("Blindside Radio") == 1,
      board.station_names())

kept = os.path.join(tempfile.mkdtemp(), "stations.json")
board.save(kept)
reloaded = Board.load(kept)
check("they survive a save and a load",
      reloaded.station_names() == ["Tony Gebhard Radio", "Blindside Radio"],
      reloaded.station_names())
check("with their passwords, or you would type them again every time",
      all(s.get("stream_password") for s in reloaded.stream_stations))
check("and the one that was loaded is still the one loaded",
      reloaded.stream_name == "Blindside Radio", reloaded.stream_name)

older = os.path.join(tempfile.mkdtemp(), "old.json")
with open(older, "w", encoding="utf-8") as handle:
    json.dump({"stream_host": "radio.example.com", "stream_port": 8001,
               "stream_name": "Only One"}, handle)
upgraded = Board.load(older)
check("a board saved before stations existed keeps the one it had",
      upgraded.station_names() == ["Only One"], upgraded.station_names())

junk = os.path.join(tempfile.mkdtemp(), "junk.json")
with open(junk, "w", encoding="utf-8") as handle:
    json.dump({"stream_stations": ["nonsense", 7, {"no": "name"},
                                   {"stream_name": "Real", "stream_port": 9}]},
              handle)
check("nonsense in the file is dropped rather than becoming a station",
      Board.load(junk).station_names() == ["Real"],
      Board.load(junk).station_names())

check("forgetting one leaves the other", board.forget_station("Only One") is False
      and board.forget_station("Tony Gebhard Radio")
      and board.station_names() == ["Blindside Radio"], board.station_names())


# ---------------------------------------------------------------------------
print("\nNothing is lost on the way out")
# ---------------------------------------------------------------------------

# Users reported skips and stutters. Two real things came out of chasing it:
# the last fraction of a second was thrown away every time you came off air,
# and a connection that could not keep up said nothing at all.

got_tail = bytearray()
enc = Encoder(got_tail.extend, fmt="mp3", samplerate=RATE, bitrate=128)
# Deliberately not a whole number of codec frames, which is the ordinary case.
frames = enc.frame_size * 3 + enc.frame_size // 2
enc.feed(tone(frames, 440.0))
enc.close()
back, _rate = decode(got_tail)
check("the remainder is encoded rather than dropped when a stream ends",
      len(back) >= frames, "fed %d, got %d back" % (frames, len(back)))

with MockServer(password="hackme") as server:
    mixer = Mixer(open_stream=False, samplerate=RATE)
    bus = AirBus(RATE)
    mixer.air_tap = bus
    streamer = Streamer(bus, settings(server.port))
    streamer.start()
    mixer.play_samples(0, tone(RATE * 6, 440.0), bus=C.BUS_SFX)
    started = time.time()
    made = 0
    while time.time() - started < 4.0:
        want = int((time.time() - started) * RATE) - made
        if want >= 512:
            step = min(want, 4096) // 512 * 512
            mixer.render(step)
            made += step
        else:
            time.sleep(0.002)
    streamer.stop()
    mixer.stop_all(fade_out=0.0)
    mixer.close()
    heard, rate = decode(server.body)
    played = made / float(RATE)
    arrived = len(heard) / float(rate) if rate else 0.0
    check("and coming off air does not clip the last moment of the show",
          arrived > played - 0.12,
          "played %.2fs, arrived %.2fs" % (played, arrived))

# ---------------------------------------------------------------------------
print("\nA connection that cannot keep up says so")
# ---------------------------------------------------------------------------

# A stream falling behind sounds perfect in the room and skips at the other
# end. Silence about it is the worst of both.

warnings = []
with MockServer(password="hackme", bytes_per_second=6000) as server:
    mixer = Mixer(open_stream=False, samplerate=RATE)
    bus = AirBus(RATE)
    mixer.air_tap = bus
    streamer = Streamer(bus, settings(server.port, bitrate=320),
                        on_trouble=warnings.append)
    streamer.start()
    mixer.play_samples(0, tone(RATE * 40, 440.0), bus=C.BUS_SFX)
    started = time.time()
    made = 0
    while time.time() - started < 25 and not warnings:
        want = int((time.time() - started) * RATE) - made
        if want >= 512:
            step = min(want, 4096) // 512 * 512
            mixer.render(step)
            made += step
        else:
            time.sleep(0.002)
    check("320 kbps down a link that cannot carry it is noticed",
          bool(warnings), warnings[:1])
    check("and what it says names the problem, not a number",
          any("listeners" in w.lower() for w in warnings), warnings[:1])
    streamer.stop()
    mixer.stop_all(fade_out=0.0)
    mixer.close()

# It only says it once, because a show does not need it every quarter second.
quiet = []
bus = AirBus(RATE)
streamer = Streamer(bus, settings(9), on_trouble=quiet.append)
streamer.bus.dropped = 5
streamer._watch_backlog()
streamer._watch_backlog()
streamer._watch_backlog()
check("and it says it once, not every time round the loop",
      len(quiet) == 1, len(quiet))

# ---------------------------------------------------------------------------
print("\nThe app around it")
# ---------------------------------------------------------------------------

import wx                                                    # noqa: E402

from dropdeck.dialogs import SettingsDialog                   # noqa: E402
from dropdeck.ui import (ID_STREAM_STATUS, ID_STREAM_TOGGLE,  # noqa: E402
                         DropDeckFrame)

app = wx.App(redirect=False)
frame = DropDeckFrame()

titles = [frame.GetMenuBar().GetMenuLabelText(i)
          for i in range(frame.GetMenuBar().GetMenuCount())]
check("there is a menu for it, named the way a radio station would",
      "On air" in titles, titles)

entries = {(e.GetFlags(), e.GetKeyCode()): e.GetCommand()
           for e in frame._accelerators}
check("Ctrl+B goes live",
      entries.get((wx.ACCEL_CTRL, ord("B"))) == ID_STREAM_TOGGLE)
check("Ctrl+Shift+B asks what it is doing",
      entries.get((wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("B")))
      == ID_STREAM_STATUS)
check("and both survive being in a text box, because they have a modifier",
      all(e.GetFlags() != wx.ACCEL_NORMAL for e in frame._typing_accelerators
          if e.GetCommand() in (ID_STREAM_TOGGLE, ID_STREAM_STATUS)))

check("it starts off air, every time",
      frame.streamer is None and not frame.streaming())
check("and says so when asked", "Off air" in frame.stream_status(),
      frame.stream_status())

prefs = SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic,
                       page=SettingsDialog.PAGE_STREAM)
check("Preferences opens on Streaming when asked for it",
      prefs.tabs.GetPageText(prefs.tabs.GetSelection()) == "Streaming",
      prefs.tabs.GetPageText(prefs.tabs.GetSelection()))
named = [prefs.stream_host.GetName(), prefs.stream_port.GetName(),
         prefs.stream_mount.GetName(), prefs.stream_password.GetName()]
check("and every box on it is named for a screen reader",
      all(named) and "Password" in named, named)
check("the password box does not show the password",
      bool(prefs.stream_password.GetWindowStyle() & wx.TE_PASSWORD))
prefs.stream_host.SetValue("radio.example.com")
prefs.stream_port.SetValue(8001)
prefs.stream_mount.SetValue("/live")
prefs.stream_password.SetValue("secret")
settings_out = prefs.stream_settings
check("what it reads back is what was typed in",
      settings_out["host"] == "radio.example.com"
      and settings_out["port"] == 8001
      and settings_out["mount"] == "/live"
      and settings_out["password"] == "secret", settings_out)
prefs.Destroy()

board = Board()
board.stream_host = "radio.example.com"
board.stream_port = 8001
board.stream_mount = "/live"
board.stream_password = "secret"
board.stream_bitrate = 192
board.stream_format = "opus"
board.stream_mic = False
saved = os.path.join(tempfile.mkdtemp(), "board.json")
board.save(saved)
back = Board.load(saved)
check("the settings survive a save and a load",
      (back.stream_host, back.stream_port, back.stream_mount,
       back.stream_password, back.stream_bitrate, back.stream_format,
       back.stream_mic)
      == ("radio.example.com", 8001, "/live", "secret", 192, "opus", False))
bad = os.path.join(tempfile.mkdtemp(), "bad.json")
with open(bad, "w", encoding="utf-8") as handle:
    json.dump({"stream_port": "not a port", "stream_bitrate": 999999}, handle)
nonsense = Board.load(bad)
check("and nonsense in the file falls back rather than stopping the app",
      nonsense.stream_port == C.DEFAULT_STREAM_PORT
      and nonsense.stream_bitrate in C.STREAM_BITRATES,
      (nonsense.stream_port, nonsense.stream_bitrate))

with MockServer(password="hackme") as server:
    frame.board.stream_host = "127.0.0.1"
    frame.board.stream_port = server.port
    frame.board.stream_mount = "/live"
    frame.board.stream_password = "hackme"
    frame.board.stream_format = "mp3"
    frame.board.stream_bitrate = 128
    check("going live opens the tap on every sound card",
          frame.start_stream()
          and all(m.air_tap is not None for m in frame.mixer.mixers))
    deadline = time.time() + 15
    while time.time() < deadline and len(server.body) < 8000:
        wx.Yield()
        time.sleep(0.02)
    check("and the show reaches the server",
          len(server.body) > 4000, len(server.body))
    check("with the app saying it is on air",
          frame.streamer.state == streamout.ON_AIR, frame.streamer.state)
    check("the status bar says so too, without anything being pressed",
          "ON AIR" in frame.status.GetStatusText(0),
          frame.status.GetStatusText(0))
    check("and Ctrl+Shift+B answers with something worth hearing",
          "On air for" in frame.stream_status(), frame.stream_status())

    frame.toggle_stream()
    check("Ctrl+B again comes off air",
          not frame.streaming() and frame.streamer is None)
    check("and puts every tap back",
          all(m.air_tap is None for m in frame.mixer.mixers))
    check("and the microphone is no longer live",
          frame.mic.on_air is False)

with MockServer(password="hackme") as server:
    frame.board.stream_port = server.port
    frame.start_stream()
    deadline = time.time() + 12
    while time.time() < deadline and frame.streamer.state != streamout.ON_AIR:
        wx.Yield()
        time.sleep(0.02)
    check("closing the app while on air comes off air first",
          frame.streamer is not None)
    frame.stop_background_work()
    check("and the streaming thread really stops",
          frame.streamer is None)

frame.Destroy()
app.Yield()

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
print()
print("Two sound cards that do not run at the same rate")

# A bank sent to a card that will only open at 44100, while the main output
# runs at 48000. Both write a minute of audio.
bus = AirBus(48000)
drained = []
overflowed_at = None
for second in range(60):
    for _ in range(48000 // 512):
        bus.write("main", np.zeros((512, CHANNELS), dtype=np.float32), 48000)
    for _ in range(44100 // 512):
        bus.write("second", np.full((512, CHANNELS), 0.1, dtype=np.float32),
                  44100)
    # The encoder drains at the bus rate, the way the pump does.
    want = bus.available()
    if want:
        drained.append(bus.read(want))
    if bus.dropped and overflowed_at is None:
        overflowed_at = second

check("a minute of two cards at different rates drops nothing",
      bus.dropped == 0, "first drop in second %s" % overflowed_at)
total = sum(len(piece) for piece in drained)
check("and a minute in is a minute out", abs(total - 48000 * 60) < 48000,
      "%d frames of %d" % (total, 48000 * 60))
mixed = np.concatenate(drained) if drained else np.zeros((1, CHANNELS))
check("with the slower card actually in the mix, not gaps",
      float(np.abs(mixed).min()) > 0.05,
      "quietest sample %.3f" % float(np.abs(mixed).min()))

# And the pitch, because the point is that it is converted, not just counted.
# A tone from the 44100 card has to come out at the pitch it went in.
bus = AirBus(48000)
pieces = []
position = 0
while position < 44100 * 2:
    moment = np.arange(position, position + 512) / 44100.0
    wave = (0.5 * np.sin(2 * np.pi * 1000 * moment)).astype(np.float32)
    bus.write("odd", np.repeat(wave[:, None], CHANNELS, axis=1), 44100)
    position += 512
    got = bus.available()
    if got:
        pieces.append(bus.read(got))
heard = np.concatenate(pieces)[:, 0].astype(np.float64)
window = heard * np.hanning(len(heard))
loudest = int(np.argmax(np.abs(np.fft.rfft(window))))
hz = np.fft.rfftfreq(len(heard), 1.0 / 48000)[loudest]
check("and at the pitch it was played at, not four per cent sharp",
      abs(hz - 1000.0) < 5.0, "%.1f Hz, sent 1000" % hz)

# One card at the bus rate keeps the straight path, with no resampler at all.
plain = AirBus(48000)
plain.write("main", np.ones((512, CHANNELS), dtype=np.float32), 48000)
check("a card already at the bus rate is not resampled",
      not plain._rates and plain.available() == 512)

print()
print("An encoder is not left behind when the server refuses")

closed = []
real_close = Encoder.close


def counting_close(self):
    closed.append(self)
    return real_close(self)


class Refuses(streamout.IcecastSink):
    def connect(self):
        raise streamout.SinkError("no")


streamout.Encoder.close = counting_close
streamout.SERVERS["refuses"] = ("Refuses", Refuses)
try:
    streamer = Streamer(AirBus(48000), {"server": "refuses", "host": "x",
                                        "port": 8000, "format": "mp3",
                                        "bitrate": 128})
    for _ in range(20):
        try:
            streamer._build()
        except Exception:
            pass
    check("twenty refused connections close twenty encoders",
          len(closed) == 20, len(closed))
    check("and none of them is left as the live one",
          streamer._encoder is None)
finally:
    streamout.Encoder.close = real_close
    del streamout.SERVERS["refuses"]


print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
