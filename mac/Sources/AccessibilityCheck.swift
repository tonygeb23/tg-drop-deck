// Every window, read the way VoiceOver reads it, with nobody at the keyboard.
//
// `--check-accessibility`. The shell the checks run from cannot be given the
// Accessibility permission, so System Events cannot read this app from the
// outside. This reads it from the inside instead: the real windows and panels
// are built exactly as the app builds them, never shown, and every element is
// walked through the NSAccessibility protocol (isAccessibilityElement,
// accessibilityRole, accessibilityLabel, accessibilityTitle,
// accessibilityTitleUIElement, accessibilityValue, accessibilityChildren),
// which is what VoiceOver itself is handed.
//
// What it refuses:
//
//   - a control you can reach and work (a button, a check box, a popup, a
//     text box, a slider, a stepper, a table, a control inside a table cell)
//     that has no spoken name. VoiceOver says "button" and nothing else, which
//     is a control that does not exist for the person this app is for;
//   - the running order saying anything but the truth about a tick (Siena,
//     9 September 2026);
//   - a menu item with no title, or the go live and microphone keys not being
//     where the manual says they are.
//
// And it warns about two controls of the same kind with the same name on the
// same page, which VoiceOver cannot tell apart either.
//
// Nothing real is touched. The board is built in memory, the data folder is a
// scratch folder, the keychain is not read, nothing is announced, and no
// microphone, camera, screen capture or network is opened: panels that would
// wait for a person are handed to the check by `ModalAudit` instead of run.

import AppKit

/// Where a modal panel goes instead of on screen, while the accessibility
/// check is running. Nil in the app, always, so every call below is exactly
/// `runModal()`.
enum ModalAudit {

    static var capture: ((NSAlert) -> Void)?

    @discardableResult
    static func run(_ alert: NSAlert) -> NSApplication.ModalResponse {
        guard let capture else {
            let answer = alert.runModal()
            // What the box's command says next waits for VoiceOver to finish
            // reading where focus landed. See `Speaker.interfaceClosed`.
            Speaker.interfaceClosed()
            return answer
        }
        capture(alert)
        return escapeAnswer(alert)
    }

    /// The answer Escape would give: the button that carries Escape, or the
    /// one called Cancel, or else the second, which is what PanelKeys gives.
    /// A panel read by the check is always left the way you leave it without
    /// changing anything.
    static func escapeAnswer(_ alert: NSAlert) -> NSApplication.ModalResponse {
        let buttons = alert.buttons
        let index = buttons.firstIndex(where: { $0.keyEquivalent == "\u{1b}" })
            ?? buttons.firstIndex(where: { $0.title == "Cancel" })
            ?? (buttons.count > 1 ? 1 : 0)
        return NSApplication.ModalResponse(
            rawValue: NSApplication.ModalResponse.alertFirstButtonReturn.rawValue + index)
    }
}

// ------------------------------------------------------------------ the walk ---

final class AccessibilityAudit {

    enum Level: String { case fail = "FAIL", warn = "WARN" }

    private(set) var findings: [(Level, String)] = []
    private(set) var checked = 0
    private(set) var perWindow: [(String, Int)] = []

    var failed: Int { findings.filter { $0.0 == .fail }.count }
    var warned: Int { findings.filter { $0.0 == .warn }.count }

    func fail(_ text: String) { findings.append((.fail, text)) }
    func warn(_ text: String) { findings.append((.warn, text)) }

    /// The roles VoiceOver lands on as something to work. A text area counts:
    /// every read only box in this app is focusable on purpose, and one with
    /// no name is read as "text" and nothing else.
    static let controlRoles: Set<NSAccessibility.Role> = [
        .button, .checkBox, .radioButton, .popUpButton, .menuButton, .comboBox,
        .textField, .textArea, .slider, .incrementor, .table, .outline,
        .disclosureTriangle, .colorWell, .link,
    ]

    /// Roles whose title is their name. A popup's title, where it has one, is
    /// the chosen item, which is its value, and a text box has no title.
    static let titledRoles: Set<NSAccessibility.Role> = [
        .button, .checkBox, .radioButton, .menuButton, .disclosureTriangle, .link,
    ]

    struct Control {
        let role: NSAccessibility.Role
        let name: String
        let scope: String
        let inTable: Bool
    }

