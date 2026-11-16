// Paths that travel: a board written on Windows read here, a board written
// here read on Windows, and a board carried between them in a cloud folder.
//
// Siena Trigiani, 12 October 2026: a board made on Windows and saved to
// Google Drive relinked fine on another Windows laptop, and on the Mac said
// "16 sounds still missing" with every one of them in the folder she chose.
// On macOS a backslash is not a separator, so `lastPathComponent` of
// "G:\My Drive\SienaT Radio\intro.mp3" is that WHOLE string, which matches
// no file name anywhere. Every Windows path failed, every time.
//
// Ali Moosa, 14 October 2026: a board saved to Google Drive opened elsewhere
// with its whole playlist missing, because a board only held where its sounds
// were on the computer it was made on. Windows 3.9.0 answered both; this is
// the Mac half, with Windows' rules (`dropdeck/board.py`, `_basename`,
// `_portable`, `_is_relative`, `_index_folder`).

import Foundation

enum BoardPaths {

    /// The last part of a path written on EITHER system. Windows'
    /// `board._basename`, exactly: split on both slashes after trimming any
    /// trailing ones.
    static func basename(_ path: String?) -> String {
        guard var text = path, !text.isEmpty else { return "" }
        while let last = text.last, last == "/" || last == "\\" { text.removeLast() }
        return text.split(omittingEmptySubsequences: false, whereSeparator: { $0 == "/" || $0 == "\\" })
            .last.map(String.init) ?? ""
    }

    /// The file name without its extension, on either system.
    static func stem(_ path: String?) -> String {
        (basename(path) as NSString).deletingPathExtension
    }

    /// A Windows absolute path: a drive ("G:\", "G:/") or a share ("\\server").
    /// Not absolute to macOS, and never to be joined onto a board's folder:
    /// that gave "<board folder>/G:\My Drive\..." until 3.10.0.
    static func isWindowsAbsolute(_ path: String) -> Bool {
        let chars = Array(path)
        if chars.count >= 2, chars[0] == "\\", chars[1] == "\\" { return true }
        if chars.count >= 3, chars[0].isLetter, chars[0].isASCII, chars[1] == ":",
           chars[2] == "\\" || chars[2] == "/" { return true }
        return false
    }

    /// A path written relative to its board, on either system. Windows'
    /// `_is_relative`: anything starting with a slash of either kind, or a
    /// drive, is somebody's absolute path and is kept exactly as written.
    static func isRelative(_ path: String?) -> Bool {
        guard let path, let first = path.first else { return false }
        if first == "/" || first == "\\" || first == "~" { return false }
        if path.count >= 2, Array(path)[1] == ":" { return false }
        return true
    }

    /// A relative path made whole against the board's folder. A board written
    /// on Windows may use either slash, so both are separators here.
    static func resolve(_ path: String, folder: String) -> String {
        let forward = path.replacingOccurrences(of: "\\", with: "/")
        return ((folder as NSString).appendingPathComponent(forward) as NSString).standardizingPath
    }

    /// `path` relative to `base` if it is under it, with forward slashes,
    /// which both copies read. Anything else is handed back as it came.
    /// Windows' `_portable`.
    static func portable(_ path: String, base: String) -> String {
        guard !path.isEmpty, !base.isEmpty, (path as NSString).isAbsolutePath else { return path }
        let full = ((path as NSString).standardizingPath as NSString).resolvingSymlinksInPath
        let root = ((base as NSString).standardizingPath as NSString).resolvingSymlinksInPath
        let rootSlash = root.hasSuffix("/") ? root : root + "/"
        // Compared without regard to case, because APFS usually is.
        guard full.lowercased().hasPrefix(rootSlash.lowercased()) else { return path }
        let rest = String(full.dropFirst(rootSlash.count))
        return rest.isEmpty ? path : rest
    }

    /// Every sound path in a board dictionary rewritten with `change`, the
    /// pads, the running order and the drops library. Windows'
    /// `_map_sound_paths`.
    static func mapSoundPaths(_ data: [String: Any], _ change: (String) -> String) -> [String: Any] {
        var out = data
        if let slots = data["slots"] as? [[String: Any]] {
            out["slots"] = slots.map { row -> [String: Any] in
                var row = row
                if let p = row["filepath"] as? String, !p.isEmpty { row["filepath"] = change(p) }
                return row
            }
        }
        if var playlist = data["playlist"] as? [String: Any],
           let tracks = playlist["tracks"] as? [[String: Any]] {
            playlist["tracks"] = tracks.map { row -> [String: Any] in
                var row = row
                if let p = row["filepath"] as? String, !p.isEmpty { row["filepath"] = change(p) }
                return row
            }
            out["playlist"] = playlist
        }
        if var drops = data["drops"] as? [String: Any], let paths = drops["paths"] as? [String] {
            drops["paths"] = paths.map(change)
            out["drops"] = drops
        }
        return out
    }

