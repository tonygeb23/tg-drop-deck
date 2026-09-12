// The programme bus: one ring per sound card, summed on the way out.
//
// One ring would do if there were only ever one output. A bank can be sent to
// its own card though, and everything the presenter can hear should be what
// goes out, so each mixer gets a ring of its own and they are summed when the
// encoder asks.
//
// The rings are the drift absorber. Two sound cards are never quite the same
// speed, and neither is quite the speed of the clock the encoder runs on, so
// over an hour they slide by a few milliseconds. A ring running behind gives
// silence for the frames it does not have; one running ahead has its oldest
// frames dropped. Both are inaudible at these sizes and neither accumulates.
//
// Drift is not the same thing as a different RATE. A bank sent to a card that
// will only open at 44100, while the main output runs at 48000, delivers 44100
// frames a second into a ring the encoder drains 48000 times a second. That is
// not a few milliseconds an hour, it is four thousand frames a minute: the ring
// runs dry, that card gets nothing but gaps, and the faster ring overflows.
// Each card is converted to the bus rate as it arrives instead.

import Foundation

/// A rate converter that allocates nothing and never blocks, because it runs
/// inside an audio callback.
///
/// Cubic Hermite rather than a windowed sinc. It is used only where two sound
/// cards disagree about their rate, which is a rare path, and the difference
/// between this and a mastering resampler at 44100 to 48000 is far below what
/// a listener on a stream will ever hear. The playback path, where quality does
/// matter, uses AVAudioConverter at mastering quality instead.
final class RTResampler {

    private var ratio: Double
    private var position: Double = 0
    // The three samples before the window, per channel, carried between blocks
    // so the interpolation has no seam at a block boundary.
    private var historyL: (Float, Float, Float) = (0, 0, 0)
    private var historyR: (Float, Float, Float) = (0, 0, 0)

    init(from: Double, to: Double) {
        ratio = from > 0 ? to / from : 1.0
    }

    func set(from: Double, to: Double) {
        let wanted = from > 0 ? to / from : 1.0
        if abs(wanted - ratio) > 1e-12 {
            ratio = wanted
            position = 0
            historyL = (0, 0, 0)
            historyR = (0, 0, 0)
        }
    }

    var isIdentity: Bool { abs(ratio - 1.0) < 1e-12 }

    @inline(__always)
    private func hermite(_ a: Float, _ b: Float, _ c: Float, _ d: Float, _ t: Float) -> Float {
        let c0 = b
        let c1 = 0.5 * (c - a)
        let c2 = a - 2.5 * b + 2.0 * c - 0.5 * d
        let c3 = 0.5 * (d - a) + 1.5 * (b - c)
        return ((c3 * t + c2) * t + c1) * t + c0
    }

    /// Convert `frames` of interleaved stereo into `out`, returning how many
    /// frames were produced. `out` must have room for at least
    /// `Int(Double(frames) * ratio) + 4` frames.
    func convert(_ input: UnsafePointer<Float>, frames: Int,
                 into out: UnsafeMutablePointer<Float>, capacity: Int) -> Int {
        guard frames > 0 else { return 0 }
        if isIdentity {
            let n = min(frames, capacity)
            out.update(from: input, count: n * 2)
            return n
        }
        var produced = 0
        let step = 1.0 / ratio
        while produced < capacity {
            let index = Int(position.rounded(.down))
            if index >= frames { break }
            let t = Float(position - Double(index))

            @inline(__always) func sample(_ offset: Int, _ channel: Int) -> Float {
                let i = index + offset
                if i >= 0 {
                    return i < frames ? input[i * 2 + channel] : input[(frames - 1) * 2 + channel]
                }
                let h = channel == 0 ? historyL : historyR
                switch i {
                case -1: return h.2
                case -2: return h.1
                default: return h.0
                }
            }

            out[produced * 2] = hermite(sample(-1, 0), sample(0, 0),
                                        sample(1, 0), sample(2, 0), t)
            out[produced * 2 + 1] = hermite(sample(-1, 1), sample(0, 1),
                                            sample(1, 1), sample(2, 1), t)
            produced += 1
            position += step
        }
        // Carry the tail of this block into the next one.
        if frames >= 3 {
            historyL = (input[(frames - 3) * 2], input[(frames - 2) * 2], input[(frames - 1) * 2])
            historyR = (input[(frames - 3) * 2 + 1], input[(frames - 2) * 2 + 1],
                        input[(frames - 1) * 2 + 1])
        }
        position -= Double(frames)
        if position < 0 { position = 0 }
        return produced
    }
}

/// One sound card's worth of programme, waiting to be summed.
private final class AirRing {
    var buffer: [Float]
    var write = 0
    var filled = 0
    var lastSeen: TimeInterval
    var resampler: RTResampler?
    var scratch: [Float]

    init(frames: Int, now: TimeInterval) {
        buffer = [Float](repeating: 0, count: frames * 2)
        lastSeen = now
        scratch = [Float](repeating: 0, count: (frames + 8) * 2)
    }
}

final class AirBus {

    let sampleRate: Double
    private let frames: Int
    private let patience: TimeInterval
    private var rings: [String: AirRing] = [:]
    private let lock = NSLock()

    /// Blocks thrown away because the encoder could not keep up. The presenter
    /// is told, because silent dropouts are how a stream lies.
    private(set) var dropped = 0

    init(sampleRate: Double, seconds: Double = C.airRingSeconds) {
        self.sampleRate = sampleRate
        self.frames = max(1, Int(sampleRate * seconds))
        self.patience = seconds
    }

