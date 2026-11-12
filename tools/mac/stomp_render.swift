// stomp_render.swift - a recording of the HX Stomp's screen (tools/hx_mirror.py view --record) set into a photo of the unit, its
// controls moving as they were used, as an H.264 MP4 at 30 frames a second, small enough to attach on GitHub (10 MB at most).
//   swiftc -O tools/mac/stomp_render.swift -o build/stomp_render     (hx_mirror.py builds it on first use)
//   stomp_render IN.mov TRACKS.json OUT.mp4 SKIN.json PHOTO_DIR [--audio SOUND.m4a OFFSET] [--keep FROM TO [FROM TO ...]]
//   stomp_render IN.mov TRACKS.json OUT.gif SKIN.json PHOTO_DIR --gif FROM TO [FROM TO ...] [--screen]
// --gif: FROM to TO seconds of the take as a looping GIF for a README, 480 x 360 at 15 frames a second: the unit on the skin's
// background, or with --screen the screen alone, where small text stays readable. More windows, in order, are joined: a cut
// leaves out a slip. IN may be a PNG, a still screen throughout. --audio puts the take's sound in the MP4, its start OFFSET
// seconds into the video (negative: it began before the first frame). --keep makes the MP4 of those windows only, joined, the
// sound cut with them.
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
var gifTimes: [Double] = [], keepTimes: [Double] = [], gifScreen = false, soundPath: String? = nil, soundOffset = 0.0
var badArgs = args.count < 6, a = 6
while a < args.count {
    switch args[a] {
    case "--gif":
        while a + 1 < args.count, let v = Double(args[a + 1]) { gifTimes.append(v); a += 1 }
    case "--keep":
        while a + 1 < args.count, let v = Double(args[a + 1]) { keepTimes.append(v); a += 1 }
    case "--screen": gifScreen = true
    case "--audio" where a + 2 < args.count && Double(args[a + 2]) != nil:
        soundPath = args[a + 1]; soundOffset = Double(args[a + 2])!; a += 2
    default: badArgs = true
    }
    a += 1
}
func windows(_ t: [Double]) -> [(Double, Double)] { stride(from: 0, to: t.count - 1, by: 2).map { (t[$0], t[$0 + 1]) } }
func inOrder(_ t: [Double]) -> Bool { t.count % 2 == 0 && (t.first ?? 0) >= 0 && zip(t, t.dropFirst()).allSatisfy { $0 < $1 } }
let gifWindows = windows(gifTimes)
guard !badArgs && inOrder(gifTimes) && inOrder(keepTimes)
        && (gifTimes.isEmpty ? !gifScreen : soundPath == nil && keepTimes.isEmpty) else {
    FileHandle.standardError.write(("usage: stomp_render IN.mov TRACKS.json OUT.mp4 SKIN.json PHOTO_DIR [--audio SOUND.m4a OFFSET] [--keep FROM TO ...]\n" +
        "       stomp_render IN.mov TRACKS.json OUT.gif SKIN.json PHOTO_DIR --gif FROM TO [FROM TO ...] [--screen]\n").data(using: .utf8)!)
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
    // sRGB, as a web colour is: CGColor(red:...) is Generic RGB, and #0d1117 came out a shade off the page
    return CGColor(srgbRed: CGFloat(v >> 16 & 255) / 255, green: CGFloat(v >> 8 & 255) / 255, blue: CGFloat(v & 255) / 255, alpha: 1)
}
let backdrop = colour(skin.background ?? "#0d1117")
let accent = colour(skin.accent ?? "#ff2d6f")          // a touched control's colour: white is lost on a shiny black unit

let FPS = 30.0
let DEGREES_A_CLICK = 12.0, SWEEP = 0.08          // a knob click turns the photo's knob this far, over this many seconds
let PRESS_IN = 0.08, PRESS_HOLD = 0.4, PRESS_OUT = 0.3   // a press eases in, shows at least PRESS_HOLD, then fades
let PRESS_GAP = 0.1                                // dark between quick presses, so taps don't read as one hold
let TOUCH = 0.3                                    // a foot resting on a footswitch is a faint tint, so its clicks stand out
let WIDTH = 1280.0
let DARKEN = 0.22                                  // the unit only, so the backdrop still matches the page around it
let MAX_BYTES = 8_000_000.0                        // GitHub takes 10 MB; H.264's average rate overshoots a little
let K = WIDTH / skin.crop[2]                       // video pixels a photo pixel
let W = Int((skin.crop[2] * K / 2).rounded()) * 2, H = Int((skin.crop[3] * K / 2).rounded()) * 2

