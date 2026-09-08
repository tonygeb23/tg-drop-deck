// Things on top of the picture: four named places, and what is in them.
//
// Mirrors dropdeck/overlay.py, including the geometry, the wording of every
// spoken line, and the one second file poll.
//
// **There is no canvas and there are no coordinates, and that is the point.**
// Putting something at an exact position is the easy half. Knowing whether it
// looks right is the half that needs eyes, and it is why every guide for blind
// streamers ends with "get a sighted person to lay it out once". Four places
// that are already the right size and cannot land on top of each other can be
// checked without looking, because the answer to "what is on screen" is four
// lines long.
//
// ## What is different here, and it is only the drawing
//
// Windows needs Pillow to put a glyph on a pixel, and pays about three
// megabytes for it. Core Text is already in the process, so the Mac pays
// nothing. The font itself is the SAME Roboto the Windows copy ships, byte for
// byte, because a card made on a Mac and a card made on a PC have to be the
// same card, and because the digits are tabular so a clock does not wobble.
//
// One consequence is measured and deliberate: `fits` does NOT agree with the
// Windows number to the pixel, because the two renderers do not draw the same
// width. Pillow measures through FreeType with hinting on, which snaps stems
// to the pixel grid; Core Text measures unhinted. Sixteen letter i's at 66 px
// are 288 px wide on Windows and 272 here. `fits` predicts what THIS machine
// is about to draw, so agreeing with the other one would be being wrong on
// purpose. docs/MAC-VIDEO-PLAN.md section 3a has the measurements, and the
// self test checks the promise the number exists to keep: that nothing is cut
// short without being said first.

import Foundation
import CoreText
import CoreGraphics
import AppKit

/// One named place on the picture, as fractions of the frame.
///
/// Fractions rather than pixels so the same layout holds at 720p, 1080p or
/// anything else, and so nothing has to be re-measured when the size changes.
struct OverlayPlace {
    let key: String
    let label: String
    let left: Double
    let top: Double
    let right: Double
    let bottom: Double
    /// Text height as a fraction of frame height.
    let size: Double
    let align: OverlayAlign

    /// Where this place is, in pixels, at one frame size.
    func rect(_ width: Int, _ height: Int) -> (left: Int, top: Int, right: Int, bottom: Int) {
        (Int((left * Double(width)).rounded()),
         Int((top * Double(height)).rounded()),
         Int((right * Double(width)).rounded()),
         Int((bottom * Double(height)).rounded()))
    }

    func textSize(_ height: Int) -> Int {
        max(10, Int((size * Double(height)).rounded()))
    }

    func describeWhere() -> String { C.placeWhere[key] ?? "" }
}

enum OverlayAlign { case left, right }

enum Overlays {

    /// The four places, deliberately few and deliberately unable to overlap.
    /// Two things in one spot is precisely the confusion that not being able
    /// to look at the screen makes unrecoverable.
    static let places: [OverlayPlace] = [
        OverlayPlace(key: C.placeTop, label: "Top strip",
                     left: 0.030, top: 0.035, right: 0.700, bottom: 0.125,
                     size: 0.052, align: .left),
        OverlayPlace(key: C.placeCorner, label: "Corner",
                     left: 0.730, top: 0.035, right: 0.970, bottom: 0.125,
                     size: 0.045, align: .right),
        OverlayPlace(key: C.placeLower, label: "Lower third",
                     left: 0.047, top: 0.775, right: 0.640, bottom: 0.925,
                     size: 0.068, align: .left),
        OverlayPlace(key: C.placeClock, label: "Clock",
                     left: 0.680, top: 0.775, right: 0.953, bottom: 0.925,
                     size: 0.062, align: .right),
    ]

    static let byKey: [String: OverlayPlace] =
        Dictionary(uniqueKeysWithValues: places.map { ($0.key, $0) })

    static func placeLabel(_ key: String) -> String {
        byKey[key]?.label ?? key
    }

