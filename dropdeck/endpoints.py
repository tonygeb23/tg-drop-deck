"""What format Windows has each sound device set to, and whether a cable agrees with itself.

Tony, 9 September 2026, on sending Drop Deck into TeamTalk: "a change in pitch,
a little choppiness". Chasing that turned up a second thing, on his own
machine, which nothing in this app could see:

    CABLE Input  (playback)   48000 Hz, 24 bit
    CABLE Output (recording)  192000 Hz, 16 bit

**Two ends of one cable, four times apart.** They are two separate Windows
endpoints with two separate format settings, in two different tabs of a dialog
nobody opens, and **nothing in Windows keeps them in step**. A virtual cable we
owned would close that by construction. On the road we are actually taking,
where Windows users install VB-CABLE, it has to be closed on purpose.

## What a mismatch really costs, stated honestly

Not the pitch. That was measured on 9 September and the cable is honest: 1000
Hz in, 1000.2 Hz out, whatever the two ends are set to. The driver converts.

What it costs is **two conversions instead of none**, on every sample, plus
whatever the receiving program then does to reach its own rate. At 192000 Hz
the capture side is also carrying four times the data for no benefit at all,
and a conferencing app is going to resample it down to 48000 or 16000 anyway.
So: wasted work, an extra conversion in the chain, and a setting that looks
deliberate and is not.

**This module reports. It does not write.** The endpoint format lives under
HKEY_LOCAL_MACHINE, so changing it needs administrator rights, and Drop Deck
installs per user precisely so it never needs them. See tools/dropdeck.iss,
where that is an accessibility decision rather than a packaging one.

## How the pairing is known

Not by guessing at names. Both ends of one cable carry the same **device
description**, `{b3f8fa53-0004-438e-9003-51a46e139bfc},6`, which for VB-CABLE
reads "VB-Audio Virtual Cable" on the render side and on the capture side.
That property is what ties them together, so this works for any cable whose
two ends come from one driver, not only the one we happen to have tested.

This module imports no wx and opens no sound card, which is what makes every
rule in it testable one at a time.
"""
from __future__ import annotations

import struct

try:
    import winreg
except ImportError:                                   # not Windows
    winreg = None

RENDER = "Render"
CAPTURE = "Capture"

_MMDEVICES = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"

#: The friendly name of the endpoint, "CABLE Input".
_NAME = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
#: The DEVICE description, "VB-Audio Virtual Cable". Shared by both ends of
#: one cable, which is what lets them be paired.
_DEVICE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
#: The format Windows has this endpoint set to, as a WAVEFORMATEX(TENSIBLE)
#: behind an eight byte property header.
_FORMAT = "{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0"

#: Endpoints Windows has switched off or unplugged. 1 is ACTIVE.
_ACTIVE = 1


class Endpoint:
    """One Windows sound endpoint and the format it is set to."""

    def __init__(self, side, name="", device="", rate=0, bits=0, channels=0):
        self.side = side
        self.name = name
        self.device = device
        self.rate = int(rate or 0)
        self.bits = int(bits or 0)
        self.channels = int(channels or 0)

    @property
    def known(self):
        return bool(self.rate and self.bits)

    @property
    def full_name(self):
        """The name PortAudio gives this endpoint.

        Windows stores the short name and the device apart, and every host
        API joins them: "CABLE Input" plus "VB-Audio Virtual Cable" is
        offered to us as "CABLE Input (VB-Audio Virtual Cable)". Measured on
        this machine, 11 September 2026, under MME, DirectSound and WASAPI.
        """
        if self.name and self.device:
            return "%s (%s)" % (self.name, self.device)
        return self.name or self.device

    def said(self):
        """The format, as somebody would say it out loud."""
        if not self.known:
            return "an unknown format"
        return "%d hertz, %d bit" % (self.rate, self.bits)

    def __repr__(self):                                # pragma: no cover
        return "<Endpoint %s %s %s>" % (self.side, self.name, self.said())


def _read_format(blob):
    """Rate, bits and channels out of a DeviceFormat property blob.

    The property is stored as an eight byte header (a type tag and a
    reserved word) followed by a WAVEFORMATEX, so every field is eight
    further along than a reader of the struct alone would expect. That
    offset is the whole trick and it is why this is a function with a test
    rather than three subscripts inline.
    """
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 24:
        return 0, 0, 0
    try:
        channels, rate = struct.unpack_from("<HI", blob, 10)
        bits = struct.unpack_from("<H", blob, 22)[0]
    except struct.error:
        return 0, 0, 0
    # A rate outside anything a sound card does means the blob was not what
    # we thought it was. Say nothing rather than something wrong.
    if not (4000 <= rate <= 768000):
        return 0, 0, 0
    return rate, bits, channels


#: MME truncates every device name to this many characters, so the cable
#: arrives as "CABLE Input (VB-Audio Virtual C". Measured, not looked up.
MME_NAME_LIMIT = 31


