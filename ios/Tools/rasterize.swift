// Renders an SVG to a PNG of an exact pixel size with WebKit: logo images and app icons.
// usage: rasterize <in.svg> <out.png> <width px> <height px> <background: none | RRGGBB> [content scale 0…1]
import AppKit
import WebKit

let arguments = CommandLine.arguments
guard arguments.count >= 6 else {
    print("usage: rasterize <in.svg> <out.png> <width> <height> <none|RRGGBB> [scale]")
    exit(2)
}
let input = URL(fileURLWithPath: arguments[1])
let output = URL(fileURLWithPath: arguments[2])
let width = Int(arguments[3]) ?? 512
let height = Int(arguments[4]) ?? 512
let background = arguments[5]
let scale = arguments.count > 6 ? Double(arguments[6]) ?? 1 : 1

final class Rasterizer: NSObject, WKNavigationDelegate {
    let webView: WKWebView
    let window: NSWindow

    override init() {
        window = NSWindow(contentRect: NSRect(x: -30000, y: -30000, width: 100, height: 100),
                          styleMask: [.borderless], backing: .buffered, defer: false)
        let factor = window.backingScaleFactor
        let size = NSSize(width: CGFloat(width) / factor, height: CGFloat(height) / factor)
        window.setContentSize(size)
        webView = WKWebView(frame: NSRect(origin: .zero, size: size))
        super.init()
        if background == "none" { webView.setValue(false, forKey: "drawsBackground") }
        webView.navigationDelegate = self
        window.contentView = webView
        window.orderFront(nil)
    }

    func start() {
        guard var svg = try? String(contentsOf: input, encoding: .utf8) else {
            print("cannot read", input.path)
            exit(1)
        }
        // Let CSS size the root <svg>
        if let tag = svg.range(of: "<svg[^>]*>", options: .regularExpression) {
            var head = String(svg[tag])
            head = head.replacingOccurrences(of: #"\s(width|height)="[^"]*""#, with: "", options: .regularExpression)
            svg.replaceSubrange(tag, with: head)
        }
        let fill = background == "none" ? "transparent" : "#\(background)"
        let percent = scale * 100
        let html = """
        <html><head><style>html,body{margin:0;width:100%;height:100%;background:\(fill);overflow:hidden}\
        body{display:flex;align-items:center;justify-content:center}\
        body>svg{display:block;width:\(percent)%;height:\(percent)%}</style></head><body>\(svg)</body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            let configuration = WKSnapshotConfiguration()
            configuration.afterScreenUpdates = true
            webView.takeSnapshot(with: configuration) { image, error in
                guard let image, let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
                    print("snapshot failed:", error?.localizedDescription ?? "no image")
                    exit(1)
                }
                // Draw into a bitmap of the exact size requested; app icons must not have an alpha channel
                let opaque = background != "none"
                let context = CGContext(
                    data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: opaque ? CGImageAlphaInfo.noneSkipLast.rawValue : CGImageAlphaInfo.premultipliedLast.rawValue
                )!
                context.interpolationQuality = .high
                context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
                let png = context.makeImage().flatMap { NSBitmapImageRep(cgImage: $0).representation(using: .png, properties: [:]) }
                guard let png else { exit(1) }
                try? png.write(to: output)
                print("saved", output.lastPathComponent, width, "x", height)
                exit(0)
            }
        }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let rasterizer = Rasterizer()
rasterizer.start()
app.run()
