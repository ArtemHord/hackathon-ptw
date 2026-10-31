# STATUS — Call Crew backend

Owned by the orchestrator: updated after every task. Times are Europe/Warsaw.

## Now
- Milestone: M3 (HERO)
- In progress: E2E — verifier local run (hero + tools a–f); Artem: prod integrations all unset (Slack/Telegram/Jira) → setup in /ui, then live checklist docs/DEMO.md
- Blocked: M3.5 first E2E demo run → needs Artem: Railway vars/keys, Slack Request URL + Dima email, Meet call

## Plan (re-baselined 03:00; SPEC "Plan do freeze o 11:00")
Cut rules: escalation not end-to-end by 06:30 → drop M5. After 08:30 → bug fixes only. 11:00 → freeze. If M2 not done by 05:30 → start M3 anyway.
Hosting: `PUBLIC_BASE_URL` = Railway domain (EU, auto-deploy from main); Slack + Recall webhooks point there; ngrok only as fallback for live debugging. During demo runs and after 08:30: no push to main without Artem's OK (deploy wipes in-memory WS hub + active escalations).

### M0 · Fundament (target 03:45) — DONE 03:08 — order M0.1 → M0.2 → M0.4 → M0.3
- [x] M0.1 Backend skeleton: uv, FastAPI, `/health`, config (all SPEC env vars), ruff, pytest, root `.env.example`
- [x] M0.2 API contract: `docs/API.pl.md` + `mocks/*.json` incl. `/app/ws` events (Misha blocked on it)
- [x] M0.4 `backend/Dockerfile` (uvicorn on `0.0.0.0:${PORT:-8000}`), Railway root `backend/`, healthcheck `/health`
- [x] M0.3 Migrations `001_init.sql` (all tables + `vector`) + `scripts/migrate.py` (idempotent; Supabase Session pooler 5432)

### M1 · Agent in the call (target 04:30) — DONE 03:20 (live Meet join pending, batched with M2.1)
- [x] M1.1 Recall client, `POST /meetings`, `POST /meetings/{id}/leave`; bot joins Google Meet
- [x] M1.2 Transcript webhook → `utterances`, dedup, WS event
- [x] M1.3 Bot status webhook
- [x] M1.4 `scripts/simulate_meeting.py` + demo-scenario fixture

### M2 · Agent speaks (target 05:30) — DONE 03:34 (live voice + real LLM latency pending keys)
- [x] M2.1 Agent page + `/agent-page/ws`; a test phrase is audible in the call
- [x] M2.2 ElevenLabs TTS + `POST /tts` + cached "One sec…"
- [x] M2.3a Seed docs `backend/seed/{api,roadmap,team}.md` (developer)
- [x] M2.3b Name trigger "Crew" → LLM (brief + docs in prompt) → voice; measure latency (senior-developer)
- [x] M2.4 Delegate brief — merged into M2.3b (brief in system prompt + "no commitments for owner" rule)

### M2.5 · Agent camera orb (designer, added 03:55)
- [x] M2.5a Port orb (`docs/design/agent-clips/`) to vanilla JS in agent page: 4 states + transitions + ask sequence, WS `state`/`ask`/`ask_done`, mic + output levels (senior-developer)
- [x] M2.5b Server signals: orchestrator → thinking/idle, escalation → ask/ask_done (developer)

### M3 · Slack escalation — HERO (target 06:30)
- [x] M3.1 `Notifier` interface + expert matching
- [x] M3.2 Slack adapter + `/webhooks/slack`
- [x] M3.3a Escalation loop core: start → Slack DM, expert reply → voice + Recall chat + WS, 2-min timeout → action item (senior-developer)
- [x] M3.3b Fake notifier + `/debug/expert-reply` + simulator `--expert-reply` for E2E without Slack (developer)
- [ ] M3.4 Telegram adapter (P2, fallback) — CUT unless M3.5 passes before 06:30
- [ ] M3.5 First end-to-end demo run (~06:15)

### M4 · Memory and chat (target 07:30) — DONE 04:16 (real-key run pending)
- [x] M4.1a KB RAG on pgvector: `GET/POST /kb/docs`, `rag.search`, `scripts/seed_kb.py`, backfill (orchestrator keeps full docs, decision 25)
- [x] M4.2 Post-call pipeline (summary, decisions, action items, facts)
- [x] M4.3a `GET /meetings`, `GET /meetings/{id}?since=` (contract key sets asserted)
- [x] M4.3b `POST /chat` with citations (after M4.1)

