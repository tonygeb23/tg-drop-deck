"""One picture pipeline, however many things want to look at it.

Tony, 12 September 2026: "when recording video, it should not send out a
still freeze frame of the radio show title... if visual streaming is being
done, it should default to what's being captured, camera + screen, just
camera, whatever is selected. none of this still frame of a radio show. that
is different. ice cast, shoucast, is not the same as facebook and youtube."

He was right twice over, and the second half is the architecture.

## What went wrong, and why a wrapper had to exist

Four separate things in this app want the picture: the RTMP stream, the file
recording (3.7.0), the preview behind the shot check, and the framing watcher.
Before this module each of them **built its own** with `picture.build`, and
that had already produced three faults, every one silent:

1. `ui._record_picture_run` built a source and **never called `start()`**. The
   capture threads live behind `start()`, so `frame()` answered None for ever
   and `FallbackSource` substituted the card. Measured against Tony's own
   board on 12 September 2026: 175 frames in six seconds, mean pixel
   difference from a freshly drawn card **zero**. A recording of a card with
   his station name on it, which is exactly what he reported.
2. A recording made while live was supposed to take the frames the encoder was
   already sending. It asked `getattr(streamer, "destination", None)` and the
   attribute is `_destination`, so that path **never ran once**. What ran
   instead was a second pipeline, opening a second camera on a device
   DirectShow hands to one owner at a time.
3. Nothing had a way to change the picture for a recording, because
   `set_video_source` only spoke to the streamer.

A second copy of a pipeline is not a performance problem, it is a
CORRECTNESS problem: **a camera has one owner.** So there is one source here,
reference counted, and everybody reads the same frames.

## The rules, all of them learned the hard way somewhere else in this app

- **Start on the first taker, close on the last.** Not on the last *stop*: a
  preview must never be able to close the camera out from under a live show,
  and a recording that ends must not take the stream's picture with it.
- **The new source goes in BEFORE the old one comes out.** A camera is about
  six tenths of a second to its first frame, and closing first puts a card on
  the air for that six tenths. Same rule as `ui.set_video_source`, and the
  reason is the same.
- **`frame()` never raises**, because the RTMP pump and the recorder both call
  it on a thread carrying audio.
- **The title survives a rebuild.** A card built mid show with no title on it
  says nothing until the next track change, which on an album side is a
  quarter of an hour. `Streamer.set_video_source` carries the same scar.
- **A fallback is announced once, and it names what it affects.** "The stream
  is showing a card instead" is the wrong sentence when nothing is streaming
  and the card is going into a file.

This module imports no wx and touches no board, which is what makes every
rule above testable one at a time. Settings arrive through a callable so a
rebuild always reads what is true NOW, not what was true when the feed
was made.
"""
from __future__ import annotations

import threading

from . import constants as C
from . import picture

#: What a taker is called, for `describe_holders` and so a message can say
#: which of them a card is standing in for. Plain words: they are spoken.
FOR_STREAM = "the stream"
FOR_RECORDING = "the recording"
FOR_PREVIEW = "a preview"


