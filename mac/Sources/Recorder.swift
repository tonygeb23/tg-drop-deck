// Recording the show.
//
// What is captured is the PROGRAMME: every sound card, the running order at
// full level, the microphone if it is on air, and any extra sources on air.
// Never the cue and never a preview, because those are the presenter's and not
// the listener's.
//
// It does not need you to be on air, and it does not fight with the stream:
// the two get separate AirBus instances, because reading a bus takes the audio
// out of it and two readers on one ring would each get half a show.

import Foundation
import AVFoundation

final class Recorder {

    private(set) var isRecording = false
    private(set) var path: String?
    private(set) var lastError: String?

    /// Counted from frames written rather than from a wall clock, so a machine
    /// that stalled for a moment reports the length of the file rather than the
    /// length of the wait.
    private(set) var framesWritten: Int = 0

    /// The track list written beside the file, as the show goes out. Nil until
    /// a recording starts. Every timestamp in it comes from `elapsed`, which is
    /// frames written over the sample rate and never a wall clock: a machine
    /// that stalls makes the file shorter than the clock says, and a list timed
    /// against the wall drifts away from the audio it describes.
    private(set) var cue: CueFile?

    /// What `bus.dropped` was when this started. **Nothing anywhere read the
    /// recorder's drop counter until 3.7.1**, so a recording that lost sound
    /// said nothing at all, in either sense.
    private var droppedAtStart = 0
    /// Audio the bus threw away because this could not keep up.
    var losingAudio: Int { max(0, (bus?.dropped ?? 0) - droppedAtStart) }

    private var bus: AirBus?
    /// The taps this recording's bus was added to, so a recording that fails
    /// on its own can take the bus back out (N3).
    private weak var taps: Taps?
    /// Set by the writer when the FILE refused, rather than somebody pressing
    /// stop. Read once, where the writer ends.
    private var failed = false
    /// Told, on the main queue, when the recording stops by itself because
    /// the file could not be written: the sentence to say. **Nothing said so
    /// until 3.8.4** (N3): the recording simply stopped, the menu still said
    /// Stop recording, and the bus stayed in the taps for the rest of the
    /// session, because `stop()` returned at its first guard.
    var onFailed: ((String) -> Void)?
    private var file: AVAudioFile?
    // MP3 does not go through AVAudioFile, which cannot write one. It is LAME
    // and a file handle, and the two paths meet again in `write`.
    private var mp3: MP3Encoder?
    private var mp3File: FileHandle?
    private var thread: Thread?
    private var stopping = false
    private let lock = NSLock()
    private var rate: Double = C.defaultSampleRate

    var elapsed: Double { rate > 0 ? Double(framesWritten) / rate : 0 }

    /// Option Shift R. See `PauseGate`. The elapsed time is what is in the
    /// file, so it stands still while paused.
    let gate = PauseGate()
    var isPaused: Bool { isRecording && gate.isPaused }
    @discardableResult
    func pause() -> Bool { isRecording && gate.pause(waiting: bus?.available() ?? 0) }
    @discardableResult
    func resume() -> Bool { gate.resume(waiting: bus?.available() ?? 0) }

    static let stem = "Drop Deck Stream "

    /// Documents, asked of the system rather than assumed. A machine where
    /// Documents has been redirected does not have one at the path guessing
    /// would produce.
    static func defaultFolder() -> String {
        let base = FileManager.default.urls(for: .documentDirectory,
                                            in: .userDomainMask).first!
        return base.appendingPathComponent(C.appName).path
    }

    /// What a recording of this kind is called on disk.
    ///
    /// **A format nobody here recognises used to become `.wav`, quietly.** That
    /// is the same fault Windows found the first time it recorded a picture: an
    /// unknown format fell through to the audio default, so the first MP4 this
    /// app ever wrote would have gone into a file called `.wav`, and it would
    /// have played nowhere and looked like a broken encoder. Every format the
    /// app can write is named here, including the video one, and anything else
    /// keeps its own name rather than borrowing a lie.
    static func fileExtension(for format: String) -> String {
        switch format {
        case "wav": return ".wav"
        case "aac": return ".m4a"
        case "flac": return ".flac"
        case "mp3": return ".mp3"
        case "mp4": return ".mp4"
        default: return "." + format.filter { $0.isLetter || $0.isNumber }
        }
    }

