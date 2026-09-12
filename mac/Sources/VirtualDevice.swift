// Drop Deck Audio: the app's half of its own virtual audio cable.
//
// The driver itself is `mac/driver/DropDeckAudio.c`, an AudioServerPlugIn that
// ships inside this app's Resources. This file is everything the app needs to
// say about it: whether it is there, whether it is the version we ship, how to
// put it there, and how to take it away again.
//
// ## Why the app ships a cable at all
//
// Because the alternative is a sentence. Without one, "send this show to
// TeamTalk" means: go and find a virtual audio cable, work out that the thing
// called Input is a playback device and the thing called Output is a recording
// one, install it with an administrator password, come back, pick it here, then
// go into TeamTalk and pick the other end. Tony asked for the version of that
// with none of it in it: one entry called Drop Deck Audio, in both lists,
// already pointed at.
//
// ## What this cannot do, said plainly
//
// **A HAL plug-in lives in /Library/Audio/Plug-Ins/HAL, which belongs to root**,
// so installing one needs an administrator password. There is no version of
// this that does not. The app asks once, with macOS's own password box, which
// VoiceOver reads.
//
// **Core Audio has to be restarted before a new plug-in appears.** That stops
// every sound on the machine for a moment, VoiceOver included, which for the
// person this app is written for is not a detail. So it is said out loud
// BEFORE it happens, in words, and it is the user's choice: `restartAudio`
// exists as its own step and the install can decline to take it.
// `sudo launchctl kickstart` is not an alternative, it has been refused under
// System Integrity Protection since macOS 14.4.

import Foundation
import AppKit

enum VirtualDevice {

    /// What the driver calls itself. The UID is what a board stores and what
    /// `AudioDevices` matches on, so it must never change once it has shipped:
    /// a changed UID is every user's send silently pointing at nothing.
    static let uid = "TGStudios:DropDeckAudio:1"
    static let name = "Drop Deck Audio"
    static let bundleName = "Drop Deck Audio.driver"
    static let halFolder = "/Library/Audio/Plug-Ins/HAL"

    static var installedPath: String { "\(halFolder)/\(bundleName)" }

    // ------------------------------------------------------------- is it here ---

    /// Is the device really on this machine, asked of Core Audio rather than of
    /// the file system. A bundle in place that coreaudiod has not loaded is not
    /// a device, and the commonest reason for that is the folder's permissions.
    static var isPresent: Bool {
        AudioDevices.deviceID(forUID: uid) != nil
    }

    /// Is the bundle on disk, whether or not Core Audio has picked it up.
    static var isInstalled: Bool {
        FileManager.default.fileExists(atPath: installedPath)
    }

    /// The copy inside this app, which is the one we would install.
    static var bundled: String? {
        Bundle.main.path(forResource: "Drop Deck Audio", ofType: "driver")
    }

    private static func version(of bundlePath: String) -> String? {
        let plist = bundlePath + "/Contents/Info.plist"
        guard let data = FileManager.default.contents(atPath: plist),
              let info = try? PropertyListSerialization.propertyList(
                from: data, options: [], format: nil) as? [String: Any] else { return nil }
        return info["CFBundleShortVersionString"] as? String
    }

    static var installedVersion: String? { version(of: installedPath) }
    static var bundledVersion: String? { bundled.flatMap(version(of:)) }

    /// Is the copy on this machine older than the one in this app.
    static var needsUpdating: Bool {
        guard isInstalled, let ours = bundledVersion else { return false }
        guard let theirs = installedVersion else { return true }
        return theirs.compare(ours, options: .numeric) == .orderedAscending
    }

    // ------------------------------------------------------------- what to say ---

    /// One line about where things stand, for Help and for the send panel.
    static func describe() -> String {
        if isPresent && !needsUpdating {
            return "\(name) is installed and Core Audio can see it. Choose it "
                + "as the send's output here, and set the other program's "
                + "microphone to \(name) as well."
        }
        if isPresent && needsUpdating {
            return "\(name) is installed, and this copy of Drop Deck ships a "
                + "newer version of it. Installing again will replace it."
        }
        if isInstalled {
            // The single commonest real fault, and it is invisible: the folder
            // is there, the bundle is there, and coreaudiod cannot read it.
            return "\(name) is on this machine but Core Audio has not loaded "
                + "it. That is almost always the permissions on "
                + "\(halFolder). Installing it again puts them right."
        }
        return "\(name) is not installed yet. It is a virtual audio cable that "
            + "belongs to Drop Deck: install it once and it appears in every "
            + "program's microphone list, so TeamTalk, Zoom or Skype can take "
            + "your whole show with nothing else to set up."
    }

