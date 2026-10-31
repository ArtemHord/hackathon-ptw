# STATUS — Call Crew backend

Owned by the orchestrator: updated after every task. Times are Europe/Warsaw.

## Now
- Milestone: M0
- In progress: —
- Blocked: —

## Plan (SPEC "Plan do freeze o 11:00")
Cut rules: escalation not end-to-end by 06:30 → drop M5. After 08:30 → bug fixes only. 11:00 → freeze.

### M0 · Fundament (target 02:45)
- [ ] M0.1 Backend skeleton: uv, FastAPI, `/health`, config, ruff, pytest, `.env.example`, README
- [ ] M0.2 API contract: `docs/API.pl.md` + `mocks/*.json` (Misha needs it for the app)
- [ ] M0.3 Supabase migrations (all tables + `vector`) + `scripts/migrate.py`
- [ ] M0.4 Dockerfile + Railway deploy (EU), `PUBLIC_BASE_URL` (HUMAN: Railway project)

### M1 · Agent in the call (target 03:30)
- [ ] M1.1 Recall client, `POST /meetings`, `POST /meetings/{id}/leave`; bot joins Google Meet
- [ ] M1.2 Transcript webhook → `utterances`, dedup, WS event
- [ ] M1.3 Bot status webhook
- [ ] M1.4 `scripts/simulate_meeting.py` + demo-scenario fixture

### M2 · Agent speaks (target 05:00)
- [ ] M2.1 Agent page + `/agent-page/ws`; a test phrase is audible in the call
- [ ] M2.2 ElevenLabs TTS + `POST /tts` + cached "One sec…"
- [ ] M2.3 Name trigger "Crew" → LLM (brief + docs in prompt) → voice; measure latency
- [ ] M2.4 Delegate brief

### M3 · Slack escalation — HERO (target 06:30)
- [ ] M3.1 `Notifier` interface + expert matching
- [ ] M3.2 Slack adapter + `/webhooks/slack`
- [ ] M3.3 Escalation loop end-to-end, 2-min timeout → action item
- [ ] M3.4 Telegram adapter (P2, fallback)
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

## Human tasks (Artem)
- [ ] Recall.ai account + API key (eu-central-1)
- [ ] Supabase project (EU) + enable `vector` → `DATABASE_URL`
- [ ] Railway project (EU)
- [ ] Slack app: scopes, events, install (30–45 min)
- [ ] ElevenLabs voice id
- [ ] ngrok for local webhooks
- [ ] SPEC "Do weryfikacji" items answered (researcher)

## Log (newest on top)
- 02:30 · setup · orchestrator, developer, STATUS.md created
