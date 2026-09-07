// One slot on the board, and how it describes itself to a screen reader.
//
// A faithful port of dropdeck/slot.py. The label composition in particular is
// not to be improved on: the order of the words in button_label is what a
// screen reader reads when you arrow along a row, and it was arrived at by
// listening to it.

import Foundation

func bankForIndex(_ index: Int) -> Int { index / C.slotsPerBank + 1 }
func positionInBank(_ index: Int) -> Int { index % C.slotsPerBank + 1 }

/// A spoken friendly duration. No bare colons for a screen reader to trip on.
func formatDuration(_ seconds: Double?) -> String {
    guard let seconds, seconds > 0 else { return "" }
    let total = Int(seconds.rounded())
    let minutes = total / 60
    let secs = total % 60
    if minutes > 0 && secs > 0 { return "\(minutes) min \(secs) sec" }
    if minutes > 0 { return "\(minutes) min" }
    return "\(secs) sec"
}

final class Slot {

    /// Bank number to the name the user gave that bank, shared by reference
    /// with the Board that owns this slot. Deliberately not part of the slot's
    /// own saved state: it is the board's, it must never reach toDict, and a
    /// slot built on its own in a test falls back to the shipped names.
    weak var board: Board?

    let index: Int
    var filepath: String?
    var name: String?
    var duration: Double?
    var customHotkey: String?
    /// The Windows key code and modifier mask. Carried through untouched so a
    /// board written here still fires the right key when it is opened on the
    /// Windows copy. This build never interprets them.
    var winKeyCode: Int?
    var winModifiers: Int?
    /// The Mac equivalent, which is what this build actually uses. A separate
    /// pair rather than a reused one, so neither platform can quietly destroy
    /// the other's binding.
    var macKeyCode: Int?
    var macModifiers: UInt?
    /// A system wide hotkey, which fires this slot while another window has
    /// focus. Separate from customHotkey, which only works inside the app.
    var globalHotkey: String?
    var loop: Bool
    /// Per slot trim in decibels, so one loud sound can be tamed on its own.
    var trimDB: Double = 0.0
    /// Taken off the board. The slot keeps everything it had, including its
    /// sound and its hotkeys, and can be put back; it simply is not shown and
    /// its key does nothing. Removing one NEVER renumbers the others, because
    /// the digit map is muscle memory: take slot 5 away and 6 is still on the
    /// 6 key.
    var hidden: Bool = false
    /// Pressing this slot's key again stops it, instead of playing a second
    /// copy on top of the first.
    ///
    /// Off by default, and deliberately. Effects and drops overlapping is the
    /// thing a soundboard is FOR: a laugh landing on top of a sting is the
    /// point, and making every key a toggle would take that away from everyone
    /// to help the one slot that needed it. Beds have always toggled and go on
    /// doing so whatever this says.
    var toggleStop: Bool = false
    /// How many playable sounds are in this slot's folder, when filepath is a
    /// folder rather than a file. Saved so the label is right before the first
    /// scan, which then corrects it. nil for an ordinary slot.
    var folderCount: Int?

    /// Anything in the saved slot this build did not recognise, kept so a round
    /// trip through the Mac copy cannot lose a Windows only field.
    var unknown: [String: Any] = [:]

    // The folder's contents, scanned. Never saved: it is what is on disk right
    // now, and the point of a folder slot is that you can drop another jingle
    // in without touching the app.
    private var folderFiles: [String] = []
    private var folderStamp: Int?
    private var lastPick: String?

    init(index: Int) {
        self.index = index
        self.loop = bankForIndex(index) == C.loopingBank
    }

    // ----------------------------------------------------------- identity ---
    var bank: Int { bankForIndex(index) }
    var number: Int { positionInBank(index) }
    var isBed: Bool { bank == C.loopingBank }

    /// What this slot's bank is called, the user's name for it if any.
    var bankTitle: String {
        board?.bankNames[bank] ?? C.bankTitles[bank] ?? ""
    }

