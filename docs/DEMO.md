# Demo run sheet (90 s, Google Meet, English)

`BASE=https://hackathon-ptw-production.up.railway.app` · `DT=<DEMO_TOKEN>` · `WT=<WEBHOOK_TOKEN>`

## Preflight (once)
- [ ] `curl -s $BASE/health` → `{"status":"ok"}`
- [ ] Railway vars: RECALL_API_KEY, RECALL_BASE_URL=https://eu-central-1.recall.ai, DATABASE_URL (Session pooler 5432, sslmode=require), PUBLIC_BASE_URL=$BASE, WEBHOOK_TOKEN, DEMO_TOKEN, OPENAI_API_KEY, OPENAI_CHAT_MODEL, OPENAI_EMBED_MODEL=text-embedding-3-small, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID, SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET
- [ ] Supabase migrated (`cd backend && uv run python ../scripts/migrate.py`) and KB seeded (`… ../scripts/seed_kb.py`)
- [ ] Recall dashboard (EU) status webhook: `$BASE/webhooks/recall/status?token=$WT`, events bot.*
- [ ] Slack Event Subscriptions Request URL `$BASE/webhooks/slack` = Verified, event `message.im`; Dima's real email in `backend/seed/experts.json` (redeploy)
- [ ] Dima (Julian/Rem) has Slack on his phone, "Thursday" ready in clipboard
- [ ] **No push to main during runs** (a deploy wipes live escalations + WS)

## Start a run
1. Artem opens `meet.new` (host), copies the link.
2. App → New call → Delegate, brief: `Done: SDK v2 shipped. Blocked: rate limit review. Don't agree to deadlines.`
   (or `curl -s -X POST $BASE/meetings -H "Authorization: Bearer $DT" -H 'content-type: application/json' -d '{"meeting_url":"<link>","mode":"delegate","brief":"Done: SDK v2 shipped. Blocked: rate limit review. Don'"'"'t agree to deadlines.","title":"Stand-up"}'`)
3. Admit **"Atlas (AI) for Artem"**. Orb visible in its tile.

## Script
| s | Who | Says | Expect |
|---|---|---|---|
| 20 | Misha | "Okay Atlas, what did Artem finish this week?" | orb thinking → voice: SDK v2 (from brief), 3–5 s |
| 35 | Misha | "Atlas, when do we migrate to Postgres 17?" | "I don't know, asking Dima now." orb → ask screen; Dima gets Slack DM |
| 45 | Dima | replies **in the thread**: "Thursday" | orb flash → "Dima says: Thursday" in call + Meet chat |
| 60 | Misha | "Our API limit is 100 requests per second." | Meet chat: "Heads-up: api.md says … 50 rps …" |
| 75 | Artem | app → Leave → summary (~5–10 s) → Chat: "What did Dima say about the migration?" | answer + citation (Dima, answered time) |
| 85 | Artem | app → KB → proposals (if a "change" line was said) | Approve / Reject card |

## Fallbacks
- "Atlas" not heard → say "Okay Atlas, …" clearly within the first words; backup: `curl -s -X POST "$BASE/debug/ask?meeting_id=<id>&token=$WT" -H 'content-type: application/json' -d '{"text":"what did Artem finish this week?"}'`
- Dima late or Slack down → `curl -s "$BASE/debug/escalations?meeting_id=<id>&token=$WT"` → `curl -s -X POST "$BASE/debug/expert-reply?token=$WT" -H 'content-type: application/json' -d '{"escalation_id":"<esc>","text":"Thursday"}'`
- No sound → `curl -X POST "$BASE/debug/say-tone?meeting_id=<id>&token=$WT"`; if silent, Recall Bot Explorer → Remote DevTools console ("play() rejected").
- Bot stuck in waiting room → host admits; auto-leaves after 600 s.
- Summary missing → it runs on `bot.done` or 5 s after Leave; check Railway logs for "LLM failed".

## E2E with integrations (live Meet, one call, ~10 min)
Setup: `migrate.py` (002) · `/ui` → Integrations: Slack / Jira / Telegram keys + **Test** = ok · `/ui` → Experts: real emails, channel, **Test** = DM arrives.
| # | Say (or do) | Expect | Check |
|---|---|---|---|
| 1 | "Okay Atlas, what did Artem finish this week?" | voice: SDK v2 (brief) | log `crew latency` ≤ 5 s |
| 2 | "Atlas, what is our API rate limit?" | "50 requests per second" (docs) | no escalation |
| 3 | "Atlas, what is the latest stable Python version?" (M8) | voice answer + ≤2 source URLs in Meet chat | log `tools=web_search` |
| 4 | "Atlas, what did Dima say last time about the migration?" (M8) | answer from past-call facts | log `tools=search_knowledge` |
| 5 | "Atlas, create a doc with the decisions from this call." (M8) | "I created the doc …" | `/ui` → KB: new doc |
| 6 | "Atlas, when do we migrate to Postgres 17?" | "asking Dima" → Slack DM → reply in thread "Thursday" → "Dima says: Thursday" | orb ask → flash; Meet chat |
| 7 | same with expert channel = telegram | Telegram message → reply → spoken | |
| 8 | "Atlas, what's the status of PTW-1?" (real key) | status / assignee / due | log `jira lookup` |
| 9 | Escalate, nobody replies 120 s | spoken timeout line; Jira "Follow-up:" issue | Jira board |
| 10 | "Our API limit is 100 requests per second." | Meet chat heads-up 50 rps | |
| 11 | App/`/ui` → Leave | summary + action items; "→ Jira" button creates issue | `/ui` → Meeting |
Must not happen: #6 answered from the web instead of escalating; agent promising a date for Artem.

## Measure (each run)
- Railway logs: `crew latency` lines (trigger→llm→tts+push, ms). Target total ≤ 5 s.
- Note: answer correct? escalation round-trip seconds? fact-check posted?
