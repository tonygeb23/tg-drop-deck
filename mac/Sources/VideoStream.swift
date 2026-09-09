// Going out on YouTube, Facebook, Restream, or anything else that speaks RTMP.
//
// The counterpart of `Streamer` in StreamOut.swift, which sends audio to a
// radio server. Command+B goes to one or the other, never both: two
// destinations means two encoders and twice the upload, and it is not built.
//
// ## Audio is the master clock, and this is where that lives
//
// **Video timestamps count frames encoded against the audio sample counter,
// never a wall clock and never the camera's own timing.** Carried across from
// Windows unchanged, and it is the single most important thing in the video
// work. Three things fall out of it and none of them would survive a different
// choice:
//
//   * the picture can be swapped mid stream without the timeline moving,
//     because the clock does not belong to the picture;
//   * sound and picture cannot drift, because there is only one clock;
//   * a slow frame costs a frame rather than a second, because the pump asks
//     "how many frames should exist by now" rather than "how long since last
//     time".
//
// Measured against the mock server by `mac/tools/check_rtmp.py`: sound and
// picture finished 0 ms apart over a three second publish.
//
// ## The catch-up limit is not a knob
//
// Measured on Windows on 7 September 2026: with the pump running four times a
// second, video left in bursts of eight frames with a fifth of a second of
// nothing between them, which is what "choppy" looks like from the sending end
// even though the AVERAGE gap was a perfect 33 ms. So no more than
// `C.rtmpCatchupFrames` go out in one turn of the loop.

import Foundation
import AVFoundation
import CoreVideo

final class VideoStreamer {

    private(set) var state: StreamState = .off
    private(set) var detail = ""
    private(set) var startedAt: Date?
    private(set) var reconnects = 0
    private(set) var behindSeconds: Double = 0

    /// Told when the state changes, so the window can speak it and relabel a
    /// menu. Always called on the main queue.
    var onState: ((StreamState, String) -> Void)?
    /// Told when the picture falls back, or comes back, or dies. One sentence.
    var onSay: ((String) -> Void)?

    private let lock = NSLock()
    private var bus: AirBus?
    private var thread: Thread?
    private var stopping = false
    private var client: RTMPClient?
    private var encoder: VideoEncoder?
    private var source: PictureSource?
    private var wantedSource: PictureSource?
    private var overlay = Overlay()
    private let health = HealthWatcher()
    private(set) var framer = Framer()

    private var settings = VideoStreamSettings()
    private var currentTitle = ""
    /// Samples read off the bus. The master clock.
    private var samplesSent = 0
    private var videoFrames = 0

    var isOn: Bool {
        lock.lock(); defer { lock.unlock() }
        return state != .off && state != .failed
    }

    var elapsed: Double { startedAt.map { -$0.timeIntervalSinceNow } ?? 0 }
    var bytesSent: Int { client?.bytesSent ?? 0 }

    // ------------------------------------------------------------ going on ---

    @discardableResult
    func start(group: MixerGroup, settings: VideoStreamSettings) -> Bool {
        guard !isOn else { return true }
        guard !settings.host.isEmpty else {
            set(.failed, "there is no video platform set up yet")
            return false
        }
        guard !settings.key.isEmpty else {
            set(.failed, "there is no stream key for this station")
            return false
        }
        self.settings = settings
        let rate = group.sampleRate
        let bus = AirBus(sampleRate: rate)
        self.bus = bus
        group.addAirBus(bus)

        overlay.apply(settings.overlay)
        framer = Framer(level: settings.framingLevel,
                        onSay: { [weak self] text in self?.say(text) })
        health.reset()
        health.onSay = { [weak self] text in self?.say(text) }

        stopping = false
        samplesSent = 0
        videoFrames = 0
        startedAt = Date()
        set(.connecting, "")

        let worker = Thread { [weak self] in self?.run(rate: rate) }
        worker.name = "dropdeck-rtmp"
        worker.qualityOfService = .userInitiated
        thread = worker
        worker.start()
        return true
    }

