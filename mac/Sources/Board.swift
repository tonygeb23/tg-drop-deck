// Eighty slots on disk, and everything else a board remembers.
//
// The file format is the Windows one, unchanged, so the same board.json opens
// on either machine. Two rules make that safe:
//
//   1. Anything this build does not recognise is kept and written back out.
//      A board saved here must never lose the streaming server, the microphone
//      chain or anything else the Windows copy owns and this one has not
//      reached yet.
//   2. Where a value cannot mean the same thing on both platforms, the Mac one
//      gets a key of its own rather than overwriting the Windows one. The slot
//      hotkeys are the case that matters: key_code and modifiers are wx's, and
//      mac_key_code and mac_modifiers sit beside them.

import Foundation

let boardFormatVersion = 3

final class Board {

    var path: String?
    var dirty = false

    var slots: [Slot] = []
    var bankNames: [Int: String] = [:]

    var sfxVolume: Float = C.defaultSFXVolume
    var bedVolume: Float = C.defaultBedVolume
    var playlistVolume: Float = C.defaultPlaylistVolume
    var ducking = true
    var duckDB: Float = C.defaultDuckDB
    var bedFadeIn = C.fadeInBed
    var bedFadeOut = C.fadeOutBed

    var deviceUID: String?
    var deviceName: String?
    var bankDevices: [Int: String] = [:]      // bank to device UID

    var announcePlayback = true
    var speechLevel = C.defaultSpeechLevel
    var previewSounds = true

    var warnBeforeEnd = C.defaultWarnBeforeEnd
    var warnSeconds = C.defaultWarnSeconds
    var cueSound = C.defaultCueSound
    var cueLevelDB = C.cueLevelDB

    var recordFormat = C.defaultRecordFormat
    var recordBitrate = C.defaultRecordBitrate
    var recordFolder: String?

    var stopPresses = C.defaultStopPresses
    var stopFade = true

    var lastSoundDir: String?
    var lastPlaylistDir: String?

    /// Which bank modifier scheme the user asked for. Mac only, so it has a
    /// key of its own and the Windows copy ignores it.
    var bankScheme: BankScheme = .command

    // ----------------------------------------------------------- microphone ---
    //
    // The device, the gain and whether monitoring is wanted are saved. Whether
    // the microphone was ON is deliberately not: nothing opens a microphone
    // except a keypress, and a board that reopened it on load would put a live
    // room on air the moment the app started.
    var micDeviceUID: String?
    var micDeviceName: String?
    var micOutputUID: String?
    var micGainDB: Float = C.defaultMicGainDB
    var micMonitor = false
    var micChannel: MicChannel = .mix
    var voiceOn = true
    var voiceSettings: [String: Double] = MicChain.defaults

    // ------------------------------------------------------------ streaming ---
    var stream = StreamSettings()
    var streamStations: [[String: Any]] = []
    var playlistMonitorOnly = true

    // ------------------------------------------------------------- the video ---
    //
    // Mirrors the keys dropdeck/board.py added in 3.4.0 through 3.5.2, with
    // the SAME defaults: the two copies read and write one board.json, so a
    // default that differs is the same file behaving two ways. Every one of
    // these is whitelisted on the way in the way the audio settings already
    // are, because a board file is plain JSON a user can write and some of
    // these end up in a URL.
    /// Whether Command B asks what it is about to do before it does it.
    ///
    /// A Windows key since 3.4.1 and one the Mac had no use for until video
    /// arrived, because there was nothing much to be wrong about. It travels
    /// in the same board file, so it is read and written here whether or not
    /// this build acts on it.
    var askBeforeLive = true

    var videoServer = "youtube"
    var videoHost = C.rtmpIngest["youtube"] ?? ""
    /// Kept only so a board written by an older build round trips. The key
    /// itself belongs in the keychain: see Secrets.swift.
    var videoKey = ""
    /// Which of the two Command+B sends the show to.
    var liveTo = C.liveToAudio
    var picture = C.pictureCard
    var pictureFile = ""
    var pictureClock = false
    var camera = ""
    var screen = C.screenAll
    var splitCorner = C.splitCorner
    var textPlaces: [String: [String: String]] = Board.emptyTextPlaces()
    var colourBackground = C.colourBackground
    var colourText = C.colourText
    var colourAccent = C.colourAccent
    var visionProvider = C.visionProvider
    var visionModel = ""
    var videoWidth = C.rtmpWidth
    var videoHeight = C.rtmpHeight
    var videoFPS = C.rtmpFPS
    var videoBitrate = C.rtmpVideoBitrate
    var framingLevel = "problems"

    /// The four places, all empty. A separate function because it is needed
    /// both as the default and as the floor `textPlaces(from:)` builds on.
    static func emptyTextPlaces() -> [String: [String: String]] {
        var out: [String: [String: String]] = [:]
        for key in C.placesOrder {
            out[key] = ["kind": C.textNone, "words": "", "file": ""]
        }
        return out
    }

