// The frame's half of the video work: what the keys and the menu actually do.
//
// The panels are in VideoPanels.swift and know nothing about the show. This is
// where they are handed the board, the speaker and a way to change what is
// going out, and where Command B learns that there are two places a show can
// go.

import AppKit
import CoreVideo

extension MainWindow {

    /// What is playing, the way a listener would be told it.
    ///
    /// The card and the lower third both want this and they must agree, so it
    /// is asked for in one place rather than assembled twice.
    var nowPlayingTitle: String {
        guard let track = player?.currentTrack else { return "" }
        let artist = (track.artist ?? "").trimmingCharacters(in: .whitespaces)
        let title = (track.title ?? "").trimmingCharacters(in: .whitespaces)
        if !artist.isEmpty && !title.isEmpty { return "\(artist) - \(title)" }
        return title.isEmpty ? track.displayName : title
    }

    // ------------------------------------------------------ the settings ---

    /// What the picture needs, out of the board.
    ///
    /// **Deliberately separate from the destination's settings.** Windows
    /// keeps three dictionaries here and the reason is a bug that shipped in
    /// 3.5.0: reading the picture out of the destination's settings gives a
    /// board pointed at the radio station no picture key at all, so the shot
    /// check confidently described a card the user never chose.
    func pictureSettings() -> PictureSettings {
        var s = PictureSettings()
        s.picture = board.picture
        s.pictureFile = board.pictureFile
        s.pictureClock = board.pictureClock
        s.camera = board.camera
        s.screen = board.screen
        s.splitCorner = board.splitCorner
        s.name = board.stream.name
        s.streamName = board.stream.name
        s.title = nowPlayingTitle
        s.colourBackground = board.colourBackground
        s.colourText = board.colourText
        s.colourAccent = board.colourAccent
        s.videoWidth = board.videoWidth
        s.videoHeight = board.videoHeight
        s.videoFPS = board.videoFPS
        return s
    }

    func overlaySettings() -> OverlaySettings {
        var s = OverlaySettings()
        s.places = board.textPlaces
        s.name = board.stream.name
        s.streamName = board.stream.name
        s.colourBackground = board.colourBackground
        s.colourText = board.colourText
        return s
    }

    func videoStreamSettings() -> VideoStreamSettings {
        var s = VideoStreamSettings()
        s.server = board.videoServer
        s.host = board.videoHost
        s.key = Secrets.fetch(station: board.stream.name.isEmpty
                              ? board.videoServer : board.stream.name)
        s.width = board.videoWidth
        s.height = board.videoHeight
        s.fps = board.videoFPS
        s.videoBitrate = board.videoBitrate
        s.audioBitrate = board.stream.bitrate
        s.framingLevel = board.framingLevel
        s.overlay = overlaySettings()
        return s
    }

    /// The settings the pre-flight reads, which is what the streamer will see.
    func preflightSettings() -> PreflightSettings {
        var s = PreflightSettings()
        let video = board.liveTo == C.liveToVideo
        s.server = video ? board.videoServer : board.stream.server
        s.host = video ? board.videoHost : board.stream.host
        s.mount = video ? "" : board.stream.mount
        s.name = board.stream.name
        s.password = video ? videoStreamSettings().key : board.stream.password
        s.format = board.stream.format
        s.bitrate = board.stream.bitrate
        s.picture = board.picture
        s.pictureFile = board.pictureFile
        s.camera = board.camera
        s.streamName = board.stream.name
        s.videoWidth = board.videoWidth
        s.videoHeight = board.videoHeight
        s.videoFPS = board.videoFPS
        s.videoBitrate = board.videoBitrate
        return s
    }

    func preflightBoard() -> PreflightBoard {
        var b = PreflightBoard()
        b.liveTo = board.liveTo
        b.videoServer = board.videoServer
        b.streamMic = board.stream.sendMic
        b.streamTitles = board.stream.sendTitles
        b.textPlaces = board.textPlaces
        return b
    }