    func stop(group: MixerGroup) {
        lock.lock(); stopping = true; lock.unlock()
        thread?.cancel()
        thread = nil
        if let bus { group.removeAirBus(bus) }
        bus = nil
        source?.close()
        source = nil
        encoder?.close()
        encoder = nil
        client?.close()
        client = nil
        startedAt = nil
        set(.off, "")
    }

    /// Change what is going out, without dropping the stream.
    ///
    /// The new source is built and STARTED here and picked up by the pump on
    /// its next turn, so nothing that blocks happens on the thread carrying
    /// the audio.
    /// Returns what went wrong, or "" when it did not. The caller says so:
    /// a switcher that reports success whatever happened is a switcher that
    /// leaves somebody broadcasting a card and believing otherwise.
    @discardableResult
    func setPicture(_ picture: PictureSettings) -> String {
        let made = Picture.build(picture, onFallback: { [weak self] text in
            self?.say(text)
        })
        made.start()
        let ready = made.waitReady(timeout: C.cameraOpenTimeout)
        made.setTitle(currentTitle)
        lock.lock(); wantedSource = made; lock.unlock()
        if ready { return "" }
        // A card cannot fail and never reports one, so an error here is the
        // real source saying it could not open.
        let trouble = made.error
        return trouble.isEmpty
            ? "\((C.pictureLabels[picture.picture] ?? picture.picture).lowercased()) "
              + "did not start" : trouble
    }

    func setOverlay(_ settings: OverlaySettings) {
        overlay.apply(settings)
    }

    func setTitle(_ title: String) {
        currentTitle = title
        overlay.setTitle(title)
        lock.lock()
        source?.setTitle(title)
        wantedSource?.setTitle(title)
        lock.unlock()
    }

    /// The frame going out right now, for the shot check.
    ///
    /// The picture that is really on the air, so "how does my shot look" is
    /// answered about what viewers can see rather than about a fresh grab
    /// taken while the presenter was moving.
    func currentFrame() -> CVPixelBuffer? {
        lock.lock(); let picture = source; lock.unlock()
        guard let picture else { return nil }
        guard let frame = picture.frame(width: settings.width,
                                        height: settings.height) else { return nil }
        return Pixels.composite(frame, overlay, width: settings.width,
                                height: settings.height)
    }

    /// What is on the screen, in words.
    func describePicture() -> String {
        lock.lock(); let picture = source; lock.unlock()
        return picture?.describe() ?? "nothing yet"
    }

    /// What the stream is doing, for Command+Shift+B.
    func statusLine() -> String {
        lock.lock()
        let now = state
        let said = detail
        let frames = videoFrames
        lock.unlock()
        switch now {
        case .off: return "Off air"
        case .connecting: return "Connecting"
        case .failed: return "Off air. \(said)"
        case .retrying: return "Reconnecting. \(said)"
        case .live:
            let seconds = Int(elapsed)
            let where_ = StreamServers.serverLabel(settings.server)
            var line = "On air to \(where_) for \(seconds / 60) minutes "
                     + "\(seconds % 60) seconds, \(frames) frames sent"
            if let source { line += ", showing \(source.describe())" }
            let picture = health.describe()
            if picture != "the picture looks fine" { line += ". " + picture }
            return line
        }
    }

    // ------------------------------------------------------------ the pump ---

    private func run(rate: Double) {
        guard let bus else { return }
        guard let aac = AACEncoder(rate: rate, bitrate: settings.audioBitrate) else {
            set(.failed, "the sound encoder would not start")
            return
        }
        let chunk = AACEncoder.frameSize
        guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2),
              let pcm = AVAudioPCMBuffer(pcmFormat: format,
                                         frameCapacity: AVAudioFrameCount(chunk))
        else { return }
        var interleaved = [Float](repeating: 0, count: chunk * 2)

