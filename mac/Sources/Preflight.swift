// What is about to go on the air, worked out before it does.
//
// A deliberate mirror of dropdeck/preflight.py, which mac/CLAUDE.md singles
// out as the one piece of the Windows video work that could be ported almost
// literally. Every sentence here is the Windows sentence, and
// `mac/tools/cross_check.py` proves it.
//
// Command+B used to be a leap. The app knew perfectly well where the show was
// going, what it was encoding, what would be on the screen and whether the
// presenter's own microphone was part of the programme, and it said none of
// it: it connected, and several seconds later either announced the destination
// or a failure. A sighted broadcaster has a rack of settings in front of them
// and can glance at it. There is no glance here, so the app has to say it.
//
// **And "it connected" is not the same claim as "it is right".** Nearly every
// way of getting this wrong survives the connection and ruins the broadcast
// quietly:
//
//   * a picture file that has been moved sends a flat dark rectangle for three
//     hours, because the image source fills a canvas rather than failing;
//   * the microphone left off the programme sends a show with no presenter on
//     it, and it sounds perfect from where the presenter is sitting because
//     monitoring is downstream of the split;
//   * the wrong one of the two destinations ticked sends the show to a radio
//     server nobody is listening to while the video platform waits;
//   * a bitrate outside what the platform publishes can have the broadcast
//     ended from the other end, with nothing said at this one.
//
// None of those raise. All of them are knowable in advance.
//
// **Nothing here opens a window and nothing here touches the network.** It is
// arithmetic and string building over a settings value, which is what makes
// the whole of it testable with no sound card, no camera and no display.

import Foundation

/// How bad one thing is.
enum NoteLevel: String {
    /// A problem that will stop the broadcast working at all. Command+B does
    /// not proceed past one of these.
    case stop = "stop"
    /// A problem that will let the broadcast happen and spoil it. These are
    /// the expensive ones, because nothing downstream will mention them again.
    case warn = "warn"
}

/// One thing worth saying before going live.
struct PreflightNote {
    let level: NoteLevel
    let text: String
    /// Where to send somebody who wants to put it right. A settings page name,
    /// or "" when there is nothing to open.
    let fix: String

    init(_ level: NoteLevel, _ text: String, _ fix: String = "") {
        self.level = level
        self.text = text
        self.fix = fix
    }
}

/// What Command+B is about to do, and what is wrong with it.
struct Preflight {
    /// C.liveToAudio or C.liveToVideo.
    let target: String
    /// The summary, as (label, value) pairs in the order they are read. An
    /// array rather than a dictionary because the order is the whole point:
    /// where it is going first, then what is being sent, then who is on it.
    let lines: [(label: String, value: String)]
    let notes: [PreflightNote]

    var stops: [PreflightNote] { notes.filter { $0.level == .stop } }
    var warnings: [PreflightNote] { notes.filter { $0.level == .warn } }
    var blocked: Bool { !stops.isEmpty }

    /// The one sentence answer to "where is this going". First line only.
    /// Everything else is available and this is what gets spoken when somebody
    /// just wants to go live.
    func summary() -> String { lines.first?.value ?? "" }

    /// The whole thing, as one string a screen reader reads straight through.
    ///
    /// Semicolons rather than full stops between the settings, so a screen
    /// reader runs them together as a list rather than reading each as its own
    /// sentence, and full stops before the problems so they land separately.
    /// Measured against a real screen reader rather than guessed at.
    func spoken() -> String {
        var said = lines.map { "\($0.label) \($0.value)" }.joined(separator: "; ")
        let trouble = notes.map { $0.text }
        if !trouble.isEmpty {
            said += ". " + trouble.joined(separator: ". ")
        }
        return said
    }
}

/// What the streamer will see. Mirrors the dictionary `_stream_settings`
/// builds on Windows, so the pre-flight reads exactly what goes on the air
/// rather than taking a second reading of the board.
struct PreflightSettings {
    var server = ""
    var host = ""
    var mount = ""
    var name = ""
    var password = ""
    var format = "mp3"
    var bitrate = 0
    var picture = C.pictureCard
    var pictureFile = ""
    var camera = ""
    var streamName = ""
    var videoWidth = C.rtmpWidth
    var videoHeight = C.rtmpHeight
    var videoFPS = C.rtmpFPS
    var videoBitrate = C.rtmpVideoBitrate
}

/// The few live facts the pre-flight needs from the board. Passed in rather
/// than fetched, which is what keeps this callable from a test with nothing
/// running.
struct PreflightBoard {
    var liveTo = C.liveToAudio
    var videoServer = ""
    var streamMic = true
    var streamTitles = true
    /// The four named places, exactly as board.json stores them.
    var textPlaces: [String: [String: String]] = [:]
}

enum Preflighter {

    /// What the four places are called, and whether a string fits in one.
    /// Supplied by `Overlay` when it exists, so the pre-flight can be built
    /// and checked before the drawing is. Windows does the same thing with a
    /// lazy import and an `available()` guard.
    struct TextFitting {
        var placeLabel: (String) -> String
        var fits: (_ text: String, _ place: String, _ width: Int, _ height: Int) -> Bool
    }

