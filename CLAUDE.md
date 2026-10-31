@AGENTS.md

## Claude Code specifics
- Backend build: start with `claude --agent orchestrator`. It plans from `docs/STATUS.md`, delegates to `developer`, gates with `reviewer` / `verifier`.
- Subagents (`.claude/agents/`): `developer` (sonnet) implements routine tasks, `senior-developer` (opus) hard logic, `reviewer` before every commit/PR, `verifier` to check a flow in the running app, `researcher` for library/API docs so the main context stays clean.
- Skills (`.claude/skills/`): `/spec-to-issues`, `/ship-issue <n>`, `/integrate`, `/pitch`.
- Anything touching more than 3 files → plan mode first, show the plan, then implement.
- `/clear` between issues. One session = one issue.
