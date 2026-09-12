// The windows behind the On air menu.
//
// Every one of them is driven from the keyboard first, because the show is
// running while they are open. Source control in particular is used mid link
// and needs neither Tab nor a mouse.

import AppKit
import Carbon.HIToolbox

// ------------------------------------------------------------ hotkey capture ---

enum HotkeyResult {
    case chosen(HotkeyCombination)
    case cleared
}

/// Press the combination you want.
///
/// Everything is captured with a local monitor so keys are seen before any
/// control eats them, and every capture is spoken, because a read only field
/// changing its text fires no accessibility event a screen reader will notice.
final class HotkeyPanel {

    private let title: String
    private let global: Bool
    private let current: String?
    private let speaker: Speaker
    private var captured: HotkeyCombination?
    private var readout: NSTextField!
    private var warning: NSTextField!

    init(title: String, global: Bool, current: String?, speaker: Speaker) {
        self.title = title
        self.global = global
        self.current = current
        self.speaker = speaker
    }

    func run(over parent: NSWindow?) -> HotkeyResult? {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = global
            ? "Press the combination you want. It will fire this sound from any program, "
              + "so it always needs Control, Option, Command or Shift with it."
            : "Press the combination you want. Press Delete to clear it."
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Clear hotkey")
        alert.addButton(withTitle: "Cancel")

        let box = NSStackView()
        box.orientation = .vertical
        box.alignment = .leading
        box.spacing = 6
        box.frame = NSRect(x: 0, y: 0, width: 420, height: 70)

        let label = NSTextField(labelWithString: "Hotkey")
        label.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        label.textColor = .secondaryLabelColor
        box.addArrangedSubview(label)

        readout = NSTextField(labelWithString: current ?? "No hotkey set")
        readout.font = NSFont.boldSystemFont(ofSize: NSFont.systemFontSize * 1.2)
        readout.setAccessibilityLabel("Hotkey, \(current ?? "none set")")
        box.addArrangedSubview(readout)

        warning = NSTextField(wrappingLabelWithString: "")
        warning.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        warning.textColor = .systemRed
        warning.widthAnchor.constraint(equalToConstant: 410).isActive = true
        box.addArrangedSubview(warning)

        alert.accessoryView = box

        // Claimed rather than monitored, so the digit map cannot fire a pad
        // while somebody is pressing the very combination they want to bind.
        var response: NSApplication.ModalResponse = .cancel
        ModalKeys.claim({ [weak self] event in self?.capture(event) ?? false },
                        window: alert.window) {
            response = alert.runModal()
        }

        switch response {
        case .alertFirstButtonReturn:
            if let captured { return .chosen(captured) }
            return nil
        case .alertSecondButtonReturn:
            return .cleared
        default:
            return nil
        }
    }

    /// Returns true when the key was taken as a capture rather than passed on.
    private func capture(_ event: NSEvent) -> Bool {
        let code = UInt32(event.keyCode)
        // Escape leaves, Return accepts, Tab moves: those are how the dialog is
        // worked and they cannot also be captured.
        if code == UInt32(kVK_Escape) || code == UInt32(kVK_Return)
            || code == UInt32(kVK_ANSI_KeypadEnter) || code == UInt32(kVK_Tab) {
            let bare = event.modifierFlags
                .intersection([.command, .option, .control, .shift]).isEmpty
            if bare { return false }
        }
        if code == UInt32(kVK_Delete) || code == UInt32(kVK_ForwardDelete) {
            captured = nil
            readout.stringValue = "No hotkey set"
            readout.setAccessibilityLabel("Hotkey, none set")
            warning.stringValue = ""
            speaker.announce("Hotkey cleared.")
            return true
        }
        guard let combination = HotkeyCombination.from(event: event) else {
            return true
        }
        // Command Q and Command W close things everywhere. Taking one would be
        // taking a key the whole system relies on.
        if combination.modifiers == UInt32(cmdKey)
            && (combination.keyCode == UInt32(kVK_ANSI_Q)
                || combination.keyCode == UInt32(kVK_ANSI_W)) {
            warning.stringValue = "\(combination.label) closes or quits in every program. "
                                + "Pick another combination."
            speaker.announce(warning.stringValue)
            return true
        }
        if global && combination.isBare {
            warning.stringValue = "A global hotkey needs a modifier. "
                + "\(combination.label) on its own would be taken from every other program."
            speaker.announce(warning.stringValue)
            return true
        }
        captured = combination
        readout.stringValue = combination.label
        readout.setAccessibilityLabel("Hotkey, \(combination.spoken)")
        warning.stringValue = ""
        speaker.announce(combination.spoken)
        return true
    }
}

