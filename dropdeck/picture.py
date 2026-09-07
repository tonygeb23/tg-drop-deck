"""What goes on the screen, for a show that is mostly sound.

YouTube refuses an ingest with no video track. That is the only reason this
file exists: a radio show has no picture and still has to send one. So the
question is not "what video does the presenter want", it is "what is the least
this can be while still being worth looking at", and the answer is a card with
the station name and what is playing on it.

Three kinds of picture, and a camera is only one of them:

    Card      drawn here, from the station name and the current title.
    Image     the user's own artwork, scaled and letterboxed.
    Camera    a real camera. See `camera.py`.

Every source answers the same question: `frame(width, height)` gives back an
RGB array of exactly that size, and never raises. A source that cannot produce
a picture returns the last one that worked, or black. **A picture that fails
must not take the show off the air**, which is the same rule the microphone and
the sound cards already follow.

Nothing here talks to wx. The card is drawn with numpy so it can be rendered
and checked in a test with no display attached, which is how `tests/test_video.py`
proves the title really reaches the screen.
"""
from __future__ import annotations

import os
import threading
import time

import numpy as np

from . import constants as C

try:
    import av
except Exception:      # pragma: no cover - PyAV missing is a real state
    av = None


# ---------------------------------------------------------------------------
# Text, without a font file
# ---------------------------------------------------------------------------

#: A five by seven bitmap font, enough for a station name and a song title.
#: Drawn here rather than loaded because a font file is one more thing to
#: bundle, one more licence to honour, and one more thing to go missing. The
#: card is not typography, it is a legible caption.
_GLYPHS = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ",": ("00000", "00000", "00000", "00000", "01100", "01100", "01000"),
    "'": ("01100", "01100", "01000", "00000", "00000", "00000", "00000"),
    "!": ("00100", "00100", "00100", "00100", "00100", "00000", "00100"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "&": ("01100", "10010", "10100", "01000", "10101", "10010", "01101"),
    "#": ("01010", "01010", "11111", "01010", "11111", "01010", "01010"),
}

GLYPH_W = 5
GLYPH_H = 7
_UNKNOWN = ("11111", "10001", "10001", "10001", "10001", "10001", "11111")


def text_width(text, scale):
    """How wide this string will draw, in pixels, including the gaps."""
    if not text:
        return 0
    return (len(text) * (GLYPH_W + 1) - 1) * scale


def draw_text(canvas, text, x, y, scale, colour):
    """Blit a string onto an RGB array. Clipped, never raising."""
    height, width = canvas.shape[:2]
    colour = np.asarray(colour, dtype=np.uint8)
    cursor = x
    for char in str(text).upper():
        rows = _GLYPHS.get(char)
        if rows is None:
            rows = _UNKNOWN if not char.isspace() else _GLYPHS[" "]
        for row, bits in enumerate(rows):
            top = y + row * scale
            if top + scale <= 0 or top >= height:
                continue
            for col, bit in enumerate(bits):
                if bit != "1":
                    continue
                left = cursor + col * scale
                if left + scale <= 0 or left >= width:
                    continue
                canvas[max(0, top):top + scale,
                       max(0, left):left + scale] = colour
        cursor += (GLYPH_W + 1) * scale
    return cursor


def fit_scale(text, room, maximum, minimum=1):
    """The biggest scale this text fits in, down to `minimum`."""
    for scale in range(maximum, minimum - 1, -1):
        if text_width(text, scale) <= room:
            return scale
    return minimum


def shorten(text, room, scale):
    """Trim a string to what fits, with a full stop rather than a hard cut."""
    if text_width(text, scale) <= room:
        return text
    out = str(text)
    while out and text_width(out + "...", scale) > room:
        out = out[:-1]
    return (out + "...") if out else ""


# ---------------------------------------------------------------------------
# The sources
# ---------------------------------------------------------------------------

class PictureSource:
    """Something that can answer with a picture. Never raises."""

    kind = ""

    def frame(self, width, height):
        raise NotImplementedError

    def describe(self):
        return ""

    def start(self):
        return self

    def close(self):
        pass


