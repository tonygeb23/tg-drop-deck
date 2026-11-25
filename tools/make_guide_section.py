"""Write the manual's video streaming steps from the app's own help text.

    python tools/make_guide_section.py            print them
    python tools/make_guide_section.py --write    put them into the guide

On a machine somebody is using, run it through `tools/run_private.py`. That
passes no arguments, so a wrapper that sets `sys.argv` and calls `main()` is
how `--write` gets there.

The manual lives in another repository, at
`Websites/tgstudios.app/content/pages/drop-deck-guide.md`. That is the right
place for it, and it is also why `tools/check_guide.py` exists: documentation
kept somewhere else goes stale in silence.

Steps a user follows word by word are the worst possible thing to keep in two
places, so they are not kept in two places. `dropdeck/streamhelp.py` holds
them, the app shows them on Help, Setting up streaming, and this renders the
same steps into the chapter. Change the steps once and both follow.

**It writes only its own part of the chapter**: the four platforms, What goes
on the screen, Knowing what the camera can see and If something goes wrong.
The chapter's opening paragraphs, and every section after those four, are
written in the guide by hand and are never touched. The first version
replaced the whole chapter, so one run would have put back an opening
sentence two releases out of date and deleted the stream key section.

**It finds the chapter by its title, never by its number, and it never adds
or renumbers a chapter.** It looked for "## 23." long after the chapter had
become 27. Renumbering moved the headings and the contents and left every
"chapter 32" in the text pointing at the old number. When it cannot find its
part, or would leave two copies of a section, it writes nothing and says why.

**The help is written for a text box and the guide for a page**, so the
words are the help's and the marks are the guide's: a key the help spells
out, "Control Shift B", is `Ctrl+Shift+B`; capitals used for emphasis are
bold; the label over each group is a heading, so a screen reader can move by
it; a line on its own is a paragraph rather than a list of one; and If
something goes wrong is a bold question and its answer, the way the guide's
own trouble chapter is written. The help says "YouTube will not take sound on
its own" in the steps every platform shares, so under the other three it is
left out.

**It does not deploy anything.** Writing the guide file is a change in the
website repository, which is published separately.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import streamhelp
from dropdeck import streamout

GUIDE = os.path.join(
    os.path.expanduser("~"), "Dropbox", "Websites", "tgstudios.app",
    "content", "pages", "drop-deck-guide.md")

#: The chapter this writes into, found by its title.
CHAPTER = "Streaming video to YouTube, Facebook and Restream"

#: The sections after the four platforms that this writes too.
AFTER_PLATFORMS = ("What goes on the screen",
                   "Knowing what the camera can see",
                   "If something goes wrong")

#: Words in the help that are in capitals because that is how they are
#: spelled. Any other word in capitals is emphasis.
SPELLED_IN_CAPITALS = frozenset((
    "OK", "RTMP", "RTMPS", "OBS", "MP3", "MP4", "AAC", "URL", "HD", "TV",
    "NVDA", "JAWS", "USB", "NAS", "PC", "DJ"))

#: The shared steps say this for every platform. It is about YouTube.
YOUTUBE_ONLY = re.compile(r"\s*YouTube will not take sound on its own[^.]*\.")

#: Drop Deck's own boxes, buttons and menus, in bold as the rest of the guide
#: names them. Whole phrases, so the Show box is bolded and the word "show"
#: never is. A phrase the help no longer uses simply matches nothing.
LABELS = (
    ("On air, Streaming location", "**On air, Streaming location**"),
    ("Get my stream key", "**Get my stream key**"),
    ("Check my stream key", "**Check my stream key**"),
    ("Look through the camera now", "**Look through the camera now**"),
    ("the Platform box", "the **Platform** box"),
    ("the Show box", "the **Show** box"),
    ("the Camera box", "the **Camera** box"),
    ("the Address box", "the **Address** box"),
    ("into Address.", "into **Address**."),
    ("into Stream key", "into **Stream key**"),
    ("Lower Picture quality", "Lower **Picture quality**"),
    ("The Go live here when I press Control B box",
     "The **Go live here when I press Control B** box"),
)

#: A line of What goes on the screen or Knowing what the camera can see that
#: starts with a choice's own name has that name in bold. Longest first.
CHOICES = ("Tell me when something is wrong", "Tell me about every change",
           "Do not tell me about the shot", "A picture of my own", "A camera",
           "A card")

_WORD = re.compile(r"[A-Za-z0-9']+")
_MODIFIER_WORDS = ("CONTROL", "ALT", "SHIFT")
_SPELLED_KEY = re.compile(
    r"\b((?:(?:Control|Alt|Shift) )+)(F\d{1,2}|[A-Z0-9])\b")


def _shouted(text, tokens, k, first):
    """Is token k part of a run of capitals, starting at token `first`?"""
    word = tokens[k].group(0)
    if k > first and text[tokens[k - 1].end():tokens[k].start()] != " ":
        return False                    # only a single space joins a run
    if len(word) == 1:
        # A key's own letter, as in CONTROL B, belongs to the run around it.
        return (k > first and word.isupper()
                and tokens[k - 1].group(0) in _MODIFIER_WORDS)
    return (word.isalpha() and word.isupper()
            and word not in SPELLED_IN_CAPITALS)


def _starts_sentence(text, at):
    before = text[:at].rstrip()
    return not before or before.endswith((".", "!", "?"))


def _quieter(text):
    """Capitals used for emphasis, as bold, in ordinary case.

    "PRESSING CONTROL B PUTS YOU LIVE STRAIGHT AWAY." is a whole sentence and
    becomes a bold one; "Copy BOTH the address" becomes "Copy **both** the
    address". CONTROL, ALT and SHIFT keep a capital and a key's letter keeps
    its own, so a key in the run is still spelled as a key afterwards.
    """
    tokens = list(_WORD.finditer(text))
    out = []
    done = 0
    i = 0
    while i < len(tokens):
        j = i
        while j < len(tokens) and _shouted(text, tokens, j, i):
            j += 1
        if j == i:
            i += 1
            continue
        start, end = tokens[i].start(), tokens[j - 1].end()
        pieces = []
        for k in range(i, j):
            word = tokens[k].group(0)
            if k > i:
                pieces.append(" ")
            if word in _MODIFIER_WORDS:
                pieces.append(word.capitalize())
            elif len(word) == 1:
                pieces.append(word)
            else:
                pieces.append(word.lower())
        phrase = "".join(pieces)
        opens = _starts_sentence(text, start)
        if opens:
            phrase = phrase[0].upper() + phrase[1:]
        out.append(text[done:start])
        if opens and text[end:end + 1] == ".":
            # The whole sentence was in capitals: its full stop goes in too.
            out.append("**%s.**" % phrase)
            done = end + 1
        else:
            out.append("**%s**" % phrase)
            done = end
        i = j
    out.append(text[done:])
    return "".join(out)


def _keys(text):
    """A key the help spells out, "Control Shift B", as `Ctrl+Shift+B`."""
    def written(match):
        words = ["Ctrl" if word == "Control" else word
                 for word in match.group(1).split()]
        return "`%s`" % "+".join(words + [match.group(2)])
    return _SPELLED_KEY.sub(written, text)


def _guide_words(text):
    """One line of the help, marked the way the guide marks things."""
    text = _quieter(text)
    for phrase, marked in LABELS:
        text = text.replace(phrase, marked)
    return _keys(text)


def _named(line):
    """A choice's own name, at the start of its line, in bold."""
    for name in CHOICES:
        if line.startswith(name + " "):
            return "**%s**%s" % (name, line[len(name):])
    return line