// -------------------------------------------------------------- the sources ---

/// One list plus one set of controls that follows it. A dialog per source is
/// far more to hear.
final class SourcesPanel: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private let board: Board
    private var working: [SourceConfig]
    private var table: NSTableView!
    private var nameField: NSTextField!
    private var kindPopup: NSPopUpButton!
    private var devicePopup: NSPopUpButton!
    private var programPopup: NSPopUpButton!
    private var channelPopup: NSPopUpButton!
    private var gainSlider: NSSlider!
    private var onAirBox: NSButton!
    private var monitorBox: NSButton!
    private var delaySlider: NSSlider!
    private var delayReadout: NSTextField!

    private var devices: [AudioDeviceInfo] = []
    private var programs: [AudioProcessInfo] = []

    init(board: Board) {
        self.board = board
        working = board.sources
        super.init()
    }

    func run(over parent: NSWindow?) -> Bool {
        devices = AudioDevices.inputs()
        programs = AudioProcesses.all()
        // A program the board already names stays in the list even when it is
        // not running at this moment, because otherwise opening this panel and
        // pressing OK would quietly throw that choice away. Losing a setting by
        // looking at it is the worst kind of bug.
        for c in working where c.isProcess {
            guard let bundle = c.bundleID, !bundle.isEmpty,
                  !programs.contains(where: { $0.bundleID == bundle }) else { continue }
            programs.append(AudioProcessInfo(
                objectID: 0, pid: 0, bundleID: bundle,
                name: bundle.components(separatedBy: ".").last ?? bundle,
                isPlaying: false, isKnownToCoreAudio: false))
        }

        let alert = NSAlert()
        alert.messageText = "Audio sources"
        alert.informativeText = """
            Anything else that should be on the air with you: a co-host's microphone, \
            a hardware mixer, or one single program captured straight from it.

            Your screen reader is in the program list, so a demonstration goes out the \
            way any other program does. Every program that is running is listed, whether \
            or not it is making a sound yet, and the ones playing right now come first.
            """
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")

        let box = NSView(frame: NSRect(x: 0, y: 0, width: 620, height: 420))

        let scroll = NSScrollView(frame: NSRect(x: 0, y: 250, width: 620, height: 160))
        table = NSTableView(frame: scroll.bounds)
        for (id, title, width) in [("name", "Name", 200), ("kind", "Kind", 110),
                                   ("from", "Taking from", 190), ("air", "On air", 70)] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id))
            column.title = title
            column.width = CGFloat(width)
            table.addTableColumn(column)
        }
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel("Sources")
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        box.addSubview(scroll)

        let add = NSButton(title: "Add a source", target: self, action: #selector(addSource))
        add.frame = NSRect(x: 0, y: 214, width: 150, height: 28)
        add.bezelStyle = .rounded
        box.addSubview(add)
        let remove = NSButton(title: "Remove this one", target: self,
                              action: #selector(removeSource))
        remove.frame = NSRect(x: 158, y: 214, width: 160, height: 28)
        remove.bezelStyle = .rounded
        box.addSubview(remove)

        func label(_ text: String, _ y: CGFloat) {
            let l = NSTextField(labelWithString: text)
            l.frame = NSRect(x: 0, y: y, width: 200, height: 16)
            l.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
            l.textColor = .secondaryLabelColor
            box.addSubview(l)
        }

        label("Called", 190)
        nameField = NSTextField(frame: NSRect(x: 0, y: 164, width: 300, height: 24))
        nameField.setAccessibilityLabel("Called")
        nameField.target = self
        nameField.action = #selector(fieldChanged)
        box.addSubview(nameField)

        label("Take audio from", 140)
        kindPopup = NSPopUpButton(frame: NSRect(x: 0, y: 114, width: 300, height: 26))
        kindPopup.addItems(withTitles: ["A sound card or a cable", "One program"])
        kindPopup.setAccessibilityLabel("Take audio from")
        kindPopup.target = self
        kindPopup.action = #selector(fieldChanged)
        box.addSubview(kindPopup)

        label("Device", 90)
        devicePopup = NSPopUpButton(frame: NSRect(x: 0, y: 64, width: 300, height: 26))
        devicePopup.addItem(withTitle: "Default input")
        for d in devices { devicePopup.addItem(withTitle: d.name) }
        devicePopup.setAccessibilityLabel("Device")
        devicePopup.target = self
        devicePopup.action = #selector(fieldChanged)
        box.addSubview(devicePopup)

        label("Program", 90)
        programPopup = NSPopUpButton(frame: NSRect(x: 310, y: 64, width: 300, height: 26))
        // The first row is "not chosen", exactly as the device popup has, so a
        // brand new source starts with nothing chosen instead of silently
        // inheriting whatever the row above it points at.
        programPopup.addItem(withTitle: "not chosen")
        for p in programs {
            // Say which of the three a program is, because "not in the list"
            // and "in the list but silent" are different problems and only one
            // of them is yours to fix.
            let suffix = p.isPlaying ? "  (playing now)"
                       : p.isKnownToCoreAudio ? "  (has played)" : "  (running)"
            programPopup.addItem(withTitle: p.name + suffix)
        }
        programPopup.setAccessibilityLabel("Program")
        programPopup.target = self
        programPopup.action = #selector(fieldChanged)
        box.addSubview(programPopup)

        label("Which channel", 140)
        channelPopup = NSPopUpButton(frame: NSRect(x: 310, y: 114, width: 300, height: 26))
        for c in MicChannel.allCases { channelPopup.addItem(withTitle: c.label) }
        channelPopup.setAccessibilityLabel("Which channel")
        channelPopup.target = self
        channelPopup.action = #selector(fieldChanged)
        box.addSubview(channelPopup)

        label("Gain in decibels", 190)
        gainSlider = NSSlider(value: 0, minValue: -24, maxValue: 24,
                              target: self, action: #selector(fieldChanged))
        gainSlider.frame = NSRect(x: 310, y: 164, width: 300, height: 24)
        gainSlider.numberOfTickMarks = 49
        gainSlider.allowsTickMarkValuesOnly = true
        gainSlider.setAccessibilityLabel("Gain in decibels")
        box.addSubview(gainSlider)

        onAirBox = NSButton(checkboxWithTitle: "Put this on the air", target: self,
                            action: #selector(fieldChanged))
        onAirBox.frame = NSRect(x: 0, y: 30, width: 250, height: 22)
        box.addSubview(onAirBox)

        monitorBox = NSButton(checkboxWithTitle: "Hear it yourself", target: self,
                              action: #selector(fieldChanged))
        monitorBox.frame = NSRect(x: 310, y: 30, width: 250, height: 22)
        box.addSubview(monitorBox)

        // Holding a source back. Darrell, a listener, 10 September 2026, on a
        // capture card: "in obs, we can adjust the offset for the source, so it
        // does not lag as much."
        //
        // Everything above is laid out by hand against the bottom of the box,
        // so a new row at the bottom means moving all of it. One nudge here
        // rather than thirty numbers edited by hand, which is the version of
        // this that gets one of them wrong and clips a control off the window.
        box.setFrameSize(NSSize(width: 620, height: 452))
        for view in box.subviews { view.frame.origin.y += 32 }
        label("Hold this one back, in milliseconds", 4)
        delaySlider = NSSlider(value: 0, minValue: 0,
                               maxValue: Double(C.maxSourceDelayMS),
                               target: self, action: #selector(fieldChanged))
        delaySlider.frame = NSRect(x: 220, y: 0, width: 240, height: 24)
        delaySlider.numberOfTickMarks = 21
        delaySlider.allowsTickMarkValuesOnly = false
        // **The label says what it cannot do, because the control cannot.** It
        // can only ever make a source LATER: nothing can make live audio arrive
        // earlier than it does, so a source running BEHIND is corrected by
        // holding the others back instead. OBS works the same way and it
        // surprises everybody once.
        delaySlider.setAccessibilityLabel("Hold this one back, in milliseconds. "
            + "It can only ever make a source later. If this one is running "
            + "behind the others, hold the others back instead")
        box.addSubview(delaySlider)
        delayReadout = NSTextField(labelWithString: "")
        delayReadout.frame = NSRect(x: 470, y: 4, width: 140, height: 16)
        delayReadout.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        delayReadout.textColor = .secondaryLabelColor
        box.addSubview(delayReadout)

        alert.accessoryView = box
        if !working.isEmpty {
            table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        }
        loadSelection()

        guard alert.runModal() == .alertFirstButtonReturn else { return false }
        board.sources = working
        return true
    }

    // -------------------------------------------------------------- editing ---

    private var selected: Int { table.selectedRow }

    private func loadSelection() {
        let enabled = selected >= 0 && selected < working.count
        let controls: [NSControl] = [nameField, kindPopup, devicePopup, programPopup,
                                     channelPopup, gainSlider, onAirBox, monitorBox,
                                     delaySlider]
        for control in controls { control.isEnabled = enabled }
        guard enabled else {
            nameField.stringValue = ""
            return
        }
        let c = working[selected]
        nameField.stringValue = c.name
        kindPopup.selectItem(at: c.isProcess ? 1 : 0)
        devicePopup.selectItem(at: (devices.firstIndex { $0.uid == c.deviceUID }
                                    .map { $0 + 1 }) ?? 0)
        programPopup.selectItem(at: (programs.firstIndex { $0.bundleID == c.bundleID }
                                     .map { $0 + 1 }) ?? 0)
        // A captured program is always kept in stereo, so the popup SAYS
        // stereo rather than sitting dimmed on "both, mixed together". Dimmed
        // does not mean "does not apply" to somebody reading it aloud: it
        // reads as the setting in force, and it would be the opposite of what
        // actually happens to that program's audio.
        channelPopup.selectItem(at: MicChannel.allCases.firstIndex(
            of: c.isProcess ? .stereo : c.channel) ?? 0)
        gainSlider.doubleValue = Double(c.gainDB)
        onAirBox.state = c.onAir ? .on : .off
        monitorBox.state = c.monitor ? .on : .off
        delaySlider.doubleValue = c.delayMS
        sayDelay(c.delayMS)
        devicePopup.isEnabled = !c.isProcess
        programPopup.isEnabled = c.isProcess
        channelPopup.isEnabled = !c.isProcess
    }

    /// The delay in words beside the slider. Zero is "not held back at all"
    /// rather than "0 ms", because zero is the ordinary state and a number
    /// invites somebody to wonder what is wrong with it.
    private func sayDelay(_ ms: Double) {
        delayReadout?.stringValue = ms <= 0
            ? "not held back"
            : "\(Int(ms)) ms later"
    }

    @objc private func fieldChanged() {
        guard selected >= 0, selected < working.count else { return }
        var c = working[selected]
        let wasProcess = c.isProcess
        let name = nameField.stringValue.trimmingCharacters(in: .whitespaces)
        if !name.isEmpty { c.name = name }
        c.kind = kindPopup.indexOfSelectedItem == 1 ? "process" : "device"
        let d = devicePopup.indexOfSelectedItem
        c.deviceUID = d == 0 ? nil : devices[d - 1].uid
        let p = programPopup.indexOfSelectedItem
        c.bundleID = (p >= 1 && p <= programs.count) ? programs[p - 1].bundleID : nil
        // Only a device has a channel to choose. A program shows stereo
        // because that is what happens to it, and its stored choice is left
        // untouched so switching the source back to a device brings the real
        // one straight back rather than quietly becoming stereo.
        if !c.isProcess && !wasProcess {
            c.channel = MicChannel.allCases[max(0, channelPopup.indexOfSelectedItem)]
        }
        channelPopup.selectItem(at: MicChannel.allCases.firstIndex(
            of: c.isProcess ? .stereo : c.channel) ?? 0)
        c.gainDB = Float(gainSlider.doubleValue.rounded())
        c.onAir = onAirBox.state == .on
        c.monitor = monitorBox.state == .on
        c.delayMS = delaySlider.doubleValue.rounded()
        sayDelay(c.delayMS)
        working[selected] = c
        devicePopup.isEnabled = !c.isProcess
        programPopup.isEnabled = c.isProcess
        channelPopup.isEnabled = !c.isProcess
        table.reloadData()
        table.selectRowIndexes(IndexSet(integer: selected), byExtendingSelection: false)
    }

    @objc private func addSource() {
        var c = SourceConfig()
        c.name = "Source \(working.count + 1)"
        working.append(c)
        table.reloadData()
        table.selectRowIndexes(IndexSet(integer: working.count - 1), byExtendingSelection: false)
        loadSelection()
    }

    @objc private func removeSource() {
        guard selected >= 0, selected < working.count else { return }
        working.remove(at: selected)
        table.reloadData()
        if !working.isEmpty {
            table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        }
        loadSelection()
    }

    func numberOfRows(in tableView: NSTableView) -> Int { working.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard let tableColumn, row < working.count else { return nil }
        let c = working[row]
        let text: String
        switch tableColumn.identifier.rawValue {
        case "name": text = c.name
        case "kind": text = c.isProcess ? "Program" : "Sound card"
        case "from":
            text = c.isProcess
                ? (programs.first { $0.bundleID == c.bundleID }?.name ?? c.bundleID ?? "not chosen")
                : (devices.first { $0.uid == c.deviceUID }?.name ?? "Default input")
        default: text = c.onAir ? "yes" : "no"
        }
        let field = NSTextField(labelWithString: text)
        field.setAccessibilityLabel(text)
        return field
    }

    func tableViewSelectionDidChange(_ notification: Notification) { loadSelection() }
}


// -------------------------------------------------------- source control ---

/// Mute, solo, rename or remove, mid show.
///
/// **A STATE is a check box and an ACTION is a button.** Until 3.5.2 left and
/// right cycled mute, solo, rename and remove, and Space did whichever you had
/// landed on. That is a mode: something to remember, and something the window
/// had to keep announcing because nothing on screen said which of the four you
/// were on. Tony asked for the mode on 5 September and asked for it to go on
/// the 8th, and he was right both times. A check box says what it is the
/// moment focus lands on it, and Space toggles it the way Space toggles every
/// check box anywhere.
///
/// The digits stay, because during a link you do not want to arrow anywhere.
final class SourceControlPanel: NSObject {

    private let group: SourceGroup
    private let mic: MicInput
    private let speaker: Speaker
    private var table: NSTableView!
    private var mutedBox: NSButton!
    private var soloBox: NSButton!
    private var doing: NSTextField!
    private var renameButton: NSButton!
    private var removeButton: NSButton!
    private var alert: NSAlert!

    init(group: SourceGroup, mic: MicInput, speaker: Speaker) {
        self.group = group
        self.mic = mic
        self.speaker = speaker
        super.init()
    }

    private var rows: [(id: String, label: String, muted: Bool, solo: Bool, air: Bool)] {
        var out: [(String, String, Bool, Bool, Bool)] = [
            (micDuckKey, "The microphone", false, group.soloed == micDuckKey,
             mic.isOpen && mic.onAir),
        ]
        for source in group.all {
            out.append((source.config.id, source.config.name, source.config.muted,
                        group.soloed == source.config.id, source.config.onAir))
        }
        return out
    }

    func run(over parent: NSWindow?) {
        alert = NSAlert()
        alert.messageText = "Source control"
        alert.informativeText = "Up and down choose a source. Tab to the boxes and "
            + "buttons for what to do with it. A digit jumps straight to a source, "
            + "and zero is the microphone."
        alert.addButton(withTitle: "Close")

        let width: CGFloat = 620
        let box = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 340))
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 110, width: width, height: 220))
        table = NSTableView(frame: scroll.bounds)
        for (id, title, w) in [("n", "Number", 70), ("name", "Source", 200),
                               ("muted", "Muted", 80), ("solo", "Solo", 80),
                               ("air", "On air", 80)] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id))
            column.title = title
            column.width = CGFloat(w)
            table.addTableColumn(column)
        }
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel("Sources")
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        box.addSubview(scroll)

        // The labels are "Muted" and "Solo" and they NEVER change. The tick
        // carries the value; a control's accessible name must not be rewritten
        // when its value moves.
        mutedBox = NSButton(checkboxWithTitle: "Muted", target: self,
                            action: #selector(mutedToggled))
        mutedBox.frame = NSRect(x: 0, y: 76, width: 200, height: 24)
        mutedBox.setAccessibilityLabel("Muted")
        mutedBox.toolTip = "This source stops going out, and stops being recorded. "
                         + "You go on hearing everything else."
        box.addSubview(mutedBox)

        soloBox = NSButton(checkboxWithTitle: "Solo", target: self,
                           action: #selector(soloToggled))
        soloBox.frame = NSRect(x: 210, y: 76, width: 200, height: 24)
        soloBox.setAccessibilityLabel("Solo")
        soloBox.toolTip = "Only the soloed sources go out. Everything else is silent "
                        + "until nothing is soloed."
        box.addSubview(soloBox)

        doing = NSTextField(wrappingLabelWithString: "")
        doing.frame = NSRect(x: 0, y: 40, width: width, height: 30)
        doing.setAccessibilityLabel("What this does")
        box.addSubview(doing)

        renameButton = NSButton(title: "Rename...", target: self,
                                action: #selector(renamePressed))
        renameButton.frame = NSRect(x: 0, y: 4, width: 130, height: 30)
        renameButton.setAccessibilityLabel("Rename")
        box.addSubview(renameButton)

        removeButton = NSButton(title: "Remove...", target: self,
                                action: #selector(removePressed))
        removeButton.frame = NSRect(x: 140, y: 4, width: 130, height: 30)
        removeButton.setAccessibilityLabel("Remove")
        box.addSubview(removeButton)

        alert.accessoryView = box
        table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        alert.window.initialFirstResponder = table
        loadSelection()

        // The digits are claimed rather than monitored: a second local monitor
        // raced the window's own and sometimes fired pads instead. The window
        // is named so a nested rename box takes the keyboard back while it is
        // up; see ModalKeys.owner for what went wrong without it.
        ModalKeys.claim({ [weak self] event in self?.handle(event) ?? false },
                        window: alert.window) {
            alert.runModal()
        }
    }

    private func handle(_ event: NSEvent) -> Bool {
        guard NSApp.keyWindow === alert.window else { return false }
        guard !(alert.window.firstResponder is NSTextView) else { return false }
        let mods = event.modifierFlags.intersection([.command, .option, .control, .shift])
        guard mods.isEmpty else { return false }
        if event.keyCode == 53 {                           // Escape
            NSApp.stopModal(withCode: .alertFirstButtonReturn)
            return true
        }
        // The boxes and buttons want their own keys. Only act on a key while
        // the LIST has focus.
        guard alert.window.firstResponder === table else { return false }
        if event.charactersIgnoringModifiers == String(UnicodeScalar(NSF2FunctionKey)!) {
            rename()
            return true
        }
        if event.charactersIgnoringModifiers == String(UnicodeScalar(NSDeleteFunctionKey)!)
            || event.charactersIgnoringModifiers == "\u{8}" {
            remove()
            return true
        }
        // A digit jumps to that source. Its NUMBER is its position, not its
        // name, so renaming never renumbers anything.
        if let chars = event.charactersIgnoringModifiers, let digit = Int(chars),
           digit >= 0, digit < rows.count {
            table.selectRowIndexes(IndexSet(integer: digit), byExtendingSelection: false)
            loadSelection()
            return true
        }
        return false
    }

    private func selected() -> (id: String, label: String, muted: Bool, solo: Bool, air: Bool)? {
        let row = max(0, table.selectedRow)
        let all = rows
        return row < all.count ? all[row] : nil
    }

    /// Put the boxes where the selected row is.
    ///
    /// **Deliberately not the same path as applying a change.** In wx, setting
    /// a check box raises its own event, so arrowing down the list wrote the
    /// displayed value straight back onto every source it passed and silently
    /// muted them, and Windows carries a `_syncing` guard because of it.
    /// Setting `NSButton.state` sends no action here, so the guard is not
    /// needed. Keeping the two paths apart is what makes sure it stays that
    /// way.
    private func loadSelection() {
        guard let entry = selected() else { return }
        let isMic = entry.id == micDuckKey
        mutedBox.state = entry.muted ? .on : .off
        soloBox.state = entry.solo ? .on : .off
        mutedBox.isEnabled = !isMic
        renameButton.isEnabled = !isMic
        removeButton.isEnabled = !isMic
        // A disabled control leaves the Tab loop, so the reason has to be
        // somewhere a Tab user will pass. Here.
        doing.stringValue = isMic
            ? "The microphone. It cannot be renamed or removed; Command M turns it off."
            : "\(entry.label). The boxes and buttons below act on this one."
    }

    @objc private func mutedToggled() {
        guard let entry = selected(), entry.id != micDuckKey,
              let source = group.source(id: entry.id) else {
            mutedBox.state = .off
            speaker.announceAnswer("The microphone is turned off with Command M, "
                                 + "not muted here")
            return
        }
        source.config.muted = mutedBox.state == .on
        refresh()
        speaker.announceState("\(entry.label) \(source.config.muted ? "muted" : "unmuted")")
    }

    @objc private func soloToggled() {
        guard let entry = selected() else { return }
        if soloBox.state == .on {
            group.soloed = entry.id
            speaker.announceState("\(entry.label) soloed. Everything else is silent.")
        } else {
            group.soloed = nil
            speaker.announceState("\(entry.label) no longer soloed. Everything is back")
        }
        refresh()
    }

    @objc private func renamePressed() { rename() }
    @objc private func removePressed() { remove() }

    private func rename() {
        guard let entry = selected() else { return }
        if entry.id == micDuckKey {
            speaker.announceAnswer("The microphone is always called the microphone")
            return
        }
        guard let source = group.source(id: entry.id) else { return }
        let alert = NSAlert()
        alert.messageText = "Rename \(source.config.name)"
        alert.addButton(withTitle: "Rename")
        alert.addButton(withTitle: "Cancel")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.stringValue = source.config.name
        field.setAccessibilityLabel("Name")
        alert.accessoryView = field
        alert.window.initialFirstResponder = field
        field.currentEditor()?.selectAll(nil)
        if alert.runModal() == .alertFirstButtonReturn {
            let name = field.stringValue.trimmingCharacters(in: .whitespaces)
            if !name.isEmpty && name != source.config.name {
                source.config.name = name
                speaker.announceAnswer("Renamed to \(name)")
            } else {
                speaker.announceAnswer("Left as \(source.config.name)")
            }
        } else {
            speaker.announceAnswer("Kept")
        }
        refresh()
    }

    private func remove() {
        guard let entry = selected() else { return }
        if entry.id == micDuckKey {
            speaker.announceAnswer("The microphone cannot be removed. "
                                 + "Command M turns it off.")
            return
        }
        let confirm = NSAlert()
        confirm.messageText = "Remove \(entry.label)?"
        confirm.informativeText = "It stops going out and its settings are forgotten."
        // The safe answer is the default.
        confirm.addButton(withTitle: "Cancel")
        confirm.addButton(withTitle: "Remove")
        guard confirm.runModal() == .alertSecondButtonReturn else {
            speaker.announceAnswer("Kept")
            return
        }
        let row = max(0, table.selectedRow)
        if let source = group.source(id: entry.id) {
            source.stop()
            source.config.onAir = false
        }
        speaker.announceAnswer("Removed \(entry.label)")
        table.reloadData()
        // The cursor lands on the row that took its place rather than off the
        // end of the list.
        let next = min(row, max(0, rows.count - 1))
        table.selectRowIndexes(IndexSet(integer: next), byExtendingSelection: false)
        loadSelection()
    }

    private func refresh() {
        let row = max(0, table.selectedRow)
        table.reloadData()
        table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
        loadSelection()
    }
}

extension SourceControlPanel: NSTableViewDataSource, NSTableViewDelegate {

    func numberOfRows(in tableView: NSTableView) -> Int { rows.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        let all = rows
        guard row < all.count, let column = tableColumn else { return nil }
        let entry = all[row]
        let text: String
        switch column.identifier.rawValue {
        case "n": text = row == 0 ? "Mic" : String(row)
        case "name": text = entry.label
        case "muted": text = entry.muted ? "yes" : "no"
        case "solo": text = entry.solo ? "yes" : "no"
        default: text = entry.air ? "yes" : "no"
        }
        let cell = NSTextField(labelWithString: text)
        cell.setAccessibilityLabel(text)
        return cell
    }

    /// Nothing is spoken on arrow. The row already carries the number, the
    /// name, muted, solo and on air. The old sentence existed only because the
    /// mode had to be announced, and with the mode gone it would be the row
    /// read twice.
    func tableViewSelectionDidChange(_ notification: Notification) { loadSelection() }
}