    /// The same, short, for lists that span every bank.
    ///
    /// A renamed bank has no short form and inventing one would be guesswork,
    /// so the name the user typed is used whole. "SFX" is only a contraction of
    /// a name they did not choose.
    var bankShort: String {
        board?.bankNames[bank] ?? C.bankShort[bank] ?? ""
    }

    /// The key that fires this slot, fixed by bank or chosen by the user.
    var hotkeyLabel: String {
        if bank == C.bankMisc { return customHotkey ?? "" }
        return KeyMap.hotkeyLabel(bank: bank, positionInBank: number - 1)
    }

    // ------------------------------------------------------------ content ---
    var isAssigned: Bool { !(filepath ?? "").isEmpty }

    /// This slot holds a folder, and plays a different sound every press.
    ///
    /// A chart countdown has half a dozen "down the chart" jingles and you do
    /// not care which one you get, only that one plays. So the slot points at
    /// the folder and picks for you.
    var isFolder: Bool {
        guard let p = filepath, !p.isEmpty else { return false }
        var isDir: ObjCBool = false
        return FileManager.default.fileExists(atPath: p, isDirectory: &isDir) && isDir.boolValue
    }

    /// Assigned, but the file is not where it used to be.
    var isMissing: Bool {
        guard let p = filepath, !p.isEmpty else { return false }
        return !FileManager.default.fileExists(atPath: p)
    }

    var displayName: String {
        if let n = name, !n.isEmpty { return n }
        if let p = filepath, !p.isEmpty {
            return (p as NSString).lastPathComponent.replacingOccurrences(
                of: "." + (p as NSString).pathExtension, with: "")
        }
        return "Empty"
    }

    private func stateWords(playing: Bool) -> [String] {
        var state: [String] = []
        if isMissing {
            state.append(folderCount != nil ? "folder missing" : "file missing")
        } else if isAssigned {
            if playing { state.append("playing") }
            if loop { state.append("loops") }
            if isFolder {
                // A count, not a length. Every press is a different file, so a
                // duration here would be a different lie each time.
                if let n = folderCount {
                    state.append("folder, " + (n == 0 ? "empty"
                                               : n == 1 ? "1 sound"
                                               : "\(n) sounds"))
                } else {
                    state.append("folder, not counted yet")
                }
            } else {
                let dur = formatDuration(duration)
                if !dur.isEmpty { state.append(dur) }
            }
        }
        return state
    }

    /// What the button says, and therefore what a screen reader reads.
    ///
    /// Name first, because that is what you are hunting for when you arrow
    /// along a row. The bank is not repeated here, the tab already said it.
    func buttonLabel(playing: Bool = false) -> String {
        var parts = ["\(number). \(displayName)"]
        if !hotkeyLabel.isEmpty { parts.append("key \(hotkeyLabel)") }
        if let g = globalHotkey, !g.isEmpty { parts.append("global \(g)") }
        parts.append(contentsOf: stateWords(playing: playing))
        return parts.joined(separator: ", ")
    }

    /// Same idea, but for lists that span every bank, so name the bank.
    func searchLabel(playing: Bool = false) -> String {
        var parts = [displayName, "\(bankShort) \(number)"]
        if !hotkeyLabel.isEmpty { parts.append("key \(hotkeyLabel)") }
        if let g = globalHotkey, !g.isEmpty { parts.append("global \(g)") }
        parts.append(contentsOf: stateWords(playing: playing))
        return parts.joined(separator: ", ")
    }

    // ------------------------------------------------------------ folders ---