    // -------------------------------------------------------------- sources ---
    var sources: [SourceConfig] = []
    var globalHotkeysOn = false

    let playlist = Playlist()
    /// The drops library travels with the board: a board is a show and a show
    /// has its own idents.
    let drops = DropLibrary()

    /// Everything in the saved file this build did not recognise.
    private var unknown: [String: Any] = [:]

    init() {
        slots = (0..<C.totalSlots).map { index in
            let s = Slot(index: index)
            s.board = self
            return s
        }
    }

    // ---------------------------------------------------------------- banks ---

    func bankName(_ bank: Int) -> String {
        bankNames[bank] ?? C.bankTitles[bank] ?? ""
    }

    func bankSlots(_ bank: Int) -> [Slot] {
        let start = (bank - 1) * C.slotsPerBank
        return Array(slots[start..<(start + C.slotsPerBank)])
    }

    func visibleSlots(_ bank: Int) -> [Slot] {
        bankSlots(bank).filter { !$0.hidden }
    }

    func assignedCount(_ bank: Int) -> Int {
        bankSlots(bank).filter { $0.isAssigned && !$0.hidden }.count
    }

    /// A fade in seconds, clamped. Zero is a supported value and means the bed
    /// plays exactly as recorded, so nothing here may treat zero as absent.
    static func fade(_ value: Any?, fallback: Double) -> Double {
        guard let d = value as? Double, d.isFinite else {
            if let i = value as? Int { return min(C.maxBedFade, max(0.0, Double(i))) }
            return fallback
        }
        return min(C.maxBedFade, max(0.0, d))
    }

    /// A number out of a board file, clamped, or the default.
    ///
    /// Same shape as the port and bitrate helpers. A picture size of nought or
    /// a frame rate of a million is a crash at the moment somebody goes live,
    /// which is the worst moment this app has.
    static func videoNumber(_ value: Any?, _ fallback: Int, _ low: Int, _ high: Int) -> Int {
        var number: Int
        if let i = value as? Int { number = i }
        else if let d = value as? Double, d.isFinite { number = Int(d) }
        else if let s = value as? String, let i = Int(s) { number = i }
        else { return fallback }
        return max(low, min(high, number))
    }

    /// A colour NAME out of a board file, whitelisted like everything else.
    ///
    /// An unknown name becomes the default rather than being carried forward
    /// as a string nothing will ever draw. A board written by a later version
    /// with more colours in it therefore opens and looks ordinary, instead of
    /// opening and drawing nothing.
    static func colour(_ raw: Any?, _ fallback: String) -> String {
        guard let name = raw as? String, Colours.names.contains(name) else {
            return fallback
        }
        return name
    }

    /// What is on top of the picture, whitelisted out of a board file.
    ///
    /// A place whose kind is not one this build knows becomes "nothing" rather
    /// than being carried forward. Same rule as every other setting here.
    static func textPlaces(from raw: Any?) -> [String: [String: String]] {
        var out = emptyTextPlaces()
        guard let dict = raw as? [String: Any] else { return out }
        for (key, value) in dict {
            guard out[key] != nil, let spot = value as? [String: Any] else { continue }
            let kind = spot["kind"] as? String ?? ""
            out[key]?["kind"] = C.textKinds.contains(kind) ? kind : C.textNone
            out[key]?["words"] = String((spot["words"] as? String ?? "").prefix(200))
            out[key]?["file"] = spot["file"] as? String ?? ""
        }
        return out
    }

    // ----------------------------------------------------------- where it is ---

    static func configDir() -> String {
        let base = FileManager.default.urls(for: .applicationSupportDirectory,
                                            in: .userDomainMask).first!
        return base.appendingPathComponent("TG Studios/TG Drop Deck").path
    }

    static func defaultBoardPath() -> String {
        (configDir() as NSString).appendingPathComponent("board.json")
    }

    // --------------------------------------------------------------- saving ---

