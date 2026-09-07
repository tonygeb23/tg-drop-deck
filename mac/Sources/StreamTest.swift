// A headless run of the whole broadcast path, for --streamtest.
//
// Programme bus, encoder, socket, in the shapes the real app uses, with a
// synthetic tone standing in for the show. It exists because the one thing the
// unit checks cannot prove is that a real server on the other end accepts what
// this sends: the ADTS header can be right byte for byte and the handshake
// still be wrong.
//
//   TGDropDeck --streamtest <host> <port> <mount> <user> <password> [seconds]
//
// Run it against tools/mock_icecast.py from the Windows project, which speaks
// enough of both source protocols to be indistinguishable from the far end.

import Foundation

enum StreamTest {

    static func run(_ arguments: [String]) -> Int32 {
        guard arguments.count >= 5 else {
            print("usage: --streamtest <host> <port> <mount> <user> <password> [seconds]")
            return 2
        }
        var settings = StreamSettings()
        settings.host = arguments[0]
        settings.port = Int(arguments[1]) ?? 8000
        settings.mount = arguments[2]
        settings.user = arguments[3]
        settings.password = arguments[4]
        settings.name = "Self test"
        settings.bitrate = 128
        let seconds = arguments.count > 5 ? (Double(arguments[5]) ?? 3.0) : 3.0

        let rate = 48000.0
        // No sound card is opened. The group exists so the streamer can attach
        // its bus to the same taps a mixer would write to.
        let group = MixerGroup(mainDeviceUID: nil, bankDevices: [:])
        let streamer = Streamer()

        var states: [String] = []
        streamer.onState = { state, detail in
            states.append(detail.isEmpty ? state.rawValue : "\(state.rawValue) (\(detail))")
        }

        print("connecting to \(settings.host):\(settings.port)\(settings.mount) ...")
        guard streamer.start(group: group, settings: settings) else {
            print("FAIL: the streamer refused to start")
            return 1
        }

        // A tone, written the way a mixer writes: in blocks, at real time.
        let frames = 512
        var block = [Float](repeating: 0, count: frames * 2)
        var phase = 0.0
        let deadline = Date().addingTimeInterval(seconds)
        var written = 0
        while Date() < deadline {
            for i in 0..<frames {
                let v = Float(sin(phase)) * 0.25
                phase += 2 * .pi * 440 / rate
                block[i * 2] = v
                block[i * 2 + 1] = v
            }
            block.withUnsafeBufferPointer { p in
                group.taps.write(key: "main", samples: p.baseAddress!,
                                 frames: frames, rate: rate)
            }
            written += frames
            // Real time, because the encoder thread drains at real time and
            // running flat out would only prove the ring can overflow.
            Thread.sleep(forTimeInterval: Double(frames) / rate)
        }
        Thread.sleep(forTimeInterval: 0.5)

        let live = streamer.state == .live
        let line = streamer.statusLine()
        streamer.stop(group: group)
        group.stop()

        print("states seen: \(states.joined(separator: " -> "))")
        print("status: \(line)")
        print("wrote \(written) frames of programme")
        if live {
            print("OK: the server took the connection and the audio")
            return 0
        }
        print("FAIL: never reached the live state")
        return 1
    }
}
