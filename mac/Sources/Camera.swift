// The camera, on its own thread, and what to say when it will not open.
//
// Mirrors dropdeck/camera.py in behaviour and in wording. What differs is the
// machinery: Windows opens a camera through FFmpeg and DirectShow, and this
// uses AVFoundation, which is in the process already.
//
// Two rules carried across unchanged, both of which cost a broadcast on
// Windows before they were understood:
//
//   * **Anything that blocks belongs on its own thread, and the caller takes
//     the last frame it finished.** The audio thread must never wait on a
//     camera.
//   * **Stale is the same as gone.** The last frame used to be kept for ever,
//     so a camera unplugged twenty minutes into a show kept handing back the
//     same frozen picture: the fallback never fired, nobody was told, and the
//     framing announcements reported a frozen shot as though it were live.
//     Answering nothing is what lets FallbackSource do its job.
//
// Letterboxed rather than cropped, which is also inherited. Filling the frame
// would mean cutting the edges off, and cutting the edges off a shot the
// presenter cannot see is how somebody ends up broadcasting their own forehead.

import Foundation
import AVFoundation
import CoreVideo
import VideoToolbox
import CoreGraphics

enum Cameras {

    /// Every camera this Mac can see, by name.
    ///
    /// Includes Continuity cameras, which is worth knowing: an iPhone on a
    /// stand is a far better camera than any webcam and it appears here with
    /// no setting up.
    static func all() -> [String] {
        discovery().devices.map { $0.localizedName }
    }

    static func device(named name: String) -> AVCaptureDevice? {
        let devices = discovery().devices
        if let exact = devices.first(where: { $0.localizedName == name }) { return exact }
        if let byID = devices.first(where: { $0.uniqueID == name }) { return byID }
        return name.isEmpty ? devices.first : nil
    }

    private static func discovery() -> AVCaptureDevice.DiscoverySession {
        AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInWideAngleCamera, .external, .continuityCamera],
            mediaType: .video, position: .unspecified)
    }

    /// Whether the user has said yes to the camera, and whether asking is
    /// still possible.
    static func permission() -> AVAuthorizationStatus {
        AVCaptureDevice.authorizationStatus(for: .video)
    }

    /// A size said the way a person says it, not as a pair of numbers.
    static func describeSize(_ width: Int, _ height: Int, fps: Double? = nil) -> String {
        let names: [String: String] = [
            "1920x1080": "1080p", "1280x720": "720p", "854x480": "480p",
            "640x480": "640 by 480", "640x360": "360p",
        ]
        let label = names["\(width)x\(height)"] ?? "\(width) by \(height)"
        if let fps, fps > 0 {
            return "\(label) at \(Int(fps.rounded())) frames a second"
        }
        return label
    }

    /// What a camera that will not open means, turned into the thing to do.
    ///
    /// The common case by a distance is another program holding the device:
    /// OBS, Teams and Zoom all keep a camera for as long as they are running.
    static func explain(_ trouble: String, device: String = "") -> String {
        let name = device.isEmpty ? "the camera" : device
        let lowered = trouble.lowercased()
        if lowered.contains("not connected") || lowered.contains("no such")
            || lowered.contains("could not find") {
            return "\(name) is not there any more. It may have been unplugged"
        }
        if lowered.contains("in use") || lowered.contains("busy")
            || lowered.contains("i/o error") {
            return "\(name) could not be opened. Another program is probably using "
                 + "it: close OBS, Teams or Zoom and try again"
        }
        if lowered.contains("permission") || lowered.contains("denied")
            || lowered.contains("not authorized") {
            return "macOS would not allow access to \(name). Turn Drop Deck on under "
                 + "Camera in System Settings, Privacy and Security"
        }
        if lowered.contains("timed out") { return "\(name) did not respond" }
        return "\(name) could not be opened"
    }
}

/// One camera, delivering into a buffer the caller reads whenever it likes.
final class CameraSource: NSObject, PictureSource, AVCaptureVideoDataOutputSampleBufferDelegate {

    let kind = C.pictureCamera
    let device: String
    private let wantWidth: Int
    private let wantHeight: Int
    private let wantFPS: Int
    private let bars: RGB

    private let lock = NSLock()
    private var session: AVCaptureSession?
    private let queue = DispatchQueue(label: "app.tgstudios.dropdeck.camera")
    private var latest: CVPixelBuffer?
    private var latestAt: Double = 0
    private var scaled: CVPixelBuffer?
    private var scaledKey: String?
    private(set) var error = ""
    private(set) var framesRead = 0
    private(set) var width = 0
    private(set) var height = 0
    private let ready = DispatchSemaphore(value: 0)
    private var signalled = false

    var moving: Bool { true }
    var now: () -> Double = { ProcessInfo.processInfo.systemUptime }

    init(device: String, width: Int? = nil, height: Int? = nil, fps: Int? = nil,
         bars: RGB = C.cardBackground) {
        self.device = device
        self.wantWidth = width ?? C.rtmpWidth
        self.wantHeight = height ?? C.rtmpHeight
        self.wantFPS = fps ?? C.rtmpFPS
        self.bars = bars
    }

