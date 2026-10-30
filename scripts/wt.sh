#!/usr/bin/env bash
# One issue = one worktree = one agent, so parallel agents never touch the same checkout.
# Usage: scripts/wt.sh <issue-number> [claude|codex]
#   scripts/wt.sh 12          -> worktree ../<repo>-12 on branch issue-12, starts Claude Code with /ship-issue 12
#   scripts/wt.sh 13 codex    -> same, starts Codex CLI with the issue as the task
# Cleanup after merge: git worktree remove ../<repo>-12
set -euo pipefail

n="${1:?issue number}"
agent="${2:-claude}"
root="$(git rev-parse --show-toplevel)"
dir="$(dirname "$root")/$(basename "$root")-$n"

git -C "$root" fetch -q origin
git -C "$root" worktree add -b "issue-$n" "$dir" origin/main

# Worktrees don't get untracked files: copy local env, then install deps.
for f in .env .env.local; do [ -f "$root/$f" ] && cp "$root/$f" "$dir/$f"; done
cd "$dir"
# TODO: uncomment the install line for our stack
# pnpm i --silent || npm i --silent
# pip install -q -r requirements.txt

if [ "$agent" = "codex" ]; then
  exec codex "Implement GitHub issue #$n. First run: gh issue view $n --comments. Follow AGENTS.md exactly (definition of done). Work only on this branch, then open a PR with 'Closes #$n'."
else
  exec claude "/ship-issue $n"
fi
