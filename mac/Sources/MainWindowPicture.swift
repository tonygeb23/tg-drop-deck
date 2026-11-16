// The window's half of the one picture: who holds it, what is said about it,
// and who fills a recording's frames.
//
// The picture belongs to the APP, not to where Command+B is pointed (Windows
// 3.8.1, and ../CLAUDE.md). Nothing here asks `board.liveTo` except the one
// question it is right for: whether a STREAM wants a picture at all.
//
// The sentences are Windows' (dropdeck/ui.py), with the keys translated. Every
// one that can be a pure function is one, so the self test can hold it.

import AppKit
import CoreVideo

extension MainWindow {

    // ---------------------------------------------------------- the feed ---

    func makePictureFeed() -> PictureFeed {
        let feed = PictureFeed(settings: { [weak self] in
            self?.pictureSettings() ?? PictureSettings()
        })
        feed.onFallback = { [weak self] reason in
            DispatchQueue.main.async { self?.pictureFailed(reason) }
        }
        feed.onChange = { [weak self] in
            DispatchQueue.main.async { self?.updateStatusLine() }
        }
        return feed
    }

    /// Whether a picture is going out on the air right now.
    var showingPicture: Bool { videoStreamer.isOn }

    /// Whether a change to the picture takes effect THIS INSTANT: the stream
    /// or a recording is holding it. A momentary preview is invisible to the
    /// user and must not change what the app claims.
    func pictureLive() -> Bool {
        pictureFeed.heldBy(PictureFeed.forStream)
            || pictureFeed.heldBy(PictureFeed.forRecording)
    }

    /// The label of the picture the board is set to, lower case, as it is said.
    var chosenPictureLabel: String {
        (C.pictureLabels[board.picture] ?? board.picture).lowercased()
    }

    /// Said once, from whatever thread noticed, never once a frame (W381-43).
    ///
    /// It names WHAT is showing the card. "The stream is showing a card
    /// instead" is untrue when nothing is streaming and the card is going into
    /// a file, and the presenter would check the wrong thing.
    func pictureFailed(_ reason: String) {
        speaker.announce(MainWindow.fallbackSentence(
            reason, holders: pictureFeed.describeHolders()))
        updateStatusLine()
    }

    static func fallbackSentence(_ reason: String, holders: String) -> String {
        if PictureFeed.isRecovery(reason) {
            return "\(reason). \(pyCapitalize(holders.isEmpty ? "The picture" : holders)) "
                + "has the picture again."
        }
        return "\(reason). \(pyCapitalize(holders.isEmpty ? "The stream" : holders)) "
            + "is showing a card instead."
    }

    /// Python's `str.capitalize`: the first letter up and the rest down. The
    /// sentences here are copied from Windows and made the same way.
    static func pyCapitalize(_ text: String) -> String {
        guard let first = text.first else { return text }
        return String(first).uppercased() + text.dropFirst().lowercased()
    }

    /// A new track: the card and the words on top follow it, on the air and
    /// in a recording alike (W381-20). The recording's words used to be
    /// frozen on whatever was playing at Command+Shift+R.
    func pictureFollowsTrack() {
        let title = nowPlayingTitle
        recordOverlay.setTitle(title)
        videoStreamer.setTitle(title)
        pictureFeed.setTitle(title)
    }

    /// The words on top changed: every copy of them follows, the stream's and
    /// the recording's.
    func refreshPictureWords() {
        videoStreamer.setOverlay(overlaySettings())
        recordOverlay.apply(overlaySettings())
        recordOverlay.setTitle(nowPlayingTitle)
    }

    /// What Preferences, OK does about the picture in use: rebuild it only
    /// when something the PICTURE is made from changed and something holds
    /// it, and say so only when that is the air or a recording, because a
    /// momentary preview is invisible. The title is not a picture field: it
    /// follows the track on its own.
    static func picturePrefsChange(before: PictureSettings, after: PictureSettings,
                                   held: Bool, live: Bool) -> (rebuild: Bool, say: String?) {
        guard held, PictureFeed.comparable(before) != PictureFeed.comparable(after) else {
            return (false, nil)
        }
        return (true, live ? picturePrefsSentence : nil)
    }

    static let picturePrefsSentence = "The picture in use now follows the new settings"

    // ------------------------------------------------------ the stream's hold ---

    /// Command+B to a video platform takes the stream's hold. Returns the feed
    /// to hand the streamer, or nil when the destination sends no picture.
    func takeStreamPicture() -> PictureFeed? {
        guard PictureFeed.wantedFor(server: board.videoServer) else { return nil }
        if !pictureFeed.heldBy(PictureFeed.forStream) {
            pictureFeed.acquire(PictureFeed.forStream)
        }
        return pictureFeed
    }

