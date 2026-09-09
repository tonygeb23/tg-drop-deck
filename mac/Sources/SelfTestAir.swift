// Checks for the capture and broadcast half: the programme bus, the voice
// chain, the encoder, the recorder and the hotkeys.
//
// Same rule as the rest of the suite. Every number is asserted against the
// constant rather than a copy of it, and anything that can be proved without a
// sound card is proved without one.

import Foundation
import AVFoundation
import AudioToolbox
import Carbon.HIToolbox

extension SelfTest {

    func runAirChecks() {
        testAirBus()
        testDSPChain()
        testCeiling()
        testEncoder()
        testMicOnAir()
        testRecorder()
        testHotkeys()
        testAirBoard()
    }

    // ------------------------------------------------------ the programme bus ---

    fileprivate func testAirBus() {
        out.append("The programme bus, which is the sum of every sound card")

        let rate = 48000.0
        let bus = AirBus(sampleRate: rate)
        let frames = 512
        let block = [Float](repeating: 0.25, count: frames * 2)
        let readBuf = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { readBuf.deallocate() }

        check("an empty bus offers nothing", bus.available() == 0)

        block.withUnsafeBufferPointer { p in
            bus.write(key: "main", samples: p.baseAddress!, frames: frames, rate: rate)
        }
        check("one card's block is there to read", bus.available() == frames,
              "\(bus.available())")

        bus.read(frames: frames, into: readBuf)
        check("and reads back at the level it went in",
              near(Double(readBuf[0]), 0.25, 0.001), "\(readBuf[0])")
        check("reading takes it away", bus.available() == 0)

        // Two cards are SUMMED, which is the whole point: a drop sent to a
        // separate card is still part of the show.
        block.withUnsafeBufferPointer { p in
            bus.write(key: "main", samples: p.baseAddress!, frames: frames, rate: rate)
            bus.write(key: "second", samples: p.baseAddress!, frames: frames, rate: rate)
        }
        bus.read(frames: frames, into: readBuf)
        check("two cards are summed, not chosen between",
              near(Double(readBuf[0]), 0.5, 0.001), "\(readBuf[0])")

        // A card at a different RATE is converted rather than absorbed. Drift
        // is a few milliseconds an hour; a rate mismatch is four thousand
        // frames a minute and would drain the ring dry.
        let slow = AirBus(sampleRate: 48000)
        let atFortyFour = [Float](repeating: 0.5, count: 441 * 2)
        atFortyFour.withUnsafeBufferPointer { p in
            slow.write(key: "card", samples: p.baseAddress!, frames: 441, rate: 44100)
        }
        let produced = slow.available()
        check("a card at 44100 is converted up to the bus rate",
              produced >= 470 && produced <= 490, "\(produced) frames from 441")

        // A ring nobody has written to for a while stops holding the stream up,
        // or an unplugged card would pin it at zero for ever.
        let patient = AirBus(sampleRate: rate, seconds: 0.05)
        block.withUnsafeBufferPointer { p in
            patient.write(key: "alive", samples: p.baseAddress!, frames: 64, rate: rate)
            patient.write(key: "gone", samples: p.baseAddress!, frames: 64, rate: rate)
        }
        patient.read(frames: 64, into: readBuf)
        check("both rings drain together", patient.available() == 0)
        block.withUnsafeBufferPointer { p in
            patient.write(key: "alive", samples: p.baseAddress!, frames: 64, rate: rate)
        }
        Thread.sleep(forTimeInterval: 0.12)
        check("a card that has gone quiet stops holding the stream up",
              patient.available() == 64, "\(patient.available())")
        out.append("")
    }

    // --------------------------------------------------------- the voice chain ---

