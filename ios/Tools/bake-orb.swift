// Bakes the CTA orb animations (SVG with SMIL) into HEVC-with-alpha videos for the app.
// WebKit renders every frame exactly as the browser would; the app then plays light, hardware-decoded video.
//
// usage: xcrun swiftc -O -o /tmp/bake-orb Tools/bake-orb.swift && /tmp/bake-orb Design/Animations ChatUI/Animations [pixels] [fps]
import AppKit
import AVFoundation
import VideoToolbox
import WebKit

let arguments = CommandLine.arguments
guard arguments.count >= 3 else {
    print("usage: bake-orb <svg folder> <output folder> [pixels=768] [fps=30]")
    exit(2)
}
let inputFolder = URL(fileURLWithPath: arguments[1])
let outputFolder = URL(fileURLWithPath: arguments[2])
let pixels = arguments.count > 3 ? Int(arguments[3]) ?? 768 : 768
let fps = arguments.count > 4 ? Double(arguments[4]) ?? 30 : 30

let files = ((try? FileManager.default.contentsOfDirectory(at: inputFolder, includingPropertiesForKeys: nil)) ?? [])
    .filter { $0.pathExtension == "svg" }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }
guard !files.isEmpty else {
    print("no .svg files in", inputFolder.path)
    exit(1)
}
try? FileManager.default.createDirectory(at: outputFolder, withIntermediateDirectories: true)

