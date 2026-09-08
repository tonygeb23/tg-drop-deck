"""What is on the computer screen, as a picture the stream can send.

The third kind of thing worth pointing a stream at, after a card and a camera.
A presenter demonstrating something, walking through a website, or showing a
piece of software wants the audience to see the screen, and until now the only
answer was "use OBS", which is the answer this app exists to avoid giving.

**Everything here is Windows GDI through ctypes, and that is deliberate.**
There is no new dependency: no mss, no dxcam, no Pillow grab, nothing added to
the installer. `proccapture.py` already talks to Windows this way for audio,
and the same reasoning applies. A capture library would be one more wheel to
bundle, one more thing to go missing in a frozen build, and one more licence.

## The one measurement that decides the design

**A desktop blit costs 16 to 33 ms and it BLOCKS**, measured 8 September 2026
on Tony's machine at 1920x1080. That is not the copy, which is trivial: it is
the Desktop Window Manager handing over a composited frame, so it is paced by
the display's own refresh and the cost is the same whether the destination is
1280x720 or 320x180. Measured: 16.5 ms median at 720p, 16.6 ms at 360p, 26 ms
at full size, with a p90 of 35 ms. `GetDIBits` after it is 0.4 ms.

At 30 fps the whole frame budget is 33.3 ms. So the capture cannot happen on
the thread that feeds the encoder: one slow blit would hold up the audio as
well, and `_pump_video` calls `frame()` inline on the streaming thread.

**So this reads on its own thread and hands back the last picture it got**,
exactly as `camera.py` does and for exactly the same reason. `frame()` takes a
lock, copies a reference and returns. It never waits for the screen.

## Why StretchBlt rather than grab-then-resize

The blit costs the same at any destination size, so scaling on the GDI side is
free and scaling afterwards is not: `GetDIBits` on a full 1920x1080 frame is
1.3 ms against 0.4 ms at 720p, and a `cv2.resize` after it is another 2.9 ms.
Blitting straight to the size the encoder wants skips both. `HALFTONE` and
`COLORONCOLOR` were measured against `cv2.INTER_AREA` and differ from it by
2.7 and 3.5 grey levels out of 255, so the cheap one is used.

## What this cannot capture

GDI sees the composited desktop, which is every ordinary window: a browser, a
document, a DAW, a screen reader's own display. It does **not** reliably see a
full screen exclusive game or a window that has opted out of capture, and
those come back black rather than raising. That is a real limit and the app
says so rather than shipping a black rectangle in silence, which is the whole
lesson of `camera.py`'s staleness rule.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

import numpy as np

from . import constants as C
from .picture import PictureSource, _letterbox

try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
except Exception:      # pragma: no cover - not Windows
    _user32 = _gdi32 = None


class ScreenError(Exception):
    """The screen could not be captured, in words worth hearing."""


# ---------------------------------------------------------------------------
# The Windows bits
# ---------------------------------------------------------------------------

_SRCCOPY = 0x00CC0020
#: Include layered windows. Measured at no extra cost (16.3 ms against 16.5),
#: and without it a window drawn with transparency can come back missing.
_CAPTUREBLT = 0x40000000
_COLORONCOLOR = 3

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3)]


def available():
    """Whether this machine can be captured at all."""
    return _user32 is not None and _gdi32 is not None


def why_unavailable():
    if available():
        return ""
    return "this copy cannot capture the screen"


def screens():
    """What can be captured, widest first.

    Two entries at most and usually two: the whole desktop, and the main
    screen on its own. Per monitor enumeration is deliberately not offered.
    A presenter who cannot see the screens cannot be asked which of
    "monitor 2" and "monitor 3" they meant, and the honest choice is between
    "everything" and "the one Windows calls the main one".
    """
    if not available():
        return []
    out = []
    try:
        width = _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
        height = _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
        main_w = _user32.GetSystemMetrics(_SM_CXSCREEN)
        main_h = _user32.GetSystemMetrics(_SM_CYSCREEN)
    except Exception:
        return []
    if width and height:
        out.append((C.SCREEN_ALL, "Everything on my screens",
                    int(width), int(height)))
    if main_w and main_h and (main_w != width or main_h != height):
        out.append((C.SCREEN_MAIN, "My main screen only",
                    int(main_w), int(main_h)))
    return out


def _bounds(which):
    """Where to capture from, as (left, top, width, height)."""
    if which == C.SCREEN_MAIN:
        return (0, 0,
                int(_user32.GetSystemMetrics(_SM_CXSCREEN)),
                int(_user32.GetSystemMetrics(_SM_CYSCREEN)))
    return (int(_user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)),
            int(_user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)),
            int(_user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)),
            int(_user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)))


def _fit(source_w, source_h, box_w, box_h):
    """The biggest box_w by box_h rectangle keeping the source's shape."""
    if source_w <= 0 or source_h <= 0:
        return max(1, box_w), max(1, box_h)
    scale = min(box_w / float(source_w), box_h / float(source_h))
    return (max(1, int(round(source_w * scale))),
            max(1, int(round(source_h * scale))))


