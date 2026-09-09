// An RTMP client, written by hand over the Network framework.
//
// This is the one genuinely new thing in the Mac's video work. Everything else
// is either arithmetic retyped from the Windows copy or a system framework
// doing its job; nothing on a Mac speaks RTMP, so this is a protocol
// implementation rather than a port.
//
// It is small enough to read in one sitting because a PUBLISHER needs about a
// third of RTMP. There is no playback here, no seeking, no shared objects, no
// server side scripting: a handshake, a chunk layer, five AMF0 commands, and
// then audio and video tags until somebody presses the key again.
//
// ## What it speaks
//
//     handshake      C0/C1 out, S0/S1/S2 in, C2 out. The simple version, not
//                    the signed one, which is what every ingest accepts from
//                    a publisher.
//     connect        with the app name out of the URL
//     releaseStream  and FCPublish, which YouTube and Facebook both expect
//     createStream   answered with a stream id
//     publish        answered with NetStream.Publish.Start, after which the
//                    tags flow
//
// ## RTMPS is not a preference
//
// Facebook has refused unencrypted RTMP since 2018 and YouTube asks for RTMPS,
// so `rtmps` gets TLS from `Network` with nothing added to the app. Measured
// on this Mac: both ingests complete a TLS 1.3 handshake in about a quarter of
// a second.
//
// ## The stream key never appears in anything that can be read out
//
// It is the last path component of the URL and it is a credential: anybody
// holding a YouTube key can broadcast to that channel. `StreamServers.hostLabel`
// is what the status line and the pre-flight use, and nothing here logs a URL.

import Foundation
import Network

enum RTMPError: Error, CustomStringConvertible {
    case badURL
    case refused(String)
    case handshake(String)
    case dropped(String)

    var description: String {
        switch self {
        case .badURL: return "that address is not one this can use"
        case .refused(let why): return why
        case .handshake(let why): return why
        case .dropped(let why): return why
        }
    }
}

/// One inbound message, put back together out of its chunks.
struct RTMPMessage {
    let type: UInt8
    let streamID: UInt32
    let payload: Data
}

/// The chunk layer, incoming.
///
/// **This is the half that was missing, and missing it cost a release.** RTMP
/// does not put a message on the wire in one piece: it cuts it into chunks and
/// puts a header byte in front of every piece after the first, and until the
/// server has been told otherwise those pieces are 128 bytes long. So
/// `NetConnection.Connect.Success`, which is what YouTube answers a connect
/// with, arrives as `NetConnection.Conne`, then a header byte, then
/// `ct.Success`.
///
/// The first version of this client looked for those names in the raw bytes.
/// That works against `tools/mock_rtmp.py`, whose replies are small enough to
/// fit in one chunk, and it does not work against YouTube. Measured against
/// the real ingest on 8 September 2026: the connect succeeded, the answer
/// arrived in 311 bytes, and searching for the name found nothing, so the app
/// waited fifteen seconds, gave up, and sat on "connecting" for ever.
///
/// A publisher needs to UNDERSTAND about six of these messages and can ignore
/// the rest, but it has to unwrap all of them to find the six.
struct RTMPChunkReader {

    /// What the far end says its chunks are. 128 until it says otherwise, and
    /// it always says otherwise early.
    private(set) var chunkSize = 128

    private struct Partial {
        var type: UInt8 = 0
        var streamID: UInt32 = 0
        var length: Int = 0
        var timestamp: Int = 0
        var payload = Data()
    }
    private var streams: [UInt32: Partial] = [:]

    /// Take whatever has arrived and hand back every WHOLE message in it,
    /// leaving the leftovers in `buffer` for next time.
    mutating func read(from buffer: inout Data) -> [RTMPMessage] {
        var out: [RTMPMessage] = []
        while true {
            guard let (message, used) = one(buffer) else { break }
            buffer.removeFirst(used)
            if let message {
                // Set Chunk Size. Everything after it is cut differently, so
                // this one is acted on here rather than handed up.
                if message.type == 1, message.payload.count >= 4 {
                    let value = message.payload.prefix(4).reduce(0) { ($0 << 8) | Int($1) }
                    if value > 0 { chunkSize = min(value, 0x00ff_ffff) }
                }
                out.append(message)
            }
        }
        return out
    }

