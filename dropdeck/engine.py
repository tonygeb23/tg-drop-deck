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
import soxr

from . import audiofile
from . import constants as C
from .audiofile import CHANNELS, to_stereo as _to_stereo

_DTYPE = audiofile.DTYPE

#: How far ahead a streaming voice reads, in seconds. Enough to ride out a
#: sluggish disk without making the first block late.
_PREBUFFER_SECONDS = 1.5
_READ_FRAMES = 8192


def db_to_gain(db):
    return float(10.0 ** (db / 20.0))


def probe(path):
    """Duration, samplerate and channel count, without decoding the audio."""
    return audiofile.probe(path)


def load_audio(path, target_rate):
    """Decode a whole file to stereo float32 at the rate the mixer runs at."""
    data, rate = audiofile.read_all(path)
    if rate != target_rate and len(data):
        data = soxr.resample(data, rate, target_rate)
    return np.ascontiguousarray(data, dtype=np.float32)


def _shaped(wave, rate, edge=None):
    """Fade a few milliseconds in and out. Without it a tone is a click."""
    edge = max(1, int((C.CUE_TONE_EDGE if edge is None else edge) * rate))
    if len(wave) > 2 * edge:
        ramp = np.linspace(0.0, 1.0, edge, dtype=np.float32)
        wave[:edge] *= ramp
        wave[-edge:] *= ramp[::-1]
    return wave


def _sine(rate, hz, seconds, edge=None):
    frames = max(1, int(seconds * rate))
    t = np.arange(frames, dtype=np.float32) / float(rate)
    return _shaped(np.sin(2.0 * np.pi * hz * t).astype(np.float32), rate, edge)


def _gap(rate, seconds):
    return np.zeros(max(1, int(seconds * rate)), dtype=np.float32)


def _cue_shape(kind, rate):
    """One cue, as a mono waveform, before it is levelled.

    Six of them, and the differences are deliberately differences of SHAPE.
    Over a song a bell and a sweep are told apart at once, where two tones a
    third apart are not, and a cue you have to stop and identify has already
    cost you the moment it was warning you about.
    """
    if kind == "double":
        # Two short ones. The classic "stand by" from a talkback panel.
        pip = _sine(rate, C.CUE_TONE_HZ, 0.075)
        return np.concatenate([pip, _gap(rate, 0.075), pip])
    if kind == "chime":
        # A fifth up, the second overlapping the first, so it reads as one
        # gesture rather than two sounds.
        low = _sine(rate, 880.0, 0.16)
        high = _sine(rate, 1318.5, 0.20)
        out = np.zeros(len(low) + len(high) - int(0.06 * rate),
                       dtype=np.float32)
        out[:len(low)] += low
        out[len(out) - len(high):] += high
        return out
    if kind == "bell":
        # Struck, and left to ring. Bell partials are not harmonics, which is
        # exactly why a bell sounds like a bell and not like an organ.
        frames = max(1, int(0.6 * rate))
        t = np.arange(frames, dtype=np.float32) / float(rate)
        out = np.zeros(frames, dtype=np.float32)
        for ratio, weight, decay in ((1.0, 1.0, 4.0), (2.0, 0.6, 6.0),
                                     (2.76, 0.4, 8.0), (5.4, 0.15, 12.0)):
            out += (weight * np.exp(-decay * t)
                    * np.sin(2.0 * np.pi * 1046.5 * ratio * t)).astype(np.float32)
        return _shaped(out, rate, edge=0.002)
    if kind == "tick":
        # Three, like a clock running out. Higher and shorter than the pip,
        # so it cuts through music without being a tone anybody could mistake
        # for part of it.
        tick = _sine(rate, 2200.0, 0.022, edge=0.004)
        gap = _gap(rate, 0.085)
        return np.concatenate([tick, gap, tick, gap, tick])
    if kind == "sweep":
        # Rising, which reads as "coming up" rather than "stop".
        frames = max(1, int(0.22 * rate))
        t = np.arange(frames, dtype=np.float32) / float(rate)
        hz = 600.0 + (1600.0 - 600.0) * (t / t[-1] if frames > 1 else t)
        phase = 2.0 * np.pi * np.cumsum(hz) / float(rate)
        return _shaped(np.sin(phase).astype(np.float32), rate, edge=0.008)
    # "pip", and anything a board asks for that this version has never heard
    # of. A cue that is missing is worse than a cue that is plain.
    return _sine(rate, C.CUE_TONE_HZ, C.CUE_TONE_SECONDS)


