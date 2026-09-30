// Decode the iPhone "Spatial Audio" track (APAC, Apple Positional Audio Codec) of .MOV files to
// 4-channel first-order ambisonics WAV (ACN channel order W, Y, Z, X; SN3D normalisation).
//
// Runs on a Mac only (APAC can only be decoded by Apple's frameworks). Needs macOS 26 or newer for recordings made with iOS 27 (macOS 15 decodes them to silence).
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
        case .readerFailed(let m): return "decoding failed: \(m) (recordings from iOS 27 need macOS 26 or newer)"
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

    // Describe the source track in the log (helps when a macOS version decodes differently).
    for desc in try await track.load(.formatDescriptions) {
        if let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc)?.pointee {
            print("  source: \(fourCC(asbd.mFormatID)), \(asbd.mChannelsPerFrame) ch, \(Int(asbd.mSampleRate)) Hz")
        }
    }

    var layout = AudioChannelLayout()
    layout.mChannelLayoutTag = kHOA_ACN_SN3D | 4
    let layoutData = Data(bytes: &layout, count: MemoryLayout<AudioChannelLayout>.size)
    let pcm: [String: Any] = [
        AVFormatIDKey: kAudioFormatLinearPCM,
        AVLinearPCMBitDepthKey: 32,
        AVLinearPCMIsFloatKey: true,
        AVLinearPCMIsBigEndianKey: false,
        AVLinearPCMIsNonInterleaved: false,
    ]
    // Output formats to try, best first. A variant is accepted only if it produces real (non-silent) audio.
    var hoa = pcm; hoa[AVNumberOfChannelsKey] = 4; hoa[AVChannelLayoutKey] = layoutData
    var four = pcm; four[AVNumberOfChannelsKey] = 4
    let native = pcm
    let variants: [(String, [String: Any])] = [("HOA ACN/SN3D 4ch", hoa), ("4ch", four), ("native", native)]

    var lastError = "no output format produced audio"
    for (label, settings) in variants {
        let reader = try AVAssetReader(asset: asset)
        let out = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
        out.alwaysCopiesSampleData = true
        guard reader.canAdd(out) else { print("  \(label): not supported"); continue }
        reader.add(out)
        guard reader.startReading() else {
            lastError = reader.error?.localizedDescription ?? lastError
            print("  \(label): cannot start (\(lastError))"); continue
        }
        var samples: [Float] = []
        var channels = 0
        var sampleRate = 48000
        while let buf = out.copyNextSampleBuffer() {
            if channels == 0, let fd = CMSampleBufferGetFormatDescription(buf),
               let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fd)?.pointee {
                channels = Int(asbd.mChannelsPerFrame)
                sampleRate = Int(asbd.mSampleRate)
            }
            guard let block = CMSampleBufferGetDataBuffer(buf) else { continue }
            let n = CMBlockBufferGetDataLength(block)
            var chunk = [Float](repeating: 0, count: n / 4)
            chunk.withUnsafeMutableBytes { _ = CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: n, destination: $0.baseAddress!) }
            samples.append(contentsOf: chunk)
        }
        if reader.status == .failed {
            lastError = reader.error?.localizedDescription ?? "unknown"
            print("  \(label): failed while reading (\(lastError))"); continue
        }
        let peak = samples.reduce(Float(0)) { max($0, abs($1)) }
        let frames = channels > 0 ? samples.count / channels : 0
        print("  \(label): \(channels) ch, \(frames) frames, peak \(String(format: "%.5f", peak))")
        if frames == 0 || peak < 1e-5 {
            lastError = "\(label) produced silence"
            continue
        }
        if channels != 4 { print("  warning: \(channels) channels instead of 4 - not first-order ambisonics") }
        try writeWav(samples, channels: channels, sampleRate: sampleRate, to: output)
        return (channels, Double(frames) / Double(sampleRate))
    }
    throw DecodeError.readerFailed(lastError)
}

func fourCC(_ v: UInt32) -> String {
    let bytes = [24, 16, 8, 0].map { UInt8((v >> UInt32($0)) & 0xff) }
    return String(bytes: bytes, encoding: .ascii) ?? String(v)
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
