"""Review of 24 November 2026, the polish: what Jessica (accessibility) and
Ryder (the user's side) found in the major release.

    python tools/run_private.py tests/test_review_polish.py

Every `check` here fails on 6fa5dad and passes on the fix. A `guard` is a
thing that was already right and has to stay right (a key that was already
the right key, a line that was already short, a known good rename that
proves the listening works); guards pass on both and are counted on a line
of their own. Item 3, Delete on the track on the air, is checked in
tests/test_review_speech.py, in place of the checks for the box it replaced.

  1. the status bar reaches the screen reader whole, both fields;
  2. Ctrl+M says first when the microphone opens and nobody else hears it,
     and why, decided by the predicate the air taps use;
  4. on a track's menu R inserts a random drop again and M removes;
  5. Put it right on the microphone warning lands on Send my microphone;
  6. a saved station that changes Send my microphone says so and makes it
     so, and Audio streaming says where the box went;
  7. the label of a command whose key a pad keeps, and the empty pad's note;
  8. the compare says where it is heard, and once where to listen;
  9. Ctrl+S on a board never named, after a restart and on a first run;
 10. three labels that were only in tooltips;
 11. a disabled control's label is disabled with it;
 12. Preferences waits for the window coming back before it speaks;
 13. Both, always mixed;
 14. By how much further, in decibels, as the edit box reads it;
 15. the Stop everything button is not renamed with the same words;
 16. Firm says the ceiling it moved;
 17. Hear my own voice there;
 18. Send my microphone to streams, recordings and other programs;
 19. what moved, said once on the first start of this version.

Speech is what reaches the frame's speaker at a given `speech_level`. Keys
and menu items are posted as command events to the frame, the window that
really receives them, and Preferences is the real window driven in code.
What a screen reader reads is read the way it reads it: the status bar from
the native control, a name through MSAA, a rename as the event Windows
raises, an access key by the dialog manager's own rule. Nothing opens a
sound card, a microphone or a camera, nothing makes a sound, no key is
pressed, and every modal window, file windows included, is stood in.
"""

import ctypes
import faulthandler
import json
import os
import sys
import tempfile
import time
from ctypes import POINTER, byref, wintypes

faulthandler.enable()
faulthandler.dump_traceback_later(280, exit=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-polish-")

import numpy as np                                     # noqa: E402
import soundfile as sf                                 # noqa: E402
import wx                                              # noqa: E402

import comtypes.client                                 # noqa: E402
comtypes.client.GetModule("oleacc.dll")
from comtypes.gen.Accessibility import IAccessible    # noqa: E402
from comtypes.automation import VARIANT                # noqa: E402

from dropdeck import board as boardmod                 # noqa: E402
from dropdeck import cabletest                         # noqa: E402
from dropdeck import constants as C                    # noqa: E402
from dropdeck import dialogs                           # noqa: E402
from dropdeck import globalhotkeys                     # noqa: E402
from dropdeck import micinput                          # noqa: E402
from dropdeck import recorder                          # noqa: E402
from dropdeck import secrets                           # noqa: E402
from dropdeck import send as sendmod                   # noqa: E402
from dropdeck import sources                           # noqa: E402
from dropdeck import ui as uimod                       # noqa: E402
from dropdeck.audiofile import CHANNELS                # noqa: E402
from dropdeck.board import Board, same_path            # noqa: E402
from dropdeck.micinput import MicInput                 # noqa: E402
from dropdeck.mixer import Mixer, MixerGroup           # noqa: E402
from dropdeck.plids import ID_PL_ROW_RANDOM, ID_PL_ROW_REMOVE  # noqa: E402

RATE = 48000
BLOCK = 512
CHECKS = []
GUARDS = []
FAILED = []


def check(label, condition, detail=""):
    """A fix: fails on 6fa5dad, passes now."""
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
    """One item. A raise is a failed check, so 6fa5dad runs to the end."""
    try:
        body()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stdout)
        check("%s (raised %s: %s)" % (label, type(exc).__name__, exc), False)


# ---------------------------------------------------------------- stand-ins --
app = wx.App(False)
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
    """wx.FileDialog, answered: a path, or Cancel when there is none. Keeps
    what it was opened with, defaults included."""

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


