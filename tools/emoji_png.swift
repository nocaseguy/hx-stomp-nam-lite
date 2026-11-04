// Renders one emoji (Apple Color Emoji, macOS) to a 160x160 RGBA PNG: swift tools/emoji_png.swift <emoji> <out.png>
import AppKit

let args = CommandLine.arguments
guard args.count == 3, let font = NSFont(name: "AppleColorEmoji", size: 120) else {
    FileHandle.standardError.write("usage: swift emoji_png.swift <emoji> <out.png>\n".data(using: .utf8)!)
    exit(1)
}
let side = 160
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side, bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                           bytesPerRow: 0, bitsPerPixel: 0)!
let text = NSAttributedString(string: args[1], attributes: [.font: font])
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let size = text.size()
text.draw(at: NSPoint(x: (CGFloat(side) - size.width) / 2, y: (CGFloat(side) - size.height) / 2))
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[2]))
