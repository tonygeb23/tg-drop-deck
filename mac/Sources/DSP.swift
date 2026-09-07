// The voice chain: a gate, a high pass, a three band equaliser, a compressor
// and a ceiling, in that order.
//
// The order is not arbitrary. Gate first, so the compressor is not busy
// pulling up room noise between words. High pass next, because rumble and
// plosives are energy the compressor would otherwise react to. Equaliser
// before the compressor, so the compressor responds to the voice you have
// shaped rather than the one you have not. Limiter last, always last, because
// its entire job is to be the final word on how loud anything gets.
//
// The Windows copy hands the first four to pedalboard, which is JUCE, and hand
// writes only the ceiling. This build hand writes all of it, and that is a
// measured decision rather than a preference:
//
//   Apple's kAudioUnitSubType_DynamicsProcessor has SEVEN parameters and a
//   compression RATIO is not among them: the curve is implied by threshold
//   plus headroom. "Four to one at minus eighteen" cannot be dialled into it.
//   Its expander shares the compressor's attack and release and has no hold,
//   so it is not a broadcast gate either.
//
//   Apple's kAudioUnitSubType_PeakLimiter has no threshold and no ceiling at
//   all. It limits at full scale and you drive it with pre-gain. "Never louder
//   than minus one" has to be a promise, not an approximation.
//
// So the whole chain is here, it is real time safe, and every number in it is
// the number the Windows copy uses.

import Foundation

/// One knob, described well enough to be a row in a list.
///
/// A plugin whose own window no screen reader can read becomes a list any
/// screen reader can, and the app's own chain is described the same way so the
/// two read alike.
struct DSPParameter {
    let key: String
    let group: String
    let label: String
    let minimum: Double
    let maximum: Double
    let step: Double
    let unit: String
    /// A switch is a parameter with two named values rather than a special case.
    let choices: [String]?

    init(_ key: String, group: String, label: String,
         min minimum: Double, max maximum: Double, step: Double,
         unit: String, choices: [String]? = nil) {
        self.key = key
        self.group = group
        self.label = label
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.unit = unit
        self.choices = choices
    }

    /// What the row says out loud, with a real unit rather than a bare number.
    func spoken(_ value: Double) -> String {
        if let choices {
            let index = min(choices.count - 1, max(0, Int(value.rounded())))
            return "\(label), \(choices[index])"
        }
        switch unit {
        case "dB":
            return String(format: "%@, %+.1f decibels", label, value)
        case "Hz":
            return value >= 1000
                ? String(format: "%@, %.1f kilohertz", label, value / 1000)
                : String(format: "%@, %.0f hertz", label, value)
        case "ms":
            return String(format: "%@, %.0f milliseconds", label, value)
        case "ratio":
            return String(format: "%@, %.1f to 1", label, value)
        default:
            return String(format: "%@, %.2f", label, value)
        }
    }
}

// ------------------------------------------------------------------ biquad ---

/// One second order section. Direct form one, transposed, which is the form
/// that keeps its head at low frequencies in single precision.
private struct Biquad {
    var b0: Float = 1, b1: Float = 0, b2: Float = 0, a1: Float = 0, a2: Float = 0
    var z1: Float = 0, z2: Float = 0

    mutating func reset() { z1 = 0; z2 = 0 }

    @inline(__always)
    mutating func process(_ x: Float) -> Float {
        let y = b0 * x + z1
        z1 = b1 * x - a1 * y + z2
        z2 = b2 * x - a2 * y
        return y
    }

    mutating func highPass(hz: Double, q: Double, rate: Double) {
        let w = 2.0 * Double.pi * max(10.0, min(hz, rate * 0.45)) / rate
        let alpha = sin(w) / (2.0 * q)
        let cosw = cos(w)
        let a0 = 1 + alpha
        b0 = Float((1 + cosw) / 2 / a0)
        b1 = Float(-(1 + cosw) / a0)
        b2 = b0
        a1 = Float(-2 * cosw / a0)
        a2 = Float((1 - alpha) / a0)
    }

