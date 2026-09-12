"""Proving the cable actually works, by sending a tone down it and listening.

Everything else about a send is inferred. PortAudio opens a stream, reports
a healthy one, and says nothing whatever about whether a single sample
reached the other program. That gap is not theoretical: a fixed 512 frame
output buffer lost a measured 7.39 per cent of the audio into a cable while
PortAudio reported no underrun at all, which is the whole of what 3.6.0 was
built to fix, and it was found by recording the far end rather than by
asking the driver.

So this is the same measurement, small enough to run from a dialog. Play a
tone out of the device the show goes to, record the other end of the same
cable at the same time, and say what came back.

## Three things it can tell you, and only one of them is "it works"

- **Nothing came back.** The cable is not carrying anything. Either the two
  ends are not the two ends of one cable, or something has it muted.
- **It came back with holes in it.** This is the 3.6.0 fault and it is the
  one nobody can diagnose by ear: it sounds like a change in pitch rather
  than like dropouts. Tony, 9 September 2026: "a change in pitch, a little
  choppiness".
- **It came back clean**, with a level, so "I can hear it" has a number
  behind it.

## What it deliberately does NOT do

It does not touch the send. It opens its own output stream on the same
device and closes it again, because a test that runs through the live path
measures the show as well as the tone, and because the caller may well want
to test a cable before ever turning a send on.

It also never runs itself. `frame` refuses while the show is on air or
recording, for the obvious reason: this puts a loud tone into a cable that
somebody may be in a call on.

No wx and no board here, so every rule in it can be checked one at a time.
"""
from __future__ import annotations

import numpy as np

from . import constants as C
from . import endpoints
from .audiofile import CHANNELS

#: The tone. 1000 Hz is what the 3.6.0 measurement used, it sits in the
#: middle of everything a conferencing codec keeps, and a cycle count on it
#: is what turned "a change in pitch" into a number.
TONE_HZ = 1000.0
#: Played well below full scale. A test that clips tells you nothing about a
#: show that does not, and a tone at full scale into somebody's headphones
#: is a genuinely unpleasant thing to do to a person.
TONE_LEVEL = 0.3
#: How long it listens. Long enough for several dropouts to land in it at the
#: measured rate of about six a second, short enough that nobody waits.
SECONDS = 2.0

#: A block counts as a gap when its loudest sample is under this. The tone is
#: played at 0.3, so this is more than twenty decibels down: nothing but real
#: silence reaches it.
GAP_BELOW = 0.05
#: Sixty four samples is a third of a millisecond at 192 kHz, finer than any
#: gap worth hearing.
GAP_BLOCK = 64
#: Below this much of the tone arriving, nothing is getting through at all.
#: A cable carrying nothing reads as the noise floor, which is far under it.
ARRIVED_DB = -60.0
#: More than this share of the recording silent is a fault worth naming. Two
#: blocks out of a thousand is the far end starting a moment late.
GAP_SHARE_OK = 0.5


class Result:
    """What came back, and the sentence to say about it."""

    def __init__(self, ok=False, said="", level_db=-999.0, gap_share=0.0,
                 gaps=0, rate=0, heard=""):
        self.ok = ok
        self.said = said
        self.level_db = level_db
        self.gap_share = gap_share
        self.gaps = gaps
        self.rate = rate
        #: The recording device it actually listened on, for the report.
        self.heard = heard

    def __repr__(self):                                # pragma: no cover
        return "<Result %s %r>" % ("ok" if self.ok else "not ok", self.said)


def tone(frames, rate, phase=0.0, hz=TONE_HZ, level=TONE_LEVEL):
    """A block of the test tone, and the phase to carry into the next one."""
    step = 2.0 * np.pi * hz / rate
    angle = phase + step * np.arange(frames)
    wave = (level * np.sin(angle)).astype(np.float32)
    return (np.column_stack([wave] * CHANNELS),
            float((phase + step * frames) % (2.0 * np.pi)))


def level_at(signal, rate, hz=TONE_HZ, width=40.0):
    """How loud one frequency is in a recording, in dBFS.

    An ABSOLUTE level, never a ratio against the noise floor. The first
    version of the tool this came from divided by the median of the
    spectrum, and a recording of a pure tone has a median of essentially
    zero, so every answer came back around three hundred decibels. A number
    that large is not a strong signal, it is a broken measurement.

    A Hann window scales a sine by its coherent gain, the mean of the
    window, so dividing the peak by the window's sum and doubling it, for
    the half of the energy in the negative frequencies, gives the amplitude
    back.
    """
    if len(signal) < 16:
        return -999.0
    window = np.hanning(len(signal))
    spectrum = np.abs(np.fft.rfft(signal * window))
    freqs = np.fft.rfftfreq(len(signal), 1.0 / rate)
    band = (freqs > hz - width) & (freqs < hz + width)
    if not band.any():
        return -999.0
    amplitude = 2.0 * float(spectrum[band].max()) / float(window.sum())
    return float(20.0 * np.log10(max(amplitude, 1e-12)))


