// The keyboard map, and how the Windows one was carried across.
//
// The digit map is frozen: 1 to 0, Shift, then a modifier, then that modifier
// with Shift, across four banks of twenty. That SHAPE is the muscle memory and
// it is preserved exactly. What changes on a Mac is which key sits under the
// thumb, and there is one hard reason it has to change.
//
// VoiceOver's own modifier is Control plus Option, the "VO keys". The Windows
// bank three is Alt plus Ctrl plus a digit, which translates literally to
// Control plus Option plus a digit, which is VO plus a digit. Handing the
// looping bank to VoiceOver is not a trade worth making, so the default map
// moves the Windows Ctrl to the Mac Command, which is the translation every
// other program on this machine already makes:
//
//     Windows                     Mac (default)
//     1 to 0                      1 to 0
//     Shift+1 to 0                Shift+1 to 0
//     Ctrl+1 to 0                 Command+1 to 0
//     Ctrl+Shift+1 to 0           Command+Shift+1 to 0
//     Alt+Ctrl+1 to 0             Option+Command+1 to 0
//     Alt+Ctrl+Shift+1 to 0       Option+Command+Shift+1 to 0
//
// Every finger moves the same way; the thumb moves one key left. Anyone who
// would rather have the literal Windows combinations can ask for them in
// Preferences, and is told there what VoiceOver will take.
//
// The command keys follow the same rule, Ctrl becomes Command, and the literal
// Control versions are ALSO accepted wherever the system leaves them free.
// That is the standing TG Studios rule that a key somebody has already learned
// never gets taken away, applied across a platform rather than across a
// release.

import AppKit

/// The one place a modal panel says "these keys are mine".
///
/// The window's key monitor consults this before it does anything else, so a
/// panel that drives itself with bare digits and arrow keys does not have to
/// install a second monitor and hope it is asked first. AppKit does not promise
/// an order between local monitors, and the source control panel's digits, the
/// ones that jump straight to a source mid link, were losing that race to the
/// digit map and firing pads instead.
enum ModalKeys {
    /// Returns true when the panel has dealt with the key. Set on the way in,
    /// cleared on the way out, and never left set.
    static var current: ((NSEvent) -> Bool)?

    /// Claim the keyboard for the length of one modal panel.
    static func claim(_ handler: @escaping (NSEvent) -> Bool, during body: () -> Void) {
        let previous = current
        current = handler
        body()
        current = previous
    }
}

enum BankScheme: String {
    /// Command, the Mac translation of the Windows Ctrl. The default.
    case command
    /// The literal Windows combinations. Bank three then collides with
    /// VoiceOver and the Preferences window says so.
    case literal
}

/// Everything the frame can be asked to do. One case per command, so the menu,
/// the key map and the help text are all built from the same list and cannot
/// drift apart.
enum Command: String, CaseIterable {
    case newBoard, openBoard, saveBoard, saveBoardAs, importBank, loadDemo
    case relink, preferences
    case assign, assignFolder, rename, trim, hotkey, globalHotkey, toggleLoop
    case properties, clearSlot, removeSlot, restoreSlot, restoreAllSlots
    case search, whatsPlaying, ducking, stopLatest, stopAll
    case renameBank, resetBankName, nextBank, previousBank
    case volSFXDown, volSFXUp, volBedDown, volBedUp, volPlaylistDown, volPlaylistUp
    case viewPlaylist, viewBoard, viewNext
    case playlistPaste, playlistAdd, playlistDropRandom, playlistDropFile
    case playlistLibrary, playlistDropEvery, playlistCheckAll, playlistUncheckAll
    case playlistPlayFromHere, playlistGotoPlaying, playlistNext, playlistPrevious
    case playlistStop, playlistCrossfade, playlistSave, playlistOpen, playlistClear
    case micToggle, micSettings
    case streamToggle, streamStatus, streamStats, streamSetup
    case record, recordFolder, sources, sourceControl, muteSources, soloMic
    case shortcuts, userGuide, checkUpdates, feedback, donate, about
    case keyboardCheck, globalHotkeysToggle
}

/// One binding: the characters the key produces with modifiers ignored, and the
/// modifier set that has to be held.
struct Binding {
    let key: String
    let mods: NSEvent.ModifierFlags
    /// Shown in a menu. A binding that is only an alias is not shown, because a
    /// menu that lists two keys for one thing reads as two commands.
    let primary: Bool