def cue_tone(rate, kind=None, level_db=None):
    """One cue, made rather than loaded.

    Generated so there is no file to ship, no file to lose and nothing to
    license. Every shape is normalised to the same peak before the level is
    applied, so changing which cue you use never changes how loud it is.
    """
    wave = _cue_shape(kind or C.DEFAULT_CUE_SOUND, rate)
    level = db_to_gain(C.CUE_LEVEL_DB if level_db is None else float(level_db))
    if len(wave):
        # Matched on the loudest MOMENT rather than on the peak. A bell and a
        # steady pip at the same peak are not the same loudness: the bell
        # decays, so most of it is quiet, and peak matching left it ten
        # decibels down in energy and easy to miss over a song. This measures
        # a thirty millisecond window, which is roughly what an ear averages
        # over, and then backs off if that would push the peak past the
        # level, so nothing ever gets louder than you asked for.
        window = max(1, int(0.03 * rate))
        energy = np.convolve(wave.astype(np.float64) ** 2,
                             np.ones(window) / window, mode="valid")
        loudest = float(np.sqrt(energy.max())) if len(energy) else 0.0
        peak = float(np.abs(wave).max())
        # A steady sine's window RMS is its peak over root two, so the pip
        # comes out exactly at the level and every other shape is matched to
        # it. A peakier shape is then allowed a higher PEAK to get there, up
        # to a decibel below full scale, which is the difference between a
        # bell you hear over the music and one you do not.
        ceiling = 0.891251                     # minus one decibel
        gain = (level / 1.41421356) / loudest if loudest > 0 else 0.0
        if peak > 0 and peak * gain > ceiling:
            gain = ceiling / peak
        wave = (wave * gain).astype(np.float32)
    return np.ascontiguousarray(np.tile(wave[:, None], (1, CHANNELS)),
                                dtype=np.float32)


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
        #: A fader move, which is not a fade. See set_gain.
        self._glide_frames = max(1, int(C.VOLUME_GLIDE * rate))
        #: How long the move in progress has to take, and how far it has to
        #: travel. Both are set wherever the target is set, rather than being
        #: guessed from which direction the gain is going: a fade in, a fade
        #: out and somebody nudging the volume key are three different moves
        #: that all look the same from inside _ramp.
        self._ramp_frames = self._fade_in_frames
        self._ramp_span = abs(self._target - self._gain)
        self._releasing = False
        self._frames_played = 0

    def _ramp(self, frames):
        """Move the gain toward its target across this block."""
        if self._gain == self._target:
            return self._gain
        # The step is a fraction of the distance THIS move has to cover, not
        # a fraction of full scale. Without that, a fade on a fader sitting at
        # eighty per cent finished in eighty per cent of the time it was asked
        # for, so a three second crossfade was really two and a half and the
        # number in the box was not the number you heard.
        distance = self._ramp_span or abs(self._target - self._gain)
        step = distance * frames / float(max(1, self._ramp_frames))
        delta = self._target - self._gain
        move = min(abs(delta), step) * (1.0 if delta > 0 else -1.0)
        new = self._gain + move
        ramp = np.linspace(self._gain, new, frames, dtype=np.float32)
        self._gain = new
        return ramp[:, None]

    def _aim(self, target, frames):
        """Head for a new gain, over this many frames."""
        self._target = float(target)
        self._ramp_frames = max(1, int(frames))
        self._ramp_span = abs(self._target - self._gain)

    def set_gain(self, gain):
        """A fader moved. Glide to it, do not fade to it.

        A bed's fade out is most of a second, and that is right for stopping a
        bed and wrong for a keypress on the volume: holding F5 down would
        crawl. A few tens of milliseconds is enough to keep a step from
        clicking, which is all a fader move needs.
        """
        if not self._releasing:
            self._aim(gain, self._glide_frames)

    def release(self, fade_out=None):
        """Fade out and finish. Calling it twice is harmless."""
        if fade_out is not None:
            self._fade_out_frames = max(1, int(fade_out * self.rate))
        self._releasing = True
        self._aim(0.0, self._fade_out_frames)

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

    @property
    def exhausted(self):
        """Is there definitely no more audio to come.

        A short pull from a memory voice means the sound ended. A short pull
        from a streaming one usually means the disk was slow, and ending the
        sound on that would cut a song off mid word because a Dropbox sync
        picked that moment to run.
        """
        return True

    def _pull(self, frames):
        raise NotImplementedError

    def render(self, frames, duck=1.0):
        if self.finished:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        block = self._pull(frames)
        # Only the frames that were really there count towards the position.
        # Padding an underrun and calling it playback made position_seconds
        # run ahead of the music, and the cue point is measured against it.
        self._frames_played += len(block)
        if len(block) < frames:
            padded = np.zeros((frames, CHANNELS), dtype=np.float32)
            if len(block):
                padded[:len(block)] = block
            block = padded
            if not self.loop and self.exhausted:
                self.finished = True
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
        handle = None
        try:
            handle = audiofile.reader(self._path)
            resampler = None
            if handle.samplerate != self.rate:
                resampler = soxr.ResampleStream(
                    handle.samplerate, self.rate, CHANNELS, dtype=_DTYPE)
            while not self._stop.is_set():
                if self._ring.frames >= self._prebuffer:
                    self._stop.wait(0.02)
                    continue
                data = handle.read(_READ_FRAMES)
                if len(data) == 0:
                    if self.loop:
                        handle.seek_start()
                        continue
                    if resampler is not None:
                        tail = resampler.resample_chunk(
                            np.zeros((0, CHANNELS), dtype=np.float32), last=True)
                        self._ring.put(np.ascontiguousarray(tail, dtype=np.float32))
                    self._eof = True
                    return
                if resampler is not None:
                    data = resampler.resample_chunk(data)
                if len(data):
                    self._ring.put(np.ascontiguousarray(data, dtype=np.float32))
        except Exception:
            self._eof = True
        finally:
            if handle is not None:
                handle.close()

    @property
    def buffered_frames(self):
        return self._ring.frames

    @property
    def at_eof(self):
        return self._eof

    @property
    def exhausted(self):
        """Read to the end AND drained. Anything less is an underrun."""
        return self._eof and self._ring.frames == 0

    def _pull(self, frames):
        # Short is allowed: render pads it, and only a voice that is both at
        # end of file and drained is allowed to finish.
        return self._ring.take(frames)

    def close(self):
        self._stop.set()