/// Longest `dur` in the file: the length of the animation
func duration(of svg: String) -> Double {
    let regex = try! NSRegularExpression(pattern: #"\bdur="([\d.]+)(ms|s)?""#)
    var longest = 0.0
    for match in regex.matches(in: svg, range: NSRange(svg.startIndex..., in: svg)) {
        guard let valueRange = Range(match.range(at: 1), in: svg), let value = Double(svg[valueRange]) else { continue }
        let isMilliseconds = Range(match.range(at: 2), in: svg).map { svg[$0] == "ms" } ?? false
        longest = max(longest, isMilliseconds ? value / 1000 : value)
    }
    return longest
}

final class Baker: NSObject, WKNavigationDelegate {
    private let webView: WKWebView
    private let window: NSWindow
    private var queue: [URL]

    private var file: URL?
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var frame = 0
    private var frameCount = 0
    private var checkedSize = false

    init(files: [URL]) {
        queue = files
        window = NSWindow(contentRect: NSRect(x: -30000, y: -30000, width: 100, height: 100),
                          styleMask: [.borderless], backing: .buffered, defer: false)
        let points = CGFloat(pixels) / window.backingScaleFactor
        window.setContentSize(NSSize(width: points, height: points))
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: points, height: points))
        super.init()
        webView.setValue(false, forKey: "drawsBackground")
        webView.navigationDelegate = self
        window.contentView = webView
        window.orderFront(nil)
    }

    func nextFile() {
        guard !queue.isEmpty else {
            print("done")
            exit(0)
        }
        let url = queue.removeFirst()
        guard var svg = try? String(contentsOf: url, encoding: .utf8) else {
            print("cannot read", url.path)
            exit(1)
        }
        let length = duration(of: svg)
        let loops = svg.contains("repeatCount=\"indefinite\"")
        // A loop leaves out its last frame (it equals the first); a one-shot keeps its final, frozen frame
        frameCount = Int((length * fps).rounded()) + (loops ? 0 : 1)
        frame = 0
        file = url
        if let range = svg.range(of: #"width="600" height="600""#) {
            svg.replaceSubrange(range, with: "")
        }
        let html = """
        <html><head><style>html,body{margin:0;width:100%;height:100%;background:transparent;overflow:hidden}\
        body>svg{display:block;width:100%;height:100%}</style></head><body>\(svg)</body></html>
        """
        print(String(format: "%@: %.2f s, %d frames%@", url.lastPathComponent, length, frameCount, loops ? ", loop" : ""))
        webView.loadHTMLString(html, baseURL: nil)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        startWriter()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.renderFrame() }
    }

    private func startWriter() {
        guard let file else { return }
        let output = outputFolder.appendingPathComponent(file.deletingPathExtension().lastPathComponent + ".mov")
        try? FileManager.default.removeItem(at: output)
        let writer = try! AVAssetWriter(outputURL: output, fileType: .mov)
        var compression: [String: Any] = [
            AVVideoQualityKey: 0.8,
            AVVideoExpectedSourceFrameRateKey: fps,
            kVTCompressionPropertyKey_TargetQualityForAlpha as String: 0.85,
            kVTCompressionPropertyKey_AlphaChannelMode as String: kVTAlphaChannelMode_PremultipliedAlpha,
        ]
        var settings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.hevcWithAlpha,
            AVVideoWidthKey: pixels,
            AVVideoHeightKey: pixels,
            AVVideoCompressionPropertiesKey: compression,
            AVVideoColorPropertiesKey: [
                AVVideoColorPrimariesKey: AVVideoColorPrimaries_ITU_R_709_2,
                AVVideoTransferFunctionKey: AVVideoTransferFunction_ITU_R_709_2,
                AVVideoYCbCrMatrixKey: AVVideoYCbCrMatrix_ITU_R_709_2,
            ],
        ]
        if !writer.canApply(outputSettings: settings, forMediaType: .video) {
            compression.removeValue(forKey: AVVideoQualityKey)
            settings[AVVideoCompressionPropertiesKey] = compression
        }
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
        input.expectsMediaDataInRealTime = false
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: pixels,
            kCVPixelBufferHeightKey as String: pixels,
        ])
        writer.add(input)
        writer.startWriting()
        writer.startSession(atSourceTime: .zero)
        self.writer = writer
        self.input = input
        self.adaptor = adaptor
    }

    private func renderFrame() {
        guard frame < frameCount else {
            finishFile()
            return
        }
        let time = Double(frame) / fps
        let script = "var s=document.querySelector('svg');s.pauseAnimations();s.setCurrentTime(\(time));s.getBBox();0"
        webView.evaluateJavaScript(script) { _, _ in
            let configuration = WKSnapshotConfiguration()
            configuration.afterScreenUpdates = true
            self.webView.takeSnapshot(with: configuration) { image, error in
                guard let image, let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
                    print("snapshot failed:", error?.localizedDescription ?? "no image")
                    exit(1)
                }
                if !self.checkedSize {
                    self.checkedSize = true
                    if cgImage.width != pixels {
                        print("note: snapshot is \(cgImage.width) px, scaled to \(pixels) px")
                    }
                }
                self.append(cgImage, at: self.frame)
                self.frame += 1
                self.renderFrame()
            }
        }
    }

    private func append(_ image: CGImage, at index: Int) {
        guard let input, let adaptor, let pool = adaptor.pixelBufferPool else { return }
        while !input.isReadyForMoreMediaData {
            RunLoop.current.run(until: Date().addingTimeInterval(0.005))
        }
        var buffer: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, pool, &buffer)
        guard let buffer else { return }
        CVPixelBufferLockBaseAddress(buffer, [])
        let context = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer),
            width: pixels,
            height: pixels,
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpace(name: CGColorSpace.sRGB)!,
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        )!
        context.clear(CGRect(x: 0, y: 0, width: pixels, height: pixels))
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: pixels, height: pixels))
        CVPixelBufferUnlockBaseAddress(buffer, [])
        adaptor.append(buffer, withPresentationTime: CMTime(value: CMTimeValue(index), timescale: CMTimeScale(fps)))
    }

    private func finishFile() {
        guard let writer, let input else { return }
        input.markAsFinished()
        writer.finishWriting {
            DispatchQueue.main.async {
                if writer.status != .completed {
                    print("writing failed:", writer.error?.localizedDescription ?? "unknown")
                    exit(1)
                }
                let size = (try? writer.outputURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
                print("  saved", writer.outputURL.lastPathComponent, ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))
                self.writer = nil
                self.nextFile()
            }
        }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let baker = Baker(files: files)
baker.nextFile()
app.run()
