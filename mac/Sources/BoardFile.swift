// A board file is the user's, and the app must never write over one it did
// not write.
//
// Windows 3.8.3, fb40, 19 September 2026: "if I rename, move or copy the json
// file, it acts as if it was never set up." Three faults, and the Mac had all
// three. Every start opened board.json whatever board was in use; closing
// saved over a board copied in while the app was open, the very act of
// picking the copy up; and a board that would not load was replaced by the
// demo, which then took its path and was autosaved over it.
//
// This file is the policy, kept apart from the window so every decision in it
// can be asserted on real files in a scratch folder: which board opens, what
// is said about it, where a save goes, and what coming back to the window
// does. The window only turns the answers into speech.

import Foundation

enum BoardFiles {

    // ------------------------------------------------------- remembering ---

    /// Which board was open last, so the next start opens that one again.
    /// The Windows name and shape, `{"path": "..."}`, beside board.json.
    static let lastBoardFile = "last_board.json"

    /// How long to wait at startup for the board that was open last time,
    /// when it may be on a network volume that has gone away. Windows
    /// measured 43.8 seconds for a dead share to answer, before the window
    /// exists. `C.BOARD_REACH_SECONDS`.
    static let reachSeconds = 2.0
    /// How long a remembered board is given to be READ, once it is known to
    /// be there. Longer than the reach, because a real board over a slow
    /// share takes a moment; still a limit, because a share that goes away
    /// between the two questions blocks the read as long as the stat.
    static let readSeconds = 5.0

    /// How long after the app comes back before looking at the board's file.
    /// VoiceOver is announcing the window at exactly that moment, and
    /// whichever speaks second cuts the other off. `C.BOARD_CHECK_DELAY_MS`.
    static let checkDelay = 0.5

    static func defaultBoardPath(configDir: String) -> String {
        (configDir as NSString).appendingPathComponent("board.json")
    }

    /// The board that was open last time, or nil if none was remembered.
    static func rememberedBoardPath(configDir: String = Board.configDir()) -> String? {
        let file = (configDir as NSString).appendingPathComponent(lastBoardFile)
        guard let data = FileManager.default.contents(atPath: file),
              let raw = try? JSONSerialization.jsonObject(with: data),
              let dict = raw as? [String: Any],
              let path = dict["path"] as? String,
              !path.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return path
    }

    /// Write down which board is open. True if it is now remembered.
    ///
    /// Called on every save, so it writes only when the answer changes, and
    /// it writes beside then swaps so a crash cannot leave half a note.
    @discardableResult
    static func rememberBoardPath(_ path: String?, configDir: String = Board.configDir()) -> Bool {
        guard let path, !path.isEmpty else { return false }
        let absolute = ((path as NSString).expandingTildeInPath as NSString).standardizingPath
        if Board.samePath(rememberedBoardPath(configDir: configDir), absolute) { return true }
        let files = FileManager.default
        try? files.createDirectory(atPath: configDir, withIntermediateDirectories: true)
        let target = (configDir as NSString).appendingPathComponent(lastBoardFile)
        let temp = target + ".tmp"
        defer { try? files.removeItem(atPath: temp) }
        do {
            let data = try JSONSerialization.data(withJSONObject: ["path": absolute])
            try data.write(to: URL(fileURLWithPath: temp))
            if files.fileExists(atPath: target) {
                _ = try files.replaceItemAt(URL(fileURLWithPath: target),
                                            withItemAt: URL(fileURLWithPath: temp))
            } else {
                try files.moveItem(atPath: temp, toPath: target)
            }
            return true
        } catch {
            return false
        }
    }

    /// The board a command line check should look at: the one the app would
    /// open, which is the remembered one when it is there. `--check-sources`
    /// and `--check-stream-key` read board.json and nothing else until 3.8.4,
    /// which would have been the wrong board the moment the app stopped doing
    /// the same (N7).
    static func boardToOpen(configDir: String = Board.configDir()) -> String {
        if let remembered = rememberedBoardPath(configDir: configDir),
           FileManager.default.fileExists(atPath: remembered) {
            return remembered
        }
        return defaultBoardPath(configDir: configDir)
    }

