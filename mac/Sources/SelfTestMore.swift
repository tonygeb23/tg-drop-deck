// The checks for what arrived after the air side: running orders, the drops
// library, stations, importing, feedback and the update channel.
//
// Same rules as SelfTest.swift. Nothing here touches the network: the update
// checks sign a manifest with a key made on the spot and prove the verifier
// against it, and the one thing that cannot be made up, the exact bytes Python
// signs, is held as a sample of Python's own output.

import Foundation
import CryptoKit

extension SelfTest {

    func runMoreChecks() {
        testRunningOrders()
        testDropLibrary()
        testStationsAndImport()
        testFeedback()
        testUpdates()
    }

    private func scratchFolder(_ name: String) -> String {
        let path = NSTemporaryDirectory() + "dropdeck-selftest/" + name
        try? FileManager.default.removeItem(atPath: path)
        try? FileManager.default.createDirectory(atPath: path, withIntermediateDirectories: true)
        return path
    }

    @discardableResult
    private func touchFile(_ path: String, _ contents: String = "") -> String {
        try? FileManager.default.createDirectory(atPath: (path as NSString).deletingLastPathComponent,
                                                 withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: path, contents: contents.data(using: .utf8))
        return path
    }

    // ------------------------------------------------------- running orders ---

    private func testRunningOrders() {
        out.append("Running orders on disk, as M3U")
        let scratch = scratchFolder("m3u")
        let one = touchFile(scratch + "/Music/one.mp3")
        let two = touchFile(scratch + "/Music/two.mp3")
        let ident = touchFile(scratch + "/Drops/ident.wav")

        let pl = Playlist()
        pl.crossfade = 2.5
        let a = Track(filepath: one)
        a.duration = 200
        a.artist = "Motorhead"
        a.title = "Ace of Spades"
        let d = Track(filepath: ident)
        d.kind = C.trackDrop
        d.enabled = false
        d.crossfade = 1.5
        d.duration = 4
        let b = Track(filepath: two)
        b.duration = 181.4
        pl.tracks = [a, d, b]

        let text = M3U.dumps(pl, folder: scratch + "/Music")
        let lines = text.split(separator: "\n").map(String.init)
        check("the file starts with the extended header", lines.first == "#EXTM3U")
        check("the playlist crossfade goes on the first Drop Deck line",
              lines.contains("#DROPDECK:crossfade=2.5"), text)
        check("artist and title go on the EXTINF line",
              lines.contains("#EXTINF:200,Motorhead - Ace of Spades"), text)
        check("a length is rounded to whole seconds",
              lines.contains("#EXTINF:181,two"), text)
        check("a path under the playlist's folder is written relative",
              lines.contains("one.mp3"), text)
        check("a path outside it is written in full",
              lines.contains(ident), text)
        check("what M3U cannot say goes on a Drop Deck line",
              lines.contains("#DROPDECK:kind=drop enabled=0 crossfade=1.5"), text)

        let saved = scratch + "/show.m3u"
        do {
            let n = try M3U.save(saved, playlist: pl)
            check("save reports how many went in", n == 3)
        } catch {
            check("save does not throw", false, error.localizedDescription)
        }
        if let raw = FileManager.default.contents(atPath: saved) {
            check("it is written with CRLF line ends, like the Windows copy",
                  raw.range(of: Data("\r\n".utf8)) != nil)
            check("and without a byte order mark", raw.first == UInt8(ascii: "#"))
        }
        if let loaded = try? M3U.load(saved) {
            check("it reads back with every item", loaded.entries.count == 3,
                  "\(loaded.entries.count)")
            check("and the playlist crossfade", loaded.crossfade == 2.5)
            check("a relative path resolves against the file's own folder",
                  loaded.entries.first?.filepath == one, loaded.entries.first?.filepath ?? "nil")
            check("the artist and title survive", loaded.entries.first?.artist == "Motorhead"
                  && loaded.entries.first?.title == "Ace of Spades")
            check("the length survives", loaded.entries.first?.duration == 200)
            let drop = loaded.entries[1]
            check("a drop is still a drop", drop.kind == "drop")
            check("an unticked item is still unticked", drop.enabled == false)
            check("a crossfade of its own survives", drop.crossfade == 1.5)

            let again = Playlist()
            let added = again.addEntries(loaded.entries)
            check("a running order round trips into tracks", added.count == 3)
            check("with the drop's kind, tick and crossfade intact",
                  added[1].isDrop && !added[1].enabled && added[1].crossfade == 1.5)
        } else {
            check("the saved file loads", false)
        }

        // A playlist written on Windows, or by something else entirely.
        let windows = "\u{FEFF}#EXTM3U\r\n#EXTINF:123,Some Artist - Song\r\nMusic\\track.mp3\r\n"
                    + "# a comment\r\n\r\nhttp://stream.example/live\r\n"
                    + "file:///Users/tony/Music/a%20b.mp3\r\n\"/Users/tony/quoted.wav\"\r\n"
        let parsed = M3U.loads(windows, folder: "/tmp/x")
        check("a byte order mark is stripped", parsed.entries.first?.artist == "Some Artist")
        check("a Windows relative path with backslashes resolves",
              parsed.entries.first?.filepath == "/tmp/x/Music/track.mp3",
              parsed.entries.first?.filepath ?? "nil")
        check("a stream address is not something we play", parsed.entries.count == 3,
              "\(parsed.entries.map(\.filepath))")
        check("a file URL is a path", parsed.entries[1].filepath == "/Users/tony/Music/a b.mp3",
              parsed.entries[1].filepath)
        check("quotes are taken off", parsed.entries[2].filepath == "/Users/tony/quoted.wav")
        check("an old Windows-1252 file still decodes",
              M3U.decode(Data([0x63, 0x61, 0x66, 0xE9])) == "caf\u{E9}")

        // A saved running order comes back with its missing tracks still in it.
        let gone = Playlist()
        let kept = gone.addEntries([M3UEntry(filepath: "/nowhere/lost.mp3", title: "Lost", artist: nil,
                                             duration: 90, kind: nil, enabled: true, crossfade: nil)])
        check("a missing track is kept in its place rather than dropped",
              kept.count == 1 && kept[0].isMissing && kept[0].displayName == "Lost"
              && kept[0].duration == 90)
        check("relative-if-under refuses a path that would begin with dot dot",
              M3U.relativeIfUnder("/a/b/c.mp3", "/a/x") == "/a/b/c.mp3")
        out.append("")
    }

