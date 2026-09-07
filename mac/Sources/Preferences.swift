// Preferences, and the window that proves what the keyboard really does.
//
// Eight tabs, the same eight the Windows copy has. Every field carries its own
// accessibility label, so the MSAA discipline of building each static text
// BEFORE its control, which most of dialogs.py is shaped around, is simply not
// needed here and a field cannot inherit the name of the row above it.
//
// The keyboard check is the Mac counterpart of tools/check_keyboard.py, and it
// is here rather than in a test for the same reason: some things can only be
// tested with a real keystroke. Whether VoiceOver hands a combination to this
// app is not knowable from any documentation, and calling the handler by hand
// proves nothing at all. So the app asks you to press the key and tells you
// exactly what arrived.

import AppKit
import Carbon.HIToolbox

extension MainWindow {

    func showPreferences(tab wanted: String? = nil) {
        let alert = NSAlert()
        alert.messageText = "Preferences"
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")

        let tabs = SettingsCategories()

        let outputs = AudioDevices.outputs()
        let inputs = AudioDevices.inputs()

        // ------------------------------------------------------------ output --
        let outputBox = stack()
        let devicePopup = NSPopUpButton()
        devicePopup.setAccessibilityLabel("Main output")
        devicePopup.addItem(withTitle: "System default output")
        for d in outputs { devicePopup.addItem(withTitle: d.name) }
        if let uid = board.deviceUID, let match = outputs.firstIndex(where: { $0.uid == uid }) {
            devicePopup.selectItem(at: match + 1)
        }
        outputBox.addArrangedSubview(field("Main output", devicePopup))
        outputBox.addArrangedSubview(note(
            "Leave a bank on the main output unless you want it on a separate channel of "
            + "your mixer. Ducking still works across outputs, and so does the stream: the "
            + "encoder takes the sum of everything whatever card it went to."))

        var bankPopups: [Int: NSPopUpButton] = [:]
        for bank in 1...C.bankCount {
            let popup = NSPopUpButton()
            popup.setAccessibilityLabel("\(board.bankName(bank)) output")
            popup.addItem(withTitle: "Main output")
            for d in outputs { popup.addItem(withTitle: d.name) }
            if let uid = board.bankDevices[bank],
               let match = outputs.firstIndex(where: { $0.uid == uid }) {
                popup.selectItem(at: match + 1)
            }
            bankPopups[bank] = popup
            outputBox.addArrangedSubview(field("\(board.bankName(bank)) output", popup))
        }
        add(tabs, "Output", outputBox)

        // --------------------------------------------------- sounds and beds --
        let soundsBox = stack()
        let duckSlider = slider(Double(board.duckDB), -24, 0, 25, "How far the beds duck, in decibels")
        soundsBox.addArrangedSubview(field("How far the beds duck, in decibels", duckSlider))
        let fadeIn = text(String(format: "%.2f", board.bedFadeIn), "Bed fade in, seconds")
        soundsBox.addArrangedSubview(field("Bed fade in, seconds", fadeIn))
        let fadeOut = text(String(format: "%.2f", board.bedFadeOut), "Bed fade out, seconds")
        soundsBox.addArrangedSubview(field("Bed fade out, seconds", fadeOut))
        soundsBox.addArrangedSubview(note(
            "Zero is a real setting and means the bed plays exactly as recorded. A bed cued "
            + "on its first beat cannot ease in. Up to \(Int(C.maxBedFade)) seconds."))
        let stopPopup = NSPopUpButton()
        stopPopup.setAccessibilityLabel("Presses of Escape to stop everything")
        for n in C.minStopPresses...C.maxStopPresses {
            stopPopup.addItem(withTitle: n == 1 ? "1 press" : "\(n) presses")
        }
        stopPopup.selectItem(at: board.stopPresses - C.minStopPresses)
        soundsBox.addArrangedSubview(field("Presses of Escape to stop everything", stopPopup))
        let fadeStopBox = check("Fade when stopping, rather than cutting dead", board.stopFade)
        soundsBox.addArrangedSubview(fadeStopBox)
        add(tabs, "Sounds and beds", soundsBox)

        // ---------------------------------------------------------- playlist --
        let playlistBox = stack()
        let crossfade = text(String(format: "%.1f", board.playlist.crossfade),
                             "Crossfade between tracks, seconds")
        playlistBox.addArrangedSubview(field("Crossfade between tracks, seconds", crossfade))
        let warnBox = check("Beep before a track ends", board.warnBeforeEnd)
        playlistBox.addArrangedSubview(warnBox)
        let warnSeconds = text(String(format: "%.0f", board.warnSeconds),
                               "How many seconds before the end")
        playlistBox.addArrangedSubview(field("How many seconds before the end", warnSeconds))
        let cuePopup = NSPopUpButton()
        cuePopup.setAccessibilityLabel("Which sound")
        for cue in C.cueSounds { cuePopup.addItem(withTitle: cue.label) }
        cuePopup.selectItem(at: C.cueSounds.firstIndex { $0.key == board.cueSound } ?? 0)
        playlistBox.addArrangedSubview(field("Which sound", cuePopup))
        let cueLevel = slider(Double(board.cueLevelDB), Double(C.minCueLevelDB),
                              Double(C.maxCueLevelDB), 31, "How loud the beep is, in decibels")
        playlistBox.addArrangedSubview(field("How loud the beep is, in decibels", cueLevel))
        playlistBox.addArrangedSubview(note(
            "The beep goes where you hear yourself, so it stays out of the show. It never "
            + "reaches the stream or a recording."))
        let monitorOnlyBox = check("The playlist fader only changes what YOU hear",
                                   board.playlistMonitorOnly)
        playlistBox.addArrangedSubview(monitorOnlyBox)
        playlistBox.addArrangedSubview(note(
            "On by default. Pull the music down in your own ears to hear your screen reader "
            + "and the listener hears no such thing, which is what a desk does. Turn it off "
            + "to make F7 and F8 change the level on air too."))
        add(tabs, "Playlist", playlistBox)

        // -------------------------------------------------------- microphone --
        let micBox = stack()
        let micPopup = NSPopUpButton()
        micPopup.setAccessibilityLabel("Microphone")
        micPopup.addItem(withTitle: "Default input")
        for d in inputs { micPopup.addItem(withTitle: d.name) }
        if let uid = board.micDeviceUID, let match = inputs.firstIndex(where: { $0.uid == uid }) {
            micPopup.selectItem(at: match + 1)
        }
        micBox.addArrangedSubview(field("Microphone", micPopup))

        let micChannelPopup = NSPopUpButton()
        micChannelPopup.setAccessibilityLabel("Which channel")
        for c in MicChannel.allCases { micChannelPopup.addItem(withTitle: c.label) }
        micChannelPopup.selectItem(at: MicChannel.allCases.firstIndex(of: board.micChannel) ?? 0)
        micBox.addArrangedSubview(field("Which channel", micChannelPopup))

        let micGain = slider(Double(board.micGainDB), Double(C.minMicGainDB),
                             Double(C.maxMicGainDB), 49, "Microphone gain, in decibels")
        micBox.addArrangedSubview(field("Microphone gain, in decibels", micGain))

        let micMonitorBox = check("Hear yourself", board.micMonitor)
        micBox.addArrangedSubview(micMonitorBox)
        let micOutputPopup = NSPopUpButton()
        micOutputPopup.setAccessibilityLabel("Hear yourself through")
        micOutputPopup.addItem(withTitle: "The main output")
        for d in outputs { micOutputPopup.addItem(withTitle: d.name) }
        if let uid = board.micOutputUID, let match = outputs.firstIndex(where: { $0.uid == uid }) {
            micOutputPopup.selectItem(at: match + 1)
        }
        micBox.addArrangedSubview(field("Hear yourself through", micOutputPopup))
        micBox.addArrangedSubview(note(
            "Nothing opens your microphone but pressing Command M. The device, the gain and "
            + "whether you want to hear yourself are remembered; whether it was on is not."))
        add(tabs, "Microphone", micBox)

        // ------------------------------------------------------------- voice --
        //
        // Every parameter is a row in a list, in plain words with real units,
        // read out as you change it. That is what makes a chain somebody
        // cannot see usable, and it is the same shape a plugin would get.
        let voiceBox = stack()
        let voiceOnBox = check("Process my voice", board.voiceOn)
        voiceBox.addArrangedSubview(voiceOnBox)
        let voiceList = VoiceParameterList(chain: mic.chain, speaker: speaker)
        voiceBox.addArrangedSubview(field("Voice settings", voiceList.view))
        voiceBox.addArrangedSubview(note(
            "Left and right arrows change the setting you are on, and hold Shift to move ten "
            + "at a time. A gate, a high pass filter, a three band equaliser, a compressor "
            + "and a ceiling, in that order."))
        add(tabs, "Voice", voiceBox)

        // --------------------------------------------------------- streaming --
        let streamBox = stack()
        let serverPopup = NSPopUpButton()
        serverPopup.setAccessibilityLabel("What kind of server")
        for key in C.streamServers {
            serverPopup.addItem(withTitle: C.streamServerLabels[key] ?? key)
        }
        serverPopup.selectItem(at: C.streamServers.firstIndex(of: board.stream.server) ?? 0)
        streamBox.addArrangedSubview(field("What kind of server", serverPopup))

        let hostField = text(board.stream.host, "Address")
        streamBox.addArrangedSubview(field("Address", hostField))
        let portField = text("\(board.stream.port)", "Port")
        streamBox.addArrangedSubview(field("Port", portField))
        let mountField = text(board.stream.mount, "Mount point")
        streamBox.addArrangedSubview(field("Mount point", mountField))
        let userField = text(board.stream.user, "User name")
        streamBox.addArrangedSubview(field("User name", userField))
        let passwordField = NSSecureTextField(string: board.stream.password)
        passwordField.setAccessibilityLabel("Password")
        streamBox.addArrangedSubview(field("Password", passwordField))

        let streamFormatPopup = NSPopUpButton()
        streamFormatPopup.setAccessibilityLabel("Send as")
        for key in C.streamFormatKeys {
            streamFormatPopup.addItem(withTitle: C.streamFormatLabels[key] ?? key)
        }
        streamFormatPopup.selectItem(
            at: C.streamFormatKeys.firstIndex(of: board.stream.format) ?? 0)
        streamBox.addArrangedSubview(field("Send as", streamFormatPopup))

        let bitratePopup = NSPopUpButton()
        bitratePopup.setAccessibilityLabel("Bit rate")
        for b in C.streamBitrates { bitratePopup.addItem(withTitle: "\(b) kbps") }
        bitratePopup.selectItem(at: C.streamBitrates.firstIndex(of: board.stream.bitrate) ?? 2)
        streamBox.addArrangedSubview(field("Bit rate", bitratePopup))
        streamBox.addArrangedSubview(note(
            "AAC is what most Icecast and SHOUTcast mounts take. Opus in Ogg sounds better at "
            + "half the bitrate and is what Icecast recommends now; an Ogg mount wants it. WAV "
            + "is uncompressed and has no bit rate: it is for a relay or for feeding another "
            + "encoder, not for an audience, because anyone who joins part way through a WAV "
            + "stream misses the header and hears nothing.\n\n"
            + "MP3 is not offered, and that is not an oversight. macOS has no MP3 encoder at "
            + "any layer: it decodes MP3 and cannot write it. Sending MP3 from a Mac needs a "
            + "third party encoder inside the app, which is a licensing decision rather than "
            + "a missing feature. A station saved on Windows that names MP3 comes in here as "
            + "AAC so it can still go on air."))

        let nameField = text(board.stream.name, "Station name")
        streamBox.addArrangedSubview(field("Station name", nameField))
        let genreField = text(board.stream.genre, "Genre")
        streamBox.addArrangedSubview(field("Genre", genreField))
        let statsField = text(board.stream.statsURL, "Where to ask who is listening")
        streamBox.addArrangedSubview(field("Where to ask who is listening", statsField))
        streamBox.addArrangedSubview(note(
            "Leave that empty and it asks the server you send to. Fill it in when the server "
            + "people listen on is a different one."))
        let publicBox = check("List this station publicly", board.stream.isPublic)
        streamBox.addArrangedSubview(publicBox)
        let micAirBox = check("Send the microphone as well", board.stream.sendMic)
        streamBox.addArrangedSubview(micAirBox)
        let titlesBox = check("Send what is playing", board.stream.sendTitles)
        streamBox.addArrangedSubview(titlesBox)

        // More than one station, because Tony runs two and retyping an address
        // and a password to move between them is the friction that stops you
        // bothering. Saving or forgetting one is a deliberate act and survives
        // Cancel, so the board is marked dirty on the spot.
        let stationPopup = NSPopUpButton()
        stationPopup.setAccessibilityLabel("Saved stations")
        let fillStations = { [board] in
            stationPopup.removeAllItems()
            let names = board.stationNames
            if names.isEmpty {
                stationPopup.addItem(withTitle: "No stations saved yet")
                stationPopup.item(at: 0)?.isEnabled = false
            } else {
                for name in names { stationPopup.addItem(withTitle: name) }
                if let at = names.firstIndex(of: board.stream.name) { stationPopup.selectItem(at: at) }
            }
        }
        fillStations()
        let stationControls = StationControls()
        stationControls.onPick = { [weak self, board] in
            guard let self, let name = stationPopup.titleOfSelectedItem,
                  board.loadStation(name) else { return }
            serverPopup.selectItem(at: C.streamServers.firstIndex(of: board.stream.server) ?? 0)
            hostField.stringValue = board.stream.host
            portField.stringValue = "\(board.stream.port)"
            mountField.stringValue = board.stream.mount
            userField.stringValue = board.stream.user
            passwordField.stringValue = board.stream.password
            streamFormatPopup.selectItem(
                at: C.streamFormatKeys.firstIndex(of: board.stream.format) ?? 0)
            bitratePopup.selectItem(at: C.streamBitrates.firstIndex(of: board.stream.bitrate) ?? 2)
            nameField.stringValue = board.stream.name
            genreField.stringValue = board.stream.genre
            statsField.stringValue = board.stream.statsURL
            publicBox.state = board.stream.isPublic ? .on : .off
            micAirBox.state = board.stream.sendMic ? .on : .off
            titlesBox.state = board.stream.sendTitles ? .on : .off
            self.speaker.announce("Loaded \(name).")
        }
        stationControls.onSave = { [weak self, board] in
            guard let self else { return }
            let name = nameField.stringValue.trimmingCharacters(in: .whitespaces)
            guard !name.isEmpty else {
                self.speaker.announce("Give the station a name first, in Station name.")
                nameField.window?.makeFirstResponder(nameField)
                return
            }
            board.stream.server = C.streamServers[max(0, serverPopup.indexOfSelectedItem)]
            board.stream.host = hostField.stringValue.trimmingCharacters(in: .whitespaces)
            board.stream.port = Int(portField.stringValue) ?? 8000
            board.stream.mount = mountField.stringValue.trimmingCharacters(in: .whitespaces)
            board.stream.user = userField.stringValue.trimmingCharacters(in: .whitespaces)
            board.stream.password = passwordField.stringValue
            board.stream.format = C.streamFormatKeys[
                max(0, min(C.streamFormatKeys.count - 1,
                           streamFormatPopup.indexOfSelectedItem))]
            board.stream.bitrate = C.streamBitrates[max(0, bitratePopup.indexOfSelectedItem)]
            board.stream.name = name
            board.stream.genre = genreField.stringValue
            board.stream.statsURL = statsField.stringValue.trimmingCharacters(in: .whitespaces)
            board.stream.isPublic = publicBox.state == .on
            board.stream.sendMic = micAirBox.state == .on
            board.stream.sendTitles = titlesBox.state == .on
            board.saveStation(name)
            fillStations()
            self.speaker.announce("Saved \(name).")
        }
        stationControls.onForget = { [weak self, board] in
            guard let self, let name = stationPopup.titleOfSelectedItem else { return }
            guard board.forgetStation(name) else {
                self.speaker.announce("There is nothing saved by that name.")
                return
            }
            fillStations()
            self.speaker.announce("Forgot \(name).")
        }
        stationControls.onTest = { [weak self] in
            guard let self else { return }
            var trial = StreamSettings()
            trial.server = C.streamServers[max(0, serverPopup.indexOfSelectedItem)]
            trial.host = hostField.stringValue.trimmingCharacters(in: .whitespaces)
            trial.port = Int(portField.stringValue) ?? 8000
            trial.mount = mountField.stringValue.trimmingCharacters(in: .whitespaces)
            trial.user = userField.stringValue.trimmingCharacters(in: .whitespaces)
            trial.password = passwordField.stringValue
            trial.bitrate = C.streamBitrates[max(0, bitratePopup.indexOfSelectedItem)]
            trial.name = nameField.stringValue
            trial.genre = genreField.stringValue
            trial.isPublic = publicBox.state == .on
            self.speaker.announce("Testing \(trial.host.isEmpty ? "the connection" : trial.host)")
            DispatchQueue.global(qos: .userInitiated).async {
                let verdict = Streamer.testConnection(trial)
                DispatchQueue.main.async {
                    self.speaker.announce(verdict)
                    self.say("Test the connection", verdict)
                }
            }
        }
        stationPopup.target = stationControls
        stationPopup.action = #selector(StationControls.pick)
        streamBox.addArrangedSubview(field("Saved stations", stationPopup))
        streamBox.addArrangedSubview(note(
            "Pick one to load its settings into the boxes above. Save this station remembers "
            + "whatever is in the boxes under the station name, and the On air menu, Station, "
            + "switches between them without coming in here."))
        let saveStation = NSButton(title: "Save this station", target: stationControls,
                                   action: #selector(StationControls.save))
        saveStation.bezelStyle = .rounded
        let forgetStation = NSButton(title: "Forget this station", target: stationControls,
                                     action: #selector(StationControls.forget))
        forgetStation.bezelStyle = .rounded
        let testButton = NSButton(title: "Test the connection", target: stationControls,
                                  action: #selector(StationControls.test))
        testButton.bezelStyle = .rounded
        testButton.toolTip = "Connects with the settings above, says what the server answered, "
                           + "and disconnects. It sends no audio."
        let stationRow = NSStackView(views: [saveStation, forgetStation, testButton])
        stationRow.orientation = .horizontal
        stationRow.spacing = 8
        streamBox.addArrangedSubview(stationRow)
        add(tabs, "Streaming", streamBox)

        // --------------------------------------------------------- recording --
        let recordBox = stack()
        let formatPopup = NSPopUpButton()
        formatPopup.setAccessibilityLabel("Record as")
        for key in C.recordFormatKeys {
            formatPopup.addItem(withTitle: C.recordFormatLabels[key] ?? key)
        }
        formatPopup.selectItem(at: C.recordFormatKeys.firstIndex(of: board.recordFormat) ?? 0)
        recordBox.addArrangedSubview(field("Record as", formatPopup))
        let recordBitrate = NSPopUpButton()
        recordBitrate.setAccessibilityLabel("Bit rate, for AAC")
        for b in C.streamBitrates { recordBitrate.addItem(withTitle: "\(b) kbps") }
        recordBitrate.selectItem(at: C.streamBitrates.firstIndex(of: board.recordBitrate) ?? 4)
        recordBox.addArrangedSubview(field("Bit rate, for AAC", recordBitrate))
        let folderField = text(board.recordFolder ?? Recorder.defaultFolder(),
                               "Where recordings go")
        recordBox.addArrangedSubview(field("Where recordings go", folderField))
        recordBox.addArrangedSubview(note(
            "A recording is the same mix that goes on air: every sound card, the running "
            + "order, the microphone if it is on air. Never your preview and never the beep "
            + "before a track ends. It does not need you to be on air."))
        add(tabs, "Recording", recordBox)

        // ---------------------------------------------------------- keyboard --
        let keyBox = stack()
        let schemePopup = NSPopUpButton()
        schemePopup.setAccessibilityLabel("Which keys fire banks 2 and 3")
        schemePopup.addItem(withTitle: "Command, the Mac translation (recommended)")
        schemePopup.addItem(withTitle: "Control and Option, exactly as Windows")
        schemePopup.selectItem(at: KeyMap.scheme == .command ? 0 : 1)
        keyBox.addArrangedSubview(field("Which keys fire banks 2 and 3", schemePopup))
        keyBox.addArrangedSubview(note(
            "The Windows copy uses Control for the drops and Option plus Control for the "
            + "beds. On a Mac, Control plus Option is VoiceOver's own modifier: VoiceOver "
            + "takes those combinations for its hot spots before this app sees them, so the "
            + "beds bank would not work. Control plus a digit is also how macOS switches "
            + "desktops. Choose the Windows keys only if you have moved VoiceOver's modifier "
            + "to Caps Lock and turned the desktop shortcuts off. Help, Check the keyboard, "
            + "will tell you what actually arrives."))
        let hotkeyBox = check("Global hotkeys on", board.globalHotkeysOn)
        keyBox.addArrangedSubview(hotkeyBox)
        keyBox.addArrangedSubview(note(
            "A global hotkey fires a sound while another program has focus, and always needs "
            + "a modifier: a bare key would be taken away from everything else on the Mac."))
        add(tabs, "Keyboard", keyBox)

        // ------------------------------------------------------------ speech --
        let speechBox = stack()
        let speechPopup = NSPopUpButton()
        speechPopup.setAccessibilityLabel("Spoken feedback from the app")
        for label in C.speechLabels { speechPopup.addItem(withTitle: label) }
        speechPopup.selectItem(at: C.speechLevels.firstIndex(of: board.speechLevel) ?? 0)
        speechBox.addArrangedSubview(field("Spoken feedback from the app", speechPopup))
        let playbackBox = check("Say the name when a sound starts or stops",
                                board.announcePlayback)
        speechBox.addArrangedSubview(playbackBox)
        speechBox.addArrangedSubview(note(
            "The line at the bottom of the window shows everything at every level, so nothing "
            + "this app has to say is ever only spoken."))
        add(tabs, "Speech", speechBox)

        tabs.select(wanted ?? "Output")
        alert.accessoryView = tabs.view
        alert.window.initialFirstResponder = tabs.list

        // The Voice tab changes the live chain as you move, so Cancel has to
        // put it back.
        let voiceBefore = mic.chain.settings
        guard alert.runModal() == .alertFirstButtonReturn else {
            mic.chain.settings = voiceBefore
            speaker.announceHelp("Nothing changed")
            // A station saved or forgotten on the Streaming tab is a deliberate
            // act and survives Cancel, so the board still has to reach the disk.
            if board.dirty { touch() }
            updateAirMenu()
            return
        }

        // ------------------------------------------------------------ applying --
        var deviceChanged = false
        let chosen = devicePopup.indexOfSelectedItem
        let newUID = chosen == 0 ? nil : outputs[chosen - 1].uid
        if newUID != board.deviceUID {
            board.deviceUID = newUID
            board.deviceName = chosen == 0 ? nil : outputs[chosen - 1].name
            deviceChanged = true
        }
        for (bank, popup) in bankPopups {
            let i = popup.indexOfSelectedItem
            let uid = i == 0 ? nil : outputs[i - 1].uid
            if uid != board.bankDevices[bank] {
                if let uid { board.bankDevices[bank] = uid }
                else { board.bankDevices.removeValue(forKey: bank) }
                deviceChanged = true
            }
        }

        board.duckDB = Float(duckSlider.doubleValue.rounded())
        board.bedFadeIn = Board.fade(Double(fadeIn.stringValue), fallback: board.bedFadeIn)
        board.bedFadeOut = Board.fade(Double(fadeOut.stringValue), fallback: board.bedFadeOut)
        board.stopPresses = stopPopup.indexOfSelectedItem + C.minStopPresses
        board.stopFade = fadeStopBox.state == .on

        if let value = Double(crossfade.stringValue) {
            board.playlist.crossfade = min(C.maxCrossfade, max(0, value))
        }
        board.warnBeforeEnd = warnBox.state == .on
        if let value = Double(warnSeconds.stringValue) {
            board.warnSeconds = min(C.maxWarnSeconds, max(C.minWarnSeconds, value))
        }
        board.cueSound = C.cueSounds[max(0, cuePopup.indexOfSelectedItem)].key
        board.cueLevelDB = Float(cueLevel.doubleValue.rounded())
        board.playlistMonitorOnly = monitorOnlyBox.state == .on
        player.warnBeforeEnd = board.warnBeforeEnd
        player.warnSeconds = board.warnSeconds
        for m in group.mixers.values { m.playlistMonitorOnly = board.playlistMonitorOnly }

        let micIndex = micPopup.indexOfSelectedItem
        board.micDeviceUID = micIndex == 0 ? nil : inputs[micIndex - 1].uid
        board.micDeviceName = micIndex == 0 ? nil : inputs[micIndex - 1].name
        board.micChannel = MicChannel.allCases[max(0, micChannelPopup.indexOfSelectedItem)]
        board.micGainDB = Float(micGain.doubleValue.rounded())
        board.micMonitor = micMonitorBox.state == .on
        let micOut = micOutputPopup.indexOfSelectedItem
        board.micOutputUID = micOut == 0 ? nil : outputs[micOut - 1].uid
        mic.gainDB = board.micGainDB
        mic.channel = board.micChannel
        mic.monitorWanted = board.micMonitor
        board.voiceOn = voiceOnBox.state == .on
        board.voiceSettings = mic.chain.settings

        board.stream.server = C.streamServers[max(0, serverPopup.indexOfSelectedItem)]
        board.stream.host = hostField.stringValue.trimmingCharacters(in: .whitespaces)
        board.stream.port = Int(portField.stringValue) ?? 8000
        board.stream.mount = mountField.stringValue.trimmingCharacters(in: .whitespaces)
        board.stream.user = userField.stringValue.trimmingCharacters(in: .whitespaces)
        board.stream.password = passwordField.stringValue
        board.stream.bitrate = C.streamBitrates[max(0, bitratePopup.indexOfSelectedItem)]
        board.stream.name = nameField.stringValue
        board.stream.genre = genreField.stringValue
        board.stream.statsURL = statsField.stringValue.trimmingCharacters(in: .whitespaces)
        board.stream.isPublic = publicBox.state == .on
        board.stream.sendMic = micAirBox.state == .on
        board.stream.sendTitles = titlesBox.state == .on
        mic.onAir = board.stream.sendMic

        board.recordFormat = C.recordFormatKeys[max(0, formatPopup.indexOfSelectedItem)]
        board.stream.format = C.streamFormatKeys[
            max(0, min(C.streamFormatKeys.count - 1, streamFormatPopup.indexOfSelectedItem))]
        board.recordBitrate = C.streamBitrates[max(0, recordBitrate.indexOfSelectedItem)]
        let folder = folderField.stringValue.trimmingCharacters(in: .whitespaces)
        board.recordFolder = folder.isEmpty ? nil : folder

        let wantScheme: BankScheme = schemePopup.indexOfSelectedItem == 0 ? .command : .literal
        let schemeChanged = wantScheme != KeyMap.scheme
        KeyMap.scheme = wantScheme
        board.bankScheme = wantScheme
        if (hotkeyBox.state == .on) != hotkeys.enabled {
            if hotkeyBox.state == .on { armGlobalHotkeys(announce: false) }
            else { hotkeys.unregisterAll(); board.globalHotkeysOn = false }
        }

        board.speechLevel = C.speechLevels[speechPopup.indexOfSelectedItem]
        board.announcePlayback = playbackBox.state == .on
        speaker.level = board.speechLevel
        speaker.playbackEnabled = board.announcePlayback

        group.apply(board)
        if deviceChanged {
            group.stopAll(fadeOut: 0.0)
            group.rebuild(mainDeviceUID: board.deviceUID, bankDevices: board.bankDevices)
            group.apply(board)
            group.start()
            group.primary.airSource = sourceGroup
            group.primary.monitorSource = sourceMonitor
            for m in group.mixers.values { m.playlistMonitorOnly = board.playlistMonitorOnly }
            group.warmCache(board)
        }
        if schemeChanged { refreshAllPads() }
        playlistView.refresh(rowsChanged: false)
        updateStatusLine()
        touch()

        var line = "Preferences saved"
        if deviceChanged {
            line += ". Everything playing through "
                 + (board.deviceName ?? "the system default output")
        }
        if schemeChanged {
            line += ". Banks 2 and 3 now fire on \(KeyMap.bank2Spoken) and \(KeyMap.bank3Spoken)"
        }
        line += ". " + micSummary()
        speaker.announce(line)
    }

    // ------------------------------------------------------ keyboard check ---

    /// Press a key, and be told exactly what reached the app.
    ///
    /// Whether VoiceOver hands a combination through is not knowable from
    /// documentation, and it differs with the user's own VoiceOver settings.
    /// So this asks the machine in front of you rather than guessing.
    func showKeyboardCheck() {
        let panel = KeyboardCheckPanel()
        panel.run(speaker: speaker)
    }

    // ------------------------------------------------------------- helpers ---

    private func add(_ tabs: SettingsCategories, _ label: String, _ box: NSStackView) {
        tabs.add(label, wrap(box))
    }

    private func stack() -> NSStackView {
        let s = NSStackView()
        s.orientation = .vertical
        s.alignment = .leading
        s.spacing = 8
        s.edgeInsets = NSEdgeInsets(top: 12, left: 14, bottom: 12, right: 14)
        return s
    }

    private func wrap(_ box: NSStackView) -> NSView {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.drawsBackground = false
        scroll.documentView = box
        return scroll
    }

    private func note(_ words: String) -> NSTextField {
        let t = NSTextField(wrappingLabelWithString: words)
        t.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        t.textColor = .secondaryLabelColor
        t.preferredMaxLayoutWidth = 560
        return t
    }

    private func text(_ value: String, _ label: String) -> NSTextField {
        let f = NSTextField(string: value)
        f.setAccessibilityLabel(label)
        return f
    }

    private func check(_ title: String, _ on: Bool) -> NSButton {
        let b = NSButton(checkboxWithTitle: title, target: nil, action: nil)
        b.state = on ? .on : .off
        b.setAccessibilityLabel(title)
        return b
    }

    private func slider(_ value: Double, _ minimum: Double, _ maximum: Double,
                        _ ticks: Int, _ label: String) -> NSSlider {
        let s = NSSlider(value: value, minValue: minimum, maxValue: maximum,
                         target: nil, action: nil)
        s.numberOfTickMarks = ticks
        s.allowsTickMarkValuesOnly = true
        s.setAccessibilityLabel(label)
        return s
    }

    private func field(_ label: String, _ control: NSView) -> NSView {
        let text = NSTextField(labelWithString: label)
        text.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        text.textColor = .secondaryLabelColor
        let s = NSStackView(views: [text, control])
        s.orientation = .vertical
        s.alignment = .leading
        s.spacing = 2
        control.widthAnchor.constraint(greaterThanOrEqualToConstant: 420).isActive = true
        return s
    }
}

// ---------------------------------------------------------- station buttons ---

/// The three station controls on the Streaming tab need a target that outlives
/// the click. Closures set by the window; nothing else.
final class StationControls: NSObject {
    var onPick: (() -> Void)?
    var onSave: (() -> Void)?
    var onForget: (() -> Void)?
    var onTest: (() -> Void)?
    @objc func pick() { onPick?() }
    @objc func save() { onSave?() }
    @objc func forget() { onForget?() }
    @objc func test() { onTest?() }
}

// ------------------------------------------------------- the voice as a list ---

/// Every parameter of the voice chain as a row you can arrow through.
///
/// This is the thing that makes a chain usable without seeing it, and it is the
/// same shape a hosted plugin would get: a name, a value, a real unit, spoken
/// as you change it. Left and right adjust; Shift moves ten steps.
final class VoiceParameterList: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private let chain: MicChain
    private let speaker: Speaker
    private let table = NSTableView()
    private let scroll = NSScrollView()
    private var monitor: Any?

    var view: NSView { scroll }

    init(chain: MicChain, speaker: Speaker) {
        self.chain = chain
        self.speaker = speaker
        super.init()

        for (id, title, width) in [("group", "Section", 130), ("name", "Setting", 200),
                                   ("value", "Value", 150)] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id))
            column.title = title
            column.width = CGFloat(width)
            table.addTableColumn(column)
        }
        table.dataSource = self
        table.delegate = self
        table.setAccessibilityLabel("Voice settings")
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        scroll.frame = NSRect(x: 0, y: 0, width: 500, height: 200)
        scroll.heightAnchor.constraint(equalToConstant: 200).isActive = true
        table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)

        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown]) {
            [weak self] event in
            guard let self, self.table.window?.firstResponder === self.table
            else { return event }
            return self.handle(event) ? nil : event
        }
    }

    deinit { if let monitor { NSEvent.removeMonitor(monitor) } }

    private func handle(_ event: NSEvent) -> Bool {
        let row = table.selectedRow
        guard row >= 0, row < MicChain.parameters.count else { return false }
        let mods = event.modifierFlags.intersection([.command, .option, .control, .shift])
        guard mods.isEmpty || mods == .shift else { return false }
        let step: Double
        switch event.keyCode {
        case UInt16(kVK_LeftArrow): step = -1
        case UInt16(kVK_RightArrow): step = 1
        default: return false
        }
        let parameter = MicChain.parameters[row]
        // Ten at a time with Shift. Page Up and Page Down are deliberately left
        // to the list, so it can still be moved through quickly.
        let multiplier = mods == .shift ? 10.0 : 1.0
        let current = chain.value(parameter.key)
        chain.set(parameter.key, current + step * parameter.step * multiplier)
        table.reloadData(forRowIndexes: IndexSet(integer: row),
                         columnIndexes: IndexSet(integersIn: 0..<table.numberOfColumns))
        speaker.announceAnswer(parameter.spoken(chain.value(parameter.key)))
        return true
    }

    func numberOfRows(in tableView: NSTableView) -> Int { MicChain.parameters.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard let tableColumn, row < MicChain.parameters.count else { return nil }
        let parameter = MicChain.parameters[row]
        let value = chain.value(parameter.key)
        let text: String
        switch tableColumn.identifier.rawValue {
        case "group": text = parameter.group
        case "name": text = parameter.label
        default:
            if let choices = parameter.choices {
                text = choices[min(choices.count - 1, max(0, Int(value.rounded())))]
            } else if parameter.unit == "Hz" && value >= 1000 {
                text = String(format: "%.1f kHz", value / 1000)
            } else if parameter.unit == "ratio" {
                text = String(format: "%.1f to 1", value)
            } else if parameter.unit.isEmpty {
                text = String(format: "%.2f", value)
            } else {
                text = String(format: "%.1f %@", value, parameter.unit)
            }
        }
        let field = NSTextField(labelWithString: text)
        // The whole row is what a screen reader should read, so the value cell
        // carries the full sentence rather than a bare number.
        field.setAccessibilityLabel(tableColumn.identifier.rawValue == "value"
                                    ? parameter.spoken(value) : text)
        return field
    }
}