    // ------------------------------------------------------ being careful ---

    /// Does this file exist. True, false, or nil if nothing answered in time.
    ///
    /// Asked on a queue of its own and waited for briefly, because a file on
    /// a network volume that has gone away blocks for as long as macOS takes
    /// to give up on it, and this runs before the window exists.
    static func existsQuickly(_ path: String, timeout: Double = reachSeconds,
                              exists: @escaping (String) -> Bool = {
                                  FileManager.default.fileExists(atPath: $0) }) -> Bool? {
        final class Answer: @unchecked Sendable {
            let lock = NSLock()
            var value: Bool?
        }
        let answer = Answer()
        let done = DispatchSemaphore(value: 0)
        DispatchQueue.global(qos: .userInitiated).async {
            let there = exists(path)
            answer.lock.lock(); answer.value = there; answer.lock.unlock()
            done.signal()
        }
        guard done.wait(timeout: .now() + timeout) == .success else { return nil }
        answer.lock.lock(); defer { answer.lock.unlock() }
        return answer.value
    }

    /// `Board.read`, with a time limit. Nil when it did not answer in time
    /// (audit 1, finding 10): the remembered board was asked whether it was
    /// there with a limit and then read with none, so a network volume going
    /// away between the two still froze the start.
    static func readQuickly(_ path: String, timeout: Double = readSeconds,
                            read: @escaping (String) -> Result<Board, BoardReadFailure> = {
                                Board.read($0) }) -> Result<Board, BoardReadFailure>? {
        final class Answer: @unchecked Sendable {
            let lock = NSLock()
            var value: Result<Board, BoardReadFailure>?
        }
        let answer = Answer()
        let done = DispatchSemaphore(value: 0)
        DispatchQueue.global(qos: .userInitiated).async {
            let got = read(path)
            answer.lock.lock(); answer.value = got; answer.lock.unlock()
            done.signal()
        }
        guard done.wait(timeout: .now() + timeout) == .success else { return nil }
        answer.lock.lock(); defer { answer.lock.unlock() }
        return answer.value
    }

    /// Copy a board that will not load out of harm's way. Its new path, or
    /// nil if even that failed.
    ///
    /// Beside the original, named for what happened to it and when. An
    /// identical copy already there from an earlier start the same minute is
    /// the same copy, not a failure.
    static func keepUnreadable(_ path: String, now: Date = Date()) -> String? {
        let files = FileManager.default
        guard let original = files.contents(atPath: path) else { return nil }
        let ns = path as NSString
        let ext = ns.pathExtension.isEmpty ? "json" : ns.pathExtension
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.dateFormat = "yyyy-MM-dd HHmm"
        let stem = "\(ns.deletingPathExtension) (could not be read \(format.string(from: now))"
        var candidate = "\(stem)).\(ext)"
        var count = 2
        while files.fileExists(atPath: candidate) {
            if files.contents(atPath: candidate) == original { return candidate }
            candidate = "\(stem), \(count)).\(ext)"
            count += 1
        }
        do {
            try files.copyItem(atPath: path, toPath: candidate)
            return candidate
        } catch {
            return nil
        }
    }

    // ----------------------------------------------------- what is said ---

    /// A board file said aloud: its name without the .json on the end.
    static func boardWords(_ path: String?) -> String {
        let name = (((path ?? "") as NSString).lastPathComponent as NSString).deletingPathExtension
        return name.isEmpty ? "The board" : name
    }

    /// The folder a file is in, by its own name only. Never the whole path:
    /// VoiceOver reads a path as one long run of words and slashes.
    static func folderWords(_ path: String?) -> String {
        let folder = (((path ?? "") as NSString).deletingLastPathComponent as NSString)
            .lastPathComponent
        return folder.isEmpty || folder == "/" ? "its folder" : folder
    }

    static func notReached(_ path: String, missing reachable: Bool?) -> String {
        "The board you had open last time, \(boardWords(path)), "
            + (reachable == nil ? "could not be reached"
                                : "is not in \(folderWords(path)) any more")
            + ". File, Open board finds it"
    }

