import Foundation

/// An error the OpenAI API returned, with its own message (for example "Incorrect API key provided")
struct OpenAIError: LocalizedError {
    let status: Int
    let message: String

    var errorDescription: String? { "OpenAI \(status): \(message)" }

    static func from(status: Int, body: Data) -> OpenAIError {
        struct Envelope: Decodable {
            struct Detail: Decodable { let message: String }
            let error: Detail
        }
        let message = (try? JSONDecoder().decode(Envelope.self, from: body).error.message)
            ?? String(data: body, encoding: .utf8)
            ?? "Unknown error"
        return OpenAIError(status: status, message: message)
    }
}

/// Real answers from OpenAI Chat Completions, streamed token by token
struct OpenAIChatService: ChatService {
    let apiKey: String
    let model: String

    func reply(to history: [Message], context: ChatContext) -> AsyncThrowingStream<String, Error> {
        let request: URLRequest
        do {
            request = try makeRequest(history: history, context: context)
        } catch {
            return AsyncThrowingStream { $0.finish(throwing: error) }
        }

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await URLSession.shared.bytes(for: request)
                    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                    guard status == 200 else {
                        var body = Data()
                        for try await byte in bytes { body.append(byte) }
                        throw OpenAIError.from(status: status, body: body)
                    }
                    // Server-sent events: "data: {json}" lines, ending with "data: [DONE]"
                    for try await line in bytes.lines {
                        guard line.hasPrefix("data:") else { continue }
                        let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        if payload == "[DONE]" { break }
                        if let chunk = Self.delta(in: payload), !chunk.isEmpty {
                            continuation.yield(chunk)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private func makeRequest(history: [Message], context: ChatContext) throws -> URLRequest {
        var messages: [[String: String]] = [["role": "system", "content": Self.systemPrompt(for: context)]]
        for message in history where !message.text.isEmpty {
            messages.append(["role": message.role == .user ? "user" : "assistant", "content": message.text])
        }
        let body: [String: Any] = ["model": model, "messages": messages, "stream": true]

        var request = URLRequest(url: URL(string: "https://api.openai.com/v1/chat/completions")!)
        request.httpMethod = "POST"
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        request.timeoutInterval = 60
        return request
    }

    private static func delta(in payload: String) -> String? {
        struct Chunk: Decodable {
            struct Choice: Decodable {
                struct Delta: Decodable { let content: String? }
                let delta: Delta
            }
            let choices: [Choice]
        }
        guard let data = payload.data(using: .utf8),
              let chunk = try? JSONDecoder().decode(Chunk.self, from: data) else { return nil }
        return chunk.choices.first?.delta.content
    }

    /// The conversation (or the list of all conversations) the user is asking about
    private static func systemPrompt(for context: ChatContext) -> String {
        var lines = [
            "You are an assistant inside an app where people review their recorded conversations: summaries, tasks to check and full transcripts.",
            "Answer in the language of the user's question. Be concise and use Markdown: short paragraphs, bullet lists, **bold** for names and key facts.",
        ]
        switch context.scope {
        case .conversation(let title):
            lines.append("The user is asking about the conversation \"\(title)\".")
            lines.append("Participants: \(context.people.joined(separator: ", ")).")
            lines.append("Summary:\n" + context.summary.map { "- \($0)" }.joined(separator: "\n"))
            if !context.tasks.isEmpty {
                lines.append("Open tasks:\n" + context.tasks.map { "- \($0)" }.joined(separator: "\n"))
            }
            lines.append("Transcript:\n" + context.transcript)
        case .allConversations(let titles):
            lines.append("The user is asking about all their conversations.")
            lines.append("Conversations, newest first:\n" + titles.map { "- \($0)" }.joined(separator: "\n"))
            if !context.tasks.isEmpty {
                lines.append("Open tasks:\n" + context.tasks.map { "- \($0)" }.joined(separator: "\n"))
            }
            if !context.people.isEmpty {
                lines.append("People and how many conversations you share:\n" + context.people.map { "- \($0)" }.joined(separator: "\n"))
            }
        }
        return lines.joined(separator: "\n\n")
    }
}

/// Speech-to-text through OpenAI's transcription endpoint
struct OpenAITranscriber: SpeechToText {
    let apiKey: String
    let model: String

    func transcribe(_ fileURL: URL) async throws -> String {
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        func field(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".data(using: .utf8)!)
        }
        field("model", model)
        field("response_format", "json")
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.m4a\"\r\nContent-Type: audio/m4a\r\n\r\n".data(using: .utf8)!)
        body.append(try Data(contentsOf: fileURL))
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        var request = URLRequest(url: URL(string: "https://api.openai.com/v1/audio/transcriptions")!)
        request.httpMethod = "POST"
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60

        let (data, response) = try await URLSession.shared.upload(for: request, from: body)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { throw OpenAIError.from(status: status, body: data) }

        struct Result: Decodable { let text: String }
        return try JSONDecoder().decode(Result.self, from: data).text
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