    func toDict() -> [String: Any] {
        var d = unknown
        d["app"] = C.appName
        d["format"] = boardFormatVersion
        d["sfx_volume"] = Double(sfxVolume)
        d["bed_volume"] = Double(bedVolume)
        d["playlist_volume"] = Double(playlistVolume)
        d["ducking"] = ducking
        d["duck_db"] = Double(duckDB)
        d["bed_fade_in"] = bedFadeIn
        d["bed_fade_out"] = bedFadeOut
        d["bank_names"] = Dictionary(uniqueKeysWithValues:
            bankNames.map { (String($0.key), $0.value) })
        d["announce_playback"] = announcePlayback
        d["speech_level"] = speechLevel
        d["preview_sounds"] = previewSounds
        d["warn_before_end"] = warnBeforeEnd
        d["warn_seconds"] = warnSeconds
        d["cue_sound"] = cueSound
        d["cue_level_db"] = Double(cueLevelDB)
        d["record_format"] = recordFormat
        d["record_bitrate"] = recordBitrate
        d["record_folder"] = recordFolder as Any? ?? NSNull()
        d["stop_presses"] = stopPresses
        d["stop_fade"] = stopFade
        d["last_sound_dir"] = lastSoundDir as Any? ?? NSNull()
        d["last_playlist_dir"] = lastPlaylistDir as Any? ?? NSNull()
        d["playlist"] = playlist.toDict()
        d["drops"] = drops.toDict()
        d["slots"] = slots.map { $0.toDict() }

        // Mac only keys, kept apart from the Windows ones on purpose.
        d["mac_device_uid"] = deviceUID as Any? ?? NSNull()
        d["mac_bank_devices"] = Dictionary(uniqueKeysWithValues:
            bankDevices.map { (String($0.key), $0.value) })
        d["mac_bank_scheme"] = bankScheme.rawValue
        d["mac_mic_device_uid"] = micDeviceUID as Any? ?? NSNull()
        d["mac_mic_output_uid"] = micOutputUID as Any? ?? NSNull()
        d["mic_device_name"] = micDeviceName as Any? ?? NSNull()
        d["mic_gain_db"] = Double(micGainDB)
        d["mic_monitor"] = micMonitor
        d["mic_channel"] = micChannel.rawValue
        d["voice_on"] = voiceOn
        d["voice_settings"] = voiceSettings
        d["global_hotkeys_on"] = globalHotkeysOn
        d["playlist_monitor_only"] = playlistMonitorOnly
        d["sources"] = sources.map { $0.toDict() }

        // The video half. Written whether or not this board has ever been on
        // a video platform, because a Windows copy reading this file expects
        // the keys to be there and falls back to ITS defaults when they are
        // not, and its defaults are these.
        d["ask_before_live"] = askBeforeLive
        d["video_server"] = videoServer
        d["video_host"] = videoHost
        d["video_key"] = videoKey
        d["live_to"] = liveTo
        d["picture"] = picture
        d["picture_file"] = pictureFile
        d["picture_clock"] = pictureClock
        d["camera"] = camera
        d["screen"] = screen
        d["split_corner"] = splitCorner
        d["text_places"] = textPlaces
        d["colour_background"] = colourBackground
        d["colour_text"] = colourText
        d["colour_accent"] = colourAccent
        d["vision_provider"] = visionProvider
        d["vision_model"] = visionModel
        d["video_width"] = videoWidth
        d["video_height"] = videoHeight
        d["video_fps"] = videoFPS
        d["video_bitrate"] = videoBitrate
        d["framing_level"] = framingLevel

        d["stream_server"] = stream.server
        d["stream_host"] = stream.host
        d["stream_port"] = stream.port
        d["stream_mount"] = stream.mount
        d["stream_user"] = stream.user
        d["stream_password"] = stream.password
        d["stream_format"] = stream.format
        d["stream_bitrate"] = stream.bitrate
        d["stream_name"] = stream.name
        d["stream_description"] = stream.description
        d["stream_genre"] = stream.genre
        d["stream_url"] = stream.url
        d["stream_stats_url"] = stream.statsURL
        d["stream_public"] = stream.isPublic
        d["stream_mic"] = stream.sendMic
        d["stream_titles"] = stream.sendTitles
        d["stream_stations"] = streamStations
        // The device NAME in the Windows shape, so that copy can still match
        // on it and so a board is readable by a person.
        d["device_name"] = deviceName as Any? ?? NSNull()
        return d
    }

    @discardableResult
    func save(to target: String? = nil) throws -> String {
        let dest = target ?? path ?? Board.defaultBoardPath()
        try FileManager.default.createDirectory(
            atPath: (dest as NSString).deletingLastPathComponent,
            withIntermediateDirectories: true)
        let data = try JSONSerialization.data(withJSONObject: toDict(),
                                              options: [.prettyPrinted, .sortedKeys])
        // Write beside the target then swap, so a crash mid save cannot leave a
        // half written board where the real one used to be. Dropbox holds a
        // newly created file open long enough to break the swap, so it retries.
        let temp = dest + ".tmp"
        try data.write(to: URL(fileURLWithPath: temp))
        var lastError: Error?
        for attempt in 0..<5 {
            do {
                _ = try FileManager.default.replaceItemAt(
                    URL(fileURLWithPath: dest), withItemAt: URL(fileURLWithPath: temp))
                lastError = nil
                break
            } catch {
                lastError = error
                Thread.sleep(forTimeInterval: 0.08 * Double(attempt + 1))
            }
        }
        if let lastError {
            // Last resort: write straight over it. Worse than the swap and far
            // better than not saving the show.
            try data.write(to: URL(fileURLWithPath: dest))
            _ = lastError
            try? FileManager.default.removeItem(atPath: temp)
        }
        path = dest
        dirty = false
        return dest
    }

    // -------------------------------------------------------------- loading ---

