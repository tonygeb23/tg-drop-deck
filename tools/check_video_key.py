"""Does Windows actually deliver Alt+Shift+V to this app.

    python tools/check_video_key.py video       Alt+Shift+V
    python tools/check_video_key.py text        Alt+Shift+T
    python tools/check_video_key.py onscreen    Ctrl+Shift+V

**One key per run, and that is not tidiness.** Three chords in one process
was reliable for the first and dropped about half the later ones, whichever
they were: the harness drifts, the foreground moves, the message loop falls
behind. A check that fails half the time teaches nobody anything, so each key
gets its own process and its own fresh grab of the foreground.

A separate file from `check_keyboard.py` for the same reason that one is not
in `tests/`: it synthesises real Windows input, real Windows input goes to
whatever holds the foreground, and on a desktop somebody is using that moves.
It says "skipped" rather than reporting a failure it cannot stand behind.

**Why this key needs a real keystroke and the accelerator table is not
enough.** `Alt+Shift` on its own is the Windows shortcut for switching
keyboard layout on a machine with more than one installed. The chord here is
a different one and should not trigger it, but "should not" is not a test:
the layout switch fires on the modifiers being released, so a combination
built on Alt+Shift is worth proving rather than assuming, exactly the way the
digit map turned out to be eaten by the accelerator table before the crossfade
box ever saw it.

It also checks the layout is the one it started with afterwards, which is the
failure this is really looking for: a key that works AND silently switches the
user's keyboard to another language is not a working key.
"""

import ctypes
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wx

from dropdeck import constants as C
from dropdeck.dialogs import ScreenTextDialog, VideoSourceDialog
from dropdeck.ui import ID_VIDEO_SOURCES, DropDeckFrame
# The foreground dance is already solved next door, several ways round
# Windows refusing to hand the foreground to a process with no recent input.
# Copying it here would be a second copy to keep right.
from check_keyboard import (drop_foreground_lock, force_foreground,
                            restore_foreground_lock)

u32 = ctypes.windll.user32
FAILED = []
SKIPPED = []


def say(label, ok, extra=""):
    if ok is None:
        SKIPPED.append(label)
        print("  skip " + label + (("  " + str(extra)) if extra else ""))
        return
    if not ok:
        FAILED.append(label)
    print(("  ok   " if ok else "  FAIL ") + label
          + (("  " + str(extra)) if extra else ""))


def pump(ms=250):
    """Let the message loop run for a while.

    wx.Yield rather than YieldIfNeeded, the same as check_keyboard.py: a
    synthesised keystroke arrives as a real Windows message and has to be
    dispatched through the loop, which is also the only place an accelerator
    is translated. That translation is the thing under test.
    """
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        wx.Yield()
        wx.MilliSleep(5)


def layout():
    """The keyboard layout of the foreground window's thread."""
    thread = u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), None)
    return u32.GetKeyboardLayout(thread)


