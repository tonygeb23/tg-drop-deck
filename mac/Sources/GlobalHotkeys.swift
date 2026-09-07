// Keys that fire a pad while another program has focus.
//
// The Windows copy uses RegisterHotKey on a dedicated listener thread with its
// own message loop, which is where its worst bug lived: a wx.CallAfter with no
// wx.App killed that thread before it reached the loop, leaving every
// combination registered with Windows, firing nothing, and unavailable to every
// other program until the process died.
//
// macOS has RegisterEventHotKey, which needs no thread of its own because
// NSApplication already pumps the Carbon event loop, and needs no permission at
// all: not Accessibility, not Input Monitoring. It is old and it is not
// deprecated. Unregistering still happens on the way out, because registration
// is exclusive and a combination left registered is taken from everybody.
//
// One rule carried over unchanged: A GLOBAL HOTKEY ALWAYS NEEDS A MODIFIER.
// Registering a bare key takes it away from every other program on the machine,
// including whatever the user is typing into.

import AppKit
import Carbon.HIToolbox

struct HotkeyCombination: Equatable {
    var keyCode: UInt32
    /// Carbon modifier mask: cmdKey, shiftKey, optionKey, controlKey.
    var modifiers: UInt32

    var isBare: Bool { modifiers == 0 }

    /// What it is called, in the app's own words, and what parse reads back.
    var label: String {
        var parts: [String] = []
        if modifiers & UInt32(controlKey) != 0 { parts.append("Ctrl") }
        if modifiers & UInt32(optionKey) != 0 { parts.append("Opt") }
        if modifiers & UInt32(cmdKey) != 0 { parts.append("Cmd") }
        if modifiers & UInt32(shiftKey) != 0 { parts.append("Shift") }
        parts.append(HotkeyCombination.name(for: keyCode))
        return parts.joined(separator: "+")
    }

    var spoken: String {
        label.replacingOccurrences(of: "Ctrl", with: "Control")
             .replacingOccurrences(of: "Opt", with: "Option")
             .replacingOccurrences(of: "Cmd", with: "Command")
             .replacingOccurrences(of: "+", with: " ")
    }

    static let namedKeys: [(String, UInt32)] = [
        ("Space", UInt32(kVK_Space)), ("Return", UInt32(kVK_Return)),
        ("Tab", UInt32(kVK_Tab)), ("Delete", UInt32(kVK_Delete)),
        ("ForwardDelete", UInt32(kVK_ForwardDelete)),
        ("Home", UInt32(kVK_Home)), ("End", UInt32(kVK_End)),
        ("PageUp", UInt32(kVK_PageUp)), ("PageDown", UInt32(kVK_PageDown)),
        ("Left", UInt32(kVK_LeftArrow)), ("Right", UInt32(kVK_RightArrow)),
        ("Up", UInt32(kVK_UpArrow)), ("Down", UInt32(kVK_DownArrow)),
        ("Escape", UInt32(kVK_Escape)),
        ("F1", UInt32(kVK_F1)), ("F2", UInt32(kVK_F2)), ("F3", UInt32(kVK_F3)),
        ("F4", UInt32(kVK_F4)), ("F5", UInt32(kVK_F5)), ("F6", UInt32(kVK_F6)),
        ("F7", UInt32(kVK_F7)), ("F8", UInt32(kVK_F8)), ("F9", UInt32(kVK_F9)),
        ("F10", UInt32(kVK_F10)), ("F11", UInt32(kVK_F11)), ("F12", UInt32(kVK_F12)),
        ("F13", UInt32(kVK_F13)), ("F14", UInt32(kVK_F14)), ("F15", UInt32(kVK_F15)),
        ("1", UInt32(kVK_ANSI_1)), ("2", UInt32(kVK_ANSI_2)), ("3", UInt32(kVK_ANSI_3)),
        ("4", UInt32(kVK_ANSI_4)), ("5", UInt32(kVK_ANSI_5)), ("6", UInt32(kVK_ANSI_6)),
        ("7", UInt32(kVK_ANSI_7)), ("8", UInt32(kVK_ANSI_8)), ("9", UInt32(kVK_ANSI_9)),
        ("0", UInt32(kVK_ANSI_0)),
        ("A", UInt32(kVK_ANSI_A)), ("B", UInt32(kVK_ANSI_B)), ("C", UInt32(kVK_ANSI_C)),
        ("D", UInt32(kVK_ANSI_D)), ("E", UInt32(kVK_ANSI_E)), ("F", UInt32(kVK_ANSI_F)),
        ("G", UInt32(kVK_ANSI_G)), ("H", UInt32(kVK_ANSI_H)), ("I", UInt32(kVK_ANSI_I)),
        ("J", UInt32(kVK_ANSI_J)), ("K", UInt32(kVK_ANSI_K)), ("L", UInt32(kVK_ANSI_L)),
        ("M", UInt32(kVK_ANSI_M)), ("N", UInt32(kVK_ANSI_N)), ("O", UInt32(kVK_ANSI_O)),
        ("P", UInt32(kVK_ANSI_P)), ("Q", UInt32(kVK_ANSI_Q)), ("R", UInt32(kVK_ANSI_R)),
        ("S", UInt32(kVK_ANSI_S)), ("T", UInt32(kVK_ANSI_T)), ("U", UInt32(kVK_ANSI_U)),
        ("V", UInt32(kVK_ANSI_V)), ("W", UInt32(kVK_ANSI_W)), ("X", UInt32(kVK_ANSI_X)),
        ("Y", UInt32(kVK_ANSI_Y)), ("Z", UInt32(kVK_ANSI_Z)),
    ]