    static func load(_ path: String) -> Board? {
        guard let data = FileManager.default.contents(atPath: path),
              let raw = try? JSONSerialization.jsonObject(with: data),
              let dict = raw as? [String: Any] else { return nil }
        let board = Board.from(dict: dict, relativeTo: (path as NSString).deletingLastPathComponent)
        board.path = path
        return board
    }

    static func from(dict: [String: Any], relativeTo folder: String?) -> Board {
        let b = Board()
        let known: Set<String> = [
            "app", "format", "sfx_volume", "bed_volume", "playlist_volume",
            "ducking", "duck_db", "bed_fade_in", "bed_fade_out", "bank_names",
            "announce_playback", "speech_level", "preview_sounds",
            "warn_before_end", "warn_seconds", "cue_sound", "cue_level_db",
            "record_format", "record_bitrate", "record_folder",
            "stop_presses", "stop_fade", "last_sound_dir", "last_playlist_dir",
            "playlist", "drops", "slots",
            "mac_device_uid", "mac_bank_devices", "mac_bank_scheme", "device_name",
            "mac_mic_device_uid", "mac_mic_output_uid", "mic_device_name",
            "mic_gain_db", "mic_monitor", "mic_channel", "voice_on", "voice_settings",
            "global_hotkeys_on", "playlist_monitor_only", "sources",
            "stream_server", "stream_host", "stream_port", "stream_mount",
            "stream_user", "stream_password", "stream_format", "stream_bitrate",
            "stream_name", "stream_description", "stream_genre", "stream_url",
            "stream_stats_url", "stream_public", "stream_mic", "stream_titles",
            "stream_stations",
            "ask_before_live",
            "video_server", "video_host", "video_key", "live_to",
            "picture", "picture_file", "picture_clock", "camera", "screen",
            "split_corner", "text_places", "colour_background", "colour_text",
            "colour_accent", "vision_provider", "vision_model",
            "video_width", "video_height", "video_fps", "video_bitrate",
            "framing_level",
        ]
        b.unknown = dict.filter { !known.contains($0.key) }

        if let v = dict["sfx_volume"] as? Double { b.sfxVolume = Float(min(1, max(0, v))) }
        if let v = dict["bed_volume"] as? Double { b.bedVolume = Float(min(1, max(0, v))) }
        if let v = dict["playlist_volume"] as? Double { b.playlistVolume = Float(min(1, max(0, v))) }
        if let v = dict["ducking"] as? Bool { b.ducking = v }
        if let v = dict["duck_db"] as? Double { b.duckDB = Float(min(0, max(-24, v))) }
        b.bedFadeIn = fade(dict["bed_fade_in"], fallback: C.fadeInBed)
        b.bedFadeOut = fade(dict["bed_fade_out"], fallback: C.fadeOutBed)

        if let names = dict["bank_names"] as? [String: String] {
            for (k, v) in names {
                if let bank = Int(k), !v.isEmpty { b.bankNames[bank] = String(v.prefix(C.maxBankName)) }
            }
        }
        if let v = dict["announce_playback"] as? Bool { b.announcePlayback = v }
        if let v = dict["speech_level"] as? String, C.speechLevels.contains(v) { b.speechLevel = v }
        if let v = dict["preview_sounds"] as? Bool { b.previewSounds = v }
        if let v = dict["warn_before_end"] as? Bool { b.warnBeforeEnd = v }
        if let v = dict["warn_seconds"] as? Double {
            b.warnSeconds = min(C.maxWarnSeconds, max(C.minWarnSeconds, v))
        }
        if let v = dict["cue_sound"] as? String,
           C.cueSounds.contains(where: { $0.key == v }) { b.cueSound = v }
        if let v = dict["cue_level_db"] as? Double {
            b.cueLevelDB = Float(min(Double(C.maxCueLevelDB), max(Double(C.minCueLevelDB), v)))
        }
        if let v = dict["record_format"] as? String, C.recordFormatKeys.contains(v) {
            b.recordFormat = v
        }
        if let v = dict["record_bitrate"] as? Int { b.recordBitrate = v }
        b.recordFolder = dict["record_folder"] as? String
        if let v = dict["stop_presses"] as? Int {
            b.stopPresses = min(C.maxStopPresses, max(C.minStopPresses, v))
        }
        if let v = dict["stop_fade"] as? Bool { b.stopFade = v }
        b.lastSoundDir = dict["last_sound_dir"] as? String
        b.lastPlaylistDir = dict["last_playlist_dir"] as? String

        b.deviceUID = dict["mac_device_uid"] as? String
        b.deviceName = dict["device_name"] as? String
        if let devices = dict["mac_bank_devices"] as? [String: String] {
            for (k, v) in devices { if let bank = Int(k) { b.bankDevices[bank] = v } }
        }
        if let s = dict["mac_bank_scheme"] as? String, let scheme = BankScheme(rawValue: s) {
            b.bankScheme = scheme
        }

        b.micDeviceUID = dict["mac_mic_device_uid"] as? String
        b.micOutputUID = dict["mac_mic_output_uid"] as? String
        b.micDeviceName = dict["mic_device_name"] as? String
        if let v = dict["mic_gain_db"] as? Double {
            b.micGainDB = Float(min(Double(C.maxMicGainDB), max(Double(C.minMicGainDB), v)))
        }
        b.micMonitor = dict["mic_monitor"] as? Bool ?? false
        if let ch = dict["mic_channel"] as? String, let parsed = MicChannel(rawValue: ch) {
            b.micChannel = parsed
        }
        b.voiceOn = dict["voice_on"] as? Bool ?? true
        if let voice = dict["voice_settings"] as? [String: Double] {
            var merged = MicChain.defaults
            for (k, v) in voice where MicChain.parameter(k) != nil { merged[k] = v }
            b.voiceSettings = merged
        }
        b.globalHotkeysOn = dict["global_hotkeys_on"] as? Bool ?? false
        b.playlistMonitorOnly = dict["playlist_monitor_only"] as? Bool ?? true
        if let rows = dict["sources"] as? [[String: Any]] {
            b.sources = rows.compactMap { SourceConfig.fromDict($0) }
        }
        if let v = dict["stream_server"] as? String, C.streamServers.contains(v) {
            b.stream.server = v
        }
        b.stream.host = dict["stream_host"] as? String ?? ""
        b.stream.port = dict["stream_port"] as? Int ?? 8000
        b.stream.mount = dict["stream_mount"] as? String ?? "/live"
        b.stream.user = dict["stream_user"] as? String ?? "source"
        b.stream.password = dict["stream_password"] as? String ?? ""
        // A board written on Windows may name MP3, which no Mac can encode.
        // It is moved to the nearest thing this build really sends rather than
        // refused, because the alternative is a station that cannot go on air
        // at all on a Mac. An Ogg station now lands on Opus, which is an Ogg
        // stream, rather than on AAC.
        let savedFormat = dict["stream_format"] as? String ?? C.defaultStreamFormat
        b.stream.format = C.streamFormatFor(savedFormat)
        b.stream.bitrate = dict["stream_bitrate"] as? Int ?? C.defaultStreamBitrate
        b.stream.name = dict["stream_name"] as? String ?? ""
        b.stream.description = dict["stream_description"] as? String ?? ""
        b.stream.genre = dict["stream_genre"] as? String ?? ""
        b.stream.url = dict["stream_url"] as? String ?? ""
        b.stream.statsURL = dict["stream_stats_url"] as? String ?? ""
        b.stream.isPublic = dict["stream_public"] as? Bool ?? false
        b.stream.sendMic = dict["stream_mic"] as? Bool ?? true
        b.stream.sendTitles = dict["stream_titles"] as? Bool ?? true
        b.streamStations = cleanStations(dict["stream_stations"])

        // ------------------------------------------------------- the video ---
        //
        // Whitelisted the same way the audio settings are, and for the same
        // reason: a board file is plain JSON that a user can write, and some
        // of these end up in a URL. An unknown value becomes the default
        // rather than being carried forward as a string nothing will draw, so
        // a board written by a LATER build with more choices in it opens and
        // looks ordinary instead of opening and drawing nothing.
        b.askBeforeLive = dict["ask_before_live"] as? Bool ?? true
        let server = dict["video_server"] as? String ?? ""
        b.videoServer = C.videoServerOrder.contains(server) ? server : "youtube"
        b.videoHost = dict["video_host"] as? String ?? ""
        b.videoKey = dict["video_key"] as? String ?? ""
        let liveTo = dict["live_to"] as? String ?? ""
        b.liveTo = C.liveTo.contains(liveTo) ? liveTo : C.liveToAudio

        // A board written by the first build of this feature put the platform
        // in stream_server, where the audio settings live. Move it, rather
        // than leaving a board that says its radio station is "youtube" and
        // then tries to open a mount point on it.
        if let stray = dict["stream_server"] as? String,
           C.videoServerOrder.contains(stray) {
            b.videoServer = stray
            b.videoHost = dict["stream_host"] as? String ?? ""
            b.liveTo = C.liveToVideo
            b.stream.server = C.streamServerIcecast
            b.stream.host = ""
        }
        if b.videoHost.isEmpty {
            b.videoHost = C.rtmpIngest[b.videoServer] ?? ""
        }

        let picture = dict["picture"] as? String ?? ""
        b.picture = C.pictureSources.contains(picture) ? picture : C.pictureCard
        b.pictureFile = dict["picture_file"] as? String ?? ""
        b.pictureClock = dict["picture_clock"] as? Bool ?? false
        b.camera = dict["camera"] as? String ?? ""
        let screen = dict["screen"] as? String ?? ""
        b.screen = C.screenChoices.contains(screen) ? screen : C.screenAll
        let corner = dict["split_corner"] as? String ?? ""
        b.splitCorner = C.splitCorners.contains(corner) ? corner : C.splitCorner
        b.textPlaces = Board.textPlaces(from: dict["text_places"])
        b.colourBackground = Board.colour(dict["colour_background"], C.colourBackground)
        b.colourText = Board.colour(dict["colour_text"], C.colourText)
        b.colourAccent = Board.colour(dict["colour_accent"], C.colourAccent)
        let provider = dict["vision_provider"] as? String ?? ""
        // Nobody has chosen: take the one that has a key on this machine
        // rather than the first in the list, so a board saved before this
        // feature existed opens on something that will actually work.
        b.visionProvider = C.visionProviders.contains(provider)
            ? provider : ShotCheck.bestProvider(fallback: C.visionProvider)
        if let model = dict["vision_model"] as? String {
            b.visionModel = String(model.trimmingCharacters(in: .whitespacesAndNewlines)
                                        .prefix(80))
        } else {
            b.visionModel = ""
        }
        // **A model name belonging to a different provider is worse than
        // none.** Tony's board came out of 3.5.2 holding Gemini and
        // "claude-sonnet-5" together, because changing the provider did not
        // change the model box. Asking Google for a Claude model is a 404,
        // which this app then explains as "a model name that cannot look at
        // pictures", so the message sends somebody looking in the wrong place.
        // An empty model means "use the default for whoever is chosen", which
        // is the right answer here.
        if !b.visionModel.isEmpty {
            let mine = ShotCheck.knownModels[b.visionProvider] ?? []
            let theirs = ShotCheck.providers.filter { $0 != b.visionProvider }
                .flatMap { ShotCheck.knownModels[$0] ?? [] }
            if !mine.contains(b.visionModel) && theirs.contains(b.visionModel) {
                b.visionModel = ""
            }
        }
        b.videoWidth = Board.videoNumber(dict["video_width"], C.rtmpWidth, 160, 3840)
        b.videoHeight = Board.videoNumber(dict["video_height"], C.rtmpHeight, 120, 2160)
        b.videoFPS = Board.videoNumber(dict["video_fps"], C.rtmpFPS, 1, 60)
        b.videoBitrate = Board.videoNumber(dict["video_bitrate"], C.rtmpVideoBitrate,
                                           200, 20000)
        let level = dict["framing_level"] as? String ?? ""
        b.framingLevel = C.framingLevels.contains(level) ? level : C.framingProblems

        if let rows = dict["slots"] as? [[String: Any]] {
            for (i, row) in rows.enumerated() where i < C.totalSlots {
                let slot = Slot.fromDict(index: i, data: row)
                slot.board = b
                // A board may store paths relative to itself, which is how the
                // shipped demo resolves wherever the app lands.
                if let p = slot.filepath, !p.isEmpty, !(p as NSString).isAbsolutePath,
                   let folder {
                    slot.filepath = (folder as NSString).appendingPathComponent(p)
                }
                b.slots[i] = slot
            }
        }
        if let pl = dict["playlist"] as? [String: Any] {
            b.playlist.load(from: pl, relativeTo: folder)
        }
        b.drops.load(from: dict["drops"] as? [String: Any], relativeTo: folder)
        // A board written before stations existed still has one set up, and
        // losing it on upgrade would be the worst kind of small betrayal.
        if b.streamStations.isEmpty && !b.stream.host.isEmpty {
            b.streamStations = [b.stationSettings()]
        }
        return b
    }

