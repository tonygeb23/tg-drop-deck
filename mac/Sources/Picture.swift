// What goes on the screen, and what happens when it fails.
//
// Mirrors dropdeck/picture.py. One picture source at a time: a card the app
// draws, an image file, a camera, the screen, or the screen with the camera
// inset. No scenes, no layers, no compositing. That is a decision Windows
// argued out and this copy inherits rather than revisits.
//
// ## Frames are CVPixelBuffers, and that is the one real difference
//
// Windows carries frames as numpy arrays because PyAV wants one. Here a frame
// is a `CVPixelBuffer`, BGRA, IOSurface backed, because that is what
// VideoToolbox takes without a copy and what AVFoundation and ScreenCaptureKit
// already hand out. Nothing in the pipeline converts colour on the CPU.
//
// ## The blocky card is deliberately not here
//
// Windows draws the card twice: once in Roboto, and once in a hand made font
// of five by seven blocks for when Pillow is missing. That fallback exists
// because Pillow is a wheel that can fail to install. Core Text is in the
// process on every Mac, so the second card would be dead code that could only
// ever ship a worse picture. See docs/MAC-VIDEO-PLAN.md.

import Foundation
import CoreGraphics
import CoreVideo
import CoreText
import ImageIO

/// One thing that can be on the screen.
protocol PictureSource: AnyObject {
    var kind: String { get }
    /// The picture at one size, or nothing when this source cannot answer.
    func frame(width: Int, height: Int) -> CVPixelBuffer?
    /// What it is, in words, for the status line and the pre-flight.
    func describe() -> String
    func start()
    func close()
    /// Wait for a real first frame. A card is ready the moment it exists.
    func waitReady(timeout: Double) -> Bool
    func setTitle(_ title: String)
    /// Whether this source is SUPPOSED to be moving. A card and a still image
    /// are legitimately frozen, so only a live source can be stuck.
    var moving: Bool { get }
    /// Why it could not answer, when it could not.
    var error: String { get }
}

extension PictureSource {
    func start() {}
    func close() {}
    func waitReady(timeout: Double) -> Bool { true }
    func setTitle(_ title: String) {}
    var moving: Bool { false }
    var error: String { "" }
}

// ---------------------------------------------------------------- buffers ---

enum Pixels {

    /// A BGRA buffer the encoder can take without a copy.
    ///
    /// IOSurface backed on purpose: without that attribute VideoToolbox falls
    /// back to copying every frame into one of its own.
    static func make(width: Int, height: Int) -> CVPixelBuffer? {
        var buffer: CVPixelBuffer?
        let attributes: [CFString: Any] = [
            kCVPixelBufferIOSurfacePropertiesKey: [:] as CFDictionary,
            kCVPixelBufferCGImageCompatibilityKey: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey: true,
        ]
        CVPixelBufferCreate(kCFAllocatorDefault, width, height,
                            kCVPixelFormatType_32BGRA,
                            attributes as CFDictionary, &buffer)
        return buffer
    }

    /// A drawing context over a buffer. The buffer must be locked around it.
    static func context(for buffer: CVPixelBuffer) -> CGContext? {
        CGContext(data: CVPixelBufferGetBaseAddress(buffer),
                  width: CVPixelBufferGetWidth(buffer),
                  height: CVPixelBufferGetHeight(buffer),
                  bitsPerComponent: 8,
                  bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
                  space: CGColorSpaceCreateDeviceRGB(),
                  bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue
                            | CGBitmapInfo.byteOrder32Little.rawValue)
    }

    /// Make a buffer and draw into it. The lock is handled here so no caller
    /// can forget it, which on a pixel buffer is a silent wrong answer rather
    /// than a crash.
    static func draw(width: Int, height: Int,
                     _ body: (CGContext) -> Void) -> CVPixelBuffer? {
        guard let buffer = make(width: width, height: height) else { return nil }
        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
        guard let ctx = context(for: buffer) else { return nil }
        body(ctx)
        return buffer
    }

    /// A frame with the overlay drawn on top of it, as a NEW buffer.
    ///
    /// **Never draw on the buffer a source hands back.** Every source caches
    /// the frame it returns, so that a card is not redrawn thirty times a
    /// second and a camera is not rescaled thirty times a second. Painting the
    /// overlay straight onto that cache means painting it onto the SAME
    /// pixels again on the next frame, and again, so a clock smears and a
    /// lower third turns to mud within a second. The Windows copy learned the
    /// same thing in its split source, which copies before it insets.
    ///
    /// When there is nothing on top, the source's own buffer is handed
    /// straight back and nothing is copied.
    static func composite(_ frame: CVPixelBuffer, _ overlay: Overlay,
                          width: Int, height: Int) -> CVPixelBuffer {
        guard overlay.anythingOn(), let image = CameraSource.image(from: frame) else {
            return frame
        }
        return draw(width: width, height: height) { ctx in
            ctx.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            overlay.draw(into: ctx, width: width, height: height)
        } ?? frame
    }

