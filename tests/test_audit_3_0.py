"""What the 3.0 cross-audit found in the windows, and how each one is held.

    python tests/test_audit_3_0.py

Two agents were sent through the voice processing work to question each
other's findings. These are the ones in the user interface that survived, and
every check here stands for something a person would have hit:

  * A plugin chosen in Preferences lasted exactly as long as the session did.
  * Cancel on Preferences kept the voice changes and did not save them, then
    said "nothing changed".
  * Opening a board left the microphone on the last board's settings, and the
    next OK wrote those back over what the opened board had saved.
  * Enter on Cancel in the hotkey window did what OK does, and Space did
    nothing at all on any button.
  * A station saved in Preferences was gone by the next launch.
  * A board that could not be saved on the way out was lost without a word.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-audit30-")

import wx

from dropdeck import dsp, vst
from dropdeck.board import Board
from dropdeck.dialogs import AssignHotkeyDialog, SettingsDialog
from dropdeck.slot import Slot
from dropdeck.ui import DropDeckFrame

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name
          + (("  " + str(detail)) if detail != "" else ""))


app = wx.App(redirect=False)

# A real plugin if this machine has one, so the checks are about the app
# rather than about a stand in. Without one the plugin checks are skipped and
# say so, which is honest; the rest still run.
PLUGIN = None
for name, path in vst.installed():
    if name in ("Bite", "Dirt", "Phasis", "bx_enhancer", "Flair"):
        try:
            PLUGIN = (name, path, vst.load(path))
        except Exception:
            continue
        break


print("A plugin outlives the session that chose it")

chain = dsp.MicChain(48000)
check("a chain with no plugin writes none down", "plugin" not in chain.to_dict())

if PLUGIN is None:
    print("  ..     no VST3 on this machine, so the plugin checks are skipped")
else:
    name, path, plugin = PLUGIN
    chain.set_plugin(plugin, path)
    saved = chain.to_dict()
    check("choosing one records where it came from", saved.get("plugin") == path,
          saved.get("plugin"))
    check("and how it is set", bool(saved.get("plugin_values")),
          len(saved.get("plugin_values") or {}))
    check("the compressor is still in there beside it",
          saved.get("comp_ratio") == chain.settings["comp_ratio"])

    # Which is what the next launch reads.
    fresh = dsp.MicChain(48000, saved)
    check("a chain built from that asks for the same plugin",
          fresh.wanted_plugin == path)
    check("with the same settings to put back",
          fresh.wanted_plugin_values == saved["plugin_values"])
    check("and it does not load it itself, because that takes a second",
          fresh.plugin is None)
    check("the ordinary settings came back too",
          fresh.settings == chain.settings)

    chain.set_plugin(None)
    check("taking it out forgets it", "plugin" not in chain.to_dict())
    check("and stops asking for it on the next launch",
          chain.wanted_plugin is None)

# Through a real board file, because that is the trip that was losing it.
board = Board()
board.voice_settings = {"comp_ratio": 6.0, "plugin": "C:/x/Some.vst3",
                        "plugin_values": {"mix": 0.5}}
board.voice_on = False
written = os.path.join(tempfile.mkdtemp(), "board.json")
board.save(written)
back = Board.load(written)
check("a board file carries the plugin", back.voice_settings.get("plugin")
      == "C:/x/Some.vst3", back.voice_settings.get("plugin"))
check("and its settings", back.voice_settings.get("plugin_values")
      == {"mix": 0.5})
check("and whether the chain is on at all", back.voice_on is False)


print()
print("Cancel on Preferences means cancel")

frame = DropDeckFrame()
frame.Show()
app.Yield()
live = frame.mic.chain
if live is None:
    print("  ..     no processing library, so the voice checks are skipped")
else:
    live.update({"comp_ratio": 3.0})
    live.enabled = True
    dialog = SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic)
    check("the window writes down what it found", dialog._voice_before
          is not None)

    # What arrowing about on the Voice tab does: it changes the chain that is
    # running, so the presenter can hear it.
    params = {p.key: p for p in dialog._voice_parameters()}
    ratio = params.get("comp_ratio")
    ratio.nudge(3)
    dialog.voice_on.SetValue(False)
    live.enabled = False
    check("and the live chain really did change",
          live.settings["comp_ratio"] != 3.0, live.settings["comp_ratio"])

    undone = dialog.restore_voice()
    check("cancelling says it put something back", undone is True)
    check("the compressor is back where it was",
          live.settings["comp_ratio"] == 3.0, live.settings["comp_ratio"])
    check("and the chain is switched back on", live.enabled is True)

    # And a window nobody touched has nothing to put back, so the app can
    # still say "nothing changed" and be telling the truth.
    quiet = SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic)
    check("a window nobody touched reports no change",
          quiet.restore_voice() is False)
    quiet.Destroy()
    dialog.Destroy()

print()
print("And it means cancel on the Streaming tab too")

frame.board.stream_host = "first.example.com"
frame.board.stream_password = "first"
frame.board.stream_name = "First"
frame.board.save_station()
frame.board.stream_host = "second.example.com"
frame.board.stream_name = "Second"
frame.board.save_station()

frame.board.stream_host = "live.example.com"
frame.board.stream_name = "Live"
frame.board.stream_password = "live"
dialog = SettingsDialog(frame, frame.board, frame.mixer, mic=frame.mic)
dialog.stream_picker.SetStringSelection("First")
dialog._on_pick_station(None)
check("choosing a saved station loads it into the board",
      frame.board.stream_host == "first.example.com", frame.board.stream_host)
check("cancelling says so", dialog.restore_stream() is True)
check("and the board is back on what it was broadcasting",
      frame.board.stream_host == "live.example.com", frame.board.stream_host)
check("password and all", frame.board.stream_password == "live",
      frame.board.stream_password)
dialog.Destroy()

# The station itself is a deliberate save and stays, but it has to reach disk.
board = Board()
board.dirty = False
board.stream_name = "Kept"
board.save_station()
check("saving a station marks the board as needing saving", board.dirty is True)
board.dirty = False
check("so does forgetting one", board.forget_station("Kept") and board.dirty)


print()
print("The hotkey window's buttons")

slot = Slot(index=0, filepath="x.wav", name="Test")
keys = AssignHotkeyDialog(frame, slot)
keys.Show()
app.Yield()
ended = []
keys.EndModal = lambda code: ended.append(code)

cancel = keys.FindWindow(wx.ID_CANCEL)
ok = keys.FindWindow(wx.ID_OK)
check("it has the two buttons a dialog has", cancel is not None
      and ok is not None)


class Keystroke:
    """A key arriving at the dialog's hook.

    A real wx.KeyEvent cannot be given a key code from Python: m_keyCode is
    not settable and GetKeyCode stays at nought, which makes every check
    against one pass or fail for the wrong reason. This carries exactly what
    the handler asks of an event and records whether it was passed on.
    """

    def __init__(self, code, ctrl=False, alt=False, shift=False):
        self.code = code
        self.ctrl, self.alt, self.shift = ctrl, alt, shift
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

    def GetSkipped(self):
        return self.skipped


def press(code, window, **held):
    """That keystroke, with the focus actually where the test says it is."""
    window.SetFocus()
    app.Yield()
    event = Keystroke(code, **held)
    keys._on_key(event)
    return event


event = press(wx.WXK_RETURN, cancel)
check("Enter on Cancel is left to Cancel", event.GetSkipped())
check("and does not quietly do what OK does", not ended, ended)

event = press(wx.WXK_SPACE, ok)
check("Space on OK presses OK", event.GetSkipped())
check("rather than being refused as a reserved key",
      "needed to work the app" not in keys.warning.GetLabel(),
      keys.warning.GetLabel())

# In the readout, which is where hotkeys are captured, they still are not keys.
event = press(wx.WXK_SPACE, keys.readout)
check("but Space in the readout is still refused, because it works the app",
      not event.GetSkipped() and keys._key_code != wx.WXK_SPACE)
event = press(wx.WXK_RETURN, keys.readout)
check("and Enter in the readout is still OK", ended == [wx.ID_OK], ended)

# Capturing a real combination still works from either place.
ended.clear()
press(ord("K"), keys.readout, ctrl=True)
check("Ctrl+K is still captured", keys._key_code == ord("K"), keys._key_code)
check("and reads back as a hotkey", keys.hotkey_text() == "Ctrl+K",
      keys.hotkey_text())
# From a button too, because tabbing to Clear should not stop you setting one.
press(ord("J"), cancel, ctrl=True, shift=True)
check("and so is a combination pressed while standing on a button",
      keys._key_code == ord("J"), keys._key_code)
keys.Destroy()


print()
print("Opening a board brings its microphone with it")

other = Board()
other.mic_gain_db = 7.0
other.mic_channel = "right"
other.voice_on = False
other.voice_settings = {"comp_ratio": 8.0}
frame.mic.gain_db = 0.0
frame.mic.channel = "mix"
frame._apply_board_voice(other)
check("the gain follows the board", frame.mic.gain_db == 7.0)
check("so does which channel the voice is on", frame.mic.channel == "right")
if frame.mic.chain is not None:
    check("and the compressor", frame.mic.chain.settings["comp_ratio"] == 8.0,
          frame.mic.chain.settings["comp_ratio"])
    check("and whether the chain runs at all",
          frame.mic.chain.enabled is False)

frame.stop_background_work()
frame.Destroy()
app.Yield()

failed = [n for n, ok in CHECKS if not ok]
print()
print("%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
