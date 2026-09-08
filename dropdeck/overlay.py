"""Things on top of the picture, in places that already fit.

Until now a stream showed exactly one thing: a card, or artwork, or a camera,
or the screen. Nothing on top of it. No station name, no song title, no clock.
This is what puts those there.

## Why named places instead of a canvas

OBS gives you a canvas and exact coordinates, and that is honest, and it is
the single thing about OBS that a blind broadcaster cannot use. The research
behind `docs/VISUALS-PLAN.md` could not find one account, anywhere, of a
blind person laying out a stream independently. Every guide resolves it the
same way: borrow a sighted person once, then never touch the layout again.

So there is no canvas here. There are four **named places**, each with a fixed
geometry that was chosen to be legible and that cannot overlap another. You
put content in a place. You cannot put it forty pixels off the bottom, you
cannot put two things on top of each other, and you can always be told what is
on screen, because the set of possible answers is four long.

That trades away arbitrary layout, which nobody in this audience is doing
anyway, for the thing OBS cannot offer: knowing.

## The rules that came out of measuring, and must not be undone

**`Image.alpha_composite` HOLDS THE GIL.** Measured 8 September 2026 against a
simulated audio wake-up: it made the audio thread late by up to 16.9 ms, as
bad as a pure Python busy loop, and it is 2.01x slower on two threads where
`Image.paste` is 1.00x. This whole app is built on nothing stalling the audio.
**Nothing here calls it.** Blending is numpy on a slice.

**Render on change, never per frame.** A tile is drawn when its text changes
and cached. Drawing costs about 2 ms; blending the cached tile costs about
2 ms; drawing every frame would spend the budget twice for nothing.

**Blend the rectangle, never the frame.** A region blend is about 2 ms. The
same arithmetic over a whole 1280x720 frame is 30 ms with integers and 42 ms
with floats, against a 33 ms budget. That one mistake would have made all of
this impossible and it is one line different.

**Integer maths.** See above.

**Tabular digits or the clock jitters.** Pillow's Windows wheels carry no
HarfBuzz, so `features=["tnum"]` cannot be reached and the font has to have
tabular figures by default. Roboto does. Impact and Bahnschrift do not, which
is why the obvious broadcast font is not the one bundled.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import numpy as np

from . import colours
from . import constants as C

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:      # pragma: no cover - Pillow missing is a real state
    Image = ImageDraw = ImageFont = None


def available():
    """Whether anything can be drawn on top of the picture at all."""
    return Image is not None


def why_unavailable():
    if available():
        return ""
    return "this copy cannot draw text on the picture"


# ---------------------------------------------------------------------------
# The fonts
# ---------------------------------------------------------------------------

def _font_dir():
    """Where the bundled fonts are, frozen or not."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "fonts")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
        __file__))), "assets", "fonts")


_FONTS = {}
_FONT_LOCK = threading.Lock()


def font(size, bold=True):
    """A bundled font at one size, made once and kept.

    Bundled rather than taken from Windows so a card looks the same on every
    machine, and because the digits have to be tabular: see the module note.
    Roboto is Apache 2.0, which is permissive and compatible with this app's
    MIT licence. `assets/fonts/LICENSE-Roboto.txt` ships beside it.
    """
    if ImageFont is None:
        return None
    key = (int(size), bool(bold))
    with _FONT_LOCK:
        got = _FONTS.get(key)
        if got is not None:
            return got
        name = C.FONT_BOLD if bold else C.FONT_REGULAR
        try:
            got = ImageFont.truetype(os.path.join(_font_dir(), name), int(size))
        except Exception:
            try:
                got = ImageFont.load_default(int(size))
            except Exception:
                return None
        _FONTS[key] = got
        return got


# ---------------------------------------------------------------------------
# The places
# ---------------------------------------------------------------------------

class Place:
    """One named place on the picture, as fractions of the frame.

    Fractions rather than pixels so the same layout holds at 720p, 1080p or
    anything else, and so nothing has to be re-measured when the size changes.
    """

    def __init__(self, key, label, left, top, right, bottom, size, align="left"):
        self.key = key
        self.label = label
        self._box = (left, top, right, bottom)
        self._size = size          # text height as a fraction of frame height
        self.align = align

    def rect(self, width, height):
        """Where this place is, in pixels, at one frame size."""
        left, top, right, bottom = self._box
        return (int(round(left * width)), int(round(top * height)),
                int(round(right * width)), int(round(bottom * height)))

    def text_size(self, height):
        return max(10, int(round(self._size * height)))

    def describe_where(self):
        return C.PLACE_WHERE.get(self.key, "")


#: The four places, and they are deliberately few and deliberately unable to
#: overlap. Two things in one spot is precisely the confusion that not being
#: able to look at the screen makes unrecoverable.
PLACES = [
    Place(C.PLACE_TOP, "Top strip", 0.030, 0.035, 0.700, 0.125, 0.052),
    Place(C.PLACE_CORNER, "Corner", 0.730, 0.035, 0.970, 0.125, 0.045,
          align="right"),
    Place(C.PLACE_LOWER, "Lower third", 0.047, 0.775, 0.640, 0.925, 0.068),
    Place(C.PLACE_CLOCK, "Clock", 0.680, 0.775, 0.953, 0.925, 0.062,
          align="right"),
]

