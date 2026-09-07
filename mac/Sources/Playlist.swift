// The running order, its cue points, and the two decks.
//
// The playlist plays on two decks, exactly the way a playout system does: the
// outgoing song on one and the incoming song on the other, and a crossfade is
// the two of them overlapping. Their slot indices sit above the eighty pads so
// the mixer needs no special case for any of it.
//
// Two rules that the arithmetic below exists to keep, and that are easy to
// undo:
//
//   A crossfade is measured from where the MUSIC stops, not where the file
//   does. An MP3 carries a second or two of digital silence on the end, so
//   cueing three seconds from the last sample puts most of the crossfade
//   inside that silence. Nothing on the cue path may go back to using
//   `duration` directly.
//
//   The incoming track comes in AT LEVEL and the outgoing one rides down.
//   Both tracks ramping is a DJ blend, not a radio segue, and it is what made
//   a crossfade sound like a hole.

import Foundation

final class Track {
    var filepath: String
    var title: String?
    var artist: String?
    var duration: Double?
    /// Measured once, on a background pass, and saved with the board.
    /// nil means not measured yet, which is a different answer from zero.
    var tailSilence: Double?
    /// nil means "use the playlist's crossfade", which is a different answer
    /// from zero and must stay that way.
    var crossfade: Double?
    var enabled = true
    var kind: String = C.trackSong
    var trimDB: Double = 0.0
    var unknown: [String: Any] = [:]

    init(filepath: String) { self.filepath = filepath }

    var isDrop: Bool { kind == C.trackDrop }

    var isMissing: Bool { !FileManager.default.fileExists(atPath: filepath) }

    var displayName: String {
        if let t = title, !t.isEmpty { return t }
        let base = (filepath as NSString).lastPathComponent
        return (base as NSString).deletingPathExtension
    }

    /// Where the music stops, as opposed to where the file does.
    var playableEnd: Double {
        guard let d = duration, d > 0 else { return 0.0 }
        let tail = min(max(tailSilence ?? 0.0, 0.0), d)
        return max(0.0, d - tail)
    }

    func crossfadeSeconds(default fallback: Double) -> Double {
        if let c = crossfade { return c }
        // A drop butts up against the song behind it. It is a spot, not a
        // segue, and fading one under a song is how a station sounds sloppy.
        return isDrop ? 0.0 : fallback
    }

    func readMetadata() {
        if duration == nil || tailSilence == nil {
            if let info = AudioFile.probe(filepath) {
                duration = info.duration
            }
        }
        if title == nil || artist == nil {
            let tags = AudioFile.tags(filepath)
            if title == nil { title = tags.title }
            if artist == nil { artist = tags.artist }
        }
        if tailSilence == nil {
            tailSilence = AudioFile.tailSilence(filepath, duration: duration)
        }
    }

    func toDict() -> [String: Any] {
        var d = unknown
        d["filepath"] = filepath
        d["title"] = title as Any? ?? NSNull()
        d["artist"] = artist as Any? ?? NSNull()
        d["duration"] = duration as Any? ?? NSNull()
        d["tail_silence"] = tailSilence as Any? ?? NSNull()
        d["crossfade"] = crossfade as Any? ?? NSNull()
        d["enabled"] = enabled
        d["kind"] = kind
        d["trim_db"] = trimDB
        return d
    }

    static func fromDict(_ data: [String: Any]) -> Track? {
        guard let p = data["filepath"] as? String, !p.isEmpty else { return nil }
        let t = Track(filepath: p)
        let known: Set<String> = ["filepath", "title", "artist", "duration",
                                  "tail_silence", "crossfade", "enabled",
                                  "kind", "trim_db"]
        t.unknown = data.filter { !known.contains($0.key) }
        t.title = data["title"] as? String
        t.artist = data["artist"] as? String
        t.duration = data["duration"] as? Double
        t.tailSilence = data["tail_silence"] as? Double
        t.crossfade = data["crossfade"] as? Double
        t.enabled = data["enabled"] as? Bool ?? true
        if let k = data["kind"] as? String { t.kind = k }
        t.trimDB = data["trim_db"] as? Double ?? 0.0
        return t
    }
}

