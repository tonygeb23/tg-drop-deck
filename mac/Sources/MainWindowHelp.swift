// Everything behind the Help menu, and the two things that run on their own
// at startup: the feedback queue and the update check.
//
// The rule for all of it is the Windows one. A failure is on `announce`, a
// confirmation on `announceHelp`, and every answer to a question the user asked
// with a menu item is also a real, focusable window, whatever the speech
// setting says, so silence can never be mistaken for the feature being broken.

import AppKit

extension MainWindow {

    // ---------------------------------------------------------------- startup ---

    /// Called once the window is up and the startup line has been said.
    func startupHousekeeping() {
        AppUpdate.cleanLeftovers()
        Feedback.flushInBackground()
        startUpdateCheck()
        // Deferred behind the startup announcement on purpose: the first thing
        // the app says to somebody must be about their board, never about money.
        DispatchQueue.main.asyncAfter(deadline: .now() + 4.0) { [weak self] in
            self?.maybeAskAboutDonating()
        }
    }

    func plainAlert(_ title: String, _ text: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = text
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    // --------------------------------------------------------------- feedback ---

    /// Settings and counts only. Never a name, never a path.
    func feedbackDiagnostics() -> [String: Any] {
        [
            "sounds_assigned": board.assignedTotal,
            "sounds_missing": board.missingSlots.count,
            "folder_slots": board.folderSlots.count,
            "banks_renamed": board.bankNames.count,
            "playlist_tracks": board.playlist.count,
            "playlist_crossfade": board.playlist.crossfade,
            "drops_in_library": board.drops.count,
            "speech_level": board.speechLevel,
            "ducking": board.ducking,
            "duck_db": Double(board.duckDB),
            "bed_fade_in": board.bedFadeIn,
            "bed_fade_out": board.bedFadeOut,
            "global_hotkeys": board.globalHotkeysOn,
            "bank_scheme": board.bankScheme.rawValue,
            "audio_running": group.isRunning,
            "outputs": group.mixers.count,
            "samplerate": group.sampleRate,
            "mic_open": mic?.isOpen ?? false,
            "mic_monitor": board.micMonitor,
            "streaming": streamer.isOn,
            "recording": recorder.isRecording,
            "sources": board.sources.count,
        ]
    }

    /// Say what happened, from inside the app, at the moment it happened.
    /// Queued to disk before it is sent, so a report survives no network, a
    /// server restart, or the app being closed on the way out of a venue.
    func submitFeedback() {
        let panel = FeedbackPanel(diagnostics: feedbackDiagnostics())
        guard let (kind, text) = panel.run(over: window) else {
            speaker.announceHelp("Feedback closed, nothing sent")
            return
        }
        speaker.announceHelp("Sending")
        Feedback.submit(type: kind, message: text, extra: feedbackDiagnostics()) {
            [weak self] sent, queued in
            guard let self else { return }
            let message: String
            if sent > 0 {
                let earlier = sent - 1
                message = earlier == 0
                    ? "Thank you. That has been sent."
                    : "Thank you. That has been sent, and \(earlier) earlier one\(earlier == 1 ? "" : "s") went with it."
            } else {
                // NOT an error. It is on disk and it will go on its own.
                message = "Thank you. That is saved and will be sent the next time this Mac is online. "
                        + "Nothing has been lost."
            }
            _ = queued
            self.speaker.announce(message)
            self.plainAlert("Feedback", message)
        }
    }

    // --------------------------------------------------------------- donating ---

    /// Help, Donate, and the weekly word. The same window for both.
    func showDonate(mark: Bool) {
        let (donate, never) = DonatePanel().run(over: window)
        if never { Feedback.markNever(true) }
        if donate {
            Feedback.markDonated()
            if let url = URL(string: C.donateURL) { NSWorkspace.shared.open(url) }
            speaker.announce("Opening the donate page in your browser. Thank you")
            return
        }
        if mark { Feedback.markAsked() }
        speaker.announceHelp(never ? "Right you are, that will not come up again"
                                   : "No problem. Help, Donate, is there if you change your mind")
    }

    /// Once a week at the very most, and never in the first week.
    func maybeAskAboutDonating() {
        guard Feedback.shouldAskAboutDonating() else { return }
        // Never over a window somebody is already in.
        guard NSApp.modalWindow == nil else { return }
        showDonate(mark: true)
    }

    // ---------------------------------------------------------------- updates ---

    /// Look for a new version in the background, throttled to once a day, and
    /// silent unless something is actually there.
    func startUpdateCheck() {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let (available, info, _) = AppUpdate.autoCheck(Board.configDir())
            guard available, let info else { return }
            DispatchQueue.main.async { self?.offerUpdate(info, unasked: true) }
        }
    }

