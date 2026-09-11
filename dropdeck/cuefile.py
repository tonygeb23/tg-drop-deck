"""A .cue tracklist written beside a recording, as the show goes out.

Tyler McClain, 10 September 2026, clarifying a request after 3.7.0 had already
shipped a live cue sheet window, which turned out not to be what he meant:

    "i'm talking about adding the ability to let it write a .cue file with the
    title, artist, and when it was played, like 0:00 or something. where people
    can have a .cue sheet right in the recordings folder with the same file
    name, like if they want to post it to mixcloud or something like that."

So: `Drop Deck Stream 004.mp3` gets `Drop Deck Stream 004.cue` beside it,
holding every track that went out and the moment it started, measured from the
top of the recording. Upload the pair to Mixcloud, or open the cue in anything
that reads one, and the tracklist is already done.

**This is a different feature from `cuesheet.py`.** That one is the window on
`Ctrl+Shift+C` showing what is coming UP. This one is the file recording what
has already GONE OUT. They share a word and nothing else.

## The clock, which is the only hard part

**Timestamps come from the recording's own sample count, never from a wall
clock.** `recorder.Recorder.elapsed` and `videorecord.VideoRecorder.
audio_seconds` are both frames written divided by the sample rate, for exactly
this reason: if the machine stalls for a moment, the file is shorter than the
wall clock says, and a tracklist timed against the wall would drift away from
the audio it describes. Ask the recorder where it has got to, and the mark
lands where the music really is.

## Written as it goes, not at the end

A three hour show that crashes at hour two should still have a tracklist for
the two hours it got. Every track appends and flushes, so the file on disk is
always complete up to the last thing that played. That is the same reasoning
the recording itself uses, where a fragmented MP4 costs one second rather than
everything.

## The format, and the one bit everybody gets wrong

`INDEX 01 mm:ss:ff`, and **ff is frames at seventy five per second**, not
hundredths and not milliseconds. It is a CD sector, which is what the format
was invented for. Half a second is 37.5 frames, so it lands on `38`, and
never on the `50` that hundredths would give.
"""
from __future__ import annotations

import os
import threading

#: What a .cue may call the audio it points at. Anything not in here is
#: written as WAVE, which every reader accepts and none of them chokes on.
FILE_TYPES = {".wav": "WAVE", ".mp3": "MP3", ".aiff": "AIFF", ".aif": "AIFF"}
DEFAULT_FILE_TYPE = "WAVE"

#: Frames per second in a .cue timestamp. A CD sector, not a video frame.
FRAMES_PER_SECOND = 75

EXTENSION = ".cue"


def file_type(path):
    """What to call this audio file in a FILE line."""
    return FILE_TYPES.get(os.path.splitext(path or "")[1].lower(),
                          DEFAULT_FILE_TYPE)


def timestamp(seconds):
    """Seconds to mm:ss:ff, where ff is seventy fifths of a second.

    Minutes are not wrapped at sixty. A two hour show's last track is at
    `119:58:00`, which is what the format means and what readers expect; a
    tracklist that restarted its clock every hour would be unusable.
    """
    seconds = max(0.0, float(seconds or 0.0))
    whole = int(seconds)
    frames = int(round((seconds - whole) * FRAMES_PER_SECOND))
    if frames >= FRAMES_PER_SECOND:          # rounding up on the boundary
        frames = 0
        whole += 1
    minutes, secs = divmod(whole, 60)
    return "%02d:%02d:%02d" % (minutes, secs, frames)


def quoted(text):
    """A .cue string, safely.

    The format has no escape for a double quote, so one is turned into a
    single. A title with a quote in it is rare and a file that will not parse
    is not.
    """
    text = (text or "").replace('"', "'").replace("\r", " ").replace("\n", " ")
    return '"%s"' % text.strip()


def render(audio_name, entries):
    """The whole file, as text. Pure, so every rule above is testable."""
    lines = ["FILE %s %s" % (quoted(audio_name), file_type(audio_name))]
    for number, entry in enumerate(entries, start=1):
        title, performer, seconds = entry
        lines.append("  TRACK %02d AUDIO" % number)
        lines.append("    TITLE %s" % quoted(title or "Untitled"))
        if performer:
            lines.append("    PERFORMER %s" % quoted(performer))
        lines.append("    INDEX 01 %s" % timestamp(seconds))
    return "\n".join(lines) + "\n"


def path_for(audio_path):
    """Where the .cue goes: beside the audio, same stem."""
    if not audio_path:
        return None
    return os.path.splitext(audio_path)[0] + EXTENSION


class CueFile:
    """The tracklist for one recording, kept up to date on disk.

    ``audio_path`` is the recording it describes. Nothing is written until the
    first track is added, so a recording with no running order behind it does
    not litter the folder with an empty file.
    """

    def __init__(self, audio_path):
        self.audio_path = audio_path
        self.path = path_for(audio_path)
        self.entries = []
        self.last_error = None
        self._lock = threading.Lock()

    def add(self, title, performer="", seconds=0.0):
        """One track went out. Returns True if the file was written.

        Never raises. A tracklist that cannot be written is worth saying
        something about later, and is never worth taking a show down for.
        """
        with self._lock:
            # The same track twice at the same moment is a double press, not
            # two plays. The timestamp is what tells them apart.
            entry = (title or "", performer or "", max(0.0, float(seconds or 0.0)))
            if self.entries and self.entries[-1] == entry:
                return False
            self.entries.append(entry)
            return self._write()

    def _write(self):
        if not self.path:
            return False
        try:
            name = os.path.basename(self.audio_path or "")
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(render(name, self.entries))
                # Flushed every time, so the file on disk is always complete
                # up to the last track. A show that crashes at hour two keeps
                # its first two hours of tracklist.
                handle.flush()
                os.fsync(handle.fileno())
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def describe(self):
        """One line about what was written, for the end of a recording."""
        if not self.entries:
            return ""
        if self.last_error:
            return ("The track list could not be written. %s"
                    % self.last_error)
        return ("%d %s in the track list beside it"
                % (len(self.entries),
                   "track" if len(self.entries) == 1 else "tracks"))