    init(_ key: String, _ mods: NSEvent.ModifierFlags = [], primary: Bool = true) {
        self.key = key
        self.mods = mods
        self.primary = primary
    }
}

enum KeyMap {

    /// Which bank scheme is in force. Set from the board on load.
    static var scheme: BankScheme = .command

    // ------------------------------------------------------ bank modifiers ---

    /// The modifier for banks two and three, per scheme. Bank one is bare and
    /// bank four takes the user's own keys, so neither is listed.
    static var bank2Mods: NSEvent.ModifierFlags {
        scheme == .command ? [.command] : [.control]
    }
    static var bank3Mods: NSEvent.ModifierFlags {
        scheme == .command ? [.option, .command] : [.option, .control]
    }

    static var bank2Spoken: String {
        scheme == .command ? "Command plus 1 through 0" : "Control plus 1 through 0"
    }
    static var bank3Spoken: String {
        scheme == .command ? "Option plus Command plus 1 through 0"
                           : "Option plus Control plus 1 through 0"
    }

    /// The label written on a pad and read out by VoiceOver, for one slot.
    /// Bank four is empty here: its keys are the user's own and come off the
    /// slot itself.
    static func hotkeyLabel(bank: Int, positionInBank: Int) -> String {
        // The row is ten digits wide and a bank is twenty, so the modulus is
        // the digit count and not the bank size. Getting that wrong indexes
        // off the end of the digit row for every slot above ten.
        let digits = Array(C.digits)
        guard positionInBank >= 0, positionInBank < C.slotsPerBank else { return "" }
        let digit = String(digits[positionInBank % digits.count])
        let upper = positionInBank >= digits.count
        switch bank {
        case C.bankSFX:
            return upper ? "Shift+\(digit)" : digit
        case C.bankDrops:
            let base = scheme == .command ? "Cmd" : "Ctrl"
            return upper ? "\(base)+Shift+\(digit)" : "\(base)+\(digit)"
        case C.bankBeds:
            let base = scheme == .command ? "Opt+Cmd" : "Opt+Ctrl"
            return upper ? "\(base)+Shift+\(digit)" : "\(base)+\(digit)"
        default:
            return ""
        }
    }

    /// The same thing said out loud. VoiceOver reads "Cmd" as "cmd", so the
    /// spoken form spells the modifiers out.
    static func hotkeySpoken(bank: Int, positionInBank: Int) -> String {
        let label = hotkeyLabel(bank: bank, positionInBank: positionInBank)
        if label.isEmpty { return "" }
        return label
            .replacingOccurrences(of: "Opt+Cmd", with: "Option Command ")
            .replacingOccurrences(of: "Opt+Ctrl", with: "Option Control ")
            .replacingOccurrences(of: "Cmd", with: "Command ")
            .replacingOccurrences(of: "Ctrl", with: "Control ")
            .replacingOccurrences(of: "Shift+", with: "Shift ")
            .replacingOccurrences(of: "+", with: " ")
    }

    /// Which slot, if any, a bare or modified digit fires. Returns the absolute
    /// slot index across the eighty, or nil.
    ///
    /// Bank one is bare digits, so this is only ever consulted from the board
    /// view's own keyDown, well after a focused text field has had its chance.
    static func slotFor(characters: String, mods: NSEvent.ModifierFlags) -> Int? {
        let clean = mods.intersection([.command, .option, .control, .shift])
        guard let position = Array(C.digits).firstIndex(of: Character(characters.lowercased()))
        else { return nil }

        let shifted = clean.contains(.shift)
        let base = clean.subtracting(.shift)
        let offset = shifted ? 10 : 0

        var bank: Int
        if base.isEmpty {
            bank = C.bankSFX
        } else if base == bank2Mods.subtracting(.shift) {
            bank = C.bankDrops
        } else if base == bank3Mods.subtracting(.shift) {
            bank = C.bankBeds
        } else if base == [.control] && scheme == .command {
            // The literal Windows binding, kept as an alias. Costs nothing and
            // the fingers of anybody arriving from the Windows copy already
            // know it.
            bank = C.bankDrops
        } else if base == [.option, .control] && scheme == .command {
            // Likewise, and VoiceOver will usually take it first. Harmless
            // either way.
            bank = C.bankBeds
        } else {
            return nil
        }
        return (bank - 1) * C.slotsPerBank + position + offset
    }

