import Foundation

func py(_ b: Bool) -> String { b ? "True" : "False" }
var out: [String] = []

// ---------------------------------------------------------------- labels ---
for key in ["icecast", "shoutcast", "youtube", "facebook", "restream", "rtmp",
            "nonsense", ""] {
    out.append("label|\(key)|\(StreamServers.serverLabel(key))")
    out.append("isrtmp|\(key)|\(py(StreamServers.isRTMP(key)))")
}
for url in ["rtmps://a.rtmps.youtube.com/live2/abcd-key",
            "rtmp://live.restream.io/live", "http://radio.example.com:8000",
            "not a url", "", "rtmps://live-api-s.facebook.com:443/rtmp/FB-1-key"] {
    out.append("host|\(url)|\(StreamServers.hostLabel(url))")
}

// -------------------------------------------------------- bitrate advice ---
for server in ["facebook", "youtube", "restream", "rtmp"] {
    for size in [(1920, 1080, 60), (1920, 1080, 30), (1280, 720, 60),
                 (1280, 720, 30), (854, 480, 30), (640, 360, 30), (1024, 576, 25)] {
        for vb in [400, 500, 1500, 2500, 4000, 6000, 12000] {
            for ab in [128, 320] {
                let got = StreamServers.bitrateAdvice(
                    server: server, width: size.0, height: size.1, fps: size.2,
                    videoKbps: vb, audioKbps: ab)
                out.append("advice|\(server)|\(size.0)|\(size.1)|\(size.2)|\(vb)|\(ab)|\(got)")
            }
        }
    }
}

// ------------------------------------------------------- where it goes ---
for video in [false, true] {
    for name in ["", "Blindside Radio"] {
        for server in ["icecast", "shoutcast", "youtube", "facebook", "restream", "rtmp"] {
            for host in ["", "radio.example.com", "rtmps://a.rtmps.youtube.com/live2/k"] {
                var s = PreflightSettings()
                s.server = server; s.host = host; s.name = name; s.mount = "/live"
                out.append("goes|\(py(video))|\(name)|\(server)|\(host)|"
                         + Preflighter.whereItGoes(s, video: video))
            }
        }
    }
}

// --------------------------------------------------------- picture words ---
for kind in C.pictureSources {
    for cam in ["", "MacBook Pro Camera"] {
        for pf in ["", "/tmp/nope/art.png"] {
            for name in ["", "Tony's Tunes"] {
                var s = PreflightSettings()
                s.picture = kind; s.camera = cam; s.pictureFile = pf
                s.name = name; s.streamName = ""
                out.append("pic|\(kind)|\(cam)|\(pf)|\(name)|\(Preflighter.pictureWords(s))")
            }
        }
    }
}

// ----------------------------------------------------- going live warning ---
for liveTo in C.liveTo {
    for vs in ["youtube", "facebook", "restream", "rtmp", ""] {
        var b = PreflightBoard()
        b.liveTo = liveTo; b.videoServer = vs
        out.append("warn|\(liveTo)|\(vs)|\(Preflighter.goingLiveWarning(b))")
    }
}

// --------------------------------------------------------- the whole check ---
var n = 0
for liveTo in C.liveTo {
    for pair in [("icecast", ""), ("icecast", "radio.example.com"),
                 ("youtube", ""),
                 ("youtube", "rtmps://a.rtmps.youtube.com/live2/key"),
                 ("facebook", "rtmps://live-api-s.facebook.com:443/rtmp/k"),
                 ("restream", "rtmp://live.restream.io/live")] {
        for password in ["", "secret"] {
            for picture in C.pictureSources {
                for mic in [true, false] {
                    for titles in [true, false] {
                        for audioRunning in [true, false] {
                            for micOpen in [true, false] {
                                for screenReady in [true, false] {
                                    n += 1
                                    if n % 7 != 0 { continue }
                                    var s = PreflightSettings()
                                    s.server = pair.0; s.host = pair.1
                                    s.mount = "/live"; s.name = "Blindside Radio"
                                    s.password = password; s.format = "mp3"
                                    s.bitrate = 128; s.picture = picture
                                    s.pictureFile = "/tmp/nope/art.png"
                                    s.camera = "MacBook Pro Camera"
                                    s.videoWidth = 1280; s.videoHeight = 720
                                    s.videoFPS = 30; s.videoBitrate = 2500
                                    var b = PreflightBoard()
                                    b.liveTo = liveTo; b.videoServer = pair.0
                                    b.streamMic = mic; b.streamTitles = titles
                                    let pf = Preflighter.check(
                                        settings: s, board: b,
                                        audioRunning: audioRunning, micOpen: micOpen,
                                        screenReady: screenReady, screenReason: "")
                                    out.append("check|\(n)|\(pf.target)|\(py(pf.blocked))|\(pf.spoken())")
                                    for note in pf.notes {
                                        out.append("  note|\(note.level.rawValue)|\(note.fix)|\(note.text)")
                                    }
                                    out.append("  summary|\(pf.summary())")
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
print(out.joined(separator: "\n"))
