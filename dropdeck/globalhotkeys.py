"""System-wide hotkeys, so a sound fires while another window has focus.

This is the point of a soundboard on a live show. You are in the DAW, or the
call software, or a browser, and you need the sting *now*, alt-tabbing to the
board first is the whole problem.

Three rules, and they are why this is a separate opt-in layer rather than the
existing keys being made global:

  1. **It never registers a bare key.** Making `1` a system-wide hotkey would
     take the digit away from every other program on the machine, including the
     one you are typing into. Every global hotkey needs at least one modifier,
     and this module refuses to register anything that does not. Nor Shift
     plus a printable key, nor Ctrl plus copy, paste and the like, for the
     same reason: see `refusal`.
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


def _parts(text):
    """(modifier bits, [every key in it that is not a modifier]).

    A single character keeps its own case, because the keyboard layout is
    asked about the character as written.
    """
    mods, keys = 0, []
    for raw in str(text or "").replace("-", "+").split("+"):
        part = raw.strip()
        if not part:
            continue
        if part.upper() in MODIFIER_NAMES:
            mods |= MODIFIER_NAMES[part.upper()]
        else:
            keys.append(part if len(part) == 1 else part.upper())
    return mods, keys


def _character_key(char):
    """The virtual key that types one character on this keyboard, or None.

    Letters and digits are their own codes on every Windows layout. Anything
    else is asked of the current layout, and counts only when the layout
    types it with no Shift, Ctrl or Alt. **Never `ord()`**: the code of an
    apostrophe is 0x27, which is VK_RIGHT, so Ctrl+' registered Ctrl+Right
    Arrow, Ctrl+. took Delete and Ctrl+, took Print Screen (Mark, 24
    November 2026). A character this cannot place is refused.
    """
    if char.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        return ord(char.upper())
    try:
        scan = ctypes.windll.user32.VkKeyScanW
        scan.argtypes = [ctypes.c_wchar]
        scan.restype = ctypes.c_short
        found = int(scan(char))
    except Exception:
        return None
    if found == -1:
        return None
    vk, shift_state = found & 0xFF, (found >> 8) & 0xFF
    if shift_state or vk in (0, 0xFF):
        return None
    return vk


def _key_code(part):
    if part in NAMED_KEYS:
        return NAMED_KEYS[part]
    if len(part) == 1:
        return _character_key(part)
    return None


def parse(text):
    """"Ctrl+Alt+F9" -> (modifiers, virtual key). None if it cannot be used.

    Returns None for a bare key with no modifier. That is not a parse failure,
    it is a refusal: a system-wide hotkey with no modifier takes that key away
    from every other program running. None too for more than one key that is
    not a modifier: this kept the last one, so Ctrl+F9+V registered Ctrl+V.
    """
    mods, keys = _parts(text)
    if len(keys) != 1 or mods == 0:
        return None
    key = _key_code(keys[0])
    if key is None:
        return None
    return mods | MOD_NOREPEAT, key


#: What Ctrl plus each of these does in nearly every Windows program. A
#: global hotkey on one takes it away from all of them: a board holding
#: Ctrl+C as a pad's global hotkey stopped copy working anywhere on the
#: machine while global hotkeys were on (Mark, 24 November 2026).
CTRL_KEYS_EVERYBODY_NEEDS = {
    "A": "select all", "C": "copy", "V": "paste", "X": "cut", "Z": "undo",
    "Y": "redo", "S": "save", "F": "find", "N": "new", "O": "open",
    "P": "print", "W": "close",
}

#: Keys that move, select and edit in every program, with what they do.
#: With any ONE modifier they are Shift+Tab, Ctrl+Left, Shift+End, Win+Up
#: and the rest, which nobody can lose.
EDITING_KEYS = {
    "TAB": "moves between controls in every program",
    "INSERT": "edits text in nearly every program",
    "DELETE": "edits text in nearly every program",
    "BACKSPACE": "edits text in nearly every program",
    "LEFT": "moves or selects in nearly every program",
    "RIGHT": "moves or selects in nearly every program",
    "UP": "moves or selects in nearly every program",
    "DOWN": "moves or selects in nearly every program",
    "HOME": "moves or selects in nearly every program",
    "END": "moves or selects in nearly every program",
    "PAGEUP": "moves or selects in nearly every program",
    "PAGEDOWN": "moves or selects in nearly every program",
}

#: Windows' own, whatever program is in front.
WINDOWS_KEYS = {
    (MOD_ALT, "F4"): "closes the window in every program",
    (MOD_ALT, "TAB"): "switches between programs",
    (MOD_CONTROL, "TAB"): "moves between tabs in nearly every program",
    (MOD_ALT, "SPACE"): "opens the window menu in every program",
}

#: What `why_not` says for Shift plus a printable key, kept as a name
#: because the window used to compare against it.
TYPES = "types a character in every program"

#: What `why_not` says for Ctrl+Alt plus a character. A name, so the startup
#: line can say it the short way for several pads at once.
ALTGR = ("is AltGr to Windows, which types characters such as @ and the "
         "euro sign on many keyboards")


def why_not(text):
    """Why this may not be a GLOBAL hotkey, as a clause after "it", or "".

    "" for anything a global hotkey may have, and for what `parse` refuses on
    its own (a bare key, a name it does not know), which `describe` words.
    Separate from `parse`, which also reads this app's own menu keys, Ctrl+S
    among them, to find out which of them another program holds.
    """
    mods, keys = _parts(text)
    if not mods or not keys:
        return ""
    if len(keys) > 1:
        return "has more than one key besides Ctrl, Alt, Shift and Windows"
    key = keys[0]
    if len(key) == 1 and _character_key(key) is None:
        return ("is a character this keyboard types with Shift or not at "
                "all, so it cannot be told apart from another key")
    if parse(text) is None:
        return ""
    single = bin(mods).count("1") == 1
    upper = key.upper()
    if (mods, upper) in WINDOWS_KEYS:
        return WINDOWS_KEYS[(mods, upper)]
    if single and upper in EDITING_KEYS:
        return EDITING_KEYS[upper]
    if mods == MOD_CONTROL and upper in CTRL_KEYS_EVERYBODY_NEEDS:
        return "is %s in nearly every program" % CTRL_KEYS_EVERYBODY_NEEDS[upper]
    if mods == MOD_SHIFT and (len(key) == 1 or upper == "SPACE"):
        return TYPES
    if mods == MOD_CONTROL | MOD_ALT and len(key) == 1:
        # Windows reads Ctrl+Alt as AltGr, and on most European layouts
        # AltGr is how @, the euro sign and the braces are typed.
        return ALTGR
    return ""


def refusal(text):
    """Why a combination must not be a GLOBAL hotkey, as a sentence, or "".

    It adds to the rule that a global hotkey needs a modifier, which `parse`
    keeps. Every rule is in `why_not`.
    """
    why = why_not(text)
    if not why:
        return ""
    return ("%s cannot be a global hotkey, because it %s. A function key with "
            "Ctrl or Alt is the safest choice." % (text, why))


def usable(text):
    """Can this be registered as a global hotkey at all."""
    return parse(text) is not None and not why_not(text)


def describe(text):
    """Why a hotkey was refused, in words the user can act on."""
    if not text:
        return "No hotkey set."
    if why_not(text):
        return refusal(text)
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
        self._refused = {}         # slot index -> hotkey text `refusal` kept back
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

    @property
    def refused(self):
        """Hotkeys never offered to Windows, because they would take a key
        every program needs. See `refusal`. Not failures: nobody else has
        them, and saying another program does would be untrue."""
        with self._lock:
            return dict(self._refused)

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
            self._refused.clear()

        hotkey_id = 1
        for index, text in sorted(wanted.items()):
            parsed = parse(text)
            if refusal(text):
                # The last word, whoever asked: a board file is the usual
                # way one of these arrives, and the window filters them too.
                with self._lock:
                    self._refused[index] = text
                continue
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