    static func name(for code: UInt32) -> String {
        namedKeys.first { $0.1 == code }?.0 ?? "key \(code)"
    }

    /// Read a saved label back. Returns nil for anything that is not a hotkey
    /// this can register, INCLUDING a bare key.
    static func parse(_ text: String) -> HotkeyCombination? {
        let parts = text.split(separator: "+").map {
            $0.trimmingCharacters(in: .whitespaces)
        }
        guard !parts.isEmpty else { return nil }
        var modifiers: UInt32 = 0
        var keyName: String?
        for part in parts {
            switch part.lowercased() {
            case "ctrl", "control": modifiers |= UInt32(controlKey)
            case "opt", "option", "alt": modifiers |= UInt32(optionKey)
            case "cmd", "command", "win", "windows": modifiers |= UInt32(cmdKey)
            case "shift": modifiers |= UInt32(shiftKey)
            default: keyName = part
            }
        }
        guard let keyName,
              let code = namedKeys.first(where: {
                  $0.0.lowercased() == keyName.lowercased()
              })?.1 else { return nil }
        // A bare key would be taken from every other program on the machine.
        guard modifiers != 0 else { return nil }
        return HotkeyCombination(keyCode: code, modifiers: modifiers)
    }

    /// Build one from a key event, for the capture dialog.
    static func from(event: NSEvent) -> HotkeyCombination? {
        var modifiers: UInt32 = 0
        let flags = event.modifierFlags
        if flags.contains(.control) { modifiers |= UInt32(controlKey) }
        if flags.contains(.option) { modifiers |= UInt32(optionKey) }
        if flags.contains(.command) { modifiers |= UInt32(cmdKey) }
        if flags.contains(.shift) { modifiers |= UInt32(shiftKey) }
        let code = UInt32(event.keyCode)
        guard namedKeys.contains(where: { $0.1 == code }) else { return nil }
        return HotkeyCombination(keyCode: code, modifiers: modifiers)
    }
}

final class GlobalHotkeys {

    /// Fired on the main thread with the slot index.
    var onFire: ((Int) -> Void)?
    private(set) var enabled = false
    /// Combinations another program already owns, so the user can be told
    /// which ones rather than that "some" failed.
    private(set) var refused: [String] = []

    private var registered: [EventHotKeyRef] = []
    private var slotsByID: [UInt32: Int] = [:]
    private var handler: EventHandlerRef?
    private var nextID: UInt32 = 1

    private static let signature: OSType = 0x54474444   // "TGDD"

    init() { installHandler() }
    deinit { unregisterAll(); removeHandler() }

    private func installHandler() {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                 eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, context in
            guard let event, let context else { return noErr }
            var id = EventHotKeyID()
            let status = GetEventParameter(event, EventParamName(kEventParamDirectObject),
                                           EventParamType(typeEventHotKeyID), nil,
                                           MemoryLayout<EventHotKeyID>.size, nil, &id)
            guard status == noErr else { return noErr }
            let keys = Unmanaged<GlobalHotkeys>.fromOpaque(context).takeUnretainedValue()
            keys.fired(id.id)
            return noErr
        }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), &handler)
    }

    private func removeHandler() {
        if let handler { RemoveEventHandler(handler) }
        handler = nil
    }

    private func fired(_ id: UInt32) {
        guard let slot = slotsByID[id] else { return }
        // Already on the main thread: NSApplication pumps the Carbon loop.
        onFire?(slot)
    }

    /// Register every slot that has a global hotkey. Returns the labels that
    /// could not be taken.
    @discardableResult
    func register(_ board: Board) -> [String] {
        unregisterAll()
        refused = []
        for slot in board.slots {
            guard let text = slot.globalHotkey, !text.isEmpty,
                  let combination = HotkeyCombination.parse(text) else { continue }
            let id = EventHotKeyID(signature: GlobalHotkeys.signature, id: nextID)
            var ref: EventHotKeyRef?
            let status = RegisterEventHotKey(combination.keyCode, combination.modifiers,
                                             id, GetEventDispatcherTarget(), 0, &ref)
            if status == noErr, let ref {
                registered.append(ref)
                slotsByID[nextID] = slot.index
                nextID += 1
            } else {
                // eventHotKeyExistsErr, almost always: another program has it.
                refused.append(combination.label)
            }
        }
        enabled = true
        return refused
    }

    func unregisterAll() {
        for ref in registered { UnregisterEventHotKey(ref) }
        registered = []
        slotsByID = [:]
        enabled = false
    }

    /// How many are live right now.
    var count: Int { registered.count }
}
