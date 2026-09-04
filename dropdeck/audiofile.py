"""Reading audio files: what libsndfile opens, and what it cannot.

libsndfile handles WAV, MP3, OGG, FLAC and the rest of that family, and it is
what the mixer has always used. It does not handle the MPEG-4 family at all,
which is what iTunes, Apple Music and every iPhone recording produce, so an
m4a was simply refused. Brian Hartgen, September 2026: "The app does not
accept m4A files at all."

So there are two decoders behind one door. libsndfile is tried first because
it is faster and it is what every existing file already goes through; FFmpeg,
through PyAV, picks up whatever libsndfile will not open: m4a, m4b, aac, wma,
opus and the rest. Nothing above this module knows which one answered.

Three rules hold this together:

- **The extension list is what the decoders can really decode.** With no PyAV
  on the machine, m4a is not offered in the file dialogs and is not accepted
  from a paste, rather than being accepted and then failing at the moment
  somebody presses a key.
- **PyAV is imported lazily**, on the first file libsndfile refuses. It loads
  sixty megabytes of FFmpeg and there is no reason to pay for that at startup
  on a board of WAVs.
- **Tags are read with mutagen and nothing else.** Reading a tag is not
  decoding, it needs no audio library at all, and a file whose tags are
  broken must still play.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import threading

import numpy as np
import soundfile as sf

CHANNELS = 2
DTYPE = "float32"

#: What libsndfile opens. The list this app shipped with.
CORE_EXTENSIONS = (".wav", ".mp3", ".ogg", ".flac", ".aiff", ".aif", ".w64",
                   ".au")

#: What FFmpeg adds when it is there. The MPEG-4 family first, because that is
#: what a music library ripped on a Mac or bought from Apple is made of.
EXTRA_EXTENSIONS = (".m4a", ".m4b", ".mp4", ".aac", ".wma", ".opus", ".webm",
                    ".ac3", ".mka", ".amr", ".ape", ".wv")

#: A silence floor. Below this it is not music any more, it is the run out at
#: the end of a file, and a crossfade landing in it is a crossfade nobody
#: hears. Minus fifty four decibels: under the noise floor of any encoder, and
#: far under the quietest point a fade out still counts as.
SILENCE_FLOOR = 0.002

#: How far into the end of a file to look for that floor. A run out longer
#: than this is not a run out, it is a hidden track, and cutting into one
#: would be worse than the gap.
MAX_TAIL_SCAN = 30.0

_av_lock = threading.Lock()
_av = None
_av_tried = False


def _have_av_module():
    """Is PyAV installed. Asked without importing it."""
    try:
        return importlib.util.find_spec("av") is not None
    except (ImportError, ValueError):
        return False


def av_module():
    """PyAV, imported on first use, or None if it is not usable here.

    Lazy on purpose: it pulls in the whole of FFmpeg, and a board of WAV files
    must not pay for that on the way to its first keypress.
    """
    global _av, _av_tried
    with _av_lock:
        if not _av_tried:
            _av_tried = True
            try:
                _av = importlib.import_module("av")
            except Exception:
                _av = None
        return _av


def has_fallback():
    """Can anything on this machine decode what libsndfile will not."""
    return _av is not None if _av_tried else _have_av_module()


def supported_extensions():
    """Every extension this machine can actually play."""
    if has_fallback():
        return CORE_EXTENSIONS + EXTRA_EXTENSIONS
    return CORE_EXTENSIONS


def wildcard():
    """The file dialog filter, built from the same list."""
    every = supported_extensions()
    joined = ";".join("*" + e for e in every)
    parts = ["Audio files (%s)|%s" % (joined, joined)]
    for label, exts in (("WAV", (".wav",)), ("MP3", (".mp3",)),
                        ("M4A and AAC", (".m4a", ".m4b", ".aac", ".mp4")),
                        ("OGG and Opus", (".ogg", ".opus")),
                        ("FLAC", (".flac",)), ("Windows Media", (".wma",))):
        keep = [e for e in exts if e in every]
        if not keep:
            continue
        spec = ";".join("*" + e for e in keep)
        parts.append("%s files (%s)|%s" % (label, spec, spec))
    parts.append("All files (*.*)|*.*")
    return "|".join(parts)


def is_supported(path):
    return os.path.splitext(path)[1].lower() in supported_extensions()


#: The ones worth naming out loud, in the order somebody would name them.
_SPOKEN_FIRST = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".wma")


def spoken_formats():
    """The formats, said out loud without reading twenty of them.

    A screen reader working through "wav, mp3, ogg, flac, aiff, aif, w64, au,
    m4a, m4b, mp4, aac, wma, opus, webm, ac3, mka, amr, ape, wv" is a screen
    reader nobody listens to the end of.
    """
    every = supported_extensions()
    named = [e for e in _SPOKEN_FIRST if e in every]
    text = ", ".join(e.lstrip(".") for e in named)
    rest = len(every) - len(named)
    return "%s and %d more" % (text, rest) if rest > 0 else text


def to_stereo(block):
    """Force any channel count to stereo, cheaply and predictably."""
    if block.ndim == 1:
        block = block[:, None]
    if block.shape[1] == 1:
        return np.repeat(block, 2, axis=1)
    if block.shape[1] > 2:
        return np.ascontiguousarray(block[:, :2])
    return block


# --------------------------------------------------------------- probing ---
def probe(path):
    """Duration, samplerate and channel count, without decoding the audio."""
    try:
        info = sf.info(path)
    except Exception:
        return _av_probe(path)
    duration = info.frames / float(info.samplerate) if info.samplerate else 0.0
    return duration, info.samplerate, info.channels


def _av_probe(path):
    av = av_module()
    if av is None:
        raise RuntimeError("%s needs a decoder this build does not have"
                           % os.path.basename(path))
    with av.open(path) as container:
        if not container.streams.audio:
            raise RuntimeError("%s has no audio in it" % os.path.basename(path))
        stream = container.streams.audio[0]
        rate = int(stream.rate or 0)
        channels = int(getattr(stream.codec_context, "channels", 2) or 2)
        duration = None
        if stream.duration is not None and stream.time_base:
            duration = float(stream.duration * stream.time_base)
        elif container.duration:
            duration = float(container.duration) / av.time_base
    return duration or 0.0, rate, channels


# --------------------------------------------------------------- reading ---
class _SoundFileReader:
    """libsndfile, block by block, at the file's own rate."""

    def __init__(self, path):
        self._handle = sf.SoundFile(path)
        self.samplerate = self._handle.samplerate

    def read(self, frames):
        return to_stereo(self._handle.read(frames, dtype=DTYPE, always_2d=True))

    def seek_start(self):
        self._handle.seek(0)

    def seek_seconds(self, seconds):
        """Jump to ``seconds`` in. Returns where it landed, or None."""
        try:
            frame = max(0, int(seconds * self.samplerate))
            return self._handle.seek(frame) / float(self.samplerate)
        except Exception:
            return None

    def close(self):
        try:
            self._handle.close()
        except Exception:
            pass


