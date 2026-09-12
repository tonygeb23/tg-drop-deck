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

// Are the extra sources really on the air, or only configured to be? A source
// delivering silence sounds exactly like one that works, from where the
// presenter is sitting.
if CommandLine.arguments.contains("--check-sources") {
    exit(SourceCheck.run(seconds: {
        if let at = CommandLine.arguments.firstIndex(of: "--check-sources"),
           at + 1 < CommandLine.arguments.count,
           let n = Double(CommandLine.arguments[at + 1]) { return n }
        return 2.0
    }()))
}

// Which way of asking for a process tap works on this machine. Diagnostic.
if let at = CommandLine.arguments.firstIndex(of: "--tap-probe"),
   at + 1 < CommandLine.arguments.count {
    let seconds = at + 2 < CommandLine.arguments.count
        ? (Double(CommandLine.arguments[at + 2]) ?? 6) : 6
    exit(TapProbe.run(CommandLine.arguments[at + 1], seconds: seconds))
}

// Every key the app binds, one per line, for mac/check_guide.py.
if CommandLine.arguments.contains("--dump-keys") {
    for key in KeyMap.dump() { print(key) }
    exit(0)
}

// A real send into a real cable, recorded off the other end and counted for
// gaps. The one thing about a send that cannot be proved from inside the app.
if let at = CommandLine.arguments.firstIndex(of: "--check-send") {
    let rest = CommandLine.arguments.dropFirst(at + 1)
    let seconds = rest.first.flatMap(Double.init) ?? 6.0
    let uid = rest.first(where: { Double($0) == nil })
    exit(SendCheck.run(seconds: seconds, deviceUID: uid))
}

// The F1 list exactly as the app would show it, so the half of it that is
// derived can be read rather than taken on trust.
if CommandLine.arguments.contains("--dump-help") {
    print(KeyboardHelp.chapters() + KeyboardHelp.everythingElse(nil))
    exit(0)
}

// Ask the live server, the way the daily check does, and say what came back.
// This is how a release is proved end to end: the installed app itself reads
// the feed, verifies the signature and compares versions.
if CommandLine.arguments.contains("--check-updates") {
    let result = AppUpdate.check()
    print("manifest  : \(AppUpdate.manifestURL)")
    print("verified  : \(result.info != nil)")
    print("available : \(result.available)")
    print("message   : \(result.message)")
    if let info = result.info {
        print("feed says : \(info.version)  \(info.url)")
    }
    exit(result.info != nil ? 0 : 1)
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
