import SwiftUI

/// Call overview: title, participants, the agent while the call is live, summary, decisions, tasks,
/// questions to experts, fact-checks and the transcript
struct ConversationOverview: View {
    let conversation: Conversation
    let store: ConversationStore

    @Environment(\.theme) private var theme
    @State private var replyingTo: Escalation?
    @State private var replyText = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            header

            if conversation.isLive {
                LiveAgentCard(status: conversation.status, mode: conversation.mode, activity: store.agentActivity)
            }

            section("Summary") { summary }

            if !conversation.decisions.isEmpty {
                section("Decisions") {
                    MarkdownView(text: conversation.decisions.map { "- \($0)" }.joined(separator: "\n"))
                }
            }

            if !conversation.tasks.isEmpty {
                section("Tasks to check") {
                    VStack(alignment: .leading, spacing: 14) {
                        ForEach(conversation.tasks) { task in
                            TaskRow(task: task) { store.toggleTask(task.id) }
                        }
                    }
                }
            }

            if !conversation.escalations.isEmpty {
                section("Asked experts") {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(conversation.escalations) { escalation in
                            EscalationCard(escalation: escalation, canReply: store.usesBackend) {
                                replyText = ""
                                replyingTo = escalation
                            }
                        }
                    }
                }
            }

            if !conversation.factChecks.isEmpty {
                section("Fact checks") {
                    VStack(alignment: .leading, spacing: 16) {
                        ForEach(conversation.factChecks) { FactCheckRow(check: $0) }
                    }
                }
            }

            section("Transcript") { transcript }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .alert(
            "Reply as \(replyingTo?.expert ?? "the expert")",
            isPresented: Binding(get: { replyingTo != nil }, set: { if !$0 { replyingTo = nil } })
        ) {
            TextField("Answer", text: $replyText)
            Button("Send") {
                let text = replyText.trimmingCharacters(in: .whitespacesAndNewlines)
                guard let escalation = replyingTo, !text.isEmpty else { return }
                Task { await store.replyAsExpert(escalation, text: text) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text((conversation.isLive ? "Atlas will say the answer in the call." : "The call has ended, so the answer is saved with it.")
                + "\n\n“\(replyingTo?.question ?? "")”")
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(theme.headlineText(conversation.displayTitle))
                .font(theme.headline(26))
                .lineSpacing(theme.wideHeadlines ? 4 : 0)
            HStack(spacing: 8) {
                if conversation.isLive { LiveBadge(status: conversation.status) }
                Text(conversation.metaLine)
                    .font(.onest(15))
                    .foregroundStyle(theme.secondaryText)
            }
            if !conversation.people.isEmpty {
                HStack(spacing: 10) {
                    AvatarStack(people: Array(conversation.people.prefix(6)), size: 26)
                    Text(conversation.people.map(\.name).joined(separator: ", "))
                        .font(.onest(15))
                        .foregroundStyle(theme.secondaryText)
                        .lineLimit(1)
                }
                .padding(.top, 2)
            }
        }
    }

    @ViewBuilder
    private var summary: some View {
        if !conversation.summary.isEmpty {
            MarkdownView(text: conversation.summary)
        } else if conversation.isLive {
            Note(icon: "text.append", text: "The summary, decisions and tasks appear when the call ends.")
        } else if conversation.status == .failed {
            Note(icon: "exclamationmark.triangle", text: "The agent couldn't join this call.")
        } else if conversation.status == .done && conversation.isDetailLoaded {
            // Checked again every few seconds: after a while without a summary, stop promising one
            TimelineView(.periodic(from: .now, by: 10)) { _ in
                if conversation.summaryIsLate {
                    Note(icon: "text.badge.xmark", text: "No summary for this call.")
                } else {
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Writing the summary…")
                            .font(.onest(16))
                            .foregroundStyle(theme.secondaryText)
                    }
                }
            }
        } else {
            ProgressView()
        }
    }

    @ViewBuilder
    private var transcript: some View {
        if conversation.transcript.isEmpty {
            Note(
                icon: "waveform",
                text: conversation.isLive ? "Waiting for the first words…" : (conversation.isDetailLoaded ? "No transcript." : "Loading…")
            )
        } else {
            LazyVStack(alignment: .leading, spacing: 22) {
                ForEach(conversation.transcript) { UtteranceView(utterance: $0) }
            }
        }
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title)
            content()
        }
    }
}

/// A gray line with an icon: placeholders while something is on its way
private struct Note: View {
    let icon: String
    let text: String
    @Environment(\.theme) private var theme

    var body: some View {
        Label {
            Text(text).font(.onest(16))
        } icon: {
            Image(systemName: icon).font(.system(size: 15))
        }
        .foregroundStyle(theme.secondaryText)
    }
}

