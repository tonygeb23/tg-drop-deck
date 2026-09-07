// The transport: two decks, a cue point, and the handover between them.
//
// A crossfade needs no special case in the mixer at all. It is one voice
// fading out while another one is already at level, on a different deck, and
// the deck indices sit above the eighty pads so nothing downstream has to know
// the playlist exists.
//
// Ported from the player half of dropdeck/playlist.py and ui.py. The order of
// the checks in tick() is load bearing and is commented where it is.

import Foundation

/// Set DROPDECK_TRACE to watch the transport decide things.
func ddTrace(_ s: @autoclosure () -> String) {
    guard ProcessInfo.processInfo.environment["DROPDECK_TRACE"] != nil else { return }
    FileHandle.standardError.write(("trace: " + s() + "\n").data(using: .utf8)!)
}

final class PlaylistPlayer {

    let playlist: Playlist
    private let group: MixerGroup

    private(set) var isPlaying = false
    private(set) var index = 0
    private(set) var lastError: String?

    /// Starts at 1 so the first item lands on deck A.
    private var deck = 1
    private var voice: Voice?
    private var timer: Timer?
    private var warnedFor: Int?

    /// Told which item is on air, so the window can speak it and retitle
    /// itself. The rows are never rewritten: what is on air is spoken, and
    /// answered on demand.
    var onMoved: ((Int, Track) -> Void)?
    var onStopped: (() -> Void)?
    /// Asked to play the end of track cue, which goes to the presenter's
    /// monitor and never to the stream.
    var onWarning: ((Int, Track, Double) -> Void)?
    /// Every bed is faded out when the playlist starts: both are music.
    var onStarting: (() -> Void)?

    var warnBeforeEnd = C.defaultWarnBeforeEnd
    var warnSeconds = C.defaultWarnSeconds

    init(playlist: Playlist, group: MixerGroup) {
        self.playlist = playlist
        self.group = group
    }

    var currentTrack: Track? {
        playlist.tracks.indices.contains(index) ? playlist.tracks[index] : nil
    }

    /// How much of the current track is left, for Command L.
    var remaining: Double? {
        guard isPlaying, let voice, let track = currentTrack else { return nil }
        let end = track.playableEnd > 0 ? track.playableEnd : (track.duration ?? 0)
        guard end > 0 else { return nil }
        return max(0, end - voice.positionSeconds)
    }

    private func nextDeck() -> Int {
        deck = 1 - deck
        return C.playlistDecks[deck]
    }

    @discardableResult
    private func start(_ at: Int, fadeIn: Double? = nil) -> Voice? {
        guard playlist.tracks.indices.contains(at) else { return nil }
        let track = playlist.tracks[at]
        let started = group.primary.play(
            slotIndex: nextDeck(), path: track.filepath, bus: C.busPlaylist,
            loop: false, trimDB: track.trimDB, name: track.displayName,
            duration: track.duration,
            fadeIn: fadeIn ?? C.segueFadeIn,
            // Pre-loaded with this item's own handover, so a later release with
            // no argument rides down over exactly the right time.
            fadeOut: playlist.handoverAt(at))
        guard let started else {
            lastError = "\(track.displayName) would not open"
            return nil
        }
        ddTrace("start row \(at) \(track.displayName) duration=\(track.duration ?? -1) "
                + "tail=\(track.tailSilence ?? -1)")
        index = at
        voice = started
        warnedFor = nil
        onMoved?(at, track)
        return started
    }

    @discardableResult
    func play(from at: Int) -> Bool {
        stop(fadeOut: 0.05, quiet: true)
        guard let first = playlist.willPlay(at) ? at : playlist.firstPlayable(from: at)
        else {
            lastError = "There is nothing in the running order to play"
            return false
        }
        onStarting?()
        guard start(first) != nil else { return false }
        isPlaying = true
        startTicking()
        return true
    }

