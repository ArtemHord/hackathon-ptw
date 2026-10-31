import AVFoundation
import SwiftUI
import UIKit

/// What the assistant is doing right now; drives the orb everywhere in the app.
/// Raw values match the video names in Animations (orb-idle.mov, transition-idle-to-listening.mov…).
enum OrbState: String, Equatable {
    case idle, listening, thinking, speaking

    var caption: String {
        switch self {
        case .idle: "Ready"
        case .listening: "Listening…"
        case .thinking: "Thinking…"
        case .speaking: "Answering…"
        }
    }
}

/// The CTA orb. The designer's SVG animations are baked into HEVC-with-alpha videos (Tools/bake-orb.swift),
/// so the app plays exactly the same frames, hardware-decoded and cheap on battery.
struct OrbView: View {
    var state: OrbState = .idle
    /// Greater than 1 enlarges the artwork in its frame; the faint outer glow spills over the edges
    var zoom: Double = 1
    /// Stops the animation, for example while the orb is hidden behind another control
    var isPaused = false
    /// Plays one video once instead of the state loops (the launch animation)
    var once: String? = nil
    /// Called when a one-time video shows its first frame, with its length in seconds
    var onStart: ((Double) -> Void)? = nil

    @Environment(\.theme) private var theme

    var body: some View {
        OrbPlayer(state: state, zoom: zoom, isPaused: isPaused, once: once, onStart: onStart)
            // The artwork is in the brand colors; other accent palettes shift its hue
            .hueRotation(.degrees(theme.palette.hueRotation))
    }
}

private struct OrbPlayer: UIViewRepresentable {
    let state: OrbState
    let zoom: Double
    let isPaused: Bool
    let once: String?
    let onStart: ((Double) -> Void)?

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeUIView(context: Context) -> OrbPlayerView {
        let view = OrbPlayerView()
        configure(view)
        if let once {
            view.playOnce(once)
        } else {
            view.setState(state)
        }
        return view
    }

    func updateUIView(_ view: OrbPlayerView, context: Context) {
        configure(view)
        if once == nil { view.setState(state) }
    }

    private func configure(_ view: OrbPlayerView) {
        view.zoom = zoom
        view.isPaused = isPaused || reduceMotion
        view.onStart = onStart
    }
}

/// Plays the orb videos: every state loops; a state change plays the matching 0.8 s transition first.
/// Each clip gets its own video layer and only appears once its first frame is ready, so nothing ever blinks.
final class OrbPlayerView: UIView {
    private final class Clip {
        let layer: AVPlayerLayer
        let player: AVQueuePlayer
        var looper: AVPlayerLooper?
        var endObserver: NSObjectProtocol?
        var readyObserver: NSKeyValueObservation?

        init(player: AVQueuePlayer, looper: AVPlayerLooper?) {
            self.player = player
            self.looper = looper
            layer = AVPlayerLayer(player: player)
            layer.videoGravity = .resizeAspect
            layer.backgroundColor = UIColor.clear.cgColor
            layer.opacity = 0
        }

        func stop() {
            readyObserver = nil
            if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
            endObserver = nil
            looper?.disableLooping()
            looper = nil
            player.pause()
            player.removeAllItems()
            layer.player = nil
            layer.removeFromSuperlayer()
        }
    }

    var zoom: CGFloat = 1 {
        didSet { if zoom != oldValue { setNeedsLayout() } }
    }
    var isPaused = false {
        didSet { if isPaused != oldValue { updatePlayback() } }
    }
    var onStart: ((Double) -> Void)?

    /// On screen
    private var visible: Clip?
    /// Waiting for its first frame
    private var incoming: Clip?
    /// The loop on screen; nil while a transition plays
    private var loopState: OrbState?
    /// Where the running transition goes
    private var transitionTarget: OrbState?
    private var target: OrbState = .idle
    private var isOneShot = false

