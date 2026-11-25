"""Review of 24 November 2026, Area 5: where options live, and four Area 4
leftovers.

    python tools/run_private.py tests/test_review_options.py

Every `check` here fails on 129a3fd and passes on the fix. A `guard` is a
thing that was already right and has to stay right (the go live question on
both keys, Cancel putting a station back, a named board saving where it is);
guards pass on both and are counted on a line of their own.

  0. since 3.8.2 Ctrl+B is the video platform and Alt+Shift+B the radio
     station, so nothing says Ctrl+B about the radio station any more:
     Ctrl+Shift+B off air, loading a saved station, Ctrl+Shift+W on the
     picture, the status bar, and the two tooltips about the go live
     question, which both keys ask;
  1. the cue sheet is on the Playlist menu, letter T, with its key;
  2. Add songs to the end has Alt+Shift+A, which was free, and a bank 4 pad
     that already had it keeps it, the way Alt+Shift+P yields;
  3. Send my microphone to streams, recordings and the send is on the
     Microphone page: saved by OK, put back by Cancel, filled by a station,
     and still refused onto the send's own cable;
  4. Hear yourself through is What I listen on;
  5. the ducking box says it ducks under the microphone too;
  6. the status bar says the state first;
  7. Ctrl+S on a board that was never named asks where to save it;
  8. Send song titles as, three ways round, with the album read alongside
     the other tags and the station's title made in one place.

Speech is what reaches the frame's speaker at a given `speech_level`. Keys
and menu items are posted as command events to the frame, the window that
really receives them, and Preferences is the real window driven in code.
Nothing opens a sound card, a microphone or a camera, and nothing makes a
sound: the mixers run with no stream, the microphone's start opens nothing,
the send and the streamer are stand-ins, and every modal window, file
windows included, is stood in.
"""

import faulthandler
import json
import os
import shutil
import sys
import tempfile

faulthandler.enable()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-options-")

import numpy as np                                     # noqa: E402
import soundfile as sf                                 # noqa: E402
import wx                                              # noqa: E402

from dropdeck import audiofile                         # noqa: E402
from dropdeck import board as boardmod                 # noqa: E402
from dropdeck import cabletest                         # noqa: E402
from dropdeck import constants as C                    # noqa: E402
from dropdeck import dialogs                           # noqa: E402
from dropdeck import globalhotkeys                     # noqa: E402
from dropdeck import micinput                          # noqa: E402
from dropdeck import playlist as playlistmod           # noqa: E402
from dropdeck import secrets                           # noqa: E402
from dropdeck import send as sendmod                   # noqa: E402
from dropdeck import streamout                         # noqa: E402
from dropdeck import ui as uimod                       # noqa: E402
from dropdeck.audiofile import CHANNELS                # noqa: E402
from dropdeck.board import Board                       # noqa: E402
from dropdeck.micinput import MicInput                 # noqa: E402
from dropdeck.mixer import Mixer, MixerGroup           # noqa: E402
from dropdeck.playlist import Track                    # noqa: E402

RATE = 48000
CHECKS = []
GUARDS = []
FAILED = []


def check(label, condition, detail=""):
    """A fix: fails on 129a3fd, passes now."""
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
    """One item. A raise is a failed check, so 129a3fd runs to the end."""
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
# registering each one for a moment. Not here: nothing in this file needs it.
uimod.micdiag.taken_elsewhere = lambda keys, own=None: []

CABLE_IN = "CABLE Input (VB-Audio Virtual Cable)"
CABLE_OUT = "CABLE Output (VB-Audio Virtual Cable)"
CARDS = {"Desk": 901, "Phones": 903, CABLE_IN: 911}
uimod.resolve_device = lambda spec: CARDS.get((spec or {}).get("name"))
uimod.resolve_input = lambda spec: None
Mixer._device_rate = staticmethod(lambda device: RATE)
cabletest.capture_for = (lambda name, found=None:
                         CABLE_OUT if name == CABLE_IN else "")
DEFAULT_MIC = ["Microphone (Yeti Stereo Microphone)"]
micinput.default_input_name = lambda: DEFAULT_MIC[0]


def never_open(self, device=None, other_routes=True):
    self.last_error = "not opened in a test"
    return False


MicInput.start = never_open


class QuietGroup(MixerGroup):
    #: Whether the sound card is said to be running, for the pre-flight.
    RUNNING = [True]

    def __init__(self, *args, **kw):
        kw["open_stream"] = False
        super().__init__(*args, **kw)

    @property
    def is_running(self):
        return QuietGroup.RUNNING[0]


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


class FakeStreamer:
    """What start_stream builds, going nowhere: it keeps the titles."""

    made = []

    def __init__(self, bus=None, settings=None, **kw):
        self.bus = bus
        self.settings = settings or {}
        self.processor = None
        self.running = False
        self.state = streamout.CONNECTING
        self.detail = ""
        self.error = ""
        self.on_air_for = 0.0
        self.backlog = 0.0
        self.reconnects = 0
        self.bytes_sent = 0
        self._destination = None
        self.titles = []
        FakeStreamer.made.append(self)

    def set_title(self, title):
        self.titles.append(title)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def set_frame_tap(self, tap):
        return False

    def set_overlay(self, overlay):
        pass

    def wants_video(self):
        return False


class FakeFileDialog:
    """wx.FileDialog, answered: a path, or Cancel when there is none."""

    opened = []
    answer = [None]

    def __init__(self, parent=None, message="", *a, **kw):
        FakeFileDialog.opened.append(message)

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


def preferences(script):
    Scripted.script = staticmethod(script)
    frame._on_settings()


class Keystroke:
    """A key at the hotkey dialog's hook. See tests/test_audit_3_0.py for
    why a real wx.KeyEvent cannot be given a key code from Python."""

    def __init__(self, code, ctrl=False, alt=False, shift=False):
        self.code, self.ctrl, self.alt, self.shift = code, ctrl, alt, shift

    def GetKeyCode(self):
        return self.code

    def AltDown(self):
        return self.alt

    def ControlDown(self):
        return self.ctrl

    def ShiftDown(self):
        return self.shift

    def Skip(self, skip=True):
        pass


class Ear:
    """The frame's speaker: what would have been said."""

    def __init__(self):
        self.said = []
        self.available = True

    def say(self, text, interrupt=True):
        self.said.append(text)


def pump(seconds=0.0):
    app.ProcessPendingEvents()
    app.Yield()
    if seconds > 0:
        wx.CallLater(max(1, int(seconds * 1000)), app.ExitMainLoop)
        app.MainLoop()
        app.ProcessPendingEvents()


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
TMP = tempfile.mkdtemp(prefix="dropdeck-options-files-")


