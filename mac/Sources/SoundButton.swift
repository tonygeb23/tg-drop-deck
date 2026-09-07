// One pad: what it draws, and what a screen reader is told it is.
//
// The rule this whole file exists for, carried over unchanged from the Windows
// copy, where it was Brian Hartgen's 2.3.0 report:
//
//   A pad's label is rewritten the instant the user EDITS the slot, and never
//   while it is only the mixer talking.
//
// An edit lands immediately, focus or no focus, because a screen reader has to
// answer "did that apply?" without the user tabbing away and back. A sound
// starting is deferred until focus leaves, because rewriting the label under
// the user's fingers restarts the announcement mid sentence, on air. And a pad
// that now points at a DIFFERENT slot is relabelled unconditionally, because
// the pad under the cursor is now a different sound and saying otherwise is
// the one thing worse than saying it twice.

import AppKit

final class SoundButton: NSButton {

    private(set) var slot: Slot
    private var playing = false
    private var lastLabel = ""
    private var lastContent = ""

    var onTrigger: ((Slot) -> Void)?
    var onContextMenu: ((SoundButton, NSPoint) -> Void)?

    init(slot: Slot) {
        self.slot = slot
        super.init(frame: .zero)
        wantsLayer = true
        isBordered = false
        title = ""
        setButtonType(.momentaryChange)
        focusRingType = .default
        target = self
        action = #selector(pressed)
        setContentHuggingPriority(.defaultLow, for: .horizontal)
        setContentHuggingPriority(.defaultLow, for: .vertical)
        applyLabel(force: true)
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    @objc private func pressed() { onTrigger?(slot) }

    // ------------------------------------------------------------ the rule ---

    /// Point this pad at a different slot. Always relabels.
    func setSlot(_ newSlot: Slot) {
        slot = newSlot
        playing = false
        lastLabel = ""
        lastContent = ""
        applyLabel(force: true)
        needsDisplay = true
    }

    /// Bring the pad up to date. `nowPlaying` is the mixer talking.
    func refresh(playing nowPlaying: Bool) {
        let label = slot.buttonLabel(playing: nowPlaying)
        // The label with the "playing" word left out. Comparing THIS is what
        // tells an edit apart from a sound starting.
        let content = slot.buttonLabel(playing: false)
        let stateChanged = nowPlaying != playing
        let edited = content != lastContent
        playing = nowPlaying

        if label != lastLabel && (edited || !hasFocus) {
            lastLabel = label
            lastContent = content
            setAccessibilityLabel(label)
            toolTip = label
        }
        if stateChanged || edited { needsDisplay = true }
    }

    private var hasFocus: Bool {
        window?.firstResponder === self
    }

    private func applyLabel(force: Bool) {
        let label = slot.buttonLabel(playing: playing)
        lastLabel = label
        lastContent = slot.buttonLabel(playing: false)
        setAccessibilityLabel(label)
        toolTip = label
    }

    override func becomeFirstResponder() -> Bool {
        needsDisplay = true
        return super.becomeFirstResponder()
    }

    override func resignFirstResponder() -> Bool {
        // A relabel that was held back while this pad had focus is applied on
        // the way out.
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.refresh(playing: self.playing)
        }
        needsDisplay = true
        return super.resignFirstResponder()
    }

    // ----------------------------------------------------------- the menu ---

    override func rightMouseDown(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        onContextMenu?(self, point)
    }

    override func menu(for event: NSEvent) -> NSMenu? {
        // VoiceOver's own "open a menu" gesture arrives here with no useful
        // mouse position, so the caller computes one on the control. The same
        // rule as the Windows Applications key: a menu must never open on
        // another monitor because that is where the pointer happens to be.
        onContextMenu?(self, NSPoint(x: bounds.midX, y: bounds.midY))
        return nil
    }

    // ---------------------------------------------------------- the drawing ---
    //
    // Drawn in three zones because a plain button centres one line and clips
    // it at both ends with no ellipsis. Colour is never the only cue: every
    // state painted here is also a word inside the accessible label, which is
    // what is read aloud.

