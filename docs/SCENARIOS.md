# Integrations setup, demo data and test scenarios

Owner: second dev (setup + tests). Artem builds features. The orchestrator fixes bugs.
Prod: `https://hackathon-ptw-production.up.railway.app` (`$BASE`) · panel `$BASE/ui` · token = `DEMO_TOKEN`. Ask Artem for it and never paste it into docs or chat.
Rules:
- No push to main while someone is in a live call, because a deploy kills the bot and open escalations.
- When testing alone, give the experts your own emails.

## 1. Connect the services (order matters)
1. **Supabase**: migration 002 is applied (08:01). Nothing to do.
2. **Slack app**
   1. api.slack.com/apps → Create New App → From scratch → "Atlas".
   2. OAuth & Permissions → Bot Token Scopes: `chat:write`, `im:write`, `im:history`, `users:read`, `users:read.email` → Install to Workspace → copy `xoxb-…`.
   3. Basic Information → copy the Signing Secret.
   4. `/ui` → Integrations → Slack: paste both → **Test** must return ok.
   5. Event Subscriptions → On → Request URL `$BASE/webhooks/slack` → must show **Verified**. This only works after step 4. Add bot event `message.im` → Save → reinstall if asked.
   6. App Home → turn on Messages Tab and "Allow users to send messages".
3. **Experts**: `/ui` → Experts. Fill in a real Slack email for Dima (database, postgres, infra), Julian (api, webhooks, rate limit), Misha (mobile, billing) and Artem (owner). Press **Test** → a DM arrives. Seed `experts.json` only fills an empty table, so edit experts in `/ui`.
4. **Jira Cloud**
   1. Site `https://<name>.atlassian.net`, team-managed project, key `PTW`, issue type **Task**.
   2. Token: id.atlassian.com/manage-profile/security/api-tokens.
   3. `/ui` → Integrations → Jira: `JIRA_BASE_URL` (no path), `JIRA_EMAIL` (your Atlassian login), `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY=PTW`, optional `JIRA_AUTO_CREATE=true`, so action items are created as issues after the call.
   4. **Test**, then create the tickets from §3.
5. **Telegram** (optional, backup channel)
   1. @BotFather → /newbot → token.
   2. `/ui` → Integrations → Telegram: token + `TELEGRAM_WEBHOOK_SECRET` (any random string) → **Test**. This also registers the webhook.
   3. The expert opens `t.me/<bot>?start=<expert_id>` and presses Start. Set the expert's channel to `telegram`.
6. **Content**: KB seed is on prod. Past-call history (§4) and `customers.md` come with task M9.1 (`scripts/seed_history.py`).

Apps ↔ backend:
- REST with `Authorization: Bearer <DEMO_TOKEN>` (contract: `docs/API.pl.md` + `mocks/`).
- Live events: `wss://…/app/ws?meeting_id=<id>&token=<DEMO_TOKEN>`, which sends 7 events (see API.pl.md).

## 2. Fake company (matches `backend/seed/*.md`)
**Acme**: a small API platform (REST API, SDK v2, webhooks). Team:
| Name | Role and topics |
|---|---|
| Artem | owner, SDK |
| Dima | backend, infra, Postgres, auth |
| Julian | API, webhooks, rate limit |
| Misha | mobile, billing |

Facts in the KB:
- Rate limit 50 rps per key (`api.md`).
- SDK v2 done on 9 Oct.
- Webhooks retry: Julian, in progress, due 14 Nov, up to 5 attempts.
- Billing page: Misha, due 5 Dec (`roadmap.md`).

Customer: **Northwind Logistics**. Contact Sarah Chen (CTO), Enterprise plan, SLA **99.9 %**, renewal 1 Dec 2026, 3 API keys. This goes in a new `seed/customers.md` (M9.1).

**Do not seed anything about the Postgres 17 migration date or auth-token caching.** Those are the escalation demos. If the data answers them, Atlas stops asking the expert.

## 3. Jira tickets (create by hand, about 5 min)
| Key | Summary | Assignee | Status | Due |
|---|---|---|---|---|
| PTW-1 | Postgres 17 migration | Dima | In Progress | (none: date unknown, escalation demo) |
| PTW-2 | Webhooks retry (exponential backoff, 5 attempts) | Julian | In Progress | 2026-11-14 |
| PTW-3 | Northwind: CSV export of events | Artem | To Do | 2026-11-28 |
| PTW-4 | Billing page (iOS + web) | Misha | In Progress | 2026-12-05 |
| PTW-5 | Rate limit review (Northwind Black Friday peak) | Julian | To Do | — |

