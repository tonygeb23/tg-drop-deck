"""Review of 24 November 2026, Area 2: security.

    python tools/run_private.py tests/test_review_security.py

A board file is plain JSON that people send each other, and every fault here
was a board file, or an export of one, doing something its reader never
agreed to: loading a DLL from anywhere, sending the stream key to its own
server, carrying the Icecast password and the user's folders to whoever got
the export, recording to a share, reading a file through the listener
count, and taking Ctrl+C and Shift+A from every program on the machine. Plus
the shot check's Ask box sending the screen unasked, an uninstaller that
emptied whatever folder it had been pointed at, and two key store slips.

Every fix has a check here that fails on 3.10.1 and passes on the fix. A few
more are guards that the ordinary case still works, and pass on both.

**Nothing here reaches Tony's Credential Manager.** `secrets._advapi` hands
back a stand-in for advapi32's four credential calls, over a dictionary, so
the old code and the new one both talk to it and neither talks to Windows.
Nothing here opens a sound card, a microphone, a camera or a socket: the
mixer runs with no stream, the streamer is a stand-in that records what it
was given, global hotkeys register nothing, and the one network library call
that could have gone out is replaced by a recorder.
"""

import ctypes
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-security-")

import wx                                                     # noqa: E402

from dropdeck import board as boardmod                        # noqa: E402
from dropdeck import constants as C                           # noqa: E402
from dropdeck import dialogs                                  # noqa: E402
from dropdeck import dsp                                      # noqa: E402
from dropdeck import globalhotkeys                            # noqa: E402
from dropdeck import mixer as mixermod                        # noqa: E402
from dropdeck import preflight                                # noqa: E402
from dropdeck import secrets                                  # noqa: E402
from dropdeck import sources as sourcesmod                    # noqa: E402
from dropdeck import streamout                                # noqa: E402
from dropdeck import streamstats                              # noqa: E402
from dropdeck import ui as uimod                              # noqa: E402
from dropdeck import vision                                   # noqa: E402
from dropdeck import vst                                      # noqa: E402
from dropdeck.board import Board                              # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail != "" and not condition else ""))


def heading(text):
    print("\n" + text)


def attempt(label, action, detail=None):
    """A check whose question may raise on the old code, which is a fail."""
    try:
        ok = action()
    except Exception as exc:
        check(label + " (raised %s: %s)" % (type(exc).__name__, exc), False)
        return
    check(label, ok, detail() if callable(detail) else ("" if detail is None
                                                        else detail))


# ------------------------------------------------- the credential store --
class FakeCredentials:
    """advapi32's CredWriteW, CredReadW, CredDeleteW and CredFree, over a
    dictionary of target -> (text, user name). `refuse` makes every write
    fail, the way a locked down credential store does."""

    def __init__(self):
        self.held = {}
        self.refuse = False
        self._alive = []
        store = self

        def CredWriteW(credential, flags):
            if store.refuse:
                return 0
            record = credential._obj
            size = int(record.CredentialBlobSize)
            text = (ctypes.string_at(record.CredentialBlob, size)
                    .decode("utf-16-le") if size else "")
            store.held[record.TargetName] = (text, record.UserName or "")
            return 1

        def CredReadW(target, kind, flags, out):
            if target not in store.held:
                return 0
            text, user = store.held[target]
            blob = text.encode("utf-16-le")
            buffer = (ctypes.c_byte * max(1, len(blob))).from_buffer_copy(
                blob or b"\0")
            record = secrets._CREDENTIAL()
            record.TargetName = target
            record.UserName = user
            record.CredentialBlobSize = len(blob)
            record.CredentialBlob = ctypes.cast(buffer,
                                                ctypes.POINTER(ctypes.c_byte))
            self._alive.append((buffer, record))
            out._obj.contents = record
            return 1

        def CredDeleteW(target, kind, flags):
            return 1 if store.held.pop(target, None) is not None else 0

        def CredFree(pointer):
            return None

        self.CredWriteW, self.CredReadW = CredWriteW, CredReadW
        self.CredDeleteW, self.CredFree = CredDeleteW, CredFree

    def user_of(self, station, prefix=secrets.TARGET_PREFIX):
        return self.held.get(secrets.target_for(station, prefix), ("", ""))[1]

    def text_of(self, station, prefix=secrets.TARGET_PREFIX):
        return self.held.get(secrets.target_for(station, prefix), ("", ""))[0]

    def keep_old_style(self, station, key):
        """A key as 3.10.1 wrote it: no server written down beside it."""
        self.held[secrets.target_for(station)] = (key, "stream")


VAULT = FakeCredentials()
secrets._advapi = lambda: VAULT

YOUTUBE = C.RTMP_INGEST["youtube"]
ATTACKER = "rtmps://ingest.attacker.example/live2"
WEBDAV = "\\\\attacker.example@SSL\\DavWWWRoot\\shows"
EVIL_PLUGIN = "\\\\attacker.example@SSL\\DavWWWRoot\\x.vst3"

# ------------------------------------------------------------- stand-ins --
app = wx.App(False)
BOXES = []


def fake_box(message, caption="", style=0, parent=None, *rest, **kw):
    BOXES.append((caption, message))
    return wx.OK


wx.MessageBox = fake_box


class QuietGroup(mixermod.MixerGroup):
    def __init__(self, *args, **kw):
        kw["open_stream"] = False
        super().__init__(*args, **kw)

    @property
    def is_running(self):
        # No card is opened, and the pre-flight would stop every broadcast
        # for that. Nothing reaches a card either way.
        return True


