import Foundation

/// What the assistant knows about one call (or all of them)
struct ChatContext: Sendable {
    enum Scope: Sendable {
        case conversation(title: String)
        case allConversations(titles: [String])
    }

    var scope: Scope
    var summary: [String] = []
    var tasks: [String] = []
    var people: [String] = []
    var transcript: String = ""
    /// Call titles by id, to name the calls an answer cites
    var titles: [String: String] = [:]
}

/// Where answers come from: the Call Crew backend, OpenAI directly, or the offline demo
protocol ChatService: Sendable {
    /// The answer arrives in chunks — that's how the text "types itself" out
    func reply(to history: [Message], context: ChatContext) -> AsyncThrowingStream<String, Error>
}

/// Splits text after spaces and line breaks, for the typing effect
private func wordChunks(of text: String) -> [String] {
    var result: [String] = []
    var current = ""
    for character in text {
        current.append(character)
        if character == " " || character == "\n" {
            result.append(current)
            current = ""
        }
    }
    if !current.isEmpty { result.append(current) }
    return result
}

/// Answers from the backend's `POST /chat`: it searches every call and the knowledge base, and cites them
struct BackendChatService: ChatService {
    let client: BackendClient

    func reply(to history: [Message], context: ChatContext) -> AsyncThrowingStream<String, Error> {
        let question = history.last { $0.role == .user }?.text ?? ""
        // The backend searches all calls; naming the call keeps the answer about it
        let asked = switch context.scope {
        case .conversation(let title): "About the call “\(title)”: \(question)"
        case .allConversations: question
        }
        let client = client
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let response = try await client.chat(asked)
                    let text = response.answer + Self.sources(response.citations ?? [], titles: context.titles)
                    for chunk in wordChunks(of: text) {
                        if Task.isCancelled { break }
                        continuation.yield(chunk)
                        try? await Task.sleep(for: .milliseconds(Int.random(in: 10...26)))
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// Quotes from calls link back to the call (`cta://meeting/<id>`); documents are named with their version
    private static func sources(_ citations: [ChatResponseDTO.Citation], titles: [String: String]) -> String {
        var seen = Set<String>()
        let lines: [String] = citations.compactMap { citation in
            if citation.type == "document" {
                let title = citation.title ?? "Document"
                guard seen.insert("doc-\(citation.doc_id ?? title)").inserted else { return nil }
                return "- \(title)" + (citation.version.map { " (v\($0))" } ?? "")
            }
            guard let id = citation.meeting_id else { return nil }
            let seconds = Int(citation.ts ?? 0)
            guard seen.insert("\(id)-\(seconds)").inserted else { return nil }
            let call = titles[id] ?? "A call"
            let time = String(format: "%02d:%02d", seconds / 60, seconds % 60)
            var line = "- [\(call) · \(time)](cta://meeting/\(id))"
            if let text = citation.text, !text.isEmpty {
                let quote = text.count > 90 ? String(text.prefix(90)) + "…" : text
                line += " — " + (citation.speaker.map { "\($0): " } ?? "") + "“\(quote)”"
            }
            return line
        }
        guard !lines.isEmpty else { return "" }
        return "\n\n**Sources**\n" + lines.prefix(5).joined(separator: "\n")
    }
}

/// No backend and no demo data: tell the user where to connect instead of making something up
struct NotConnectedChatService: ChatService {
    struct NotConnected: LocalizedError {
        var errorDescription: String? { "Connect the backend first: Settings → Backend (server + DEMO_TOKEN)." }
    }

    func reply(to history: [Message], context: ChatContext) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { $0.finish(throwing: NotConnected()) }
    }
}

/// Demo service without a network: builds an answer from the summary and tasks and streams it word by word
struct MockChatService: ChatService {
    func reply(to history: [Message], context: ChatContext) -> AsyncThrowingStream<String, Error> {
        let answer = Self.answer(for: history.last?.text ?? "", context: context)
        return AsyncThrowingStream { continuation in
            let task = Task {
                // "Thinks" before the first word
                try? await Task.sleep(for: .milliseconds(650))
                for chunk in wordChunks(of: answer) {
                    if Task.isCancelled { break }
                    continuation.yield(chunk)
                    try? await Task.sleep(for: .milliseconds(Int.random(in: 16...42)))
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private static let footnote = "*This is a demo answer. Connect the backend in Settings to get real ones.*"

    private static func answer(for prompt: String, context: ChatContext) -> String {
        let words = prompt.lowercased().split { !$0.isLetter }.map(String.init)
        // A word starts with one of the stems, so "task" also matches "tasks"
        let mentions = { (stems: [String]) in words.contains { word in stems.contains { word.hasPrefix($0) } } }
        let bullets = { (items: [String]) in items.map { "- \($0)" }.joined(separator: "\n") }

        if mentions(["task", "todo", "action", "deadline"]) {
            let list = context.tasks.isEmpty ? "No open tasks." : bullets(context.tasks)
            return "## Tasks to check\n\n\(list)\n\n\(footnote)"
        }

        if words.contains("who") || mentions(["people", "person", "participant", "attendee"]) {
            switch context.scope {
            case .conversation:
                return "## Participants\n\n\(bullets(context.people))\n\n\(footnote)"
            case .allConversations:
                return "## Who you talk to most\n\nShared calls:\n\n\(bullets(context.people))\n\n\(footnote)"
            }
        }

        switch context.scope {
        case .conversation(let title):
            return """
            Here's a quick recap of “\(title)”:

            \(bullets(context.summary))

            I can list the tasks or tell you who said what.

            \(footnote)
            """
        case .allConversations(let titles):
            return """
            You have \(titles.count) \(titles.count == 1 ? "call" : "calls"). The latest:

            \(bullets(Array(titles.prefix(3))))

            Open tasks: **\(context.tasks.count)**. I can list them or summarize any call.

            \(footnote)
            """
        }
    }
}