class Ear:
    """The frame's speaker: what would have been said, and how."""

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
    MainLoop for that long."""
    app.ProcessPendingEvents()
    app.Yield()
    if seconds > 0:
        wx.CallLater(max(1, int(seconds * 1000)), app.ExitMainLoop)
        app.MainLoop()
        app.ProcessPendingEvents()


def settle(times=10):
    """Windows messages handled without a nested main loop, for inside a
    handler that is itself being run by a posted command."""
    for _ in range(times):
        app.ProcessPendingEvents()
        app.Yield()
        time.sleep(0.02)


def post(window, command):
    """A key or a menu item, the way Windows hands it to the frame."""
    event = wx.CommandEvent(wx.wxEVT_MENU, command)
    event.SetEventObject(window)
    window.GetEventHandler().ProcessEvent(event)


def table(target):
    return {(e.GetFlags(), e.GetKeyCode()): e.GetCommand()
            for e in target._build_accelerators()}


ALT_SHIFT = wx.ACCEL_ALT | wx.ACCEL_SHIFT
CTRL_SHIFT = wx.ACCEL_CTRL | wx.ACCEL_SHIFT
TMP = tempfile.mkdtemp(prefix="dropdeck-polish-files-")


def wav(name, seconds=2.0):
    path = os.path.join(TMP, name + ".wav")
    sf.write(path, np.zeros((int(RATE * seconds), CHANNELS), np.float32), RATE)
    return path


def make_board(name, **fields):
    board = Board()
    for key, value in fields.items():
        setattr(board, key, value)
    path = os.path.join(TMP, name + ".json")
    board.save(path)
    return path


def make_frame():
    """A frame the way the app makes one, and its ear. Past its startup
    line (half a second) and its sources (1.2 s), both on timers, so neither
    lands in the middle of a check or after the frame has gone."""
    made = uimod.DropDeckFrame(None)
    made.Show()
    pump(1.4)
    heard = Ear()
    made.speaker = heard
    made._check_mic_signal = lambda *a, **k: None
    return made, heard


def close_frame(made):
    try:
        made.stop_background_work()
    except Exception:
        pass
    try:
        made.mixer.close()
    except Exception:
        pass
    made.board.dirty = False
    made.Destroy()
    pump(0.1)


START = make_board("Start")
boardmod.remember_board_path(START)
frame, ear = make_frame()
ESSENTIAL = C.SPEECH_ESSENTIAL
LAPTOP = "Laptop Mic"


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


def menu_named(title):
    bar = frame.GetMenuBar()
    return bar.GetMenu(bar.FindMenu(title))


def letters_of(labels):
    """{letter: [labels]} for one menu level or page, from its labels."""
    found = {}
    for text in labels:
        text = text.split(chr(9))[0].replace("&&", "")
        if "&" in text and text.index("&") + 1 < len(text):
            found.setdefault(text[text.index("&") + 1].lower(), []).append(
                text)
    return found


def controls(page):
    """Every control on a Preferences page, in creation order."""
    found = []

    def walk(parent):
        for child in parent.GetChildren():
            found.append(child)
            walk(child)

    walk(page)
    return found


WORDED = (wx.StaticText, wx.CheckBox, wx.Button, wx.RadioButton, wx.StaticBox)


def page_letters(page):
    return letters_of([c.GetLabel() for c in controls(page)
                       if isinstance(c, WORDED)])


def real_preferences(page):
    return dialogs.SettingsDialog(frame, frame.board, frame.mixer,
                                  mic=frame.mic, page=page)


def tick(box, value):
    """A check box ticked the way a person ticks it: the value, then the
    event its own handlers listen for."""
    box.SetValue(value)
    event = wx.CommandEvent(wx.wxEVT_CHECKBOX, box.GetId())
    event.SetEventObject(box)
    event.SetInt(1 if value else 0)
    box.GetEventHandler().ProcessEvent(event)


S = dialogs.SettingsDialog

# ------------------------------------------------- what Windows reads --
user32 = ctypes.windll.user32
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetFocus.restype = wintypes.HWND
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetNextDlgTabItem.restype = wintypes.HWND
user32.GetNextDlgTabItem.argtypes = [wintypes.HWND, wintypes.HWND,
                                     wintypes.BOOL]
user32.IsWindowEnabled.argtypes = [wintypes.HWND]
_send_message = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM,
    wintypes.LPARAM)(("SendMessageW", user32))
oleacc = ctypes.oledll.oleacc
OBJID_CLIENT = 0xFFFFFFFC
GW_HWNDNEXT, GW_CHILD = 2, 5
WS_VISIBLE, WS_DISABLED = 0x10000000, 0x08000000
SB_GETTEXTLENGTHW, SB_GETTEXTW = 0x0400 + 12, 0x0400 + 13


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def window_text(hwnd):
    buf = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 1024)
    return buf.value


def native_field(bar, n):
    """One field of a status bar as the native control holds it, which is
    what NVDA+End reads."""
    hwnd = bar.GetHandle()
    length = _send_message(hwnd, SB_GETTEXTLENGTHW, n, 0) & 0xFFFF
    buf = ctypes.create_unicode_buffer(length + 2)
    _send_message(hwnd, SB_GETTEXTW, n, ctypes.addressof(buf))
    return buf.value


def msaa_name(hwnd):
    """A window's name as MSAA hands it to a screen reader."""
    acc = POINTER(IAccessible)()
    oleacc.AccessibleObjectFromWindow(wintypes.HWND(hwnd),
                                      ctypes.c_ulong(OBJID_CLIENT),
                                      byref(IAccessible._iid_), byref(acc))
    child = VARIANT()
    child.value = 0
    return acc.accName(child) or ""


def mnemonic(text):
    """The access key a native label offers, or None."""
    at = 0
    while at < len(text) - 1:
        if text[at] == "&":
            if text[at + 1] == "&":
                at += 2
                continue
            return text[at + 1].lower()
        at += 1
    return None


def lands(page, letter):
    """Where Alt plus `letter` lands on a page, by the dialog manager's rule.

    Only a control that is visible and NOT disabled answers its access key;
    a label answers by moving to the next control in tab order, which skips
    disabled ones. That second half is why an enabled label in front of a
    disabled control sent the key on to whatever came next (Jessica,
    24 November 2026, measured with GetNextDlgTabItem).
    """
    page_hwnd = page.GetHandle()
    child = user32.GetWindow(page_hwnd, GW_CHILD)
    while child:
        style = user32.GetWindowLongW(child, -16) & 0xFFFFFFFF
        if (style & (WS_VISIBLE | WS_DISABLED)) == WS_VISIBLE \
                and mnemonic(window_text(child)) == letter:
            if class_name(child) == "Static":
                return user32.GetNextDlgTabItem(page_hwnd, child, False)
            return child
        child = user32.GetWindow(child, GW_HWNDNEXT)
    return None


UDM_GETBUDDY = 0x0400 + 106


def native(window):
    """The window a control's access key or focus really lands on: the edit
    box of a spin control, or the control itself. A native wx.SpinCtrl is
    the arrows, with the edit box beside it as their buddy."""
    hwnd = window.GetHandle()
    if class_name(hwnd) == "msctls_updown32":
        return _send_message(hwnd, UDM_GETBUDDY, 0, 0)
    for child in window.GetChildren():
        if isinstance(child, wx.TextCtrl):
            return child.GetHandle()
    return hwnd


# Renames, as Windows raises them to a screen reader. In process and out of
# context, so they arrive as messages while wx runs.
NAMECHANGE = 0x800C
RENAMED = []
_WinEventProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD,
                                   wintypes.HWND, wintypes.LONG, wintypes.LONG,
                                   wintypes.DWORD, wintypes.DWORD)


def _on_event(_hook, event, hwnd, _obj, _child, _thread, _ms):
    if event == NAMECHANGE:
        RENAMED.append(hwnd)


_EVENT_PROC = _WinEventProc(_on_event)
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HMODULE, _WinEventProc,
                                   wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD]
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
HOOK = user32.SetWinEventHook(NAMECHANGE, NAMECHANGE, None, _EVENT_PROC,
                              os.getpid(), 0, 0)


# ===========================================================================
heading("1. The status bar reaches the screen reader whole")


