// Output streams, per bank routing, ducking, and the three faders.
//
// A port of dropdeck/mixer.py. The device layer underneath is different, AUHAL
// rather than PortAudio, but the callback contract is the same one and the
// same rule holds above everything else in this file:
//
//   THE AUDIO CALLBACK NEVER THROWS. A voice that fails is marked finished and
//   skipped. One exception escaping the callback silences that sound card for
//   the rest of the show, and nothing anywhere restarts it.

import Foundation
import AudioToolbox
import CoreAudio

/// Which mixers currently have a loud voice, shared across every mixer in a
/// group and by the microphone.
///
/// Once banks can go to different sound cards the beds may be on a different
/// device from the drop that is supposed to duck them, and a mixer looking
/// only at its own voices would quietly stop ducking at all.
final class DuckBus {
    private var flags: [String: Bool] = [:]
    private let lock = NSLock()

    func publish(_ key: String, _ isLoud: Bool) {
        lock.lock(); flags[key] = isLoud; lock.unlock()
    }
    var loud: Bool {
        lock.lock(); defer { lock.unlock() }
        return flags.values.contains(true)
    }
    func forget(_ key: String) {
        lock.lock(); flags.removeValue(forKey: key); lock.unlock()
    }
}

/// Anything that can be summed into the programme without being a Voice: the
/// microphone and the extra sources.
protocol AudioSource: AnyObject {
    /// Never blocks. Returns silence rather than stalling the output callback.
    func read(frames: Int, into out: UnsafeMutablePointer<Float>)
}

/// Where the programme goes on its way to an encoder or a recorder.
protocol ProgramTap: AnyObject {
    func write(key: String, samples: UnsafePointer<Float>, frames: Int, rate: Double)
}

final class Mixer {

    let key: String
    private(set) var sampleRate: Double
    private(set) var deviceUID: String?
    private(set) var isRunning = false
    private(set) var lastError: String?

    var sfxGain: Float = C.defaultSFXVolume
    var bedGain: Float = C.defaultBedVolume
    var playlistGain: Float = C.defaultPlaylistVolume

    var ducking = true
    var duckDB: Float = C.defaultDuckDB
    var bedFadeIn = C.fadeInBed
    var bedFadeOut = C.fadeOutBed

    /// The playlist fader is a MONITOR fader by default: you pull the music
    /// down in your own ears to hear your screen reader, and the listener
    /// hears no such thing.
    var playlistMonitorOnly = true

    let duckBus: DuckBus
    var cache: DecodeCache

    /// Heard by the presenter only. Added AFTER the duck, or the voice would
    /// duck itself, and never part of the programme.
    weak var monitorSource: AudioSource?
    /// The microphone and the extra sources, which ARE part of the programme.
    /// Only the primary mixer reads this: every mixer reading it would take the
    /// same audio away from each other and the voice would arrive in pieces.
    weak var airSource: AudioSource?
    var tap: ProgramTap?

    /// A THIRD reader of the same mix, and the one that does not need anything
    /// to be live: the show, out of a sound card, for another program on this
    /// machine. It has a bus of its own for the same reason the recorder does,
    /// because reading a bus takes the audio out of it. See `Send.swift`.
    var sendTap: ProgramTap?
    /// The one source the send leaves out, by NAME. Mix minus. Only the mixer
    /// holding the `airSource` can do anything with it, which is the primary.
    var sendMinus: String?

    /// What this card is playing, offered to the card the presenter listens on.
    /// Taken after the voices and before anything that belongs only to the
    /// presenter: a monitor wants the show, not a second copy of somebody
    /// else's headphone feed.
    var monitorTap: ProgramTap?
    /// And the other way round, on the one card the presenter listens on:
    /// every OTHER card's show, added to this one's. This is what makes a
    /// monitor carry the whole programme rather than only whatever happens to
    /// be routed to it.
    var monitorFeed: AirBus?
    private var monitorPrimed = false
    private(set) var monitorGaps = 0