    // ---------------------------------------------------- reading one element --
    //
    // **Asked the way the accessibility server asks, not through the public
    // getters.** A control is not itself the element VoiceOver is handed: its
    // CELL is, and the label set on the control lives on the control. The
    // public `cell.accessibilityLabel()` answers "" for every popup, slider
    // and text box in the app, while VoiceOver reads the label perfectly well,
    // because the server fetches each attribute through AppKit's
    // `_accessibilityValueForAttribute:clientError:`, which merges what was
    // set on the control into what its cell says. Measured 29 September 2026:
    // a popup labelled "Main output" answers "" publicly and "Main output"
    // through that accessor, and so does the override on a running order
    // tick. So the check asks that accessor, the one question VoiceOver
    // itself asks, and falls back to the public getters only where it is not
    // there.

    private static let serverSelector = NSSelectorFromString(
        "_accessibilityValueForAttribute:clientError:")
    private typealias ServerAccessor = @convention(c)
        (AnyObject, Selector, NSString, UnsafeMutablePointer<Int32>?) -> Unmanaged<AnyObject>?

    /// One attribute, as the accessibility server would be answered. Nil
    /// when the element has none, or does not answer that way at all.
    static func server(_ e: Any, _ attribute: NSAccessibility.Attribute) -> Any?? {
        let object = e as AnyObject
        guard let o = object as? NSObject, o.responds(to: serverSelector),
              let imp = o.method(for: serverSelector) else { return nil }
        let call = unsafeBitCast(imp, to: ServerAccessor.self)
        var error: Int32 = 0
        let got = call(o, serverSelector, attribute.rawValue as NSString, &error)
        return .some(got?.takeUnretainedValue())
    }

    static func role(_ e: Any) -> NSAccessibility.Role? {
        if let answered = server(e, .role) {
            return (answered as? String).map { NSAccessibility.Role(rawValue: $0) }
        }
        if let p = e as? NSAccessibilityProtocol { return p.accessibilityRole() }
        return nil
    }

    static func children(_ e: Any) -> [Any] {
        if let answered = server(e, .children) { return (answered as? [Any]) ?? [] }
        if let p = e as? NSAccessibilityProtocol { return p.accessibilityChildren() ?? [] }
        return []
    }

    static func value(_ e: Any) -> Any? {
        if let answered = server(e, .value) { return answered }
        return (e as? NSAccessibilityProtocol)?.accessibilityValue()
    }

    static func label(_ e: Any) -> String {
        if let answered = server(e, .description) { return text(answered) }
        return text((e as? NSAccessibilityProtocol)?.accessibilityLabel())
    }

    static func title(_ e: Any) -> String {
        if let answered = server(e, .title) { return text(answered) }
        return text((e as? NSAccessibilityProtocol)?.accessibilityTitle())
    }

    static func titleElement(_ e: Any) -> Any? {
        if let answered = server(e, .titleUIElement) { return answered }
        return (e as? NSAccessibilityProtocol)?.accessibilityTitleUIElement()
    }

    static func text(_ any: Any?) -> String {
        if let s = any as? String { return s.trimmingCharacters(in: .whitespacesAndNewlines) }
        if let a = any as? NSAttributedString {
            return a.string.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return ""
    }

    /// What VoiceOver says the thing is called: its label, or for a button its
    /// title, or the title of the element named as its title.
    static func spokenName(_ e: Any) -> String {
        let said = label(e)
        if !said.isEmpty { return said }
        if let r = role(e), titledRoles.contains(r) {
            let t = title(e)
            if !t.isEmpty { return t }
        }
        if let linked = titleElement(e) {
            for said in [title(linked), text(value(linked)), label(linked)] where !said.isEmpty {
                return said
            }
        }
        return ""
    }

    /// Where a nameless control is, in words a person fixing it can find:
    /// its class, and the text on the page just before it.
    private static func whereIs(_ e: Any, near: String) -> String {
        let kind = String(describing: type(of: e))
        var bits = [kind]
        if let v = e as? NSView {
            if let title = (v as? NSButton)?.title, !title.isEmpty { bits.append("titled \"\(title)\"") }
            if let popup = v as? NSPopUpButton, let first = popup.itemTitles.first {
                bits.append("first item \"\(first)\"")
            }
            if let tip = v.toolTip, !tip.isEmpty { bits.append("tooltip \"\(tip.prefix(60))\"") }
        }
        if !near.isEmpty { bits.append("after \"\(near.prefix(60))\"") }
        return bits.joined(separator: ", ")
    }

    // ------------------------------------------------------------ the walker --

    private var seen = Set<ObjectIdentifier>()
    private var found: [Control] = []
    /// The last piece of static text passed, which is what a sighted person
    /// would take as the name of the next control.
    private var lastText = ""

    /// Read one window's worth of elements under `root`, report every nameless
    /// control and every indistinguishable pair, and return how many controls
    /// there were.
    /// Draw a view and everything in it into a bitmap nobody sees.
    ///
    /// A control's cell is the element VoiceOver is handed, and a cell only
    /// knows which control it belongs to, and so which label, once it has
    /// been drawn in it (`NSCell.controlView` is "the view in which the cell
    /// was most recently drawn"). A window that has never been on screen has
    /// drawn nothing, so without this every popup and slider reads as
    /// nameless when on screen it is not.
    static func draw(_ view: NSView) {
        if view.frame.size.width < 1 || view.frame.size.height < 1 {
            view.setFrameSize(NSSize(width: max(view.frame.width, 400),
                                     height: max(view.frame.height, 24)))
        }
        view.layoutSubtreeIfNeeded()
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: rep)
    }

