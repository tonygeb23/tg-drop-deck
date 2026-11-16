// File, Export board with its sounds.
//
// Ali Moosa, 14 October 2026: "I exported my soundboard to Google Drive ...
// It does not import the board with the original files." A board only ever
// held where its sounds were on the computer it was made on. An export is
// one folder holding the board and a copy of every sound it plays, written
// with paths RELATIVE to itself and forward slashes, so it opens as it is on
// any computer, Windows included: carried in Google Drive, on a USB stick or
// in a zip. Windows 3.9.0's `Board.export_with_sounds`, rule for rule.
//
// Everything here works on values handed in, never on the live board, so it
// runs on a thread of its own and is checked on real files.

import Foundation

struct ExportStopped: Error {}

/// A yes or no that one thread sets and another reads.
final class StopFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false
    func set() { lock.lock(); value = true; lock.unlock() }
    func reset() { lock.lock(); value = false; lock.unlock() }
    var isSet: Bool { lock.lock(); defer { lock.unlock() }; return value }
}

struct ExportResult {
    let board: String
    let copied: Int
    /// The paths that could not be found or read, left pointing where they
    /// were in the exported board.
    let missing: [String]
    let bytes: Int64
}

enum BoardExport {

    /// Every file or folder a board plays, once each, in board order: the
    /// pads, then the running order, then the drops.
    static func soundPaths(_ board: Board) -> [String] {
        var seen = Set<String>()
        var out: [String] = []
        let all = board.slots.compactMap { $0.filepath }.filter { !$0.isEmpty }
            + board.playlist.tracks.map(\.filepath).filter { !$0.isEmpty }
            + board.drops.paths
        for path in all {
            let key = (path as NSString).standardizingPath.lowercased()
            if seen.insert(key).inserted { out.append(path) }
        }
        return out
    }

    /// What an exported board and its folder are called, before anybody
    /// types a name. The settings folder's own board is board.json, and a
    /// folder called "board" in somebody's Google Drive says nothing about
    /// what is in it.
    static func defaultName(_ path: String?) -> String {
        let stem = BoardPaths.stem(path)
        if stem.isEmpty || stem.lowercased() == "board" { return "Drop Deck board" }
        return stem
    }

