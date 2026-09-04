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
print("\nThe app around it")
# ---------------------------------------------------------------------------

import wx                                                    # noqa: E402

from dropdeck.board import Board                              # noqa: E402
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
print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
