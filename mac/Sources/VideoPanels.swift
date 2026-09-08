// The windows the video half added: what is on the screen, what is on top of
// it, what it looks like, and what Command B is about to do.
//
// Built against docs/MAC-A11Y-SPEC.md, which was written from the Windows
// dialogs and from the conventions the existing panels already keep. Three
// facts from it shape every window here, because AppKit will never tell
// VoiceOver any of them:
//
//   1. **A label whose text changes says nothing.** Every one of the Windows
//      windows has a line under its list that changes as you arrow, and it is
//      silent on both platforms. So it stays, for a sighted reader, and
//      anything a blind user must hear goes into a table cell or through the
//      Speaker.
//   2. **A table cell that changes under the cursor is not re-read.** After a
//      reload that leaves the selection where it was, VoiceOver says nothing
//      even though the cell just changed. That is why every state change here
//      has a spoken line beside it, and why the line is not politeness.
//   3. **A disabled control leaves the Tab loop.** So a control is disabled
//      only when the reason is somewhere a Tab user will pass.
//
// Every panel is an NSAlert with an accessoryView, like every other panel in
// this app, so that the Speaker's announcements land inside it and Escape
// behaves. Each claims Escape for itself, because AppKit wires it only to a
// button called "Cancel" and none of these buttons is called that.

import AppKit
import CoreVideo

/// The Escape claim every panel here installs, with the two guards the spec
/// calls load bearing.
///
/// The second one is why renaming a source was broken before 3.5.2: a claim
/// that keeps answering while a nested box is up eats the keys meant for it.
enum PanelKeys {
    static func run(_ alert: NSAlert, extra: ((NSEvent) -> Bool)? = nil) -> NSApplication.ModalResponse {
        var response: NSApplication.ModalResponse = .alertFirstButtonReturn
        ModalKeys.claim({ event in
            guard NSApp.keyWindow === alert.window else { return false }
            guard !(alert.window.firstResponder is NSTextView) else { return false }
            if event.keyCode == 53 {                       // Escape
                NSApp.stopModal(withCode: .alertSecondButtonReturn)
                return true
            }
            return extra?(event) ?? false
        }, window: alert.window) {
            response = alert.runModal()
        }
        return response
    }
}

/// A table that answers Return and Space itself.
///
/// A subclass rather than a key claim, because a subclass cannot be reached
/// while another control has focus, which is exactly the property wanted: the
/// popup below the list must go on getting its own keys.
final class ActionTable: NSTableView {
    var onChoose: (() -> Void)?
    var onDelete: (() -> Void)?
    override func keyDown(with event: NSEvent) {
        let key = event.charactersIgnoringModifiers ?? ""
        if key == "\r" || key == " " {
            onChoose?()
            return
        }
        if let onDelete,
           key == String(UnicodeScalar(NSDeleteFunctionKey)!) || key == "\u{8}" {
            onDelete()
            return
        }
        super.keyDown(with: event)
    }
}

// ------------------------------------------------------------ video source ---

