"""Colours you can choose without being able to see them.

Branding is the one thing on a stream that is purely visual, so it is the
hardest thing in this app to do without sight, and a colour wheel is not an
answer: it is the problem restated. Everywhere else this app has taken the
same line, which is that the app MEASURES what a sighted person would glance
at and SAYS it. Colour is no different, and it turns out to be the easiest of
the lot, because legibility is arithmetic.

## What was measured, on 8 September 2026, through the real encoder

A caption was drawn in nine colour pairs, encoded as the app really encodes
(H.264, yuv420p, 1280x720) and decoded back:

    combination            WCAG    what came back
    white on dark navy    16.7:1   perfect
    black on white        21.0:1   perfect
    orange on navy         8.0:1   perfect
    red on blue            2.1:1   DESTROYED
    cyan on magenta        2.5:1   DESTROYED
    yellow on white        1.1:1   crisp and unreadable

**The two that were destroyed had zero brightness difference to begin with.**
Measured directly: the greyscale edge between red text and a blue background,
before any encoding, is 0. The text is carried entirely by hue. Video chroma
is stored at half resolution in 4:2:0, so hue detail is exactly what gets
thrown away, and what came back was chroma bleed rather than letters.

**So one number covers both failures, and it is the WCAG contrast ratio.**
It is a ratio of *relative luminance*, which is brightness, so it scores
red-on-blue at 2.1:1 for the same reason the encoder ruins it: there is no
brightness there. A rule about subsampling would have been a second thing to
explain and it would have caught nothing this does not.

The app therefore never asks the user to judge a colour. It says the number
and what the number means.

## Why named colours rather than a picker

A hex field or a colour wheel asks somebody to imagine the result. A short
list of named colours asks them to choose one, and every name in it can be
read out. The trade is the same one the overlay makes with named places
rather than a canvas: fewer possibilities, all of them checkable.
"""
from __future__ import annotations

#: The named colours, in the order the list offers them. Chosen to be a
#: usable brand palette rather than a rainbow: a few darks that work as a
#: background, a few lights that work as text, and a few accents with enough
#: brightness range to pair with either.
#:
#: Names are what a screen reader says, so they are ordinary words. "Slate"
#: rather than "#2E3440", and nothing is called "primary" or "surface".
NAMED = (
    ("black", (0, 0, 0)),
    ("near black", (14, 18, 28)),
    ("charcoal", (32, 34, 40)),
    ("slate", (48, 56, 72)),
    ("navy", (16, 32, 72)),
    ("deep purple", (48, 24, 72)),
    ("dark green", (16, 56, 40)),
    ("maroon", (72, 20, 28)),
    ("brown", (72, 48, 24)),
    ("mid grey", (128, 128, 128)),
    ("teal", (0, 128, 128)),
    ("blue", (24, 96, 200)),
    ("green", (32, 150, 72)),
    ("red", (200, 40, 40)),
    ("orange", (255, 140, 0)),
    ("gold", (232, 184, 40)),
    ("pink", (232, 96, 152)),
    ("light blue", (128, 184, 248)),
    ("light green", (144, 216, 160)),
    ("cream", (248, 240, 216)),
    ("off white", (240, 242, 248)),
    ("white", (255, 255, 255)),
)

BY_NAME = {name: rgb for name, rgb in NAMED}
NAMES = tuple(name for name, _rgb in NAMED)


def rgb(name, fallback=(240, 242, 248)):
    """One named colour, or the fallback when the name is not one of ours."""
    return BY_NAME.get(name, fallback)


def name_of(value, fallback="off white"):
    """The name of a colour, for saying out loud. Nearest by brightness and
    hue when it is not exactly one of ours, so a board from another version
    still describes itself rather than reading out three numbers."""
    if value is None:
        return fallback
    got = tuple(int(v) for v in value[:3])
    for name, known in NAMED:
        if known == got:
            return name
    best, gap = fallback, None
    for name, known in NAMED:
        far = sum((a - b) ** 2 for a, b in zip(known, got))
        if gap is None or far < gap:
            best, gap = name, far
    return best


# ---------------------------------------------------------------------------
# Legibility, which is the whole point
# ---------------------------------------------------------------------------

