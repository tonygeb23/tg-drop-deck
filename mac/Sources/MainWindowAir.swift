// Everything on the On air menu: the microphone, recording, the stream, the
// other programs riding with you, and the keys that work from anywhere.
//
// The rule that shapes the announcements here is the same one as everywhere
// else in this app: a failure is on `announce`, a confirmation is on
// `announceHelp`, and a key whose only job is to answer a question, like
// Command Shift B, is on `announceAnswer` so it still speaks at every level.

import AppKit

extension MainWindow {

    /// "and it is not going out", when that is true and somebody is in a
    /// position to care.
    ///
    /// The microphone reaching the air is the one thing about a show you cannot
    /// hear for yourself: you monitor your own voice either way, so a stream
    /// and a recording without you in it sound exactly like ones with you in it
    /// from where you are sitting. Nothing said so until 3.3.2, and the first
    /// person to hit it had a stream going out with no presenter on it.
    ///
    /// **Either streamer is a stream** (audit 1, finding 7): both take the
    /// same on air mix, which the one switch keeps the microphone out of, and
    /// "On air to YouTube" used to carry no warning at all. A picture
    /// recording is a recording, for the same reason.
    var micOffAirNote: String? {
        MainWindow.micOffAirNote(sendMic: board.stream.sendMic,
                                 streaming: streamer.isOn || videoStreamer.isOn,
                                 recording: recorder.isRecording || videoRecorder.isRecording)
    }

    static func micOffAirNote(sendMic: Bool, streaming live: Bool, recording taping: Bool) -> String? {
        guard !sendMic else { return nil }
        guard live || taping else { return nil }
        let what = live && taping ? "the stream or the recording"
                 : live ? "the stream" : "the recording"
        return "Your microphone is NOT going to \(what). "
             + "Preferences, Streaming, put the microphone on the air"
    }

    // ---------------------------------------------------------- microphone ---

    /// Command M, and Option Shift M. The only thing in this app that ever
    /// opens a microphone.
    ///
    /// **This key must never do nothing** (Windows 3.8.3, Mashal). Every way
    /// it can fail is said in words: the privacy settings are asked BEFORE
    /// anything opens, because a refused microphone opens perfectly well on a
    /// Mac and sends silence (W383-06); a failure is said in plain words from
    /// the real OSStatus (W383-07); the chosen microphone being unplugged is
    /// said and never saved over (W383-09); and a moment after opening, exact
    /// silence is noticed and said (W383-10).
    func toggleMic() {
        if mic.isOpen {
            mic.close()
            speaker.announceState("Microphone off. Music back up")
            updateStatusLine()
            return
        }
        switch MicDiag.privacy(Permissions.state(.microphone)) {
        case .refuse(let said):
            speaker.announceState(MicDiag.failureLine(reason: said, missing: nil))
        case .ask:
            // macOS has never been asked. Ask, and open in the answer: the
            // keypress is still what opens it, a moment later.
            speaker.announceState("macOS is asking first whether Drop Deck may use "
                                  + "the microphone")
            Permissions.ask(.microphone) { [weak self] state, _ in
                guard let self else { return }
                if state == .allowed {
                    self.openMic()
                } else {
                    self.speaker.announceState(MicDiag.failureLine(
                        reason: MicDiag.privacySentence(state) ?? MicDiag.privacyBlocked,
                        missing: nil))
                }
                self.updateAirMenu()
            }
        case .open:
            openMic()
        }
    }

    private func openMic() {
        guard !mic.isOpen else { return }
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
        // A chosen microphone that is not plugged in today: the system default
        // is opened instead and that is SAID. The board is not touched, so the
        // real one comes back the moment it is plugged in again.
        let missing = MicDiag.missing(chosenUID: board.micDeviceUID,
                                      chosenName: board.micDeviceName,
                                      isPresent: { AudioDevices.deviceID(forUID: $0) != nil })
        guard mic.open(deviceUID: missing == nil ? board.micDeviceUID : nil,
                       outputRate: group.sampleRate) else {
            speaker.announceState(MicDiag.failureLine(reason: MicDiag.explain(mic.lastStatus),
                                                      missing: missing))
            updateAirMenu()
            return
        }
        var line = "Microphone on, \(mic.deviceName ?? "default input"). Music ducked"
        if let missing { line += MicDiag.fellBack(missing) }
        if let warning = micOffAirNote { line += ". \(warning)" }
        speaker.announceState(line)
        updateStatusLine()
        updateAirMenu()
        // A microphone that opens is not yet a microphone that works.
        let opening = mic.openings
        DispatchQueue.main.asyncAfter(deadline: .now() + C.micSignalCheckSeconds) {
            [weak self] in self?.checkMicSignal(opening)
        }
    }

