// Sending the show to another program on this machine.
//
// A mirror of dropdeck/send.py. Tony, 9 September 2026: "if I want team talk to
// be able to take audio from TG Drop Deck itself ... really anything that TG
// Drop Deck is catching."
//
// Until now the only way to get Drop Deck into another program was to point the
// main output at a virtual cable, and that gives the other program the pads,
// the beds and the running order and **nothing else**. The microphone and every
// source Drop Deck captures live on the air bus, and the air bus only exists
// while you are streaming or recording. So the show and the send were two
// different mixes and the second one was missing the presenter.
//
// A send is the air bus, out of a sound card, whether or not anything is live.
// Same sum the listener would get, same rules: monitoring is not in it, the
// running order is in it at full level however far down the fader is in the
// room.
//
// ## Mix minus, and why it is a subtraction
//
// Tony's board captures TeamTalk as a source and puts it on the air. Send that
// mix back to TeamTalk and everybody in the call hears themselves a quarter of
// a second late, which is the oldest fault in broadcasting and the reason mix
// minus exists.
//
// So a send names one source to leave out. It cannot do that by summing the
// sources again without it, because reading a source takes the audio away from
// it: two sums would each get half a voice. `SourceGroup.read(frames:into:
// minus:taken:)` does the one read every callback already does and hands back
// that source's own block, and `Mixer.render` subtracts it, which is exact
// because everything upstream of the soft clip is a plain sum.
//
// ## Why it does not share the main output's stream
//
// Two reasons, and the first one is measured.
//
// A soundboard wants a short output buffer, because the gap between the key and
// the sound is the whole product. A send wants a deep one, because there is
// already a hundred milliseconds of network between here and the other person
// and nobody can hear another twenty. Sharing a stream would mean choosing, and
// the choice would be wrong for one of them.
//
// The second is that the send has its own sound card and therefore its own
// clock. The `AirBus` is what absorbs the difference: it is written by the
// mixers' callbacks and drained by this one, and neither has to know the other
// exists.
//
// ## The buffer size, which is where the two platforms differ
//
// Windows 3.6.0 was largely ABOUT this number. Every PortAudio output it opened
// asked the card for a fixed 512 frames, which is fine on real hardware and
// loses audio into a virtual cable: measured on a real cable, seven runs in ten
// lost audio, median 2.67 per cent, about six gaps a second, and PortAudio
// reported a perfectly healthy stream throughout.
//
// **A Mac cannot have that fault, and it is worth knowing why rather than being
// pleased about it.** An AUHAL output unit is not asked for a block size at
// all: `coreaudiod` calls back with the device's own buffer, and `DeviceOutput`
// has never set `kAudioDevicePropertyBufferFrameSize` or a maximum frames per
// slice. So the Mac has always had what Windows had to be changed to have.
// `C.sendBlockFrames` is therefore a REQUEST made of the device and not a
// promise made to the mixer, and `Mixer.timeBlock` times the callback anyway,
// because "the driver says it is fine" is exactly what Windows was told.

import Foundation
import AudioToolbox

/// What the send is putting out, for the presenter's own headphones.
///
/// Shaped like a source rather than like a mixer input, because that is what
/// `SourceGroup` already sums: `readMonitor` is what you hear and `readAir` is
/// what the listener hears. **A confidence feed answers SILENCE to the second
/// one, and that single fact is what stops it going round for ever.** It is
/// heard on the monitor output, it is never on the air, and it can therefore
/// never arrive back in the send it came from.
///
/// Off by default. A presenter who is not listening to it pays for one boolean
/// per block.
final class Confidence: RunningSource {

    var config: SourceConfig
    private(set) var lastError: String?
    private(set) var peak: Float = 0
    private(set) var on = false
    private let ring: AudioRing

    var isRunning: Bool { on }

    init(frames: Int) {
        ring = AudioRing(frames: max(256, frames))
        var c = SourceConfig()
        c.id = "dropdeck.send.confidence"
        c.name = "The send"
        c.onAir = false
        c.monitor = true
        config = c
    }

    @discardableResult func start(outputRate: Double) -> Bool { start(); return true }

    func start() {
        ring.clear()
        peak = 0
        on = true
    }

    func stop() {
        on = false
        peak = 0
        ring.clear()
    }

    /// Called from the send's own callback. Never blocks.
    func offer(_ samples: UnsafePointer<Float>, frames: Int) {
        guard on else { return }
        ring.push(samples, count: frames)
    }

    /// What the presenter hears.
    func readMonitor(frames: Int, into out: UnsafeMutablePointer<Float>) {
        guard on else {
            out.update(repeating: 0, count: frames * 2)
            return
        }
        ring.pull(out, count: frames)
        var p: Float = 0
        for i in 0..<(frames * 2) { p = max(p, abs(out[i])) }
        peak = p
    }

    /// What the listener hears, which is nothing. See the note above.
    func readAir(frames: Int, into out: UnsafeMutablePointer<Float>) {
        out.update(repeating: 0, count: frames * 2)
    }
}

/// The on air mix, out of a sound card, live or not.
final class Send {

    /// nil is the system default output.
    private(set) var deviceUID: String?
    private(set) var sampleRate: Double
    var gainDB: Float
    private(set) var lastError: String?

    /// Rebuilt if the card answers with a rate it did not advertise, which is
    /// why the caller points its `sendTap` at this AFTER `start` returns rather
    /// than before.
    private(set) var bus: AirBus
    private(set) var confidence: Confidence

    /// How full the ring has to be before a single sample goes out, and again
    /// after it has ever run dry. Two sound cards are never quite the same
    /// speed, so over a long show the ring drains or fills; a jitter buffer is
    /// what turns that into one inaudible correction rather than a permanent
    /// stutter.
    private var primeFrames: Int
    private let primeSeconds: Double
    private var primed = false