    mutating func lowShelf(hz: Double, gainDB: Double, rate: Double) {
        let a = pow(10.0, gainDB / 40.0)
        let w = 2.0 * Double.pi * max(10.0, min(hz, rate * 0.45)) / rate
        let cosw = cos(w), sinw = sin(w)
        let alpha = sinw / 2 * sqrt((a + 1 / a) * (1 / 0.9 - 1) + 2)
        let twoSqrtAAlpha = 2 * sqrt(a) * alpha
        let a0 = (a + 1) + (a - 1) * cosw + twoSqrtAAlpha
        b0 = Float(a * ((a + 1) - (a - 1) * cosw + twoSqrtAAlpha) / a0)
        b1 = Float(2 * a * ((a - 1) - (a + 1) * cosw) / a0)
        b2 = Float(a * ((a + 1) - (a - 1) * cosw - twoSqrtAAlpha) / a0)
        a1 = Float(-2 * ((a - 1) + (a + 1) * cosw) / a0)
        a2 = Float(((a + 1) + (a - 1) * cosw - twoSqrtAAlpha) / a0)
    }

    mutating func highShelf(hz: Double, gainDB: Double, rate: Double) {
        let a = pow(10.0, gainDB / 40.0)
        let w = 2.0 * Double.pi * max(10.0, min(hz, rate * 0.45)) / rate
        let cosw = cos(w), sinw = sin(w)
        let alpha = sinw / 2 * sqrt((a + 1 / a) * (1 / 0.9 - 1) + 2)
        let twoSqrtAAlpha = 2 * sqrt(a) * alpha
        let a0 = (a + 1) - (a - 1) * cosw + twoSqrtAAlpha
        b0 = Float(a * ((a + 1) + (a - 1) * cosw + twoSqrtAAlpha) / a0)
        b1 = Float(-2 * a * ((a - 1) + (a + 1) * cosw) / a0)
        b2 = Float(a * ((a + 1) + (a - 1) * cosw - twoSqrtAAlpha) / a0)
        a1 = Float(2 * ((a - 1) - (a + 1) * cosw) / a0)
        a2 = Float(((a + 1) - (a - 1) * cosw - twoSqrtAAlpha) / a0)
    }

    mutating func peak(hz: Double, gainDB: Double, q: Double, rate: Double) {
        let a = pow(10.0, gainDB / 40.0)
        let w = 2.0 * Double.pi * max(10.0, min(hz, rate * 0.45)) / rate
        let alpha = sin(w) / (2.0 * max(0.05, q))
        let cosw = cos(w)
        let a0 = 1 + alpha / a
        b0 = Float((1 + alpha * a) / a0)
        b1 = Float(-2 * cosw / a0)
        b2 = Float((1 - alpha * a) / a0)
        a1 = Float(-2 * cosw / a0)
        a2 = Float((1 - alpha / a) / a0)
    }
}

// ------------------------------------------------------------------ ceiling ---

/// The limiter, and the reason it is written by hand.
///
/// Zero lookahead, zero latency, instantaneous attack, and a release that is
/// exponential in decibels. Latency matters here more than transparency: the
/// presenter is listening to themselves, and a few milliseconds of delay
/// against bone conduction sounds like a barrel.
///
/// This is a SAMPLE peak ceiling, not an inter sample true peak one. There is
/// no oversampling. Reaching for an oversampled limiter would change the sound
/// and is not what the Windows copy does.
final class Ceiling {
    var ceilingDB: Double = -1.0
    var releaseMS: Double = 100.0
    private var gainDB: Double = 0
    private var rate: Double = C.defaultSampleRate

    func prepare(rate: Double) {
        self.rate = rate
        gainDB = 0
    }

    /// In place, on interleaved stereo. The same gain is applied to both
    /// channels so the image cannot wander under a loud syllable.
    func process(_ block: UnsafeMutablePointer<Float>, frames: Int) {
        let ceiling = pow(10.0, ceilingDB / 20.0)
        // The release recovers twenty decibels in releaseMS.
        let rise = 20.0 / max(1.0, releaseMS * 0.001 * rate)
        for i in 0..<frames {
            let peak = Double(max(abs(block[i * 2]), abs(block[i * 2 + 1])))
            let target = min(0.0, -20.0 * log10(max(peak, 1e-12) / ceiling))
            // g[n] = min(target[n], g[n-1] + rise). Instant down, eased up.
            gainDB = min(target, gainDB + rise)
            if gainDB < 0 {
                let g = Float(pow(10.0, gainDB / 20.0))
                block[i * 2] *= g
                block[i * 2 + 1] *= g
            }
        }
    }
}

