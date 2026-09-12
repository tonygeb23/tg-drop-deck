"""The cable test: does a tone sent down a cable actually come back.

Everything here runs with no sound card. `judge` is separated from `run` for
exactly this reason, so every verdict can be put to it as audio made by
hand, including the two it has to get right and cannot be shown on a working
machine: a cable carrying nothing, and a cable losing audio.

The real cable was measured too, on 11 September 2026: a tone generated at
0.3 amplitude came back at minus 10.5 dBFS, where the arithmetic says minus
10.46, with no gaps. That is the level measurement proved against reality to
four hundredths of a decibel. It cannot be a check in here because it needs
VB-CABLE installed, so it lives in tools/check_cable.py.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import cabletest                       # noqa: E402
from dropdeck import endpoints as EP                 # noqa: E402
from dropdeck.audiofile import CHANNELS              # noqa: E402

RATE = 48000
passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  ok   %s" % name)
    else:
        failed += 1
        print("  FAIL %s %s" % (name, detail))


def clean(seconds=2.0, level=cabletest.TONE_LEVEL):
    """A recording of a cable that is working."""
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    return (level * np.sin(2 * np.pi * cabletest.TONE_HZ * t)
            ).astype(np.float32)


def with_gaps(signal, every_ms=160.0, long_ms=4.0):
    """The 3.6.0 fault: about six holes a second, four milliseconds each.

    Those are the measured numbers, not invented ones. A 1 kHz tone with
    this done to it read 974 Hz on a cycle count, which is what Tony heard
    as "a change in pitch, a little choppiness".
    """
    out = signal.copy()
    step = int(RATE * every_ms / 1000.0)
    hole = int(RATE * long_ms / 1000.0)
    for at in range(step, len(out) - hole, step):
        out[at:at + hole] = 0.0
    return out


print("The tone itself")
block, phase = cabletest.tone(512, RATE)
check("it is stereo, because the send is", block.shape == (512, CHANNELS))
check("both sides carry the same thing, so it cannot be a phase test",
      np.allclose(block[:, 0], block[:, -1]))
check("it is well under full scale, because a test that clips measures "
      "nothing", float(np.abs(block).max()) <= 0.31)
check("the phase carries on, so joined blocks have no click in them",
      0.0 < phase < 2 * np.pi)
second, _ = cabletest.tone(512, RATE, phase)
# Measured against the step INSIDE a block rather than against a number
# picked by eye. A 1 kHz sine at 0.3 moves 0.039 between neighbouring
# samples at 48 kHz, so "less than 0.01" would have condemned a perfect
# join, and did: this check failed on correct code the first time it ran.
inside = float(np.abs(np.diff(block[:, 0])).max())
joint = abs(float(second[0, 0] - block[-1, 0]))
check("and the joint really is seamless: the step across it is no bigger "
      "than a step inside a block", joint <= inside * 1.05, (joint, inside))

print("\nReading a level off a recording")
db = cabletest.level_at(clean(), RATE)
check("a tone at 0.3 reads as minus 10.5 dBFS, which is what the "
      "arithmetic says", abs(db - 20 * np.log10(0.3)) < 0.2, db)
check("half the level is six decibels down, so it is a real scale",
      abs(cabletest.level_at(clean(level=0.15), RATE) - (db - 6.02)) < 0.3)
check("silence is far below anything that counts as arriving",
      cabletest.level_at(np.zeros(RATE, np.float32), RATE)
      < cabletest.ARRIVED_DB)
check("and a tone at a DIFFERENT frequency does not count as our tone, or "
      "any noise at all would pass",
      cabletest.level_at(
          (0.3 * np.sin(2 * np.pi * 5000 * np.arange(RATE) / RATE)
           ).astype(np.float32), RATE) < cabletest.ARRIVED_DB)

print("\nCounting what is missing")
share, runs = cabletest.silence_in(clean())
check("a clean recording has no silence in it at all",
      share == 0.0 and runs == 0, (share, runs))
share, runs = cabletest.silence_in(with_gaps(clean()))
check("the measured 3.6.0 fault is found", share > 1.0 and runs > 5,
      (share, runs))
check("and the COUNT is separate from the share, because one long gap and "
      "sixty short ones are different faults", runs > 5)

print("\nThe verdict, which is the only part a user ever sees")
good = cabletest.judge(clean(), RATE, "CABLE Output")
check("a working cable passes", good.ok, good.said)
check("and says the level, so 'I can hear it' has a number behind it",
      "-10 decibels" in good.said, good.said)
check("and names what it listened on", "CABLE Output" in good.said)

nothing = cabletest.judge(np.zeros(RATE, np.float32), RATE)
check("a cable carrying nothing FAILS", not nothing.ok)
check("and says what to go and look at, rather than a number",
      "muted" in nothing.said and "volume mixer" in nothing.said,
      nothing.said)

lossy = cabletest.judge(with_gaps(clean()), RATE)
check("a cable losing audio FAILS, which is the whole reason this exists",
      not lossy.ok, lossy.said)
check("it says how much and how many", "per cent" in lossy.said
      and "separate gaps" in lossy.said, lossy.said)
check("and it warns that this one does not SOUND like dropouts, which is "
      "why it went unnoticed for so long",
      "change in pitch" in lossy.said, lossy.said)

# A tone that simply stops is not a fault. Without this the test would fail
# every time the recording happened to outlast the tone by a block.
stopped = np.concatenate([clean(1.0), np.zeros(int(RATE * 0.5), np.float32)])
verdict = cabletest.judge(stopped, RATE)
check("a tone that just STOPS at the end is not called a fault",
      verdict.ok, verdict.said)
check("even though a third of it is silent", verdict.gap_share > 30.0,
      verdict.gap_share)

print("\nFinding the other end of the cable")
E = lambda side, name, dev, rate, bits: EP.Endpoint(  # noqa: E731
    side, name, dev, rate, bits, 2)
CABLE = [E(EP.RENDER, "CABLE Input", "VB-Audio Virtual Cable", 48000, 24),
         E(EP.CAPTURE, "CABLE Output", "VB-Audio Virtual Cable", 48000, 24),
         E(EP.RENDER, "Speakers", "Realtek(R) Audio", 48000, 16),
         E(EP.CAPTURE, "Microphone", "Realtek(R) Audio", 48000, 16)]
check("the far end comes back as PortAudio would name it, not as Windows "
      "does", cabletest.capture_for(CABLE[0].full_name, CABLE)
      == "CABLE Output (VB-Audio Virtual Cable)",
      cabletest.capture_for(CABLE[0].full_name, CABLE))
check("a sound card that is not a cable has no far end to listen on",
      cabletest.capture_for("Nothing (By That Name)", CABLE) == "")
check("and the far end really is the SAME device, never another cable's",
      cabletest.capture_for(CABLE[2].full_name, CABLE)
      == "Microphone (Realtek(R) Audio)")

print("\nThe COM apartment, which is what makes it work off the UI thread")
import inspect                                        # noqa: E402
import threading                                      # noqa: E402


def on_a_thread(fn):
    """Run something on a worker thread and bring back what happened."""
    out = []

    def work():
        try:
            out.append(fn())
        except Exception as why:                       # noqa: BLE001
            out.append(why)

    t = threading.Thread(target=work)
    t.start()
    t.join(20)
    return out[0] if out else TimeoutError("never finished")


def enter_and_leave():
    with cabletest._Apartment() as room:
        return bool(room.ours)


# A worker thread with no COM apartment cannot open a WASAPI stream in a
# process where wx owns the main thread's, and the error it gets names WDM-KS
# rather than COM. Measured 11 September 2026, reproducible three times out
# of three before the fix and zero out of three after it.
check("run() opens its apartment BEFORE it touches any audio, or it would "
      "be measuring inside the fault", "_Apartment()"
      in inspect.getsource(cabletest.run))
check("the measurement itself is a separate function, so the apartment "
      "cannot be skipped by an early return",
      "_Apartment" not in inspect.getsource(cabletest._run))
check("it is MULTITHREADED, because an apartment threaded worker owes a "
      "message loop and this one has no window",
      cabletest._Apartment._MULTITHREADED == 0x0)
check("entering one on a worker thread works, which is the whole point",
      on_a_thread(enter_and_leave) is True)
check("and it can be done twice running without the second one failing",
      on_a_thread(enter_and_leave) is True
      and on_a_thread(enter_and_leave) is True)


def changed_mode():
    """Somebody else got there first, with the OTHER apartment model.

    This is the case that must not be undone. Uninitialising COM that
    another part of the program set up would pull the floor out from under
    it, and on the UI thread that other part is wx.
    """
    import ctypes
    hr = ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # STA, first
    if hr != 0:
        return "could not set up the case"
    try:
        with cabletest._Apartment() as room:
            claimed = room.ours
        # Still ours after the apartment left, or it took somebody else's.
        again = ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        alive = again == 1                               # S_FALSE, still up
        if again in (0, 1):
            ctypes.windll.ole32.CoUninitialize()
        return (claimed, alive)
    finally:
        ctypes.windll.ole32.CoUninitialize()


outcome = on_a_thread(changed_mode)
check("when COM is already up in the other model it does NOT claim it",
      outcome == (False, True), outcome)
check("and so the thread is left exactly as it was found, which matters "
      "because on the UI thread the one that set it up is wx",
      isinstance(outcome, tuple) and outcome[1] is True, outcome)

print("\nRunning it when there is nothing to run it on")
result = cabletest.run("Nothing (By That Name)")
check("it refuses rather than raising", isinstance(result, cabletest.Result)
      and not result.ok)
check("and explains that a cable has two ends and this has one",
      "two ends" in result.said, result.said)

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