    // --------------------------------------------------------- the library ---

    private func testDropLibrary() {
        out.append("The drops library, and a drop every so many songs")
        let scratch = scratchFolder("drops")
        for name in ["ident1.wav", "ident2.wav", "ident3.wav"] { touchFile(scratch + "/lib/" + name) }
        touchFile(scratch + "/lib/notes.txt")

        let library = DropLibrary()
        let added = library.add([scratch + "/lib"])
        check("a folder is expanded and only the sounds go in", added.count == 3, "\(added.count)")
        check("adding the same folder again adds nothing", library.add([scratch + "/lib"]).isEmpty)

        var previous: String?
        var repeated = false
        for _ in 0..<40 {
            let pick = library.pick()
            if pick != nil && pick == previous { repeated = true }
            previous = pick
        }
        check("a pick is never the same one twice running", !repeated)
        check("a label numbers from one", library.label(0) == "1. ident1", library.label(0))

        let withMissing = DropLibrary()
        withMissing.load(from: ["paths": ["/nowhere/gone.wav"]], relativeTo: nil)
        check("the Windows key is read", withMissing.count == 1)
        check("a missing drop is counted as missing", withMissing.missing.count == 1)
        check("and is never picked", withMissing.pick() == nil)
        check("and says so in its label", withMissing.label(0).hasSuffix("file missing"))
        let transitional = DropLibrary()
        transitional.load(from: ["files": ["/nowhere/a.wav", "/nowhere/b.wav"]], relativeTo: nil)
        check("the key this build briefly wrote is still read", transitional.count == 2)
        check("but it is written back under the Windows key",
              (library.toDict()["paths"] as? [String])?.count == 3)

        // Through the board, which is where it travels.
        let board = Board()
        board.drops.add([scratch + "/lib/ident1.wav"])
        let back = Board.from(dict: board.toDict(), relativeTo: nil)
        check("the library rides with the board", back.drops.paths == board.drops.paths)

        // A drop after every so many songs.
        let pl = Playlist()
        for i in 1...5 {
            let t = Track(filepath: touchFile(scratch + "/songs/s\(i).mp3"))
            pl.tracks.append(t)
        }
        let drop = scratch + "/lib/ident2.wav"
        let shape = { pl.tracks.map { $0.isDrop ? "D" : "s" } }
        check("every two songs, over five songs, puts in two",
              pl.insertDropEvery(drop, every: 2) == 2, "\(shape())")
        check("after songs two and four, never after the last",
              shape() == ["s", "s", "D", "s", "s", "D", "s"], "\(shape())")
        check("running it again adds nothing, the drops are already there",
              pl.insertDropEvery(drop, every: 2) == 0)
        let three = Playlist()
        for i in 1...3 { three.tracks.append(Track(filepath: scratch + "/songs/s\(i).mp3")) }
        check("every song, over three songs, puts in two", three.insertDropEvery(drop, every: 1) == 2)
        check("zero songs is refused", three.insertDropEvery(drop, every: 0) == 0)

        let fromLibrary = Playlist()
        for i in 1...5 { fromLibrary.tracks.append(Track(filepath: scratch + "/songs/s\(i).mp3")) }
        let n = fromLibrary.insertDropsEvery(library, every: 1)
        check("the library version fills every gap", n == 4, "\(n)")
        let picks = fromLibrary.tracks.filter(\.isDrop).map(\.filepath)
        var sameTwice = false
        for i in 1..<picks.count where picks[i] == picks[i - 1] { sameTwice = true }
        check("and never the same ident twice running", !sameTwice, "\(picks)")
        out.append("")
    }

