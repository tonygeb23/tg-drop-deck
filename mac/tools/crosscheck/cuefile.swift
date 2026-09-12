import Foundation

var out: [String] = []

out.append("frames|\(Cue.framesPerSecond)")
out.append("ext|.\(Cue.fileExtension)")
out.append("deftype|\(Cue.defaultFileType)")

let names = ["show.wav", "show.mp3", "show.aiff", "show.aif", "show.m4a",
             "show.flac", "show.WAV", "show.Mp3", "show", "",
             "Drop Deck Stream 004.mp3", "/a/b c/Drop Deck Stream 004.wav"]
for (i, name) in names.enumerated() {
    out.append("type|\(i)|\(Cue.fileType(name))")
    // Python prints None for the empty name; Swift returns nil for it.
    out.append("path|\(i)|\(Cue.path(for: name) ?? "None")")
}

let stamps = [0.0, -1.0, 0.001, 0.0066, 0.0067, 0.5, 0.99, 0.993, 0.9934,
              1.0, 1.5, 59.999, 60.0, 60.5, 119.5, 599.99, 3599.0, 3600.0,
              3661.5, 7198.6666, 7199.9999]
for (i, value) in stamps.enumerated() {
    out.append("stamp|\(i)|\(Cue.timestamp(value))")
}
for i in 0..<200 {
    out.append("stampstep|\(i)|\(Cue.timestamp(Double(i) / 150.0))")
}

let texts = ["", "  padded  ", "He said \"hello\"", "line\nbreak",
             "carriage\rreturn", "both\r\nof them", "Ünïcödé",
             "a'b", "\"", "\"\"quoted\"\""]
for (i, text) in texts.enumerated() {
    out.append("quote|\(i)|\(Cue.quoted(text))")
}

let entries = [
    Cue.Entry(title: "First Track", performer: "An Artist", seconds: 0.0),
    Cue.Entry(title: "", performer: "", seconds: 12.5),
    Cue.Entry(title: "No Artist", performer: "", seconds: 61.0),
    Cue.Entry(title: "A \"quoted\" title", performer: "Somebody", seconds: 3661.4934),
    Cue.Entry(title: "Ünïcödé", performer: "Ärtïst", seconds: 7199.9999),
]
out.append("render|<<<")
// Python's print adds a newline after a string that already ends in one, so
// the block appears with a blank line before the closing marker. The Swift
// side has to do the same or the diff is one newline wide.
out.append(Cue.render(audioName: "Drop Deck Stream 004.mp3", entries: entries))
out.append(">>>")
out.append("render-empty|<<<")
out.append(Cue.render(audioName: "show.flac", entries: []))
out.append(">>>")

let cue = CueFile(audioPath: "/nowhere/Drop Deck Stream 004.mp3")
out.append("describe-none|\(cue.describe())")
cue.entries.append(Cue.Entry(title: "One", performer: "", seconds: 0.0))
out.append("describe-one|\(cue.describe())")
cue.entries.append(Cue.Entry(title: "Two", performer: "", seconds: 10.0))
out.append("describe-two|\(cue.describe())")
cue.lastError = "Permission denied"
out.append("describe-bad|\(cue.describe())")
print(out.joined(separator: "\n"))
