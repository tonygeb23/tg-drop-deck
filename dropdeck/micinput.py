"""The microphone: an input stream, a gain, and optional monitoring.

The first piece of the live-show side of the app. Three jobs, and they are
deliberately separate:

**Capture.** One `sounddevice.InputStream`, opened at the smallest block the
device will take and asked for low latency, because a monitored microphone with
a lag on it is unusable, you hear yourself late and you cannot speak over it.

**Ducking.** While the microphone is open, everything musical gets out of the
way. That is not done by listening to the level: it is done by the fact that the
microphone is *on*. A gate that opens on your voice clips the first syllable of
every sentence, and one that stays open ducks the bed when you cough. Open means
ducked; closed means back up. `DuckBus` already exists for exactly this, it is
how a drop on one sound card ducks a bed on another, so the microphone simply
publishes onto it under its own key.

**Monitoring.** Off by default, and it says why: on speakers it is a feedback
loop. On headphones it is how you know you are live. The captured blocks go into
a small ring buffer that the output mixer drains; if it runs dry the mixer gets
silence rather than a stall, because a starved monitor must never take the
music down with it.

Like `engine.py` and `mixer.py`, this module knows nothing about wx.
"""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd
import soxr

from . import constants as C
from .engine import CHANNELS, db_to_gain

#: The key the microphone publishes under on the shared DuckBus. Anything but
#: a mixer's own key, which is what the mixers publish their own drops under.
DUCK_KEY = "microphone"


def input_devices():
    """Every input the machine offers, newest APIs first.

    Same shape and the same ordering as ``mixer.output_devices``: WASAPI at the
    top because that is where the low latency and the virtual cables are.
    """
    hostapis = [h["name"] for h in sd.query_hostapis()]
    found = []
    for index, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        found.append({
            "index": index,
            "name": dev["name"],
            "hostapi": hostapis[dev["hostapi"]],
            "channels": dev["max_input_channels"],
            "samplerate": int(dev["default_samplerate"]),
        })
    preferred = {"Windows WASAPI": 0, "Windows DirectSound": 1, "MME": 2}
    found.sort(key=lambda d: (preferred.get(d["hostapi"], 3), d["name"].lower()))
    return found


def describe_input(device):
    """A spoken-friendly name for one input index, or the system default."""
    if device is None:
        try:
            return "%s (system default)" % sd.query_devices(kind="input")["name"]
        except Exception:
            return "system default"
    try:
        info = sd.query_devices(device)
        return "%s (%s)" % (info["name"],
                            sd.query_hostapis(info["hostapi"])["name"])
    except Exception:
        return "unknown device"


def resolve_input(spec):
    """Turn a saved {name, hostapi} back into a live index, or None.

    Remembered by name for the same reason outputs are: indices move the moment
    anything is plugged in or unplugged.
    """
    if not spec or not spec.get("name"):
        return None
    name = spec.get("name")
    hostapi = spec.get("hostapi")
    devices = input_devices()
    for device in devices:
        if device["name"] == name and device["hostapi"] == hostapi:
            return device["index"]
    for device in devices:
        if device["name"] == name:
            return device["index"]
    return None


def input_rate(device):
    """The rate a microphone actually wants, or a sane guess."""
    try:
        if device is None:
            info = sd.query_devices(kind="input")
        else:
            info = sd.query_devices(device)
        return int(info["default_samplerate"])
    except Exception:
        return C.DEFAULT_SAMPLERATE


class _Ring:
    """A block of audio written by one callback and drained by another.

    Nothing here locks: MicInput owns the lock, because the two rings are
    written in the same breath and a reader must not see one updated and not
    the other.
    """

    def __init__(self, frames=None):
        self.buf = np.zeros((frames or C.MIC_RING_FRAMES, CHANNELS),
                            dtype=np.float32)
        self.write_at = 0
        self.available = 0

    def clear(self):
        self.buf[:] = 0.0
        self.write_at = 0
        self.available = 0

    def write(self, block):
        room = len(self.buf)
        count = min(len(block), room)
        end = self.write_at + count
        if end <= room:
            self.buf[self.write_at:end] = block[:count]
        else:
            first = room - self.write_at
            self.buf[self.write_at:] = block[:first]
            self.buf[:end - room] = block[first:count]
        self.write_at = end % room
        self.available = min(room, self.available + count)

    def read(self, frames):
        out = np.zeros((frames, CHANNELS), dtype=np.float32)
        count = min(frames, self.available)
        if count <= 0:
            return out
        room = len(self.buf)
        start = (self.write_at - self.available) % room
        end = start + count
        if end <= room:
            out[:count] = self.buf[start:end]
        else:
            first = room - start
            out[:first] = self.buf[start:]
            out[first:count] = self.buf[:end - room]
        self.available -= count
        return out


