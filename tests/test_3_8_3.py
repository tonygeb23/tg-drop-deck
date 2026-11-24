"""3.8.3: a microphone key that can never do nothing, a board that is never
lost, and program sources that come back by themselves.

    python tests/test_3_8_3.py

Three reports, 19 September 2026.

**Mashal, relayed by Tony:** Ctrl+M did nothing at all, on or off. Installed
and portable, after a restart, privacy settings checked, nobody else seeing
it. The app had no way to say why, because nothing was looking: a key taken
by another program never arrives, a fault inside the handler vanished into a
console a released copy does not have, and a microphone that opens and sends
silence looked exactly like one that works.

**fb40, a Windows user on 3.8.2:** "if I rename, move or copy the json file,
it acts as if it was never set up." Every start opened board.json and nothing
else; closing the app saved over a board copied in while it was open; and a
board that would not load was replaced by the demo, which then took its path.

**Tony:** a program source did not come back when Chrome was opened again.
A capture belongs to one process, and nothing went looking for the new one.

The real keystroke is pressed by `tools/check_video_key.py mic` and
`tools/check_video_key.py micalt`. Nothing in here can replace that: this
file proves the wiring and the words, not the key.
"""

import ctypes
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-383-test-")

import numpy as np
import wx

from dropdeck import board as boardmod
from dropdeck import constants as C
from dropdeck import errorlog
from dropdeck import micdiag
from dropdeck import micinput
from dropdeck import proccapture
from dropdeck import sources
from dropdeck import ui as uimod
from dropdeck.board import Board
from dropdeck.micinput import MicInput
from dropdeck.mixer import DuckBus

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" and not condition else ""))


# ===========================================================================
print("\nThe words for a failure, from the codes Windows really returns")
# ===========================================================================
IN_USE = ("Error opening InputStream: Unanticipated host error "
          "[PaErrorCode -9999]: 'Undefined external error.' "
          "[Windows WASAPI error -2004287478]")
DENIED = ("Error opening InputStream: Unanticipated host error "
          "[PaErrorCode -9999]: 'Undefined external error.' "
          "[Windows WASAPI error -2147024891]")
GONE = ("Error opening InputStream: Unanticipated host error "
        "[PaErrorCode -9999]: 'x' [Windows WASAPI error -2004287484]")
MME_BUSY = ("Error opening InputStream: Unanticipated host error "
            "[PaErrorCode -9999]: 'x' [MME error 4]")
RATE = "Error opening InputStream: Invalid sample rate [PaErrorCode -9997]"

check("exclusive use by another program is named as that",
      micdiag.explain("48000 Hz, 2 channel: " + IN_USE) == micdiag.IN_USE)
check("MME's version of the same thing is too",
      micdiag.explain(MME_BUSY) == micdiag.IN_USE)
check("access denied is named as the privacy settings",
      micdiag.explain(DENIED) == micdiag.ACCESS_DENIED)
check("and that sentence says exactly where to go",
      "Privacy and security, Microphone" in micdiag.ACCESS_DENIED)
check("an unplugged microphone is named as gone",
      micdiag.explain(GONE) == micdiag.GONE)
check("PortAudio's own invalid device is gone too",
      micdiag.explain("Invalid device [PaErrorCode -9996]") == micdiag.GONE)
check("a format refused on every try is a format problem",
      micdiag.explain(RATE + "; " + RATE) == micdiag.BAD_FORMAT)
check("the most specific reason wins over a format one",
      micdiag.explain(RATE + "; " + DENIED) == micdiag.ACCESS_DENIED)
check("an unexplained host error still gets a sentence with a next step",
      micdiag.explain("Unanticipated host error [PaErrorCode -9999]")
      == micdiag.REFUSED and "Privacy" in micdiag.REFUSED)
check("no microphone at all is said as that",
      micdiag.explain("no microphone available") == micdiag.NOTHING_THERE)
check("nothing it says contains a raw error code",
      not any("-99" in s or "0x" in s for s in (
          micdiag.IN_USE, micdiag.ACCESS_DENIED, micdiag.GONE,
          micdiag.REFUSED, micdiag.BAD_FORMAT, micdiag.NOT_AVAILABLE)))
check("and nothing it says uses a dash",
      not any(ch in s for ch in (chr(0x2013), chr(0x2014)) for s in (
          micdiag.IN_USE, micdiag.ACCESS_DENIED, micdiag.PRIVACY_BLOCKED)))


# ===========================================================================
print("\nWindows' privacy switches, read the way Settings writes them")
# ===========================================================================
def reader(values):
    def read(root, path, name):
        return values.get((root, path.rsplit("\\", 1)[-1], name))
    return read


allow = {("HKLM", "microphone", "Value"): "Allow",
         ("HKCU", "microphone", "Value"): "Allow",
         ("HKCU", "NonPackaged", "Value"): "Allow"}
check("everything allowed is allowed", micdiag.privacy(reader(allow))[0]
      == micdiag.ALLOWED)
blocked_desktop = dict(allow)
blocked_desktop[("HKCU", "NonPackaged", "Value")] = "Deny"
state, said = micdiag.privacy(reader(blocked_desktop))
check("desktop apps turned off is a block", state == micdiag.BLOCKED, state)
check("and names the switch", "Let desktop apps access your microphone" in said)
blocked_device = dict(allow)
blocked_device[("HKLM", "microphone", "Value")] = "Deny"
check("the whole device turned off is a block",
      micdiag.privacy(reader(blocked_device))[0] == micdiag.BLOCKED)
