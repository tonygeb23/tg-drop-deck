"""Review of 24 November 2026, Area 1: wiring.

    python tools/run_private.py tests/test_review_wiring.py

Every check here fails on 3.10.1 and passes on the fix. The faults were all
the same shape: a setting or a key that reached the board and stopped there.
Opening a board switched its pads and left its sound cards, sources, send,
global hotkeys, folder pads, tabs and menus on the board before it. Rename in
Source control raised. The pads were dead while the cue sheet had focus.
Preferences changed things a running show never heard about, and could move
where Ctrl+B goes under a live stream.

Nothing here opens a sound card, a microphone or a camera. The mixer runs
with no stream, the device names resolve to made up numbers, the send and
the global hotkeys are stand-ins, and the credential store is never read.
Keys and menu items are proved through their BINDINGS: the event is posted
to the window that really receives it.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-wiring-")

import numpy as np
import soundfile as sf
import wx

from dropdeck import board as boardmod
from dropdeck import constants as C
from dropdeck import dialogs
from dropdeck import globalhotkeys
from dropdeck import mixer as mixermod
from dropdeck import picturefeed
from dropdeck import secrets
from dropdeck import send as sendmod
from dropdeck import sources as sourcesmod
from dropdeck import ui as uimod
from dropdeck.board import Board

CHECKS = []
RATE = 48000


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" and not condition else ""))


def heading(text):
    print("\n" + text)


def attempt(label, action):
    """Run something that the old code raised in, and count the raise."""
    try:
        return action()
    except Exception as exc:
        check(label + " (raised %s)" % type(exc).__name__, False)
        return None


# ------------------------------------------------------------- stand-ins --
app = wx.App(False)
BOXES = []


def fake_box(message, caption="", style=0, parent=None, *rest, **kw):
    BOXES.append((caption, message))
    return wx.OK


wx.MessageBox = fake_box

# The credential store is Tony's. Nothing here reads or writes it.
secrets.fetch = (lambda name, prefix=None:
                 "test-key" if prefix == secrets.VISION_PREFIX else None)
secrets.store = lambda *a, **kw: True
secrets.forget = lambda *a, **kw: None

#: Sound cards by name. Nothing is opened: the mixer runs with no stream.
CARDS = {"Desk A": 901, "Beds A": 902, "Phones A": 903, "Desk B": 904,
         "Drops B": 905, "Phones B": 906, "Cable A": 911}


def fake_resolve(spec):
    return CARDS.get((spec or {}).get("name"))


uimod.resolve_device = fake_resolve
# No input is ever found, so no source and no microphone can open.
uimod.resolve_input = lambda spec: None
sourcesmod.resolve_input = lambda spec: None
uimod.DropDeckFrame._start_update_check = lambda self: None


class QuietGroup(mixermod.MixerGroup):
    def __init__(self, *args, **kw):
        kw["open_stream"] = False
        super().__init__(*args, **kw)


uimod.MixerGroup = QuietGroup


class FakeHotkeys:
    """Global hotkeys that register nothing with Windows.

    Refused the way Windows refuses them: a combination another program
    holds (TAKEN), and the second pad on a combination this one already
    registered. And reported the way the real listener reports them, to the
    UI thread, where the frame used to put up a box.
    """

    TAKEN = {"Ctrl+Alt+F12"}

    def __init__(self, on_fire=None, on_problem=None):
        self.enabled = False
        self.bindings = {}
        self.failures = {}
        self.on_problem = on_problem or (lambda message: None)

    def _register(self):
        self.failures = {}
        held = set()
        for index, text in sorted(self.bindings.items()):
            if text in self.TAKEN or text in held:
                self.failures[index] = text
            else:
                held.add(text)
        if self.failures:
            wx.CallAfter(self.on_problem,
                         "These global hotkeys could not be registered, most "
                         "likely because another program already uses them: "
                         "%s" % ", ".join(sorted(set(self.failures.values()))))

    def set_bindings(self, bindings):
        self.bindings = dict(bindings)
        if self.enabled:
            self._register()

    def start(self):
        if not self.enabled:
            self.enabled = True
            self._register()
        return True

    def stop(self):
        self.enabled = False

    def toggle(self):
        if self.enabled:
            self.stop()
        else:
            self.start()
        return self.enabled

    def count(self):
        return (len(self.bindings) - len(self.failures)) if self.enabled else 0


globalhotkeys.GlobalHotkeys = FakeHotkeys
RealSend = sendmod.Send


class _Running:
    active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


class FakeSend(RealSend):
    """A send whose card is a stand-in: it runs and plays nothing."""

    def __init__(self, device=None, gain_db=0.0, **kw):
        super().__init__(device=device, samplerate=RATE, gain_db=gain_db,
                         open_stream=False)
        self.stream = _Running()

    def start(self):
        self.stream = _Running()
        return True


sendmod.Send = FakeSend


def listen(frame):
    """Everything the frame says from now on, in order."""
    heard = []
    for name in ("announce", "announce_help", "announce_answer"):
        real = getattr(frame, name)

        def hook(text, *args, _real=real, **kw):
            heard.append(text)
            return _real(text, *args, **kw)

        setattr(frame, name, hook)
    return heard


def click(button):
    event = wx.CommandEvent(wx.wxEVT_BUTTON, button.GetId())
    event.SetEventObject(button)
    button.GetEventHandler().ProcessEvent(event)


def tick(box, value):
    box.SetValue(value)
    event = wx.CommandEvent(wx.wxEVT_CHECKBOX, box.GetId())
    event.SetEventObject(box)
    event.SetInt(int(value))
    box.GetEventHandler().ProcessEvent(event)


def choose(control, index):
    control.SetSelection(index)
    event = wx.CommandEvent(wx.wxEVT_CHOICE, control.GetId())
    event.SetEventObject(control)
    event.SetInt(index)
    control.GetEventHandler().ProcessEvent(event)


def button_called(window, label):
    for child in window.GetChildren():
        if isinstance(child, wx.Button) and child.GetLabel() == label:
            return child
    return None


def pump_until(done, seconds=5.0):
    """Let posted events and worker threads finish, up to a limit."""
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.ProcessPendingEvents()
        if done():
            return True
        time.sleep(0.02)
    app.ProcessPendingEvents()
    return done()


def loaded_line(heard):
    found = [line for line in heard if line.startswith("Loaded")]
    return found[-1] if found else ""


def menu_labels(menu):
    out = []
    for item in menu.GetMenuItems():
        if item.GetSubMenu() is not None:
            out.extend(menu_labels(item.GetSubMenu()))
        elif not item.IsSeparator():
            out.append(item.GetItemLabelText())
    return out


class Keystroke:
    """A key at the hotkey dialog's hook. See tests/test_audit_3_0.py for
    why a real wx.KeyEvent cannot be given a key code from Python."""

    def __init__(self, code, ctrl=False, alt=False, shift=False):
        self.code, self.ctrl, self.alt, self.shift = code, ctrl, alt, shift
        self.skipped = False

    def GetKeyCode(self):
        return self.code

    def AltDown(self):
        return self.alt

    def ControlDown(self):
        return self.ctrl

    def ShiftDown(self):
        return self.shift

    def Skip(self, skip=True):
        self.skipped = bool(skip)


class Scripted(dialogs.SettingsDialog):
    """Preferences, with a script standing where a person would."""

    script = None
    mic_choice = None

    def ShowModal(self):
        return Scripted.script(self)

    @property
    def chosen_mic_device(self):
        if Scripted.mic_choice is not None:
            return Scripted.mic_choice
        return dialogs.SettingsDialog.chosen_mic_device.fget(self)


uimod.SettingsDialog = Scripted


def preferences(frame, script):
    Scripted.script = staticmethod(script)
    frame._on_settings()
    Scripted.mic_choice = None


# --------------------------------------------------------------- boards --
HOME = tempfile.mkdtemp(prefix="dropdeck-wiring-boards-")


def tone(folder, name):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    sf.write(path, np.zeros((RATE // 20, 2), dtype=np.float32), RATE)
    return path


SOUND = tone(os.path.join(HOME, "sounds"), "drop.wav")
FOLDER_A = os.path.join(HOME, "countdowns A")
FOLDER_B = os.path.join(HOME, "countdowns B")
FILES_A = [tone(FOLDER_A, "a1.wav"), tone(FOLDER_A, "a2.wav")]
FILES_B = [tone(FOLDER_B, "b1.wav"), tone(FOLDER_B, "b2.wav")]


def board_a():
    board = Board()
    board.device_name, board.device_hostapi = "Desk A", "WASAPI"
    board.bank_devices = {3: {"name": "Beds A", "hostapi": "WASAPI"}}
    board.mic_output_name, board.mic_output_hostapi = "Phones A", "WASAPI"
    board.sources = [{"name": "Games call A", "kind": "device",
                      "device_name": "Capture A", "on_air": True}]
    board.send_on = True
    board.send_device_name, board.send_device_hostapi = "Cable A", "WASAPI"
    board.slots[0].filepath = SOUND
    board.slots[0].global_hotkey = "Ctrl+Alt+F9"
    board.global_hotkeys_on = True
    board.slots[1].filepath = FOLDER_A
    board.slots[1].name = "Countdown A"
    board.rename_bank(1, "Alpha drops")
    board.slots[4].hidden = True
    board.stream_name, board.stream_host = "Station A", "a.example.invalid"
    board.live_to = C.LIVE_TO_AUDIO
    board.save_station()
    return board


def board_b():
    board = Board()
    board.device_name, board.device_hostapi = "Desk B", "WASAPI"
    board.bank_devices = {2: {"name": "Drops B", "hostapi": "WASAPI"}}
    board.mic_output_name, board.mic_output_hostapi = "Phones B", "WASAPI"
    board.sources = [
        {"name": "Callers B", "kind": "device", "device_name": "Capture B",
         "on_air": True},
        {"name": "Second mic B", "kind": "device", "device_name": "Mic B",
         "on_air": True}]
    board.send_on = False
    board.slots[2].filepath = SOUND
    board.slots[2].global_hotkey = "Ctrl+Alt+F10"
    board.global_hotkeys_on = False
    board.slots[5].filepath = FOLDER_B
    board.slots[5].name = "Countdown B"
    board.rename_bank(2, "Bravo")
    board.slots[C.SLOTS_PER_BANK + 2].hidden = True
    board.stream_name = "Station B"
    board.live_to = C.LIVE_TO_VIDEO
    board.save_station()
    return board


PATH_A = os.path.join(HOME, "Board A.json")
PATH_B = os.path.join(HOME, "Board B.json")
board_a().save(PATH_A)
board_b().save(PATH_B)
boardmod.remember_board_path(PATH_A)

# ===========================================================================
heading("Board A is what the app starts on, with all of it live")
frame = uimod.DropDeckFrame(None)
check("the board that opened is A", boardmod.same_path(frame.board.path,
                                                       PATH_A))
check("A's cards are the live ones",
      frame.mixer.bank_devices == {1: 901, 2: 901, 3: 902, 4: 901}
      and frame.mixer.monitor_device == 903,
      (frame.mixer.bank_devices, frame.mixer.monitor_device))
check("A's send is running", frame.sending())
check("A's global hotkeys are on", frame.hotkeys.enabled
      and frame.hotkeys.bindings == {0: "Ctrl+Alt+F9"}, frame.hotkeys.bindings)

# ===========================================================================
heading("File, Open board B: B takes over everything, not only its pads")
heard = listen(frame)
call = frame.send
check("it opens", frame._open_board(PATH_B) is True)
loaded = [line for line in heard if line.startswith("Loaded")]
check("B's sound cards are the live ones",
      frame.mixer.bank_devices == {1: 904, 2: 905, 3: 904, 4: 904},
      frame.mixer.bank_devices)
check("and B's monitor card", frame.mixer.monitor_device == 906,
      frame.mixer.monitor_device)
check("B's sources replace A's",
      [s.name for s in frame.sources] == ["Callers B", "Second mic B"],
      [s.name for s in getattr(frame, "sources", [])])
check("and the source group reads B's sources",
      frame.source_group.sources is frame.sources)
check("no source and no microphone was opened",
      not any(s.is_open for s in frame.sources) and not frame._mic_open())
check("a send carrying a call is never stopped by a board change",
      frame.sending() and frame.send is call)
check("and the Loaded line says it carries on",
      loaded and "Still sending your whole show" in loaded[-1], loaded)
check("the sources that would not open are said once, in the Loaded line",
      sum("would not open" in line for line in heard) == 1
      and "Callers B, Second mic B" in loaded[-1], heard)
check("A's global hotkeys are gone and B's are the ones bound",
      frame.hotkeys.bindings == {2: "Ctrl+Alt+F10"}, frame.hotkeys.bindings)
check("and B saved them off, so they are off", not frame.hotkeys.enabled)
check("and the menu tick says off", not frame.global_item.IsChecked())
folder = frame.board.slots[5]
check("B's folder pad is counted, feedback 42",
      sorted(folder.folder_files) == sorted(FILES_B), folder.folder_files)
check("and a press has a sound to play", folder.pick_file() in FILES_B)
check("the bank tabs are B's names",
      frame.notebook.GetPageText(1).startswith("2. Bravo")
      and "Alpha" not in frame.notebook.GetPageText(0),
      [frame.notebook.GetPageText(n) for n in range(C.BANK_COUNT)])
check("B's hidden pad is hidden",
      not frame.pages[2].buttons[2].IsShown())
check("and A's hidden pad is back", frame.pages[1].buttons[4].IsShown())
check("Streaming location ticks B's destination",
      frame.station_menu.FindItemById(uimod.ID_LIVE_TO_VIDEO).IsChecked())
saved = menu_labels(frame.station_menu)
check("the saved setups are B's", "Station B" in saved
      and "Station A" not in saved, saved)
check("opening a board does not mark it changed", not frame.board.dirty)
check("nothing went live", not frame.streaming())

heading("Back to A: its hotkeys come back on, and a stopped send starts")
frame._stop_send(quiet=True)
heard.clear()
check("it opens", frame._open_board(PATH_A) is True)
check("A's send starts, out of A's card, as it does at startup",
      frame.sending() and frame.send.device == 911,
      getattr(frame.send, "device", None))
loaded = [line for line in heard if line.startswith("Loaded")]
check("and it is said, the startup line's sentence",
      loaded and "Sending your whole show to" in loaded[-1], loaded)
check("the global hotkeys are said too",
      loaded and "Global hotkeys on, 1 active" in loaded[-1], loaded)
check("A's hotkeys are on and bound",
      frame.hotkeys.enabled and frame.hotkeys.bindings == {0: "Ctrl+Alt+F9"})
check("and the menu tick says on", frame.global_item.IsChecked())

heading("A board with the same send keeps the call going")
same = board_a()
same.slots[0].name = "Something else"
PATH_A2 = os.path.join(HOME, "Board A two.json")
same.save(PATH_A2)
running = frame.send
frame._open_board(PATH_A2)
check("the send was not stopped and started again", frame.send is running)

# ===========================================================================
heading("File, New and the demo pack keep the studio they were opened in")
running = frame.send
frame._on_new(None)
check("New is empty", frame.board.assigned_count == 0)
check("but on the same sound cards",
      frame.mixer.bank_devices == {1: 901, 2: 901, 3: 902, 4: 901}
      and frame.mixer.monitor_device == 903,
      (frame.mixer.bank_devices, frame.mixer.monitor_device))
check("with the same send, still running", frame.send is running)
check("and the same sources",
      [s.name for s in frame.sources] == ["Games call A"])
check("an untouched new board is still not marked changed",
      not frame.board.dirty)
if os.path.exists(boardmod.demo_board_path()):
    frame._on_load_demo(None)
    check("the demo pack keeps them too",
          frame.mixer.bank_devices == {1: 901, 2: 901, 3: 902, 4: 901}
          and frame.send is running)

# ===========================================================================
heading("Mute and solo survive a change of board, and so does keeping the "
        "microphone out")
PATH_M = os.path.join(HOME, "Board M.json")
board_a().save(PATH_M)
frame._open_board(PATH_M)
check("set up: the send is carrying the show", frame.sending())
muted = frame.sources[0]
muted.muted = True
frame.apply_source_mixing()
frame._on_new(None)
check("a source muted on a call is still muted after File New",
      frame.sources[0].muted)
check("and still off the air", not frame.sources[0].input.on_air)
frame.sources[0].muted = False
frame.sources[0].soloed = True
frame.apply_source_mixing()
check("set up: a soloed source takes the microphone off",
      not frame.mic.on_air)
frame._on_new(None)
check("solo survives File New", frame.anything_soloed())
check("so the microphone stays off the air", not frame.mic.on_air)
different = board_a()
different.sources = [
    {"name": "Games call A", "kind": "device", "device_name": "Capture A",
     "on_air": True, "gain_db": 3.0},
    {"name": "Extra", "kind": "device", "device_name": "Capture X",
     "on_air": True}]
PATH_M2 = os.path.join(HOME, "Board M two.json")
different.save(PATH_M2)
frame._open_board(PATH_M2)
check("on a board with a different list, the same name keeps its solo",
      frame.sources[0].soloed and not frame.sources[1].soloed,
      [(x.name, x.soloed) for x in frame.sources])
for source in frame.sources:
    source.soloed = False
frame.board.stream_mic = False
frame.apply_source_mixing()
check("set up: Put the microphone on air is off, so it is not sent",
      not frame.mic.on_air)
frame._on_new(None)
check("File New keeps the microphone out", frame.board.stream_mic is False)
check("so it is still not on the send", not frame.mic.on_air)

# ===========================================================================
heading("A board naming cards this machine does not have says so")
alien = board_a()
alien.device_name = "Co-host desk"
alien.bank_devices = {3: {"name": "Co-host beds", "hostapi": "WASAPI"}}
alien.mic_output_name = "Co-host phones"
PATH_ALIEN = os.path.join(HOME, "Alien.json")
alien.save(PATH_ALIEN)
heard.clear()
frame._open_board(PATH_ALIEN)
line = loaded_line(heard)
check("the main card it names is said", "Co-host desk, which is not here"
      in line, line)
check("and a bank's card", "Co-host beds, which is not here" in line, line)
check("and the card you listen on", "Co-host phones, which is not here"
      in line, line)

# ===========================================================================
heading("Global hotkeys a board turns on are said, and never in a box")
glob = Board()
for index, key in ((0, "Ctrl+Alt+F11"), (1, "Ctrl+Alt+F11"),
                   (2, "Ctrl+Alt+F12"), (3, "Ctrl+M")):
    glob.slots[index].filepath = SOUND
    glob.slots[index].global_hotkey = key
glob.global_hotkeys_on = True
PATH_G = os.path.join(HOME, "Glob.json")
glob.save(PATH_G)
frame._open_board(PATH_B)
heard.clear()
BOXES.clear()
frame._open_board(PATH_G)
app.ProcessPendingEvents()
line = loaded_line(heard)
check("switching them on is said, with how many work",
      "Global hotkeys on, 2 active" in line, line)
check("two pads on one combination is said as the board's own doing",
      "Ctrl+Alt+F11 is the global hotkey for two pads on this board" in line,
      line)
check("a key another program holds is said as another program's",
      "another program already uses them: Ctrl+Alt+F12" in line, line)
check("and the duplicate is not blamed on another program",
      "already uses them: Ctrl+Alt+F11" not in line, line)
check("a pad on one of the app's own keys is said",
      "Ctrl+M is also the global hotkey" in line, line)
check("and no box, though the listener reported the refusals",
      not BOXES, BOXES)
frame._stop_send(quiet=True)
again = Board()
again.slots[0].filepath = SOUND
again.slots[0].global_hotkey = "Ctrl+Alt+F12"
again.global_hotkeys_on = True
frame.board.dirty = False
again.save(PATH_G)
BOXES.clear()
heard.clear()
frame._check_board_file(wait=True)
app.ProcessPendingEvents()
check("a reload from disk takes the new board", frame.board.slots[1].filepath
      is None and frame.board.slots[0].global_hotkey == "Ctrl+Alt+F12")
check("and puts up no box about its hotkeys", not BOXES, BOXES)
check("it says them instead",
      "another program already uses them: Ctrl+Alt+F12" in loaded_line(heard),
      heard)

# ===========================================================================
heading("While on air, another board is refused with the come off air rule")
frame._open_board(PATH_A)
frame.streaming = lambda: True
heard.clear()
check("File, Open board is refused", frame._open_board(PATH_B) is False)
check("and A is still the board", boardmod.same_path(frame.board.path,
                                                     PATH_A))
check("it says come off air first, with the key",
      any("Come off air first, Alt+Shift+B" in line for line in heard),
      heard)
frame._on_new(None)
check("File, New is refused too", boardmod.same_path(frame.board.path,
                                                     PATH_A))
del frame.streaming

# ===========================================================================
heading("Preferences: a mid show change reaches the show")
plain = Board()
plain.claim_path(os.path.join(HOME, "plain.json"))
frame._adopt(plain)
frame.board.send_on = True
frame.board.send_device_name = "Cable A"
frame._start_send(quiet=True)
frame.board.stream_mic = False
frame._sync_air_taps()
check("set up: sending, and the microphone is not on the send",
      frame.sending() and not frame.mic.on_air)


def mic_on_air(dialog):
    dialog.stream_mic.SetValue(True)
    return wx.ID_OK


preferences(frame, mic_on_air)
check("Put the microphone on air reaches the send at once", frame.mic.on_air)
check("and the microphone's group is what the mixer sends",
      frame.mixer.primary.air_source is frame.source_group)

heading("Switching microphone while it is open, when the new one fails")
real_start, real_open = frame.mic.start, frame._mic_open
frame.mic.start = lambda device=None: False
frame._mic_open = lambda: True
frame.mic_item.Check(True)
heard.clear()
Scripted.mic_choice = (7, "Imaginary USB microphone", "MME")
preferences(frame, lambda dialog: wx.ID_OK)
check("Microphone on is no longer ticked", not frame.mic_item.IsChecked())
check("and it is said, the way Ctrl+M says it",
      heard and "would not open" in heard[-1], heard[-1:])
frame.mic.start, frame._mic_open = real_start, real_open
del frame.mic.start
del frame._mic_open

heading("Where Ctrl+B goes cannot be changed under a live stream")
frame.board.live_to = C.LIVE_TO_AUDIO
frame.streaming = lambda: True
heard.clear()
seen = {}


def flip_live_to(dialog):
    tick(dialog.live_to_video, True)
    seen["box"] = dialog.live_to_video.GetValue()
    return wx.ID_OK


preferences(frame, flip_live_to)
check("the box is put back the moment it is ticked", seen.get("box") is False)
check("and it says come off air first",
      any("Come off air first" in line for line in heard), heard)
check("the board still sends Ctrl+B to the radio station",
      frame.board.live_to == C.LIVE_TO_AUDIO)


def sneak_live_to(dialog):
    dialog.live_to_video.SetValue(True)        # no event: the backstop
    return wx.ID_OK


heard.clear()
preferences(frame, sneak_live_to)
check("OK does not move it either", frame.board.live_to == C.LIVE_TO_AUDIO)
check("and says why", any("did not change" in line for line in heard), heard)

frame.board.stream_name = "One"
frame.board.save_station()
frame.board.stream_name = "Two"
frame.board.stream_host = "two.example.invalid"
frame.board.save_station()
frame.board.load_station("One")
heard.clear()


def pick_other_station(dialog):
    names = list(dialog.stream_picker.GetStrings())
    choose(dialog.stream_picker, names.index("Two"))
    seen["picker"] = dialog.stream_picker.GetStringSelection()
    seen["loaded"] = dialog.board.stream_name
    return wx.ID_CANCEL


preferences(frame, pick_other_station)
check("a saved station is not loaded while on air",
      seen.get("loaded") == "One", seen.get("loaded"))
check("the list goes back to the station in use", seen.get("picker") == "One",
      seen.get("picker"))
check("and it says come off air first",
      any("then change station" in line for line in heard), heard)

# The setup on air was typed in and never saved as a station.
frame.board.stream_name = "Unsaved tonight"
frame.board.stream_host = "tonight.example.invalid"


def pick_while_unsaved(dialog):
    seen["at_open"] = dialog.stream_picker.GetStringSelection()
    names = list(dialog.stream_picker.GetStrings())
    choose(dialog.stream_picker, names.index("Two"))
    seen["after"] = dialog.stream_picker.GetStringSelection()
    return wx.ID_CANCEL


preferences(frame, pick_while_unsaved)
check("a refused pick never shows a station that is not the one in use",
      seen.get("after") in ("", "Unsaved tonight"), seen)
check("it shows what it showed before",
      seen.get("after") == seen.get("at_open"), seen)
frame.board.load_station("One")
del frame.streaming

# ===========================================================================
heading("Cancel puts back all of a picked station, and the menu is current")
board = frame.board
board.screen, board.split_corner = "screen-one", "top left"
board.colour_background, board.colour_text = "navy", "cream"
first = C.PLACES_ORDER[0]
board.text_places[first]["kind"] = C.TEXT_WORDS
board.text_places[first]["words"] = "Hello from One"
board.stream_name = "One"
board.save_station()
board.screen, board.split_corner = "screen-two", "bottom right"
board.colour_background, board.colour_text = "black", "white"
board.text_places[first]["words"] = "Hello from Two"
board.stream_name = "Two"
board.save_station()
board.load_station("One")
before = {f: getattr(board, f) for f in ("screen", "split_corner",
                                         "colour_background", "colour_text")}


def pick_then_cancel(dialog):
    names = list(dialog.stream_picker.GetStrings())
    choose(dialog.stream_picker, names.index("Two"))
    dialog.stream_name.SetValue("Three")
    click(button_called(dialog.stream_picker.GetParent(),
                        "Sa&ve this station"))
    choose(dialog.stream_picker, list(dialog.stream_picker.GetStrings())
           .index("Two"))
    click(button_called(dialog.stream_picker.GetParent(), "For&get it"))
    return wx.ID_CANCEL


preferences(frame, pick_then_cancel)
after = {f: getattr(board, f) for f in before}
check("the screen, the corner and the colours are put back",
      after == before, after)
check("and the words on the picture",
      board.text_places[first]["words"] == "Hello from One",
      board.text_places[first]["words"])
saved = menu_labels(frame.station_menu)
check("a station saved before Cancel is on the menu", "Three" in saved, saved)
check("and one forgotten before Cancel is not", "Two" not in saved, saved)

heading("A saved station keeps its own words and colours")
board.text_places[first]["words"] = "Kept"
board.stream_name = "Copy"
board.save_station()
board.text_places[first]["words"] = "Edited afterwards"
stored = [s for s in board.stream_stations if s["stream_name"] == "Copy"][0]
check("editing the board does not edit the saved station",
      stored["text_places"][first]["words"] == "Kept",
      stored["text_places"][first]["words"])
board.load_station("Copy")
board.text_places[first]["words"] = "Edited after loading"
check("and editing after loading it does not either",
      stored["text_places"][first]["words"] == "Kept",
      stored["text_places"][first]["words"])

# ===========================================================================
heading("Picture changes in Preferences reach a picture already going out")


class FakePicture:
    def __init__(self, settings):
        self.kind = settings.get("picture")
        self.fallen_back = False

    def start(self):
        pass

    def close(self):
        pass

    def frame(self, width, height):
        return None

    def set_title(self, title):
        pass


picturefeed.picture.build = lambda settings, on_fallback=None: \
    FakePicture(settings)
board.picture = C.PICTURE_CARD
feed = frame.feed()
feed.acquire(picturefeed.FOR_RECORDING)
built = feed.builds
heard.clear()
# Never opened: the picture is built by the stand-in above.
picture_file = os.path.join(HOME, "art.png")


def to_picture(dialog):
    choose(dialog.picture_kind, dialog._picture_kinds.index(C.PICTURE_IMAGE))
    dialog.picture_file.SetValue(picture_file)
    return wx.ID_OK


preferences(frame, to_picture)
check("the picture going into the recording is rebuilt",
      feed.builds == built + 1, (built, feed.builds))
check("and it is the picture that was chosen", feed.kind == C.PICTURE_IMAGE,
      feed.kind)
check("and it is said", any("picture of my own" in line for line in heard),
      heard)


def bigger(dialog):
    sizes = dialog._sizes
    other = [n for n, s in enumerate(sizes)
             if s != (frame.board.video_width, frame.board.video_height)][0]
    choose(dialog.video_size, other)
    return wx.ID_OK


heard.clear()
preferences(frame, bigger)
check("a new size says it starts next time",
      any("next time" in line for line in heard), heard)


def boom():
    raise RuntimeError("the framing watch broke")


def back_to_card(dialog):
    choose(dialog.picture_kind, dialog._picture_kinds.index(C.PICTURE_CARD))
    return wx.ID_OK


frame._start_framing = boom
frame.board.dirty = False
frame._save_timer.Stop()
attempt("a fault in the framing watch does not escape Preferences",
        lambda: preferences(frame, back_to_card))
check("and Preferences is still saved",
      frame.board.dirty and frame._save_timer.IsRunning())
del frame._start_framing

heading("Check the shot is not left busy when the picture raises")


def broken_frame(width, height):
    raise RuntimeError("the capture thread fell over")


feed.frame = broken_frame
checker = dialogs.ShotCheckDialog(frame, frame)
click(checker.go)
check("the check finishes, rather than staying busy for good",
      pump_until(lambda: not checker._busy), checker._busy)
check("and says there is no picture",
      "no picture" in checker.answer.GetValue(), checker.answer.GetValue())
checker.Destroy()
del feed.frame

heading("Look through the camera now, while the picture is held")
frame.board.picture = C.PICTURE_CAMERA
dialog = dialogs.SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic)
dialog._cameras = ["Imaginary camera"]
dialog.camera_choice.Set(["Imaginary camera"])
dialog.camera_choice.SetSelection(0)
dialog.picture_kind.SetSelection(dialog._picture_kinds.index(C.PICTURE_CAMERA))
heard.clear()
look = button_called(dialog.picture_kind.GetParent(),
                     "&Look through the camera now")
attempt("the button does something", lambda: click(look))
check("it says the camera is already held, and opens nothing",
      any("already has the camera" in line for line in heard), heard)
dialog.Destroy()
feed.release(picturefeed.FOR_RECORDING)
frame.board.picture = C.PICTURE_CARD

# ===========================================================================
heading("Preview sounds is saved")
frame.board.dirty = False
frame._save_timer.Stop()
browser = dialogs.SoundBrowserDialog(frame, HOME, "Choose a sound",
                                     frame=frame)
tick(browser.preview, not browser.preview.GetValue())
check("turning preview on or off marks the board changed",
      frame.board.dirty and frame._save_timer.IsRunning())
browser._stop_preview()
browser.Destroy()
frame.board.dirty = False
frame._save_timer.Stop()
native = dialogs.NativePreview(None, frame, on=False)
native.toggle()
check("Alt+P in the Windows file window does too", frame.board.dirty)
frame.board.dirty = False
frame._save_timer.Stop()

# ===========================================================================
heading("A bank four hotkey cannot take one of the app's own keys")
pad = frame.board.bank_slots(C.BANK_MISC)[0]
pad.filepath = SOUND
taken = frame._hotkey_map(exclude=pad.index)
keys = dialogs.AssignHotkeyDialog(frame, pad, taken)
for code, held, means in ((ord("S"), {"ctrl": True}, "Save board"),
                          (ord("D"), {"ctrl": True}, "Ducking"),
                          (ord("M"), {"ctrl": True}, "Microphone"),
                          (wx.WXK_F5, {}, "turns the beds down")):
    keys._on_key(Keystroke(code, **held))
    label = dialogs.key_label(code, wx.ACCEL_CTRL if held else 0)
    check("%s is refused" % label, keys.result[0] is None, keys.result)
    check("with a sentence naming what %s does" % label,
          means in keys.warning.GetLabel(), keys.warning.GetLabel())
free = [c for c in range(ord("A"), ord("Z") + 1)
        if (c, wx.ACCEL_ALT | wx.ACCEL_SHIFT) not in taken][0]
keys._on_key(Keystroke(free, alt=True, shift=True))
check("a free key is still taken", keys.result[0] == free, keys.result)
keys._on_key(Keystroke(ord("1"), ctrl=True))
check("and a pad's key is still only a warning",
      keys.result[0] == ord("1") and "Careful" in keys.warning.GetLabel(),
      keys.warning.GetLabel())


def refused(label, code, words, **held):
    keys._key_code, keys._modifiers = None, 0
    keys._on_key(Keystroke(code, **held))
    check("%s is refused, and says it %s" % (label, words),
          keys.result[0] is None and words in keys.warning.GetLabel(),
          (keys.result, keys.warning.GetLabel()))


# Alt plus each menu's own letter, read off the menu bar as it is.
bar = frame.GetMenuBar()
for position in range(bar.GetMenuCount()):
    title = bar.GetMenuLabel(position)
    at = title.find("&")
    if at >= 0 and at + 1 < len(title):
        refused("Alt+%s" % title[at + 1].upper(), ord(title[at + 1].upper()),
                "opens the %s menu" % bar.GetMenuLabelText(position), alt=True)
refused("F10", wx.WXK_F10, "opens the menu bar")
refused("Shift+F10", wx.WXK_F10, "opens the menu for the pad you are on",
        shift=True)
refused("The Applications key", wx.WXK_WINDOWS_MENU,
        "opens the menu for the pad you are on")
refused("Ctrl+Page Down", wx.WXK_PAGEDOWN, "moves to the next bank",
        ctrl=True)
refused("Ctrl+Page Up", wx.WXK_PAGEUP, "moves to the previous bank",
        ctrl=True)
keys.Destroy()
pad.clear()

# ===========================================================================
heading("Rename in Source control")
frame.apply_sources([{"name": "Games call", "kind": "device",
                      "device_name": "Capture A", "on_air": True}])
real_ask = dialogs.ask_text


def answered(parent, prompt, title, value=""):
    box = real_ask(parent, prompt, title, value)
    box.ShowModal = lambda: wx.ID_OK
    # SetValue on the dialog, which is what OK would have read back.
    box.SetValue("Callers on air")
    return box


dialogs.ask_text = answered
control = dialogs.SourceControlDialog(frame)
control.list.Select(1)
control.list.Focus(1)
heard.clear()
attempt("Rename does not raise", lambda: click(control.rename))
check("the source is renamed", frame.sources[0].name == "Callers on air",
      (frame.sources[0].name, control.list.GetFirstSelected(), heard))
check("and the board keeps the new name",
      frame.board.sources[0]["name"] == "Callers on air")
control.Destroy()
dialogs.ask_text = real_ask

# ===========================================================================
heading("The cue sheet hands every key to the window it belongs to")
fired = []
real_trigger = frame.trigger
frame.trigger = lambda index, *a, **kw: fired.append(index)
sheet = dialogs.CueSheetDialog(frame)
wx.PostEvent(sheet, wx.CommandEvent(wx.wxEVT_MENU, uimod.ID_SLOT_BASE + 3))
app.ProcessPendingEvents()
check("a pad's key in the cue sheet plays the pad", fired == [3], fired)
was = frame.board.sfx_volume
wx.PostEvent(sheet, wx.CommandEvent(wx.wxEVT_MENU, uimod.ID_VOL_SFX_DOWN))
app.ProcessPendingEvents()
check("and an app key, F3, does its job", frame.board.sfx_volume < was,
      (was, frame.board.sfx_volume))
carried = getattr(sheet, "keys", None)
check("Escape is left to close the cue sheet, not to count towards stopping",
      carried is not None and carried
      and not any(e.GetKeyCode() == wx.WXK_ESCAPE for e in carried))
sheet._on_close()
# The cue sheet the app opens, kept current when another board comes in.
keyed = board_b()
siren = keyed.bank_slots(C.BANK_MISC)[7]
siren.filepath, siren.name = SOUND, "Siren"
siren.key_code, siren.modifiers = wx.WXK_F11, wx.ACCEL_CTRL | wx.ACCEL_SHIFT
siren.custom_hotkey = "Ctrl+Shift+F11"
PATH_K = os.path.join(HOME, "Keyed.json")
keyed.save(PATH_K)
frame._on_cue_sheet()
opened_sheet = frame.cue_window
frame._open_board(PATH_K)
check("after File, Open board the cue sheet carries the new board's keys",
      any(e.GetKeyCode() == wx.WXK_F11
          and e.GetFlags() == wx.ACCEL_CTRL | wx.ACCEL_SHIFT
          and e.GetCommand() == uimod.ID_SLOT_BASE + siren.index
          for e in opened_sheet.keys))
fired.clear()
wx.PostEvent(opened_sheet, wx.CommandEvent(wx.wxEVT_MENU,
                                           uimod.ID_SLOT_BASE + siren.index))
app.ProcessPendingEvents()
check("and a key there still plays its pad, once", fired == [siren.index],
      fired)
opened_sheet._on_close()
frame.trigger = real_trigger
del frame.trigger

# ===========================================================================
heading("Buttons that are working stay where focus is, and say so")
real_thread = dialogs.threading.Thread


class HeldThread:
    """Started, never run: the work stays in flight for the check."""

    made = []

    def __init__(self, target=None, **kw):
        HeldThread.made.append(target)

    def start(self):
        pass


def in_flight(label, button, busy_line):
    HeldThread.made.clear()
    dialogs.threading.Thread = HeldThread
    try:
        heard.clear()
        click(button)
        check(label + ": the button stays enabled while it works",
              button.IsEnabled())
        click(button)
        check(label + ": a second press starts nothing",
              len(HeldThread.made) == 1, len(HeldThread.made))
        check(label + ": and says so", any(busy_line in line
                                           for line in heard), heard)
    finally:
        dialogs.threading.Thread = real_thread


shot = dialogs.ShotCheckDialog(frame, frame)
in_flight("Check the shot", shot.go, "Still looking at the picture")
shot.ask.question.SetValue("Is the plant still there?")
in_flight("Ask", shot.ask.send, "Still waiting for the answer")
shot.Destroy()
colours = dialogs.ColoursDialog(frame, frame.board)
in_flight("What does this look like", colours.describe_button,
          "Still looking at these colours")
colours.Destroy()


def cable_dialog():
    box = dialogs.SendDialog(frame, frame.board)
    box.devices = [{"name": "Imaginary cable", "hostapi": "WASAPI",
                    "index": 950}]
    box.device.Set(["Imaginary cable"])
    box.device.SetSelection(0)
    return box


frame._stop_send(quiet=True)
sending = cable_dialog()
in_flight("Test the cable", sending.test, "Still testing")
sending.Destroy()

frame.board.send_on = True
frame.board.send_device_name = "Cable A"
frame._start_send(quiet=True)
sending = cable_dialog()
HeldThread.made.clear()
dialogs.threading.Thread = HeldThread
try:
    heard.clear()
    click(sending.test)
finally:
    dialogs.threading.Thread = real_thread
check("Test the cable puts no tone down a cable while the send runs",
      frame.sending() and not HeldThread.made, HeldThread.made)
check("and says why", any("send is running" in line for line in heard),
      heard)
sending.Destroy()
frame._stop_send(quiet=True)

settings = dialogs.SettingsDialog(frame, frame.board, frame.mixer,
                                  mic=frame.mic)
asked = []
real_list = dialogs.vision.list_models


def queued_behind(who, key, *args, **kw):
    """A second press arrives while the first is still waiting."""
    asked.append(who)
    if len(asked) == 1:
        button = settings.vision_models_get
        event = wx.CommandEvent(wx.wxEVT_BUTTON, button.GetId())
        event.SetEventObject(button)
        wx.PostEvent(button.GetEventHandler(), event)
    return True, ["model-one", "model-two"]


dialogs.vision.list_models = queued_behind
heard.clear()
click(settings.vision_models_get)
check("Get the list: the button stays enabled while it asks",
      settings.vision_models_get.IsEnabled())
pump_until(lambda: not getattr(settings, "_asking_models", False)
           and asked)
pump_until(lambda: False, 0.3)
check("Get the list: a press queued behind the first asks nothing",
      len(asked) == 1, asked)
check("and says it is still asking",
      any("Still asking" in line for line in heard), heard)
check("and the list does arrive", settings.vision_model.GetCount() == 2,
      settings.vision_model.GetCount())
dialogs.vision.list_models = real_list
settings.Destroy()

# ===========================================================================
heading("The suspected four")
heard.clear()
BOXES.clear()
real_save = frame.board.save


def refusing(path=None):
    raise PermissionError(13, "Access is denied")


frame.board.save = refusing
frame._touch()
frame._autosave()
frame._autosave()
check("an autosave that cannot write shows no box mid show", not BOXES,
      BOXES)
check("it says so instead, once",
      sum("could not be saved" in line for line in heard) == 1, heard)
check("and the board still holds the change", frame.board.dirty)
frame.board.save = real_save
del frame.board.save
frame.board.dirty = False
frame._save_timer.Stop()
other = Board()
other.claim_path(os.path.join(HOME, "other.json"))
frame._adopt(other)
frame.board.save = refusing
frame._touch()
frame._autosave()
check("the next board's own first failed save is said too",
      sum("could not be saved" in line for line in heard) == 2, heard)
del frame.board.save
frame.board.dirty = False
frame._save_timer.Stop()

ticked = []
real_tick = frame.player.tick
frame.player.tick = lambda: ticked.append(True)


def broken():
    raise RuntimeError("a helper broke")


frame._push_stream_title = broken
attempt("the playlist tick does not raise",
        lambda: frame._on_player_tick(None))
check("a helper that raises does not stop the playlist ticking", ticked)
del frame._push_stream_title
frame.player.tick = real_tick
del frame.player.tick
frame._player_timer.Stop()


class Explodes:
    """A source whose driver raises instead of answering."""

    name = "Exploding source"
    wanted_on_air = True
    wanted_monitor = False
    is_open = False
    muted = False
    soloed = False

    def __init__(self):
        self.input = type("Input", (), {"on_air": False, "monitor": False})()

    def start(self, *a, **kw):
        raise OSError("the driver fell over")

    def wants_air(self, soloed=False):
        return False

    def wants_monitor(self, soloed=False):
        return False

    def close(self):
        pass


frame.sources = [Explodes()] + list(frame.sources)
frame._next_source_watch = float("inf")
heard.clear()
attempt("start_sources does not raise", frame.start_sources)
check("one source that raises does not stop the watcher",
      frame._next_source_watch != float("inf"))
check("and it is named among those that would not open",
      any("Exploding source" in line for line in heard), heard)
frame.sources = frame.sources[1:]

box = frame.playlist_panel.crossfade
check("Ctrl+V in the crossfade box: its edit part is a wx.TextCtrl, which "
      "keeps Ctrl+V for itself, so no fix is needed",
      any(isinstance(child, wx.TextCtrl) for child in box.GetChildren()))

# ===========================================================================
heading("A board changed on disk is not reloaded under an open Preferences")
frame._stop_send(quiet=True)
PATH_R = os.path.join(HOME, "Reload.json")
first_copy = Board()
first_copy.slots[0].filepath = SOUND
first_copy.save(PATH_R)
frame._open_board(PATH_R)
frame.board.dirty = False
frame._save_timer.Stop()
original = frame.board
ducking = not original.ducking


def reload_inside(dialog):
    outside = Board()
    outside.slots[0].filepath = SOUND
    outside.slots[1].filepath = SOUND
    outside.save(PATH_R)                       # somebody else's copy lands
    frame._check_board_file(wait=True)        # the half second check fires
    seen["during"] = frame.board
    dialog.duck_on.SetValue(ducking)
    return wx.ID_OK


heard.clear()
preferences(frame, reload_inside)
check("the board is not swapped while Preferences is open",
      seen.get("during") is original)
check("so OK changes the board the window was opened on",
      frame.board is original and original.ducking == ducking)
check("and the change on disk is looked at once it closes",
      pump_until(lambda: any("changed outside Drop Deck" in line
                             for line in heard)), heard)
frame.board.dirty = False
frame._save_timer.Stop()

# ===========================================================================
heading("A source with no input chosen does not open the default input")
from dropdeck import micinput                                 # noqa: E402
tried = []
real_open = micinput.MicInput.start
micinput.MicInput.start = lambda self, *a, **kw: tried.append(a or kw) or False
heard.clear()
try:
    frame.apply_sources([{"name": "Unfinished", "kind": "device",
                          "device_name": "", "on_air": True}])
finally:
    micinput.MicInput.start = real_open
check("nothing tries to open an input for it", tried == [], tried)
check("and it says the source has no input chosen",
      any("Unfinished has no input chosen" in line for line in heard), heard)
frame.apply_sources([])

# ===========================================================================
frame._stop_send(quiet=True)
frame.board.dirty = False
frame.Destroy()
print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