/// The red LIVE (or JOINING) mark of a call that is happening now
struct LiveBadge: View {
    let status: CallStatus
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(.red)
                .frame(width: 7, height: 7)
                .opacity(pulse ? 0.35 : 1)
                .animation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true), value: pulse)
                .onAppear { pulse = true }
            Text(status == .joining ? "JOINING" : "LIVE")
                .font(.onest(12, .semibold))
                .tracking(0.6)
        }
        .foregroundStyle(.red)
        .padding(.horizontal, 8)
        .frame(height: 22)
        .background(.red.opacity(0.1), in: .capsule)
    }
}

/// The agent in the call: the orb follows what it is doing
private struct LiveAgentCard: View {
    let status: CallStatus
    let mode: String?
    let activity: OrbState
    @Environment(\.theme) private var theme

    private var title: String {
        if status == .joining { return "\(ConversationStore.agentName) is joining the call…" }
        switch activity {
        case .thinking: return "\(ConversationStore.agentName) is thinking…"
        case .speaking: return "\(ConversationStore.agentName) is answering…"
        case .idle, .listening: return "\(ConversationStore.agentName) is listening"
        }
    }

    private var detail: String {
        mode == "delegate"
            ? "Say “\(ConversationStore.agentName), …” in the call to ask. Questions it can't answer go to an expert."
            : "Taking notes. The summary and tasks appear when the call ends."
    }

    var body: some View {
        HStack(spacing: 14) {
            OrbView(state: status == .joining ? .thinking : activity, zoom: 1.4)
                .frame(width: 64, height: 64)
                .padding(-6)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.onest(17, .semibold))
                    .contentTransition(.opacity)
                Text(detail)
                    .font(.onest(14))
                    .foregroundStyle(theme.secondaryText)
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .background(theme.card, in: .rect(cornerRadius: 22, style: .continuous))
        .animation(.smooth, value: activity)
    }
}

/// A question the agent couldn't answer and sent to an expert
private struct EscalationCard: View {
    let escalation: Escalation
    let canReply: Bool
    let onReply: () -> Void
    @Environment(\.theme) private var theme

    private var channel: String {
        switch escalation.channel {
        case "slack": "Slack"
        case "telegram": "Telegram"
        case let other?: other.capitalized
        case nil: "chat"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .foregroundStyle(iconColor)
                Text(statusLine)
                    .font(.onest(14, .medium))
                    .foregroundStyle(theme.secondaryText)
            }
            Text("“\(escalation.question)”")
                .font(.onest(17))
            if let answer = escalation.answer, !answer.isEmpty {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: "arrowshape.turn.up.left.fill")
                        .font(.system(size: 13))
                        .foregroundStyle(theme.accent)
                    Text(answer)
                        .font(.onest(16))
                }
            }
            if escalation.status == .waiting && canReply {
                Button(action: onReply) {
                    Label("Reply as \(escalation.expert ?? "expert")", systemImage: "arrowshape.turn.up.left")
                        .font(.onest(15, .semibold))
                        .foregroundStyle(theme.onAccent)
                        .padding(.horizontal, 14)
                        .frame(height: 36)
                        .background(theme.accent, in: .capsule)
                }
                .buttonStyle(.plain)
                .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(theme.card, in: .rect(cornerRadius: 20, style: .continuous))
    }

    private var statusLine: String {
        let who = escalation.expert ?? "an expert"
        switch escalation.status {
        case .waiting: return "Waiting for \(who) on \(channel)"
        case .answered: return "\(who) answered on \(channel)"
        case .timeout: return "\(who) didn't answer in time"
        }
    }

    private var icon: String {
        switch escalation.status {
        case .waiting: "clock"
        case .answered: "checkmark.bubble"
        case .timeout: "clock.badge.xmark"
        }
    }

    private var iconColor: Color {
        switch escalation.status {
        case .waiting: .orange
        case .answered: .green
        case .timeout: .secondary
        }
    }
}

/// A claim from the call checked against the knowledge base
private struct FactCheckRow: View {
    let check: FactCheck
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 17))
                .foregroundStyle(color)
            VStack(alignment: .leading, spacing: 4) {
                Text(check.claim)
                    .font(.onest(17))
                if let correction = check.correction, !correction.isEmpty {
                    Text(correction)
                        .font(.onest(15))
                        .foregroundStyle(.primary.opacity(0.8))
                }
                Text([label, check.source].compactMap { $0 }.joined(separator: " · "))
                    .font(.onest(14))
                    .foregroundStyle(theme.secondaryText)
            }
        }
    }

    private var label: String {
        switch check.verdict {
        case .confirmed: "Confirmed"
        case .contradicted: "Contradicted"
        case .unverified: "Not verified"
        }
    }

    private var icon: String {
        switch check.verdict {
        case .confirmed: "checkmark.seal.fill"
        case .contradicted: "xmark.seal.fill"
        case .unverified: "questionmark.circle"
        }
    }

    private var color: Color {
        switch check.verdict {
        case .confirmed: .green
        case .contradicted: .red
        case .unverified: theme.secondaryText
        }
    }
}