### M5 · Fact-check (target 08:00, cut first) — DONE 04:22 (live Recall chat body unconfirmed)
- [x] M5.1 Live fact-check + message in the meeting chat
- [x] M5.2 KB update proposals + approve / reject

### M6 · Stabilize + demo (target 08:30)
- [x] M6.3 Wake word → **Atlas** (config AGENT_NAME), alias in first 6 words, utterance/no-trigger INFO logs, noisy-ASR prompt, `/debug/ask` (senior-developer)
- [x] M6.6 Deepgram nova-3 transcription + keyterm "Atlas" (TRANSCRIPT_PROVIDER env, fallback to recallai on 400) (senior-developer)
- [x] M2.5c Sharpen orb (offscreen blur buffers 220/440 px → looks 240p in Meet)
- [x] M6.3b Deepgram spells "Atlas" correctly → no alias top-up; instead partial-question merge (2.5 s) + endpointing 500
- [x] M6.4 `POST /meetings/{id}/ask` app endpoint (done in M7.1)
- [ ] M6.5 (after M3.5 passes) Redact `token=` in uvicorn WS log lines (token leaked to Railway logs → rotate WEBHOOK_TOKEN)
- [x] M6.1 `/app/ws` all events (e2e test, real DB), tokens, CORS
- [ ] M6.2 3 runs of the 90-s scenario on real Meet, latency measured, backup video by 09:30

### M7 · Web setup app + integrations (Julian, PR #1 — MERGED 07:16)
- [x] M7.1 Runtime settings in DB (`app_settings`, `app/runtime.py`, env fallback), experts CRUD, `/integrations/*/test`, `/debug/simulate`, `/meetings/{id}/ask`
- [x] M7.2 Web app (React + Vite + shadcn) at `/ui`, multi-stage Dockerfile
- [x] M7.3 Telegram escalation adapter + `/webhooks/telegram` + deep-link expert linking
- [x] M7.4 Jira: in-call ticket lookup, action items → issues (button + `JIRA_AUTO_CREATE`), escalation timeout → issue
- [x] M7.5 Verifier fixes: simulate waits for the agent (speed 20 dropped wake-word lines) and keeps the call open for a manual expert reply; expert role null -> ""
- [ ] M7.6 HUMAN (also: Dima email via /ui → Experts, seed only fills an empty table): `migrate.py` on Supabase (002), keys via `/ui` → Integrations, live Telegram + Jira check

### M8 · Agent tools (Artem 07:05) — feature freeze 08:30
- [x] M8.1 Tool calling via Responses API: `web_search` + `search_knowledge` + `create_doc` (new docs only), 9 s cap, fallback to chat_json; internal questions still escalate (senior-developer, worktree ../hackathon-ptw-m8)
- [ ] M8.2 Live test: web question + doc request + Postgres 17 escalation (Artem)

### M9 · Demo content + scenarios (Artem 08:45; data, not features)
- [x] M9.0 `docs/SCENARIOS.md`: integrations setup for the second dev, fake company Acme + customer Northwind, Jira tickets PTW-1..5, past-call history, scenarios S1–S13, fact-check lines F1–F5 + P1
- [x] M9.1 `seed/customers.md` + `scripts/seed_history.py` (2 backdated past calls) (developer)
- [ ] M9.2 Second dev: run SCENARIOS.md §1 setup + §5 tests, fill §6 results
- [ ] (Artem decides) spoken fact-check interjection behind a flag

## Research
- [x] R1 SPEC "Do weryfikacji" blocking M1–M3 → `docs/decisions.md` (Recall output_media+recording_config, meeting chat endpoint, bot status events; Slack url_verification + signature)

