"""The mixer.

One output stream, many voices summed into it. Short sounds are decoded into
memory so they fire the instant you hit the key; long ones stream from disk on
a reader thread so twenty music beds do not cost a gigabyte of RAM.

Nothing in here knows about wx. It is driven entirely by slot indices and file
paths, which is what makes it testable without a sound card.
"""

from __future__ import annotations

import threading
from collections import deque

import numpy as np
import soundfile as sf
import soxr

from . import constants as C

CHANNELS = 2
_DTYPE = "float32"

#: How far ahead a streaming voice reads, in seconds. Enough to ride out a
#: sluggish disk without making the first block late.
_PREBUFFER_SECONDS = 1.5
_READ_FRAMES = 8192


def db_to_gain(db):
    return float(10.0 ** (db / 20.0))


def probe(path):
    """Duration, samplerate and channel count, without decoding the audio."""
    info = sf.info(path)
    duration = info.frames / float(info.samplerate) if info.samplerate else 0.0
    return duration, info.samplerate, info.channels


def _to_stereo(block):
    """Force any channel count to stereo, cheaply and predictably."""
    if block.ndim == 1:
        block = block[:, None]
    if block.shape[1] == 1:
        return np.repeat(block, 2, axis=1)
    if block.shape[1] > 2:
        return np.ascontiguousarray(block[:, :2])
    return block


def load_audio(path, target_rate):
    """Decode a whole file to stereo float32 at the rate the mixer runs at."""
    data, rate = sf.read(path, dtype=_DTYPE, always_2d=True)
    data = _to_stereo(data)
    if rate != target_rate and len(data):
        data = soxr.resample(data, rate, target_rate)
    return np.ascontiguousarray(data, dtype=np.float32)


class _Ring:
    """A thread-safe queue of audio blocks that hands out exact frame counts."""

    def __init__(self):
        self._blocks = deque()
        self._frames = 0
        self._lock = threading.Lock()

    @property
    def frames(self):
        with self._lock:
            return self._frames

    def put(self, block):
        if not len(block):
            return
        with self._lock:
            self._blocks.append(block)
            self._frames += len(block)

    def take(self, frames):
        """Up to ``frames`` frames. A short return means the buffer ran dry."""
        out = np.zeros((frames, CHANNELS), dtype=np.float32)
        filled = 0
        with self._lock:
            while filled < frames and self._blocks:
                head = self._blocks[0]
                want = min(frames - filled, len(head))
                out[filled:filled + want] = head[:want]
                filled += want
                if want == len(head):
                    self._blocks.popleft()
                else:
                    self._blocks[0] = head[want:]
                self._frames -= want
        return out[:filled]


class Voice:
    """One sound in flight, with its own gain envelope."""

    def __init__(self, slot_index, *, gain, loop, fade_in, fade_out, rate,
                 is_bed=False, bus=None, name=""):
        self.slot_index = slot_index
        self.name = name
        #: Which fader this voice sits on, and how ducking treats it.
        #: "sfx" causes ducking, "bed" and "playlist" get ducked. ``is_bed``
        #: is still accepted and still readable, because it is what every
        #: existing caller and test says.
        self.bus = bus or (C.BUS_BED if is_bed else C.BUS_SFX)
        self.loop = loop
        self.rate = rate
        self.finished = False

        self._target = float(gain)
        self._gain = 0.0 if fade_in > 0 else float(gain)
        self._fade_in_frames = max(1, int(fade_in * rate))
        self._fade_out_frames = max(1, int(fade_out * rate))
        self._releasing = False
        self._frames_played = 0

    def _ramp(self, frames):
        """Move the gain toward its target across this block."""
        if self._gain == self._target:
            return self._gain
        span = self._fade_out_frames if self._target < self._gain else self._fade_in_frames
        step = frames / float(span)
        delta = self._target - self._gain
        move = min(abs(delta), step) * (1.0 if delta > 0 else -1.0)
        new = self._gain + move
        ramp = np.linspace(self._gain, new, frames, dtype=np.float32)
        self._gain = new
        return ramp[:, None]

    def set_gain(self, gain):
        if not self._releasing:
            self._target = float(gain)

    def release(self, fade_out=None):
        """Fade out and finish. Calling it twice is harmless."""
        if fade_out is not None:
            self._fade_out_frames = max(1, int(fade_out * self.rate))
        self._releasing = True
        self._target = 0.0

    @property
    def is_bed(self):
        return self.bus == C.BUS_BED

    @property
    def is_ducked(self):
        """Music gets out of the way of speech. Beds and playlist tracks both."""
        return self.bus in (C.BUS_BED, C.BUS_PLAYLIST)

    @property
    def is_loud(self):
        """Does this voice push the music down. Only sounds and drops do.

        A playlist track must NOT: it is the music, and a bed ducking under
        the song it is supposed to sit beneath is backwards.
        """
        return self.bus == C.BUS_SFX

    @property
    def releasing(self):
        return self._releasing

    @property
    def position_seconds(self):
        return self._frames_played / float(self.rate)

    @property
    def buffered_frames(self):
        """How much audio is ready to play. ``None`` means always ready."""
        return None

    @property
    def at_eof(self):
        return False

    def _pull(self, frames):
        raise NotImplementedError

    def render(self, frames, duck=1.0):
        if self.finished:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        block = self._pull(frames)
        if len(block) < frames:
            padded = np.zeros((frames, CHANNELS), dtype=np.float32)
            if len(block):
                padded[:len(block)] = block
            block = padded
            if not self.loop:
                self.finished = True
        self._frames_played += frames
        block = block * self._ramp(frames)
        if self.is_ducked:
            block = block * duck
        if self._releasing and self._gain <= 1e-5:
            self.finished = True
        return block

    def close(self):
        pass


