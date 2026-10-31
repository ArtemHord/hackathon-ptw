# STATUS — Call Crew backend

Owned by the orchestrator: updated after every task. Times are Europe/Warsaw.

## Now
- Milestone: M1
- In progress: M1.2 transcript webhook + /app/ws hub (senior-developer)
- Blocked: —

## Plan (re-baselined 03:00; SPEC "Plan do freeze o 11:00")
Cut rules: escalation not end-to-end by 06:30 → drop M5. After 08:30 → bug fixes only. 11:00 → freeze. If M2 not done by 05:30 → start M3 anyway.
Hosting: `PUBLIC_BASE_URL` = Railway domain (EU, auto-deploy from main); Slack + Recall webhooks point there; ngrok only as fallback for live debugging. During demo runs and after 08:30: no push to main without Artem's OK (deploy wipes in-memory WS hub + active escalations).

### M0 · Fundament (target 03:45) — DONE 03:08 — order M0.1 → M0.2 → M0.4 → M0.3
- [x] M0.1 Backend skeleton: uv, FastAPI, `/health`, config (all SPEC env vars), ruff, pytest, root `.env.example`
- [x] M0.2 API contract: `docs/API.pl.md` + `mocks/*.json` incl. `/app/ws` events (Misha blocked on it)
- [x] M0.4 `backend/Dockerfile` (uvicorn on `0.0.0.0:${PORT:-8000}`), Railway root `backend/`, healthcheck `/health`
- [x] M0.3 Migrations `001_init.sql` (all tables + `vector`) + `scripts/migrate.py` (idempotent; Supabase Session pooler 5432)

### M1 · Agent in the call (target 04:30)
- [x] M1.1 Recall client, `POST /meetings`, `POST /meetings/{id}/leave`; bot joins Google Meet
- [ ] M1.2 Transcript webhook → `utterances`, dedup, WS event
- [ ] M1.3 Bot status webhook
- [ ] M1.4 `scripts/simulate_meeting.py` + demo-scenario fixture

### M2 · Agent speaks (target 05:30)
- [ ] M2.1 Agent page + `/agent-page/ws`; a test phrase is audible in the call
- [ ] M2.2 ElevenLabs TTS + `POST /tts` + cached "One sec…"
- [ ] M2.3 Name trigger "Crew" → LLM (brief + docs in prompt) → voice; measure latency
- [ ] M2.4 Delegate brief

### M3 · Slack escalation — HERO (target 06:30)
- [ ] M3.1 `Notifier` interface + expert matching
- [ ] M3.2 Slack adapter + `/webhooks/slack`
- [ ] M3.3 Escalation loop end-to-end, 2-min timeout → action item
- [ ] M3.4 Telegram adapter (P2, fallback) — CUT unless M3.5 passes before 06:30
- [ ] M3.5 First end-to-end demo run (~06:15)

### M4 · Memory and chat (target 07:30)
- [ ] M4.1 KB RAG on pgvector: `POST /kb/docs`, Acme seed, top-6 chunks in the prompt
- [ ] M4.2 Post-call pipeline (summary, decisions, action items, facts)
- [ ] M4.3 `GET /meetings`, `GET /meetings/{id}`, `POST /chat` with citations

### M5 · Fact-check (target 08:00, cut first)
- [ ] M5.1 Live fact-check + message in the meeting chat
- [ ] M5.2 KB update proposals + approve / reject

### M6 · Stabilize + demo (target 08:30)
- [ ] M6.1 `/app/ws` all events, tokens, CORS
- [ ] M6.2 3 runs of the 90-s scenario on real Meet, latency measured, backup video by 09:30

## Research
- [x] R1 SPEC "Do weryfikacji" blocking M1–M3 → `docs/decisions.md` (Recall output_media+recording_config, meeting chat endpoint, bot status events; Slack url_verification + signature)

## Essentials (survive compaction)
- Contract FROZEN after M0: `docs/API.pl.md` + `mocks/` (17). Changes = Artem gate. One escalation shape {id, expert, channel, question, asked_by, ts, status waiting|answered|timeout, answer, answered_ts}; timeout = `escalation_answered` with status timeout. WS envelope {type, meeting_id, ts ISO, data}; data.ts = seconds from call start. 7 WS events incl. `meeting_status`.
- DB: `001_init.sql`, text ids (uuid), `utterances` dedup → `INSERT … ON CONFLICT (meeting_id, speaker, ts_start) DO NOTHING`; Slack reply lookup `escalations.external_msg_id`. `agent_said` table for poll mode.
- Recall/Slack facts: `docs/decisions.md` #13–20 (one bot create with output_media + recording_config, `recallai_streaming` prioritize_low_latency; status via dashboard webhook, post-call on `bot.done`; Slack v0 HMAC, ignore bot_id/bot_message, dedupe event_id).
- Run: `cd backend && uv run pytest -q`; Docker CMD uvicorn on `${PORT:-8000}`; agent-page/ outside build context → serve from backend/ (M2.1).

## Human tasks (Artem, in parallel — we build on respx mocks, ask only for live checks)
- [ ] Supabase project (EU) + enable `vector` → `DATABASE_URL` (Session pooler, 5432)
- [ ] Railway project (EU), auto-deploy from main, root `backend/` → domain = `PUBLIC_BASE_URL`
- [ ] Recall.ai API key (eu-central-1)
- [ ] Slack app (SPEC "Konfiguracja Slack app"); Request URL after M3.2 is deployed
- [ ] ElevenLabs voice id + OpenAI key
- Live checks pending: Recall live join (needs RECALL_API_KEY, PUBLIC_BASE_URL, DATABASE_URL; after M1.3) · Railway public `/health` (deploy from main, root `backend/`) → send domain for `PUBLIC_BASE_URL`; `cd backend && uv run python ../scripts/migrate.py` on Supabase (Session pooler, sslmode=require)

## Log (newest on top)
- 03:13 · M1.1 · Recall create/leave, Bearer auth, lazy DB pool; 18 tests, db.py checked on real pg · c30cb1d
- 03:08 · M0 verify · 6/6 PASS (pytest, ruff, /health, docker PORT=9000, migrate ×2, mocks) · contract frozen
- 03:08 · M0.3 · schema 13 tables + agent_said, migrate ×2 on docker pgvector ok, pytest 6 · a654c75
- 03:06 · M0.4 · docker build+run PORT=9000 → /health ok, image 482MB · 1b26525
- 03:05 · M0.2 · contract + 17 mocks (7 WS events incl. meeting_status; one escalation shape; agent_said[] for poll) · 1 review round · 7fe5206
- 03:02 · M0.1 · skeleton green (pytest 2, ruff clean, /health ok); embed-model default kept (SPEC Decyzje fixes 3-small/1536) · ed1d5d9
- 03:01 · R1 · Recall/Slack open items → decisions #13–20; UNCONFIRMED: send_chat_message body, Slack bot_id · R1 commit
- 03:00 · kickoff · re-baseline M0 03:45/M1 04:30/M2 05:30/M3 06:30 · researcher + M0.1 started
- 02:30 · setup · orchestrator, developer, STATUS.md created
