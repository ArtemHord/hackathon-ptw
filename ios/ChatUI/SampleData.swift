import SwiftUI

/// Demo calls shown until the app is connected to the backend. Times are relative to now, so the calendar looks alive.
enum SampleData {
    static let you = Person(name: "Artem", role: "Owner", isOwner: true)
    static let atlas = Person(name: "Atlas", isAgent: true)
    static let anna = Person(name: "Anna", role: "Design")
    static let oleg = Person(name: "Oleg", role: "iOS")
    static let iryna = Person(name: "Iryna", role: "Client")
    static let max = Person(name: "Max", role: "Backend")
    static let sofia = Person(name: "Sofia", role: "Research")
    static let taras = Person(name: "Taras")

    /// A moment in the past, rounded down to 5 minutes
    private static func ago(hours: Double) -> Date {
        let date = Date().addingTimeInterval(-hours * 3600)
        return Date(timeIntervalSinceReferenceDate: (date.timeIntervalSinceReferenceDate / 300).rounded(.down) * 300)
    }

    private static func bullets(_ items: [String]) -> String {
        items.map { "- \($0)" }.joined(separator: "\n")
    }

    /// Transcript lines with ids from the call and their position
    private static func lines(_ call: String, _ items: [(Person, Int, String)]) -> [Utterance] {
        items.enumerated().map { index, item in
            Utterance(id: "\(call)-u\(index)", speaker: item.0, offset: item.1, text: item.2)
        }
    }

