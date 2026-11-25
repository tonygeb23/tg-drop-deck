"""Review of 24 November 2026, Area 4: speech and commands.

    python tools/run_private.py tests/test_review_speech.py

Every `check` here fails on b96da8c and passes on the fix. A `guard` is a
thing that was already right and has to stay right (a refusal still said, a
row that is not on air still removed at once); guards pass on both and are
counted on a line of their own.

  1. Ctrl+M and Alt+Shift+M: "Mic on" and "Mic off", the device only when it
     is news, "music ducked" only with ducking on, and first that nobody else
     hears it when it is not on the air (worded so since the polish step);
  2. a reconnect says "Back on air", not the whole going live line again;
  3. Delete on the track on the air wants a second press (it asked with a box
     until the polish step), and says what it did at the essential level;
  4. Streaming location says the key that really goes there, and the Ctrl+B
     stop names Alt+Shift+B to a radio presenter;
  5. the Stop everything button counts the Escapes the board really wants;
  6. F7 and F8 say "what you hear only" whenever anything carries the show;
  7. Alt+Enter on a playlist row opens its crossfade;
  8. Assign a global hotkey off a pad says so;
  9. menu speech waits for the menu, and a view swap says only where you are;
 10. the search count waits for typing to stop and honours the speech level,
     and so do the dialogs' own lines;
 11. no two items or controls you can see at once share a letter;
 12. the microphone item is "Microphone", ticked or not.

Speech is what reaches the frame's speaker at a given `speech_level`, not what
a source file says. Keys and menu items are posted as command events to the
frame, the window that really receives them. Nothing opens a sound card or a
microphone and nothing makes a sound: the mixers run with no stream, the
microphone's start is a stand-in that opens nothing, and the send is a stand
in. Every modal path has its window stood in.
"""

import faulthandler
import os
import subprocess
import sys
import tempfile
import time

faulthandler.enable()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-speech-")

import numpy as np                                     # noqa: E402
import soundfile as sf                                 # noqa: E402
import wx                                              # noqa: E402

from dropdeck import board as boardmod                 # noqa: E402
from dropdeck import constants as C                    # noqa: E402
from dropdeck import dialogs                           # noqa: E402
from dropdeck import globalhotkeys                     # noqa: E402
from dropdeck import preflight                         # noqa: E402
from dropdeck import secrets                           # noqa: E402
from dropdeck import send as sendmod                   # noqa: E402
from dropdeck import streamout                         # noqa: E402
from dropdeck import ui as uimod                       # noqa: E402
from dropdeck.audiofile import CHANNELS                # noqa: E402
from dropdeck.board import Board                       # noqa: E402
from dropdeck.micinput import MicInput                 # noqa: E402
from dropdeck.mixer import Mixer, MixerGroup           # noqa: E402

RATE = 48000
CHECKS = []
GUARDS = []
FAILED = []


def check(label, condition, detail=""):
    """A fix: fails on b96da8c, passes now."""
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
    """One item. A raise is a failed check, so b96da8c runs to the end."""
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
uimod.resolve_device = lambda spec: None
Mixer._device_rate = staticmethod(lambda device: RATE)

#: Two microphones by name, as resolve_input would find them.
MICS = {"Desk": 4, "Lapel": 6}
NAMES = {None: "Laptop Mic", 4: "Desk Mic", 6: "Lapel Mic", 21: "Desk Mic"}
uimod.resolve_input = lambda spec: MICS.get((spec or {}).get("name"))
uimod.describe_input = lambda device: NAMES.get(device, "Mic %s" % device)
uimod._input_name = lambda device: NAMES.get(device, "Mic %s" % device)


class Opened:
    """A microphone stream that is open and is nothing at all."""

    active = True

    def stop(self):
        pass

    def close(self):
        pass


#: What the next MicInput.start does: "open", "refuse" or "reroute".
MIC_MODE = ["open"]


def stand_in_start(self, device=None, other_routes=True):
    """Opens nothing. Pretends to, so the sentence after it can be heard."""
    self.fell_back_from = None
    if MIC_MODE[0] == "refuse":
        self.last_error = "Device unavailable [PaErrorCode -9985]"
        return False
    self.stream = Opened()
    self.openings += 1
    if MIC_MODE[0] == "reroute":
        self.fell_back_from = 21
    return True


MicInput.start = stand_in_start


