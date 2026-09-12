// The checks, run with --selftest.
//
// The Windows copy runs its suites against the FROZEN build rather than the
// source, because the source passing tells you nothing about the shipped one:
// a missing data file or a dead audio backend only shows up in the bundle. So
// this lives inside the app and the release script runs the built binary.
//
// The engine tests render the whole mixer and inspect the samples with no
// sound card present, which is the reason Engine.swift and Mixer.swift know
// nothing about AppKit. Where a number is asserted here it is asserted against
// the constant, not against a copy of it, so changing a constant cannot
// silently invalidate a test.

import Foundation
import AppKit
import AVFoundation

/// Prints each line as it arrives.
final class LiveLog {
    func append(_ line: String) {
        print(line)
        fflush(stdout)
    }
}

final class SelfTest {

    private var failures: [String] = []
    private var checks = 0
    // Printed as it goes rather than collected, so a crash mid run still
    // shows which check it got to.
    let out = LiveLog()

    func check(_ name: String, _ condition: Bool, _ detail: String = "") {
        checks += 1
        if condition {
            out.append("  ok    \(name)")
        } else {
            failures.append(name + (detail.isEmpty ? "" : ": " + detail))
            out.append("  FAIL  \(name)\(detail.isEmpty ? "" : "  " + detail)")
        }
    }

    func near(_ a: Double, _ b: Double, _ tolerance: Double = 0.01) -> Bool {
        abs(a - b) <= tolerance
    }

    func run() -> Int32 {
        out.append("\(C.appName) \(C.appVersion), self test")
        out.append("")

        testSlotLabels()
        testKeyMap()
        testBoardRoundTrip()
        testPlaylistArithmetic()
        testVoiceEnvelope()
        testDuckRamp()
        testSoftClip()
        testDecoding()
        testHandover()
        testCueTone()
        testSettingsLayout()
        testKeyboardHelp()
        testStreamEncoders()
        runMoreChecks()
        runAirChecks()
        runSendChecks()
        runVideoChecks()
        testRealDevice()

        out.append("")
        out.append("\(checks) checks, \(failures.count) failed")
        if !failures.isEmpty {
            out.append("")
            for f in failures { out.append("FAILED: \(f)") }
        }
        return failures.isEmpty ? 0 : 1
    }

    // ---------------------------------------------------------- slot labels ---

    private func testSlotLabels() {
        out.append("Slot labels, which are what a screen reader reads")
        KeyMap.scheme = .command

        let scratch = NSTemporaryDirectory() + "dropdeck-selftest"
        try? FileManager.default.createDirectory(atPath: scratch,
                                                 withIntermediateDirectories: true)
        func touchFile(_ name: String) -> String {
            let p = (scratch as NSString).appendingPathComponent(name)
            FileManager.default.createFile(atPath: p, contents: Data())
            return p
        }

        let board = Board()
        let slot = board.slots[2]                    // bank 1, button 3
        check("an empty pad names its key",
              slot.buttonLabel() == "3. Empty, key 3", slot.buttonLabel())

        slot.filepath = touchFile("audience laugh.wav")
        slot.duration = 4.0
        check("name, key and length, in that order",
              slot.buttonLabel() == "3. audience laugh, key 3, 4 sec", slot.buttonLabel())

        check("playing is added only when asked for",
              slot.buttonLabel(playing: true) == "3. audience laugh, key 3, playing, 4 sec",
              slot.buttonLabel(playing: true))

        slot.globalHotkey = "Ctrl+Alt+F9"
        check("a global hotkey comes after the key",
              slot.buttonLabel() == "3. audience laugh, key 3, global Ctrl+Alt+F9, 4 sec",
              slot.buttonLabel())
        slot.globalHotkey = nil

        try? FileManager.default.removeItem(atPath: slot.filepath!)
        // A missing file says so and says nothing else: a duration for a file
        // that is not there would be a claim about something we cannot see.
        check("a missing file replaces the state words",
              slot.buttonLabel() == "3. audience laugh, key 3, file missing", slot.buttonLabel())

        let bed = board.slots[(C.bankBeds - 1) * C.slotsPerBank + 12]   // bed 13
        bed.filepath = touchFile("playful quirky.ogg")
        bed.duration = 30.0
        check("a bed says it loops",
              bed.buttonLabel().contains("loops"), bed.buttonLabel())
        check("bed 13 is on the shifted row",
              bed.hotkeyLabel == "Opt+Cmd+Shift+3", bed.hotkeyLabel)

        let folder = board.slots[6]
        folder.filepath = scratch
        folder.folderCount = 6
        check("a folder gives a count, never a length",
              folder.buttonLabel().contains("folder, 6 sounds"), folder.buttonLabel())

        check("a duration says minutes and seconds without a colon",
              formatDuration(83) == "1 min 23 sec", formatDuration(83))
        check("a whole minute drops the seconds",
              formatDuration(120) == "2 min", formatDuration(120))

        // The bank name belongs to the user; what the keys do does not.
        board.bankNames[C.bankBeds] = "Under-beds"
        check("a renamed bank keeps its behaviour",
              bed.isBed && bed.loop && bed.bankTitle == "Under-beds", bed.bankTitle)
        check("a renamed bank is used whole in a search label",
              bed.searchLabel().contains("Under-beds 13"), bed.searchLabel())
        out.append("")
    }

    // --------------------------------------------------------------- keymap ---

