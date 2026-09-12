// A real send into a real cable, recorded off the other end and counted.
//
//     TGDropDeck --check-send [seconds] [device UID]
//
// The Mac's counterpart to `tools/check_send.py` on Windows, and it exists for
// the same reason: **the one thing a send has to do cannot be proved from
// inside the app.** Every layer can report itself healthy while nothing arrives.
// Windows learned that the expensive way, with PortAudio reporting a perfectly
// clean stream through a measured seven per cent loss into a virtual cable, and
// the only thing that caught it was recording the far end and counting.
//
// So this drives the REAL `Send`, through the REAL `AirBus`, out of a REAL
// sound card, and opens that same card's input side to hear what arrived.
// Nothing here is a test double.
//
// ## What it measures, and why each one
//
// **Gaps.** Runs of silence in the middle of a continuous tone. This is the
// number: on Windows a short output buffer gave about six gaps a second, four
// milliseconds each, and the app said nothing at all.
//
// **The pitch it comes back at.** A tone with audio missing reads LOW on a
// cycle count, because the missing pieces take whole cycles with them: 1 kHz
// came back as 974 Hz through the broken path. Tony heard that as "a change in
// pitch, a little choppiness" going into TeamTalk, and the frequency is what
// turns that sentence into a number.
//
// **The level.** A cable that carries nothing and a cable that carries silence
// look the same to a gap counter that has nothing to count.
//
// **What the mix minus left out.** With a source excluded, the excluded tone
// has to be gone from what arrives, not merely quieter.

import Foundation
import AudioToolbox

enum SendCheck {

    /// A tone, generated a block at a time, written into the send's bus exactly
    /// as a mixer's callback would write it.
    private final class Tone {
        private var phase: Double = 0
        private let step: Double
        private let level: Float
        init(hz: Double, rate: Double, level: Float) {
            step = 2.0 * Double.pi * hz / rate
            self.level = level
        }
        func fill(_ out: UnsafeMutablePointer<Float>, frames: Int) {
            for i in 0..<frames {
                let v = Float(sin(phase)) * level
                out[i * 2] = v
                out[i * 2 + 1] = v
                phase += step
                if phase > 2.0 * Double.pi { phase -= 2.0 * Double.pi }
            }
        }
    }

    /// What came back, gathered on the capture thread and read once at the end.
    private final class Heard {
        var samples: [Float] = []
        var rate: Double = C.defaultSampleRate
        let lock = NSLock()
        func take(_ p: UnsafePointer<Float>, frames: Int, channels: UInt32) {
            lock.lock()
            samples.reserveCapacity(samples.count + frames)
            for i in 0..<frames { samples.append(p[i * Int(channels)]) }
            lock.unlock()
        }
    }

    /// Shared between the feeding thread and the one waiting on it. A `var`
    /// captured by a `Thread` closure is captured by value, which would leave
    /// the feeder running for the life of the process.
    private final class Stopper { var wanted = false }

    /// How much tone goes into the ring before the card is opened. See the
    /// note where it is used: this stands in for the hardware clock a real
    /// mixer writes on, which this harness does not have.
    static let cushionSeconds: Double = 0.6