uimod.MixerGroup = QuietGroup
uimod.resolve_input = lambda spec: None
sourcesmod.resolve_input = lambda spec: None
uimod.DropDeckFrame._start_update_check = lambda self: None
uimod.DropDeckFrame._maybe_ask_about_donating = lambda self: None


class FakeHotkeys:
    """Global hotkeys that register nothing with Windows."""

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
        return len(self.bindings) if self.enabled else 0


REAL_HOTKEYS = globalhotkeys.GlobalHotkeys
uimod.globalhotkeys.GlobalHotkeys = FakeHotkeys

#: Every plugin the app asked to load. A plugin is a DLL, and the stand-in
#: never touches the path, which could be a share.
LOADS = []
REAL_VST_LOAD = vst.load


def fake_vst_load(path):
    LOADS.append(path)
    raise vst.LoadFailed("a stand-in loads nothing")


vst.load = fake_vst_load


class FakeStreamer:
    """What start_stream hands the stream to. It connects to nothing."""

    made = []

    def __init__(self, air_bus, settings, **kw):
        self.settings = dict(settings)
        self.running = False
        self.state = streamout.CONNECTING
        self.detail = self.error = ""
        self.backlog = self.reconnects = 0
        self.on_air_for = 0.0
        self.wants_video = bool(kw.get("video_source"))
        FakeStreamer.made.append(self)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def set_title(self, *a, **kw):
        pass

    def set_frame_tap(self, *a, **kw):
        pass

    def set_overlay(self, *a, **kw):
        pass

    def set_video_source(self, *a, **kw):
        pass


streamout.Streamer = FakeStreamer


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


def command(frame, ident):
    """A menu command or key, posted to the window that receives it."""
    event = wx.CommandEvent(wx.wxEVT_MENU, ident)
    event.SetEventObject(frame)
    frame.GetEventHandler().ProcessEvent(event)


def pump_until(done, seconds=5.0):
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


def saved(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


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

    def ShowModal(self):
        return Scripted.script(self)


uimod.SettingsDialog = Scripted


def preferences(frame, script):
    Scripted.script = staticmethod(script)
    frame._on_settings()


HOME = tempfile.mkdtemp(prefix="dropdeck-security-boards-")


def write_board(name, data):
    path = os.path.join(HOME, name)
    data = dict(data)
    data.setdefault("app", C.APP_NAME)
    data.setdefault("format", 2)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)
    return path


# ===========================================================================
heading("1. A board can only ask for a plugin that is installed here")

attempt("a plugin on a share is not one of the installed ones",
        lambda: vst.is_installed(EVIL_PLUGIN) is False)
real_exists = os.path.exists
touched = []
# Answers for the disk without asking it, so the old loader cannot reach out
# to the share either.
os.path.exists = lambda p: touched.append(p) or False
try:
    try:
        REAL_VST_LOAD(EVIL_PLUGIN)
        refused = False
    except vst.LoadFailed:
        refused = True
finally:
    os.path.exists = real_exists
check("the loader itself refuses it", refused)
check("without asking the disk about the path, which would reach the share",
      EVIL_PLUGIN not in touched, touched)
INSTALLED = vst.installed()
if INSTALLED:
    attempt("one that IS installed is allowed",
            lambda: vst.is_installed(INSTALLED[0][1]))
    attempt("whatever case and slashes it is written in",
            lambda: vst.is_installed(INSTALLED[0][1].upper().replace(
                "\\", "/")))
else:
    check("SKIPPED: no VST3 installed on this machine to allow", True)

# ===========================================================================
heading("The startup board: a plugin, a recording folder, hotkeys, a password")

MIXCLOUD = "rtmp://live.mixcloud.example/live"
SECOND = "rtmp://second.example/app"
NAS = "\\\\nas.example\\shows"
START = write_board("Startup.json", {
    "voice_on": True, "voice_settings": {"plugin": EVIL_PLUGIN},
    "record_folder": NAS,
    "global_hotkeys_on": True,
    "stream_name": "Night Shift", "stream_host": "radio.example.org",
    "stream_password": "hunter2",
    "live_to": "video", "ask_before_live": False,
    "video_server": "rtmp", "video_host": MIXCLOUD,
    "stream_stations": [{"stream_name": "Second Show",
                         "video_server": "rtmp", "video_host": SECOND}],
    "slots": [{"global_hotkey": "Ctrl+C"}, {"global_hotkey": "Shift+A"},
              {"global_hotkey": "Ctrl+Alt+F9"}],
})
# What 3.10.1 left in Credential Manager: keys by station name, with no
# server written beside them. Two the startup board names, one it does not.
VAULT.keep_old_style("Night Shift", "MIXCLOUD-KEY")
VAULT.keep_old_style("Second Show", "SECOND-KEY")
VAULT.keep_old_style("Elsewhere", "ELSEWHERE-KEY")
boardmod.remember_board_path(START)
frame = uimod.DropDeckFrame(None)
heard = listen(frame)
app.ProcessPendingEvents()
pump_until(lambda: False, 0.5)
check("the startup board is the one that opened",
      boardmod.same_path(frame.board.path, START), frame.board.path)
line = ""
try:
    frame._startup_line()
    line = heard[-1] if heard else ""
except Exception as exc:
    line = "raised %s" % exc
CHAIN = getattr(frame.mic, "chain", None)
if dsp.available() and CHAIN is not None:
    check("at startup the plugin is never handed to the loader",
          LOADS == [], LOADS)
    check("the voice chain runs without it", CHAIN.plugin is None)
    check("and the startup line says so, by name",
          "This board asks for a voice plugin that is not installed here, x, "
          "so the voice runs without it" in line, line)