    // ------------------------------------------------- stations, importing ---

    private func testStationsAndImport() {
        out.append("Saved stations, and boards from elsewhere")
        let board = Board()
        board.stream.host = "radio.example"
        board.stream.name = "Tony's Tunes"
        board.stream.password = "hunter2"
        check("a station is saved under its name",
              board.saveStation() != nil && board.stationNames == ["Tony's Tunes"])
        board.stream.host = "other.example"
        check("and loads back over the live settings",
              board.loadStation("Tony's Tunes") && board.stream.host == "radio.example")
        check("saving the same name again replaces rather than doubles",
              board.saveStation() != nil && board.streamStations.count == 1)
        board.stream.name = "Blindside Radio"
        board.stream.host = "blindside.example"
        board.saveStation()
        check("two stations, two names", board.stationNames == ["Tony's Tunes", "Blindside Radio"])
        check("an unknown station is refused", !board.loadStation("Nowhere FM"))
        check("a station can be forgotten",
              board.forgetStation("Tony's Tunes") && board.stationNames == ["Blindside Radio"])
        check("forgetting one that is not there says so", !board.forgetStation("Tony's Tunes"))

        let again = Board.from(dict: board.toDict(), relativeTo: nil)
        check("stations survive the file", again.stationNames == ["Blindside Radio"])
        check("with the password",
              (again.streamStations.first?["stream_password"] as? String) == "hunter2")

        var junk = Board().toDict()
        junk["stream_stations"] = ["not a station", ["stream_host": "no name"],
                                   ["stream_name": "Real", "stream_host": "x"]]
        check("junk in the station list is dropped rather than trusted",
              Board.from(dict: junk, relativeTo: nil).stationNames == ["Real"])

        var old = Board().toDict()
        old["stream_host"] = "legacy.example"
        old["stream_name"] = "Old"
        old.removeValue(forKey: "stream_stations")
        check("a board older than stations still has its one station",
              Board.from(dict: old, relativeTo: nil).stationNames == ["Old"])

        var winFormat = Board().toDict()
        winFormat["stream_stations"] = [["stream_name": "MP3 station", "stream_host": "h",
                                         "stream_format": "mp3"]]
        let mp3 = Board.from(dict: winFormat, relativeTo: nil)
        mp3.loadStation("MP3 station")
        check("a Windows MP3 station is moved to a format this build sends",
              mp3.stream.format == C.defaultStreamFormat)

        let scratch = scratchFolder("import")
        let ours = scratch + "/board.json"
        _ = try? Board().save(to: ours)
        check("our own board is recognised", Board.describeSource(ours) == "drop deck")
        let legacy = touchFile(scratch + "/old.json",
                               "{\"slots\": [{\"filepath\": \"/tmp/x.wav\", \"name\": \"X\"}], \"sfx_volume\": 0.7}")
        check("an old soundboard bank is recognised", Board.describeSource(legacy) == "legacy soundboard")
        check("and loads with its slots", Board.load(legacy)?.slots[0].name == "X")
        check("anything else is refused",
              Board.describeSource(touchFile(scratch + "/other.json", "{\"x\": 1}")) == nil)
        check("a file that is not there is refused", Board.describeSource("/nowhere.json") == nil)

        // Adopting: everything moves, and the slots know their new board.
        let source = Board()
        source.bankNames[1] = "Stings"
        source.playlist.tracks = [Track(filepath: "/tmp/song.mp3")]
        source.playlist.crossfade = 4.0
        source.drops.load(from: ["paths": ["/tmp/d.wav"]], relativeTo: nil)
        source.stream.host = "live.example"
        source.micGainDB = 6
        source.speechLevel = C.speechEssential
        let target = Board()
        target.path = "/tmp/mine.json"
        target.replaceContents(with: source)
        check("the running order comes across",
              target.playlist.count == 1 && target.playlist.crossfade == 4.0)
        check("so does the library", target.drops.count == 1)
        check("and the stream, the microphone and the speech level",
              target.stream.host == "live.example" && target.micGainDB == 6
              && target.speechLevel == C.speechEssential)
        check("and the bank names", target.bankNames[1] == "Stings")
        check("the slots belong to the new board", target.slots[0].board === target)
        check("the path is the one thing kept", target.path == "/tmp/mine.json")
        out.append("")
    }