    // ---------------------------------------------------------- the font ---

    private static var fonts: [String: CTFont] = [:]
    private static let fontLock = NSLock()

    private static func load(_ name: String) -> CGFont? {
        var tried: [String] = []
        if let inBundle = Bundle.main.path(forResource: name, ofType: nil,
                                           inDirectory: "fonts") {
            tried.append(inBundle)
        }
        tried.append("mac/Resources/fonts/" + name)
        tried.append("assets/fonts/" + name)
        for path in tried {
            if let data = FileManager.default.contents(atPath: path),
               let provider = CGDataProvider(data: data as CFData),
               let font = CGFont(provider) {
                return font
            }
        }
        return nil
    }

    private static let boldFont: CGFont? = load(C.fontBold)
    /// The card's title and its clock are Roboto REGULAR on Windows, and were
    /// Bold here until 3.5.2 because only one face was ever loaded. A card
    /// somebody has been broadcasting for months has to look the same on the
    /// other machine, so both faces ship and both are used.
    private static let regularFont: CGFont? = load(C.fontRegular)

    private static var graphicsFont: CGFont? = {
        // Beside the binary in the bundle, or beside the sources when this is
        // being run from a checkout by a test.
        boldFont
    }()

    /// Whether anything can be drawn on top of the picture at all.
    ///
    /// Always true in a built bundle. It is asked because the Windows copy
    /// asks it, Pillow being a wheel that can be missing, and because a
    /// checkout running a test without the fonts should say so rather than
    /// draw nothing and look correct.
    static func available() -> Bool { boldFont != nil && regularFont != nil }

    static func whyUnavailable() -> String {
        available() ? "" : "A bundled font is missing, so nothing can be put on the picture."
    }

    /// One size of one of the two bundled faces, made once and kept.
    static func font(_ size: Int, bold: Bool = true) -> CTFont? {
        guard let face = bold ? boldFont : regularFont else { return nil }
        let key = "\(size)|\(bold)"
        fontLock.lock(); defer { fontLock.unlock() }
        if let got = fonts[key] { return got }
        let made = CTFontCreateWithGraphicsFont(face, CGFloat(size), nil, nil)
        fonts[key] = made
        return made
    }

    /// How wide a string is, in the font a tile is drawn in.
    static func width(_ text: String, size: Int, bold: Bool = true) -> Double {
        guard !text.isEmpty, let face = font(size, bold: bold) else { return 0 }
        let line = CTLineCreateWithAttributedString(NSAttributedString(
            string: text, attributes: [.font: face]))
        return CTLineGetTypographicBounds(line, nil, nil, nil)
    }

    /// The text, shortened with an ellipsis if it will not fit.
    static func fit(_ text: String, size: Int, room: Double,
                    bold: Bool = true) -> String {
        if width(text, size: size, bold: bold) <= room { return text }
        let ell = "..."
        var cut = text
        while !cut.isEmpty && width(cut + ell, size: size, bold: bold) > room {
            cut.removeLast()
        }
        return cut.isEmpty ? ell : cut + ell
    }

    /// The padding inside a tile, which is also what `fits` has to allow for.
    static func padding(_ tileHeight: Int) -> Int {
        max(8, Int(Double(tileHeight) * 0.22))
    }

    /// Whether a string fits its place without being cut. For the pre-flight.
    ///
    /// Answerable before going on the air, which is the point: a title too
    /// long for the lower third is knowable now rather than discoverable by
    /// somebody watching.
    static func fits(_ text: String, key: String, width frameWidth: Int,
                     height frameHeight: Int) -> Bool {
        if text.isEmpty { return true }
        guard let spot = byKey[key], available() else { return true }
        let box = spot.rect(frameWidth, frameHeight)
        let pad = padding(box.bottom - box.top)
        let room = Double((box.right - box.left) - pad * 2)
        return width(text, size: spot.textSize(frameHeight)) <= room
    }