    static func couldNotRead(_ path: String, _ failure: BoardReadFailure, kept: Bool) -> String {
        // Said without the copy's file name, which is all brackets and a date
        // and reads as noise.
        "\(boardWords(path)) could not be read, \(failure.reason). "
            + (kept ? "A copy is kept in the same folder, so nothing is lost"
                    : "It has been left alone, and will not be saved over")
    }

    static func openedInstead(_ path: String) -> String {
        "\(boardWords(path)) opened instead"
    }

    static func notSavedOver(_ path: String?) -> String {
        "\(boardWords(path)) was changed outside Drop Deck, so it has not been saved "
            + "over. File, Open board opens the new one"
    }

    static func keptBeside(_ path: String?) -> String {
        let name = boardWords(path)
        return "\(name) was changed outside Drop Deck, so it was not saved over. Your "
             + "changes are in a copy beside it, and the new \(name) opens next time"
    }

    static func changedWhileBusy(_ path: String?) -> String {
        "\(boardWords(path)) has been changed outside Drop Deck. It will not be saved "
            + "over. File, Open board loads the new one when you are ready"
    }

    static func changedAndUnreadable(_ path: String?, _ failure: BoardReadFailure) -> String {
        "\(boardWords(path)) was changed outside Drop Deck, and the new one cannot be "
            + "read, \(failure.reason). It will not be saved over"
    }

    /// The board's file name, or nothing when it is the usual one.
    static func boardName(_ path: String?, configDir: String = Board.configDir()) -> String {
        guard let path, !path.isEmpty,
              !Board.samePath(path, defaultBoardPath(configDir: configDir)) else { return "" }
        return boardWords(path)
    }

    /// The board half of the startup line, in Windows' order.
    ///
    /// What went wrong with the board comes BEFORE the count, so it is heard
    /// first rather than at the end of a long line, and the hint about
    /// starting from scratch is dropped when there is a problem to hear,
    /// because it is the one sentence that would bury it. The board's name
    /// is said when it is not the usual one, because the board that opens is
    /// now whichever was open last, and somebody with two boards should hear
    /// which this is.
    ///
    /// The running order is counted too (Windows 3.10.0, `_playlist_tail`),
    /// so a board that is all playlist does not open as "0 sounds loaded".
    static func startupParts(note: String, loadedDemo: Bool, assigned: Int,
                             boardName: String, tracks: Int = 0) -> [String] {
        var parts: [String] = []
        if !note.isEmpty { parts.append(note) }
        let tail = tracks > 0 ? ", \(tracks) playlist track\(tracks == 1 ? "" : "s")" : ""
        if loadedDemo {
            parts.append("demo pack loaded, \(assigned) sounds and beds" + tail
                         + (note.isEmpty ? ". File, new board starts you from scratch" : ""))
        } else {
            parts.append((boardName.isEmpty ? "" : boardName + ", ") + "\(assigned) sounds loaded" + tail)
        }
        return parts
    }

    // -------------------------------------------------- which board opens ---

    struct Startup {
        let board: Board
        /// What the startup line says about the board, or "".
        let note: String
        let loadedDemo: Bool
        /// A remembered board that was not there today. It stays remembered
        /// for next time: a memory stick left out for one start must not
        /// cost it for good.
        let pinned: String?
    }