    /// LET GO, do not close. A recording still running wants the same
    /// picture; the feed shuts the device when the LAST holder lets go.
    func releaseStreamPicture() {
        if pictureFeed.heldBy(PictureFeed.forStream) {
            pictureFeed.release(PictureFeed.forStream)
        }
        // The stream was filling a recording's tap. It is not any more, so the
        // recording pulls for itself or its picture would freeze (W381-37).
        syncRecordPicture()
    }

    // ---------------------------------------------------- the recording's ---

    /// Decide who fills the recording's tap, and decide again on every change.
    ///
    /// **While the stream is ON AIR it fills the tap**, so the file carries the
    /// identical composited frame, for nothing and with no second camera.
    /// Otherwise the recording's own thread pulls from the shared feed.
    /// "On air", not merely "on": while connecting and reconnecting there is
    /// nothing being sent to take frames from, so the recording's own thread
    /// keeps the job until the picture is really going out. A drop mid show
    /// used to freeze the recording's picture for as long as it lasted.
    func syncRecordPicture() {
        guard videoRecorder.isRecording, let tap = recordTap else {
            recordPump?.stop()
            recordPump = nil
            videoStreamer.setFrameTap(nil)
            return
        }
        if videoStreamer.state == .live {
            recordPump?.stop()
            recordPump = nil
            videoStreamer.setFrameTap(tap)
            return
        }
        videoStreamer.setFrameTap(nil)
        if recordPump == nil {
            let pump = RecordPicturePump(
                feed: pictureFeed, tap: tap, width: board.videoWidth,
                height: board.videoHeight, fps: board.videoFPS,
                overlay: recordOverlay, framingLevel: board.framingLevel,
                say: { [weak self] text in
                    DispatchQueue.main.async { self?.speaker.announce(text) }
                })
            recordPump = pump
            pump.start()
        }
    }

    /// Finish the picture recording and say where it is, unless quiet. The
    /// recorder is STOPPED FIRST and asked afterwards, so its size is the
    /// size on the disk.
    @discardableResult
    func finishVideoRecording(quiet: Bool) -> String {
        recordPump?.stop()
        recordPump = nil
        videoStreamer.setFrameTap(nil)
        videoRecorder.stop(taps: group.taps)
        group.syncTaps()
        recordTap = nil
        if pictureFeed.heldBy(PictureFeed.forRecording) {
            pictureFeed.release(PictureFeed.forRecording)
        }
        let said = videoRecorder.report()
        if !quiet {
            if said.hasPrefix("Recording saved as ") {
                announceRecording("Recording stopped", "Picture and sound saved as "
                                  + said.dropFirst("Recording saved as ".count))
            } else {
                speaker.announceState(said)
            }
        }
        updateStatusLine()
        updateAirMenu()
        return said
    }

    /// The writer failed mid recording. Said, and the recording put away down
    /// the ordinary path, so the camera is let go and the label is right. The
    /// sound recording is a different file with a different fault and is
    /// left alone (../CLAUDE.md, "Two recorders are two files").
    func pictureRecordingFailed(_ why: String) {
        guard videoRecorder.isRecording else { return }
        var said = finishVideoRecording(quiet: true)
        if recorder.isRecording { said += " Your sound recording is still going." }
        speaker.announce(said)
    }

    /// " Picture: ...", what the PICTURE of a video recording is (W381-14).
    ///
    /// Everything the app said about a recording was true and none of it was
    /// about the picture, which is how a recording of a card went unnoticed.
    func pictureInTheRecording() -> String {
        guard videoRecorder.isRecording || videoRecordingStarting else { return "" }
        let feed = pictureFeed
        return MainWindow.pictureInTheRecording(
            chosen: chosenPictureLabel, running: feed.running,
            asked: feed.framesAsked, fallenBack: feed.fallenBack,
            reason: feed.reason, described: feed.describe())
    }

    static func pictureInTheRecording(chosen: String, running: Bool, asked: Int,
                                      fallenBack: Bool, reason: String,
                                      described: String) -> String {
        // Nothing has looked through it yet, so there is no fallback to report
        // and describing one would be a guess. Say what is set up.
        if !running || asked == 0 { return " Picture: \(chosen)." }
        if fallenBack {
            return " Picture: a card instead of \(chosen)"
                + (reason.isEmpty ? "" : ", because \(reason)") + "."
        }
        return " Picture: \(described.isEmpty ? chosen : described)."
    }