def item_1():
    frame.SetSize(frame.FromDIP(wx.Size(820, 600)))
    pump(0.2)
    frame.board.stream_mic = True
    post(frame, uimod.ID_MIC_TOGGLE)
    frame.send = FakeSend()
    try:
        frame._update_status()
        frame.announce("Send my microphone is off on the Microphone page of "
                       "Preferences, so your voice is not in it. Everything is "
                       "in it. The send is keeping up.")
        pump(0.2)
        bar = frame.status
        wide = [bar.GetTextExtent(bar.GetStatusText(n))[0]
                > bar.GetFieldRect(n).width for n in (0, 1)]
        guard("both fields hold more than their room, so the check means "
              "something", all(wide),
              (wide, [bar.GetFieldRect(n).width for n in (0, 1)]))
        for n, what in ((0, "the readout, mic and sending first"),
                        (1, "the last announcement")):
            got = native_field(bar, n)
            check("the native status bar holds %s whole, as NVDA+End reads "
                  "it" % what, got == bar.GetStatusText(n) and bool(got),
                  (got, bar.GetStatusText(n)))
    finally:
        frame.send = None
        mic_off()
        frame._update_status()


section("1", item_1)


# ===========================================================================
heading("2. Ctrl+M says first that nobody else hears it, and why")


def ctrl_m():
    return hear(lambda: post(frame, uimod.ID_MIC_TOGGLE))


def item_2():
    guard("Ctrl+M is the microphone in the table",
          table(frame).get((wx.ACCEL_CTRL, ord("M"))) == uimod.ID_MIC_TOGGLE)
    mic_off()
    frame._mic_named = LAPTOP
    frame.mixer.ducking = True
    frame.board.stream_mic = True
    frame.send = FakeSend()
    frame._sync_air_taps()
    try:
        frame.mic.muted = True
        frame.apply_source_mixing()
        said = ctrl_m()
        check("sending, and muted in Source control: first that nobody else "
              "hears it, and why, then Music ducked",
              said == ["Mic on, but nobody else hears it: you are muted in "
                       "Source control. Music ducked"], said)
        guard("and nobody does: the air tap has it off",
              frame.mic.on_air is False)
        mic_off()
        frame.mic.muted = False

        frame.board.stream_mic = False
        frame.apply_source_mixing()
        said = ctrl_m()
        check("with Send my microphone off, in those words, first",
              said == ["Mic on, but nobody else hears it: Send my microphone "
                       "is off. Music ducked"], said)
        mic_off()
        frame.mixer.ducking = False
        said = ctrl_m()
        check("with ducking off, the reason and nothing after it",
              said == ["Mic on, but nobody else hears it: Send my microphone "
                       "is off"], said)
        mic_off()
        frame.mixer.ducking = True
        frame.board.stream_mic = True

        guest = sources.Source(name="Guest", samplerate=RATE)
        guest.soloed = True
        frame.sources.append(guest)
        try:
            frame.apply_source_mixing()
            said = ctrl_m()
            check("with a source soloed and not the microphone: a source is "
                  "soloed",
                  said == ["Mic on, but nobody else hears it: a source is "
                           "soloed. Music ducked"], said)
            guard("and the tap agrees", frame.mic.on_air is False)
            mic_off()
            frame.mic.soloed = True
            frame.apply_source_mixing()
            said = ctrl_m()
            guard("with the microphone soloed too it reaches the air, and "
                  "the line is the short one", said == ["Mic on. Music ducked"]
                  and frame.mic.on_air is True, said)
            mic_off()
            frame.mic.soloed = False
        finally:
            frame.sources.remove(guest)
            frame.apply_source_mixing()

        # One predicate. Told the microphone reaches the air while it is
        # muted, the taps must put it there AND Ctrl+M must say the short
        # line; a copy of the rule in either place would disagree.
        frame.mic.muted = True
        frame._mic_off_air_reason = lambda: ""
        try:
            frame.apply_source_mixing()
            said = ctrl_m()
            check("Ctrl+M and the air taps ask the same predicate",
                  frame.mic.on_air is True and said == ["Mic on. Music ducked"],
                  (frame.mic.on_air, said))
        finally:
            del frame._mic_off_air_reason
            frame.mic.muted = False
            mic_off()
            frame.apply_source_mixing()

        said = ctrl_m()
        guard("sending with the microphone on it, the short line as it was",
              said == ["Mic on. Music ducked"], said)
        mic_off()
    finally:
        frame.send = None
        frame._sync_air_taps()
    frame.board.stream_mic = False
    said = ctrl_m()
    guard("with nothing going out there is no air to be off: the short line",
          said == ["Mic on. Music ducked"], said)
    mic_off()
    frame.board.stream_mic = True


section("2", item_2)


# ===========================================================================
heading("4. On a track's menu R inserts a random drop and M removes")

SONGS = [wav("Song %d" % n, 6.0) for n in (1, 2, 3)]
POPPED = []


def capture_rows(self, menu, *args, **kw):
    POPPED.append([(item.GetItemLabel(), item.GetId())
                   for item in menu.GetMenuItems() if not item.IsSeparator()])
    return True


def row_menu(panel):
    real = wx.ListCtrl.__dict__.get("PopupMenu")
    wx.ListCtrl.PopupMenu = capture_rows
    try:
        POPPED.clear()
        event = wx.ContextMenuEvent(wx.wxEVT_CONTEXT_MENU, panel.list.GetId())
        event.SetEventObject(panel.list)
        panel.list.GetEventHandler().ProcessEvent(event)
    finally:
        if real is None:
            del wx.ListCtrl.PopupMenu
        else:
            wx.ListCtrl.PopupMenu = real
    return POPPED[0] if POPPED else []


