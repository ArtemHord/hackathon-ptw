import SwiftUI

/// Bottom input: "+", text, microphone for dictation and the AI button.
/// The AI button is a flat circle like ChatGPT's: its icon shows whether the assistant listens, thinks or answers.
struct Composer: View {
    @Binding var text: String
    let placeholder: String
    let isStreaming: Bool
    /// What the assistant is doing; the icon in the button follows it
    let orbState: OrbState
    let level: Double
    let isDictating: Bool
    var focus: FocusState<Bool>.Binding
    let onSend: () -> Void
    let onStop: () -> Void
    /// Empty field: start or finish a spoken question
    let onVoice: () -> Void
    /// Microphone: start or finish dictation into the field
    let onDictate: () -> Void

    @Environment(\.theme) private var theme

    private var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// Send only when the assistant is free
    private var showsSend: Bool { hasText && orbState == .idle }

    var body: some View {
        HStack(alignment: .bottom, spacing: 0) {
            Button {} label: {
                Image(systemName: "plus")
                    .font(.system(size: 21))
                    .frame(width: 48, height: 48)
            }

            TextField(
                "",
                text: $text,
                prompt: Text(placeholder).foregroundStyle(theme.placeholder),
                axis: .vertical
            )
            .font(.onest(17))
            .lineLimit(1...6)
            .focused(focus)
            .padding(.vertical, 13)

            Button(action: onDictate) {
                Image(systemName: isDictating ? "mic.fill" : "mic")
                    .font(.system(size: 19))
                    .foregroundStyle(isDictating ? AnyShapeStyle(theme.accent) : AnyShapeStyle(.primary))
                    .contentTransition(.symbolEffect(.replace))
                    .frame(width: 42, height: 48)
            }
            .accessibilityLabel(isDictating ? "Stop dictation" : "Dictate")

            aiButton
                .padding(.vertical, 2)
        }
        .padding(.trailing, 4)
        .buttonStyle(.plain)
        .foregroundStyle(.primary)
        .glassEffect(.regular, in: .rect(cornerRadius: 24, style: .continuous))
        .padding(.horizontal, 32)
    }

    private var aiButton: some View {
        Button(action: tap) {
            ZStack {
                glyph
                    .id(glyphKey)
                    .transition(.scale(scale: 0.5).combined(with: .opacity))
            }
            .font(.system(size: 15, weight: .bold))
            .foregroundStyle(theme.onAccent)
            .frame(width: 34, height: 34)
            .background(theme.accent, in: .circle)
            .scaleEffect(orbState == .listening ? 1 + level * 0.12 : 1)
            .animation(.snappy(duration: 0.2), value: glyphKey)
            .animation(.easeOut(duration: 0.1), value: level)
            .frame(width: 44, height: 44)
            .contentShape(.circle)
        }
        .accessibilityLabel(isStreaming ? "Stop" : showsSend ? "Send" : orbState == .listening ? "Finish speaking" : "Ask by voice")
    }

    /// Flat SF icons that follow the assistant: waveform → listening bars → dots → stop
    @ViewBuilder
    private var glyph: some View {
        if isStreaming {
            RoundedRectangle(cornerRadius: 2.5, style: .continuous)
                .frame(width: 11, height: 11)
        } else if showsSend {
            Image(systemName: "arrow.up")
        } else {
            switch orbState {
            case .listening:
                Image(systemName: "waveform")
                    .symbolEffect(.variableColor.iterative.reversing, options: .repeating)
            case .thinking:
                Image(systemName: "ellipsis")
                    .symbolEffect(.variableColor.iterative, options: .repeating)
            case .idle, .speaking:
                Image(systemName: "waveform")
            }
        }
    }

    private var glyphKey: String {
        isStreaming ? "stop" : showsSend ? "send" : orbState.rawValue
    }

    private func tap() {
        if isStreaming {
            onStop()
        } else if showsSend {
            onSend()
        } else if orbState != .thinking {
            onVoice()
        }
    }
}
