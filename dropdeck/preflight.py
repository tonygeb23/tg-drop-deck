"""What is about to go on the air, worked out before it does.

Ctrl+B used to be a leap. The app knew perfectly well where the show was
going, what it was encoding, what would be on the screen and whether the
presenter's own microphone was part of the programme, and it said none of it:
it connected, and several seconds later either announced the destination or a
failure. A sighted broadcaster has a rack of settings in front of them and can
glance at it. There is no glance here, so the app has to say it.

**And "it connected" is not the same claim as "it is right".** Nearly every way
of getting this wrong survives the connection and ruins the broadcast quietly:

  * a picture file that has been moved sends a flat dark rectangle for three
    hours, because ImageSource fills a canvas rather than failing;
  * the microphone left off the programme sends a show with no presenter on
    it, and it sounds perfect from where the presenter is sitting because
    monitoring is downstream of the split;
  * the wrong one of the two destinations ticked sends the show to a radio
    server nobody is listening to while the video platform waits;
  * a bitrate outside what the platform publishes can have the broadcast
    ended from the other end, with nothing said at this one.

None of those raise. All of them are knowable in advance. So this module is
the answer to every one: given the settings and a few facts about the running
app, say what will be sent and what is wrong with it, in a form the frame can
speak, put in a dialog, or assert against in a test.

**Nothing here imports wx, and nothing here touches the network.** It is
arithmetic and string building over a settings dict, which is what makes the
whole of it testable with no sound card, no camera and no display, and why the
list of warnings can be checked one by one rather than by going on the air.
"""
from __future__ import annotations

import os

from . import constants as C
from . import streamout


#: A problem that will stop the broadcast working at all. Ctrl+B does not
#: proceed past one of these.
STOP = "stop"

#: A problem that will let the broadcast happen and spoil it. These are the
#: expensive ones, because nothing downstream will mention them again.
WARN = "warn"


class Note:
    """One thing worth saying before going live."""

    def __init__(self, level, text, fix=""):
        self.level = level
        self.text = text
        #: Where to send somebody who wants to put it right. A settings page
        #: constant, or "" when there is nothing to open.
        self.fix = fix

    def __repr__(self):      # pragma: no cover - debugging only
        return "Note(%r, %r)" % (self.level, self.text)


class Preflight:
    """What Ctrl+B is about to do, and what is wrong with it."""

    def __init__(self, target, lines, notes):
        #: C.LIVE_TO_AUDIO or C.LIVE_TO_VIDEO.
        self.target = target
        #: The summary, as (label, value) pairs in the order they are read.
        #: A list rather than a dict because the order is the whole point:
        #: where it is going first, then what is being sent, then who is on it.
        self.lines = list(lines)
        self.notes = list(notes)

    @property
    def stops(self):
        return [n for n in self.notes if n.level == STOP]

    @property
    def warnings(self):
        return [n for n in self.notes if n.level == WARN]

    @property
    def blocked(self):
        return bool(self.stops)

    def summary(self):
        """The one sentence answer to "where is this going".

        First line only. Everything else is available and this is what gets
        spoken when somebody just wants to go live.
        """
        return self.lines[0][1] if self.lines else ""

    def spoken(self):
        """The whole thing, as one string a screen reader reads straight through.

        Semicolons rather than full stops between the settings, so a screen
        reader runs them together as a list rather than reading each as its
        own sentence, and full stops before the problems so they land
        separately. Measured against NVDA rather than guessed at.
        """
        parts = ["%s %s" % (label, value) for label, value in self.lines]
        said = "; ".join(parts)
        trouble = [n.text for n in self.notes]
        if trouble:
            said += ". " + ". ".join(trouble)
        return said