class QuietGroup(MixerGroup):
    def __init__(self, *args, **kw):
        kw["open_stream"] = False
        super().__init__(*args, **kw)

    @property
    def is_running(self):
        # No sound card is opened, and the pre-flight must not stop on that:
        # the sentences under test come after it.
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
    """Let wx run. A timer needs the real event loop; Yield does not run it
    (test_3_9_0 found that first), so a wait runs MainLoop for that long."""
    app.ProcessPendingEvents()
    app.Yield()
    if seconds > 0:
        wx.CallLater(max(1, int(seconds * 1000)), app.ExitMainLoop)
        app.MainLoop()
        app.ProcessPendingEvents()


def post(frame, command):
    """A key or a menu item, the way Windows hands it to the frame."""
    event = wx.CommandEvent(wx.wxEVT_MENU, command)
    event.SetEventObject(frame)
    frame.GetEventHandler().ProcessEvent(event)


def table(frame):
    return {(e.GetFlags(), e.GetKeyCode()): e.GetCommand()
            for e in frame._build_accelerators()}


TMP = tempfile.mkdtemp(prefix="dropdeck-speech-files-")


def wav(name, seconds=2.0):
    path = os.path.join(TMP, name + ".wav")
    sf.write(path, np.zeros((int(RATE * seconds), CHANNELS), np.float32), RATE)
    return path


boardmod.remember_board_path(os.path.join(TMP, "nothing yet.json"))
frame = uimod.DropDeckFrame(None)
frame.Show()
pump(0.2)
ear = Ear()
frame.speaker = ear
frame._check_mic_signal = lambda *a, **k: None


def hear(level, action, wait=0.0):
    """What reaches the speaker at this speech level while `action` runs."""
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


ESSENTIAL = C.SPEECH_ESSENTIAL


# ===========================================================================
heading("1. Ctrl+M and Alt+Shift+M say less, and only what is true")


def item_1():
    keys = table(frame)
    guard("Ctrl+M and Alt+Shift+M are one command in the table",
          keys.get((wx.ACCEL_CTRL, ord("M"))) == uimod.ID_MIC_TOGGLE
          and keys.get((wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("M")))
          == uimod.ID_MIC_TOGGLE)
    mic_off()
    frame._mic_named = None
    frame.board.mic_device_name, frame.board.mic_device_hostapi = "Desk", ""
    frame.mixer.ducking = True
    frame.board.stream_mic = True
    MIC_MODE[0] = "open"
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    check("the first open this session: Mic on, the device, music ducked",
          said == ["Mic on, Desk Mic. Music ducked"], said)
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    check("closing it says Mic off and nothing more", said == ["Mic off"],
          said)
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    check("the same microphone again is not named again",
          said == ["Mic on. Music ducked"], said)
    mic_off()
    frame.mixer.ducking = False
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    check("with ducking off (Ctrl+D) nothing is said to have ducked",
          said == ["Mic on"], said)
    mic_off()
    frame.mixer.ducking = True
    frame.board.mic_device_name = "Lapel"
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    check("a different microphone from the last one is named",
          said == ["Mic on, Lapel Mic. Music ducked"], said)
    mic_off()
    frame.board.mic_device_name = "Desk"
    hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    mic_off()
    MIC_MODE[0] = "reroute"
    frame._told_route = True
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    check("the same microphone in by another route is named, because that "
          "is news", said == ["Mic on, Desk Mic. Music ducked"], said)
    mic_off()
    MIC_MODE[0] = "open"

    # Not on air: a send is running and the microphone is kept off it. Said
    # first, with the reason, since the polish step (test_review_polish 2).
    frame.send = FakeSend()
    frame.board.stream_mic = False
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    check("with the send running and the microphone kept off the air, it "
          "says nobody else hears it",
          said == ["Mic on, but nobody else hears it: Send my microphone is "
                   "off. Music ducked"], said)
    mic_off()
    frame.board.stream_mic = True
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    check("and with it on the air, it does not",
          said == ["Mic on. Music ducked"], said)
    mic_off()
    frame.send = None
    frame.board.stream_mic = False
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    check("nor with nothing running, where there is no air to be off",
          said == ["Mic on. Music ducked"], said)
    mic_off()
    frame.board.stream_mic = True

    # The faults stay.
    MIC_MODE[0] = "refuse"
    from dropdeck import micdiag
    real_privacy = micdiag.privacy
    micdiag.privacy = lambda read=None: (micdiag.ALLOWED, "")
    try:
        said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    finally:
        micdiag.privacy = real_privacy
    guard("a microphone that will not open still says why",
          len(said) == 1 and said[0].startswith("The microphone would not "
                                                "open"), said)
    MIC_MODE[0] = "open"
    frame.board.mic_device_name = "A Microphone Nobody Has"
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_MIC_TOGGLE))
    guard("a chosen microphone that is not plugged in is still named",
          said and "A Microphone Nobody Has" in said[0]
          and "not plugged in" in said[0], said)
    mic_off()
    frame.board.mic_device_name = "Desk"


