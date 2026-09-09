// What macOS lets this app do, and asking for it.
//
// **An app does not appear in System Settings, Privacy and Security until it
// has ASKED.** That is the whole of the fault this file exists to fix. Until
// 3.5.22 the app only ever checked: `AVCaptureDevice.authorizationStatus` for
// the camera and `CGPreflightScreenCaptureAccess` for the screen, neither of
// which prompts and neither of which registers anything. So the camera was
// never granted, the screen was never granted, and searching the Camera list
// for Drop Deck found nothing, because as far as macOS was concerned Drop Deck
// had never wanted a camera.
//
// Tony, 8 September 2026: "it should automatically prompt anyone for all the
// permissions". It should, and now it does, in the two places that matter:
//
//   * **at the point of use**, when a camera or the screen is actually
//     started, which is what Apple asks for and what puts the prompt in front
//     of somebody who has just asked for the thing it is about;
//   * **on demand**, from Help, What Drop Deck is allowed to do, because a
//     presenter who cannot see a dialog needs a way to ask for one deliberately
//     rather than discovering the state of things halfway through a show.
//
// ## Three things about macOS that shape all of this
//
// **A prompt happens once, ever.** After that, `requestAccess` calls back with
// the stored answer and shows nothing. So a refusal cannot be un-refused from
// inside the app: it has to be System Settings after that, and this says so
// rather than asking again and looking broken.
//
// **Screen recording usually needs the app restarted** after it is granted,
// even though the switch is on. That is macOS, not this app, and it is worth
// saying out loud because otherwise it looks like the grant did not work.
//
// **The microphone is asked for by the audio system itself** the first time an
// input is opened, so there has never been a bug there. It is listed here
// anyway, because "what am I allowed to do" is a question with three answers
// and a list of two is a list somebody has to wonder about.

import Foundation
import AVFoundation
import CoreGraphics
import AppKit

enum Permission: String, CaseIterable {
    case microphone
    case camera
    case screen

    var label: String {
        switch self {
        case .microphone: return "Microphone"
        case .camera: return "Camera"
        case .screen: return "Screen recording"
        }
    }

    /// What the app cannot do without it, said as what the user loses.
    var whatFor: String {
        switch self {
        case .microphone:
            return "Your voice, on the air and in recordings"
        case .camera:
            return "A camera as the picture, and what the camera can see"
        case .screen:
            return "Your screen as the picture, and the camera in its corner"
        }
    }

    /// Where System Settings keeps it, said the way the pane is named.
    var settingsName: String {
        switch self {
        case .microphone: return "Microphone"
        case .camera: return "Camera"
        case .screen: return "Screen and System Audio Recording"
        }
    }

    private var settingsAnchor: String {
        switch self {
        case .microphone: return "Privacy_Microphone"
        case .camera: return "Privacy_Camera"
        case .screen: return "Privacy_ScreenCapture"
        }
    }

    var settingsURL: URL? {
        URL(string: "x-apple.systempreferences:com.apple.preference.security?"
                  + settingsAnchor)
    }
}

enum PermissionState: String {
    /// Never asked, so macOS does not list the app at all yet.
    case neverAsked
    case allowed
    case refused
    /// Asked for and answered by somebody else, a parental control or an MDM.
    case notYours

    var said: String {
        switch self {
        case .neverAsked: return "not asked for yet"
        case .allowed: return "allowed"
        case .refused: return "refused"
        case .notYours: return "not yours to change on this Mac"
        }
    }
}

enum Permissions {

    static func state(_ which: Permission) -> PermissionState {
        switch which {
        case .microphone, .camera:
            let media: AVMediaType = which == .camera ? .video : .audio
            switch AVCaptureDevice.authorizationStatus(for: media) {
            case .authorized: return .allowed
            case .denied: return .refused
            case .restricted: return .notYours
            case .notDetermined: return .neverAsked
            @unknown default: return .neverAsked
            }
        case .screen:
            // **What the app SAW outranks what the system said.** Preflight
            // has been caught answering true while every captured pixel was
            // zero, so once a capture has come back blank this reports the
            // truth rather than repeating the lie. See Screens.provedBlank.
            if Screens.provedBlank { return .refused }
            // Otherwise: there is no "never asked" for the screen. The only
            // thing macOS will tell an app is whether it may capture right
            // now, and an app that has never asked and one that was refused
            // both answer false, which is why this one is worth ASKING for
            // rather than reading.
            return CGPreflightScreenCaptureAccess() ? .allowed : .neverAsked
        }
    }