    // ---------------------------------------------------- is it keeping up ---
    //
    // Timed here rather than trusted to the driver. Two clock reads and a
    // compare, which is nothing beside the mixing below, and it is the only
    // reason this app can say "that output is not keeping up" instead of
    // shrugging: on Windows, PortAudio reported a clean stream through a
    // measured seven per cent loss into a virtual cable.

    private(set) var blocks = 0
    private(set) var lateBlocks = 0
    private(set) var worstGap: Double = 0
    private(set) var lastFrames = 0
    private var lastCallback: Double = 0

    var lateShare: Double { blocks > 0 ? Double(lateBlocks) / Double(blocks) : 0 }

    /// One callback arrived. Called from the audio thread, so it does nothing
    /// but read a clock and add up.
    func timeBlock(frames: Int) {
        let now = ProcessInfo.processInfo.systemUptime
        let previous = lastCallback
        lastCallback = now
        blocks += 1
        lastFrames = frames
        guard previous > 0, frames > 0, sampleRate > 0 else { return }
        let gap = now - previous
        if gap > worstGap { worstGap = gap }
        if gap > (Double(frames) / sampleRate) * C.lateBlockFactor { lateBlocks += 1 }
    }

    /// Is this output healthy, and one line saying why if it is not.
    func keepingUp() -> (Bool, String) {
        if !isRunning { return (false, lastError ?? "not running") }
        if lateBlocks > 0 && lateShare > C.lateBlockWarnShare {
            return (false, "\(lateBlocks) of \(blocks) blocks arrived late, "
                + "worst gap \(Int((worstGap * 1000).rounded())) milliseconds")
        }
        return (true, "keeping up")
    }

    private var voices: [Voice] = []
    private let voiceLock = NSLock()
    private var duck: Float = 1.0
    private var playlistFader: Float = C.defaultPlaylistVolume
    private(set) var peak: Float = 0

    private var output: DeviceOutput?

    // Scratch buffers, allocated once. Nothing in the callback allocates.
    private var voiceBuf: UnsafeMutablePointer<Float>
    private var rampBuf: UnsafeMutablePointer<Float>
    private var duckBuf: UnsafeMutablePointer<Float>
    private var airBuf: UnsafeMutablePointer<Float>
    private var srcBuf: UnsafeMutablePointer<Float>
    /// The send's own sum and the one member subtracted out of it. Both are
    /// allocated whether or not anything is sending, because allocating them
    /// the moment somebody presses a key would allocate on the audio thread.
    private var sendBuf: UnsafeMutablePointer<Float>
    private var takenBuf: UnsafeMutablePointer<Float>
    private var capacity = 4096

    init(key: String, deviceUID: String?, sampleRate: Double, duckBus: DuckBus,
         cache: DecodeCache) {
        self.key = key
        self.deviceUID = deviceUID
        self.sampleRate = sampleRate
        self.duckBus = duckBus
        self.cache = cache
        voiceBuf = .allocate(capacity: capacity * 2)
        rampBuf = .allocate(capacity: capacity)
        duckBuf = .allocate(capacity: capacity)
        airBuf = .allocate(capacity: capacity * 2)
        srcBuf = .allocate(capacity: capacity * 2)
        sendBuf = .allocate(capacity: capacity * 2)
        takenBuf = .allocate(capacity: capacity * 2)
    }

    deinit {
        voiceBuf.deallocate(); rampBuf.deallocate(); duckBuf.deallocate()
        airBuf.deallocate(); srcBuf.deallocate()
        sendBuf.deallocate(); takenBuf.deallocate()
    }

    private func grow(_ frames: Int) {
        guard frames > capacity else { return }
        voiceBuf.deallocate(); rampBuf.deallocate(); duckBuf.deallocate()
        airBuf.deallocate(); srcBuf.deallocate()
        sendBuf.deallocate(); takenBuf.deallocate()
        capacity = frames * 2
        voiceBuf = .allocate(capacity: capacity * 2)
        rampBuf = .allocate(capacity: capacity)
        duckBuf = .allocate(capacity: capacity)
        airBuf = .allocate(capacity: capacity * 2)
        srcBuf = .allocate(capacity: capacity * 2)
        sendBuf = .allocate(capacity: capacity * 2)
        takenBuf = .allocate(capacity: capacity * 2)
    }

