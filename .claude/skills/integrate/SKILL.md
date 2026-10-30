---
name: integrate
description: Merge the open, green PRs into main oldest-first, rebase the rest, and re-check the demo flow. Use at every integration checkpoint (every 60–90 min) or when asked to integrate or merge PRs.
disable-model-invocation: true
---
# Integration checkpoint

1. `git fetch origin && gh pr list --state open --json number,title,headRefName,isDraft,labels,mergeable`.
2. Oldest-first, for each non-draft PR:
   - `gh pr checks <n>` and read review comments (Prelint, `@codex review`, reviewer). Unresolved BLOCKER → skip it and note why.
   - Contract changes (`contracts/`) are merged only if the PR is labeled `contract`.
   - `gh pr merge <n> --squash --delete-branch`.
3. For PRs that now conflict: comment `Needs rebase on main after #<merged>` — do not resolve another agent's conflicts yourself unless trivial (imports, lockfile).
4. On updated main: run the start/test commands from AGENTS.md, then delegate to the `verifier` subagent with SPEC.md §4 "Demo script".
5. Report in 8 lines max: merged · skipped (why) · demo flow ✅/❌ per step · the next 3 issues to start.
