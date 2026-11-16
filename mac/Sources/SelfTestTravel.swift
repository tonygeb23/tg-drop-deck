// The checks for 3.10.0's board work, on REAL files in a scratch folder:
//
//   A board that takes the open one's place never takes its FILE (Siena
//   Trigiani and Rob Castrogiovanni, 15 November 2026). For each of New,
//   Load demo, Import and Open, the outgoing file is byte for byte unchanged
//   after the autosave AND after quitting, the default board file is
//   unchanged, and no new file exists until something is edited. That is the
//   list Mark wrote for Windows' `tests/test_3_10_0.py`.
//
//   Paths that travel (Windows 3.9.0): a Windows path relinks on the Mac
//   (Siena, 12 October 2026), a board looks beside itself when it opens, a
//   sound beside the board is saved relative, and Export board with its
//   sounds writes a folder that opens anywhere (Ali Moosa).
//
// Called from `runBoardFileChecks`, so the config folder is already pointed
// at scratch and nothing here can reach the real board.

import Foundation
import AVFoundation

extension SelfTest {

    func runBoardTravelChecks(_ scratch: String) {
        let root = (scratch as NSString).appendingPathComponent("travel")
        try? FileManager.default.createDirectory(atPath: root, withIntermediateDirectories: true)
        testOneBoardForAnother(root)
        testWindowsPaths(root)
        testSavedRelative(root)
        testFindBeside(root)
        testExport(root)
        testLoadedWords()
        testSpeechAfterABox()
        testPausing(root)
        testMisnamedFiles(root)
    }

    // ------------------------------------------------------------ helpers ---

    private func put(_ path: String, _ text: String = "x") {
        try? FileManager.default.createDirectory(
            atPath: (path as NSString).deletingLastPathComponent, withIntermediateDirectories: true)
        try? Data(text.utf8).write(to: URL(fileURLWithPath: path))
    }

    private func bytes(_ path: String) -> Data? { FileManager.default.contents(atPath: path) }

    private func exists(_ path: String) -> Bool { FileManager.default.fileExists(atPath: path) }

    /// What `MainWindow.adopt` does to the board: the same object, new
    /// contents, and the path only when the board came from a file that is
    /// to be saved to.
    private func arrive(_ board: Board, _ loaded: Board, path: String?) {
        board.replaceContents(with: loaded)
        if let path {
            board.path = path
            board.takeDiskKnowledge(from: loaded)
        }
    }

    /// A folder of its own for one case, with a config folder holding a
    /// board.json that must never change, and a saved show.
    private func stage(_ root: String, _ name: String)
        -> (config: String, show: String, usual: String, usualBytes: Data?, board: Board,
            keeper: BoardKeeper) {
        let folder = (root as NSString).appendingPathComponent(name)
        let config = (folder as NSString).appendingPathComponent("config")
        try? FileManager.default.createDirectory(atPath: config, withIntermediateDirectories: true)
        let usual = BoardFiles.defaultBoardPath(configDir: config)
        put(usual, "{\"app\": \"TG Drop Deck\", \"stream_host\": \"usual.example.org\"}")
        let show = (folder as NSString).appendingPathComponent("Siena show.json")
        let board = Board()
        board.slots[0].filepath = "/Music/intro.mp3"
        board.slots[1].filepath = "/Music/outro.mp3"
        let keeper = BoardKeeper(board: board, configDir: config)
        _ = keeper.save(to: show)
        return (config, show, usual, bytes(usual), board, keeper)
    }

    private func newFiles(_ config: String) -> [String] {
        ((try? FileManager.default.contentsOfDirectory(atPath: config)) ?? [])
            .filter { $0.hasSuffix(".json") && $0 != "board.json" && $0 != "last_board.json" }
            .sorted()
    }

    // ------------------------------------------- one board for another ---

