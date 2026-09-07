"""The camera: finding one, opening it, and reading it without stalling.

A camera is a picture source like the card is, and it answers the same
`frame(width, height)`. Everything difficult about it is in three places, and
all three were measured on 7 September 2026 rather than guessed.

**It reads on a thread of its own.** A camera delivers when it feels like it,
and the `Streamer` thread is carrying the audio. So the reader loops on its
own, keeps the last picture it got, and `frame()` hands back whatever that is.
A camera that stalls holds its last frame and the show carries on, which is the
same bargain the AirBus makes for sound cards.

**A camera is exclusive, and the error says nothing.** With OBS running, the
device opened, agreed to 1280x720, and then every read failed with
`OSError: [Errno 5] I/O error`, twenty seven times, no recovery. Camera privacy
consent was `Allow` at user and machine level, so permission was never the
problem. "I/O error" is no use to a presenter, so it is translated: the answer
is almost always that another program has it.

**Enumeration arrives in fragments.** FFmpeg emits the device list as partial
lines: `'"HP HD Camera"'`, then `' (video'`, then `')'`, then `'\\n'` as four
separate log records. A regex per record matches nothing and gives an empty
camera list, silently, which is the worst way for this to fail. Join every
record into one string, THEN split on newlines.
"""
from __future__ import annotations

import re
import threading
import time

import numpy as np

from . import constants as C
from .picture import PictureSource, _letterbox

try:
    import av
    import av.logging
except Exception:      # pragma: no cover - PyAV missing is a real state
    av = None


# ---------------------------------------------------------------------------
# Finding one
# ---------------------------------------------------------------------------

_DEVICE_LINE = re.compile(r'^"(.+)"\s+\((video|audio)\)$')
_SIZE_LINE = re.compile(r"min s=(\d+)x(\d+) fps=([\d.]+)\s+max s=(\d+)x(\d+) fps=([\d.]+)")


def _dshow_log(target, options):
    """Run a DirectShow listing and give back everything it printed.

    DirectShow answers these by logging and then refusing to open, so the
    exception is expected and the log is the actual answer.
    """
    if av is None:
        return ""
    try:
        av.logging.set_level(av.logging.INFO)
    except Exception:
        return ""
    try:
        with av.logging.Capture(local=False) as records:
            try:
                av.open(target, format="dshow", options=options)
            except Exception:
                pass
    except Exception:
        return ""
    # Joined first and split second. See the note at the top of the file.
    return "".join(message for _level, _name, message in records)


def cameras():
    """Every video capture device, by the name FFmpeg wants back."""
    found = []
    for line in _dshow_log("dummy", {"list_devices": "true"}).splitlines():
        match = _DEVICE_LINE.match(line.strip())
        if match and match.group(2) == "video":
            name = match.group(1)
            if name not in found:
                found.append(name)
    return found


def capabilities(device):
    """The sizes and rates one camera offers, biggest first.

    Used to fill the resolution list rather than offering sizes the camera
    cannot do and failing at the moment somebody goes live.
    """
    sizes = {}
    for line in _dshow_log("video=%s" % device, {"list_options": "true"}).splitlines():
        match = _SIZE_LINE.search(line)
        if not match:
            continue
        width, height = int(match.group(4)), int(match.group(5))
        fps = float(match.group(6))
        key = (width, height)
        sizes[key] = max(sizes.get(key, 0.0), fps)
    return [(w, h, fps) for (w, h), fps in
            sorted(sizes.items(), key=lambda item: -item[0][0] * item[0][1])]


def describe_size(width, height, fps=None):
    """A size said the way a person says it, not as a pair of numbers."""
    names = {(1920, 1080): "1080p", (1280, 720): "720p", (854, 480): "480p",
             (640, 480): "640 by 480", (640, 360): "360p"}
    label = names.get((width, height), "%d by %d" % (width, height))
    if fps:
        return "%s at %d frames a second" % (label, round(fps))
    return label


# ---------------------------------------------------------------------------
# Reading one
# ---------------------------------------------------------------------------

def explain(error, device=""):
    """FFmpeg's camera errors, turned into the thing to actually do.

    `I/O error` is what a camera another program already has gives back, and
    it is the common case by a distance: OBS, Teams and Zoom all hold a camera
    for as long as they are running.
    """
    text = str(error)
    name = device or "the camera"
    lowered = text.lower()
    if "could not find" in lowered or "no such" in lowered:
        return "%s is not there any more. It may have been unplugged" % name
    if "Errno 5" in text or "i/o error" in lowered:
        return ("%s could not be opened. Another program is probably using "
                "it: close OBS, Teams or Zoom and try again" % name)
    if "permission" in lowered or "Errno 13" in text or "denied" in lowered:
        return ("Windows would not allow access to %s. Turn the camera on for "
                "desktop apps in Privacy settings" % name)
    if "timed out" in lowered:
        return "%s did not respond" % name
    return "%s could not be opened" % name


class CameraError(RuntimeError):
    """Raised when a camera cannot be opened, with a sayable reason."""


