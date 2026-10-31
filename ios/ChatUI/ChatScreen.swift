import SwiftUI
import UIKit

/// Call screen (summary, tasks, transcript and questions about it) or the general Discuss thread.
/// Text scrolls under the glass buttons at the top and the input field at the bottom.
struct ChatScreen: View {
    let store: ConversationStore
    let openSidebar: () -> Void

    @State private var draft = ""
    @State private var position = ScrollPosition(edge: .top)
    @State private var isAtBottom = true
    @State private var followsStream = true
    @State private var scrollPhase: ScrollPhase = .idle
    @State private var bannerVisible = false
    @State private var bannerTask: Task<Void, Never>?
    @State private var isRenaming = false
    @State private var renameText = ""
    @FocusState private var composerFocused: Bool
    @State private var voice = VoiceInput()
    /// A question asked by voice gets its answer read out loud
    @State private var speaksNextAnswer = false
    @Environment(\.theme) private var theme

    private var conversation: Conversation? { store.currentConversation }

    /// What the assistant is doing — every orb on the screen follows it
    private var orbState: OrbState {
        switch voice.phase {
        case .listening: return .listening
        case .transcribing: return .thinking
        case .idle: break
        }
        if store.isStreaming {
            return (store.streamingMessage?.text.isEmpty ?? true) ? .thinking : .speaking
        }
        if store.speech.isPlaying { return .speaking }
        if store.speech.isLoading { return .thinking }
        return .idle
    }

    private var showsEmptyDiscuss: Bool { conversation == nil && store.currentMessages.isEmpty }

    /// The field says what the voice input is doing
    private var composerPlaceholder: String {
        switch voice.phase {
        case .listening: "Listening…"
        case .transcribing: "Transcribing…"
        case .idle: conversation == nil ? "Ask about your calls" : "Ask about this call"
        }
    }

    var body: some View {
        NavigationStack {
            content
                .safeAreaBar(edge: .bottom) {
                    Composer(
                        text: $draft,
                        placeholder: composerPlaceholder,
                        isStreaming: store.isStreaming,
                        orbState: orbState,
                        level: voice.level,
                        isDictating: voice.phase == .listening && voice.purpose == .dictation,
                        focus: $composerFocused,
                        onSend: { send() },
                        onStop: store.stop,
                        onVoice: toggleVoiceQuestion,
                        onDictate: toggleDictation
                    )
                    .overlay(alignment: .top) {
                        if !isAtBottom && !store.currentMessages.isEmpty {
                            scrollToBottomButton
                                .offset(y: -50)
                                .transition(.scale(scale: 0.6).combined(with: .opacity))
                        }
                    }
                }
                .overlay(alignment: .top) {
                    if bannerVisible, let share = shareContent {
                        ShareBanner(title: share.title, preview: share.preview, item: share.item)
                            .padding(.top, 18)
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }
                }
                .toolbar { toolbar }
                .navigationBarTitleDisplayMode(.inline)
                // Sources under an answer link to the call they quote
                .environment(\.openURL, OpenURLAction { url in
                    guard url.scheme == "cta", url.host() == "meeting" else { return .systemAction }
                    let id = url.lastPathComponent
                    guard store.conversation(id) != nil else { return .discarded }
                    store.open(id)
                    return .handled
                })
                .alert("Rename call", isPresented: $isRenaming) {
                    TextField("Title", text: $renameText)
                    Button("Save") { store.renameCurrent(to: renameText) }
                    Button("Cancel", role: .cancel) {}
                }
                .task {
                    // Like ChatGPT: offer to share after a screenshot
                    for await _ in NotificationCenter.default.notifications(named: UIApplication.userDidTakeScreenshotNotification) {
                        showBanner()
                    }
                }
                .alert("Voice input", isPresented: Binding(
                    get: { voice.errorMessage != nil },
                    set: { if !$0 { voice.errorMessage = nil } }
                )) {
                    Button("OK", role: .cancel) {}
                } message: {
                    Text(voice.errorMessage ?? "")
                }
                .onChange(of: store.selection) {
                    voice.cancel()
                    store.stopListening()
                    speaksNextAnswer = false
                    isAtBottom = true
                    followsStream = true
                    // A conversation opens at the top, a discussion at the latest messages
                    position.scrollTo(edge: conversation == nil ? .bottom : .top)
                }
        }
    }

    // MARK: - Content

