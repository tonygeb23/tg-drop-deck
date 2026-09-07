// Running orders on disk, as M3U.
//
// A board is a show's furniture: eighty pads, the drops library, the settings.
// A running order is the show itself, and people want to keep those. Last
// Tuesday's, the Christmas one, the two hours you had ready before the guest
// cancelled. Tony, 3 September 2026: "in the event people need to save
// playlists of their shows".
//
// M3U rather than a format of this app's own, because a running order is worth
// more if other things can read it. Every player, every phone and every other
// playout system opens an M3U, so a show saved here can be checked in VLC,
// handed to a co-presenter or loaded into the studio machine without this app
// being anywhere near it. A file written by the Windows copy opens here and the
// other way round, which is the whole point of sharing the format.
//
// Three decisions worth knowing about, all of them the Windows module's:
//
//   It is an extended M3U, so each track carries its length and its
//   "Artist - Title" on an #EXTINF line. That is what makes the file readable
//   rather than a column of paths.
//
//   What M3U cannot say is said in comments. Whether an item is a drop, whether
//   it is ticked, and whether it has a crossfade of its own all go on a
//   #DROPDECK line, which every other player ignores and this one reads back.
//
//   Paths under the playlist's own folder are written relative. Save a show
//   into the folder its music lives in and the whole folder can be moved, or
//   copied to another machine, and still work. Anything outside is written in
//   full, because a relative path out of a folder you have moved is worse than
//   no path at all.
//
// Like Playlist.swift, nothing here knows what AppKit is.

import Foundation

/// What one line of a playlist file said about one item. The path is the only
/// thing that has to be there; everything else is filled in from the file
/// itself once it is loaded.
struct M3UEntry {
    var filepath: String
    var title: String?
    var artist: String?
    var duration: Double?
    var kind: String?
    var enabled = true
    var crossfade: Double?
}

enum M3U {

    static let extensions = ["m3u", "m3u8"]
    static let header = "#EXTM3U"
    /// Our own line. Anything else reading this file sees a comment.
    static let mark = "#DROPDECK:"

    static func isPlaylistFile(_ path: String) -> Bool {
        extensions.contains((path as NSString).pathExtension.lowercased())
    }

    // ---------------------------------------------------------------- writing ---

    /// "Artist - Title", or just the title. What every other player shows.
    private static func extinfTitle(_ track: Track) -> String {
        let artist = (track.artist ?? "").trimmingCharacters(in: .whitespaces)
        let title = track.displayName
        return artist.isEmpty ? title : "\(artist) - \(title)"
    }

    /// A path relative to `folder`, but only if it really is under it.
    ///
    /// A relative path that begins with ".." breaks the moment the playlist is
    /// moved, which is the one thing a relative path was supposed to survive.
    static func relativeIfUnder(_ path: String, _ folder: String?) -> String {
        guard let folder, !folder.isEmpty else { return path }
        let base = (folder as NSString).standardizingPath
        let full = (path as NSString).standardizingPath
        let prefix = base.hasSuffix("/") ? base : base + "/"
        guard full.hasPrefix(prefix), full.count > prefix.count else { return path }
        return String(full.dropFirst(prefix.count))
    }

    /// The bits of a track that M3U has no way of saying.
    private static func fields(_ track: Track) -> [String] {
        var found: [String] = []
        if track.isDrop { found.append("kind=drop") }
        if !track.enabled { found.append("enabled=0") }
        if let c = track.crossfade { found.append("crossfade=" + String(format: "%g", c)) }
        return found
    }

    /// The whole running order as M3U text. `folder` is where the file is
    /// going, which is what decides whether a path can be written relative.
    static func dumps(_ playlist: Playlist, folder: String? = nil) -> String {
        var lines = [header,
                     "#PLAYLIST:\(C.appName) running order",
                     mark + "crossfade=" + String(format: "%g", playlist.crossfade)]
        for track in playlist.tracks {
            let seconds = (track.duration ?? 0) > 0 ? Int(track.duration!.rounded()) : -1
            lines.append("#EXTINF:\(seconds),\(extinfTitle(track))")
            let extra = fields(track)
            if !extra.isEmpty { lines.append(mark + extra.joined(separator: " ")) }
            lines.append(relativeIfUnder(track.filepath, folder))
        }
        return lines.joined(separator: "\n") + "\n"
    }

    /// Write the running order to `path`. Returns how many items went in.
    ///
    /// UTF-8 with no byte order mark, for both extensions, and CRLF line ends
    /// like the Windows copy writes, so the two files are byte for byte the
    /// same shape. A BOM makes some older players read the first path as
    /// though it began with three junk characters.
    @discardableResult
    static func save(_ path: String, playlist: Playlist) throws -> Int {
        let folder = ((path as NSString).standardizingPath as NSString).deletingLastPathComponent
        let text = dumps(playlist, folder: folder)
            .replacingOccurrences(of: "\n", with: "\r\n")
        try text.data(using: .utf8)!.write(to: URL(fileURLWithPath: path))
        return playlist.count
    }

    // ---------------------------------------------------------------- reading ---

    /// Text out of bytes, however the thing that wrote it felt about encoding.
    ///
    /// UTF-8 first, with a byte order mark stripped if there is one. Then
    /// Windows-1252, which is what an M3U written before about 2010 will be,
    /// and then Latin-1, which cannot fail, so there is always an answer.
    static func decode(_ raw: Data) -> String {
        var data = raw
        if data.count >= 3, data[0] == 0xEF, data[1] == 0xBB, data[2] == 0xBF {
            data = data.subdata(in: 3..<data.count)
        }
        if let s = String(data: data, encoding: .utf8) { return s }
        if let s = String(data: data, encoding: .windowsCP1252) { return s }
        return String(data: data, encoding: .isoLatin1) ?? ""
    }

