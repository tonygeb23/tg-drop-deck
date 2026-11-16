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
import CryptoKit

let boardFormatVersion = 3

final class Board {

    /// Where this board lives on disk.
    ///
    /// **Pointing a board at a different file forgets what it knew about the
    /// old one**, which is Windows' `Board.path` setter exactly. The demo
    /// loaded over a board used to carry the demo's fingerprint against
    /// somebody's own board.json, and a fingerprint compared against the wrong
    /// file answers the wrong question with complete confidence.
    var path: String? {
        didSet {
            if !Board.samePath(path, oldValue) { disk = nil }
        }
    }
    var dirty = false

    /// What `findBeside` repaired by guessing. See `Guesses`.
    var guessed = Guesses()
    /// How many missing sounds opening this board found beside it, for the
    /// Loaded line and the startup line.
    var foundBeside = 0

    /// What the file at `path` looked like when this board last read or
    /// wrote it, or what was there when the path was claimed without reading
    /// it. See `changedOnDisk`. Nil means nothing is known, and nothing known
    /// is never counted as a change.
    private(set) var disk: DiskKnowledge?

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

    /// How a track is named where a listener hears or sees it: see
    /// `TitleFormat`. A Mac first key, `stream_title_format`.
    var titleFormat = TitleFormat.defaultFormat

    var videoServer = "youtube"
    var videoHost = C.rtmpIngest["youtube"] ?? ""
    /// What the VIDEO platform's channel is called, which is not the radio
    /// station's name and must never be printed as though it were. Windows
    /// 3.8.2's `video_name`: "Blindside Radio, on YouTube Live" was the go
    /// live summary putting an Icecast station's name on a YouTube channel.
    /// Empty is the ordinary state and means "just say the platform", because
    /// a name nobody typed is not a name.
    var videoName = ""
    /// Kept only so a board written by an older build round trips. The key
    /// itself belongs in the keychain: see Secrets.swift.
    var videoKey = ""
    /// Which platform `videoKey` belongs to, as `Secrets.videoStation` names
    /// it. The Mac's own key, `mac_video_key_server`, beside Windows'
    /// `video_key`, which is left exactly as Windows wrote it (audit 1,
    /// finding 5). Without it the one board key was offered to whatever
    /// platform was chosen: a YouTube key came up in the Facebook box, and
    /// Check my stream key and Command+B sent it there. A board that has none
    /// (older, or written by Windows) is given the platform it was saved with.
    var videoKeyFor = ""
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

    // -------------------------------- sending the show to another program ---
    //
    // Off until it is set up. This is the ON AIR MIX out of a sound card, and
    // not one more place the pads can be routed to: the main output carries
    // the pads, the beds and the running order, and the microphone and every
    // captured source live on the air mix. See Send.swift.

    var sendOn = false
    /// The Windows spelling, so a person reading the file on either machine
    /// sees the card's name. The Mac resolves by UID, beside it.
    var sendDeviceName: String?
    var sendDeviceUID: String?
    var sendGainDB: Float = 0
    /// The NAME of the one source the send leaves out. Mix minus: a send to
    /// TeamTalk must not carry the TeamTalk capture, or everybody in the call
    /// hears themselves. By name rather than by index, because a source list
    /// gets reordered and an index would silently start excluding somebody
    /// else.
    var sendMinus = ""
    /// Whether the presenter is listening to the send. **Deliberately not
    /// saved**: it is a confidence check you do during a show, like a mute, and
    /// coming back tomorrow to a second copy of everything in your headphones
    /// is worse than pressing the key again. Same as the Windows copy, and the
    /// same rule as the microphone never opening itself at launch.
    var sendMonitor = false

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

    /// Set only by the self test, for the length of a check, so nothing it
    /// does can reach the real board in Application Support.
    static var configDirOverride: String?

    /// The Windows `TGDROPDECK_DATA`, with the same name and the same job:
    /// everything goes to the folder it names instead. It exists so a check
    /// run from the command line can be pointed at a scratch folder, and it
    /// is an escape hatch for anybody who wants their settings elsewhere.
    static let dataEnvironment = "TGDROPDECK_DATA"

