import Foundation

/// Turns a recorded file into text
protocol SpeechToText: Sendable {
    func transcribe(_ fileURL: URL) async throws -> String
}

/// An error ElevenLabs returned, with its own message
struct ElevenLabsError: LocalizedError {
    let status: Int
    let message: String

    var errorDescription: String? { "ElevenLabs \(status): \(message)" }

    static func from(status: Int, body: Data) -> ElevenLabsError {
        // Errors come as {"detail": {"message": …}} or {"detail": "…"}
        let json = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
        let detail = json?["detail"]
        let message = (detail as? [String: Any])?["message"] as? String
            ?? detail as? String
            ?? String(data: body, encoding: .utf8)
            ?? "Unknown error"
        return ElevenLabsError(status: status, message: message)
    }
}

/// Speech-to-text with ElevenLabs Scribe
struct ElevenLabsTranscriber: SpeechToText {
    let apiKey: String
    let model: String

    func transcribe(_ fileURL: URL) async throws -> String {
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        func field(_ name: String, _ value: String) {
            body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
        }
        field("model_id", model)
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.m4a\"\r\nContent-Type: audio/m4a\r\n\r\n".utf8))
        body.append(try Data(contentsOf: fileURL))
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))

        var request = URLRequest(url: URL(string: "https://api.elevenlabs.io/v1/speech-to-text")!)
        request.httpMethod = "POST"
        request.setValue(apiKey, forHTTPHeaderField: "xi-api-key")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60

        let (data, response) = try await URLSession.shared.upload(for: request, from: body)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { throw ElevenLabsError.from(status: status, body: data) }

        struct Result: Decodable { let text: String }
        return try JSONDecoder().decode(Result.self, from: data).text
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
