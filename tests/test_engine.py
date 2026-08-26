"""The mixer, driven silently.

No sound card is opened. We render blocks by hand and look at the samples, so
this runs anywhere — including on a machine with no audio at all.

    python tests/test_engine.py
"""

import os
import sys
import tempfile
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dropdeck import constants as C
from dropdeck.engine import db_to_gain, load_audio, probe
from dropdeck.mixer import Mixer

RATE = 48000
CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append((label, bool(condition), detail))
    if not condition:
        print(f"  FAIL  {label}   {detail}")


def tone(path, seconds, rate=44100, freq=440.0, channels=2, amp=0.5):
    n = int(seconds * rate)
    t = np.arange(n, dtype=np.float32) / rate
    wave = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    data = np.tile(wave[:, None], (1, channels))
    sf.write(path, data, rate)
    return path


def rms(block):
    return float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0


def render_seconds(mix, seconds, stream=None, frames=C.BLOCKSIZE):
    """Render and return every block concatenated.

    A test renders far faster than real time, so a streaming voice would
    underrun here purely because the disk reader never gets a turn. Where a
    stream is under test we wait for its buffer, which is what the sound card
    does for us in the real app.
    """
    blocks = []
    for _ in range(int(seconds * RATE / frames)):
        if stream is not None and not stream.finished and not stream.at_eof:
            deadline = time.monotonic() + 2.0
            while (stream.buffered_frames < frames
                   and not stream.at_eof
                   and time.monotonic() < deadline):
                time.sleep(0.001)
        blocks.append(mix.render(frames).copy())
    return np.concatenate(blocks) if blocks else np.zeros((0, 2), np.float32)


