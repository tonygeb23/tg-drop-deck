// What the camera can see, said out loud, without becoming a commentary.
//
// Mirrors dropdeck/framing.py: the same bands, the same hysteresis, the same
// sentences, the same anti-repetition rule. What differs is the detector.
// Windows loads a YuNet model through OpenCV and ships both; the Vision
// framework is already in the process here, so the Mac ships neither and gets
// a better detector.
//
// One consequence worth stating, because it removes a branch rather than
// adding one. On Windows the whole feature can be UNAVAILABLE, when the wheel
// failed to install or the model file is missing, and there is an error path
// through every function for it. Vision cannot be missing from a Mac, so
// framing here either has an answer or has not looked yet.
//
// **It says changes, not states.** At the most talkative setting, six seconds
// in front of a camera produced one sentence. A running commentary on your own
// face while you are trying to present a show is worse than silence, which is
// why there are three levels and why the floor between announcements exists.

import Foundation
import Vision
import CoreVideo

/// What the camera can see, in words rather than numbers.
struct FramingReading {
    var found = false
    var horizontal = ""
    var vertical = ""
    var distance = ""
    var light = ""
    var centreX = 0.0
    var centreY = 0.0
    var size = 0.0
    var luminance = 0.0
    var confidence = 0.0

    /// What has to change before anything is worth saying again.
    var key: String {
        "\(found)|\(horizontal)|\(vertical)|\(distance)|\(light)"
    }

    /// A shot nobody needs to be told about.
    var good: Bool {
        found && horizontal == "centred" && vertical == "centred"
            && distance != "far away" && light != "dark"
    }

    /// The whole reading, for the key that answers on demand.
    func sentence() -> String {
        if !found {
            return light == "dark" ? "No face in shot, and the picture is dark"
                                   : "No face in shot"
        }
        var parts: [String] = []
        if horizontal == "centred" && vertical == "centred" {
            parts.append("centred")
        } else {
            if horizontal != "centred" { parts.append(horizontal) }
            if vertical != "centred" { parts.append(vertical) }
        }
        parts.append(distance)
        parts.append(light)
        let joined = parts.filter { !$0.isEmpty }.joined(separator: ", ")
        // Python's str.capitalize lowercases the rest, and every band here is
        // already lower case, so the two agree.
        guard let first = joined.first else { return joined }
        return String(first).uppercased() + joined.dropFirst().lowercased()
    }

    /// The one thing worth interrupting for, or nothing.
    func problem() -> String {
        if !found { return "No face in shot" }
        if light == "dark" { return "The picture is dark" }
        if horizontal != "centred" { return capitalised(horizontal) }
        if vertical != "centred" { return capitalised(vertical) }
        if distance == "far away" { return "Far away from the camera" }
        return ""
    }

    private func capitalised(_ s: String) -> String {
        guard let first = s.first else { return s }
        return String(first).uppercased() + s.dropFirst().lowercased()
    }
}

/// Looks at frames and says what changed.
final class Framer {

    var level: String
    var onSay: (String) -> Void
    var clock: () -> Double

    private let lock = NSLock()
    private(set) var reading = FramingReading()
    private(set) var checks = 0
    private(set) var error = ""
    private var saidKey: String?
    private var saidAt: Double = 0
    private var lastLook: Double = 0

    init(level: String = C.framingProblems,
         onSay: @escaping (String) -> Void = { _ in },
         clock: @escaping () -> Double = { ProcessInfo.processInfo.systemUptime }) {
        self.level = C.framingLevels.contains(level) ? level : C.framingProblems
        self.onSay = onSay
        self.clock = clock
    }

    /// Whether it is time to look again. Cheap, so it can be asked often.
    func due() -> Bool { (clock() - lastLook) >= C.faceCheckSeconds }

    /// Analyse one frame and speak if anything changed.
    @discardableResult
    func look(_ buffer: CVPixelBuffer) -> FramingReading {
        lastLook = clock()
        let made = measure(buffer)
        lock.lock(); reading = made; lock.unlock()
        maybeSay(made)
        return made
    }