def luminance(value):
    """WCAG 2 relative luminance, 0 to 1.

    The sRGB channels are linearised and weighted by how bright the eye finds
    each one: green counts for most of brightness and blue for almost none,
    which is why blue text on black is so much worse than it looks on paper.
    """
    out = []
    for channel in value[:3]:
        c = channel / 255.0
        # 0.04045, not the 0.03928 WCAG 2.0 shipped. That figure came from
        # an obsolete IEC draft and the W3C corrected it in May 2021
        # (w3c/wcag issue 308). It moves nothing at 8 bits, but a number this
        # app says out loud should be the right one.
        out.append(c / 12.92 if c <= 0.04045
                   else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(one, two):
    """The WCAG 2 contrast ratio between two colours, 1.0 to 21.0."""
    a, b = luminance(one), luminance(two)
    high, low = (a, b) if a >= b else (b, a)
    return (high + 0.05) / (low + 0.05)


#: What a ratio has to reach. WCAG's own thresholds are 4.5:1 for body text
#: and 3:1 for large text, and overlay captions ARE large text, so 3:1 is the
#: floor rather than the target. 4.5 is used as the target anyway because a
#: stream is watched on a phone in daylight, recompressed, at whatever size
#: the platform feels like, and none of that is true of a web page.
CONTRAST_GOOD = 4.5
CONTRAST_FLOOR = 3.0


def verdict(front, back):
    """What to SAY about two colours together. Never a number on its own.

    The number matters and means nothing by itself to somebody who has never
    seen contrast, so it is always said with what it implies.
    """
    ratio = contrast(front, back)
    if ratio >= 7.0:
        return ratio, "easy to read"
    if ratio >= CONTRAST_GOOD:
        return ratio, "readable"
    if ratio >= CONTRAST_FLOOR:
        return ratio, "readable at this size, but only just"
    if ratio >= 2.0:
        return ratio, "too close together to read"
    return ratio, "almost invisible"


#: Above this, a colour visibly frays at the edges once it is encoded, and
#: no amount of contrast or bitrate repairs it. Measured 8 September 2026
#: through a real encoder: the error on a letter's edge tracks saturation
#: almost exactly, at roughly 1.27 eight-bit levels per percent, and it is
#: unchanged from 1 Mbps to 6 Mbps because subsampling, not the bitrate, is
#: what does it. 60 percent is where the fringe reaches about a third of the
#: range and starts to be visible on a letter rather than only on a chart.
FRINGE_LIMIT = 0.60


def saturation(value):
    """How far a colour is from grey, 0 to 1.

    Value form, not lightness form: what matters is how much colour the
    encoder has to carry in the half resolution planes, and that is the gap
    between the strongest and weakest channel.
    """
    channels = [c for c in value[:3]]
    high = max(channels)
    if not high:
        return 0.0
    return (high - min(channels)) / float(high)


def fringing(value):
    """Whether a colour will fray at the edges on video, and by how much.

    **This is a SECOND question, and contrast cannot answer it.** Contrast
    is a brightness ratio, and brightness is the half of the picture that
    survives 4:2:0 intact. Colour is stored at half resolution in both
    directions, so a strongly coloured letter keeps its shape and loses its
    edges, whatever its contrast. The two faults have two different repairs:
    poor contrast wants a different pair or a heavier outline, and fringing
    wants a less saturated colour. Nothing else fixes it, bitrate included.
    """
    level = saturation(value)
    return level, level > FRINGE_LIMIT


def even(thickness):
    """A coloured line's thickness, rounded to an even number of pixels.

    Not fussiness. Colour is stored one sample per two by two block, so a
    coloured line an odd number of pixels high straddles two of those blocks
    and shares each with whatever is beside it. Measured 8 September 2026: a
    one pixel red rule lost 57 levels of colour, two pixels lost 12, and
    THREE pixels lost 17, worse than two. The app was drawing three at 720p.
    """
    return max(2, int(thickness) // 2 * 2)


def describe_pair(front_name, back_name):
    """One sentence about a pair, ready to be spoken."""
    ratio, said = verdict(rgb(front_name), rgb(back_name))
    line = "%s on %s: %s, %.1f to 1" % (front_name, back_name, said, ratio)
    level, frays = fringing(rgb(front_name))
    if frays:
        line += ", and strong enough to fray at the edges on video"
    return line


def readable(front, back):
    """Whether a pair clears the floor. Used by the pre-flight."""
    return contrast(front, back) >= CONTRAST_FLOOR


# ---------------------------------------------------------------------------
# Whole looks, so nobody has to assemble one
# ---------------------------------------------------------------------------

#: Ready-made sets, every one of which was checked against the numbers above
#: rather than chosen by eye. `tests/test_colours.py` asserts that every
#: single one clears CONTRAST_GOOD on both of its pairs, so a preset can
#: never ship unreadable.
SCHEMES = (
    ("Default", "near black", "off white", "light blue"),
    ("Ink", "black", "white", "gold"),
    ("Slate", "slate", "off white", "light blue"),
    ("Midnight", "navy", "cream", "gold"),
    ("Forest", "dark green", "cream", "light green"),
    ("Wine", "maroon", "cream", "pink"),
    ("Coffee", "brown", "cream", "gold"),
    ("Grape", "deep purple", "off white", "pink"),
    ("Paper", "cream", "black", "red"),
    ("Daylight", "white", "black", "blue"),
)

SCHEME_NAMES = tuple(name for name, _b, _t, _a in SCHEMES)


def scheme(name):
    """One ready-made look as (background, text, accent) names."""
    for got, back, text, accent in SCHEMES:
        if got == name:
            return back, text, accent
    return SCHEMES[0][1:]


def describe_scheme(name):
    """A whole look, said out loud, with the number that matters."""
    back, text, accent = scheme(name)
    ratio, said = verdict(rgb(text), rgb(back))
    return "%s: %s on %s, %s, %.1f to 1. %s for the rule and the edges." % (
        name, text, back, said, ratio, accent.capitalize())
