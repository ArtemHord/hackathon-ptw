# Decisions (one line each, newest on top)

Agents and `@codex review` check PRs against this file.

| # | Decision | Why |
|---|----------|-----|
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
