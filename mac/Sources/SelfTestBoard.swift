// The checks for "a board file is the user's" (Windows 3.8.2 to 3.8.4 on the
// board side): the channel name, the address whitelist, which board opens,
// never saving over a changed board, an unreadable board copied aside, the
// stream key's read order and what OK does with it, and the camera that was
// not plugged in.
//
// Every one of these works on REAL files in a scratch folder, and the config
// folder is pointed at that scratch folder for the whole section, so nothing
// here can reach the real board in Application Support.

import Foundation

extension SelfTest {

    func runBoardFileChecks() {
        let scratch = (NSTemporaryDirectory() as NSString)
            .appendingPathComponent("dropdeck-selftest-boards-\(ProcessInfo.processInfo.processIdentifier)")
        try? FileManager.default.removeItem(atPath: scratch)
        try? FileManager.default.createDirectory(atPath: scratch, withIntermediateDirectories: true)
        let before = Board.configDirOverride
        let config = (scratch as NSString).appendingPathComponent("config")
        try? FileManager.default.createDirectory(atPath: config, withIntermediateDirectories: true)
        Board.configDirOverride = config
        defer {
            Board.configDirOverride = before
            try? FileManager.default.removeItem(atPath: scratch)
        }

        testVideoName()
        testRTMPAddress()
        testStationLabels()
        testFingerprint(scratch)
        testReadReasons(scratch)
        testSavingSafely(scratch)
        testNeverOverAChangedBoard(scratch, config: config)
        testClaimingAPath(scratch, config: config)
        testRememberedBoard(scratch)
        testUnreadableAtStartup(scratch)
        testComingBack(scratch, config: config)
        testStartupWords()
        testStreamKeyRules()
        testCameraPlaceholder()
        runBoardTravelChecks(scratch)
    }

    // ------------------------------------------------------ the channel ---

    private func testVideoName() {
        out.append("")
        out.append("The video channel has a name of its own (Windows 3.8.2)")
        let b = Board()
        b.stream.name = "Blindside Radio"
        b.videoName = "Tony Gebhard"
        let back = Board.from(dict: b.toDict(), relativeTo: nil)
        check("video_name is written to the board file",
              (b.toDict()["video_name"] as? String) == "Tony Gebhard")
        check("and both names survive a save and a load",
              back.videoName == "Tony Gebhard" && back.stream.name == "Blindside Radio",
              "\(back.videoName) / \(back.stream.name)")
        check("an absent video_name is empty, never the station's name",
              Board.from(dict: ["stream_name": "Blindside Radio"], relativeTo: nil).videoName == "")

        let cleaned = Board.cleanStations([["stream_name": "X", "video_name": "Y"]])
        check("a saved station keeps its channel name when a board is opened",
              cleaned.first?["video_name"] as? String == "Y", "\(cleaned)")
        b.saveStation("Round Trip")
        let saved = b.streamStations.first { ($0["stream_name"] as? String) == "Round Trip" }
        check("saving a station writes the channel name into it",
              saved?["video_name"] as? String == "Tony Gebhard")
        b.videoName = "Somebody Else"
        check("and loading it brings the channel name back",
              b.loadStation("Round Trip") && b.videoName == "Tony Gebhard", b.videoName)
        b.streamStations.append(["stream_name": "Old", "stream_host": "old.example.com"])
        b.videoName = "Kept"
        _ = b.loadStation("Old")
        check("a station saved before 3.8.2 leaves the channel name alone",
              b.videoName == "Kept", b.videoName)

        let other = Board()
        other.replaceContents(with: back)
        check("File, Open carries the channel name across", other.videoName == "Tony Gebhard")
    }

    // ------------------------------------------------------ the address ---

