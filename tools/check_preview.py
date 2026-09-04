"""Drive the real Windows file dialog.

Three things have to be true and none of them can be taken on trust:
Alt+P switches preview while the dialog is up, arrowing plays each sound,
and Alt+P pressed while another program is in front is left alone.

Every result prints the moment it is known, and a watchdog kills the process
if the native dialog will not close, so this can never sit on somebody's
screen waiting.
"""
import ctypes, os, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dd-np-")
import numpy as np, soundfile as sf, wx
from dropdeck import constants as C
from dropdeck.dialogs import NativePreview
from dropdeck.ui import DropDeckFrame

u32 = ctypes.windll.user32
SPI_GET, SPI_SET, SPIF = 0x2000, 0x2001, 2
GUI_INMENUMODE, GUI_POPUPMENUMODE = 0x00000004, 0x00000010
FAILED = []


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint),
                ("hwndActive", ctypes.c_void_p), ("hwndFocus", ctypes.c_void_p),
                ("hwndCapture", ctypes.c_void_p),
                ("hwndMenuOwner", ctypes.c_void_p),
                ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p),
                ("rcCaret", ctypes.c_long * 4)]


def gui_state():
    """What the keyboard is doing: which control has it, and menu mode.

    Alt used to be swallowed by a registered hotkey. It is not any more, so
    the dialog sees it, and the thing to prove is that seeing it costs
    nothing: same control still focused, no menu opened.
    """
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if not u32.GetGUIThreadInfo(0, ctypes.byref(info)):
        return None, 0
    return info.hwndFocus, info.flags

tmp = tempfile.mkdtemp()
for i, f in enumerate((300, 700, 1100)):
    n = 3 * 44100; t = np.arange(n) / 44100
    sf.write(os.path.join(tmp, "sound %d.wav" % (i + 1)),
             np.tile((0.4 * np.sin(2 * np.pi * f * t)).astype(np.float32)[:, None],
                     (1, 2)), 44100)


def say(label, ok, extra=None):
    if not ok:
        FAILED.append(label)
    print(("  ok   " if ok else "  FAIL ") + label
          + (("  " + str(extra)) if extra is not None else ""), flush=True)


def watchdog(seconds):
    """Nothing gets to hang. A native modal window cannot be reasoned with."""
    def bite():
        time.sleep(seconds)
        print("  FAIL watchdog: the dialog never closed", flush=True)
        os._exit(3)
    threading.Thread(target=bite, daemon=True).start()


def lock_off():
    was = ctypes.c_uint(0)
    u32.SystemParametersInfoW(SPI_GET, 0, ctypes.byref(was), 0)
    u32.SystemParametersInfoW(SPI_SET, 0, ctypes.c_void_p(0), SPIF)
    u32.AllowSetForegroundWindow(-1)
    return was.value


def fg(hwnd):
    if u32.GetForegroundWindow() == hwnd:
        return True
    u32.ShowWindow(hwnd, 9); u32.BringWindowToTop(hwnd)
    if u32.SetForegroundWindow(hwnd) and u32.GetForegroundWindow() == hwnd:
        return True
    other = u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), None)
    mine = u32.GetWindowThreadProcessId(hwnd, None)
    if other and other != mine:
        u32.AttachThreadInput(other, mine, True)
        u32.SetForegroundWindow(hwnd); u32.SetActiveWindow(hwnd)
        u32.AttachThreadInput(other, mine, False)
    return u32.GetForegroundWindow() == hwnd


app = wx.App(redirect=False)
lock = lock_off()
frame = DropDeckFrame(); frame.Show(); frame.Raise()
sim = wx.UIActionSimulator()


def pump(ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        wx.Yield(); wx.MilliSleep(10)


def go():
    watchdog(60)
    pump(600)
    for _ in range(20):
        if fg(frame.GetHandle()):
            break
        pump(200)
    dlg = wx.FileDialog(frame, "Pick", defaultDir=tmp,
                        defaultFile="sound 1.wav",
                        wildcard="Audio (*.wav)|*.wav",
                        style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
    preview = NativePreview(dlg, frame, on=False).start()
    steps = {"n": 0, "native": 0}
    watch = wx.Timer(frame)

    def shut():
        watch.Stop()
        preview.stop()
        # Escape is how a person closes it, and unlike WM_CLOSE it works even
        # when the dialog has gone into keyboard menu mode.
        for _ in range(3):
            sim.Char(wx.WXK_ESCAPE)
            pump(300)
            if not u32.IsWindowVisible(steps["native"]):
                return
        if steps["native"]:
            u32.PostMessageW(steps["native"], 0x0010, 0, 0)

    def drive(_e):
        steps["n"] += 1
        n = steps["n"]
        here = u32.GetForegroundWindow()
        if here and here != frame.GetHandle():
            steps["native"] = here
        if n == 3:
            say("the dialog is foreground", steps["native"] not in (0, frame.GetHandle()))
            say("and it reports what is highlighted", bool(preview._selection()),
                preview._selection())
            say("the window in front counts as ours", preview.ours_is_in_front())
        if n == 4:
            # Somebody else's window, to prove the test is a real test: the
            # desktop belongs to explorer.exe, never to us.
            pid = ctypes.c_ulong(0)
            u32.GetWindowThreadProcessId(u32.GetShellWindow(), ctypes.byref(pid))
            say("another program's window does not",
                bool(pid.value) and pid.value != os.getpid())
        if n == 5:
            # Pretend Drop Deck is not the program in front, which is what
            # Tony hit: Alt+P meant for something else must not reach us.
            preview.ours_is_in_front = lambda: False
            sim.Char(ord("P"), wx.MOD_ALT)
        if n == 10:
            say("Alt+P while another program is in front is ignored", not preview.on)
            del preview.ours_is_in_front
        if n == 13:
            say("and it does not fire late once we are back", not preview.on)
            steps["focus"], steps["flags"] = gui_state()
            sim.Char(ord("P"), wx.MOD_ALT)
        if n == 18:
            say("Alt+P here switched preview on", preview.on)
            focus, flags = gui_state()
            say("and the dialog kept the keyboard where it was",
                focus == steps["focus"])
            say("with no menu opened by the Alt",
                not flags & (GUI_INMENUMODE | GUI_POPUPMENUMODE))
            say("the dialog is still the window in front",
                u32.GetForegroundWindow() == steps["native"])
        if n == 25:
            say("and the highlighted sound is playing",
                frame.mixer.is_playing(C.PREVIEW_SLOT),
                os.path.basename(preview._selection() or "nothing"))
        if n == 30:
            sim.Char(ord("P"), wx.MOD_ALT)
        if n == 35:
            say("Alt+P switched it off again", not preview.on)
            say("and silenced it", not frame.mixer.is_playing(C.PREVIEW_SLOT))
            focus, flags = gui_state()
            say("keyboard still where it was, twice over",
                focus == steps["focus"]
                and not flags & (GUI_INMENUMODE | GUI_POPUPMENUMODE))
        if n >= 40:
            shut()

    frame.Bind(wx.EVT_TIMER, drive, watch)
    watch.Start(200)
    dlg.ShowModal()
    watch.Stop()
    preview.stop()
    dlg.Destroy()
    u32.SystemParametersInfoW(SPI_SET, 0, ctypes.c_void_p(int(lock)), SPIF)
    frame.stop_background_work()
    try:
        frame.mixer.close()
    except Exception:
        pass
    frame.Destroy()
    print(("FAILED %d" % len(FAILED)) if FAILED else "all good", flush=True)


wx.CallLater(700, go)
app.MainLoop()
sys.exit(1 if FAILED else 0)
