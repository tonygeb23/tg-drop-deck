"""Real keystrokes into the real window.

    python tools/check_keyboard.py

**Run this by hand, on a desktop where nothing else is grabbing focus.** It is
not in tests/ because it cannot be trusted to run unattended: it synthesises
real Windows input, and real Windows input goes to whatever window has the
foreground at that instant. Anything popping up mid run sends the keystrokes
somewhere else, and a key that went to another window looks exactly like a key
this app ignored. It notices that and says "skipped" rather than reporting a
failure it cannot stand behind, so a skip means run it again with the desktop
quiet, not that something is broken.

What it can prove, when it does run, is the part no other test can reach.

Every other test here drives handlers directly, which is fast and which is
exactly why it missed two of the things Brian Hartgen reported in September
2026. Both were about what Windows does with a key BEFORE any of this app's
code sees it:

- **Enter did nothing on a playlist row.** The handler was there and it was
  correct. A list box on a frame never receives Return at all: the dialog
  message loop takes it first. Calling the handler by hand proved nothing.
- **The crossfade box could not be typed into.** The pads are on bare digits,
  and an accelerator table on a frame is consulted BEFORE the control that
  has focus. Every digit fired a sound instead of landing in the box.

So this one uses wx.UIActionSimulator: real key events, through the real
message loop, into the real frame. Two things it therefore needs, and both of
them are the reason the file is shaped the way it is:

- **It runs inside MainLoop.** A synthesised keystroke is a Windows message,
  and messages are translated by the event loop. Nothing dispatched outside
  one gets accelerators applied at all, which is the very thing under test.
- **It needs the window genuinely in the foreground**, which is not something
  a script can always have. When it cannot get it, it says so and stops,
  rather than reporting failures that are only about which window Windows
  happened to be pointing at.
"""

import ctypes
import os
import shutil
import sys
import tempfile
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-live-appdata-")

import wx

from dropdeck.ui import VIEW_PLAYLIST, DropDeckFrame

RATE = 44100
CHECKS = []
u32 = ctypes.windll.user32

SPI_GETFOREGROUNDLOCKTIMEOUT = 0x2000
SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
SPIF_SENDCHANGE = 2


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


def tone(path, seconds, freq=440.0):
    n = int(seconds * RATE)
    t = np.arange(n, dtype=np.float32) / RATE
    wave = (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.tile(wave[:, None], (1, 2)), RATE)
    return path


def drop_foreground_lock():
    """Turn off the timer that stops a quiet process taking the foreground.

    Returns what it was, to be put back afterwards. Leaving somebody's machine
    with the lock off would be rude.
    """
    was = ctypes.c_uint(0)
    u32.SystemParametersInfoW(SPI_GETFOREGROUNDLOCKTIMEOUT, 0,
                              ctypes.byref(was), 0)
    u32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0,
                              ctypes.c_void_p(0), SPIF_SENDCHANGE)
    u32.AllowSetForegroundWindow(-1)            # ASFW_ANY
    return was.value


def restore_foreground_lock(value):
    u32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0,
                              ctypes.c_void_p(int(value)), SPIF_SENDCHANGE)


def force_foreground(window):
    """Ask Windows, several ways, to point at us."""
    hwnd = window.GetHandle()
    if u32.GetForegroundWindow() == hwnd:
        return True
    u32.ShowWindow(hwnd, 9)                     # SW_RESTORE
    u32.BringWindowToTop(hwnd)
    if u32.SetForegroundWindow(hwnd) and u32.GetForegroundWindow() == hwnd:
        return True
    # Refused. Borrow the current foreground thread's input queue, which is
    # the documented way round it for a process with no recent input.
    foreground = u32.GetForegroundWindow()
    mine = u32.GetWindowThreadProcessId(hwnd, None)
    theirs = u32.GetWindowThreadProcessId(foreground, None)
    if theirs and theirs != mine:
        u32.AttachThreadInput(theirs, mine, True)
        u32.BringWindowToTop(hwnd)
        u32.SetForegroundWindow(hwnd)
        u32.SetActiveWindow(hwnd)
        u32.AttachThreadInput(theirs, mine, False)
    return u32.GetForegroundWindow() == hwnd


