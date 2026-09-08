// Colours you can choose without being able to see them.
//
// A deliberate mirror of dropdeck/colours.py. Every number here was measured
// on the Windows side through a real encoder on 8 September 2026 and the
// reasoning is kept there in full. Nothing in this file may disagree with it:
// `SelfTest` compares the ratios against the same expected values the Windows
// tests assert, so a drift here fails a build rather than shipping a Mac that
// scores a colour pair differently from a Windows machine reading the same
// board.
//
// The short version of why it exists. Branding is the one purely visual thing
// on a stream, and a colour wheel is the problem restated rather than an
// answer. Legibility, though, is arithmetic: the WCAG contrast ratio is a
// ratio of BRIGHTNESS, and brightness is exactly the half of a picture that
// survives 4:2:0 chroma subsampling intact. So the one number that says
// whether a viewer can read a caption also says whether the encoder will
// destroy it. Red on blue scores 2.1 to 1 and came back as coloured mush for
// the same reason: there is no brightness difference there to carry the
// letters.

import Foundation

enum Colours {

    /// The named colours, in the order the list offers them. Ordinary words,
    /// because a screen reader says them: "slate", never "#2E3440", and
    /// nothing is called "primary" or "surface".
    static let named: [(name: String, rgb: RGB)] = [
        ("black",       RGB(0, 0, 0)),
        ("near black",  RGB(14, 18, 28)),
        ("charcoal",    RGB(32, 34, 40)),
        ("slate",       RGB(48, 56, 72)),
        ("navy",        RGB(16, 32, 72)),
        ("deep purple", RGB(48, 24, 72)),
        ("dark green",  RGB(16, 56, 40)),
        ("maroon",      RGB(72, 20, 28)),
        ("brown",       RGB(72, 48, 24)),
        ("mid grey",    RGB(128, 128, 128)),
        ("teal",        RGB(0, 128, 128)),
        ("blue",        RGB(24, 96, 200)),
        ("green",       RGB(32, 150, 72)),
        ("red",         RGB(200, 40, 40)),
        ("orange",      RGB(255, 140, 0)),
        ("gold",        RGB(232, 184, 40)),
        ("pink",        RGB(232, 96, 152)),
        ("light blue",  RGB(128, 184, 248)),
        ("light green", RGB(144, 216, 160)),
        ("cream",       RGB(248, 240, 216)),
        ("off white",   RGB(240, 242, 248)),
        ("white",       RGB(255, 255, 255)),
    ]

    static let names: [String] = named.map { $0.name }

    private static let byName: [String: RGB] =
        Dictionary(uniqueKeysWithValues: named.map { ($0.name, $0.rgb) })

    static let fallbackRGB = RGB(240, 242, 248)

    /// One named colour, or the fallback when the name is not one of ours.
    static func rgb(_ name: String, fallback: RGB = fallbackRGB) -> RGB {
        byName[name] ?? fallback
    }

    /// The name of a colour, for saying out loud. Nearest by squared distance
    /// when it is not exactly one of ours, so a board written by a version
    /// that had more colours still describes itself rather than reading out
    /// three numbers.
    static func nameOf(_ value: RGB?, fallback: String = "off white") -> String {
        guard let value else { return fallback }
        for (name, known) in named where known == value { return name }
        var best = fallback
        var gap: Int?
        for (name, known) in named {
            let far = known.squaredDistance(to: value)
            if gap == nil || far < gap! { best = name; gap = far }
        }
        return best
    }

    // --------------------------------------------- legibility, the point ---

