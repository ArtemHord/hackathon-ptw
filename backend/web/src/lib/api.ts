import { toast } from "sonner"

// ---- types (docs/API.pl.md) ----
export type Mode = "notetaker" | "delegate"
export interface MeetingRow {
  id: string
  title: string | null
  platform: string
  mode: Mode
  status: string
  live: boolean
  started_at: string
  duration_min: number | null
}
export interface Utterance { id: string; speaker: string; text: string; ts: number }
export interface AgentSaid { id: string; text: string; ts: number; in_reply_to?: string | null }
export interface FactCheck {
  id: string; claim: string; verdict: "confirmed" | "contradicted" | "unverified"
  source: string | null; correction: string | null; ts: number; proposal_id: string | null
}
export interface Escalation {
  id: string; expert: string; channel: string; question: string; asked_by: string | null
  ts: number; status: "waiting" | "answered" | "timeout"; answer: string | null; answered_ts: number | null
}
export interface ActionItem {
  id: string; owner: string | null; text: string; due: string | null
  jira_key?: string | null; jira_url?: string | null
}
export interface MeetingDetail extends MeetingRow {
  summary: string
  decisions: string[]
  action_items: ActionItem[]
  fact_checks: FactCheck[]
  escalations: Escalation[]
  utterances: Utterance[]
  agent_said: AgentSaid[]
}
export type Citation =
  | { type: "meeting"; meeting_id: string; ts: number; speaker: string; text: string }
  | { type: "document"; doc_id: string; title: string; version: number }
export interface KbDoc { id: string; title: string; version: number; updated_at: string; chunks: number }
export interface Proposal {
  id: string; doc_id: string; doc_title: string; status: string; created_at: string
  meeting_id: string | null; ts: number | null; speaker: string | null
  reason: string; old_text: string; new_text: string
}
export interface SettingValue {
  secret: boolean; value: string | null; set: boolean; hint: string | null; source: "db" | "env" | "unset"
}
export interface SettingsResp { values: Record<string, SettingValue>; public_base_url: string }
export interface Integrations {
  slack: { configured: boolean; webhook_url: string }
  telegram: { configured: boolean; webhook_url: string; bot_username: string | null }
  jira: { configured: boolean; base_url: string | null; project_key: string | null }
}
export interface TestResult { ok: boolean; detail: string; bot_username?: string }
export interface Expert {
  id: string; name: string; role: string | null; topics: string[]; channel: "slack" | "telegram"
  email: string | null; slack_user_id: string | null; telegram_chat_id: string | null; is_owner: boolean
  profile?: "acme" | "msp"
}
export type ExpertInput = Partial<Omit<Expert, "id">>

// ---- auth ----
const KEY = "callcrew_token"
export const getToken = () => localStorage.getItem(KEY) ?? ""
export const setToken = (t: string) => localStorage.setItem(KEY, t)
export const clearToken = () => localStorage.removeItem(KEY)

let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn }

export class ApiError extends Error {
  status: number
  code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function raise(res: Response, quiet: boolean): Promise<never> {
  let code = "http_error"
  let message = `HTTP ${res.status}`
  try {
    const body = await res.json()
    if (body?.error) { code = body.error.code ?? code; message = body.error.message ?? message }
    else if (typeof body?.detail === "string") message = body.detail
  } catch { /* not json */ }
  if (res.status === 401) {
    clearToken()
    onUnauthorized()
  } else if (!quiet) {
    toast.error(`${code}: ${message}`)
  }
  throw new ApiError(res.status, code, message)
}

interface Opts { method?: string; json?: unknown; form?: FormData; quiet?: boolean }

async function raw(path: string, o: Opts = {}): Promise<Response> {
  const headers: Record<string, string> = { Authorization: `Bearer ${getToken()}` }
  let body: BodyInit | undefined
  if (o.form) body = o.form
  else if (o.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(o.json) }
  const res = await fetch(path, { method: o.method ?? (body ? "POST" : "GET"), headers, body })
  if (!res.ok) await raise(res, o.quiet ?? false)
  return res
}

async function req<T>(path: string, o: Opts = {}): Promise<T> {
  const res = await raw(path, o)
  return (await res.json()) as T
}

export const api = {
  health: () => fetch("/health").then((r) => r.ok).catch(() => false),
  /** validates a token against a cheap authenticated endpoint */
  checkToken: async (t: string) => {
    const res = await fetch("/meetings", { headers: { Authorization: `Bearer ${t}` } })
    return res.ok
  },
  meetings: () => req<{ items: MeetingRow[] }>("/meetings"),
  createMeeting: (b: { meeting_url: string; mode: Mode; brief?: string; title?: string }) =>
    req<{ id: string }>("/meetings", { json: b }),
  meeting: (id: string, since?: number) =>
    req<MeetingDetail>(`/meetings/${id}${since !== undefined ? `?since=${since}` : ""}`, { quiet: since !== undefined }),
  leave: (id: string) => req<{ id: string }>(`/meetings/${id}/leave`, { method: "POST" }),
  ask: (id: string, text?: string) => req<{ question: string }>(`/meetings/${id}/ask`, { json: text ? { text } : {} }),
  simulate: () => req<{ meeting_id: string }>("/debug/simulate", { json: { speed: 20, expert_reply: null } }),
  expertReply: (escalation_id: string, text: string) =>
    req<unknown>("/debug/expert-reply", { json: { escalation_id, text } }),
  createJira: (mid: string, itemId: string) =>
    req<{ jira_key: string; url: string }>(`/meetings/${mid}/action-items/${itemId}/jira`, { method: "POST" }),
  chat: (question: string) => req<{ answer: string; citations: Citation[] }>("/chat", { json: { question } }),
  tts: async (text: string) => (await raw("/tts", { json: { text } })).blob(),
  kbDocs: () => req<{ items: KbDoc[] }>("/kb/docs"),
  uploadDoc: (file: File, title?: string) => {
    const f = new FormData()
    f.append("file", file)
    if (title) f.append("title", title)
    return req<KbDoc>("/kb/docs", { form: f })
  },
  proposals: () => req<{ items: Proposal[] }>("/kb/proposals?status=all"),
  decide: (id: string, action: "approve" | "reject") => req<unknown>(`/kb/proposals/${id}/${action}`, { method: "POST" }),
  settings: () => req<SettingsResp>("/settings"),
  saveSettings: (b: Record<string, string>) => req<SettingsResp>("/settings", { method: "PUT", json: b }),
  integrations: () => req<Integrations>("/integrations"),
  testIntegration: (name: string) => req<TestResult>(`/integrations/${name}/test`, { method: "POST" }),
  experts: () => req<{ items: Expert[] }>("/experts"),
  createExpert: (b: ExpertInput) => req<Expert>("/experts", { json: b }),
  updateExpert: (id: string, b: ExpertInput) => req<Expert>(`/experts/${id}`, { method: "PUT", json: b }),
  deleteExpert: (id: string) => req<unknown>(`/experts/${id}`, { method: "DELETE" }),
  testExpert: (id: string) => req<TestResult>(`/experts/${id}/test`, { method: "POST" }),
}

export function wsUrl(meetingId: string) {
  const proto = location.protocol === "https:" ? "wss" : "ws"
  return `${proto}://${location.host}/app/ws?meeting_id=${encodeURIComponent(meetingId)}&token=${encodeURIComponent(getToken())}`
}

export const fmtTs = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`