    // ------------------------------------------------------------- looking ---

    struct Index {
        /// Lower cased file name (and, with stems, name without its
        /// extension for a sound file) to the full path.
        var files: [String: String] = [:]
        /// Lower cased folder name to the full path. A pad that held a folder
        /// must be repaired with a folder, or a random pick pad silently
        /// becomes a one shot.
        var folders: [String: String] = [:]
    }

    /// Breadth first, so where a name appears twice the SHALLOWER one wins
    /// (Mark, 16 October 2026: depth first handed back a/b/c/x.wav ahead of
    /// z/x.wav). `depth`, `seconds` and `entries` bound it and are checked
    /// at every entry; left out, it is the whole tree, which is what a relink
    /// somebody asked for has always done.
    static func index(_ folder: String, recursive: Bool = true, depth: Int? = nil,
                      seconds: Double? = nil, entries: Int? = nil,
                      stems: Bool = true) -> Index {
        var found = Index()
        let files = FileManager.default
        let deadline = seconds.map { Date().addingTimeInterval($0) }
        var seen = 0
        var queue: [(String, Int)] = [(folder, 0)]
        var head = 0
        while head < queue.count {
            let (root, level) = queue[head]
            head += 1
            guard let names = try? files.contentsOfDirectory(atPath: root) else { continue }
            for name in names.sorted(by: { $0.lowercased() < $1.lowercased() }) {
                seen += 1
                if let entries, seen > entries { return found }
                if let deadline, Date() > deadline { return found }
                if name.hasPrefix(".") { continue }
                let full = (root as NSString).appendingPathComponent(name)
                var isDir: ObjCBool = false
                guard files.fileExists(atPath: full, isDirectory: &isDir) else { continue }
                let key = name.lowercased()
                if isDir.boolValue {
                    if found.folders[key] == nil { found.folders[key] = full }
                    if recursive, depth == nil || level + 1 < depth! { queue.append((full, level + 1)) }
                    continue
                }
                if found.files[key] == nil { found.files[key] = full }
                let ext = (name as NSString).pathExtension.lowercased()
                if stems, AudioFile.supportedExtensions.contains(ext) {
                    let stem = (name as NSString).deletingPathExtension.lowercased()
                    if found.files[stem] == nil { found.files[stem] = full }
                }
            }
        }
        return found
    }

    /// `index` on a thread of its own, abandoned if it has not answered in
    /// `wait` seconds. The clock inside the walk cannot interrupt one folder
    /// on a sleeping network drive that takes most of a minute to list, so
    /// the caller is never held longer than the bound, whatever the disk
    /// does. Nil when it did not answer in time.
    static func indexWithin(_ wait: Double, _ folder: String, depth: Int, seconds: Double,
                            entries: Int) -> Index? {
        final class Answer: @unchecked Sendable {
            let lock = NSLock()
            var value: Index?
        }
        let answer = Answer()
        let done = DispatchSemaphore(value: 0)
        DispatchQueue.global(qos: .userInitiated).async {
            let got = index(folder, depth: depth, seconds: seconds, entries: entries, stems: false)
            answer.lock.lock(); answer.value = got; answer.lock.unlock()
            done.signal()
        }
        guard done.wait(timeout: .now() + wait) == .success else { return nil }
        answer.lock.lock(); defer { answer.lock.unlock() }
        return answer.value
    }
}

/// What `Board.findBeside` repaired by guessing, so a save can put the board
/// file's own paths back. **A guess is never written down**: writing it
/// replaced a real path on a drive that was only unplugged today with a
/// same named file that happened to be nearby, and marking the board changed
/// stopped a synced board reloading when the other computer saved it (Mark,
/// 16 October 2026). Each computer looks again when it opens the board.
///
/// Remembered per ITEM, not per found file: one file beside the board can
/// stand in for a playlist track written on a Mac and a drop written on
/// Windows, and each must get its own path back.
struct Guesses {
    var items: [ObjectIdentifier: (guess: String, original: String)] = [:]
    var drops: [Int: (guess: String, original: String)] = [:]
    var isEmpty: Bool { items.isEmpty && drops.isEmpty }
    mutating func clear() { items.removeAll(); drops.removeAll() }
}