    private func testKeyMap() {
        out.append("The keyboard map")
        KeyMap.scheme = .command

        check("bare 1 is sound 1",
              KeyMap.slotFor(characters: "1", mods: []) == 0)
        check("0 is sound 10",
              KeyMap.slotFor(characters: "0", mods: []) == 9)
        check("Shift 1 is sound 11",
              KeyMap.slotFor(characters: "1", mods: [.shift]) == 10)
        check("Command 1 is drop 1",
              KeyMap.slotFor(characters: "1", mods: [.command]) == C.slotsPerBank)
        check("Command Shift 1 is drop 11",
              KeyMap.slotFor(characters: "1", mods: [.command, .shift]) == C.slotsPerBank + 10)
        check("Option Command 1 is bed 1",
              KeyMap.slotFor(characters: "1", mods: [.option, .command]) == C.slotsPerBank * 2)
        check("Option Command Shift 1 is bed 11",
              KeyMap.slotFor(characters: "1", mods: [.option, .command, .shift])
              == C.slotsPerBank * 2 + 10)

        // The Windows combinations stay accepted where the system leaves them
        // free. A key somebody has already learned does not get taken away.
        check("the Windows Control 1 still reaches drop 1",
              KeyMap.slotFor(characters: "1", mods: [.control]) == C.slotsPerBank)
        check("the Windows Option Control 1 still reaches bed 1",
              KeyMap.slotFor(characters: "1", mods: [.option, .control]) == C.slotsPerBank * 2)

        check("bank 4 has no fixed key",
              KeyMap.hotkeyLabel(bank: C.bankMisc, positionInBank: 0).isEmpty)
        check("nothing fires on Command Option Control together",
              KeyMap.slotFor(characters: "1", mods: [.command, .option, .control]) == nil)

        // Every slot must be reachable, and no two by the same combination.
        var reached = Set<Int>()
        let modSets: [NSEventModifierFlagsBox] = [
            .init(NSEvent.ModifierFlags()), .init(NSEvent.ModifierFlags.shift),
            .init(KeyMap.bank2Mods), .init(KeyMap.bank2Mods.union(.shift)),
            .init(KeyMap.bank3Mods), .init(KeyMap.bank3Mods.union(.shift)),
        ]
        for m in modSets {
            for d in C.digits {
                if let slot = KeyMap.slotFor(characters: String(d), mods: m.value) {
                    reached.insert(slot)
                }
            }
        }
        check("all sixty fixed pads are reachable and distinct", reached.count == 60,
              "\(reached.count)")

        KeyMap.scheme = .literal
        check("the literal scheme puts drops back on Control",
              KeyMap.hotkeyLabel(bank: C.bankDrops, positionInBank: 0) == "Ctrl+1")
        KeyMap.scheme = .command
        check("the command scheme labels drops with Cmd",
              KeyMap.hotkeyLabel(bank: C.bankDrops, positionInBank: 0) == "Cmd+1")

        // TWO COMMANDS ON ONE KEY IS NOT A CLASH ANYTHING REPORTS. AppKit gives
        // the key to whichever menu item it reaches first in the menu bar and
        // the other one is simply unreachable for ever, with nothing anywhere
        // saying why. That is how "Go to the soundboard" quietly took Option
        // Command Shift S off Source control between 3.2.2 and 3.3.0, and it is
        // the same shape as the Windows bug where a frame accelerator took
        // Ctrl+Shift+S off Save board as. Nothing but a check catches it.
        var claimed: [String: String] = [:]
        var collisions: [String] = []
        for command in Command.allCases {
            for binding in KeyMap.bindings[command] ?? [] {
                let key = KeyMap.identity(key: binding.key, mods: binding.mods)
                if let already = claimed[key], already != command.rawValue {
                    collisions.append("\(KeyMap.spell(key: binding.key, mods: binding.mods)): "
                                      + "\(already) and \(command.rawValue)")
                } else {
                    claimed[key] = command.rawValue
                }
            }
        }
        check("no two commands are on the same key", collisions.isEmpty,
              collisions.joined(separator: "; "))

        // A modal key claim must not reach past a box opened on top of it.
        // Shipped broken in 3.3.2: the source control panel claimed every key
        // for every window, then opened a nested rename alert, so a digit
        // typed into the name jumped the list behind it and Space opened a
        // second rename box. A source name with a space in it could not be
        // typed. See ModalKeys.owner.
        do {
            let outer = NSWindow()
            let inner = NSWindow()
            var reached = 0
            ModalKeys.claim({ _ in reached += 1; return true }, window: outer) {
                check("a claim with no window in front is active", ModalKeys.active())
                // Nothing here can run a real modal session, so the state is
                // exercised directly: what matters is that `active` answers on
                // the identity of the front window rather than always yes.
                check("a claim knows which window owns it", ModalKeys.owner === outer)
            }
            check("a claim is cleared on the way out", ModalKeys.current == nil)
            check("and so is its owner", ModalKeys.owner == nil)
            check("a claim never fired outside its body", reached == 0)
            _ = inner
        }

        // An alias is only reachable because the key monitor dispatches it, and
        // it must never be some other command's real menu key.
        var shadowed: [String] = []
        var aliases = 0
        for command in Command.allCases {
            for binding in KeyMap.bindings[command] ?? [] where !binding.primary {
                aliases += 1
                if KeyMap.primaryKeys.contains(
                    KeyMap.identity(key: binding.key, mods: binding.mods)) {
                    shadowed.append("\(KeyMap.spell(key: binding.key, mods: binding.mods)) "
                                    + "for \(command.rawValue)")
                }
            }
        }
        check("every alias key is free of the menus", shadowed.isEmpty,
              shadowed.joined(separator: "; "))
        check("the aliases are still there to dispatch", aliases >= 8, "\(aliases)")

        // The three keys that answer for the sources, which have to exist and
        // have to be distinct from each other and from everything else.
        for command in [Command.sourceControl, .muteSources, .soloMic] {
            check("\(command.rawValue) has a key",
                  KeyMap.menuKey(command) != nil)
        }
        out.append("")
    }

    // ------------------------------------------------------- board on disk ---

