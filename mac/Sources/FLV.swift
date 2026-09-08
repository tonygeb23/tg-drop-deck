// AMF0 and FLV: the two little formats RTMP is made of.
//
// There is no FFmpeg on the Mac, so this is written out by hand. It is a small
// job and a well specified one; what makes it worth care is that every mistake
// in it produces a stream that CONNECTS and then looks wrong to everybody
// except the person sending it.
//
// Two things measured on this Mac on 8 September 2026 make it smaller than it
// looks. VideoToolbox emits **AVCC with four byte length prefixes**, which is
// exactly what an FLV video tag carries, so there is no Annex B conversion to
// write. And with frame reordering off the decode order is the display order,
// so the composition time offset is always zero.

import Foundation

// ------------------------------------------------------------------- AMF0 ---

/// The little value format RTMP's control messages are written in.
enum AMF0 {

    enum Value {
        case number(Double)
        case bool(Bool)
        case string(String)
        case object([(String, Value)])
        case null
        case ecmaArray([(String, Value)])
    }

    static func encode(_ value: Value) -> Data {
        var out = Data()
        switch value {
        case .number(let n):
            out.append(0x00)
            out.append(contentsOf: withUnsafeBytes(of: n.bitPattern.bigEndian) { Array($0) })
        case .bool(let b):
            out.append(0x01)
            out.append(b ? 1 : 0)
        case .string(let s):
            out.append(0x02)
            out.append(string(s))
        case .object(let pairs):
            out.append(0x03)
            for (key, item) in pairs {
                out.append(string(key))
                out.append(encode(item))
            }
            out.append(contentsOf: [0x00, 0x00, 0x09])   // end of object
        case .null:
            out.append(0x05)
        case .ecmaArray(let pairs):
            out.append(0x08)
            out.append(contentsOf: withUnsafeBytes(of: UInt32(pairs.count).bigEndian) { Array($0) })
            for (key, item) in pairs {
                out.append(string(key))
                out.append(encode(item))
            }
            out.append(contentsOf: [0x00, 0x00, 0x09])
        }
        return out
    }

    /// A string with its two byte length, which is how a KEY is written: no
    /// type marker. The marker belongs to the value.
    private static func string(_ s: String) -> Data {
        let bytes = Array(s.utf8)
        var out = Data()
        out.append(UInt8((bytes.count >> 8) & 0xff))
        out.append(UInt8(bytes.count & 0xff))
        out.append(contentsOf: bytes)
        return out
    }

    /// Enough of a reader to find out what the server said.
    ///
    /// Only what is needed: the command name, and the `code` inside whatever
    /// object came with it, because that is where `NetStream.Publish.Start`
    /// and every refusal live.
    static func read(_ data: Data) -> [Value] {
        var at = data.startIndex
        var out: [Value] = []
        while at < data.endIndex, let (value, next) = readOne(data, at) {
            out.append(value)
            at = next
        }
        return out
    }

    private static func readOne(_ d: Data, _ at: Data.Index) -> (Value, Data.Index)? {
        guard at < d.endIndex else { return nil }
        let marker = d[at]
        var i = d.index(after: at)
        switch marker {
        case 0x00:
            guard d.distance(from: i, to: d.endIndex) >= 8 else { return nil }
            var raw: UInt64 = 0
            for _ in 0..<8 { raw = (raw << 8) | UInt64(d[i]); i = d.index(after: i) }
            return (.number(Double(bitPattern: raw)), i)
        case 0x01:
            guard i < d.endIndex else { return nil }
            let b = d[i] != 0
            return (.bool(b), d.index(after: i))
        case 0x02:
            guard let (s, next) = readString(d, i) else { return nil }
            return (.string(s), next)
        case 0x03, 0x08:
            if marker == 0x08 { i = d.index(i, offsetBy: 4, limitedBy: d.endIndex) ?? d.endIndex }
            var pairs: [(String, Value)] = []
            while i < d.endIndex {
                guard let (key, afterKey) = readString(d, i) else { return nil }
                i = afterKey
                if key.isEmpty, i < d.endIndex, d[i] == 0x09 {
                    return (.object(pairs), d.index(after: i))
                }
                guard let (value, afterValue) = readOne(d, i) else { return nil }
                pairs.append((key, value))
                i = afterValue
            }
            return (.object(pairs), i)
        case 0x05, 0x06:
            return (.null, i)
        default:
            return nil
        }
    }

    private static func readString(_ d: Data, _ at: Data.Index) -> (String, Data.Index)? {
        guard d.distance(from: at, to: d.endIndex) >= 2 else { return nil }
        var i = at
        let hi = Int(d[i]); i = d.index(after: i)
        let lo = Int(d[i]); i = d.index(after: i)
        let length = hi << 8 | lo
        guard d.distance(from: i, to: d.endIndex) >= length else { return nil }
        let end = d.index(i, offsetBy: length)
        return (String(decoding: d[i..<end], as: UTF8.self), end)
    }

