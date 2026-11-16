// How much the app says out loud, and where the words land when it does not.
//
// A screen reader is already reading every control. Speech from the app is only
// for what the screen reader cannot know, and how much of it is the user's
// choice. Five channels, and deciding which one a line belongs on is the whole
// job.
//
// On Windows this went through accessible_output2 to NVDA. On macOS the same
// job is done by posting an announcement to VoiceOver through NSAccessibility,
// which needs no library and no bridge object.
//
// ALL FIVE CHANNELS WRITE THE STATUS LINE AT EVERY LEVEL, so nothing this app
// has to say is ever only spoken. At "none" the information is still on screen
// and still reachable, it just does not interrupt.
//
// WHERE THE ANNOUNCEMENT IS POSTED IS NOT A DETAIL. Until 3.3.0 this posted to
// the window's content view, and VoiceOver said nothing at all: an announcement
// request is only honoured on an NSWindow or on NSApp, so every spoken line in
// the app was silently landing in the status bar and nowhere else. Command D
// changed the ducking and said nothing; Command Shift B answered into a box at
// the bottom of the window. Post to the KEY window, which is also what puts the
// line inside whichever alert is up rather than behind it.

import AppKit

final class Speaker {

    /// Where a line goes when it is not spoken. Set by the window.
    var status: ((String) -> Void)?

    var level: String = C.defaultSpeechLevel
    /// The separate switch for playback names, which is a board setting.
    var playbackEnabled = true

    /// The window the app belongs to, used only when nothing is key.
    private weak var home: NSWindow?

    /// The last thing said and when, so a line repeated inside one run loop
    /// turn, which happens when a menu item and a key both reach the same
    /// handler, is not spoken over itself.
    private var lastSpoken = ""
    private var lastSpokenAt = Date.distantPast

    func attach(to view: NSView) { home = view.window }
    func attach(to window: NSWindow?) { home = window }

    // ------------------------------------------------------------ channels ---

    /// What you cannot otherwise know: a missing file, a key the system
    /// refused, a number you asked for. Silent only at "none".
    func announce(_ text: String, interrupt: Bool = true) {
        note(text)
        guard level != C.speechNone else { return }
        say(text, interrupt: interrupt)
    }

    /// A state you have just changed and cannot see: ducking, the microphone,
    /// the stream, the recorder, a source muted or soloed. Spoken at EVERY
    /// level, for the same reason as an answer. A switch you pressed that then
    /// says nothing is not quiet, it is a switch you have to go and look up.
    ///
    /// This is the channel that "none" is not allowed to silence, because
    /// "none" means stop narrating, not stop answering.
    func announceState(_ text: String) {
        note(text)
        say(text)
    }

    /// A confirmation of something you just did, or a hint you have read
    /// before. Silent below "all".
    func announceHelp(_ text: String, interrupt: Bool = true) {
        note(text)
        guard level == C.speechAll else { return }
        say(text, interrupt: interrupt)
    }

    /// The name of a sound you can hear anyway. Silent below "all", and off
    /// entirely when the user has turned playback names off.
    func announcePlayback(_ text: String) {
        note(text)
        guard level == C.speechAll, playbackEnabled else { return }
        say(text)
    }

    /// The answer to a question the user asked with a key. Spoken at EVERY
    /// level including "none", because a key whose only job is to answer and
    /// which then says nothing is broken, not quiet.
    func announceAnswer(_ text: String) {
        note(text)
        say(text)
    }

    /// Things the screen reader has already said for itself. Never spoken,
    /// always written down.
    func note(_ text: String) {
        guard !text.isEmpty else { return }
        if Thread.isMainThread { status?(text) }
        else { DispatchQueue.main.async { self.status?(text) } }
    }

    // --------------------------------------------------------------- saying ---

    /// Where VoiceOver will accept an announcement. The key window first, so a
    /// line spoken from inside a dialog belongs to that dialog; then the main
    /// window; then the application itself, which is the documented fallback.
    private var target: Any {
        if let key = NSApp.keyWindow { return key }
        if let modal = NSApp.modalWindow { return modal }
        if let home { return home }
        return NSApp as Any
    }

    /// Interrupting is the default: during a live show the thing you just did
    /// matters more than the thing you did a second ago.
    ///
    /// **A line nobody asked for waits its turn** (W383-15). A timer's line, a
    /// program closing or coming back, a send coming back, arrives at a moment
    /// nobody chose, perhaps half way through VoiceOver reading something the
    /// presenter is listening to; it is queued behind that rather than cutting
    /// it off. Windows passes `interrupt=False` for the same lines.
    static func priority(interrupt: Bool) -> NSAccessibilityPriorityLevel {
        interrupt ? .high : .medium
    }

    /// Told every line that is really spoken, and whether it interrupts. For
    /// the checks, which hold the call sites to queueing what nobody asked
    /// for (audit 2, finding 8).
    var spoken: ((String, Bool) -> Void)?

    /// Set only by `--check-accessibility`, which builds every window with
    /// nobody at the keyboard: what the windows would have said still reaches
    /// `status` and `spoken`, and nothing is posted to VoiceOver.
    static var muted = false

    // ------------------------------------------- after a menu or a box ---
    //
    // Siena chooses Start recording with VO+M, and the line it speaks was
    // never heard (October 2026). When a menu or a box closes, VoiceOver
    // reads wherever focus lands, at exactly the moment the command answers,
    // and whichever speaks second cuts the other off. Windows found the same
    // with NVDA and waits 400 ms after a menu closes, then queues the line
    // behind the screen reader rather than interrupting it (3.9.0,
    // `AFTER_MENU_*`). The Mac starts from Windows' numbers. **They have not
    // been measured against VoiceOver yet**; change them only after doing so.
    // A key equivalent does not track the menu, so a key pressed in the
    // middle of a show is still answered at once.

    /// When a menu, a box or a file panel last closed.
    private(set) static var interfaceClosedAt = Date.distantPast
    /// A line within this long of that waits.
    static let afterInterfaceSeconds = 0.5
    /// And waits this long, then queues rather than interrupts.
    static let afterInterfaceDelay = 0.4

    /// Called when a menu stops tracking, and after every box and panel.
    static func interfaceClosed(at when: Date = Date()) { interfaceClosedAt = when }

    /// How long a line spoken now should wait, or zero.
    static func waitAfterInterface(now: Date = Date()) -> Double {
        now.timeIntervalSince(interfaceClosedAt) < afterInterfaceSeconds ? afterInterfaceDelay : 0
    }

    private func say(_ text: String, interrupt: Bool = true) {
        guard !text.isEmpty else { return }
        let wait = Thread.isMainThread ? Speaker.waitAfterInterface() : 0
        let interrupt = wait > 0 ? false : interrupt
        spoken?(text, interrupt)
        guard !Speaker.muted else { return }
        let post = { [weak self] in
            guard let self else { return }
            let now = Date()
            if text == self.lastSpoken, now.timeIntervalSince(self.lastSpokenAt) < 0.15 { return }
            self.lastSpoken = text
            self.lastSpokenAt = now
            NSAccessibility.post(
                element: self.target,
                notification: .announcementRequested,
                userInfo: [
                    .announcement: text,
                    .priority: Speaker.priority(interrupt: interrupt).rawValue,
                ])
        }
        if wait > 0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + wait, execute: post)
        } else if Thread.isMainThread {
            post()
        } else {
            DispatchQueue.main.async(execute: post)
        }
    }
}
