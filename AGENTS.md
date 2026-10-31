# AGENTS.md — rules for every coding agent (Claude Code, Codex)

## Project
Call Crew: an AI agent joins Google Meet / Zoom / Teams through Recall.ai, takes notes, answers for its owner when someone says "Crew, …", and when it does not know, asks the right expert on Slack and speaks the expert's answer back in the same call.
**SPEC.md (Polish, symlink to `docs/SPEC.pl.md` — edit the file in `docs/`) is the source of truth.** It is ~450 lines: read only the sections your task needs. Hero feature = the Slack escalation loop (SPEC: "Eskalacja na Slacku"). If an issue contradicts SPEC.md, follow SPEC.md and say so in the PR.
Everything the agent says or writes in a call is in English (demo language).

## Stack & commands (run from repo root)
- Backend: Python 3.12, uv, FastAPI + uvicorn, pydantic v2 + pydantic-settings, httpx (async), asyncpg + pgvector, OpenAI, ElevenLabs TTS (REST), Slack Web API, Recall.ai.
- DB: Supabase Postgres + pgvector (EU). Migrations are plain SQL in `backend/migrations/*.sql`.
- Install: `cd backend && uv sync`
- Run dev: `cd backend && uv run uvicorn app.main:app --reload --port 8000`
- Public URL for Recall/Slack webhooks: `ngrok http 8000` → set `PUBLIC_BASE_URL`
- Test: `cd backend && uv run pytest -q` (no real network: mock every external HTTP call with respx)
- Smoke: `curl -s localhost:8000/health`
- Lint/format: `cd backend && uv run ruff check --fix . && uv run ruff format .`
- Migrate / seed: `cd backend && uv run python ../scripts/migrate.py` · `cd backend && uv run python ../scripts/seed_kb.py`
- Simulate a call without Recall: `cd backend && uv run python ../scripts/simulate_meeting.py`
- Deploy: Railway (EU) from `backend/Dockerfile`, health check `/health`.
- Env: copy `.env.example` → `.env`; variable names are in SPEC.md ("Zmienne środowiskowe"). Never read, print or commit `.env`.
- If you change how the project is installed, run or tested, update this section in the same PR.

## Repo map
- `backend/app/` — one module per concern: `main.py`, `config.py`, `db.py`, `recall.py`, `orchestrator.py`, `escalation.py`, `notifier/` (base, slack, telegram), `tts.py`, `rag.py`, `factcheck.py`, `postcall.py`
- `backend/migrations/`, `backend/seed/`, `backend/tests/`
- `agent-page/index.html` — the bot's "camera" page (vanilla JS, no build), served by FastAPI at `/agent`
- `scripts/` — migrate, seed_kb, simulate_meeting
- **API contract = `docs/API.pl.md` + `mocks/*.json`**. The iOS app is built against it. Frozen after M0: change only via an issue labeled `contract`, and update the mocks in the same PR.
- `ios/` — SwiftUI app (later, from Misha's mockup)
- `docs/decisions.md` — short decision log

## Backend rules
- External services only through their module (`recall.py`, `tts.py`, `notifier/*`, `rag.py`, one OpenAI client). Routers never call them directly.
- Webhooks (Recall, Slack, Telegram) answer 200 immediately and process with `asyncio.create_task`; deduplicate retries.
- Every webhook and WebSocket checks its token (`WEBHOOK_TOKEN`, `DEMO_TOKEN`); Slack requests verify the signature. Ignore messages from our own bot.
- Model names and IDs come from env (`OPENAI_CHAT_MODEL`, `ELEVENLABS_MODEL_ID`, `ELEVENLABS_VOICE_ID`), never hardcoded.
- Anything SPEC.md marks "do weryfikacji": check official docs first (use the `researcher` subagent), then add one line to `docs/decisions.md`.
- The agent never makes commitments or deadlines for its owner and never changes the knowledge base without human approval.
- Single instance: in-memory WebSocket hub, no queues, no Redis.

## How we work
- Backend runs in orchestrator mode: tasks live in `docs/STATUS.md`; the orchestrator commits each reviewed task to `main` as `<task-id>: <what>`. Parallel Codex tasks: one GitHub issue = one branch `issue-<n>-<slug>` = one PR with `Closes #<n>`. Never force-push.
- Touch only the files/area listed in the brief or issue. Wiring a router into `main.py`, a setting into `config.py` or a dependency via `uv add` is fine — mention it. API contract or migrations outside the brief: minimal change, listed under **Needs**.
- Working demo > clean architecture. Seed / hardcode data when it saves time; mark it `HACK:`.
- Ambiguous issue → pick the simplest option, list it under **Assumptions** in the PR.

## Code Review Rules
(Used by `@codex review` and the `reviewer` subagent.)
- Flag only what breaks the 90-second demo (SPEC "Produkt i demo w 90 sekund"), the API contract, or security: missing token/signature checks, secrets in code, real network calls in tests.
- Flag edits outside the issue's area.
- Do not flag style, naming or missing tests on HACK-marked code.

## Definition of done (before opening a PR)
1. `uv run pytest -q` passes, the app starts, `/health` answers.
2. Every acceptance criterion checked by running something (pytest, curl, `simulate_meeting.py`).
3. `ruff check` passes.
4. Report (or PR body): `Closes #<n>` if there is an issue · what changed · how verified (commands + result) · Assumptions · Needs.
