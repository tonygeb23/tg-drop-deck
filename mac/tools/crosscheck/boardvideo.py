# The repository root is on the path already, put there by cross_check.py.
#
# The point of this one: the two copies read and write ONE board.json. A
# default that differs, or a whitelist that lets a value through on one side
# and not the other, is the same file behaving two ways on two machines. That
# is the worst class of bug this project can have, because nothing about it
# looks wrong until a show goes to the wrong place.
import json
import os
import tempfile


def sorted_repr(value):
    """A dict printed in key order, so the two sides compare content.

    Python prints a dict in insertion order and Swift has none, so the Swift
    side sorts. Without this the diff would be full of orderings rather than
    of differences.
    """
    if isinstance(value, dict):
        inner = ", ".join("%r: %s" % (k, sorted_repr(value[k]))
                          for k in sorted(value))
        return "{" + inner + "}"
    return repr(value)

from dropdeck.board import Board

# Every case is a board dict as it might really arrive: absent keys, keys of
# the wrong type, values out of range, values from a LATER build, and the
# 3.4.0 migration where the platform was saved in stream_server.
CASES = [
    ("empty", {}),
    ("nulls", {k: None for k in (
        "video_server", "video_host", "video_key", "live_to", "picture",
        "picture_file", "picture_clock", "camera", "screen", "split_corner",
        "text_places", "colour_background", "colour_text", "colour_accent",
        "vision_provider", "vision_model", "video_width", "video_height",
        "video_fps", "video_bitrate", "framing_level")}),
    ("youtube", {"video_server": "youtube", "live_to": "video",
                 "picture": "camera", "camera": "MacBook Pro Camera",
                 "video_width": 1920, "video_height": 1080, "video_fps": 60,
                 "video_bitrate": 6000, "framing_level": "everything"}),
    ("unknown-values", {"video_server": "vimeo", "live_to": "carrier pigeon",
                        "picture": "hologram", "screen": "monitor 3",
                        "split_corner": "middle", "vision_provider": "grok",
                        "framing_level": "chatty",
                        "colour_background": "puce", "colour_text": "puce",
                        "colour_accent": "puce"}),
    ("out-of-range", {"video_width": 0, "video_height": 99999,
                      "video_fps": 1000, "video_bitrate": -5}),
    ("range-edges", {"video_width": 160, "video_height": 2160,
                     "video_fps": 60, "video_bitrate": 200}),
    ("wrong-types", {"video_width": "1280", "video_height": 720.0,
                     "video_fps": [30], "video_bitrate": {"a": 1},
                     "picture_clock": "yes", "camera": 42,
                     "vision_model": 7}),
    ("migration", {"stream_server": "facebook",
                   "stream_host": "rtmps://live-api-s.facebook.com:443/rtmp",
                   "stream_mount": "/live"}),
    ("migration-not-video", {"stream_server": "icecast",
                             "stream_host": "radio.example.com"}),
    ("host-blank", {"video_server": "restream", "video_host": ""}),
    ("model-long", {"vision_model": "  " + "m" * 200 + "  "}),
    ("places-full", {"text_places": {
        "top": {"kind": "station", "words": "", "file": ""},
        "corner": {"kind": "time", "words": "", "file": ""},
        "lower": {"kind": "words", "words": "w" * 300, "file": ""},
        "clock": {"kind": "file", "words": "", "file": "/tmp/np.txt"}}}),
    ("places-bad", {"text_places": {
        "top": {"kind": "weather"},
        "nowhere": {"kind": "station"},
        "corner": "not a dict",
        "lower": {"kind": "words", "words": None, "file": None}}}),
    ("places-not-dict", {"text_places": ["top"]}),
    ("colours-good", {"colour_background": "navy", "colour_text": "cream",
                      "colour_accent": "gold"}),
    ("unknown-keys", {"something_from_a_later_build": {"a": 1},
                      "another": [1, 2, 3], "video_server": "restream"}),
]