/// What the stream is showing. Option+Shift+V.
///
/// A switcher, not a settings page. There is no OK, because a list you have to
/// arrow through and then Tab out of to confirm is not something anybody uses
/// mid link.
final class VideoSourcePanel: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private let board: Board
    private let speaker: Speaker
    private let live: Bool
    /// Told to put one on the air. Answers with what went wrong, or "".
    private let apply: (String) -> String
    private let applyCorner: (String) -> Void

    private var table: ActionTable!
    private var doing: NSTextField!
    private var kinds: [String] = []

    init(board: Board, speaker: Speaker, live: Bool,
         apply: @escaping (String) -> String,
         applyCorner: @escaping (String) -> Void) {
        self.board = board
        self.speaker = speaker
        self.live = live
        self.apply = apply
        self.applyCorner = applyCorner
        super.init()
    }

    /// What this machine can really offer.
    ///
    /// A machine with no camera is not offered a camera, and one whose screen
    /// cannot be captured is not offered its screen. An entry that would
    /// always fail is worse than a shorter list.
    private func offered() -> [String] {
        let hasCamera = !Cameras.all().isEmpty
        let hasScreen = Screens.available()
        return C.pictureSources.filter { kind in
            if C.pictureNeedsCamera.contains(kind) && !hasCamera { return false }
            if C.pictureNeedsScreen.contains(kind) && !hasScreen { return false }
            return true
        }
    }

    /// What a row's third column says.
    ///
    /// The split names the REAL corner. Windows leaves the constant's fixed
    /// "bottom corner" wording in the column, which is what a screen reader
    /// reads, and puts the truth only in the silent line underneath. So on
    /// Windows the row says "bottom corner" while the corner is top right.
    private func sentence(_ kind: String) -> String {
        guard kind == C.pictureSplit else { return C.pictureDescriptions[kind] ?? "" }
        return "Your screen filling the frame with the camera small in the "
             + "\(board.splitCorner) corner. The screen stays readable this way."
    }

    func run(over parent: NSWindow?) {
        kinds = offered()
        let alert = NSAlert()
        alert.messageText = "Video source"
        alert.informativeText = live
            ? "Up and down read the choices. Return puts one on the air."
            : "Up and down read the choices. Return picks one for the next time you go live."
        alert.addButton(withTitle: "Close")

        let box = NSView(frame: NSRect(x: 0, y: 0, width: 620, height: 320))
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 70, width: 620, height: 250))
        table = ActionTable(frame: scroll.bounds)
        // The second column's title is decided ONCE, from whether a picture is
        // really going out. Windows titles it "On air" always and writes "yes"
        // off air as well, which tells somebody who cannot look at a preview
        // that a card is on the air when nothing is.
        for (id, title, width) in [("name", "Source", 220),
                                   ("air", live ? "On air" : "Chosen", 70),
                                   ("what", "What it sends", 320)] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id))
            column.title = title
            column.width = CGFloat(width)
            table.addTableColumn(column)
        }
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel("Video sources")
        table.onChoose = { [weak self] in self?.choose() }
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        box.addSubview(scroll)

        // Kept enabled at all times, and NOT disabled off the split row.
        // Windows disables it and writes down why, and the reason is right;
        // on AppKit disabling causes exactly the movement it was avoiding,
        // because a disabled control drops out of the Tab loop, so arrowing
        // the list would change how many Tab presses reach Close.
        let corner = NSPopUpButton(frame: NSRect(x: 0, y: 38, width: 220, height: 26))
        corner.addItems(withTitles: C.splitCorners.map { $0.capitalisedWords })
        corner.selectItem(at: C.splitCorners.firstIndex(of: board.splitCorner) ?? 0)
        corner.setAccessibilityLabel("Camera corner")
        corner.target = self
        corner.action = #selector(cornerChanged(_:))
        box.addSubview(corner)

        doing = NSTextField(wrappingLabelWithString: "")
        doing.frame = NSRect(x: 240, y: 26, width: 380, height: 40)
        doing.setAccessibilityLabel("What this one does")
        box.addSubview(doing)

        alert.accessoryView = box
        let start = kinds.firstIndex(of: board.picture) ?? 0
        table.selectRowIndexes(IndexSet(integer: start), byExtendingSelection: false)
        alert.window.initialFirstResponder = table
        describe()
        _ = PanelKeys.run(alert)
    }

    @objc private func cornerChanged(_ sender: NSPopUpButton) {
        let picked = C.splitCorners[max(0, min(C.splitCorners.count - 1,
                                               sender.indexOfSelectedItem))]
        board.splitCorner = picked
        board.dirty = true
        applyCorner(picked)
        // Applied and saved at once rather than on closing, because the whole
        // point of this window is trying it.
        if board.picture == C.pictureSplit {
            speaker.announceState("Camera in the \(picked)")
        } else {
            speaker.announceState("Camera in the \(picked), for when you show your "
                                + "screen with the camera in the corner")
        }
        table.reloadData()
        describe()
    }

    private func choose() {
        let row = max(0, table.selectedRow)
        guard row < kinds.count else { return }
        let kind = kinds[row]
        let label = (C.pictureLabels[kind] ?? kind).lowercased()
        let trouble = apply(kind)
        table.reloadData()
        table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
        describe()
        // The only thing that reports the change: the two rows whose cell just
        // flipped are not re-read by VoiceOver.
        if !trouble.isEmpty {
            speaker.announceState("That did not work: \(trouble). Still showing a card")
        } else if live {
            speaker.announceState("Now showing \(label)")
        } else {
            speaker.announceState("Next time you go live: \(label)")
        }
    }

    private func describe() {
        let row = max(0, table.selectedRow)
        guard row < kinds.count else { return }
        let kind = kinds[row]
        let label = (C.pictureLabels[kind] ?? kind).lowercased()
        let detail = sentence(kind)
        if kind == board.picture {
            doing.stringValue = (live ? "This is the one going out now.  "
                                      : "This is the one chosen.  ") + detail
        } else {
            doing.stringValue = (live ? "Return puts \(label) on the air.  "
                                      : "Return picks \(label).  ") + detail
        }
    }

    func numberOfRows(in tableView: NSTableView) -> Int { kinds.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard row < kinds.count, let column = tableColumn else { return nil }
        let kind = kinds[row]
        let text: String
        switch column.identifier.rawValue {
        case "name": text = C.pictureLabels[kind] ?? kind
        case "air": text = kind == board.picture ? "yes" : "no"
        default: text = sentence(kind)
        }
        let cell = NSTextField(labelWithString: text)
        cell.setAccessibilityLabel(text)
        return cell
    }

    func tableViewSelectionDidChange(_ notification: Notification) {
        // Nothing is spoken. VoiceOver reads the row, which carries the name,
        // whether it is live, and the whole sentence. Speaking as well would
        // be the row read twice.
        describe()
    }
}

extension String {
    /// "bottom right" becomes "Bottom right", which is how a corner is offered.
    var capitalisedWords: String {
        guard let first = self.first else { return self }
        return String(first).uppercased() + dropFirst()
    }
}

// ------------------------------------------------------------- screen text ---