    // ------------------------------------------------------------ the door ---

    func start() {
        stop()
        blocks = 0; lateBlocks = 0; worstGap = 0; lastCallback = 0
        let out = DeviceOutput(deviceUID: deviceUID)
        out.render = { [weak self] buf, frames in
            guard let self else { return }
            // Timed HERE and not inside `render`, because the self test calls
            // `render` by hand as fast as it can and would otherwise report
            // every block as catastrophically late.
            self.timeBlock(frames: frames)
            self.render(frames: frames, into: buf)
        }
        if out.start() {
            output = out
            sampleRate = out.sampleRate
            isRunning = true
            lastError = nil
        } else {
            output = nil
            isRunning = false
            lastError = out.lastError
        }
    }

    func stop() {
        output?.stop()
        output = nil
        isRunning = false
    }

    func setDevice(uid: String?) {
        stopAll(fadeOut: 0.0)
        deviceUID = uid
        stop()
        start()
        // Cached audio was resampled for the old rate.
        if cache.rate != sampleRate { cache.clear(newRate: sampleRate) }
    }

    // -------------------------------------------------------------- faders ---

    func busGain(_ bus: String) -> Float {
        switch bus {
        case C.busPreview: return sfxGain
        // A cue you have turned the sound down on is a cue you will miss, and
        // turning the sound down is the first thing anybody does while they
        // are talking.
        case C.busCue: return 1.0
        case C.busBed: return bedGain
        case C.busPlaylist: return playlistGain
        default: return sfxGain
        }
    }

    func setBusGain(_ bus: String, _ value: Float) {
        let v = min(1.0, max(0.0, value))
        switch bus {
        case C.busBed: bedGain = v
        case C.busPlaylist: playlistGain = v; return   // applied per block, not baked in
        default: sfxGain = v
        }
        voiceLock.lock()
        // A voice mid crossfade is on its way somewhere; moving its target
        // under it would abandon the fade half done.
        for voice in voices where voice.bus == bus && !voice.releasing {
            voice.setGain(v)
        }
        voiceLock.unlock()
    }

    // ------------------------------------------------------------ playing ---

    @discardableResult
    func play(slotIndex: Int, path: String, bus: String = C.busSFX,
              loop: Bool = false, trimDB: Double = 0.0, name: String = "",
              duration: Double? = nil,
              fadeIn: Double? = nil, fadeOut: Double? = nil) -> Voice? {

        let level: Float = (bus == C.busPlaylist) ? 1.0 : busGain(bus)
        let gain = level * dbToGain(trimDB)

        let isBed = bus == C.busBed
        let fIn = fadeIn ?? (isBed ? bedFadeIn : C.fadeInSFX)
        let fOut = fadeOut ?? (isBed ? bedFadeOut : C.fadeOutSFX)

        var voice: Voice?
        if let d = duration, d > 0, d <= C.preloadSeconds,
           let samples = cache.cached(path) {
            voice = MemoryVoice(samples: samples, slotIndex: slotIndex, bus: bus,
                                name: name, gain: gain, loop: loop, rate: sampleRate,
                                fadeIn: fIn, fadeOut: fOut)
        } else {
            voice = StreamVoice(path: path, slotIndex: slotIndex, bus: bus,
                                name: name, gain: gain, loop: loop, rate: sampleRate,
                                fadeIn: fIn, fadeOut: fOut)
        }
        guard let v = voice else { return nil }
        voiceLock.lock(); voices.append(v); voiceLock.unlock()
        return v
    }

    /// Play a block of samples this file made itself, which is how the cue pip
    /// reaches a sound card without a file on disk.
    @discardableResult
    func playSamples(slotIndex: Int, samples: [Float], bus: String,
                     name: String = "", gain: Float = 1.0,
                     fadeIn: Double = 0.0, fadeOut: Double = 0.01) -> Voice {
        let v = MemoryVoice(samples: samples, slotIndex: slotIndex, bus: bus,
                            name: name, gain: gain, loop: false, rate: sampleRate,
                            fadeIn: fadeIn, fadeOut: fadeOut)
        voiceLock.lock(); voices.append(v); voiceLock.unlock()
        return v
    }