class PictureFeed:
    """The one picture source, shared by everything that wants a frame.

    Duck typed as a `picture.PictureSource` on purpose: `RtmpDestination`
    takes this as its `video_source` and calls `frame`, `describe`, `kind`
    and `set_title` on it without knowing the difference. That is what lets a
    source swap reach the stream, the recording and the framing watcher at
    once, and what makes the swap survive a reconnect: the destination is
    rebuilt holding the same feed rather than a snapshot of a source.
    """

    def __init__(self, settings_for, on_fallback=None, on_change=None):
        #: Callable answering the PICTURE settings dict, read afresh on every
        #: build. `ui._picture_settings` is the one that matters: asking the
        #: DESTINATION for picture settings is what put a card in front of
        #: the shot check on 8 September.
        self._settings_for = settings_for
        self._on_fallback = on_fallback or (lambda reason: None)
        self._on_change = on_change or (lambda: None)
        #: RLock, not Lock: `rebuild` holds it and calls `_open`, and a
        #: fallback arriving from a capture thread lands in `_fell_back`.
        self._lock = threading.RLock()
        self._source = None
        #: {name: how many hold it}. A COUNT, not a set, because the names
        #: are not unique: two previews at once (the shot check and
        #: Ctrl+Shift+F, say) both call themselves "a preview", so a list of
        #: names de-duplicated them into one entry and the first release
        #: closed the camera under the second. Same lesson as the mix minus
        #: naming rule in CLAUDE.md: a name that matches is not a count.
        self._holders = {}
        self._title = ""
        #: The reason the card is standing in, or "" when it is not. Read by
        #: the UI to say something true about a recording's picture.
        self.reason = ""
        self._built_from = {}
        self.builds = 0
        #: How many frames have been asked of it. Nought means nothing has
        #: looked yet, which is different from a fallback and must not be
        #: reported as one: at the moment a recording starts there is no
        #: answer to "is the camera working" and claiming a card is a lie in
        #: the alarming direction.
        self.frames_asked = 0

    # -------------------------------------------------------- who wants it --
    def acquire(self, who, ready_timeout=None):
        """Somebody wants the picture. Opens it if nobody had it yet.

        Returns self, so a caller can hand it straight to a destination.
        ``ready_timeout`` waits for the real source rather than the card
        standing in for it while a camera opens; None does not wait, which is
        right for going live, where the fallback covers the first half second
        and blocking the key press does not.
        """
        with self._lock:
            fresh = not self._holders
            self._holders[who] = self._holders.get(who, 0) + 1
            # OPENED IF NOBODY HAD IT, and ALSO if what is open was built
            # for different settings. A momentary preview holds the feed, so
            # going live or starting a recording while one is in flight used
            # to be handed the preview's source: built from the settings of
            # a moment ago, which is how a picture chosen in between would
            # have been silently ignored. Cheap: a dict comparison.
            if fresh or self._stale():
                self._open()
            source = self._source
        if ready_timeout and source is not None:
            waiter = getattr(source, "wait_ready", None)
            if waiter is not None:
                try:
                    waiter(ready_timeout)
                except Exception:
                    pass
        return self

    def release(self, who):
        """One taker lets go. The source closes when the last one does.

        Closing is done OUTSIDE the lock, because `CameraSource.close` joins
        its capture thread and that thread can be inside `_fell_back` wanting
        the same lock.
        """
        doomed = None
        with self._lock:
            left = self._holders.get(who, 0) - 1
            if left > 0:
                self._holders[who] = left
            else:
                self._holders.pop(who, None)
            if not self._holders:
                doomed, self._source = self._source, None
        if doomed is not None:
            _shut(doomed)
        return self

    def close(self):
        """Everybody lets go. For shutdown, where politeness is not the point."""
        with self._lock:
            self._holders = {}
            doomed, self._source = self._source, None
        if doomed is not None:
            _shut(doomed)

    @property
    def running(self):
        with self._lock:
            return self._source is not None

    def holders(self):
        """The names holding it, once each however many times over."""
        with self._lock:
            return list(self._holders)

    def held_by(self, who):
        with self._lock:
            return self._holders.get(who, 0) > 0

    def describe_holders(self):
        """"the stream and the recording", for a sentence about a fault."""
        names = self.holders()
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        return "%s and %s" % (", ".join(names[:-1]), names[-1])

    # ------------------------------------------------------------ pictures --
    def frame(self, width, height):
        """The picture, at the size asked for. None only when nothing holds it.

        Never raises: this is called from the RTMP pump and from the
        recorder's picture thread, and a source that throws must not be able
        to end a broadcast or a recording.
        """
        # NO LOCK. This is called from `RtmpDestination._pump_video`, which
        # is the thread carrying the audio, and `rebuild` holds the lock
        # across `_open`, which starts a camera. Waiting on that lock would
        # put a camera's open time into the audio path, which is the one
        # thing `screen.py`'s whole design exists to avoid.
        #
        # Safe without one because `_source` is a single attribute: this
        # either gets the old source or the new one and never a half swapped
        # pair, and both are valid objects because the new one is started
        # before it is published and the old one is closed after. The same
        # argument `RtmpDestination.set_video_source` already makes, and
        # `frames_asked` is a counter for a sentence, not a decision.
        source = self._source
        if source is None:
            return None
        self.frames_asked += 1
        try:
            return source.frame(width, height)
        except Exception:
            return None

    def wait_ready(self, timeout=None):
        """Wait for the REAL source, not the card standing in for it.

        Delegated to the primary through `FallbackSource.wait_ready`, because
        the backup is a card and a card is ready the moment it exists.

        Worth waiting for on any thread that is not the UI's. A capture
        thread takes a moment to produce its first frame (a camera about six
        tenths of a second, a screen one compositor tick), and whoever asks
        first gets None. None is not "not yet" to `FallbackSource`: it is a
        failure, it swaps to the card, and it does not look again for
        `C.PICTURE_RETRY_SECONDS`. So one early question costs five seconds
        of card and an announcement saying the picture stopped.
        """
        with self._lock:
            source = self._source
        if source is None:
            return False
        waiter = getattr(source, "wait_ready", None)
        if waiter is None:
            return True
        try:
            return bool(waiter(timeout))
        except Exception:
            return False

    def latest(self):
        """The raw camera frame, at its own size, for the framing watcher.

        Through the fallback to the primary, because what a face detector
        wants is the camera and not the card standing in for it. `SplitSource`
        answers this with the camera rather than the composite, which is the
        whole reason the method exists.
        """
        with self._lock:
            source = self._source
        for candidate in (source, getattr(source, "primary", None)):
            getter = getattr(candidate, "latest", None)
            if getter is not None:
                try:
                    return getter()
                except Exception:
                    return None
        return None

    @property
    def kind(self):
        """What is really being shown, which `_moving` asks before calling a
        picture frozen. A card IS frozen and must never be reported as stuck."""
        with self._lock:
            source = self._source
        if source is None:
            return ""
        if getattr(source, "fallen_back", False):
            return C.PICTURE_CARD
        return getattr(source, "kind", "")

    @property
    def chosen(self):
        """What the user ASKED for, fallback or not. For saying what is set up."""
        try:
            settings = self._settings_for() or {}
        except Exception:
            return ""
        return settings.get("picture", "") or ""

    @property
    def fallen_back(self):
        with self._lock:
            return bool(getattr(self._source, "fallen_back", False))

    def describe(self):
        with self._lock:
            source = self._source
        if source is None:
            return ""
        try:
            return source.describe() or ""
        except Exception:
            return ""

    def set_title(self, title):
        """What is playing, for the card. Remembered for the next build."""
        with self._lock:
            self._title = title or ""
            source = self._source
        setter = getattr(source, "set_title", None)
        if setter is not None:
            try:
                setter(title)
            except Exception:
                pass

    def set_corner(self, corner):
        """Move a split's camera inset, with no rebuild at all.

        `SplitSource._inset` reads `self.corner` on every frame, so there
        was never anything to rebuild: the corner used to go through
        `set_video_source`, which closes and reopens the camera. Measured by
        Mark, walking the four corners with the arrow keys opened the camera
        five times and blocked the UI thread for up to 0.32 seconds an
        arrow, putting card on the air each time.

        False when the live source is not a split, so the caller can fall
        back to a rebuild rather than silently doing nothing.
        """
        source = self._source
        target = getattr(source, "primary", source)
        if target is None or not hasattr(target, "corner"):
            return False
        try:
            target.corner = corner
        except Exception:
            return False
        return True

    # ------------------------------------------------------------- rebuild --
    def rebuild(self, ready_timeout=None):
        """The settings changed. Swap the source under everybody watching.

        Returns True when a swap happened, False when nothing holds the feed,
        and raises nothing: a camera that will not open comes back as the card
        through `FallbackSource`, which is the same answer a fresh build gives.

        The old source is closed AFTER the new one is in place and outside the
        lock, for the two reasons in this module's docstring.
        """
        with self._lock:
            if not self._holders:
                return False
            old = self._source
            self._open()
            source = self._source
        if ready_timeout and source is not None:
            waiter = getattr(source, "wait_ready", None)
            if waiter is not None:
                try:
                    waiter(ready_timeout)
                except Exception:
                    pass
        if old is not None and old is not source:
            _shut(old)
        try:
            self._on_change()
        except Exception:
            pass
        return True

    def _stale(self):
        """Whether what is open was built for settings that have changed."""
        if self._source is None:
            return True
        try:
            return dict(self._settings_for() or {}) != self._built_from
        except Exception:
            return False

    def _open(self):
        """Build and start one source. Called holding the lock."""
        settings = {}
        try:
            settings = self._settings_for() or {}
        except Exception:
            settings = {}
        #: What this source was built from, so a later taker can tell
        #: whether it is still the picture that was asked for.
        self._built_from = dict(settings)
        self.reason = ""
        # The callback is bound to THIS source. The old one is closed after
        # the swap and its capture threads can fire on_fallback on the way
        # out, which used to write "the camera stopped" over a brand new and
        # perfectly healthy source, and announce it.
        holder = []
        source = picture.build(
            settings,
            on_fallback=lambda reason: self._fell_back(reason, holder[0]))
        holder.append(source)
        self._source = source
        self.builds += 1
        self.frames_asked = 0
        if self._title:
            setter = getattr(source, "set_title", None)
            if setter is not None:
                try:
                    setter(self._title)
                except Exception:
                    pass
        # start() is the whole reason this module exists. Everything below
        # frame() is a thread, and a source that was never started answers
        # None for ever while looking perfectly healthy.
        try:
            source.start()
        except Exception as exc:
            self.reason = str(exc)

    def _fell_back(self, reason, source=None):
        """`FallbackSource` has swapped to the card, or come back off it.

        Arrives on whichever thread noticed, so it records the reason under
        the lock and hands the sentence on. The sentence names the takers,
        because "the stream is showing a card" is a lie when the card is
        going into a file.

        ``source`` is the source that is reporting. A source that has
        already been replaced is IGNORED: `rebuild` closes the old one after
        the swap, its capture threads can fall back on the way out, and that
        used to write a stale reason over a healthy new source and announce
        it to the presenter.
        """
        if source is not None and source is not self._source:
            return
        with self._lock:
            self.reason = "" if _is_recovery(reason) else (reason or "")
        try:
            self._on_fallback(reason)
        except Exception:
            pass


def _is_recovery(reason):
    """`FallbackSource` reports coming back with the same callback it left by."""
    return bool(reason) and "is back" in str(reason).lower()


def _shut(source):
    try:
        source.close()
    except Exception:
        pass


def wanted_for(settings):
    """Whether a picture is worth opening a camera for at all.

    An Icecast station has nowhere to put a picture, and opening a camera for
    it would be a light on in the room for no reason. This is the question
    `ui._build_picture` asks before going live, kept here so the recording
    side cannot answer it differently: a recording ALWAYS wants one, whatever
    Ctrl+B is pointed at, and that distinction is the fault Tony reported.
    """
    from . import streamout
    return streamout.is_rtmp(settings.get("server", ""))


#: How long to wait for a real camera before settling for the card, when a
#: caller is in a position to wait at all. A preview and a recording are;
#: pressing Ctrl+B is not.
READY_SECONDS = C.CAMERA_OPEN_TIMEOUT
