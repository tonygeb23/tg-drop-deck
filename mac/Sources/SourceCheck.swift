// Are the extra sources really on the air, or only configured to be?
//
// **The one thing a presenter cannot check for themselves.** A source that is
// set up, started, and delivering silence sounds exactly like a source that is
// working, from where the presenter is sitting, because they go on hearing the
// program itself either way. It is the same shape of fault as a microphone
// left off the air, and it costs the same thing: a show that is missing
// something and nobody in the room can tell.
//
// Run it with `--check-sources`. It opens every source the board has, listens
// for a couple of seconds, and says whether any sound actually arrived.

import Foundation
import AVFoundation
import AppKit

enum SourceCheck {

    static func run(seconds: Double = 2.0) -> Int32 {
        print("\(C.appName) \(C.appVersion), checking the audio sources")
        print("")

        let board = Board.load(Board.defaultBoardPath()) ?? Board()
        let configs = board.sources
        if configs.isEmpty {
            print("This board has no extra sources. Option Shift S adds one.")
            return 0
        }

        // What macOS has to allow. A process tap is covered by the same
        // permission as screen recording, which is not obvious from its name.
        print("Screen and System Audio Recording: "
            + "\(Permissions.state(.screen).said)")
        print("  a tap on another program's audio is covered by that one, "
            + "whatever its name suggests")
        print("")

        // Asked of the system directly. The shim the app normally uses is
        // wired up by the app delegate, which does not run in this mode.
        var running: [(bundleID: String, name: String)] = []
        for app in NSWorkspace.shared.runningApplications {
            guard let id = app.bundleIdentifier else { continue }
            running.append((bundleID: id, name: app.localizedName ?? id))
        }
        var failed = 0

        let group = SourceGroup()
        group.replace(with: configs, outputRate: C.defaultSampleRate)
        // Let the rings fill.
        Thread.sleep(forTimeInterval: 2.5)

        let frames = 4096
        let buffer = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { buffer.deallocate() }

        // Every source is listened to at the same time, over one window, so
        // one pass of playing something covers all of them. Reading them one
        // after another asks somebody to keep making a noise for as long as
        // the list is, and quietly rewards the source that happened to be
        // first.
        print("listening to all of them for \(Int(seconds)) seconds. "
            + "Play something in each program now.")
        print("")
        // A second, completely independent tap on each of the same programs.
        // It answers the one question the app's own numbers cannot: when a
        // source reads silent, is the program quiet or is the app losing it?
        // Two answers that disagree is a bug here; two that agree is a program
        // that is not making a noise.
        var reference: [String: AnyObject] = [:]
        if #available(macOS 14.2, *) {
            for source in group.all where source.config.isProcess {
                guard let bundle = source.config.bundleID, !bundle.isEmpty else { continue }
                if let tap = ReferenceTap(bundle: bundle) { reference[source.config.id] = tap }
            }
        }
        defer {
            if #available(macOS 14.2, *) {
                for tap in reference.values { (tap as? ReferenceTap)?.close() }
            }
        }

        var peaks: [String: Float] = [:]
        let until = Date().addingTimeInterval(seconds)
        // At the pace the audio actually arrives, NOT as fast as the loop can
        // go. Pulling faster than the source fills empties the ring, and a
        // program that speaks in bursts, which is exactly what a screen reader
        // does, then reads as silent every time. That is the checker inventing
        // the very fault it is meant to find.
        let step = Double(frames) / C.defaultSampleRate
        var next = Date()
        while Date() < until {
            for source in group.all {
                source.readAir(frames: frames, into: buffer)
                var peak = peaks[source.config.id] ?? 0
                for i in 0..<(frames * 2) { peak = max(peak, abs(buffer[i])) }
                peaks[source.config.id] = peak
            }
            next = next.addingTimeInterval(step)
            let wait = next.timeIntervalSinceNow
            if wait > 0 { Thread.sleep(forTimeInterval: wait) } else { next = Date() }
        }

        for source in group.all {
            let c = source.config
            print("\(c.name)")
            print("   what it is        : \(c.isProcess ? "a program" : "a device")")
            if c.isProcess {
                let bundle = c.bundleID ?? "not chosen"
                print("   the program       : \(bundle)")
                let match = running.first { $0.bundleID == bundle }
                print("   is it running now : \(match != nil ? "yes, \(match!.name)" : "NO")")
                // The fault that put VoiceOver's audio under a source called
                // "logic pro": two sources pointing at one program.
                let same = configs.filter { $0.bundleID == c.bundleID }
                if same.count > 1 {
                    print("   WARNING           : \(same.count) sources point at this same "
                        + "program (\(same.map { $0.name }.joined(separator: ", ")))")
                    failed += 1
                }
            } else {
                print("   the device        : \(c.deviceUID ?? "not chosen")")
            }
            print("   on air            : \(c.onAir)")
            print("   muted             : \(c.muted)")
            print("   started           : \(source.isRunning)")
            if let error = source.lastError {
                print("   it said           : \(error)")
            }

            // The half that matters: did any sound actually arrive?
            let peak = peaks[c.id] ?? 0
            let db = peak > 0 ? 20 * log10(Double(peak)) : -200
            var secondOpinion: Float? = nil
            if #available(macOS 14.2, *), let tap = reference[c.id] as? ReferenceTap {
                let refDB = tap.peak > 0 ? 20 * log10(Double(tap.peak)) : -200
                print(String(format: "   a separate tap    : %d callbacks, loudest %.4f (%.1f dB)",
                             tap.calls, tap.peak, refDB))
                secondOpinion = tap.peak
            }
            if let base = source as? BaseSource {
                let inDB = base.peakIn > 0 ? 20 * log10(Double(base.peakIn)) : -200
                print(String(format: "   arriving from it  : %d frames, loudest %.4f (%.1f dB)",
                             base.framesIn, base.peakIn, inDB))
            }
            print(String(format: "   sound on the air  : peak %.4f (%.1f dB)",
                         peak, db))
            if !source.isRunning {
                print("   VERDICT           : NOT on the air, it did not start")
                failed += 1
            } else if !c.onAir {
                print("   VERDICT           : NOT on the air, its On air box is off")
                failed += 1
            } else if c.muted {
                print("   VERDICT           : NOT on the air, it is muted")
                failed += 1
            } else if peak <= 0.0001 {
                // Which kind of silence this is, said plainly, because the two
                // are nothing like each other. One is a program with its
                // transport stopped and there is nothing to fix. The other is
                // this app dropping audio it was handed, and that is a bug.
                if let second = secondOpinion, second > 0.0001 {
                    print("   VERDICT           : BROKEN. A separate tap on the same "
                        + "program heard it, and this source did not, so the sound is "
                        + "being lost on the way here. Please report this.")
                } else if c.isProcess {
                    print("   VERDICT           : no sound, because that program is not "
                        + "playing anything. A separate tap heard the same silence, so "
                        + "the capture itself is fine. Play something in it and run "
                        + "this again.")
                } else {
                    print("   VERDICT           : running, but SILENT. Check the device "
                        + "is the right one and something is going into it.")
                }
                failed += 1
            } else {
                print("   VERDICT           : on the air and making sound")
            }
            print("")
        }

        group.stopAll()
        if failed > 0 {
            print("\(failed) thing\(failed == 1 ? "" : "s") to put right.")
            return 1
        }
        print("Every source is on the air and making sound.")
        return 0
    }
}


