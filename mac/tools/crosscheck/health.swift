import Foundation

let W = 64, H = 36

/// numpy's RandomState(seed).randint(-20, 21, shape), reimplemented so both
/// copies see the SAME pixels. Mersenne Twister, and numpy's own bounded
/// integer draw (Lemire rejection over a masked range).
final class NumpyRandom {
    private var mt = [UInt32](repeating: 0, count: 624)
    private var index = 625
    init(seed: UInt32) {
        mt[0] = seed
        for i in 1..<624 {
            mt[i] = 1812433253 &* (mt[i - 1] ^ (mt[i - 1] >> 30)) &+ UInt32(i)
        }
        index = 624
    }
    private func generate() {
        for i in 0..<624 {
            let y = (mt[i] & 0x8000_0000) | (mt[(i + 1) % 624] & 0x7fff_ffff)
            var next = mt[(i + 397) % 624] ^ (y >> 1)
            if y & 1 != 0 { next ^= 2567483615 }
            mt[i] = next
        }
        index = 0
    }
    func uint32() -> UInt32 {
        if index >= 624 { generate() }
        var y = mt[index]; index += 1
        y ^= y >> 11
        y ^= (y << 7) & 2636928640
        y ^= (y << 15) & 4022730752
        y ^= y >> 18
        return y
    }
    /// numpy's rk_random_uint32 bounded draw: mask to the next power of two
    /// and reject anything over the range.
    func bounded(_ range: UInt32) -> UInt32 {
        var mask = range
        mask |= mask >> 1; mask |= mask >> 2; mask |= mask >> 4
        mask |= mask >> 8; mask |= mask >> 16
        while true {
            let value = uint32() & mask
            if value <= range { return value }
        }
    }
}

func frame(_ level: Int, seed: UInt32? = nil) -> [UInt8] {
    var a = [UInt8](repeating: UInt8(level), count: W * H * 3)
    if let seed {
        let rng = NumpyRandom(seed: seed)
        for i in 0..<a.count {
            let delta = Int(rng.bounded(40)) - 20
            a[i] = UInt8(max(0, min(255, level + delta)))
        }
    }
    return a
}

var script: [(frame: [UInt8], moving: Bool, when: Double)] = []
var t = 0.0
for i in 0..<6 { script.append((frame(120, seed: UInt32(i)), true, t + Double(i) * 0.5)) }
t = 3.0
for i in 0..<30 { script.append((frame(1), true, t + Double(i) * 0.5)) }
t = 18.0
for i in 0..<30 { script.append((frame(120, seed: UInt32(100 + i)), true, t + Double(i) * 0.5)) }
t = 33.0
for i in 0..<40 { script.append((frame(120, seed: 7), true, t + Double(i) * 0.5)) }
t = 53.0
for i in 0..<60 { script.append((frame(120, seed: UInt32(200 + i)), true, t + Double(i) * 1.5)) }
t = 143.0
for i in 0..<20 { script.append((frame(120, seed: 7), false, t + Double(i) * 0.5)) }
t = 153.0
for i in 0..<20 { script.append((frame(2), false, t + Double(i) * 0.5)) }

let w = HealthWatcher()
var out: [String] = []
for (n, step) in script.enumerated() {
    let said = w.look(frame: step.frame, width: W, height: H,
                      moving: step.moving, now: step.when)
    out.append("look|\(n)|\(String(format: "%.2f", step.when))|"
             + "\(step.moving ? "True" : "False")|\(w.state.rawValue)|\(w.describe())|\(said)")
}
out.append("frames|\(w.frames)")
w.reset()
out.append("reset|\(w.state.rawValue)|\(w.describe())")
out.append("empty|\(w.look(frame: [], width: 0, height: 0, now: 200.0))")
print(out.joined(separator: "\n"))
