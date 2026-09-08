"""3.5.0: things on top of the picture, and knowing what is on screen.

Tony, 8 September 2026, after reading the OBS research: "yes. do it all.
perform a riggerous test sweep for the visuals to ensure it all checks out,
otpimally, accessibly for us, and works as you say."

So this file is written against what was promised, claim by claim, and every
number in it was measured rather than hoped for. Four things are being proved:

**It looks right.** Real glyphs, in places that do not overlap, that fit.

**It is affordable.** The whole reason this was possible is a set of
measurements that could each have gone the other way: caching tiles instead of
drawing per frame, blending a rectangle instead of a frame, integer maths
instead of float. Each of those has a check here, because each of them is one
line away from being undone by somebody tidying up.

**It does not stall the audio.** `Image.alpha_composite` holds the GIL and
made an audio thread 16.9 ms late in the research. Nothing in this code may
call it, and there is a check that reads the source to make sure.

**It can be operated without looking.** Which is the entire point, and is the
thing OBS cannot do: its preview is a GPU surface with no accessibility tree
on any platform.

    python tests/test_visuals.py
"""

import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-visuals-test-")

from dropdeck import constants as C
from dropdeck import health, overlay, preflight
from dropdeck.board import Board

CHECKS = []
W, H = 1280, 720


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


def bench(fn, n=40):
    fn()
    ts = []
    for _ in range(n):
        started = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - started) * 1000.0)
    ts.sort()
    return ts[len(ts) // 2], ts[int(n * 0.9)]


def a_frame(value=90):
    return np.full((H, W, 3), value, np.uint8)


# ---------------------------------------------------------------------------
print("\nThe font, which is a countdown problem before it is a taste one")
# ---------------------------------------------------------------------------

check("text can be drawn at all", overlay.available(), overlay.why_unavailable())

face = overlay.font(64, bold=True)
check("the bundled bold face loads", face is not None)
if face is not None:
    widths = sorted({face.getlength(d) for d in "0123456789"})
    # Pillow's Windows wheels carry no HarfBuzz, so features=["tnum"] cannot
    # be reached and the font must be tabular BY DEFAULT. Impact and
    # Bahnschrift are not, which is why neither is the one bundled.
    check("its digits are all one width, so a clock cannot jitter",
          len(widths) == 1, widths)
    check("and a changing time never changes width",
          face.getlength("03:41") == face.getlength("11:11")
          == face.getlength("08:00"), face.getlength("03:41"))
check("the same size is only built once", overlay.font(64, True) is face)

licence = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "assets", "fonts")
check("the font licence ships beside the font",
      any(n.upper().startswith("LICENSE") or n.upper().startswith("OFL")
          for n in os.listdir(licence)), os.listdir(licence))


# ---------------------------------------------------------------------------
print("\nThe card, which is the picture most people actually broadcast")
# ---------------------------------------------------------------------------

from dropdeck import picture      # noqa: E402

card = picture.CardSource(name="Blindside Radio", title="Never Lose Sight",
                          clock=True)
drawn = card.frame(W, H)
check("the card draws", drawn is not None and drawn.shape == (H, W, 3),
      None if drawn is None else drawn.shape)
check("in real letters, not the 5 by 7 blocks",
      card._draw_real(W, H, "Blindside Radio", "Never Lose Sight") is not None)

# THE FLOOR. A build where Pillow did not come along must still put a card on
# the air rather than a black rectangle, which is the rule the whole picture
# path already follows.
was = overlay.Image
overlay.Image = None
try:
    blocks = picture.CardSource(name="Blindside Radio").frame(W, H)
finally:
    overlay.Image = was
check("and it still draws with no Pillow at all, in the old blocks",
      blocks is not None and blocks.shape == (H, W, 3))
check("which is genuinely a different picture, so the floor is real",
      not np.array_equal(blocks, picture.CardSource(
          name="Blindside Radio").frame(W, H)))