/// Four named places on top of the picture. Option+Shift+T.
///
/// **There are no coordinates anywhere and that is the feature.** The answer
/// to "what is on screen" is four lines long, which is the only reason it can
/// be checked without looking.
final class ScreenTextPanel: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private let board: Board
    private let speaker: Speaker
    private let live: Bool
    private let window: NSWindow?
    private let ask: (String, String, String, String) -> String?
    /// Told that the places changed, so the picture going out is rebuilt.
    private let apply: () -> Void
    /// What is playing now, for the "Which is" column.
    private let nowPlaying: () -> String

    private var table: ActionTable!
    private var doing: NSTextField!
    private var emptyButton: NSButton!

    init(board: Board, speaker: Speaker, live: Bool, window: NSWindow?,
         ask: @escaping (String, String, String, String) -> String?,
         nowPlaying: @escaping () -> String,
         apply: @escaping () -> Void) {
        self.board = board
        self.speaker = speaker
        self.live = live
        self.window = window
        self.ask = ask
        self.nowPlaying = nowPlaying
        self.apply = apply
        super.init()
    }

    /// What this place would actually be saying right now.
    ///
    /// **The column that makes this window worth having**, because it answers
    /// "is my lower third actually saying anything" without going on the air.
    private func detail(_ key: String) -> String {
        let held = board.textPlaces[key] ?? [:]
        switch held["kind"] ?? C.textNone {
        case C.textWords:
            let words = held["words"] ?? ""
            return words.isEmpty ? "nothing typed yet" : words
        case C.textFile:
            let path = held["file"] ?? ""
            return path.isEmpty ? "no file chosen yet"
                                : (path as NSString).lastPathComponent
        case C.textStation:
            let name = board.stream.name
            return name.isEmpty ? "no station name set" : name
        case C.textPlaying:
            let title = nowPlaying()
            return title.isEmpty ? "nothing playing" : title
        case C.textTime:
            let formatter = DateFormatter()
            formatter.dateFormat = C.overlayClockFormat
            return formatter.string(from: Date())
        default:
            return ""
        }
    }

    func run(over parent: NSWindow?) {
        let alert = NSAlert()
        alert.messageText = "Screen text"
        alert.informativeText = live
            ? "Up and down read the places. Return chooses what goes in one. It changes while you are on air."
            : "Up and down read the places. Return chooses what goes in one."
        alert.addButton(withTitle: "Close")

        let box = NSView(frame: NSRect(x: 0, y: 0, width: 640, height: 300))
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 74, width: 640, height: 220))
        table = ActionTable(frame: scroll.bounds)
        for (id, title, width) in [("place", "Place", 120), ("where", "Where", 120),
                                   ("showing", "Showing", 160),
                                   ("which", "Which is", 220)] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id))
            column.title = title
            column.width = CGFloat(width)
            table.addTableColumn(column)
        }
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel("Places on the picture")
        table.onChoose = { [weak self] in self?.change() }
        table.onDelete = { [weak self] in self?.emptyIt() }
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        box.addSubview(scroll)

        doing = NSTextField(wrappingLabelWithString: "")
        doing.frame = NSRect(x: 0, y: 40, width: 640, height: 30)
        doing.setAccessibilityLabel("What this place does")
        box.addSubview(doing)

        let change = NSButton(title: "Change...", target: self,
                              action: #selector(changePressed))
        change.frame = NSRect(x: 0, y: 4, width: 120, height: 30)
        change.setAccessibilityLabel("Change")
        box.addSubview(change)

        // Left ENABLED even when the place is already empty. Disabling it
        // would take it out of the Tab loop as you arrow, which changes how
        // many Tab presses reach Close. It answers instead.
        emptyButton = NSButton(title: "Empty it", target: self,
                               action: #selector(emptyPressed))
        emptyButton.frame = NSRect(x: 130, y: 4, width: 120, height: 30)
        emptyButton.setAccessibilityLabel("Empty it")
        box.addSubview(emptyButton)

        alert.accessoryView = box
        table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        alert.window.initialFirstResponder = table
        describe()
        _ = PanelKeys.run(alert)
    }

    @objc private func changePressed() { change() }
    @objc private func emptyPressed() { emptyIt() }

    private func selected() -> (key: String, spot: OverlayPlace)? {
        let row = max(0, table.selectedRow)
        guard row < C.placesOrder.count else { return nil }
        let key = C.placesOrder[row]
        guard let spot = Overlays.byKey[key] else { return nil }
        return (key, spot)
    }

    private func change() {
        guard let (key, spot) = selected() else { return }
        let options = C.textKinds.map { C.textLabels[$0] ?? $0 }
        let picker = ChoicePanel(title: spot.label,
                                 message: "What should the \(spot.label.lowercased()) show?",
                                 options: options, okTitle: "Use this")
        guard let index = picker.run(over: window), index < C.textKinds.count else {
            let was = board.textPlaces[key]?["kind"] ?? C.textNone
            speaker.announceHelp("Left as \((C.textLabels[was] ?? "nothing").lowercased())")
            return
        }
        let kind = C.textKinds[index]
        var held = board.textPlaces[key] ?? ["kind": C.textNone, "words": "", "file": ""]

        if kind == C.textWords {
            let typed = ask(spot.label, "What should it say?", held["words"] ?? "",
                            "What it says")
            guard let typed else { speaker.announceHelp("Left as it was"); return }
            held["words"] = String(typed.prefix(200))
        } else if kind == C.textFile {
            let open = NSOpenPanel()
            open.allowedContentTypes = [.plainText, .text]
            open.allowsOtherFileTypes = true
            open.message = "Which text file? It is re-read a second after it changes, "
                         + "so anything else on this Mac that writes a text file can "
                         + "drive this place."
            let already = held["file"] ?? ""
            if !already.isEmpty {
                open.directoryURL = URL(fileURLWithPath: already).deletingLastPathComponent()
            }
            guard open.runModal() == .OK, let url = open.url else {
                speaker.announceHelp("Left as it was")
                return
            }
            held["file"] = url.path
        }
        held["kind"] = kind
        board.textPlaces[key] = held
        board.dirty = true
        apply()
        refresh()
        speaker.announceState("\(spot.label) now shows "
                            + "\((C.textLabels[kind] ?? kind).lowercased())")
    }

    private func emptyIt() {
        guard let (key, spot) = selected() else { return }
        let held = board.textPlaces[key] ?? [:]
        if (held["kind"] ?? C.textNone) == C.textNone {
            speaker.announceHelp("The \(spot.label.lowercased()) is already empty")
            return
        }
        var next = held
        next["kind"] = C.textNone
        board.textPlaces[key] = next
        board.dirty = true
        apply()
        refresh()
        speaker.announceState("\(spot.label) is empty now")
    }

    private func refresh() {
        let row = max(0, table.selectedRow)
        table.reloadData()
        table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
        table.window?.makeFirstResponder(table)
        describe()
    }

    private func describe() {
        guard let (key, spot) = selected() else { return }
        let kind = board.textPlaces[key]?["kind"] ?? C.textNone
        doing.stringValue = "\(spot.describeWhere()) \(spot.label.lowercased()). "
                          + (C.textDescriptions[kind] ?? "")
    }

    func numberOfRows(in tableView: NSTableView) -> Int { C.placesOrder.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard row < C.placesOrder.count, let column = tableColumn else { return nil }
        let key = C.placesOrder[row]
        let spot = Overlays.byKey[key]
        let kind = board.textPlaces[key]?["kind"] ?? C.textNone
        let text: String
        switch column.identifier.rawValue {
        case "place": text = spot?.label ?? key
        case "where":
            // The constant carries a trailing comma so it can be read into a
            // sentence. A column is not a sentence.
            text = (C.placeWhere[key] ?? "").replacingOccurrences(of: ",", with: "")
        case "showing": text = C.textLabels[kind] ?? kind
        default: text = detail(key)
        }
        let cell = NSTextField(labelWithString: text)
        cell.setAccessibilityLabel(text)
        return cell
    }

    func tableViewSelectionDidChange(_ notification: Notification) { describe() }
}

// -------------------------------------------------------------- asking it ---

/// Type a question about a picture, hear the answer, ask another.
///
/// One class, used by the shot check and the colours window, because it is the
/// same thing in both. It is handed a way to GET a picture rather than a
/// picture, because in both places the picture is built fresh: the shot check
/// opens the camera, and the colours window renders whatever the brand is at
/// that moment.
///
/// Three rules it inherits from the rest of the AI work. **Its own queue**,
/// always. **It never fails loudly.** And it is **never on the way to
/// anything**: closing the window while an answer is in the air is fine.
final class AskPanel: NSObject {

    private let speaker: Speaker
    private let board: Board
    private let kind: String
    private let label: String
    /// The picture to ask about, and whether it needs consent.
    private let picture: () -> CVPixelBuffer?
    /// Asks the user, on the main queue, and returns their answer.
    private let askConsent: (CVPixelBuffer) -> Bool