class CardSource(PictureSource):
    """The station name, and what is playing, on a plain background.

    Redrawn only when something changes. A card is the same picture thirty
    times a second, and drawing it thirty times a second would be thirty times
    the work for no difference at all; the encoder is perfectly happy to be
    handed the same array again and squeezes it to almost nothing.
    """

    kind = C.PICTURE_CARD

    def __init__(self, name="", title="", background=None, foreground=None,
                 accent=None, clock=False):
        self.name = name or "TG Drop Deck"
        self._title = title or ""
        self.background = tuple(background or C.CARD_BACKGROUND)
        self.foreground = tuple(foreground or C.CARD_FOREGROUND)
        self.accent = tuple(accent or C.CARD_ACCENT)
        self.clock = bool(clock)
        self._lock = threading.Lock()
        self._cache = None
        self._cache_key = None
        self.redraws = 0

    # ------------------------------------------------------------ the title --
    @property
    def title(self):
        with self._lock:
            return self._title

    def set_title(self, title):
        """What is playing. Called from wherever the title changes."""
        with self._lock:
            self._title = title or ""

    def set_name(self, name):
        with self._lock:
            self.name = name or "TG Drop Deck"

    # ----------------------------------------------------------- the picture --
    def frame(self, width, height):
        minute = int(time.time() // 60) if self.clock else 0
        with self._lock:
            key = (width, height, self.name, self._title, minute)
            if key == self._cache_key and self._cache is not None:
                return self._cache
            canvas = self._draw(width, height, self.name, self._title)
            self._cache = canvas
            self._cache_key = key
            self.redraws += 1
            return canvas

    def _draw(self, width, height, name, title):
        canvas = np.empty((height, width, 3), dtype=np.uint8)
        canvas[:, :] = np.asarray(self.background, dtype=np.uint8)

        margin = max(8, width // 16)
        room = width - margin * 2

        # The station name, as big as it will go.
        name_scale = fit_scale(name, room, max(1, height // 90))
        name_text = shorten(name, room, name_scale)
        name_y = height // 2 - GLYPH_H * name_scale
        draw_text(canvas, name_text,
                  (width - text_width(name_text, name_scale)) // 2,
                  name_y, name_scale, self.foreground)

        # A rule under it, which is the whole of the decoration.
        rule_y = name_y + GLYPH_H * name_scale + max(4, height // 60)
        rule_h = max(2, height // 240)
        canvas[rule_y:rule_y + rule_h,
               margin:width - margin] = np.asarray(self.accent, dtype=np.uint8)

        # And what is playing, under that.
        if title:
            title_scale = fit_scale(title, room, max(1, name_scale - 1))
            title_text = shorten(title, room, title_scale)
            draw_text(canvas, title_text,
                      (width - text_width(title_text, title_scale)) // 2,
                      rule_y + rule_h + max(6, height // 40),
                      title_scale, self.accent)

        if self.clock:
            stamp = time.strftime("%H:%M")
            scale = max(1, height // 180)
            draw_text(canvas, stamp,
                      width - margin - text_width(stamp, scale),
                      margin, scale, self.accent)
        return canvas

    def describe(self):
        return "a card"


class ImageSource(PictureSource):
    """The user's own artwork, scaled once and kept.

    Read through PyAV, which is already here, so a PNG or a JPEG both work
    without another imaging library going into the build.
    """

    kind = C.PICTURE_IMAGE

    def __init__(self, path, background=None):
        self.path = path
        self.background = tuple(background or C.CARD_BACKGROUND)
        self.error = ""
        self._cache = None
        self._cache_size = None
        self._source = None

    def _load(self):
        if self._source is not None or self.error:
            return
        if not self.path or not os.path.isfile(self.path):
            self.error = "that picture file is not there"
            return
        if av is None:
            self.error = "this copy cannot read pictures"
            return
        try:
            with av.open(self.path) as container:
                for frame in container.decode(video=0):
                    self._source = frame.to_ndarray(format="rgb24")
                    break
        except Exception:
            self.error = "that file is not a picture this can read"

    def frame(self, width, height):
        if self._cache_size == (width, height) and self._cache is not None:
            return self._cache
        self._load()
        canvas = np.empty((height, width, 3), dtype=np.uint8)
        canvas[:, :] = np.asarray(self.background, dtype=np.uint8)
        if self._source is not None:
            canvas = _letterbox(self._source, canvas)
        self._cache = canvas
        self._cache_size = (width, height)
        return canvas

    def describe(self):
        if self.error:
            return "a picture that could not be read"
        return "a picture"


def _letterbox(source, canvas):
    """Fit `source` inside `canvas` without stretching it out of shape."""
    height, width = canvas.shape[:2]
    src_h, src_w = source.shape[:2]
    if not src_h or not src_w:
        return canvas
    scale = min(width / float(src_w), height / float(src_h))
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    # Nearest neighbour, by indexing. It is a still picture on a video stream
    # and this avoids another dependency for something nobody will see.
    rows = (np.arange(new_h) * (src_h / float(new_h))).astype(np.int32)
    cols = (np.arange(new_w) * (src_w / float(new_w))).astype(np.int32)
    scaled = source[np.clip(rows, 0, src_h - 1)][:, np.clip(cols, 0, src_w - 1)]
    top = (height - new_h) // 2
    left = (width - new_w) // 2
    canvas[top:top + new_h, left:left + new_w] = scaled
    return canvas


class FallbackSource(PictureSource):
    """One source, with another behind it when the first cannot answer.

    This is what makes a camera safe to use on a live show. A camera that is
    unplugged, or taken by another program halfway through, falls back to the
    card and the show carries on. Coming off air because a webcam was pulled
    out is the failure this exists to prevent.
    """

    def __init__(self, primary, backup, on_fallback=None):
        self.primary = primary
        self.backup = backup
        self.on_fallback = on_fallback or (lambda reason: None)
        self.fallen_back = False
        self.reason = ""
        self._tried_at = 0.0

    @property
    def kind(self):
        return self.primary.kind

    def start(self):
        try:
            self.primary.start()
        except Exception as exc:
            self._fall_back(str(exc))
        self.backup.start()
        return self

    def frame(self, width, height):
        """The primary if it can answer, otherwise the backup.

        It RETRIES. The first version gave up for good on the first failure,
        and its recovery branch sat inside `if not self.fallen_back` where it
        could never run. One glitched frame, or OBS holding the camera for a
        moment, meant the card for the rest of a three hour show even after
        the camera was fine again. Retrying costs one call every few seconds
        and gets the presenter their camera back.
        """
        now = time.monotonic()
        if self.fallen_back and (now - self._tried_at) >= C.PICTURE_RETRY_SECONDS:
            self._tried_at = now
            picture = self._ask(width, height)
            if picture is not None:
                self.fallen_back = False
                self.reason = ""
                try:
                    self.on_fallback("The camera is back")
                except Exception:
                    pass
                return picture
        elif not self.fallen_back:
            picture = self._ask(width, height)
            if picture is not None:
                return picture
            self._fall_back(getattr(self.primary, "error", "")
                            or "the picture stopped")
        return self.backup.frame(width, height)

    def _ask(self, width, height):
        try:
            return self.primary.frame(width, height)
        except Exception as exc:
            if not self.fallen_back:
                self.reason = str(exc)
            return None

    def _fall_back(self, reason):
        if self.fallen_back:
            return
        self.fallen_back = True
        self.reason = reason
        # Said once, not once a frame. A camera that has gone is going to keep
        # being gone thirty times a second.
        try:
            self.on_fallback(reason)
        except Exception:
            pass

    def describe(self):
        if self.fallen_back:
            return "%s, showing a card instead" % self.primary.describe()
        return self.primary.describe()

    def set_title(self, title):
        for source in (self.primary, self.backup):
            setter = getattr(source, "set_title", None)
            if setter is not None:
                setter(title)

    def close(self):
        for source in (self.primary, self.backup):
            try:
                source.close()
            except Exception:
                pass


def build(settings, on_fallback=None):
    """The picture source one station's settings ask for.

    A camera and a picture file both get the card behind them, because a
    camera that is unplugged or a file that has been moved must not be the end
    of a broadcast. The card alone needs no such thing: it cannot fail.
    """
    card = CardSource(name=settings.get("name") or settings.get("stream_name")
                      or "TG Drop Deck",
                      title=settings.get("title", ""),
                      clock=bool(settings.get("picture_clock", False)))
    kind = settings.get("picture", C.PICTURE_CARD)
    if kind == C.PICTURE_IMAGE:
        primary = ImageSource(settings.get("picture_file", ""))
    elif kind == C.PICTURE_CAMERA:
        # Imported here rather than at the top: picture.py is what camera.py
        # imports, and the other way round as well would be a cycle.
        from .camera import CameraSource
        primary = CameraSource(settings.get("camera", ""),
                               settings.get("video_width"),
                               settings.get("video_height"),
                               settings.get("video_fps"))
    else:
        return card
    return FallbackSource(primary, card, on_fallback)
