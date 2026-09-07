// Voices: memory playback, disk streaming, gain envelopes.
//
// This file knows nothing about AppKit, deliberately, which is what lets the
// tests render the whole mixer and inspect the samples with no sound card
// present. It is a literal port of dropdeck/engine.py, and two things in it
// are easy to "improve" into being wrong:
//
//   1. A fade's step is a fraction of THE DISTANCE THIS MOVE HAS TO COVER, not
//      of full scale. Without that, a fade on a fader sitting at eighty per
//      cent finished in eighty per cent of the time it was asked for, so a
//      three second crossfade was really two and a half and the number in the
//      box was not the number you heard.
//   2. Position counts only frames that were really there. Padding an
//      underrun and calling it playback made the position run ahead of the
//      music, and the cue point is measured against it.

import Foundation

@inline(__always) func dbToGain(_ db: Double) -> Float { Float(pow(10.0, db / 20.0)) }
@inline(__always) func dbToGain(_ db: Float) -> Float { powf(10.0, db / 20.0) }

/// One sounding thing. Everything the mixer holds is one of these.
class Voice {

    let slotIndex: Int
    let bus: String
    let name: String
    let loop: Bool
    let rate: Double

    /// Set when the sound has run out or a release has reached zero. The mixer
    /// reaps these.
    var finished = false
    private(set) var releasing = false

    private var gain: Float
    private var target: Float
    private var fadeInFrames: Int
    private var fadeOutFrames: Int
    private var glideFrames: Int
    private var rampFrames: Int
    private var rampSpan: Float

    private var framesPlayed: Int = 0

    init(slotIndex: Int, bus: String, name: String, gain: Float,
         loop: Bool, rate: Double, fadeIn: Double, fadeOut: Double) {
        self.slotIndex = slotIndex
        self.bus = bus
        self.name = name
        self.loop = loop
        self.rate = rate
        self.target = gain
        // A fade in of zero means the sound starts AT level. Nothing on this
        // path may use a falsy test to default it: zero is a real answer.
        self.gain = fadeIn > 0 ? 0.0 : gain
        self.fadeInFrames = max(1, Int(fadeIn * rate))
        self.fadeOutFrames = max(1, Int(fadeOut * rate))
        self.glideFrames = max(1, Int(C.volumeGlide * rate))
        self.rampFrames = self.fadeInFrames
        self.rampSpan = abs(self.target - self.gain)
    }

    /// Seconds of real audio played. Only frames that were really there count.
    var positionSeconds: Double { Double(framesPlayed) / rate }

    var isDucked: Bool { bus == C.busBed || bus == C.busPlaylist }
    var isLoud: Bool { bus == C.busSFX }
    var isBed: Bool { bus == C.busBed }

    /// Point the envelope somewhere new, over this many frames.
    private func aim(_ newTarget: Float, _ frames: Int) {
        target = newTarget
        rampFrames = max(1, frames)
        rampSpan = abs(target - gain)
    }

    /// Move the fader. Ignored while releasing: a bed's fade out is most of a
    /// second, which is right for stopping and wrong for a keypress, and
    /// holding the volume key down would crawl.
    func setGain(_ g: Float) {
        guard !releasing else { return }
        aim(g, glideFrames)
    }

    /// Stop, over the given fade. Idempotent, and re-releasable with a shorter
    /// fade, which is what stopping mid crossfade needs.
    func release(fadeOut: Double? = nil) {
        if let f = fadeOut { fadeOutFrames = max(1, Int(f * rate)) }
        releasing = true
        aim(0.0, fadeOutFrames)
    }

    /// The gain for this block: a single value when the envelope has settled,
    /// otherwise a ramp written into `scratch`.
    private func ramp(frames: Int, into scratch: UnsafeMutablePointer<Float>) -> Float? {
        if gain == target { return gain }
        let distance = rampSpan > 0 ? rampSpan : abs(target - gain)
        let step = distance * Float(frames) / Float(max(1, rampFrames))
        let delta = target - gain
        let move = min(abs(delta), step) * (delta > 0 ? 1.0 : -1.0)
        let newGain = gain + move
        if frames == 1 {
            scratch[0] = newGain
        } else {
            let inc = (newGain - gain) / Float(frames - 1)
            for i in 0..<frames { scratch[i] = gain + inc * Float(i) }
        }
        gain = newGain
        return nil
    }