    /// Exactly what installing will do, said before it is done rather than
    /// after. **The restart matters more here than in most apps**: it stops
    /// every sound on the machine for a moment, and on this machine that
    /// includes VoiceOver.
    static let warning = """
        Installing \(name) does two things.

        It copies the cable into \(halFolder), which belongs to the system, so \
        macOS will ask for your password. That is macOS asking, not Drop Deck: \
        the app never sees what you type.

        Then it restarts Core Audio, which stops every sound on this Mac for a \
        second or two. VOICEOVER WILL GO QUIET AND COME BACK. If you are on \
        air, or in a call, do this afterwards instead.

        If you would rather not restart Core Audio now, the cable will appear \
        the next time you log in.
        """

    // ------------------------------------------------------------ doing it ---

    enum Outcome {
        case done
        case cancelled
        case failed(String)
    }

    /// Put the bundled cable in place, and optionally restart Core Audio.
    ///
    /// One `osascript` call, so macOS asks for the password ONCE for the whole
    /// job rather than once per command. Everything in it is quoted, and every
    /// path is one of ours: nothing a user typed reaches this string.
    ///
    /// **The `chown` and `chmod` are not tidiness.** `_coreaudiod` has to
    /// traverse the folder and read the bundle, and the one failure everybody
    /// hits is a HAL folder left at the wrong mode by some other installer: the
    /// driver is there, nothing loads it, and no error appears anywhere a user
    /// could find.
    static func install(restartAudio: Bool) -> Outcome {
        guard let source = bundled else {
            return .failed("this copy of Drop Deck does not have the cable inside it")
        }
        var script = "mkdir -p '\(halFolder)'"
            + " && rm -rf '\(installedPath)'"
            + " && cp -R '\(source)' '\(installedPath)'"
            + " && chown -R root:wheel '\(halFolder)'"
            + " && chmod -R 755 '\(halFolder)'"
        if restartAudio {
            // `killall -9`, because coreaudiod traps SIGTERM on current macOS
            // and a plain killall can be a no-op that looks like success.
            script += " && killall -9 coreaudiod"
        }
        return run(script)
    }

    /// Take it away again, completely.
    static func uninstall(restartAudio: Bool) -> Outcome {
        guard isInstalled else { return .done }
        var script = "rm -rf '\(installedPath)'"
        if restartAudio { script += " && killall -9 coreaudiod" }
        return run(script)
    }

    /// Restart Core Audio on its own, for somebody who declined it earlier.
    static func restartCoreAudio() -> Outcome {
        run("killall -9 coreaudiod")
    }

    private static func run(_ script: String) -> Outcome {
        let source = "do shell script \"\(script.replacingOccurrences(of: "\"", with: "\\\""))\""
            + " with administrator privileges"
        var error: NSDictionary?
        guard let apple = NSAppleScript(source: source) else {
            return .failed("the installer could not be built")
        }
        apple.executeAndReturnError(&error)
        guard let error else { return .done }
        // Apple event error -128 is the user pressing Cancel on the password
        // box. That is an answer, not a fault, and saying "installation failed"
        // to somebody who chose not to install is simply wrong.
        if (error[NSAppleScript.errorNumber] as? Int) == -128 { return .cancelled }
        let why = (error[NSAppleScript.errorMessage] as? String)
            ?? "macOS did not say why"
        return .failed(why)
    }

    /// Wait for Core Audio to hand the device back after a restart.
    ///
    /// `coreaudiod` is launch on demand with no KeepAlive, so it comes back
    /// within a second or two of the next client asking for it. Asking is what
    /// `AudioDevices` does, so this polls rather than sleeping a fixed time.
    static func waitToAppear(timeout: Double = 8.0) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if isPresent { return true }
            Thread.sleep(forTimeInterval: 0.25)
        }
        return isPresent
    }
}
