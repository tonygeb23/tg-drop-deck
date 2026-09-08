"""The shot check: asking a model that can see, without it ever mattering.

Tony, 8 September 2026: "a user can use their claude, open AI, or Gemini key
to look at the visual output before they go streaming, and get a detailed
description on what's on the screen, the camera, give advice if things don't
look good in the camera view".

Everything else in this app MEASURES and says the number. This one ASKS, and
that makes it the first thing here that can be slow, can cost money, can fail
for reasons outside the machine, and can send a picture of somebody's desktop
to a company. So the checks below are mostly about what it must NEVER do:
never sit between a person and going live, never raise, and never send a
screen without asking first, every single time.

    python tests/test_shotcheck.py
"""

import inspect
import os
import sys
import tempfile
import urllib.error

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="dropdeck-shot-test-")

from dropdeck import constants as C
from dropdeck import secrets, vision
from dropdeck.board import Board

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append(bool(condition))
    print(("  ok   " if condition else "  FAIL ") + label
          + (("  " + str(detail)) if detail else ""))


def head(title):
    print(os.linesep + title + os.linesep)


def picture(width=640, height=360, colour=(20, 40, 90)):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = colour
    return frame


# ---------------------------------------------------------------------------
head("A screen is never sent without asking, and asking is EVERY time")

check("a screen needs consent", vision.needs_consent("screen"))
check("a camera does not, being the face you are about to broadcast anyway",
      not vision.needs_consent("camera"))
question = vision.consent_question("screen", "google")
check("the question names the company the picture goes to",
      "Google" in question, question[:44])
check("and says it is the WHOLE screen", "WHOLE SCREEN" in question)
check("and warns about what may be behind the window",
      "password" in question.lower() and "email" in question.lower())
check("a camera asks nothing", vision.consent_question("camera", "google") == "")
# There is no remembered yes anywhere, on purpose: a yes given about one
# screen is not a yes about the next one.
source = inspect.getsource(vision)
check("nothing in here remembers a consent",
      "remember" not in source.lower().replace("remembered yes", ""),
      "")

head("Nothing raises, ever, whatever is wrong")

ok, said = vision.describe(picture(), "camera", "google", "")
check("no key is a sentence, not an exception", not ok and "key" in said.lower())
ok, said = vision.describe(picture(), "camera", "notaprovider", "k")
check("an unknown provider is a sentence too", not ok and "provider" in said)
ok, said = vision.describe(None, "camera", "google", "k")
check("and no picture at all", not ok and "picture" in said.lower())
for code, word in ((401, "key"), (404, "model"), (429, "credit"),
                   (500, "their end")):
    error = urllib.error.HTTPError("u", code, "m", {}, None)
    said = vision._trouble(error, "google")
    check("HTTP %d is explained in words, not a number" % code,
          word in said.lower(), said[:58])
    check("and %d never shows the raw code to the user" % code,
          str(code) not in said, said[:40])
said = vision._trouble(urllib.error.URLError("offline"), "google")
check("being offline says the show is unaffected", "unaffected" in said, said[:50])

head("It cannot get in the way of going live")

frame_source = inspect.getsource(
    __import__("dropdeck.ui", fromlist=["ui"]))
start = frame_source.index("def toggle_stream")
end = frame_source.index("def ", start + 10)
check("toggle_stream does not mention the shot check at all",
      "shot" not in frame_source[start:end].lower(),
      "")
start = frame_source.index("def start_stream")
end = frame_source.index("\n    def ", start + 10)
check("and neither does start_stream", "vision" not in frame_source[start:end])
check("the work is put on a thread of its own",
      "dropdeck-shotcheck" in inspect.getsource(
          __import__("dropdeck.dialogs", fromlist=["dialogs"])))

head("The key is kept where a stream key is kept, and not in the board")

check("there is a prefix of its own", secrets.VISION_PREFIX
      != secrets.TARGET_PREFIX)