    private var question: NSTextField!
    private var send: NSButton!
    private var answer: NSTextView!
    private var busy = false
    private(set) var history: [(asked: String, answered: String)] = []

    var view: NSView!

    init(speaker: Speaker, board: Board, kind: String, label: String,
         picture: @escaping () -> CVPixelBuffer?,
         askConsent: @escaping (CVPixelBuffer) -> Bool) {
        self.speaker = speaker
        self.board = board
        self.kind = kind
        self.label = label
        self.picture = picture
        self.askConsent = askConsent
        super.init()
    }

    func build(width: CGFloat) -> NSView {
        let box = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 190))

        let heading = NSTextField(labelWithString: label)
        heading.frame = NSRect(x: 0, y: 160, width: width, height: 20)
        box.addSubview(heading)

        question = NSTextField(frame: NSRect(x: 0, y: 132, width: width - 90, height: 24))
        // Named for what the user needs, not for the heading above it. The
        // Windows copy has to match that heading because MSAA hands a screen
        // reader the preceding static text whatever the app says; on AppKit
        // the label is whatever we set.
        question.setAccessibilityLabel(label)
        // Return asks. A question box you have to Tab out of to send is a
        // question box nobody uses twice.
        question.target = self
        question.action = #selector(ask)
        box.addSubview(question)

        send = NSButton(title: "Ask", target: self, action: #selector(ask))
        send.frame = NSRect(x: width - 80, y: 128, width: 80, height: 30)
        send.setAccessibilityLabel("Ask")
        box.addSubview(send)

        let (scroll, view) = readOnlyText("Nothing asked yet.", label: "The answer",
                                          width: width, height: 120)
        scroll.frame = NSRect(x: 0, y: 0, width: width, height: 120)
        answer = view
        box.addSubview(scroll)

        self.view = box
        return box
    }

    /// Add what another part of the window found out, so a follow up knows it.
    func remember(asked: String, answered: String) {
        history.append((asked, answered))
    }

    @objc func ask() {
        if busy { return }
        let asked = question.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if asked.isEmpty {
            speaker.announce("Type a question first.")
            question.window?.makeFirstResponder(question)
            return
        }
        let key = Secrets.fetch(station: board.visionProvider, prefix: Secrets.visionPrefix)
        if key.isEmpty {
            show("No key has been set up yet. Open Preferences, AI Provider, and put one in.")
            speaker.announce("No key has been set up yet. Open Preferences, AI Provider, "
                           + "and put one in.")
            return
        }
        guard let shot = picture() else {
            show("There is no picture to ask about yet.")
            speaker.announce("There is no picture to ask about yet.")
            return
        }
        // Consent is asked HERE, on the main queue, before anything leaves.
        // The Windows copy asks in the Check the shot button and NOT in this
        // box, so a question about a screen sends the whole desktop with
        // nothing asked at all.
        var ticket: ShotCheck.Ticket?
        if ShotCheck.needsConsent(kind) {
            guard askConsent(shot),
                  let made = ShotCheck.consent(for: shot, kind: kind, answered: true) else {
                show("Nothing was sent.")
                speaker.announce("Nothing was sent.")
                return
            }
            ticket = made
        }

        busy = true
        send.isEnabled = false
        show("Asking...")
        speaker.announce("Asking.")
        let provider = board.visionProvider
        let model = board.visionModel
        let past = history
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let got = ShotCheck.converse(shot, question: asked, history: past,
                                         kind: self?.kind ?? "camera",
                                         provider: provider, key: key, model: model,
                                         consent: ticket)
            DispatchQueue.main.async {
                guard let self else { return }
                self.busy = false
                self.send.isEnabled = true
                self.show(got.text)
                if got.ok {
                    self.history.append((asked, got.text))
                    self.question.stringValue = ""
                }
                self.question.window?.makeFirstResponder(self.question)
                self.speaker.announceAnswer(AskPanel.firstLine(got.text))
            }
        }
    }

    /// The first line, which is the one that gets heard while somebody is
    /// still reaching for a key. The rest is there to be read.
    static func firstLine(_ text: String) -> String {
        text.split(separator: "\n").first.map(String.init) ?? text
    }

    private func show(_ text: String) {
        answer.string = text
        answer.setSelectedRange(NSRange(location: 0, length: 0))
        answer.scrollRangeToVisible(NSRange(location: 0, length: 0))
    }
}

// ----------------------------------------------------------- check my shot ---

/// Ask something that can see what the shot looks like. Option+Shift+D.
final class ShotCheckPanel: NSObject {

    private let board: Board
    private let speaker: Speaker
    private let window: NSWindow?
    /// Builds the picture that is going out, or would be. Never on the main
    /// queue: opening a camera is about six tenths of a second.
    private let grab: () -> CVPixelBuffer?
    private let kind: String

    private var looks: NSTextView!
    private var ask: AskPanel!
    private var goButton: NSButton?
    private var busy = false
    private var lookedAt: CVPixelBuffer?
    private static var toldAboutTabbing = false

    init(board: Board, speaker: Speaker, window: NSWindow?, kind: String,
         grab: @escaping () -> CVPixelBuffer?) {
        self.board = board
        self.speaker = speaker
        self.window = window
        self.kind = kind
        self.grab = grab
        super.init()
    }