def _block(items, numbered=False):
    """Lines as the guide writes them: a list, or one paragraph on its own."""
    items = [_guide_words(item) for item in items]
    if numbered:
        return ["%d. %s" % (n, item) for n, item in enumerate(items, 1)] + [""]
    if len(items) == 1:
        return [items[0], ""]
    return ["- %s" % item for item in items] + [""]


def titles():
    """The headings of every section this writes, in order."""
    return ([streamout.server_label(platform)
             for platform in streamhelp.ORDER] + list(AFTER_PLATFORMS))


def render():
    """This tool's part of the chapter, as markdown."""
    out = []
    for platform in streamhelp.ORDER:
        out += ["### %s" % streamout.server_label(platform), ""]
        for heading, items in streamhelp.steps_for(platform):
            if platform != "youtube":
                items = [YOUTUBE_ONLY.sub("", item) for item in items]
            out += ["#### %s" % heading, ""]
            out += _block(items, numbered=heading == "Setting it up")

    out += ["### What goes on the screen", ""]
    out += _block([_named(line) for line in streamhelp.PICTURE])

    out += ["### Knowing what the camera can see", "",
            "This is the part of camera streaming worth having. You cannot "
            "look at a preview window, so the app tells you instead.", ""]
    out += _block([_named(line) for line in streamhelp.FRAMING])

    out += ["### If something goes wrong", ""]
    for what, fix in streamhelp.TROUBLE:
        out += ["**%s.** %s" % (_guide_words(what), _guide_words(fix)), ""]
    return "\n".join(out).rstrip("\n") + "\n"


