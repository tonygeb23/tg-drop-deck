// Recording the picture as well as the sound, in sync, to one file.
//
// A mirror of dropdeck/videorecord.py. Tony, 10 September 2026: "in addition to
// taking audio, it also takes video as well. ensure it is perfectly in sync
// with audio." Darrell, a listener, the same day: "when setting up a video
// source, such as a camera or capture card, should you not be able to record in
// video if you are doing a recording test?"
//
// Command+R still records sound alone and is untouched. Command+Shift+R records
// both, and neither needs you to be on air.
//
// ## The clock, which is the whole feature
//
// **The audio sample clock is master and video absorbs every bit of drift.**
// Master is this recorder's own count of samples written to the file,
// `framesWritten / sampleRate`, which came off the sound card through the
// `AirBus`. Video is emitted until its frame count reaches
// `Int(audioSeconds * fps)`, so a camera running slow has a frame repeated and
// one running fast has a frame skipped, and neither can move the timeline.
// **No part of this file may ever timestamp anything from a wall clock**, and
// the self test asserts that by reading this source.
//
// That is the same mechanism `VideoStreamer.pumpVideo` already uses. Tiffany
// measured the Windows version holding sync to 0.00 ms per minute over a real
// 45 second recording, with a per frame stamp read back out of the decoded
// picture. She also measured what happens if any part of it takes its time from
// the wall clock instead, on a card running 0.3 per cent off: **minus 150 ms
// per minute**. That is the worst mistake available here and it is one line
// away at all times.
//
// ## Three things that are right for a socket and wrong for a file
//
// The RTMP path is correct where it lives. Copying it wholesale is not.
//
// 1. **The time base.** FLV carries millisecond timestamps, so the stream
//    stamps `frames * 1000 / fps` at 1/1000. On Windows that gave real frame
//    intervals of 33.312, 33.313 and 33.375 ms in an MP4: a variable frame rate
//    file, which is a nuisance in an editor. Here every frame is stamped
//    `CMTime(value: framesSent, timescale: fps)`, which is exact by
//    construction and cannot round at all.
// 2. **A missing picture.** Returning without sending is correct for a socket,
//    where a missed frame is simply not sent. In a file it stalls the video
//    timeline while audio keeps going. Measured on Windows over an eight second
//    camera outage: **the picture ran 6.48 seconds ahead of the sound**, was
//    still 0.48 seconds out sixteen seconds later, and nothing was dropped, no
//    gap appeared, no count was wrong and nothing was logged anywhere. Here a
//    missing picture repeats the last frame, which is also cheaper.
// 3. **The rate control.** `VideoEncoder` uses `ConstantBitRate` because a
//    platform publishes a bitrate FLOOR and pads up to it with filler. A file
//    has no floor and no reason to carry filler, so this asks for an AVERAGE
//    bitrate instead. Windows reaches the same place with CRF, which
//    VideoToolbox has no equivalent of.
//
// ## Why the file is fragmented
//
// A plain MP4 keeps its index in a moov atom written at the end, so a crash
// leaves a file that will not open at all. `movieFragmentInterval` makes
// AVAssetWriter write the index as it goes, so a three hour show that stops
// unexpectedly loses its last second rather than all of it. Windows measured
// the same trade at minus 0.04 per cent in bytes, the fragment headers being
// smaller than the index they replace.

import Foundation
import AVFoundation
import CoreMedia
import CoreVideo

/// One picture, put down by whoever has it and picked up by the recorder.
///
/// One lock and one slot. Deliberately not a queue: the recorder wants the
/// NEWEST frame and nothing else, and a queue would let a slow encoder build a
/// backlog of stale pictures and then play them late.
final class FrameTap {
    private var frame: CVPixelBuffer?
    private let lock = NSLock()
    private(set) var puts = 0

    func put(_ buffer: CVPixelBuffer?) {
        guard let buffer else { return }
        lock.lock()
        frame = buffer
        puts += 1
        lock.unlock()
    }

    func latest() -> CVPixelBuffer? {
        lock.lock(); defer { lock.unlock() }
        return frame
    }

    func clear() {
        lock.lock(); frame = nil; lock.unlock()
    }
}

final class VideoRecorder {

    private(set) var isRecording = false
    private(set) var path: String?
    private(set) var lastError: String?

