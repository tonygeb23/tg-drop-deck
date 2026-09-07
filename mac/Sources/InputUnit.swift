// One sound card, opened for capture.
//
// The microphone and every extra source open a device the same way, so they
// open it through here rather than each keeping its own copy of the AUHAL
// dance. Duplicating a capture path is exactly where a bug hides: one copy
// gets the channel count fix and the other does not.
//
// This class does nothing to the audio. It hands the raw interleaved frames to
// its owner at whatever rate and channel count the device really offers, and
// the owner decides what that means.

import Foundation
import AudioToolbox
import CoreAudio

final class InputUnit {

    /// Called on the audio thread. Interleaved, `channels` wide, at
    /// `captureRate`. Must not block and must not throw.
    var onCapture: ((UnsafePointer<Float>, Int, UInt32) -> Void)?

    private(set) var captureRate: Double = C.defaultSampleRate
    private(set) var channels: UInt32 = 2
    private(set) var isOpen = false
    private(set) var lastError: String?
    private(set) var deviceUID: String?
    private(set) var deviceName: String?

    private var unit: AudioUnit?
    private var bufferList: UnsafeMutableAudioBufferListPointer?
    private var raw: UnsafeMutablePointer<Float>
    private var capacity = 8192

    init() { raw = .allocate(capacity: capacity * 4) }

    deinit { close(); raw.deallocate() }

    /// Open a specific device, or the system default input when uid is nil.
    @discardableResult
    func open(deviceUID uid: String?) -> Bool {
        guard !isOpen else { return true }
        lastError = nil

        guard var deviceID = uid.flatMap(AudioDevices.deviceID(forUID:))
                ?? AudioDevices.defaultInput() else {
            lastError = "There is no input device on this Mac"
            return false
        }
        deviceUID = AudioDevices.info(for: deviceID)?.uid ?? uid
        deviceName = AudioDevices.info(for: deviceID)?.name

        var desc = AudioComponentDescription(
            componentType: kAudioUnitType_Output,
            componentSubType: kAudioUnitSubType_HALOutput,
            componentManufacturer: kAudioUnitManufacturer_Apple,
            componentFlags: 0, componentFlagsMask: 0)
        guard let comp = AudioComponentFindNext(nil, &desc) else {
            lastError = "No audio input unit on this system"
            return false
        }
        var u: AudioUnit?
        guard AudioComponentInstanceNew(comp, &u) == noErr, let unit = u else {
            lastError = "Could not open that input"
            return false
        }

        func fail(_ message: String) -> Bool {
            lastError = message
            AudioComponentInstanceDispose(unit)
            self.unit = nil
            return false
        }

        // Input on element 1, output off on element 0. An AUHAL that is not
        // told this captures nothing at all, silently.
        var on: UInt32 = 1, off: UInt32 = 0
        guard AudioUnitSetProperty(unit, kAudioOutputUnitProperty_EnableIO,
                                   kAudioUnitScope_Input, 1, &on,
                                   UInt32(MemoryLayout<UInt32>.size)) == noErr,
              AudioUnitSetProperty(unit, kAudioOutputUnitProperty_EnableIO,
                                   kAudioUnitScope_Output, 0, &off,
                                   UInt32(MemoryLayout<UInt32>.size)) == noErr
        else { return fail("That input would not open for capture") }

        guard AudioUnitSetProperty(unit, kAudioOutputUnitProperty_CurrentDevice,
                                   kAudioUnitScope_Global, 0, &deviceID,
                                   UInt32(MemoryLayout<AudioDeviceID>.size)) == noErr
        else { return fail("That input would not open") }

        // Take the rate the device really offers and convert afterwards. Asking
        // for a rate a device does not have is simply refused, and a working
        // input at the wrong rate beats no input at all.
        var hardware = AudioStreamBasicDescription()
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        AudioUnitGetProperty(unit, kAudioUnitProperty_StreamFormat,
                             kAudioUnitScope_Input, 1, &hardware, &size)
        captureRate = hardware.mSampleRate > 0 ? hardware.mSampleRate : C.defaultSampleRate
        channels = max(1, min(2, hardware.mChannelsPerFrame))

        var format = AudioStreamBasicDescription(
            mSampleRate: captureRate,
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagsNativeFloatPacked,
            mBytesPerPacket: 4 * channels,
            mFramesPerPacket: 1,
            mBytesPerFrame: 4 * channels,
            mChannelsPerFrame: channels,
            mBitsPerChannel: 32, mReserved: 0)
        guard AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat,
                                   kAudioUnitScope_Output, 1, &format,
                                   UInt32(MemoryLayout<AudioStreamBasicDescription>.size))
                == noErr
        else { return fail("That input would not give float audio") }