    // ------------------------------------------------------------- stations ---
    //
    // More than one station, because Tony runs two and retyping an address and
    // a password to swap between them is the sort of thing that goes wrong on
    // air. A saved station is kept in the Windows shape, a dictionary of the
    // stream_* keys, so the list moves between the two copies untouched.

    /// What travels in a saved station.
    ///
    /// **The video half belongs to the station too**, and leaving it out was
    /// not merely incomplete, it was destructive: `cleanStations` filters an
    /// incoming station down to this list, so a board written on Windows whose
    /// station carried a YouTube channel, opened here and saved, lost it for
    /// good. The two copies share one file and this is the list that decides
    /// what survives a round trip.
    ///
    /// A YouTube station needs these and the Icecast station on the same board
    /// does not, which is exactly why they are per station rather than per
    /// board.
    static let stationFields = [
        "stream_name", "stream_server", "stream_host", "stream_port",
        "stream_mount", "stream_user", "stream_password", "stream_format",
        "stream_bitrate", "stream_description", "stream_genre", "stream_url",
        "stream_public", "stream_mic", "stream_titles", "stream_stats_url",
        "video_server", "video_host", "video_key", "live_to",
        "picture", "picture_file", "picture_clock", "camera", "screen",
        "split_corner", "text_places", "colour_background", "colour_text",
        "colour_accent", "video_width", "video_height", "video_fps",
        "video_bitrate",
    ]

