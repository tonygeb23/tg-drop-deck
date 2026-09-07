// Everything on the On air menu: the microphone, recording, the stream, the
// other programs riding with you, and the keys that work from anywhere.
//
// The rule that shapes the announcements here is the same one as everywhere
// else in this app: a failure is on `announce`, a confirmation is on
// `announceHelp`, and a key whose only job is to answer a question, like
// Command Shift B, is on `announceAnswer` so it still speaks at every level.

import AppKit

extension MainWindow {

    // ---------------------------------------------------------- microphone ---

    /// Command M. The only thing in this app that ever opens a microphone.
    func toggleMic() {
        if mic.isOpen {
            mic.close()
            speaker.announce("Microphone off. Music back up")
            updateStatusLine()
            return
        }
        mic.gainDB = board.micGainDB
        mic.channel = board.micChannel
        mic.monitorWanted = board.micMonitor
        mic.onAir = board.stream.sendMic
        mic.chain.settings = board.voiceOn ? board.voiceSettings : MicChain.defaults
        if !board.voiceOn {
            // Processing off leaves the settings alone and simply switches
            // every stage out, so turning it back on restores what was there.
            for key in ["gate_on", "highpass_on", "eq_on", "comp_on", "limit_on"] {
                mic.chain.set(key, 0)
            }
        }
        guard mic.open(deviceUID: board.micDeviceUID, outputRate: group.sampleRate) else {
            speaker.announce("The microphone would not open. "
                             + (mic.lastError ?? "no reason given"))
            return
        }
        board.micDeviceUID = mic.deviceUID
        board.micDeviceName = mic.deviceName
        speaker.announce("Microphone on, \(mic.deviceName ?? "default input"). Music ducked")
        updateStatusLine()
        touch()
    }

    func micSummary() -> String {
        var parts = ["Microphone \(board.micDeviceName ?? "default input")"]
        parts.append(String(format: "gain %+.0f decibels", board.micGainDB))
        parts.append(board.micMonitor ? "monitoring on" : "monitoring off")
        return parts.joined(separator: ", ")
    }

    // ------------------------------------------------------------ recording ---

    /// Command R. It does not need you to be on air and it does not fight with
    /// the stream: the two get separate buses.
    func toggleRecording() {
        if recorder.isRecording {
            let summary = recorder.stop(taps: group.taps)
            // The recorder took its own bus off the taps; this puts the mixers
            // back to not building an air sum if nothing else wants one.
            group.syncTaps()
            speaker.announce(summary ?? "The recording stopped")
            updateStatusLine()
            return
        }
        guard let path = recorder.start(taps: group.taps, rate: group.sampleRate,
                                        format: board.recordFormat,
                                        bitrate: board.recordBitrate,
                                        folder: board.recordFolder) else {
            speaker.announce("Recording would not start. "
                             + (recorder.lastError ?? "no reason given"))
            return
        }
        // The taps only feed the mixers once something is listening.
        group.syncTaps()
        speaker.announce("Recording to \((path as NSString).lastPathComponent)")
        updateStatusLine()
    }

    func openRecordingsFolder() {
        let folder = board.recordFolder ?? Recorder.defaultFolder()
        try? FileManager.default.createDirectory(atPath: folder,
                                                 withIntermediateDirectories: true)
        NSWorkspace.shared.open(URL(fileURLWithPath: folder))
    }

    // ------------------------------------------------------------- the air ---

    /// Command B. Nothing goes out until this is pressed.
    func toggleStream() {
        if streamer.isOn {
            streamer.stop(group: group)
            speaker.announce("Off air")
            updateStatusLine()
            return
        }
        guard !board.stream.host.isEmpty else {
            speaker.announce("There is no server set up yet. "
                             + "Set up streaming is on the On air menu")
            return
        }
        streamer.onState = { [weak self] state, detail in
            guard let self else { return }
            self.updateStatusLine()
            self.updateAirMenu()
            switch state {
            case .live: self.speaker.announce("On air")
            case .failed: self.speaker.announce("Could not go on air. \(detail)")
            case .retrying: self.speaker.announce("Off air, trying again. \(detail)")
            default: break
            }
        }
        mic.onAir = board.stream.sendMic
        _ = streamer.start(group: group, settings: board.stream)
        speaker.announce("Connecting to \(board.stream.host)")
        updateStatusLine()
    }