    /// Everything Command B is about to do, worked out before it does it.
    func preflight() -> Preflight {
        Preflighter.check(
            settings: preflightSettings(), board: preflightBoard(),
            audioRunning: group.isRunning, micOpen: mic.isOpen,
            screenReady: Screens.available(),
            screenReason: Screens.whyUnavailable(),
            text: Preflighter.TextFitting(
                placeLabel: { Overlays.placeLabel($0) },
                fits: { Overlays.fits($0, key: $1, width: $2, height: $3) }))
    }

    // ---------------------------------------------------------- the keys ---

    /// Refuse a picture window when Command B is pointed at the radio station.
    ///
    /// **A picture nobody will ever send is worse than no window**, because
    /// it answers confidently. The same silent-wrong-answer class as the 3.5.1
    /// fault, where the shot check described a card the user had not chosen.
    private func videoIsWhereItGoes() -> Bool {
        if board.liveTo == C.liveToVideo { return true }
        speaker.announceAnswer("Command B is set to go to your radio station, which "
                             + "sends no picture. Video streaming is in Preferences")
        return false
    }

    func showVideoSource() {
        guard videoIsWhereItGoes() else { return }
        let panel = VideoSourcePanel(
            board: board, speaker: speaker, live: videoStreamer.isOn,
            apply: { [weak self] kind in
                guard let self else { return "" }
                let was = self.board.picture
                self.board.picture = kind
                self.board.dirty = true
                guard self.videoStreamer.isOn else { return "" }
                let trouble = self.videoStreamer.setPicture(self.pictureSettings())
                if !trouble.isEmpty {
                    // The picture stays where it was, because a chosen source
                    // that did not open is not the one going out.
                    self.board.picture = was
                    _ = self.videoStreamer.setPicture(self.pictureSettings())
                }
                return trouble
            },
            applyCorner: { [weak self] _ in
                guard let self, self.videoStreamer.isOn,
                      self.board.picture == C.pictureSplit else { return }
                self.videoStreamer.setPicture(self.pictureSettings())
            })
        panel.run(over: window)
    }

    func showScreenText() {
        guard videoIsWhereItGoes() else { return }
        let panel = ScreenTextPanel(
            board: board, speaker: speaker, live: videoStreamer.isOn, window: window,
            ask: { [weak self] title, message, value, fieldLabel in
                self?.ask(title: title, message: message, value: value,
                          okTitle: "OK", fieldLabel: fieldLabel)
            },
            nowPlaying: { [weak self] in self?.nowPlayingTitle ?? "" },
            apply: { [weak self] in
                guard let self else { return }
                self.videoStreamer.setOverlay(self.overlaySettings())
            })
        panel.run(over: window)
    }

    func showColours() {
        let panel = ColoursPanel(
            board: board, speaker: speaker, window: window,
            sample: { [weak self] in self?.brandSample() },
            apply: { [weak self] in
                guard let self else { return }
                self.videoStreamer.setOverlay(self.overlaySettings())
                if self.videoStreamer.isOn {
                    self.videoStreamer.setPicture(self.pictureSettings())
                }
            })
        panel.run(over: window)
    }

    /// A real frame of the brand, with the overlay on it.
    ///
    /// Not a list of colour names: a model cannot judge what three names look
    /// like together any better than the person asking can.
    func brandSample() -> CVPixelBuffer? {
        var settings = pictureSettings()
        settings.picture = C.pictureCard
        settings.title = "What is playing right now"
        let card = Picture.build(settings)
        guard let frame = card.frame(width: board.videoWidth,
                                     height: board.videoHeight) else { return nil }
        let overlay = Overlay(settings: overlaySettings())
        overlay.setTitle(settings.title)
        return Pixels.composite(frame, overlay, width: board.videoWidth,
                                height: board.videoHeight)
    }

