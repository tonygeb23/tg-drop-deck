// The windows behind the Help menu, and one list picker the rest of the app
// borrows.
//
// Every one of them puts its text in a read only text view rather than in the
// alert's own message, and for the same reason the Windows copy moved off
// wx.MessageBox: a message is read once as the window opens and there is no way
// back over it. Release notes and a paragraph about donating are things a
// person wants to arrow through at their own pace, and "what version am I on
// again" is a fair question to ask twice.
//
// Tab moves between controls in every text view here. A text view eats Tab by
// default, and a window a keyboard user cannot leave is a trap.

import AppKit

/// Tab and Shift Tab leave the text view; nothing else changes.
final class TabbingTextView: NSTextView {
    override func keyDown(with event: NSEvent) {
        if event.keyCode == 48 {                          // Tab
            if event.modifierFlags.contains(.shift) { window?.selectPreviousKeyView(nil) }
            else { window?.selectNextKeyView(nil) }
            return
        }
        // **A read only text view SWALLOWS Return**, and that is measured
        // rather than assumed: a real Return delivered to a panel whose focus
        // is in one of these left the window standing and never reached the
        // default button. `insertNewline` on a view that cannot be edited does
        // nothing at all, and the event is used up by then.
        //
        // That matters because every panel in this app that has something to
        // say puts focus on the SAYING rather than on a button, which is what
        // makes it reviewable. So Return, the key somebody presses when they
        // have finished reading, did nothing: on the update panel it did not
        // update, and it would not have gone live or checked a shot either.
        // Shipped that way in 3.3.2 and found on 8 September 2026.
        if event.keyCode == 36, !isEditable,
           event.modifierFlags.intersection([.command, .option, .control, .shift]).isEmpty,
           let button = window?.defaultButtonCell {
            button.performClick(nil)
            return
        }
        super.keyDown(with: event)
    }
}

/// A read only, focusable, scrolling block of text with a real name.
func readOnlyText(_ text: String, label: String, width: CGFloat, height: CGFloat) -> (NSScrollView, NSTextView) {
    let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: width, height: height))
    let view = TabbingTextView(frame: scroll.bounds)
    view.isEditable = false
    view.isSelectable = true
    view.string = text
    view.font = NSFont.systemFont(ofSize: NSFont.systemFontSize)
    view.textContainerInset = NSSize(width: 6, height: 6)
    view.setAccessibilityLabel(label)
    view.autoresizingMask = [.width]
    scroll.documentView = view
    scroll.hasVerticalScroller = true
    scroll.borderType = .bezelBorder
    return (scroll, view)
}

private func smallLabel(_ text: String) -> NSTextField {
    let f = NSTextField(labelWithString: text)
    f.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
    f.textColor = .secondaryLabelColor
    return f
}

// --------------------------------------------------------------- a choice ---

/// Pick one thing from a list. Used for putting a removed slot back, where a
/// pop up would hide the choices and a list can be arrowed through.
final class ChoicePanel: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private let title: String
    private let message: String
    private let options: [String]
    private let okTitle: String
    private var table: NSTableView!
    private var alert: NSAlert!

    init(title: String, message: String, options: [String], okTitle: String = "OK") {
        self.title = title
        self.message = message
        self.options = options
        self.okTitle = okTitle
    }

    func run(over parent: NSWindow?) -> Int? {
        alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: okTitle)
        alert.addButton(withTitle: "Cancel")

        let height = min(300, max(96, CGFloat(options.count) * 24 + 8))
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 460, height: height))
        table = NSTableView(frame: scroll.bounds)
        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("choice"))
        column.width = 440
        table.addTableColumn(column)
        table.headerView = nil
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel(title)
        table.target = self
        table.doubleAction = #selector(chosenByDoubleClick)
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        if !options.isEmpty {
            table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        }

        alert.accessoryView = scroll
        alert.window.initialFirstResponder = table
        guard alert.runModal() == .alertFirstButtonReturn,
              table.selectedRow >= 0, table.selectedRow < options.count else { return nil }
        return table.selectedRow
    }

    @objc private func chosenByDoubleClick() {
        guard table.clickedRow >= 0 else { return }
        table.selectRowIndexes(IndexSet(integer: table.clickedRow), byExtendingSelection: false)
        alert.buttons.first?.performClick(nil)
    }

    func numberOfRows(in tableView: NSTableView) -> Int { options.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        let f = NSTextField(labelWithString: options[row])
        f.setAccessibilityLabel(options[row])
        return f
    }
}

