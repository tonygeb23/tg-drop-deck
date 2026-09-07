// Streaming to your own station.
//
// It sends everything you can hear: sounds, beds, the running order and,
// unless you turn it off, the microphone. It does NOT send a preview or the
// beep before a track ends, because those are yours and not the listener's.
//
// Encoding and the network run on their own thread, so a bad connection costs
// the stream and never your own audio. That is the right way round and it is
// the whole reason the programme goes through a ring rather than being handed
// to the encoder from the audio callback.
//
// Nothing goes out until you press the key.

import Foundation
import AVFoundation
import AudioToolbox
import Network

/// AAC low complexity, wrapped in ADTS.
///
/// ADTS is self framing, so a listener can join a stream part way through and
/// there is no container to keep in step. macOS encodes AAC natively, which is
/// why it is the format here: there is no MP3 encoder anywhere on this system
/// and Apple's own Ogg muxer cannot write a file.
final class AACEncoder {

    private var converter: AVAudioConverter?
    private let inputFormat: AVAudioFormat
    private let outputFormat: AVAudioFormat
    private let rate: Double
    private let bitrate: Int
    private(set) var lastError: String?

    /// One AAC frame is always 1024 samples.
    static let frameSize = 1024

    init?(rate: Double, bitrate: Int) {
        self.rate = rate
        self.bitrate = bitrate
        guard let input = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2)
        else { return nil }
        var description = AudioStreamBasicDescription(
            mSampleRate: rate,
            mFormatID: kAudioFormatMPEG4AAC,
            mFormatFlags: 0, mBytesPerPacket: 0,
            mFramesPerPacket: UInt32(AACEncoder.frameSize),
            mBytesPerFrame: 0, mChannelsPerFrame: 2,
            mBitsPerChannel: 0, mReserved: 0)
        guard let output = AVAudioFormat(streamDescription: &description) else { return nil }
        inputFormat = input
        outputFormat = output
        guard let c = AVAudioConverter(from: input, to: output) else { return nil }
        c.bitRate = bitrate * 1000
        converter = c
    }

    /// Sample rate index, as ADTS writes it.
    private static let rateIndex: [Double: UInt8] = [
        96000: 0, 88200: 1, 64000: 2, 48000: 3, 44100: 4, 32000: 5,
        24000: 6, 22050: 7, 16000: 8, 12000: 9, 11025: 10, 8000: 11,
    ]

    var isUsable: Bool { AACEncoder.rateIndex[rate] != nil && converter != nil }

    /// Encode one buffer and return the ADTS framed bytes, or nil when the
    /// encoder wanted more input before it could say anything.
    func encode(_ pcm: AVAudioPCMBuffer) -> Data? {
        guard let converter, let index = AACEncoder.rateIndex[rate] else { return nil }
        let compressed = AVAudioCompressedBuffer(
            format: outputFormat, packetCapacity: 8,
            maximumPacketSize: converter.maximumOutputPacketSize)

        var supplied = false
        var error: NSError?
        let status = converter.convert(to: compressed, error: &error) { _, statusOut in
            if supplied {
                statusOut.pointee = .noDataNow
                return nil
            }
            supplied = true
            statusOut.pointee = .haveData
            return pcm
        }
        if let error {
            lastError = error.localizedDescription
            return nil
        }
        guard status != .error, compressed.packetCount > 0,
              let descriptions = compressed.packetDescriptions else { return nil }

        var out = Data()
        let base = compressed.data.assumingMemoryBound(to: UInt8.self)
        for i in 0..<Int(compressed.packetCount) {
            let d = descriptions[i]
            let length = Int(d.mDataByteSize)
            guard length > 0 else { continue }
            out.append(contentsOf: AACEncoder.adtsHeader(payload: length, rateIndex: index))
            out.append(base + Int(d.mStartOffset), count: length)
        }
        return out.isEmpty ? nil : out
    }

    /// Seven bytes, no CRC. Written out rather than pulled from a library so
    /// there is one place to look when a player refuses the stream.
    static func adtsHeader(payload: Int, rateIndex: UInt8,
                           channels: UInt8 = 2) -> [UInt8] {
        let total = payload + 7
        var h = [UInt8](repeating: 0, count: 7)
        h[0] = 0xFF
        // MPEG-4, layer 00, no CRC.
        h[1] = 0xF1
        // Profile is object type minus one; AAC-LC is object type 2, so 01.
        h[2] = (0x01 << 6) | ((rateIndex & 0x0F) << 2) | ((channels >> 2) & 0x01)
        h[3] = UInt8((channels & 0x03) << 6) | UInt8((total >> 11) & 0x03)
        h[4] = UInt8((total >> 3) & 0xFF)
        h[5] = UInt8((total & 0x07) << 5) | 0x1F
        h[6] = 0xFC
        return h
    }

    var mimeType: String { "audio/aac" }
}