    /// One chunk off the front. Returns the message when that chunk finished
    /// one, and how many bytes were consumed, or nothing when there is not a
    /// whole chunk yet.
    private mutating func one(_ data: Data) -> (RTMPMessage?, Int)? {
        var at = 0
        func byte(_ i: Int) -> UInt8? {
            let index = data.index(data.startIndex, offsetBy: i, limitedBy: data.endIndex)
            guard let index, index < data.endIndex else { return nil }
            return data[index]
        }
        guard let first = byte(at) else { return nil }
        at += 1
        let fmt = (first >> 6) & 0x03

        // The chunk stream id, in one, two or three bytes.
        var csid = UInt32(first & 0x3f)
        if csid == 0 {
            guard let b = byte(at) else { return nil }
            csid = UInt32(b) + 64
            at += 1
        } else if csid == 1 {
            guard let lo = byte(at), let hi = byte(at + 1) else { return nil }
            csid = UInt32(hi) * 256 + UInt32(lo) + 64
            at += 2
        }

        var partial = streams[csid] ?? Partial()
        var timestampField = partial.timestamp

        func three(_ i: Int) -> Int? {
            guard let a = byte(i), let b = byte(i + 1), let c = byte(i + 2) else { return nil }
            return Int(a) << 16 | Int(b) << 8 | Int(c)
        }

        switch fmt {
        case 0:
            guard let ts = three(at), let len = three(at + 3), let type = byte(at + 6),
                  let s0 = byte(at + 7), let s1 = byte(at + 8),
                  let s2 = byte(at + 9), let s3 = byte(at + 10) else { return nil }
            timestampField = ts
            partial.length = len
            partial.type = type
            // The one little endian field in the whole protocol.
            partial.streamID = UInt32(s0) | UInt32(s1) << 8 | UInt32(s2) << 16 | UInt32(s3) << 24
            at += 11
        case 1:
            guard let ts = three(at), let len = three(at + 3),
                  let type = byte(at + 6) else { return nil }
            timestampField = ts
            partial.length = len
            partial.type = type
            at += 7
        case 2:
            guard let ts = three(at) else { return nil }
            timestampField = ts
            at += 3
        default:
            break
        }

        if timestampField == 0xffffff {
            guard let a = byte(at), let b = byte(at + 1),
                  let c = byte(at + 2), let d = byte(at + 3) else { return nil }
            timestampField = Int(a) << 24 | Int(b) << 16 | Int(c) << 8 | Int(d)
            at += 4
        }
        partial.timestamp = timestampField

        // A message longer than one chunk arrives in chunkSize pieces.
        let remaining = max(0, partial.length - partial.payload.count)
        let take = min(chunkSize, remaining)
        guard data.count >= at + take else { return nil }
        if take > 0 {
            let from = data.index(data.startIndex, offsetBy: at)
            partial.payload.append(data[from..<data.index(from, offsetBy: take)])
        }
        at += take

        if partial.payload.count >= partial.length && partial.length > 0 {
            let message = RTMPMessage(type: partial.type, streamID: partial.streamID,
                                      payload: partial.payload)
            partial.payload = Data()
            streams[csid] = partial
            return (message, at)
        }
        streams[csid] = partial
        return (nil, at)
    }
}

/// One publishing connection.
final class RTMPClient {

    // Chunk stream ids. Two so audio and video interleave without either
    // having to rewrite the other's header every message.
    private let controlChunk: UInt32 = 3
    private let audioChunk: UInt32 = 4
    private let videoChunk: UInt32 = 6

    private let messageStreamID: UInt32 = 1

    /// How much of what the server has said is kept. Generous next to the
    /// handshake, which is the largest single thing ever read, and small
    /// enough that it cannot grow over a long broadcast.
    static let keepBytes = 64 * 1024

    private var connection: NWConnection?
    private let queue = DispatchQueue(label: "app.tgstudios.dropdeck.rtmp")
    private var outChunkSize = 4096
    private var streamID: Double = 1
    private var transaction: Double = 1
    /// The last timestamp written on each chunk stream, for the type 1 header.
    private var lastStamp: [UInt32: Int] = [:]