def where_it_goes(settings, video):
    """The destination, said the way its owner would say it.

    The station's own NAME first when it has one, because that is what the
    user called it and it is shorter and clearer than the software running
    on it. `server_label` says "Icecast, or Liquidsoap harbor", which is
    exactly right in the Preferences dropdown, where somebody is working out
    which entry covers their server, and exactly wrong on the way to air.

    The software name is the fallback rather than the lead, so a server with
    no name still says something useful.

    **The two destinations have two names and this must never borrow one for
    the other.** `name` is the radio station. A video platform's name is
    `video_name`, which is usually empty, and an empty one means the platform
    speaks for itself. It used to print the radio station's name on the way to
    YouTube: "Blindside Radio, on YouTube Live", which names an Icecast
    station as though it were a YouTube channel. Tony read that on 12
    September 2026 and called it untrue, because it is.
    """
    host = settings.get("host", "")
    if video:
        # An RTMP address has the stream key in it, so it goes through
        # host_label. YouTube and Facebook have one address each and it is
        # not the user's to choose, so naming the platform is enough.
        platform = streamout.server_label(settings.get("server", "")) or ""
        channel = (settings.get("video_name") or "").strip()
        if channel and platform:
            return "%s, on %s" % (channel, platform)
        if channel:
            return channel
        if not platform:
            return streamout.host_label(host)
        # YouTube and Facebook have ONE address each and it is not the user's
        # to choose, so the address tells them nothing they can act on and
        # reads as a scary URL on the way to air. A custom server's address
        # is the one useful fact about it, so that one keeps it.
        if settings.get("server", "") in C.RTMP_FIXED_ADDRESS:
            return platform
        return "%s, %s" % (platform, streamout.host_label(host))
    name = (settings.get("name") or "").strip()
    where = "%s%s" % (host, settings.get("mount", "") or "")
    if name:
        return "%s, %s" % (name, where)
    return "%s, %s" % (streamout.server_label(settings.get("server", "")), where)


def _picture_words(settings):
    """What will be on the screen, said as the audience would see it."""
    kind = settings.get("picture", C.PICTURE_CARD)
    if kind == C.PICTURE_IMAGE:
        path = settings.get("picture_file", "")
        return "your own picture, %s" % (os.path.basename(path) or "not chosen")
    if kind == C.PICTURE_CAMERA:
        return settings.get("camera") or "a camera, but none is chosen"
    if kind == C.PICTURE_SCREEN:
        return "what is on your screen"
    if kind == C.PICTURE_SPLIT:
        camera = settings.get("camera") or "no camera chosen"
        return "your screen, with %s in the corner" % camera
    name = settings.get("name") or settings.get("stream_name") or ""
    if name:
        return "a card saying %s" % name
    return "a card"


#: What is going to consume the picture, for the warnings to name. A
#: recording is not a stream, and a sentence that says "the stream would show
#: an empty screen" to somebody about to record ninety minutes tells them to
#: check the wrong thing.
FOR_STREAM = "the stream"
FOR_RECORDING = "the recording"


def _check_picture(settings, notes, screen_ready=True, screen_reason="",
                   consumer=FOR_STREAM):
    """Everything that can be wrong with the picture, before it is opened."""
    kind = settings.get("picture", C.PICTURE_CARD)
    if kind == C.PICTURE_IMAGE:
        path = settings.get("picture_file", "")
        if not path:
            notes.append(Note(WARN, "No picture file has been chosen, so %s "
                                    "would show an empty screen" % consumer,
                              C.FIX_VIDEO))
        elif not os.path.isfile(path):
            # The expensive one. ImageSource fills a canvas with the
            # background colour rather than returning None, so the fallback
            # never fires, nothing is announced, and the whole broadcast is a
            # dark rectangle that looks deliberate.
            notes.append(Note(WARN, "That picture file is not there any more, "
                                    "so %s would show an empty screen"
                                    % consumer, C.FIX_VIDEO))
    if kind in C.PICTURE_NEEDS_CAMERA and not settings.get("camera"):
        notes.append(Note(WARN, "No camera has been chosen, so %s would fall "
                                "back to a card" % consumer, C.FIX_VIDEO))
    if kind in C.PICTURE_NEEDS_SCREEN and not screen_ready:
        notes.append(Note(WARN, screen_reason or "The screen cannot be "
                                                 "captured on this machine",
                          C.FIX_VIDEO))