    /// What is wrong with the picture, said once, as a recording starts
    /// (W381-15). Spoken rather than a window: Command+Shift+R is pressed in
    /// the middle of a show and must never stop to ask, but a picture fault in
    /// a recording is permanent and this is the only chance to mention it.
    func pictureWarnings() -> String {
        var ready = true, reason = ""
        if C.pictureNeedsScreen.contains(board.picture) {
            ready = Screens.available()
            reason = Screens.whyUnavailable()
        }
        let notes = Preflighter.pictureNotes(
            settings: preflightSettings(), board: preflightBoard(),
            screenReady: ready, screenReason: reason,
            consumer: Preflighter.forRecording,
            text: Preflighter.TextFitting(
                placeLabel: { Overlays.placeLabel($0) },
                fits: { Overlays.fits($0, key: $1, width: $2, height: $3) }))
        return MainWindow.spokenNotes(notes)
    }

    static func spokenNotes(_ notes: [PreflightNote]) -> String {
        let said = notes.map { $0.text }
        return said.isEmpty ? "" : " " + said.joined(separator: ". ") + "."
    }

    /// One sentence about a picture recording, or nothing, for Command+Shift+B
    /// (W381-13). "Am I recording" and "am I on air" are the same question
    /// asked in a hurry, and `VideoRecorder.describe` had no caller at all.
    func recordingLine() -> String {
        guard videoRecorder.isRecording else { return "" }
        return "\(videoRecorder.describe()).\(pictureInTheRecording())"
    }

    // ------------------------------------------------------- what is said ---

    /// Nothing that matters is holding the picture, so a change is for later.
    /// It used to say "next time you go live" during a video recording, while
    /// the file went on carrying the old picture (W381-08).
    static func nextTimeSentence(_ label: String) -> String {
        "Next time you go live or record the picture: \(label)"
    }

    /// "Now showing", or the truth when it is going into a file.
    static func pictureVerb(showing: Bool, recording: Bool) -> String {
        if showing && recording { return "On air and recording:" }
        if recording { return "Now recording:" }
        return "Now showing"
    }

    /// What the picture is and what is using it, for Command+Shift+W (W381-11).
    func pictureReport() -> String {
        let feed = pictureFeed
        let marks = Overlay(settings: overlaySettings())
        marks.setTitle(nowPlayingTitle)
        return MainWindow.pictureReport(
            chosen: chosenPictureLabel, width: board.videoWidth,
            height: board.videoHeight, using: feed.describeHolders(),
            liveToVideo: board.liveTo == C.liveToVideo,
            fallenBack: feed.running && feed.fallenBack, reason: feed.reason,
            marks: marks.anythingOn() ? marks.describe() : "")
    }

    static func pictureReport(chosen: String, width: Int, height: Int, using: String,
                              liveToVideo: Bool, fallenBack: Bool, reason: String,
                              marks: String) -> String {
        var said = ["Your picture is \(chosen), \(width) by \(height)."]
        if !using.isEmpty {
            said.append("\(pyCapitalize(using)) "
                        + "\(using.contains(" and ") ? "are using" : "is using") it.")
        } else if liveToVideo {
            said.append("Nothing is using it yet. It goes out when you press Command+B, "
                        + "and into the file when you press Command+Shift+R.")
        } else {
            // The sentence Tony's report was asking for. His radio station
            // takes no picture, and that is not a reason for him to have no
            // picture: it is a reason to say which of the two this is for.
            // NOT Windows' "Ctrl+B goes to your radio station ... until you
            // switch Ctrl+B over", which the key split made false: Command+B
            // always goes to the video platform now, and the radio station
            // has a key of its own.
            said.append("Nothing is using it yet. Your radio station sends no picture, "
                        + "so Option+Shift+B does not use it. It goes out when you press "
                        + "Command+B, which goes live on your video platform, and into "
                        + "the file when you press Command+Shift+R.")
        }
        if fallenBack {
            said.append("A card is standing in"
                        + (reason.isEmpty ? "" : ", because \(reason)") + ".")
        }
        if !marks.isEmpty { said.append("On top of it: \(marks).") }
        return said.joined(separator: " ")
    }

    /// The first half of Command+Shift+V: WHERE the picture is going, first,
    /// because that is what it used to get wrong (W381-10). A board pointed at
    /// a radio station said "Nothing" while a picture was being written to a
    /// file.
    static func screenHead(live: Bool, showing: Bool, recording: Bool,
                           described: String, chosen: String) -> String {
        if live {
            var going: [String] = []
            if showing { going.append("going out") }
            if recording { going.append("being recorded") }
            let said = described.isEmpty ? "a picture" : described
            return "\(said), \(going.isEmpty ? "open" : going.joined(separator: " and "))"
        }
        if recording { return "\(chosen), once the picture starts" }
        return "\(chosen), once you go live or start recording the picture"
    }

    /// Where the shot check's picture is, for its first line (W381-39).
    static func shotWhere(showing: Bool, recording: Bool) -> String {
        if showing { return "going out" }
        return recording ? "going into your recording" : "that would go out"
    }
}