    @discardableResult
    func stopSlot(_ slotIndex: Int, fadeOut: Double? = nil,
                  alsoReleasing: Bool = false) -> Int {
        voiceLock.lock(); defer { voiceLock.unlock() }
        var stopped = 0
        for v in voices where v.slotIndex == slotIndex {
            if v.releasing && !alsoReleasing { continue }
            if !v.releasing { stopped += 1 }
            v.release(fadeOut: fadeOut)
        }
        return stopped
    }

    @discardableResult
    func stopAll(fadeOut: Double? = nil) -> Int {
        let fade = fadeOut ?? C.fadeOutPanic
        voiceLock.lock()
        var stopped = 0
        for v in voices {
            if !v.releasing { stopped += 1 }
            v.release(fadeOut: fade)
        }
        voiceLock.unlock()
        if fade <= 0.0 { reap(force: true) }
        return stopped
    }

    func isPlaying(slotIndex: Int) -> Bool {
        voiceLock.lock(); defer { voiceLock.unlock() }
        return voices.contains { $0.slotIndex == slotIndex && !$0.finished && !$0.releasing }
    }

    var playingSlots: [Int] {
        voiceLock.lock(); defer { voiceLock.unlock() }
        return voices.filter { !$0.finished && !$0.releasing }.map(\.slotIndex)
    }

    var playingNames: [String] {
        voiceLock.lock(); defer { voiceLock.unlock() }
        return voices.filter { !$0.finished && !$0.releasing && !$0.name.isEmpty }
                     .map(\.name)
    }

    private func reap(force: Bool = false) {
        voiceLock.lock()
        var kept: [Voice] = []
        var dead: [Voice] = []
        for v in voices {
            if v.finished || force { dead.append(v) } else { kept.append(v) }
        }
        voices = kept
        voiceLock.unlock()
        for v in dead { v.close() }
    }

    // ------------------------------------------------------------- the duck ---

    /// The duck ramp, written into `duckBuf`, or a flat value.
    ///
    /// The step here is deliberately NOT normalised to the distance, unlike a
    /// Voice fade. It travels one gain unit per span seconds, so at the default
    /// minus nine decibels the attack really takes about 77 ms and the release
    /// about 452 ms. Making it "reach the target in DUCK_ATTACK seconds" would
    /// slow the duck by half and change how the show sounds.
    private func duckRamp(frames: Int) -> Float? {
        let anyLoud: Bool = {
            voiceLock.lock(); defer { voiceLock.unlock() }
            return voices.contains { $0.isLoud && !$0.finished && !$0.releasing }
        }()
        duckBus.publish(key, anyLoud)

        let target: Float = (ducking && duckBus.loud) ? dbToGain(duckDB) : 1.0
        if abs(duck - target) < 1e-6 { duck = target; return target }

        let span = target < duck ? C.duckAttack : C.duckRelease
        let step = Float(frames) / Float(max(1, Int(span * sampleRate)))
        let delta = target - duck
        let move = min(abs(delta), step) * (delta > 0 ? 1.0 : -1.0)
        let newDuck = duck + move
        if frames == 1 {
            duckBuf[0] = newDuck
        } else {
            let inc = (newDuck - duck) / Float(frames - 1)
            for i in 0..<frames { duckBuf[i] = duck + inc * Float(i) }
        }
        duck = newDuck
        return nil
    }

    /// Where the output starts rounding off rather than being sawn flat.
    ///
    /// A crossfade sums two full level songs, and two full level songs are
    /// louder than one. Clipping is a right angle and sounds like one. This
    /// bends the top instead, and its ceiling is exactly 1.0.
    private func softClip(_ buf: UnsafeMutablePointer<Float>, count: Int) {
        let threshold = C.softClipFrom
        let knee = 1.0 - threshold
        var peakSeen: Float = 0
        for i in 0..<count { peakSeen = max(peakSeen, abs(buf[i])) }
        guard peakSeen > threshold else { return }
        for i in 0..<count {
            let v = buf[i]
            let a = abs(v)
            if a > threshold {
                buf[i] = (v < 0 ? -1 : 1) * (threshold + knee * tanhf((a - threshold) / knee))
            }
        }
    }

