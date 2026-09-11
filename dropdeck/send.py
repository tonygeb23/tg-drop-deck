"""Sending the show to another program on the same machine.

Tony, 9 September 2026: "if I want team talk to be able to take audio from
TG Drop Deck itself ... really anything that TG Drop Deck is catching."

Until now the only way to get Drop Deck into another program was to point the
main output at a virtual cable, and that gives the other program the pads, the
beds and the playlist and **nothing else**. The microphone and every source
Drop Deck captures live on the air bus, and the air bus only exists while you
are streaming or recording. So the show and the send were two different mixes
and the second one was missing the presenter.

A send is the air bus, out of a sound card, whether or not anything is live.
Same sum the listener would get, same rules: monitoring is not in it, the
playlist is in it at full level however far down you have pulled the fader in
the room.

## Mix minus, and why it is a subtraction

Tony's board captures ``TeamTalk5.exe`` as a source and puts it on the air.
Send that mix back to TeamTalk and everybody in the call hears themselves a
quarter of a second late, which is the oldest fault in broadcasting and the
reason mix minus exists.

So a send names one source to leave out. It cannot do that by summing the
sources again without it, because reading a source takes the audio away from
it: two sums would each get half a voice. `SourceGroup.read_air_minus` does
the one read every callback already did and subtracts that one source's own
block, which is exact, because everything upstream of the soft clip is a plain
sum.

## Why it does not share the main output's stream

Two reasons, and the first one is measured.

A soundboard wants a short output buffer, because the gap between the key and
the sound is the whole product. A send wants a deep one, because there is
already a hundred milliseconds of network between here and the other person
and nobody can hear another twenty. Sharing a stream would mean choosing, and
the choice would be wrong for one of them.

The second is that the send has its own sound card and therefore its own
clock. The `AirBus` is what absorbs the difference: it is written by the
mixers' callbacks and drained by this one, and neither has to know the other
exists.
"""
from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

from . import constants as C
from .audiofile import CHANNELS
from .engine import db_to_gain
from .mixer import describe_device
from .streamout import AirBus


class _Ring:
    """One block written by the send's callback, drained by the monitor's.

    The same shape as micinput._Ring and for the same reason: two audio
    callbacks on two different cards, so a short read is silence and never a
    wait. Its own lock, because unlike the microphone's pair there is only one
    ring here and nothing has to see two of them agree.
    """

    def __init__(self, frames):
        self._buf = np.zeros((int(frames), CHANNELS), dtype=np.float32)
        self._write_at = 0
        self._available = 0
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            self._buf[:] = 0.0
            self._write_at = 0
            self._available = 0

    def write(self, block):
        room = len(self._buf)
        count = min(len(block), room)
        if count <= 0:
            return
        with self._lock:
            end = self._write_at + count
            if end <= room:
                self._buf[self._write_at:end] = block[:count]
            else:
                first = room - self._write_at
                self._buf[self._write_at:] = block[:first]
                self._buf[:end - room] = block[first:count]
            self._write_at = end % room
            self._available = min(room, self._available + count)

    def read(self, frames):
        out = np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            count = min(frames, self._available)
            if count <= 0:
                return out
            room = len(self._buf)
            start = (self._write_at - self._available) % room
            end = start + count
            if end <= room:
                out[:count] = self._buf[start:end]
            else:
                first = room - start
                out[:first] = self._buf[start:]
                out[first:count] = self._buf[:end - room]
            self._available -= count
        return out


class Confidence:
    """What the send is putting out, for the presenter's own headphones.

    Shaped like a source rather than like a mixer input, because that is what
    `SourceGroup` already sums: ``read`` is what you hear and ``read_air`` is
    what the listener hears. A confidence feed answers zeros to the second one,
    and that single fact is what stops it going round for ever. It is heard on
    the monitor output, it is never on the air, and it can therefore never
    arrive back in the send it came from.

    Off by default. A presenter who is not listening to it pays for one
    boolean per block.
    """

    def __init__(self, frames):
        self.on = False
        self.peak = 0.0
        self._ring = _Ring(frames)

    def offer(self, block):
        """Called from the send's callback. Never blocks, never raises."""
        if not self.on:
            return
        try:
            self._ring.write(block)
        except Exception:
            pass

    def read(self, frames):
        """What the presenter hears."""
        if not self.on:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        block = self._ring.read(frames)
        self.peak = float(np.abs(block).max()) if len(block) else 0.0
        return block

    def read_air(self, frames):
        """What the listener hears, which is nothing. See the class note."""
        return np.zeros((frames, CHANNELS), dtype=np.float32)

    def start(self):
        self._ring.clear()
        self.on = True

    def stop(self):
        self.on = False
        self.peak = 0.0
        self._ring.clear()