    @discardableResult
    func audit(_ window: String, _ root: Any) -> Int {
        if let view = root as? NSView { AccessibilityAudit.draw(view) }
        seen.removeAll()
        found.removeAll()
        lastText = ""
        walk(root, scope: window, inTable: false, window: window)
        let count = found.count
        checked += count
        perWindow.append((window, count))
        reportDuplicates(window)
        return count
    }

    private func walk(_ e: Any, scope: String, inTable: Bool, window: String) {
        let object = e as AnyObject
        let id = ObjectIdentifier(object)
        guard !seen.contains(id) else { return }
        seen.insert(id)
        if let v = e as? NSView, v.isHidden { return }

        if let tabs = e as? NSTabView {
            walkTabs(tabs, scope: scope, inTable: inTable, window: window)
            return
        }

        let role = AccessibilityAudit.role(e)
        if ProcessInfo.processInfo.environment["DROPDECK_A11Y_DEBUG"] != nil {
            print("DEBUG \(window) | \(type(of: e)) | \(role?.rawValue ?? "-") | "
                  + "name \(AccessibilityAudit.spokenName(e)) | "
                  + "value \(AccessibilityAudit.text(AccessibilityAudit.value(e)).prefix(60))")
        }
        if role == .staticText {
            let said = AccessibilityAudit.text(AccessibilityAudit.value(e))
            let label = AccessibilityAudit.spokenName(e)
            if !said.isEmpty || !label.isEmpty { lastText = said.isEmpty ? label : said }
        }
        // A scroll bar's arrows and page areas are parts of the bar, named by
        // their subrole, never in the Tab order, and not the app's to label.
        if role == .scrollBar { return }
        if let role, AccessibilityAudit.controlRoles.contains(role) {
            record(e, role: role, scope: scope, inTable: inTable, window: window)
            if let table = e as? NSTableView {
                walkCells(table, scope: scope, window: window)
            }
            return
        }
        for child in AccessibilityAudit.children(e) {
            walk(child, scope: scope, inTable: inTable, window: window)
        }
        // A plain view that is not an accessibility element still has to hand
        // over its subviews; AppKit does that through accessibilityChildren,
        // and this is the fallback for one that has not been laid out.
        if let v = e as? NSView, AccessibilityAudit.children(e).isEmpty {
            for sub in v.subviews { walk(sub, scope: scope, inTable: inTable, window: window) }
        }
    }

    private func record(_ e: Any, role: NSAccessibility.Role, scope: String,
                        inTable: Bool, window: String) {
        let name = AccessibilityAudit.spokenName(e)
        found.append(Control(role: role, name: name, scope: scope, inTable: inTable))
        if name.isEmpty {
            fail("\(window): a \(role.rawValue.replacingOccurrences(of: "AX", with: "")) "
                 + "with no spoken name (\(AccessibilityAudit.whereIs(e, near: lastText)))")
        }
    }

