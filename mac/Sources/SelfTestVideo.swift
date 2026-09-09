// The checks for the video half, which came to the Mac in 3.5.2.
//
// Two kinds of thing are checked here and they are not the same kind.
//
// **The arithmetic and the words** are also proved against the real Windows
// modules by `mac/tools/cross_check.py`, which is a far stronger test than
// anything in this file: it runs dropdeck/colours.py and Colours.swift over
// the same inputs and diffs them byte for byte. What is here is the subset
// that has to hold in the SHIPPED bundle, because a cross check passing on a
// checkout says nothing about a build with a missing font.
//
// **The drawing** is only checked here, because there is nothing on the other
// side to compare it against: Windows draws with Pillow and this draws with
// Core Text, and the two do not produce the same pixels. So these assert the
// PROMISE rather than the pixels: that a tile has words on it, that the words
// stay inside their box, and that `fits` agrees with what is really drawn.
//
// That last one earned its place. The first version of `renderTile` used
// `.strokeClip`, which does not draw an outline, it intersects the clip with
// one, so the fill that followed was clipped away to nothing. Every arithmetic
// check passed and every tile came out as a panel with no words on it. Only
// counting the ink pixels found it.

import Foundation
import AppKit
import CoreGraphics
import CoreVideo

extension SelfTest {

    func runVideoChecks() {
        testColourArithmetic()
        testOverlayGeometry()
        testOverlayDrawing()
        testPreflight()
        testKeychain()
        testPictureSources()
        testVideoKeys()
        testEditMenu()
        testPermissions()
        testChunkReader()
        testFreezeSubjects()
        testSavedSetups()
    }

    // -------------------------------------------------------------- colours ---

    private func testColourArithmetic() {
        out.append("")
        out.append("Colours, which are chosen by number rather than by eye")

        check("black and white is the whole range",
              near(Colours.contrast(RGB(0, 0, 0), RGB(255, 255, 255)), 21.0, 0.001))
        check("a colour against itself is one to one",
              near(Colours.contrast(RGB(120, 30, 90), RGB(120, 30, 90)), 1.0, 0.001))

        // The measurement the whole module exists for: red on blue reads as
        // unreadable AND is what the encoder destroys, because both come from
        // there being no brightness difference.
        let redOnBlue = Colours.contrast(RGB(200, 40, 40), RGB(24, 96, 200))
        check("red on blue scores as unreadable", redOnBlue < Colours.contrastFloor,
              Colours.oneDecimal(redOnBlue))

        var bad: [String] = []
        for scheme in Colours.schemes {
            let text = Colours.contrast(Colours.rgb(scheme.text),
                                        Colours.rgb(scheme.background))
            let accent = Colours.contrast(Colours.rgb(scheme.accent),
                                          Colours.rgb(scheme.background))
            if text < Colours.contrastGood || accent < Colours.contrastGood {
                bad.append("\(scheme.name) \(Colours.oneDecimal(min(text, accent)))")
            }
        }
        check("every ready made look clears the target on both pairs",
              bad.isEmpty, bad.joined(separator: ", "))

        check("a coloured rule is an even number of pixels high",
              C.placesOrder.count == 4 && Colours.even(3) == 2 && Colours.even(1) == 2
              && Colours.even(4) == 4)
        check("a name that is not ours falls back rather than drawing nothing",
              Colours.rgb("puce") == Colours.fallbackRGB)
    }

    // ------------------------------------------------------------- overlay ---

    private func testOverlayGeometry() {
        out.append("")
        out.append("The four places on top of the picture")

        check("the bundled font is in the build", Overlays.available(),
              Overlays.whyUnavailable())
        check("there are four places and no more", Overlays.places.count == 4)

        // The reason there are places rather than coordinates: they cannot
        // land on top of each other, so "what is on screen" is four lines.
        var overlaps: [String] = []
        for (w, h) in [(1280, 720), (1920, 1080), (854, 480), (640, 360)] {
            let boxes = Overlays.places.map { ($0.key, $0.rect(w, h)) }
            for i in 0..<boxes.count {
                for j in (i + 1)..<boxes.count {
                    let a = boxes[i].1, b = boxes[j].1
                    let apart = a.right <= b.left || b.right <= a.left
                              || a.bottom <= b.top || b.bottom <= a.top
                    if !apart {
                        overlaps.append("\(boxes[i].0) and \(boxes[j].0) at \(w) by \(h)")
                    }
                }
            }
        }
        check("no two places can overlap, at any size that ships",
              overlaps.isEmpty, overlaps.joined(separator: ", "))

        for (w, h) in [(1280, 720), (1920, 1080), (640, 360)] {
            var outside: [String] = []
            for spot in Overlays.places {
                let r = spot.rect(w, h)
                if r.left < 0 || r.top < 0 || r.right > w || r.bottom > h {
                    outside.append(spot.key)
                }
            }
            check("every place is inside a \(w) by \(h) frame", outside.isEmpty,
                  outside.joined(separator: ", "))
        }

        let empty = Overlay()
        check("nothing set says so rather than saying nothing",
              empty.describe() == "nothing on top of it", empty.describe())
    }

