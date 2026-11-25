"""Final team audit of the major release, 24 November 2026: the code fixes.

    python tools/run_private.py --timeout 600 tests/test_review_final.py

Every `check` here fails on f324179 and passes on the fix. A `guard` is a
thing that was already right and has to stay right; guards pass on both and
are counted on a line of their own.

  1. looking at the demo pack writes nothing, and it does not open next time;
  2. the go live summary and the status bar say when the microphone is not
     going out, and why, and Put it right goes where the reason was made;
  3. a station picked inside Preferences cannot send the microphone into its
     own cable;
  4. a save only the background pass asked for fails in silence;
  5. "never named" counts only in the settings folder;
  6. a control character in a pad's name never reaches a menu as a key;
  7. tools/check_guide.py reaches nothing outside its own process;
  8. Delete twice: ten seconds, the new words, and a song change between;
  9. a compare left bypassed is said in three places, and the hint;
 10. global hotkeys that are not used, one sentence a reason;
 11. the first start note;
 12. the microphone channel: "mix" is the plain average again, "voice" new;
 13. F1;
 14. the record folder note, once a session;
 15. the labels a pad's key reaches, after a rename, a clear and a hide;
 16. the leftover home after Save as: after a restart, and through a junction;
 17. an album from a board file is text or nothing;
 18. Delete, not Del, on the menus;
 19. today's names;
 20. the ceiling claims;
 21. the send's cost, as Jackson measured it;
 22. the cable's sample rate steps;
 23. the streaming help: YouTube's sentence under YouTube, no capitals.

Speech is what reaches a frame's speaker at a given `speech_level`. Keys and
menu items are posted as command events to the frame, the window that really
receives them, and Preferences is the real window driven in code. Nothing
opens a sound card, a microphone or a camera, nothing makes a sound, no key
is pressed, the network is shut, and every modal window is stood in. Item 7
runs tools/check_guide.py in a child process of this one, which inherits its
private desktop and its silent speech, with Windows' credential store, the
sound cards, the network and the plugin loader stood in and watched.
"""

import copy
import ctypes
import faulthandler
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

faulthandler.enable()
faulthandler.dump_traceback_later(570, exit=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_BASE = tempfile.mkdtemp(prefix="dropdeck-final-")
os.environ["APPDATA"] = os.path.join(_BASE, "appdata")
os.environ["TGDROPDECK_DATA"] = os.path.join(_BASE, "data")
for _folder in (os.environ["APPDATA"], os.environ["TGDROPDECK_DATA"]):
    os.makedirs(_folder, exist_ok=True)


def _no_network(*_a, **_kw):
    raise OSError("no network in tests/test_review_final.py")


socket.create_connection = _no_network
socket.socket.connect = lambda self, *a, **kw: _no_network()
socket.socket.connect_ex = lambda self, *a, **kw: _no_network()

import numpy as np                                     # noqa: E402
import soundfile as sf                                 # noqa: E402
import wx                                              # noqa: E402

from dropdeck import board as boardmod                 # noqa: E402
from dropdeck import cabletest                         # noqa: E402
from dropdeck import constants as C                    # noqa: E402
from dropdeck import dialogs                           # noqa: E402
from dropdeck import endpoints as EP                   # noqa: E402
from dropdeck import feedback                          # noqa: E402
from dropdeck import globalhotkeys                     # noqa: E402
from dropdeck import micinput                          # noqa: E402
from dropdeck import playlist as playlistmod           # noqa: E402
from dropdeck import preflight                         # noqa: E402
from dropdeck import secrets                           # noqa: E402
from dropdeck import send as sendmod                   # noqa: E402
from dropdeck import sources                           # noqa: E402
from dropdeck import streamhelp                        # noqa: E402
from dropdeck import streamout                         # noqa: E402
from dropdeck import streamstats                       # noqa: E402
from dropdeck import ui as uimod                       # noqa: E402
from dropdeck.audiofile import CHANNELS                # noqa: E402
from dropdeck.board import Board, same_path            # noqa: E402
from dropdeck.micinput import MicInput                 # noqa: E402
from dropdeck.mixer import Mixer, MixerGroup           # noqa: E402
from dropdeck.playlist import Track                    # noqa: E402
from dropdeck.plids import ID_PL_ROW_REMOVE            # noqa: E402

RATE = 48000
BLOCK = 512
CHECKS = []
GUARDS = []
FAILED = []


def check(label, condition, detail=""):
    """A fix: fails on f324179, passes now."""
    CHECKS.append(bool(condition))
    _show(label, condition, detail)


def guard(label, condition, detail=""):
    """Already right, and must stay right."""
    GUARDS.append(bool(condition))
    _show("(guard) " + label, condition, detail)


def _show(label, condition, detail):
    if not condition:
        FAILED.append(label + (("  " + str(detail)) if detail != "" else ""))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" and not condition else ""))


def heading(text):
    print("\n" + text)


def section(label, body):
    """One item. A raise is a failed check, so f324179 runs to the end."""
    try:
        body()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stdout)
        check("%s (raised %s: %s)" % (label, type(exc).__name__, exc), False)


def flat(text):
    """Text as a screen reader runs it together: wrapping is not words."""
    return " ".join(str(text or "").split())


# ---------------------------------------------------------------- stand-ins --
app = wx.App(False)
app.SetExitOnFrameDelete(False)
BOXES = []
ANSWERS = []


def fake_box(message="", caption="", style=0, parent=None, *a, **kw):
    BOXES.append((message, caption, style))
    return ANSWERS.pop(0) if ANSWERS else wx.OK


wx.MessageBox = fake_box
secrets.fetch = lambda name, prefix=None: None
secrets.store = lambda *a, **kw: True
secrets.forget = lambda *a, **kw: None
secrets.key_for = lambda name, host, trusted=(): ("", None, "")
secrets.unconfirmed = lambda name: False
uimod.DropDeckFrame._start_update_check = lambda self: None
uimod.DropDeckFrame._maybe_ask_about_donating = lambda self: None
uimod.DropDeckFrame._clean_update_staging = lambda self: None
feedback.flush_in_background = lambda: None
os.startfile = lambda *a, **kw: None
# The startup line asks Windows whether another program holds our keys by
# registering each one for a moment. Not here.
uimod.micdiag.taken_elsewhere = lambda keys, own=None: []
uimod.resolve_device = lambda spec: None
uimod.resolve_input = lambda spec: None
uimod.describe_input = lambda device: "Laptop Mic"
uimod._input_name = lambda device: "Laptop Mic"
Mixer._device_rate = staticmethod(lambda device: RATE)
cabletest.capture_for = lambda name, found=None: ""
micinput.default_input_name = lambda: "Microphone (Yeti Stereo Microphone)"


class Opened:
    """A microphone stream that is open and is nothing at all."""

    active = True

    def stop(self):
        pass

    def close(self):
        pass


def stand_in_start(self, device=None, other_routes=True):
    """Opens nothing. Pretends to, so the sentence after it can be heard."""
    self.fell_back_from = None
    self.stream = Opened()
    self.openings += 1
    return True


MicInput.start = stand_in_start


class QuietGroup(MixerGroup):
    def __init__(self, *args, **kw):
        kw["open_stream"] = False
        super().__init__(*args, **kw)

    @property
    def is_running(self):
        return True


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


class _Running:
    active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


class FakeSend(sendmod.Send):
    """A send that is running and goes nowhere."""

    def __init__(self, device=None, gain_db=0.0, **kw):
        super().__init__(device=device, samplerate=RATE, gain_db=gain_db,
                         open_stream=False)
        self.stream = _Running()

    def start(self):
        self.stream = _Running()
        return True


sendmod.Send = FakeSend


class FakeFileDialog:
    """wx.FileDialog, answered: a path, or Cancel when there is none."""

    opened = []
    answer = [None]

    def __init__(self, parent=None, message="", *a, **kw):
        FakeFileDialog.opened.append((message, dict(kw)))

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def ShowModal(self):
        return wx.ID_OK if FakeFileDialog.answer[0] else wx.ID_CANCEL

    def GetPath(self):
        return FakeFileDialog.answer[0] or ""

    def GetPaths(self):
        return [FakeFileDialog.answer[0]] if FakeFileDialog.answer[0] else []

    def Destroy(self):
        pass


