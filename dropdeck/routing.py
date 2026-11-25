"""Where everything goes, and what makes a routing wrong.

Tony, 10 September 2026, on getting Drop Deck into TeamTalk: "the vb cable
input is set as an output device, right? the vb cable output is then set as
the input device on teamtalk, so, vb cable input output device sends things to
vb cable output. does this make any sense?"

It does, and the names are the reason it has to be asked. A virtual cable is
named from the CABLE's point of view and not the user's: "CABLE Input" is a
playback device because it is the input TO the cable, and "CABLE Output" is a
recording device because it is the output OF the cable. So a program plays
into CABLE Input and another program records from CABLE Output. Everybody
reads that backwards the first time.

This module imports no wx and touches no sound card, which is what makes every
rule in it testable one at a time. Everything it needs is passed in. Same
reason `preflight.py` is built that way.

## The three roles, and why they are three

- **The banks** play out of a sound card each, so a presenter can ride the
  balance of drops against beds on a real desk. That is a MIXING choice.
- **The monitor** is what the presenter hears. With the full programme
  monitor on it carries every card's show, so it is one pair of headphones
  with everything in it.
- **The programme output** is the whole show, pads and beds and playlist and
  microphone and every captured source, out of one card for another program
  on this machine to pick up. That is a DELIVERY choice, and it is the one
  the cable wants.

The main output is NOT the programme. It carries the pads, the beds and the
playlist; the microphone and the captured sources live on the on air mix.
Measured 10 September 2026 with the banks on one card and the monitor on
another: the banks' card carried the pads and no microphone, and the monitor
carried the microphone and no pads. Neither output had the whole show. That
is why the programme output exists rather than somebody being told to point
the main output at a cable.
"""
from __future__ import annotations

#: What each role is called when it is spoken aloud. The wording is the
#: user's, not the code's: nobody says "bank device".
BANKS = "your sounds"
MONITOR = "what you hear"
PROGRAM = "the programme output"


def conflicts(bank_devices=None, monitor_device=None, program_device=None,
              program_on=False, describe=None):
    """Everything wrong with this routing, as sentences to read aloud.

    ``bank_devices`` is the {bank: device} mapping, ``monitor_device`` the
    card the presenter listens on, ``program_device`` the card the whole show
    goes out of for another program to take. Devices are whatever the rest of
    the app uses for one: an index, or None for the system default.

    ``describe`` turns a device into a name. Left out, a device is called by
    its own value, which is enough for a test and no use to a person.

    Returns a list of strings. Empty means the routing is sound.

    **The main output and the monitor being the same card is NOT a conflict**,
    and that matters more than any rule here: it is what every single sound
    card setup in the world looks like, and refusing it would break the
    ordinary case to guard the unusual one. What is refused is the programme
    output landing on a card that is already doing something else, because
    then that card carries the show twice.
    """
    describe = describe or (lambda device: str(device))
    found = []
    if not program_on:
        # Nothing is being sent, so nothing can collide with it. A programme
        # output that is not on is not a routing at all.
        return found

    # The system default deserves its own sentence, and it comes FIRST because
    # it is the one that explains the others. This used to sit forty lines
    # below an early return that included `program_device is None`, so the one
    # case the module's own comment calls "how a show ends up going out of the
    # laptop speakers" was the one case it could never report. Dead code,
    # found by Mark, 10 September 2026.
    if program_device is None:
        found.append(
            "%s is set to the system default, so it will follow whatever "
            "Windows is using. Choose the card by name instead." % PROGRAM)

    banks = dict(bank_devices or {})
    clashing = sorted({bank for bank, device in banks.items()
                       if device == program_device})
    if clashing:
        found.append(
            "%s is carrying %s as well as %s, so that card would get the "
            "show twice. Send the programme somewhere nothing else is using, "
            "or move those sounds to another card."
            % (describe(program_device),
               _banks_said(clashing), PROGRAM))

    if monitor_device == program_device:
        found.append(
            "%s is both %s and %s, so you would hear the whole show twice "
            "over. Send the programme to a card of its own."
            % (describe(program_device), MONITOR, PROGRAM))

    return found


