// Press a key, and be told exactly what reached the app.
//
// The Mac counterpart of tools/check_keyboard.py, and it is in the app rather
// than in a test for the same reason that one is in tools rather than in tests:
// some things can only be tested with a real keystroke. Whether VoiceOver hands
// a combination through is not knowable from any documentation and differs with
// one user's own VoiceOver settings, so this asks the machine in front of you.
//
// Like the Windows one, it says "never arrived" rather than reporting a failure
// it cannot stand behind.

import AppKit

final class KeyboardCheckPanel: NSObject {

    private var log: NSTextView!
    private var monitor: Any?
    private var seen = Set<String>()

    private static let wanted: [(String, String)] = [
        ("1", "bank 1, sound 1"),
        ("Shift 1", "bank 1, sound 11"),
        ("Command 1", "bank 2, drop 1"),
        ("Command Shift 1", "bank 2, drop 11"),
        ("Option Command 1", "bank 3, bed 1"),
        ("Option Command Shift 1", "bank 3, bed 11"),
        ("Control 1", "the Windows key for bank 2, if your Mac leaves it free"),
        ("Option Control 1", "the Windows key for bank 3, which VoiceOver usually takes"),
        ("F1", "the shortcut list"),
        ("F2", "rename"),
        ("F3", "sound volume down"),
        ("F5", "bed volume down"),
        ("F7", "playlist volume down"),
        ("Escape", "stop everything"),
        ("Option Space", "stop the last sound"),
        ("Command M", "the microphone"),
        ("Command R", "recording"),
        ("Command B", "go live"),
        ("Command L", "what is playing"),
    ]

    func run(speaker: Speaker) {
        let alert = NSAlert()
        alert.messageText = "Check the keyboard"
        alert.informativeText = """
            Press each combination below. Every key that reaches the app is listed as it \
            arrives, so anything missing from the list is a key something else on this Mac \
            took first, usually VoiceOver.

            Nothing here plays a sound and nothing is saved.
            """
        alert.addButton(withTitle: "Done")

        let box = NSView(frame: NSRect(x: 0, y: 0, width: 580, height: 360))
        let wantedText = NSTextField(wrappingLabelWithString:
            "Try: " + Self.wanted.map(\.0).joined(separator: ",  "))
        wantedText.frame = NSRect(x: 0, y: 286, width: 580, height: 70)
        wantedText.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        wantedText.textColor = .secondaryLabelColor
        box.addSubview(wantedText)

        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 580, height: 278))
        log = NSTextView(frame: scroll.bounds)
        log.isEditable = false
        log.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        log.string = "Waiting for a key.\n"
        log.setAccessibilityLabel("Keys that arrived")
        scroll.documentView = log
        scroll.hasVerticalScroller = true
        box.addSubview(scroll)
        alert.accessoryView = box

        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown]) { [weak self] event in
            self?.record(event, speaker: speaker)
            return nil          // nothing here fires a pad
        }
        alert.runModal()
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil

        let missing = Self.wanted.filter { !seen.contains($0.0) }
        if missing.isEmpty {
            speaker.announceAnswer("Every key checked arrived.")
        } else {
            speaker.announceAnswer("These never arrived: "
                + missing.map { "\($0.0), which would be \($0.1)" }.joined(separator: ". "))
        }
    }

    private func record(_ event: NSEvent, speaker: Speaker) {
        let mods = event.modifierFlags
        var name: String
        switch event.keyCode {
        case 53: name = "Escape"
        case 49: name = "Space"
        case 36: name = "Return"
        case 51: name = "Delete"
        case 122: name = "F1"
        case 120: name = "F2"
        case 99: name = "F3"
        case 118: name = "F4"
        case 96: name = "F5"
        case 97: name = "F6"
        case 98: name = "F7"
        case 100: name = "F8"
        default:
            name = KeyMap.digitFor(event: event)
                ?? (event.charactersIgnoringModifiers?.uppercased() ?? "key \(event.keyCode)")
        }
        // Reported in the order the help text uses, so the two can be compared
        // side by side.
        var ordered: [String] = []
        if mods.contains(.control) { ordered.append("Control") }
        if mods.contains(.option) { ordered.append("Option") }
        if mods.contains(.command) { ordered.append("Command") }
        if mods.contains(.shift) { ordered.append("Shift") }
        let described = (ordered + [name]).joined(separator: " ")
        seen.insert(described)
        log.string += described + "\n"
        log.scrollToEndOfDocument(nil)
        speaker.note(described)
    }
}