    // ------------------------------------------------------------- feedback ---

    private func testFeedback() {
        out.append("Feedback, which never sends a name or a path")
        let scratch = scratchFolder("feedback")
        Feedback.stateDirOverride = scratch
        defer { Feedback.stateDirOverride = nil }

        let id = Feedback.installID()
        check("an install id is eight hex characters",
              id.count == 8 && id.allSatisfy { $0.isHexDigit }, id)
        check("and is the same the second time", Feedback.installID() == id)

        let report = Feedback.build(type: "bug", message: "  It broke  ",
                                    extra: ["sounds_assigned": 3, "ducking": true])
        check("a report carries exactly the declared fields",
              Set(report.keys) == ["type", "type_label", "message", "install", "written_at", "diagnostics"],
              "\(report.keys.sorted())")
        check("the message is trimmed", (report["message"] as? String) == "It broke")
        let text = Feedback.readable(report)
        check("the read back names the category",
              text.contains("Category: Bug - something is broken or wrong"))
        check("and shows the counts with their names",
              text.contains("sounds assigned: 3") && text.contains("ducking: True"), text)
        check("and the version and platform",
              text.contains("version: \(C.appVersion)") && text.contains("platform: macOS"))
        check("and says what is not sent", text.contains("No file names, no sound names"))
        check("this copy is named by its id", text.contains("this copy: \(id)"))

        check("the queue starts empty", Feedback.queuedCount() == 0)
        Feedback.record(report)
        check("a report is on disk before anything is sent", Feedback.queuedCount() == 1)
        try? FileManager.default.removeItem(atPath: scratch + "/" + Feedback.queueFile)

        // Donating: never in the first week, once a week after, and never
        // again once asked not to.
        let day = 86400.0
        func setDonate(_ state: [String: Any]) {
            let data = try! JSONSerialization.data(withJSONObject: state)
            try! data.write(to: URL(fileURLWithPath: scratch + "/" + Feedback.donateFile))
        }
        func stamp(_ daysAgo: Double) -> String {
            let f = ISO8601DateFormatter()
            f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            return f.string(from: Date(timeIntervalSinceNow: -daysAgo * day))
        }
        try? FileManager.default.removeItem(atPath: scratch + "/" + Feedback.donateFile)
        check("the first launch starts the clock and says nothing", !Feedback.shouldAskAboutDonating())
        check("and the clock is written", Feedback.donateState()["first_seen"] != nil)
        check("nobody is asked in their first week", !Feedback.shouldAskAboutDonating())
        setDonate(["first_seen": stamp(30)])
        check("after a month with no asks it is time", Feedback.shouldAskAboutDonating())
        setDonate(["first_seen": stamp(30), "asked_at": stamp(2)])
        check("asked two days ago means not yet", !Feedback.shouldAskAboutDonating())
        setDonate(["first_seen": stamp(30), "asked_at": stamp(8)])
        check("asked eight days ago means yes", Feedback.shouldAskAboutDonating())
        setDonate(["first_seen": stamp(30), "donated_at": stamp(20)])
        check("somebody who donated is left alone for months", !Feedback.shouldAskAboutDonating())
        setDonate(["first_seen": stamp(400), "never": true])
        check("never means never", !Feedback.shouldAskAboutDonating())
        // The Windows copy's own stamp shape, six fractional digits and an offset.
        setDonate(["first_seen": "2026-01-01T10:00:00.123456+00:00"])
        check("a stamp written by the Windows copy is understood", Feedback.shouldAskAboutDonating())
        out.append("")
    }

