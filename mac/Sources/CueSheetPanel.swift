// The window that shows what is coming up, and the one rule that holds it up.
//
// Command+Shift+C. Built from the ticked items in the running order, draining
// from the top as the show runs, and it never touches the running order itself.
//
// **The row you are standing on never moves.** That is the load bearing rule
// and `CueSheet.applyChanges` is where it lives; this file is the window that
// obeys it. Removing a row above or below the cursor is silent. Removing the
// row UNDER it moves the selection, which posts a selection-changed
// notification, which is exactly what VoiceOver reads from: it stops mid
// sentence and reads out a track the presenter never chose, on air, at the
// moment a song changes. So that one row is held until you move off it.
//
// Your pads and every other key still work while it is open, which is why this
// is an ordinary window and not a modal panel: the show is running.

import AppKit

/// `Track` answers the cue sheet's questions. Here rather than in
/// `CueSheet.swift` so that file stays compilable with nothing but the
/// constants beside it, which is what lets `cross_check.py` prove its list
/// rules without dragging the whole audio model in.
extension Track: CueTrack {
    var cueTitle: String { displayName }
    var cueArtist: String { artist ?? "" }
    var cueKind: String { isDrop ? "Drop" : "Song" }
    var cueSeconds: Double { duration ?? 0.0 }
    var cueTicked: Bool { enabled }
    var cueMissing: Bool { isMissing }
}