    override init(frame: CGRect) {
        super.init(frame: frame)
        isUserInteractionEnabled = false
        isOpaque = false
        backgroundColor = .clear
        NotificationCenter.default.addObserver(
            self, selector: #selector(resume), name: UIApplication.willEnterForegroundNotification, object: nil
        )
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) is not supported")
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
        incoming?.stop()
        visible?.stop()
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        for clip in [visible, incoming].compactMap({ $0 }) { clip.layer.frame = clipFrame }
        CATransaction.commit()
    }

    private var clipFrame: CGRect {
        let size = CGSize(width: bounds.width * zoom, height: bounds.height * zoom)
        return CGRect(
            x: (bounds.width - size.width) / 2, y: (bounds.height - size.height) / 2,
            width: size.width, height: size.height
        )
    }

    // MARK: - State machine

    func setState(_ state: OrbState) {
        guard !isOneShot else { return }
        target = state
        advance()
    }

    func playOnce(_ name: String) {
        isOneShot = true
        guard let url = Self.url(name) else { return }
        let player = AVQueuePlayer(items: [AVPlayerItem(url: url)])
        player.actionAtItemEnd = .pause
        show(Clip(player: player, looper: nil))
    }

    private func advance() {
        // A running transition decides what comes next when it ends
        guard transitionTarget == nil else { return }
        guard let loopState else {
            playLoop(target)
            return
        }
        if target != loopState { playTransition(from: loopState, to: target) }
    }

    private func playLoop(_ state: OrbState) {
        loopState = state
        transitionTarget = nil
        guard let url = Self.url("orb-\(state.rawValue)") else { return }
        let player = AVQueuePlayer()
        let looper = AVPlayerLooper(player: player, templateItem: AVPlayerItem(url: url))
        show(Clip(player: player, looper: looper))
    }

    private func playTransition(from: OrbState, to: OrbState) {
        guard !isPaused, let url = Self.url("transition-\(from.rawValue)-to-\(to.rawValue)") else {
            playLoop(to)
            return
        }
        loopState = nil
        transitionTarget = to
        let item = AVPlayerItem(url: url)
        let player = AVQueuePlayer(items: [item])
        // The last frame stays up until the next loop is ready; it matches that loop's first frame
        player.actionAtItemEnd = .pause
        let clip = Clip(player: player, looper: nil)
        clip.endObserver = NotificationCenter.default.addObserver(
            forName: AVPlayerItem.didPlayToEndTimeNotification, object: item, queue: .main
        ) { [weak self] _ in
            self?.transitionEnded(at: to)
        }
        show(clip)
    }

    private func transitionEnded(at state: OrbState) {
        guard transitionTarget == state else { return }
        transitionTarget = nil
        if target == state {
            playLoop(state)
        } else {
            playTransition(from: state, to: target)
        }
    }

    private func show(_ clip: Clip) {
        // A clip that never got to show is replaced by the newer one
        incoming?.stop()
        incoming = clip
        clip.player.isMuted = true
        clip.player.preventsDisplaySleepDuringVideoPlayback = false
        clip.layer.frame = clipFrame
        layer.addSublayer(clip.layer)
        clip.readyObserver = clip.layer.observe(\.isReadyForDisplay, options: [.initial, .new]) { [weak self, weak clip] layer, _ in
            guard layer.isReadyForDisplay else { return }
            DispatchQueue.main.async {
                guard let self, let clip else { return }
                self.reveal(clip)
            }
        }
        if !isPaused { clip.player.play() }
    }

    /// Crossfades to the clip once its first frame is ready, then stops the one it covers
    private func reveal(_ clip: Clip) {
        guard clip === incoming else { return }
        incoming = nil
        clip.readyObserver = nil
        let previous = visible
        visible = clip
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.12)
        clip.layer.opacity = 1
        previous?.layer.opacity = 0
        CATransaction.commit()

        if isOneShot, let item = clip.player.currentItem {
            onStart?(max(CMTimeGetSeconds(item.duration), 0))
        }
        if let previous {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { previous.stop() }
        }
    }

    private func updatePlayback() {
        for clip in [visible, incoming].compactMap({ $0 }) {
            if isPaused {
                clip.player.pause()
            } else {
                clip.player.play()
            }
        }
    }

    @objc private func resume() {
        if !isPaused { visible?.player.play() }
    }

    private static func url(_ name: String) -> URL? {
        Bundle.main.url(forResource: name, withExtension: "mov")
    }
}

/// Brand intro on launch: the star appears, stretches and bursts; the app shows up under the glow
struct LaunchOverlay: View {
    let onFinish: () -> Void

    @Environment(\.theme) private var theme
    @State private var coverOpacity = 1.0
    @State private var isFinished = false

    var body: some View {
        ZStack {
            theme.background
                .opacity(coverOpacity)
                .ignoresSafeArea()
            OrbView(once: "launch", onStart: start)
                .frame(width: 340, height: 340)
        }
        .allowsHitTesting(coverOpacity > 0.5)
        .task {
            // If the video can't start, don't keep the app covered
            try? await Task.sleep(for: .seconds(3))
            if coverOpacity == 1 { finish() }
        }
    }

    private func start(_ duration: Double) {
        // The burst begins at about 1.3 s: fade the cover out under it
        withAnimation(.easeInOut(duration: 0.5).delay(1.25)) { coverOpacity = 0 }
        Task {
            try? await Task.sleep(for: .seconds(max(duration, 2)))
            finish()
        }
    }

    private func finish() {
        guard !isFinished else { return }
        isFinished = true
        withAnimation(.easeOut(duration: 0.25)) { coverOpacity = 0 }
        onFinish()
    }
}

/// The CTA logo: mark and "CALL TO ACTION", plum on light, white on dark
struct LogoView: View {
    var height: CGFloat = 38

    var body: some View {
        Image("Wordmark")
            .resizable()
            .scaledToFit()
            .frame(height: height)
            .accessibilityLabel(Brand.name)
    }
}
