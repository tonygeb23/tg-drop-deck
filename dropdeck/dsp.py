"""Processing for the microphone: gate, equaliser, compressor, limiter.

What a broadcast chain is for, in one sentence: it makes a voice sit at a
steady level and stay out of trouble, so the presenter can lean back, lean in,
shout and whisper without anybody riding a fader.

The order is the conventional one and it is not arbitrary:

    gate  ->  high pass  ->  equaliser  ->  compressor  ->  limiter

Gate first, so the compressor is not busy pulling up room noise between words.
High pass next, because rumble and plosives are energy the compressor would
otherwise react to and nobody wants to hear. Equaliser before the compressor,
so the compressor responds to the voice you have shaped rather than the one
you have not. Limiter last, always last, because its entire job is to be the
final word on how loud anything gets.

**The processing is JUCE, through pedalboard.** Writing four processors by
hand is a week of work to arrive somewhere worse than a library that is
already here, already fast and already used in anger. Measured: the whole
chain takes 0.09 ms of a 512 frame block's 11.6 ms budget, so under one per
cent, which is what makes it safe to run inside an audio callback.

**It is optional at every level.** No pedalboard, no processing, and the
microphone works exactly as it did. Every processor can be switched off on its
own, and the whole chain can be bypassed, because the fastest way to know what
a compressor is doing is to turn it off and on.

**Nothing here is allowed to raise.** A microphone that stops working because
a filter disagreed with a number is worse than a microphone with no filter.
"""
from __future__ import annotations

import math
import threading

import numpy as np

try:
    import pedalboard
except Exception:      # pragma: no cover - pedalboard missing is a real state
    pedalboard = None


def available():
    """Whether there is any processing to be had on this machine."""
    return pedalboard is not None


# ---------------------------------------------------------------------------
# One knob
# ---------------------------------------------------------------------------