class Scripted(dialogs.SettingsDialog):
    """Preferences, the real window, with a script where a person would be."""

    script = None
    pages = []

    def __init__(self, *args, **kw):
        Scripted.pages.append(kw.get("page"))
        super().__init__(*args, **kw)

    def ShowModal(self):
        return Scripted.script(self)

    @property
    def chosen_device(self):
        return (None, self.board.device_name, self.board.device_hostapi)

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


def preferences(script):
    Scripted.script = staticmethod(script)
    frame._on_settings()


class PutItRight(dialogs.GoLiveDialog):
    """The real go live window. Each ShowModal presses Put it right or Stay
    off air, through the button's own binding, and nothing waits."""

    answers = []
    shown = []

    def ShowModal(self):
        PutItRight.shown.append([note.text for note in self.report.notes])
        self._ended = wx.ID_CANCEL
        if (PutItRight.answers and PutItRight.answers.pop(0) == "fix"
                and getattr(self, "putright", None) is not None):
            event = wx.CommandEvent(wx.wxEVT_BUTTON, self.putright.GetId())
            event.SetEventObject(self.putright)
            self.putright.GetEventHandler().ProcessEvent(event)
        return self._ended

    def EndModal(self, code):
        try:
            self.remember = bool(self.again.GetValue())
        except Exception:
            pass
        self._ended = code


class FakeSourceControl:
    """Source control, opened and closed again, and counted."""

    opened = []

    def __init__(self, parent=None, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def ShowModal(self):
        FakeSourceControl.opened.append(True)
        return wx.ID_OK


class FakeText:
    """ask_text's window, answered with a name."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def ShowModal(self):
        return wx.ID_OK

    def GetValue(self):
        return self.value

    def Destroy(self):
        pass


class Ear:
    """A frame's speaker: what would have been said, and how."""

    def __init__(self):
        self.said = []
        self.available = True

    def say(self, text, interrupt=True):
        self.said.append((text, interrupt))

    @property
    def texts(self):
        return [text for text, _i in self.said]


def pump(seconds=0.0):
    """Let wx run. A timer needs the real event loop, so a wait runs
    MainLoop for that long, and really that long: a loop that came back
    early is run again, and the timer meant to end it is stopped, or it
    would end the next wait early instead, and that one the next."""
    app.ProcessPendingEvents()
    app.Yield()
    if seconds > 0:
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0.005:
                break
            later = wx.CallLater(max(1, int(left * 1000)), app.ExitMainLoop)
            app.MainLoop()
            try:
                later.Stop()
            except Exception:
                pass
        app.ProcessPendingEvents()


def post(window, command):
    """A key or a menu item, the way Windows hands it to the frame."""
    event = wx.CommandEvent(wx.wxEVT_MENU, command)
    event.SetEventObject(window)
    window.GetEventHandler().ProcessEvent(event)


ALT_SHIFT = wx.ACCEL_ALT | wx.ACCEL_SHIFT
CTRL_SHIFT = wx.ACCEL_CTRL | wx.ACCEL_SHIFT
TMP = tempfile.mkdtemp(prefix="dropdeck-final-files-")


def wav(name, seconds=2.0, level=0.0):
    path = os.path.join(TMP, name + ".wav")
    data = np.zeros((int(RATE * seconds), CHANNELS), np.float32)
    if level:
        t = np.arange(len(data)) / RATE
        data[:, 0] = data[:, 1] = level * np.sin(2 * np.pi * 440 * t)
    sf.write(path, data, RATE)
    return path


def make_board(name, **fields):
    board = Board()
    for key, value in fields.items():
        setattr(board, key, value)
    path = os.path.join(TMP, name + ".json")
    board.save(path)
    return path


def starting(path):
    """A start of the app on `path`, heard from the very first moment. Past
    its startup line (half a second) and its sources (1.2 s)."""
    boardmod.remember_board_path(path)
    made = uimod.DropDeckFrame(None)
    heard = Ear()
    made.speaker = heard
    made._check_mic_signal = lambda *a, **k: None
    made.Show()
    pump(1.4)
    return made, heard


def close_frame(made):
    for step in (lambda: made.stop_background_work(),
                 lambda: made.mixer.close(),
                 lambda: setattr(made.board, "dirty", False),
                 lambda: made._save_timer.Stop(),
                 lambda: made.Destroy()):
        try:
            step()
        except Exception:
            pass
    pump(0.1)


def wait_for_pass(made, limit=40.0, quiet=2.6):
    """Until the background pass is done and no save is waiting, and has
    stayed that way for `quiet` seconds, so a two second save timer started
    by the pass has had its chance to fire."""
    end = time.monotonic() + limit
    calm = None
    while time.monotonic() < end:
        pump(0.2)
        thread = made._metadata_thread
        busy = ((thread is not None and thread.is_alive())
                or made._save_timer.IsRunning())
        if busy:
            calm = None
        elif calm is None:
            calm = time.monotonic()
        elif time.monotonic() - calm >= quiet:
            return True
    return False


def settings_files():
    folder = boardmod.config_dir()
    return sorted(name for name in os.listdir(folder)
                  if name.endswith(".json"))


# --------------------------------------------------- what Windows reads --
user32 = ctypes.windll.user32
_send_message = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM,
    wintypes.LPARAM)(("SendMessageW", user32))
SB_GETTEXTLENGTHW, SB_GETTEXTW = 0x0400 + 12, 0x0400 + 13


def native_field(bar, n):
    """One field of a status bar as the native control holds it, which is
    what NVDA+End reads."""
    hwnd = bar.GetHandle()
    length = _send_message(hwnd, SB_GETTEXTLENGTHW, n, 0) & 0xFFFF
    buf = ctypes.create_unicode_buffer(length + 2)
    _send_message(hwnd, SB_GETTEXTW, n, ctypes.addressof(buf))
    return buf.value


START = make_board("Start")
ESSENTIAL = C.SPEECH_ESSENTIAL


# ===========================================================================
heading("1. Looking at the demo pack writes nothing, and opens nothing")


def item_1():
    boardmod.remember_board_path(START)
    made, _heard = starting(START)
    try:
        demo_path = boardmod.demo_board_path()
        guard("the demo pack is installed beside the app",
              os.path.exists(demo_path), demo_path)
        post(made, uimod.ID_DEMO)
        pump(0.2)
        demo = made.board
        home = demo.path or ""
        guard("File, Load demo pack gives it a home of its own, not yet written",
              os.path.basename(home) == "Demo board.json"
              and not os.path.exists(home), home)
        guard("its background pass runs to the end",
              wait_for_pass(made, 60.0))
        check("the pass writes no Demo board.json for a board nobody touched",
              not os.path.exists(home), settings_files())
        check("so the demo is not the board that opens next time",
              same_path(boardmod.remembered_board_path(), START),
              boardmod.remembered_board_path())
        guard("and nothing on it is marked as changed", not demo.dirty)
        # A pass that comes back after File, New, for the demo that left.
        BOXES.clear()
        post(made, wx.ID_NEW)
        pump(0.1)
        guard("File, New takes its place", made.board is not demo)
        made._playlist_metadata_ready(demo)
        pump(0.2)
        check("a pass for the demo that comes back after File, New writes "
              "nothing either", not os.path.exists(home), settings_files())
        made.Close()
        pump(0.4)
        check("and after closing, the board that opens next time is still "
              "the one that was open first",
              same_path(boardmod.remembered_board_path(), START)
              and not os.path.exists(home),
              (boardmod.remembered_board_path(), settings_files()))
    finally:
        close_frame(made)
        boardmod.remember_board_path(START)


section("1", item_1)

# The window most items use, on a board of the user's.
boardmod.remember_board_path(START)
frame, _first_heard = starting(START)
ear = Ear()
frame.speaker = ear


def hear(action, wait=0.0, level=ESSENTIAL):
    """What reaches the speaker while `action` runs, as words."""
    frame.board.speech_level = level
    frame._menu_closed_at = None
    ear.said.clear()
    action()
    pump(wait)
    return list(ear.texts)


def mic_off():
    if frame._mic_open():
        frame.mic.stop()
        frame.mic_item.Check(False)


def radio(board):
    board.stream_name = "Blindside Radio"
    board.stream_host = "stream.example.com"
    board.stream_mount = "/live"
    board.stream_password = "hackme"
    board.live_to = C.LIVE_TO_AUDIO


def real_preferences(page):
    return dialogs.SettingsDialog(frame, frame.board, frame.mixer,
                                  mic=frame.mic, page=page)


S = dialogs.SettingsDialog


