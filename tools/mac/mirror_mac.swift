// mirror_mac.swift - the window tools/hx_mirror.py shows the HX Stomp's screen in, and its recorder, without ffmpeg.
//   swiftc -O tools/mac/mirror_mac.swift -o build/mirror_mac     (hx_mirror.py builds it on first use)
//   mirror_mac WIDTH HEIGHT SCALE TITLE [OUT.mov]
// Reads frames on stdin, each a little-endian Double (seconds, any clock) then WIDTH x HEIGHT RGB pixels, top row first, and
// shows each one SCALE times as big with square pixels. With OUT.mov it also writes them as H.264 at that size, each frame at
// its time after the first, so the video keeps the HX Stomp's timing however unevenly the frames came. It finishes the file
// and exits when stdin ends or the window closes.
import AVFoundation
import AppKit

let args = CommandLine.arguments
// Plain globals rather than guard-let bindings: the classes below may only use globals
let w = args.count >= 5 ? Int(args[1]) ?? 0 : 0, h = args.count >= 5 ? Int(args[2]) ?? 0 : 0
let scale = args.count >= 5 ? Int(args[3]) ?? 0 : 0
if w < 1 || h < 1 || scale < 1 {
    FileHandle.standardError.write("usage: mirror_mac WIDTH HEIGHT SCALE TITLE [OUT.mov]\n".data(using: .utf8)!)
    exit(2)
}
let title = args[4], outPath = args.count > 5 ? args[5] : nil
let sw = w * scale, sh = h * scale
func say(_ s: String) { FileHandle.standardError.write(("mirror_mac: " + s + "\n").data(using: .utf8)!) }

final class Recorder {
    let writer: AVAssetWriter
    let input: AVAssetWriterInput
    let adaptor: AVAssetWriterInputPixelBufferAdaptor
    var first: Double?
    var last = CMTime.invalid

    init(path: String) throws {
        try? FileManager.default.removeItem(atPath: path)
        writer = try AVAssetWriter(outputURL: URL(fileURLWithPath: path), fileType: .mov)
        input = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: sw, AVVideoHeightKey: sh,
            AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 8_000_000],
        ])
        input.expectsMediaDataInRealTime = true
        adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: sw, kCVPixelBufferHeightKey as String: sh,
        ])
        writer.add(input)
        writer.startWriting()
        writer.startSession(atSourceTime: .zero)
    }

    func add(_ bgra: [UInt8], at seconds: Double) {
        let t = CMTime(seconds: seconds - (first ?? seconds), preferredTimescale: 1_000_000)
        if first == nil { first = seconds }
        guard t > last || !last.isValid, input.isReadyForMoreMediaData, let pool = adaptor.pixelBufferPool else { return }
        var pb: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, pool, &pb)
        guard let buf = pb else { return }
        CVPixelBufferLockBaseAddress(buf, [])
        let dst = CVPixelBufferGetBaseAddress(buf)!.assumingMemoryBound(to: UInt8.self)
        let stride = CVPixelBufferGetBytesPerRow(buf)
        bgra.withUnsafeBufferPointer { src in
            for y in 0..<sh { memcpy(dst + y * stride, src.baseAddress! + y * sw * 4, sw * 4) }
        }
        CVPixelBufferUnlockBaseAddress(buf, [])
        if adaptor.append(buf, withPresentationTime: t) { last = t }
    }

    func finish() {
        input.markAsFinished()
        let done = DispatchSemaphore(value: 0)
        writer.finishWriting { done.signal() }
        done.wait()
        if writer.status != .completed { say("recording failed: \(writer.error.map { "\($0)" } ?? "unknown")") }
    }
}

// Each pixel scale x scale, as BGRA
func scaled(_ rgb: [UInt8]) -> [UInt8] {
    var out = [UInt8](repeating: 255, count: sw * sh * 4)
    for y in 0..<h {
        for x in 0..<w {
            let s = (y * w + x) * 3
            for dy in 0..<scale {
                var d = ((y * scale + dy) * sw + x * scale) * 4
                for _ in 0..<scale {
                    out[d] = rgb[s + 2]; out[d + 1] = rgb[s + 1]; out[d + 2] = rgb[s]
                    d += 4
                }
            }
        }
    }
    return out
}

let recorder: Recorder? = outPath.map { p in
    do { return try Recorder(path: p) } catch { say("cannot record to \(p): \(error)"); exit(1) }
}
var finished = false
let finishLock = NSLock()
func finish() {
    finishLock.lock()
    defer { finishLock.unlock() }
    if finished { return }
    finished = true
    recorder?.finish()
}

final class Delegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    let layer = CALayer()

    func applicationDidFinishLaunching(_ note: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: sw, height: sh), styleMask: [.titled, .closable, .miniaturizable],
                          backing: .buffered, defer: false)
        window.title = title + (outPath != nil ? " (recording)" : "")
        window.delegate = self
        let view = NSView(frame: window.contentLayoutRect)
        view.wantsLayer = true
        layer.magnificationFilter = .nearest
        layer.backgroundColor = NSColor.black.cgColor
        layer.frame = view.bounds
        view.layer!.addSublayer(layer)
        window.contentView = view
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        Thread { self.read() }.start()
    }

    func read() {
        let input = FileHandle.standardInput
        let size = 8 + w * h * 3
        while true {
            var data = Data()
            while data.count < size {
                let more = input.readData(ofLength: size - data.count)
                if more.isEmpty { finish(); DispatchQueue.main.async { NSApp.terminate(nil) }; return }
                data.append(more)
            }
            let seconds = data.prefix(8).withUnsafeBytes { $0.loadUnaligned(as: Double.self) }
            let rgb = [UInt8](data.dropFirst(8))
            let image = CGImage(width: w, height: h, bitsPerComponent: 8, bitsPerPixel: 24, bytesPerRow: w * 3,
                                space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: 0),
                                provider: CGDataProvider(data: Data(rgb) as CFData)!, decode: nil, shouldInterpolate: false,
                                intent: .defaultIntent)
            DispatchQueue.main.async {
                CATransaction.begin()
                CATransaction.setDisableActions(true)
                self.layer.contents = image
                CATransaction.commit()
            }
            if let r = recorder {
                let frame = scaled(rgb)
                finishLock.lock()
                if !finished { r.add(frame, at: seconds) }
                finishLock.unlock()
            }
        }
    }

    func windowWillClose(_ note: Notification) {
        finish()
        exit(0)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = Delegate()
app.delegate = delegate
app.run()
