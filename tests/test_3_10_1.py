"""3.10.1: changing the output device actually moves the sound.

Martin Sutton, 20 November 2026: "I change my output to another soundcard but
it doesn't change."

What he heard was true. "Hear yourself through" left on "Same as the
soundboard" is a monitor device of None, and `MixerGroup._build` put that None
in the set of cards to open, where None also means the Windows default output.
So a main output moved off the default left a second stream open on the
default, `monitor_mixer` found it under the key None, and since 3.7.0 the full
programme monitor fed it every other card's show. The sound arrived on the new
card AND carried on coming out of the old one, which from the chair is an
output that did not change.

Everything here runs with no sound card: `open_stream=False`, and the samples
are read off `render`.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile as _tempfile                       # noqa: E402
os.environ["APPDATA"] = _tempfile.mkdtemp(prefix="dropdeck-3101-")

from dropdeck import constants as C                # noqa: E402
from dropdeck.audiofile import CHANNELS            # noqa: E402
from dropdeck.mixer import MixerGroup              # noqa: E402

RATE = 48000
FRAMES = 512
PAD = 0.3
MIC = 0.5
#: Stand-ins for two real cards. Nothing is opened, so any numbers will do.
NEW_CARD = 7
DESK_CARD = 5
HEADPHONES = 9
passed = failed = 0


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


class FakeMic:
    def read(self, frames):
        return np.full((frames, CHANNELS), MIC, dtype=np.float32)

    def read_air(self, frames):
        return np.full((frames, CHANNELS), MIC, dtype=np.float32)


def everything_on(device):
    return {bank: device for bank in range(1, C.BANK_COUNT + 1)}


def pad(group, slot=0):
    """A pad, put in through the routing, the way a key press does it."""
    group.for_slot(slot).play_samples(
        slot, np.full((RATE * 3, CHANNELS), PAD, dtype=np.float32), name="pad")


def heard_on(group, device, blocks=40):
    """The loudest thing that card plays over enough blocks to prime a bus."""
    loudest = 0.0
    for _ in range(blocks):
        for key, mixer in list(group._mixers.items()):
            out = mixer.render(FRAMES)
            if key == device:
                loudest = max(loudest, peak(out))
    return loudest


print("Martin's report: move the main output off the Windows default")
group = MixerGroup(bank_devices=everything_on(None), open_stream=False,
                   monitor_device=None)
group.monitor_source = FakeMic()
check("it starts as one stream, on the default",
      list(group._mixers) == [None], list(group._mixers))
group.set_bank_devices(everything_on(NEW_CARD))
group.monitor_source = FakeMic()
check("after the move there is still exactly one stream",
      group.distinct_device_count() == 1, list(group._mixers))
check("and it is on the card that was chosen",
      list(group._mixers) == [NEW_CARD], list(group._mixers))
check("nothing is left open on the old card",
      None not in group._mixers, list(group._mixers))
check("no monitor bus is carrying the show anywhere else",
      group._monitor_bus is None)
pad(group)
check("the pad comes out of the new card",
      heard_on(group, NEW_CARD) >= PAD - 1e-4)
check("what you hear is the main output, as the setting says",
      group.monitor_mixer is group.primary)
check("so the microphone is monitored on the new card too",
      group._mixers[NEW_CARD].monitor_source is not None)
group.close()

print("\nThe same board opened fresh, which is every start after the change")
group = MixerGroup(bank_devices=everything_on(NEW_CARD), open_stream=False,
                   monitor_device=None)
check("one stream, on the chosen card, and none on the default",
      list(group._mixers) == [NEW_CARD], list(group._mixers))
group.close()

print("\nAnd back again")
group = MixerGroup(bank_devices=everything_on(NEW_CARD), open_stream=False,
                   monitor_device=None)
group.set_bank_devices(everything_on(None))
check("moving back to the default leaves one stream, on the default",
      list(group._mixers) == [None], list(group._mixers))
group.close()

print("\nA bank on its own card stays on its own card")
routed = everything_on(NEW_CARD)
routed[C.LOOPING_BANK] = DESK_CARD
group = MixerGroup(bank_devices=routed, open_stream=False, monitor_device=None)
check("two cards, and neither of them is the default",
      sorted(group._mixers, key=str) == sorted([DESK_CARD, NEW_CARD], key=str),
      list(group._mixers))
bed_slot = (C.LOOPING_BANK - 1) * C.SLOTS_PER_BANK
pad(group, bed_slot)
check("the bed comes out of the desk card",
      heard_on(group, DESK_CARD) >= PAD - 1e-4)
pad(group, bed_slot)
check("and NOT out of the main card as well, or a desk could not ride it",
      heard_on(group, NEW_CARD) == 0.0)
group.close()

print("\nA separate monitor output still hears everything")
group = MixerGroup(bank_devices=everything_on(NEW_CARD), open_stream=False,
                   monitor_device=HEADPHONES)
check("the monitor card is opened beside the main one",
      sorted(group._mixers, key=str) == sorted([NEW_CARD, HEADPHONES], key=str),
      list(group._mixers))
check("and the bus that feeds it exists", group._monitor_bus is not None)
pad(group)
check("the headphones carry the pad",
      heard_on(group, HEADPHONES) >= PAD - 1e-3)
group.set_monitor_device(None)
check("set back to Same as the soundboard, the monitor card is closed",
      list(group._mixers) == [NEW_CARD], list(group._mixers))
check("and what you hear is the main output again",
      group.monitor_mixer is group.primary)
group.close()

print("\nA monitor card that will not open still goes to the default, "
      "never to bank 1")
# Really opened, because the fallback only exists for a stream that refused.
# The main output is left on the default so no other card is touched.
group = MixerGroup(bank_devices=everything_on(None), open_stream=True,
                   monitor_device=999999)
check("the dead card is let go of", group.monitor_device is None)
check("and the warning is still given",
      any("would not broadcast" in p for p in group.problems), group.problems)
group.close()
# The dangerous half, with no sound card: bank 1 on a cable and a monitor
# that has fallen back. It must come out of the default, not the cable.
group = MixerGroup(bank_devices=everything_on(NEW_CARD), open_stream=False,
                   monitor_device=HEADPHONES)
group.monitor_device = None
group._monitor_fell_back = True
group._build()
group.monitor_source = FakeMic()
check("a monitor that fell back opens the default beside the main card",
      sorted(group._mixers, key=str) == sorted([NEW_CARD, None], key=str),
      list(group._mixers))
check("and the microphone is heard there, not on bank 1's card",
      group._mixers[None].monitor_source is not None
      and group._mixers[NEW_CARD].monitor_source is None)
check("choosing Same as the soundboard afterwards is honoured",
      group.set_monitor_device(None) is True
      and list(group._mixers) == [NEW_CARD], list(group._mixers))
group.close()

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