def item_4():
    panel = frame.playlist_panel
    frame.board.playlist.clear()
    panel.refresh()
    panel.add_paths(SONGS)
    frame.board.drops.add([wav("Station ID", 1.0)])
    frame.show_view(uimod.VIEW_PLAYLIST)
    panel.focus_list()
    panel.select(1)
    pump(0.1)
    items = row_menu(panel)
    found = {}
    for label, command in items:
        text = label.split(chr(9))[0].replace("&&", "")
        if "&" in text:
            found.setdefault(text[text.index("&") + 1].lower(), []).append(
                (text, command))
    check("R is Insert a random drop from the library again, and its alone",
          found.get("r") == [("Insert a &random drop from the library",
                              ID_PL_ROW_RANDOM)], found.get("r"))
    check("M is Remove from the running order, and its alone",
          found.get("m") == [("Re&move from the running order",
                              ID_PL_ROW_REMOVE)], found.get("m"))
    check("and Remove still shows its key, written Delete since the final "
          "audit",
          [label for label, command in items if command == ID_PL_ROW_REMOVE]
          == ["Re&move from the running order" + chr(9) + "Delete"], items)
    guard("Move to the top keeps the O the last step gave it",
          [c for _t, c in found.get("o", [])] == [uimod.ID_PL_ROW_TOP],
          found.get("o"))
    guard("and no letter twice at that level",
          not {k: v for k, v in found.items() if len(v) > 1}, found)
    # What each of those letters does, through the item's own binding.
    count = len(frame.board.playlist)
    post(frame, ID_PL_ROW_RANDOM)
    guard("the random drop's item puts a drop from the library in",
          len(frame.board.playlist) == count + 1
          and frame.board.playlist[1].is_drop, len(frame.board.playlist))
    panel.select(0)
    count = len(frame.board.playlist)
    post(frame, ID_PL_ROW_REMOVE)
    guard("and Remove's takes the row out",
          len(frame.board.playlist) == count - 1, len(frame.board.playlist))
    frame.board.playlist.clear()
    panel.refresh()
    frame.show_view(uimod.VIEW_BOARD)


section("4", item_4)


# ===========================================================================
heading("5. Put it right on the microphone warning lands on the box")


def item_5():
    radio(frame.board)
    frame.board.stream_mic = False
    frame.board.ask_before_live = True
    seen = []

    def look(dialog):
        dialog.Show()
        settle()
        focus = wx.Window.FindFocus()
        seen.append((focus.GetHandle() if focus else None,
                     dialog.stream_mic.GetHandle(),
                     dialog.mic_device.GetHandle()))
        dialog.Hide()
        return wx.ID_CANCEL

    Scripted.script = staticmethod(look)
    Scripted.pages.clear()
    real = uimod.GoLiveDialog
    uimod.GoLiveDialog = PutItRight
    PutItRight.answers[:] = ["fix", "stay"]
    try:
        post(frame, uimod.ID_STREAM_TOGGLE_AUDIO)
    finally:
        uimod.GoLiveDialog = real
    guard("Put it right on the warning opens Preferences on the Microphone "
          "page", Scripted.pages == [S.PAGE_MIC], Scripted.pages)
    check("with focus on Send my microphone, the box the warning is about",
          seen and seen[0][0] == seen[0][1], seen)
    guard("while Ctrl+Shift+M still lands on the microphone picker",
          table(frame).get((CTRL_SHIFT, ord("M"))) == uimod.ID_MIC_SETTINGS)
    seen.clear()
    post(frame, uimod.ID_MIC_SETTINGS)
    guard("and does", seen and seen[0][0] == seen[0][2], seen)
    frame.board.stream_mic = True


section("5", item_5)


# ===========================================================================
heading("6. A station that changes Send my microphone says so")


def item_6():
    board = frame.board
    board.stream_stations = []
    radio(board)
    for name, mic in (("Loud Station", True), ("Quiet Station", False),
                      ("Also Quiet", False), ("Scratch", False)):
        board.stream_name = name
        board.stream_mic = mic
        board.save_station()
    frame._rebuild_station_menu()
    names = board.station_names()
    frame.send = FakeSend()
    frame._sync_air_taps()
    try:
        guard("set up: Scratch is loaded and the microphone is off the send",
              board.stream_name == "Scratch" and frame.mic.on_air is False)
        said = hear(lambda: post(frame, uimod.ID_STATION_BASE
                                 + names.index("Loud Station")))
        check("loading a station that sends the microphone says so, last",
              said and said[-1].startswith("Loud Station. Alt+Shift+B goes")
              and said[-1].endswith(". Your microphone goes out with this "
                                    "station"), said)
        check("and it is true at once: the send already running has it",
              frame.mic.on_air is True)
        # On the send now whatever the load did, so the next load is seen
        # taking it off rather than finding it off already.
        frame._sync_air_taps()
        guard("set up: the microphone is on the send",
              frame.mic.on_air is True)
        said = hear(lambda: post(frame, uimod.ID_STATION_BASE
                                 + names.index("Quiet Station")))
        check("one that keeps it out says that",
              said and said[-1].endswith(". Your microphone is not sent with "
                                         "this station"), said)
        check("and the microphone is off the send at once",
              frame.mic.on_air is False)
        said = hear(lambda: post(frame, uimod.ID_STATION_BASE
                                 + names.index("Also Quiet")))
        guard("a station that changes nothing about it says nothing about it",
              said and said[-1].startswith("Also Quiet.")
              and "microphone" not in said[-1].lower(), said)
    finally:
        frame.send = None
        frame._sync_air_taps()

    def pick(name):
        def script(dialog):
            dialog.stream_picker.SetSelection(
                dialog.stream_picker.GetStrings().index(name))
            dialog._on_pick_station(None)
            return wx.ID_CANCEL
        return script

    said = hear(lambda: preferences(pick("Loud Station")))
    check("loading one inside Preferences says it too, since the box is on "
          "another page", "Loaded Loud Station. Your microphone goes out with "
          "this station." in said, said)
    said = hear(lambda: preferences(pick("Also Quiet")))
    guard("and Loaded, alone, when it changes nothing",
          "Loaded Also Quiet." in said, said)

    prefs = real_preferences(S.PAGE_STREAM)
    try:
        page = prefs.tabs.GetPage(S.PAGE_STREAM)
        order = list(page.GetChildren())
        notes = [c for c in order if isinstance(c, wx.StaticText)
                 and c.GetLabel() == "Whether your microphone goes out is on "
                                     "the Microphone page"]
        check("Audio streaming says where the box went", len(notes) == 1,
              len(notes))
        check("where the box used to be, just before the go live question",
              notes and order.index(prefs.ask_before_live)
              == order.index(notes[0]) + 1)
    finally:
        prefs.Destroy()
    board.stream_mic = True


section("6", item_6)


# ===========================================================================
heading("7. Whose key it is, on the menu and at startup")


