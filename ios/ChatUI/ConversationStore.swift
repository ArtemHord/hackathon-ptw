import SwiftUI

/// All calls and questions. Connected: calls come from the Call Crew backend and stay in sync
/// (list every 5 s, the open live call over WebSocket). Not connected: sample calls for a demo.
@MainActor @Observable
final class ConversationStore {
    enum Selection: Hashable {
        /// General discussion of all calls (the Discuss button)
        case discussion
        case conversation(Conversation.ID)
        case section(SidebarSection)
    }

    enum Connection: Equatable {
        /// No backend set up and demo data off: the app asks for the server and token
        case setup
        /// No backend set up, "Demo data" on in Settings: sample calls
        case demo
        case connecting
        case connected
        case unauthorized
        case offline(String)
    }

    /// Where messages live: in the general discussion or in questions about one call
    private enum Thread: Equatable {
        case discussion
        case conversation(Conversation.ID)
    }

    var conversations: [Conversation] = []
    var discussion: [Message] = []
    var selection: Selection = .discussion
    private(set) var connection: Connection = .setup
    private(set) var settings: BackendSettings?
    private(set) var experts: [Person] = []
    /// What the agent is doing in the open live call — the orb on the call screen follows it
    private(set) var agentActivity: OrbState = .idle
    /// Grows with every live transcript line, so the screen can follow along
    private(set) var liveRevision = 0
    private(set) var streamingID: Message.ID?
    /// Grows with every streamed chunk — the screen keeps scrolling down on it
    private(set) var streamRevision = 0
    let speech = SpeechPlayer()
    /// The answer that is being read out loud
    private(set) var listeningID: Message.ID?
    /// A one-line error to show in an alert
    var notice: String?
    /// Demo calls started from this phone: the backend replays them, there is no bot to remove
    private(set) var demoCallIDs: Set<String> = []

    @ObservationIgnored private var service: any ChatService = MockChatService()
    @ObservationIgnored private var streamTask: Task<Void, Never>?
    @ObservationIgnored private var syncTask: Task<Void, Never>?
    @ObservationIgnored private var watchTask: Task<Void, Never>?
    @ObservationIgnored private var activityTask: Task<Void, Never>?
    @ObservationIgnored private var liveFeed: LiveFeed?
    @ObservationIgnored private var prefetched: Set<String> = []
    /// Calls started from this phone that the list may not show yet
    @ObservationIgnored private var pending: [String: Date] = [:]
    @ObservationIgnored private var doneTasks: Set<String>
    @ObservationIgnored private var hasOpenedFirstCall = false
    @ObservationIgnored private var hasStarted = false

    /// The wake word the agent answers to (backend AGENT_NAME)
    static let agentName = "Atlas"

    init() {
        doneTasks = Set(UserDefaults.standard.stringArray(forKey: "doneTasks") ?? [])
    }

    /// Called once from RootView: SwiftUI can create stores it then throws away, so init does no work
    func start() {
        guard !hasStarted else { return }
        hasStarted = true
        if let saved = BackendSettings.load() {
            connect(saved)
        } else {
            useOffline()
        }
    }

    /// Settings → "Demo data": sample calls only when no backend is connected, off by default
    var demoDataEnabled: Bool { UserDefaults.standard.bool(forKey: "demoData") }

    func setDemoData(_ on: Bool) {
        UserDefaults.standard.set(on, forKey: "demoData")
        if !usesBackend { useOffline() }
    }

    var client: BackendClient? { settings.map(BackendClient.init) }
    var isConnected: Bool { connection == .connected }
    var usesBackend: Bool { settings != nil }

    // MARK: - Connection

    /// Checks the token with `GET /meetings` (as the web app does), then saves it and starts syncing
    func connect(url: URL, token: String) async -> String? {
        let candidate = BackendSettings(baseURL: url, token: token)
        do {
            _ = try await BackendClient(settings: candidate).meetings()
            candidate.save()
            connect(candidate)
            return nil
        } catch let error as BackendError where error.isUnauthorized {
            return "Wrong token."
        } catch {
            return error.localizedDescription
        }
    }