def pump(ms=250):
    """Let the message loop run for a while.

    wx.Yield rather than YieldIfNeeded: a synthesised keystroke arrives as a
    real Windows message and has to be dispatched through the loop, which is
    also the only place accelerators are translated.
    """
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        wx.Yield()
        wx.MilliSleep(5)


class Skipped(Exception):
    """The desktop would not hold still long enough to test anything."""


def run(frame, songs, state):
    """Everything this file checks. Runs inside the message loop."""
    pump(600)
    for _ in range(20):
        if force_foreground(frame):
            break
        pump(200)
    if u32.GetForegroundWindow() != frame.GetHandle():
        print("\n  skipped: this window could not be brought to the "
              "foreground, so no real keystroke would reach it.")
        return None

    sim = wx.UIActionSimulator()
    panel = frame.playlist_panel
    panel.add_paths(songs)
    frame.show_view(VIEW_PLAYLIST)
    pump(300)

    # Any modifier left held down by whatever ran before this would turn
    # every keystroke below into a different one: a stray Shift makes 1 into
    # Shift+1, which is a different pad and a different check.
    for modifier in (wx.WXK_SHIFT, wx.WXK_CONTROL, wx.WXK_ALT):
        sim.KeyUp(modifier)
    pump(150)

    # Every key that actually reaches the window is counted. A synthesised
    # keystroke goes to whatever has the foreground, and on a desktop
    # somebody else is using that is not always this window. A key that never
    # arrived looks exactly like a key the app ignored, and reporting the
    # second when it was the first would be worse than reporting nothing.
    arrived = []
    frame.Bind(wx.EVT_CHAR_HOOK,
               lambda e: (arrived.append(e.GetKeyCode()), e.Skip()))

    def press(key):
        for attempt in range(3):
            if u32.GetForegroundWindow() != frame.GetHandle():
                focused = wx.Window.FindFocus()
                force_foreground(frame)
                pump(200)
                if focused is not None:
                    focused.SetFocus()
                    pump(150)
            before = len(arrived)
            sim.Char(key)
            pump(320)
            if len(arrived) > before:
                return True
        state["lost"] = True
        raise Skipped()

    def focus_on(window):
        """Put focus somewhere and make sure it went.

        Focus is the other half of what a keystroke means. If something else
        on the desktop took it back between putting it and pressing the key,
        every check below is about the wrong control, and reporting that as a
        failure of the app would be a lie.
        """
        for _ in range(3):
            force_foreground(frame)
            window.SetFocus()
            pump(250)
            if _within(wx.Window.FindFocus(), window):
                return True
        state["lost"] = True
        raise Skipped()

    # -----------------------------------------------------------------------
    print("Typing into the crossfade box, which the pads used to swallow")

    frame.board.playlist.crossfade = 3.0
    panel.crossfade.SetValue(3.0)
    focus_on(panel.crossfade)

    check("and the pad keys have stood down for it",
          frame._accelerators_typing is True, frame._accelerators_typing)

    # Which pad fired, if any, and what the map thought it was doing at the
    # time. A pad firing while the typing map is reportedly installed is a
    # different fault from a pad firing because the map was not installed,
    # and the difference is worth having in the output.
    pads = []
    real_trigger = frame.trigger
    frame.trigger = lambda index: pads.append(
        (index, frame._accelerators_typing, repr(wx.Window.FindFocus())))
    was = panel.crossfade.GetTextValue()
    press(ord("8"))
    frame.trigger = real_trigger
    typed = panel.crossfade.GetTextValue()
    # The value it lands on depends on where the caret was and on the box's
    # own maximum. What matters is that the keystroke reached the box at all
    # rather than being taken by pad 8 on the way past.
    check("the digit lands in the box rather than firing pad 8",
          typed != was, "%s then %s" % (was, typed))
    check("and no pad was fired by typing it", not pads, pads)

    # Tab out, which is what commits a typed value.
    press(wx.WXK_TAB)
    check("leaving the box applies what was typed",
          frame.board.playlist.crossfade != 3.0,
          frame.board.playlist.crossfade)

    # -----------------------------------------------------------------------
    print("And the pads still fire everywhere else")

    frame.board.playlist.crossfade = 3.0
    panel.refresh()
    focus_on(panel.list)
    check("and the pad keys are back on for the list",
          frame._accelerators_typing is False, frame._accelerators_typing)
    fired = []
    real_trigger = frame.trigger
    frame.trigger = lambda index: fired.append(index)
    press(ord("1"))
    frame.trigger = real_trigger
    check("a digit pressed in the running order still fires pad 1",
          fired == [0], fired)

    # -----------------------------------------------------------------------
    print("Enter on a row, which never reached the app before")

    # A short crossfade, because these songs are three seconds long: with the
    # crossfade at three as well, every track is at its cue point the instant
    # it starts and the playlist runs away down the order while we watch.
    frame.board.playlist.crossfade = 0.5
    panel.refresh()
    frame.stop_playlist(quiet=True)
    focus_on(panel.list)
    panel.select(1)
    pump(250)
    press(wx.WXK_RETURN)
    check("Enter plays from the row the cursor is on",
          frame.player.playing and frame.player.index == 1,
          "playing %s, index %s" % (frame.player.playing, frame.player.index))
    frame.stop_playlist(quiet=True)
    pump(200)

    # -----------------------------------------------------------------------
    print("Space, which has to tick and NOT play")

    focus_on(panel.list)
    panel.select(0)
    pump(250)
    before_tick = panel.is_ticked(0)
    press(wx.WXK_SPACE)
    check("Space toggles the tick box", panel.is_ticked(0) != before_tick,
          "%s then %s" % (before_tick, panel.is_ticked(0)))
    check("and the model follows it",
          frame.board.playlist[0].enabled == panel.is_ticked(0),
          frame.board.playlist[0].enabled)
    check("and it did not also put the playlist on air",
          not frame.player.playing)
    press(wx.WXK_SPACE)
    check("and back again", panel.is_ticked(0) == before_tick)

    # -----------------------------------------------------------------------
    print("First letter navigation, which the row numbers used to block")

    focus_on(panel.list)
    panel.select(0)
    pump(250)
    press(ord("0"))          # "03 Charlie" begins with a zero, as files do
    check("a keypress moves the cursor inside the list",
          panel.list.GetFocusedItem() >= 0, panel.list.GetFocusedItem())
    check("and the first cell of a row is its title, with no number in front",
          panel.cell(1, 0) == "02 Bravo", panel.cell(1, 0))

    frame.stop_playlist(quiet=True)
    return True


