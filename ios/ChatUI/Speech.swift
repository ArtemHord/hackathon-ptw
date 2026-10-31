import AVFoundation
import Observation
import Speech

/// Speech-to-text on the phone with Apple's recognizer: works without any API key.
/// The iOS 26 SpeechAnalyzer once its model is on the phone, SFSpeechRecognizer until then.
/// The Simulator runs neither (no speech model there): use an iPhone, or a cloud key in Secrets.env.
struct AppleSpeechTranscriber: SpeechToText {
    private final class Once: @unchecked Sendable {
        var done = false
    }

    struct Failure: LocalizedError {
        let errorDescription: String?
    }

    private static let language = Locale(identifier: "en-US")

    func transcribe(_ fileURL: URL) async throws -> String {
        let status = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard status == .authorized else {
            throw Failure(errorDescription: "Allow speech recognition in Settings to ask by voice.")
        }
        if let text = try? await analyze(fileURL) { return text }
        do {
            guard let recognizer = SFSpeechRecognizer(locale: Self.language), recognizer.isAvailable else {
                throw Failure(errorDescription: "Speech recognition isn't available right now.")
            }
            // On the phone when its model is there, otherwise Apple's server
            if recognizer.supportsOnDeviceRecognition,
               let text = try? await recognize(fileURL, with: recognizer, onDevice: true) {
                return text
            }
            return try await recognize(fileURL, with: recognizer, onDevice: false)
        } catch {
            #if targetEnvironment(simulator)
            throw Failure(errorDescription: "The Simulator has no speech model. Try it on an iPhone, or add ELEVENLABS_API_KEY or OPENAI_API_KEY to Secrets.env.")
            #else
            throw error
            #endif
        }
    }

    // MARK: SpeechAnalyzer (iOS 26)

    /// SpeechTranscriber where the device has it, DictationTranscriber otherwise (older iPhones, the simulator)
    private func analyze(_ fileURL: URL) async throws -> String {
        if Speech.SpeechTranscriber.isAvailable,
           let locale = await Speech.SpeechTranscriber.supportedLocale(equivalentTo: Self.language) {
            let module = Speech.SpeechTranscriber(locale: locale, preset: .transcription)
            return try await analyze(fileURL, with: module, results: module.results.map { String($0.text.characters) })
        }
        guard let locale = await DictationTranscriber.supportedLocale(equivalentTo: Self.language) else {
            throw Failure(errorDescription: "Speech recognition doesn't support English on this device.")
        }
        let module = DictationTranscriber(locale: locale, preset: .longDictation)
        return try await analyze(fileURL, with: module, results: module.results.map { String($0.text.characters) })
    }

    private func analyze<Results: AsyncSequence & Sendable>(
        _ fileURL: URL, with module: any SpeechModule, results: Results
    ) async throws -> String where Results.Element == String {
        // The language model downloads once, in the background; this question goes to the older recognizer meanwhile
        let status = await AssetInventory.status(forModules: [module])
        guard status == .installed else {
            if status == .supported {
                Task.detached { try? await AssetInventory.assetInstallationRequest(supporting: [module])?.downloadAndInstall() }
            }
            throw Failure(errorDescription: "The speech model isn't on this phone yet.")
        }
        guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [module]) else {
            throw Failure(errorDescription: "Speech recognition isn't available right now.")
        }
        let audio = try Self.read(fileURL, as: format)

        let analyzer = SpeechAnalyzer(modules: [module])
        let collector = Task {
            var text = ""
            for try await piece in results { text += piece }
            return text
        }
        let (input, feed) = AsyncStream<AnalyzerInput>.makeStream()
        feed.yield(AnalyzerInput(buffer: audio))
        feed.finish()
        if let end = try await analyzer.analyzeSequence(input) {
            try await analyzer.finalizeAndFinish(through: end)
        } else {
            await analyzer.cancelAndFinishNow()
        }
        return try await collector.value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// The whole recording as one buffer in the format the model takes (the app records 16 kHz AAC)
    private static func read(_ url: URL, as format: AVAudioFormat) throws -> AVAudioPCMBuffer {
        let file = try AVAudioFile(forReading: url)
        guard let source = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length)) else {
            throw Failure(errorDescription: "Couldn't read the recording.")
        }
        try file.read(into: source)
        if source.format == format { return source }

        let capacity = AVAudioFrameCount(Double(source.frameLength) * format.sampleRate / source.format.sampleRate) + 1024
        guard let converter = AVAudioConverter(from: source.format, to: format),
              let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else {
            throw Failure(errorDescription: "Couldn't convert the recording.")
        }
        var given = false
        var failure: NSError?
        let status = converter.convert(to: output, error: &failure) { _, inputStatus in
            if given {
                inputStatus.pointee = .endOfStream
                return nil
            }
            given = true
            inputStatus.pointee = .haveData
            return source
        }
        if status == .error { throw failure ?? Failure(errorDescription: "Couldn't convert the recording.") }
        return output
    }

    // MARK: SFSpeechRecognizer

    private func recognize(_ fileURL: URL, with recognizer: SFSpeechRecognizer, onDevice: Bool) async throws -> String {
        let request = SFSpeechURLRecognitionRequest(url: fileURL)
        request.shouldReportPartialResults = false
        request.requiresOnDeviceRecognition = onDevice

        let once = Once()
        return try await withCheckedThrowingContinuation { continuation in
            recognizer.recognitionTask(with: request) { result, error in
                guard !once.done else { return }
                if let result, result.isFinal {
                    once.done = true
                    continuation.resume(returning: result.bestTranscription.formattedString)
                } else if let error {
                    once.done = true
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}

/// Plays answers in the server's ElevenLabs voice (`POST /tts`)
@MainActor @Observable
final class SpeechPlayer: NSObject, AVAudioPlayerDelegate {
    private(set) var isLoading = false
    private(set) var isPlaying = false
    var errorMessage: String?

    @ObservationIgnored private var player: AVAudioPlayer?
    @ObservationIgnored private var request: Task<Void, Never>?

    func speak(_ text: String, using client: BackendClient) {
        stop()
        let spoken = Self.plain(text)
        guard !spoken.isEmpty else { return }
        isLoading = true
        request = Task {
            do {
                let audio = try await client.speech(spoken)
                guard !Task.isCancelled else { return }
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.playback, mode: .spokenAudio)
                try session.setActive(true)
                let player = try AVAudioPlayer(data: audio)
                player.delegate = self
                self.player = player
                isLoading = false
                isPlaying = player.play()
            } catch {
                guard !Task.isCancelled else { return }
                isLoading = false
                let backendError = error as? BackendError
                errorMessage = backendError?.status == 502
                    ? "The server has no voice set up (ElevenLabs)."
                    : "Couldn't play the answer. \(error.localizedDescription)"
            }
        }
    }

    func stop() {
        request?.cancel()
        request = nil
        player?.stop()
        player = nil
        isLoading = false
        isPlaying = false
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.isPlaying = false
            self.player = nil
        }
    }

    /// Markdown markers and the source list aren't read out loud
    private static func plain(_ text: String) -> String {
        let answer = text.components(separatedBy: "\n\n**Sources**").first ?? text
        return answer
            .replacingOccurrences(of: #"\[([^\]]+)\]\([^)]+\)"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"[*_`#>]"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