        let video = VideoEncoder(width: settings.width, height: settings.height,
                                 fps: settings.fps, bitrate: settings.videoBitrate)
        guard video.open() else {
            set(.failed, video.error)
            return
        }
        encoder = video

        var sequenceSent = false
        var backoff = 1.0

        while true {
            lock.lock(); let finishing = stopping; lock.unlock()
            if finishing { break }

            if client == nil {
                let made = RTMPClient(url: settings.host, key: settings.key)
                do {
                    try made.connect()
                    client = made
                    backoff = 1.0
                    sequenceSent = false
                    try made.send(metadata: FLV.metadata(
                        width: settings.width, height: settings.height,
                        fps: settings.fps, videoBitrate: settings.videoBitrate,
                        audioBitrate: settings.audioBitrate,
                        sampleRate: Int(rate), channels: 2))
                    try made.send(audio: FLV.audio(
                        FLV.audioSpecificConfig(sampleRate: Int(rate), channels: 2),
                        sequence: true), timestamp: 0)
                    set(.live, StreamServers.serverLabel(settings.server))
                } catch {
                    made.close()
                    reconnects += 1
                    set(.retrying, "\(error)")
                    var waited = 0.0
                    while waited < backoff {
                        lock.lock(); let f = stopping; lock.unlock()
                        if f { break }
                        Thread.sleep(forTimeInterval: 0.1)
                        waited += 0.1
                    }
                    backoff = min(15.0, backoff * 2)
                    continue
                }
            }
            guard let client else { continue }

            // A platform that is going to refuse may do it after the first
            // frames rather than at publish, so it is asked every turn.
            if let refused = client.refusal() {
                client.close()
                self.client = nil
                set(.failed, refused)
                break
            }

            // The picture is swapped here rather than under the caller, so the
            // old one is closed on this thread and never while it is being read.
            lock.lock()
            if let wanted = wantedSource {
                let old = source
                source = wanted
                wantedSource = nil
                lock.unlock()
                old?.close()
                health.reset()
                video.forceKeyframe()
            } else {
                lock.unlock()
            }

            let ready = bus.available()
            behindSeconds = Double(ready) / rate
            if ready < chunk {
                Thread.sleep(forTimeInterval: C.streamPollSeconds)
                continue
            }

            interleaved.withUnsafeMutableBufferPointer { raw in
                bus.read(frames: chunk, into: raw.baseAddress!)
                pcm.frameLength = AVAudioFrameCount(chunk)
                guard let channels = pcm.floatChannelData else { return }
                for i in 0..<chunk {
                    channels[0][i] = raw[i * 2]
                    channels[1][i] = raw[i * 2 + 1]
                }
            }
            samplesSent += chunk
            let milliseconds = Int(Double(samplesSent) * 1000.0 / rate)

            var ok = true
            if let packet = aac.encode(pcm) {
                for frame in VideoStreamer.adtsFrames(packet) {
                    do {
                        try client.send(audio: FLV.audio(FLV.stripADTS(frame),
                                                         sequence: false),
                                        timestamp: milliseconds)
                    } catch { ok = false; break }
                }
            }

            if ok { ok = pumpVideo(client: client, video: video,
                                   milliseconds: milliseconds,
                                   sequenceSent: &sequenceSent) }
            if !ok {
                client.close()
                self.client = nil
                connectedLost()
            }
        }
        video.close()
        client?.close()
        client = nil
    }

    /// How many frames should exist by now, capped.
    private func pumpVideo(client: RTMPClient, video: VideoEncoder,
                           milliseconds: Int, sequenceSent: inout Bool) -> Bool {
        lock.lock(); let picture = source; lock.unlock()
        guard let picture else { return true }

        let wanted = milliseconds * settings.fps / 1000
        var behind = wanted - videoFrames
        if behind <= 0 { return true }
        // See the note at the top: a burst is what choppy looks like.
        behind = min(behind, C.rtmpCatchupFrames)

        for _ in 0..<behind {
            guard let frame = picture.frame(width: settings.width,
                                            height: settings.height) else {
                videoFrames += 1
                continue
            }
            // The overlay goes on here, once per frame, into a buffer of our
            // own. See Pixels.composite for why it must not go onto the one
            // the source handed back.
            let shown = Pixels.composite(frame, overlay, width: settings.width,
                                         height: settings.height)
            health.look(buffer: shown, moving: picture.moving)
            if framer.due(), let camera = VideoStreamer.cameraFrame(picture) {
                framer.look(camera)
            }
            let at = videoFrames * 1000 / settings.fps
            video.encode(shown, milliseconds: at)
            videoFrames += 1
        }

        for out in video.drain() {
            do {
                if !sequenceSent, let config = video.config {
                    try client.send(video: FLV.video(config.record(), keyframe: true,
                                                     sequence: true),
                                    timestamp: out.timestamp)
                    sequenceSent = true
                }
                try client.send(video: FLV.video(out.data, keyframe: out.keyframe,
                                                 sequence: false),
                                timestamp: out.timestamp)
            } catch {
                return false
            }
        }
        return true
    }

    /// The camera's own picture, for the framing checker.
    ///
    /// NOT the composite: on a shared screen that is mostly desktop with the
    /// presenter a quarter of the width in the corner, and a face detector
    /// given that would report a shot nobody is actually in.
    static func cameraFrame(_ source: PictureSource) -> CVPixelBuffer? {
        if let camera = source as? CameraSource { return camera.latestFrame() }
        if let split = source as? SplitSource { return split.latestFrame() }
        if let fallback = source as? FallbackSource {
            return cameraFrame(fallback.primary)
        }
        return nil
    }

    /// An AAC packet from the app's encoder is one or more ADTS frames, and
    /// each declares its own length. RTMP carries the raw frames.
    static func adtsFrames(_ packet: Data) -> [Data] {
        var out: [Data] = []
        var at = packet.startIndex
        while packet.distance(from: at, to: packet.endIndex) > 7 {
            let b3 = Int(packet[packet.index(at, offsetBy: 3)])
            let b4 = Int(packet[packet.index(at, offsetBy: 4)])
            let b5 = Int(packet[packet.index(at, offsetBy: 5)])
            let length = ((b3 & 0x03) << 11) | (b4 << 3) | ((b5 & 0xe0) >> 5)
            guard length > 7,
                  packet.distance(from: at, to: packet.endIndex) >= length else { break }
            let end = packet.index(at, offsetBy: length)
            out.append(packet.subdata(in: at..<end))
            at = end
        }
        // Not ADTS at all: hand it back whole rather than dropping the audio.
        return out.isEmpty ? [packet] : out
    }

    private func connectedLost() {
        reconnects += 1
        // The stream loses picture and sound and your own monitoring carries
        // on, which is the right way round.
        set(.retrying, "the connection dropped")
    }

    private func say(_ text: String) {
        guard !text.isEmpty else { return }
        DispatchQueue.main.async { [weak self] in self?.onSay?(text) }
    }

    private func set(_ newState: StreamState, _ newDetail: String) {
        lock.lock()
        state = newState
        detail = newDetail
        lock.unlock()
        DispatchQueue.main.async { [weak self] in
            self?.onState?(newState, newDetail)
        }
    }
}

/// What a video broadcast needs. Built from the board, the same way
/// `StreamSettings` is, and deliberately SEPARATE from the picture's own
/// settings: Windows keeps three dictionaries here and the reason is a bug
/// that shipped. Reading the picture out of the destination's settings gives a
/// board pointed at a radio station no picture key at all, and the shot check
/// then confidently describes a card the user never chose.
struct VideoStreamSettings {
    var server = "youtube"
    var host = ""
    var key = ""
    var width = C.rtmpWidth
    var height = C.rtmpHeight
    var fps = C.rtmpFPS
    var videoBitrate = C.rtmpVideoBitrate
    var audioBitrate = C.defaultStreamBitrate
    var framingLevel = C.framingProblems
    var overlay = OverlaySettings()
}
