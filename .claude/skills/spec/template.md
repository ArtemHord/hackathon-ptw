# SPEC — <project name>

## 1. Problem
One paragraph. One number that proves it hurts (time lost, money, % of users).

## 2. User and moment
Who exactly, in what situation, what they do today instead.

## 3. Solution in one sentence
"<Name> lets <user> <do X> in <Y> instead of <Z>."

## 4. Demo script (the 90 seconds judges see)
1. ...
2. ... ← WOW moment
3. ...
Seed data needed: ...
Fallback if live demo fails: recorded video / screenshots at `notes/demo/`.

## 5. Scope
- **IN (demo-critical):** ...
- **NICE (only if ahead of schedule):** ...
- **OUT:** auth, settings, ...

## 6. Architecture
Components and who calls whom. Where sponsor tech is used (OpenAI API / Codex, ElevenLabs, partner's API) — make it visible in the demo.

## 7. Contracts
### Endpoints
`POST /api/...`
```json
// request
{}
// response
{}
```
### Shared types / data model
```ts
type Example = {}
```

## 8. Tickets
| id | title | owner | area | P | depends | acceptance (checkable) |
|----|-------|-------|------|---|---------|------------------------|
| T1 | Walking skeleton: scaffold + contracts + 1 endpoint ↔ 1 screen | agent:claude | infra | P0 | — | `<run cmd>` starts; screen shows data from endpoint |

Owners: `agent:claude` · `agent:codex` · `human:dev` · `human:ux` · `human:biz`

## 9. Risks and cut-plan
| risk | mitigation | cut at 03:00 | cut at 08:00 |
|------|------------|--------------|--------------|

## 10. Judging criteria → how we hit each
| criterion | how | where in demo |
|-----------|-----|---------------|
