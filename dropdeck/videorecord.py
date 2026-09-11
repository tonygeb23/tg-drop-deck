"""Recording the picture as well as the sound, in sync, to one file.

Tony, 10 September 2026: "in addition to taking audio, it also takes video as
well. ensure it is perfectly in sync with audio." Darrell, a listener, the
same day: "when setting up a video source, such as a camera or capture card,
should you not be able to record in video if you are doing a recording test?"

`Ctrl+R` still records sound alone and is untouched. `Ctrl+Shift+R` records
both.

## The clock, which is the whole feature

**The audio sample clock is master and video absorbs every bit of drift.**
Master is this recorder's own count of samples written to the file,
``frames_written / samplerate``, which came off the sound card through the
`AirBus`. Video is emitted until its frame count reaches
``int(audio_seconds * fps)``, so a camera running slow has a frame repeated
and one running fast has a frame skipped, and neither can move the timeline.
No part of this file may ever timestamp anything from ``time.monotonic()``.

That is the same mechanism `RtmpDestination._pump_video` already uses, and
Tiffany measured it holding sync to **0.00 ms per minute** over a real 45
second recording, with a per frame stamp read back out of the decoded picture
showing a flat +19.5 ms of video lead. She also measured what happens if any
part of it takes its time from the wall clock instead, on a card running 0.3
per cent off: **minus 150 ms per minute**. That is the worst mistake available
here and it is one line away at all times.

## Three things that are right for a socket and wrong for a file

The RTMP path is correct where it lives. Copying it wholesale is not.

1. **The time base.** FLV carries millisecond timestamps, so the stream stamps
   ``int(round(frames_sent * 1000.0 / fps))`` at ``1/1000``. Measured on a
   real MP4 that gives frame intervals of 33.312, 33.313 and 33.375 ms: a
   variable frame rate file, which is a nuisance in an editor. With
   ``time_base = 1/fps`` and ``pts = frames_sent``, 1348 of 1349 intervals
   came back exactly 33.3333 ms.
2. **`if picture is None: return`.** Correct for a socket, where a missed
   frame is simply not sent. In a file it stalls the video timeline while
   audio keeps going, and then the picture catches up. Measured over an eight
   second camera outage: **the picture ran 6.48 seconds ahead of the sound**,
   was still 0.48 seconds out sixteen seconds later, and **nothing was dropped,
   no gap appeared, no count was wrong and nothing was logged**. Here, a
   missing picture repeats the last frame. Repeating is also cheaper: 9.73 ms
   a frame against 10.94, and 13.6 per cent of the bytes.
3. **Constant bitrate with filler.** The stream pads to a rate because
   platforms publish floors. A file has no floor. Measured on the same ten
   seconds: CBR at 6000k gave 7.62 MB, CRF 18 gave **2.20 MB**, better looking
   and three and a half times smaller.

## Why the file is fragmented

A plain MP4 keeps its index in a moov atom written at the end, so a crash
leaves a file that will not open at all. Measured, each writer killed with
``os._exit`` eight seconds in: plain MP4 **0.0 seconds survived and would not
open**; fragmented at one second, **7.0 of 8.0 seconds, opens**. The loss is
one fragment, fixed, so a three hour show loses its last second rather than
all of it. It costs nothing: measured overhead **minus 0.04 per cent**,
because the moof headers are smaller than the moov index they replace.

**And none of that works without ``flush_packets``.** The first round of that
measurement was wrong: FFmpeg holds up to a 256 KB buffer, so every container
including the fragmented one lost nearly everything, 28 bytes of eight
seconds. The container choice does nothing until the muxer is told to flush.
"""
from __future__ import annotations

import fractions
import os
import threading
import time

import numpy as np

from . import constants as C
from . import recorder as audiorecord
from . import streamout

#: PyAV, imported on the first recording rather than at startup. It loads
#: sixty megabytes of FFmpeg and a board of WAVs must not pay for that, which
#: is the same rule audiofile.py follows.
av = None

#: What a picture recording is written as. One entry, because there is one
#: right answer, and a list so the settings page reads the same as the audio
#: one does.
FORMATS = [("mp4", "MP4, H.264 and AAC")]
FORMAT_KEYS = [key for key, _label in FORMATS]
DEFAULT_FORMAT = "mp4"
EXTENSION = ".mp4"

IDLE = audiorecord.IDLE
RECORDING = audiorecord.RECORDING
FAILED = audiorecord.FAILED


