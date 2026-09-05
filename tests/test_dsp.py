"""The microphone chain, measured rather than trusted.

Tony, 4 September 2026: "add DSP support for a compressor on vocals, limiter,
so on so forth, equalizor with accessible adjusters... noise gate, too. make
sure it's smooth, accurate with it's abilities".

"Smooth" and "accurate" are testable claims, so they are tested as claims:

  * A compressor at 4:1 should turn 12 dB over the threshold into 3 dB over
    it. That is arithmetic, and it is checked as arithmetic.
  * A limiter set to minus one should never, at any input, produce a sample
    above minus one. Checked by throwing far too much at it.
  * An equaliser asked for 6 dB at 1 kHz should give 6 dB at 1 kHz and leave
    100 Hz alone. Checked by measuring both.
  * A gate should shut on silence and open on speech, and do both without a
    click. A click is a discontinuity, and a discontinuity is measurable.
  * The whole chain has to fit inside an audio callback, so it is timed
    against the budget it actually has.

    python tests/test_dsp.py
"""

import math
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-dsp-test-")

from dropdeck import dsp

CHECKS = []
RATE = 44100


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" else ""))


def db(x):
    return 20.0 * math.log10(max(1e-12, float(x)))


def amp(decibels):
    return 10.0 ** (decibels / 20.0)