    /// Called from an audio callback. Must not block for long and must not
    /// throw.
    func write(key: String, samples: UnsafePointer<Float>, frames n: Int, rate: Double) {
        guard n > 0 else { return }
        let now = Date().timeIntervalSinceReferenceDate
        lock.lock()
        defer { lock.unlock() }

        let ring: AirRing
        if let existing = rings[key] {
            ring = existing
        } else {
            ring = AirRing(frames: frames, now: now)
            rings[key] = ring
        }
        ring.lastSeen = now

        if abs(rate - sampleRate) > 0.5 {
            // A card running at a different rate is converted as it arrives.
            // The scratch buffer is a property so nothing is allocated here,
            // and the whole conversion happens inside its own scope: a pointer
            // taken out of one of these closures is dangling the moment it
            // leaves, which in an audio callback is a crash nobody can
            // reproduce.
            if ring.resampler == nil { ring.resampler = RTResampler(from: rate, to: sampleRate) }
            ring.resampler?.set(from: rate, to: sampleRate)
            let capacity = ring.scratch.count / 2
            var produced = 0
            ring.scratch.withUnsafeMutableBufferPointer { scratch in
                produced = ring.resampler!.convert(samples, frames: n,
                                                   into: scratch.baseAddress!,
                                                   capacity: capacity)
                guard produced > 0 else { return }
                store(into: ring, from: scratch.baseAddress!, count: produced)
            }
            return
        }
        store(into: ring, from: samples, count: n)
    }

    /// Put a block into one card's ring. Called with the lock already held.
    private func store(into ring: AirRing, from source: UnsafePointer<Float>, count: Int) {
        ring.buffer.withUnsafeMutableBufferPointer { buf in
            let base = buf.baseAddress!
            if count >= frames {
                // A block bigger than the whole ring: keep the newest of it.
                base.update(from: source + (count - frames) * 2, count: frames * 2)
                ring.write = 0
                ring.filled = frames
                dropped += 1
                return
            }
            let end = ring.write + count
            if end <= frames {
                (base + ring.write * 2).update(from: source, count: count * 2)
            } else {
                let first = frames - ring.write
                (base + ring.write * 2).update(from: source, count: first * 2)
                base.update(from: source + first * 2, count: (count - first) * 2)
            }
            ring.write = end % frames
            if ring.filled + count > frames { dropped += 1 }
            ring.filled = min(frames, ring.filled + count)
        }
    }

    /// The thinnest ALIVE ring. A ring stays alive until it has been empty for
    /// longer than one ring length: otherwise an unplugged card pins the whole
    /// stream at zero for ever.
    func available() -> Int {
        let now = Date().timeIntervalSinceReferenceDate
        lock.lock(); defer { lock.unlock() }
        var thinnest = Int.max
        for ring in rings.values {
            if ring.filled == 0 && now - ring.lastSeen > patience { continue }
            thinnest = min(thinnest, ring.filled)
        }
        return thinnest == Int.max ? 0 : thinnest
    }

    /// Sum every card into `out`, which is interleaved stereo and is
    /// overwritten. A ring with nothing in it contributes silence rather than
    /// holding everybody else up.
    func read(frames n: Int, into out: UnsafeMutablePointer<Float>) {
        out.update(repeating: 0, count: n * 2)
        let now = Date().timeIntervalSinceReferenceDate
        lock.lock(); defer { lock.unlock() }
        for ring in rings.values {
            if ring.filled == 0 && now - ring.lastSeen > patience { continue }
            let take = min(n, ring.filled)
            guard take > 0 else { continue }
            let start = (ring.write - ring.filled + frames * 2) % frames
            ring.buffer.withUnsafeBufferPointer { buf in
                let base = buf.baseAddress!
                for i in 0..<take {
                    let at = (start + i) % frames
                    out[i * 2] += base[at * 2]
                    out[i * 2 + 1] += base[at * 2 + 1]
                }
            }
            ring.filled -= take
        }
    }

    func reset() {
        lock.lock()
        rings.removeAll()
        dropped = 0
        lock.unlock()
    }
}

/// Fans one write out to several buses, because a stream and a recording are
/// two readers and each takes what it reads away.
///
/// Swallows everything. It runs in the audio callback, where one exception
/// escaping silences that sound card for the rest of the show.
/// An AirBus IS a programme tap: its `write` is the protocol's `write`. Stated
/// rather than left implicit because the monitor bus is written by every mixer
/// directly, with no `Taps` in the middle, there being exactly one reader.
extension AirBus: ProgramTap {}

final class Taps: ProgramTap {
    private var buses: [ObjectIdentifier: AirBus] = [:]
    private let lock = NSLock()

    var isEmpty: Bool {
        lock.lock(); defer { lock.unlock() }
        return buses.isEmpty
    }

    func add(_ bus: AirBus) {
        lock.lock(); buses[ObjectIdentifier(bus)] = bus; lock.unlock()
    }

    func remove(_ bus: AirBus) {
        lock.lock(); buses.removeValue(forKey: ObjectIdentifier(bus)); lock.unlock()
    }

    func write(key: String, samples: UnsafePointer<Float>, frames: Int, rate: Double) {
        lock.lock()
        let targets = Array(buses.values)
        lock.unlock()
        for bus in targets {
            bus.write(key: key, samples: samples, frames: frames, rate: rate)
        }
    }
}