    /// AUDIO frames. The master clock.
    private(set) var framesWritten = 0
    /// Video frames handed to the writer.
    private(set) var framesSent = 0
    /// Frames where the picture had not changed, or had not arrived at all.
    private(set) var repeated = 0
    /// Frames skipped to catch up with the sound.
    private(set) var droppedPictures = 0
    private(set) var bytesWritten: Int64 = 0
    /// What `bus.dropped` was when this started, so `losingAudio` is about
    /// THIS recording and not about a stream that was struggling an hour ago.
    private var droppedAudioAtStart = 0

    /// The track list written beside the file. Nil until a track goes out.
    private(set) var cue: CueFile?

    var onState: ((String) -> Void)?

    private var width = C.rtmpWidth
    private var height = C.rtmpHeight
    private var fps = C.rtmpFPS

    private var bus: AirBus?
    private var writer: AVAssetWriter?
    private var videoInput: AVAssetWriterInput?
    private var audioInput: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var audioFormat: CMAudioFormatDescription?

    private var thread: Thread?
    private var stopping = false
    private let lock = NSLock()

    /// Where a frame comes from while this is running.
    ///
    /// When a video stream is already live this borrows the identical frame the
    /// stream is sending, which costs almost nothing and, more importantly,
    /// does not open the camera a second time: a camera is exclusive and the
    /// second opener gets nothing.
    private var borrow: (() -> CVPixelBuffer?)?
    /// And when nothing is live, this recorder owns the picture itself.
    private var ownSource: PictureSource?
    private var ownOverlay: Overlay?
    private var lastFrame: CVPixelBuffer?

    // ---------------------------------------------------------------- state ---

    /// The master clock. Samples written, not seconds elapsed.
    var audioSeconds: Double {
        guard framesWritten > 0, let rate = bus?.sampleRate, rate > 0 else { return 0 }
        return Double(framesWritten) / rate
    }

    var elapsed: Double { audioSeconds }

    /// Has the bus had to throw sound away since this started.
    var losingAudio: Int { max(0, (bus?.dropped ?? 0) - droppedAudioAtStart) }

    func describe() -> String {
        guard isRecording else { return "Not recording" }
        var said = "Recording picture and sound, "
            + "\((path as NSString?)?.lastPathComponent ?? ""), "
            + "\(clock(elapsed)), \(Int(Double(bytesWritten) / 1_048_576.0)) MB"
        if losingAudio > 0 { said += ". It is losing audio" }
        return said
    }

