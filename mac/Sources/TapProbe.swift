// Which way of asking Core Audio for a process tap actually works here, and
// does sound then come out of it.
//
//   --tap-probe <bundle id> [seconds]
//
// Diagnostic only. It exists because `AudioHardwareCreateProcessTap` can
// return noErr and hand back nothing, which is not a documented outcome and is
// impossible to reason about without trying each construction on the machine
// in front of you.

import Foundation
import AppKit
import CoreAudio
import AVFoundation

enum TapProbe {

    static func run(_ bundle: String, seconds: Double) -> Int32 {
        print("\(C.appName) \(C.appVersion), probing a process tap for \(bundle)")
        print("macOS \(ProcessInfo.processInfo.operatingSystemVersionString)")
        print("Screen and System Audio Recording: \(Permissions.state(.screen).said)")
        print("")

        guard #available(macOS 14.2, *) else {
            print("this needs macOS 14.2"); return 1
        }
        let found = AudioProcesses.find(bundleID: bundle)
        print("the process, through Core Audio: "
            + (found.map { "objectID \($0.objectID), playing now: \($0.isPlaying)" }
               ?? "NOT in the audio process list"))
        print("")

        // PLAYING watches which programs actually put sound out, which is the
        // only way to find out that a program speaks through a helper, or that
        // the thing you are waiting for is not making a noise after all.
        if bundle == "PLAYING" {
            print("watching for \(seconds) seconds, use the programs you care about now")
            var seen: [String: String] = [:]
            let until = Date().addingTimeInterval(seconds)
            while Date() < until {
                for p in AudioProcesses.all() where p.isPlaying { seen[p.bundleID] = p.name }
                Thread.sleep(forTimeInterval: 0.05)
            }
            print("")
            if seen.isEmpty { print("nothing put any sound out"); return 2 }
            print("these put sound out:")
            for (bundleID, name) in seen.sorted(by: { $0.key < $1.key }) {
                print("   \(name)  [\(bundleID)]")
            }
            return 0
        }

        // SYSTEM taps everything, which separates "the chain is broken" from
        // "that program is not making a sound".
        if bundle == "SYSTEM" {
            print("tapping everything the Mac is playing")
            return listen(CATapDescription(stereoGlobalTapButExcludeProcesses: []),
                          for: seconds, withOutputClock: false)
        }

        var anyWorked = false
        var anyHeard = false

        func attempt(_ name: String, _ make: @escaping () -> CATapDescription?) {
            guard let description = make() else {
                print("\(name): could not even build the description"); return
            }
            description.name = "\(C.appName) probe"
            description.isPrivate = true
            description.muteBehavior = .unmuted
            var tap: AudioObjectID = 0
            let status = AudioHardwareCreateProcessTap(description, &tap)
            let ok = status == noErr && tap != 0
            print("\(name)")
            print("   made a tap    : " + (ok ? "yes" : "NO (status \(status), tap \(tap))"))
            if tap != 0 { AudioHardwareDestroyProcessTap(tap) }
            guard ok, let fresh = make() else { return }
            anyWorked = true
            if listen(fresh, for: seconds, withOutputClock: false) == 0 { anyHeard = true }
        }

