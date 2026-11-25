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


def headers(menu, path=""):
    """Every submenu HEADER, with the level it sits on.

    A header answers a mnemonic at its own level like any item does, and
    `walk` steps straight past it into the submenu, so a header could share a
    letter with an item beside it and nothing here saw it. On air had "Who is
    &listening" and "Streaming &location" both on Alt+L from 3.8.2 to 3.9.0,
    which Windows treats as two items to cycle between, so Alt+L reached
    neither. Jessica found it by walking the real menu bar.
    """
    found = []
    for item in menu.GetMenuItems():
        sub = item.GetSubMenu()
        if sub is not None:
            found.append((path, item))
            found.extend(headers(sub, path + item.GetItemLabelText() + " > "))
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
# No sound card. The row and bed menus below are read while something plays,
# and nothing in this file needs to be heard.
import dropdeck.ui as _uimod                           # noqa: E402
from dropdeck.mixer import MixerGroup as _MixerGroup   # noqa: E402


class _QuietGroup(_MixerGroup):
    def __init__(self, *args, **kw):
        kw["open_stream"] = False
        super().__init__(*args, **kw)


_uimod.MixerGroup = _QuietGroup
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


def audit(bar):
    """(items, problems, duplicates) for the menu bar as it reads NOW.

    A function, because several items relabel themselves (Go live, the send,
    the recordings) and the labels they change to have to be audited as well
    as the ones the window opens with. "Come off air" and "Open the
    recordings folder" both answered Alt+F while live from 3.8.2 until the
    review of 24 November 2026, and this file only ever saw the menu off air.
    """
    problems = {"no mnemonic": [], "unbound": [], "bad accelerator": [],
                "wrong command": []}
    duplicates = []
    total = _audit_into(bar, problems, duplicates)
    return total, problems, duplicates


def _audit_into(bar, problems, duplicates):
    total = 0
    for position in range(bar.GetMenuCount()):
        menu = bar.GetMenu(position)
        title = bar.GetMenuLabel(position)
        # ONE NAMESPACE PER MENU LEVEL, which is how Windows actually resolves a
        # mnemonic: only the open level is listening, so Alt+D on a submenu item
        # cannot be confused with Alt+D on the menu above it, which is shut by
        # then. This used to pool a whole top level menu and its submenus into
        # one namespace, deliberately stricter than Windows, and On air had
        # reached the point where that strictness was the binding constraint:
        # 22 of 26 letters were spoken for and the four spare ones (j, q, x, z)
        # appear in no label anybody would write, so the menu could not accept
        # another item at all. That is the guard deciding the product rather
        # than protecting it.
        #
        # Within one level the check is unchanged, and that is the half that
        # matters: two items you can see at once must not answer the same key.
        seen_by_level = {}
        for path, item in headers(menu):
            text = item.GetItemLabel().split(chr(9))[0]
            where = "%s > %s%s" % (title, path, item.GetItemLabelText())
            if "&" not in text:
                problems["no mnemonic"].append(where)
                continue
            seen = seen_by_level.setdefault(path, {})
            letter = text[text.index("&") + 1].lower()
            if letter in seen:
                duplicates.append("%s and %s both use Alt+%s in %s"
                                  % (seen[letter], item.GetItemLabelText(),
                                     letter.upper(), title))
            seen[letter] = item.GetItemLabelText()
        for path, item in walk(menu):
            total += 1
            seen = seen_by_level.setdefault(path, {})
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
    return total


total, problems, duplicates = audit(bar)
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
print("The labels that change, as they read while it is happening")


class _Sending:
    """A send that is running, for the label that says so."""

    is_running = True

    class confidence:
        on = False