// ------------------------------------------- a second opinion on one program ---

/// A tap on a program built from scratch, next to the app's own one.
///
/// The whole value is that it shares nothing with the source it is checking
/// except the bundle id. If this one hears a program and the source does not,
/// the fault is in the app; if neither hears it, the program is quiet. Without
/// it "SILENT" means both of those at once and a person is left guessing.
@available(macOS 14.2, *)
final class ReferenceTap {
    private var tap: AudioObjectID = 0
    private var aggregate: AudioDeviceID = 0
    private var proc: AudioDeviceIOProcID?
    private(set) var peak: Float = 0
    private(set) var calls = 0

    init?(bundle: String) {
        let ids: [AudioObjectID] = (AudioProcesses.find(bundleID: bundle)?.objectID)
            .flatMap { $0 == 0 ? nil : [$0] } ?? []
        let description = ProcessSource.describeTap(
            bundle: bundle, sourceName: "second opinion", processes: ids)
        description.name = "\(C.appName) second opinion"
        guard AudioHardwareCreateProcessTap(description, &tap) == noErr, tap != 0
        else { return nil }

        var addr = AudioObjectPropertyAddress(mSelector: kAudioTapPropertyUID,
                                              mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var value: CFString?
        var size = UInt32(MemoryLayout<CFString?>.size)
        let got = withUnsafeMutablePointer(to: &value) { ptr -> OSStatus in
            AudioObjectGetPropertyData(tap, &addr, 0, nil, &size, ptr)
        }
        guard got == noErr, let uid = value as String? else { close(); return nil }

        let settings: [String: Any] = [
            kAudioAggregateDeviceNameKey: "\(C.appName) second opinion",
            kAudioAggregateDeviceUIDKey: "app.tgstudios.dropdeck.second.\(UUID().uuidString)",
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [],
            kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: uid]],
        ]
        guard AudioHardwareCreateAggregateDevice(settings as CFDictionary, &aggregate) == noErr,
              aggregate != 0 else { close(); return nil }

        var made: AudioDeviceIOProcID?
        let attached = AudioDeviceCreateIOProcIDWithBlock(&made, aggregate, nil) {
            [weak self] _, inInputData, _, _, _ in
            guard let self else { return }
            let buffers = UnsafeMutableAudioBufferListPointer(
                UnsafeMutablePointer(mutating: inInputData))
            guard let first = buffers.first,
                  let data = first.mData?.assumingMemoryBound(to: Float.self) else { return }
            self.calls += 1
            for i in 0..<(Int(first.mDataByteSize) / 4) { self.peak = max(self.peak, abs(data[i])) }
        }
        guard attached == noErr, let made,
              AudioDeviceStart(aggregate, made) == noErr else { close(); return nil }
        proc = made
    }

    func close() {
        if let proc, aggregate != 0 {
            AudioDeviceStop(aggregate, proc)
            AudioDeviceDestroyIOProcID(aggregate, proc)
        }
        proc = nil
        if aggregate != 0 { AudioHardwareDestroyAggregateDevice(aggregate); aggregate = 0 }
        if tap != 0 { AudioHardwareDestroyProcessTap(tap); tap = 0 }
    }
}
