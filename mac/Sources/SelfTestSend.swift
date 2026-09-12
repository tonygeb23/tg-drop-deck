// Checks for 3.7.1: the send, mix minus, holding a source back, the monitor
// that carries every card, the track list and the picture recorder.
//
// Same rule as the rest of the suite. Every number is asserted against the
// constant rather than a copy of it, and anything that can be proved without a
// sound card is proved without one, which here is nearly all of it.

import Foundation
import AVFoundation

extension SelfTest {

    func runSendChecks() {
        testDelayLine()
        testMixMinus()
        testSendMix()
        testSendReporting()
        testMonitorEverything()
        testCueFileOnDisk()
        testVideoRecorderClock()
        testBoardCarriesEverything()
        testVirtualDevice()
    }

    // ------------------------------------------------------------- the cable ---

    fileprivate func testVirtualDevice() {
        out.append("Drop Deck Audio, the cable that ships inside the app")

        // The bundle really is in this build. A release that quietly lost it
        // would offer to install something that is not there, and the only
        // sign would be a password box followed by a failure.
        let bundled = VirtualDevice.bundled
        check("the cable is inside the app", bundled != nil,
              bundled ?? "not in Resources")
        if let bundled {
            let binary = bundled + "/Contents/MacOS/DropDeckAudio"
            check("and it has a binary in it",
                  FileManager.default.isExecutableFile(atPath: binary))
            check("it says which version it is", VirtualDevice.bundledVersion != nil,
                  VirtualDevice.bundledVersion ?? "none")
            // Two channels EXACTLY. Zoom sums any input with more than two
            // channels to mono whatever its stereo setting says, so a cable
            // with more would arrive in a call as one ear of the show.
            if let source = try? String(
                contentsOfFile: bundled + "/Contents/Info.plist", encoding: .utf8) {
                check("it is a plug-in bundle and not a type of its own",
                      source.contains("<string>BNDL</string>"))
                check("and it names the audio server plug-in type",
                      source.contains("443ABAB8-E7B3-491A-B985-BEB9187030DB"))
            }
        }

        // The UID is what a board stores. Changing it once it has shipped is
        // every user's send silently pointing at nothing.
        check("the device UID is the one a board stores",
              VirtualDevice.uid == "TGStudios:DropDeckAudio:1")
        check("it goes where Core Audio looks for one",
              VirtualDevice.installedPath
                  == "/Library/Audio/Plug-Ins/HAL/Drop Deck Audio.driver")

        // Whatever state this machine is in, the app has a sentence for it and
        // the sentence is not empty.
        check("it can say where things stand", !VirtualDevice.describe().isEmpty)
        check("and the warning says the restart takes VoiceOver with it",
              VirtualDevice.warning.contains("VOICEOVER WILL GO QUIET"))
        check("an uninstall with nothing installed is not a failure",
              VirtualDevice.isInstalled || {
                  if case .done = VirtualDevice.uninstall(restartAudio: false) { return true }
                  return false
              }())
        if VirtualDevice.isPresent {
            out.append("  note  the cable is installed on this machine")
        } else {
            out.append("  note  the cable is not installed on this machine")
        }
        out.append("")
    }

    // ----------------------------------------------------- holding one back ---