section("1", item_1)


# ===========================================================================
heading("2. A reconnect says Back on air")


class Pretend:
    """A streamer that is on the air and goes nowhere."""

    running = True
    state = streamout.ON_AIR
    on_air_for = 12.0
    backlog = 0.0
    reconnects = 0
    bytes_sent = 900000
    detail = ""
    error = ""
    _destination = None

    def set_frame_tap(self, tap):
        pass

    def set_title(self, title):
        pass

    def stop(self):
        self.running = False


def item_2():
    frame.board.live_to = C.LIVE_TO_AUDIO
    frame.board.stream_name = "Blindside Radio"
    frame.board.stream_host = "stream.example.com"
    detail = "128 k MP3 to stream.example.com"
    frame.streamer = Pretend()
    said = hear(ESSENTIAL, lambda: frame._on_stream_state(streamout.ON_AIR,
                                                          detail))
    check("going on air names the station, in one sentence, with no address",
          said == ["On air, Blindside Radio"], said)
    hear(ESSENTIAL, lambda: frame._on_stream_state(
        streamout.RECONNECTING, "could not reach stream.example.com"))
    said = hear(ESSENTIAL, lambda: frame._on_stream_state(streamout.ON_AIR,
                                                          detail))
    check("back after a drop, it says Back on air, once",
          said == ["Back on air"], said)
    said = hear(ESSENTIAL, lambda: frame._on_stream_state(streamout.ON_AIR,
                                                          detail))
    check("and every reconnect after that the same",
          said == ["Back on air"], said)
    frame.streamer = Pretend()
    said = hear(ESSENTIAL, lambda: frame._on_stream_state(streamout.ON_AIR,
                                                          detail))
    check("a new broadcast is a first time again",
          said == ["On air, Blindside Radio"], said)
    frame.board.live_to = C.LIVE_TO_VIDEO
    frame.board.video_server = "youtube"
    frame.board.video_name = ""
    frame.streamer = Pretend()
    said = hear(ESSENTIAL, lambda: frame._on_stream_state(
        streamout.ON_AIR, "2500k video, 128k audio to a.rtmps.youtube.com"))
    check("on video it names the platform, not the radio station, and no "
          "address", len(said) == 1 and said[0].startswith("On air, YouTube")
          and "rtmps" not in said[0] and "Blindside" not in said[0], said)
    said = hear(ESSENTIAL, lambda: frame._on_stream_state(
        streamout.ON_AIR, "2500k video, 128k audio to a.rtmps.youtube.com"))
    check("and its reconnect is Back on air too, without the YouTube warning "
          "again", said == ["Back on air"], said)
    frame.streamer = None
    frame.board.live_to = C.LIVE_TO_AUDIO


section("2", item_2)


# ===========================================================================
heading("3. Delete on the track on the air wants a second press, not a box")

# The polish step took the box out. It held the pads, had Yes and No and no
# close, and Escape did not close it (Jessica and Ryder, 24 November 2026).
# These checks replace the ones that asked for the box; each fails on
# 6fa5dad, where Delete put the box up.

SONGS = [wav("Song %d" % n, 6.0) for n in (1, 2, 3)]
FIRST_DELETE = ("Song 1 is on the air. Press Delete again to remove it and "
                "stop the music")


def focus_list():
    frame.show_view(uimod.VIEW_PLAYLIST)
    frame.playlist_panel.focus_list()
    pump(0.1)


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
    focus_list()
    panel.select(row)
    pump(0.1)


def delete():
    """Delete, the way the menu bar's accelerator hands it to the frame."""
    return hear(ESSENTIAL, lambda: post(frame, uimod.ID_CLEAR_FOCUSED))


def still_on_air(rows=3):
    return (len(frame.board.playlist) == rows and frame.player.playing
            and frame.player.index == 0)


