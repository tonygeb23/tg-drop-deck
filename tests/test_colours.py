"""Branding: colours you can choose without being able to see them.

Tony, 8 September 2026: "how about playing with colors, for people doing
branding, colored text, backgrounds that sit underneath everything else, that
kind of thing?"

Branding is the one part of a stream that is purely visual, so it is the
hardest thing in this app to do without sight. A colour wheel is not an
answer, it is the problem restated. The line taken everywhere else applies:
the app MEASURES what a sighted person would glance at, and SAYS it.

**The measurement that justifies the whole design**, taken through the real
encoder on 8 September 2026, is that the colour pairs H.264 destroys are
exactly the pairs with poor WCAG contrast. Video stores colour at half
resolution in 4:2:0 and keeps brightness, so contrast carried by HUE
evaporates: red text on a blue background has a greyscale edge of ZERO before
encoding even begins, and what came back was chroma bleed rather than
letters. WCAG contrast is a ratio of brightness, so it condemns those pairs
without being told anything about video. There is a check for that below, and
it runs the encoder.

**One number was not enough, though, and saying so was the correction.**
Researched on 8 September 2026: contrast predicts what a viewer can READ, and
it is blind to what a viewer can SEE at the edges. Colour is stored at half
resolution in both directions, so a strongly coloured letter keeps its shape
and frays at its border however good its contrast is, and no bitrate mends
it. Measured at 1 Mbps and at 6 Mbps the error on a red letter was the same.
So there are two numbers with two different repairs: a poor ratio wants a
different pair, and a fraying colour wants a weaker one. `fringing()` is the
second, and gold on navy is the case that proves they are not the same
question. It reads easily at 8.6 to 1 and frays at 83 per cent.

    python tests/test_colours.py
"""

import io
import fractions
import os
import inspect
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-colours-test-")

from dropdeck import colours as K
from dropdeck import constants as C
from dropdeck import overlay, picture
from dropdeck.board import Board

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


# ---------------------------------------------------------------------------
print("\nThe arithmetic, against WCAG's own published numbers")
# ---------------------------------------------------------------------------

# WCAG 2 fixes these exactly, so they are the reference rather than a guess.
check("black on white is 21 to 1, the maximum",
      abs(K.contrast((0, 0, 0), (255, 255, 255)) - 21.0) < 0.01,
      round(K.contrast((0, 0, 0), (255, 255, 255)), 3))
check("a colour against itself is 1 to 1",
      abs(K.contrast((90, 90, 90), (90, 90, 90)) - 1.0) < 1e-9)
check("white has luminance 1", abs(K.luminance((255, 255, 255)) - 1.0) < 1e-9)
check("black has luminance 0", abs(K.luminance((0, 0, 0))) < 1e-9)
# Green carries most of brightness and blue almost none, which is why blue
# text on black reads so much worse than it looks on paper.
check("green counts for far more than blue",
      K.luminance((0, 255, 0)) > 8 * K.luminance((0, 0, 255)),
      "%.3f against %.3f" % (K.luminance((0, 255, 0)),
                             K.luminance((0, 0, 255))))
check("the ratio does not care which way round it is asked",
      abs(K.contrast((20, 20, 20), (200, 200, 200))
          - K.contrast((200, 200, 200), (20, 20, 20))) < 1e-9)


# ---------------------------------------------------------------------------
print("\nNames, because a hex triplet cannot be read out")
# ---------------------------------------------------------------------------

check("there are enough colours to brand with, and few enough to hear",
      12 <= len(K.NAMES) <= 30, len(K.NAMES))
check("every one has a plain English name",
      all(n.replace(" ", "").isalpha() for n in K.NAMES), K.NAMES)
check("no name is jargon",
      not any(n in ("primary", "secondary", "surface", "accent1")
              for n in K.NAMES))
check("looking one up gives three numbers", K.rgb("navy") == (16, 32, 72))
check("an unknown name falls back rather than raising",
      K.rgb("chartreuse") == (240, 242, 248))
