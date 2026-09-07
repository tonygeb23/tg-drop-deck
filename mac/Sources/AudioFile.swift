// The decoder behind one door, tags, and the run out.
//
// The Windows copy has two decoders, libsndfile with FFmpeg behind it, and one
// rule about the pair: the extension list is what the decoders can really
// decode, so nothing is offered that would then fail at the moment somebody
// pressed a key. macOS has one decoder, Core Audio, and the same rule applies,
// so the list is ASKED of the system rather than typed out here.
//
// Measured on macOS 26: that list covers wav, mp3, ogg, opus, flac, aiff, w64,
// au, m4a, m4b, mp4, aac, ac3 and amr, which is everything the Windows build
// plays except wma, webm, mka, ape and wv. Those five are refused honestly
// rather than offered and then failed on.

import Foundation
import AVFoundation
import AudioToolbox

enum AudioFile {

    static let channels: AVAudioChannelCount = 2

    /// Every extension Core Audio says it can read, lower case, without the
    /// dot. Asked once and cached.
    static let supportedExtensions: Set<String> = {
        var size: UInt32 = 0
        guard AudioFileGetGlobalInfoSize(kAudioFileGlobalInfo_ReadableTypes,
                                         0, nil, &size) == noErr else { return [] }
        let count = Int(size) / MemoryLayout<UInt32>.size
        var types = [UInt32](repeating: 0, count: count)
        guard AudioFileGetGlobalInfo(kAudioFileGlobalInfo_ReadableTypes,
                                     0, nil, &size, &types) == noErr else { return [] }
        var exts = Set<String>()
        for type in types {
            var t = type
            var s = UInt32(MemoryLayout<CFArray?>.size)
            var arr: Unmanaged<CFArray>?
            let status = withUnsafeMutablePointer(to: &arr) { ptr -> OSStatus in
                AudioFileGetGlobalInfo(kAudioFileGlobalInfo_ExtensionsForType,
                                       UInt32(MemoryLayout<UInt32>.size), &t, &s, ptr)
            }
            if status == noErr, let list = arr?.takeRetainedValue() as? [String] {
                for e in list { exts.insert(e.lowercased()) }
            }
        }
        // Container extensions that hold video as often as audio. Offering
        // them in a sound picker is noise.
        exts.subtract(["mov", "qt", "3gp", "3g2", "3gpp", "3gp2", "mpg4"])
        return exts
    }()

    /// The same list, short enough to say out loud.
    static var spokenFormats: String {
        let common = ["wav", "mp3", "ogg", "opus", "flac", "aiff", "m4a", "aac"]
        return common.filter { supportedExtensions.contains($0) }
                     .joined(separator: ", ")
    }

    static func canPlay(path: String) -> Bool {
        supportedExtensions.contains((path as NSString).pathExtension.lowercased())
    }

    // ------------------------------------------------------------ reading ---

    /// Everything a slot needs to know about a file without decoding it.
    struct Info {
        var duration: Double
        var sampleRate: Double
        var frames: AVAudioFramePosition
    }

    static func probe(_ path: String) -> Info? {
        guard let f = try? AVAudioFile(forReading: URL(fileURLWithPath: path)) else {
            return nil
        }
        let rate = f.fileFormat.sampleRate
        guard rate > 0 else { return nil }
        return Info(duration: Double(f.length) / rate, sampleRate: rate, frames: f.length)
    }