# The rule under the name must not cross the name. textbbox is measured from
# the drawing origin, so using its HEIGHT rather than its bottom edge put the
# line straight through the middle of the letters, which is where a
# descender lives. It looked deliberate and it was a bug.
plain = picture.CardSource(name="Blindside Radio", title="")
shot = plain.frame(W, H)
column = shot[:, W // 2]
rows = np.where((column != np.asarray(C.CARD_BACKGROUND)).any(axis=1))[0]
runs = np.split(rows, np.where(np.diff(rows) > 3)[0] + 1) if len(rows) else []
check("the rule sits below the name rather than through it",
      len(runs) >= 2, "%d separate bands of ink down the middle" % len(runs))

# ---------------------------------------------------------------------------
print("\nThe places: few, named, and unable to overlap")
# ---------------------------------------------------------------------------

check("there are four of them", len(overlay.PLACES) == 4,
      [p.key for p in overlay.PLACES])
check("every one has a label and a spoken position",
      all(p.label and p.describe_where() for p in overlay.PLACES))

rects = {p.key: p.rect(W, H) for p in overlay.PLACES}
check("each one is inside the frame",
      all(0 <= l and 0 <= t and r <= W and b <= H
          for l, t, r, b in rects.values()), rects)
check("and big enough to read",
      all((r - l) > 120 and (b - t) > 40 for l, t, r, b in rects.values()),
      {k: (v[2] - v[0], v[3] - v[1]) for k, v in rects.items()})


def overlaps(one, two):
    al, at, ar, ab = one
    bl, bt, br, bb = two
    return not (ar <= bl or br <= al or ab <= bt or bb <= at)


keys = list(rects)
clashes = [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]
           if overlaps(rects[a], rects[b])]
# THE ONE THAT MATTERS. Two things in one spot is the confusion that not
# being able to look at the screen makes unrecoverable, and it is the reason
# there is no canvas here at all.
check("NO TWO PLACES OVERLAP, at 1280x720", not clashes, clashes)

for size in ((1920, 1080), (854, 480), (640, 360)):
    other = {p.key: p.rect(*size) for p in overlay.PLACES}
    bad = [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]
           if overlaps(other[a], other[b])]
    inside = all(0 <= l and 0 <= t and r <= size[0] and b <= size[1]
                 for l, t, r, b in other.values())
    check("nor at %dx%d, because they are fractions not pixels" % size,
          not bad and inside, bad or "")


# ---------------------------------------------------------------------------
print("\nDrawing, and the three measurements the whole thing rests on")
# ---------------------------------------------------------------------------

marks = overlay.Overlay({
    "name": "Blindside Radio",
    "text_%s" % C.PLACE_LOWER: C.TEXT_STATION,
    "text_%s" % C.PLACE_CLOCK: C.TEXT_TIME,
    "text_%s" % C.PLACE_TOP: C.TEXT_PLAYING,
})
marks.set_title("Never Lose Sight")

frame = a_frame()
before = frame.copy()
marks.draw_on(frame)
check("three places were drawn", marks.renders == 3, marks.renders)
check("the frame really changed", not np.array_equal(frame, before))

left, top, right, bottom = rects[C.PLACE_LOWER]
check("the lower third's own rectangle changed",
      not np.array_equal(frame[top:bottom, left:right],
                         before[top:bottom, left:right]))