    private let lock = NSLock()
    private var incoming = Data()
    private var reader = RTMPChunkReader()
    /// Commands the server has sent, in order, with the status code that came
    /// with each. Filled by the reassembler rather than by looking for names
    /// in the raw bytes, which is what missed YouTube's answer entirely.
    private var heard: [(command: String, code: String)] = []
    private var handshakeDone = false
    private(set) var bytesSent = 0
    private(set) var connected = false

    let url: String
    let key: String
    private var host = ""
    private var port: UInt16 = 1935
    private var app = ""
    private var secure = false

    init(url: String, key: String) {
        self.url = url
        self.key = key
    }

    /// Everything the server has said, for the diagnostics and the checks.
    /// A publisher acts on about six of these and this is all of them.
    var conversation: [(command: String, code: String)] {
        lock.lock(); defer { lock.unlock() }
        return heard
    }

    /// The full address, key included. Never shown, never logged.
    var publishTarget: String {
        key.isEmpty ? url : url + "/" + key
    }

    // ------------------------------------------------------------ opening ---

    func connect(timeout: Double = 15) throws {
        try parse()
        let host = NWEndpoint.Host(self.host)
        guard let port = NWEndpoint.Port(rawValue: self.port) else {
            throw RTMPError.badURL
        }
        let parameters: NWParameters = secure ? .tls : .tcp
        // Nagle would hold a small chunk back waiting for company, which on a
        // 30 fps stream is a frame of latency for nothing.
        if let tcp = parameters.defaultProtocolStack.internetProtocol as? NWProtocolTCP.Options {
            tcp.noDelay = true
        }
        let made = NWConnection(host: host, port: port, using: parameters)
        connection = made

        let ready = DispatchSemaphore(value: 0)
        var failure: String?
        made.stateUpdateHandler = { state in
            switch state {
            case .ready: ready.signal()
            case .failed(let error): failure = Self.explain(error); ready.signal()
            case .cancelled: failure = "the connection was closed"; ready.signal()
            default: break
            }
        }
        made.start(queue: queue)
        receiveLoop(made)
        if ready.wait(timeout: .now() + timeout) == .timedOut {
            throw RTMPError.dropped("the server did not answer in time")
        }
        if let failure { throw RTMPError.dropped(failure) }

        try handshake(timeout: timeout)
        try sendConnect(timeout: timeout)
        try sendPublish(timeout: timeout)
        connected = true
    }

    private func parse() throws {
        // rtmp://host[:port]/app[/more]
        guard let parsed = URLComponents(string: url), let scheme = parsed.scheme,
              let host = parsed.host, !host.isEmpty else { throw RTMPError.badURL }
        switch scheme.lowercased() {
        case "rtmp": secure = false; port = 1935
        case "rtmps": secure = true; port = 443
        default: throw RTMPError.badURL
        }
        if let given = parsed.port { port = UInt16(given) }
        self.host = host
        // The app is everything after the host, less the leading slash. For
        // YouTube that is "live2", for Facebook "rtmp".
        app = parsed.path.hasPrefix("/") ? String(parsed.path.dropFirst()) : parsed.path
        if app.isEmpty { throw RTMPError.badURL }
    }

    static func explain(_ error: Error) -> String {
        let text = "\(error)".lowercased()
        if text.contains("refused") {
            return "the server refused the connection"
        }
        if text.contains("hostname") || text.contains("notfound")
            || text.contains("cannot find") || text.contains("dnsresolution") {
            return "that address could not be found. Check it, and check you are online"
        }
        if text.contains("timeout") || text.contains("timed out") {
            return "the server did not answer"
        }
        if text.contains("tls") || text.contains("certificate") {
            return "the secure connection to the server could not be made"
        }
        return "the connection to the server failed"
    }

    // ---------------------------------------------------------- handshake ---

    private func handshake(timeout: Double) throws {
        // C0 is one byte of version. C1 is 1536 bytes: four of time, four of
        // zero, and 1528 the server echoes back. The signed handshake exists
        // for Flash player authentication and no ingest asks a publisher for
        // it.
        var c0c1 = Data([0x03])
        var c1 = Data(count: 1536)
        c1[0] = 0; c1[1] = 0; c1[2] = 0; c1[3] = 0
        for i in 8..<1536 { c1[i] = UInt8.random(in: 0...255) }
        c0c1.append(c1)
        try write(c0c1)

        // S0 and S1 and S2 together, and then C2 is S1 echoed.
        let reply = try read(3073, timeout: timeout)
        guard reply.count >= 3073, reply[0] == 0x03 else {
            throw RTMPError.handshake("the server did not answer as an RTMP server")
        }
        let s1 = reply.subdata(in: 1..<1537)
        try write(s1)
        // Everything from here is chunked, so the reassembler takes over. Set
        // before anything else arrives, and anything already buffered is
        // handed to it now.
        lock.lock()
        handshakeDone = true
        drainMessages()
        lock.unlock()
    }