    /// Whatever was in the file, as a list of usable stations. A board file is
    /// not a trusted document, so anything that is not a dictionary with a name
    /// is dropped rather than allowed to become a station that explodes when
    /// you select it.
    static func cleanStations(_ value: Any?) -> [[String: Any]] {
        guard let list = value as? [Any] else { return [] }
        var out: [[String: Any]] = []
        for entry in list {
            guard let dict = entry as? [String: Any],
                  let name = dict["stream_name"] as? String,
                  !name.trimmingCharacters(in: .whitespaces).isEmpty else { continue }
            out.append(dict.filter { stationFields.contains($0.key) })
        }
        return out
    }

    /// The station that is set up right now, as a saved station would be.
    func stationSettings() -> [String: Any] {
        [
            "stream_name": stream.name,
            "stream_server": stream.server,
            "stream_host": stream.host,
            "stream_port": stream.port,
            "stream_mount": stream.mount,
            "stream_user": stream.user,
            "stream_password": stream.password,
            "stream_format": stream.format,
            "stream_bitrate": stream.bitrate,
            "stream_description": stream.description,
            "stream_genre": stream.genre,
            "stream_url": stream.url,
            "stream_public": stream.isPublic,
            "stream_mic": stream.sendMic,
            "stream_titles": stream.sendTitles,
            "stream_stats_url": stream.statsURL,
            "video_server": videoServer,
            "video_host": videoHost,
            "video_key": videoKey,
            "live_to": liveTo,
            "picture": picture,
            "picture_file": pictureFile,
            "picture_clock": pictureClock,
            "camera": camera,
            "screen": screen,
            "split_corner": splitCorner,
            "text_places": textPlaces,
            "colour_background": colourBackground,
            "colour_text": colourText,
            "colour_accent": colourAccent,
            "video_width": videoWidth,
            "video_height": videoHeight,
            "video_fps": videoFPS,
            "video_bitrate": videoBitrate,
        ]
    }

