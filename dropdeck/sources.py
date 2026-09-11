"""Other things you want on the air besides your own voice.

Tony, 5 September 2026: "take the audio of an individually running program,
like a source. so. Add sources to a running stream, so in addition to the
microphone, it also can catch the audio from teamtalk.exe or, Google Chrome
chrome.exe."

A word about what this is and is not, because the difference decides how much
of it can exist.

Windows can capture **a device**: a microphone, a line input, or the output of
a virtual cable. Capturing **a process** is a different and much harder thing,
a COM interface with no Python binding, and it is what OBS uses for its
Application Audio Capture. This file does the first one.

That is less of a compromise than it sounds, because a virtual cable turns the
second problem into the first. Point TeamTalk at the cable in its own settings
and its audio arrives here as an ordinary input device, named and selectable,
with a fader of its own. It is one setup step in the other program and then it
simply works, on any Windows, with no driver of ours.

Each source is a `MicInput` with no ducking and no voice processing. Those two
belong to the microphone: program audio should not duck the beds, because it
is not somebody talking, and a compressor tuned for a voice has no business on
a games call. Everything else, opening at whatever rate the device offers,
resampling to the output, separate monitor and air taps, is the same problem
the microphone already solved.
"""
from __future__ import annotations

import numpy as np

from . import constants as C
from . import proccapture
from .micinput import (CHANNELS, MicInput, describe_input,
                       input_devices, resolve_input)

#: How many extra sources somebody can have. Not a technical limit: each one
#: is a sound card being read in real time, and a list longer than this is
#: somebody who wants a mixer rather than a soundboard.
MAX_SOURCES = 8


