---
name: spec-to-issues
description: Convert the milestone plan in SPEC.md into GitHub Issues with owner/area/priority labels and dependencies, via the gh CLI. Use when the spec is approved and the team asks to create tickets or issues.
disable-model-invocation: true
---
# SPEC.md → GitHub Issues

1. Read `SPEC.md` sections "Plan do freeze o 11:00" (milestones → tickets) and "Backend: API, infrastruktura, zmienne" (endpoints, repo structure), and `.github/ISSUE_TEMPLATE/agent-task.md`.
2. Write `tickets.json` — a list of:
   ```json
   {"id": "T2", "title": "...", "labels": ["agent:codex", "area:be", "P0"], "depends_on": ["T1"], "body": "..."}
   ```
   - `body` follows the agent-task template: Goal · Context (SPEC section) · Files/area · Acceptance criteria as `- [ ]` · Out of scope.
   - Exactly one owner label per ticket: `agent:claude`, `agent:codex`, `human:dev`, `human:ux`, `human:biz`.
   - Owner rule: T1 skeleton and anything touching `docs/API.pl.md` / `mocks/` → `agent:claude`. Well-isolated leaf tasks with a clear file area (one endpoint, one screen, one script) → alternate `agent:codex` / `agent:claude` so both run in parallel. Design → `human:ux`, research/pitch → `human:biz`.
   - Two tickets running at the same time must not edit the same files. If they would, add a dependency.
3. Print a compact table (id · title · owner · depends) and wait for the user to say ok.
4. Run `python3 scripts/create_issues.py tickets.json --dry-run`, then without `--dry-run`. The script creates missing labels, creates issues in dependency order and rewrites T-ids into real `#numbers`.
5. Print the created issue numbers grouped by owner — that is the assignment board.