## 4. Past-call history (seeded by M9.1, backdated)
**10 Oct 2026 · "Northwind onboarding sync"** (Artem, Julian, Sarah Chen), done, 25 min. Key lines:
- Sarah: "Our Black Friday peak is about 120 requests per second."
- Julian: "Standard limit is 50 per second per key, so we'll give you three API keys for the peak."
- Sarah: "We lost events last month, we need webhook retries."
- Julian: "Retries with backoff ship by 14 November."
- Artem: "We'll add a CSV export of events for your finance team by 28 November."
- Sarah: "If the export slips we'd like 10 % off the December invoice."
- Artem: "Agreed, 10 % off December if it's late."

Resulting facts:
- 3 keys × 50 rps for Black Friday.
- Webhook retries by 14 Nov (Julian).
- CSV export by 28 Nov (Artem).
- 10 % discount on the December invoice if the export is late.

**24 Oct 2026 · "Weekly sync"** (Artem, Dima, Julian, Misha). Decisions:
- The rate limit stays at 50 rps until the review (Julian).
- The billing design is final, and the iOS build starts next week (Misha).

## 5. Scenarios (run in one Meet call, or `/ui` → Simulate → "Ask agent" for text-only)
Wait for Atlas to finish speaking (orb idle) before the next "Atlas, …". A trigger said while it speaks is dropped.

| ID | Say / do | Expected | Verify |
|---|---|---|---|
| S1 brief | "Okay Atlas, what did Artem finish this week?" | SDK v2 (from the brief) | voice; `agent latency` ≤ 5 s |
| S2 KB | "Atlas, what's our API rate limit?" | 50 rps per key | no escalation |
| S3 memory ★ | "Atlas, a few weeks ago we promised Northwind something if the export is late, what was it?" | "On the 10 October call Artem agreed to 10 % off the December invoice if the CSV export slips past 28 November." | log `tools=search_knowledge` |
| S4 memory | "Atlas, how many API keys did we give Northwind for Black Friday?" | three keys (customers.md); may not mention Black Friday | |
| S5 Jira | "Atlas, what's the status of ticket 2?" | In Progress, Julian, due 14 Nov | log `jira lookup` (if ASR writes "two", report it as a bug) |
| S6 escalation ★ | "Atlas, when do we migrate to Postgres 17?" | "asking Dima" → Slack DM → reply **in thread** "Thursday" → "Dima says: Thursday" + Meet chat | orb ask → flash; `/ui` meeting card |
| S7 recall after escalation | (later) "Atlas, what did Dima say about the migration?" | "Dima said Thursday" | needs M8.1b on prod |
| S8 timeout | escalate, nobody answers for 120 s | spoken timeout line + Jira "Follow-up: …" issue | Jira board |
| S9 web | "Atlas, what's the latest stable Python version?" | answer + ≤2 links in Meet chat | `tools=web_search` |
| S10 doc | "Atlas, create a doc with the decisions from this call." | "I created the doc …" | `/ui` → KB |
| S11 no promise | "Atlas, can Artem deliver the export by Monday?" | no commitment, escalates to owner | |
| S12 leave | `/ui` → Leave | summary, decisions, action items; "→ Jira" creates an issue | `/ui` → Meeting, Jira |
| S13 app chat | `/ui` or app → Chat: "What did we agree with Northwind?" | answer + citation (meeting 10 Oct) | |

### Fact-check
How it works:
- Every utterance runs through a free filter: a number with a unit, or a team name.
- One LLM call then judges the claim against the KB and past facts.
- If the claim is **contradicted** with confidence ≥ 0.8, a heads-up goes to the Meet chat ("Heads-up: api.md says …"), at most once per 60 s per meeting. The app gets a `fact_check` event.
- A confident **change** ("from now on …") creates a KB proposal (Approve or Reject in `/ui` → KB).

False claims to say (space them more than 60 s apart):
| ID | Say (no wake word) | Contradicts | Expected |
|---|---|---|---|
| F1 ★ | "Our API limit is 100 requests per second." | api.md: 50 rps | Meet chat heads-up |
| F2 | "Julian already shipped webhook retries last week." | roadmap: in progress, due 14 Nov | heads-up |
| F3 | "Webhooks retry up to 10 times, right Julian?" | roadmap: 5 attempts | heads-up |
| F4 | "Northwind has a 99.99 percent SLA." | customers.md: 99.9 % (after M9.1) | heads-up |
| F5 | "We promised Northwind a 20 percent discount." | 10 Oct call: 10 % | heads-up (from past facts) |
| P1 | "From today the rate limit is 100 requests per second, Julian approved it." | api.md | KB proposal → Approve → api.md v2 |

A spoken fact-check (Atlas cutting in by voice) is not built; today the heads-up goes to the Meet chat only. Artem's call: add it as a feature flag (speak the heads-up when the agent is idle).

## 6. Results (fill in during tests)
| Time | ID | Pass/Fail | Latency | Note / log line |
|---|---|---|---|---|
| | | | | |
Bugs: one line here plus a message to Artem. Logs: `railway logs | grep -E "agent latency|tools=|jira|escalat|fact"`.