    private func testRTMPAddress() {
        out.append("")
        out.append("A board file cannot point the show at something that is not RTMP (W384-24, 25)")
        let dropped = ["/Users/Public", "C:\\Users\\Public", "C:/Users/Public",
                       "\\\\server\\share", "file:///etc/passwd", "http://evil.example/upload",
                       "udp://10.0.0.1:1234", "localhost:1935/live"]
        for address in dropped {
            check("dropped: \(address)", Board.rtmpAddress(address) == "",
                  Board.rtmpAddress(address))
        }
        let kept = ["rtmp://live.example.com/app", "RTMPS://a.rtmps.youtube.com/live2",
                    "live.example.com/app", "  rtmp://x.example/live  "]
        for address in kept {
            check("kept: \(address.trimmingCharacters(in: .whitespaces))",
                  Board.rtmpAddress(address) == address.trimmingCharacters(in: .whitespaces),
                  Board.rtmpAddress(address))
        }

        let loaded = Board.from(dict: ["video_server": "rtmp", "video_host": "/Users/Public"],
                                relativeTo: nil)
        check("a path in a board file is dropped and the platform's default used",
              loaded.videoHost == (C.rtmpIngest["rtmp"] ?? ""), loaded.videoHost)
        check("and the default is never the path",
              !loaded.videoHost.contains("Public"), loaded.videoHost)

        let b = Board()
        b.videoHost = C.rtmpIngest["youtube"] ?? ""
        b.streamStations = [["stream_name": "Their Setup", "video_server": "rtmp",
                             "video_host": "C:/Users/Public", "live_to": C.liveToVideo]]
        _ = b.loadStation("Their Setup")
        check("a saved station cannot smuggle a path in either",
              !b.videoHost.contains("Public"), b.videoHost)
        b.streamStations = [["stream_name": "Typed", "video_server": "rtmp",
                             "video_host": "live.example.com/app"]]
        _ = b.loadStation("Typed")
        check("but an address somebody typed without rtmp is kept, to be corrected",
              b.videoHost == "live.example.com/app", b.videoHost)
        b.videoServer = "facebook"
        b.picture = C.pictureCamera
        b.streamStations = [["stream_name": "Junk", "video_server": "vimeo",
                             "picture": "hologram"]]
        _ = b.loadStation("Junk")
        check("a station naming a platform nobody knows lands on YouTube, as on Windows",
              b.videoServer == "youtube", b.videoServer)
        check("and a picture nobody knows lands on the card",
              b.picture == C.pictureCard, b.picture)
    }

    private func testStationLabels() {
        out.append("")
        out.append("A saved station with no name still has something to say")
        check("a nameless station is called by its place",
              Board.stationLabel("", at: 0) == "Station 1, no name")
        check("a named one by its name", Board.stationLabel("Blindside", at: 3) == "Blindside")
        // A board from before saved setups gets one made from its server,
        // with whatever name it had, which may be none. Windows does the same.
        let old = Board.from(dict: ["stream_host": "radio.example.com"], relativeTo: nil)
        check("a board from before stations gets its server as a station, name or not",
              old.streamStations.count == 1
                && (old.streamStations.first?["stream_name"] as? String) == "")
        check("and loading that nameless station works", old.loadStation(""))
    }

    // --------------------------------------------------- the fingerprint ---

    private func write(_ path: String, _ text: String) {
        try? text.write(toFile: path, atomically: false, encoding: .utf8)
    }

    private func contents(_ path: String) -> String {
        (try? String(contentsOfFile: path, encoding: .utf8)) ?? "<missing>"
    }

    /// Change a file's modification time without changing a byte of it.
    private func touchFile(_ path: String, by seconds: TimeInterval) {
        let later = Date().addingTimeInterval(seconds)
        try? FileManager.default.setAttributes([.modificationDate: later], ofItemAtPath: path)
    }

    private func testFingerprint(_ scratch: String) {
        out.append("")
        out.append("A board knows what its file looked like")
        let path = (scratch as NSString).appendingPathComponent("Fingerprint.json")
        let b = Board()
        b.stream.host = "mine.example.org"
        _ = try? b.save(to: path)
        check("a board this app just wrote has not changed on disk", !b.changedOnDisk())
        check("and what it remembers is exactly what is there",
              b.disk == .stamp(Board.diskStamp(path)!))
        _ = try? b.save()
        check("saving it again is still ours", !b.changedOnDisk())
        touchFile(path, by: 30)
        check("a file touched without being changed is not somebody's edit",
              !b.changedOnDisk())
        var theirs = (try? JSONSerialization.jsonObject(
            with: Data(contentsOf: URL(fileURLWithPath: path)))) as? [String: Any] ?? [:]
        theirs["stream_host"] = "theirs.example.org"
        if let data = try? JSONSerialization.data(withJSONObject: theirs) {
            try? data.write(to: URL(fileURLWithPath: path))
        }
        check("one written over it by something else has", b.changedOnDisk())
        b.path = (scratch as NSString).appendingPathComponent("Elsewhere.json")
        check("a board pointed at another file forgets the old fingerprint",
              b.disk == nil && !b.changedOnDisk())
        let reread = Board.load(path)
        check("a board read from a file knows that file", reread?.disk != nil
              && reread?.changedOnDisk() == false)
        check("the same path by another spelling is the same file",
              Board.samePath(path, (scratch as NSString).appendingPathComponent("./Fingerprint.json")))
        check("and two files are two files",
              !Board.samePath(path, (scratch as NSString).appendingPathComponent("Other.json")))
    }

