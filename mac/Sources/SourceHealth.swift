// Are the extra sources really on the air, or only set up to be?
//
// **The one thing a presenter cannot check for themselves.** A source that is
// set up, started, and delivering silence sounds exactly like one that is
// working, from where the presenter is sitting, because they go on hearing the
// program in their own ears either way. It is the same shape of fault as a
// microphone left off the air and it costs the same thing: a show missing a
// voice, with nobody in the room able to tell.
//
// It watches what is ARRIVING from each capture rather than reading the ring
// the broadcast reads. Reading that ring would take the audio out of it, so a
// check on a live show would damage the show it was checking.

import Foundation
import AppKit

enum SourceHealth {

    struct Finding {
        let name: String
        let good: Bool
        let line: String
    }

    /// How long to listen. Long enough for a screen reader to say something,
    /// short enough that nobody walks away from it.
    static let window: TimeInterval = 6

    static func look(at group: SourceGroup) -> [BaseSource] {
        let watched = group.all.compactMap { $0 as? BaseSource }
        for source in watched { source.resetMeter() }
        return watched
    }

    static func read(_ watched: [BaseSource], running: [String: String]) -> [Finding] {
        watched.map { source in
            let c = source.config
            let where_ = c.isProcess
                ? (c.bundleID.map { running[$0] ?? $0 } ?? "no program chosen")
                : (c.deviceUID.map { AudioDevices.name(forUID: $0) ?? $0 }
                   ?? "no device chosen")
            let db = source.peakIn > 0 ? 20 * log10(Double(source.peakIn)) : -200

            if !(c.onAir || c.monitor) {
                return Finding(name: c.name, good: true,
                               line: "\(c.name), \(where_): switched off, on purpose.")
            }
            if !source.isRunning {
                return Finding(name: c.name, good: false,
                    line: "\(c.name), \(where_): NOT on the air. "
                        + (source.lastError ?? "it would not open") + ".")
            }
            if c.muted {
                return Finding(name: c.name, good: false,
                    line: "\(c.name), \(where_): NOT on the air, it is muted.")
            }
            if !c.onAir {
                return Finding(name: c.name, good: true,
                    line: "\(c.name), \(where_): you hear it, and it is not going out.")
            }
            if source.framesIn == 0 {
                return Finding(name: c.name, good: false,
                    line: "\(c.name), \(where_): running, but nothing at all is coming "
                        + "from it. If that is a program, it has to be playing something.")
            }
            if source.peakIn <= 0.0001 {
                return Finding(name: c.name, good: false,
                    line: "\(c.name), \(where_): the capture is working and what is "
                        + "arriving is silence. Play something in it, or check it is not "
                        + "muted at its own end.")
            }
            // Mono where stereo was expected is invisible on a level meter,
            // so it is said. A program capture is always stereo now; a device
            // folded on purpose is not a fault and does not read as one.
            let sound = source.sawStereo
                ? "in stereo"
                : (c.isProcess ? "the same in both ears, which for a program is "
                               + "either a mono program or nothing playing in stereo yet"
                   : "the same in both ears, which is what \(c.channel.spoken) does")
            return Finding(name: c.name, good: true,
                line: String(format: "%@, %@: on the air, %.0f decibels, %@.",
                             c.name, where_, db, sound))
        }
    }

    /// The whole thing as one piece of prose, for reading aloud.
    static func report(_ findings: [Finding], micOnAir: Bool, micOpen: Bool) -> String {
        var out: [String] = []
        out.append(micOpen
            ? (micOnAir ? "Your microphone is open and going out."
                        : "Your microphone is open, and it is NOT going out.")
            : "Your microphone is not open.")
        if findings.isEmpty {
            out.append("There are no other sources. Option Shift S adds one.")
        } else {
            let bad = findings.filter { !$0.good }.count
            out.append(bad == 0
                ? "All \(findings.count) of your other sources are as they should be."
                : "\(bad) of your \(findings.count) other sources "
                  + "\(bad == 1 ? "needs" : "need") attention.")
            out.append(contentsOf: findings.map(\.line))
        }
        return out.joined(separator: "\n")
    }
}

// ------------------------------------------------------------- the dialog ---

/// Help, Check my audio sources.
///
/// It listens for a few seconds and then says, in words, whether each source
/// is actually putting sound on the air. Safe to run mid broadcast: it reads
/// the meter on what is arriving and never touches the audio itself.
final class SourceHealthPanel: NSObject {

    private let group: SourceGroup
    private let speaker: Speaker
    private let micOnAir: Bool
    private let micOpen: Bool
    private var results: NSTextView!
    private var busy = false

    init(group: SourceGroup, speaker: Speaker, micOnAir: Bool, micOpen: Bool) {
        self.group = group
        self.speaker = speaker
        self.micOnAir = micOnAir
        self.micOpen = micOpen
        super.init()
    }

    /// `parent` is not used: an NSAlert run as a sheet cannot be run again in
    /// a loop, and this panel is meant to be listened with more than once.
    func run(over parent: NSWindow?) {
        _ = parent
        let alert = NSAlert()
        alert.messageText = "Check my audio sources"
        alert.informativeText =
            "This listens for \(Int(SourceHealth.window)) seconds and says whether each "
            + "source is really putting sound on the air, which is the one thing you "
            + "cannot hear for yourself. Make each program talk or play while it listens. "
            + "It is safe to do this on air."
        alert.addButton(withTitle: "Listen")
        alert.addButton(withTitle: "Close")

        let width: CGFloat = 620
        let (scroll, view) = readOnlyText(
            "Nothing has been listened to yet. Choose Listen, then make each program "
            + "play something.",
            label: "What each source is doing", width: width, height: 240)
        results = view
        alert.accessoryView = scroll
        alert.window.initialFirstResponder = results
        alert.buttons.first?.setAccessibilityLabel("Listen")
        alert.buttons.last?.setAccessibilityLabel("Close")

        while true {
            // The alert closes on any button, so it is run again. Everything it
            // has found is held on this object, so nothing is lost. The same
            // shape as Check my shot, and PanelKeys rather than runModal so
            // Escape closes it and the text view keeps its own keys.
            let answer = PanelKeys.run(alert)
            guard answer == .alertFirstButtonReturn else { break }
            listen()
        }
    }

    private func listen() {
        guard !busy else { return }
        busy = true
        speaker.announceState("Listening for \(Int(SourceHealth.window)) seconds. "
                            + "Make each program play something now.")
        let watched = SourceHealth.look(at: group)
        var running: [String: String] = [:]
        for app in NSWorkspace.shared.runningApplications {
            guard let id = app.bundleIdentifier else { continue }
            running[id] = app.localizedName ?? id
        }
        // The run loop has to keep turning while it listens, so the app stays
        // alive and the announcement is actually spoken. Sleeping the thread
        // here would freeze the whole app for six seconds.
        let until = Date().addingTimeInterval(SourceHealth.window)
        while Date() < until {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
        }
        let findings = SourceHealth.read(watched, running: running)
        let text = SourceHealth.report(findings, micOnAir: micOnAir, micOpen: micOpen)
        results.string = text
        results.setSelectedRange(NSRange(location: 0, length: 0))
        speaker.announceAnswer(text)
        busy = false
    }
}
