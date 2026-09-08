import Foundation

// Python's repr() for the handful of types a board field can hold, so the two
// sides print the same thing for the same value.
func rp(_ v: Any) -> String {
    if let s = v as? String { return "'" + s.replacingOccurrences(of: "'", with: "\\'") + "'" }
    if let b = v as? Bool { return b ? "True" : "False" }
    if let i = v as? Int { return String(i) }
    return String(describing: v)
}

let cases: [(String, [String: Any])] = [
    ("empty", [:]),
    ("nulls", Dictionary(uniqueKeysWithValues: [
        "video_server", "video_host", "video_key", "live_to", "picture",
        "picture_file", "picture_clock", "camera", "screen", "split_corner",
        "text_places", "colour_background", "colour_text", "colour_accent",
        "vision_provider", "vision_model", "video_width", "video_height",
        "video_fps", "video_bitrate", "framing_level",
    ].map { ($0, NSNull() as Any) })),
    ("youtube", ["video_server": "youtube", "live_to": "video",
                 "picture": "camera", "camera": "MacBook Pro Camera",
                 "video_width": 1920, "video_height": 1080, "video_fps": 60,
                 "video_bitrate": 6000, "framing_level": "everything"]),
    ("unknown-values", ["video_server": "vimeo", "live_to": "carrier pigeon",
                        "picture": "hologram", "screen": "monitor 3",
                        "split_corner": "middle", "vision_provider": "grok",
                        "framing_level": "chatty",
                        "colour_background": "puce", "colour_text": "puce",
                        "colour_accent": "puce"]),
    ("out-of-range", ["video_width": 0, "video_height": 99999,
                      "video_fps": 1000, "video_bitrate": -5]),
    ("range-edges", ["video_width": 160, "video_height": 2160,
                     "video_fps": 60, "video_bitrate": 200]),
    ("wrong-types", ["video_width": "1280", "video_height": 720.0,
                     "video_fps": [30], "video_bitrate": ["a": 1],
                     "picture_clock": "yes", "camera": 42,
                     "vision_model": 7]),
    ("migration", ["stream_server": "facebook",
                   "stream_host": "rtmps://live-api-s.facebook.com:443/rtmp",
                   "stream_mount": "/live"]),
    ("migration-not-video", ["stream_server": "icecast",
                             "stream_host": "radio.example.com"]),
    ("host-blank", ["video_server": "restream", "video_host": ""]),
    ("model-long", ["vision_model": "  " + String(repeating: "m", count: 200) + "  "]),
    ("places-full", ["text_places": [
        "top": ["kind": "station", "words": "", "file": ""],
        "corner": ["kind": "time", "words": "", "file": ""],
        "lower": ["kind": "words", "words": String(repeating: "w", count: 300), "file": ""],
        "clock": ["kind": "file", "words": "", "file": "/tmp/np.txt"]]]),
    ("places-bad", ["text_places": [
        "top": ["kind": "weather"],
        "nowhere": ["kind": "station"],
        "corner": "not a dict",
        "lower": ["kind": "words", "words": NSNull(), "file": NSNull()]]]),
    ("places-not-dict", ["text_places": ["top"]]),
    ("colours-good", ["colour_background": "navy", "colour_text": "cream",
                      "colour_accent": "gold"]),
    ("unknown-keys", ["something_from_a_later_build": ["a": 1],
                      "another": [1, 2, 3], "video_server": "restream"]),
]

let stations: [(String, [Any])] = [
    ("station-full", [[
        "stream_name": "Blindside Radio", "stream_server": "icecast",
        "stream_host": "radio.example.com", "stream_port": 8000,
        "stream_mount": "/live", "stream_password": "secret",
        "video_server": "youtube", "video_host": "rtmps://a.rtmps.youtube.com/live2",
        "live_to": "video", "picture": "camera", "camera": "A camera",
        "split_corner": "top left", "colour_background": "navy",
        "colour_text": "cream", "colour_accent": "gold",
        "video_width": 1920, "video_height": 1080, "video_fps": 60,
        "video_bitrate": 6000,
        "text_places": ["top": ["kind": "station", "words": "", "file": ""]],
    ]]),
    ("station-old", [[
        "stream_name": "Old One", "stream_server": "icecast",
        "stream_host": "old.example.com", "live_to": NSNull(),
    ]]),
    ("station-junk", [["stream_name": "Junk", "video_server": "vimeo",
                       "picture": "hologram", "video_width": 99999,
                       "text_places": "not a dict"],
                      ["no_name": true],
                      "not a dict at all"]),
]