    /// Every tab, one at a time, because only the chosen one's page is in the
    /// tree. The tab itself is a control: it is what you arrow along.
    private func walkTabs(_ tabs: NSTabView, scope: String, inTable: Bool, window: String) {
        let label = AccessibilityAudit.spokenName(tabs)
        if label.isEmpty { fail("\(window): a tab group with no spoken name") }
        let before = tabs.selectedTabViewItem
        for item in tabs.tabViewItems {
            found.append(Control(role: .radioButton, name: item.label, scope: scope,
                                 inTable: inTable))
            if item.label.trimmingCharacters(in: .whitespaces).isEmpty {
                fail("\(window): a tab with no name in \(label)")
            }
            tabs.selectTabViewItem(item)
            if let view = item.view {
                AccessibilityAudit.draw(view)
                walk(view, scope: "\(scope), \(item.label)", inTable: inTable, window: window)
            }
        }
        if let before { tabs.selectTabViewItem(before) }
    }

    /// The cells a table is showing, made the way the table makes them, since
    /// a window that has never been drawn has made none. Every control inside
    /// a cell is checked like any other.
    private func walkCells(_ table: NSTableView, scope: String, window: String) {
        let rows = min(table.numberOfRows, 40)
        for row in 0..<max(0, rows) {
            for (index, column) in table.tableColumns.enumerated() {
                let cell = table.view(atColumn: index, row: row, makeIfNecessary: true)
                    ?? table.delegate?.tableView?(table, viewFor: column, row: row)
                guard let cell else { continue }
                AccessibilityAudit.draw(cell)
                walk(cell, scope: "\(scope), row \(row + 1)", inTable: true, window: window)
            }
        }
    }

    /// Two controls of the same kind with the same name, on the same page,
    /// outside a table. Rows in a table are told apart by the row, so a
    /// column of ticks all called Play is right, not a fault.
    private func reportDuplicates(_ window: String) {
        var groups: [String: Int] = [:]
        for c in found where !c.inTable && !c.name.isEmpty {
            groups["\(c.scope)\u{0}\(c.role.rawValue)\u{0}\(c.name)", default: 0] += 1
        }
        for (key, count) in groups.sorted(by: { $0.key < $1.key }) where count > 1 {
            let parts = key.components(separatedBy: "\u{0}")
            warn("\(parts[0]): \(count) \(parts[1].replacingOccurrences(of: "AX", with: "")) "
                 + "controls all called \"\(parts[2])\"")
        }
    }

    // ------------------------------------------------------- the running order --

    /// Why a running order tick would mislead, or nil when it tells the truth.
    ///
    /// The value is the tick, one or zero, and the label never states it. The
    /// old tick was labelled "Ticked to play" on every row, so VoiceOver said
    /// "Ticked to play" whether or not it was ticked: that fails here on the
    /// label, whatever the value says.
    static func tickFault(_ box: Any, ticked: Bool) -> String? {
        let value = (AccessibilityAudit.value(box) as? NSNumber)?.intValue
        let name = spokenName(box)
        if value != (ticked ? 1 : 0) {
            return "its value is \(value.map(String.init) ?? "missing"), "
                 + "not \(ticked ? 1 : 0)"
        }
        if name.lowercased().contains("ticked") || name.lowercased().contains("ticked to play") {
            return "its label \"\(name)\" states a tick"
        }
        if name.isEmpty { return "it has no spoken name" }
        return nil
    }

    /// The first check box in a view and everything under it.
    static func firstCheckBox(in e: Any) -> Any? {
        if role(e) == .checkBox { return e }
        for child in children(e) {
            if let got = firstCheckBox(in: child) { return got }
        }
        if let v = e as? NSView {
            for sub in v.subviews { if let got = firstCheckBox(in: sub) { return got } }
        }
        return nil
    }
}

// ---------------------------------------------------------------- the check ---

enum AccessibilityCheck {

    /// Build everything, read everything, print what is wrong. Non zero when
    /// anything failed.
    static func run() -> Int32 {
        let folder = (NSTemporaryDirectory() as NSString)
            .appendingPathComponent("dropdeck-a11y-\(ProcessInfo.processInfo.processIdentifier)")
        try? FileManager.default.createDirectory(atPath: folder,
                                                 withIntermediateDirectories: true)
        setenv(Board.dataEnvironment, folder, 1)
        defer { try? FileManager.default.removeItem(atPath: folder) }

        let app = DropDeckApplication.shared
        app.setActivationPolicy(.prohibited)

        let audit = AccessibilityAudit()
        auditEverything(audit, folder: folder)

        for (window, count) in audit.perWindow {
            print("  \(window): \(count) controls")
        }
        for (level, line) in audit.findings { print("\(level.rawValue)  \(line)") }
        print("\(audit.checked) controls checked, \(audit.failed) failed, "
              + "\(audit.warned) warnings")
        return audit.failed > 0 ? 1 : 0
    }