    fileprivate func testDSPChain() {
        out.append("The voice chain")

        let rate = 48000.0
        let chain = MicChain()
        chain.prepare(rate: rate)

        check("every parameter has a real unit and a range",
              MicChain.parameters.allSatisfy { $0.maximum > $0.minimum })
        check("and a default inside that range",
              MicChain.parameters.allSatisfy { p in
                  let d = MicChain.defaults[p.key] ?? Double.nan
                  return d >= p.minimum && d <= p.maximum
              })
        check("a value is clamped rather than trusted", {
            chain.set("comp_ratio", 999)
            return chain.value("comp_ratio") == 20
        }())
        chain.set("comp_ratio", 3)

        // Spoken form: a real unit, not a bare number. This is the whole reason
        // a chain nobody can see is usable.
        let ratio = MicChain.parameter("comp_ratio")!
        check("a ratio is said as a ratio",
              ratio.spoken(4) == "Compression ratio, 4.0 to 1", ratio.spoken(4))
        let hz = MicChain.parameter("eq_mid_hz")!
        check("a high frequency is said in kilohertz",
              hz.spoken(1800) == "Middle at, 1.8 kilohertz", hz.spoken(1800))
        let sw = MicChain.parameter("gate_on")!
        check("a switch is said as off or on", sw.spoken(1) == "Noise gate, on", sw.spoken(1))

        let frames = 4096
        let buf = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { buf.deallocate() }

        func fill(_ amplitude: Float, hz: Double = 220) {
            for i in 0..<frames {
                let v = amplitude * Float(sin(2 * .pi * hz * Double(i) / rate))
                buf[i * 2] = v
                buf[i * 2 + 1] = v
            }
        }
        /// The peak of the SECOND HALF of the block. The first half carries
        /// the filter's transient and the envelope follower still settling,
        /// and measuring that would be measuring the start of a sound rather
        /// than what the chain does to a steady one.
        func peak() -> Float {
            var p: Float = 0
            for i in (frames)..<(frames * 2) { p = max(p, abs(buf[i])) }
            return p
        }

        /// Feed the chain a continuous tone: a fresh block each time, the way
        /// a microphone really delivers them. Processing the SAME buffer twice
        /// would put the chain's own output back into it, which compresses and
        /// filters compound and measures nothing real.
        func run(_ blocks: Int, _ amplitude: Float, _ hz: Double = 220) {
            for _ in 0..<blocks {
                fill(amplitude, hz: hz)
                chain.process(buf, frames: frames)
            }
        }

        // The gate closes on something well under its threshold and stays open
        // on a real voice level.
        chain.settings = MicChain.defaults
        chain.set("comp_on", 0)
        chain.set("eq_on", 0)
        chain.set("highpass_on", 0)
        chain.set("limit_on", 0)
        run(8, 0.0005)                                 // about minus 66 dB
        check("the gate closes on room noise", peak() < 0.0004,
              String(format: "%.6f", peak()))

        chain.prepare(rate: rate)
        chain.settings = MicChain.defaults
        chain.set("comp_on", 0); chain.set("eq_on", 0)
        chain.set("highpass_on", 0); chain.set("limit_on", 0)
        run(8, 0.3)                                    // a real voice
        check("and stays open on a voice", peak() > 0.25, String(format: "%.3f", peak()))

        // The high pass really removes low frequencies and leaves high ones.
        chain.prepare(rate: rate)
        chain.settings = MicChain.defaults
        chain.set("gate_on", 0); chain.set("comp_on", 0)
        chain.set("eq_on", 0); chain.set("limit_on", 0)
        chain.set("highpass_hz", 200)
        run(6, 0.5, 40)
        let lowAfter = peak()
        chain.prepare(rate: rate)
        run(6, 0.5, 4000)
        let highAfter = peak()
        check("the high pass takes rumble out", lowAfter < 0.15,
              String(format: "%.3f at 40 Hz", lowAfter))
        check("and leaves the voice alone", highAfter > 0.45,
              String(format: "%.3f at 4 kHz", highAfter))

        // The compressor really compresses, by about the ratio it claims.
        chain.prepare(rate: rate)
        chain.settings = MicChain.defaults
        chain.set("gate_on", 0); chain.set("eq_on", 0)
        chain.set("highpass_on", 0); chain.set("limit_on", 0)
        chain.set("comp_threshold", -20)
        chain.set("comp_ratio", 4)
        chain.set("comp_makeup", 0)
        chain.set("comp_attack", 1)
        run(16, 0.5)                                   // about minus 6 dB
        let compressed = 20 * log10(Double(peak()))
        // Minus 6 in, threshold minus 20, four to one: 14 dB over becomes 3.5,
        // so about minus 16.5 out.
        check("four to one really is about four to one",
              compressed < -13 && compressed > -20,
              String(format: "%.1f dB out for %.1f dB in", compressed, -6.0))
        out.append("")
    }