    fileprivate func testDelayLine() {
        out.append("Holding a source back")

        let line = DelayLine()
        let frames = 8
        let block = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { block.deallocate() }

        // Zero costs nothing at all: the block comes back exactly as it went in.
        line.set(frames: 0)
        for i in 0..<(frames * 2) { block[i] = Float(i + 1) }
        line.feed(block, frames: frames)
        check("a delay of nothing hands the block straight back",
              block[0] == 1 && block[frames * 2 - 1] == Float(frames * 2))

        // Three frames of delay: the first three frames out are silence, and
        // what went in comes back three frames later.
        line.set(frames: 3)
        check("the line holds the frames it was told to", line.heldFrames == 3)
        for i in 0..<(frames * 2) { block[i] = Float(i + 1) }
        line.feed(block, frames: frames)
        check("the first frames out are silence",
              block[0] == 0 && block[1] == 0 && block[4] == 0 && block[5] == 0)
        check("and the audio arrives exactly that many frames later",
              block[6] == 1 && block[7] == 2, "\(block[6]), \(block[7])")
        check("both ears are held by the same amount",
              block[8] == 3 && block[9] == 4)

        // The second block carries the tail of the first one out in front.
        let tail = Float(frames * 2)
        for i in 0..<(frames * 2) { block[i] = -1 }
        line.feed(block, frames: frames)
        check("what was held comes out on the next block",
              block[0] == tail - 5 && block[1] == tail - 4,
              "\(block[0]), \(block[1])")

        // Changing it starts again rather than stretching what is held: a
        // delay changed mid show is somebody lining a source up by ear, and a
        // click while they do it beats an answer that keeps sliding.
        line.set(frames: 5)
        for i in 0..<(frames * 2) { block[i] = 9 }
        line.feed(block, frames: frames)
        check("changing the delay starts it again rather than stretching it",
              block[0] == 0 && block[9] == 0 && block[10] == 9,
              "\(block[0]), \(block[9]), \(block[10])")

        // And a block SHORTER than the delay, which is the case a ring gets
        // wrong if the arithmetic is written for the other one.
        let small = UnsafeMutablePointer<Float>.allocate(capacity: 4)
        defer { small.deallocate() }
        let short = DelayLine()
        short.set(frames: 4)
        for pass in 0..<3 {
            for i in 0..<4 { small[i] = Float(pass * 4 + i + 1) }
            short.feed(small, frames: 2)
            if pass == 0 {
                check("a block shorter than the delay comes out silent first",
                      small[0] == 0 && small[3] == 0)
            }
            if pass == 2 {
                check("and the held audio comes back in order",
                      small[0] == 1 && small[1] == 2, "\(small[0]), \(small[1])")
            }
        }

        // The board clamps it, because a source file arrives from anywhere and
        // this number ends up as an allocation.
        var wild = SourceConfig()
        wild.delayMS = 0
        let big = SourceConfig.fromDict(["delay_ms": 999_999.0])
        check("a board cannot ask for a delay beyond the ceiling",
              big?.delayMS == Double(C.maxSourceDelayMS), "\(big?.delayMS ?? -1)")
        let negative = SourceConfig.fromDict(["delay_ms": -50.0])
        check("nor for a negative one", negative?.delayMS == 0)
        let notANumber = SourceConfig.fromDict(["delay_ms": Double.nan])
        check("and NaN loads as no delay rather than as a ceiling",
              notANumber?.delayMS == 0, "\(notANumber?.delayMS ?? -1)")
        wild.delayMS = 250
        check("the delay travels in the board under the Windows key",
              (wild.toDict()["delay_ms"] as? Double) == 250)
        out.append("")
    }

    // ------------------------------------------------------------ mix minus ---

    fileprivate func testMixMinus() {
        out.append("Mix minus, which is a subtraction off ONE read")

        let frames = 64
        let group = SourceGroup()
        let a = StandInSource(name: "TeamTalk", level: 0.25)
        let b = StandInSource(name: "Games console", level: 0.125)
        group.useForTesting([a, b])

        let sum = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        let taken = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { sum.deallocate(); taken.deallocate() }

        group.read(frames: frames, into: sum, minus: nil, taken: taken)
        check("with nothing left out, everything is in the sum",
              near(Double(sum[0]), 0.375, 0.0001), "\(sum[0])")
        check("and nothing is taken", taken[0] == 0)

        group.read(frames: frames, into: sum, minus: "TeamTalk", taken: taken)
        check("the sum still carries everything", near(Double(sum[0]), 0.375, 0.0001))
        check("and the named source's own block comes back to subtract",
              near(Double(taken[0]), 0.25, 0.0001), "\(taken[0])")
        check("so the send is exactly the other one",
              near(Double(sum[0] - taken[0]), 0.125, 0.0001))

        // **A mix minus that is not happening must never look like one that
        // is.** A name matching nothing takes nothing, so the subtraction is a
        // no-op and everything goes out, and the report says so in as many
        // words rather than leaving a call full of echo unexplained.
        group.read(frames: frames, into: sum, minus: "Somebody Who Left", taken: taken)
        check("a name that matches nothing takes nothing out", taken[0] == 0)

        // Case and stray spaces are the user's, not the code's.
        group.read(frames: frames, into: sum, minus: "  teamtalk ", taken: taken)
        check("the name is matched without case or spaces getting in the way",
              near(Double(taken[0]), 0.25, 0.0001))

        // ONE read. Reading a source drains its ring, so a second pass would
        // give each sum half a voice. The stand-ins count their reads.
        let before = a.reads
        group.read(frames: frames, into: sum, minus: "TeamTalk", taken: taken)
        check("each source is read exactly once per block", a.reads == before + 1,
              "\(a.reads - before)")

        // And the REAL source, with a real ring, so the guard the stand-in
        // copies is proved rather than assumed. `deliver` is the common tail of
        // both capture paths, so this is the path a sound card takes with no
        // sound card present.
        var config = SourceConfig()
        config.name = "A real one"
        config.onAir = true
        let real = OpenStandIn(config: config)
        let feed = [Float](repeating: 0.5, count: frames * 2)
        let got = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { got.deallocate() }
        feed.withUnsafeBufferPointer {
            real.deliver($0.baseAddress!, frames: frames, channels: 2,
                         captureRate: real.outputRate)
        }
        real.readAir(frames: frames, into: got)
        check("a real source really carries its audio to the air",
              near(Double(got[0]), 0.5, 0.001), "\(got[0])")
        real.config.muted = true
        feed.withUnsafeBufferPointer {
            real.deliver($0.baseAddress!, frames: frames, channels: 2,
                         captureRate: real.outputRate)
        }
        real.readAir(frames: frames, into: got)
        check("and a muted one is silent, whether or not anything is live",
              got[0] == 0, "\(got[0])")
        out.append("")
    }