    /// One place's picture, or nothing when there is nothing to say.
    ///
    /// A rounded panel with the text on it, outlined so it survives whatever
    /// is behind it.
    static func renderTile(_ text: String, width tileWidth: Int, height tileHeight: Int,
                           size: Int, align: OverlayAlign = .left,
                           panel: RGB = C.overlayBackground,
                           ink: RGB = C.overlayForeground) -> CGImage? {
        guard !text.isEmpty, let face = font(size) else { return nil }
        let w = max(2, tileWidth), h = max(2, tileHeight)
        guard let ctx = CGContext(
            data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        ctx.clear(CGRect(x: 0, y: 0, width: w, height: h))

        let radius = CGFloat(max(4, Int(Double(h) * 0.16)))
        let rounded = CGPath(roundedRect: CGRect(x: 0, y: 0, width: w, height: h),
                             cornerWidth: radius, cornerHeight: radius,
                             transform: nil)
        ctx.addPath(rounded)
        ctx.setFillColor(red: CGFloat(panel.r) / 255, green: CGFloat(panel.g) / 255,
                         blue: CGFloat(panel.b) / 255,
                         alpha: CGFloat(C.overlayAlpha) / 255)
        ctx.fillPath()

        let pad = padding(h)
        let shown = fit(text, size: size, room: Double(w - pad * 2))
        // The outline is black or white depending on which the words are
        // further from, so an outline never makes text HARDER to see. Picking
        // one and keeping it would have made pale text on a pale panel worse.
        let edge: RGB = Colours.luminance(ink) > 0.4 ? RGB(0, 0, 0) : RGB(255, 255, 255)
        let stroke = max(1, Int(Double(size) * 0.045))

        let inkColour = CGColor(red: CGFloat(ink.r) / 255, green: CGFloat(ink.g) / 255,
                                blue: CGFloat(ink.b) / 255, alpha: 1)
        let edgeColour = CGColor(red: CGFloat(edge.r) / 255, green: CGFloat(edge.g) / 255,
                                 blue: CGFloat(edge.b) / 255, alpha: 1)
        // Pillow strokes outward from the glyph and then fills. Core Graphics
        // strokes CENTRED on the path, so the width is doubled and the fill is
        // drawn over the top: that puts the same amount of outline outside the
        // letter and leaves its inside the ink colour.
        //
        // The two passes are `.stroke` then `.fill` on the CONTEXT, and the
        // stroke colour comes from the context too. It is worth saying why,
        // because the obvious spellings are both wrong and both fail silently.
        // `.strokeClip` does not draw at all, it intersects the clip with the
        // stroke, so a fill drawn afterwards is clipped away to nothing and
        // the tile comes out as a panel with no words on it. And putting
        // `.strokeColor` and `.strokeWidth` in the attributed string is the
        // AppKit spelling, which CTLineDraw under an explicit text drawing
        // mode does not honour.
        let attributes: [NSAttributedString.Key: Any] = [
            .font: face,
            .foregroundColor: inkColour,
        ]
        let line = CTLineCreateWithAttributedString(
            NSAttributedString(string: shown, attributes: attributes))
        var ascent: CGFloat = 0, descent: CGFloat = 0
        let advance = CTLineGetTypographicBounds(line, &ascent, &descent, nil)
        let x: CGFloat = align == .right
            ? CGFloat(w - pad) - CGFloat(advance)
            : CGFloat(pad)
        // Core Graphics counts up from the bottom, so the baseline sits the
        // descent above the vertical centre of the remaining space.
        let y = (CGFloat(h) - (ascent + descent)) / 2 + descent

        ctx.setLineWidth(CGFloat(stroke) * 2)
        ctx.setLineJoin(.round)
        ctx.setStrokeColor(edgeColour)
        ctx.setTextDrawingMode(.stroke)
        ctx.textPosition = CGPoint(x: x, y: y)
        CTLineDraw(line, ctx)

        ctx.setTextDrawingMode(.fill)
        ctx.textPosition = CGPoint(x: x, y: y)
        CTLineDraw(line, ctx)
        return ctx.makeImage()
    }
}

/// What is on top of the picture, and how it gets there.
///
/// Holds one string per place. Re-renders a tile only when its string changes,
/// and draws the cached tiles onto a frame. Called on the streaming thread,
/// once per video frame, so the hot path is a cache lookup per place and a
/// draw over that place's rectangle only.
final class Overlay {