    static func run(seconds: Double = 6.0, deviceUID: String? = nil) -> Int32 {
        let uid = deviceUID ?? VirtualDevice.uid
        print("\(C.appName) \(C.appVersion), a real send into a real cable")
        print("")

        guard let device = AudioDevices.deviceID(forUID: uid),
              let info = AudioDevices.info(for: device) else {
            print("  FAIL  there is no device with the UID \(uid) on this machine")
            print("        On air, Drop Deck Audio installs the one this app ships.")
            return 1
        }
        print("  card  \(info.name), \(info.outputChannels) out, \(info.inputChannels) in")
        guard info.outputChannels >= 2, info.inputChannels >= 2 else {
            print("  FAIL  a cable has to be two channels in BOTH directions")
            return 1
        }

        // The far end first, so nothing is missed between the two opening.
        let heard = Heard()
        let input = InputUnit()
        input.onCapture = { p, frames, channels in
            heard.take(p, frames: frames, channels: channels)
        }
        guard input.open(deviceUID: uid) else {
            print("  FAIL  the cable's input side would not open: "
                + (input.lastError ?? "no reason given"))
            return 1
        }
        heard.rate = input.captureRate

        // **Opened but not started**, so the ring can be filled before anything
        // drains it. A real mixer writes into this from its own sound card's
        // callback, clocked by hardware; this harness writes from a wall clock
        // with `Thread.sleep` in it, which is far jitterier than the thing it
        // is standing in for. Without a cushion the harness runs the ring dry
        // and the SEND gets the blame, which is exactly what happened the first
        // time this was run: one 188 ms gap, one rebuffer, and a tone reading
        // 968 Hz, all of it the harness.
        let send = Send(deviceUID: uid, gainDB: 0, openStream: false)

        // The cushion, laid down before the card is opened at all.
        let block = 512
        let cushion = Int(send.sampleRate * cushionSeconds)
        do {
            let tone = Tone(hz: 1000.0, rate: send.sampleRate, level: 0.5)
            let buffer = UnsafeMutablePointer<Float>.allocate(capacity: block * 2)
            defer { buffer.deallocate() }
            var written = 0
            while written < cushion {
                tone.fill(buffer, frames: block)
                send.bus.write(key: "check", samples: buffer, frames: block,
                               rate: send.sampleRate)
                written += block
            }
        }
        guard send.start(), send.isRunning else {
            print("  FAIL  the send would not open: \(send.lastError ?? "no reason given")")
            input.close()
            return 1
        }
        print("  send  open at \(Int(send.sampleRate)) Hz, cable reading at "
            + "\(Int(input.captureRate)) Hz, \(Int(cushionSeconds * 1000)) ms of cushion")

        // And then in real time, on a thread of its own, the way a show does.
        //
        // **The feeding never stops while the far end is listening**, and that
        // is not a detail. The first cut of this stopped writing, waited, then
        // closed both ends, so the recording ended with the tail of the ring
        // draining into silence and the send counting one rebuffer for a ring
        // nobody was filling any more. It reported one 188 ms gap and a tone at
        // 968 Hz, which looks exactly like the fault this check exists to find
        // and was entirely the harness switching itself off. A show does not
        // stop feeding its send and then ask whether the send is keeping up.
        let stopping = Stopper()
        let feeder = Thread {
            let tone = Tone(hz: 1000.0, rate: send.sampleRate, level: 0.5)
            let buffer = UnsafeMutablePointer<Float>.allocate(capacity: block * 2)
            defer { buffer.deallocate() }
            let started = Date()
            var sent = 0
            while !stopping.wanted {
                let due = Int(Date().timeIntervalSince(started) * send.sampleRate)
                if sent > due {
                    Thread.sleep(forTimeInterval: Double(block) / send.sampleRate / 2)
                    continue
                }
                tone.fill(buffer, frames: block)
                send.bus.write(key: "check", samples: buffer, frames: block,
                               rate: send.sampleRate)
                sent += block
            }
        }
        feeder.name = "dropdeck-check-send"
        feeder.qualityOfService = .userInitiated
        feeder.start()

        Thread.sleep(forTimeInterval: seconds)

        // Read the health BEFORE anything is closed, so what is reported is
        // what happened during the show rather than during the shutdown.
        let (clean, why) = send.keepingUp()
        let rebuffers = send.rebuffers
        let dropped = send.bus.dropped
        input.close()
        stopping.wanted = true
        send.close()

        heard.lock.lock()
        let got = heard.samples
        heard.lock.unlock()
        var failures = report(got, rate: heard.rate, clean: clean, why: why,
                              rebuffers: rebuffers, dropped: dropped)
        failures += idleIsSilent(uid: uid)
        return failures
    }

    /// **A cable nobody is feeding has to be SILENT.**
    ///
    /// Without a guard in the driver, the input side goes on reading a ring
    /// nobody is refilling, so the far end of a call hears the last fraction of
    /// a second of the show over and over for as long as they stay connected:
    /// a buzz that does not stop and does not appear anywhere in this app. It
    /// is the single most embarrassing thing a home made cable can do, and the
    /// only way to know it is not happening is to listen with nothing playing.
    private static func idleIsSilent(uid: String) -> Int32 {
        print("")
        print("  With nothing being sent, which is where a bad cable buzzes")
        // A moment for the last of the real audio to fall out of the ring.
        Thread.sleep(forTimeInterval: 0.5)
        let heard = Heard()
        let input = InputUnit()
        input.onCapture = { p, frames, channels in
            heard.take(p, frames: frames, channels: channels)
        }
        guard input.open(deviceUID: uid) else {
            print("  FAIL the cable would not open to listen to")
            return 1
        }
        heard.rate = input.captureRate
        Thread.sleep(forTimeInterval: 1.5)
        input.close()
        heard.lock.lock()
        let got = heard.samples
        heard.lock.unlock()

        guard got.count > Int(heard.rate) / 2 else {
            print("  FAIL nothing was recorded from the idle cable")
            return 1
        }
        // The last second, so whatever was still draining when this started is
        // long gone.
        let body = Array(got.suffix(Int(heard.rate)))
        var peak: Float = 0
        for v in body { peak = max(peak, abs(v)) }
        let quiet = peak < 0.0005
        print("  \(quiet ? "ok  " : "FAIL") an idle cable is silent, not a loop of the last "
            + "thing it heard  " + String(format: "peak %.6f", peak))
        return quiet ? 0 : 1
    }