    private func testOneBoardForAnother(_ root: String) {
        out.append("")
        out.append("A board that takes another's place never takes its file (Siena and Rob, 3.10.0)")

        check("a board that arrives is not marked changed by arriving", {
            let live = Board(); live.dirty = false
            live.replaceContents(with: Board())
            return !live.dirty
        }())

        // File, New, after a save and then a change made in the last two
        // seconds, which must be written to the board it was made on.
        do {
            let s = stage(root, "new")
            s.board.slots[2].filepath = "/Music/sting.wav"
            s.board.dirty = true
            let put = s.keeper.putAway()
            check("New: a change not yet written is written to its own board first",
                  put == .saved(s.show) && Board.load(s.show)?.slots[2].filepath == "/Music/sting.wav",
                  "\(String(describing: put))")
            let showBytes = bytes(s.show)
            check("New: the board you had has a file, so the box can say it is kept",
                  s.keeper.hasAFile && s.keeper.keptWords()
                    == "Siena show is saved first and stays exactly as it is. File, Open board brings it back.")
            arrive(s.board, Board(), path: nil)
            let home = s.keeper.giveNewHome()
            check("New: the new board has a file of its own called New board",
                  (home as NSString).lastPathComponent == "New board.json"
                    && Board.samePath((home as NSString).deletingLastPathComponent, s.config))
            check("New: the autosave writes nothing", s.keeper.autosave() == nil)
            check("New: the board you had is byte for byte unchanged after the autosave",
                  bytes(s.show) == showBytes)
            check("New: quitting writes nothing", s.keeper.saveForClose() == nil)
            check("New: and it is still unchanged after quitting", bytes(s.show) == showBytes)
            check("New: the usual board is unchanged", bytes(s.usual) == s.usualBytes)
            check("New: no new file until something is edited", newFiles(s.config).isEmpty,
                  newFiles(s.config).joined(separator: ", "))
            check("New: an untouched new board says the demo sentence, not a promise",
                  !s.keeper.hasAFile
                    && s.keeper.keptWords() == "The demo pack comes back with File, Load demo pack.")
            s.board.slots[0].filepath = "/Music/new.wav"
            s.board.dirty = true
            check("New: the first change writes the new board to its own file",
                  s.keeper.autosave() == .saved(home) && exists(home))
            check("New: and still not over the board you had", bytes(s.show) == showBytes)
            let named = ((s.show as NSString).deletingLastPathComponent as NSString)
                .appendingPathComponent("Named.json")
            check("Save board as names it, and the New board file it was kept in goes",
                  s.keeper.saveAs(named) == .saved(named) && exists(named) && !exists(home))
            check("and a named board is no longer a fresh one",
                  !s.keeper.unstarted && s.keeper.freshHome == nil)
            check("a second new board in the same folder is New board 2 only while the first exists",
                  { put_(home); defer { try? FileManager.default.removeItem(atPath: home) }
                    return (BoardKeeper.newHome(configDir: s.config) as NSString).lastPathComponent
                        == "New board 2.json" }())
        }

        // Load the demo pack.
        do {
            let s = stage(root, "demo")
            let showBytes = bytes(s.show)
            let demo = Board()
            demo.slots[0].filepath = "/Demo/airhorn.flac"
            _ = s.keeper.putAway()
            arrive(s.board, demo, path: nil)
            let home = s.keeper.giveNewHome("Demo board")
            check("Demo: it gets a file of its own called Demo board",
                  (home as NSString).lastPathComponent == "Demo board.json")
            check("Demo: the autosave and quitting write nothing",
                  s.keeper.autosave() == nil && s.keeper.saveForClose() == nil)
            check("Demo: the board you had is byte for byte unchanged", bytes(s.show) == showBytes)
            check("Demo: the usual board is unchanged, and no new file", bytes(s.usual) == s.usualBytes
                    && newFiles(s.config).isEmpty)
        }

        // Import an old bank: it holds something worth keeping, so it is
        // marked changed and written, to a file named after it.
        do {
            let s = stage(root, "import")
            let showBytes = bytes(s.show)
            let bank = Board()
            bank.slots[0].filepath = "/Old/jingle.wav"
            _ = s.keeper.putAway()
            arrive(s.board, bank, path: nil)
            let home = s.keeper.giveNewHome("Tony show bank")
            check("Import: no file before the import is kept", newFiles(s.config).isEmpty)
            s.board.dirty = true
            check("Import: it is written to a file named after the bank",
                  s.keeper.autosave() == .saved(home)
                    && (home as NSString).lastPathComponent == "Tony show bank.json")
            check("Import: and never over the board you had, or the usual one",
                  bytes(s.show) == showBytes && bytes(s.usual) == s.usualBytes)
            check("Import: a bank called last_board is never given the app's own file",
                  (BoardKeeper.newHome("last_board", configDir: s.config) as NSString)
                    .lastPathComponent == "Imported last_board.json")
        }

        // File, Open: the change made in the last two seconds goes to the
        // board it was made on, and the opened board is not written.
        do {
            let s = stage(root, "open")
            let other = ((s.show as NSString).deletingLastPathComponent as NSString)
                .appendingPathComponent("Rob show.json")
            let rob = Board()
            rob.slots[0].filepath = "/Rob/open.wav"
            _ = try? rob.save(to: other)
            let otherBytes = bytes(other)
            s.board.slots[5].filepath = "/Music/late.wav"
            s.board.dirty = true
            _ = s.keeper.putAway()
            let showBytes = bytes(s.show)
            check("Open: the last change is in the board it was made on",
                  Board.load(s.show)?.slots[5].filepath == "/Music/late.wav")
            guard let opened = Board.load(other) else {
                check("Open: the other board reads", false)
                return
            }
            arrive(s.board, opened, path: other)
            s.keeper.opened(other)
            s.keeper.forgetNewHome()
            check("Open: the autosave writes nothing", s.keeper.autosave() == nil)
            check("Open: the board you had is unchanged after the autosave", bytes(s.show) == showBytes)
            _ = s.keeper.saveForClose()
            check("Open: and after quitting", bytes(s.show) == showBytes)
            check("Open: the board opened still says what it said",
                  otherBytes != nil && Board.load(other)?.slots[0].filepath == "/Rob/open.wav")
            check("Open: the usual board is unchanged and no new file",
                  bytes(s.usual) == s.usualBytes && newFiles(s.config).isEmpty)
        }

        check("a typed name loses what a file name cannot hold, and a typed .json",
              BoardKeeper.fileWords("  My: show?.json ") == "My show"
                && BoardKeeper.fileWords("...") == "")
        check("the usual board is called Your board in a sentence",
              BoardKeeper.boardSaid(BoardFiles.defaultBoardPath(configDir: "/tmp/x"),
                                    configDir: "/tmp/x") == "Your board"
                && BoardKeeper.boardSaid("/a/Siena show.json", configDir: "/tmp/x") == "Siena show")
    }