    func run(over parent: NSWindow?) {
        let who = ShotCheck.providerNames[board.visionProvider] ?? board.visionProvider
        let alert = NSAlert()
        alert.messageText = "Check my shot"
        alert.informativeText = ShotCheck.needsConsent(kind)
            ? "This describes the picture going out, which right now includes your "
              + "screen. \(who) is asked."
            : "This describes the picture going out, camera and anything on top of "
              + "it. \(who) is asked."
        alert.addButton(withTitle: "Check the shot")
        alert.addButton(withTitle: "Close")

        let width: CGFloat = 620
        let box = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 400))
        let (scroll, view) = readOnlyText(
            "Nothing has been checked yet. Choose Check the shot.",
            label: "What it looks like", width: width, height: 190)
        scroll.frame = NSRect(x: 0, y: 200, width: width, height: 190)
        looks = view
        box.addSubview(scroll)

        ask = AskPanel(speaker: speaker, board: board, kind: kind,
                       label: "Ask a question about this",
                       // A follow up asks about the picture that was DESCRIBED,
                       // not a fresh one, or "is the plant still there" is
                       // answered about a frame taken while the presenter was
                       // moving.
                       picture: { [weak self] in self?.lookedAt ?? self?.grab() },
                       askConsent: { [weak self] _ in self?.consent() ?? false })
        let asking = ask.build(width: width)
        asking.frame = NSRect(x: 0, y: 0, width: width, height: 190)
        box.addSubview(asking)

        alert.accessoryView = box
        alert.window.initialFirstResponder = looks
        goButton = alert.buttons.first
        goButton?.setAccessibilityLabel("Check the shot")
        alert.buttons.last?.setAccessibilityLabel("Close")

        while true {
            let answer = PanelKeys.run(alert)
            guard answer == .alertFirstButtonReturn else { break }
            check()
            // The alert closes on any button, so it is run again. The state is
            // all in this object, so nothing is lost.
        }
    }

    /// **Asked every single time, and never remembered.**
    ///
    /// A yes given about one screen is not a yes about the next, and the
    /// person answering cannot look at the frame to see what is in it. That
    /// asymmetry, that the reason the feature exists is the reason its user
    /// cannot vet what it uploads, is the whole argument for asking again.
    private func consent() -> Bool {
        let alert = NSAlert()
        alert.messageText = "Send a picture of your screen?"
        alert.informativeText = ShotCheck.consentQuestion(
            kind: kind, provider: board.visionProvider)
        // The safe one first, and it takes Escape. Windows uses NO_DEFAULT so
        // both Enter and Escape decline; an AppKit button carries one key
        // equivalent, so Return is left bound to nothing. Neither of the two
        // keys somebody presses without reading can send their desktop.
        let no = alert.addButton(withTitle: "Do not send")
        no.keyEquivalent = "\u{1b}"
        let yes = alert.addButton(withTitle: "Send the picture")
        yes.keyEquivalent = ""
        return alert.runModal() == .alertFirstButtonReturn ? false : true
    }

    private func check() {
        if busy { return }
        let key = Secrets.fetch(station: board.visionProvider, prefix: Secrets.visionPrefix)
        if key.isEmpty {
            let said = "No key has been set up yet. Open Preferences, AI Provider, "
                     + "and put one in."
            show(said)
            speaker.announce(said)
            return
        }
        // **Asked here, on the main thread, before anything else happens.**
        // It used to be asked from the background queue with a main.sync,
        // which is a deadlock waiting for a main thread that is inside a modal
        // loop. It is also the wrong shape: the question is "may I send a
        // picture of your screen", and the honest moment to ask it is before
        // the screen is even grabbed.
        if ShotCheck.needsConsent(kind) && !consent() {
            show("Nothing was sent.")
            speaker.announce("Nothing was sent.")
            return
        }
        busy = true
        goButton?.isEnabled = false
        show("Looking at the picture. This usually takes a second or two.")
        // Windows only SHOWS this, so pressing the button produces silence for
        // a second or two. Say it.
        speaker.announce("Looking at the picture. This usually takes a second or two.")

        let provider = board.visionProvider
        let model = board.visionModel
        let kind = self.kind
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            // The GRAB is on this queue, not the main one. Opening a camera
            // blocks and a screen capture waits on the compositor, and the
            // main queue is carrying the keyboard.
            let shot = self.grab()
            // The ticket is minted from the bytes that are about to go, so
            // consent cannot drift onto a different picture between the
            // question and the send.
            let ticket = shot.flatMap {
                ShotCheck.needsConsent(kind)
                    ? ShotCheck.consent(for: $0, kind: kind, answered: true) : nil
            }
            let got = ShotCheck.describe(shot, kind: kind, provider: provider,
                                         key: key, model: model, consent: ticket)
            DispatchQueue.main.async {
                self.busy = false
                self.goButton?.isEnabled = true
                self.lookedAt = shot
                self.show(got.text)
                self.speaker.announceAnswer("Shot check: " + AskPanel.firstLine(got.text))
                if got.ok, !ShotCheckPanel.toldAboutTabbing {
                    ShotCheckPanel.toldAboutTabbing = true
                    self.speaker.announceHelp("Tab to What it looks like to read the rest.")
                }
                if got.ok {
                    self.ask.remember(asked: "What does this shot look like?",
                                      answered: got.text)
                }
            }
        }
    }

    private func show(_ text: String) {
        looks.string = text
        looks.setSelectedRange(NSRange(location: 0, length: 0))
        looks.scrollRangeToVisible(NSRange(location: 0, length: 0))
    }
}

// ---------------------------------------------------------------- colours ---

