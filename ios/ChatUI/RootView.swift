import SwiftUI
import UIKit

/// The main screen slides right to reveal the sidebar — like in ChatGPT.
/// Open: the menu button or a swipe right. Close: a tap on the screen or a swipe left.
struct RootView: View {
    @State private var store = ConversationStore()
    @State private var isOpen = false
    @State private var dragX: CGFloat = 0
    @State private var dragAxis: Axis?
    @State private var width: CGFloat = 393
    @State private var showsLaunch = true
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var sidebarWidth: CGFloat { max(width - 84, 260) }

    private var offset: CGFloat {
        min(max((isOpen ? sidebarWidth : 0) + dragX, 0), sidebarWidth)
    }

    private var progress: CGFloat { offset / sidebarWidth }

    var body: some View {
        ZStack(alignment: .leading) {
            SidebarView(store: store, close: { setOpen(false) })
                .frame(width: sidebarWidth)
                .offset(x: (progress - 1) * 32)

            MainView(store: store, openSidebar: { setOpen(true) })
                .overlay {
                    theme.background
                        .opacity(0.78 * progress)
                        .ignoresSafeArea()
                        .allowsHitTesting(isOpen)
                        .onTapGesture { setOpen(false) }
                }
                .mask {
                    RoundedRectangle(cornerRadius: 50 * min(progress * 3, 1), style: .continuous)
                        .ignoresSafeArea()
                }
                .overlay {
                    // Hairline that separates the screen from the sidebar
                    RoundedRectangle(cornerRadius: 50 * min(progress * 3, 1), style: .continuous)
                        .strokeBorder(theme.separator, lineWidth: 1)
                        .opacity(min(progress * 3, 1))
                        .ignoresSafeArea()
                        .allowsHitTesting(false)
                }
                .background {
                    RoundedRectangle(cornerRadius: 50, style: .continuous)
                        .fill(theme.background)
                        .shadow(color: .black.opacity(0.18 * progress), radius: 30, x: -10)
                        .ignoresSafeArea()
                }
                .offset(x: offset)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
        .simultaneousGesture(drawerDrag)
        .sensoryFeedback(.impact(weight: .light), trigger: isOpen)
        .overlay {
            if showsLaunch && !reduceMotion {
                LaunchOverlay { showsLaunch = false }
                    .transition(.opacity)
            }
        }
        .task { store.start() }
        .alert("Call Crew", isPresented: Binding(
            get: { store.notice != nil },
            set: { if !$0 { store.notice = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(store.notice ?? "")
        }
    }

    private var drawerDrag: some Gesture {
        DragGesture(minimumDistance: 12)
            .onChanged { value in
                if dragAxis == nil {
                    dragAxis = abs(value.translation.width) > abs(value.translation.height) ? .horizontal : .vertical
                }
                guard dragAxis == .horizontal else { return }
                dragX = value.translation.width
            }
            .onEnded { value in
                defer { dragAxis = nil }
                guard dragAxis == .horizontal else { return }
                let projected = (isOpen ? sidebarWidth : 0) + value.predictedEndTranslation.width
                setOpen(projected > sidebarWidth / 2)
            }
    }

    private func setOpen(_ open: Bool) {
        if open {
            UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        }
        withAnimation(.spring(duration: 0.38, bounce: 0.12)) {
            isOpen = open
            dragX = 0
        }
    }
}

struct MainView: View {
    let store: ConversationStore
    let openSidebar: () -> Void

    var body: some View {
        content
            .overlay(alignment: .top) {
                ConnectionBanner(store: store, openSidebar: openSidebar)
                    .padding(.top, 56)
            }
    }

    @ViewBuilder
    private var content: some View {
        if case .section(let section) = store.selection {
            SectionScreen(section: section, store: store, openSidebar: openSidebar)
        } else {
            ChatScreen(store: store, openSidebar: openSidebar)
        }
    }
}

/// Not connected, wrong token or a backend error: say so on the main screen, with a way out (never sample data)
private struct ConnectionBanner: View {
    let store: ConversationStore
    let openSidebar: () -> Void
    @Environment(\.theme) private var theme

    var body: some View {
        switch store.connection {
        case .setup:
            banner("Not connected. Menu → ⚙︎ Settings → Backend: paste DEMO_TOKEN.", button: "Open menu", action: openSidebar)
        case .unauthorized:
            banner("Wrong token. Menu → ⚙︎ Settings → Backend.", button: "Open menu", action: openSidebar)
        case .offline(let message):
            banner("Backend error: \(message.prefix(140))", button: "Retry") { Task { await store.refresh() } }
        case .connected, .connecting, .demo:
            EmptyView()
        }
    }

    private func banner(_ text: String, button: String, action: @escaping () -> Void) -> some View {
        HStack(spacing: 10) {
            Text(text)
                .font(.onest(14))
                .lineLimit(3)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button(button, action: action)
                .font(.onest(14, .semibold))
                .foregroundStyle(theme.accent)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .padding(.horizontal, 12)
    }
}
