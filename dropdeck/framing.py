"""Telling a presenter who cannot see the screen what the camera can see.

This is the part of camera streaming worth building. OBS answers "am I in
shot?" with a preview window, which is not an answer, it is the question
restated. A blind presenter going live has no way to know whether they are
centred, lit, or whether they wandered out of frame twenty minutes ago and have
been broadcasting an empty chair since.

So the app says it.

**Not repetitively, which is the whole design.** A face wobbles. A detector
that reports what it sees would say "centred, left, centred, left" for three
hours, over the top of a screen reader, on air. Three things stop that and all
three are needed:

1. **Changes are spoken, never states.** Nothing is said while the reading is
   what it already was. This removes almost all of it on its own.
2. **Hysteresis on every threshold.** A face sitting on a boundary has to cross
   a wider band to change the answer than it did to set it. Without this, one
   pixel of wobble flips the answer back and forth for ever.
3. **A floor between announcements.** Several seconds minimum, counted from
   when something was last SAID rather than from when it changed.

**On demand is the primary interface, and the announcements are the backstop.**
Somebody setting a shot up wants to ask over and over for ten seconds and then
never again, which is a key, not a running commentary. `describe()` always
answers, at every level, including when the detector is switched off.

The default level is PROBLEMS: quiet while the shot is good, speaks when you
leave it. A show is three hours and what you need to hear about is the twenty
seconds that went wrong.

The detector is YuNet, through OpenCV. It runs on a small greyscale copy two or
three times a second, not on every frame: measured 7 September 2026 on a real
camera, a face found in 36 of 36 checks at 3.0 ms on average and 12.6 ms at
worst. **OpenCV 5.0 has removed `CascadeClassifier`**, so there is no Haar
fallback; without the model the framing simply turns itself off and says so,
and streaming is unaffected.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import numpy as np

from . import constants as C

try:
    import cv2
except Exception:      # pragma: no cover - OpenCV missing is a real state
    cv2 = None


#: How much of the framing is spoken. Not the app's speech levels: this is one
#: setting about one thing, and it defaults to the quiet useful middle.
FRAMING_OFF = "off"
FRAMING_PROBLEMS = "problems"
FRAMING_EVERYTHING = "everything"
FRAMING_LEVELS = (FRAMING_OFF, FRAMING_PROBLEMS, FRAMING_EVERYTHING)

FRAMING_LEVEL_LABELS = {
    FRAMING_OFF: "Do not tell me about the shot",
    FRAMING_PROBLEMS: "Tell me when something is wrong",
    FRAMING_EVERYTHING: "Tell me about every change",
}


def model_path():
    """Where the detector's model lives, frozen or from source."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "models", C.FACE_MODEL_FILE)


def available():
    """Whether framing can work at all here."""
    return cv2 is not None and hasattr(cv2, "FaceDetectorYN") \
        and os.path.isfile(model_path())


def why_unavailable():
    """The reason, for saying out loud. Empty when it is available."""
    if cv2 is None:
        return "this copy cannot look at the picture"
    if not hasattr(cv2, "FaceDetectorYN"):
        return "this copy has no face detector"
    if not os.path.isfile(model_path()):
        return "the face detection model is missing"
    return ""


# ---------------------------------------------------------------------------
# One look at the picture
# ---------------------------------------------------------------------------

