// The running order, its tick boxes and its keys.
//
// On Windows this had to be a wx.ListCtrl rather than a wxCheckListBox,
// because a check list box there is an owner drawn list box with a tick
// painted on it and MSAA never knows the tick is there. NSTableView has no
// such problem: the tick is a real NSButton and VoiceOver says "checked" or
// "unchecked" for free.
//
// Three rules carried over, and one improved:
//
//   The title is what first letter navigation searches. On Windows that forced
//   the title to be column 0 and forbade a running order number in front of
//   it. On macOS typeSelectStringFor says so explicitly, so the tick can sit
//   in the first column where it reads naturally and the rule still holds.
//
//   No running order number goes in front of the title.
//
//   ONE PRESS MUST NOT BOTH TICK AND GO TO AIR. On Windows, Space raised
//   ITEM_ACTIVATED as well as toggling, which needed a flag to tell apart.
//   Here Space is handled and consumed, and Return is separate, so the
//   collision does not exist.
//
//   Rows never say "playing". What is on air is spoken as it changes and
//   answered on demand by Command L. Rewriting the row a screen reader is
//   standing on, at the moment a song changes, is the thing this app does not
//   do.

import AppKit

protocol PlaylistViewDelegate: AnyObject {
    func playlistPlayFromHere(_ row: Int)
    func playlistSegueTo(_ row: Int)
    func playlistToggleTick(_ row: Int)
    func playlistRemove(_ row: Int)
    func playlistMove(_ row: Int, by offset: Int)
    func playlistMoveToEdge(_ row: Int, top: Bool)
    func playlistTickAll(_ ticked: Bool)
    func playlistCrossfadeChanged(_ seconds: Double)
    func playlistAddFiles()
    func playlistInsertDrop()
    func playlistStop()
    func playlistRowMenu(_ row: Int, at point: NSPoint, in view: NSView)
    /// Files, folders or a playlist file dropped on the list. nil means the end.
    func playlistDropped(_ paths: [String], at row: Int?)
}

final class PlaylistTable: NSTableView {

    weak var keys: PlaylistViewDelegate?
    var isEmptyState = false

    override func keyDown(with event: NSEvent) {
        let row = selectedRow
        let mods = event.modifierFlags.intersection([.command, .option, .control, .shift])

        // Nothing below makes sense with only the empty placeholder showing.
        if isEmptyState { super.keyDown(with: event); return }

        switch event.keyCode {
        case 49:                                   // Space
            guard row >= 0 else { break }
            keys?.playlistToggleTick(row)
            return
        case 36, 76:                               // Return, Enter
            guard row >= 0 else { break }
            if mods.contains(.shift) { keys?.playlistSegueTo(row) }
            else { keys?.playlistPlayFromHere(row) }
            return
        case 51, 117:                              // Backspace, Delete
            guard row >= 0 else { break }
            keys?.playlistRemove(row)
            return
        case 126 where mods.contains(.option):     // Option Up
            guard row > 0 else { return }
            keys?.playlistMove(row, by: -1)
            return
        case 125 where mods.contains(.option):     // Option Down
            guard row >= 0, row < numberOfRows - 1 else { return }
            keys?.playlistMove(row, by: +1)
            return
        case 115 where mods.contains(.option):     // Option Home
            guard row > 0 else { return }
            keys?.playlistMoveToEdge(row, top: true)
            return
        case 119 where mods.contains(.option):     // Option End
            guard row >= 0, row < numberOfRows - 1 else { return }
            keys?.playlistMoveToEdge(row, top: false)
            return
        default:
            break
        }

        // Shift A and Shift U tick and untick everything. Gated on Shift alone
        // so plain letters stay free for first letter navigation.
        if mods == .shift, let c = event.charactersIgnoringModifiers?.lowercased() {
            if c == "a" { keys?.playlistTickAll(true); return }
            if c == "u" { keys?.playlistTickAll(false); return }
        }
        super.keyDown(with: event)
    }

    override func menu(for event: NSEvent) -> NSMenu? {
        let point = convert(event.locationInWindow, from: nil)
        var row = self.row(at: point)
        // VoiceOver's own menu gesture arrives with no useful mouse position,
        // so fall back to the selection and to a position on the control.
        if row < 0 { row = selectedRow }
        guard row >= 0, !isEmptyState else { return nil }
        let where_ = self.row(at: point) >= 0
            ? point
            : NSPoint(x: bounds.width / 3, y: rect(ofRow: row).midY)
        keys?.playlistRowMenu(row, at: where_, in: self)
        return nil
    }
}

