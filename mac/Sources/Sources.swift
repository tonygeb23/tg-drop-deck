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
    /// How much audio has actually arrived from the capture, and how loud the
    /// loudest of it was. Only for the diagnostics: it separates "nothing is
    /// arriving" from "it arrives and then does not survive the way here",
    /// which look identical from the far end and have nothing in common.
    private(set) var framesIn = 0
    private(set) var peakIn: Float = 0
    /// Whether the two channels have ever differed. A program folded to mono
    /// puts the same number in both ears for ever, and that is invisible from
    /// a level meter, which is how a stereo mix went out flat without anybody
    /// being able to point at where.
    private(set) var sawStereo = false
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

    /// Start the arriving-audio meter again, for a fresh look at a source.
    func resetMeter() { framesIn = 0; peakIn = 0; sawStereo = false }

    /// How the incoming channels are folded down to the two that go out.
    ///
    /// The board's choice, for a device: a microphone on one leg of a stereo
    /// interface has to be mixed or picked, and "both, mixed together" is the
    /// right default for one. A captured PROGRAM overrides it, because there
    /// is nothing to choose: see `ProcessSource`.
    var foldChannel: MicChannel { config.channel }

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
                            channel: foldChannel, gain: gain, into: stereo)
        framesIn += frames
        peakIn = max(peakIn, peak)
        // Sampled rather than every frame: this runs in the audio callback and
        // one difference anywhere is the whole answer.
        if !sawStereo {
            var i = 0
            while i < frames {
                if stereo[i * 2] != stereo[i * 2 + 1] { sawStereo = true; break }
                i += 64
            }
        }

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
        // A named device that is not there is a failure, NOT a reason to open
        // the built in microphone instead. The layer below falls back to the
        // default input, which is right for the microphone and wrong here: a
        // source set to a mixer on a desk would quietly become the laptop lid,
        // sound perfectly healthy, and put the wrong thing on the air. Windows
        // refuses the same way, with the same words.
        if let uid = config.deviceUID, !uid.isEmpty,
           AudioDevices.deviceID(forUID: uid) == nil {
            setError("\(AudioDevices.name(forUID: uid) ?? "That device") is not plugged in")
            return false
        }
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

/// One program that could be put on the air.
///
/// `isPlaying` means it is making a noise this second. `isKnownToCoreAudio`
/// means Core Audio has an object for it, which on macOS 25 and earlier is what
/// a tap needs; from macOS 26 a tap is described by bundle id and a program that
/// has not made a sound yet can still be chosen.
struct AudioProcessInfo {
    let objectID: AudioObjectID
    let pid: pid_t
    let bundleID: String
    let name: String
    let isPlaying: Bool
    var isKnownToCoreAudio: Bool = true
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
        // AND EVERY OTHER PROGRAM THAT IS RUNNING.
        //
        // Core Audio's process list only holds programs that have already
        // opened audio. Spotify sitting there paused, or just launched, is not
        // in it, and the first report of this was exactly that: "when adding a
        // source to a broadcast Spotify does not show up in the list". From
        // macOS 26 the tap is described by bundle id, so a program can be
        // chosen before it has made a sound and the tap picks it up when it
        // does. Anything already found above wins, because that entry carries
        // the object id an older macOS needs.
        let known = Set(out.map(\.bundleID))
        for app in NSRunningApplicationShim.running() where !known.contains(app.bundleID) {
            out.append(AudioProcessInfo(objectID: 0, pid: app.pid,
                                        bundleID: app.bundleID, name: app.name,
                                        isPlaying: false, isKnownToCoreAudio: false))
        }

