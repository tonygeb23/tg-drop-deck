"""Find, and optionally remove, em and en dashes.

    python tools/nodashes.py            report every one, with its line
    python tools/nodashes.py --fix      replace them with plain punctuation

Tony's standing rule, 2 September 2026: no em dashes or en dashes anywhere. An
em dash is one of the loudest tells that a machine wrote something, and this
app's text is read aloud, where a dash is either silence or the words "em
dash". Neither is what the sentence meant.

TWO RULES THIS TOOL LEARNED THE HARD WAY
----------------------------------------
**It only ever touches a dash.** The first version also ran tidy-up regexes
over the whole file to clean up after itself, and one of them turned

    BANK_MISC: ("",) * SLOTS_PER_BANK

into `("") * SLOTS_PER_BANK`, which is an empty string rather than a tuple of
twenty. Bank four's hotkey labels silently became "". A text tool that edits
code it was not asked to edit is worse than no tool, so this one replaces the
dash character and changes nothing else on the line.

**It cannot write prose.** Swapping a dash for a comma leaves comma splices,
and no regex can tell a good comma from a bad one. It says so at the end, and
it means it: read the diff.
"""

import io
import os
import re
import sys

EM = chr(8212)
EN = chr(8211)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "dist", "build", "demo", "boards", ".idea"}
SUFFIXES = (".py", ".md", ".txt", ".iss")


def files(root):
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(names):
            if name.endswith(SUFFIXES):
                yield os.path.join(base, name)


def clean_line(line):
    """One line, with its dashes replaced and nothing else changed.

    Only the dash and the whitespace immediately around it are touched. No
    tidy-up passes over the rest of the line: see the module docstring for
    what that cost the first time.
    """
    if EM not in line and EN not in line:
        return line

    # A range of numbers or letters: 1-0, 11-20, A-Z.
    line = re.sub(r"(?<=\w)\s*" + EN + r"\s*(?=\w)", " to ", line)
    line = line.replace(EN, "-")

    # An em dash between spaces is a pause: a comma carries it, and a human
    # decides afterwards whether it wanted a full stop.
    line = re.sub(r"\s+" + EM + r"\s+", ", ", line)
    # One at the start of a line, usually a continued thought.
    line = re.sub(r"^(\s*)" + EM + r"\s*", r"\1", line)
    # Anything left: a dash with no space on one side.
    line = re.sub(r"\s*" + EM + r"\s*", ", ", line)
    return line


def main():
    fix = "--fix" in sys.argv
    found = 0
    touched = 0
    for path in files(HERE):
        try:
            text = io.open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        count = text.count(EM) + text.count(EN)
        if not count:
            continue
        found += count
        rel = os.path.relpath(path, HERE).replace(os.sep, "/")
        if not fix:
            print("%s  (%d)" % (rel, count))
            for number, line in enumerate(text.splitlines(), 1):
                if EM in line or EN in line:
                    print("   %4d  %s" % (number, line.strip()[:96]))
            continue
        lines = text.split("\n")
        cleaned = "\n".join(clean_line(line) for line in lines)
        if cleaned != text:
            io.open(path, "w", encoding="utf-8", newline="").write(cleaned)
            touched += 1
            print("%-46s %d removed" % (rel, count))

    print()
    if not found:
        print("No em or en dashes anywhere. Good.")
        return 0
    if fix:
        print("%d dash(es) removed from %d file(s)." % (found, touched))
        print()
        print("NOW READ THE DIFF. A dash swapped for a comma leaves comma")
        print("splices behind, and this tool cannot tell a good comma from a")
        print("bad one. Anything a person reads or hears wants a full stop far")
        print("more often than it wants a comma.")
        return 0
    print("%d dash(es) found. Run with --fix, then read the diff." % found)
    return 1


if __name__ == "__main__":
    sys.exit(main())
