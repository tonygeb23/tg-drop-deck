// The beep before a track ends.
//
// Every cue is generated rather than shipped: no file to lose, nothing to
// license, and every one comes out at the same loudness so changing your mind
// does not change how loud your warning is.
//
// They are deliberately different SHAPES rather than different pitches. Over a
// song, a bell and a sweep are told apart instantly where two tones a third
// apart are not, and a cue you have to think about is a cue that has already
// cost you the moment it was warning you of.

import Foundation

enum CueTone {

    private static var cache: [String: [Float]] = [:]
    private static let lock = NSLock()

    /// Interleaved stereo, the same signal both sides.
    static func waveform(kind: String, levelDB: Float, rate: Double) -> [Float] {
        let key = "\(kind)|\(levelDB)|\(rate)"
        lock.lock()
        if let hit = cache[key] { lock.unlock(); return hit }
        lock.unlock()

        var mono = shape(kind, rate: rate)
        normalise(&mono, levelDB: levelDB, rate: rate)

        var stereo = [Float](repeating: 0, count: mono.count * 2)
        for i in 0..<mono.count {
            stereo[i * 2] = mono[i]
            stereo[i * 2 + 1] = mono[i]
        }
        lock.lock(); cache[key] = stereo; lock.unlock()
        return stereo
    }

    // ------------------------------------------------------------- shaping ---

    private static func tone(_ hz: Double, _ seconds: Double, rate: Double,
                             edge: Double = C.cueToneEdge) -> [Float] {
        let n = max(1, Int(seconds * rate))
        var out = [Float](repeating: 0, count: n)
        let edgeFrames = max(1, Int(edge * rate))
        for i in 0..<n {
            let t = Double(i) / rate
            var v = sin(2.0 * Double.pi * hz * t)
            // Shaped at both ends so it is a pip rather than a click.
            if i < edgeFrames { v *= Double(i) / Double(edgeFrames) }
            if i > n - edgeFrames { v *= Double(n - i) / Double(edgeFrames) }
            out[i] = Float(v)
        }
        return out
    }

    private static func silence(_ seconds: Double, rate: Double) -> [Float] {
        [Float](repeating: 0, count: max(0, Int(seconds * rate)))
    }

    private static func mix(_ a: [Float], _ b: [Float], overlap: Int) -> [Float] {
        let start = max(0, a.count - overlap)
        var out = a
        if out.count < start + b.count {
            out.append(contentsOf: [Float](repeating: 0, count: start + b.count - out.count))
        }
        for i in 0..<b.count { out[start + i] += b[i] }
        return out
    }

    private static func shape(_ kind: String, rate: Double) -> [Float] {
        switch kind {
        case "double":
            return tone(C.cueToneHz, 0.075, rate: rate)
                 + silence(0.075, rate: rate)
                 + tone(C.cueToneHz, 0.075, rate: rate)

        case "chime":
            // Two notes rising, overlapping so it rings rather than steps.
            return mix(tone(880.0, 0.16, rate: rate),
                       tone(1318.5, 0.20, rate: rate),
                       overlap: Int(0.06 * rate))

        case "bell":
            // Inharmonic partials with their own decays, which is what makes a
            // bell a bell rather than a tone with a fade on it.
            let seconds = 0.6
            let n = Int(seconds * rate)
            let base = 1046.5
            let ratios: [Double] = [1.0, 2.0, 2.76, 5.4]
            let weights: [Double] = [1.0, 0.6, 0.4, 0.15]
            let decays: [Double] = [4, 6, 8, 12]
            var out = [Float](repeating: 0, count: n)
            let edge = max(1, Int(0.002 * rate))
            for i in 0..<n {
                let t = Double(i) / rate
                var v = 0.0
                for p in 0..<ratios.count {
                    v += weights[p] * sin(2 * .pi * base * ratios[p] * t) * exp(-decays[p] * t)
                }
                if i < edge { v *= Double(i) / Double(edge) }
                out[i] = Float(v)
            }
            return out

        case "tick":
            var out: [Float] = []
            for i in 0..<3 {
                out += tone(2200.0, 0.022, rate: rate, edge: 0.004)
                if i < 2 { out += silence(0.085, rate: rate) }
            }
            return out

        case "sweep":
            let seconds = 0.22
            let n = Int(seconds * rate)
            var out = [Float](repeating: 0, count: n)
            let edge = max(1, Int(0.008 * rate))
            var phase = 0.0
            for i in 0..<n {
                let progress = Double(i) / Double(n)
                let hz = 600.0 + (1600.0 - 600.0) * progress
                phase += 2 * .pi * hz / rate
                var v = sin(phase)
                if i < edge { v *= Double(i) / Double(edge) }
                if i > n - edge { v *= Double(n - i) / Double(edge) }
                out[i] = Float(v)
            }
            return out

        default:
            // Anything unknown falls back to the pip rather than to silence: a
            // cue that does not sound is worse than the wrong cue.
            return tone(C.cueToneHz, C.cueToneSeconds, rate: rate)
        }
    }

    // ---------------------------------------------------------- the loudness ---

    /// Matched by window RMS, not by peak.
    ///
    /// A bell and a steady pip at the same peak are not the same loudness: the
    /// bell decays, so most of it is quiet, and peak matching left it about ten
    /// decibels down in energy and easy to miss over a song.
    private static func normalise(_ samples: inout [Float], levelDB: Float, rate: Double) {
        guard !samples.isEmpty else { return }
        let window = max(1, Int(0.03 * rate))
        var loudest: Double = 0
        var i = 0
        while i < samples.count {
            let end = min(i + window, samples.count)
            var sum = 0.0
            for j in i..<end { sum += Double(samples[j]) * Double(samples[j]) }
            let rms = (sum / Double(end - i)).squareRoot()
            loudest = max(loudest, rms)
            i = end
        }
        guard loudest > 1e-9 else { return }

        let level = Double(dbToGain(levelDB))
        var gain = (level / 2.0.squareRoot()) / loudest

        // And backed off so the peak never goes over minus one decibel,
        // whatever the shape does.
        let ceiling = 0.891251
        var peak: Double = 0
        for s in samples { peak = max(peak, abs(Double(s))) }
        if peak * gain > ceiling { gain = ceiling / peak }

        for j in samples.indices { samples[j] = Float(Double(samples[j]) * gain) }
    }
}