policy = dict(allow)
policy[("HKLM", "AppPrivacy", "LetAppsAccessMicrophone")] = 2
state, said = micdiag.privacy(reader(policy))
check("a policy forcing it off is a block",
      state == micdiag.BLOCKED and "policy" in said, said)
check("nothing readable is unknown, never a guess",
      micdiag.privacy(reader({}))[0] == micdiag.UNKNOWN)
check("and a reader that raises is unknown rather than a crash",
      micdiag.privacy(lambda *a: 1 / 0)[0] == micdiag.UNKNOWN)
check("this machine's own answer is one of the three",
      micdiag.privacy()[0] in (micdiag.ALLOWED, micdiag.BLOCKED,
                               micdiag.UNKNOWN))


# ===========================================================================
print("\nA key another program holds is found by asking Windows")
# ===========================================================================
VK_F11 = 0x7A
MODS = micdiag.MOD_CONTROL | micdiag.MOD_ALT | micdiag.MOD_SHIFT
held = threading.Event()
release = threading.Event()


def other_program():
    """Holds a key for the whole machine, the way another program would."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ok = user32.RegisterHotKey(None, 7, MODS | 0x4000, VK_F11)
    held.set() if ok else held.set()
    release.wait(10)
    if ok:
        user32.UnregisterHotKey(None, 7)


check("a key nobody holds is free", micdiag.held_elsewhere(MODS, VK_F11)
      is False)
holder = threading.Thread(target=other_program, daemon=True)
holder.start()
held.wait(5)
check("the same key held by somebody else is reported as taken",
      micdiag.held_elsewhere(MODS, VK_F11) is True)
check("and the list of taken keys names it by its label",
      micdiag.taken_elsewhere([("Ctrl+Alt+Shift+F11", MODS, VK_F11)])
      == ["Ctrl+Alt+Shift+F11"])
check("unless it is one this app registered itself",
      micdiag.taken_elsewhere([("Ctrl+Alt+Shift+F11", MODS, VK_F11)],
                              own=[(MODS | 0x4000, VK_F11)]) == [])
release.set()
holder.join(5)
check("and free again once it is let go",
      micdiag.held_elsewhere(MODS, VK_F11) is False)
check("the probe lets go of every key it tries, or the next probe fails",
      micdiag.held_elsewhere(MODS, VK_F11) is False)
check("keys Windows keeps for itself are not reported",
      micdiag.taken_elsewhere([("Alt+F4", micdiag.MOD_ALT, 0x73),
                               ("Ctrl+Alt+Tab",
                                micdiag.MOD_CONTROL | micdiag.MOD_ALT,
                                0x09)]) == [])

line = micdiag.keys_sentence(["Ctrl+M"])
check("a taken Ctrl+M says so and names the second key",
      "Ctrl+M" in line and "Alt+Shift+M" in line and "On air menu" in line,
      line)
line = micdiag.keys_sentence(["Ctrl+M", "Alt+Shift+M"])
check("with both taken it offers only the menu",
      "Alt+Shift+M turns" not in line and "On air menu" in line, line)
check("nothing taken says nothing", micdiag.keys_sentence([]) == "")
line = micdiag.keys_sentence(["Ctrl+B", "Ctrl+R"])
check("two keys read as a list", "Ctrl+B and Ctrl+R" in line
      and "them" in line, line)


# ===========================================================================
print("\nThe device list survives a device it cannot describe")
# ===========================================================================
real_query = micinput.sd.query_devices
real_hostapis = micinput.sd.query_hostapis
FAKE = [
    {"name": "Speakers", "hostapi": 0, "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000.0},
    {"name": "Mic A", "hostapi": 0, "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 48000.0},
    None,     # a Bluetooth headset named after somebody's phone
    {"name": "Mic B", "hostapi": 0, "max_input_channels": 1,
     "max_output_channels": 0, "default_samplerate": 44100.0},
]


def fake_query(device=None, kind=None):
    if device is None and kind is None:
        raise UnicodeDecodeError("utf-8", b"\x92", 0, 1, "invalid start byte")
    if isinstance(device, int):
        if device >= len(FAKE):
            raise micinput.sd.PortAudioError("Error querying device")
        if FAKE[device] is None:
            raise UnicodeDecodeError("utf-8", b"\x92", 0, 1, "bad")
        return dict(FAKE[device], index=device)
    raise ValueError("not faked")


micinput.sd.query_devices = fake_query
micinput.sd.query_hostapis = lambda index=None: (
    ({"name": "Windows WASAPI", "default_input_device": 1},)
    if index is None else {"name": "Windows WASAPI"})
try:
    found = micinput.input_devices()
    names = [d["name"] for d in found]
    check("one unreadable device no longer takes the whole list down",
          names == ["Mic A", "Mic B"], names)
    check("and resolving a saved microphone does not raise either",
          micinput.resolve_input({"name": "Mic B",
                                  "hostapi": "Windows WASAPI"}) == 3)
finally:
    micinput.sd.query_devices = real_query
    micinput.sd.query_hostapis = real_hostapis


# ===========================================================================
print("\nOpening: a fault half way through never leaves a running stream")
# ===========================================================================
class FakeStream:
    made = []

    def __init__(self, device=None, **kw):
        self.device = device
        self.started = self.aborted = self.closed = False
        FakeStream.made.append(self)
        if device in FakeStream.refuse:
            raise micinput.sd.PortAudioError(
                "Error opening InputStream: Unanticipated host error "
                "[PaErrorCode -9999]: 'x' [Windows WASAPI error -2004287478]")

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def abort(self):
        self.aborted = True
        self.started = False

    def close(self):
        self.closed = True


FakeStream.refuse = set()
real_stream = micinput.sd.InputStream
micinput.sd.InputStream = FakeStream
try:
    bus = DuckBus()
    mic = MicInput(duck_bus=bus, samplerate=48000)
    mic.device = 5
    real_reset = mic._reset_ring

    def exploding_reset():
        raise RuntimeError("the resampler would not build")

    mic._reset_ring = exploding_reset
    opened = mic.start(other_routes=False)
    check("a fault after the stream starts is a failure, not an escape",
          opened is False)
    check("nothing is left running", not any(s.started for s in
                                             FakeStream.made))
    check("every stream it made is closed again",
          all(s.closed for s in FakeStream.made), len(FakeStream.made))
    check("the microphone says it is closed", not mic.is_open)
    check("the music is not left ducked", not bus.loud)
    check("and the fault is in the reasons it gives",
          "resampler" in (mic.last_error or ""), mic.last_error)
    mic._reset_ring = real_reset

    # ---------------------------------------------------- another route in
    FakeStream.made = []
    FakeStream.refuse = {5}
    real_alternatives = micinput.alternatives
    micinput.alternatives = lambda device: [6, 7] if device == 5 else []
    mic = MicInput(duck_bus=DuckBus(), samplerate=48000)
    opened = mic.start(device=5)
    check("a microphone that will not open one way is tried another",
          opened and mic.device == 6, (opened, mic.device))
    check("and it says which it was asked for", mic.fell_back_from == 5)
    FakeStream.refuse = {5, 6, 7}
    mic.stop()
    opened = mic.start(device=5)
    check("when every route fails it gives up and says why",
          not opened and "-2004287478" in (mic.last_error or ""))
    check("and it goes back to pointing at the one that was chosen",
          mic.device == 5, mic.device)
    check("which is explained as another program holding it",
          micdiag.explain(mic.last_error) == micdiag.IN_USE)
    micinput.alternatives = real_alternatives
finally:
    micinput.sd.InputStream = real_stream


# Two headsets whose names MME cuts to the same 31 characters.
TWO = [
    {"index": 1, "name": "Headset Microphone (Plantronics", "hostapi": "MME",
     "channels": 1, "samplerate": 44100},
    {"index": 2, "name": "Headset Microphone (Plantronics BT600)",
     "hostapi": "Windows WASAPI", "channels": 1, "samplerate": 48000},
    {"index": 4, "name": "Headset Microphone (Plantronics Blackwire 3220 "
                         "Series)", "hostapi": "Windows WASAPI",
     "channels": 1, "samplerate": 48000},
]
real_devices = micinput.input_devices
micinput.input_devices = lambda: TWO
try:
    check("a cut name two headsets share is never taken for either",
          micinput.alternatives(1) == [], micinput.alternatives(1))
    check("and neither full name falls back to it",
          1 not in micinput.alternatives(2) and 4 not in
          micinput.alternatives(2), micinput.alternatives(2))
finally:
    micinput.input_devices = real_devices

# The system default that would not open is said, not hidden. Both of its own
# ways in refuse: WASAPI's default, which is tried first since the major
# release after 3.10.1, and MME's, which is PortAudio's None.
FakeStream.made = []
FakeStream.refuse = {None, 7}
micinput.sd.InputStream = FakeStream
real_alternatives = micinput.alternatives
micinput.alternatives = lambda device: [9] if device is None else []
real_default = micinput._default_input_index
micinput._default_input_index = lambda: 8
real_wasapi = getattr(micinput, "wasapi_default", None)
micinput.wasapi_default = lambda kind="output": 7
try:
    mic = MicInput(duck_bus=DuckBus(), samplerate=48000)
    mic.device = None
    opened = mic.start()
    check("a system default that would not open is noted as that",
          opened and mic.fell_back_from == micinput.SYSTEM_DEFAULT,
          (opened, mic.fell_back_from))
    mic.stop()
finally:
    micinput.sd.InputStream = real_stream
    micinput.alternatives = real_alternatives
    micinput._default_input_index = real_default
    if real_wasapi is not None:
        micinput.wasapi_default = real_wasapi

# A device source that came in another way is not closed and reopened.
dev_source = sources.Source(name="Mixer", device_name="Line In",
                            device_hostapi="Windows WASAPI", on_air=True)
dev_source.input.stream = object()          # open
dev_source.input.device = 9                 # the route it came in by
dev_source.input.fell_back_from = 5         # the one that was chosen
reopened = []
dev_source.input.start = lambda *a, **k: reopened.append(1) or True
real_resolve = sources.resolve_input
sources.resolve_input = lambda spec: 5
try:
    check("a source already open by another route is left open",
          dev_source.start() is True and not reopened, reopened)
finally:
    sources.resolve_input = real_resolve
    dev_source.input.stream = None

check("MME's cut down name is the same microphone",
      micinput._same_microphone("Microphone (Yeti Stereo Microph",
                                "Microphone (Yeti Stereo Microphone)"))
check("a different microphone is not",
      not micinput._same_microphone("Microphone (Realtek(R) Audio)",
                                    "Microphone (Yeti Stereo Microphone)"))
check("and a short name is not a prefix match by accident",
      not micinput._same_microphone("Mic", "Microphone (Yeti)"))
routes = micinput.alternatives(None)
check("the system default has other ways in as well", isinstance(routes, list))

mic = MicInput(duck_bus=DuckBus(), samplerate=48000)
mic._callback(np.zeros((512, 1), dtype=np.float32), 512, None, None)
check("blocks are counted as they arrive", mic.blocks_seen == 1)
check("and exact silence is not mistaken for a voice", not mic.signal_seen)
mic._callback(np.full((512, 1), 0.001, dtype=np.float32), 512, None, None)
check("the faintest real sound is", mic.signal_seen)


# ===========================================================================
print("\nThe error log catches what a released copy used to lose")
# ===========================================================================
errorlog.install()
app = wx.App(False)
probe_frame = wx.Frame(None)
probe_id = wx.NewIdRef()


def raising_handler(_event):
    raise LookupError("raised inside a handler")


probe_frame.Bind(wx.EVT_MENU, raising_handler, id=probe_id)
probe_frame.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, probe_id))
recent = errorlog.recent()
check("a handler that raises is written down",
      any("LookupError" in line for line in recent), recent)
check("by where and what kind, never the message",
      not any("inside a handler" in line for line in recent), recent)
log = errorlog.log_path()
check("with the whole traceback in the log file",
      log and os.path.exists(log)
      and "raised inside a handler" in open(log, encoding="utf-8").read())
probe_frame.Destroy()


# ===========================================================================
print("\nCtrl+M, Alt+Shift+M and what they say")
# ===========================================================================
frame = uimod.DropDeckFrame(None)
said = []
frame.speaker.say = lambda text, *a, **k: said.append(text)
entries = frame._build_accelerators()
table = {(e.GetFlags(), e.GetKeyCode()): e.GetCommand() for e in entries}
check("Ctrl+M still opens and closes the microphone",
      table.get((wx.ACCEL_CTRL, ord("M"))) == uimod.ID_MIC_TOGGLE)
check("and Alt+Shift+M does the same thing",
      table.get((wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("M")))
      == uimod.ID_MIC_TOGGLE)
check("F1 says so", "Alt+Shift+M" in C.KEYBOARD_HELP)
check("and says how to find out what took Ctrl+M",
      "NVDA+1" in C.KEYBOARD_HELP)

real_privacy = micdiag.privacy
micdiag.privacy = lambda read=None: (micdiag.ALLOWED, "")

# A fault in the handler is said, not swallowed.
real_start = frame.mic.start


def raising_start(*a, **k):
    raise RuntimeError("a driver fault on one machine")


frame.mic.start = raising_start
said.clear()
result = frame.toggle_mic()
check("a fault inside the key is said out loud", result is False and said
      and "fault" in said[-1], said[-1:] if said else "silence")
check("without reading a class name out", "RuntimeError" not in said[-1],
      said[-1:])
check("the microphone is left closed", not frame._mic_open())
check("the menu tick agrees", not frame.mic_item.IsChecked())
check("and the fault is in the error log for a feedback report",
      any("_toggle_mic: RuntimeError" in line for line in errorlog.recent()),
      errorlog.recent())

# A refusal is explained in plain words.


def refusing_start(*a, **k):
    frame.mic.last_error = "48000 Hz, 2 channel: " + IN_USE
    return False


frame.mic.start = refusing_start
said.clear()
frame.toggle_mic()
check("a refusal is explained, not recited",
      said and micdiag.IN_USE in said[-1] and "PaErrorCode" not in said[-1],
      said[-1:] if said else "silence")

micdiag.privacy = lambda read=None: (micdiag.BLOCKED,
                                     micdiag.PRIVACY_BLOCKED)
said.clear()
frame.toggle_mic()
check("and when Windows privacy is blocking it, that is what is said",
      said and micdiag.PRIVACY_FIX in said[-1], said[-1:])
micdiag.privacy = lambda read=None: (micdiag.ALLOWED, "")

# A chosen microphone that is not here is not replaced in silence.
frame.board.mic_device_name = "A Microphone Nobody Has"
frame.board.mic_device_hostapi = "Windows WASAPI"
frame.mic.device = 3                 # a stale index from an earlier open


class Opened:
    def stop(self):
        pass

    def close(self):
        pass


def opening_start(*a, **k):
    frame.mic.stream = Opened()
    frame.mic.openings += 1
    return True


frame.mic.start = opening_start
said.clear()
frame.toggle_mic()
check("a missing microphone opens the system default, not a stale index",
      frame.mic.device is None, frame.mic.device)
check("and says so, naming the one that is missing",
      said and "A Microphone Nobody Has" in said[-1]
      and "not plugged in" in said[-1], said[-1:])
frame.toggle_mic()                    # and off again
frame.board.mic_device_name = None
frame.board.mic_device_hostapi = None

# Opened another way: named as the one chosen, the route said once, queued.
calls = []
frame.speaker.say = lambda text, *a, **k: (said.append(text),
                                           calls.append(k))
real_input_name = uimod._input_name
uimod._input_name = lambda device: "Studio Microphone With A Long Full Name"
real_via = type(frame.mic).opened_via
type(frame.mic).opened_via = property(lambda self: "MME")


def fallback_start(*a, **k):
    frame.mic.stream = Opened()
    frame.mic.openings += 1
    frame.mic.fell_back_from = 21
    return True


frame.mic.start = fallback_start
frame._told_route = False
said.clear()
calls.clear()
frame.toggle_mic()
check("a microphone that came in another way is named by its full name",
      said and "Studio Microphone With A Long Full Name" in said[0], said)
check("the route is not in the line that says it is on",
      said and "MME" not in said[0], said[:1])
check("the route is said once, after it, on the chatty channel",
      len(said) == 2 and "MME" in said[1], said)
check("and queued behind it rather than cutting it off",
      len(calls) == 2 and calls[1].get("interrupt") is False, calls)
frame.toggle_mic()                    # off
said.clear()
frame.toggle_mic()                    # on again, same way in
check("and never again that session", len(said) == 1, said)
frame.toggle_mic()                    # off
uimod._input_name = real_input_name
type(frame.mic).opened_via = real_via
frame.speaker.say = lambda text, *a, **k: said.append(text)

# Opened, and then nothing arrives.
frame.mic.stream = Opened()
frame.mic.openings = 41
frame.mic.blocks_seen, frame.mic.signal_seen = 0, False
said.clear()
frame._check_mic_signal(41)
check("a microphone that sends nothing at all is noticed",
      said and "has not sent" in said[-1], said[-1:])
frame.mic.blocks_seen = 12
said.clear()
frame._check_mic_signal(41)
check("and one that sends exact silence is noticed too",
      said and "not even background noise" in said[-1], said[-1:])
frame.mic.signal_seen = True
said.clear()
frame._check_mic_signal(41)
check("a microphone that is working is left alone", not said, said)
frame.mic.signal_seen = False
said.clear()
frame._check_mic_signal(40)
check("a check meant for an earlier opening says nothing", not said, said)
frame.mic.stream = None
said.clear()
frame._check_mic_signal(41)
check("nor does one for a microphone that has been closed", not said, said)
frame.mic.start = real_start

# ---------------------------------------------------------------- keys
keys = [label for label, _m, _v in frame._app_keys()]
check("the key check covers the table", "Ctrl+M" in keys
      and "Alt+Shift+M" in keys and "Ctrl+B" in keys, keys[:8])
check("and the keys only the menus bind", "Ctrl+O" in keys, keys)
check("and never a bare key, which could not be held elsewhere",
      all("+" in k for k in keys))

real_taken = micdiag.taken_elsewhere
micdiag.taken_elsewhere = lambda keys, own=(): ["Ctrl+M"]
said.clear()
frame.board.speech_level = C.SPEECH_ESSENTIAL
frame._startup_line()
check("a taken Ctrl+M is said at startup, even with chatter turned down",
      said and "has taken Ctrl+M" in said[-1] and "Alt+Shift+M" in said[-1],
      said[-1:])
frame.board.speech_level = C.SPEECH_ALL
micdiag.taken_elsewhere = real_taken


class FakeHotkeys:
    enabled = True


frame.hotkeys, real_hotkeys = FakeHotkeys(), frame.hotkeys
frame.board[3].global_hotkey = "Ctrl+M"
clashes = frame._own_key_clashes()
check("a pad's global hotkey on Ctrl+M is caught as well",
      clashes and "Ctrl+M" in clashes[0] and "Ctrl+G" in clashes[0], clashes)
check("and our own global hotkey is never reported as somebody else's",
      "Ctrl+M" not in frame._keys_taken_elsewhere())
frame.board[3].global_hotkey = ""

# A pad whose global hotkey Windows refused is NOT ours: another program has
# the key, and that is what must be said, not that our pad plays instead.
class RefusedHotkeys:
    enabled = True
    failures = {3: "Ctrl+M"}


frame.hotkeys = RefusedHotkeys()
frame.board[3].global_hotkey = "Ctrl+M"
check("a global hotkey Windows refused is not counted as ours",
      not frame._own_global_keys(), frame._own_global_keys())
check("so no false line says our pad has the key",
      frame._own_key_clashes() == [], frame._own_key_clashes())
frame.board[3].global_hotkey = ""
frame.hotkeys = real_hotkeys

# ------------------------------------------------------- feedback report
from dropdeck import feedback  # noqa: E402
frame.board.mic_device_name = "Secret Studio Microphone"
frame.mic.last_error = "48000 Hz, 2 channel: " + IN_USE
info = feedback.diagnostics(frame)
blob = json.dumps(info)
check("a feedback report says whether the microphone key can arrive",
      "keys_taken_elsewhere" in info)
check("and what the microphone's trouble was, in words",
      info.get("mic_problem") == micdiag.IN_USE, info.get("mic_problem"))
check("with the numbers that diagnose it",
      "WASAPI error -2004287478" in info.get("mic_error_codes", ""),
      info.get("mic_error_codes"))
check("and the privacy switches", info.get("mic_privacy") in
      (micdiag.ALLOWED, micdiag.BLOCKED, micdiag.UNKNOWN))
check("and what went wrong inside the app", "recent_errors" in info)
check("but never the microphone's name", "Secret Studio" not in blob)
frame.board.mic_device_name = None
frame.mic.last_error = None
micdiag.privacy = real_privacy


# ===========================================================================
print("\nThe board that was open last is the one that opens (fb40)")
# ===========================================================================
work = tempfile.mkdtemp(prefix="dropdeck-383-boards-")
show = os.path.join(work, "My Show.json")
frame.board.stream_host = "radio.example.org"
saved = frame._save(path=show)
check("Save board as writes the board where it was asked",
      saved == show and os.path.exists(show))
check("and remembers it", boardmod.same_path(
    boardmod.remembered_board_path(), show))

check("the saved board has a server and no station name, the case that "
      "could not open", Board.load(show).stream_stations
      and not Board.load(show).stream_stations[0].get("stream_name"))
frame2 = uimod.DropDeckFrame(None)
check("and it opens: a nameless saved setup no longer stops the window",
      frame2 is not None)
check("the next start opens the board that was open, not board.json",
      boardmod.same_path(frame2.board.path, show), frame2.board.path)
check("so its streaming is still set up",
      frame2.board.stream_host == "radio.example.org")
said2 = []
frame2.speaker.say = lambda text, *a, **k: said2.append(text)
frame2._startup_line()
check("and the startup line says which board it is",
      said2 and "My Show" in said2[-1], said2[-1:])
frame2.stop_background_work()
frame2.mixer.close()
frame2.Destroy()

os.replace(show, show + ".moved")
frame3 = uimod.DropDeckFrame(None)
note = frame3._startup_board_note
check("a board that has been moved away is said, not silently replaced",
      "My Show" in note and "not in" in note, note)
check("naming the folder by its own name, never the whole path",
      "\\" not in note and os.path.basename(work) in note, note)
check("with the way to find it", "File, Open board" in note, note)
frame3.stop_background_work()
frame3.mixer.close()
frame3.Destroy()
os.replace(show + ".moved", show)

# A board that will not load is copied aside before anything can touch it.
broken = os.path.join(work, "Broken.json")
with open(broken, "w", encoding="utf-8") as handle:
    handle.write('{"app": "TG Drop Deck", "stream_host": "x",}')
boardmod.remember_board_path(broken)
frame4 = uimod.DropDeckFrame(None)
note = frame4._startup_board_note
kept = [n for n in os.listdir(work) if n.startswith("Broken (could not")]
check("a board with a mistake in it is not replaced in silence",
      "Broken could not be read" in note and "line" in note, note)
check("and says a copy is kept without reading its bracketed name out",
      "A copy is kept in the same folder" in note and "(" not in note, note)
check("it is copied aside first", len(kept) == 1, os.listdir(work))
check("and the copy is exactly what was there",
      kept and open(os.path.join(work, kept[0]), encoding="utf-8").read()
      == open(broken, encoding="utf-8").read())
frame4.stop_background_work()
frame4.mixer.close()
frame4.Destroy()

# A board saved by Notepad with a byte order mark is a board.
bom = os.path.join(work, "Notepad.json")
with open(bom, "wb") as handle:
    handle.write(b"\xef\xbb\xbf" + json.dumps(
        {"app": "TG Drop Deck", "stream_host": "bom.example.org"}).encode())
check("a board with a byte order mark loads",
      Board.load(bom).stream_host == "bom.example.org")

# ------------------------------------------- changed outside while open
live = os.path.join(work, "Live.json")
frame.board.stream_host = "mine.example.org"
frame._save(path=live)
check("a board this app just wrote has not changed on disk",
      not frame.board.changed_on_disk())
theirs = json.load(open(live, encoding="utf-8"))
theirs["stream_host"] = "theirs.example.org"
time.sleep(0.02)
with open(live, "w", encoding="utf-8") as handle:
    json.dump(theirs, handle)
check("one copied over it has", frame.board.changed_on_disk())

frame.board.dirty = False
check("closing does not write over it",
      frame._save_for_close() is None
      and json.load(open(live, encoding="utf-8"))["stream_host"]
      == "theirs.example.org")
check("nor does an autosave", frame._save(quiet=True) is None
      and json.load(open(live, encoding="utf-8"))["stream_host"]
      == "theirs.example.org")

frame.board.dirty = True
said.clear()
kept_as = frame._save(quiet=True)
check("with changes on screen as well, those go beside it under a new name",
      kept_as and kept_as != live and os.path.exists(kept_as), kept_as)
check("the copy on disk is still theirs",
      json.load(open(live, encoding="utf-8"))["stream_host"]
      == "theirs.example.org")
check("the file that came in is still the one that opens next time",
      boardmod.same_path(boardmod.remembered_board_path(), live),
      boardmod.remembered_board_path())
check("and it is said", said and "was not saved over" in said[-1]
      and "opens next time" in said[-1],
      said[-1:])

# Back to the window with nothing playing: the new file simply loads.
frame._save(path=live)
with open(live, "w", encoding="utf-8") as handle:
    json.dump(theirs, handle)
frame.board.dirty = False
frame._check_board_file(wait=True)
check("coming back to the window loads a board copied in meanwhile",
      frame.board.stream_host == "theirs.example.org",
      frame.board.stream_host)

# Pointing a board at a different file forgets the old fingerprint.
frame.board.path = os.path.join(work, "Elsewhere.json")
check("a board pointed at another file does not compare it with the last",
      not frame.board.changed_on_disk())



# ---------------------------------------------- the first run, Mark's case
# No board.json and nothing remembered: the demo opens. A board copied into
# the settings folder while it is open must not be saved over on close.
fresh_appdata = tempfile.mkdtemp(prefix="dropdeck-383-firstrun-")
os.environ["APPDATA"] = fresh_appdata
first = uimod.DropDeckFrame(None)
check("with no board at all the demo opens",
      first._loaded_demo and boardmod.same_path(
          first.board.path, boardmod.default_board_path()))
check("and it knows nothing was there",
      first.board._disk == boardmod.NOTHING_THERE, first.board._disk)
copied_in = {"app": "TG Drop Deck", "stream_host": "copied.example.org"}
with open(boardmod.default_board_path(), "w", encoding="utf-8") as handle:
    json.dump(copied_in, handle)
check("a board copied in meanwhile counts as changed",
      first.board.changed_on_disk())
first.board.dirty = False
first._save_for_close()
check("and closing does not write the demo over it",
      json.load(open(boardmod.default_board_path(), encoding="utf-8"))
      .get("stream_host") == "copied.example.org")
first._check_board_file(wait=True)
check("coming back to the window with nothing playing loads it",
      first.board.stream_host == "copied.example.org", first.board.stream_host)

# ------------------------------------------- the box that came back forever
boxes = []
real_box = wx.MessageBox
wx.MessageBox = lambda *a, **k: boxes.append(a) or wx.OK
with open(boardmod.default_board_path(), "w", encoding="utf-8") as handle:
    handle.write('{"app": "TG Drop Deck",}')
said_first = []
first.speaker.say = lambda text, *a, **k: said_first.append(text)
first._check_board_file(wait=True)
first._check_board_file(wait=True)
first._check_board_file(wait=True)
check("a board broken outside the app shows no box at all", not boxes, boxes)
check("it is said once", len([s for s in said_first
                              if "cannot be read" in s]) == 1, said_first)
wx.MessageBox = real_box
first.stop_background_work()
first.mixer.close()
first.Destroy()

# -------------------------------- unreadable and not even copyable: left alone
locked_appdata = tempfile.mkdtemp(prefix="dropdeck-383-locked-")
os.environ["APPDATA"] = locked_appdata
precious = '{"app": "TG Drop Deck", "stream_host": "precious",'   # broken
with open(boardmod.default_board_path(), "w", encoding="utf-8") as handle:
    handle.write(precious)
real_keep = uimod.DropDeckFrame._keep_unreadable
uimod.DropDeckFrame._keep_unreadable = staticmethod(lambda path: None)
locked = uimod.DropDeckFrame(None)
# Put it back as a STATIC method. Reading it off the class hands back the
# plain function, so assigning that back made it an instance method, and the
# next frame to meet an unreadable board raised TypeError inside its own
# constructor. Nothing hit that path afterwards until 3.8.4 moved the
# settings folder, which is the only reason it was ever seen.
uimod.DropDeckFrame._keep_unreadable = staticmethod(real_keep)
check("a board that could not be read or copied says it is left alone",
      "will not be saved over" in locked._startup_board_note,
      locked._startup_board_note)
locked.board.dirty = True
locked._save(quiet=True)
locked._save_for_close()
check("and nothing is ever written over it",
      open(boardmod.default_board_path(), encoding="utf-8").read()
      == precious)
locked.stop_background_work()
locked.mixer.close()
locked.Destroy()

# ------------------------------ a remembered board out of reach for one start
away_appdata = tempfile.mkdtemp(prefix="dropdeck-383-away-")
os.environ["APPDATA"] = away_appdata
stick = os.path.join(tempfile.mkdtemp(prefix="dropdeck-383-stick-"),
                     "Stick.json")
boardmod.remember_board_path(stick)                  # the stick is not in
away = uimod.DropDeckFrame(None)
away._save_for_close()
check("a board missing for one start is still the one tried next time",
      boardmod.same_path(boardmod.remembered_board_path(), stick),
      boardmod.remembered_board_path())
away.stop_background_work()
away.mixer.close()
away.Destroy()

# ---------------------------------------------- a share that never answers
real_exists = os.path.exists


def hanging(path):
    if "never-answers" in str(path):
        time.sleep(3)
    return real_exists(path)


os.path.exists = hanging
began = time.monotonic()
answer = uimod._exists_quickly(r"\\never-answers\share\Show.json",
                               timeout=0.3)
took = time.monotonic() - began
os.path.exists = real_exists
check("a board on a share that never answers is given up on quickly",
      answer is None and took < 1.5, (answer, round(took, 2)))

# ------------------------------------------------ read only, and no litter
readonly = os.path.join(tempfile.mkdtemp(prefix="dropdeck-383-ro-"),
                        "ReadOnly.json")
Board().save(readonly)
os.chmod(readonly, 0o444)
began = time.monotonic()
try:
    Board().save(readonly)
    refused = False
except OSError:
    refused = True
took = time.monotonic() - began
os.chmod(readonly, 0o666)
check("a read only board is refused at once, not after a second of retries",
      refused and took < 0.5, (refused, round(took, 2)))
check("and the half written save is not left beside it",
      not os.path.exists(readonly + ".tmp"))

# ------------------------------------------------ claiming a path
claimed = Board()
spot = os.path.join(work, "Claimed.json")
claimed.claim_path(spot)
check("claiming a path with nothing there remembers that",
      claimed._disk == boardmod.NOTHING_THERE and not claimed.changed_on_disk())
Board().save(spot)
check("and something appearing there is somebody else's",
      claimed.changed_on_disk())
claimed.claim_path(spot)
check("claiming what is there takes it as ours",
      not claimed.changed_on_disk())
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-383-after-")

# ===========================================================================
print("\nProgram sources come back when the program does")
# ===========================================================================
check("a program that is running is found by its executable",
      proccapture.is_running("explorer.exe"))
check("and one that is not, is not",
      not proccapture.is_running("a-program-nobody-has.exe"))
# find_pid: the process with the window or the sound, by the executable.
real_programs = proccapture.running_programs
real_table = proccapture._process_table
proccapture.running_programs = lambda: [
    {"name": "Chrome.exe", "pid": 700, "title": "YouTube", "kind": "window"}]
proccapture._process_table = lambda: [("chrome.exe", 700, 4),
                                      ("chrome.exe", 701, 700)]
check("a program is found by its executable whatever its window says",
      proccapture.find_pid("chrome.exe") == 700)
proccapture.running_programs = lambda: []
proccapture._process_table = lambda: [("helper.exe", 902, 901),
                                      ("helper.exe", 901, 12),
                                      ("helper.exe", 903, 901)]
check("with no window and no sound yet, the process at the top is taken",
      proccapture.find_pid("helper.exe") == 901)
proccapture.running_programs = real_programs
proccapture._process_table = real_table

source = sources.Source(name="Chrome", kind=sources.Source.PROGRAM,
                        program="chrome-that-is-not-here.exe", on_air=True)
check("a program source that is not capturing is waiting for its program",
      source.waiting_for_program())
check("while the program is not running nothing is started",
      source.find_again(now=100.0) is False
      and "not running" in (source.last_error or ""))

real_running = proccapture.is_running
starts = []
proccapture.is_running = lambda exe: True
source.start = lambda rate=None, **kw: starts.append(kw) or False
check("a program that has only just started is given a moment first",
      source.find_again(now=200.0) is False and not starts)
settled = 200.0 + C.SOURCE_SETTLE_SECONDS + 0.1
check("and then it is started", source.find_again(now=settled) is True
      and len(starts) == 1)
check("without waiting on the window's thread",
      starts and starts[0].get("wait") is False, starts)
check("with mute and solo handed over first", "soloed" in starts[0], starts)
check("the next look waits", source.find_again(now=settled + 1) is False
      and len(starts) == 1)
check("and then tries again",
      source.find_again(now=settled + C.SOURCE_RETRY_SECONDS + 0.1) is True
      and len(starts) == 2)
source.lost_program(now=300.0)
check("just after a program closes it waits for it to finish closing",
      source.find_again(now=301.0) is False and len(starts) == 2)
proccapture.is_running = real_running

# The one snapshot is used rather than a new one per source.
calls = []
source2 = sources.Source(name="Zoom", kind=sources.Source.PROGRAM,
                         program="zoom.exe", on_air=True)
real_running = proccapture.is_running
proccapture.is_running = lambda exe: calls.append(exe) or False
source2.find_again(now=100.0, running={"explorer.exe"})
check("a snapshot handed in is used instead of taking another", not calls,
      calls)
proccapture.is_running = real_running

# A muted source reattached is not on air for a moment first.
muted = sources.Source(name="Game", kind=sources.Source.PROGRAM,
                       program="game.exe", on_air=True)
muted.muted = True
seen = {}
muted._start_program = lambda wait=True, air=None, monitor=None: seen.update(
    air=air, now=muted.input.on_air) or False
muted.start(wait=False, soloed=False)
check("a muted source starts with the air off",
      seen.get("air") is False and seen.get("now") is False, seen)

# A capture still coming up is not started twice.
capture = proccapture.ProcessCapture(pid=os.getpid())


class Busy:
    def is_alive(self):
        return True


capture._thread = Busy()
check("a capture still coming up is not started a second time",
      capture.start(wait=False) is False)
capture._thread = None


class FakeProgramSource:
    is_program = True
    wanted_on_air = True
    wanted_monitor = False
    muted = soloed = False

    class input:                       # what the air taps set on a source
        on_air = monitor = False

    def __init__(self, name, was_open, is_open, comes_back=False):
        self.name, self.program = name, name.lower() + ".exe"
        self.was_open, self.is_open = was_open, is_open
        self.comes_back = comes_back
        self.lost = False
        self.looked = []

    def wants_air(self, soloed=False):
        return True

    def wants_monitor(self, soloed=False):
        return False

    def waiting_for_program(self):
        return not self.is_open

    def lost_program(self, now=None):
        self.lost = True

    def find_again(self, samplerate=None, now=None, running=None,
                   soloed=None):
        self.looked.append(running)
        if self.comes_back:
            self.is_open = True        # comes up on its own thread
        return self.comes_back


closing = FakeProgramSource("Chrome", was_open=True, is_open=False)
returning = FakeProgramSource("TeamTalk", was_open=False, is_open=False,
                              comes_back=True)
real_sources = frame.sources
frame.sources = [closing, returning]
mixing = []
real_mixing = frame.apply_source_mixing
frame.apply_source_mixing = lambda: mixing.append(1)
frame.board.speech_level = C.SPEECH_ALL
said.clear()
frame._next_source_watch = 0.0
frame._watch_program_sources()
check("a program closing is said once",
      any("chrome closed, so it is silent" in s for s in said), said)
check("without reading the file extension out",
      not any(".exe" in s for s in said), said)
check("and it is told to wait before looking again", closing.lost)
check("a waiting program is looked for with one shared snapshot",
      returning.looked and isinstance(returning.looked[0], set)
      and closing.looked and closing.looked[0] is returning.looked[0])
check("and nothing is announced before the capture is really up",
      not any("teamtalk" in s for s in said), said)
said.clear()
frame._next_source_watch = 0.0
frame._watch_program_sources()
check("it is announced once it has come up",
      any("teamtalk is back" in s for s in said), said)
check("with mute and solo put back on it", mixing)
said.clear()
frame._watch_program_sources()
check("and nothing is said twice, or before the next look", not said, said)
frame.sources = real_sources
frame.apply_source_mixing = real_mixing


# ===========================================================================
frame.stop_background_work()
frame.mixer.close()
frame.Destroy()
print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.stdout.flush()
os._exit(0 if all(CHECKS) else 1)