else:
    check("SKIPPED: no voice chain in this copy, so nothing to load", True)
check("the NAS the user's own board records to is kept at the first start",
      frame.board.record_folder == NAS, frame.board.record_folder)
check("and the startup line does not call it refused",
      "not a folder on this computer" not in line, line)
MACHINE = os.path.join(boardmod.config_dir(), getattr(
    boardmod, "MACHINE_FILE", "this computer.json"))
machine = json.load(open(MACHINE, encoding="utf-8")) \
    if os.path.exists(MACHINE) else {}
check("it is written down as picked on this computer, outside the board",
      NAS in (machine.get("record_folders") or []), machine)
check("the startup line names the global hotkeys that are not used, and why",
      "Ctrl+C on" in line and "is copy" in line and "Shift+A on" in line
      and "types a character" in line, line)
check("they are never offered to Windows",
      frame.hotkeys.bindings == {2: "Ctrl+Alt+F9"}, frame.hotkeys.bindings)
check("the station password went into Credential Manager",
      VAULT.text_of("Night Shift", getattr(secrets, "PASSWORD_PREFIX", "?"))
      == "hunter2", sorted(VAULT.held))
check("tied to the station's server",
      VAULT.user_of("Night Shift", getattr(secrets, "PASSWORD_PREFIX", "?"))
      == "for radio.example.org",
      VAULT.user_of("Night Shift", getattr(secrets, "PASSWORD_PREFIX", "?")))
frame._autosave()
on_disk = saved(START)
check("and once it is kept, it is not in the board file any more",
      on_disk.get("stream_password") == "", on_disk.get("stream_password"))
check("the folder stays in the user's own board file",
      on_disk.get("record_folder") == NAS, on_disk.get("record_folder"))
check("the hotkeys that are not used stay on their pads in the file",
      [s.get("global_hotkey") for s in on_disk["slots"][:3]]
      == ["Ctrl+C", "Shift+A", "Ctrl+Alt+F9"],
      [s.get("global_hotkey") for s in on_disk["slots"][:3]])
check("and the live board still has the password to broadcast with",
      frame.board.stream_password == "hunter2")

heading("The first start ties the keys 3.10.1 kept to the user's own servers")
check("the startup station's key is tied to the custom server it names",
      VAULT.user_of("Night Shift") == "for " + MIXCLOUD,
      VAULT.user_of("Night Shift"))
check("and a saved station's to the server that station names",
      VAULT.user_of("Second Show") == "for " + SECOND,
      VAULT.user_of("Second Show"))
check("a key the user's board does not name is left untied",
      VAULT.user_of("Elsewhere") == "stream", VAULT.user_of("Elsewhere"))
machine = json.load(open(MACHINE, encoding="utf-8")) \
    if os.path.exists(MACHINE) else {}
check("and it is written down that this was done",
      machine.get("upgrade_trusted") is True, machine)
FakeStreamer.made.clear()
heard.clear()
command(frame, uimod.ID_STREAM_TOGGLE)
made = FakeStreamer.made[-1] if FakeStreamer.made else None
check("so Ctrl+B goes live on the custom server at the first show, no "
      "retyping", made is not None
      and made.settings.get("host") == MIXCLOUD
      and made.settings.get("password") == "MIXCLOUD-KEY",
      [line for line in heard if "stream key" in line])
if frame.streaming():
    frame.stop_stream(quiet=True)
VAULT.keep_old_style("Second Show", "SECOND-KEY")
attempt("it happens once: the next start ties nothing",
        lambda: frame._trust_own_board_once() is None
        and VAULT.user_of("Second Show") == "stream")
VAULT.held[secrets.target_for("Second Show")] = ("SECOND-KEY", "for " + SECOND)

heading("A board changed on disk while it is open is held to the same rule")
LOADS.clear()
heard.clear()
outside = saved(START)
outside["voice_settings"] = {"plugin": EVIL_PLUGIN.replace("x.vst3", "y.vst3")}
time.sleep(0.02)
with open(START, "w", encoding="utf-8") as handle:
    json.dump(outside, handle)
frame.board.dirty = False
frame._check_board_file(wait=True)
reloaded = loaded_line(heard)
check("the copy on disk is loaded when the window comes back",
      reloaded.startswith("Loaded Startup"), heard)
if dsp.available() and CHAIN is not None:
    pump_until(lambda: bool(LOADS), 0.5)
    check("on a reload the plugin is never handed to the loader",
          LOADS == [], LOADS)
    check("and the Loaded line says so, by name",
          "voice plugin that is not installed here, y" in reloaded, reloaded)
check("the station password comes back from Credential Manager",
      frame.board.stream_password == "hunter2", frame.board.stream_password)

# ===========================================================================
heading("File, Open on a board that asks for all of it")

EVIL = write_board("Evil.json", {
    "stream_name": "", "video_server": "youtube", "video_host": ATTACKER,
    "live_to": "video", "ask_before_live": False,
    "voice_on": True, "voice_settings": {"plugin": EVIL_PLUGIN},
    "record_folder": WEBDAV, "stream_stats_url": "file:///C:/Windows/win.ini",
    "stream_stations": [{"stream_name": "Blindside Radio",
                         "stream_password": "hunter2",
                         "video_server": "youtube", "video_host": ATTACKER,
                         "stream_stats_url": "ftp://attacker.example/x"}],
    "slots": [],
})
# What 3.10.1 kept for somebody who never named their station: a YouTube key
# under "the current station", with no server written beside it.
VAULT.keep_old_style("", "VICTIM-YOUTUBE-KEY")
LOADS.clear()
heard.clear()
check("it opens", frame._open_board(EVIL) is True)
opened = loaded_line(heard)
if dsp.available() and CHAIN is not None:
    pump_until(lambda: bool(LOADS), 0.5)
    check("on open the plugin is never handed to the loader", LOADS == [],
          LOADS)
    check("and the Loaded line says so, by name",
          "voice plugin that is not installed here, x" in opened, opened)