    private func put_(_ path: String) { put(path, "{}") }

    // ------------------------------------------------------ Windows paths ---

    private func testWindowsPaths(_ root: String) {
        out.append("")
        out.append("A board made on Windows relinks on the Mac (Siena, 12 October 2026)")
        check("a Windows path gives up its file name",
              BoardPaths.basename("G:\\My Drive\\SienaT Radio\\intro.mp3") == "intro.mp3"
                && BoardPaths.basename("/Users/siena/intro.mp3") == "intro.mp3"
                && BoardPaths.basename("C:\\Shows\\Countdown\\") == "Countdown")
        check("a drive or a share is absolute, a board's own folder is not",
              !BoardPaths.isRelative("G:\\My Drive\\a.wav") && !BoardPaths.isRelative("\\\\nas\\a.wav")
                && !BoardPaths.isRelative("/Users/a.wav") && BoardPaths.isRelative("Sounds/a.wav")
                && BoardPaths.isRelative("Sounds\\a.wav"))
        let folder = (root as NSString).appendingPathComponent("drive")
        let windows = Board.from(dict: [
            "slots": [["filepath": "G:\\My Drive\\SienaT Radio\\intro.mp3"],
                      ["filepath": "Sounds\\bed.wav"],
                      ["filepath": "C:\\Effects\\applause.wav"]],
            "playlist": ["tracks": [["filepath": "G:\\My Drive\\SienaT Radio\\song.mp3"]]],
            "drops": ["paths": ["G:\\My Drive\\SienaT Radio\\ident.wav"]],
        ], relativeTo: folder)
        check("a Windows absolute path is kept as written, never joined onto the folder",
              windows.slots[0].filepath == "G:\\My Drive\\SienaT Radio\\intro.mp3")
        check("a relative path with a backslash resolves under the board's folder",
              windows.slots[1].filepath == (folder as NSString).appendingPathComponent("Sounds/bed.wav"))
        check("a pad written on Windows is called by its file name",
              windows.slots[0].displayName == "intro")
        let chosen = (root as NSString).appendingPathComponent("Siena Drive")
        for name in ["intro.mp3", "song.mp3", "ident.wav", "Deep/applause.flac"] {
            put((chosen as NSString).appendingPathComponent(name))
        }
        let before = windows.missingCount
        let repaired = windows.relink(using: BoardPaths.index(chosen))
        check("every Windows path in the folder chosen is relinked: pads, running order, drops",
              before == 5 && repaired == 4 && windows.missingCount == 1,
              "\(before) missing, \(repaired) repaired, \(windows.missingCount) left")
        check("a pad matches a name without its extension, as Windows always has",
              windows.slots[2].filepath?.hasSuffix("Deep/applause.flac") == true)
        check("and a relink somebody asked for is written down, so the board is changed",
              windows.dirty && windows.guessed.isEmpty)
    }

