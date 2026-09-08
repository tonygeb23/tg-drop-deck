"""Knowing what the camera can see, and not going on about it.

The risky half of this feature is not the detector, it is the speech. A face
wobbles, so a detector that reports what it sees talks over a screen reader for
three hours. Most of what is here drives the Framer with made up readings,
because that is the only way to test "it did NOT say anything" properly.

There is a live camera section at the end. It is skipped when no camera is
free, and says so, rather than failing on a machine that has none or on one
where OBS has it.

    python tests/test_framing.py
"""

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-framing-test-")

from dropdeck import constants as C
from dropdeck import framing
from dropdeck.framing import Framer, Reading, _band

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def framer(level=framing.FRAMING_PROBLEMS):
    """A Framer whose readings are handed to it rather than detected."""
    said = []
    clock = FakeClock()
    f = Framer(level=level, on_say=said.append, clock=clock)
    f.checks = 1                      # pretend it has looked at something
    pending = {"reading": Reading()}

    def measure(_rgb):
        return pending["reading"]

    f.measure = measure

    def feed(reading, gap=C.FACE_SAY_FLOOR + 1):
        clock.advance(gap)
        pending["reading"] = reading
        return f.look(None)

    return f, said, feed, clock


def good():
    return Reading(True, "centred", "centred", "a good distance", "well lit",
                   0.5, 0.5, 0.15, 120.0, 0.95)


def gone():
    return Reading(False, light="well lit", luminance=120.0)


# ---------------------------------------------------------------------------
print("The model, and what happens without it")
# ---------------------------------------------------------------------------

check("the model ships with the app", os.path.isfile(framing.model_path()),
      framing.model_path())
check("so framing is available", framing.available(),
      framing.why_unavailable())
check("and there is no reason to report", framing.why_unavailable() == "")
check("the model is the one the README documents",
      C.FACE_MODEL_FILE in framing.model_path())


# ---------------------------------------------------------------------------
print("\nWhat a reading says")
# ---------------------------------------------------------------------------

check("a good shot reads as centred",
      good().sentence() == "Centred, a good distance, well lit",
      good().sentence())
check("and is nothing to report", good().problem() == "" and good().good)
check("no face says so", gone().sentence() == "No face in shot",
      gone().sentence())
check("and that IS worth reporting", gone().problem() == "No face in shot")

off_left = Reading(True, "left of shot", "centred", "a good distance",
                   "well lit")
check("being off to one side is said plainly",
      "left of shot" in off_left.sentence().lower(), off_left.sentence())
check("and it is a problem", off_left.problem() == "Left of shot")
check("but the word centred is not also said",
      off_left.sentence().count("centred") == 0, off_left.sentence())

dark = Reading(True, "centred", "centred", "a good distance", "dark")
check("a dark picture is reported", dark.problem() == "The picture is dark")
check("no face AND dark says both",
      Reading(False, light="dark").sentence()
      == "No face in shot, and the picture is dark")

both_off = Reading(True, "right of shot", "low in shot", "very close",
                   "well lit")
check("two things off are both said",
      "right of shot" in both_off.sentence().lower()
      and "low in shot" in both_off.sentence().lower(), both_off.sentence())


# ---------------------------------------------------------------------------
print("\nHysteresis, or the answer flips several times a second")
# ---------------------------------------------------------------------------

check("plainly left is left",
      _band(0.1, 0.35, 0.65, "left", "centred", "right") == "left")
check("plainly centred is centred",
      _band(0.5, 0.35, 0.65, "left", "centred", "right") == "centred")
check("plainly right is right",
      _band(0.9, 0.35, 0.65, "left", "centred", "right") == "right")

edge = 0.355
check("a value just inside the band reads as centred from nothing",
      _band(edge, 0.35, 0.65, "left", "centred", "right") == "centred")
check("and STAYS left when it was left, because it has not travelled far",
      _band(edge, 0.35, 0.65, "left", "centred", "right",
            previous="left", margin=0.04) == "left")
check("it takes a real move to come back to centred",
      _band(0.42, 0.35, 0.65, "left", "centred", "right",
            previous="left", margin=0.04) == "centred")

wobble = [0.348, 0.352, 0.349, 0.351, 0.353, 0.347]
plain = []
sticky = []
last = ""
for value in wobble:
    plain.append(_band(value, 0.35, 0.65, "left", "centred", "right"))
    last = _band(value, 0.35, 0.65, "left", "centred", "right",
                 previous=last, margin=0.04)
    sticky.append(last)