class FrameTap:
    """One picture, put down by whoever has it and picked up by the recorder.

    One lock and one slot. Deliberately not a queue: the recorder wants the
    NEWEST frame and nothing else, and a queue would let a slow encoder build
    a backlog of stale pictures and then play them late.

    **The picture is pushed, never pulled**, and that is not a style choice.
    A DirectShow camera is exclusive, so the recorder cannot open one the
    stream already has. And `picture.FallbackSource.frame` holds no lock at
    all: `fallen_back` and `_tried_at` are read and written unguarded, so two
    threads calling it would race the retry and could fire `on_fallback`
    twice. One owner at a time, handing frames over, avoids both.
    """

    def __init__(self):
        self._frame = None
        self._lock = threading.Lock()
        self.puts = 0

    def put(self, frame):
        """Called by whoever is building the picture. Never raises."""
        if frame is None:
            return
        with self._lock:
            self._frame = frame
            self.puts += 1

    def latest(self):
        with self._lock:
            return self._frame

    def clear(self):
        with self._lock:
            self._frame = None


class VideoRecorder:
    """The show, picture and sound, into one fragmented MP4.

    ``bus`` is an `AirBus` carrying the on air mix, exactly as the audio
    recorder takes one. ``tap`` is a `FrameTap` somebody else is filling with
    the picture that would go out.

    One thread does both, and the order matters: audio is read, encoded and
    muxed FIRST, and only then is video pumped against the count of samples
    written. So if the video encoder ever runs long, the frame counter falls
    behind and the next pass repeats or drops to catch up. **The audio can
    never stall behind the picture.**
    """

    def __init__(self, bus, tap, width=1280, height=720, fps=30,
                 bitrate=192, crf=None, folder=None, on_state=None,
                 path=None, encoder_name=""):
        self.bus = bus
        self.tap = tap
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.bitrate = int(bitrate)
        self.crf = int(C.RECORD_VIDEO_CRF if crf is None else crf)
        self.folder = folder or audiorecord.default_folder()
        self.on_state = on_state
        self.encoder_name = encoder_name

        self.state = IDLE
        self.detail = ""
        self.path = path
        self.started_at = 0.0
        self.frames_written = 0          # AUDIO frames. The master clock.
        self.frames_sent = 0             # video frames muxed
        self.repeated = 0                # frames the picture did not update
        self.dropped_pictures = 0        # frames skipped to catch up
        self.bytes_written = 0
        #: Audio the bus threw away because this could not keep up. Nothing
        #: anywhere read the audio recorder's equivalent, so a recording that
        #: lost sound said nothing at all. See `losing_audio`.
        self.dropped_audio_at_start = 0

        self._thread = None
        self._stop = threading.Event()
        self._container = None
        self._handle = None
        self._audio = None
        self._video = None
        self._resampler = None
        self._last_frame = None
        #: The audio stream's own sample counter, at the ENCODER's rate.
        #: Separate from frames_written, which counts what came off the bus
        #: at the bus's rate, because the two can differ.
        self._apts = 0
        from .engine import db_to_gain
        self._headroom = db_to_gain(C.RECORD_AAC_HEADROOM_DB)
        self._said_losing = 0

    # -------------------------------------------------------------- state --
    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def audio_seconds(self):
        """The master clock. Samples written, not seconds elapsed."""
        if not self.frames_written:
            return 0.0
        return self.frames_written / float(self.bus.samplerate)

    @property
    def elapsed(self):
        return self.audio_seconds

    @property
    def losing_audio(self):
        """Has the bus had to throw sound away since this started."""
        return max(0, self.bus.dropped - self.dropped_audio_at_start)

    def describe(self):
        if self.state != RECORDING:
            return "Not recording"
        minutes, seconds = divmod(int(self.elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        length = ("%d:%02d:%02d" % (hours, minutes, seconds) if hours
                  else "%d:%02d" % (minutes, seconds))
        size = self.bytes_written / (1024.0 * 1024.0)
        said = ("Recording picture and sound, %s, %s, %.0f MB"
                % (os.path.basename(self.path or ""), length, size))
        if self.losing_audio:
            said += ". It is losing audio"
        return said

    def _set_state(self, state, detail=""):
        self.state, self.detail = state, detail
        if self.on_state is not None:
            try:
                self.on_state(state, detail)
            except Exception:
                pass

    # --------------------------------------------------------------- work --
    def start(self):
        """Open the file and begin. True, or False with a reason set."""
        if self.running:
            return True
        try:
            os.makedirs(self.folder, exist_ok=True)
        except OSError as exc:
            self._set_state(FAILED, "Could not make %s. %s" % (self.folder, exc))
            return False
        if self.path is None:
            self.path = audiorecord.next_path(self.folder, DEFAULT_FORMAT)
        try:
            self._open()
        except Exception as exc:
            self._close()
            self._set_state(FAILED, "Could not start recording. %s" % exc)
            return False
        self._stop.clear()
        self.started_at = time.monotonic()
        self.frames_written = 0
        self.frames_sent = 0
        self._apts = 0
        self.repeated = 0
        self.dropped_pictures = 0
        self.bytes_written = 0
        self.dropped_audio_at_start = self.bus.dropped
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dropdeck-record-video")
        self._thread.start()
        self._set_state(RECORDING, self.path)
        return True

    def _open(self):
        global av
        if av is None:
            import av as _av            # lazy: sixty megabytes of FFmpeg
            av = _av

        # buffering=0 so Python adds no buffer of its own on top of the one
        # flush_packets is there to defeat.
        self._handle = open(self.path, "wb", buffering=0)
        self._container = av.open(
            self._handle, mode="w", format="mp4",
            options={
                # Written as it goes, so a crash costs one fragment rather
                # than the whole file. See this module's docstring.
                "movflags": "frag_custom+empty_moov+default_base_moof",
                "frag_duration": str(int(C.RECORD_FRAGMENT_SECONDS * 1000000)),
                "flush_packets": "1",
            })
        self._audio = self._add_audio(self._container)
        self._video = self._add_video(self._container)
        self._resampler = streamout._Resampler(self.bus.samplerate,
                                               self._audio.rate)
        self._container.start_encoding()

    def _add_audio(self, container):
        audio = container.add_stream("aac", rate=int(self.bus.samplerate))
        audio.bit_rate = self.bitrate * 1000
        try:
            audio.layout = "stereo"
        except Exception:
            pass
        return audio

    def _add_video(self, container):
        """The picture stream, falling back the way the stream's does.

        Two differences from `RtmpDestination._add_video`, both measured and
        both explained in this module's docstring: the time base is 1/fps so
        the file is constant frame rate, and the rate control is CRF because
        a file has no bitrate floor to pad up to.
        """
        last = None
        tried = []
        for name in (self.encoder_name,) + tuple(C.RTMP_VIDEO_ENCODERS):
            if not name or name in tried:
                continue
            tried.append(name)
            try:
                video = container.add_stream(name, rate=self.fps)
                video.width = self.width
                video.height = self.height
                video.pix_fmt = "yuv420p"
                # Without these a real file reads back colorspace 2,
                # primaries 2, trc 2, range 0: all unspecified, which is the
                # 8 September colour fault in a new place. With them every
                # encoder tested reads back 1, 1, 1, 1.
                streamout._tag_colour(video)
                video.time_base = fractions.Fraction(1, self.fps)
                video.options = self._video_options(name)
                self.encoder_name = name
                return video
            except Exception as exc:
                last = exc
        raise streamout.EncoderError(
            "no video encoder on this machine would start, so the picture "
            "cannot be recorded: %s" % last)

    def _video_options(self, name):
        if name != "libx264":
            # The hardware and Media Foundation encoders do not take CRF.
            # Give them a bitrate rather than nothing.
            return {"b": "%dk" % C.RECORD_VIDEO_BITRATE}
        return {
            "crf": str(self.crf),
            "preset": C.RECORD_VIDEO_PRESET,
            # Bounded on purpose. Two unbounded x264 instances, one for the
            # stream and one for the recording, will oversubscribe every core
            # on the machine and the thing that suffers is the audio.
            "threads": str(C.RECORD_VIDEO_THREADS),
        }

    # ------------------------------------------------------------- running --
    def _check_backlog(self):
        """Notice the file falling behind the show, and say so once.

        Under load the bus overflows and hands back audio a whole ring old,
        which Jackson measured pinning the sound 1967 ms behind the picture
        for a whole run while 19 seconds of a 27 second show were deleted.
        `Streamer` says "the stream is losing audio" for this. `Recorder`
        never read `bus.dropped` at all, so a recording that lost sound was
        silent about it in every sense.
        """
        lost = self.losing_audio
        if lost and lost != self._said_losing:
            self._said_losing = lost
            self._set_state(RECORDING,
                            "The recording is losing audio. The machine "
                            "cannot keep up with the picture.")

    def _run(self):
        # A FRAME's worth of audio, not a quarter of a second. This one line
        # is the difference between a file that is in sync and one that is
        # 257 ms out in a way nothing here could detect. See
        # C.RECORD_DRAIN_FRAMES_PER_PICTURE.
        chunk = max(256, int(self.bus.samplerate
                             * C.RECORD_DRAIN_FRAMES_PER_PICTURE
                             / float(self.fps or 30)))
        try:
            while not self._stop.is_set():
                if self.bus.available() < chunk:
                    if self._stop.wait(C.STREAM_POLL_SECONDS):
                        break
                    continue
                self._feed_audio(self.bus.read(chunk))
                self._pump_video()
                self._check_backlog()
            left = self.bus.available()
            if left:
                self._feed_audio(self.bus.read(left))
            self._pump_video()
        except Exception as exc:
            self._set_state(FAILED, "Recording stopped. %s" % exc)
        finally:
            self._close()

    def _feed_audio(self, block):
        if not len(block) or self._audio is None:
            return
        self.frames_written += len(block)
        out = self._resampler.feed(block)
        if not len(out):
            return
        if self._headroom != 1.0:
            # AAC decodes ABOVE what was encoded: measured +0.26 dBFS at 192
            # kbps on material the soft clip had already ceilinged at 0. One
            # decibel of room here, on this thread, and nothing anywhere near
            # the mixer, which is feeding the speakers and the stream.
            out = out * self._headroom
        # Exactly what RtmpDestination._encode_audio does, because the file
        # and the stream have to carry the same sound.
        planar = np.ascontiguousarray(out.T.astype(np.float32))
        frame = av.AudioFrame.from_ndarray(planar, format="fltp",
                                           layout="stereo")
        frame.rate = self._audio.rate
        frame.pts = self._apts
        frame.time_base = fractions.Fraction(1, self._audio.rate)
        self._apts += len(out)
        for packet in self._audio.encode(frame):
            self._mux(packet)

    def _pump_video(self):
        """Emit frames until the picture has caught up with the sound.

        The master clock is `audio_seconds`, which is samples written to this
        file. Never a wall clock, and there is a check that says so.
        """
        if self._video is None:
            return
        # Stamped against the audio that has ARRIVED, not only the audio
        # already encoded. The picture in the tap was grabbed a moment ago
        # and the encoder is always a little behind the bus, so counting only
        # what is encoded puts every frame slightly early, which reads as the
        # sound being late. Capped, so it can never run away.
        waiting = 0.0
        try:
            waiting = self.bus.available() / float(self.bus.samplerate)
        except Exception:
            pass
        lead = min(int(waiting * self.fps), C.RECORD_STAMP_LEAD_FRAMES)
        due = int(self.audio_seconds * self.fps) + lead
        # A cap, so a long stall cannot become a burst of a thousand frames
        # that starves the audio behind it. Anything beyond the cap is a drop,
        # counted, and the timeline stays right because the counter moves.
        room = C.RECORD_CATCHUP_FRAMES
        if due - self.frames_sent > room:
            skipped = (due - self.frames_sent) - room
            self.dropped_pictures += skipped
            self.frames_sent += skipped
        while self.frames_sent < due and not self._stop.is_set():
            self._emit_one()

    def _emit_one(self):
        picture = self.tap.latest() if self.tap is not None else None
        if picture is None:
            picture = self._last_frame
            self.repeated += 1
        elif picture is self._last_frame:
            self.repeated += 1
        else:
            self._last_frame = picture
        if picture is None:
            # Nothing has ever arrived. A black frame keeps the timeline
            # honest, which is the whole point: NEVER return without
            # advancing, or the sound runs on without the picture and comes
            # back seconds out with every count still correct.
            picture = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
        # dst_colorspace is not optional here either. Without it swscale
        # converts with the BT.601 matrix and the file goes out with standard
        # definition colour weights on a high definition picture.
        frame = frame.reformat(format="yuv420p",
                               dst_colorspace=C.RTMP_COLOURSPACE)
        # The whole reason this is not RtmpDestination's line: pts counts
        # FRAMES at a time base of 1/fps, so the file is constant frame rate.
        # Milliseconds at 1/1000 gave 33.312, 33.313 and 33.375 ms intervals.
        frame.pts = self.frames_sent
        frame.time_base = fractions.Fraction(1, self.fps)
        self.frames_sent += 1
        try:
            for packet in self._video.encode(frame):
                self._mux(packet)
        except Exception:
            # One bad frame must never end a recording. The timeline has
            # already moved, so sync is unaffected.
            pass

    def _mux(self, packet):
        container = self._container
        if container is None:
            return
        container.mux(packet)
        try:
            self.bytes_written = self._handle.tell()
        except Exception:
            pass

    def _close(self):
        container, self._container = self._container, None
        if container is not None:
            for stream in (self._audio, self._video):
                if stream is None:
                    continue
                try:
                    for packet in stream.encode(None):
                        container.mux(packet)
                except Exception:
                    pass
            try:
                container.close()
            except Exception:
                pass
        self._audio = self._video = None
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
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

    # -------------------------------------------------------------- report --
    def report(self):
        """What happened, as a sentence, for the line said when it stops."""
        minutes, seconds = divmod(int(self.elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        length = ("%d hours %d minutes" % (hours, minutes) if hours
                  else "%d minutes %d seconds" % (minutes, seconds))
        size = self.bytes_written / (1024.0 * 1024.0)
        said = ["Recording saved as %s, %s, %.0f megabytes"
                % (os.path.basename(self.path or ""), length, size)]
        if self.losing_audio:
            said.append("It lost audio %d times, so there are gaps in it"
                        % self.losing_audio)
        if self.dropped_pictures:
            said.append("%d frames of picture were skipped to keep the sound "
                        "in step" % self.dropped_pictures)
        return ". ".join(said) + "."
