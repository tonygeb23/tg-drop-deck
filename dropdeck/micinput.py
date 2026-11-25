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
from .mixer import all_devices, host_api_names, wasapi_default

#: Where an open microphone came from when it is the system default: Windows'
#: own default, opened through WASAPI shared mode. Never exclusive, which
#: would take the card away from the screen reader.
_ASKED = object()

#: The key the microphone publishes under on the shared DuckBus. Anything but
#: a mixer's own key, which is what the mixers publish their own drops under.
DUCK_KEY = "microphone"

#: The ways Windows offers one microphone, in the order a failed one is
#: retried. WDM-KS is not on the list: it takes the device away from every
#: other program while it is open, which is not something to fall back into.
FALLBACK_APIS = ("Windows WASAPI", "Windows DirectSound", "MME")

#: MME cuts every device name to 31 characters, so the same microphone is
#: "Microphone (Yeti Stereo Microph" there and the full name everywhere else.
MME_NAME_LENGTH = 31

#: What `fell_back_from` says when the microphone asked for was the system
#: default. It cannot be None, because None is "it opened as asked", and a
#: default that would not open was then never mentioned anywhere.
SYSTEM_DEFAULT = "system default"


def input_devices():
    """Every input the machine offers, newest APIs first.

    Same shape and the same ordering as ``mixer.output_devices``: WASAPI at the
    top because that is where the low latency and the virtual cables are.

    Never raises. This runs inside the Ctrl+M handler, and a device list that
    raised there made the key do nothing at all, with nothing said.
    """
    hostapis = host_api_names()
    found = []
    for index, dev in all_devices():
        if dev["hostapi"] >= len(hostapis):
            continue
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