    static func fill(_ ctx: CGContext, _ colour: RGB, width: Int, height: Int) {
        ctx.setFillColor(red: CGFloat(colour.r) / 255, green: CGFloat(colour.g) / 255,
                         blue: CGFloat(colour.b) / 255, alpha: 1)
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
    }

    /// Fit a picture inside a frame without stretching it out of shape.
    static func letterbox(_ image: CGImage, into ctx: CGContext,
                          width: Int, height: Int) {
        let sw = Double(image.width), sh = Double(image.height)
        guard sw > 0, sh > 0 else { return }
        let scale = min(Double(width) / sw, Double(height) / sh)
        let w = max(1.0, (sw * scale).rounded())
        let h = max(1.0, (sh * scale).rounded())
        ctx.interpolationQuality = .high
        ctx.draw(image, in: CGRect(x: (Double(width) - w) / 2,
                                   y: (Double(height) - h) / 2,
                                   width: w, height: h))
    }
}

// ------------------------------------------------------------------- card ---

/// The station name, and what is playing, on a plain background.
///
/// Redrawn only when something changes. A card is the same picture thirty
/// times a second, and drawing it thirty times a second would be thirty times
/// the work for no difference at all; the encoder is perfectly happy to be
/// handed the same buffer again and squeezes it to almost nothing.
final class CardSource: PictureSource {

    let kind = C.pictureCard

    private let lock = NSLock()
    private var name: String
    private var titleText: String
    private let background: RGB
    private let foreground: RGB
    private let accent: RGB
    private let showClock: Bool
    private var cache: CVPixelBuffer?
    private var cacheKey: String?
    private(set) var redraws = 0

    /// Held so a test can pin the minute. The app never sets it.
    var clock: () -> Date = { Date() }

    init(name: String = "", title: String = "",
         background: RGB = C.cardBackground, foreground: RGB = C.cardForeground,
         accent: RGB = C.cardAccent, clock showClock: Bool = false) {
        self.name = name.isEmpty ? C.appName : name
        self.titleText = title
        self.background = background
        self.foreground = foreground
        self.accent = accent
        self.showClock = showClock
    }

    var title: String {
        lock.lock(); defer { lock.unlock() }
        return titleText
    }

    func setTitle(_ title: String) {
        lock.lock(); titleText = title; lock.unlock()
    }

    func setName(_ name: String) {
        lock.lock(); self.name = name.isEmpty ? C.appName : name; lock.unlock()
    }

    func frame(width: Int, height: Int) -> CVPixelBuffer? {
        let minute = showClock ? Int(clock().timeIntervalSince1970 / 60) : 0
        lock.lock(); defer { lock.unlock() }
        let key = "\(width)x\(height)|\(name)|\(titleText)|\(minute)"
        if key == cacheKey, let cache { return cache }
        let drawn = draw(width: width, height: height, name: name, title: titleText)
        cache = drawn
        cacheKey = key
        redraws += 1
        return drawn
    }