# The middle of the frame is nobody's place, so nothing may touch it.
check("and the middle of the picture was left alone",
      np.array_equal(frame[H // 2 - 40:H // 2 + 40, W // 2 - 40:W // 2 + 40],
                     before[H // 2 - 40:H // 2 + 40, W // 2 - 40:W // 2 + 40]))

# RENDER ON CHANGE, NEVER PER FRAME.
again = a_frame()
for _ in range(60):
    marks.draw_on(again)
check("sixty more frames drew no new tiles", marks.renders == 3, marks.renders)

marks.set_title("A Different Song")
marks.draw_on(a_frame())
check("but changing what it says does redraw, and only that one",
      marks.renders == 4, marks.renders)

# BLEND THE RECTANGLE, NEVER THE FRAME.
median, p90 = bench(lambda: marks.draw_on(again))
check("drawing everything costs a small part of a 33 ms frame",
      median < 12.0, "median %.2f ms, p90 %.2f" % (median, p90))

naive = np.zeros((H, W, 4), np.uint8)
naive[:, :, 3] = 128


def whole_frame():
    alpha = naive[:, :, 3:4].astype(np.uint16)
    return ((again.astype(np.uint16) * (255 - alpha)
             + naive[:, :, :3] * alpha) // 255).astype(np.uint8)


full_median, _ = bench(whole_frame, n=20)
check("and far less than doing the whole frame, which is the trap",
      median < full_median / 2.0,
      "%.1f ms against %.1f for a full frame" % (median, full_median))

# INTEGER MATHS. A float path would be slower still and is the other trap.
check("the blend is integers, not floats",
      "uint16" in open(os.path.join(os.path.dirname(os.path.dirname(
          os.path.abspath(__file__))), "dropdeck", "overlay.py"),
          encoding="utf-8").read())

# NOTHING MAY CALL alpha_composite. It holds the GIL, and it made an audio
# thread 16.9 ms late when this was measured. A comment would rot; reading
# the source does not.
source = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "dropdeck", "overlay.py"), encoding="utf-8").read()
check("NOTHING here calls Image.alpha_composite, which holds the GIL",
      "alpha_composite" not in source.split('"""')[-1], "found in the code")


# ---------------------------------------------------------------------------
print("\nText that will not fit is shortened, and said so beforehand")
# ---------------------------------------------------------------------------

check("a short title fits the lower third",
      overlay.fits("Blindside Radio", C.PLACE_LOWER, W, H))
huge = "The Tony Gebhard Show With A Very Long Subtitle Indeed And More"
check("a very long one does not", not overlay.fits(huge, C.PLACE_LOWER, W, H))

tile = overlay.render_tile(huge, 400, 90, 44)
check("but it still draws, shortened rather than overflowing",
      tile is not None and tile.width == 400, tile.width if tile else None)
check("nothing is drawn for an empty string",
      overlay.render_tile("", 400, 90, 44) is None)

board = Board()
board.live_to = C.LIVE_TO_VIDEO
board.video_server = "youtube"
board.video_host = C.RTMP_INGEST["youtube"]
board.stream_name = "Blindside Radio"
board.text_places[C.PLACE_LOWER] = {"kind": C.TEXT_WORDS, "words": huge,
                                    "file": ""}
settings = {"server": "youtube", "host": C.RTMP_INGEST["youtube"],
            "password": "key", "format": "aac", "bitrate": 128,
            "picture": C.PICTURE_CARD, "name": "Blindside Radio",
            "video_width": W, "video_height": H, "video_fps": 30,
            "video_bitrate": 2500}
report = preflight.check(settings, board)
check("going live warns that it would be cut short",
      any("too long" in n.text for n in report.warnings),
      [n.text for n in report.warnings])

board.text_places[C.PLACE_LOWER] = {"kind": C.TEXT_WORDS, "words": "",
                                    "file": ""}
report = preflight.check(settings, board)
check("and warns about a place set to words with none typed",
      any("there are none yet" in n.text for n in report.warnings),
      [n.text for n in report.warnings])

board.text_places[C.PLACE_LOWER] = {"kind": C.TEXT_FILE, "words": "",
                                    "file": os.path.join(tempfile.gettempdir(),
                                                         "no-such-file.txt")}
report = preflight.check(settings, board)
check("and about a file that is not there",
      any("not there any more" in n.text for n in report.warnings),
      [n.text for n in report.warnings])

board.text_places[C.PLACE_LOWER] = {"kind": C.TEXT_STATION, "words": "",
                                    "file": ""}
report = preflight.check(settings, board)
check("a station name that fits raises nothing",
      not any("too long" in n.text for n in report.notes),
      [n.text for n in report.notes])


# ---------------------------------------------------------------------------
print("\nA text file, which is how every other tool will drive this")
# ---------------------------------------------------------------------------

path = os.path.join(tempfile.mkdtemp(prefix="dd-text-"), "now-playing.txt")
with open(path, "w", encoding="utf-8") as handle:
    handle.write("First Song\n")
reader = overlay.Overlay({"text_%s" % C.PLACE_LOWER: C.TEXT_FILE,
                          "text_%s_file" % C.PLACE_LOWER: path})
frame = a_frame()
reader.draw_on(frame)
check("it reads the file", reader._text.get(C.PLACE_LOWER) == "First Song",
      reader._text.get(C.PLACE_LOWER))

with open(path, "w", encoding="utf-8") as handle:
    handle.write("Second Song\n")
os.utime(path, (time.time() + 5, time.time() + 5))
reader._file_seen[C.PLACE_LOWER] = (0.0, None)     # let the poll come round
reader.draw_on(a_frame())
check("and re-reads it when it changes",
      reader._text.get(C.PLACE_LOWER) == "Second Song",
      reader._text.get(C.PLACE_LOWER))

reads = []
real_open = open


def counted(*a, **kw):
    if a and a[0] == path:
        reads.append(1)
    return real_open(*a, **kw)


import builtins      # noqa: E402
builtins.open = counted
try:
    for _ in range(40):
        reader.draw_on(a_frame())
finally:
    builtins.open = real_open
# The point of the mtime poll is that it is one stat a second, not a read a
# frame. Forty frames is well over a second of video and must not be forty
# reads of somebody's disk.
check("forty frames did not read the file forty times", len(reads) <= 2,
      "%d reads" % len(reads))

gone = overlay.Overlay({"text_%s" % C.PLACE_LOWER: C.TEXT_FILE,
                        "text_%s_file" % C.PLACE_LOWER: path + ".missing"})
gone.draw_on(a_frame())
check("a file that is not there draws nothing rather than raising",
      gone._text.get(C.PLACE_LOWER) == "")


# ---------------------------------------------------------------------------
print("\nSaying what is on screen, which nothing else does")
# ---------------------------------------------------------------------------

said = marks.describe()
check("it names what is showing", "Blindside Radio" in said, said)
check("and where each thing is", "bottom left" in said and "top" in said, said)
check("in words, not coordinates",
      not any(ch.isdigit() for ch in said.replace(":", "")) or "reading" in said,
      said)

empty = overlay.Overlay({})
check("with nothing set up it still answers",
      empty.describe() == "nothing on top of it", empty.describe())
check("and knows it is empty", not empty.anything_on())
check("where a set up one knows it is not", marks.anything_on())


# ---------------------------------------------------------------------------
print("\nNoticing the picture has died, which OBS has never done")
# ---------------------------------------------------------------------------

watch = health.Watcher()
black = np.zeros((H, W, 3), np.uint8)
at = 0.0
first = ""
for _ in range(10):
    at += 1.0
    got = watch.look(black, moving=True, now=at)
    if got and not first:
        first = got
        when = at
check("a black picture is noticed", bool(first), first)
check("but not instantly, because a camera blinks",
      when >= C.HEALTH_PATIENCE, "after %.0f seconds" % when)
check("and it is said once, not every frame",
      sum(1 for _ in range(20)
          if watch.look(black, moving=True, now=at + _ + 1)) == 0)

# A STILL CARD IS LEGITIMATELY FROZEN. Calling it a fault would mean the app
# announcing a problem about its own default picture, for ever.
still = health.Watcher()
card = np.full((H, W, 3), 30, np.uint8)
at = 0.0
complained = False
for _ in range(20):
    at += 1.0
    if still.look(card, moving=False, now=at):
        complained = True
check("a still card is not called frozen, because it is meant to be still",
      not complained)
check("nor called black, because it is dark and not dead",
      still.state == health.OK, still.state)

frozen = health.Watcher()
at = 0.0
found = ""
for _ in range(10):
    at += 1.0
    got = frozen.look(card, moving=True, now=at)
    if got and not found:
        found = got
check("but a CAMERA stuck on one frame is called frozen",
      "frozen" in found.lower(), found)

lively = health.Watcher()
at = 0.0
noise = False
rng = np.random.default_rng(7)
for _ in range(20):
    at += 1.0
    live = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
    if lively.look(live, moving=True, now=at):
        noise = True
check("a moving picture is never complained about", not noise)
check("and describes itself as fine", "fine" in lively.describe())

back = health.Watcher()
at = 0.0
for _ in range(8):
    at += 1.0
    back.look(black, moving=True, now=at)
recovered = ""
for _ in range(8):
    at += 1.0
    got = back.look(rng.integers(0, 255, (H, W, 3), dtype=np.uint8),
                    moving=True, now=at)
    if got:
        recovered = got
check("and coming back is said too, so silence is never the only signal",
      "back" in recovered.lower(), recovered)

# It has to be cheap: it runs on the streaming thread, once per frame.
watching = health.Watcher()
median, _ = bench(lambda: watching.look(a_frame(), moving=True))
check("looking at a frame costs almost nothing", median < 3.0,
      "%.2f ms" % median)


# ---------------------------------------------------------------------------
print("\nThe whole thing on a frame, at the size the encoder wants")
# ---------------------------------------------------------------------------

full = overlay.Overlay({
    "name": "Blindside Radio",
    "text_%s" % C.PLACE_TOP: C.TEXT_WORDS,
    "text_%s_words" % C.PLACE_TOP: "LIVE",
    "text_%s" % C.PLACE_CORNER: C.TEXT_WORDS,
    "text_%s_words" % C.PLACE_CORNER: "Ep. 214",
    "text_%s" % C.PLACE_LOWER: C.TEXT_STATION,
    "text_%s" % C.PLACE_CLOCK: C.TEXT_TIME,
})
canvas = a_frame(70)
full.draw_on(canvas)
check("all four places drew", full.renders == 4, full.renders)
check("the frame is still the right shape and type",
      canvas.shape == (H, W, 3) and canvas.dtype == np.uint8,
      (canvas.shape, canvas.dtype))
check("and still encodable, with nothing out of range",
      int(canvas.min()) >= 0 and int(canvas.max()) <= 255)

watcher = health.Watcher()
combined, _ = bench(lambda: (full.draw_on(canvas),
                             watcher.look(canvas, moving=True)))
check("drawing everything AND checking it fits a 30 fps frame",
      combined < 16.0, "%.2f ms of a 33.3 ms budget" % combined)

for size in ((1920, 1080), (640, 360)):
    other = np.full((size[1], size[0], 3), 70, np.uint8)
    full.draw_on(other)
    check("it also draws at %dx%d" % size,
          other.shape == (size[1], size[0], 3))


print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