# ===========================================================================
heading("2. The summary and the status bar say when the microphone is out")


def mic_line(report):
    return dict(report.lines).get("Microphone")


def mic_notes(report):
    return [(note.level, note.text, note.fix) for note in report.notes
            if note.text.startswith("Microphone:")]


def item_2():
    radio(frame.board)
    frame.board.stream_mic = True
    mic_off()
    frame._mic_named = "Laptop Mic"
    post(frame, uimod.ID_MIC_TOGGLE)
    frame.send = FakeSend()
    frame._sync_air_taps()
    was_sources = frame.sources
    try:
        guard("the microphone is open and the show is going out of the send",
              frame._mic_open() and frame.sending())
        frame.mic.muted = True
        frame.apply_source_mixing()
        report = frame.preflight()
        guard("Ctrl+M's own answer, the one that decides what goes out",
              frame._mic_off_air_reason() == "you are muted in Source control"
              and not frame.mic.on_air)
        check("muted in Source control, the summary says the microphone is "
              "NOT going out, and why",
              mic_line(report) == "NOT going out, you are muted in Source "
                                  "control", mic_line(report))
        check("as a warning, whose Put it right opens Source control",
              mic_notes(report) == [(preflight.WARN, "Microphone: NOT going "
                                     "out, you are muted in Source control",
                                     getattr(C, "FIX_SOURCE_CONTROL", "-"))],
              mic_notes(report))
        bar = native_field(frame.status, 0)
        check("and the status bar says Mic ON, not going out",
              bar.startswith("Mic ON, not going out (Ctrl+M)"), bar)

        # Put it right, pressed, in the real go live window.
        real_live, real_control = uimod.GoLiveDialog, uimod.SourceControlDialog
        uimod.GoLiveDialog = PutItRight
        uimod.SourceControlDialog = FakeSourceControl
        PutItRight.shown.clear()
        PutItRight.answers[:] = ["fix", "stay"]
        FakeSourceControl.opened.clear()
        Scripted.pages.clear()
        Scripted.script = staticmethod(lambda dialog: wx.ID_CANCEL)
        try:
            post(frame, uimod.ID_STREAM_TOGGLE_AUDIO)
        finally:
            uimod.GoLiveDialog = real_live
            uimod.SourceControlDialog = real_control
        check("Put it right on it opens Source control, and not Preferences",
              FakeSourceControl.opened == [True] and Scripted.pages == [],
              (FakeSourceControl.opened, Scripted.pages, PutItRight.shown))
        guard("and the show stayed off the air", not frame.streaming())

        frame.mic.muted = False
        other = sources.Source(name="Call", device_name="Line in",
                               samplerate=RATE)
        other.soloed = True
        frame.sources = [other]
        frame.apply_source_mixing()
        report = frame.preflight()
        check("another source soloed: NOT going out, and why",
              mic_line(report) == "NOT going out, a source is soloed"
              and mic_notes(report) == [(
                  preflight.WARN, "Microphone: NOT going out, a source is "
                  "soloed", getattr(C, "FIX_SOURCE_CONTROL", "-"))],
              (mic_line(report), mic_notes(report)))
        check("and the status bar says so too",
              native_field(frame.status, 0).startswith(
                  "Mic ON, not going out (Ctrl+M)"),
              native_field(frame.status, 0))
        frame.sources = was_sources
        frame.apply_source_mixing()

        frame.board.stream_mic = False
        frame._sync_air_taps()
        frame.apply_source_mixing()
        report = frame.preflight()
        check("Send my microphone off reads the same way as the other two, "
              "and its Put it right is the Microphone page",
              mic_line(report) == "NOT going out, Send my microphone is off"
              and mic_notes(report) == [(
                  preflight.WARN, "Microphone: NOT going out, Send my "
                  "microphone is off", C.FIX_MIC)],
              (mic_line(report), mic_notes(report)))
        check("and the status bar says Mic ON, not going out for it as well",
              native_field(frame.status, 0).startswith(
                  "Mic ON, not going out (Ctrl+M)"),
              native_field(frame.status, 0))

        frame.board.stream_mic = True
        frame._sync_air_taps()
        frame.apply_source_mixing()
        report = frame.preflight()
        guard("with nothing keeping it out: on the air, no warning, Mic ON",
              mic_line(report) == "on the air" and not mic_notes(report)
              and native_field(frame.status, 0).startswith("Mic ON (Ctrl+M)"),
              (mic_line(report), native_field(frame.status, 0)))
    finally:
        frame.sources = was_sources
        frame.mic.muted = False
        frame.send = None
        mic_off()
        frame._sync_air_taps()
        frame.apply_source_mixing()


section("2", item_2)


# ===========================================================================
heading("3. A station picked inside Preferences cannot loop the microphone")


def item_3():
    cable_in = "CABLE Input (VB-Audio Virtual Cable)"
    cable_out = "CABLE Output (VB-Audio Virtual Cable)"
    board = frame.board
    kept = {field: copy.deepcopy(getattr(board, field)) for field in (
        "stream_stations", "send_on", "send_device_name", "mic_device_name",
        "stream_mic", "stream_name", "stream_host", "stream_mount",
        "stream_password", "live_to")}
    real_default = micinput.default_input_name
    micinput.default_input_name = lambda: cable_out
    try:
        radio(board)
        board.stream_name = "Loop FM"
        board.stream_mic = True
        board.save_station()
        board.stream_name = "Quiet"
        board.stream_mic = False
        board.save_station()
        board.send_on = True
        board.send_device_name = cable_in
        board.mic_device_name = cable_out
        frame.send = FakeSend()
        frame._sync_air_taps()
        mic_off()
        post(frame, uimod.ID_MIC_TOGGLE)
        guard("the microphone on the far end of the send's own cable is open, "
              "with Send my microphone off",
              frame._mic_open() and frame.sending() and not frame.mic.on_air)
        guard("the send's loop guard knows that cable",
              bool(frame._send_loops([(uimod._YOUR_MIC,
                                       frame._mic_capture_name())])))

        def pick_and_ok(dialog):
            names = dialog.stream_picker.GetStrings()
            dialog.stream_picker.SetSelection(names.index("Loop FM"))
            dialog._on_pick_station(None)
            return wx.ID_OK

        said = hear(lambda: preferences(pick_and_ok), wait=0.6)
        check("picking that station in Preferences and pressing OK leaves "
              "the microphone out of the send",
              board.stream_mic is False and frame.mic.on_air is False,
              (board.stream_mic, frame.mic.on_air))
        check("and says why, as the On air menu says it",
              any("back into itself" in text for text in said), said)
    finally:
        micinput.default_input_name = real_default
        frame.send = None
        mic_off()
        for field, value in kept.items():
            setattr(board, field, value)
        frame._sync_air_taps()


section("3", item_3)


# ===========================================================================
heading("5. Never named counts only in the settings folder")


def item_5():
    real = wx.FileDialog
    wx.FileDialog = FakeFileDialog
    try:
        mac = os.path.join(TMP, "Named on the Mac.json")
        board = Board()
        board[0].filepath = wav("One", 0.5)
        board.never_named = True
        board.save(mac)
        with open(mac, encoding="utf-8") as handle:
            guard("a Mac Save As left never named in it",
                  json.load(handle).get("never_named") is True)
        frame._open_board(mac)
        check("opened from a folder of the user's, it is a board with a name",
              frame.board.never_named is False, frame.board.never_named)
        with open(mac, "rb") as handle:
            before = handle.read()
        frame.board[1].filepath = wav("Two", 0.5)
        frame._touch()
        FakeFileDialog.opened.clear()
        FakeFileDialog.answer[0] = None
        post(frame, wx.ID_SAVE)
        with open(mac, "rb") as handle:
            after = handle.read()
        check("so Ctrl+S saves it where it is, the way the save timer does, "
              "and asks for no name",
              not FakeFileDialog.opened and after != before
              and same_path(frame.board.path, mac), FakeFileDialog.opened)
        with open(mac, encoding="utf-8") as handle:
            check("and the file stops saying it was never named",
                  json.load(handle).get("never_named") is False)
    finally:
        wx.FileDialog = real
        frame._open_board(START)


section("5", item_5)


# ===========================================================================
heading("6. A control character in a pad's name is never a key")


