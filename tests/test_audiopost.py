"""Post-processing for the demo pack: levels, and loops that do not click.

    python tests/test_audiopost.py
"""

import io
import os
import sys
import tempfile

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from audiopost import (BED_RMS_DBFS, SFX_PEAK_DBFS, decode, loudness_normalise,
                       make_seamless, peak_normalise, seam_discontinuity,
                       write_bed, write_sfx)

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append((label, bool(condition), detail))
    if not condition:
        print(f"  FAIL  {label}   {detail}")


def dbfs(x):
    return 20.0 * np.log10(max(float(x), 1e-9))


def encoded(data, rate=48000, fmt="WAV"):
    """A file in memory, the way the API hands one back."""
    buffer = io.BytesIO()
    sf.write(buffer, data, rate, format=fmt)
    return buffer.getvalue()


def music(seconds=4.0, rate=48000, freq=110.0, amp=0.3):
    """Something with a continuous phase, so a bad cut is obvious."""
    n = int(seconds * rate)
    t = np.arange(n, dtype=np.float32) / rate
    wave = amp * (np.sin(2 * np.pi * freq * t)
                  + 0.4 * np.sin(2 * np.pi * freq * 2.5 * t))
    return np.tile(wave.astype(np.float32)[:, None], (1, 2))


def main():
    tmp = tempfile.mkdtemp(prefix="dropdeck-post-")

    print("Decoding")
    mono = np.tile(np.linspace(-0.5, 0.5, 4800, dtype=np.float32)[:, None], (1, 1))
    data, rate = decode(encoded(mono))
    check("mono is widened to stereo", data.shape[1] == 2)
    check("both sides match after widening",
          np.allclose(data[:, 0], data[:, 1]))
    check("samplerate survives", rate == 48000)

    six = np.tile(music(0.5)[:, :1], (1, 6))
    data, _ = decode(encoded(six))
    check("more than two channels is folded to two", data.shape[1] == 2)

    print("Levels")
    hot = music(1.0, amp=0.9) * 1.4          # the API really does send these
    check("the test signal is over full scale", np.abs(hot).max() > 1.0)
    tamed = peak_normalise(hot)
    check("effects are brought under full scale", np.abs(tamed).max() <= 1.0)
    check("effects land on the target peak",
          abs(dbfs(np.abs(tamed).max()) - SFX_PEAK_DBFS) < 0.01,
          f"{dbfs(np.abs(tamed).max()):.3f} dBFS")

    quiet = music(1.0, amp=0.02)
    loud = music(1.0, amp=0.8)
    a = loudness_normalise(quiet, 48000)
    b = loudness_normalise(loud, 48000)
    rms_a = dbfs(np.sqrt(np.mean(a ** 2)))
    rms_b = dbfs(np.sqrt(np.mean(b ** 2)))
    check("a quiet bed is brought up to the target",
          abs(rms_a - BED_RMS_DBFS) < 0.1, f"{rms_a:.2f} dBFS")
    check("a loud bed is brought down to the target",
          abs(rms_b - BED_RMS_DBFS) < 0.1, f"{rms_b:.2f} dBFS")
    check("beds end up matched to each other", abs(rms_a - rms_b) < 0.1,
          f"{rms_a:.2f} vs {rms_b:.2f}")

    spiky = music(1.0, amp=0.05)
    spiky[1000] = 1.0
    held = loudness_normalise(spiky, 48000)
    check("a peak is held under the ceiling", np.abs(held).max() <= 1.0)

    print("Loops")
    clip = music(4.0)
    looped = make_seamless(clip, 48000, seconds=3.0)
    check("the loop is exactly the length asked for",
          len(looped) == 3 * 48000, f"{len(looped)}")
    naive = clip[:3 * 48000]
    check("crossfading beats a straight cut at the seam",
          seam_discontinuity(looped) < seam_discontinuity(naive),
          f"crossfaded {seam_discontinuity(looped):.2f} "
          f"vs cut {seam_discontinuity(naive):.2f}")
    check("the seam is small enough not to hear",
          seam_discontinuity(looped) < 1.0,
          f"{seam_discontinuity(looped):.3f}")
    check("the body of the loop is untouched",
          np.allclose(looped[48000:], clip[48000:3 * 48000], atol=1e-6))

    short = make_seamless(music(1.0), 48000, seconds=10.0)
    check("asking for more than there is does not crash",
          0 < len(short) <= 48000, f"{len(short)}")

    print("Writing")
    sfx_path = os.path.join(tmp, "effect.flac")
    seconds = write_sfx(encoding := encoded(music(1.5) * 1.3), sfx_path)
    check("an effect is written", os.path.exists(sfx_path))
    check("an effect keeps its length", abs(seconds - 1.5) < 0.01, f"{seconds}")
    info = sf.info(sfx_path)
    check("effects are written lossless", info.format == "FLAC", info.format)
    back, _ = sf.read(sfx_path, dtype="float32", always_2d=True)
    check("the written effect does not clip", np.abs(back).max() <= 1.0)

    bed_path = os.path.join(tmp, "bed.ogg")
    seconds = write_bed(encoded(music(6.0)), bed_path, 5.0)
    check("a bed is written", os.path.exists(bed_path))
    check("a bed is trimmed to exactly the loop length",
          abs(seconds - 5.0) < 0.001, f"{seconds}")
    info = sf.info(bed_path)
    check("beds are written compressed", info.subtype == "VORBIS", info.subtype)
    check("the file reports the exact loop length",
          abs(info.frames / info.samplerate - 5.0) < 0.001,
          f"{info.frames / info.samplerate}")
    check("no part file is left behind",
          not os.path.exists(bed_path + ".part"))
    back, _ = sf.read(bed_path, dtype="float32", always_2d=True)
    check("the written bed is at the target loudness",
          abs(dbfs(np.sqrt(np.mean(back ** 2))) - BED_RMS_DBFS) < 1.0,
          f"{dbfs(np.sqrt(np.mean(back ** 2))):.2f} dBFS")
    check("the written bed still loops cleanly",
          seam_discontinuity(back) < 1.0, f"{seam_discontinuity(back):.3f}")

    print("The shipped pack, if it has been generated")
    demo = os.path.join(ROOT, "demo")
    beds = os.path.join(demo, "beds")
    sfx = os.path.join(demo, "sfx")
    if os.path.isdir(beds) and os.listdir(beds):
        files = sorted(f for f in os.listdir(beds) if f.endswith(".ogg"))
        lengths = []
        rmss = []
        for name in files:
            data, rate = sf.read(os.path.join(beds, name), dtype="float32",
                                 always_2d=True)
            lengths.append(len(data) / rate)
            rmss.append(dbfs(np.sqrt(np.mean(data ** 2))))
        check("every shipped bed is exactly thirty seconds",
              all(abs(v - 30.0) < 0.01 for v in lengths),
              f"{min(lengths):.3f} to {max(lengths):.3f}")
        # Not zero spread on purpose. A sparse tension bed has far more crest
        # than a busy pop bed, and squashing it flat to match would wreck the
        # thing that makes it useful. Three decibels is close enough that you
        # are not reaching for F5 every time you change bed.
        check("shipped beds are level with each other",
              max(rmss) - min(rmss) < 3.0,
              f"spread {max(rmss) - min(rmss):.2f} dB")
        check("every shipped bed loops without a click",
              all(seam_discontinuity(sf.read(os.path.join(beds, n),
                                             dtype="float32", always_2d=True)[0]) < 1.0
                  for n in files))
        print(f"  checked {len(files)} beds")
    else:
        print("  no beds generated yet, skipped")

    if os.path.isdir(sfx) and os.listdir(sfx):
        peaks = []
        for name in sorted(os.listdir(sfx)):
            data, _ = sf.read(os.path.join(sfx, name), dtype="float32",
                              always_2d=True)
            peaks.append(np.abs(data).max())
        check("no shipped effect clips", max(peaks) <= 1.0, f"{max(peaks):.4f}")
        check("shipped effects are normalised to the same peak",
              all(abs(dbfs(p) - SFX_PEAK_DBFS) < 0.1 for p in peaks),
              f"{dbfs(min(peaks)):.2f} to {dbfs(max(peaks)):.2f} dBFS")
        print(f"  checked {len(peaks)} effects")
    else:
        print("  no effects generated yet, skipped")

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