check("a colour can be named back", K.name_of((16, 32, 72)) == "navy")
check("and one that is not exactly ours gets the nearest name, not numbers",
      K.name_of((18, 30, 70)) == "navy", K.name_of((18, 30, 70)))
check("darks and lights are both offered, or nothing could be branded",
      any(K.luminance(K.rgb(n)) < 0.05 for n in K.NAMES)
      and any(K.luminance(K.rgb(n)) > 0.7 for n in K.NAMES))


# ---------------------------------------------------------------------------
print("\nWhat it SAYS, which is the whole accessibility of it")
# ---------------------------------------------------------------------------

ratio, said = K.verdict(K.rgb("off white"), K.rgb("near black"))
check("a good pair is called easy to read", said == "easy to read", said)
ratio, said = K.verdict(K.rgb("red"), K.rgb("blue"))
check("a hopeless pair is called what it is",
      "invisible" in said or "too close" in said, said)
check("a number is never said on its own",
      all(w for _r, w in [K.verdict(K.rgb(a), K.rgb(b))
                          for a in K.NAMES[:6] for b in K.NAMES[-6:]]))
line = K.describe_pair("gold", "navy")
check("a pair describes itself in one sentence",
      "gold" in line and "navy" in line and "to 1" in line, line)


# ---------------------------------------------------------------------------
print("\nEvery ready-made look, checked rather than chosen by eye")
# ---------------------------------------------------------------------------

check("there are several to choose from", len(K.SCHEMES) >= 6, len(K.SCHEMES))
bad_text, bad_accent = [], []
for name in K.SCHEME_NAMES:
    back, text, accent = K.scheme(name)
    if K.contrast(K.rgb(text), K.rgb(back)) < K.CONTRAST_GOOD:
        bad_text.append(name)
    if K.contrast(K.rgb(accent), K.rgb(back)) < K.CONTRAST_GOOD:
        bad_accent.append(name)
# THE ONE THAT MATTERS. A preset that ships unreadable is worse than no
# presets, because somebody who cannot check it has no reason to doubt it.
check("EVERY preset's words clear the target on its background",
      not bad_text, bad_text)
check("and every preset's accent does too", not bad_accent, bad_accent)
check("each names three colours we actually have",
      all(all(n in K.BY_NAME for n in K.scheme(s)) for s in K.SCHEME_NAMES))
check("a look describes itself with its number",
      "to 1" in K.describe_scheme("Midnight"), K.describe_scheme("Midnight"))
check("an unknown look falls back to the first rather than raising",
      K.scheme("Nonsense") == K.scheme(K.SCHEME_NAMES[0]))


# ---------------------------------------------------------------------------
print("\nThe brand reaches everything that draws")
# ---------------------------------------------------------------------------

board = Board()
check("a new board starts on a real look",
      board.colour_background in K.BY_NAME and board.colour_text in K.BY_NAME
      and board.colour_accent in K.BY_NAME)
check("and the default is readable",
      K.readable(K.rgb(board.colour_text), K.rgb(board.colour_background)))

board.colour_background = "navy"
board.colour_text = "cream"
board.colour_accent = "gold"
saved = Board.load.__self__ if False else None
data = board.to_dict()
check("the brand is saved with the board", data["colour_background"] == "navy")

settings = {"name": "Blindside Radio", "title": "Never Lose Sight",
            "picture": C.PICTURE_CARD, "colour_background": "navy",
            "colour_text": "cream", "colour_accent": "gold"}
back, ink, accent = picture.brand(settings)
check("the three come back as numbers", back == K.rgb("navy")
      and ink == K.rgb("cream") and accent == K.rgb("gold"))

card = picture.build(settings)
frame = card.frame(1280, 720)
corner = frame[4:24, 4:24].reshape(-1, 3).mean(axis=0)
check("the card is painted in the background colour",
      max(abs(int(a) - b) for a, b in zip(corner, K.rgb("navy"))) < 12,
      tuple(int(v) for v in corner))
