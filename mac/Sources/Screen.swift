// The screen as a picture source, and the camera in its corner.
//
// Mirrors dropdeck/screen.py. Windows blits the desktop through GDI; this uses
// ScreenCaptureKit, which is the supported way on macOS 12.3 and later and the
// only one that keeps working under the hardened runtime.
//
// **The screen fills the frame and the camera goes in a corner.** That is not
// a preference. A 1280 wide picture split down the middle leaves the screen
// 640 across, and a 1920x1080 desktop rendered 640 across is not small text,
// it is no text: ordinary writing turns to a grey smear. At the full width the
// same screen reads perfectly. A screen nobody can read is not worth sending.
//
// Per monitor choices are deliberately not offered. Somebody who cannot see
// the screens cannot be asked to pick between "monitor 2" and "monitor 3", so
// the honest choice is between everything and the main one.

import Foundation
import ScreenCaptureKit
import CoreVideo
import CoreGraphics
import CoreMedia

enum Screens {

    /// Set once a capture has come back entirely blank.
    ///
    /// **`CGPreflightScreenCaptureAccess` lies**, and this is the app's memory
    /// of catching it at it. Measured on this Mac with a Developer ID signed
    /// build: preflight answered true, every frame arrived marked complete, at
    /// the right size, at thirty a second, and every pixel was zero. A grant
    /// recorded against an older build's code identity reads as a grant and
    /// captures nothing.
    ///
    /// So what the app SAW outranks what the system said, and everything that
    /// reports on the screen asks this first.
    static private(set) var provedBlank = false

    static func sawBlankCapture() {
        provedBlank = true
        // This is what puts Drop Deck in the Screen and System Audio Recording
        // list. An app that has never asked is not in it, which is why looking
        // for it there and finding nothing is not the user's mistake.
        _ = CGRequestScreenCaptureAccess()
    }

    /// Whether this machine can be captured at all.
    ///
    /// The permission is a system one and the user grants it once, in System
    /// Settings. Asking here rather than assuming is what lets the pre-flight
    /// say so before somebody goes live rather than after.
    static func available() -> Bool {
        if provedBlank { return false }
        return CGPreflightScreenCaptureAccess()
    }

    /// What to say when the screen cannot be captured. One sentence, and it
    /// names the setting rather than the problem, because the problem is not
    /// something the user can do anything with.
    static let notAllowed = "The screen is coming back black. Almost always that is "
                          + "Drop Deck not being allowed to record it: turn it on under "
                          + "Screen and System Audio Recording in System Settings, "
                          + "Privacy and Security, then quit and open Drop Deck again. "
                          + "If it is already on, check whether the VoiceOver screen "
                          + "curtain is up"

    static func whyUnavailable() -> String {
        available() ? "" : notAllowed
    }

    /// Ask for the permission, which shows the system's own dialog once.
    @discardableResult
    static func request() -> Bool { CGRequestScreenCaptureAccess() }

    /// What can be captured, widest first. Two entries at most.
    static func all() -> [(value: String, label: String, width: Int, height: Int)] {
        var out: [(String, String, Int, Int)] = []
        let displays = CGDisplayCount()
        _ = displays
        var bounds = CGRect.null
        var mainSize = (0, 0)
        for id in activeDisplays() {
            let r = CGDisplayBounds(id)
            bounds = bounds.isNull ? r : bounds.union(r)
            if CGDisplayIsMain(id) != 0 {
                mainSize = (Int(r.width), Int(r.height))
            }
        }
        if !bounds.isNull, bounds.width > 0, bounds.height > 0 {
            out.append((C.screenAll, "Everything on my screens",
                        Int(bounds.width), Int(bounds.height)))
        }
        if mainSize.0 > 0, mainSize != (Int(bounds.width), Int(bounds.height)) {
            out.append((C.screenMain, "My main screen only", mainSize.0, mainSize.1))
        }
        return out
    }

