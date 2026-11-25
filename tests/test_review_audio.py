"""Review of 24 November 2026, Area 3: audio.

    python tools/run_private.py tests/test_review_audio.py

Every item has checks that fail on 3.10.1 (a3767e3) and pass on the fix;
the others are guards that what was already right stayed right. Ten items,
in the order of the brief:

  1. a bed started under an open microphone came in 8 dB loud;
  2. previews played out of bank 1's card with a monitor card set;
  3. Stop everything with the stop fade off clicked;
  4. "mix" averaged a microphone with the other input's hiss, 6 dB down;
  5. the voice chain kept the rate it started at;
  6. nothing stopped the send's far end being captured back in;
  7. a monitor card at another rate played the inputs at the wrong pitch;
  8. the microphone and source rings had no target fill;
  9. "System default" opened through MME, about 200 ms;
 10. duck while talking, a second stage under the open microphone's duck.

Step 3, Mark's findings on e26e98d and b157d05, each with checks that fail
on b157d05:

  S1. the send's loop guard refused working sends: it is decided by the
      virtual cable's own naming now, and a physical card is never refused;
  S2. two talkers on two inputs: the second lost the first 2 s of each turn;
  S3. one inf or NaN sample silenced the monitor card's conversion for good;
  S10. a read a few ms short was a 21 ms hole and 10.7 ms more delay after.

Nothing here opens a sound card or a microphone and nothing makes a sound.
The mixers run with no stream and are read off `render`; where a stream is
opened, `sounddevice` is a stand-in that records what it was asked for;
every `MicInput.start` the frame could reach is replaced with one that opens
nothing; and the microphone is driven by handing its callback samples, as a
sound card would. Keys and menu items are proved through their BINDINGS.
"""

import math
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-audio-")

import numpy as np                                     # noqa: E402
import soundfile as sf                                 # noqa: E402

from dropdeck import constants as C                    # noqa: E402
from dropdeck import dsp                               # noqa: E402
from dropdeck import micinput                          # noqa: E402
from dropdeck import mixer as mixermod                 # noqa: E402
from dropdeck import routing                           # noqa: E402
from dropdeck import send as sendmod                   # noqa: E402
from dropdeck import sources as sourcesmod             # noqa: E402
from dropdeck.audiofile import CHANNELS                # noqa: E402
from dropdeck.board import Board                       # noqa: E402
from dropdeck.micinput import MicInput                 # noqa: E402
from dropdeck.mixer import Mixer, MixerGroup           # noqa: E402

RATE = 48000
BLOCK = C.BLOCKSIZE
CHECKS = []
FAILED = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    if not condition:
        FAILED.append(label + (("  " + str(detail)) if detail != "" else ""))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" and not condition else ""))


def heading(text):
    print("\n" + text)


def section(label, body):
    """One item. A raise is a failed check, so HEAD runs to the end."""
    try:
        body()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stdout)
        check("%s (raised %s: %s)" % (label, type(exc).__name__, exc), False)


def sine(hz, seconds, amp=0.5, rate=RATE, start=0):
    n = np.arange(start, start + int(seconds * rate), dtype=np.float64)
    wave = (amp * np.sin(2 * np.pi * hz * n / rate)).astype(np.float32)
    return np.repeat(wave[:, None], CHANNELS, axis=1)


def db(x):
    return 20.0 * math.log10(max(float(x), 1e-12))


def rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) \
        if len(x) else 0.0