class CameraSource(PictureSource):
    """One camera, read on its own thread, never blocking the caller."""

    kind = C.PICTURE_CAMERA

    def __init__(self, device, width=None, height=None, fps=None):
        self.device = device
        self.want_width = int(width or C.RTMP_WIDTH)
        self.want_height = int(height or C.RTMP_HEIGHT)
        self.want_fps = int(fps or C.RTMP_FPS)
        self.error = ""
        self.frames_read = 0
        self.width = 0
        self.height = 0

        self._container = None
        self._thread = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._latest = None
        self._latest_at = 0.0
        self._scaled = None
        self._scaled_key = None

    # ------------------------------------------------------------- opening --
    def start(self):
        if self._thread is not None:
            return self
        if av is None:
            self.error = "this copy cannot open a camera"
            raise CameraError(self.error)
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dropdeck-camera")
        self._thread.start()
        return self

    def wait_ready(self, timeout=None):
        """Block until the first frame or the failure. True when it worked.

        Opening measured at 0.58 seconds to the first frame on a real webcam,
        so this is not instant and must not be called on the UI thread.
        """
        self._ready.wait(timeout if timeout is not None else C.CAMERA_OPEN_TIMEOUT)
        return self._latest is not None

    def _open(self):
        options = {
            "video_size": "%dx%d" % (self.want_width, self.want_height),
            "framerate": str(self.want_fps),
            # Without this a camera that delivers faster than we drain fills
            # FFmpeg's own buffer and starts logging that it is dropping.
            "rtbufsize": C.CAMERA_BUFFER,
        }
        try:
            return av.open("video=%s" % self.device, format="dshow",
                           options=options)
        except Exception:
            # A camera that will not take the size asked for is still a camera.
            # Better a working picture at a size nobody chose than no picture.
            try:
                return av.open("video=%s" % self.device, format="dshow",
                               options={"rtbufsize": C.CAMERA_BUFFER})
            except Exception as exc:
                raise CameraError(explain(exc, self.device)) from exc

    def _run(self):
        try:
            container = self._open()
        except CameraError as exc:
            self.error = str(exc)
            self._ready.set()
            return
        self._container = container
        try:
            stream = container.streams.video[0]
            self.width = stream.width
            self.height = stream.height
            for frame in container.decode(video=0):
                if self._stop.is_set():
                    break
                picture = frame.to_ndarray(format="rgb24")
                with self._lock:
                    self._latest = picture
                    self._latest_at = time.monotonic()
                    self._scaled_key = None
                self.frames_read += 1
                self._ready.set()
        except Exception as exc:
            # This is where a camera taken by another program lands: the open
            # succeeds and the first read fails. Say the useful thing.
            if not self.error:
                self.error = explain(exc, self.device)
        finally:
            self._ready.set()
            # The reader has stopped, so the last frame is a photograph now
            # and must not be passed off as a camera feed.
            with self._lock:
                self._latest = None
                self._scaled = None
                self._scaled_key = None
            try:
                container.close()
            except Exception:
                pass
            self._container = None

    # ------------------------------------------------------------ pictures --
    @property
    def live(self):
        """Whether a frame has arrived recently enough to still be the truth."""
        with self._lock:
            if self._latest is None:
                return False
            return (time.monotonic() - self._latest_at) < C.CAMERA_STALE_SECONDS

    def latest(self):
        """The most recent frame at the camera's own size, or None."""
        with self._lock:
            return self._latest

    def frame(self, width, height):
        """The camera's picture at the size the encoder wants.

        Letterboxed rather than cropped. Filling the frame would mean cutting
        the edges off, and cutting the edges off a shot the presenter cannot
        see is how somebody ends up broadcasting their own forehead.
        """
        with self._lock:
            source = self._latest
            if source is None:
                return None
            # STALE IS THE SAME AS GONE. _latest used to be set once and never
            # cleared, so a camera unplugged twenty minutes into a show kept
            # handing back the same frozen picture for the rest of it: the
            # fallback never fired, nobody was told, and the framing kept
            # reporting a frozen shot as though it were live. Answering None
            # is what lets FallbackSource do its job.
            if (time.monotonic() - self._latest_at) > C.CAMERA_STALE_SECONDS:
                if not self.error:
                    self.error = ("%s stopped sending pictures"
                                  % (self.device or "the camera"))
                return None
            key = (width, height, id(source))
            if key == self._scaled_key and self._scaled is not None:
                return self._scaled
            canvas = np.empty((height, width, 3), dtype=np.uint8)
            canvas[:, :] = np.asarray(C.CARD_BACKGROUND, dtype=np.uint8)
            canvas = _letterbox(source, canvas)
            self._scaled = canvas
            self._scaled_key = key
            return canvas

    def describe(self):
        if self.error:
            return "a camera that could not be opened"
        if not self.frames_read:
            return "a camera that is still starting"
        return "%s at %s" % (self.device,
                             describe_size(self.width, self.height))

    def close(self):
        """Give the device back, and do not merely ask nicely.

        Closing the container is what actually releases a camera. Setting the
        stop flag only works if the reader is between frames; on a camera that
        has stopped delivering, decode() blocks and the thread never reaches
        its own cleanup. The device then stayed open for the life of the
        process, the light stayed on, and the NEXT attempt to go live was
        refused with "another program is probably using it". The other program
        was this one.
        """
        self._stop.set()
        container, self._container = self._container, None
        if container is not None:
            try:
                container.close()
            except Exception:
                pass          # closing under a blocked read is allowed to fail
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=C.CAMERA_STOP_TIMEOUT)
        with self._lock:
            self._latest = None
            self._scaled = None
            self._scaled_key = None
