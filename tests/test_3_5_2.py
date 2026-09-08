"""3.5.2: the camera's corner, and asking questions rather than only reading.

Three asks, 8 September 2026.

  1. Somebody pointed out that the camera is always bottom right. A presenter
     whose screen has its own furniture down one side, or a platform that
     puts a chat panel over a corner, needs it somewhere else, and there is
     no single right answer.
  2. "can you add an edit box to chat and ask questions?" The shot check
     described the picture and then stopped. Everything a person wants next
     is a follow-up: is the plant distracting, can you read the caption.
  3. On the colours window: a description of the chosen look that can be
     TABBED TO, and a button that asks a model what the branding actually
     looks like to somebody who can see it. That last one is the only
     question in this app that arithmetic genuinely cannot answer.

    python tests/test_3_5_2.py
"""

import inspect
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-352-test-")

import wx

from dropdeck import constants as C, picture, screen, ui, vision
from dropdeck.board import Board
from dropdeck.dialogs import AskPanel, ColoursDialog, ShotCheckDialog
from dropdeck.dialogs import VideoSourceDialog

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


def head(title):
    print(os.linesep + title + os.linesep)


class FakeScreen:
    kind = "screen"

    def frame(self, w, h):
        a = np.zeros((h, w, 3), dtype=np.uint8)
        a[:, :] = (20, 20, 20)
        return a

    def start(self):
        return self

    def close(self):
        pass

    def wait_ready(self, _t=None):
        return True


class FakeCam(FakeScreen):
    kind = "camera"

    def frame(self, w, h):
        a = np.zeros((h, w, 3), dtype=np.uint8)
        a[:, :] = (255, 0, 0)
        return a


def where_is_the_camera(corner, width=1280, height=720):
    """The rectangle the camera really occupies, found by looking."""
    source = screen.SplitSource(FakeScreen(), FakeCam(), corner=corner)
    shot = source.frame(width, height)
    red = np.argwhere((shot[:, :, 0] > 200) & (shot[:, :, 1] < 60))
    top, left = red.min(axis=0)
    bottom, right = red.max(axis=0)
    return int(top), int(left), int(bottom), int(right)


app = wx.App()
frame = ui.DropDeckFrame(None)

# ---------------------------------------------------------------------------
head("The camera goes in the corner you ask for")

check("there are four of them", len(C.SPLIT_CORNERS) == 4, C.SPLIT_CORNERS)
check("named rather than numbered, because the name is what is read out",
      all(" " in c and c.islower() for c in C.SPLIT_CORNERS))
check("and bottom right is still the default, which is where it has always "
      "been", C.SPLIT_CORNER == "bottom right")

W, H = 1280, 720
seen = {}
for corner in C.SPLIT_CORNERS:
    seen[corner] = where_is_the_camera(corner, W, H)
    top, left, bottom, right = seen[corner]
    vertical = "top" if top < H / 2 else "bottom"
    horizontal = "left" if left < W / 2 else "right"
    check("%s really puts it %s %s" % (corner, vertical, horizontal),
          corner == "%s %s" % (vertical, horizontal),
          "rows %d-%d cols %d-%d" % (top, bottom, left, right))

# The margins have to mirror, or the inset drifts away from one corner.
tl = seen["top left"]
br = seen["bottom right"]
check("the left margin matches the right one", tl[1] == W - 1 - br[3],
      "%d and %d" % (tl[1], W - 1 - br[3]))
check("and the top margin matches the bottom", tl[0] == H - 1 - br[2],
      "%d and %d" % (tl[0], H - 1 - br[2]))
sizes = {(b - t, r - l) for t, l, b, r in seen.values()}
check("and the camera is the same size in every corner", len(sizes) == 1,
      sizes)

head("The corner is remembered, and cannot be anything it likes")

board = Board()
check("a new board starts bottom right",
      board.split_corner == C.SPLIT_CORNER, board.split_corner)
check("it is saved", "split_corner" in board.to_dict())
check("and it belongs to the station, like the rest of the picture",
      "split_corner" in getattr(__import__("dropdeck.board",
                                           fromlist=["board"]),
                                "STATION_FIELDS", ()))
saved = board.to_dict()
saved["split_corner"] = "somewhere else entirely"
check("a board file cannot smuggle in a corner of its own",
      Board.load_dict(saved).split_corner in C.SPLIT_CORNERS
      if hasattr(Board, "load_dict") else True)
check("the source refuses a corner it does not know",
      screen.SplitSource(FakeScreen(), FakeCam(),
                         corner="nonsense").corner == C.SPLIT_CORNER)
check("and the picture settings carry it to the builder",
      "split_corner" in frame._picture_settings())

head("And you can change it in the video source window")

box = VideoSourceDialog(frame, frame.board, live=False)
check("there is a corner control", hasattr(box, "corner"))
check("it offers all four", box.corner.GetCount() == 4, box.corner.GetCount())
check("it starts on the board's own", box.corner.GetSelection()
      == C.SPLIT_CORNERS.index(frame.board.split_corner))
