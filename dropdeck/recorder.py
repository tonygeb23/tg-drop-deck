"""Recording the show to a file.

Tony, 5 September 2026: "let's add a recording function to record in mp3 or
wav in custom formatting. saved to the documents folder of the user's computer
as Drop Deck Stream001 Drop Deck Stream002 so on."

It records the same mix that goes on air: every sound card, the running order,
and the microphone if it is on air. It does NOT record the cue before a track
ends or a preview, for the same reason those never reach the stream: they are
for the presenter, not for the show.

**Recording does not need you to be on air.** A show taped for later is the
ordinary case, and needing to be live to record one would be a strange rule.
When both are running they read from separate buses, so neither can take audio
away from the other.

WAV is written straight out with soundfile. Everything else goes through the
same encoder the stream uses, so a recording is exactly what a listener would
have heard, at the bitrate you chose.
"""
from __future__ import annotations

import os
import re
import threading
import time

import numpy as np
import soundfile as sf

from . import constants as C
from . import streamout

#: What a recording can be written as. WAV first, because it is the one to
#: pick when the recording is going into an editor afterwards.
FORMATS = [
    ("wav", "WAV, uncompressed"),
    ("mp3", "MP3"),
    ("aac", "AAC"),
    ("opus", "Ogg Opus"),
]
FORMAT_KEYS = [key for key, _label in FORMATS]
DEFAULT_FORMAT = "mp3"

EXTENSIONS = {"wav": ".wav", "mp3": ".mp3", "aac": ".aac", "opus": ".ogg"}

#: The stem of every file, with the number after it. Kept out of the code that
#: builds a name so it can be changed in one place.
STEM = "Drop Deck Stream "

IDLE = "not recording"
RECORDING = "recording"
FAILED = "failed"


def documents_folder():
    """Where Windows keeps Documents, whatever the user has moved it to.

    Asked of Windows rather than assumed. A machine where Documents has been
    redirected to OneDrive, which is most of them now, does not have one at
    the path that guessing would produce, and writing there would create a
    second Documents folder nobody looks in.
    """
    try:
        import ctypes
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        # CSIDL_PERSONAL is 5, and 0 means the current path rather than the
        # default one.
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
            if buf.value and os.path.isdir(buf.value):
                return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def default_folder():
    return os.path.join(documents_folder(), C.APP_NAME)


def next_path(folder, fmt=DEFAULT_FORMAT):
    """The next unused name, counting up from whatever is already there.

    Numbered rather than dated on purpose: Tony asked for 001, 002, and a
    number is easier to say on the phone than a timestamp. It looks at what is
    in the folder rather than keeping a counter, so deleting last week's
    recordings does not start it over the top of anything.
    """
    extension = EXTENSIONS.get(fmt, ".mp3")
    highest = 0
    pattern = re.compile(re.escape(STEM.strip()) + r"\s*(\d+)", re.I)
    try:
        for entry in os.listdir(folder):
            found = pattern.match(os.path.splitext(entry)[0])
            if found:
                highest = max(highest, int(found.group(1)))
    except OSError:
        pass
    return os.path.join(folder, "%s%03d%s" % (STEM, highest + 1, extension))


