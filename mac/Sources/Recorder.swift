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
                  let handle = FileHandle(forWritingAtPath: destination) else {
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
        taps.add(bus)
        path = destination
        framesWritten = 0
        droppedAtStart = bus.dropped
        cue = CueFile(audioPath: destination)
        stopping = false
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

        while true {
            lock.lock(); let finishing = stopping; lock.unlock()
            let ready = bus.available()
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
        lock.unlock()
    }

    /// Whatever LAME is still holding, and then the Info tag over the
    /// placeholder it left at the very start of the file.
    private func finishMP3() {
        guard let encoder = mp3, let handle = mp3File else { return }
        if let tail = encoder.flush() { handle.write(tail) }
        if let tag = encoder.infoTagFrame() {
            // Over the placeholder, not inserted: it is the same size, and
            // seeking back is the whole reason a file can have this and a
            // stream cannot.
            try? handle.seek(toOffset: 0)
            handle.write(tag)
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
            if let bytes = encoder.encode(buffer) { handle.write(bytes) }
            if let problem = encoder.lastError {
                lastError = "The recording stopped. \(problem)"
                lock.lock(); stopping = true; lock.unlock()
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
            lock.lock(); stopping = true; lock.unlock()
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
        let name = (finished as NSString).lastPathComponent
        var said = [String(format: "Recording saved as %@, %@, %.1f megabytes",
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