def silence_in(signal):
    """How much of a recording is silent: (share as a percentage, how many).

    The share and the count are two different questions and both matter. One
    long gap at the start is the far end opening late and is harmless; sixty
    short ones spread through it is the fault that sounds like a change in
    pitch.
    """
    usable = len(signal) // GAP_BLOCK * GAP_BLOCK
    if usable < GAP_BLOCK:
        return 100.0, 1
    envelope = np.abs(signal[:usable]).reshape(-1, GAP_BLOCK).max(axis=1)
    quiet = envelope < GAP_BELOW
    runs = int(np.count_nonzero(quiet[1:] & ~quiet[:-1])) + int(quiet[0])
    return float(quiet.sum()) / len(quiet) * 100.0, runs


def judge(signal, rate, heard=""):
    """The whole verdict on a recording of the far end.

    Separated from the recording itself so it can be checked against audio
    made by hand, with no sound card anywhere near it.
    """
    signal = np.asarray(signal, dtype=np.float32).reshape(-1)
    db = level_at(signal, rate)
    share, runs = silence_in(signal)

    if db < ARRIVED_DB:
        return Result(
            False, "Nothing came back. The other end of the cable heard "
            "silence, so the show is not reaching it. Check that the send is "
            "pointed at the cable's playback end and that nothing has it "
            "muted in the Windows volume mixer.",
            db, share, runs, rate, heard)

    # The trailing gap is the tone stopping, not a fault, so a single run at
    # the very end is not counted against it. This is why the share alone is
    # not the test: one run of any length is a start or a stop.
    if share > GAP_SHARE_OK and runs > 1:
        return Result(
            False, "The tone came back, but %.1f per cent of it was missing, "
            "in %d separate gaps. That is audio being lost on the way into "
            "the cable, and it sounds like a change in pitch rather than "
            "like dropouts, so it is easy to mistake for something else. "
            "Tell Tony, because the output buffer is supposed to make this "
            "impossible." % (share, runs),
            db, share, runs, rate, heard)

    where = (" Listening on %s." % heard) if heard else ""
    return Result(
        True, "The cable is working. The tone came back at %d decibels with "
        "nothing missing, at %d hertz.%s" % (round(db), rate, where),
        db, share, runs, rate, heard)


def capture_for(playback_name, found=None):
    """The recording device that is the far end of a playback device.

    Returns the name PortAudio would use, "CABLE Output (VB-Audio Virtual
    Cable)", or "". Windows keeps the short name and the sound card apart
    and every host API joins them, so this joins them the same way.
    """
    found = endpoints.endpoints() if found is None else found
    partner = endpoints.partner_of(playback_name, found)
    if not partner:
        return ""
    for point in found:
        if point.side == endpoints.CAPTURE and point.name == partner:
            ours = endpoints._render_for(playback_name, found)
            if ours is not None and point.device == ours.device:
                return point.full_name
    return partner


def _index_for(name, want_input):
    """The PortAudio device index for a name, WASAPI first, or None.

    WASAPI first for the same reason `output_devices` lists it first: the
    same sound card through MME is about two hundred milliseconds and
    through WASAPI is twenty two, measured. Nothing here depends on the
    latency, but a test should run through the path the app really uses.
    """
    import sounddevice as sd

    wanted = (name or "").strip()
    if not wanted:
        return None
    apis = [h["name"] for h in sd.query_hostapis()]
    devices = list(sd.query_devices())
    for api in ("Windows WASAPI", "Windows DirectSound", "MME"):
        for index, dev in enumerate(devices):
            if apis[dev["hostapi"]] != api:
                continue
            channels = (dev["max_input_channels"] if want_input
                        else dev["max_output_channels"])
            if channels <= 0:
                continue
            # MME truncates every name it has to 31 characters, so the name
            # off the registry is matched as a prefix rather than exactly.
            if dev["name"] == wanted or wanted.startswith(dev["name"]):
                return index
    return None


