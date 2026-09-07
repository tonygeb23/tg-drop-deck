// Update the app itself.
//
// The same channel as dropdeck/appupdate.py, in the same shape, signed with the
// same TG Studios update key: one update mechanism across every TG Studios app,
// one set of traps already found, one thing to fix if it ever breaks. Only the
// feed URL differs, drop-deck-mac.json beside drop-deck-app.json, because a
// Mac cannot run the Windows installer and the two builds may not always ship
// on the same day.
//
// The trust model is the Windows one and deliberately strict, because this ends
// in replacing an executable:
//
//   1. The manifest is ed25519 signed. The public half is baked in below and
//      must never change once shipped, or every installed copy silently stops
//      seeing updates.
//   2. The download is SHA-256'd against the signed manifest before anything
//      is done with it.
//   3. Nothing is downloaded or installed without the user saying yes.
//
// Point 3 is not negotiable. A free app that silently replaces itself is
// indistinguishable from malware, and for a screen reader user an app vanishing
// underneath them mid show is worse than no update at all.
//
// THE SIGNED BYTES. The Windows publisher signs json.dumps(manifest,
// sort_keys=True, separators=(",", ":")), which is compact, key sorted and
// ASCII only, with everything outside space to tilde written as \uXXXX. This
// file rebuilds those exact bytes from the parsed manifest, and the self test
// holds a sample of Python's own output to prove it byte for byte. Get one
// escape wrong and every manifest is "signed by the wrong key" for ever, with
// nothing anywhere reporting why.
//
// HOW A MAC COPY REPLACES ITSELF. Windows will not let a running executable be
// overwritten, so there the NEW copy does the swap after the old one exits.
// macOS has no such rule: a running bundle can be renamed and moved with the
// process none the wiser. So the running copy does its own swap, the old bundle
// is RENAMED aside rather than deleted, put back if anything fails, and removed
// by the new copy on its first launch. The relaunch is a detached shell that
// waits a second first, because the new copy's single instance check would
// otherwise find this one still quitting and hand back to it.

import Foundation
import CryptoKit

enum AppUpdate {

    /// Public half of the TG Studios installer update key. Baked in.
    static let publicKeyB64 = "kJOlcZKYCyYBk/1JrmyfxFSX5Vf6JiM7oXf+0PEDZ04="

    static let manifestURL = URL(string: "https://tgstudios.app/updates/drop-deck-mac.json")!
    static let timeout: TimeInterval = 30
    /// The app is about 3 MB zipped. This is slack, not a target.
    static let maxBytes = 120 * 1024 * 1024
    static let stampFile = "last_app_check.json"
    static let defaultIntervalHours = 24.0

    struct Info {
        let version: String
        let url: String
        let sha256: String
        let size: Int
        let notes: String
        let minMacOS: String?
        let raw: [String: Any]