def item_3():
    panel = frame.playlist_panel
    first_on_air()
    guard("the playlist is playing its first track",
          frame.player.playing and frame.player.index == 0)
    BOXES.clear()
    said = delete()
    check("the first Delete on the track on the air puts up no box",
          not BOXES, BOXES)
    check("and says what a second one does, at the essential level",
          said == [FIRST_DELETE], said)
    guard("nothing is removed or stopped by it", still_on_air())
    pump(0.2)
    said = delete()
    check("a second Delete on the same row, inside the window, removes it "
          "and stops the playlist",
          len(frame.board.playlist) == 2 and not frame.player.playing,
          (len(frame.board.playlist), frame.player.playing))
    check("and says so at the essential level",
          said == ["Removed Song 1. The playlist has stopped"], said)

    # The window going by starts again.
    first_on_air()
    window = getattr(C, "DELETE_ON_AIR_WINDOW_MS", None)
    C.DELETE_ON_AIR_WINDOW_MS = 300
    try:
        delete()
        pump(0.5)
        said = delete()
    finally:
        if window is None:
            del C.DELETE_ON_AIR_WINDOW_MS
        else:
            C.DELETE_ON_AIR_WINDOW_MS = window
    check("after the window a Delete is a first press again: said, and "
          "nothing removed", said == [FIRST_DELETE] and still_on_air(),
          (said, len(frame.board.playlist)))
    check("the window is a constant of its own, a few seconds long",
          window is not None and 2000 <= window <= 6000, window)

    # The cursor moving starts again, even back to the same row.
    first_on_air()
    delete()
    panel.select(1)
    panel.select(0)
    pump(0.1)
    said = delete()
    check("moving off the row and back starts again",
          said == [FIRST_DELETE] and still_on_air(),
          (said, len(frame.board.playlist)))

    # Another row in between goes at once, and starts it again.
    first_on_air()
    delete()
    panel.select(2)
    BOXES.clear()
    delete()
    guard("any other row goes at once, with no box", not BOXES
          and len(frame.board.playlist) == 2 and frame.player.playing,
          (BOXES, len(frame.board.playlist)))
    panel.select(0)
    said = delete()
    check("and the track on the air then wants its two presses again",
          said == [FIRST_DELETE] and still_on_air(2),
          (said, len(frame.board.playlist)))
    frame.stop_playlist(quiet=True)


section("3", item_3)


# ===========================================================================
heading("4. Streaming location says the key that really goes there")


def item_4():
    frame.board.stream_name = "Blindside Radio"
    frame.board.stream_host = "stream.example.com"
    frame.board.stream_mount = "/live"
    frame.board.stream_password = "hackme"
    frame.board.video_server = "youtube"
    frame.board.video_host = C.RTMP_INGEST["youtube"]
    frame.board.video_key = ""
    frame.board.live_to = C.LIVE_TO_VIDEO
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_LIVE_TO_AUDIO))
    check("picking My radio station says Alt+Shift+B goes live there",
          len(said) == 1 and said[0].startswith(
              "Alt+Shift+B goes live to Blindside Radio"), said)
    check("and never that Ctrl+B does", said and "Ctrl+B" not in said[0],
          said)
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_LIVE_TO_VIDEO))
    check("picking My video platform says Ctrl+B goes live there",
          len(said) == 1 and said[0].startswith("Ctrl+B goes live to your "
                                                "video platform"), said)

    report = frame.preflight()
    check("a radio presenter stopped by Ctrl+B is told the radio key",
          report is not None and report.blocked
          and report.stops[0].text.endswith(
              "For your radio station, press Alt+Shift+B"),
          report.stops if report else None)
    frame.board.ask_before_live = False
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_STREAM_TOGGLE))
    check("and it is what Ctrl+B itself says",
          said and "For your radio station, press Alt+Shift+B" in said[-1]
          and not frame.streaming(), said)
    frame.board.ask_before_live = True
    host = frame.board.stream_host
    frame.board.stream_host = ""
    report = frame.preflight()
    guard("a board with no radio station is not sent looking for one",
          report is not None and report.blocked and not any(
              "Alt+Shift+B" in note.text for note in report.stops),
          report.stops if report else None)
    frame.board.stream_host = host
    frame.board.live_to = C.LIVE_TO_AUDIO
    found = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import dropdeck.preflight; "
         "print('wx' in sys.modules)"
         % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))],
        capture_output=True, text=True, timeout=60)
    guard("preflight.py still imports no wx",
          found.stdout.strip() == "False", found.stdout + found.stderr)


