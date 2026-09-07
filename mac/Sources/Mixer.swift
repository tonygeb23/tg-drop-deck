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
    }

    deinit {
        voiceBuf.deallocate(); rampBuf.deallocate(); duckBuf.deallocate()
        airBuf.deallocate(); srcBuf.deallocate()
    }

    private func grow(_ frames: Int) {
        guard frames > capacity else { return }
        voiceBuf.deallocate(); rampBuf.deallocate(); duckBuf.deallocate()
        airBuf.deallocate(); srcBuf.deallocate()
        capacity = frames * 2
        voiceBuf = .allocate(capacity: capacity * 2)
        rampBuf = .allocate(capacity: capacity)
        duckBuf = .allocate(capacity: capacity)
        airBuf = .allocate(capacity: capacity * 2)
        srcBuf = .allocate(capacity: capacity * 2)
    }

    // ------------------------------------------------------------ the door ---

    func start() {
        stop()
        let out = DeviceOutput(deviceUID: deviceUID)
        out.render = { [weak self] buf, frames in
            self?.render(frames: frames, into: buf)
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

        let wantAir = tap != nil
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
            if let air = airSource {
                srcBuf.update(repeating: 0, count: count)
                air.read(frames: frames, into: srcBuf)
                for i in 0..<count { airBuf[i] += srcBuf[i] }
            }
            softClip(airBuf, count: count)
            tap?.write(key: key, samples: airBuf, frames: frames, rate: sampleRate)
        }

        reap()
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