    // --------------------------------------------------------------- render ---

    /// One block. `out` holds frames * 2 interleaved floats and is overwritten.
    func render(frames: Int, into out: UnsafeMutablePointer<Float>) {
        grow(frames)
        let count = frames * 2
        out.update(repeating: 0, count: count)

        // The send is a reader of the same sum and does not need anything to be
        // live, so it counts as a reason to build it.
        let wantSend = sendTap != nil
        let wantAir = tap != nil || wantSend
        if wantAir { airBuf.update(repeating: 0, count: count) }

        let flatDuck = duckRamp(frames: frames)

        voiceLock.lock()
        let snapshot = voices
        voiceLock.unlock()

        // The playlist fader glides at one gain unit per VOLUME_GLIDE, the same
        // shape as the duck, because a gain that steps between blocks clicks.
        let faderTarget = playlistGain
        var faderStart = playlistFader
        if abs(faderTarget - playlistFader) > 1e-6 {
            let step = Float(frames) / Float(max(1, Int(C.volumeGlide * sampleRate)))
            let delta = faderTarget - playlistFader
            playlistFader += min(abs(delta), step) * (delta > 0 ? 1 : -1)
        } else {
            playlistFader = faderTarget
        }
        let faderEnd = playlistFader
        let faderInc = frames > 1 ? (faderEnd - faderStart) / Float(frames - 1) : 0

        var anyFailed = false
        for voice in snapshot {
            if voice.finished { continue }
            let duckValue: Float = flatDuck ?? 1.0
            var produced = false
            if flatDuck != nil {
                produced = voice.render(frames: frames, duck: duckValue,
                                        into: voiceBuf, rampScratch: rampBuf)
            } else {
                // A per sample duck: render without it, then apply the ramp.
                produced = voice.render(frames: frames, duck: 1.0,
                                        into: voiceBuf, rampScratch: rampBuf)
                if produced && voice.isDucked {
                    for i in 0..<frames {
                        let d = duckBuf[i]
                        voiceBuf[i * 2] *= d
                        voiceBuf[i * 2 + 1] *= d
                    }
                }
            }
            if !produced { anyFailed = true; continue }

            if voice.bus == C.busPlaylist {
                var g = faderStart
                for i in 0..<frames {
                    out[i * 2] += voiceBuf[i * 2] * g
                    out[i * 2 + 1] += voiceBuf[i * 2 + 1] * g
                    g += faderInc
                }
                if wantAir {
                    if playlistMonitorOnly {
                        for i in 0..<count { airBuf[i] += voiceBuf[i] }
                    } else {
                        var ga = faderStart
                        for i in 0..<frames {
                            airBuf[i * 2] += voiceBuf[i * 2] * ga
                            airBuf[i * 2 + 1] += voiceBuf[i * 2 + 1] * ga
                            ga += faderInc
                        }
                    }
                }
            } else {
                for i in 0..<count { out[i] += voiceBuf[i] }
                // A preview and a cue are yours, not the listener's.
                if wantAir && voice.bus != C.busPreview && voice.bus != C.busCue {
                    for i in 0..<count { airBuf[i] += voiceBuf[i] }
                }
            }
        }
        _ = anyFailed
        faderStart = faderEnd

        // What this card is playing, offered to a monitor on another card.
        // Taken HERE, after the voices and before anything that belongs only
        // to the presenter: a monitor wants the show, not a second copy of
        // somebody's headphone feed.
        monitorTap?.write(key: key, samples: out, frames: frames, rate: sampleRate)

        // And the other way round, on the card the presenter listens on: every
        // OTHER card's show, added to this one's.
        if let feed = monitorFeed {
            srcBuf.update(repeating: 0, count: count)
            if readMonitorFeed(frames: frames, feed: feed, into: srcBuf) {
                for i in 0..<count { out[i] += srcBuf[i] }
            }
        }

        // Monitoring is added AFTER the duck. The point of the duck is to get
        // the music out from under the voice; ducking the voice as well would
        // undo it. A monitor that starves returns silence rather than stalling.
        if let monitor = monitorSource {
            srcBuf.update(repeating: 0, count: count)
            monitor.read(frames: frames, into: srcBuf)
            for i in 0..<count { out[i] += srcBuf[i] }
        }

        var p: Float = 0
        for i in 0..<count { p = max(p, abs(out[i])) }
        peak = p
        softClip(out, count: count)

        if wantAir {
            // ONE read of the sources, because reading one drains its ring.
            // `takenBuf` comes back holding the block belonging to the source
            // the send leaves out, or silence when there is no mix minus, no
            // such source, or nothing arrived from it.
            var subtract = false
            if let air = airSource {
                srcBuf.update(repeating: 0, count: count)
                if wantSend, let group = air as? SourceGroup, sendMinus != nil {
                    group.read(frames: frames, into: srcBuf,
                               minus: sendMinus, taken: takenBuf)
                    subtract = true
                } else {
                    air.read(frames: frames, into: srcBuf)
                }
                for i in 0..<count { airBuf[i] += srcBuf[i] }
            }
            // **Both sums are finished before either is soft clipped**, and
            // neither array is ever clipped twice. Everything upstream of the
            // clip is a plain addition, and that is exactly what makes the
            // subtraction exact.
            if wantSend {
                if subtract {
                    for i in 0..<count { sendBuf[i] = airBuf[i] - takenBuf[i] }
                } else {
                    sendBuf.update(from: airBuf, count: count)
                }
                softClip(sendBuf, count: count)
                sendTap?.write(key: key, samples: sendBuf, frames: frames,
                               rate: sampleRate)
            }
            if tap != nil {
                softClip(airBuf, count: count)
                tap?.write(key: key, samples: airBuf, frames: frames, rate: sampleRate)
            }
        }

        reap()
    }
}