def main():
    tmp = tempfile.mkdtemp(prefix="dropdeck-test-")
    short = tone(os.path.join(tmp, "short.wav"), 1.0, rate=44100, freq=440)
    tiny = tone(os.path.join(tmp, "tiny.wav"), 0.25, rate=48000, freq=880)
    mono = tone(os.path.join(tmp, "mono.wav"), 0.5, rate=32000, channels=1)
    long_bed = tone(os.path.join(tmp, "bed.wav"), 40.0, rate=44100, freq=220, amp=0.4)
    # A silent one-shot triggers ducking without adding anything to the mix,
    # so the bed level is the only thing the duck checks are measuring.
    silent = tone(os.path.join(tmp, "silent.wav"), 1.0, rate=48000, amp=0.0)

    print("Decoding and conversion")
    dur, rate, ch = probe(short)
    check("probe reports duration", abs(dur - 1.0) < 0.01, f"got {dur}")
    check("probe reports rate", rate == 44100, f"got {rate}")
    data = load_audio(short, RATE)
    check("resampled to mixer rate", abs(len(data) - RATE) < 200, f"got {len(data)}")
    check("resampled is stereo", data.shape[1] == 2)
    md = load_audio(mono, RATE)
    check("mono becomes stereo", md.shape[1] == 2 and np.allclose(md[:, 0], md[:, 1]))
    check("decibels convert", abs(db_to_gain(-6.0) - 0.5012) < 0.001)

    print("One shot playback")
    mix = Mixer(open_stream=False, samplerate=RATE)
    mix.sfx_gain = 1.0
    voice = mix.play(0, tiny, is_bed=False, name="tiny")
    check("play returns a voice", voice is not None)
    audio = render_seconds(mix, 0.1)
    check("one shot makes sound", rms(audio) > 0.1, f"rms {rms(audio):.4f}")
    check("slot reports playing", mix.is_playing(0))
    render_seconds(mix, 0.4)
    check("one shot ends by itself", not mix.is_playing(0))
    check("finished voice is reaped", mix.voice_count() == 0, f"{mix.voice_count()} left")

    print("Sounds overlap and never cut each other off")
    mix.play(1, tiny, name="a")
    mix.play(1, tiny, name="b")
    check("same slot layers", mix.voice_count() == 2, f"{mix.voice_count()}")
    two = render_seconds(mix, 0.05)
    mix.stop_all(fade_out=0.0)
    mix.play(1, tiny, name="a")
    one = render_seconds(mix, 0.05)
    check("two copies are louder than one", rms(two) > rms(one) * 1.5,
          f"two {rms(two):.4f} one {rms(one):.4f}")
    mix.stop_all(fade_out=0.0)

    print("Volume and per slot trim")
    mix.set_sfx_gain(1.0)
    mix.play(2, tiny)
    full = rms(render_seconds(mix, 0.05))
    mix.stop_all(fade_out=0.0)
    mix.set_sfx_gain(0.5)
    mix.play(2, tiny)
    half = rms(render_seconds(mix, 0.05))
    mix.stop_all(fade_out=0.0)
    check("volume scales the output", abs(half / full - 0.5) < 0.05,
          f"ratio {half / full:.3f}")
    mix.set_sfx_gain(1.0)
    mix.play(2, tiny, trim_db=-6.0)
    trimmed = rms(render_seconds(mix, 0.05))
    mix.stop_all(fade_out=0.0)
    check("trim scales one slot", abs(trimmed / full - 0.5012) < 0.05,
          f"ratio {trimmed / full:.3f}")

    print("Beds loop and stream")
    mix.set_bed_gain(1.0)
    bed = mix.play(40, long_bed, is_bed=True, loop=True, duration=40.0)
    check("long file streams", type(bed).__name__ == "StreamVoice",
          f"got {type(bed).__name__}")
    check("short file stays in memory",
          type(mix.play(3, tiny)).__name__ == "MemoryVoice")
    mix.stop_slot(3, fade_out=0.0)
    render_seconds(mix, 0.6, stream=bed)         # let the reader thread fill
    body = render_seconds(mix, 0.3, stream=bed)
    check("bed is audible", rms(body) > 0.05, f"rms {rms(body):.4f}")
    check("bed keeps playing", mix.is_playing(40))

    print("Ducking")
    steady = rms(render_seconds(mix, 0.2, stream=bed))
    mix.play(4, silent)                          # a drop over the bed
    render_seconds(mix, C.DUCK_ATTACK + 0.05, stream=bed)
    ducked = rms(render_seconds(mix, 0.05, stream=bed))
    expected = C.DEFAULT_DUCK_DB
    check("bed ducks under a drop", ducked < steady * 0.6,
          f"steady {steady:.4f} ducked {ducked:.4f}")
    check("duck depth matches the setting",
          abs(ducked / steady - db_to_gain(expected)) < 0.05,
          f"ratio {ducked / steady:.3f} wanted {db_to_gain(expected):.3f}")
    mix.stop_slot(4, fade_out=0.0)
    render_seconds(mix, C.DUCK_RELEASE + 0.3, stream=bed)
    recovered = rms(render_seconds(mix, 0.2, stream=bed))
    check("bed comes back up", recovered > steady * 0.85,
          f"steady {steady:.4f} recovered {recovered:.4f}")

    mix.ducking = False
    mix.play(5, silent)
    render_seconds(mix, C.DUCK_ATTACK + 0.05, stream=bed)
    undipped = rms(render_seconds(mix, 0.05, stream=bed))
    check("ducking can be turned off", undipped > steady * 0.85,
          f"steady {steady:.4f} with duck off {undipped:.4f}")
    mix.stop_slot(5, fade_out=0.0)
    mix.ducking = True

    print("Stopping")
    mix.stop_slot(40, fade_out=0.2)
    tail = render_seconds(mix, 0.4, stream=bed)
    check("bed fades rather than cutting", rms(tail[:200]) > rms(tail[-200:]),
          "tail should be quieter than the head")
    check("faded bed finishes", not mix.is_playing(40))

    mix.play(6, tiny)
    mix.play(7, tiny)
    stopped = mix.stop_all(fade_out=0.05)
    check("stop all reports what it stopped", stopped == 2, f"got {stopped}")
    render_seconds(mix, 0.2)
    check("stop all empties the mixer", mix.voice_count() == 0,
          f"{mix.voice_count()} left")

    print("Bad input")
    check("missing file returns None",
          mix.play(8, os.path.join(tmp, "nope.wav")) is None)
    junk = os.path.join(tmp, "junk.wav")
    with open(junk, "wb") as handle:
        handle.write(b"this is not audio")
    check("unreadable file returns None", mix.play(9, junk) is None)
    check("mixer survives bad input", mix.voice_count() == 0)

    print("Output never clips past full scale")
    mix.set_sfx_gain(1.0)
    for slot in range(10, 20):
        mix.play(slot, tiny, trim_db=0.0)
    loud = render_seconds(mix, 0.05)
    check("mix is limited to full scale", float(np.abs(loud).max()) <= 1.0001,
          f"peak {float(np.abs(loud).max()):.4f}")
    mix.stop_all(fade_out=0.0)
    mix.close()

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
