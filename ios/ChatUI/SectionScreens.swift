import SwiftUI

/// Sidebar sections: Calendar, Projects, People, Tasks
struct SectionScreen: View {
    let section: SidebarSection
    let store: ConversationStore
    let openSidebar: () -> Void

    @Environment(\.theme) private var theme

    var body: some View {
        NavigationStack {
            Group {
                switch section {
                case .calendar: CalendarList(store: store)
                case .projects: ProjectsList(store: store)
                case .people: PeopleList(store: store)
                case .tasks: TasksList(store: store)
                case .knowledge: ProposalsList(store: store)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(theme.background)
            .refreshable(when: store.usesBackend) { await store.refresh() }
            .navigationTitle(section.title)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(action: openSidebar) { Image(systemName: "line.3.horizontal") }
                        .tint(.primary)
                        .accessibilityLabel("Open sidebar")
                }
            }
            .navigationDestination(for: String.self) { project in
                ConversationList(title: project, items: store.conversations(in: project), store: store)
            }
            .navigationDestination(for: Person.self) { person in
                ConversationList(title: person.name, items: store.conversations(with: person), store: store)
            }
        }
    }
}

/// Calls grouped by day
private struct CalendarList: View {
    let store: ConversationStore

    var body: some View {
        List {
            if store.conversations.isEmpty {
                EmptyState(title: "No calls yet", icon: "calendar", text: "Calls appear here by day.")
            }
            ForEach(store.conversationsByDay) { group in
                Section {
                    ForEach(group.items) { conversation in
                        Button {
                            store.open(conversation.id)
                        } label: {
                            ConversationRow(conversation: conversation, showsDay: false)
                        }
                        .buttonStyle(.plain)
                    }
                } header: {
                    ListHeader(Self.title(for: group.day))
                }
            }
        }
    }

    private static func title(for day: Date) -> String {
        let calendar = Calendar.current
        if calendar.isDateInToday(day) { return "Today" }
        if calendar.isDateInYesterday(day) { return "Yesterday" }
        return day.formatted(.dateTime.weekday(.wide).month(.abbreviated).day())
    }
}

private struct ProjectsList: View {
    let store: ConversationStore
    @Environment(\.theme) private var theme

    var body: some View {
        // The backend has no projects yet: calls are grouped by where they happened
        List {
            if store.projects.isEmpty {
                EmptyState(title: "No projects yet", icon: "folder", text: "Calls are grouped by Meet, Zoom or Teams.")
            }
            ForEach(store.projects, id: \.self) { project in
                NavigationLink(value: project) {
                    HStack(spacing: 14) {
                        Image(systemName: "video")
                            .font(.system(size: 19))
                            .frame(width: 28)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(project)
                                .font(.onest(17))
                            Text("^[\(store.conversations(in: project).count) call](inflect: true)")
                                .font(.onest(14))
                                .foregroundStyle(theme.secondaryText)
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
        }
    }
}

private struct PeopleList: View {
    let store: ConversationStore
    @Environment(\.theme) private var theme

    var body: some View {
        List {
            if store.people.isEmpty {
                EmptyState(title: "No people yet", icon: "person.2", text: "Experts and everyone who speaks in a call.")
            }
            ForEach(store.people) { person in
                NavigationLink(value: person) {
                    HStack(spacing: 14) {
                        Avatar(person: person, size: 36)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(person.name)
                                .font(.onest(17))
                            Text(subtitle(for: person))
                                .font(.onest(14))
                                .foregroundStyle(theme.secondaryText)
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
        }
    }

    private func subtitle(for person: Person) -> String {
        let count = store.conversations(with: person).count
        let calls = count == 1 ? "1 call" : "\(count) calls"
        return [person.isOwner ? "Owner" : person.role, calls].compactMap { $0 }.joined(separator: " · ")
    }
}

/// Tasks to check from all calls
private struct TasksList: View {
    let store: ConversationStore

    private var calls: [Conversation] { store.conversations.filter { !$0.tasks.isEmpty } }

    var body: some View {
        List {
            if calls.isEmpty {
                EmptyState(title: "No tasks yet", icon: "checklist", text: "Action items appear here after each call.")
            }
            ForEach(calls) { conversation in
                Section {
                    ForEach(conversation.tasks) { task in
                        TaskRow(task: task) { store.toggleTask(task.id) }
                            .padding(.vertical, 4)
                    }
                } header: {
                    ListHeader(conversation.displayTitle)
                }
            }
        }
    }
}

/// Calls of one project or person
private struct ConversationList: View {
    let title: String
    let items: [Conversation]
    let store: ConversationStore

    @Environment(\.theme) private var theme

    var body: some View {
        List(items) { conversation in
            Button {
                store.open(conversation.id)
            } label: {
                ConversationRow(conversation: conversation)
            }
            .buttonStyle(.plain)
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(theme.background)
        .navigationTitle(title)
    }
}

/// List section header: Onest, or small Druk Wide caps in the bold variant
private struct ListHeader: View {
    let title: String
    @Environment(\.theme) private var theme

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        if theme.wideHeadlines {
            Text(title.uppercased())
                .font(.druk(11))
                .tracking(0.5)
                .foregroundStyle(theme.accentGradient)
        } else {
            Text(title)
                .font(.onest(15, .semibold))
                .foregroundStyle(theme.secondaryText)
        }
    }
}

/// A centered placeholder inside a list
struct EmptyState: View {
    let title: String
    let icon: String
    let text: String

    var body: some View {
        ContentUnavailableView(title, systemImage: icon, description: Text(text))
            .font(.onest(17))
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
            .padding(.top, 60)
    }
}