class _AvReader:
    """FFmpeg, block by block, at the file's own rate.

    PyAV hands over frames of whatever size the codec feels like, so they are
    resampled to stereo float32 once and then queued. The rate is left alone:
    the caller resamples to the mixer's rate with soxr exactly as it does for
    a libsndfile file, so there is one resampling path here and not two.
    """

    def __init__(self, path):
        av = av_module()
        if av is None:
            raise RuntimeError("no decoder for %s" % os.path.basename(path))
        self._av = av
        self._path = path
        self._container = av.open(path)
        if not self._container.streams.audio:
            self._container.close()
            raise RuntimeError("%s has no audio in it" % os.path.basename(path))
        self._stream = self._container.streams.audio[0]
        self.samplerate = int(self._stream.rate or 48000)
        self._resampler = None
        self._frames = None
        self._pending = np.zeros((0, CHANNELS), dtype=np.float32)
        self._done = False
        self._start()

    def _start(self):
        self._resampler = self._av.audio.resampler.AudioResampler(
            format="flt", layout="stereo", rate=self.samplerate)
        self._frames = self._container.decode(audio=0)
        self._pending = np.zeros((0, CHANNELS), dtype=np.float32)
        self._done = False

    def _fill(self, want):
        while not self._done and len(self._pending) < want:
            try:
                frame = next(self._frames)
            except StopIteration:
                # Whatever the resampler is still holding on to.
                try:
                    tail = self._resampler.resample(None)
                except Exception:
                    tail = []
                self._done = True
                for out in tail or []:
                    self._append(out)
                break
            except Exception:
                self._done = True
                break
            for out in self._resampler.resample(frame):
                self._append(out)

    def _append(self, frame):
        block = frame.to_ndarray()
        if not block.size:
            return
        block = np.ascontiguousarray(block.reshape(-1, CHANNELS),
                                     dtype=np.float32)
        self._pending = (block if not len(self._pending)
                         else np.concatenate((self._pending, block)))

    def read(self, frames):
        self._fill(frames)
        take = min(frames, len(self._pending))
        block = self._pending[:take]
        self._pending = self._pending[take:]
        return np.ascontiguousarray(block, dtype=np.float32)

    def seek_start(self):
        try:
            self._container.seek(0)
        except Exception:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = self._av.open(self._path)
            self._stream = self._container.streams.audio[0]
        self._start()

    def seek_seconds(self, seconds):
        """Jump to roughly ``seconds`` in. Returns where it landed, or None.

        Roughly, because a compressed stream can only be entered at a packet
        boundary. That is fine for measuring a run out and no use at all for
        playback, which is why nothing on the audio path calls it.
        """
        try:
            offset = max(0, int(seconds * self._av.time_base))
            self._container.seek(offset, backward=True)
        except Exception:
            return None
        self._start()
        return seconds

    def close(self):
        try:
            self._container.close()
        except Exception:
            pass


