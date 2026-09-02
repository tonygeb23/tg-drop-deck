"""Feedback, and the word about donating.

    python tests/test_feedback.py

Nothing here talks to the live server: the send is stood in for, and what is
checked is everything around it. Two things matter more than the rest.

**A report is never lost.** It is written to disk before any attempt to send,
so no network, a server restarting, or the app being closed on the way out of
a venue costs somebody a bug report they have already spent their attention
writing. A failed send is "still queued", not an error.

**Nothing about the board ever leaves the machine.** A soundboard holds
somebody's whole show, and the file paths alone would say where they keep it.
The diagnostics carry counts and settings and nothing else, and the window
reads back exactly what will be sent - so the check here is that no name and
no path can be found anywhere in it.

The donate prompt is checked for being quiet: never in the first week, once a
week at the very most after that, and gone for good if somebody says so.
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APPDATA = tempfile.mkdtemp(prefix="dropdeck-feedback-appdata-")
os.environ["APPDATA"] = APPDATA

import wx

from dropdeck import constants as C
from dropdeck import feedback
from dropdeck.board import Board
from dropdeck.dialogs import DonateDialog, FeedbackDialog
from dropdeck.ui import DropDeckFrame

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition)))
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))


def reset_state():
    for name in ("feedback_queue.json", "donate.json", "install.json"):
        path = os.path.join(feedback._state_dir(), name)
        if os.path.exists(path):
            os.remove(path)


app = wx.App(redirect=False)
tmp = tempfile.mkdtemp(prefix="dropdeck-feedback-")
reset_state()

# ---------------------------------------------------------------------------
print("What a report is")

check("there are categories, and Tony's are among them",
      {"accessibility", "bug", "suggestion", "audio", "other"}
      <= {key for key, _label in feedback.TYPES},
      [k for k, _ in feedback.TYPES])
check("every one of them is spelled out rather than left as a slug",
      all(len(label) > len(key) for key, label in feedback.TYPES))

first = feedback.install_id()
check("this copy has an id", first and len(first) == 8, first)
check("and it is the same one next time", feedback.install_id() == first)

report = feedback.build("bug", "  it went quiet  ")
check("a report carries the category and its label",
      report["type"] == "bug" and "broken" in report["type_label"],
      report["type_label"])
check("the message is trimmed", report["message"] == "it went quiet")
check("it is stamped", report["written_at"].startswith(str(datetime.now().year)))
check("and it names the product and version",
      report["diagnostics"]["product"] == C.APP_NAME
      and report["diagnostics"]["version"] == C.APP_VERSION)

# ---------------------------------------------------------------------------
print("Nothing about the board ever leaves the machine")

frame = DropDeckFrame()
board = Board()
board.path = os.path.join(tmp, "live.json")
board.rename_bank(1, "Sirens and Alarms")
board[0].filepath = os.path.join(tmp, "Very Private Show", "secret jingle.wav")
board[0].name = "Secret Jingle"
board.playlist.add([])
frame._adopt(board)

report = feedback.build("bug", "the thing broke", frame)
blob = json.dumps(report)
check("a private sound name is nowhere in the report",
      "Secret Jingle" not in blob, "leaked a sound name")
check("nor a file path", "Very Private Show" not in blob, "leaked a path")
check("nor a bank the user renamed",
      "Sirens and Alarms" not in blob, "leaked a bank name")
check("but the counts are, which is what makes a report actionable",
      "sounds_assigned" in report["diagnostics"]
      and "playlist_tracks" in report["diagnostics"],
      sorted(report["diagnostics"]))
check("and the audio settings, which is where the answer usually is",
      "ducking" in report["diagnostics"]
      and "bed_fade_in" in report["diagnostics"])

text = feedback.readable(report)
check("the window reads back the message", "the thing broke" in text)
check("and every single thing that goes with it",
      all(key.replace("_", " ") in text
          for key in report["diagnostics"]), text[:200])
check("and says plainly what is NOT sent",
      "No file names" in text and "running order" in text, text[-200:])

# ---------------------------------------------------------------------------
print("A report is never lost to a bad connection")

reset_state()
check("the queue starts empty", feedback.queued_count() == 0)

sent = []


def refuse(_report):
    raise OSError("no network")


def accept(report):
    sent.append(report)
    return True


real_post = feedback._post
feedback._post = refuse
delivered, queued = feedback.submit("bug", "written on a train", frame)
check("a send that fails is not an error", delivered is False)
check("and the report is on disk", queued == 1 and feedback.queued_count() == 1)

feedback._post = refuse
feedback.submit("audio", "and another one", frame)
check("they stack up in the order they were written",
      feedback.queued_count() == 2)

feedback._post = accept
count, left = feedback.flush()
check("and all of them go out when the network comes back",
      count == 2 and left == 0, (count, left))
check("in the order they were written",
      [r["message"] for r in sent] == ["written on a train", "and another one"],
      [r["message"] for r in sent])

# One that will not send blocks the ones behind it, deliberately.
sent.clear()
feedback._post = refuse
feedback.submit("bug", "first", frame)
feedback.submit("bug", "second", frame)
attempts = []


def only_second(report):
    attempts.append(report["message"])
    return report["message"] != "first"


feedback._post = only_second
feedback.flush()
check("a report that will not go does not let the ones behind it overtake",
      attempts == ["first"] and feedback.queued_count() == 2, attempts)

feedback._post = accept
feedback.flush()
check("and they all go once it can", feedback.queued_count() == 0)
feedback._post = real_post

reset_state()

# ---------------------------------------------------------------------------
print("The window itself")

dialog = FeedbackDialog(frame, frame)
check("the category box is named for a screen reader",
      dialog.kind.GetName() == "What kind of feedback")
check("the message box is too", dialog.message.GetName() == "Your message")
check("and so is the read-back",
      dialog.preview.GetName() == "What will be sent")
check("every category is offered",
      dialog.kind.GetCount() == len(feedback.TYPES), dialog.kind.GetCount())
check("Submit is off until there is something to send",
      not dialog.submit.IsEnabled())
dialog.message.SetValue("something to say")
dialog._refresh()
check("and on once there is", dialog.submit.IsEnabled())
check("the read-back updates as you type",
      "something to say" in dialog.preview.GetValue())
dialog.kind.SetSelection(1)
dialog._refresh()
check("and follows the category",
      dialog.feedback_type == feedback.TYPES[1][0], dialog.feedback_type)
dialog.Destroy()

# ---------------------------------------------------------------------------
print("The word about donating, and how quiet it is")

reset_state()
now = datetime.now(timezone.utc)
check("nobody is asked on their first run",
      not feedback.should_ask_about_donating(now))
check("which is when the clock starts",
      "first_seen" in feedback.donate_state())
check("and not the next day either",
      not feedback.should_ask_about_donating(now + timedelta(days=1)))
check("nor at six days", not feedback.should_ask_about_donating(
    now + timedelta(days=6)))
check("but at a week, yes",
      feedback.should_ask_about_donating(now + timedelta(days=7, hours=1)))

asked = now + timedelta(days=7, hours=1)
feedback.mark_asked(asked)
check("having asked, it does not ask again the next day",
      not feedback.should_ask_about_donating(asked + timedelta(days=1)))
check("nor six days later",
      not feedback.should_ask_about_donating(asked + timedelta(days=6)))
check("but a week after that, once",
      feedback.should_ask_about_donating(asked + timedelta(days=7, hours=1)))

feedback.mark_donated(asked)
check("somebody who has been to the donate page is left alone",
      not feedback.should_ask_about_donating(asked + timedelta(days=30)))
check("for months, not weeks",
      not feedback.should_ask_about_donating(asked + timedelta(days=170)))
check("and is asked again only long afterwards",
      feedback.should_ask_about_donating(asked + timedelta(days=200)))

reset_state()
feedback.should_ask_about_donating(now)          # start the clock
feedback.mark_never(True)
check("and never means never",
      not feedback.should_ask_about_donating(now + timedelta(days=365)))
check("which is written down, so it survives a restart",
      feedback.donate_state().get("never") is True)

reset_state()
donate = DonateDialog(frame)
words = donate.text.GetValue()
check("the message is in a box that can be read back at your own pace",
      donate.text.IsEditable() is False and donate.text.GetName())
check("it says the app is free and staying free",
      "free" in words and "carry on being free" in words, words[:80])
check("it says where the money goes",
      "development" in words and "server costs" in words
      and "new products" in words)
check("it offers the contributors list, and says it is optional",
      "contributors list" in words and "rockstar" in words)
check("and it says how often it will ask",
      "once a week" in words and "first week" in words)
check("there is a way to stop it asking", donate.never is not None)
check("and it is off unless you tick it", not donate.never_again)
donate.Destroy()

# ---------------------------------------------------------------------------
print("From the app")

check("Help offers both without needing a key",
      any("submit feedback" in item.GetItemLabelText().lower()
          for menu, _title in
          [(frame.GetMenuBar().GetMenu(i), None)
           for i in range(frame.GetMenuBar().GetMenuCount())]
          for item in menu.GetMenuItems() if not item.IsSeparator()))
labels = [item.GetItemLabelText().lower()
          for i in range(frame.GetMenuBar().GetMenuCount())
          for item in frame.GetMenuBar().GetMenu(i).GetMenuItems()
          if not item.IsSeparator()]
check("and Donate is there too", any("donate" in text for text in labels),
      labels)
check("the donate page is the real one",
      feedback.DONATE_URL.startswith("https://tgstudios.app/donate"),
      feedback.DONATE_URL)
check("and feedback goes somewhere over HTTPS",
      feedback.ENDPOINT.startswith("https://"), feedback.ENDPOINT)

check("F1 help explains both", "Submit feedback" in C.KEYBOARD_HELP
      and "Donate" in C.KEYBOARD_HELP)
check("and says what is not sent",
      "Never a file name" in C.KEYBOARD_HELP)

# ---------------------------------------------------------------------------
try:
    frame.stop_background_work()
except Exception:
    pass
try:
    frame.mixer.close()
except Exception:
    pass
frame.Destroy()
shutil.rmtree(tmp, ignore_errors=True)

failed = [n for n, ok in CHECKS if not ok]
print("\n%d/%d checks passed" % (len(CHECKS) - len(failed), len(CHECKS)))
if failed:
    for n in failed:
        print("  FAILED: " + n)
    sys.exit(1)