    /// A digit typed with Shift produces a symbol rather than a digit, so
    /// charactersIgnoringModifiers is what has to be matched. On a US layout
    /// Shift+1 is "!". This maps them back.
    static func digitFor(event: NSEvent) -> String? {
        if let c = event.charactersIgnoringModifiers, C.digits.contains(c) { return c }
        // keyCode is layout dependent but the number row is stable across the
        // layouts this app has been asked about, and it is the fallback rather
        // than the first answer.
        let byCode: [UInt16: String] = [
            18: "1", 19: "2", 20: "3", 21: "4", 23: "5",
            22: "6", 26: "7", 28: "8", 25: "9", 29: "0",
        ]
        return byCode[event.keyCode]
    }

    // ---------------------------------------------------------- commands ---

    /// Every command's keys. The first entry of each is what the menu shows.
    ///
    /// Where a Windows key had to move, the reason is with it. Where it did
    /// not have to move, it did not move.
    static let bindings: [Command: [Binding]] = [
        // File
        .newBoard:      [Binding("n", [.command])],
        .openBoard:     [Binding("o", [.command])],
        .saveBoard:     [Binding("s", [.command])],
        .saveBoardAs:   [Binding("s", [.command, .shift])],
        .preferences:   [Binding(",", [.command]),          // the Mac idiom
                         Binding("p", [.command], primary: false)],  // and the Windows one

        // Sounds
        .rename:        [Binding(String(UnicodeScalar(NSF2FunctionKey)!))],
        .properties:    [Binding("i", [.command]),          // Get Info, the Mac idiom
                         Binding("\r", [.option], primary: false)],  // the TG Studios convention
        .search:        [Binding("f", [.command]),
                         Binding("e", [.command], primary: false)],  // Ctrl+E was search for two releases
        .whatsPlaying:  [Binding("l", [.command])],
        .ducking:       [Binding("d", [.command])],
        // Cmd+Space is Spotlight and cannot be taken. Option+Space is free, is
        // next to the thumb the Windows key used, and nothing on the frozen map
        // moved for it.
        .stopLatest:    [Binding(" ", [.option])],
        .clearSlot:     [Binding(String(UnicodeScalar(NSDeleteFunctionKey)!)),
                         Binding("\u{8}", primary: false)],  // Backspace, which is what a Mac keyboard calls Delete
        .removeSlot:    [Binding(String(UnicodeScalar(NSDeleteFunctionKey)!), [.shift]),
                         Binding("\u{8}", [.shift], primary: false)],

        // Banks
        .renameBank:    [Binding(String(UnicodeScalar(NSF2FunctionKey)!), [.command])],
        .nextBank:      [Binding("\t", [.control]),
                         Binding("]", [.command, .shift], primary: false)],
        .previousBank:  [Binding("\t", [.control, .shift]),
                         Binding("[", [.command, .shift], primary: false)],

        // The three faders. Tony's Mac already has "Use F1, F2, etc. as
        // standard function keys" switched on, which is what makes these
        // arrive at all. The app checks that at launch and says so once if it
        // is off, because a fader key that does nothing looks like a fault.
        .volSFXDown:      [Binding(String(UnicodeScalar(NSF3FunctionKey)!))],
        .volSFXUp:        [Binding(String(UnicodeScalar(NSF4FunctionKey)!))],
        .volBedDown:      [Binding(String(UnicodeScalar(NSF5FunctionKey)!))],
        .volBedUp:        [Binding(String(UnicodeScalar(NSF6FunctionKey)!))],
        .volPlaylistDown: [Binding(String(UnicodeScalar(NSF7FunctionKey)!))],
        .volPlaylistUp:   [Binding(String(UnicodeScalar(NSF8FunctionKey)!))],

        // The two views
        .viewPlaylist:  [Binding("p", [.command, .shift])],
        .viewBoard:     [Binding("s", [.command, .shift, .option])],
        .viewNext:      [Binding("\t", [.command, .option])],

        // Playlist
        .playlistPaste:       [Binding("v", [.command])],
        .playlistDropRandom:  [Binding("d", [.option])],
        .playlistDropFile:    [Binding("d", [.command, .shift])],
        .playlistPlayFromHere:[Binding("\r", [.command, .shift])],
        .playlistGotoPlaying: [Binding("l", [.command, .shift])],

        // On air
        .micToggle:     [Binding("m", [.command])],
        .micSettings:   [Binding("m", [.command, .shift])],
        .streamToggle:  [Binding("b", [.command])],
        .streamStatus:  [Binding("b", [.command, .shift])],
        .streamStats:   [Binding("a", [.command, .shift])],
        .record:        [Binding("r", [.command])],
        // The three source keys are one family: Option Command and then C, M or
        // S for control, mute and solo.
        //
        // Source control used to be Option Command Shift S, the literal Windows
        // key, and that is also what "Go to the soundboard" had to become when
        // Command Shift S went to Save board as. Two menu items with one key is
        // not a clash AppKit reports: the first one in the menu bar simply wins
        // and the other is unreachable for ever. The Playlist menu comes first,
        // so from 3.2.2 until now that key went to the soundboard and source
        // control could only be opened with the mouse. The soundboard keeps the
        // key it has been answering to; source control gets one of its own, and
        // the Windows combination stays on as an alias where the system leaves
        // it free. `SelfTest` now refuses a build with two commands on one key.
        .sources:       [Binding("s", [.option, .shift])],
        .sourceControl: [Binding("c", [.option, .command]),
                         Binding("s", [.option, .control, .shift], primary: false)],
        .muteSources:   [Binding("m", [.option, .command])],
        .soloMic:       [Binding("s", [.option, .command])],
        // Command G arms and disarms the global hotkeys. A new key on Windows
        // too, taken off nothing.
        .globalHotkeysToggle: [Binding("g", [.command])],

        // Help
        .shortcuts:     [Binding(String(UnicodeScalar(NSF1FunctionKey)!))],
    ]