def item_6():
    board = Board()
    misc = board.bank_slots(C.BANK_MISC)
    misc[0].filepath = wav("Applause", 0.5)
    misc[0].name = "Applause" + chr(9) + "Ctrl+Shift+Z"
    misc[0].custom_hotkey = "Alt+Shift+A"
    misc[0].key_code, misc[0].modifiers = ord("A"), ALT_SHIFT
    misc[1].filepath = wav("Horn", 0.5)
    misc[1].name = "Horn" + chr(9) + "1"
    misc[1].custom_hotkey = "Alt+Shift+P"
    misc[1].key_code, misc[1].modifiers = ord("P"), ALT_SHIFT
    misc[2].filepath = wav("Lines", 0.5)
    misc[2].name = "Line one" + chr(13) + chr(10) + "Line two"
    path = os.path.join(TMP, "Control characters.json")
    board.save(path)
    frame._open_board(path)
    try:
        add = frame.GetMenuBar().FindItemById(uimod.ID_PL_ADD)
        compare = frame.onair_item
        labels = [add.GetItemLabel(), compare.GetItemLabel()]
        check("no control character reaches a menu label from a pad's name",
              not any(ord(char) < 32 for text in labels for char in text),
              [repr(text) for text in labels])
        check("so neither label binds a key of its own: no Ctrl+Shift+Z, no "
              "bare 1", add.GetAccel() is None and compare.GetAccel() is None,
              (add.GetAccel(), compare.GetAccel()))
        uses = frame._app_key_uses()
        check("and neither is counted as one of the app's own keys",
              (ord("Z"), CTRL_SHIFT) not in uses
              and (ord("1"), wx.ACCEL_NORMAL) not in uses,
              [uses.get((ord("Z"), CTRL_SHIFT)),
               uses.get((ord("1"), wx.ACCEL_NORMAL))])
        guard("the label still says whose key it is",
              "Alt+Shift+A plays Applause" in add.GetItemLabel(),
              add.GetItemLabel())
        label = frame._button_for(frame.board.bank_slots(C.BANK_MISC)[2]) \
            .GetLabel()
        check("and a pad's own label has spaces where its name had a line "
              "break", chr(13) not in label and chr(10) not in label
              and "Line one  Line two" in label, repr(label))
    finally:
        frame._open_board(START)


section("6", item_6)


# ===========================================================================
heading("8. Delete twice on the track on air")

SONGS = [wav("Song %d" % n, 20.0) for n in (1, 2, 3)]
FIRST_DELETE = "Song 1 is on air. Delete again removes it and stops the music"


def first_on_air(row=0):
    """Three songs, the first on the air, the cursor on `row`."""
    panel = frame.playlist_panel
    frame.stop_playlist(quiet=True)
    frame.board.playlist.clear()
    panel.refresh()
    panel.add_paths(SONGS)
    pump(0.1)
    frame.play_playlist(0)
    pump(0.1)
    frame.show_view(uimod.VIEW_PLAYLIST)
    panel.focus_list()
    pump(0.1)
    panel.select(row)
    pump(0.1)


def delete():
    """Delete, the way the menu bar's accelerator hands it to the frame."""
    return hear(lambda: post(frame, uimod.ID_CLEAR_FOCUSED))


def item_8():
    panel = frame.playlist_panel
    check("the window for the second press is ten seconds",
          getattr(C, "DELETE_ON_AIR_WINDOW_MS", None) == 10000,
          getattr(C, "DELETE_ON_AIR_WINDOW_MS", None))
    first_on_air()
    guard("the playlist is playing its first track",
          frame.player.playing and frame.player.index == 0)
    said = delete()
    check("the first press says exactly what the second one does",
          said == [FIRST_DELETE], said)
    armed = getattr(panel, "_armed", None)
    guard("and waits for the second press", armed is not None)
    if armed is not None:
        # The first press, six seconds ago: inside ten, outside five.
        panel._armed = (armed[0], time.monotonic() - 6.0)
    said = delete()
    check("a second press six seconds later still removes it",
          len(frame.board.playlist) == 2 and not frame.player.playing
          and said == ["Removed Song 1. The playlist has stopped"],
          (said, len(frame.board.playlist)))

    first_on_air()
    delete()
    frame.player.next()
    pump(0.1)
    guard("the next song comes on between the two presses, the cursor "
          "still on the first", frame.player.playing
          and frame.player.index == 1 and panel.selection() == 0,
          (frame.player.index, panel.selection()))
    said = delete()
    guard("the second press still takes out the track it was about",
          [t.display_name for t in frame.board.playlist]
          == ["Song 2", "Song 3"],
          [t.display_name for t in frame.board.playlist])
    check("and says so at the essential level, with the playlist carrying on",
          said == ["Removed Song 1. The playlist carries on"], said)
    guard("the music did not stop", frame.player.playing
          and frame.player.current is not None
          and frame.player.current.display_name == "Song 2")
    frame.stop_playlist(quiet=True)
    frame.board.playlist.clear()
    panel.refresh()
    frame.show_view(uimod.VIEW_BOARD)


section("8", item_8)


# ===========================================================================
heading("9. A compare left bypassed is said, in three places")

BYPASSED = "On air sound is bypassed. Alt+Shift+P puts it back"
HINT = ("To hear the difference, record a minute with Ctrl+R, or send the "
        "show with Alt+Shift+O and press Ctrl+Shift+H")