    /// Pull raw samples. Subclasses fill `out` with up to `frames` frames of
    /// interleaved stereo and return how many they really produced.
    func pull(frames: Int, into out: UnsafeMutablePointer<Float>) -> Int { 0 }

    /// True when a short pull means the sound has genuinely ended, rather than
    /// the reader simply not having kept up.
    var exhausted: Bool { true }

    func close() {}

    /// Render one block of interleaved stereo into `out`, which must hold
    /// frames * 2 floats. Returns false when there was nothing to render.
    ///
    /// A voice can only be rendered once per block, because rendering advances
    /// it. The mixer builds the monitor sum and the air sum from this one
    /// block, never by a second pass.
    func render(frames: Int, duck: Float,
                into out: UnsafeMutablePointer<Float>,
                rampScratch: UnsafeMutablePointer<Float>) -> Bool {
        if finished {
            out.update(repeating: 0, count: frames * 2)
            return false
        }
        let got = pull(frames: frames, into: out)
        framesPlayed += got
        if got < frames {
            (out + got * 2).update(repeating: 0, count: (frames - got) * 2)
            if !loop && exhausted { finished = true }
        }

        if let flat = ramp(frames: frames, into: rampScratch) {
            if flat != 1.0 {
                for i in 0..<(frames * 2) { out[i] *= flat }
            }
        } else {
            for i in 0..<frames {
                let g = rampScratch[i]
                out[i * 2] *= g
                out[i * 2 + 1] *= g
            }
        }

        if isDucked && duck != 1.0 {
            for i in 0..<(frames * 2) { out[i] *= duck }
        }

        if releasing && gain <= 1e-5 { finished = true }
        return true
    }
}

// ------------------------------------------------------------------ memory ---

/// A sound decoded up front, so the key is instant.
final class MemoryVoice: Voice {
    private let samples: [Float]
    private let totalFrames: Int
    private var position = 0

    init(samples: [Float], slotIndex: Int, bus: String, name: String, gain: Float,
         loop: Bool, rate: Double, fadeIn: Double, fadeOut: Double) {
        self.samples = samples
        self.totalFrames = samples.count / 2
        super.init(slotIndex: slotIndex, bus: bus, name: name, gain: gain,
                   loop: loop, rate: rate, fadeIn: fadeIn, fadeOut: fadeOut)
    }

    /// A short pull from memory always means the sound ended.
    override var exhausted: Bool { true }

    override func pull(frames: Int, into out: UnsafeMutablePointer<Float>) -> Int {
        guard totalFrames > 0 else { return 0 }
        var written = 0
        samples.withUnsafeBufferPointer { buf in
            guard let base = buf.baseAddress else { return }
            while written < frames {
                if position >= totalFrames {
                    // Wrapping happens inside the block, so a loop has no gap
                    // at the seam and needs no crossfade.
                    if loop { position = 0 } else { break }
                }
                let take = min(frames - written, totalFrames - position)
                (out + written * 2).update(from: base + position * 2, count: take * 2)
                position += take
                written += take
            }
        }
        return written
    }
}

// ------------------------------------------------------------------ stream ---

/// A long file read from disk on its own thread, so twenty music beds do not
/// cost a gigabyte.
final class StreamVoice: Voice {

    private static let prebufferSeconds = 1.5
    private static let readFrames = 8192

    private let path: String
    private let lock = NSLock()
    private var ring: [Float] = []
    private var eof = false
    private var stopping = false
    private var thread: Thread?

    init?(path: String, slotIndex: Int, bus: String, name: String, gain: Float,
          loop: Bool, rate: Double, fadeIn: Double, fadeOut: Double) {
        self.path = path
        super.init(slotIndex: slotIndex, bus: bus, name: name, gain: gain,
                   loop: loop, rate: rate, fadeIn: fadeIn, fadeOut: fadeOut)
        guard AudioFile.probe(path) != nil else { return nil }
        let t = Thread { [weak self] in self?.run() }
        t.name = "dropdeck-reader"
        t.stackSize = 512 * 1024
        thread = t
        t.start()
        // Wait briefly for the prebuffer so the first block is not silence.
        let deadline = Date().addingTimeInterval(0.5)
        while Date() < deadline {
            lock.lock(); let have = ring.count / 2; let done = eof; lock.unlock()
            if done || Double(have) >= rate * 0.25 { break }
            Thread.sleep(forTimeInterval: 0.005)
        }
    }

