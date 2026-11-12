// mirror_mac.swift - the window tools/hx_mirror.py shows the HX Stomp's screen in, and its recorder, without ffmpeg.
//   swiftc -O tools/mac/mirror_mac.swift -o build/mirror_mac     (hx_mirror.py builds it on first use)
//   mirror_mac WIDTH HEIGHT SCALE TITLE [OUT.mov [REC_SCALE [h264|prores [AUDIO_DEVICE]]]]
// Reads frames on stdin, each a little-endian Double (seconds, any clock) then WIDTH x HEIGHT RGB pixels, top row first, and
// shows each one SCALE times as big with square pixels. With OUT.mov it also writes them REC_SCALE times as big (4 by default),
// each frame at its time after the first, so the video keeps the HX Stomp's timing however unevenly the frames came: as H.264,
// or ProRes 4444, which keeps every pixel's colour. An even REC_SCALE keeps H.264's half-resolution colour inside each screen
// pixel; at an odd one, colours bleed across pixel edges. It finishes the file and exits when stdin ends or the window closes.
// With AUDIO_DEVICE (part of an input's name, e.g. HX Stomp; - for none) it records that device's sound beside the video.
import AVFoundation
import AppKit

let args = CommandLine.arguments
// Plain globals rather than guard-let bindings: the classes below may only use globals
let w = args.count >= 5 ? Int(args[1]) ?? 0 : 0, h = args.count >= 5 ? Int(args[2]) ?? 0 : 0
let scale = args.count >= 5 ? Int(args[3]) ?? 0 : 0
if w < 1 || h < 1 || scale < 1 {
    FileHandle.standardError.write("usage: mirror_mac WIDTH HEIGHT SCALE TITLE [OUT.mov [REC_SCALE [h264|prores [AUDIO_DEVICE]]]]\n"
        .data(using: .utf8)!)
    exit(2)
}
let title = args[4], outPath = args.count > 5 ? args[5] : nil
let rscale = args.count > 6 ? max(1, Int(args[6]) ?? 4) : 4
let prores = args.count > 7 && args[7] == "prores"
let audioName = args.count > 8 && args[8] != "-" ? args[8] : nil
let sw = w * scale, sh = h * scale, rw = w * rscale, rh = h * rscale
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
            AVVideoCodecKey: prores ? AVVideoCodecType.proRes4444 : AVVideoCodecType.h264, AVVideoWidthKey: rw, AVVideoHeightKey: rh,
        ].merging(prores ? [:] : [AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: rw * rh * 16,
                                                                     AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel]]) { a, _ in a })
        input.expectsMediaDataInRealTime = true
        adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: rw, kCVPixelBufferHeightKey as String: rh,
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
            for y in 0..<rh { memcpy(dst + y * stride, src.baseAddress! + y * rw * 4, rw * 4) }
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

// Each pixel rscale x rscale, as BGRA
func scaled(_ rgb: [UInt8]) -> [UInt8] {
    var out = [UInt8](repeating: 255, count: rw * rh * 4)
    for y in 0..<h {
        for x in 0..<w {
            let s = (y * w + x) * 3
            for dy in 0..<rscale {
                var d = ((y * rscale + dy) * rw + x * rscale) * 4
                for _ in 0..<rscale {
                    out[d] = rgb[s + 2]; out[d + 1] = rgb[s + 1]; out[d + 2] = rgb[s]
                    d += 4
                }
            }
        }
    }
    return out
}

// The device's sound as <take>-audio.m4a, and in <take>-audio.json when it began on the host clock (mach time, which Python's
// time.monotonic reads too): the frames run on the unit's clock, so hx_mirror places the sound against them from both
final class AudioTake: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    let session = AVCaptureSession(), queue = DispatchQueue(label: "audio")
    let writer: AVAssetWriter, input: AVAssetWriterInput, meta: String
    var start: Double?

    init?(named name: String, base: String) {
        let found = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external], mediaType: .audio, position: .unspecified)
        guard let dev = found.devices.first(where: { $0.localizedName.localizedCaseInsensitiveContains(name) }) else {
            say("no sound input named \(name): recording without sound"); return nil
        }
        if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
            let asked = DispatchSemaphore(value: 0)
            AVCaptureDevice.requestAccess(for: .audio) { _ in asked.signal() }
            asked.wait()
        }
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            say("this terminal may not record sound (System Settings > Privacy & Security > Microphone): recording without sound")
            return nil
        }
        meta = base + "-audio.json"
        try? FileManager.default.removeItem(atPath: meta)
        try? FileManager.default.removeItem(atPath: base + "-audio.m4a")
        guard let devIn = try? AVCaptureDeviceInput(device: dev),
              let w = try? AVAssetWriter(outputURL: URL(fileURLWithPath: base + "-audio.m4a"), fileType: .m4a) else {
            say("cannot record sound from \(dev.localizedName)"); return nil
        }
        writer = w
        input = AVAssetWriterInput(mediaType: .audio, outputSettings: [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 48000,
                                                                         AVNumberOfChannelsKey: 2, AVEncoderBitRateKey: 256000])
        input.expectsMediaDataInRealTime = true
        super.init()
        w.add(input)
        let out = AVCaptureAudioDataOutput()
        // the device's first two channels, USB 1/2: the HX Stomp's main output
        out.audioSettings = [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 48000, AVNumberOfChannelsKey: 2,
                             AVLinearPCMBitDepthKey: 32, AVLinearPCMIsFloatKey: true, AVLinearPCMIsNonInterleaved: false]
        out.setSampleBufferDelegate(self, queue: queue)
        session.addInput(devIn)
        session.addOutput(out)
        w.startWriting()
        session.startRunning()
        say("recording sound from \(dev.localizedName)")
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sample: CMSampleBuffer, from connection: AVCaptureConnection) {
        let pts = CMSampleBufferGetPresentationTimeStamp(sample)
        if start == nil {
            let host = CMClockGetHostTimeClock()
            start = CMSyncConvertTime(pts, from: session.synchronizationClock ?? host, to: host).seconds
            writer.startSession(atSourceTime: pts)
        }
        if input.isReadyForMoreMediaData { input.append(sample) }
    }

    func finish() {
        session.stopRunning()
        queue.sync {}
        guard let began = start else { writer.cancelWriting(); return }
        input.markAsFinished()
        let done = DispatchSemaphore(value: 0)
        writer.finishWriting { done.signal() }
        done.wait()
        try? "{\"host_start\": \(began)}\n".write(toFile: meta, atomically: true, encoding: .utf8)
    }
}

let recorder: Recorder? = outPath.map { p in
    do { return try Recorder(path: p) } catch { say("cannot record to \(p): \(error)"); exit(1) }
}
let audioTake: AudioTake? = outPath.flatMap { p in audioName.flatMap { AudioTake(named: $0, base: (p as NSString).deletingPathExtension) } }
var finished = false
let finishLock = NSLock()
func finish() {
    finishLock.lock()
    defer { finishLock.unlock() }
    if finished { return }
    finished = true
    recorder?.finish()
    audioTake?.finish()
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
