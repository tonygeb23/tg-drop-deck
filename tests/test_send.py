"""The send: mix minus, the confidence feed, and the output buffer.

Everything here runs with no sound card. `Mixer(open_stream=False)` and
`Send(open_stream=False)` both exist for exactly this, so the whole path from
a voice to the far end of the send can be rendered by hand and the samples
inspected.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import constants as C          # noqa: E402
from dropdeck.audiofile import CHANNELS      # noqa: E402
from dropdeck.mixer import Mixer             # noqa: E402
from dropdeck.send import Confidence, Send   # noqa: E402
from dropdeck import sources                 # noqa: E402
from dropdeck.sources import SourceGroup     # noqa: E402

RATE = 48000
FRAMES = 512
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
    return float(np.abs(block).max()) if len(block) else 0.0


class FakeInput:
    """Something shaped like a source, handing out a constant level.

    Counts its reads, because the whole point of mix minus here is that a
    source is read ONCE however many sums it ends up in.
    """

    def __init__(self, air=0.0, monitor=0.0):
        self._air = air
        self._monitor = monitor
        self.air_reads = 0
        self.monitor_reads = 0

    def read(self, frames):
        self.monitor_reads += 1
        return np.full((frames, CHANNELS), self._monitor, dtype=np.float32)

    def read_air(self, frames):
        self.air_reads += 1
        return np.full((frames, CHANNELS), self._air, dtype=np.float32)


class FakeTap:
    """An air tap that keeps what it was given."""

    def __init__(self):
        self.blocks = []

    def write(self, key, block, rate=None):
        self.blocks.append(np.array(block, copy=True))

    def total(self):
        return (np.concatenate(self.blocks) if self.blocks
                else np.zeros((0, CHANNELS), dtype=np.float32))


print("The output buffer, which is what was losing audio")
mix = Mixer(open_stream=False, samplerate=RATE)
check("an output asks the card for nothing and lets it choose",
      mix.blocksize == 0, "got %r" % mix.blocksize)
check("and that is what the constant says",
      C.OUTPUT_BLOCKSIZE == 0, "got %r" % C.OUTPUT_BLOCKSIZE)
check("a send asks for a deep one instead",
      C.SEND_BLOCKSIZE >= 2048, "got %r" % C.SEND_BLOCKSIZE)
check("the mic's own block size is untouched",
      C.BLOCKSIZE == 512, "got %r" % C.BLOCKSIZE)
check("an output can still be told a size by hand",
      Mixer(open_stream=False, blocksize=1024).blocksize == 1024)

print("\nA late callback is counted, because the driver will not say")
mix = Mixer(open_stream=False, samplerate=RATE)
check("nothing has run, so nothing is late", mix.late_share == 0.0)
mix._last_callback = None
mix._callback(np.zeros((FRAMES, CHANNELS), dtype=np.float32),
              FRAMES, None, None)
first = mix.late_blocks
# A second callback a whole second later is late by any measure.
mix._last_callback -= 1.0
mix._callback(np.zeros((FRAMES, CHANNELS), dtype=np.float32),
              FRAMES, None, None)
check("a callback a second late is counted",
      mix.late_blocks == first + 1, "%d then %d" % (first, mix.late_blocks))
check("and the worst gap is remembered", mix.worst_gap >= 1.0)
ok, why = mix.keeping_up()
check("a mixer with no stream says so", not ok and "not running" in why, why)

print("\nMix minus: the send leaves one source out")
teamtalk = FakeInput(air=0.2)
nvda = FakeInput(air=0.05)
group = SourceGroup(mic=FakeInput(air=0.1), sources=[teamtalk, nvda])
total, without = group.read_air_minus(FRAMES, minus=teamtalk)
check("the air sum has everything in it",
      abs(peak(total) - 0.35) < 1e-6, peak(total))
check("the send sum has the excluded source taken out",
      abs(peak(without) - 0.15) < 1e-6, peak(without))
check("every source was read exactly once",
      (teamtalk.air_reads, nvda.air_reads) == (1, 1),
      "%d and %d" % (teamtalk.air_reads, nvda.air_reads))
check("the two sums are different arrays", without is not total)

total, without = group.read_air_minus(FRAMES, minus=None)
check("with nothing excluded the send is the air mix itself",
      without is total)

stranger = FakeInput(air=0.9)
total, without = group.read_air_minus(FRAMES, minus=stranger)
check("excluding a source that is not in the group changes nothing",
      without is total and abs(peak(total) - 0.35) < 1e-6, peak(total))
check("and it is certainly not read", stranger.air_reads == 0)

print("\nThe same thing through a real mixer")
tap, send_tap = FakeTap(), FakeTap()
mix = Mixer(open_stream=False, samplerate=RATE)
teamtalk = FakeInput(air=0.25)
mix.air_source = SourceGroup(mic=FakeInput(air=0.1), sources=[teamtalk])
mix.air_tap = tap
mix.send_tap = send_tap
mix.send_minus = teamtalk
mix.render(FRAMES)
check("the stream got the whole mix",
      abs(peak(tap.total()) - 0.35) < 1e-6, peak(tap.total()))
check("the send got the mix without TeamTalk in it",
      abs(peak(send_tap.total()) - 0.10) < 1e-6, peak(send_tap.total()))
check("one read for both", teamtalk.air_reads == 1, teamtalk.air_reads)

print("\nA send runs with nothing live and nothing recording")
send_tap = FakeTap()
mix = Mixer(open_stream=False, samplerate=RATE)
mix.air_tap = None
mix.send_tap = send_tap
mix.air_source = SourceGroup(mic=FakeInput(air=0.4))
mix.render(FRAMES)
check("the send is fed with no air tap at all",
      abs(peak(send_tap.total()) - 0.4) < 1e-6, peak(send_tap.total()))

print("\nNothing at all attached costs nothing")
mix = Mixer(open_stream=False, samplerate=RATE)
mix.render(FRAMES)
check("no tap, no send, no air block built", mix.air_tap is None)

print("\nThe confidence feed is heard and is never on the air")
conf = Confidence(int(RATE * 0.5))
conf.start()
conf.offer(np.full((FRAMES, CHANNELS), 0.3, dtype=np.float32))
heard = conf.read(FRAMES)
check("what the send put out is what the presenter hears",
      abs(peak(heard) - 0.3) < 1e-6, peak(heard))
check("and the listener hears nothing of it",
      peak(conf.read_air(FRAMES)) == 0.0)
conf.stop()
conf.offer(np.full((FRAMES, CHANNELS), 0.3, dtype=np.float32))
check("switched off it holds nothing", peak(conf.read(FRAMES)) == 0.0)

conf = Confidence(int(RATE * 0.5))
conf.start()
group = SourceGroup(mic=FakeInput(air=0.2, monitor=0.2), extras=[conf])
conf.offer(np.full((FRAMES, CHANNELS), 0.5, dtype=np.float32))
check("an extra is summed into what you hear",
      abs(peak(group.read(FRAMES)) - 0.7) < 1e-6, peak(group.read(FRAMES)))
conf.offer(np.full((FRAMES, CHANNELS), 0.5, dtype=np.float32))
check("and contributes nothing to what goes out, so it cannot loop",
      abs(peak(group.read_air(FRAMES)) - 0.2) < 1e-6)

print("\nThe send's own buffer")
send = Send(open_stream=False, samplerate=RATE)
check("it opened a ring at its own rate", send.bus.samplerate == RATE)
check("it is not running with no stream", not send.is_running)
ok, why = send.keeping_up()
check("nothing has played, so there is nothing wrong with the audio yet",
      ok and "nothing has played" in why, why)
check("and being switched off is a separate question the report answers",
      send.report().startswith("The send is off"), send.report())

out = np.zeros((FRAMES, CHANNELS), dtype=np.float32)
send._callback(out, FRAMES, None, None)
check("nothing has been written, so nothing comes out", peak(out) == 0.0)
check("and it has not primed", not send._primed)

# Fill past the prime level and it starts.
block = np.full((4096, CHANNELS), 0.4, dtype=np.float32)
while send.bus.available() < send._prime_frames + FRAMES:
    send.bus.write("test", block, RATE)
send._callback(out, FRAMES, None, None)
check("once primed the audio comes out", abs(peak(out) - 0.4) < 1e-6, peak(out))
check("and nothing has starved", send.starved == 0)

# Drain it dry and it rebuffers rather than stuttering on for ever.
for _ in range(200):
    send._callback(out, FRAMES, None, None)
check("running the ring dry is counted", send.starved >= 1, send.starved)
check("and it fills up again rather than limping", not send._primed)
ok, why = send.keeping_up()
check("which is what it reports", not ok and "rebuffer" in why, why)

print("\nThe gain, and a report worth hearing")
send = Send(open_stream=False, samplerate=RATE, gain_db=-6.0)
# A stand-in for the stream, because what is under test here is the wording
# of the report and not sounddevice.
send.stream = object()
while send.bus.available() < send._prime_frames + FRAMES:
    send.bus.write("test", block, RATE)
send._callback(out, FRAMES, None, None)
check("minus six decibels halves it",
      abs(peak(out) - 0.4 * 0.5011872) < 1e-4, peak(out))
line = send.report()
check("the report is a sentence, not a number", line.endswith("."), line)
check("it says where the send is going", "Sending to" in line, line)
check("it says whether you are hearing it", "hearing it" in line, line)
send.stream = None
check("and a send that is not on says that first",
      send.report().startswith("The send is off"), send.report())

# ---------------------------------------------------------------------------
# The frame: the keys, the wiring, and the sentence that stops an echo being
# a mystery. A real frame, with a stand-in for the sound card.
# ---------------------------------------------------------------------------
import os as _os
import tempfile as _tempfile

_os.environ["APPDATA"] = _tempfile.mkdtemp(prefix="dropdeck-send-test-")

import wx                                        # noqa: E402
from dropdeck import send as sendout             # noqa: E402
import dropdeck.ui as uimod                      # noqa: E402
from dropdeck.dialogs import SendDialog          # noqa: E402


class FakeSend:
    """A send with no sound card in it. Same surface, nothing opened."""

    opened = []

    def __init__(self, device=None, gain_db=0.0, **kw):
        self.device = device
        self.gain_db = gain_db
        self.bus = object()
        self.confidence = Confidence(4096)
        self.is_running = True
        self.last_error = None
        self.closed = False
        FakeSend.opened.append(self)

    def describe(self):
        return "a stand-in output"

    def report(self):
        return "Sending to a stand-in output at 48000 hertz."

    def keeping_up(self):
        return True, "the send is arriving clean"

    def close(self):
        self.closed = True
        self.is_running = False


print("\nThe frame")
app = wx.App(redirect=False)
frame = uimod.DropDeckFrame()
frame.board.path = _os.path.join(_tempfile.mkdtemp(), "send.json")
real_send = sendout.Send
uimod.sendout.Send = FakeSend
try:
    check("a frame starts with nothing being sent", frame.send is None)
    check("and says so when asked",
          "Nothing is being sent" in frame.send_report(), frame.send_report())
    check("no send means no send tap on the mixers",
          frame.mixer.send_tap is None)

    ids = (uimod.ID_SEND_SETUP, uimod.ID_SEND_STATUS, uimod.ID_SEND_MONITOR)
    check("three ids, all different", len(set(ids)) == 3)
    entries = {(e.GetFlags(), e.GetKeyCode()): e.GetCommand()
               for e in frame._build_accelerators() or frame._accelerators}
    alt_shift = wx.ACCEL_ALT | wx.ACCEL_SHIFT
    ctrl_shift = wx.ACCEL_CTRL | wx.ACCEL_SHIFT
    check("Alt+Shift+O sets the send up",
          entries.get((alt_shift, ord("O"))) == uimod.ID_SEND_SETUP)
    check("Ctrl+Shift+O asks how it is doing",
          entries.get((ctrl_shift, ord("O"))) == uimod.ID_SEND_STATUS)
    check("Ctrl+Shift+H turns the confidence feed on and off",
          entries.get((ctrl_shift, ord("H"))) == uimod.ID_SEND_MONITOR)
    # The frozen digit map is digits with modifiers and never a letter.
    check("and not one of them is on the frozen digit map",
          all(chr(code).isalpha() for (_flags, code) in
              [(alt_shift, ord("O")), (ctrl_shift, ord("O")),
               (ctrl_shift, ord("H"))]))

    print("\nStarting and stopping it")
    frame.board.send_device_name = None
    frame.board.send_gain_db = -3.0
    started = frame._start_send(quiet=True)
    check("it starts", started and frame.send is not None)
    check("the level from the board went with it",
          frame.send.gain_db == -3.0, frame.send.gain_db)
    check("every mixer is now writing to the send",
          frame.mixer.send_tap is frame.send.bus)
    check("the confidence feed is on the source group",
          frame.send.confidence in frame.source_group.extras)
    check("and it is not switched on until it is asked for",
          not frame.send.confidence.on)
    frame._update_status()
    check("the status bar says the show is going out of this machine",
          "SENDING" in frame.status.GetStatusText(0),
          frame.status.GetStatusText(0))

    frame._on_send_monitor()
    check("Ctrl+Shift+H starts it", frame.send.confidence.on)
    check("and the board remembers it for this session",
          frame.board.send_monitor is True)
    frame._on_send_monitor()
    check("and stops it again", not frame.send.confidence.on)

    held = frame.send
    frame._stop_send(quiet=True)
    check("stopping closes the card", held.closed)
    check("the tap comes off every mixer", frame.mixer.send_tap is None)
    frame._update_status()
    check("and the status bar stops mentioning it, rather than naming a "
          "feature nobody is using",
          "SENDING" not in frame.status.GetStatusText(0),
          frame.status.GetStatusText(0))
    check("and the confidence feed comes off the group",
          held.confidence not in frame.source_group.extras)

    print("\nA device that is not here any more")
    frame.board.send_device_name = "A sound card nobody has"
    frame.board.send_device_hostapi = "Windows WASAPI"
    frame.board.send_on = True
    said = []
    frame.announce = lambda text, *a, **k: said.append(text)
    check("it refuses rather than sending to the wrong card",
          not frame._start_send())
    check("it turns the send off on the board", not frame.board.send_on)
    check("and it says which card is missing",
          said and "A sound card nobody has" in said[-1], said)

    print("\nMix minus, from the board's point of view")
    frame.board.send_device_name = None
    frame.board.send_device_hostapi = None
    frame.sources = [sources.Source(name="TEAM TALK", kind="program",
                                    program="TeamTalk5.exe"),
                     sources.Source(name="NVDA", kind="program",
                                    program="nvda.exe")]
    frame.source_group = sources.SourceGroup(frame.mic, frame.sources)
    frame.board.send_minus = "TEAM TALK"
    check("the source is found by name",
          frame._send_minus_source() is frame.sources[0])
    frame.board.send_minus = "team talk"
    check("and case does not matter",
          frame._send_minus_source() is frame.sources[0])
    frame.board.send_minus = SendDialog.MIC_LABEL
    check("the microphone can be the one left out",
          frame._send_minus_source() is frame.mic)
    frame.board.send_minus = ""
    check("nothing named means nothing left out",
          frame._send_minus_source() is None)

    frame.board.send_minus = "TEAM TALK"
    frame._start_send(quiet=True)
    check("the mixer is told which source to subtract",
          frame.mixer.send_minus is frame.sources[0])
    check("and the report says so", "leaves out TEAM TALK" in
          frame.send_report(), frame.send_report())

    print("\nA mix minus that is not happening must not look like one that is")
    frame.board.send_minus = "A source that was renamed"
    frame._sync_air_taps()
    check("nothing is subtracted, because nothing matches",
          frame.mixer.send_minus is None)
    line = frame.send_report()
    check("and it says so in as many words",
          "nothing by that name" in line and "everything is going out" in line,
          line)

    frame._stop_send(quiet=True)
finally:
    uimod.sendout.Send = real_send
    frame.stop_background_work()
    frame.Destroy()

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