class Parameter:
    """One adjustable value, described well enough to be read out loud.

    Everything the interface needs to present a control without knowing what
    it controls: what it is called, where it sits, how far it goes, what the
    number means and how to say it. Built in processors and VST3 plugins both
    produce these, so one accessible list serves both and a plugin nobody has
    ever seen is as usable as the compressor.
    """

    def __init__(self, key, label, getter, setter, low, high, step,
                 unit="", decimals=1, choices=None):
        self.key = key
        self.label = label
        self._get = getter
        self._set = setter
        self.low = low
        self.high = high
        self.step = step
        self.unit = unit
        self.decimals = decimals
        #: For a parameter that is a list of names rather than a number.
        self.choices = choices

    @property
    def value(self):
        try:
            return self._get()
        except Exception:
            return self.low

    @value.setter
    def value(self, new):
        try:
            self._set(self.clamp(new))
        except Exception:
            pass

    def clamp(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return self.low
        return max(self.low, min(self.high, value))

    def nudge(self, steps):
        """Move by whole steps, which is what an arrow key means."""
        self.value = self.value + steps * self.step
        return self.value

    def spoken(self):
        """The value, said the way a person would say it."""
        value = self.value
        if self.choices:
            index = int(round(value))
            if 0 <= index < len(self.choices):
                return self.choices[index]
        if self.unit == "ratio":
            return "%.1f to 1" % value
        text = ("%%.%df" % self.decimals) % value
        if text.endswith("." + "0" * self.decimals):
            text = text.split(".")[0]
        return ("%s %s" % (text, self.unit)).strip()

    def describe(self):
        return "%s, %s" % (self.label, self.spoken())


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------

#: Defaults chosen for a spoken voice on a normal microphone, not for a
#: mastering chain. Gentle enough that switching it on is an improvement
#: rather than an effect.
DEFAULTS = {
    "gate_on": True, "gate_threshold": -45.0, "gate_ratio": 6.0,
    "gate_attack": 1.0, "gate_release": 120.0,

    "highpass_on": True, "highpass_hz": 80.0,

    "eq_on": True,
    "eq_low_hz": 200.0, "eq_low_db": 0.0,
    "eq_mid_hz": 1800.0, "eq_mid_db": 0.0, "eq_mid_q": 1.0,
    "eq_high_hz": 6000.0, "eq_high_db": 0.0,

    "comp_on": True, "comp_threshold": -20.0, "comp_ratio": 3.0,
    "comp_attack": 8.0, "comp_release": 140.0, "comp_makeup": 4.0,

    "limit_on": True, "limit_ceiling": -1.0, "limit_release": 100.0,
}



class Ceiling:
    """A limiter that means what it says: nothing gets louder than this.

    pedalboard ships a Limiter and it is not this. Measured, 4 September 2026:
    set its threshold to minus six and feed it a tone at minus twenty, and it
    comes out at minus ten. It is a loudness maximiser, where a lower setting
    means more make up gain and the output is allowed all the way to full
    scale. Correct for its purpose and exactly backwards for a broadcast
    ceiling, where "never louder than minus one" has to be a promise.

    So this is the promise. Gain falls instantly when a peak arrives, which
    means no overshoot at all rather than the small one a lookahead limiter
    trades latency to avoid, and recovers at the release rate afterwards.
    Latency is zero, which matters when the presenter is listening to
    themselves: a few milliseconds of delay against bone conduction sounds
    like a barrel, and no amount of transparent limiting is worth that.

    The recurrence looks like it needs a loop over samples. It does not. Gain
    in decibels is

        g[n] = min(target[n], g[n-1] + rise)

    which unrolls to min over all earlier k of (target[k] + rise*(n-k)), and
    subtracting the ramp turns that into a running minimum:

        h = target - rise*n        ->    g = rise*n + minimum.accumulate(h)

    Exact, and one pass of numpy rather than five hundred iterations of
    Python inside an audio callback.
    """

    def __init__(self, samplerate, ceiling_db=-1.0, release_ms=100.0):
        self.samplerate = float(samplerate)
        self.ceiling_db = float(ceiling_db)
        self.release_ms = max(1.0, float(release_ms))
        self._gain_db = 0.0

    def reset(self):
        self._gain_db = 0.0

    def process(self, block):
        if not len(block):
            return block
        ceiling = 10.0 ** (self.ceiling_db / 20.0)
        peak = np.abs(block).max(axis=1)
        # How much each sample would have to come down by, and never up: this
        # limiter only ever attenuates.
        with np.errstate(divide="ignore"):
            target_db = np.minimum(
                0.0, 20.0 * np.log10(np.maximum(peak, 1e-12) / ceiling) * -1.0)
        rise = 20.0 / (self.release_ms * 0.001 * self.samplerate)
        ramp = rise * np.arange(len(block), dtype=np.float64)
        seeded = np.empty(len(block) + 1, dtype=np.float64)
        seeded[0] = self._gain_db
        seeded[1:] = target_db - ramp
        gain_db = ramp + np.minimum.accumulate(seeded)[1:]
        gain_db = np.minimum(gain_db, 0.0)
        self._gain_db = float(gain_db[-1])
        gain = (10.0 ** (gain_db / 20.0)).astype(np.float32)
        return (block * gain[:, None]).astype(np.float32)


class MicChain:
    """The whole microphone chain, rebuilt whenever a number changes.

    Rebuilding rather than mutating in place is deliberate. pedalboard's
    processors are cheap to construct and rebuilding is the only way to be
    certain a change has taken, whereas setting an attribute on a live
    processor sometimes leaves the old coefficients running until the next
    reset. A microphone chain changes settings when somebody is fiddling in a
    dialog, not per block, so the cost never lands during a show.
    """

    def __init__(self, samplerate=44100, settings=None):
        self.samplerate = int(samplerate)
        self.settings = dict(DEFAULTS)
        if settings:
            self.update(settings, rebuild=False)
        #: The whole chain off, for hearing what it is doing by turning it off.
        self.enabled = True
        #: A VST3, or None. See vst.py.
        self.plugin = None
        #: How much the chain pulled the loudest moment down, in decibels.
        #: Measured rather than asked of the compressor, because pedalboard
        #: does not report it and a number you can hear is worth having.
        self.gain_reduction_db = 0.0
        self._board = None
        #: Held while the chain is used and while it is rebuilt, so the two
        #: never overlap. Rebuilding hands pedalboard a fresh set of objects,
        #: and handing a plugin to a new Pedalboard calls into that plugin at
        #: the same moment the audio thread may be inside its processBlock.
        #: That is a crash in C++, not an exception in Python, and it is what
        #: Tony saw as "it almost crashed when I was moving around and
        #: loading vsts".
        #:
        #: Only ever held for one block, about a tenth of a millisecond, or
        #: one rebuild, about a hundredth. Loading a plugin takes over a
        #: second and happens OUTSIDE it, deliberately.
        self._lock = threading.RLock()
        #: The live stage objects, so a value can be changed on the chain
        #: that is running rather than by building a new one around it.
        self._stages = {}
        #: Ours, not pedalboard's, and always the last thing to touch the
        #: audio. See Ceiling for why.
        self._ceiling = Ceiling(self.samplerate)
        self.rebuild()

    # ------------------------------------------------------------ settings --
    def update(self, settings, rebuild=True):
        for key, value in (settings or {}).items():
            if key in self.settings:
                self.settings[key] = value
        if rebuild:
            self.rebuild()

    #: Which live object and attribute each setting drives. A value listed
    #: here is changed on the running chain; anything else, and every switch,
    #: changes the SHAPE of the chain and so needs it rebuilt.
    LIVE = {
        "gate_threshold": ("gate", "threshold_db"),
        "gate_ratio": ("gate", "ratio"),
        "gate_attack": ("gate", "attack_ms"),
        "gate_release": ("gate", "release_ms"),
        "highpass_hz": ("highpass", "cutoff_frequency_hz"),
        "eq_low_hz": ("low", "cutoff_frequency_hz"),
        "eq_low_db": ("low", "gain_db"),
        "eq_mid_hz": ("mid", "cutoff_frequency_hz"),
        "eq_mid_db": ("mid", "gain_db"),
        "eq_mid_q": ("mid", "q"),
        "eq_high_hz": ("high", "cutoff_frequency_hz"),
        "eq_high_db": ("high", "gain_db"),
        "comp_threshold": ("comp", "threshold_db"),
        "comp_ratio": ("comp", "ratio"),
        "comp_attack": ("comp", "attack_ms"),
        "comp_release": ("comp", "release_ms"),
        "comp_makeup": ("makeup", "gain_db"),
    }

    def apply_one(self, key, value):
        """Change one setting on the chain that is already running.

        Arrowing through the settings list used to rebuild the whole chain on
        every single keypress. Wasteful on its own, and the reason loading a
        plugin was dangerous: a rebuild while the audio thread is inside the
        old chain is two threads in one plugin. A number now lands on the
        live object, and only a switch or a plugin changes any shape.
        """
        self.settings[key] = value
        if key in ("limit_ceiling", "limit_release"):
            self._ceiling.ceiling_db = float(self.settings["limit_ceiling"])
            self._ceiling.release_ms = float(self.settings["limit_release"])
            return
        where = self.LIVE.get(key)
        if where is None:
            self.rebuild()
            return
        with self._lock:
            stage = self._stages.get(where[0])
            if stage is not None:
                try:
                    setattr(stage, where[1], float(value))
                    return
                except Exception:
                    pass
        self.rebuild()

    def rebuild(self):
        """Make the processor chain the settings describe."""
        if pedalboard is None:
            with self._lock:
                self._board = None
                self._stages = {}
            return
        s = self.settings
        stages = []
        live = {}
        try:
            if s["gate_on"]:
                live["gate"] = pedalboard.NoiseGate(
                    threshold_db=float(s["gate_threshold"]),
                    ratio=float(s["gate_ratio"]),
                    attack_ms=float(s["gate_attack"]),
                    release_ms=float(s["gate_release"]))
                stages.append(live["gate"])
            if s["highpass_on"]:
                live["highpass"] = pedalboard.HighpassFilter(
                    cutoff_frequency_hz=float(s["highpass_hz"]))
                stages.append(live["highpass"])
            if s["eq_on"]:
                live["low"] = pedalboard.LowShelfFilter(
                    cutoff_frequency_hz=float(s["eq_low_hz"]),
                    gain_db=float(s["eq_low_db"]))
                live["mid"] = pedalboard.PeakFilter(
                    cutoff_frequency_hz=float(s["eq_mid_hz"]),
                    gain_db=float(s["eq_mid_db"]),
                    q=float(s["eq_mid_q"]))
                live["high"] = pedalboard.HighShelfFilter(
                    cutoff_frequency_hz=float(s["eq_high_hz"]),
                    gain_db=float(s["eq_high_db"]))
                stages.extend([live["low"], live["mid"], live["high"]])
            if s["comp_on"]:
                live["comp"] = pedalboard.Compressor(
                    threshold_db=float(s["comp_threshold"]),
                    ratio=float(s["comp_ratio"]),
                    attack_ms=float(s["comp_attack"]),
                    release_ms=float(s["comp_release"]))
                stages.append(live["comp"])
                # Always present, even at nought, so make up gain can change
                # without changing the shape of the chain.
                live["makeup"] = pedalboard.Gain(
                    gain_db=float(s["comp_makeup"]))
                stages.append(live["makeup"])
            if self.plugin is not None:
                stages.append(self.plugin)
            built = pedalboard.Pedalboard(stages) if stages else None
            with self._lock:
                self._board = built
                self._stages = live
        except Exception:
            # A number the library will not take must not leave the
            # microphone dead. No chain is a working microphone.
            with self._lock:
                self._board = None
                self._stages = {}
        self._ceiling.ceiling_db = float(s["limit_ceiling"])
        self._ceiling.release_ms = float(s["limit_release"])

    def set_plugin(self, plugin):
        """Put a plugin in the chain, or take one out.

        The plugin must already be LOADED. Loading takes over a second and
        runs the plugin's own start up code; doing that while holding the
        lock would stall the audio thread for the whole of it, which is a
        gap in the sound rather than a race.
        """
        with self._lock:
            self.plugin = plugin
        self.rebuild()

    # --------------------------------------------------------------- audio --
    def process(self, block):
        """One block in, one block out. Never raises, never changes length.

        ``block`` is (frames, channels) float32, which is how the rest of this
        app carries audio. pedalboard wants (channels, frames), so it is
        transposed on the way in and back on the way out.
        """
        if not self.enabled or not len(block):
            self.gain_reduction_db = 0.0
            return block
        try:
            before = float(np.abs(block).max())
            with self._lock:
                if self._board is not None:
                    out = self._board.process(
                        np.ascontiguousarray(block.T), self.samplerate,
                        reset=False)
                    out = np.ascontiguousarray(out.T).astype(np.float32)
                else:
                    out = block
            if self.settings["limit_on"]:
                out = self._ceiling.process(out)
            if len(out) != len(block):
                # A processor that changes the length would put every later
                # stage out of step. Better to hear the unprocessed block.
                self.gain_reduction_db = 0.0
                return block
            after = float(np.abs(out).max())
            if before > 1e-5 and after > 1e-9:
                self.gain_reduction_db = max(
                    0.0, 20.0 * math.log10(before / after))
            else:
                self.gain_reduction_db = 0.0
            return out
        except Exception:
            self.gain_reduction_db = 0.0
            return block

    def reset(self):
        """Forget every envelope and filter, for a fresh start."""
        if self._board is not None:
            try:
                self._board.reset()
            except Exception:
                pass
        self._ceiling.reset()
        self.gain_reduction_db = 0.0

    # ---------------------------------------------------------- the knobs --
    def parameters(self, group=None):
        """Every adjustable value, described well enough to read aloud."""
        s = self.settings

        def make(key, label, low, high, step, unit="", decimals=1):
            return Parameter(
                key, label,
                lambda k=key: float(s[k]),
                lambda v, k=key: self.apply_one(k, v),
                low, high, step, unit, decimals)

        def switch(key, label):
            return Parameter(
                key, label,
                lambda k=key: 1.0 if s[k] else 0.0,
                lambda v, k=key: (s.__setitem__(k, bool(round(v))),
                                  self.rebuild()),
                0.0, 1.0, 1.0, "", 0, choices=["off", "on"])

        groups = {
            "gate": [
                switch("gate_on", "Noise gate"),
                make("gate_threshold", "Gate opens above", -80, 0, 1, "dB", 0),
                make("gate_ratio", "Gate depth", 1, 20, 0.5, "ratio"),
                make("gate_attack", "Gate attack", 0.1, 50, 0.5, "ms"),
                make("gate_release", "Gate release", 5, 1000, 10, "ms", 0),
            ],
            "eq": [
                switch("highpass_on", "High pass filter"),
                make("highpass_hz", "High pass at", 20, 400, 5, "Hz", 0),
                switch("eq_on", "Equaliser"),
                make("eq_low_hz", "Low shelf at", 40, 600, 10, "Hz", 0),
                make("eq_low_db", "Low shelf gain", -18, 18, 0.5, "dB"),
                make("eq_mid_hz", "Middle at", 200, 8000, 50, "Hz", 0),
                make("eq_mid_db", "Middle gain", -18, 18, 0.5, "dB"),
                make("eq_mid_q", "Middle width", 0.2, 8, 0.1, "Q"),
                make("eq_high_hz", "High shelf at", 1500, 16000, 250, "Hz", 0),
                make("eq_high_db", "High shelf gain", -18, 18, 0.5, "dB"),
            ],
            "comp": [
                switch("comp_on", "Compressor"),
                make("comp_threshold", "Compress above", -60, 0, 1, "dB", 0),
                make("comp_ratio", "Compression ratio", 1, 20, 0.5, "ratio"),
                make("comp_attack", "Compressor attack", 0.1, 100, 1, "ms"),
                make("comp_release", "Compressor release", 10, 2000, 10,
                     "ms", 0),
                make("comp_makeup", "Make up gain", 0, 24, 0.5, "dB"),
            ],
            "limit": [
                switch("limit_on", "Limiter"),
                make("limit_ceiling", "Never louder than", -12, 0, 0.5, "dB"),
                make("limit_release", "Limiter release", 10, 1000, 10, "ms", 0),
            ],
        }
        if group:
            return groups.get(group, [])
        out = []
        for name in ("gate", "eq", "comp", "limit"):
            out.extend(groups[name])
        return out

    def to_dict(self):
        return dict(self.settings)
