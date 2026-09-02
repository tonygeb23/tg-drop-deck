"""Every menu, audited rather than read through.

    python tests/test_menus.py

A menu is the only part of this app somebody can use without knowing a single
keystroke, so it is the part that has to be right for a first-time screen
reader user. This walks the real menu bar off a real frame and derives what it
checks, rather than holding a list that will go stale the moment a menu grows:

  * **Every item has a mnemonic**, so Alt plus a letter reaches it.
  * **No two items in one menu share one.** Windows cycles between duplicates
    instead of activating, so a duplicate silently turns one keystroke into
    two - and the second item is the one nobody finds.
  * **No shortcut a menu advertises is stolen by something else.** wx
    registers a menu item's own key for you, so a key absent from the
    accelerator table is fine - but a key present in it BEATS the menu. When
    2.5.0 gave Ctrl+Shift+S to the soundboard view, Save board as quietly
    stopped working and nothing anywhere said so. This is the check that
    catches that, and it is why F12 saves a board now.
  * **Every item is bound to something.** An item with no handler does
    nothing at all when chosen, and says nothing about it either.
  * **Nothing is named so vaguely it cannot be told apart when read aloud.**
"""

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tempfile as _tempfile
os.environ["APPDATA"] = _tempfile.mkdtemp(prefix="dropdeck-test-appdata-")

import wx

from dropdeck import constants as C
from dropdeck.board import Board
from dropdeck.ui import DropDeckFrame

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


#: wx spells the modifiers one way in an accelerator table and another way in
#: the text after the tab. This is the only place the two have to agree.
MODIFIERS = {"ctrl": wx.ACCEL_CTRL, "alt": wx.ACCEL_ALT, "shift": wx.ACCEL_SHIFT}
NAMED = {
    "enter": wx.WXK_RETURN, "return": wx.WXK_RETURN, "del": wx.WXK_DELETE,
    "delete": wx.WXK_DELETE, "esc": wx.WXK_ESCAPE, "escape": wx.WXK_ESCAPE,
    "space": wx.WXK_SPACE, "tab": wx.WXK_TAB, "backspace": wx.WXK_BACK,
    "up": wx.WXK_UP, "down": wx.WXK_DOWN, "left": wx.WXK_LEFT,
    "right": wx.WXK_RIGHT, "home": wx.WXK_HOME, "end": wx.WXK_END,
}
for _n in range(1, 25):
    NAMED["f%d" % _n] = getattr(wx, "WXK_F%d" % _n)


def parse_accelerator(text):
    """"Ctrl+Shift+P" -> (flags, keycode), or None if it cannot be read."""
    flags = 0
    key = None
    for part in text.split("+"):
        part = part.strip()
        low = part.lower()
        if low in MODIFIERS:
            flags |= MODIFIERS[low]
        elif low in NAMED:
            key = NAMED[low]
        elif len(part) == 1:
            key = ord(part.upper())
        else:
            return None
    if key is None:
        return None
    return flags, key


def walk(menu, path=""):
    """Every real item in a menu and its submenus, in order."""
    found = []
    for item in menu.GetMenuItems():
        if item.IsSeparator():
            continue
        sub = item.GetSubMenu()
        if sub is not None:
            found.extend(walk(sub, path + item.GetItemLabelText() + " > "))
            continue
        found.append((path, item))
    return found


def bound_ids():
    """Every id ui.py binds a menu handler to, read out of the source.

    wx offers no way to ask a window what it is bound to, and a hand-kept list
    would go stale the first time a menu grew - which is the failure this whole
    file exists to catch. So the bindings are read from the code that makes
    them, and an id that appears in a menu but in no Bind call is reported.
    """
    import dropdeck.ui as uimod
    import dropdeck.plids as plids
    source = io.open(uimod.__file__, encoding="utf-8").read()
    found = set()
    for name in re.findall(r"id=([A-Za-z_][A-Za-z0-9_.]*)", source):
        if name.startswith("wx."):
            value = getattr(wx, name[3:], None)
        else:
            value = getattr(uimod, name, None)
            if value is None:
                value = getattr(plids, name, None)
        if isinstance(value, int):
            found.add(value)
    # The slot hotkeys are bound as one range, id to id2.
    if "id2=ID_SLOT_BASE" in source:
        base = uimod.ID_SLOT_BASE
        found.update(range(base, base + C.TOTAL_SLOTS + 1))
    return found


app = wx.App(redirect=False)
frame = DropDeckFrame()
frame.board.path = os.path.join(_tempfile.mkdtemp(), "menus.json")
bar = frame.GetMenuBar()
BOUND = bound_ids()

