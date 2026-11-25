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
        # Plus one sample of release. The carried gain is where the LAST block
        # ended, and the recurrence says the first sample of this one is
        # min(target[0], previous + rise): the running minimum below indexes
        # the carry at k = -1, so its ramp term is rise, not nought. Without
        # it every block boundary quietly ate one sample of recovery.
        seeded[0] = self._gain_db + rise
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
        #: Where it came from, so it can be found again next time. Loading a
        #: plugin takes over a second, so nothing is loaded here: this only
        #: remembers what was asked for, and whoever owns the chain loads it
        #: when it suits them.
        self.plugin_path = None
        self.wanted_plugin = (settings or {}).get("plugin") or None
        wanted = (settings or {}).get("plugin_values")
        self.wanted_plugin_values = dict(wanted) if isinstance(wanted, dict) else {}
        #: How much the chain pulled the loudest moment down, in decibels.
        #: Measured rather than asked of the compressor, because pedalboard
        #: does not report it and a number you can hear is worth having.
        self.gain_reduction_db = 0.0
        self._board = None
        #: Held while the chain is used, while it is rebuilt, and while any
        #: plugin parameter is read or written. That last one is the real
        #: hazard and it was missed the first time round: constructing a
        #: Pedalboard only stores pointers and its own processing takes a
        #: mutex per plugin, but the parameter bindings take nothing, and
        #: reading a plugin's parameters the first time sweeps a thousand
        #: values per knob, writing and restoring each. A thousand
        #: unsynchronised writes into a plugin the audio thread is inside is
        #: a crash in C++ rather than an exception in Python, and it is what
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

    def set_samplerate(self, rate):
        """Run at another rate. True if it changed.

        pedalboard designs every filter for the rate it is TOLD, not the one
        the audio is really at, so a chain told 48000 and fed 96000 has
        every corner an octave high. Rebuilt rather than retuned, for the
        reason the class gives.
        """
        rate = int(rate or 0)
        if rate <= 0 or rate == self.samplerate:
            return False
        with self._lock:
            self.samplerate = rate
            self._ceiling.samplerate = float(rate)
        self.rebuild()
        return True

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

    def set_plugin(self, plugin, path=None):
        """Put a plugin in the chain, or take one out.

        The plugin must already be LOADED. Loading takes over a second and
        runs the plugin's own start up code; doing that while holding the
        lock would stall the audio thread for the whole of it, which is a
        gap in the sound rather than a race.

        ``path`` is where it was loaded from, kept so the same plugin comes
        back next time the app opens. Without it, choosing a plugin lasted
        exactly as long as the session did.
        """
        with self._lock:
            self.plugin = plugin
            self.plugin_path = path if plugin is not None else None
            if plugin is None:
                self.wanted_plugin = None
                self.wanted_plugin_values = {}
        self.rebuild()

    def plugin_values(self):
        """Every plugin knob and its value, or nothing if there is no plugin."""
        from . import vst
        with self._lock:
            plugin = self.plugin
        if plugin is None:
            return {}
        try:
            return vst.snapshot(plugin, self._lock)
        except Exception:
            return {}

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
        """Forget every envelope and filter, for a fresh start.

        Under the lock. A VST3's reset() runs its own code, and the microphone
        stream is already live by the time this is called: _try_open starts the
        capture callback and only then resets the rings. Resetting a plugin
        while it is processing is the same crash by another door.
        """
        with self._lock:
            if self._board is not None:
                try:
                    self._board.reset()
                except Exception:
                    pass
        self._ceiling.reset()
        self.gain_reduction_db = 0.0

    # ---------------------------------------------------------- the knobs --
    def plugin_parameters(self):
        """The plugin's knobs, guarded by this chain's lock."""
        from . import vst
        with self._lock:
            plugin = self.plugin
        return vst.parameters(plugin, self._lock) if plugin is not None else []

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
        """Everything worth writing down, including which plugin and how it is
        set. The plugin used to be left out, so a compressor survived a
        restart and the effect chosen to go after it did not."""
        out = dict(self.settings)
        path = self.plugin_path or self.wanted_plugin
        if path:
            out["plugin"] = path
            values = self.plugin_values() or self.wanted_plugin_values
            if values:
                out["plugin_values"] = dict(values)
        return out


# ---------------------------------------------------------------------------
# On air sound
# ---------------------------------------------------------------------------