        // A program that is making a noise right now is the one somebody is
        // looking for, so those come first, then everything Core Audio already
        // knows, then the rest of what is running, each set by name.
        func rank(_ p: AudioProcessInfo) -> Int {
            p.isPlaying ? 0 : (p.isKnownToCoreAudio ? 1 : 2)
        }
        return out.sorted {
            rank($0) != rank($1) ? rank($0) < rank($1)
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

    /// Every program running right now that could plausibly make a noise.
    /// Set by the window; empty until it is, which is what the self test sees.
    static var runningApps: (() -> [(pid: pid_t, bundleID: String, name: String)])?
    static func running() -> [(pid: pid_t, bundleID: String, name: String)] {
        runningApps?() ?? []
    }
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

    /// **A captured program is always kept in stereo.**
    ///
    /// The tap is a stereo mixdown of that program's own output, so the two
    /// channels are already exactly what the program is playing. Folding them
    /// together would throw away half of a stereo mix for no reason, and there
    /// is no microphone-on-one-leg case here to fold for.
    ///
    /// This is also what Windows does, though it arrives there by accident:
    /// its channel setting is only ever applied to a device, because a program
    /// source uses `ProcessCapture`, which has no channel attribute at all.
    /// The Mac applied the board's channel to both, and the board's default is
    /// "both, mixed together", so **every captured program went out in mono**
    /// while the panel would not even let you change it: the channel popup is
    /// disabled for a program, correctly, because the setting does not apply.
    /// Reported by Tony: Logic Pro arrived on YouTube in mono.
    override var foldChannel: MicChannel { .stereo }

    /// How a tap is asked for. **The only place it is built**, because getting
    /// this wrong is silent.
    ///
    /// It MUST use one of the initialisers that takes the processes up front.
    /// A plain `CATapDescription()` with the processes or the bundle ids set
    /// afterwards is refused without saying so: Core Audio returns noErr and
    /// hands back tap object 0, nothing is captured, and every layer above
    /// goes on reporting the source as on the air. That is not documented
    /// anywhere. It is measured, on the machine in front of you, by
    /// `--tap-probe`, which builds every form and reports which ones make a
    /// tap and which ones actually carry sound:
    ///
    ///     init(stereoMixdownOfProcesses:)                  tap, sound
    ///     init(stereoMixdownOfProcesses:) + bundleIDs      tap, sound
    ///     init(stereoMixdownOfProcesses: []) + bundleIDs   tap, sound
    ///     CATapDescription() then set bundleIDs            NO TAP
    ///     CATapDescription() then set processes            NO TAP
    ///
    /// Do not shorten this to the plain initialiser. It is the reason two
    /// sources that were on the air went out as silence.
    @available(macOS 14.2, *)
    static func describeTap(bundle: String, sourceName: String,
                            processes: [AudioObjectID]) -> CATapDescription {
        let description = CATapDescription(stereoMixdownOfProcesses: processes)
        description.name = "\(C.appName) tap for \(sourceName)"
        description.isPrivate = true
        // The presenter goes on hearing the program in their own ears while it
        // also goes to air. Muting it locally would be catastrophic when the
        // program is the screen reader.
        description.muteBehavior = .unmuted
        if #available(macOS 26.0, *) {
            // From macOS 26 the tap can also name the program by bundle id,
            // which is what lets a program be chosen before it has ever made a
            // sound, and what lets the tap pick the program up again when it
            // restarts. VoiceOver does get restarted.
            description.bundleIDs = [bundle]
            description.isProcessRestoreEnabled = true
        }
        return description
    }

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

