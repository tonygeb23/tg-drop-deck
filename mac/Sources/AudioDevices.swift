// Which sound cards this machine has, and how to name one in a saved board.
//
// The Windows copy saves a device by NAME plus host API, because PortAudio
// device indices move when anything is plugged in. Core Audio hands out a UID
// that is stable across reboots and replugs, so a board can name a device
// exactly rather than by a string match that a renamed interface would break.
// Both are saved: the UID is what this build uses, and the name is what it
// says out loud and what the Windows copy would match on.

import Foundation
import CoreAudio
import AudioToolbox

struct AudioDeviceInfo {
    let id: AudioDeviceID
    let uid: String
    let name: String
    let outputChannels: Int
    let inputChannels: Int
}

enum AudioDevices {

    private static func property(_ selector: AudioObjectPropertySelector,
                                 scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal)
    -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: selector, mScope: scope,
                                   mElement: kAudioObjectPropertyElementMain)
    }

    static func all() -> [AudioDeviceInfo] {
        var addr = property(kAudioHardwarePropertyDevices)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject),
                                             &addr, 0, nil, &size) == noErr else { return [] }
        let count = Int(size) / MemoryLayout<AudioDeviceID>.size
        var ids = [AudioDeviceID](repeating: 0, count: count)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),
                                         &addr, 0, nil, &size, &ids) == noErr else { return [] }
        return ids.compactMap { info(for: $0) }
    }

    static func info(for id: AudioDeviceID) -> AudioDeviceInfo? {
        guard let uid = string(id, kAudioDevicePropertyDeviceUID),
              let name = string(id, kAudioObjectPropertyName) else { return nil }
        return AudioDeviceInfo(id: id, uid: uid, name: name,
                               outputChannels: channels(id, scope: kAudioDevicePropertyScopeOutput),
                               inputChannels: channels(id, scope: kAudioDevicePropertyScopeInput))
    }

    static func outputs() -> [AudioDeviceInfo] {
        all().filter { $0.outputChannels > 0 }
    }

    static func inputs() -> [AudioDeviceInfo] {
        all().filter { $0.inputChannels > 0 }
    }

    static func deviceID(forUID uid: String) -> AudioDeviceID? {
        all().first { $0.uid == uid }?.id
    }

    static func name(forUID uid: String) -> String? {
        all().first { $0.uid == uid }?.name
    }

    static func defaultOutput() -> AudioDeviceID? {
        var addr = property(kAudioHardwarePropertyDefaultOutputDevice)
        var id = AudioDeviceID(0)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),
                                         &addr, 0, nil, &size, &id) == noErr else { return nil }
        return id
    }

    static func defaultInput() -> AudioDeviceID? {
        var addr = property(kAudioHardwarePropertyDefaultInputDevice)
        var id = AudioDeviceID(0)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),
                                         &addr, 0, nil, &size, &id) == noErr else { return nil }
        return id
    }

    static func nominalRate(_ id: AudioDeviceID) -> Double? {
        var addr = property(kAudioDevicePropertyNominalSampleRate)
        var rate: Float64 = 0
        var size = UInt32(MemoryLayout<Float64>.size)
        guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &rate) == noErr,
              rate > 0 else { return nil }
        return rate
    }

    // ------------------------------------------------------------- helpers ---

    private static func string(_ id: AudioDeviceID,
                               _ selector: AudioObjectPropertySelector) -> String? {
        var addr = property(selector)
        var value: CFString? = nil
        var size = UInt32(MemoryLayout<CFString?>.size)
        let status = withUnsafeMutablePointer(to: &value) { ptr -> OSStatus in
            AudioObjectGetPropertyData(id, &addr, 0, nil, &size, ptr)
        }
        guard status == noErr, let v = value else { return nil }
        return v as String
    }

    private static func channels(_ id: AudioDeviceID,
                                 scope: AudioObjectPropertyScope) -> Int {
        var addr = property(kAudioDevicePropertyStreamConfiguration, scope: scope)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(id, &addr, 0, nil, &size) == noErr,
              size > 0 else { return 0 }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: 16)
        defer { raw.deallocate() }
        guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, raw) == noErr else { return 0 }
        let list = UnsafeMutableAudioBufferListPointer(
            raw.assumingMemoryBound(to: AudioBufferList.self))
        return list.reduce(0) { $0 + Int($1.mNumberChannels) }
    }
}