// -------------------------------------------------------------- the chain ---

final class MicChain {

    static let defaults: [String: Double] = [
        "gate_on": 1, "gate_threshold": -45, "gate_ratio": 6,
        "gate_attack": 1, "gate_release": 120,
        "highpass_on": 1, "highpass_hz": 80,
        "eq_on": 1, "eq_low_hz": 200, "eq_low_db": 0,
        "eq_mid_hz": 1800, "eq_mid_db": 0, "eq_mid_q": 1.0,
        "eq_high_hz": 6000, "eq_high_db": 0,
        "comp_on": 1, "comp_threshold": -20, "comp_ratio": 3,
        "comp_attack": 8, "comp_release": 140, "comp_makeup": 4,
        "limit_on": 1, "limit_ceiling": -1, "limit_release": 100,
    ]

    /// The order the accessible list offers them in: gate, equaliser,
    /// compressor, ceiling. Chosen for a spoken voice on a normal microphone,
    /// not for a mastering chain. Gentle enough that switching it on is an
    /// improvement rather than an effect.
    static let parameters: [DSPParameter] = [
        DSPParameter("gate_on", group: "Noise gate", label: "Noise gate",
                     min: 0, max: 1, step: 1, unit: "", choices: ["off", "on"]),
        DSPParameter("gate_threshold", group: "Noise gate", label: "Gate opens above",
                     min: -80, max: 0, step: 1, unit: "dB"),
        DSPParameter("gate_ratio", group: "Noise gate", label: "Gate depth",
                     min: 1, max: 20, step: 0.5, unit: "ratio"),
        DSPParameter("gate_attack", group: "Noise gate", label: "Gate attack",
                     min: 0.1, max: 50, step: 0.5, unit: "ms"),
        DSPParameter("gate_release", group: "Noise gate", label: "Gate release",
                     min: 5, max: 1000, step: 10, unit: "ms"),

        DSPParameter("highpass_on", group: "High pass filter", label: "High pass filter",
                     min: 0, max: 1, step: 1, unit: "", choices: ["off", "on"]),
        DSPParameter("highpass_hz", group: "High pass filter", label: "High pass at",
                     min: 20, max: 400, step: 5, unit: "Hz"),

        DSPParameter("eq_on", group: "Equaliser", label: "Equaliser",
                     min: 0, max: 1, step: 1, unit: "", choices: ["off", "on"]),
        DSPParameter("eq_low_hz", group: "Equaliser", label: "Low shelf at",
                     min: 40, max: 600, step: 10, unit: "Hz"),
        DSPParameter("eq_low_db", group: "Equaliser", label: "Low shelf gain",
                     min: -18, max: 18, step: 0.5, unit: "dB"),
        DSPParameter("eq_mid_hz", group: "Equaliser", label: "Middle at",
                     min: 200, max: 8000, step: 50, unit: "Hz"),
        DSPParameter("eq_mid_db", group: "Equaliser", label: "Middle gain",
                     min: -18, max: 18, step: 0.5, unit: "dB"),
        DSPParameter("eq_mid_q", group: "Equaliser", label: "Middle width",
                     min: 0.2, max: 8, step: 0.1, unit: "Q"),
        DSPParameter("eq_high_hz", group: "Equaliser", label: "High shelf at",
                     min: 1500, max: 16000, step: 250, unit: "Hz"),
        DSPParameter("eq_high_db", group: "Equaliser", label: "High shelf gain",
                     min: -18, max: 18, step: 0.5, unit: "dB"),

        DSPParameter("comp_on", group: "Compressor", label: "Compressor",
                     min: 0, max: 1, step: 1, unit: "", choices: ["off", "on"]),
        DSPParameter("comp_threshold", group: "Compressor", label: "Compress above",
                     min: -60, max: 0, step: 1, unit: "dB"),
        DSPParameter("comp_ratio", group: "Compressor", label: "Compression ratio",
                     min: 1, max: 20, step: 0.5, unit: "ratio"),
        DSPParameter("comp_attack", group: "Compressor", label: "Compressor attack",
                     min: 0.1, max: 100, step: 1, unit: "ms"),
        DSPParameter("comp_release", group: "Compressor", label: "Compressor release",
                     min: 10, max: 2000, step: 10, unit: "ms"),
        DSPParameter("comp_makeup", group: "Compressor", label: "Make up gain",
                     min: 0, max: 24, step: 0.5, unit: "dB"),

        DSPParameter("limit_on", group: "Ceiling", label: "Limiter",
                     min: 0, max: 1, step: 1, unit: "", choices: ["off", "on"]),
        DSPParameter("limit_ceiling", group: "Ceiling", label: "Never louder than",
                     min: -12, max: 0, step: 0.5, unit: "dB"),
        DSPParameter("limit_release", group: "Ceiling", label: "Limiter release",
                     min: 10, max: 1000, step: 10, unit: "ms"),
    ]