    private static func parseFields(_ text: String) -> [String: String] {
        var found: [String: String] = [:]
        for piece in text.split(whereSeparator: { $0 == " " || $0 == "\t" }) {
            guard let eq = piece.firstIndex(of: "=") else { continue }
            let key = piece[..<eq].trimmingCharacters(in: .whitespaces).lowercased()
            let value = piece[piece.index(after: eq)...].trimmingCharacters(in: .whitespaces)
            found[key] = value
        }
        return found
    }

    /// One line of a playlist turned into a path on this machine.
    ///
    /// Handles the things that turn up: an ordinary path, a path with
    /// backslashes in it because it was written on Windows, and a file:// URL,
    /// which several players write and which is a perfectly good way of saying
    /// the same thing.
    static func resolve(_ line: String, folder: String?) -> String? {
        var entry = line.trimmingCharacters(in: .whitespaces)
        if entry.hasPrefix("\"") && entry.hasSuffix("\"") && entry.count >= 2 {
            entry = String(entry.dropFirst().dropLast())
        }
        guard !entry.isEmpty else { return nil }
        let lowered = entry.lowercased()
        if lowered.hasPrefix("file:") {
            guard let url = URL(string: entry) ?? URL(string: entry.addingPercentEncoding(
                withAllowedCharacters: .urlPathAllowed) ?? entry) else { return nil }
            var path = url.path
            if let host = url.host, !host.isEmpty { path = "//\(host)\(path)" }
            // file:///C:/x turns into /C:/x, which is not a path anybody wants.
            if path.count > 2, path.hasPrefix("/"),
               path[path.index(path.startIndex, offsetBy: 2)] == ":" {
                path.removeFirst()
            }
            entry = path
        } else if lowered.prefix(8).contains("://") {
            return nil                   // http and the rest: not something we play
        }
        // A relative path written on Windows has backslashes and no slashes.
        // A Mac file name may legitimately contain a backslash, so only a path
        // with no forward slash at all is treated as a Windows one.
        if entry.contains("\\") && !entry.contains("/") {
            entry = entry.replacingOccurrences(of: "\\", with: "/")
        }
        if !(entry as NSString).isAbsolutePath, let folder, !folder.isEmpty {
            entry = (folder as NSString).appendingPathComponent(entry)
        }
        return (entry as NSString).standardizingPath
    }

    /// Parse M3U text. Whatever wrote the file, the path is the only thing that
    /// has to be there.
    static func loads(_ text: String, folder: String? = nil) -> (entries: [M3UEntry], crossfade: Double?) {
        var entries: [M3UEntry] = []
        var crossfade: Double?
        var pending: [String: String] = [:]
        // A byte order mark that survived decoding, or came in with pasted
        // text, would turn the header line into a path.
        var body = text
        if body.hasPrefix("\u{FEFF}") { body.removeFirst() }
        for rawLine in body.components(separatedBy: .newlines) {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }
            if line.hasPrefix(mark) {
                let found = parseFields(String(line.dropFirst(mark.count)))
                if entries.isEmpty, pending.isEmpty, let c = found["crossfade"] {
                    crossfade = Double(c)
                    continue
                }
                pending.merge(found) { _, new in new }
                continue
            }
            if line.uppercased().hasPrefix("#EXTINF:") {
                let info = String(line.dropFirst("#EXTINF:".count))
                let length: Substring
                let title: Substring
                if let comma = info.firstIndex(of: ",") {
                    length = info[..<comma]
                    title = info[info.index(after: comma)...]
                } else {
                    length = Substring(info)
                    title = ""
                }
                if let seconds = Double(length.trimmingCharacters(in: .whitespaces)), seconds > 0 {
                    pending["duration"] = String(seconds)
                }
                let cleanTitle = title.trimmingCharacters(in: .whitespaces)
                if !cleanTitle.isEmpty {
                    if let range = cleanTitle.range(of: " - ") {
                        let artist = cleanTitle[..<range.lowerBound].trimmingCharacters(in: .whitespaces)
                        let rest = cleanTitle[range.upperBound...].trimmingCharacters(in: .whitespaces)
                        if !rest.isEmpty {
                            pending["artist"] = artist
                            pending["title"] = rest
                        } else {
                            pending["title"] = cleanTitle
                        }
                    } else {
                        pending["title"] = cleanTitle
                    }
                }
                continue
            }
            if line.hasPrefix("#") { continue }        // somebody else's comment
            guard let path = resolve(line, folder: folder) else { pending = [:]; continue }
            var entry = M3UEntry(filepath: path)
            entry.title = pending["title"]
            entry.artist = pending["artist"]
            entry.duration = pending["duration"].flatMap(Double.init)
            entry.kind = pending["kind"]?.lowercased()
            entry.enabled = pending["enabled"] != "0"
            entry.crossfade = pending["crossfade"].flatMap(Double.init)
            entries.append(entry)
            pending = [:]
        }
        return (entries, crossfade)
    }

    /// Read a playlist file.
    static func load(_ path: String) throws -> (entries: [M3UEntry], crossfade: Double?) {
        let raw = try Data(contentsOf: URL(fileURLWithPath: path))
        let folder = ((path as NSString).standardizingPath as NSString).deletingLastPathComponent
        return loads(decode(raw), folder: folder)
    }
}