    // ------------------------------------------------------------ commands ---

    private func sendConnect(timeout: Double) throws {
        // Tell the server how big our chunks are before anything else, or
        // every message over 128 bytes has to be split into 128 byte pieces.
        try write(chunk(type: 0, chunkStream: 2, messageType: 1, streamID: 0,
                        timestamp: 0, payload: be32(UInt32(outChunkSize))))

        var body = AMF0.encode(.string("connect"))
        body.append(AMF0.encode(.number(nextTransaction())))
        body.append(AMF0.encode(.object([
            ("app", .string(app)),
            ("type", .string("nonprivate")),
            ("flashVer", .string("FMLE/3.0 (compatible; \(C.appName))")),
            ("tcUrl", .string(url)),
        ])))
        try write(chunk(type: 0, chunkStream: controlChunk, messageType: 20,
                        streamID: 0, timestamp: 0, payload: body))

        guard let said = try waitFor(code: ["NetConnection.Connect.Success"],
                                   timeout: timeout) else {
            throw RTMPError.refused("the server did not accept the connection")
        }
        if said != "NetConnection.Connect.Success" {
            throw RTMPError.refused(Self.saying(said))
        }
    }

    private func sendPublish(timeout: Double) throws {
        // releaseStream and FCPublish. YouTube and Facebook both expect them
        // and neither answers, so nothing waits on them.
        for name in ["releaseStream", "FCPublish"] {
            var body = AMF0.encode(.string(name))
            body.append(AMF0.encode(.number(nextTransaction())))
            body.append(AMF0.encode(.null))
            body.append(AMF0.encode(.string(key)))
            try write(chunk(type: 0, chunkStream: controlChunk, messageType: 20,
                            streamID: 0, timestamp: 0, payload: body))
        }

        var create = AMF0.encode(.string("createStream"))
        create.append(AMF0.encode(.number(nextTransaction())))
        create.append(AMF0.encode(.null))
        try write(chunk(type: 0, chunkStream: controlChunk, messageType: 20,
                        streamID: 0, timestamp: 0, payload: create))
        _ = try waitFor(code: [], timeout: timeout, wantCommand: "_result")

        var publish = AMF0.encode(.string("publish"))
        publish.append(AMF0.encode(.number(nextTransaction())))
        publish.append(AMF0.encode(.null))
        publish.append(AMF0.encode(.string(key)))
        publish.append(AMF0.encode(.string("live")))
        try write(chunk(type: 0, chunkStream: controlChunk, messageType: 20,
                        streamID: messageStreamID, timestamp: 0, payload: publish))

        // **Do NOT wait for NetStream.Publish.Start, because YouTube never
        // sends it.** Measured against the real ingest on 8 September 2026:
        // connect is answered, onBWDone arrives, createStream is answered, and
        // then publish gets silence. Silence before the metadata, silence
        // after the metadata, silence after an audio sequence header, for
        // twelve seconds.
        //
        // Waiting for it is therefore a deadlock, and it is the one that
        // shipped: the app waited fifteen seconds for a status that was never
        // coming, gave up, retried, and sat on "connecting to YouTube" for
        // ever while YouTube sat waiting for a stream.
        //
        // So this is what every real encoder does: say publish, wait only long
        // enough to catch a refusal that comes straight back, and then START
        // SENDING. A server that is going to say no says it in an `_error` or
        // an onStatus, and `refusal()` is checked on every turn of the pump
        // after this, so a no that arrives later still stops the broadcast.
        if let said = try waitFor(code: [], timeout: C.rtmpPublishGrace),
           said != "publish" {
            throw RTMPError.refused(Self.saying(said))
        }
    }