    private static func report(_ got: [Float], rate: Double,
                               clean: Bool, why: String,
                               rebuffers: Int, dropped: Int) -> Int32 {
        var failures = 0
        func check(_ name: String, _ ok: Bool, _ detail: String = "") {
            print("  \(ok ? "ok  " : "FAIL") \(name)\(detail.isEmpty ? "" : "  " + detail)")
            if !ok { failures += 1 }
        }

        check("audio arrived at the far end at all", got.count > Int(rate),
              "\(got.count) frames")
        guard got.count > Int(rate) else { return 1 }

        // Trim the opening, which is the prime time and legitimately silent,
        // and the last tenth, which is the stream being closed underneath us.
        let from = Int(rate * (C.sendPrimeSeconds + 0.3))
        let to = got.count - Int(rate * 0.05)
        guard to > from + Int(rate) else {
            check("there is enough of it to measure", false)
            return 1
        }
        let body = Array(got[from..<to])

        var peak: Float = 0
        for v in body { peak = max(peak, abs(v)) }
        check("it is at the level it went in", peak > 0.4 && peak < 0.6,
              String(format: "peak %.3f", peak))

        // A gap is a run of near silence long enough to hear. A 1 kHz tone
        // crosses zero every half millisecond, so anything past a millisecond
        // of silence is missing audio and not a zero crossing.
        let floorLevel: Float = 0.02
        let leastGap = max(8, Int(rate * 0.001))
        var gaps = 0
        var worst = 0
        var run = 0
        for v in body {
            if abs(v) < floorLevel {
                run += 1
            } else {
                if run >= leastGap { gaps += 1; worst = max(worst, run) }
                run = 0
            }
        }
        if run >= leastGap { gaps += 1; worst = max(worst, run) }
        if gaps > 0 {
            var at = 0
            var where_: [String] = []
            var length = 0
            for (i, v) in body.enumerated() {
                if abs(v) < floorLevel {
                    if length == 0 { at = i }
                    length += 1
                } else {
                    if length >= leastGap {
                        where_.append(String(format: "%.2f s for %.1f ms",
                                             Double(at) / rate,
                                             Double(length) * 1000.0 / rate))
                    }
                    length = 0
                }
            }
            print("        gaps at: " + where_.joined(separator: ", "))
        }
        check("no gaps in what arrived", gaps == 0,
              gaps == 0 ? "" : String(format: "%d gaps, worst %.1f ms", gaps,
                                      Double(worst) * 1000.0 / rate))

        // The pitch. Missing audio takes whole cycles with it, so a tone with
        // holes in it reads LOW. This is the measurement that turns "a change
        // in pitch, a little choppiness" into a number.
        var crossings = 0
        var previous = body[0]
        for v in body.dropFirst() {
            if previous < 0 && v >= 0 { crossings += 1 }
            previous = v
        }
        let measured = Double(crossings) * rate / Double(body.count)
        check("it comes back at the frequency it went out",
              abs(measured - 1000.0) < 5.0,
              String(format: "%.1f Hz against 1000.0", measured))

        check("the send says it was clean, and it was", clean, why)
        check("the ring never had to throw a block away", dropped == 0, "\(dropped)")
        check("and it never had to rebuffer", rebuffers == 0, "\(rebuffers)")

        print("")
        print(String(format: "  %.1f seconds recorded off the cable at %d Hz",
                     Double(got.count) / rate, Int(rate)))
        print(failures == 0 ? "  The send arrives clean." : "  \(failures) checks failed.")
        return failures == 0 ? 0 : 1
    }
}
