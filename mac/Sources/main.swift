// The way in.

import AppKit

// The checks run against the built app, never against the source: a missing
// data file or a dead audio backend only ever shows up in the bundle.
if CommandLine.arguments.contains("--selftest") {
    exit(SelfTest().run())
}

// The one thing the unit checks cannot prove is that a real server accepts what
// this sends. See StreamTest.
if let at = CommandLine.arguments.firstIndex(of: "--streamtest") {
    exit(StreamTest.run(Array(CommandLine.arguments.dropFirst(at + 1))))
}

// Every key the app binds, one per line, for mac/check_guide.py.
if CommandLine.arguments.contains("--dump-keys") {
    for key in KeyMap.dump() { print(key) }
    exit(0)
}

// The release script's rehearsal: verify a staged manifest with the key baked
// into THIS build, before anything is uploaded. Signing with a key the app does
// not carry is the exact failure that produces a silent outage.
if let at = CommandLine.arguments.firstIndex(of: "--verify-manifest"),
   at + 1 < CommandLine.arguments.count {
    let path = CommandLine.arguments[at + 1]
    guard let data = FileManager.default.contents(atPath: path) else {
        print("FAILED: could not read \(path)")
        exit(2)
    }
    let asOld = AppUpdate.evaluate(data, currentVersion: "0.0.0")
    let asCurrent = AppUpdate.evaluate(data, currentVersion: C.appVersion)
    print("  signature verifies with the baked in key : \(asOld.info != nil)")
    print("  a client on 0.0.0 is offered it           : \(asOld.available)  (\(asOld.message))")
    print("  a client on \(C.appVersion) is not              : \(!asCurrent.available)  (\(asCurrent.message))")
    if let info = asOld.info {
        print("  version : \(info.version)")
        print("  url     : \(info.url)")
        print("  sha256  : \(info.sha256)")
    }
    exit(asOld.info != nil && asOld.available && !asCurrent.available ? 0 : 1)
}

// macOS 13 and later quietly retitle a Preferences item to Settings, and read
// this switch once, before the application object exists. Every TG Studios
// app, the Windows copy, the window itself and the manual say Preferences, and
// a menu that says one thing while the manual says another is a trap for
// somebody reading both by ear.
UserDefaults.standard.register(defaults: ["NSMenuShouldUpdateSettingsTitle": false])

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
