"""The microphone: ducking, gain, monitoring, and where it comes out.

    python tests/test_mic.py

No microphone is opened. `MicInput` is driven by handing its callback blocks of
samples directly, which is exactly what a sound card would do and works on a
machine with no input device at all, the same trick `test_engine` uses on the
output side.

The thing worth being careful about:

  * **Opening the microphone ducks the music. Being loud does not.** A gate
    that opens on your voice clips the first syllable of every sentence. So
    the check is that the duck follows `start` and `stop`, and that a silent
    microphone ducks exactly as hard as a shouted one.
  * **Monitoring is added after the duck.** Ducking the voice you are ducking
    the music *for* would undo the whole point.
  * **A starved monitor is silence, never a stall.** Two streams have two
    clocks; the output callback must never wait on the input one.
"""

import os
import sys
import tempfile
import threading
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile as _tempfile
os.environ["APPDATA"] = _tempfile.mkdtemp(prefix="dropdeck-test-appdata-")

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.engine import CHANNELS, db_to_gain
from dropdeck.micinput import MicInput, input_devices, resolve_input
from dropdeck.mixer import DuckBus, Mixer, MixerGroup

RATE = 48000
CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


def rms(block):
    return float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0


def feed(mic, frames, amplitude=0.5, freq=440.0):
    """Hand the microphone a block, the way its sound card would."""
    t = np.arange(frames, dtype=np.float32) / RATE
    block = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    mic._callback(block[:, None], frames, None, None)


def render(mix, blocks):
    out = [mix.render(C.BLOCKSIZE).copy() for _ in range(blocks)]
    return np.concatenate(out)


tmp = tempfile.mkdtemp(prefix="dropdeck-mic-")


def tone(name, seconds, freq=220.0, amp=0.5):
    path = os.path.join(tmp, name)
    n = int(seconds * RATE)
    t = np.arange(n, dtype=np.float32) / RATE
    wave = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.tile(wave[:, None], (1, 2)), RATE)
    return path


music = tone("music.wav", 20.0)

# ---------------------------------------------------------------------------
print("Devices")

devices = input_devices()
check("the machine's inputs can be listed", isinstance(devices, list))
check("each one is named and carries a host API",
      all(d.get("name") and d.get("hostapi") for d in devices), devices[:2])
check("an input remembered by a name nothing answers to resolves to nothing",
      resolve_input({"name": "No Such Microphone", "hostapi": "MME"}) is None)
check("and no name at all means the system default",
      resolve_input(None) is None and resolve_input({}) is None)

# ---------------------------------------------------------------------------
print("Ducking follows the switch, not the level")

bus = DuckBus()
mic = MicInput(duck_bus=bus, samplerate=RATE)
check("a microphone starts closed", not mic.is_open)
check("and nothing is ducked because of it", not bus.loud)

# start() would open a real device, which a test machine may not have. The
# ducking contract is what _publish does, so that is what is driven.
mic._publish(True)
check("an open microphone ducks the music", bus.loud)
mic._publish(False)
check("and closing it puts the music back", not bus.loud)

mic._publish(True)
mic.close()
check("closing the microphone forgets it on the bus, rather than leaving the "
      "music ducked forever", not bus.loud)

# Silence through an open microphone must duck exactly as hard as speech: the
# switch is what ducks, not the signal.
bus = DuckBus()
mic = MicInput(duck_bus=bus, samplerate=RATE)
mic._publish(True)
feed(mic, C.BLOCKSIZE, amplitude=0.0)
check("a silent open microphone still ducks", bus.loud)
check("and its level reads as silence", mic.peak == 0.0, mic.peak)
feed(mic, C.BLOCKSIZE, amplitude=0.5)
check("a loud one ducks no harder, because it cannot", bus.loud)
check("but the level readout follows the signal", mic.peak > 0.4, mic.peak)
mic.close()

# ---------------------------------------------------------------------------
print("The music actually gets out of the way")

mix = Mixer(open_stream=False, samplerate=RATE)
mix.bed_gain = 1.0
mix.ducking = True
mic = MicInput(duck_bus=mix.duck_bus, samplerate=RATE)

mix.play(40, music, is_bed=True, name="bed")
steady = rms(render(mix, 40))
check("a bed plays at its own level with the microphone closed",
      steady > 0.1, steady)

mic._publish(True)
render(mix, int(C.DUCK_ATTACK * RATE / C.BLOCKSIZE) + 4)
ducked = rms(render(mix, 10))
check("opening the microphone ducks it", ducked < steady * 0.6,
      "steady %.4f ducked %.4f" % (steady, ducked))