    /// Every window and panel the app has, built for real and read. Also
    /// called by the self test.
    static func auditEverything(_ audit: AccessibilityAudit, folder: String) {
        let dirBefore = Board.configDirOverride
        let offlineBefore = Secrets.offline
        let mutedBefore = Speaker.muted
        Board.configDirOverride = folder
        Secrets.offline = true
        Speaker.muted = true
        // Read INSIDE the capture, while the function that built the panel
        // is still on the stack: a panel's controller (the Preferences page
        // list, a table's data source) is held by that function and nothing
        // else, and is gone the moment it returns.
        var built = 0
        var current = ""
        ModalAudit.capture = { alert in
            alert.layout()
            built += 1
            let label = alert.messageText.isEmpty ? current : alert.messageText
            if label == "Preferences" {
                readPreferences(audit, alert)
            } else if let content = alert.window.contentView {
                audit.audit(label, content)
            }
        }
        defer {
            ModalAudit.capture = nil
            Board.configDirOverride = dirBefore
            Secrets.offline = offlineBefore
            Speaker.muted = mutedBefore
        }

        // A board worth reading: a few pads with sounds, and a running order
        // with some rows ticked and some not.
        let board = Board()
        for (i, name) in ["Intro", "Station ident", "Applause"].enumerated() {
            board.slots[i].filepath = "/nowhere/\(name).wav"
            board.slots[i].name = name
        }
        let ticks = [true, false, true, false]
        for (i, on) in ticks.enumerated() {
            let t = Track(filepath: "/nowhere/song\(i + 1).mp3")
            t.title = "Song \(i + 1)"
            t.artist = "Artist \(i + 1)"
            t.duration = 180
            t.tailSilence = 0
            t.enabled = on
            board.playlist.tracks.append(t)
        }

        let main = MainWindow(board: board)
        let delegate = AppDelegate()
        delegate.main = main
        delegate.buildMenus()

        // --------------------------------------------------- the main window --
        if let content = main.window?.contentView {
            audit.audit("Main window, the soundboard", content)
            main.playlistView.isHidden = false
            main.playlistView.refresh()
            audit.audit("Main window, the running order", main.playlistView!)
            main.playlistView.isHidden = true
        }
        checkRunningOrder(audit, main: main, ticks: ticks)

        // -------------------------------------------------------------- panels --
        func read(_ name: String, _ open: () -> Void) {
            built = 0
            current = name
            open()
            if built == 0 { audit.fail("\(name): the window was never built") }
        }

        read("Preferences") { main.showPreferences(tab: nil) }
        read("Send this show to another program") { main.showSendSetup() }

        // A source to control, a stand in that opens nothing.
        let stand = AuditSource(name: "Co-host")
        board.sources = [stand.config]
        main.sourceGroup.useForTesting([stand])
        read("Source control") { main.showSourceControl() }
        read("Audio sources") { main.showSources() }
        read("Picture") { main.showVideoSource() }
        read("Go live") {
            _ = GoLivePanel(report: main.preflight(), board: board).run(over: nil)
        }
        read("Check my shot") {
            ShotCheckPanel(board: board, speaker: main.speaker, window: nil,
                           kind: "camera", grab: { nil }).run(over: nil)
        }
        read("Check the keyboard") { main.showKeyboardCheck() }
        read("Keyboard shortcuts") { main.showShortcuts() }
        read("Screen text") { main.showScreenText() }
        read("Colours") { main.showColours() }
        read("Setting up streaming") { main.showStreamHelp() }
        read("What Drop Deck is allowed to do") { main.showPermissions() }
        read("Check my audio sources") { main.showSourceCheck() }
        read("Drops library") { main.showDropsLibrary() }
        read("Search sounds") { main.showSearch() }
        read("Properties") { _ = SlotPropertiesPanel(slot: board.slots[0]).run(over: nil) }
        read("Hotkey") {
            _ = HotkeyPanel(title: "Assign a hotkey", global: false, current: nil,
                            speaker: main.speaker).run(over: nil)
        }
        read("Crossfade for one track") {
            _ = TrackCrossfadePanel(track: board.playlist.tracks[0],
                                    defaultSeconds: 2).run(over: nil)
        }
        read("Put a removed slot back") {
            _ = ChoicePanel(title: "Put a removed slot back", message: "Which one?",
                            options: ["Bank 1, slot 4", "Bank 2, slot 1"]).run(over: nil)
        }
        read("Submit feedback") { _ = FeedbackPanel(diagnostics: [:]).run(over: nil) }
        read("A one line prompt") {
            _ = main.ask(title: "Rename", message: "What should this be called?",
                         value: "Intro")
        }

        // The cue sheet is a window of its own rather than a panel.
        let cue = CueSheetWindow(main: main)
        cue.build()
        if let content = cue.window?.contentView { audit.audit("What is coming up", content) }
        cue.window?.close()

        checkTheCheckCanSee(audit)
        checkPreferencesHasTheNewControls(audit)
        checkSendHasTheCableTest(audit)
        checkMenus(audit, delegate: delegate)
    }