check("a wobble on the boundary flips the plain answer",
      len(set(plain)) > 1, plain)
check("and hysteresis holds it still", len(set(sticky)) == 1, sticky)


# ---------------------------------------------------------------------------
print("\nIt says changes, not states")
# ---------------------------------------------------------------------------

f, said, feed, clock = framer(framing.FRAMING_EVERYTHING)
feed(good())
check("the first reading is announced", len(said) == 1, said)
for _ in range(20):
    feed(good())
check("the same reading twenty more times says nothing else",
      len(said) == 1, said)
feed(Reading(True, "left of shot", "centred", "a good distance", "well lit"))
check("a change is announced", len(said) == 2, said)
check("and it is the new reading", "left of shot" in said[-1].lower(),
      said[-1])


# ---------------------------------------------------------------------------
print("\nThe floor between announcements")
# ---------------------------------------------------------------------------

f, said, feed, clock = framer(framing.FRAMING_EVERYTHING)
feed(good())
before = len(said)
feed(Reading(True, "left of shot", "centred", "a good distance", "well lit"),
     gap=0.5)
check("a change too soon after the last one is held back",
      len(said) == before, said)
feed(Reading(True, "left of shot", "centred", "a good distance", "well lit"),
     gap=C.FACE_SAY_FLOOR + 1)
check("and is said once the floor has passed, not lost",
      len(said) == before + 1 and "left of shot" in said[-1].lower(), said)

f, said, feed, clock = framer(framing.FRAMING_EVERYTHING)
feed(good())
for i in range(30):
    feed(Reading(True, "left of shot" if i % 2 else "right of shot",
                 "centred", "a good distance", "well lit"), gap=0.2)
check("thirty changes in six seconds do not make thirty announcements",
      len(said) <= 3, len(said))


# ---------------------------------------------------------------------------
print("\nThe three levels")
# ---------------------------------------------------------------------------

f, said, feed, clock = framer(framing.FRAMING_OFF)
for reading in (good(), gone(), good(), Reading(True, "left of shot")):
    feed(reading)
check("off says nothing at all", said == [], said)
check("but it is still watching, so the answer is ready",
      f.reading.horizontal == "left of shot", f.reading.horizontal)

f, said, feed, clock = framer(framing.FRAMING_PROBLEMS)
feed(good())
check("problems only is silent about a good shot", said == [], said)
feed(gone())
check("and speaks when you leave shot", said == ["No face in shot"], said)
feed(good())
check("and once when you come back", said[-1] == "Back in shot", said)
before = len(said)
for _ in range(10):
    feed(good())
check("then goes quiet again", len(said) == before, said)

f, said, feed, clock = framer(framing.FRAMING_EVERYTHING)
feed(good())
check("everything announces a good shot too", len(said) == 1, said)

f, said, feed, clock = framer(framing.FRAMING_PROBLEMS)
feed(Reading(True, "centred", "centred", "a good distance", "dark"))
check("a dark picture is a problem worth speaking",
      said == ["The picture is dark"], said)


# ---------------------------------------------------------------------------
print("\nAsking on demand, which is the key people will actually use")
# ---------------------------------------------------------------------------

f, said, feed, clock = framer(framing.FRAMING_OFF)
feed(Reading(True, "right of shot", "centred", "very close", "well lit"))
answer = f.describe().lower()
check("a silenced framer still answers when asked",
      "right of shot" in answer and "very close" in answer, answer)
check("and asking does not announce anything", said == [], said)

fresh = Framer(level=framing.FRAMING_PROBLEMS)
check("before it has looked, it says so rather than guessing",
      "not been looked at" in fresh.describe(), fresh.describe())

broken = Framer(level=framing.FRAMING_PROBLEMS)
broken.error = "the face detection model is missing"
check("and a broken detector reports itself when asked",
      broken.describe() == "the face detection model is missing")

f.reset()
check("resetting forgets the reading", not f.reading.found)


# ---------------------------------------------------------------------------
print("\nIt never raises, whatever it is handed")
# ---------------------------------------------------------------------------

real = Framer(level=framing.FRAMING_EVERYTHING)
for label, frame in [
        ("nothing", None),
        ("an empty array", np.zeros((0, 0, 3), dtype=np.uint8)),
        ("one pixel", np.zeros((1, 1, 3), dtype=np.uint8)),
        ("pure black", np.zeros((180, 320, 3), dtype=np.uint8)),
        ("pure white", np.full((180, 320, 3), 255, dtype=np.uint8)),
        ("noise", np.random.randint(0, 255, (180, 320, 3), dtype=np.uint8)),
        ("a tall thin frame", np.zeros((400, 40, 3), dtype=np.uint8)),
        ("a 4 by 3 camera", np.zeros((480, 640, 3), dtype=np.uint8))]:
    try:
        reading = real.measure(frame)
        check("%s gives a reading rather than raising" % label,
              isinstance(reading, Reading))
    except Exception as exc:
        check("%s gives a reading rather than raising" % label, False, exc)

