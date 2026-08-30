"""Per-bank outputs, and the option to stop announcing what you can hear.

Both features came from Brian Hartgen, 2026-08-30, and both are about getting
out of the user's way: one stops the screen reader confirming something audible,
the other lets a bank go to its own sound card so the balance can be ridden on a
physical desk instead of by automatic ducking.

No sound card is opened. MixerGroup takes ``open_stream=False`` for the same
reason Mixer does, so this runs on a machine with no audio at all.

    python tests/test_routing.py
"""

import os
import sys
import tempfile

import numpy as np
import soundfile as sf
import wx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.engine import db_to_gain
from dropdeck.mixer import DuckBus, Mixer, MixerGroup, device_spec, resolve_device
from dropdeck.ui import DropDeckFrame

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append((label, bool(condition), detail))
    if not condition:
        print(f"  FAIL  {label}   {detail}")


def tone(path, seconds=1.0, rate=48000, freq=220.0, amp=0.5):
    t = np.arange(int(seconds * rate)) / rate
    wave = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.column_stack([wave, wave]), rate)
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="dropdeck-routing-")
    sound = tone(os.path.join(tmp, "sound.wav"), seconds=4.0)
    bed = tone(os.path.join(tmp, "bed.wav"), seconds=6.0, freq=110.0)

    print("Everything on one output is still one output")
    group = MixerGroup(open_stream=False)
    check("a single stream when nothing is routed away",
          group.distinct_device_count() == 1, str(group.distinct_device_count()))
    check("every bank lands on the same mixer",
          len({id(group.for_bank(b)) for b in range(1, C.BANK_COUNT + 1)}) == 1)
    check("no problems reported", not group.problems, str(group.problems))
    group.close()

    print("\nRouting a bank away makes a second output, and only one more")
    group = MixerGroup(bank_devices={C.BANK_BEDS: 5}, open_stream=False)
    check("two outputs, not four", group.distinct_device_count() == 2,
          str(group.distinct_device_count()))
    check("beds are on their own mixer",
          group.for_bank(C.BANK_BEDS) is not group.for_bank(C.BANK_SFX))
    check("the other three banks still share one",
          group.for_bank(C.BANK_SFX) is group.for_bank(C.BANK_DROPS)
          is group.for_bank(C.BANK_MISC))

    print("\nA slot reaches the mixer its bank is routed to")
    first_bed = (C.BANK_BEDS - 1) * C.SLOTS_PER_BANK
    first_sfx = 0
    check("slot 0 goes to the sound effects mixer",
          group.for_slot(first_sfx) is group.for_bank(C.BANK_SFX))
    check("the first bed slot goes to the beds mixer",
          group.for_slot(first_bed) is group.for_bank(C.BANK_BEDS))
    check("the last bed slot goes there too",
          group.for_slot(first_bed + C.SLOTS_PER_BANK - 1)
          is group.for_bank(C.BANK_BEDS))
    check("the slot after the beds bank does not",
          group.for_slot(first_bed + C.SLOTS_PER_BANK)
          is not group.for_bank(C.BANK_BEDS))

    print("\nPlaying and stopping work across the split")
    group.play(first_sfx, sound, is_bed=False, duration=4.0)
    group.play(first_bed, bed, is_bed=True, loop=False, duration=6.0)
    check("both voices are counted", group.voice_count() == 2,
          str(group.voice_count()))
    check("playing_slots sees both outputs",
          group.playing_slots() == sorted([first_sfx, first_bed]),
          str(group.playing_slots()))
    check("is_playing finds the one on the second output",
          group.is_playing(first_bed))
    check("stop_all reaches every output", group.stop_all(fade_out=0.0) == 2)
    group.close()

    print("\nDucking still crosses outputs, which is the point")
    # A drop on output A must duck a bed on output B. Without the shared bus
    # each mixer would only see its own voices, and routing the beds elsewhere
    # would silently turn ducking off - a regression disguised as a feature.
    group = MixerGroup(bank_devices={C.BANK_BEDS: 5}, open_stream=False)
    group.ducking = True
    sfx_mixer = group.for_bank(C.BANK_SFX)
    bed_mixer = group.for_bank(C.BANK_BEDS)
    check("the two mixers share one duck bus",
          sfx_mixer.duck_bus is bed_mixer.duck_bus)

    group.play(first_bed, bed, is_bed=True, loop=True, duration=6.0,
               fade_in=0.0, fade_out=0.0)
    for _ in range(20):
        bed_mixer.render(1024)
    quiet_level = float(np.abs(bed_mixer.render(1024)).max())

    group.play(first_sfx, sound, is_bed=False, duration=4.0,
               fade_in=0.0, fade_out=0.0)
    # The sfx mixer has to render for its voice to reach the bus, and the
    # duck attack is 0.12 s - about six blocks. Fifteen is comfortably
    # past that and comfortably short of the four second sound ending.
    for _ in range(15):
        sfx_mixer.render(1024)
        bed_mixer.render(1024)
    ducked_level = float(np.abs(bed_mixer.render(1024)).max())

    check("a drop on one output ducks a bed on another",
          ducked_level < quiet_level * 0.9,
          f"{quiet_level:.4f} then {ducked_level:.4f}")
    group.stop_all(fade_out=0.0)
    group.close()

    print("\nA missing device falls back and says so")
    group = MixerGroup(bank_devices={C.BANK_BEDS: 999}, open_stream=True)
    check("it reports the problem rather than going silent",
          bool(group.problems), str(group.problems))
    check("the bank was moved back to the main output",
          group.bank_devices.get(C.BANK_BEDS) is None,
          str(group.bank_devices))
    check("something still plays", group.distinct_device_count() >= 1)
    group.close()

    print("\nDevices are remembered by name, not by index")
    spec = device_spec(5)
    check("a live index converts to a name and host API",
          spec and spec.get("name") and spec.get("hostapi"), str(spec))
    check("that name resolves back to an index", resolve_device(spec) is not None)
    check("a device that is not here resolves to None",
          resolve_device({"name": "No Such Sound Card", "hostapi": "MME"}) is None)
    check("no device at all resolves to None", resolve_device(None) is None)

    print("\nThe duck bus itself")
    bus = DuckBus()
    check("nothing loud to start", not bus.loud)
    bus.publish("a", True)
    check("one loud output is enough", bus.loud)
    bus.publish("a", False)
    check("and it clears again", not bus.loud)
    bus.publish("a", True)
    bus.forget("a")
    check("a closed output stops holding everything ducked", not bus.loud)

    print("\nThe board remembers both settings")
    board = Board()
    check("announcements are on by default", board.announce_playback is True)
    check("no bank is routed away by default", board.bank_devices == {})
    board.announce_playback = False
    board.bank_devices = {C.BANK_BEDS: {"name": "CABLE Input", "hostapi": "MME"}}
    path = os.path.join(tmp, "board.json")
    board.save(path)
    reloaded = Board.load(path)
    check("the announcement setting survives a save",
          reloaded.announce_playback is False)
    check("the routing survives a save",
          reloaded.bank_devices == {C.BANK_BEDS: {"name": "CABLE Input",
                                                  "hostapi": "MME"}},
          str(reloaded.bank_devices))
    check("bank keys come back as integers",
          all(isinstance(k, int) for k in reloaded.bank_devices))

    print("\nThe announcement gate, on the real frame")
    app = wx.App(redirect=False)
    frame = DropDeckFrame()
    spoken = []
    frame.speaker.say = lambda text, *a, **k: spoken.append(text)
    try:
        frame.board.announce_playback = True
        spoken.clear()
        frame.announce_playback("Playing bed, Test")
        check("with it on, playback is spoken", spoken == ["Playing bed, Test"],
              str(spoken))

        frame.board.announce_playback = False
        spoken.clear()
        frame.announce_playback("Playing bed, Test")
        check("with it off, playback is not spoken", spoken == [], str(spoken))

        # The status bar is the half that must NOT be optional: turning speech
        # off is about the interruption, not about hiding the information.
        check("the status bar still says what happened",
              "Playing bed, Test" in frame.status.GetStatusText(1),
              frame.status.GetStatusText(1))

        spoken.clear()
        frame.announce("Test.wav, file missing. Use File, relink missing sounds")
        check("a failure is spoken even with playback speech off",
              len(spoken) == 1, str(spoken))

        spoken.clear()
        frame.stop_all()
        check("stop everything still confirms, because silence is ambiguous",
              len(spoken) == 1, str(spoken))
    finally:
        frame.stop_background_work()
        frame.Destroy()
        app.Destroy()

    passed = sum(1 for _l, ok, _d in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