    /// Same check, but say something either way because the user asked.
    func checkForUpdates() {
        speaker.announceHelp("Checking for a new version.")
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let (available, info, message) = AppUpdate.autoCheck(Board.configDir(), force: true)
            DispatchQueue.main.async {
                self?.updateCheckDone(available: available, info: info, message: message)
            }
        }
    }

    /// The user asked a question, so answer it in a window either way. Anybody
    /// who has turned the app's speech down would otherwise get silence in reply
    /// to choosing Check for updates, which reads as the feature being broken.
    private func updateCheckDone(available: Bool, info: AppUpdate.Info?, message: String?) {
        if available, let info {
            offerUpdate(info, unasked: false)
            return
        }
        var problem = ""
        if let message, !message.lowercased().contains("newest") { problem = message }
        speaker.announceHelp(message ?? "You have the newest version.")
        _ = UpdatePanel.ask(over: window, product: C.appName, current: C.appVersion, problem: problem)
    }

    /// Ask before downloading, always. An app that replaces itself without
    /// asking is indistinguishable from malware, and one vanishing underneath
    /// somebody listening rather than looking is worse than no update at all.
    /// Doubly so on a live show.
    func offerUpdate(_ info: AppUpdate.Info, unasked: Bool) {
        if unasked && (NSApp.modalWindow != nil || streamer.isOn || recorder.isRecording) {
            // Not now. The daily check will find it again tomorrow, and Help,
            // check for updates finds it today.
            return
        }
        let answer = UpdatePanel.ask(over: window, product: C.appName, current: C.appVersion,
                                     newVersion: info.version, notes: info.notes)
        guard answer == .update else {
            speaker.announceHelp("Update skipped. Help, check for updates when you are ready.")
            return
        }
        guard AppUpdate.isInstalledCopy else {
            let text = "This copy is not in the Applications folder, so it cannot replace itself. "
                     + "Download version \(info.version) from tgstudios.app instead."
            speaker.announce(text)
            plainAlert("Update", text)
            return
        }
        guard !streamer.isOn, !recorder.isRecording else {
            let text = "Not while you are on air or recording. Come off air first, then Help, check for updates."
            speaker.announce(text)
            plainAlert("Update", text)
            return
        }
        speaker.announceHelp("Downloading. This may take a moment.")
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let (path, message) = AppUpdate.download(info)
            DispatchQueue.main.async { self?.downloadDone(path: path, message: message, info: info) }
        }
    }

    private func downloadDone(path: String?, message: String, info: AppUpdate.Info) {
        guard let path else {
            speaker.announce(message)
            plainAlert("Update failed", message)
            return
        }
        let target = Bundle.main.bundlePath
        let newApp: String
        do {
            newApp = try AppUpdate.unpack(zipPath: path, version: info.version)
        } catch {
            let text = "The download was fine but \(error.localizedDescription). Nothing has been changed."
            speaker.announce(text)
            plainAlert("Update failed", text)
            return
        }
        guard AppUpdate.canReplace(target) else {
            let text = "The Applications folder cannot be written to by this account, so version "
                     + "\(info.version) has been unpacked at \(newApp). Move it over the copy you "
                     + "have when you can. Your board and settings are shared, so everything is "
                     + "where you left it."
            speaker.announce(text)
            plainAlert("Update ready", text)
            return
        }
        // Asked once more, because the next thing that happens is the app
        // closing.
        guard confirm("Version \(info.version) is ready. Update now?",
                      informative: "Drop Deck will close and open again on the new version, in the "
                                 + "same place. Your board and settings are untouched.",
                      confirmTitle: "Update now") else {
            speaker.announce("Update left for later. The download is kept.")
            return
        }
        saveQuietly()
        let (ok, why) = AppUpdate.replace(target: target, with: newApp)
        guard ok else {
            speaker.announce(why)
            plainAlert("Update failed", why)
            return
        }
        speaker.announce("Updating. Drop Deck will open again in a moment.")
        AppUpdate.relaunch(target)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { NSApp.terminate(nil) }
    }

    // ------------------------------------------------------------------ about ---

    func showAbout() {
        say("\(C.appName) \(C.appVersion)", """
            \(C.tagline)

            Eighty slots across four banks: twenty sound effects, twenty dialog drops, \
            twenty looping music beds and twenty of your own.

            Sounds overlap and never cut each other off. Beds duck out of the way while a \
            sound plays, then come back.

            Free, and built keyboard first for screen reader users. This is the Mac copy: \
            it reads and writes the same board as the Windows one.

            The forty sounds and beds in the demo pack were generated with ElevenLabs AI. \
            Nothing in it is recorded or sampled from a commercial sound library.

            MP3 encoding is by LAME, https://lame.sourceforge.io/, which is included \
            as a separate library under the GNU Library General Public License. Its full \
            licence is in the app, at Contents/Resources/LAME-LICENSE.txt, and the source \
            is at https://tgstudios.app/downloads/lame-3.100.tar.gz. macOS has no MP3 \
            encoder of its own.

            (C) 2026 Tony Gebhard. MIT licensed.
            https://tgstudios.app/drop-deck/
            """)
    }
}

// ---------------------------------------------------------------- stations ---

extension MainWindow {

    /// Load a saved station from the On air menu. Not while it is broadcasting:
    /// swapping the server under a live stream mid sentence is not a thing to
    /// do quietly.
    func pickStation(_ name: String) { loadSavedSetup(name) }

    /// Load a saved setup, and say where the show goes now.
    ///
    /// **A saved setup carries both Preferences pages and where the show
    /// goes**, so loading one can move the show from a radio station to a
    /// video platform. Saying only the station's host would not mention that,
    /// which is why this answers with the pre-flight's summary.
    func loadSavedSetup(_ name: String) {
        guard !name.isEmpty, name != board.stream.name else { return }
        if streamer.isOn || videoStreamer.isOn {
            speaker.announce("Come off air first, Command B, then change where it goes")
            updateAirMenu()
            return
        }
        let wasVideo = board.liveTo == C.liveToVideo
        if board.loadStation(name) {
            mic.onAir = board.stream.sendMic
            touch()
            let report = preflight()
            var said = "\(name). Command B goes to \(report.summary())"
            if wasVideo != (board.liveTo == C.liveToVideo) {
                said += ", which is a different kind of destination from the last one"
            }
            speaker.announce(said)
        }
        updateAirMenu()
    }
}