    static let conversations: [Conversation] = [
        Conversation(
            id: "sample-design",
            title: "App design discussion",
            date: ago(hours: 1.5),
            minutes: 42,
            platform: "google_meet",
            mode: "delegate",
            summary: bullets([
                "The bottom navigation stays native: `TabView` with Liquid Glass, like in Apple Music.",
                "Sidebar: Calendar, Projects, People and Tasks, with recent calls below.",
                "Each call opens as a summary, tasks to check and the full transcript.",
            ]),
            decisions: ["Use the native iOS 26 components instead of custom navigation."],
            tasks: [
                TaskItem(id: "sample-design-t1", title: "Prepare the sidebar mockup", owner: anna, due: "Friday"),
                TaskItem(id: "sample-design-t2", title: "Build a SwiftUI prototype", owner: oleg),
                TaskItem(id: "sample-design-t3", title: "Send the transcript to the team", owner: you, isDone: true),
            ],
            factChecks: [
                FactCheck(id: "sample-design-f1", claim: "Liquid Glass ships with iOS 26", verdict: .confirmed, source: "Apple Human Interface Guidelines", correction: nil, offset: 7),
            ],
            transcript: lines("sample-design", [
                (you, 0, "Hi! Let's go through the main screen and the sidebar."),
                (anna, 7, "I suggest we don't draw the navigation ourselves and use the native iOS 26 components. The Liquid Glass tab bar looks almost like Apple Music."),
                (oleg, 21, "Agreed. In SwiftUI it's `TabView` plus `.tabViewBottomAccessory` for the mini player — just a few lines of code."),
                (you, 34, "What about the sidebar? I like it when the main screen slides to the right."),
                (anna, 42, "Let's do that. Sections at the top: Calendar, Projects, People and Tasks, and recent calls below."),
                (oleg, 58, "Atlas, when is the design review?"),
                (atlas, 61, "The design review is on Thursday at 11:00, according to the team calendar."),
                (you, 72, "And I want the text to scroll nicely under the glass buttons."),
                (oleg, 79, "That's what `safeAreaBar` is for — the system blurs the text under the bars."),
                (anna, 91, "Then I'll have the sidebar mockup ready by Friday, and Oleg will build the prototype."),
                (you, 100, "Great, I'll send everyone the transcript. Thanks!"),
            ])
        ),
        Conversation(
            id: "sample-client",
            title: "Client call about the MVP",
            date: ago(hours: 4.2),
            minutes: 28,
            platform: "zoom",
            mode: "notetaker",
            summary: bullets([
                "The client needs an MVP in six weeks: recording, transcripts and search.",
                "Calendar integration moves to version two.",
                "The budget will be approved after next Tuesday's demo.",
            ]),
            decisions: ["Calendar integration waits for version two."],
            tasks: [
                TaskItem(id: "sample-client-t1", title: "Send the timeline estimate", owner: you),
                TaskItem(id: "sample-client-t2", title: "Prepare the demo for Tuesday", owner: you, due: "Tuesday"),
            ],
            escalations: [
                Escalation(id: "sample-client-e1", expert: "Max", channel: "slack", question: "Can we export transcripts as PDF in the MVP?", askedBy: "Iryna", offset: 22, status: .answered, answer: "Yes, PDF export is a one-day task."),
            ],
            transcript: lines("sample-client", [
                (iryna, 0, "Good afternoon! It's important for us to launch as soon as possible."),
                (you, 9, "Understood. What absolutely has to be in the first version?"),
                (iryna, 15, "Recording, the transcript and search in it. The calendar can wait."),
                (iryna, 22, "Atlas, can we export transcripts as PDF?"),
                (atlas, 25, "I'm not sure, so I've asked Max on Slack. I'll tell you as soon as he answers."),
                (you, 31, "Then six weeks works. I'll show you a demo by Tuesday."),
                (atlas, 40, "Max says PDF export is a one-day task, so it fits the MVP."),
            ])
        ),
        Conversation(
            id: "sample-sync",
            title: "Weekly team sync",
            date: ago(hours: 26),
            minutes: 35,
            platform: "google_meet",
            mode: "notetaker",
            summary: bullets([
                "Release 1.2 moves by a week because of onboarding fixes.",
                "Sofia will run two more user interviews.",
            ]),
            decisions: ["Release 1.2 moves by one week."],
            tasks: [
                TaskItem(id: "sample-sync-t1", title: "Update the release plan", owner: max),
                TaskItem(id: "sample-sync-t2", title: "Schedule two interviews", owner: sofia, isDone: true),
            ],
            transcript: lines("sample-sync", [
                (you, 0, "Let's start with the release. How are we on timing?"),
                (max, 6, "Onboarding still needs fixes, so I suggest moving the release by a week."),
                (sofia, 18, "That gives me time to run two interviews and test the new screens."),
                (anna, 29, "I'll update the onboarding mockups by Wednesday."),
            ])
        ),
        Conversation(
            id: "sample-interview",
            title: "User interview #3",
            date: ago(hours: 50),
            minutes: 51,
            platform: "teams",
            mode: "notetaker",
            summary: bullets([
                "The user finds old calls through the calendar, not search.",
                "What matters most in a transcript is seeing quickly who said what and what needs to be done.",
            ]),
            tasks: [
                TaskItem(id: "sample-interview-t1", title: "Add a people filter to search", owner: anna),
            ],
            transcript: lines("sample-interview", [
                (sofia, 0, "How do you find the call you need today?"),
                (taras, 7, "I usually remember when it was and scroll through the calendar. I rarely use search."),
                (sofia, 19, "And what matters most when you open a transcript?"),
                (taras, 24, "Quickly seeing who said what and what I need to do."),
            ])
        ),
        Conversation(
            id: "sample-release",
            title: "Release 1.2 planning",
            date: ago(hours: 98),
            minutes: 23,
            platform: "google_meet",
            mode: "delegate",
            summary: bullets([
                "Transcript search and tasks to check go into the release.",
                "Dark mode gets finished before the code freeze.",
            ]),
            tasks: [
                TaskItem(id: "sample-release-t1", title: "Check dark mode on every screen", owner: oleg),
                TaskItem(id: "sample-release-t2", title: "Write the release notes", owner: you),
            ],
            transcript: lines("sample-release", [
                (max, 0, "Let's lock what goes into 1.2."),
                (oleg, 5, "Transcript search and tasks will definitely make it."),
                (you, 14, "Good. And we'll finish dark mode before the code freeze."),
            ])
        ),
        Conversation(
            id: "sample-onboarding",
            title: "Onboarding ideas",
            date: ago(hours: 196),
            minutes: 15,
            platform: "zoom",
            mode: "notetaker",
            summary: bullets([
                "Three-screen onboarding: record, read the transcript, act on the tasks.",
                "We offer to record the first call right after sign-in.",
            ]),
            tasks: [
                TaskItem(id: "sample-onboarding-t1", title: "Draw the three onboarding screens", owner: anna, isDone: true),
            ],
            transcript: lines("sample-onboarding", [
                (anna, 0, "I'd show the value in three steps: you record, you read, you act on the tasks."),
                (you, 12, "And right away we offer to record the first call."),
            ])
        ),
    ].map { call in
        var call = call
        call.isDetailLoaded = true
        return call
    }
}
