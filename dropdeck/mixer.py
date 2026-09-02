"""The output stream and everything that plays into it.

The mixer owns the sound card. It knows how to start a slot, stop a slot, duck
the beds under a drop, and stop the world. It does not know what a button is.

It can also run with no sound card at all (``open_stream=False``), which is how
the tests drive it: call ``render`` yourself and inspect the samples.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

import numpy as np
import sounddevice as sd

from . import constants as C
from .engine import (CHANNELS, MemoryVoice, StreamVoice, db_to_gain, load_audio,
                     probe)

#: Decoded audio we keep around so a repeat press is instant. Short sounds only.
_CACHE_BUDGET_BYTES = 256 * 1024 * 1024


def output_devices():
    """Every output the machine offers, newest APIs first.

    Returns a list of dicts with ``index``, ``name``, ``hostapi``, ``channels``
    and ``samplerate``. WASAPI is listed first because it is the one with the
    low latency and the virtual cables people actually want.
    """
    hostapis = [h["name"] for h in sd.query_hostapis()]
    found = []
    for index, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] < 1:
            continue
        found.append({
            "index": index,
            "name": dev["name"],
            "hostapi": hostapis[dev["hostapi"]],
            "channels": dev["max_output_channels"],
            "samplerate": int(dev["default_samplerate"]),
        })
    preferred = {"Windows WASAPI": 0, "Windows DirectSound": 1, "MME": 2}
    found.sort(key=lambda d: (preferred.get(d["hostapi"], 3), d["name"].lower()))
    return found


def describe_device(device):
    """A spoken-friendly name for one device index, or the system default."""
    if device is None:
        try:
            info = sd.query_devices(kind="output")
            return f"{info['name']} (system default)"
        except Exception:
            return "system default"
    try:
        info = sd.query_devices(device)
        api = sd.query_hostapis(info["hostapi"])["name"]
        return f"{info['name']} ({api})"
    except Exception:
        return "unknown device"


class DuckBus:
    """Which outputs currently have something loud on them.

    Ducking used to be a private matter inside one mixer, because there was only
    ever one. Once banks can go to different sound cards, the beds may be on a
    different device from the drop that is supposed to duck them - and a mixer
    looking only at its own voices would quietly stop ducking at all.

    So every mixer publishes whether it has a non-bed voice running, and every
    mixer asks the bus rather than itself. With a single output this is exactly
    the old behaviour.
    """

    def __init__(self):
        self._loud = {}
        self._lock = threading.Lock()

    def publish(self, key, loud):
        with self._lock:
            self._loud[key] = bool(loud)

    def forget(self, key):
        with self._lock:
            self._loud.pop(key, None)

    @property
    def loud(self):
        with self._lock:
            return any(self._loud.values())


class Mixer:
    """Sums every playing voice into one output stream."""

    def __init__(self, device=None, open_stream=True, samplerate=None,
                 duck_bus=None, key=None):
        self._lock = threading.Lock()
        self._voices = []
        self._cache = OrderedDict()
        self._cache_bytes = 0

        self.device = device
        self.samplerate = samplerate or self._device_rate(device)
        self.stream = None
        self.last_error = None

        # With no bus supplied a mixer gets a private one, so a lone Mixer
        # behaves exactly as it always did and every existing test still
        # constructs one the same way.
        self.duck_bus = duck_bus if duck_bus is not None else DuckBus()
        self.key = key if key is not None else id(self)

        self.sfx_gain = C.DEFAULT_SFX_VOLUME
        self.bed_gain = C.DEFAULT_BED_VOLUME
        self.playlist_gain = C.DEFAULT_PLAYLIST_VOLUME
        self.ducking = True
        self.duck_db = C.DEFAULT_DUCK_DB

        #: Bed fades, in seconds, both settable - see board.bed_fade_in. Zero
        #: in means the bed starts at full level on its first sample, which is
        #: what a cued music bed has to do.
        self.bed_fade_in = C.FADE_IN_BED
        self.bed_fade_out = C.FADE_OUT_BED

        #: A microphone being monitored, or None. Anything with a
        #: read(frames) that never blocks will do; see micinput.MicInput.
        self.monitor_source = None

        self._duck = 1.0
        self.peak = 0.0
        self.underruns = 0

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
            return 48000

    def start(self):
        """Open the output stream. Returns True if audio is actually running."""
        self.stop_stream()
        try:
            self.stream = sd.OutputStream(
                device=self.device,
                samplerate=self.samplerate,
                channels=CHANNELS,
                dtype="float32",
                blocksize=C.BLOCKSIZE,
                callback=self._callback,
            )
            self.stream.start()
            self.last_error = None
            return True
        except Exception as exc:  # no sound card, device in use, wrong rate
            self.stream = None
            self.last_error = str(exc)
            return False

    @property
    def is_running(self):
        """Is audio actually coming out of this mixer."""
        return self.stream is not None

    def stop_stream(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def set_device(self, device):
        """Move to another output. Anything playing is stopped first."""
        self.stop_all(fade_out=0.0)
        self.device = device
        self.samplerate = self._device_rate(device)
        self._clear_cache()          # cached audio was resampled for the old rate
        return self.start()

    def close(self):
        self.stop_all(fade_out=0.0)
        self.stop_stream()
        self.duck_bus.forget(self.key)

    # ---------------------------------------------------------------- cache --
    def _clear_cache(self):
        self._cache.clear()
        self._cache_bytes = 0

    def _cached(self, path):
        data = self._cache.get(path)
        if data is not None:
            self._cache.move_to_end(path)
            return data
        data = load_audio(path, self.samplerate)
        self._cache[path] = data
        self._cache_bytes += data.nbytes
        while self._cache_bytes > _CACHE_BUDGET_BYTES and len(self._cache) > 1:
            _, evicted = self._cache.popitem(last=False)
            self._cache_bytes -= evicted.nbytes
        return data

    # ------------------------------------------------------------ transport --
    def play(self, slot_index, path, *, is_bed=False, bus=None, loop=False,
             trim_db=0.0, name="", duration=None, fade_in=None, fade_out=None):
        """Start a sound. Returns the Voice, or None if the file would not open."""
        if duration is None:
            try:
                duration = probe(path)[0]
            except Exception as exc:
                self.last_error = str(exc)
                return None

        bus = bus or (C.BUS_BED if is_bed else C.BUS_SFX)
        if fade_in is None:
            fade_in = self.bed_fade_in if bus == C.BUS_BED else C.FADE_IN_SFX
        if fade_out is None:
            fade_out = self.bed_fade_out if bus == C.BUS_BED else C.FADE_OUT_SFX

        gain = self.bus_gain(bus) * db_to_gain(trim_db)
        common = dict(slot_index=slot_index, gain=gain, loop=loop, name=name,
                      fade_in=fade_in, fade_out=fade_out, rate=self.samplerate,
                      bus=bus)
        try:
            if duration and duration <= C.PRELOAD_SECONDS:
                voice = MemoryVoice(self._cached(path), **common)
            else:
                voice = StreamVoice(path, **common)
        except Exception as exc:
            self.last_error = str(exc)
            return None

        with self._lock:
            self._voices.append(voice)
        return voice

    def stop_slot(self, slot_index, fade_out=None, also_releasing=False):
        """Fade out every voice belonging to one slot.

        ``also_releasing`` re-releases a voice that is already on its way out,
        with the shorter fade. That matters mid-crossfade: the outgoing song is
        releasing over the whole crossfade, so "stop the playlist" would
        otherwise leave it audible for another few seconds after being told to
        stop. Voice.release is safe to call twice and takes the new fade.
        """
        stopped = 0
        with self._lock:
            for voice in self._voices:
                if voice.slot_index != slot_index:
                    continue
                if voice.releasing and not also_releasing:
                    continue
                if not voice.releasing:
                    stopped += 1
                voice.release(fade_out)
        return stopped

    def stop_all(self, fade_out=None):
        if fade_out is None:
            fade_out = C.FADE_OUT_PANIC
        with self._lock:
            count = sum(1 for v in self._voices if not v.releasing)
            for voice in self._voices:
                voice.release(fade_out)
        if fade_out <= 0.0:
            self._reap(force=True)
        return count

    def is_playing(self, slot_index):
        with self._lock:
            return any(v.slot_index == slot_index and not v.releasing and not v.finished
                       for v in self._voices)

    def playing_slots(self):
        with self._lock:
            return sorted({v.slot_index for v in self._voices
                           if not v.releasing and not v.finished})

    def voice_count(self):
        with self._lock:
            return len(self._voices)

    # ------------------------------------------------------------- levels ----
    def bus_gain(self, bus):
        return {C.BUS_SFX: self.sfx_gain,
                C.BUS_BED: self.bed_gain,
                C.BUS_PLAYLIST: self.playlist_gain}.get(bus, self.sfx_gain)

    def _set_bus_gain(self, bus, gain):
        gain = max(0.0, min(1.0, gain))
        setattr(self, {C.BUS_SFX: "sfx_gain", C.BUS_BED: "bed_gain",
                       C.BUS_PLAYLIST: "playlist_gain"}[bus], gain)
        with self._lock:
            for voice in self._voices:
                if voice.bus == bus:
                    # A voice mid-crossfade is on its way somewhere; moving its
                    # target under it would abandon the fade half done.
                    if not voice.releasing:
                        voice.set_gain(gain)
        return gain

    def set_sfx_gain(self, gain):
        self._set_bus_gain(C.BUS_SFX, gain)

    def set_bed_gain(self, gain):
        self._set_bus_gain(C.BUS_BED, gain)

    def set_playlist_gain(self, gain):
        self._set_bus_gain(C.BUS_PLAYLIST, gain)

    # ------------------------------------------------------------ rendering --
    def _reap(self, force=False):
        dead = []
        with self._lock:
            keep = []
            for voice in self._voices:
                if force or voice.finished:
                    dead.append(voice)
                else:
                    keep.append(voice)
            self._voices = keep
        for voice in dead:
            voice.close()

    def _duck_ramp(self, frames, voices):
        """Where the beds should sit this block, given what else is playing."""
        # Published every block whether or not THIS mixer is ducking, because
        # another output may be ducking and needs to know about our drops.
        self.duck_bus.publish(
            self.key,
            any(v.is_loud and (not v.finished) and (not v.releasing)
                for v in voices))

        target = 1.0
        if self.ducking and self.duck_bus.loud:
            target = db_to_gain(self.duck_db)
        if abs(self._duck - target) < 1e-6:
            self._duck = target
            return target
        span = C.DUCK_ATTACK if target < self._duck else C.DUCK_RELEASE
        step = frames / float(max(1, int(span * self.samplerate)))
        delta = target - self._duck
        move = min(abs(delta), step) * (1.0 if delta > 0 else -1.0)
        new = self._duck + move
        ramp = np.linspace(self._duck, new, frames, dtype=np.float32)
        self._duck = new
        return ramp[:, None]

    def render(self, frames):
        """Mix one block. Public so tests can run the whole engine silently."""
        mix = np.zeros((frames, CHANNELS), dtype=np.float32)
        with self._lock:
            voices = list(self._voices)
        if voices:
            duck = self._duck_ramp(frames, voices)
            for voice in voices:
                mix += voice.render(frames, duck)
        else:
            self._duck = 1.0
            self.duck_bus.publish(self.key, False)

        # Monitoring is added AFTER the duck. The point of the duck is to get
        # the music out from under the voice; ducking the voice as well would
        # undo it.
        source = self.monitor_source
        if source is not None:
            try:
                mix += source.read(frames)
            except Exception:
                pass          # a monitor must never take the music down

        peak = float(np.abs(mix).max()) if frames else 0.0
        self.peak = peak
        if peak > 1.0:
            np.clip(mix, -1.0, 1.0, out=mix)

        if any(v.finished for v in voices):
            self._reap()
        return mix

    def _callback(self, outdata, frames, time_info, status):
        if status:
            self.underruns += 1
        outdata[:] = self.render(frames)


def resolve_device(spec):
    """Turn a saved {name, hostapi} into a live device index, or None.

    Devices are remembered by name because indices move the moment something is
    plugged in or unplugged. Returns None for "system default", and also None
    when a remembered device is simply not here any more - the caller is
    expected to notice that and say so rather than fail quietly.
    """
    if not spec:
        return None
    name = spec.get("name")
    hostapi = spec.get("hostapi")
    if not name:
        return None
    for dev in output_devices():
        if dev["name"] == name and (not hostapi or dev["hostapi"] == hostapi):
            return dev["index"]
    return None


def device_spec(index):
    """The inverse: a live index turned into a {name, hostapi} worth saving."""
    if index is None:
        return None
    for dev in output_devices():
        if dev["index"] == index:
            return {"name": dev["name"], "hostapi": dev["hostapi"]}
    return None


class MixerGroup:
    """One mixer per distinct output, and the routing that decides which.

    This exists so a bank can be sent to its own sound card - beds to one
    channel of a physical desk, drops to another - which is what a broadcaster
    needs in order to ride the balance by hand instead of relying on automatic
    ducking. The request came from a user who was explicit that he was not
    asking for better ducking; he was asking to be able to stop relying on it.

    Two things it deliberately does NOT do:

    - It does not make a mixer per bank. Banks sharing a device share a mixer,
      so the ordinary case of everything on the default output is still one
      stream and one callback, exactly as before.
    - It does not make ducking a per-device affair. Every mixer shares one
      DuckBus, so a drop on one card still ducks a bed on another. Routing the
      beds elsewhere must not silently turn ducking off.

    The public surface matches Mixer's, so the frame holds one of these and
    mostly does not have to care which it has.
    """

    def __init__(self, bank_devices=None, open_stream=True,
                 monitor_device=None):
        #: bank number -> device index, or None for the system default.
        self.bank_devices = dict(bank_devices or {})
        #: Where a monitored microphone goes. Its own output, because
        #: monitoring belongs in the presenter's headphones and the show does
        #: not. None means whatever bank 1 is using.
        self.monitor_device = monitor_device
        self._monitor_source = None
        self.open_stream = open_stream
        self.duck_bus = DuckBus()
        self._mixers = {}
        self.problems = []
        self._build()

    # ------------------------------------------------------------- plumbing --
    def _build(self):
        for mixer in self._mixers.values():
            mixer.close()
        self._mixers = {}
        self.problems = []

        wanted = {self.bank_devices.get(bank) for bank in range(1, C.BANK_COUNT + 1)}
        # The monitor output is opened alongside the banks' outputs, so a
        # microphone can be monitored on a card nothing else is using.
        wanted.add(self.monitor_device)
        for device in sorted(wanted, key=lambda d: (d is not None, d)):
            mixer = Mixer(device=device, open_stream=self.open_stream,
                          duck_bus=self.duck_bus, key=device)
            # A remembered device that is gone, or held exclusively by something
            # else, must not leave that bank silent with no explanation. Fall
            # back to the default output and record why, so the frame can say so.
            if self.open_stream and mixer.stream is None and device is not None:
                self.problems.append(
                    "%s could not be opened, so those sounds are going to the "
                    "default output instead" % describe_device(device))
                mixer.close()
                for bank, dev in list(self.bank_devices.items()):
                    if dev == device:
                        self.bank_devices[bank] = None
                if None in self._mixers:
                    continue
                device = None
                mixer = Mixer(device=None, open_stream=self.open_stream,
                              duck_bus=self.duck_bus, key=None)
            self._mixers.setdefault(device, mixer)

        if not self._mixers:
            self._mixers[None] = Mixer(device=None, open_stream=self.open_stream,
                                       duck_bus=self.duck_bus, key=None)

    @property
    def mixers(self):
        return list(self._mixers.values())

    def for_bank(self, bank):
        return self._mixers.get(self.bank_devices.get(bank)) or self.primary

    def for_slot(self, slot_index):
        return self.for_bank(slot_index // C.SLOTS_PER_BANK + 1)

    @property
    def primary(self):
        """Whatever bank 1 plays through; the fallback for everything else."""
        return (self._mixers.get(self.bank_devices.get(C.BANK_SFX))
                or next(iter(self._mixers.values())))

    def set_bank_devices(self, bank_devices):
        """Re-route. Everything playing stops, because a voice belongs to a stream."""
        previous = (self.sfx_gain, self.bed_gain, self.ducking, self.duck_db,
                    self.bed_fade_in, self.bed_fade_out, self.playlist_gain)
        monitor = self.monitor_source
        self.stop_all(fade_out=0.0)
        self.bank_devices = dict(bank_devices or {})
        self._build()
        self.set_sfx_gain(previous[0])
        self.set_bed_gain(previous[1])
        self.ducking = previous[2]
        self.duck_db = previous[3]
        self.bed_fade_in = previous[4]
        self.bed_fade_out = previous[5]
        self.set_playlist_gain(previous[6])
        # Rebuilding replaced every mixer, so the monitor has to be re-attached
        # or it would go on writing into an output nothing is draining.
        self.monitor_source = monitor
        return not self.problems

    def distinct_device_count(self):
        return len(self._mixers)

    @property
    def is_running(self):
        """Is audio coming out of any of these mixers.

        A group has no single ``stream`` and never did. ui.py asked for one
        anyway, which raised inside the wx.CallLater that speaks the startup
        line - so from 2.1.2 to 2.3.0 the app silently said nothing at startup,
        including "3 files missing" and "audio could not start". Ask a question
        the object can actually answer.
        """
        return any(m.stream is not None for m in self._mixers.values())

    def close(self):
        for mixer in self._mixers.values():
            mixer.close()
        self._mixers = {}

    # ------------------------------------------------------------ transport --
    def play(self, slot_index, path, **kwargs):
        return self.for_slot(slot_index).play(slot_index, path, **kwargs)

    def stop_slot(self, slot_index, fade_out=None, also_releasing=False):
        return self.for_slot(slot_index).stop_slot(
            slot_index, fade_out=fade_out, also_releasing=also_releasing)

    def stop_all(self, fade_out=None):
        return sum(m.stop_all(fade_out=fade_out) for m in self._mixers.values())

    def is_playing(self, slot_index):
        return self.for_slot(slot_index).is_playing(slot_index)

    def playing_slots(self):
        found = set()
        for mixer in self._mixers.values():
            found.update(mixer.playing_slots())
        return sorted(found)

    def voice_count(self):
        return sum(m.voice_count() for m in self._mixers.values())

    # --------------------------------------------------------------- levels --
    @property
    def sfx_gain(self):
        return self.primary.sfx_gain

    @property
    def bed_gain(self):
        return self.primary.bed_gain

    def set_sfx_gain(self, gain):
        for mixer in self._mixers.values():
            mixer.set_sfx_gain(gain)

    def set_bed_gain(self, gain):
        for mixer in self._mixers.values():
            mixer.set_bed_gain(gain)

    @property
    def monitor_mixer(self):
        """The output a monitored microphone plays out of."""
        return self._mixers.get(self.monitor_device) or self.primary

    @property
    def monitor_source(self):
        return self._monitor_source

    @monitor_source.setter
    def monitor_source(self, source):
        """Monitoring goes to exactly ONE output.

        Attaching it to every mixer would have several of them draining the
        same ring buffer, each getting a fraction of the audio and none of
        them getting speech.
        """
        self._monitor_source = source
        for mixer in self._mixers.values():
            mixer.monitor_source = None
        self.monitor_mixer.monitor_source = source

    def set_monitor_device(self, device):
        """Move monitoring to another output, opening it if need be."""
        if device == self.monitor_device:
            return False
        self.monitor_device = device
        source = self._monitor_source
        self.set_bank_devices(self.bank_devices)
        self.monitor_source = source
        return True

    @property
    def playlist_gain(self):
        return self.primary.playlist_gain

    def set_playlist_gain(self, gain):
        for mixer in self._mixers.values():
            mixer.set_playlist_gain(gain)

    @property
    def ducking(self):
        return self.primary.ducking

    @ducking.setter
    def ducking(self, value):
        for mixer in self._mixers.values():
            mixer.ducking = bool(value)

    @property
    def duck_db(self):
        return self.primary.duck_db

    @duck_db.setter
    def duck_db(self, value):
        for mixer in self._mixers.values():
            mixer.duck_db = value

    @property
    def bed_fade_in(self):
        return self.primary.bed_fade_in

    @bed_fade_in.setter
    def bed_fade_in(self, value):
        for mixer in self._mixers.values():
            mixer.bed_fade_in = float(value)

    @property
    def bed_fade_out(self):
        return self.primary.bed_fade_out

    @bed_fade_out.setter
    def bed_fade_out(self, value):
        for mixer in self._mixers.values():
            mixer.bed_fade_out = float(value)

    @property
    def device(self):
        """Bank 1's output, for the places that still ask about "the" device."""
        return self.bank_devices.get(C.BANK_SFX)

    @property
    def last_error(self):
        for mixer in self._mixers.values():
            if mixer.last_error:
                return mixer.last_error
        return None

    @property
    def underruns(self):
        return sum(m.underruns for m in self._mixers.values())

    @property
    def peak(self):
        return max((m.peak for m in self._mixers.values()), default=0.0)

    @property
    def samplerate(self):
        return self.primary.samplerate

    def render(self, frames):
        """Test hook: one block of the primary output."""
        return self.primary.render(frames)