    /// The board you had open last time, otherwise yours, otherwise the demo.
    ///
    /// A board that will not load is never replaced in silence: it is copied
    /// aside first, and if even that fails it is claimed as unreadable, so it
    /// is never written over at all. `reach` is how a remembered board is
    /// asked about, with a time limit; the usual board.json is asked
    /// directly, as Windows does.
    static func loadStartup(configDir: String, demoPath: String?,
                            reach: (String) -> Bool? = { existsQuickly($0) },
                            readRemembered: (String) -> Result<Board, BoardReadFailure>? = {
                                readQuickly($0) },
                            now: Date = Date()) -> Startup {
        let usual = defaultBoardPath(configDir: configDir)
        var candidates: [(String, Bool)] = []
        if let remembered = rememberedBoardPath(configDir: configDir),
           !Board.samePath(remembered, usual) {
            candidates.append((remembered, true))
        }
        candidates.append((usual, false))
        var notes: [String] = []
        var pinned: String?
        var untouchable = false
        for (path, wasRemembered) in candidates {
            let there: Bool? = wasRemembered ? reach(path)
                                             : FileManager.default.fileExists(atPath: path)
            guard there == true else {
                if wasRemembered {
                    notes.append(notReached(path, missing: there))
                    pinned = path
                }
                continue
            }
            // The remembered one is READ with a limit too; the usual one is
            // read directly, as Windows does.
            let got: Result<Board, BoardReadFailure>
            if wasRemembered {
                guard let answered = readRemembered(path) else {
                    notes.append(notReached(path, missing: nil))
                    pinned = path
                    continue
                }
                got = answered
            } else {
                got = Board.read(path)
            }
            switch got {
            case .success(let board):
                if !notes.isEmpty { notes.append(openedInstead(path)) }
                return Startup(board: board, note: notes.joined(separator: ". "),
                               loadedDemo: false, pinned: pinned)
            case .failure(let failure):
                let kept = keepUnreadable(path, now: now)
                if kept == nil && Board.samePath(path, usual) { untouchable = true }
                notes.append(couldNotRead(path, failure, kept: kept != nil))
            }
        }
        var board: Board?
        var loadedDemo = false
        if let demoPath, let demo = Board.load(demoPath) {
            board = demo
            loadedDemo = true
        }
        let chosen = board ?? Board()
        // The demo's own file is not this board's file and nothing at the
        // usual path was read, so what is there now is written down rather
        // than owned.
        chosen.claimPath(usual, unreadable: untouchable)
        return Startup(board: chosen, note: notes.joined(separator: ". "),
                       loadedDemo: loadedDemo, pinned: pinned)
    }
}

// ------------------------------------------------------------- saving ---

/// Where a save goes, and what it did. The window's half of `Board.save`.
///
/// Every save the app makes comes through here: the autosave, Command S, Save
/// board as, the save on closing and the save on quitting. Nothing saves over
/// a board file that changed outside the app since it was read, and nothing
/// shows a box.
final class BoardKeeper {

    enum Outcome: Equatable {
        /// Written where the board lives, or where somebody chose.
        case saved(String)
        /// The board's own file was somebody else's by now, so what was on
        /// screen went beside it.
        case keptBeside(original: String?, copy: String)
        /// The board's own file was somebody else's by now and nothing had
        /// changed here, so nothing was written at all.
        case leftAlone(String?)
        case failed(String)
    }

    let board: Board
    let configDir: String
    /// A board that opens next time instead of the one just saved: the one
    /// that came in from outside, or a remembered one that was away today.
    var pinned: String?

    init(board: Board, configDir: String = Board.configDir(), pinned: String? = nil) {
        self.board = board
        self.configDir = configDir
        self.pinned = pinned
    }

    /// Write the board, to `target` when somebody chose a place.
    ///
    /// A path chosen in Save board as is a decision, and that one is
    /// honoured. Anything else goes through the guard.
    func save(to target: String? = nil) -> Outcome {
        if target == nil && board.changedOnDisk() { return changedElsewhere() }
        do {
            let saved = try board.save(to: target)
            // A place somebody chose is the board from now on.
            if target != nil { pinned = nil }
            remember(saved)
            return .saved(saved)
        } catch {
            return .failed(error.localizedDescription)
        }
    }

    /// The save on the way out, from closing the window AND from quitting.
    ///
    /// Quitting used to save twice (N12), once from the window and once from
    /// the app, and the second must be harmless: after a clash the board is
    /// pointed at the copy it just wrote and is no longer dirty, so the second
    /// pass writes that copy again with the same contents and never makes a
    /// second one.
    ///
    /// **A new board nobody has put anything in is not written at all**
    /// (3.10.0). Writing it would leave an empty "New board" file behind and
    /// make it the board that opens, empty, at the next start.
    func saveForClose() -> Outcome? {
        if unstarted && !board.dirty { return nil }
        return save()
    }

