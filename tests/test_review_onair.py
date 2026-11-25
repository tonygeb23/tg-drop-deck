"""Review of 24 November 2026, Area 3, step 2: the on air sound.

    python tools/run_private.py tests/test_review_onair.py

Every item has checks that fail on e26e98d and pass on the fix; the others
are guards that what was already right stayed right.

  A. the startup line says a sound card that would not open;
  B. Preferences refuses "Put the microphone on air" onto the send's far end;
  1. dsp.ProgramChain: a slow leveller, then the ceiling;
  2. one each in the stream, both recorders and the send, after the cards are
     summed, the soft clip skipped while it runs, the presenter untouched;
  3. the On air sound page and Alt+Shift+P, proved through its binding;
  4. on for new boards, off for existing ones;
  5. loudness matching, measured on the background pass and never on a press,
     a trim the user set winning.

Step 3, Mark's findings on b157d05, each with checks that fail there:

  S3. one inf or NaN silenced the stream, the recordings and the send;
  S4. the leveller held whenever a microphone was open, ducking off or not;
  S5. loudness numbers outlived the file they were measured on, and a board
      file's numbers were believed;
  S6. closing during the first loudness pass waited for the whole file;
  S7. Alt+Shift+P took the key off a 3.10.1 board's bank 4 pad;
  S8. the compare jumped 10 dB, and the leveller froze while bypassed;
  S9. "never louder than" was a sample peak, not a true peak;
  S11. a trim of exactly 0 dB could not keep a pad as recorded.

Nothing here opens a sound card or a microphone and nothing makes a sound:
mixers run with no stream and are read off `render`, the send is a stand-in,
and every MicInput.start the frame could reach opens nothing.
"""

import json
import math
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-onair-")

import numpy as np                                     # noqa: E402
import soundfile as sf                                 # noqa: E402
import soxr                                            # noqa: E402

from dropdeck import audiofile                         # noqa: E402
from dropdeck import constants as C                    # noqa: E402
from dropdeck import dsp                               # noqa: E402
from dropdeck import micinput                          # noqa: E402
from dropdeck import send as sendmod                   # noqa: E402
from dropdeck import sources as sourcesmod             # noqa: E402
from dropdeck import streamout                         # noqa: E402
from dropdeck.audiofile import CHANNELS                # noqa: E402
from dropdeck.board import Board, demo_board_path      # noqa: E402
from dropdeck.micinput import MicInput                 # noqa: E402
from dropdeck.mixer import Mixer, MixerGroup           # noqa: E402

RATE = 48000
CHUNK = int(RATE * C.STREAM_CHUNK_SECONDS)
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
    """One item. A raise is a failed check, so e26e98d runs to the end."""
    try:
        body()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stdout)
        check("%s (raised %s: %s)" % (label, type(exc).__name__, exc), False)


def db(x):
    return 20.0 * math.log10(max(float(x), 1e-12))


def noise(seconds, level_db, seed=1):
    """Steady pink-ish noise, stereo, scaled by its RMS. Music-like enough
    for a leveller and not a sine, so the K weighting has a spectrum."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    white = rng.standard_normal((n, CHANNELS))
    pink = np.cumsum(white, axis=0)
    pink -= np.linspace(0, 1, n)[:, None] * pink[-1]
    pink = np.diff(np.concatenate([np.zeros((1, CHANNELS)), pink]), axis=0)
    pink = white * 0.5 + pink * 0.5
    pink /= np.sqrt(np.mean(pink ** 2))
    return (pink * 10 ** (level_db / 20.0)).astype(np.float32)


def sine(hz, seconds, amp=0.5, start=0):
    n = np.arange(start, start + int(seconds * RATE))
    wave = (amp * np.sin(2 * np.pi * hz * n / RATE)).astype(np.float32)
    return np.repeat(wave[:, None], CHANNELS, axis=1)


def run_chain(chain, signal):
    """Through the chain in the stream's own chunks: gains, and the output."""
    gains, out = [], []
    for s in range(0, len(signal) - CHUNK + 1, CHUNK):
        out.append(chain.process(signal[s:s + CHUNK]))
        gains.append(chain.gain_db)
    return np.array(gains), np.concatenate(out)


TMP = tempfile.mkdtemp(prefix="dropdeck-onair-files-")


def wav(name, data):
    path = os.path.join(TMP, name)
    sf.write(path, data, RATE)
    return path


# ===========================================================================
heading("1. The program chain: a slow leveller, then the ceiling")
CEILING = 10 ** (getattr(C, "DEFAULT_ONAIR_CEILING_DB", -2.0) / 20.0)