#: What can be tested, and what each one should reach. One per run: see the
#: note at the top of this file.
KEYS = {
    "video": ("Alt+Shift+V", "the video sources", "_on_video_sources",
              (wx.WXK_ALT, wx.WXK_SHIFT), "V"),
    "text": ("Alt+Shift+T", "the screen text", "_on_screen_text",
             (wx.WXK_ALT, wx.WXK_SHIFT), "T"),
    "onscreen": ("Ctrl+Shift+V", "what is on screen", "describe_screen",
                 (wx.WXK_CONTROL, wx.WXK_SHIFT), "V"),
}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "video"
    if which not in KEYS:
        print("Which key? One of: %s" % ", ".join(sorted(KEYS)))
        return 2
    shown, what, handler_name, mods, letter = KEYS[which]
    app = wx.App(redirect=False)

    # BEFORE the frame exists. See this file's note: the frame binds the
    # bound method in __init__, so a class patch applied afterwards is never
    # the thing that runs and the counter below would always read zero.
    fired = []
    real_handler = getattr(DropDeckFrame, handler_name)

    def counted(self, event=None):
        fired.append(1)
        return None          # never open the real window

    setattr(DropDeckFrame, handler_name, counted)

    # THE CONTROL. Alt+Shift+S has shipped since 2.5.0 and Tony uses it, so
    # it is known good. If the simulator cannot deliver that either then the
    # fault is in this file rather than in the key under test, and saying so
    # is the difference between a bug report and a wild goose chase.
    control = []
    real_control = DropDeckFrame._on_sources

    def counted_control(self, event=None):
        control.append(1)
        return None

    DropDeckFrame._on_sources = counted_control

    frame = DropDeckFrame()
    frame.board.live_to = C.LIVE_TO_VIDEO
    frame.board.video_server = "youtube"
    frame.board.video_host = C.RTMP_INGEST["youtube"]
    frame.Show()
    frame.Raise()
    was_lock = drop_foreground_lock()
    force_foreground(frame)
    pump(600)

    opened = []
    real = VideoSourceDialog.ShowModal

    def watched(self):
        # Recorded and closed at once. A modal window in a script that cannot
        # click is a hang, and a hang here looks exactly like a key that did
        # nothing.
        opened.append(self)
        return wx.ID_CANCEL

    VideoSourceDialog.ShowModal = watched

    # Did the COMMAND arrive at all? Separating "Windows never delivered the
    # key" from "the handler ran and declined" is the whole diagnosis, and
    # the two look identical from outside.

    def go():
        try:
            if u32.GetForegroundWindow() != int(frame.GetHandle()):
                force_foreground(frame)
                pump(400)
            if u32.GetForegroundWindow() != int(frame.GetHandle()):
                say("Alt+Shift+V reaches the app", None,
                    "another window has the foreground, so run it again on a "
                    "quiet desktop")
                return
            before = layout()
            sim = wx.UIActionSimulator()

            def chord(keys, key):
                # Anything an earlier press left held turns this key into a
                # different key, so everything is released first.
                for stuck in (wx.WXK_SHIFT, wx.WXK_CONTROL, wx.WXK_ALT):
                    sim.KeyUp(stuck)
                pump(150)
                for mod in keys:
                    sim.KeyDown(mod)
                pump(120)
                sim.Char(ord(key))
                pump(120)
                for mod in reversed(keys):
                    sim.KeyUp(mod)
                pump(700)

            # THE CONTROL, first, and it is a known good key: Alt+Shift+S has
            # shipped since 2.5.0. If the simulator cannot deliver that, this
            # file cannot judge anything and says so rather than blaming the
            # app.
            chord((wx.WXK_ALT, wx.WXK_SHIFT), "S")
            if not control:
                say("%s reaches the app" % shown, None,
                    "the simulator could not deliver Alt+Shift+S either, "
                    "which already works, so this run proves nothing")
                return
            say("the simulator can deliver a chord at all", bool(control))

            chord(mods, letter)
            if u32.GetForegroundWindow() != int(frame.GetHandle()) and not fired:
                say("%s reaches the app" % shown, None,
                    "the foreground moved during the press")
                return
            say("%s really does reach %s" % (shown, what), bool(fired),
                "" if fired else "the command never arrived: Windows ate it")
            say("and Windows did not switch the keyboard layout under it",
                layout() == before,
                "layout changed from %s to %s" % (before, layout()))
        finally:
            VideoSourceDialog.ShowModal = real
            setattr(DropDeckFrame, handler_name, real_handler)
            DropDeckFrame._on_sources = real_control
            # Putting somebody's machine back the way it was found.
            restore_foreground_lock(was_lock)
            frame.stop_background_work()
            frame.Destroy()
            app.ExitMainLoop()

    wx.CallLater(400, go)
    # A watchdog, so this can never sit on somebody's screen waiting.
    threading.Timer(30.0, lambda: os._exit(2)).start()
    app.MainLoop()

    print()
    if FAILED:
        print("%d FAILED" % len(FAILED))
        return 1
    if SKIPPED:
        print("Skipped: the desktop was not quiet enough to prove it.")
        return 0
    print("The key works, and costs nothing else.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