    fileprivate func testCeiling() {
        out.append("The ceiling, which has to be a promise")

        let rate = 48000.0
        let ceiling = Ceiling()
        ceiling.ceilingDB = -1.0
        ceiling.releaseMS = 100
        ceiling.prepare(rate: rate)

        let frames = 4096
        let buf = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { buf.deallocate() }

        // Full scale in, and the promise is minus one out.
        for i in 0..<frames {
            let v = Float(sin(2 * .pi * 440 * Double(i) / rate))
            buf[i * 2] = v
            buf[i * 2 + 1] = v
        }
        ceiling.process(buf, frames: frames)
        var peak: Float = 0
        for i in 0..<(frames * 2) { peak = max(peak, abs(buf[i])) }
        let wanted = Float(pow(10.0, -1.0 / 20.0))
        check("full scale in comes out at the ceiling and not above it",
              peak <= wanted + 0.001, String(format: "%.4f, ceiling %.4f", peak, wanted))

        // Below the ceiling nothing happens at all, which is what makes it a
        // ceiling rather than a loudness maximiser. Apple's own PeakLimiter has
        // no threshold and would have turned this UP.
        ceiling.prepare(rate: rate)
        for i in 0..<frames {
            let v = 0.2 * Float(sin(2 * .pi * 440 * Double(i) / rate))
            buf[i * 2] = v
            buf[i * 2 + 1] = v
        }
        ceiling.process(buf, frames: frames)
        peak = 0
        for i in 0..<(frames * 2) { peak = max(peak, abs(buf[i])) }
        check("quiet audio is left exactly where it was",
              near(Double(peak), 0.2, 0.002), String(format: "%.4f", peak))

        // Both channels get the same gain, or the image would wander under a
        // loud syllable.
        ceiling.prepare(rate: rate)
        for i in 0..<frames {
            buf[i * 2] = 1.5
            buf[i * 2 + 1] = 0.1
        }
        ceiling.process(buf, frames: frames)
        let ratioL = Double(buf[0]) / 1.5
        let ratioR = Double(buf[1]) / 0.1
        check("both channels are moved by the same amount",
              near(ratioL, ratioR, 0.001),
              String(format: "%.4f against %.4f", ratioL, ratioR))
        out.append("")
    }

    // ---------------------------------------------------------------- encoder ---

    fileprivate func testEncoder() {
        out.append("The encoder")

        let rate = 48000.0
        guard let encoder = AACEncoder(rate: rate, bitrate: 128) else {
            check("an AAC encoder can be made", false)
            return
        }
        check("an AAC encoder can be made", true)
        check("and this rate can be signalled in ADTS", encoder.isUsable)

        guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2),
              let pcm = AVAudioPCMBuffer(pcmFormat: format,
                                         frameCapacity: AVAudioFrameCount(AACEncoder.frameSize))
        else {
            check("a buffer can be made", false)
            return
        }
        pcm.frameLength = AVAudioFrameCount(AACEncoder.frameSize)
        for c in 0..<2 {
            for i in 0..<AACEncoder.frameSize {
                pcm.floatChannelData![c][i] = Float(sin(2 * .pi * 440 * Double(i) / rate)) * 0.5
            }
        }
        // The encoder primes on the first buffers, so it is fed until it speaks.
        var data: Data?
        for _ in 0..<8 {
            if let d = encoder.encode(pcm), !d.isEmpty { data = d; break }
        }
        guard let data else {
            check("it produces AAC", false, encoder.lastError ?? "nothing came out")
            return
        }
        check("it produces AAC", true)