check("and it is not the old default any more",
      max(abs(int(a) - b) for a, b in zip(corner, C.CARD_BACKGROUND)) > 12)

marks = overlay.Overlay(dict(settings, **{"text_%s" % C.PLACE_LOWER:
                                          C.TEXT_STATION}))
tile = marks._tile_for(C.PLACE_LOWER, 1280, 720)
check("the overlay panel is the background colour too", tile is not None)
if tile is not None:
    _rect, rgb_tile, alpha = tile
    # Sampled where the alpha is the PANEL's, not where it is opaque. The
    # panel is drawn at C.OVERLAY_ALPHA so the picture behind still reads;
    # the only fully opaque pixels in a tile are the text and its outline,
    # and comparing a black outline to a navy background rightly failed.
    panel_pixels = rgb_tile[alpha[:, :, 0] == C.OVERLAY_ALPHA]
    check("the panel is drawn at the translucent alpha, not opaque",
          len(panel_pixels) > 100, len(panel_pixels))
    if len(panel_pixels):
        near = np.abs(panel_pixels.astype(int)
                      - np.asarray(K.rgb("navy"))).sum(axis=1)
        check("so the panels match the card rather than fighting it",
              int(near.min()) < 30, int(near.min()))

# The letterbox bars are the "background under everything" in the most
# literal sense: they are what shows when a shot does not fill the frame.
from dropdeck.screen import ScreenSource      # noqa: E402
grabber = ScreenSource(C.SCREEN_ALL, 1280, 720, 30, bars=K.rgb("navy"))
check("the bars behind a shot take the brand colour",
      grabber.bars == K.rgb("navy"), grabber.bars)
from dropdeck.camera import CameraSource      # noqa: E402
check("and so do the bars behind a camera",
      CameraSource("", bars=K.rgb("maroon")).bars == K.rgb("maroon"))


# ---------------------------------------------------------------------------
print("\nThrough the real encoder, which is what justifies the whole design")
# ---------------------------------------------------------------------------

import av      # noqa: E402
from PIL import Image, ImageDraw      # noqa: E402

W, H = 640, 360


def greyscale_edge(front, back):
    """The sharpest BRIGHTNESS step in a caption, before and after encoding.

    Brightness, not colour, because that is what 4:2:0 keeps. A pair whose
    difference is entirely hue has no brightness step at all, and the encoder
    has nothing to preserve.
    """
    img = Image.new("RGB", (W, H), tuple(back))
    ImageDraw.Draw(img).text((40, 150), "Blindside 09:41",
                             font=overlay.font(40, bold=True),
                             fill=tuple(front))
    frame = np.asarray(img)
    out = io.BytesIO()
    container = av.open(out, mode="w", format="mp4")
    stream = container.add_stream("libx264", rate=30)
    stream.width, stream.height, stream.pix_fmt = W, H, "yuv420p"
    stream.bit_rate = 1200 * 1000
    stream.options = {"preset": "veryfast", "tune": "zerolatency", "bf": "0"}
    for at in range(6):
        video = av.VideoFrame.from_ndarray(frame, format="rgb24")
        video = video.reformat(format="yuv420p")
        video.pts = at
        video.time_base = fractions.Fraction(1, 30)
        for packet in stream.encode(video):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    out.seek(0)
    back_in = av.open(out)
    last = None
    for got in back_in.decode(video=0):
        last = got.to_ndarray(format="rgb24")
    back_in.close()

    def edge(image):
        grey = image.mean(axis=2)
        return float(np.abs(np.diff(grey, axis=1)).max())

    return edge(frame), edge(last)


good_before, good_after = greyscale_edge(K.rgb("off white"),
                                         K.rgb("near black"))
check("a good pair has a strong brightness step", good_before > 150,
      "%.0f" % good_before)
check("and keeps it through the encoder", good_after > good_before * 0.85,
      "%.0f then %.0f" % (good_before, good_after))

