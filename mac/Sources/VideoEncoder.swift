// H.264, through VideoToolbox, for the RTMP side.
//
// The Windows copy runs libx264 inside FFmpeg. There is no FFmpeg here, and
// there does not need to be: VideoToolbox is hardware H.264 on every Mac this
// app runs on. Measured on this machine on 8 September 2026, fed at real time:
// **2.8 per cent of one core at 720p30**, and 7.4 times real time when pushed.
//
// ## The three settings that were measured rather than chosen
//
// **Constant bitrate, and nothing else.** This is the same fault Windows had
// to chase down, arriving by a different road. A still card compresses to
// almost nothing, and both platforms publish bitrate FLOORS: Facebook's is 400
// kbps even at 360p. Asked for 2500 kbps on a static card, measured here:
//
//     AverageBitRate                    329 kbps
//     AverageBitRate + DataRateLimits   244 kbps
//     ConstantBitRate                  2375 kbps
//
// `DataRateLimits` is worse than useless: on MOVING content it undershoots to
// 70 per cent of target. So `ConstantBitRate` is the property, and the other
// two are not set at all.
//
// **Frame reordering off.** B-frames would mean a composition time offset in
// every FLV tag and a decode timestamp to track. With reordering off the
// decode order is the display order, the offset is always zero, and the muxer
// gets simpler in the place where a mistake is hardest to see.
//
// **`EnableLowLatencyRateControl` is deliberately absent.** It sounds exactly
// like what a broadcast wants. Measured: it silently dropped 85 per cent of
// frames, delivering 44 of 300. Nothing reported it.
//
// ## Colour, which is where Windows had a real bug
//
// Windows 3.5.0 fixed a picture converted with the standard definition matrix
// and then sent as high definition, carrying no tag at all so every player
// guessed. Measured here: **VideoToolbox converts at BT.709 whatever these
// properties say**, so it writes the TAG only and the Windows fault cannot
// happen. The opposite one can: setting the matrix to 601 would ship 709
// pixels labelled 601, which is invisible from the sending end. They are set
// to 709 and never touched.

import Foundation
import VideoToolbox
import CoreMedia
import CoreVideo

/// One encoded picture, ready for the muxer.
struct EncodedFrame {
    /// AVCC: each NAL unit preceded by its length in four bytes. VideoToolbox
    /// hands this over directly, so there is no Annex B conversion to write.
    let data: Data
    let keyframe: Bool
    /// Milliseconds against the audio clock. See `VideoEncoder.encode`.
    let timestamp: Int
    /// Always zero, because frame reordering is off. Kept in the type so the
    /// muxer reads as the format does rather than hiding an assumption.
    let compositionOffset: Int
}

/// The parameter sets, which go out once at the top of the stream.
struct AVCConfig {
    let sps: Data
    let pps: Data

    /// The AVCDecoderConfigurationRecord an FLV video tag carries first.
    func record() -> Data {
        var out = Data()
        out.append(1)                                  // configurationVersion
        out.append(sps.count > 1 ? sps[1] : 0x64)      // AVCProfileIndication
        out.append(sps.count > 2 ? sps[2] : 0x00)      // profile_compatibility
        out.append(sps.count > 3 ? sps[3] : 0x1f)      // AVCLevelIndication
        out.append(0xff)                               // 6 bits set, then 4 byte lengths
        out.append(0xe1)                               // 3 bits set, then one SPS
        out.append(UInt8((sps.count >> 8) & 0xff))
        out.append(UInt8(sps.count & 0xff))
        out.append(sps)
        out.append(1)                                  // one PPS
        out.append(UInt8((pps.count >> 8) & 0xff))
        out.append(UInt8(pps.count & 0xff))
        out.append(pps)
        return out
    }
}

final class VideoEncoder {

    private var session: VTCompressionSession?
    private let lock = NSLock()
    private var pending: [EncodedFrame] = []
    private(set) var config: AVCConfig?
    private(set) var framesIn = 0
    private(set) var framesOut = 0
    private(set) var bytesOut = 0
    private(set) var error = ""

    let width: Int
    let height: Int
    let fps: Int
    let bitrate: Int

    init(width: Int, height: Int, fps: Int, bitrate: Int) {
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate = bitrate
    }

    @discardableResult
    func open() -> Bool {
        var made: VTCompressionSession?
        let status = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault, width: Int32(width), height: Int32(height),
            codecType: kCMVideoCodecType_H264, encoderSpecification: nil,
            imageBufferAttributes: nil, compressedDataAllocator: nil,
            outputCallback: nil, refcon: nil, compressionSessionOut: &made)
        guard status == noErr, let session = made else {
            error = "the picture encoder would not start"
            return false
        }
        self.session = session

