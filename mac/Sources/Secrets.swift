// Where a stream key is kept, which is not the board file.
//
// Mirrors dropdeck/secrets.py. The reasoning is the same on both platforms and
// only the store differs: Windows uses Credential Manager, a Mac uses the
// keychain.
//
// `stream_password` has always been a station field, so it went into
// `board.json` along with the eighty pads. That was already the wrong place
// for an Icecast source password. **It is a much worse place for a YouTube or
// Facebook stream key**, for a reason that is easy to miss: anybody holding
// that key can broadcast to the channel it belongs to. A board file is plain
// JSON, a user can write one anywhere, and boards get sent to people. There is
// nothing about a file full of sound names that suggests a broadcast
// credential is in it.
//
// So keys live in the **login keychain**, under one account per station, and
// the board file keeps only the station's name. It is the same store every
// other Mac program uses, so a user can open Keychain Access and see and
// remove what this app has kept without taking its word for it.
//
// **Nothing here is allowed to throw.** A machine with a locked keychain must
// fall back rather than stop a show. `store` returns whether it worked and the
// caller decides what to do about it, which for the moment means keeping the
// key in the board file the way it always was and saying so.
//
// ## Why nothing prompts, and what would change that
//
// The app is Developer ID signed and is NOT sandboxed, and an item this app
// created and owns is readable by this app without a dialog: the keychain
// grants access to the application that made the item. Two things would break
// that and both are worth knowing before somebody changes them. Re-signing
// with a different identity makes the app a different program as far as the
// keychain is concerned, so the first read after that WILL prompt. And an item
// written by a build signed with one identity and read by a build signed with
// another is the same situation. That is a reason to keep the signing identity
// stable, not a reason to keep keys somewhere worse.

import Foundation
import Security

enum Secrets {

    /// One account per station, so removing a station removes its key and a
    /// user reading Keychain Access can tell what each entry is for.
    static let targetPrefix = "TG Drop Deck stream key: "

    /// The other kind of secret this app keeps. A vision key is not a stream
    /// key and must not be filed as one: the whole point of using the system
    /// store is that somebody can open Keychain Access and see what is there
    /// without taking this app's word for it, and a label that lies defeats
    /// that. It is also billable, which a stream key is not.
    static let visionPrefix = "TG Drop Deck vision key: "

    /// What one station's entry is called. The same string Windows uses for
    /// its target name, so a person who runs both copies sees the same label
    /// in two different credential stores.
    static func target(for station: String, prefix: String = targetPrefix) -> String {
        prefix + (station.isEmpty ? "the current station" : station)
    }

    /// Whether keys can be kept out of the board file on this machine.
    ///
    /// True on any Mac: the keychain is not optional the way a locked down
    /// Windows credential store can be. It is still asked, because the callers
    /// are shared with the Windows shape and a machine that has somehow lost
    /// its keychain should degrade rather than crash.
    static func available() -> Bool {
        // A round trip on a name nothing else uses. Cheap, and it proves the
        // daemon answers rather than assuming it.
        let probe = "TG Drop Deck keychain check"
        var query = base(account: probe)
        query[kSecValueData as String] = Data("ok".utf8)
        SecItemDelete(base(account: probe) as CFDictionary)
        let wrote = SecItemAdd(query as CFDictionary, nil)
        if wrote == errSecSuccess {
            SecItemDelete(base(account: probe) as CFDictionary)
            return true
        }
        return wrote == errSecDuplicateItem
    }

    /// Keep a key. True when it really went into the keychain.
    @discardableResult
    static func store(station: String, key: String,
                      prefix: String = targetPrefix) -> Bool {
        if key.isEmpty { return forget(station: station, prefix: prefix) }
        let account = target(for: station, prefix: prefix)
        let data = Data(key.utf8)
        // Update first, because adding over an existing item fails rather than
        // replacing it, and a user changing a key is the commonest case.
        let updated = SecItemUpdate(
            base(account: account) as CFDictionary,
            [kSecValueData as String: data] as CFDictionary)
        if updated == errSecSuccess { return true }
        var item = base(account: account)
        item[kSecValueData as String] = data
        item[kSecAttrLabel as String] = account
        item[kSecAttrComment as String] = "A live stream key. Safe to delete."
        // Kept for this user on this machine, and NOT synchronised to their
        // other devices or to iCloud. A broadcast key following somebody onto
        // a shared machine is not a kindness, which is the same reason the
        // Windows copy asks for local persistence rather than roaming.
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlocked
        return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
    }

    /// The key for one station, or an empty string. Never throws.
    static func fetch(station: String, prefix: String = targetPrefix) -> String {
        var query = base(account: target(for: station, prefix: prefix))
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return "" }
        return String(decoding: data, as: UTF8.self)
    }

    /// Remove a station's key. True when there is no longer one there.
    @discardableResult
    static func forget(station: String, prefix: String = targetPrefix) -> Bool {
        SecItemDelete(base(account: target(for: station, prefix: prefix)) as CFDictionary)
        // Deleting something that was never there is a success, not a failure:
        // what was asked for was that no key is kept, and none is.
        return fetch(station: station, prefix: prefix).isEmpty
    }

    /// A key as it may be shown or logged: enough to recognise, not to use.
    ///
    /// Never put a whole key on screen, in a status bar or in a spoken line. A
    /// presenter checking they pasted the right one needs the last few
    /// characters and nothing else.
    static func redact(_ key: String) -> String {
        let key = key.trimmingCharacters(in: .whitespacesAndNewlines)
        if key.isEmpty { return "not set" }
        if key.count <= 4 { return "set" }
        return "set, ending \(key.suffix(4))"
    }

    // ------------------------------------------------------------ the item ---

    /// A generic password under this app's own service name. One service, one
    /// account per secret, which is the shape Keychain Access displays most
    /// clearly.
    private static func base(account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: C.appName,
            kSecAttrAccount as String: account,
        ]
    }
}
