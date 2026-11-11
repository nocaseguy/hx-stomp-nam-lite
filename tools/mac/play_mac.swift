// play_mac.swift - play a fixed test signal into an audio output's channels on macOS (no ffmpeg).
//   swiftc -O tools/mac/play_mac.swift -o build/play_mac
//   ./build/play_mac "HX Stomp" 6 5,6 [LEVEL]
// Picks the first output device whose name contains the first argument and plays, for SECONDS,
// a "pluck" every 0.5 s on the listed channels (1-based): a 110 Hz sawtooth with a 0.25 s decay,
// peak LEVEL (default 0.3). Every other channel is silent. With the HX Stomp's input block set to
// USB 5/6 this reamps the unit with the same signal every time (hx_smoke, record_mac).
import AVFoundation
import CoreAudio
import Foundation

let args = CommandLine.arguments
guard args.count >= 4, let seconds = Double(args[2]) else {
    FileHandle.standardError.write("usage: play_mac DEVICE-NAME SECONDS CH[,CH..] [LEVEL]\n".data(using: .utf8)!)
    exit(2)
}
let want = args[1]
let chans = args[3].split(separator: ",").compactMap { Int($0) }.map { $0 - 1 }
let level = args.count > 4 ? Float(args[4]) ?? 0.3 : 0.3
func say(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

func outputDevice(named want: String) -> AudioDeviceID? {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
                                          mScope: kAudioObjectPropertyScopeGlobal,
                                          mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size)
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids)
    for id in ids {
        var nameAddr = AudioObjectPropertyAddress(mSelector: kAudioObjectPropertyName,
                                                  mScope: kAudioObjectPropertyScopeGlobal,
                                                  mElement: kAudioObjectPropertyElementMain)
        var name: Unmanaged<CFString>?
        var nsize = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        AudioObjectGetPropertyData(id, &nameAddr, 0, nil, &nsize, &name)
        var outAddr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreamConfiguration,
                                                 mScope: kAudioDevicePropertyScopeOutput,
                                                 mElement: kAudioObjectPropertyElementMain)
        var osize: UInt32 = 0
        AudioObjectGetPropertyDataSize(id, &outAddr, 0, nil, &osize)
        if let n = name?.takeRetainedValue() as String?, n.contains(want), osize > UInt32(MemoryLayout<AudioBufferList>.size) - 16 {
            return id
        }
    }
    return nil
}

guard var dev = outputDevice(named: want) else { say("no audio output like '\(want)'"); exit(1) }
let engine = AVAudioEngine()
let out = engine.outputNode
guard let au = out.audioUnit else { exit(1) }
guard AudioUnitSetProperty(au, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0,
                           &dev, UInt32(MemoryLayout<AudioDeviceID>.size)) == noErr else {
    say("could not select the device"); exit(1)
}
let fmt = out.outputFormat(forBus: 0)                 // the device's own format (all its channels)
let nch = Int(fmt.channelCount), rate = fmt.sampleRate
guard chans.allSatisfy({ $0 >= 0 && $0 < nch }) else { say("the device has \(nch) output channels"); exit(1) }
let layout = AVAudioChannelLayout(layoutTag: kAudioChannelLayoutTag_DiscreteInOrder | UInt32(nch))!
let srcFmt = AVAudioFormat(standardFormatWithSampleRate: rate, channelLayout: layout)   // (more than 2 channels need a layout)
var t: Int = 0
let period = Int(rate * 0.5), f0 = 110.0
let src = AVAudioSourceNode(format: srcFmt) {
    _, _, frameCount, abl in
    let bufs = UnsafeMutableAudioBufferListPointer(abl)
    for f in 0..<Int(frameCount) {
        let k = t % period
        let ph = (Double(k) * f0 / rate).truncatingRemainder(dividingBy: 1.0)
        let v = Float((2 * ph - 1) * exp(-Double(k) / (rate * 0.25))) * level
        for (c, b) in bufs.enumerated() {
            b.mData!.assumingMemoryBound(to: Float.self)[f] = chans.contains(c) ? v : 0
        }
        t += 1
    }
    return noErr
}
engine.attach(src)
engine.connect(src, to: out, format: srcFmt)
do { try engine.start() } catch { say("engine: \(error)"); exit(1) }
say("playing plucks (110 Hz, peak \(level)) on channel(s) \(chans.map { $0 + 1 }) of \(nch) at \(Int(rate)) Hz for \(seconds) s")
Thread.sleep(forTimeInterval: seconds)
engine.stop()