#: MME cuts every device name to this many characters. See micinput.
_MME_NAME = 31


def same_device(a, b):
    """Are two names the same sound device, however Windows spelled them.

    Equal, or one is the other cut to 31 characters, which is how MME offers
    every device. Nothing looser: a short name standing for any device that
    starts with it called "Microphone" the same card as every microphone on
    the machine.
    """
    raw = (a or "", b or "")
    if not raw[0].strip() or not raw[1].strip():
        return False
    if raw[0].strip() == raw[1].strip():
        return True
    # Unstripped: the cut can end on a space, "CABLE Output (VB-Audio
    # Virtual " is exactly 31, and that space is part of MME's name.
    short, full = sorted(raw, key=len)
    return len(short) == _MME_NAME and full.startswith(short)


def _split(name):
    """The endpoint and its card: "CABLE Input (VB-Audio Virtual Cable)" is
    ("CABLE Input", "VB-Audio Virtual Cable"). A name MME cut short keeps
    whatever it has left of the card."""
    name = (name or "").strip()
    at = name.find(" (")
    if at < 0:
        return name, ""
    return name[:at].strip(), name[at + 2:].rstrip(")").strip()


def _same_card(a, b):
    """Two card names from inside the brackets, either possibly cut by MME."""
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


#: Virtual cables this app knows by name, as (pattern for the end a program
#: plays into, pattern for the end a program records from). Each is matched
#: against the endpoint's own name, the part before the card in brackets, and
#: the card must be the same on both sides. A group named "which" must agree,
#: so CABLE-A is never taken for CABLE-B.
_CABLES = (
    # VB-Audio CABLE and its A, B, C and D: "CABLE Input" and "CABLE Output",
    # "CABLE-A Input" and "CABLE-A Output".
    (r"cable(?P<which>-[a-d])? in(put)?\b", r"cable(?P<which>-[a-d])? output\b"),
    # VoiceMeeter's virtual inputs and the B buses they feed by default:
    # "VoiceMeeter Input" against "VoiceMeeter Output", the Aux and VAIO3
    # pairs the same way, and the newer "Voicemeeter Out B1" spelling.
    (r"voicemeeter(?P<which> aux| vaio3)? input\b",
     r"voicemeeter(?P<which> aux| vaio3)? (output|out b\d)\b"),
)

#: Virtual Audio Cable names a line the same at both ends: "Line 1 (Virtual
#: Audio Cable)" is the playback and the recording.
_SAME_NAME_CARDS = ("virtual audio cable",)

#: Recording endpoints that ARE what the same card plays: a Focusrite style
#: "Loopback" input, Realtek's "Stereo Mix" and the like. Only ever a loop on
#: the card the show is being sent INTO.
_LOOPBACK_INPUT = r"(loopback|stereo mix|what u hear|wave out mix)\b"


def loops_back(sent_to, heard_from):
    """Would recording ``heard_from`` pick up what is sent into ``sent_to``.

    Decided by the cable's naming and nothing else, and only for something
    that IS a loop by construction: a known virtual cable's other end, or a
    loopback input on the card the show is sent into. **A physical card's
    microphone is never a loop here**, whatever Windows pairs it with. A
    false refusal is worse than a missed loop: it takes a guest on a USB
    headset off the air, where a missed loop is an echo somebody hears and
    can stop. The registry pairs the two ends of a device by the card's
    description, and a headset's speakers and microphone share one, so the
    registry cannot be what decides (Mark, 24 November 2026).
    """
    import re
    if not sent_to or not heard_from:
        return False
    out_name, out_card = _split(sent_to)
    in_name, in_card = _split(heard_from)
    if not _same_card(out_card, in_card):
        return False
    out_name, in_name = out_name.lower(), in_name.lower()
    for plays, records in _CABLES:
        played = re.match(plays, out_name)
        recorded = re.match(records, in_name)
        if (played and recorded and (played.group("which") or "")
                == (recorded.group("which") or "")):
            return True
    if any(card in out_card.lower() for card in _SAME_NAME_CARDS):
        return same_device(sent_to, heard_from) or out_name == in_name
    return bool(re.match(_LOOPBACK_INPUT, in_name))