// --------------------------------------------------------------- feedback ---

/// Say what happened, pick what kind of thing it is, send it.
///
/// Two controls and a read back. The read back is the part that matters: it
/// shows exactly what will leave the machine, because a window that says
/// "diagnostics are attached" and does not say which is asking to be trusted
/// rather than earning it.
final class FeedbackPanel: NSObject, NSTextViewDelegate {

    private let extra: [String: Any]
    private var kind: NSPopUpButton!
    private var message: NSTextView!
    private var preview: NSTextView!
    private var alert: NSAlert!

    init(diagnostics: [String: Any]) { extra = diagnostics }

    var typeKey: String {
        let i = kind.indexOfSelectedItem
        return Feedback.types[max(0, min(Feedback.types.count - 1, i))].key
    }

    var text: String { message.string.trimmingCharacters(in: .whitespacesAndNewlines) }

    func run(over parent: NSWindow?) -> (type: String, message: String)? {
        alert = NSAlert()
        alert.messageText = "Submit feedback"
        alert.informativeText = "Tell us what happened, or what would make this better. "
                              + "It goes straight to the person who wrote the app."
        alert.addButton(withTitle: "Submit")
        alert.addButton(withTitle: "Cancel")

        let width: CGFloat = 620
        let box = NSStackView()
        box.orientation = .vertical
        box.alignment = .leading
        box.spacing = 4
        box.frame = NSRect(x: 0, y: 0, width: width, height: 470)

        kind = NSPopUpButton()
        for t in Feedback.types { kind.addItem(withTitle: t.label) }
        kind.setAccessibilityLabel("What kind of feedback")
        kind.target = self
        kind.action = #selector(kindChanged)
        box.addArrangedSubview(smallLabel("What kind of feedback"))
        box.addArrangedSubview(kind)
        kind.widthAnchor.constraint(equalToConstant: width).isActive = true

        let messageScroll = NSScrollView()
        message = TabbingTextView(frame: NSRect(x: 0, y: 0, width: width, height: 140))
        message.isRichText = false
        message.font = NSFont.systemFont(ofSize: NSFont.systemFontSize)
        message.textContainerInset = NSSize(width: 6, height: 6)
        message.setAccessibilityLabel("Your message")
        message.delegate = self
        message.autoresizingMask = [.width]
        messageScroll.documentView = message
        messageScroll.hasVerticalScroller = true
        messageScroll.borderType = .bezelBorder
        messageScroll.heightAnchor.constraint(equalToConstant: 140).isActive = true
        messageScroll.widthAnchor.constraint(equalToConstant: width).isActive = true
        box.addArrangedSubview(smallLabel("Your message"))
        box.addArrangedSubview(messageScroll)

        let (previewScroll, previewView) = readOnlyText("", label: "What will be sent",
                                                        width: width, height: 200)
        preview = previewView
        preview.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
        previewScroll.heightAnchor.constraint(equalToConstant: 200).isActive = true
        previewScroll.widthAnchor.constraint(equalToConstant: width).isActive = true
        box.addArrangedSubview(smallLabel("What will be sent"))
        box.addArrangedSubview(previewScroll)

        alert.accessoryView = box
        alert.window.initialFirstResponder = kind
        refresh()

        guard alert.runModal() == .alertFirstButtonReturn, !text.isEmpty else { return nil }
        return (typeKey, text)
    }

    @objc private func kindChanged() { refresh() }

