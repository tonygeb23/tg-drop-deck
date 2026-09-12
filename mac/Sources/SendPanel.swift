// Where the show goes when another program on this machine wants it.
//
// One window, five controls, and a paragraph that says the thing everybody
// gets wrong: the main output is NOT the programme. It carries the pads, the
// beds and the running order, and your microphone and every source you are
// catching live on the on air mix. Pointing Preferences, Output at a cable
// hands the other program a soundboard with no voice on it, which is the whole
// reason this window exists.

import AppKit

final class SendPanel: NSObject {

    private let board: Board
    private let sources: [SourceConfig]

    private var onBox: NSButton!
    private var devicePopup: NSPopUpButton!
    private var minusPopup: NSPopUpButton!
    private var gainSlider: NSSlider!
    private var hearBox: NSButton!

    private var outputs: [AudioDeviceInfo] = []
    /// What the minus popup offers, in the order it offers it. Index 0 is
    /// "nothing", so a choice is never an index into the source list.
    private var minusNames: [String] = []

    init(board: Board, sources: [SourceConfig]) {
        self.board = board
        self.sources = sources
        super.init()
    }

    func run(over parent: NSWindow?) -> Bool {
        // **Drop Deck Audio goes first**, when it is there. It is the answer to
        // the question this window asks, and a list sorted by whatever order
        // Core Audio happened to enumerate in makes somebody arrow past it.
        // Everything else keeps the order it came in.
        let all = AudioDevices.outputs()
        outputs = all.filter { $0.uid == VirtualDevice.uid }
            + all.filter { $0.uid != VirtualDevice.uid }

        let alert = NSAlert()
        alert.messageText = "Send this show to another program"
        alert.informativeText = """
            Point this at a virtual audio cable, then set TeamTalk, Zoom, Discord or \
            OBS to take that same cable as its microphone. It sends the whole show: \
            your pads, your beds, your running order, your microphone with its \
            processing, and every source you are catching. It does not need you to be \
            on air or recording.

            Do NOT point Preferences, Output at a cable instead. That output carries \
            your sounds and NOT your microphone, so the other program would get a \
            soundboard with no voice on it, and you would lose your own speakers.
            """
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")

        let box = NSStackView()
        box.orientation = .vertical
        box.alignment = .leading
        box.spacing = 8
        box.frame = NSRect(x: 0, y: 0, width: 520, height: 300)

        onBox = NSButton(checkboxWithTitle: "Send this show to another program",
                         target: nil, action: nil)
        onBox.state = board.sendOn ? .on : .off
        onBox.setAccessibilityLabel("Send this show to another program")
        box.addArrangedSubview(onBox)

        devicePopup = NSPopUpButton()
        devicePopup.addItem(withTitle: "System default output")
        for device in outputs {
            // Named for what it IS here, because "Drop Deck Audio" in a list of
            // sound cards does not say that it is the one built for this.
            devicePopup.addItem(withTitle: device.uid == VirtualDevice.uid
                ? "\(device.name), the cable built into Drop Deck"
                : device.name)
        }
        if let uid = board.sendDeviceUID,
           let match = outputs.firstIndex(where: { $0.uid == uid }) {
            devicePopup.selectItem(at: match + 1)
        }
        devicePopup.setAccessibilityLabel("Send it out of")
        box.addArrangedSubview(labelled("Send it out of", devicePopup))

        // Mix minus. The list is built from the sources the board really has,
        // and the CHOICE IS STORED BY NAME rather than by position, because a
        // source list gets reordered and an index would quietly start excluding
        // somebody else.
        minusPopup = NSPopUpButton()
        minusPopup.addItem(withTitle: "Nothing, send everything")
        minusNames = [""]
        for source in sources {
            minusPopup.addItem(withTitle: source.name)
            minusNames.append(source.name)
        }
        minusPopup.addItem(withTitle: SourceGroup.micLabel)
        minusNames.append(SourceGroup.micLabel)
        // A name the board remembers that no longer matches anything is kept in
        // the list and marked, rather than silently reset to "send everything".
        // Losing a setting by opening the window that shows it is the worst
        // kind of bug, and this one would be heard as an echo on the next show.
        let saved = board.sendMinus.trimmingCharacters(in: .whitespaces)
        if !saved.isEmpty, !minusNames.contains(where: { $0.lowercased() == saved.lowercased() }) {
            minusPopup.addItem(withTitle: "\(saved), which is not here any more")
            minusNames.append(saved)
        }
        if let at = minusNames.firstIndex(where: { $0.lowercased() == saved.lowercased() }) {
            minusPopup.selectItem(at: at)
        }
        minusPopup.setAccessibilityLabel("Leave one source out")
        box.addArrangedSubview(labelled("Leave one source out, so it does not hear itself",
                                        minusPopup))

        let minusNote = note("Broadcasting calls this mix minus. If you capture "
            + "TeamTalk as a source and you are sending to TeamTalk, leave TeamTalk "
            + "out, or everybody in the call hears themselves a moment late.")
        box.addArrangedSubview(minusNote)

        gainSlider = NSSlider(value: Double(board.sendGainDB),
                              minValue: Double(C.minMicGainDB),
                              maxValue: Double(C.maxMicGainDB),
                              target: nil, action: nil)
        gainSlider.numberOfTickMarks = 13
        gainSlider.allowsTickMarkValuesOnly = false
        gainSlider.setAccessibilityLabel("Level, in decibels")
        box.addArrangedSubview(labelled("Level, in decibels", gainSlider))

        hearBox = NSButton(checkboxWithTitle: "Hear what is being sent (Command+Shift+H)",
                           target: nil, action: nil)
        hearBox.state = board.sendMonitor ? .on : .off
        hearBox.setAccessibilityLabel("Hear what is being sent")
        box.addArrangedSubview(hearBox)

        // And say where the cable stands, because the commonest reason this
        // window is open at all is that somebody has nothing to point it at.
        if !VirtualDevice.isPresent {
            box.addArrangedSubview(note("You have no \(VirtualDevice.name) yet. "
                + "On air, Drop Deck Audio installs the cable that comes with "
                + "this app, and then it is in both lists with nothing else to "
                + "set up. Any other virtual cable works here too."))
        }

        box.addArrangedSubview(note("Command+Shift+O says whether it is arriving "
            + "cleanly. Command+Shift+W reads out where everything is going."))

        alert.accessoryView = box
        alert.window.initialFirstResponder = onBox
        return alert.runModal() == .alertFirstButtonReturn
    }

