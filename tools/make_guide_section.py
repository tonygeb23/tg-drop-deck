"""Write the manual's video streaming chapter from the app's own help text.

    python tools/make_guide_section.py            print it
    python tools/make_guide_section.py --write    put it into the guide

The manual lives in another repository, at
`Websites/tgstudios.app/content/pages/drop-deck-guide.md`. That is the right
place for it, and it is also why `tools/check_guide.py` exists: documentation
kept somewhere else goes stale in silence.

Steps a user follows word by word are the worst possible thing to keep in two
places, so they are not kept in two places. `dropdeck/streamhelp.py` holds
them, the app shows them on Help, Setting up streaming, and this renders the
same text as the chapter. Change the steps once and both follow.

**It does not deploy anything.** Writing the guide file is a change in the
website repository, which is published separately.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import constants as C
from dropdeck import streamhelp
from dropdeck import streamout

GUIDE = os.path.join(
    os.path.expanduser("~"), "Dropbox", "Websites", "tgstudios.app",
    "content", "pages", "drop-deck-guide.md")

HEADING = "## 23. Streaming video to YouTube, Facebook and Restream"

#: Where the chapter goes: after the audio streaming one, before Stations.
AFTER_HEADING = "## 22. Streaming"
BEFORE_HEADING = "## 23. Stations"


def render():
    """The chapter, as markdown."""
    out = [HEADING, ""]
    out.append(
        "Drop Deck can send your show to YouTube, Facebook, Restream or any "
        "other server that speaks RTMP, with a picture, and without a second "
        "program in the chain.")
    out.append("")
    out.append(
        "**All of this is also in the app**, on **Help, Setting up "
        "streaming**, and on the **How do I set this up?** button on the "
        "Video streaming page. It is the same text, so it cannot go out of "
        "date against what the app does.")
    out.append("")
    out.append(
        "**Video streaming is a page of its own**, separate from the audio "
        "streaming page that feeds a radio station. They are separate jobs "
        "with none of the same settings: no mount point, no port, no format, "
        "a stream key instead of a password, and a picture. `Ctrl+B` goes to "
        "one of them, and which one is a tick box on the Video streaming "
        "page.")
    out.append("")
    out.append(
        "**Something has to be on the screen.** YouTube will not take sound "
        "on its own, so a radio show still sends a picture. A card with your "
        "station name and whatever is playing is the default and costs almost "
        "nothing.")
    out.append("")

    for platform in streamhelp.ORDER:
        spec = streamhelp.PLATFORMS[platform]
        out.append("### %s" % streamout.server_label(platform))
        out.append("")
        for heading, items in streamhelp.steps_for(platform):
            out.append("**%s**" % heading)
            out.append("")
            numbered = heading == "Setting it up"
            for index, item in enumerate(items, 1):
                out.append(("%d. %s" % (index, item)) if numbered
                           else "- %s" % item)
            out.append("")

    out.append("### What goes on the screen")
    out.append("")
    for line in streamhelp.PICTURE:
        out.append("- %s" % line)
    out.append("")

    out.append("### Knowing what the camera can see")
    out.append("")
    out.append(
        "This is the part of camera streaming worth having. You cannot look "
        "at a preview window, so the app tells you instead.")
    out.append("")
    for line in streamhelp.FRAMING:
        out.append("- %s" % line)
    out.append("")

    out.append("### If something goes wrong")
    out.append("")
    out.append("| What it says | What to do |")
    out.append("|---|---|")
    for what, fix in streamhelp.TROUBLE:
        out.append("| %s | %s |" % (what, fix))
    out.append("")
    return "\n".join(out)


def _anchor(title):
    """The anchor a markdown heading gets, the way the site generates them."""
    out = []
    for ch in title.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -":
            out.append("-")
    text = "".join(out)
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-")


def renumber(text, from_number):
    """Shift every chapter at or after `from_number` up by one.

    Headings AND the contents list, because a contents entry that points at a
    heading which has moved is worse than no contents: a screen reader user
    follows the link and lands in the wrong chapter.
    """
    import re

    def bump_heading(match):
        number = int(match.group(1))
        if number < from_number:
            return match.group(0)
        return "## %d. %s" % (number + 1, match.group(2))

    text = re.sub(r"^## (\d+)\. (.+)$", bump_heading, text, flags=re.M)

    def bump_entry(match):
        number = int(match.group(1))
        title = match.group(2)
        if number < from_number:
            return match.group(0)
        new = number + 1
        return "- [%d. %s](#%s)" % (new, title, _anchor("%d %s" % (new, title)))

    return re.sub(r"^- \[(\d+)\. ([^\]]+)\]\(#[^)]+\)$", bump_entry,
                  text, flags=re.M)


def add_to_contents(text, number, title):
    """Put the new chapter in the contents, under Getting it out."""
    entry = "- [%d. %s](#%s)" % (number, title,
                                 _anchor("%d %s" % (number, title)))
    if entry in text:
        return text
    anchor_line = "- [22. Streaming](#22-streaming)"
    if anchor_line not in text:
        return text
    return text.replace(anchor_line, anchor_line + "\n" + entry, 1)


def splice(guide_text, chapter):
    """Put the chapter in, replacing an older copy of it if there is one."""
    if HEADING in guide_text:
        start = guide_text.index(HEADING)
        rest = guide_text[start + len(HEADING):]
        end = rest.find("\n## ")
        tail = rest[end + 1:] if end != -1 else ""
        return guide_text[:start] + chapter + "\n" + tail
    if BEFORE_HEADING not in guide_text:
        raise SystemExit(
            "Could not find %r in the guide, so there is nowhere obvious to "
            "put the chapter. Add it by hand." % BEFORE_HEADING)
    # Everything from Stations onward moves up one, headings and contents
    # together, before the new chapter goes into the gap that leaves. A
    # contents entry pointing at a heading that has moved is worse than no
    # contents: somebody follows the link and lands in the wrong chapter.
    guide_text = renumber(guide_text, 23)
    guide_text = add_to_contents(
        guide_text, 23, "Streaming video to YouTube, Facebook and Restream")
    at = guide_text.index("## 24. Stations")
    return guide_text[:at] + chapter + "\n" + guide_text[at:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="put it into the guide file")
    parser.add_argument("--guide", default=GUIDE)
    args = parser.parse_args()

    chapter = render()
    if not args.write:
        print(chapter)
        print("# %d lines. Run with --write to put it in %s"
              % (len(chapter.splitlines()), args.guide), file=sys.stderr)
        return

    if not os.path.isfile(args.guide):
        raise SystemExit("No guide at %s" % args.guide)
    with open(args.guide, "r", encoding="utf-8") as handle:
        text = handle.read()
    updated = splice(text, chapter)
    if updated == text:
        print("The guide already says exactly this. Nothing written.")
        return
    with open(args.guide, "w", encoding="utf-8") as handle:
        handle.write(updated)
    print("Wrote the chapter into %s" % args.guide)
    print("The guide is a separate repository. Nothing has been published.")


if __name__ == "__main__":
    main()