    func textDidChange(_ notification: Notification) { refresh() }

    /// Keep the read back honest as the message is typed. Nothing to send is
    /// not a thing to send: an empty report would sit in the queue for ever
    /// being retried, so Submit stays off until there are words.
    private func refresh() {
        let report = Feedback.build(type: typeKey, message: text, extra: extra)
        preview.string = Feedback.readable(report)
        alert.buttons.first?.isEnabled = !text.isEmpty
    }
}

// ---------------------------------------------------------------- donating ---

/// The occasional word about donating. Never more than a word.
final class DonatePanel {

    static let message = """
        TG Drop Deck is free, and it will carry on being free.

        Donations go into development, server costs, and new products for TG Studios \
        users. If you enjoy using Drop Deck and you would like to be part of the team, \
        please consider a small contribution of whatever size suits you.

        If you would like it to be, your name goes on a public contributors list. And if \
        you would rather not, you are a rockstar either way.

        This asks about once a week at most, and never in your first week. Help, Donate, \
        is here whenever you want it.
        """

    func run(over parent: NSWindow?) -> (donate: Bool, never: Bool) {
        let alert = NSAlert()
        alert.messageText = "Drop Deck is free"
        alert.addButton(withTitle: "Donate")
        alert.addButton(withTitle: "No thank you")

        let box = NSStackView()
        box.orientation = .vertical
        box.alignment = .leading
        box.spacing = 8
        box.frame = NSRect(x: 0, y: 0, width: 520, height: 250)
        let (scroll, text) = readOnlyText(DonatePanel.message, label: "About donating",
                                          width: 520, height: 200)
        scroll.heightAnchor.constraint(equalToConstant: 200).isActive = true
        scroll.widthAnchor.constraint(equalToConstant: 520).isActive = true
        box.addArrangedSubview(scroll)
        let never = NSButton(checkboxWithTitle: "Do not ask me about this again", target: nil, action: nil)
        never.toolTip = "Help, Donate, still opens the page whenever you want it."
        box.addArrangedSubview(never)

        alert.accessoryView = box
        alert.window.initialFirstResponder = text
        let answer = alert.runModal()
        return (answer == .alertFirstButtonReturn, never.state == .on)
    }
}

// ----------------------------------------------------------------- updates ---

enum UpdateAnswer { case update, later, closed }

/// One dialog, three things it can say: up to date, update, or a problem.
/// Identical in wording to the Windows one, which is read aloud out of context:
/// "Hey, TG Drop Deck is up to date" tells you which of several open apps just
/// answered you.
enum UpdatePanel {

    static func ask(over parent: NSWindow?, product: String, current: String,
                    newVersion: String? = nil, notes: String = "", problem: String = "") -> UpdateAnswer {
        let message: String
        if !problem.isEmpty {
            message = "\(product) could not check for updates.\n\n\(problem)"
        } else if let newVersion {
            var m = "\(product) has an update.\n\nVersion \(newVersion) is available. "
                  + "You have version \(current).\n\nChoose the Update button to download and install it."
            let trimmed = notes.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { m += "\n\nWhat is new:\n\n" + trimmed }
            message = m
        } else {
            message = "Hey, \(product) is up to date.\n\nYou have version \(current), which is the newest one."
        }

        let alert = NSAlert()
        alert.messageText = "\(product) updates"
        if newVersion != nil && problem.isEmpty {
            alert.addButton(withTitle: "Update")
            alert.addButton(withTitle: "Not now")
        } else {
            alert.addButton(withTitle: "OK")
        }
        let (scroll, text) = readOnlyText(message, label: "Message", width: 520, height: 220)
        alert.accessoryView = scroll
        // Focus the message, not a button: it is what the reader should hear
        // first, and starting there is what makes it reviewable at all.
        alert.window.initialFirstResponder = text
        let answer = alert.runModal()
        guard newVersion != nil && problem.isEmpty else { return .closed }
        return answer == .alertFirstButtonReturn ? .update : .later
    }
}