    private func testReadReasons(_ scratch: String) {
        out.append("")
        out.append("A board that will not load says why, in words")
        let broken = (scratch as NSString).appendingPathComponent("Broken.json")
        write(broken, "{\n\"app\": \"TG Drop Deck\",\n\"stream_host\": \"x\"\n\"x\": 1}")
        if case .failure(let why) = Board.read(broken) {
            check("a mistake is placed on its line", why == .mistake(line: 4), "\(why)")
            check("and said as Windows says it",
                  why.reason == "there is a mistake in it on line 4", why.reason)
        } else {
            check("a board with a mistake in it does not load", false)
        }
        let binary = (scratch as NSString).appendingPathComponent("Binary.json")
        try? Data([0xff, 0xfe, 0x00, 0x41, 0x80, 0x81]).write(to: URL(fileURLWithPath: binary))
        if case .failure(let why) = Board.read(binary) {
            check("a file that is not text is said to be that", why == .notText, "\(why)")
        } else { check("a file that is not text does not load", false) }
        let list = (scratch as NSString).appendingPathComponent("List.json")
        write(list, "[1, 2, 3]")
        if case .failure(let why) = Board.read(list) {
            check("JSON that is not a board is not recognised",
                  why.reason == "Drop Deck does not recognise what is in it", why.reason)
        } else { check("a list is not a board", false) }
        let bom = (scratch as NSString).appendingPathComponent("Notepad.json")
        var data = Data([0xEF, 0xBB, 0xBF])
        data.append(Data("{\"app\": \"TG Drop Deck\", \"stream_host\": \"bom.example.org\"}".utf8))
        try? data.write(to: URL(fileURLWithPath: bom))
        check("a board with a byte order mark loads",
              Board.load(bom)?.stream.host == "bom.example.org")
        check("a missing board is missing", Board.load(
            (scratch as NSString).appendingPathComponent("Nowhere.json")) == nil)
        check("no reason is ever an error code",
              ![BoardReadFailure.missing, .noPermission, .notText, .mistake(line: 2), .notRecognised]
                .contains { $0.reason.contains("3840") || $0.reason.contains("Error") })
    }

    private func testSavingSafely(_ scratch: String) {
        out.append("")
        out.append("A save leaves nothing behind and respects a locked file")
        let folder = (scratch as NSString).appendingPathComponent("readonly")
        try? FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
        let locked = (folder as NSString).appendingPathComponent("ReadOnly.json")
        _ = try? Board().save(to: locked)
        let original = contents(locked)
        try? FileManager.default.setAttributes([.posixPermissions: 0o444], ofItemAtPath: locked)
        let began = Date()
        var refused = false
        do { _ = try Board().save(to: locked) } catch { refused = true }
        let took = Date().timeIntervalSince(began)
        try? FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: locked)
        check("a board marked read only is refused, not written over",
              refused && contents(locked) == original)
        check("at once, not after a second of retries", took < 0.5, String(format: "%.2f s", took))
        check("and the half written save is not left beside it",
              !FileManager.default.fileExists(atPath: locked + ".tmp"))
        let fine = (scratch as NSString).appendingPathComponent("Fine.json")
        _ = try? Board().save(to: fine)
        check("an ordinary save leaves no .tmp either",
              !FileManager.default.fileExists(atPath: fine + ".tmp"))