class _Grabber:
    """One set of GDI handles, reused. Freed once, in close()."""

    def __init__(self, width, height):
        self.width = int(width)
        self.height = int(height)
        self._desktop = _user32.GetDC(None)
        if not self._desktop:
            raise ScreenError("Windows would not hand over the screen")
        self._memory = _gdi32.CreateCompatibleDC(self._desktop)
        self._bitmap = _gdi32.CreateCompatibleBitmap(
            self._desktop, self.width, self.height)
        if not self._memory or not self._bitmap:
            self.close()
            raise ScreenError("Windows would not hand over the screen")
        _gdi32.SelectObject(self._memory, self._bitmap)
        _gdi32.SetStretchBltMode(self._memory, _COLORONCOLOR)
        _gdi32.SetBrushOrgEx(self._memory, 0, 0, None)
        self._info = _BITMAPINFO()
        self._info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        self._info.bmiHeader.biWidth = self.width
        # Negative, so the rows arrive top down and nothing has to be flipped.
        self._info.bmiHeader.biHeight = -self.height
        self._info.bmiHeader.biPlanes = 1
        self._info.bmiHeader.biBitCount = 32
        self._info.bmiHeader.biCompression = 0
        self._buffer = ctypes.create_string_buffer(self.width * self.height * 4)

    def grab(self, left, top, source_w, source_h):
        """One frame, as RGB. None when Windows refused."""
        ok = _gdi32.StretchBlt(self._memory, 0, 0, self.width, self.height,
                               self._desktop, left, top, source_w, source_h,
                               _SRCCOPY | _CAPTUREBLT)
        if not ok:
            return None
        got = _gdi32.GetDIBits(self._memory, self._bitmap, 0, self.height,
                               self._buffer, ctypes.byref(self._info), 0)
        if not got:
            return None
        raw = np.frombuffer(self._buffer, dtype=np.uint8)
        raw = raw.reshape(self.height, self.width, 4)
        # BGRA to RGB, and a copy because the buffer is written again next
        # time round and the streaming thread may still be holding this one.
        return np.ascontiguousarray(raw[:, :, 2::-1])

    def close(self):
        for handle, free in ((getattr(self, "_bitmap", None),
                              _gdi32.DeleteObject),
                             (getattr(self, "_memory", None),
                              _gdi32.DeleteDC)):
            if handle:
                try:
                    free(handle)
                except Exception:
                    pass
        desktop = getattr(self, "_desktop", None)
        if desktop:
            try:
                _user32.ReleaseDC(None, desktop)
            except Exception:
                pass
        self._bitmap = self._memory = self._desktop = None


# ---------------------------------------------------------------------------
# The source
# ---------------------------------------------------------------------------

