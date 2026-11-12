// stomp_render.swift - a recording of the HX Stomp's screen (tools/hx_mirror.py view --record) set into a photo of the unit, its
// controls moving as they were used, as an H.264 MP4 at 30 frames a second, small enough to attach on GitHub (10 MB at most).
//   swiftc -O tools/mac/stomp_render.swift -o build/stomp_render     (hx_mirror.py builds it on first use)
//   stomp_render IN.mov TRACKS.json OUT.mp4 SKIN.json PHOTO_DIR
// SKIN.json (tools/mac/skins/): the photo's file name in PHOTO_DIR and, in its pixels (y down), where the unit is ("crop"), its
// screen, knobs [x, y, r], volume knob (and the level its pointer shows, "volume_at"), buttons [x, y, w, h], footswitch rings
// (the boxes to find their coloured pixels in), where FS4/FS5 light up ("badges") and, optionally, a touched control's colour
// ("accent", red-pink by default). The photos are the user's own copies of
// product photos, kept out of the repository (build/art/); the skins hold only coordinates. The video is the crop, 1280 pixels wide:
// twice a README's width, for sharp text on high-density screens.
// TRACKS.json (hx_mirror.tracks): {"duration": s, "controls": {name: {"down": [[from, to], ...], "turns": [[t, clicks], ...],
// "touch": [[from, to], ...], "levels": [[t, 0..1], ...], "led": [[t, the driver's colour, mode], ...]}}} for fs1..fs5,
// knob1..knob5, view, action, page_left, page_right and volume, times in seconds from the recording's first frame: touch is a
// footswitch's sensor, which feels a foot before the click, levels the volume knob's, led a footswitch ring's (mode 0 off, 1 on,
// 2 blinking).
import AVFoundation
import AppKit

let args = CommandLine.arguments
guard args.count == 6 else {
    FileHandle.standardError.write("usage: stomp_render IN.mov TRACKS.json OUT.mov SKIN.json PHOTO_DIR\n".data(using: .utf8)!)
    exit(2)
}
func fail(_ s: String) -> Never { FileHandle.standardError.write(("stomp_render: " + s + "\n").data(using: .utf8)!); exit(1) }

struct Track: Decodable { var down: [[Double]]?; var turns: [[Double]]?; var touch: [[Double]]?; var levels: [[Double]]?; var led: [[Double]]? }
struct Tracks: Decodable { var duration: Double?; var controls: [String: Track] }
struct Control {
    var down: [(Double, Double)] = [], turns: [(Double, Double)] = [], touch: [(Double, Double)] = [], levels: [(Double, Double)] = []
    var led: [(Double, Int, Int)] = []
}
guard let tracksData = try? Data(contentsOf: URL(fileURLWithPath: args[2])),
      let tracks = try? JSONDecoder().decode(Tracks.self, from: tracksData) else { fail("cannot read the tracks in \(args[2])") }
var controls: [String: Control] = [:]
for (name, v) in tracks.controls {
    controls[name] = Control(down: (v.down ?? []).map { ($0[0], $0[1]) }, turns: (v.turns ?? []).map { ($0[0], $0[1]) },
                             touch: (v.touch ?? []).map { ($0[0], $0[1]) }, levels: (v.levels ?? []).map { ($0[0], $0[1]) },
                             led: (v.led ?? []).map { ($0[0], Int($0[1]), Int($0[2])) })
}

struct Skin: Decodable {
    var photo: String; var crop: [Double]; var screen: [Double]; var knobs: [[Double]]; var volume: [Double]; var volume_at: Double
    var buttons: [String: [Double]]; var rings: [[Double]]; var badges: [[Double]]
    var matte: Bool?; var background: String?; var shadow_from: Double?; var accent: String?
}
guard let skinData = try? Data(contentsOf: URL(fileURLWithPath: args[4])),
      let skin = try? JSONDecoder().decode(Skin.self, from: skinData) else { fail("cannot read the skin \(args[4])") }
