"""Taking the audio out of one running program.

    python tests/test_proccapture.py

Tony, 5 September 2026: "let's implement a full ability to grab program audio
itself... similar to how obs grabs audio sources."

This one really does open Windows audio machinery, so it makes its own noise
to capture: a helper process that plays a steady tone. Nothing here touches a
microphone or a real sound card input.

The check that matters is the third one. Two helpers playing different tones
at the same moment, captured one at a time, have to give back one tone each.
Anything less and this is device loopback wearing a disguise.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-proc-")

import numpy as np

from dropdeck import proccapture
from dropdeck.micinput import CHANNELS
from dropdeck.sources import Source

CHECKS = []
RATE = 48000

NOISEMAKER = textwrap.dedent('''
    import sys, time
    import numpy as np, sounddevice as sd
    HZ = float(sys.argv[1])
    RATE = 48000
    phase = 0.0
    def callback(outdata, frames, time_info, status):
        global phase
        step = 2.0 * np.pi * HZ / RATE
        t = phase + step * np.arange(frames)
        phase = float((t[-1] + step) % (2.0 * np.pi))
        wave = (0.25 * np.sin(t)).astype(np.float32)
        outdata[:] = np.repeat(wave[:, None], outdata.shape[1], axis=1)
    with sd.OutputStream(samplerate=RATE, channels=2, dtype="float32",
                         callback=callback, blocksize=480):
        time.sleep(float(sys.argv[2]))
''')


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name
          + (("  " + str(detail)) if detail != "" else ""))


def loudest(block, rate=RATE):
    """The frequency with most of the energy in it, or None for silence."""
    if not len(block):
        return None
    mono = block[:, 0].astype(np.float64)
    if float(np.abs(mono).max()) < 1e-4:
        return None
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    return float(np.fft.rfftfreq(len(mono), 1.0 / rate)[int(np.argmax(spectrum))])


folder = tempfile.mkdtemp()
script = os.path.join(folder, "noisemaker.py")
with open(script, "w", encoding="utf-8") as handle:
    handle.write(NOISEMAKER)


def noise(hz, seconds=25):
    return subprocess.Popen([sys.executable, script, str(hz), str(seconds)])


print("What this Windows can do")

check("it can capture a program at all", proccapture.supported(),
      "build %d, needs 20348" % sys.getwindowsversion().build)
if not proccapture.supported():
    print("\nNothing else here can run on this machine.")
    sys.exit(0)

programs = proccapture.running_programs()
check("it can list the programs that are running", len(programs) > 0,
      len(programs))
check("each one has a name and a process id",
      all(entry.get("name") and entry.get("pid") for entry in programs))
check("they are programs, not windows: no name appears twice",
      len({entry["name"].lower() for entry in programs}) == len(programs))
check("something everybody has is in the list",
      any(entry["name"].lower() == "explorer.exe" for entry in programs),
      [entry["name"] for entry in programs][:6])

check("a program that is running can be found by name",
      proccapture.find_pid("explorer.exe") is not None)
check("and one that is not gives nothing rather than a wrong answer",
      proccapture.find_pid("a-program-nobody-has.exe") is None)
check("asking about nothing at all is safe",
      proccapture.find_pid("") is None)
check("a process id that never existed is not alive",
      proccapture.alive(999999) is False)
check("and this very process is", proccapture.alive(os.getpid()) is True)


print()
print("Capturing one program")

first = noise(1000)
time.sleep(2.5)
capture = proccapture.ProcessCapture(pid=first.pid, samplerate=RATE,
                                     monitor=True)
capture.on_air = True
started = capture.start()
check("it opens", started, capture.last_error)
time.sleep(2.0)

heard = loudest(capture.read(RATE))
check("what it hears is the tone that program is playing",
      heard is not None and abs(heard - 1000.0) < 15.0, heard)
air = capture.read_air(RATE // 2)
check("and the same reaches the air ring, which is drained separately",
      float(np.abs(air).max()) > 0.001, "peak %.3f" % float(np.abs(air).max()))
check("both rings hand back the right shape",
      capture.read(512).shape == (512, CHANNELS))

# Measured against itself, not against a number. How loud this arrives
# depends on the helper's own volume in the Windows mixer, which is not ours
# to set, so an absolute threshold here would be a test of somebody's slider.
capture.read(RATE)
time.sleep(1.0)
plain = float(np.abs(capture.read(RATE // 2)).max())
capture.gain_db = 6.0
time.sleep(1.0)
louder = float(np.abs(capture.read(RATE // 2)).max())
capture.gain_db = 0.0
check("six decibels of gain really is about six decibels",
      plain > 0.001 and 1.6 < louder / plain < 2.4,
      "%.4f then %.4f, a factor of %.2f" % (plain, louder, louder / (plain or 1)))

capture.monitor = False
time.sleep(0.5)
capture.read(RATE)
check("with monitoring off it hands back silence to the speakers",
      float(np.abs(capture.read(2048)).max()) == 0.0)
capture.monitor = True


print()
print("And only that program")

second = noise(300)
time.sleep(2.5)
other = proccapture.ProcessCapture(pid=second.pid, samplerate=RATE,
                                   monitor=True)
other.start()
time.sleep(2.0)

# Both are playing. Each capture must hear its own and not the other.
capture.read(RATE * 2)
other.read(RATE * 2)
time.sleep(1.5)
one = loudest(capture.read(RATE))
two = loudest(other.read(RATE))
check("the first capture still hears only its own tone",
      one is not None and abs(one - 1000.0) < 15.0, one)
check("and the second hears only its own",
      two is not None and abs(two - 300.0) < 15.0, two)
check("which is the whole point: this is not everything on the sound card",
      one is not None and two is not None and abs(one - two) > 500.0)

other.stop()
second.terminate()


print()
print("When the program is not there")

check("a process id that does not exist is refused",
      proccapture.ProcessCapture(pid=999999).start() is False)
gone = proccapture.ProcessCapture(pid=999999)
gone.start()
check("and it says why rather than being silently quiet",
      "not running" in (gone.last_error or ""), gone.last_error)
check("no program chosen at all is refused too",
      proccapture.ProcessCapture().start() is False)

# A program that closes while it is being captured.
watched = noise(500, seconds=30)
time.sleep(2.0)
watcher = proccapture.ProcessCapture(pid=watched.pid, samplerate=RATE,
                                     monitor=True)
check("a live one opens", watcher.start(), watcher.last_error)
watched.terminate()
for _ in range(60):
    if not watcher.is_open:
        break
    time.sleep(0.25)
check("closing the program stops the capture rather than leaving it silent",
      not watcher.is_open)
check("and says so", "closed" in (watcher.last_error or ""),
      watcher.last_error)
watcher.stop()

capture.stop()
check("stopping is final", not capture.is_open)
check("and reading a stopped capture is silence, not a crash",
      float(np.abs(capture.read(1024)).max()) == 0.0)
first.terminate()


print()
print("As a source, which is how the app uses it")

playing = noise(800)
time.sleep(2.5)
source = Source(name="The helper", kind=Source.PROGRAM,
                program=os.path.basename(sys.executable),
                monitor=True, on_air=True, samplerate=RATE)
check("a program source knows what it is", source.is_program)
check("and says so when read out",
      os.path.basename(sys.executable) in source.describe(),
      source.describe())
check("it starts by finding the program by name", source.start(RATE),
      source.last_error)
time.sleep(2.0)
found = loudest(source.read(RATE))
check("and hears it", found is not None and abs(found - 800.0) < 20.0, found)

kept = Source.from_dict(source.to_dict(), samplerate=RATE)
check("what it is survives being written down",
      kept.is_program and kept.program == source.program)
check("a board from before this existed still loads, as a device",
      Source.from_dict({"name": "old", "device_name": "Something"}).kind
      == Source.DEVICE)

source.close()
playing.terminate()
missing = Source(name="Nope", kind=Source.PROGRAM,
                 program="a-program-nobody-has.exe", on_air=True)
check("a source pointing at a program that is not running says so",
      missing.start(RATE) is False and "not running" in (missing.last_error or ""),
      missing.last_error)

failed = [n for n, ok in CHECKS if not ok]
print()
print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
