"""Fact-check the published user guide against the app it describes.

    python tools/check_guide.py [path to drop-deck-guide.md]

A user guide is documentation that lives somewhere else, which is the kind that
goes stale silently. This reads the guide, pulls every keystroke out of it, and
checks each one against the accelerator table the app actually builds - plus
the specific numbers the guide quotes.

It is derived, not a list: add a key to the app and this finds it in the guide
or does not, without anybody remembering to update a checklist.
"""

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="guide-check-"))

import wx                                                       # noqa: E402

from dropdeck import constants as C                             # noqa: E402
from dropdeck.board import Board, demo_board_path               # noqa: E402
from dropdeck.ui import DropDeckFrame                           # noqa: E402

DEFAULT_GUIDE = os.path.join(
    os.path.expanduser("~"), "Dropbox", "Websites", "tgstudios.app",
    "content", "pages", "drop-deck-guide.md")

PROBLEMS = []
CHECKED = 0


def ok(label):
    global CHECKED
    CHECKED += 1
    print("  ok   " + label)


def bad(label, detail=""):
    global CHECKED
    CHECKED += 1
    PROBLEMS.append("%s  %s" % (label, detail))
    print("  WRONG " + label + ("  " + str(detail) if detail else ""))


def check(label, condition, detail=""):
    ok(label) if condition else bad(label, detail)


MODIFIERS = {"ctrl": wx.ACCEL_CTRL, "alt": wx.ACCEL_ALT, "shift": wx.ACCEL_SHIFT}
NAMED = {"enter": wx.WXK_RETURN, "del": wx.WXK_DELETE, "delete": wx.WXK_DELETE,
         "escape": wx.WXK_ESCAPE, "esc": wx.WXK_ESCAPE, "space": wx.WXK_SPACE,
         "tab": wx.WXK_TAB, "up": wx.WXK_UP, "down": wx.WXK_DOWN}
for _n in range(1, 25):
    NAMED["f%d" % _n] = getattr(wx, "WXK_F%d" % _n)


