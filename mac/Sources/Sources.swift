// Other audio on the air with you.
//
// Two kinds, and they look the same once they are running: a sound card or a
// cable, which is a co-host's microphone or a hardware mixer, and ONE PROGRAM,
// captured straight from it with no cable in the middle and nothing to install.
//
// Your screen reader is in that list. VoiceOver is an ordinary audio process as
// far as Core Audio is concerned, so a demonstration or a tutorial goes out the
// way any other program does. The tap is created with muteBehavior .unmuted on
// purpose: the presenter goes on hearing VoiceOver in their own ears while it
// also goes to air, and muting it locally the moment the encoder started
// reading would be catastrophic for a blind presenter.
//
// Extra sources are never processed and never ducked. Both of those belong to
// the microphone.

import Foundation
import AudioToolbox
import CoreAudio

// ------------------------------------------------------------- what it is ---

struct SourceConfig {
    var id: String = UUID().uuidString
    var name: String = "Source"
    /// "device" or "process".
    var kind: String = "device"
    var deviceUID: String?
    var bundleID: String?
    var channel: MicChannel = .mix
    var gainDB: Float = 0
    var onAir: Bool = true
    var monitor: Bool = false
    var muted: Bool = false

    var isProcess: Bool { kind == "process" }

    func toDict() -> [String: Any] {
        [
            "id": id, "name": name, "kind": kind,
            "device_uid": deviceUID as Any? ?? NSNull(),
            "bundle_id": bundleID as Any? ?? NSNull(),
            "channel": channel.rawValue,
            "gain_db": Double(gainDB),
            "on_air": onAir, "monitor": monitor, "muted": muted,
        ]
    }

    static func fromDict(_ d: [String: Any]) -> SourceConfig? {
        var c = SourceConfig()
        c.id = d["id"] as? String ?? UUID().uuidString
        c.name = d["name"] as? String ?? "Source"
        c.kind = d["kind"] as? String ?? "device"
        c.deviceUID = d["device_uid"] as? String
        c.bundleID = d["bundle_id"] as? String
        if let ch = d["channel"] as? String, let parsed = MicChannel(rawValue: ch) {
            c.channel = parsed
        }
        c.gainDB = Float(d["gain_db"] as? Double ?? 0)
        c.onAir = d["on_air"] as? Bool ?? true
        c.monitor = d["monitor"] as? Bool ?? false
        c.muted = d["muted"] as? Bool ?? false
        return c
    }
}

protocol RunningSource: AnyObject {
    var config: SourceConfig { get set }
    var isRunning: Bool { get }
    var lastError: String? { get }
    var peak: Float { get }
    @discardableResult func start(outputRate: Double) -> Bool
    func stop()
    func readAir(frames: Int, into out: UnsafeMutablePointer<Float>)
    func readMonitor(frames: Int, into out: UnsafeMutablePointer<Float>)
}

/// Everything both kinds share: gain, channel choice, rate conversion and the
/// two rings.
class BaseSource: RunningSource {
    var config: SourceConfig
    private(set) var lastError: String?
    private(set) var peak: Float = 0
    var isRunning: Bool { false }

    let monitorRing = AudioRing(frames: C.micRingFrames)
    let airRing = AudioRing(frames: C.micRingFrames)
    var outputRate: Double = C.defaultSampleRate
    var resampler: RTResampler?

    var stereo: UnsafeMutablePointer<Float>
    var resampled: UnsafeMutablePointer<Float>
    var capacity = 8192

    init(config: SourceConfig) {
        self.config = config
        stereo = .allocate(capacity: capacity * 2)
        resampled = .allocate(capacity: capacity * 4)
    }

    deinit { stereo.deallocate(); resampled.deallocate() }

    func setError(_ message: String?) { lastError = message }

    func grow(_ frames: Int) {
        guard frames > capacity else { return }
        stereo.deallocate(); resampled.deallocate()
        capacity = frames * 2
        stereo = .allocate(capacity: capacity * 2)
        resampled = .allocate(capacity: capacity * 4)
    }

    /// Common tail of both capture paths.
    func deliver(_ raw: UnsafePointer<Float>, frames: Int, channels: UInt32,
                 captureRate: Double) {
        grow(frames)
        let gain = config.muted ? 0 : dbToGain(config.gainDB)
        peak = foldToStereo(raw, frames: frames, channels: channels,
                            channel: config.channel, gain: gain, into: stereo)

        var out = stereo
        var count = frames
        if abs(captureRate - outputRate) > 0.5 {
            if resampler == nil {
                resampler = RTResampler(from: captureRate, to: outputRate)
            }
            resampler?.set(from: captureRate, to: outputRate)
            let produced = resampler!.convert(stereo, frames: frames,
                                              into: resampled, capacity: capacity * 2)
            guard produced > 0 else { return }
            out = resampled
            count = produced
        }
        // An extra source is never processed and never ducked: both of those
        // belong to the microphone.
        if config.monitor { monitorRing.push(out, count: count) }
        if config.onAir { airRing.push(out, count: count) }
    }