check("the Loaded line says the recording folder was not kept",
      "not a folder on this computer" in opened, opened)
check("YouTube's address is YouTube's, whatever the file says",
      frame.board.video_host == YOUTUBE, frame.board.video_host)
check("the listener count will not read a file",
      frame.board.stream_stats_url == "", frame.board.stream_stats_url)
attempt("nor will the saved station's, when it is picked",
        lambda: frame.board.load_station("Blindside Radio")
        and frame.board.stream_stats_url == ""
        and frame.board.video_host == YOUTUBE,
        lambda: (frame.board.stream_stats_url, frame.board.video_host))
frame.board.stream_name = ""

heading("2. Ctrl+B on that board: the key goes to YouTube and nowhere else")
FakeStreamer.made.clear()
command(frame, uimod.ID_STREAM_TOGGLE)
made = FakeStreamer.made[-1] if FakeStreamer.made else None
check("it went live, as the board asked",
      made is not None and made.running, FakeStreamer.made)
check("to YouTube's own ingest, not the board's server",
      made is not None and made.settings.get("host") == YOUTUBE,
      made and made.settings.get("host"))
check("and the key kept by 3.10.1 is now tied to YouTube, the first time "
      "it is used there", VAULT.user_of("") == "for " + YOUTUBE,
      VAULT.user_of(""))
frame.stop_stream(quiet=True)

CUSTOM = write_board("Custom.json", {
    "stream_name": "Blindside Radio", "video_server": "rtmp",
    "video_host": ATTACKER, "live_to": "video", "ask_before_live": False,
    "slots": []})
VAULT.held[secrets.target_for("Blindside Radio")] = ("BLINDSIDE-KEY",
                                                     "for " + YOUTUBE)
heard.clear()
check("a board naming the station and its own server opens",
      frame._open_board(CUSTOM) is True)
summary = frame.preflight()
check("the go live summary names the server, which is not a platform's",
      summary is not None and "ingest.attacker.example" in summary.summary(),
      summary and summary.summary())
check("the pre-flight stops it", summary is not None and summary.blocked,
      summary and [n.text for n in summary.notes])
check("with a plain sentence saying whose key it is and why it stays here",
      summary is not None and summary.stops
      and "is for a.rtmps.youtube.com, not ingest.attacker.example"
      in summary.stops[0].text, summary and summary.stops
      and summary.stops[0].text)
FakeStreamer.made.clear()
heard.clear()
command(frame, uimod.ID_STREAM_TOGGLE)
check("Ctrl+B does not go live", not FakeStreamer.made
      and not frame.streaming(), FakeStreamer.made)
check("and says why, out loud",
      any("is for a.rtmps.youtube.com" in line for line in heard), heard)
attempt("start_stream refuses it too, whoever calls it",
        lambda: frame.start_stream() is False and not FakeStreamer.made)
check("the key itself was never put in the settings",
      frame._stream_settings().get("password") != "BLINDSIDE-KEY")
if frame.streaming():
    frame.stop_stream(quiet=True)

heading("A key kept by 3.10.1 does not go to a server nobody tied it to")
VAULT.keep_old_style("Blindside Radio", "OLD-BLINDSIDE-KEY")
held = frame._stream_settings()
check("it is held back for a custom server",
      held.get("password") == "" and held.get("key_held"),
      (held.get("password"), held.get("key_held")))
check("and the pre-flight says how to bring it back",
      any("type the key again on the Video streaming page" in n.text
          for n in frame.preflight().stops),
      [n.text for n in frame.preflight().notes])
box = dialogs.SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic,
                             page=dialogs.SettingsDialog.PAGE_VIDEO)
check("Preferences does not put a held key in the box, where Check could "
      "send it to that server", box.video_settings["key"] == "",
      box.video_settings["key"])
box.Destroy()


def ok_untouched(dialog):
    return wx.ID_OK


preferences(frame, ok_untouched)
check("OK with that box untouched and empty does not delete the key",
      VAULT.text_of("Blindside Radio") == "OLD-BLINDSIDE-KEY",
      VAULT.text_of("Blindside Radio"))


def type_the_key(dialog):
    dialog.video_key.SetValue("OLD-BLINDSIDE-KEY")
    return wx.ID_OK


preferences(frame, type_the_key)
check("typing it again ties it to the server beside it, so it works there",
      frame._stream_settings().get("password") == "OLD-BLINDSIDE-KEY"
      and VAULT.user_of("Blindside Radio") == "for " + ATTACKER,
      VAULT.user_of("Blindside Radio"))

heading("An empty station name is not a wildcard")
VAULT.held[secrets.target_for("")] = ("UNNAMED-KEY", "for " + YOUTUBE)
frame.board.stream_name = ""
frame.board.video_server, frame.board.video_host = "rtmp", ATTACKER
check("a board with no station name does not get the unnamed setup's key "
      "for its own server", frame._stream_settings().get("password") == "",
      frame._stream_settings().get("password"))
frame.board.video_server, frame.board.video_host = "youtube", YOUTUBE
check("nor a key saved for a NAMED station",
      frame._stream_settings().get("password") not in ("BLINDSIDE-KEY",
                                                       "OLD-BLINDSIDE-KEY"))