let photoPath = (args[5] as NSString).appendingPathComponent(skin.photo)
guard let photoRep = NSBitmapImageRep(data: (try? Data(contentsOf: URL(fileURLWithPath: photoPath))) ?? Data()),
      let photoOriginal = photoRep.cgImage else { fail("no photo at \(photoPath): put the unit's photo there (it stays out of git)") }

// A dark unit's white backdrop, taken out from the edges in: what joins the border and is light becomes black, as transparent as
// it was light, so the backdrop goes and the shadow under the unit stays a shadow on the video's background
func matted(_ img: CGImage) -> CGImage {
    let w = img.width, h = img.height
    var px = [UInt8](repeating: 0, count: w * h * 4)
    let ctx = CGContext(data: &px, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
    func lum(_ i: Int) -> Int { (Int(px[i * 4]) + Int(px[i * 4 + 1]) + Int(px[i * 4 + 2])) / 3 }
    let shadowRow = Int(skin.shadow_from ?? Double(h))      // below it, the unit's grey shadow: above, only near white, so the
    func grey(_ i: Int) -> Bool {                           // silver jacks along the top edge are kept
        let r = Int(px[i * 4]), g = Int(px[i * 4 + 1]), b = Int(px[i * 4 + 2])
        return max(r, g, b) - min(r, g, b) < 40 && lum(i) > (i / w >= shadowRow ? 70 : 225)    // the buffer's first row is the top
    }
    var seen = [Bool](repeating: false, count: w * h), stack: [Int] = []
    for x in 0..<w { stack += [x, (h - 1) * w + x] }
    for y in 0..<h { stack += [y * w, y * w + w - 1] }
    while let i = stack.popLast() {
        if seen[i] || !grey(i) { continue }
        seen[i] = true
        let x = i % w, y = i / w
        if x > 0 { stack.append(i - 1) }
        if x < w - 1 { stack.append(i + 1) }
        if y > 0 { stack.append(i - w) }
        if y < h - 1 { stack.append(i + w) }
    }
    for i in 0..<(w * h) where seen[i] {
        let a = UInt8(max(0, min(255, (255 - lum(i)) * 13 / 10)))
        px[i * 4] = 0; px[i * 4 + 1] = 0; px[i * 4 + 2] = 0; px[i * 4 + 3] = a
    }
    return ctx.makeImage()!
}
let photo = skin.matte == true ? matted(photoOriginal) : photoOriginal
func colour(_ hex: String) -> CGColor {
    let v = Int(hex.dropFirst(), radix: 16) ?? 0
    return CGColor(red: CGFloat(v >> 16 & 255) / 255, green: CGFloat(v >> 8 & 255) / 255, blue: CGFloat(v & 255) / 255, alpha: 1)
}
let backdrop = colour(skin.background ?? "#0d1117")
let accent = colour(skin.accent ?? "#ff2d6f")          // a touched control's colour: white is lost on a shiny black unit

let FPS = 30.0
let DEGREES_A_CLICK = 12.0, SWEEP = 0.08          // a knob click turns the photo's knob this far, over this many seconds
let PRESS_IN = 0.08, PRESS_HOLD = 0.4, PRESS_OUT = 0.3   // a press eases in, shows at least PRESS_HOLD, then fades
let WIDTH = 1280.0
let DARKEN = 0.22                                  // the unit only, so the backdrop still matches the page around it
let MAX_BYTES = 8_000_000.0                        // GitHub takes 10 MB; H.264's average rate overshoots a little
let K = WIDTH / skin.crop[2]                       // video pixels a photo pixel
let W = Int((skin.crop[2] * K / 2).rounded()) * 2, H = Int((skin.crop[3] * K / 2).rounded()) * 2

func isDown(_ c: Control?, _ t: Double) -> Double { inSpan(c?.down, t) }
func isTouched(_ c: Control?, _ t: Double) -> Double { inSpan(c?.touch, t) }
func inSpan(_ spans: [(Double, Double)]?, _ t: Double) -> Double {
    var v = 0.0
    for (a, b) in spans ?? [] where t >= a {
        let end = max(b, a + PRESS_HOLD)
        v = max(v, ease((t - a) / PRESS_IN) * (1 - ease((t - end) / PRESS_OUT)))
    }
    return v
}
func ease(_ x: Double) -> Double { let c = max(0, min(1, x)); return c * c * (3 - 2 * c) }
// 1 while a knob turns, fading out over PRESS_OUT after its last click
func moving(_ c: Control?, _ t: Double) -> Double { 1 - ease((t - lastMove(c, t) - SWEEP) / PRESS_OUT) }
func angle(_ c: Control?, _ t: Double) -> Double {
    var a = 0.0
    for (at, clicks) in c?.turns ?? [] where at <= t { a += clicks * DEGREES_A_CLICK * min(1, (t - at) / SWEEP) }
    return a
}
func lastMove(_ c: Control?, _ t: Double) -> Double {
    max((c?.turns.last(where: { $0.0 <= t })?.0) ?? -1e9, (c?.levels.last(where: { $0.0 <= t })?.0) ?? -1e9)
}
func level(_ c: Control?, _ t: Double) -> Double? { c?.levels.last(where: { $0.0 <= t })?.1 }
// 1 clockwise, -1 anticlockwise: the clicks of the last 0.3 s on balance, as an encoder throws the odd click backwards mid-turn
func direction(_ c: Control?, _ t: Double) -> Double {
    if let turn = c?.turns.last(where: { $0.0 <= t }) {
        let net = c!.turns.filter { $0.0 <= t && $0.0 > turn.0 - 0.3 }.reduce(0) { $0 + $1.1 }
        return net < 0 || (net == 0 && turn.1 < 0) ? -1 : 1
    }
    let seen = c?.levels.filter { $0.0 <= t } ?? []
    return seen.count >= 2 && seen[seen.count - 1].1 < seen[seen.count - 2].1 ? -1 : 1
}

// A footswitch ring's colour at t, or nil when it is dark: the driver's bytes are red, green, blue, low first (TAP's red is
// 0x0300ff, seen on the unit), and LED drive is linear light, so brighten as sRGB does or a dimmed ring looks off
func ledColour(_ c: Control?, _ t: Double) -> CGColor? {
    guard let (_, rgb, mode) = c?.led.last(where: { $0.0 <= t }), mode != 0, rgb != 0 else { return nil }
    if mode == 2 && Int(t / 0.25) % 2 == 1 { return nil }
    func v(_ x: Int) -> CGFloat { CGFloat(pow(Double(x) / 255, 1 / 2.2)) }
    return CGColor(red: v(rgb & 255), green: v(rgb >> 8 & 255), blue: v(rgb >> 16 & 255), alpha: 1)
}

// Each ring's coloured pixels in the photo, as a white image solid where they are, to paint the live colour over
let ringMasks: [CGImage] = skin.rings.map { r in
    let x0 = Int(r[0]), y0 = Int(r[1]), w = Int(r[2]), h = Int(r[3])
    var px = [UInt8](repeating: 0, count: w * h * 4)
    for y in 0..<h {
        for x in 0..<w {
            guard let c = photoRep.colorAt(x: x0 + x, y: y0 + y)?.usingColorSpace(.deviceRGB) else { continue }
            let hi = max(c.redComponent, c.greenComponent, c.blueComponent), lo = min(c.redComponent, c.greenComponent, c.blueComponent)
            let a = UInt8(max(0, min(1, (hi - lo - 0.1) * 5)) * 255)    // solid over the whole ring, or its old colour shows
            let i = (y * w + x) * 4
            px[i] = a; px[i + 1] = a; px[i + 2] = a; px[i + 3] = a        // premultiplied white
        }
    }
    let ctx = CGContext(data: &px, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    return ctx.makeImage()!
}

let ringClips = ringMasks.map { $0.flippedForClip() }

// Drawing happens in the photo's pixels, y down; images are drawn upright through drawUpright
func toPhoto(_ ctx: CGContext) {
    ctx.translateBy(x: 0, y: CGFloat(H))
    ctx.scaleBy(x: K, y: -K)
    ctx.translateBy(x: -skin.crop[0], y: -skin.crop[1])
}
func drawUpright(_ ctx: CGContext, _ img: CGImage, _ r: CGRect) {
    ctx.saveGState()
    ctx.translateBy(x: r.minX, y: r.maxY)
    ctx.scaleBy(x: 1, y: -1)
    ctx.draw(img, in: CGRect(x: 0, y: 0, width: r.width, height: r.height))
    ctx.restoreGState()
}
let photoRect = CGRect(x: 0, y: 0, width: photo.width, height: photo.height)
func circle(_ k: [Double], _ scale: Double = 1) -> CGRect {
    CGRect(x: k[0] - k[2] * scale, y: k[1] - k[2] * scale, width: 2 * k[2] * scale, height: 2 * k[2] * scale)
}
func glow(_ ctx: CGContext, _ c: CGPoint, _ r: Double, _ colour: CGColor, _ strength: Double, hole: Double = 0) {
    ctx.saveGState()
    if hole > 0 {                                   // a halo only: what is inside hole (a footswitch cap) stays as photographed
        ctx.addRect(CGRect(x: c.x - r * 2, y: c.y - r * 2, width: r * 4, height: r * 4))
        ctx.addEllipse(in: CGRect(x: c.x - hole, y: c.y - hole, width: 2 * hole, height: 2 * hole))
        ctx.clip(using: .evenOdd)
    }
    defer { ctx.restoreGState() }
    for k in stride(from: 6, through: 1, by: -1) {
        let rr = r * (1 + 0.08 * Double(k))
        ctx.setFillColor(colour.copy(alpha: strength * 0.06 * Double(7 - k))!)
        ctx.fillEllipse(in: CGRect(x: c.x - rr, y: c.y - rr, width: 2 * rr, height: 2 * rr))
    }
}
let white = CGColor(gray: 1, alpha: 1)
// A turning knob, unlike a pressed one, stays black: a pointer turning with it (the encoders have none of their own) and an
// arrow round it the way it turns, trailing the pointer
func turning(_ ctx: CGContext, _ k: [Double], _ deg: Double, _ dir: Double, _ strength: Double, pointer: CGColor?) {
    guard strength > 0 else { return }
    let c = CGPoint(x: k[0], y: k[1]), r = k[2] * 1.3, a = (deg - 90) * Double.pi / 180
    func at(_ phi: Double, _ rr: Double) -> CGPoint { CGPoint(x: c.x + rr * cos(phi), y: c.y + rr * sin(phi)) }
    ctx.saveGState()
    ctx.setAlpha(strength)
    ctx.setLineCap(.round)
    ctx.setLineWidth(5 / K)
    ctx.setStrokeColor(accent)
    ctx.move(to: at(a - dir * 1.75, r))
    for i in 1...24 { ctx.addLine(to: at(a - dir * 1.75 * (1 - Double(i) / 24), r)) }
    ctx.strokePath()
    let tangent = CGPoint(x: -sin(a) * dir, y: cos(a) * dir), out = CGPoint(x: cos(a), y: sin(a)), tip = at(a, r), h = 14 / K
    ctx.setFillColor(accent)
    ctx.move(to: CGPoint(x: tip.x + tangent.x * h, y: tip.y + tangent.y * h))
    ctx.addLine(to: CGPoint(x: tip.x + out.x * h * 0.8, y: tip.y + out.y * h * 0.8))
    ctx.addLine(to: CGPoint(x: tip.x - out.x * h * 0.8, y: tip.y - out.y * h * 0.8))
    ctx.fillPath()
    if let p = pointer {
        ctx.setLineWidth(6 / K)
        ctx.setStrokeColor(p)
        ctx.move(to: at(a, k[2] * 0.35))
        ctx.addLine(to: at(a, k[2] * 0.85))
        ctx.strokePath()
    }
    ctx.restoreGState()
}

// A control in the accent colour while touched: lighten for the black ones, keeping their printed labels; over the chrome
// footswitch caps, mostly opaque, as lighten leaves them pale and multiply dull
func tint(_ ctx: CGContext, _ path: CGPath, _ strength: Double, _ blend: CGBlendMode = .lighten) {
    guard strength > 0 else { return }
    ctx.saveGState()
    ctx.addPath(path)
    ctx.clip()
    ctx.setBlendMode(blend)
    ctx.setFillColor(accent.copy(alpha: strength * (blend == .normal ? 0.85 : 1))!)
    ctx.fill(path.boundingBox)
    ctx.restoreGState()
}

// The photo's own knob, turned by deg about its centre: its brushed face and knurl turn as the real one does
func turnKnob(_ ctx: CGContext, _ k: [Double], _ deg: Double) {
    guard deg.truncatingRemainder(dividingBy: 360) != 0 else { return }
    ctx.saveGState()
    ctx.addEllipse(in: circle(k, 1.02))
    ctx.clip()
    ctx.translateBy(x: k[0], y: k[1])
    ctx.rotate(by: deg * Double.pi / 180)
    ctx.translateBy(x: -k[0], y: -k[1])
    drawUpright(ctx, photo, photoRect)
    ctx.restoreGState()
}

func draw(_ ctx: CGContext, _ screen: CGImage?, _ t: Double) {
    ctx.setFillColor(backdrop)
    ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
    ctx.beginTransparencyLayer(auxiliaryInfo: nil)
    ctx.saveGState()
    toPhoto(ctx)
    ctx.interpolationQuality = .high
    drawUpright(ctx, photo, photoRect)
    let s = CGRect(x: skin.screen[0], y: skin.screen[1], width: skin.screen[2], height: skin.screen[3])
    ctx.setFillColor(CGColor(gray: 0, alpha: 1))
    ctx.fill(s)
    if let img = screen {
        let h = s.width * 3 / 4
        drawUpright(ctx, img, CGRect(x: s.minX, y: s.midY - h / 2, width: s.width, height: h))
    }
    litScreen(ctx, s)
    for (k, knob) in skin.knobs.enumerated() { turnKnob(ctx, knob, angle(controls["knob\(k + 1)"], t)) }
    if let v = level(controls["volume"], t) { turnKnob(ctx, skin.volume, (v - skin.volume_at) * 270) }
    for (k, ring) in skin.rings.enumerated() {
        let ctl = controls["fs\(k + 1)"]
        let r = CGRect(x: ring[0], y: ring[1], width: ring[2], height: ring[3])
        let c = CGPoint(x: r.midX, y: r.midY), radius = Double(min(r.width, r.height)) / 2
        let lit = ledColour(ctl, t)
        ctx.saveGState()
        ctx.clip(to: r, mask: ringClips[k])
        ctx.setFillColor(lit ?? CGColor(gray: 0.55, alpha: 1))     // an unlit ring: its plastic, grey
        ctx.fill(r)
        ctx.restoreGState()
        if let l = lit { glow(ctx, c, radius, l, 0.5, hole: radius * 0.98) }
    }
    ctx.restoreGState()
    ctx.setBlendMode(.sourceAtop)
    ctx.setFillColor(CGColor(gray: 0, alpha: DARKEN))
    ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
    ctx.endTransparencyLayer()

    // What is being touched, after the darkening so it stays bright
    ctx.saveGState()
    toPhoto(ctx)
    for (k, knob) in skin.knobs.enumerated() {
        let ctl = controls["knob\(k + 1)"], pressed = isDown(ctl, t)
        tint(ctx, CGPath(ellipseIn: circle(knob, 1.02), transform: nil), pressed)
        turning(ctx, knob, angle(ctl, t), direction(ctl, t), moving(ctl, t), pointer: pressed > 0.5 ? white : accent)
    }
    let vol = controls["volume"]
    if let v = level(vol, t) { turning(ctx, skin.volume, (v - skin.volume_at) * 270, direction(vol, t), moving(vol, t), pointer: nil) }
    for (name, b) in skin.buttons {
        let r = CGRect(x: b[0], y: b[1], width: b[2], height: b[3])
        tint(ctx, CGPath(roundedRect: r, cornerWidth: r.width * 0.12, cornerHeight: r.width * 0.12, transform: nil),
             isDown(controls[name], t))
    }
    for (k, ring) in skin.rings.enumerated() {
        let ctl = controls["fs\(k + 1)"]
        let r = CGRect(x: ring[0], y: ring[1], width: ring[2], height: ring[3])
        // The chrome cap, seen from above and in front: it sits a little right of the ring's centre and runs down past it
        let R = Double(min(r.width, r.height)) / 2
        let cap = CGRect(x: r.midX - 0.6 * R, y: r.midY - 0.5 * R, width: 1.3 * R, height: 1.4 * R)
        tint(ctx, CGPath(roundedRect: cap, cornerWidth: 0.6 * R, cornerHeight: 0.6 * R, transform: nil),
             max(isDown(ctl, t), isTouched(ctl, t)), .normal)
    }
    for (k, b) in skin.badges.enumerated() {
        let pressed = isDown(controls["fs\(k + 4)"], t)
        guard pressed > 0 else { continue }
        let r = Double(skin.screen[2]) * 0.09, c = CGPoint(x: b[0], y: b[1])
        ctx.setAlpha(pressed)
        ctx.setFillColor(accent)
        ctx.fillEllipse(in: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r))
        ctx.saveGState()
        ctx.translateBy(x: c.x, y: c.y)
        ctx.scaleBy(x: 1, y: -1)
        let text = NSAttributedString(string: "FS\(k + 4)", attributes: [.font: NSFont.systemFont(ofSize: r * 0.8, weight: .bold),
                                                                         .foregroundColor: NSColor.white])
        let line = CTLineCreateWithAttributedString(text)
        let w = CTLineGetTypographicBounds(line, nil, nil, nil)
        ctx.textPosition = CGPoint(x: -w / 2, y: -r * 0.28)
        CTLineDraw(line, ctx)
        ctx.restoreGState()
        ctx.setAlpha(1)
    }
    ctx.restoreGState()
}

// The live screen as a lit LCD under glass in the photo's light: a little dimmer, its black never quite black, a sheen across the
// glass, and the bezel's shadow along its top and left edges
func litScreen(_ ctx: CGContext, _ s: CGRect) {
    ctx.saveGState()
    ctx.clip(to: s)
    ctx.setFillColor(CGColor(gray: 0, alpha: 0.14))
    ctx.fill(s)
    ctx.setBlendMode(.lighten)
    ctx.setFillColor(CGColor(gray: 0.045, alpha: 1))
    ctx.fill(s)
    ctx.setBlendMode(.normal)
    let sheen = CGGradient(colorsSpace: nil, colors: [CGColor(gray: 1, alpha: 0.09), CGColor(gray: 1, alpha: 0.02),
                                                       CGColor(gray: 1, alpha: 0)] as CFArray, locations: [0, 0.45, 1])!
    ctx.drawLinearGradient(sheen, start: CGPoint(x: s.minX, y: s.minY), end: CGPoint(x: s.maxX, y: s.maxY), options: [])
    let shade = CGGradient(colorsSpace: nil, colors: [CGColor(gray: 0, alpha: 0.45), CGColor(gray: 0, alpha: 0)] as CFArray,
                           locations: [0, 1])!
    ctx.drawLinearGradient(shade, start: CGPoint(x: s.midX, y: s.minY), end: CGPoint(x: s.midX, y: s.minY + s.height * 0.06), options: [])
    ctx.drawLinearGradient(shade, start: CGPoint(x: s.minX, y: s.midY), end: CGPoint(x: s.minX + s.width * 0.035, y: s.midY), options: [])
    ctx.restoreGState()
}

extension CGImage {
    // clip(to:mask:) takes the mask in the context's y; drawing is y down here, so the mask is turned over to match
    func flippedForClip() -> CGImage {
        let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
        ctx.translateBy(x: 0, y: CGFloat(height))
        ctx.scaleBy(x: 1, y: -1)
        ctx.draw(self, in: CGRect(x: 0, y: 0, width: width, height: height))
        return ctx.makeImage()!
    }
}

// Read the recording's frames in order, keeping the latest one at or before each output frame's time
let asset = AVURLAsset(url: URL(fileURLWithPath: args[1]))
guard let track = asset.tracks(withMediaType: .video).first else { fail("no video in \(args[1])") }
guard let reader = try? AVAssetReader(asset: asset) else { fail("cannot read \(args[1])") }
let readOut = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
reader.add(readOut)
reader.startReading()
let duration = tracks.duration ?? asset.duration.seconds

let ciContext = CIContext()
func image(_ sample: CMSampleBuffer) -> CGImage? {
    guard let pb = CMSampleBufferGetImageBuffer(sample) else { return nil }
    let ci = CIImage(cvPixelBuffer: pb)
    return ciContext.createCGImage(ci, from: ci.extent)
}

try? FileManager.default.removeItem(atPath: args[3])
guard let writer = try? AVAssetWriter(outputURL: URL(fileURLWithPath: args[3]), fileType: .mp4) else { fail("cannot write \(args[3])") }
let bitRate = Int(min(Double(W * H * 4), MAX_BYTES * 8 / max(duration, 1)))
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: W, AVVideoHeightKey: H,
    AVVideoColorPropertiesKey: [AVVideoColorPrimariesKey: AVVideoColorPrimaries_ITU_R_709_2,
                                AVVideoTransferFunctionKey: AVVideoTransferFunction_ITU_R_709_2,
                                AVVideoYCbCrMatrixKey: AVVideoYCbCrMatrix_ITU_R_709_2],
    // A keyframe of the glittery photo costs ~150 KB, so one a second starves the frames between of bits
    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: bitRate, AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
                                      AVVideoMaxKeyFrameIntervalDurationKey: 10, AVVideoMaxKeyFrameIntervalKey: 300],
])
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA, kCVPixelBufferWidthKey as String: W,
    kCVPixelBufferHeightKey as String: H,
])
writer.add(input)
writer.startWriting()
writer.startSession(atSourceTime: .zero)

var current: CGImage? = nil
var pending = readOut.copyNextSampleBuffer()
let frames = Int((duration * FPS).rounded(.up)) + 1
for k in 0..<frames {
    let t = Double(k) / FPS
    while let s = pending, CMSampleBufferGetPresentationTimeStamp(s).seconds <= t + 1e-6 {
        current = image(s) ?? current
        pending = readOut.copyNextSampleBuffer()
    }
    while !input.isReadyForMoreMediaData { usleep(1000) }
    var pb: CVPixelBuffer?
    CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &pb)
    guard let buf = pb else { fail("no pixel buffer") }
    CVPixelBufferLockBaseAddress(buf, [])
    let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buf), width: W, height: H, bitsPerComponent: 8,
                        bytesPerRow: CVPixelBufferGetBytesPerRow(buf), space: CGColorSpaceCreateDeviceRGB(),
                        bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)!
    draw(ctx, current, t)
    CVPixelBufferUnlockBaseAddress(buf, [])
    adaptor.append(buf, withPresentationTime: CMTime(value: CMTimeValue(k), timescale: CMTimeScale(FPS)))
}
input.markAsFinished()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
if writer.status != .completed { fail("writing failed: \(writer.error.map { "\($0)" } ?? "unknown")") }
print(args[3])
