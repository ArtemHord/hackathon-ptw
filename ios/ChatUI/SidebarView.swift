import SwiftUI

/// Sidebar. The list scrolls under the header and under the Discuss / Settings buttons.
struct SidebarView: View {
    let store: ConversationStore
    let close: () -> Void

    @Environment(\.theme) private var theme
    @State private var showSearch = false
    @State private var showSettings = false
    @State private var showNewCall = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(SidebarSection.allCases) { section in
                    SidebarRow(
                        title: section.title,
                        icon: section.icon,
                        isSelected: store.selection == .section(section)
                    ) {
                        store.openSection(section)
                        close()
                    }
                }

                connectionRow
                    .padding(.top, 10)

                HStack {
                    recentsHeader
                    Spacer()
                    Button {
                        showNewCall = true
                    } label: {
                        Image(systemName: "plus")
                            .font(.system(size: 18, weight: .medium))
                            .frame(width: 40, height: 40)
                            .contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("New call")
                }
                .padding(.leading, 23)
                .padding(.trailing, 4)
                .frame(height: 48)
                .padding(.top, 12)

                if store.conversations.isEmpty {
                    if store.isConnected {
                        SidebarRow(title: "Run a demo call", icon: "play.circle") { showNewCall = true }
                    } else if store.connection == .connecting {
                        SidebarRow(title: "Loading calls…", icon: "arrow.triangle.2.circlepath") {}
                            .disabled(true)
                    }
                }

                // Each item is a recorded call; live ones get a red dot
                ForEach(store.conversations) { conversation in
                    SidebarRow(
                        title: conversation.displayTitle,
                        icon: "waveform",
                        isSelected: store.selection == .conversation(conversation.id),
                        isLive: conversation.isLive
                    ) {
                        store.open(conversation.id)
                        close()
                    }
                }
            }
            .padding(.horizontal, 10)
            .padding(.top, 6)
            .padding(.bottom, 16)
        }
        .scrollIndicators(.hidden)
        .scrollEdgeEffectStyle(.soft, for: .all)
        .safeAreaBar(edge: .top) { topBar }
        .safeAreaBar(edge: .bottom) { bottomBar }
        .background(theme.sidebar)
        .sheet(isPresented: $showSearch) {
            SearchConversationsView(store: store, onOpen: close)
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(store: store)
        }
        .sheet(isPresented: $showNewCall) {
            NewCallSheet(store: store, onStarted: close)
        }
    }

    /// Where the calls come from, when it isn't the backend yet
    @ViewBuilder
    private var connectionRow: some View {
        switch store.connection {
        case .connected:
            EmptyView()
        case .connecting:
            ConnectionRow(color: .orange, title: "Connecting to the backend…", action: nil)
        case .setup:
            ConnectionRow(color: .orange, title: "Not connected", detail: "Open Settings", action: { showSettings = true })
        case .demo:
            ConnectionRow(color: theme.secondaryText, title: "Demo data", detail: "Connect", action: { showSettings = true })
        case .unauthorized:
            ConnectionRow(color: .red, title: "Wrong token", detail: "Open Settings", action: { showSettings = true })
        case .offline(let message):
            ConnectionRow(color: .orange, title: "Backend error: \(message.prefix(80))", detail: "Retry", action: { Task { await store.refresh() } })
        }
    }

    @ViewBuilder
    private var recentsHeader: some View {
        if theme.wideHeadlines {
            Text("RECENTS")
                .font(.druk(12))
                .tracking(0.6)
                .foregroundStyle(theme.secondaryText)
        } else {
            Text("Recents")
                .font(.onest(17, .semibold))
        }
    }

    private var topBar: some View {
        HStack(spacing: 12) {
            LogoView(height: 26)
            Spacer()
            Button {
                showSearch = true
            } label: {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 20))
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .glassEffect(.regular.interactive(), in: .circle)
            .accessibilityLabel("Search calls")
        }
        .padding(.leading, 33)
        .padding(.trailing, 23)
    }

    private var bottomBar: some View {
        HStack {
            Button {
                store.openDiscussion()
                close()
            } label: {
                // One color and the new-chat icon, like ChatGPT's Chat button
                HStack(spacing: 10) {
                    Image(systemName: "square.and.pencil")
                        .font(.system(size: 18, weight: .semibold))
                    Text("Discuss")
                        .font(.onest(18, .semibold))
                }
                .foregroundStyle(theme.onAccent)
                .padding(.horizontal, 20)
                .frame(height: 46)
                .background(theme.accent, in: .capsule)
                .contentShape(.capsule)
            }
            .buttonStyle(.plain)

            Spacer()

            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape")
                    .font(.system(size: 21))
                    .frame(width: 48, height: 48)
            }
            .buttonStyle(.plain)
            .glassEffect(.regular.interactive(), in: .circle)
            .accessibilityLabel("Settings")
        }
        .padding(.leading, 34)
        .padding(.trailing, 24)
    }
}

struct SidebarRow: View {
    let title: String
    let icon: String
    var isSelected = false
    var isLive = false
    let action: () -> Void

    @Environment(\.theme) private var theme

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 19))
                    .frame(width: 24)
                Text(title)
                    .font(.onest(17))
                    .lineLimit(1)
                Spacer(minLength: 0)
                if isLive {
                    Circle()
                        .fill(.red)
                        .frame(width: 8, height: 8)
                        .accessibilityLabel("Live")
                }
            }
            .padding(.leading, 23)
            .padding(.trailing, 12)
            .frame(height: 48)
            .background {
                if isSelected {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(theme.rowHighlight)
                }
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
    }
}

/// A small status line in the sidebar: sample calls, wrong token, offline
private struct ConnectionRow: View {
    let color: Color
    let title: String
    var detail: String? = nil
    let action: (() -> Void)?

    @Environment(\.theme) private var theme

    var body: some View {
        Button {
            action?()
        } label: {
            HStack(spacing: 10) {
                Circle()
                    .fill(color)
                    .frame(width: 8, height: 8)
                Text(title)
                    .font(.onest(15, .medium))
                if let detail {
                    Text(detail)
                        .font(.onest(15))
                        .foregroundStyle(theme.accent)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 16)
            .frame(height: 42)
            .background(theme.card, in: .rect(cornerRadius: 14, style: .continuous))
            .padding(.horizontal, 10)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(action == nil)
    }
}