def add_songs_item():
    return frame.GetMenuBar().FindItemById(uimod.ID_PL_ADD)


def item_7():
    board = Board()
    misc = board.bank_slots(C.BANK_MISC)
    misc[0].filepath = wav("Q and A bumper", 0.5)
    misc[0].name = "Q&A bumper"
    misc[0].custom_hotkey = "Alt+Shift+P"
    misc[0].key_code, misc[0].modifiers = ord("P"), ALT_SHIFT
    # Emptied in 3.10.1 with its key still on it, which 3.10.1 allowed.
    misc[2].custom_hotkey = "Alt+Shift+A"
    misc[2].key_code, misc[2].modifiers = ord("A"), ALT_SHIFT
    path = os.path.join(TMP, "Pads keep keys.json")
    board.save(path)
    frame._open_board(path)
    frame.board.onair_on = True
    frame._onair_bypassed = False
    frame._apply_onair()
    compare = frame.onair_item.GetItemLabel()
    check("the compare says whose key it is, without No key or on this board",
          compare == "&Quick compare, on air sound is on. Alt+Shift+P plays "
                     "Q&&A bumper", compare)
    drawn = frame.onair_item.GetItemLabelText()
    check("and the pad's own ampersand draws as it reads, Q&A",
          drawn == "Quick compare, on air sound is on. Alt+Shift+P plays Q&A "
                   "bumper", drawn)
    add = add_songs_item().GetItemLabel()
    check("an empty pad keeping Alt+Shift+A is named by its bank and number",
          add == "&Add songs to the end... Alt+Shift+A is kept by Misc 3, "
                 "which is empty", add)
    guard("Q is the compare's alone on the On air menu",
          len(letters_of(i.GetItemLabel() for i in
                         menu_named("On air").GetMenuItems()
                         if not i.IsSeparator()).get("q", [])) == 1)
    said = " ".join(hear(frame._startup_line))
    check("the startup line says the empty pad keeps it, and how to free it",
          "Alt+Shift+A is kept by Misc 3, which is empty, so Add songs to the "
          "end has no key. Clear that pad's hotkey to free it" in said, said)
    guard("and a pad with a sound on its key is said as it was",
          "Alt+Shift+P plays Q&A bumper on this board, so the quick compare "
          "of the on air sound has no key. It is on the On air menu" in said,
          said)
    frame._open_board(START)
    guard("a board where no pad has them gets both keys back",
          add_songs_item().GetItemLabel().endswith(chr(9) + "Alt+Shift+A")
          and frame.onair_item.GetItemLabel().endswith(chr(9)
                                                       + "Alt+Shift+P"))


section("7", item_7)


# ===========================================================================
heading("8. The compare says where it is heard")


def item_8():
    item = frame.GetMenuBar().FindItemById(uimod.ID_SEND_MONITOR)
    guard("Ctrl+Shift+H really is Hear what is being sent, in the table and "
          "on the menu",
          table(frame).get((CTRL_SHIFT, ord("H"))) == uimod.ID_SEND_MONITOR
          and item is not None and item.GetItemLabel()
          == "Hear what is &being sent" + chr(9) + "Ctrl+Shift+H",
          item.GetItemLabel() if item else None)
    frame.board.onair_on = True
    frame._onair_bypassed = False
    frame._apply_onair()
    said = hear(lambda: post(frame, uimod.ID_ONAIR_COMPARE))
    check("pressed: bypassed, in what goes out", said
          == ["On air sound bypassed, in what goes out"], said)
    said = hear(lambda: post(frame, uimod.ID_ONAIR_COMPARE))
    check("pressed again: back on", said == ["On air sound back on"], said)

    def press_all():
        frame.board.speech_level = C.SPEECH_ALL
        frame._menu_closed_at = None
        ear.said.clear()
        post(frame, uimod.ID_ONAIR_COMPARE)
        return list(ear.said)

    first = press_all()
    check("at the all level the first bypass also says where to listen, "
          "queued behind it, the essential presses not having used it up",
          first == [("On air sound bypassed, in what goes out", True),
                    ("To hear the difference, record a minute with Ctrl+R, "
                     "or send the show with Alt+Shift+O and press "
                     "Ctrl+Shift+H", False)], first)
    press_all()
    again = press_all()
    check("and only once a session",
          again == [("On air sound bypassed, in what goes out", True)], again)
    press_all()
    guard("the compare is still a compare: back where it started",
          frame._onair_bypassed is False)
    frame.board.speech_level = ESSENTIAL


section("8", item_8)


# ===========================================================================
heading("9. Ctrl+S on a board never named, after a restart and a first run")