    /// A moment after opening: is macOS sending anything at all? Said once
    /// per opening, and only when it is true. See `MicDiag.silenceLine`.
    func checkMicSignal(_ opening: Int) {
        guard mic.isOpen, mic.openings == opening else { return }
        if let line = MicDiag.silenceLine(signal: mic.signalSeen, blocks: mic.blocksSeen,
                                          privacy: Permissions.state(.microphone)) {
            speaker.announce(line)
        }
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
            announceRecording("Recording stopped", summary ?? "")
            updateStatusLine()
            return
        }
        guard let path = recorder.start(taps: group.taps, rate: group.sampleRate,
                                        format: board.recordFormat,
                                        bitrate: board.recordBitrate,
                                        folder: board.recordFolder) else {
            speaker.announceState("Recording would not start. "
                                  + (recorder.lastError ?? "no reason given"))
            return
        }
        // The taps only feed the mixers once something is listening.
        group.syncTaps()
        // Whatever is already on the air belongs at 0:00, or the first track
        // of the show is missing from its own track list.
        noteCurrentTrack()
        var detail = ((path as NSString).lastPathComponent as NSString).deletingPathExtension
        if mic.isOpen, let warning = micOffAirNote { detail += ". \(warning)" }
        announceRecording("Recording started", detail)
        updateStatusLine()
    }

    /// A recording starting, stopping, pausing or resuming.
    ///
    /// Siena, October 2026: starting or stopping a recording "doesn't
    /// actually announce whether the recording has started or stopped". It
    /// opened with "Recording to Drop Deck Stream 004.mp3", a file name, so
    /// the one fact asked about was never said in as many words. It now
    /// opens with `short`, and the detail follows. A file being written makes
    /// no sound, so this is answered at every level; at "none" only `short`
    /// is spoken, and the whole line is on the status line. Chosen from the
    /// menu, the line waits for VoiceOver to read where focus landed (see
    /// `Speaker.interfaceClosed`).
    func announceRecording(_ short: String, _ detail: String = "") {
        let full = detail.isEmpty ? short : "\(short). \(detail)"
        if speaker.level == C.speechNone {
            speaker.announceState(short)
            speaker.note(full)
        } else {
            speaker.announceState(full)
        }
    }

    /// Either recording is paused. ANY, because that is what the key does:
    /// if either is paused it resumes both.
    var recordingPaused: Bool { recorder.isPaused || videoRecorder.isPaused }

    /// Option Shift R. Hold the recording and carry on into the same file.
    /// One key for both recordings, because a show recorded as sound and as
    /// picture is one show: pausing one and not the other is a pair of files
    /// that no longer line up.
    func togglePauseRecording() {
        let running = recorder.isRecording || videoRecorder.isRecording
        guard running else {
            announceRecording("Nothing is recording", "Command R starts a recording")
            return
        }
        if recordingPaused {
            recorder.resume()
            videoRecorder.resume()
            noteCurrentTrack(resuming: true)
            announceRecording("Recording resumed")
        } else {
            if recorder.isRecording { recorder.pause() }
            if videoRecorder.isRecording { videoRecorder.pause() }
            let elapsed = max(recorder.isRecording ? recorder.elapsed : 0,
                              videoRecorder.isRecording ? videoRecorder.elapsed : 0)
            announceRecording("Recording paused",
                              "\(MainWindow.spokenDuration(elapsed)) so far. Option Shift R carries on")
        }
        updateStatusLine()
    }

    /// The running order track on the air, into every track list being
    /// written. On resume, a track that is already the last entry is not
    /// listed twice.
    func noteCurrentTrack(resuming: Bool = false) {
        guard player.isPlaying, let track = player.currentTrack else { return }
        let title = track.displayName
        let artist = track.artist ?? ""
        for (on, cue, at) in [(recorder.isRecording, recorder.cue, recorder.elapsed),
                              (videoRecorder.isRecording, videoRecorder.cue, videoRecorder.elapsed)]
        where on {
            if resuming { cue?.noteOnResume(title: title, performer: artist, seconds: at) }
            else { _ = cue?.add(title: title, performer: artist, seconds: at) }
        }
        cueWindow?.refresh()
    }

    /// "2 seconds", "1 minute 5 seconds", "1 hour 3 minutes". No zeros.
    /// Windows' `_duration`.
    static func spokenDuration(_ seconds: Double) -> String {
        let whole = max(0, Int(seconds))
        let hours = whole / 3600, minutes = (whole % 3600) / 60, secs = whole % 60
        if hours > 0 {
            return count(hours, "hour") + (minutes > 0 ? " " + count(minutes, "minute") : "")
        }
        if minutes > 0 {
            return count(minutes, "minute") + (secs > 0 ? " " + count(secs, "second") : "")
        }
        return count(secs, "second")
    }

    func openRecordingsFolder() {
        let folder = board.recordFolder ?? Recorder.defaultFolder()
        try? FileManager.default.createDirectory(atPath: folder,
                                                 withIntermediateDirectories: true)
        NSWorkspace.shared.open(URL(fileURLWithPath: folder))
    }

    // ------------------------------------------------------------- the air ---

    /// Command B goes live on the video platform and Option Shift B on the
    /// radio station, each a toggle for its own destination (W382-07). Nothing
    /// goes out until one of them is pressed.
    ///
    /// **The key IS the choice**, so it is written down before anything reads
    /// it (W382-08): everything downstream asks the board which destination
    /// this is, and it gets the answer the user just gave rather than one from
    /// last week. And, as on Windows, Stay off air leaves it where the key
    /// pointed it: a mis-press is undone by pressing the other key.
    ///
    /// **The wrong key while live does nothing but say where you are**
    /// (W382-09). It used to stop whatever was on, which after the split
    /// would have let the radio key drop a video broadcast.
    ///
    /// **The asking lives here and never in `startStream`.** That is load
    /// bearing rather than tidy: this is called by a person pressing a key,
    /// and only a person can answer a question. A panel inside the starting
    /// code would hang every check that goes live, for ever, on a window
    /// nothing can click.
    func toggleStream(to: String? = nil) {
        // Nobody said, so honour what is set up. The keys and the menu items
        // always say; this covers anything older that does not.
        let to = to ?? board.liveTo
        switch OnAir.press(to, liveTo: board.liveTo, videoOn: videoStreamer.isOn,
                           radioOn: streamer.isOn) {
        case .comeOff:
            if to == C.liveToVideo {
                videoStreamer.stop(group: group)
                // Let go of the picture, never close it: a recording may be
                // holding the same one, and it now fills its own frames.
                releaseStreamPicture()
            } else {
                streamer.stop(group: group)
            }
            speaker.announceState("Off air")
            updateStatusLine()
            updateAirMenu()
            return
        case .elsewhere(let said):
            speaker.announceAnswer(said)
            return
        case .goLive(let pointAt):
            if pointAt {
                board.liveTo = to
                touch()
                updateAirMenu()
            }
        }
        // What is about to happen, said before it happens, and checked.
        // Nearly every way of getting a broadcast wrong survives the
        // connection and ruins the show quietly.
        if board.askBeforeLive {
            // A LOOP, because Put it right opens the page that fixes it and
            // then the question is worth asking again with the fix in. One
            // shot would send somebody to Preferences and leave them off air
            // with nothing to press.
            var asking = true
            while asking {
                // Put it right opens Preferences, where the Streaming location
                // box lives, and unticking it there must not turn Command B
                // into a radio broadcast. The key pressed is the destination.
                if board.liveTo != to {
                    board.liveTo = to
                    touch()
                    updateAirMenu()
                }
                let report = preflight()
                switch GoLivePanel(report: report, board: board).run(over: window) {
                case .stayOff:
                    // The reason, when there is one (W384-13): Escape after a
                    // blocked summary used to answer "Still off air" and
                    // nothing else.
                    speaker.announceState(GoLivePanel.stayOffSentence(report))
                    return
                case .putItRight(let page):
                    showPreferences(tab: page == C.fixVideo ? "Video streaming" : "Streaming")
                    // Round again with the fix in, unless the box was ticked
                    // on the way past.
                    asking = board.askBeforeLive
                case .goLive:
                    asking = false
                }
            }
        } else {
            // The asking is off. **The checking still happens and everything
            // it found is still said**, stops and warnings alike, because a
            // presenter who turned the dialog off did not ask to stop being
            // told their microphone is off the air. Windows says the same list
            // whether or not it is blocked.
            let report = preflight()
            let trouble = (report.stops + report.warnings).map { $0.text }
            if !trouble.isEmpty {
                speaker.announceState(trouble.joined(separator: ". "))
            }
            if report.blocked { return }
        }
        if to == C.liveToVideo { startVideoStream() } else { startAudioStream() }
    }

    private func startAudioStream() {
        guard !board.stream.host.isEmpty else {
            speaker.announceState("There is no server set up yet. "
                             + "Set up streaming is on the On air menu")
            return
        }
        streamer.onState = { [weak self] state, detail in
            guard let self else { return }
            self.updateStatusLine()
            self.updateAirMenu()
            switch state {
            case .live:
                var line = "On air"
                if self.mic.isOpen, let warning = self.micOffAirNote { line += ". \(warning)" }
                self.speaker.announceState(line)
            case .failed: self.speaker.announceState("Could not go on air. \(detail)")
            case .retrying: self.speaker.announceState("Off air, trying again. \(detail)")
            default: break
            }
        }
        mic.onAir = board.stream.sendMic
        // What is playing, held before the connection so it is sent the
        // moment the station takes us.
        streamer.nowPlaying(nowPlayingTitle)
        _ = streamer.start(group: group, settings: board.stream)
        speaker.announceState("Connecting to \(board.stream.host)")
        updateStatusLine()
    }

    private func startVideoStream() {
        videoStreamer.onState = { [weak self] state, detail in
            guard let self else { return }
            self.updateStatusLine()
            self.updateAirMenu()
            switch state {
            case .live:
                var line = "On air to \(StreamServers.serverLabel(self.board.videoServer))"
                if self.mic.isOpen, let warning = self.micOffAirNote { line += ". \(warning)" }
                self.speaker.announceState(line)
            case .failed:
                self.speaker.announceState("Could not go on air. \(detail)")
                // A run that ended itself lets go of the picture too.
                self.releaseStreamPicture()
            case .retrying: self.speaker.announceState("Off air, trying again. \(detail)")
            default: break
            }
            // WHO FILLS A RECORDING'S FRAMES depends on whether the stream is
            // really on air, so it is decided again on every change of state.
            self.syncRecordPicture()
        }
        // The picture and the health of it are said out loud as they happen,
        // because there is no preview to glance at.
        videoStreamer.onSay = { [weak self] text in self?.speaker.announce(text) }
        mic.onAir = board.stream.sendMic
        // The stream's hold on the ONE picture. It opens on the feed's own
        // queue, so a camera opening does not hold the keyboard, and the card
        // stands in for the half second it takes (W381-31).
        let picture = takeStreamPicture()
        guard videoStreamer.start(group: group, settings: videoStreamSettings(),
                                  picture: picture) else {
            releaseStreamPicture()
            speaker.announceState("Could not go on air. \(videoStreamer.detail)")
            return
        }
        videoStreamer.setTitle(nowPlayingTitle)
        speaker.announceState("Connecting to "
                            + StreamServers.serverLabel(board.videoServer))
        updateStatusLine()
    }

    /// Command Shift B. An answer, so it speaks at every level.
    func streamStatus() {
        // **Whichever destination Streaming location points at**, named with
        // the key that goes live there. Windows read the
        // radio station's address whichever was ticked until 3.4.1, so a board
        // set up for YouTube and nothing else answered "Off air, and no server
        // is set up yet" while Command B would have gone live perfectly well.
        // It is the one question this key exists to answer.
        // And a picture recording, when there is one, in the same answer
        // (W381-13): "am I recording" and "am I on air" are the same question
        // asked in a hurry.
        let taping = recordingLine()
        if videoStreamer.isOn {
            speaker.announceAnswer(MainWindow.withSentence(videoStreamer.statusLine(), taping))
            return
        }
        if streamer.isOn {
            speaker.announceAnswer(MainWindow.withSentence(streamer.statusLine(), taping))
            return
        }
        // **Off air, this answers with the pre-flight rather than a bare "Off
        // air".** It is the one question this key exists to answer, and a
        // board set up for a video platform and nothing else used to be told
        // "no server is set up yet" while Command B would have gone live
        // perfectly well.
        let report = preflight()
        var line = OnAir.offAirStatus(liveTo: board.liveTo, summary: report.summary())
        let trouble = (report.stops + report.warnings).map { $0.text }
        if !trouble.isEmpty { line += ". " + trouble.joined(separator: ". ") }
        speaker.announceAnswer(MainWindow.withSentence(line, taping))
    }

    /// One more sentence on the end of a line, with the full stop between
    /// them that a screen reader needs to pause.
    static func withSentence(_ line: String, _ more: String) -> String {
        guard !more.isEmpty else { return line }
        let ends = line.hasSuffix(".") || line.isEmpty
        return line + (ends ? " " : ". ") + more
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

    /// Help, Check my audio sources. Listens, then says what each one is
    /// really doing. Safe on air: it reads meters, never the audio.
    func showSourceCheck() {
        SourceHealthPanel(group: sourceGroup, speaker: speaker,
                          micOnAir: mic.onAir, micOpen: mic.isOpen).run(over: window)
    }

    /// Say which sources would not open, once, quietly.
    ///
    /// Mirrors what Windows says in `start_sources`. A source that is not
    /// plugged in is an ordinary thing on a laptop that moves between desks and
    /// must not become a dialog in front of a show, but it must not be silent
    /// either: a source marked on air that is not running is the difference
    /// between a broadcast with your screen reader in it and one without.
    func announceSourceTrouble(_ trouble: [String]) {
        guard !trouble.isEmpty else { return }
        speaker.announceHelp(trouble.count == 1
            ? "This source would not open. \(trouble[0])"
            : "These sources would not open. \(trouble.joined(separator: ". "))")
    }

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
        let panel = SourceControlPanel(group: sourceGroup, mic: mic, speaker: speaker) {
            [weak self] id in
            guard let self else { return false }
            return self.removeSource(id: id)
        }
        panel.run(over: window)
        // The names may have changed, so put them back on the board.
        for source in sourceGroup.all {
            if let index = board.sources.firstIndex(where: { $0.id == source.config.id }) {
                board.sources[index] = source.config
            }
        }
        touch()
    }

    /// One source out of the show and off the board, the way Option Shift S
    /// removes one, and everything that was reading it put right. Saved on
    /// the spot, because a removal that waits for the window to close is one a
    /// crash undoes.
    @discardableResult
    func removeSource(id: String) -> Bool {
        guard sourceGroup.forget(id: id, on: board) else { return false }
        // A send leaving this one out now leaves out nothing, which
        // `sendReport` says; the taps follow what is still on.
        syncSend()
        group.syncTaps()
        touch()
        updateStatusLine()
        return true
    }

    /// Option Command M. Every extra source at once, off and back on.
    ///
    /// Not the microphone: that is Command M and it is a different thing, an
    /// open sound card rather than a gain. This is the key for the guest's
    /// laptop, the phone line or the desk feed all going quiet in one press,
    /// with the music and the pads untouched.
    func toggleSourceMute() {
        let sources = sourceGroup.all
        guard !sources.isEmpty else {
            speaker.announceState("There are no extra sources to mute. "
                                  + "Option Shift S adds one, and Command M is the microphone")
            return
        }
        // Anything still open means the press is a mute. It takes two presses
        // to unmute a half muted desk, and that is the right way round: the
        // first press is the one you make in a hurry.
        let muting = sources.contains { !$0.config.muted }
        for source in sources { source.config.muted = muting }
        for source in sources {
            if let index = board.sources.firstIndex(where: { $0.id == source.config.id }) {
                board.sources[index] = source.config
            }
        }
        let n = sources.count
        let word = n == 1 ? "\(sources[0].config.name)" : "all \(n) sources"
        speaker.announceState(muting ? "\(word) muted" : "\(word) unmuted")
        updateStatusLine()
        touch()
    }

    /// Option Command S. Just me, and back.
    ///
    /// Solo is on the source sum only, so the music and the running order carry
    /// on: this is "take every other input off the air", not "stop the show".
    /// Pressed with a solo already set it drops it, whatever was soloed, so the
    /// key always has a way back.
    func toggleSolo() {
        if let soloed = sourceGroup.soloed {
            sourceGroup.soloed = nil
            let name = soloed == micDuckKey ? "The microphone"
                     : (sourceGroup.source(id: soloed)?.config.name ?? "That source")
            speaker.announceState("\(name) no longer soloed. Every source is back")
            updateStatusLine()
            return
        }
        guard mic.isOpen else {
            speaker.announceState("The microphone is off, so there is nothing to solo it over. "
                                  + "Command M opens it, and Option Command C solos any source")
            return
        }
        sourceGroup.soloed = micDuckKey
        speaker.announceState("Microphone soloed. Every other source is silent, "
                              + "and the music carries on")
        updateStatusLine()
    }

    // ------------------------------------------------------- global hotkeys ---

    /// Command G arms and disarms the whole set.
    func toggleGlobalHotkeys() {
        if hotkeys.enabled {
            hotkeys.unregisterAll()
            board.globalHotkeysOn = false
            speaker.announceState("Global hotkeys off. Other programs have those keys back.")
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
        speaker.announceState(line)
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