    /// The two second timer. **It writes only a board that has something to
    /// write.** A timer still running when one board took another's place
    /// used to save the newcomer, which is how an untouched new board got a
    /// file, and how File, New wrote eighty empty slots over a saved board.
    func autosave() -> Outcome? {
        board.dirty ? save() : nil
    }

    // ------------------------------------------ one board for another ---
    //
    // Siena Trigiani and Rob Castrogiovanni, 15 November 2026: boards saved
    // with Command S came back empty. File, New kept the old board's PATH,
    // because on a Mac the board object stays and `adopt` with no path kept
    // the one it had; the next save then wrote the new, empty board over the
    // saved one. Load demo and Import did the same, and File, Open dropped
    // whatever had changed in the last two seconds. Windows 3.10.0 fixed the
    // same fault the same way, and these are its rules:
    //
    //   1. Before any board takes the open one's place, the open one is put
    //      away: a change not yet written is written to ITS OWN file now.
    //   2. A board that takes another's place never takes its FILE. New, the
    //      demo and an import each get a file of their own in the settings
    //      folder, which is not written until something changes.

    /// The file this session gave a board that has no name yet, while it is
    /// still that board's. See `leftoverHome`.
    var freshHome: String?
    /// The board is a new one, given a file of its own by `giveNewHome`,
    /// which nobody has changed yet. Such a board is not saved on closing.
    var unstarted = false

    /// The open board is about to be replaced: keep everything in it.
    ///
    /// Nil when there was nothing to write. Otherwise what the save did; a
    /// `.failed` is the window's cue to ask before going on, because a read
    /// only file or a drive that has gone would otherwise shut somebody out
    /// of New and Open for as long as it lasts.
    func putAway() -> Outcome? {
        guard board.dirty else { return nil }
        return save()
    }

    /// What the app keeps in its settings folder under names of its own,
    /// less the .json. A board is never given one of these: an old bank
    /// called last_board, imported, would be written over by the note of
    /// which board opens next.
    static let settingsOwn: Set<String> = [
        "board", "last_board", "donate", "install", "feedback_queue",
        "last_app_check", "settings", "errors",
    ]

    /// Something typed, made safe to be a file and a folder name. May be "".
    ///
    /// The same rule as Windows, so a board named on one machine has the
    /// same name on the other: no characters Windows refuses, no control
    /// characters, nothing ending in a dot or a space, and a name typed with
    /// ".json" on the end means the name without it.
    static func fileWords(_ text: String) -> String {
        let refused = Set("<>:\"/\\|?*")
        let mapped = String(text.map { ch -> Character in
            if refused.contains(ch) { return " " }
            if let scalar = ch.unicodeScalars.first, scalar.value < 32 { return " " }
            return ch
        })
        var words = mapped.split(whereSeparator: { $0 == " " || $0 == "\t" })
            .joined(separator: " ")
        if words.lowercased().hasSuffix(".json") { words = String(words.dropLast(5)) }
        let trim = CharacterSet(charactersIn: " .")
        words = words.trimmingCharacters(in: trim)
        return String(words.prefix(80)).trimmingCharacters(in: trim)
    }

    /// A board file of its own for a board that has no name yet: "New
    /// board", "New board 2" and so on, in the settings folder, never a file
    /// that is already there. Nothing is written by asking.
    static func newHome(_ name: String = "New board", configDir: String) -> String {
        var stem = fileWords(name)
        if stem.isEmpty { stem = "New board" }
        if settingsOwn.contains(stem.lowercased()) { stem = "Imported " + stem }
        let folder = configDir as NSString
        var candidate = folder.appendingPathComponent(stem + ".json")
        var count = 2
        while FileManager.default.fileExists(atPath: candidate) {
            candidate = folder.appendingPathComponent("\(stem) \(count).json")
            count += 1
        }
        return candidate
    }