    static func parameter(_ key: String) -> DSPParameter? {
        parameters.first { $0.key == key }
    }

    private var values: [String: Double] = MicChain.defaults
    private let lock = NSRecursiveLock()
    private var rate: Double = C.defaultSampleRate

    // Filters, one per channel.
    private var highpass = [Biquad(), Biquad()]
    private var lowShelf = [Biquad(), Biquad()]
    private var midPeak = [Biquad(), Biquad()]
    private var highShelf = [Biquad(), Biquad()]

    // Envelope followers, shared across the pair so the image does not wander.
    private var gateEnvelope: Double = 0
    private var gateGain: Double = 1
    private var compEnvelope: Double = 0
    private var compGainDB: Double = 0
    private let ceiling = Ceiling()

    /// Measured from the block rather than asked of anything, because a hand
    /// written compressor is the only thing that could answer and the answer a
    /// user wants is what the whole chain did.
    private(set) var gainReductionDB: Double = 0

    init() { rebuild() }

    func prepare(rate: Double) {
        lock.lock()
        self.rate = rate
        ceiling.prepare(rate: rate)
        for i in 0..<2 {
            highpass[i].reset(); lowShelf[i].reset()
            midPeak[i].reset(); highShelf[i].reset()
        }
        rebuild()
        lock.unlock()
    }

    func value(_ key: String) -> Double {
        lock.lock(); defer { lock.unlock() }
        return values[key] ?? MicChain.defaults[key] ?? 0
    }

    func set(_ key: String, _ value: Double) {
        guard let p = MicChain.parameter(key) else { return }
        let clamped = min(p.maximum, max(p.minimum, value))
        lock.lock()
        values[key] = clamped
        rebuild()
        lock.unlock()
    }

    var settings: [String: Double] {
        get { lock.lock(); defer { lock.unlock() }; return values }
        set {
            lock.lock()
            for (k, v) in newValue where MicChain.parameter(k) != nil {
                if let p = MicChain.parameter(k) {
                    values[k] = min(p.maximum, max(p.minimum, v))
                }
            }
            rebuild()
            lock.unlock()
        }
    }

    /// Recompute the filter coefficients. Cheap, and only the coefficients:
    /// nothing here reallocates and nothing resets an envelope, so a knob can
    /// be moved while the microphone is open without a click.
    private func rebuild() {
        let v = { (k: String) in self.values[k] ?? MicChain.defaults[k] ?? 0 }
        for i in 0..<2 {
            highpass[i].highPass(hz: v("highpass_hz"), q: 0.707, rate: rate)
            lowShelf[i].lowShelf(hz: v("eq_low_hz"), gainDB: v("eq_low_db"), rate: rate)
            midPeak[i].peak(hz: v("eq_mid_hz"), gainDB: v("eq_mid_db"),
                            q: v("eq_mid_q"), rate: rate)
            highShelf[i].highShelf(hz: v("eq_high_hz"), gainDB: v("eq_high_db"), rate: rate)
        }
        ceiling.ceilingDB = v("limit_ceiling")
        ceiling.releaseMS = v("limit_release")
    }

    @inline(__always)
    private static func coefficient(_ ms: Double, _ rate: Double) -> Double {
        // The usual one pole time constant: reach 1 - 1/e in ms milliseconds.
        ms <= 0 ? 0 : exp(-1.0 / (ms * 0.001 * rate))
    }