    /// Nothing is written to the board until OK, and then all of it at once.
    func apply(to board: Board) {
        board.sendOn = onBox.state == .on
        let chosen = devicePopup.indexOfSelectedItem
        board.sendDeviceUID = chosen == 0 ? nil : outputs[chosen - 1].uid
        board.sendDeviceName = chosen == 0 ? nil : outputs[chosen - 1].name
        let minus = minusPopup.indexOfSelectedItem
        board.sendMinus = (minus > 0 && minus < minusNames.count) ? minusNames[minus] : ""
        board.sendGainDB = Float(gainSlider.doubleValue.rounded())
        board.sendMonitor = hearBox.state == .on
    }

    // ------------------------------------------------------------ helpers ---

    private func labelled(_ title: String, _ control: NSView) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 2
        let label = NSTextField(labelWithString: title)
        label.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        label.textColor = .secondaryLabelColor
        stack.addArrangedSubview(label)
        stack.addArrangedSubview(control)
        control.widthAnchor.constraint(equalToConstant: 500).isActive = true
        return stack
    }

    private func note(_ text: String) -> NSTextField {
        let field = NSTextField(wrappingLabelWithString: text)
        field.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        field.textColor = .secondaryLabelColor
        field.preferredMaxLayoutWidth = 500
        return field
    }

}