// ------------------------------------------------------ the settings layout ---

/// Categories down the left, the chosen category's settings beside them.
///
/// The same shape as VoiceOver Utility, and chosen for the same reason it is
/// the shape VoiceOver Utility uses: a list is one object with rows you arrow
/// through, and a tab view is a control you have to interact with before its
/// tabs exist at all. Eight tabs meant eight VO interactions to find out what
/// was in them. A list says where you are the moment you arrow onto it, and the
/// settings for that category are the very next thing in the Tab order.
///
/// Nothing here is a new preference. The tabs, their contents and the OK and
/// Cancel behaviour are exactly what they were; only the way you move between
/// them has changed.
final class SettingsCategories: NSObject, NSTableViewDataSource, NSTableViewDelegate {

    private(set) var labels: [String] = []
    private var panes: [NSView] = []

    let list = NSTableView()
    private let detail = NSView(frame: NSRect(x: 216, y: 0, width: 464, height: 420))
    private let box = NSView(frame: NSRect(x: 0, y: 0, width: 680, height: 420))
    private let heading = NSTextField(labelWithString: "")

    var view: NSView { box }

    override init() {
        super.init()

        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("category"))
        column.title = "Category"
        column.width = 190
        list.addTableColumn(column)
        list.headerView = nil
        list.rowHeight = 22
        list.dataSource = self
        list.delegate = self
        list.setAccessibilityLabel("Settings categories")
        list.allowsEmptySelection = false

        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 206, height: 420))
        scroll.documentView = list
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        box.addSubview(scroll)

        // The heading is what a sighted user reads to know which pane this is,
        // and what VoiceOver reads when it enters the pane, because the group
        // itself carries the same name.
        heading.frame = NSRect(x: 216, y: 396, width: 464, height: 20)
        heading.font = NSFont.boldSystemFont(ofSize: NSFont.systemFontSize)
        box.addSubview(heading)

        detail.frame = NSRect(x: 216, y: 0, width: 464, height: 392)
        box.addSubview(detail)
    }

    func add(_ label: String, _ pane: NSView) {
        labels.append(label)
        pane.frame = detail.bounds
        pane.autoresizingMask = [.width, .height]
        pane.setAccessibilityLabel("\(label) settings")
        panes.append(pane)
        list.reloadData()
    }

    func select(_ label: String) {
        let index = labels.firstIndex(of: label) ?? 0
        guard index < panes.count else { return }
        list.selectRowIndexes(IndexSet(integer: index), byExtendingSelection: false)
        show(index)
    }

    private func show(_ index: Int) {
        guard index >= 0, index < panes.count else { return }
        detail.subviews.forEach { $0.removeFromSuperview() }
        detail.addSubview(panes[index])
        heading.stringValue = labels[index]
        detail.setAccessibilityLabel("\(labels[index]) settings")
    }

    func numberOfRows(in tableView: NSTableView) -> Int { labels.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?,
                   row: Int) -> NSView? {
        guard row < labels.count else { return nil }
        let field = NSTextField(labelWithString: labels[row])
        field.setAccessibilityLabel(labels[row])
        return field
    }

    func tableViewSelectionDidChange(_ notification: Notification) {
        show(list.selectedRow)
    }
}
