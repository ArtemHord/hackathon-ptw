import Foundation
import Security

// The Call Crew backend (docs/API.pl.md, mocks/*.json): REST with a Bearer DEMO_TOKEN, one WebSocket per live call.
// The app never holds OpenAI, ElevenLabs or Recall keys — the server does.

/// Where the backend is and how to sign in
struct BackendSettings: Equatable, Sendable {
    var baseURL: URL
    var token: String

    static let productionURL = URL(string: "https://hackathon-ptw-production.up.railway.app")!

    /// Launch environment / Secrets.env first (CALLCREW_BASE_URL, CALLCREW_DEMO_TOKEN), then what Settings saved
    static func load() -> BackendSettings? {
        if let token = AppConfig.value("CALLCREW_DEMO_TOKEN") {
            let url = AppConfig.value("CALLCREW_BASE_URL").flatMap(URL.init(string:)) ?? productionURL
            return BackendSettings(baseURL: url, token: token)
        }
        guard let token = Keychain.read(account: "demo-token") else { return nil }
        let url = UserDefaults.standard.string(forKey: "backendURL").flatMap(URL.init(string:)) ?? productionURL
        return BackendSettings(baseURL: url, token: token)
    }

    func save() {
        UserDefaults.standard.set(baseURL.absoluteString, forKey: "backendURL")
        Keychain.write(token, account: "demo-token")
    }

    static func clear() {
        Keychain.delete(account: "demo-token")
    }
}

/// The demo token lives in the Keychain, not in UserDefaults
enum Keychain {
    private static let service = "com.example.ChatUI.backend"

