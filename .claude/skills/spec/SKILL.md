---
name: spec
description: Turn hackathon brainstorm notes and the case brief into SPEC.md using the team template. Use when the team has picked an idea and needs a spec, or asks to write or update the spec.
---
# Write SPEC.md

Inputs: `notes/brief.md` (the case brief + judging criteria) and `notes/brainstorm.md` (or notes pasted in chat).

1. Read both. If the primary user, the one core flow, or the demo "wow" moment is unclear, ask at most 3 questions in one message, then proceed.
2. Write `SPEC.md` from [template.md](template.md). Hard rules:
   - One primary user, one core flow, one wow moment. Everything else goes to OUT.
   - Buildable by 2 devs + agents in ~8 hours of build time. If not, cut until it is.
   - Contracts concrete enough that frontend and backend can be built in parallel: exact endpoints, request/response JSON examples, shared types, data model. These go to `contracts/` too.
   - Tickets are vertical slices of 30–90 min agent work, each with acceptance criteria checkable by running something (a curl, a click path, a test).
   - Ticket T1 is always the walking skeleton: repo scaffold + contracts + one endpoint wired to one screen, deployed or runnable.
   - Language: write SPEC.md in Polish (the team reads it); keep code identifiers, endpoints and ticket titles in English.
3. End with the 3 biggest risks and the cut-plan: what we drop first at 03:00 and at 08:00 if late.