    override func draw(_ dirtyRect: NSRect) {
        let assigned = slot.isAssigned
        let focused = hasFocus
        let missing = slot.isMissing

        let radius: CGFloat = 8
        let inset: CGFloat = 1.5
        let box = bounds.insetBy(dx: inset, dy: inset)
        let path = NSBezierPath(roundedRect: box, xRadius: radius, yRadius: radius)

        if assigned {
            (playing ? NSColor.controlAccentColor.withAlphaComponent(0.22)
                     : NSColor.controlBackgroundColor).setFill()
            path.fill()
        }

        let borderColour: NSColor
        if missing { borderColour = .systemRed }
        else if playing { borderColour = .controlAccentColor }
        else if focused { borderColour = .keyboardFocusIndicatorColor }
        else { borderColour = .separatorColor }
        borderColour.setStroke()
        path.lineWidth = (focused || playing) ? 2.5 : 1
        if !assigned {
            path.setLineDash([4, 3], count: 2, phase: 0)
        }
        path.stroke()

        // The accent bar, dropped entirely when the system asks for no colour.
        let states = stateWords()
        if assigned && !states.isEmpty
            && !NSWorkspace.shared.accessibilityDisplayShouldDifferentiateWithoutColor {
            let bar = NSRect(x: box.minX + 1, y: box.minY + 4, width: 4, height: box.height - 8)
            borderColour.withAlphaComponent(0.8).setFill()
            NSBezierPath(roundedRect: bar, xRadius: 2, yRadius: 2).fill()
        }

        let left = box.minX + 12
        let width = box.width - 20
        var y = box.maxY - 6

        let nameFont = NSFont.systemFont(ofSize: NSFont.systemFontSize * 1.25, weight: .semibold)
        let nameColour: NSColor = assigned ? .labelColor : .secondaryLabelColor
        y -= draw("\(slot.number). \(slot.displayName)",
                  font: nameFont, colour: nameColour,
                  at: NSPoint(x: left, y: y), width: width)

        var keyBits: [String] = []
        if !slot.hotkeyLabel.isEmpty { keyBits.append(slot.hotkeyLabel) }
        if let g = slot.globalHotkey, !g.isEmpty { keyBits.append("global \(g)") }
        if !keyBits.isEmpty {
            y -= 2
            y -= draw(keyBits.joined(separator: "   "),
                      font: NSFont.systemFont(ofSize: NSFont.systemFontSize * 0.88),
                      colour: .secondaryLabelColor,
                      at: NSPoint(x: left, y: y), width: width)
        }
        if !states.isEmpty {
            let text = states.joined(separator: ", ")
            let font = NSFont.systemFont(ofSize: NSFont.systemFontSize * 0.88)
            let h = height(of: text, font: font, width: width)
            _ = draw(text, font: font,
                     colour: missing ? .systemRed : .secondaryLabelColor,
                     at: NSPoint(x: left, y: box.minY + 6 + h), width: width)
        }
    }

    private func stateWords() -> [String] {
        // The same words the label uses, taken from the same place so the two
        // can never disagree.
        let full = slot.buttonLabel(playing: playing)
        let head = "\(slot.number). \(slot.displayName)"
        var rest = full.hasPrefix(head) ? String(full.dropFirst(head.count)) : ""
        if rest.hasPrefix(", ") { rest = String(rest.dropFirst(2)) }
        var parts = rest.isEmpty ? [] : rest.components(separatedBy: ", ")
        parts.removeAll { $0.hasPrefix("key ") || $0.hasPrefix("global ") }
        return parts
    }

    @discardableResult
    private func draw(_ text: String, font: NSFont, colour: NSColor,
                      at point: NSPoint, width: CGFloat) -> CGFloat {
        let style = NSMutableParagraphStyle()
        style.lineBreakMode = .byTruncatingTail
        let attrs: [NSAttributedString.Key: Any] = [
            .font: font, .foregroundColor: colour, .paragraphStyle: style,
        ]
        let h = ceil(font.ascender - font.descender + font.leading)
        (text as NSString).draw(in: NSRect(x: point.x, y: point.y - h, width: width, height: h),
                                withAttributes: attrs)
        return h
    }

    private func height(of text: String, font: NSFont, width: CGFloat) -> CGFloat {
        ceil(font.ascender - font.descender + font.leading)
    }

    override var acceptsFirstResponder: Bool { !slot.hidden }
    override var canBecomeKeyView: Bool { !slot.hidden }
}
