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

/// What a stream can be encoded as, and the one thing every encoder has to do.
///
/// THE FORMAT IS THE SERVER'S CHOICE, NOT OURS. A mount somebody set up years
/// ago expects what it expects, so this build offers every format macOS can
/// really produce rather than the one that was easiest to write.
///
///   AAC in ADTS   native, self framing, what most Icecast and SHOUTcast 2
///                 mounts take, and the default.
///   Opus in Ogg   native encoder, and the Ogg pages are written here. This is
///                 the one Icecast recommends now: better than MP3 at half the
///                 bitrate, and an Ogg mount expects an Ogg stream.
///   WAV           16 bit PCM with a streaming header. Not a broadcast format
///                 and it is not offered as one: it is for a local relay or
///                 for feeding another encoder, and the Preferences window
///                 says exactly that.
///
/// MP3 IS NOT HERE AND CANNOT BE, and it is worth writing down why so nobody
/// spends another evening on it. macOS has no MP3 encoder at any layer. Asked
/// directly, kAudioFormatProperty_Encoders returns nothing for '.mp3' while
/// returning Apple's own encoders for AAC, Opus, FLAC and ALAC, and
/// AVAudioConverter to MP3 is nil at every rate. afconvert lists MP3 because it
/// can READ it. Shipping MP3 out means vendoring LAME, which is a licensing
/// decision and a signed and notarized third party binary inside the bundle,
/// and that is Tony's call rather than something to slip into a release.
protocol StreamEncoder: AnyObject {
    /// How many frames of the CARD's audio to hand over at a time.
    var frameSize: Int { get }
    /// The Content-Type the server is told.
    var mimeType: String { get }
    var isUsable: Bool { get }
    var lastError: String? { get }
    /// Bytes to send once, before any audio. Nil for a self framing format.
    func preamble() -> Data?
    func encode(_ pcm: AVAudioPCMBuffer) -> Data?
}

/// The encoder for one format, or nil when this build cannot make one.
func makeStreamEncoder(format: String, rate: Double, bitrate: Int) -> StreamEncoder? {
    switch format {
    case C.streamFormatOpus: return OggOpusEncoder(rate: rate, bitrate: bitrate)
    case C.streamFormatWAV: return PCMEncoder(rate: rate)
    default: return AACEncoder(rate: rate, bitrate: bitrate)
    }
}

/// AAC low complexity, wrapped in ADTS.
///
/// ADTS is self framing, so a listener can join a stream part way through and
/// there is no container to keep in step. macOS encodes AAC natively, which is
/// why it is the default here.
final class AACEncoder: StreamEncoder {

    private var converter: AVAudioConverter?
    private let inputFormat: AVAudioFormat
    private let outputFormat: AVAudioFormat
    private let rate: Double
    private let bitrate: Int
    private(set) var lastError: String?

    /// One AAC frame is always 1024 samples.
    static let frameSize = 1024
    var frameSize: Int { AACEncoder.frameSize }
    var mimeType: String { "audio/aac" }
    func preamble() -> Data? { nil }

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
}

// ------------------------------------------------------------------- Ogg ---

/// Ogg pages, written here because macOS cannot write one.
///
/// Apple encodes Opus natively and then has nowhere to put it: afconvert
/// produces a zero byte file for an Ogg output, measured. The container is 27
/// bytes of header, a lacing table and a CRC, so it is written rather than
/// vendored. One packet per page, which is what every live Opus encoder does
/// and what keeps a listener joining part way through in sync.
struct OggStream {

    let serial: UInt32
    private var sequence: UInt32 = 0

    init(serial: UInt32 = UInt32.random(in: 1...UInt32.max)) { self.serial = serial }

    /// The Ogg variant: polynomial 0x04c11db7, no reflection, no final xor.
    /// Not the CRC32 in zlib, and a stream with the wrong one is refused by
    /// every player with no useful message.
    private static let crcTable: [UInt32] = {
        var table = [UInt32](repeating: 0, count: 256)
        for i in 0..<256 {
            var r = UInt32(i) << 24
            for _ in 0..<8 {
                r = (r & 0x8000_0000) != 0 ? (r << 1) ^ 0x04c1_1db7 : (r << 1)
            }
            table[i] = r
        }
        return table
    }()

    static func crc(_ bytes: [UInt8]) -> UInt32 {
        var r: UInt32 = 0
        for b in bytes { r = (r << 8) ^ crcTable[Int(((r >> 24) & 0xFF) ^ UInt32(b))] }
        return r
    }