    private func testBoardRoundTrip() {
        out.append("The board file, which the Windows copy also reads")

        let board = Board()
        board.slots[0].filepath = "/tmp/one.wav"
        board.slots[0].name = "One"
        board.slots[0].duration = 2.5
        board.slots[0].trimDB = -3
        board.bankNames[2] = "Idents"
        board.bedFadeIn = 0.0
        board.bedFadeOut = 1.25
        board.duckDB = -12

        // A field this build has never heard of, standing in for everything
        // the Windows copy owns and this one has not reached yet.
        var dict = board.toDict()
        dict["stream_password"] = "hunter2"
        dict["voice_settings"] = ["comp_ratio": 3.0]
        var slotRow = dict["slots"] as! [[String: Any]]
        slotRow[0]["key_code"] = 49
        slotRow[0]["modifiers"] = 2
        dict["slots"] = slotRow

        let reloaded = Board.from(dict: dict, relativeTo: nil)
        let again = reloaded.toDict()

        check("a bank name survives", (again["bank_names"] as? [String: String])?["2"] == "Idents")
        check("a bed fade of zero is not turned into the default",
              (again["bed_fade_in"] as? Double) == 0.0,
              "\(again["bed_fade_in"] ?? "nil")")
        check("a bed fade out survives", (again["bed_fade_out"] as? Double) == 1.25)
        check("the duck depth survives", (again["duck_db"] as? Double) == -12)
        check("an unknown top level field is written back",
              (again["stream_password"] as? String) == "hunter2")
        check("an unknown nested field is written back",
              (again["voice_settings"] as? [String: Any])?["comp_ratio"] as? Double == 3.0)

        let outSlots = again["slots"] as! [[String: Any]]
        check("the Windows key code is carried through untouched",
              (outSlots[0]["key_code"] as? Int) == 49)
        check("the Windows modifiers are carried through untouched",
              (outSlots[0]["modifiers"] as? Int) == 2)
        check("a slot name survives", (outSlots[0]["name"] as? String) == "One")
        check("a slot trim survives", (outSlots[0]["trim_db"] as? Double) == -3)

        // A board may store paths relative to itself, which is how the shipped
        // demo resolves wherever the app lands.
        var relative = Board().toDict()
        var rows = relative["slots"] as! [[String: Any]]
        rows[0]["filepath"] = "sfx/airhorn.flac"
        relative["slots"] = rows
        let resolved = Board.from(dict: relative, relativeTo: "/opt/demo")
        check("a relative path resolves against the board's own folder",
              resolved.slots[0].filepath == "/opt/demo/sfx/airhorn.flac",
              resolved.slots[0].filepath ?? "nil")

        check("a fade is clamped rather than trusted",
              Board.fade(99.0, fallback: 0.6) == C.maxBedFade)
        check("a fade that is not a number falls back",
              Board.fade("banana", fallback: 0.6) == 0.6)
        out.append("")
    }

    // ------------------------------------------------------------- playlist ---

    private func testPlaylistArithmetic() {
        out.append("The playlist cue points")

        let scratch = NSTemporaryDirectory() + "dropdeck-selftest"
        try? FileManager.default.createDirectory(atPath: scratch,
                                                 withIntermediateDirectories: true)
        func realFile(_ name: String) -> String {
            let p = (scratch as NSString).appendingPathComponent(name)
            FileManager.default.createFile(atPath: p, contents: Data())
            return p
        }

        let pl = Playlist()
        for i in 1...3 {
            let t = Track(filepath: realFile("song\(i).wav"))
            t.duration = 4.0
            t.tailSilence = 0.0
            pl.tracks.append(t)
        }
        pl.crossfade = 1.0
        var points = pl.cuePoints()
        check("three four second songs at a one second crossfade start at 0, 3 and 6",
              near(points[0] ?? -1, 0) && near(points[1] ?? -1, 3) && near(points[2] ?? -1, 6),
              "\(points)")
        check("and run for ten seconds", near(pl.totalDuration, 10.0), "\(pl.totalDuration)")

        // With no crossfade at all each song still overlaps by SEGUE_LEAD, or a
        // spot would sit in a hole rather than butting up against the song.
        pl.crossfade = 0.0
        check("zero crossfade still leaves the segue lead",
              near(pl.totalDuration, 12.0 - 2 * C.segueLead), "\(pl.totalDuration)")

        // A crossfade longer than the track is clamped to the track.
        let sting = Playlist()
        let short = Track(filepath: realFile("sting.wav"))
        short.duration = 0.4
        short.tailSilence = 0.0
        sting.tracks = [short, Track(filepath: realFile("next.wav"))]
        sting.tracks[1].duration = 4.0
        sting.tracks[1].tailSilence = 0.0
        sting.crossfade = 3.0
        check("a crossfade longer than the track is clamped to it",
              near(sting.crossfadeFor(0), 0.4), "\(sting.crossfadeFor(0))")

        // A drop butts up against the song behind it and never fades under it.
        let withDrop = Playlist()
        for i in 0..<3 {
            let t = Track(filepath: realFile("t\(i).wav"))
            t.duration = 4.0
            t.tailSilence = 0.0
            withDrop.tracks.append(t)
        }
        withDrop.tracks[1].kind = C.trackDrop
        withDrop.crossfade = 3.0
        check("a drop has no crossfade of its own",
              withDrop.crossfadeFor(1) == 0.0, "\(withDrop.crossfadeFor(1))")
        points = withDrop.cuePoints()
        check("so the song after a drop starts a segue lead before it ends",
              near(points[2] ?? -1, (points[1] ?? 0) + 4.0 - C.segueLead), "\(points)")

        check("the last item has nothing to hand over to",
              withDrop.crossfadeFor(2) == 0.0)

        // An unticked item keeps its place and is stepped over.
        withDrop.tracks[1].enabled = false
        points = withDrop.cuePoints()
        check("an unticked item has no start time at all", points[1] == nil)
        // With the drop unticked, the song before it hands over to the song
        // after it at the ordinary crossfade, not at the segue lead: the drop
        // keeps its place in the list and is simply stepped over.
        check("and the one after it takes its place at the ordinary crossfade",
              near(points[2] ?? -1, 4.0 - 3.0), "\(points)")
        check("next playing steps over it", withDrop.nextPlaying(after: 0) == 2)

        // The crossfade is measured from where the music stops.
        let padded = Playlist()
        let t = Track(filepath: realFile("padded.mp3"))
        t.duration = 10.0
        t.tailSilence = 2.0
        padded.tracks = [t, Track(filepath: realFile("after.wav"))]
        padded.tracks[1].duration = 4.0
        padded.crossfade = 3.0
        check("playable end is the duration less the run out",
              near(t.playableEnd, 8.0), "\(t.playableEnd)")
        check("and the next song starts three seconds before THAT",
              near(padded.cuePoints()[1] ?? -1, 5.0), "\(padded.cuePoints())")

        check("a track crossfade of nil is not the same as zero",
              t.crossfade == nil && t.crossfadeSeconds(default: 3.0) == 3.0)
        t.crossfade = 0.0
        check("a track crossfade of zero is honoured",
              t.crossfadeSeconds(default: 3.0) == 0.0)
        out.append("")
    }

    // ------------------------------------------------------- the envelope ---