def reader(path):
    """A block reader for any file this app will play.

    libsndfile first, FFmpeg for the rest. Both hand back stereo float32 at
    the file's own samplerate, so the caller has one thing to resample.
    """
    try:
        return _SoundFileReader(path)
    except Exception:
        if av_module() is None:
            raise
        return _AvReader(path)


def read_all(path):
    """Decode a whole file to stereo float32 at its own rate."""
    try:
        data, rate = sf.read(path, dtype=DTYPE, always_2d=True)
        return to_stereo(data), rate
    except Exception:
        if av_module() is None:
            raise
    handle = _AvReader(path)
    try:
        blocks = []
        while True:
            block = handle.read(65536)
            if not len(block):
                break
            blocks.append(block)
        data = (np.concatenate(blocks) if blocks
                else np.zeros((0, CHANNELS), dtype=np.float32))
        return data, handle.samplerate
    finally:
        handle.close()


# ------------------------------------------------------------------ tags ---
def _first(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


#: Where an artist and a title hide, per tag format. mutagen's easy interface
#: covers most of it; the raw keys are here for the files it does not.
_ARTIST_KEYS = ("artist", "albumartist", "TPE1", "\xa9ART", "Author",
                "WM/AlbumArtist", "ARTIST")
_TITLE_KEYS = ("title", "TIT2", "\xa9nam", "Title", "TITLE")


def tags(path):
    """An artist and a title out of the file, as far as it has them.

    A file with no tags, unreadable tags, or no mutagen on the machine gives
    an empty dict back and the caller falls back to the file name. Reading a
    tag must never be a reason a track will not play.
    """
    try:
        mutagen = importlib.import_module("mutagen")
    except Exception:
        return {}
    metas = []
    for easy in (True, False):
        try:
            meta = mutagen.File(path, easy=easy)
        except Exception:
            meta = None
        if meta is not None:
            metas.append(meta)
    found = {}
    for field, keys in (("artist", _ARTIST_KEYS), ("title", _TITLE_KEYS)):
        for meta in metas:
            for key in keys:
                try:
                    value = _first(meta.get(key))
                except Exception:
                    value = None
                if value:
                    found[field] = value
                    break
            if field in found:
                break
    return found


# --------------------------------------------------------------- silence ---
def tail_silence(path, duration=None):
    """How many seconds of the end of this file are not music.

    This is what makes a crossfade land on the song rather than on the run out
    after it. An MP3 routinely carries a second or two of digital silence at
    the end: encoder padding, or simply where the CD track stopped. Cue three
    seconds from the last SAMPLE of such a file and two of those three seconds
    are the outgoing track playing nothing while the incoming one comes up
    alone, which is exactly what Brian Hartgen heard and described as "the
    song is playing out in full and the second one is fading in".

    Returns 0.0 when nothing can be measured, so an unreadable file behaves
    the way it always did rather than failing.
    """
    try:
        handle = reader(path)
    except Exception:
        return 0.0
    try:
        rate = float(handle.samplerate or 48000)
        if duration is None:
            try:
                duration = probe(path)[0]
            except Exception:
                duration = None
        # Only the last half minute is worth looking at, so a known duration
        # buys a seek straight to it rather than decoding a four minute song
        # to find out about its last two seconds. A file that will not seek is
        # read through, which is slower and gives the same answer.
        started_at = 0.0
        if duration and duration > MAX_TAIL_SCAN:
            landed = handle.seek_seconds(duration - MAX_TAIL_SCAN)
            if landed is not None:
                started_at = max(0.0, float(landed))
        block = max(1, int(0.02 * rate))
        chunk = block * 64
        played = 0
        last_loud = None
        while True:
            data = handle.read(chunk)
            if not len(data):
                break
            peak = np.abs(data).max(axis=1)
            for offset in range(0, len(peak), block):
                piece = peak[offset:offset + block]
                if len(piece) and float(piece.max()) > SILENCE_FLOOR:
                    last_loud = started_at + (played + offset + len(piece)) / rate
            played += len(data)
        total = duration if duration else started_at + played / rate
        if last_loud is None or not total:
            return 0.0
        return max(0.0, min(MAX_TAIL_SCAN, total - last_loud))
    except Exception:
        return 0.0
    finally:
        handle.close()