    // ---------------------------------------------------- saved relative ---

    private func testSavedRelative(_ root: String) {
        out.append("")
        out.append("A sound beside the board is saved relative to it (Ali Moosa, 3.9.0)")
        let folder = (root as NSString).appendingPathComponent("Drive show")
        let inside = (folder as NSString).appendingPathComponent("Sounds/intro.wav")
        put(inside)
        let file = (folder as NSString).appendingPathComponent("Show.json")
        let board = Board()
        board.slots[0].filepath = inside
        board.slots[1].filepath = "/Elsewhere/outro.wav"
        board.playlist.tracks = [Track(filepath: inside)]
        _ = try? board.save(to: file)
        let raw = (try? JSONSerialization.jsonObject(with: bytes(file) ?? Data())) as? [String: Any]
        let slots = raw?["slots"] as? [[String: Any]]
        let tracks = (raw?["playlist"] as? [String: Any])?["tracks"] as? [[String: Any]]
        check("under the board's folder it is written relative, with forward slashes",
              slots?[0]["filepath"] as? String == "Sounds/intro.wav"
                && tracks?[0]["filepath"] as? String == "Sounds/intro.wav")
        check("anywhere else it keeps its full path", slots?[1]["filepath"] as? String == "/Elsewhere/outro.wav")
        check("in memory it is still the whole path", board.slots[0].filepath == inside)
        check("and it reads back whole",
              Board.samePath(Board.load(file)?.slots[0].filepath, inside))
    }

    // -------------------------------------------------------- find beside ---