        // The tap MUST be built with one of the initialisers that takes the
        // processes up front. A plain CATapDescription() with the processes or
        // the bundle ids set afterwards is silently refused: Core Audio returns
        // noErr and hands back tap object 0, so nothing is captured and nothing
        // says why. That is not documented anywhere. It is measured, on this
        // machine, by `--tap-probe`, which builds every form and reports which
        // ones make a tap and which ones actually carry sound:
        //
        //   init(stereoMixdownOfProcesses:)                  tap, sound
        //   init(stereoMixdownOfProcesses:) + bundleIDs      tap, sound
        //   init(stereoMixdownOfProcesses: []) + bundleIDs   tap, sound
        //   CATapDescription() then set bundleIDs            NO TAP
        //   CATapDescription() then set processes            NO TAP
        //
        // Do not shorten this to the plain initialiser. It is the reason two
        // sources that were on the air went out as silence.
        let known = AudioProcesses.find(bundleID: bundle)
        // objectID 0 means the program is running but has never opened audio,
        // so Core Audio has no object for it yet and there is nothing to pass.
        let ids: [AudioObjectID] = (known?.objectID).flatMap { $0 == 0 ? nil : [$0] } ?? []
        if #unavailable(macOS 26.0), ids.isEmpty {
            setError("\(config.name) has not played any audio yet. Play something in it, "
                     + "then switch this source off and on again.")
            return false
        }
        let description = ProcessSource.describeTap(bundle: bundle, sourceName: config.name,
                                                    processes: ids)

        var tap: AudioObjectID = 0
        let status = AudioHardwareCreateProcessTap(description, &tap)
        guard status == noErr, tap != 0 else {
            setError(status == kAudioHardwareIllegalOperationError
                     ? "macOS refused to capture that program. Allow \(C.appName) under "
                       + "Privacy and Security, Screen and System Audio Recording."
                     : status == noErr
                       ? "macOS would not capture \(config.name) and gave no reason."
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
        // The name has to be unique for THIS capture, not just for this source.
        // A fixed name collides with the same source in a second copy of the
        // app, and with one left behind by a copy that was force quit, and Core
        // Audio answers that collision with kAudioHardwareIllegalOperationError
        // and no explanation. The source then reports "it did not start" and
        // the program goes out as silence, which is the same ending as the tap
        // fault this replaced and just as hard to see.
        let aggregateUID = "app.tgstudios.dropdeck.tap.\(config.id).\(UUID().uuidString)"
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
            setError(created == kAudioHardwareIllegalOperationError
                     ? "macOS would not make a capture device for \(config.name). "
                       + "Another copy of \(C.appName) may already be capturing it."
                     : "The capture device could not be made (\(created))")
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

    @discardableResult
    func replace(with configs: [SourceConfig], outputRate: Double) -> [String] {
        stopAll()
        lock.lock()
        sources = configs.map { config -> RunningSource in
            config.isProcess ? ProcessSource(config: config) : DeviceSource(config: config)
        }
        let list = sources
        lock.unlock()
        for source in list { source.start(outputRate: outputRate) }
        return trouble
    }

    /// The wanted sources that are not actually running, each with its reason.
    ///
    /// **Nothing else in the app noticed that a source had failed.** Two
    /// sources sat there marked on air, reading as on air, and went out as
    /// silence, because the only place that ever looked was the sources panel
    /// and only on the way out of it. Windows says "These sources would not
    /// open" every time it opens them; this is that list.
    var trouble: [String] {
        all.filter { ($0.config.onAir || $0.config.monitor) && !$0.isRunning }
           .map { source in
               let why = source.lastError ?? "it would not open"
               return "\(source.config.name): \(why)"
           }
    }

    /// Sources that are perfectly healthy and will still be silent.
    ///
    /// From macOS 26 a tap can be made for a program BEFORE that program is
    /// running, and it waits for it. That is the right behaviour, and it is
    /// also a new way for a source to pass every check and send nothing: the
    /// capture is fine, the program simply is not there. Said before going
    /// live rather than discovered afterwards on somebody's phone.
    var waitingForAProgram: [String] {
        all.compactMap { source in
            let c = source.config
            guard c.isProcess, c.onAir, source.isRunning,
                  let bundle = c.bundleID, !bundle.isEmpty,
                  AudioProcesses.find(bundleID: bundle) == nil else { return nil }
            let program = bundle.components(separatedBy: ".").last ?? bundle
            return "\(c.name) is set to capture \(program), which is not running"
        }
    }

    /// Try the ones that are not running again.
    ///
    /// A program can be chosen before it is open, and somebody who starts
    /// Logic after going on air should not have to know to go back into a
    /// dialog. Only the failed ones are touched, so a running capture is never
    /// interrupted by the retry.
    func retryFailed(outputRate: Double) -> [String] {
        var cameOn: [String] = []
        for source in all where !source.isRunning {
            guard source.config.onAir || source.config.monitor else { continue }
            if source.start(outputRate: outputRate) { cameOn.append(source.config.name) }
        }
        return cameOn
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
