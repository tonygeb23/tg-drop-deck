// A .cue track list written beside a recording, as the show goes out.
//
// A deliberate mirror of dropdeck/cuefile.py, byte for byte on the same input,
// which `mac/tools/cross_check.py` proves.
//
// Tyler McClain, 10 September 2026, clarifying a request after 3.7.0 had
// already shipped a live cue sheet window, which turned out not to be what he
// meant:
//
//     "i'm talking about adding the ability to let it write a .cue file with
//     the title, artist, and when it was played, like 0:00 or something. where
//     people can have a .cue sheet right in the recordings folder with the same
//     file name, like if they want to post it to mixcloud or something like
//     that."
//
// So: `Drop Deck Stream 004.mp3` gets `Drop Deck Stream 004.cue` beside it,
// holding every track that went out and the moment it started, measured from
// the top of the recording. Upload the pair to Mixcloud, or open the cue in
// anything that reads one, and the track list is already done.
//
// **This is a different feature from `CueSheet.swift`.** That one is the window
// on Command+Shift+C showing what is coming UP. This one is the file recording
// what has already GONE OUT. They share a word and nothing else.
//
// ## The clock, which is the only hard part
//
// **Timestamps come from the recording's own sample count, never from a wall
// clock.** `Recorder.elapsed` and `VideoRecorder.audioSeconds` are both frames
// written divided by the sample rate, for exactly this reason: if the machine
// stalls for a moment, the file is shorter than the wall clock says, and a
// track list timed against the wall would drift away from the audio it
// describes. Ask the recorder where it has got to, and the mark lands where
// the music really is.
//
// ## Written as it goes, not at the end
//
// A three hour show that crashes at hour two should still have a track list
// for the two hours it got. Every track appends and flushes, so the file on
// disk is always complete up to the last thing that played. That is the same
// reasoning the recording itself uses.
//
// ## The format, and the one bit everybody gets wrong
//
// `INDEX 01 mm:ss:ff`, and **ff is frames at seventy five per second**, not
// hundredths and not milliseconds. It is a CD sector, which is what the format
// was invented for. Half a second is 37.5 frames, so it lands on `38`, and
// never on the `50` that hundredths would give.

import Foundation

enum Cue {

    /// What a .cue may call the audio it points at. Anything not in here is
    /// written as WAVE, which every reader accepts and none of them chokes on.
    /// The Mac records m4a and flac as well, and neither has a keyword in the
    /// format: WAVE is what they get, deliberately, and it parses everywhere.
    static let fileTypes: [String: String] = [
        "wav": "WAVE", "mp3": "MP3", "aiff": "AIFF", "aif": "AIFF",
    ]
    static let defaultFileType = "WAVE"

    /// Frames per second in a .cue timestamp. A CD sector, not a video frame.
    static let framesPerSecond = 75

    static let fileExtension = "cue"

    /// What to call this audio file in a FILE line.
    static func fileType(_ path: String) -> String {
        let ext = (path as NSString).pathExtension.lowercased()
        return fileTypes[ext] ?? defaultFileType
    }

    /// Seconds to mm:ss:ff, where ff is seventy fifths of a second.
    ///
    /// Minutes are not wrapped at sixty. A two hour show's last track is at
    /// `119:58:00`, which is what the format means and what readers expect; a
    /// track list that restarted its clock every hour would be unusable.
    static func timestamp(_ seconds: Double) -> String {
        let value = max(0.0, seconds.isFinite ? seconds : 0.0)
        var whole = Int(value)
        // `.toNearestOrEven`, not the default `.toNearestOrAwayFromZero`,
        // because Python's `round` is banker's rounding and this has to agree
        // with `dropdeck/cuefile.py` to the byte. It lands on exactly half a
        // frame more often than anyone would guess: every 150th of a second
        // does it, so a track cued at 0.0867 seconds came out one frame later
        // on the Mac than on Windows. Found by cross_check.py on its first run.
        var frames = Int(((value - Double(whole)) * Double(framesPerSecond))
            .rounded(.toNearestOrEven))
        if frames >= framesPerSecond {      // rounding up on the boundary
            frames = 0
            whole += 1
        }
        let minutes = whole / 60
        let secs = whole % 60
        return String(format: "%02d:%02d:%02d", minutes, secs, frames)
    }