check("the summary for YouTube's own ingest still just says YouTube Live",
      frame.preflight().summary() == "YouTube Live",
      frame.preflight().summary())
check("a board that says youtube and names another server is summarised "
      "with that server, whatever built the settings",
      "ingest.attacker.example" in preflight.where_it_goes(
          {"server": "youtube", "host": ATTACKER}, True))

# ===========================================================================
heading("3a. An export leaves out the passwords and the user's own folders")

PICTURE = os.path.join(HOME, "my card.png")
with open(PICTURE, "wb") as handle:
    handle.write(b"\x89PNG\r\n\x1a\n not really a picture")
SOUND = os.path.join(HOME, "drop.wav")
with open(SOUND, "wb") as handle:
    handle.write(b"RIFF not really a sound")
VAULT.refuse = True        # so the password and the key stay on the board
share = Board()
share.slots[0].filepath = SOUND
share.stream_name, share.stream_host = "Blindside Radio", "blindsideradio.com"
share.stream_password = "hunter2"
share.video_key = "FALLBACK-KEY-1234"
share.record_folder = "C:\\Users\\tony\\Recordings"
share.last_sound_dir = "C:\\Users\\tony\\Music"
share.last_playlist_dir = "C:\\Users\\tony\\Shows"
share.picture, share.picture_file = C.PICTURE_IMAGE, PICTURE
share.voice_settings = {"plugin": "C:\\Users\\tony\\AppData\\Local\\Programs"
                                  "\\Common\\VST3\\Phasis.vst3"}
share.save_station()
share.stream_stations.append({"stream_name": "Other", "stream_password": "pw2",
                              "video_key": "OTHER-KEY",
                              "picture_file": os.path.join(HOME, "gone.png")})
share_path = os.path.join(HOME, "Share.json")
share.save(share_path)
check("the board's own file still has them, so the board works",
      "hunter2" in open(share_path, encoding="utf-8").read())
frame._open_board(share_path)
target = os.path.join(tempfile.mkdtemp(prefix="dropdeck-export-"), "Shared")
heard.clear()
frame._run_export(target, "Shared show")
pump_until(lambda: not frame._exporting, 15)
exported = os.path.join(target, "Shared show.json")
text = open(exported, encoding="utf-8").read() if os.path.exists(exported) \
    else ""
data = json.loads(text) if text else {}
check("the export was written", bool(data))
check("no Icecast password in it, anywhere", "hunter2" not in text
      and "pw2" not in text)
check("no stream key the credential store refused, anywhere",
      "FALLBACK-KEY-1234" not in text and "OTHER-KEY" not in text)
check("no recording folder, and not the folders sounds came from",
      data.get("record_folder") == "" and data.get("last_sound_dir") == ""
      and data.get("last_playlist_dir") == "",
      (data.get("record_folder"), data.get("last_sound_dir")))
check("the voice plugin goes by its file name alone",
      (data.get("voice_settings") or {}).get("plugin") == "Phasis.vst3",
      (data.get("voice_settings") or {}).get("plugin"))
check("no path with the user's name in it at all", "tony" not in text.lower())
carried = data.get("picture_file", "")
check("the picture is carried beside the sounds, by a relative path",
      carried and not os.path.isabs(carried)
      and os.path.isfile(os.path.join(target, carried)), carried)
check("a station's picture that is not there is left out",
      [s.get("picture_file") for s in data.get("stream_stations", [])
       if s.get("stream_name") == "Other"] == [""],
      [s.get("picture_file") for s in data.get("stream_stations", [])])
check("and the confirmation says so",
      any("Passwords and your own folders were left out" in line
          for line in heard), heard[-1:] if heard else heard)
check("it still counts the sounds, not the picture",
      any(line.startswith("Export finished: 1 sound,") for line in heard),
      heard[-1:] if heard else heard)
if data:
    opened_export = Board.load(exported)
    check("the export opens with its picture found beside it",
          os.path.isfile(opened_export.picture_file)
          and os.path.dirname(os.path.abspath(opened_export.picture_file))
          .startswith(os.path.abspath(target)), opened_export.picture_file)
VAULT.refuse = False

heading("3c. A plugin named by its file name alone is found here, if it is")
FAKE_PLUGIN = "C:\\Program Files\\Common Files\\VST3\\Phasis.vst3"
real_installed = vst.installed
vst.installed = lambda: [("Phasis", FAKE_PLUGIN)]
try:
    if dsp.available() and CHAIN is not None:
        LOADS.clear()
        heard.clear()
        frame._open_board(write_board("Imported.json", {
            "voice_on": True, "voice_settings": {"plugin": "Phasis.vst3"},
            "slots": []}))
        opened = loaded_line(heard)
        pump_until(lambda: bool(LOADS), 1.0)
        check("the one installed plugin of that file name is the one loaded",
              LOADS == [FAKE_PLUGIN], LOADS)
        check("and the Loaded line does not call it missing",
              "not installed here" not in opened, opened)
        vst.installed = lambda: [("Phasis", FAKE_PLUGIN),
                                 ("Phasis copy", "D:\\Plugins\\Phasis.vst3")]
        LOADS.clear()
        heard.clear()
        frame._open_board(write_board("Imported two.json", {
            "voice_on": True, "voice_settings": {"plugin": "Phasis.vst3"},
            "slots": []}))
        pump_until(lambda: bool(LOADS), 0.5)
        check("with two of that name installed, neither is guessed",
              LOADS == [] and "not installed here, Phasis"
              in loaded_line(heard), (LOADS, loaded_line(heard)))
        LOADS.clear()
        heard.clear()
        frame._open_board(write_board("Imported three.json", {
            "voice_on": True, "voice_settings": {"plugin": "Missing.vst3"},
            "slots": []}))
        pump_until(lambda: bool(LOADS), 0.5)
        check("and with none, the voice runs without it and says so",
              LOADS == [] and "not installed here, Missing"
              in loaded_line(heard), (LOADS, loaded_line(heard)))
    else:
        check("SKIPPED: no voice chain in this copy, so nothing to load", True)
