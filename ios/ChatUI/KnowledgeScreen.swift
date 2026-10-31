import SwiftUI

/// Knowledge base proposals from fact-checks: a human approves or rejects each one (the agent never edits the KB itself)
struct ProposalsList: View {
    let store: ConversationStore

    @State private var proposals: [ProposalDTO] = []
    @State private var error: String?
    @State private var isLoading = false
    @State private var busy: Set<String> = []
    @Environment(\.theme) private var theme

    var body: some View {
        List {
            if let error {
                VStack(alignment: .leading, spacing: 8) {
                    Text(error).font(.onest(15)).foregroundStyle(.red)
                    Button("Retry") { Task { await load() } }
                        .font(.onest(15, .semibold))
                }
                .listRowSeparator(.hidden)
            } else if proposals.isEmpty && !isLoading {
                EmptyState(
                    title: store.usesBackend ? "No proposals" : "Not connected",
                    icon: "book",
                    text: store.usesBackend
                        ? "When a fact-check finds the knowledge base out of date, the change waits here for your approval."
                        : "Connect the backend in Settings → Backend."
                )
            }
            ForEach(proposals) { proposal in
                row(proposal)
            }
        }
        .overlay { if isLoading && proposals.isEmpty { ProgressView() } }
        .task { await load() }
        .refreshable { await load() }
    }

    private func row(_ proposal: ProposalDTO) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(proposal.doc_title ?? "Document")
                .font(.onest(17, .semibold))
            if let reason = proposal.reason, !reason.isEmpty {
                Text(reason).font(.onest(15)).foregroundStyle(theme.secondaryText)
            }
            if let old = proposal.old_text, !old.isEmpty {
                Text(old).font(.onest(15)).strikethrough().foregroundStyle(theme.secondaryText)
            }
            if let new = proposal.new_text, !new.isEmpty {
                Text(new).font(.onest(15))
            }
            if let speaker = proposal.speaker, !speaker.isEmpty {
                Text("Said by \(speaker)").font(.onest(13)).foregroundStyle(theme.secondaryText)
            }
            HStack(spacing: 12) {
                Button("Approve") { Task { await decide(proposal, approve: true) } }
                    .buttonStyle(.borderedProminent)
                Button("Reject", role: .destructive) { Task { await decide(proposal, approve: false) } }
                    .buttonStyle(.bordered)
                if busy.contains(proposal.id) { ProgressView() }
            }
            .font(.onest(15, .semibold))
            .disabled(busy.contains(proposal.id))
        }
        .padding(.vertical, 6)
    }

    private func load() async {
        guard let client = store.client else {
            proposals = []
            error = nil
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            proposals = try await client.proposals().filter { ($0.status ?? "pending") == "pending" }
            error = nil
        } catch {
            self.error = "Couldn't load proposals. \(error.localizedDescription)"
        }
    }

    private func decide(_ proposal: ProposalDTO, approve: Bool) async {
        guard let client = store.client else { return }
        busy.insert(proposal.id)
        defer { busy.remove(proposal.id) }
        do {
            try await client.decide(proposal: proposal.id, approve: approve)
            proposals.removeAll { $0.id == proposal.id }
        } catch let failure as BackendError where failure.status == 409 {
            // Already decided elsewhere (web app): just drop it
            proposals.removeAll { $0.id == proposal.id }
        } catch {
            store.notice = "Couldn't \(approve ? "approve" : "reject"). \(error.localizedDescription)"
        }
    }
}