    /// A .cue string, safely.
    ///
    /// The format has no escape for a double quote, so one is turned into a
    /// single. A title with a quote in it is rare and a file that will not
    /// parse is not.
    static func quoted(_ text: String) -> String {
        let cleaned = text
            .replacingOccurrences(of: "\"", with: "'")
            .replacingOccurrences(of: "\r", with: " ")
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespaces)
        return "\"\(cleaned)\""
    }

    /// One track that went out.
    struct Entry: Equatable {
        let title: String
        let performer: String
        let seconds: Double
    }

    /// The whole file, as text. Pure, so every rule above is testable.
    static func render(audioName: String, entries: [Entry]) -> String {
        var lines = ["FILE \(quoted(audioName)) \(fileType(audioName))"]
        for (index, entry) in entries.enumerated() {
            lines.append(String(format: "  TRACK %02d AUDIO", index + 1))
            lines.append("    TITLE \(quoted(entry.title.isEmpty ? "Untitled" : entry.title))")
            if !entry.performer.isEmpty {
                lines.append("    PERFORMER \(quoted(entry.performer))")
            }
            lines.append("    INDEX 01 \(timestamp(entry.seconds))")
        }
        return lines.joined(separator: "\n") + "\n"
    }

    /// Where the .cue goes: beside the audio, same stem.
    static func path(for audioPath: String) -> String? {
        guard !audioPath.isEmpty else { return nil }
        return (audioPath as NSString).deletingPathExtension + "." + fileExtension
    }
}

/// The track list for one recording, kept up to date on disk.
///
/// `audioPath` is the recording it describes. Nothing is written until the
/// first track is added, so a recording with no running order behind it does
/// not litter the folder with an empty file.
final class CueFile {

    let audioPath: String
    let path: String?
    /// Plain properties, exactly as the Windows class has them, so a check can
    /// set up a state without going through the disk. Nothing in the app
    /// writes either of these: the recorder only ever calls `add`.
    var entries: [Cue.Entry] = []
    var lastError: String?
    private let lock = NSLock()

    init(audioPath: String) {
        self.audioPath = audioPath
        self.path = Cue.path(for: audioPath)
    }

    /// One track went out. True if the file was written.
    ///
    /// Never throws. A track list that cannot be written is worth saying
    /// something about later, and is never worth taking a show down for.
    @discardableResult
    func add(title: String, performer: String = "", seconds: Double = 0.0) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        // The same track twice at the same moment is a double press, not two
        // plays. The timestamp is what tells them apart.
        let entry = Cue.Entry(title: title, performer: performer,
                              seconds: max(0.0, seconds.isFinite ? seconds : 0.0))
        if entries.last == entry { return false }
        entries.append(entry)
        return write()
    }

    private func write() -> Bool {
        guard let path = path else { return false }
        let name = (audioPath as NSString).lastPathComponent
        let text = Cue.render(audioName: name, entries: entries)
        do {
            // Written and flushed every time, so the file on disk is always
            // complete up to the last track. A show that crashes at hour two
            // keeps its first two hours of track list. `atomically` is what
            // supplies the flush: it writes a temporary file and renames it,
            // so a reader never sees a half written list either.
            try text.write(toFile: path, atomically: true, encoding: .utf8)
            lastError = nil
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    /// One line about what was written, for the end of a recording.
    func describe() -> String {
        lock.lock()
        defer { lock.unlock() }
        if entries.isEmpty { return "" }
        if let error = lastError {
            return "The track list could not be written. \(error)"
        }
        return "\(entries.count) \(entries.count == 1 ? "track" : "tracks") in the track list beside it"
    }
}