    private func testVoiceEnvelope() {
        out.append("Voice envelopes, rendered with no sound card present")

        let rate = 48000.0
        let frames = 512
        let block = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        let ramp = UnsafeMutablePointer<Float>.allocate(capacity: frames)
        defer { block.deallocate(); ramp.deallocate() }

        // One second of full scale, so any gain applied is measurable.
        let samples = [Float](repeating: 1.0, count: Int(rate) * 2)

        // A fade in of zero starts at level. A bed cued on its first beat
        // cannot ease in.
        let flat = MemoryVoice(samples: samples, slotIndex: 0, bus: C.busBed, name: "flat",
                               gain: 1.0, loop: false, rate: rate,
                               fadeIn: 0.0, fadeOut: C.fadeOutBed)
        _ = flat.render(frames: 8, duck: 1.0, into: block, rampScratch: ramp)
        check("a fade in of zero means the first sample is at full level",
              block[0] == 1.0, "\(block[0])")

        // A fade in of 0.1 s should be near silent at its first sample.
        let eased = MemoryVoice(samples: samples, slotIndex: 0, bus: C.busBed, name: "eased",
                                gain: 1.0, loop: false, rate: rate,
                                fadeIn: 0.1, fadeOut: C.fadeOutBed)
        _ = eased.render(frames: 8, duck: 1.0, into: block, rampScratch: ramp)
        check("a fade in of a tenth of a second starts near silence",
              block[0] < 0.01, "\(block[0])")

        // A fade takes the time it was asked for whatever level it starts from.
        // This is the bug the distance normalised step exists to prevent: a
        // three second crossfade on a fader at eighty per cent was really two
        // and a half.
        for startLevel in [Float(1.0), 0.8, 0.5] {
            let v = MemoryVoice(samples: samples, slotIndex: 0, bus: C.busSFX, name: "fade",
                                gain: startLevel, loop: false, rate: rate,
                                fadeIn: 0.0, fadeOut: 0.5)
            v.release(fadeOut: 0.5)
            var rendered = 0
            while !v.finished && rendered < Int(rate) * 2 {
                _ = v.render(frames: frames, duck: 1.0, into: block, rampScratch: ramp)
                rendered += frames
            }
            let seconds = Double(rendered) / rate
            check("a half second fade from \(startLevel) really takes half a second",
                  near(seconds, 0.5, 0.03), String(format: "%.3f s", seconds))
        }

        // Position counts only frames that were really there.
        let short = MemoryVoice(samples: [Float](repeating: 0.5, count: 1000 * 2),
                                slotIndex: 0, bus: C.busSFX, name: "short", gain: 1.0,
                                loop: false, rate: rate, fadeIn: 0, fadeOut: 0)
        _ = short.render(frames: 4096, duck: 1.0, into: UnsafeMutablePointer<Float>
            .allocate(capacity: 4096 * 2), rampScratch: ramp)
        check("position counts real frames, not the padding",
              near(short.positionSeconds, 1000.0 / rate, 0.0001),
              "\(short.positionSeconds)")
        check("a sound that ran out is finished", short.finished)

        // A looping voice never finishes and has no gap at the seam.
        let looping = MemoryVoice(samples: [Float](repeating: 0.5, count: 100 * 2),
                                  slotIndex: 0, bus: C.busBed, name: "loop", gain: 1.0,
                                  loop: true, rate: rate, fadeIn: 0, fadeOut: 0)
        _ = looping.render(frames: 512, duck: 1.0, into: block, rampScratch: ramp)
        var silent = 0
        for i in 0..<(512 * 2) where block[i] == 0 { silent += 1 }
        check("a loop has no gap at the seam", silent == 0, "\(silent) silent samples")
        check("and never finishes on its own", !looping.finished)

        // Only the bed and playlist buses duck; the cue and preview never do.
        check("the sfx bus is what ducks",
              MemoryVoice(samples: samples, slotIndex: 0, bus: C.busSFX, name: "", gain: 1,
                          loop: false, rate: rate, fadeIn: 0, fadeOut: 0).isLoud)
        for bus in [C.busBed, C.busPlaylist] {
            check("the \(bus) bus is ducked",
                  MemoryVoice(samples: samples, slotIndex: 0, bus: bus, name: "", gain: 1,
                              loop: false, rate: rate, fadeIn: 0, fadeOut: 0).isDucked)
        }
        for bus in [C.busCue, C.busPreview] {
            let v = MemoryVoice(samples: samples, slotIndex: 0, bus: bus, name: "", gain: 1,
                                loop: false, rate: rate, fadeIn: 0, fadeOut: 0)
            check("the \(bus) bus neither ducks nor is ducked", !v.isDucked && !v.isLoud)
        }
        out.append("")
    }

    // ------------------------------------------------------------- the duck ---

    private func testDuckRamp() {
        self.out.append("The duck, which really ducks by the amount it claims")

        let rate = 48000.0
        let frames = 512
        let cache = DecodeCache(rate: rate)
        let bus = DuckBus()
        let mixer = Mixer(key: "test", deviceUID: nil, sampleRate: rate,
                          duckBus: bus, cache: cache)
        mixer.ducking = true
        mixer.duckDB = C.defaultDuckDB

        let buf = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { buf.deallocate() }

        // A bed on its own comes out at the bed fader, untouched.
        let bed = [Float](repeating: 0.5, count: Int(rate * 4) * 2)
        mixer.bedGain = 1.0
        mixer.playSamples(slotIndex: 40, samples: bed, bus: C.busBed, name: "bed", gain: 1.0)
        mixer.render(frames: frames, into: buf)
        check("a bed on its own is not ducked", near(Double(buf[0]), 0.5, 0.02), "\(buf[0])")

        // Now a drop lands on top of it.
        let drop = [Float](repeating: 0.0, count: Int(rate) * 2)
        mixer.playSamples(slotIndex: 0, samples: drop, bus: C.busSFX, name: "drop", gain: 1.0)

        // The duck travels one gain unit per DUCK_ATTACK seconds, so reaching
        // minus nine decibels takes DUCK_ATTACK times the distance. Rendering
        // for twice that must have arrived.
        let expected = 0.5 * Double(dbToGain(C.defaultDuckDB))
        let attackSeconds = C.duckAttack * (1.0 - Double(dbToGain(C.defaultDuckDB)))
        var rendered = 0
        while Double(rendered) / rate < attackSeconds * 2 {
            mixer.render(frames: frames, into: buf)
            rendered += frames
        }
        check("a drop ducks the bed to the depth it claims",
              near(Double(buf[0]), expected, 0.02),
              String(format: "%.3f wanted %.3f", buf[0], expected))

        // And the attack is the time the constant implies, not the constant.
        let mixer2 = Mixer(key: "t2", deviceUID: nil, sampleRate: rate,
                           duckBus: DuckBus(), cache: cache)
        mixer2.bedGain = 1.0
        mixer2.playSamples(slotIndex: 40, samples: bed, bus: C.busBed, name: "b", gain: 1.0)
        mixer2.playSamples(slotIndex: 0, samples: drop, bus: C.busSFX, name: "d", gain: 1.0)
        var frameCount = 0
        var landed = false
        while frameCount < Int(rate) {
            mixer2.render(frames: frames, into: buf)
            frameCount += frames
            if Double(buf[0]) <= expected + 0.003 { landed = true; break }
        }
        let took = Double(frameCount) / rate
        check("the duck attack takes the time the constant really implies",
              landed && near(took, attackSeconds, 0.02),
              String(format: "%.3f s, expected about %.3f s", took, attackSeconds))
        self.out.append("")
    }