    /// The literal Windows Control combinations, accepted as aliases wherever
    /// the system leaves them free. Checked only after the menus and the first
    /// responder have had their turn, so nothing here can shadow a real key.
    ///
    /// Control+Space is deliberately absent: macOS gives it to the input source
    /// switcher, and a key that works on one machine and not the next is worse
    /// than a key that is documented as moved.
    static let windowsAliases: [String: Command] = [
        "f": .search, "e": .search, "l": .whatsPlaying, "d": .ducking,
        "b": .streamToggle, "r": .record, "g": .globalHotkeysToggle, "m": .micToggle,
    ]

    /// The characters a binding is written with, for one real event.
    ///
    /// Not just `charactersIgnoringModifiers`: a Mac's Delete key does not
    /// produce `NSDeleteFunctionKey`, and Shift IS applied to that property, so
    /// Command Shift `]` arrives as `}`. Those keys are taken off the key code
    /// for the same reason `digitFor` does it, and with the same caveat: the
    /// number row and these few punctuation keys are stable across the layouts
    /// this app has been asked about.
    static func eventKey(_ event: NSEvent) -> String? {
        let byCode: [UInt16: String] = [
            51: "\u{8}",                                          // Delete
            117: String(UnicodeScalar(NSDeleteFunctionKey)!),     // forward Delete
            36: "\r", 76: "\r", 48: "\t", 49: " ",
            33: "[", 30: "]", 43: ",",
        ]
        if let named = byCode[event.keyCode] { return named }
        if let digit = digitFor(event: event) { return digit }
        guard let chars = event.charactersIgnoringModifiers?.lowercased(),
              !chars.isEmpty else { return nil }
        return chars
    }

    /// One key and its modifiers, as a string nothing else can collide with.
    ///
    /// NOT `spell`, which is written for a person and calls both the forward
    /// delete and the Backspace a Mac keyboard's Delete key sends "Delete".
    /// Those are two different keys and a check that cannot tell them apart
    /// would report a clash that is not there and miss one that is.
    static func identity(key: String, mods: NSEvent.ModifierFlags) -> String {
        let scalars = key.lowercased().unicodeScalars.map { String($0.value) }.joined(separator: ".")
        return "\(mods.rawValue & 0x00FF_0000):\(scalars)"
    }

    /// Every key a menu item really carries. Anything in here belongs to AppKit
    /// and must never be claimed by the alias dispatcher below.
    static let primaryKeys: Set<String> = {
        var out = Set<String>()
        for (_, list) in bindings {
            for b in list where b.primary { out.insert(identity(key: b.key, mods: b.mods)) }
        }
        return out
    }()