/// Utterance: avatar, name and time, with the text below. The agent's lines are marked as AI.
struct UtteranceView: View {
    let utterance: Utterance
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Avatar(person: utterance.speaker, size: 22)
                Text(utterance.speaker.name)
                    .font(.onest(15, .semibold))
                if utterance.speaker.isAgent {
                    Text("AI")
                        .font(.onest(11, .bold))
                        .foregroundStyle(theme.accent)
                        .padding(.horizontal, 6)
                        .frame(height: 18)
                        .background(theme.accent.opacity(0.12), in: .capsule)
                }
                Text(utterance.timestamp)
                    .font(.onest(13))
                    .monospacedDigit()
                    .foregroundStyle(theme.secondaryText)
            }
            Text(Markdown.inline(utterance.text))
                .font(.onest(17))
                .lineSpacing(4)
                .tint(.primary)
                .padding(.leading, 30)
        }
    }
}

struct TaskRow: View {
    let task: TaskItem
    let onToggle: () -> Void

    @Environment(\.theme) private var theme

    private var details: String? {
        let parts = [task.owner?.name, task.due.map { "due \($0)" }].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Button(action: onToggle) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Image(systemName: task.isDone ? "checkmark.circle.fill" : "circle")
                        .font(.system(size: 20))
                        .foregroundStyle(task.isDone ? theme.accent : theme.secondaryText)
                        .contentTransition(.symbolEffect(.replace))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(task.title)
                            .font(.onest(17))
                            .strikethrough(task.isDone)
                            .foregroundStyle(task.isDone ? theme.secondaryText : .primary)
                        if let details {
                            Text(details)
                                .font(.onest(14))
                                .foregroundStyle(theme.secondaryText)
                        }
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .sensoryFeedback(.selection, trigger: task.isDone)

            if let key = task.jiraKey {
                if let url = task.jiraURL {
                    Link(key, destination: url)
                        .font(.onest(13, .semibold))
                        .padding(.horizontal, 8)
                        .frame(height: 24)
                        .background(theme.bubble, in: .capsule)
                } else {
                    Text(key)
                        .font(.onest(13, .semibold))
                        .foregroundStyle(theme.secondaryText)
                }
            }
        }
    }
}

struct Avatar: View {
    let person: Person
    var size: CGFloat = 24
    @Environment(\.theme) private var theme

    var body: some View {
        if person.isAgent {
            Circle()
                .fill(theme.accentGradient)
                .frame(width: size, height: size)
                .overlay {
                    Image(systemName: "sparkle")
                        .font(.system(size: size * 0.5, weight: .semibold))
                        .foregroundStyle(.white)
                }
        } else {
            Circle()
                .fill(person.color)
                .frame(width: size, height: size)
                .overlay {
                    Text(person.initial)
                        .font(.onest(size * 0.45, .semibold))
                        .foregroundStyle(.white)
                }
        }
    }
}

/// Overlapping avatars
struct AvatarStack: View {
    let people: [Person]
    var size: CGFloat = 24

    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: -size * 0.3) {
            ForEach(people) { person in
                Avatar(person: person, size: size)
                    .overlay {
                        Circle().stroke(theme.background, lineWidth: 2)
                    }
            }
        }
    }
}

/// Call row in lists: title, time, duration and participants
struct ConversationRow: View {
    let conversation: Conversation
    var showsDay = true

    @Environment(\.theme) private var theme

    private var subtitle: String {
        let time = showsDay
            ? conversation.date.formatted(.dateTime.month(.abbreviated).day().hour().minute())
            : conversation.date.formatted(date: .omitted, time: .shortened)
        if conversation.isLive { return time }
        if conversation.status == .failed { return "\(time) · Failed" }
        return conversation.minutes.map { "\(time) · \($0) min" } ?? time
    }

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(conversation.displayTitle)
                    .font(.onest(17))
                    .lineLimit(1)
                HStack(spacing: 6) {
                    if conversation.isLive { LiveBadge(status: conversation.status) }
                    Text(subtitle)
                        .font(.onest(14))
                        .foregroundStyle(theme.secondaryText)
                }
            }
            Spacer(minLength: 8)
            AvatarStack(people: Array(conversation.people.filter { !$0.isOwner }.prefix(4)), size: 22)
        }
        .padding(.vertical, 4)
        .contentShape(.rect)
    }
}
