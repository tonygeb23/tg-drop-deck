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
    func announce(_ text: String) {
        note(text)
        guard level != C.speechNone else { return }
        say(text)
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
    func announceHelp(_ text: String) {
        note(text)
        guard level == C.speechAll else { return }
        say(text)
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
    private func say(_ text: String) {
        guard !text.isEmpty else { return }
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
                    .priority: NSAccessibilityPriorityLevel.high.rawValue,
                ])
        }
        if Thread.isMainThread { post() } else { DispatchQueue.main.async(execute: post) }
    }
}