    /// A refusal the server has sent at any point, or nothing.
    ///
    /// The pump asks this every turn. `publish` is not answered by every
    /// platform, so the absence of an answer is not an error and cannot be
    /// treated as one; the presence of a refusal always is.
    func refusal() -> String? {
        lock.lock(); defer { lock.unlock() }
        for entry in heard {
            if RTMPClient.refusals.contains(entry.code) { return Self.saying(entry.code) }
            if entry.command == "_error" {
                return entry.code.isEmpty
                    ? "the server refused the stream"
                    : Self.saying(entry.code)
            }
        }
        return nil
    }

    /// What one of the server's refusals means, in a sentence.
    static func saying(_ code: String) -> String {
        switch code {
        case "NetConnection.Connect.Rejected", "NetStream.Publish.Denied":
            return "the server refused the stream key"
        case "NetConnection.Connect.InvalidApp":
            return "that address has the wrong application name in it"
        case "NetStream.Publish.BadName":
            return "something is already publishing with that stream key"
        default:
            return "the server refused the stream: \(code)"
        }
    }

    // ------------------------------------------------------------- sending ---

    /// One FLV tag out. `timestamp` is milliseconds against the audio clock.
    func send(audio payload: Data, timestamp: Int) throws {
        try sendTag(chunkStream: audioChunk, messageType: 8,
                    payload: payload, timestamp: timestamp)
    }

    func send(video payload: Data, timestamp: Int) throws {
        try sendTag(chunkStream: videoChunk, messageType: 9,
                    payload: payload, timestamp: timestamp)
    }

    func send(metadata payload: Data) throws {
        try sendTag(chunkStream: controlChunk, messageType: 18,
                    payload: payload, timestamp: 0)
    }

    private func sendTag(chunkStream: UInt32, messageType: UInt8,
                         payload: Data, timestamp: Int) throws {
        // A type 0 header every time is four bytes more than a type 1 and is
        // what makes this recoverable: no chunk depends on the one before it,
        // so a message never has to be rebuilt because an earlier one moved.
        try write(chunk(type: 0, chunkStream: chunkStream, messageType: messageType,
                        streamID: messageStreamID, timestamp: timestamp,
                        payload: payload))
        lastStamp[chunkStream] = timestamp
    }

    // -------------------------------------------------------------- chunks ---

    private func chunk(type: UInt8, chunkStream: UInt32, messageType: UInt8,
                       streamID: UInt32, timestamp: Int, payload: Data) -> Data {
        var out = Data()
        out.append(UInt8((type << 6) | UInt8(chunkStream & 0x3f)))

        // Past 0xffffff the timestamp moves to an extended field at the end of
        // the header and the three byte one is all ones. A show over four
        // hours and a half reaches this, so it is not theoretical.
        let extended = timestamp >= 0xffffff
        let shown = extended ? 0xffffff : timestamp
        out.append(UInt8((shown >> 16) & 0xff))
        out.append(UInt8((shown >> 8) & 0xff))
        out.append(UInt8(shown & 0xff))

        out.append(UInt8((payload.count >> 16) & 0xff))
        out.append(UInt8((payload.count >> 8) & 0xff))
        out.append(UInt8(payload.count & 0xff))
        out.append(messageType)
        // The message stream id is the one little endian field in the whole
        // protocol, which is a wart of the format and not a mistake here.
        out.append(contentsOf: withUnsafeBytes(of: streamID.littleEndian) { Array($0) })
        if extended {
            out.append(contentsOf: be32(UInt32(timestamp)))
        }

        // Split into chunks, each continuation carrying a one byte type 3
        // header.
        var at = payload.startIndex
        var first = true
        while at < payload.endIndex {
            if !first {
                out.append(UInt8(0xc0 | UInt8(chunkStream & 0x3f)))
                if extended { out.append(contentsOf: be32(UInt32(timestamp))) }
            }
            let take = min(outChunkSize, payload.distance(from: at, to: payload.endIndex))
            let end = payload.index(at, offsetBy: take)
            out.append(payload[at..<end])
            at = end
            first = false
        }
        return out
    }

    private func be32(_ value: UInt32) -> Data {
        Data([UInt8((value >> 24) & 0xff), UInt8((value >> 16) & 0xff),
              UInt8((value >> 8) & 0xff), UInt8(value & 0xff)])
    }

    private func nextTransaction() -> Double {
        transaction += 1
        return transaction - 1
    }

    // ---------------------------------------------------------- the socket ---

