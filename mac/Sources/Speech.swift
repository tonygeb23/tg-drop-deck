// How much the app says out loud, and where the words land when it does not.
//
// A screen reader is already reading every control. Speech from the app is only
// for what the screen reader cannot know, and how much of it is the user's
// choice. Four channels, and deciding which one a line belongs on is the whole
// job.
//
// On Windows this went through accessible_output2 to NVDA. On macOS the same
// job is done by posting an announcement to VoiceOver through NSAccessibility,
// which needs no library and no bridge object.
//
// ALL FOUR CHANNELS WRITE THE STATUS LINE AT EVERY LEVEL, so nothing this app
// has to say is ever only spoken. At "none" the information is still on screen
// and still reachable, it just does not interrupt.

import AppKit

final class Speaker {

    /// Where a line goes when it is not spoken. Set by the window.
    var status: ((String) -> Void)?

    var level: String = C.defaultSpeechLevel
    /// The separate switch for playback names, which is a board setting.
    var playbackEnabled = true

    private weak var element: NSView?

    func attach(to view: NSView) { element = view }

    // ------------------------------------------------------------ channels ---

    /// What you cannot otherwise know: a missing file, a key the system
    /// refused, a number you asked for. Silent only at "none".
    func announce(_ text: String) {
        note(text)
        guard level != C.speechNone else { return }
        say(text, interrupt: true)
    }

    /// A confirmation of something you just did, or a hint you have read
    /// before. Silent below "all".
    func announceHelp(_ text: String) {
        note(text)
        guard level == C.speechAll else { return }
        say(text, interrupt: true)
    }

    /// The name of a sound you can hear anyway. Silent below "all", and off
    /// entirely when the user has turned playback names off.
    func announcePlayback(_ text: String) {
        note(text)
        guard level == C.speechAll, playbackEnabled else { return }
        say(text, interrupt: true)
    }

    /// The answer to a question the user asked with a key. Spoken at EVERY
    /// level including "none", because a key whose only job is to answer and
    /// which then says nothing is broken, not quiet.
    func announceAnswer(_ text: String) {
        note(text)
        say(text, interrupt: true)
    }

    /// Things the screen reader has already said for itself. Never spoken,
    /// always written down.
    func note(_ text: String) {
        guard !text.isEmpty else { return }
        if Thread.isMainThread { status?(text) }
        else { DispatchQueue.main.async { self.status?(text) } }
    }

    // --------------------------------------------------------------- saying ---

    /// Interrupting is the default: during a live show the thing you just did
    /// matters more than the thing you did a second ago.
    private func say(_ text: String, interrupt: Bool) {
        guard !text.isEmpty else { return }
        let post = {
            let target: Any = self.element ?? NSApp as Any
            NSAccessibility.post(
                element: target,
                notification: .announcementRequested,
                userInfo: [
                    .announcement: text,
                    .priority: (interrupt ? NSAccessibilityPriorityLevel.high
                                          : NSAccessibilityPriorityLevel.medium).rawValue,
                ])
        }
        if Thread.isMainThread { post() } else { DispatchQueue.main.async(execute: post) }
    }
}