    var stationNames: [String] {
        streamStations.compactMap { $0["stream_name"] as? String }
    }

    /// Put a saved station into the live settings. True if there was one.
    @discardableResult
    func loadStation(_ name: String) -> Bool {
        guard let station = streamStations.first(where: { ($0["stream_name"] as? String) == name })
        else { return false }
        stream.name = name
        if let v = station["stream_server"] as? String, C.streamServers.contains(v) { stream.server = v }
        if let v = station["stream_host"] as? String { stream.host = v }
        if let v = station["stream_port"] as? Int { stream.port = (1...65535).contains(v) ? v : 8000 }
        if let v = station["stream_mount"] as? String { stream.mount = v }
        if let v = station["stream_user"] as? String { stream.user = v }
        if let v = station["stream_password"] as? String { stream.password = v }
        // A station saved on Windows may name MP3. Moved to the nearest format
        // this build sends, for the same reason the board loader does.
        if let v = station["stream_format"] as? String {
            stream.format = C.streamFormatFor(v)
        }
        if let v = station["stream_bitrate"] as? Int {
            stream.bitrate = C.streamBitrates.contains(v) ? v : C.defaultStreamBitrate
        }
        if let v = station["stream_description"] as? String { stream.description = v }
        if let v = station["stream_genre"] as? String { stream.genre = v }
        if let v = station["stream_url"] as? String { stream.url = v }
        if let v = station["stream_public"] as? Bool { stream.isPublic = v }
        if let v = station["stream_mic"] as? Bool { stream.sendMic = v }
        if let v = station["stream_titles"] as? Bool { stream.sendTitles = v }
        if let v = station["stream_stats_url"] as? String { stream.statsURL = v }

        // The video half, whitelisted the same way the board loader does it.
        //
        // **A missing key means the field did not exist when this was saved,
        // not that it should be set to nothing.** Stations saved before 3.4.0
        // carry no live_to at all, and copying that nothing over the top left
        // the board with a destination that was neither of the two and then
        // behaved as audio whatever the user had chosen. So each of these is
        // only touched when the station really has it.
        if let v = station["video_server"] as? String, C.videoServerOrder.contains(v) {
            videoServer = v
        }
        if let v = station["video_host"] as? String { videoHost = v }
        if let v = station["video_key"] as? String { videoKey = v }
        if let v = station["live_to"] as? String, C.liveTo.contains(v) { liveTo = v }
        if let v = station["picture"] as? String, C.pictureSources.contains(v) {
            picture = v
        }
        if let v = station["picture_file"] as? String { pictureFile = v }
        if let v = station["picture_clock"] as? Bool { pictureClock = v }
        if let v = station["camera"] as? String { camera = v }
        if let v = station["screen"] as? String, C.screenChoices.contains(v) { screen = v }
        if let v = station["split_corner"] as? String, C.splitCorners.contains(v) {
            splitCorner = v
        }
        if station["text_places"] != nil {
            textPlaces = Board.textPlaces(from: station["text_places"])
        }
        if station["colour_background"] != nil {
            colourBackground = Board.colour(station["colour_background"], colourBackground)
        }
        if station["colour_text"] != nil {
            colourText = Board.colour(station["colour_text"], colourText)
        }
        if station["colour_accent"] != nil {
            colourAccent = Board.colour(station["colour_accent"], colourAccent)
        }
        if station["video_width"] != nil {
            videoWidth = Board.videoNumber(station["video_width"], videoWidth, 160, 3840)
        }
        if station["video_height"] != nil {
            videoHeight = Board.videoNumber(station["video_height"], videoHeight, 120, 2160)
        }
        if station["video_fps"] != nil {
            videoFPS = Board.videoNumber(station["video_fps"], videoFPS, 1, 60)
        }
        if station["video_bitrate"] != nil {
            videoBitrate = Board.videoNumber(station["video_bitrate"], videoBitrate,
                                             200, 20000)
        }
        return true
    }