mic._publish(False)
render(mix, int(C.DUCK_RELEASE * RATE / C.BLOCKSIZE) + 8)
back = rms(render(mix, 10))
check("and closing it brings it back to where it was",
      back > steady * 0.85, "steady %.4f back %.4f" % (steady, back))

# A playlist track is music too, and must duck the same way.
mix.stop_all(fade_out=0.0)
render(mix, 2)
mix.set_playlist_gain(1.0)
mix.play(C.PLAYLIST_DECK_A, music, bus=C.BUS_PLAYLIST, name="song")
steady = rms(render(mix, 40))
mic._publish(True)
render(mix, int(C.DUCK_ATTACK * RATE / C.BLOCKSIZE) + 4)
ducked = rms(render(mix, 10))
check("a playlist track ducks under the microphone as well",
      ducked < steady * 0.6, "steady %.4f ducked %.4f" % (steady, ducked))
mic._publish(False)
mix.stop_all(fade_out=0.0)
render(mix, 2)

# ---------------------------------------------------------------------------
print("Gain, and monitoring")

mic = MicInput(duck_bus=mix.duck_bus, samplerate=RATE, gain_db=0.0)
check("zero decibels is unity gain", abs(mic.gain - 1.0) < 1e-6, mic.gain)
mic.gain_db = 6.0
check("and the gain is real decibels",
      abs(mic.gain - db_to_gain(6.0)) < 1e-6, mic.gain)

mic.gain_db = 0.0
mic.monitor = False
feed(mic, C.BLOCKSIZE, amplitude=0.5)
block = mic.read(C.BLOCKSIZE)
check("with monitoring off nothing comes back", rms(block) == 0.0, rms(block))
check("and the block is still the right shape, so a caller can just add it",
      block.shape == (C.BLOCKSIZE, CHANNELS), block.shape)

mic.monitor = True
mic.stream = object()          # pretend the device is open; nothing is read
feed(mic, C.BLOCKSIZE, amplitude=0.5)
block = mic.read(C.BLOCKSIZE)
check("with monitoring on the audio comes back", rms(block) > 0.2, rms(block))
check("in both channels", np.allclose(block[:, 0], block[:, 1]))

check("reading again with nothing fed returns silence, not the same block "
      "twice", rms(mic.read(C.BLOCKSIZE)) == 0.0)

# The one that matters: a starved monitor must not stall the output.
big = mic.read(C.BLOCKSIZE * 4)
check("asking for more than has arrived returns silence for the rest, "
      "never a wait", big.shape == (C.BLOCKSIZE * 4, CHANNELS))

mic.gain_db = 6.0
feed(mic, C.BLOCKSIZE, amplitude=0.4)
louder = float(np.abs(mic.read(C.BLOCKSIZE)).max())
mic.gain_db = -6.0
feed(mic, C.BLOCKSIZE, amplitude=0.4)
quieter = float(np.abs(mic.read(C.BLOCKSIZE)).max())
check("the gain reaches the monitored audio", louder > quieter * 2,
      "louder %.4f quieter %.4f" % (louder, quieter))

# Monitoring is added AFTER the duck, or the voice would duck itself.
mix.monitor_source = mic
mic.gain_db = 0.0
mix.ducking = True
mic._publish(True)
render(mix, 20)                                  # let the duck settle
for _ in range(8):
    feed(mic, C.BLOCKSIZE, amplitude=0.5)
monitored = rms(render(mix, 8))
check("a monitored voice is NOT ducked by its own microphone",
      monitored > 0.2, monitored)
mic._publish(False)
mix.monitor_source = None
mic.stream = None
mic.close()

# A monitor that throws must never take the music down with it.
class _Broken:
    def read(self, frames):
        raise RuntimeError("the monitor fell over")

mix.monitor_source = _Broken()
mix.play(40, music, is_bed=True, name="bed")
survived = rms(render(mix, 10))
check("a monitor that throws does not stop the music", survived > 0.05,
      survived)
mix.monitor_source = None
mix.stop_all(fade_out=0.0)
mix.close()

# ---------------------------------------------------------------------------
print("Where monitoring comes out")

group = MixerGroup(bank_devices={C.BANK_BEDS: None}, open_stream=False)
mic = MicInput(duck_bus=group.duck_bus, samplerate=RATE, monitor=True)
group.monitor_source = mic
attached = [m for m in group.mixers if m.monitor_source is mic]
check("monitoring is attached to exactly one output, never several draining "
      "the same buffer", len(attached) == 1, len(attached))
check("the group remembers what is monitoring", group.monitor_source is mic)

group.set_bank_devices({C.BANK_BEDS: None})
still = [m for m in group.mixers if m.monitor_source is mic]
check("and it survives a re-route, rather than writing into an output "
      "nothing drains any more", len(still) == 1, len(still))