final class Playlist {

    var tracks: [Track] = []
    var crossfade: Double = C.defaultCrossfade

    var count: Int { tracks.count }
    var isEmpty: Bool { tracks.isEmpty }

    /// Ticked and on disk. An unticked item keeps its place in the list and is
    /// stepped over.
    func willPlay(_ index: Int) -> Bool {
        guard tracks.indices.contains(index) else { return false }
        let t = tracks[index]
        return t.enabled && !t.isMissing
    }

    var enabledTracks: [Track] { tracks.enumerated().filter { willPlay($0.offset) }.map(\.element) }

    func nextPlaying(after index: Int) -> Int? {
        var i = index + 1
        while i < tracks.count {
            if willPlay(i) { return i }
            i += 1
        }
        return nil
    }

    func previousPlaying(before index: Int) -> Int? {
        var i = index - 1
        while i >= 0 {
            if willPlay(i) { return i }
            i -= 1
        }
        return nil
    }

    func firstPlayable(from index: Int = 0) -> Int? {
        var i = max(0, index)
        while i < tracks.count {
            if willPlay(i) { return i }
            i += 1
        }
        return nil
    }

    private func clean(_ value: Double?, fallback: Double) -> Double {
        guard let v = value, v.isFinite else { return fallback }
        return min(C.maxCrossfade, max(0.0, v))
    }

    /// How long this item overlaps the next one, as the user asked for it.
    func crossfadeFor(_ index: Int) -> Double {
        guard willPlay(index), nextPlaying(after: index) != nil else { return 0.0 }
        let track = tracks[index]
        var fade = clean(track.crossfadeSeconds(default: crossfade), fallback: crossfade)
        let end = track.playableEnd
        if end > 0 { fade = min(fade, end) }
        return max(0.0, fade)
    }

    /// The overlap actually used, which is never less than SEGUE_LEAD.
    ///
    /// A drop that hands over only once its last sample has played leaves a
    /// hole: the tick that notices, and then the moment the next file takes to
    /// open.
    func handoverAt(_ index: Int) -> Double {
        guard willPlay(index), nextPlaying(after: index) != nil else { return 0.0 }
        var overlap = max(crossfadeFor(index), C.segueLead)
        let end = tracks[index].playableEnd
        if end > 0 { overlap = min(overlap, end) }
        return max(0.0, overlap)
    }

    /// When each item starts, counted from the beginning of the running order.
    /// A skipped item has no start time at all, which is a different answer
    /// from zero.
    func cuePoints() -> [Double?] {
        var points: [Double?] = []
        var clock = 0.0
        for i in tracks.indices {
            guard willPlay(i) else { points.append(nil); continue }
            points.append(clock)
            clock += max(0.0, tracks[i].playableEnd - handoverAt(i))
        }
        return points
    }

    var totalDuration: Double {
        let points = cuePoints()
        guard let last = tracks.indices.reversed().first(where: { willPlay($0) }),
              let start = points[last] else { return 0.0 }
        let t = tracks[last]
        let tail = t.playableEnd > 0 ? t.playableEnd : (t.duration ?? 0.0)
        return start + tail
    }

    // ---------------------------------------------------------- persistence ---

    func toDict() -> [String: Any] {
        ["crossfade": crossfade, "tracks": tracks.map { $0.toDict() }]
    }

    func load(from data: [String: Any], relativeTo folder: String?) {
        if let c = data["crossfade"] as? Double { crossfade = clean(c, fallback: C.defaultCrossfade) }
        tracks = (data["tracks"] as? [[String: Any]] ?? []).compactMap { row in
            guard let t = Track.fromDict(row) else { return nil }
            if !(t.filepath as NSString).isAbsolutePath, let folder {
                t.filepath = (folder as NSString).appendingPathComponent(t.filepath)
            }
            return t
        }
    }

