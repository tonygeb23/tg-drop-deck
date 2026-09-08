"""Noticing that the picture has died, and saying so.

**OBS has never had this.** People have asked for it on their forums for
years, it is a standard metric in professional broadcast infrastructure
because the arithmetic is trivial, and no desktop encoder speaks it. For a
presenter who cannot look at a preview it is the difference between a bad
minute and a bad show: a camera that unplugs, a screen that goes black when
the machine locks, a capture that freezes on one frame. All three look
perfectly fine from where you are sitting, and all three are obvious to
anybody watching.

The reason it is nearly free here is that the frame is already in our hands.
`_pump_video` has the RGB array a moment before it hands it to the encoder,
so this is two numpy reductions on a subsample of something already in cache.

## Why it is careful rather than eager

**A still card is legitimately frozen** and a dark card is legitimately dark,
so a naive check would announce a fault on the app's own default picture,
every time, for ever. Two things stop that: the caller says whether this
source is supposed to be moving, and nothing is said until a fault has lasted
`HEALTH_PATIENCE` seconds. A camera blinks. A dead camera does not come back.

The same anti-repetition rule the framing announcements already follow: say
changes, not states, and put a floor between them.
"""
from __future__ import annotations

import time

import numpy as np

from . import constants as C

#: What it can conclude.
OK = "ok"
BLACK = "black"
FROZEN = "frozen"


class Watcher:
    """Watches the frames going out, and says when they stop being a picture.

    One instance per broadcast. `look` is called with the frame that is about
    to be encoded and returns something to say, or "".
    """

    def __init__(self, on_say=None):
        self.on_say = on_say
        self.state = OK
        self.frames = 0
        self._last = None
        self._since = 0.0
        self._said_at = 0.0
        self._said = OK

    def reset(self):
        self.state = OK
        self._last = None
        self._since = 0.0
        self._said_at = 0.0
        self._said = OK

    def look(self, frame, moving=True, now=None):
        """One frame. Returns what to say about it, or "".

        `moving` is False for a card or a still image, which are supposed to
        be frozen: a still picture is only a fault when something was meant
        to be moving behind it.
        """
        if frame is None or getattr(frame, "size", 0) == 0:
            return ""
        now = time.monotonic() if now is None else now
        self.frames += 1
        # A subsample. One pixel in sixty four is plenty to tell a black
        # frame from a picture, and it keeps this off the profile entirely.
        small = frame[::8, ::8]
        brightness = float(small.mean())
        found = OK
        if brightness < C.HEALTH_BLACK_BELOW:
            found = BLACK
        elif moving and self._last is not None:
            if self._last.shape == small.shape:
                moved = float(np.abs(small.astype(np.int16)
                                     - self._last.astype(np.int16)).mean())
                if moved < C.HEALTH_FROZEN_BELOW:
                    found = FROZEN
        self._last = small.copy()

        if found != self.state:
            # A new state starts its clock. Nothing is said yet: this is
            # where a blink gets absorbed.
            self.state = found
            self._since = now
            return ""
        if found == OK:
            if self._said != OK and (now - self._since) >= C.HEALTH_PATIENCE:
                self._said = OK
                self._said_at = now
                return self._say(C.HEALTH_BACK)
            return ""
        if (now - self._since) < C.HEALTH_PATIENCE:
            return ""
        if self._said == found and (now - self._said_at) < C.HEALTH_REPEAT:
            return ""
        self._said = found
        self._said_at = now
        return self._say(C.HEALTH_BLACK_SAID if found == BLACK
                         else C.HEALTH_FROZEN_SAID)

    def _say(self, text):
        if self.on_say is not None:
            try:
                self.on_say(text)
            except Exception:
                pass
        return text

    def describe(self):
        """The current answer, for anybody who asks rather than waits."""
        if self.state == BLACK:
            return "the picture is black"
        if self.state == FROZEN:
            return "the picture has stopped moving"
        return "the picture looks fine"