def splice(guide_text, block):
    """The guide with this tool's part of the chapter replaced by `block`.

    Raises SystemExit, having changed nothing, when the chapter or this
    tool's first section in it cannot be found, or when the result would
    hold any of its sections other than exactly once.
    """
    chapter = re.search(r"^## \d+\. %s$" % re.escape(CHAPTER), guide_text,
                        re.M)
    if chapter is None:
        raise SystemExit(
            "No chapter called %r in the guide. Nothing written: this "
            "replaces its own part of that chapter, and never adds or "
            "renumbers one." % CHAPTER)
    following = re.search(r"^## ", guide_text[chapter.end():], re.M)
    chapter_end = (chapter.end() + following.start() if following
                   else len(guide_text))
    body = guide_text[chapter.start():chapter_end]

    names = titles()
    first = re.search(r"^### %s$" % re.escape(names[0]), body, re.M)
    if first is None:
        raise SystemExit(
            "The chapter has no %r section, so there is nowhere certain to "
            "put the steps. Nothing written." % ("### " + names[0]))
    # Up to the first section heading after it that is not this tool's.
    stop = len(body)
    for heading in re.finditer(r"^### (.+)$", body[first.start():], re.M):
        if heading.group(1).strip() not in names:
            stop = first.start() + heading.start()
            break
    rest = body[stop:]
    new_body = (body[:first.start()] + block.rstrip("\n") + "\n\n"
                + rest.lstrip("\n"))
    for name in names:
        count = len(re.findall(r"^### %s$" % re.escape(name), new_body, re.M))
        if count != 1:
            raise SystemExit(
                "Writing the steps would leave %d copies of %r in the "
                "chapter, so a section the guide wrote by hand is probably "
                "in among them. Nothing written: move it after If something "
                "goes wrong." % (count, "### " + name))
    return guide_text[:chapter.start()] + new_body + guide_text[chapter_end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="put them into the guide file")
    parser.add_argument("--guide", default=GUIDE)
    args = parser.parse_args()

    block = render()
    if not args.write:
        print(block)
        print("# %d lines. Run with --write to put them in %s"
              % (len(block.splitlines()), args.guide), file=sys.stderr)
        return

    if not os.path.isfile(args.guide):
        raise SystemExit("No guide at %s" % args.guide)
    # Read and written untranslated, so the file keeps the line endings it
    # has. Text mode on Windows would turn every one into CRLF.
    with open(args.guide, "r", encoding="utf-8", newline="") as handle:
        raw = handle.read()
    ending = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    updated = splice(text, block)
    if updated == text:
        print("The guide already says exactly this. Nothing written.")
        return
    with open(args.guide, "w", encoding="utf-8", newline="") as handle:
        handle.write(updated.replace("\n", ending))
    print("Wrote the streaming steps into %s" % args.guide)
    print("The guide is a separate repository. Nothing has been published.")


if __name__ == "__main__":
    main()