    /// Decode a whole file to interleaved stereo float at the target rate.
    ///
    /// One place resamples, which is what keeps the two paths, memory and
    /// disk, sounding the same.
    static func readAll(_ path: String, targetRate: Double) -> [Float]? {
        guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path))
        else { return nil }
        let outFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                      sampleRate: targetRate,
                                      channels: channels,
                                      interleaved: true)!
        guard let converter = AVAudioConverter(from: file.processingFormat, to: outFormat)
        else { return nil }
        // Mastering quality costs nothing here: this runs on the cache warmer,
        // not between a keypress and a sound.
        converter.sampleRateConverterQuality = AVAudioQuality.max.rawValue
        converter.sampleRateConverterAlgorithm = AVSampleRateConverterAlgorithm_Mastering

        let inChunk: AVAudioFrameCount = 32768
        let ratio = targetRate / file.processingFormat.sampleRate
        let outChunk = AVAudioFrameCount(Double(inChunk) * ratio) + 4096

        var out: [Float] = []
        out.reserveCapacity(Int(Double(file.length) * ratio) * 2 + 8192)

        var finished = false
        while !finished {
            guard let outBuf = AVAudioPCMBuffer(pcmFormat: outFormat,
                                                frameCapacity: outChunk) else { break }
            var err: NSError?
            let status = converter.convert(to: outBuf, error: &err) { _, statusOut in
                guard let inBuf = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                                   frameCapacity: inChunk) else {
                    statusOut.pointee = .endOfStream
                    return nil
                }
                do { try file.read(into: inBuf) } catch {
                    statusOut.pointee = .endOfStream
                    return nil
                }
                if inBuf.frameLength == 0 {
                    statusOut.pointee = .endOfStream
                    return nil
                }
                statusOut.pointee = .haveData
                return inBuf
            }
            if let data = outBuf.floatChannelData, outBuf.frameLength > 0 {
                let n = Int(outBuf.frameLength) * Int(channels)
                out.append(contentsOf: UnsafeBufferPointer(start: data[0], count: n))
            }
            if status == .endOfStream || status == .error { finished = true }
            if err != nil { finished = true }
        }
        return out.isEmpty ? nil : out
    }

    // --------------------------------------------------------------- tags ---

    struct Tags {
        var artist: String?
        var title: String?
    }

    /// Artist and title out of the file's own tags.
    ///
    /// Read through Core Audio's info dictionary rather than AVAsset. The
    /// AVAsset properties that answer this were deprecated in favour of an
    /// async API, and this is called from the main thread when somebody pastes
    /// an album in: waiting on an async load there is how a window stops
    /// redrawing. This route is synchronous, cheap and not deprecated.
    ///
    /// A file with broken tags still plays, so nothing here is allowed to be
    /// fatal: every failure just means no artist and no title.
    static func tags(_ path: String) -> Tags {
        var out = Tags()
        var file: AudioFileID?
        let url = URL(fileURLWithPath: path) as CFURL
        guard AudioFileOpenURL(url, .readPermission, 0, &file) == noErr,
              let file else { return out }
        defer { AudioFileClose(file) }

        var size = UInt32(MemoryLayout<CFDictionary?>.size)
        var info: Unmanaged<CFDictionary>?
        let status = withUnsafeMutablePointer(to: &info) { ptr -> OSStatus in
            AudioFileGetProperty(file, kAudioFilePropertyInfoDictionary, &size, ptr)
        }
        guard status == noErr,
              let dictionary = info?.takeRetainedValue() as? [String: Any] else { return out }

        if let title = dictionary[kAFInfoDictionary_Title] as? String, !title.isEmpty {
            out.title = title
        }
        if let artist = dictionary[kAFInfoDictionary_Artist] as? String, !artist.isEmpty {
            out.artist = artist
        }
        return out
    }

    // --------------------------------------------------------- the run out ---

    /// Anything quieter than this counts as silence. About minus 54 dBFS.
    static let silenceFloor: Float = 0.002
    /// A run out longer than this is not a run out, it is a hidden track, and
    /// cutting into one would be worse than the gap.
    static let maxTailScan: Double = 30.0

    /// How many seconds of silence sit on the end of a file.
    ///
    /// An MP3 routinely carries a second or two of digital silence at the end:
    /// encoder padding, or simply where the CD track stopped. Cue three seconds
    /// from the last SAMPLE of such a file and two of those three seconds are
    /// the outgoing track playing nothing while the incoming one comes up
    /// alone. This is measured once, on a background pass, and saved with the
    /// board.
    ///
    /// Returns 0 on any failure, which is the safe answer: it makes the cue
    /// behave exactly as it did before this existed.
    static func tailSilence(_ path: String, duration knownDuration: Double? = nil) -> Double {
        guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path))
        else { return 0.0 }
        let rate = file.processingFormat.sampleRate
        guard rate > 0, file.length > 0 else { return 0.0 }
        let duration = knownDuration ?? Double(file.length) / file.fileFormat.sampleRate

        // Only the last half minute is looked at. Seeking is exact on every
        // format Core Audio opens, so there is no read-through fallback to
        // write here.
        var startedAt = 0.0
        if duration > maxTailScan {
            startedAt = max(0.0, duration - maxTailScan)
            file.framePosition = AVAudioFramePosition(startedAt * rate)
        }

        let window = max(1, Int(0.02 * rate))          // 20 ms
        let chunk = AVAudioFrameCount(window * 64)     // about 1.3 s
        guard let buf = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                         frameCapacity: chunk) else { return 0.0 }

        var lastLoud: Double? = nil
        var played = 0
        let channelCount = Int(file.processingFormat.channelCount)

        while true {
            do { try file.read(into: buf) } catch { break }
            let n = Int(buf.frameLength)
            if n == 0 { break }
            guard let data = buf.floatChannelData else { break }

            var offset = 0
            while offset < n {
                let end = min(offset + window, n)
                var peak: Float = 0
                for c in 0..<channelCount {
                    let p = data[c]
                    for i in offset..<end { peak = max(peak, abs(p[i])) }
                }
                if peak > silenceFloor {
                    // The END of the last loud window, not its start.
                    lastLoud = startedAt + Double(played + end) / rate
                }
                offset = end
            }
            played += n
        }

        guard let loud = lastLoud else { return 0.0 }
        let total = duration > 0 ? duration : startedAt + Double(played) / rate
        return max(0.0, min(maxTailScan, total - loud))
    }
}