    func start() {
        lock.lock()
        if session != nil { lock.unlock(); return }
        lock.unlock()

        if Cameras.permission() == .denied || Cameras.permission() == .restricted {
            setError(Cameras.explain("not authorized", device: device))
            return
        }
        guard let picked = Cameras.device(named: device) else {
            setError(Cameras.explain("not connected", device: device))
            return
        }
        let made = AVCaptureSession()
        made.beginConfiguration()
        // A preset rather than a hand picked format: the encoder letterboxes
        // whatever arrives, so matching exactly buys nothing and a camera that
        // cannot do the asked for size would fail to open for no reason.
        if wantHeight >= 1080, made.canSetSessionPreset(.hd1920x1080) {
            made.sessionPreset = .hd1920x1080
        } else if made.canSetSessionPreset(.hd1280x720) {
            made.sessionPreset = .hd1280x720
        }
        do {
            let input = try AVCaptureDeviceInput(device: picked)
            guard made.canAddInput(input) else {
                made.commitConfiguration()
                setError(Cameras.explain("in use", device: device))
                return
            }
            made.addInput(input)
        } catch {
            made.commitConfiguration()
            setError(Cameras.explain(error.localizedDescription, device: device))
            return
        }
        let output = AVCaptureVideoDataOutput()
        output.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        ]
        // The newest frame is the only one worth having: this is a live shot,
        // not a recording, and a queue of stale frames is latency.
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        guard made.canAddOutput(output) else {
            made.commitConfiguration()
            setError(Cameras.explain("in use", device: device))
            return
        }
        made.addOutput(output)
        made.commitConfiguration()

        lock.lock(); session = made; lock.unlock()
        // startRunning blocks while the device warms up, which is why it is
        // not on the caller's thread.
        queue.async { made.startRunning() }
    }

    /// Wait for a real first frame. Measured on Windows at 0.58 seconds from
    /// open to first frame; the timeout is generous and still short enough
    /// that a presenter is not left wondering.
    func waitReady(timeout: Double = C.cameraOpenTimeout) -> Bool {
        if !error.isEmpty { return false }
        return ready.wait(timeout: .now() + timeout) == .success
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lock.lock()
        latest = buffer
        latestAt = now()
        framesRead += 1
        width = CVPixelBufferGetWidth(buffer)
        height = CVPixelBufferGetHeight(buffer)
        error = ""
        let first = !signalled
        signalled = true
        lock.unlock()
        if first { ready.signal() }
    }

    /// Whether a frame has arrived recently enough to still be the truth.
    func live() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard latest != nil else { return false }
        return (now() - latestAt) < C.cameraStaleSeconds
    }

    /// The most recent frame at the camera's own size, or nothing.
    func latestFrame() -> CVPixelBuffer? {
        lock.lock(); defer { lock.unlock() }
        return latest
    }

    func frame(width: Int, height: Int) -> CVPixelBuffer? {
        lock.lock()
        guard let source = latest else { lock.unlock(); return nil }
        // STALE IS THE SAME AS GONE. See the note at the top of the file.
        if (now() - latestAt) > C.cameraStaleSeconds {
            if error.isEmpty {
                error = "\(device.isEmpty ? "the camera" : device) stopped sending pictures"
            }
            lock.unlock()
            return nil
        }
        let key = "\(width)x\(height)|\(latestAt)"
        if key == scaledKey, let scaled { lock.unlock(); return scaled }
        lock.unlock()

        let made = Pixels.draw(width: width, height: height) { ctx in
            Pixels.fill(ctx, bars, width: width, height: height)
            if let image = CameraSource.image(from: source) {
                Pixels.letterbox(image, into: ctx, width: width, height: height)
            }
        }
        lock.lock(); scaled = made; scaledKey = key; lock.unlock()
        return made
    }

    /// A CGImage over a pixel buffer, without copying the pixels.
    static func image(from buffer: CVPixelBuffer) -> CGImage? {
        var out: CGImage?
        VTCreateCGImageFromCVPixelBuffer(buffer, options: nil, imageOut: &out)
        return out
    }

    func describe() -> String {
        lock.lock(); defer { lock.unlock() }
        if !error.isEmpty { return "a camera that could not be opened" }
        if framesRead == 0 { return "a camera that is still starting" }
        return "\(device) at \(Cameras.describeSize(width, height))"
    }

    private func setError(_ text: String) {
        lock.lock(); error = text; lock.unlock()
        // Anybody waiting on a first frame is waiting for one that is not
        // coming, and should be told now rather than at the timeout.
        if !signalled { signalled = true; ready.signal() }
    }

    /// Give the device back, and do not merely ask nicely.
    ///
    /// Stopping the session is what actually releases a camera and turns its
    /// light off. A flag checked between frames does not, because a camera
    /// that has stopped delivering never reaches the check.
    func close() {
        lock.lock()
        let running = session
        session = nil
        latest = nil
        scaled = nil
        scaledKey = nil
        lock.unlock()
        running?.stopRunning()
    }
}
