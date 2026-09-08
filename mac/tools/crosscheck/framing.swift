import Foundation

func py(_ b: Bool) -> String { b ? "True" : "False" }
func two(_ v: Double) -> String { String(format: "%.2f", v) }
var out: [String] = []
out.append("level|FRAMING_OFF|\(C.framingOff)")
out.append("level|FRAMING_PROBLEMS|\(C.framingProblems)")
out.append("level|FRAMING_EVERYTHING|\(C.framingEverything)")
for (key, label) in C.framingLevelLabels.sorted(by: { $0.key < $1.key }) {
    out.append("levellabel|\(key)|\(label)")
}
for previous in ["", "left of shot", "centred", "right of shot"] {
    for i in 0...100 {
        let v = Double(i) / 100.0
        out.append("bandh|\(previous)|\(two(v))|"
            + Framer.band(v, C.faceLeftEdge, C.faceRightEdge,
                          "left of shot", "centred", "right of shot",
                          previous, C.faceHysteresis))
    }
}
for previous in ["", "high in shot", "centred", "low in shot"] {
    for i in 0...100 {
        let v = Double(i) / 100.0
        out.append("bandv|\(previous)|\(two(v))|"
            + Framer.band(v, C.faceTopEdge, C.faceBottomEdge,
                          "high in shot", "centred", "low in shot",
                          previous, C.faceHysteresis))
    }
}
for previous in ["", "far away", "a good distance", "very close"] {
    for i in 0...50 {
        let v = Double(i) / 100.0
        out.append("bands|\(previous)|\(two(v))|"
            + Framer.band(v, C.faceFarBelow, C.faceCloseAbove,
                          "far away", "a good distance", "very close",
                          previous, C.faceSizeHysteresis))
    }
}
for found in [false, true] {
    for h in ["left of shot", "centred", "right of shot"] {
        for v in ["high in shot", "centred", "low in shot"] {
            for d in ["far away", "a good distance", "very close"] {
                for light in ["dark", "well lit"] {
                    let r = FramingReading(found: found, horizontal: h, vertical: v,
                                           distance: d, light: light)
                    out.append("say|\(py(found))|\(h)|\(v)|\(d)|\(light)|"
                             + "\(r.sentence())|\(r.problem())|\(py(r.good))")
                    // Python prints the key as a tuple.
                    out.append("  key|(\(py(found)), '\(h)', '\(v)', '\(d)', '\(light)')")
                }
            }
        }
    }
}

final class Ticker { var t = 0.0 }
for level in C.framingLevels {
    let ticker = Ticker()
    var said: [String] = []
    let framer = Framer(level: level, onSay: { said.append($0) }, clock: { ticker.t })
    let script: [(Double, FramingReading)] = [
        (0.0, FramingReading(found: true, horizontal: "centred", vertical: "centred", distance: "a good distance", light: "well lit")),
        (1.0, FramingReading(found: true, horizontal: "centred", vertical: "centred", distance: "a good distance", light: "well lit")),
        (2.0, FramingReading(found: false, horizontal: "", vertical: "", distance: "", light: "well lit")),
        (3.0, FramingReading(found: false, horizontal: "", vertical: "", distance: "", light: "well lit")),
        (9.0, FramingReading(found: true, horizontal: "left of shot", vertical: "centred", distance: "a good distance", light: "well lit")),
        (10.0, FramingReading(found: true, horizontal: "centred", vertical: "centred", distance: "a good distance", light: "dark")),
        (20.0, FramingReading(found: true, horizontal: "centred", vertical: "centred", distance: "a good distance", light: "well lit")),
        (21.0, FramingReading(found: true, horizontal: "centred", vertical: "centred", distance: "far away", light: "well lit")),
        (40.0, FramingReading(found: true, horizontal: "centred", vertical: "centred", distance: "a good distance", light: "well lit")),
    ]
    for (when, reading) in script {
        ticker.t = when
        framer.announce(reading)
        framer.remember(reading)
        out.append("flow|\(level)|\(String(format: "%.1f", when))|"
                 + "[" + said.map { "'\($0)'" }.joined(separator: ", ") + "]")
    }
    out.append("flowsaid|\(level)|[" + said.map { "'\($0)'" }.joined(separator: ", ") + "]")
}
print(out.joined(separator: "\n"))