    /// Command Shift B. An answer, so it speaks at every level.
    func streamStatus() {
        speaker.announceAnswer(streamer.statusLine())
    }

    /// Command Shift A. Who is listening, which has to handle the awkward case
    /// that is really the common one: the server you send to is often not the
    /// server people listen on.
    func streamStats() {
        let text = board.stream.statsURL.isEmpty
            ? "http://\(board.stream.host):\(board.stream.port)/status-json.xsl"
            : board.stream.statsURL
        guard let url = URL(string: text) else {
            speaker.announce("That statistics address is not a web address")
            return
        }
        speaker.announceAnswer("Asking \(url.host ?? text)")
        var request = URLRequest(url: url)
        request.timeoutInterval = 8
        if !board.stream.password.isEmpty {
            let credentials = "\(board.stream.user):\(board.stream.password)"
            let auth = Data(credentials.utf8).base64EncodedString()
            request.setValue("Basic \(auth)", forHTTPHeaderField: "Authorization")
        }
        URLSession.shared.dataTask(with: request) { [weak self] data, _, error in
            guard let self else { return }
            DispatchQueue.main.async {
                if let error {
                    self.speaker.announceAnswer(
                        "The server did not answer. \(error.localizedDescription)")
                    return
                }
                guard let data,
                      let json = try? JSONSerialization.jsonObject(with: data)
                        as? [String: Any] else {
                    self.speaker.announceAnswer(
                        "The server answered, but not with anything this can read")
                    return
                }
                self.say("Who is listening", self.describeStats(json))
            }
        }.resume()
    }

    private func describeStats(_ json: [String: Any]) -> String {
        guard let stats = json["icestats"] as? [String: Any] else {
            return "The server answered, but not with Icecast statistics."
        }
        var lines: [String] = []
        if let host = stats["host"] as? String { lines.append("Server: \(host)") }
        let sources: [[String: Any]]
        if let list = stats["source"] as? [[String: Any]] { sources = list }
        else if let one = stats["source"] as? [String: Any] { sources = [one] }
        else { sources = [] }

        if sources.isEmpty {
            lines.append("")
            lines.append("No stream is connected to that server right now.")
            return lines.joined(separator: "\n")
        }
        var total = 0
        for source in sources {
            let mount = source["listenurl"] as? String
                ?? source["mount"] as? String ?? "a stream"
            let listeners = source["listeners"] as? Int ?? 0
            let peak = source["listener_peak"] as? Int ?? 0
            let title = source["title"] as? String
                ?? source["yp_currently_playing"] as? String ?? ""
            total += listeners
            lines.append("")
            lines.append(mount)
            lines.append("  Listening now: \(listeners)")
            lines.append("  Most at once: \(peak)")
            if !title.isEmpty { lines.append("  Playing: \(title)") }
        }
        let head = total == 0 ? "Nobody is listening at the moment."
                 : total == 1 ? "1 person is listening."
                 : "\(total) people are listening."
        return ([head] + lines).joined(separator: "\n")
    }

    func updateAirMenu() {
        NotificationCenter.default.post(name: .dropDeckAirChanged, object: nil)
    }

    // ------------------------------------------------------------- sources ---

    /// Option Shift S. One list plus one set of controls that follows it,
    /// deliberately, because a dialog per source is far more to hear.
    func showSources() {
        let panel = SourcesPanel(board: board)
        guard panel.run(over: window) else { return }
        sourceGroup.replace(with: board.sources, outputRate: group.sampleRate)
        let live = sourceGroup.all.filter(\.isRunning).count
        var line = board.sources.isEmpty
            ? "No extra sources"
            : "\(board.sources.count) source\(board.sources.count == 1 ? "" : "s"), "
              + "\(live) running"
        for source in sourceGroup.all where !source.isRunning {
            if let error = source.lastError {
                line += ". \(source.config.name): \(error)"
            }
        }
        speaker.announce(line)
        touch()
    }

