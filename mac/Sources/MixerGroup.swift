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
    ///
    /// **Until 3.7.1 this returned the main output whatever the board said.**
    /// Preferences has offered "Hear yourself through" since the microphone
    /// landed, it was saved, it was carried across a File Open, and nothing
    /// anywhere read it: monitoring came out of the main card every time. A
    /// setting that does nothing is worse than no setting, because somebody
    /// who cannot see it has no way to tell.
    var monitorMixer: Mixer { monitor ?? primary }

    /// The card the presenter listens on, when it is not one of the cards the
    /// show is already coming out of.
    private(set) var monitor: Mixer?
    private(set) var monitorUID: String?

    /// Does the monitor carry every card's show, or only what is routed to it.
    ///
    /// On by default. With one sound card it costs nothing at all: there are no
    /// other mixers, so there is no bus, no ring and no added latency anywhere
    /// near the path between a key and a sound.
    private(set) var monitorEverything = true
    private var monitorBus: AirBus?

    var isRunning: Bool { mixers.values.contains { $0.isRunning } }
    var lastError: String? { primary?.lastError ?? mixers.values.compactMap(\.lastError).first }
    var sampleRate: Double { primary?.sampleRate ?? C.defaultSampleRate }

    init(mainDeviceUID: String?, bankDevices: [Int: String],
         monitorDeviceUID: String? = nil, monitorEverything: Bool = true) {
        cache = DecodeCache(rate: C.defaultSampleRate)
        self.monitorEverything = monitorEverything
        rebuild(mainDeviceUID: mainDeviceUID, bankDevices: bankDevices,
                monitorDeviceUID: monitorDeviceUID)
    }

    func rebuild(mainDeviceUID: String?, bankDevices: [Int: String],
                 monitorDeviceUID: String? = nil) {
        stop()
        mixers.removeAll()
        bankMixer.removeAll()
        monitor = nil
        monitorUID = monitorDeviceUID

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
        wireMonitorMixer(monitorDeviceUID)
    }

    /// Give the presenter's own card a mixer, making one if the show is not
    /// already coming out of it.
    ///
    /// A monitor card that is ALSO a bank card is not a second mixer: it is
    /// that one. Two mixers on one device is two output streams fighting over
    /// the same hardware, which is the one arrangement Core Audio will let you
    /// build and will not let you hear.
    private func wireMonitorMixer(_ uid: String?) {
        guard let uid, !uid.isEmpty else { monitor = nil; return }
        if let existing = mixers[uid] { monitor = existing; return }
        let m = Mixer(key: uid, deviceUID: uid, sampleRate: C.defaultSampleRate,
                      duckBus: duckBus, cache: cache)
        mixers[uid] = m
        monitor = m
    }

    /// Give the card the presenter listens on every other card's show.
    ///
    /// One bus, written by every mixer except the monitor's own and drained by
    /// that one. The monitor mixer is left out of its own bus for the obvious
    /// reason: what it plays already comes out of the card it is playing on,
    /// and putting it through the ring as well would be a second copy of itself
    /// a few milliseconds late.
    ///
    /// **With one sound card this does nothing at all**, which is the ordinary
    /// case: there are no other mixers, so there is no bus, no ring and no
    /// added latency on the path between a key and a sound.
    func wireMonitor() {
        for m in mixers.values { m.monitorTap = nil; m.monitorFeed = nil }
        monitorBus = nil
        guard monitorEverything, let listening = monitor ?? primary else { return }
        let others = mixers.values.filter { $0 !== listening }
        guard !others.isEmpty else { return }
        let bus = AirBus(sampleRate: listening.sampleRate,
                         seconds: C.monitorRingSeconds)
        monitorBus = bus
        listening.monitorFeed = bus
        for m in others { m.monitorTap = bus }
    }

    /// Turn the full programme monitor on or off, and rewire. True if it moved.
    @discardableResult
    func setMonitorEverything(_ on: Bool) -> Bool {
        guard on != monitorEverything else { return false }
        monitorEverything = on
        wireMonitor()
        return true
    }

    /// Times the monitor feed ran dry. A monitoring fault, never an air one.
    var monitorGaps: Int { mixers.values.reduce(0) { $0 + $1.monitorGaps } }

    // ------------------------------------------------------------ the send ---

    /// Where the whole show goes for another program on this machine, or nil.
    /// Set on EVERY mixer, because a bank on its own card is part of the show.
    var sendTap: ProgramTap? {
        get { primary?.sendTap }
        set { for m in mixers.values { m.sendTap = newValue } }
    }

    /// The one source the send leaves out. Only the mixer holding the sources
    /// can act on it, but it is set everywhere so nothing has to know which.
    var sendMinus: String? {
        get { primary?.sendMinus }
        set { for m in mixers.values { m.sendMinus = newValue } }
    }

    // ------------------------------------------------- are they keeping up ---

    var lateBlocks: Int { mixers.values.reduce(0) { $0 + $1.lateBlocks } }

    /// The worst answer any of the outputs gives, because one card stuttering
    /// is the whole show stuttering as far as a listener is concerned.
    func keepingUp() -> (Bool, String) {
        for m in mixers.values {
            let (ok, why) = m.keepingUp()
            if !ok { return (false, why) }
        }
        return (true, "keeping up")
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
        // After `start`, because the ring is sized from the rate the card
        // really answered with rather than the one that was guessed.
        wireMonitor()
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