def parse(text):
    flags, key = 0, None
    for part in text.split("+"):
        low = part.strip().lower()
        if low in MODIFIERS:
            flags |= MODIFIERS[low]
        elif low in NAMED:
            key = NAMED[low]
        elif len(low) == 1:
            key = ord(low.upper())
        else:
            return None
    return None if key is None else (flags, key)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GUIDE
    if not os.path.exists(path):
        raise SystemExit("No guide at %s" % path)
    raw = open(path, encoding="utf-8").read()
    # The guide is hard-wrapped markdown, so any phrase longer than a few
    # words straddles a newline. Match against a whitespace-normalised copy:
    # otherwise this reports the guide as wrong for being wrapped, which is
    # the checker being wrong rather than the guide.
    guide = re.sub(r"\s+", " ", raw)

    app = wx.App(redirect=False)
    frame = DropDeckFrame()
    entries = frame._build_accelerators()
    registered = {(e.GetFlags(), e.GetKeyCode()) for e in entries}
    # Keys wx registers from a menu label rather than from the table.
    for position in range(frame.GetMenuBar().GetMenuCount()):
        for item in frame.GetMenuBar().GetMenu(position).GetMenuItems():
            if item.IsSeparator():
                continue
            label = item.GetItemLabel()
            if chr(9) in label:
                shortcut = parse(label.split(chr(9))[1].strip())
                if shortcut:
                    registered.add(shortcut)

    print("Every keystroke the guide names")
    # Backticked things that look like keys.
    quoted = set(re.findall(r"`([^`]+)`", raw))
    keyish = set()
    for text in quoted:
        text = text.strip()
        if not text or text.startswith("/"):
            continue
        if re.fullmatch(r"(?i)((ctrl|alt|shift)\+)*"
                        r"(f\d{1,2}|[a-z0-9]|enter|space|tab|delete|del|escape"
                        r"|up|down)", text):
            keyish.add(text)

    # Keys the app handles somewhere other than the accelerator table, with
    # the reason, so an unexplained miss is a real miss.
    HANDLED_ELSEWHERE = {
        "Ctrl+Tab": "the notebook's own, not ours to register",
        "Enter": "per control - a pad plays, a list row plays from there",
        "Space": "per control - a pad plays, a list row ticks",
        "Delete": "routed by view in _focused_action",
        "Escape": "menu accelerator on Stop everything",
        "Alt+Up": "the playlist list's own key handler",
        "Alt+Down": "the playlist list's own key handler",
        "Alt+P": ("the search dialog's char hook, the sound browser's preview "
                  "box, and a keyboard read done only while the Windows file "
                  "window is open and Drop Deck is in front"),
        "1": "the frozen digit map", "0": "the frozen digit map",
        "2": "the frozen digit map",
        # Named as an EXAMPLE of a global hotkey you could assign yourself,
        # not as a key the app ships with. Assigning it is the whole point of
        # the sentence it appears in.
        "Alt+A": "an example of a global hotkey, not a shipped one",
    }
    missing = []
    for text in sorted(keyish):
        shortcut = parse(text)
        if shortcut is None:
            continue
        if shortcut in registered or text in HANDLED_ELSEWHERE:
            continue
        missing.append(text)
    check("every key the guide names really exists in the app",
          not missing, "guide invents: %s" % missing)

    # And the reverse: a key in the app that the guide never mentions.
    print()
    print("Keys the app has that the guide should probably mention")
    important = {
        "F2": "rename", "Ctrl+F2": "rename bank", "F3": "sound volume",
        "F5": "bed volume", "F7": "playlist volume", "Ctrl+M": "microphone",
        "Ctrl+Shift+M": "mic settings", "Ctrl+Shift+P": "playlist",
        "Ctrl+Shift+S": "soundboard", "Alt+D": "random drop",
        "Ctrl+Shift+D": "drop from file", "Ctrl+V": "paste",
        "Ctrl+G": "global hotkeys", "Ctrl+L": "what is playing",
        "Ctrl+F": "search", "Ctrl+E": "search", "Ctrl+D": "ducking",
        "Ctrl+P": "audio settings", "Ctrl+F12": "save as", "F1": "help",
        "Alt+Enter": "properties", "Ctrl+Tab": "next bank",
    }
    absent = [key for key in important if key not in quoted]
    check("the guide names every key that matters", not absent, absent)

    print()
    print("The numbers the guide quotes")

    check("the demo pack is the size the guide says",
          "forty sounds" in guide.lower(),
          "guide says 'forty sounds'")
    if os.path.exists(demo_board_path()):
        demo = Board.load(demo_board_path())
        check("and the demo pack really holds that many",
              demo.assigned_count == 40, demo.assigned_count)
        first = demo[0].display_name.lower()
        check("press 1 really does give you applause",
              "applause" in first, "slot 1 is %r" % demo[0].display_name)
    else:
        bad("the demo pack is where the guide assumes", "not found")

    check("twenty slots a bank", C.SLOTS_PER_BANK == 20 and "Twenty slots" in guide)
    check("eighty in total", C.TOTAL_SLOTS == 80 and "eighty in total" in guide)
    check("four banks", C.BANK_COUNT == 4 and "four banks" in guide.lower())
    check("bank three is the looping bank",
          C.LOOPING_BANK == 3 and "bank three is still the looping bank" in guide)
    check("bank four takes the custom hotkeys", C.BANK_MISC == 4)

    check("ducking is about nine decibels",
          abs(C.DEFAULT_DUCK_DB) == 9.0 and "nine decibels" in guide,
          C.DEFAULT_DUCK_DB)
    check("the crossfade starts at three seconds",
          C.DEFAULT_CROSSFADE == 3.0 and "Three seconds" in guide,
          C.DEFAULT_CROSSFADE)
    check("there are three speech settings",
          len(C.SPEECH_LEVELS) == 3 and "three settings" in guide)
    check("and the guide quotes their real wording",
          all(label.split(",")[0].split(" - ")[0][:24] in guide
              for label in C.SPEECH_LABELS[:2]),
          list(C.SPEECH_LABELS))

    print()
    print("The claims about how it behaves")

    check("the guide's URL is the one the app opens",
          C.USER_GUIDE_URL.rstrip("/").endswith("drop-deck-guide"),
          C.USER_GUIDE_URL)
    check("a bed really does toggle", "Beds toggle" in guide)
    check("banks 1, 2 and 4 really do overlap",
          "banks 1, 2 and 4 overlap" in guide)
    check("a global hotkey really does need a modifier",
          "needs at least one modifier" in guide)
    check("Alt really does count as one, so Alt+A works",
          "`Alt` on its own counts" in guide)
    check("the app really does refuse a bare key",
          "the app refuses it" in guide)
    check("the microphone really does duck by being open",
          "because the microphone is *open*" in guide)
    check("monitoring really does start off",
          "off until you turn it on" in guide)
    check("nothing really does open the mic but the key",
          "except you pressing `Ctrl+M`" in guide)
    check("a folder slot really does avoid repeating itself",
          "never the same one twice running" in guide)
    check("Alt+D really does too",
          guide.count("never the same one twice running") >= 2)
    check("unticking really does keep a track in the list",
          "stays in the list and keeps its place" in guide)
    check("relink really does repair the playlist and library too",
          "playlist and your drops library out of the same search" in guide)
    check("feedback really does withhold names and paths",
          "Never a file name, a sound name, a bank name" in guide)
    check("the board really does save itself",
          "board saves itself" in guide)

    try:
        frame.stop_background_work()
        frame.mixer.close()
    except Exception:
        pass
    frame.Destroy()

    print()
    print("%d/%d claims check out" % (CHECKED - len(PROBLEMS), CHECKED))
    if PROBLEMS:
        print()
        for problem in PROBLEMS:
            print("  WRONG: " + problem)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