section("4", item_4)


# ===========================================================================
heading("5. The Stop everything button counts what the board wants")


class Scripted(dialogs.SettingsDialog):
    script = None

    def ShowModal(self):
        return Scripted.script(self)

    @property
    def chosen_device(self):
        return (None, None, None)

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


def item_5():
    guard("the board this frame opened on wants the default",
          frame.board.stop_presses == C.DEFAULT_STOP_PRESSES == 2,
          frame.board.stop_presses)
    label = frame.FindWindowById(uimod.ID_STOP_ALL).GetLabel()
    check("the default board says Escape twice, which is what it takes",
          label == "Stop everything  (Escape twice)", label)
    item = frame.GetMenuBar().FindItemById(uimod.ID_STOP_ALL)
    check("and so does the menu item's help",
          item is not None and "Escape twice" in item.GetHelp(),
          item.GetHelp() if item else None)

    real = uimod.SettingsDialog
    uimod.SettingsDialog = Scripted

    def four(dialog):
        dialog.stop_presses.SetValue(4)
        return wx.ID_OK

    Scripted.script = staticmethod(four)
    try:
        frame._on_settings()
    finally:
        uimod.SettingsDialog = real
    pump(0.1)
    label = frame.FindWindowById(uimod.ID_STOP_ALL).GetLabel()
    check("Preferences changing it to four changes the button",
          frame.board.stop_presses == 4
          and label == "Stop everything  (Escape four times)", label)

    other = Board()
    other.stop_presses = 1
    path = os.path.join(TMP, "One press.json")
    other.save(path)
    frame._open_board(path)
    pump(0.1)
    label = frame.FindWindowById(uimod.ID_STOP_ALL).GetLabel()
    check("opening a board that wants one press says once",
          label == "Stop everything  (Escape once)", label)
    frame.board.speech_level = C.SPEECH_ALL


section("5", item_5)


# ===========================================================================
heading("6. F7 and F8 say what you hear only whenever the show is going out")


def item_6():
    keys = table(frame)
    guard("F7 and F8 are the playlist fader in the table",
          keys.get((wx.ACCEL_NORMAL, wx.WXK_F7)) == uimod.ID_VOL_PL_DOWN
          and keys.get((wx.ACCEL_NORMAL, wx.WXK_F8)) == uimod.ID_VOL_PL_UP)
    frame.board.playlist_monitor_only = True
    frame.mixer.playlist_monitor_only = True
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_VOL_PL_DOWN))
    guard("with nothing going out it is just the volume",
          said and "what you hear only" not in said[-1], said)
    frame.send = FakeSend()
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_VOL_PL_UP))
    check("with the send running, F8 says it is what you hear only",
          said and said[-1].endswith(", what you hear only"), said)
    frame.send = None
    frame.board.record_folder = tempfile.mkdtemp(prefix="dropdeck-speech-rec-")
    started = frame.start_recording()
    try:
        said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_VOL_PL_DOWN))
        check("and with a recording running, F7 says it too",
              started and said and said[-1].endswith(", what you hear only"),
              (started, said))
    finally:
        frame.stop_recording(quiet=True)
    frame.board.playlist_monitor_only = False
    frame.mixer.playlist_monitor_only = False


section("6", item_6)


# ===========================================================================
heading("7. Alt+Enter on a playlist row opens its crossfade")


class ScriptedFade:
    """TrackCrossfadeDialog, answered: OK with two and a half seconds."""

    opened = []

    def __init__(self, parent, track, default_seconds):
        ScriptedFade.opened.append(track.display_name)
        self.result = 2.5

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def ShowModal(self):
        return wx.ID_OK


class ScriptedProperties:
    opened = []

    def __init__(self, parent, slot, taken=None):
        ScriptedProperties.opened.append(slot.index)

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def ShowModal(self):
        return wx.ID_CANCEL