def wav(name, seconds=2.0):
    path = os.path.join(TMP, name + ".wav")
    sf.write(path, np.zeros((int(RATE * seconds), CHANNELS), np.float32), RATE)
    return path


def make_board(name, **fields):
    board = Board()
    board.device_name, board.device_hostapi = "Desk", "Windows WASAPI"
    for key, value in fields.items():
        setattr(board, key, value)
    path = os.path.join(TMP, name + ".json")
    board.save(path)
    return path


START = make_board("Start")
boardmod.remember_board_path(START)
frame = uimod.DropDeckFrame(None)
frame.Show()
pump(0.2)
ear = Ear()
frame.speaker = ear
frame._check_mic_signal = lambda *a, **k: None
ESSENTIAL = C.SPEECH_ESSENTIAL


def hear(action, wait=0.0, level=ESSENTIAL):
    """What reaches the speaker while `action` runs."""
    frame.board.speech_level = level
    frame._menu_closed_at = None
    ear.said.clear()
    action()
    pump(wait)
    return list(ear.said)


def radio(board):
    """A radio station set up and pointed at, with nothing wrong with it."""
    board.stream_name = "Blindside Radio"
    board.stream_host = "stream.example.com"
    board.stream_mount = "/live"
    board.stream_password = "hackme"
    board.live_to = C.LIVE_TO_AUDIO


def video(board):
    board.video_server = "youtube"
    board.video_host = C.RTMP_INGEST["youtube"]
    board.video_key = ""
    board.live_to = C.LIVE_TO_VIDEO


def menu_named(title):
    bar = frame.GetMenuBar()
    return bar.GetMenu(bar.FindMenu(title))


def level_letters(menu):
    """{letter: [labels]} for one open menu level, headers included."""
    found = {}
    for item in menu.GetMenuItems():
        if item.IsSeparator():
            continue
        text = item.GetItemLabel().split(chr(9))[0].replace("&&", "")
        if "&" in text:
            found.setdefault(text[text.index("&") + 1].lower(), []).append(
                item.GetItemLabelText())
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


#: Controls whose label is their own words, not a value.
WORDED = (wx.StaticText, wx.CheckBox, wx.Button, wx.RadioButton, wx.StaticBox)


def page_letters(page):
    """{letter: [labels]} for the access keys one page offers at once."""
    found = {}
    for child in controls(page):
        if not isinstance(child, WORDED):
            continue
        label = child.GetLabel().replace("&&", "")
        if "&" in label and label.index("&") + 1 < len(label):
            found.setdefault(label[label.index("&") + 1].lower(), []).append(
                label)
    return found


def labelled(page, label, kind=None):
    return [c for c in controls(page) if isinstance(c, kind or wx.Window)
            and isinstance(c, WORDED) and c.GetLabel() == label]


#: "Other programs" rather than "the send" since the polish step
#: (test_review_polish item 18).
MIC_OUT_LABEL = ("Send my m&icrophone to streams, recordings and other "
                 "programs")
LISTEN_LABEL = "What I listen &on"
TITLES_AS_LABEL = "Send s&ong titles as"


def real_preferences(page):
    return dialogs.SettingsDialog(frame, frame.board, frame.mixer,
                                  mic=frame.mic, page=page)


# ===========================================================================
heading("0. Nothing says Ctrl+B about the radio station")


def item_0():
    keys = table(frame)
    guard("Ctrl+Shift+B, Ctrl+Shift+W, Ctrl+B and Alt+Shift+B are the keys "
          "they always were",
          keys.get((CTRL_SHIFT, ord("B"))) == uimod.ID_STREAM_STATUS
          and keys.get((CTRL_SHIFT, ord("W"))) == uimod.ID_ROUTING
          and keys.get((wx.ACCEL_CTRL, ord("B"))) == uimod.ID_STREAM_TOGGLE)
    radio(frame.board)

    # a. Ctrl+Shift+B off air.
    said = hear(lambda: post(frame, uimod.ID_STREAM_STATUS))
    check("off air on a radio board, Ctrl+Shift+B says Alt+Shift+B goes live "
          "there", said and said[-1].startswith(
              "Off air. Alt+Shift+B goes live to Blindside Radio"), said)
    check("and not Ctrl+B", said and "Ctrl+B" not in said[-1], said)
    QuietGroup.RUNNING[0] = False
    try:
        said = hear(lambda: post(frame, uimod.ID_STREAM_STATUS))
    finally:
        QuietGroup.RUNNING[0] = True
    check("with something stopping it, it says Alt+Shift+B WOULD go there, "
          "and why not",
          said and said[-1].startswith("Off air. Alt+Shift+B would go to "
                                       "Blindside Radio")
          and "sound card is not running" in said[-1], said)
    video(frame.board)
    said = hear(lambda: post(frame, uimod.ID_STREAM_STATUS))
    guard("on a video board it is still Ctrl+B",
          said and said[-1].startswith("Off air. Ctrl+B would go to "
                                       "YouTube"), said)
    frame._update_status()
    guard("and the status bar says Ctrl+B beside the air state",
          "Off air (Ctrl+B)" in frame.status.GetStatusText(0),
          frame.status.GetStatusText(0))
    radio(frame.board)
    frame._update_status()
    check("on a radio board the status bar says Alt+Shift+B beside it",
          "Off air (Alt+Shift+B)" in frame.status.GetStatusText(0),
          frame.status.GetStatusText(0))

    # b. A saved station, loaded from the On air menu.
    frame.board.stream_stations = []
    radio(frame.board)
    frame.board.save_station()
    frame.board.stream_name = "My Channel"
    video(frame.board)
    frame.board.save_station()
    frame.board.stream_name = "Scratch"
    frame._rebuild_station_menu()
    names = frame.board.station_names()
    said = hear(lambda: post(frame, uimod.ID_STATION_BASE
                             + names.index("Blindside Radio")))
    check("loading the radio station says Alt+Shift+B goes there",
          said and said[-1].startswith("Blindside Radio. Alt+Shift+B goes "
                                       "to Blindside Radio"), said)
    said = hear(lambda: post(frame, uimod.ID_STATION_BASE
                             + names.index("My Channel")))
    guard("loading the video station still says Ctrl+B",
          said and said[-1].startswith("My Channel. Ctrl+B goes to"), said)
    frame.board.live_to = C.LIVE_TO_AUDIO
    frame.streaming = lambda: True
    try:
        said = hear(lambda: post(frame, uimod.ID_STATION_BASE
                                 + names.index("Blindside Radio")))
    finally:
        del frame.streaming
    check("refused while live on the radio, it names Alt+Shift+B to come "
          "off air", said == ["Come off air first, Alt+Shift+B, then change "
                              "station"], said)

    # c. Ctrl+Shift+W on the picture, for a radio presenter.
    radio(frame.board)
    said = hear(lambda: post(frame, uimod.ID_ROUTING))
    check("Ctrl+Shift+W says the radio station, on Alt+Shift+B, takes no "
          "picture", said and "Your radio station, on Alt+Shift+B, takes no "
          "picture" in said[-1], said)
    check("and that the picture goes out with Ctrl+B and into the file with "
          "Ctrl+Shift+R", said and "goes out with Ctrl+B to your video "
          "platform, and into the file with Ctrl+Shift+R" in said[-1], said)
    check("and no longer that Ctrl+B goes to the radio station",
          said and "Ctrl+B goes to your radio" not in said[-1]
          and "switch Ctrl+B over" not in said[-1], said)

    # d. The go live question, which both keys ask.
    prefs = real_preferences(dialogs.SettingsDialog.PAGE_STREAM)
    try:
        tip = prefs.ask_before_live.GetToolTipText()
        label = prefs.ask_before_live.GetLabel()
    finally:
        prefs.Destroy()
    check("the Preferences box's tooltip says Alt+Shift+B asks too",
          "Alt+Shift+B" in tip and "Ctrl+B" in tip, tip)
    # The polish step took Ctrl+B out of the label as well, since both keys
    # ask: test_review_polish item 10. Its A is unchanged.
    guard("its A is as it was",
          label == "S&ay what is going out before going live", label)
    box = dialogs.GoLiveDialog(frame, frame.preflight())
    try:
        tip = box.again.GetToolTipText()
        label = box.again.GetLabel()
    finally:
        box.Destroy()
    check("the go live window's Do not ask again says both keys",
          "Ctrl+B and Alt+Shift+B go straight on the air" in tip, tip)
    guard("its label and its D are as they were",
          label == "&Do not ask again, just go live", label)


