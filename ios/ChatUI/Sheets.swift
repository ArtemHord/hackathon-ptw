import SwiftUI

/// Search across titles, summaries, transcripts and people
struct SearchConversationsView: View {
    let store: ConversationStore
    let onOpen: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var query = ""

    private var results: [Conversation] {
        guard !query.isEmpty else { return store.conversations }
        return store.conversations.filter { conversation in
            conversation.title.localizedCaseInsensitiveContains(query)
                || conversation.summary.localizedCaseInsensitiveContains(query)
                || conversation.decisions.contains { $0.localizedCaseInsensitiveContains(query) }
                || conversation.tasks.contains { $0.title.localizedCaseInsensitiveContains(query) }
                || conversation.transcript.contains { $0.text.localizedCaseInsensitiveContains(query) }
                || conversation.people.contains { $0.name.localizedCaseInsensitiveContains(query) }
        }
    }

    var body: some View {
        NavigationStack {
            List(results) { conversation in
                Button {
                    store.open(conversation.id)
                    dismiss()
                    onOpen()
                } label: {
                    ConversationRow(conversation: conversation)
                }
                .buttonStyle(.plain)
            }
            .listStyle(.plain)
            .overlay {
                if results.isEmpty {
                    ContentUnavailableView.search(text: query)
                }
            }
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search calls")
            .navigationTitle("Search")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close", systemImage: "xmark") { dismiss() }
                }
            }
        }
    }
}

struct SettingsView: View {
    let store: ConversationStore

    @Environment(\.dismiss) private var dismiss
    @AppStorage("design") private var design: DesignVariant = .clean
    @AppStorage("appearance") private var appearance: Appearance = .light
    @AppStorage("palette") private var palette: AccentPalette = .sunset

    var body: some View {
        NavigationStack {
            Form {
                BackendSection(store: store)
                Section {
                    // Menu pickers keep the tint they were created with; .id rebuilds them when the color changes
                    Picker("Design", selection: $design) {
                        ForEach(DesignVariant.allCases) { Text($0.title).tag($0) }
                    }
                    .id(palette)
                    Picker("Theme", selection: $appearance) {
                        ForEach(Appearance.allCases) { Text($0.title).tag($0) }
                    }
                    .disabled(design.theme.colorScheme != nil)
                    .id(palette)
                    LabeledContent("Color") {
                        AccentSwatches(selection: $palette)
                    }
                } header: {
                    Text("Appearance")
                } footer: {
                    if design.theme.colorScheme != nil {
                        Text("\(design.title) is always dark.")
                    }
                }
                Section {
                    LabeledContent("Answers", value: answersSource)
                    LabeledContent("Voice answers", value: store.usesBackend ? "Server · ElevenLabs" : "Off")
                    LabeledContent("Voice input", value: AppConfig.voiceInputDescription)
                } header: {
                    Text("AI")
                } footer: {
                    Text(store.usesBackend
                        ? "Answers, search across calls and the voice come from the backend, so the phone needs no AI keys."
                        : "Connect the backend for real answers. Without it, OPENAI_API_KEY in Secrets.env answers from the phone.")
                }
                Section {
                    LabeledContent("Version", value: "1.0 (demo)")
                }
            }
            .font(.onest(17))
            // The sheet keeps the tint it opened with, so it follows the picked color itself
            .tint(palette.accent)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .scrollDismissesKeyboard(.interactively)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", systemImage: "checkmark") { dismiss() }
                }
            }
        }
    }
}

extension SettingsView {
    private var answersSource: String {
        if store.usesBackend { return "Call Crew backend" }
        return AppConfig.openAIKey == nil ? "Demo" : "OpenAI · \(AppConfig.chatModel)"
    }
}

/// Server address and demo token. The token is checked with `GET /meetings` before it is saved.
private struct BackendSection: View {
    let store: ConversationStore

    @State private var server = BackendSettings.productionURL.absoluteString
    @State private var token = ""
    @State private var isConnecting = false
    @State private var error: String?
    @Environment(\.theme) private var theme

    var body: some View {
        Section {
            if let settings = store.settings {
                LabeledContent("Server", value: settings.baseURL.host() ?? settings.baseURL.absoluteString)
                LabeledContent("Status") { status }
                Button("Disconnect", role: .destructive) { store.disconnect() }
            } else {
                TextField("Server", text: $server)
                    .keyboardType(.URL)
                    .textContentType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                SecureField("Demo token", text: $token)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button {
                    Task { await connect() }
                } label: {
                    HStack {
                        Text("Connect")
                        if isConnecting {
                            Spacer()
                            ProgressView()
                        }
                    }
                }
                .disabled(isConnecting || token.trimmingCharacters(in: .whitespaces).isEmpty || URL(string: server)?.host() == nil)
                if let error {
                    Text(error)
                        .font(.onest(15))
                        .foregroundStyle(.red)
                }
            }
        } header: {
            Text("Backend")
        } footer: {
            Text(store.usesBackend
                ? "Calls, transcripts and tasks sync from the Call Crew backend every few seconds."
                : "Paste DEMO_TOKEN from the backend (Railway → Variables). It stays in the Keychain on this phone. Without it, the app shows sample calls.")
        }
    }