finally:
    vst.installed = real_installed

# ===========================================================================
heading("3b. The station password lives in Credential Manager")

pw = Board()
pw.stream_name, pw.stream_host = "Blindside Radio", "blindsideradio.com"
pw.stream_password = "hunter2"
pw.save_station()
pw.stream_stations.append({"stream_name": "Second", "stream_host":
                           "second.example", "stream_password": "pw2"})
attempt("putting them away reports one was kept and none refused",
        lambda: pw.secure_passwords() == (True, False))
attempt("the board file leaves both out",
        lambda: pw.to_dict()["stream_password"] == ""
        and all(not s.get("stream_password")
                for s in pw.to_dict()["stream_stations"]))
pw_path = os.path.join(HOME, "Passwords.json")
pw.save(pw_path)
back = Board.load(pw_path)
check("reading the file alone never touches the credential store",
      back.stream_password == "")
attempt("the window gives them back from Credential Manager",
        lambda: back.secure_passwords() is not None
        and back.stream_password == "hunter2"
        and [s.get("stream_password") for s in back.stream_stations]
        == ["hunter2", "pw2"])
stranger = Board()
stranger.stream_name, stranger.stream_host = "Blindside Radio", \
    "attacker.example"
attempt("a board naming that station with another server gets nothing",
        lambda: stranger.secure_passwords() is not None
        and stranger.stream_password == "")

VAULT.refuse = True
# The export above already met a refusal, and it is said once a session.
frame._password_refusal_said = False
REFUSED = write_board("Refused.json", {"stream_name": "Locked down",
                                       "stream_host": "locked.example",
                                       "stream_password": "still-here",
                                       "slots": []})
REFUSED_TOO = write_board("Refused too.json", {"stream_name": "Also locked",
                                               "stream_host": "also.example",
                                               "stream_password": "pw3",
                                               "slots": []})
heard.clear()
frame._open_board(REFUSED)
first = loaded_line(heard)
check("Windows refusing the store is said",
      "Windows would not keep your station password safely" in first, first)
frame._autosave()
check("and the password stays in the file rather than being lost",
      saved(REFUSED).get("stream_password") == "still-here")
heard.clear()
frame._open_board(REFUSED_TOO)
check("said once, not at every board", "Windows would not keep your station "
      "password" not in loaded_line(heard), loaded_line(heard))
VAULT.refuse = False

# ===========================================================================
heading("4. The shot check's Ask box never sends a screen nobody agreed to")

VAULT.held[secrets.target_for(frame.board.vision_provider,
                              secrets.VISION_PREFIX)] = ("vision-key", "")
GRABS, SENT = [], []
AGREED = object()
real_preview = frame.preview_picture
real_converse, real_describe = vision.converse, vision.describe
frame.preview_picture = lambda *a, **kw: GRABS.append(1) or (AGREED, "a still")
vision.converse = lambda shot, *a, **kw: SENT.append(shot) or (True, "Fine")
vision.describe = lambda shot, *a, **kw: (True, "A desktop")
frame.board.picture = C.PICTURE_SCREEN
shot = dialogs.ShotCheckDialog(frame, frame)
shot.ask.question.SetValue("Is my email on show?")
click(shot.ask.send)
pump_until(lambda: not shot.ask._busy, 3)
check("with no check run, Ask takes no picture of the screen", GRABS == [],
      GRABS)
check("and sends nothing", SENT == [], SENT)
check("it says to check the shot first",
      shot.ask.answer.GetValue().startswith("Check the shot first"),
      shot.ask.answer.GetValue())
answers = iter([wx.YES])
wx.MessageBox = lambda *a, **kw: next(answers, wx.NO)
try:
    click(shot.go)
    pump_until(lambda: not shot._busy, 3)
finally:
    wx.MessageBox = fake_box
check("once the screen is agreed to in the check, it is grabbed once",
      GRABS == [1], GRABS)
shot.ask.question.SetValue("Is my email on show?")
click(shot.ask.send)
pump_until(lambda: not shot.ask._busy and SENT, 3)
check("Ask then sends that same picture, and grabs no other",
      SENT == [AGREED] and GRABS == [1], (SENT, GRABS))
shot.Destroy()
frame.board.picture = C.PICTURE_CAMERA
GRABS.clear()
SENT.clear()
camera_shot = dialogs.ShotCheckDialog(frame, frame)
camera_shot.ask.question.SetValue("Am I in shot?")
click(camera_shot.ask.send)
pump_until(lambda: not camera_shot.ask._busy and SENT, 3)
check("a camera still is taken fresh and asked about, as before",
      GRABS == [1] and SENT == [AGREED], (GRABS, SENT))
camera_shot.Destroy()
frame.preview_picture = real_preview
vision.converse, vision.describe = real_converse, real_describe
frame.board.picture = C.PICTURE_CARD

# ===========================================================================
heading("5. Uninstalling removes only what the program left in its folder")


def iss_sections(path):
    sections, current = {}, None
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith(";"):
                continue
            found = re.fullmatch(r"\[([^\]]+)\]", line)
            if found:
                current = found.group(1)
                sections.setdefault(current, [])
                continue
            if current is not None:
                sections[current].append(line)
    return sections


