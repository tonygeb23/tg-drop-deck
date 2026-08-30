"""System-wide hotkeys, so a sound fires while another window has focus.

This is the point of a soundboard on a live show. You are in the DAW, or the
call software, or a browser, and you need the sting *now* — alt-tabbing to the
board first is the whole problem.

Three rules, and they are why this is a separate opt-in layer rather than the
existing keys being made global:

  1. **It never registers a bare key.** Making `1` a system-wide hotkey would
     take the digit away from every other program on the machine, including the
     one you are typing into. Every global hotkey needs at least one modifier,
     and this module refuses to register anything that does not.
  2. **The in-app map is untouched.** `1`-`0` with Shift, Ctrl, Ctrl+Shift and
     Alt+Ctrl still work exactly as they always have while the board has focus.
     A global hotkey is a *second*, separate key the user assigns on purpose.
  3. **It can be turned off in one keystroke** (Ctrl+G). While global hotkeys
     are on, this app owns those combinations everywhere; the user has to be
     able to hand them back without hunting through a menu.

Windows posts WM_HOTKEY to the thread that called RegisterHotKey. wx gives no
way to see that message, so registration and the message pump both live on a
dedicated thread here, and firing hops back to the UI thread with CallAfter.
That hop costs well under a millisecond, and a global hotkey is pressed from
another application anyway, so it is nowhere near the local hot path that
CLAUDE.md protects.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading

import wx

user32 = ctypes.windll.user32

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000          # holding the key fires once, not eighty times
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

#: Names accepted in a hotkey string, mapped to a Windows virtual key code.
NAMED_KEYS = {
    "SPACE": 0x20, "ENTER": 0x0D, "RETURN": 0x0D, "TAB": 0x09,
    "BACKSPACE": 0x08, "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24,
    "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "NUMPAD0": 0x60, "NUMPAD1": 0x61, "NUMPAD2": 0x62, "NUMPAD3": 0x63,
    "NUMPAD4": 0x64, "NUMPAD5": 0x65, "NUMPAD6": 0x66, "NUMPAD7": 0x67,
    "NUMPAD8": 0x68, "NUMPAD9": 0x69,
}
for _n in range(1, 25):
    NAMED_KEYS[f"F{_n}"] = 0x6F + _n

MODIFIER_NAMES = {"CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL,
                  "ALT": MOD_ALT, "SHIFT": MOD_SHIFT,
                  "WIN": MOD_WIN, "WINDOWS": MOD_WIN}


def parse(text):
    """"Ctrl+Alt+F9" -> (modifiers, virtual key). None if it cannot be used.

    Returns None for a bare key with no modifier. That is not a parse failure,
    it is a refusal: a system-wide hotkey with no modifier takes that key away
    from every other program running.
    """
    if not text:
        return None
    mods, key = 0, None
    for part in str(text).replace("-", "+").split("+"):
        part = part.strip().upper()
        if not part:
            continue
        if part in MODIFIER_NAMES:
            mods |= MODIFIER_NAMES[part]
        elif part in NAMED_KEYS:
            key = NAMED_KEYS[part]
        elif len(part) == 1:
            key = ord(part)
        else:
            return None
    if key is None or mods == 0:
        return None
    return mods | MOD_NOREPEAT, key


def describe(text):
    """Why a hotkey was refused, in words the user can act on."""
    if not text:
        return "No hotkey set."
    if parse(text) is None:
        if "+" not in str(text):
            return ("A global hotkey needs a modifier. %s on its own would be "
                    "taken away from every other program." % text)
        return "%s is not a hotkey this can register." % text
    return ""


class GlobalHotkeys:
    """Owns the listener thread and the registrations.

    `on_fire(slot_index)` is called on the UI thread when a hotkey is pressed.
    """

    def __init__(self, on_fire, on_problem=None):
        self.on_fire = on_fire
        self.on_problem = on_problem or (lambda message: None)
        self.enabled = False
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._wanted = {}          # slot index -> hotkey text
        self._registered = {}      # hotkey id -> slot index
        self._failed = {}          # slot index -> hotkey text that would not register
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- state
    def set_bindings(self, bindings):
        """bindings: {slot_index: "Ctrl+Alt+F9"}. Re-registers if running."""
        with self._lock:
            self._wanted = dict(bindings)
        if self.enabled:
            self.stop()
            self.start()

    @property
    def failures(self):
        """Hotkeys Windows would not give us, usually because another program
        already owns them. Reported rather than swallowed: a hotkey that
        silently does nothing is worse than one that says it is taken."""
        with self._lock:
            return dict(self._failed)

    def count(self):
        with self._lock:
            return len(self._registered)

    # -------------------------------------------------------------- control
    def start(self):
        if self.enabled:
            return True
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dropdeck-hotkeys")
        self._thread.start()
        self._ready.wait(timeout=3.0)
        self.enabled = True
        return True

    def stop(self):
        """Hand every combination back to the rest of the system."""
        if not self.enabled:
            return
        tid = self._thread_id
        if tid:
            user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None
        self.enabled = False

    def toggle(self):
        if self.enabled:
            self.stop()
        else:
            self.start()
        return self.enabled

    # --------------------------------------------------------------- thread
    def _run(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        with self._lock:
            wanted = dict(self._wanted)
            self._registered.clear()
            self._failed.clear()

        hotkey_id = 1
        for index, text in sorted(wanted.items()):
            parsed = parse(text)
            if parsed is None:
                with self._lock:
                    self._failed[index] = text
                continue
            mods, key = parsed
            if user32.RegisterHotKey(None, hotkey_id, mods, key):
                with self._lock:
                    self._registered[hotkey_id] = index
                hotkey_id += 1
            else:
                # Almost always ERROR_HOTKEY_ALREADY_REGISTERED: some other
                # program got there first. Nothing we can do but say so.
                with self._lock:
                    self._failed[index] = text

        self._ready.set()
        try:
            if self._failed:
                self._to_ui(self._report_failures)

            msg = ctypes.wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    with self._lock:
                        index = self._registered.get(msg.wParam)
                    if index is not None:
                        self._to_ui(self.on_fire, index)
        finally:
            # Unregister in a finally, always. Anything that escapes the loop
            # otherwise leaves the combinations owned by this process until it
            # dies - registered with Windows, firing nothing, and unavailable
            # to every other program. That is exactly what happened when a
            # wx.CallAfter with no wx.App raised in here and killed the thread
            # before it ever reached the message loop.
            for hid in list(self._registered):
                user32.UnregisterHotKey(None, hid)
            with self._lock:
                self._registered.clear()

    @staticmethod
    def _to_ui(func, *args):
        """Hop to the UI thread, but never take the listener down trying.

        wx.CallAfter asserts if no wx.App exists, which is true in a test and
        would be true for a moment during startup.
        """
        try:
            if wx.GetApp() is not None:
                wx.CallAfter(func, *args)
            else:
                func(*args)
        except Exception:
            pass

    def _report_failures(self):
        failures = self.failures
        if not failures:
            return
        taken = ", ".join(sorted(set(failures.values())))
        self.on_problem(
            "These global hotkeys could not be registered, most likely because "
            "another program already uses them: %s" % taken)
