// The two playlist windows that are more than a question: the drops library,
// and the crossfade for one track.

import AppKit
import UniformTypeIdentifiers

/// The list in the library, where Delete takes one out.
final class LibraryTable: NSTableView {
    var onDelete: (() -> Void)?
    override func keyDown(with event: NSEvent) {
        if event.keyCode == 51 || event.keyCode == 117, selectedRow >= 0 {
            onDelete?()
            return
        }
        super.keyDown(with: event)
    }
}

/// The drops you use over and over, in one place.
///
/// Nothing here plays anything: it is a list you build once so that Option D
/// has something to reach for. The list is the whole control, the same way the
/// running order is.
final class DropsLibraryPanel: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private let library: DropLibrary
    private let speaker: Speaker
    private(set) var lastDir: String?
    private(set) var changed = false

    private var table: LibraryTable!
    private var summary: NSTextField!
    private var removeButton: NSButton!

    init(library: DropLibrary, speaker: Speaker, lastDir: String?) {
        self.library = library
        self.speaker = speaker
        self.lastDir = lastDir
    }

    func run(over parent: NSWindow?) -> Bool {
        let alert = NSAlert()
        alert.messageText = "Drops library"
        alert.informativeText = "The idents and stingers you reach for over and over. Once they are "
                              + "in here, Option D puts one in the running order at random, wherever "
                              + "you are, and never the same one twice running."
        alert.addButton(withTitle: "Close")

        let width: CGFloat = 560
        let box = NSStackView()
        box.orientation = .vertical
        box.alignment = .leading
        box.spacing = 6
        box.frame = NSRect(x: 0, y: 0, width: width, height: 330)

        let label = NSTextField(labelWithString: "Drops")
        label.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        label.textColor = .secondaryLabelColor
        box.addArrangedSubview(label)

        let scroll = NSScrollView()
        table = LibraryTable()
        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("drop"))
        column.width = width - 20
        table.addTableColumn(column)
        table.headerView = nil
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel("Drops")
        table.onDelete = { [weak self] in self?.removePressed() }
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        scroll.heightAnchor.constraint(equalToConstant: 220).isActive = true
        scroll.widthAnchor.constraint(equalToConstant: width).isActive = true
        box.addArrangedSubview(scroll)

        summary = NSTextField(labelWithString: "")
        summary.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        summary.setAccessibilityLabel("Library summary")
        box.addArrangedSubview(summary)

        let add = NSButton(title: "Add drops...", target: self, action: #selector(addPressed))
        add.bezelStyle = .rounded
        add.toolTip = "Choose files, or a whole folder of them"
        removeButton = NSButton(title: "Remove", target: self, action: #selector(removePressed))
        removeButton.bezelStyle = .rounded
        removeButton.toolTip = "Take this one out of the library"
        let row = NSStackView(views: [add, removeButton])
        row.orientation = .horizontal
        row.spacing = 8
        box.addArrangedSubview(row)

        alert.accessoryView = box
        alert.window.initialFirstResponder = table
        refresh(keep: 0)
        alert.runModal()
        return changed
    }

    private func refresh(keep: Int?) {
        table.reloadData()
        let count = library.count
        if count > 0 {
            var row = keep ?? table.selectedRow
            if row < 0 || row >= count { row = count - 1 }
            table.selectRowIndexes(IndexSet(integer: max(0, row)), byExtendingSelection: false)
            table.scrollRowToVisible(max(0, row))
        }
        let missing = library.missing.count
        if count == 0 {
            summary.stringValue = "Nothing in the library yet. Add some, and Option D will start reaching for them."
        } else {
            var text = "\(count) drop\(count == 1 ? "" : "s")"
            if missing > 0 { text += ".  \(missing) file\(missing == 1 ? "" : "s") missing" }
            summary.stringValue = text
        }
        summary.setAccessibilityLabel(summary.stringValue)
        removeButton.isEnabled = count > 0
    }

    @objc private func addPressed() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.message = "Add drops to the library. Choose files, or a whole folder of them."
        panel.allowedContentTypes = AudioFile.supportedExtensions.compactMap {
            UTType(filenameExtension: $0)
        } + [UTType.folder]
        if let lastDir { panel.directoryURL = URL(fileURLWithPath: lastDir) }
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return }
        lastDir = panel.urls[0].hasDirectoryPath
            ? panel.urls[0].path : panel.urls[0].deletingLastPathComponent().path
        let before = library.count
        let added = library.add(panel.urls.map(\.path))
        if added.isEmpty {
            refresh(keep: nil)
            speaker.announce("Those are already in the library")
            return
        }
        changed = true
        refresh(keep: before)
        speaker.announce("\(added.count) added")
    }

    @objc private func removePressed() {
        let index = table.selectedRow
        guard index >= 0, let gone = library.remove(at: index) else { return }
        changed = true
        refresh(keep: min(index, library.count - 1))
        speaker.announce("Removed " + ((gone as NSString).lastPathComponent as NSString).deletingPathExtension)
    }

    func numberOfRows(in tableView: NSTableView) -> Int { library.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard row < library.count else { return nil }
        let text = library.label(row)
        let f = NSTextField(labelWithString: text)
        f.setAccessibilityLabel(text)
        return f
    }
}