    private var content: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 28) {
                if let conversation {
                    ConversationOverview(conversation: conversation, store: store)
                    if !store.currentMessages.isEmpty {
                        SectionHeader("Discussion")
                            .padding(.top, 8)
                    }
                }
                ForEach(store.currentMessages) { message in
                    MessageView(
                        message: message,
                        isStreaming: store.streamingID == message.id,
                        isLast: message.id == store.currentMessages.last?.id,
                        store: store
                    )
                }
            }
            .padding(.horizontal, 17)
            .padding(.top, 12)
            .padding(.bottom, 24)
        }
        .scrollPosition($position)
        .defaultScrollAnchor(conversation == nil ? .bottom : .top, for: .initialOffset)
        .scrollDismissesKeyboard(.interactively)
        .onScrollPhaseChange { _, phase in
            scrollPhase = phase
        }
        .onScrollGeometryChange(for: Int.self, of: Self.distanceToBottom) { _, distance in
            // Track the distance on every frame: a single Bool change at launch sometimes gets lost
            let nearBottom = distance < 60
            if nearBottom != isAtBottom {
                withAnimation(.snappy(duration: 0.25)) { isAtBottom = nearBottom }
            }
            if nearBottom {
                followsStream = true
            } else if scrollPhase == .interacting || scrollPhase == .decelerating {
                // The user scrolled up on purpose — don't pull them down while the answer streams
                followsStream = false
            }
        }
        .onChange(of: store.streamRevision) {
            if followsStream { position.scrollTo(edge: .bottom) }
        }
        .onChange(of: store.isStreaming) {
            // Action buttons appear under the answer when it finishes — scroll to them too
            if !store.isStreaming && followsStream {
                withAnimation(.smooth) { position.scrollTo(edge: .bottom) }
            }
            // Asked by voice: hear the answer in the server's voice
            if !store.isStreaming && speaksNextAnswer {
                speaksNextAnswer = false
                if store.usesBackend, let answer = store.lastAssistantMessage { store.listen(to: answer) }
            }
        }
        .onChange(of: store.liveRevision) {
            // New lines of a live call: follow them if you're already at the end
            if isAtBottom && store.currentMessages.isEmpty {
                withAnimation(.smooth) { position.scrollTo(edge: .bottom) }
            }
        }
        .refreshable(when: store.usesBackend && conversation != nil) {
            await store.reloadCurrent()
        }
        .alert("Listen", isPresented: Binding(
            get: { store.speech.errorMessage != nil },
            set: { if !$0 { store.speech.errorMessage = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(store.speech.errorMessage ?? "")
        }
        .overlay {
            if showsEmptyDiscuss {
                DiscussEmptyView(
                    orbState: orbState,
                    level: voice.level,
                    onPick: { send($0) },
                    onOrbTap: toggleVoiceQuestion
                )
            }
        }
        .background(theme.background)
    }

    /// visibleRect includes the areas under the bars, so the content bottom = height + bottom inset
    private static func distanceToBottom(_ geometry: ScrollGeometry) -> Int {
        Int(geometry.contentSize.height + geometry.contentInsets.bottom - geometry.visibleRect.maxY)
    }

    private var scrollToBottomButton: some View {
        Button {
            followsStream = true
            withAnimation(.smooth) { position.scrollTo(edge: .bottom) }
        } label: {
            Image(systemName: "arrow.down")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(theme.secondaryText)
                .frame(width: 36, height: 36)
        }
        .buttonStyle(.plain)
        .glassEffect(.regular.interactive(), in: .circle)
    }

    // MARK: - Top buttons

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button(action: openSidebar) {
                Image(systemName: "line.3.horizontal")
            }
            // Top icons stay black / white like in ChatGPT; the accent is for AI elements
            .tint(.primary)
            .accessibilityLabel("Open sidebar")
        }
        ToolbarItemGroup(placement: .topBarTrailing) {
            Button {
                composerFocused = false
                store.newDiscussion()
            } label: {
                Image(systemName: "square.and.pencil")
            }
            .tint(.primary)
            .accessibilityLabel("New discussion")

            Menu {
                if let conversation {
                    ShareLink(item: conversation.shareText) {
                        Label("Share transcript", systemImage: "square.and.arrow.up")
                    }
                    if store.usesBackend {
                        if conversation.isLive && !store.demoCallIDs.contains(conversation.id) {
                            Divider()
                            Button("Remove Atlas from the call", systemImage: "phone.down", role: .destructive) {
                                Task { await store.leaveCurrentCall() }
                            }
                        }
                    } else {
                        Button("Rename", systemImage: "pencil") {
                            renameText = conversation.title
                            isRenaming = true
                        }
                        Divider()
                        Button("Delete", systemImage: "trash", role: .destructive) {
                            store.deleteCurrent()
                        }
                    }
                } else {
                    ShareLink(item: discussionText) {
                        Label("Share", systemImage: "square.and.arrow.up")
                    }
                    Divider()
                    Button("Clear discussion", systemImage: "trash", role: .destructive) {
                        store.deleteCurrent()
                    }
                }
            } label: {
                Image(systemName: "ellipsis")
            }
            .tint(.primary)
            .disabled(conversation == nil && store.currentMessages.isEmpty)
        }
    }

    private var discussionText: String {
        store.currentMessages
            .map { ($0.role == .user ? "You: " : "Assistant: ") + $0.text }
            .joined(separator: "\n\n")
    }

    private var shareContent: (title: String, preview: String, item: String)? {
        if let conversation {
            return ("Share Call", conversation.displayTitle, conversation.shareText)
        }
        if let message = store.lastAssistantMessage {
            return ("Share Message", ShareBanner.preview(of: message.text), message.text)
        }
        return nil
    }

    // MARK: - Actions

    private func send(_ preset: String? = nil) {
        let text = (preset ?? draft).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        if preset == nil { draft = "" }
        followsStream = true
        store.send(text)
        withAnimation(.smooth) { position.scrollTo(edge: .bottom) }
    }

    /// Round button with an empty field: ask out loud, the answer comes right away
    private func toggleVoiceQuestion() {
        switch voice.phase {
        case .listening:
            voice.finish()
        case .transcribing:
            break
        case .idle:
            guard !store.isStreaming else { return }
            composerFocused = false
            store.stopListening()
            voice.start(.question) { text in
                speaksNextAnswer = true
                send(text)
            }
        }
    }

    /// Microphone: speech goes into the field, so you can edit it before sending
    private func toggleDictation() {
        switch voice.phase {
        case .listening:
            voice.finish()
        case .transcribing:
            break
        case .idle:
            voice.start(.dictation) { text in
                draft = draft.isEmpty ? text : draft + " " + text
                composerFocused = true
            }
        }
    }

    private func showBanner() {
        guard shareContent != nil else { return }
        withAnimation(.spring(duration: 0.4, bounce: 0.2)) { bannerVisible = true }
        bannerTask?.cancel()
        bannerTask = Task {
            try? await Task.sleep(for: .seconds(5))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.25)) { bannerVisible = false }
        }
    }
}