    /// The name centred above the middle, a rule under it, the title under
    /// that, and the clock in the top right corner. The same layout as the
    /// Windows card, so a card somebody has been broadcasting for months does
    /// not jump about when they move machine.
    private func draw(width: Int, height: Int, name: String, title: String) -> CVPixelBuffer? {
        let bigSize = max(14, Int(Double(height) * 0.115))
        let smallSize = max(11, Int(Double(height) * 0.070))
        guard let big = Overlays.font(bigSize), let small = Overlays.font(smallSize)
        else { return nil }

        return Pixels.draw(width: width, height: height) { ctx in
            Pixels.fill(ctx, background, width: width, height: height)
            let margin = max(8, width / 16)
            let room = Double(width - margin * 2)

            let shown = Overlays.fit(name, size: bigSize, room: room)
            let line = CTLineCreateWithAttributedString(NSAttributedString(
                string: shown, attributes: [.font: big,
                                            .foregroundColor: cg(foreground)]))
            var ascent: CGFloat = 0, descent: CGFloat = 0
            let advance = CTLineGetTypographicBounds(line, &ascent, &descent, nil)

            // Core Graphics counts up from the bottom. Windows puts the name's
            // TOP at height/2 minus its ink height, so the baseline here is
            // that same top less the ascent, flipped.
            let nameTop = Double(height) / 2 - Double(ascent)
            let baseline = Double(height) - nameTop - Double(ascent)
            ctx.setTextDrawingMode(.fill)
            ctx.textPosition = CGPoint(x: (Double(width) - advance) / 2, y: baseline)
            CTLineDraw(line, ctx)

            // The rule sits under the INK, not under the line box, which is
            // where a descender lives. Windows got that wrong once and drew
            // the rule through the middle of the name.
            let ruleTop = nameTop + Double(ascent) + Double(descent)
                        + Double(max(6, height / 50))
            let ruleH = Double(Colours.even(height / 240))
            ctx.setFillColor(cg(accent))
            ctx.fill(CGRect(x: Double(margin),
                            y: Double(height) - ruleTop - ruleH,
                            width: Double(width - margin * 2), height: ruleH))

            if !title.isEmpty {
                let shownTitle = Overlays.fit(title, size: smallSize, room: room)
                let tline = CTLineCreateWithAttributedString(NSAttributedString(
                    string: shownTitle, attributes: [.font: small,
                                                     .foregroundColor: cg(accent)]))
                var ta: CGFloat = 0, td: CGFloat = 0
                let tadv = CTLineGetTypographicBounds(tline, &ta, &td, nil)
                let top = ruleTop + ruleH + Double(max(8, height / 40))
                ctx.textPosition = CGPoint(x: (Double(width) - tadv) / 2,
                                           y: Double(height) - top - Double(ta))
                CTLineDraw(tline, ctx)
            }

            if showClock {
                let formatter = DateFormatter()
                formatter.dateFormat = C.overlayClockFormat
                let stamp = formatter.string(from: clock())
                let cline = CTLineCreateWithAttributedString(NSAttributedString(
                    string: stamp, attributes: [.font: small,
                                                .foregroundColor: cg(accent)]))
                var ca: CGFloat = 0, cd: CGFloat = 0
                let cadv = CTLineGetTypographicBounds(cline, &ca, &cd, nil)
                ctx.textPosition = CGPoint(x: Double(width - margin) - cadv,
                                           y: Double(height - margin) - Double(ca))
                CTLineDraw(cline, ctx)
            }
        }
    }

    private func cg(_ c: RGB) -> CGColor {
        CGColor(red: CGFloat(c.r) / 255, green: CGFloat(c.g) / 255,
                blue: CGFloat(c.b) / 255, alpha: 1)
    }

    func describe() -> String { "a card" }
}

// ------------------------------------------------------------------ image ---

/// The user's own artwork, scaled once and kept.
///
/// Read through ImageIO, which is in the process already, so a PNG, a JPEG, a
/// HEIC or a TIFF all work with nothing added to the download.
final class ImageSource: PictureSource {

    let kind = C.pictureImage
    let path: String
    private let background: RGB
    private(set) var error = ""
    private var source: CGImage?
    private var cache: CVPixelBuffer?
    private var cacheSize: (Int, Int)?
    private var loaded = false

    init(path: String, background: RGB = C.cardBackground) {
        self.path = path
        self.background = background
    }

    private func load() {
        if loaded { return }
        loaded = true
        guard !path.isEmpty, FileManager.default.fileExists(atPath: path) else {
            error = "that picture file is not there"
            return
        }
        guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
              CGImageSourceGetCount(src) > 0,
              let image = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
            error = "that file is not a picture this can read"
            return
        }
        source = image
    }

    func frame(width: Int, height: Int) -> CVPixelBuffer? {
        if let cache, cacheSize.map({ $0 == (width, height) }) == true { return cache }
        load()
        let made = Pixels.draw(width: width, height: height) { ctx in
            Pixels.fill(ctx, background, width: width, height: height)
            if let source {
                Pixels.letterbox(source, into: ctx, width: width, height: height)
            }
        }
        cache = made
        cacheSize = (width, height)
        return made
    }

    func describe() -> String {
        error.isEmpty ? "a picture" : "a picture that could not be read"
    }
}

// --------------------------------------------------------------- fallback ---

/// One source, with another behind it when the first cannot answer.
///
/// **This is what makes a camera safe to use on a live show.** A camera that
/// is unplugged, or taken by another program halfway through, falls back to
/// the card and the show carries on. Coming off air because a webcam was
/// pulled out is the failure this exists to prevent.
final class FallbackSource: PictureSource {

    let primary: PictureSource
    let backup: PictureSource
    var onFallback: (String) -> Void
    private(set) var fallenBack = false
    private(set) var reason = ""
    private var triedAt: Double = 0
    var now: () -> Double = { ProcessInfo.processInfo.systemUptime }

    init(primary: PictureSource, backup: PictureSource,
         onFallback: @escaping (String) -> Void = { _ in }) {
        self.primary = primary
        self.backup = backup
        self.onFallback = onFallback
    }

    var kind: String { primary.kind }
    var moving: Bool { fallenBack ? backup.moving : primary.moving }
    var error: String { primary.error }

    func start() {
        primary.start()
        backup.start()
    }

    /// Wait for the real source, not the card standing in for it.
    ///
    /// Without this a preview of a camera photographs the card: opening a
    /// webcam takes about half a second and the first frame call lands long
    /// before that.
    func waitReady(timeout: Double) -> Bool {
        primary.waitReady(timeout: timeout)
    }