    /// The walk is shown two nameless controls, a popup and a picture only
    /// button, and must report both. A check that reports nothing because it
    /// cannot see anything would look exactly like a clean app.
    private static func checkTheCheckCanSee(_ audit: AccessibilityAudit) {
        let box = NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 80))
        let popup = NSPopUpButton(frame: NSRect(x: 0, y: 40, width: 200, height: 26))
        popup.addItem(withTitle: "Something chosen")
        box.addSubview(popup)
        let picture = NSButton(frame: NSRect(x: 0, y: 0, width: 40, height: 30))
        picture.title = ""
        picture.image = NSImage(size: NSSize(width: 16, height: 16))
        box.addSubview(picture)
        let named = NSButton(title: "Named", target: nil, action: nil)
        named.frame = NSRect(x: 60, y: 0, width: 100, height: 30)
        box.addSubview(named)
        let probe = AccessibilityAudit()
        probe.audit("probe", box)
        if probe.failed != 2 || probe.checked != 3 {
            audit.fail("The check itself: shown two nameless controls and one named one, "
                       + "it found \(probe.failed) nameless of \(probe.checked)")
        }
    }

    // ----------------------------------------------------------- preferences --

    /// What the Preferences pages must hold, found while they were read.
    private static var preferenceNames: [String: [(NSAccessibility.Role, String)]] = [:]
    private static var sendNames: [(NSAccessibility.Role, String)] = []

    /// Every page, one at a time: only the chosen one is in the window.
    private static func readPreferences(_ audit: AccessibilityAudit, _ alert: NSAlert) {
        guard let content = alert.window.contentView,
              let list = findTable(in: content, named: "Settings categories"),
              let pages = list.dataSource as? SettingsCategories else {
            audit.fail("Preferences: the category list is not there")
            return
        }
        preferenceNames = [:]
        for label in pages.labels {
            pages.select(label)
            audit.audit("Preferences, \(label)", content)
            preferenceNames[label] = names(in: content)
        }
    }

    private static func checkPreferencesHasTheNewControls(_ audit: AccessibilityAudit) {
        let wanted: [(String, NSAccessibility.Role, String)] = [
            ("Video streaming", .textField, "Channel name"),
            ("Video streaming", .button, "Check my stream key"),
            ("Video streaming", .textArea, "What happened"),
            ("Video streaming", .textField, "Stream key"),
            ("Streaming", .popUpButton, "How a song is named"),
            ("Microphone", .popUpButton, "Microphone"),
            ("Output", .popUpButton, "Main output"),
            ("Recording", .popUpButton, "Record as"),
            ("Keyboard", .popUpButton, "Which keys fire banks 2 and 3"),
        ]
        for (page, role, name) in wanted {
            guard let names = preferenceNames[page] else {
                audit.fail("Preferences: there is no \(page) page")
                continue
            }
            if !names.contains(where: { $0.0 == role && $0.1 == name }) {
                audit.fail("Preferences, \(page): no \(role.rawValue) called \"\(name)\"")
            }
        }
    }

    private static func checkSendHasTheCableTest(_ audit: AccessibilityAudit) {
        // Read again on its own: the send panel's names, from the real one.
        let panel = SendPanel(board: Board(), sources: [], speaker: nil, refusal: { nil },
                              outputs: [])
        let accessory = panel.makeAccessory()
        AccessibilityAudit.draw(accessory)
        sendNames = names(in: accessory)
        if !sendNames.contains(where: { $0.0 == .button && $0.1 == "Test the cable" }) {
            audit.fail("Send this show to another program: no button called \"Test the cable\"")
        }
    }

    /// Every named control under a view, as role and name.
    private static func names(in root: Any) -> [(NSAccessibility.Role, String)] {
        var out: [(NSAccessibility.Role, String)] = []
        var seen = Set<ObjectIdentifier>()
        func walk(_ e: Any) {
            let id = ObjectIdentifier(e as AnyObject)
            guard !seen.contains(id) else { return }
            seen.insert(id)
            if let v = e as? NSView, v.isHidden { return }
            if let role = AccessibilityAudit.role(e),
               AccessibilityAudit.controlRoles.contains(role) {
                out.append((role, AccessibilityAudit.spokenName(e)))
                return
            }
            for child in AccessibilityAudit.children(e) { walk(child) }
            if let v = e as? NSView, AccessibilityAudit.children(e).isEmpty {
                for sub in v.subviews { walk(sub) }
            }
        }
        walk(root)
        return out
    }

    private static func findTable(in view: NSView, named name: String) -> NSTableView? {
        if let t = view as? NSTableView, t.accessibilityLabel() == name { return t }
        for sub in view.subviews {
            if let got = findTable(in: sub, named: name) { return got }
        }
        return nil
    }

    // ----------------------------------------------------- the running order --

    /// Siena's report: every row said "Ticked to play". Read from the real
    /// running order's own table, row by row, and proved able to see the old
    /// fault by showing it the old tick.
    private static func checkRunningOrder(_ audit: AccessibilityAudit, main: MainWindow,
                                          ticks: [Bool]) {
        let view: PlaylistView = main.playlistView
        guard let table = findTable(in: view, named: "Running order") else {
            audit.fail("Running order: the table is not there")
            return
        }
        for (row, ticked) in ticks.enumerated() {
            var box: Any?
            for (index, column) in table.tableColumns.enumerated() {
                let cell = table.view(atColumn: index, row: row, makeIfNecessary: true)
                    ?? table.delegate?.tableView?(table, viewFor: column, row: row)
                if let cell { AccessibilityAudit.draw(cell) }
                if let cell, let found = AccessibilityAudit.firstCheckBox(in: cell) {
                    box = found
                    break
                }
            }
            guard let box else {
                audit.fail("Running order, row \(row + 1): no tick box")
                continue
            }
            if let fault = AccessibilityAudit.tickFault(box, ticked: ticked) {
                audit.fail("Running order, row \(row + 1), \(ticked ? "ticked" : "not ticked"): "
                           + fault)
            }
        }

        // The old tick, exactly as 3.8.3 and before built it. If the rule
        // above passes this, the rule cannot see Siena's bug.
        let old = NSButton(checkboxWithTitle: "", target: nil, action: nil)
        old.setAccessibilityLabel("Ticked to play")
        old.state = .off
        // Asked of the cell, which is the element VoiceOver is handed.
        let oldElement: Any = old.cell ?? old
        if AccessibilityAudit.tickFault(oldElement, ticked: false) == nil {
            audit.fail("Running order: the check passes the old \"Ticked to play\" tick, "
                       + "so it cannot see Siena's bug")
        }
    }

    // ----------------------------------------------------------------- menus --

    private static func checkMenus(_ audit: AccessibilityAudit, delegate: AppDelegate) {
        guard let bar = NSApp.mainMenu else {
            audit.fail("Menus: there is no menu bar")
            return
        }
        var count = 0
        var items: [NSMenuItem] = []
        func walk(_ menu: NSMenu, path: String, top: Bool) {
            for (index, item) in menu.items.enumerated() where !item.isSeparatorItem {
                count += 1
                items.append(item)
                var name = item.title.trimmingCharacters(in: .whitespaces)
                if name.isEmpty { name = item.submenu?.title ?? "" }
                // The first menu is the application's, which macOS names
                // after the app whatever it is called here.
                if name.isEmpty && !(top && index == 0) {
                    audit.fail("Menus, \(path): item \(index + 1) has no title")
                }
                if let sub = item.submenu {
                    walk(sub, path: path.isEmpty ? (name.isEmpty ? C.appName : name)
                                                 : "\(path), \(name)", top: false)
                }
            }
        }
        walk(bar, path: "", top: true)

        func command(_ c: Command) -> NSMenuItem? {
            items.first { ($0.representedObject as? String) == c.rawValue }
        }
        func expect(_ c: Command, key: String, mods: NSEvent.ModifierFlags,
                    word: String, spoken: String) {
            guard let item = command(c) else {
                audit.fail("Menus, On air: no item for \(spoken)")
                return
            }
            let got = item.keyEquivalentModifierMask.intersection([.command, .option,
                                                                   .control, .shift])
            if item.keyEquivalent.lowercased() != key || got != mods {
                audit.fail("Menus, On air: \"\(item.title)\" is on "
                           + "\(KeyMap.spell(key: item.keyEquivalent, mods: got)), "
                           + "not \(spoken)")
            }
            if !item.title.lowercased().contains(word) {
                audit.fail("Menus, On air: the \(spoken) item is called \"\(item.title)\", "
                           + "which does not say \(word)")
            }
            if item.menu?.title != "On air" {
                audit.fail("Menus: \"\(item.title)\" is not in the On air menu")
            }
        }
        expect(.streamToggle, key: "b", mods: [.command], word: "video",
               spoken: "Command+B")
        expect(.streamToggleRadio, key: "b", mods: [.option, .shift], word: "radio",
               spoken: "Option+Shift+B")

        // Option+Shift+M reaches the microphone: the key is an alias, so it is
        // the key monitor's to dispatch, and it dispatches to the same place
        // the Microphone item goes.
        let event = NSEvent.keyEvent(
            with: .keyDown, location: .zero, modifierFlags: [.option, .shift],
            timestamp: 0, windowNumber: 0, context: nil, characters: "M",
            charactersIgnoringModifiers: "m", isARepeat: false, keyCode: 46)
        let alias = event.flatMap { KeyMap.aliasCommand(for: $0) }
        if alias != .micToggle {
            audit.fail("Menus: Option+Shift+M goes to \(alias.map { $0.rawValue } ?? "nothing"), "
                       + "not the microphone")
        }
        if let mic = command(.micToggle) {
            if mic.action != #selector(AppDelegate.toggleMic) {
                audit.fail("Menus: the Microphone item does not turn the microphone on and off")
            }
        } else {
            audit.fail("Menus, On air: no Microphone item")
        }
        audit.note(window: "Menus", count: count)
    }
}

