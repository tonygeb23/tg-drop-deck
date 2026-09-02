"""Turning a raw generation into something the deck can actually fire.

Two problems come back from the API and both are fixed here.

The effects arrive hot, peaks above full scale, which would clip the moment
the mixer sums two of them. The beds arrive as MP3, which carries encoder
padding, so a bed that should be thirty seconds is thirty seconds and a bit;
loop that and you hear a tick every time round.
"""

from __future__ import annotations

import io
import time
import os

import numpy as np
import soundfile as sf

#: Effects want headroom but should still hit hard.
SFX_PEAK_DBFS = -1.0
#: Beds are matched to each other by loudness, not by peak, so that twenty
#: different styles sit at the same level under a voice.
BED_RMS_DBFS = -20.0
BED_PEAK_CEILING_DBFS = -1.5
#: Long enough to hide an MP3 seam, short enough not to smear a downbeat.
LOOP_CROSSFADE_SECONDS = 0.25


def decode(raw):
    """Decode whatever the API sent into stereo float32."""
    data, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    return np.ascontiguousarray(data), rate


def _db(x):
    return float(20.0 * np.log10(max(x, 1e-9)))


def _gain(db):
    return float(10.0 ** (db / 20.0))


def peak_normalise(data, target_dbfs=SFX_PEAK_DBFS):
    peak = float(np.abs(data).max())
    if peak <= 0:
        return data
    return np.clip(data * (_gain(target_dbfs) / peak), -1.0, 1.0)


def limit(data, rate, ceiling_dbfs=BED_PEAK_CEILING_DBFS,
          lookahead=0.005, release=0.10):
    """Hold the peaks down without turning the whole track down.

    Scaling a whole bed to fit its loudest drum hit is why a punchy bed ends up
    quieter than a soft one. This rides the gain instead: a short lookahead so
    the reduction arrives before the transient, and a slow release so it is not
    audible as pumping.
    """
    from scipy.ndimage import minimum_filter1d

    ceiling = _gain(ceiling_dbfs)
    envelope = np.abs(data).max(axis=1)
    if envelope.max() <= ceiling:
        return data

    needed = np.minimum(1.0, ceiling / np.maximum(envelope, 1e-9))
    window = max(3, int(lookahead * rate) * 2 + 1)
    gain = minimum_filter1d(needed, size=window, mode="nearest")

    # One pole release, so the gain returns gently rather than snapping back.
    coefficient = float(np.exp(-1.0 / max(1.0, release * rate)))
    smoothed = np.empty_like(gain)
    current = 1.0
    step = max(1, len(gain) // 4096)
    for start in range(0, len(gain), step):
        block = gain[start:start + step]
        floor = float(block.min())
        current = min(floor, current * coefficient + floor * (1.0 - coefficient))
        smoothed[start:start + step] = current
    gain = np.minimum(smoothed, needed)

    return np.clip(data * gain[:, None], -1.0, 1.0)


def loudness_normalise(data, rate=48000, target_dbfs=BED_RMS_DBFS,
                       ceiling_dbfs=BED_PEAK_CEILING_DBFS):
    """Match beds to each other by average level, then limit the peaks.

    Average level is what the ear compares, so that is what gets matched. The
    limiter afterwards protects the ceiling without undoing the match.
    """
    rms = float(np.sqrt(np.mean(np.square(data))))
    if rms <= 0:
        return data
    data = data * (_gain(target_dbfs) / rms)
    return limit(data, rate, ceiling_dbfs)


def make_seamless(data, rate, seconds=None, crossfade=LOOP_CROSSFADE_SECONDS):
    """Return a clip whose end runs into its own beginning without a seam.

    The tail is folded back over the head with an equal-power crossfade, and
    the result is exactly the loop length, so playing it end to end forever
    has no gap and no click.
    """
    total = len(data)
    fade = int(crossfade * rate)
    target = int(seconds * rate) if seconds else total - fade
    target = max(fade + 1, min(target, total - fade))
    if target + fade > total:
        fade = max(1, total - target)

    out = np.array(data[:target], dtype=np.float32, copy=True)
    tail = data[target:target + fade]
    if len(tail) == fade and fade > 1:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
        # Equal power, so the overlap does not dip in the middle.
        out[:fade] = out[:fade] * np.sqrt(ramp) + tail * np.sqrt(1.0 - ramp)
    return out


def seam_discontinuity(data):
    """How big the jump is from the last sample back round to the first.

    Measured against how big the jumps are everywhere else in the file, so the
    number means the same thing for a busy track and a sparse one. Comparing
    against the opening samples instead would divide by almost nothing whenever
    a bed fades in from silence, and report a clean loop as a terrible one.

    Below 1 means the seam is no more abrupt than the music already is.
    """
    if len(data) < 2:
        return 0.0
    wrap = float(np.abs(data[0] - data[-1]).max())
    steps = np.abs(np.diff(data, axis=0)).max(axis=1)
    typical = float(np.percentile(steps, 99.9))
    return wrap / max(typical, 1e-6)


def write_sfx(raw, path):
    data, rate = decode(raw)
    data = peak_normalise(data)
    sf.write(path, data, rate, format="FLAC", subtype="PCM_16")
    return len(data) / float(rate)


def _write_chunked(path, data, rate, fmt, subtype, block=48000):
    """Write in blocks rather than in one call.

    libsndfile's Vorbis encoder takes the whole buffer badly once a file gets
    past a few seconds, it kills the process outright, with no exception to
    catch. Feeding it a second at a time is just as fast and does not.

    Written to a temporary file and moved into place, so a failure never
    leaves a half-encoded file that the next run would skip as "already done".
    """
    temp = path + ".part"
    if os.path.exists(temp):
        os.remove(temp)
    with sf.SoundFile(temp, "w", samplerate=rate, channels=data.shape[1],
                      format=fmt, subtype=subtype) as handle:
        for start in range(0, len(data), block):
            handle.write(data[start:start + block])

    # Dropbox indexes a file the moment it appears and briefly holds it open,
    # which makes the swap fail. Wait it out rather than losing the encode.
    for attempt in range(10):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            time.sleep(0.5 * (attempt + 1))
    os.replace(temp, path)


def write_bed(raw, path, seconds):
    data, rate = decode(raw)
    data = make_seamless(data, rate, seconds=seconds)
    data = loudness_normalise(data, rate)
    _write_chunked(path, data, rate, "OGG", "VORBIS")
    return len(data) / float(rate)