class Reading:
    """What the camera can see, in words rather than numbers."""

    __slots__ = ("found", "horizontal", "vertical", "distance", "light",
                 "centre_x", "centre_y", "size", "luminance", "confidence")

    def __init__(self, found=False, horizontal="", vertical="", distance="",
                 light="", centre_x=0.0, centre_y=0.0, size=0.0,
                 luminance=0.0, confidence=0.0):
        self.found = found
        self.horizontal = horizontal
        self.vertical = vertical
        self.distance = distance
        self.light = light
        self.centre_x = centre_x
        self.centre_y = centre_y
        self.size = size
        self.luminance = luminance
        self.confidence = confidence

    @property
    def key(self):
        """What has to change before anything is worth saying again."""
        return (self.found, self.horizontal, self.vertical, self.distance,
                self.light)

    @property
    def good(self):
        """A shot nobody needs to be told about."""
        return (self.found and self.horizontal == "centred"
                and self.vertical == "centred" and self.distance != "far away"
                and self.light != "dark")

    def sentence(self):
        """The whole reading, for the key that answers on demand."""
        if not self.found:
            if self.light == "dark":
                return "No face in shot, and the picture is dark"
            return "No face in shot"
        parts = []
        if self.horizontal == "centred" and self.vertical == "centred":
            parts.append("centred")
        else:
            if self.horizontal != "centred":
                parts.append(self.horizontal)
            if self.vertical != "centred":
                parts.append(self.vertical)
        parts.append(self.distance)
        parts.append(self.light)
        return ", ".join(p for p in parts if p).capitalize()

    def problem(self):
        """The one thing worth interrupting for, or empty."""
        if not self.found:
            return "No face in shot"
        if self.light == "dark":
            return "The picture is dark"
        if self.horizontal != "centred":
            return self.horizontal.capitalize()
        if self.vertical != "centred":
            return self.vertical.capitalize()
        if self.distance == "far away":
            return "Far away from the camera"
        return ""


def _band(value, low, high, below, middle, above, previous="", margin=0.0):
    """One reading with hysteresis, so a wobble does not flip the answer.

    Coming OUT of a state needs `margin` more than going in did. Without it a
    face resting on a boundary changes the answer several times a second, and
    the announcement floor then hides real changes behind fake ones.
    """
    lo, hi = low, high
    if previous == below:
        lo = low + margin
    elif previous == above:
        hi = high - margin
    elif previous == middle:
        lo, hi = low - margin, high + margin
    if value < lo:
        return below
    if value > hi:
        return above
    return middle


