# Call Crew web app

One React app (Vite, Tailwind 4, shadcn/base-ui), two versions behind one sign-in (`DEMO_TOKEN`):

| URL | For | What |
|---|---|---|
| `/ui/` | Clients | The iOS app's features and style: calls synced from the backend, the live call (WebSocket, agent orb), summary, decisions, tasks, questions to experts with "Reply as …", fact-checks, transcript, Discuss with sources, Listen, New call (demo or a real link), Calendar, Projects, People, Tasks, Knowledge. |
| `/ui/test/` | The team | Testing tools: calls table + simulate (speed, expert reply), call debug timeline (Ask agent, Leave, expert reply, Jira), raw chat, knowledge base, agent, experts, integrations. |

```bash
npm i
npm run dev                                  # http://localhost:5173/ui/ → backend on :8000
BACKEND_URL=http://127.0.0.1:8001 npm run dev  # another backend
npm run build && npm run lint                # FastAPI serves dist/ at /ui
```

- `src/client/` — the client app; `src/test/` — testing tools (lazy-loaded).
- `src/lib/live.ts` — calls list every 5 s, the open call over `/app/ws`; `src/lib/call-state.ts` — merge rules shared with the iOS app (status never goes back from done, cards merge by id).
- `src/components/brand.tsx` — logo and the orb (the designer's SVG animations in `src/assets/orb`).
- Theme: `src/index.css` maps the Call to Action colors onto shadcn's variables. HACK: Druk Wide (page titles) is a commercial font, as in `backend/agent_page`: demo use only.