    // --------------------------------------------------- the mixer's two sums ---

    fileprivate func testSendMix() {
        out.append("The send takes the programme, less one source")

        let frames = 128
        let group = SourceGroup()
        let voice = StandInSource(name: "My co-host", level: 0.2)
        let call = StandInSource(name: "TeamTalk", level: 0.3)
        group.useForTesting([voice, call])

        let mixer = Mixer(key: "check", deviceUID: nil, sampleRate: 48000,
                          duckBus: DuckBus(), cache: DecodeCache(rate: 48000))
        mixer.airSource = group
        let air = CollectingTap()
        let send = CollectingTap()
        mixer.tap = air
        mixer.sendTap = send
        mixer.sendMinus = "TeamTalk"

        let out_ = UnsafeMutablePointer<Float>.allocate(capacity: frames * 2)
        defer { out_.deallocate() }
        mixer.render(frames: frames, into: out_)

        check("the air tap gets both sources",
              near(Double(air.first), 0.5, 0.001), "\(air.first)")
        check("and the send gets the programme without the one named",
              near(Double(send.first), 0.2, 0.001), "\(send.first)")

        // Nothing named means the two are the same mix.
        mixer.sendMinus = nil
        air.reset(); send.reset()
        mixer.render(frames: frames, into: out_)
        check("with no mix minus the send is the same as the air",
              near(Double(send.first), Double(air.first), 0.0001))

        // And the send alone still builds the sum, because it does not need
        // anything to be live. This is the whole reason it is not a mode on
        // the recorder.
        mixer.tap = nil
        send.reset()
        mixer.render(frames: frames, into: out_)
        check("a send with nothing else listening still gets the show",
              near(Double(send.first), 0.5, 0.001), "\(send.first)")

        // **Muting and soloing must not take a voice off the send.** On Windows
        // every Mute and Solo asked whether something was live or recording,
        // and a send is neither, so one press of Space in Source Control during
        // a call removed the presenter and unmuting did not put them back. The
        // Mac never asked that question; this is the check that keeps it that
        // way.
        mixer.tap = nil
        mixer.sendTap = send
        send.reset()
        call.config.muted = true
        mixer.render(frames: frames, into: out_)
        check("muting a source takes it off the send and leaves the rest",
              near(Double(send.first), 0.2, 0.001), "\(send.first)")
        call.config.muted = false
        group.soloed = call.config.id
        send.reset()
        mixer.render(frames: frames, into: out_)
        check("a solo is honoured on the send too",
              near(Double(send.first), 0.3, 0.001), "\(send.first)")
        group.soloed = nil
        send.reset()
        mixer.render(frames: frames, into: out_)
        check("and dropping it puts everybody back",
              near(Double(send.first), 0.5, 0.001), "\(send.first)")

        // A rebuilt mixer has no tap on it, which is the whole of the Windows
        // fault: changing any output device while sending stopped the other
        // program receiving audio and never started it again. Here the group
        // sets it on every mixer it has, so the check is that a NEW group with
        // the tap set really carries it.
        let rebuilt = MixerGroup(mainDeviceUID: nil, bankDevices: [:])
        check("a fresh group has no send tap", rebuilt.sendTap == nil)
        rebuilt.sendTap = send
        rebuilt.sendMinus = "TeamTalk"
        check("setting it reaches every mixer",
              rebuilt.mixers.values.allSatisfy { $0.sendTap != nil && $0.sendMinus != nil })
        rebuilt.rebuild(mainDeviceUID: nil, bankDevices: [:])
        check("and a rebuild drops it, which is why the caller puts it back",
              rebuilt.sendTap == nil)

        mixer.sendTap = nil
        mixer.airSource = nil
        out.append("")
    }

