"""A real send into a real virtual cable, recorded off the other end.

The counterpart to `check_switching.py`, and it exists for the same reason:
every check in `tests/test_send.py` renders the mixer by hand, and a test
renders far faster than a sound card, so none of them proves anything about
what actually survives the trip into a cable. That trip is the entire fault
this feature was built to fix.

What it does, on whatever virtual cable this machine has:

1. Opens a real `Send` on the cable's playback end.
2. Plays a 1 kHz tone through a real `Mixer`, plus a stand-in "source" at a
   different frequency standing in for a captured program.
3. Records the cable's capture end for the whole time.
4. Decodes what arrived and counts what is missing.

Two things it proves that nothing else can:

- **Continuity.** A gap is measured as a stretch of the recording with no
  signal in it. Before this work, Drop Deck's fixed 512 frame output buffer
  lost a median 2.67 per cent of the audio over ten runs, in about six gaps a
  second, and PortAudio reported a perfectly healthy stream throughout.
- **Mix minus.** The stand-in source's own frequency is looked for in the
  recording. Its absence is the proof that the send is not feeding a captured
  program its own audio back.

Run it by hand. It needs a virtual audio cable installed and it puts audio
through it, so it is in tools rather than tests.

    python tools/check_send.py
"""
from __future__ import annotations

import os
import sys
import threading
import time

import numpy as np
import sounddevice as sd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import constants as C                    # noqa: E402
from dropdeck.audiofile import CHANNELS                # noqa: E402
from dropdeck.mixer import Mixer                       # noqa: E402
from dropdeck.send import Send                         # noqa: E402
from dropdeck.sources import SourceGroup               # noqa: E402

#: The show, and the captured program that must not come back.
SHOW_HZ = 1000.0
SOURCE_HZ = 3000.0
SECONDS = 20.0

#: A block is called a gap when its loudest sample is below this. The tone is
#: played at 0.3, so this is more than twenty decibels down: nothing but real
#: silence reaches it.
GAP_BELOW = 0.05
#: How many samples a gap is measured in. 64 at 192 kHz is a third of a
#: millisecond, which is finer than any gap worth hearing.
GAP_BLOCK = 64


class Tone:
    """Something shaped like a source, generating a tone rather than reading one.

    It counts its reads for the same reason the tests do: mix minus is only
    exact if a source is read ONCE however many sums it ends up in.
    """

    def __init__(self, hz, rate, level=0.3):
        self.hz = hz
        self.rate = rate
        self.level = level
        self.phase = 0.0
        self.air_reads = 0

    def _block(self, frames):
        step = 2.0 * np.pi * self.hz / self.rate
        angle = self.phase + step * np.arange(frames)
        self.phase = (self.phase + step * frames) % (2.0 * np.pi)
        wave = (self.level * np.sin(angle)).astype(np.float32)
        return np.column_stack([wave, wave])

    def read(self, frames):
        return np.zeros((frames, CHANNELS), dtype=np.float32)

    def read_air(self, frames):
        self.air_reads += 1
        return self._block(frames)


def cable():
    """The two ends of a virtual cable, WASAPI for preference."""
    apis = [h["name"] for h in sd.query_hostapis()]
    out = into = None
    for api in ("Windows WASAPI", "Windows DirectSound", "MME"):
        for index, dev in enumerate(sd.query_devices()):
            if apis[dev["hostapi"]] != api:
                continue
            name = dev["name"].lower()
            if "cable" not in name:
                continue
            if out is None and dev["max_output_channels"] > 0 and "input" in name:
                out = (index, dev)
            if into is None and dev["max_input_channels"] > 0 and "output" in name:
                into = (index, dev)
        if out and into:
            return out, into
        out = into = None
    return None, None


def gaps(signal, rate):
    """Every stretch of silence in the recording, as (at, milliseconds)."""
    usable = len(signal) // GAP_BLOCK * GAP_BLOCK
    envelope = np.abs(signal[:usable]).reshape(-1, GAP_BLOCK).max(axis=1)
    quiet = envelope < GAP_BELOW
    found = []
    at = 0
    while at < len(quiet):
        if not quiet[at]:
            at += 1
            continue
        end = at
        while end < len(quiet) and quiet[end]:
            end += 1
        found.append((at * GAP_BLOCK / rate,
                      (end - at) * GAP_BLOCK / rate * 1000.0))
        at = end
    return found, float(quiet.sum()) / len(quiet) * 100.0


def level_at(signal, rate, hz, width=40.0):
    """How loud one frequency is in the recording, in dBFS.

    An absolute level, not a ratio against a noise floor. The first version
    of this divided by the median of the spectrum, and the recording is two
    pure tones, so the median is essentially zero and every answer came back
    as three hundred decibels. A number that large is not a strong signal, it
    is a broken measurement.

    A Hann window scales a sine by its coherent gain, which is the mean of
    the window, so dividing the peak by the window's sum and doubling it (for
    the half of the energy in the negative frequencies) gives the amplitude
    back.
    """
    window = np.hanning(len(signal))
    spectrum = np.abs(np.fft.rfft(signal * window))
    freqs = np.fft.rfftfreq(len(signal), 1.0 / rate)
    band = (freqs > hz - width) & (freqs < hz + width)
    if not band.any():
        return -999.0
    amplitude = 2.0 * float(spectrum[band].max()) / float(window.sum())
    return 20.0 * np.log10(max(amplitude, 1e-12))