/// Empty discussion: the AI orb, a question and ready-made suggestions. Tap the orb to ask by voice.
struct DiscussEmptyView: View {
    let orbState: OrbState
    let level: Double
    let onPick: (String) -> Void
    let onOrbTap: () -> Void
    @Environment(\.theme) private var theme

    private let suggestions = [
        "What did we decide this week?",
        "Which tasks are still open?",
        "What did the experts answer?",
    ]

    var body: some View {
        VStack(spacing: 22) {
            Button(action: onOrbTap) {
                OrbView(state: orbState, zoom: 1.35)
                    .frame(width: 230, height: 230)
                    .scaleEffect(orbState == .listening ? 1 + level * 0.12 : 1)
                    .animation(.easeOut(duration: 0.1), value: level)
                    .contentShape(.circle)
            }
            .buttonStyle(.plain)
            .padding(.vertical, -24)
            .accessibilityLabel(orbState.caption)
            .accessibilityHint("Ask by voice")

            Text(orbState == .idle ? theme.headlineText("What would you like to discuss?") : theme.headlineText(orbState.caption))
                .font(theme.headline(26))
                .lineSpacing(theme.wideHeadlines ? 4 : 0)
                .multilineTextAlignment(.center)
            VStack(spacing: 10) {
                ForEach(suggestions, id: \.self) { suggestion in
                    Button {
                        onPick(suggestion)
                    } label: {
                        Text(suggestion)
                            .font(.onest(16))
                            .padding(.horizontal, 18)
                            .frame(height: 42)
                    }
                    .buttonStyle(.plain)
                    .glassEffect(.regular.interactive(), in: .capsule)
                }
            }
        }
        .padding(.horizontal, 32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

extension View {
    /// Pull to refresh only where there is something to reload
    @ViewBuilder
    func refreshable(when enabled: Bool, action: @escaping @Sendable () async -> Void) -> some View {
        if enabled {
            refreshable(action: action)
        } else {
            self
        }
    }
}