class Send:
    """The on air mix, out of a sound card, live or not.

    ``device`` is an output index or None for the system default. Everything
    else has a working default, and with ``open_stream=False`` it runs with no
    sound card at all so the tests can drive it.
    """

    def __init__(self, device=None, samplerate=None, gain_db=0.0,
                 open_stream=True, blocksize=None, prime_seconds=None):
        self.device = device
        self.samplerate = int(samplerate or self._device_rate(device))
        #: Deep on purpose. A send is never on the path between a key and a
        #: sound, so it buys reliability with latency nobody can hear over a
        #: call. See C.OUTPUT_BLOCKSIZE for what a short one cost.
        self.blocksize = (C.SEND_BLOCKSIZE if blocksize is None
                          else int(blocksize))
        self.gain_db = float(gain_db)
        self.last_error = None
        self.stream = None

        self.bus = AirBus(self.samplerate, seconds=C.SEND_RING_SECONDS)
        self.confidence = Confidence(
            int(self.samplerate * C.SEND_MONITOR_SECONDS))

        #: How full the ring has to be before a single sample goes out, and
        #: again after it has ever run dry. Two sound cards are never quite
        #: the same speed, so over a long show the ring drains or fills; a
        #: jitter buffer is what turns that into one inaudible correction
        #: rather than a permanent stutter.
        self._prime_frames = int(self.samplerate *
                                 (prime_seconds or C.SEND_PRIME_SECONDS))
        self._primed = False

        #: What to say when asked how it is doing.
        self.blocks = 0
        self.starved = 0            # callbacks the ring could not fill
        self.rebuffers = 0          # times it had to fill up again
        self.peak = 0.0

        if open_stream:
            self.start()

    # ------------------------------------------------------------- plumbing --
    @staticmethod
    def _device_rate(device):
        try:
            if device is None:
                info = sd.query_devices(kind="output")
            else:
                info = sd.query_devices(device)
            return int(info["default_samplerate"])
        except Exception:
            return C.DEFAULT_SAMPLERATE

    def start(self):
        """Open the output. True if audio is really going out of it."""
        self.stop_stream()
        self._primed = False
        self.blocks = 0
        self.starved = 0
        self.rebuffers = 0
        self.bus.reset()
        try:
            self.stream = sd.OutputStream(
                device=self.device,
                samplerate=self.samplerate,
                channels=CHANNELS,
                dtype="float32",
                blocksize=self.blocksize,
                callback=self._callback,
            )
            self.stream.start()
            self.last_error = None
            return True
        except Exception as exc:
            self.stream = None
            self.last_error = str(exc)
            return False

    def stop_stream(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def close(self):
        self.stop_stream()
        self.confidence.stop()
        self.bus.reset()

    @property
    def is_running(self):
        """Is audio really going out of this, not merely was a card opened.

        `stream.active` as well as `stream is not None`. An unplugged card
        looks to PortAudio like an aborted stream, and the object stays put:
        `sending()` said yes, the tap stayed on, the status bar kept saying
        SENDING and the report kept saying "Sending to", with nothing coming
        out. Found by Mark, 10 September 2026.
        """
        stream = self.stream
        if stream is None:
            return False
        try:
            return bool(stream.active)
        except Exception:
            # A closed stream raises rather than answering. That is a no.
            return False

    def describe(self):
        """One line, written to be read aloud rather than looked at."""
        return describe_device(self.device)

    # ---------------------------------------------------------------- audio --
    def _callback(self, outdata, frames, time_info, status):
        # Everything in here is guarded, because sounddevice aborts the stream
        # on a raise and a send that has silently stopped is the whole fault
        # this feature exists to fix.
        try:
            self.blocks += 1
            have = self.bus.available()
            if not self._primed:
                if have < self._prime_frames:
                    outdata.fill(0.0)
                    return
                self._primed = True
            if have < frames:
                # The ring ran dry. Say so, and fill up again rather than
                # limp along starving on every block from here on: the two
                # cards have drifted apart and one short silence beats a
                # permanent stutter.
                self.starved += 1
                self.rebuffers += 1
                self._primed = False
                outdata.fill(0.0)
                return
            block = self.bus.read(frames)
            gain = db_to_gain(self.gain_db) if self.gain_db else 1.0
            if gain != 1.0:
                block = block * gain
            self.peak = float(np.abs(block).max()) if frames else 0.0
            outdata[:] = block
            self.confidence.offer(block)
        except Exception as exc:
            self.last_error = str(exc)
            try:
                outdata.fill(0.0)
            except Exception:
                pass

    # --------------------------------------------------------------- health --
    def keeping_up(self):
        """Is the audio arriving clean, and one line saying why if it is not.

        Deliberately NOT the question of whether the send is switched on.
        That one is ``is_running``, and ``report`` is what puts the two
        together: keeping this to the audio alone is what makes it answerable
        with no sound card in the machine.
        """
        if not self.blocks:
            return True, "the send is open and nothing has played yet"
        if self.rebuffers:
            return False, ("the send has had to rebuffer %d %s"
                           % (self.rebuffers,
                              "time" if self.rebuffers == 1 else "times"))
        if self.bus.dropped:
            return False, ("the send has dropped %d %s"
                           % (self.bus.dropped,
                              "block" if self.bus.dropped == 1 else "blocks"))
        return True, "the send is arriving clean"

    def report(self):
        """The whole answer to "how is the send doing", as one spoken line."""
        if self.stream is None:
            return "The send is off. %s" % (self.last_error or
                                            "Nothing is being sent.")
        _, why = self.keeping_up()
        where = self.describe()
        hearing = ("You are hearing it." if self.confidence.on
                   else "You are not hearing it.")
        return "Sending to %s at %d hertz. %s. %s" % (
            where, self.samplerate, why[0].upper() + why[1:], hearing)