    func disconnect() {
        BackendSettings.clear()
        stopSync()
        useOffline()
    }

    private func connect(_ settings: BackendSettings) {
        stopSync()
        self.settings = settings
        connection = .connecting
        conversations = []
        discussion = []
        prefetched = []
        hasOpenedFirstCall = false
        selection = .discussion
        service = BackendChatService(client: BackendClient(settings: settings))
        startSync()
    }

    /// No backend: sample calls behind the "Demo data" toggle, otherwise nothing and a prompt to connect.
    /// Answers never come from OpenAI on the phone.
    private func useOffline() {
        settings = nil
        experts = []
        discussion = []
        if demoDataEnabled {
            connection = .demo
            service = MockChatService()
            conversations = SampleData.conversations
            selection = .conversation(SampleData.conversations[0].id)
        } else {
            connection = .setup
            service = NotConnectedChatService()
            conversations = []
            selection = .discussion
        }
    }

    private func stopSync() {
        syncTask?.cancel()
        syncTask = nil
        stopWatching()
        stop()
    }

    // MARK: - Sync

    private func startSync() {
        syncTask = Task { [weak self] in
            await self?.loadExperts()
            while !Task.isCancelled {
                guard let store = self else { return }
                await store.refresh()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    /// Pull-to-refresh and the 5-second sync
    func refresh() async {
        guard let client else { return }
        do {
            let items = try await client.meetings()
            // Disconnected or switched servers while the request was out
            guard settings == client.settings else { return }
            merge(items)
            connection = .connected
            if !hasOpenedFirstCall {
                hasOpenedFirstCall = true
                if case .discussion = selection, discussion.isEmpty, let newest = conversations.first {
                    open(newest.id)
                }
            }
            prefetchDetails()
        } catch {
            guard settings == client.settings, !Task.isCancelled else { return }
            if let error = error as? BackendError, error.isUnauthorized {
                tokenRejected()
            } else {
                connection = .offline(error.localizedDescription)
            }
        }
    }

    /// The server said the token is wrong: stop asking with it
    private func tokenRejected() {
        connection = .unauthorized
        syncTask?.cancel()
        stopWatching()
    }

    /// Pull-to-refresh on a call: the list and the open call
    func reloadCurrent() async {
        await refresh()
        guard let client, case .conversation(let id) = selection else { return }
        do {
            apply(try await client.meeting(id))
        } catch {
            notice = "Couldn't load this call. \(error.localizedDescription)"
        }
    }

    private func loadExperts() async {
        guard let client, let items = try? await client.experts() else { return }
        experts = items.map { Person(name: $0.name, role: $0.role, isOwner: $0.is_owner ?? false) }
    }

    private func merge(_ items: [MeetingDTO]) {
        let known = Dictionary(conversations.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let listed = Set(items.map(\.id))
        pending = pending.filter { !listed.contains($0.key) && $0.value.timeIntervalSinceNow > -60 }
        let waiting = conversations.filter { pending[$0.id] != nil }
        conversations = waiting + items.map { item in
            let isNew = known[item.id] == nil
            var conversation = known[item.id] ?? Conversation(id: item.id, title: "", date: .now)
            let wasLive = conversation.isLive
            conversation.title = item.title ?? ""
            conversation.date = Self.date(item.started_at) ?? conversation.date
            conversation.minutes = item.duration_min ?? conversation.minutes
            conversation.status = isNew
                ? CallStatus(rawValue: item.status ?? "") ?? .done
                : Self.advance(conversation.status, to: item.status)
            conversation.platform = item.platform
            conversation.mode = item.mode
            // A call that just ended gets its summary and tasks fetched again
            if wasLive && !conversation.isLive { prefetched.remove(item.id) }
            return conversation
        }
        // The open call changed state: follow it
        if case .conversation(let id) = selection, let current = conversation(id),
           current.isLive != (liveFeed != nil) {
            watchCurrent()
        }
    }

    /// Tasks and People need the full calls: fetch the newest ones in the background
    private func prefetchDetails() {
        guard let client else { return }
        let pending = conversations.prefix(15).filter { !$0.isLive && !prefetched.contains($0.id) }.map(\.id)
        guard !pending.isEmpty else { return }
        prefetched.formUnion(pending)
        Task {
            for id in pending {
                if let detail = try? await client.meeting(id) { apply(detail) }
            }
        }
    }

    // MARK: - Navigation

    func open(_ id: Conversation.ID) {
        selection = .conversation(id)
        watchCurrent()
    }

    func openDiscussion() {
        selection = .discussion
        stopWatching()
    }

    func newDiscussion() {
        stop()
        discussion.removeAll()
        openDiscussion()
    }

    func openSection(_ section: SidebarSection) {
        selection = .section(section)
        stopWatching()
    }

    /// Opens the call's WebSocket while it is live, and keeps the details fresh until the summary is written
    private func watchCurrent() {
        stopWatching()
        guard let client, case .conversation(let id) = selection else { return }
        let isLive = conversation(id)?.isLive ?? false
        if isLive, let url = client.liveURL(meetingID: id) {
            agentActivity = .listening
            // The WebSocket opens before the first fetch, so no line falls in between
            liveFeed = LiveFeed(
                meetingID: id, url: url,
                onEvent: { [weak self] event in self?.apply(event, to: id) },
                onRejected: { [weak self] in self?.tokenRejected() }
            )
        }
        watchTask = Task { [weak self] in
            var reported = false
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    self.apply(try await client.meeting(id))
                } catch {
                    let loaded = self.conversation(id)?.isDetailLoaded ?? true
                    if !reported, !loaded, !Task.isCancelled, !((error as? BackendError)?.isUnauthorized ?? false) {
                        reported = true
                        self.notice = "Couldn't load this call. \(error.localizedDescription) Pull down to retry."
                    }
                }
                guard let call = self.conversation(id) else { return }
                let waitingForSummary = call.status == .done && call.summary.isEmpty && !call.summaryIsLate
                guard call.isLive || waitingForSummary else { return }
                try? await Task.sleep(for: .seconds(4))
            }
        }
    }

    private func stopWatching() {
        liveFeed?.stop()
        liveFeed = nil
        watchTask?.cancel()
        watchTask = nil
        activityTask?.cancel()
        agentActivity = .idle
    }

    // MARK: - Applying backend data

    /// Only calls already in the list are updated, so a late answer can't bring back a call from another server
    private func apply(_ detail: MeetingDetailDTO) {
        guard let index = conversations.firstIndex(where: { $0.id == detail.id }) else { return }
        var call = conversations[index]
        call.title = detail.title ?? call.title
        call.date = Self.date(detail.started_at) ?? call.date
        call.minutes = detail.duration_min ?? call.minutes
        call.status = Self.advance(call.status, to: detail.status)
        call.platform = detail.platform ?? call.platform
        call.mode = detail.mode ?? call.mode
        call.summary = detail.summary ?? ""
        call.decisions = detail.decisions ?? []
        call.tasks = (detail.action_items ?? []).map { task($0, in: detail.id) }
        // A poll that left before a WebSocket event must not hide or roll back what the event brought
        call.factChecks = Self.merged(call.factChecks, (detail.fact_checks ?? []).map(Self.factCheck))
        call.escalations = Self.merged(call.escalations, (detail.escalations ?? []).map(Self.escalation)) { old, new in
            old.status != .waiting && new.status == .waiting
        }
        // Lines that arrived over the WebSocket stay; the fetch fills in the rest
        var lines = Dictionary(call.transcript.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        for line in (detail.utterances ?? []).map(Self.utterance) + (detail.agent_said ?? []).map(Self.agentLine) {
            lines[line.id] = line
        }
        call.transcript = Self.sorted(Array(lines.values))
        call.isDetailLoaded = true
        conversations[index] = call
    }

    private func apply(_ event: LiveEvent, to id: Conversation.ID) {
        guard let index = conversations.firstIndex(where: { $0.id == id }) else { return }
        switch event {
        case .utterance(let dto):
            let line = Self.utterance(dto)
            guard !conversations[index].transcript.contains(where: { $0.id == line.id }) else { return }
            conversations[index].transcript = Self.sorted(conversations[index].transcript + [line])
            liveRevision += 1
            if line.text.localizedCaseInsensitiveContains(Self.agentName) { setActivity(.thinking, for: 20) }
        case .agentSaid(let dto):
            let line = Self.agentLine(dto)
            guard !conversations[index].transcript.contains(where: { $0.id == line.id }) else { return }
            conversations[index].transcript = Self.sorted(conversations[index].transcript + [line])
            liveRevision += 1
            setActivity(.speaking, for: 5)
        case .factCheck(let dto):
            let check = Self.factCheck(dto)
            conversations[index].factChecks.removeAll { $0.id == check.id }
            conversations[index].factChecks.append(check)
        case .escalation(let dto):
            let escalation = Self.escalation(dto)
            if let existing = conversations[index].escalations.firstIndex(where: { $0.id == escalation.id }) {
                conversations[index].escalations[existing] = escalation
            } else {
                conversations[index].escalations.append(escalation)
            }
        case .status(let raw):
            conversations[index].status = Self.advance(conversations[index].status, to: raw)
            if !conversations[index].isLive { callEnded(id) }
        case .ended(let raw, let minutes):
            conversations[index].status = raw.flatMap(CallStatus.init(rawValue:)) ?? .done
            conversations[index].minutes = minutes ?? conversations[index].minutes
            callEnded(id)
        }
    }

    private func callEnded(_ id: Conversation.ID) {
        liveFeed?.stop()
        liveFeed = nil
        activityTask?.cancel()
        agentActivity = .idle
        prefetched.remove(id)
        // Keep fetching until the post-call summary is there
        if case .conversation(let open) = selection, open == id { watchCurrent() }
    }

    /// The orb goes back to listening after a while
    private func setActivity(_ state: OrbState, for seconds: Double) {
        agentActivity = state
        activityTask?.cancel()
        activityTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(seconds))
            guard !Task.isCancelled, let self, self.liveFeed != nil else { return }
            self.agentActivity = .listening
        }
    }

    /// Item ids are only unique within a call (`ai_00`…), so they get the call's id in front
    private func task(_ dto: ActionItemDTO, in meetingID: String) -> TaskItem {
        let id = "\(meetingID)/\(dto.id)"
        return TaskItem(
            id: id,
            title: dto.text,
            owner: dto.owner.flatMap { $0.isEmpty ? nil : Person(name: $0) },
            due: dto.due,
            jiraKey: dto.jira_key,
            jiraURL: dto.jira_url.flatMap(URL.init(string:)),
            isDone: doneTasks.contains(id)
        )
    }

    /// The backend never reopens a call: once done or failed, a stale response can't make it live again
    private static func advance(_ current: CallStatus, to raw: String?) -> CallStatus {
        guard let next = raw.flatMap(CallStatus.init(rawValue:)) else { return current }
        return current == .done || current == .failed ? current : next
    }

    /// The fetched items win, unless `keepOld` says the one we have is newer; items only the WebSocket brought stay
    private static func merged<Item: Identifiable>(
        _ current: [Item], _ fetched: [Item], keepOld: (Item, Item) -> Bool = { _, _ in false }
    ) -> [Item] where Item.ID == String {
        let old = Dictionary(current.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        let fetchedIDs = Set(fetched.map(\.id))
        let updated = fetched.map { item in old[item.id].map { keepOld($0, item) ? $0 : item } ?? item }
        return updated + current.filter { !fetchedIDs.contains($0.id) }
    }

    private static func utterance(_ dto: UtteranceDTO) -> Utterance {
        let name = (dto.speaker ?? "").trimmingCharacters(in: .whitespaces)
        return Utterance(id: dto.id, speaker: Person(name: name.isEmpty ? "Participant" : name), offset: Int(dto.ts ?? 0), text: dto.text)
    }

    private static func agentLine(_ dto: AgentSaidDTO) -> Utterance {
        Utterance(id: "agent-\(dto.id)", speaker: Person(name: agentName, isAgent: true), offset: Int(dto.ts ?? 0), text: dto.text)
    }

    private static func factCheck(_ dto: FactCheckDTO) -> FactCheck {
        FactCheck(
            id: dto.id, claim: dto.claim,
            verdict: FactCheck.Verdict(rawValue: dto.verdict ?? "") ?? .unverified,
            source: dto.source, correction: dto.correction, offset: Int(dto.ts ?? 0)
        )
    }

    private static func escalation(_ dto: EscalationDTO) -> Escalation {
        Escalation(
            id: dto.id, expert: dto.expert, channel: dto.channel, question: dto.question,
            askedBy: dto.asked_by, offset: Int(dto.ts ?? 0),
            status: Escalation.Status(rawValue: dto.status ?? "") ?? .waiting, answer: dto.answer
        )
    }

    private static func sorted(_ lines: [Utterance]) -> [Utterance] {
        lines.sorted { $0.offset == $1.offset ? $0.id < $1.id : $0.offset < $1.offset }
    }

    private static func date(_ text: String?) -> Date? {
        guard let text else { return nil }
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: text) { return date }
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: text)
    }