    /// In place, on interleaved stereo. Never throws, never allocates, and
    /// refuses to change the length of what it was given.
    func process(_ block: UnsafeMutablePointer<Float>, frames: Int) {
        lock.lock()
        defer { lock.unlock() }

        let v = { (k: String) in self.values[k] ?? MicChain.defaults[k] ?? 0 }
        let gateOn = v("gate_on") >= 0.5
        let hpOn = v("highpass_on") >= 0.5
        let eqOn = v("eq_on") >= 0.5
        let compOn = v("comp_on") >= 0.5
        let limitOn = v("limit_on") >= 0.5

        var before: Float = 0
        for i in 0..<(frames * 2) { before = max(before, abs(block[i])) }

        // ------------------------------------------------------------ gate --
        if gateOn {
            let threshold = pow(10.0, v("gate_threshold") / 20.0)
            let ratio = max(1.0, v("gate_ratio"))
            let attack = MicChain.coefficient(v("gate_attack"), rate)
            let release = MicChain.coefficient(v("gate_release"), rate)
            for i in 0..<frames {
                let level = Double(max(abs(block[i * 2]), abs(block[i * 2 + 1])))
                // A peak follower with separate attack and release, so a
                // consonant opens it and a pause does not slam it shut.
                gateEnvelope = level > gateEnvelope
                    ? level + (gateEnvelope - level) * attack
                    : level + (gateEnvelope - level) * release
                var target = 1.0
                if gateEnvelope < threshold {
                    let under = 20 * log10(max(gateEnvelope, 1e-9) / threshold)
                    target = pow(10.0, (under * (ratio - 1) / ratio) / 20.0)
                }
                gateGain = target < gateGain
                    ? target + (gateGain - target) * release
                    : target + (gateGain - target) * attack
                let g = Float(gateGain)
                block[i * 2] *= g
                block[i * 2 + 1] *= g
            }
        }

        // ------------------------------------------------------- high pass --
        if hpOn {
            for i in 0..<frames {
                block[i * 2] = highpass[0].process(block[i * 2])
                block[i * 2 + 1] = highpass[1].process(block[i * 2 + 1])
            }
        }

        // ------------------------------------------------------- equaliser --
        if eqOn {
            for i in 0..<frames {
                var l = block[i * 2], r = block[i * 2 + 1]
                l = lowShelf[0].process(l); r = lowShelf[1].process(r)
                l = midPeak[0].process(l); r = midPeak[1].process(r)
                l = highShelf[0].process(l); r = highShelf[1].process(r)
                block[i * 2] = l
                block[i * 2 + 1] = r
            }
        }

        // ------------------------------------------------------ compressor --
        if compOn {
            let thresholdDB = v("comp_threshold")
            let ratio = max(1.0, v("comp_ratio"))
            let attack = MicChain.coefficient(v("comp_attack"), rate)
            let release = MicChain.coefficient(v("comp_release"), rate)
            let makeup = Float(pow(10.0, v("comp_makeup") / 20.0))
            for i in 0..<frames {
                let level = Double(max(abs(block[i * 2]), abs(block[i * 2 + 1])))
                compEnvelope = level > compEnvelope
                    ? level + (compEnvelope - level) * attack
                    : level + (compEnvelope - level) * release
                let levelDB = 20 * log10(max(compEnvelope, 1e-9))
                var wanted = 0.0
                if levelDB > thresholdDB {
                    wanted = -(levelDB - thresholdDB) * (1.0 - 1.0 / ratio)
                }
                // Smoothed in decibels, which is what makes a ratio mean what
                // it says.
                compGainDB = wanted < compGainDB
                    ? wanted + (compGainDB - wanted) * attack
                    : wanted + (compGainDB - wanted) * release
                let g = Float(pow(10.0, compGainDB / 20.0)) * makeup
                block[i * 2] *= g
                block[i * 2 + 1] *= g
            }
        }

        // --------------------------------------------------------- ceiling --
        if limitOn { ceiling.process(block, frames: frames) }

        var after: Float = 0
        for i in 0..<(frames * 2) { after = max(after, abs(block[i])) }
        if before > 1e-5 && after > 1e-9 {
            gainReductionDB = max(0, 20 * log10(Double(before / after)))
        }
    }
}