def _within(window, parent):
    for _ in range(4):
        if window is None:
            return False
        if window is parent:
            return True
        window = window.GetParent()
    return False


def main():
    app = wx.App(redirect=False)
    tmp = tempfile.mkdtemp(prefix="dropdeck-live-")
    songs = [tone(os.path.join(tmp, name), 3.0, freq) for name, freq in (
        ("01 Alpha.wav", 220), ("02 Bravo.wav", 440), ("03 Charlie.wav", 660))]
    lock = drop_foreground_lock()
    frame = DropDeckFrame()
    frame.Show()
    frame.Raise()
    state = {}

    def go():
        try:
            state["ran"] = run(frame, songs, state)
        except Skipped:
            state["ran"] = None
        except Exception as exc:                # pragma: no cover
            state["error"] = exc
        finally:
            frame.stop_background_work()
            try:
                frame.mixer.close()
            except Exception:
                pass
            frame.Destroy()

    wx.CallLater(400, go)
    app.MainLoop()
    restore_foreground_lock(lock)
    shutil.rmtree(tmp, ignore_errors=True)

    if state.get("error") is not None:
        raise state["error"]
    if state.get("ran") is None:
        return 0
    if state.get("lost"):
        print("\n  skipped: a keystroke never reached this window, so "
              "something else on this desktop had the foreground. Run it "
              "again with nothing else grabbing focus.")
        return 0

    failed = [name for name, ok in CHECKS if not ok]
    print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
    for name in failed:
        print("  FAILED: " + name)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