    private func testOverlayDrawing() {
        out.append("")
        out.append("Drawing on the picture, counted rather than assumed")

        guard let spot = Overlays.byKey[C.placeLower] else {
            check("the lower third exists", false)
            return
        }
        let box = spot.rect(C.rtmpWidth, C.rtmpHeight)
        let w = box.right - box.left, h = box.bottom - box.top
        let size = spot.textSize(C.rtmpHeight)
        let pad = Overlays.padding(h)

        guard let tile = Overlays.renderTile("Fleetwood Mac - Dreams",
                                             width: w, height: h, size: size) else {
            check("a tile is drawn at all", false)
            return
        }
        check("a tile is the size of its place",
              tile.width == w && tile.height == h, "\(tile.width) by \(tile.height)")

        // Count the pixels. An empty panel and a panel with words on it are
        // the same shape, the same size and the same arithmetic.
        var buf = [UInt8](repeating: 0, count: w * h * 4)
        buf.withUnsafeMutableBytes { raw in
            guard let ctx = CGContext(data: raw.baseAddress, width: w, height: h,
                                      bitsPerComponent: 8, bytesPerRow: w * 4,
                                      space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
            else { return }
            ctx.draw(tile, in: CGRect(x: 0, y: 0, width: w, height: h))
        }
        var ink = 0, clear = 0, minX = w, maxX = 0
        for y in 0..<h {
            for x in 0..<w {
                let i = (y * w + x) * 4
                if buf[i + 3] == 0 { clear += 1; continue }
                if buf[i] > 200 && buf[i + 1] > 200 && buf[i + 2] > 200 {
                    ink += 1
                    minX = min(minX, x); maxX = max(maxX, x)
                }
            }
        }
        check("the tile has words on it and not just a panel", ink > 500, "\(ink) ink pixels")
        check("the corners are rounded", clear > 0, "\(clear) transparent pixels")
        check("the words start at the padding", ink > 0 && minX >= pad - 3, "x \(minX)")
        check("and finish inside the tile", ink > 0 && maxX < w, "x \(maxX)")

        // What `fits` is FOR. It may not agree with the Windows number, since
        // the two renderers do not draw the same width, but it must agree with
        // what THIS machine draws, which is the only thing it claims.
        var wrong: [String] = []
        for text in ["Short", "Fleetwood Mac - Dreams",
                     "A really very long track title that will certainly not fit here at all",
                     String(repeating: "i", count: 40),
                     String(repeating: "W", count: 30)] {
            let said = Overlays.fits(text, key: C.placeLower,
                                     width: C.rtmpWidth, height: C.rtmpHeight)
            let cut = Overlays.fit(text, size: size,
                                   room: Double(w - pad * 2)) != text
            if said == cut { wrong.append(String(text.prefix(20))) }
        }
        check("fits agrees with what is really drawn", wrong.isEmpty,
              wrong.joined(separator: ", "))
    }

    // ------------------------------------------------------ picture sources ---

    private func testPictureSources() {
        out.append("")
        out.append("The picture, drawn and captured for real")

        // The card, which is the default and the one that cannot fail.
        let card = CardSource(name: "Blindside Radio", title: "Fleetwood Mac - Dreams",
                              background: Colours.rgb("near black"),
                              foreground: Colours.rgb("off white"),
                              accent: Colours.rgb("light blue"))
        guard let frame = card.frame(width: C.rtmpWidth, height: C.rtmpHeight) else {
            check("a card is drawn", false)
            return
        }
        check("a card is drawn", true)
        check("at the size asked for",
              CVPixelBufferGetWidth(frame) == C.rtmpWidth
              && CVPixelBufferGetHeight(frame) == C.rtmpHeight)
        check("in the format the encoder takes without a copy",
              CVPixelBufferGetPixelFormatType(frame) == kCVPixelFormatType_32BGRA)

        let look = SelfTest.inspect(frame)
        check("the card is not a black rectangle", look.mean > 8, "mean \(look.mean)")
        check("and has words on it, not just a background",
              look.distinct > 8, "\(look.distinct) distinct colours")

        // A card is the same picture thirty times a second and must not be
        // drawn thirty times a second.
        let before = card.redraws
        _ = card.frame(width: C.rtmpWidth, height: C.rtmpHeight)
        _ = card.frame(width: C.rtmpWidth, height: C.rtmpHeight)
        check("an unchanged card is not redrawn", card.redraws == before)
        card.setTitle("Something else")
        _ = card.frame(width: C.rtmpWidth, height: C.rtmpHeight)
        check("and a changed one is", card.redraws == before + 1)

        // A picture file that is not there must fall back rather than send a
        // dark rectangle for three hours.
        let missing = ImageSource(path: "/tmp/dropdeck-no-such-picture.png")
        check("a missing picture file says so",
              missing.frame(width: 320, height: 180) != nil
              && !missing.error.isEmpty, missing.error)
        check("and describes itself honestly",
              missing.describe() == "a picture that could not be read")

        // The fallback, which is what makes a camera safe on a live show.
        var told: [String] = []
        let broken = ImageSource(path: "")
        let fallback = FallbackSource(primary: NeverAnswers(), backup: card,
                                      onFallback: { told.append($0) })
        _ = broken
        check("a source that cannot answer falls back to the card",
              fallback.frame(width: 320, height: 180) != nil && fallback.fallenBack)
        check("and says so once, not once a frame", {
            for _ in 0..<5 { _ = fallback.frame(width: 320, height: 180) }
            return told.count == 1
        }(), "said \(told.count) times")
        check("and describes what happened",
              fallback.describe().hasSuffix(", showing a card instead"),
              fallback.describe())

        // The screen. Whether it can be captured is the user's decision, made
        // once in System Settings, so not being allowed yet is a note rather
        // than a failure. What must never happen is a capture that SAYS it
        // worked and sends black, which is the fault health.py exists for.
        if !Screens.available() {
            out.append("  note  the screen has not been allowed yet: "
                       + Screens.whyUnavailable())
        } else {
            let screen = ScreenSource(which: C.screenAll, width: C.rtmpWidth,
                                      height: C.rtmpHeight, fps: C.rtmpFPS)
            screen.start()
            // Not asserted on: waitReady answers as soon as ANY frame lands,
            // and a blank one is a frame. The verdict below is the real answer.
            _ = screen.waitReady(timeout: C.screenOpenTimeout)
            // Long enough to have looked at its opening frames, and that is
            // NOT the frame rate: ScreenCaptureKit sends nothing at all while
            // the screen is not changing, so five real frames off a still
            // desktop can take several seconds. Waited for rather than slept
            // through, so it costs nothing when the answer comes quickly.
            let until = Date().addingTimeInterval(8)
            while Date() < until && !Screens.provedBlank && screen.error.isEmpty {
                Thread.sleep(forTimeInterval: 0.05)
            }
            let shot = screen.frame(width: C.rtmpWidth, height: C.rtmpHeight)

            if Screens.provedBlank || screen.error == Screens.notAllowed {
                // Not a fault in the build. The user has not said yes to THIS
                // build yet, and what matters is that the app worked it out
                // from the pixels rather than from the system call, which
                // answered that everything was fine.
                out.append("  note  the screen is not allowed to this build, and the "
                           + "app worked that out from the pixels rather than from "
                           + "the system call, which said it was fine")
                check("a screen that is not allowed refuses rather than sending black",
                      shot == nil)
            } else if let shot {
                let seen = SelfTest.inspect(shot)
                if seen.mean > 8 && seen.distinct > 20 {
                    check("the screen delivers a real picture", true)
                } else {
                    // Blank, but the five frame verdict has not landed yet.
                    // Asserting either way here is asserting on a race.
                    out.append("  note  the screen is coming back blank and the app has "
                               + "not seen enough frames to say so yet. Nothing is "
                               + "asserted on that race")
                }
            } else {
                out.append("  note  the screen delivered nothing in time: "
                           + (screen.error.isEmpty ? "no reason given" : screen.error))
            }
            screen.close()
        }

        // **The overlay must not compound.** Every source caches the frame it
        // hands back, so drawing the overlay onto that buffer draws it onto
        // the same pixels again next frame, and again: a clock smears and a
        // lower third turns to mud within a second. Nothing else here would
        // catch it, because every frame is the right size, the right format
        // and not black.
        var overlaySettings = OverlaySettings()
        overlaySettings.places = ["lower": ["kind": C.textWords,
                                            "words": "Compounding check",
                                            "file": ""]]
        let overlay = Overlay(settings: overlaySettings)
        let steady = CardSource(name: "Steady", title: "Nothing changes")
        var readings: [Int] = []
        for _ in 0..<6 {
            guard let raw = steady.frame(width: C.rtmpWidth, height: C.rtmpHeight) else {
                break
            }
            let shown = Pixels.composite(raw, overlay, width: C.rtmpWidth,
                                         height: C.rtmpHeight)
            readings.append(SelfTest.inspect(shown).mean)
        }
        check("the overlay is drawn once a frame, not once more each frame",
              readings.count == 6 && Set(readings).count == 1,
              readings.map(String.init).joined(separator: ", "))
        // And the source's own buffer is untouched by it.
        if let raw = steady.frame(width: C.rtmpWidth, height: C.rtmpHeight) {
            let bare = SelfTest.inspect(raw).mean
            let withText = SelfTest.inspect(Pixels.composite(
                raw, overlay, width: C.rtmpWidth, height: C.rtmpHeight)).mean
            check("the source keeps its own picture clean",
                  SelfTest.inspect(raw).mean == bare && withText != bare,
                  "bare \(bare), with the overlay \(withText)")
        }

        // Cameras are listed without opening one. Opening asks the user for
        // permission, which is a system dialog and belongs to their first real
        // use rather than to a test run.
        out.append("  note  cameras seen: "
                   + (Cameras.all().isEmpty ? "none" : Cameras.all().joined(separator: ", ")))
    }

    // --------------------------------------------------------- the Edit menu ---

    private func testEditMenu() {
        out.append("")
        out.append("The Edit menu, which is what makes Command V paste")

        // **The app shipped without one from 3.0.0 to 3.5.2**, and nobody
        // noticed until a stream key had to go into a box. On macOS the Edit
        // menu is not decoration: it is what SUPPLIES Command C, V, X, A and
        // Z. A text field implements `paste:` and waits to be sent it, and the
        // only thing that sends it is a menu item with that key equivalent.
        // With no Edit menu there was nothing to send it, so nothing in the
        // whole app could be pasted into.
        // Built here rather than read off the live menu bar, because the
        // checks run headless and there is no menu bar yet. It is the same
        // function the menu bar is built from, so there is nothing to drift.
        let edit = AppDelegate.makeEditMenu()
        check("there is an Edit menu with something in it", edit.items.count >= 6,
              "\(edit.items.count) items")

        var missing: [String] = []
        for (title, key, selector) in [
            ("Cut", "x", #selector(NSText.cut(_:))),
            ("Copy", "c", #selector(NSText.copy(_:))),
            ("Paste", "v", #selector(NSText.paste(_:))),
            ("Select All", "a", #selector(NSText.selectAll(_:))),
        ] {
            guard let entry = edit.items.first(where: { $0.title == title }) else {
                missing.append("\(title) is not there"); continue
            }
            if entry.keyEquivalent != key {
                missing.append("\(title) is on \(entry.keyEquivalent) not \(key)")
            }
            if entry.action != selector {
                missing.append("\(title) does not send the standard selector")
            }
            // Targeting nil is what "go to whatever has focus" means. A target
            // here would send every paste to one object and text fields would
            // never see it, which is the bug in a different shape.
            if entry.target != nil { missing.append("\(title) has a fixed target") }
        }
        check("Cut, Copy, Paste and Select All are there, on their own keys, "
              + "going to whatever has focus", missing.isEmpty,
              missing.joined(separator: "; "))

        // 3.5.21 is NEWER than 3.5.2, and that is worth a check rather than a
        // shrug: as strings it is not, and an update that sorts backwards is
        // an update that never offers itself again.
        check("3.5.21 is newer than 3.5.2",
              AppUpdate.isNewer("3.5.21", than: "3.5.2"))
        check("and 3.5.2 is not newer than 3.5.21",
              !AppUpdate.isNewer("3.5.2", than: "3.5.21"))
        check("and 3.5.3 is not newer than 3.5.21",
              !AppUpdate.isNewer("3.5.3", than: "3.5.21"))
        check("this build's own version sorts above the one before it",
              AppUpdate.isNewer(C.appVersion, than: "3.5.2"), C.appVersion)

        // A model belonging to another provider is dropped rather than kept.
        var mixed = Board.from(dict: ["vision_provider": "google",
                                      "vision_model": "claude-sonnet-5"],
                               relativeTo: nil)
        check("a model from the wrong provider is dropped",
              mixed.visionProvider == "google" && mixed.visionModel.isEmpty,
              "\(mixed.visionProvider) / \(mixed.visionModel)")
        mixed = Board.from(dict: ["vision_provider": "google",
                                  "vision_model": "gemini-flash-latest"],
                           relativeTo: nil)
        check("and one that belongs to it is kept",
              mixed.visionModel == "gemini-flash-latest", mixed.visionModel)
        mixed = Board.from(dict: ["vision_provider": "google",
                                  "vision_model": "some-new-model-2027"],
                           relativeTo: nil)
        check("and a name this build has never heard of is left alone, "
              + "because model names change faster than this app ships",
              mixed.visionModel == "some-new-model-2027", mixed.visionModel)

        // And nothing else may claim Command V, or the menu bar picks a winner
        // without saying so and text fields lose again.
        var clashes: [String] = []
        for command in Command.allCases {
            for binding in KeyMap.bindings[command] ?? []
            where binding.key == "v" && binding.mods == [.command] {
                clashes.append(command.rawValue)
            }
        }
        check("nothing else claims Command V", clashes.isEmpty,
              clashes.joined(separator: ", "))
    }

    // ------------------------------------------------------- permissions ---

    private func testPermissions() {
        out.append("")
        out.append("What macOS lets this app do")

        // **The app has to ASK, not just look.** Until 3.5.22 it only ever
        // read the status, which prompts nobody and registers nothing, so it
        // never appeared in System Settings under Camera at all and there was
        // nothing there to switch on. Reported by Tony, who went looking.
        check("there are three permissions and they are all named",
              Permission.allCases.count == 3
              && Permission.allCases.allSatisfy { !$0.label.isEmpty })

        var bad: [String] = []
        for which in Permission.allCases {
            if which.whatFor.isEmpty { bad.append("\(which.label) says what it is for") }
            if which.settingsName.isEmpty { bad.append("\(which.label) names its pane") }
            if which.settingsURL == nil { bad.append("\(which.label) can open Settings") }
        }
        check("each one says what it is for, where it lives, and can open it",
              bad.isEmpty, bad.joined(separator: ", "))

        // Every state has a sentence. "not asked for yet" is the one that
        // matters: it is the state the whole fault lived in, and an app in it
        // is invisible to System Settings.
        for state in [PermissionState.neverAsked, .allowed, .refused, .notYours] {
            check("the state \(state.rawValue) has words", !state.said.isEmpty, state.said)
        }
        check("the never asked wording says so plainly",
              PermissionState.neverAsked.said == "not asked for yet")

        // And the whole thing answers, whatever this Mac has granted.
        let said = Permissions.describe()
        check("it can say what it is allowed to do", said.contains("Microphone")
              && said.contains("Camera") && said.contains("Screen recording"), said)
        out.append("  note  on this Mac right now: " + said)
    }

    // ---------------------------------------------------- the chunk layer ---

    private func testChunkReader() {
        out.append("")
        out.append("Putting a chunked RTMP message back together")

        // **This is the fault that stopped 3.5.22 going live at all.** RTMP
        // cuts a message into pieces and puts a header byte in front of every
        // piece after the first, and until the server says otherwise those
        // pieces are 128 bytes. So YouTube's answer to connect arrives as
        // "NetConnection.Conne", a header byte, then "ct.Success". The client
        // looked for the name in the raw bytes, which works when a reply fits
        // in one chunk, as the mock server's do, and never worked on YouTube.
        /// Shaped like YouTube's real answer, which is what makes it long
        /// enough to be cut in two. Read off the wire on 8 September 2026:
        /// _result, then the properties object with fmsVer and capabilities
        /// and mode, then the information object with level, code,
        /// description, objectEncoding and data.
        func amfResult(_ code: String) -> Data {
            var body = AMF0.encode(.string("_result"))
            body.append(AMF0.encode(.number(1)))
            body.append(AMF0.encode(.object([
                ("fmsVer", .string("FMS/3,5,3,824")),
                ("capabilities", .number(127)),
                ("mode", .number(1)),
            ])))
            body.append(AMF0.encode(.object([
                ("level", .string("status")),
                ("code", .string(code)),
                ("description", .string("Connection succeeded.")),
                ("objectEncoding", .number(0)),
                ("data", .ecmaArray([("version", .string("3,5,3,824"))])),
            ])))
            return body
        }
        /// One message, cut the way a server cuts it.
        func chunked(_ payload: Data, size: Int, csid: UInt8 = 3,
                     type: UInt8 = 20) -> Data {
            var out = Data()
            out.append(UInt8(csid & 0x3f))                       // fmt 0
            out.append(contentsOf: [0, 0, 0])                    // timestamp
            out.append(UInt8((payload.count >> 16) & 0xff))
            out.append(UInt8((payload.count >> 8) & 0xff))
            out.append(UInt8(payload.count & 0xff))
            out.append(type)
            out.append(contentsOf: [0, 0, 0, 0])                 // stream id
            var at = payload.startIndex
            var first = true
            while at < payload.endIndex {
                if !first { out.append(UInt8(0xc0 | (csid & 0x3f))) }
                let take = min(size, payload.distance(from: at, to: payload.endIndex))
                let end = payload.index(at, offsetBy: take)
                out.append(payload[at..<end])
                at = end
                first = false
            }
            return out
        }

        let body = amfResult("NetConnection.Connect.Success")
        check("the reply is longer than one 128 byte chunk, as YouTube's is",
              body.count > 128, "\(body.count) bytes")

        // The old way, for the record: this is what shipped and it finds
        // nothing.
        let wire = chunked(body, size: 128)
        let needle = Array("NetConnection.Connect.Success".utf8)
        let bytes = Array(wire)
        var contiguous = false
        if bytes.count >= needle.count {
            for i in 0...(bytes.count - needle.count)
            where Array(bytes[i..<(i + needle.count)]) == needle { contiguous = true; break }
        }
        check("and the name is NOT contiguous on the wire, which is why "
              + "searching the bytes could never work", !contiguous)

        var reader = RTMPChunkReader()
        var buffer = wire
        var messages = reader.read(from: &buffer)
        check("the reassembler gets one whole message out of it",
              messages.count == 1, "\(messages.count)")
        if let first = messages.first {
            let values = AMF0.read(first.payload)
            check("and it reads as _result", AMF0.firstString(in: values) == "_result",
                  AMF0.firstString(in: values) ?? "nothing")
            check("carrying the code the client waits for",
                  AMF0.code(in: values) == "NetConnection.Connect.Success",
                  AMF0.code(in: values) ?? "nothing")
        }

        // Arriving a byte at a time must give the same answer: a socket does
        // not promise to deliver a message in one piece either.
        reader = RTMPChunkReader()
        var dribble = Data()
        var got: [RTMPMessage] = []
        for byte in wire {
            dribble.append(byte)
            got += reader.read(from: &dribble)
        }
        check("and the same when it arrives one byte at a time",
              got.count == 1 && AMF0.code(in: AMF0.read(got[0].payload))
                                == "NetConnection.Connect.Success")

        // Set Chunk Size changes how everything after it is cut.
        reader = RTMPChunkReader()
        var withSize = Data([0x02, 0, 0, 0, 0, 0, 4, 1, 0, 0, 0, 0])
        withSize.append(contentsOf: [0x00, 0x00, 0x10, 0x00])     // 4096
        withSize.append(chunked(body, size: 4096))
        messages = reader.read(from: &withSize)
        check("Set Chunk Size is obeyed, so what follows is cut differently",
              reader.chunkSize == 4096, "\(reader.chunkSize)")
        check("and the message after it still comes out whole",
              messages.contains { AMF0.code(in: AMF0.read($0.payload))
                                  == "NetConnection.Connect.Success" })

        // And the thing the deadlock came from: publish is not answered by
        // every platform, so nothing may wait for a yes.
        check("there is a grace for a refusal rather than a wait for permission",
              C.rtmpPublishGrace > 0 && C.rtmpPublishGrace <= 5,
              "\(C.rtmpPublishGrace) seconds")
    }

    // ------------------------------- what the freeze check is asked about ---

    private func testFreezeSubjects() {
        out.append("")
        out.append("Which sources may be called frozen")

        // **Reported by Tony while he was on the air**: "stuck on one frame,
        // camera is frozen" every forty five seconds, with nothing wrong. His
        // picture was the screen with the camera in the corner, and a desktop
        // nobody is touching produces identical frames. Measured on his own
        // setup: the mean difference between consecutive composite frames was
        // 0.000, so every sample read as frozen.
        //
        // A screen that is not changing is not a broken screen. Liveness for
        // a capture comes from its heartbeat, never from its pixels.
        let screen = ScreenSource(which: C.screenAll)
        check("a screen is never called frozen by its pixels", !screen.moving)
        let split = SplitSource(screen: ScreenSource(which: C.screenAll),
                                camera: CameraSource(device: ""))
        check("nor is a screen with the camera in the corner", !split.moving)
        check("but a camera is, because identical frames there mean something "
              + "has stopped", CameraSource(device: "").moving)
        check("and a card is not, because it is supposed to be still",
              !CardSource().moving)
        check("nor a picture file", !ImageSource(path: "/tmp/x.png").moving)

        // The arithmetic that produced the false alarm, run directly: two
        // identical frames read as frozen, and that is CORRECT of the
        // watcher. What was wrong was asking it about a desktop.
        let still = HealthWatcher()
        let frame = [UInt8](repeating: 120, count: 64 * 36 * 4)
        var said = ""
        for i in 0..<40 {
            said = still.look(frame: frame, width: 64, height: 36,
                              bytesPerPixel: 4, counted: 3, rowBytes: 64 * 4,
                              moving: true, now: Double(i))
            if !said.isEmpty { break }
        }
        check("an unchanging picture IS called frozen when it is supposed to move",
              said == C.healthFrozenSaid, said)

        let allowed = HealthWatcher()
        var quiet = true
        for i in 0..<40 where !allowed.look(frame: frame, width: 64, height: 36,
                                            bytesPerPixel: 4, counted: 3,
                                            rowBytes: 64 * 4, moving: false,
                                            now: Double(i)).isEmpty {
            quiet = false
        }
        check("and is not, when it is not supposed to move", quiet)

        // Black is still a fault whatever the source, because a black picture
        // going out is a black picture going out.
        let dark = HealthWatcher()
        let black = [UInt8](repeating: 0, count: 64 * 36 * 4)
        var blackSaid = ""
        for i in 0..<40 {
            blackSaid = dark.look(frame: black, width: 64, height: 36,
                                  bytesPerPixel: 4, counted: 3, rowBytes: 64 * 4,
                                  moving: false, now: Double(i))
            if !blackSaid.isEmpty { break }
        }
        check("a black picture is still reported even from a still source",
              blackSaid == C.healthBlackSaid, blackSaid)
    }

    // ------------------------------------------------------- saved setups ---

    private func testSavedSetups() {
        out.append("")
        out.append("A saved setup carries the video half")

        // **This was destructive before 3.5.2.** cleanStations filters an
        // incoming station down to stationFields, so a board written on
        // Windows whose station carried a YouTube channel, opened here and
        // saved, lost it for good. The two copies share one file.
        var missing: [String] = []
        for key in ["video_server", "video_host", "video_key", "live_to",
                    "picture", "picture_file", "picture_clock", "camera",
                    "screen", "split_corner", "text_places",
                    "colour_background", "colour_text", "colour_accent",
                    "video_width", "video_height", "video_fps", "video_bitrate"]
        where !Board.stationFields.contains(key) {
            missing.append(key)
        }
        check("every video key is part of a saved setup", missing.isEmpty,
              missing.joined(separator: ", "))

        let board = Board()
        board.stream.name = "A Station"
        board.videoServer = "facebook"
        board.videoHost = "rtmps://live-api-s.facebook.com:443/rtmp"
        board.liveTo = C.liveToVideo
        board.picture = C.pictureCamera
        board.camera = "Some camera"
        board.splitCorner = "top left"
        board.colourAccent = "gold"
        board.videoWidth = 1920
        board.videoHeight = 1080
        board.saveStation("A Station")

        // Move everything, then load it back.
        board.videoServer = "youtube"
        board.liveTo = C.liveToAudio
        board.picture = C.pictureCard
        board.camera = ""
        board.splitCorner = "bottom right"
        board.colourAccent = "light blue"
        board.videoWidth = 1280
        board.videoHeight = 720
        check("a saved setup loads", board.loadStation("A Station"))
        check("and brings the platform with it", board.videoServer == "facebook",
              board.videoServer)
        check("and where the show goes", board.liveTo == C.liveToVideo, board.liveTo)
        check("and the picture", board.picture == C.pictureCamera, board.picture)
        check("and the camera", board.camera == "Some camera", board.camera)
        check("and the corner", board.splitCorner == "top left", board.splitCorner)
        check("and the accent", board.colourAccent == "gold", board.colourAccent)
        check("and the size", board.videoWidth == 1920 && board.videoHeight == 1080,
              "\(board.videoWidth) by \(board.videoHeight)")

        // A station written by a build that had no video half must not blank
        // the board's own settings when it is loaded.
        board.streamStations.append(["stream_name": "Older",
                                     "stream_host": "old.example.com"])
        _ = board.loadStation("Older")
        check("an older setup keeps the destination rather than blanking it",
              board.liveTo == C.liveToVideo && board.videoServer == "facebook",
              "\(board.liveTo), \(board.videoServer)")
    }

    // ------------------------------------------------------------ the keys ---

    private func testVideoKeys() {
        out.append("")
        out.append("The keys the video half added")

        // Every one of them must have a binding. A command with none is a menu
        // item and nothing else, which is how Ctrl+Shift+F was unreachable on
        // Windows for a whole release.
        let wanted: [Command] = [.videoSource, .screenText, .shotCheck, .colours,
                                 .cameraCheck, .sayScreen]
        var missing: [String] = []
        for command in wanted where (KeyMap.bindings[command] ?? []).isEmpty {
            missing.append(command.rawValue)
        }
        check("every new command has a key", missing.isEmpty,
              missing.joined(separator: ", "))

        // The Option Shift family, which is what Windows' Alt Shift becomes.
        let family: [(Command, String)] = [
            (.sources, "s"), (.videoSource, "v"), (.screenText, "t"),
            (.shotCheck, "d"), (.colours, "c"),
        ]
        var wrong: [String] = []
        for (command, key) in family {
            guard let binding = KeyMap.bindings[command]?.first else {
                wrong.append(command.rawValue); continue
            }
            if binding.key != key || binding.mods != [.option, .shift] {
                wrong.append("\(command.rawValue) is \(KeyMap.spell(key: binding.key, mods: binding.mods))")
            }
        }
        check("the Option Shift family is intact", wrong.isEmpty,
              wrong.joined(separator: ", "))

        // The two that were Ctrl Shift on Windows.
        for (command, key) in [(Command.cameraCheck, "f"), (Command.sayScreen, "v")] {
            let binding = KeyMap.bindings[command]?.first
            check("\(command.rawValue) is Command Shift \(key.uppercased())",
                  binding?.key == key && binding?.mods == [.command, .shift],
                  binding.map { KeyMap.spell(key: $0.key, mods: $0.mods) } ?? "none")
        }

        // The digit map is frozen and nothing here may sit on it.
        var onDigits: [String] = []
        for command in Command.allCases {
            for binding in KeyMap.bindings[command] ?? [] where C.digits.contains(binding.key) {
                onDigits.append(command.rawValue)
            }
        }
        check("nothing new sits on the frozen digit map", onDigits.isEmpty,
              onDigits.joined(separator: ", "))
    }

    // ----------------------------------------------------------- pre-flight ---

    private func testPreflight() {
        out.append("")
        out.append("What Command B is about to do")

        var settings = PreflightSettings()
        var board = PreflightBoard()

        // Nowhere to go is a stop, not a warning.
        let nowhere = Preflighter.check(settings: settings, board: board)
        check("no server at all stops the broadcast", nowhere.blocked)
        check("and says which kind is missing",
              nowhere.stops.first?.text == "There is no server set up yet",
              nowhere.stops.first?.text ?? "")

        // The expensive one: the microphone off the air sounds perfect from
        // where the presenter is sitting.
        settings.host = "radio.example.com"
        settings.mount = "/live"
        settings.password = "secret"
        settings.bitrate = 128
        board.streamMic = false
        let noMic = Preflighter.check(settings: settings, board: board)
        check("a microphone off the air is warned about", !noMic.blocked
              && noMic.warnings.contains { $0.text.contains("not on the air") })
        check("and the summary line says NOT going out",
              noMic.lines.contains { $0.label == "Microphone" && $0.value == "NOT going out" })

        // YouTube publishes the moment you connect, and that is said BEFORE.
        board = PreflightBoard()
        board.liveTo = C.liveToVideo
        board.videoServer = "youtube"
        settings.server = "youtube"
        settings.host = C.rtmpIngest["youtube"] ?? ""
        let live = Preflighter.check(settings: settings, board: board)
        check("YouTube's own behaviour is said before connecting",
              live.warnings.contains { $0.text.contains("puts you live the moment you connect") })
        check("Facebook's opposite behaviour is said too", {
            var b = board; b.videoServer = "facebook"
            return Preflighter.goingLiveWarning(b).contains("post nothing until you press")
        }())

        // A stream key is a stop on video and a password is only a warning on
        // audio, because a private Icecast can legitimately want none.
        var noKey = settings
        noKey.password = ""
        check("no stream key stops a video broadcast",
              Preflighter.check(settings: noKey, board: board).blocked)
        var audio = PreflightBoard()
        audio.liveTo = C.liveToAudio
        check("no password only warns on a radio server",
              !Preflighter.check(settings: noKey, board: audio).blocked)

        // The spoken line is read straight through by a screen reader, so its
        // punctuation is load bearing.
        check("the spoken summary separates settings with semicolons",
              live.spoken().contains("; "))
        check("and the problems with full stops",
              live.warnings.isEmpty || live.spoken().contains(". "))
    }

    // ------------------------------------------------------------ keychain ---

    private func testKeychain() {
        out.append("")
        out.append("Where a stream key is kept, which is not the board file")

        check("the keychain answers on this machine", Secrets.available())

        let station = "TG Drop Deck self test station"
        Secrets.forget(station: station)
        check("nothing is there to begin with",
              Secrets.fetch(station: station).isEmpty)
        check("a key can be kept", Secrets.store(station: station, key: "abcd-1234-wxyz"))
        check("and read back", Secrets.fetch(station: station) == "abcd-1234-wxyz")
        check("keeping it again replaces rather than duplicates",
              Secrets.store(station: station, key: "second-value")
              && Secrets.fetch(station: station) == "second-value")

        // A vision key is not a stream key and must not be filed as one.
        check("a vision key is a different entry",
              Secrets.target(for: station) != Secrets.target(for: station,
                                                             prefix: Secrets.visionPrefix))
        Secrets.store(station: station, key: "vision-key", prefix: Secrets.visionPrefix)
        check("and does not collide with the stream key",
              Secrets.fetch(station: station) == "second-value"
              && Secrets.fetch(station: station, prefix: Secrets.visionPrefix) == "vision-key")
        check("forgetting one leaves the other",
              Secrets.forget(station: station, prefix: Secrets.visionPrefix)
              && Secrets.fetch(station: station) == "second-value")
        check("and forgetting the other leaves nothing",
              Secrets.forget(station: station)
              && Secrets.fetch(station: station).isEmpty)

        // Never put a whole key on screen or in a spoken line.
        check("a key is redacted to its last four",
              Secrets.redact("abcd-1234-wxyz") == "set, ending wxyz")
        check("a short one says only that it is set", Secrets.redact("abc") == "set")
        check("and nothing says not set", Secrets.redact("") == "not set")
    }
}


extension SelfTest {
    /// What a frame actually contains, so "it drew something" is counted
    /// rather than assumed. A black rectangle and a picture are the same
    /// shape, the same size and pass every arithmetic check alike.
    static func inspect(_ buffer: CVPixelBuffer) -> (mean: Int, distinct: Int) {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer)?
                .assumingMemoryBound(to: UInt8.self) else { return (0, 0) }
        let w = CVPixelBufferGetWidth(buffer), h = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        var total = 0, n = 0
        var seen = Set<UInt32>()
        for y in Swift.stride(from: 0, to: h, by: 8) {
            for x in Swift.stride(from: 0, to: w, by: 8) {
                let p = base + y * stride + x * 4
                total += Int(p[0]) + Int(p[1]) + Int(p[2])
                n += 3
                seen.insert(UInt32(p[0]) << 16 | UInt32(p[1]) << 8 | UInt32(p[2]))
            }
        }
        return (n > 0 ? total / n : 0, seen.count)
    }
}

/// A source that never has a picture, for checking the fallback.
private final class NeverAnswers: PictureSource {
    let kind = C.pictureCamera
    var error: String { "there is no picture" }
    var moving: Bool { true }
    func frame(width: Int, height: Int) -> CVPixelBuffer? { nil }
    func describe() -> String { "a camera that could not be opened" }
}