    /// What to say when asked how it is doing.
    private(set) var blocks = 0
    private(set) var starved = 0
    private(set) var rebuffers = 0
    private(set) var peak: Float = 0

    private var output: DeviceOutput?
    private var scratch: UnsafeMutablePointer<Float>
    private var capacity = 8192

    init(deviceUID: String?, gainDB: Float = 0, openStream: Bool = true,
         primeSeconds: Double? = nil) {
        self.deviceUID = deviceUID
        self.gainDB = gainDB
        // The device's own rate, asked for before anything is opened, so the
        // ring is the right size the first time rather than after a rebuild.
        let named = deviceUID.flatMap { AudioDevices.deviceID(forUID: $0) }
        let rate = (named ?? AudioDevices.defaultOutput())
            .flatMap { AudioDevices.nominalRate($0) } ?? C.defaultSampleRate
        sampleRate = rate
        bus = AirBus(sampleRate: rate, seconds: C.sendRingSeconds)
        confidence = Confidence(frames: Int(rate * C.sendMonitorSeconds))
        self.primeSeconds = primeSeconds ?? C.sendPrimeSeconds
        primeFrames = Int(rate * self.primeSeconds)
        scratch = .allocate(capacity: capacity * 2)
        if openStream { start() }
    }

    deinit { scratch.deallocate() }

    /// Is audio really going out of this, not merely was a card opened.
    ///
    /// An unplugged card looks to a driver like a stream that is still there,
    /// and the object stays put: on Windows `sending()` said yes, the tap
    /// stayed on, the status line kept saying SENDING and the report kept
    /// saying "Sending to", with nothing coming out. Found by Mark, 10
    /// September 2026.
    var isRunning: Bool { output?.isRunning ?? false }

    /// Open the output. True if audio is really going out of it.
    @discardableResult
    func start() -> Bool {
        stopStream()
        primed = false
        blocks = 0
        starved = 0
        rebuffers = 0
        bus.reset()
        let out = DeviceOutput(deviceUID: deviceUID)
        out.render = { [weak self] buf, frames in
            self?.fill(buf, frames: frames)
        }
        guard out.start() else {
            lastError = out.lastError ?? "the card would not open"
            return false
        }
        output = out
        if abs(out.sampleRate - sampleRate) > 0.5 {
            // The card answered with a rate it did not advertise. An AirBus
            // fixes its rate at birth, so this is a new one. Nothing is lost:
            // the mixers are not pointed at it until this returns.
            sampleRate = out.sampleRate
            bus = AirBus(sampleRate: sampleRate, seconds: C.sendRingSeconds)
            primeFrames = Int(sampleRate * primeSeconds)
            let hearing = confidence.on
            confidence = Confidence(frames: Int(sampleRate * C.sendMonitorSeconds))
            if hearing { confidence.start() }
        }
        lastError = nil
        return true
    }

    func stopStream() {
        output?.stop()
        output = nil
    }

    func close() {
        stopStream()
        confidence.stop()
        bus.reset()
    }

    func describe() -> String {
        guard let uid = deviceUID else { return "the system default output" }
        return AudioDevices.outputs().first { $0.uid == uid }?.name ?? uid
    }

    private func grow(_ frames: Int) {
        guard frames > capacity else { return }
        scratch.deallocate()
        capacity = frames * 2
        scratch = .allocate(capacity: capacity * 2)
    }

    // ----------------------------------------------------------------- audio ---

    private func fill(_ out: UnsafeMutablePointer<Float>, frames: Int) {
        let count = frames * 2
        grow(frames)
        blocks += 1
        let have = bus.available()
        if !primed {
            if have < primeFrames {
                out.update(repeating: 0, count: count)
                return
            }
            primed = true
        }
        if have < frames {
            // The ring ran dry. Say so, and fill up again rather than limp
            // along starving on every block from here on: the two cards have
            // drifted apart and one short silence beats a permanent stutter.
            starved += 1
            rebuffers += 1
            primed = false
            out.update(repeating: 0, count: count)
            return
        }
        bus.read(frames: frames, into: out)
        let gain = gainDB == 0 ? Float(1) : dbToGain(gainDB)
        var p: Float = 0
        if gain != 1 {
            for i in 0..<count { out[i] *= gain }
        }
        for i in 0..<count { p = max(p, abs(out[i])) }
        peak = p
        confidence.offer(out, frames: frames)
    }

    // ---------------------------------------------------------------- health ---

    /// Is the audio arriving clean, and one line saying why if it is not.
    ///
    /// Deliberately NOT the question of whether the send is switched on. That
    /// one is `isRunning`, and the report is what puts the two together:
    /// keeping this to the audio alone is what makes it answerable with no
    /// sound card in the machine.
    func keepingUp() -> (Bool, String) {
        if blocks == 0 { return (true, "the send is open and nothing has played yet") }
        if rebuffers > 0 {
            return (false, "the send has had to rebuffer \(rebuffers) "
                + (rebuffers == 1 ? "time" : "times"))
        }
        if bus.dropped > 0 {
            return (false, "the send has dropped \(bus.dropped) "
                + (bus.dropped == 1 ? "block" : "blocks"))
        }
        return (true, "the send is arriving clean")
    }

    /// The whole answer to "how is the send doing", as one spoken line.
    func report() -> String {
        guard output != nil else {
            return "The send is off. \(lastError ?? "Nothing is being sent.")"
        }
        let (_, why) = keepingUp()
        let said = why.prefix(1).uppercased() + why.dropFirst()
        let hearing = confidence.on ? "You are hearing it." : "You are not hearing it."
        return "Sending to \(describe()) at \(Int(sampleRate)) hertz. \(said). \(hearing)"
    }
}