    static func activeDisplays() -> [CGDirectDisplayID] {
        var count: UInt32 = 0
        CGGetActiveDisplayList(0, nil, &count)
        var ids = [CGDirectDisplayID](repeating: 0, count: Int(count))
        CGGetActiveDisplayList(count, &ids, &count)
        return Array(ids.prefix(Int(count)))
    }
}

/// The desktop, captured on ScreenCaptureKit's own queue.
final class ScreenSource: NSObject, PictureSource, SCStreamOutput {

    let kind = C.pictureScreen
    let which: String
    private let wantWidth: Int
    private let wantHeight: Int
    private let wantFPS: Int
    private let bars: RGB

    private let lock = NSLock()
    private var stream: SCStream?
    private let queue = DispatchQueue(label: "app.tgstudios.dropdeck.screen")
    private var latest: CVPixelBuffer?
    private var latestAt: Double = 0
    /// When the capture last CONFIRMED the picture is current, which is not
    /// the same question as when a new frame last arrived. See the note on
    /// `didOutputSampleBuffer`.
    private var heartbeatAt: Double = 0
    private(set) var idleFrames = 0
    private var scaled: CVPixelBuffer?
    private var scaledKey: String?
    private(set) var error = ""
    private(set) var framesRead = 0
    private(set) var width = 0
    private(set) var height = 0
    private let ready = DispatchSemaphore(value: 0)
    private var signalled = false
    /// How many of the first frames were entirely blank. See `looksBlank`.
    private var blankRun = 0
    private var checkedBlank = false
    /// Once the capture has been judged not allowed, every later frame is
    /// black too and must not be let back in. Without this the verdict is
    /// reached, the cache is emptied, and the next frame a fortieth of a
    /// second later fills it straight back up with the same black picture.
    private var refused = false

    /// **A screen that is not changing is not a broken screen.**
    ///
    /// The freeze check compares one frame with the last and calls them the
    /// same a fault. That is right for a camera, where identical frames mean
    /// something has stopped, and wrong for a desktop, where identical frames
    /// mean nobody has moved the mouse. Measured on Tony's own setup while he
    /// was on the air: the mean difference between consecutive frames was
    /// 0.000 and every single sample read as frozen, so the app told him his
    /// picture had died every forty five seconds while it was perfectly fine.
    ///
    /// ScreenCaptureKit says the same thing in its own words by sending an
    /// `idle` frame rather than a picture, and the heartbeat in
    /// `didOutputSampleBuffer` is what notices a capture that has really
    /// stopped. Liveness here comes from that, never from the pixels.
    ///
    /// Black is still checked, because a black screen going out IS a fault
    /// whatever is causing it.
    var moving: Bool { false }
    var now: () -> Double = { ProcessInfo.processInfo.systemUptime }

    init(which: String = C.screenAll, width: Int? = nil, height: Int? = nil,
         fps: Int? = nil, bars: RGB = C.cardBackground) {
        self.which = which.isEmpty ? C.screenAll : which
        self.wantWidth = width ?? C.rtmpWidth
        self.wantHeight = height ?? C.rtmpHeight
        self.wantFPS = fps ?? C.rtmpFPS
        self.bars = bars
    }

    func start() {
        lock.lock()
        if stream != nil { lock.unlock(); return }
        lock.unlock()
        // The same fault as the camera, and worse, because there is no
        // "never asked" to read for the screen: an app that has never asked
        // and an app that was refused both answer false. So it ASKS, which is
        // also the only thing that puts Drop Deck in the Screen and System
        // Audio Recording list where it can be switched on.
        if !Screens.available() {
            let waiting = DispatchSemaphore(value: 0)
            var granted = false
            var said = ""
            Permissions.ask(.screen) { state, sentence in
                granted = state == .allowed
                said = sentence
                waiting.signal()
            }
            if waiting.wait(timeout: .now() + 120) == .timedOut || !granted {
                setError(said.isEmpty ? Screens.notAllowed : said)
                return
            }
        }
        Task { await open() }
    }