extension Mixer {

    /// One block of the other cards' show. Never blocks, never raises.
    ///
    /// Primed the way the send is, and for the same reason: two sound cards run
    /// on two clocks, so a ring read the moment it is created is a ring that is
    /// empty. Running dry re-primes rather than starving on every block from
    /// then on, because one short silence beats a permanent stutter in the ears
    /// of somebody who cannot see a meter.
    fileprivate func readMonitorFeed(frames: Int, feed: AirBus,
                                     into out: UnsafeMutablePointer<Float>) -> Bool {
        let prime = Int(sampleRate * C.monitorPrimeSeconds)
        if !monitorPrimed {
            if feed.available() < prime { return false }
            monitorPrimed = true
        }
        if feed.available() < frames {
            monitorPrimed = false
            monitorGaps += 1
            return false
        }
        feed.read(frames: frames, into: out)
        return true
    }
}

// ------------------------------------------------------------ device output ---

/// One sound card, opened through AUHAL so a specific device can be named.
///
/// AVAudioEngine would be less code and cannot do this: it plays to whatever
/// the system output is. A bank routed to its own card is the whole reason a
/// broadcaster can ride levels on a desk, so the lower level unit is the right
/// one here.
final class DeviceOutput {

    var render: ((UnsafeMutablePointer<Float>, Int) -> Void)?
    private(set) var sampleRate: Double = C.defaultSampleRate
    private(set) var lastError: String?

    private var unit: AudioUnit?
    private let deviceUID: String?

    init(deviceUID: String?) { self.deviceUID = deviceUID }

    /// Is the unit REALLY running, asked of Core Audio rather than remembered.
    ///
    /// An unplugged card leaves the object exactly where it was, so a flag set
    /// at `start` goes on saying yes for ever. On Windows that is what made the
    /// send report "Sending to" with nothing coming out: the stream had aborted
    /// and only PortAudio knew. Found by Mark, 10 September 2026.
    var isRunning: Bool {
        guard let unit else { return false }
        var running: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        let status = AudioUnitGetProperty(unit, kAudioOutputUnitProperty_IsRunning,
                                          kAudioUnitScope_Global, 0, &running, &size)
        return status == noErr && running != 0
    }

