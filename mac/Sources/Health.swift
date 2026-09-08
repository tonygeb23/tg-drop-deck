// Noticing that the picture has died, and saying so.
//
// A deliberate mirror of dropdeck/health.py, including its numbers and its
// exact wording. `mac/tools/cross_check.py` proves the two agree.
//
// **OBS has never had this.** People have asked for it on their forums for
// years, it is a standard metric in professional broadcast infrastructure
// because the arithmetic is trivial, and no desktop encoder speaks it. For a
// presenter who cannot look at a preview it is the difference between a bad
// minute and a bad show: a camera that unplugs, a screen that goes black when
// the machine locks, a capture that freezes on one frame. All three look
// perfectly fine from where you are sitting, and all three are obvious to
// anybody watching.
//
// It is nearly free because the frame is already in our hands. The video pump
// has the pixels a moment before it hands them to the encoder, so this is two
// reductions over a subsample of something already in cache.
//
// ## Why it is careful rather than eager
//
// **A still card is legitimately frozen** and a dark card is legitimately
// dark, so a naive check would announce a fault on the app's own default
// picture, every time, for ever. Two things stop that: the caller says whether
// this source is supposed to be moving, and nothing is said until a fault has
// lasted `C.healthPatience` seconds. A camera blinks. A dead camera does not
// come back.
//
// The same anti-repetition rule the framing announcements follow: say changes,
// not states, and put a floor between them.

import Foundation
import CoreVideo

/// What the watcher can conclude.
enum PictureHealth: String {
    case ok = "ok"
    case black = "black"
    case frozen = "frozen"
}

/// Watches the frames going out, and says when they stop being a picture.
///
/// One instance per broadcast. `look` is called with the frame that is about
/// to be encoded and returns something to say, or "".
final class HealthWatcher {

    /// Told what to say. The caller decides whether that is speech, a status
    /// line or both, exactly as on Windows.
    var onSay: ((String) -> Void)?

    private(set) var state: PictureHealth = .ok
    private(set) var frames = 0

    private var last: [Int32]?
    private var since: Double = 0
    private var saidAt: Double = 0
    private var said: PictureHealth = .ok

    init(onSay: ((String) -> Void)? = nil) {
        self.onSay = onSay
    }

    func reset() {
        state = .ok
        last = nil
        since = 0
        saidAt = 0
        said = .ok
    }

    /// One frame of packed 8 bit pixels, `width` by `height`, with
    /// `bytesPerPixel` bytes each of which the first `counted` are colour.
    /// Returns what to say about it, or "".
    ///
    /// The Windows frame is an RGB array and `frame[::8, ::8].mean()` averages
    /// over the channels as well as the pixels, so this does too. A Mac frame
    /// arrives from a `CVPixelBuffer` as BGRA: pass 4 and 3, and the alpha is
    /// left out. B, G and R are the same three numbers as R, G and B, so the
    /// mean matches Windows for the same picture.
    ///
    /// `moving` is false for a card or a still image, which are supposed to be
    /// frozen: a still picture is only a fault when something was meant to be
    /// moving behind it.
    @discardableResult
    func look(frame: [UInt8], width: Int, height: Int,
              bytesPerPixel: Int = 3, counted: Int = 3,
              rowBytes: Int = 0, moving: Bool = true,
              now: Double? = nil) -> String {
        guard !frame.isEmpty, width > 0, height > 0,
              counted > 0, counted <= bytesPerPixel else { return "" }
        let stride = rowBytes > 0 ? rowBytes : width * bytesPerPixel
        let now = now ?? ProcessInfo.processInfo.systemUptime
        frames += 1

        // A subsample. One pixel in sixty four is plenty to tell a black frame
        // from a picture, and it keeps this off the profile entirely. numpy
        // slices [::8, ::8], so the rows and columns taken are the same ones.
        let rows = (height + 7) / 8
        let cols = (width + 7) / 8
        var small = [Int32](repeating: 0, count: rows * cols * counted)
        var total = 0
        var at = 0
        for row in Swift.stride(from: 0, to: height, by: 8) {
            let base = row * stride
            for col in Swift.stride(from: 0, to: width, by: 8) {
                let pixel = base + col * bytesPerPixel
                for c in 0..<counted {
                    let v = Int32(frame[pixel + c])
                    small[at] = v
                    total += Int(v)
                    at += 1
                }
            }
        }
        let brightness = Double(total) / Double(small.count)

        var found = PictureHealth.ok
        if brightness < C.healthBlackBelow {
            found = .black
        } else if moving, let previous = last, previous.count == small.count {
            var moved = 0
            for i in 0..<small.count { moved += Int(abs(small[i] - previous[i])) }
            if Double(moved) / Double(small.count) < C.healthFrozenBelow {
                found = .frozen
            }
        }
        last = small

        if found != state {
            // A new state starts its clock. Nothing is said yet: this is where
            // a blink gets absorbed.
            state = found
            since = now
            return ""
        }
        if found == .ok {
            if said != .ok && (now - since) >= C.healthPatience {
                said = .ok
                saidAt = now
                return say(C.healthBack)
            }
            return ""
        }
        if (now - since) < C.healthPatience { return "" }
        if said == found && (now - saidAt) < C.healthRepeat { return "" }
        said = found
        saidAt = now
        return say(found == .black ? C.healthBlackSaid : C.healthFrozenSaid)
    }

    @discardableResult
    private func say(_ text: String) -> String {
        onSay?(text)
        return text
    }

    /// The current answer, for anybody who asks rather than waits.
    func describe() -> String {
        switch state {
        case .black:  return "the picture is black"
        case .frozen: return "the picture has stopped moving"
        case .ok:     return "the picture looks fine"
        }
    }
}


extension HealthWatcher {
    /// One frame straight off the encoder's buffer.
    ///
    /// **This is the shape the numbers were measured against.** Windows
    /// strides the real 1280 by 720 frame by eight, which is 160 by 90 and
    /// 14,400 samples. Handing this a subsample that had ALREADY been reduced
    /// to 64 by 36 left it striding that by eight again, so it was judging a
    /// broadcast on forty pixels, and `healthFrozenBelow` of 0.35 is far
    /// noisier over forty values than over fourteen thousand. The module
    /// mirrored Windows faithfully and its caller did not, which is exactly
    /// the kind of fault a cross check of the module alone cannot see.
    @discardableResult
    func look(buffer: CVPixelBuffer, moving: Bool = true,
              now: Double? = nil) -> String {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer)?
                .assumingMemoryBound(to: UInt8.self) else { return "" }
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        let bytes = Array(UnsafeBufferPointer(start: base, count: stride * height))
        // BGRA, and the alpha is not part of how bright anything is.
        return look(frame: bytes, width: width, height: height,
                    bytesPerPixel: 4, counted: 3, rowBytes: stride,
                    moving: moving, now: now)
    }
}