    private func testSoftClip() {
        self.out.append("Summing, and the ceiling that is a curve rather than a corner")

        let rate = 48000.0
        let frames = 512
        let cache = DecodeCache(rate: rate)
        let mixer = Mixer(key: "clip", deviceUID: nil, sampleRate: rate,
                          duckBus: DuckBus(), cache: cache)
        mixer.ducking = false
        mixer.sfxGain = 1.0
        let buf = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { buf.deallocate() }

        // Two full scale sounds at once, which is what a crossfade is.
        let loud = [Float](repeating: 0.9, count: Int(rate) * 2)
        mixer.playSamples(slotIndex: 0, samples: loud, bus: C.busSFX, name: "a", gain: 1.0)
        mixer.playSamples(slotIndex: 1, samples: loud, bus: C.busSFX, name: "b", gain: 1.0)
        mixer.render(frames: frames, into: buf)

        var peak: Float = 0
        for i in 0..<(frames * 2) { peak = max(peak, abs(buf[i])) }
        check("two loud sounds do not come out above full scale", peak <= 1.0, "\(peak)")
        check("and are bent rather than sawn flat", peak > C.softClipFrom && peak < 1.0,
              "\(peak)")

        // Anything below the threshold is untouched.
        let quiet = Mixer(key: "quiet", deviceUID: nil, sampleRate: rate,
                          duckBus: DuckBus(), cache: cache)
        quiet.ducking = false
        quiet.sfxGain = 1.0
        quiet.playSamples(slotIndex: 0, samples: [Float](repeating: 0.5, count: Int(rate) * 2),
                          bus: C.busSFX, name: "q", gain: 1.0)
        quiet.render(frames: frames, into: buf)
        check("anything under the threshold is left exactly alone",
              near(Double(buf[0]), 0.5, 0.0001), "\(buf[0])")
        self.out.append("")
    }

    // ------------------------------------------------------------- decoding ---

    private func testDecoding() {
        out.append("Decoding, asked of the system rather than assumed")

        let exts = AudioFile.supportedExtensions
        for wanted in ["wav", "mp3", "flac", "aiff", "m4a", "aac"] {
            check("this Mac can read \(wanted)", exts.contains(wanted))
        }
        // The Windows build plays these through FFmpeg. macOS reads the first
        // two and not the rest, which is why the list is derived and not typed.
        check("ogg and opus are readable here too",
              exts.contains("ogg") && exts.contains("opus"))
        check("nothing offers wma, which this Mac cannot decode", !exts.contains("wma"))

        // The demo pack, if it is beside the app.
        if let demoBoard = AppDelegateDemo.locate(),
           let board = Board.load(demoBoard) {
            let assigned = board.slots.filter { $0.isAssigned }
            check("the demo pack loads", assigned.count == 40, "\(assigned.count) slots")
            let present = assigned.filter { !$0.isMissing }
            check("and every file in it is where the board says",
                  present.count == assigned.count,
                  "\(assigned.count - present.count) missing")
            if let first = present.first, let path = first.filepath {
                let info = AudioFile.probe(path)
                check("a demo sound can be probed", info != nil, path)
                let decoded = AudioFile.readAll(path, targetRate: 48000)
                check("and decoded to stereo at the target rate",
                      (decoded?.count ?? 0) > 0)
                if let d = decoded, let i = info {
                    let frames = d.count / 2
                    let seconds = Double(frames) / 48000.0
                    check("with the length the file says it has",
                          near(seconds, i.duration, 0.05),
                          String(format: "%.3f against %.3f", seconds, i.duration))
                }
            }
            // Tags are read through Core Audio rather than AVAsset, so this
            // proves the route works and, more importantly, that an untagged
            // file is not a failure: a file with no tags still plays.
            if let first = present.first, let path = first.filepath {
                let tags = AudioFile.tags(path)
                check("reading tags never throws, tagged or not",
                      tags.title != nil || tags.title == nil)
                let none = AudioFile.tags("/nowhere/at/all.wav")
                check("and a file that is not there gives no tags, not a crash",
                      none.title == nil && none.artist == nil)
            }

            // A bed, which is a loop, should have almost no run out on it.
            if let bed = board.bankSlots(C.bankBeds).first(where: { !$0.isMissing }),
               let path = bed.filepath {
                let tail = AudioFile.tailSilence(path)
                check("a looping bed has no run out to speak of", tail < 0.5,
                      String(format: "%.3f s", tail))
            }
        } else {
            out.append("  note  the demo pack is not beside the app, so it was not checked")
        }
        out.append("")
    }
}

extension SelfTest {