section("0", item_0)


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


def item_0_question():
    radio(frame.board)
    frame.board.stream_mic = False
    frame.board.ask_before_live = True
    real = uimod.GoLiveDialog
    uimod.GoLiveDialog = PutItRight
    PutItRight.shown.clear()
    PutItRight.answers[:] = ["stay"]
    try:
        said = hear(lambda: post(frame, uimod.ID_STREAM_TOGGLE_AUDIO))
    finally:
        uimod.GoLiveDialog = real
    guard("Alt+Shift+B asks the same question as Ctrl+B, so the tooltips are "
          "right to say both", len(PutItRight.shown) == 1
          and said and said[-1] == "Staying off air", (PutItRight.shown, said))
    frame.board.stream_mic = True


section("0d", item_0_question)


# ===========================================================================
heading("1. The cue sheet is on the Playlist menu")


def item_1():
    menu = menu_named("Playlist")
    items = [item for item in menu.GetMenuItems()
             if item.GetId() == uimod.ID_CUE_SHEET]
    check("the Playlist menu has the cue sheet, on the key's own id",
          len(items) == 1, len(items))
    item = items[0] if items else None
    check("called Cue sheet, what is coming up, with T and Ctrl+Shift+C",
          item is not None and item.GetItemLabel()
          == "Cue shee&t, what is coming up" + chr(9) + "Ctrl+Shift+C",
          item.GetItemLabel() if item else None)
    accel = item.GetAccel() if item is not None else None
    keys = table(frame)
    check("and the key it shows is the cue sheet's in the table",
          accel is not None and accel.GetFlags() == CTRL_SHIFT
          and accel.GetKeyCode() == ord("C")
          and keys.get((CTRL_SHIFT, ord("C"))) == uimod.ID_CUE_SHEET)
    letters = level_letters(menu)
    check("T is that item's alone on the Playlist menu",
          letters.get("t") == ["Cue sheet, what is coming up"],
          letters.get("t"))
    words = str(frame._app_key_uses().get((ord("C"), CTRL_SHIFT), ""))
    check("the hotkey window names Ctrl+Shift+C by its menu item now",
          "Cue sheet, what is coming up, on the Playlist menu" in words, words)
    post(frame, uimod.ID_CUE_SHEET)
    pump(0.1)
    window = getattr(frame, "cue_window", None)
    guard("choosing it opens the cue sheet", window is not None)
    if window:
        window.Destroy()
        pump(0.1)


section("1", item_1)


# ===========================================================================
heading("2. Add songs to the end is Alt+Shift+A, and a pad that had it keeps it")


def add_songs_item():
    return frame.GetMenuBar().FindItemById(uimod.ID_PL_ADD)


def owners_of(code):
    return [e.GetCommand() for e in frame._accelerators
            if (e.GetFlags(), e.GetKeyCode()) == (ALT_SHIFT, code)]


def advertising(text):
    found = []
    bar = frame.GetMenuBar()

    def walk(menu):
        for item in menu.GetMenuItems():
            if item.GetSubMenu() is not None:
                walk(item.GetSubMenu())
            elif chr(9) in item.GetItemLabel() and item.GetItemLabel().split(
                    chr(9))[1].strip() == text:
                found.append(item.GetItemLabelText())

    for position in range(bar.GetMenuCount()):
        walk(bar.GetMenu(position))
    return found


def pad_board(name, holders):
    """A board whose bank 4 pads hold these Alt+Shift letters."""
    board = Board()
    board.device_name, board.device_hostapi = "Desk", "Windows WASAPI"
    for n, (letter, sound) in enumerate(holders):
        pad = board.bank_slots(C.BANK_MISC)[n]
        pad.filepath = wav(sound, 0.5)
        pad.name = sound
        pad.custom_hotkey = "Alt+Shift+" + letter
        pad.key_code = ord(letter)
        pad.modifiers = ALT_SHIFT
    path = os.path.join(TMP, name + ".json")
    board.save(path)
    return path