// ---------------------------------------------------------- what it is doing ---

enum StreamState: String {
    case off, connecting, live, retrying, failed
    var spoken: String {
        switch self {
        case .off: return "Off air"
        case .connecting: return "Connecting to the server"
        case .live: return "On air"
        case .retrying: return "Off air, trying again"
        case .failed: return "Could not go on air"
        }
    }
}

struct StreamSettings {
    var server = C.streamServerIcecast
    var host = ""
    var port = 8000
    var mount = "/live"
    var user = "source"
    var password = ""
    var format = C.defaultStreamFormat
    var bitrate = C.defaultStreamBitrate
    var name = ""
    var description = ""
    var genre = ""
    var url = ""
    var isPublic = false
    var sendMic = true
    var sendTitles = true
    var statsURL = ""
}

/// The encoder and the socket, on their own thread.
final class Streamer {

    private(set) var state: StreamState = .off
    private(set) var detail: String = ""
    private(set) var startedAt: Date?
    private(set) var reconnects = 0
    private(set) var droppedBlocks = 0
    private(set) var behindSeconds: Double = 0

    var settings = StreamSettings()
    /// Told when the state changes, so the window can speak it and relabel a
    /// menu. Always called on the main queue.
    var onState: ((StreamState, String) -> Void)?

    private var bus: AirBus?
    private var thread: Thread?
    private var stopping = false
    private let lock = NSLock()
    private var connection: NWConnection?
    private var connected = false
    private var currentTitle = ""

    var isOn: Bool {
        lock.lock(); defer { lock.unlock() }
        return state != .off && state != .failed
    }

    var elapsed: Double { startedAt.map { -$0.timeIntervalSinceNow } ?? 0 }

    // -------------------------------------------------------------- going on ---

    @discardableResult
    func start(group: MixerGroup, settings: StreamSettings) -> Bool {
        guard !isOn else { return true }
        guard !settings.host.isEmpty else {
            set(.failed, "there is no server set up yet")
            return false
        }
        self.settings = settings
        let rate = group.sampleRate
        guard AACEncoder(rate: rate, bitrate: settings.bitrate)?.isUsable == true else {
            set(.failed, "this sound card's rate cannot be encoded")
            return false
        }

        let bus = AirBus(sampleRate: rate)
        self.bus = bus
        group.addAirBus(bus)

        stopping = false
        reconnects = 0
        droppedBlocks = 0
        startedAt = Date()
        set(.connecting, settings.host)

        let t = Thread { [weak self] in self?.run(rate: rate) }
        t.name = "dropdeck-stream"
        thread = t
        t.start()
        return true
    }

    func stop(group: MixerGroup) {
        lock.lock(); stopping = true; lock.unlock()
        connection?.cancel()
        connection = nil
        if let bus { group.removeAirBus(bus) }
        bus = nil
        thread = nil
        startedAt = nil
        connected = false
        set(.off, "")
    }

    private func set(_ newState: StreamState, _ newDetail: String) {
        lock.lock()
        state = newState
        detail = newDetail
        lock.unlock()
        let s = newState, d = newDetail
        DispatchQueue.main.async { [weak self] in self?.onState?(s, d) }
    }

    // ------------------------------------------------------------ the thread ---

    private func run(rate: Double) {
        guard let bus, let encoder = AACEncoder(rate: rate, bitrate: settings.bitrate)
        else { return }
        guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2)
        else { return }

        let chunk = AACEncoder.frameSize
        guard let pcm = AVAudioPCMBuffer(pcmFormat: format,
                                         frameCapacity: AVAudioFrameCount(chunk))
        else { return }
        var interleaved = [Float](repeating: 0, count: chunk * 2)

