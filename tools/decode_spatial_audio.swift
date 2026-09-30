// Decode the iPhone "Spatial Audio" track (APAC, Apple Positional Audio Codec) of .MOV files to
// 4-channel first-order ambisonics WAV (ACN channel order W, Y, Z, X; SN3D normalisation).
//
// Runs on a Mac only (APAC can only be decoded by Apple's frameworks). Needs macOS 15 (Sequoia) or newer.
//
//   swift mac/decode_spatial_audio.swift data/videos            # every .MOV in the folder
//   swift mac/decode_spatial_audio.swift clap1.MOV out_folder   # one file
//
// Output: <out_folder>/<name>_foa.wav (default out_folder: data/spatial). Copy that folder back to the
// Windows PC; the next "python -m roomrecon" run uses data/spatial/<name>_foa.wav automatically.

import AVFoundation
import CoreMedia
import Foundation

let kAPAC: FourCharCode = 0x6170_6163                 // 'apac'
let kHOA_ACN_SN3D: AudioChannelLayoutTag = (190 << 16) // kAudioChannelLayoutTag_HOA_ACN_SN3D

enum DecodeError: Error, CustomStringConvertible {
    case noSpatialTrack, readerFailed(String)
    var description: String {
        switch self {
        case .noSpatialTrack: return "no APAC (Spatial Audio) track found"
        case .readerFailed(let m): return "decoding failed: \(m) (APAC decoding needs macOS 15 or newer)"
        }
    }
}

func writeWav(_ samples: [Float], channels: Int, sampleRate: Int, to url: URL) throws {
    var d = Data()
    func u32(_ v: UInt32) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 4)) }
    func u16(_ v: UInt16) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 2)) }
    let dataBytes = samples.count * 4
    d.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + dataBytes))
    d.append("WAVE".data(using: .ascii)!)
    d.append("fmt ".data(using: .ascii)!); u32(16)
    u16(3)                                   // IEEE float
    u16(UInt16(channels)); u32(UInt32(sampleRate))
    u32(UInt32(sampleRate * channels * 4)); u16(UInt16(channels * 4)); u16(32)
    d.append("data".data(using: .ascii)!); u32(UInt32(dataBytes))
    samples.withUnsafeBufferPointer { d.append(Data(buffer: $0)) }
    try d.write(to: url)
}

func decode(_ input: URL, to output: URL) async throws -> (Int, Double) {
    let asset = AVURLAsset(url: input)
    let tracks = try await asset.loadTracks(withMediaType: .audio)
    var spatial: AVAssetTrack?
    for t in tracks {
        let descs = try await t.load(.formatDescriptions)
        if descs.contains(where: { CMFormatDescriptionGetMediaSubType($0) == kAPAC }) { spatial = t }
    }
    guard let track = spatial else { throw DecodeError.noSpatialTrack }

    var layout = AudioChannelLayout()
    layout.mChannelLayoutTag = kHOA_ACN_SN3D | 4
    let layoutData = Data(bytes: &layout, count: MemoryLayout<AudioChannelLayout>.size)
    let sampleRate = 48000
    let base: [String: Any] = [
        AVFormatIDKey: kAudioFormatLinearPCM,
        AVLinearPCMBitDepthKey: 32,
        AVLinearPCMIsFloatKey: true,
        AVLinearPCMIsBigEndianKey: false,
        AVLinearPCMIsNonInterleaved: false,
        AVSampleRateKey: sampleRate,
        AVNumberOfChannelsKey: 4,
    ]
    // Ask for ambisonics (HOA ACN/SN3D, 4 channels) explicitly; if the system refuses that layout,
    // fall back to the decoder's native 4-channel output.
    var withLayout = base
    withLayout[AVChannelLayoutKey] = layoutData
    var reader: AVAssetReader?
    var out: AVAssetReaderTrackOutput?
    var lastError = "output settings not supported"
    for settings in [withLayout, base] {
        let r = try AVAssetReader(asset: asset)
        let o = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        o.alwaysCopiesSampleData = false
        guard r.canAdd(o) else { continue }
        r.add(o)
        if r.startReading() { reader = r; out = o; break }
        lastError = r.error?.localizedDescription ?? lastError
    }
    guard let reader, let out else { throw DecodeError.readerFailed(lastError) }

    var samples: [Float] = []
    while let buf = out.copyNextSampleBuffer() {
        guard let block = CMSampleBufferGetDataBuffer(buf) else { continue }
        let n = CMBlockBufferGetDataLength(block)
        var chunk = [Float](repeating: 0, count: n / 4)
        chunk.withUnsafeMutableBytes { _ = CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: n, destination: $0.baseAddress!) }
        samples.append(contentsOf: chunk)
    }
    if reader.status == .failed { throw DecodeError.readerFailed(reader.error?.localizedDescription ?? "unknown") }
    try writeWav(samples, channels: 4, sampleRate: sampleRate, to: output)
    return (4, Double(samples.count / 4) / Double(sampleRate))
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    print("usage: swift decode_spatial_audio.swift <video or folder> [output folder]")
    exit(1)
}
let fm = FileManager.default
let input = URL(fileURLWithPath: args[1])
let outDir = URL(fileURLWithPath: args.count >= 3 ? args[2] : "data/spatial")
try? fm.createDirectory(at: outDir, withIntermediateDirectories: true)

var isDir: ObjCBool = false
_ = fm.fileExists(atPath: input.path, isDirectory: &isDir)
let videos: [URL] = isDir.boolValue
    ? ((try? fm.contentsOfDirectory(at: input, includingPropertiesForKeys: nil)) ?? [])
        .filter { ["mov", "mp4"].contains($0.pathExtension.lowercased()) }
        .sorted { $0.lastPathComponent < $1.lastPathComponent }
    : [input]

var failures = 0
for v in videos {
    let dst = outDir.appendingPathComponent(v.deletingPathExtension().lastPathComponent + "_foa.wav")
    do {
        let (ch, dur) = try await decode(v, to: dst)
        print("\(v.lastPathComponent) -> \(dst.path)  (\(ch) ch, \(String(format: "%.2f", dur)) s)")
    } catch {
        failures += 1
        print("\(v.lastPathComponent): \(error)")
    }
}
exit(failures == 0 ? 0 : 1)