    /// One packet in one page. Every packet this app writes is far below the
    /// 255 by 255 a single page can carry.
    mutating func page(_ packet: [UInt8], granule: Int64,
                       bos: Bool = false, eos: Bool = false) -> Data {
        var lacing: [UInt8] = []
        var left = packet.count
        while left >= 255 { lacing.append(255); left -= 255 }
        lacing.append(UInt8(left))

        var page: [UInt8] = Array("OggS".utf8)
        page.append(0)                                        // version
        page.append((bos ? 0x02 : 0) | (eos ? 0x04 : 0))      // header type
        withUnsafeBytes(of: granule.littleEndian) { page.append(contentsOf: $0) }
        withUnsafeBytes(of: serial.littleEndian) { page.append(contentsOf: $0) }
        withUnsafeBytes(of: sequence.littleEndian) { page.append(contentsOf: $0) }
        let crcAt = page.count
        page.append(contentsOf: [0, 0, 0, 0])                 // CRC, filled below
        page.append(UInt8(lacing.count))
        page.append(contentsOf: lacing)
        page.append(contentsOf: packet)
        withUnsafeBytes(of: OggStream.crc(page).littleEndian) { bytes in
            for (i, b) in bytes.enumerated() { page[crcAt + i] = b }
        }
        sequence &+= 1
        return Data(page)
    }
}

/// Opus in Ogg, as RFC 7845 lays it out.
///
/// Opus only ever runs at 48 kHz, so a 44.1 kHz card is resampled by the same
/// converter that encodes. The granule position is counted in 48 kHz samples
/// whatever the card is doing, which is the part that is easy to get wrong and
/// which makes a stream that plays at the wrong speed.
final class OggOpusEncoder: StreamEncoder {

    /// Twenty milliseconds at 48 kHz, the ordinary Opus frame.
    private static let opusFrames = 960
    private static let opusRate = 48000.0
    /// libopus always throws away this much at the start.
    private static let preSkip: UInt16 = 312

    private var converter: AVAudioConverter?
    private let outputFormat: AVAudioFormat
    private let cardRate: Double
    private var ogg = OggStream()
    private var granule: Int64 = Int64(OggOpusEncoder.preSkip)
    private(set) var lastError: String?

    /// Fed at the card's rate, so a 44.1 kHz card hands over a little more than
    /// twenty milliseconds each time and the converter sorts it out.
    var frameSize: Int {
        Int(((Double(OggOpusEncoder.opusFrames) / OggOpusEncoder.opusRate) * cardRate).rounded())
    }
    var mimeType: String { "audio/ogg" }
    var isUsable: Bool { converter != nil }

    init?(rate: Double, bitrate: Int) {
        cardRate = rate
        guard let input = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2)
        else { return nil }
        var description = AudioStreamBasicDescription(
            mSampleRate: OggOpusEncoder.opusRate,
            mFormatID: kAudioFormatOpus,
            mFormatFlags: 0, mBytesPerPacket: 0,
            mFramesPerPacket: UInt32(OggOpusEncoder.opusFrames),
            mBytesPerFrame: 0, mChannelsPerFrame: 2,
            mBitsPerChannel: 0, mReserved: 0)
        guard let output = AVAudioFormat(streamDescription: &description) else { return nil }
        outputFormat = output
        guard let c = AVAudioConverter(from: input, to: output) else { return nil }
        // Opus tops out well below the AAC list; asking for 320 gets 256 and a
        // stream nobody needed that much of.
        c.bitRate = min(256, max(32, bitrate)) * 1000
        converter = c
    }

    /// The two header pages every Ogg Opus stream begins with.
    func preamble() -> Data? {
        var head: [UInt8] = Array("OpusHead".utf8)
        head.append(1)                                        // version
        head.append(2)                                        // channels
        withUnsafeBytes(of: OggOpusEncoder.preSkip.littleEndian) { head.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt32(cardRate).littleEndian) { head.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt16(0).littleEndian) { head.append(contentsOf: $0) }
        head.append(0)                                        // mapping family

        var tags: [UInt8] = Array("OpusTags".utf8)
        let vendor = Array("\(C.appName) \(C.appVersion)".utf8)
        withUnsafeBytes(of: UInt32(vendor.count).littleEndian) { tags.append(contentsOf: $0) }
        tags.append(contentsOf: vendor)
        withUnsafeBytes(of: UInt32(0).littleEndian) { tags.append(contentsOf: $0) }

        var out = ogg.page(head, granule: 0, bos: true)
        out.append(ogg.page(tags, granule: 0))
        return out
    }

    func encode(_ pcm: AVAudioPCMBuffer) -> Data? {
        guard let converter else { return nil }
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
            var packet = [UInt8](repeating: 0, count: length)
            packet.withUnsafeMutableBytes { raw in
                raw.baseAddress!.copyMemory(from: base + Int(d.mStartOffset), byteCount: length)
            }
            granule += Int64(OggOpusEncoder.opusFrames)
            out.append(ogg.page(packet, granule: granule))
        }
        return out.isEmpty ? nil : out
    }
}