def item_9():
    real_dialog = wx.FileDialog
    wx.FileDialog = FakeFileDialog
    documents = recorder.documents_folder()
    try:
        # A first run: nothing remembered that is there, no board.json, and
        # no board ever saved in a folder of the user's.
        default = boardmod.default_board_path()
        if os.path.exists(default):
            os.remove(default)
        boardmod.remember_board_path(os.path.join(TMP, "gone.json"))
        state = boardmod.machine_state()
        state.pop("board_folder", None)
        boardmod.save_machine_state(state)
        first, _heard = make_frame()
        try:
            guard("a first run opens the demo pack", first._loaded_demo)
            FakeFileDialog.opened.clear()
            FakeFileDialog.answer[0] = None
            post(first, wx.ID_SAVE)
            opened = FakeFileDialog.opened
            check("Ctrl+S on the board a first run opens asks where to save it",
                  [m for m, _k in opened] == ["Save board as"], opened)
            kw = opened[0][1] if opened else {}
            check("starting in Documents, with no folder of the user's "
                  "known yet", same_path(kw.get("defaultDir"), documents),
                  kw.get("defaultDir"))
            check("with a name already in the box, and not board.json",
                  kw.get("defaultFile") == "Drop Deck board.json",
                  kw.get("defaultFile"))
            check("and Cancel there writes no board.json",
                  not os.path.exists(default))
        finally:
            close_frame(first)
        if os.path.exists(default):
            os.remove(default)

        # A board of the user's, in a folder of theirs, saved there.
        shows = tempfile.mkdtemp(prefix="dropdeck-polish-shows-")
        mine = os.path.join(shows, "Mine.json")
        Board().save(mine)
        boardmod.remember_board_path(mine)
        before, _heard = make_frame()
        try:
            before.board[0].filepath = wav("Sting", 0.5)
            before._touch()
            guard("a named board saves where it is",
                  before._save(quiet=True) and os.path.exists(mine))
            # File, New, something on it, and the save timer's save.
            post(before, wx.ID_NEW)
            pump(0.1)
            home = before.board.path
            before.board[1].filepath = wav("Stinger", 0.5)
            before._touch()
            before._save(quiet=True)
            guard("File, New's board is in a home of its own in the settings "
                  "folder", os.path.dirname(home) == boardmod.config_dir()
                  and os.path.exists(home), home)
            with open(home, encoding="utf-8") as handle:
                data = json.load(handle)
            check("and its file says it has never been named",
                  data.get("never_named") is True, data.get("never_named"))
        finally:
            close_frame(before)

        # A restart: the board that opens is that home.
        after, heard = make_frame()
        try:
            guard("after the restart the home opens",
                  same_path(after.board.path, home), after.board.path)
            FakeFileDialog.opened.clear()
            FakeFileDialog.answer[0] = None
            post(after, wx.ID_SAVE)
            opened = FakeFileDialog.opened
            check("Ctrl+S on it still asks where to save it",
                  [m for m, _k in opened] == ["Save board as"], opened)
            kw = opened[0][1] if opened else {}
            check("starting in the folder the last board was saved in",
                  same_path(kw.get("defaultDir"), shows), kw.get("defaultDir"))
            check("with its own name in the box",
                  kw.get("defaultFile") == "New board.json",
                  kw.get("defaultFile"))
            named = os.path.join(shows, "Morning show.json")
            FakeFileDialog.answer[0] = named
            after.board.speech_level = C.SPEECH_ALL
            after._menu_closed_at = None
            heard.said.clear()
            post(after, wx.ID_SAVE)
            pump((C.AFTER_MENU_SPEECH_MS + 300) / 1000.0)
            check("saved, it says its name and its folder, no .json and no "
                  "path", heard.texts == ["Saved as Morning show, in %s"
                                          % os.path.basename(shows)],
                  heard.texts)
            saved = {}
            if os.path.exists(named):
                with open(named, encoding="utf-8") as handle:
                    saved = json.load(handle)
            check("the named file has the flag cleared, and so does the board",
                  saved.get("never_named") is False
                  and after.board.never_named is False,
                  (saved.get("never_named"),
                   getattr(after.board, "never_named", None)))
            FakeFileDialog.opened.clear()
            after.board[2].filepath = wav("Third", 0.5)
            after._touch()
            post(after, wx.ID_SAVE)
            check("and once named, Ctrl+S saves there with no window",
                  not FakeFileDialog.opened
                  and same_path(after.board.path, named),
                  (FakeFileDialog.opened, after.board.path))
        finally:
            close_frame(after)
    finally:
        wx.FileDialog = real_dialog
        FakeFileDialog.answer[0] = None
        boardmod.remember_board_path(START)


section("9", item_9)


# ===========================================================================
heading("10. What was only in tooltips is in the labels")


def item_10():
    prefs = real_preferences(S.PAGE_STREAM)
    try:
        label = prefs.ask_before_live.GetLabel()
        check("the go live question says going live, which both keys do",
              label == "S&ay what is going out before going live", label)
        guard("and A is still its alone on Audio streaming",
              len(page_letters(prefs.tabs.GetPage(S.PAGE_STREAM))
                  .get("a", [])) == 1)
        label = prefs.match_loudness.GetLabel()
        check("loudness matching says it changes what you hear as well",
              label == "&Match the loudness of songs and sounds, for you and "
                       "on air", label)
        label = prefs.onair_on.GetLabel()
        check("the on air sound box reads as the Voice page's does",
              label == "Process the &on air sound", label)
        letters = page_letters(prefs.tabs.GetPage(S.PAGE_ONAIR))
        check("O is that box's alone on its page",
              letters.get("o") == ["Process the &on air sound"],
              letters.get("o"))
        guard("and no letter twice there",
              not {k: v for k, v in letters.items() if len(v) > 1}, letters)
    finally:
        prefs.Destroy()


section("10", item_10)


# ===========================================================================
heading("11. A label is disabled with its control")


def item_11():
    frame.board.ducking = True
    frame.board.talk_duck = False
    frame.board.onair_on = True
    prefs = real_preferences(S.PAGE_SOUND)
    prefs.Show()
    pump(0.2)
    try:
        sound = prefs.tabs.GetPage(S.PAGE_SOUND)
        landed = lands(sound, "h")
        check("Duck further off: Alt+H lands nowhere, not on Fade beds in",
              landed is None, class_name(landed) if landed else None)
        tick(prefs.talk_duck, True)
        guard("ticked, Alt+H lands on the amount's edit box",
              lands(sound, "h") == native(prefs.talk_duck_db))
        tick(prefs.duck_on, False)
        landed = lands(sound, "c")
        check("ducking off: Alt+C, the duck depth, lands nowhere",
              landed is None, class_name(landed) if landed else None)
        tick(prefs.duck_on, True)
        tick(prefs.talk_duck, False)
        prefs.tabs.SetSelection(S.PAGE_ONAIR)
        pump(0.2)
        onair = prefs.tabs.GetPage(S.PAGE_ONAIR)
        tick(prefs.onair_on, False)
        for letter, what in (("e", "Even out the music"),
                             ("n", "Never louder than")):
            landed = lands(onair, letter)
            check("On air sound off: Alt+%s, %s, lands nowhere, not on Match "
                  "the loudness" % (letter.upper(), what), landed is None,
                  window_text(landed) if landed else None)
        tick(prefs.onair_on, True)
        guard("on again, Alt+E lands on Even out the music",
              lands(onair, "e") == prefs.onair_even.GetHandle())
    finally:
        prefs.Destroy()
        pump(0.1)


section("11", item_11)


# ===========================================================================
heading("12. Preferences waits for the window coming back before speaking")


