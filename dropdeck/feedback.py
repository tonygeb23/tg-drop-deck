"""Feedback sent from inside the app, and the occasional word about donating.

WHY FROM INSIDE THE APP
-----------------------
The people using this are blind and low-vision, and the moment worth capturing
is the moment something goes wrong — which is exactly the moment when leaving
the app, finding an email client, describing where you were and what you had
pressed, and remembering the version number is most expensive. A menu item and
a sentence gets a report that would otherwise never be written.

Same shape as Word Champion's, deliberately, and the same endpoint: one place
to read both means feedback actually gets read.

NOTHING IS EVER LOST TO A BAD CONNECTION
----------------------------------------
A report is written to a local queue first and only then sent. If the send
fails — no network, the server restarting, somebody on a train — the queue
keeps it and the next launch tries again. The user is told which of the two
happened, because "thanks, that's been sent" when it has not is worse than
saying nothing.

WHAT IS SENT, AND WHAT IS NOT
-----------------------------
The message, the category, and what `diagnostics()` lists: the version, the
platform, how many sounds are on the board, and the audio and speech settings.

**Never the board itself.** Not a file path, not a sound name, not a bank name,
not a track in the running order. A soundboard holds somebody's whole show and
the paths alone would say where they keep it. The feedback window reads back
exactly what will be sent before it sends it, so nobody has to take this
docstring's word for it.

`install_id()` is eight random hex characters made on this machine, so two
reports from the same copy can be recognised as such. It is not identity and
cannot be traced to a person by anyone, us included.
"""

from __future__ import annotations

import json
import os
import platform
import secrets
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import constants as C

ENDPOINT = "https://tgstudios.app/beta/feedback"
DONATE_URL = "https://tgstudios.app/donate/"
TIMEOUT_SECONDS = 20

#: The categories, in the order the box offers them. Tony's list.
TYPES = [
    ("accessibility", "Accessibility - hard to use with my screen reader"),
    ("bug", "Bug - something is broken or wrong"),
    ("suggestion", "Program suggestion - something you would like added"),
    ("audio", "Audio - devices, levels, ducking or the sound itself"),
    ("other", "Something else"),
]
TYPE_LABELS = dict(TYPES)

#: How long between one offer to donate and the next. Long enough that it is
#: not a nag, short enough to be seen by somebody who uses the app for months.
DONATE_INTERVAL_DAYS = 7
#: After somebody has actually gone to the donate page, they are left alone for
#: a good long while. They did the thing; asking again in a week is rude.
DONATE_THANKS_DAYS = 180
#: Nobody is asked on their first run. The app has to be worth something to
#: you before it asks you for anything.
DONATE_GRACE_DAYS = 7


def _state_dir():
    from .board import config_dir
    return config_dir()


def _read(name, default):
    path = os.path.join(_state_dir(), name)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _write(name, data):
    path = os.path.join(_state_dir(), name)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ identity
def install_id():
    """A random id for this copy, made on first use and kept."""
    data = _read("install.json", {})
    if isinstance(data.get("id"), str) and data["id"]:
        return data["id"]
    new_id = secrets.token_hex(4)
    _write("install.json", {"id": new_id})
    return new_id


def diagnostics(frame=None):
    """The context attached to every report. Small, and all of it declared."""
    info = {
        "product": C.APP_NAME,
        "version": C.APP_VERSION,
        "platform": "%s %s" % (platform.system(), platform.release()),
        "python": platform.python_version(),
    }
    if frame is None:
        return info
    # Settings and counts only. Never a name, never a path.
    try:
        board = frame.board
        info["sounds_assigned"] = board.assigned_count
        info["sounds_missing"] = len(board.missing_slots)
        info["folder_slots"] = len(board.folder_slots)
        info["banks_renamed"] = len(board.bank_names)
        info["playlist_tracks"] = len(board.playlist)
        info["playlist_crossfade"] = board.playlist.crossfade
        info["drops_in_library"] = len(board.drops)
        info["speech_level"] = board.speech_level
        info["ducking"] = bool(board.ducking)
        info["duck_db"] = board.duck_db
        info["bed_fade_in"] = board.bed_fade_in
        info["bed_fade_out"] = board.bed_fade_out
        info["global_hotkeys"] = bool(board.global_hotkeys_on)
    except Exception:
        pass
    try:
        info["audio_running"] = bool(frame.mixer.is_running)
        info["outputs"] = frame.mixer.distinct_device_count()
        info["samplerate"] = frame.mixer.samplerate
        info["mic_open"] = bool(frame.mic.is_open)
        info["mic_monitor"] = bool(frame.mic.monitor)
    except Exception:
        pass
    try:
        info["speech_available"] = bool(frame.speaker.available)
    except Exception:
        pass
    return info