    /// The primary if it can answer, otherwise the backup.
    ///
    /// **It RETRIES.** The Windows version gave up for good on the first
    /// failure to begin with, and its recovery branch sat where it could never
    /// run: one glitched frame, or another program holding the camera for a
    /// moment, meant the card for the rest of a three hour show even after the
    /// camera was fine again. Retrying costs one call every few seconds and
    /// gets the presenter their camera back.
    func frame(width: Int, height: Int) -> CVPixelBuffer? {
        let at = now()
        if fallenBack {
            if (at - triedAt) >= C.pictureRetrySeconds {
                triedAt = at
                if let picture = primary.frame(width: width, height: height) {
                    fallenBack = false
                    reason = ""
                    onFallback("The camera is back")
                    return picture
                }
            }
        } else {
            if let picture = primary.frame(width: width, height: height) {
                return picture
            }
            fallBack(primary.error.isEmpty ? "the picture stopped" : primary.error)
        }
        return backup.frame(width: width, height: height)
    }

    private func fallBack(_ why: String) {
        if fallenBack { return }
        fallenBack = true
        reason = why
        triedAt = now()
        // Said once, not once a frame. A camera that has gone is going to keep
        // being gone thirty times a second.
        onFallback(why)
    }

    func describe() -> String {
        fallenBack ? "\(primary.describe()), showing a card instead" : primary.describe()
    }

    func setTitle(_ title: String) {
        primary.setTitle(title)
        backup.setTitle(title)
    }

    func close() {
        primary.close()
        backup.close()
    }
}

// ------------------------------------------------------------- building it ---

/// What the picture needs out of a board. A value rather than the board, for
/// the same reason the pre-flight takes one: it can be built and checked with
/// no camera, no screen and no display.
struct PictureSettings {
    var picture = C.pictureCard
    var pictureFile = ""
    var pictureClock = false
    var camera = ""
    var screen = C.screenAll
    var splitCorner = C.splitCorner
    var name = ""
    var streamName = ""
    var title = ""
    var colourBackground = ""
    var colourText = ""
    var colourAccent = ""
    var videoWidth = C.rtmpWidth
    var videoHeight = C.rtmpHeight
    var videoFPS = C.rtmpFPS
}

enum Picture {

    /// The three brand colours, as numbers.
    ///
    /// One place, so the card, the letterbox bars, the overlay and the split's
    /// edge cannot drift apart. Names in, numbers out: the user only ever sees
    /// the names, and Colours.swift explains why.
    static func brand(_ s: PictureSettings) -> (background: RGB, ink: RGB, accent: RGB) {
        (Colours.rgb(s.colourBackground.isEmpty ? C.colourBackground : s.colourBackground),
         Colours.rgb(s.colourText.isEmpty ? C.colourText : s.colourText),
         Colours.rgb(s.colourAccent.isEmpty ? C.colourAccent : s.colourAccent))
    }

    /// The picture source one station's settings ask for.
    ///
    /// A camera and a picture file both get the card behind them, because a
    /// camera that is unplugged or a file that has been moved must not be the
    /// end of a broadcast. The card alone needs no such thing: it cannot fail.
    static func build(_ s: PictureSettings,
                      onFallback: @escaping (String) -> Void = { _ in }) -> PictureSource {
        let (back, _, accent) = brand(s)
        let card = CardSource(
            name: s.name.isEmpty ? (s.streamName.isEmpty ? C.appName : s.streamName) : s.name,
            title: s.title, background: back, foreground: brand(s).ink,
            accent: accent, clock: s.pictureClock)

        let primary: PictureSource
        switch s.picture {
        case C.pictureImage:
            primary = ImageSource(path: s.pictureFile, background: back)
        case C.pictureCamera:
            primary = CameraSource(device: s.camera, width: s.videoWidth,
                                   height: s.videoHeight, fps: s.videoFPS, bars: back)
        case C.pictureScreen:
            primary = ScreenSource(which: s.screen, width: s.videoWidth,
                                   height: s.videoHeight, fps: s.videoFPS, bars: back)
        case C.pictureSplit:
            // The camera is built even when it cannot open: the split reports
            // that itself and goes on with the screen, which is still a show.
            primary = SplitSource(
                screen: ScreenSource(which: s.screen, width: s.videoWidth,
                                     height: s.videoHeight, fps: s.videoFPS, bars: back),
                camera: CameraSource(device: s.camera, width: s.videoWidth,
                                     height: s.videoHeight, fps: s.videoFPS, bars: back),
                edge: accent, corner: s.splitCorner)
        default:
            return card
        }
        return FallbackSource(primary: primary, backup: card, onFallback: onFallback)
    }
}