    /// One reading, with no speech and no state. Safe to call anywhere.
    func measure(_ buffer: CVPixelBuffer) -> FramingReading {
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        guard width >= 2, height >= 2 else { return FramingReading() }

        let luminance = Framer.brightness(buffer)
        let light = luminance < C.faceDarkBelow ? "dark" : "well lit"

        let request = VNDetectFaceRectanglesRequest()
        let handler = VNImageRequestHandler(cvPixelBuffer: buffer, options: [:])
        do {
            try handler.perform([request])
        } catch {
            // A detector that fails must never take the show down. No reading
            // is a fine answer; a stopped stream is not.
            return FramingReading(light: light, luminance: luminance)
        }
        lock.lock(); checks += 1; lock.unlock()

        // The biggest face, which is the presenter. Anyone in the background
        // is smaller and is not who this is for.
        let faces = (request.results ?? []).filter { Double($0.confidence) >= C.faceConfidence }
        guard let face = faces.max(by: { $0.boundingBox.width * $0.boundingBox.height
                                       < $1.boundingBox.width * $1.boundingBox.height })
        else {
            return FramingReading(light: light, luminance: luminance)
        }

        // Vision's box is in a coordinate space with the origin at the BOTTOM
        // left and everything as a fraction of the image. The bands are
        // written the way a person describes a picture, from the top, so the
        // vertical is flipped here rather than in the bands.
        let box = face.boundingBox
        let centreX = Double(box.midX)
        let centreY = 1.0 - Double(box.midY)
        let size = Double(box.width)

        let previous = reading
        let horizontal = Framer.band(centreX, C.faceLeftEdge, C.faceRightEdge,
                                     "left of shot", "centred", "right of shot",
                                     previous.horizontal, C.faceHysteresis)
        let vertical = Framer.band(centreY, C.faceTopEdge, C.faceBottomEdge,
                                   "high in shot", "centred", "low in shot",
                                   previous.vertical, C.faceHysteresis)
        let distance = Framer.band(size, C.faceFarBelow, C.faceCloseAbove,
                                   "far away", "a good distance", "very close",
                                   previous.distance, C.faceSizeHysteresis)
        return FramingReading(found: true, horizontal: horizontal, vertical: vertical,
                              distance: distance, light: light, centreX: centreX,
                              centreY: centreY, size: size, luminance: luminance,
                              confidence: Double(face.confidence))
    }

    /// One reading with hysteresis, so a wobble does not flip the answer.
    ///
    /// Coming OUT of a state needs `margin` more than going in did. Without it
    /// a face resting on a boundary changes the answer several times a second,
    /// and the announcement floor then hides real changes behind fake ones.
    static func band(_ value: Double, _ low: Double, _ high: Double,
                     _ below: String, _ middle: String, _ above: String,
                     _ previous: String = "", _ margin: Double = 0) -> String {
        var lo = low, hi = high
        if previous == below { lo = low + margin }
        else if previous == above { hi = high - margin }
        else if previous == middle { lo = low - margin; hi = high + margin }
        if value < lo { return below }
        if value > hi { return above }
        return middle
    }

    /// The mean level of a frame, over the same subsample Windows takes.
    static func brightness(_ buffer: CVPixelBuffer) -> Double {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer)?
                .assumingMemoryBound(to: UInt8.self) else { return 0 }
        let w = CVPixelBufferGetWidth(buffer), h = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        var total = 0, n = 0
        for y in Swift.stride(from: 0, to: h, by: 8) {
            for x in Swift.stride(from: 0, to: w, by: 8) {
                let p = base + y * stride + x * 4
                // BGRA, and the alpha is not part of how bright anything is.
                total += Int(p[0]) + Int(p[1]) + Int(p[2])
                n += 3
            }
        }
        return n > 0 ? Double(total) / Double(n) : 0
    }

    // ----------------------------------------------------------- speech ---

    /// Run the announcement rule over a reading, without a camera.
    ///
    /// Public because the checks drive it directly: the rule is the part a
    /// presenter actually experiences, and it is worth being able to test it
    /// against a scripted minute rather than against a face.
    func announce(_ reading: FramingReading) { maybeSay(reading) }

    /// Record a reading as the current one, without announcing it.
    func remember(_ reading: FramingReading) {
        lock.lock(); self.reading = reading; lock.unlock()
    }

    private func maybeSay(_ reading: FramingReading) {
        if level == C.framingOff { saidKey = reading.key; return }
        if reading.key == saidKey { return }
        let now = clock()
        let first = saidKey == nil
        if !first && (now - saidAt) < C.faceSayFloor {
            // Too soon. The key is deliberately NOT recorded, so the change is
            // still pending and gets said once the floor has passed rather
            // than being lost.
            return
        }
        let text = words(reading, first: first)
        saidKey = reading.key
        if text.isEmpty { return }
        saidAt = now
        onSay(text)
    }

    private func words(_ reading: FramingReading, first: Bool) -> String {
        if level == C.framingEverything { return reading.sentence() }
        // Problems only: speak a fault, and speak recovery ONCE, because "you
        // are back in shot" is the other half of "you have gone".
        let problem = reading.problem()
        if !problem.isEmpty { return problem }
        if first { return "" }
        return reading.found ? "Back in shot" : ""
    }

    /// Always answers, at every level, including off.
    ///
    /// This is the key a presenter actually uses, and a switch that silences
    /// the announcements must not silence the answer to a direct question.
    func describe() -> String {
        if !error.isEmpty { return error }
        lock.lock()
        let made = reading
        let count = checks
        lock.unlock()
        if count == 0 { return "The camera has not been looked at yet" }
        return made.sentence()
    }

    /// Forget what was said, so a new shot starts clean.
    func reset() {
        lock.lock(); reading = FramingReading(); lock.unlock()
        saidKey = nil
        saidAt = 0
    }
}