def picture_notes(settings, board, screen_ready=True, screen_reason="",
                  consumer=FOR_STREAM):
    """Everything wrong with the picture, for anybody who wants one.

    Split out of `check` so `Ctrl+Shift+R` can ask it. The picture half of
    the pre-flight was gated on `board.live_to`, so a board pointed at a
    radio station got no picture checks at all, which is exactly the board
    that records video: no "no camera has been chosen", no moved picture
    file, no "the screen cannot be captured", no overlay text measured.

    Imports nothing and fetches nothing, like everything else in this file,
    so every warning is testable one at a time.
    """
    notes = []
    _check_picture(settings, notes, screen_ready, screen_reason, consumer)
    _check_screen_text(settings, board, notes)
    if (settings.get("picture") == C.PICTURE_CARD
            and not getattr(board, "stream_titles", True)):
        # The card is the only place a viewer finds out what is playing, and
        # the switch that freezes it lives on the other page.
        notes.append(Note(WARN, "Track titles are turned off, so the card "
                                "will not say what is playing", C.FIX_AUDIO))
    return notes


def _check_screen_text(settings, board, notes):
    """Whether anything on top of the picture would be cut off.

    Answerable now, and only now: once you are on the air the only way to
    find out is somebody watching telling you. The place has a known width
    and the text has a measurable one, so "that will not fit" is arithmetic
    rather than an opinion.
    """
    places = getattr(board, "text_places", None)
    if not places:
        return
    try:
        from . import overlay
    except Exception:
        return
    if not overlay.available():
        return
    width = settings.get("video_width", C.RTMP_WIDTH)
    height = settings.get("video_height", C.RTMP_HEIGHT)
    for key in C.PLACES_ORDER:
        held = places.get(key) or {}
        kind = held.get("kind", C.TEXT_NONE)
        if kind == C.TEXT_NONE:
            continue
        if kind == C.TEXT_WORDS:
            words = held.get("words", "")
            if not words:
                notes.append(Note(WARN, "The %s is set to your own words and "
                                        "there are none yet, so it would be "
                                        "empty" % overlay.place_label(key).lower(),
                                  C.FIX_VIDEO))
                continue
        elif kind == C.TEXT_FILE:
            path = held.get("file", "")
            if not path:
                notes.append(Note(WARN, "The %s is set to read a file and none "
                                        "is chosen, so it would be empty"
                                  % overlay.place_label(key).lower(),
                                  C.FIX_VIDEO))
                continue
            if not os.path.isfile(path):
                notes.append(Note(WARN, "The file the %s reads is not there any "
                                        "more, so it would be empty"
                                  % overlay.place_label(key).lower(),
                                  C.FIX_VIDEO))
                continue
            words = ""
        elif kind == C.TEXT_STATION:
            words = settings.get("name") or ""
            if not words:
                notes.append(Note(WARN, "The %s shows your station name and "
                                        "there is not one set"
                                  % overlay.place_label(key).lower(),
                                  C.FIX_AUDIO))
                continue
        else:
            continue
        if words and not overlay.fits(words, key, width, height):
            notes.append(Note(WARN, "%s is too long for the %s and would be "
                                    "cut short" % (words,
                                                   overlay.place_label(key).lower()),
                              C.FIX_VIDEO))