class Source:
    """One extra input, on its way to the stream or your headphones."""

    #: What this source is listening to. A sound card, or one program.
    DEVICE = "device"
    PROGRAM = "program"

    def __init__(self, name="", device_name="", device_hostapi="",
                 gain_db=0.0, monitor=False, on_air=True, channel="mix",
                 samplerate=None, kind=DEVICE, program="", delay_ms=0.0):
        self.name = name or "Source"
        self.kind = kind if kind in (self.DEVICE, self.PROGRAM) else self.DEVICE
        #: Remembered by NAME, like every other device in this app. An index
        #: changes the moment somebody plugs in a headset.
        self.device_name = device_name or ""
        self.device_hostapi = device_hostapi or ""
        #: The executable, for a program source. Never a process id: that is
        #: a different number every time the program starts, so a board that
        #: saved one would capture nothing next week.
        self.program = program or ""
        self.wanted_monitor = bool(monitor)
        self.wanted_on_air = bool(on_air)
        rate = samplerate or C.DEFAULT_SAMPLERATE
        if self.kind == self.PROGRAM:
            self.input = proccapture.ProcessCapture(
                samplerate=rate, gain_db=gain_db, monitor=bool(monitor))
        else:
            self.input = MicInput(duck_bus=None, samplerate=rate,
                                  gain_db=gain_db, monitor=bool(monitor))
            self.input.channel = (channel if channel in ("mix", "left", "right")
                                  else "mix")
        self.last_error = None

        #: How far this source is held back, in milliseconds. Darrell's
        #: request: a capture card arrives whenever its own hardware gets
        #: round to it. See _DelayLine, which also says what this cannot do.
        #: A line per tap, because what you hear and what goes out are read
        #: separately and each consumes what it takes.
        self._delay_ms = 0.0
        self._delay_monitor = _DelayLine()
        self._delay_air = _DelayLine()
        self.delay_ms = delay_ms

    @property
    def delay_ms(self):
        return self._delay_ms

    @delay_ms.setter
    def delay_ms(self, value):
        try:
            value = float(value or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(C.MAX_SOURCE_DELAY_MS, value))
        self._delay_ms = value
        rate = getattr(self.input, "output_rate", None) or C.DEFAULT_SAMPLERATE
        frames = int(round(value * rate / 1000.0))
        self._delay_monitor.set_frames(frames)
        self._delay_air.set_frames(frames)

    #: Silenced by hand, from the source control list. Never saved: a mute
    #: is something you do during a show, and coming back tomorrow to a
    #: source that is quiet for reasons you cannot remember is worse than
    #: having to press it again.
    muted = False
    #: Soloed. While anything at all is soloed, everything that is not is
    #: silent. Also never saved.
    soloed = False

    def wants_air(self, anything_soloed=False):
        """Whether this should be on the air right now.

        Three things decide it: what the source is set to, whether it has
        been muted, and whether something somewhere is soloed. Kept in one
        place so the microphone and the sources answer it the same way.
        """
        if self.muted:
            return False
        if anything_soloed and not self.soloed:
            return False
        return bool(self.wanted_on_air)

    def wants_monitor(self, anything_soloed=False):
        if self.muted:
            return False
        if anything_soloed and not self.soloed:
            return False
        return bool(self.wanted_monitor)

    # ------------------------------------------------------------ settings --
    @property
    def gain_db(self):
        return self.input.gain_db

    @gain_db.setter
    def gain_db(self, value):
        self.input.gain_db = float(value)

    @property
    def channel(self):
        # A program capture arrives stereo as Windows hands it over, so there
        # is no side to choose.
        return getattr(self.input, "channel", "mix")

    @channel.setter
    def channel(self, value):
        if hasattr(self.input, "channel"):
            self.input.channel = (value if value in ("mix", "left", "right")
                                  else "mix")

    @property
    def is_program(self):
        return self.kind == self.PROGRAM

    @property
    def is_open(self):
        return self.input.is_open

    @property
    def peak(self):
        return self.input.peak

    def spec(self):
        return {"name": self.device_name, "hostapi": self.device_hostapi}

    def describe(self):
        """One line, written to be read aloud rather than looked at."""
        if self.is_program:
            where = self.program or "no program chosen"
        else:
            where = self.device_name or "no device chosen"
        parts = [self.name, where]
        if not self.wanted_on_air and not self.wanted_monitor:
            parts.append("off")
        else:
            parts.append("on air" if self.wanted_on_air else "not on air")
            if self.wanted_monitor:
                parts.append("you hear it")
        if self.gain_db:
            parts.append("%+.0f dB" % self.gain_db)
        if self.delay_ms:
            parts.append("held back %d ms" % int(self.delay_ms))
        chosen = self.program if self.is_program else self.device_name
        if chosen and not self.is_open:
            parts.append(self.last_error or "not open")
        return ", ".join(parts)

    # ------------------------------------------------------------ lifetime --
    def start(self, samplerate=None):
        """Open it, if this source is wanted at all. True if it is running."""
        if samplerate:
            self.input.set_output_rate(samplerate)
        if not (self.wanted_on_air or self.wanted_monitor):
            self.stop()
            return False
        self.input.monitor = self.wanted_monitor
        self.input.on_air = self.wanted_on_air
        if self.is_program:
            return self._start_program()
        device = resolve_input(self.spec())
        if device is None and self.device_name:
            self.last_error = "%s is not plugged in" % self.device_name
            self.stop()
            return False
        if self.input.is_open and self.input.device == device:
            return True
        started = self.input.start(device=device)
        self.last_error = None if started else self.input.last_error
        return started

    def _start_program(self):
        """Find the program by name, then capture it.

        By name every time, even when it is already running: a program that
        was closed and opened again has a different process id, and a capture
        pointed at the old number would quietly give nothing at all.
        """
        if not self.program:
            self.last_error = "No program chosen"
            return False
        pid = proccapture.find_pid(self.program)
        if pid is None:
            self.last_error = "%s is not running" % self.program
            self.stop()
            return False
        if self.input.is_open and self.input.pid == pid:
            return True
        self.stop()
        self.input.monitor = self.wanted_monitor
        self.input.on_air = self.wanted_on_air
        started = self.input.start(pid=pid)
        self.last_error = None if started else self.input.last_error
        return started

    def stop(self):
        self.input.on_air = False
        self.input.monitor = False
        return self.input.stop()

    def close(self):
        self.input.close()

    # --------------------------------------------------------------- audio --
    def read(self, frames):
        return self._delay_monitor.feed(self.input.read(frames))

    def read_air(self, frames):
        return self._delay_air.feed(self.input.read_air(frames))

    # ------------------------------------------------------------- storage --
    def to_dict(self):
        return {"name": self.name, "kind": self.kind,
                "device_name": self.device_name,
                "device_hostapi": self.device_hostapi,
                "program": self.program,
                "gain_db": float(self.gain_db), "channel": self.channel,
                "delay_ms": float(self.delay_ms),
                "monitor": bool(self.wanted_monitor),
                "on_air": bool(self.wanted_on_air)}

    @classmethod
    def from_dict(cls, data, samplerate=None):
        data = data if isinstance(data, dict) else {}
        try:
            gain = float(data.get("gain_db", 0.0) or 0.0)
        except (TypeError, ValueError):
            gain = 0.0
        return cls(name=str(data.get("name") or "Source"),
                   kind=str(data.get("kind") or cls.DEVICE),
                   program=str(data.get("program") or ""),
                   device_name=str(data.get("device_name") or ""),
                   device_hostapi=str(data.get("device_hostapi") or ""),
                   gain_db=max(C.MIN_MIC_GAIN_DB,
                               min(C.MAX_MIC_GAIN_DB, gain)),
                   monitor=bool(data.get("monitor", False)),
                   on_air=bool(data.get("on_air", True)),
                   channel=str(data.get("channel") or "mix"),
                   delay_ms=data.get("delay_ms", 0.0),
                   samplerate=samplerate)