/// One colour, chosen by name and judged by number. Never by a swatch.
final class ColourPickerPanel: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private let title: String
    private let against: String
    private let againstName: String
    private let current: String
    /// True when the thing being picked is the background, in which case the
    /// score is what the WORDS will look like ON it.
    private let isBackground: Bool
    private var table: ActionTable!
    private var doing: NSTextField!
    private var alert: NSAlert!

    init(title: String, current: String, against: String, againstName: String,
         isBackground: Bool) {
        self.title = title
        self.current = current
        self.against = against
        self.againstName = againstName
        self.isBackground = isBackground
        super.init()
    }

    /// The pair, in the order contrast wants them: front on back.
    private func pair(_ name: String) -> (front: RGB, back: RGB) {
        isBackground ? (Colours.rgb(against), Colours.rgb(name))
                     : (Colours.rgb(name), Colours.rgb(against))
    }

    func run(over parent: NSWindow?) -> String? {
        alert = NSAlert()
        alert.messageText = title
        alert.informativeText = isBackground
            ? "Every colour says how it will read against your words, \(againstName)."
            : "Every colour says how it will read against the background, \(againstName)."
        alert.addButton(withTitle: "Use this one")
        alert.addButton(withTitle: "Cancel")

        let width: CGFloat = 620
        let box = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 330))
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 46, width: width, height: 280))
        table = ActionTable(frame: scroll.bounds)
        for (id, heading, w) in [("name", "Colour", 130),
                                 ("reads", "How it reads", 250),
                                 ("ratio", "Contrast", 100),
                                 ("video", "On video", 130)] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id))
            column.title = heading
            column.width = CGFloat(w)
            table.addTableColumn(column)
        }
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel("Colours")
        table.onChoose = { [weak self] in
            NSApp.stopModal(withCode: .alertFirstButtonReturn)
            _ = self
        }
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        box.addSubview(scroll)

        doing = NSTextField(wrappingLabelWithString: "")
        doing.frame = NSRect(x: 0, y: 0, width: width, height: 40)
        doing.setAccessibilityLabel("What this colour does")
        box.addSubview(doing)

        alert.accessoryView = box
        let start = Colours.names.firstIndex(of: current) ?? 0
        table.selectRowIndexes(IndexSet(integer: start), byExtendingSelection: false)
        table.scrollRowToVisible(start)
        alert.window.initialFirstResponder = table
        describe()

        let answer = PanelKeys.run(alert)
        guard answer == .alertFirstButtonReturn else { return nil }
        let row = max(0, table.selectedRow)
        return row < Colours.names.count ? Colours.names[row] : nil
    }

    private func describe() {
        let row = max(0, table.selectedRow)
        guard row < Colours.names.count else { return }
        let name = Colours.names[row]
        let p = pair(name)
        let (ratio, said) = Colours.verdict(front: p.front, back: p.back)
        var line = "\(name.capitalisedWords) on the \(isBackground ? "words" : "background"), "
                 + "\(againstName): \(said), \(Colours.oneDecimal(ratio)) to 1."
        let fringe = Colours.fringing(Colours.rgb(name))
        if fringe.frays {
            line += " Strong enough that its edges will fray a little once the video is "
                  + "encoded, which suits a rule or a heading better than small print."
        }
        doing.stringValue = line
    }

    func numberOfRows(in tableView: NSTableView) -> Int { Colours.names.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard row < Colours.names.count, let column = tableColumn else { return nil }
        let name = Colours.names[row]
        let p = pair(name)
        let (ratio, said) = Colours.verdict(front: p.front, back: p.back)
        let text: String
        switch column.identifier.rawValue {
        case "name": text = name
        case "reads": text = said
        case "ratio": text = "\(Colours.oneDecimal(ratio)) to 1"
        default:
            // A SECOND question, and contrast cannot answer it. A strongly
            // coloured letter keeps its shape and loses its edges however good
            // its ratio, and no bitrate mends it.
            text = Colours.fringing(Colours.rgb(name)).frays ? "frays a little" : "clean"
        }
        let cell = NSTextField(labelWithString: text)
        cell.setAccessibilityLabel(text)
        return cell
    }

    func tableViewSelectionDidChange(_ notification: Notification) { describe() }
}