def item_2():
    frame._open_board(START)
    table(frame)
    check("Alt+Shift+A is in the table, for Add songs to the end and nothing "
          "else", owners_of(ord("A")) == [uimod.ID_PL_ADD], owners_of(ord("A")))
    check("and no menu item but Add songs advertises it",
          advertising("Alt+Shift+A") == ["Add songs to the end..."],
          advertising("Alt+Shift+A"))
    item = add_songs_item()
    accel = item.GetAccel() if item is not None else None
    check("its label carries the key after a tab, and its A",
          item is not None and item.GetItemLabel()
          == "&Add songs to the end..." + chr(9) + "Alt+Shift+A",
          item.GetItemLabel() if item else None)
    check("which is the key the menu binds",
          accel is not None and accel.GetFlags() == ALT_SHIFT
          and accel.GetKeyCode() == ord("A"))

    real_dialog = wx.FileDialog
    wx.FileDialog = FakeFileDialog
    try:
        FakeFileDialog.opened.clear()
        FakeFileDialog.answer[0] = None
        post(frame, uimod.ID_PL_ADD)
        guard("Add songs still opens the file window",
              FakeFileDialog.opened == ["Add songs to the running order"],
              FakeFileDialog.opened)
        frame.board.playlist.clear()
        frame.playlist_panel.refresh()
        FakeFileDialog.answer[0] = wav("Song for the end", 1.0)
        post(frame, uimod.ID_PL_ADD)
        guard("and puts what is chosen at the end",
              [t.display_name for t in frame.board.playlist]
              == ["Song for the end"])
    finally:
        wx.FileDialog = real_dialog
        FakeFileDialog.answer[0] = None
    frame.show_view(uimod.VIEW_BOARD)

    # A new bank 4 key is refused while no pad holds it.
    pad = frame.board.bank_slots(C.BANK_MISC)[0]
    pad.filepath = wav("Pad", 0.5)
    taken = frame._hotkey_map(exclude=pad.index)
    keys = dialogs.AssignHotkeyDialog(frame, pad, taken)
    try:
        keys._on_key(Keystroke(ord("A"), alt=True, shift=True))
        check("the hotkey window refuses Alt+Shift+A for a bank 4 pad",
              keys.result[0] is None, keys.result)
        check("saying it is Add songs to the end, on the Playlist menu",
              "Alt+Shift+A is Add songs to the end, on the Playlist menu"
              in keys.warning.GetLabel(), keys.warning.GetLabel())
    finally:
        keys.Destroy()
    kept = frame._accelerators
    frame._accelerators = [e for e in kept
                           if e.GetCommand() != uimod.ID_PL_ADD]
    try:
        words = str(frame._app_key_uses().get((ord("A"), ALT_SHIFT), ""))
    finally:
        frame._accelerators = kept
    check("_app_key_uses finds it on the menu label alone, with the table "
          "entry taken out", "Add songs to the end, on the Playlist menu"
          in words, words)
    pad.clear()

    # A board whose pad already had it.
    frame._open_board(pad_board("Applause on A", [("A", "Applause")]))
    holder = frame.board.bank_slots(C.BANK_MISC)[0]
    mine = uimod.ID_SLOT_BASE + holder.index
    guard("the pad keeps Alt+Shift+A: it is the only one in the table",
          owners_of(ord("A")) == [mine], owners_of(ord("A")))
    label = add_songs_item().GetItemLabel()
    # Without "No key," and "on this board" since the polish step
    # (test_review_polish item 7).
    check("Add songs says it has no key, and whose the key is",
          chr(9) not in label and label == "&Add songs to the end... "
          "Alt+Shift+A plays Applause", label)
    guard("and the key map the hotkey window checks does not claim it",
          "add songs" not in str(frame._app_key_uses().get(
              (ord("A"), ALT_SHIFT), "")).lower())
    taken = frame._hotkey_map(exclude=holder.index)
    keys = dialogs.AssignHotkeyDialog(frame, holder, taken)
    try:
        keys._on_key(Keystroke(ord("A"), alt=True, shift=True))
        guard("so the pad can still be given its own key again",
              keys.result[0] == ord("A"), keys.result)
    finally:
        keys.Destroy()
    said = hear(frame._startup_line)
    lines = [text for text in said if "Alt+Shift+A" in text]
    check("the startup line says so, once",
          len(lines) == 1 and lines[0].count("Alt+Shift+A") == 1
          and "Alt+Shift+A plays Applause on this board, so Add songs to the "
          "end has no key. It is on the Playlist menu" in lines[0], said)
    real_dialog = wx.FileDialog
    wx.FileDialog = FakeFileDialog
    try:
        FakeFileDialog.opened.clear()
        post(frame, uimod.ID_PL_ADD)
    finally:
        wx.FileDialog = real_dialog
    guard("the menu item still adds songs",
          FakeFileDialog.opened == ["Add songs to the running order"],
          FakeFileDialog.opened)
    frame.show_view(uimod.VIEW_BOARD)

    # Both keys held, on one board: one helper answers for both.
    frame._open_board(pad_board("Both held", [("A", "Applause"),
                                              ("P", "Pling")]))
    said = hear(frame._startup_line)
    joined = " ".join(said)
    check("with both keys on pads, the startup line says each once",
          joined.count("Alt+Shift+A plays Applause") == 1
          and joined.count("Alt+Shift+P plays Pling") == 1, said)
    commands = {e.GetCommand() for e in frame._accelerators}
    guard("and neither command is in the table",
          uimod.ID_PL_ADD not in commands
          and uimod.ID_ONAIR_COMPARE not in commands)
    check("and both labels say whose key it is",
          "Alt+Shift+A plays Applause" in add_songs_item()
          .GetItemLabel()
          and "Alt+Shift+P plays Pling" in frame.onair_item
          .GetItemLabel(),
          (add_songs_item().GetItemLabel(), frame.onair_item.GetItemLabel()))
    check("the two compare helpers became one for both keys",
          not hasattr(uimod.DropDeckFrame, "_compare_key_holder")
          and not hasattr(uimod.DropDeckFrame, "_compare_key_note"))

    frame._open_board(START)
    check("a board where no pad has it gets the key back, label and all",
          owners_of(ord("A")) == [uimod.ID_PL_ADD]
          and add_songs_item().GetItemLabel().endswith(chr(9)
                                                       + "Alt+Shift+A"))


section("2", item_2)


# ===========================================================================
heading("3. Send my microphone is on the Microphone page")


def mic_page_box(dialog):
    found = labelled(dialog.tabs.GetPage(dialog.PAGE_MIC), MIC_OUT_LABEL,
                     wx.CheckBox)
    return found[0] if found else None


