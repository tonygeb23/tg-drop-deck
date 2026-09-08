# The repository root is on the path already, put there by cross_check.py.
#
# The GEOMETRY and the WORDS are checked here. The drawing is not, and
# `fits` is deliberately not: the two renderers do not draw the same width,
# so agreeing with the other platform's number would mean being wrong about
# this machine's own picture. See docs/MAC-VIDEO-PLAN.md section 3a.
import time
from dropdeck import constants as C
from dropdeck import overlay as O

# The clock is pinned so both copies see the same minute.
time.strftime = lambda fmt, *a: "09:41" if fmt == C.OVERLAY_CLOCK_FORMAT else ""

out = []
for spot in O.PLACES:
    out.append("place|%s|%s|%s|%s" % (spot.key, spot.label, spot.align,
                                      spot.describe_where()))
    for (w, h) in ((1280, 720), (1920, 1080), (854, 480), (640, 360), (3840, 2160)):
        out.append("  rect|%s|%d|%d|%s|%d"
                   % (spot.key, w, h, spot.rect(w, h), spot.text_size(h)))
for key in ("top", "corner", "lower", "clock", "nowhere"):
    out.append("label|%s|%s" % (key, O.place_label(key)))

# describe(), which is what Command Shift V reads out.
CASES = [
    ("nothing", {}),
    ("station-only", {"text_top": "station", "name": "Blindside Radio"}),
    ("station-no-name", {"text_top": "station"}),
    ("two", {"text_top": "station", "name": "Tony's Tunes",
             "text_clock": "time"}),
    ("three", {"text_top": "station", "name": "Tony's Tunes",
               "text_clock": "time", "text_lower": "playing"}),
    ("all-four", {"text_top": "station", "name": "Tony's Tunes",
                  "text_corner": "words", "text_corner_words": "LIVE",
                  "text_lower": "playing", "text_clock": "time"}),
    ("playing-empty", {"text_lower": "playing"}),
    ("words-empty", {"text_corner": "words"}),
    ("file-missing", {"text_lower": "file", "text_lower_file": "/tmp/nope-xyz.txt"}),
    ("stream-name", {"text_top": "station", "stream_name": "Fallback FM"}),
    ("unknown-kind", {"text_top": "weather"}),
]
for name, settings in CASES:
    for title in ("", "Fleetwood Mac - Dreams"):
        ov = O.Overlay(settings)
        ov.set_title(title)
        out.append("describe|%s|%r|%s" % (name, title, ov.describe()))
        out.append("  anything|%s|%s" % (name, ov.anything_on()))
        for key in C.PLACES_ORDER:
            out.append("  kind|%s|%s|%s" % (name, key, ov.kind_of(key)))
print("\n".join(out))
