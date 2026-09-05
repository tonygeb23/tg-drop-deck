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
from .micinput import (CHANNELS, MicInput, describe_input,
                       input_devices, resolve_input)

#: How many extra sources somebody can have. Not a technical limit: each one
#: is a sound card being read in real time, and a list longer than this is
#: somebody who wants a mixer rather than a soundboard.
MAX_SOURCES = 8


class Source:
    """One extra input, on its way to the stream or your headphones."""

    def __init__(self, name="", device_name="", device_hostapi="",
                 gain_db=0.0, monitor=False, on_air=True, channel="mix",
                 samplerate=None):
        self.name = name or "Source"
        #: Remembered by NAME, like every other device in this app. An index
        #: changes the moment somebody plugs in a headset.
        self.device_name = device_name or ""
        self.device_hostapi = device_hostapi or ""
        self.wanted_monitor = bool(monitor)
        self.wanted_on_air = bool(on_air)
        self.input = MicInput(duck_bus=None,
                              samplerate=samplerate or C.DEFAULT_SAMPLERATE,
                              gain_db=gain_db, monitor=bool(monitor))
        self.input.channel = channel if channel in ("mix", "left", "right") \
            else "mix"
        self.last_error = None

    # ------------------------------------------------------------ settings --
    @property
    def gain_db(self):
        return self.input.gain_db

    @gain_db.setter
    def gain_db(self, value):
        self.input.gain_db = float(value)

    @property
    def channel(self):
        return self.input.channel

    @channel.setter
    def channel(self, value):
        self.input.channel = value if value in ("mix", "left", "right") else "mix"

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
        if self.device_name and not self.is_open:
            parts.append("not open")
        return ", ".join(parts)

    # ------------------------------------------------------------ lifetime --
    def start(self, samplerate=None):
        """Open the device, if this source is wanted at all. True if it is on."""
        if samplerate:
            self.input.set_output_rate(samplerate)
        if not (self.wanted_on_air or self.wanted_monitor):
            self.stop()
            return False
        device = resolve_input(self.spec())
        if device is None and self.device_name:
            self.last_error = "%s is not plugged in" % self.device_name
            self.stop()
            return False
        self.input.monitor = self.wanted_monitor
        self.input.on_air = self.wanted_on_air
        if self.input.is_open and self.input.device == device:
            return True
        started = self.input.start(device=device)
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
        return self.input.read(frames)

    def read_air(self, frames):
        return self.input.read_air(frames)

    # ------------------------------------------------------------- storage --
    def to_dict(self):
        return {"name": self.name, "device_name": self.device_name,
                "device_hostapi": self.device_hostapi,
                "gain_db": float(self.gain_db), "channel": self.channel,
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
                   device_name=str(data.get("device_name") or ""),
                   device_hostapi=str(data.get("device_hostapi") or ""),
                   gain_db=max(C.MIN_MIC_GAIN_DB,
                               min(C.MAX_MIC_GAIN_DB, gain)),
                   monitor=bool(data.get("monitor", False)),
                   on_air=bool(data.get("on_air", True)),
                   channel=str(data.get("channel") or "mix"),
                   samplerate=samplerate)


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

    def __init__(self, mic=None, sources=None):
        self.mic = mic
        self.sources = list(sources or [])

    def __len__(self):
        return len(self.sources) + (1 if self.mic is not None else 0)

    def __bool__(self):
        return bool(len(self))

    def _sum(self, frames, what):
        block = None
        for source in ([self.mic] if self.mic is not None else []) + self.sources:
            try:
                piece = getattr(source, what)(frames)
            except Exception:
                continue      # one bad input must never take the show down
            if piece is None or not len(piece):
                continue
            if block is None:
                block = piece.copy()
            else:
                block += piece
        return block

    def read(self, frames):
        """What the presenter hears. Zeros when nothing is monitored."""
        block = self._sum(frames, "read")
        if block is None:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        return block

    def read_air(self, frames):
        """What the listener hears."""
        block = self._sum(frames, "read_air")
        if block is None:
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        return block


def available_inputs():
    """Every input device, for a picker. The same list the microphone uses."""
    return input_devices()


def describe(device):
    return describe_input(device)