    // ----------------------------------------------------------- what it says ---

    fileprivate func testSendReporting() {
        out.append("What a send says about itself")

        let send = Send(deviceUID: nil, gainDB: 0, openStream: false)
        check("a send that was never opened says so plainly",
              send.report().hasPrefix("The send is off"), send.report())
        let (ok, why) = send.keepingUp()
        check("and with nothing played it is not called unhealthy", ok)
        check("it says why rather than only yes",
              why.contains("nothing has played yet"), why)

        // The confidence feed is heard and NEVER sent, and that one fact is
        // what stops hearing the send putting the send inside itself.
        let heard = UnsafeMutablePointer<Float>.allocate(capacity: 32)
        defer { heard.deallocate() }
        let confidence = send.confidence
        confidence.start()
        let block = [Float](repeating: 0.5, count: 32)
        block.withUnsafeBufferPointer {
            confidence.offer($0.baseAddress!, frames: 16)
        }
        confidence.readAir(frames: 16, into: heard)
        check("a confidence feed answers SILENCE to the air",
              heard[0] == 0 && heard[31] == 0)
        confidence.readMonitor(frames: 16, into: heard)
        check("and the presenter really hears it",
              near(Double(heard[0]), 0.5, 0.001), "\(heard[0])")
        check("it is never on air in its own right", !confidence.config.onAir)
        confidence.stop()
        confidence.readMonitor(frames: 16, into: heard)
        check("switched off, it costs one boolean and hands back silence",
              heard[0] == 0)
        send.close()

        // The gain is clamped on the way in for the reason Windows found the
        // hard way: NaN loaded as +24 dB, a sixteenfold boost into a call.
        let wild = Board.from(dict: ["send_gain_db": Double.nan], relativeTo: nil)
        check("NaN in a board file loads as no gain at all", wild.sendGainDB == 0,
              "\(wild.sendGainDB)")
        let loud = Board.from(dict: ["send_gain_db": 900.0], relativeTo: nil)
        check("and a huge one is clamped to the ceiling",
              loud.sendGainDB == C.maxMicGainDB, "\(loud.sendGainDB)")
        out.append("")
    }

    // --------------------------------------------- the monitor carries it all ---

    fileprivate func testMonitorEverything() {
        out.append("What you hear carries every card")

        // With one card there is no bus at all, which is the ordinary case and
        // the one that must not pay a millisecond for this.
        let one = MixerGroup(mainDeviceUID: nil, bankDevices: [:])
        one.wireMonitor()
        check("one sound card builds no monitor bus",
              one.mixers.values.allSatisfy { $0.monitorTap == nil && $0.monitorFeed == nil })

        // With a bank on a card of its own, that card's show is offered to the
        // card the presenter listens on, and the listening one is not offered
        // its own show back.
        let two = MixerGroup(mainDeviceUID: nil, bankDevices: [C.bankBeds: "second-card"])
        two.wireMonitor()
        let listening = two.monitorMixer
        check("the card you listen on drains the bus", listening.monitorFeed != nil)
        check("and is not writing into it", listening.monitorTap == nil)
        let others = two.mixers.values.filter { $0 !== listening }
        check("every other card writes into it",
              !others.isEmpty && others.allSatisfy { $0.monitorTap != nil })
        check("and none of them drains it",
              others.allSatisfy { $0.monitorFeed == nil })

        two.setMonitorEverything(false)
        check("turned off, the bus goes away entirely",
              two.mixers.values.allSatisfy { $0.monitorTap == nil && $0.monitorFeed == nil })
        two.setMonitorEverything(true)
        check("and comes back", two.monitorMixer.monitorFeed != nil)

        // "Hear yourself through" is a real output from 3.7.1. It was saved,
        // carried across a File Open, and read by nothing: monitoring came out
        // of the main card whatever the board said.
        let named = MixerGroup(mainDeviceUID: nil, bankDevices: [:],
                               monitorDeviceUID: "headphones")
        check("a named monitor card gets a mixer of its own",
              named.monitor != nil && named.monitor !== named.primary)
        check("and it is the one a cue goes to",
              named.monitorMixer === named.monitor)
        let shared = MixerGroup(mainDeviceUID: "one-card",
                                bankDevices: [C.bankBeds: "one-card"],
                                monitorDeviceUID: "one-card")
        check("a monitor card the show already uses is that mixer, not a second one",
              shared.monitorMixer === shared.primary && shared.mixers.count == 1,
              "\(shared.mixers.count)")
        out.append("")
    }