    /// Point the board at a file of its own, claimed as nothing there. It is
    /// written the first time something changes, and not before.
    @discardableResult
    func giveNewHome(_ name: String = "New board") -> String {
        let home = BoardKeeper.newHome(name, configDir: configDir)
        board.claimPath(home)
        board.dirty = false
        freshHome = home
        unstarted = true
        // A board pinned earlier in the session is not this one.
        pinned = nil
        return home
    }

    /// A board somebody opened from a file, or that came back changed: it
    /// has a name, so nothing about a fresh home applies to it.
    func forgetNewHome() {
        freshHome = nil
        unstarted = false
    }

    /// The file a not yet named board is in, when it is ours to remove.
    ///
    /// Only the file this session gave this very board, that the board
    /// itself wrote, and that nothing has changed since. Anything else at
    /// that path is somebody's own and is left alone.
    func leftoverHome() -> String? {
        guard let home = freshHome, Board.samePath(home, board.path),
              case .stamp? = board.disk,
              FileManager.default.fileExists(atPath: home),
              !board.changedOnDisk() else { return nil }
        return home
    }

    /// Save board as, for the window: the save, and then the "New board"
    /// file the board was kept in until it had a name, which holds nothing
    /// the named one does not. Left behind, every board ever named would
    /// leave a twin.
    func saveAs(_ target: String) -> Outcome {
        let leftover = leftoverHome()
        let outcome = save(to: target)
        guard case .saved(let saved) = outcome else { return outcome }
        forgetNewHome()
        if let leftover, !Board.samePath(leftover, saved),
           Board.samePath(BoardFiles.rememberedBoardPath(configDir: configDir), saved) {
            try? FileManager.default.removeItem(atPath: leftover)
        }
        return outcome
    }

    /// Is there, or will there be, a file holding this board. False only
    /// for a board as it arrived with no file of its own: the demo as it
    /// shipped, or a new board, neither changed since.
    var hasAFile: Bool {
        if board.dirty { return true }
        if unstarted { return false }
        return board.disk != .nothingThere
    }

    /// A board's name for a sentence. The usual one is "Your board".
    static func boardSaid(_ path: String?, configDir: String) -> String {
        guard let path, !path.isEmpty,
              !Board.samePath(path, BoardFiles.defaultBoardPath(configDir: configDir))
        else { return "Your board" }
        return BoardFiles.boardWords(path)
    }

    /// What happens to the open board when another takes its place, for the
    /// box that asks. It has to be TRUE, so it is worked out: the demo as it
    /// shipped has no file and is not given one for being looked at, so
    /// saying it "is saved" would be a promise nothing keeps.
    func keptWords() -> String {
        guard hasAFile else { return "The demo pack comes back with File, Load demo pack." }
        return "\(BoardKeeper.boardSaid(board.path, configDir: configDir)) is saved first "
             + "and stays exactly as it is. File, Open board brings it back."
    }

    /// The board's own file was changed outside the app. Keep both.
    ///
    /// Nothing changed here since the file was read: the file on disk is the
    /// newer one and it wins, and it opens next time. Changed here as well:
    /// what is on screen goes beside it under a new name, so neither is lost,
    /// and the one that came in still opens next time.
    private func changedElsewhere() -> Outcome {
        let original = board.path
        guard board.dirty else { return .leftAlone(original) }
        do {
            let copy = try board.save(to: board.sidecarPath())
            pinned = original ?? Board.defaultBoardPath()
            remember(copy)
            return .keptBeside(original: original, copy: copy)
        } catch {
            return .failed(error.localizedDescription)
        }
    }

    /// Write down which board opens next time. Normally the one just saved.
    /// After a clash, the one that came in, not the copy beside it: that is
    /// the whole point of copying a board in.
    func remember(_ saved: String) {
        BoardFiles.rememberBoardPath(pinned ?? saved, configDir: configDir)
    }

    /// A board somebody opened is their choice, so nothing pinned earlier in
    /// the session outranks it.
    func opened(_ path: String) {
        pinned = nil
        BoardFiles.rememberBoardPath(path, configDir: configDir)
    }