    static func read(account: String) -> String? {
        var item: CFTypeRef?
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func write(_ value: String, account: String) {
        delete(account: account)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    static func delete(account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}

/// An error from the backend: `{"error": {"code", "message"}}`, or a plain status
struct BackendError: LocalizedError {
    let status: Int
    let code: String?
    let message: String

    var isUnauthorized: Bool { status == 401 }
    var errorDescription: String? { message }

    static func from(status: Int, body: Data) -> BackendError {
        struct Envelope: Decodable {
            struct Detail: Decodable { let code: String?; let message: String? }
            let error: Detail
        }
        if let envelope = try? JSONDecoder().decode(Envelope.self, from: body) {
            return BackendError(status: status, code: envelope.error.code, message: envelope.error.message ?? "Error \(status)")
        }
        if status == 401 { return BackendError(status: status, code: "unauthorized", message: "Wrong token") }
        let text = String(data: body, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return BackendError(status: status, code: nil, message: text.isEmpty ? "Server error \(status)" : "Server error \(status): \(text.prefix(120))")
    }
}

// MARK: - Response shapes

struct MeetingDTO: Decodable, Sendable {
    let id: String
    let title: String?
    let platform: String?
    let mode: String?
    let status: String?
    let started_at: String?
    let duration_min: Int?
}

struct MeetingDetailDTO: Decodable, Sendable {
    let id: String
    let title: String?
    let platform: String?
    let mode: String?
    let status: String?
    let started_at: String?
    let duration_min: Int?
    let summary: String?
    let decisions: [String]?
    let action_items: [ActionItemDTO]?
    let fact_checks: [FactCheckDTO]?
    let escalations: [EscalationDTO]?
    let utterances: [UtteranceDTO]?
    let agent_said: [AgentSaidDTO]?
}

struct UtteranceDTO: Decodable, Sendable {
    let id: String
    let speaker: String?
    let text: String
    let ts: Double?
}

struct AgentSaidDTO: Decodable, Sendable {
    let id: String
    let text: String
    let ts: Double?
    let in_reply_to: String?
}

struct ActionItemDTO: Decodable, Sendable {
    let id: String
    let owner: String?
    let text: String
    let due: String?
    let jira_key: String?
    let jira_url: String?
}

struct FactCheckDTO: Decodable, Sendable {
    let id: String
    let claim: String
    let verdict: String?
    let source: String?
    let correction: String?
    let ts: Double?
}

struct EscalationDTO: Decodable, Sendable {
    let id: String
    let expert: String?
    let channel: String?
    let question: String
    let asked_by: String?
    let ts: Double?
    let status: String?
    let answer: String?
}

struct ExpertDTO: Decodable, Sendable {
    let id: String
    let name: String
    let role: String?
    let is_owner: Bool?
}

struct ChatResponseDTO: Decodable, Sendable {
    struct Citation: Decodable, Sendable {
        let type: String
        let meeting_id: String?
        let ts: Double?
        let speaker: String?
        let text: String?
        let doc_id: String?
        let title: String?
        let version: Int?
    }

    let answer: String
    let citations: [Citation]?
}

// MARK: - REST

struct BackendClient: Sendable {
    let settings: BackendSettings

    func meetings() async throws -> [MeetingDTO] {
        struct List: Decodable { let items: [MeetingDTO] }
        let list: List = try await request("GET", "/meetings")
        return list.items
    }

    func meeting(_ id: String) async throws -> MeetingDetailDTO {
        try await request("GET", "/meetings/\(id)")
    }

    func experts() async throws -> [ExpertDTO] {
        struct List: Decodable { let items: [ExpertDTO] }
        let list: List = try await request("GET", "/experts")
        return list.items
    }

    func chat(_ question: String) async throws -> ChatResponseDTO {
        try await request("POST", "/chat", body: ["question": String(question.prefix(500))])
    }

    /// mp3 spoken by the server's ElevenLabs voice
    func speech(_ text: String) async throws -> Data {
        try await raw("POST", "/tts", body: ["text": String(text.prefix(1000))])
    }

    /// A demo call without Zoom or Meet: the backend replays a stand-up through its real webhooks
    func simulateCall(speed: Double) async throws -> String {
        struct Started: Decodable { let meeting_id: String }
        let body = SimulateBody(speed: speed, expert_reply: nil)
        let started: Started = try await request("POST", "/debug/simulate", body: body)
        return started.meeting_id
    }

    /// Answers a waiting escalation as the expert would on Slack
    func replyAsExpert(escalationID: String, text: String) async throws {
        let _: EmptyResponse = try await request("POST", "/debug/expert-reply", body: ["escalation_id": escalationID, "text": text])
    }

    /// Sends the Recall bot into a real Meet / Zoom / Teams call
    func joinCall(url: String, mode: String, brief: String?) async throws -> MeetingDTO {
        var body = ["meeting_url": url, "mode": mode]
        if let brief, !brief.isEmpty { body["brief"] = brief }
        return try await request("POST", "/meetings", body: body)
    }

    func leave(_ id: String) async throws {
        let _: EmptyResponse = try await request("POST", "/meetings/\(id)/leave")
    }

    func liveURL(meetingID: String) -> URL? {
        guard var components = URLComponents(url: settings.baseURL, resolvingAgainstBaseURL: false) else { return nil }
        components.scheme = components.scheme == "http" ? "ws" : "wss"
        components.path = (components.path.hasSuffix("/") ? String(components.path.dropLast()) : components.path) + "/app/ws"
        // URLQueryItem leaves "+" as is, and the server reads it as a space: encode everything but unreserved characters
        let unreserved = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        components.percentEncodedQueryItems = [
            URLQueryItem(name: "meeting_id", value: meetingID.addingPercentEncoding(withAllowedCharacters: unreserved)),
            URLQueryItem(name: "token", value: settings.token.addingPercentEncoding(withAllowedCharacters: unreserved)),
        ]
        return components.url
    }

    // MARK: Plumbing

    private struct EmptyResponse: Decodable {}

    private struct SimulateBody: Encodable {
        let speed: Double
        let expert_reply: String?

        private enum CodingKeys: String, CodingKey { case speed, expert_reply }

        func encode(to encoder: Encoder) throws {
            var container = encoder.container(keyedBy: CodingKeys.self)
            try container.encode(speed, forKey: .speed)
            // An explicit null keeps the call open so the expert can be answered by hand
            try container.encode(expert_reply, forKey: .expert_reply)
        }
    }

    private func request<T: Decodable>(_ method: String, _ path: String, body: (any Encodable)? = nil) async throws -> T {
        let data = try await raw(method, path, body: body)
        return try JSONDecoder().decode(T.self, from: data.isEmpty ? Data("{}".utf8) : data)
    }

    private func raw(_ method: String, _ path: String, body: (any Encodable)? = nil) async throws -> Data {
        var request = URLRequest(url: settings.baseURL.appending(path: path))
        request.httpMethod = method
        request.timeoutInterval = 30
        request.setValue("Bearer \(settings.token)", forHTTPHeaderField: "Authorization")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw BackendError.from(status: status, body: data) }
        return data
    }
}

// MARK: - Live events

/// One message from `/app/ws`: `{type, meeting_id, ts, data}`
enum LiveEvent: Sendable {
    case utterance(UtteranceDTO)
    case agentSaid(AgentSaidDTO)
    case factCheck(FactCheckDTO)
    case escalation(EscalationDTO)
    case status(String)
    case ended(status: String?, durationMin: Int?)

    static func decode(_ data: Data) -> LiveEvent? {
        struct Envelope: Decodable { let type: String }
        struct Wrapped<T: Decodable>: Decodable { let data: T }
        struct Status: Decodable { let status: String }
        struct Ended: Decodable { let status: String?; let duration_min: Int? }
        let decoder = JSONDecoder()
        guard let type = try? decoder.decode(Envelope.self, from: data).type else { return nil }
        switch type {
        case "utterance":
            return (try? decoder.decode(Wrapped<UtteranceDTO>.self, from: data)).map { .utterance($0.data) }
        case "agent_said":
            return (try? decoder.decode(Wrapped<AgentSaidDTO>.self, from: data)).map { .agentSaid($0.data) }
        case "fact_check":
            return (try? decoder.decode(Wrapped<FactCheckDTO>.self, from: data)).map { .factCheck($0.data) }
        case "escalation_created", "escalation_answered":
            return (try? decoder.decode(Wrapped<EscalationDTO>.self, from: data)).map { .escalation($0.data) }
        case "meeting_status":
            return (try? decoder.decode(Wrapped<Status>.self, from: data)).map { .status($0.data.status) }
        case "meeting_ended":
            return (try? decoder.decode(Wrapped<Ended>.self, from: data)).map { .ended(status: $0.data.status, durationMin: $0.data.duration_min) }
        default:
            return nil
        }
    }
}

/// WebSocket to one live call. Reconnects every 3 s unless the server rejects the token (close code 4401).
@MainActor
final class LiveFeed {
    let meetingID: String
    private let url: URL
    private let onEvent: (LiveEvent) -> Void
    private let onRejected: () -> Void
    private var task: URLSessionWebSocketTask?
    private var isStopped = false

    init(meetingID: String, url: URL, onEvent: @escaping (LiveEvent) -> Void, onRejected: @escaping () -> Void) {
        self.meetingID = meetingID
        self.url = url
        self.onEvent = onEvent
        self.onRejected = onRejected
        connect()
    }

    func stop() {
        isStopped = true
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
    }

    private func connect() {
        guard !isStopped else { return }
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        receive(on: task)
    }

    private func receive(on task: URLSessionWebSocketTask) {
        task.receive { [weak self] result in
            Task { @MainActor in
                guard let self, !self.isStopped, self.task === task else { return }
                switch result {
                case .success(let message):
                    let data: Data? = switch message {
                    case .string(let text): Data(text.utf8)
                    case .data(let data): data
                    @unknown default: nil
                    }
                    if let data, let event = LiveEvent.decode(data) { self.onEvent(event) }
                    self.receive(on: task)
                case .failure:
                    if task.closeCode.rawValue == 4401 {
                        self.onRejected()
                        return
                    }
                    try? await Task.sleep(for: .seconds(3))
                    self.connect()
                }
            }
        }
    }
}