class MicInput:
    """One microphone. Open or closed, with a gain and an optional monitor.

    The capture rate is the MICROPHONE's, not the speakers'. They are very
    often different - a headset at 44100 next to an interface at 48000 - and
    PortAudio simply refuses to open an input at a rate the device does not
    offer:

        Error opening InputStream: Invalid sample rate [PaErrorCode -9997]

    So the microphone opens at a rate it will accept, and the monitored audio
    is resampled to the output's rate on the way through. When the two match,
    which is the common case, nothing is resampled at all.
    """

    def __init__(self, duck_bus=None, samplerate=None, device=None,
                 gain_db=0.0, monitor=False):
        self.duck_bus = duck_bus
        self.device = device
        #: The rate the OUTPUT runs at, which is what monitored audio has to
        #: arrive in. Kept in step with the mixer by whoever owns both.
        self.output_rate = int(samplerate or C.DEFAULT_SAMPLERATE)
        #: The rate the microphone is actually open at. Set by start().
        self.samplerate = self.output_rate
        self.gain_db = float(gain_db)
        self.monitor = bool(monitor)
        self.stream = None
        self.last_error = None
        #: Peak of the most recent block, 0 to 1, for a level readout. This
        #: one is BEFORE the processing, because it is what a gain control
        #: needs to be set against.
        self.peak = 0.0
        #: And after it, which is what actually leaves the building.
        self.processed_peak = 0.0
        self.overruns = 0

        #: Gate, equaliser, compressor and limiter. None means the voice
        #: goes out exactly as it arrives, which is what happens when the
        #: processing library is not installed.
        self.chain = None

        #: On air. Separate from monitoring on purpose: a presenter working
        #: on speakers hears nothing back and is still being broadcast, and a
        #: presenter checking their headphones is not necessarily live.
        self.on_air = False

        self._lock = threading.Lock()
        #: What the speakers drain, and what the stream drains. Two readers
        #: cannot share one ring, because each takes what it reads away.
        self._monitor = _Ring()
        self._air = _Ring()
        #: Set when the microphone's rate differs from the output's. Stateful,
        #: because resampling each block independently would click at every
        #: block boundary.
        self._resampler = None

    # ------------------------------------------------------------- state ---
    @property
    def is_open(self):
        return self.stream is not None

    @property
    def gain(self):
        return db_to_gain(self.gain_db)

    @property
    def gain_reduction_db(self):
        """How hard the compressor is working, or zero if there is none."""
        chain = self.chain
        return chain.gain_reduction_db if chain is not None else 0.0

    def describe(self):
        return describe_input(self.device)

    @property
    def resampling(self):
        """Is the microphone running at a different rate from the output."""
        return self.samplerate != self.output_rate

    def set_output_rate(self, rate):
        """The output moved to a device with another rate. Follow it.

        Called when the soundboard's output changes. A microphone left at the
        old rate would monitor sharp or flat by however far the two differ.
        """
        rate = int(rate or C.DEFAULT_SAMPLERATE)
        if rate == self.output_rate:
            return False
        self.output_rate = rate
        if self.is_open:
            self.start()          # reopens, and rebuilds the resampler
        else:
            self._reset_ring()
        return True

    # ------------------------------------------------------------ opening --
    def candidate_rates(self):
        """Rates to try, best first.

        The output's rate first, because matching it means no resampling at
        all. Then what the microphone itself says it wants, then the two rates
        every device on earth supports. Duplicates removed, order kept.
        """
        wanted = [self.output_rate, input_rate(self.device), 48000, 44100]
        seen = []
        for rate in wanted:
            rate = int(rate or 0)
            if rate > 0 and rate not in seen:
                seen.append(rate)
        return seen

    def start(self, device=None):
        """Open the microphone. Returns True if it is actually running.

        Nothing opens a microphone on its own: this is only ever called
        because somebody pressed the key. An app that quietly turned a
        microphone on at startup would be a different kind of program.
        """
        if device is not None:
            self.device = device
        self.stop()

        failures = []
        for rate in self.candidate_rates():
            try:
                stream = sd.InputStream(
                    device=self.device,
                    samplerate=rate,
                    channels=1,      # one channel, spread across both outputs
                    dtype="float32",
                    blocksize=C.BLOCKSIZE,
                    latency="low",
                    callback=self._callback,
                )
                stream.start()
            except Exception as exc:  # no microphone, in use, rate refused
                failures.append("%d Hz: %s" % (rate, exc))
                continue
            self.stream = stream
            self.samplerate = rate
            self.last_error = None
            self._reset_ring()
            self._publish(True)
            return True

        self.stream = None
        # Every rate, not just the last one. "Invalid sample rate" on its own
        # does not say which rates were tried, which is the only useful part.
        self.last_error = "; ".join(failures) or "no microphone available"
        self._publish(False)
        return False

    def stop(self):
        """Close the microphone and put the music back up."""
        was_open = self.stream is not None
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        self.peak = 0.0
        self._publish(False)
        self._reset_ring()
        return was_open

    def toggle(self, device=None):
        """Returns True if the microphone is open afterwards."""
        if self.is_open:
            self.stop()
            return False
        return self.start(device=device)

    def close(self):
        self.stop()
        if self.duck_bus is not None:
            self.duck_bus.forget(DUCK_KEY)

    def _publish(self, live):
        """Tell every output whether the microphone is open.

        This is the whole ducking story. Open means the music gets out of the
        way; closed means it comes back. No level detection, no gate, nothing
        that can clip the first word of a sentence.
        """
        if self.duck_bus is not None:
            self.duck_bus.publish(DUCK_KEY, bool(live))

    # ------------------------------------------------------------ capture --
    def _reset_ring(self):
        with self._lock:
            self._monitor.clear()
            self._air.clear()
        chain = self.chain
        if chain is not None:
            # Envelopes and filters remember the last thing they heard, and
            # the last thing they heard was a different microphone.
            chain.reset()
            if self.samplerate != self.output_rate:
                self._resampler = soxr.ResampleStream(
                    self.samplerate, self.output_rate, CHANNELS,
                    dtype="float32")
            else:
                self._resampler = None

    def _callback(self, indata, frames, time_info, status):
        if status:
            self.overruns += 1
        block = np.asarray(indata, dtype=np.float32)
        if block.ndim == 2:
            block = block[:, 0]
        block = block * self.gain
        peak = float(np.abs(block).max()) if frames else 0.0
        self.peak = peak
        if not self.monitor and not self.on_air:
            return
        # One channel up the middle of both. Written into the rings under the
        # lock; each reader drains its own from its own callback.
        stereo = np.repeat(block[:, None], CHANNELS, axis=1)
        with self._lock:
            if self._resampler is not None:
                # The microphone and the speakers are on different clocks and
                # different rates. Resampled once here, so both readers only
                # ever deal in the output's rate and can add it straight in.
                stereo = self._resampler.resample_chunk(stereo)
                if not len(stereo):
                    return

        # Processed OUTSIDE the lock. It is only a tenth of a millisecond, but
        # the output callback takes this same lock to read the monitor, and
        # there is no reason to make it wait behind a compressor.
        chain = self.chain
        if chain is not None:
            stereo = chain.process(stereo)
        self.processed_peak = (float(np.abs(stereo).max())
                               if len(stereo) else 0.0)

        with self._lock:
            if self.monitor:
                self._monitor.write(stereo)
            if self.on_air:
                self._air.write(stereo)

    def read(self, frames):
        """Drain up to ``frames`` of monitored audio. Never blocks.

        Returns a (frames, CHANNELS) block, zero-padded when the microphone has
        not produced enough yet. Two streams have two clocks and they drift; a
        monitor running dry has to be silence for a moment, never a stall in
        the output callback that would take the music with it.
        """
        if not self.monitor or not self.is_open:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            return self._monitor.read(frames)

    def read_air(self, frames):
        """The same, for the stream. Its own tap, drained independently.

        Monitoring and broadcasting are different questions and each reader
        takes what it reads away, so the answer to one cannot come out of the
        other's ring.
        """
        if not self.on_air or not self.is_open:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            return self._air.read(frames)