    /// What to say about an outcome, or nil for nothing. `quiet` is the
    /// autosave, which says nothing about a save that simply worked.
    static func sentence(_ outcome: Outcome, quiet: Bool) -> String? {
        switch outcome {
        case .saved(let path):
            return quiet ? nil : "Saved to \((path as NSString).lastPathComponent)"
        case .keptBeside(let original, _):
            return BoardFiles.keptBeside(original)
        case .leftAlone(let original):
            return quiet ? nil : BoardFiles.notSavedOver(original)
        case .failed(let why):
            return "The board was not saved. \(why)"
        }
    }

    // ------------------------------------------------ coming back to it ---

    /// Each version of the file already acted on. See `comingBack`.
    var seenVersion: String?

    /// What is at the board's path when the app starts, when that is a file
    /// this board does not own: one it could not read, or one that was not
    /// there and now is. It has already been spoken about in the startup
    /// line, so the first time the app comes forward must not announce it
    /// again as "changed outside Drop Deck".
    func noteStartingVersion() {
        guard let path = board.path, let disk = board.disk,
              disk == .unreadable || disk == .nothingThere,
              let now = Board.diskStamp(path) else { return }
        seenVersion = now.hash
    }

    enum ComingBack: Equatable {
        case nothing
        case say(String)
        case load(Board)

        static func == (a: ComingBack, b: ComingBack) -> Bool {
            switch (a, b) {
            case (.nothing, .nothing): return true
            case (.say(let x), .say(let y)): return x == y
            case (.load(let x), .load(let y)): return x === y
            default: return false
            }
        }
    }

    /// Coming back to the window after the board's file changed meanwhile.
    ///
    /// Somebody who copies a board into place in Finder comes straight back
    /// here to use it, so when nothing is playing, live, open or changed on
    /// screen the new file is simply loaded. Otherwise it is said once and
    /// nothing moves: a file dropping in must never cut a show off mid sound.
    ///
    /// **Each version of the file is acted on ONCE, and nothing here shows a
    /// box.** On Windows the load went through the Open board path, which
    /// shows a box when the file will not load; closing the box brought the
    /// window back, which asked again, and the box came back for ever. Mark
    /// found it with a board holding one stray comma.
    func comingBack(_ look: Look, busy: Bool) -> ComingBack {
        let path = look.path
        guard look.changed, Board.samePath(board.path, path) else { return .nothing }
        // **Stale: the app has written the file itself since the look began**
        // (audit 1, finding 10). The look compared the file with what was
        // known BEFORE it left the main thread; an autosave in between makes
        // the app's own write look like somebody else's, which said "changed
        // outside Drop Deck" about nothing, or reloaded the board for no
        // reason. The next look, with what is known now, is the one to trust.
        guard board.disk == look.knowledge else { return .nothing }
        let version = look.now.map { $0.hash } ?? "unreadable \(path)"
        if version == seenVersion { return .nothing }
        seenVersion = version
        if busy || board.dirty { return .say(BoardFiles.changedWhileBusy(path)) }
        // Read on the look's own thread, never here: this runs on the main
        // one, and a board on a network volume that has gone away can take
        // most of a minute to answer.
        switch look.read {
        case .success(let fresh)?: return .load(fresh)
        case .failure(let failure)?:
            return .say(BoardFiles.changedAndUnreadable(path, failure))
        case nil:
            return .say(BoardFiles.changedAndUnreadable(path, .missing))
        }
    }

    /// Everything `comingBack` needs to know about the file, found out on any
    /// thread but the main one: whether it changed since `knowledge`, what it
    /// is now, and what reading it gives. Nothing here touches the board.
    struct Look {
        let path: String
        let knowledge: DiskKnowledge?
        let changed: Bool
        let now: DiskStamp?
        let read: Result<Board, BoardReadFailure>?
    }

    static func look(path: String, knowledge: DiskKnowledge?) -> Look {
        let changed = Board.changedOnDisk(path: path, knowledge: knowledge)
        return Look(path: path, knowledge: knowledge, changed: changed,
                    now: changed ? Board.diskStamp(path) : nil,
                    read: changed ? Board.read(path) : nil)
    }
}
