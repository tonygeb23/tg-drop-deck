"""Other things on the air besides your own voice.

    python tests/test_sources.py

Tony, 5 September 2026: "take the audio of an individually running program,
like a source. so. Add sources to a running stream, so in addition to the
microphone, it also can catch the audio from teamtalk.exe or, Google Chrome
chrome.exe."

Windows can capture a DEVICE. Capturing a PROCESS is a different and much
harder thing, so this captures devices, and a virtual cable turns one problem
into the other: point TeamTalk at the cable and it arrives here as an ordinary
input with a fader of its own.

No device is opened here. Every input is driven by handing its callback blocks
of samples, which is exactly what a sound card does and works on a machine
with nothing plugged in, the same trick test_mic uses.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-src-")

import numpy as np
import wx

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.micinput import CHANNELS, MicInput
from dropdeck.sources import MAX_SOURCES, Source, SourceGroup
from dropdeck.ui import DropDeckFrame

CHECKS = []
RATE = 48000


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name
          + (("  " + str(detail)) if detail != "" else ""))


app = wx.App(redirect=False)


def ready(inp):
    """An input that behaves as though its device were open."""
    inp.samplerate = RATE
    inp.channels_open = 1
    inp.monitor = True
    inp.on_air = True
    inp.stream = object()
    inp._reset_ring()


def feed(inp, hz, blocks=8, amp=0.3):
    for i in range(blocks):
        t = np.arange(i * C.BLOCKSIZE, (i + 1) * C.BLOCKSIZE) / float(RATE)
        wave = (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)
        inp._callback(wave[:, None], C.BLOCKSIZE, None, None)


def strength(block, hz):
    """How much of that frequency is in there, against the loudest thing."""
    mono = block[:, 0].astype(np.float64)
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    freqs = np.fft.rfftfreq(len(mono), 1.0 / RATE)
    top = float(spectrum.max()) or 1.0
    at = int(np.argmin(np.abs(freqs - hz)))
    return float(spectrum[max(0, at - 2):at + 3].max()) / top


print("A source is an input with no ducking and no voice processing")

one = Source(name="Games call", device_name="CABLE Output", samplerate=RATE)
check("it has no duck bus, so program audio never pushes the beds down",
      one.input.duck_bus is None)
check("and no voice chain, because a compressor for a voice is wrong here",
      one.input.chain is None)
check("it says what it is, for a list somebody reads out",
      "Games call" in one.describe() and "CABLE Output" in one.describe(),
      one.describe())
check("a source with no device says so rather than looking fine",
      "no device chosen" in Source(name="Empty").describe(),
      Source(name="Empty").describe())

one.gain_db = 6.0
one.channel = "left"
back = Source.from_dict(one.to_dict())
check("everything about it survives being written down and read back",
      (back.name, back.device_name, back.gain_db, back.channel,
       back.wanted_on_air, back.wanted_monitor)
      == (one.name, one.device_name, one.gain_db, one.channel,
          one.wanted_on_air, one.wanted_monitor))
check("nonsense falls back rather than exploding",
      Source.from_dict({"gain_db": "loud", "channel": "sideways"}).channel
      == "mix")
check("and a wild gain is clamped",
      Source.from_dict({"gain_db": 9999}).gain_db == C.MAX_MIC_GAIN_DB)
check("a source that is neither on air nor monitored does not open",
      Source(name="Off", device_name="", on_air=False,
             monitor=False).start(RATE) is False)


print()
print("The group is read as if it were one input")

mic = MicInput(samplerate=RATE)
call = Source(name="Call", samplerate=RATE)
browser = Source(name="Browser", samplerate=RATE)
for inp in (mic, call.input, browser.input):
    ready(inp)

group = SourceGroup(mic, [call, browser])
check("it counts the microphone as well as the sources", len(group) == 3)

feed(mic, 200.0)
feed(call.input, 600.0)
feed(browser.input, 1500.0)
block = group.read(C.BLOCKSIZE * 4)
check("the monitor mix has all three in it",
      min(strength(block, 200), strength(block, 600),
          strength(block, 1500)) > 0.3,
      [round(strength(block, hz), 2) for hz in (200, 600, 1500)])
check("and nothing at a frequency nobody sent",
      strength(block, 3000) < 0.05, round(strength(block, 3000), 4))

feed(mic, 200.0)
feed(call.input, 600.0)
feed(browser.input, 1500.0)
air = group.read_air(C.BLOCKSIZE * 4)
check("so does the air mix", float(np.abs(air).max()) > 0.1,
      "peak %.3f" % float(np.abs(air).max()))

# Reading takes the audio away, which is exactly why the group holds the
# sources rather than letting two parts of the app read them. Emptied first,
# then given one block, so what is left afterwards is not from earlier.
for inp in (mic, call.input, browser.input):
    inp._reset_ring()
group.read(C.BLOCKSIZE * 8)
feed(call.input, 600.0, blocks=1)
first = float(np.abs(group.read(C.BLOCKSIZE)).max())
second = float(np.abs(group.read(C.BLOCKSIZE)).max())
check("audio read once is gone, so nothing may read a source twice",
      first > 0.05 and second < 0.001, "%.3f then %.3f" % (first, second))


class Broken:
    """A source whose device has been unplugged mid show."""

    def read(self, frames):
        raise RuntimeError("gone")

    def read_air(self, frames):
        raise RuntimeError("gone")


group.sources = [Broken(), call]
feed(mic, 200.0)
feed(call.input, 600.0)
survived = group.read(C.BLOCKSIZE * 2)
check("one source that throws does not take the others down",
      float(np.abs(survived).max()) > 0.05,
      "peak %.3f" % float(np.abs(survived).max()))

empty = SourceGroup(None, [])
check("a group with nothing in it reads silence of the right shape",
      empty.read(512).shape == (512, CHANNELS), empty.read(512).shape)
check("and knows it is empty", not empty)


print()
print("What the board remembers")

board = Board()
check("a new board has no sources", board.sources == [])
board.sources = [one.to_dict(), Source(name="Second").to_dict()]
written = os.path.join(tempfile.mkdtemp(), "board.json")
board.save(written)
back = Board.load(written)
check("they are saved and read back", len(back.sources) == 2,
      len(back.sources))
check("with what was set on them",
      back.sources[0]["name"] == "Games call"
      and back.sources[0]["gain_db"] == 6.0, back.sources[0])
data = json.load(open(written, encoding="utf-8"))
data["sources"] = ["nonsense", 42, {"name": "Real"}]
json.dump(data, open(written, "w", encoding="utf-8"))
check("rubbish in the file is dropped rather than loaded",
      [s["name"] for s in Board.load(written).sources] == ["Real"],
      Board.load(written).sources)
data["sources"] = "not a list at all"
json.dump(data, open(written, "w", encoding="utf-8"))
check("and so is the wrong kind of thing entirely",
      Board.load(written).sources == [])


print()
print("In the app")

frame = DropDeckFrame()
frame.Show()
app.Yield()

check("the mixer monitors the group, not the microphone alone",
      frame.mixer.monitor_source is frame.source_group)
check("which holds the microphone", frame.source_group.mic is frame.mic)
check("and no sources to begin with", frame.sources == [])

frame.apply_sources([{"name": "Games call", "device_name": "",
                      "on_air": True, "monitor": False},
                     {"name": "Browser", "device_name": "",
                      "on_air": False, "monitor": True}])
check("adding sources puts them on the board",
      len(frame.board.sources) == 2, len(frame.board.sources))
check("and builds them", len(frame.sources) == 2)
check("the group sees them", len(frame.source_group.sources) == 2)
check("the mixer is still monitoring that group",
      frame.mixer.monitor_source is frame.source_group)
check("and they are saved with the board",
      [s["name"] for s in frame.board.sources] == ["Games call", "Browser"])

frame.apply_sources([])
check("removing them all leaves nothing", frame.sources == []
      and frame.board.sources == [])
check("and the group is still what the mixer reads",
      frame.mixer.monitor_source is frame.source_group)

check("there is a limit, so this cannot become a mixing desk",
      MAX_SOURCES >= 4 and MAX_SOURCES <= 16, MAX_SOURCES)

frame.stop_background_work()
frame.Destroy()
app.Yield()

failed = [n for n, ok in CHECKS if not ok]
print()
print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
