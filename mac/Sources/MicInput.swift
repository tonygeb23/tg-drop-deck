// The microphone: capture, gain, processing, monitoring and ducking.
//
// Two rules from the Windows copy, and neither is negotiable:
//
//   THE MICROPHONE DUCKS BY BEING OPEN, not by level and not through a gate.
//   Opening it puts a flag on the shared DuckBus and closing it takes the flag
//   off, which is why it ducks a bed playing out of a different sound card. A
//   gate that opens on your voice clips the first syllable of every sentence;
//   one that hangs open ducks the bed when you cough.
//
//   NOTHING OPENS A MICROPHONE EXCEPT A KEYPRESS. Not startup, not loading a
//   board. The device, the gain and whether monitoring is wanted are saved;
//   whether it was ON is deliberately not, and there is a test that says so.

import Foundation

/// A fixed size ring that never blocks and never allocates while running.
///
/// Each reader takes what it reads away, which is why the microphone keeps two
/// of these: a presenter on speakers monitors nothing and is still on air.
final class AudioRing {
    private var buffer: [Float]
    private let frames: Int
    private var write = 0
    private var filled = 0
    private let lock = NSLock()

    init(frames: Int) {
        self.frames = max(1, frames)
        buffer = [Float](repeating: 0, count: self.frames * 2)
    }

    var available: Int {
        lock.lock(); defer { lock.unlock() }
        return filled
    }

    func clear() {
        lock.lock(); write = 0; filled = 0; lock.unlock()
    }

    func push(_ source: UnsafePointer<Float>, count: Int) {
        guard count > 0 else { return }
        lock.lock(); defer { lock.unlock() }
        buffer.withUnsafeMutableBufferPointer { buf in
            let base = buf.baseAddress!
            if count >= frames {
                base.update(from: source + (count - frames) * 2, count: frames * 2)
                write = 0
                filled = frames
                return
            }
            let end = write + count
            if end <= frames {
                (base + write * 2).update(from: source, count: count * 2)
            } else {
                let first = frames - write
                (base + write * 2).update(from: source, count: first * 2)
                base.update(from: source + first * 2, count: (count - first) * 2)
            }
            write = end % frames
            filled = min(frames, filled + count)
        }
    }

    /// Zero pads rather than blocking. A starved monitor must never take the
    /// music down with it.
    func pull(_ out: UnsafeMutablePointer<Float>, count: Int) {
        out.update(repeating: 0, count: count * 2)
        lock.lock(); defer { lock.unlock() }
        let take = min(count, filled)
        guard take > 0 else { return }
        let start = (write - filled + frames * 2) % frames
        buffer.withUnsafeBufferPointer { buf in
            let base = buf.baseAddress!
            for i in 0..<take {
                let at = (start + i) % frames
                out[i * 2] = base[at * 2]
                out[i * 2 + 1] = base[at * 2 + 1]
            }
        }
        filled -= take
    }
}

/// What is taken off an input with more than one channel.
///
/// The first four fold to mono and put the same signal in both ears, which is
/// what a microphone wants: a mono voice panned anywhere but the middle is a
/// voice half the audience hears quietly. `stereo` is the one that does not,
/// and it exists because a microphone input is not always a microphone. A
/// loopback device carrying a whole programme, a desk feed or a mixer's main
/// out is stereo, and folding it was throwing the image away: "if I use a
/// loopback device as my microphone input and have it set to capture both
/// channels the audio comes out in mono".
enum MicChannel: String, CaseIterable {
    case mix, left, right, stereo
    var label: String {
        switch self {
        case .mix: return "Both, mixed together (a microphone)"
        case .left: return "Left only"
        case .right: return "Right only"
        case .stereo: return "Keep it in stereo (a loopback, desk or mixer feed)"
        }
    }
    /// Said out loud when it changes, where the full label is too long.
    var spoken: String {
        switch self {
        case .mix: return "both channels mixed to mono"
        case .left: return "the left channel only"
        case .right: return "the right channel only"
        case .stereo: return "left and right kept apart, in stereo"
        }
    }
}

/// The key the microphone publishes its duck under.
let micDuckKey = "microphone"