    static func configDir() -> String {
        if let override = configDirOverride { return override }
        let named = (ProcessInfo.processInfo.environment[dataEnvironment] ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if !named.isEmpty {
            let folder = ((named as NSString).expandingTildeInPath as NSString).standardizingPath
            try? FileManager.default.createDirectory(atPath: folder,
                                                     withIntermediateDirectories: true)
            // A folder that cannot be written to falls through to the usual
            // place, as it does on Windows, rather than a board that can
            // never be saved.
            if FileManager.default.isWritableFile(atPath: folder) { return folder }
        }
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

        // The send. `send_device_hostapi` is Windows's half of naming a card
        // and is deliberately absent here, so it stays in `unknown` and goes
        // back out untouched for the machine that wrote it.
        d["send_on"] = sendOn
        d["send_device_name"] = sendDeviceName as Any? ?? NSNull()
        d["send_gain_db"] = Double(sendGainDB)
        d["send_minus"] = sendMinus
        d["mac_send_device_uid"] = sendDeviceUID as Any? ?? NSNull()

        // The video half. Written whether or not this board has ever been on
        // a video platform, because a Windows copy reading this file expects
        // the keys to be there and falls back to ITS defaults when they are
        // not, and its defaults are these.
        d["ask_before_live"] = askBeforeLive
        d["video_server"] = videoServer
        d["video_host"] = videoHost
        d["video_name"] = videoName
        d["video_key"] = videoKey
        d["mac_video_key_server"] = videoKeyFor
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
        d["stream_title_format"] = titleFormat
        d["stream_stations"] = streamStations
        // The device NAME in the Windows shape, so that copy can still match
        // on it and so a board is readable by a person.
        d["device_name"] = deviceName as Any? ?? NSNull()
        return d
    }

    @discardableResult
    func save(to target: String? = nil) throws -> String {
        let dest = target ?? path ?? Board.defaultBoardPath()
        let files = FileManager.default
        try files.createDirectory(
            atPath: (dest as NSString).deletingLastPathComponent,
            withIntermediateDirectories: true)
        // **A board marked read only is refused at once.** On a Mac the swap
        // below renames over a read only file quite happily, because what it
        // needs is the folder's permission, not the file's, so a board
        // somebody had deliberately locked was written over. Windows refuses
        // it too, and does not wait a second retrying a setting.
        if files.fileExists(atPath: dest) && !files.isWritableFile(atPath: dest) {
            throw BoardSaveError.readOnly
        }
        // **A sound in the board's own folder, or under it, is written
        // relative to the board, with forward slashes** (Windows 3.9.0), so a
        // board kept with its sounds in a cloud folder opens on every
        // computer that folder reaches. Without it a Mac save turned a
        // portable board back into a Mac only one. Anything elsewhere keeps
        // its full path, and a guess from `findBeside` is never written.
        let base = (dest as NSString).deletingLastPathComponent
        let written = BoardPaths.mapSoundPaths(restoreGuesses(toDict())) {
            BoardPaths.portable($0, base: base)
        }
        let data = try JSONSerialization.data(withJSONObject: written,
                                              options: [.prettyPrinted, .sortedKeys])
        // Write beside the target then swap, so a crash mid save cannot leave a
        // half written board where the real one used to be. Dropbox holds a
        // newly created file open long enough to break the swap, so it retries.
        let temp = dest + ".tmp"
        // Never leave the half of a save that did not land lying beside
        // somebody's board (N6). After a swap that worked there is nothing
        // there to remove, which is fine.
        defer { try? files.removeItem(atPath: temp) }
        try data.write(to: URL(fileURLWithPath: temp))
        var lastError: Error?
        for attempt in 0..<5 {
            do {
                _ = try files.replaceItemAt(
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
            // better than not saving the show, but never over a file somebody
            // else has changed since this board read it: that guard is the
            // whole of fb40 and a last resort does not get to skip it.
            if target == nil && changedOnDisk() { throw lastError }
            try data.write(to: URL(fileURLWithPath: dest))
        }
        path = dest
        dirty = false
        disk = Board.diskStamp(dest).map { .stamp($0) }
        return dest
    }

    // ------------------------------------------------- whose file it is ---
    //
    // Windows 3.8.3, fb40: "if I rename, move or copy the json file, it acts
    // as if it was never set up." A board copied into place while the app was
    // open was saved over by the very act of closing the app to pick it up.
    // So a board remembers what its file looked like, and nothing saves over
    // a file that has changed since.

    /// Two paths naming the same file. APFS is usually case insensitive and
    /// /tmp is /private/tmp, so text alone is not the answer: a file that
    /// exists is compared by identity.
    static func samePath(_ a: String?, _ b: String?) -> Bool {
        guard let a, let b, !a.isEmpty, !b.isEmpty else { return false }
        let left = URL(fileURLWithPath: (a as NSString).expandingTildeInPath)
            .standardizedFileURL.resolvingSymlinksInPath()
        let right = URL(fileURLWithPath: (b as NSString).expandingTildeInPath)
            .standardizedFileURL.resolvingSymlinksInPath()
        if left.path == right.path { return true }
        guard let one = try? left.resourceValues(forKeys: [.fileResourceIdentifierKey])
                .fileResourceIdentifier,
              let two = try? right.resourceValues(forKeys: [.fileResourceIdentifierKey])
                .fileResourceIdentifier else { return false }
        return one.isEqual(two)
    }

    /// The bytes of a file and what they looked like, from ONE open.
    ///
    /// Size and time come from the open handle, after the read, so they
    /// describe exactly the bytes that were read: a separate stat could see a
    /// write that landed in between, and that write would then never be
    /// noticed and would be saved over. Windows' `_stamp_of`, for the same
    /// reason.
    static func readStamped(_ path: String) throws -> (Data, DiskStamp) {
        let fd = open(path, O_RDONLY)
        if fd < 0 {
            let code = errno
            throw (code == EACCES || code == EPERM) ? BoardReadFailure.noPermission
                                                     : BoardReadFailure.missing
        }
        defer { close(fd) }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: false)
        let data: Data
        do { data = try handle.readToEnd() ?? Data() } catch {
            throw BoardReadFailure.noPermission
        }
        var info = stat()
        guard fstat(fd, &info) == 0 else { throw BoardReadFailure.missing }
        return (data, DiskStamp(size: Int64(info.st_size),
                                modified: Board.nanoseconds(info.st_mtimespec),
                                hash: Board.sha1(data)))
    }

    static func nanoseconds(_ t: timespec) -> Int64 {
        Int64(t.tv_sec) * 1_000_000_000 + Int64(t.tv_nsec)
    }

    static func sha1(_ data: Data) -> String {
        Insecure.SHA1.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// Size, time and hash of a file, or nil if it cannot be read.
    static func diskStamp(_ path: String) -> DiskStamp? {
        (try? readStamped(path))?.1
    }

    /// Point this board at a file it did NOT load, writing down what is there.
    ///
    /// The demo at first run, a new board, the demo loaded over a board: each
    /// takes a path without reading it, and knowing nothing about a file is
    /// not the same as owning it. Mark found the first run case on Windows:
    /// with nothing remembered, a board copied into the settings folder while
    /// the demo was open was written over on close. So NOTHING THERE means a
    /// file appearing later is somebody else's, and `unreadable` is a file
    /// that could not be read or even copied aside, which is never written
    /// over at all.
    func claimPath(_ newPath: String?, unreadable: Bool = false) {
        path = newPath
        guard let newPath, !newPath.isEmpty else { return }
        if unreadable {
            disk = .unreadable
        } else if FileManager.default.fileExists(atPath: newPath) {
            disk = Board.diskStamp(newPath).map { .stamp($0) } ?? .unreadable
        } else {
            disk = .nothingThere
        }
    }

    /// Take over what another board knew about ITS file, for a board whose
    /// contents and path have just been replaced by that one's.
    func takeDiskKnowledge(from other: Board) {
        disk = other.disk
    }

    /// Has something other than this app changed the board's file?
    ///
    /// A file that is not there is not a change: saving puts it back, which
    /// is what always happened.
    func changedOnDisk() -> Bool {
        Board.changedOnDisk(path: path, knowledge: disk)
    }

    /// The same question with its inputs handed over, so it can be asked off
    /// the main thread without touching a board the main thread owns.
    static func changedOnDisk(path: String?, knowledge: DiskKnowledge?) -> Bool {
        guard let path, !path.isEmpty, let knowledge else { return false }
        switch knowledge {
        case .nothingThere, .unreadable:
            // Nothing was there and something is now, or what was there was
            // never ours to write over in the first place.
            return FileManager.default.fileExists(atPath: path)
        case .stamp(let was):
            var info = stat()
            guard stat(path, &info) == 0 else { return false }
            // Size and time are the quick question. The hash is the real one,
            // asked only when those two differ, so something that touched the
            // file without changing it does not count as somebody's edit.
            if Int64(info.st_size) == was.size
                && Board.nanoseconds(info.st_mtimespec) == was.modified { return false }
            guard let now = diskStamp(path) else { return false }
            return now.hash != was.hash
        }
    }

    /// What the board's file holds at this moment, for telling one change
    /// from the next. Nil when there is nothing readable there.
    func diskNow() -> DiskStamp? {
        path.flatMap { Board.diskStamp($0) }
    }

    /// Where to keep this board when its own file belongs to somebody else.
    ///
    /// Beside the original, with the time in the name, so both are found in
    /// the same place and neither is ever written over.
    func sidecarPath(now: Date = Date()) -> String {
        Board.besidePath(path ?? Board.defaultBoardPath(), words: "Drop Deck copy", now: now)
    }

    /// "<name> (<words> YYYY-MM-DD HHMM[, n]).<ext>", never an existing file.
    static func besidePath(_ original: String, words: String, now: Date = Date()) -> String {
        let ns = original as NSString
        let ext = ns.pathExtension.isEmpty ? "json" : ns.pathExtension
        let stem = ns.deletingPathExtension
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.dateFormat = "yyyy-MM-dd HHmm"
        let stamp = format.string(from: now)
        var candidate = "\(stem) (\(words) \(stamp)).\(ext)"
        var count = 2
        while FileManager.default.fileExists(atPath: candidate) {
            candidate = "\(stem) (\(words) \(stamp), \(count)).\(ext)"
            count += 1
        }
        return candidate
    }

    // -------------------------------------------------------------- loading ---

    static func load(_ path: String) -> Board? {
        try? read(path).get()
    }

    /// A board, or why it would not load, in words that can be said.
    ///
    /// `load` answered nil for a missing file and an unreadable one alike, so
    /// the demo loaded with board.json's path and the next autosave wrote it
    /// over a board that might only have needed a comma fixing. The reason is
    /// what the startup line says; the file is copied aside before anything
    /// can touch it.
    static func read(_ path: String) -> Result<Board, BoardReadFailure> {
        let data: Data
        let stamp: DiskStamp
        do { (data, stamp) = try readStamped(path) } catch let failure as BoardReadFailure {
            return .failure(failure)
        } catch {
            return .failure(.notRecognised)
        }
        let raw: Any
        do { raw = try JSONSerialization.jsonObject(with: data) } catch {
            return .failure(BoardReadFailure.parsing(data, error))
        }
        guard let dict = raw as? [String: Any] else { return .failure(.notRecognised) }
        let board = Board.from(dict: dict, relativeTo: (path as NSString).deletingLastPathComponent)
        board.path = path
        board.disk = .stamp(stamp)
        // A board carried to another computer usually has its sounds right
        // beside it. Looked for before anybody is asked to relink by hand,
        // bounded, and never written down. Counted as what stopped being
        // missing, so the drops, which are strings, are counted too.
        let before = board.missingCount
        if before > 0 {
            board.findBeside()
            board.foundBeside = before - board.missingCount
        }
        return .success(board)
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
            "send_on", "send_device_name", "send_gain_db", "send_minus",
            "mac_send_device_uid",
            "stream_server", "stream_host", "stream_port", "stream_mount",
            "stream_user", "stream_password", "stream_format", "stream_bitrate",
            "stream_name", "stream_description", "stream_genre", "stream_url",
            "stream_stats_url", "stream_public", "stream_mic", "stream_titles",
            "stream_title_format", "stream_stations",
            "ask_before_live",
            "video_server", "video_host", "video_name", "video_key", "live_to",
            "mac_video_key_server",
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

        // The send. Every value clamped or whitelisted on the way in, the same
        // as everything else here: a board file arrives from anywhere and the
        // gain ends up multiplying somebody's call.
        b.sendOn = dict["send_on"] as? Bool ?? false
        b.sendDeviceName = dict["send_device_name"] as? String
        b.sendDeviceUID = dict["mac_send_device_uid"] as? String
        if let v = dict["send_gain_db"] as? Double, v.isFinite {
            // NaN and Infinity are the reason this is not a bare cast. On
            // Windows they loaded as +24 dB, a sixteenfold boost into
            // somebody's call, because the clamp was written as a comparison
            // and every comparison against NaN is false.
            b.sendGainDB = Float(min(Double(C.maxMicGainDB), max(Double(C.minMicGainDB), v)))
        } else {
            b.sendGainDB = 0
        }
        b.sendMinus = dict["send_minus"] as? String ?? ""
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
        b.titleFormat = TitleFormat.clean(dict["stream_title_format"])
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
        b.videoName = dict["video_name"] as? String ?? ""
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
        // W384-24. A board file is plain JSON that people send each other,
        // and one press of Command B on a board whose address is a folder or
        // an http endpoint would have sent a live microphone wherever its
        // author chose, while the pre-flight read it out as a server.
        // `RTMPClient.parse` refuses such an address as well; this keeps it
        // out of the settings in the first place.
        b.videoHost = Board.rtmpAddress(b.videoHost)
        if b.videoHost.isEmpty {
            b.videoHost = C.rtmpIngest[b.videoServer] ?? ""
        }
        // Whose the board's key is. Recorded when the Mac wrote it; otherwise
        // the platform the board was saved with, which is the one it was
        // typed for.
        if b.videoKey.isEmpty {
            b.videoKeyFor = ""
        } else if let owner = dict["mac_video_key_server"] as? String, !owner.isEmpty {
            b.videoKeyFor = owner
        } else {
            b.videoKeyFor = Secrets.videoStation(server: b.videoServer, host: b.videoHost)
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
                // **Relative on EITHER system** (3.10.0): a Windows drive or
                // share is somebody's absolute path, not one to join onto the
                // board's folder, which gave "<folder>/G:\My Drive\...".
                if let p = slot.filepath, BoardPaths.isRelative(p), let folder {
                    slot.filepath = BoardPaths.resolve(p, folder: folder)
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
        "stream_name", "video_name",
        "stream_server", "stream_host", "stream_port",
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
            "video_name": videoName,
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

    /// What a saved station is called in a menu. **Never an empty label**:
    /// Windows asserted on one while the window was being built, so a board
    /// whose server was set up without a station name could not be opened at
    /// all, and on a Mac an empty item is simply silent under VoiceOver. A
    /// board from before saved setups gets exactly that, a setup made from its
    /// server with whatever name it had, which may be none. Windows' words.
    static func stationLabel(_ name: String, at offset: Int) -> String {
        name.isEmpty ? "Station \(offset + 1), no name" : name
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
        // A platform or a picture the station names that this build does not
        // know becomes YouTube and the card, as Windows 3.8.4 does it
        // (W384-25), so one station loads the same way on both machines.
        if let raw = station["video_server"], !(raw is NSNull) {
            let v = raw as? String ?? ""
            videoServer = C.videoServerOrder.contains(v) ? v : "youtube"
        }
        if let v = station["video_host"] as? String { videoHost = v }
        // Only when the station has one: a station saved before 3.8.2 has no
        // channel name, and that is not the same as asking for none.
        if let v = station["video_name"] as? String { videoName = v }
        if let v = station["video_key"] as? String {
            videoKey = v
            // A station's key is the key of the platform that station names.
            videoKeyFor = v.isEmpty ? "" : Secrets.videoStation(server: videoServer,
                                                                host: videoHost)
        }
        if let v = station["live_to"] as? String, C.liveTo.contains(v) { liveTo = v }
        if let raw = station["picture"], !(raw is NSNull) {
            let v = raw as? String ?? ""
            picture = C.pictureSources.contains(v) ? v : C.pictureCard
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
        // W384-25. The board loader whitelists the address and a station went
        // round it, so a board that could not smuggle a path in through
        // video_host could smuggle it in through a saved station. Windows'
        // `load_station` does exactly this, and leaves the address empty
        // rather than putting the platform's default back.
        videoHost = Board.rtmpAddress(videoHost)
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

    /// Every sound this board cannot find: pads, running order and drops.
    /// "Loaded, 20 sounds" counted the pads alone, so a board whose whole
    /// running order was missing opened without a word about it. That is
    /// how Ali Moosa's playlist went missing in silence.
    var missingCount: Int {
        missingSlots.count + playlist.missing.count + drops.missing.count
    }

    // ------------------------------------------------------ relinking ---

    /// Repair what is missing out of `index`. The number repaired.
    ///
    /// Pads match by file name and, with `filesForFolders`, by name without
    /// its extension, as Windows has always done; a pad that held a folder is
    /// repaired only with a folder. The running order and the drops match by
    /// file name. Every name is taken after EITHER slash, which is the whole
    /// of Siena's "16 sounds still missing".
    @discardableResult
    func relinkFrom(_ index: BoardPaths.Index, filesForFolders: Bool = true) -> Int {
        var repaired = playlist.relink(using: index.files).count
        repaired += drops.relink(using: index.files).count
        for slot in missingSlots {
            let base = BoardPaths.basename(slot.filepath)
            let stem = (base as NSString).deletingPathExtension
            let found: String?
            if slot.folderCount != nil {
                found = index.folders[base.lowercased()]
            } else if filesForFolders {
                found = index.files[base.lowercased()] ?? index.files[stem.lowercased()]
            } else {
                // Exact names only. A pad saved with no folder count may have
                // been a folder, so a name with no extension is not matched to
                // a file at all.
                found = (base as NSString).pathExtension.isEmpty ? nil : index.files[base.lowercased()]
            }
            guard let found else { continue }
            slot.filepath = found
            if slot.folderCount != nil || slot.isFolder {
                slot.scanFolder(force: true)
            } else if slot.duration == nil {
                slot.duration = AudioFile.probe(found)?.duration
            }
            repaired += 1
        }
        return repaired
    }

    /// A relink somebody asked for, out of a folder they chose. What it finds
    /// is no longer a guess, so it is written down like any other path.
    @discardableResult
    func relink(using index: BoardPaths.Index) -> Int {
        guessed.clear()
        let repaired = relinkFrom(index)
        if repaired > 0 { dirty = true }
        return repaired
    }

    /// Repair what is missing out of the board's own folder, in memory.
    ///
    /// Windows' `find_beside`, and its three rules (Mark, 16 October 2026).
    /// **It is a guess, so it is never written down**: `save` puts the
    /// original path back and the board is not marked changed. **Exact file
    /// names only**: no name without its extension, which turned a missing
    /// applause.wav into a different applause.flac, and no file for a folder.
    /// **Never longer than the bound**, whatever the disk does.
    @discardableResult
    func findBeside() -> Int {
        guard let path, missingCount > 0 else { return 0 }
        let folder = (path as NSString).deletingLastPathComponent
        guard let index = BoardPaths.indexWithin(
            C.besideSearchSeconds + 0.5, folder, depth: C.besideSearchDepth,
            seconds: C.besideSearchSeconds, entries: C.besideSearchEntries) else { return 0 }
        let wasDirty = dirty
        var before: [ObjectIdentifier: String] = [:]
        for slot in slots { if let p = slot.filepath { before[ObjectIdentifier(slot)] = p } }
        for track in playlist.tracks { before[ObjectIdentifier(track)] = track.filepath }
        let dropsBefore = drops.paths
        let repaired = relinkFrom(index, filesForFolders: false)
        for slot in slots {
            let id = ObjectIdentifier(slot)
            if let was = before[id], let now = slot.filepath, was != now {
                guessed.items[id] = (now, was)
            }
        }
        for track in playlist.tracks {
            let id = ObjectIdentifier(track)
            if let was = before[id], was != track.filepath {
                guessed.items[id] = (track.filepath, was)
            }
        }
        for (at, pair) in zip(dropsBefore, drops.paths).enumerated() where pair.0 != pair.1 {
            guessed.drops[at] = (pair.1, pair.0)
        }
        dirty = wasDirty
        return repaired
    }

    /// The board file's own paths put back over `findBeside`'s guesses, only
    /// where the item still holds the guess: anything reassigned or relinked
    /// since is somebody's decision and is written as it is.
    func restoreGuesses(_ data: [String: Any]) -> [String: Any] {
        guard !guessed.isEmpty else { return data }
        var out = data
        if var rows = data["slots"] as? [[String: Any]] {
            for (at, slot) in slots.enumerated() where at < rows.count {
                if let held = guessed.items[ObjectIdentifier(slot)],
                   rows[at]["filepath"] as? String == held.guess {
                    rows[at]["filepath"] = held.original
                }
            }
            out["slots"] = rows
        }
        if var pl = data["playlist"] as? [String: Any], var rows = pl["tracks"] as? [[String: Any]] {
            for (at, track) in playlist.tracks.enumerated() where at < rows.count {
                if let held = guessed.items[ObjectIdentifier(track)],
                   rows[at]["filepath"] as? String == held.guess {
                    rows[at]["filepath"] = held.original
                }
            }
            pl["tracks"] = rows
            out["playlist"] = pl
        }
        if var dr = data["drops"] as? [String: Any], var paths = dr["paths"] as? [String] {
            for (at, path) in paths.enumerated() {
                if let held = guessed.drops[at], path == held.guess { paths[at] = held.original }
            }
            dr["paths"] = paths
            out["drops"] = dr
        }
        return out
    }
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
        titleFormat = other.titleFormat
        streamStations = other.streamStations
        playlistMonitorOnly = other.playlistMonitorOnly
        sources = other.sources
        globalHotkeysOn = other.globalHotkeysOn

        // The video half. **Not one of these was here until 3.7.1**, so from
        // the day video landed, File, Open loaded a board's picture, colours,
        // platform and stream size correctly and then threw every one of them
        // away: you kept the PREVIOUS board's shot and the previous board's
        // destination, and the only sign was on the air. This is the bug this
        // method's own comment warns about, in the code the comment is on.
        askBeforeLive = other.askBeforeLive
        videoServer = other.videoServer
        videoHost = other.videoHost
        videoName = other.videoName
        videoKey = other.videoKey
        videoKeyFor = other.videoKeyFor
        liveTo = other.liveTo
        picture = other.picture
        pictureFile = other.pictureFile
        pictureClock = other.pictureClock
        camera = other.camera
        screen = other.screen
        splitCorner = other.splitCorner
        textPlaces = other.textPlaces
        colourBackground = other.colourBackground
        colourText = other.colourText
        colourAccent = other.colourAccent
        visionProvider = other.visionProvider
        visionModel = other.visionModel
        videoWidth = other.videoWidth
        videoHeight = other.videoHeight
        videoFPS = other.videoFPS
        videoBitrate = other.videoBitrate
        framingLevel = other.framingLevel

        // The send. `sendMonitor` is deliberately absent: it is never saved.
        sendOn = other.sendOn
        sendDeviceName = other.sendDeviceName
        sendDeviceUID = other.sendDeviceUID
        sendGainDB = other.sendGainDB
        sendMinus = other.sendMinus
        playlist.tracks = other.playlist.tracks
        playlist.crossfade = other.playlist.crossfade
        drops.replace(with: other.drops)
        unknown = other.unknown
        guessed = other.guessed
        foundBeside = other.foundBeside
        // **The arriving board's own state, never "changed".** This said
        // `dirty = true` until 3.10.0, so every File, Open and every File,
        // New wrote the board out two seconds later whether or not anybody
        // had touched it, and with the old path still in place after New
        // that save was Siena's lost board.
        dirty = other.dirty
    }

    // ---------------------------------------------------- the stream key ---

    /// The video stream key that is really in force: the keychain's, or the
    /// one in the board file when the keychain would not keep it.
    ///
    /// **Every place the key is read asks this, in this order.** Windows
    /// found the other shape the hard way: the Preferences box read the
    /// credential store alone while the streamer read the store OR the board,
    /// so on a machine whose store refused a write the box came up empty over
    /// a key that was working, and OK, seeing an empty box, forgot it.
    func videoKeyInForce() -> String {
        videoKeyInForce(server: videoServer, host: videoHost)
    }

    /// The key in force for a platform that may not be the board's own yet:
    /// Preferences asks this as the platform popup moves.
    func videoKeyInForce(server: String, host: String) -> String {
        Board.keyInForce(keychain: Secrets.fetchVideoKey(
            server: server, host: host, stationName: stream.name),
            board: videoKey, boardFor: videoKeyOwner,
            station: Secrets.videoStation(server: server, host: host))
    }

    /// Whose the board key is, never empty while there is a key.
    var videoKeyOwner: String {
        if videoKey.isEmpty { return "" }
        return videoKeyFor.isEmpty ? Secrets.videoStation(server: videoServer, host: videoHost)
                                   : videoKeyFor
    }

    /// The read order, as arithmetic, so it can be asserted. The board's key
    /// is offered ONLY to the platform it was saved for (audit 1, finding 5),
    /// the rule `Secrets.fetchVideoKey` already keeps for the keychain.
    static func keyInForce(keychain: String, board: String, boardFor: String,
                           station: String) -> String {
        if !keychain.isEmpty { return keychain }
        return !board.isEmpty && boardFor == station ? board : ""
    }

    // ------------------------------------------------------ the address ---

    /// An RTMP address out of a board file, or "" so the default is used.
    ///
    /// Windows 3.8.4's `_rtmp_address`, rule for rule, including how Python's
    /// `urlparse` decides what the scheme is (letters first, then letters,
    /// digits, plus, minus or dot, up to the first colon), because the two
    /// copies read one file and must keep and drop the same addresses.
    ///
    /// **An address with NO scheme is kept, and that is on purpose.** It is
    /// what somebody typed who left the rtmp off, and erasing it means they
    /// open the app to an empty box with nothing to correct. It cannot reach
    /// a server either way, because `RTMPClient.parse` refuses anything that
    /// is not rtmp or rtmps. What must never survive is a scheme that names
    /// another kind of output, or a path, because those are the shapes that
    /// would have worked.
    static func rtmpAddress(_ value: String) -> String {
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return "" }
        let scheme = pythonScheme(text)
        if scheme == "rtmp" || scheme == "rtmps" { return text }
        let chars = Array(text)
        let drivePath = chars.count >= 3 && chars[1] == ":" && chars[2] == "\\"
        if !scheme.isEmpty || text.hasPrefix("\\\\") || drivePath || text.hasPrefix("/") {
            return ""
        }
        return text
    }

    /// The scheme Python's `urllib.parse.urlsplit` would find, lower case, or
    /// "" when it finds none.
    static func pythonScheme(_ text: String) -> String {
        guard let colon = text.firstIndex(of: ":"), colon != text.startIndex else { return "" }
        let head = text[text.startIndex..<colon]
        guard let first = head.first, first.isASCII, first.isLetter else { return "" }
        let allowed = Set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-.")
        guard head.allSatisfy({ allowed.contains($0) }) else { return "" }
        return head.lowercased()
    }

    /// Scan every folder slot once, on a background thread, so a label is right
    /// before the user reaches it and no scan ever happens on the trigger path.
    func warmFolders() {
        for slot in slots where slot.isFolder { slot.scanFolder() }
    }
}

// ------------------------------------------------------ the file on disk ---

/// Size, modification time in nanoseconds, and SHA-1 of a board file's bytes.
struct DiskStamp: Equatable {
    let size: Int64
    let modified: Int64
    let hash: String
}

/// What a board knows about the file at its path. Windows' `_disk`, with its
/// two markers spelled as cases rather than strings.
enum DiskKnowledge: Equatable {
    /// Read or written by this board, and this is what it looked like.
    case stamp(DiskStamp)
    /// There was no file when the path was claimed, so one appearing later is
    /// somebody else's.
    case nothingThere
    /// There was one this board could not read, so it is never written over.
    case unreadable
}

/// Why a board file would not load, in a few words for the startup line.
///
/// Never an error's class name or code: "NSCocoaErrorDomain 3840" is noise
/// read aloud. Windows' `_short_reason`, sentence for sentence.
enum BoardReadFailure: Error, Equatable {
    case missing
    case noPermission
    case notText
    case mistake(line: Int)
    case notRecognised

    var reason: String {
        switch self {
        case .mistake(let line): return "there is a mistake in it on line \(line)"
        case .notText: return "it is not saved as text Drop Deck can read"
        case .noPermission: return "macOS would not let Drop Deck open it"
        case .missing, .notRecognised: return "Drop Deck does not recognise what is in it"
        }
    }

    /// What a JSON parser's complaint means, from the bytes it was given.
    ///
    /// The line is counted from the byte offset the parser reports rather
    /// than read out of its English, which is not a promise. A file that is
    /// not UTF-8 at all is the text case, which is what Windows' reading as
    /// `utf-8-sig` would have refused.
    static func parsing(_ data: Data, _ error: Error) -> BoardReadFailure {
        var body = data
        if body.starts(with: [0xEF, 0xBB, 0xBF]) { body = body.dropFirst(3) }
        if String(data: body, encoding: .utf8) == nil { return .notText }
        let info = (error as NSError).userInfo
        if let index = info["NSJSONSerializationErrorIndex"] as? Int, index >= 0 {
            let upto = data.prefix(min(index, data.count))
            return .mistake(line: upto.reduce(1) { $0 + ($1 == 0x0A ? 1 : 0) })
        }
        if let said = info["NSDebugDescription"] as? String,
           let range = said.range(of: "line ") {
            let digits = said[range.upperBound...].prefix { $0.isNumber }
            if let line = Int(digits) { return .mistake(line: line) }
        }
        return .notRecognised
    }
}

enum BoardSaveError: Error, LocalizedError {
    case readOnly

    var errorDescription: String? {
        switch self {
        case .readOnly: return "The file is marked read only"
        }
    }
}