    // ------------------------------------------------------- the track list ---

    fileprivate func testCueFileOnDisk() {
        out.append("The track list beside a recording")

        let scratch = NSTemporaryDirectory() + "dropdeck-selftest-cue"
        try? FileManager.default.removeItem(atPath: scratch)
        try? FileManager.default.createDirectory(atPath: scratch,
                                                 withIntermediateDirectories: true)
        let audio = scratch + "/Drop Deck Stream 004.mp3"
        let cue = CueFile(audioPath: audio)
        check("it goes beside the audio with the same stem",
              cue.path == scratch + "/Drop Deck Stream 004.cue", cue.path ?? "none")
        check("nothing is written before a track goes out",
              !FileManager.default.fileExists(atPath: cue.path ?? ""))

        check("adding a track writes it", cue.add(title: "First", performer: "A Band"))
        check("the same track at the same moment is a double press, not a play",
              !cue.add(title: "First", performer: "A Band"))
        check("the same track LATER is a second play",
              cue.add(title: "First", performer: "A Band", seconds: 200))

        guard let text = try? String(contentsOfFile: cue.path ?? "", encoding: .utf8) else {
            check("the file is really on disk", false)
            return
        }
        check("the file names the audio it describes",
              text.contains("FILE \"Drop Deck Stream 004.mp3\" MP3"), text)
        check("and holds both plays", text.contains("TRACK 01") && text.contains("TRACK 02"))
        check("the second one is stamped where the music really is",
              text.contains("INDEX 01 03:20:00"), text)
        check("it says what it wrote", cue.describe() == "2 tracks in the track list beside it",
              cue.describe())
        try? FileManager.default.removeItem(atPath: scratch)
        out.append("")
    }

    // -------------------------------------------------- the picture recorder ---

    fileprivate func testVideoRecorderClock() {
        out.append("The picture recorder's clock is the SOUND")

        let recorder = VideoRecorder()
        check("nothing is recording to begin with", !recorder.isRecording)
        check("and the clock reads zero rather than a wall time",
              recorder.audioSeconds == 0 && recorder.elapsed == 0)
        check("it describes itself honestly when idle",
              recorder.describe() == "Not recording")

        // The numbers that decide whether a finished file is in sync. Asserted
        // against the constants rather than against a copy of them, because
        // changing one must not silently invalidate the reasoning written
        // beside it.
        check("audio is drained a FRAME at a time, not a quarter of a second",
              C.recordDrainFramesPerPicture == 1)
        check("the stamp lead is bounded", C.recordStampLeadFrames == 4)
        check("and so is the catch up", C.recordCatchupFrames == 30)
        check("a file is made safe to open every second",
              C.recordFragmentSeconds == 1.0)
        check("there is a decibel of room before the AAC encoder",
              C.recordAACHeadroomDB == -1.0)
        check("an MP4 is what a picture recording is written as",
              C.recordVideoFormatKeys == ["mp4"]
              && Recorder.fileExtension(for: "mp4") == ".mp4")
        out.append("")
    }

    // -------------------------------------- a board survives a File, Open ---

