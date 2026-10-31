# Decisions (one line each, newest on top)

Agents and `@codex review` check PRs against this file.

| # | Decision | Why |
|---|----------|-----|
| 26 | Wake word: keep `recallai_streaming` low-latency (key_terms unsupported in that mode, R3); fuzzy trigger in first 3 tokens + question check; backup triggers `POST /meetings/{id}/ask` (app "Ask agent", contract change approved by Artem 05:10) and `/debug/ask` | Live test: "Crew" heard as "cat"/"crap"; Deepgram keyterms needs extra account + dashboard setup |
| 25 | Orchestrator keeps all KB docs in the prompt while total < 20k chars; pgvector top-6 only above that. RAG (`rag.search`) serves `/chat` and post-call | 3 small seed docs: full context is more accurate and saves a ~300 ms embedding call on the 3–5 s voice path |
| 24 | Agent camera = designer orb (`docs/design/agent-clips/`), ported to vanilla JS in the agent page (no React/Babel in Recall's bot browser). Page states idle/listening/thinking/speaking + ask; server→page WS `state` / `ask` / `ask_done`; listening from page-mic level; plate shows "ASKING <EXPERT> ON SLACK" (design placeholder "YES, ATLAS" dropped) | Visible wow on stage; React + Babel standalone (3 MB) too heavy for the bot browser |
| 23 | OpenAI called via plain httpx (`backend/app/llm.py`, `/v1/chat/completions`, strict json_schema), not the openai SDK; embeddings (M4.1) go through llm.py too | openai SDK 3.x uses httpx2, which respx does not intercept → tests hit the real API |
| 22 | Agent page lives in `backend/agent_page/index.html` (not repo-root `agent-page/`), served at `GET /agent` | Railway build context = `backend/`; one image, no extra config |
| 21 | Recall auth header `Authorization: Token <RECALL_API_KEY>` (prefix optional); DB `meetings.mode` stores API enum `notetaker|delegate` (no CHECK; column default `notes` is cosmetic) | https://docs.recall.ai/docs/authentication |
| 20 | Slack: ignore events with `bot_id`, `subtype=bot_message` or `user` == our bot user (`auth.test`); dedupe by `event_id`, skip if `X-Slack-Retry-Num` present (bot_id field UNCONFIRMED in fetched page) | https://docs.slack.dev/reference/events/message · https://docs.slack.dev/apis/events-api/ |
| 19 | Slack signature: `v0=` + hex HMAC-SHA256(signing_secret, `v0:{X-Slack-Request-Timestamp}:{raw body}`) vs `X-Slack-Signature`, `hmac.compare_digest`, reject if ts >5 min off; `url_verification` → 200 `{"challenge": ...}`; answer <3 s | https://docs.slack.dev/authentication/verifying-requests-from-slack · https://docs.slack.dev/reference/events/url_verification |
| 18 | Recall leave: `POST /api/v1/bot/{id}/leave_call/` | https://docs.recall.ai/reference/bot_leave_call_create |
| 17 | Recall meeting chat: `POST /api/v1/bot/{id}/send_chat_message/`; body `{"to":"everyone","message":...}` CONFIRMED (R2); Meet caps chat at 500 chars → truncated; Meet supports bot chat | https://docs.recall.ai/reference/bot_send_chat_message_create |
| 16 | Recall status: dashboard webhook (per region, all bots) → `POST /webhooks/recall/status`; events `bot.joining_call`, `bot.in_waiting_room`, `bot.in_call_not_recording`, `bot.in_call_recording`, `bot.call_ended`, `bot.done`, `bot.fatal`; bot id `data.bot.id`, code `data.data.code`; post-call runs on `bot.done` (not `call_ended`) | https://docs.recall.ai/docs/bot-status-change-events |
| 15 | Recall waiting room: `automatic_leave.waiting_room_timeout` (seconds, min 30) | https://docs.recall.ai/reference/bot_create |
| 14 | Recall transcript: `recording_config.transcript.provider.recallai_streaming` with `mode: prioritize_low_latency`, `language_code: en` (default accuracy mode lags minutes) + `realtime_endpoints: [{type: webhook, url: <PUBLIC_BASE_URL>/webhooks/recall/transcript?meeting_id=&token=, events: [transcript.data]}]` | https://docs.recall.ai/reference/bot_create |
| 13 | Recall `output_media` (`camera.kind=webpage`, `config.url=<PUBLIC_BASE_URL>/agent`) + `recording_config` in ONE `POST /api/v1/bot/` (both top-level keys of Create Bot; no doc example of both → confirm on first live join M1.1); page URL must be public | https://docs.recall.ai/reference/bot_create · https://docs.recall.ai/docs/stream-media |
| 12 | Demo only on Google Meet; Zoom/Teams = same Recall API, not shown on stage | Least risk |
| 11 | Demo in English | Recall low-latency transcription is English-only |
| 10 | Agent speaks only when addressed "Crew"; TTS pipeline, not a full voice agent in the call | A full agent would interrupt people |
| 9 | Knowledge base changes only after human Approve | One ASR error would corrupt docs |
| 8 | Slack = main escalation channel, Telegram = fallback, both behind `Notifier` | Teams live in Slack |
| 7 | One demo user + static `DEMO_TOKEN`; every webhook/WS checks a token | No time for real auth, still no open endpoints |
| 6 | One FastAPI instance, in-memory WS hub, `asyncio.create_task`, no queue | Simplicity |
| 5 | Until M4 KB docs go straight into the prompt; pgvector RAG after | Ship the hero loop first |
| 4 | API contract = `docs/API.pl.md` + `mocks/*.json`, frozen after M0 | iOS app built in parallel on mocks |
| 3 | Supabase Postgres + pgvector (EU), no separate vector DB | Fewer services |
| 2 | Recall.ai (eu-central-1) for bots in Meet/Zoom/Teams | One API, voice via Output Media |
| 1 | Backend: Python 3.12 + uv + FastAPI; mobile: SwiftUI (iOS) | Team skills, SPEC "Decyzje" |
