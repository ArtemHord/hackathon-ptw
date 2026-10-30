# Hackathon kit — Claude Code + Codex

Skopiuj zawartość tego folderu (razem z ukrytymi plikami: `.claude/`, `.github/`, `.mcp.json`, `.gitignore`, `.worktreeinclude`) do roota nowego repo, commit, push. Dalej wszyscy pracują z jednego `main`.

## Co tu jest
| Plik | Do czego |
|------|----------|
| `AGENTS.md` | Reguły dla **wszystkich** agentów. Codex czyta go sam, Claude — przez `@AGENTS.md` w `CLAUDE.md`. Sekcja `Code Review Rules` jest dla `@codex review`. Uzupełnić TODO ok. 21:30. |
| `CLAUDE.md` | Importuje AGENTS.md + kilka linii specyficznych dla Claude Code. |
| `.claude/agents/` | 3 subagenci: `reviewer` (przed PR, read-only), `verifier` (przechodzi flow w przeglądarce/curl), `researcher` (dokumentacja bibliotek, żeby nie zaśmiecać głównego kontekstu). |
| `.claude/skills/` | 5 skilli: `/spec`, `/spec-to-issues`, `/ship-issue <n>`, `/integrate`, `/pitch`. |
| `.claude/settings.json` | Uprawnienia (gh/git bez potwierdzeń), zakaz czytania `.env` i force-push, powiadomienia „agent skończył / czeka”, po compact SPEC.md wraca do kontekstu. |
| `.mcp.json` | Playwright (sprawdzanie UI) + Context7 (aktualna dokumentacja). Więcej nie trzeba — każdy MCP zjada kontekst. |
| `scripts/create_issues.py` | `tickets.json` → GitHub Issues z labelami i zależnościami (najpierw `--dry-run`). |
| `scripts/wt.sh` | `scripts/wt.sh 12 codex` — osobny worktree + gałąź + agent na jedno issue. |
| `docs/decisions.md` | Krótka lista decyzji. Prelint czyta markdown w repo i łapie PR-y, które są z nim sprzeczne. |
| `.github/` | Szablon issue dla agenta i szablon PR. |
| `notes/brief.md` | Tu od razu na starcie wklejamy brief i kryteria oceny. |

## Setup (10 min, przed 20:00 albo zaraz na starcie)
```bash
gh auth login
chmod +x scripts/*.sh scripts/*.py .claude/hooks/*.sh
claude                      # raz interaktywnie w repo → zaakceptuj trust, /mcp → sprawdź playwright/context7
# Prelint: app.prelint.com → Connect GitHub → wybierz repo (5 min, bez CI)
# Codex: podłącz repo w Codex cloud + włącz code review dla repo
# Misha (Figma → kod): claude mcp add --transport http figma https://mcp.figma.com/mcp  → /mcp → Authenticate
```

## Flow
```bash
claude                      # /spec → SPEC.md ; /spec-to-issues → issues z labelami
scripts/wt.sh 1             # T1 szkielet — Claude, sekwencyjnie, reszta czeka/przygotowuje
# dalej równolegle, każde w osobnej karcie terminala:
scripts/wt.sh 2 codex       # Codex CLI we własnym worktree
scripts/wt.sh 3             # Claude Code we własnym worktree
# albo bez kart — sesje Claude Code w tle:
claude --bg --name issue-4 "Implement GitHub issue #4 following AGENTS.md, open a PR"
claude agents               # dashboard wszystkich sesji: Space — podgląd, Enter — wejście
# co 60–90 min:
claude                      # /integrate → merge zielonych PR, verifier po demo-flow
```
Na PR: Prelint robi review automatycznie; napisz `@codex review` na PR od Claude — krzyżowe review łapie więcej.

## Przed snem
- Zadania w Codex cloud **działają, gdy laptop śpi** → tam 2–3 izolowane tickety (testy, dane seed, osobny ekran).
- Sesje `claude --bg` **zatrzymują się, gdy laptop zasypia** → na macOS `caffeinate -dims &` albo nie odpalać ich na noc.

## Zasady, które ratują noc
1. Szkielet (T1) + `contracts/` — do 22:30. Potem kontrakty są zamrożone.
2. Jedno issue = jedna gałąź = jeden worktree = jeden agent. Dwóch agentów nigdy nie edytuje tych samych plików.
3. Merge do `main` co 60–90 min (`/integrate`). Maks. ~6 otwartych PR naraz.
4. Agenta trzeba było poprawiać więcej niż dwa razy — zabij sesję, przepisz ticket.
5. O 08:00 feature freeze. Dalej tylko bugi, demo, pitch.
