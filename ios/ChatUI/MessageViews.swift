import SwiftUI
import UIKit

struct MessageView: View {
    let message: Message
    let isStreaming: Bool
    let isLast: Bool
    let store: ConversationStore

    var body: some View {
        switch message.role {
        case .user:
            UserBubble(text: message.text)
        case .assistant:
            AssistantMessage(message: message, isStreaming: isStreaming, isLast: isLast, store: store)
        }
    }
}

/// User question — gray bubble on the right
struct UserBubble: View {
    let text: String
    @Environment(\.theme) private var theme

    var body: some View {
        Text(Markdown.inline(text))
            .font(.onest(17))
            .lineSpacing(3)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(theme.bubble, in: .rect(cornerRadius: 22, style: .continuous))
            .contextMenu {
                Button("Copy", systemImage: "doc.on.doc") { UIPasteboard.general.string = text }
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.leading, 56)
    }
}

/// Assistant answer — full-width text without a bubble, actions below
struct AssistantMessage: View {
    let message: Message
    let isStreaming: Bool
    let isLast: Bool
    let store: ConversationStore
    @Environment(\.theme) private var theme
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if isStreaming && message.text.isEmpty {
                // The diamond sits on the text edge; the frame is wider for the glow
                OrbView(state: .thinking, zoom: 1.5)
                    .frame(width: 56, height: 56)
                    .padding(.leading, -14)
                    .padding(.vertical, -10)
            } else {
                MarkdownView(text: message.text)
            }

            if !isStreaming && !message.text.isEmpty {
                actions
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var actions: some View {
        HStack(spacing: 22) {
            Button {
                UIPasteboard.general.string = message.text
                copied = true
                Task {
                    try? await Task.sleep(for: .seconds(1.5))
                    copied = false
                }
            } label: {
                Image(systemName: copied ? "checkmark" : "doc.on.doc")
                    .contentTransition(.symbolEffect(.replace))
            }
            Button {
                store.toggleFeedback(.liked, for: message.id)
            } label: {
                Image(systemName: message.feedback == .liked ? "hand.thumbsup.fill" : "hand.thumbsup")
            }
            Button {
                store.toggleFeedback(.disliked, for: message.id)
            } label: {
                Image(systemName: message.feedback == .disliked ? "hand.thumbsdown.fill" : "hand.thumbsdown")
            }
            ShareLink(item: message.text) {
                Image(systemName: "square.and.arrow.up")
            }
            if store.usesBackend {
                // Read out loud in the server's ElevenLabs voice
                Button {
                    store.listen(to: message)
                } label: {
                    Image(systemName: store.isListening(to: message) ? "stop.circle" : "speaker.wave.2")
                        .contentTransition(.symbolEffect(.replace))
                        .symbolEffect(.variableColor.iterative, isActive: store.isListening(to: message) && store.speech.isPlaying)
                }
                .accessibilityLabel(store.isListening(to: message) ? "Stop" : "Listen")
            }
            if isLast {
                Button {
                    store.regenerate()
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
            }
        }
        .font(.system(size: 15, weight: .medium))
        .foregroundStyle(theme.secondaryText)
        .buttonStyle(.plain)
        .padding(.top, 2)
    }
}

/// Banner after a screenshot — offers to share the conversation or the answer
struct ShareBanner: View {
    let title: String
    let preview: String
    let item: String
    @Environment(\.theme) private var theme

    /// First non-empty line without Markdown symbols
    static func preview(of text: String) -> String {
        let firstLine = text
            .components(separatedBy: "\n")
            .first { !$0.trimmingCharacters(in: .whitespaces).isEmpty } ?? ""
        return firstLine
            .replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "`", with: "")
            .trimmingCharacters(in: CharacterSet(charactersIn: "#- "))
    }

    var body: some View {
        ShareLink(item: item) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.onest(16, .semibold))
                    Text(preview)
                        .font(.onest(15))
                        .foregroundStyle(theme.secondaryText)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.system(size: 17, weight: .semibold))
            }
            .foregroundStyle(.primary)
            .padding(.leading, 12)
            .padding(.trailing, 18)
            .frame(height: 64)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 22, style: .continuous))
        .padding(.horizontal, 18)
    }
}