    private func clock(_ seconds: Double) -> String {
        let whole = Int(seconds)
        let h = whole / 3600, m = (whole % 3600) / 60, s = whole % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s)
                     : String(format: "%d:%02d", m, s)
    }

    // ----------------------------------------------------------------- work ---

    /// Open the file and begin. The path, or nil with `lastError` set.
    ///
    /// `borrow` is where a frame comes from when a stream is already live.
    /// `own` is the pair to build and drive when nothing is.
    @discardableResult
    func start(taps: Taps, rate: Double, width: Int, height: Int, fps: Int,
               folder: String?,
               borrow: (() -> CVPixelBuffer?)?,
               own: (() -> (PictureSource, Overlay))?) -> String? {
        guard !isRecording else { return path }
        self.width = max(2, width)
        self.height = max(2, height)
        self.fps = max(1, fps)
        self.borrow = borrow

        let dir = folder ?? Recorder.defaultFolder()
        do {
            try FileManager.default.createDirectory(atPath: dir,
                                                    withIntermediateDirectories: true)
        } catch {
            lastError = "Could not make \(dir). \(error.localizedDescription)"
            return nil
        }
        let file = Recorder.nextPath(folder: dir, format: C.defaultRecordVideoFormat)

        do {
            try open(file: file, rate: rate)
        } catch {
            close()
            lastError = "Could not start recording. \(error.localizedDescription)"
            return nil
        }

        // Only opened when nothing is live, and closed again on stop: a camera
        // left open is a light on in the room and a device no other program can
        // have.
        if borrow == nil, let own {
            let (source, overlay) = own()
            source.start()
            _ = source.waitReady(timeout: C.cameraOpenTimeout)
            ownSource = source
            ownOverlay = overlay
        }

        let bus = AirBus(sampleRate: rate)
        self.bus = bus
        taps.add(bus)
        droppedAudioAtStart = bus.dropped

        path = file
        framesWritten = 0
        framesSent = 0
        repeated = 0
        droppedPictures = 0
        bytesWritten = 0
        lastFrame = nil
        saidLosing = 0
        stopping = false
        isRecording = true
        cue = CueFile(audioPath: file)

        let worker = Thread { [weak self] in self?.run(rate: rate) }
        worker.name = "dropdeck-record-video"
        worker.qualityOfService = .userInitiated
        thread = worker
        worker.start()
        return file
    }

    private func open(file: String, rate: Double) throws {
        let url = URL(fileURLWithPath: file)
        try? FileManager.default.removeItem(at: url)
        let w = try AVAssetWriter(outputURL: url, fileType: .mp4)
        // Written as it goes, so a crash costs one fragment rather than the
        // whole file. See this file's header.
        w.movieFragmentInterval = CMTime(seconds: C.recordFragmentSeconds,
                                         preferredTimescale: 1000)
        w.shouldOptimizeForNetworkUse = false

        let video = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [
                // AVERAGE, and never constant. See the header: a file has no
                // platform floor to pad up to, and padding is what the stream's
                // filler bytes are for.
                AVVideoAverageBitRateKey: C.recordVideoBitrate * 1000,
                AVVideoMaxKeyFrameIntervalKey: fps * 2,
                AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
                AVVideoAllowFrameReorderingKey: false,
            ],
            // The same three tags the stream sets. A player that has to guess
            // the colour range guesses wrong, and that is what "washed out" and
            // "crushed" look like to somebody who can see the file.
            AVVideoColorPropertiesKey: [
                AVVideoColorPrimariesKey: AVVideoColorPrimaries_ITU_R_709_2,
                AVVideoTransferFunctionKey: AVVideoTransferFunction_ITU_R_709_2,
                AVVideoYCbCrMatrixKey: AVVideoYCbCrMatrix_ITU_R_709_2,
            ],
        ])
        video.expectsMediaDataInRealTime = true

        let audio = AVAssetWriterInput(mediaType: .audio, outputSettings: [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: rate,
            AVNumberOfChannelsKey: 2,
            AVEncoderBitRateKey: C.defaultStreamBitrate * 1000,
        ])
        audio.expectsMediaDataInRealTime = true

        guard w.canAdd(video), w.canAdd(audio) else {
            throw NSError(domain: "TGDropDeck", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "this Mac would not start an H.264 writer",
            ])
        }
        w.add(video)
        w.add(audio)

        adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: video,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
            ])

        var asbd = AudioStreamBasicDescription(
            mSampleRate: rate,
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked,
            mBytesPerPacket: 8, mFramesPerPacket: 1, mBytesPerFrame: 8,
            mChannelsPerFrame: 2, mBitsPerChannel: 32, mReserved: 0)
        var format: CMAudioFormatDescription?
        let status = CMAudioFormatDescriptionCreate(
            allocator: kCFAllocatorDefault, asbd: &asbd, layoutSize: 0, layout: nil,
            magicCookieSize: 0, magicCookie: nil, extensions: nil,
            formatDescriptionOut: &format)
        guard status == noErr, let format else {
            throw NSError(domain: "TGDropDeck", code: 2, userInfo: [
                NSLocalizedDescriptionKey: "the audio format would not describe itself",
            ])
        }
        audioFormat = format

        guard w.startWriting() else {
            throw w.error ?? NSError(domain: "TGDropDeck", code: 3, userInfo: [
                NSLocalizedDescriptionKey: "the writer would not start",
            ])
        }
        w.startSession(atSourceTime: .zero)
        writer = w
        videoInput = video
        audioInput = audio
    }

    // -------------------------------------------------------------- running ---

    private var saidLosing = 0

    /// Notice the file falling behind the show, and say so once.
    private func checkBacklog() {
        let lost = losingAudio
        guard lost > 0, lost != saidLosing else { return }
        saidLosing = lost
        onState?("The recording is losing audio. The machine cannot keep up "
            + "with the picture.")
    }

    private func run(rate: Double) {
        // **A FRAME's worth of audio, not a quarter of a second.** This one
        // line is the difference between a file that is in sync and one that is
        // 257 ms out in a way nothing here could detect. See
        // C.recordDrainFramesPerPicture.
        let chunk = max(256, Int(rate * Double(C.recordDrainFramesPerPicture)
                                 / Double(fps)))
        let scratch = UnsafeMutablePointer<Float>.allocate(capacity: chunk * 2)
        defer { scratch.deallocate() }

        while true {
            lock.lock(); let finishing = stopping; lock.unlock()
            guard let bus else { break }
            let ready = bus.available()
            if ready < chunk {
                if finishing {
                    if ready > 0 {
                        let last = UnsafeMutablePointer<Float>.allocate(capacity: ready * 2)
                        bus.read(frames: ready, into: last)
                        feedAudio(last, frames: ready, rate: rate)
                        last.deallocate()
                    }
                    pumpVideo()
                    break
                }
                Thread.sleep(forTimeInterval: C.streamPollSeconds)
                continue
            }
            bus.read(frames: chunk, into: scratch)
            // Audio FIRST, then the picture against the count of samples
            // written. So if the video encoder ever runs long the frame counter
            // falls behind and the next pass repeats or drops to catch up.
            // **The audio can never stall behind the picture.**
            feedAudio(scratch, frames: chunk, rate: rate)
            pumpVideo()
            checkBacklog()
        }
        finish()
    }

    private func feedAudio(_ samples: UnsafeMutablePointer<Float>, frames: Int,
                           rate: Double) {
        guard frames > 0, let input = audioInput, let format = audioFormat else { return }
        let startFrame = framesWritten
        framesWritten += frames

        // AAC decodes ABOVE what was encoded: Windows measured +0.26 dBFS at
        // 192 kbps on material the soft clip had already ceilinged at 0. One
        // decibel of room here, on this thread, and nothing anywhere near the
        // mixer, which is feeding the speakers and the stream.
        let headroom = dbToGain(C.recordAACHeadroomDB)
        if headroom != 1 {
            for i in 0..<(frames * 2) { samples[i] *= headroom }
        }

        guard input.isReadyForMoreMediaData else { return }
        let bytes = frames * 2 * MemoryLayout<Float>.size
        var block: CMBlockBuffer?
        guard CMBlockBufferCreateWithMemoryBlock(
            allocator: kCFAllocatorDefault, memoryBlock: nil, blockLength: bytes,
            blockAllocator: kCFAllocatorDefault, customBlockSource: nil,
            offsetToData: 0, dataLength: bytes, flags: 0,
            blockBufferOut: &block) == noErr, let block else { return }
        guard CMBlockBufferReplaceDataBytes(with: samples, blockBuffer: block,
                                            offsetIntoDestination: 0,
                                            dataLength: bytes) == noErr else { return }
        var sample: CMSampleBuffer?
        var timing = CMSampleTimingInfo(
            duration: CMTime(value: 1, timescale: CMTimeScale(rate)),
            presentationTimeStamp: CMTime(value: CMTimeValue(startFrame),
                                          timescale: CMTimeScale(rate)),
            decodeTimeStamp: .invalid)
        guard CMSampleBufferCreateReady(
            allocator: kCFAllocatorDefault, dataBuffer: block,
            formatDescription: format, sampleCount: frames,
            sampleTimingEntryCount: 1, sampleTimingArray: &timing,
            sampleSizeEntryCount: 0, sampleSizeArray: nil,
            sampleBufferOut: &sample) == noErr, let sample else { return }
        input.append(sample)
    }

    /// Emit frames until the picture has caught up with the sound.
    private func pumpVideo() {
        guard let input = videoInput, let adaptor else { return }
        // Stamped against the audio that has ARRIVED, not only the audio
        // already written. The picture was grabbed a moment ago and the writer
        // is always a little behind the bus, so counting only what is written
        // puts every frame slightly early, which reads as the sound being late.
        // Capped, so it can never run away.
        var waiting = 0.0
        if let bus, bus.sampleRate > 0 {
            waiting = Double(bus.available()) / bus.sampleRate
        }
        let lead = min(Int(waiting * Double(fps)), C.recordStampLeadFrames)
        let due = Int(audioSeconds * Double(fps)) + lead

        // A cap, so a long stall cannot become a burst of a thousand frames
        // that starves the audio behind it. Anything beyond the cap is a drop,
        // counted, and the timeline stays right because the counter moves.
        if due - framesSent > C.recordCatchupFrames {
            let skipped = (due - framesSent) - C.recordCatchupFrames
            droppedPictures += skipped
            framesSent += skipped
        }
        while framesSent < due {
            // A writer that is not ready is one that has fallen behind. Leaving
            // now and coming back next pass is right: `due` is recomputed from
            // the sound each time, so the frames are not lost, they are caught
            // up or counted as a skip by the cap above.
            guard input.isReadyForMoreMediaData else { return }
            emitOne(adaptor)
        }
    }

    /// A black frame, made once and kept, so a recording that starts before
    /// anything has arrived still has a timeline.
    private var black: CVPixelBuffer?
    private func blackFrame() -> CVPixelBuffer? {
        if let black { return black }
        black = Pixels.draw(width: width, height: height) { ctx in
            ctx.setFillColor(red: 0, green: 0, blue: 0, alpha: 1)
            ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        }
        return black
    }

    private func emitOne(_ adaptor: AVAssetWriterInputPixelBufferAdaptor) {
        var picture: CVPixelBuffer?
        if let borrow {
            picture = borrow()
        } else if let source = ownSource {
            if let raw = source.frame(width: width, height: height) {
                picture = ownOverlay.map {
                    Pixels.composite(raw, $0, width: width, height: height)
                } ?? raw
            }
        }
        if picture == nil || picture === lastFrame {
            picture = lastFrame ?? blackFrame()
            repeated += 1
        } else {
            lastFrame = picture
        }
        guard let shown = picture else {
            // Nothing has ever arrived and a black frame could not even be
            // made. NEVER return without advancing, or the sound runs on
            // without the picture and comes back seconds out with every count
            // still correct.
            framesSent += 1
            return
        }
        // **`CMTime(value: framesSent, timescale: fps)`**, which is exact by
        // construction. Milliseconds at 1/1000 is what gives an editor a
        // variable frame rate file.
        let at = CMTime(value: CMTimeValue(framesSent), timescale: CMTimeScale(fps))
        framesSent += 1
        adaptor.append(shown, withPresentationTime: at)
    }

    // --------------------------------------------------------------- finish ---

    private func finish() {
        guard let w = writer else { return }
        videoInput?.markAsFinished()
        audioInput?.markAsFinished()
        let done = DispatchSemaphore(value: 0)
        w.finishWriting { done.signal() }
        _ = done.wait(timeout: .now() + C.streamStopSeconds)
        if w.status == .failed {
            lastError = w.error?.localizedDescription
        }
        if let path, let size = try? FileManager.default
            .attributesOfItem(atPath: path)[.size] as? Int64 {
            bytesWritten = size
        }
        close()
    }

    private func close() {
        writer = nil
        videoInput = nil
        audioInput = nil
        adaptor = nil
        audioFormat = nil
        ownSource?.close()
        ownSource = nil
        ownOverlay = nil
        lastFrame = nil
        black = nil
        borrow = nil
    }

    /// Finish the file. Returns where it is, or nil if it never started.
    @discardableResult
    func stop(taps: Taps) -> String? {
        guard isRecording else { return nil }
        lock.lock(); stopping = true; lock.unlock()
        if let worker = thread, worker !== Thread.current {
            let deadline = Date().addingTimeInterval(C.streamStopSeconds)
            while !worker.isFinished && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.01)
            }
        }
        thread = nil
        if let bus { taps.remove(bus) }
        bus = nil
        isRecording = false
        return path
    }

    /// What happened, as a sentence, for the line said when it stops.
    func report() -> String {
        let whole = Int(elapsed)
        let h = whole / 3600, m = (whole % 3600) / 60, s = whole % 60
        let length = h > 0 ? "\(h) hours \(m) minutes" : "\(m) minutes \(s) seconds"
        var said = ["Recording saved as \((path as NSString?)?.lastPathComponent ?? ""), "
            + "\(length), \(Int(Double(bytesWritten) / 1_048_576.0)) megabytes"]
        if losingAudio > 0 {
            said.append("It lost audio \(losingAudio) times, so there are gaps in it")
        }
        if droppedPictures > 0 {
            said.append("\(droppedPictures) frames of picture were skipped to keep "
                + "the sound in step")
        }
        if let line = cue?.describe(), !line.isEmpty { said.append(line) }
        return said.joined(separator: ". ") + "."
    }
}