#: Saved setups, which are the half that was quietly losing the video keys.
#: A station is filtered against STATION_FIELDS on the way in, so a station
#: carrying video settings written by one copy and opened by the other has to
#: survive.
STATIONS = [
    ("station-full", [{
        "stream_name": "Blindside Radio", "stream_server": "icecast",
        "stream_host": "radio.example.com", "stream_port": 8000,
        "stream_mount": "/live", "stream_password": "secret",
        "video_server": "youtube", "video_host": "rtmps://a.rtmps.youtube.com/live2",
        "live_to": "video", "picture": "camera", "camera": "A camera",
        "split_corner": "top left", "colour_background": "navy",
        "colour_text": "cream", "colour_accent": "gold",
        "video_width": 1920, "video_height": 1080, "video_fps": 60,
        "video_bitrate": 6000,
        "text_places": {"top": {"kind": "station", "words": "", "file": ""}},
    }]),
    # Saved before 3.4.0, so it carries no answer to "where does this go".
    # Loading it must KEEP what the user picked rather than blanking it.
    ("station-old", [{
        "stream_name": "Old One", "stream_server": "icecast",
        "stream_host": "old.example.com", "live_to": None,
    }]),
    ("station-junk", [{"stream_name": "Junk", "video_server": "vimeo",
                       "picture": "hologram", "video_width": 99999,
                       "text_places": "not a dict"},
                      {"no_name": True},
                      "not a dict at all"]),
]

# vision_provider is in here even though its value depends on what keys are in
# the credential store on THIS machine, because an absent one is the trap: it
# does not fall back to a constant like its fourteen neighbours, it asks
# best_provider. With no keys stored on either machine both sides answer the
# fallback, and that is what is compared.
FIELDS = ("video_server", "video_host", "video_key", "live_to", "picture",
          "picture_file", "picture_clock", "camera", "screen", "split_corner",
          "colour_background", "colour_text", "colour_accent",
          "vision_model", "video_width", "video_height", "video_fps",
          "video_bitrate", "framing_level", "vision_provider")

out = []
for name, payload in CASES:
    data = {"app": "TG Drop Deck", "format": 3}
    data.update(payload)
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, handle)
    handle.close()
    try:
        b = Board.load(handle.name)
    finally:
        os.unlink(handle.name)
    for f in FIELDS:
        out.append("%s|%s|%r" % (name, f, getattr(b, f)))
    for key in ("top", "corner", "lower", "clock"):
        spot = b.text_places[key]
        out.append("%s|place.%s|%r|%r|%r"
                   % (name, key, spot["kind"], spot["words"], spot["file"]))
    # And what it writes back out, which is the half that reaches Windows.
    d = b.to_dict()
    for f in FIELDS:
        out.append("%s|out.%s|%r" % (name, f, d[f]))
    # Unknown keys must survive untouched, or a board written by a later build
    # loses whatever that build added the first time this one saves it.
    for key in sorted(k for k in payload if k not in FIELDS):
        out.append("%s|kept.%s|%s" % (name, key, sorted_repr(d.get(key))))

# ------------------------------------------------------------- the stations ---
for name, stations in STATIONS:
    data = {"app": "TG Drop Deck", "format": 3, "stream_stations": stations,
            "live_to": "audio", "video_server": "facebook",
            "picture": "card", "split_corner": "bottom right"}
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, handle)
    handle.close()
    try:
        b = Board.load(handle.name)
    finally:
        os.unlink(handle.name)
    out.append("%s|count|%d" % (name, len(b.stream_stations)))
    for station in b.stream_stations:
        for key in sorted(station):
            out.append("  kept|%s|%s|%s" % (name, key, sorted_repr(station[key])))
    # Loading one has to bring the video half with it.
    for station in list(b.stream_stations):
        got = b.load_station(station.get("stream_name"))
        out.append("  loaded|%s|%s|%s" % (name, station.get("stream_name"), got))
        for f in FIELDS:
            out.append("    after|%s|%s|%r" % (name, f, getattr(b, f)))
    # And saving the current settings has to write it back out.
    b.save_station("Round Trip")
    saved = [x for x in b.stream_stations if x.get("stream_name") == "Round Trip"]
    for key in sorted(saved[0] if saved else {}):
        out.append("  saved|%s|%s|%s" % (name, key, sorted_repr(saved[0][key])))
print("\n".join(out))