/// Sixteen bit PCM, with a WAV header that never ends.
///
/// Honest about what it is: the sizes in the header are the streaming
/// convention of "unknown", so a player takes it as a stream rather than a
/// file, and a listener who joins part way through gets no header at all and
/// hears nothing. That is a property of PCM over HTTP and not something this
/// can fix, which is why Preferences says it is for a relay or for feeding
/// another encoder rather than for an audience.
final class PCMEncoder: StreamEncoder {

    private let rate: Double
    private(set) var lastError: String?

    var frameSize: Int { 2048 }
    var mimeType: String { "audio/wav" }
    var isUsable: Bool { rate > 0 }

    init(rate: Double) { self.rate = rate }

    func preamble() -> Data? {
        let bytesPerSecond = UInt32(rate) * 4
        var h: [UInt8] = Array("RIFF".utf8)
        // "Unknown length", which is what every streaming WAV writes.
        withUnsafeBytes(of: UInt32.max.littleEndian) { h.append(contentsOf: $0) }
        h.append(contentsOf: Array("WAVEfmt ".utf8))
        withUnsafeBytes(of: UInt32(16).littleEndian) { h.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt16(1).littleEndian) { h.append(contentsOf: $0) }   // PCM
        withUnsafeBytes(of: UInt16(2).littleEndian) { h.append(contentsOf: $0) }   // channels
        withUnsafeBytes(of: UInt32(rate).littleEndian) { h.append(contentsOf: $0) }
        withUnsafeBytes(of: bytesPerSecond.littleEndian) { h.append(contentsOf: $0) }
        withUnsafeBytes(of: UInt16(4).littleEndian) { h.append(contentsOf: $0) }   // block align
        withUnsafeBytes(of: UInt16(16).littleEndian) { h.append(contentsOf: $0) }  // bits
        h.append(contentsOf: Array("data".utf8))
        withUnsafeBytes(of: UInt32.max.littleEndian) { h.append(contentsOf: $0) }
        return Data(h)
    }

    func encode(_ pcm: AVAudioPCMBuffer) -> Data? {
        guard let channels = pcm.floatChannelData else { return nil }
        let frames = Int(pcm.frameLength)
        guard frames > 0 else { return nil }
        var out = [Int16](repeating: 0, count: frames * 2)
        for i in 0..<frames {
            // Clamped, because a float that has crept above one wraps round to
            // full scale the other way and puts a bang on the air.
            out[i * 2] = Int16(max(-32768, min(32767, (channels[0][i] * 32767).rounded())))
            out[i * 2 + 1] = Int16(max(-32768, min(32767, (channels[1][i] * 32767).rounded())))
        }
        return out.withUnsafeBufferPointer { Data(buffer: $0) }
    }
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
        guard makeStreamEncoder(format: settings.format, rate: rate,
                                bitrate: settings.bitrate)?.isUsable == true else {
            set(.failed, "this sound card's rate cannot be encoded as "
                         + (C.streamFormatLabels[settings.format] ?? settings.format))
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
        guard let bus, let encoder = makeStreamEncoder(format: settings.format, rate: rate,
                                                       bitrate: settings.bitrate)
        else { return }
        guard let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2)
        else { return }

        let chunk = encoder.frameSize
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
                    // Ogg and WAV both begin with bytes that are not audio, and
                    // a reconnect is a new request body, so they go again. AAC
                    // is self framing and has none.
                    if let preamble = encoder.preamble(), !send(preamble) {
                        connected = false
                        connection?.cancel()
                        connection = nil
                        set(.retrying, "the connection dropped")
                        continue
                    }
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
        // The server is told what is really coming. Getting this wrong is how a
        // mount ends up serving Opus as audio/aac and every player refusing it.
        let mime = makeStreamEncoder(format: settings.format, rate: C.defaultSampleRate,
                                     bitrate: settings.bitrate)?.mimeType ?? "audio/aac"

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