def item_1():
    from dropdeck import loudness
    tone = sine(997.0, 2.0, 0.1)
    level = loudness.integrated(
        [loudness.energy(tone[i:i + 4800], RATE)
         for i in range(0, len(tone), 4800)], [4800] * (len(tone) // 4800))
    check("the meter reads a stereo 997 Hz tone at -20 dBFS as -20.0 LUFS",
          level is not None and abs(level + 20.0) < 0.1, level)

    seconds = C.STREAM_CHUNK_SECONDS
    loud, out = run_chain(dsp.ProgramChain(RATE, even="gentle"),
                          noise(12, -8.0))
    steps = np.abs(np.diff(np.concatenate([[0.0], loud])))
    print("     measured, gentle on steady music at about -6 LUFS: the gain "
          "goes down at %.2f dB a second at most and settles at %+.1f dB"
          % (steps.max() / seconds, loud[-1]))
    check("gentle brings loud music down no faster than 3 dB a second",
          steps.max() <= 3.0 * seconds + 1e-6, steps.max() / seconds)
    check("and no further than its 10 dB cut", abs(loud[-1] + 10.0) < 1e-6,
          loud[-1])
    check("nothing out of it is louder than -2 dBFS",
          float(np.abs(out).max()) <= CEILING + 1e-6,
          db(np.abs(out).max()))
    quiet, _out = run_chain(dsp.ProgramChain(RATE, even="gentle"),
                            noise(10, -32.0))
    steps = np.abs(np.diff(np.concatenate([[0.0], quiet])))
    check("it brings quiet music up no faster than 1 dB a second",
          steps.max() <= 1.0 * seconds + 1e-6, steps.max() / seconds)
    check("and no further than its 6 dB boost", abs(quiet[-1] - 6.0) < 1e-6,
          quiet[-1])
    hush, _out = run_chain(dsp.ProgramChain(RATE, even="gentle"),
                           noise(6, -60.0))
    check("under -45 it holds: a pause is not wound up to full boost",
          float(np.abs(hush).max()) == 0.0, hush.max())
    held, _out = run_chain(dsp.ProgramChain(RATE, even="gentle",
                                            held=lambda: True),
                           noise(6, -8.0))
    check("while the duck is down it holds, so the music is never pumped "
          "back up under the voice", float(np.abs(held).max()) == 0.0,
          held.max())
    firm, _out = run_chain(dsp.ProgramChain(RATE, even="firm"),
                           noise(12, -8.0))
    steps = np.abs(np.diff(np.concatenate([[0.0], firm])))
    check("firm moves at 6 dB a second down and cuts up to 12",
          abs(steps.max() - 6.0 * seconds) < 1e-6
          and abs(firm[-1] + 12.0) < 1e-6, (steps.max(), firm[-1]))
    flat, out = run_chain(dsp.ProgramChain(RATE, even="off"), noise(4, -3.0))
    check("off is the ceiling alone: no levelling, every peak still under",
          float(np.abs(flat).max()) == 0.0
          and float(np.abs(out).max()) <= CEILING + 1e-6)
    block = noise(1, 0.0)[:CHUNK]
    off = dsp.ProgramChain(RATE, on=False)
    lag = getattr(getattr(off, "_dry", None), "frames", 0)
    passed = off.process(block)
    check("switched off it hands the audio back untouched, %d samples later "
          "(the ceiling's lookahead, so switching it on is a clean "
          "crossfade)" % lag,
          passed is block or np.array_equal(passed[lag:], block[:len(block)
                                                                - lag]))
    chain = dsp.ProgramChain(RATE)
    chain.configure(ceiling_db=-6.0)
    out = chain.process(noise(1, 0.0)[:CHUNK])
    check("a ceiling changed while it runs takes at the next block",
          float(np.abs(out).max()) <= 10 ** (-6 / 20.0) + 1e-6)


section("item 1", item_1)

# ===========================================================================
heading("2. After the cards are summed, never the presenter's output")


class Capture:
    def __init__(self):
        self.parts = []

    def write(self, key, block, rate=None):
        self.parts.append(np.array(block, copy=True))

    def peak(self):
        return max((float(np.abs(p).max()) for p in self.parts), default=0.0)


def item_2_mixer():
    def show(skip):
        m = Mixer(open_stream=False, samplerate=RATE)
        if skip:
            m.air_soft_clip = False
        air = Capture()
        m.air_tap = air
        # Two loud sounds at once, which sum past full scale.
        m.play_samples(0, sine(220.0, 1.0, 0.7), bus=C.BUS_SFX)
        m.play_samples(1, sine(220.0, 1.0, 0.7), bus=C.BUS_SFX)
        heard = np.concatenate([m.render(512).copy() for _ in range(40)])
        return heard, air.peak()

    plain, air_plain = show(False)
    skipped, air_skipped = show(True)
    check("with the on air sound running the presenter's output is bit for "
          "bit what it was", np.array_equal(plain, skipped))
    check("and it is still soft clipped, as it always was",
          float(np.abs(skipped).max()) < 1.0)
    check("the air sum is not soft clipped twice: the ceiling does it on the "
          "summed show", air_skipped > 1.3 and air_plain < 1.0,
          (air_plain, air_skipped))
    group = MixerGroup(bank_devices={}, open_stream=False)
    group.air_soft_clip = False
    group.set_bank_devices({3: 902})
    check("rebuilding the outputs keeps it, on every card",
          all(not m.air_soft_clip for m in group.mixers))
    group.close()


def item_2_consumers():
    hot = (noise(2, 0.0) * 2.0).astype(np.float32)        # well past 0 dBFS

    class Dest:
        def __init__(self):
            self.got = []

        def feed(self, block):
            self.got.append(np.array(block, copy=True))

    bus = streamout.AirBus(RATE)
    bus.write("card", hot, RATE)
    streamer = streamout.Streamer(bus, {})
    streamer._destination = Dest()
    streamer._resampler = streamout._Resampler(RATE, RATE)
    streamer.processor = dsp.ProgramChain(RATE)
    streamer._drain()
    peak = max(float(np.abs(b).max()) for b in streamer._destination.got)
    check("the stream sends what the chain made: nothing over -2 dBFS",
          peak <= CEILING + 1e-6, db(peak))

    from dropdeck import recorder as recordmod

    class File:
        def __init__(self):
            self.got = []

        def write(self, block):
            self.got.append(np.array(block, copy=True))

    rec = recordmod.Recorder(streamout.AirBus(RATE))
    rec._file = File()
    rec.processor = dsp.ProgramChain(RATE)
    rec._feed(hot[:CHUNK])
    check("the recording is written through it",
          float(np.abs(rec._file.got[0]).max()) <= CEILING + 1e-6)

    from dropdeck import videorecord

    class Audio:
        rate = RATE

        def __init__(self):
            self.got = []

        def encode(self, frame):
            self.got.append(frame.to_ndarray())
            return []

    vid = videorecord.VideoRecorder(streamout.AirBus(RATE),
                                    videorecord.FrameTap(), width=640,
                                    height=360, fps=30, bitrate=128)
    if videorecord.av is None:
        videorecord.av = audiofile.av_module()     # loaded at start() normally
    vid._audio = Audio()
    vid._resampler = streamout._Resampler(RATE, RATE)
    vid._headroom = 1.0
    vid._apts = 0
    vid.processor = dsp.ProgramChain(RATE)
    vid._feed_audio(hot[:CHUNK])
    check("and so is the MP4's sound",
          float(np.abs(vid._audio.got[0]).max()) <= CEILING + 1e-6)

    send = sendmod.Send(device=None, samplerate=RATE, open_stream=False)
    send.processor = dsp.ProgramChain(RATE)
    send.bus.write("card", hot, RATE)
    out = np.zeros((2048, CHANNELS), dtype=np.float32)
    loudest = 0.0
    for _ in range(12):
        send._callback(out, 2048, None, None)
        loudest = max(loudest, float(np.abs(out).max()))
    check("the send puts out what its own chain made", 0.0 < loudest
          <= CEILING + 1e-6, db(loudest))


section("item 2, the mixer", item_2_mixer)
section("item 2, the four consumers", item_2_consumers)

# ===========================================================================
heading("4. On for a new board, off for one saved before it existed")


def item_4():
    board = Board()
    check("a new board has the on air sound on", board.onair_on is True)
    check("and loudness matching on", board.match_loudness is True)
    check("gentle, never louder than -2", board.onair_even == "gentle"
          and board.onair_ceiling_db == -2.0)
    path = os.path.join(TMP, "old.json")
    board.save(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for field in ("onair_on", "match_loudness", "onair_even",
                  "onair_ceiling_db"):
        data.pop(field, None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    old = Board.load(path)
    check("an existing board.json without the fields loads with both off",
          old.onair_on is False and old.match_loudness is False)
    old.onair_on, old.onair_even, old.onair_ceiling_db = True, "firm", -4.0
    old.save(path)
    again = Board.load(path)
    check("and what is set is saved and loaded",
          again.onair_on is True and again.onair_even == "firm"
          and again.onair_ceiling_db == -4.0)
    data["onair_even"], data["onair_ceiling_db"] = "loud", 99
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    odd = Board.load(path)
    check("a hand edited board falls back and clamps",
          odd.onair_even == "gentle" and odd.onair_ceiling_db == 0.0)
    demo = Board.load(demo_board_path())
    check("the demo pack is a new board to whoever opens it: both on",
          demo.onair_on is True and demo.match_loudness is True)


section("item 4", item_4)

# ===========================================================================
heading("5. Loudness matching: a default trim, the user's own winning")


def item_5_rules():
    from dropdeck import loudness
    check("a loud master is brought down to -18",
          abs(loudness.matched_trim(-6.3, 0.0) + 11.7) < 1e-6)
    check("but no further than 15 dB",
          abs(loudness.matched_trim(-1.0, 0.0) + 15.0) < 1e-6)
    check("a quiet one is brought up only as far as its own peaks allow",
          abs(loudness.matched_trim(-30.0, -3.0) - 1.5) < 1e-6)
    check("one that already peaks at full scale is not brought up at all",
          loudness.matched_trim(-18.3, -0.5) == 0.0)
    check("and never more than 6 dB up",
          loudness.matched_trim(-40.0, -30.0) == 6.0)
    check("a file that was not measured is played as it is",
          loudness.matched_trim(None, None) == 0.0)

    from dropdeck.slot import Slot
    slot = Slot(index=0, filepath="loud.wav")
    slot.loudness, slot.peak_db, slot.loudness_for = -6.3, -0.1, "loud.wav"
    check("matching on, the pad gets the matched trim",
          abs(loudness.trim_for(slot, True) + 11.7) < 1e-6)
    check("matching off, it gets none", loudness.trim_for(slot, False) == 0.0)
    slot.trim_db = -3.0
    check("a trim the user set wins", loudness.trim_for(slot, True) == -3.0)
    slot.trim_db = 0.0
    slot.filepath = "another.wav"
    check("a number measured for a different file is never used",
          loudness.trim_for(slot, True) == 0.0)
    saved = Slot.from_dict(0, {"filepath": "x.wav", "loudness": -9.0,
                               "peak_db": -1.0, "loudness_checked": True,
                               "loudness_stamp": [1000, 2000]})
    check("saved with the board and back", saved.loudness == -9.0
          and saved.loudness_for == "x.wav")
    check("and a board file carries the numbers but no path",
          "loudness_for" not in saved.to_dict())


section("item 5, the rules", item_5_rules)

# ===========================================================================
# The frame: the user's paths, through bindings, with nothing opened.
import wx                                               # noqa: E402

from dropdeck import board as boardmod                  # noqa: E402
from dropdeck import cabletest                          # noqa: E402
from dropdeck import dialogs                            # noqa: E402
from dropdeck import globalhotkeys                      # noqa: E402
from dropdeck import secrets                            # noqa: E402
from dropdeck import ui as uimod                        # noqa: E402

app = wx.App(False)
wx.MessageBox = lambda *a, **kw: wx.OK
secrets.fetch = lambda name, prefix=None: None
secrets.store = lambda *a, **kw: True
secrets.forget = lambda *a, **kw: None

CABLE_IN = "CABLE Input (VB-Audio Virtual Cable)"
CABLE_OUT = "CABLE Output (VB-Audio Virtual Cable)"
CARDS = {"Desk": 901, "Phones": 903, CABLE_IN: 911}
uimod.resolve_device = lambda spec: CARDS.get((spec or {}).get("name"))
uimod.resolve_input = lambda spec: None
sourcesmod.resolve_input = lambda spec: None
uimod.DropDeckFrame._start_update_check = lambda self: None
Mixer._device_rate = staticmethod(lambda device: RATE)
cabletest.capture_for = (lambda name, found=None:
                         CABLE_OUT if name == CABLE_IN else "")
DEFAULT_MIC = ["Microphone (Yeti Stereo Microphone)"]
micinput.default_input_name = lambda: DEFAULT_MIC[0]
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

    def ShowModal(self):
        return Scripted.script(self)

    @property
    def chosen_device(self):
        return (901, "Desk", "Windows WASAPI")

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


def preferences(frame, script):
    Scripted.script = staticmethod(script)
    frame._on_settings()


def listen(frame):
    heard = []
    for name in ("announce", "announce_help", "announce_answer"):
        real = getattr(frame, name)

        def hook(text, *args, _real=real, _name=name, **kw):
            heard.append((_name, text))
            return _real(text, *args, **kw)

        setattr(frame, name, hook)
    return heard


def said(heard, words, channel=None):
    return any(words in text and (channel is None or name == channel)
               for name, text in heard)


def post(frame, command):
    event = wx.CommandEvent(wx.wxEVT_MENU, command)
    event.SetEventObject(frame)
    frame.GetEventHandler().ProcessEvent(event)


def pump_until(done, seconds=10.0):
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.ProcessPendingEvents()
        app.Yield()
        if done():
            return True
        time.sleep(0.02)
    return done()


HOME = tempfile.mkdtemp(prefix="dropdeck-onair-boards-")


def make_board(name, legacy=False, **fields):
    board = Board()
    board.device_name, board.device_hostapi = "Desk", "Windows WASAPI"
    for key, value in fields.items():
        setattr(board, key, value)
    path = os.path.join(HOME, name + ".json")
    board.save(path)
    if legacy:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for key in ("onair_on", "match_loudness", "onair_even",
                    "onair_ceiling_db"):
            data.pop(key, None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    return path


START = make_board("Start")
boardmod.remember_board_path(START)
frame = uimod.DropDeckFrame(None)
heard = listen(frame)


def frame_a():
    frame.mixer.problems = ["Desk could not be opened, so those sounds are "
                            "going to the default output instead"]
    heard.clear()
    frame._startup_line()
    check("the startup line says a sound card that would not open",
          said(heard, "Desk could not be opened"), heard)
    check("on the announce channel, which no speech level below none hides",
          said(heard, "Desk could not be opened", "announce"), heard)
    check("once", sum("Desk could not be opened" in text
                      for _n, text in heard) == 1)
    frame.mixer.problems = []


section("A, through the window", frame_a)


def frame_b():
    frame.board.send_device_name = CABLE_IN
    frame.board.send_device_hostapi = "Windows WASAPI"
    frame.board.send_on = True
    frame.board.stream_mic = False
    check("a send runs", frame._start_send(quiet=True) and frame.sending())
    DEFAULT_MIC[0] = CABLE_OUT
    frame.mic.stream = object()               # open, as far as the frame knows
    try:
        def tick_it(dialog):
            dialog.stream_mic.SetValue(True)
            return wx.ID_OK

        heard.clear()
        preferences(frame, tick_it)
        check("Put the microphone on air onto the send's far end is refused",
              frame.board.stream_mic is False)
        check("and it says why, the way Ctrl+M does",
              said(heard, "back into itself"), heard)
        check("and the microphone is not on the air",
              not frame.mic.on_air)
    finally:
        frame.mic.stream = None
        DEFAULT_MIC[0] = "Microphone (Yeti Stereo Microphone)"
    frame._stop_send(quiet=True)
    frame.board.send_on = False


section("B, through the window", frame_b)


class StandIn:
    """A stream or a recorder as the frame sees one, opening nothing."""

    state = streamout.OFF
    detail = ""
    running = False
    paused = False
    bytes_sent = 0

    def __init__(self):
        self.bus = streamout.AirBus(RATE)
        self.processor = None

    def stop(self, *a, **kw):
        pass


def frame_2():
    frame.board.onair_on = True
    frame.board.send_device_name = CABLE_IN
    frame.board.send_on = True
    frame._start_send(quiet=True)
    frame.streamer = StandIn()
    frame.recorder = StandIn()
    frame.video_recorder = StandIn()
    frame._apply_onair()
    chains = [getattr(c, "processor", None) for c in
              (frame.streamer, frame.recorder, frame.video_recorder,
               frame.send)]
    check("the stream, both recorders and the send each have the on air "
          "sound", all(isinstance(c, dsp.ProgramChain) for c in chains),
          chains)
    check("each its own: no gain or window is shared, so the send's mix "
          "minus is processed apart", len({id(c) for c in chains}) == 4)
    check("the mixers stop soft clipping the air and send sums while it runs",
          frame.mixer.air_soft_clip is False)
    loud = noise(2, -6.0)
    for s in range(0, len(loud) - CHUNK, CHUNK):
        frame.send.processor.process(loud[s:s + CHUNK])
    check("and one moving leaves the others where they were",
          frame.send.processor.gain_db < 0.0
          and frame.streamer.processor.gain_db == 0.0)
    duck = frame.mixer.duck_bus
    duck.publish_down("test", True)
    check("each reads the duck from the live bus", all(
        c._held() for c in chains))
    duck.forget("test")


section("2, through the window", frame_2)


def frame_3():
    heard.clear()
    tabs = []

    def look(dialog):
        tabs.extend(dialog.tabs.GetPageText(i)
                    for i in range(dialog.tabs.GetPageCount()))
        seen["page"] = dialog.PAGE_ONAIR
        seen["ceiling"] = type(dialog.onair_ceiling).__name__
        seen["even"] = [dialog.onair_even.GetString(i)
                        for i in range(dialog.onair_even.GetCount())]
        dialog.onair_even.SetSelection(2)
        dialog.onair_ceiling.SetValue(-4.0)
        return wx.ID_OK

    seen = {}
    preferences(frame, look)
    check("Preferences has an On air sound page, next to Voice",
          "On air sound" in tabs
          and tabs.index("On air sound") == tabs.index("Voice") + 1, tabs)
    check("Even out the music: off, gentle or firm",
          len(seen.get("even", [])) == 3, seen.get("even"))
    check("Never louder than is a spin box in dBFS, never a slider",
          seen.get("ceiling") == "SpinCtrlDouble", seen.get("ceiling"))
    check("OK puts it on the board", frame.board.onair_even == "firm"
          and frame.board.onair_ceiling_db == -4.0)
    check("and on what is already running, at once",
          frame.send.processor.even == "firm"
          and frame.send.processor.ceiling_db == -4.0)

    keys = [(e.GetFlags(), e.GetKeyCode(), e.GetCommand())
            for e in frame._accelerators]
    check("Alt+Shift+P is in the key table, bound to the compare",
          (wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("P"),
           uimod.ID_ONAIR_COMPARE) in keys)
    label = frame.onair_item.GetItemLabel()
    check("the On air menu has it, with the key in the label",
          "Alt+Shift+P" in label, label)
    dirty_before = frame.board.dirty
    frame.board.dirty = False
    heard.clear()
    post(frame, uimod.ID_ONAIR_COMPARE)
    check("pressed, it says On air sound off",
          said(heard, "On air sound off"), heard)
    check("and the stream, the recorders and the send hear the show without "
          "it", not frame.send.processor.on and not frame.streamer.processor.on)
    check("and the soft clip comes back, so nothing goes out unbounded",
          frame.mixer.air_soft_clip is True)
    check("the menu says it is off for now",
          "off for now" in frame.onair_item.GetItemLabel())
    heard.clear()
    post(frame, uimod.ID_ONAIR_COMPARE)
    check("pressed again, On air sound on", said(heard, "On air sound on"),
          heard)
    check("and it is back", frame.send.processor.on
          and frame.mixer.air_soft_clip is False)
    check("a compare, not a setting: the board is not changed by it",
          frame.board.dirty is False and frame.board.onair_on is True
          and "onair_bypass" not in frame.board.to_dict())
    frame.board.dirty = dirty_before


section("3, through the window", frame_3)


def frame_4():
    old = make_board("Old", legacy=True)
    frame._open_board(old)
    check("an existing board opens with the on air sound off",
          frame.board.onair_on is False and frame.board.match_loudness is False)
    check("so its show goes out as it did, soft clipped",
          frame.mixer.air_soft_clip is True
          and not frame.send.processor.on)
    fresh = make_board("Fresh")
    frame._open_board(fresh)
    check("a board made since opens with it on",
          frame.board.onair_on is True and frame.mixer.air_soft_clip is False)


section("4, through the window", frame_4)

LOUD_FILE = wav("loud.wav", noise(3, -4.0, seed=3))


def frame_5():
    measured = []
    real_measure = audiofile.measure_loudness

    def counting(path, **kw):
        measured.append((path, threading.current_thread().name))
        return real_measure(path, **kw)

    audiofile.measure_loudness = counting
    played = []
    real_play = frame.mixer.play

    def recording_play(slot_index, path, **kw):
        played.append(kw.get("trim_db"))
        return real_play(slot_index, path, **kw)

    frame.mixer.play = recording_play
    try:
        frame.board.match_loudness = True
        slot = frame.board.slots[3]
        frame._apply_file(slot, LOUD_FILE)
        check("assigning a sound measures it, on the background pass",
              pump_until(lambda: slot.loudness_for == LOUD_FILE))
        check("never on the window's thread",
              measured and all(name != threading.main_thread().name
                               for _p, name in measured), measured)
        from dropdeck import loudness
        expect = loudness.matched_trim(slot.loudness, slot.peak_db)
        print("     measured: a loud file at %.1f LUFS, peaking %+.1f dBFS, "
              "plays at %+.1f dB" % (slot.loudness, slot.peak_db, expect))
        before = len(measured)
        post(frame, uimod.ID_SLOT_BASE + slot.index)
        check("a press does no measuring at all", len(measured) == before,
              measured[before:])
        check("and plays at the stored, matched trim",
              played and abs(played[-1] - expect) < 1e-9 and expect < -5.0,
              played)
        slot.trim_db = -2.0
        post(frame, uimod.ID_SLOT_BASE + slot.index)
        check("a trim the user set wins", played[-1] == -2.0, played)
        slot.trim_db = 0.0
        frame.board.match_loudness = False
        frame._apply_onair()
        post(frame, uimod.ID_SLOT_BASE + slot.index)
        check("with matching off the pad plays as it is", played[-1] == 0.0,
              played)
        from dropdeck.playlist import Track
        track = Track(filepath=LOUD_FILE)
        track.loudness, track.peak_db = slot.loudness, slot.peak_db
        track.loudness_for = LOUD_FILE
        frame.board.match_loudness = True
        frame._apply_onair()
        frame.player.playlist.tracks.append(track)
        frame.player._start(len(frame.player.playlist.tracks) - 1)
        check("a song in the running order is matched the same way",
              abs(played[-1] - expect) < 1e-9, played)
        frame.player.stop(fade_out=0.0, quiet=True)
        frame.player.playlist.tracks.remove(track)
        frame.mixer.stop_all(at_once=True)
    finally:
        audiofile.measure_loudness = real_measure
        frame.mixer.play = real_play


section("5, through the window", frame_5)


def true_peak(x):
    """BS.1770's 4x, by soxr. Its first and last 50 ms are left out: soxr
    takes the signal beyond the ends as silence, so audio cut off mid wave
    rings there, a peak in the measurement and not in the audio."""
    up = np.abs(soxr.resample(np.asarray(x, np.float64), RATE, RATE * 4))
    return db(up[4 * 2400:-4 * 2400].max())


def master(seconds, seed=11):
    """Mark's loudness war master: pink noise and a kick, clipped hard at
    full scale, so its true peak is well over its sample peak."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    w = rng.standard_normal((n, 2))
    pink = np.cumsum(w, axis=0)
    pink -= np.convolve(pink[:, 0], np.ones(64) / 64, "same")[:, None]
    pink = pink / np.abs(pink).max()
    kick = np.zeros(n)
    kick[::RATE // 2] = 1.0
    kick = np.convolve(kick, np.exp(-np.arange(2000) / 300.0)
                       * np.sin(np.arange(2000) * 2 * np.pi * 60 / RATE),
                       "same")
    x = pink * 0.6 + kick[:, None] * 0.8 + w * 0.05
    return np.clip(x * 2.5, -1.0, 1.0).astype(np.float32)


def pink_music(seconds, seed=11):
    """Pink noise peaking at full scale and never clipped: music, mastered
    but not brickwalled."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    w = rng.standard_normal((n, 2))
    pink = np.cumsum(w, axis=0)
    pink -= np.convolve(pink[:, 0], np.ones(64) / 64, "same")[:, None]
    pink = pink / np.abs(pink).max()
    return (pink * 0.9 + w * 0.02).astype(np.float32)


# ===========================================================================
heading("S3. One inf or NaN does not silence the show for good")


def step3_nan():
    bad_runs = []
    for even in ("gentle", "firm", "off"):
        for bad in (float("inf"), float("nan")):
            signal = noise(8, -14.0, seed=5)
            signal[RATE, 0] = bad
            _g, out = run_chain(dsp.ProgramChain(RATE, even=even,
                                                 ceiling_db=-2.0), signal)
            tail = out[2 * RATE:]
            fine = bool(np.all(np.isfinite(tail)))
            loud = float(np.abs(np.nan_to_num(tail)).max())
            if not (fine and loud > 0.05):
                bad_runs.append((even, bad, fine, round(loud, 3)))
    check("after one inf or NaN sample the stream, the recordings and the "
          "send carry the music again within a block, finite, on Gentle, "
          "Firm and Off", not bad_runs, bad_runs)
    off = dsp.ProgramChain(RATE, on=False)
    block = noise(1, -6.0)[:CHUNK]
    block[10, 1] = float("nan")
    block[20, 0] = float("inf")
    out = off.process(block)
    check("switched off in Preferences it is made finite and bounded too",
          bool(np.all(np.isfinite(out)))
          and float(np.abs(out).max()) <= C.ONAIR_SANE_LEVEL,
          float(np.nanmax(np.abs(out))))


section("S3", step3_nan)

# ===========================================================================
heading("S4. The leveller holds only while the music really is ducked")


def step3_hold():
    frame.board.onair_on = True
    frame.board.send_device_name = CABLE_IN
    frame.board.send_on = True
    frame._start_send(quiet=True)
    frame._apply_onair()
    chain = frame.send.processor
    mixers = frame.mixer
    was = mixers.ducking
    try:
        mixers.ducking = False
        frame.mic._publish(True)
        for _ in range(20):
            mixers.primary.render(C.BLOCKSIZE)
        off = chain._held()
        level = dsp.ProgramChain(RATE, even="gentle", held=chain.held)
        gains, _out = run_chain(level, noise(20, -8.0))
        closed = dsp.ProgramChain(RATE, even="gentle")
        shut, _out = run_chain(closed, noise(20, -8.0))
        print("     measured, hot music for 20 s with the microphone open and "
              "ducking off: %+.1f dB, against %+.1f dB with it closed"
              % (gains[-1], shut[-1]))
        check("with ducking off, an open microphone does not hold it: it "
              "levels exactly as with the microphone closed (b157d05: +0.0 "
              "dB, frozen)", off is False and abs(gains[-1] - shut[-1]) < 1e-6,
              (off, gains[-1], shut[-1]))
        mixers.ducking = True
        frame.mixer.primary.play_samples(0, noise(2, -12.0), bus=C.BUS_SFX)
        for _ in range(40):
            mixers.primary.render(C.BLOCKSIZE)
        check("with ducking on and the music down under the voice, it holds",
              chain._held() is True)
    finally:
        frame.mic._publish(False)
        frame.mixer.stop_all(at_once=True)
        for _ in range(40):
            mixers.primary.render(C.BLOCKSIZE)
        mixers.ducking = was
    check("and once the voice is gone and the music is back up, it moves "
          "again", chain._held() is False)
    frame._stop_send(quiet=True)
    frame.board.send_on = False


section("S4", step3_hold)

# ===========================================================================
heading("S5. Loudness belongs to one version of one file")


def step3_stale():
    from dropdeck import loudness
    from dropdeck.slot import Slot
    path = wav("jingle.wav", noise(3, -34.0, seed=7))
    slot = Slot(index=0, filepath=path)
    slot.measure_loudness()
    first = loudness.trim_for(slot, True)
    sf.write(path, np.clip(noise(3, -3.0, seed=8), -0.99, 0.99), RATE)
    due = slot.needs_loudness()
    after = loudness.trim_for(slot, True)
    print("     measured: the quiet jingle played at %+.1f dB; re-rendered "
          "loud under the same name, %+.1f dB until it is measured again"
          % (first, after))
    check("a file re-rendered under the same name is measured again, and "
          "until it is its old trim is dropped (b157d05 kept +6 dB, peaks at "
          "+5.9 dBFS)", first > 5.0 and due is True and after == 0.0,
          (first, due, after))
    slot.measure_loudness()
    check("and measured again it is cut, not boosted",
          loudness.trim_for(slot, True) < -10.0, loudness.trim_for(slot, True))
    kept = Slot.from_dict(0, slot.to_dict())
    check("a board saves the file's size and time with the numbers",
          "loudness_stamp" in slot.to_dict() and kept.loudness_for == path)
    check("loaded, they are not checked yet, so they may only cut",
          kept.loudness_verified is False
          and loudness.trim_for(kept, True) == loudness.trim_for(slot, True))
    quiet = Slot.from_dict(0, slot.to_dict())
    quiet.loudness, quiet.peak_db = -34.0, -20.0
    check("unchecked numbers that would boost are not used to boost",
          loudness.trim_for(quiet, True) == 0.0, loudness.trim_for(quiet, True))
    check("checked against the file on the background pass, they are used",
          kept.needs_loudness() is False and kept.loudness_verified is True)
    lies = dict(slot.to_dict(), loudness=-80.0, peak_db=-120.0)
    told = Slot.from_dict(0, lies)
    check("a board file claiming -80 LUFS and a -120 dBFS peak is not a "
          "measurement: nothing is taken, the file plays as it is",
          told.loudness_for is None and loudness.trim_for(told, True) == 0.0,
          (told.loudness, told.peak_db, loudness.trim_for(told, True)))
    wrong = []
    for level, peak in ((-75.0, -20.0), (-20.0, None), (-5.0, -20.0),
                        (5.0, 20.0), ("loud", -1.0)):
        if Slot.from_dict(0, dict(slot.to_dict(), loudness=level,
                                  peak_db=peak)).loudness_for is not None:
            wrong.append((level, peak))
    check("nor is any other pair no file could give", not wrong, wrong)

    frame.board.match_loudness = True
    pad = frame.board.slots[5]
    loud = wav("relink.wav", noise(3, -6.0, seed=9))
    frame._apply_file(pad, loud)
    check("assigned, it is measured", pump_until(
        lambda: pad.loudness_for == loud and pad.loudness is not None))
    sf.write(loud, noise(3, -36.0, seed=10), RATE)
    # The window coming back, through its handler. What it schedules is run
    # here at once: wx timers do not fire under this harness's Yield.
    later = []
    real_later = wx.CallLater
    wx.CallLater = lambda ms, func, *a, **kw: later.append((ms, func))
    try:
        frame._on_frame_activate(wx.ActivateEvent(wx.wxEVT_ACTIVATE, True))
    finally:
        wx.CallLater = real_later
    for _ms, func in later:
        if getattr(func, "__name__", "") == "scan_playlist_metadata":
            func()
    from dropdeck.slot import file_stamp
    check("coming back to the window measures it again, on the background "
          "pass", pump_until(lambda: pad.loudness is not None
                             and pad.loudness < -25.0, seconds=15.0),
          (pad.loudness, pad.loudness_stamp, file_stamp(loud),
           frame._metadata_thread, frame.board.slots[5] is pad))
    frame.board.match_loudness = False


section("S5", step3_stale)

# ===========================================================================
heading("S6. Closing during a measurement does not wait for the file")

LONG_FILE = os.path.join(TMP, "an hour.wav")
with sf.SoundFile(LONG_FILE, "w", RATE, 2, subtype="PCM_16") as handle:
    for _ in range(30):
        handle.write(noise(2, -20.0, seed=4))


class _Slow:
    """A reader 20 ms a piece: a one minute file takes twelve seconds, as an
    hour long one does on a slow disk."""

    def __init__(self, handle):
        self.handle = handle
        self.samplerate = handle.samplerate

    def read(self, frames):
        import time
        time.sleep(0.02)
        return self.handle.read(frames)

    def close(self):
        self.handle.close()


def step3_stop():
    import time
    real_reader = audiofile.reader
    audiofile.reader = lambda path: _Slow(real_reader(path))
    try:
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        start = time.perf_counter()
        try:
            got = audiofile.measure_loudness(LONG_FILE, stop=stop)
        except TypeError:
            got = audiofile.measure_loudness(LONG_FILE)
        took = time.perf_counter() - start
        print("     measured: stopped 0.30 s into a file that takes 12 s, "
              "back after %.2f s" % took)
        check("a measurement told to stop is back within a fraction of a "
              "second, without an answer", took < 0.6 and got == (None, None),
              (round(took, 2), got))
    finally:
        audiofile.reader = real_reader


section("S6", step3_stop)

# ===========================================================================
heading("S7. Alt+Shift+P on a board whose bank 4 pad already has it")


def step3_compare_key():
    from dropdeck.board import Board as _Board
    board = _Board()
    board.device_name, board.device_hostapi = "Desk", "Windows WASAPI"
    pad = board.bank_slots(C.BANK_MISC)[0]
    pad.filepath = wav("applause.wav", noise(1, -20.0))
    pad.name = "Applause"
    pad.custom_hotkey = "Alt+Shift+P"
    pad.key_code = ord("P")
    pad.modifiers = wx.ACCEL_ALT | wx.ACCEL_SHIFT
    path = os.path.join(HOME, "Applause.json")
    board.save(path)
    frame._open_board(path)
    want = (wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("P"))
    owners = [e.GetCommand() for e in frame._accelerators
              if (e.GetFlags(), e.GetKeyCode()) == want]
    mine = uimod.ID_SLOT_BASE + frame.board.bank_slots(C.BANK_MISC)[0].index
    check("the pad keeps the key: it is the only Alt+Shift+P in the table "
          "(b157d05 had the compare first, so the sound never played)",
          owners == [mine], owners)
    label = frame.onair_item.GetItemLabel()
    check("the menu item says it has no key, and whose the key is",
          "\t" not in label and "Applause" in label and "No key" in label,
          label)
    uses = frame._app_key_uses()
    check("and the key map the hotkey box checks against does not claim it "
          "for the compare",
          "compare" not in str(uses.get(want[::-1], "")).lower(),
          uses.get(want[::-1]))
    heard.clear()
    frame._startup_line()
    lines = [t for _n, t in heard if "Alt+Shift+P" in t]
    check("the startup line says it, once",
          len(lines) == 1 and lines[0].count("Alt+Shift+P") == 1
          and "Applause" in lines[0], lines)
    heard.clear()
    was = frame._onair_bypassed
    post(frame, uimod.ID_ONAIR_COMPARE)
    check("the menu item still compares", frame._onair_bypassed != was
          and said(heard, "On air sound"), heard)
    post(frame, uimod.ID_ONAIR_COMPARE)
    frame._open_board(START)
    keys = [(e.GetFlags(), e.GetKeyCode(), e.GetCommand())
            for e in frame._accelerators]
    check("a board where no pad has it gets the key back, label and all",
          want + (uimod.ID_ONAIR_COMPARE,) in keys
          and "Alt+Shift+P" in frame.onair_item.GetItemLabel())
    frame.board.slots[0].global_hotkey = "Alt+Shift+P"
    frame.hotkeys.enabled = True
    try:
        clashes = frame._own_key_clashes()
    finally:
        frame.hotkeys.enabled = False
        frame.board.slots[0].global_hotkey = None
    check("a pad's GLOBAL hotkey on Alt+Shift+P is said, the way any of "
          "this window's keys is", any("Alt+Shift+P" in line
                                       for line in clashes), clashes)


section("S7", step3_compare_key)

# ===========================================================================
heading("S8. The compare crossfades, and the leveller keeps up meanwhile")


def step3_compare_fade():
    chain = dsp.ProgramChain(RATE, even="gentle", ceiling_db=-2.0)
    run_chain(chain, noise(15, -8.0))
    block = 960                                 # 20 ms, the send's size
    # A steady tone for the two blocks either side, so 2 ms of it measures
    # the gain and not the noise.
    hot = sine(997.0, 0.1, 0.5)
    before = chain.process(hot[:block])
    chain.configure(on=False)
    after = chain.process(hot[block:2 * block])
    edge = db(np.sqrt(np.mean(after[:96] ** 2))) - db(
        np.sqrt(np.mean(before[-96:] ** 2)))
    print("     measured: switched off with the leveller at -10 dB, the "
          "level 2 ms either side of the switch moves %+.1f dB" % edge)
    check("off is a crossfade, not a 10 dB step in one sample (b157d05: "
          "+10 dB at once)", abs(edge) < 2.0, edge)
    rest = run_chain(chain, noise(15, -30.0))[0]
    tracked = chain.gain_db
    chain.configure(on=True)
    back = chain.process(noise(1, -30.0)[:block])
    print("     measured: 15 s of quiet music while compared, the gain went "
          "from -10.0 to %+.1f dB" % tracked)
    check("while it is off the leveller keeps up with the music, so on "
          "again is at the right level (b157d05 came back at -10 dB on "
          "quiet music)", tracked > 0.0 and len(rest) and len(back), tracked)


section("S8", step3_compare_fade)

# ===========================================================================
heading("S9. Never louder than, as a true peak")


def step3_true_peak():
    import time
    brick = master(12)
    music = pink_music(12)
    rows = []
    for name, x in (("brickwalled master", brick), ("music", music)):
        for even in ("off", "gentle"):
            _g, out = run_chain(dsp.ProgramChain(RATE, even=even,
                                                 ceiling_db=-2.0), x)
            rows.append((name, even, true_peak(out[2 * RATE:])))
    print("     measured, at -2: " + "; ".join(
        "%s %s %.2f dBTP" % row for row in rows))
    check("ordinary music holds the ceiling as a true peak, within 0.1 dB",
          all(tp <= -1.9 for name, _e, tp in rows if name == "music"), rows)
    check("a brickwalled master comes out under -1.3 dBTP at a -2 ceiling "
          "(b157d05: -0.22, the sample peak ceiling let 1.8 dB through)",
          all(tp <= -1.3 for name, _e, tp in rows if name != "music"), rows)
    check("Firm, which limits hardest, starts at -3",
          getattr(C, "DEFAULT_ONAIR_FIRM_CEILING_DB", None) == -3.0
          and dsp.ProgramChain(RATE, even="firm").ceiling_db == -3.0
          and dsp.ProgramChain(RATE, even="gentle").ceiling_db == -2.0)
    old = make_board("Firm old", onair_even="firm")
    with open(old, encoding="utf-8") as f:
        data = json.load(f)
    data.pop("onair_ceiling_db", None)
    with open(old, "w", encoding="utf-8") as f:
        json.dump(data, f)
    check("a board on Firm with no ceiling saved gets Firm's",
          Board.load(old).onair_ceiling_db == -3.0)

    def switch(dialog):
        keys = [key for key, _l in C.ONAIR_EVEN_CHOICES]
        dialog.onair_ceiling.SetValue(-2.0)
        dialog.onair_even.SetSelection(keys.index("gentle"))
        dialog._onair_mode = "gentle"
        dialog.onair_even.SetSelection(keys.index("firm"))
        event = wx.CommandEvent(wx.wxEVT_CHOICE, dialog.onair_even.GetId())
        event.SetEventObject(dialog.onair_even)
        dialog.onair_even.GetEventHandler().ProcessEvent(event)
        seen["firm"] = dialog.onair_ceiling.GetValue()
        dialog.onair_ceiling.SetValue(-5.0)
        dialog.onair_even.SetSelection(keys.index("gentle"))
        dialog.onair_even.GetEventHandler().ProcessEvent(event)
        seen["chosen"] = dialog.onair_ceiling.GetValue()
        return wx.ID_CANCEL

    seen = {}
    preferences(frame, switch)
    check("in Preferences, choosing Firm moves a ceiling still at -2 to -3, "
          "and one the user chose stays where they put it",
          seen.get("firm") == -3.0 and seen.get("chosen") == -5.0, seen)

    chain = dsp.ProgramChain(RATE, even="gentle")
    piece = brick[:CHUNK]
    small = brick[:960]
    for _ in range(5):
        chain.process(piece)
    t = time.perf_counter()
    for _ in range(40):
        chain.process(piece)
    per_chunk = (time.perf_counter() - t) / 40 * 1e3
    t = time.perf_counter()
    for _ in range(200):
        chain.process(small)
    per_block = (time.perf_counter() - t) / 200 * 1e3
    print("     measured cost: %.2f ms per %d ms stream chunk, %.3f ms per "
          "20 ms block, stereo at 48 kHz"
          % (per_chunk, int(C.STREAM_CHUNK_SECONDS * 1000), per_block))
    check("and it is cheap: under a tenth of the time it processes",
          per_chunk < C.STREAM_CHUNK_SECONDS * 100.0
          and per_block < 2.0, (per_chunk, per_block))


section("S9", step3_true_peak)

# ===========================================================================
heading("S11. A trim the user set wins, nought included")


def step3_trim():
    from dropdeck import loudness
    from dropdeck.slot import Slot
    from dropdeck.playlist import Track
    slot = Slot(index=0, filepath="master.wav")
    slot.loudness, slot.peak_db, slot.loudness_for = -6.0, -0.1, "master.wav"
    slot.loudness_verified = True
    check("matched, a brickwalled master is cut", loudness.trim_for(
        slot, True) < -10.0)
    slot.trim_db = 0.0
    check("the user sets 0 dB: it plays as recorded (b157d05: -12 dB)",
          loudness.trim_for(slot, True) == 0.0, loudness.trim_for(slot, True))
    again = Slot.from_dict(0, slot.to_dict())
    again.loudness, again.peak_db = -6.0, -0.1
    again.loudness_for, again.loudness_verified = again.filepath, True
    check("and that is saved", again.trim_set is True
          and loudness.trim_for(again, True) == 0.0)
    old = Slot.from_dict(0, {"filepath": "master.wav", "trim_db": 0.0})
    old.loudness, old.peak_db = -6.0, -0.1
    old.loudness_for, old.loudness_verified = old.filepath, True
    check("an older board's 0 dB still means not set, so it is matched",
          old.trim_set is False and loudness.trim_for(old, True) < -10.0)
    kept = Slot.from_dict(0, {"filepath": "master.wav", "trim_db": -4.0})
    check("and its -4 dB is still the user's", kept.trim_set is True
          and loudness.trim_for(kept, True) == -4.0)
    slot.clear()
    check("an emptied pad is matched again", slot.trim_set is False)
    track = Track(filepath="master.wav")
    track.loudness, track.peak_db = -6.0, -0.1
    track.loudness_for, track.loudness_verified = "master.wav", True
    track.trim_db = 0.0
    check("a song's trim the same way",
          loudness.trim_for(track, True) == 0.0
          and Track.from_dict(track.to_dict()).trim_set is True)


section("S11", step3_trim)


def step3_close_mid_file():
    """Last, because it closes the frame's background work for good."""
    import time
    real_reader = audiofile.reader
    audiofile.reader = lambda path: _Slow(real_reader(path))
    try:
        frame.board.match_loudness = True
        pad = frame.board.slots[6]
        frame._apply_file(pad, LONG_FILE)
        pump_until(lambda: frame._metadata_thread is not None
                   and frame._metadata_thread.is_alive(), seconds=3.0)
        time.sleep(0.3)
        busy = (frame._metadata_thread is not None
                and frame._metadata_thread.is_alive())
        start = time.perf_counter()
        frame._closing.set()
        thread = frame._metadata_thread
        if thread is not None:
            thread.join(3.0)
        took = time.perf_counter() - start
        print("     measured: closing 0.3 s into a 12 s measurement, the pass "
              "was done after %.2f s" % took)
        check("closing in the middle of a measurement does not wait for the "
              "file: the pass is done within a fraction of a second "
              "(b157d05: the close waited its whole 3 s)",
              busy and took < 0.6, (busy, round(took, 2)))
        check("and nothing half measured is kept", pad.loudness_for is None)
    finally:
        audiofile.reader = real_reader


section("S6, closing mid file", step3_close_mid_file)

check("nothing in this file even tried to open a microphone or a source",
      OPENED == [], OPENED)
frame._stop_send(quiet=True)
for name in ("streamer", "recorder", "video_recorder"):
    setattr(frame, name, None)
frame.board.dirty = False
frame._save_timer.Stop()
frame.stop_background_work()
frame.Destroy()
app.Yield()
for line in FAILED:
    print("  failed: " + line)
print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