    /// The next free name. The folder is scanned for the highest number rather
    /// than a counter being kept, so deleting last week's recordings does not
    /// start it over the top of anything.
    static func nextPath(folder: String, format: String) -> String {
        let ext = fileExtension(for: format)
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder)) ?? []
        var highest = 0
        for name in names where name.hasPrefix(stem) {
            let rest = name.dropFirst(stem.count)
            let digits = rest.prefix(while: { $0.isNumber })
            if let n = Int(digits) { highest = max(highest, n) }
        }
        return (folder as NSString)
            .appendingPathComponent(String(format: "%@%03d%@", stem, highest + 1, ext))
    }

    private static func settings(format: String, rate: Double, bitrate: Int) -> [String: Any] {
        switch format {
        case "aac":
            return [
                AVFormatIDKey: kAudioFormatMPEG4AAC,
                AVSampleRateKey: rate,
                AVNumberOfChannelsKey: 2,
                AVEncoderBitRateKey: bitrate * 1000,
            ]
        case "flac":
            return [
                AVFormatIDKey: kAudioFormatFLAC,
                AVSampleRateKey: rate,
                AVNumberOfChannelsKey: 2,
            ]
        default:
            // Sixteen bit, which is what a broadcast recording is listened to
            // as and half the size of the float the mixer works in.
            return [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: rate,
                AVNumberOfChannelsKey: 2,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
                AVLinearPCMIsNonInterleaved: false,
            ]
        }
    }

    /// How an MP3 file is opened for writing. The app's is the obvious one;
    /// a check hands in a handle that refuses every write, to drive the real
    /// writer down its real failure path.
    var openForWriting: (String) -> FileHandle? = { FileHandle(forWritingAtPath: $0) }

    /// Said when an MP3 file stops taking what is written to it.
    static let cannotWrite = "The file could not be written. The disk may be full, or it "
        + "may have been disconnected"

    @discardableResult
    func start(taps: Taps, rate: Double, format: String, bitrate: Int,
               folder: String?) -> String? {
        guard !isRecording else { return path }
        lastError = nil
        self.rate = rate

        let target = folder ?? Recorder.defaultFolder()
        do {
            try FileManager.default.createDirectory(atPath: target,
                                                    withIntermediateDirectories: true)
        } catch {
            lastError = "Could not make the recordings folder. \(error.localizedDescription)"
            return nil
        }
        let destination = Recorder.nextPath(folder: target, format: format)

        if format == "mp3" {
            guard let encoder = MP3Encoder(rate: rate, bitrate: bitrate, forFile: true) else {
                lastError = "The MP3 encoder would not start."
                return nil
            }
            guard FileManager.default.createFile(atPath: destination, contents: nil),
                  let handle = openForWriting(destination) else {
                lastError = "The recording file could not be made."
                return nil
            }
            mp3 = encoder
            mp3File = handle
        } else {
            do {
                file = try AVAudioFile(
                    forWriting: URL(fileURLWithPath: destination),
                    settings: Recorder.settings(format: format, rate: rate, bitrate: bitrate),
                    commonFormat: .pcmFormatFloat32, interleaved: false)
            } catch {
                lastError = "The recording would not start. \(error.localizedDescription)"
                file = nil
                return nil
            }
        }

        let bus = AirBus(sampleRate: rate)
        self.bus = bus
        self.taps = taps
        failed = false
        taps.add(bus)
        path = destination
        framesWritten = 0
        droppedAtStart = bus.dropped
        cue = CueFile(audioPath: destination)
        stopping = false
        gate.reset()
        isRecording = true

        let t = Thread { [weak self] in self?.run() }
        t.name = "dropdeck-record"
        thread = t
        t.start()
        return destination
    }

    private func run() {
        guard let bus, file != nil || mp3File != nil else { return }
        let chunk = max(256, Int(bus.sampleRate * C.streamChunkSeconds))
        guard let format = AVAudioFormat(standardFormatWithSampleRate: bus.sampleRate,
                                         channels: 2),
              let buffer = AVAudioPCMBuffer(pcmFormat: format,
                                            frameCapacity: AVAudioFrameCount(chunk))
        else { return }
        var interleaved = [Float](repeating: 0, count: chunk * 2)

        loop: while true {
            lock.lock(); let finishing = stopping, broken = failed; lock.unlock()
            // A file that refused takes nothing more: what is left on the bus
            // has nowhere to go.
            if broken { break }
            let ready = bus.available()
            switch gate.step(ready: ready, chunk: chunk) {
            case .normal:
                break
            case .write(let n):
                if n > 0 { write(n, bus, buffer, &interleaved) }
                else if finishing { break loop }
                else { Thread.sleep(forTimeInterval: C.streamPollSeconds) }
                continue loop
            case .discard(let n):
                // Stopped while paused: what is waiting came after the pause.
                if finishing { break loop }
                if n > 0 {
                    if interleaved.count < n * 2 { interleaved = [Float](repeating: 0, count: n * 2) }
                    interleaved.withUnsafeMutableBufferPointer { raw in
                        bus.read(frames: n, into: raw.baseAddress!)
                    }
                } else {
                    Thread.sleep(forTimeInterval: C.streamPollSeconds)
                }
                continue loop
            }
            if ready < chunk {
                // Stopping a recording should not cost the last quarter second
                // of it, so the remaining ring is drained before the file is
                // closed.
                if finishing {
                    if ready > 0 { write(ready, bus, buffer, &interleaved) }
                    break
                }
                Thread.sleep(forTimeInterval: C.streamPollSeconds)
                continue
            }
            write(chunk, bus, buffer, &interleaved)
        }

        finishMP3()

        lock.lock()
        self.file = nil
        isRecording = false
        let broke = failed
        lock.unlock()
        if broke { writerFailed() }
    }

    /// The writer stopped because the file refused. Let go of the bus and
    /// say so, on the main queue, once.
    func writerFailed() {
        let finish = { [weak self] in
            // Stop pressed at the same moment has already finished the file
            // and said so; this has nothing left to add.
            guard let self, self.path != nil || self.bus != nil else { return }
            if let bus = self.bus { self.taps?.remove(bus) }
            self.bus = nil
            self.thread = nil
            let name = (self.path as NSString?)?.lastPathComponent ?? "the recording"
            self.path = nil
            self.cue = nil
            var why = self.lastError ?? ""
            if why.hasPrefix("The recording stopped. ") {
                why = String(why.dropFirst("The recording stopped. ".count))
            }
            self.onFailed?(Recorder.failedLine(name: name, why: why))
        }
        if Thread.isMainThread { finish() } else { DispatchQueue.main.async(execute: finish) }
    }

    /// What is said when a sound recording stops by itself. What is already
    /// in the file stays there, which is worth knowing mid show.
    static func failedLine(name: String, why: String) -> String {
        let reason = why.trimmingCharacters(in: .whitespaces)
        let said = reason.isEmpty ? "" : (reason.hasSuffix(".") ? reason : reason + ".") + " "
        return "The recording to \(name) has stopped by itself. \(said)What was "
            + "recorded before that is still in the file."
    }

    /// For the self test: behave exactly as the writer does when the file
    /// refuses, with no file to break.
    func failForTesting(_ why: String) {
        lock.lock()
        lastError = why
        failed = true
        isRecording = false
        lock.unlock()
        writerFailed()
    }

    /// For the self test: a recording in progress, as far as the bus and the
    /// taps can tell, with nothing written anywhere.
    func pretendRecording(taps: Taps, rate: Double, path: String) {
        let bus = AirBus(sampleRate: rate)
        self.bus = bus
        self.taps = taps
        self.path = path
        taps.add(bus)
        isRecording = true
    }

    /// Whether this recording's bus is still in the taps. For the self test.
    var holdsBus: Bool { bus != nil }

    /// Whatever LAME is still holding, and then the Info tag over the
    /// placeholder it left at the very start of the file.
    private func finishMP3() {
        guard let encoder = mp3, let handle = mp3File else { return }
        // The THROWING writes, here as in `write` (audit 2, finding 4). The
        // old `write(_:)` raises an Objective-C exception on a full disk or a
        // volume that has gone, which nothing in Swift can catch, and it was
        // raised on the recording's own thread: the app died mid show. At the
        // end of a file there is nothing left to save, so a refusal here is
        // simply the end.
        if let tail = encoder.flush() { try? handle.write(contentsOf: tail) }
        if let tag = encoder.infoTagFrame() {
            // Over the placeholder, not inserted: it is the same size, and
            // seeking back is the whole reason a file can have this and a
            // stream cannot.
            try? handle.seek(toOffset: 0)
            try? handle.write(contentsOf: tag)
        }
        try? handle.close()
        mp3File = nil
        mp3 = nil
    }

    private func write(_ frames: Int, _ bus: AirBus,
                       _ buffer: AVAudioPCMBuffer, _ interleaved: inout [Float]) {
        if interleaved.count < frames * 2 {
            interleaved = [Float](repeating: 0, count: frames * 2)
        }
        interleaved.withUnsafeMutableBufferPointer { raw in
            bus.read(frames: frames, into: raw.baseAddress!)
            buffer.frameLength = AVAudioFrameCount(frames)
            guard let channels = buffer.floatChannelData else { return }
            for i in 0..<frames {
                channels[0][i] = raw[i * 2]
                channels[1][i] = raw[i * 2 + 1]
            }
        }
        if let encoder = mp3, let handle = mp3File {
            if let bytes = encoder.encode(buffer) {
                do {
                    try handle.write(contentsOf: bytes)
                } catch {
                    // A full disk or a volume that has gone: stop cleanly and
                    // say so, rather than an exception ending the app.
                    lastError = "The recording stopped. \(Recorder.cannotWrite)"
                    lock.lock(); stopping = true; failed = true; lock.unlock()
                    return
                }
            }
            if let problem = encoder.lastError {
                lastError = "The recording stopped. \(problem)"
                lock.lock(); stopping = true; failed = true; lock.unlock()
                return
            }
            framesWritten += frames
            return
        }
        guard let file else { return }
        do {
            try file.write(from: buffer)
            framesWritten += frames
        } catch {
            lastError = "The recording stopped. \(error.localizedDescription)"
            lock.lock(); stopping = true; failed = true; lock.unlock()
        }
    }

    /// Finish the file and hand back a line about it.
    ///
    /// Closing the app finishes the file first, so a recording always opens.
    @discardableResult
    func stop(taps: Taps) -> String? {
        guard isRecording, let finished = path else { return nil }
        lock.lock(); stopping = true; lock.unlock()

        // Wait for the writer to drain and close, but never for ever.
        let deadline = Date().addingTimeInterval(3.0)
        while Date() < deadline {
            lock.lock(); let done = !isRecording; lock.unlock()
            if done { break }
            Thread.sleep(forTimeInterval: 0.02)
        }
        // Read BEFORE the bus is let go, or the count goes with it.
        let lost = losingAudio
        if let bus { taps.remove(bus) }
        bus = nil
        // If the writer did not finish inside the deadline the MP3 is still
        // open and still missing its tail, so it is closed here rather than
        // left as a file that ends mid frame.
        finishMP3()
        file = nil
        isRecording = false
        thread = nil

        let seconds = elapsed
        let attributes = try? FileManager.default.attributesOfItem(atPath: finished)
        let size = (attributes?[.size] as? NSNumber)?.intValue ?? 0
        let megabytes = Double(size) / (1024 * 1024)
        // The name without its extension, which is read aloud as "dot wav".
        // Said after "Recording stopped", which the window puts first: Siena
        // never heard the recording say it had stopped (Windows 3.9.0).
        let name = ((finished as NSString).lastPathComponent as NSString).deletingPathExtension
        var said = [String(format: "Saved as %@, %@, %.1f megabytes",
                           name, formatDuration(seconds), megabytes)]
        if lost > 0 {
            said.append("It lost audio \(lost) times, so there are gaps in it")
        }
        if let line = cue?.describe(), !line.isEmpty { said.append(line) }
        cue = nil
        path = nil
        return said.joined(separator: ". ") + "."

    }
}


