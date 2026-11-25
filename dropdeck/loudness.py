"""Loudness as ITU-R BS.1770 measures it, in numpy and nothing else.

Two things use it. The on air sound's leveller (dsp.ProgramChain) asks how
loud the last three seconds of the show were, and the background pass asks
how loud a whole file is, once, so a song and a pad can be matched without
anything being measured on the way from a keypress to a sound.

**The K weighting is applied in the frequency domain**, as a weight on each
bin of a block's spectrum, rather than as the two IIR filters the standard
describes. That has two virtues here and one cost. There is no filter state
to carry from block to block, so a block can be measured on its own on any
thread; and nothing needs scipy, which the build leaves out. The cost is that
a block is weighted as though it were periodic, which smears a little energy
across its edges: measured against the exact filters on real tracks it reads
within a few tenths of a LU, which is far closer than a level needs.

This module imports no wx and opens nothing.
"""
from __future__ import annotations

import numpy as np

#: The two K weighting stages as BS.1770 publishes them, for 48 kHz: the
#: high shelf that models the head, then the high pass (RLB).
_SHELF = ((1.53512485958697, -2.69169618940638, 1.19839281085285),
          (1.0, -1.69065929318241, 0.73248077421585))
_HIGHPASS = ((1.0, -2.0, 1.0), (1.0, -1.99004745483398, 0.99007225036621))

#: The absolute gate, and how far under the first answer the relative one is.
ABSOLUTE_GATE = -70.0
RELATIVE_GATE = 10.0

#: The measurement piece, and how many make one gating block: 400 ms blocks
#: overlapping by three quarters, as the standard has it.
PIECE_SECONDS = 0.1
PIECES_PER_BLOCK = 4

_WEIGHTS = {}


def _weights(frames, rate):
    """|H(f)|^2 of the K weighting at each rfft bin, one sided, cached.

    The published coefficients are for 48 kHz. At another rate the same curve
    is read at the same frequency in hertz, which is what the filter means;
    above 24 kHz it is held at its top, where the shelf is flat anyway.
    """
    key = (int(frames), int(rate))
    found = _WEIGHTS.get(key)
    if found is not None:
        return found
    hz = np.minimum(np.fft.rfftfreq(int(frames), 1.0 / float(rate)), 23999.0)
    back = np.exp(-2j * np.pi * hz / 48000.0)
    weight = np.ones(len(hz))
    for b, a in (_SHELF, _HIGHPASS):
        num = b[0] + b[1] * back + b[2] * back * back
        den = a[0] + a[1] * back + a[2] * back * back
        weight = weight * np.abs(num / den) ** 2
    # Every bin but DC and Nyquist stands for two in a one sided spectrum.
    weight[1:] *= 2.0
    if int(frames) % 2 == 0:
        weight[-1] /= 2.0
    if len(_WEIGHTS) > 64:
        _WEIGHTS.clear()
    _WEIGHTS[key] = weight
    return weight


def energy(block, rate):
    """The K weighted sum of squares of a block, all its channels added.

    BS.1770 adds the channels' mean squares, left and right at a weight of
    one each, so dividing this by the block's length gives that sum.
    """
    n = len(block)
    if n < 2:
        return 0.0
    data = np.asarray(block, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    spectrum = np.fft.rfft(data, axis=0)
    power = spectrum.real ** 2 + spectrum.imag ** 2
    return float((power * _weights(n, rate)[:, None]).sum() / n)


def lufs(total_energy, frames):
    """Energy over a stretch of frames, as loudness. None for silence."""
    if frames <= 0 or total_energy <= 0.0:
        return None
    return -0.691 + 10.0 * np.log10(total_energy / float(frames))


def integrated(energies, counts):
    """BS.1770 integrated loudness from 100 ms pieces, in LUFS, or None.

    ``energies`` and ``counts`` are each piece's K weighted energy and its
    length in frames. Four consecutive pieces are one 400 ms gating block.
    None when there is not one whole block, or nothing passes the gates.
    """
    e = np.asarray(energies, dtype=np.float64)
    n = np.asarray(counts, dtype=np.float64)
    if len(e) < PIECES_PER_BLOCK:
        return None
    ones = np.ones(PIECES_PER_BLOCK)
    z = (np.convolve(e, ones, mode="valid")
         / np.maximum(np.convolve(n, ones, mode="valid"), 1.0))
    with np.errstate(divide="ignore"):
        loud = -0.691 + 10.0 * np.log10(np.maximum(z, 1e-30))
    keep = loud > ABSOLUTE_GATE
    if not keep.any():
        return None
    relative = -0.691 + 10.0 * np.log10(z[keep].mean()) - RELATIVE_GATE
    keep &= loud > relative
    if not keep.any():
        return None
    return float(-0.691 + 10.0 * np.log10(z[keep].mean()))


def matched_trim(level, peak_db):
    """The trim that brings a file to C.MATCH_TARGET_LUFS, in decibels.

    Down as far as C.MATCH_MOST_CUT_DB. Up only as far as the file's own
    peaks allow under C.MATCH_PEAK_CEILING_DB, and never past
    C.MATCH_MOST_BOOST_DB, because the presenter's output has no limiter: a
    quiet master that already peaks at full scale stays where it is. Nought
    when the file has not been, or could not be, measured.
    """
    from . import constants as C
    if level is None:
        return 0.0
    trim = C.MATCH_TARGET_LUFS - float(level)
    if trim > 0.0:
        room = (C.MATCH_PEAK_CEILING_DB - float(peak_db)
                if peak_db is not None else 0.0)
        return float(max(0.0, min(trim, C.MATCH_MOST_BOOST_DB, room)))
    return float(max(trim, C.MATCH_MOST_CUT_DB))


def trim_for(item, matching):
    """The trim a pad or a song plays at. A trim the user set always wins.

    ``item`` is a `Slot` or a playlist `Track`: anything with ``trim_db``,
    ``filepath`` and the three loudness fields. Arithmetic on numbers
    measured earlier, so it is safe on the way from a keypress to a sound.
    A measurement taken of a different file than the one there now (the pad
    was given another sound, or the file was relinked) is not used. Numbers
    read from a board file and not yet checked against the file on this
    machine (slot.loudness_due) may cut a sound but never bring it up.
    """
    own = float(getattr(item, "trim_db", 0.0) or 0.0)
    if own or not matching or getattr(item, "trim_set", False):
        return own
    if getattr(item, "loudness_for", None) != getattr(item, "filepath", None):
        return 0.0
    trim = matched_trim(getattr(item, "loudness", None),
                        getattr(item, "peak_db", None))
    if not getattr(item, "loudness_verified", False):
        trim = min(trim, 0.0)
    return trim