final class CueSheetWindow: NSObject, NSWindowDelegate,
                            NSTableViewDataSource, NSTableViewDelegate {

    private weak var main: MainWindow?
    private var window: NSWindow!
    private var table: NSTableView!
    private var clock: NSTextField!
    private var summary: NSTextField!
    private var timer: Timer?

    /// What the list is displaying right now, which is not always what it
    /// WOULD display. See `CueSheet.applyChanges`.
    private var rows: [CueRow] = []

    var onClose: (() -> Void)?

    init(main: MainWindow) {
        self.main = main
        super.init()
    }

    // ----------------------------------------------------------- the window ---

    func show() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 700, height: 420),
            styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "What is coming up"
        window.delegate = self
        window.isReleasedWhenClosed = false

        let content = NSView(frame: window.contentLayoutRect)
        content.autoresizingMask = [.width, .height]

        clock = NSTextField(labelWithString: "")
        clock.frame = NSRect(x: 12, y: 384, width: 676, height: 20)
        clock.autoresizingMask = [.width, .minYMargin]
        // A static text is never the focus object, so rewriting it twice a
        // second is silent by construction. That is the whole reason the one
        // moving number lives out here and not in a cell.
        clock.setAccessibilityLabel("What is on air")
        content.addSubview(clock)

        let scroll = NSScrollView(frame: NSRect(x: 12, y: 40, width: 676, height: 338))
        scroll.autoresizingMask = [.width, .height]
        table = NSTableView(frame: scroll.bounds)
        // The title is column 0 because that is what first letter navigation
        // searches, and no running order number goes in front of it for the
        // same reason. The same rule the running order itself follows.
        for (id, title, width) in [("title", "Title", 250), ("artist", "Artist", 170),
                                   ("kind", "Kind", 70), ("length", "Length", 100),
                                   ("status", "Status", 80)] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id))
            column.title = title
            column.width = CGFloat(width)
            table.addTableColumn(column)
        }
        table.dataSource = self
        table.delegate = self
        table.allowsMultipleSelection = false
        table.setAccessibilityLabel("Coming up")
        table.target = self
        table.doubleAction = #selector(activateRow)
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        content.addSubview(scroll)

        summary = NSTextField(labelWithString: "")
        summary.frame = NSRect(x: 12, y: 12, width: 676, height: 20)
        summary.autoresizingMask = [.width, .maxYMargin]
        summary.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        summary.textColor = .secondaryLabelColor
        summary.setAccessibilityLabel("Summary")
        content.addSubview(summary)

        window.contentView = content
        rebuild(force: true)
        window.center()
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(table)
        if !rows.isEmpty { table.selectRowIndexes([0], byExtendingSelection: false) }

        timer = Timer.scheduledTimer(withTimeInterval: Double(C.cueRefreshMS) / 1000.0,
                                     repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    func raise() {
        window?.makeKeyAndOrderFront(nil)
        if let table { window?.makeFirstResponder(table) }
    }

    func windowWillClose(_ notification: Notification) {
        timer?.invalidate()
        timer = nil
        onClose?()
    }

    // -------------------------------------------------------------- content ---

    func refresh() {
        clock.stringValue = main?.cueClockLine() ?? ""
        rebuild(force: false)
    }

    private func rebuild(force: Bool) {
        guard let main else { return }
        let tracks = main.board.playlist.tracks
        let playing = main.player.isPlaying ? main.player.index : nil
        let wanted = CueSheet.build(tracks: tracks, playingIndex: playing,
                                    playedFor: main.player.playedFor)
        // The title of the row the cursor is on, or nil when this window is not
        // the one with focus. Nil means every change may land at once.
        var focused: String?
        if window.isKeyWindow, window.firstResponder === table,
           table.selectedRow >= 0, table.selectedRow < rows.count {
            focused = rows[table.selectedRow].title
        }
        let next = force ? wanted
                         : CueSheet.applyChanges(shown: rows, wanted: wanted,
                                                 focusedTitle: focused)
        summary.stringValue = CueSheet.summary(tracks: tracks, rows: next)
        guard next != rows else { return }
        // Held so the selection lands back on the same TRACK rather than on
        // the same row number, which is a different track the moment one
        // leaves above it.
        let standing = focused
        rows = next
        table.reloadData()
        if let standing, let at = rows.firstIndex(where: { $0.title == standing }) {
            table.selectRowIndexes([at], byExtendingSelection: false)
        }
    }

    /// "Next X. Then Y. Then Z." One sentence, for the key that asks.
    private func sayNext() {
        main?.speaker.announceAnswer(CueSheet.nextFew(rows))
    }

    /// Return crosses into the track under the cursor.
    @objc private func activateRow() {
        guard let main, table.selectedRow >= 0, table.selectedRow < rows.count,
              let at = rows[table.selectedRow].index else { return }
        main.playlistPlayFromHere(at)
    }

    // --------------------------------------------------------------- table ---

    func numberOfRows(in tableView: NSTableView) -> Int { rows.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard row < rows.count, let column = tableColumn else { return nil }
        let cells = rows[row].cells
        let order = ["title", "artist", "kind", "length", "status"]
        guard let at = order.firstIndex(of: column.identifier.rawValue) else { return nil }
        let id = NSUserInterfaceItemIdentifier("cue.\(column.identifier.rawValue)")
        let field: NSTextField
        if let reused = tableView.makeView(withIdentifier: id, owner: self) as? NSTextField {
            field = reused
        } else {
            field = NSTextField(labelWithString: "")
            field.identifier = id
            field.lineBreakMode = .byTruncatingTail
        }
        field.stringValue = cells[at]
        return field
    }

    /// The keys that work inside this window.
    ///
    /// `N` says the next three in one sentence, because a presenter plans a
    /// link out of what is coming and arrowing three rows means three
    /// announcements and losing your place. Return crosses into a track.
    /// Everything else, the pads included, falls through to the main window's
    /// own monitor, which is the point of this being a window rather than a
    /// panel: the show is running.
    func handle(_ event: NSEvent) -> Bool {
        guard window?.isKeyWindow == true else { return false }
        let characters = event.charactersIgnoringModifiers?.lowercased() ?? ""
        if event.modifierFlags.intersection([.command, .option, .control]).isEmpty {
            if characters == "n" { sayNext(); return true }
            if characters == "\r" { activateRow(); return true }
        }
        return false
    }
}
