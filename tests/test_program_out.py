"""The programme output, the full programme monitor, and the routing rules.

Tony, 10 September 2026: "program out to the cable. build that."

Three things are proved here, and the first one is the fault the other two
exist to fix.

1. **Neither output used to carry the whole show.** With the banks on one card
   and the monitor on another, the banks' card had the pads and no microphone,
   and the monitor had the microphone and no pads.
2. **The monitor now carries every card's show**, through a bus, without any
   voice being rendered twice.
3. **A routing that would send the show out of one card twice is refused**,
   and the ordinary one card setup is still allowed, which matters more.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile as _tempfile                       # noqa: E402
os.environ["APPDATA"] = _tempfile.mkdtemp(prefix="dropdeck-progout-")

from dropdeck import constants as C                # noqa: E402
from dropdeck import routing                       # noqa: E402
from dropdeck.audiofile import CHANNELS            # noqa: E402
from dropdeck.mixer import MixerGroup              # noqa: E402
from dropdeck.sources import SourceGroup           # noqa: E402

RATE = 48000
FRAMES = 512
passed = failed = 0

PAD = 0.3
MIC = 0.5


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  ok   %s" % name)
    else:
        failed += 1
        print("  FAIL %s %s" % (name, detail))


def peak(block):
    return round(float(np.abs(block).max()), 4) if len(block) else 0.0


class Fake:
    """Something shaped like a source: a level to hear, a level to send."""

    def __init__(self, monitor=0.0, air=0.0):
        self.monitor, self.air = monitor, air

    def read(self, frames):
        return np.full((frames, CHANNELS), self.monitor, dtype=np.float32)

    def read_air(self, frames):
        return np.full((frames, CHANNELS), self.air, dtype=np.float32)


def two_card_group(monitor_everything=True):
    """Banks on device 0, the presenter listening on device 1."""
    group = MixerGroup(bank_devices={1: 0, 2: 0, 3: 0, 4: 0},
                       open_stream=False, monitor_device=1)
    group.monitor_everything = monitor_everything
    group._wire_monitor()
    mic = Fake(monitor=MIC, air=MIC)
    group.monitor_source = SourceGroup(mic=mic)
    group.air_source = SourceGroup(mic=mic)
    # A pad, put in through the ROUTING rather than by hand. Rendering a
    # voice advances it, so injecting one into each mixer would be measuring
    # the test rather than the app.
    group.for_slot(0).play_samples(
        0, np.full((RATE * 3, CHANNELS), PAD, dtype=np.float32), name="pad")
    return group, group._mixers[0], group._mixers[1]


print("The fault: with two cards, neither one had the whole show")
group, banks, monitor = two_card_group(monitor_everything=False)
check("the banks' card carries the pads",
      abs(peak(banks.render(FRAMES)) - PAD) < 1e-4)
check("and NOT the microphone, which is the half that went to the cable",
      abs(peak(monitor.render(FRAMES)) - MIC) < 1e-4)
check("the monitor carries the microphone and NOT the pads",
      abs(peak(monitor.render(FRAMES)) - MIC) < 1e-4)
check("with the full monitor off, no bus is built at all",
      group._monitor_bus is None)
group.close()

print("\nThe fix: the monitor carries every card")
group, banks, monitor = two_card_group()
check("a bus exists once there is more than one card",
      group._monitor_bus is not None)
check("the banks' card writes into it", banks.monitor_tap is not None)
check("the monitor drains it", monitor.monitor_feed is not None)
check("and the monitor is NOT in its own bus, or it would hear itself twice",
      monitor.monitor_tap is None)

for _ in range(30):
    banks.render(FRAMES)          # fill past the prime
check("the banks' card still carries only its own sounds",
      abs(peak(banks.render(FRAMES)) - PAD) < 1e-4)
heard = monitor.render(FRAMES)
check("the monitor now carries the pads AND the microphone",
      abs(peak(heard) - (PAD + MIC)) < 1e-3, peak(heard))
check("and nothing ran dry doing it", group.monitor_gaps == 0,
      group.monitor_gaps)

print("\nA voice is still only ever rendered once")
group2 = MixerGroup(bank_devices={1: 0, 2: 0, 3: 0, 4: 0}, open_stream=False,
                    monitor_device=1)
data = np.full((FRAMES, CHANNELS), PAD, dtype=np.float32)
group2.for_slot(0).play_samples(0, data, name="one block only")
banks2, monitor2 = group2._mixers[0], group2._mixers[1]
first = peak(banks2.render(FRAMES))
second = peak(banks2.render(FRAMES))
check("one block of audio plays once and then is gone",
      abs(first - PAD) < 1e-4 and second == 0.0, "%s then %s" % (first, second))
group2.close()

print("\nThe monitor bus re-primes rather than starving for ever")
group, banks, monitor = two_card_group()
for _ in range(30):
    banks.render(FRAMES)
monitor.render(FRAMES)
before = group.monitor_gaps
for _ in range(200):              # drain it with nothing writing
    monitor.render(FRAMES)
check("running the monitor feed dry is counted",
      group.monitor_gaps > before, group.monitor_gaps)
check("and it fills up again rather than limping",
      not monitor._monitor_primed)
group.close()

print("\nOne sound card costs nothing at all")
group = MixerGroup(bank_devices={}, open_stream=False, monitor_device=None)
check("no second card means no bus", group._monitor_bus is None)
check("and no tap on the one mixer there is",
      all(m.monitor_tap is None for m in group.mixers))
check("the monitor mixer is the main output, as it always was",
      group.monitor_mixer is group.primary)
group.close()

print("\nA monitor device that will not open must not land in the cable")
group = MixerGroup(bank_devices={1: None, 2: None, 3: None, 4: None},
                   open_stream=True, monitor_device=999999)
check("the dead device is let go of, rather than left dangling",
      group.monitor_device is None, group.monitor_device)
check("and the app says what really happened to what you hear",
      any("what you hear" in p for p in group.problems), group.problems)
check("in words that warn you before you speak",
      any("would not broadcast" in p for p in group.problems), group.problems)
group.close()

print("\nThe routing rules")
name = {None: "the system default", 0: "Speakers", 18: "CABLE Input"}
say = lambda device: name.get(device, str(device))     # noqa: E731

clean = routing.conflicts(bank_devices={1: 0, 2: 0, 3: 0, 4: 0},
                          monitor_device=0, program_device=18,
                          program_on=True, describe=say)
check("banks on one card and the programme on a cable is sound", clean == [],
      clean)

same = routing.conflicts(bank_devices={1: 18, 2: 0, 3: 0, 4: 0},
                         monitor_device=0, program_device=18,
                         program_on=True, describe=say)
check("the programme sharing a card with a bank is refused", len(same) == 1)
check("and the sentence names the card and the bank",
      same and "CABLE Input" in same[0] and "bank 1" in same[0], same)

both = routing.conflicts(bank_devices={1: 0, 2: 0, 3: 0, 4: 0},
                         monitor_device=18, program_device=18,
                         program_on=True, describe=say)
check("the programme landing on the card you listen on is refused",
      len(both) == 1 and "twice over" in both[0], both)

ordinary = routing.conflicts(bank_devices={1: None, 2: None, 3: None, 4: None},
                             monitor_device=None, program_device=18,
                             program_on=True, describe=say)
check("but ONE sound card doing everything is still allowed, which matters "
      "more than any rule here", ordinary == [], ordinary)

off = routing.conflicts(bank_devices={1: 18, 2: 18, 3: 18, 4: 18},
                        monitor_device=18, program_device=18,
                        program_on=False, describe=say)
check("nothing collides with a programme output that is switched off",
      off == [], off)

# This check used to assert the opposite, and the opposite was a bug: the
# early return that skipped a programme output with no device made the
# warning below it unreachable. Mark found it as dead code, 10 September 2026.
default = routing.conflicts(bank_devices={1: 0, 2: 0, 3: 0, 4: 0},
                            monitor_device=0, program_device=None,
                            program_on=True, describe=say)
check("a programme output left on the system default is warned about, "
      "because that is how a show ends up going out of the laptop speakers",
      any("system default" in line for line in default), default)

# And it is reachable at all, which is the part that was broken. A branch
# after an early return that swallows its own condition is not a rule, it is
# a comment.
check("the warning is not dead code behind an early return",
      routing.conflicts(program_device=None, program_on=True) != [])

print("\nReading the whole routing out")
line = routing.describe_routing(
    bank_devices={1: 0, 2: 0, 3: 0, 4: 0}, monitor_device=0,
    program_device=18, program_on=True, describe=say)
check("it says where the sounds are", "Speakers" in line, line)
check("it says where the show goes", "CABLE Input" in line, line)
check("it says the microphone is in it", "microphone" in line, line)

line = routing.describe_routing(
    bank_devices={1: 0, 2: 0, 3: 0, 4: 0}, monitor_device=0,
    program_device=None, program_on=False, describe=say)
check("and says so plainly when nothing is being sent",
      "Nothing is being sent" in line, line)

line = routing.describe_routing(
    bank_devices={1: 0, 2: 5, 3: 5, 4: 0}, monitor_device=9,
    program_device=18, program_on=True, describe=say,
    bank_names={2: "Dialog Drops", 3: "Music Beds"})
check("several banks on one card are one sentence, and it agrees with itself",
      "Dialog Drops and Music Beds play out of" in line, line)
check("a bank name the user chose keeps its capitals",
      "Music Beds" in line and "Music beds" not in line, line)
check("and a separate monitor is named",
      "You hear everything on" in line, line)

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