PLACES_BY_KEY = {p.key: p for p in PLACES}


def place_label(key):
    got = PLACES_BY_KEY.get(key)
    return got.label if got else key


# ---------------------------------------------------------------------------
# Drawing one tile
# ---------------------------------------------------------------------------

def render_tile(text, width, height, size, align="left", panel=None,
                ink=None):
    """One place's picture, as RGBA, or None when there is nothing to say.

    A rounded panel with the text on it, outlined so it survives whatever is
    behind it. Drawn with Pillow because that is the only thing in the bundle
    that can put a real glyph on a pixel: `cv2` has only the Hershey stroke
    fonts, and numpy has no rasteriser at all.
    """
    if Image is None or not text:
        return None
    face = font(size, bold=True)
    if face is None:
        return None
    tile = Image.new("RGBA", (max(2, width), max(2, height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    panel = tuple(panel or C.OVERLAY_BACKGROUND)
    ink = tuple(ink or C.OVERLAY_FOREGROUND)
    draw.rounded_rectangle([0, 0, tile.width - 1, tile.height - 1],
                           radius=max(4, int(height * 0.16)),
                           fill=panel + (C.OVERLAY_ALPHA,))
    pad = max(8, int(height * 0.22))
    shown = _fit(draw, text, face, tile.width - pad * 2)
    box = draw.textbbox((0, 0), shown, font=face)
    y = (tile.height - (box[3] - box[1])) // 2 - box[1]
    if align == "right":
        x = tile.width - pad - (box[2] - box[0]) - box[0]
    else:
        x = pad
    # An outline, because the panel is translucent and whatever is behind it
    # is not ours to choose.
    # The outline is black or white depending on which the words are further
    # from, so an outline never makes text HARDER to see. Picking one and
    # keeping it would have made pale text on a pale panel worse.
    edge = (0, 0, 0) if colours.luminance(ink) > 0.4 else (255, 255, 255)
    draw.text((x, y), shown, font=face, fill=ink + (255,),
              stroke_width=max(1, int(size * 0.045)),
              stroke_fill=edge + (255,))
    return tile


def _fit(draw, text, face, room):
    """The text, shortened with an ellipsis if it will not fit."""
    if draw.textlength(text, font=face) <= room:
        return text
    ell = "..."
    cut = text
    while cut and draw.textlength(cut + ell, font=face) > room:
        cut = cut[:-1]
    return (cut + ell) if cut else ell


def fits(text, key, width, height):
    """Whether a string fits its place without being cut. For the pre-flight.

    Answerable before going on the air, which is the point: a title too long
    for the lower third is knowable now rather than discoverable by somebody
    watching.
    """
    if Image is None or not text:
        return True
    spot = PLACES_BY_KEY.get(key)
    if spot is None:
        return True
    left, top, right, bottom = spot.rect(width, height)
    face = font(spot.text_size(height), bold=True)
    if face is None:
        return True
    pad = max(8, int((bottom - top) * 0.22))
    probe = ImageDraw.Draw(Image.new("RGBA", (2, 2)))
    return probe.textlength(text, font=face) <= (right - left) - pad * 2


# ---------------------------------------------------------------------------
# The overlay
# ---------------------------------------------------------------------------

class Overlay:
    """What is on top of the picture, and how it gets there.

    Holds one string per place. Re-renders a tile only when its string
    changes, and blends the cached tiles onto a frame with numpy on a slice.
    Never touches `Image.alpha_composite`: see the module note.
    """

    def __init__(self, settings=None):
        self._lock = threading.Lock()
        self._text = {}            # place key -> the string showing now
        self._tiles = {}           # place key -> (rect, rgb uint16, alpha)
        self._size = (0, 0)
        self.station = ""
        self.title = ""
        self.renders = 0
        self.apply(settings or {})

    # ------------------------------------------------------------ settings --
    def apply(self, settings):
        """What each place is FOR, from the board."""
        with self._lock:
            self._kinds = {p.key: (settings.get("text_%s" % p.key)
                                   or C.TEXT_NONE) for p in PLACES}
            self._custom = {p.key: (settings.get("text_%s_words" % p.key) or "")
                            for p in PLACES}
            self._files = {p.key: (settings.get("text_%s_file" % p.key) or "")
                           for p in PLACES}
            self._file_seen = {}
            self._file_text = {}
            self._tiles = {}
            self._text = {}
        self.station = settings.get("name") or settings.get("stream_name") or ""
        self.panel = colours.rgb(settings.get("colour_background")
                                 or C.COLOUR_BACKGROUND)
        self.ink = colours.rgb(settings.get("colour_text") or C.COLOUR_TEXT)

    def kind_of(self, key):
        with self._lock:
            return self._kinds.get(key, C.TEXT_NONE)

    def set_title(self, title):
        """What is playing. Called from the same place the card is told."""
        self.title = title or ""

    # --------------------------------------------------------- the strings --
    def _wanted(self, key):
        """What this place should be saying right now."""
        kind = self._kinds.get(key, C.TEXT_NONE)
        if kind == C.TEXT_NONE:
            return ""
        if kind == C.TEXT_STATION:
            return self.station
        if kind == C.TEXT_PLAYING:
            return self.title
        if kind == C.TEXT_TIME:
            return time.strftime(C.OVERLAY_CLOCK_FORMAT)
        if kind == C.TEXT_WORDS:
            return self._custom.get(key, "")
        if kind == C.TEXT_FILE:
            return self._from_file(key)
        return ""

    def _from_file(self, key):
        """A text file, re-read when it changes. OBS's mechanism exactly.

        OBS polls the file's modification time once a second and re-reads on
        change, and that one 1 Hz stat call is the entire "now playing"
        ecosystem: every Spotify overlay and countdown script out there works
        by writing a text file. Copying it verbatim means every one of those
        tools works with this app too, for nothing.
        """
        path = self._files.get(key, "")
        if not path:
            return ""
        now = time.monotonic()
        seen = self._file_seen.get(key)
        if seen is not None and (now - seen[0]) < C.OVERLAY_FILE_POLL:
            return self._file_text.get(key, "")
        stamp = 0.0
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            self._file_seen[key] = (now, None)
            self._file_text[key] = ""
            return ""
        if seen is not None and seen[1] == stamp:
            self._file_seen[key] = (now, stamp)
            return self._file_text.get(key, "")
        text = ""
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read(C.OVERLAY_FILE_MAX).strip().splitlines()
            text = text[0].strip() if text else ""
        except OSError:
            text = ""
        self._file_seen[key] = (now, stamp)
        self._file_text[key] = text
        return text

    # ----------------------------------------------------------- rendering --
    def _tile_for(self, key, width, height):
        """The cached tile for one place, redrawn only when its text moved."""
        want = self._wanted(key)
        if self._size != (width, height):
            self._tiles = {}
            self._text = {}
            self._size = (width, height)
        if self._text.get(key) == want and key in self._tiles:
            return self._tiles[key]
        self._text[key] = want
        if not want:
            self._tiles[key] = None
            return None
        spot = PLACES_BY_KEY[key]
        left, top, right, bottom = spot.rect(width, height)
        picture = render_tile(want, right - left, bottom - top,
                              spot.text_size(height), spot.align,
                              panel=self.panel, ink=self.ink)
        if picture is None:
            self._tiles[key] = None
            return None
        raw = np.asarray(picture)
        # Split once, into the shapes the blend wants, so the hot path does
        # no conversion at all.
        rgb = np.ascontiguousarray(raw[:, :, :3]).astype(np.uint16)
        alpha = np.ascontiguousarray(raw[:, :, 3]).astype(np.uint16)[:, :, None]
        self.renders += 1
        self._tiles[key] = ((left, top, right, bottom), rgb, alpha)
        return self._tiles[key]

    def draw_on(self, frame):
        """Put everything on a frame, in place. Returns the frame.

        Called on the streaming thread, once per video frame, so it does the
        least possible: a cache lookup per place and an integer blend over
        that place's rectangle only.
        """
        if Image is None or frame is None:
            return frame
        height, width = frame.shape[0], frame.shape[1]
        with self._lock:
            for spot in PLACES:
                try:
                    tile = self._tile_for(spot.key, width, height)
                except Exception:
                    tile = None
                if tile is None:
                    continue
                (left, top, right, bottom), rgb, alpha = tile
                if right <= left or bottom <= top:
                    continue
                region = frame[top:bottom, left:right]
                if region.shape[:2] != rgb.shape[:2]:
                    continue
                blended = (region.astype(np.uint16) * (255 - alpha)
                           + rgb * alpha) // 255
                frame[top:bottom, left:right] = blended.astype(np.uint8)
        return frame

    def anything_on(self):
        with self._lock:
            return any(self._kinds.get(p.key, C.TEXT_NONE) != C.TEXT_NONE
                       for p in PLACES)

    # ------------------------------------------------------------- speaking --
    def describe(self):
        """What is on top of the picture, in words. Never empty."""
        with self._lock:
            parts = []
            for spot in PLACES:
                kind = self._kinds.get(spot.key, C.TEXT_NONE)
                if kind == C.TEXT_NONE:
                    continue
                said = self._text.get(spot.key)
                if said is None:
                    said = self._wanted(spot.key)
                if not said:
                    parts.append("%s, %s, nothing to show yet"
                                 % (spot.label, C.TEXT_LABELS.get(kind, kind)))
                else:
                    parts.append("%s %s reading %s"
                                 % (spot.describe_where(), spot.label.lower(),
                                    said))
        if not parts:
            return "nothing on top of it"
        return ", and ".join(parts) if len(parts) == 2 else ". ".join(parts)