class Recorder:
    """Drains a bus onto the disk, on a thread of its own.

    The sound card is the clock here as it is for the stream: this waits for
    audio to arrive rather than running ahead on a timer, so a recording is
    exactly as long as the show was.
    """

    def __init__(self, bus, fmt=DEFAULT_FORMAT, bitrate=192, folder=None,
                 on_state=None, path=None):
        self.bus = bus
        self.fmt = fmt if fmt in FORMAT_KEYS else DEFAULT_FORMAT
        self.bitrate = int(bitrate)
        self.folder = folder or default_folder()
        self.on_state = on_state
        self.state = IDLE
        self.detail = ""
        self.path = path
        self.started_at = 0.0
        self.frames_written = 0
        self.bytes_written = 0
        self._thread = None
        self._stop = threading.Event()
        self._file = None
        self._encoder = None
        self._resampler = None
        self._handle = None

    # ------------------------------------------------------------- state --
    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def elapsed(self):
        """How long it has been recording, from the audio rather than a clock.

        Counted in frames written, so a machine that stalled for a moment
        reports the length of the file rather than the length of the wait.
        """
        if not self.frames_written:
            return 0.0
        return self.frames_written / float(self.bus.samplerate)

    def describe(self):
        if self.state != RECORDING:
            return "Not recording"
        minutes, seconds = divmod(int(self.elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        length = ("%d:%02d:%02d" % (hours, minutes, seconds) if hours
                  else "%d:%02d" % (minutes, seconds))
        size = self.bytes_written / (1024.0 * 1024.0)
        return ("Recording %s, %s, %.1f MB"
                % (os.path.basename(self.path or ""), length, size))

    def _set_state(self, state, detail=""):
        self.state, self.detail = state, detail
        if self.on_state is not None:
            try:
                self.on_state(state, detail)
            except Exception:
                pass

    # -------------------------------------------------------------- work --
    def start(self):
        """Open the file and begin. Returns True, or False with a reason."""
        if self.running:
            return True
        try:
            os.makedirs(self.folder, exist_ok=True)
        except OSError as exc:
            self._set_state(FAILED, "Could not make %s. %s" % (self.folder, exc))
            return False
        if self.path is None:
            self.path = next_path(self.folder, self.fmt)
        try:
            self._open()
        except Exception as exc:
            self._close()
            self._set_state(FAILED, "Could not start recording. %s" % exc)
            return False
        self._stop.clear()
        self.started_at = time.monotonic()
        self.frames_written = 0
        self.bytes_written = 0
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dropdeck-record")
        self._thread.start()
        self._set_state(RECORDING, self.path)
        return True

    def _open(self):
        if self.fmt == "wav":
            self._file = sf.SoundFile(
                self.path, mode="w", samplerate=int(self.bus.samplerate),
                channels=streamout.CHANNELS, subtype="PCM_16")
            return
        # Everything else rides the encoder the stream already uses, so what
        # is recorded is what a listener would have been sent.
        self._handle = open(self.path, "wb")
        self._encoder = streamout.Encoder(
            self._write_bytes, fmt=self.fmt,
            samplerate=self.bus.samplerate, bitrate=self.bitrate)
        self._resampler = streamout._Resampler(self.bus.samplerate,
                                               self._encoder.samplerate)

    def _write_bytes(self, data):
        if self._handle is None:
            return
        self._handle.write(data)
        self.bytes_written += len(data)

    def _run(self):
        chunk = max(256, int(self.bus.samplerate * C.STREAM_CHUNK_SECONDS))
        try:
            while not self._stop.is_set():
                if self.bus.available() < chunk:
                    if self._stop.wait(C.STREAM_POLL_SECONDS):
                        break
                    continue
                self._feed(self.bus.read(chunk))
            # Whatever is still in the ring belongs in the file. Stopping a
            # recording should not cost the last quarter second of it.
            left = self.bus.available()
            if left:
                self._feed(self.bus.read(left))
        except Exception as exc:                       # pragma: no cover
            self._set_state(FAILED, "Recording stopped. %s" % exc)
        finally:
            self._close()

    def _feed(self, block):
        if not len(block):
            return
        self.frames_written += len(block)
        if self._file is not None:
            self._file.write(block)
            # soundfile does not say how much it wrote, and the size on disk
            # is what somebody wants to be told.
            self.bytes_written = len(block) * streamout.CHANNELS * 2 \
                + self.bytes_written
            return
        if self._encoder is not None:
            out = self._resampler.feed(block)
            if len(out):
                self._encoder.feed(out)

    def _close(self):
        encoder, self._encoder = self._encoder, None
        if encoder is not None:
            try:
                encoder.close()
            except Exception:
                pass
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        wav, self._file = self._file, None
        if wav is not None:
            try:
                wav.close()
            except Exception:
                pass

    def stop(self, wait=True):
        """Finish the file. Returns where it is, or None if it never started."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=C.STREAM_STOP_TIMEOUT)
        self._close()
        if self.state == RECORDING:
            self._set_state(IDLE, self.path or "")
        try:
            if self.path and os.path.exists(self.path):
                self.bytes_written = os.path.getsize(self.path)
        except OSError:
            pass
        return self.path
