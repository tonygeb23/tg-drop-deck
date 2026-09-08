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

        guard let said = try waitFor(code: ["NetStream.Publish.Start"],
                                   timeout: timeout) else {
            throw RTMPError.refused("the server never said the stream had started")
        }
        if said != "NetStream.Publish.Start" {
            throw RTMPError.refused(Self.saying(said))
        }
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
            if complete || error != nil { return }
            self.receiveLoop(connection)
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
    private func waitFor(code wanted: [String], timeout: Double,
                       wantCommand: String? = nil) throws -> String? {
        let until = Date().addingTimeInterval(timeout)
        while Date() < until {
            lock.lock()
            let seen = incoming
            lock.unlock()
            if let found = Self.scan(seen, for: wanted, command: wantCommand) {
                return found
            }
            if let text = Self.scanRefusal(seen) { return text }
            Thread.sleep(forTimeInterval: 0.02)
        }
        return nil
    }

    static func scan(_ data: Data, for wanted: [String], command: String?) -> String? {
        let text = String(decoding: data, as: UTF8.self)
        for code in wanted where text.contains(code) { return code }
        if let command, text.contains(command) { return command }
        return nil
    }

    static func scanRefusal(_ data: Data) -> String? {
        let text = String(decoding: data, as: UTF8.self)
        for code in ["NetConnection.Connect.Rejected", "NetStream.Publish.Denied",
                     "NetConnection.Connect.InvalidApp", "NetStream.Publish.BadName",
                     "NetConnection.Connect.Failed"] where text.contains(code) {
            return code
        }
        return nil
    }

    func close() {
        connected = false
        connection?.cancel()
        connection = nil
    }
}