        let b = Board()
        b.path = (scratch as NSString).appendingPathComponent("Show.json")
        let when = DateComponents(calendar: Calendar(identifier: .gregorian),
                                  year: 2026, month: 9, day: 29, hour: 14, minute: 5).date!
        let first = b.sidecarPath(now: when)
        check("the copy beside a board is named for what it is and when",
              (first as NSString).lastPathComponent == "Show (Drop Deck copy 2026-09-29 1405).json",
              (first as NSString).lastPathComponent)
        write(first, "{}")
        let second = b.sidecarPath(now: when)
        check("and never over an earlier copy",
              (second as NSString).lastPathComponent == "Show (Drop Deck copy 2026-09-29 1405, 2).json",
              (second as NSString).lastPathComponent)
    }

    // ------------------------------------------ never over a changed board ---

    private func testNeverOverAChangedBoard(_ scratch: String, config: String) {
        out.append("")
        out.append("A board changed outside the app is never saved over (fb40)")
        let live = (scratch as NSString).appendingPathComponent("Live.json")
        let b = Board()
        b.stream.host = "mine.example.org"
        let keeper = BoardKeeper(board: b, configDir: config)
        check("Save board as writes where it was asked",
              keeper.save(to: live) == .saved(live) && FileManager.default.fileExists(atPath: live))
        check("and remembers it",
              Board.samePath(BoardFiles.rememberedBoardPath(configDir: config), live))
        let theirs = "{\"app\": \"TG Drop Deck\", \"stream_host\": \"theirs.example.org\"}"
        write(live, theirs)
        b.dirty = false
        let closing = keeper.saveForClose()
        check("closing does not write over a board copied in meanwhile",
              closing == .leftAlone(live) && contents(live) == theirs, "\(closing)")
        check("nor does an autosave", keeper.save() == .leftAlone(live) && contents(live) == theirs)
        check("which is said when asked for, and not by the autosave",
              BoardKeeper.sentence(.leftAlone(live), quiet: false)
                == "Live was changed outside Drop Deck, so it has not been saved over. "
                 + "File, Open board opens the new one"
                && BoardKeeper.sentence(.leftAlone(live), quiet: true) == nil)

        b.dirty = true
        let kept = keeper.save()
        guard case .keptBeside(let original, let copy) = kept else {
            check("with changes on screen as well, those go beside it", false, "\(kept)")
            return
        }
        let name = (copy as NSString).lastPathComponent
        check("with changes on screen as well, those go beside it under a new name",
              original == live && copy != live && FileManager.default.fileExists(atPath: copy)
                && name.hasPrefix("Live (Drop Deck copy ") && name.hasSuffix(").json"), name)
        check("the copy holds what was on screen",
              Board.load(copy)?.stream.host == "mine.example.org")
        check("the file on disk is still theirs", contents(live) == theirs)
        check("the file that came in is still the one that opens next time",
              Board.samePath(BoardFiles.rememberedBoardPath(configDir: config), live))
        check("and it is said, in Windows' words",
              BoardKeeper.sentence(kept, quiet: true)
                == "Live was changed outside Drop Deck, so it was not saved over. Your changes "
                 + "are in a copy beside it, and the new Live opens next time")

        // Quitting saves twice, once from the window and once from the app.
        let copyBefore = contents(copy)
        let copies = { (try? FileManager.default.contentsOfDirectory(atPath: scratch))?
            .filter { $0.hasPrefix("Live (Drop Deck copy") }.count ?? 0 }
        let count = copies()
        _ = keeper.saveForClose()
        _ = keeper.saveForClose()
        check("saving twice on the way out makes no second copy", copies() == count,
              "\(count) then \(copies())")
        check("and changes nothing that was kept",
              contents(live) == theirs && Board.load(copy)?.stream.host == "mine.example.org"
                && contents(copy) == copyBefore)
        check("and still opens the one that came in next time",
              Board.samePath(BoardFiles.rememberedBoardPath(configDir: config), live))
    }

    private func testClaimingAPath(_ scratch: String, config: String) {
        out.append("")
        out.append("A path taken without reading it is claimed, never assumed")
        let spot = (scratch as NSString).appendingPathComponent("Claimed.json")
        let demo = Board()
        demo.stream.host = "demo.example.org"
        demo.claimPath(spot)
        check("claiming a path with nothing there remembers that",
              demo.disk == .nothingThere && !demo.changedOnDisk())
        let appeared = "{\"app\": \"TG Drop Deck\", \"stream_host\": \"copied.example.org\"}"
        write(spot, appeared)
        check("and something appearing there later is somebody else's", demo.changedOnDisk())
        let keeper = BoardKeeper(board: demo, configDir: config)
        demo.dirty = false
        _ = keeper.saveForClose()
        check("closing does not write the demo over it", contents(spot) == appeared)
        demo.dirty = true
        _ = keeper.save()
        check("not even with changes of its own", contents(spot) == appeared)
        demo.claimPath(spot)
        check("claiming what is there takes it as ours", !demo.changedOnDisk())

        let precious = (scratch as NSString).appendingPathComponent("Precious.json")
        let broken = "{\"app\": \"TG Drop Deck\", \"stream_host\": \"precious\""
        write(precious, broken)
        let locked = Board()
        locked.claimPath(precious, unreadable: true)
        let lockedKeeper = BoardKeeper(board: locked, configDir: config)
        locked.dirty = true
        _ = lockedKeeper.save()
        _ = lockedKeeper.saveForClose()
        check("a board claimed as unreadable is never written over", contents(precious) == broken)
    }

    // ---------------------------------------------------- which board opens ---

    private func testRememberedBoard(_ scratch: String) {
        out.append("")
        out.append("The board that was open last is the one that opens (fb40)")
        let config = (scratch as NSString).appendingPathComponent("remember")
        try? FileManager.default.createDirectory(atPath: config, withIntermediateDirectories: true)
        check("nothing remembered is nothing", BoardFiles.rememberedBoardPath(configDir: config) == nil)
        let show = (scratch as NSString).appendingPathComponent("My Show.json")
        let b = Board()
        b.stream.host = "radio.example.org"
        _ = try? b.save(to: show)
        check("a board is remembered", BoardFiles.rememberBoardPath(show, configDir: config))
        check("and read back", Board.samePath(BoardFiles.rememberedBoardPath(configDir: config), show))
        let note = (config as NSString).appendingPathComponent(BoardFiles.lastBoardFile)
        let raw = (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: note))))
            as? [String: Any]
        check("in the Windows file and shape", raw?.keys.sorted() == ["path"])

        let start = BoardFiles.loadStartup(configDir: config, demoPath: nil)
        check("the next start opens the board that was open, not board.json",
              Board.samePath(start.board.path, show), start.board.path ?? "nil")
        check("so its streaming is still set up", start.board.stream.host == "radio.example.org")
        check("with nothing to say about it", start.note.isEmpty, start.note)
        check("and its name is said, because it is not the usual one",
              BoardFiles.boardName(start.board.path, configDir: config) == "My Show")
        check("the command line checks open it too",
              Board.samePath(BoardFiles.boardToOpen(configDir: config), show))

        let moved = show + ".moved"
        try? FileManager.default.moveItem(atPath: show, toPath: moved)
        let away = BoardFiles.loadStartup(configDir: config, demoPath: nil)
        check("a board that has been moved away is said, not silently replaced",
              away.note.contains("My Show") && away.note.contains("is not in "), away.note)
        check("naming the folder by its own name, never the whole path",
              away.note.contains((scratch as NSString).lastPathComponent)
                && !away.note.contains("/"), away.note)
        check("with the way to find it", away.note.contains("File, Open board finds it"), away.note)
        check("and it stays remembered for next time", away.pinned == show)
        let keeper = BoardKeeper(board: away.board, configDir: config, pinned: away.pinned)
        away.board.dirty = true
        _ = keeper.saveForClose()
        check("even after this session saves somewhere else",
              Board.samePath(BoardFiles.rememberedBoardPath(configDir: config), show),
              BoardFiles.rememberedBoardPath(configDir: config) ?? "nil")
        check("the command line checks fall back to board.json while it is away",
              Board.samePath(BoardFiles.boardToOpen(configDir: config),
                             BoardFiles.defaultBoardPath(configDir: config)))
        let unreachable = BoardFiles.loadStartup(configDir: config, demoPath: nil,
                                                 reach: { _ in nil })
        check("one that does not answer in time is said as that",
              unreachable.note.contains("could not be reached"), unreachable.note)
        check("and what opened instead is named",
              unreachable.note.hasSuffix("board opened instead"), unreachable.note)
        try? FileManager.default.moveItem(atPath: moved, toPath: show)

        // Audit 1, finding 10: asked with a limit whether it is there, and
        // then READ with one too. A share that goes away between the two
        // questions used to freeze the start for as long as macOS took.
        let slowBegan = Date()
        let slowRead = BoardFiles.loadStartup(
            configDir: config, demoPath: nil,
            readRemembered: { path in
                BoardFiles.readQuickly(path, timeout: 0.3) { _ in
                    Thread.sleep(forTimeInterval: 3)
                    return .failure(.missing)
                }
            })
        let slowTook = Date().timeIntervalSince(slowBegan)
        check("a remembered board that will not finish being read is not waited for",
              slowTook < 1.5 && slowRead.note.contains("could not be reached")
                && Board.samePath(slowRead.pinned, show),
              String(format: "%.2f s: %@", slowTook, slowRead.note))
        check("and a quick one is read as ever",
              BoardFiles.readQuickly(show).map { if case .success = $0 { return true }; return false }
                == true)

        let began = Date()
        let answer = BoardFiles.existsQuickly("/Volumes/never-answers/Show.json", timeout: 0.3) { _ in
            Thread.sleep(forTimeInterval: 3)
            return true
        }
        let took = Date().timeIntervalSince(began)
        check("a board on a volume that never answers is given up on quickly",
              answer == nil && took < 1.5, String(format: "%.2f s", took))
        check("and one that answers is answered",
              BoardFiles.existsQuickly(show, timeout: 2) == true)
    }

    private func testUnreadableAtStartup(_ scratch: String) {
        out.append("")
        out.append("A board that will not load is copied aside, never replaced in silence")
        let config = (scratch as NSString).appendingPathComponent("unreadable")
        try? FileManager.default.createDirectory(atPath: config, withIntermediateDirectories: true)
        let usual = BoardFiles.defaultBoardPath(configDir: config)
        let broken = "{\n\"app\": \"TG Drop Deck\",\n\"stream_host\": \"x\"\n\"y\": 2}"
        write(usual, broken)
        let demoFile = (scratch as NSString).appendingPathComponent("demo-board.json")
        let demo = Board()
        demo.slots[0].filepath = "/tmp/demo.wav"
        _ = try? demo.save(to: demoFile)
        let start = BoardFiles.loadStartup(configDir: config, demoPath: demoFile)
        let kept = ((try? FileManager.default.contentsOfDirectory(atPath: config)) ?? [])
            .filter { $0.hasPrefix("board (could not be read ") }
        check("a board with a mistake in it is not replaced in silence",
              start.note.contains("board could not be read, there is a mistake in it on line 4"),
              start.note)
        check("and says a copy is kept without reading its bracketed name out",
              start.note.contains("A copy is kept in the same folder") && !start.note.contains("("),
              start.note)
        check("it is copied aside first", kept.count == 1, "\(kept)")
        check("and the copy is exactly what was there",
              kept.first.map { contents((config as NSString).appendingPathComponent($0)) } == broken)
        check("the demo opens in its place", start.loadedDemo)
        check("claiming the board's path, not the demo's",
              Board.samePath(start.board.path, usual))
        check("a second start the same minute finds the same copy, not a failure",
              BoardFiles.keepUnreadable(usual) != nil
                && ((try? FileManager.default.contentsOfDirectory(atPath: config)) ?? [])
                    .filter { $0.hasPrefix("board (could not be read ") }.count == 1)
        // Copied aside, the broken board is safe, and the demo may take the
        // usual path from here on, exactly as on Windows.
        let keeper = BoardKeeper(board: start.board, configDir: config)
        start.board.dirty = true
        _ = keeper.saveForClose()
        check("and what was in it is still there after the demo is saved",
              kept.first.map { contents((config as NSString).appendingPathComponent($0)) } == broken)

        // Not even copyable: a folder nobody may write to.
        let lockedConfig = (scratch as NSString).appendingPathComponent("locked")
        try? FileManager.default.createDirectory(atPath: lockedConfig, withIntermediateDirectories: true)
        let lockedBoard = BoardFiles.defaultBoardPath(configDir: lockedConfig)
        write(lockedBoard, broken)
        try? FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: lockedConfig)
        let locked = BoardFiles.loadStartup(configDir: lockedConfig, demoPath: demoFile)
        check("a board that could not be read or copied says it is left alone",
              locked.note.contains("It has been left alone, and will not be saved over"), locked.note)
        check("and is claimed as unreadable", locked.board.disk == .unreadable)
        let lockedKeeper = BoardKeeper(board: locked.board, configDir: lockedConfig)
        lockedKeeper.noteStartingVersion()
        check("and coming back to the window does not announce it a second time",
              lockedKeeper.comingBack(BoardKeeper.look(path: lockedBoard,
                                                       knowledge: locked.board.disk),
                                      busy: false) == .nothing)
        locked.board.dirty = true
        _ = lockedKeeper.save()
        _ = lockedKeeper.saveForClose()
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: lockedConfig)
        check("and nothing is ever written over it", contents(lockedBoard) == broken)

        // No board at all, and nothing remembered: the demo, claiming a path
        // with nothing there.
        let empty = (scratch as NSString).appendingPathComponent("firstrun")
        try? FileManager.default.createDirectory(atPath: empty, withIntermediateDirectories: true)
        let first = BoardFiles.loadStartup(configDir: empty, demoPath: demoFile)
        check("with no board at all the demo opens, knowing nothing was there",
              first.loadedDemo && first.board.disk == .nothingThere && first.note.isEmpty)
        let copiedIn = "{\"app\": \"TG Drop Deck\", \"stream_host\": \"copied.example.org\"}"
        write(BoardFiles.defaultBoardPath(configDir: empty), copiedIn)
        let firstKeeper = BoardKeeper(board: first.board, configDir: empty)
        first.board.dirty = false
        _ = firstKeeper.saveForClose()
        check("a board copied in meanwhile is not saved over on close",
              contents(BoardFiles.defaultBoardPath(configDir: empty)) == copiedIn)
    }

    private func testComingBack(_ scratch: String, config: String) {
        out.append("")
        out.append("Coming back to the window after the file changed (W383-23)")
        let path = (scratch as NSString).appendingPathComponent("Back.json")
        let b = Board()
        b.stream.host = "mine.example.org"
        let keeper = BoardKeeper(board: b, configDir: config)
        _ = keeper.save(to: path)
        func look(_ at: String = path) -> BoardKeeper.Look {
            BoardKeeper.look(path: at, knowledge: b.disk)
        }
        check("nothing changed is nothing to do",
              keeper.comingBack(look(), busy: false) == .nothing)
        write(path, "{\"app\": \"TG Drop Deck\", \"stream_host\": \"theirs.example.org\"}")
        let changedLook = look()
        let loaded = keeper.comingBack(changedLook, busy: false)
        if case .load(let fresh) = loaded {
            check("with nothing going on, a board copied in meanwhile loads",
                  fresh.stream.host == "theirs.example.org")
        } else {
            check("with nothing going on, a board copied in meanwhile loads", false, "\(loaded)")
        }
        check("and the same version is never acted on twice",
              keeper.comingBack(changedLook, busy: false) == .nothing)

        write(path, "{\"app\": \"TG Drop Deck\", \"stream_host\": \"third.example.org\"}")
        let busy = keeper.comingBack(look(), busy: true)
        check("while something is playing or live it is said and nothing moves",
              busy == .say("Back has been changed outside Drop Deck. It will not be saved over. "
                           + "File, Open board loads the new one when you are ready"), "\(busy)")
        check("once",
              keeper.comingBack(look(), busy: true) == .nothing)

        write(path, "{\"app\": \"TG Drop Deck\",\n\"x\": 1\n\"y\": 2}")
        var said: [ComingBackSaid] = []
        for _ in 0..<3 {
            let answer = keeper.comingBack(look(), busy: false)
            if case .say(let line) = answer { said.append(ComingBackSaid(line: line)) }
            if case .load = answer { said.append(ComingBackSaid(line: "LOADED")) }
        }
        check("a board broken outside the app is said once, and never loaded",
              said.count == 1 && said[0].line.contains("cannot be read, there is a mistake in it on line 3")
                && said[0].line.hasSuffix("It will not be saved over"), "\(said.map { $0.line })")
        check("a different board's path is none of its business",
              keeper.comingBack(BoardKeeper.Look(path: path + ".other", knowledge: b.disk,
                                                 changed: true, now: nil, read: nil),
                                busy: false) == .nothing)

        // Audit 1, finding 10. A look that set out before the app's own save
        // landed compares the file with what was known BEFORE, so the app's
        // own write looks like somebody else's. Thrown away.
        let own = (scratch as NSString).appendingPathComponent("Own.json")
        let mine = Board()
        mine.stream.host = "mine.example.org"
        let ownKeeper = BoardKeeper(board: mine, configDir: config)
        _ = ownKeeper.save(to: own)
        let before = mine.disk
        mine.stream.host = "changed.example.org"
        mine.dirty = true
        _ = ownKeeper.save()          // the autosave, while the look was out
        mine.dirty = false
        let stale = BoardKeeper.look(path: own, knowledge: before)
        check("the app's own save is not taken for somebody else's",
              stale.changed && ownKeeper.comingBack(stale, busy: false) == .nothing,
              "changed \(stale.changed)")
        check("and the next look, with what is known now, sees nothing changed",
              ownKeeper.comingBack(BoardKeeper.look(path: own, knowledge: mine.disk),
                                   busy: false) == .nothing)

        // And the board is not read on the main thread: `comingBack` uses the
        // look's own reading and never reads the file again itself.
        let elsewhere = Board()
        elsewhere.stream.host = "read.on.the.look.example.org"
        write(own, "{\"app\": \"TG Drop Deck\",\n\"x\": 1\n\"y\": 2}")
        let handed = BoardKeeper.Look(path: own, knowledge: mine.disk, changed: true,
                                      now: Board.diskStamp(own), read: .success(elsewhere))
        if case .load(let got) = ownKeeper.comingBack(handed, busy: false) {
            check("comingBack loads what the look read, not a fresh read of its own",
                  got === elsewhere)
        } else {
            check("comingBack loads what the look read, not a fresh read of its own", false)
        }
    }

    private struct ComingBackSaid { let line: String }

    private func testStartupWords() {
        out.append("")
        out.append("The startup line says what happened to the board first (W383-25)")
        let plain = BoardFiles.startupParts(note: "", loadedDemo: false, assigned: 12, boardName: "")
        check("the usual board is a count", plain == ["12 sounds loaded"], "\(plain)")
        let named = BoardFiles.startupParts(note: "", loadedDemo: false, assigned: 3,
                                            boardName: "My Show")
        check("another board is named", named == ["My Show, 3 sounds loaded"], "\(named)")
        let demo = BoardFiles.startupParts(note: "", loadedDemo: true, assigned: 40, boardName: "")
        check("the demo says how to start from scratch",
              demo == ["demo pack loaded, 40 sounds and beds. File, new board starts you from scratch"],
              "\(demo)")
        let trouble = BoardFiles.startupParts(note: "Show could not be read, x. y",
                                              loadedDemo: true, assigned: 40, boardName: "")
        check("a board note comes before the count",
              trouble.first == "Show could not be read, x. y", "\(trouble)")
        check("and buries nothing under the hint",
              trouble.last == "demo pack loaded, 40 sounds and beds", "\(trouble)")
        check("a board is said by its name, never its path",
              BoardFiles.boardWords("/Users/x/Boards/My Show.json") == "My Show"
                && BoardFiles.folderWords("/Users/x/Boards/My Show.json") == "Boards")
        check("and the usual one is not named at all",
              BoardFiles.boardName(Board.defaultBoardPath()) == "")
    }

    // ---------------------------------------------------- the stream key ---

    private func testStreamKeyRules() {
        out.append("")
        out.append("Preferences OK never deletes a stream key (W384-20 to 23)")
        check("an untouched box changes nothing",
              VideoPrefs.videoKeyAction(typed: "abcd-1234", atOpen: "abcd-1234") == .leave)
        check("including one that came up empty because the keychain could not be read",
              VideoPrefs.videoKeyAction(typed: "", atOpen: "") == .leave)
        check("a key typed in is stored",
              VideoPrefs.videoKeyAction(typed: "new-key", atOpen: "old-key") == .store)
        check("and one typed into an empty box is stored",
              VideoPrefs.videoKeyAction(typed: "new-key", atOpen: "") == .store)
        check("an emptied box forgets it",
              VideoPrefs.videoKeyAction(typed: "", atOpen: "old-key") == .forget)
        check("every space and newline comes out of a key, not only the ends",
              VideoPrefs.cleanKey(" abcd - 1234\n") == "abcd-1234")
        check("so a pasted copy of the same key is still untouched",
              VideoPrefs.videoKeyAction(typed: VideoPrefs.cleanKey("abcd-1234 \n"),
                                        atOpen: VideoPrefs.cleanKey("abcd-1234")) == .leave)
        check("the keychain's key is the one in force",
              Board.keyInForce(keychain: "from-keychain", board: "from-board",
                               boardFor: "youtube", station: "youtube") == "from-keychain")
        check("and the board file's only when the keychain has none",
              Board.keyInForce(keychain: "", board: "from-board",
                               boardFor: "youtube", station: "youtube") == "from-board")

        // Audit 1, finding 5: the board's one key is never offered to another
        // platform. The keychain is not asked here; the owner rule is.
        check("a board key saved for YouTube is not offered to Facebook",
              Board.keyInForce(keychain: "", board: "yt-key", boardFor: "youtube",
                               station: "facebook") == "")
        var file: [String: Any] = ["app": "TG Drop Deck", "video_server": "youtube",
                                   "video_key": "yt-key"]
        let older = Board.from(dict: file, relativeTo: nil)
        check("a board with no owner recorded (older, or Windows') is given the platform it was saved with",
              older.videoKeyFor == "youtube" && older.videoKeyOwner == "youtube",
              older.videoKeyFor)
        older.videoServer = "facebook"
        check("so moving it to Facebook does not carry the YouTube key there",
              Board.keyInForce(keychain: "", board: older.videoKey, boardFor: older.videoKeyOwner,
                               station: Secrets.videoStation(server: older.videoServer,
                                                             host: older.videoHost)) == "",
              older.videoKeyOwner)
        let written = older.toDict()
        check("Windows' video_key is written exactly as it was, and the owner beside it",
              written["video_key"] as? String == "yt-key"
                && written["mac_video_key_server"] as? String == "youtube"
                && written["video_server"] as? String == "facebook")
        let back = Board.from(dict: written, relativeTo: nil)
        check("and it reads back as YouTube's, whatever the board's platform is now",
              back.videoKeyOwner == "youtube" && back.videoServer == "facebook"
                && back.toDict()["mac_video_key_server"] as? String == "youtube")
        check("coming back to YouTube offers it again",
              Board.keyInForce(keychain: "", board: back.videoKey, boardFor: back.videoKeyOwner,
                               station: "youtube") == "yt-key")
        file["video_key"] = ""
        check("no key, no owner", Board.from(dict: file, relativeTo: nil).videoKeyOwner == "")
        check("a key the keychain would not keep is said out loud, in Windows' words",
              VideoPrefs.keyNotKept == "macOS would not store your stream key safely, so it is "
                + "in your board file. Do not send that file to anybody.")
    }

    private func testCameraPlaceholder() {
        out.append("")
        out.append("A camera that is not plugged in is not swapped for another (W384-30)")
        let cameras = ["FaceTime HD Camera", "Studio Display Camera"]
        let away = VideoPrefs.cameraChoices(cameras: cameras, saved: "Logitech Brio")
        check("it is offered as itself, not connected, and chosen",
              away.titles.first == "Logitech Brio (not connected)" && away.selected == 0,
              "\(away)")
        check("so OK keeps it",
              VideoPrefs.cameraAfterOK(cameras: cameras, saved: "Logitech Brio",
                                       selected: away.selected) == "Logitech Brio")
        check("and choosing a real one still works",
              VideoPrefs.cameraAfterOK(cameras: cameras, saved: "Logitech Brio", selected: 2)
                == "Studio Display Camera")
        let here = VideoPrefs.cameraChoices(cameras: cameras, saved: "Studio Display Camera")
        check("a camera that is here is simply chosen",
              here.titles == cameras && here.selected == 1, "\(here)")
        let none = VideoPrefs.cameraChoices(cameras: [], saved: "")
        check("no cameras and none saved says so",
              none.titles == ["No camera found"]
                && VideoPrefs.cameraAfterOK(cameras: [], saved: "", selected: 0) == "")
    }
}
