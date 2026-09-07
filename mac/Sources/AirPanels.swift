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
    private var monitor: Any?

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

        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown]) {
            [weak self] event in
            guard let self else { return event }
            return self.capture(event) ? nil : event
        }
        let response = alert.runModal()
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil

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

        let alert = NSAlert()
        alert.messageText = "Audio sources"
        alert.informativeText = """
            Anything else that should be on the air with you: a co-host's microphone, \
            a hardware mixer, or one single program captured straight from it.

            Your screen reader is in the program list, so a demonstration goes out the \
            way any other program does.
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
        for p in programs {
            programPopup.addItem(withTitle: p.isPlaying ? "\(p.name)  (playing)" : p.name)
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
                                     channelPopup, gainSlider, onAirBox, monitorBox]
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
        if let bundle = c.bundleID,
           let index = programs.firstIndex(where: { $0.bundleID == bundle }) {
            programPopup.selectItem(at: index)
        }
        channelPopup.selectItem(at: MicChannel.allCases.firstIndex(of: c.channel) ?? 0)
        gainSlider.doubleValue = Double(c.gainDB)
        onAirBox.state = c.onAir ? .on : .off
        monitorBox.state = c.monitor ? .on : .off
        devicePopup.isEnabled = !c.isProcess
        programPopup.isEnabled = c.isProcess
        channelPopup.isEnabled = !c.isProcess
    }

    @objc private func fieldChanged() {
        guard selected >= 0, selected < working.count else { return }
        var c = working[selected]
        let name = nameField.stringValue.trimmingCharacters(in: .whitespaces)
        if !name.isEmpty { c.name = name }
        c.kind = kindPopup.indexOfSelectedItem == 1 ? "process" : "device"
        let d = devicePopup.indexOfSelectedItem
        c.deviceUID = d == 0 ? nil : devices[d - 1].uid
        let p = programPopup.indexOfSelectedItem
        if p >= 0 && p < programs.count { c.bundleID = programs[p].bundleID }
        c.channel = MicChannel.allCases[max(0, channelPopup.indexOfSelectedItem)]
        c.gainDB = Float(gainSlider.doubleValue.rounded())
        c.onAir = onAirBox.state == .on
        c.monitor = monitorBox.state == .on
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

/// Mute, solo, rename or remove, mid show, from a list you drive with the
/// arrow keys.
///
/// Two axes: up and down choose a source, left and right choose an action,
/// Space does it. A digit jumps straight to that source and zero is the
/// microphone, because during a link you do not want to arrow anywhere.
final class SourceControlPanel: NSObject {

    private let group: SourceGroup
    private let mic: MicInput
    private let speaker: Speaker
    private var table: NSTableView!
    private var actionLabel: NSTextField!
    private var monitor: Any?
    private var action = 0
    private static let actions = ["mute", "solo", "rename", "remove"]

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
        let alert = NSAlert()
        alert.messageText = "Source control"
        alert.informativeText = "Up and down choose a source. Left and right choose what "
            + "Space will do. A digit jumps straight to a source, and zero is the microphone."
        alert.addButton(withTitle: "Close")

        let box = NSView(frame: NSRect(x: 0, y: 0, width: 560, height: 280))
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 30, width: 560, height: 250))
        table = NSTableView(frame: scroll.bounds)
        for (id, title, width) in [("n", "Number", 70), ("name", "Source", 220),
                                   ("muted", "Muted", 70), ("solo", "Solo", 70),
                                   ("air", "On air", 80)] {
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

        actionLabel = NSTextField(labelWithString: "")
        actionLabel.frame = NSRect(x: 0, y: 4, width: 560, height: 20)
        actionLabel.setAccessibilityLabel("What Space will do")
        box.addSubview(actionLabel)

        alert.accessoryView = box
        table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        describe()

        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown]) {
            [weak self] event in
            guard let self else { return event }
            return self.handle(event) ? nil : event
        }
        alert.runModal()
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
    }

    private func describe() {
        let row = max(0, table.selectedRow)
        guard row < rows.count else { return }
        let entry = rows[row]
        let verb = SourceControlPanel.actions[action]
        let state = entry.muted ? "muted" : "not muted"
        actionLabel.stringValue = "Space will \(verb) \(entry.label), \(state)"
        speaker.announceAnswer(actionLabel.stringValue)
    }

    private func handle(_ event: NSEvent) -> Bool {
        let mods = event.modifierFlags.intersection([.command, .option, .control, .shift])
        guard mods.isEmpty else { return false }
        switch event.keyCode {
        case UInt16(kVK_LeftArrow):
            action = (action + SourceControlPanel.actions.count - 1)
                % SourceControlPanel.actions.count
            describe()
            return true
        case UInt16(kVK_RightArrow):
            action = (action + 1) % SourceControlPanel.actions.count
            describe()
            return true
        case UInt16(kVK_Space), UInt16(kVK_Return):
            perform()
            return true
        default: break
        }
        // A digit jumps to that source. Its NUMBER is its position, not its
        // name, so renaming never renumbers anything.
        if let chars = event.charactersIgnoringModifiers, let digit = Int(chars),
           digit >= 0, digit < rows.count {
            table.selectRowIndexes(IndexSet(integer: digit), byExtendingSelection: false)
            describe()
            return true
        }
        return false
    }

    private func perform() {
        let row = max(0, table.selectedRow)
        guard row < rows.count else { return }
        let entry = rows[row]
        let isMic = entry.id == micDuckKey

        switch SourceControlPanel.actions[action] {
        case "mute":
            if isMic {
                speaker.announceAnswer("The microphone is turned off with Command M, "
                                       + "not muted here")
                return
            }
            if let source = group.source(id: entry.id) {
                source.config.muted.toggle()
                speaker.announceAnswer("\(entry.label) \(source.config.muted ? "muted" : "unmuted")")
            }
        case "solo":
            if group.soloed == entry.id {
                group.soloed = nil
                speaker.announceAnswer("\(entry.label) no longer soloed. Everything is back")
            } else {
                group.soloed = entry.id
                speaker.announceAnswer("\(entry.label) soloed. Everything else is silent.")
            }
        case "rename":
            if isMic {
                speaker.announceAnswer("The microphone is always called the microphone")
                return
            }
            guard let source = group.source(id: entry.id) else { return }
            let alert = NSAlert()
            alert.messageText = "Rename \(source.config.name)"
            alert.addButton(withTitle: "Rename")
            alert.addButton(withTitle: "Cancel")
            let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
            field.stringValue = source.config.name
            field.setAccessibilityLabel("Name")
            alert.accessoryView = field
            alert.window.initialFirstResponder = field
            if alert.runModal() == .alertFirstButtonReturn {
                let name = field.stringValue.trimmingCharacters(in: .whitespaces)
                if !name.isEmpty {
                    source.config.name = name
                    speaker.announceAnswer("Renamed to \(name)")
                } else {
                    speaker.announceAnswer("Left as \(source.config.name)")
                }
            } else {
                speaker.announceAnswer("Kept")
            }
        default:
            if isMic {
                speaker.announceAnswer("The microphone cannot be removed. "
                                       + "Command M turns it off.")
                return
            }
            if let source = group.source(id: entry.id) {
                source.stop()
                source.config.onAir = false
                speaker.announceAnswer("Removed \(entry.label)")
            }
        }
        table.reloadData()
        table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
    }
}

extension SourceControlPanel: NSTableViewDataSource, NSTableViewDelegate {
    func numberOfRows(in tableView: NSTableView) -> Int { rows.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard let tableColumn, row < rows.count else { return nil }
        let entry = rows[row]
        let text: String
        switch tableColumn.identifier.rawValue {
        case "n": text = "\(row)"
        case "name": text = entry.label
        case "muted": text = entry.muted ? "yes" : "no"
        case "solo": text = entry.solo ? "yes" : "no"
        default: text = entry.air ? "yes" : "no"
        }
        let field = NSTextField(labelWithString: text)
        field.setAccessibilityLabel(text)
        return field
    }

    func tableViewSelectionDidChange(_ notification: Notification) { describe() }
}
