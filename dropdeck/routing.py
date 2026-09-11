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