func field(_ b: Board, _ name: String) -> Any {
    switch name {
    case "video_server": return b.videoServer
    case "video_host": return b.videoHost
    case "video_key": return b.videoKey
    case "live_to": return b.liveTo
    case "picture": return b.picture
    case "picture_file": return b.pictureFile
    case "picture_clock": return b.pictureClock
    case "camera": return b.camera
    case "screen": return b.screen
    case "split_corner": return b.splitCorner
    case "colour_background": return b.colourBackground
    case "colour_text": return b.colourText
    case "colour_accent": return b.colourAccent
    case "vision_model": return b.visionModel
    case "video_width": return b.videoWidth
    case "video_height": return b.videoHeight
    case "video_fps": return b.videoFPS
    case "video_bitrate": return b.videoBitrate
    case "framing_level": return b.framingLevel
    case "vision_provider": return b.visionProvider
    default: return ""
    }
}

let fields = ["video_server", "video_host", "video_key", "live_to", "picture",
              "picture_file", "picture_clock", "camera", "screen", "split_corner",
              "colour_background", "colour_text", "colour_accent",
              "vision_model", "video_width", "video_height", "video_fps",
              "video_bitrate", "framing_level", "vision_provider"]

func py(_ b: Bool) -> String { b ? "True" : "False" }

func pyRepr(_ v: Any) -> String {
    if v is NSNull { return "None" }
    if let s = v as? String { return "'" + s.replacingOccurrences(of: "'", with: "\\'") + "'" }
    if let b = v as? Bool { return b ? "True" : "False" }
    if let i = v as? Int { return String(i) }
    if let d = v as? [String: Any] {
        let inner = d.keys.sorted().map { "'\($0)': \(pyRepr(d[$0]!))" }
        return "{" + inner.joined(separator: ", ") + "}"
    }
    return String(describing: v)
}

var out: [String] = []
for (name, payload) in cases {
    var data: [String: Any] = ["app": "TG Drop Deck", "format": 3]
    for (k, v) in payload { data[k] = v }
    let b = Board.from(dict: data, relativeTo: nil)
    for f in fields { out.append("\(name)|\(f)|\(rp(field(b, f)))") }
    for key in ["top", "corner", "lower", "clock"] {
        let spot = b.textPlaces[key] ?? [:]
        out.append("\(name)|place.\(key)|\(rp(spot["kind"] ?? ""))|"
                 + "\(rp(spot["words"] ?? ""))|\(rp(spot["file"] ?? ""))")
    }
    let d = b.toDict()
    for f in fields { out.append("\(name)|out.\(f)|\(rp(d[f] ?? ""))") }
    for key in payload.keys.filter({ !fields.contains($0) }).sorted() {
        out.append("\(name)|kept.\(key)|\(d[key].map(pyRepr) ?? "None")")
    }
}

// ------------------------------------------------------------- the stations ---

for (name, list) in stations {
    var data: [String: Any] = ["app": "TG Drop Deck", "format": 3,
                               "stream_stations": list, "live_to": "audio",
                               "video_server": "facebook", "picture": "card",
                               "split_corner": "bottom right"]
    let b = Board.from(dict: data, relativeTo: nil)
    _ = data
    out.append("\(name)|count|\(b.streamStations.count)")
    for station in b.streamStations {
        for key in station.keys.sorted() {
            out.append("  kept|\(name)|\(key)|\(pyRepr(station[key]!))")
        }
    }
    for station in b.streamStations {
        let who = station["stream_name"] as? String ?? ""
        let got = b.loadStation(who)
        out.append("  loaded|\(name)|\(who)|\(py(got))")
        for f in fields { out.append("    after|\(name)|\(f)|\(rp(field(b, f)))") }
    }
    b.saveStation("Round Trip")
    let saved = b.streamStations.first { ($0["stream_name"] as? String) == "Round Trip" } ?? [:]
    for key in saved.keys.sorted() {
        out.append("  saved|\(name)|\(key)|\(pyRepr(saved[key]!))")
    }
}
print(out.joined(separator: "\n"))