def _states():
    """Put the menu bar in each state the app relabels it for, in turn.

    Through the frame's own relabelling functions, the ones going live, a
    send and a recording call, so the words audited are the words shown.
    """
    board = frame.board
    was = board.live_to
    for name, live_to, live, sending, recording in (
            ("live on video", C.LIVE_TO_VIDEO, True, False, False),
            ("live on radio", C.LIVE_TO_AUDIO, True, False, False),
            ("sending", C.LIVE_TO_VIDEO, False, True, False),
            ("recording", C.LIVE_TO_VIDEO, False, False, True),
            ("live, sending and recording at once", C.LIVE_TO_AUDIO, True,
             True, True)):
        board.live_to = live_to
        frame.send = _Sending() if sending else None
        frame._set_air_labels(live)
        frame._sync_send_menu()
        frame._set_record_label(recording)
        frame._set_video_record_label(recording)
        yield name
    frame.send = None
    board.live_to = was
    frame._set_air_labels(False)
    frame._sync_send_menu()
    frame._set_record_label(False)
    frame._set_video_record_label(False)


for state in _states():
    _total, state_problems, state_duplicates = audit(bar)
    check("%s, no two items in one menu share a mnemonic" % state,
          not state_duplicates, state_duplicates)
    check("%s, every item still has one" % state,
          not state_problems["no mnemonic"], state_problems["no mnemonic"])
    check("%s, and every shortcut still does what it says" % state,
          not state_problems["wrong command"],
          state_problems["wrong command"])

# ---------------------------------------------------------------------------
print("The two menus opened on one thing: a playlist row, and a bed")

# They are built when they are opened, so they are opened: the frame's own
# handlers build them, and PopupMenu is stood in to read the menu and return
# at once instead of waiting for a click.
_popped = []


def _read_popup(self, menu, *args, **kw):
    letters, missing = {}, []
    for item in menu.GetMenuItems():
        if item.IsSeparator():
            continue
        text = item.GetItemLabel().split(chr(9))[0].replace("&&", "")
        if "&" not in text:
            missing.append(item.GetItemLabelText())
            continue
        letters.setdefault(text[text.index("&") + 1].lower(), []).append(
            item.GetItemLabelText())
    _popped.append((letters, missing))
    return True


def _shared(letters):
    return {k: v for k, v in letters.items() if len(v) > 1}


import numpy as _np                                    # noqa: E402
import soundfile as _sf                                # noqa: E402

_sounds = _tempfile.mkdtemp(prefix="dropdeck-menus-sounds-")


def _wav(name, seconds):
    path = os.path.join(_sounds, name + ".wav")
    _sf.write(path, _np.zeros((int(48000 * seconds), 2), _np.float32), 48000)
    return path


_saved_popup = {cls: cls.__dict__.get("PopupMenu")
                for cls in (wx.Window, wx.ListCtrl, wx.Button)}
for _cls in _saved_popup:
    _cls.PopupMenu = _read_popup
try:
    _panel = frame.playlist_panel
    _panel.add_paths([_wav("Song A", 4.0), _wav("Song B", 4.0)])
    frame.board.playlist.insert_drop(_wav("Ident", 1.0), at=1)
    _panel.refresh()
    for _playing in (False, True):
        if _playing:
            frame.play_playlist(0)
        for _row in range(len(frame.board.playlist)):
            _panel.select(_row)
            _popped.clear()
            _event = wx.ContextMenuEvent(wx.wxEVT_CONTEXT_MENU,
                                         _panel.list.GetId())
            _event.SetEventObject(_panel.list)
            _panel.list.GetEventHandler().ProcessEvent(_event)
            _letters, _missing = _popped[0] if _popped else ({}, ["no menu"])
            check("the playlist row menu on row %d%s has no letter twice"
                  % (_row + 1, ", playing" if _playing else ""),
                  _popped and not _shared(_letters), _shared(_letters))
            check("and every item on it has one", not _missing, _missing)
    frame.stop_playlist(quiet=True)

    _bed = frame.board.bank_slots(C.LOOPING_BANK)[0]
    _bed.filepath = _wav("Bed", 3.0)
    _bed.name = "Bed"
    for _playing in (False, True):
        if _playing:
            frame.trigger(_bed.index)
        _popped.clear()
        frame.show_slot_menu(_bed, frame._button_for(_bed))
        _letters, _missing = _popped[0] if _popped else ({}, ["no menu"])
        check("the bed menu%s has no letter twice"
              % (", playing" if _playing else ""),
              _popped and not _shared(_letters), _shared(_letters))
        check("and every item on it has one", not _missing, _missing)
    frame.mixer.stop_all(fade_out=0.0)