    /// The line under the running order, and what the view says out loud.
    func summary() -> String {
        guard !tracks.isEmpty else {
            return "Nothing in the running order yet. Copy some files in Finder and press Command V here."
        }
        let songs = tracks.filter { !$0.isDrop }.count
        let drops = tracks.filter { $0.isDrop }.count
        let unticked = tracks.filter { !$0.enabled }.count
        var parts = ["\(tracks.count) items"]
        if songs > 0 { parts.append("\(songs) song\(songs == 1 ? "" : "s")") }
        if drops > 0 { parts.append("\(drops) drop\(drops == 1 ? "" : "s")") }
        if unticked > 0 { parts.append("\(unticked) unticked") }
        let total = totalDuration
        if total > 0 { parts.append(formatDuration(total)) }
        parts.append(crossfade > 0 ? "crossfade \(formatDuration(crossfade))" : "no crossfade")
        return parts.joined(separator: ".  ")
    }
}

// ------------------------------------------------------------ building it ---
//
// The half of dropdeck/playlist.py that puts things INTO the running order.
// Durations and tags are taken here, once, because that is what the cue points
// are made of, and because measuring them later would mean measuring them
// while the show is on. The run out is NOT measured here: that means decoding,
// and pasting an album should not stop the app for two seconds. See
// MainWindow.measureTails.

extension Playlist {

    /// The audio files out of a mixed bag of paths, folders expanded.
    ///
    /// Pasting from Finder hands over whatever was selected, which for an album
    /// is usually the folder. Taking the folder's contents is what somebody who
    /// selected it meant; taking nothing is not.
    static func playable(_ paths: [String]) -> [String] {
        let fm = FileManager.default
        var found: [String] = []
        for path in paths {
            var isDir: ObjCBool = false
            guard fm.fileExists(atPath: path, isDirectory: &isDir) else { continue }
            if isDir.boolValue {
                for name in (try? fm.contentsOfDirectory(atPath: path))?.sorted() ?? [] {
                    let full = (path as NSString).appendingPathComponent(name)
                    var inner: ObjCBool = false
                    guard fm.fileExists(atPath: full, isDirectory: &inner), !inner.boolValue,
                          AudioFile.canPlay(path: full) else { continue }
                    found.append(full)
                }
            } else if AudioFile.canPlay(path: path) {
                found.append(path)
            }
        }
        return found
    }

    /// One Track, with its length measured. nil if the file will not open.
    static func makeTrack(_ path: String, kind: String = C.trackSong,
                          crossfade: Double? = nil) -> Track? {
        guard AudioFile.canPlay(path: path) else { return nil }
        let t = Track(filepath: path)
        t.kind = kind
        t.crossfade = crossfade
        if let info = AudioFile.probe(path) { t.duration = info.duration }
        // The tags are read here too, because the file is already open in every
        // practical sense and reading them costs about a millisecond.
        let tags = AudioFile.tags(path)
        t.title = tags.title
        t.artist = tags.artist
        return t
    }

    var missing: [Track] { tracks.filter(\.isMissing) }

    private func insert(_ added: [Track], at: Int?) {
        if let at, at < tracks.count {
            tracks.insert(contentsOf: added, at: max(0, at))
        } else {
            tracks.append(contentsOf: added)
        }
    }

    /// Put files into the running order. Returns the tracks that went in.
    @discardableResult
    func add(_ paths: [String], at: Int? = nil, kind: String = C.trackSong) -> [Track] {
        let added = Playlist.playable(paths).compactMap { Playlist.makeTrack($0, kind: kind) }
        guard !added.isEmpty else { return [] }
        insert(added, at: at)
        return added
    }