// ------------------------------------------------------------- pausing ---

/// Holding a recording and carrying on into the same file.
///
/// Siena, October 2026: "it would be helpful to have the option to pause and
/// resume a recording without having to stop it and make a new recording."
/// Both recorders keep reading the air bus while paused and throw what they
/// read away, so the ring never fills and nothing is lost to an overflow when
/// the recording carries on. The cut falls at the sample waiting at the press:
/// what was already in the ring when Pause was pressed happened BEFORE the
/// press and is written; what is in it when Resume is pressed happened during
/// the pause and is not. Windows 3.9.0 measured the first version leaking a
/// quarter second across the press, which is what the two counts are for.
///
/// Kept apart from the writers so the arithmetic can be checked without a
/// file, a bus or a thread.
final class PauseGate {
    private let lock = NSLock()
    private var paused = false
    /// Frames that were waiting at the press of Pause: still to be written.
    private var drain = 0
    /// Frames that were waiting at the press of Resume: still to be dropped.
    private var discard = 0

    enum Step: Equatable {
        /// Not paused and nothing left over: the writer carries on as usual.
        case normal
        /// Write this many (nought means wait for more).
        case write(Int)
        /// Read and throw away this many (nought means wait for more).
        case discard(Int)
    }

    var isPaused: Bool { lock.lock(); defer { lock.unlock() }; return paused }

    /// `waiting` is what the bus holds at the press. False when already paused.
    @discardableResult
    func pause(waiting: Int) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !paused else { return false }
        paused = true
        drain = max(0, waiting)
        return true
    }

    /// `waiting` is what the bus holds at the press. False when not paused.
    @discardableResult
    func resume(waiting: Int) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard paused else { return false }
        paused = false
        // Anything from before the pause not yet written is written first; the
        // rest of what is waiting arrived during the pause.
        discard = max(0, waiting - drain)
        return true
    }

    /// What the writer should do with `ready` frames, at most `chunk`.
    func step(ready: Int, chunk: Int) -> Step {
        lock.lock(); defer { lock.unlock() }
        if drain > 0 {
            let n = min(drain, ready, chunk)
            drain -= n
            return .write(n)
        }
        if discard > 0 {
            let n = min(discard, ready, chunk)
            discard -= n
            return .discard(n)
        }
        if paused { return .discard(min(ready, chunk)) }
        return .normal
    }

    func reset() {
        lock.lock(); paused = false; drain = 0; discard = 0; lock.unlock()
    }
}