    /// The `code` out of whatever the server sent, which is the only field
    /// anything here acts on.
    static func code(in values: [Value]) -> String? {
        for value in values {
            if case .object(let pairs) = value {
                for (key, item) in pairs where key == "code" {
                    if case .string(let s) = item { return s }
                }
            }
        }
        return nil
    }

    static func firstString(in values: [Value]) -> String? {
        for value in values { if case .string(let s) = value { return s } }
        return nil
    }
}

// -------------------------------------------------------------------- FLV ---

enum FLV {

    /// The first byte of an audio tag: AAC, 44.1 kHz, 16 bit, stereo.
    ///
    /// The rate and channel bits are what an FLV header can say, and AAC
    /// ignores them: the real rate and channel count come from the
    /// AudioSpecificConfig below. They are still written the way every encoder
    /// writes them, because some ingests read them anyway.
    static let aacHeader: UInt8 = 0xaf          // 1010 1111

    /// An audio tag body. `sequence` is the one that carries the
    /// AudioSpecificConfig and goes first, once.
    static func audio(_ payload: Data, sequence: Bool) -> Data {
        var out = Data()
        out.append(aacHeader)
        out.append(sequence ? 0x00 : 0x01)
        out.append(payload)
        return out
    }

    /// A video tag body.
    ///
    /// The first nibble is the frame type, 1 for a keyframe and 2 for the
    /// rest, and the second is 7 for AVC.
    static func video(_ payload: Data, keyframe: Bool, sequence: Bool,
                      compositionOffset: Int = 0) -> Data {
        var out = Data()
        out.append(keyframe ? 0x17 : 0x27)
        out.append(sequence ? 0x00 : 0x01)
        let offset = Int32(compositionOffset)
        out.append(UInt8((offset >> 16) & 0xff))
        out.append(UInt8((offset >> 8) & 0xff))
        out.append(UInt8(offset & 0xff))
        out.append(payload)
        return out
    }

    /// The AudioSpecificConfig for AAC, built rather than read.
    ///
    /// **Do not take this from `AVAudioConverter.magicCookie`.** Measured on
    /// this Mac: that cookie is a 39 byte elementary stream descriptor, and
    /// the two bytes wanted are buried inside it at descriptor tag 0x05. It is
    /// two bytes of bit packing to build and one wrong offset to extract, so
    /// it is built: five bits of object type, four of a rate index, four of a
    /// channel count, then three spare.
    static func audioSpecificConfig(sampleRate: Int, channels: Int,
                                    objectType: Int = 2) -> Data {
        let rates = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050,
                     16000, 12000, 11025, 8000, 7350]
        let index = rates.firstIndex(of: sampleRate) ?? 4      // 44100
        let first = UInt8((objectType << 3) | ((index >> 1) & 0x07))
        let second = UInt8(((index & 0x01) << 7) | ((channels & 0x0f) << 3))
        return Data([first, second])
    }

    /// The `@setDataFrame` body that tells the platform what is coming.
    ///
    /// Not decoration. YouTube's health page reads these and reports a stream
    /// with no metadata as a problem, which is a thing a presenter cannot see
    /// and would be told about by a viewer.
    static func metadata(width: Int, height: Int, fps: Int, videoBitrate: Int,
                         audioBitrate: Int, sampleRate: Int, channels: Int) -> Data {
        var out = AMF0.encode(.string("@setDataFrame"))
        out.append(AMF0.encode(.string("onMetaData")))
        out.append(AMF0.encode(.ecmaArray([
            ("duration", .number(0)),
            ("width", .number(Double(width))),
            ("height", .number(Double(height))),
            ("videodatarate", .number(Double(videoBitrate))),
            ("framerate", .number(Double(fps))),
            ("videocodecid", .number(7)),              // AVC
            ("audiodatarate", .number(Double(audioBitrate))),
            ("audiosamplerate", .number(Double(sampleRate))),
            ("audiosamplesize", .number(16)),
            ("stereo", .bool(channels > 1)),
            ("audiocodecid", .number(10)),             // AAC
            ("encoder", .string("\(C.appName) \(C.appVersion)")),
        ])))
        return out
    }

    /// Strip the ADTS header an AAC encoder puts on every frame.
    ///
    /// **RTMP must not carry it.** The Mac's existing `AACEncoder` writes ADTS
    /// because that is what an Icecast mount wants: a header on every frame is
    /// what lets a listener joining halfway through work out the rate and the
    /// channels. An RTMP stream is told once, in the sequence header, and a
    /// second copy on every frame is a decoder error at the other end.
    ///
    /// The header is seven bytes, or nine when it carries a CRC, and the flag
    /// for that is the low bit of the second byte, inverted.
    static func stripADTS(_ frame: Data) -> Data {
        guard frame.count > 7, frame[frame.startIndex] == 0xff,
              (frame[frame.index(after: frame.startIndex)] & 0xf0) == 0xf0 else {
            return frame
        }
        let hasCRC = (frame[frame.index(after: frame.startIndex)] & 0x01) == 0
        let length = hasCRC ? 9 : 7
        guard frame.count > length else { return frame }
        return frame.subdata(in: frame.index(frame.startIndex, offsetBy: length)..<frame.endIndex)
    }
}