group.close()
mic.close()

# ---------------------------------------------------------------------------
print("A microphone that does not run at the speakers' rate")

# Reported by Tony on 2 September, from the app:
#   The microphone would not open. Error opening InputStream:
#   Invalid sample rate [PaErrorCode -9997]
# The microphone was being opened at the OUTPUT device's rate. A headset at
# 44100 next to an interface at 48000 simply refuses, and PortAudio says so.
mic = MicInput(duck_bus=DuckBus(), samplerate=48000)
rates = mic.candidate_rates()
check("the output's rate is tried first, so a match needs no resampling",
      rates[0] == 48000, rates)
check("but it is not the only one tried", len(rates) > 1, rates)
check("and the fallbacks are rates every device supports",
      44100 in rates, rates)
check("with no duplicates, so a device is not asked the same thing twice",
      len(rates) == len(set(rates)), rates)

mic.output_rate = 44100
mic.device = None
check("the list follows the output", mic.candidate_rates()[0] == 44100,
      mic.candidate_rates())

# Captured at 44100, monitored into a 48000 output.
mic = MicInput(duck_bus=DuckBus(), samplerate=48000, monitor=True)
mic.samplerate = 44100
mic.stream = object()
mic._reset_ring()
check("a rate mismatch is noticed", mic.resampling)
for _ in range(6):
    feed(mic, C.BLOCKSIZE, amplitude=0.5)
block = mic.read(C.BLOCKSIZE)
check("and the monitored audio still arrives, resampled to the output's rate",
      rms(block) > 0.2, rms(block))
check("in the right shape for the mixer to add straight in",
      block.shape == (C.BLOCKSIZE, CHANNELS), block.shape)

mic.samplerate = 48000
mic._reset_ring()
check("matching rates resample nothing at all", not mic.resampling)
for _ in range(2):
    feed(mic, C.BLOCKSIZE, amplitude=0.5)
check("and still monitor", rms(mic.read(C.BLOCKSIZE)) > 0.2)

# The level was never the question. A microphone with no resampler at all
# still delivers a full strength block: it is simply the wrong SPEED. So this
# measures the pitch, which is the thing a listener would actually notice.
#
# It matters because the resampler spent a version nested inside a check for
# a voice processing chain, so a copy built without pedalboard had none, and
# went out a tone and a half sharp with nothing to say why.
def at_own_rate(mic, seconds, hz=1000.0):
    """Play a tone at the microphone's rate and collect what comes out."""
    mic._reset_ring()
    pieces = []
    position = 0
    while position < int(mic.samplerate * seconds):
        moment = (np.arange(position, position + C.BLOCKSIZE)
                  / float(mic.samplerate))
        wave = (0.5 * np.sin(2 * np.pi * hz * moment)).astype(np.float32)
        mic._callback(wave[:, None], C.BLOCKSIZE, None, None)
        position += C.BLOCKSIZE
        if mic._monitor.available:
            pieces.append(mic._monitor.read(mic._monitor.available))
    return np.concatenate(pieces)[:, 0].astype(np.float64)


def pitch_of(signal, rate):
    spectrum = np.abs(np.fft.rfft(signal * np.hanning(len(signal))))
    return float(np.fft.rfftfreq(len(signal), 1.0 / rate)[int(np.argmax(spectrum))])


slow = MicInput(duck_bus=DuckBus(), samplerate=48000, monitor=True)
slow.samplerate = 44100
slow.stream = object()
slow.chain = None                     # the state a copy without pedalboard is in
slow._reset_ring()
check("a microphone with no voice processing still has a resampler",
      slow._resampler is not None)
heard = at_own_rate(slow, 1.0)
check("a second in is a second out at the output's rate",
      abs(len(heard) - 48000) < 1200, "%d frames" % len(heard))
check("and it comes out at the pitch it went in at",
      abs(pitch_of(heard, 48000) - 1000.0) < 6.0,
      "%.1f Hz, played 1000" % pitch_of(heard, 48000))
check("which is a check that could tell the difference",
      abs(pitch_of(heard, 44100) - 1000.0) > 30.0,
      "%.1f Hz read at the wrong rate" % pitch_of(heard, 44100))
slow.stream = None
slow.close()

# The output callback takes the same lock to read the monitor, so the capture
# callback must not hold it across the resample. soxr allocates, and a hitch
# on the microphone thread would otherwise become a hitch in the music.
class Slow:
    def __init__(self, mic):
        self.mic = mic
        self.free = []

    def resample_chunk(self, block):
        got = self.mic._lock.acquire(blocking=False)
        if got:
            self.mic._lock.release()
        self.free.append(got)
        time.sleep(0.01)
        return block