def captures_itself(sent_to, captures, _unused=""):
    """Every input that would pick the send's own audio back up.

    ``sent_to`` is the device the whole show is sent into ("CABLE Input
    (VB-Audio Virtual Cable)"), and ``captures`` a list of (who, device
    name) pairs: the microphone and every source. `loops_back` says what
    counts, and it is deliberately narrow.

    **This is the loop, and nothing used to stop it.** The send carries the
    microphone and every source, so an input on the other end of the cable
    the show goes into hears the show, puts it on the air, and the send
    carries it round again a cable's delay later: an echo that feeds itself.
    Returns one sentence per input that would do it.
    """
    found = []
    for who, name in captures or []:
        if loops_back(sent_to, name):
            found.append(
                "%s listens to %s, which hears everything sent into %s, "
                "where your show is being sent. That would send the show "
                "back into itself, round and round, so it is refused. "
                "Choose a different input for %s, or send the show "
                "somewhere else." % (who, name, sent_to, _object(who)))
    return found


def _object(who):
    """"Your microphone" is "your microphone" mid sentence; a name is kept."""
    return who[:1].lower() + who[1:] if who.startswith("Your ") else who


def _banks_said(banks):
    """"bank 2" or "banks 2 and 3", said rather than listed."""
    words = ["bank %d" % bank for bank in banks]
    if len(words) == 1:
        return words[0]
    return "%s and %s" % (", ".join(words[:-1]), words[-1])


def describe_routing(bank_devices=None, monitor_device=None,
                     program_device=None, program_on=False,
                     monitor_everything=True, describe=None,
                     bank_names=None):
    """The whole routing in one spoken paragraph.

    This is the thing somebody who cannot see it actually needs: not a page
    of controls, but the answer to "where is all of this going" read out in
    one go. Every fact in it comes from the arguments, so it can never drift
    from what the app is really doing.
    """
    describe = describe or (lambda device: str(device))
    names = dict(bank_names or {})
    banks = dict(bank_devices or {})

    # Group the banks by card, so four banks on one card is one sentence.
    by_card = {}
    for bank in sorted(banks) or []:
        by_card.setdefault(banks.get(bank), []).append(bank)
    if not by_card:
        by_card = {None: []}

    parts = []
    for device, which in by_card.items():
        where = describe(device)
        if not which or len(which) >= 4:
            parts.append("Your sounds play out of %s." % where)
        else:
            said = [names.get(bank, "bank %d" % bank) for bank in which]
            # Not str.capitalize: it lowercases everything after the first
            # letter, so a bank the user called "Music Beds" came back as
            # "Music beds". Only the first character is the app's business.
            first = said[0][:1].upper() + said[0][1:]
            said = [first] + said[1:]
            if len(said) == 1:
                joined, verb = said[0], "plays"
            else:
                joined = "%s and %s" % (", ".join(said[:-1]), said[-1])
                verb = "play"
            parts.append("%s %s out of %s." % (joined, verb, where))

    if monitor_device is not None and monitor_device not in by_card:
        if monitor_everything:
            parts.append("You hear everything on %s."
                         % describe(monitor_device))
        else:
            parts.append("You hear your microphone on %s, and nothing else "
                         "that is on another card."
                         % describe(monitor_device))

    if program_on and program_device is not None:
        parts.append("The whole show, your microphone and your sources "
                     "included, also goes out of %s for another program to "
                     "pick up." % describe(program_device))
    else:
        parts.append("Nothing is being sent to another program.")
    return " ".join(parts)