    @discardableResult func start(outputRate: Double) -> Bool { false }
    func stop() {}

    func readAir(frames: Int, into out: UnsafeMutablePointer<Float>) {
        guard isRunning, config.onAir, !config.muted else {
            out.update(repeating: 0, count: frames * 2)
            return
        }
        airRing.pull(out, count: frames)
    }

    func readMonitor(frames: Int, into out: UnsafeMutablePointer<Float>) {
        guard isRunning, config.monitor, !config.muted else {
            out.update(repeating: 0, count: frames * 2)
            return
        }
        monitorRing.pull(out, count: frames)
    }
}

// ------------------------------------------------------ a card or a cable ---

final class DeviceSource: BaseSource {
    private let input = InputUnit()
    override var isRunning: Bool { input.isOpen }

    override init(config: SourceConfig) {
        super.init(config: config)
        input.onCapture = { [weak self] raw, frames, channels in
            guard let self else { return }
            self.deliver(raw, frames: frames, channels: channels,
                         captureRate: self.input.captureRate)
        }
    }

    @discardableResult
    override func start(outputRate: Double) -> Bool {
        guard !isRunning else { return true }
        self.outputRate = outputRate
        guard input.open(deviceUID: config.deviceUID) else {
            setError(input.lastError)
            return false
        }
        setError(nil)
        resampler = nil
        monitorRing.clear(); airRing.clear()
        return true
    }

    override func stop() {
        input.close()
        monitorRing.clear(); airRing.clear()
    }
}

// ---------------------------------------------------------- one program ---

/// One running program with audio, as Core Audio sees it.
struct AudioProcessInfo {
    let objectID: AudioObjectID
    let pid: pid_t
    let bundleID: String
    let name: String
    let isPlaying: Bool
}

enum AudioProcesses {

    static func all() -> [AudioProcessInfo] {
        var addr = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyProcessObjectList,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject),
                                             &addr, 0, nil, &size) == noErr else { return [] }
        let count = Int(size) / MemoryLayout<AudioObjectID>.size
        var ids = [AudioObjectID](repeating: 0, count: count)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),
                                         &addr, 0, nil, &size, &ids) == noErr else { return [] }

        var out: [AudioProcessInfo] = []
        for id in ids {
            guard let bundle = string(id, kAudioProcessPropertyBundleID), !bundle.isEmpty
            else { continue }
            let pid = integer(id, kAudioProcessPropertyPID) ?? 0
            let playing = (integer(id, kAudioProcessPropertyIsRunningOutput) ?? 0) != 0
            out.append(AudioProcessInfo(objectID: id, pid: pid_t(pid),
                                        bundleID: bundle,
                                        name: friendlyName(bundle: bundle, pid: pid_t(pid)),
                                        isPlaying: playing))
        }
        // A program that is making a noise right now is the one somebody is
        // looking for, so those come first.
        return out.sorted {
            $0.isPlaying != $1.isPlaying ? $0.isPlaying
                                         : $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
        }
    }

    static func find(bundleID: String) -> AudioProcessInfo? {
        all().first { $0.bundleID == bundleID }
    }

    private static func friendlyName(bundle: String, pid: pid_t) -> String {
        if let app = NSRunningApplicationShim.name(forPID: pid), !app.isEmpty { return app }
        // The last component of a bundle id is a decent fallback and is what
        // somebody would recognise: com.apple.VoiceOver becomes VoiceOver.
        return bundle.components(separatedBy: ".").last ?? bundle
    }

    private static func string(_ id: AudioObjectID,
                               _ selector: AudioObjectPropertySelector) -> String? {
        var addr = AudioObjectPropertyAddress(mSelector: selector,
                                              mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var value: CFString?
        var size = UInt32(MemoryLayout<CFString?>.size)
        let status = withUnsafeMutablePointer(to: &value) { ptr -> OSStatus in
            AudioObjectGetPropertyData(id, &addr, 0, nil, &size, ptr)
        }
        guard status == noErr, let v = value else { return nil }
        return v as String
    }

    private static func integer(_ id: AudioObjectID,
                                _ selector: AudioObjectPropertySelector) -> Int? {
        var addr = AudioObjectPropertyAddress(mSelector: selector,
                                              mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var value: Int32 = 0
        var size = UInt32(MemoryLayout<Int32>.size)
        guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &value) == noErr
        else { return nil }
        return Int(value)
    }
}