    /// The picture going out, or the one that would go out.
    ///
    /// **Checking after you are live is not checking**, so this builds the
    /// picture, looks at it and puts it away again when nothing is on the air.
    /// Never on the main queue: opening a camera blocks.
    func previewPicture() -> CVPixelBuffer? {
        if videoStreamer.isOn, let frame = videoStreamer.currentFrame() { return frame }
        let source = Picture.build(pictureSettings())
        source.start()
        // Closed whatever happens: a camera left open holds the device and
        // its light stays on.
        defer { source.close() }
        _ = source.waitReady(timeout: C.cameraOpenTimeout)
        let frame = source.frame(width: board.videoWidth, height: board.videoHeight)
        let overlay = Overlay(settings: overlaySettings())
        overlay.setTitle(nowPlayingTitle)
        return frame.map {
            Pixels.composite($0, overlay, width: board.videoWidth,
                             height: board.videoHeight)
        }
    }

    func showShotCheck() {
        // The kind decides whether consent is asked for, so it is read from
        // what the picture really is rather than passed around.
        let kind = C.pictureNeedsScreen.contains(board.picture) ? "screen" : "camera"
        let panel = ShotCheckPanel(board: board, speaker: speaker, window: window,
                                   kind: kind,
                                   grab: { [weak self] in self?.previewPicture() })
        panel.run(over: window)
    }

    /// What the camera can see. Answers at every talkativeness setting,
    /// including off: a switch that silences the announcements must not
    /// silence the answer to a direct question.
    func sayWhatTheCameraSees() {
        if videoStreamer.isOn {
            speaker.announceAnswer(videoStreamer.framer.describe())
            return
        }
        guard !board.camera.isEmpty else {
            speaker.announceAnswer("No camera has been chosen. Option Shift V picks one.")
            return
        }
        speaker.announce("Looking through the camera.")
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let camera = CameraSource(device: self.board.camera)
            camera.start()
            defer { camera.close() }
            guard camera.waitReady(timeout: C.cameraOpenTimeout),
                  let frame = camera.latestFrame() else {
                let why = camera.error.isEmpty ? "The camera did not answer" : camera.error
                DispatchQueue.main.async { self.speaker.announceAnswer(why) }
                return
            }
            let framer = Framer(level: self.board.framingLevel)
            let reading = framer.measure(frame)
            DispatchQueue.main.async { self.speaker.announceAnswer(reading.sentence()) }
        }
    }

    /// The picture, and everything on top of it, in words.
    ///
    /// **Nothing else in broadcasting does this.** A preview window is a
    /// graphics surface with no accessibility information at all, on any
    /// platform, so there is nothing anywhere that will tell the person making
    /// a stream what is currently in it.
    func sayWhatIsOnScreen() {
        var parts: [String] = []
        if videoStreamer.isOn {
            parts.append("On air, showing \(videoStreamer.describePicture())")
        } else if board.liveTo != C.liveToVideo {
            speaker.announceAnswer("Nothing. Command B is set to go to your radio "
                                 + "station, which sends no picture")
            return
        } else {
            let label = (C.pictureLabels[board.picture] ?? board.picture).lowercased()
            parts.append("\(label), once you go live")
        }
        let overlay = Overlay(settings: overlaySettings())
        overlay.setTitle(nowPlayingTitle)
        parts.append("On top of it: \(overlay.describe())")
        parts.append(Colours.describePair(front: board.colourText,
                                          back: board.colourBackground))
        speaker.announceAnswer(parts.joined(separator: ". "))
    }

    func showStreamHelp() {
        StreamHelpPanel(speaker: speaker).run(over: window)
    }

    /// Which of the two Command B sends the show to.
    func setLiveTo(_ which: String) {
        guard C.liveTo.contains(which) else { return }
        if streamer.isOn || videoStreamer.isOn {
            speaker.announce("Come off air first, Command B, then change where it goes")
            return
        }
        board.liveTo = which
        board.dirty = true
        let name = C.liveToLabels[which] ?? which
        // The pre-flight summary, so the answer is where it is going rather
        // than which of two words was picked.
        let report = preflight()
        var said = "Command B now goes to \(name), \(report.summary())"
        if report.blocked {
            said += ". " + report.stops.map { $0.text }.joined(separator: ". ")
        }
        speaker.announceState(said)
        updateAirMenu()
    }
}