#: "Even out the music". Each is a slow leveller in front of the ceiling, and
#: "off" is the ceiling alone. The leveller aims the last ``window`` seconds
#: of the show at ``target`` LUFS (BS.1770 short term loudness is three
#: seconds), moving no faster than ``up`` and ``down`` decibels a second and
#: never further than ``boost`` up or ``cut`` down from where the music was.
#: Gentle is the review's numbers. Firm reaches the same place in roughly
#: half the time and from further away, for a show whose music ranges more.
EVEN_OUT = {
    "off": None,
    "gentle": {"target": -18.0, "window": 3.0, "up": 1.0, "down": 3.0,
               "boost": 6.0, "cut": 10.0},
    "firm": {"target": -18.0, "window": 3.0, "up": 2.0, "down": 6.0,
             "boost": 9.0, "cut": 12.0},
}


def _tp_kernels(half, beta=7.0):
    """Windowed sinc interpolators for the three points between two samples
    at four times the rate: 2 * half taps each, unity at DC."""
    grid = np.linspace(-half, half, 2 * half + 1)
    window = np.kaiser(2 * half + 1, beta)
    out = []
    for t in (0.25, 0.5, 0.75):
        u = t - np.arange(-half + 1, half + 1)
        c = np.sinc(u) * np.interp(u, grid, window)
        out.append((c / c.sum()).astype(np.float64))
    return out


def _sliding_min(values, width):
    """min(values[i:i + width]) for every i that fits, in log2(width) passes."""
    out = values.copy()
    span = 1
    while span * 2 <= width:
        out = np.minimum(out[:-span], out[span:])
        span *= 2
    rest = width - span
    if rest:
        out = np.minimum(out[:len(out) - rest], out[rest:])
    return out


class TruePeakCeiling:
    """`Ceiling`, aimed at the true peak, so "never louder than" means dBTP.

    A sample peak limiter holds every SAMPLE under the ceiling and lets the
    wave between them go over: measured by Mark on a brickwalled master,
    sample peak -2.00 dBFS and true peak -0.22 dBTP. So the peak is looked
    for at four times the rate, the way BS.1770 measures it, with a 24 tap
    interpolator for each point between two samples.

    **The gain is HELD flat over everything that interpolator leans on**,
    C.ONAIR_TP_HALF samples either side of a peak plus C.ONAIR_TP_SMOOTH,
    then averaged over C.ONAIR_TP_SMOOTH, so the attack is a short ramp and
    still at or under what every peak needs. That needs lookahead, 56 samples
    at 48 kHz, 1.2 ms, on the stream, the recorders and the send and nowhere
    near the presenter. About 2.3 ms of work per 250 ms of stereo.

    **What it does not promise.** Measured against soxr's 4x, worst of three
    ten second runs at a -2 ceiling: music mastered to full scale -2.11
    dBTP, the same pushed 6 dB into the ceiling -2.03, but a brickwalled
    master -1.66 and bright noise -0.85. Gains that change from one sample
    to the next, which is what limiting all the time is, lean on samples far
    beyond any short interpolator. Only limiting at four times the rate
    would close that, at several times the cost on four chains at once, so
    Firm, which limits hardest, starts at -3 instead. On Mark's master the
    sample peak ceiling this replaced let through -0.22 dBTP.
    """

    def __init__(self, samplerate, ceiling_db=-2.0, release_ms=100.0):
        from . import constants as C
        self.samplerate = float(samplerate)
        self.ceiling_db = float(ceiling_db)
        self.release_ms = max(1.0, float(release_ms))
        self._half = int(C.ONAIR_TP_HALF)
        self._smooth = int(C.ONAIR_TP_SMOOTH)
        self._hold = self._half + self._smooth
        self._pad = float(C.ONAIR_TP_PAD_DB)
        self._kernels = _tp_kernels(self._half)
        #: How late its output is, in samples.
        self.delay = self._half + self._hold
        self._xkeep = 2 * self._half - 1 + self._hold
        self._gkeep = self._smooth - 1 + 2 * self._hold
        self.reset()

    def reset(self):
        self._x = None
        self._g = np.zeros(self._gkeep)
        self._gain_db = 0.0

    def process(self, block):
        frames = len(block)
        if not frames:
            return block
        H, M, L = self._half, self._hold, self._smooth
        data = np.asarray(block, dtype=np.float64)
        if self._x is None or self._x.shape[1] != data.shape[1]:
            self._x = np.zeros((self._xkeep, data.shape[1]))
        z = np.concatenate([self._x, data])
        self._x = z[-self._xkeep:]
        # The intervals whose interpolation has just become possible: the
        # newest is j to j+1 with j = len(z) - 1 - H.
        first = len(z) - frames - H
        span = z[first - H + 1:first + frames + H]
        env = np.maximum(np.abs(z[first:first + frames]),
                         np.abs(z[first + 1:first + frames + 1])).max(axis=1)
        for kernel in self._kernels:
            for channel in range(z.shape[1]):
                np.maximum(env, np.abs(np.correlate(span[:, channel], kernel,
                                                    mode="valid")), out=env)
        env *= 10.0 ** (self._pad / 20.0)
        ceiling = 10.0 ** (self.ceiling_db / 20.0)
        with np.errstate(divide="ignore"):
            wanted = np.minimum(
                0.0, -20.0 * np.log10(np.maximum(env, 1e-12) / ceiling))
        # Instant attack and the release, exactly as Ceiling does it.
        rise = 20.0 / (self.release_ms * 0.001 * self.samplerate)
        ramp = rise * np.arange(frames, dtype=np.float64)
        seeded = np.empty(frames + 1, dtype=np.float64)
        seeded[0] = self._g[-1] + rise
        seeded[1:] = wanted - ramp
        fresh = np.minimum(ramp + np.minimum.accumulate(seeded)[1:], 0.0)
        g = np.concatenate([self._g, fresh])
        self._g = g[-self._gkeep:]
        self._gain_db = float(g[-1])
        held = _sliding_min(g, 2 * M + 1)
        sums = np.concatenate([[0.0], np.cumsum(held)])
        smoothed = (sums[L:L + frames] - sums[:frames]) / L
        end = len(z) - self.delay
        out = z[end - frames:end]
        return (out * (10.0 ** (smoothed / 20.0))[:, None]).astype(np.float32)