extension AccessibilityAudit {
    /// Controls counted somewhere other than a view walk, the menus.
    func note(window: String, count: Int) {
        checked += count
        perWindow.append((window, count))
    }
}

/// A source that opens nothing, so Source control has something to list.
final class AuditSource: RunningSource {
    var config: SourceConfig
    var isRunning = true
    var lastError: String?
    var peak: Float = 0

    init(name: String) {
        var c = SourceConfig()
        c.name = name
        c.onAir = true
        config = c
    }

    @discardableResult func start(outputRate: Double) -> Bool { true }
    func stop() {}
    func readAir(frames: Int, into out: UnsafeMutablePointer<Float>) {
        out.update(repeating: 0, count: frames * 2)
    }
    func readMonitor(frames: Int, into out: UnsafeMutablePointer<Float>) {
        out.update(repeating: 0, count: frames * 2)
    }
}

// ------------------------------------------------------------ the self test ---

extension SelfTest {

    /// The whole of `--check-accessibility`, as two checks. After every
    /// check that spins the run loop, because it builds a real main window
    /// whose timers would otherwise tick through them; only the real sound
    /// card comes after it, and that waits with a plain sleep.
    func runAccessibilityChecks() {
        out.append("")
        out.append("Every window read the way VoiceOver reads it (--check-accessibility)")
        _ = NSApplication.shared
        let folder = (NSTemporaryDirectory() as NSString)
            .appendingPathComponent("dropdeck-selftest-a11y")
        try? FileManager.default.createDirectory(atPath: folder,
                                                 withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(atPath: folder) }
        let audit = AccessibilityAudit()
        AccessibilityCheck.auditEverything(audit, folder: folder)
        check("every window and menu was read", audit.checked > 300 && audit.perWindow.count > 30,
              "\(audit.checked) controls in \(audit.perWindow.count) windows")
        let failed = audit.findings.filter { $0.0 == .fail }.map(\.1)
        check("every control has a spoken name, the running order ticks tell the truth, "
              + "and the go live and microphone keys are where the manual says",
              failed.isEmpty, failed.prefix(5).joined(separator: "; "))
    }
}