final class MicInput {

    var isOpen: Bool { input.isOpen }
    private(set) var lastError: String?
    var deviceUID: String? { input.deviceUID }
    var deviceName: String? { input.deviceName }

    var gainDB: Float = C.defaultMicGainDB
    var channel: MicChannel = .mix
    var monitorWanted = false
    var onAir = true

    /// Measured before processing, because that is what a gain control needs
    /// to be set against.
    private(set) var peak: Float = 0
    private(set) var processedPeak: Float = 0

    let chain = MicChain()
    private let duckBus: DuckBus
    private let input = InputUnit()

    private let monitorRing: AudioRing
    private let airRing: AudioRing

    private var outputRate: Double = C.defaultSampleRate
    private var resampler: RTResampler?
    private var stereo: UnsafeMutablePointer<Float>
    private var resampled: UnsafeMutablePointer<Float>
    private var capacity = 8192

    init(duckBus: DuckBus) {
        self.duckBus = duckBus
        monitorRing = AudioRing(frames: C.micRingFrames)
        airRing = AudioRing(frames: C.micRingFrames)
        stereo = .allocate(capacity: capacity * 2)
        resampled = .allocate(capacity: capacity * 4)
        input.onCapture = { [weak self] raw, frames, channels in
            self?.handle(raw, frames, channels)
        }
    }

    deinit {
        close()
        stereo.deallocate(); resampled.deallocate()
    }

    /// Open the microphone. Called only from a keypress.
    @discardableResult
    func open(deviceUID: String?, outputRate: Double) -> Bool {
        guard !isOpen else { return true }
        self.outputRate = outputRate
        guard input.open(deviceUID: deviceUID) else {
            lastError = input.lastError
            return false
        }
        lastError = nil
        chain.prepare(rate: outputRate)
        resampler = abs(input.captureRate - outputRate) > 0.5
            ? RTResampler(from: input.captureRate, to: outputRate) : nil
        monitorRing.clear()
        airRing.clear()
        // Ducking is by being OPEN. This is the whole mechanism.
        duckBus.publish(micDuckKey, true)
        return true
    }

    func close() {
        input.close()
        peak = 0
        processedPeak = 0
        duckBus.publish(micDuckKey, false)
        monitorRing.clear()
        airRing.clear()
    }

    private func handle(_ raw: UnsafePointer<Float>, _ frames: Int, _ channels: UInt32) {
        if frames > capacity { grow(frames) }
        peak = foldToStereo(raw, frames: frames, channels: channels,
                            channel: channel, gain: dbToGain(gainDB), into: stereo)

        // Nothing else is worth doing if nobody is listening.
        guard monitorWanted || onAir else { return }

        var out = stereo
        var count = frames
        if let resampler {
            let produced = resampler.convert(stereo, frames: frames,
                                             into: resampled, capacity: capacity * 2)
            guard produced > 0 else { return }
            out = resampled
            count = produced
        }

        chain.process(out, frames: count)

        var after: Float = 0
        for i in 0..<(count * 2) { after = max(after, abs(out[i])) }
        processedPeak = after

        // Two separate rings, because each reader takes what it reads away.
        if monitorWanted { monitorRing.push(out, count: count) }
        if onAir { airRing.push(out, count: count) }
    }

    private func grow(_ frames: Int) {
        stereo.deallocate(); resampled.deallocate()
        capacity = frames * 2
        stereo = .allocate(capacity: capacity * 2)
        resampled = .allocate(capacity: capacity * 4)
    }

    /// What the presenter hears. Added after the duck, so the voice does not
    /// duck itself.
    func readMonitor(frames: Int, into out: UnsafeMutablePointer<Float>) {
        guard isOpen, monitorWanted else {
            out.update(repeating: 0, count: frames * 2)
            return
        }
        monitorRing.pull(out, count: frames)
    }

    /// What the listener hears.
    func readAir(frames: Int, into out: UnsafeMutablePointer<Float>) {
        guard isOpen, onAir else {
            out.update(repeating: 0, count: frames * 2)
            return
        }
        airRing.pull(out, count: frames)
    }
}