    func start() -> Bool {
        var desc = AudioComponentDescription(
            componentType: kAudioUnitType_Output,
            componentSubType: kAudioUnitSubType_HALOutput,
            componentManufacturer: kAudioUnitManufacturer_Apple,
            componentFlags: 0, componentFlagsMask: 0)
        guard let comp = AudioComponentFindNext(nil, &desc) else {
            lastError = "No audio output unit on this system"
            return false
        }
        var u: AudioUnit?
        var status = AudioComponentInstanceNew(comp, &u)
        guard status == noErr, let unit = u else {
            lastError = "Could not open the audio output (\(status))"
            return false
        }
        self.unit = unit

        let device = deviceUID.flatMap(AudioDevices.deviceID(forUID:)) ?? AudioDevices.defaultOutput()
        if var dev = device {
            status = AudioUnitSetProperty(unit, kAudioOutputUnitProperty_CurrentDevice,
                                          kAudioUnitScope_Global, 0, &dev,
                                          UInt32(MemoryLayout<AudioDeviceID>.size))
            if status != noErr {
                lastError = "That sound card would not open (\(status))"
                AudioComponentInstanceDispose(unit); self.unit = nil
                return false
            }
            sampleRate = AudioDevices.nominalRate(dev) ?? C.defaultSampleRate
        }

        var format = AudioStreamBasicDescription(
            mSampleRate: sampleRate,
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagsNativeFloatPacked,
            mBytesPerPacket: 8, mFramesPerPacket: 1, mBytesPerFrame: 8,
            mChannelsPerFrame: 2, mBitsPerChannel: 32, mReserved: 0)
        status = AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat,
                                      kAudioUnitScope_Input, 0, &format,
                                      UInt32(MemoryLayout<AudioStreamBasicDescription>.size))
        guard status == noErr else {
            lastError = "That sound card would not take stereo audio (\(status))"
            AudioComponentInstanceDispose(unit); self.unit = nil
            return false
        }

        var callback = AURenderCallbackStruct(
            inputProc: outputRenderCallback,
            inputProcRefCon: Unmanaged.passUnretained(self).toOpaque())
        status = AudioUnitSetProperty(unit, kAudioUnitProperty_SetRenderCallback,
                                      kAudioUnitScope_Input, 0, &callback,
                                      UInt32(MemoryLayout<AURenderCallbackStruct>.size))
        guard status == noErr else {
            lastError = "The audio callback would not attach (\(status))"
            AudioComponentInstanceDispose(unit); self.unit = nil
            return false
        }

        status = AudioUnitInitialize(unit)
        guard status == noErr else {
            lastError = "The audio output would not start (\(status))"
            AudioComponentInstanceDispose(unit); self.unit = nil
            return false
        }
        status = AudioOutputUnitStart(unit)
        guard status == noErr else {
            lastError = "The audio output would not start (\(status))"
            AudioUnitUninitialize(unit)
            AudioComponentInstanceDispose(unit); self.unit = nil
            return false
        }
        return true
    }

    func stop() {
        guard let unit else { return }
        AudioOutputUnitStop(unit)
        AudioUnitUninitialize(unit)
        AudioComponentInstanceDispose(unit)
        self.unit = nil
    }
}

private func outputRenderCallback(
    inRefCon: UnsafeMutableRawPointer,
    ioActionFlags: UnsafeMutablePointer<AudioUnitRenderActionFlags>,
    inTimeStamp: UnsafePointer<AudioTimeStamp>,
    inBusNumber: UInt32,
    inNumberFrames: UInt32,
    ioData: UnsafeMutablePointer<AudioBufferList>?
) -> OSStatus {
    guard let ioData else { return noErr }
    let out = Unmanaged<DeviceOutput>.fromOpaque(inRefCon).takeUnretainedValue()
    let buffers = UnsafeMutableAudioBufferListPointer(ioData)
    guard let first = buffers.first,
          let data = first.mData?.assumingMemoryBound(to: Float.self) else { return noErr }
    let frames = Int(inNumberFrames)
    if let render = out.render {
        render(data, frames)
    } else {
        data.update(repeating: 0, count: frames * 2)
    }
    return noErr
}