## Essentials (survive compaction)
- Contract FROZEN after M0: `docs/API.pl.md` + `mocks/` (17). Changes = Artem gate. One escalation shape {id, expert, channel, question, asked_by, ts, status waiting|answered|timeout, answer, answered_ts}; timeout = `escalation_answered` with status timeout. WS envelope {type, meeting_id, ts ISO, data}; data.ts = seconds from call start. 7 WS events incl. `meeting_status`.
- DB: `001_init.sql`, text ids (uuid), `utterances` dedup → `INSERT … ON CONFLICT (meeting_id, speaker, ts_start) DO NOTHING`; Slack reply lookup `escalations.external_msg_id`. `agent_said` table for poll mode.
- Recall/Slack facts: `docs/decisions.md` #13–20 (one bot create with output_media + recording_config, `recallai_streaming` prioritize_low_latency; status via dashboard webhook, post-call on `bot.done`; Slack v0 HMAC, ignore bot_id/bot_message, dedupe event_id).
- Orchestrator: `orchestrator.on_needs_expert(meeting_id, question, topic, asked_by)` hook (M3 replaces; may return name or {expert, escalation_id}); OpenAI via httpx in llm.py (decision 23); latency log line "crew latency".
- Stage backup: `POST /debug/expert-reply?token=WEBHOOK_TOKEN {escalation_id,text}` speaks the answer if Slack fails; `GET /debug/escalations?meeting_id=&token=`. No SLACK_BOT_TOKEN → fake notifier (logs only).
- Run: `cd backend && uv run pytest -q`; simulate: `cd backend && DATABASE_URL=… WEBHOOK_TOKEN=… DEMO_TOKEN=… uv run python ../scripts/simulate_meeting.py --speed 20` (needs running backend + DB; exit 1 if utterance events != unique lines); Recall status dashboard URL `{PUBLIC_BASE_URL}/webhooks/recall/status?token={WEBHOOK_TOKEN}`; Docker CMD uvicorn on `${PORT:-8000}`; agent-page/ outside build context → serve from backend/ (M2.1).

## Next human steps (in order)
1. ~~Recall dashboard status webhook~~ done (events arrive) `{PUBLIC_BASE_URL}/webhooks/recall/status?token=WT`
2. Slack Request URL `{PUBLIC_BASE_URL}/webhooks/slack` Verified + Dima real email in seed/experts.json
3. ~~seed_kb~~ done 04:28
4. LIVE TEST 1 (join/transcript/tone) → M3.5 full run per docs/DEMO.md

## Human tasks (Artem, in parallel — we build on respx mocks, ask only for live checks)
- [x] Supabase project (EU) + `vector`; migrate 001 applied 04:09
- [x] Railway live 04:24: PUBLIC_BASE_URL=https://hackathon-ptw-production.up.railway.app (/health ok)
- [x] Recall.ai API key (eu-central-1)
- [ ] Slack app (SPEC "Konfiguracja Slack app"); Request URL after M3.2 is deployed
- [x] ElevenLabs voice id + OpenAI key
- Live checks pending: seed KB on Supabase `cd backend && uv run python ../scripts/seed_kb.py` · SLACK app (critical path M3) — scopes, install, tokens, Dima email; Request URL after M3.2 deploy · LIVE TEST 1 = Recall join + transcript + tone via `POST /debug/say-tone?meeting_id=&token=` (autoplay in Recall browser unconfirmed) · Recall live join (needs RECALL_API_KEY, PUBLIC_BASE_URL, DATABASE_URL; after M1.3) · Railway public `/health` (deploy from main, root `backend/`) → send domain for `PUBLIC_BASE_URL`; 