def item_3():
    prefs = real_preferences(dialogs.SettingsDialog.PAGE_MIC)
    try:
        mic_page = prefs.tabs.GetPage(prefs.PAGE_MIC)
        stream_page = prefs.tabs.GetPage(prefs.PAGE_STREAM)
        box = mic_page_box(prefs)
        check("the box is on the Microphone page, with its new words",
              box is not None)
        check("and it is the board's stream_mic, the control OK reads",
              box is not None and box is prefs.stream_mic)
        # A check box: since the polish step a static text where the box was
        # says where it went (test_review_polish item 6).
        old = [c.GetLabel() for c in controls(stream_page)
               if isinstance(c, wx.CheckBox)
               and "microphone" in c.GetLabel().replace("&", "").lower()]
        check("Audio streaming no longer has it", not old, old)
        letters = page_letters(mic_page)
        check("I is still its letter, and nothing else on the Microphone "
              "page has I", letters.get("i") == [MIC_OUT_LABEL],
              letters.get("i"))
        twice = {k: v for k, v in letters.items() if len(v) > 1}
        guard("no two controls on the Microphone page share a letter",
              not twice, twice)
        twice = {k: v for k, v in page_letters(stream_page).items()
                 if len(v) > 1}
        guard("nor on Audio streaming", not twice, twice)
    finally:
        prefs.Destroy()

    # Saved by OK, from where it is now.
    frame.board.stream_mic = True
    found = []

    def untick(dialog):
        box = mic_page_box(dialog)
        found.append(box is not None)
        if box is None:
            return wx.ID_CANCEL
        box.SetValue(False)
        return wx.ID_OK

    preferences(untick)
    check("unticking it on the Microphone page and OK keeps the microphone "
          "out", found == [True] and frame.board.stream_mic is False,
          (found, frame.board.stream_mic))

    def tick(dialog):
        box = mic_page_box(dialog)
        found.append(box is not None)
        if box is None:
            return wx.ID_CANCEL
        box.SetValue(True)
        return wx.ID_OK

    preferences(tick)
    check("and ticking it there puts it back on",
          found == [True, True] and frame.board.stream_mic is True, found)

    # A station loaded inside Preferences fills it at once; Cancel undoes it.
    frame.board.stream_stations = []
    radio(frame.board)
    frame.board.stream_name = "Quiet Station"
    frame.board.stream_mic = False
    frame.board.save_station()
    frame.board.stream_name = "Loud Station"
    frame.board.stream_mic = True
    frame.board.save_station()
    seen = []

    def pick_quiet(answer):
        def script(dialog):
            names = dialog.stream_picker.GetStrings()
            dialog.stream_picker.SetSelection(names.index("Quiet Station"))
            dialog._on_pick_station(None)
            box = mic_page_box(dialog)
            seen.append(None if box is None else box.GetValue())
            return answer
        return script

    preferences(pick_quiet(wx.ID_CANCEL))
    check("loading a station inside Preferences sets the Microphone page box "
          "at once", seen == [False], seen)
    guard("and Cancel puts the board's own back",
          frame.board.stream_mic is True
          and frame.board.stream_name == "Loud Station")
    preferences(pick_quiet(wx.ID_OK))
    guard("while OK keeps the station's",
          frame.board.stream_mic is False
          and frame.board.stream_name == "Quiet Station")
    entry = frame.board.station_settings()
    guard("a saved station still carries stream_mic, as the board's own",
          "stream_mic" in boardmod.STATION_FIELDS
          and entry["stream_mic"] is False)

    # The refusal of step 1, from the new place.
    frame.board.send_device_name = CABLE_IN
    frame.board.send_device_hostapi = "Windows WASAPI"
    frame.board.send_on = True
    frame.board.stream_mic = False
    guard("a send runs", frame._start_send(quiet=True) and frame.sending())
    DEFAULT_MIC[0] = CABLE_OUT
    frame.mic.stream = object()                # open, as far as the frame knows
    found.clear()
    try:
        def tick_it(dialog):
            box = mic_page_box(dialog)
            found.append(box is not None)
            if box is not None:
                box.SetValue(True)
            return wx.ID_OK

        # Said once the window coming back has been read, since the polish
        # step (test_review_polish item 12), so it is waited for.
        said = hear(lambda: preferences(tick_it),
                    wait=(C.AFTER_MENU_SPEECH_MS + 300) / 1000.0)
    finally:
        frame.mic.stream = None
        DEFAULT_MIC[0] = "Microphone (Yeti Stereo Microphone)"
    check("ticking it on the Microphone page with the microphone on the "
          "send's own cable is refused, and said",
          found == [True] and frame.board.stream_mic is False
          and any("back into itself" in text for text in said), (found, said))

    # Sentences that say where it is.
    report = frame.send_report()
    check("the send's report names the Microphone page, not Audio streaming",
          "Microphone page" in report and "Audio streaming" not in report,
          report)
    recorded = frame.what_is_in_the_recording()
    check("and so does what is in a recording",
          "Microphone page" in recorded
          and "Audio streaming" not in recorded, recorded)
    frame._stop_send(quiet=True)
    frame.board.send_on = False

    # Put it right on the go live warning opens the Microphone page.
    report = frame.preflight()
    notes = [note for note in report.notes
             if note.text.startswith("Your microphone is not on the air")]
    check("the warning that the microphone is not on the air points at the "
          "Microphone page", notes
          and notes[0].fix == getattr(C, "FIX_MIC", "not there"),
          [n.fix for n in notes])
    real = uimod.GoLiveDialog
    uimod.GoLiveDialog = PutItRight
    PutItRight.shown.clear()
    PutItRight.answers[:] = ["fix", "stay"]
    Scripted.pages.clear()
    Scripted.script = staticmethod(lambda dialog: wx.ID_CANCEL)
    try:
        post(frame, uimod.ID_STREAM_TOGGLE_AUDIO)
    finally:
        uimod.GoLiveDialog = real
    check("and Put it right, pressed, opens Preferences on it",
          Scripted.pages == [dialogs.SettingsDialog.PAGE_MIC],
          (Scripted.pages, PutItRight.shown))
    frame.board.stream_mic = True


section("3", item_3)


# ===========================================================================
heading("4. Hear yourself through is What I listen on")