/// The brand: what sits underneath, what the words are, and the accent.
final class ColoursPanel: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private let board: Board
    private let speaker: Speaker
    private let window: NSWindow?
    /// Rebuilds whatever is going out, so a change is seen at once.
    private let apply: () -> Void
    /// A rendered sample of the brand, for the one question arithmetic cannot
    /// answer.
    private let sample: () -> CVPixelBuffer?

    private var table: ActionTable!
    private var doing: NSTextField!
    private var lookText: NSTextView!
    private var ask: AskPanel!
    private var opinionButton: NSButton!
    private var busy = false

    private static let rows = ["look", "background", "text", "accent"]

    init(board: Board, speaker: Speaker, window: NSWindow?,
         sample: @escaping () -> CVPixelBuffer?, apply: @escaping () -> Void) {
        self.board = board
        self.speaker = speaker
        self.window = window
        self.sample = sample
        self.apply = apply
        super.init()
    }

    private var schemeName: String? {
        for s in Colours.schemes where s.background == board.colourBackground
            && s.text == board.colourText && s.accent == board.colourAccent {
            return s.name
        }
        return nil
    }

    func run(over parent: NSWindow?) {
        let alert = NSAlert()
        alert.messageText = "Colours"
        alert.informativeText = "Up and down read them. Return changes one. "
                              + "Every choice says how it will read."
        alert.addButton(withTitle: "Close")

        let width: CGFloat = 660
        let box = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 560))

        let scroll = NSScrollView(frame: NSRect(x: 0, y: 440, width: width, height: 110))
        table = ActionTable(frame: scroll.bounds)
        for (id, heading, w) in [("what", "What", 230), ("now", "Now", 140),
                                 ("reads", "How it reads", 280)] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id))
            column.title = heading
            column.width = CGFloat(w)
            table.addTableColumn(column)
        }
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel("Brand")
        table.onChoose = { [weak self] in self?.change() }
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        box.addSubview(scroll)

        doing = NSTextField(wrappingLabelWithString: "")
        doing.frame = NSRect(x: 0, y: 406, width: width, height: 30)
        doing.setAccessibilityLabel("What this row is")
        box.addSubview(doing)

        // A text view rather than a label, and that is the point of it. The
        // line above changes with the selected row, which is right for "what
        // is this row" and wrong for "what have I ended up with". This one
        // always says the whole thing and can be arrowed a line at a time.
        let (lookScroll, look) = readOnlyText("", label: "This look",
                                              width: width, height: 90)
        lookScroll.frame = NSRect(x: 0, y: 310, width: width, height: 90)
        lookText = look
        box.addSubview(lookScroll)

        opinionButton = NSButton(title: "What does this look like to a sighted viewer?",
                                 target: self, action: #selector(opinion))
        opinionButton.frame = NSRect(x: 0, y: 274, width: 400, height: 30)
        opinionButton.setAccessibilityLabel("What does this look like to a sighted viewer")
        box.addSubview(opinionButton)

        ask = AskPanel(speaker: speaker, board: board, kind: "branding",
                       label: "Ask about these colours",
                       picture: { [weak self] in self?.sample() },
                       askConsent: { _ in true })
        let asking = ask.build(width: width)
        asking.frame = NSRect(x: 0, y: 74, width: width, height: 190)
        box.addSubview(asking)

        let change = NSButton(title: "Change...", target: self, action: #selector(changePressed))
        change.frame = NSRect(x: 0, y: 34, width: 130, height: 30)
        change.setAccessibilityLabel("Change")
        box.addSubview(change)

        let back = NSButton(title: "Back to default", target: self,
                            action: #selector(backToDefault))
        back.frame = NSRect(x: 140, y: 34, width: 170, height: 30)
        back.setAccessibilityLabel("Back to default")
        box.addSubview(back)

        alert.accessoryView = box
        table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        alert.window.initialFirstResponder = table
        refresh()
        _ = PanelKeys.run(alert)
    }

    @objc private func changePressed() { change() }

    private func change() {
        let row = max(0, table.selectedRow)
        guard row < ColoursPanel.rows.count else { return }
        if ColoursPanel.rows[row] == "look" {
            let picker = ChoicePanel(title: "Ready-made look", message: "Which look?",
                                     options: Colours.schemeNames, okTitle: "Use this")
            guard let index = picker.run(over: window),
                  index < Colours.schemes.count else { return }
            let chosen = Colours.schemes[index]
            board.colourBackground = chosen.background
            board.colourText = chosen.text
            board.colourAccent = chosen.accent
            board.dirty = true
            apply()
            refresh()
            speaker.announceState(Colours.describeScheme(chosen.name))
            return
        }
        let which = ColoursPanel.rows[row]
        let isBackground = which == "background"
        let title = which == "background" ? "Background"
                  : (which == "text" ? "Words" : "Accent")
        let current = which == "background" ? board.colourBackground
                    : (which == "text" ? board.colourText : board.colourAccent)
        let against = isBackground ? board.colourText : board.colourBackground
        let picker = ColourPickerPanel(title: title, current: current,
                                       against: against, againstName: against,
                                       isBackground: isBackground)
        guard let picked = picker.run(over: window) else { return }
        switch which {
        case "background": board.colourBackground = picked
        case "text": board.colourText = picked
        default: board.colourAccent = picked
        }
        board.dirty = true
        apply()
        refresh()
        speaker.announceState("\(title) is \(picked) now. "
                            + Colours.describePair(front: isBackground ? board.colourText : picked,
                                                   back: isBackground ? picked : board.colourBackground))
    }

    @objc private func backToDefault() {
        board.colourBackground = C.colourBackground
        board.colourText = C.colourText
        board.colourAccent = C.colourAccent
        board.dirty = true
        apply()
        refresh()
        speaker.announceState("Back to the default look. "
                            + Colours.describePair(front: C.colourText,
                                                   back: C.colourBackground))
    }

    @objc private func opinion() {
        if busy { return }
        let key = Secrets.fetch(station: board.visionProvider, prefix: Secrets.visionPrefix)
        if key.isEmpty {
            let said = "No key has been set up yet. Open Preferences, AI Provider, "
                     + "and put one in."
            speaker.announce(said)
            return
        }
        busy = true
        opinionButton.isEnabled = false
        speaker.announce("Looking at these colours.")
        let provider = board.visionProvider
        let model = board.visionModel
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let shot = self.sample()
            let got = ShotCheck.describe(shot, kind: "branding", provider: provider,
                                         key: key, model: model)
            DispatchQueue.main.async {
                self.busy = false
                self.opinionButton.isEnabled = true
                self.speaker.announceAnswer(AskPanel.firstLine(got.text))
                if got.ok {
                    self.ask.remember(asked: "What do these colours look like?",
                                      answered: got.text)
                }
            }
        }
    }

    private func refresh() {
        let row = max(0, table.selectedRow)
        table.reloadData()
        table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
        table.window?.makeFirstResponder(table)
        describe()
        var lines: [String] = []
        if let name = schemeName {
            lines.append(Colours.describeScheme(name))
        } else {
            lines.append("Your own mix, not one of the ready-made looks.")
        }
        lines.append("Background \(board.colourBackground), words \(board.colourText), "
                   + "accent \(board.colourAccent).")
        lines.append("Words on the background: "
                   + Colours.describePair(front: board.colourText,
                                          back: board.colourBackground))
        lines.append("Accent on the background: "
                   + Colours.describePair(front: board.colourAccent,
                                          back: board.colourBackground))
        lookText.string = lines.joined(separator: "\n")
        lookText.setSelectedRange(NSRange(location: 0, length: 0))
    }

    private func describe() {
        let row = max(0, table.selectedRow)
        guard row < ColoursPanel.rows.count else { return }
        switch ColoursPanel.rows[row] {
        case "look":
            doing.stringValue = "Ten looks that were each checked against the numbers "
                              + "rather than picked by eye."
        case "background":
            doing.stringValue = "What everything sits on: the card, the panels behind "
                              + "the words, and the bars either side of a camera."
        case "text":
            doing.stringValue = "The words on the card and in the four places."
        default:
            doing.stringValue = "The rule under your station name and the line round "
                              + "the camera inset."
        }
    }

    func numberOfRows(in tableView: NSTableView) -> Int { ColoursPanel.rows.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard row < ColoursPanel.rows.count, let column = tableColumn else { return nil }
        let which = ColoursPanel.rows[row]
        var what = "", now = "", reads = ""
        switch which {
        case "look":
            what = "Ready-made look"
            now = schemeName ?? "your own"
        case "background":
            what = "Background, under everything"
            now = board.colourBackground
            // Scored by what the WORDS look like ON it, which is the only
            // question anybody actually has about a background.
            reads = "words " + Colours.verdict(front: Colours.rgb(board.colourText),
                                               back: Colours.rgb(now)).said
        case "text":
            what = "Words"
            now = board.colourText
            let v = Colours.verdict(front: Colours.rgb(now),
                                    back: Colours.rgb(board.colourBackground))
            reads = "\(v.said), \(Colours.oneDecimal(v.ratio)) to 1"
        default:
            what = "Accent, the rule and the edges"
            now = board.colourAccent
            let v = Colours.verdict(front: Colours.rgb(now),
                                    back: Colours.rgb(board.colourBackground))
            reads = "\(v.said), \(Colours.oneDecimal(v.ratio)) to 1"
        }
        let text: String
        switch column.identifier.rawValue {
        case "what": text = what
        case "now": text = now
        default: text = reads
        }
        let cell = NSTextField(labelWithString: text)
        cell.setAccessibilityLabel(text)
        return cell
    }

    func tableViewSelectionDidChange(_ notification: Notification) { describe() }
}

// --------------------------------------------------------------- going live ---

/// What Command B is about to do, and what is wrong with it.
///
/// Command B then Return is still the whole gesture. The muscle memory costs
/// one extra keypress and the presenter hears the destination, the format, the
/// picture and whether their own microphone is on the air on the way past.
enum GoLiveAnswer {
    case goLive
    case stayOff
    /// Open the settings page named, then ask again.
    case putItRight(String)
}