// -------------------------------------------------- one track's crossfade ---

enum TrackCrossfadeChoice {
    case playlistDefault
    case seconds(Double)
}

/// How long THIS track overlaps the next one.
///
/// Most tracks want the playlist's own crossfade, which is why the default is a
/// tick box rather than a number: "same as the rest" is a different answer from
/// "three seconds", and a board that cannot tell them apart would freeze every
/// track at whatever the playlist happened to be set to on the day.
final class TrackCrossfadePanel: NSObject {

    private let track: Track
    private let defaultSeconds: Double
    private var useDefault: NSButton!
    private var seconds: NSTextField!
    private var stepper: NSStepper!

    init(track: Track, defaultSeconds: Double) {
        self.track = track
        self.defaultSeconds = defaultSeconds
    }

    func run(over parent: NSWindow?) -> TrackCrossfadeChoice? {
        let alert = NSAlert()
        alert.messageText = "Crossfade for one track"
        alert.informativeText = "How long should \(track.displayName) overlap the track after it?"
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")

        let box = NSStackView()
        box.orientation = .vertical
        box.alignment = .leading
        box.spacing = 8
        box.frame = NSRect(x: 0, y: 0, width: 460, height: 120)

        useDefault = NSButton(checkboxWithTitle:
            "Use the playlist's crossfade (\(String(format: "%g", defaultSeconds)) seconds)",
            target: self, action: #selector(defaultToggled))
        useDefault.state = track.crossfade == nil ? .on : .off
        box.addArrangedSubview(useDefault)

        let start = track.crossfade ?? track.crossfadeSeconds(default: defaultSeconds)
        seconds = NSTextField(string: String(format: "%.1f", start))
        seconds.setAccessibilityLabel("Crossfade for this track, seconds")
        seconds.toolTip = "Zero means it plays right out and the next one starts after it, "
                        + "which is what a drop does unless you say otherwise."
        seconds.widthAnchor.constraint(equalToConstant: 70).isActive = true
        stepper = NSStepper()
        stepper.minValue = 0
        stepper.maxValue = C.maxCrossfade
        stepper.increment = 0.5
        stepper.doubleValue = start
        stepper.target = self
        stepper.action = #selector(stepped)
        stepper.setAccessibilityLabel("Crossfade for this track, seconds")
        let label = NSTextField(labelWithString: "Seconds for this one")
        label.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        label.textColor = .secondaryLabelColor
        let row = NSStackView(views: [seconds, stepper])
        row.orientation = .horizontal
        row.spacing = 4
        box.addArrangedSubview(label)
        box.addArrangedSubview(row)
        defaultToggled()

        alert.accessoryView = box
        alert.window.initialFirstResponder = useDefault
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        if useDefault.state == .on { return .playlistDefault }
        let value = min(C.maxCrossfade, max(0, seconds.doubleValue))
        return .seconds((value * 100).rounded() / 100)
    }

    @objc private func defaultToggled() {
        let own = useDefault.state == .off
        seconds.isEnabled = own
        stepper.isEnabled = own
    }

    @objc private func stepped() {
        seconds.stringValue = String(format: "%.1f", stepper.doubleValue)
    }
}
