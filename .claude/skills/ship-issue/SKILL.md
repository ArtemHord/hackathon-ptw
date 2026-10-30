---
name: ship-issue
description: Implement one GitHub issue end-to-end on its own branch, verify it and open a PR. Use when asked to work on, ship or do issue #N.
argument-hint: <issue-number>
disable-model-invocation: true
---
# Ship issue #$ARGUMENTS

1. `gh issue view $ARGUMENTS --comments`. Read the SPEC.md sections it points to and AGENTS.md.
   If it depends on an issue that is still open and not merged, stop and say so.
2. Branch: if the current branch already contains `issue-$ARGUMENTS` (a worktree made for it), stay on it. Otherwise `git fetch origin && git switch -c issue-$ARGUMENTS-<short-slug> origin/main`.
3. Implement the smallest change that meets every acceptance criterion. Stay inside the issue's files/area.
4. Verify by running things, not by reading code: the test/lint/run commands from AGENTS.md. For a UI or multi-step flow, delegate to the `verifier` subagent.
5. Delegate to the `reviewer` subagent with the issue number. Fix BLOCKERS only.
6. Commit with a clear message, `git push -u origin HEAD`, then `gh pr create` with body:
   `Closes #$ARGUMENTS` · What changed · How verified (commands + results) · Assumptions · Needs.
7. Final message: PR link + the one thing a human should click or check.