def readable(report):
    """Exactly what will be sent, as lines a person can read back.

    The feedback window shows this. A window that says "diagnostics are
    attached" and does not say which is asking to be trusted rather than
    earning it.
    """
    lines = ["Category: %s" % report.get("type_label", report.get("type", "")),
             "", "Your message:", report.get("message", ""), "",
             "Sent with it:"]
    for key, value in sorted((report.get("diagnostics") or {}).items()):
        lines.append("  %s: %s" % (key.replace("_", " "), value))
    lines.append("  this copy: %s" % report.get("install", ""))
    lines.append("")
    lines.append("Nothing else. No file names, no sound names, no bank names, "
                 "and nothing from your running order.")
    return "\n".join(lines)


# --------------------------------------------------------------------- queue
QUEUE = "feedback_queue.json"


def _queue():
    data = _read(QUEUE, [])
    return data if isinstance(data, list) else []


def queued_count():
    return len(_queue())


def build(feedback_type, message, frame=None):
    """The report that would be sent, without sending or storing it."""
    return {
        "type": feedback_type,
        "type_label": TYPE_LABELS.get(feedback_type, feedback_type),
        "message": (message or "").strip(),
        "install": install_id(),
        "written_at": datetime.now(timezone.utc).isoformat(),
        "diagnostics": diagnostics(frame),
    }


def record(report):
    """Write a report to the queue, before any attempt to send it."""
    queue = _queue()
    queue.append(report)
    _write(QUEUE, queue)
    return report


def _post(report):
    body = json.dumps(report).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "%s/%s" % (C.APP_NAME.replace(" ", ""),
                                          C.APP_VERSION)})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return 200 <= response.status < 300


def flush():
    """Try to send everything queued. Returns (sent, still_queued).

    A report that will not send stays at the front and blocks the ones behind
    it, deliberately: they were written in order and read as a sequence.
    """
    queue = _queue()
    sent = 0
    while queue:
        try:
            if not _post(queue[0]):
                break
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            break
        queue.pop(0)
        sent += 1
        _write(QUEUE, queue)
    _write(QUEUE, queue)
    return sent, len(queue)


def flush_in_background():
    """Send anything queued without holding the app up at startup."""
    if not _queue():
        return None
    thread = threading.Thread(target=flush, daemon=True,
                              name="dropdeck-feedback")
    thread.start()
    return thread


def submit(feedback_type, message, frame=None):
    """Record and try to send. Returns (delivered, still_queued).

    ``delivered`` False is not something the user has to fix - the report is
    safely on disk and goes out on its own next time.
    """
    record(build(feedback_type, message, frame))
    sent, queued = flush()
    return bool(sent), queued


# ------------------------------------------------------------------- donating
DONATE_STATE = "donate.json"


def _now():
    return datetime.now(timezone.utc)


def _parse(text):
    try:
        stamp = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def donate_state():
    return _read(DONATE_STATE, {})


def should_ask_about_donating(now=None):
    """Is it time to mention donating. Returns True at most once a week.

    Three rules, all of them about not being a nuisance:

    * nobody is asked in their first week - the app has to have been worth
      something to you before it asks you for anything;
    * a week between asks, and the clock is reset whether the answer was yes
      or no, so declining is a real answer rather than a snooze;
    * and somebody who has been to the donate page is left alone for six
      months. They did the thing.
    """
    now = now or _now()
    state = donate_state()

    first = _parse(state.get("first_seen"))
    if first is None:
        # First launch. Start the clock and say nothing.
        _write(DONATE_STATE, dict(state, first_seen=now.isoformat()))
        return False
    if now - first < timedelta(days=DONATE_GRACE_DAYS):
        return False

    if state.get("never"):
        return False

    donated = _parse(state.get("donated_at"))
    if donated is not None and now - donated < timedelta(days=DONATE_THANKS_DAYS):
        return False

    asked = _parse(state.get("asked_at"))
    if asked is not None and now - asked < timedelta(days=DONATE_INTERVAL_DAYS):
        return False
    return True


def mark_asked(now=None):
    state = donate_state()
    _write(DONATE_STATE, dict(state, asked_at=(now or _now()).isoformat()))


def mark_donated(now=None):
    """They went to the page. Leave them alone for a long while."""
    now = now or _now()
    state = donate_state()
    _write(DONATE_STATE, dict(state, asked_at=now.isoformat(),
                              donated_at=now.isoformat()))


def mark_never(value=True):
    """Never again, if they ask for that. It has to be a real answer."""
    state = donate_state()
    _write(DONATE_STATE, dict(state, never=bool(value)))