# The accelerator table is the authority on what a key really does.
entries = frame._build_accelerators()
registered = {}
for entry in entries:
    registered.setdefault((entry.GetFlags(), entry.GetKeyCode()), set()).add(
        entry.GetCommand())

# ---------------------------------------------------------------------------
print("The menu bar")

titles = [bar.GetMenuLabel(i) for i in range(bar.GetMenuCount())]
check("there is a menu bar with menus on it", bar.GetMenuCount() >= 3, titles)
check("every menu has a mnemonic, so Alt reaches it",
      all("&" in t for t in titles), titles)

letters = [t[t.index("&") + 1].lower() for t in titles if "&" in t]
check("and no two menus share one",
      len(letters) == len(set(letters)),
      [t for t in titles])

# ---------------------------------------------------------------------------
print("Every item in every menu")

problems = {"no mnemonic": [], "unbound": [], "bad accelerator": [],
            "wrong command": []}
duplicates = []
total = 0

for position in range(bar.GetMenuCount()):
    menu = bar.GetMenu(position)
    title = bar.GetMenuLabel(position)
    seen = {}
    for path, item in walk(menu):
        total += 1
        label = item.GetItemLabel()
        where = "%s > %s%s" % (title, path, item.GetItemLabelText())

        # A mnemonic, and a unique one within this menu.
        text = label.split(chr(9))[0]
        if "&" not in text:
            problems["no mnemonic"].append(where)
        else:
            letter = text[text.index("&") + 1].lower()
            if letter in seen:
                duplicates.append("%s and %s both use Alt+%s in %s"
                                  % (seen[letter], item.GetItemLabelText(),
                                     letter.upper(), title))
            seen[letter] = item.GetItemLabelText()

        # Something has to happen when it is chosen.
        if item.GetId() not in BOUND:
            problems["unbound"].append(where)

        # What the label promises after the tab has to be real.
        if chr(9) in label:
            shortcut = label.split(chr(9))[1].strip()
            parsed = parse_accelerator(shortcut)
            if parsed is None:
                problems["bad accelerator"].append("%s (%s)" % (where, shortcut))
            elif parsed in registered and item.GetId() not in registered[parsed]:
                # THE check. wx registers a menu item's own shortcut for you,
                # so a key missing from the table is fine - but a key that IS
                # in the table beats the menu, and if it fires something else
                # the menu is advertising a key that no longer does what it
                # says. That is how Ctrl+Shift+S quietly stopped saving a
                # board when 2.5.0 gave it to the soundboard view.
                #
                # Ctrl+Tab and Alt+F4 are Windows' own and are advertised
                # without being ours to register.
                if shortcut.lower() not in ("ctrl+tab", "alt+f4"):
                    problems["wrong command"].append(
                        "%s promises %s, which fires something else"
                        % (where, shortcut))

check("there are menus worth auditing", total > 30, total)
check("every item has a mnemonic", not problems["no mnemonic"],
      problems["no mnemonic"])
check("no two items in one menu share a mnemonic", not duplicates, duplicates)
check("every item is bound to a handler", not problems["unbound"],
      problems["unbound"])
check("every advertised shortcut can be read", not problems["bad accelerator"],
      problems["bad accelerator"])
check("no advertised shortcut is stolen by something else",
      not problems["wrong command"], problems["wrong command"])

# ---------------------------------------------------------------------------
print("What the items say")

vague = []
for position in range(bar.GetMenuCount()):
    menu = bar.GetMenu(position)
    for _path, item in walk(menu):
        spoken = item.GetItemLabelText().strip()
        if len(spoken) < 3:
            vague.append(spoken)
check("no item is named too briefly to tell apart when read aloud", not vague,
      vague)

# The three things a first-timer has to be able to find without a keystroke.
labels = []
for position in range(bar.GetMenuCount()):
    for _path, item in walk(bar.GetMenu(position)):
        labels.append(item.GetItemLabelText().lower())
joined = " | ".join(labels)
for needed in ("microphone", "playlist", "drops li", "rename this bank",
               "assign a folder", "random drop", "crossfade"):
    check("the menus offer %r without needing a key" % needed,
          needed in joined, joined[:200])

# ---------------------------------------------------------------------------
print("The keys the menus advertise are the keys the app documents")

for shortcut in ("Ctrl+M", "Ctrl+Shift+M", "Ctrl+Shift+P", "Ctrl+Shift+S",
                 "Alt+D", "Ctrl+F2", "Ctrl+V", "Ctrl+F12"):
    check("F1 help documents %s" % shortcut, shortcut in C.KEYBOARD_HELP)

# ---------------------------------------------------------------------------
try:
    frame.stop_background_work()
except Exception:
    pass
try:
    frame.mixer.close()
except Exception:
    pass
frame.Destroy()

failed = [n for n, ok in CHECKS if not ok]
print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