    /// Ask for one, and say what happened.
    ///
    /// `done` is always called, on the main queue, with the state afterwards
    /// and one sentence to say. Never throws and never leaves a caller
    /// waiting: a permission the user ignores is a dialog still on screen, and
    /// the show carries on behind it.
    static func ask(_ which: Permission,
                    done: @escaping (PermissionState, String) -> Void) {
        let before = state(which)
        if before == .allowed {
            finish(done, .allowed, "\(which.label) is already allowed.")
            return
        }
        if before == .notYours {
            finish(done, .notYours, "\(which.label) is managed for you on this Mac, "
                                  + "so Drop Deck cannot ask for it.")
            return
        }
        if before == .refused {
            // The screen is worth one more go even from here: asking is what
            // puts the app in the list, and a stale grant against an older
            // build's identity is exactly the case where it is not in it yet.
            if which == .screen { _ = CGRequestScreenCaptureAccess() }
            // macOS prompts once, ever. Asking again shows nothing at all, so
            // saying "asking" here would be a lie followed by silence.
            finish(done, .refused,
                   "\(which.label) was refused, and macOS only asks once. Turn Drop "
                 + "Deck on under \(which.settingsName) in System Settings, Privacy "
                 + "and Security.")
            return
        }

        switch which {
        case .microphone, .camera:
            let media: AVMediaType = which == .camera ? .video : .audio
            AVCaptureDevice.requestAccess(for: media) { granted in
                let after: PermissionState = granted ? .allowed : .refused
                finish(done, after, granted
                    ? "\(which.label) is allowed now."
                    : "\(which.label) was refused. Turn Drop Deck on under "
                    + "\(which.settingsName) in System Settings, Privacy and Security.")
            }
        case .screen:
            // Synchronous, and it is what puts the app in the list. It returns
            // false both when somebody says no and when the switch needs the
            // app restarted, which is why the wording covers both.
            let granted = CGRequestScreenCaptureAccess()
            finish(done, granted ? .allowed : .neverAsked, granted
                ? "Screen recording is allowed now."
                : "Drop Deck is now listed under Screen and System Audio Recording in "
                + "System Settings, Privacy and Security. Turn it on there, then quit "
                + "and open Drop Deck again, which macOS requires for this one.")
        }
    }

    /// Ask for everything that is not settled, one after another.
    ///
    /// In order, and one at a time: two system prompts at once is one prompt
    /// nobody sees.
    static func askAll(done: @escaping (String) -> Void) {
        var said: [String] = []
        var queue = Permission.allCases
        func next() {
            guard !queue.isEmpty else {
                finishText(done, said.joined(separator: " "))
                return
            }
            let which = queue.removeFirst()
            ask(which) { _, sentence in
                said.append(sentence)
                next()
            }
        }
        next()
    }

    /// Everything, in words, for the status line and for saying out loud.
    static func describe() -> String {
        Permission.allCases
            .map { "\($0.label): \(state($0).said)" }
            .joined(separator: ". ")
    }

    static func open(_ which: Permission) {
        guard let url = which.settingsURL else { return }
        NSWorkspace.shared.open(url)
    }

    private static func finish(_ done: @escaping (PermissionState, String) -> Void,
                               _ state: PermissionState, _ said: String) {
        if Thread.isMainThread { done(state, said) }
        else { DispatchQueue.main.async { done(state, said) } }
    }

    private static func finishText(_ done: @escaping (String) -> Void, _ said: String) {
        if Thread.isMainThread { done(said) }
        else { DispatchQueue.main.async { done(said) } }
    }
}