        var backoff = 1.0
        while true {
            lock.lock(); let finishing = stopping; lock.unlock()
            if finishing { break }

            if !connected {
                if connect() {
                    connected = true
                    backoff = 1.0
                    set(.live, settings.host)
                    if settings.sendTitles && !currentTitle.isEmpty {
                        pushMetadata(currentTitle)
                    }
                } else {
                    // The stream loses audio and your own sound carries on,
                    // which is the right way round.
                    reconnects += 1
                    set(.retrying, detail)
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
            guard let packet = encoder.encode(pcm) else { continue }
            if !send(packet) {
                connected = false
                connection?.cancel()
                connection = nil
                set(.retrying, "the connection dropped")
            }
        }
        connection?.cancel()
        connection = nil
        connected = false
    }

    // ------------------------------------------------------------ the socket ---

    private func connect() -> Bool {
        let host = NWEndpoint.Host(settings.host)
        guard let port = NWEndpoint.Port(rawValue: UInt16(settings.port)) else {
            set(.failed, "that port number is not valid")
            return false
        }
        let connection = NWConnection(host: host, port: port, using: .tcp)
        self.connection = connection

        let ready = DispatchSemaphore(value: 0)
        var ok = false
        connection.stateUpdateHandler = { state in
            switch state {
            case .ready: ok = true; ready.signal()
            case .failed, .cancelled: ok = false; ready.signal()
            default: break
            }
        }
        connection.start(queue: DispatchQueue.global(qos: .userInitiated))
        if ready.wait(timeout: .now() + 8) == .timedOut {
            set(.retrying, "the server did not answer")
            connection.cancel()
            self.connection = nil
            return false
        }
        guard ok else {
            set(.retrying, "the server could not be reached")
            connection.cancel()
            self.connection = nil
            return false
        }

        guard send(Data(handshake().utf8)) else {
            set(.retrying, "the server would not take the connection")
            return false
        }

        // Icecast answers a PUT with a status line. SHOUTcast answers "OK2".
        // Either way, silence for a moment means it took it: a source that
        // insists on a reply before sending would hang on a harbor that sends
        // none.
        let answer = readAnswer(timeout: 3.0)
        if let answer, !answer.isEmpty {
            let head = answer.split(separator: "\r\n").first.map(String.init) ?? answer
            if head.contains("401") || head.lowercased().contains("unauthor") {
                set(.failed, "the server refused the password")
                connection.cancel()
                self.connection = nil
                return false
            }
            if head.contains("403") {
                set(.failed, "the server refused the mount point")
                connection.cancel()
                self.connection = nil
                return false
            }
            if head.contains("404") {
                set(.failed, "the server has no such mount point")
                connection.cancel()
                self.connection = nil
                return false
            }
        }
        return true
    }

    /// Prove the settings before the show rather than during it: connect,
    /// send the source handshake, read what the server says, and disconnect.
    /// No audio is ever sent, and the streamer's own state is not touched, so
    /// this is safe to run while another station is on air. Blocking; call it
    /// off the main thread.
    static func testConnection(_ settings: StreamSettings) -> String {
        guard !settings.host.isEmpty else { return "There is no server address to test." }
        guard let port = NWEndpoint.Port(rawValue: UInt16(clamping: settings.port)), settings.port > 0
        else { return "That port number is not valid." }
        let probe = Streamer()
        probe.settings = settings
        let connection = NWConnection(host: NWEndpoint.Host(settings.host), port: port, using: .tcp)
        probe.connection = connection
        defer { connection.cancel(); probe.connection = nil }

        let ready = DispatchSemaphore(value: 0)
        var reached = false
        var why = ""
        connection.stateUpdateHandler = { state in
            switch state {
            case .ready: reached = true; ready.signal()
            case .failed(let error): why = error.localizedDescription; ready.signal()
            case .cancelled: ready.signal()
            default: break
            }
        }
        connection.start(queue: DispatchQueue.global(qos: .userInitiated))
        let where_ = "\(settings.host), port \(settings.port)"
        if ready.wait(timeout: .now() + 8) == .timedOut {
            return "Nothing answered at \(where_) within eight seconds. Check the address and the port."
        }
        guard reached else {
            return "Could not reach \(where_). \(why.isEmpty ? "The connection was refused." : why)"
        }
        guard probe.send(Data(probe.handshake().utf8)) else {
            return "Connected to \(where_), but the server closed the connection before it would take a source."
        }
        let answer = probe.readAnswer(timeout: 3.0) ?? ""
        let head = answer.split(separator: "\r\n").first.map(String.init) ?? answer
        let mount = settings.mount.hasPrefix("/") ? settings.mount : "/" + settings.mount
        if head.contains("401") || head.lowercased().contains("unauthor") {
            return "\(where_) answered, and refused the password. That is the source password it wants, "
                 + "not the listener one, and the user name is almost always source. It said: \(head)"
        }
        if head.contains("403") {
            return "\(where_) answered, and refused the mount point \(mount). It said: \(head)"
        }
        if head.contains("404") {
            return "\(where_) has no mount point called \(mount). It said: \(head)"
        }
        if head.contains("200") || head.uppercased().hasPrefix("OK") || head.contains("100") {
            return "Good. \(where_) took the connection for \(mount) and is ready for a source. "
                 + "It said: \(head). Nothing was broadcast, and the connection is closed again."
        }
        if head.isEmpty {
            return "\(where_) took the connection for \(mount) and said nothing, which is what a "
                 + "Liquidsoap harbor does until audio arrives. That is a pass. Nothing was broadcast."
        }
        return "\(where_) answered with something unexpected: \(head)"
    }

    private func handshake() -> String {
        let credentials = "\(settings.user):\(settings.password)"
        let auth = Data(credentials.utf8).base64EncodedString()
        let mount = settings.mount.hasPrefix("/") ? settings.mount : "/" + settings.mount
        let mime = "audio/aac"

        if settings.server == C.streamServerShoutcast {
            // SHOUTcast's own source verb, which predates HTTP PUT.
            var lines = ["SOURCE \(mount) HTTP/1.0",
                         "Authorization: Basic \(auth)",
                         "User-Agent: \(C.appName)/\(C.appVersion)",
                         "Content-Type: \(mime)",
                         "icy-name: \(settings.name)",
                         "icy-genre: \(settings.genre)",
                         "icy-br: \(settings.bitrate)",
                         "icy-pub: \(settings.isPublic ? 1 : 0)"]
            if !settings.url.isEmpty { lines.append("icy-url: \(settings.url)") }
            return lines.joined(separator: "\r\n") + "\r\n\r\n"
        }

        var lines = ["PUT \(mount) HTTP/1.1",
                     "Host: \(settings.host):\(settings.port)",
                     "Authorization: Basic \(auth)",
                     "User-Agent: \(C.appName)/\(C.appVersion)",
                     "Content-Type: \(mime)",
                     "Ice-Public: \(settings.isPublic ? 1 : 0)",
                     "Ice-Name: \(settings.name)",
                     "Ice-Description: \(settings.description)",
                     "Ice-Genre: \(settings.genre)",
                     "Ice-Audio-Info: bitrate=\(settings.bitrate)",
                     "Expect: 100-continue"]
        if !settings.url.isEmpty { lines.append("Ice-URL: \(settings.url)") }
        return lines.joined(separator: "\r\n") + "\r\n\r\n"
    }

    @discardableResult
    private func send(_ data: Data) -> Bool {
        guard let connection else { return false }
        let done = DispatchSemaphore(value: 0)
        var ok = true
        connection.send(content: data, completion: .contentProcessed { error in
            if error != nil { ok = false }
            done.signal()
        })
        // A send that does not complete in five seconds is a receiver whose
        // window has closed for far too long to be a pause.
        if done.wait(timeout: .now() + 5) == .timedOut { return false }
        return ok
    }

    private func readAnswer(timeout: Double) -> String? {
        guard let connection else { return nil }
        let done = DispatchSemaphore(value: 0)
        var text: String?
        connection.receive(minimumIncompleteLength: 1, maximumLength: 2048) {
            data, _, _, _ in
            if let data, !data.isEmpty { text = String(data: data, encoding: .utf8) }
            done.signal()
        }
        _ = done.wait(timeout: .now() + timeout)
        return text
    }

    // ------------------------------------------------------------- metadata ---

    /// What is playing, sent to the server's admin door rather than in band.
    /// AAC has nowhere to carry it, which is exactly how Icecast expects it.
    func nowPlaying(_ title: String) {
        currentTitle = title
        guard isOn, settings.sendTitles, !title.isEmpty else { return }
        pushMetadata(title)
    }

    private func pushMetadata(_ title: String) {
        let mount = settings.mount.hasPrefix("/") ? settings.mount : "/" + settings.mount
        var components = URLComponents()
        components.scheme = "http"
        components.host = settings.host
        components.port = settings.port
        components.path = "/admin/metadata"
        components.queryItems = [
            URLQueryItem(name: "mode", value: "updinfo"),
            URLQueryItem(name: "mount", value: mount),
            URLQueryItem(name: "song", value: title),
        ]
        guard let url = components.url else { return }
        var request = URLRequest(url: url)
        request.timeoutInterval = 5
        let credentials = "\(settings.user):\(settings.password)"
        let auth = Data(credentials.utf8).base64EncodedString()
        request.setValue("Basic \(auth)", forHTTPHeaderField: "Authorization")
        // Nothing is done with the answer. A station that refuses a title
        // update is still a station taking the audio, and taking the show off
        // air over a metadata refusal would be absurd.
        URLSession.shared.dataTask(with: request).resume()
    }

    /// The line Command Shift B reads out.
    func statusLine() -> String {
        lock.lock()
        let s = state, d = detail
        lock.unlock()
        guard s != .off else {
            return settings.host.isEmpty
                ? "Off air, and no server is set up yet"
                : "Off air. Command B goes live to \(settings.host)"
        }
        var parts = [s.spoken]
        if s == .live {
            parts.append("for \(formatDuration(elapsed))")
            parts.append("\(settings.bitrate) kbps AAC")
            parts.append("to \(settings.host)")
            if let bus, bus.dropped > 0 {
                parts.append("\(bus.dropped) blocks lost, so listeners have heard gaps")
            }
            if behindSeconds > 1.0 {
                parts.append(String(format: "running %.0f seconds behind, "
                                    + "so the connection is not keeping up", behindSeconds))
            }
            if reconnects > 0 { parts.append("reconnected \(reconnects) times") }
        } else if !d.isEmpty {
            parts.append(d)
        }
        return parts.joined(separator: ", ")
    }
}