class MemoryVoice(Voice):
    """A sound already decoded into a numpy array."""

    def __init__(self, data, **kwargs):
        super().__init__(**kwargs)
        self._data = data
        self._pos = 0

    def _pull(self, frames):
        n = len(self._data)
        if n == 0:
            return np.zeros((0, CHANNELS), dtype=np.float32)
        if not self.loop:
            chunk = self._data[self._pos:self._pos + frames]
            self._pos += len(chunk)
            return chunk
        out = np.empty((frames, CHANNELS), dtype=np.float32)
        filled = 0
        while filled < frames:
            want = min(frames - filled, n - self._pos)
            out[filled:filled + want] = self._data[self._pos:self._pos + want]
            filled += want
            self._pos += want
            if self._pos >= n:
                self._pos = 0
        return out


class StreamVoice(Voice):
    """A long sound read from disk on its own thread."""

    def __init__(self, path, **kwargs):
        super().__init__(**kwargs)
        self._path = path
        self._ring = _Ring()
        self._eof = False
        self._stop = threading.Event()
        self._prebuffer = int(_PREBUFFER_SECONDS * self.rate)
        self._thread = threading.Thread(
            target=self._run, name="dropdeck-reader", daemon=True)
        self._thread.start()

    def _run(self):
        try:
            with sf.SoundFile(self._path) as handle:
                resampler = None
                if handle.samplerate != self.rate:
                    resampler = soxr.ResampleStream(
                        handle.samplerate, self.rate, CHANNELS, dtype=_DTYPE)
                while not self._stop.is_set():
                    if self._ring.frames >= self._prebuffer:
                        self._stop.wait(0.02)
                        continue
                    data = handle.read(_READ_FRAMES, dtype=_DTYPE, always_2d=True)
                    if len(data) == 0:
                        if self.loop:
                            handle.seek(0)
                            continue
                        if resampler is not None:
                            tail = resampler.resample_chunk(
                                np.zeros((0, CHANNELS), dtype=np.float32), last=True)
                            self._ring.put(np.ascontiguousarray(tail, dtype=np.float32))
                        self._eof = True
                        return
                    data = _to_stereo(data)
                    if resampler is not None:
                        data = resampler.resample_chunk(data)
                    if len(data):
                        self._ring.put(np.ascontiguousarray(data, dtype=np.float32))
        except Exception:
            self._eof = True

    @property
    def buffered_frames(self):
        return self._ring.frames

    @property
    def at_eof(self):
        return self._eof

    def _pull(self, frames):
        block = self._ring.take(frames)
        if len(block) < frames and not self._eof:
            # Underrun: the disk was slow. Pad rather than end the sound.
            padded = np.zeros((frames, CHANNELS), dtype=np.float32)
            if len(block):
                padded[:len(block)] = block
            return padded
        return block

    def close(self):
        self._stop.set()