func isDown(_ c: Control?, _ t: Double) -> Double { inSpan(c?.down, t) }
func isTouched(_ c: Control?, _ t: Double) -> Double { inSpan(c?.touch, t) * TOUCH }
func inSpan(_ spans: [(Double, Double)]?, _ t: Double) -> Double {
    let s = spans ?? []
    var v = 0.0
    for (i, (a, b)) in s.enumerated() where t >= a {
        // shown less long when the next press comes soon, and gone PRESS_GAP before it
        let next = i + 1 < s.count ? s[i + 1].0 : Double.infinity
        let end = max(b, min(a + PRESS_HOLD, next - PRESS_GAP - 0.15))
        let out = max(0.05, min(PRESS_OUT, next - end - PRESS_GAP))
        v = max(v, ease((t - a) / PRESS_IN) * (1 - ease((t - end) / out)))
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
let still = args[1].lowercased().hasSuffix(".png") ? NSBitmapImageRep(data: (try? Data(contentsOf: URL(fileURLWithPath: args[1])))
                                                                      ?? Data())?.cgImage : nil
if args[1].lowercased().hasSuffix(".png") && still == nil { fail("cannot read \(args[1])") }
let asset = AVURLAsset(url: URL(fileURLWithPath: args[1]))
var reader: AVAssetReader? = nil, readOut: AVAssetReaderTrackOutput? = nil     // reader kept: its output stops without it
if still == nil {
    guard let track = asset.tracks(withMediaType: .video).first else { fail("no video in \(args[1])") }
    guard let r = try? AVAssetReader(asset: asset) else { fail("cannot read \(args[1])") }
    let out = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
    r.add(out)
    r.startReading()
    reader = r; readOut = out
}
let duration = tracks.duration ?? asset.duration.seconds

let ciContext = CIContext()
func image(_ sample: CMSampleBuffer) -> CGImage? {
    guard let pb = CMSampleBufferGetImageBuffer(sample) else { return nil }
    let ci = CIImage(cvPixelBuffer: pb)
    return ciContext.createCGImage(ci, from: ci.extent)
}
var current: CGImage? = still
var pending = readOut?.copyNextSampleBuffer()
func screen(at t: Double) -> CGImage? {
    while let s = pending, CMSampleBufferGetPresentationTimeStamp(s).seconds <= t + 1e-6 {
        current = image(s) ?? current
        pending = readOut?.copyNextSampleBuffer()
    }
    return current
}

// A GIF for a README (480 x 360, 15 frames a second, looping, under 5 MB) from FROM to TO seconds of the take. Written here, not by
// ImageIO, which stores every frame whole: after the first, a frame holds only the pixels that changed, so the photo is sent once
let GIF_W = 480, GIF_H = 360, GIF_FPS = 15.0

final class Gif {
    var data = Data("GIF89a".utf8)
    var last: [UInt32]? = nil
    var held: Data? = nil, heldDelay = 0          // the frame before, written once the next one shows how long it stays

    init(_ w: Int, _ h: Int) {
        le(w); le(h)
        data += [0, 0, 0]                          // no global colour table: each frame brings its own
        data += [0x21, 0xff, 11] + Array("NETSCAPE2.0".utf8) + [3, 1, 0, 0, 0]     // loop for ever
    }
    func le(_ v: Int, into d: inout Data) { d += [UInt8(v & 255), UInt8(v >> 8 & 255)] }
    func le(_ v: Int) { le(v, into: &data) }

    // rgb: GIF_W x GIF_H pixels, 0xRRGGBB, top row first; shown for delay hundredths of a second
    func add(_ rgb: [UInt32], delay: Int) {
        var x0 = 0, y0 = 0, x1 = GIF_W - 1, y1 = GIF_H - 1
        if let prev = last {
            x0 = GIF_W; y0 = GIF_H; x1 = -1; y1 = -1
            for y in 0..<GIF_H {
                for x in 0..<GIF_W where rgb[y * GIF_W + x] != prev[y * GIF_W + x] {
                    x0 = min(x0, x); x1 = max(x1, x); y0 = min(y0, y); y1 = max(y1, y)
                }
            }
            if x1 < 0 { heldDelay += delay; return }
        }
        let w = x1 - x0 + 1, h = y1 - y0 + 1
        var changed: [UInt32] = [], keep = [Bool](repeating: false, count: w * h)
        for y in 0..<h {
            for x in 0..<w {
                let i = (y0 + y) * GIF_W + x0 + x
                if let prev = last, prev[i] == rgb[i] { keep[y * w + x] = true } else { changed.append(rgb[i]) }
            }
        }
        let clear = keep.contains(true)
        let (palette, index) = quantize(changed, colours: clear ? 255 : 256)
        var pixels = [UInt8](repeating: UInt8(clear ? palette.count : 0), count: w * h), k = 0
        for j in 0..<(w * h) where !keep[j] { pixels[j] = index(changed[k]); k += 1 }
        let bits = max(1, Int(ceil(log2(Double(palette.count + (clear ? 1 : 0))))))
        var f = Data([0x21, 0xf9, 4, clear ? 0x05 : 0x04])                  // keep the frame drawn under the next
        f += [0, 0, UInt8(clear ? palette.count : 0), 0]
        f += [0x2c]
        le(x0, into: &f); le(y0, into: &f); le(w, into: &f); le(h, into: &f)
        f += [0x80 | UInt8(bits - 1)]
        for k in 0..<(1 << bits) {
            let c = k < palette.count ? palette[k] : 0
            f += [UInt8(c >> 16 & 255), UInt8(c >> 8 & 255), UInt8(c & 255)]
        }
        f += lzw(pixels, max(2, bits))
        flush()
        held = f; heldDelay = delay
        last = rgb
    }
    func flush() {
        guard var f = held else { return }
        f[4] = UInt8(heldDelay & 255); f[5] = UInt8(heldDelay >> 8 & 255)
        data += f
        held = nil
    }
    func finish() -> Data { flush(); data += [0x3b]; return data }
}

// Median cut on 5 bits a channel: the palette (at most colours entries) and a lookup from a colour to its nearest entry. A colour
// on 1 % of the pixels or more keeps its own entry, exact: the backdrop has to match the page round the GIF
func quantize(_ px: [UInt32], colours: Int) -> ([UInt32], (UInt32) -> UInt8) {
    func key(_ c: UInt32) -> Int { Int(c >> 19 & 31) << 10 | Int(c >> 11 & 31) << 5 | Int(c >> 3 & 31) }
    var tally = [UInt32: Int]()
    for c in px { tally[c, default: 0] += 1 }
    let exact = Array(tally.filter { $0.value * 100 >= px.count }.keys.sorted().prefix(colours / 2))
    var exactIndex = [UInt32: UInt8]()
    for (j, c) in exact.enumerated() { exactIndex[c] = UInt8(j) }
    var count = [Int](repeating: 0, count: 32768), sum = [Int](repeating: 0, count: 32768 * 3)
    for c in px where exactIndex[c] == nil {
        let k = key(c)
        count[k] += 1
        sum[k * 3] += Int(c >> 16 & 255); sum[k * 3 + 1] += Int(c >> 8 & 255); sum[k * 3 + 2] += Int(c & 255)
    }
    var boxes: [[Int]] = [(0..<32768).filter { count[$0] > 0 }].filter { !$0.isEmpty }
    func channel(_ k: Int, _ a: Int) -> Int { k >> (10 - 5 * a) & 31 }
    func spread(_ b: [Int]) -> (Int, Int) {
        var best = (0, -1)
        for a in 0..<3 {
            let v = b.map { channel($0, a) }
            if v.max()! - v.min()! > best.1 { best = (a, v.max()! - v.min()!) }
        }
        return best
    }
    while boxes.count < colours - exact.count {
        // split the box with the most pixels among those still made of more than one colour
        guard let (i, _) = boxes.enumerated().filter({ $0.element.count > 1 })
            .max(by: { $0.element.reduce(0) { $0 + count[$1] } < $1.element.reduce(0) { $0 + count[$1] } }) else { break }
        let (a, _) = spread(boxes[i])
        let b = boxes[i].sorted { channel($0, a) < channel($1, a) }
        var half = 0, seen = 0, total = b.reduce(0) { $0 + count[$1] }
        while half < b.count - 1 && seen + count[b[half]] <= total / 2 { seen += count[b[half]]; half += 1 }
        half = max(1, half)
        boxes[i] = Array(b[..<half]); boxes.append(Array(b[half...]))
    }
    let palette: [UInt32] = exact + boxes.map { b in
        let n = max(1, b.reduce(0) { $0 + count[$1] })
        let r = b.reduce(0) { $0 + sum[$1 * 3] } / n, g = b.reduce(0) { $0 + sum[$1 * 3 + 1] } / n, bl = b.reduce(0) { $0 + sum[$1 * 3 + 2] } / n
        return UInt32(r << 16 | g << 8 | bl)
    }
    var nearest = [Int16](repeating: -1, count: 32768)
    return (palette, { c in
        if let j = exactIndex[c] { return j }
        let k = key(c)
        if nearest[k] < 0 {
            var best = 0, bestD = Int.max
            for (j, p) in palette.enumerated() {
                let dr = Int(p >> 16 & 255) - Int(c >> 16 & 255), dg = Int(p >> 8 & 255) - Int(c >> 8 & 255), db = Int(p & 255) - Int(c & 255)
                let d = 2 * dr * dr + 4 * dg * dg + 3 * db * db
                if d < bestD { best = j; bestD = d }
            }
            nearest[k] = Int16(best)
        }
        return UInt8(nearest[k])
    })
}

// GIF's LZW: codes grow from minimum + 1 bits to 12, then the table starts again; in sub-blocks of at most 255 bytes
func lzw(_ px: [UInt8], _ minimum: Int) -> Data {
    let clearCode = 1 << minimum
    var table = [Int: Int](), next = clearCode + 2, size = minimum + 1
    var out = [UInt8](), acc = 0, nbits = 0
    func put(_ code: Int) {
        acc |= code << nbits; nbits += size
        while nbits >= 8 { out.append(UInt8(acc & 255)); acc >>= 8; nbits -= 8 }
    }
    put(clearCode)
    var prefix = Int(px[0])
    for p in px.dropFirst() {
        let k = prefix << 8 | Int(p)
        if let code = table[k] { prefix = code; continue }
        put(prefix)
        table[k] = next
        if next == 1 << size { size += 1 }
        next += 1
        if next == 4096 { put(clearCode); table.removeAll(keepingCapacity: true); next = clearCode + 2; size = minimum + 1 }
        prefix = Int(p)
    }
    put(prefix)
    put(clearCode + 1)
    if nbits > 0 { out.append(UInt8(acc & 255)) }
    var d = Data([UInt8(minimum)])
    for s in stride(from: 0, to: out.count, by: 255) { let e = min(out.count, s + 255); d += [UInt8(e - s)] + out[s..<e] }
    return d + [0]
}

try? FileManager.default.removeItem(atPath: args[3])
if !gifWindows.isEmpty {
    var px = [UInt8](repeating: 0, count: GIF_W * GIF_H * 4)
    // sRGB, as browsers show a GIF
    let ctx = CGContext(data: &px, width: GIF_W, height: GIF_H, bitsPerComponent: 8, bytesPerRow: GIF_W * 4,
                        space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    ctx.interpolationQuality = .high
    let gif = Gif(GIF_W, GIF_H)
    let times = gifWindows.flatMap { w in (0..<Int(((w.1 - w.0) * GIF_FPS).rounded())).map { w.0 + Double($0) / GIF_FPS } }
    for (k, t) in times.enumerated() {
        let shown = screen(at: t)
        ctx.saveGState()
        ctx.setFillColor(backdrop)
        ctx.fill(CGRect(x: 0, y: 0, width: GIF_W, height: GIF_H))
        if gifScreen {
            if let img = shown { ctx.draw(img, in: CGRect(x: 0, y: 0, width: GIF_W, height: GIF_H)) }
        } else {
            let s = min(Double(GIF_W) / Double(W), Double(GIF_H) / Double(H))
            ctx.translateBy(x: (Double(GIF_W) - Double(W) * s) / 2, y: (Double(GIF_H) - Double(H) * s) / 2)
            ctx.scaleBy(x: s, y: s)
            draw(ctx, shown, t)
        }
        ctx.restoreGState()
        var rgb = [UInt32](repeating: 0, count: GIF_W * GIF_H)
        for i in 0..<(GIF_W * GIF_H) { rgb[i] = UInt32(px[i * 4]) << 16 | UInt32(px[i * 4 + 1]) << 8 | UInt32(px[i * 4 + 2]) }
        // whole hundredths that add up to the frame times, as a GIF counts no finer
        gif.add(rgb, delay: Int((Double(k + 1) * 100 / GIF_FPS).rounded()) - Int((Double(k) * 100 / GIF_FPS).rounded()))
    }
    do { try gif.finish().write(to: URL(fileURLWithPath: args[3])) } catch { fail("cannot write \(args[3])") }
    print(args[3])
    exit(0)
}

guard let writer = try? AVAssetWriter(outputURL: URL(fileURLWithPath: args[3]), fileType: .mp4) else { fail("cannot write \(args[3])") }
let kept = keepTimes.isEmpty ? [(0.0, duration)] : windows(keepTimes).map { ($0.0, min($0.1, duration)) }
let keptStarts = kept.indices.map { i in kept[..<i].reduce(0) { $0 + $1.1 - $1.0 } }      // each window's start in the video
let length = kept.reduce(0) { $0 + $1.1 - $1.0 }
let SOUND_RATE = 160_000.0
let bitRate = Int(min(Double(W * H * 4), MAX_BYTES * 8 / max(length, 1) - (soundPath != nil ? SOUND_RATE : 0)))
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

// The sound, decoded and moved soundOffset later, fed a little ahead of the frames: the writer interleaves the two
var soundOut: AVAssetReaderTrackOutput? = nil, soundIn: AVAssetWriterInput? = nil, soundReader: AVAssetReader? = nil   // kept
if let path = soundPath {
    let asset = AVURLAsset(url: URL(fileURLWithPath: path))
    guard let track = asset.tracks(withMediaType: .audio).first, let r = try? AVAssetReader(asset: asset),
          let desc = (track.formatDescriptions.first as! CMAudioFormatDescription?),
          let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc)?.pointee else { fail("no sound in \(path)") }
    let out = AVAssetReaderTrackOutput(track: track, outputSettings: [AVFormatIDKey: kAudioFormatLinearPCM])
    r.add(out)
    r.startReading()
    let sound = AVAssetWriterInput(mediaType: .audio, outputSettings: [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: asbd.mSampleRate,
        AVNumberOfChannelsKey: min(2, Int(asbd.mChannelsPerFrame)), AVEncoderBitRateKey: SOUND_RATE])
    writer.add(sound)
    soundReader = r; soundOut = out; soundIn = sound
}
var nextSound = soundOut?.copyNextSampleBuffer(), soundQueue: [CMSampleBuffer] = [], soundWritten = 0.0   // in the video's time
// Silence like s's samples for the video's from to to: a gap before the sound (its capture takes a moment to start) would hold
// the writer up, and some players close it, putting the sound early
func silence(like s: CMSampleBuffer, from: Double, to: Double) -> CMSampleBuffer? {
    guard let format = CMSampleBufferGetFormatDescription(s),
          let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(format)?.pointee else { return nil }
    let count = Int(((to - from) * asbd.mSampleRate).rounded()), bytes = count * Int(asbd.mBytesPerFrame)
    var block: CMBlockBuffer?, out: CMSampleBuffer?
    guard count > 0, CMBlockBufferCreateWithMemoryBlock(allocator: nil, memoryBlock: nil, blockLength: bytes, blockAllocator: nil,
            customBlockSource: nil, offsetToData: 0, dataLength: bytes, flags: kCMBlockBufferAssureMemoryNowFlag, blockBufferOut: &block) == 0,
          let b = block, CMBlockBufferFillDataBytes(with: 0, blockBuffer: b, offsetIntoDestination: 0, dataLength: bytes) == 0 else { return nil }
    CMAudioSampleBufferCreateReadyWithPacketDescriptions(allocator: nil, dataBuffer: b, formatDescription: format, sampleCount: count,
        presentationTimeStamp: CMTime(seconds: from, preferredTimescale: CMTimeScale(asbd.mSampleRate)), packetDescriptions: nil,
        sampleBufferOut: &out)
    return out
}
// The parts of s (an LPCM buffer of the take's sound) inside the kept windows, each at its time in the video
func pieces(_ s: CMSampleBuffer) -> [(at: Double, buffer: CMSampleBuffer)] {
    var timing = CMSampleTimingInfo()
    CMSampleBufferGetSampleTimingInfo(s, at: 0, timingInfoOut: &timing)
    let one = timing.duration.seconds, n = CMSampleBufferGetNumSamples(s)                // LPCM: a sample's duration
    let at = timing.presentationTimeStamp.seconds + soundOffset, end = at + Double(n) * one
    var out: [(Double, CMSampleBuffer)] = []
    for (w, start) in zip(kept, keptStarts) where end > w.0 && at < w.1 {
        let first = Int(((max(at, w.0) - at) / one).rounded()), last = min(n, Int(((min(end, w.1) - at) / one).rounded()))
        var part: CMSampleBuffer?
        guard last > first, CMSampleBufferCopySampleBufferForRange(allocator: nil, sampleBuffer: s,
                sampleRange: CFRange(location: first, length: last - first), sampleBufferOut: &part) == 0, let p = part else { continue }
        var moved = timing, copy: CMSampleBuffer?
        moved.presentationTimeStamp = CMTime(seconds: start + at + Double(first) * one - w.0, preferredTimescale: timing.presentationTimeStamp.timescale)
        moved.decodeTimeStamp = .invalid
        CMSampleBufferCreateCopyWithNewTiming(allocator: nil, sampleBuffer: p, sampleTimingEntryCount: 1, sampleTimingArray: &moved,
                                              sampleBufferOut: &copy)
        if let c = copy { out.append((moved.presentationTimeStamp.seconds, c)) }
    }
    return out
}
// Fed a little ahead of the frames, one buffer each time the writer is ready: it interleaves the two
func feedSound(until t: Double) {
    guard let sound = soundIn else { return }
    while sound.isReadyForMoreMediaData {
        if !soundQueue.isEmpty { sound.append(soundQueue.removeFirst()); continue }
        // finished as soon as it runs out or passes the last window: until then the writer holds the frames back for it
        guard let s = nextSound, CMSampleBufferGetPresentationTimeStamp(s).seconds + soundOffset < kept.last!.1 else {
            sound.markAsFinished(); soundIn = nil; return
        }
        let parts = pieces(s)
        if let first = parts.first, first.at > t { return }
        for (at, b) in parts {
            if at > soundWritten + 0.002, let quiet = silence(like: b, from: soundWritten, to: at) { soundQueue.append(quiet) }
            soundQueue.append(b)
            soundWritten = at + CMSampleBufferGetDuration(b).seconds
        }
        nextSound = soundOut?.copyNextSampleBuffer()
    }
}

writer.startWriting()
writer.startSession(atSourceTime: .zero)

// (the take's time, the video's) of each frame: the whole take keeps a last frame at its very end
let times: [(Double, Double)] = zip(kept, keptStarts).flatMap { w, start in
    (0..<(keepTimes.isEmpty ? Int((duration * FPS).rounded(.up)) + 1 : Int(((w.1 - w.0) * FPS).rounded()))).map {
        (w.0 + Double($0) / FPS, start + Double($0) / FPS)
    }
}
for (k, (t, v)) in times.enumerated() {
    let shown = screen(at: t)
    feedSound(until: v + 0.5)
    while !input.isReadyForMoreMediaData { feedSound(until: v + 1); usleep(1000) }
    var pb: CVPixelBuffer?
    CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &pb)
    guard let buf = pb else { fail("no pixel buffer") }
    CVPixelBufferLockBaseAddress(buf, [])
    let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buf), width: W, height: H, bitsPerComponent: 8,
                        bytesPerRow: CVPixelBufferGetBytesPerRow(buf), space: CGColorSpaceCreateDeviceRGB(),
                        bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)!
    draw(ctx, shown, t)
    CVPixelBufferUnlockBaseAddress(buf, [])
    adaptor.append(buf, withPresentationTime: CMTime(value: CMTimeValue(k), timescale: CMTimeScale(FPS)))
}
input.markAsFinished()
while soundIn != nil {
    feedSound(until: length)
    usleep(1000)
}
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
if writer.status != .completed { fail("writing failed: \(writer.error.map { "\($0)" } ?? "unknown")") }
print(args[3])