## Log (newest on top)
- 08:57 · push · M8.1b + M9.1 + SCENARIOS.md on main (9c459f5), Artem OK · Railway deploying; next: Artem seeds Supabase (seed_kb + seed_history)
- 08:50 · M9.1 · local: S3 "10 % off December" 4.5 s via search_knowledge; S4 three keys 3.1 s; Postgres 17 still escalates; sim RESULT OK; 329 tests · local commit; Artem: push + seed_kb.py + seed_history.py on Supabase
- 08:46 · M9.0 · docs/SCENARIOS.md written; M9.1 seed history → developer · —
- 08:10 · M8.1b · cause: Dima's fact ranked 7th behind KB chunks + facts-only vector_search SQL bug; fix: facts/KB searched separately, attributed format, prompt rule; live local: "Dima … said Thursday" 4.2 s, fresh Postgres 17 still escalates; 328 tests; review no blockers · local commit, push waits for Artem OK
- 08:06 · E2E local (verifier) · 5/6 PASS: hero sim RESULT OK; web_search 4.3 s; create_doc 7.6 s + duplicate refused; Postgres 17 escalates (no web) 2.7 s; AGENT_TOOLS=false fallback ok · FAIL c: in-call "what did Dima say about the migration?" escalates again instead of using Dima's answer → M8.1b senior-developer · —
- 08:01 · M7.6 · Artem: 002_settings.sql applied on Supabase → /ui settings writable · —
- 07:59 · E2E · prod /health ok; /settings: Slack, Telegram, Jira all unset; verifier started on local E2E (hero + web_search/search_knowledge/create_doc/escalation/AGENT_TOOLS off) · —
- 07:57 · M8.1 · blockers fixed (14 s total budget, create_doc lock + casefold); 324 tests, ruff green; merged m8-agent-tools → main · 5df1fa8 · pushed
- 07:58 · M8.1 · built (321 tests; live smoke: web_search 3.5–4.2 s, Postgres 17 still escalates 3.6–5.6 s); review: 2 blockers (stacked 9 s+15 s timeouts, create_doc race/case) → back to senior-developer · —
- 07:16 · PR #1 · merged on GitHub (b6af7fc); local main merged, 308 tests + ruff green · pushed
- 07:15 · PR #1 review · no blockers; 308 tests, ruff, docker build OK; starts without migration 002 (env fallback); contract changes additive (action_items jira_key/jira_url, /settings, /integrations, /experts, action-item→Jira) → needs Artem OK · —
- 07:10 · M8.1 · tool calling (web_search + search_knowledge + create_doc) → senior-developer in worktree ../hackathon-ptw-m8 (branch m8-agent-tools on PR #1 tip); PR #1 (Julian, M7 /ui + Telegram + Jira) → reviewer · —
- 07:05 · M7 · Artem: add tool calling (web search, research, docs creation) for Atlas; researcher on OpenAI Responses web_search; Julian email unread (Chrome extension not connected) · —
- 06:11 · M3.5 · Railway has no SLACK_* vars, experts.json emails are placeholders → human gate, steps sent to Artem · —
- 06:09 · M6.3b · partial "Atlas, what did" + "Artem finish…?" merged; endpointing 500; 216 tests · 1ec11e0 · pushed
- 06:06 · LIVE TEST 3 PASS · Deepgram nova-3 keyterm accepted (201, no fallback); "Okay Atlas, what did Artem finish" → voice answer; latency total 2.7–3.2 s (LLM 2.4–3.0 s, TTS+push ~230 ms), conf 0.98, filler played; orb sharp pushed (b4c49aa)
- 05:46 · M2.5c · orb sharp (full-res edges, 640x360 glow), 30 fps @4x throttle; review clean · b4c49aa (local, push held)
- 05:42 · M6.6 · Deepgram nova-3 keyterm + endpointing 300 behind TRANSCRIPT_PROVIDER, 400→recallai fallback, armed wake word (6 s); 212 tests · 891e7b6 · pushed
- 05:37 · LIVE TEST 2 · bot "Atlas (AI)" joined, utterances logged; "Okay Atlas, what did Artem finish" → ASR "oh okay what did i finish this week" (name dropped) → Artem chose Deepgram nova-3 + keyterm (M6.6); orb looks ~240p in Meet (M2.5c)
- 05:29 · M6.3 · Atlas wake word + trigger fix + logs + /debug/ask; simulator triggers on "Atlas, …"; review clean; 202 tests · 6d523dd · pushed
- 05:23 · LIVE TEST 1 detail · utterance rows DO arrive (Supabase), just unlogged → no log line since 04:28; trigger anchored at segment start + ASR mis-hears "Crew" · decision 27: wake word Atlas · order: M6.3 → LIVE TEST 2 → M3.5 → M6.4/M6.5
- 05:07 · LIVE TEST 1 · Recall join OK (output_media+recording_config in one call ✓), agent page WS ✓, transcript ✓, status in_call/done ✓, fact-check ran ✓; FAIL: wake word ("Crew"→"cat"/"crap"); fix: PUBLIC_BASE_URL was missing in Railway · R3: key_terms not in low-latency → fuzzy trigger + ask endpoint (decision 26)
- 04:28 · HUMAN · OpenAI key fixed; KB seeded on Supabase (api/roadmap/team v1)
- 04:27 · R2 · Recall send_chat_message body confirmed; Meet 500-char cap → truncate · HUMAN: seed_kb failed, OPENAI_API_KEY wrong (key_… not sk-…)
- 04:26 · M6.1 · CORS + e2e 7-event test (re-run by me on real pg: 3/3, timeout patch 3→8 s); 180 tests · 5e493ce
- 04:24 · HUMAN · Railway /health ok (502 was Railway config)
- 04:22 · M5.2 · proposals + approve/reject (transactional, 409 stale), + my guard old_text ≥ 10 chars; 177 tests · f57aab6
- 04:19 · M5.1 · fact-check; review BLOCKER (source null in app) → kb_chunk_for_title, verified on real pg; 170 tests · a688278
- 04:17 · M4 verify · PASS: list/detail keys = mocks, ?since filters, /chat fallback, /kb/docs, 401s · item keys of empty arrays covered by M4.3a real-DB tests
- 04:16 · M4.3b · /chat RAG + citations; review demo nits fixed (Dima cited at answered_ts=380 verified on real pg, fact embedded on reply); 163 tests · d8000be
- 04:16 · HUMAN · Railway domain https://hackathon-ptw-production.up.railway.app → 502; local image OK with PORT → Railway config (target port/root dir)
- 04:13 · M4.1a · KB API + RAG + seed; DB tests re-run by me on real pg (5/5); 159 tests · 304865e
- 04:10 · M2.5b · orb signals wired (thinking/idle/ask/ask_done), ask layout persists while speaking (screenshot ok); cap lowered to 0.3 s after review; 154 tests · 9f8e73e
- 04:09 · HUMAN · Supabase migrated (001 applied) after password reset (special chars broke DSN)
- 04:08 · M2.5a · orb ported to canvas, 30 fps, ?demo/?state debug; review: orb failure must not mute agent → isolated, proven with orb.js blocked; 146 tests · ebb2b7c
- 03:55 · M4.2 · postcall (idempotent, merges timeout items, bot.done + leave+5 s); 139 tests · 017c881
- 03:55 · design · Artem sent orb animation → M2.5 added; source extracted to docs/design/agent-clips (decision 24)
- 03:52 · M4.3a · list + detail endpoints, real-DB tests (localhost-only guard added by me after review BLOCKER); 133 tests · 935de9e
- 03:49 · M3.3b · fake notifier + debug reply endpoints + simulator flags; 128 tests · abd82d4 · M3 code complete, M3.5 waits on Artem
- 03:45 · M3.3a · escalation loop: fast start, SQL first-reply-wins, timeout → spoken line + action item, late reply stored; 125 tests · 7864a9f
- 03:39 · M3.2 · Slack adapter + webhook (raw-body HMAC, 300 s window, retry skip, event_id dedupe, bot filter); 113 tests · 23b2ff1
- 03:36 · M3.1 · Notifier protocol + registry, match_expert (postgres/infra→Dima, else owner Artem), experts seeded from json (real DB ok); 93 tests · d603dc7
- 03:35 · M2 verify · PASS: /agent in browser (green dot, bad token → red), say-tone delivered, simulator OK, no-key LLM fails silently · real voice/LLM untested (keys)
- 03:34 · M2.3b+M2.4 · orchestrator: aliases, delegate-only, speaking guard, lock, 1.5 s filler, strict JSON, no-commitment rule, agent_said; 82 tests · b9ce17b
- 03:28 · M2.3a · seed docs; review caught token-lifetime leak (would answer the cache escalation) → removed · bd3eb95
- 03:27 · M2.2 · tts.py (flash model via env), /tts, filler cache, say(); 47 tests · 318458e
- 03:25 · M2.1 · /agent page + WS play/tone, is_speaking w/ 90 s TTL; 1 review round (stuck flag); 38 tests · 2b58ac6
- 03:20 · M1 verify · PASS: auth 401s, simulator 7/7 utterances + in_call/done, DB state ok · live join not tested
- 03:20 · M1.4 · simulator replays demo (7 lines, dedup shown, status in_call/done); 31 tests · bb3b6ab
- 03:18 · M1.3 · status webhook mapping + terminal-state guard, postcall_hook stub; 30 tests · 609ed4d
- 03:16 · M1.2 · transcript webhook dedup + /app/ws (4401), orchestrator_hook stub for M2.3; 26 tests; Docker --no-access-log (token in query) · 2adf1ce
- 03:13 · M1.1 · Recall create/leave, Bearer auth, lazy DB pool; 18 tests, db.py checked on real pg · c30cb1d
- 03:08 · M0 verify · 6/6 PASS (pytest, ruff, /health, docker PORT=9000, migrate ×2, mocks) · contract frozen
- 03:08 · M0.3 · schema 13 tables + agent_said, migrate ×2 on docker pgvector ok, pytest 6 · a654c75
- 03:06 · M0.4 · docker build+run PORT=9000 → /health ok, image 482MB · 1b26525
- 03:05 · M0.2 · contract + 17 mocks (7 WS events incl. meeting_status; one escalation shape; agent_said[] for poll) · 1 review round · 7fe5206
- 03:02 · M0.1 · skeleton green (pytest 2, ruff clean, /health ok); embed-model default kept (SPEC Decyzje fixes 3-small/1536) · ed1d5d9
- 03:01 · R1 · Recall/Slack open items → decisions #13–20; UNCONFIRMED: send_chat_message body, Slack bot_id · R1 commit
- 03:00 · kickoff · re-baseline M0 03:45/M1 04:30/M2 05:30/M3 06:30 · researcher + M0.1 started
- 02:30 · setup · orchestrator, developer, STATUS.md created