        init?(_ raw: [String: Any]) {
            guard let version = raw["version"] as? String,
                  let url = raw["url"] as? String else { return nil }
            self.version = version
            self.url = url
            self.sha256 = (raw["sha256"] as? String ?? "").lowercased()
            self.size = raw["size"] as? Int ?? 0
            self.notes = (raw["notes"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            self.minMacOS = raw["min_macos"] as? String
            self.raw = raw
        }
    }

    struct CheckResult {
        let available: Bool
        let info: Info?
        let message: String
    }

    // -------------------------------------------------------------- versions ---

    /// "3.2.2" to [3, 2, 2]. Unreadable parts sort as 0 rather than failing.
    /// Compared as numbers, never as strings: "0.10.0" is older than "0.9.0" as
    /// a string and newer as a version, and getting that backwards means an
    /// update that never offers itself again.
    static func parseVersion(_ text: String?) -> [Int] {
        var out = (text ?? "0").split(separator: ".").map { part -> Int in
            Int(part.filter { $0.isNumber }) ?? 0
        }
        while out.count < 3 { out.append(0) }
        return Array(out.prefix(3))
    }

    static func isNewer(_ candidate: String?, than current: String) -> Bool {
        parseVersion(candidate).lexicographicallyPrecedes(parseVersion(current)) == false
            && parseVersion(candidate) != parseVersion(current)
    }

    // ------------------------------------------------------- canonical bytes ---

    /// The exact bytes Python's json.dumps(sort_keys=True, separators=(",",":"))
    /// produces for the same object. See the file comment.
    static func canonical(_ object: Any) -> Data {
        var out = ""
        write(object, into: &out)
        return Data(out.utf8)
    }

    private static func write(_ value: Any, into out: inout String) {
        switch value {
        case let dict as [String: Any]:
            out.append("{")
            let keys = dict.keys.sorted { a, b in
                a.unicodeScalars.map(\.value).lexicographicallyPrecedes(b.unicodeScalars.map(\.value))
            }
            for (i, key) in keys.enumerated() {
                if i > 0 { out.append(",") }
                writeString(key, into: &out)
                out.append(":")
                write(dict[key]!, into: &out)
            }
            out.append("}")
        case let list as [Any]:
            out.append("[")
            for (i, item) in list.enumerated() {
                if i > 0 { out.append(",") }
                write(item, into: &out)
            }
            out.append("]")
        case let s as String:
            writeString(s, into: &out)
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() {
                out.append(n.boolValue ? "true" : "false")
            } else if String(cString: n.objCType) == "d" || String(cString: n.objCType) == "f" {
                writeDouble(n.doubleValue, into: &out)
            } else {
                out.append("\(n.int64Value)")
            }
        case let b as Bool:
            out.append(b ? "true" : "false")
        case let i as Int:
            out.append("\(i)")
        case let d as Double:
            writeDouble(d, into: &out)
        case is NSNull:
            out.append("null")
        default:
            out.append("null")
        }
    }

    private static func writeDouble(_ d: Double, into out: inout String) {
        // Python's repr: the shortest text that reads back to the same number,
        // and always with a point in it. Swift's description is the same rule.
        out.append("\(d)")
    }

    /// Python's ensure_ascii escaping: the seven short escapes, and \uXXXX with
    /// lower case hex for anything else outside space to tilde, as a surrogate
    /// pair above the basic plane.
    private static func writeString(_ s: String, into out: inout String) {
        out.append("\"")
        for scalar in s.unicodeScalars {
            switch scalar {
            case "\"": out.append("\\\"")
            case "\\": out.append("\\\\")
            case "\n": out.append("\\n")
            case "\r": out.append("\\r")
            case "\t": out.append("\\t")
            case "\u{08}": out.append("\\b")
            case "\u{0C}": out.append("\\f")
            default:
                let v = scalar.value
                if v >= 0x20 && v <= 0x7E {
                    out.unicodeScalars.append(scalar)
                } else if v < 0x10000 {
                    out.append(String(format: "\\u%04x", v))
                } else {
                    let shifted = v - 0x10000
                    out.append(String(format: "\\u%04x\\u%04x",
                                      0xD800 + (shifted >> 10), 0xDC00 + (shifted & 0x3FF)))
                }
            }
        }
        out.append("\"")
    }

    // -------------------------------------------------------------- verifying ---

    static func verify(_ payload: Data, signatureB64: String,
                       publicKeyB64: String = publicKeyB64) -> Bool {
        guard let keyBytes = Data(base64Encoded: publicKeyB64),
              let signature = Data(base64Encoded: signatureB64),
              let key = try? Curve25519.Signing.PublicKey(rawRepresentation: keyBytes)
        else { return false }
        return key.isValidSignature(signature, for: payload)
    }

    /// Parse an envelope and check its signature. The message is what the user
    /// is told when it fails.
    static func parseEnvelope(_ data: Data, publicKeyB64: String = publicKeyB64)
        -> (info: Info?, message: String?) {
        guard let raw = try? JSONSerialization.jsonObject(with: data),
              let envelope = raw as? [String: Any],
              let manifest = envelope["manifest"] as? [String: Any],
              let signature = envelope["signature"] as? String else {
            return (nil, "The update server sent something unreadable.")
        }
        guard verify(canonical(manifest), signatureB64: signature, publicKeyB64: publicKeyB64) else {
            return (nil, "The update was signed by the wrong key and was rejected. Nothing was changed.")
        }
        guard let info = Info(manifest) else {
            return (nil, "The update server sent something unreadable.")
        }
        return (info, nil)
    }

    /// Is there a newer build, given the envelope bytes?
    static func evaluate(_ data: Data, currentVersion: String,
                         publicKeyB64: String = publicKeyB64) -> CheckResult {
        let (info, problem) = parseEnvelope(data, publicKeyB64: publicKeyB64)
        guard let info else { return CheckResult(available: false, info: nil, message: problem ?? "") }
        guard isNewer(info.version, than: currentVersion) else {
            return CheckResult(available: false, info: info, message: "You have the newest version.")
        }
        return CheckResult(available: true, info: info,
                           message: "Version \(info.version) is available. You have \(currentVersion).")
    }

    // --------------------------------------------------------------- fetching ---

    enum FetchError: LocalizedError {
        case status(Int), tooLarge, noData, transport(String)
        var errorDescription: String? {
            switch self {
            case .status(let code): return "the server answered \(code)"
            case .tooLarge: return "the download was larger than expected"
            case .noData: return "the server sent nothing"
            case .transport(let why): return why
            }
        }
    }

    /// One download, waited for. Only ever called off the main thread.
    static func fetch(_ url: URL, limit: Int = maxBytes) throws -> Data {
        var request = URLRequest(url: url)
        request.timeoutInterval = timeout
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("\(C.appName.replacingOccurrences(of: " ", with: ""))/\(C.appVersion)",
                         forHTTPHeaderField: "User-Agent")
        let done = DispatchSemaphore(value: 0)
        var got: Data?
        var failure: Error?
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error { failure = FetchError.transport(error.localizedDescription) }
            else if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                failure = FetchError.status(http.statusCode)
            } else { got = data }
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + timeout + 10)
        if let failure { throw failure }
        guard let got else { throw FetchError.noData }
        if got.count > limit { throw FetchError.tooLarge }
        return got
    }