def main():
    out, into = cable()
    if out is None or into is None:
        print("No virtual audio cable on this machine, so there is nothing to "
              "check. Install VB-CABLE and run this again.")
        return 0

    out_index, out_dev = out
    in_index, in_dev = into
    in_rate = int(in_dev["default_samplerate"])
    print("Sending into  %s at %d Hz" % (out_dev["name"],
                                         int(out_dev["default_samplerate"])))
    print("Recording off %s at %d Hz" % (in_dev["name"], in_rate))
    print("Send buffer %d frames, output buffer %r (0 means the card chooses)"
          % (C.SEND_BLOCKSIZE, C.OUTPUT_BLOCKSIZE))

    recorded = []
    overflows = [0]

    def record():
        with sd.InputStream(device=in_index, samplerate=in_rate,
                            channels=CHANNELS, dtype="float32",
                            blocksize=2048) as stream:
            until = time.monotonic() + SECONDS + 1.5
            while time.monotonic() < until:
                block, over = stream.read(2048)
                if over:
                    overflows[0] += 1
                recorded.append(block.copy())

    listener = threading.Thread(target=record, name="check-send-recorder")
    listener.start()
    time.sleep(0.5)

    # A send on the cable, and a mixer with no card at all: the mixer is
    # rendered by hand here so the test is about the SEND's clock and the
    # cable, and not about a second sound card's.
    #
    # The stream is opened AFTER the mixer has put some audio in the bus,
    # which is the order the real app is always in: a send is switched on
    # while the mixers are already running, so its ring fills from the very
    # next callback. Opening the card first and then starting to render
    # counts one starve on the way in, which is the harness arriving late
    # and not the send failing.
    send = Send(device=out_index, open_stream=False)

    mixer = Mixer(open_stream=False, samplerate=send.samplerate)
    captured = Tone(SOURCE_HZ, send.samplerate)
    show = Tone(SHOW_HZ, send.samplerate)
    mixer.air_source = SourceGroup(mic=show, sources=[captured])
    mixer.send_tap = send.bus
    mixer.send_minus = captured

    frames = 512
    while send.bus.available() < send._prime_frames + frames * 4:
        mixer.render(frames)
    if not send.start():
        print("The send would not open: %s" % send.last_error)
        listener.join()
        return 1

    # Render in real time, which is what a sound card would be doing.
    started = time.monotonic()
    rendered = 0
    while time.monotonic() - started < SECONDS:
        due = int((time.monotonic() - started) * send.samplerate)
        if rendered >= due + frames:
            time.sleep(0.002)
            continue
        mixer.render(frames)
        rendered += frames

    # Read the counters BEFORE the tail, not after. Nothing writes to the bus
    # once the render loop stops, so the send runs it dry within the prime
    # length and counts a starve: that is this harness ending, not the send
    # failing, and counting it would make a clean run look faulty every time.
    starved, rebuffers, dropped = send.starved, send.rebuffers, send.bus.dropped
    blocks = send.blocks
    time.sleep(0.3)
    send.close()
    listener.join()

    if not recorded:
        print("Nothing was recorded at all.")
        return 1
    signal = np.concatenate(recorded)[:, 0]
    # The first second is the send priming and the last half is the tail.
    signal = signal[int(in_rate * 1.0):int(in_rate * SECONDS)]
    found, share = gaps(signal, in_rate)

    print("")
    print("%.1f seconds recorded, %d input overflows" % (len(signal) / in_rate,
                                                         overflows[0]))
    print("Send callbacks %d, starved %d, rebuffers %d, blocks dropped %d"
          % (blocks, starved, rebuffers, dropped))
    print("Gaps: %d, %.3f per cent of the recording, longest %.1f ms"
          % (len(found), share, max([g[1] for g in found]) if found else 0.0))
    if found[:8]:
        print("  first few at " + ", ".join("%.2fs (%.1f ms)" % g
                                            for g in found[:8]))

    show_db = level_at(signal, in_rate, SHOW_HZ)
    source_db = level_at(signal, in_rate, SOURCE_HZ)
    print("The show at %.0f Hz arrived at %.1f dBFS" % (SHOW_HZ, show_db))
    print("The excluded source at %.0f Hz arrived at %.1f dBFS, %.1f dB down"
          % (SOURCE_HZ, source_db, show_db - source_db))
    print("It was read %d times, so it was in the sum and taken back out"
          % captured.air_reads)

    problems = []
    if share > 0.05:
        problems.append("%.3f per cent of the audio never arrived" % share)
    # The tone is played at 0.3, which is -10.5 dBFS. Anything below -30 has
    # not really arrived.
    if show_db < -30.0:
        problems.append("the show is not really there (%.1f dBFS)" % show_db)
    if source_db > show_db - 40.0:
        problems.append("the excluded source came through at %.1f dBFS, only "
                        "%.1f dB down, which is a mix minus that is not "
                        "working" % (source_db, show_db - source_db))
    if rebuffers:
        problems.append("the send rebuffered %d times" % rebuffers)

    print("")
    if problems:
        for line in problems:
            print("FAULT: %s" % line)
        return 1
    print("Clean. Nothing missing, and the excluded source is not in it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