    private func write(_ data: Data) throws {
        guard let connection else { throw RTMPError.dropped("the connection is gone") }
        let done = DispatchSemaphore(value: 0)
        var failure: String?
        connection.send(content: data, completion: .contentProcessed { error in
            if let error { failure = Self.explain(error) }
            done.signal()
        })
        if done.wait(timeout: .now() + 20) == .timedOut {
            throw RTMPError.dropped("the connection stopped accepting anything")
        }
        if let failure { throw RTMPError.dropped(failure) }
        lock.lock(); bytesSent += data.count; lock.unlock()
    }

    private func receiveLoop(_ connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) {
            [weak self] data, _, complete, error in
            guard let self else { return }
            if let data, !data.isEmpty {
                self.lock.lock()
                self.incoming.append(data)
                self.drainMessages()
                // **Trimmed, or a three hour show grows a buffer for three
                // hours.** The server goes on sending acknowledgements and
                // ping requests for as long as the stream is up, and nothing
                // here consumes them: this client only ever LOOKS for a
                // command name. So the tail is kept, which is where anything
                // new is, and the rest is dropped.
                if self.incoming.count > RTMPClient.keepBytes {
                    self.incoming = self.incoming.suffix(RTMPClient.keepBytes)
                }
                self.lock.unlock()
            }
            // **Only a finished stream ends the loop.** An error on one read
            // used to end it for good, which on a connection that had not
            // finished coming up meant nothing was ever received again.
            if complete { return }
            self.receiveLoop(connection)
        }
    }

    /// Take whole messages out of the buffer and remember what they said.
    /// Called with the lock held.
    private func drainMessages() {
        guard handshakeDone else { return }
        for message in reader.read(from: &incoming) where message.type == 20 {
            let values = AMF0.read(message.payload)
            guard let name = AMF0.firstString(in: values) else { continue }
            heard.append((name, AMF0.code(in: values) ?? ""))
        }
    }

    private func read(_ count: Int, timeout: Double) throws -> Data {
        let until = Date().addingTimeInterval(timeout)
        while Date() < until {
            lock.lock()
            if incoming.count >= count {
                let out = incoming.prefix(count)
                incoming.removeFirst(count)
                lock.unlock()
                return Data(out)
            }
            lock.unlock()
            Thread.sleep(forTimeInterval: 0.01)
        }
        throw RTMPError.dropped("the server stopped answering")
    }

    /// Wait for the server to say one of these, or to say something else.
    ///
    /// Deliberately forgiving about the chunk layer on the way IN. A publisher
    /// only ever needs the AMF0 command messages, and the acknowledgements,
    /// window sizes and peer bandwidth messages that arrive alongside them
    /// carry nothing this acts on. So rather than a full reassembler this
    /// looks for the command names in what has arrived, which cannot be fooled
    /// into a wrong answer: the strings are length prefixed and unique.
    /// Wait for the server to say one of these, or to say something else.
    ///
    /// Asks the REASSEMBLER, not the raw bytes. A command name is split across
    /// chunk boundaries as a matter of course, so looking for one in what
    /// arrived finds it only when the reply happens to be short. YouTube's is
    /// not, and that is exactly how this shipped broken.
    private func waitFor(code wanted: [String], timeout: Double,
                         wantCommand: String? = nil) throws -> String? {
        let until = Date().addingTimeInterval(timeout)
        while Date() < until {
            lock.lock()
            let said = heard
            lock.unlock()
            for entry in said {
                if wanted.contains(entry.code) { return entry.code }
                if let wantCommand, entry.command == wantCommand {
                    // A _result with no status code is still an answer: that
                    // is what createStream sends back.
                    return entry.code.isEmpty ? wantCommand : entry.code
                }
                if entry.command == "_error" || RTMPClient.refusals.contains(entry.code) {
                    return entry.code.isEmpty ? "_error" : entry.code
                }
            }
            Thread.sleep(forTimeInterval: 0.02)
        }
        return nil
    }

    static let refusals: Set<String> = [
        "NetConnection.Connect.Rejected", "NetStream.Publish.Denied",
        "NetConnection.Connect.InvalidApp", "NetStream.Publish.BadName",
        "NetConnection.Connect.Failed",
    ]

    func close() {
        connected = false
        connection?.cancel()
        connection = nil
    }
}