    /// Ask the server. Off the main thread.
    static func check(currentVersion: String = C.appVersion) -> CheckResult {
        let data: Data
        do { data = try fetch(manifestURL, limit: 1024 * 1024) } catch {
            return CheckResult(available: false, info: nil,
                               message: "Could not reach the update server. \(error.localizedDescription)")
        }
        return evaluate(data, currentVersion: currentVersion)
    }

    /// Fetch the download and check it against the signed hash. The file is
    /// only left on disk if the hash matched, so there is never a half verified
    /// download sitting in a temporary folder for somebody to open by hand.
    static func download(_ info: Info) -> (path: String?, message: String) {
        guard let url = URL(string: info.url) else {
            return (nil, "The update names a download address that is not an address.")
        }
        let blob: Data
        do { blob = try fetch(url) } catch {
            return (nil, "Download failed. \(error.localizedDescription)")
        }
        let digest = SHA256.hash(data: blob).map { String(format: "%02x", $0) }.joined()
        guard digest == info.sha256 else {
            return (nil, "The download did not match its signed checksum, so it was thrown away. "
                       + "Nothing was installed.")
        }
        let folder = (NSTemporaryDirectory() as NSString)
            .appendingPathComponent("dropdeck-update-\(UUID().uuidString.prefix(8))")
        let name = url.lastPathComponent.isEmpty ? "TG-Drop-Deck-mac.zip" : url.lastPathComponent
        let path = (folder as NSString).appendingPathComponent(name)
        do {
            try FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
            try blob.write(to: URL(fileURLWithPath: path))
        } catch {
            return (nil, "The download could not be saved. \(error.localizedDescription)")
        }
        return (path, "Downloaded \(info.version).")
    }

