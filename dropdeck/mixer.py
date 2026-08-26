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


class Mixer:
    """Sums every playing voice into one output stream."""

    def __init__(self, device=None, open_stream=True, samplerate=None):
        self._lock = threading.Lock()
        self._voices = []
        self._cache = OrderedDict()
        self._cache_bytes = 0

        self.device = device
        self.samplerate = samplerate or self._device_rate(device)
        self.stream = None
        self.last_error = None

        self.sfx_gain = C.DEFAULT_SFX_VOLUME
        self.bed_gain = C.DEFAULT_BED_VOLUME
        self.ducking = True
        self.duck_db = C.DEFAULT_DUCK_DB

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
    def play(self, slot_index, path, *, is_bed=False, loop=False, trim_db=0.0,
             name="", duration=None, fade_in=None, fade_out=None):
        """Start a sound. Returns the Voice, or None if the file would not open."""
        if duration is None:
            try:
                duration = probe(path)[0]
            except Exception as exc:
                self.last_error = str(exc)
                return None

        if fade_in is None:
            fade_in = C.FADE_IN_BED if is_bed else C.FADE_IN_SFX
        if fade_out is None:
            fade_out = C.FADE_OUT_BED if is_bed else C.FADE_OUT_SFX

        base = self.bed_gain if is_bed else self.sfx_gain
        gain = base * db_to_gain(trim_db)
        common = dict(slot_index=slot_index, gain=gain, loop=loop, name=name,
                      fade_in=fade_in, fade_out=fade_out, rate=self.samplerate,
                      is_bed=is_bed)
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

    def stop_slot(self, slot_index, fade_out=None):
        """Fade out every voice belonging to one slot."""
        stopped = 0
        with self._lock:
            for voice in self._voices:
                if voice.slot_index == slot_index and not voice.releasing:
                    voice.release(fade_out)
                    stopped += 1
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
    def set_sfx_gain(self, gain):
        self.sfx_gain = max(0.0, min(1.0, gain))
        with self._lock:
            for voice in self._voices:
                if not voice.is_bed:
                    voice.set_gain(self.sfx_gain)

    def set_bed_gain(self, gain):
        self.bed_gain = max(0.0, min(1.0, gain))
        with self._lock:
            for voice in self._voices:
                if voice.is_bed:
                    voice.set_gain(self.bed_gain)

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
        target = 1.0
        if self.ducking:
            loud = any((not v.is_bed) and (not v.finished) and (not v.releasing)
                       for v in voices)
            if loud:
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
