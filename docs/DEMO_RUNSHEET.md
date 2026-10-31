# Demo run sheet: weekly sync, Artem is double-booked (profile acme)

Story for the jury: Artem has three meetings at once, so he sends Atlas to the team sync. Atlas knows our docs and the Jira board. When it doesn't know something, it asks the right person on Slack (@mention) and brings the answer back into the same call.

Where the knowledge comes from (show `/ui` → Knowledge base):
- Docs: `api.md`, `roadmap.md`, `team.md`, `customers.md`. Confluence or Notion in a real company.
- Jira: `jira.md` (mock export). The live connector is built and switches on with keys in `/ui` → Integrations.
- People: Slack DM with an @mention.
- Meetings: Atlas remembers what was said.

## Before the call (5 min)
1. `/ui` → Agent: profile **Acme**.
2. `/ui` → Experts: Slack user ids:
   - Artem `U0CDL5TMV99`
   - Julian `U0CDS3WE8TC`
   - Misha `U0CDM3U1MA9`
   - Dima, renamed to **Jacob**, `U0CDM3SCQJZ`

   Then press **Send test** for each one.
3. `/ui` → Knowledge base → upload `backend/seed/jira.md`, so it is visible on screen.
4. `/ui` → New meeting → Meet link, mode **Delegate**, brief: `Done: SDK v2. Blocked: rate limit review. Do not agree to deadlines.` → Admit the bot in Meet.
5. Artem: Slack open on his phone or on screen, ready to reply.

## In the call
Rule: say the next "Atlas, …" only after Atlas has finished speaking (the orb is calm).

| # | Julian says | Shows | Atlas answers (roughly) |
|---|---|---|---|
| 1 | "Okay Atlas, what did Artem finish this week?" | stands in for the boss (brief) | "Artem finished SDK v2." |
| 2 | "Atlas, what's our API rate limit?" | docs | "50 requests per second per API key." |
| 3 | "Atlas, what's the status of PTW-2?" | Jira | "In progress, Julian, due 14 November." |
| 4 | "Atlas, ask Artem when we migrate to Postgres 17." | Slack, async ★ | "Sure, asking Artem on Slack now." → DM to **@Artem Hordiienko** |
| 4b | (keep talking 10–20 s, e.g. about the billing page) | the call doesn't stop | |
| 4c | Artem replies on Slack: "Thursday after 6 pm, Jacob runs it." | | "Artem says: Thursday after 6 pm, Jacob runs it." (+ Meet chat) |
| 5 | "Atlas, what did Artem say about the migration?" | memory | "Artem said Thursday after 6 pm." |
| 6 | `/ui` → Leave → open the meeting | summary | summary, decisions, action items |

Optional, if there is time:
- "Atlas, can Artem promise the billing page by Monday?" → no commitment for the owner (roadmap: Misha, 5 Dec).
- Without the wake word: "Our API limit is 100 requests per second." → heads-up in the Meet chat.

## If something breaks
- "Atlas" is not recognised: `/ui` → meeting → **Ask agent** (type the question).
- Slack reply doesn't arrive within 2 min: Atlas says it added it to follow-ups. Still a good story.
- Everything is down: the backup video of the dry run.
