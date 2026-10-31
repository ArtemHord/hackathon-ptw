import SwiftUI

struct Person: Identifiable, Hashable {
    let name: String
    var role: String? = nil
    /// The owner the AI delegate stands in for
    var isOwner = false
    /// The AI delegate itself (Atlas)
    var isAgent = false

    var id: String { name }
    var initial: String { String(name.prefix(1)).uppercased() }

    /// The same person always gets the same color
    var color: Color {
        if isAgent { return Color(hex: 0xE0255E) }
        let palette: [UInt32] = [0xF58C33, 0x3380F2, 0xE6548C, 0x29A673, 0x9461F2, 0x1A99B3, 0x6B6B75]
        let hash = name.unicodeScalars.reduce(5381) { ($0 << 5) &+ $0 &+ Int($1.value) }
        return Color(hex: palette[abs(hash) % palette.count])
    }
}

/// One line of the transcript: what a participant said, or what the agent said in the call
struct Utterance: Identifiable, Hashable {
    let id: String
    let speaker: Person
    /// Seconds from the start of the call
    let offset: Int
    let text: String

    var timestamp: String { String(format: "%02d:%02d", offset / 60, offset % 60) }
}

/// An action item from the call
struct TaskItem: Identifiable, Hashable {
    let id: String
    var title: String
    var owner: Person?
    var due: String? = nil
    var jiraKey: String? = nil
    var jiraURL: URL? = nil
    /// Checked off on this device; the backend has no done state yet
    var isDone = false
}

/// The agent checked a claim against the knowledge base
struct FactCheck: Identifiable, Hashable {
    enum Verdict: String { case confirmed, contradicted, unverified }

    let id: String
    let claim: String
    let verdict: Verdict
    let source: String?
    let correction: String?
    let offset: Int
}

/// The agent didn't know and asked an expert (Slack / Telegram)
struct Escalation: Identifiable, Hashable {
    enum Status: String { case waiting, answered, timeout }

    let id: String
    let expert: String?
    let channel: String?
    let question: String
    let askedBy: String?
    let offset: Int
    let status: Status
    let answer: String?
}

enum CallStatus: String, Hashable {
    case scheduled, joining, inCall = "in_call", done, failed

    var isLive: Bool { self == .joining || self == .inCall }

    var label: String {
        switch self {
        case .scheduled: "Scheduled"
        case .joining: "Joining…"
        case .inCall: "Live"
        case .done: "Done"
        case .failed: "Failed"
        }
    }
}

/// A recorded call: summary, decisions, tasks, fact-checks, questions to experts and the transcript
struct Conversation: Identifiable, Hashable {
    let id: String
    var title: String
    var date: Date
    var minutes: Int?
    var status: CallStatus = .done
    var platform: String? = nil
    var mode: String? = nil
    /// Markdown from the post-call step; empty until it is ready
    var summary: String = ""
    var decisions: [String] = []
    var tasks: [TaskItem] = []
    var factChecks: [FactCheck] = []
    var escalations: [Escalation] = []
    var transcript: [Utterance] = []
    /// The full call was fetched (not only the list row)
    var isDetailLoaded = false
    var messages: [Message] = []

    var isLive: Bool { status.isLive }

    /// Ended a while ago and still no summary: it isn't coming (no AI on the server, or it failed)
    var summaryIsLate: Bool {
        status == .done && summary.isEmpty
            && date.addingTimeInterval(Double((minutes ?? 0) * 60 + 180)) < .now
    }

    /// Everyone who spoke, except the agent
    var people: [Person] {
        var seen = Set<String>()
        return transcript.map(\.speaker).filter { !$0.isAgent && seen.insert($0.id).inserted }
    }

    /// The call's platform stands in for a project
    var project: String? { platform.map(Self.platformName) }

    var displayTitle: String {
        title.trimmingCharacters(in: .whitespaces).isEmpty ? "Untitled call" : title
    }

    var metaLine: String {
        var parts = [date.formatted(.dateTime.month(.abbreviated).day().hour().minute())]
        if status == .failed {
            parts.append(status.label)
        } else if !isLive, let minutes {
            parts.append("\(minutes) min")
        }
        if let project { parts.append(project) }
        return parts.joined(separator: " · ")
    }

    var shareText: String {
        var lines = [displayTitle, metaLine]
        if !summary.isEmpty { lines += ["", "Summary", summary] }
        if !decisions.isEmpty {
            lines += ["", "Decisions"]
            lines += decisions.map { "• \($0)" }
        }
        if !tasks.isEmpty {
            lines += ["", "Tasks to check"]
            lines += tasks.map { task in
                (task.isDone ? "☑ " : "☐ ") + task.title + (task.owner.map { " — \($0.name)" } ?? "")
            }
        }
        lines += ["", "Transcript"]
        lines += transcript.map { "[\($0.timestamp)] \($0.speaker.name): \($0.text)" }
        return lines.joined(separator: "\n")
    }

    static func platformName(_ platform: String) -> String {
        switch platform {
        case "google_meet": "Google Meet"
        case "zoom": "Zoom"
        case "teams", "microsoft_teams": "Microsoft Teams"
        default: platform.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
}

struct Message: Identifiable, Hashable {
    enum Role: Hashable { case user, assistant }
    enum Feedback: Hashable { case liked, disliked }

    let id = UUID()
    let role: Role
    var text: String
    var feedback: Feedback? = nil
}

enum SidebarSection: String, CaseIterable, Identifiable, Hashable {
    case calendar, projects, people, tasks, knowledge

    var id: Self { self }
    var title: String { rawValue.capitalized }

    var icon: String {
        switch self {
        case .calendar: "calendar"
        case .projects: "folder"
        case .people: "person.2"
        case .tasks: "checklist"
        case .knowledge: "book"
        }
    }
}