    /// WCAG 2 relative luminance, 0 to 1.
    ///
    /// The sRGB channels are linearised and weighted by how bright the eye
    /// finds each one: green counts for most of brightness and blue for
    /// almost none, which is why blue text on black is so much worse than it
    /// looks on paper.
    static func luminance(_ value: RGB) -> Double {
        // 0.04045, not the 0.03928 WCAG 2.0 shipped. That figure came from an
        // obsolete IEC draft and the W3C corrected it in May 2021 (w3c/wcag
        // issue 308). It moves nothing at 8 bits, but a number this app says
        // out loud should be the right one.
        func linear(_ channel: Int) -> Double {
            let c = Double(channel) / 255.0
            return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * linear(value.r)
             + 0.7152 * linear(value.g)
             + 0.0722 * linear(value.b)
    }

    /// The WCAG 2 contrast ratio between two colours, 1.0 to 21.0.
    static func contrast(_ one: RGB, _ two: RGB) -> Double {
        let a = luminance(one), b = luminance(two)
        let high = max(a, b), low = min(a, b)
        return (high + 0.05) / (low + 0.05)
    }

    /// What a ratio has to reach. WCAG's own thresholds are 4.5 to 1 for body
    /// text and 3 to 1 for large text, and overlay captions ARE large text, so
    /// 3 is the floor rather than the target. 4.5 is used as the target anyway
    /// because a stream is watched on a phone in daylight, recompressed, at
    /// whatever size the platform feels like, and none of that is true of a
    /// web page.
    static let contrastGood = 4.5
    static let contrastFloor = 3.0

    /// What to SAY about two colours together. Never a number on its own: the
    /// number means nothing by itself to somebody who has never seen contrast,
    /// so it is always said with what it implies.
    static func verdict(front: RGB, back: RGB) -> (ratio: Double, said: String) {
        let ratio = contrast(front, back)
        if ratio >= 7.0 { return (ratio, "easy to read") }
        if ratio >= contrastGood { return (ratio, "readable") }
        if ratio >= contrastFloor { return (ratio, "readable at this size, but only just") }
        if ratio >= 2.0 { return (ratio, "too close together to read") }
        return (ratio, "almost invisible")
    }

    /// Above this, a colour visibly frays at the edges once it is encoded, and
    /// no amount of contrast or bitrate repairs it. Measured 8 September 2026
    /// through a real encoder: the error on a letter's edge tracks saturation
    /// almost exactly, at roughly 1.27 eight-bit levels per percent, and it is
    /// unchanged from 1 Mbps to 6 Mbps because subsampling, not the bitrate,
    /// is what does it.
    static let fringeLimit = 0.60

    /// How far a colour is from grey, 0 to 1. Value form, not lightness form:
    /// what matters is how much colour the encoder has to carry in the half
    /// resolution planes, and that is the gap between the strongest and
    /// weakest channel.
    static func saturation(_ value: RGB) -> Double {
        let high = max(value.r, value.g, value.b)
        if high == 0 { return 0 }
        return Double(high - min(value.r, value.g, value.b)) / Double(high)
    }

    /// Whether a colour will fray at the edges on video, and by how much.
    ///
    /// **This is a SECOND question, and contrast cannot answer it.** Contrast
    /// is a brightness ratio, and brightness is the half of the picture that
    /// survives 4:2:0 intact. Colour is stored at half resolution in both
    /// directions, so a strongly coloured letter keeps its shape and loses its
    /// edges, whatever its contrast. The two faults have two different
    /// repairs: poor contrast wants a different pair or a heavier outline, and
    /// fringing wants a less saturated colour. Nothing else fixes it, bitrate
    /// included.
    static func fringing(_ value: RGB) -> (level: Double, frays: Bool) {
        let level = saturation(value)
        return (level, level > fringeLimit)
    }

    /// A coloured line's thickness, rounded to an even number of pixels.
    ///
    /// Not fussiness. Colour is stored one sample per two by two block, so a
    /// coloured line an odd number of pixels high straddles two of those
    /// blocks and shares each with whatever is beside it. Measured 8 September
    /// 2026: a one pixel red rule lost 57 levels of colour, two pixels lost
    /// 12, and THREE pixels lost 17, worse than two. The app was drawing three
    /// at 720p.
    static func even(_ thickness: Int) -> Int {
        max(2, (thickness / 2) * 2)
    }

    /// One sentence about a pair, ready to be spoken.
    static func describePair(front frontName: String, back backName: String) -> String {
        let (ratio, said) = verdict(front: rgb(frontName), back: rgb(backName))
        var line = "\(frontName) on \(backName): \(said), \(oneDecimal(ratio)) to 1"
        if fringing(rgb(frontName)).frays {
            line += ", and strong enough to fray at the edges on video"
        }
        return line
    }

    /// Whether a pair clears the floor. Used by the pre-flight.
    static func readable(front: RGB, back: RGB) -> Bool {
        contrast(front, back) >= contrastFloor
    }

    // ------------------------------- whole looks, so nobody assembles one ---

    /// Ready-made sets, every one of which was checked against the numbers
    /// above rather than chosen by eye. `SelfTest` asserts that every single
    /// one clears `contrastGood` on both of its pairs, exactly as
    /// `tests/test_colours.py` does on Windows, so a preset can never ship
    /// unreadable.
    static let schemes: [(name: String, background: String, text: String, accent: String)] = [
        ("Default",  "near black",  "off white", "light blue"),
        ("Ink",      "black",       "white",     "gold"),
        ("Slate",    "slate",       "off white", "light blue"),
        ("Midnight", "navy",        "cream",     "gold"),
        ("Forest",   "dark green",  "cream",     "light green"),
        ("Wine",     "maroon",      "cream",     "pink"),
        ("Coffee",   "brown",       "cream",     "gold"),
        ("Grape",    "deep purple", "off white", "pink"),
        ("Paper",    "cream",       "black",     "red"),
        ("Daylight", "white",       "black",     "blue"),
    ]

    static let schemeNames: [String] = schemes.map { $0.name }

    /// One ready-made look as (background, text, accent) names.
    static func scheme(_ name: String) -> (background: String, text: String, accent: String) {
        for s in schemes where s.name == name {
            return (s.background, s.text, s.accent)
        }
        let first = schemes[0]
        return (first.background, first.text, first.accent)
    }

    /// A whole look, said out loud, with the number that matters.
    static func describeScheme(_ name: String) -> String {
        let s = scheme(name)
        let (ratio, said) = verdict(front: rgb(s.text), back: rgb(s.background))
        return "\(name): \(s.text) on \(s.background), \(said), "
             + "\(oneDecimal(ratio)) to 1. \(s.accent.capitalisedFirst) for the rule and the edges."
    }

    /// Python's "%.1f", which rounds half away from zero. Swift's String(format:)
    /// agrees with it, and the ratios are said out loud so the two copies must
    /// not differ by a digit.
    static func oneDecimal(_ value: Double) -> String {
        String(format: "%.1f", value)
    }
}

/// Eight bits a channel, which is what a board file stores and what every
/// number above expects.
struct RGB: Equatable {
    var r: Int
    var g: Int
    var b: Int

    init(_ r: Int, _ g: Int, _ b: Int) {
        self.r = r; self.g = g; self.b = b
    }

    func squaredDistance(to other: RGB) -> Int {
        let dr = r - other.r, dg = g - other.g, db = b - other.b
        return dr * dr + dg * dg + db * db
    }
}

private extension String {
    /// Python's str.capitalize() lowercases the rest. Every accent name here
    /// is already lower case so the two agree, but say so rather than assume.
    var capitalisedFirst: String {
        guard let first else { return self }
        return String(first).uppercased() + dropFirst().lowercased()
    }
}
