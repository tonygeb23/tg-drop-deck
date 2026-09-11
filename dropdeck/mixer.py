"""The output stream and everything that plays into it.

The mixer owns the sound card. It knows how to start a slot, stop a slot, duck
the beds under a drop, and stop the world. It does not know what a button is.

It can also run with no sound card at all (``open_stream=False``), which is how
the tests drive it: call ``render`` yourself and inspect the samples.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

import numpy as np
import sounddevice as sd

from . import constants as C
from .engine import (CHANNELS, MemoryVoice, StreamVoice, cue_tone, db_to_gain,
                     load_audio, probe)
# The monitor bus is an AirBus. Same problem, same answer: several audio
# callbacks on several clocks writing, one draining, nothing allowed to block.
# streamout imports engine and constants only, so there is no cycle here.
from .streamout import AirBus

#: Decoded audio we keep around so a repeat press is instant. Short sounds only.
_CACHE_BUDGET_BYTES = 256 * 1024 * 1024

#: What the system default output is called on a bus. A NAME rather than
#: None, because Mixer turns a key of None into id(self), and id(self) is a
#: different number every time the outputs are rebuilt. Every rebuild
#: therefore orphaned the default output's ring on the send bus and started a
#: fresh one, which is half of why a send died on any device change.
DEFAULT_DEVICE_KEY = "the system default output"


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


def _soft_clip(mix):
    """Round off anything past the threshold instead of chopping it square.

    A crossfade sums two full level songs, and two full level songs are louder
    than one. The old answer was np.clip, which is a right angle: the moment
    the sum goes over, the waveform is sawn flat and what you hear is a crackle
    on every loud beat of the overlap. This bends the top instead. Everything
    below the threshold is untouched, so quiet material is bit for bit what it
    was, and nothing can ever leave here past full scale.

    In place, and only called on a block that actually needs it.
    """
    knee = 1.0 - C.SOFT_CLIP_FROM
    over = np.abs(mix) > C.SOFT_CLIP_FROM
    if not over.any():
        return
    values = mix[over]
    signs = np.sign(values)
    excess = (np.abs(values) - C.SOFT_CLIP_FROM) / knee
    mix[over] = signs * (C.SOFT_CLIP_FROM + knee * np.tanh(excess))


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
                 duck_bus=None, key=None, blocksize=None):
        self._lock = threading.Lock()
        self._voices = []
        self._cache = OrderedDict()
        self._cache_bytes = 0

        self.device = device
        self.samplerate = samplerate or self._device_rate(device)
        #: How many frames the card is asked for. None means C.OUTPUT_BLOCKSIZE,
        #: which is zero, which means "you choose". Read the note there before
        #: putting a number back: a fixed 512 lost several per cent of the
        #: audio going into a virtual cable, measured, and said nothing.
        self.blocksize = (C.OUTPUT_BLOCKSIZE if blocksize is None
                          else int(blocksize))
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

        #: Where the on air mix goes while streaming, or None. Anything with a
        #: write(key, block) that never blocks will do; see streamout.AirBus.
        #: None is the ordinary state and costs nothing at all.
        self.air_tap = None

        #: The microphone, read through its own tap for the stream. Not the
        #: same read as monitor_source: each takes what it reads away, and a
        #: presenter on speakers monitors nothing and is still on air.
        self.air_source = None

        #: Where the same mix goes when it is being sent to another program on
        #: this machine, or None. Shaped exactly like air_tap, and separate
        #: from it so a send works with nothing live and nothing recording.
        #: See send.py.
        self.send_tap = None

        #: Where this mixer's own program block goes so that a monitor on
        #: ANOTHER sound card can hear it, or None. Set on every mixer except
        #: the monitor's own, which would otherwise hear itself twice.
        self.monitor_tap = None

        #: The other cards' program blocks, for this mixer to add into what
        #: comes out of it. Only ever set on the monitor mixer. An AirBus,
        #: because the problem is identical: several callbacks on several
        #: clocks writing, one callback draining, and nothing allowed to block.
        self.monitor_feed = None
        self._monitor_primed = False
        self._monitor_prime = int(self.samplerate * C.MONITOR_PRIME_SECONDS)
        #: Times the monitor feed ran dry. Only ever a monitoring fault: the
        #: show itself is unaffected, which is why it is counted separately
        #: from anything on the air.
        self.monitor_gaps = 0

        #: The one source the send leaves out. Mix minus: feeding a captured
        #: program its own audio back is an echo of itself, so the send to
        #: TeamTalk must not carry the TeamTalk capture. It has to be a
        #: subtraction off the single read rather than a second sum, because
        #: reading a source takes the audio away from it. See
        #: sources.SourceGroup.read_air_minus.
        self.send_minus = None

        #: The cue, made once per shape, level and samplerate. See play_cue.
        self._cue_tone = None
        self._cue_key = None

        #: Where the playlist fader actually is, as opposed to where it has
        #: been asked to go. It glides, the same way ducking does, because a
        #: gain that jumps between blocks clicks.
        self._playlist_level = C.DEFAULT_PLAYLIST_VOLUME

        #: The playlist fader changes what you hear and not what goes out.
        #: Tony, 4 September 2026: "I adjust the playlist volume and it turned
        #: it down on air, too, that should only be for the program only".
        #: He is describing a monitor fader, which is what a desk has: you
        #: pull the music down in your own ears to hear your screen reader,
        #: and the listener hears no such thing.
        self.playlist_monitor_only = True

        self._duck = 1.0
        self.peak = 0.0
        self.underruns = 0

        #: Callbacks that arrived later than they should have. PortAudio's
        #: own underrun flag reported nothing at all through a seven per cent
        #: loss on a virtual cable, so this app times its own callback rather
        #: than take the driver's word for it. See C.LATE_BLOCK_FACTOR.
        self.late_blocks = 0
        self.blocks = 0
        #: The worst gap between two callbacks, in seconds, and the last
        #: block size seen. Both only for saying out loud what happened.
        self.worst_gap = 0.0
        self.last_frames = 0
        self._last_callback = None

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
        self._last_callback = None
        self.late_blocks = 0
        self.blocks = 0
        self.worst_gap = 0.0
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

        # The playlist fader is applied per block in render() rather than
        # baked into the voice, so that the same rendered block can go to the
        # speakers turned down and to the stream at full level. A voice can
        # only be rendered once, so this is the only place the two can differ.
        level = 1.0 if bus == C.BUS_PLAYLIST else self.bus_gain(bus)
        gain = level * db_to_gain(trim_db)
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

    def play_samples(self, slot_index, data, *, bus=None, gain=1.0,
                     fade_in=0.0, fade_out=0.01, name=""):
        """Play audio that is already in memory, at the rate this mixer runs.

        For sounds this app makes rather than reads: the end of track pip is
        the only one so far. Nothing here touches the decode cache, because
        there is no file to cache.
        """
        voice = MemoryVoice(
            data, slot_index=slot_index, gain=float(gain), loop=False,
            name=name, fade_in=fade_in, fade_out=fade_out,
            rate=self.samplerate, bus=bus or C.BUS_CUE)
        with self._lock:
            self._voices.append(voice)
        return voice

    def play_cue(self, kind=None, level_db=None):
        """The end of track cue. Returns the Voice, or None if it will not.

        ``kind`` is which of the shapes in C.CUE_SOUNDS, and ``level_db`` how
        loud. Both are cached with the samplerate, so arrowing through the
        picker in Preferences builds each one once and no more.
        """
        try:
            key = (kind, level_db, self.samplerate)
            if self._cue_tone is None or self._cue_key != key:
                self._cue_tone = cue_tone(self.samplerate, kind, level_db)
                self._cue_key = key
            # Only ever one. Pressing on through a second one landing on top
            # of the first would be a rattle, not a cue.
            self.stop_slot(C.CUE_SLOT, fade_out=0.01, also_releasing=True)
            return self.play_samples(C.CUE_SLOT, self._cue_tone,
                                     bus=C.BUS_CUE, name="end of track")
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def play_preview(self, path, trim_db=0.0):
        """Audition one file. Whatever was being auditioned stops first.

        On its own slot and its own bus, so stopping it cannot touch a sound
        that is on air, and so it neither ducks the beds nor gets ducked. You
        are choosing a sound here, not playing one out.
        """
        self.stop_preview()
        return self.play(C.PREVIEW_SLOT, path, bus=C.BUS_PREVIEW,
                         trim_db=trim_db, fade_in=0.0, fade_out=0.04,
                         name="preview")

    def stop_preview(self):
        return self.stop_slot(C.PREVIEW_SLOT, fade_out=0.04,
                              also_releasing=True)

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
        if bus == C.BUS_PREVIEW:
            # The sound fader, so a preview sounds like the pad will sound.
            return self.sfx_gain
        if bus == C.BUS_CUE:
            # Its own level, and no fader. A cue you have turned the sound
            # down on is a cue you will miss, and turning the sound down is
            # the first thing anybody does while they are talking.
            return 1.0
        return {C.BUS_SFX: self.sfx_gain,
                C.BUS_BED: self.bed_gain,
                C.BUS_PLAYLIST: self.playlist_gain}.get(bus, self.sfx_gain)

    def _set_bus_gain(self, bus, gain):
        gain = max(0.0, min(1.0, gain))
        setattr(self, {C.BUS_SFX: "sfx_gain", C.BUS_BED: "bed_gain",
                       C.BUS_PLAYLIST: "playlist_gain"}[bus], gain)
        if bus == C.BUS_PLAYLIST:
            # Nothing to push. render() reads playlist_gain every block, which
            # is what lets the fader be a monitor control.
            return gain
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
            # Guarded for the same reason render() is: this runs inside the
            # audio callback, and sounddevice aborts the stream on a raise.
            # Closing a voice is releasing a file handle, and a file handle
            # that will not close is not worth a silent sound card.
            try:
                voice.close()
            except Exception:
                pass

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

    def _playlist_ramp(self, frames):
        """Where the playlist fader should sit this block.

        The same shape as _duck_ramp, and for the same reason: a gain that
        steps between blocks is an audible click, so it walks there over
        VOLUME_GLIDE instead.
        """
        target = self.playlist_gain
        if abs(self._playlist_level - target) < 1e-6:
            self._playlist_level = target
            return target
        step = frames / float(max(1, int(C.VOLUME_GLIDE * self.samplerate)))
        delta = target - self._playlist_level
        move = min(abs(delta), step) * (1.0 if delta > 0 else -1.0)
        new = self._playlist_level + move
        ramp = np.linspace(self._playlist_level, new, frames, dtype=np.float32)
        self._playlist_level = new
        return ramp[:, None]

    def render(self, frames):
        """Mix one block. Public so tests can run the whole engine silently."""
        mix = np.zeros((frames, CHANNELS), dtype=np.float32)
        tap = self.air_tap
        send_tap = self.send_tap
        # The same sum serves the stream, the recorder and the send. It is
        # built when ANY of them wants it: a send works with nothing live and
        # nothing recording, which is the whole point of it.
        air = (np.zeros((frames, CHANNELS), dtype=np.float32)
               if (tap is not None or send_tap is not None) else None)
        with self._lock:
            voices = list(self._voices)
        if voices:
            duck = self._duck_ramp(frames, voices)
            fader = self._playlist_ramp(frames)
            for voice in voices:
                # Guarded, because sounddevice returns paAbort when a callback
                # raises and nothing here restarts a stopped stream. One
                # malformed voice would silence that sound card for the rest
                # of the show, which is a far worse outcome than one sound
                # not playing.
                try:
                    block = voice.render(frames, duck)
                except Exception:
                    voice.finished = True
                    continue
                # A voice can only be rendered once, because rendering moves
                # it along. So the on air sum is built here beside the one
                # going to the speakers rather than by a second pass over the
                # same voices, which would play everything twice as fast.
                if voice.bus == C.BUS_PLAYLIST:
                    # The one bus whose fader is a monitor control: turned
                    # down in the room, full level to the listener.
                    mix += block * fader
                    if air is not None:
                        air += (block if self.playlist_monitor_only
                                else block * fader)
                else:
                    mix += block
                    if air is not None and voice.bus not in C.OFF_AIR_BUSES:
                        air += block
        else:
            self._duck = 1.0
            self.duck_bus.publish(self.key, False)

        # What this card is playing, offered to a monitor on another card.
        # Taken HERE, after the voices and before anything that belongs only
        # to the presenter: a monitor wants the show, not a second copy of
        # somebody's headphone feed.
        monitor_tap = self.monitor_tap
        if monitor_tap is not None:
            try:
                monitor_tap.write(self.key, mix, self.samplerate)
            except Exception:
                pass          # a monitor must never take the show down

        # And the other way round, on the one card the presenter listens on:
        # every OTHER card's show, added to this one's. This is what makes a
        # monitor carry the whole programme rather than only whatever happens
        # to be routed to it.
        feed = self.monitor_feed
        if feed is not None:
            try:
                mix += self._from_monitor(frames, feed)
            except Exception:
                pass

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
        if peak > C.SOFT_CLIP_FROM:
            _soft_clip(mix)

        if air is not None:
            self._to_air(air, frames, tap, send_tap)

        if any(v.finished for v in voices):
            self._reap()
        return mix

    def _from_monitor(self, frames, feed):
        """One block of the other cards' show. Never blocks, never raises.

        Primed the way the send is, and for the same reason: two sound cards
        run on two clocks, so a ring read the moment it is created is a ring
        that is empty. Running dry re-primes rather than starving on every
        block from then on, because one short silence beats a permanent
        stutter in the ears of somebody who cannot see a meter.
        """
        if not self._monitor_primed:
            if feed.available() < self._monitor_prime:
                return 0.0
            self._monitor_primed = True
        if feed.available() < frames:
            self._monitor_primed = False
            self.monitor_gaps += 1
            return 0.0
        return feed.read(frames)

    def _to_air(self, air, frames, tap, send_tap=None):
        """Finish the on air block and hand it over. Never raises.

        This runs inside the audio callback, so it does exactly two cheap
        things and gets out. Everything expensive, the encoding and the
        socket, happens on the streaming thread at the other end of the tap.
        A stream that cannot keep up must never become a gap in the sound
        coming out of the speakers.

        The send gets the same block, unless it is leaving a source out, in
        which case it gets one of its own. Both are finished before either is
        handed over: soft clipping is in place, so a shared array must not be
        clipped twice.
        """
        mic = self.air_source
        send = air if send_tap is not None else None
        if mic is not None:
            try:
                minus = self.send_minus if send_tap is not None else None
                if minus is not None and hasattr(mic, "read_air_minus"):
                    # One read, two sums. See sources.SourceGroup.
                    total, without = mic.read_air_minus(frames, minus)
                    if without is not total:
                        send = air + without
                    air += total
                else:
                    air += mic.read_air(frames)
            except Exception:
                pass          # a microphone must never take the show down
        if frames and float(np.abs(air).max()) > C.SOFT_CLIP_FROM:
            _soft_clip(air)
        if send is not None and send is not air:
            if frames and float(np.abs(send).max()) > C.SOFT_CLIP_FROM:
                _soft_clip(send)
        # With the rate, because a bank on a card that would only open at
        # 44100 has to be converted before it is summed with a main output
        # at 48000, not simply added as though they matched.
        if tap is not None:
            try:
                tap.write(self.key, air, self.samplerate)
            except Exception:
                pass
        if send_tap is not None and send is not None:
            try:
                send_tap.write(self.key, send, self.samplerate)
            except Exception:
                pass

    def _callback(self, outdata, frames, time_info, status):
        if status:
            self.underruns += 1
        # Timed here rather than trusted to the driver. Two perf_counter calls
        # and a compare, which is nothing beside the mixing below, and it is
        # the only reason this app can say "that output is not keeping up"
        # instead of shrugging: PortAudio reported a clean stream through a
        # measured seven per cent loss into a virtual cable.
        now = time.perf_counter()
        previous, self._last_callback = self._last_callback, now
        self.blocks += 1
        self.last_frames = frames
        if previous is not None and frames:
            gap = now - previous
            if gap > self.worst_gap:
                self.worst_gap = gap
            if gap > (frames / float(self.samplerate)) * C.LATE_BLOCK_FACTOR:
                self.late_blocks += 1
        outdata[:] = self.render(frames)

    # -------------------------------------------------------------- health --
    @property
    def late_share(self):
        """What fraction of blocks arrived late. Zero when nothing has run."""
        return (self.late_blocks / float(self.blocks)) if self.blocks else 0.0

    def keeping_up(self):
        """Is this output healthy, and one line saying why if it is not."""
        if self.stream is None:
            return False, self.last_error or "not running"
        if self.underruns:
            return False, "%d dropouts reported by the sound card" % self.underruns
        if self.late_blocks and self.late_share > C.LATE_BLOCK_WARN_SHARE:
            return False, ("%d of %d blocks arrived late, worst gap %d "
                           "milliseconds" % (self.late_blocks, self.blocks,
                                             round(self.worst_gap * 1000)))
        return True, "keeping up"


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


def _key_for(device):
    """A bus key that survives a rebuild. See DEFAULT_DEVICE_KEY."""
    return DEFAULT_DEVICE_KEY if device is None else device


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
        #: Whether the monitor card carries EVERY card's show or only its own.
        #: On by default, because the alternative is a presenter who cannot
        #: hear half of what is going out. Measured 10 September 2026: banks
        #: on one card and the monitor on another gave the banks' card the
        #: pads with no microphone, and the monitor the microphone with no
        #: pads. Neither output had the whole show.
        self.monitor_everything = True
        self._monitor_bus = None
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
                          duck_bus=self.duck_bus, key=_key_for(device))
            # A remembered device that is gone, or held exclusively by something
            # else, must not leave that bank silent with no explanation. Fall
            # back to the default output and record why, so the frame can say so.
            if self.open_stream and mixer.stream is None and device is not None:
                # WHICH role was on that card decides what just happened and
                # what has to be said. This used to remap the banks and say
                # "those sounds", whatever the card was for.
                #
                # **The monitor was never remapped at all**, and that is the
                # part that was dangerous rather than merely untidy.
                # `monitor_mixer` is `_mixers.get(monitor_device) or primary`,
                # so a monitor device left pointing at a card that would not
                # open silently resolves to BANK 1's output. With bank 1 on a
                # virtual cable, which is exactly the setup this is for, the
                # presenter's microphone and the end of track cue go straight
                # into whatever program is listening to that cable, and the
                # message said they had gone to the default output. Found by
                # Jackson, 10 September 2026, measured with a sleeping
                # Bluetooth headset.
                was_bank = any(dev == device
                               for dev in self.bank_devices.values())
                was_monitor = (self.monitor_device == device)
                mixer.close()
                for bank, dev in list(self.bank_devices.items()):
                    if dev == device:
                        self.bank_devices[bank] = None
                if was_monitor:
                    self.monitor_device = None
                where = describe_device(device)
                if was_monitor and was_bank:
                    self.problems.append(
                        "%s could not be opened, so those sounds and what you "
                        "hear are both going to the default output instead"
                        % where)
                elif was_monitor:
                    self.problems.append(
                        "%s could not be opened, so what you hear is going to "
                        "the default output instead. Check where that is "
                        "before you say anything you would not broadcast"
                        % where)
                else:
                    self.problems.append(
                        "%s could not be opened, so those sounds are going to "
                        "the default output instead" % where)
                if None in self._mixers:
                    continue
                device = None
                mixer = Mixer(device=None, open_stream=self.open_stream,
                              duck_bus=self.duck_bus, key=_key_for(None))
            self._mixers.setdefault(device, mixer)

        if not self._mixers:
            self._mixers[None] = Mixer(device=None, open_stream=self.open_stream,
                                       duck_bus=self.duck_bus,
                                       key=_key_for(None))
        self._wire_monitor()

    def _wire_monitor(self):
        """Give the card the presenter listens on every other card's show.

        One bus, written by every mixer except the monitor's own and drained
        by that one. The monitor mixer is left out of its own bus for the
        obvious reason: what it plays already comes out of the card it is
        playing on, and putting it through the ring as well would be a second
        copy of itself a few milliseconds late.

        **With one sound card this does nothing at all**, which is the
        ordinary case: there are no other mixers, so there is no bus, no ring
        and no added latency on the path between a key and a sound.
        """
        for mixer in self._mixers.values():
            mixer.monitor_tap = None
            mixer.monitor_feed = None
        self._monitor_bus = None
        if not self.monitor_everything:
            return
        monitor = self.monitor_mixer
        others = [m for m in self._mixers.values() if m is not monitor]
        if not others:
            return
        bus = AirBus(monitor.samplerate, seconds=C.MONITOR_RING_SECONDS)
        self._monitor_bus = bus
        monitor.monitor_feed = bus
        for mixer in others:
            mixer.monitor_tap = bus

    def set_monitor_everything(self, on):
        """Turn the full programme monitor on or off, and rewire."""
        on = bool(on)
        if on == self.monitor_everything:
            return False
        self.monitor_everything = on
        self._wire_monitor()
        return True

    @property
    def monitor_gaps(self):
        """Times the monitor feed ran dry. A monitoring fault, never an air one."""
        return sum(m.monitor_gaps for m in self._mixers.values())

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
        # The stream, and the microphone feeding it. Rebuilding replaces every
        # mixer, and a new mixer has no tap, so changing an output device while
        # on air used to take the stream off it: nothing wrote to the ring, the
        # streamer waited five seconds, decided the audio had stopped and
        # reconnected forever, silently. The presenter was told "reconnecting"
        # rather than "your stream is dead", and only coming off air and back
        # fixed it.
        air_tap = self.air_tap
        air_source = self.air_source
        # The send is carried across for exactly the reason above, and it is
        # easier to lose: a send runs with nothing live, so a device change
        # would silently take it off with no stream to notice.
        send_tap = self.send_tap
        send_minus = self.send_minus
        monitor_only = self.playlist_monitor_only
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
        self.playlist_monitor_only = monitor_only
        if air_tap is not None:
            self.air_tap = air_tap
            self.air_source = air_source
        if send_tap is not None:
            self.send_tap = send_tap
            self.send_minus = send_minus
            # The sources are read by whichever mixer holds air_source, and
            # with nothing live that would be nobody at all.
            if air_source is not None and self.air_source is None:
                self.air_source = air_source
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

    def play_preview(self, path, trim_db=0.0):
        """Auditioning goes to the ordinary output, not the monitor one.

        A preview is the sound you are about to put on a pad, so you want to
        hear it the way it will be heard.
        """
        return self.primary.play_preview(path, trim_db=trim_db)

    def stop_preview(self):
        return sum(m.stop_preview() for m in self._mixers.values())

    def play_cue(self, kind=None, level_db=None):
        """Out of the monitor output, which is where the presenter is.

        The same output the microphone is monitored on, for the same reason:
        it is what the person running the show hears and what the show does
        not go to. With no separate monitor output set it is the ordinary
        output, which is what somebody with one sound card wants.
        """
        return self.monitor_mixer.play_cue(kind, level_db)

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

    @property
    def air_tap(self):
        """Where the on air mix goes, across every card at once."""
        return self.primary.air_tap

    @air_tap.setter
    def air_tap(self, tap):
        for mixer in self._mixers.values():
            mixer.air_tap = tap

    @property
    def air_source(self):
        return self.primary.air_source

    @air_source.setter
    def air_source(self, source):
        # Only the primary reads the microphone. Every mixer reading it would
        # take the same audio away from each other and the voice would arrive
        # in pieces.
        for mixer in self._mixers.values():
            mixer.air_source = None
        self.primary.air_source = source

    @property
    def send_tap(self):
        """Where the send takes the mix from, across every card at once."""
        return self.primary.send_tap

    @send_tap.setter
    def send_tap(self, tap):
        # Every card, the same as air_tap: a bank routed to its own output is
        # still part of the show and still has to reach whoever is being sent
        # it. See the program bus note in CLAUDE.md.
        for mixer in self._mixers.values():
            mixer.send_tap = tap

    @property
    def send_minus(self):
        return self.primary.send_minus

    @send_minus.setter
    def send_minus(self, source):
        # Only on the mixer that actually reads the sources, which is the same
        # one air_source is on. Setting it anywhere else would be a promise
        # nothing keeps.
        for mixer in self._mixers.values():
            mixer.send_minus = None
        self.primary.send_minus = source

    @property
    def playlist_monitor_only(self):
        return self.primary.playlist_monitor_only

    @playlist_monitor_only.setter
    def playlist_monitor_only(self, value):
        for mixer in self._mixers.values():
            mixer.playlist_monitor_only = bool(value)

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
    def late_blocks(self):
        return sum(m.late_blocks for m in self._mixers.values())

    def keeping_up(self):
        """Are all the outputs healthy, and the first reason one is not."""
        for mixer in self._mixers.values():
            ok, why = mixer.keeping_up()
            if not ok:
                return False, "%s: %s" % (describe_device(mixer.device), why)
        return True, "keeping up"

    @property
    def peak(self):
        return max((m.peak for m in self._mixers.values()), default=0.0)

    @property
    def samplerate(self):
        return self.primary.samplerate

    def render(self, frames):
        """Test hook: one block of the primary output."""
        return self.primary.render(frames)