    // ------------------------------------------------------------- throttling ---

    private static func stampPath(_ configDir: String) -> String {
        (configDir as NSString).appendingPathComponent(stampFile)
    }

    static func lastChecked(_ configDir: String) -> TimeInterval {
        guard let data = FileManager.default.contents(atPath: stampPath(configDir)),
              let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let when = raw["last_check"] as? Double else { return 0 }
        return when
    }

    static func stampCheck(_ configDir: String, when: TimeInterval = Date().timeIntervalSince1970) {
        try? FileManager.default.createDirectory(atPath: configDir, withIntermediateDirectories: true)
        if let data = try? JSONSerialization.data(withJSONObject: ["last_check": when]) {
            try? data.write(to: URL(fileURLWithPath: stampPath(configDir)))
        }
    }

    static func shouldCheck(_ configDir: String, intervalHours: Double = defaultIntervalHours,
                            now: TimeInterval = Date().timeIntervalSince1970) -> Bool {
        let elapsed = now - lastChecked(configDir)
        // A clock that moved backwards must not lock out checking until it
        // catches up, so a negative gap counts as due.
        return elapsed < 0 || elapsed >= intervalHours * 3600
    }

    /// Only a copy in Applications is offered a replacement of itself. A build
    /// sitting in the build folder is the developer's, and replacing it would
    /// put a release where the next build was about to go.
    static var isInstalledCopy: Bool {
        let path = Bundle.main.bundlePath
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return path.hasPrefix("/Applications/") || path.hasPrefix(home + "/Applications/")
    }

    /// (available, info, message). A nil message means nothing happened and the
    /// user should not be told anything, so a normal launch stays silent.
    static func autoCheck(_ configDir: String, force: Bool = false,
                          intervalHours: Double = defaultIntervalHours) -> (Bool, Info?, String?) {
        if !isInstalledCopy && !force { return (false, nil, nil) }
        if !force && !shouldCheck(configDir, intervalHours: intervalHours) { return (false, nil, nil) }
        stampCheck(configDir)      // stamp first, so a dead server is not retried every launch
        let result = check()
        if !result.available { return (false, result.info, force ? result.message : nil) }
        return (true, result.info, result.message)
    }

    // ------------------------------------------------------------- installing ---

    static func stagingRoot() -> String {
        (Board.configDir() as NSString).appendingPathComponent("update-staging")
    }

    /// Remove what an update leaves behind: the staging folder, and the old
    /// bundle set aside next to this one. Called at startup by the copy that
    /// came after, which is the only copy that can.
    static func cleanLeftovers() {
        let fm = FileManager.default
        try? fm.removeItem(atPath: stagingRoot())
        let aside = Bundle.main.bundlePath + ".replaced"
        if fm.fileExists(atPath: aside) { try? fm.removeItem(atPath: aside) }
    }