    /// Remember the current settings under their own name.
    ///
    /// Saving over a station of the same name replaces it in place rather than
    /// adding a second one, because two stations called the same thing is a
    /// list nobody can use.
    @discardableResult
    func saveStation(_ name: String? = nil) -> [String: Any]? {
        let wanted = (name ?? stream.name).trimmingCharacters(in: .whitespaces)
        guard !wanted.isEmpty else { return nil }
        stream.name = wanted
        let entry = stationSettings()
        // Worth saving: a station saved in Preferences and then cancelled out
        // of must not be gone by the next launch. That is a password somebody
        // has to go and find again.
        dirty = true
        if let at = streamStations.firstIndex(where: { ($0["stream_name"] as? String) == wanted }) {
            streamStations[at] = entry
        } else {
            streamStations.append(entry)
        }
        return entry
    }

    @discardableResult
    func forgetStation(_ name: String) -> Bool {
        let before = streamStations.count
        streamStations.removeAll { ($0["stream_name"] as? String) == name }
        let gone = streamStations.count != before
        if gone { dirty = true }
        return gone
    }

    // ------------------------------------------------------------ describing ---

    var missingSlots: [Slot] { slots.filter { $0.isMissing } }
    var folderSlots: [Slot] { slots.filter { $0.isFolder } }
    var assignedTotal: Int { slots.filter { $0.isAssigned }.count }

    /// Whether a file on disk is one of ours or an old soundboard bank.
    static func describeSource(_ path: String) -> String? {
        guard let data = FileManager.default.contents(atPath: path),
              let raw = try? JSONSerialization.jsonObject(with: data),
              let dict = raw as? [String: Any] else { return nil }
        if (dict["app"] as? String) == C.appName { return "drop deck" }
        if dict["slots"] != nil && dict["sfx_volume"] != nil { return "legacy soundboard" }
        return nil
    }

    // -------------------------------------------------------------- adopting ---

    /// Make this board carry everything `other` does, keeping only this one's
    /// path. The window holds this Board, its Playlist and its DropLibrary by
    /// reference, so opening a file means moving the contents across rather
    /// than swapping the object. Every stored property is listed here on
    /// purpose: one that is missing is a setting that silently survives a File,
    /// Open, which is how the running order used to be lost.
    func replaceContents(with other: Board) {
        slots = other.slots
        for slot in slots { slot.board = self }
        bankNames = other.bankNames
        sfxVolume = other.sfxVolume
        bedVolume = other.bedVolume
        playlistVolume = other.playlistVolume
        ducking = other.ducking
        duckDB = other.duckDB
        bedFadeIn = other.bedFadeIn
        bedFadeOut = other.bedFadeOut
        deviceUID = other.deviceUID
        deviceName = other.deviceName
        bankDevices = other.bankDevices
        announcePlayback = other.announcePlayback
        speechLevel = other.speechLevel
        previewSounds = other.previewSounds
        warnBeforeEnd = other.warnBeforeEnd
        warnSeconds = other.warnSeconds
        cueSound = other.cueSound
        cueLevelDB = other.cueLevelDB
        recordFormat = other.recordFormat
        recordBitrate = other.recordBitrate
        recordFolder = other.recordFolder
        stopPresses = other.stopPresses
        stopFade = other.stopFade
        lastSoundDir = other.lastSoundDir
        lastPlaylistDir = other.lastPlaylistDir
        bankScheme = other.bankScheme
        micDeviceUID = other.micDeviceUID
        micDeviceName = other.micDeviceName
        micOutputUID = other.micOutputUID
        micGainDB = other.micGainDB
        micMonitor = other.micMonitor
        micChannel = other.micChannel
        voiceOn = other.voiceOn
        voiceSettings = other.voiceSettings
        stream = other.stream
        streamStations = other.streamStations
        playlistMonitorOnly = other.playlistMonitorOnly
        sources = other.sources
        globalHotkeysOn = other.globalHotkeysOn
        playlist.tracks = other.playlist.tracks
        playlist.crossfade = other.playlist.crossfade
        drops.replace(with: other.drops)
        unknown = other.unknown
        dirty = true
    }

    /// Scan every folder slot once, on a background thread, so a label is right
    /// before the user reaches it and no scan ever happens on the trigger path.
    func warmFolders() {
        for slot in slots where slot.isFolder { slot.scanFolder() }
    }
}
