// Recording the picture as well as the sound, and the track list beside both.
//
// Command+R records the sound alone and is untouched. Command+Shift+R records
// the picture and the sound together into one MP4, and neither needs you to be
// on air.

import AppKit

extension MainWindow {

    /// Command+Shift+R. The picture and the sound, into one file.
    func toggleVideoRecording() {
        if videoRecorder.isRecording {
            videoRecorder.stop(taps: group.taps)
            group.syncTaps()
            speaker.announceState(videoRecorder.report())
            updateStatusLine()
            return
        }
        // Two recorders at once is legal and two recorders on one file is not,
        // so they are simply two files. The audio one is untouched by this.
        let live = videoStreamer.isOn
        let borrow: (() -> CVPixelBuffer?)? = live
            ? { [weak self] in self?.videoStreamer.currentFrame() }
            : nil
        let own: (() -> (PictureSource, Overlay))? = live ? nil : { [weak self] in
            guard let self else { return (Picture.build(PictureSettings()), Overlay()) }
            let source = Picture.build(self.pictureSettings(), onFallback: { [weak self] text in
                // The same sentence the stream would say. A source that fills
                // a canvas rather than failing is the whole reason anything
                // says this: nothing downstream will.
                DispatchQueue.main.async { self?.speaker.announce(text) }
            })
            let overlay = Overlay(settings: self.overlaySettings())
            overlay.setTitle(self.nowPlayingTitle)
            return (source, overlay)
        }
        guard let path = videoRecorder.start(
            taps: group.taps, rate: group.sampleRate,
            width: board.videoWidth, height: board.videoHeight, fps: board.videoFPS,
            folder: board.recordFolder, borrow: borrow, own: own) else {
            speaker.announceState("Recording the picture would not start. "
                + (videoRecorder.lastError ?? "no reason given"))
            return
        }
        videoRecorder.onState = { [weak self] line in
            DispatchQueue.main.async { self?.speaker.announce(line) }
        }
        group.syncTaps()
        var line = "Recording the picture and the sound to "
            + "\((path as NSString).lastPathComponent)"
        if !live { line += ", taking the picture that would go out" }
        if let note = whatIsReallyInTheFile() { line += ". \(note)" }
        speaker.announceState(line)
        updateStatusLine()
    }

    /// What is really in a recording, said when one starts.
    ///
    /// Darrell, 10 September 2026, ticked "Hear it yourself" and his source was
    /// not in the recording. **Monitoring is what YOU hear; a recording takes
    /// the on air mix.** That is the right design and nothing anywhere said so,
    /// so both recording keys now name what is in the file, including anything
    /// you can hear that is not on the air and therefore not in it.
    func whatIsReallyInTheFile() -> String? {
        var missing: [String] = []
        if mic.isOpen && !board.stream.sendMic { missing.append("your microphone") }
        for source in sourceGroup.all
        where source.config.monitor && !source.config.onAir && !source.config.muted {
            missing.append(source.config.name)
        }
        guard !missing.isEmpty else { return nil }
        let list = missing.count == 1
            ? missing[0]
            : missing.dropLast().joined(separator: ", ") + " and " + missing[missing.count - 1]
        let verb = missing.count == 1 ? "is" : "are"
        return "It takes the on air mix, so \(list) \(verb) not in it: you can "
            + "hear \(missing.count == 1 ? "it" : "them") and the recording cannot."
    }

    /// A running order track has gone out: put it in every open track list.
    ///
    /// Called from `player.onMoved`, which fires for the first track, for a
    /// natural handover and for a manual segue alike. **Pads are deliberately
    /// not in it**: a track list with forty sound effects in it is not a track
    /// list.
    func trackWentOut(_ track: Track) {
        let title = track.displayName
        let artist = track.artist ?? ""
        if recorder.isRecording {
            recorder.cue?.add(title: title, performer: artist, seconds: recorder.elapsed)
        }
        if videoRecorder.isRecording {
            videoRecorder.cue?.add(title: title, performer: artist,
                                   seconds: videoRecorder.elapsed)
        }
        cueWindow?.refresh()
    }

    // ------------------------------------------------------- the cue sheet ---

    /// Command+Shift+C. What is coming up, from the ticked items.
    ///
    /// Opens it, or brings it to the front and puts the cursor back in the
    /// list. **It never CLOSES it**: a toggle whose state you cannot see is a
    /// coin flip, and Escape closes it like every other window here.
    func showCueSheet() {
        if let window = cueWindow {
            window.raise()
            return
        }
        let sheet = CueSheetWindow(main: self)
        cueWindow = sheet
        sheet.onClose = { [weak self] in self?.cueWindow = nil }
        sheet.show()
    }

    /// What is on air and how long is left, for the cue sheet's clock.
    ///
    /// The one moving number, and it lives OUTSIDE the list on purpose: a
    /// counting cell inside a row is a name change every second, and a name
    /// change on the focused row makes a screen reader start again.
    func cueClockLine() -> String {
        guard player.isPlaying, let track = player.currentTrack else {
            return "Nothing is playing from the running order."
        }
        var said: [String] = []
        let left = player.remaining ?? 0
        said.append("On air, \(track.displayName)"
            + (left > 0 ? ", \(CueSheet.saidLength(left)) left" : ""))
        if let next = player.nextTrack {
            let until = player.untilHandover
            said.append("Next, \(next.displayName)"
                + (until > 0 ? ", in \(CueSheet.saidLength(until))" : ""))
        }
        return said.joined(separator: ".  ") + "."
    }
}