        var callback = AURenderCallbackStruct(
            inputProc: inputUnitCallback,
            inputProcRefCon: Unmanaged.passUnretained(self).toOpaque())
        guard AudioUnitSetProperty(unit, kAudioOutputUnitProperty_SetInputCallback,
                                   kAudioUnitScope_Global, 0, &callback,
                                   UInt32(MemoryLayout<AURenderCallbackStruct>.size)) == noErr
        else { return fail("The capture callback would not attach") }

        guard AudioUnitInitialize(unit) == noErr else {
            return fail("That input would not start")
        }

        let list = AudioBufferList.allocate(maximumBuffers: 1)
        list[0].mNumberChannels = channels
        list[0].mDataByteSize = 0
        list[0].mData = nil
        bufferList = list

        guard AudioOutputUnitStart(unit) == noErr else {
            AudioUnitUninitialize(unit)
            if let l = bufferList { free(l.unsafeMutablePointer) }
            bufferList = nil
            return fail("That input would not start")
        }

        self.unit = unit
        isOpen = true
        return true
    }

    func close() {
        guard let unit else { return }
        AudioOutputUnitStop(unit)
        AudioUnitUninitialize(unit)
        AudioComponentInstanceDispose(unit)
        self.unit = nil
        if let list = bufferList { free(list.unsafeMutablePointer) }
        bufferList = nil
        isOpen = false
    }

    fileprivate func render(flags: UnsafeMutablePointer<AudioUnitRenderActionFlags>,
                            timestamp: UnsafePointer<AudioTimeStamp>,
                            bus: UInt32, frames: UInt32) {
        guard let unit, let list = bufferList else { return }
        let n = Int(frames)
        if n > capacity {
            raw.deallocate()
            capacity = n * 2
            raw = .allocate(capacity: capacity * 4)
        }
        list[0].mNumberChannels = channels
        list[0].mDataByteSize = UInt32(n * Int(channels) * 4)
        list[0].mData = UnsafeMutableRawPointer(raw)
        guard AudioUnitRender(unit, flags, timestamp, bus, frames,
                              list.unsafeMutablePointer) == noErr else { return }
        onCapture?(raw, n, channels)
    }
}

private func inputUnitCallback(
    inRefCon: UnsafeMutableRawPointer,
    ioActionFlags: UnsafeMutablePointer<AudioUnitRenderActionFlags>,
    inTimeStamp: UnsafePointer<AudioTimeStamp>,
    inBusNumber: UInt32,
    inNumberFrames: UInt32,
    ioData: UnsafeMutablePointer<AudioBufferList>?
) -> OSStatus {
    let unit = Unmanaged<InputUnit>.fromOpaque(inRefCon).takeUnretainedValue()
    unit.render(flags: ioActionFlags, timestamp: inTimeStamp,
                bus: inBusNumber, frames: inNumberFrames)
    return noErr
}

/// Fold a captured block down to interleaved stereo, applying the channel
/// choice and the gain, and report the peak.
///
/// "Mixed" AVERAGES rather than sums, so choosing it never makes a centred
/// voice six decibels louder than choosing a side.
@discardableResult
func foldToStereo(_ raw: UnsafePointer<Float>, frames: Int, channels: UInt32,
                  channel: MicChannel, gain: Float,
                  into out: UnsafeMutablePointer<Float>) -> Float {
    var loudest: Float = 0
    if channels >= 2 {
        for i in 0..<frames {
            let l = raw[i * 2], r = raw[i * 2 + 1]
            let v: Float
            switch channel {
            case .left: v = l
            case .right: v = r
            case .mix: v = (l + r) * 0.5
            }
            let scaled = v * gain
            loudest = max(loudest, abs(scaled))
            out[i * 2] = scaled
            out[i * 2 + 1] = scaled
        }
    } else {
        for i in 0..<frames {
            let scaled = raw[i] * gain
            loudest = max(loudest, abs(scaled))
            out[i * 2] = scaled
            out[i * 2 + 1] = scaled
        }
    }
    return loudest
}