bad_before, bad_after = greyscale_edge(K.rgb("red"), K.rgb("blue"))
# Stated as a comparison rather than an absolute, because the palette's red
# and blue are not the pure primaries: there IS a step, it is simply tiny.
# With the pure primaries it really is zero, which is what makes the point,
# but a check should assert what this palette actually does.
check("red on blue has almost no brightness step for the encoder to keep",
      bad_before < good_before / 10.0,
      "%.0f against %.0f for a good pair" % (bad_before, good_before))
check("so what comes back is chroma bleed rather than letters",
      bad_after < good_after / 5.0,
      "%.0f against %.0f" % (bad_after, good_after))
check("and the contrast number condemns it without being told about video",
      K.contrast(K.rgb("red"), K.rgb("blue")) < K.CONTRAST_FLOOR,
      "%.1f to 1" % K.contrast(K.rgb("red"), K.rgb("blue")))

# The pure primaries, which is where the effect is total and where the
# design decision actually came from.
pure_before, _pure_after = greyscale_edge((255, 0, 0), (0, 0, 255))
check("with the PURE primaries there is no step at all", pure_before < 1.0,
      "%.1f" % pure_before)

# Every preset has to survive the encoder, not merely score well on paper.
worst = None
for name in K.SCHEME_NAMES:
    back, text, _accent = K.scheme(name)
    step, _kept = greyscale_edge(K.rgb(text), K.rgb(back))
    if worst is None or step < worst[1]:
        worst = (name, step)
check("EVERY preset has a real brightness step, so none can be eaten by 4:2:0",
      worst is not None and worst[1] > 100,
      "weakest is %s at %.0f" % worst if worst else "")



def head(title):
    print(os.linesep + title + os.linesep)


# ---------------------------------------------------------------------------
# What the research changed, 8 September 2026
# ---------------------------------------------------------------------------

head("The picture goes out as BT.709, and says so")

# Measured before this was fixed: swscale's default is the BT.601 matrix, so
# a 720p stream was carrying standard definition colour weights, untagged,
# and every player assumes BT.709 for anything this size. The reference
# values are white 235, red 63, blue 32.
import av as _av
from dropdeck.streamout import _video_options, _tag_colour

_opts = _video_options("libx264", 30, 2500)
_params = _opts.get("x264-params", "")
for _want in ("colorprim=bt709", "transfer=bt709", "colormatrix=bt709",
              "range=tv"):
    check("the encoder is told %s" % _want, _want in _params, _params[:40])
check("and the CBR padding is still there beside it",
      "nal-hrd=cbr" in _params and "filler=1" in _params, _params[-24:])
_plain = _video_options("libx264", 30, 0).get("x264-params", "")
check("a stream with no bitrate set is tagged too, not only the CBR one",
      "colormatrix=bt709" in _plain, _plain)

_out = os.path.join(tempfile.gettempdir(), "dropdeck_709.flv")
_c = _av.open(_out, "w", format="flv")
_v = _c.add_stream("libx264", rate=30)
_v.width, _v.height = 320, 240
_v.pix_fmt = "yuv420p"
_tag_colour(_v)
_v.options = _opts
_img = np.zeros((240, 320, 3), dtype=np.uint8)
_img[:, :106] = (255, 255, 255)
_img[:, 106:213] = (255, 0, 0)
_img[:, 213:] = (0, 0, 255)
for _i in range(20):
    _f = _av.VideoFrame.from_ndarray(_img, format="rgb24")
    _f = _f.reformat(format="yuv420p", dst_colorspace=C.RTMP_COLOURSPACE)
    _f.pts = _i * 33
    _f.time_base = fractions.Fraction(1, 1000)
    for _p in _v.encode(_f):
        _c.mux(_p)
for _p in _v.encode():
    _c.mux(_p)
_c.close()

_d = _av.open(_out)
_cc = _d.streams.video[0].codec_context
check("the tag survives the FLV, which carries no colour metadata itself",
      _cc.colorspace == 1, _cc.colorspace)