# It means nothing unless the screen is what is going out.
frame.board.picture = C.PICTURE_CARD
box.refresh()
check("and it is dead while a card is what is going out",
      not box.corner.IsEnabled())
kinds = box.kinds()
if C.PICTURE_SPLIT in kinds:
    box.list.Select(kinds.index(C.PICTURE_SPLIT))
    check("and alive when the split is chosen", box.corner.IsEnabled())
    check("the sentence under the list says WHICH corner",
          frame.board.split_corner in box.doing.GetLabel(),
          box.doing.GetLabel()[-60:])
else:
    check("no screen capture here, so the split is not offered", True,
          "skipped")
box.Destroy()

head("A question box, in both places, and it is the same one")

check("there is one class, not two", inspect.isclass(AskPanel))
source = inspect.getsource(AskPanel)
check("it works on its own thread", "dropdeck-ask" in source)
check("Enter sends the question, so nobody has to tab to a button",
      "TE_PROCESS_ENTER" in source and "EVT_TEXT_ENTER" in source)
check("the answer is a read only box, so it can be arrowed line by line",
      "TE_READONLY" in source and "TE_MULTILINE" in source)
check("and closing the window mid answer is not a fault",
      "RuntimeError" in source)

shot_box = ShotCheckDialog(frame, frame)
check("the shot check has one", isinstance(shot_box.ask, AskPanel))
check("asking nothing is refused politely, not sent",
      shot_box.ask._on_ask() is None
      and "question" in shot_box.ask.answer.GetValue().lower(),
      shot_box.ask.answer.GetValue()[:40])
check("a follow-up asks about the picture that was DESCRIBED, not a new one",
      "_looked_at" in inspect.getsource(ShotCheckDialog._last_or_fresh))
check("and falls back to a fresh one if nothing has been checked yet",
      shot_box._last_or_fresh() is not None)
shot_box.Destroy()

head("The colours window says what the look IS, in a box you can tab to")

colour_box = ColoursDialog(frame, frame.board)
check("there is a summary control", hasattr(colour_box, "summary"))
check("it is a text box rather than a label, so it can be read a line at a "
      "time", isinstance(colour_box.summary, wx.TextCtrl))
check("and it is read only", colour_box.summary.IsEditable() is False)
lines = colour_box.summary.GetValue().splitlines()
check("it names the ready-made look when one is chosen",
      any("Default" in line for line in lines), lines[:1])
check("it names all three colours",
      any("Background" in line and "words" in line and "accent" in line
          for line in lines), lines[1:2] if len(lines) > 1 else lines)
check("it scores the words against the background",
      any("Words on the background" in line for line in lines))
check("and the accent too, which the row list only shows one at a time",
      any("Accent on the background" in line for line in lines))

head("And what a sighted person would make of it, which no number can say")

check("there is a button for it", hasattr(colour_box, "describe_button"))
check("it renders a real frame rather than sending a list of names",
      colour_box._sample().shape == (720, 1280, 3),
      colour_box._sample().shape)
sample = colour_box._sample()
check("the sample really is in the brand's own background colour",
      tuple(sample[5, 5]) == tuple(
          __import__("dropdeck.colours", fromlist=["colours"]).rgb(
              frame.board.colour_background)),
      tuple(sample[5, 5]))
check("the colours window has a question box too",
      isinstance(colour_box.ask, AskPanel))
check("and it asks about branding, not about a camera shot",
      colour_box.ask.kind == "branding")
check("what it asks is a different question from the shot check's",
      vision.prompt_for("branding") != vision.prompt_for("camera"))
colour_box.Destroy()

head("What gets asked, for a look rather than a shot")

branding = vision.prompt_for("branding")
check("it says the person is blind and has never seen these together",
      "blind" in branding.lower() and "never seen" in branding.lower())
check("it says they already know the contrast, so do not repeat it",
      "readable" in branding.lower() and "numbers" in branding.lower())
check("it asks for an impression rather than a description",
      "impression" in branding.lower())
check("it asks what the look would SUIT", "suit" in branding.lower())
check("it allows the answer to be that it looks bad",
      "bad" in branding.lower())
check("and it says a compliment they cannot check is worth nothing",
      "compliment" in branding.lower())

head("Follow-ups carry what was already said")

follow = vision._FOLLOW_UP
check("a follow-up is not the whole checklist again", follow != branding)
check("it answers the question asked, first", "first" in follow.lower())
check("and does not re-describe everything",
      "re-describe" in follow.lower())
check("only the last few exchanges travel, so a long chat stays cheap",
      2 <= vision.MEMORY <= 12, vision.MEMORY)
ok, said = vision.converse(np.zeros((8, 8, 3), dtype=np.uint8), "  ", [],
                           "google", "k")
check("an empty question never reaches the network", not ok, said)

frame.stop_background_work()
frame.Destroy()

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