class _DelayLine:
    """Holds a source back by a fixed number of frames.

    Darrell, a listener, 10 September 2026: "when using external audio
    sources, there is some lag there. For example, I would stream my capture
    card as an audio or video source for game audio. In obs, we can adjust
    the offset for the source, so it does not lag as much. Could this be done
    in drop deck?"

    Yes, and this is it. A capture card, a console, a games call over a cable:
    each arrives whenever its own hardware gets round to it, and nothing in
    the world lines them up for you.

    **What this can and cannot do, said plainly because the UI has to say it
    too.** It can only ever make a source LATER. Nothing can make live audio
    arrive earlier than it does, so a source that is running behind is
    corrected by delaying everything it is out with, not by delaying it.
    That is also how OBS works and it surprises everybody once.

    Its own line per tap, because what you hear and what goes out are read
    separately and each consumes what it takes.
    """

    def __init__(self, frames=0):
        self._frames = 0
        self._held = np.zeros((0, CHANNELS), dtype=np.float32)
        self.set_frames(frames)

    def set_frames(self, frames):
        frames = max(0, int(frames))
        if frames == self._frames:
            return
        self._frames = frames
        # Start again rather than stretch what is held: a delay changed mid
        # show is somebody lining a source up by ear, and a click while they
        # do it is better than an answer that keeps sliding.
        self._held = np.zeros((frames, CHANNELS), dtype=np.float32)

    @property
    def frames(self):
        return self._frames

    def feed(self, block):
        if not self._frames or block is None or not len(block):
            return block
        both = np.concatenate([self._held, block])
        out, self._held = both[:len(block)], both[len(block):]
        return out


class SourceGroup:
    """The microphone and every extra source, read as if they were one.

    The mixer takes a single object for monitoring and a single object for
    the on air mix. Rather than teach it about lists, which would mean
    changing the two places in the audio callback that are hardest to get
    right, this looks exactly like one input and sums the others behind it.

    Each source is read ONCE per callback, because reading takes the audio
    away: two readers on one source would each get half of it. That is why the
    mixer holds this and not the sources themselves.
    """

    def __init__(self, mic=None, sources=None, extras=None):
        self.mic = mic
        self.sources = list(sources or [])
        self.extras = list(extras or [])

    def __len__(self):
        return len(self.sources) + (1 if self.mic is not None else 0)

    def __bool__(self):
        return bool(len(self))

    def _members(self):
        """Everything summed here, in order.

        ``extras`` are feeds the presenter hears and the listener never does.
        A confidence monitor of the send is the one so far. They are summed
        into ``read`` and left out of ``read_air`` by answering zeros to it,
        which is what makes it impossible for one to arrive back in the mix
        it came from.
        """
        return (([self.mic] if self.mic is not None else [])
                + self.sources + list(self.extras))

    def _sum(self, frames, what, minus=None):
        """Sum every member once. Optionally a second sum, less one member.

        One read, because reading a source TAKES the audio away from it: two
        passes over the same sources would give each sum half a voice. So the
        second sum is the first with one member's own block subtracted, which
        is exact, everything here being a plain addition.
        """
        block = None
        taken = None
        for source in self._members():
            try:
                piece = getattr(source, what)(frames)
            except Exception:
                continue      # one bad input must never take the show down
            if piece is None or not len(piece):
                continue
            if source is minus:
                taken = piece
            if block is None:
                block = piece.copy()
            else:
                block += piece
        return block, taken

    def read(self, frames):
        """What the presenter hears. Zeros when nothing is monitored."""
        block, _ = self._sum(frames, "read")
        if block is None:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        return block

    def read_air(self, frames):
        """What the listener hears."""
        block, _ = self._sum(frames, "read_air")
        if block is None:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        return block

    def read_air_minus(self, frames, minus=None):
        """The on air sum, and the same sum without one source in it.

        This is mix minus. Feeding a program back its own audio is how a call
        gets an echo of itself, so a send that carries a captured program has
        to leave that program out, and it has to do it off the one read
        everything else is already using.

        Returns a pair, always. With no ``minus``, or a ``minus`` that
        contributed nothing this block, the two are the same array rather
        than a copy: nothing downstream may write into either in place.
        """
        block, taken = self._sum(frames, "read_air", minus=minus)
        if block is None:
            block = np.zeros((frames, CHANNELS), dtype=np.float32)
            return block, block
        if taken is None:
            return block, block
        return block, block - taken


def available_inputs():
    """Every input device, for a picker. The same list the microphone uses."""
    return input_devices()


def describe(device):
    return describe_input(device)