def _render_for(device_name, found):
    """The playback endpoint a PortAudio device name refers to, or None.

    **Two of these matching is not a near miss, it is a reason to say
    nothing.** Two identical sound cards have full names that agree for the
    first 31 characters, so under MME they are genuinely the same string and
    nothing here can tell them apart. A warning about the wrong one of a
    matched pair is worse than no warning, because the user would go and
    change a setting that was already right.
    """
    wanted = (device_name or "").strip()
    if not wanted:
        return None
    hits = []
    for point in found:
        if point.side != RENDER:
            continue
        full = point.full_name
        if full == wanted or (len(wanted) >= MME_NAME_LIMIT
                              and full.startswith(wanted)):
            hits.append(point)
    return hits[0] if len(hits) == 1 else None


def _read_side(side):
    out = []
    if winreg is None:
        return out
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                              "%s\\%s" % (_MMDEVICES, side))
    except OSError:
        return out
    try:
        index = 0
        while True:
            try:
                guid = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                key = winreg.OpenKey(root, guid)
                try:
                    state, _ = winreg.QueryValueEx(key, "DeviceState")
                except OSError:
                    state = _ACTIVE
                if int(state) != _ACTIVE:
                    continue
                props = winreg.OpenKey(key, "Properties")
            except OSError:
                continue
            values = {}
            for want in (_NAME, _DEVICE, _FORMAT):
                try:
                    values[want] = winreg.QueryValueEx(props, want)[0]
                except OSError:
                    values[want] = None
            rate, bits, channels = _read_format(values[_FORMAT])
            out.append(Endpoint(side, str(values[_NAME] or ""),
                                str(values[_DEVICE] or ""),
                                rate, bits, channels))
    finally:
        try:
            root.Close()
        except Exception:
            pass
    return out


def endpoints():
    """Every active playback and recording endpoint, with its format."""
    return _read_side(RENDER) + _read_side(CAPTURE)


def two_sided(found=None):
    """Devices that have BOTH a playback and a recording endpoint.

    Returns a list of (device description, render endpoint, capture
    endpoint).

    **These are not all cables, and assuming they were was wrong.** The first
    version of this said "a real sound card has a playback end and no
    matching capture end", and one run against this machine's registry
    disproved it: Realtek(R) Audio pairs Speakers with Microphone, and so
    does the Yeti. A headset is two sided and there is no reason on earth its
    two halves should share a sample rate. Warning about those would be
    nagging about somebody's headset.

    So this is the raw pairing, and `mismatch_for` is the thing that judges,
    scoped to the one device the user is actually sending a show into.
    """
    found = endpoints() if found is None else found
    by_device = {}
    for point in found:
        if not point.device:
            continue
        by_device.setdefault(point.device, {}).setdefault(point.side, point)
    pairs = []
    for device, sides in sorted(by_device.items()):
        render, capture = sides.get(RENDER), sides.get(CAPTURE)
        if render is not None and capture is not None:
            pairs.append((device, render, capture))
    return pairs


def mismatch_for(playback_name, found=None):
    """Is the cable we are sending into set the same at both ends.

    ``playback_name`` is the friendly name of the output the programme is
    going to, "CABLE Input". Returns a sentence, or "" when there is nothing
    to say.

    **Deliberately scoped to one device.** A warning about every two sided
    device on the machine would fire on headsets, which is noise, and noise
    is how a real warning gets ignored. The user chose this one as the place
    to send their show, which is what makes its two ends our business: they
    are relying on something else picking the audio up off the other end.
    """
    found = endpoints() if found is None else found
    ours = _render_for(playback_name, found)
    if ours is None:
        return ""
    for device, render, capture in two_sided(found):
        if render is not ours:
            continue
        if not (render.known and capture.known):
            return ""
        if (render.rate, render.bits) == (capture.rate, capture.bits):
            return ""
        return (
            "%s and %s are the two sides of one device and Windows has them "
            "set differently: %s going in, %s coming out. Nothing in Windows "
            "keeps those two in step, so it is worth setting both the same. "
            "48000 hertz is a good choice, in Sound settings under each "
            "one's Properties and then Advanced. It works as it is, it just "
            "converts twice for no reason."
            % (render.name or "the playback end",
               capture.name or "the recording end",
               render.said(), capture.said()))
    return ""


def partner_of(playback_name, found=None):
    """What a program should choose to hear what we send. "CABLE Output".

    This is the single most useful sentence the whole feature has. Sending a
    show into a cable is only half the job: somebody then has to pick the
    OTHER end of it in TeamTalk, and the two are named from the cable's point
    of view, so the thing you choose over there is the one whose name says
    Output. Tony had to work that out for himself.
    """
    found = endpoints() if found is None else found
    ours = _render_for(playback_name, found)
    if ours is None:
        return ""
    for _device, render, capture in two_sided(found):
        if render is ours:
            return capture.name
    return ""


def describe(found=None):
    """Every two sided device and what it is set to, for a diagnostic."""
    lines = []
    for device, render, capture in two_sided(found):
        if render.known and capture.known and \
                (render.rate, render.bits) == (capture.rate, capture.bits):
            lines.append("%s is set to %s at both ends."
                         % (device, render.said()))
        else:
            lines.append("%s is %s going in and %s coming out."
                         % (device, render.said(), capture.said()))
    return lines
