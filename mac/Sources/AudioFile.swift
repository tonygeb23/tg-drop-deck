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
import CryptoKit
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

    // ------------------------------------------- what a file really is ---
    //
    // Raymond, in-app feedback 46, 21 October 2026: songs from Suno, one MP3
    // and one M4A, "won't play". Not reproduced: nobody here has his files.
    // What WAS measured on this Mac, 16 November 2026: AVAudioFile opens an
    // MP3 with five megabytes of cover art in its tag, an M4A with artwork,
    // ALAC, FLAC and Opus inside MP4, and an M4A that also carries a video
    // track. What it refuses is a file whose CONTENTS do not match its NAME:
    // AAC in a file called .mp3, and (for AVAssetReader too) MP3 in a file
    // called .m4a. Audio File Services takes its first guess from the
    // extension, and a download that has been renamed, or a site that names
    // its files carelessly, is exactly that. Opened through a link with the
    // right name, every one of them plays. A WebM file is the one thing here
    // macOS cannot decode at all, and that is now said in as many words.

    /// What a file is from its first bytes, as the extension it should have,
    /// or nil when it is not recognised.
    static func sniff(_ path: String) -> String? {
        guard let handle = FileHandle(forReadingAtPath: path) else { return nil }
        defer { try? handle.close() }
        guard let head = try? handle.read(upToCount: 16), head.count >= 4 else { return nil }
        let b = [UInt8](head)
        func text(_ at: Int, _ n: Int) -> String {
            guard b.count >= at + n else { return "" }
            return String(bytes: b[at..<(at + n)], encoding: .isoLatin1) ?? ""
        }
        if text(4, 4) == "ftyp" { return "m4a" }
        if text(0, 3) == "ID3" { return "mp3" }
        if text(0, 4) == "RIFF" && text(8, 4) == "WAVE" { return "wav" }
        if text(0, 4) == "RF64" { return "wav" }
        if text(0, 4) == "fLaC" { return "flac" }
        if text(0, 4) == "OggS" { return "ogg" }
        if text(0, 4) == "FORM" && (text(8, 4) == "AIFF" || text(8, 4) == "AIFC") { return "aiff" }
        if text(0, 4) == "caff" { return "caf" }
        if text(0, 5) == "#!AMR" { return "amr" }
        if b[0] == 0x1A && b[1] == 0x45 && b[2] == 0xDF && b[3] == 0xA3 { return "webm" }
        if b[0] == 0x30 && b[1] == 0x26 && b[2] == 0xB2 && b[3] == 0x75 { return "wma" }
        if b[0] == 0xFF && (b[1] & 0xF6) == 0xF0 { return "aac" }       // ADTS
        if b[0] == 0xFF && (b[1] & 0xE0) == 0xE0 && (b[1] & 0x06) != 0 { return "mp3" }
        return nil
    }

    /// The URL to open a file through: the file itself, or, when its name
    /// says one thing and its contents another, a link to it in the temporary
    /// folder with the name its contents deserve. Nothing is copied or moved.
    static func namedRight(_ path: String) -> URL? {
        guard let real = sniff(path), supportedExtensions.contains(real) else { return nil }
        let ext = (path as NSString).pathExtension.lowercased()
        // Already called what it is; a different name would change nothing.
        if ext == real || (real == "m4a" && ["m4a", "m4b", "mp4", "aac", "alac"].contains(ext)) {
            return nil
        }
        let folder = (NSTemporaryDirectory() as NSString).appendingPathComponent("dropdeck-named")
        try? FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
        let key = Insecure.SHA1.hash(data: Data(path.utf8)).map { String(format: "%02x", $0) }.joined()
        let link = (folder as NSString).appendingPathComponent("\(key).\(real)")
        if (try? FileManager.default.destinationOfSymbolicLink(atPath: link)) != path {
            try? FileManager.default.removeItem(atPath: link)
            do { try FileManager.default.createSymbolicLink(atPath: link, withDestinationPath: path) }
            catch { return nil }
        }
        return URL(fileURLWithPath: link)
    }

    /// The one way a sound file is opened for reading.
    ///
    /// **By its contents FIRST when they disagree with its name**, and not
    /// only when macOS refuses it. Measured on this Mac: AAC written by
    /// AVAudioFile and then called .mp3 is not refused at all. It OPENS, as
    /// an MP3, and is 0.02 seconds long, because the parser finds something
    /// that looks like a frame header and plays that. A pad that "plays" a
    /// fiftieth of a second of nothing is exactly "they won't play", and a
    /// fallback that waits for a refusal never runs. The sniff is sixteen
    /// bytes, which is nothing beside opening the file.
    static func open(_ path: String) -> AVAudioFile? {
        if let renamed = namedRight(path), let file = try? AVAudioFile(forReading: renamed) {
            return file
        }
        return try? AVAudioFile(forReading: URL(fileURLWithPath: path))
    }

    /// Why a file will not open, as the end of a sentence: "Could not play
    /// Intro, " and then this. "They won't play" is what somebody says when
    /// the app gave them no reason, so there is always one.
    static func refusal(_ path: String) -> String {
        let files = FileManager.default
        guard files.fileExists(atPath: path) else { return "the file is not there" }
        let size = ((try? files.attributesOfItem(atPath: path))?[.size] as? NSNumber)?.intValue ?? 0
        if size == 0 { return "the file is empty" }
        let ext = (path as NSString).pathExtension.lowercased()
        let named: [String: String] = ["webm": "a WebM file", "wma": "a Windows Media file"]
        if let real = sniff(path), !supportedExtensions.contains(real) {
            let what = named[real] ?? "a \(real.uppercased()) file"
            return "it is really \(what), and macOS cannot play those"
        }
        if !ext.isEmpty && !supportedExtensions.contains(ext) {
            return "macOS cannot play \(ext.uppercased()) files"
        }
        return "macOS could not decode it, so it may be damaged or not what its name says"
    }

    static func probe(_ path: String) -> Info? {
        guard let f = open(path) else {
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
        guard let file = open(path) else { return nil }
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
        // By its contents first when they disagree with its name, as `open`.
        let url = (namedRight(path) ?? URL(fileURLWithPath: path)) as CFURL
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
        guard let file = open(path) else { return 0.0 }
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