    /// The destination, said the way its owner would say it.
    ///
    /// The station's own NAME first when it has one, because that is what the
    /// user called it and it is shorter and clearer than the software running
    /// on it. `serverLabel` says "Icecast, or Liquidsoap harbor", which is
    /// exactly right in the Preferences dropdown, where somebody is working
    /// out which entry covers their server, and exactly wrong on the way to
    /// air. The software name is the fallback rather than the lead, so a
    /// server with no name still says something useful.
    static func whereItGoes(_ settings: PreflightSettings, video: Bool) -> String {
        let host = settings.host
        let name = settings.name.trimmingCharacters(in: .whitespacesAndNewlines)
        if video {
            // An RTMP address has the stream key in it, so it goes through
            // hostLabel. YouTube and Facebook have one address each and it is
            // not the user's to choose, so naming the platform is enough.
            let platform = StreamServers.serverLabel(settings.server)
            if !name.isEmpty {
                return platform.isEmpty ? name : "\(name), on \(platform)"
            }
            return "\(platform), \(StreamServers.hostLabel(host))"
        }
        let where_ = host + settings.mount
        if !name.isEmpty { return "\(name), \(where_)" }
        return "\(StreamServers.serverLabel(settings.server)), \(where_)"
    }

    /// What will be on the screen, said as the audience would see it.
    static func pictureWords(_ settings: PreflightSettings) -> String {
        switch settings.picture {
        case C.pictureImage:
            let base = (settings.pictureFile as NSString).lastPathComponent
            return "your own picture, \(base.isEmpty ? "not chosen" : base)"
        case C.pictureCamera:
            return settings.camera.isEmpty ? "a camera, but none is chosen" : settings.camera
        case C.pictureScreen:
            return "what is on your screen"
        case C.pictureSplit:
            let camera = settings.camera.isEmpty ? "no camera chosen" : settings.camera
            return "your screen, with \(camera) in the corner"
        default:
            let name = settings.name.isEmpty ? settings.streamName : settings.name
            return name.isEmpty ? "a card" : "a card saying \(name)"
        }
    }

    /// Everything that can be wrong with the picture, before it is opened.
    private static func checkPicture(_ settings: PreflightSettings,
                                     _ notes: inout [PreflightNote],
                                     screenReady: Bool, screenReason: String) {
        let kind = settings.picture
        if kind == C.pictureImage {
            let path = settings.pictureFile
            if path.isEmpty {
                notes.append(PreflightNote(.warn, "No picture file has been chosen, so "
                    + "the stream would show an empty screen", C.fixVideo))
            } else if !FileManager.default.fileExists(atPath: path) {
                // The expensive one. The image source fills a canvas with the
                // background colour rather than returning nothing, so the
                // fallback never fires, nothing is announced, and the whole
                // broadcast is a dark rectangle that looks deliberate.
                notes.append(PreflightNote(.warn, "That picture file is not there any "
                    + "more, so the stream would show an empty screen", C.fixVideo))
            }
        }
        if C.pictureNeedsCamera.contains(kind) && settings.camera.isEmpty {
            notes.append(PreflightNote(.warn, "No camera has been chosen, so the stream "
                + "would fall back to a card", C.fixVideo))
        }
        if C.pictureNeedsScreen.contains(kind) && !screenReady {
            notes.append(PreflightNote(.warn, screenReason.isEmpty
                ? "The screen cannot be captured on this machine" : screenReason,
                C.fixVideo))
        }
    }

    /// Whether anything on top of the picture would be cut off.
    ///
    /// Answerable now, and only now: once you are on the air the only way to
    /// find out is somebody watching telling you. The place has a known width
    /// and the text has a measurable one, so "that will not fit" is arithmetic
    /// rather than an opinion.
    private static func checkScreenText(_ settings: PreflightSettings,
                                        _ board: PreflightBoard,
                                        _ notes: inout [PreflightNote],
                                        _ text: TextFitting?) {
        guard let text, !board.textPlaces.isEmpty else { return }
        let width = settings.videoWidth
        let height = settings.videoHeight
        for key in C.placesOrder {
            let held = board.textPlaces[key] ?? [:]
            let kind = held["kind"] ?? C.textNone
            if kind == C.textNone { continue }
            var words = ""
            let place = text.placeLabel(key).lowercased()
            if kind == C.textWords {
                words = held["words"] ?? ""
                if words.isEmpty {
                    notes.append(PreflightNote(.warn, "The \(place) is set to your own "
                        + "words and there are none yet, so it would be empty", C.fixVideo))
                    continue
                }
            } else if kind == C.textFile {
                let path = held["file"] ?? ""
                if path.isEmpty {
                    notes.append(PreflightNote(.warn, "The \(place) is set to read a "
                        + "file and none is chosen, so it would be empty", C.fixVideo))
                    continue
                }
                if !FileManager.default.fileExists(atPath: path) {
                    notes.append(PreflightNote(.warn, "The file the \(place) reads is "
                        + "not there any more, so it would be empty", C.fixVideo))
                    continue
                }
                words = ""
            } else if kind == C.textStation {
                words = settings.name
                if words.isEmpty {
                    notes.append(PreflightNote(.warn, "The \(place) shows your station "
                        + "name and there is not one set", C.fixAudio))
                    continue
                }
            } else {
                continue
            }
            if !words.isEmpty && !text.fits(words, key, width, height) {
                notes.append(PreflightNote(.warn, "\(words) is too long for the "
                    + "\(place) and would be cut short", C.fixVideo))
            }
        }
    }