black = real.measure(np.zeros((180, 320, 3), dtype=np.uint8))
check("black really is called dark", black.light == "dark", black.light)
check("and no face is found in it", not black.found)
white = real.measure(np.full((180, 320, 3), 255, dtype=np.uint8))
check("white is not called dark", white.light == "well lit", white.light)


# ---------------------------------------------------------------------------
print("\nThe thresholds, which were measured and not chosen")
# ---------------------------------------------------------------------------

check("a face at ordinary desk distance is NOT far away",
      C.FACE_FAR_BELOW < 0.12 < C.FACE_CLOSE_ABOVE,
      "%s < 0.12 < %s" % (C.FACE_FAR_BELOW, C.FACE_CLOSE_ABOVE))
check("which was the bug in the first draft of these numbers",
      C.FACE_FAR_BELOW <= 0.07)
check("the centred band is wide, because centred means nobody need act",
      C.FACE_RIGHT_EDGE - C.FACE_LEFT_EDGE >= 0.25)
check("a real sitting position reads as centred",
      C.FACE_LEFT_EDGE < 0.545 < C.FACE_RIGHT_EDGE)
check("and a real sitting height does too",
      C.FACE_TOP_EDGE < 0.465 < C.FACE_BOTTOM_EDGE)
check("a normally lit room is not called dark", C.FACE_DARK_BELOW < 119)
check("hysteresis is smaller than the band it guards",
      C.FACE_HYSTERESIS < (C.FACE_RIGHT_EDGE - C.FACE_LEFT_EDGE) / 2)
check("the floor between announcements is seconds, not milliseconds",
      C.FACE_SAY_FLOOR >= 3.0)
check("and looking happens a few times a second, not every frame",
      0.2 <= C.FACE_CHECK_SECONDS <= 1.0)


# ---------------------------------------------------------------------------
print("\nA real camera, if one is free")
# ---------------------------------------------------------------------------

from dropdeck import camera as cameras

devices = [d for d in cameras.cameras() if "Virtual" not in d]
if not devices:
    print("  skipped: no camera on this machine")
else:
    cam = cameras.CameraSource(devices[0], 1280, 720, 30)
    try:
        cam.start()
        if not cam.wait_ready(6):
            print("  skipped: %s" % (cam.error or "the camera gave no frames"))
        else:
            watcher = Framer(level=framing.FRAMING_EVERYTHING)
            import time as _time
            readings = []
            deadline = _time.time() + 5
            while _time.time() < deadline:
                if watcher.due():
                    readings.append(watcher.look(cam.latest()))
                _time.sleep(0.05)
            check("it looks at the camera several times", len(readings) >= 5,
                  len(readings))
            check("every look gives a reading",
                  all(isinstance(r, Reading) for r in readings))
            check("the picture is not reported as dark in a lit room",
                  readings[-1].light == "well lit",
                  "%.0f" % readings[-1].luminance)
            found = [r for r in readings if r.found]
            if found:
                # NOT "found in every look". Whether a face is in shot depends
                # on whether a person is sitting in front of the camera and
                # staying there, which is not something a test gets to
                # require: this failed once in a batch run and passed on its
                # own, purely because somebody moved. What can be asserted is
                # that when a face IS found the answer is sane.
                check("a face that is found is found with real confidence",
                      all(r.confidence >= C.FACE_CONFIDENCE for r in found),
                      min(r.confidence for r in found))
                check("and lands inside the frame",
                      all(0.0 <= r.centre_x <= 1.0 and 0.0 <= r.centre_y <= 1.0
                          for r in found))
                check("and the reading is a sentence, not numbers",
                      " " in found[-1].sentence(), found[-1].sentence())
                print("       found in %d of %d looks"
                      % (len(found), len(readings)))
                print("       reading: %s" % found[-1].sentence())
                print("       cx %.3f  cy %.3f  size %.3f  lum %.0f"
                      % (found[-1].centre_x, found[-1].centre_y,
                         found[-1].size, found[-1].luminance))
            else:
                print("  (nobody in front of the camera, so no face checks)")
    finally:
        cam.close()


print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