def item_7():
    keys = table(frame)
    guard("Alt+Enter is properties in the table",
          keys.get((wx.ACCEL_ALT, wx.WXK_RETURN)) == uimod.ID_PROPERTIES)
    panel = frame.playlist_panel
    frame.board.playlist.clear()
    panel.refresh()
    panel.add_paths(SONGS)
    focus_list()
    panel.select(1)
    real_fade, real_props = uimod.TrackCrossfadeDialog, \
        uimod.SlotPropertiesDialog
    uimod.TrackCrossfadeDialog = ScriptedFade
    uimod.SlotPropertiesDialog = ScriptedProperties
    try:
        said = hear(C.SPEECH_ALL, lambda: post(frame, uimod.ID_PROPERTIES))
        check("Alt+Enter on a row opens that track's crossfade",
              ScriptedFade.opened == ["Song 2"], ScriptedFade.opened)
        check("and what is chosen there is the track's",
              frame.board.playlist[1].crossfade == 2.5,
              frame.board.playlist[1].crossfade)
        check("it no longer says the key is for the soundboard",
              not any("for the soundboard" in s for s in said), said)
        frame.show_view(uimod.VIEW_BOARD)
        pump(0.1)
        button = frame.pages[frame._current_bank()].first_visible()
        button.SetFocus()
        pump(0.1)
        hear(C.SPEECH_ALL, lambda: post(frame, uimod.ID_PROPERTIES))
        guard("Alt+Enter on a pad still opens its properties",
              ScriptedProperties.opened == [button.slot.index],
              ScriptedProperties.opened)
    finally:
        uimod.TrackCrossfadeDialog = real_fade
        uimod.SlotPropertiesDialog = real_props


section("7", item_7)


# ===========================================================================
heading("8. Assign a global hotkey off a pad says what to do")


def item_8():
    focus_list()
    said = hear(ESSENTIAL, lambda: post(frame, uimod.ID_GLOBAL_HOTKEY))
    check("with focus off a pad it says to move to one, at the essential "
          "level", said == ["Move to a sound button first"], said)


section("8", item_8)


# ===========================================================================
heading("9. Menu speech waits for the menu; a view swap says where you are")


def close_a_menu():
    """What Windows sends when a menu closes, to the frame's own binding."""
    event = wx.MenuEvent(wx.wxEVT_MENU_CLOSE, 0, None)
    event.SetEventObject(frame)
    frame.GetEventHandler().ProcessEvent(event)


def item_9():
    frame.board.speech_level = C.SPEECH_ALL
    frame._menu_closed_at = None
    ear.said.clear()
    close_a_menu()
    post(frame, uimod.ID_WHATS_PLAYING)
    at_once = list(ear.said)
    pump((C.AFTER_MENU_SPEECH_MS + 300) / 1000.0)
    check("Ctrl+L from a menu is not said under the screen reader's reading "
          "of the focus", not at_once, at_once)
    check("it is said after the wait, queued behind that reading",
          ear.said and ear.said[-1][1] is False
          and "playing" in ear.said[-1][0].lower(), ear.said)

    pad = frame.board[0]
    pad.filepath = wav("Applause", 1.0)
    pad.name = "Applause"
    frame._menu_closed_at = None
    ear.said.clear()
    close_a_menu()
    post(frame, uimod.ID_SLOT_BASE + pad.index)
    at_once = list(ear.said)
    pump((C.AFTER_MENU_SPEECH_MS + 300) / 1000.0)
    check("a sound started from a menu is named after the wait, not under it",
          not at_once and ear.said and ear.said[-1][0].startswith("Applause")
          and ear.said[-1][1] is False, (at_once, ear.said))
    frame.mixer.stop_all(fade_out=0.0)

    keys = table(frame)
    guard("Alt+Shift+W is the swap in the table",
          keys.get((wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("W")))
          == uimod.ID_VIEW_NEXT)
    frame.board.playlist.clear()
    frame.playlist_panel.refresh()
    frame.playlist_panel.add_paths(SONGS)
    frame.show_view(uimod.VIEW_BOARD)
    pump(0.1)
    said = hear(C.SPEECH_ALL, lambda: post(frame, uimod.ID_VIEW_NEXT))
    check("swapping to the playlist says Playlist and not the whole summary",
          said == ["Playlist"], said)
    said = hear(C.SPEECH_ALL, lambda: post(frame, uimod.ID_VIEW_NEXT))
    check("swapping back says the soundboard and the bank, nothing more",
          said == ["Soundboard, %s"
                   % frame.board.bank_name(frame._current_bank())], said)
    frame.show_view(uimod.VIEW_PLAYLIST)
    pump(0.1)
    said = hear(C.SPEECH_ALL, lambda: post(frame, uimod.ID_VIEW_PLAYLIST))
    guard("the summary is still there, from the key for where you already are",
          said and "3 items" in said[-1], said)