    private func open() async {
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(
                false, onScreenWindowsOnly: true)
            guard let display = pick(from: content.displays) else {
                setError("there is no screen to capture")
                return
            }
            // The app's own windows are left out. A presenter sharing their
            // screen does not want Drop Deck's own window in the shot, and a
            // capture that includes the window showing the capture is the
            // hall of mirrors everybody discovers once.
            let mine = content.applications.filter {
                $0.bundleIdentifier == Bundle.main.bundleIdentifier
            }
            let filter = SCContentFilter(display: display,
                                         excludingApplications: mine,
                                         exceptingWindows: [])
            let config = SCStreamConfiguration()
            config.width = display.width
            config.height = display.height
            config.pixelFormat = kCVPixelFormatType_32BGRA
            config.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(wantFPS))
            // One frame in hand. The newest is the only one worth having and
            // a queue of stale desktops is latency, exactly as on the camera.
            config.queueDepth = 3
            config.showsCursor = true
            config.scalesToFit = true

            let made = SCStream(filter: filter, configuration: config, delegate: nil)
            try made.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
            try await made.startCapture()
            keep(made)
        } catch {
            setError(explain(error))
        }
    }

    /// Taking a lock directly inside an async function is refused in the
    /// Swift 6 language mode, so the one line that needs it lives here.
    private func keep(_ made: SCStream) {
        lock.lock(); stream = made; lock.unlock()
    }

    private func pick(from displays: [SCDisplay]) -> SCDisplay? {
        if which == C.screenMain {
            if let main = displays.first(where: { CGDisplayIsMain($0.displayID) != 0 }) {
                return main
            }
        }
        // "Everything" is the widest one. ScreenCaptureKit captures one
        // display at a time, so on a multi screen Mac this is the largest
        // rather than the union, and the picker says so.
        return displays.max(by: { $0.width * $0.height < $1.width * $1.height })
    }

    private func explain(_ error: Error) -> String {
        let text = error.localizedDescription.lowercased()
        if text.contains("permission") || text.contains("declined")
            || text.contains("not authorized") {
            return Screens.whyUnavailable()
        }
        return "the screen could not be captured"
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .screen, CMSampleBufferIsValid(sampleBuffer),
              let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lock.lock()
        let alreadyRefused = refused
        lock.unlock()
        if alreadyRefused { return }
        // ScreenCaptureKit is not a camera and this is the difference that
        // matters most.
        //
        // **It does not send a frame when the screen is not changing.**
        // Measured on this Mac: six seconds of a static desktop at 30 fps gave
        // 46 frames marked `complete` and 142 marked `idle`, which is real
        // pictures at under 8 fps. A Windows desktop blit always returns the
        // current screen, which is why `SCREEN_STALE_SECONDS` of 2 is safe
        // there and why copying it here without this would have shipped a bug:
        // a presenter showing a static slide for three seconds would have had
        // the screen declared dead and the station card put out instead, mid
        // show, with nothing whatever wrong.
        //
        // So there are two clocks. An `idle` frame is a HEARTBEAT: it carries
        // no picture and says the last one is still what is on the screen, so
        // it refreshes liveness without replacing anything. Only `blank`,
        // `suspended`, or the callback stopping altogether, count towards the
        // picture being gone.
        var status = SCFrameStatus.complete
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(
                sampleBuffer, createIfNecessary: false) as? [[CFString: Any]],
           let raw = attachments.first?[SCStreamFrameInfo.status.rawValue as CFString] as? Int,
           let read = SCFrameStatus(rawValue: raw) {
            status = read
        }
        switch status {
        case .idle:
            lock.lock(); heartbeatAt = now(); idleFrames += 1; lock.unlock()
            return
        case .complete:
            break
        default:
            // blank, suspended, started, stopped: no picture, and no promise
            // that the old one is still right.
            return
        }

        // **A capture that has not been allowed comes back BLACK, not as an
        // error, and `CGPreflightScreenCaptureAccess` still answers yes.**
        // Measured on this Mac on 8 September 2026, with a Developer ID signed
        // build: every frame arrived marked `complete`, at the right size, at
        // thirty a second, and every pixel was zero.
        //
        // That is the exact shape of failure this whole app exists to catch:
        // it looks perfect from where the presenter is sitting and it is three
        // hours of nothing for everybody watching. So the opening frames are
        // looked at, once, and an all black start is called what it almost
        // always is. A genuinely black desktop for the first few frames is
        // possible and is the price; the card takes over and says why, which
        // is recoverable, where a silent black broadcast is not.
        if !checkedBlank {
            if SelfTestScreenBlank.looksBlank(buffer) {
                blankRun += 1
                if blankRun >= 5 {
                    checkedBlank = true
                    Screens.sawBlankCapture()
                    // The frames already taken were black too, so they must go
                    // with the verdict. Leaving them cached is how the app
                    // would go on serving the very picture it just decided was
                    // not a picture.
                    lock.lock()
                    refused = true
                    latest = nil
                    scaled = nil
                    scaledKey = nil
                    lock.unlock()
                    setError(Screens.notAllowed)
                    return
                }
            } else {
                checkedBlank = true
            }
        }

        lock.lock()
        latest = buffer
        latestAt = now()
        heartbeatAt = latestAt
        framesRead += 1
        width = CVPixelBufferGetWidth(buffer)
        height = CVPixelBufferGetHeight(buffer)
        if !error.isEmpty && error != Screens.notAllowed { error = "" }
        let first = !signalled
        signalled = true
        lock.unlock()
        if first { ready.signal() }
    }

    func waitReady(timeout: Double = C.screenOpenTimeout) -> Bool {
        if !error.isEmpty { return false }
        return ready.wait(timeout: .now() + timeout) == .success
    }

    func live() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard latest != nil else { return false }
        // Against the heartbeat, not the last new picture: a screen nobody is
        // touching is still a screen.
        return (now() - heartbeatAt) < C.screenStaleSeconds
    }

    func latestFrame() -> CVPixelBuffer? {
        lock.lock(); defer { lock.unlock() }
        return latest
    }

    func frame(width: Int, height: Int) -> CVPixelBuffer? {
        lock.lock()
        guard let source = latest else { lock.unlock(); return nil }
        // Past this the last capture is a photograph rather than the screen,
        // and the card takes over. Measured against the heartbeat rather than
        // the last new frame, for the reason in `didOutputSampleBuffer`.
        if (now() - heartbeatAt) > C.screenStaleSeconds {
            if error.isEmpty { error = "the screen stopped being captured" }
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

    func describe() -> String {
        lock.lock(); defer { lock.unlock() }
        if !error.isEmpty { return "a screen that could not be captured" }
        if framesRead == 0 { return "the screen, still starting" }
        for entry in Screens.all() where entry.value == which {
            return "\(entry.label.lowercased()) at \(width) by \(height)"
        }
        return "the screen at \(width) by \(height)"
    }

    private func setError(_ text: String) {
        lock.lock(); error = text; lock.unlock()
        if !signalled { signalled = true; ready.signal() }
    }

    func close() {
        lock.lock()
        let running = stream
        stream = nil
        latest = nil
        scaled = nil
        scaledKey = nil
        lock.unlock()
        guard let running else { return }
        Task { try? await running.stopCapture() }
    }
}

/// The screen filling the frame, with the camera small in a corner.
final class SplitSource: PictureSource {

    let kind = C.pictureSplit
    let screen: ScreenSource
    let camera: CameraSource
    private let edge: RGB
    private let corner: String
    private(set) var showingCamera = false

    /// The composite is mostly desktop: the camera is a quarter of the width
    /// in one corner, which is about a sixteenth of the picture. So even a
    /// lively camera moves too little of the whole frame to clear the
    /// threshold, and a still desktop drags the average to nothing. The
    /// camera is checked on its own instead, in the pump.
    var moving: Bool { false }
    var error: String { screen.error }

    init(screen: ScreenSource, camera: CameraSource,
         edge: RGB = C.cardAccent, corner: String = C.splitCorner) {
        self.screen = screen
        self.camera = camera
        self.edge = edge
        self.corner = C.splitCorners.contains(corner) ? corner : C.splitCorner
    }

    func start() {
        screen.start()
        camera.start()
    }

    /// The screen is what makes this a show. A camera that will not open is
    /// reported and the broadcast carries on without it.
    func waitReady(timeout: Double) -> Bool {
        screen.waitReady(timeout: timeout)
    }

    func frame(width: Int, height: Int) -> CVPixelBuffer? {
        guard let base = screen.frame(width: width, height: height) else { return nil }
        let boxW = max(2, Int((Double(width) * C.splitInsetWidth).rounded()))
        let boxH = max(2, Int((Double(boxW) * Double(height) / Double(max(1, width))).rounded()))
        guard let inset = camera.frame(width: boxW, height: boxH),
              let insetImage = CameraSource.image(from: inset) else {
            showingCamera = false
            return base
        }
        showingCamera = true

        let marginX = Int((Double(width) * C.splitInsetMargin).rounded())
        let marginY = Int((Double(height) * C.splitInsetMargin).rounded())
        // The margin is kept on whichever edges the box is against, so the
        // inset is the same distance from the corner whichever corner it is.
        // Mirroring the arithmetic rather than the picture.
        let left = corner.contains("left") ? marginX : max(0, width - boxW - marginX)
        let top = corner.contains("top") ? marginY : max(0, height - boxH - marginY)

        // The screen source caches the buffer it hands back and would
        // otherwise be given the camera painted into it for ever.
        guard let baseImage = CameraSource.image(from: base) else { return base }
        return Pixels.draw(width: width, height: height) { ctx in
            ctx.draw(baseImage, in: CGRect(x: 0, y: 0, width: width, height: height))
            // The line is there so the inset does not read as part of the
            // screen behind it, which matters when the corner of a window
            // happens to be pale.
            let border = C.splitInsetBorder
            ctx.setFillColor(red: CGFloat(edge.r) / 255, green: CGFloat(edge.g) / 255,
                             blue: CGFloat(edge.b) / 255, alpha: 1)
            ctx.fill(CGRect(x: left - border, y: height - top - boxH - border,
                            width: boxW + border * 2, height: boxH + border * 2))
            ctx.draw(insetImage, in: CGRect(x: left, y: height - top - boxH,
                                            width: boxW, height: boxH))
        }
    }

    /// The camera's own frame, for the framing checker.
    ///
    /// The one part of this source a face detector wants: the raw camera
    /// picture at its own size, NOT the composite, which is mostly screen and
    /// would have the presenter at a quarter of the width in the corner.
    func latestFrame() -> CVPixelBuffer? { camera.latestFrame() }

    func describe() -> String {
        let said = camera.describe()
        if said.isEmpty || !showingCamera || !camera.error.isEmpty {
            return "\(screen.describe()), with no camera"
        }
        return "\(screen.describe()), with \(said) in the corner"
    }

    func close() {
        camera.close()
        screen.close()
    }
}


/// Whether a captured frame has anything in it at all.
///
/// Kept apart from ScreenSource because the self test uses the same reading,
/// and because "is this picture blank" is a question worth having one answer
/// to rather than two that can disagree.
enum SelfTestScreenBlank {
    static func looksBlank(_ buffer: CVPixelBuffer) -> Bool {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer)?
                .assumingMemoryBound(to: UInt8.self) else { return false }
        let w = CVPixelBufferGetWidth(buffer), h = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        // A wide subsample: one pixel in a thousand is plenty to tell a
        // desktop from a black rectangle, and this runs on the capture queue.
        var total = 0, n = 0
        for y in Swift.stride(from: 0, to: h, by: 32) {
            for x in Swift.stride(from: 0, to: w, by: 32) {
                let p = base + y * stride + x * 4
                total += Int(p[0]) + Int(p[1]) + Int(p[2])
                n += 3
            }
        }
        return n > 0 && (Double(total) / Double(n)) < C.healthBlackBelow
    }
}