    /// Re-read the folder if it has changed. Returns how many sounds it holds.
    ///
    /// Cheap to call often: it compares the folder's own timestamp and does
    /// nothing when nobody has touched it. It is never called between a
    /// keypress and a sound, the trigger path uses whatever the last scan
    /// found, and the cache warmer does the scanning at startup.
    @discardableResult
    func scanFolder(force: Bool = false) -> Int {
        guard isFolder, let path = filepath else {
            folderFiles = []
            return 0
        }
        let fm = FileManager.default
        guard let attrs = try? fm.attributesOfItem(atPath: path),
              let modified = attrs[.modificationDate] as? Date else {
            return folderFiles.count
        }
        let stamp = Int(modified.timeIntervalSince1970 * 1_000_000_000)
        if !force, stamp == folderStamp, !folderFiles.isEmpty {
            return folderFiles.count
        }
        guard let names = try? fm.contentsOfDirectory(atPath: path) else {
            return folderFiles.count
        }
        folderFiles = names.sorted().compactMap { name in
            let full = (path as NSString).appendingPathComponent(name)
            let ext = (name as NSString).pathExtension.lowercased()
            guard AudioFile.supportedExtensions.contains(ext) else { return nil }
            var isDir: ObjCBool = false
            guard fm.fileExists(atPath: full, isDirectory: &isDir), !isDir.boolValue
            else { return nil }
            return full
        }
        folderStamp = stamp
        folderCount = folderFiles.count
        return folderFiles.count
    }

    var folderFileList: [String] { folderFiles }

    /// One file out of the folder, at random, avoiding an instant repeat.
    ///
    /// Two presses in a row giving the same jingle is what makes a random
    /// stinger sound broken rather than random, so the last one is excluded
    /// whenever there is anything else to choose from.
    func pickFile() -> String? {
        guard !folderFiles.isEmpty else { return nil }
        var choices = folderFiles
        if choices.count > 1, let last = lastPick, choices.contains(last) {
            choices = choices.filter { $0 != last }
        }
        lastPick = choices.randomElement()
        return lastPick
    }

    /// What a press should play. A folder picks one; a file is itself.
    func playablePath() -> String? {
        isFolder ? pickFile() : filepath
    }

    /// Empty the slot but keep any custom hotkey the user set up.
    func clear() {
        filepath = nil
        name = nil
        duration = nil
        trimDB = 0.0
        folderCount = nil
        folderFiles = []
        folderStamp = nil
        lastPick = nil
        loop = isBed
    }

    // --------------------------------------------------------- conversion ---
    func toDict() -> [String: Any] {
        var d = unknown
        d["filepath"] = filepath as Any? ?? NSNull()
        d["name"] = name as Any? ?? NSNull()
        d["duration"] = duration as Any? ?? NSNull()
        d["custom_hotkey"] = customHotkey as Any? ?? NSNull()
        d["global_hotkey"] = globalHotkey as Any? ?? NSNull()
        d["key_code"] = winKeyCode as Any? ?? NSNull()
        d["modifiers"] = winModifiers as Any? ?? NSNull()
        d["mac_key_code"] = macKeyCode as Any? ?? NSNull()
        d["mac_modifiers"] = macModifiers as Any? ?? NSNull()
        d["loop"] = loop
        d["trim_db"] = trimDB
        d["folder_count"] = folderCount as Any? ?? NSNull()
        d["hidden"] = hidden
        d["toggle_stop"] = toggleStop
        return d
    }

    static func fromDict(index: Int, data: [String: Any]?) -> Slot {
        let s = Slot(index: index)
        guard let data else { return s }
        let known: Set<String> = ["filepath", "name", "duration", "custom_hotkey",
                                  "global_hotkey", "key_code", "modifiers",
                                  "mac_key_code", "mac_modifiers", "loop",
                                  "trim_db", "folder_count", "hidden", "toggle_stop"]
        s.unknown = data.filter { !known.contains($0.key) }

        s.filepath = data["filepath"] as? String
        s.name = data["name"] as? String
        s.duration = data["duration"] as? Double
        s.customHotkey = data["custom_hotkey"] as? String
        s.globalHotkey = data["global_hotkey"] as? String
        s.winKeyCode = data["key_code"] as? Int
        s.winModifiers = data["modifiers"] as? Int
        s.macKeyCode = data["mac_key_code"] as? Int
        s.macModifiers = data["mac_modifiers"] as? UInt
        s.loop = data["loop"] as? Bool ?? (bankForIndex(index) == C.loopingBank)
        s.trimDB = data["trim_db"] as? Double ?? 0.0
        if let fc = data["folder_count"] as? Int { s.folderCount = max(0, fc) }
        s.hidden = data["hidden"] as? Bool ?? false
        s.toggleStop = data["toggle_stop"] as? Bool ?? false
        return s
    }
}