def item_12():
    item = frame.GetMenuBar().FindItemById(uimod.ID_SETTINGS)
    guard("Ctrl+P is Preferences on the File menu", item is not None
          and item.GetItemLabel().endswith(chr(9) + "Ctrl+P"))
    Scripted.script = staticmethod(lambda dialog: wx.ID_CANCEL)
    frame.board.speech_level = C.SPEECH_ALL
    frame._menu_closed_at = None
    ear.said.clear()
    post(frame, uimod.ID_SETTINGS)
    at_once = list(ear.said)
    pump((C.AFTER_MENU_SPEECH_MS + 300) / 1000.0)
    check("nothing is said under the screen reader's reading of the window "
          "coming back", not at_once, at_once)
    check("it is said after that, queued behind it",
          ear.said == [("Nothing changed", False)], ear.said)
    frame.board.speech_level = ESSENTIAL


section("12", item_12)


# ===========================================================================
heading("13. Both, always mixed")


def feed_voice(mic, seconds=3.0):
    """A voice on input 1 and nothing but hiss on input 2, through the
    microphone's own callback. The weights it mixes with, block by block."""
    rnd = np.random.default_rng(3)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    pair = np.zeros((n, 2), np.float32)
    pair[:, 0] = 0.1 * np.sin(2 * np.pi * 220.0 * t)
    pair[:, 1] = rnd.standard_normal(n) * 10 ** (-70 / 20.0)
    seen = []
    for at in range(0, n, BLOCK):
        block = np.ascontiguousarray(pair[at:at + BLOCK])
        mic._callback(block, len(block), None, None)
        seen.append(tuple(round(float(w), 6) for w in mic._side_weights))
    return seen


def item_13():
    prefs = real_preferences(S.PAGE_MIC)
    try:
        choices = [prefs.mic_channel.GetString(n)
                   for n in range(prefs.mic_channel.GetCount())]
        check("Which channel offers both kinds of Both, then each side",
              choices == ["Both, the side with a voice on it",
                          "Both, always mixed", "Left only", "Right only"],
              choices)
        guard("a board made by this version opens on the first",
              prefs.mic_channel.GetSelection() == 0)
    finally:
        prefs.Destroy()

    def choose(label):
        def script(dialog):
            names = [dialog.mic_channel.GetString(n)
                     for n in range(dialog.mic_channel.GetCount())]
            if label not in names:
                return wx.ID_CANCEL
            dialog.mic_channel.SetSelection(names.index(label))
            return wx.ID_OK
        return script

    preferences(choose("Both, always mixed"))
    check("choosing Both, always mixed saves mix, the plain average, onto "
          "the board and the microphone",
          frame.board.mic_channel == "mix"
          and frame.mic.channel == "mix",
          (frame.board.mic_channel, frame.mic.channel))
    weights = feed_voice(frame.mic)
    check("and it never moves the weights: half each, all three seconds, "
          "with one input silent", set(weights) == {(0.5, 0.5)},
          sorted(set(weights))[:4])
    preferences(choose("Both, the side with a voice on it"))
    guard("the side with a voice on it is the key voice",
          frame.board.mic_channel == "voice"
          and frame.mic.channel == "voice")
    weights = feed_voice(frame.mic)
    guard("which still takes the talking side alone after a second",
          weights[-1] == (1.0, 0.0), weights[-1])

    path = os.path.join(TMP, "Averaged.json")
    Board().save(path)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["mic_channel"] = "average"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    check("a board file with the unreleased average opens as mix, the "
          "same thing", Board.load(path).mic_channel == "mix",
          Board.load(path).mic_channel)
    data["mic_channel"] = "sideways"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    guard("anything else in a board file opens as the plain average, as "
          "3.10.1 opened it", Board.load(path).mic_channel == "mix")
    frame.board.mic_channel = frame.mic.channel = "voice"


section("13", item_13)


# ===========================================================================
heading("14. By how much further, in decibels, as the edit box reads it")


def item_14():
    frame.board.ducking = True
    frame.board.talk_duck = True
    prefs = real_preferences(S.PAGE_SOUND)
    prefs.Show()
    pump(0.2)
    try:
        sound = prefs.tabs.GetPage(S.PAGE_SOUND)
        statics = [c.GetLabel() for c in controls(sound)
                   if isinstance(c, wx.StaticText)
                   and "how much" in c.GetLabel().replace("&", "")]
        check("the label is By how much further, in decibels, with its H",
              statics == ["By &how much further, in decibels"], statics)
        check("and its name for wx is the same words",
              prefs.talk_duck_db.GetName() == "By how much further, in "
                                              "decibels",
              prefs.talk_duck_db.GetName())
        prefs.talk_duck_db.SetFocus()
        pump(0.1)
        hwnd = user32.GetFocus()
        name = msaa_name(hwnd) if hwnd else ""
        check("the edit box that takes focus reads those words, through MSAA",
              class_name(hwnd) == "Edit"
              and name == "By how much further, in decibels",
              (class_name(hwnd), name))
    finally:
        prefs.Destroy()
        pump(0.1)
    frame.board.talk_duck = False


section("14", item_14)


# ===========================================================================
heading("15. The Stop everything button is renamed only for new words")


def item_15():
    button = frame.stop_button
    hwnd = button.GetHandle()
    pump(0.2)
    RENAMED.clear()
    frame._sync_stop_words()
    frame._sync_stop_words()
    pump(0.3)
    same = [h for h in RENAMED if h == hwnd]
    check("syncing the same words raises no name change on the button",
          not same, len(same))
    frame.board.stop_presses = 3
    RENAMED.clear()
    frame._sync_stop_words()
    pump(0.3)
    changed = [h for h in RENAMED if h == hwnd]
    guard("new words still rename it, and the rename is heard (the control)",
          changed and button.GetLabel() == "Stop everything  (Escape three "
                                           "times)",
          (len(changed), button.GetLabel()))
    frame.board.stop_presses = C.DEFAULT_STOP_PRESSES
    frame._sync_stop_words()


section("15", item_15)


# ===========================================================================
heading("16. Firm says the ceiling it moved")