class ScreenSource(PictureSource):
    """The desktop, read on its own thread, never blocking the caller."""

    kind = C.PICTURE_SCREEN

    def __init__(self, which="", width=None, height=None, fps=None):
        self.which = which or C.SCREEN_ALL
        self.want_width = int(width or C.RTMP_WIDTH)
        self.want_height = int(height or C.RTMP_HEIGHT)
        self.want_fps = int(fps or C.RTMP_FPS)
        self.error = ""
        self.frames_read = 0
        self.width = 0
        self.height = 0

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
        if not available():
            self.error = why_unavailable()
            raise ScreenError(self.error)
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dropdeck-screen")
        self._thread.start()
        return self

    def wait_ready(self, timeout=None):
        """Block until the first frame or the failure. True when it worked."""
        self._ready.wait(timeout if timeout is not None
                         else C.SCREEN_OPEN_TIMEOUT)
        with self._lock:
            return self._latest is not None

    # ------------------------------------------------------------ the loop --
    def _run(self):
        grabber = None
        try:
            left, top, source_w, source_h = _bounds(self.which)
            if source_w <= 0 or source_h <= 0:
                raise ScreenError("Windows reported no screen to capture")
            # Captured at the shape of the screen, scaled to fit inside what
            # the encoder wants. The letterbox in frame() then only has to
            # paste, which keeps the streaming thread's share near nothing.
            grab_w, grab_h = _fit(source_w, source_h,
                                  self.want_width, self.want_height)
            grabber = _Grabber(grab_w, grab_h)
            self.width, self.height = source_w, source_h
            interval = 1.0 / float(max(1, self.want_fps))
            blank = 0
            while not self._stop.is_set():
                started = time.monotonic()
                picture = grabber.grab(left, top, source_w, source_h)
                if picture is None:
                    blank += 1
                    if blank >= C.SCREEN_REFUSED_LIMIT and not self.error:
                        self.error = "Windows stopped handing over the screen"
                    # Nothing is stored, so the frame goes stale and the card
                    # takes over. A blank rectangle is not a picture.
                else:
                    blank = 0
                    with self._lock:
                        self._latest = picture
                        self._latest_at = time.monotonic()
                        self._scaled_key = None
                    self.frames_read += 1
                    self._ready.set()
                # The blit is already paced by the compositor, so this only
                # gives time back when the screen is handing frames over
                # faster than the stream needs them.
                left_over = interval - (time.monotonic() - started)
                if left_over > 0 and self._stop.wait(left_over):
                    break
        except ScreenError as exc:
            self.error = str(exc)
        except Exception as exc:      # pragma: no cover - defensive
            self.error = "the screen could not be captured: %s" % exc
        finally:
            if grabber is not None:
                grabber.close()
            # A dead reader must not go on handing out a photograph of the
            # screen as it was. Same rule as the camera, same reason.
            with self._lock:
                self._latest = None
                self._scaled = None
                self._scaled_key = None
            self._ready.set()

    # ------------------------------------------------------------ pictures --
    @property
    def live(self):
        with self._lock:
            if self._latest is None:
                return False
            return (time.monotonic() - self._latest_at) < C.SCREEN_STALE_SECONDS

    def latest(self):
        """The most recent capture, or None."""
        with self._lock:
            return self._latest

    def frame(self, width, height):
        with self._lock:
            source = self._latest
            if source is None:
                return None
            if (time.monotonic() - self._latest_at) > C.SCREEN_STALE_SECONDS:
                if not self.error:
                    self.error = "the screen stopped being handed over"
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
            return "a screen that could not be captured"
        if not self.frames_read:
            return "the screen, still starting"
        for value, label, _w, _h in screens():
            if value == self.which:
                return "%s at %d by %d" % (label.lower(),
                                           self.width, self.height)
        return "the screen at %d by %d" % (self.width, self.height)

    def close(self):
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=C.SCREEN_STOP_TIMEOUT)
        with self._lock:
            self._latest = None
            self._scaled = None
            self._scaled_key = None