/// A tiny shim so this file does not have to import AppKit.
enum NSRunningApplicationShim {
    static var lookup: ((pid_t) -> String?)?
    static func name(forPID pid: pid_t) -> String? { lookup?(pid) }
}

/// One program's audio, captured with a Core Audio process tap.
///
/// This is the direct equivalent of the Windows WASAPI application loopback,
/// and it is better in one way that matters here: macOS 26 lets the tap be
/// described by BUNDLE ID and restore itself when the program is restarted, so
/// a tap on VoiceOver survives VoiceOver being relaunched mid show. Without
/// that the tap would quietly go dead and nothing would say so.
final class ProcessSource: BaseSource {

    private var tapID: AudioObjectID = 0
    private var aggregateID: AudioDeviceID = 0
    private var ioProc: AudioDeviceIOProcID?
    private var running = false
    private var captureRate: Double = C.defaultSampleRate

    override var isRunning: Bool { running }

    @discardableResult
    override func start(outputRate: Double) -> Bool {
        guard !running else { return true }
        guard #available(macOS 14.2, *) else {
            setError("Capturing one program's audio needs macOS 14.2 or later")
            return false
        }
        guard let bundle = config.bundleID, !bundle.isEmpty else {
            setError("No program chosen")
            return false
        }
        self.outputRate = outputRate

        let description = CATapDescription()
        description.name = "\(C.appName) tap for \(config.name)"
        description.isPrivate = true
        // The presenter goes on hearing the program in their own ears while it
        // also goes to air. Muting it locally would be catastrophic when the
        // program is the screen reader.
        description.muteBehavior = .unmuted

        if #available(macOS 26.0, *) {
            description.bundleIDs = [bundle]
            // The tap remembers the program by bundle id and picks it up again
            // when it restarts. VoiceOver does get restarted.
            description.isProcessRestoreEnabled = true
        } else {
            guard let process = AudioProcesses.find(bundleID: bundle) else {
                setError("\(config.name) is not making any audio at the moment")
                return false
            }
            description.processes = [process.objectID]
        }

        var tap: AudioObjectID = 0
        let status = AudioHardwareCreateProcessTap(description, &tap)
        guard status == noErr, tap != 0 else {
            setError(status == kAudioHardwareIllegalOperationError
                     ? "macOS refused to capture that program. Allow \(C.appName) under "
                       + "Privacy and Security, Screen and System Audio Recording."
                     : "That program's audio could not be captured (\(status))")
            return false
        }
        tapID = tap

        guard let uid = tapUID(tap) else {
            AudioHardwareDestroyProcessTap(tap)
            tapID = 0
            setError("The capture was created but could not be read")
            return false
        }

        // The tap is read through a private aggregate device, which is the only
        // way Core Audio offers to get at one.
        let aggregateUID = "app.tgstudios.dropdeck.tap.\(config.id)"
        let description2: [String: Any] = [
            kAudioAggregateDeviceNameKey: "\(C.appName) \(config.name)",
            kAudioAggregateDeviceUIDKey: aggregateUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [],
            kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: uid]],
        ]
        var aggregate: AudioDeviceID = 0
        let created = AudioHardwareCreateAggregateDevice(description2 as CFDictionary, &aggregate)
        guard created == noErr, aggregate != 0 else {
            AudioHardwareDestroyProcessTap(tap)
            tapID = 0
            setError("The capture device could not be made (\(created))")
            return false
        }
        aggregateID = aggregate
        captureRate = AudioDevices.nominalRate(aggregate) ?? outputRate

        var proc: AudioDeviceIOProcID?
        let attached = AudioDeviceCreateIOProcIDWithBlock(&proc, aggregate, nil) {
            [weak self] _, inInputData, _, _, _ in
            guard let self else { return }
            let buffers = UnsafeMutableAudioBufferListPointer(
                UnsafeMutablePointer(mutating: inInputData))
            guard let first = buffers.first,
                  let data = first.mData?.assumingMemoryBound(to: Float.self)
            else { return }
            let channels = first.mNumberChannels
            let frames = channels > 0
                ? Int(first.mDataByteSize) / (4 * Int(channels)) : 0
            guard frames > 0 else { return }
            self.deliver(data, frames: frames, channels: channels,
                         captureRate: self.captureRate)
        }
        guard attached == noErr, let proc else {
            cleanUp()
            setError("The capture could not be started (\(attached))")
            return false
        }
        ioProc = proc
        guard AudioDeviceStart(aggregate, proc) == noErr else {
            cleanUp()
            setError("The capture would not start")
            return false
        }
        running = true
        setError(nil)
        resampler = nil
        monitorRing.clear(); airRing.clear()
        return true
    }

    private func tapUID(_ tap: AudioObjectID) -> String? {
        var addr = AudioObjectPropertyAddress(
            mSelector: kAudioTapPropertyUID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var value: CFString?
        var size = UInt32(MemoryLayout<CFString?>.size)
        let status = withUnsafeMutablePointer(to: &value) { ptr -> OSStatus in
            AudioObjectGetPropertyData(tap, &addr, 0, nil, &size, ptr)
        }
        guard status == noErr, let v = value else { return nil }
        return v as String
    }

    private func cleanUp() {
        if aggregateID != 0 {
            if let proc = ioProc {
                AudioDeviceStop(aggregateID, proc)
                AudioDeviceDestroyIOProcID(aggregateID, proc)
            }
            AudioHardwareDestroyAggregateDevice(aggregateID)
        }
        if tapID != 0, #available(macOS 14.2, *) {
            AudioHardwareDestroyProcessTap(tapID)
        }
        ioProc = nil
        aggregateID = 0
        tapID = 0
        running = false
    }

    override func stop() {
        cleanUp()
        monitorRing.clear(); airRing.clear()
    }
}