def item_4():
    prefs = real_preferences(dialogs.SettingsDialog.PAGE_MIC)
    try:
        mic_page = prefs.tabs.GetPage(prefs.PAGE_MIC)
        order = list(mic_page.GetChildren())
        statics = labelled(mic_page, LISTEN_LABEL, wx.StaticText)
        check("its label is What I listen on, with the O it had",
              len(statics) == 1, len(statics))
        check("built right before the choice, so it is what a screen reader "
              "reads", statics and prefs.mic_output in order
              and order.index(prefs.mic_output)
              == order.index(statics[0]) + 1)
        check("and its name is the same words",
              prefs.mic_output.GetName() == "What I listen on",
              prefs.mic_output.GetName())
        tip = prefs.mic_output.GetToolTipText()
        check("its tooltip says it carries the beep, auditioning and the "
              "whole show", "beep" in tip and "audition" in tip
              and "whole show" in tip, tip)
        # And since the polish step the monitoring box is "Hear my own voice
        # there" (test_review_polish item 17), so none is left at all.
        left = [c.GetLabel() for c in controls(mic_page)
                if isinstance(c, WORDED)
                and "Hear yourself thr" in c.GetLabel().replace("&", "")]
        check("no Hear yourself through is left on the page", left == [],
              left)
        at = order.index(prefs.mic_output)
        before = order[at - 1].GetLabel() if at > 0 else ""
        box = prefs.mic_monitor.GetLabel()
        guard("the choice's label and the monitoring box have a letter each, "
              "O and H, never the same one",
              "&o" in before and box.startswith("&H"), (before, box))
        output = [c.GetLabel() for c in controls(
            prefs.tabs.GetPage(prefs.PAGE_OUTPUT))
            if isinstance(c, wx.StaticText) and "Microphone tab" in c.GetLabel()]
        check("the Output page sends you to it by its new name",
              output and "under What I listen on" in output[0], output)
    finally:
        prefs.Destroy()
    check("and F1 names it, where F1 quoted the old one",
          "Preferences, Microphone, What I listen on is what YOU hear"
          in C.KEYBOARD_HELP
          and "Hear yourself through is what YOU hear" not in C.KEYBOARD_HELP)


section("4", item_4)


# ===========================================================================
heading("5. The ducking box says what it ducks")


def item_5():
    prefs = real_preferences(dialogs.SettingsDialog.PAGE_SOUND)
    try:
        label = prefs.duck_on.GetLabel()
        letters = page_letters(prefs.tabs.GetPage(prefs.PAGE_SOUND))
    finally:
        prefs.Destroy()
    check("it is Duck the music under sounds, drops and the microphone",
          label == "&Duck the music under sounds, drops and the microphone",
          label)
    guard("D, and nothing else on Sounds and beds has D",
          letters.get("d") == [label], letters.get("d"))
    item = frame.GetMenuBar().FindItemById(uimod.ID_DUCK)
    accel = item.GetAccel() if item is not None else None
    was = frame.mixer.ducking
    post(frame, uimod.ID_DUCK)
    guard("Ctrl+D is still the same switch, on the Sounds menu",
          accel is not None and accel.GetFlags() == wx.ACCEL_CTRL
          and accel.GetKeyCode() == ord("D") and frame.mixer.ducking != was)
    post(frame, uimod.ID_DUCK)


section("5", item_5)


# ===========================================================================
heading("6. The status bar says the state first")


def item_6():
    radio(frame.board)
    frame._update_status()
    text = frame.status.GetStatusText(0)
    parts = text.split("   ")
    check("it starts with the microphone", text.startswith("Mic off (Ctrl+M)"),
          text)
    check("then whether you are on air",
          len(parts) > 1 and parts[1].startswith("Off air"), parts)
    guard("and the volumes and ducking are all still there",
          all(word in text for word in ("Sound ", "Beds ", "Playlist ",
                                        "Ducking ")), text)
    frame.board.record_folder = tempfile.mkdtemp(prefix="dropdeck-opt-rec-")
    started = frame.start_recording()
    try:
        frame._update_status()
        text = frame.status.GetStatusText(0)
        check("RECORDING comes before the volumes",
              started and "RECORDING (Ctrl+R)" in text
              and text.index("RECORDING") < text.index("Sound "), text)
    finally:
        frame.stop_recording(quiet=True)
    frame.send = FakeSend()
    try:
        frame._update_status()
        text = frame.status.GetStatusText(0)
        check("and so does SENDING", "SENDING (Alt+Shift+O)" in text
              and text.index("SENDING") < text.index("Sound "), text)
    finally:
        frame.send = None
    frame._update_status()
    readout = frame.status.GetStatusText(0)
    frame.announce("A sentence")
    guard("announcements still go to the second field and leave the first",
          frame.status.GetStatusText(1) == "A sentence"
          and frame.status.GetStatusText(0) == readout,
          frame.status.GetStatusText(1))


section("6", item_6)


# ===========================================================================
heading("7. Ctrl+S on a board that was never named asks for a name")


def item_7():
    item = frame.GetMenuBar().FindItemById(wx.ID_SAVE)
    guard("Ctrl+S is Save board, on the File menu",
          item is not None
          and item.GetItemLabel() == "&Save board" + chr(9) + "Ctrl+S")
    real_dialog = wx.FileDialog
    wx.FileDialog = FakeFileDialog
    try:
        # File, New.
        post(frame, wx.ID_NEW)
        pump(0.1)
        home = frame.board.path
        guard("File, New gives the board a file of its own, not yet written",
              os.path.basename(home) == "New board.json"
              and not os.path.exists(home), home)
        frame.board.slots[0].filepath = wav("New one", 0.5)
        frame._touch()
        FakeFileDialog.opened.clear()
        FakeFileDialog.answer[0] = None
        said = hear(lambda: post(frame, wx.ID_SAVE))
        check("Ctrl+S on it opens Save board as",
              FakeFileDialog.opened == ["Save board as"],
              FakeFileDialog.opened)
        check("and Cancel writes nothing, and says no dot json",
              not os.path.exists(home)
              and not any(".json" in text for text in said), said)
        named = os.path.join(TMP, "My show.json")
        FakeFileDialog.opened.clear()
        FakeFileDialog.answer[0] = named
        post(frame, wx.ID_SAVE)
        check("a name chosen there is where it is saved, and New board.json "
              "is never written",
              os.path.exists(named) and boardmod.same_path(frame.board.path,
                                                           named)
              and not os.path.exists(home))
        FakeFileDialog.opened.clear()
        frame.board.slots[1].filepath = wav("Another", 0.5)
        frame._touch()
        post(frame, wx.ID_SAVE)
        check("once named, Ctrl+S saves where it is, with no window",
              not FakeFileDialog.opened and os.path.exists(named)
              and Board.load(named).slots[1].filepath.endswith("Another.wav"),
              FakeFileDialog.opened)

        # File, Load the demo pack.
        post(frame, uimod.ID_DEMO)
        pump(0.1)
        FakeFileDialog.opened.clear()
        FakeFileDialog.answer[0] = None
        post(frame, wx.ID_SAVE)
        check("the demo pack's board asks for a name too",
              FakeFileDialog.opened == ["Save board as"]
              and os.path.basename(frame.board.path) == "Demo board.json",
              (FakeFileDialog.opened, frame.board.path))

        # File, Import.
        bank = make_board("An old bank", stream_name="Old")
        FakeFileDialog.answer[0] = bank
        post(frame, uimod.ID_IMPORT)
        pump(0.1)
        FakeFileDialog.opened.clear()
        FakeFileDialog.answer[0] = None
        post(frame, wx.ID_SAVE)
        check("and so does an imported one",
              FakeFileDialog.opened == ["Save board as"]
              and os.path.basename(frame.board.path) == "An old bank.json"
              and os.path.dirname(frame.board.path)
              == boardmod.config_dir(),
              (FakeFileDialog.opened, frame.board.path))

        # A board somebody opened.
        opened = make_board("Opened show")
        frame._open_board(opened)
        frame.board.slots[2].filepath = wav("Third", 0.5)
        frame._touch()
        FakeFileDialog.opened.clear()
        post(frame, wx.ID_SAVE)
        guard("an opened board saves where it is, with no window",
              not FakeFileDialog.opened
              and Board.load(opened).slots[2].filepath.endswith("Third.wav"),
              FakeFileDialog.opened)
    finally:
        wx.FileDialog = real_dialog
        FakeFileDialog.answer[0] = None
    frame._open_board(START)