class SplitSource(PictureSource):
    """The screen, with the camera inset in a corner of it.

    **The screen gets the whole frame and the camera is the inset, rather than
    the two side by side, and that was measured rather than chosen.** A 1280
    wide stream split in half leaves the screen 640 pixels across, and a
    1920x1080 desktop at 640 wide is not small text, it is no text: body copy
    turns to a grey smear and headings are barely shapes. Measured 8 September
    2026 by rendering a real desktop at each width. At the full 1280 the same
    screen reads perfectly.

    So the choice is between a legible screen with a small presenter on it and
    an illegible screen with a large one, and a screen nobody can read is not
    worth sending. If side by side is ever wanted it needs a 1920 wide stream,
    where each half is 960 and the text survives.

    Either half may fail on its own. A camera taken by another program leaves
    the screen filling the frame, which is a working show; the screen failing
    is what takes this source down to the card.
    """

    kind = C.PICTURE_SPLIT

    def __init__(self, screen, camera):
        self.screen = screen
        self.camera = camera
        self.error = ""
        #: Whether the last frame really had the camera in it. describe() used
        #: to ask the camera to describe itself, which a camera handing back
        #: nothing will still do perfectly cheerfully, so the status line
        #: claimed a camera in the corner of a picture that had none.
        self.showing_camera = False

    def start(self):
        # The screen is the one that has to work. A camera that refuses is
        # reported and the show goes on with the screen alone, because that is
        # still the thing the audience came to look at.
        self.screen.start()
        try:
            self.camera.start()
        except Exception as exc:
            self.error = str(exc)
        return self

    def wait_ready(self, timeout=None):
        ready = self.screen.wait_ready(timeout)
        try:
            self.camera.wait_ready(timeout)
        except Exception:
            pass
        return ready

    def frame(self, width, height):
        canvas = self.screen.frame(width, height)
        if canvas is None:
            return None
        inset = self._inset(width, height)
        self.showing_camera = inset is not None
        if inset is None:
            return canvas
        picture, box = inset
        left, top, box_w, box_h = box
        # The screen source caches the array it hands back and would otherwise
        # be given the camera painted into it for ever.
        canvas = canvas.copy()
        edge = C.SPLIT_INSET_BORDER
        canvas[max(0, top - edge):top + box_h + edge,
               max(0, left - edge):left + box_w + edge] = np.asarray(
                   C.CARD_ACCENT, dtype=np.uint8)
        canvas[top:top + box_h, left:left + box_w] = picture
        return canvas

    def _inset(self, width, height):
        """The camera, at inset size, and where it goes. None when it cannot."""
        box_w = max(2, int(round(width * C.SPLIT_INSET_WIDTH)))
        box_h = max(2, int(round(box_w * height / float(max(1, width)))))
        try:
            picture = self.camera.frame(box_w, box_h)
        except Exception:
            return None
        if picture is None:
            return None
        margin_x = int(round(width * C.SPLIT_INSET_MARGIN))
        margin_y = int(round(height * C.SPLIT_INSET_MARGIN))
        left = max(0, width - box_w - margin_x)
        top = max(0, height - box_h - margin_y)
        return picture, (left, top, box_w, box_h)

    def latest(self):
        """The camera's own frame, for the framing checker.

        The one part of this source that a face detector wants: the raw
        camera picture at its own size, NOT the composite, which is mostly
        screen and would have the presenter at a quarter of the width in the
        corner of it. `_framing_loop` looks for this method by name.
        """
        getter = getattr(self.camera, "latest", None)
        return getter() if getter is not None else None

    def describe(self):
        camera = ""
        try:
            camera = self.camera.describe()
        except Exception:
            camera = ""
        if not camera or not self.showing_camera or getattr(
                self.camera, "error", ""):
            return "%s, with no camera" % self.screen.describe()
        return "%s, with %s in the corner" % (self.screen.describe(), camera)

    def close(self):
        for part in (self.camera, self.screen):
            try:
                part.close()
            except Exception:
                pass