def iss_entries(lines):
    out = []
    for line in lines:
        fields = {}
        for part in line.split(";"):
            if ":" in part:
                key, _, value = part.partition(":")
                fields[key.strip().lower()] = value.strip().strip('"')
        out.append(fields)
    return out


ISS = iss_sections(os.path.join(ROOT, "tools", "dropdeck.iss"))
setup = dict(line.split("=", 1) for line in ISS.get("Setup", []) if "=" in line)
check("the folder page is off, so it cannot be pointed at Documents",
      setup.get("DisableDirPage", "").lower() == "yes",
      setup.get("DisableDirPage"))
check("and an existing install keeps the folder it has",
      setup.get("UsePreviousAppDir", "").lower() == "yes",
      setup.get("UsePreviousAppDir"))
removed = iss_entries(ISS.get("UninstallDelete", []))
check("nothing deletes the whole program folder",
      not any(e.get("name", "").rstrip("\\") == "{app}"
              and e.get("type") in ("files", "filesandordirs")
              for e in removed), removed)
check("nothing names the user's own userdata folder",
      not any("userdata" in e.get("name", "").lower() for e in removed))
check("every entry is inside the program folder",
      all(e.get("name", "").startswith("{app}") for e in removed), removed)
check("and they are only the program's own leftovers",
      {e.get("name") for e in removed if e.get("type") != "dirifempty"}
      == {"{app}\\_internal.replaced", "{app}\\.dropdeck-write-test"},
      removed)
check("the folder itself goes only when nothing else is left in it",
      any(e.get("type") == "dirifempty" and e.get("name") == "{app}"
          for e in removed), removed)

# ===========================================================================
heading("6. A board cannot record to a share or read a file as a listener count")

for label, value in (("a share nobody picked here",
                      "\\\\other-nas.example\\shows"),
                     ("a WebDAV address", WEBDAV),
                     ("a relative folder", "shows")):
    probe = Board.load(write_board("Folder.json", {"record_folder": value}))
    check("a recording folder on %s is dropped" % label,
          probe.record_folder == "", probe.record_folder)
    check("and said, once, in plain words",
          any("not a folder on this computer" in n
              for n in getattr(probe, "load_notes", [])))
mine = Board.load(write_board("Folder.json", {"record_folder": "D:\\Shows"}))
check("a folder on this computer is kept", mine.record_folder == "D:\\Shows",
      mine.record_folder)
for value in ("file:///C:/Windows/win.ini", "ftp://attacker.example/x",
              "C:\\Windows\\win.ini", "/etc/passwd"):
    probe = Board.load(write_board("Stats.json", {"stream_stats_url": value}))
    check("Where listeners connect refuses %s" % value,
          probe.stream_stats_url == "", probe.stream_stats_url)
probe = Board.load(write_board("Stats.json", {
    "stream_stats_url": "https://listen.example.com/status-json.xsl"}))
check("a web address is kept",
      probe.stream_stats_url == "https://listen.example.com/status-json.xsl")
asked = []
real_open = streamstats.urllib.request.urlopen


def record_open(*a, **kw):
    asked.append(a)
    raise streamstats.urllib.error.URLError("a stand-in opens nothing")


streamstats.urllib.request.urlopen = record_open
try:
    answer = streamstats.fetch({"stats_url": "file:///C:/Windows/win.ini",
                                "host": "radio.example.org"})
finally:
    streamstats.urllib.request.urlopen = real_open
check("the listener count never opens a file, whatever it is handed",
      asked == [], asked)
check("and says why", "http or https" in (answer.error or ""), answer.error)


NAS_TWO = "\\\\nas2.example\\recordings"


def pick_a_nas(dialog):
    dialog.record_folder.SetValue(NAS_TWO)
    dialog.stream_stats.SetValue("file:///C:/Windows/win.ini")
    return wx.ID_OK


frame.board.record_folder = "D:\\Shows"
frame.board.stream_stats_url = ""
heard.clear()
preferences(frame, pick_a_nas)
check("Preferences takes a NAS folder picked on this computer",
      frame.board.record_folder == NAS_TWO, frame.board.record_folder)
machine = json.load(open(MACHINE, encoding="utf-8")) \
    if os.path.exists(MACHINE) else {}
check("and writes it down on this computer, not in the board",
      NAS_TWO in (machine.get("record_folders") or []), machine)
check("so a board file naming that folder keeps it on load",
      Board.load(write_board("Folder.json", {"record_folder": NAS_TWO}))
      .record_folder == NAS_TWO)
check("while another share in a board file is still dropped",
      Board.load(write_board("Folder.json", {
          "record_folder": "\\\\other-nas.example\\shows"})).record_folder
      == "")
check("a listener count address that is not a web address is refused",
      frame.board.stream_stats_url == "", frame.board.stream_stats_url)
check("and said", any("web address" in line for line in heard), heard)


def a_relative_folder(dialog):
    dialog.record_folder.SetValue("shows")
    return wx.ID_OK


heard.clear()
preferences(frame, a_relative_folder)
check("a folder that is not a whole path is not taken",
      frame.board.record_folder == NAS_TWO, frame.board.record_folder)
check("and that is said", any("has to be a whole folder path" in line
                              for line in heard), heard)

# ===========================================================================
heading("7. Global hotkeys never take keys every program needs")

for text, why in (("Ctrl+C", "copy"), ("Ctrl+V", "paste"),
                  ("ctrl+z", "undo"), ("Ctrl+W", "close"),
                  ("Shift+A", "types a character"),
                  ("Shift+1", "types a character"),
                  ("Shift+Space", "types a character")):
    attempt("%s is refused as a global hotkey" % text,
            lambda t=text, w=why: w in globalhotkeys.refusal(t),
            lambda t=text: globalhotkeys.describe(t))