check("and so do the primaries", _cc.color_primaries == 1, _cc.color_primaries)
check("and the transfer curve", _cc.color_trc == 1, _cc.color_trc)
check("and the range says limited, which is what is really being sent",
      int(_cc.color_range) == 1, _cc.color_range)
for _fr in _d.decode(video=0):
    _y = np.frombuffer(_fr.planes[0], dtype=np.uint8).reshape(
        -1, _fr.planes[0].line_size)
    _white, _red, _blue = int(_y[120, 50]), int(_y[120, 160]), int(_y[120, 270])
    break
_d.close()
check("white comes back at the reference 235", abs(_white - 235) <= 1, _white)
check("red at 63, which is BT.709 and not the 81 BT.601 was giving",
      abs(_red - 63) <= 2, _red)
check("blue at 32, not 41", abs(_blue - 32) <= 2, _blue)
try:
    os.remove(_out)
except OSError:
    pass


head("Fraying is a second question, and contrast cannot answer it")

check("a strong colour is flagged", K.fringing(K.rgb("orange"))[1],
      "%.0f%%" % (K.fringing(K.rgb("orange"))[0] * 100))
check("and a near neutral one is not", not K.fringing(K.rgb("off white"))[1],
      "%.0f%%" % (K.fringing(K.rgb("off white"))[0] * 100))
check("grey has no colour to lose at all", K.saturation((128, 128, 128)) == 0.0,
      K.saturation((128, 128, 128)))
check("black does not divide by zero", K.saturation((0, 0, 0)) == 0.0)
# The point of having two numbers: a pair that reads perfectly can still fray.
_ratio = K.contrast(K.rgb("gold"), K.rgb("navy"))
check("gold on navy reads easily", _ratio >= 7.0, "%.1f to 1" % _ratio)
check("and frays all the same, which one number would have hidden",
      K.fringing(K.rgb("gold"))[1], "%.0f%%" % (K.fringing(K.rgb("gold"))[0] * 100))
check("so the sentence says both", "fray" in K.describe_pair("gold", "navy"),
      K.describe_pair("gold", "navy"))

head("No ready-made look puts a fraying colour in the WORDS")

for _name, _back, _ink, _accent in K.SCHEMES:
    _level, _frays = K.fringing(K.rgb(_ink))
    check("%s writes in something that will not fray" % _name, not _frays,
          "%s at %.0f%%" % (_ink, _level * 100))

head("A coloured rule is an even number of pixels high")

# One pixel lost 57 levels of colour, two lost 12, and three lost 17: an odd
# height straddles two chroma blocks. 720 // 240 is 3, so this was the common
# case, not an edge one.
check("720p rounds down to two rather than the three it was drawing",
      K.even(720 // 240) == 2, K.even(720 // 240))
check("1080p gets four", K.even(1080 // 240) == 4, K.even(1080 // 240))
check("and nothing ever goes below two", K.even(0) == 2 and K.even(1) == 2)
for _h in range(1, 40):
    if K.even(_h) % 2:
        check("every thickness is even", False, _h)
        break
else:
    check("every thickness from 1 to 40 comes back even", True)

head("The luminance constant is the corrected one")

# Pinning the COMPARISON, not the file: the docstring names the old figure
# on purpose, to say what was changed and why. And there is no behavioural
# check to be had here, which is worth knowing rather than hunting for. Both
# thresholds fall between channel 10 (0.0392) and channel 11 (0.0431), so at
# eight bits every possible input takes the same branch either way. The
# correction is about being right, not about moving a pixel.
check("the comparison itself uses 0.04045, the figure the W3C corrected to",
      "c <= 0.04045" in inspect.getsource(K.luminance), "")
check("and nothing still compares against the withdrawn 0.03928",
      "c <= 0.03928" not in inspect.getsource(K.luminance), "")
# Sanity: the well known ratios still come out right.
check("white on black is still 21 to 1",
      abs(K.contrast((255, 255, 255), (0, 0, 0)) - 21.0) < 0.01,
      "%.2f" % K.contrast((255, 255, 255), (0, 0, 0)))

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