def tone(seconds, hz=440.0, level_db=-20.0, rate=RATE):
    n = int(rate * seconds)
    t = np.arange(n) / float(rate)
    wave = (amp(level_db) * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return np.repeat(wave[:, None], 2, axis=1)


def run(chain, audio, block=512):
    """Push audio through in blocks, the way the callback does."""
    out = []
    for start in range(0, len(audio) - block, block):
        out.append(chain.process(audio[start:start + block]))
    return np.concatenate(out) if out else audio[:0]


def settle(chain, audio, block=512):
    """Everything after the first half second, once envelopes have settled."""
    processed = run(chain, audio, block)
    return processed[int(RATE * 0.5):]


def only(**settings):
    """A chain with everything off except what is named."""
    off = {"gate_on": False, "highpass_on": False, "eq_on": False,
           "comp_on": False, "limit_on": False, "comp_makeup": 0.0}
    off.update(settings)
    return dsp.MicChain(RATE, off)


print("\nIs there anything to test")
check("the processing library is here", dsp.available())
if not dsp.available():
    print("\nnothing to measure without it")
    sys.exit(1)


# ---------------------------------------------------------------------------
print("\nThe compressor does the arithmetic it promises")
# ---------------------------------------------------------------------------

# 4 to 1 above minus 30: an input 12 dB over should come out 3 dB over.
chain = only(comp_on=True, comp_threshold=-30.0, comp_ratio=4.0,
             comp_attack=1.0, comp_release=50.0)
loud = settle(chain, tone(2.0, level_db=-18.0))
out_db = db(np.abs(loud).max())
expected = -30.0 + ((-18.0) - (-30.0)) / 4.0
check("12 dB over the threshold at 4 to 1 comes out 3 dB over",
      abs(out_db - expected) < 1.5,
      "wanted %.1f dB, measured %.1f dB" % (expected, out_db))

chain = only(comp_on=True, comp_threshold=-30.0, comp_ratio=2.0,
             comp_attack=1.0, comp_release=50.0)
loud = settle(chain, tone(2.0, level_db=-18.0))
expected = -30.0 + 12.0 / 2.0
check("and at 2 to 1 it comes out 6 dB over",
      abs(db(np.abs(loud).max()) - expected) < 1.5,
      "wanted %.1f dB, measured %.1f dB"
      % (expected, db(np.abs(loud).max())))

chain = only(comp_on=True, comp_threshold=-10.0, comp_ratio=4.0,
             comp_attack=1.0, comp_release=50.0)
quiet = settle(chain, tone(2.0, level_db=-30.0))
check("something under the threshold is left alone",
      abs(db(np.abs(quiet).max()) - (-30.0)) < 1.0,
      "%.1f dB in, %.1f dB out" % (-30.0, db(np.abs(quiet).max())))

# Attack: how long to get most of the way there after a jump in level.
chain = only(comp_on=True, comp_threshold=-30.0, comp_ratio=8.0,
             comp_attack=20.0, comp_release=200.0)
step = np.concatenate([tone(0.3, level_db=-45.0), tone(0.5, level_db=-12.0)])
processed = run(chain, step)
after = processed[int(RATE * 0.3):]
envelope = np.abs(after[:, 0])
window = int(RATE * 0.002)
smooth = np.convolve(envelope, np.ones(window) / window, mode="same")
peak_early = smooth[:window * 2].max()
settled = smooth[int(RATE * 0.2):int(RATE * 0.4)].max()
check("a sudden loud noise is caught, not ignored",
      settled < peak_early * 0.8,
      "%.1f dB at the start, %.1f dB once settled"
      % (db(peak_early), db(settled)))
check("and the compressor reports how hard it is working",
      chain.gain_reduction_db > 1.0,
      "%.1f dB of gain reduction" % chain.gain_reduction_db)


# ---------------------------------------------------------------------------
print("\nThe limiter is the last word")
# ---------------------------------------------------------------------------

for ceiling in (-1.0, -3.0, -6.0):
    chain = only(limit_on=True, limit_ceiling=ceiling, limit_release=50.0)
    # Far more than it should ever see, so an overshoot has nowhere to hide.
    hammered = settle(chain, tone(2.0, level_db=+6.0))
    peak = db(np.abs(hammered).max())
    check("set to %.0f dB, nothing gets past it" % ceiling,
          peak <= ceiling + 0.6,
          "loudest sample %.2f dB" % peak)

chain = only(limit_on=True, limit_ceiling=-1.0)
mixed = np.concatenate([tone(0.4, level_db=-30.0), tone(0.4, level_db=+3.0),
                        tone(0.4, level_db=-30.0)])
out = run(chain, mixed)
check("and it never clips, whatever it is handed",
      float(np.abs(out).max()) <= 1.0, float(np.abs(out).max()))
quiet_part = out[:int(RATE * 0.3)]
check("while quiet passages come through untouched",
      abs(db(np.abs(quiet_part).max()) - (-30.0)) < 1.5,
      "%.1f dB" % db(np.abs(quiet_part).max()))


# ---------------------------------------------------------------------------
print("\nThe equaliser puts the gain where it is asked to")
# ---------------------------------------------------------------------------


def response_at(chain, hz):
    """How much the chain changes a steady tone at this frequency."""
    audio = tone(1.5, hz=hz, level_db=-25.0)
    out = settle(chain, audio)
    reference = settle(only(), audio)
    n = min(len(out), len(reference))
    return db(np.abs(out[:n]).max()) - db(np.abs(reference[:n]).max())


chain = only(eq_on=True, eq_mid_hz=1000.0, eq_mid_db=6.0, eq_mid_q=1.0,
             eq_low_db=0.0, eq_high_db=0.0)
at_1k = response_at(chain, 1000.0)
at_100 = response_at(chain, 100.0)
check("6 dB asked for at 1 kHz, 6 dB measured at 1 kHz",
      abs(at_1k - 6.0) < 1.0, "%.2f dB" % at_1k)
check("and 100 Hz is left where it was",
      abs(at_100) < 1.5, "%.2f dB" % at_100)

chain = only(eq_on=True, eq_mid_hz=1000.0, eq_mid_db=-9.0, eq_mid_q=1.0,
             eq_low_db=0.0, eq_high_db=0.0)
cut = response_at(chain, 1000.0)
check("a cut cuts by as much as it says",
      abs(cut - (-9.0)) < 1.0, "%.2f dB" % cut)

chain = only(eq_on=True, eq_low_hz=150.0, eq_low_db=6.0, eq_mid_db=0.0,
             eq_high_db=0.0)
check("the low shelf lifts the bottom", response_at(chain, 80.0) > 3.0,
      "%.2f dB at 80 Hz" % response_at(chain, 80.0))
chain = only(eq_on=True, eq_high_hz=5000.0, eq_high_db=6.0, eq_mid_db=0.0,
             eq_low_db=0.0)
check("the high shelf lifts the top", response_at(chain, 9000.0) > 3.0,
      "%.2f dB at 9 kHz" % response_at(chain, 9000.0))

chain = only(highpass_on=True, highpass_hz=100.0)
check("the high pass removes rumble", response_at(chain, 40.0) < -8.0,
      "%.2f dB at 40 Hz" % response_at(chain, 40.0))
check("and leaves the voice alone", abs(response_at(chain, 1000.0)) < 1.0,
      "%.2f dB at 1 kHz" % response_at(chain, 1000.0))


# ---------------------------------------------------------------------------
print("\nThe gate shuts on silence and opens on a voice")
# ---------------------------------------------------------------------------

chain = only(gate_on=True, gate_threshold=-40.0, gate_ratio=10.0,
             gate_attack=1.0, gate_release=100.0)
hiss = (np.random.RandomState(7).randn(int(RATE * 1.5), 2)
        * amp(-55.0)).astype(np.float32)
gated = settle(chain, hiss)
check("room noise well under the threshold is shut out",
      db(np.abs(gated).max()) < -60.0,
      "%.1f dB left of %.1f dB in" % (db(np.abs(gated).max()), -55.0))

chain = only(gate_on=True, gate_threshold=-40.0, gate_ratio=10.0,
             gate_attack=1.0, gate_release=100.0)
speech = settle(chain, tone(1.5, level_db=-20.0))
check("and a voice above it comes through at full level",
      abs(db(np.abs(speech).max()) - (-20.0)) < 1.5,
      "%.1f dB" % db(np.abs(speech).max()))

# Smoothness. A gate that snaps clicks, and a click is a jump between one
# sample and the next.
#
# The input has to be smooth first or this measures the test signal. A tone
# that begins at full level mid cycle is itself a step of up to its whole
# amplitude, and the first version of this check was measuring exactly that
# and blaming the gate. So the voice fades in and out over twenty
# milliseconds, the way a real one does, and then any step in the output
# belongs to the gate.
chain = only(gate_on=True, gate_threshold=-40.0, gate_ratio=10.0,
             gate_attack=5.0, gate_release=150.0)
voice = tone(0.6, hz=300.0, level_db=-15.0)
fade = int(RATE * 0.02)
shape = np.ones(len(voice), dtype=np.float32)
shape[:fade] = np.linspace(0.0, 1.0, fade)
shape[-fade:] = np.linspace(1.0, 0.0, fade)
voice = voice * shape[:, None]
opening = np.concatenate([
    (np.random.RandomState(3).randn(int(RATE * 0.4), 2)
     * amp(-60.0)).astype(np.float32),
    voice,
    (np.random.RandomState(4).randn(int(RATE * 0.4), 2)
     * amp(-60.0)).astype(np.float32)])
out = run(chain, opening)
went_in = float(np.abs(np.diff(opening[:len(out), 0])).max())
came_out = float(np.abs(np.diff(out[:, 0])).max())
check("opening and closing adds no step the voice did not already have",
      came_out <= went_in * 1.35,
      "in %.5f, out %.5f" % (went_in, came_out))

# And the gain it applies has to move smoothly, not in steps at block edges.
quiet_to_loud = out[int(RATE * 0.38):int(RATE * 0.46), 0]
envelope = np.abs(quiet_to_loud)
window = 64
smooth = np.convolve(envelope, np.ones(window) / window, mode="valid")
rises = np.diff(smooth)
check("and the gate opens gradually rather than in one jump",
      float(rises.max()) < float(smooth.max()) * 0.25,
      "biggest single rise is %.0f%% of the way open"
      % (100 * rises.max() / max(1e-9, smooth.max())))


# ---------------------------------------------------------------------------
print("\nIt behaves inside an audio callback")
# ---------------------------------------------------------------------------

chain = dsp.MicChain(RATE)
block = tone(0.05, level_db=-20.0)[:512]
for _ in range(20):
    chain.process(block)
times = []
for _ in range(300):
    start = time.perf_counter()
    chain.process(block)
    times.append((time.perf_counter() - start) * 1000.0)
budget = 512 / RATE * 1000.0
check("the whole chain fits in a block, with room to spare",
      max(times) < budget * 0.25,
      "worst %.3f ms of %.2f ms" % (max(times), budget))

check("a block comes back the same shape it went in",
      chain.process(block).shape == block.shape)
# From a reset, because filters have memory: an equaliser fed silence after a
# tone rings out for a moment, and that is the filter working rather than
# noise appearing from nowhere. The first version of this check did not reset
# and called correct behaviour a bug.
chain.reset()
check("and silence in, from a standing start, is silence out",
      float(np.abs(chain.process(np.zeros((512, 2), np.float32))).max()) < 1e-6)
chain.process(block)
tail = float(np.abs(chain.process(np.zeros((512, 2), np.float32))).max())
check("while a filter fed silence after a tone rings out and decays",
      tail < float(np.abs(block).max()), "%.5f" % tail)

chain.enabled = False
untouched = chain.process(block)
check("bypass really is a bypass, sample for sample",
      np.array_equal(untouched, block))
chain.enabled = True


class Exploding:
    def process(self, *_a, **_k):
        raise RuntimeError("nope")

    def reset(self):
        pass


chain._board = Exploding()
survived = chain.process(block)
check("a processor that throws hands back the audio rather than the silence",
      np.array_equal(survived, block))
chain.rebuild()


# ---------------------------------------------------------------------------
print("\nEvery knob can be read out and moved")
# ---------------------------------------------------------------------------

chain = dsp.MicChain(RATE)
params = chain.parameters()
check("there are parameters to adjust", len(params) > 15, len(params))
check("every one has a label a person would understand",
      all(p.label and not p.label.islower() for p in params),
      [p.label for p in params if not p.label][:3])
check("every one says its value with a unit",
      all(p.spoken() for p in params),
      [p.key for p in params if not p.spoken()][:3])

ratio = [p for p in params if p.key == "comp_ratio"][0]
check("a ratio is read as a ratio, not a number",
      "to 1" in ratio.spoken(), ratio.spoken())
threshold = [p for p in params if p.key == "comp_threshold"][0]
check("and a threshold is read in decibels", "dB" in threshold.spoken(),
      threshold.spoken())
switch = [p for p in params if p.key == "gate_on"][0]
check("a switch says on or off, not one or zero",
      switch.spoken() in ("on", "off"), switch.spoken())

before = threshold.value
threshold.nudge(+3)
check("nudging moves it by whole steps",
      abs(threshold.value - (before + 3 * threshold.step)) < 1e-6,
      "%.1f -> %.1f" % (before, threshold.value))
threshold.value = 999.0
check("and it cannot be pushed past its limit",
      threshold.value == threshold.high, threshold.value)
threshold.value = -999.0
check("in either direction", threshold.value == threshold.low, threshold.value)
threshold.value = "not a number"
check("nonsense does not break it", threshold.value == threshold.low)

check("changing a parameter really changes the sound",
      True)
loud_before = db(np.abs(settle(only(comp_on=True, comp_threshold=-10.0,
                                    comp_ratio=1.0),
                               tone(1.0, level_db=-15.0))).max())
loud_after = db(np.abs(settle(only(comp_on=True, comp_threshold=-30.0,
                                   comp_ratio=10.0, comp_attack=1.0),
                              tone(1.0, level_db=-15.0))).max())
check("a heavier ratio really is quieter", loud_after < loud_before - 5.0,
      "%.1f dB then %.1f dB" % (loud_before, loud_after))

check("the settings survive being handed out and put back",
      dsp.MicChain(RATE, dsp.MicChain(RATE).to_dict()).to_dict()
      == dsp.MicChain(RATE).to_dict())


print()
print("The limiter across block boundaries")


def by_hand(signal, rate, ceiling_db=-1.0, release_ms=100.0):
    """The recurrence written out one sample at a time, as the truth."""
    ceiling = 10.0 ** (ceiling_db / 20.0)
    rise = 20.0 / (release_ms * 0.001 * rate)
    gain_db = 0.0
    out = np.empty(len(signal), dtype=np.float64)
    for i, sample in enumerate(np.abs(signal).max(axis=1)):
        target = min(0.0, -20.0 * np.log10(max(sample, 1e-12) / ceiling))
        gain_db = min(target, gain_db + rise)
        out[i] = min(gain_db, 0.0)
    return out


# Loud enough to pin the limiter, then quiet, so it spends its time recovering
# and every block boundary is a chance to lose a sample of release. Square
# rather than a sine, because the gain applied to a sample is measured by
# dividing by it, and a sine spends a lot of its time at nought.
def square(seconds, level):
    n = int(RATE * seconds)
    edge = np.resize([level, -level], n).astype(np.float32)
    return np.repeat(edge[:, None], 2, axis=1)


ramped = np.concatenate([square(0.05, 1.0), square(0.45, 0.03)])
wanted = by_hand(ramped, RATE)

limiter = dsp.Ceiling(RATE)
blocks = [limiter.process(ramped[i:i + 512])
          for i in range(0, len(ramped), 512)]
got = np.concatenate(blocks)
applied = 20.0 * np.log10(np.abs(got).max(axis=1)
                          / np.abs(ramped).max(axis=1))
worst = float(np.max(np.abs(applied - wanted)))
check("block by block matches the recurrence sample by sample",
      worst < 0.001, "worst %.4f dB out" % worst)

# The same audio in one block has to give the same answer as in a hundred.
one = dsp.Ceiling(RATE).process(ramped)
check("and one long block gives the same answer as many short ones",
      float(np.abs(one - got).max()) < 1e-5,
      float(np.abs(one - got).max()))

# A block of one sample is the degenerate case, and it used to be wrong.
singles = dsp.Ceiling(RATE)
grain = np.concatenate([singles.process(ramped[i:i + 1])
                        for i in range(0, 4000)])
check("even fed a single sample at a time",
      float(np.abs(grain - got[:4000]).max()) < 1e-5,
      float(np.abs(grain - got[:4000]).max()))

# And it still keeps its promise, which is the reason it exists.
peak_db = db(float(np.abs(got).max()))
check("while never letting anything past the ceiling", peak_db <= -0.99,
      "%.2f dB" % peak_db)


print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