    /// Put items in from a playlist file. Returns the tracks that went in.
    ///
    /// Not `add`, and deliberately: `add` throws away anything that is not a
    /// playable file on this machine right now, which is what you want from a
    /// paste and exactly what you do not want from a saved running order. A
    /// show whose music has moved has to come back with its missing tracks
    /// still in it, in the right order, so File, Relink missing sounds can go
    /// and find them. Dropping them silently would leave somebody rebuilding a
    /// two hour order by hand.
    @discardableResult
    func addEntries(_ entries: [M3UEntry], at: Int? = nil) -> [Track] {
        var added: [Track] = []
        for entry in entries {
            let path = entry.filepath.trimmingCharacters(in: .whitespaces)
            guard !path.isEmpty else { continue }
            let here = FileManager.default.fileExists(atPath: path)
            if here && !AudioFile.canPlay(path: path) { continue }   // a real file, but not one this app can play
            let t = Track(filepath: path)
            t.kind = entry.kind == "drop" ? C.trackDrop : C.trackSong
            if let c = entry.crossfade, c.isFinite { t.crossfade = min(C.maxCrossfade, max(0, c)) }
            t.enabled = entry.enabled
            if here {
                // Measured, because the file is the truth and the number in a
                // playlist file was written by something else. The file's own
                // tags first, then whatever the playlist file said: an M3U
                // exported by something with a better library than the file
                // itself has is worth keeping.
                t.duration = AudioFile.probe(path)?.duration
                let tags = AudioFile.tags(path)
                t.artist = tags.artist ?? entry.artist
                t.title = tags.title ?? entry.title
            } else {
                // Nothing to measure. Keep what the file said so the row can
                // still be read out and recognised.
                t.duration = entry.duration
                t.artist = entry.artist
                t.title = entry.title
            }
            added.append(t)
        }
        guard !added.isEmpty else { return [] }
        insert(added, at: at)
        return added
    }

    /// One drop, at a position. nil if the file is unplayable.
    func insertDrop(_ path: String, at: Int? = nil) -> Track? {
        add([path], at: at, kind: C.trackDrop).first
    }

    /// Where a drop may go after the song at `index` in `original`, by the rules
    /// both insert-every commands share. Counted in songs, not in items, so
    /// running it twice does not start counting the drops it put in last time as
    /// though they were music. Never after the very last song: a drop after the
    /// last song is a drop playing to an empty studio. And never where there is
    /// one already.
    private func wantsDropAfter(_ index: Int, in original: [Track], songs: Int, every: Int) -> Bool {
        guard songs % every == 0 else { return false }
        let rest = original[(index + 1)...]
        if rest.isEmpty || rest.allSatisfy(\.isDrop) { return false }
        if rest.first!.isDrop { return false }
        return true
    }

    /// A drop after every `every` songs. Returns how many went in.
    func insertDropEvery(_ path: String, every: Int) -> Int {
        guard every >= 1, let template = Playlist.makeTrack(path, kind: C.trackDrop) else { return 0 }
        let original = tracks
        var rebuilt: [Track] = []
        var songs = 0
        var inserted = 0
        for (index, track) in original.enumerated() {
            rebuilt.append(track)
            if track.isDrop { continue }
            songs += 1
            guard wantsDropAfter(index, in: original, songs: songs, every: every) else { continue }
            if let copy = Track.fromDict(template.toDict()) {
                rebuilt.append(copy)
                inserted += 1
            }
        }
        tracks = rebuilt
        return inserted
    }

    /// The library version: same placement rules, a different pick each time,
    /// so a countdown does not play the same ident five times.
    func insertDropsEvery(_ library: DropLibrary, every: Int) -> Int {
        guard every >= 1, !library.isEmpty else { return 0 }
        let original = tracks
        var rebuilt: [Track] = []
        var songs = 0
        var inserted = 0
        for (index, track) in original.enumerated() {
            rebuilt.append(track)
            if track.isDrop { continue }
            songs += 1
            guard wantsDropAfter(index, in: original, songs: songs, every: every) else { continue }
            guard let path = library.pick() else { break }
            guard let drop = Playlist.makeTrack(path, kind: C.trackDrop) else { continue }
            rebuilt.append(drop)
            inserted += 1
        }
        tracks = rebuilt
        return inserted
    }

    func clear() { tracks.removeAll() }

    /// Repair moved tracks out of the same folder walk the pads use. `index` is
    /// lower cased file name to full path. Returns what was repaired.
    @discardableResult
    func relink(using index: [String: String]) -> [Track] {
        var repaired: [Track] = []
        for track in tracks where track.isMissing {
            let name = (track.filepath as NSString).lastPathComponent.lowercased()
            guard let found = index[name] else { continue }
            track.filepath = found
            if track.duration == nil { track.duration = AudioFile.probe(found)?.duration }
            repaired.append(track)
        }
        return repaired
    }
}