section("7", item_7)


# ===========================================================================
heading("8. Send song titles as")


def tagged(name, artist="Abba", title="Dancing Queen", album="Arrival"):
    """A FLAC with real tags, so mutagen reads them as it would a song."""
    from mutagen.flac import FLAC
    path = os.path.join(TMP, name + ".flac")
    sf.write(path, np.zeros((RATE, CHANNELS), np.float32), RATE,
             format="FLAC", subtype="PCM_16")
    song = FLAC(path)
    for key, value in (("artist", artist), ("title", title),
                       ("album", album)):
        if value:
            song[key] = value
    song.save()
    return path


def station_title(track, form):
    found = getattr(playlistmod, "station_title", None)
    return found(track, form) if found is not None else None


def drain_metadata(seconds=20.0):
    """Run the background pass to a standstill, as test_feedback_2_6 does:
    in the app one pass chains the next from the window's thread, and here
    that chaining is done by hand."""
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        thread = frame._metadata_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
            continue
        pump(0.05)
        frame._metadata_thread = None
        if not frame.board.playlist.needs_metadata():
            return True
        started = frame.scan_playlist_metadata()
        if started is None:
            return False
        started.join(timeout=seconds)
    return False


FORMS = (getattr(C, "TITLE_BY_ARTIST", "title_by_artist"),
         getattr(C, "ARTIST_TITLE", "artist_title"),
         getattr(C, "ARTIST_TITLE_ALBUM", "artist_title_album"))


def song_track(album="Arrival", **fields):
    """A track as the tags left it. The album is set afterwards, so the
    checks below each fail on their own on a tree with no album at all."""
    track = Track(**fields)
    track.album = album
    return track


def item_8_words():
    by, plain, album = FORMS
    song = song_track(filepath="dq.flac", artist="Abba",
                      title="Dancing Queen")
    check("Title by Artist is what a station was always sent",
          station_title(song, by) == "Dancing Queen by Abba"
          == song.display_name, station_title(song, by))
    check("Artist - Title", station_title(song, plain)
          == "Abba - Dancing Queen", station_title(song, plain))
    check("Artist - Title - Album", station_title(song, album)
          == "Abba - Dancing Queen - Arrival", station_title(song, album))
    no_album = song_track(album="", filepath="dq.flac", artist="Abba",
                          title="Dancing Queen")
    check("no album leaves no hyphen hanging",
          station_title(no_album, album) == "Abba - Dancing Queen",
          station_title(no_album, album))
    no_artist = song_track(filepath="dq.flac", artist="",
                           title="Dancing Queen")
    check("no artist is the title alone, or the title and the album",
          station_title(no_artist, plain) == "Dancing Queen"
          and station_title(no_artist, album) == "Dancing Queen - Arrival",
          (station_title(no_artist, plain), station_title(no_artist, album)))
    renamed = song_track(filepath="dq.flac", name="Station ident",
                         artist="Abba", title="Dancing Queen")
    check("a name typed for the track is all of it, every way round",
          {station_title(renamed, form) for form in FORMS}
          == {"Station ident"})
    bare = song_track(filepath=r"C:\music\Abba - Dancing Queen.mp3",
                      artist="Abba", title="")
    check("no title tag goes by the file name alone, which has the artist",
          {station_title(bare, form) for form in FORMS}
          == {"Abba - Dancing Queen"},
          {station_title(bare, form) for form in FORMS})
    check("nothing playing is nothing sent", station_title(None, album) == "")
    check("an unknown way round is the default",
          station_title(song, "shouting") == "Dancing Queen by Abba")
    sent = station_title(song, album) or ""
    check("the hyphen is the plain one, and there is no other dash",
          " - " in sent and "\u2013" not in sent and "\u2014" not in sent
          and all(ord(ch) < 128 for ch in sent), repr(sent))
    labels = dict(getattr(C, "TITLE_FORMAT_LABELS", {}))
    check("each choice reads out a song worked through",
          len(labels) == 3 and all(", as in " in labels.get(form, "")
                                   for form in FORMS)
          and labels.get(by, "").startswith("Title by Artist")
          and labels.get(album, "").startswith("Artist - Title - Album"),
          labels)


section("8a", item_8_words)


