import Foundation

/// Keys and models from Secrets.env (bundled for local testing) or from launch environment variables
enum AppConfig {
    private static let prefixes = ["OPENAI_", "ELEVENLABS_", "CALLCREW_"]

    private static let values: [String: String] = {
        var result: [String: String] = [:]
        if let url = Bundle.main.url(forResource: "Secrets", withExtension: "env"),
           let text = try? String(contentsOf: url, encoding: .utf8) {
            for line in text.split(whereSeparator: \.isNewline) {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                guard !trimmed.isEmpty, !trimmed.hasPrefix("#"), let equals = trimmed.firstIndex(of: "=") else { continue }
                let key = trimmed[..<equals].trimmingCharacters(in: .whitespaces)
                var value = trimmed[trimmed.index(after: equals)...].trimmingCharacters(in: .whitespaces)
                // Allow KEY="value" as well as KEY=value
                if value.count >= 2, let first = value.first, first == value.last, first == "\"" || first == "'" {
                    value = String(value.dropFirst().dropLast())
                }
                result[key] = value
            }
        }
        // Environment variables win over the file: the Xcode scheme (Run → Environment)
        // or SIMCTL_CHILD_… variables passed to `xcrun simctl launch`
        for (key, value) in ProcessInfo.processInfo.environment where prefixes.contains(where: key.hasPrefix) {
            result[key] = value
        }
        return result
    }()

    static func value(_ key: String) -> String? {
        guard let value = values[key]?.trimmingCharacters(in: .whitespaces), !value.isEmpty else { return nil }
        return value
    }

    // MARK: - OpenAI

    static var openAIKey: String? { value("OPENAI_API_KEY") }
    /// OPENAI_MODEL is the older name of the same setting
    static var chatModel: String { value("OPENAI_CHAT_MODEL") ?? value("OPENAI_MODEL") ?? "gpt-4.1-mini" }
    /// For search by meaning; not used by the app yet
    static var embedModel: String { value("OPENAI_EMBED_MODEL") ?? "text-embedding-3-small" }
    static var transcribeModel: String { value("OPENAI_TRANSCRIBE_MODEL") ?? "gpt-4o-mini-transcribe" }

    // MARK: - ElevenLabs

    static var elevenLabsKey: String? { value("ELEVENLABS_API_KEY") }
    static var elevenLabsSpeechModel: String { value("ELEVENLABS_STT_MODEL") ?? "scribe_v1" }

    // MARK: - Voice input

    /// Who turns speech into text: ElevenLabs or OpenAI when their key is set, otherwise Apple's recognizer on the phone
    static var transcriber: any SpeechToText {
        if let key = elevenLabsKey { return ElevenLabsTranscriber(apiKey: key, model: elevenLabsSpeechModel) }
        if let key = openAIKey { return OpenAITranscriber(apiKey: key, model: transcribeModel) }
        return AppleSpeechTranscriber()
    }

    static var voiceInputDescription: String {
        if elevenLabsKey != nil { return "ElevenLabs · \(elevenLabsSpeechModel)" }
        if openAIKey != nil { return "OpenAI · \(transcribeModel)" }
        #if targetEnvironment(simulator)
        return "iPhone only (needs a key here)"
        #else
        return "On device"
        #endif
    }
}