class Framer:
    """Looks at frames and says what changed, without becoming a commentary."""

    def __init__(self, level=FRAMING_PROBLEMS, on_say=None, clock=None):
        self.level = level if level in FRAMING_LEVELS else FRAMING_PROBLEMS
        self.on_say = on_say or (lambda text: None)
        self._clock = clock or time.monotonic
        self._detector = None
        self._input = None
        self._lock = threading.Lock()
        self.error = ""
        self.checks = 0
        self.reading = Reading()
        self._said_key = None
        self._said_at = 0.0
        self._last_look = 0.0

    # ------------------------------------------------------------ detector --
    def _ensure(self):
        if self._detector is not None or self.error:
            return
        reason = why_unavailable()
        if reason:
            self.error = reason
            return
        try:
            self._detector = cv2.FaceDetectorYN.create(
                model_path(), "", (C.FACE_INPUT_WIDTH, C.FACE_INPUT_HEIGHT),
                score_threshold=C.FACE_CONFIDENCE)
            self._input = (C.FACE_INPUT_WIDTH, C.FACE_INPUT_HEIGHT)
        except Exception as exc:
            self.error = "the face detector would not start: %s" % exc

    # ---------------------------------------------------------- one look --
    def due(self):
        """Whether it is time to look again. Cheap, so it can be asked often."""
        return (self._clock() - self._last_look) >= C.FACE_CHECK_SECONDS

    def look(self, rgb):
        """Analyse one frame and speak if anything changed. Never raises."""
        self._last_look = self._clock()
        reading = self.measure(rgb)
        with self._lock:
            self.reading = reading
        self._maybe_say(reading)
        return reading

    def measure(self, rgb):
        """One reading, with no speech and no state. Safe to call anywhere."""
        self._ensure()
        if rgb is None:
            return Reading()
        try:
            luminance = float(rgb[::8, ::8].mean())
        except Exception:
            luminance = 0.0
        light = "dark" if luminance < C.FACE_DARK_BELOW else "well lit"
        if self._detector is None:
            return Reading(light=light, luminance=luminance)

        try:
            height, width = rgb.shape[:2]
            scale = C.FACE_INPUT_WIDTH / float(width or 1)
            small_h = max(2, int(round(height * scale)))
            small = cv2.resize(rgb, (C.FACE_INPUT_WIDTH, small_h))
            # The detector has to be told the shape it is being given, and a
            # 4:3 camera is not the shape a 16:9 one is.
            if self._input != (C.FACE_INPUT_WIDTH, small_h):
                self._detector.setInputSize((C.FACE_INPUT_WIDTH, small_h))
                self._input = (C.FACE_INPUT_WIDTH, small_h)
            bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
            _count, faces = self._detector.detect(bgr)
            self.checks += 1
        except Exception:
            # A detector that throws must never take the show down. No reading
            # is a fine answer; a crashed stream is not.
            return Reading(light=light, luminance=luminance)

        if faces is None or not len(faces):
            return Reading(light=light, luminance=luminance)

        # The biggest face, which is the presenter. Anyone in the background
        # is smaller and is not who this is for.
        face = max(faces, key=lambda f: float(f[2]) * float(f[3]))
        x, y, w, h = (float(face[0]), float(face[1]),
                      float(face[2]), float(face[3]))
        confidence = float(face[-1])
        centre_x = (x + w / 2.0) / float(C.FACE_INPUT_WIDTH)
        centre_y = (y + h / 2.0) / float(small_h)
        size = w / float(C.FACE_INPUT_WIDTH)

        previous = self.reading
        horizontal = _band(
            centre_x, C.FACE_LEFT_EDGE, C.FACE_RIGHT_EDGE,
            "left of shot", "centred", "right of shot",
            previous.horizontal, C.FACE_HYSTERESIS)
        vertical = _band(
            centre_y, C.FACE_TOP_EDGE, C.FACE_BOTTOM_EDGE,
            "high in shot", "centred", "low in shot",
            previous.vertical, C.FACE_HYSTERESIS)
        distance = _band(
            size, C.FACE_FAR_BELOW, C.FACE_CLOSE_ABOVE,
            "far away", "a good distance", "very close",
            previous.distance, C.FACE_SIZE_HYSTERESIS)
        return Reading(True, horizontal, vertical, distance, light,
                       centre_x, centre_y, size, luminance, confidence)

    # -------------------------------------------------------------- speech --
    def _maybe_say(self, reading):
        if self.level == FRAMING_OFF:
            self._said_key = reading.key
            return
        if reading.key == self._said_key:
            return
        now = self._clock()
        first = self._said_key is None
        if not first and (now - self._said_at) < C.FACE_SAY_FLOOR:
            # Too soon. The key is deliberately NOT recorded, so the change is
            # still pending and gets said once the floor has passed rather
            # than being lost.
            return

        text = self._words(reading, first)
        self._said_key = reading.key
        if not text:
            return
        self._said_at = now
        try:
            self.on_say(text)
        except Exception:
            pass

    def _words(self, reading, first):
        """What to say about this reading, or nothing."""
        if self.level == FRAMING_EVERYTHING:
            return reading.sentence()
        # Problems only: speak a fault, and speak recovery ONCE, because
        # "you are back in shot" is the other half of "you have gone".
        problem = reading.problem()
        if problem:
            return problem
        if first:
            return ""
        return "Back in shot" if reading.found else ""

    # ------------------------------------------------------------ on demand --
    def describe(self):
        """Always answers, at every level, including off.

        This is the key a presenter actually uses, and a switch that silences
        the announcements must not silence the answer to a direct question.
        """
        if self.error:
            return self.error
        with self._lock:
            reading = self.reading
        if not self.checks:
            return "The camera has not been looked at yet"
        return reading.sentence()

    def reset(self):
        """Forget what was said, so a new shot starts clean."""
        with self._lock:
            self.reading = Reading()
        self._said_key = None
        self._said_at = 0.0
