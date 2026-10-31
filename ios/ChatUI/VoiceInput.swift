import AVFoundation
import Observation

/// Microphone input for spoken questions and dictation, transcribed on the phone (or by ElevenLabs / OpenAI when their key is set)
@MainActor @Observable
final class VoiceInput {
    enum Phase: Equatable { case idle, listening, transcribing }
    enum Purpose { case question, dictation }

    private(set) var phase: Phase = .idle
    private(set) var purpose: Purpose = .question
    /// Smoothed microphone level, 0…1
    private(set) var level: Double = 0
    var errorMessage: String?

    @ObservationIgnored private var recorder: AVAudioRecorder?
    @ObservationIgnored private var meterTask: Task<Void, Never>?
    @ObservationIgnored private var heardSpeech = false
    @ObservationIgnored private var quietSince: Date?
    @ObservationIgnored private var startedAt = Date.now
    @ObservationIgnored private var onText: ((String) -> Void)?

    /// Starts listening. When you stop (or pause after speaking), the speech is transcribed and passed to `onText`.
    func start(_ purpose: Purpose, onText: @escaping (String) -> Void) {
        guard phase == .idle else { return }
        self.purpose = purpose
        self.onText = onText
        Task { await begin() }
    }

    /// Stops listening and transcribes what was said
    func finish() {
        guard phase == .listening, let recorder else { return }
        let duration = recorder.currentTime
        let url = recorder.url
        stopRecording()
        guard heardSpeech || duration > 1 else {
            phase = .idle
            try? FileManager.default.removeItem(at: url)
            return
        }
        phase = .transcribing
        Task {
            defer { try? FileManager.default.removeItem(at: url) }
            do {
                let text = try await AppConfig.transcriber.transcribe(url)
                if !text.isEmpty { onText?(text) }
                phase = .idle
            } catch {
                phase = .idle
                errorMessage = "Couldn't recognize speech. \(error.localizedDescription)"
            }
        }
    }

    /// Stops listening and throws the recording away
    func cancel() {
        guard phase == .listening, let url = recorder?.url else { return }
        stopRecording()
        phase = .idle
        try? FileManager.default.removeItem(at: url)
    }

    private func begin() async {
        guard await AVAudioApplication.requestRecordPermission() else {
            errorMessage = "Allow microphone access in Settings to ask by voice."
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try session.setActive(true)

            let url = FileManager.default.temporaryDirectory.appendingPathComponent("voice-\(UUID().uuidString).m4a")
            let recorder = try AVAudioRecorder(url: url, settings: [
                AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
                AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: 1,
                AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue,
            ])
            recorder.isMeteringEnabled = true
            guard recorder.record() else {
                errorMessage = "Couldn't start the microphone."
                return
            }
            self.recorder = recorder
            heardSpeech = false
            quietSince = nil
            startedAt = .now
            phase = .listening
            meterTask = Task { [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .milliseconds(50))
                    self?.updateLevel()
                }
            }
        } catch {
            errorMessage = "Couldn't start the microphone. \(error.localizedDescription)"
        }
    }

    private func updateLevel() {
        guard phase == .listening, let recorder else { return }
        recorder.updateMeters()
        let power = Double(recorder.averagePower(forChannel: 0)) // −160…0 dB
        let normalized = min(1, max(0, (power + 50) / 42))
        level = level * 0.55 + normalized * 0.45

        // Finishes by itself after a short pause once you've said something
        if normalized > 0.3 {
            heardSpeech = true
            quietSince = nil
        } else if heardSpeech {
            if let since = quietSince {
                if Date.now.timeIntervalSince(since) > 1.6 { finish() }
            } else {
                quietSince = .now
            }
        }
        if Date.now.timeIntervalSince(startedAt) > 60 { finish() }
    }

    private func stopRecording() {
        meterTask?.cancel()
        meterTask = nil
        recorder?.stop()
        recorder = nil
        level = 0
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
