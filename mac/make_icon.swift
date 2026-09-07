// The Drop Deck mark, drawn rather than loaded, into an .icns.
//
// The same four pads in a two by two grid with the top left one lit that
// dropdeck/appicon.py draws for Windows, with the same colours, so the two
// copies are the same product in a Dock and a taskbar. Drawn at every size
// macOS asks for and baked with iconutil, and run by build.sh only when the
// icon is missing or this file is newer than it.
//
//     swift make_icon.swift Resources/AppIcon.icns

import AppKit

let body = "#1c2436"                // the case, shared with the other TG Studios marks
let lit = "#e8b33f"                 // the pad that is playing
let pad = "#596b86"                 // the three that are not
let rim = "#8a97ad"                 // so the case reads on a dark Dock

func colour(_ hex: String) -> CGColor {
    let v = UInt32(hex.dropFirst(), radix: 16)!
    return CGColor(red: CGFloat((v >> 16) & 0xFF) / 255, green: CGFloat((v >> 8) & 0xFF) / 255,
                   blue: CGFloat(v & 0xFF) / 255, alpha: 1)
}

func draw(_ size: Int) -> CGImage {
    let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
                        space: CGColorSpace(name: CGColorSpace.sRGB)!,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    // Top left origin, so the lit pad is at the top like the Windows one.
    ctx.translateBy(x: 0, y: CGFloat(size))
    ctx.scaleBy(x: 1, y: -1)
    ctx.setAllowsAntialiasing(true)
    let u = CGFloat(size) / 32.0

    // A rim, not just a fill: the case is 1.05 to 1 against a dark Dock and
    // without an outline the whole silhouette disappears.
    let caseRect = CGRect(x: 1 * u, y: 1 * u, width: 30 * u, height: 30 * u)
    let casePath = CGPath(roundedRect: caseRect, cornerWidth: 7 * u, cornerHeight: 7 * u, transform: nil)
    ctx.addPath(casePath)
    ctx.setFillColor(colour(body))
    ctx.fillPath()
    ctx.addPath(casePath)
    ctx.setStrokeColor(colour(rim))
    ctx.setLineWidth(max(1, u))
    ctx.strokePath()

    // Below about 20 pixels the gaps between four pads close up and the grid
    // turns into a blob, so the small mark is one big lit pad instead.
    if size < 20 {
        ctx.addPath(CGPath(roundedRect: CGRect(x: 7 * u, y: 7 * u, width: 18 * u, height: 18 * u),
                           cornerWidth: 4 * u, cornerHeight: 4 * u, transform: nil))
        ctx.setFillColor(colour(lit))
        ctx.fillPath()
    } else {
        for row in 0..<2 {
            for col in 0..<2 {
                let r = CGRect(x: (6 + CGFloat(col) * 11) * u, y: (6 + CGFloat(row) * 11) * u,
                               width: 9 * u, height: 9 * u)
                ctx.addPath(CGPath(roundedRect: r, cornerWidth: 2.2 * u, cornerHeight: 2.2 * u,
                                   transform: nil))
                ctx.setFillColor(colour(row == 0 && col == 0 ? lit : pad))
                ctx.fillPath()
            }
        }
    }
    return ctx.makeImage()!
}

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "Resources/AppIcon.icns"
let work = NSTemporaryDirectory() + "dropdeck-icon-\(getpid())/AppIcon.iconset"
try! FileManager.default.createDirectory(atPath: work, withIntermediateDirectories: true)

// macOS wants each point size at one and two times scale.
for points in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = points * scale
        let image = draw(pixels)
        let rep = NSBitmapImageRep(cgImage: image)
        rep.size = NSSize(width: points, height: points)
        let png = rep.representation(using: .png, properties: [:])!
        let name = scale == 1 ? "icon_\(points)x\(points).png" : "icon_\(points)x\(points)@2x.png"
        try! png.write(to: URL(fileURLWithPath: work + "/" + name))
    }
}

let task = Process()
task.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
task.arguments = ["-c", "icns", "-o", out, work]
try! task.run()
task.waitUntilExit()
try? FileManager.default.removeItem(atPath: (work as NSString).deletingLastPathComponent)
if task.terminationStatus != 0 {
    FileHandle.standardError.write("iconutil failed\n".data(using: .utf8)!)
    exit(1)
}
print("Wrote \(out)")