class _Apartment:
    """COM, initialised on whatever thread this runs on. Windows only.

    **A worker thread with no COM apartment cannot open a WASAPI stream,
    and the error it gets names the wrong thing entirely.** Measured
    11 September 2026, with a wx dialog on screen and the measurement on a
    background thread, opening a device resolved correctly to WASAPI:

        Error starting stream: Unanticipated host error [PaErrorCode -9999]:
        'GetNameFromCategory: usbTerminalGUID = 7D1E ' [Windows WDM-KS error]

    A WDM-KS error, for a WASAPI device, meaning neither. The same call
    from the main thread worked every time, which is exactly the shape of
    fault that gets written off as flaky. With CoInitializeEx on the worker
    it passed every time, in either apartment model.

    MULTITHREADED rather than apartment threaded because an STA thread has
    to pump a message loop and this one has no business doing that. It is
    a two second measurement, not a window.

    S_FALSE means COM was already up on this thread and still owes an
    uninitialise. RPC_E_CHANGED_MODE means somebody else got there first
    with the other model, which is fine and is NOT ours to undo.
    """

    _MULTITHREADED = 0x0
    _CHANGED_MODE = -2147417850              # RPC_E_CHANGED_MODE

    def __init__(self):
        self.ours = False

    def __enter__(self):
        try:
            import ctypes
            hr = ctypes.windll.ole32.CoInitializeEx(None,
                                                    self._MULTITHREADED)
            self.ours = hr not in (self._CHANGED_MODE,)
        except Exception:                              # not Windows
            self.ours = False
        return self

    def __exit__(self, *_exc):
        if not self.ours:
            return False
        try:
            import ctypes
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass
        return False


def run(playback_name, seconds=SECONDS):
    """Play a tone out of a device and record the far end of its cable.

    Blocking, and it takes `seconds`, so it belongs on a thread. It brings
    its own COM apartment for that reason, see `_Apartment`.

    **It opens its own streams and closes them again.** Not the send: a test
    that runs through the live path measures the show as well as the tone,
    and somebody may well want to prove a cable before turning a send on at
    all.
    """
    with _Apartment():
        return _run(playback_name, seconds)


def _run(playback_name, seconds):
    """The measurement itself, inside a COM apartment."""
    try:
        import sounddevice as sd
    except Exception as why:                           # pragma: no cover
        return Result(False, "The audio system could not be reached. %s"
                      % why)

    listen_name = capture_for(playback_name)
    if not listen_name:
        return Result(
            False, "There is no recording device that is the other end of "
            "%s, so there is nothing to listen on. A virtual audio cable has "
            "two ends and this looks like a sound card rather than a cable."
            % (playback_name or "that output"))

    out_index = _index_for(playback_name, want_input=False)
    in_index = _index_for(listen_name, want_input=True)
    if out_index is None or in_index is None:
        missing = playback_name if out_index is None else listen_name
        return Result(False, "Windows knows about %s but the audio system "
                             "cannot open it. Try unplugging and replugging "
                             "it, or restarting Drop Deck." % missing)

    rate = int(C.DEFAULT_SAMPLERATE)
    heard = []
    phase = 0.0

    def playing(outdata, frames, _time, _status):
        nonlocal phase
        block, phase = tone(frames, rate, phase)
        outdata[:] = block

    def listening(indata, _frames, _time, _status):
        heard.append(indata.copy())

    try:
        # Opened in this order on purpose: the recorder is listening before
        # the tone starts, so the leading silence is the cable's own latency
        # and not this function's.
        with sd.InputStream(device=in_index, samplerate=rate,
                            channels=1, dtype="float32",
                            blocksize=C.OUTPUT_BLOCKSIZE,
                            callback=listening):
            with sd.OutputStream(device=out_index, samplerate=rate,
                                 channels=CHANNELS, dtype="float32",
                                 blocksize=C.OUTPUT_BLOCKSIZE,
                                 callback=playing):
                sd.sleep(int(seconds * 1000))
    except Exception as why:
        return Result(False, "The cable could not be opened. %s "
                             "Something else may have exclusive use of it."
                      % why)

    if not heard:
        return Result(False, "Nothing was recorded from %s at all, so the "
                             "cable could not be measured." % listen_name)

    signal = np.concatenate(heard).reshape(-1)
    # The first moments are the streams starting at slightly different
    # times, which is not a gap in anybody's audio. Measured against a real
    # cable, the far end is listening before the tone arrives by design.
    skip = min(len(signal) // 4, int(rate * 0.25))
    return judge(signal[skip:], rate, listen_name)