def item_8_tags():
    by, plain, album = FORMS
    path = tagged("Dancing Queen")
    check("the album comes out of the file with the artist and the title",
          audiofile.tags(path).get("album") == "Arrival",
          audiofile.tags(path))
    frame.board.playlist.clear()
    frame.playlist_panel.refresh()
    frame.playlist_panel.add_paths([path])
    added = frame.board.playlist[0]
    check("a song put in has its album, read with the other two",
          getattr(added, "album", None) == "Arrival",
          getattr(added, "album", None))
    # A track saved before the album was read: its artist and title are
    # what the running order file said, and must stay so.
    old = Track.from_dict({"filepath": path, "duration": 1.0,
                           "tail_silence": 0.0,
                           "artist": "ABBA, from the M3U",
                           "title": "Dancing Queen"})
    frame.board.playlist.tracks.append(old)
    check("the background pass looks at it once more",
          old in frame.board.playlist.needs_metadata())
    drain_metadata()
    check("and fills in the album alone",
          getattr(old, "album", None) == "Arrival"
          and old.artist == "ABBA, from the M3U"
          and old.title == "Dancing Queen",
          (getattr(old, "album", None), old.artist, old.title))
    guard("after which there is nothing left to look at",
          old not in frame.board.playlist.needs_metadata())
    again = Track.from_dict(old.to_dict())
    check("and the album is saved with the track",
          getattr(again, "album", None) == "Arrival")

    # The board's choice, through a file as it really travels.
    saved = Board()
    saved.stream_title_format = album
    where = os.path.join(TMP, "Titles.json")
    saved.save(where)
    with open(where, encoding="utf-8") as handle:
        data = json.load(handle)
    back = Board.load(where)
    check("the choice is saved with the board as stream_title_format",
          data.get("stream_title_format") == album
          and getattr(back, "stream_title_format", None) == album,
          data.get("stream_title_format"))

    def loaded(value):
        changed = dict(data)
        if value is None:
            changed.pop("stream_title_format", None)
        else:
            changed["stream_title_format"] = value
        with open(where, "w", encoding="utf-8") as handle:
            json.dump(changed, handle)
        return getattr(Board.load(where), "stream_title_format", None)

    check("an unknown value is the default", loaded("shouting") == by)
    check("and so is none at all, a board from before",
          loaded(None) == by)
    check("and the value a Mac board carries is read as it is, not dropped",
          loaded(plain) == plain)


section("8b", item_8_tags)


def title_choice(dialog):
    page = dialog.tabs.GetPage(dialog.PAGE_STREAM)
    found = [c for c in controls(page) if isinstance(c, wx.Choice)
             and c.GetName() == "Send song titles as"]
    return found[0] if found else None


def item_8_preferences():
    by, plain, album = FORMS
    frame.board.stream_title_format = plain
    prefs = real_preferences(dialogs.SettingsDialog.PAGE_STREAM)
    try:
        page = prefs.tabs.GetPage(prefs.PAGE_STREAM)
        choice = title_choice(prefs)
        check("Send song titles as is on the Audio streaming page",
              choice is not None)
        order = list(page.GetChildren())
        statics = labelled(page, TITLES_AS_LABEL, wx.StaticText)
        check("its label, with O, is built right before it",
              choice is not None and len(statics) == 1
              and order.index(choice) == order.index(statics[0]) + 1)
        check("and right after Send the track title",
              statics and order.index(statics[0])
              == order.index(prefs.stream_titles) + 1)
        check("three choices, in order, each with its example",
              choice is not None and choice.GetStrings()
              == [C.TITLE_FORMAT_LABELS[form] for form in FORMS],
              choice.GetStrings() if choice else None)
        check("it shows the board's choice", choice is not None
              and choice.GetSelection() == 1)
        letters = page_letters(page)
        check("O is its letter alone on that page",
              letters.get("o") == [TITLES_AS_LABEL], letters.get("o"))
    finally:
        prefs.Destroy()
    found = []

    def pick(index, answer):
        def script(dialog):
            choice = title_choice(dialog)
            found.append(choice is not None)
            if choice is None:
                return wx.ID_CANCEL
            choice.SetSelection(index)
            return answer
        return script

    preferences(pick(2, wx.ID_OK))
    check("OK keeps it", found == [True]
          and frame.board.stream_title_format == album)
    found.clear()
    preferences(pick(0, wx.ID_CANCEL))
    check("Cancel does not", found == [True]
          and frame.board.stream_title_format == album)


section("8c", item_8_preferences)


def item_8_station():
    by, plain, album = FORMS
    path = tagged("Dancing Queen, to air")
    frame.board.playlist.clear()
    frame.playlist_panel.refresh()
    frame.playlist_panel.add_paths([path])
    radio(frame.board)
    frame.board.stream_titles = True
    frame.board.stream_title_format = album
    guard("the playlist is playing it", frame.play_playlist(0)
          and frame.player.current is frame.board.playlist[0])
    calls = []
    real_tags = playlistmod.audiofile.tags

    def counted(found_path):
        calls.append(found_path)
        return real_tags(found_path)

    frame.streamer = FakeStreamer()
    frame.streamer.running = True
    playlistmod.audiofile.tags = counted
    try:
        frame._on_player_tick(None)
    finally:
        playlistmod.audiofile.tags = real_tags
    sent = frame.streamer.titles
    check("each tick hands the station the board's order",
          sent and sent[-1] == "Abba - Dancing Queen - Arrival", sent)
    guard("and the tick reads no file to do it, the tags are already held",
          not calls, calls)
    frame.board.stream_title_format = by
    frame._on_player_tick(None)
    guard("Title by Artist is what it always sent",
          sent[-1] == "Dancing Queen by Abba", sent)
    frame.board.stream_titles = False
    before = len(sent)
    frame._on_player_tick(None)
    guard("and nothing is handed over with Send the track title off",
          len(sent) == before, sent)
    frame.streamer = None

    # Ctrl+B's first title goes the same way.
    real = streamout.Streamer
    streamout.Streamer = FakeStreamer
    FakeStreamer.made.clear()
    try:
        frame.board.stream_titles = True
        frame.board.stream_title_format = plain
        frame.start_stream()
        first = FakeStreamer.made[-1].titles if FakeStreamer.made else []
        frame.stop_stream(quiet=True)
        check("going live hands over the first title the same way",
              first and first[0] == "Abba - Dancing Queen", first)
        frame.board.stream_titles = False
        frame.start_stream()
        first = FakeStreamer.made[-1].titles if FakeStreamer.made else []
        frame.stop_stream(quiet=True)
        check("and with Send the track title off, it hands over none",
              first == [""], first)
        frame.board.stream_titles = True
        video(frame.board)
        frame.board.video_key = "a-key"
        title = frame._station_title() if hasattr(
            frame, "_station_title") else frame._now_playing_title()
        guard("the video platform's card keeps the name the picture uses",
              title == "Dancing Queen by Abba", title)
        frame.board.video_key = ""
    finally:
        streamout.Streamer = real
    frame.stop_playlist(quiet=True)
    radio(frame.board)


section("8d", item_8_station)


# ---------------------------------------------------------------------------
try:
    frame.stop_playlist(quiet=True)
    frame.stop_background_work()
except Exception:
    pass
try:
    frame.mixer.close()
except Exception:
    pass
frame.board.dirty = False
frame.Destroy()
shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
print("%d/%d guards passed" % (sum(GUARDS), len(GUARDS)))
if FAILED:
    print("FAILED:")
    for line in FAILED:
        print("  " + line)
sys.exit(1 if FAILED else 0)