check("and it does not call itself a stream key",
      "stream" not in secrets.VISION_PREFIX.lower(), secrets.VISION_PREFIX)
board = Board()
saved = board.to_dict()
blob = str(saved)
check("the board saves which provider to ask", "vision_provider" in saved)
check("and the model", "vision_model" in saved)
check("and NEVER the key itself", "vision_key" not in saved
      and "api_key" not in blob.lower())
check("a board file cannot smuggle in a provider of its own",
      Board.from_dict({"vision_provider": "http://evil"}).vision_provider
      in C.VISION_PROVIDERS
      if hasattr(Board, "from_dict") else True)

head("What is asked, which is most of whether it is any use")

camera = vision.prompt_for("camera")
screen = vision.prompt_for("screen")
check("the two questions are different", camera != screen)
check("the camera one asks about lighting", "lighting" in camera.lower())
check("and about the background", "background" in camera.lower())
check("and about whether the overlay covers the face",
      "face" in camera.lower())
check("the screen one leads on anything private",
      screen.lower().index("private") < screen.lower().index("legibility"))
check("and names a password manager by name",
      "password manager" in screen.lower())
for prompt in (camera, screen):
    check("it says the reader is blind and cannot check the answer",
          "blind" in prompt.lower() and "cannot" in prompt.lower())
    check("it asks for a verdict first", "First line" in prompt)
    check("and forbids hedging", "possibly" in prompt)

head("The picture is made smaller before it goes anywhere")

big = picture(1920, 1080)
jpeg = vision.as_jpeg(big)
check("a frame really does encode", jpeg is not None and len(jpeg) > 200,
      "%d bytes" % (len(jpeg) if jpeg else 0))
check("and it is a JPEG", jpeg[:2] == b"\xff\xd8" if jpeg else False)
check("1920 wide is scaled down to the sending width",
      vision.SEND_WIDTH < 1920, vision.SEND_WIDTH)
smaller = vision.as_jpeg(picture(320, 180))
check("a small frame is not scaled UP", len(smaller) < len(jpeg),
      "%d against %d" % (len(smaller), len(jpeg)))
check("the size can be said out loud before sending",
      vision.sent_kilobytes(big) > 0,
      "%.0f kB" % vision.sent_kilobytes(big))

head("Who to ask, when nobody has said")

held = secrets.fetch("google", secrets.VISION_PREFIX)
if held:
    check("the default follows the key that is really on this machine",
          vision.best_provider("anthropic") in vision.providers_with_keys(),
          vision.best_provider("anthropic"))
else:
    check("with no keys at all it falls back rather than failing",
          vision.best_provider("anthropic") == "anthropic")
check("every provider has a name that can be read out",
      all(p in vision.PROVIDER_NAMES for p in vision.PROVIDERS))
check("and a default model", all(p in vision.DEFAULT_MODELS
                                for p in vision.PROVIDERS))
check("the Google default is a moving alias, not a pinned version",
      "latest" in vision.DEFAULT_MODELS["google"],
      vision.DEFAULT_MODELS["google"])
check("the timeout is generous enough for a slow thinking model",
      vision.TIMEOUT >= 60, vision.TIMEOUT)

head("The three envelopes")

jpeg = vision.as_jpeg(picture())
for name, builder in (("anthropic", vision._anthropic),
                      ("openai", vision._openai), ("google", vision._google)):
    request, _read = builder("m", "SECRETKEY", jpeg, "ask")
    check("%s posts" % name, request.method == "POST")
    check("%s sends the key in a HEADER, never in the URL" % name,
          "SECRETKEY" not in request.full_url,
          request.full_url[:52])
    check("%s says it is JSON" % name,
          "json" in str(request.headers).lower())

print("\n%d/%d checks passed" % (sum(CHECKS), len(CHECKS)))
sys.exit(0 if all(CHECKS) else 1)
