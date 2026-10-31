# Agent camera orb — design reference ("Sunset" palette)

Source: designer bundle `Agent Clips.html` (Claude Design export, React + Babel). The orb logic lives in
`orb-reference.jsx` (JSX, timeline-driven). Fonts: `DrukWideCyr.ttf` (Ask question text), `Onest-latin.woff2`,
`JetBrainsMono-latin.woff2`. HACK: Druk Wide is a commercial font; private repo, demo use only.

Palette (from source): O `#FF8A1A`, R `#E0255E`, PL `#4A0F2A`, CR `#FFE3A3`, INK `#FFF3E6`.

## States (orb = the agent's camera)
1. **Idle** (loop 4 s): soft-rayed star, does not rotate, only breathes (scale in/out, 4 s). Muted colour, weak glow.
2. **Listening** (loop 8 s): rounded square, jitters to the rhythm of the other person's voice. Orange rings
   contract inward, as if it is pulling in sound. Louder voice means brighter rings and a stronger pulse.
3. **Thinking** (loop 4 s): almost round and calm outside. Orange, cream and crimson blobs swirl inside; brightness flickers slowly.
4. **Speaking** (loop 8 s): perfect circle, the brightest and warmest state. It swells on every syllable, and its edge ripples with the voice.

**Transitions:** 12 (every pair), 0.8 s each. Shape, colour, size, rings and inner blobs morph smoothly.

## Asking (4 clips)
- **Ask in** (3.5 s): from Idle the orb slides to the left third of the frame and shrinks, while speaking. On the right, the question
  types out in large Druk Wide with an orange cursor. A dark plate with a phrase appears under it. Ends in Listening.
- **Ask countdown** (8 s in the design): the orb listens. The dark-wine fill in the plate drains left→right; the last 3 s turn crimson.
- **Ask confirmed** (1.2 s): the plate fills coral with a flash, the text fades, the orb returns to the centre and goes to Thinking.
- **Ask timeout** (1 s): the text fades, the orb returns to the centre and goes to Idle.
- Every clip starts and ends on its state's rest frame, so clips join in any order.

## Mapping to Call Crew (decision 24)
| Orb | Trigger |
|---|---|
| idle | default; after an answer finishes playing |
| listening | room audio level from the page mic (Recall feeds call audio to the page as microphone), above a threshold, while not speaking |
| thinking | server → page `{"type":"state","state":"thinking"}` when a "Crew, …" trigger fires |
| speaking | while queued audio plays; syllable swell = output audio level |
| ask in → countdown | server → page `{"type":"ask","id","question","expert","timeout_s"}` on `escalation_created`; plate text = `ASKING <EXPERT> ON SLACK`; countdown spans `timeout_s` (120), last 10 % crimson |
| ask confirmed / timeout | server → page `{"type":"ask_done","id","result":"answered"|"timeout"}` |

The design's plate phrase "YES, ATLAS" is a placeholder; we show the expert + channel instead.
