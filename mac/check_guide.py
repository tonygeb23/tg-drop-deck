#!/usr/bin/env python3
"""Fact-check the published Mac manual against the app it describes.

    python3 mac/check_guide.py [path to drop-deck-guide-mac.md]

The Mac counterpart of tools/check_guide.py, for the same reason: a manual
that lives in another repository is the kind that goes stale in silence. It
reads the guide, pulls every keystroke out of it, and checks each against the
keys the BUILT app really binds, which the app itself reports with
--dump-keys. Derived, not a list: add a key to the app and this finds it in
the guide or does not, without anybody remembering to update a checklist.

Keys the guide mentions that the app handles somewhere other than its key map
are listed in EXPLAINED with the reason, so an unexplained miss is a real miss.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILT = os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                     "TG Studios Build", "drop-deck-mac", "TG Drop Deck.app",
                     "Contents", "MacOS", "TGDropDeck")
INSTALLED = "/Applications/TG Drop Deck.app/Contents/MacOS/TGDropDeck"
DEFAULT_GUIDE = os.path.join(
    os.path.expanduser("~"), "Library", "CloudStorage", "Dropbox", "Websites",
    "tgstudios.app", "content", "pages", "drop-deck-guide-mac.md")

#: Backticked things in the guide that look like keys but are not bound by the
#: app's own map, each with the reason.
EXPLAINED = {
    "fn": "a hardware modifier the Mac handles before any app sees it",
    "VO": "VoiceOver's own modifier, named to explain why the digit map moved",
    "Command": "a modifier named on its own in prose",
    "Option": "a modifier named on its own in prose",
    "Control": "a modifier named on its own in prose",
    "Shift": "a modifier named on its own in prose",
    "Ctrl": "the Windows modifier, named when explaining the translation",
    "Alt+Ctrl": "the Windows bed modifier, named when explaining the translation",
    "Control+Option": "VoiceOver's keys, named when explaining the translation",
    "Option+Control": "the literal Windows bed modifier, offered in Preferences, Keyboard",
    "Option+fn+Left": "what Option+Home is on a laptop keyboard",
    "Option+fn+Right": "what Option+End is on a laptop keyboard",
    "0": "the microphone's number in Source control, a list key",
    "6": "an example slot number in prose",
    "Command+Space": "Spotlight, named to explain why the stop key moved to Option+Space",
    "Control+Space": "the input source switcher, named for the same reason",
    "Tab": "AppKit's own key for moving between controls, named in prose",
    "Option+Control+Shift+S": "the literal Windows Source control key, kept as an alias",
}

MODIFIER_ORDER = ["Control", "Option", "Shift", "Command"]
SYNONYMS = {"Cmd": "Command", "Opt": "Option", "Ctrl": "Control", "Enter": "Return",
            "Esc": "Escape", "Del": "Delete", "Backspace": "Delete"}

PROBLEMS = []
CHECKED = 0


def check(label, condition, detail=""):
    global CHECKED
    CHECKED += 1
    if condition:
        print("  ok    " + label)
    else:
        PROBLEMS.append("%s  %s" % (label, detail))
        print("  WRONG " + label + ("  " + str(detail) if detail else ""))


def sorted_mods(mods):
    mods = [SYNONYMS.get(m, m) for m in mods]
    return sorted(mods, key=lambda m: MODIFIER_ORDER.index(m) if m in MODIFIER_ORDER else 99)


def normalise(text):
    """`Shift+Command+P` and `Command+Shift+P` are the same key. A token ending
    in a plus sign is a prefix standing for "that modifier and any digit"."""
    text = text.strip()
    parts = text.split("+")
    if text.endswith("+"):
        return "+".join(sorted_mods([p for p in parts if p])) + "+"
    mods = sorted_mods(parts[:-1])
    key = SYNONYMS.get(parts[-1], parts[-1])
    if key.lower() == "comma":
        key = "comma"
    elif len(key) == 1:
        key = key.upper()
    return "+".join(mods + [key])


def looks_like_key(token):
    if token.endswith("+"):
        return True                     # `Command+` digit, written as a prefix
    parts = token.split("+")
    key = parts[-1]
    mods_ok = all(m in MODIFIER_ORDER + ["Ctrl", "Alt", "fn", "VO", "Cmd", "Opt"] for m in parts[:-1])
    key_ok = (len(key) == 1 or key in ("Return", "Enter", "Space", "Tab", "Delete", "Escape",
                                       "Up", "Down", "Left", "Right", "Home", "End", "comma")
              or re.fullmatch(r"F\d{1,2}", key))
    return mods_ok and key_ok


def app_keys():
    binary = BUILT if os.path.exists(BUILT) else INSTALLED
    if not os.path.exists(binary):
        raise SystemExit("No built app. Run mac/build.sh first.")
    out = subprocess.run([binary, "--dump-keys"], capture_output=True, text=True, check=True).stdout
    keys = {normalise(line) for line in out.splitlines() if line.strip()}
    # A prefix like `Command+` in the guide stands for Command plus any digit.
    prefixes = set()
    for key in keys:
        parts = key.split("+")
        if parts[-1].isdigit() and len(parts) > 1:
            prefixes.add("+".join(parts[:-1]) + "+")
    return keys, prefixes, binary


def main():
    guide = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GUIDE
    text = open(guide, encoding="utf-8").read()
    keys, prefixes, binary = app_keys()
    print("Keys the built app reports: %d  (%s)" % (len(keys), binary))
    print()

    print("Every keystroke the guide mentions")
    mentioned = sorted(set(re.findall(r"`([^`\n]+)`", text)))
    for token in mentioned:
        if not looks_like_key(token):
            continue                    # a path, a file name, a word
        if token in EXPLAINED:
            check("%-28s explained: %s" % (token, EXPLAINED[token]), True)
            continue
        norm = normalise(token)
        if token.endswith("+"):
            check("%-28s a digit prefix the map has" % token, norm in prefixes, norm)
        else:
            check("%-28s bound by the app" % token, norm in keys, norm)

    print()
    print("Keys the app binds that the guide never mentions")
    guide_norm = {normalise(t) for t in mentioned}
    guide_prefixes = {normalise(t) for t in mentioned if t.endswith("+")}
    for key in sorted(keys):
        parts = key.split("+")
        if parts[-1].isdigit():
            prefix = "+".join(parts[:-1]) + "+" if len(parts) > 1 else ""
            if key in guide_norm or (prefix and prefix in guide_prefixes) or parts[-1] in ("1", "0"):
                continue
            if len(parts) == 1:
                continue                # a bare digit is written as 1 to 0
        elif key in guide_norm:
            continue
        # The Windows Control aliases are documented as a class, not one by one.
        alias = parts[0] == "Control" and (len(parts[-1]) == 1 or parts[-1] == "Tab")
        check("%-28s mentioned" % key, alias, "not in the guide")

    print()
    print("Things the guide states as fact")
    check("the guide names every format the app can send",
          all(w in text for w in ("AAC", "Opus", "WAV")))
    check("the guide says why there is no MP3",
          "no MP3" in text and "MP3 encoder" in text)
    check("the guide says the microphone can be kept in stereo",
          "keep it in stereo" in text.lower())
    check("the guide names the three source keys",
          all(k in text for k in ("Option+Command+C", "Option+Command+M",
                                  "Option+Command+S")))
    check("the guide says which macOS the taps need", "14.2" in text)
    check("the guide does not use an em dash or an en dash",
          "—" not in text and "–" not in text)
    check("the guide has no Windows Ctrl keys left in its tables",
          not re.search(r"\| `Ctrl\+", text))

    print()
    if PROBLEMS:
        print("%d of %d checks WRONG:" % (len(PROBLEMS), CHECKED))
        for p in PROBLEMS:
            print("  - " + p)
        sys.exit(1)
    print("All %d checks passed. The Mac manual matches the built app." % CHECKED)


if __name__ == "__main__":
    main()