    /// Work out what Command+B would do with these settings.
    static func check(settings: PreflightSettings, board: PreflightBoard,
                      audioRunning: Bool = true, micOpen: Bool = false,
                      screenReady: Bool = true, screenReason: String = "",
                      text: TextFitting? = nil) -> Preflight {
        var notes: [PreflightNote] = []
        var lines: [(label: String, value: String)] = []
        let video = board.liveTo == C.liveToVideo
        let page = video ? C.fixVideo : C.fixAudio
        let what = video ? "video platform" : "server"

        // ------------------------------------------------------ where it goes
        if settings.host.isEmpty {
            lines.append(("Going to", "nowhere: no \(what) is set up yet"))
            notes.append(PreflightNote(.stop, "There is no \(what) set up yet", page))
        } else {
            lines.append(("Going to", whereItGoes(settings, video: video)))
        }

        // --------------------------------------------------------- the sound
        let fmt = C.streamFormatShortLabels[settings.format] ?? settings.format.uppercased()
        lines.append(("Sound", "\(settings.bitrate) kbps \(fmt)"))

        // ------------------------------------------------------- the picture
        if video {
            lines.append(("Picture", "\(pictureWords(settings)), "
                + "\(settings.videoWidth) by \(settings.videoHeight) at "
                + "\(settings.videoBitrate) kbps"))
        }

        // ----------------------------------------------------- the presenter
        // Said every time, not only when it is wrong. "Microphone on air" is
        // the line a presenter wants to hear before they start talking, and a
        // warning that only appears when something is broken teaches nobody
        // where to look.
        if board.streamMic {
            lines.append(("Microphone", micOpen ? "on the air"
                : "on the air when you open it, Command+M"))
        } else {
            lines.append(("Microphone", "NOT going out"))
            notes.append(PreflightNote(.warn, "Your microphone is not on the air, so "
                + "listeners will not hear you at all", C.fixAudio))
        }

        // -------------------------------------------------------- the faults
        if video && settings.password.isEmpty {
            notes.append(PreflightNote(.stop, "There is no stream key for this station",
                                       C.fixVideo))
        }
        if !video && !settings.host.isEmpty && settings.password.isEmpty {
            // Not a stop: a private Icecast can be set up to want no password,
            // and refusing to broadcast over a guess would be worse than the
            // warning.
            notes.append(PreflightNote(.warn, "There is no password for this server, "
                + "which most servers will refuse", C.fixAudio))
        }
        if !audioRunning {
            notes.append(PreflightNote(.stop, "The sound card is not running, so there "
                + "is nothing to send", C.fixAudio))
        }
        if video {
            checkPicture(settings, &notes, screenReady: screenReady,
                         screenReason: screenReason)
            checkScreenText(settings, board, &notes, text)
            let advice = StreamServers.bitrateAdvice(
                server: settings.server, width: settings.videoWidth,
                height: settings.videoHeight, fps: settings.videoFPS,
                videoKbps: settings.videoBitrate, audioKbps: settings.bitrate)
            if !advice.isEmpty {
                notes.append(PreflightNote(.warn, advice, C.fixVideo))
            }
            if settings.picture == C.pictureCard && !board.streamTitles {
                // The card is the only place a viewer finds out what is
                // playing, and the switch that freezes it lives on the other
                // page.
                notes.append(PreflightNote(.warn, "Track titles are turned off, so the "
                    + "card will not say what is playing", C.fixAudio))
            }
        }
        let warning = goingLiveWarning(board)
        if !warning.isEmpty {
            notes.append(PreflightNote(.warn, warning, ""))
        }
        return Preflight(target: board.liveTo, lines: lines, notes: notes)
    }

    /// What the platform itself does the moment the stream connects.
    ///
    /// The two behave in opposite ways and both surprises are expensive:
    /// YouTube publishes and notifies subscribers at once, Facebook shows a
    /// preview and posts nothing. This is said BEFORE connecting. It used to
    /// be said after, which is the wrong side of the only decision it informs.
    static func goingLiveWarning(_ board: PreflightBoard) -> String {
        if board.liveTo != C.liveToVideo { return "" }
        if C.rtmpGoesLiveAtOnce[board.videoServer] == true {
            return "\(StreamServers.serverLabel(board.videoServer)) puts you live the "
                 + "moment you connect, and tells your subscribers"
        }
        if board.videoServer == "facebook" {
            return "Facebook will show you a preview and post nothing until you press "
                 + "Go Live Now"
        }
        return ""
    }
}