    private func testFindBeside(_ root: String) {
        out.append("")
        out.append("A board carried to another computer looks beside itself (3.9.0)")
        let folder = (root as NSString).appendingPathComponent("Carried")
        put((folder as NSString).appendingPathComponent("Sounds/sting.wav"))
        put((folder as NSString).appendingPathComponent("Sounds/applause.flac"))
        put((folder as NSString).appendingPathComponent("Sounds/song.mp3"))
        let file = (folder as NSString).appendingPathComponent("Carried.json")
        let json: [String: Any] = [
            "app": "TG Drop Deck",
            "slots": [["filepath": "G:\\Old\\sting.wav"], ["filepath": "C:\\Old\\applause.wav"]],
            "playlist": ["tracks": [["filepath": "/Users/ali/Music/song.mp3"]]],
        ]
        put(file, String(data: (try? JSONSerialization.data(withJSONObject: json)) ?? Data(),
                         encoding: .utf8) ?? "")
        guard let board = Board.load(file) else {
            check("the carried board reads", false)
            return
        }
        check("what is beside it is found on opening, and counted",
              board.foundBeside == 2 && board.slots[0].filepath?.hasSuffix("Sounds/sting.wav") == true
                && board.playlist.tracks[0].filepath.hasSuffix("Sounds/song.mp3"),
              "found \(board.foundBeside)")
        check("exact names only: applause.wav is not a different applause.flac",
              board.slots[1].filepath == "C:\\Old\\applause.wav")
        check("finding it does not mark the board changed", !board.dirty)
        _ = try? board.save()
        let saved = (try? JSONSerialization.jsonObject(with: bytes(file) ?? Data())) as? [String: Any]
        let rows = saved?["slots"] as? [[String: Any]]
        let tracks = (saved?["playlist"] as? [String: Any])?["tracks"] as? [[String: Any]]
        check("a guess is never written down: the board file keeps its own paths",
              rows?[0]["filepath"] as? String == "G:\\Old\\sting.wav"
                && tracks?[0]["filepath"] as? String == "/Users/ali/Music/song.mp3")
        let mine = (folder as NSString).appendingPathComponent("Sounds/applause.flac")
        board.slots[0].filepath = mine
        _ = try? board.save()
        let after = (try? JSONSerialization.jsonObject(with: bytes(file) ?? Data())) as? [String: Any]
        check("but a pad somebody reassigned since is theirs, and saved",
              (after?["slots"] as? [[String: Any]])?[0]["filepath"] as? String == "Sounds/applause.flac")
        let other = Board()
        other.replaceContents(with: board)
        check("the guesses travel with the board through File, Open", !other.guessed.isEmpty)
    }

    // -------------------------------------------------------------- export ---