for text in ("Ctrl+Alt+C", "Ctrl+Shift+V", "Alt+A", "Shift+F5", "Ctrl+F9",
             "Ctrl+Alt+F9"):
    attempt("%s is still allowed" % text,
            lambda t=text: globalhotkeys.refusal(t) == ""
            and globalhotkeys.parse(t) is not None)
check("a bare key is still refused, which this adds to",
      globalhotkeys.parse("F9") is None)

registered = []


class FakeUser32:
    def RegisterHotKey(self, hwnd, ident, mods, key):
        registered.append((mods & 0x000F, key))
        return 1

    def UnregisterHotKey(self, hwnd, ident):
        return 1

    def GetMessageW(self, *a):
        return 0

    def PostThreadMessageW(self, *a):
        return 1


real_user32 = globalhotkeys.user32
globalhotkeys.user32 = FakeUser32()
try:
    hk = REAL_HOTKEYS(on_fire=lambda i: None)
    hk.set_bindings({0: "Ctrl+C", 1: "Shift+A", 2: "Ctrl+Alt+F9"})
    hk._to_ui = lambda func, *args: None
    hk._run()          # registers, reads one message (none), lets go
finally:
    globalhotkeys.user32 = real_user32
check("the listener itself offers Windows only the safe one",
      registered == [(globalhotkeys.MOD_CONTROL | globalhotkeys.MOD_ALT,
                      0x78)], registered)
attempt("and keeps the others apart from Windows' own refusals",
        lambda: set(hk.refused) == {0, 1} and hk.failures == {},
        lambda: (getattr(hk, "refused", None), hk.failures))

HOTKEYS = write_board("Hotkeys.json", {
    "global_hotkeys_on": True,
    "slots": [{"global_hotkey": "Ctrl+V"}, {"global_hotkey": "Ctrl+Alt+F10"}]})
heard.clear()
frame._open_board(HOTKEYS)
opened = loaded_line(heard)
check("on open, only the safe one is registered",
      frame.hotkeys.bindings == {1: "Ctrl+Alt+F10"}, frame.hotkeys.bindings)
check("and the Loaded line says which and why",
      "Ctrl+V on" in opened and "is paste" in opened, opened)
check("the pad keeps it", frame.board.slots[0].global_hotkey == "Ctrl+V")
frame.hotkeys.enabled = False
frame.board.global_hotkeys_on = False
heard.clear()
command(frame, uimod.ID_GLOBAL_TOGGLE)
check("Ctrl+G turning them on says it too",
      any("Ctrl+V on" in line for line in heard), heard)

slot = frame.board.slots[3]
capture = dialogs.AssignHotkeyDialog(frame, slot, global_mode=True)
for keys, why in (((ord("C"),), {"ctrl": True}), ((ord("A"),),
                                                  {"shift": True})):
    capture._on_key(Keystroke(keys[0], **why))
check("the assign window will not take Ctrl+C or Shift+A",
      capture.readout.GetValue() == "None", capture.readout.GetValue())
check("and says why", "types a character" in capture.warning.GetLabel(),
      capture.warning.GetLabel())
capture._on_key(Keystroke(ord("C"), ctrl=True, alt=True))
check("Ctrl+Alt+C is taken as it always was",
      capture.readout.GetValue() == "Alt+Ctrl+C", capture.readout.GetValue())
capture.Destroy()


class AnswersCtrlX:
    def __init__(self, *a, **kw):
        pass

    def ShowModal(self):
        return wx.ID_OK

    def hotkey_text(self):
        return "Ctrl+X"

    def Destroy(self):
        pass


real_assign = uimod.AssignHotkeyDialog
uimod.AssignHotkeyDialog = AnswersCtrlX
frame._context_slot = slot
heard.clear()
try:
    command(frame, uimod.ID_GLOBAL_HOTKEY)
finally:
    uimod.AssignHotkeyDialog = real_assign
    frame._context_slot = None
check("Sounds, Assign a global hotkey refuses Ctrl+X",
      slot.global_hotkey in (None, ""), slot.global_hotkey)
check("with the reason", any("is cut" in line for line in heard), heard)

# ===========================================================================
heading("8. The key store's two slips")

VAULT.held[secrets.target_for("google")] = ("a stream key", "stream")
VAULT.held[secrets.target_for("google", secrets.VISION_PREFIX)] = ("v", "")
check("forgetting a vision key answers about the VISION key",
      secrets.forget("google", secrets.VISION_PREFIX) is True)
check("and leaves a stream key of the same name alone",
      VAULT.text_of("google") == "a stream key")
VAULT.refuse = True


def type_vision_key(dialog):
    dialog.vision_key.SetValue("sk-new-key")
    return wx.ID_OK


heard.clear()
preferences(frame, type_vision_key)
VAULT.refuse = False
check("a vision key Windows will not keep is said, not dropped in silence",
      any("Windows would not keep your AI provider key" in line
          for line in heard), heard)
check("and it is not put in the board file instead",
      "sk-new-key" not in json.dumps(frame.board.to_dict()))
attempt("a key is kept with the server it is for, in one spelling",
        lambda: secrets.store("Spelling", "K", host="RTMPS://Live.Example/app/")
        and secrets.tied_to("Spelling") == "rtmps://live.example/app")

# ===========================================================================
frame.board.dirty = False
frame._save_timer.Stop()
frame.stop_background_work()
frame.Destroy()
app.ProcessPendingEvents()
print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
