import { useCallback, useEffect, useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import {
  api, fmtTs, wsUrl,
  type ActionItem, type AgentSaid, type Escalation, type FactCheck, type MeetingDetail, type Utterance,
} from "@/lib/api"
import { cn } from "@/lib/utils"

type Feed = Pick<MeetingDetail, "utterances" | "agent_said" | "fact_checks" | "escalations">
type Item = { id: string; ts: number }

function upsert<T extends Item>(list: T[], item: T): T[] {
  const i = list.findIndex((x) => x.id === item.id)
  if (i < 0) return [...list, item]
  const copy = list.slice()
  copy[i] = item
  return copy
}
function upsertMany<T extends Item>(list: T[], items: T[]): T[] {
  return items.reduce(upsert, list)
}
const maxTs = (f: Feed) =>
  Math.max(0, ...f.utterances.map((x) => x.ts), ...f.agent_said.map((x) => x.ts), ...f.fact_checks.map((x) => x.ts), ...f.escalations.map((x) => x.ts))

const VERDICT: Record<string, string> = {
  confirmed: "bg-green-600 text-white", contradicted: "bg-red-600 text-white", unverified: "bg-amber-500 text-white",
}

function EscalationCard({ e }: { e: Escalation }) {
  const [text, setText] = useState("Thursday")
  const reply = useMutation({
    mutationFn: () => api.expertReply(e.id, text),
    onSuccess: () => toast.success("Expert reply sent"),
  })
  const color = e.status === "waiting" ? "bg-amber-500" : e.status === "answered" ? "bg-green-600" : "bg-red-600"
  return (
    <Card className="border-amber-300">
      <CardContent className="flex flex-col gap-2 py-3 text-sm">
        <div className="flex items-center gap-2">
          <span className="font-medium">Asked {e.expert} on {e.channel}</span>
          <Badge className={cn("text-white", color)}>{e.status}</Badge>
          <span className="ml-auto text-xs text-muted-foreground">{fmtTs(e.ts)}</span>
        </div>
        <div>Q: {e.question}</div>
        {e.answer && <div className="font-medium">A: {e.answer}</div>}
        {e.status === "waiting" && (
          <div className="flex gap-2">
            <Input value={text} onChange={(e) => setText(e.target.value)} className="max-w-xs" />
            <Button size="sm" variant="outline" disabled={reply.isPending || !text.trim()} onClick={() => reply.mutate()}>
              Simulate expert reply
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function FactCheckCard({ f }: { f: FactCheck }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 py-3 text-sm">
        <div className="flex items-center gap-2">
          <span className="font-medium">Fact check</span>
          <Badge className={VERDICT[f.verdict]}>{f.verdict}</Badge>
          <span className="ml-auto text-xs text-muted-foreground">{fmtTs(f.ts)}</span>
        </div>
        <div>Claim: {f.claim}</div>
        {f.correction && <div>Correction: {f.correction}</div>}
        {f.source && <div className="text-xs text-muted-foreground">Source: {f.source}</div>}
        {f.proposal_id && (
          <Link to="/kb" className="text-xs underline">KB proposal {f.proposal_id}</Link>
        )}
      </CardContent>
    </Card>
  )
}

type Row =
  | { k: "u"; ts: number; v: Utterance }
  | { k: "a"; ts: number; v: AgentSaid }
  | { k: "f"; ts: number; v: FactCheck }
  | { k: "e"; ts: number; v: Escalation }

function Timeline({ feed }: { feed: Feed }) {
  const rows: Row[] = [
    ...feed.utterances.map((v) => ({ k: "u" as const, ts: v.ts, v })),
    ...feed.agent_said.map((v) => ({ k: "a" as const, ts: v.ts, v })),
    ...feed.fact_checks.map((v) => ({ k: "f" as const, ts: v.ts, v })),
    ...feed.escalations.map((v) => ({ k: "e" as const, ts: v.ts, v })),
  ].sort((a, b) => a.ts - b.ts)
  if (!rows.length) return <p className="text-sm text-muted-foreground">Nothing yet.</p>
  return (
    <div className="flex flex-col gap-2">
      {rows.map((r) => {
        const key = r.k + r.v.id
        if (r.k === "u")
          return (
            <div key={key} className="text-sm">
              <span className="mr-2 text-xs text-muted-foreground">{fmtTs(r.ts)}</span>
              <span className="font-medium">{r.v.speaker}:</span> {r.v.text}
            </div>
          )
        if (r.k === "a")
          return (
            <div key={key} className="rounded-md border-l-4 border-primary bg-muted px-3 py-2 text-sm">
              <span className="mr-2 text-xs text-muted-foreground">{fmtTs(r.ts)}</span>
              <Badge variant="secondary" className="mr-2">Agent</Badge>{r.v.text}
            </div>
          )
        if (r.k === "f") return <FactCheckCard key={key} f={r.v} />
        return <EscalationCard key={key} e={r.v} />
      })}
    </div>
  )
}

function ActionItems({ meetingId, items }: { meetingId: string; items: ActionItem[] }) {
  const qc = useQueryClient()
  const jira = useMutation({
    mutationFn: (id: string) => api.createJira(meetingId, id),
    onSuccess: (r) => { toast.success(`Created ${r.jira_key}`); qc.invalidateQueries({ queryKey: ["meeting", meetingId] }) },
  })
  if (!items.length) return <p className="text-sm text-muted-foreground">None.</p>
  return (
    <ul className="flex flex-col gap-2">
      {items.map((a) => (
        <li key={a.id} className="flex items-center gap-2 text-sm">
          <span className="flex-1">
            {a.text} <span className="text-muted-foreground">({a.owner ?? "unassigned"}{a.due ? `, due ${a.due}` : ""})</span>
          </span>
          {a.jira_key ? (
            a.jira_url ? <a href={a.jira_url} target="_blank" rel="noreferrer" className="underline">{a.jira_key}</a> : <Badge>{a.jira_key}</Badge>
          ) : (
            <Button size="sm" variant="outline" disabled={jira.isPending} onClick={() => jira.mutate(a.id)}>Create in Jira</Button>
          )}
        </li>
      ))}
    </ul>
  )
}

export default function Meeting() {
  const { id = "" } = useParams()
  const qc = useQueryClient()
  const { data: meeting, isLoading } = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api.meeting(id),
    // only poll while the post-call summary is still being generated
    refetchInterval: (q) => (q.state.data?.status === "done" && !q.state.data.summary ? 4000 : false),
  })

  const [feed, setFeed] = useState<Feed>({ utterances: [], agent_said: [], fact_checks: [], escalations: [] })
  const [status, setStatus] = useState<string>("")
  const [wsOk, setWsOk] = useState(false)
  const feedRef = useRef(feed)
  feedRef.current = feed

  // Seed from REST whenever the full object refreshes.
  useEffect(() => {
    if (!meeting) return
    setFeed({
      utterances: meeting.utterances, agent_said: meeting.agent_said,
      fact_checks: meeting.fact_checks, escalations: meeting.escalations,
    })
    setStatus(meeting.status)
  }, [meeting])

  const live = ["joining", "in_call"].includes(status)

  const onEvent = useCallback((msg: { type: string; data: Record<string, unknown> }) => {
    const d = msg.data
    switch (msg.type) {
      case "utterance": setFeed((f) => ({ ...f, utterances: upsert(f.utterances, d as unknown as Utterance) })); break
      case "agent_said": setFeed((f) => ({ ...f, agent_said: upsert(f.agent_said, d as unknown as AgentSaid) })); break
      case "fact_check": setFeed((f) => ({ ...f, fact_checks: upsert(f.fact_checks, d as unknown as FactCheck) })); break
      case "escalation_created":
      case "escalation_answered": setFeed((f) => ({ ...f, escalations: upsert(f.escalations, d as unknown as Escalation) })); break
      case "meeting_status": setStatus(String(d.status)); break
      case "meeting_ended":
        setStatus(String(d.status))
        // the summary is produced asynchronously: refetch now and the interval keeps polling until it shows up
        qc.invalidateQueries({ queryKey: ["meeting", id] })
        break
    }
  }, [id, qc])

  // WebSocket while live
  useEffect(() => {
    if (!live) return
    let closed = false
    let ws: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout>
    const connect = () => {
      ws = new WebSocket(wsUrl(id))
      ws.onopen = () => setWsOk(true)
      ws.onmessage = (ev) => { try { onEvent(JSON.parse(ev.data)) } catch { /* ignore */ } }
      ws.onclose = (ev) => {
        setWsOk(false)
        if (!closed && ev.code !== 4401) retry = setTimeout(connect, 3000)
      }
    }
    connect()
    return () => { closed = true; clearTimeout(retry); ws?.close(); setWsOk(false) }
  }, [id, live, onEvent])

  // Poll fallback while live and WS is down
  useEffect(() => {
    if (!live || wsOk) return
    const t = setInterval(async () => {
      try {
        const d = await api.meeting(id, maxTs(feedRef.current))
        setFeed((f) => ({
          utterances: upsertMany(f.utterances, d.utterances), agent_said: upsertMany(f.agent_said, d.agent_said),
          fact_checks: upsertMany(f.fact_checks, d.fact_checks), escalations: upsertMany(f.escalations, d.escalations),
        }))
        setStatus(d.status)
      } catch { /* retry next tick */ }
    }, 2000)
    return () => clearInterval(t)
  }, [id, live, wsOk])

  const [askText, setAskText] = useState("")
  const ask = useMutation({
    mutationFn: () => api.ask(id, askText.trim() || undefined),
    onSuccess: () => { setAskText(""); toast.success("Agent is on it") },
  })
  const leave = useMutation({
    mutationFn: () => api.leave(id),
    onSuccess: () => { setStatus("done"); qc.invalidateQueries({ queryKey: ["meeting", id] }) },
  })

  if (isLoading || !meeting) return <Skeleton className="h-60 w-full" />

  const done = status === "done"
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-semibold">{meeting.title || meeting.id}</h1>
        {live && <Badge className="bg-red-600 text-white">LIVE</Badge>}
        <Badge variant="outline">{meeting.mode}</Badge>
        <Badge variant="secondary">{status}</Badge>
        {live && <span className="text-xs text-muted-foreground">{wsOk ? "websocket" : "polling"}</span>}
        <div className="ml-auto flex gap-2">
          {live && <Button variant="destructive" disabled={leave.isPending} onClick={() => leave.mutate()}>Leave</Button>}
        </div>
      </div>

      {live && (
        <div className="flex gap-2">
          <Input placeholder="Ask agent (empty = last utterance)" value={askText} onChange={(e) => setAskText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask.mutate()} />
          <Button disabled={ask.isPending} onClick={() => ask.mutate()}>Ask agent</Button>
        </div>
      )}

      {done && (
        <Card>
          <CardHeader><CardTitle>Summary</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-4 text-sm">
            {meeting.summary ? <p>{meeting.summary}</p> : <p className="text-muted-foreground">Summary is being generated...</p>}
            <div>
              <h3 className="mb-1 font-medium">Decisions</h3>
              {meeting.decisions.length ? <ul className="list-disc pl-5">{meeting.decisions.map((d, i) => <li key={i}>{d}</li>)}</ul>
                : <p className="text-muted-foreground">None.</p>}
            </div>
            <div>
              <h3 className="mb-1 font-medium">Action items</h3>
              <ActionItems meetingId={id} items={meeting.action_items} />
            </div>
          </CardContent>
        </Card>
      )}

      <Separator />
      <h2 className="text-lg font-medium">{done ? "Full transcript" : "Live feed"}</h2>
      <Timeline feed={feed} />
    </div>
  )
}