    /// Drive the real transport through a real handover, with no sound card
    /// and no clock: blocks are rendered by hand to advance the voice, and
    /// tick() is called the way the timer would.
    ///
    /// This is the one behaviour that the arithmetic tests cannot prove on
    /// their own. The cue points say WHEN the handover should happen; this says
    /// that it does, that the incoming track is already at level, and that the
    /// outgoing one is riding down rather than gone.
    fileprivate func testHandover() {
        out.append("The handover between the two decks")

        let rate = 48000.0
        let frames = 512
        let group = MixerGroup(mainDeviceUID: nil, bankDevices: [:])
        // No device is opened. The mixer is rendered by hand below.
        let mixer = group.primary!
        mixer.ducking = false

        // Two four second tones written to disk, so the player opens real
        // files through the real decoder.
        let scratch = NSTemporaryDirectory() + "dropdeck-selftest"
        try? FileManager.default.createDirectory(atPath: scratch,
                                                 withIntermediateDirectories: true)
        func writeTone(_ name: String, seconds: Double, hz: Double) -> String? {
            let path = (scratch as NSString).appendingPathComponent(name)
            guard let format = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                             sampleRate: rate, channels: 2,
                                             interleaved: false)
            else { return nil }
            let settings: [String: Any] = [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: rate,
                AVNumberOfChannelsKey: 2,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
            ]
            guard let file = try? AVAudioFile(forWriting: URL(fileURLWithPath: path),
                                              settings: settings) else { return nil }
            let n = AVAudioFrameCount(seconds * rate)
            guard let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: n)
            else { return nil }
            buf.frameLength = n
            for c in 0..<2 {
                for i in 0..<Int(n) {
                    buf.floatChannelData![c][i] = Float(sin(2 * .pi * hz * Double(i) / rate)) * 0.5
                }
            }
            try? file.write(from: buf)
            return path
        }
        guard let one = writeTone("deck-one.wav", seconds: 4.0, hz: 220),
              let two = writeTone("deck-two.wav", seconds: 4.0, hz: 660) else {
            check("could write two test tones", false)
            return
        }

        let list = Playlist()
        for path in [one, two] {
            let t = Track(filepath: path)
            t.duration = 4.0
            t.tailSilence = 0.0
            list.tracks.append(t)
        }
        list.crossfade = 1.0
        let player = PlaylistPlayer(playlist: list, group: group)

        var moves: [Int] = []
        player.onMoved = { row, _ in moves.append(row) }

        check("the player starts", player.play(from: 0))
        check("and is on the first item", moves == [0], "\(moves)")

        let buf = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { buf.deallocate() }

        /// Render enough blocks to advance the voice by this many seconds,
        /// calling tick() as the timer would.
        func advance(_ seconds: Double) {
            var rendered = 0
            let want = Int(seconds * rate)
            while rendered < want {
                mixer.render(frames: frames, into: buf)
                rendered += frames
                player.tickForTesting()
            }
        }

        // The cue point is one second from the end of a four second track.
        advance(2.5)
        check("no handover before the cue point", moves == [0], "\(moves)")

        advance(1.0)
        check("the handover happens at the cue point", moves == [0, 1], "\(moves)")

        // Both decks are sounding during the overlap, which is what a crossfade
        // is, and the sum is louder than either alone. That is exactly why the
        // soft clip exists.
        mixer.render(frames: frames, into: buf)
        var peak: Float = 0
        for i in 0..<(frames * 2) { peak = max(peak, abs(buf[i])) }
        check("both decks are sounding during the overlap", peak > 0.5,
              String(format: "%.3f", peak))

        // And after the overlap only the incoming one is left.
        advance(1.5)
        check("the outgoing deck has gone by the end of the overlap",
              mixer.playingSlots.count <= 1, "\(mixer.playingSlots)")
        check("the incoming one is still playing", player.isPlaying)

        player.stop(quiet: true)
        group.stop()
        out.append("")
    }

    /// The end of track cue, which is generated rather than shipped so that
    /// every shape comes out at the same loudness.
    fileprivate func testCueTone() {
        out.append("The end of track cue")
        let rate = 48000.0
        let ceiling = 0.891251                       // minus one decibel

        for (key, _) in C.cueSounds {
            let wave = CueTone.waveform(kind: key, levelDB: C.cueLevelDB, rate: rate)
            check("\(key) generates something", !wave.isEmpty)
            var peak: Float = 0
            for v in wave { peak = max(peak, abs(v)) }
            check("\(key) never goes over minus one decibel",
                  Double(peak) <= ceiling + 0.001, String(format: "%.4f", peak))
        }

        // Matched by window RMS rather than by peak. A bell and a steady pip at
        // the same peak are not the same loudness: the bell decays, so most of
        // it is quiet, and peak matching left it about ten decibels down in
        // energy and easy to miss over a song.
        func loudestWindowRMS(_ wave: [Float]) -> Double {
            let window = max(1, Int(0.03 * rate)) * 2
            var loudest = 0.0
            var i = 0
            while i < wave.count {
                let end = min(i + window, wave.count)
                var sum = 0.0
                for j in i..<end { sum += Double(wave[j]) * Double(wave[j]) }
                loudest = max(loudest, (sum / Double(end - i)).squareRoot())
                i = end
            }
            return loudest
        }
        let pip = loudestWindowRMS(CueTone.waveform(kind: "pip", levelDB: C.cueLevelDB, rate: rate))
        let bell = loudestWindowRMS(CueTone.waveform(kind: "bell", levelDB: C.cueLevelDB, rate: rate))
        let sweep = loudestWindowRMS(CueTone.waveform(kind: "sweep", levelDB: C.cueLevelDB, rate: rate))
        let ratio = 20 * log10(max(bell, 1e-9) / max(pip, 1e-9))
        check("a bell is the same loudness as a pip, within three decibels",
              abs(ratio) < 3.0, String(format: "%.1f dB apart", ratio))
        let sweepRatio = 20 * log10(max(sweep, 1e-9) / max(pip, 1e-9))
        check("and so is a sweep",
              abs(sweepRatio) < 3.0, String(format: "%.1f dB apart", sweepRatio))

        // An unknown name falls back to the pip: a cue that does not sound is
        // worse than the wrong cue.
        check("an unknown cue falls back to the pip rather than to silence",
              !CueTone.waveform(kind: "banana", levelDB: C.cueLevelDB, rate: rate).isEmpty)

        // Quieter settings really are quieter.
        let loud = CueTone.waveform(kind: "pip", levelDB: -6, rate: rate)
        let quiet = CueTone.waveform(kind: "pip", levelDB: -20, rate: rate)
        var loudPeak: Float = 0, quietPeak: Float = 0
        for v in loud { loudPeak = max(loudPeak, abs(v)) }
        for v in quiet { quietPeak = max(quietPeak, abs(v)) }
        let apart = 20 * log10(Double(loudPeak) / Double(max(quietPeak, 1e-9)))
        check("minus twenty really is fourteen decibels under minus six",
              abs(apart - 14.0) < 1.0, String(format: "%.1f dB", apart))
        out.append("")
    }

    /// Open a real sound card. The source passing tells you nothing about
    /// whether the shipped app can make a noise, and a dead audio backend is
    /// exactly the sort of thing that only shows up in the bundle.
    ///
    /// Nothing audible is played: it opens the device, renders silence, and
    /// closes it again.
    /// The Preferences layout, built and driven with no window on screen.
    ///
    /// It replaced an NSTabView, and the failure it would have is quiet: a pane
    /// that is never put in front of you, or one with no accessibility label,
    /// looks like an empty Preferences window and says nothing about why.
    /// F1 cannot fall behind the app.
    ///
    /// Windows shipped an F1 list that went eight keys behind between 3.5.0 and
    /// 3.7.0 and still taught the wiring of a release that had been replaced.
    /// Nothing reported it, because a hand kept list is only wrong when
    /// somebody reads it. This is the check that makes "derived from the menus"
    /// a guarantee rather than an intention.
    fileprivate func testKeyboardHelp() {
        out.append("F1 says every key the app really binds")

        let help = KeyboardHelp.chapters() + KeyboardHelp.everythingElse(nil)
        var missing: [String] = []
        var bindings = 0
        for command in Command.allCases {
            guard let (key, mods) = KeyMap.menuKey(command) else { continue }
            bindings += 1
            let said = KeyMap.spell(key: key, mods: mods)
                .replacingOccurrences(of: "+", with: " ")
            if !help.contains(said) { missing.append("\(command.rawValue) on \(said)") }
        }
        check("this build binds keys at all", bindings > 20, "\(bindings)")
        check("every key this build binds is in the F1 list", missing.isEmpty,
              missing.joined(separator: "; "))

        // And the other way: a key the chapters teach that the app does not
        // bind is a sentence that sends somebody to press nothing.
        let bound = Set(KeyMap.dump().map { $0.replacingOccurrences(of: "+", with: " ") })
        check("the new keys are all taught",
              ["Command Shift R", "Command Shift C", "Command Shift W",
               "Command Shift H", "Command Shift O", "Option Shift O"]
                  .allSatisfy { bound.contains($0) && help.contains($0) })
        out.append("")
    }

    fileprivate func testSettingsLayout() {
        out.append("The Preferences layout")
        let pane = SettingsCategories()
        var made: [NSView] = []
        for name in ["Output", "Sounds and beds", "Streaming"] {
            let box = NSStackView()
            box.setAccessibilityLabel(name)
            made.append(box)
            pane.add(name, box)
        }
        check("every category is in the list", pane.labels.count == 3)
        check("the list has a row for each", pane.list.numberOfRows == 3,
              "\(pane.list.numberOfRows)")

        pane.select("Streaming")
        check("choosing a category selects its row", pane.list.selectedRow == 2,
              "\(pane.list.selectedRow)")
        check("and puts that category's settings in front",
              made[2].superview != nil && made[0].superview == nil)
        check("and the settings say which category they are",
              made[2].accessibilityLabel() == "Streaming settings",
              made[2].accessibilityLabel() ?? "none")

        pane.select("Output")
        check("choosing another swaps them over",
              made[0].superview != nil && made[2].superview == nil)
        check("a category that is not there falls back to the first",
              { pane.select("Nonsense"); return pane.list.selectedRow == 0 }())
        check("the list itself is named for a screen reader",
              pane.list.accessibilityLabel() == "Settings categories",
              pane.list.accessibilityLabel() ?? "none")
        out.append("")
    }

    /// The three things a stream can be encoded as, driven for real.
    ///
    /// Not "does the encoder exist": two seconds of a real tone through each
    /// one, and then the bytes are read the way a server would. An Ogg page
    /// with a wrong CRC is refused by every player with no useful message, and
    /// the CRC here is the Ogg variant rather than the one in zlib, so it is
    /// checked rather than trusted. Each stream is also written out beside the
    /// other scratch files so it can be opened in a player when something is
    /// argued about.
    fileprivate func testStreamEncoders() {
        out.append("The stream encoders")
        let rate = 44100.0
        guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2) else {
            check("a float format for the encoders", false)
            return
        }
        let folder = (NSTemporaryDirectory() as NSString)
            .appendingPathComponent("dropdeck-selftest")
        try? FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)

        for key in C.streamFormatKeys {
            guard let encoder = makeStreamEncoder(format: key, rate: rate, bitrate: 128) else {
                check("\(key): an encoder is made", false)
                continue
            }
            check("\(key): an encoder is made and is usable", encoder.isUsable)
            var body = Data()
            if let preamble = encoder.preamble() { body.append(preamble) }
            let preambleLength = body.count

            var phase = 0.0
            let chunk = encoder.frameSize
            var fed = 0
            while fed < Int(rate * 2) {
                guard let pcm = AVAudioPCMBuffer(pcmFormat: format,
                                                 frameCapacity: AVAudioFrameCount(chunk))
                else { break }
                pcm.frameLength = AVAudioFrameCount(chunk)
                for i in 0..<chunk {
                    let v = Float(sin(phase) * 0.3)
                    phase += 2 * Double.pi * 440 / rate
                    pcm.floatChannelData![0][i] = v
                    pcm.floatChannelData![1][i] = v
                }
                fed += chunk
                if let bytes = encoder.encode(pcm) { body.append(bytes) }
            }
            check("\(key): two seconds of tone produced bytes", body.count > preambleLength,
                  "\(body.count) bytes")
            check("\(key): no error was left behind", encoder.lastError == nil,
                  encoder.lastError ?? "")

            let bytes = [UInt8](body)
            switch key {
            case C.streamFormatAAC:
                // Every ADTS frame begins with the twelve bit sync word.
                check("aac: it starts with an ADTS sync word",
                      bytes.count > 7 && bytes[0] == 0xFF && (bytes[1] & 0xF0) == 0xF0)
                check("aac: the content type is the one a mount expects",
                      encoder.mimeType == "audio/aac")
            case C.streamFormatOpus:
                check("opus: the first page is a beginning of stream page",
                      bytes.count > 28 && Array(bytes[0..<4]) == Array("OggS".utf8)
                      && bytes[5] == 0x02)
                let head = String(decoding: bytes.prefix(64), as: UTF8.self)
                check("opus: the first packet is an OpusHead", head.contains("OpusHead"))
                check("opus: the second page is the OpusTags",
                      String(decoding: bytes.prefix(160), as: UTF8.self).contains("OpusTags"))
                check("opus: it is served as Ogg", encoder.mimeType == "audio/ogg")
                // Walk every page and check its CRC, which is the one thing
                // that cannot be eyeballed and the one thing that silently
                // breaks every player at once.
                var at = 0, pages = 0, bad = 0
                while at + 27 <= bytes.count, Array(bytes[at..<(at + 4)]) == Array("OggS".utf8) {
                    let segments = Int(bytes[at + 26])
                    guard at + 27 + segments <= bytes.count else { break }
                    var payload = 0
                    for i in 0..<segments { payload += Int(bytes[at + 27 + i]) }
                    let length = 27 + segments + payload
                    guard at + length <= bytes.count else { break }
                    var page = Array(bytes[at..<(at + length)])
                    let stated = UInt32(page[22]) | UInt32(page[23]) << 8
                                 | UInt32(page[24]) << 16 | UInt32(page[25]) << 24
                    for i in 22...25 { page[i] = 0 }
                    if OggStream.crc(page) != stated { bad += 1 }
                    pages += 1
                    at += length
                }
                check("opus: every Ogg page checksums", bad == 0, "\(bad) of \(pages) bad")
                check("opus: the pages account for every byte", at == bytes.count,
                      "stopped at \(at) of \(bytes.count)")
                check("opus: two seconds is more than a hundred pages", pages > 100, "\(pages)")
            case C.streamFormatMP3:
                // Every MPEG audio frame starts with eleven set bits. Nothing
                // wraps it, which is what makes it joinable part way through.
                check("mp3: it starts with an MPEG frame sync",
                      bytes.count > 4 && bytes[0] == 0xFF && (bytes[1] & 0xE0) == 0xE0)
                check("mp3: layer III, not I or II",
                      bytes.count > 1 && ((bytes[1] >> 1) & 0x03) == 0x01)
                check("mp3: nothing is sent before the audio", preambleLength == 0)
                check("mp3: it is served as MPEG audio", encoder.mimeType == "audio/mpeg")
            default:
                check("wav: it starts with a RIFF WAVE header",
                      bytes.count > 44 && Array(bytes[0..<4]) == Array("RIFF".utf8)
                      && Array(bytes[8..<12]) == Array("WAVE".utf8))
                check("wav: the header is the usual 44 bytes", preambleLength == 44,
                      "\(preambleLength)")
                check("wav: the sample rate in the header is the card's",
                      bytes.count > 28
                      && (UInt32(bytes[24]) | UInt32(bytes[25]) << 8
                          | UInt32(bytes[26]) << 16 | UInt32(bytes[27]) << 24) == UInt32(rate))
                check("wav: sixteen bit stereo is four bytes a frame",
                      (body.count - preambleLength) % 4 == 0)
                check("wav: it is served as WAV", encoder.mimeType == "audio/wav")
            }

            let ext = ["opus": "opus", "wav": "wav", "mp3": "mp3"][key] ?? "aac"
            let path = (folder as NSString).appendingPathComponent("stream-sample.\(ext)")
            try? body.write(to: URL(fileURLWithPath: path))
            out.append("  note  \(path)")

            // AND THEN LISTEN TO IT. Valid framing is not the same as correct
            // audio: MP3's first version of this shipped a stream that was
            // nothing but clipping, because LAME has two float entry points one
            // letter apart, one wanting plus or minus 1 and the other plus or
            // minus 32768. It framed perfectly and decoded as a perfectly good
            // MP3. Only the level says which one you fed.
            //
            // macOS decodes all of these even where it cannot encode them, so
            // the round trip costs nothing and is the only check here that
            // could tell the difference.
            if key != C.streamFormatWAV, let decoded = try? AVAudioFile(
                forReading: URL(fileURLWithPath: path)) {
                let heard = AVAudioFormat(standardFormatWithSampleRate:
                                            decoded.processingFormat.sampleRate, channels: 2)
                var peak: Float = 0
                if let heard, let block = AVAudioPCMBuffer(pcmFormat: heard,
                                                           frameCapacity: 65536) {
                    // Past the first tenth of a second, so an encoder's own
                    // start up padding is not what gets measured.
                    decoded.framePosition = AVAudioFramePosition(
                        decoded.processingFormat.sampleRate * 0.2)
                    if (try? decoded.read(into: block)) != nil,
                       let channels = block.floatChannelData {
                        for i in 0..<Int(block.frameLength) {
                            peak = max(peak, abs(channels[0][i]))
                        }
                    }
                }
                // The tone went in at 0.3. A lossy encoder overshoots a pure
                // sine by a little; 32768 times too loud is the failure this
                // is here for, and so is silence.
                check("\(key): it decodes back at the level it went in at",
                      peak > 0.15 && peak < 0.9, String(format: "peak %.3f", peak))
            }
        }
        out.append("")
    }

    fileprivate func testRealDevice() {
        out.append("The sound card, opened for real")

        let outputs = AudioDevices.outputs()
        check("this Mac has an output device", !outputs.isEmpty,
              "\(outputs.count) found")
        for d in outputs.prefix(4) {
            out.append("  note  \(d.name), \(d.outputChannels) out, "
                       + "\(Int(AudioDevices.nominalRate(d.id) ?? 0)) Hz")
        }
        check("there is a default output", AudioDevices.defaultOutput() != nil)

        let group = MixerGroup(mainDeviceUID: nil, bankDevices: [:])
        group.start()
        check("the mixer opens the default output",
              group.isRunning, group.lastError ?? "no reason given")
        if group.isRunning {
            check("and reports a sensible sample rate",
                  group.sampleRate >= 8000 && group.sampleRate <= 192000,
                  "\(group.sampleRate)")
            // Let a few real callbacks run, with nothing playing, so a crash in
            // the render path shows up here rather than on the first keypress.
            Thread.sleep(forTimeInterval: 0.25)
            check("and survives a quarter second of real callbacks", group.isRunning)
        }
        group.stop()
        out.append("")
    }
}

/// A small box so an array of modifier sets can be built in a test without
/// fighting the type checker.
struct NSEventModifierFlagsBox {
    let value: NSEvent.ModifierFlags
    init(_ v: NSEvent.ModifierFlags) { value = v }
}