    /// Option Command Shift S. Two axes: up and down choose a source, left and
    /// right choose an action, Space does it. Nothing here needs Tab or a
    /// mouse, because it is used mid link.
    func showSourceControl() {
        guard !sourceGroup.all.isEmpty || mic.isOpen else {
            speaker.announce("There is nothing on the air but the board. "
                             + "Option Shift S adds a source")
            return
        }
        let panel = SourceControlPanel(group: sourceGroup, mic: mic, speaker: speaker)
        panel.run(over: window)
        // The names may have changed, so put them back on the board.
        for source in sourceGroup.all {
            if let index = board.sources.firstIndex(where: { $0.id == source.config.id }) {
                board.sources[index] = source.config
            }
        }
        touch()
    }

    // ------------------------------------------------------- global hotkeys ---

    /// Command G arms and disarms the whole set.
    func toggleGlobalHotkeys() {
        if hotkeys.enabled {
            hotkeys.unregisterAll()
            board.globalHotkeysOn = false
            speaker.announce("Global hotkeys off. Other programs have those keys back.")
        } else {
            armGlobalHotkeys(announce: true)
        }
        touch()
    }

    func armGlobalHotkeys(announce: Bool) {
        let refused = hotkeys.register(board)
        board.globalHotkeysOn = true
        guard announce else { return }
        var line = "Global hotkeys on. "
        let n = hotkeys.count
        line += n == 0 ? "None assigned yet. Use Sounds, assign a global hotkey."
              : n == 1 ? "1 hotkey active." : "\(n) hotkeys active."
        if !refused.isEmpty {
            line += " These could not be registered, most likely because another "
                  + "program already uses them: " + refused.joined(separator: ", ")
        }
        speaker.announce(line)
    }

    /// A key for one slot, inside this app, for bank four only.
    func assignCustomHotkey() {
        guard let slot = actionSlot() else { return }
        guard slot.bank == C.bankMisc else {
            speaker.announce("\(slot.bankTitle) already has fixed hotkeys. "
                             + "Custom hotkeys are for bank four")
            return
        }
        let panel = HotkeyPanel(title: "Assign hotkey for \(slot.displayName)",
                                global: false,
                                current: slot.customHotkey,
                                speaker: speaker)
        guard let result = panel.run(over: window) else { return }
        switch result {
        case .cleared:
            slot.customHotkey = nil
            slot.macKeyCode = nil
            slot.macModifiers = nil
            speaker.announce("Hotkey cleared for \(slot.displayName)")
        case .chosen(let combination):
            slot.customHotkey = combination.label
            slot.macKeyCode = Int(combination.keyCode)
            slot.macModifiers = UInt(combination.modifiers)
            speaker.announce("Hotkey \(combination.spoken) for \(slot.displayName)")
        }
        refreshSlot(slot.index)
        touch()
    }

    /// A key that works from any program.
    func assignGlobalHotkey() {
        guard let slot = actionSlot() else { return }
        guard slot.isAssigned else {
            speaker.announce("That slot is empty")
            return
        }
        let panel = HotkeyPanel(title: "Assign global hotkey for \(slot.displayName)",
                                global: true,
                                current: slot.globalHotkey,
                                speaker: speaker)
        guard let result = panel.run(over: window) else { return }
        switch result {
        case .cleared:
            slot.globalHotkey = nil
            speaker.announce("Global hotkey removed from \(slot.displayName).")
        case .chosen(let combination):
            slot.globalHotkey = combination.label
            speaker.announce("Global hotkey \(combination.spoken) for \(slot.displayName).")
        }
        refreshSlot(slot.index)
        if hotkeys.enabled { armGlobalHotkeys(announce: false) }
        touch()
    }

    /// A key typed inside the app that belongs to a bank four slot.
    func customHotkeySlot(for event: NSEvent) -> Int? {
        guard let pressed = HotkeyCombination.from(event: event), !pressed.isBare
        else { return nil }
        for slot in board.bankSlots(C.bankMisc) where !slot.hidden {
            guard let code = slot.macKeyCode, let mods = slot.macModifiers else { continue }
            if UInt32(code) == pressed.keyCode && UInt32(mods) == pressed.modifiers {
                return slot.index
            }
        }
        return nil
    }
}

extension Notification.Name {
    static let dropDeckAirChanged = Notification.Name("DropDeckAirChanged")
}