def check(settings, board, audio_running=True, mic_open=False,
          screen_ready=True, screen_reason=""):
    """Work out what Ctrl+B would do with these settings.

    `settings` is what `_stream_settings` builds, so this sees exactly what
    the streamer will see rather than a second reading of the board. The live
    facts are passed in rather than fetched, which is what keeps this callable
    from a test with nothing running.
    """
    notes = []
    lines = []
    video = board.live_to == C.LIVE_TO_VIDEO
    server = settings.get("server", "")
    host = settings.get("host", "")
    page = C.FIX_VIDEO if video else C.FIX_AUDIO

    # ---------------------------------------------------------- where it goes
    if not host:
        lines.append(("Going to", "nowhere: no %s is set up yet"
                      % ("video platform" if video else "server")))
        notes.append(Note(STOP, "There is no %s set up yet"
                          % ("video platform" if video else "server"), page))
    else:
        lines.append(("Going to", where_it_goes(settings, video)))

    # ------------------------------------------------------------ the sound
    spec = streamout.FORMATS.get(settings.get("format", "mp3"))
    fmt = spec["label"] if spec else str(settings.get("format", "")).upper()
    lines.append(("Sound", "%d kbps %s" % (settings.get("bitrate", 0), fmt)))

    # ------------------------------------------------------------ the picture
    if video:
        lines.append(("Picture", "%s, %d by %d at %d kbps"
                      % (_picture_words(settings),
                         settings.get("video_width", C.RTMP_WIDTH),
                         settings.get("video_height", C.RTMP_HEIGHT),
                         settings.get("video_bitrate", C.RTMP_VIDEO_BITRATE))))

    # ---------------------------------------------------------- the presenter
    # Said every time, not only when it is wrong. "Microphone on air" is the
    # line a presenter wants to hear before they start talking, and a warning
    # that only appears when something is broken teaches nobody where to look.
    if board.stream_mic:
        lines.append(("Microphone", "on the air" if mic_open
                      else "on the air when you open it, Ctrl+M"))
    else:
        lines.append(("Microphone", "NOT going out"))
        notes.append(Note(WARN, "Your microphone is not on the air, so "
                                "listeners will not hear you at all",
                          C.FIX_AUDIO))

    # ------------------------------------------------------------- the faults
    if video and not settings.get("password"):
        notes.append(Note(STOP, "There is no stream key for this station",
                          C.FIX_VIDEO))
    if not video and host and not settings.get("password"):
        # Not a stop: a private Icecast can be set up to want no password, and
        # refusing to broadcast over a guess would be worse than the warning.
        notes.append(Note(WARN, "There is no password for this server, which "
                                "most servers will refuse", C.FIX_AUDIO))
    if not audio_running:
        notes.append(Note(STOP, "The sound card is not running, so there is "
                                "nothing to send", C.FIX_AUDIO))
    if video:
        notes.extend(picture_notes(settings, board, screen_ready,
                                   screen_reason, FOR_STREAM))
        advice = streamout.bitrate_advice(
            server, settings.get("video_width", C.RTMP_WIDTH),
            settings.get("video_height", C.RTMP_HEIGHT),
            settings.get("video_fps", C.RTMP_FPS),
            settings.get("video_bitrate", C.RTMP_VIDEO_BITRATE),
            settings.get("bitrate", 128))
        if advice:
            notes.append(Note(WARN, advice, C.FIX_VIDEO))
    warning = going_live_warning(board)
    if warning:
        notes.append(Note(WARN, warning, ""))
    return Preflight(board.live_to, lines, notes)


def going_live_warning(board):
    """What the platform itself does the moment the stream connects.

    The two behave in opposite ways and both surprises are expensive: YouTube
    publishes and notifies subscribers at once, Facebook shows a preview and
    posts nothing. This is said BEFORE connecting now. It used to be said
    after, which is the wrong side of the only decision it informs.
    """
    if board.live_to != C.LIVE_TO_VIDEO:
        return ""
    if C.RTMP_GOES_LIVE_AT_ONCE.get(board.video_server):
        return ("%s puts you live the moment you connect, and tells your "
                "subscribers" % streamout.server_label(board.video_server))
    if board.video_server == "facebook":
        return ("Facebook will show you a preview and post nothing until you "
                "press Go Live Now")
    return ""
