// How a call's data comes together from REST polls and WebSocket events.
// The same rules as the iOS app (ios/ChatUI/ConversationStore.swift).
import type { Escalation, MeetingDetail, MeetingRow } from "@/lib/api"

export const isLive = (status?: string | null) => status === "joining" || status === "in_call"
export const isEnded = (status?: string | null) => status === "done" || status === "failed"

/** The backend never reopens a call: once done or failed, a stale response can't make it live again */
export function advance(current: string | undefined, next: string | undefined): string {
  if (!next) return current ?? "scheduled"
  return current && isEnded(current) ? current : next
}

/** Fetched items win unless `keepOld` says ours is newer; items only the WebSocket brought so far stay */
export function mergeById<T extends { id: string }>(current: T[], fetched: T[], keepOld?: (old: T, fresh: T) => boolean): T[] {
  const old = new Map(current.map((x) => [x.id, x]))
  const ids = new Set(fetched.map((x) => x.id))
  const updated = fetched.map((x) => {
    const o = old.get(x.id)
    return o && keepOld?.(o, x) ? o : x
  })
  return [...updated, ...current.filter((x) => !ids.has(x.id))]
}

/** An answer that arrived over the WebSocket isn't rolled back by a poll that left before it */
const keepAnswered = (old: Escalation, fresh: Escalation) => old.status !== "waiting" && fresh.status === "waiting"

const byTs = <T extends { ts: number }>(list: T[]) => [...list].sort((a, b) => a.ts - b.ts)

export function mergeDetail(prev: MeetingDetail | undefined, fresh: MeetingDetail): MeetingDetail {
  if (!prev) return { ...fresh, utterances: byTs(fresh.utterances), agent_said: byTs(fresh.agent_said) }
  return {
    ...fresh,
    status: advance(prev.status, fresh.status),
    duration_min: fresh.duration_min ?? prev.duration_min,
    utterances: byTs(mergeById(prev.utterances, fresh.utterances)),
    agent_said: byTs(mergeById(prev.agent_said, fresh.agent_said)),
    fact_checks: mergeById(prev.fact_checks, fresh.fact_checks),
    escalations: mergeById(prev.escalations, fresh.escalations, keepAnswered),
  }
}

export interface LiveMessage {
  type: string
  data: Record<string, unknown>
}

/** One WebSocket event (`{type, meeting_id, ts, data}`) applied to the call */
export function applyEvent(prev: MeetingDetail, msg: LiveMessage): MeetingDetail {
  const d = msg.data
  switch (msg.type) {
    case "utterance":
      return { ...prev, utterances: byTs(mergeById(prev.utterances, [d as unknown as MeetingDetail["utterances"][number]])) }
    case "agent_said":
      return { ...prev, agent_said: byTs(mergeById(prev.agent_said, [d as unknown as MeetingDetail["agent_said"][number]])) }
    case "fact_check":
      return { ...prev, fact_checks: mergeById(prev.fact_checks, [d as unknown as MeetingDetail["fact_checks"][number]]) }
    case "escalation_created":
    case "escalation_answered":
      return { ...prev, escalations: mergeById(prev.escalations, [d as unknown as Escalation], keepAnswered) }
    case "meeting_status":
      return { ...prev, status: advance(prev.status, String(d.status ?? "")) }
    case "meeting_ended":
      return {
        ...prev,
        status: typeof d.status === "string" && isEnded(d.status) ? d.status : "done",
        duration_min: typeof d.duration_min === "number" ? d.duration_min : prev.duration_min,
      }
    default:
      return prev
  }
}

/** Ended a while ago and still no summary: it isn't coming (no AI on the server, or it failed) */
export function summaryIsLate(m: Pick<MeetingRow, "status" | "started_at" | "duration_min"> & { summary?: string }, now = Date.now()) {
  if (m.status !== "done" || m.summary || !m.started_at) return false
  const end = new Date(m.started_at).getTime() + (m.duration_min ?? 0) * 60_000
  return end + 180_000 < now
}

/** Everyone who spoke, in order of first word */
export function speakers(m: Pick<MeetingDetail, "utterances">): string[] {
  const seen = new Set<string>()
  for (const u of m.utterances) {
    const name = u.speaker?.trim() || "Participant"
    seen.add(name)
  }
  return [...seen]
}

const PLATFORMS: Record<string, string> = { google_meet: "Google Meet", zoom: "Zoom", teams: "Microsoft Teams", microsoft_teams: "Microsoft Teams" }
export const platformName = (p?: string | null) =>
  p ? (PLATFORMS[p] ?? p.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())) : null

export const displayTitle = (m: Pick<MeetingRow, "title">) => m.title?.trim() || "Untitled call"

export const statusLabel: Record<string, string> = {
  scheduled: "Scheduled", joining: "Joining…", in_call: "Live", done: "Done", failed: "Failed",
}

/** "Oct 31, 08:17 · 12 min · Google Meet" */
export function metaLine(m: Pick<MeetingRow, "started_at" | "duration_min" | "status" | "platform">, withDay = true) {
  const parts: string[] = []
  if (m.started_at) {
    const date = new Date(m.started_at)
    parts.push(withDay
      ? date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
      : date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }))
  }
  if (m.status === "failed") parts.push("Failed")
  else if (!isLive(m.status) && m.duration_min !== null) parts.push(`${m.duration_min} min`)
  const platform = platformName(m.platform)
  if (platform) parts.push(platform)
  return parts.join(" · ")
}

export const fmtTs = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`

/** The whole call as text, for copying */
export function shareText(m: MeetingDetail, agentName: string) {
  const lines = [displayTitle(m), metaLine(m)]
  if (m.summary) lines.push("", "Summary", m.summary)
  if (m.decisions.length) lines.push("", "Decisions", ...m.decisions.map((d) => `• ${d}`))
  if (m.action_items.length) lines.push("", "Tasks to check", ...m.action_items.map((a) => `☐ ${a.text}${a.owner ? ` — ${a.owner}` : ""}`))
  const transcript = [
    ...m.utterances.map((u) => ({ ts: u.ts, who: u.speaker || "Participant", text: u.text })),
    ...m.agent_said.map((a) => ({ ts: a.ts, who: agentName, text: a.text })),
  ].sort((a, b) => a.ts - b.ts)
  lines.push("", "Transcript", ...transcript.map((l) => `[${fmtTs(l.ts)}] ${l.who}: ${l.text}`))
  return lines.join("\n")
}