    // -------------------------------------------------------------- updates ---

    private func testUpdates() {
        out.append("The update channel, verified against a key made on the spot")

        check("a version parses to three numbers", AppUpdate.parseVersion("3.2.2") == [3, 2, 2])
        check("a short version pads out", AppUpdate.parseVersion("4") == [4, 0, 0])
        check("junk sorts as zero", AppUpdate.parseVersion("banana") == [0, 0, 0])
        check("versions compare as numbers, not strings",
              AppUpdate.isNewer("0.10.0", than: "0.9.0") && !AppUpdate.isNewer("0.9.0", than: "0.10.0"))
        check("the same version is not newer", !AppUpdate.isNewer(C.appVersion, than: C.appVersion))
        check("a newer patch is newer", AppUpdate.isNewer("3.2.3", than: "3.2.2"))

        // The exact bytes Python signs. Both expected strings are Python's own
        // output for the same objects, pasted in.
        let sample: [String: Any] = [
            "b": 1,
            "a": "h\u{E9}llo \"q\" \\ \n\t/ \u{2014} \u{1F600}",
            "c": true,
            "d": NSNull(),
            "e": [1, "x", 2.5, -0.5, 10.0] as [Any],
            "f": ["z": 0, "y": -3],
        ]
        let u = "\\u"   // a backslash and a u, which is how Python spells anything non-ASCII
        let expected = "{\"a\":\"h" + u + "00e9llo \\\"q\\\" \\\\ \\n\\t/ "
            + u + "2014 " + u + "d83d" + u + "de00\",\"b\":1,\"c\":true,\"d\":null,"
            + "\"e\":[1,\"x\",2.5,-0.5,10.0],\"f\":{\"y\":-3,\"z\":0}}"
        let got = String(decoding: AppUpdate.canonical(sample), as: UTF8.self)
        check("the canonical bytes match Python's byte for byte", got == expected, got)
        let control: [String: Any] = ["n": "line\rone" + String(UnicodeScalar(UInt8(1))) + String(UnicodeScalar(UInt8(127)))]
        let expectedControl = "{\"n\":\"line\\rone" + "\\u" + "0001" + "\\u" + "007f\"}"
        let gotControl = String(decoding: AppUpdate.canonical(control), as: UTF8.self)
        check("control characters and delete are escaped the Python way",
              gotControl == expectedControl, gotControl)
        // And the same after a trip through the JSON parser, which is what the
        // real check does: numbers and booleans come back as NSNumber.
        if let parsed = try? JSONSerialization.jsonObject(with: AppUpdate.canonical(sample)) {
            check("the bytes survive being parsed and rebuilt",
                  AppUpdate.canonical(parsed) == AppUpdate.canonical(sample))
        } else {
            check("the canonical form parses as JSON", false)
        }

        for (name, key) in [("Windows", AppUpdate.publicKeyB64), ("Mac", AppUpdate.macPublicKeyB64)] {
            check("the baked in \(name) public key is a real ed25519 key",
                  Data(base64Encoded: key).flatMap {
                      try? Curve25519.Signing.PublicKey(rawRepresentation: $0) } != nil)
        }
        check("both keys are trusted and they are different",
              AppUpdate.trustedKeysB64.count == 2 && AppUpdate.publicKeyB64 != AppUpdate.macPublicKeyB64)

        // Sign a manifest with a key made here and verify it with the client's
        // own code.
        let key = Curve25519.Signing.PrivateKey()
        let publicB64 = key.publicKey.rawRepresentation.base64EncodedString()
        let manifest: [String: Any] = [
            "product": C.appName, "platform": "mac", "version": "9.9.9",
            "url": "https://tgstudios.app/downloads/TG-Drop-Deck-9.9.9-mac.zip",
            "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            "size": 3, "notes": "Everything is better \u{2014} really.",
        ]
        let signature = (try? key.signature(for: AppUpdate.canonical(manifest)))?
            .base64EncodedString() ?? ""
        func envelope(_ m: [String: Any], _ sig: String) -> Data {
            try! JSONSerialization.data(withJSONObject: ["manifest": m, "signature": sig])
        }
        let good = AppUpdate.evaluate(envelope(manifest, signature), currentVersion: "3.2.2",
                                      trustedKeys: [publicB64])
        check("a signed manifest verifies", good.info != nil, good.message)
        check("and an old client is offered it", good.available && good.info?.version == "9.9.9")
        check("with its notes", good.info?.notes.hasPrefix("Everything is better") == true)
        let current = AppUpdate.evaluate(envelope(manifest, signature), currentVersion: "9.9.9",
                                         trustedKeys: [publicB64])
        check("a client already on it is not", !current.available && current.message.contains("newest"))

        var tampered = manifest
        tampered["version"] = "99.0.0"
        let edited = AppUpdate.evaluate(envelope(tampered, signature), currentVersion: "3.2.2",
                                        trustedKeys: [publicB64])
        check("a manifest edited after signing is rejected",
              edited.info == nil && edited.message.contains("wrong key"), edited.message)
        let wrongKey = AppUpdate.evaluate(envelope(manifest, signature), currentVersion: "3.2.2")
        check("a manifest signed by somebody else's key is rejected", wrongKey.info == nil)
        let unreadable = AppUpdate.evaluate(Data("not json".utf8), currentVersion: "3.2.2",
                                            trustedKeys: [publicB64])
        check("nonsense from the server is said to be unreadable",
              unreadable.message.contains("unreadable"))
        var noURL = manifest
        noURL.removeValue(forKey: "url")
        let noSig = (try? key.signature(for: AppUpdate.canonical(noURL)))?.base64EncodedString() ?? ""
        check("a manifest with no download in it is unreadable too",
              AppUpdate.evaluate(envelope(noURL, noSig), currentVersion: "0.0.0",
                                 trustedKeys: [publicB64]).info == nil)

        check("SHA-256 is the real thing",
              SHA256.hash(data: Data("abc".utf8)).map { String(format: "%02x", $0) }.joined()
              == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

        let scratch = scratchFolder("updates")
        check("with no stamp a check is due", AppUpdate.shouldCheck(scratch))
        AppUpdate.stampCheck(scratch)
        check("just after a check it is not", !AppUpdate.shouldCheck(scratch))
        check("but a day later it is",
              AppUpdate.shouldCheck(scratch, now: Date().timeIntervalSince1970 + 25 * 3600))
        AppUpdate.stampCheck(scratch, when: Date().timeIntervalSince1970 + 7200)
        check("a clock that went backwards counts as due", AppUpdate.shouldCheck(scratch))
        out.append("")

        testUpdateInstall()
    }

    /// The swap itself, rehearsed on scratch bundles: a zip of this very app is
    /// unpacked the way a download is, and put in place of a copy standing in
    /// for the installed one. The arithmetic of an update is nothing; this is
    /// the part that has to work on a Tuesday night.
    private func testUpdateInstall() {
        out.append("Replacing the app with a new copy, rehearsed on scratch bundles")
        let fm = FileManager.default
        let bundle = Bundle.main.bundlePath
        guard bundle.hasSuffix(".app") else {
            out.append("  note  not running from a bundle, so this was not checked")
            out.append("")
            return
        }
        let scratch = scratchFolder("install")
        let zip = scratch + "/download.zip"
        let ditto = Process()
        ditto.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        ditto.arguments = ["-c", "-k", "--keepParent", bundle, zip]
        ditto.standardOutput = FileHandle.nullDevice
        try? ditto.run()
        ditto.waitUntilExit()
        check("a zip of the app can be made the way the release script makes one",
              ditto.terminationStatus == 0)

        var unpacked: String?
        do {
            unpacked = try AppUpdate.unpack(zipPath: zip, version: "selftest")
        } catch {
            check("the download unpacks and passes its signature check", false,
                  error.localizedDescription)
        }
        if let unpacked {
            check("the download unpacks and passes its signature check",
                  unpacked.hasSuffix(".app"), unpacked)
            let apps = scratch + "/Applications"
            try? fm.createDirectory(atPath: apps, withIntermediateDirectories: true)
            let target = apps + "/TG Drop Deck.app"
            try? fm.copyItem(atPath: bundle, toPath: target)
            // Mark the new copy, so a swap can be told from nothing happening.
            fm.createFile(atPath: unpacked + "/Contents/Resources/selftest-marker",
                          contents: Data("new".utf8))
            check("the folder the app lives in can be written to", AppUpdate.canReplace(target))
            let (ok, message) = AppUpdate.replace(target: target, with: unpacked)
            check("the new copy goes where the old one was", ok, message)
            check("and it really is the new copy",
                  fm.fileExists(atPath: target + "/Contents/Resources/selftest-marker"))
            check("the old copy is set aside rather than deleted",
                  fm.fileExists(atPath: target + ".replaced"))
            check("and the staging copy has moved rather than been copied",
                  !fm.fileExists(atPath: unpacked))
        }
        try? fm.removeItem(atPath: (AppUpdate.stagingRoot() as NSString).appendingPathComponent("selftest"))
        try? fm.removeItem(atPath: scratch)
        out.append("")
    }
}
