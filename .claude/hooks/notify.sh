#!/usr/bin/env bash
# Desktop notification so you can run 2–3 agent sessions and only look when one stops.
# Shows which worktree/issue finished. Never blocks Claude (always exits 0).
msg="${1:-Claude}"
where="$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")"
if command -v osascript >/dev/null 2>&1; then
  osascript -e "display notification \"$where\" with title \"$msg\" sound name \"Glass\"" >/dev/null 2>&1
elif command -v notify-send >/dev/null 2>&1; then
  notify-send "$msg" "$where" >/dev/null 2>&1
elif command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -c "[console]::beep(880,200)" >/dev/null 2>&1
fi
exit 0
