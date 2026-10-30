# AGENTS.md — rules for every coding agent (Claude Code, Codex)

> Single source of truth for agents. CLAUDE.md imports this file, Codex reads it natively.
> Fill the TODOs right after the stack is chosen (~21:30). Keep this file under ~80 lines.

## Project
TODO: one sentence — what we build and for whom.
**SPEC.md is the source of truth.** If an issue contradicts SPEC.md, follow SPEC.md and say so in the PR.

## Stack & commands
- Install: `TODO` (e.g. `pnpm i` / `pip install -r requirements.txt`)
- Run dev: `TODO`
- Test: `TODO` (if no tests — at least a smoke command that proves it starts)
- Lint/format: `TODO`
- Env: copy `.env.example` → `.env`. Never read, print or commit `.env`.

## Repo map
- `contracts/` — API schema + shared types. **Frozen after 22:00.** Change only via an issue labeled `contract`.
- `TODO` — frontend
- `TODO` — backend
- `SPEC.md` — spec, `notes/` — brief, brainstorm, pitch

## How we work
- One GitHub issue = one branch `issue-<n>-<slug>` = one PR with `Closes #<n>` in the body.
- Touch only the files/area listed in the issue. Need something outside it (shared types, contracts, config)? Stop and write it in the PR under **Needs**.
- Working demo > clean architecture. No auth, no infra, no refactors unless the issue asks.
- Seed / hardcode data when it saves time; mark it with `HACK:` comment.
- Prefer boring, well-known libraries. New dependency → one line in the PR why.
- Ambiguous issue → pick the simplest reasonable option, list it under **Assumptions** in the PR.

## Branches
`issue-<n>-<slug>` (or the `worktree-issue-<n>` branch `claude -w` creates). Never commit to `main` directly, never force-push.
Decisions that change architecture or contracts → one line in `docs/decisions.md` (Prelint reviews PRs against it).

## Code Review Rules
(Used by `@codex review`, Prelint and the `reviewer` subagent.)
- Flag only what breaks the demo flow in SPEC.md §4, the API contract in `contracts/`, or leaks secrets.
- Flag edits outside the issue's "Files / area".
- Do not flag style, naming or missing tests on HACK-marked code.

## Definition of done (before opening a PR)
1. App starts with the commands above, no new errors in the console.
2. Every acceptance criterion in the issue checked by actually running something.
3. Lint/format passes.
4. PR body: `Closes #<n>` · what changed · how verified (commands + result) · Assumptions · Needs.