    /// A folder that does not exist yet, or one with nothing in it.
    static func emptyOrAbsent(_ path: String) -> Bool {
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: path, isDirectory: &isDir) else { return true }
        guard isDir.boolValue else { return false }
        let names = (try? FileManager.default.contentsOfDirectory(atPath: path)) ?? []
        return names.filter { $0 != ".DS_Store" }.isEmpty
    }

    /// `chosen/name`, or `chosen/name (2)` and so on until it is free.
    static func target(in chosen: String, name: String) -> String {
        var target = (chosen as NSString).appendingPathComponent(name)
        var count = 2
        while !emptyOrAbsent(target) {
            target = (chosen as NSString).appendingPathComponent("\(name) (\(count))")
            count += 1
        }
        return target
    }

    /// Copy the board `data` and every sound in `paths` into `target`.
    ///
    /// `data` and `paths` are the board as it was when the export was asked
    /// for, taken on the main thread by the caller: read at the end of a long
    /// copy, a pad added meanwhile went into the board without its sound
    /// (Mark, Windows). `progress(done, total)` is called as the copy goes and
    /// may throw `ExportStopped`. A sound that cannot be read is counted as
    /// missing and the rest carry on: one sound must not cost the export.
    static func export(data: [String: Any], paths: [String], to target: String, name: String,
                       progress: ((Int64, Int64) throws -> Void)? = nil) throws -> ExportResult {
        let files = FileManager.default
        let boardFile = (target as NSString).appendingPathComponent(name + ".json")
        if files.fileExists(atPath: boardFile) {
            throw NSError(domain: "DropDeck", code: 17, userInfo: [
                NSLocalizedDescriptionKey: "there is already a board called \(name) there"])
        }
        let sounds = (target as NSString).appendingPathComponent(C.exportSoundsFolder)
        try files.createDirectory(atPath: sounds, withIntermediateDirectories: true)

        var plan: [(String, String)] = []
        var missing: [String] = []
        var taken = Set<String>()
        var mapping: [String: String] = [:]

        func destination(_ wanted: String, folder: Bool) -> String {
            let stem = folder ? wanted : (wanted as NSString).deletingPathExtension
            let ext = folder ? "" : (wanted as NSString).pathExtension
            var candidate = wanted
            var count = 2
            while taken.contains(candidate.lowercased()) {
                candidate = "\(stem) (\(count))" + (ext.isEmpty ? "" : "." + ext)
                count += 1
            }
            taken.insert(candidate.lowercased())
            return (sounds as NSString).appendingPathComponent(candidate)
        }

        for path in paths {
            let key = (path as NSString).standardizingPath.lowercased()
            var isDir: ObjCBool = false
            guard files.fileExists(atPath: path, isDirectory: &isDir) else {
                missing.append(path)
                continue
            }
            if isDir.boolValue {
                // A folder pad: its sound files, as a folder.
                let destDir = destination(BoardPaths.basename(path), folder: true)
                mapping[key] = destDir
                try files.createDirectory(atPath: destDir, withIntermediateDirectories: true)
                let names = ((try? files.contentsOfDirectory(atPath: path)) ?? []).sorted()
                for item in names where AudioFile.canPlay(path: item) {
                    let full = (path as NSString).appendingPathComponent(item)
                    var inner: ObjCBool = false
                    if files.fileExists(atPath: full, isDirectory: &inner), !inner.boolValue {
                        plan.append((full, (destDir as NSString).appendingPathComponent(item)))
                    }
                }
            } else {
                let dest = destination(BoardPaths.basename(path), folder: false)
                mapping[key] = dest
                plan.append((path, dest))
            }
        }

        func size(_ path: String) -> Int64 {
            ((try? files.attributesOfItem(atPath: path))?[.size] as? NSNumber)?.int64Value ?? 0
        }
        let total = plan.reduce(Int64(0)) { $0 + size($1.0) }
        var done: Int64 = 0
        var copied = 0
        for (source, dest) in plan {
            let bytes = size(source)
            do {
                done = try copy(source, to: dest, done: done, total: total, progress: progress)
                copied += 1
            } catch let stop as ExportStopped {
                throw stop
            } catch {
                missing.append(source)
                done += bytes
                for (key, moved) in mapping where moved == dest { mapping.removeValue(forKey: key) }
            }
        }

        let written = BoardPaths.mapSoundPaths(data) { path in
            let moved = mapping[(path as NSString).standardizingPath.lowercased()] ?? path
            return BoardPaths.portable(moved, base: target)
        }
        let json = try JSONSerialization.data(withJSONObject: written,
                                              options: [.prettyPrinted, .sortedKeys])
        let temp = boardFile + ".tmp"
        defer { try? files.removeItem(atPath: temp) }
        try json.write(to: URL(fileURLWithPath: temp))
        try files.moveItem(atPath: temp, toPath: boardFile)
        return ExportResult(board: boardFile, copied: copied, missing: missing, bytes: total)
    }

    /// One file, in blocks, reporting the running total. The running total.
    private static func copy(_ source: String, to dest: String, done start: Int64, total: Int64,
                             progress: ((Int64, Int64) throws -> Void)?) throws -> Int64 {
        try progress?(start, total)
        let files = FileManager.default
        let temp = dest + ".part"
        var done = start
        do {
            guard let input = FileHandle(forReadingAtPath: source) else {
                throw CocoaError(.fileReadNoPermission)
            }
            defer { try? input.close() }
            guard files.createFile(atPath: temp, contents: nil),
                  let output = FileHandle(forWritingAtPath: temp) else {
                throw CocoaError(.fileWriteNoPermission)
            }
            defer { try? output.close() }
            while true {
                let chunk = try input.read(upToCount: 1 << 20) ?? Data()
                if chunk.isEmpty { break }
                try output.write(contentsOf: chunk)
                done += Int64(chunk.count)
                try progress?(done, total)
            }
            try output.close()
            if files.fileExists(atPath: dest) { try files.removeItem(atPath: dest) }
            try files.moveItem(atPath: temp, toPath: dest)
        } catch {
            try? files.removeItem(atPath: temp)
            throw error
        }
        if let when = (try? files.attributesOfItem(atPath: source))?[.modificationDate] as? Date {
            try? files.setAttributes([.modificationDate: when], ofItemAtPath: dest)
        }
        return done
    }
}