held = MicInput(duck_bus=DuckBus(), samplerate=48000, monitor=True)
held.samplerate = 44100
held.stream = object()
held._reset_ring()
watcher = Slow(held)
held._resampler = watcher
for _ in range(5):
    feed(held, C.BLOCKSIZE)
check("the lock is free while the resampler is working",
      watcher.free and all(watcher.free), watcher.free)

waits = []
stop = threading.Event()


def capturing():
    while not stop.is_set():
        feed(held, C.BLOCKSIZE)


def monitoring():
    while not stop.is_set():
        began = time.perf_counter()
        held.read(C.BLOCKSIZE)
        waits.append(time.perf_counter() - began)
        time.sleep(0.001)


spun = [threading.Thread(target=capturing, daemon=True),
        threading.Thread(target=monitoring, daemon=True)]
for thread in spun:
    thread.start()
time.sleep(1.0)
stop.set()
for thread in spun:
    thread.join(timeout=5)
check("so the output never waits a resample to read the monitor",
      waits and max(waits) < 0.005,
      "worst read %.2f ms against a 10 ms resample" % (max(waits) * 1000))
check("and it really was reading throughout", len(waits) > 50, len(waits))

held._resampler = type("Broken", (), {
    "resample_chunk": lambda self, block: 1 / 0})()
before = held._monitor.available
held._callback(np.zeros((C.BLOCKSIZE, 1), dtype=np.float32) + 0.1,
               C.BLOCKSIZE, None, None)
check("a resampler that throws does not take the callback with it",
      held._monitor.available == before)
held.stream = None
held.close()


# The other half: the OUTPUT moves to a device with a different rate.
mic.stream = None
mic.output_rate = 48000
mic.samplerate = 48000
check("following the output to a new rate is a change", mic.set_output_rate(44100))
check("which is remembered", mic.output_rate == 44100)
check("and doing it again changes nothing", not mic.set_output_rate(44100))
mic.close()

failed_mic = MicInput(duck_bus=DuckBus(), samplerate=48000,
                      device=999999)          # certainly not a real device
check("a microphone that will not open at any rate says so", not failed_mic.start())
check("and names every rate it tried, not just the last",
      failed_mic.last_error and "Hz" in failed_mic.last_error,
      failed_mic.last_error)
check("without leaving the music ducked", not failed_mic.duck_bus.loud)
failed_mic.close()

# ---------------------------------------------------------------------------
print("What the board remembers")

board = Board()
check("no microphone is remembered to begin with",
      board.mic_device_name is None and board.mic_output_name is None)
check("gain starts at unity", board.mic_gain_db == C.DEFAULT_MIC_GAIN_DB)
check("and monitoring starts OFF, because on speakers it is feedback",
      board.mic_monitor is False)

board.mic_device_name = "Some Headset"
board.mic_device_hostapi = "Windows WASAPI"
board.mic_output_name = "Some Headphones"
board.mic_output_hostapi = "Windows WASAPI"
board.mic_gain_db = 7.0
board.mic_monitor = True
back = Board.load(board.save(os.path.join(tmp, "mic.json")))
check("the microphone is remembered by name, not by index",
      back.mic_device_name == "Some Headset"
      and back.mic_device_hostapi == "Windows WASAPI")
check("so is the output it is monitored through",
      back.mic_output_name == "Some Headphones")
check("the gain comes back", back.mic_gain_db == 7.0, back.mic_gain_db)
check("and so does monitoring", back.mic_monitor is True)

# There is deliberately no such thing as a remembered "microphone was on".
saved = board.to_dict()
check("whether the microphone was OPEN is never saved: nothing opens a "
      "microphone but a keypress",
      not any("open" in key or key == "mic_on" for key in saved))

silly = os.path.join(tmp, "sillymic.json")
with open(silly, "w", encoding="utf-8") as handle:
    handle.write('{"app": "TG Drop Deck", "slots": [],'
                 ' "mic_gain_db": "loud", "mic_monitor": 1}')
rescued = Board.load(silly)
check("nonsense for a gain falls back rather than stopping the board opening",
      rescued.mic_gain_db == C.DEFAULT_MIC_GAIN_DB, rescued.mic_gain_db)

clamp = os.path.join(tmp, "clampmic.json")
with open(clamp, "w", encoding="utf-8") as handle:
    handle.write('{"app": "TG Drop Deck", "slots": [], "mic_gain_db": 900}')
check("and an absurd one is clamped",
      Board.load(clamp).mic_gain_db == C.MAX_MIC_GAIN_DB)

# ---------------------------------------------------------------------------
import shutil
shutil.rmtree(tmp, ignore_errors=True)

failed = [n for n, ok in CHECKS if not ok]
print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