    fileprivate func testBoardCarriesEverything() {
        out.append("Opening a board brings ALL of it, not most of it")

        // **The check that cannot fall behind.** Every stored property, set to
        // something that is not its default, copied across, and the two boards
        // compared as the dictionaries they save as. A property left out of
        // `replaceContents` fails this without anybody having to remember to
        // add a line for it.
        //
        // Written because that is exactly what had happened: not one of the
        // twenty two video properties was in `replaceContents`, so from the day
        // video landed, File, Open loaded a board's picture, colours, platform
        // and stream size and then threw every one of them away. The only sign
        // was on the air.
        let from = Board()
        from.sfxVolume = 0.11
        from.bedVolume = 0.22
        from.playlistVolume = 0.33
        from.ducking = false
        from.duckDB = -13
        from.bankNames = [1: "Stings", 2: "Idents", 3: "Beds", 4: "Odds"]
        from.recordFormat = "flac"
        from.recordBitrate = 256
        from.speechLevel = "essential"
        from.askBeforeLive = false
        from.videoServer = "facebook"
        from.videoHost = "rtmps://example.invalid/x"
        from.liveTo = C.liveToVideo
        from.picture = C.pictureCard
        from.pictureClock = true
        from.camera = "a camera"
        from.colourBackground = Colours.names.last ?? from.colourBackground
        from.colourText = Colours.names.first ?? from.colourText
        from.visionModel = "a-model"
        from.videoWidth = 1920
        from.videoHeight = 1080
        from.videoFPS = 60
        from.videoBitrate = 4500
        from.framingLevel = "everything"
        from.sendOn = true
        from.sendDeviceName = "A Cable"
        from.sendDeviceUID = "cable-uid"
        from.sendGainDB = -6
        from.sendMinus = "TeamTalk"
        from.micOutputUID = "headphones"
        from.globalHotkeysOn = true
        from.playlistMonitorOnly = false
        var source = SourceConfig()
        source.name = "TeamTalk"
        source.delayMS = 120
        from.sources = [source]

        let into = Board()
        into.replaceContents(with: from)
        let wanted = from.toDict() as NSDictionary
        let got = into.toDict() as NSDictionary
        var missed: [String] = []
        for (key, value) in wanted {
            guard let name = key as? String else { continue }
            let mine = got[name] as AnyObject?
            if !(mine?.isEqual(value) ?? false) { missed.append(name) }
        }
        check("every stored property survives a File, Open", missed.isEmpty,
              missed.sorted().joined(separator: ", "))
        check("the send travels with it", into.sendMinus == "TeamTalk"
              && into.sendDeviceUID == "cable-uid" && into.sendOn)
        check("and so does the delay on a source", into.sources.first?.delayMS == 120)
        check("the whole dictionary matches, not only the keys checked by hand",
              got.isEqual(to: wanted as! [AnyHashable: Any]))
        out.append("")
    }
}

// ------------------------------------------------------------- stand-ins ---

/// A source that answers a steady level, and counts how often it was read.
///
/// Reading a real source drains its ring, which is the whole reason mix minus
/// has to come off one read. This counts the reads so that property can be
/// asserted rather than assumed.
final class StandInSource: RunningSource {
    var config: SourceConfig
    var isRunning = true
    var lastError: String?
    var peak: Float = 0
    private(set) var reads = 0
    private let level: Float

    init(name: String, level: Float) {
        var c = SourceConfig()
        c.name = name
        c.onAir = true
        config = c
        self.level = level
    }

    @discardableResult func start(outputRate: Double) -> Bool { true }
    func stop() {}

    /// The same guard `BaseSource.readAir` really applies. Written out rather
    /// than inherited, because a stand-in that answers a steady level cannot
    /// also be a real capture; `SelfTest.testMixMinus` proves the REAL one
    /// against a real ring beside this.
    func readAir(frames: Int, into out: UnsafeMutablePointer<Float>) {
        reads += 1
        let value = (isRunning && config.onAir && !config.muted) ? level : 0
        for i in 0..<(frames * 2) { out[i] = value }
    }

    func readMonitor(frames: Int, into out: UnsafeMutablePointer<Float>) {
        out.update(repeating: 0, count: frames * 2)
    }
}

/// A real `BaseSource` that reports itself open, so the genuine capture tail,
/// gain, channel fold, delay line and both rings can be driven with no device.
final class OpenStandIn: BaseSource {
    override var isRunning: Bool { true }
}

/// A programme tap that keeps the first sample of whatever was written to it.
final class CollectingTap: ProgramTap {
    private(set) var first: Float = 0
    private(set) var writes = 0

    func write(key: String, samples: UnsafePointer<Float>, frames: Int, rate: Double) {
        guard frames > 0 else { return }
        first = samples[0]
        writes += 1
    }

    func reset() { first = 0; writes = 0 }
}