    /// One Text with an inline symbol: a Label here makes the Form row grow
    private var status: some View {
        let (symbol, title, color): (String?, String, Color) = switch store.connection {
        case .connected: ("checkmark.circle.fill", "Connected", .green)
        case .connecting: (nil, "Connecting…", theme.secondaryText)
        case .unauthorized: ("xmark.octagon.fill", "Wrong token", .red)
        case .offline: ("wifi.slash", "Offline", .orange)
        case .demo: (nil, "Sample calls", theme.secondaryText)
        }
        return Group {
            if let symbol {
                Text("\(Image(systemName: symbol)) \(title)")
            } else {
                Text(title)
            }
        }
        .foregroundStyle(color)
    }

    private func connect() async {
        let trimmed = server.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed.contains("://") ? trimmed : "https://\(trimmed)") else { return }
        isConnecting = true
        error = await store.connect(url: url, token: token.trimmingCharacters(in: .whitespacesAndNewlines))
        isConnecting = false
        if error == nil { token = "" }
    }
}

/// Start a call: a demo replayed by the backend, or Atlas joining a real Meet / Zoom / Teams link
struct NewCallSheet: View {
    let store: ConversationStore
    let onStarted: () -> Void

    @Environment(\.dismiss) private var dismiss
    @AppStorage("palette") private var palette: AccentPalette = .sunset
    @State private var link = ""
    @State private var mode = "delegate"
    @State private var brief = ""
    @State private var isWorking = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                if !store.isConnected {
                    Section {
                        Text("Connect the backend in Settings to start calls.")
                    }
                }
                Section {
                    Button {
                        Task {
                            isWorking = true
                            await store.startDemoCall()
                            isWorking = false
                            dismiss()
                            onStarted()
                        }
                    } label: {
                        Label("Run a demo call", systemImage: "play.circle.fill")
                    }
                } header: {
                    Text("Demo")
                } footer: {
                    Text("The backend plays a short stand-up through its real pipeline: the transcript streams in, Atlas answers, and a question goes to an expert you can answer here.")
                }
                Section {
                    TextField("Meet, Zoom or Teams link", text: $link)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Picker("Atlas", selection: $mode) {
                        Text("Stands in for you").tag("delegate")
                        Text("Takes notes").tag("notetaker")
                    }
                    .id(palette)
                    if mode == "delegate" {
                        TextField("Brief: what Atlas may say", text: $brief, axis: .vertical)
                            .lineLimit(2...5)
                    }
                    Button("Send Atlas to the call") {
                        Task { await join() }
                    }
                    .disabled(URL(string: link)?.host() == nil)
                    if let error {
                        Text(error)
                            .font(.onest(15))
                            .foregroundStyle(.red)
                    }
                } header: {
                    Text("Join a real call")
                }
            }
            .disabled(!store.isConnected || isWorking)
            .font(.onest(17))
            .tint(palette.accent)
            .navigationTitle("New call")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close", systemImage: "xmark") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func join() async {
        isWorking = true
        error = await store.joinCall(url: link.trimmingCharacters(in: .whitespacesAndNewlines), mode: mode, brief: brief)
        isWorking = false
        if error == nil {
            dismiss()
            onStarted()
        }
    }
}

/// Round gradient swatches for the accent color
private struct AccentSwatches: View {
    @Binding var selection: AccentPalette

    var body: some View {
        HStack(spacing: 10) {
            ForEach(AccentPalette.allCases) { palette in
                Button {
                    selection = palette
                } label: {
                    Circle()
                        .fill(palette.gradient)
                        .frame(width: 28, height: 28)
                        .overlay {
                            if selection == palette {
                                Image(systemName: "checkmark")
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(.white)
                            }
                        }
                        .padding(3)
                        .overlay {
                            Circle().strokeBorder(selection == palette ? palette.accent : .clear, lineWidth: 2)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityLabel(palette.title)
                .accessibilityAddTraits(selection == palette ? .isSelected : [])
            }
        }
        .sensoryFeedback(.selection, trigger: selection)
    }
}
