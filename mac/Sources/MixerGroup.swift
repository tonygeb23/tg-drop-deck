// One mixer per sound card, and the things that have to be shared between them.
//
// A bank may be routed to its own sound card, so a broadcaster can ride levels
// on a desk. Banks sharing a device share a mixer, so the common case of one
// output is still one stream. Ducking is shared through a DuckBus precisely so
// that routing the beds elsewhere does not silently disable it.

import Foundation

final class MixerGroup {

    private(set) var mixers: [String: Mixer] = [:]   // device key to mixer
    private(set) var bankMixer: [Int: Mixer] = [:]
    private(set) var primary: Mixer!

    let duckBus = DuckBus()

    /// Where the programme goes. Nothing is summed into it until something is
    /// listening, because building the air sum costs a second pass over every
    /// block and there is no reason to pay for it off air.
    let taps = Taps()
    private var cache: DecodeCache

    /// The presenter's headphones when one is set, the ordinary output when it
    /// is not. A cue is for the person running the show.
    var monitorMixer: Mixer { primary }

    var isRunning: Bool { mixers.values.contains { $0.isRunning } }
    var lastError: String? { primary?.lastError ?? mixers.values.compactMap(\.lastError).first }
    var sampleRate: Double { primary?.sampleRate ?? C.defaultSampleRate }

    init(mainDeviceUID: String?, bankDevices: [Int: String]) {
        cache = DecodeCache(rate: C.defaultSampleRate)
        rebuild(mainDeviceUID: mainDeviceUID, bankDevices: bankDevices)
    }

    func rebuild(mainDeviceUID: String?, bankDevices: [Int: String]) {
        stop()
        mixers.removeAll()
        bankMixer.removeAll()

        let mainKey = mainDeviceUID ?? "default"
        let main = Mixer(key: mainKey, deviceUID: mainDeviceUID,
                         sampleRate: C.defaultSampleRate, duckBus: duckBus, cache: cache)
        mixers[mainKey] = main
        primary = main

        for bank in 1...C.bankCount {
            let uid = bankDevices[bank]
            let key = uid ?? mainKey
            if key == mainKey {
                bankMixer[bank] = main
            } else if let existing = mixers[key] {
                bankMixer[bank] = existing
            } else {
                let m = Mixer(key: key, deviceUID: uid, sampleRate: C.defaultSampleRate,
                              duckBus: duckBus, cache: cache)
                mixers[key] = m
                bankMixer[bank] = m
            }
        }
    }

    func start() {
        if !taps.isEmpty {
            for m in mixers.values { m.tap = taps }
        }
        for m in mixers.values { m.start() }
        // Everything cached was decoded for whatever rate we guessed before a
        // device answered. If the real one differs, throw it away once here
        // rather than have each voice discover it.
        if let rate = primary?.sampleRate, cache.rate != rate {
            cache.clear(newRate: rate)
        }
    }

    func stop() {
        for m in mixers.values { m.stop() }
    }

    /// Start feeding the programme bus. Called when a recording or a stream
    /// starts.
    func addAirBus(_ bus: AirBus) {
        taps.add(bus)
        for m in mixers.values { m.tap = taps }
    }

    func removeAirBus(_ bus: AirBus) {
        taps.remove(bus)
        syncTaps()
    }

    /// Feed the programme bus only while something is listening. Building the
    /// air sum costs a second pass over every block and there is no reason to
    /// pay for it off air.
    func syncTaps() {
        let wanted: ProgramTap? = taps.isEmpty ? nil : taps
        for m in mixers.values { m.tap = wanted }
    }

    func mixer(forSlot index: Int) -> Mixer {
        if index < C.totalSlots {
            return bankMixer[bankForIndex(index)] ?? primary
        }
        // The playlist decks, the cue and the preview all live on the main
        // output. They are not a bank and have no routing of their own.
        return primary
    }

    func apply(_ board: Board) {
        for m in mixers.values {
            m.sfxGain = board.sfxVolume
            m.bedGain = board.bedVolume
            m.playlistGain = board.playlistVolume
            m.ducking = board.ducking
            m.duckDB = board.duckDB
            m.bedFadeIn = board.bedFadeIn
            m.bedFadeOut = board.bedFadeOut
        }
    }

    func setBusGain(_ bus: String, _ value: Float) {
        for m in mixers.values { m.setBusGain(bus, value) }
    }

    var ducking: Bool {
        get { primary?.ducking ?? true }
        set { for m in mixers.values { m.ducking = newValue } }
    }

    @discardableResult
    func stopAll(fadeOut: Double? = nil) -> Int {
        mixers.values.reduce(0) { $0 + $1.stopAll(fadeOut: fadeOut) }
    }

    @discardableResult
    func stopSlot(_ index: Int, fadeOut: Double? = nil, alsoReleasing: Bool = false) -> Int {
        mixers.values.reduce(0) {
            $0 + $1.stopSlot(index, fadeOut: fadeOut, alsoReleasing: alsoReleasing)
        }
    }

    func isPlaying(slotIndex: Int) -> Bool {
        mixers.values.contains { $0.isPlaying(slotIndex: slotIndex) }
    }

    var playingSlots: Set<Int> {
        Set(mixers.values.flatMap { $0.playingSlots })
    }

    var playingNames: [String] {
        mixers.values.flatMap { $0.playingNames }
    }

    /// Decode every short sound in the background, so the first press of a key
    /// costs nothing. Measured on the Windows copy: 87.5 ms cold, 0.6 ms warm.
    func warmCache(_ board: Board) {
        DispatchQueue.global(qos: .utility).async { [cache] in
            for slot in board.slots {
                guard let path = slot.filepath, !path.isEmpty else { continue }
                if slot.isFolder {
                    slot.scanFolder()
                    for file in slot.folderFileList.prefix(8) {
                        if let d = AudioFile.probe(file)?.duration, d <= C.preloadSeconds {
                            _ = cache.cached(file)
                        }
                    }
                    continue
                }
                guard let d = slot.duration ?? AudioFile.probe(path)?.duration else { continue }
                if d <= C.preloadSeconds { _ = cache.cached(path) }
            }
        }
    }
}
