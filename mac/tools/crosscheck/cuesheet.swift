import Foundation

struct T: CueTrack {
    var cueTitle: String
    var cueArtist: String = ""
    var cueKind: String = "Song"
    var cueSeconds: Double = 0.0
    var cueTicked: Bool = true
    var cueMissing: Bool = false
}

func pyList(_ items: [String]) -> String {
    "[" + items.map { "'\($0)'" }.joined(separator: ", ") + "]"
}
func pyOpt(_ i: Int?) -> String { i.map(String.init) ?? "None" }

var out: [String] = []
out.append("onair|\(CueSheet.onAir)")
out.append("missing|\(CueSheet.missingFile)")
out.append("end|\(CueSheet.endRow)")
out.append("empty|\(CueSheet.emptyRow)")

for value in [0, -1, 1, 59, 60, 61, 119, 120, 599, 3600, 3661] {
    out.append("length|\(value)|\(CueSheet.saidLength(Double(value)))")
}

let tracks: [CueTrack] = [
    T(cueTitle: "Opening Theme", cueArtist: "The Band", cueKind: "Song", cueSeconds: 185.0),
    T(cueTitle: "Station Ident", cueArtist: "", cueKind: "Drop", cueSeconds: 9.0),
    T(cueTitle: "Second Song", cueArtist: "Another Act", cueKind: "Song", cueSeconds: 212.4),
    T(cueTitle: "Not Ticked", cueArtist: "Nobody", cueKind: "Song", cueSeconds: 100.0, cueTicked: false),
    T(cueTitle: "Gone Missing", cueArtist: "A Ghost", cueKind: "Song", cueSeconds: 150.0, cueMissing: true),
    T(cueTitle: "Last One", cueArtist: "", cueKind: "Song", cueSeconds: 60.0),
]
let empty: [CueTrack] = []
let noneTicked: [CueTrack] = [
    T(cueTitle: "Only One", cueArtist: "X", cueKind: "Song", cueSeconds: 30.0, cueTicked: false)]
let allMissing: [CueTrack] = [
    T(cueTitle: "A", cueArtist: "", cueKind: "Song", cueSeconds: 10.0, cueMissing: true),
    T(cueTitle: "B", cueArtist: "", cueKind: "Song", cueSeconds: 20.0, cueMissing: true)]

let sets: [(String, [CueTrack])] = [
    ("full", tracks), ("empty", empty), ("none-ticked", noneTicked),
    ("all-missing", allMissing),
]

for (label, set) in sets {
    var playings: [Int?] = [nil]
    playings.append(contentsOf: (0..<set.count).map { Optional($0) })
    for playing in playings {
        for played in [0.0, 5.0, 9.99, 10.0, 10.01, 30.0] {
            let rows = CueSheet.build(tracks: set, playingIndex: playing, playedFor: played)
            let key = "\(label)|\(pyOpt(playing))|\(String(format: "%.2f", played))"
            out.append("rows|\(key)|\(rows.count)")
            for (i, row) in rows.enumerated() {
                out.append("  row|\(key)|\(i)|\(pyList(row.cells))")
                out.append("  idx|\(key)|\(i)|\(pyOpt(row.index))")
            }
            out.append("summary|\(key)|\(CueSheet.summary(tracks: set, rows: rows))")
            out.append("next|\(key)|\(CueSheet.nextFew(rows))")
            out.append("next1|\(key)|\(CueSheet.nextFew(rows, howMany: 1))")
            out.append("next9|\(key)|\(CueSheet.nextFew(rows, howMany: 9))")
        }
    }
}

for grace in [0.0, 1.0, 10.0, 60.0] {
    let rows = CueSheet.build(tracks: tracks, playingIndex: 1, playedFor: 5.0, grace: grace)
    out.append("grace|\(String(format: "%.1f", grace))|\(pyList(rows.map(\.title)))")
}

let shown = CueSheet.build(tracks: tracks, playingIndex: nil)
let wanted = CueSheet.build(tracks: tracks, playingIndex: 1, playedFor: 30.0)
var focuses: [String?] = [nil]
focuses.append(contentsOf: shown.map { Optional($0.title) })
focuses.append("Nothing By This Name")
focuses.append(CueSheet.endRow)
for focused in focuses {
    let got = CueSheet.applyChanges(shown: shown, wanted: wanted, focusedTitle: focused)
    out.append("apply|\(focused ?? "None")|\(pyList(got.map(\.title)))")
}

var got = CueSheet.applyChanges(shown: wanted, wanted: shown, focusedTitle: "Opening Theme")
out.append("apply-back|\(pyList(got.map(\.title)))")
got = CueSheet.applyChanges(shown: [], wanted: wanted, focusedTitle: "Opening Theme")
out.append("apply-fresh|\(pyList(got.map(\.title)))")
print(out.joined(separator: "\n"))