        // The ADTS header is what makes the stream joinable part way through,
        // so it is checked byte by byte rather than assumed.
        let bytes = [UInt8](data)
        check("every frame starts with an ADTS sync word",
              bytes.count > 7 && bytes[0] == 0xFF && (bytes[1] & 0xF0) == 0xF0,
              String(format: "%02X %02X", bytes[0], bytes[1]))
        let index = (bytes[2] >> 2) & 0x0F
        check("and names 48000 as its rate", index == 3, "index \(index)")
        let channels = ((bytes[2] & 0x01) << 2) | ((bytes[3] >> 6) & 0x03)
        check("and says it is stereo", channels == 2, "\(channels)")
        let length = (Int(bytes[3] & 0x03) << 11) | (Int(bytes[4]) << 3)
                   | ((Int(bytes[5]) >> 5) & 0x07)
        check("and its frame length matches the bytes that follow",
              length > 7 && length <= bytes.count, "\(length) of \(bytes.count)")

        // A rate ADTS cannot name has to be refused rather than mislabelled.
        let odd = AACEncoder(rate: 47000, bitrate: 128)
        check("a rate ADTS cannot name is refused", odd?.isUsable != true)

        // Throughput, against NOISE rather than a tone. A sine is almost
        // free to encode and would let a broken bit rate look fine: measuring
        // with one is measuring nothing.
        guard let steady = AACEncoder(rate: rate, bitrate: 128) else { return }
        var produced = 0
        var frames = 0
        var seed: UInt64 = 0x2545F4914F6CDD1D
        for _ in 0..<Int(rate) / AACEncoder.frameSize {
            for c in 0..<2 {
                for i in 0..<AACEncoder.frameSize {
                    // A cheap deterministic noise source, so the number this
                    // check asserts is the same on every run.
                    seed ^= seed << 13; seed ^= seed >> 7; seed ^= seed << 17
                    let v = Float(Int32(truncatingIfNeeded: seed)) / Float(Int32.max)
                    pcm.floatChannelData![c][i] = v * 0.4
                }
            }
            frames += AACEncoder.frameSize
            if let d = steady.encode(pcm) { produced += d.count }
        }
        let seconds = Double(frames) / rate
        let kbps = Double(produced) * 8.0 / seconds / 1000.0
        check("a second of noise really comes out near the bit rate asked for",
              kbps > 90 && kbps < 170, String(format: "%.0f kbps for 128 asked", kbps))
        out.append("")
    }

    /// The switch that keeps your voice out of the programme, and the warning
    /// that now exists because nothing said a word about it.
    fileprivate func testMicOnAir() {
        out.append("The microphone reaching the air")

        let board = Board()
        check("a new board puts the microphone on the air", board.stream.sendMic)
        check("and so does a board file that never mentioned it",
              Board.from(dict: [:], relativeTo: nil).stream.sendMic)
        var off = board.toDict()
        off["stream_mic"] = false
        check("a board that says otherwise is believed",
              !Board.from(dict: off, relativeTo: nil).stream.sendMic)

        // It gates the PROGRAMME sum, which the recorder reads as well as the
        // stream, so the label on the Streaming tab was only half the story.
        let group = SourceGroup()
        let mic = MicInput(duckBus: DuckBus())
        group.mic = mic
        mic.onAir = false
        var block = [Float](repeating: 0, count: 512)
        block.withUnsafeMutableBufferPointer { p in
            group.read(frames: 256, into: p.baseAddress!)
        }
        check("a microphone that is not on air adds nothing to the programme",
              block.allSatisfy { $0 == 0 })
        out.append("")
    }

    // --------------------------------------------------------------- recorder ---

    fileprivate func testRecorder() {
        out.append("Recording")

        // MP3 is offered from 3.3.1 and does not come from macOS, which still
        // has no MP3 encoder anywhere. It comes from the LAME inside the
        // bundle, so the check that matters is that the library is really
        // there and really answers, not that the key is in a list.
        check("MP3 is offered", C.recordFormatKeys.contains("mp3"))
        check("and there is a working encoder behind it",
              MP3Encoder(rate: 44100, bitrate: 128, forFile: true)?.isUsable == true)
        check("Ogg Opus is not, because a recording has to be right at the end",
              !C.recordFormatKeys.contains("opus"))
        check("WAV, MP3, AAC and FLAC are the four",
              C.recordFormatKeys == ["wav", "mp3", "aac", "flac"])
        check("an MP3 recording is named .mp3", Recorder.fileExtension(for: "mp3") == ".mp3")

        let scratch = NSTemporaryDirectory() + "dropdeck-selftest-rec"
        try? FileManager.default.removeItem(atPath: scratch)
        try? FileManager.default.createDirectory(atPath: scratch,
                                                 withIntermediateDirectories: true)

        // The name counts up by scanning the folder, so deleting last week's
        // recordings does not start it over the top of anything.
        let first = Recorder.nextPath(folder: scratch, format: "wav")
        check("the first recording is numbered 001",
              (first as NSString).lastPathComponent == "Drop Deck Stream 001.wav",
              (first as NSString).lastPathComponent)
        FileManager.default.createFile(atPath: first, contents: Data())
        FileManager.default.createFile(
            atPath: (scratch as NSString).appendingPathComponent("Drop Deck Stream 007.wav"),
            contents: Data())
        let next = Recorder.nextPath(folder: scratch, format: "wav")
        check("and the next one carries on from the highest there",
              (next as NSString).lastPathComponent == "Drop Deck Stream 008.wav",
              (next as NSString).lastPathComponent)
        check("AAC goes in an m4a", Recorder.fileExtension(for: "aac") == ".m4a")

        // A real recording, through the real bus, with no sound card.
        //
        // MP3 goes through this too, and it has to: it is the one format that
        // does not use AVAudioFile at all. It is LAME, a file handle, a flush
        // at the end and then the Info tag written back over the placeholder
        // at offset zero, and getting that seek wrong makes a file whose first
        // frame is rubbish.
        try? FileManager.default.removeItem(atPath: first)
        for format in ["wav", "mp3"] {
            let rate = 48000.0
            let taps = Taps()
            let recorder = Recorder()
            guard let path = recorder.start(taps: taps, rate: rate, format: format,
                                            bitrate: 192, folder: scratch) else {
                check("\(format): a recording starts", false,
                      recorder.lastError ?? "no reason given")
                continue
            }
            check("\(format): a recording starts", true)

            let frames = 1024
            let block = [Float](repeating: 0.3, count: frames * 2)
            // Half a second of programme, written the way a mixer would write it.
            block.withUnsafeBufferPointer { p in
                for _ in 0..<24 {
                    taps.write(key: "main", samples: p.baseAddress!, frames: frames, rate: rate)
                    Thread.sleep(forTimeInterval: 0.01)
                }
            }
            Thread.sleep(forTimeInterval: 0.3)
            let summary = recorder.stop(taps: taps)
            check("\(format): and stops with something to say about it",
                  summary != nil, summary ?? "nil")
            check("\(format): the file is really there",
                  FileManager.default.fileExists(atPath: path))

            guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path)) else {
                check("\(format): and opens as audio", false)
                continue
            }
            let seconds = Double(file.length) / file.fileFormat.sampleRate
            // MP3 carries the encoder's own padding at each end, so it is
            // allowed to be a little longer than the audio that went in.
            check("\(format): and holds about the audio it was given",
                  seconds > 0.3 && seconds < 1.0, String(format: "%.2f s", seconds))

            // And it is really the audio, at the level it was given. This is
            // the check that catches an encoder fed the wrong float scale.
            var peak: Float = 0
            if let heard = AVAudioFormat(standardFormatWithSampleRate:
                                            file.processingFormat.sampleRate, channels: 2),
               let buffer = AVAudioPCMBuffer(pcmFormat: heard, frameCapacity: 65536) {
                file.framePosition = AVAudioFramePosition(file.processingFormat.sampleRate * 0.2)
                if (try? file.read(into: buffer)) != nil, let channels = buffer.floatChannelData {
                    for i in 0..<Int(buffer.frameLength) { peak = max(peak, abs(channels[0][i])) }
                }
            }
            check("\(format): and it decodes back near the 0.3 it was given",
                  peak > 0.15 && peak < 0.9, String(format: "peak %.3f", peak))
        }
        try? FileManager.default.removeItem(atPath: scratch)
        out.append("")
    }

    // --------------------------------------------------------------- hotkeys ---

    fileprivate func testHotkeys() {
        out.append("Hotkeys, which always need a modifier")

        // A bare key would be taken away from every other program on the Mac.
        check("a bare key is refused", HotkeyCombination.parse("F9") == nil)
        check("and so is a bare letter", HotkeyCombination.parse("A") == nil)

        guard let combination = HotkeyCombination.parse("Ctrl+Opt+F9") else {
            check("a real combination parses", false)
            return
        }
        check("a real combination parses", true)
        check("it round trips through its own label",
              HotkeyCombination.parse(combination.label) == combination, combination.label)
        check("and is said out loud in words",
              combination.spoken == "Control Option F9", combination.spoken)

        check("the Windows spelling of the Windows key is understood",
              HotkeyCombination.parse("Win+Shift+K") != nil)
        check("Alt is understood as Option",
              HotkeyCombination.parse("Alt+K") == HotkeyCombination.parse("Opt+K"))
        check("nonsense is refused rather than guessed at",
              HotkeyCombination.parse("Ctrl+Banana") == nil)

        let cmd = HotkeyCombination(keyCode: UInt32(kVK_ANSI_K), modifiers: UInt32(cmdKey))
        check("a Command combination labels itself the Mac way",
              cmd.label == "Cmd+K", cmd.label)
        out.append("")
    }

    // ------------------------------------------------------ the board, again ---

    fileprivate func testAirBoard() {
        out.append("The board remembers the air side too")

        let board = Board()
        board.micGainDB = 6
        board.micMonitor = true
        board.micChannel = .left
        board.voiceOn = false
        board.voiceSettings["comp_ratio"] = 5
        board.stream.host = "radio.example.com"
        board.stream.port = 8010
        board.stream.password = "secret"
        board.stream.bitrate = 192
        board.globalHotkeysOn = true
        board.playlistMonitorOnly = false
        var source = SourceConfig()
        source.name = "VoiceOver"
        source.kind = "process"
        source.bundleID = "com.apple.VoiceOver"
        source.onAir = true
        board.sources = [source]

        let again = Board.from(dict: board.toDict(), relativeTo: nil)
        check("the microphone gain survives", again.micGainDB == 6)
        check("monitoring survives", again.micMonitor)
        check("the channel choice survives", again.micChannel == .left)
        check("the processing switch survives", again.voiceOn == false)
        check("a voice setting survives", again.voiceSettings["comp_ratio"] == 5)
        check("the server survives", again.stream.host == "radio.example.com")
        check("the port survives", again.stream.port == 8010)
        check("the password survives", again.stream.password == "secret")
        check("the bit rate survives", again.stream.bitrate == 192)
        check("the global hotkey switch survives", again.globalHotkeysOn)
        check("the monitor fader choice survives", again.playlistMonitorOnly == false)
        check("a process source survives whole",
              again.sources.count == 1
              && again.sources[0].bundleID == "com.apple.VoiceOver"
              && again.sources[0].isProcess)

        // ---- THE TAP IS REALLY MADE ----------------------------------------
        //
        // The fault this guards against shipped, and it was invisible from
        // every direction. `AudioHardwareCreateProcessTap` was handed a plain
        // `CATapDescription()` with the bundle id set afterwards. It answered
        // noErr and returned tap object 0. Nothing threw, nothing logged, the
        // source reported itself on the air, the level meters were quiet
        // because there was no sound to show, and two sources went out as
        // silence for a whole broadcast.
        //
        // So the check is not that the description has the right fields on it.
        // It is that Core Audio, on this machine, hands back a real tap for
        // it. Nothing less would have caught this: every field was correct.
        if #available(macOS 14.2, *), Permissions.state(.screen) == .allowed {
            let me = Bundle.main.bundleIdentifier ?? "app.tgstudios.dropdeck"
            let ids: [AudioObjectID] = (AudioProcesses.find(bundleID: me)?.objectID)
                .flatMap { $0 == 0 ? nil : [$0] } ?? []
            let description = ProcessSource.describeTap(
                bundle: me, sourceName: "self test", processes: ids)
            var tap: AudioObjectID = 0
            let status = AudioHardwareCreateProcessTap(description, &tap)
            check("a process tap is really made, not just asked for",
                  status == noErr && tap != 0)
            if tap != 0 { AudioHardwareDestroyProcessTap(tap) }

            // And the shape that shipped is still refused, so if a future
            // macOS starts accepting it this check says so rather than the
            // knowledge quietly going stale.
            let plain = CATapDescription()
            if #available(macOS 26.0, *) { plain.bundleIDs = [me] }
            plain.isPrivate = true
            var noTap: AudioObjectID = 0
            _ = AudioHardwareCreateProcessTap(plain, &noTap)
            check("the plain description is still the one that gives nothing",
                  noTap == 0)
            if noTap != 0 { AudioHardwareDestroyProcessTap(noTap) }
        }

        // A source that is wanted but did not start has to be findable, since
        // nothing else in the app was looking and that is how two silent
        // sources reached the air.
        // A device that is not there, rather than a program that is not
        // running: from macOS 26 a tap can legitimately be made for a program
        // before it starts, and waits for it, so that is not a failure to
        // report. A cable that is not plugged in always is.
        var wanted = SourceConfig()
        wanted.name = "not a real device"
        wanted.kind = "device"
        wanted.deviceUID = "no such device, this is the self test"
        wanted.onAir = true
        let troubleGroup = SourceGroup()
        let trouble = troubleGroup.replace(with: [wanted], outputRate: C.defaultSampleRate)
        check("a source whose device is gone would not open", trouble.count == 1)
        check("and it is named, with a reason",
              trouble.first?.hasPrefix("not a real device: ") == true
              && trouble.first?.hasSuffix("is not plugged in") == true)
        check("and the group agrees it is in trouble", troubleGroup.trouble.count == 1)

        func troubleGroup2() -> SourceGroup {
            let g = SourceGroup()
            g.replace(with: [wanted], outputRate: C.defaultSampleRate)
            return g
        }

        // What Help, Check my audio sources says about that same source. The
        // words matter as much as the fact: this is read aloud, and "NOT on
        // the air" has to be the part that lands.
        let second = troubleGroup2()
        let findings = SourceHealth.read(SourceHealth.look(at: second), running: [:])
        defer { second.stopAll(); troubleGroup.stopAll() }
        check("the check says a source that would not open is not on the air",
              findings.count == 1 && findings[0].good == false
              && findings[0].line.contains("NOT on the air"))
        check("and the report counts it",
              SourceHealth.report(findings, micOnAir: true, micOpen: true)
                  .contains("1 of your 1 other sources needs attention"))
        check("and says when the microphone is open but not going out",
              SourceHealth.report([], micOnAir: false, micOpen: true)
                  .contains("it is NOT going out"))

        // ---- A CAPTURED PROGRAM STAYS IN STEREO ---------------------------
        //
        // The board's channel setting is for a device: a microphone on one leg
        // of a stereo interface has to be mixed or picked. It was being applied
        // to captured programs too, and its default is "both, mixed together",
        // so **every program went out in mono** while the panel would not let
        // you change it, because the popup is disabled for a program. Reported
        // by Tony: Logic Pro arrived on YouTube in mono. Windows keeps program
        // captures in stereo, though by accident: its channel only ever
        // reaches a device input.
        var stereoWanted = SourceConfig()
        stereoWanted.kind = "process"
        stereoWanted.channel = .mix
        check("a captured program is kept in stereo whatever the board says",
              ProcessSource(config: stereoWanted).foldChannel == .stereo)
        var deviceWanted = stereoWanted
        deviceWanted.kind = "device"
        check("and a device still does what the board says",
              DeviceSource(config: deviceWanted).foldChannel == .mix)

        // The fold itself, on known numbers.
        let two: [Float] = [1.0, -0.5, 0.25, -0.75]     // 2 frames, L R L R
        var folded = [Float](repeating: 0, count: 4)
        _ = two.withUnsafeBufferPointer { input in
            folded.withUnsafeMutableBufferPointer { output in
                foldToStereo(input.baseAddress!, frames: 2, channels: 2,
                             channel: .stereo, gain: 1, into: output.baseAddress!)
            }
        }
        check("stereo keeps the two channels apart",
              folded == [1.0, -0.5, 0.25, -0.75])
        _ = two.withUnsafeBufferPointer { input in
            folded.withUnsafeMutableBufferPointer { output in
                foldToStereo(input.baseAddress!, frames: 2, channels: 2,
                             channel: .mix, gain: 1, into: output.baseAddress!)
            }
        }
        check("mixed puts the average in both", folded == [0.25, 0.25, -0.25, -0.25])

        // More than two channels in, which an aggregate clocked by a multi
        // channel interface hands over. Stepping by two would read frame two's
        // first channel as frame one's right.
        let four: [Float] = [1.0, -1.0, 0.5, 0.5,       // frame 1, four channels
                             0.2, -0.2, 0.0, 0.0]       // frame 2
        _ = four.withUnsafeBufferPointer { input in
            folded.withUnsafeMutableBufferPointer { output in
                foldToStereo(input.baseAddress!, frames: 2, channels: 4,
                             channel: .stereo, gain: 1, into: output.baseAddress!)
            }
        }
        check("four channels in gives the first two out, frame by frame",
              folded == [1.0, -1.0, 0.2, -0.2])

        // A tap made for a program that is not running is healthy AND silent,
        // which is a combination nothing else in the app can tell apart.
        var absent = SourceConfig()
        absent.name = "a program nobody is running"
        absent.kind = "process"
        absent.bundleID = "com.example.definitely.not.running"
        absent.onAir = true
        let absentGroup = SourceGroup()
        absentGroup.replace(with: [absent], outputRate: C.defaultSampleRate)
        if absentGroup.all.first?.isRunning == true {
            check("a capture waiting for a program that is not running is flagged",
                  absentGroup.waitingForAProgram.count == 1)
            check("and it names the program",
                  absentGroup.waitingForAProgram.first?.contains("running") == true)
        }
        absentGroup.stopAll()

        // A source that is not wanted is not trouble. A laptop that moves
        // between desks has sources switched off on purpose and they must not
        // turn into a warning in front of a show.
        var off = wanted
        off.onAir = false
        off.monitor = false
        let quietGroup = SourceGroup()
        check("a source nobody asked for is not reported",
              quietGroup.replace(with: [off], outputRate: C.defaultSampleRate).isEmpty)
        quietGroup.stopAll()

        // NOTHING opens a microphone except a keypress. A board carries the
        // device and the gain and deliberately does not carry "it was on".
        check("a board never says the microphone was on",
              board.toDict()["mic_open"] == nil && board.toDict()["mic_on"] == nil)

        // A board written on Windows names a format this build cannot send.
        // Since 3.3.1 an MP3 station from Windows is simply an MP3 station
        // here. It used to be moved to something the Mac could send, and a
        // board that came back the other way had quietly changed format.
        var windows = board.toDict()
        windows["stream_format"] = "mp3"
        windows["record_format"] = "mp3"
        let migrated = Board.from(dict: windows, relativeTo: nil)
        check("a Windows MP3 station stays MP3 on the Mac",
              migrated.stream.format == "mp3", migrated.stream.format)
        check("and so does a Windows MP3 recording setting",
              migrated.recordFormat == "mp3", migrated.recordFormat)
        // Vorbis is the one that still has to move: macOS has no Vorbis
        // encoder either, and Opus is the Ogg stream it can make.
        windows["stream_format"] = "ogg"
        let vorbis = Board.from(dict: windows, relativeTo: nil)
        check("a Windows Ogg station becomes Ogg Opus",
              vorbis.stream.format == C.streamFormatOpus, vorbis.stream.format)
        out.append("")
    }
}
