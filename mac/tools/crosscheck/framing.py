# The repository root is on the path already, put there by cross_check.py.
#
# The DETECTOR is not checked here and cannot be: Windows runs a YuNet model
# through OpenCV and the Mac uses the Vision framework, so the two will not
# find a face in exactly the same pixel. What must match is everything after
# the box: the bands that turn a position into a word, the hysteresis that
# stops it flapping, and every sentence said out loud.
from dropdeck import constants as C
from dropdeck import framing as F

out = []
for name in ("FRAMING_OFF", "FRAMING_PROBLEMS", "FRAMING_EVERYTHING"):
    out.append("level|%s|%s" % (name, getattr(F, name)))
for key, label in sorted(F.FRAMING_LEVEL_LABELS.items()):
    out.append("levellabel|%s|%s" % (key, label))

# The bands, over the whole range and across every previous state.
for previous in ("", "left of shot", "centred", "right of shot"):
    for i in range(0, 101):
        v = i / 100.0
        out.append("bandh|%s|%.2f|%s" % (previous, v, F._band(
            v, C.FACE_LEFT_EDGE, C.FACE_RIGHT_EDGE,
            "left of shot", "centred", "right of shot", previous,
            C.FACE_HYSTERESIS)))
for previous in ("", "high in shot", "centred", "low in shot"):
    for i in range(0, 101):
        v = i / 100.0
        out.append("bandv|%s|%.2f|%s" % (previous, v, F._band(
            v, C.FACE_TOP_EDGE, C.FACE_BOTTOM_EDGE,
            "high in shot", "centred", "low in shot", previous,
            C.FACE_HYSTERESIS)))
for previous in ("", "far away", "a good distance", "very close"):
    for i in range(0, 51):
        v = i / 100.0
        out.append("bands|%s|%.2f|%s" % (previous, v, F._band(
            v, C.FACE_FAR_BELOW, C.FACE_CLOSE_ABOVE,
            "far away", "a good distance", "very close", previous,
            C.FACE_SIZE_HYSTERESIS)))

# Every sentence a reading can produce.
for found in (False, True):
    for h in ("left of shot", "centred", "right of shot"):
        for v in ("high in shot", "centred", "low in shot"):
            for d in ("far away", "a good distance", "very close"):
                for light in ("dark", "well lit"):
                    r = F.Reading(found, h, v, d, light)
                    out.append("say|%s|%s|%s|%s|%s|%s|%s|%s"
                               % (found, h, v, d, light, r.sentence(),
                                  r.problem(), r.good))
                    out.append("  key|%s" % (r.key,))

# And the announcement rule, driven by a clock the test owns.
class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t

for level in F.FRAMING_LEVELS:
    clock = Clock()
    said = []
    framer = F.Framer(level=level, on_say=said.append, clock=clock)
    script = [
        (0.0, F.Reading(True, "centred", "centred", "a good distance", "well lit")),
        (1.0, F.Reading(True, "centred", "centred", "a good distance", "well lit")),
        (2.0, F.Reading(False, "", "", "", "well lit")),
        (3.0, F.Reading(False, "", "", "", "well lit")),
        (9.0, F.Reading(True, "left of shot", "centred", "a good distance", "well lit")),
        (10.0, F.Reading(True, "centred", "centred", "a good distance", "dark")),
        (20.0, F.Reading(True, "centred", "centred", "a good distance", "well lit")),
        (21.0, F.Reading(True, "centred", "centred", "far away", "well lit")),
        (40.0, F.Reading(True, "centred", "centred", "a good distance", "well lit")),
    ]
    for when, reading in script:
        clock.t = when
        framer._maybe_say(reading)
        framer.reading = reading
        out.append("flow|%s|%.1f|%s" % (level, when, list(said)))
    out.append("flowsaid|%s|%s" % (level, said))
print("\n".join(out))