def recorded_peak(bypassed):
    """A tone at full scale through a real recording, and its peak in dB."""
    frame._onair_bypassed = bypassed
    frame._apply_onair()
    frame.start_recording()
    rec = frame.recorder
    t = np.arange(RATE) / RATE
    tone = (0.98 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    frame.record_bus.write("final check", np.repeat(tone[:, None], CHANNELS,
                                                     axis=1))
    end = time.monotonic() + 5.0
    while rec.frames_written < RATE // 2 and time.monotonic() < end:
        time.sleep(0.05)
    path = frame.stop_recording(quiet=True)
    data, _rate = sf.read(path, dtype="float32")
    return 20.0 * np.log10(max(1e-9, float(np.abs(data).max())))


def item_9():
    radio(frame.board)
    frame.board.onair_on = True
    frame.board.onair_even = "gentle"
    frame.board.onair_ceiling_db = -2.0
    frame._onair_bypassed = False
    frame._apply_onair()
    said = hear(lambda: post(frame, uimod.ID_ONAIR_COMPARE))
    guard("Alt+Shift+P bypasses the on air sound, and says so",
          frame._onair_bypassed
          and said == ["On air sound bypassed, in what goes out"], said)
    warnings = [note.text for note in frame.preflight().warnings]
    check("the go live summary warns that it is bypassed, and how to put "
          "it back", BYPASSED in warnings, warnings)
    answer = hear(lambda: post(frame, uimod.ID_STREAM_STATUS))
    check("Ctrl+Shift+B says so after its answer",
          bool(answer) and answer[-1].endswith(BYPASSED), answer)
    bar = native_field(frame.status, 0)
    check("and the status bar says it", "ON AIR SOUND BYPASSED (Alt+Shift+P)"
          in bar, bar)
    hear(lambda: post(frame, uimod.ID_ONAIR_COMPARE))
    guard("pressed again, it is back on", not frame._onair_bypassed)
    warnings = [note.text for note in frame.preflight().warnings]
    guard("and none of the three says bypassed any more",
          BYPASSED not in warnings
          and "BYPASSED" not in native_field(frame.status, 0)
          and "bypassed" not in frame.stream_status(),
          (warnings, native_field(frame.status, 0)))

    # The hint, once a session at the level that says hints.
    frame._told_compare_ear = False
    frame.board.speech_level = C.SPEECH_ALL
    frame._menu_closed_at = None
    ear.said.clear()
    post(frame, uimod.ID_ONAIR_COMPARE)
    first = list(ear.said)
    check("the first bypass says where to hear the difference, a recording "
          "first", first == [("On air sound bypassed, in what goes out",
                              True), (HINT, False)], first)
    post(frame, uimod.ID_ONAIR_COMPARE)
    frame.board.speech_level = ESSENTIAL

    # And what the hint promises: a recording carries the on air sound.
    folder = tempfile.mkdtemp(prefix="dropdeck-final-rec-")
    frame.board.record_folder = folder
    frame.board.record_format = "wav"
    try:
        held = recorded_peak(False)
        free = recorded_peak(True)
    finally:
        frame._onair_bypassed = False
        frame._apply_onair()
        frame.board.record_folder = ""
    guard("a recording carries the on air sound: a tone at full scale goes "
          "into the file under its ceiling", held <= -1.0, "%.2f dB" % held)
    guard("and the compare reaches the file: bypassed, it goes in as it "
          "came", free >= -0.5, "%.2f dB" % free)

    # A pad that kept Alt+Shift+P: the key is not named, its menu is.
    board = Board()
    misc = board.bank_slots(C.BANK_MISC)
    misc[0].filepath = wav("Horn", 0.5)
    misc[0].custom_hotkey = "Alt+Shift+P"
    misc[0].key_code, misc[0].modifiers = ord("P"), ALT_SHIFT
    radio(board)
    board.onair_on = True
    path = os.path.join(TMP, "Pad keeps P.json")
    board.save(path)
    frame._open_board(path)
    try:
        post(frame, uimod.ID_ONAIR_COMPARE)
        warnings = [note.text for note in frame.preflight().warnings]
        check("with a pad on Alt+Shift+P, the warning names the menu item, "
              "not a key that plays the pad",
              "On air sound is bypassed. Quick compare, on the On air menu, "
              "puts it back" in warnings, warnings)
        check("and so does the status bar",
              "ON AIR SOUND BYPASSED (On air menu)"
              in native_field(frame.status, 0), native_field(frame.status, 0))
    finally:
        frame._onair_bypassed = False
        frame._apply_onair()
        frame._open_board(START)
        frame._update_status()


section("9", item_9)


# ===========================================================================
heading("10. Global hotkeys that are not used: one sentence a reason")


def item_10():
    board = Board()
    for number, slot in enumerate(board.bank_slots(C.BANK_SFX)[:3], 1):
        slot.filepath = wav("Sting %d" % number, 0.5)
        slot.global_hotkey = "Ctrl+Alt+%d" % number
    fourth = board.bank_slots(C.BANK_SFX)[3]
    fourth.filepath = wav("Sting 4", 0.5)
    fourth.global_hotkey = "Ctrl+V"
    board.global_hotkeys_on = True
    path = os.path.join(TMP, "Refused hotkeys.json")
    board.save(path)
    said = " ".join(hear(lambda: frame._open_board(path)))
    altgr = ("Ctrl+Alt+1, 2 and 3, on SFX 1 to 3, are not used: Windows "
             "reads Ctrl+Alt as AltGr. Alt+Enter on a pad changes it")
    paste = ("Ctrl+V on SFX 4 is not used: it is paste in nearly every "
             "program. Alt+Enter on that pad changes it")
    check("three pads refused for one reason make one sentence, their keys "
          "and pads run together", altgr in said, said)
    check("and a pad refused for a reason of its own one more", paste in said,
          said)
    check("each reason said once", said.count("AltGr") == 1
          and said.count("is paste") == 1, said)
    guard("and none of them is offered to Windows",
          frame.hotkeys.bindings == {}, frame.hotkeys.bindings)
    frame._open_board(START)


section("10", item_10)


# ===========================================================================
heading("12. The microphone channel: mix is the plain average again")


def channel_of(value, drop=False):
    path = os.path.join(TMP, "Channel.json")
    Board().save(path)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if drop:
        data.pop("mic_channel", None)
    else:
        data["mic_channel"] = value
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return Board.load(path).mic_channel


def choose(label):
    def script(dialog):
        names = [dialog.mic_channel.GetString(n)
                 for n in range(dialog.mic_channel.GetCount())]
        if label not in names:
            return wx.ID_CANCEL
        dialog.mic_channel.SetSelection(names.index(label))
        return wx.ID_OK
    return script


def voice_and_hiss(seconds=3.0):
    """A voice on input 1 and a preamp's hiss on input 2, in blocks."""
    rnd = np.random.default_rng(12)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    pair = np.zeros((n, 2), np.float32)
    pair[:, 0] = 0.1 * np.sin(2 * np.pi * 220.0 * t)
    pair[:, 1] = rnd.standard_normal(n) * 10 ** (-70 / 20.0)
    return [np.ascontiguousarray(pair[at:at + BLOCK])
            for at in range(0, n, BLOCK)]


def on_air_output(channel, blocks):
    """What a microphone set to `channel` puts on the air, block by block,
    through its own callback. Opens nothing."""
    mic = MicInput(duck_bus=None, samplerate=RATE)
    mic.samplerate = RATE
    mic.stream = object()
    mic.channels_open = 2
    mic._reset_ring()
    mic.channel = channel
    mic.chain = None
    mic.on_air = True
    mic.monitor = False
    out = []
    for block in blocks:
        mic._callback(block, len(block), None, None)
        with mic._lock:
            out.append(mic._air._take(mic._air.available))
    return np.concatenate(out), mic


def item_12():
    check("Which channel offers the side with a voice on it, then always "
          "mixed, then each side, keyed voice and mix",
          tuple(C.MIC_CHANNELS) == (
              ("voice", "Both, the side with a voice on it"),
              ("mix", "Both, always mixed"),
              ("left", "Left only"), ("right", "Right only")),
          C.MIC_CHANNELS)
    check("a new board, as File, New and a first start make one, is voice",
          Board().mic_channel == "voice", Board().mic_channel)
    check("the demo pack, a new board to whoever opens it, is voice",
          Board.load(boardmod.demo_board_path()).mic_channel == "voice",
          Board.load(boardmod.demo_board_path()).mic_channel)
    guard("a board saved with mix keeps mix", channel_of("mix") == "mix")
    check("the unreleased average reads as mix, the same thing",
          channel_of("average") == "mix", channel_of("average"))
    guard("a board from before there was a choice is the plain average, as "
          "3.10.1 opened it", channel_of(None, drop=True) == "mix",
          channel_of(None, drop=True))
    guard("left and right as they were", channel_of("left") == "left"
          and channel_of("right") == "right")

    preferences(choose("Both, always mixed"))
    check("Both, always mixed on the Microphone page saves mix, onto the "
          "board and the microphone",
          frame.board.mic_channel == "mix" and frame.mic.channel == "mix",
          (frame.board.mic_channel, frame.mic.channel))
    preferences(choose("Both, the side with a voice on it"))
    check("and the side with a voice on it saves voice",
          frame.board.mic_channel == "voice" and frame.mic.channel == "voice",
          (frame.board.mic_channel, frame.mic.channel))

    old = os.path.join(TMP, "Saved by 3.10.1.json")
    Board().save(old)
    with open(old, encoding="utf-8") as handle:
        data = json.load(handle)
    data["mic_channel"] = "mix"
    with open(old, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    frame._open_board(old)
    guard("opening it puts its channel on the microphone",
          frame.mic.channel == "mix", frame.mic.channel)
    frame._open_board(START)
    blocks = voice_and_hiss()
    got, mic = on_air_output(Board.load(old).mic_channel, blocks)
    want = np.concatenate([np.repeat((block[:, :2].mean(axis=1)
                                      * mic.gain)[:, None], CHANNELS, axis=1)
                           for block in blocks])
    check("an old board's mix sends exactly the plain average of the two "
          "sides, bit for bit, as 3.10.1 did",
          got.shape == want.shape and np.array_equal(got, want),
          (got.shape, want.shape, float(np.abs(got - want).max())
           if got.shape == want.shape else None))
    _got, mic = on_air_output("voice", blocks)
    guard("and voice still takes the talking side alone after a second",
          tuple(round(float(w), 6) for w in mic._side_weights) == (1.0, 0.0),
          mic._side_weights)


section("12", item_12)


# ===========================================================================
heading("13. F1")

CEILING = ("Ordinary music stays under it with Even out the music on Gentle "
           "or Firm; with it Off, or with hard material such as noise, the "
           "loudest moments can still come out up to about a decibel over.")


def help_headings(text):
    found = []
    for at, line in enumerate(text.splitlines()):
        if at and line and not line.startswith(" ") and re.match(
                r"^[A-Z0-9][A-Z0-9 ,]+(?::|$)", line):
            found.append(line.split(":")[0])
    return found


def heading_over(text, phrase):
    """The heading of the F1 section a phrase is in."""
    at = text.index(phrase)
    above = text[:at].splitlines()
    for line in reversed(above):
        if line and not line.startswith(" ") and re.match(
                r"^[A-Z0-9][A-Z0-9 ,]+(?::|$)", line):
            return line.split(":")[0]
    return None


def item_13():
    text = C.KEYBOARD_HELP
    words = flat(text)
    heads = help_headings(text)
    check("the Voice list's bigger step is Shift with Left or Right, which "
          "is what the list does",
          "Hold Shift with Left or Right for a bigger step" in words
          and "Page up and page down move in bigger steps" not in words)
    check("GLOBAL comes straight after PER BUTTON",
          "PER BUTTON" in heads and heads.index("PER BUTTON") + 1
          < len(heads) and heads[heads.index("PER BUTTON") + 1] == "GLOBAL",
          heads[:6])
    check("recording is one section, said once",
          heads.count("RECORDING THE SHOW") == 1
          and "RECORDING THE PICTURE AS WELL AS THE SOUND" not in heads
          and words.count("Drop Deck Stream 001") == 1
          and words.count("Hand the pair to Mixcloud") == 1
          and words.count("Closing the app finishes the file first") == 1,
          heads)
    check("and so is sending the show to another program",
          not any(head.startswith("FEEDING") for head in heads)
          and "GIVING ANOTHER PROGRAM ON THIS MACHINE YOUR SHOW" in heads
          and words.count("It can leave one source out") == 1
          and words.count("Do NOT point Preferences, Output at a cable") == 1,
          heads)
    check("no right-click anywhere in F1, only the Applications key",
          "right-click" not in text.lower() and "right click"
          not in text.lower(),
          [line for line in text.splitlines() if "ight" in line
           and "click" in line])
    check("no spaced hyphen used as a dash",
          [line for line in text.splitlines()
           if " - " in line and "Artist - Title" not in line] == [],
          [line for line in text.splitlines()
           if " - " in line and "Artist - Title" not in line])
    check("the paragraph about cues is under THE PLAYLIST",
          heading_over(text, "Each song hands over to the next before it "
                             "ends") == "THE PLAYLIST",
          heading_over(text, "Each song hands over to the next before it "
                             "ends"))
    check("the compare's hint in F1 is the new one", HINT in words,
          words[words.find("ON AIR SOUND"):][:500])
    check("and the ceiling is said as it was measured", CEILING in words
          and "kept under a ceiling" not in words,
          words[words.find("ON AIR SOUND"):][:500])


section("13", item_13)


# ===========================================================================
heading("15. The labels a pad's key reaches follow the pad")


def item_15():
    board = Board()
    misc = board.bank_slots(C.BANK_MISC)
    misc[0].filepath = wav("Applause", 0.5)
    misc[0].name = "Applause"
    misc[0].custom_hotkey = "Alt+Shift+A"
    misc[0].key_code, misc[0].modifiers = ord("A"), ALT_SHIFT
    path = os.path.join(TMP, "Pad keeps A.json")
    board.save(path)
    frame._open_board(path)
    slot = frame.board.bank_slots(C.BANK_MISC)[0]
    item = frame.GetMenuBar().FindItemById(uimod.ID_PL_ADD)

    def entries_for_a():
        return [entry.GetCommand() for entry in frame._accelerators
                if (entry.GetFlags(), entry.GetKeyCode())
                == (ALT_SHIFT, ord("A"))]

    try:
        guard("the label says whose key it is",
              item.GetItemLabel() == "&Add songs to the end... Alt+Shift+A "
                                     "plays Applause", item.GetItemLabel())
        real_ask = uimod.ask_text
        uimod.ask_text = lambda *a, **kw: FakeText("Laughter")
        try:
            frame.rename_slot(slot)
        finally:
            uimod.ask_text = real_ask
        check("renamed, it names the pad by its new name",
              item.GetItemLabel() == "&Add songs to the end... Alt+Shift+A "
                                     "plays Laughter", item.GetItemLabel())
        ANSWERS[:] = [wx.YES]
        frame.clear_slot(slot)
        ANSWERS[:] = []
        check("cleared, it says the pad keeps the key and is empty",
              item.GetItemLabel() == "&Add songs to the end... Alt+Shift+A "
                                     "is kept by Misc 1, which is empty",
              item.GetItemLabel())
        frame.remove_slot(slot)
        check("taken off the board, the pad holds no key: Add songs has it "
              "back, on the menu and in the table, once",
              item.GetItemLabel() == "&Add songs to the end..." + chr(9)
              + "Alt+Shift+A" and entries_for_a() == [uimod.ID_PL_ADD],
              (item.GetItemLabel(), entries_for_a()))
        frame._restore(slot)
        check("put back, the pad holds it again",
              item.GetItemLabel() == "&Add songs to the end... Alt+Shift+A "
                                     "is kept by Misc 1, which is empty"
              and entries_for_a() == [uimod.ID_SLOT_BASE + slot.index],
              (item.GetItemLabel(), entries_for_a()))
    finally:
        ANSWERS[:] = []
        frame._open_board(START)


section("15", item_15)


# ===========================================================================
heading("17. An album from a board file is text or nothing")


def item_17():
    def album_of(value):
        return Track.from_dict({"filepath": "dq.flac", "artist": "Abba",
                                "title": "Dancing Queen",
                                "album": value}).album

    odd = [value for value in ({"a": 1}, 5, ["Arrival"], True, 2.5)
           if album_of(value) is not None]
    check("an album that is not text is dropped, so the tags are read again",
          not odd, odd)
    guard("an album that is text is kept", album_of("Arrival") == "Arrival")
    track = Track.from_dict({"filepath": "dq.flac", "artist": "Abba",
                             "title": "Dancing Queen", "album": {"a": 1}})
    sent = playlistmod.station_title(track, C.ARTIST_TITLE_ALBUM)
    check("so a station is never sent a dict's braces as the album",
          sent == "Abba - Dancing Queen", sent)


section("17", item_17)


# ===========================================================================
heading("18. Delete, not Del, on the menus")

POPPED = []


def capture_popup(self, menu, *args, **kw):
    POPPED.append([item.GetItemLabel() for item in menu.GetMenuItems()
                   if not item.IsSeparator()])
    return True


def capture_rows(self, menu, *args, **kw):
    POPPED.append([(item.GetItemLabel(), item.GetId())
                   for item in menu.GetMenuItems() if not item.IsSeparator()])
    return True


def item_18():
    bar = frame.GetMenuBar()
    clear = bar.FindItemById(uimod.ID_CLEAR_FOCUSED).GetItemLabel()
    remove = bar.FindItemById(uimod.ID_REMOVE_SLOT).GetItemLabel()
    check("the Sounds menu writes Delete and Shift+Delete, which NVDA reads "
          "as words", clear.endswith(chr(9) + "Delete")
          and remove.endswith(chr(9) + "Shift+Delete"), (clear, remove))

    slot = frame.board[0]
    slot.filepath = wav("Pad sound", 0.5)
    button = frame._button_for(slot)
    own = uimod.SoundButton.__dict__.get("PopupMenu")
    uimod.SoundButton.PopupMenu = capture_popup
    POPPED.clear()
    try:
        frame.show_slot_menu(slot, button)
    finally:
        if own is None:
            del uimod.SoundButton.PopupMenu
        else:
            uimod.SoundButton.PopupMenu = own
        slot.filepath = None
    labels = POPPED[0] if POPPED else []
    check("so does a pad's own menu",
          any(label.endswith(chr(9) + "Shift+Delete") for label in labels)
          and not any(label.endswith("Del") for label in labels), labels)

    panel = frame.playlist_panel
    frame.board.playlist.clear()
    panel.refresh()
    panel.add_paths([wav("A row", 1.0)])
    frame.show_view(uimod.VIEW_PLAYLIST)
    panel.focus_list()
    panel.select(0)
    pump(0.1)
    real = wx.ListCtrl.__dict__.get("PopupMenu")
    wx.ListCtrl.PopupMenu = capture_rows
    POPPED.clear()
    try:
        event = wx.ContextMenuEvent(wx.wxEVT_CONTEXT_MENU, panel.list.GetId())
        event.SetEventObject(panel.list)
        panel.list.GetEventHandler().ProcessEvent(event)
    finally:
        if real is None:
            del wx.ListCtrl.PopupMenu
        else:
            wx.ListCtrl.PopupMenu = real
    rows = POPPED[0] if POPPED else []
    check("and the running order's row menu",
          [label for label, command in rows if command == ID_PL_ROW_REMOVE]
          == ["Re&move from the running order" + chr(9) + "Delete"], rows)
    frame.board.playlist.clear()
    panel.refresh()
    frame.show_view(uimod.VIEW_BOARD)
    keys = frame._app_keys()
    check("and Shift+Delete is one of the keys the startup line asks "
          "Windows about",
          any(vk == 0x2E and (mods & 0x000F) == globalhotkeys.MOD_SHIFT
              for _label, mods, vk in keys),
          [label for label, _m, _v in keys if "Del" in label])


section("18", item_18)


# ===========================================================================
heading("19. Today's names")


def item_19():
    frame.send = FakeSend()
    frame._sync_air_taps()
    try:
        said = hear(lambda: post(frame, uimod.ID_SEND_MONITOR))
        check("hearing the send names What I listen on, not a monitor output",
              any("What I listen on" in text for text in said)
              and not any("monitor output" in text for text in said), said)
        hear(lambda: post(frame, uimod.ID_SEND_MONITOR))
    finally:
        frame.send = None
        frame._sync_air_taps()
    help_text = frame.GetMenuBar().FindItemById(uimod.ID_SEND_MONITOR) \
        .GetHelp()
    check("and so does that menu item's help",
          "What I listen on" in help_text and "monitor output" not in help_text,
          help_text)
    words = streamstats._explain(["the server did not answer"],
                                 {"server": "icecast"})
    check("no statistics from the server sends you to the Audio streaming "
          "page, not a Streaming tab",
          "Audio streaming page" in words and "Streaming tab" not in words,
          words)
    box = dialogs.SourcesDialog(frame, [])
    try:
        tip = box.monitor.GetToolTipText()
    finally:
        box.Destroy()
    check("and a source's Hear it yourself comes back on What I listen on",
          "What I listen on" in tip and "monitor output" not in tip, tip)


section("19", item_19)


# ===========================================================================
heading("20. The ceiling says what was measured")


def item_20():
    prefs = real_preferences(S.PAGE_ONAIR)
    try:
        tip = flat(prefs.onair_ceiling.GetToolTipText())
        check("Never louder than's tooltip says ordinary music stays under, "
              "and how far over the rest can come out",
              CEILING in tip and "The loudest any moment" not in tip, tip)
        guard("and keeps the reason Firm starts at minus three",
              "Firm starts at minus three" in tip, tip)
        tip = flat(prefs.onair_on.GetToolTipText())
        check("the on air sound box no longer promises every peak under the "
              "ceiling", "keeps every peak under" not in tip, tip)
    finally:
        prefs.Destroy()


section("20", item_20)


# ===========================================================================
heading("21. The send's cost, as Jackson measured it")


def item_21():
    doc = flat(streamout.on_air_sound.__doc__)
    check("a median of 0.61 ms and a worst of 1.19 ms at 48 kHz, not 0.2 ms",
          "median of 0.61 ms and a worst of 1.19 ms" in doc
          and "48 kHz" in doc and "0.2 ms" not in doc, doc)


section("21", item_21)


# ===========================================================================
heading("22. The cable's sample rate steps go where the tabs are")


def item_22():
    found = [EP.Endpoint(EP.RENDER, "CABLE Input", "VB-Audio Virtual Cable",
                         48000, 24, 2),
             EP.Endpoint(EP.CAPTURE, "CABLE Output", "VB-Audio Virtual Cable",
                         192000, 16, 2)]
    said = EP.mismatch_for(found[0].full_name, found)
    check("Windows and R, then mmsys.cpl, which has the Playback and "
          "Recording tabs, and not Sound settings, which has neither",
          "mmsys.cpl" in said and "Sound settings" not in said, said)
    check("naming each end on its own tab",
          "CABLE Input on the Playback tab" in said
          and "CABLE Output on the Recording tab" in said, said)
    guard("and saying that it works as it is", "works as it is" in said,
          said)


section("22", item_22)


# ===========================================================================
heading("23. The streaming help: YouTube's sentence under YouTube only")


def item_23():
    sentence = "YouTube will not take sound on its own"
    check("said under YouTube, and under no other platform",
          sentence in streamhelp.as_text("youtube")
          and not any(sentence in streamhelp.as_text(platform)
                      for platform in ("facebook", "restream", "rtmp"))
          and streamhelp.everything().count(sentence) == 1)
    shouted = sorted(set(word for word in re.findall(
        r"\b[A-Z]{2,}\b", streamhelp.everything())
        if word not in ("OK", "RTMP", "RTMPS", "OBS")))
    check("and nothing in it is in capitals for emphasis", not shouted,
          shouted)


section("23", item_23)


# ===========================================================================
heading("4. A save only the background pass asked for fails in silence")


def board_from_3_10_1(name):
    """A board as 3.10.1 saved it, with a running order: no album at all."""
    board = Board()
    board.playlist.add([wav(name + " one", 3.0, 0.2),
                        wav(name + " two", 3.0, 0.2)])
    data = board.to_dict()
    for track in data["playlist"]["tracks"]:
        track.pop("album", None)
        track["artist"], track["title"] = "Abba", "Dancing Queen"
        track["tail_silence"] = 0.0
    data["match_loudness"] = False
    path = os.path.join(TMP, name + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return path


def item_4():
    kept = board_from_3_10_1("Finished show")
    os.chmod(kept, stat.S_IREAD)
    try:
        made, heard = starting(kept)
        try:
            guard("its pass reads the albums 3.10.1 never stored",
                  wait_for_pass(made, 20.0)
                  and [t.album for t in made.board.playlist] == ["", ""],
                  [t.album for t in made.board.playlist])
            guard("and the start was heard, so silence below means something",
                  any(text.startswith("TG Drop Deck ready")
                      for text in heard.texts), heard.texts)
            check("a read only board says nothing about not being saved when "
                  "nobody changed it",
                  not any("could not be saved" in text
                          for text in heard.texts)
                  and "could not be saved" not in made.status.GetStatusText(1),
                  heard.texts)
            check("and is left as it was, unchanged", not made.board.dirty)
        finally:
            close_frame(made)
    finally:
        os.chmod(kept, stat.S_IREAD | stat.S_IWRITE)
    open_one = board_from_3_10_1("Open show")
    made, _heard = starting(open_one)
    try:
        wait_for_pass(made, 20.0)
        with open(open_one, encoding="utf-8") as handle:
            albums = [t.get("album") for t in
                      json.load(handle)["playlist"]["tracks"]]
        guard("one that can be written keeps what the pass found",
              albums == ["", ""] and not made.board.dirty, albums)
    finally:
        close_frame(made)
    boardmod.remember_board_path(START)


section("4", item_4)


# ===========================================================================
heading("11. The first start note")

NOTICE = ("New in this version: On air sound, which evens out the music your "
          "listeners get, is not switched on for this board yet. Put the "
          "microphone on air is now Send my microphone, on the Microphone "
          "page")


def item_11():
    path = make_board("Old show")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for key in ("onair_on", "match_loudness", "onair_even",
                "onair_ceiling_db", "never_named"):
        data.pop(key, None)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    state = boardmod.machine_state()
    state.pop("told_onair_and_mic_moved", None)
    boardmod.save_machine_state(state)
    made, heard = starting(path)
    try:
        guard("the board it opened has On air sound off, as an update's does",
              made.board.onair_on is False)
        check("the first start of this version says what changed, in the "
              "final words, queued behind the startup line",
              (NOTICE, False) in heard.said, heard.said)
    finally:
        close_frame(made)
        boardmod.remember_board_path(START)


section("11", item_11)


# ===========================================================================
heading("14. The record folder note, once a session")

FOLDER_NOTE = "This board records to a folder this computer does not use"


def item_14():
    path = make_board("Records to the NAS",
                      record_folder=r"\\nas\shows\drop deck")
    state_file = os.path.join(boardmod.config_dir(), boardmod.MACHINE_FILE)
    boardmod.save_machine_state(boardmod.machine_state())
    os.chmod(state_file, stat.S_IREAD)
    try:
        guard("this computer.json cannot be written",
              not boardmod.save_machine_state({"x": 1}))
        made, heard = starting(path)
        try:
            guard("the first start says it",
                  FOLDER_NOTE in " ".join(heard.texts), heard.texts)
            heard.said.clear()
            made._open_board(path)
            pump(0.2)
            check("opening the board again in the same session does not say "
                  "it again", FOLDER_NOTE not in " ".join(heard.texts),
                  heard.texts)
        finally:
            close_frame(made)
        made, heard = starting(path)
        try:
            guard("the next start says it once more, since nothing could "
                  "write down that it was said",
                  FOLDER_NOTE in " ".join(heard.texts), heard.texts)
        finally:
            close_frame(made)
    finally:
        os.chmod(state_file, stat.S_IREAD | stat.S_IWRITE)
        boardmod.remember_board_path(START)


section("14", item_14)


# ===========================================================================
heading("16. The leftover home after Save as")


def item_16():
    import _winapi
    real = wx.FileDialog
    wx.FileDialog = FakeFileDialog
    alias = os.path.join(TMP, "The settings folder by another name")
    try:
        first, _heard = starting(START)
        try:
            post(first, wx.ID_NEW)
            pump(0.1)
            home = first.board.path
            first.board[0].filepath = wav("Kept", 0.5)
            first._touch()
            first._save(quiet=True)
            with open(home, encoding="utf-8") as handle:
                guard("File, New's board is in a home of its own in the "
                      "settings folder, and says it was never named",
                      boardmod.same_path(os.path.dirname(home),
                                         boardmod.config_dir())
                      and json.load(handle).get("never_named") is True)
        finally:
            close_frame(first)
        after, _heard = starting(home)
        try:
            guard("after a restart that home opens, still never named",
                  same_path(after.board.path, home)
                  and after.board.never_named is True)
            named = os.path.join(TMP, "Named after a restart.json")
            FakeFileDialog.opened.clear()
            FakeFileDialog.answer[0] = named
            post(after, wx.ID_SAVE)
            pump(0.2)
            guard("Ctrl+S asks for a name and saves it there",
                  len(FakeFileDialog.opened) == 1 and os.path.exists(named))
            check("and the home it was kept in goes, now it has a name",
                  not os.path.exists(home), settings_files())

            post(after, wx.ID_NEW)
            pump(0.1)
            home2 = after.board.path
            after.board[0].filepath = wav("Kept too", 0.5)
            after._touch()
            after._save(quiet=True)
            _winapi.CreateJunction(boardmod.config_dir(), alias)
            via = os.path.join(alias, os.path.basename(home2))
            guard("the same file by two names, through a junction",
                  os.path.exists(via) and os.path.samefile(via, home2))
            FakeFileDialog.answer[0] = via
            post(after, wx.ID_SAVE)
            pump(0.2)
            check("Save as onto that same file by its other name keeps the "
                  "file it has just written",
                  os.path.exists(home2) and os.path.exists(via),
                  settings_files())
            check("and that file is the board that opens next time",
                  os.path.exists(boardmod.remembered_board_path() or ""),
                  boardmod.remembered_board_path())
        finally:
            close_frame(after)
    finally:
        wx.FileDialog = real
        FakeFileDialog.answer[0] = None
        if os.path.isdir(alias):
            os.rmdir(alias)              # the junction, never what it names
        boardmod.remember_board_path(START)


section("16", item_16)


# ===========================================================================
heading("7. tools/check_guide.py reaches nothing outside its own process")

GUIDE_HARNESS = r'''
import ctypes, json, os, runpy, socket, sys, tempfile, threading
ROOT = os.environ["DD_ROOT"]
RECORD = os.environ["DD_GUIDE_RECORD"]
base = tempfile.mkdtemp(prefix="dropdeck-final-guide-")
os.environ["APPDATA"] = os.path.join(base, "appdata")
os.environ["TGDROPDECK_DATA"] = os.path.join(base, "data")
for folder in (os.environ["APPDATA"], os.environ["TGDROPDECK_DATA"]):
    os.makedirs(folder, exist_ok=True)
seen = {"credentials": [], "streams": [], "threads": [], "loads": [],
        "net": []}


def no_net(*args, **kw):
    seen["net"].append(repr(args)[:80])
    raise OSError("no network while checking the guide")


socket.create_connection = no_net
socket.getaddrinfo = no_net
socket.socket.connect = lambda self, *a, **kw: no_net(*a)
socket.socket.connect_ex = lambda self, *a, **kw: no_net(*a)

started = threading.Thread.start


def start(self):
    seen["threads"].append(self.name)
    return started(self)


threading.Thread.start = start

import sounddevice as sd


class Stream:
    def __init__(self, *args, **kw):
        seen["streams"].append(str(kw.get("device")))
        self.active = False
        self.latency = 0.02
        self.samplerate = kw.get("samplerate") or 48000
        self.blocksize = kw.get("blocksize") or 0
        self.channels = kw.get("channels") or 2

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def abort(self):
        self.active = False

    def close(self):
        self.active = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


for name in ("OutputStream", "InputStream", "Stream", "RawOutputStream",
             "RawInputStream", "RawStream"):
    setattr(sd, name, Stream)

sys.path.insert(0, ROOT)
from dropdeck import secrets, vst


class Asked:
    def __init__(self, name):
        self.name = name

    def __call__(self, *args):
        seen["credentials"].append(self.name)
        return 0


class Advapi:
    """advapi32, with every Credential Manager call watched and answered
    with nothing found, so none reaches Windows."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        if name.startswith("Cred"):
            asked = Asked(name)
            object.__setattr__(self, name, asked)
            return asked
        return getattr(self._real, name)


real_dll = ctypes.WinDLL
secrets._advapi = lambda: Advapi(real_dll("advapi32", use_last_error=True))
vst.installed = lambda: [("A plugin", os.path.join(base, "A plugin.vst3"))]


def load(path, *args, **kw):
    seen["loads"].append(os.path.basename(path))
    raise vst.LoadFailed("not loaded while checking the guide")


vst.load = load
guide = os.path.join(base, "guide.md")
with open(guide, "w", encoding="utf-8") as handle:
    handle.write("# A guide\n\nSet it to minus one. Press `Ctrl+B`.\n")
script = os.path.join(ROOT, "tools", "check_guide.py")
sys.argv = [script, guide] + sys.argv[1:]
code = None
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    code = exc.code
except BaseException as exc:
    seen["raised"] = repr(exc)
seen["exit"] = code
with open(RECORD, "w", encoding="utf-8") as handle:
    json.dump(seen, handle)
os._exit(0)
'''


def guide_check(*flags):
    """tools/check_guide.py in a child, and what it reached for."""
    harness = os.path.join(TMP, "guide_harness.py")
    with open(harness, "w", encoding="utf-8") as handle:
        handle.write(GUIDE_HARNESS)
    record = os.path.join(TMP, "guide%s.json" % ("-".join(flags)))
    if os.path.exists(record):
        os.remove(record)
    env = dict(os.environ, DD_ROOT=ROOT, DD_GUIDE_RECORD=record)
    done = subprocess.run([sys.executable, "-u", harness] + list(flags),
                          cwd=TMP, env=env, capture_output=True, text=True,
                          timeout=240)
    if not os.path.exists(record):
        return {}, (done.stdout + done.stderr)[-800:]
    with open(record, encoding="utf-8") as handle:
        return json.load(handle), (done.stdout + done.stderr)[-800:]


def item_7():
    seen, tail = guide_check()
    guard("it ran through to its report", "exit" in seen
          and "raised" not in seen, (seen.get("raised"), tail))
    check("it reads no credential from Windows' Credential Manager",
          seen.get("credentials") == [], seen.get("credentials"))
    check("it opens no sound card", seen.get("streams") == [],
          seen.get("streams"))
    check("it checks for no update, so it goes nowhere on the network",
          "dropdeck-update" not in (seen.get("threads") or ["dropdeck-update"])
          and seen.get("net") == [], (seen.get("threads"), seen.get("net")))
    check("and it loads no plugin unless asked to", seen.get("loads") == [],
          seen.get("loads"))
    flagged, tail = guide_check("--with-plugins")
    guard("with --with-plugins it still asks the loader about each one, to "
          "find an instrument", flagged.get("loads") == ["A plugin.vst3"],
          (flagged.get("loads"), tail))
    check("and even then reaches nothing else",
          flagged.get("credentials") == [] and flagged.get("streams") == []
          and "dropdeck-update" not in (flagged.get("threads")
                                        or ["dropdeck-update"]),
          flagged)


section("7", item_7)


# ---------------------------------------------------------------------------
try:
    mic_off()
    frame.stop_background_work()
except Exception:
    pass
try:
    frame.mixer.close()
except Exception:
    pass
frame.board.dirty = False
frame.Destroy()
faulthandler.cancel_dump_traceback_later()

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
print("%d/%d guards passed" % (sum(GUARDS), len(GUARDS)))
if FAILED:
    print("FAILED:")
    for line in FAILED:
        print("  " + line)
sys.exit(1 if FAILED else 0)