finally:
    for _cls, _method in _saved_popup.items():
        if _method is None:
            try:
                del _cls.PopupMenu
            except AttributeError:
                pass
        else:
            _cls.PopupMenu = _method

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

# The eight above were a hand kept list, and a hand kept list is exactly how
# F1 fell eight keys behind the menus without one check failing. Derive it
# instead: every key a MENU advertises has to be in F1, because F1 is what
# the app itself calls the list of keys.
#
# One exemption, with its reason, the same shape check_guide.py uses.
NOT_IN_F1 = {
    "Alt+F4": "closes a window in every Windows program, so it is not this "
              "app's key to document",
}
advertised = set()
for position in range(bar.GetMenuCount()):
    for _path, item in walk(bar.GetMenu(position)):
        label = item.GetItemLabel()
        if chr(9) in label:
            advertised.add(label.split(chr(9))[1].strip())
undocumented = sorted(key for key in advertised
                      if key not in C.KEYBOARD_HELP and key not in NOT_IN_F1)
check("every key the menus advertise is in F1, with no hand kept list",
      not undocumented, undocumented)
check("and there are plenty of them to check", len(advertised) >= 30,
      len(advertised))

# ---------------------------------------------------------------------------
print("No two commands share an id")

# Tony, 5 September 2026: "ctrl shift A brings up preferences when I want to
# check listeners etc."
#
# Every menu item, button and accelerator is addressed by a number, and two
# names for the same number is two commands wired to one wire: whichever
# handler was bound last answers for both. It is invisible in the source,
# because the two definitions are hundreds of lines apart and each looks
# perfectly reasonable, and it is invisible in a test that calls the handler
# rather than pressing the key. Ctrl+Shift+A opened Preferences because the
# new id landed on Set up streaming, and Escape landed on Search.
import ast as _ast
import pathlib as _pathlib

from dropdeck import plids as _plids
from dropdeck import ui as _ui

_numbers = {}
for _module, _path in ((_ui, "dropdeck/ui.py"), (_plids, "dropdeck/plids.py")):
    _tree = _ast.parse(_pathlib.Path(_path).read_text(encoding="utf-8"))
    for _node in _tree.body:
        if isinstance(_node, _ast.Assign) and len(_node.targets) == 1:
            _target = _node.targets[0]
            if isinstance(_target, _ast.Name) and _target.id.startswith("ID_"):
                _numbers.setdefault(getattr(_module, _target.id),
                                    set()).add(_target.id)
_clashes = {n: sorted(names) for n, names in _numbers.items() if len(names) > 1}
check("every command id is its own number", not _clashes,
      "; ".join("%d is both %s" % (n, " and ".join(names))
                for n, names in sorted(_clashes.items())))
check("and there are plenty of them to check", len(_numbers) > 50,
      len(_numbers))

# The two that were wrong, by name, so a future renumbering cannot quietly
# put either back.
check("Ctrl+Shift+A is not Set up streaming",
      _ui.ID_STREAM_STATS != _ui.ID_STREAM_SETUP)
check("and Escape is not Search", _ui.ID_STOP_ALL_KEY != _ui.ID_SEARCH)

# Each accelerator has to reach a command that something actually handles.
_entries = frame._build_accelerators()
_known = set(_numbers)
_orphans = [e.ToString() for e in _entries
            if e.GetCommand() not in _known
            and not (_ui.ID_SLOT_BASE <= e.GetCommand()
                     <= _ui.ID_SLOT_BASE + C.TOTAL_SLOTS)]
check("every key in the map points at a command that exists", not _orphans,
      _orphans)

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