def render(m, seconds, frames=BLOCK):
    out = [m.render(frames).copy() for _ in range(int(seconds * RATE) // frames)]
    return np.concatenate(out)


def windows_db(x, ms=10, rate=RATE):
    n = int(rate * ms / 1000)
    return [db(rms(x[i:i + n])) for i in range(0, len(x) - n + 1, n)]


class Capture:
    """Stands in for an AirBus or the send's bus: keeps what it is given."""

    def __init__(self):
        self.blocks = []

    def write(self, key, block, rate=None):
        self.blocks.append(np.array(block, copy=True))

    def peak(self):
        return max((float(np.abs(b).max()) for b in self.blocks if len(b)),
                   default=0.0)


TMP = tempfile.mkdtemp(prefix="dropdeck-audio-files-")


def wav(name, hz, seconds, amp=0.5):
    path = os.path.join(TMP, name)
    sf.write(path, sine(hz, seconds, amp), RATE)
    return path


def open_mic(rate=RATE, duck_bus=None):
    """A MicInput that believes it is open, fed by hand. Nothing is opened."""
    mic = MicInput(duck_bus=duck_bus, samplerate=rate)
    mic.samplerate = rate
    mic.stream = object()
    mic.channels_open = 2
    mic._reset_ring()
    return mic


def feed(mic, block):
    mic._callback(np.ascontiguousarray(block, dtype=np.float32), len(block),
                  None, None)


# ===========================================================================
heading("1. A bed started under an open microphone comes in at the duck")


def item_1():
    def bed_level(publish):
        m = Mixer(open_stream=False, samplerate=RATE)
        mic = MicInput(duck_bus=m.duck_bus, samplerate=RATE)
        publish(mic, m)
        m.play_samples(10, sine(220.0, 2.0), bus=C.BUS_BED, gain=1.0,
                       fade_in=0.0)
        env = windows_db(render(m, 1.0)[:, 0])
        return env

    def mic_open(mic, m):
        mic._publish(True)              # what opening the microphone does
        render(m, 0.2)                  # nothing playing meanwhile

    env = bed_level(mic_open)
    full = db(0.5 / math.sqrt(2))
    floor = full + C.DEFAULT_DUCK_DB
    print("     measured: first 10 ms %+.1f dB against the ducked level, at "
          "50 ms %+.1f dB" % (env[0] - env[-1], env[5] - env[-1]))
    check("its first 10 ms are at the ducked level, not up to 8 dB over",
          abs(env[0] - env[-1]) < 0.5, "%+.1f dB" % (env[0] - env[-1]))
    check("and the ducked level is the duck depth below full",
          abs(env[-1] - floor) < 0.3, "%.1f against %.1f" % (env[-1], floor))

    def mic_closed(mic, m):
        mic._publish(True)
        render(m, 0.2)
        mic._publish(False)
        render(m, 0.05)

    env = bed_level(mic_closed)
    check("with the microphone closed again it starts at full level",
          abs(env[0] - full) < 0.3 and abs(env[-1] - full) < 0.3,
          "%.1f and %.1f against %.1f" % (env[0], env[-1], full))

    m = Mixer(open_stream=False, samplerate=RATE)
    m.ducking = False
    mic = MicInput(duck_bus=m.duck_bus, samplerate=RATE)
    mic._publish(True)
    render(m, 0.2)
    m.play_samples(10, sine(220.0, 2.0), bus=C.BUS_BED, gain=1.0, fade_in=0.0)
    env = windows_db(render(m, 0.3)[:, 0])
    check("with ducking off it is at full level throughout",
          abs(env[0] - full) < 0.3 and abs(env[-1] - full) < 0.3)


section("item 1", item_1)

# ===========================================================================
heading("2. A preview plays where the presenter listens, never down bank 1")

PREVIEW = wav("preview.wav", 660.0, 1.0)


def item_2():
    def play(monitor):
        group = MixerGroup(bank_devices={b: 901 for b in range(1, 5)},
                           open_stream=False, monitor_device=monitor)
        air, sent = Capture(), Capture()
        group.air_tap = air
        group.send_tap = sent
        group.play_preview(PREVIEW)
        heard = {}
        for _ in range(40):
            for key, m in list(group._mixers.items()):
                heard[key] = max(heard.get(key, 0.0),
                                 float(np.abs(m.render(BLOCK)).max()))
        group.close()
        return heard, air, sent

    level = 0.5 * C.DEFAULT_SFX_VOLUME          # the sound fader, as a pad
    heard, air, sent = play(903)
    check("with a monitor card set, the monitor card plays the preview",
          abs(heard.get(903, 0.0) - level) < 0.01, heard)
    check("and bank 1's card, which may be a cable or a desk, plays nothing",
          heard.get(901, 1.0) < 1e-6, heard)
    check("it never reaches the stream or a recording (the loop, checked)",
          air.peak() < 1e-6, air.peak())
    check("nor the send", sent.peak() < 1e-6, sent.peak())
    heard, air, sent = play(None)
    check("with no monitor card it plays out of bank 1's card, as before",
          abs(heard.get(901, 0.0) - level) < 0.01, heard)
    check("and still not on air", air.peak() < 1e-6 and sent.peak() < 1e-6)


section("item 2", item_2)

# ===========================================================================
heading("3. Stop everything with the stop fade off ramps instead of clicking")

NATURAL_997 = 0.7 * 2 * math.pi * 997.0 / RATE


def stop_step(stop):
    m = Mixer(open_stream=False, samplerate=RATE)
    m.play_samples(0, sine(997.0, 2.0, 0.7), bus=C.BUS_SFX, gain=1.0,
                   fade_out=C.FADE_OUT_SFX)
    for _ in range(7):
        m.render(BLOCK)
    last = float(m.render(331)[-1, 0])          # land mid cycle
    stop(m)
    nxt = m.render(BLOCK)[:, 0]
    seq = np.concatenate([[last], nxt])
    worst = float(np.abs(np.diff(seq)).max())
    m.render(BLOCK)
    return last, worst, float(abs(nxt[-1])), m.voice_count()


def item_3():
    last, worst, tail, left = stop_step(lambda m: m.stop_all(fade_out=0.0))
    print("     measured: last sample %+.3f, worst step after the stop %.3f "
          "(a clean 997 Hz at this level steps %.3f)" % (last, worst,
                                                       NATURAL_997))
    check("stop_all with no fade steps no more than the tone itself does",
          worst <= NATURAL_997 * 1.05, "%.3f" % worst)
    check("and it is silent by the end of that block", tail < 1e-4, tail)
    check("and the voice is gone after it", left == 0, left)
    _l, slot_worst, _t, _n = stop_step(lambda m: m.stop_slot(0, fade_out=0.0))
    check("the same as stopping a single pad abruptly",
          slot_worst <= NATURAL_997 * 1.05, "%.3f" % slot_worst)
    m = Mixer(open_stream=False, samplerate=RATE)
    m.play_samples(0, sine(997.0, 2.0), bus=C.BUS_SFX)
    m.stop_all(at_once=True)
    check("taking a stream down still clears every voice at once",
          m.voice_count() == 0)


section("item 3", item_3)

# ===========================================================================
heading("4. A microphone on one input of two arrives at its own level")

VOICE_AMP = 0.3
HISS = 10 ** (-75 / 20.0)


def item_4():
    rnd = np.random.default_rng(4)

    def run(mic, seconds, left, right, start=0):
        out = []
        for i in range(int(seconds * RATE) // BLOCK):
            n = np.arange(start + i * BLOCK, start + (i + 1) * BLOCK)
            pair = np.stack([left(n), right(n)], axis=1).astype(np.float32)
            feed(mic, pair)
            out.append(mic.read(BLOCK)[:, 0])
        return np.concatenate(out)

    voice = lambda n: VOICE_AMP * np.sin(2 * np.pi * 220.0 * n / RATE)  # noqa
    hiss = lambda n: rnd.normal(0.0, HISS, len(n))                     # noqa
    quiet = lambda n: np.zeros(len(n))                                  # noqa
    second = lambda n: VOICE_AMP * np.sin(2 * np.pi * 330.0 * n / RATE)  # noqa
    down12 = lambda n: 0.25 * VOICE_AMP * np.sin(                        # noqa
        2 * np.pi * 330.0 * n / RATE)

    mic = open_mic()
    mic.monitor = True
    out = run(mic, 3.0, voice, hiss)
    own = db(VOICE_AMP / math.sqrt(2))
    early = db(rms(out[int(0.3 * RATE):int(0.6 * RATE)]))
    late = db(rms(out[int(2.0 * RATE):]))
    print("     measured: %+.1f dB against the voice alone in the first "
          "second, %+.1f dB after two" % (early - own, late - own))
    check("after about a second the voice is at its own level, not 6 dB down",
          abs(late - own) < 0.2, "%+.2f dB" % (late - own))
    natural = VOICE_AMP * 2 * math.pi * 220.0 / RATE
    body = out[int(0.2 * RATE):]
    check("and the handover glides: no step bigger than the voice's own",
          float(np.abs(np.diff(body)).max()) <= natural * 1.1,
          "%.4f against %.4f" % (float(np.abs(np.diff(body)).max()), natural))
    pause = run(mic, 2.0, quiet, hiss, start=3 * RATE)
    check("in a pause the other input's hiss is not in it",
          db(rms(pause[int(0.5 * RATE):])) < -100.0,
          "%.1f dBFS" % db(rms(pause[int(0.5 * RATE):])))
    back = run(mic, 1.0, voice, hiss, start=5 * RATE)
    check("and the voice after the pause is straight back at its level",
          abs(db(rms(back[int(0.1 * RATE):])) - own) < 0.2,
          "%+.2f" % (db(rms(back[int(0.1 * RATE):])) - own))
    sides = []
    for i in range(int(2.0 * RATE) // BLOCK):
        n = np.arange(6 * RATE + i * BLOCK, 6 * RATE + (i + 1) * BLOCK)
        feed(mic, np.stack([voice(n), down12(n)], axis=1).astype(np.float32))
        mic.read(BLOCK)
        sides.append(getattr(mic, "_side", "none"))
    changes = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
    check("a second input coming up 12 dB under the first is a second "
          "talker: both are back at once and it stays that way, no flapping",
          sides[0] is None and changes == 0, (sides[:3], changes))
    both = run(mic, 2.5, voice, second, start=8 * RATE)
    # Two different voices at one level, averaged, sit 3 dB under either.
    averaged = db(rms(both[int(2.0 * RATE):])) - own
    check("when both inputs carry a voice it goes back to the average",
          getattr(mic, "_side", "none") is None and abs(averaged + 3.01) < 0.3,
          (getattr(mic, "_side", "none"), "%+.2f" % averaged))

    fresh = open_mic()
    fresh.monitor = True
    run(fresh, 2.0, voice, down12)
    check("from the average, one input 12 dB down is not enough to switch",
          getattr(fresh, "_side", "none") is None)

    source = sourcesmod.Source(name="Line", device_name="Line in",
                               samplerate=RATE, monitor=True)
    source.input.samplerate = RATE
    source.input.stream = object()
    source.input._reset_ring()
    out = run(source.input, 3.0, voice, hiss)
    check("a source keeps the plain average, for stereo program audio",
          abs(db(rms(out[int(2.0 * RATE):])) - (own - 6.02)) < 0.2,
          "%+.2f" % (db(rms(out[int(2.0 * RATE):])) - own))


section("item 4", item_4)

# ===========================================================================
heading("5. The voice chain follows the output rate")


def highpass_gain(chain, rate, hz=80.0):
    n = np.arange(int(0.6 * rate))
    x = (0.25 * np.sin(2 * np.pi * hz * n / rate)).astype(np.float32)
    block = np.repeat(x[:, None], CHANNELS, axis=1)
    out = np.concatenate([chain.process(block[i:i + BLOCK])
                          for i in range(0, len(block) - BLOCK, BLOCK)])
    half = len(out) // 2
    return db(rms(out[half:, 0]) / rms(block[half:len(out), 0]))


ONLY_HIGHPASS = {"gate_on": False, "eq_on": False, "comp_on": False,
                 "limit_on": False, "highpass_on": True, "highpass_hz": 80.0}


def item_5():
    if not dsp.available():
        check("pedalboard is installed, so there is a chain to check", False)
        return
    chain = dsp.MicChain(48000, ONLY_HIGHPASS)
    mic = MicInput(samplerate=48000)
    mic.chain = chain
    before = highpass_gain(chain, 96000)
    mic.set_output_rate(96000)
    after = highpass_gain(chain, 96000)
    print("     measured at 96 kHz, 80 Hz through the 80 Hz high pass: "
          "%.1f dB before following, %.1f dB after" % (before, after))
    check("set_output_rate moves the chain to the new rate",
          getattr(chain, "samplerate", 0) == 96000,
          getattr(chain, "samplerate", 0))
    check("so the 80 Hz high pass is 3 dB down at 80 Hz, not an octave up",
          abs(after + 3.0) < 0.5, "%.2f dB" % after)


section("item 5", item_5)

# ===========================================================================
heading("6. The send's own far end is refused, said in a sentence")

CABLE_IN = "CABLE Input (VB-Audio Virtual Cable)"
CABLE_OUT = "CABLE Output (VB-Audio Virtual Cable)"


#: Real names, as Windows and PortAudio give them. The three physical cards
#: are the ones Mark's repro had refused (S1).
YETI_OUT = "Speakers (Yeti Stereo Microphone)"
YETI_MIC = "Microphone (Yeti Stereo Microphone)"
REALTEK_OUT = "Speakers (Realtek(R) Audio)"
REALTEK_MIC = "Microphone (Realtek(R) Audio)"
REALTEK_MIX = "Stereo Mix (Realtek(R) Audio)"
DVR_OUT = "Speakers (Audio Control (DVR))"
DVR_MIC = "Microphone (Audio Control (DVR))"
LOOPS = [
    (CABLE_IN, CABLE_OUT),
    ("CABLE-A Input (VB-Audio Cable A)", "CABLE-A Output (VB-Audio Cable A)"),
    ("CABLE-D Input (VB-Audio Cable D)", "CABLE-D Output (VB-Audio Cable D)"),
    ("VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)",
     "VoiceMeeter Output (VB-Audio VoiceMeeter VAIO)"),
    ("VoiceMeeter Aux Input (VB-Audio VoiceMeeter AUX VAIO)",
     "VoiceMeeter Aux Output (VB-Audio VoiceMeeter AUX VAIO)"),
    ("Voicemeeter Input (VB-Audio Voicemeeter VAIO)",
     "Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)"),
    ("Line 1 (Virtual Audio Cable)", "Line 1 (Virtual Audio Cable)"),
    ("Speakers (Focusrite USB Audio)", "Loopback 1 + 2 (Focusrite USB Audio)"),
    (REALTEK_OUT, REALTEK_MIX),
    # MME's 31 characters, which can end on a space.
    (CABLE_IN[:31], CABLE_OUT[:31]),
]
NOT_LOOPS = [
    (YETI_OUT, YETI_MIC), (REALTEK_OUT, REALTEK_MIC), (DVR_OUT, DVR_MIC),
    ("Speakers (Focusrite USB Audio)", "Analogue 1 + 2 (Focusrite USB Audio)"),
    (CABLE_IN, "CABLE-A Output (VB-Audio Cable A)"),
    ("CABLE-A Input (VB-Audio Cable A)", "CABLE-B Output (VB-Audio Cable B)"),
    ("Line 1 (Virtual Audio Cable)", "Line 2 (Virtual Audio Cable)"),
    ("VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)",
     "VoiceMeeter Aux Output (VB-Audio VoiceMeeter AUX VAIO)"),
    (YETI_OUT, CABLE_OUT), (CABLE_IN, YETI_MIC),
]


def item_6_rules():
    found = routing.captures_itself(
        CABLE_IN, [("Your microphone", YETI_MIC), ("Games call", CABLE_OUT)])
    check("a source on the far end of the send's cable is a loop",
          len(found) == 1 and "Games call" in found[0], found)
    check("the sentence names the input, the cable and what to do",
          found and CABLE_OUT in found[0] and CABLE_IN in found[0]
          and "back into itself" in found[0], found)
    wrong = [pair for pair in LOOPS if not routing.loops_back(*pair)]
    check("every known virtual cable's own other end is a loop: VB-Audio "
          "CABLE and A to D, VoiceMeeter, Virtual Audio Cable, a Focusrite "
          "Loopback and Stereo Mix, MME's cut names too", not wrong, wrong)
    wrong = [pair for pair in NOT_LOOPS if routing.loops_back(*pair)]
    check("S1: a physical card's own microphone is never one, and neither "
          "is another cable's end", not wrong, wrong)
    check("and nothing is known, nothing is refused",
          not routing.captures_itself("", [("S", CABLE_OUT)]))


section("item 6, the rule", item_6_rules)

# ===========================================================================
heading("7. A monitor card at another rate hears the inputs at their pitch")


def zero_cross_hz(x, rate):
    return float(np.sum((x[:-1] < 0) & (x[1:] >= 0))) * rate / len(x)


def item_7():
    rates = {901: 48000, 903: 44100}
    real_rate = Mixer.__dict__["_device_rate"]
    Mixer._device_rate = staticmethod(lambda device: rates.get(device, 48000))
    try:
        def monitored(member_kind, monitor=903):
            group = MixerGroup(bank_devices={b: 901 for b in range(1, 5)},
                               open_stream=False, monitor_device=monitor)
            mic = None
            extras = []
            if member_kind == "mic":
                mic = open_mic(48000)
                mic.monitor = True
                writer = mic
                size = BLOCK
            elif member_kind == "source":
                source = sourcesmod.Source(name="S", device_name="X",
                                           samplerate=48000, monitor=True)
                source.input.samplerate = 48000
                source.input.stream = object()
                source.input._reset_ring()
                writer = source.input
                group_members = [source]
                size = BLOCK
            else:
                send = sendmod.Send(device=None, samplerate=48000,
                                    open_stream=False)
                send.confidence.start()
                writer = send.confidence
                extras = [send.confidence]
                size = C.SEND_BLOCKSIZE
            members = group_members if member_kind == "source" else []
            group_source = sourcesmod.SourceGroup(mic, members, extras)
            group.monitor_source = group_source
            air = Capture()
            group.air_tap = air
            monitor_mixer = group.monitor_mixer
            out_rate = monitor_mixer.samplerate
            out_frames = out_rate // 100
            heard = []
            t_in = t_out = 0.0
            phase = 0
            while t_out < 8.0:
                if t_in <= t_out:
                    block = sine(1000.0, size / 48000.0, 0.5, 48000, phase)
                    phase += size
                    if member_kind == "send":
                        writer.offer(block)
                    else:
                        feed(writer, block[:, :1])
                    t_in += size / 48000.0
                else:
                    heard.append(monitor_mixer.render(out_frames)[:, 0].copy())
                    if monitor_mixer is not group.primary:
                        group.primary.render(480)
                    t_out += out_frames / float(out_rate)
            out = np.concatenate(heard)[-4 * out_rate:]
            natural = 0.5 * 2 * math.pi * 1000.0 / out_rate
            splices = int(np.sum(np.abs(np.diff(out)) > 2 * natural))
            return (zero_cross_hz(out, out_rate), splices, air.peak(),
                    group_source)

        for kind, said in (("mic", "the microphone"), ("source", "a source"),
                           ("send", "the confidence feed")):
            hz, splices, air_peak, _g = monitored(kind)
            print("     measured, %s on a 44.1 kHz monitor card with a 48 kHz "
                  "main output: 1000 Hz comes back as %.1f Hz, %d splices in "
                  "4 s" % (said, hz, splices))
            check("%s comes back at 1000 Hz" % said, abs(hz - 1000.0) < 2.0,
                  "%.1f Hz" % hz)
            check("%s has no splices" % said, splices == 0, splices)
            if kind == "send":
                check("and the confidence feed is never on the air (the loop, "
                      "checked)", air_peak < 1e-6, air_peak)
        hz, splices, _p, group_source = monitored("mic", monitor=None)
        check("with the monitor at the main output's rate nothing is converted",
              not getattr(group_source, "_adapters", {})
              and abs(hz - 1000.0) < 2.0 and splices == 0,
              (hz, splices))
    finally:
        Mixer._device_rate = real_rate


section("item 7", item_7)

# ===========================================================================
heading("8. The microphone's ring keeps a target fill, an hour each way")

NATURAL_1K = 0.5 * 2 * math.pi * 1000.0 / RATE
#: Half a sample in, so no sample of the tone is ever exactly zero.
TABLE = (0.5 * np.sin(2 * np.pi * 1000.0 * (np.arange(48 + 4096) + 0.5)
                      / RATE)).astype(np.float32)


def two_clocks(ppm, hours, write=BLOCK, read=480, jitter=0.0015, seed=1):
    """micinput._Ring between two clocks: a 1 kHz tone in, what comes out."""
    rnd = random.Random(seed)
    ring = micinput._Ring()
    ring.rate = RATE
    w_period = write / (RATE * (1 + ppm * 1e-6))
    r_period = read / float(RATE)
    t_w = t_r = 0.0
    written = 0
    prev = None
    worst = 0.0
    quiet_blocks = 0
    padded = 0
    late = []
    want = 0.5 / math.sqrt(2)
    k = 0
    end = hours * 3600.0
    while t_r < end:
        if t_w <= t_r + rnd.uniform(-jitter, jitter):
            start = written % 48
            block = TABLE[start:start + write]
            ring.write(np.stack([block, block], axis=1))
            written += write
            t_w += w_period
            continue
        out = ring.read(read)[:, 0]
        t_r += r_period
        k += 1
        if prev is None:
            if not np.any(out):
                continue
            prev = out[-1]          # the first block fades in: not a fault
            continue
        step = max(abs(float(out[0]) - float(prev)),
                   float(np.abs(np.diff(out)).max()))
        worst = max(worst, step)
        prev = out[-1]
        # The tone never lands on an exact zero, so any zero is padding.
        padded += int(np.count_nonzero(out == 0.0))
        if rms(out) < want * 0.944:            # more than 0.5 dB down
            quiet_blocks += 1
        if k % 1000 == 0:
            late.append(ring.available / 48.0)
    return worst, quiet_blocks + padded, min(late), max(late), ring


def item_8():
    for ppm in (30, -30, 100, -100):
        worst, quiet, low, high, ring = two_clocks(ppm, 1.0)
        print("     measured over an hour at %+d ppm: worst step %.3f (a clean "
              "tone %.3f), %d blocks more than 0.5 dB down, held %.1f to "
              "%.1f ms, %s drops, %s repeats, %s holes"
              % (ppm, worst, NATURAL_1K, quiet, low, high,
                 getattr(ring, "drops", "no"), getattr(ring, "inserts", "no"),
                 getattr(ring, "holes", "no")))
        check("%+d ppm for an hour: no step bigger than the tone's own" % ppm,
              worst <= NATURAL_1K * 1.05, "%.3f" % worst)
        check("%+d ppm: no hole and no dip, not one sample of padding" % ppm,
              quiet == 0, quiet)
        check("%+d ppm: the delay stays under 25 ms all hour" % ppm,
              high < 25.0, "%.1f ms" % high)

    # A writer that stops, and starts again, landing mid cycle both times.
    ring = micinput._Ring()
    ring.rate = RATE
    written = 0
    size = 509
    for _ in range(30):
        b = TABLE[written % 48:written % 48 + size]
        ring.write(np.stack([b, b], axis=1))
        written += size
        ring.read(480)
    tail = np.concatenate([ring.read(480)[:, 0] for _ in range(6)])
    check("a writer that stops fades out rather than stopping dead",
          float(np.abs(np.diff(tail)).max()) <= NATURAL_1K * 1.05
          and not np.any(tail[-480:]),
          float(np.abs(np.diff(tail)).max()))
    check("and the ring says it had a hole", getattr(ring, "holes", 0) >= 1)
    out = [tail[-1:]]
    for _ in range(10):
        b = TABLE[written % 48:written % 48 + size]
        ring.write(np.stack([b, b], axis=1))
        written += size
        out.append(ring.read(480)[:, 0])
    out = np.concatenate(out)
    check("and comes back faded in, no click", float(
        np.abs(np.diff(out)).max()) <= NATURAL_1K * 1.05,
        float(np.abs(np.diff(out)).max()))

    big = micinput._Ring()
    big.rate = RATE
    for i in range(10):
        b = TABLE[(i * BLOCK) % 48:(i * BLOCK) % 48 + BLOCK]
        big.write(np.stack([b, b], axis=1))
    got = big.read(RATE)[:, 0]
    check("a read bigger than the ring can hold is handed what there is, "
          "never silence for ever (test_proccapture reads a second at once)",
          int(np.count_nonzero(got)) >= 10 * BLOCK - 2,   # faded both ends
          int(np.count_nonzero(got)))

    from dropdeck import proccapture
    capture = proccapture.ProcessCapture(samplerate=44100)
    check("a program source's rings are the same, read at its rate",
          hasattr(capture._monitor, "primed")
          and getattr(capture._monitor, "rate", 0) == 44100)
    send = sendmod.Send(device=None, samplerate=RATE, open_stream=False)
    send.confidence.start()
    t_w = t_r = 0.0
    short = 0
    rnd = random.Random(3)
    started = False
    offered = 0
    while t_r < 120.0:
        if t_w <= t_r + rnd.uniform(-0.0015, 0.0015):
            # Phase continuous and a quarter period in, so it is never 0.0.
            send.confidence.offer(sine(1000.0, C.SEND_BLOCKSIZE / RATE,
                                       start=offered + 12))
            offered += C.SEND_BLOCKSIZE
            t_w += C.SEND_BLOCKSIZE / (RATE * (1 - 100e-6))
        else:
            got = send.confidence.read(480)[:, 0]
            t_r += 480 / RATE
            if not started:
                started = bool(np.all(got != 0.0))
            else:
                short += int(np.count_nonzero(got == 0.0))
    check("the confidence feed has no holes either, 100 ppm slow, two "
          "minutes, not one sample of padding", started and short == 0, short)


section("item 8", item_8)

# ===========================================================================
heading("9. System default opens through WASAPI shared, MME only as a fall back")


class FakeStream:
    def __init__(self, device, kw):
        self.device = device
        self.kw = kw
        self.active = True
        self.latency = 0.022

    def start(self):
        pass

    def stop(self):
        self.active = False

    def abort(self):
        self.active = False

    def close(self):
        self.active = False


class FakeSD:
    """sounddevice, as far as opening goes: records what it is asked for and
    opens nothing. Indices and names are this machine's, read 24 November."""

    def __init__(self, wasapi_works=True):
        self.wasapi_works = wasapi_works
        self.asked = []
        self.apis = ({"name": "MME", "default_output_device": 6,
                      "default_input_device": 1},
                     {"name": "Windows WASAPI", "default_output_device": 22,
                      "default_input_device": 30})
        self.devices = {
            6: {"name": "Speakers (Yeti Stereo Microphon", "hostapi": 0,
                "default_samplerate": 44100.0, "max_output_channels": 2,
                "max_input_channels": 0, "index": 6},
            22: {"name": "Speakers (Yeti Stereo Microphone)", "hostapi": 1,
                 "default_samplerate": 48000.0, "max_output_channels": 2,
                 "max_input_channels": 0, "index": 22},
            1: {"name": "Microphone (Yeti Stereo Microph", "hostapi": 0,
                "default_samplerate": 44100.0, "max_output_channels": 0,
                "max_input_channels": 2, "index": 1},
            30: {"name": "Microphone (Yeti Stereo Microphone)", "hostapi": 1,
                 "default_samplerate": 48000.0, "max_output_channels": 0,
                 "max_input_channels": 2, "index": 30}}

    def query_hostapis(self, index=None):
        return self.apis if index is None else self.apis[index]

    def query_devices(self, device=None, kind=None):
        if device is None and kind == "output":
            return self.devices[6]
        if device is None and kind == "input":
            return self.devices[1]
        if device is None:
            return [self.devices[i] for i in sorted(self.devices)]
        return self.devices[device]

    def _open(self, direction, device, kw):
        self.asked.append((direction, device, dict(kw)))
        if device in (22, 30) and not self.wasapi_works:
            raise RuntimeError("Unanticipated host error [PaErrorCode -9999]")
        return FakeStream(device, kw)

    def OutputStream(self, device=None, **kw):
        return self._open("out", device, kw)

    def InputStream(self, device=None, **kw):
        return self._open("in", device, kw)


def item_9():
    real_mixer_sd, real_mic_sd = mixermod.sd, micinput.sd
    try:
        fake = FakeSD()
        mixermod.sd = micinput.sd = fake
        m = Mixer(device=None, open_stream=True)
        first = fake.asked[0] if fake.asked else ("", "nothing", {})
        check("System default opens Windows' default card through WASAPI",
              first[1] == 22, first[1])
        check("in shared mode: no exclusive settings are passed",
              "extra_settings" not in first[2], first[2])
        check("at the rate WASAPI has the card at", m.samplerate == 48000,
              m.samplerate)
        check("and it says nothing about falling back",
              getattr(m, "default_by_mme", None) is False)
        m.close()
        fake.asked.clear()
        chosen = Mixer(device=22, open_stream=True)
        check("a card chosen by name opens exactly that card",
              [a[1] for a in fake.asked] == [22], fake.asked)
        chosen.close()

        fake = FakeSD(wasapi_works=False)
        mixermod.sd = micinput.sd = fake
        group = MixerGroup(open_stream=True)
        check("if WASAPI will not open, MME (the PortAudio default) does",
              [a[1] for a in fake.asked] == [22, None], fake.asked)
        notices = group.take_notices() if hasattr(group, "take_notices") else []
        check("and that is said", len(notices) == 1
              and "slower" in notices[0], notices)
        group.set_bank_devices({})
        again = group.take_notices() if hasattr(group, "take_notices") else []
        check("once: rebuilding the outputs does not say it again",
              again == [], again)
        group.close()

        fake = FakeSD()
        micinput.sd = mixermod.sd = fake
        mic = MicInput(samplerate=48000)
        opened = mic.start()
        ins = [a for a in fake.asked if a[0] == "in"]
        check("the default microphone opens through WASAPI first (a stand-in "
              "sounddevice, nothing opened)",
              opened and ins and ins[0][1] == 30, ins[:1])
        check("in shared mode", ins and "extra_settings" not in ins[0][2])
        check("and reports how it came in", mic.opened_via == "Windows WASAPI",
              mic.opened_via)
        mic.stop()
        fake = FakeSD(wasapi_works=False)
        micinput.sd = mixermod.sd = fake
        mic = MicInput(samplerate=48000)
        opened = mic.start()
        ins = [a[1] for a in fake.asked if a[0] == "in"]
        check("if WASAPI refuses, the MME default opens",
              opened and ins[-1] is None and 30 in ins, ins)
        check("and the microphone knows it came the slow way",
              getattr(mic, "default_by_mme", None) is True)
        mic.stop()
    finally:
        mixermod.sd, micinput.sd = real_mixer_sd, real_mic_sd


section("item 9", item_9)

# ===========================================================================
heading("10. Duck while talking: further down only while the voice is going")


def item_10_mixer():
    def run(talk_duck=True, ducking=True, voice_from=0.3, voice_to=1.0,
            seconds=3.0):
        m = Mixer(open_stream=False, samplerate=RATE)
        m.ducking = ducking
        m.talk_duck = talk_duck
        m.talk_duck_db = C.DEFAULT_TALK_DUCK_DB
        mic = open_mic(RATE, duck_bus=m.duck_bus)
        mic.talk_detect = True
        mic._publish(True)
        m.monitor_source = mic
        mic.monitor = True
        m.play_samples(40, sine(220.0, seconds + 1), bus=C.BUS_BED, gain=1.0,
                       fade_in=0.0)
        bed = []
        for i in range(int(seconds * RATE) // BLOCK):
            t = i * BLOCK / float(RATE)
            amp = 0.2 if voice_from <= t < voice_to else 0.0
            feed(mic, sine(1000.0, BLOCK / RATE, amp, start=i * BLOCK)[:, :1])
            out = m.render(BLOCK)
            bed.append(out[:, 0])
        mix = np.concatenate(bed)
        return mix

    # The bed alone, measured with a 220 Hz band: the voice is at 1 kHz.
    def bed_db(mix, t0, t1):
        seg = mix[int(t0 * RATE):int(t1 * RATE)].astype(np.float64)
        n = np.arange(len(seg))
        ref = np.exp(-2j * np.pi * 220.0 * n / RATE)
        amp = 2.0 * abs(np.dot(seg, ref)) / len(seg)
        return db(amp)

    full = db(0.5)
    floor = full + C.DEFAULT_DUCK_DB
    talk = floor - C.DEFAULT_TALK_DUCK_DB
    mix = run()
    before = bed_db(mix, 0.2, 0.3)
    during = bed_db(mix, 0.5, 0.9)
    attack = bed_db(mix, 0.3 + C.TALK_DUCK_ATTACK + 0.012,
                    0.3 + C.TALK_DUCK_ATTACK + 0.022)
    hold = bed_db(mix, 1.0 + 0.3, 1.0 + 0.38)
    released = bed_db(mix, 1.0 + C.TALK_HOLD_SECONDS
                      + C.TALK_DUCK_RELEASE + 0.1, 2.9)
    print("     measured, against the open microphone's duck: before the "
          "voice %+.1f dB, %d ms after it starts %+.1f dB, while talking "
          "%+.1f dB, 300 ms after it stops %+.1f dB, after the hold and the "
          "release %+.1f dB" % (before - floor,
                                (C.TALK_DUCK_ATTACK + 0.012) * 1000,
                                attack - floor, during - floor, hold - floor,
                                released - floor))
    check("before the first word the music is already at the open "
          "microphone's duck, so no syllable can be clipped",
          abs(before - floor) < 0.3, "%+.2f" % (before - floor))
    check("while the voice is going it is %d dB further down"
          % C.DEFAULT_TALK_DUCK_DB, abs(during - talk) < 0.3,
          "%+.2f" % (during - floor))
    check("it gets there in about 30 ms", abs(attack - talk) < 0.5,
          "%+.2f" % (attack - floor))
    check("it holds through a pause shorter than 400 ms",
          abs(hold - talk) < 0.5, "%+.2f" % (hold - floor))
    check("and comes back up to the duck, not to full",
          abs(released - floor) < 0.3, "%+.2f" % (released - floor))
    off = run(talk_duck=False)
    check("off, which is the default, it is exactly the open microphone's "
          "duck", abs(bed_db(off, 0.5, 0.9) - floor) < 0.3)
    loose = run(ducking=False)
    check("with ducking off it does nothing at all, talking or not",
          abs(bed_db(loose, 0.5, 0.9) - full) < 0.3,
          "%+.2f" % (bed_db(loose, 0.5, 0.9) - full))

    group = MixerGroup(bank_devices={}, open_stream=False)
    group.talk_duck = True
    group.talk_duck_db = 9.0
    group.set_bank_devices({3: 902})
    check("rebuilding the outputs keeps it, on every card",
          all(m.talk_duck and m.talk_duck_db == 9.0 for m in group.mixers))
    group.close()


def item_10_board():
    board = Board()
    check("a new board has it off, 6 dB", board.talk_duck is False
          and board.talk_duck_db == C.DEFAULT_TALK_DUCK_DB)
    path = os.path.join(TMP, "talk.json")
    board.talk_duck = True
    board.talk_duck_db = 9.0
    board.save(path)
    again = Board.load(path)
    check("it is saved and loaded", again.talk_duck is True
          and again.talk_duck_db == 9.0)
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.pop("talk_duck", None)
    data.pop("talk_duck_db", None)
    data["duck_db"] = -9.0
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    old = Board.load(path)
    check("a board saved before it existed has it off",
          old.talk_duck is False and old.talk_duck_db == C.DEFAULT_TALK_DUCK_DB)
    data["talk_duck"] = "yes"
    data["talk_duck_db"] = 400
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    odd = Board.load(path)
    check("a hand edited board cannot switch it on with a string, or ask for "
          "400 dB", odd.talk_duck is False
          and odd.talk_duck_db == C.MAX_TALK_DUCK_DB)


section("item 10, the mixer", item_10_mixer)
section("item 10, the board", item_10_board)

# ===========================================================================
# The frame: the user's paths, through bindings, with nothing opened.
import wx                                               # noqa: E402

from dropdeck import board as boardmod                  # noqa: E402
from dropdeck import dialogs                            # noqa: E402
from dropdeck import globalhotkeys                      # noqa: E402
from dropdeck import secrets                            # noqa: E402
from dropdeck import ui as uimod                        # noqa: E402

app = wx.App(False)
wx.MessageBox = lambda *a, **kw: wx.OK
secrets.fetch = lambda name, prefix=None: None
secrets.store = lambda *a, **kw: True
secrets.forget = lambda *a, **kw: None

CARDS = {"Desk": 901, "Desk 96": 960, "Phones": 903, CABLE_IN: 911}
uimod.resolve_device = lambda spec: CARDS.get((spec or {}).get("name"))
uimod.resolve_input = lambda spec: None
sourcesmod.resolve_input = lambda spec: None
uimod.DropDeckFrame._start_update_check = lambda self: None
RATES = {901: 48000, 960: 96000, 903: 44100, 911: 48000}
Mixer._device_rate = staticmethod(lambda device: RATES.get(device, 48000))
from dropdeck import endpoints                          # noqa: E402


def _machine():
    E, R, P = endpoints.Endpoint, endpoints.RENDER, endpoints.CAPTURE
    found = []
    for side, full in ((R, YETI_OUT), (P, YETI_MIC), (R, REALTEK_OUT),
                       (P, REALTEK_MIC), (P, REALTEK_MIX), (R, DVR_OUT),
                       (P, DVR_MIC), (R, CABLE_IN), (P, CABLE_OUT)):
        name, card = full.split(" (", 1)
        found.append(E(side, name, card[:-1], 48000, 24, 2,
                       guid="{%08d}" % len(found)))
    return found


MACHINE = _machine()
endpoints.endpoints = lambda: list(MACHINE)
CARDS.update({YETI_OUT: 921, REALTEK_OUT: 922, DVR_OUT: 923})
DEFAULT_MIC = ["Microphone (Yeti Stereo Microphone)"]
micinput.default_input_name = lambda: DEFAULT_MIC[0]

#: No microphone and no source is ever opened from here.
OPENED = []


def never_open(self, device=None, other_routes=True):
    OPENED.append(device)
    self.last_error = "not opened in a test"
    return False


MicInput.start = never_open


class QuietGroup(MixerGroup):
    def __init__(self, *args, **kw):
        kw["open_stream"] = False
        super().__init__(*args, **kw)


uimod.MixerGroup = QuietGroup


class FakeHotkeys:
    def __init__(self, on_fire=None, on_problem=None):
        self.enabled = False
        self.bindings = {}
        self.failures = {}

    def set_bindings(self, bindings):
        self.bindings = dict(bindings)

    def start(self):
        self.enabled = True
        return True

    def stop(self):
        self.enabled = False

    def toggle(self):
        self.enabled = not self.enabled
        return self.enabled

    def count(self):
        return 0


globalhotkeys.GlobalHotkeys = FakeHotkeys
RealSend = sendmod.Send


class _Running:
    active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


class FakeSend(RealSend):
    def __init__(self, device=None, gain_db=0.0, **kw):
        super().__init__(device=device, samplerate=RATE, gain_db=gain_db,
                         open_stream=False)
        self.stream = _Running()

    def start(self):
        self.stream = _Running()
        return True


sendmod.Send = FakeSend


class Scripted(dialogs.SettingsDialog):
    script = None
    output = None

    def ShowModal(self):
        return Scripted.script(self)

    @property
    def chosen_device(self):
        if Scripted.output is not None:
            return Scripted.output
        return dialogs.SettingsDialog.chosen_device.fget(self)

    @property
    def chosen_bank_devices(self):
        return {}

    @property
    def chosen_mic_device(self):
        return (None, self.board.mic_device_name,
                self.board.mic_device_hostapi)

    @property
    def chosen_monitor_output(self):
        return (None, self.board.mic_output_name,
                self.board.mic_output_hostapi)


uimod.SettingsDialog = Scripted


def preferences(frame, script, output=None):
    Scripted.script = staticmethod(script)
    Scripted.output = output
    try:
        frame._on_settings()
    finally:
        Scripted.output = None


def listen(frame):
    heard = []
    for name in ("announce", "announce_help", "announce_answer"):
        real = getattr(frame, name)

        def hook(text, *args, _real=real, **kw):
            heard.append(text)
            return _real(text, *args, **kw)

        setattr(frame, name, hook)
    return heard


def post(frame, command):
    """A menu command through the binding, the way a key arrives."""
    event = wx.CommandEvent(wx.wxEVT_MENU, command)
    event.SetEventObject(frame)
    frame.GetEventHandler().ProcessEvent(event)


HOME = tempfile.mkdtemp(prefix="dropdeck-audio-boards-")


def make_board(name, **fields):
    board = Board()
    board.device_name, board.device_hostapi = "Desk", "Windows WASAPI"
    for key, value in fields.items():
        setattr(board, key, value)
    path = os.path.join(HOME, name + ".json")
    board.save(path)
    return path


START = make_board("Start")
boardmod.remember_board_path(START)
frame = uimod.DropDeckFrame(None)
heard = listen(frame)


def frame_3():
    frame.board.stop_fade = False
    primary = frame.mixer.primary
    primary.play_samples(0, sine(997.0, 2.0, 0.7), bus=C.BUS_SFX)
    for _ in range(7):
        primary.render(BLOCK)
    last = float(primary.render(331)[-1, 0])
    post(frame, uimod.ID_STOP_ALL)
    nxt = primary.render(BLOCK)[:, 0]
    worst = float(np.abs(np.diff(np.concatenate([[last], nxt]))).max())
    check("Stop everything, from its menu item, with the stop fade off, "
          "does not click", worst <= NATURAL_997 * 1.05,
          "%.3f against %.3f" % (worst, NATURAL_997))
    check("and it still stops everything", not frame.mixer.playing_slots())
    frame.board.stop_fade = True


section("item 3, through the window", frame_3)


def frame_5():
    frame.board.sources = []
    frame.apply_sources([{"name": "Line", "kind": "device",
                          "device_name": "Line in", "on_air": True}],
                        touch=False, quiet=True)
    path = make_board("Ninety six", device_name="Desk 96",
                      sources=[{"name": "Line", "kind": "device",
                                "device_name": "Line in", "on_air": True}])
    check("a board on a 96 kHz card opens", frame._open_board(path) is True)
    check("the main output is at 96 kHz", frame.mixer.samplerate == 96000,
          frame.mixer.samplerate)
    check("the microphone follows it", frame.mic.output_rate == 96000)
    chain = frame.mic.chain
    check("and so does the voice chain, from the board change",
          chain is not None and chain.samplerate == 96000,
          getattr(chain, "samplerate", None))
    back = make_board("Forty eight", device_name="Desk",
                      sources=[{"name": "Line", "kind": "device",
                                "device_name": "Line in", "on_air": True}])
    frame._open_board(back)
    check("back on 48 kHz the chain follows back",
          frame.mic.chain.samplerate == 48000)

    def ok(dialog):
        return wx.ID_OK

    preferences(frame, ok, output=(960, "Desk 96", "Windows WASAPI"))
    check("Preferences moving the output to 96 kHz moves the chain",
          frame.mixer.samplerate == 96000
          and frame.mic.chain.samplerate == 96000,
          (frame.mixer.samplerate, frame.mic.chain.samplerate))
    check("and every source, which only the microphone used to be told",
          all(s.input.output_rate == 96000 for s in frame.sources),
          [s.input.output_rate for s in frame.sources])
    preferences(frame, ok, output=(901, "Desk", "Windows WASAPI"))


section("item 5, through the window", frame_5)


def frame_6():
    frame._stop_send(quiet=True)
    frame.board.send_device_name = CABLE_IN
    frame.board.send_device_hostapi = "Windows WASAPI"
    frame.board.send_on = True
    frame.apply_sources([{"name": "Games call", "kind": "device",
                          "device_name": CABLE_OUT, "on_air": True}],
                        touch=False, quiet=True)
    heard.clear()
    started = frame._start_send()
    check("a send into a cable whose far end is a source is refused",
          started is False and not frame.sending())
    check("and the reason is said, naming the source and the cable",
          any("Games call" in line and "back into itself" in line
              for line in heard), heard)
    check("the reason is what the startup line and Ctrl+Shift+W will say",
          "back into itself" in (frame.send_failed or ""))
    check("and it is in the routing report",
          "back into itself" in frame.routing_report())
    frame.apply_sources([{"name": "Games call", "kind": "device",
                          "device_name": CABLE_OUT[:31], "on_air": True}],
                        touch=False, quiet=True)
    check("MME's cut name for the same far end is refused too",
          frame._start_send(quiet=True) is False)

    frame.apply_sources([{"name": "Hear the call", "kind": "device",
                          "device_name": CABLE_OUT, "on_air": False,
                          "monitor": True}], touch=False, quiet=True)
    check("a source you only listen to on the far end is allowed: it is "
          "never in the send, so it cannot loop",
          frame._start_send(quiet=True) is True)
    frame._stop_send(quiet=True)
    frame.apply_sources([], touch=False, quiet=True)
    DEFAULT_MIC[0] = CABLE_OUT
    frame.board.stream_mic = True
    check("a CLOSED microphone on the far end does not stop the send, "
          "which works today for somebody who never opens it",
          frame._start_send(quiet=True) is True)
    frame._stop_send(quiet=True)
    frame.mic.stream = object()                 # open, as far as the frame knows
    try:
        check("an open microphone that IS the far end refuses the send",
              frame._start_send(quiet=True) is False
              and "Your microphone" in frame.send_failed, frame.send_failed)
    finally:
        frame.mic.stream = None
    DEFAULT_MIC[0] = "Microphone (Yeti Stereo Microphone)"
    check("with nothing listening to the far end the send starts",
          frame._start_send(quiet=True) is True and frame.sending())

    heard.clear()
    mark = len(OPENED)
    frame.apply_sources([{"name": "Games call", "kind": "device",
                          "device_name": CABLE_OUT, "on_air": True}],
                        touch=False)
    check("while it runs, a source on its far end is not opened",
          len(OPENED) == mark and not frame.sources[0].is_open, OPENED)
    check("and that is said, out loud", any(
        "Games call" in line and "back into itself" in line
        for line in heard), heard)
    check("the send carries on", frame.sending())
    frame.apply_sources([], touch=False, quiet=True)

    heard.clear()
    mark = len(OPENED)
    DEFAULT_MIC[0] = CABLE_OUT
    post(frame, uimod.ID_MIC_TOGGLE)
    check("Ctrl+M onto the far end while sending opens nothing",
          len(OPENED) == mark and not frame._mic_open(), OPENED)
    check("and says why", any("Your microphone" in line
                              and "back into itself" in line
                              for line in heard), heard)
    DEFAULT_MIC[0] = "Microphone (Yeti Stereo Microphone)"
    frame._stop_send(quiet=True)
    frame.board.send_on = False


section("item 6, through the window", frame_6)


def frame_9():
    frame.mixer._notices = ["Windows would not open your default sound card "
                            "the quick way, so it is going the older, slower "
                            "way"]
    heard.clear()
    frame._startup_line()
    check("the startup line says the fall back", any(
        "slower way" in line for line in heard), heard)
    heard.clear()
    frame._startup_line()
    check("once", not any("slower way" in line for line in heard), heard)

    real = MicInput.start

    def slow(self, device=None, other_routes=True):
        self.default_by_mme = True
        return True

    MicInput.start = slow
    try:
        heard.clear()
        post(frame, uimod.ID_MIC_TOGGLE)
        first = [line for line in heard if "slower way" in line]
        frame.mic.stream = None
        heard.clear()
        post(frame, uimod.ID_MIC_TOGGLE)
        second = [line for line in heard if "slower way" in line]
    finally:
        MicInput.start = real
        frame.mic.stream = None
        frame.mic._publish(False)
    check("Ctrl+M on a default microphone that came in by MME says so",
          len(first) == 1, heard)
    check("once a session", second == [], second)


section("item 9, through the window", frame_9)


def frame_10():
    def turn_on(dialog):
        check("Preferences has Duck further while I am talking",
              "further while I am talking" in dialog.talk_duck.GetLabel()
              and not dialog.talk_duck.GetValue())
        check("and By how much, at 6 dB",
              dialog.talk_duck_db.GetValue() == 6)
        check("both are beside the duck depth, on the same page",
              dialog.talk_duck.GetParent() is dialog.duck_db.GetParent())
        dialog.talk_duck.SetValue(True)
        dialog.talk_duck_db.SetValue(9)
        return wx.ID_OK

    preferences(frame, turn_on)
    check("OK puts it on the board", frame.board.talk_duck is True
          and frame.board.talk_duck_db == 9.0)
    check("and on every output", frame.mixer.talk_duck is True
          and frame.mixer.talk_duck_db == 9.0)
    check("and the microphone listens for the voice",
          frame.mic.talk_detect is True)

    def look(dialog):
        dialog.duck_on.SetValue(False)
        event = wx.CommandEvent(wx.wxEVT_CHECKBOX, dialog.duck_on.GetId())
        event.SetEventObject(dialog.duck_on)
        dialog.duck_on.GetEventHandler().ProcessEvent(event)
        seen["enabled"] = (dialog.talk_duck.IsEnabled(),
                           dialog.talk_duck_db.IsEnabled())
        return wx.ID_CANCEL

    seen = {}
    preferences(frame, look)
    check("with ducking unticked both are greyed, as the depth is",
          seen.get("enabled") == (False, False), seen)

    off = make_board("Plain")
    frame._open_board(off)
    check("a board without it turns it off on the outputs and the mic",
          frame.mixer.talk_duck is False and frame.mic.talk_detect is False)
    on = make_board("Talker", talk_duck=True, talk_duck_db=4.0)
    frame._open_board(on)
    check("a board with it turns it on, at its own depth",
          frame.mixer.talk_duck is True and frame.mixer.talk_duck_db == 4.0
          and frame.mic.talk_detect is True)


section("item 10, through the window", frame_10)

# ===========================================================================
heading("S1. The loop guard, through the window, on a realistic machine")


def step3_loopguard():
    frame._stop_send(quiet=True)
    frame.board.send_device_name = YETI_OUT
    frame.board.send_device_hostapi = "Windows WASAPI"
    frame.board.send_on = True
    frame.apply_sources([{"name": "Guest", "kind": "device",
                          "device_name": YETI_MIC, "on_air": True}],
                        touch=False, quiet=True)
    check("a send into the Yeti's headphone jack with a guest on the Yeti's "
          "microphone starts (b157d05 refused it: the registry pairs the two "
          "by the card)", frame._start_send(quiet=True) is True,
          frame.send_failed)
    frame._stop_send(quiet=True)
    for out, mic in ((REALTEK_OUT, REALTEK_MIC), (DVR_OUT, DVR_MIC)):
        frame.board.send_device_name = out
        frame.apply_sources([{"name": "Guest", "kind": "device",
                              "device_name": mic, "on_air": True}],
                            touch=False, quiet=True)
        check("so does %s against its own microphone" % out,
              frame._start_send(quiet=True) is True, frame.send_failed)
        frame._stop_send(quiet=True)
    frame.board.send_device_name = REALTEK_OUT
    frame.apply_sources([{"name": "Room", "kind": "device",
                          "device_name": REALTEK_MIX, "on_air": True}],
                        touch=False, quiet=True)
    check("Stereo Mix on the card the show is sent into is still refused: it "
          "IS what that card plays", frame._start_send(quiet=True) is False
          and "back into itself" in (frame.send_failed or ""))
    frame.apply_sources([], touch=False, quiet=True)

    frame.board.send_device_name = YETI_OUT
    frame._start_send(quiet=True)
    tried = []
    real_start = MicInput.start

    def counting(self, device=None, other_routes=True):
        tried.append(device)
        self.last_error = "not opened in a test"
        return False

    MicInput.start = counting
    DEFAULT_MIC[0] = YETI_MIC
    frame.board.stream_mic = True
    heard.clear()
    try:
        post(frame, uimod.ID_MIC_TOGGLE)
    finally:
        MicInput.start = real_start
        DEFAULT_MIC[0] = "Microphone (Yeti Stereo Microphone)"
    check("Ctrl+M with the Yeti as the microphone, sending into the Yeti's "
          "jack, goes on to open it (a stand in that opens nothing)",
          len(tried) == 1 and not any("back into itself" in line
                                      for line in heard), (tried, heard))
    frame._stop_send(quiet=True)
    frame.board.send_on = False


section("S1, through the window", step3_loopguard)

# ===========================================================================
heading("S2. Two talkers on two inputs: the second is heard within 50 ms")


def step3_two_talkers():
    rnd = np.random.default_rng(1)

    def speech(n, level_db):
        t = np.arange(n) / RATE
        env = 0.55 + 0.45 * np.sin(2 * np.pi * 4 * t)
        return (rnd.standard_normal(n) * env * 10 ** (level_db / 20.0))

    mic = MicInput(device=None)
    mic.samplerate = RATE
    # "voice" since the final audit: "mix" is the plain average again.
    mic.channel = "voice"
    turns = []
    for who in (0, 1, 0, 1):
        n = 4 * RATE
        talker = speech(n, -20.0)
        pair = np.zeros((n, 2), dtype=np.float32)
        pair[:, who] = talker
        pair[:, 1 - who] = rnd.standard_normal(n) * 10 ** (-70 / 20.0)
        out = np.concatenate([mic._mix_down(pair[i:i + BLOCK])
                              for i in range(0, n, BLOCK)])

        def share(a, b):
            o, t = out[int(a * RATE):int(b * RATE)], talker[int(a * RATE):
                                                            int(b * RATE)]
            return db(abs(np.dot(o, t)) / max(np.dot(t, t), 1e-12))

        turns.append((share(0.05, 0.10), share(0.10, 0.50), share(3.0, 4.0)))
    print("     measured, the talker's level per turn (50 to 100 ms, 100 to "
          "500 ms, last second): %s" % "; ".join(
              "%+.1f %+.1f %+.1f dB" % t for t in turns))
    late = [t for t in turns[1:] if t[0] < -7.0 or t[1] < -7.0]
    check("every new turn is at least at the average (-6 dB) from 50 ms "
          "in; b157d05 had it at -98 to -101 dB for two seconds",
          not late, turns)
    check("and once one input has been talking alone for a second it has "
          "the whole level, as before: the split is still slow",
          all(abs(t[2]) < 0.5 for t in turns), turns)
    check("the split is not quick: the first 100 to 500 ms of the very "
          "first turn is still the average", abs(turns[0][1] + 6.0) < 0.5,
          turns[0])


section("S2", step3_two_talkers)

# ===========================================================================
heading("S3. One inf or NaN does not silence what comes after it")


def step3_not_a_number():
    for bad in (float("inf"), float("nan")):
        adapter = mixermod.RateAdapter(48000, 44100)
        tone = sine(440.0, 3.0, 0.3)
        tone[4800, 0] = bad
        at = [0]

        def fetch(count):
            piece = tone[at[0]:at[0] + count]
            at[0] += count
            if len(piece) < count:
                piece = np.concatenate(
                    [piece, np.zeros((count - len(piece), CHANNELS),
                                     np.float32)])
            return piece

        out = np.concatenate([adapter.read(fetch, 441) for _ in range(200)])
        tail = out[44100:]
        check("the monitor card's rate conversion after one %s: finite and "
              "still carrying the tone" % bad,
              bool(np.all(np.isfinite(tail))) and rms(tail) > 0.1,
              (bool(np.all(np.isfinite(tail))),
               rms(np.nan_to_num(tail))))
    mic = MicInput(device=None)
    mic.samplerate = RATE
    # "voice" since the final audit: "mix" is the plain average again.
    mic.channel = "voice"
    broken = np.zeros((BLOCK, 2), np.float32)
    broken[3, 1] = float("nan")
    mic._mix_down(broken)
    n = np.arange(2 * RATE)
    pair = np.stack([VOICE_AMP * np.sin(2 * np.pi * 220.0 * n / RATE),
                     np.random.default_rng(2).normal(0.0, HISS, len(n))],
                    axis=1).astype(np.float32)
    for i in range(0, len(pair), BLOCK):
        mic._mix_down(pair[i:i + BLOCK])
    check("and the two input judge still takes the talking side after a NaN",
          mic._side == 0, mic._side)


section("S3", step3_not_a_number)

# ===========================================================================
heading("S10. A read a few ms short is a repeat, not a 21 ms hole")


def step3_ring():
    ring = micinput._Ring(rate=RATE)
    w = 2 * np.pi * 440.0 / RATE
    phase = [0]

    def write():
        n = np.arange(phase[0], phase[0] + 512)
        ring.write(np.repeat((0.5 * np.sin(w * n)).astype(np.float32)[:, None],
                             2, axis=1))
        phase[0] += 512

    out = []
    for i in range(400):                         # about four seconds
        write()
        out.append(ring.read(480)[:, 0])
        if i % 15 == 14:
            out.append(ring.read(480)[:, 0])     # an extra read: less in hand
    extra = ring._extra
    # A late callback: a write that has not come yet when the read after it
    # does, at a moment when the read before leaves 2 to 8 ms in hand. So the
    # read is a few ms short, which is what one 4 ms late callback is.
    for _ in range(200):
        if 480 + 100 <= ring.available <= 480 + 400:
            break
        if ring.available > 480 + 400:
            out.append(ring.read(480)[:, 0])
        else:
            write()
    out.append(ring.read(480)[:, 0])
    in_hand = ring.available
    before = (ring.holes, ring._extra)
    out.append(ring.read(480)[:, 0])
    short = out[-1]
    after = (ring.holes, ring._extra)
    for _ in range(200):
        write()
        out.append(ring.read(480)[:, 0])
    x = np.concatenate(out)[RATE // 2:]
    zeros = 0
    longest = 0
    for value in x:
        zeros = zeros + 1 if value == 0.0 else 0
        longest = max(longest, zeros)
    residual = np.abs(x[2:] - 2 * np.cos(w) * x[1:-1] + x[:-2])
    print("     measured: a read %.1f ms short; holes %d to %d, margin learnt "
          "%d to %d frames, rescues %d, longest run of zeros %.1f ms, worst "
          "step against the tone %.3f"
          % ((480 - in_hand) / RATE * 1e3, before[0], after[0], before[1],
             after[1], getattr(ring, "rescues", 0), longest / RATE * 1e3,
             float(residual.max())))
    check("the case is real: the read had less than it asked for",
          32 <= in_hand < 480, in_hand)
    check("a read that comes up short is made whole: no hole, and no "
          "margin learnt from it (b157d05: a hole and 512 frames, 10.7 ms, "
          "more delay for the rest of the session)",
          after == before and extra == 0 and float(np.abs(short).max()) > 0.4,
          (before, after, extra))
    check("and what it plays is the tone, spliced in phase: no zeros, no step",
          longest == 0 and float(residual.max()) < 0.05,
          (longest, float(residual.max())))
    holes = ring.holes
    for _ in range(40):
        ring.read(480)
    check("a writer that has really stopped is still a hole",
          ring.holes > holes)


section("S10", step3_ring)

check("nothing in this file even tried to open a microphone or a source",
      OPENED == [], OPENED)
frame.board.dirty = False
frame._save_timer.Stop()
frame.stop_background_work()
frame.Destroy()
app.Yield()
for line in FAILED:
    print("  failed: " + line)
print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