class _Delay:
    """A fixed delay, block by block, so the untouched sound lines up with
    the processed one it is crossfaded against."""

    def __init__(self, frames):
        self.frames = int(frames)
        self._held = None

    def reset(self):
        self._held = None

    def process(self, block):
        if self._held is None or self._held.shape[1] != block.shape[1]:
            self._held = np.zeros((self.frames, block.shape[1]),
                                  dtype=np.float32)
        both = np.concatenate([self._held, block])
        self._held = both[-self.frames:] if self.frames else both[:0]
        return both[:len(block)]


class ProgramChain:
    """The on air sound: a slow leveller, then the true peak ceiling.

    What the listener gets, and only that. One instance each in the stream,
    the audio recorder, the picture recorder and the send, so none shares a
    gain or a window with another and the send's mix minus is processed on
    its own, after both sums are finished. It never touches the presenter's
    output, so nothing between a keypress and a sound has changed.

    **The leveller holds while the music really is ducked** (``held``, which
    the frame answers from the mixers' own duck gains): under the voice or a
    drop the music is meant to be quiet, and a leveller that noticed would
    wind it back up underneath them. A microphone open with ducking off is
    not a duck. It also holds below C.ONAIR_FLOOR_LUFS, so a pause is not
    treated as very quiet music. It measures what arrives, before its own
    gain, so a block's correction never feeds back into its own measurement.

    **Off is a crossfade, and the work goes on.** ``on`` False hands back the
    show untouched, after C.ONAIR_FADE_SECONDS: the compare key used to jump
    10 dB in a sample. The leveller and the ceiling keep running while it is
    off, so coming back lands where they would have been.

    **Nothing that is not a number gets in.** One inf in a glitched file used
    to reach the ceiling, take its gain to minus infinity and silence the
    stream, both recordings and the send for the rest of the session, still
    saying ON AIR. Every block is made finite and bounded on the way in, and
    any state that is not finite is started again.
    """

    def __init__(self, samplerate, even=None, ceiling_db=None, held=None,
                 on=True):
        from . import constants as C
        self.samplerate = int(samplerate)
        self.on = bool(on)
        self.even = even if even in EVEN_OUT else C.DEFAULT_ONAIR_EVEN
        #: A callable answering whether the music is ducked, or None.
        self.held = held
        self._floor = C.ONAIR_FLOOR_LUFS
        self._sane = float(C.ONAIR_SANE_LEVEL)
        self._ceiling = TruePeakCeiling(
            self.samplerate,
            (C.default_onair_ceiling(self.even) if ceiling_db is None
             else ceiling_db),
            C.ONAIR_CEILING_RELEASE_MS)
        self._dry = _Delay(self._ceiling.delay)
        self._fade_frames = max(1, int(C.ONAIR_FADE_SECONDS * self.samplerate))
        #: How much of what goes out is the processed sound, 0 to 1.
        self._wet = 1.0 if self.on else 0.0
        #: Where the leveller has the music, in decibels, and how loud the
        #: last window measured, for a report. Both this instance's own.
        self.gain_db = 0.0
        self.loudness = None
        self._window = []
        self._window_energy = 0.0
        self._window_frames = 0

    @property
    def ceiling_db(self):
        return self._ceiling.ceiling_db

    def configure(self, on=None, even=None, ceiling_db=None):
        """Change a setting on a chain that is running. Takes at the next
        block; the gain it has reached is kept, so nothing jumps."""
        if on is not None:
            self.on = bool(on)
        if even is not None and even in EVEN_OUT:
            self.even = even
        if ceiling_db is not None:
            self._ceiling.ceiling_db = float(ceiling_db)

    def reset(self):
        self.gain_db = 0.0
        self.loudness = None
        self._window = []
        self._window_energy = 0.0
        self._window_frames = 0
        self._ceiling.reset()
        self._dry.reset()

    def _held(self):
        try:
            return bool(self.held()) if self.held is not None else False
        except Exception:
            return False

    def _sanitised(self, block):
        data = np.asarray(block, dtype=np.float32)
        if data.ndim == 1:
            data = data[:, None]
        if not np.all(np.isfinite(data)):
            data = np.nan_to_num(data, nan=0.0, posinf=self._sane,
                                 neginf=-self._sane)
        return np.clip(data, -self._sane, self._sane)

    def process(self, block):
        """One block of the show in, the same length out."""
        if block is None or not len(block):
            return block
        try:
            data = self._sanitised(block)
            if not (np.isfinite(self.gain_db)
                    and np.isfinite(self._ceiling._gain_db)
                    and np.all(np.isfinite(self._ceiling._g))):
                self.reset()
            dry = self._dry.process(data)
            plan = EVEN_OUT.get(self.even)
            wet = self._level(data, plan) if plan is not None else data
            wet = self._ceiling.process(wet)
            aim = 1.0 if self.on else 0.0
            start = self._wet
            if start == aim:
                return wet if aim else dry
            step = len(data) / float(self._fade_frames)
            end = start + max(-step, min(step, aim - start))
            self._wet = end
            mix = np.linspace(start, end, len(data), dtype=np.float32)[:, None]
            return (wet * mix + dry * (1.0 - mix)).astype(np.float32)
        except Exception:
            return block

    def _level(self, block, plan):
        from . import loudness
        frames = len(block)
        rate = float(self.samplerate)
        start = self.gain_db
        aim = start
        if not self._held():
            # Measured only while not held, so the window is the MUSIC's
            # level and not the voice over it or the duck under it.
            energy = loudness.energy(block, rate)
            if np.isfinite(energy):
                self._window.append((energy, frames))
            longest = plan["window"] * rate
            while (len(self._window) > 1
                   and sum(n for _e, n in self._window[1:]) >= longest):
                self._window.pop(0)
            # Summed afresh every block rather than added to and taken from
            # all night, so rounding cannot walk it anywhere.
            self._window_energy = sum(e for e, _n in self._window)
            self._window_frames = sum(n for _e, n in self._window)
            level = loudness.lufs(self._window_energy, self._window_frames)
            self.loudness = level
            if (level is not None and level >= self._floor
                    and self._window_frames >= 0.4 * rate):
                aim = max(-plan["cut"], min(plan["boost"],
                                            plan["target"] - level))
        seconds = frames / rate
        step = (plan["up"] if aim > start else plan["down"]) * seconds
        end = start + max(-step, min(step, aim - start))
        self.gain_db = end
        if start == end:
            if start == 0.0:
                return block
            return block * np.float32(10.0 ** (start / 20.0))
        ramp = 10.0 ** (np.linspace(start, end, frames) / 20.0)
        return (block * ramp[:, None]).astype(np.float32)