    private func testExport(_ root: String) {
        out.append("")
        out.append("Export board with its sounds writes a folder that opens anywhere (3.9.0)")
        let source = (root as NSString).appendingPathComponent("Library")
        let a = (source as NSString).appendingPathComponent("A/intro.wav")
        let b = (source as NSString).appendingPathComponent("B/intro.wav")
        let pad = (source as NSString).appendingPathComponent("Countdown")
        put(a, "first"); put(b, "second")
        put((pad as NSString).appendingPathComponent("one.wav"), "1")
        put((pad as NSString).appendingPathComponent("notes.txt"), "not a sound")
        let board = Board()
        board.slots[0].filepath = a
        board.slots[1].filepath = b
        board.slots[2].filepath = pad
        board.slots[3].filepath = "/Gone/missing.wav"
        board.playlist.tracks = [Track(filepath: a)]
        board.drops.load(from: ["paths": [b]], relativeTo: nil)
        let paths = BoardExport.soundPaths(board)
        check("every sound once, pads then running order then drops", paths.count == 4, "\(paths)")
        check("a board with no name is exported as Drop Deck board",
              BoardExport.defaultName(nil) == "Drop Deck board"
                && BoardExport.defaultName("/x/board.json") == "Drop Deck board"
                && BoardExport.defaultName("/x/Ali show.json") == "Ali show")
        let into = (root as NSString).appendingPathComponent("Exported")
        try? FileManager.default.createDirectory(atPath: into, withIntermediateDirectories: true)
        let target = BoardExport.target(in: into, name: "Ali show")
        do {
            let result = try BoardExport.export(data: board.toDict(), paths: paths, to: target,
                                                name: "Ali show")
            check("it copies every sound it can and counts what it cannot",
                  result.copied == 3 && result.missing == ["/Gone/missing.wav"],
                  "\(result.copied) copied, missing \(result.missing)")
            let sounds = (target as NSString).appendingPathComponent("Sounds")
            check("two sounds with one name are kept apart as name (2)",
                  bytes((sounds as NSString).appendingPathComponent("intro.wav")) == Data("first".utf8)
                    && bytes((sounds as NSString).appendingPathComponent("intro (2).wav"))
                        == Data("second".utf8))
            check("a folder pad goes as a folder of its sounds and nothing else",
                  exists((sounds as NSString).appendingPathComponent("Countdown/one.wav"))
                    && !exists((sounds as NSString).appendingPathComponent("Countdown/notes.txt")))
            let raw = (try? JSONSerialization.jsonObject(with: bytes(result.board) ?? Data()))
                as? [String: Any]
            let rows = raw?["slots"] as? [[String: Any]]
            check("the board inside points at the copies, relative, with forward slashes",
                  rows?[0]["filepath"] as? String == "Sounds/intro.wav"
                    && rows?[1]["filepath"] as? String == "Sounds/intro (2).wav"
                    && rows?[2]["filepath"] as? String == "Sounds/Countdown"
                    && ((raw?["drops"] as? [String: Any])?["paths"] as? [String])?.first
                        == "Sounds/intro (2).wav")
            check("a sound that could not be found keeps the path it had",
                  rows?[3]["filepath"] as? String == "/Gone/missing.wav")
            check("the exported board opens with nothing missing but the one that was",
                  Board.load(result.board)?.missingCount == 1)
            check("the live board is not changed", board.slots[0].filepath == a)
            check("a second export there gets a folder of its own",
                  (BoardExport.target(in: into, name: "Ali show") as NSString).lastPathComponent
                    == "Ali show (2)")
        } catch {
            check("the export runs", false, "\(error)")
        }
        let stopped = (root as NSString).appendingPathComponent("Stopped")
        do {
            _ = try BoardExport.export(data: board.toDict(), paths: paths, to: stopped,
                                       name: "x") { _, _ in throw ExportStopped() }
            check("an export can be stopped part way", false)
        } catch {
            check("an export can be stopped part way, leaving no board file",
                  error is ExportStopped
                    && !exists((stopped as NSString).appendingPathComponent("x.json")))
        }
    }

    // ------------------------------------------------------------- words ---

    private func testLoadedWords() {
        out.append("")
        out.append("What opening a board says (Ali Moosa, 16 October 2026)")
        let playlist = Board()
        playlist.playlist.tracks = (0..<12).map { Track(filepath: "/m/\($0).mp3") }
        check("a board that is all running order says so, and is one that opens on it",
              MainWindow.loadedWords(playlist) == "12 playlist tracks, now in the playlist"
                && MainWindow.allPlaylist(playlist))
        let both = Board()
        for i in 0..<20 { both.slots[i].filepath = "/m/p\(i).wav" }
        both.playlist.tracks = (0..<12).map { Track(filepath: "/m/\($0).mp3") }
        check("a board with both counts both, and stays on the pads",
              MainWindow.loadedWords(both) == "20 sounds, 12 playlist tracks"
                && !MainWindow.allPlaylist(both))
        check("the Loaded line drops the .json and counts every kind of missing sound",
              MainWindow.loadedLine(name: BoardFiles.boardWords("/x/Ali.json"), board: both)
                == "Loaded Ali, 20 sounds, 12 playlist tracks. 32 sounds still missing: "
                 + "File, Relink missing sounds")
        check("the startup line counts the running order too",
              BoardFiles.startupParts(note: "", loadedDemo: false, assigned: 0, boardName: "Ali",
                                      tracks: 12) == ["Ali, 0 sounds loaded, 12 playlist tracks"])
    }