def item_16():
    frame.board.onair_on = True
    frame.board.onair_even = "gentle"
    frame.board.onair_ceiling_db = C.default_onair_ceiling("gentle")
    frame.board.speech_level = ESSENTIAL
    seen = []

    def script(dialog):
        keys = [key for key, _label in C.ONAIR_EVEN_CHOICES]

        def pick(key):
            ear.said.clear()
            frame._menu_closed_at = None
            dialog.onair_even.SetSelection(keys.index(key))
            event = wx.CommandEvent(wx.wxEVT_CHOICE, dialog.onair_even.GetId())
            event.SetEventObject(dialog.onair_even)
            event.SetInt(keys.index(key))
            dialog.onair_even.GetEventHandler().ProcessEvent(event)
            seen.append((list(ear.said),
                         round(float(dialog.onair_ceiling.GetValue()), 1)))

        pick("firm")
        pick("gentle")
        dialog.onair_ceiling.SetValue(-4.0)
        pick("firm")
        return wx.ID_CANCEL

    preferences(script)
    check("Firm says the ceiling it moved, queued behind the choice",
          seen and seen[0] == ([("Never louder than is now minus 3", False)],
                               -3.0), seen[:1])
    check("and back to Gentle, minus 2",
          len(seen) > 1 and seen[1] == ([("Never louder than is now minus 2",
                                          False)], -2.0), seen[1:2])
    guard("a ceiling set by hand stays where it was put, and nothing is said",
          len(seen) > 2 and seen[2] == ([], -4.0), seen[2:])


section("16", item_16)


# ===========================================================================
heading("17 and 18. The Microphone page's two boxes")


def item_17_18():
    prefs = real_preferences(S.PAGE_MIC)
    try:
        page = prefs.tabs.GetPage(S.PAGE_MIC)
        letters = page_letters(page)
        label = prefs.mic_monitor.GetLabel()
        check("the monitoring box is Hear my own voice there",
              label == "&Hear my own voice there (headphones only)", label)
        guard("keeping H, its alone on the page",
              len(letters.get("h", [])) == 1, letters.get("h"))
        label = prefs.stream_mic.GetLabel()
        check("Send my microphone says other programs, not our word the send",
              label == "Send my m&icrophone to streams, recordings and other "
                       "programs", label)
        tip = prefs.stream_mic.GetToolTipText()
        check("and so does its tooltip", "the send" not in tip
              and "other programs" in tip, tip)
        guard("keeping I, its alone on the page",
              len(letters.get("i", [])) == 1, letters.get("i"))
    finally:
        prefs.Destroy()


section("17 and 18", item_17_18)


# ===========================================================================
heading("19. What moved, said once on the first start of this version")

NOTICE = ("New in this version: On air sound, which evens out the music "
          "your listeners get, is not switched on for this board yet. Put "
          "the microphone on air is now Send my microphone, on the "
          "Microphone page")


def legacy_board(name):
    """A board as 3.10.1 saved it: no on air sound in the file at all."""
    path = make_board(name)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for key in ("onair_on", "match_loudness", "onair_even",
                "onair_ceiling_db", "never_named"):
        data.pop(key, None)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return path


def starting(path):
    """A start of the app on `path`, heard from the very first moment."""
    boardmod.remember_board_path(path)
    made = uimod.DropDeckFrame(None)
    heard = Ear()
    made.speaker = heard
    made._check_mic_signal = lambda *a, **k: None
    made.Show()
    # The startup line is half a second after the window, on a timer, and
    # the sources start at 1.2 s.
    pump(1.4)
    return made, heard


def item_19():
    state = boardmod.machine_state()
    state.pop("told_onair_and_mic_moved", None)
    boardmod.save_machine_state(state)
    first, heard = starting(legacy_board("Old show"))
    try:
        guard("the board it opened has On air sound off, as an update's does",
              first.board.onair_on is False)
        said = list(heard.said)
        check("the first start of this version says what moved, after the "
              "startup line, queued behind it",
              len(said) == 2 and said[0][0].startswith("TG Drop Deck ready")
              and said[1] == (NOTICE, False), said)
        check("and writes down on this computer that it has",
              boardmod.machine_state().get("told_onair_and_mic_moved")
              is True)
    finally:
        close_frame(first)
    second, heard = starting(legacy_board("Old show again"))
    try:
        guard("the next start does not say it again",
              NOTICE not in heard.texts, heard.texts)
    finally:
        close_frame(second)
    state = boardmod.machine_state()
    state.pop("told_onair_and_mic_moved", None)
    boardmod.save_machine_state(state)
    third, heard = starting(make_board("Made in this version"))
    try:
        guard("a board that has On air sound on is never told it is off",
              NOTICE not in heard.texts, heard.texts)
    finally:
        close_frame(third)
    boardmod.remember_board_path(START)


section("19", item_19)


# ===========================================================================
heading("20. Four sentences the guide step found untrue")


def item_20():
    prefs = real_preferences(S.PAGE_ONAIR)
    try:
        tip = prefs.match_loudness.GetToolTipText()
        check("loudness matching says a level set on a PAD wins, the only "
              "level Windows lets you set",
              "pad yourself always wins" in tip and "song" not in tip.split(
                  "matches the rest")[1], tip)
        notes = [child.GetLabel() for child in
                 prefs.tabs.GetPage(S.PAGE_MIC).GetChildren()
                 if isinstance(child, wx.StaticText)]
        said = " ".join(" ".join(n.split()) for n in notes)
        check("the Microphone page says the music ducks only while ducking "
              "is on", "While it is on, and ducking is on, the beds" in said,
              said[:200])
    finally:
        prefs.Destroy()
    item = frame.GetMenuBar().FindItemById(uimod.ID_MIC_TOGGLE)
    check("so does the Microphone menu item's help",
          item is not None and "and ducking is on" in item.GetHelp(),
          item.GetHelp() if item is not None else None)
    path = os.path.join(tempfile.mkdtemp(prefix="dropdeck-named-"),
                        "Mine.json")
    frame.board.path = path
    frame.board.never_named = False
    frame.board.dirty = True
    words = hear(lambda: frame._save(), level=C.SPEECH_ALL)
    check("a plain Ctrl+S on a named board says its name, no .json",
          any(w == "Saved Mine" for w in words)
          and not any(".json" in w for w in words), words)
    source = open(uimod.__file__, encoding="utf-8").read()
    guard("the record folder refusal names the Choose button, which is "
          "what that button is called",
          "picked with Choose" in source and "with Browse" not in source)


section("20", item_20)


# ---------------------------------------------------------------------------
user32.UnhookWinEvent(HOOK)
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