// ------------------------------------------------------------ the library ---

/// The drops you use over and over, kept in one place.
///
/// Building a running order means reaching for a station ident every few songs,
/// and picking the same file out of the same folder every time is the part that
/// wears thin. So the drops go in here once and Option D takes one at random,
/// never the same one twice running, for the same reason a folder slot does not
/// repeat itself: two identical idents in a row is what makes random sound
/// broken.
///
/// It travels with the board, because a board is a show and a show has its own
/// idents. Opening somebody else's board brings theirs. On disk it is the
/// Windows shape exactly, `{"paths": [...]}`, so a board moves between the two
/// copies with its library intact.
final class DropLibrary {

    private(set) var paths: [String] = []
    private var last: String?

    var count: Int { paths.count }
    var isEmpty: Bool { paths.isEmpty }

    var missing: [String] { paths.filter { !FileManager.default.fileExists(atPath: $0) } }
    /// The ones still on disk. A pick never offers a file that has gone.
    var available: [String] { paths.filter { FileManager.default.fileExists(atPath: $0) } }

    /// Put files in. Returns what was actually added.
    ///
    /// Folders are expanded and anything already in the library is skipped, so
    /// adding the same folder twice does not double every ident in it.
    @discardableResult
    func add(_ newPaths: [String]) -> [String] {
        var added: [String] = []
        for path in Playlist.playable(newPaths) {
            let full = (path as NSString).standardizingPath
            if paths.contains(where: { $0.caseInsensitiveCompare(full) == .orderedSame }) { continue }
            paths.append(full)
            added.append(full)
        }
        return added
    }

    @discardableResult
    func remove(at index: Int) -> String? {
        guard paths.indices.contains(index) else { return nil }
        return paths.remove(at: index)
    }

    @discardableResult
    func clear() -> Int {
        let n = paths.count
        paths.removeAll()
        last = nil
        return n
    }

    /// One drop, at random, never the same one twice running.
    func pick() -> String? {
        var choices = available
        guard !choices.isEmpty else { return nil }
        if choices.count > 1, let last, choices.contains(last) {
            choices.removeAll { $0 == last }
        }
        last = choices.randomElement()
        return last
    }

    /// One row, for the library list.
    func label(_ index: Int) -> String {
        let path = paths[index]
        let name = ((path as NSString).lastPathComponent as NSString).deletingPathExtension
        if !FileManager.default.fileExists(atPath: path) {
            return "\(index + 1). \(name), file missing"
        }
        return "\(index + 1). \(name)"
    }

    /// Repair moved drops out of the same walk everything else uses.
    @discardableResult
    func relink(using index: [String: String]) -> [String] {
        var repaired: [String] = []
        for (position, path) in paths.enumerated()
        where !FileManager.default.fileExists(atPath: path) {
            let name = (path as NSString).lastPathComponent.lowercased()
            guard let found = index[name] else { continue }
            paths[position] = found
            repaired.append(found)
        }
        return repaired
    }

    func replace(with other: DropLibrary) {
        paths = other.paths
        last = nil
    }

    func toDict() -> [String: Any] { ["paths": paths] }

    /// The Windows key is "paths". "files" is read as well because a handful of
    /// boards were written under that key by this build before it matched.
    func load(from data: [String: Any]?, relativeTo folder: String?) {
        paths = []
        last = nil
        let raw = (data?["paths"] as? [Any]) ?? (data?["files"] as? [Any]) ?? []
        for item in raw {
            guard var path = item as? String, !path.trimmingCharacters(in: .whitespaces).isEmpty
            else { continue }
            if !(path as NSString).isAbsolutePath, let folder, !folder.isEmpty {
                path = ((folder as NSString).appendingPathComponent(path) as NSString).standardizingPath
            }
            paths.append(path)
        }
    }
}