    private func testSpeechAfterABox() {
        out.append("")
        out.append("Speech straight after a menu or a box waits for VoiceOver (Siena, VO+M)")
        let now = Date()
        Speaker.interfaceClosed(at: now)
        check("a line just after a menu closes waits, then queues",
              Speaker.waitAfterInterface(now: now.addingTimeInterval(0.1)) == Speaker.afterInterfaceDelay)
        check("a line a moment later is said at once",
              Speaker.waitAfterInterface(now: now.addingTimeInterval(1.0)) == 0)
        Speaker.interfaceClosed(at: .distantPast)
    }

    // ------------------------------------------------------------- pausing ---

    private func testPausing(_ root: String) {
        out.append("")
        out.append("Pausing a recording carries on into the same file (Siena, 3.10.0)")
        let gate = PauseGate()
        gate.pause(waiting: 1000)
        check("what was waiting at the press of Pause is written, then the rest is dropped",
              gate.step(ready: 1500, chunk: 512) == .write(512)
                && gate.step(ready: 988, chunk: 512) == .write(488)
                && gate.step(ready: 500, chunk: 512) == .discard(500))
        check("pausing twice is refused", !gate.pause(waiting: 10))
        gate.resume(waiting: 700)
        check("what was waiting at the press of Resume arrived during the pause and is dropped",
              gate.step(ready: 900, chunk: 512) == .discard(512)
                && gate.step(ready: 388, chunk: 512) == .discard(188)
                && gate.step(ready: 200, chunk: 512) == .normal)
        let quick = PauseGate()
        quick.pause(waiting: 1000)
        _ = quick.step(ready: 1000, chunk: 512)
        quick.resume(waiting: 2000)
        check("Resume before the drain finished still writes the rest of what came before",
              quick.step(ready: 2000, chunk: 512) == .write(488)
                && quick.step(ready: 1512, chunk: 2000) == .discard(1512)
                && quick.step(ready: 10, chunk: 512) == .normal)

        // The real recorder, a real bus, a real file. Loud audio is written
        // only while paused, so any of it in the file is a leak.
        let folder = (root as NSString).appendingPathComponent("pause")
        try? FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
        let rate = 48000.0
        let taps = Taps()
        let recorder = Recorder()
        guard let path = recorder.start(taps: taps, rate: rate, format: "wav", bitrate: 192,
                                        folder: folder) else {
            check("a recording starts for the pause check", false, recorder.lastError ?? "")
            return
        }
        let frames = 1024
        let quiet = [Float](repeating: 0.3, count: frames * 2)
        let loud = [Float](repeating: 0.9, count: frames * 2)
        func feed(_ block: [Float]) {
            block.withUnsafeBufferPointer { p in
                for _ in 0..<24 {
                    taps.write(key: "main", samples: p.baseAddress!, frames: frames, rate: rate)
                    Thread.sleep(forTimeInterval: 0.01)
                }
            }
            Thread.sleep(forTimeInterval: 0.35)
        }
        feed(quiet)
        check("Pause is taken while recording", recorder.pause() && recorder.isPaused)
        feed(loud)
        // What was still in the ring at the press came BEFORE it and is
        // written, so the file holds exactly everything fed before Pause.
        let before = Double(24 * frames) / rate
        check("while paused the file holds everything from before the press and nothing after",
              abs(recorder.elapsed - before) < 1e-6,
              String(format: "%.4f s, wanted %.4f", recorder.elapsed, before))
        check("Resume is taken", recorder.resume() && !recorder.isPaused)
        feed(quiet)
        _ = recorder.stop(taps: taps)
        guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path)),
              let format = AVAudioFormat(standardFormatWithSampleRate: file.processingFormat.sampleRate,
                                         channels: 2),
              let buffer = AVAudioPCMBuffer(pcmFormat: format,
                                            frameCapacity: AVAudioFrameCount(file.length)) else {
            check("the paused recording opens", false)
            return
        }
        try? file.read(into: buffer)
        var peak: Float = 0
        if let channels = buffer.floatChannelData {
            for i in 0..<Int(buffer.frameLength) { peak = max(peak, abs(channels[0][i])) }
        }
        let expected = 48 * frames
        check("the file holds what came before and after, and not the pause",
              abs(Int(file.length) - expected) <= frames, "\(file.length) frames, wanted \(expected)")
        check("not one sample of the paused audio leaked into it", peak > 0.2 && peak < 0.5,
              String(format: "peak %.3f", peak))
    }

    // ------------------------------------------------------ misnamed files ---

    private func testMisnamedFiles(_ root: String) {
        out.append("")
        out.append("A sound whose name and contents disagree still plays (Raymond, feedback 46)")
        let folder = (root as NSString).appendingPathComponent("named")
        try? FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
        let honest = (folder as NSString).appendingPathComponent("song.m4a")
        let settings: [String: Any] = [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 44100,
                                       AVNumberOfChannelsKey: 2, AVEncoderBitRateKey: 128000]
        do {
            let file = try AVAudioFile(forWriting: URL(fileURLWithPath: honest), settings: settings)
            let format = file.processingFormat
            guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 44100) else { return }
            buffer.frameLength = 44100
            for c in 0..<Int(format.channelCount) {
                for i in 0..<44100 { buffer.floatChannelData![c][i] = 0.3 * sinf(Float(i) * 0.0627) }
            }
            try file.write(from: buffer)
        } catch {
            check("an AAC file can be made for the check", false, "\(error)")
            return
        }
        let liar = (folder as NSString).appendingPathComponent("suno song.mp3")
        try? FileManager.default.removeItem(atPath: liar)
        try? FileManager.default.copyItem(atPath: honest, toPath: liar)
        check("AAC in a file called .mp3 is recognised from its first bytes",
              AudioFile.sniff(liar) == "m4a" && AudioFile.sniff(honest) == "m4a")
        // Not refused: misread. It opens as an MP3 a fiftieth of a second
        // long, which is a pad that plays nothing. That is the fault.
        let misread = (try? AVAudioFile(forReading: URL(fileURLWithPath: liar)))
            .map { Double($0.length) / $0.fileFormat.sampleRate }
        check("macOS misreads it under its own name, which is the fault",
              misread == nil || misread! < 0.5,
              misread.map { String(format: "opens as %.2f s", $0) } ?? "refused")
        let probed = AudioFile.probe(liar)
        check("and Drop Deck opens it anyway, at its real length",
              probed.map { abs($0.duration - 1.0) < 0.1 } ?? false,
              probed.map { String(format: "%.2f s", $0.duration) } ?? "refused")
        let decoded = AudioFile.readAll(liar, targetRate: 48000)
        check("and decodes it", (decoded?.count ?? 0) > 80000, "\(decoded?.count ?? 0) samples")
        check("an honestly named file is opened as it is", AudioFile.namedRight(honest) == nil)

        let webm = (folder as NSString).appendingPathComponent("clip.m4a")
        try? Data([0x1A, 0x45, 0xDF, 0xA3, 0x9F, 0x42, 0x86, 0x81, 0x01, 0x42, 0xF7, 0x81])
            .write(to: URL(fileURLWithPath: webm))
        check("a WebM file is named for what it is, and why it will not play",
              AudioFile.refusal(webm) == "it is really a WebM file, and macOS cannot play those")
        let empty = (folder as NSString).appendingPathComponent("empty.wav")
        FileManager.default.createFile(atPath: empty, contents: Data())
        check("an empty file says so", AudioFile.refusal(empty) == "the file is empty")
        check("a file that has gone says so",
              AudioFile.refusal((folder as NSString).appendingPathComponent("gone.wav"))
                == "the file is not there")
        let broken = (folder as NSString).appendingPathComponent("broken.wav")
        try? Data(repeating: 7, count: 400).write(to: URL(fileURLWithPath: broken))
        check("anything else is said as something macOS could not decode",
              AudioFile.refusal(broken).hasPrefix("macOS could not decode it"))
    }
}