        let id = found?.objectID
        if let id {
            attempt("init(stereoMixdownOfProcesses:)") {
                CATapDescription(stereoMixdownOfProcesses: [id])
            }
            attempt("init(stereoMixdownOfProcesses:) plus bundleIDs and restore") {
                let d = CATapDescription(stereoMixdownOfProcesses: [id])
                if #available(macOS 26.0, *) {
                    d.bundleIDs = [bundle]
                    d.isProcessRestoreEnabled = true
                }
                return d
            }
        }
        // The case that matters most: a program that is running but has not
        // made a sound yet, so Core Audio has no object id for it.
        if #available(macOS 26.0, *) {
            attempt("init(stereoMixdownOfProcesses: []) plus bundleIDs") {
                let d = CATapDescription(stereoMixdownOfProcesses: [])
                d.bundleIDs = [bundle]
                d.isProcessRestoreEnabled = true
                return d
            }
        }
        attempt("a bare description with bundleIDs set, which is what shipped") {
            let d = CATapDescription()
            if #available(macOS 26.0, *) { d.bundleIDs = [bundle] }
            return d
        }
        attempt("a bare description with processes set, the pre 26 path") {
            let d = CATapDescription()
            if let id { d.processes = [id] }
            return d
        }

        print("")
        if !anyWorked { print("Nothing worked. No tap can be made for \(bundle) here."); return 1 }
        if !anyHeard { print("Taps were made but that program put no sound out while listening."); return 2 }
        print("A tap was made and sound came through it.")
        return 0
    }

    // Build the whole chain the app builds and report what came through it.
    @available(macOS 14.2, *)
    private static func listen(_ description: CATapDescription, for seconds: Double,
                               withOutputClock: Bool) -> Int32 {
        description.name = "\(C.appName) probe"
        description.isPrivate = true
        description.muteBehavior = .unmuted
        var tap: AudioObjectID = 0
        guard AudioHardwareCreateProcessTap(description, &tap) == noErr, tap != 0 else {
            print("the tap would not be made"); return 1
        }
        defer { AudioHardwareDestroyProcessTap(tap) }

        var addr = AudioObjectPropertyAddress(mSelector: kAudioTapPropertyUID,
                                              mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var uidValue: CFString?
        var size = UInt32(MemoryLayout<CFString?>.size)
        let got = withUnsafeMutablePointer(to: &uidValue) { ptr -> OSStatus in
            AudioObjectGetPropertyData(tap, &addr, 0, nil, &size, ptr)
        }
        guard got == noErr, let uid = uidValue as String? else {
            print("the tap has no uid"); return 1
        }

        // A tap on its own has no clock. The aggregate needs a real device in
        // it to tick, and the speakers are the right one: that is the clock the
        // tapped program is already playing to.
        let clockUID = AudioDevices.defaultOutput().flatMap { AudioDevices.info(for: $0)?.uid }

        var settings: [String: Any] = [
            kAudioAggregateDeviceNameKey: "\(C.appName) probe",
            kAudioAggregateDeviceUIDKey: "app.tgstudios.dropdeck.probe",
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [],
            kAudioAggregateDeviceTapListKey: [
                [kAudioSubTapUIDKey: uid, kAudioSubTapDriftCompensationKey: true]],
        ]
        if withOutputClock, let clockUID {
            settings[kAudioAggregateDeviceMainSubDeviceKey] = clockUID
            settings[kAudioAggregateDeviceSubDeviceListKey] = [[kAudioSubDeviceUIDKey: clockUID]]
        }
        var aggregate: AudioDeviceID = 0
        let made = AudioHardwareCreateAggregateDevice(settings as CFDictionary, &aggregate)
        guard made == noErr, aggregate != 0 else {
            print("the capture device could not be made (\(made))"); return 1
        }
        defer { AudioHardwareDestroyAggregateDevice(aggregate) }


        let box = Meter()
        var proc: AudioDeviceIOProcID?
        let attached = AudioDeviceCreateIOProcIDWithBlock(&proc, aggregate, nil) {
            _, inInputData, _, _, _ in
            let buffers = UnsafeMutableAudioBufferListPointer(
                UnsafeMutablePointer(mutating: inInputData))
            guard let first = buffers.first,
                  let data = first.mData?.assumingMemoryBound(to: Float.self),
                  first.mNumberChannels > 0 else { return }
            let count = Int(first.mDataByteSize) / 4
            box.add(data, count: count, channels: Int(first.mNumberChannels))
        }
        guard attached == noErr, let proc else {
            print("could not attach (\(attached))"); return 1
        }
        guard AudioDeviceStart(aggregate, proc) == noErr else {
            print("would not start"); return 1
        }

        let until = Date().addingTimeInterval(seconds)
        while Date() < until { RunLoop.current.run(until: Date().addingTimeInterval(0.1)) }
        AudioDeviceStop(aggregate, proc)
        AudioDeviceDestroyIOProcID(aggregate, proc)

        let heard = box.peak > 0.001
        print("   heard        : " + (heard
            ? "YES  peak \(String(format: "%.4f", box.peak)) "
              + "(\(String(format: "%.1f", 20 * log10(box.peak))) dB), "
              + "\(box.calls) callbacks, \(box.channels) channels"
            : "no sound at all (\(box.calls) callbacks)"))
        return heard ? 0 : 2
    }

    private final class Meter {
        var peak: Float = 0
        var frames = 0
        var calls = 0
        var channels = 0
        func add(_ data: UnsafePointer<Float>, count: Int, channels: Int) {
            calls += 1
            self.channels = channels
            frames += count / max(1, channels)
            for i in 0..<count { peak = max(peak, abs(data[i])) }
        }
    }
}