    private let lock = NSLock()
    private var kinds: [String: String] = [:]
    private var custom: [String: String] = [:]
    private var files: [String: String] = [:]
    /// place key to the string showing now.
    private var text: [String: String] = [:]
    private var tiles: [String: (rect: CGRect, image: CGImage)?] = [:]
    private var size: (width: Int, height: Int) = (0, 0)

    private var fileSeen: [String: (at: Double, stamp: Double?)] = [:]
    private var fileText: [String: String] = [:]

    private(set) var renders = 0
    var station = ""
    var title = ""
    private var panel = C.overlayBackground
    private var ink = C.overlayForeground

    /// Where the clock's string comes from. Held so a test can pin it; the app
    /// never sets it.
    var clock: () -> Date = { Date() }
    /// Monotonic seconds, so the file poll can be driven by a test.
    var now: () -> Double = { ProcessInfo.processInfo.systemUptime }

    init(settings: OverlaySettings = OverlaySettings()) {
        apply(settings)
    }

    /// What each place is FOR, from the board.
    func apply(_ settings: OverlaySettings) {
        lock.lock()
        kinds = [:]; custom = [:]; files = [:]
        for place in Overlays.places {
            let held = settings.places[place.key] ?? [:]
            kinds[place.key] = held["kind"] ?? C.textNone
            custom[place.key] = held["words"] ?? ""
            files[place.key] = held["file"] ?? ""
        }
        fileSeen = [:]; fileText = [:]; tiles = [:]; text = [:]
        lock.unlock()
        station = settings.name.isEmpty ? settings.streamName : settings.name
        panel = Colours.rgb(settings.colourBackground.isEmpty
                            ? C.colourBackground : settings.colourBackground)
        ink = Colours.rgb(settings.colourText.isEmpty
                          ? C.colourText : settings.colourText)
    }

    func kindOf(_ key: String) -> String {
        lock.lock(); defer { lock.unlock() }
        return kinds[key] ?? C.textNone
    }

    /// What is playing. Called from the same place the card is told.
    func setTitle(_ title: String) { self.title = title }

    // ------------------------------------------------------- the strings ---

    /// What this place should be saying right now.
    private func wanted(_ key: String) -> String {
        switch kinds[key] ?? C.textNone {
        case C.textStation: return station
        case C.textPlaying: return title
        case C.textTime:
            let formatter = DateFormatter()
            // A fixed pattern needs a fixed locale, or a region setting can
            // turn "HH:mm" into twelve hour with an am or pm on the end.
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.dateFormat = C.overlayClockFormat
            return formatter.string(from: clock())
        case C.textWords: return custom[key] ?? ""
        case C.textFile: return fromFile(key)
        default: return ""
        }
    }