// --------------------------------------------------------------- the sum ---

/// The microphone and every extra source, summed for the programme.
///
/// Only the primary mixer reads this. Every mixer reading it would take the
/// same audio away from each other and the voice would arrive in pieces.
final class SourceGroup: AudioSource {

    var mic: MicInput?
    private(set) var sources: [RunningSource] = []
    /// While one source is soloed everything else is silent, which is the
    /// fastest way to find out what a noise is mid link.
    var soloed: String?

    private var scratch: UnsafeMutablePointer<Float>
    private var capacity = 8192
    private let lock = NSLock()

    init() { scratch = .allocate(capacity: capacity * 2) }
    deinit { scratch.deallocate() }

    func replace(with configs: [SourceConfig], outputRate: Double) {
        stopAll()
        lock.lock()
        sources = configs.map { config -> RunningSource in
            config.isProcess ? ProcessSource(config: config) : DeviceSource(config: config)
        }
        let list = sources
        lock.unlock()
        for source in list { source.start(outputRate: outputRate) }
    }

    func stopAll() {
        lock.lock(); let list = sources; sources = []; lock.unlock()
        for source in list { source.stop() }
    }

    var all: [RunningSource] {
        lock.lock(); defer { lock.unlock() }
        return sources
    }

    func source(id: String) -> RunningSource? {
        all.first { $0.config.id == id }
    }

    private func audible(_ id: String) -> Bool {
        guard let soloed else { return true }
        return soloed == id
    }

    private func grow(_ frames: Int) {
        guard frames > capacity else { return }
        scratch.deallocate()
        capacity = frames * 2
        scratch = .allocate(capacity: capacity * 2)
    }

    /// The programme side: the microphone plus every source that is on air.
    func read(frames: Int, into out: UnsafeMutablePointer<Float>) {
        grow(frames)
        out.update(repeating: 0, count: frames * 2)
        if let mic, mic.isOpen, mic.onAir, audible(micDuckKey) {
            mic.readAir(frames: frames, into: scratch)
            for i in 0..<(frames * 2) { out[i] += scratch[i] }
        }
        for source in all where audible(source.config.id) {
            source.readAir(frames: frames, into: scratch)
            for i in 0..<(frames * 2) { out[i] += scratch[i] }
        }
    }

    /// What the presenter hears of all this, which never reaches the stream.
    func readMonitor(frames: Int, into out: UnsafeMutablePointer<Float>) {
        grow(frames)
        out.update(repeating: 0, count: frames * 2)
        if let mic, mic.isOpen, mic.monitorWanted, audible(micDuckKey) {
            mic.readMonitor(frames: frames, into: scratch)
            for i in 0..<(frames * 2) { out[i] += scratch[i] }
        }
        for source in all where audible(source.config.id) {
            source.readMonitor(frames: frames, into: scratch)
            for i in 0..<(frames * 2) { out[i] += scratch[i] }
        }
    }
}

/// The monitor half, handed to the mixer separately so the two sums cannot be
/// confused with each other.
final class SourceMonitor: AudioSource {
    private let group: SourceGroup
    init(_ group: SourceGroup) { self.group = group }
    func read(frames: Int, into out: UnsafeMutablePointer<Float>) {
        group.readMonitor(frames: frames, into: out)
    }
}
