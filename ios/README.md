# Call to Action — iOS app (SwiftUI)

The phone app for Call Crew. It shows every call the agent joined, live while it happens, and lets you ask about your calls.
It talks only to the backend (`docs/API.pl.md`): no OpenAI, ElevenLabs, Recall or Supabase keys on the phone.

- **Recents / Calendar / Projects / People / Tasks** — calls from `GET /meetings`, synced every 5 s; details from `GET /meetings/{id}`.
- **A live call** — WebSocket `/app/ws`: the transcript streams in, the orb follows the agent (hears "Atlas" → thinking, `agent_said` → answering), questions to experts and fact-checks appear as they happen, status flips to Done and the summary, decisions and tasks arrive.
- **Asked experts** — "Reply as …" answers a waiting question the way the expert would on Slack (`POST /debug/expert-reply`).
- **Discuss** — questions go to `POST /chat`; answers list their sources, and a source opens the call it quotes. "Listen" plays the answer in the server's ElevenLabs voice (`POST /tts`). A question asked by voice is answered out loud.
- **New call** — "Run a demo call" (`POST /debug/simulate`: a stand-up replayed through the real webhooks) or "Send Atlas to the call" with a Meet / Zoom / Teams link (`POST /meetings`). "Remove Atlas from the call" in the ⋯ menu (`POST /meetings/{id}/leave`).
- Voice input uses Apple's speech recognition on the iPhone, no key needed: the on-device SpeechAnalyzer (iOS 26) once its model is downloaded, SFSpeechRecognizer until then. The Simulator has no speech model, so there voice input needs `ELEVENLABS_API_KEY` or `OPENAI_API_KEY` in `Secrets.env`.
- No token → sample calls, so the design can be shown offline.

## Run

Xcode 26+, iOS 26 simulator or device.

```bash
open ios/ChatUI.xcodeproj
```

Run the **ChatUI** scheme. Then **Settings → Backend**: the server is prefilled with Railway production; paste `DEMO_TOKEN` (Railway → Variables) and tap **Connect**. The token is checked with `GET /meetings` and kept in the Keychain.

Instead of typing it, you can put it in `ios/ChatUI/Secrets.env` (git-ignored; copy `ios/Secrets.example.env`):

```
CALLCREW_BASE_URL=https://hackathon-ptw-production.up.railway.app
CALLCREW_DEMO_TOKEN=…
```

Launch environment variables with the same names win over the file (Xcode scheme → Run → Environment, or `SIMCTL_CHILD_CALLCREW_DEMO_TOKEN=… xcrun simctl launch …`). Release builds leave `Secrets.env` out (`EXCLUDED_SOURCE_FILE_NAMES`), so it never ships in an archive.

### Against a local backend

Start the backend as in `AGENTS.md`, then point the app at it, for example `CALLCREW_BASE_URL=http://127.0.0.1:8000`. Plain `http` works for `127.0.0.1` and `*.local` only (`ChatUI-Info.plist`: `NSAllowsLocalNetworking`). Without `OPENAI_API_KEY` on the backend the call still streams in, but the agent stays silent and there is no summary; without ElevenLabs, Listen says the server has no voice.

## Demo in the app

1. Sidebar → **+** → **Run a demo call**. The call opens with a LIVE badge; lines appear as they are said.
2. "Atlas, …" lines make the orb think; the agent's answers show up as **Atlas · AI** in the transcript.
3. A question the agent can't answer appears under **Asked experts** → **Reply as Dima** → the agent says it in the call.
4. When the call ends: summary, decisions, tasks to check (owner, due date, Jira link), fact-checks.
5. **Discuss** (or the field under a call): "What did Dima say about the migration?" → the answer with sources → tap a source to open the call.

## Code map (`ChatUI/`)

| File | What |
|---|---|
| `Backend.swift` | `BackendClient` (REST, Bearer token, error envelope), DTOs, `LiveEvent` + `LiveFeed` (WebSocket, reconnect, 4401 = wrong token), token in the Keychain |
| `ConversationStore.swift` | Sync loop, live call, demo call, expert replies, tasks, the chat thread |
| `ChatService.swift` | `BackendChatService` (`/chat` + sources), offline demo answers |
| `Speech.swift` | On-device speech-to-text, playback of `/tts` |
| `Models.swift` | Call, transcript line, task, fact-check, question to an expert |
| `ConversationViews.swift`, `ChatScreen.swift`, `SidebarView.swift`, `SectionScreens.swift`, `Sheets.swift` | Screens |
| `Orb.swift`, `Animations/` | The orb: the designer's SVG animations baked to HEVC-with-alpha (`Tools/bake-orb.swift`) |

## Not in the app yet

- Knowledge base and fact-check proposals (`/kb/*`), creating Jira issues from tasks.
- Done state of a task is kept on the phone: the backend has no field for it.
- Projects are the call's platform (Meet / Zoom / Teams): the backend has no projects.