    // MARK: - Call actions

    /// A demo call: the backend replays a stand-up through its real webhooks, slowly enough to watch
    func startDemoCall() async {
        guard let client else {
            notice = "Connect to the backend in Settings first."
            return
        }
        do {
            let id = try await client.simulateCall(speed: 2)
            pending[id] = .now
            demoCallIDs.insert(id)
            conversations.removeAll { $0.id == id }
            conversations.insert(
                Conversation(id: id, title: "Simulated stand-up", date: .now, status: .joining, platform: "google_meet", mode: "delegate"),
                at: 0
            )
            open(id)
        } catch {
            notice = "Couldn't start the demo call. \(error.localizedDescription)"
        }
    }

    /// Sends the agent into a real Meet / Zoom / Teams call
    func joinCall(url: String, mode: String, brief: String) async -> String? {
        guard let client else { return "Connect to the backend in Settings first." }
        do {
            let call = try await client.joinCall(url: url, mode: mode, brief: brief)
            pending[call.id] = .now
            conversations.removeAll { $0.id == call.id }
            conversations.insert(
                Conversation(
                    id: call.id, title: call.title ?? "", date: Self.date(call.started_at) ?? .now,
                    status: CallStatus(rawValue: call.status ?? "") ?? .joining, platform: call.platform, mode: call.mode
                ),
                at: 0
            )
            open(call.id)
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    func leaveCurrentCall() async {
        guard let client, case .conversation(let id) = selection else { return }
        do {
            try await client.leave(id)
        } catch {
            notice = error.localizedDescription
        }
    }

    /// Answers the agent's question as the expert would on Slack; the answer comes back over the WebSocket
    func replyAsExpert(_ escalation: Escalation, text: String) async {
        guard let client, let meetingID = conversations.first(where: { $0.escalations.contains { $0.id == escalation.id } })?.id else { return }
        do {
            try await client.replyAsExpert(escalationID: escalation.id, text: text)
            // A finished call has no WebSocket: fetch the answer
            try? await Task.sleep(for: .seconds(1))
            if let detail = try? await client.meeting(meetingID) { apply(detail) }
        } catch {
            notice = "Couldn't send the reply. \(error.localizedDescription)"
        }
    }

    /// Reads an answer out loud in the server's voice; again on the same answer stops it
    func listen(to message: Message) {
        guard let client else {
            notice = "Connect to the backend to hear answers."
            return
        }
        if listeningID == message.id && (speech.isPlaying || speech.isLoading) {
            stopListening()
            return
        }
        listeningID = message.id
        speech.speak(message.text, using: client)
    }

    func stopListening() {
        speech.stop()
        listeningID = nil
    }

    func isListening(to message: Message) -> Bool {
        listeningID == message.id && (speech.isPlaying || speech.isLoading)
    }

    // MARK: - Reading

    func conversation(_ id: Conversation.ID) -> Conversation? {
        conversations.first { $0.id == id }
    }

    var currentConversation: Conversation? {
        guard case .conversation(let id) = selection else { return nil }
        return conversation(id)
    }

    var currentMessages: [Message] { currentThread.map(messages(in:)) ?? [] }
    var lastAssistantMessage: Message? { currentMessages.last { $0.role == .assistant } }
    var isStreaming: Bool { streamingID != nil }
    var streamingMessage: Message? {
        streamingID.flatMap { id in currentMessages.first { $0.id == id } }
    }

    /// Experts from the backend and everyone who spoke in a call
    var people: [Person] {
        var byName: [String: Person] = [:]
        for expert in experts { byName[expert.name] = expert }
        for person in conversations.flatMap(\.people) where byName[person.name] == nil {
            byName[person.name] = person
        }
        return byName.values.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }

    var projects: [String] {
        var seen = Set<String>()
        return conversations.compactMap(\.project).filter { seen.insert($0).inserted }
    }

    struct DayGroup: Identifiable {
        let day: Date
        let items: [Conversation]
        var id: Date { day }
    }

    var conversationsByDay: [DayGroup] {
        let calendar = Calendar.current
        let groups = Dictionary(grouping: conversations) { calendar.startOfDay(for: $0.date) }
        return groups.keys.sorted(by: >).map { day in
            DayGroup(day: day, items: groups[day, default: []].sorted { $0.date > $1.date })
        }
    }

    func conversations(in project: String) -> [Conversation] {
        conversations.filter { $0.project == project }
    }

    func conversations(with person: Person) -> [Conversation] {
        conversations.filter { call in
            call.people.contains { $0.name == person.name }
                || call.tasks.contains { $0.owner?.name == person.name }
                || call.escalations.contains { $0.expert == person.name }
        }
    }

    // MARK: - Tasks

    func toggleTask(_ id: TaskItem.ID) {
        for c in conversations.indices {
            if let t = conversations[c].tasks.firstIndex(where: { $0.id == id }) {
                conversations[c].tasks[t].isDone.toggle()
                if conversations[c].tasks[t].isDone { doneTasks.insert(id) } else { doneTasks.remove(id) }
                UserDefaults.standard.set(Array(doneTasks), forKey: "doneTasks")
                return
            }
        }
    }

    // MARK: - Questions to the assistant

    func send(_ text: String) {
        guard !isStreaming, let thread = currentThread else { return }
        update(thread) { $0.append(Message(role: .user, text: text)) }
        startReply(in: thread)
    }

    func stop() {
        streamTask?.cancel()
        streamTask = nil
        streamingID = nil
    }

    func regenerate() {
        guard !isStreaming, let thread = currentThread,
              messages(in: thread).last?.role == .assistant else { return }
        update(thread) { $0.removeLast() }
        startReply(in: thread)
    }

    func toggleFeedback(_ feedback: Message.Feedback, for messageID: Message.ID) {
        updateMessage(messageID) { $0.feedback = $0.feedback == feedback ? nil : feedback }
    }

    /// Sample calls only: the backend has no rename
    func renameCurrent(to title: String) {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !usesBackend, case .conversation(let id) = selection, !trimmed.isEmpty,
              let index = conversations.firstIndex(where: { $0.id == id }) else { return }
        conversations[index].title = trimmed
    }

    /// Deletes a sample call or clears the discussion
    func deleteCurrent() {
        stop()
        switch selection {
        case .conversation(let id):
            guard !usesBackend else { return }
            conversations.removeAll { $0.id == id }
            selection = conversations.first.map { .conversation($0.id) } ?? .discussion
        case .discussion:
            discussion.removeAll()
        case .section:
            break
        }
    }

    // MARK: - Private

    private var currentThread: Thread? {
        switch selection {
        case .discussion: .discussion
        case .conversation(let id): .conversation(id)
        case .section: nil
        }
    }

    private func messages(in thread: Thread) -> [Message] {
        switch thread {
        case .discussion: discussion
        case .conversation(let id): conversation(id)?.messages ?? []
        }
    }

    private func update(_ thread: Thread, _ change: (inout [Message]) -> Void) {
        switch thread {
        case .discussion:
            change(&discussion)
        case .conversation(let id):
            if let index = conversations.firstIndex(where: { $0.id == id }) {
                change(&conversations[index].messages)
            }
        }
    }

    private func updateMessage(_ id: Message.ID, _ change: (inout Message) -> Void) {
        if let m = discussion.firstIndex(where: { $0.id == id }) {
            change(&discussion[m])
            return
        }
        for c in conversations.indices {
            if let m = conversations[c].messages.firstIndex(where: { $0.id == id }) {
                change(&conversations[c].messages[m])
                return
            }
        }
    }

    private func startReply(in thread: Thread) {
        let history = messages(in: thread)
        let context = context(for: thread)
        let reply = Message(role: .assistant, text: "")
        update(thread) { $0.append(reply) }
        streamingID = reply.id

        let service = service
        streamTask = Task {
            do {
                for try await chunk in service.reply(to: history, context: context) {
                    self.updateMessage(reply.id) { $0.text += chunk }
                    self.streamRevision += 1
                }
            } catch {
                let reason = error.localizedDescription
                self.updateMessage(reply.id) { $0.text += "\n\n*Couldn't get a response. \(reason)*" }
            }
            if self.streamingID == reply.id { self.streamingID = nil }
        }
    }

    private func context(for thread: Thread) -> ChatContext {
        let titles = Dictionary(conversations.map { ($0.id, $0.displayTitle) }, uniquingKeysWith: { first, _ in first })
        switch thread {
        case .conversation(let id):
            guard let call = conversation(id) else {
                return ChatContext(scope: .allConversations(titles: []), titles: titles)
            }
            let summary = call.summary.components(separatedBy: .newlines)
                .map { $0.trimmingCharacters(in: CharacterSet(charactersIn: "-•* ")) }
                .filter { !$0.isEmpty }
            return ChatContext(
                scope: .conversation(title: call.displayTitle),
                summary: summary + call.decisions,
                tasks: call.tasks.filter { !$0.isDone }.map(Self.describe),
                people: call.people.map(\.name),
                transcript: call.transcript.map { "\($0.speaker.name): \($0.text)" }.joined(separator: "\n"),
                titles: titles
            )
        case .discussion:
            let ranked = people
                .map { person in (person, conversations(with: person).count) }
                .sorted { $0.1 > $1.1 }
            return ChatContext(
                scope: .allConversations(titles: conversations.map(\.displayTitle)),
                tasks: conversations.flatMap { $0.tasks.filter { !$0.isDone }.map(Self.describe) },
                people: ranked.map { "**\($0.0.name)** — \($0.1)" },
                titles: titles
            )
        }
    }

    private static func describe(_ task: TaskItem) -> String {
        task.owner.map { "**\($0.name):** \(task.title)" } ?? task.title
    }
}
