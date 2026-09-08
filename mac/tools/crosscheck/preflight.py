# The repository root is on the path already, put there by cross_check.py.
import itertools
from dropdeck import constants as C
from dropdeck import preflight as P
from dropdeck import streamout


class Board:
    """Only the attributes preflight.check actually reads."""
    def __init__(self, live_to, video_server, stream_mic, stream_titles,
                 text_places=None):
        self.live_to = live_to
        self.video_server = video_server
        self.stream_mic = stream_mic
        self.stream_titles = stream_titles
        self.text_places = text_places or {}


out = []

# ---------------------------------------------------------------- labels ---
for key in ("icecast", "shoutcast", "youtube", "facebook", "restream", "rtmp",
            "nonsense", ""):
    out.append("label|%s|%s" % (key, streamout.server_label(key)))
    out.append("isrtmp|%s|%s" % (key, streamout.is_rtmp(key)))

for url in ("rtmps://a.rtmps.youtube.com/live2/abcd-key",
            "rtmp://live.restream.io/live", "http://radio.example.com:8000",
            "not a url", "", "rtmps://live-api-s.facebook.com:443/rtmp/FB-1-key"):
    out.append("host|%s|%s" % (url, streamout.host_label(url)))

# -------------------------------------------------------- bitrate advice ---
for server in ("facebook", "youtube", "restream", "rtmp"):
    for (w, h, fps) in ((1920, 1080, 60), (1920, 1080, 30), (1280, 720, 60),
                        (1280, 720, 30), (854, 480, 30), (640, 360, 30),
                        (1024, 576, 25)):
        for vb in (400, 500, 1500, 2500, 4000, 6000, 12000):
            for ab in (128, 320):
                got = streamout.bitrate_advice(server, w, h, fps, vb, ab)
                out.append("advice|%s|%d|%d|%d|%d|%d|%s"
                           % (server, w, h, fps, vb, ab, got))

# ------------------------------------------------------------ where it goes ---
for video in (False, True):
    for name in ("", "Blindside Radio"):
        for server in ("icecast", "shoutcast", "youtube", "facebook", "restream", "rtmp"):
            for host in ("", "radio.example.com", "rtmps://a.rtmps.youtube.com/live2/k"):
                s = {"server": server, "host": host, "name": name, "mount": "/live"}
                out.append("goes|%s|%s|%s|%s|%s"
                           % (video, name, server, host, P.where_it_goes(s, video)))

# --------------------------------------------------------- picture words ---
for kind in C.PICTURE_SOURCES:
    for cam in ("", "MacBook Pro Camera"):
        for pf in ("", "/tmp/nope/art.png"):
            for name in ("", "Tony's Tunes"):
                s = {"picture": kind, "camera": cam, "picture_file": pf,
                     "name": name, "stream_name": ""}
                out.append("pic|%s|%s|%s|%s|%s"
                           % (kind, cam, pf, name, P._picture_words(s)))

# -------------------------------------------------- going live warning ---
for live_to in C.LIVE_TO:
    for vs in ("youtube", "facebook", "restream", "rtmp", ""):
        out.append("warn|%s|%s|%s"
                   % (live_to, vs, P.going_live_warning(Board(live_to, vs, True, True))))

# --------------------------------------------------------- the whole check ---
n = 0
for live_to in C.LIVE_TO:
    for server, host in (("icecast", ""), ("icecast", "radio.example.com"),
                         ("youtube", ""),
                         ("youtube", "rtmps://a.rtmps.youtube.com/live2/key"),
                         ("facebook", "rtmps://live-api-s.facebook.com:443/rtmp/k"),
                         ("restream", "rtmp://live.restream.io/live")):
        for password in ("", "secret"):
            for picture in C.PICTURE_SOURCES:
                for mic in (True, False):
                    for titles in (True, False):
                        for audio_running in (True, False):
                            for mic_open in (True, False):
                                for screen_ready in (True, False):
                                    n += 1
                                    if n % 7:      # a seventh of the grid, still 700+
                                        continue
                                    s = {
                                        "server": server, "host": host,
                                        "mount": "/live", "name": "Blindside Radio",
                                        "password": password, "format": "mp3",
                                        "bitrate": 128, "picture": picture,
                                        "picture_file": "/tmp/nope/art.png",
                                        "camera": "MacBook Pro Camera",
                                        "video_width": 1280, "video_height": 720,
                                        "video_fps": 30, "video_bitrate": 2500,
                                    }
                                    b = Board(live_to, server, mic, titles)
                                    pf = P.check(s, b, audio_running=audio_running,
                                                 mic_open=mic_open,
                                                 screen_ready=screen_ready,
                                                 screen_reason="")
                                    out.append("check|%d|%s|%s|%s" % (
                                        n, pf.target, pf.blocked, pf.spoken()))
                                    for note in pf.notes:
                                        out.append("  note|%s|%s|%s"
                                                   % (note.level, note.fix, note.text))
                                    out.append("  summary|%s" % pf.summary())
print("\n".join(out))