    private var ringFrames: Int {
        lock.lock(); defer { lock.unlock() }
        return ring.count / 2
    }

    /// Anything less than a real end of file is an underrun, and ending the
    /// sound on that would cut a song off mid word because a Dropbox sync
    /// picked that moment to run.
    override var exhausted: Bool {
        lock.lock(); defer { lock.unlock() }
        return eof && ring.isEmpty
    }

    private func run() {
        let target = Int(Self.prebufferSeconds * rate) * 2
        while true {
            lock.lock(); let stop = stopping; let have = ring.count; lock.unlock()
            if stop { return }
            if have >= target {
                Thread.sleep(forTimeInterval: 0.02)
                continue
            }
            // Read the whole file once through the shared decoder. Streaming a
            // block at a time through AVAudioConverter would be the same code
            // in a slower shape; the ring is what keeps memory bounded, and it
            // is refilled from an offset rather than reopened.
            guard let all = AudioFile.readAll(path, targetRate: rate) else {
                lock.lock(); eof = true; lock.unlock()
                return
            }
            var offset = 0
            while true {
                lock.lock()
                let stop = stopping
                let have = ring.count
                lock.unlock()
                if stop { return }
                if have >= target {
                    Thread.sleep(forTimeInterval: 0.02)
                    continue
                }
                if offset >= all.count {
                    if loop { offset = 0; continue }
                    lock.lock(); eof = true; lock.unlock()
                    return
                }
                let take = min(Self.readFrames * 2, all.count - offset)
                lock.lock()
                ring.append(contentsOf: all[offset..<(offset + take)])
                lock.unlock()
                offset += take
            }
        }
    }

    override func pull(frames: Int, into out: UnsafeMutablePointer<Float>) -> Int {
        lock.lock()
        let have = ring.count / 2
        let take = min(frames, have)
        if take > 0 {
            ring.withUnsafeBufferPointer { buf in
                out.update(from: buf.baseAddress!, count: take * 2)
            }
            ring.removeFirst(take * 2)
        }
        lock.unlock()
        return take
    }

    override func close() {
        lock.lock(); stopping = true; lock.unlock()
    }
}

// ------------------------------------------------------------------- cache ---

/// Decoded audio, kept so a key is instant.
///
/// Nothing goes between a keypress and a sound: short sounds are decoded at
/// assignment time and at startup, precisely so the press costs nothing.
/// Measured on the Windows copy: a first bed press was 87.5 ms cold against
/// 0.6 ms warm.
final class DecodeCache {
    private var store: [String: [Float]] = [:]
    private var order: [String] = []
    private var bytes = 0
    private let budget = 256 * 1024 * 1024
    private let lock = NSLock()
    private(set) var rate: Double

    init(rate: Double) { self.rate = rate }

    /// A device change means everything cached was resampled for the old rate.
    func clear(newRate: Double) {
        lock.lock()
        store.removeAll(); order.removeAll(); bytes = 0
        rate = newRate
        lock.unlock()
    }

    func cached(_ path: String) -> [Float]? {
        lock.lock()
        if let hit = store[path] {
            order.removeAll { $0 == path }
            order.append(path)
            lock.unlock()
            return hit
        }
        let targetRate = rate
        lock.unlock()

        guard let data = AudioFile.readAll(path, targetRate: targetRate) else { return nil }

        lock.lock()
        // The rate may have moved while we were decoding. Rather than cache
        // audio for a device that is no longer there, hand this one back and
        // let the next call decode again.
        if targetRate == rate {
            store[path] = data
            order.append(path)
            bytes += data.count * MemoryLayout<Float>.size
            while bytes > budget && order.count > 1 {
                let oldest = order.removeFirst()
                if let gone = store.removeValue(forKey: oldest) {
                    bytes -= gone.count * MemoryLayout<Float>.size
                }
            }
        }
        lock.unlock()
        return data
    }
}