        func set(_ key: CFString, _ value: CFTypeRef) {
            VTSessionSetProperty(session, key: key, value: value)
        }
        set(kVTCompressionPropertyKey_RealTime, kCFBooleanTrue)
        // High profile with the level worked out for us: 3.1 at 720p30, 4.0 at
        // 1080p30, which is what both platforms ask for. Constrained Baseline,
        // which is what Windows' Media Foundation encoder emits, is refused by
        // both.
        set(kVTCompressionPropertyKey_ProfileLevel, kVTProfileLevel_H264_High_AutoLevel)
        set(kVTCompressionPropertyKey_H264EntropyMode, kVTH264EntropyMode_CABAC)
        set(kVTCompressionPropertyKey_AllowFrameReordering, kCFBooleanFalse)
        set(kVTCompressionPropertyKey_ExpectedFrameRate, NSNumber(value: fps))
        // Two seconds. YouTube asks for two and will not take more than four,
        // and Facebook is the same. Both spellings, because the frame count
        // alone is wrong the moment a source delivers at a different rate.
        set(kVTCompressionPropertyKey_MaxKeyFrameInterval,
            NSNumber(value: fps * C.rtmpKeyframeSeconds))
        set(kVTCompressionPropertyKey_MaxKeyFrameIntervalDuration,
            NSNumber(value: Double(C.rtmpKeyframeSeconds)))
        // See the note at the top: this and NOT AverageBitRate, and NOT
        // DataRateLimits.
        set(kVTCompressionPropertyKey_ConstantBitRate, NSNumber(value: bitrate * 1000))
        set(kVTCompressionPropertyKey_ColorPrimaries, kCVImageBufferColorPrimaries_ITU_R_709_2)
        set(kVTCompressionPropertyKey_TransferFunction, kCVImageBufferTransferFunction_ITU_R_709_2)
        set(kVTCompressionPropertyKey_YCbCrMatrix, kCVImageBufferYCbCrMatrix_ITU_R_709_2)
        VTCompressionSessionPrepareToEncodeFrames(session)
        return true
    }

    /// Encode one picture, stamped against the audio clock.
    ///
    /// **The timestamp is the whole of why a source can be swapped mid stream
    /// without moving the timeline.** It counts frames encoded against the
    /// audio sample counter, never a wall clock and never the camera's own
    /// timing. Carried across from Windows unchanged, and it is the single
    /// most important thing in this file.
    func encode(_ buffer: CVPixelBuffer, milliseconds: Int) {
        guard let session else { return }
        framesIn += 1
        let pts = CMTime(value: CMTimeValue(milliseconds), timescale: 1000)
        let duration = CMTime(value: 1, timescale: CMTimeScale(fps))
        VTCompressionSessionEncodeFrame(
            session, imageBuffer: buffer, presentationTimeStamp: pts,
            duration: duration, frameProperties: nil, infoFlagsOut: nil
        ) { [weak self] status, _, sample in
            guard let self, status == noErr, let sample,
                  CMSampleBufferDataIsReady(sample) else { return }
            self.took(sample, milliseconds: milliseconds)
        }
    }

    private func took(_ sample: CMSampleBuffer, milliseconds: Int) {
        if config == nil, let format = CMSampleBufferGetFormatDescription(sample) {
            config = VideoEncoder.parameterSets(from: format)
        }
        var keyframe = true
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(
                sample, createIfNecessary: false) as? [[CFString: Any]],
           let notSync = attachments.first?[kCMSampleAttachmentKey_NotSync] as? Bool {
            keyframe = !notSync
        }
        guard let block = CMSampleBufferGetDataBuffer(sample) else { return }
        var length = 0
        var pointer: UnsafeMutablePointer<Int8>?
        guard CMBlockBufferGetDataPointer(block, atOffset: 0, lengthAtOffsetOut: nil,
                                          totalLengthOut: &length,
                                          dataPointerOut: &pointer) == noErr,
              let pointer, length > 0 else { return }
        let data = Data(bytes: pointer, count: length)
        lock.lock()
        pending.append(EncodedFrame(data: data, keyframe: keyframe,
                                    timestamp: milliseconds, compositionOffset: 0))
        framesOut += 1
        bytesOut += length
        lock.unlock()
    }

    /// Everything encoded since the last ask.
    func drain() -> [EncodedFrame] {
        lock.lock(); defer { lock.unlock() }
        let out = pending
        pending.removeAll(keepingCapacity: true)
        return out
    }

    /// The SPS and PPS out of a format description.
    static func parameterSets(from format: CMFormatDescription) -> AVCConfig? {
        var count = 0
        guard CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                format, parameterSetIndex: 0, parameterSetPointerOut: nil,
                parameterSetSizeOut: nil, parameterSetCountOut: &count,
                nalUnitHeaderLengthOut: nil) == noErr, count >= 2 else { return nil }
        func setAt(_ index: Int) -> Data? {
            var pointer: UnsafePointer<UInt8>?
            var size = 0
            guard CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                    format, parameterSetIndex: index, parameterSetPointerOut: &pointer,
                    parameterSetSizeOut: &size, parameterSetCountOut: nil,
                    nalUnitHeaderLengthOut: nil) == noErr, let pointer else { return nil }
            return Data(bytes: pointer, count: size)
        }
        guard let sps = setAt(0), let pps = setAt(1) else { return nil }
        return AVCConfig(sps: sps, pps: pps)
    }

    /// Ask for a keyframe now. Used when the picture source is swapped, so a
    /// viewer joining at that moment is not left with half of the old shot.
    func forceKeyframe() {
        guard let session else { return }
        VTSessionSetProperty(session, key: kVTEncodeFrameOptionKey_ForceKeyFrame,
                             value: kCFBooleanTrue)
    }

    func close() {
        guard let session else { return }
        VTCompressionSessionCompleteFrames(session, untilPresentationTimeStamp: .invalid)
        VTCompressionSessionInvalidate(session)
        self.session = nil
    }
}
