import Foundation

var out: [String] = []
func tup(_ r: (left: Int, top: Int, right: Int, bottom: Int)) -> String {
    "(\(r.left), \(r.top), \(r.right), \(r.bottom))"
}
for spot in Overlays.places {
    out.append("place|\(spot.key)|\(spot.label)|"
             + "\(spot.align == .right ? "right" : "left")|\(spot.describeWhere())")
    for size in [(1280, 720), (1920, 1080), (854, 480), (640, 360), (3840, 2160)] {
        out.append("  rect|\(spot.key)|\(size.0)|\(size.1)|"
                 + "\(tup(spot.rect(size.0, size.1)))|\(spot.textSize(size.1))")
    }
}
for key in ["top", "corner", "lower", "clock", "nowhere"] {
    out.append("label|\(key)|\(Overlays.placeLabel(key))")
}

// The clock is pinned so both copies see the same minute.
let pinned: Date = {
    var c = DateComponents()
    c.year = 2026; c.month = 9; c.day = 8; c.hour = 9; c.minute = 41
    return Calendar(identifier: .gregorian).date(from: c)!
}()

let cases: [(String, OverlaySettings)] = [
    ("nothing", OverlaySettings()),
    ("station-only", { var s = OverlaySettings()
        s.places = ["top": ["kind": "station"]]; s.name = "Blindside Radio"; return s }()),
    ("station-no-name", { var s = OverlaySettings()
        s.places = ["top": ["kind": "station"]]; return s }()),
    ("two", { var s = OverlaySettings()
        s.places = ["top": ["kind": "station"], "clock": ["kind": "time"]]
        s.name = "Tony's Tunes"; return s }()),
    ("three", { var s = OverlaySettings()
        s.places = ["top": ["kind": "station"], "clock": ["kind": "time"],
                    "lower": ["kind": "playing"]]
        s.name = "Tony's Tunes"; return s }()),
    ("all-four", { var s = OverlaySettings()
        s.places = ["top": ["kind": "station"],
                    "corner": ["kind": "words", "words": "LIVE"],
                    "lower": ["kind": "playing"], "clock": ["kind": "time"]]
        s.name = "Tony's Tunes"; return s }()),
    ("playing-empty", { var s = OverlaySettings()
        s.places = ["lower": ["kind": "playing"]]; return s }()),
    ("words-empty", { var s = OverlaySettings()
        s.places = ["corner": ["kind": "words"]]; return s }()),
    ("file-missing", { var s = OverlaySettings()
        s.places = ["lower": ["kind": "file", "file": "/tmp/nope-xyz.txt"]]; return s }()),
    ("stream-name", { var s = OverlaySettings()
        s.places = ["top": ["kind": "station"]]; s.streamName = "Fallback FM"; return s }()),
    ("unknown-kind", { var s = OverlaySettings()
        s.places = ["top": ["kind": "weather"]]; return s }()),
]
for (name, settings) in cases {
    for title in ["", "Fleetwood Mac - Dreams"] {
        let ov = Overlay(settings: settings)
        ov.clock = { pinned }
        ov.setTitle(title)
        out.append("describe|\(name)|'\(title)'|\(ov.describe())")
        out.append("  anything|\(name)|\(ov.anythingOn() ? "True" : "False")")
        for key in C.placesOrder {
            out.append("  kind|\(name)|\(key)|\(ov.kindOf(key))")
        }
    }
}
print(out.joined(separator: "\n"))
