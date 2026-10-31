---
name: pitch
description: Draft the demo script, the 3-minute pitch and judge Q&A prep from SPEC.md and the case brief. Use when preparing the final presentation, demo or pitch.
---
# Pitch + demo

Inputs: `SPEC.md`, `notes/brief.md` (judging criteria, partner's problem), what actually works now (`git log --oneline -20`, ask if unsure).

Write `notes/PITCH.md`:
1. **Hook (15 s)** — the problem as one concrete scene + one number.
2. **Who hurts (15 s)** — the user from the partner's world, in their words.
3. **Live demo (90 s)** — exact click path from SPEC.md section "Produkt i demo w 90 sekund", the wow moment named. Only features that work right now.
4. **How it works (25 s)** — one architecture sentence, where OpenAI / ElevenLabs / partner tech is used.
5. **Why it matters for <partner> (20 s)** — tie to their product/metric explicitly.
6. **Next step (10 s)** — what we'd build in week 1.

Then `notes/QA.md`: 8 hardest likely judge questions (tech, business, partner-specific, "why not just use X?") with 2-line answers.

Then `notes/DEMO-CHECKLIST.md`: seed data, accounts logged in, tabs open, mic/sound for voice, offline fallback video path, who clicks and who talks.

Language: team-internal files (`QA.md`, `DEMO-CHECKLIST.md`) in Polish. `PITCH.md` in the language the jury uses — check `notes/brief.md`, ask if unknown (likely English).

Rule: never pitch a feature that is not in the demo. Plain words, no buzzword stacks.
