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
]

FIELDS = ("video_server", "video_host", "video_key", "live_to", "picture",
          "picture_file", "picture_clock", "camera", "screen", "split_corner",
          "colour_background", "colour_text", "colour_accent",
          "vision_model", "video_width", "video_height", "video_fps",
          "video_bitrate", "framing_level")

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
print("\n".join(out))
