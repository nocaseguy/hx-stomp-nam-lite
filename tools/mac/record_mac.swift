// record_mac.swift - record an audio input to a .wav on macOS, without ffmpeg.
//   swiftc -O tools/mac/record_mac.swift -o build/record_mac
//   ./build/record_mac "HX Stomp" 2.5 out.wav
// Picks the first audio capture device whose name contains the first argument
// and writes every sample buffer it delivers, as 32-bit float, all channels.
// (AVCaptureAudioFileOutput dropped a quarter of the Stomp's 8-channel audio.)
// A gap in the buffers' timestamps is reported and makes the exit status 3.
// The terminal needs microphone access (System Settings > Privacy & Security).
import AVFoundation
import CoreMedia
import Foundation

let args = CommandLine.arguments
guard args.count == 4, let seconds = Double(args[2]) else {
    FileHandle.standardError.write("usage: record_mac DEVICE-NAME SECONDS OUT.wav\n".data(using: .utf8)!)
    exit(2)
}
let want = args[1], outPath = args[3]
func say(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

let found = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external], mediaType: .audio,
                                             position: .unspecified).devices
guard let dev = found.first(where: { $0.localizedName.contains(want) }) else {
    say("no audio input like '\(want)'; have: " + found.map { $0.localizedName }.joined(separator: ", "))
    exit(1)
}

final class Sink: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    var data = Data()
    var channels = 0, rate = 0.0, frames = 0, gaps = 0
    var nextTime: Int64? = nil
    let lock = NSLock()

    func captureOutput(_ o: AVCaptureOutput, didOutput sb: CMSampleBuffer, from c: AVCaptureConnection) {
        guard let fd = CMSampleBufferGetFormatDescription(sb),
              let asbdp = CMAudioFormatDescriptionGetStreamBasicDescription(fd) else { return }
        let asbd = asbdp.pointee
        let n = CMSampleBufferGetNumSamples(sb)
        let pts = CMSampleBufferGetPresentationTimeStamp(sb)
        let ch = Int(asbd.mChannelsPerFrame)
        var block: CMBlockBuffer?
        var size = 0
        CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(sb, bufferListSizeNeededOut: &size, bufferListOut: nil,
                                                                bufferListSize: 0, blockBufferAllocator: nil,
                                                                blockBufferMemoryAllocator: nil, flags: 0,
                                                                blockBufferOut: nil)
        let raw = UnsafeMutableRawPointer.allocate(byteCount: size, alignment: 16)
        defer { raw.deallocate() }
        let abl = raw.bindMemory(to: AudioBufferList.self, capacity: 1)
        guard CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sb, bufferListSizeNeededOut: nil, bufferListOut: abl, bufferListSize: size,
            blockBufferAllocator: nil, blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: &block) == noErr
        else { return }
        let bufs = UnsafeMutableAudioBufferListPointer(abl)
        let isFloat = asbd.mFormatFlags & kAudioFormatFlagIsFloat != 0
        let nonInter = asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
        let bits = Int(asbd.mBitsPerChannel)
        let width = Int(asbd.mBytesPerFrame) / (nonInter ? 1 : max(ch, 1))   // bytes a sample takes
        let high = asbd.mFormatFlags & kAudioFormatFlagIsAlignedHigh != 0
        // one float32 per channel per frame, interleaved
        var out = [Float](repeating: 0, count: n * ch)
        func sample(_ p: UnsafeRawPointer, _ i: Int) -> Float {
            if isFloat { return p.load(fromByteOffset: 4 * i, as: Float.self) }
            switch width {
            case 2: return Float(p.load(fromByteOffset: 2 * i, as: Int16.self)) / 32768
            case 4:
                let v = p.loadUnaligned(fromByteOffset: 4 * i, as: Int32.self)
                if bits >= 32 || high { return Float(v) / 2147483648 }
                return Float(v) / Float(1 << (bits - 1))           // low-aligned, sign-extended
            default:
                let b = p.advanced(by: 3 * i).assumingMemoryBound(to: UInt8.self)
                var v = Int32(b[0]) | Int32(b[1]) << 8 | Int32(b[2]) << 16
                if v & 0x800000 != 0 { v -= 0x1000000 }
                return Float(v) / 8388608
            }
        }
        if nonInter {
            for (k, b) in bufs.enumerated() where k < ch {
                guard let p = b.mData else { continue }
                for f in 0..<n { out[f * ch + k] = sample(p, f) }
            }
        } else if let p = bufs[0].mData {
            for i in 0..<(n * ch) { out[i] = sample(p, i) }
        }
        lock.lock()
        if frames == 0 {
            say("format: \(ch) ch, \(bits) bits in \(width) bytes, float \(isFloat), non-interleaved \(nonInter), aligned high \(high)")
        }
        channels = ch
        rate = asbd.mSampleRate
        let t = CMTimeConvertScale(pts, timescale: Int32(rate), method: .roundHalfAwayFromZero).value
        if let nt = nextTime, abs(t - nt) > 1 {
            gaps += 1
            say("gap: \(t - nt) samples at sample \(frames)")
        }
        nextTime = t + Int64(n)
        out.withUnsafeBufferPointer { data.append(Data(buffer: $0)) }
        frames += n
        lock.unlock()
    }
}

let auth = DispatchSemaphore(value: 0)
var granted = false
AVCaptureDevice.requestAccess(for: .audio) { granted = $0; auth.signal() }
auth.wait()
guard granted else { say("microphone access denied for this terminal"); exit(1) }

let session = AVCaptureSession()
let output = AVCaptureAudioDataOutput()
let sink = Sink()
let queue = DispatchQueue(label: "rec")
output.setSampleBufferDelegate(sink, queue: queue)
session.addInput(try AVCaptureDeviceInput(device: dev))
session.addOutput(output)
session.startRunning()
Thread.sleep(forTimeInterval: seconds)
session.stopRunning()
queue.sync {}

sink.lock.lock()
let ch = sink.channels, rate = UInt32(sink.rate)
var wav = Data()
func u32(_ v: UInt32) { var x = v.littleEndian; wav.append(Data(bytes: &x, count: 4)) }
func u16(_ v: UInt16) { var x = v.littleEndian; wav.append(Data(bytes: &x, count: 2)) }
wav.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + sink.data.count)); wav.append("WAVE".data(using: .ascii)!)
wav.append("fmt ".data(using: .ascii)!); u32(16); u16(3); u16(UInt16(ch)); u32(rate)
u32(rate * UInt32(4 * ch)); u16(UInt16(4 * ch)); u16(32)
wav.append("data".data(using: .ascii)!); u32(UInt32(sink.data.count)); wav.append(sink.data)
try wav.write(to: URL(fileURLWithPath: outPath))
say("recorded \(sink.frames) frames (\(String(format: "%.3f", Double(sink.frames) / sink.rate)) s), \(ch) channels at \(rate) Hz from \(dev.localizedName) to \(outPath); \(sink.gaps) gap(s)")
exit(sink.gaps == 0 ? 0 : 3)