final class PlaylistView: NSView, NSTableViewDataSource, NSTableViewDelegate {

    weak var delegate: PlaylistViewDelegate?
    private let playlist: Playlist
    private var table: PlaylistTable!
    private var crossfadeField: NSTextField!
    private var summaryLabel: NSTextField!
    private var scroll: NSScrollView!

    /// Which item is on air, so the row can be found again with Command Shift L.
    /// It is deliberately NOT written into any row's text.
    var onAirRow: Int?

    private static let emptyRow = "Empty. Paste songs with Command V, or use Add files"

    private enum Column: String, CaseIterable {
        case tick, title, artist, kind, length, starts, crossfade
        var heading: String {
            switch self {
            case .tick: return "Play"
            case .title: return "Title"
            case .artist: return "Artist"
            case .kind: return "Kind"
            case .length: return "Length"
            case .starts: return "Starts"
            case .crossfade: return "Crossfade"
            }
        }
        var width: CGFloat {
            switch self {
            case .tick: return 34
            case .title: return 260
            case .artist: return 170
            case .kind: return 70
            case .length: return 90
            case .starts: return 90
            case .crossfade: return 90
            }
        }
    }

    init(playlist: Playlist) {
        self.playlist = playlist
        super.init(frame: .zero)
        build()
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    private func build() {
        let intro = NSTextField(wrappingLabelWithString: """
            Paste files here with Command V, or drag them in, as many at once as you like. \
            Each song hands over to the next before it ends.
            Space ticks or unticks a track: unticked stays in the list and is skipped. \
            Return plays from the one you are on.
            Delete removes it. Option Up and Option Down move it. Command Shift L goes to \
            whatever is on air.
            """)
        intro.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        intro.textColor = .secondaryLabelColor
        intro.translatesAutoresizingMaskIntoConstraints = false
        addSubview(intro)

        let listLabel = NSTextField(labelWithString: "Running order")
        listLabel.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        listLabel.textColor = .secondaryLabelColor
        listLabel.translatesAutoresizingMaskIntoConstraints = false
        addSubview(listLabel)

        table = PlaylistTable()
        table.dataSource = self
        table.delegate = self
        table.keys = delegate
        // Dragging files onto the list adds them, and dragging an M3U adds
        // its contents rather than replacing, because that is what dragging
        // things onto a list means.
        table.registerForDraggedTypes([.fileURL])
        table.setDraggingSourceOperationMask([], forLocal: true)
        table.usesAlternatingRowBackgroundColors = true
        table.allowsMultipleSelection = false
        table.rowHeight = 22
        table.setAccessibilityLabel("Running order")
        for c in Column.allCases {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(c.rawValue))
            column.title = c.heading
            column.width = c.width
            column.minWidth = 30
            table.addTableColumn(column)
        }

        scroll = NSScrollView()
        scroll.translatesAutoresizingMaskIntoConstraints = false
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        addSubview(scroll)

        let crossLabel = NSTextField(labelWithString: "Crossfade, seconds")
        crossLabel.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        crossLabel.textColor = .secondaryLabelColor
        crossLabel.translatesAutoresizingMaskIntoConstraints = false
        addSubview(crossLabel)

        crossfadeField = NSTextField(string: String(format: "%.1f", playlist.crossfade))
        crossfadeField.translatesAutoresizingMaskIntoConstraints = false
        crossfadeField.setAccessibilityLabel("Crossfade between tracks, seconds")
        crossfadeField.target = self
        crossfadeField.action = #selector(crossfadeCommitted)
        addSubview(crossfadeField)

        let stepper = NSStepper()
        stepper.translatesAutoresizingMaskIntoConstraints = false
        stepper.minValue = 0
        stepper.maxValue = C.maxCrossfade
        stepper.increment = 0.5
        stepper.doubleValue = playlist.crossfade
        stepper.valueWraps = false
        stepper.target = self
        stepper.action = #selector(crossfadeStepped(_:))
        stepper.setAccessibilityLabel("Crossfade between tracks, seconds")
        addSubview(stepper)

        let explain = NSTextField(wrappingLabelWithString: """
            How long one song overlaps the next. The next song starts this many seconds \
            before the one playing ends, so every start time in the list moves when you \
            change it. Zero means each song plays right out first.
            """)
        explain.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        explain.textColor = .secondaryLabelColor
        explain.translatesAutoresizingMaskIntoConstraints = false
        addSubview(explain)

        summaryLabel = NSTextField(labelWithString: playlist.summary())
        summaryLabel.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        summaryLabel.translatesAutoresizingMaskIntoConstraints = false
        summaryLabel.setAccessibilityLabel("Running order summary")
        addSubview(summaryLabel)

        let buttons = NSStackView(views: [
            button("Play from here", #selector(playPressed)),
            button("Stop playlist", #selector(stopPressed)),
            button("Add files...", #selector(addPressed)),
            button("Insert a drop...", #selector(dropPressed)),
            button("Remove", #selector(removePressed)),
        ])
        buttons.orientation = .horizontal
        buttons.spacing = 8
        buttons.translatesAutoresizingMaskIntoConstraints = false
        addSubview(buttons)

        NSLayoutConstraint.activate([
            intro.topAnchor.constraint(equalTo: topAnchor, constant: 10),
            intro.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            intro.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),

            listLabel.topAnchor.constraint(equalTo: intro.bottomAnchor, constant: 8),
            listLabel.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),

            scroll.topAnchor.constraint(equalTo: listLabel.bottomAnchor, constant: 2),
            scroll.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            scroll.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),

            crossLabel.topAnchor.constraint(equalTo: scroll.bottomAnchor, constant: 8),
            crossLabel.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),

            crossfadeField.topAnchor.constraint(equalTo: crossLabel.bottomAnchor, constant: 2),
            crossfadeField.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            crossfadeField.widthAnchor.constraint(equalToConstant: 70),

            stepper.centerYAnchor.constraint(equalTo: crossfadeField.centerYAnchor),
            stepper.leadingAnchor.constraint(equalTo: crossfadeField.trailingAnchor, constant: 4),

            explain.topAnchor.constraint(equalTo: crossfadeField.bottomAnchor, constant: 6),
            explain.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            explain.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),

            summaryLabel.topAnchor.constraint(equalTo: explain.bottomAnchor, constant: 6),
            summaryLabel.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            summaryLabel.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),

            buttons.topAnchor.constraint(equalTo: summaryLabel.bottomAnchor, constant: 8),
            buttons.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            buttons.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -10),
        ])
    }

    private func button(_ title: String, _ action: Selector) -> NSButton {
        let b = NSButton(title: title, target: self, action: action)
        b.bezelStyle = .rounded
        b.setAccessibilityLabel(title)
        return b
    }

    func attachDelegate(_ d: PlaylistViewDelegate) {
        delegate = d
        table.keys = d
    }

    var focusTarget: NSView {
        if table.selectedRow < 0 && !playlist.isEmpty { select(0) }
        return table
    }
    var selectedRow: Int { table.selectedRow }

    /// The Playlist menu's crossfade item lands here rather than in a dialog:
    /// one place for the value, and a menu item that says where it is.
    func focusCrossfade() {
        window?.makeFirstResponder(crossfadeField)
        crossfadeField.currentEditor()?.selectAll(nil)
    }

    func select(_ row: Int) {
        guard row >= 0, row < playlist.count else { return }
        table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
        table.scrollRowToVisible(row)
    }

    // ------------------------------------------------------------ refreshing ---

    /// Rebuild only when the number of rows has changed.
    ///
    /// Reloading the whole table moves focus and selection, and a screen reader
    /// reads the row again every time. Where the count is the same, the cells
    /// are written one at a time and only where the text differs.
    func refresh(rowsChanged: Bool = true) {
        let wasSelected = table.selectedRow
        table.isEmptyState = playlist.isEmpty
        if rowsChanged || table.numberOfRows != max(1, playlist.count) {
            table.reloadData()
            if wasSelected >= 0, wasSelected < table.numberOfRows {
                table.selectRowIndexes(IndexSet(integer: wasSelected),
                                       byExtendingSelection: false)
            }
        } else {
            for row in 0..<table.numberOfRows {
                for column in 0..<table.numberOfColumns {
                    guard let cell = table.view(atColumn: column, row: row,
                                                makeIfNecessary: false) else { continue }
                    apply(cell: cell, column: table.tableColumns[column], row: row)
                }
            }
        }
        summaryLabel.stringValue = playlist.summary()
        crossfadeField.stringValue = String(format: "%.1f", playlist.crossfade)
    }

    // ----------------------------------------------------------- table source ---

    func numberOfRows(in tableView: NSTableView) -> Int {
        // An empty list read by a screen reader gives nothing to read, which
        // sounds exactly like a list that failed to load. So there is always
        // one row.
        max(1, playlist.count)
    }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard let tableColumn else { return nil }
        let id = tableColumn.identifier
        if playlist.isEmpty {
            guard id.rawValue == Column.title.rawValue else { return nil }
            let f = NSTextField(labelWithString: Self.emptyRow)
            f.setAccessibilityLabel(Self.emptyRow)
            return f
        }
        if id.rawValue == Column.tick.rawValue {
            let box = NSButton(checkboxWithTitle: "", target: self, action: #selector(tickClicked(_:)))
            box.tag = row
            box.state = playlist.tracks[row].enabled ? .on : .off
            box.setAccessibilityLabel("Ticked to play")
            return box
        }
        let f = NSTextField(labelWithString: "")
        apply(cell: f, column: tableColumn, row: row)
        return f
    }

    private func apply(cell: NSView, column: NSTableColumn, row: Int) {
        guard row < playlist.count else { return }
        let track = playlist.tracks[row]
        if let box = cell as? NSButton {
            let wanted: NSControl.StateValue = track.enabled ? .on : .off
            if box.state != wanted { box.state = wanted }
            box.tag = row
            return
        }
        guard let field = cell as? NSTextField else { return }
        let text: String
        switch Column(rawValue: column.identifier.rawValue) ?? .title {
        case .title:
            // No running order number in front of it: that is what first letter
            // navigation searches.
            text = track.isMissing ? track.displayName + "  (missing)" : track.displayName
        case .artist: text = track.artist ?? ""
        case .kind: text = track.isDrop ? "Drop" : "Song"
        case .length: text = formatDuration(track.duration)
        case .starts:
            let points = cuePointCache ?? playlist.cuePoints()
            if row < points.count, let at = points[row] {
                text = at > 0 ? formatDuration(at) : "at the start"
            } else {
                text = "skipped"
            }
        case .crossfade:
            let f = playlist.crossfadeFor(row)
            text = f > 0 ? formatDuration(f) : (row == playlist.count - 1 ? "" : "none")
        case .tick: text = ""
        }
        if field.stringValue != text { field.stringValue = text }
        // An empty cell says nothing. Falling back to the column heading
        // makes "Length" sound like the length.
        field.setAccessibilityLabel(text)
    }

    private var cuePointCache: [Double?]?

    func tableView(_ tableView: NSTableView, validateDrop info: NSDraggingInfo,
                   proposedRow row: Int, proposedDropOperation: NSTableView.DropOperation)
        -> NSDragOperation {
        guard info.draggingPasteboard.canReadObject(forClasses: [NSURL.self],
                                                    options: [.urlReadingFileURLsOnly: true])
        else { return [] }
        tableView.setDropRow(min(row, playlist.count), dropOperation: .above)
        return .copy
    }

    func tableView(_ tableView: NSTableView, acceptDrop info: NSDraggingInfo, row: Int,
                   dropOperation: NSTableView.DropOperation) -> Bool {
        guard let urls = info.draggingPasteboard.readObjects(
            forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL],
              !urls.isEmpty else { return false }
        let at: Int? = (playlist.isEmpty || row >= playlist.count) ? nil : max(0, row)
        delegate?.playlistDropped(urls.map(\.path), at: at)
        return true
    }

    func tableView(_ tableView: NSTableView, typeSelectStringFor tableColumn: NSTableColumn?,
                   row: Int) -> String? {
        // First letter navigation searches the TITLE whichever column it is in.
        guard row < playlist.count else { return nil }
        return playlist.tracks[row].displayName
    }

    func tableViewSelectionDidChange(_ notification: Notification) {
        cuePointCache = nil
    }

    // --------------------------------------------------------------- actions ---

    @objc private func tickClicked(_ sender: NSButton) {
        delegate?.playlistToggleTick(sender.tag)
    }
    @objc private func crossfadeCommitted() {
        delegate?.playlistCrossfadeChanged(crossfadeField.doubleValue)
    }
    @objc private func crossfadeStepped(_ sender: NSStepper) {
        crossfadeField.stringValue = String(format: "%.1f", sender.doubleValue)
        delegate?.playlistCrossfadeChanged(sender.doubleValue)
    }
    @objc private func playPressed() {
        // With nothing chosen, play from the top rather than doing nothing and
        // saying nothing, which reads as a broken button.
        let row = table.selectedRow >= 0 ? table.selectedRow : (playlist.firstPlayable() ?? 0)
        select(row)
        delegate?.playlistPlayFromHere(row)
    }
    @objc private func stopPressed() { delegate?.playlistStop() }
    @objc private func addPressed() { delegate?.playlistAddFiles() }
    @objc private func dropPressed() { delegate?.playlistInsertDrop() }
    @objc private func removePressed() {
        delegate?.playlistRemove(table.selectedRow)
    }
}