section("9", item_9)


# ===========================================================================
heading("10. The search count waits, and every dialog honours the level")


def type_into(search, words):
    for n in range(1, len(words) + 1):
        search.query.SetValue(words[:n])


def item_10():
    for n, name in enumerate(("Sting One", "Sting Two", "Stinger")):
        frame.board[n].filepath = wav(name.replace(" ", "_"), 0.5)
        frame.board[n].name = name

    def open_search():
        search = dialogs.SearchDialog(frame, frame.board, ())
        search.Show()
        pump(0.1)
        return search

    search = open_search()
    frame.board.speech_level = C.SPEECH_ALL
    ear.said.clear()
    type_into(search, "sting")
    at_once = list(ear.texts)
    pump((C.SEARCH_COUNT_DELAY_MS + 300) / 1000.0
         if hasattr(C, "SEARCH_COUNT_DELAY_MS") else 0.7)
    check("nothing is said on each keystroke", not at_once, at_once)
    check("the count is said once, after typing stops",
          ear.texts == ["3 matches"], ear.texts)
    frame.board.speech_level = C.SPEECH_ESSENTIAL
    ear.said.clear()
    search.query.SetValue("stinge")
    search.query.SetValue("stinger")
    pump(0.7)
    check("at essential it is still said, because it cannot otherwise be "
          "known from the box, and once for two letters",
          ear.texts == ["1 match"], ear.texts)
    frame.board.speech_level = C.SPEECH_NONE
    ear.said.clear()
    search.query.SetValue("sting o")
    pump(0.7)
    check("at none it is not said", ear.texts == [], ear.texts)
    guard("and the list still shows it", search.results.GetCount() == 1,
          search.results.GetCount())
    frame.board.speech_level = C.SPEECH_ALL
    ear.said.clear()
    search.query.SetValue("st")
    search.Hide()
    pump(0.7)
    check("nothing is said about a search that has closed", ear.texts == [],
          ear.texts)
    ear.said.clear()
    search.Show()
    search.query.SetValue("sti")
    search.Destroy()
    pump(0.7)
    check("nor about one that has gone", ear.texts == [], ear.texts)

    # The dialogs' own lines.
    hotkey = dialogs.AssignHotkeyDialog(frame, frame.board[0])
    said = hear(C.SPEECH_NONE, lambda: hotkey._on_clear(None))
    check("the hotkey window says nothing at none", said == [], said)
    said = hear(C.SPEECH_ESSENTIAL, lambda: hotkey._on_clear(None))
    guard("and still says what it did at essential",
          said == ["Hotkey cleared."], said)
    hotkey.Destroy()
    props = dialogs.SlotPropertiesDialog(frame, frame.board[0])
    said = hear(C.SPEECH_ESSENTIAL, lambda: props._say("Hotkey Ctrl+1"))
    check("Properties' confirmation of a key is for the all level",
          said == [], said)
    props.Destroy()
    library = dialogs.DropsLibraryDialog(frame, frame.board.drops)
    said = hear(C.SPEECH_ESSENTIAL, lambda: library._say("Removed Sting"))
    check("the drops library's confirmations are for the all level",
          said == [], said)
    library.Destroy()
    preview = dialogs.NativePreview(None, frame)
    said = hear(C.SPEECH_NONE, lambda: preview._say("x.mid will not play "
                                                    "here"))
    check("the file window preview says nothing at none", said == [], said)
    frame.board.speech_level = C.SPEECH_ALL


section("10", item_10)


# ===========================================================================
heading("11. No two things you can see at once share a letter")


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


def clashes(menu):
    return {k: v for k, v in level_letters(menu).items() if len(v) > 1}


def on_air_menu():
    bar = frame.GetMenuBar()
    return bar.GetMenu(bar.FindMenu("On air"))


def window_letters(window):
    found = {}

    def walk(parent):
        for child in parent.GetChildren():
            if isinstance(child, wx.TopLevelWindow) or not child.IsShown():
                continue
            if not isinstance(child, (wx.TextCtrl, wx.ListBox, wx.ListCtrl,
                                      wx.Choice, wx.ComboBox)):
                label = child.GetLabel().replace("&&", "")
                if "&" in label:
                    found.setdefault(label[label.index("&") + 1].lower(),
                                     []).append(label)
            walk(child)

    walk(window)
    return {k: v for k, v in found.items() if len(v) > 1}