    /// The command an ALIAS binding names, for a key the menus do not carry.
    ///
    /// Every binding after the first is an alias: the Windows key kept alive,
    /// or the second Mac idiom for the same thing. A menu item can only show
    /// one key equivalent, so until 3.3.0 every one of those aliases was
    /// declared here and dispatched nowhere. Command E did not search, Option
    /// Return did not open properties, Command P did not open Preferences, and
    /// Delete on a laptop keyboard, which sends Backspace and not the forward
    /// delete the menu carries, did not clear a slot.
    ///
    /// A key that is some other command's real menu key is never claimed here,
    /// so an alias can never shadow the map.
    static func aliasCommand(for event: NSEvent) -> Command? {
        guard let key = eventKey(event) else { return nil }
        let mods = event.modifierFlags.intersection([.command, .option, .control, .shift])
        guard !primaryKeys.contains(identity(key: key, mods: mods)) else { return nil }
        for (command, list) in bindings {
            for b in list where !b.primary && b.mods == mods && b.key.lowercased() == key {
                return command
            }
        }
        return nil
    }

    /// Does this event match any binding for the command?
    static func matches(_ event: NSEvent, _ command: Command) -> Bool {
        guard let list = bindings[command] else { return false }
        let mods = event.modifierFlags.intersection([.command, .option, .control, .shift])
        let chars = (event.charactersIgnoringModifiers ?? "").lowercased()
        for b in list where b.mods == mods && b.key.lowercased() == chars {
            return true
        }
        return false
    }

    /// The menu's key equivalent for a command, or nil when it has none or is
    /// handled somewhere a menu cannot reach.
    static func menuKey(_ command: Command) -> (String, NSEvent.ModifierFlags)? {
        guard let b = bindings[command]?.first(where: { $0.primary }) else { return nil }
        return (b.key, b.mods)
    }

    // ------------------------------------------------------------ the dump ---

    /// A key written the way the manual writes it: modifiers in the Mac order,
    /// joined with plus signs, then the key by its name.
    static func spell(key: String, mods: NSEvent.ModifierFlags) -> String {
        var parts: [String] = []
        if mods.contains(.control) { parts.append("Control") }
        if mods.contains(.option) { parts.append("Option") }
        if mods.contains(.shift) { parts.append("Shift") }
        if mods.contains(.command) { parts.append("Command") }
        let names: [String: String] = [
            "\r": "Return", " ": "Space", "\t": "Tab", ",": "comma", "\u{8}": "Delete",
            String(UnicodeScalar(NSDeleteFunctionKey)!): "Delete",
            String(UnicodeScalar(NSUpArrowFunctionKey)!): "Up",
            String(UnicodeScalar(NSDownArrowFunctionKey)!): "Down",
            String(UnicodeScalar(NSHomeFunctionKey)!): "Home",
            String(UnicodeScalar(NSEndFunctionKey)!): "End",
            "\u{1B}": "Escape",
        ]
        var name = names[key]
        if name == nil {
            for n in 1...20 where key == String(UnicodeScalar(NSF1FunctionKey + n - 1)!) { name = "F\(n)" }
        }
        parts.append(name ?? key.uppercased())
        return parts.joined(separator: "+")
    }

    /// Every key the app binds, for mac/check_guide.py. Derived, not typed:
    /// the command bindings, every alias included, the digit map for the
    /// scheme in force, and the keys the running order and the pads handle
    /// themselves, which are listed here because they are real keys too.
    static func dump() -> [String] {
        var keys = Set<String>()
        for (_, list) in bindings {
            for b in list { keys.insert(spell(key: b.key, mods: b.mods)) }
        }
        for (letter, _) in windowsAliases { keys.insert(spell(key: letter, mods: [.control])) }
        for d in C.digits {
            let digit = String(d)
            keys.insert(spell(key: digit, mods: []))
            keys.insert(spell(key: digit, mods: [.shift]))
            keys.insert(spell(key: digit, mods: bank2Mods))
            keys.insert(spell(key: digit, mods: bank2Mods.union(.shift)))
            keys.insert(spell(key: digit, mods: bank3Mods))
            keys.insert(spell(key: digit, mods: bank3Mods.union(.shift)))
            keys.insert(spell(key: digit, mods: [.control]))
            keys.insert(spell(key: digit, mods: [.option, .control]))
        }
        // Handled by the views rather than the map. See PlaylistTable.keyDown,
        // SoundButton and AppDelegate.installKeyMonitor.
        for fixed in ["Space", "Return", "Shift+Return", "Delete", "Escape",
                      "Option+Up", "Option+Down", "Option+Home", "Option+End",
                      "Shift+A", "Shift+U", "Command+Q"] {
            keys.insert(fixed)
        }
        return keys.sorted()
    }
}
