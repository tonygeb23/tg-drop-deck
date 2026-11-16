// Recording the picture as well as the sound, and the track list beside both.
//
// Command+R records the sound alone and is untouched. Command+Shift+R records
// the picture and the sound together into one MP4, and neither needs you to be
// on air.

import AppKit

extension MainWindow {

    /// Command+Shift+R. The picture and the sound, into one file.
    ///
    /// The picture is the APP's, whatever Command+B is pointed at, and it is
    /// the one shared feed (PictureFeed.swift): the recording takes a hold on
    /// it rather than opening a camera of its own, so a recording and a stream
    /// never open the same device twice.
    ///
    /// **The picture first, and waited for, off the main thread.** The
    /// recorder's timeline begins the moment it starts and writes black until
    /// a picture arrives, so the recorder is only started once the picture is
    /// ready. Windows blocks the key for that; here the wait is on another
    /// thread, because a camera opened on the main one can wait two minutes
    /// for a permission answer that has to arrive on the main one.
    func toggleVideoRecording() {
        if videoRecordingStarting {
            speaker.announceState("The picture recording is still starting")
            return
        }
        if videoRecorder.isRecording {
            finishVideoRecording(quiet: false)
            return
        }
        // Said about the picture as it is NOW, before anything opens.
        let warnings = pictureWarnings()
        videoRecordingStarting = true
        recordOverlay.apply(overlaySettings())
        recordOverlay.setTitle(nowPlayingTitle)
        let feed = pictureFeed
        feed.acquire(PictureFeed.forRecording)
        updateStatusLine()
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            _ = feed.waitReady(timeout: C.cameraOpenTimeout)
            DispatchQueue.main.async { self?.beginVideoRecording(warnings: warnings) }
        }
    }

    /// The picture is open. Start the file.
    private func beginVideoRecording(warnings: String) {
        videoRecordingStarting = false
        guard !closedDown else {
            pictureFeed.release(PictureFeed.forRecording)
            return
        }
        let tap = FrameTap()
        // Told BEFORE it starts, so nothing it says in its first moments is
        // lost: losing audio, and a writer that fails.
        videoRecorder.onState = { [weak self] line in
            DispatchQueue.main.async { self?.speaker.announce(line) }
        }
        videoRecorder.onFailed = { [weak self] why in self?.pictureRecordingFailed(why) }
        guard let path = videoRecorder.start(
            taps: group.taps, rate: group.sampleRate,
            width: board.videoWidth, height: board.videoHeight, fps: board.videoFPS,
            folder: board.recordFolder, tap: tap) else {
            // The hold was taken before the recorder, so it is handed back, or
            // the camera light stays on for a recording that never happened.
            pictureFeed.release(PictureFeed.forRecording)
            speaker.announceState("Recording the picture would not start. "
                + (videoRecorder.lastError ?? "no reason given"))
            updateStatusLine()
            return
        }
        recordTap = tap
        group.syncTaps()
        syncRecordPicture()
        noteCurrentTrack()
        var line = "The picture and the sound, to "
            + "\(((path as NSString).lastPathComponent as NSString).deletingPathExtension)."
        if let note = whatIsReallyInTheFile() { line += " \(note)" }
        line += pictureInTheRecording() + warnings
        // "Recording started" first, then the detail (Siena, October 2026).
        announceRecording("Recording started", line)
        updateStatusLine()
        // The menu item's words follow: this is later than the key press that
        // refreshed it, because the picture was opened first.
        updateAirMenu()
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
        // Not while paused: the track is noted when the recording carries on,
        // at the moment it really starts in the file.
        if recorder.isRecording && !recorder.isPaused {
            recorder.cue?.add(title: title, performer: artist, seconds: recorder.elapsed)
        }
        if videoRecorder.isRecording && !videoRecorder.isPaused {
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
