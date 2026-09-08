import Foundation
import CoreVideo
import AVFoundation

let args = CommandLine.arguments
guard args.count >= 2 else { print("need a url"); exit(2) }
let url = args[1]
// The mock's url is rtmp://host:port/app/key; split the key off the end.
let parts = url.split(separator: "/")
let key = String(parts.last ?? "test")
let base = String(url.dropLast(key.count + 1))
print("publishing to", base, "key", key)

let client = RTMPClient(url: base, key: key)
do { try client.connect(timeout: 15) } catch {
    print("CONNECT FAILED:", error); exit(1)
}
print("connected and publishing")

let W = 640, H = 360, FPS = 30, SECONDS = 3
let encoder = VideoEncoder(width: W, height: H, fps: FPS, bitrate: 1000)
guard encoder.open() else { print("encoder failed"); exit(1) }

try client.send(metadata: FLV.metadata(width: W, height: H, fps: FPS,
                                       videoBitrate: 1000, audioBitrate: 128,
                                       sampleRate: 44100, channels: 2))

// Audio: a real AAC stream from the app's own encoder, so the sequence header
// and the ADTS stripping are both exercised.
guard let aac = AACEncoder(rate: 44100, bitrate: 128) else { print("no aac"); exit(1) }
try client.send(audio: FLV.audio(FLV.audioSpecificConfig(sampleRate: 44100, channels: 2),
                                 sequence: true), timestamp: 0)

let card = CardSource(name: "Mock Test", title: "Frame 0")
var sentVideo = 0, sentAudio = 0, keyframes = 0
var sequenceSent = false

// The audio clock is the master. Video is stamped against samples encoded,
// exactly as the real pump will do it.
var samples = 0
let format = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 2)!
let blockFrames = 1024

for frame in 0..<(FPS * SECONDS) {
    card.setTitle("Frame \(frame)")
    guard let picture = card.frame(width: W, height: H) else { continue }
    let ms = Int(Double(samples) * 1000.0 / 44100.0)
    encoder.encode(picture, milliseconds: ms)

    // Roughly one audio block per video frame at these rates.
    let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(blockFrames))!
    pcm.frameLength = AVAudioFrameCount(blockFrames)
    for c in 0..<2 {
        let ch = pcm.floatChannelData![c]
        for i in 0..<blockFrames {
            ch[i] = 0.25 * sinf(2 * .pi * 440 * Float(samples + i) / 44100)
        }
    }
    if let encoded = aac.encode(pcm) {
        // The app's AAC encoder writes ADTS for Icecast. RTMP must not carry it.
        var at = encoded.startIndex
        while at < encoded.endIndex {
            // Each ADTS frame declares its own length in bytes 3 to 5.
            guard encoded.distance(from: at, to: encoded.endIndex) > 7 else { break }
            let b3 = Int(encoded[encoded.index(at, offsetBy: 3)])
            let b4 = Int(encoded[encoded.index(at, offsetBy: 4)])
            let b5 = Int(encoded[encoded.index(at, offsetBy: 5)])
            let length = ((b3 & 0x03) << 11) | (b4 << 3) | ((b5 & 0xe0) >> 5)
            guard length > 7, encoded.distance(from: at, to: encoded.endIndex) >= length else { break }
            let one = encoded.subdata(in: at..<encoded.index(at, offsetBy: length))
            let raw = FLV.stripADTS(one)
            try client.send(audio: FLV.audio(raw, sequence: false), timestamp: ms)
            sentAudio += 1
            at = encoded.index(at, offsetBy: length)
        }
    }
    samples += blockFrames

    for out in encoder.drain() {
        if !sequenceSent, let config = encoder.config {
            try client.send(video: FLV.video(config.record(), keyframe: true, sequence: true),
                            timestamp: out.timestamp)
            sequenceSent = true
        }
        try client.send(video: FLV.video(out.data, keyframe: out.keyframe, sequence: false),
                        timestamp: out.timestamp)
        sentVideo += 1
        if out.keyframe { keyframes += 1 }
    }
    Thread.sleep(forTimeInterval: 1.0 / Double(FPS))
}
encoder.close()
for out in encoder.drain() {
    try client.send(video: FLV.video(out.data, keyframe: out.keyframe, sequence: false),
                    timestamp: out.timestamp)
    sentVideo += 1
    if out.keyframe { keyframes += 1 }
}
print("sent \(sentVideo) video tags (\(keyframes) keyframes), \(sentAudio) audio tags, \(client.bytesSent) bytes")
client.close()
print("closed")