final class GoLivePanel: NSObject {

    private let report: Preflight
    private let board: Board

    init(report: Preflight, board: Board) {
        self.report = report
        self.board = board
        super.init()
    }

    func run(over parent: NSWindow?) -> GoLiveAnswer {
        let alert = NSAlert()
        alert.messageText = "Go live"
        alert.informativeText = report.blocked
            ? "Something below has to be put right first. Return opens the page that fixes it."
            : "Return goes live. Escape stays off air."

        let live = alert.addButton(withTitle: "Go live")
        live.setAccessibilityLabel("Go live")
        let stay = alert.addButton(withTitle: "Stay off air")
        stay.setAccessibilityLabel("Stay off air")
        stay.keyEquivalent = "\u{1b}"

        let fix = report.notes.first(where: { !$0.fix.isEmpty })?.fix
        var fixButton: NSButton?
        if let fix, !fix.isEmpty {
            let button = alert.addButton(withTitle: "Put it right...")
            button.setAccessibilityLabel("Put it right")
            fixButton = button
        }
        if report.blocked {
            // Do not leave Return bound to a dead button.
            live.isEnabled = false
            live.keyEquivalent = ""
            fixButton?.keyEquivalent = "\r"
        }

        let width: CGFloat = 620
        let hasNotes = !report.notes.isEmpty
        let height: CGFloat = hasNotes ? 320 : 190
        let box = NSView(frame: NSRect(x: 0, y: 0, width: width, height: height))

        let summary = report.lines.map { "\($0.label): \($0.value)" }.joined(separator: "\n")
        let (goingScroll, going) = readOnlyText(summary, label: "What will go out",
                                                width: width, height: 130)
        goingScroll.frame = NSRect(x: 0, y: height - 130, width: width, height: 130)
        box.addSubview(goingScroll)

        if hasNotes {
            // Stops first, then warnings. Reading two warnings before the one
            // sentence that says why Go live is unavailable is the wrong way
            // round, and it is the first line somebody hears.
            let ordered = report.stops + report.warnings
            let text = ordered.map {
                ($0.level == .stop ? "Stop: " : "Warning: ") + $0.text
            }.joined(separator: "\n")
            let (noteScroll, _) = readOnlyText(text, label: "Worth knowing first",
                                               width: width, height: 120)
            noteScroll.frame = NSRect(x: 0, y: 40, width: width, height: 120)
            box.addSubview(noteScroll)
        }

        let never = NSButton(checkboxWithTitle: "Do not ask again, just go live",
                             target: nil, action: nil)
        never.frame = NSRect(x: 0, y: 6, width: width, height: 24)
        never.setAccessibilityLabel("Do not ask again, just go live")
        never.toolTip = "Command B goes straight on the air. Command Shift B still says "
                      + "what is going out, and you can turn this back on in Preferences."
        box.addSubview(never)

        alert.accessoryView = box
        alert.window.initialFirstResponder = going
        going.setSelectedRange(NSRange(location: 0, length: 0))

        let answer = PanelKeys.run(alert)
        // Read before the window goes, because the caller looks afterwards.
        if never.state == .on {
            board.askBeforeLive = false
            board.dirty = true
        }
        switch answer {
        case .alertFirstButtonReturn: return report.blocked ? .stayOff : .goLive
        case .alertThirdButtonReturn: return .putItRight(fix ?? C.fixAudio)
        default: return .stayOff
        }
    }
}

// ---------------------------------------------------- setting up streaming ---

/// Step by step for each platform, without leaving the app.
///
/// A read only text block, not a web view and not a list. A screen reader user
/// can arrow through it line by line, read a word at a time and copy a piece
/// out, which is exactly what somebody following instructions needs.
final class StreamHelpPanel: NSObject {

    private let speaker: Speaker
    private var text: NSTextView!
    private var platforms: [String] = []

    init(speaker: Speaker) {
        self.speaker = speaker
        super.init()
    }

    func run(over parent: NSWindow?) {
        platforms = StreamHelp.order
        let alert = NSAlert()
        alert.messageText = "Setting up streaming"
        alert.informativeText = "Step by step for whichever platform you pick, "
                              + "without leaving the app."
        alert.addButton(withTitle: "Close")

        let width: CGFloat = 660
        let box = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 460))

        let picker = NSPopUpButton(frame: NSRect(x: 0, y: 424, width: 340, height: 26))
        picker.addItems(withTitles: platforms.map { StreamServers.serverLabel($0) }
                        + ["All of them, and what to do when it goes wrong"])
        picker.setAccessibilityLabel("Which platform")
        picker.target = self
        picker.action = #selector(changed(_:))
        box.addSubview(picker)

        let (scroll, view) = readOnlyText(StreamHelp.asText(platforms[0]),
                                          label: "Instructions",
                                          width: width, height: 370)
        scroll.frame = NSRect(x: 0, y: 44, width: width, height: 370)
        text = view
        box.addSubview(scroll)

        // An accessory button, not an alert button: an alert button closes the
        // alert, and opening the manual should leave the window where it is so
        // somebody can come back to the steps.
        let manual = NSButton(title: "Open the full manual", target: self,
                              action: #selector(openManual))
        manual.frame = NSRect(x: 0, y: 6, width: 220, height: 30)
        manual.setAccessibilityLabel("Open the full manual")
        box.addSubview(manual)

        alert.accessoryView = box
        alert.window.initialFirstResponder = text
        _ = PanelKeys.run(alert)
    }

    @objc private func changed(_ sender: NSPopUpButton) {
        let index = sender.indexOfSelectedItem
        let name: String
        if index < platforms.count {
            text.string = StreamHelp.asText(platforms[index])
            name = StreamServers.serverLabel(platforms[index])
        } else {
            text.string = StreamHelp.everything()
            name = "All"
        }
        text.setSelectedRange(NSRange(location: 0, length: 0))
        text.scrollRangeToVisible(NSRange(location: 0, length: 0))
        // Without this the text view changes in silence and there is nothing
        // to say the window did anything. announceHelp, because it is a hint
        // somebody has read before.
        speaker.announceHelp("\(name) instructions. Tab to Instructions to read them.")
    }

    @objc private func openManual() {
        if let url = URL(string: C.userGuideURL) { NSWorkspace.shared.open(url) }
    }
}