    func stop(fadeOut: Double? = nil, quiet: Bool = false) {
        ddTrace("player.stop quiet=\(quiet) wasPlaying=\(isPlaying) index=\(index)")
        timer?.invalidate(); timer = nil
        // Stopping in the middle of a crossfade has to take the outgoing song
        // down too: it is releasing over the whole overlap and would otherwise
        // play on for seconds after somebody pressed stop.
        for slot in C.playlistDecks {
            group.stopSlot(slot, fadeOut: fadeOut, alsoReleasing: true)
        }
        voice = nil
        isPlaying = false
        if !quiet { onStopped?() }
    }

    @discardableResult
    func next() -> Bool {
        guard let following = playlist.nextPlaying(after: index) else {
            stop(fadeOut: C.fadeOutBed)
            return false
        }
        return handOver(to: following)
    }

    @discardableResult
    func previous() -> Bool {
        guard let before = playlist.previousPlaying(before: index) else { return false }
        return play(from: before)
    }

    /// Segue into a chosen item out of whatever is on air.
    @discardableResult
    func segue(to at: Int) -> Bool {
        guard isPlaying else { return play(from: at) }
        return handOver(to: at)
    }

    private func startTicking() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(
            withTimeInterval: Double(C.playlistTickMS) / 1000.0, repeats: true) {
            [weak self] _ in self?.tick()
        }
    }

    @discardableResult
    private func handOver(to following: Int?) -> Bool {
        var overlap = playlist.handoverAt(index)
        if overlap <= 0 {
            // A manual segue out of the last item, which has no handover of its
            // own because nothing follows it in the running order.
            overlap = max(playlist.crossfade, C.segueLead)
        }
        let outgoing = voice
        guard let following, let started = start(following, fadeIn: C.segueFadeIn) else {
            return false
        }
        // The incoming track is already AT LEVEL and the outgoing one rides
        // down under it. Both of them ramping is a DJ blend, not a radio segue.
        if let outgoing, outgoing !== started {
            outgoing.release(fadeOut: overlap)
        }
        isPlaying = true
        startTicking()
        return true
    }

    /// Rows were put in above or at the one on air, so the one on air has moved
    /// down the list. Without this, the next handover would count from the
    /// wrong row and replay whatever slid into its old place.
    func rowsInserted(at row: Int, count: Int) {
        guard isPlaying, count > 0, row <= index else { return }
        index += count
    }

    /// The running order was replaced under the player. Nothing is on air and
    /// nothing is remembered about what was.
    func forget() {
        stop(fadeOut: 0.05, quiet: true)
        index = 0
        warnedFor = nil
    }

    /// The self test drives the transport by hand, with no timer and no sound
    /// card, which is the only way to prove a handover deterministically.
    func tickForTesting() { tick() }

    private func tick() {
        guard isPlaying, let voice else { return }
        guard let track = currentTrack else { stop(); return }

        ddTrace("tick pos=\(String(format: "%.2f", voice.positionSeconds)) "
                + "finished=\(voice.finished) end=\(track.playableEnd) "
                + "handover=\(playlist.handoverAt(index))")
        if voice.finished {
            // The file ran out on its own, so there is no crossfade to do.
            guard let following = playlist.firstPlayable(from: index + 1) else {
                stop()
                return
            }
            if start(following) == nil {
                // Without this the player would keep the finished voice, come
                // back in fifty milliseconds and try the same broken file
                // again, for ever, in silence.
                stop()
            }
            return
        }

        let end = track.playableEnd
        checkWarning(end: end, voice: voice)
        guard end > 0 else { return }

        let overlap = playlist.handoverAt(index)
        guard overlap > 0 else { return }
        guard voice.positionSeconds >= end - overlap else { return }
        _ = handOver(to: playlist.firstPlayable(from: index + 1))
    }

    /// The countdown a sighted presenter watches on a clock.
    ///
    /// Fires once per track, and never on an item shorter than the warning
    /// itself plus a second: a nine second ident with a ten second warning
    /// would beep the moment it started.
    private func checkWarning(end: Double, voice: Voice) {
        guard warnBeforeEnd, warnSeconds > 0, end > warnSeconds + 1.0 else { return }
        guard warnedFor != index else { return }
        guard voice.positionSeconds >= end - warnSeconds else { return }
        warnedFor = index
        if let track = currentTrack { onWarning?(index, track, warnSeconds) }
    }
}