POPPED = []


def capture_popup(self, menu, *args, **kw):
    POPPED.append(level_letters(menu))
    return True


def item_11():
    frame.board.live_to = C.LIVE_TO_VIDEO
    frame._set_air_labels(True)
    found = clashes(on_air_menu())
    check("live on video, On air has no letter twice", not found, found)
    frame.board.live_to = C.LIVE_TO_AUDIO
    frame._set_air_labels(True)
    found = clashes(on_air_menu())
    check("live on radio, the same", not found, found)
    frame._set_air_labels(False)
    frame.send = FakeSend()
    frame._sync_send_menu()
    found = clashes(on_air_menu())
    check("while sending, the same", not found, found)
    frame._set_air_labels(True)
    frame._set_record_label(True)
    frame._set_video_record_label(True)
    found = clashes(on_air_menu())
    check("and live, sending and recording at once, the same", not found,
          found)
    frame.send = None
    frame._sync_send_menu()
    frame._set_air_labels(False)
    frame._set_record_label(False)
    frame._set_video_record_label(False)

    # The two menus a key opens on one thing.
    real = {cls: cls.__dict__.get("PopupMenu")
            for cls in (wx.Window, wx.ListCtrl, wx.Button)}
    for cls in real:
        cls.PopupMenu = capture_popup
    try:
        panel = frame.playlist_panel
        frame.board.playlist.clear()
        panel.refresh()
        panel.add_paths(SONGS)
        # A drop, so the row menu grows "Add this drop to the library".
        frame.board.playlist.insert_drop(wav("Station ID", 1.0), at=1)
        panel.refresh()
        frame.play_playlist(0)
        pump(0.1)
        for row in range(len(frame.board.playlist)):
            panel.select(row)
            POPPED.clear()
            event = wx.ContextMenuEvent(wx.wxEVT_CONTEXT_MENU, panel.list.GetId())
            event.SetEventObject(panel.list)
            panel.list.GetEventHandler().ProcessEvent(event)
            found = {k: v for k, v in (POPPED[0] if POPPED else {}).items()
                     if len(v) > 1}
            check("the playlist row menu on row %d, playing, has no letter "
                  "twice" % (row + 1), POPPED and not found, (POPPED, found))
        frame.stop_playlist(quiet=True)
        bed = frame.board.bank_slots(C.LOOPING_BANK)[0]
        bed.filepath = wav("Bed", 2.0)
        bed.name = "Bed"
        POPPED.clear()
        frame.show_slot_menu(bed, frame._button_for(bed))
        found = {k: v for k, v in (POPPED[0] if POPPED else {}).items()
                 if len(v) > 1}
        check("the bed menu has no letter twice", POPPED and not found,
              (POPPED, found))
    finally:
        for cls, method in real.items():
            if method is None:
                try:
                    del cls.PopupMenu
                except AttributeError:
                    pass
            else:
                cls.PopupMenu = method

    from dropdeck import colours
    feedback = dialogs.FeedbackDialog(frame, frame)
    found = window_letters(feedback)
    check("Submit feedback has no letter twice", not found, found)
    feedback.Destroy()
    shot = dialogs.ShotCheckDialog(frame, frame)
    found = window_letters(shot)
    check("Check my shot has no letter twice", not found, found)
    shot.Destroy()
    pick = dialogs.ColourChoiceDialog(
        frame, "Words", frame.board.colour_text,
        colours.rgb(frame.board.colour_background), "the background")
    found = window_letters(pick)
    check("the colour picker has no letter twice", not found, found)
    pick.Destroy()


section("11", item_11)


# ===========================================================================
heading("12. The microphone item is Microphone, ticked or not")


def item_12():
    item = frame.mic_item
    check("its label is Microphone, with M and Ctrl+M",
          item.GetItemLabel() == "&Microphone" + chr(9) + "Ctrl+M",
          item.GetItemLabel())
    guard("it is still a check item, so the tick says the state",
          item.IsCheckable())


section("12", item_12)


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

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
print("%d/%d guards passed" % (sum(GUARDS), len(GUARDS)))
if FAILED:
    print("FAILED:")
    for line in FAILED:
        print("  " + line)
sys.exit(1 if FAILED else 0)