    /// A text file, re-read when it changes. OBS's mechanism exactly.
    ///
    /// OBS polls the file's modification time once a second and re-reads on
    /// change, and that one 1 Hz stat call is the entire "now playing"
    /// ecosystem: every Spotify overlay and countdown script out there works
    /// by writing a text file. Copying it verbatim means every one of those
    /// tools works with this app too, for nothing.
    private func fromFile(_ key: String) -> String {
        let path = files[key] ?? ""
        if path.isEmpty { return "" }
        let at = now()
        if let seen = fileSeen[key], (at - seen.at) < C.overlayFilePoll {
            return fileText[key] ?? ""
        }
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              let modified = attrs[.modificationDate] as? Date else {
            fileSeen[key] = (at, nil)
            fileText[key] = ""
            return ""
        }
        let stamp = modified.timeIntervalSince1970
        if let seen = fileSeen[key], seen.stamp == stamp {
            fileSeen[key] = (at, stamp)
            return fileText[key] ?? ""
        }
        var line = ""
        if let handle = FileHandle(forReadingAtPath: path) {
            defer { try? handle.close() }
            let data = handle.readData(ofLength: C.overlayFileMax)
            let whole = String(decoding: data, as: UTF8.self)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            line = whole.split(separator: "\n", omittingEmptySubsequences: false)
                .first.map { $0.trimmingCharacters(in: .whitespaces) } ?? ""
        }
        fileSeen[key] = (at, stamp)
        fileText[key] = line
        return line
    }

    // --------------------------------------------------------- rendering ---

    /// The cached tile for one place, redrawn only when its text moved.
    private func tileFor(_ key: String, _ width: Int, _ height: Int) -> (rect: CGRect, image: CGImage)? {
        let want = wanted(key)
        if size != (width, height) {
            tiles = [:]; text = [:]
            size = (width, height)
        }
        if text[key] == want, let cached = tiles[key] { return cached }
        text[key] = want
        if want.isEmpty { tiles[key] = .some(nil); return nil }
        guard let spot = Overlays.byKey[key] else { return nil }
        let box = spot.rect(width, height)
        guard let image = Overlays.renderTile(
            want, width: box.right - box.left, height: box.bottom - box.top,
            size: spot.textSize(height), align: spot.align,
            panel: panel, ink: ink) else {
            tiles[key] = .some(nil)
            return nil
        }
        renders += 1
        // Core Graphics counts up from the bottom of the frame; the places are
        // written down from the top, the way a person describes a screen.
        let rect = CGRect(x: box.left, y: height - box.bottom,
                          width: box.right - box.left, height: box.bottom - box.top)
        let made = (rect: rect, image: image)
        tiles[key] = made
        return made
    }

    /// Put everything on a frame, in place.
    func draw(into ctx: CGContext, width: Int, height: Int) {
        guard Overlays.available() else { return }
        lock.lock(); defer { lock.unlock() }
        for spot in Overlays.places {
            guard let tile = tileFor(spot.key, width, height) else { continue }
            if tile.rect.width <= 0 || tile.rect.height <= 0 { continue }
            ctx.draw(tile.image, in: tile.rect)
        }
    }

    func anythingOn() -> Bool {
        lock.lock(); defer { lock.unlock() }
        return Overlays.places.contains { (kinds[$0.key] ?? C.textNone) != C.textNone }
    }

    // ---------------------------------------------------------- speaking ---

    /// What is on top of the picture, in words. Never empty.
    func describe() -> String {
        lock.lock()
        var parts: [String] = []
        for spot in Overlays.places {
            let kind = kinds[spot.key] ?? C.textNone
            if kind == C.textNone { continue }
            let said = text[spot.key] ?? wanted(spot.key)
            if said.isEmpty {
                parts.append("\(spot.label), \(C.textLabels[kind] ?? kind), nothing to show yet")
            } else {
                parts.append("\(spot.describeWhere()) \(spot.label.lowercased()) reading \(said)")
            }
        }
        lock.unlock()
        if parts.isEmpty { return "nothing on top of it" }
        return parts.count == 2 ? parts.joined(separator: ", and ")
                                : parts.joined(separator: ". ")
    }
}

/// What the overlay needs out of a board. A value of its own rather than the
/// whole board, so this can be built and checked with nothing running, which
/// is the same reason the pre-flight takes one.
struct OverlaySettings {
    var places: [String: [String: String]] = [:]
    var name = ""
    var streamName = ""
    var colourBackground = ""
    var colourText = ""
}