def _same_microphone(a, b):
    """Are two device names the same microphone under two host APIs.

    Equal, or one is the other cut short the way MME cuts every name.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    short, full = sorted((a, b), key=len)
    return len(short) == MME_NAME_LENGTH and full.startswith(short)


def alternatives(device):
    """The same microphone reached another way, best first.

    One physical microphone appears several times over, once per host API,
    and they fail independently: a device another program has taken for
    itself under WASAPI can still be shared under DirectSound or MME, and a
    driver that refuses one format on one path takes it on another. So when
    the chosen one will not open, these are tried before giving up.

    For the system default it is each host API's own default input, since
    PortAudio's default is only ever MME's.
    """
    try:
        hostapis = sd.query_hostapis()
    except Exception:
        return []
    names = [h["name"] for h in hostapis]
    order = {api: rank for rank, api in enumerate(FALLBACK_APIS)}
    devices = input_devices()
    if device is None:
        found = []
        for api in FALLBACK_APIS:
            if api not in names:
                continue
            index = hostapis[names.index(api)].get("default_input_device", -1)
            if isinstance(index, int) and index >= 0:
                found.append(index)
        return found
    here = next((d for d in devices if d["index"] == device), None)
    if here is None:
        return []
    if _ambiguous(here["name"], devices):
        return []
    found = [d for d in devices
             if d["index"] != device and d["hostapi"] in order
             and _same_microphone(d["name"], here["name"])
             and not _ambiguous(d["name"], devices)]
    found.sort(key=lambda d: order[d["hostapi"]])
    return [d["index"] for d in found]


def _default_input_index():
    """The index PortAudio opens for "the system default", or None."""
    try:
        return int(sd.query_devices(kind="input")["index"])
    except Exception:
        return None


def _ambiguous(name, devices):
    """Could this name be more than one microphone.

    MME cuts names to 31 characters, so "Headset Microphone (Plantronics" is
    a BT600 and a Blackwire at once. Mark, 19 September 2026: with the BT600
    refusing, the other headset opened and was announced as the one chosen.
    A cut name counts as a microphone only when exactly one full name starts
    with it and no other MME device carries it.
    """
    if len(name) != MME_NAME_LENGTH:
        return False
    longer = {d["name"] for d in devices
              if len(d["name"]) > MME_NAME_LENGTH
              and d["name"].startswith(name)}
    same_cut = sum(1 for d in devices
                   if d["hostapi"] == "MME" and d["name"] == name)
    return len(longer) > 1 or same_cut > 1


def default_input_name():
    """What Windows' default input is called, WASAPI's spelling first, or "".

    Asked of PortAudio's list, so nothing is opened. MME cuts names to 31
    characters, which is why WASAPI's is the one to compare against.
    """
    try:
        fast = wasapi_default("input")
        info = (sd.query_devices(fast) if fast is not None
                else sd.query_devices(kind="input"))
        return str(info["name"])
    except Exception:
        return ""


def host_api_of(device):
    """The host API a device index belongs to, for saying how it opened."""
    try:
        info = sd.query_devices(device, kind="input") if device is None \
            else sd.query_devices(device)
        return sd.query_hostapis(info["hostapi"])["name"]
    except Exception:
        return ""


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

    **It keeps a target fill, because the two callbacks run on two sound
    cards' clocks and no two clocks agree.** Until the major release after
    3.10.1 it had none: a read took whatever was there and padded the rest
    with zeros, and a write past the end threw the oldest away. Simulated over
    an hour with the clocks 100 ppm apart, a microphone clocked fast arrived
    230 ms late by the end and then ticked as the ring overflowed, and one
    clocked slow ticked with a run of zeros roughly every twenty seconds.

    So, the way `send.Send` does it: nothing is read until the ring holds a
    read, a write and a margin (`primed`). Over each window the lowest
    margin left after a read is noted; more than C.RING_SLACK_HIGH_SECONDS
    over the margin and the excess is DROPPED, too little and a few
    milliseconds are played twice. Either is one C.RING_SPLICE_SECONDS
    crossfade at the point that best matches (`_best`), so a steady tone
    comes through a correction without a step or a dip. A writer that really
    stops is a hole, and what is left fades to silence rather than stopping
    dead, and fades back in once the ring has primed again.

    This is drop and repeat, not resampling. At 100 ppm it is one splice
    every forty to seventy seconds and the delay stays between 2 and 22 ms.
    On a steady tone at 220 Hz or above a splice cannot be measured; on a
    pure 100 Hz tone it is a dip of about a decibel for five milliseconds.
    An adaptive resampler would hide even that, at the cost of a filter
    running in every callback for a correction that is this rare.
    """

    def __init__(self, frames=None, rate=None):
        self.buf = np.zeros((frames or C.MIC_RING_FRAMES, CHANNELS),
                            dtype=np.float32)
        #: The rate the ring is READ at, which is what turns the seconds
        #: below into frames. Kept in step by whoever owns the ring.
        self.rate = int(rate or C.DEFAULT_SAMPLERATE)
        self.write_at = 0
        self.available = 0
        #: Corrections made, for a report and for the tests.
        self.drops = 0
        self.inserts = 0
        self.holes = 0
        #: Reads that came up a few milliseconds short and were made whole
        #: with a repeat instead of a hole. See _rescued.
        self.rescues = 0
        self._last_rescue = None
        self._reads = 0
        self._restart()

    def _restart(self):
        self.primed = False
        self._fresh = False
        self._largest_write = 0
        #: Added to the margin by every hole, a write at a time, up to two.
        #: A read that is an exact multiple of the write locks the two in
        #: step, and then jitter now and again swaps which comes first: a
        #: whole write's worth of shortfall the window never saw coming.
        #: Simulated, 1024 frame reads against 512 frame writes: 8 holes in
        #: a quarter of an hour without this. Forgotten when the ring is.
        self._extra = 0
        self._window_left = 0
        self._window_low = None
        self._fix = 0
        self._low = 0
        self._last_rescue = None

    def _frames(self, seconds):
        return max(1, int(round(seconds * self.rate)))

    def clear(self):
        self.buf[:] = 0.0
        self.write_at = 0
        self.available = 0
        self._restart()

    def write(self, block):
        room = len(self.buf)
        count = min(len(block), room)
        if count > self._largest_write:
            self._largest_write = count
        end = self.write_at + count
        if end <= room:
            self.buf[self.write_at:end] = block[:count]
        else:
            first = room - self.write_at
            self.buf[self.write_at:] = block[:first]
            self.buf[:end - room] = block[first:count]
        self.write_at = end % room
        self.available = min(room, self.available + count)

    def _peek(self, offset, count):
        """``count`` frames from ``offset`` past the read point. A copy.

        A negative offset is audio already read, which stays in the buffer
        until a write comes round to it. That is what a repeat is made of.
        """
        room = len(self.buf)
        start = (self.write_at - self.available + offset) % room
        end = start + count
        if end <= room:
            return self.buf[start:end].copy()
        return np.concatenate([self.buf[start:], self.buf[:end - room]])

    def _take(self, count):
        block = self._peek(0, count)
        self.available -= count
        return block

    def read(self, frames):
        out = np.zeros((frames, CHANNELS), dtype=np.float32)
        if frames <= 0:
            return out
        margin = self._frames(C.RING_MARGIN_SECONDS) + self._extra
        splice = min(self._frames(C.RING_SPLICE_SECONDS), frames // 2)
        if not self.primed:
            # One read, one write and the margin. Less, and the first window
            # runs dry before the floor has been measured.
            need = frames + self._largest_write + margin
            if need > len(self.buf):
                # Bigger than the ring can ever hold, so it could never
                # prime and would be silence for ever. It is handed whatever
                # there is, as the ring always did.
                need = 1
            if self.available < need:
                return out
            self.primed = True
            self._fresh = True
            self._window_left = self._frames(C.RING_WINDOW_SECONDS)
            self._window_low = None
            self._fix = 0
        self._reads += frames
        if self.available < frames:
            rescued = self._rescued(frames, splice, margin)
            if rescued is not None:
                return rescued
            # The writer stopped. What is here fades out so the gap is a
            # silence and not a click, and the ring primes again.
            have = self.available
            if have:
                out[:have] = self._take(have)
                fade = max(1, min(have // 2 if self._fresh else have, splice))
                out[have - fade:have] *= np.linspace(
                    1.0, 0.0, fade, dtype=np.float32)[:, None]
                if self._fresh:
                    out[:fade] *= np.linspace(0.0, 1.0, fade,
                                              dtype=np.float32)[:, None]
            self._fresh = False
            self.holes += 1
            self.primed = False
            self._extra = min(self._extra + self._largest_write,
                              2 * self._largest_write)
            return out
        slack = self.available - frames
        if self._window_low is None or slack < self._window_low:
            self._window_low = slack
        self._window_left -= frames
        if self._window_left <= 0:
            self._decide(margin)
        if self._fix and splice >= 16:
            out[:] = self._spliced(frames, splice)
        else:
            out[:] = self._take(frames)
        if self._fresh:
            fade = max(1, splice)
            out[:fade] *= np.linspace(0.0, 1.0, fade,
                                      dtype=np.float32)[:, None]
            self._fresh = False
        return out

    def _rescued(self, frames, splice, margin):
        """A read a little short, made whole by playing a few ms twice.

        Mark, 24 November 2026: with one callback in a hundred 4 ms late, a
        microphone clocked 30 to 100 ppm slow still met one read an hour that
        found the ring a few milliseconds short, and that was a 21 ms hole.
        Every hole also taught the ring a whole write more margin, 10.7 ms
        more delay in the presenter's ears for the rest of the session.

        So a read that is short while the ring is running, with at least a
        crossfade's worth to hand, is filled from audio already played, at
        the point that best matches, crossfaded in exactly as an insert is:
        the shortfall plus the whole margin, so the next read is not short
        too. No margin is learnt from one. A second within a minute is no
        longer a hiccup, so that one teaches the ring a write more margin,
        as a hole does. A short read within a window of a rescue is a writer
        that has really stopped, and is a hole, as it always was. Returns
        None when it cannot be done.
        """
        have = self.available
        short = frames - have
        splice = min(splice, have)
        if not self.primed or self._fresh or splice < 32:
            return None
        since = (None if self._last_rescue is None
                 else self._reads - self._last_rescue)
        if since is not None and since < self._frames(C.RING_WINDOW_SECONDS):
            return None
        search = self._frames(C.RING_SEARCH_SECONDS)
        history = len(self.buf) - have - splice
        least = short + margin
        most = min(least + search, history)
        if most < least:
            return None
        head = self._peek(0, splice)
        span = self._peek(-most, most - least + splice)
        back = most - self._best(head, span, splice)
        incoming = self._peek(-back, frames)
        self.available -= frames - back
        up = np.linspace(0.0, 1.0, splice, dtype=np.float32)[:, None]
        incoming[:splice] = head * (1.0 - up) + incoming[:splice] * up
        if since is not None and since < 60 * self.rate:
            self._extra = min(self._extra + self._largest_write,
                              2 * self._largest_write)
        self.rescues += 1
        self._last_rescue = self._reads
        self._fix = 0
        return incoming

    def _decide(self, margin):
        """At the end of a window: is the ring holding too much, or too little."""
        low = self._window_low
        self._window_left = self._frames(C.RING_WINDOW_SECONDS)
        self._window_low = None
        if low is None:
            return
        # The lowest the window went is what a drop is measured against: the
        # fill at the moment of the drop may be a whole write above it.
        self._low = low
        if low > margin + self._frames(C.RING_SLACK_HIGH_SECONDS):
            self._fix = low - margin
        elif low < self._frames(C.RING_SLACK_LOW_SECONDS) + self._extra:
            self._fix = -(margin - low)

    def _spliced(self, frames, splice):
        """One read with a correction in it: a drop, or a repeat.

        The length is the asked for one give or take C.RING_SEARCH_SECONDS,
        which is half the period of a 100 Hz voice either way, so there is
        nearly a whole period to land on. Never under half what was asked,
        or a slow tone's near perfect match one sample along wins every time
        and nothing is corrected. And always landing INSIDE the band: a drop
        leaves at least half the margin under the window's leanest read, and
        a repeat stops short of the level that would set off a drop. Landing
        on the edges ping ponged between the two, and one drop to the very
        bottom met a slow clock and made a hole.
        """
        fix, self._fix = self._fix, 0
        search = self._frames(C.RING_SEARCH_SECONDS)
        margin = self._frames(C.RING_MARGIN_SECONDS) + self._extra
        head = self._peek(0, splice)
        want = abs(fix)
        least = max(1, want // 2, want - search)
        if fix > 0:
            most = min(want + search, self.available - frames,
                       self._low - margin // 2)
        else:
            most = min(want + search, len(self.buf) - self.available - splice,
                       margin + self._frames(C.RING_SLACK_HIGH_SECONDS)
                       - self._low)
        if most < least:
            least = most = min(want, most)
        if most < 1:
            return self._take(frames)
        if fix > 0:
            span = self._peek(least, most - least + splice)
            skip = least + self._best(head, span, splice)
            incoming = self._peek(skip, frames)
            self.available -= skip + frames
            self.drops += 1
        else:
            span = self._peek(-most, most - least + splice)
            back = most - self._best(head, span, splice)
            incoming = self._peek(-back, frames)
            self.available -= frames - back
            self.inserts += 1
        up = np.linspace(0.0, 1.0, splice, dtype=np.float32)[:, None]
        incoming[:splice] = head * (1.0 - up) + incoming[:splice] * up
        return incoming

    @staticmethod
    def _best(head, span, splice):
        """Where in ``span`` the audio most resembles ``head``. An index.

        Normalised cross correlation over the splice length, so a crossfade
        between two segments of a steady tone lands in phase rather than
        half cancelling. Silence matches anywhere, and gets the first.
        """
        a = head.sum(axis=1).astype(np.float64)
        s = span.sum(axis=1).astype(np.float64)
        if len(s) <= splice or not np.any(a):
            return 0
        dots = np.correlate(s, a, mode="valid")
        energy = np.concatenate([[0.0], np.cumsum(s * s)])
        norms = np.sqrt(np.maximum(energy[splice:] - energy[:-splice], 0.0))
        return int(np.argmax(dots / (norms + 1e-9)))


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

    #: Silenced by hand from the source control list, and soloed there.
    #: Neither is saved: both are things you do during a show.
    muted = False
    soloed = False

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
        #: Which part of a stereo input carries the voice.
        #:
        #: The microphone used to be opened with channels=1, which takes the
        #: FIRST channel and nothing else. That is right for a headset and
        #: wrong for the way a lot of broadcasters actually work: a hardware
        #: mixer's output arrives as a stereo pair on a line input, and if
        #: the voice is on the right, or the left is a different source
        #: entirely, one channel is all you get and it is the wrong one.
        #:
        #: JamminJerry, on Mastodon, 4 September 2026, with four sound cards
        #: into a mixer: "I can't get my microphone from my mixer on the air
        #: though." See C.MIC_CHANNELS for the four keys.
        self.channel = C.DEFAULT_MIC_CHANNEL
        #: In "voice", whether a side that is all but silent is left out.
        #:
        #: A microphone on input 1 of a two input interface used to arrive
        #: 6 dB down, because both sides were averaged, and input 2 is
        #: nothing but that preamp's hiss. So when one side is
        #: C.MIC_SIDE_SPLIT_DB quieter than the other for about a second,
        #: the louder side is taken alone, gliding across so nothing
        #: clicks, and the average comes back only once both are within
        #: C.MIC_SIDE_JOIN_DB again. The gap between those two numbers, and
        #: the second it has to hold for, are what stop it flapping.
        #:
        #: The microphone's only. A source turns it off: program audio in
        #: stereo is allowed one side well down for a second, a hard panned
        #: intro, and jumping 6 dB there would be wrong. A source chooses
        #: its side in the Sources window instead.
        self.pick_louder = True
        self._side = None
        self._side_env = None
        self._side_floor = None
        self._side_quick = False
        self._side_held = 0.0
        self._side_for = _ASKED
        self._side_weights = (0.5, 0.5)
        self.monitor = bool(monitor)
        self.stream = None
        self.last_error = None
        #: The system default came in through MME because WASAPI would not
        #: open it. Said once by the frame: MME is the slow way in.
        self.default_by_mme = False
        #: The index the open stream really uses. None is PortAudio's own
        #: default, which is MME's.
        self._opened = None
        #: Duck while talking: whether to listen for the voice at all, and
        #: whether it is above the gate threshold right now (with its hold).
        #: Off unless the board asks, and published on the duck bus so the
        #: mixers can take the music a little further down. See Mixer.
        self.talk_detect = False
        self.talking = False
        self._talk_left = 0
        #: The device that was asked for, when a different way of reaching the
        #: same microphone is what actually opened. None when it opened as
        #: asked. Said out loud, because a microphone that opened by another
        #: route is still worth knowing about.
        self.fell_back_from = None
        #: Counted by the capture callback since the last open, so the app can
        #: tell "nothing arrived" from "silence arrived" from "a voice
        #: arrived". A real microphone is never digitally silent.
        self.blocks_seen = 0
        self.signal_seen = False
        #: Goes up by one every time the microphone opens, so a check
        #: scheduled for one opening can tell it is not looking at a later one.
        self.openings = 0
        #: How many channels the device was actually opened with.
        self.channels_open = 1
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

        **The voice chain follows too**, because it runs on the audio AFTER
        it has been converted to this rate. It used to keep the rate it was
        built at, so on a 96 kHz card every filter sat an octave up: the
        80 Hz high pass cut at 160 and the voice went thin. `_reset_ring`
        does it, which both branches below reach.
        """
        rate = int(rate or C.DEFAULT_SAMPLERATE)
        if rate == self.output_rate:
            self._chain_follows()
            return False
        self.output_rate = rate
        if self.is_open:
            self.start()          # reopens, and rebuilds the resampler
        else:
            self._reset_ring()
        return True

    # ------------------------------------------------------------ opening --
    def candidate_rates(self, index=_ASKED):
        """Rates to try, best first.

        The output's rate first, because matching it means no resampling at
        all. Then what the microphone itself says it wants, then the two rates
        every device on earth supports. Duplicates removed, order kept.
        """
        device = self.device if index is _ASKED else index
        wanted = [self.output_rate, input_rate(device), 48000, 44100]
        seen = []
        for rate in wanted:
            rate = int(rate or 0)
            if rate > 0 and rate not in seen:
                seen.append(rate)
        return seen

    def _channel_counts(self, index=_ASKED):
        """How many channels to ask the device for, best first."""
        device = self.device if index is _ASKED else index
        try:
            info = sd.query_devices(device)
            most = int(info.get("max_input_channels", 1))
        except Exception:
            most = 2
        return [2, 1] if most >= 2 else [1]

    def _try_open(self, channels, rate, failures, index=_ASKED):
        """One attempt at one shape. True if the microphone is now running.

        ``index`` is the device to open when it is not `self.device`, which
        is only ever the system default being reached through WASAPI.
        """
        stream = None
        before = (self.samplerate, self.channels_open)
        device = self.device if index is _ASKED else index
        try:
            stream = sd.InputStream(
                device=device,
                samplerate=rate,
                channels=channels,
                dtype="float32",
                blocksize=C.BLOCKSIZE,
                latency="low",
                callback=self._callback,
            )
            # The rate and the resampler are settled BEFORE the stream starts,
            # so its first callback already resamples from the right rate.
            # And all of it is inside the guard, which matters: this used to
            # run after it, so anything it raised left a RUNNING stream behind
            # with the state half set, escaped the key handler, and every
            # later Ctrl+M raised again on its way through: a key that did
            # nothing, on or off, with nothing said anywhere.
            self.samplerate = rate
            self.channels_open = channels
            self._reset_ring()
            # Counted from here, before the callback can run, so the first
            # blocks of this opening are never credited to the last one.
            self.blocks_seen = 0
            self.signal_seen = False
            # Which side carries the voice belongs to a DEVICE, so it is kept
            # across Ctrl+M and judged again only for another microphone.
            if device != self._side_for:
                self._side = None
                self._side_env = None
                self._side_floor = None
                self._side_held = 0.0
                self._side_weights = (0.5, 0.5)
                self._side_for = device
            self._opened = device
            stream.start()
            self.stream = stream
            self._publish(True)
        except Exception as exc:  # no microphone, in use, rate or shape refused
            failures.append("%d Hz, %d channel: %s" % (rate, channels, exc))
            if stream is not None:
                try:
                    stream.abort()
                    stream.close()
                except Exception:
                    pass
            self.stream = None
            self.samplerate, self.channels_open = before
            return False
        self.last_error = None
        self.openings += 1
        return True

    def _open_any_shape(self, failures, index=_ASKED):
        """Every channel count and rate, on whatever self.device is."""
        # Two channels where the device has them, so a mixer feeding a stereo
        # pair can have either side or both, and one where it does not. Two is
        # tried first and one is the fallback, because a working microphone on
        # the wrong channel beats no microphone at all.
        for wanted in self._channel_counts(index):
            for rate in self.candidate_rates(index):
                if self._try_open(wanted, rate, failures, index):
                    return True
        return False

    def start(self, device=None, other_routes=True):
        """Open the microphone. Returns True if it is actually running.

        Nothing opens a microphone on its own: this is only ever called
        because somebody pressed the key. An app that quietly turned a
        microphone on at startup would be a different kind of program.

        If the device will not open at all, the SAME microphone is tried
        through the other ways Windows offers it (see `alternatives`) before
        this gives up, and `fell_back_from` says so. It is never a different
        microphone: somebody who chose the one on their desk does not want
        the one in their laptop lid switched on behind their back.
        """
        if device is not None:
            self.device = device
        self.stop()
        self.fell_back_from = None
        self.default_by_mme = False

        failures = []
        asked = self.device
        # The system default, through WASAPI shared mode FIRST. PortAudio's
        # own default is MME's, and MME is the slow way in: measured on the
        # output side, about 200 ms against 22 for the same card. Shared, never
        # exclusive, because exclusive takes the card from every other
        # program, the screen reader included. MME only if that will not open.
        fast = wasapi_default("input") if asked is None else None
        if fast is not None and self._open_any_shape(failures, fast):
            return True
        if self._open_any_shape(failures):
            self.default_by_mme = fast is not None
            return True

        if other_routes:
            # The system default IS a device, MME's default input, and it has
            # just been tried under its own index as well as under None.
            tried = {asked, _default_input_index() if asked is None else asked,
                     fast}
            for index in alternatives(asked):
                if index in tried:
                    continue
                tried.add(index)
                self.device = index
                if self._open_any_shape(failures):
                    self.fell_back_from = (SYSTEM_DEFAULT if asked is None
                                           else asked)
                    return True
            self.device = asked

        self.stream = None
        # Every rate, not just the last one. "Invalid sample rate" on its own
        # does not say which rates were tried, which is the only useful part.
        self.last_error = "; ".join(failures) or "no microphone available"
        self._publish(False)
        return False

    @property
    def opened_via(self):
        """Which of Windows' ways in the open microphone is using."""
        if not self.is_open:
            return ""
        return host_api_of(self._opened)

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
        self._say_talking(False)
        try:
            self._reset_ring()
        except Exception:
            # Closing has to work whatever state the last opening left behind,
            # or the key that turns the microphone off stops working too.
            self._resampler = None
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
            # Both are read at the output's rate, which is what their fill
            # targets are measured in.
            self._monitor.rate = self._air.rate = self.output_rate
        # The resampler is NOT conditional on there being a voice chain. It
        # ended up nested inside that check when the processing went in, so a
        # copy without pedalboard had no resampler at all and the microphone
        # went into the rings at its own rate while being drained at the
        # output's: monitoring and broadcasting sharp or flat by however far
        # the two differ.
        with self._lock:
            if self.samplerate != self.output_rate:
                self._resampler = soxr.ResampleStream(
                    self.samplerate, self.output_rate, CHANNELS,
                    dtype="float32")
            else:
                self._resampler = None
        chain = self.chain
        if chain is not None:
            self._chain_follows()
            # Envelopes and filters remember the last thing they heard, and
            # the last thing they heard was a different microphone.
            chain.reset()

    def _chain_follows(self):
        """Put the voice chain on the rate it is really fed at. See
        set_output_rate."""
        chain = self.chain
        follow = getattr(chain, "set_samplerate", None)
        if follow is not None:
            try:
                follow(self.output_rate)
            except Exception:
                pass

    def _callback(self, indata, frames, time_info, status):
        if status:
            self.overruns += 1
        block = np.asarray(indata, dtype=np.float32)
        if block.ndim == 2:
            if block.shape[1] >= 2:
                # Which half of a stereo input the voice is actually on.
                # Both sides are averaged rather than summed, so choosing
                # both never makes a centred voice 6 dB louder than a side.
                if self.channel == "left":
                    block = block[:, 0]
                elif self.channel == "right":
                    block = block[:, 1]
                else:
                    block = self._mix_down(block[:, :2])
            else:
                block = block[:, 0]
        block = block * self.gain
        peak = float(np.abs(block).max()) if frames else 0.0
        self.peak = peak
        self.blocks_seen += 1
        if peak > 0.0:
            self.signal_seen = True
        if not self.monitor and not self.on_air and not self.talk_detect:
            return
        # One channel up the middle of both. Written into the rings under the
        # lock; each reader drains its own from its own callback.
        stereo = np.repeat(block[:, None], CHANNELS, axis=1)
        # Resampled OUTSIDE the lock. soxr allocates, and the output callback
        # takes this same lock to read the monitor, so holding it across the
        # resample couples two real time threads: a hitch on the microphone
        # thread became a hitch in the show. The resampler is only ever
        # touched by this callback and by _reset_ring, which stops the stream
        # first, so it needs no lock of its own.
        resampler = self._resampler
        if resampler is not None:
            # The microphone and the speakers are on different clocks and
            # different rates. Resampled once here, so both readers only ever
            # deal in the output's rate and can add it straight in.
            try:
                stereo = resampler.resample_chunk(stereo)
            except Exception:
                return
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
        if self.talk_detect:
            self._listen_for_talk(stereo)

        with self._lock:
            if self.monitor:
                self._monitor.write(stereo)
            if self.on_air:
                self._air.write(stereo)

    def _mix_down(self, pair):
        """Both sides averaged, or the louder one alone, on a two channel
        input. "voice" picks the side with a voice on it (`pick_louder`).
        "mix" is the plain average, every block, with no side ever picked
        and the weights never moving: what 3.10.1's "Both, mixed together"
        did and the Mac's "mix" does, so a board saved with it sends exactly
        what it did. Never raises, being in the callback.
        """
        try:
            if not self.pick_louder or self.channel != "voice":
                return pair.mean(axis=1)
            side = self._judge_sides(pair)
            if side is None:
                want = (0.5, 0.5)
            else:
                want = (1.0, 0.0) if side == 0 else (0.0, 1.0)
            have = self._side_weights
            if have == want:
                self._side_quick = False
                return pair[:, 0] * want[0] + pair[:, 1] * want[1]
            frames = len(pair)
            # A second voice coming in is let in at once; see _judge_sides.
            glide = (C.MIC_SIDE_JOIN_GLIDE_SECONDS if self._side_quick
                     else C.MIC_SIDE_GLIDE_SECONDS)
            step = frames / float(max(1, int(glide * self.samplerate)))
            moved = tuple(h + max(-step, min(step, w - h))
                          for h, w in zip(have, want))
            left = np.linspace(have[0], moved[0], frames, dtype=np.float32)
            right = np.linspace(have[1], moved[1], frames, dtype=np.float32)
            close = all(abs(m - w) < 1e-6 for m, w in zip(moved, want))
            self._side_weights = want if close else moved
            return pair[:, 0] * left + pair[:, 1] * right
        except Exception:
            return pair.mean(axis=1)

    def _judge_sides(self, pair):
        """Which side carries the voice: 0, 1, or None for both.

        Each side's level is smoothed over C.MIC_SIDE_SMOOTH_SECONDS, and a
        change is only made once the evidence has pointed the same way for
        C.MIC_SIDE_HOLD_SECONDS of sound. Silence on both decides nothing,
        so a pause between sentences never puts the hiss back.

        **Leaving one side out is slow and letting it back in is not.** Two
        people on inputs 1 and 2 take turns, and the second one used to sit
        under the mix for two seconds of every turn, measured by Mark on 24
        November 2026. So the moment the side left out rises
        C.MIC_SIDE_RISE_DB above its own noise floor, and is no longer
        C.MIC_SIDE_SPLIT_DB under the side kept, both come back within a
        block. The second test is what keeps a mic that only hears the other
        person's bleed, a steady 18 dB under them, from flapping.
        """
        frames = len(pair)
        if not frames:
            return self._side
        power = np.mean(pair.astype(np.float64) ** 2, axis=0)
        if not np.all(np.isfinite(power)):
            # A broken sample decides nothing and is not remembered, or the
            # smoothed levels would be NaN for the rest of the session.
            return self._side
        fast = 10.0 * np.log10(np.maximum(power, 1e-12))
        floor = self._side_floor
        seconds = frames / float(self.samplerate)
        if (self._side is not None and floor is not None):
            other = 1 - self._side
            if (fast[other] > floor[other] + C.MIC_SIDE_RISE_DB
                    and fast[other] > fast[self._side] - C.MIC_SIDE_SPLIT_DB
                    and fast[other] > C.MIC_SIDE_FLOOR_DB):
                self._side = None
                self._side_held = 0.0
                self._side_quick = True
                self._side_env = power
                self._side_floor = np.minimum(floor, fast)
                return None
        # The noise floor: falls at once to anything quieter, creeps up at
        # C.MIC_SIDE_FLOOR_RISE_DB a second, so it is what a side sounds
        # like with nobody talking into it.
        self._side_floor = (fast.copy() if floor is None else np.minimum(
            floor + C.MIC_SIDE_FLOOR_RISE_DB * seconds, fast))
        env = self._side_env
        if env is not None and not np.all(np.isfinite(env)):
            env = None
        if env is None:
            env = power
        else:
            keep = np.exp(-frames / (C.MIC_SIDE_SMOOTH_SECONDS
                                     * float(self.samplerate)))
            env = env * keep + power * (1.0 - keep)
        self._side_env = env
        level = 10.0 * np.log10(np.maximum(env, 1e-12))
        if float(level.max()) < C.MIC_SIDE_FLOOR_DB:
            return self._side
        louder = 0 if level[0] >= level[1] else 1
        apart = abs(float(level[0] - level[1]))
        if self._side is None:
            moving, towards = apart >= C.MIC_SIDE_SPLIT_DB, louder
        elif louder != self._side and apart >= C.MIC_SIDE_SPLIT_DB:
            moving, towards = True, louder
        else:
            moving, towards = apart < C.MIC_SIDE_JOIN_DB, None
        if not moving:
            self._side_held = 0.0
            return self._side
        self._side_held += frames / float(self.samplerate)
        if self._side_held >= C.MIC_SIDE_HOLD_SECONDS:
            self._side = towards
            self._side_held = 0.0
        return self._side

    def _listen_for_talk(self, block):
        """Is the processed voice above the gate threshold, with a hold.

        Only ever takes the music FURTHER down than the open microphone
        already has it, so a word that starts before this notices is never
        clipped: the floor was down before it was spoken.
        """
        frames = len(block)
        if not frames:
            return
        try:
            threshold = float(self.chain.settings.get(
                "gate_threshold", C.TALK_THRESHOLD_DB))
        except Exception:
            threshold = C.TALK_THRESHOLD_DB
        power = float(np.mean(block[:, 0].astype(np.float64) ** 2))
        if not np.isfinite(power):
            return            # a broken block says nothing about a voice
        if 10.0 * np.log10(max(power, 1e-12)) > threshold:
            self._talk_left = int(C.TALK_HOLD_SECONDS * self.output_rate)
        else:
            self._talk_left = max(0, self._talk_left - frames)
        self._say_talking(self._talk_left > 0)

    def _say_talking(self, talking):
        if not talking:
            self._talk_left = 0
        if talking == self.talking:
            return
        self.talking = talking
        publish = getattr(self.duck_bus, "publish_talk", None)
        if publish is not None:
            publish(DUCK_KEY, talking)

    def read(self, frames):
        """Drain up to ``frames`` of monitored audio. Never blocks.

        Returns a (frames, CHANNELS) block, zero-padded when the microphone has
        not produced enough yet. Two streams have two clocks and they drift; a
        monitor running dry has to be silence for a moment, never a stall in
        the output callback that would take the music with it.
        """
        if not self.monitor or not self.is_open:
            self._forget(self._monitor)
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            return self._monitor.read(frames)

    def _forget(self, ring):
        """A tap nobody is taking starts again from empty, so turning it back
        on primes afresh rather than playing what was left in it."""
        if ring.available or ring.primed:
            with self._lock:
                ring.clear()

    def read_air(self, frames):
        """The same, for the stream. Its own tap, drained independently.

        Monitoring and broadcasting are different questions and each reader
        takes what it reads away, so the answer to one cannot come out of the
        other's ring.
        """
        if not self.on_air or not self.is_open:
            self._forget(self._air)
            return np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            return self._air.read(frames)