    @discardableResult
    private static func run(_ tool: String, _ arguments: [String]) -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: tool)
        p.arguments = arguments
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return -1 }
        p.waitUntilExit()
        return p.terminationStatus
    }

    enum InstallError: LocalizedError {
        case unpack, noBundle, badSignature
        var errorDescription: String? {
            switch self {
            case .unpack: return "the download could not be unpacked"
            case .noBundle: return "there was no application inside the download"
            case .badSignature: return "the unpacked application failed its code signature check"
            }
        }
    }

    /// Unpack a download into its own staging folder. Returns the .app inside.
    static func unpack(zipPath: String, version: String) throws -> String {
        let fm = FileManager.default
        let target = (stagingRoot() as NSString).appendingPathComponent(version.isEmpty ? "new" : version)
        try? fm.removeItem(atPath: target)
        try fm.createDirectory(atPath: target, withIntermediateDirectories: true)
        guard run("/usr/bin/ditto", ["-xk", zipPath, target]) == 0 else { throw InstallError.unpack }
        // The zip holds the bundle at its top level, or one folder down if it
        // was made by hand. Either is fine.
        func findApp(in folder: String, depth: Int) -> String? {
            guard let names = try? fm.contentsOfDirectory(atPath: folder) else { return nil }
            for name in names.sorted() where name.hasSuffix(".app") {
                return (folder as NSString).appendingPathComponent(name)
            }
            guard depth > 0 else { return nil }
            for name in names.sorted() {
                let inner = (folder as NSString).appendingPathComponent(name)
                var isDir: ObjCBool = false
                if fm.fileExists(atPath: inner, isDirectory: &isDir), isDir.boolValue,
                   let found = findApp(in: inner, depth: depth - 1) { return found }
            }
            return nil
        }
        guard let app = findApp(in: target, depth: 1) else { throw InstallError.noBundle }
        // The hash already proved the bytes are the published ones. This proves
        // the unpack did not mangle them, and costs nothing.
        guard run("/usr/bin/codesign", ["--verify", "--deep", "--strict", app]) == 0 else {
            throw InstallError.badSignature
        }
        return app
    }

    /// Whether the bundle at `target` could be replaced where it stands. Asked
    /// by writing a file next to it rather than by reading permissions, because
    /// what a folder's permissions say and what happens are two different
    /// questions on a Mac with Applications owned by an administrator.
    static func canReplace(_ target: String) -> Bool {
        let parent = (target as NSString).deletingLastPathComponent
        let probe = (parent as NSString).appendingPathComponent(".dropdeck-write-test")
        guard FileManager.default.createFile(atPath: probe, contents: Data()) else { return false }
        try? FileManager.default.removeItem(atPath: probe)
        return true
    }

    /// Put `newApp` where `target` is. The old bundle is RENAMED aside rather
    /// than deleted, put back if anything fails, and left for the new copy to
    /// remove on its first launch. Returns (ok, message).
    static func replace(target: String, with newApp: String) -> (ok: Bool, message: String) {
        let fm = FileManager.default
        let aside = target + ".replaced"
        try? fm.removeItem(atPath: aside)
        if fm.fileExists(atPath: target) {
            do { try fm.moveItem(atPath: target, toPath: aside) } catch {
                return (false, "The copy you have could not be moved aside, so nothing has been "
                             + "changed. \(error.localizedDescription)")
            }
        }
        do {
            try fm.moveItem(atPath: newApp, toPath: target)
        } catch {
            // Across volumes a move is a copy, and a copy can fail half way.
            try? fm.removeItem(atPath: target)
            do { try fm.copyItem(atPath: newApp, toPath: target) } catch {
                try? fm.removeItem(atPath: target)
                if fm.fileExists(atPath: aside) { try? fm.moveItem(atPath: aside, toPath: target) }
                return (false, "The update could not be written, so the copy you had has been put "
                             + "back. \(error.localizedDescription)")
            }
        }
        // Nothing here was downloaded by a browser, and a quarantine flag on a
        // bundle nobody can right click Open past is the download page's
        // problem, not this one's.
        run("/usr/bin/xattr", ["-dr", "com.apple.quarantine", target])
        return (true, "Updated in place.")
    }

    /// Start the app again from `target` once this process has gone. A
    /// detached shell, because the new copy's single instance check would
    /// otherwise find this one still quitting and hand straight back to it.
    static func relaunch(_ target: String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        let quoted = target.replacingOccurrences(of: "'", with: "'\\''")
        p.arguments = ["-c", "sleep 1.2; /usr/bin/open '\(quoted)'"]
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        try? p.run()
    }
}
