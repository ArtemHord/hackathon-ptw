@AGENTS.md

## Claude Code specifics
- Subagents (`.claude/agents/`): `reviewer` before every PR, `verifier` to check a flow in the running app, `researcher` for library/API docs so the main context stays clean.
- Skills (`.claude/skills/`): `/spec`, `/spec-to-issues`, `/ship-issue <n>`, `/integrate`, `/pitch`.
- Anything touching more than 3 files → plan mode first, show the plan, then implement.
- `/clear` between issues. One session = one issue.
