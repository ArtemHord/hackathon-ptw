// New call, search and settings (ios/ChatUI/Sheets.swift)
import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, FlaskConical, LogOut, PlayCircle, Search } from "lucide-react"
import { CallRow } from "@/components/call"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { api, type MeetingDetail, type MeetingRow, type Mode } from "@/lib/api"
import { platformName, speakers } from "@/lib/call-state"
import { addPendingCall, useAgentName, useCallDetails, useCalls } from "@/lib/live"
import { PALETTES, prefs, usePrefs } from "@/lib/prefs"
import { cn } from "@/lib/utils"

const pendingRow = (id: string, b: Partial<MeetingRow>): MeetingRow => ({
  id, title: null, platform: null, mode: "delegate", status: "joining", live: true, started_at: new Date().toISOString(), duration_min: null, ...b,
})

/** Start a call: a demo replayed by the backend, or the agent joining a real Meet / Zoom / Teams link */
export function NewCallDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const agentName = useAgentName()
  const [link, setLink] = useState("")
  const [mode, setMode] = useState<Mode>("delegate")
  const [brief, setBrief] = useState("")
  const [title, setTitle] = useState("")

  const opened = (id: string, row: Partial<MeetingRow>) => {
    addPendingCall(qc, pendingRow(id, row))
    onClose()
    navigate(`/calls/${id}`)
  }
  // Slow enough to watch the transcript stream in; the expert question waits for a reply by hand
  const demo = useMutation({
    mutationFn: () => api.simulate({ speed: 2, expert_reply: null }),
    onSuccess: ({ meeting_id }) => {
      prefs.addDemoCall(meeting_id)
      opened(meeting_id, { title: "Simulated stand-up", platform: "google_meet" })
    },
  })
  const join = useMutation({
    mutationFn: () => api.createMeeting({
      meeting_url: link.trim(), mode, title: title.trim() || undefined,
      brief: mode === "delegate" && brief.trim() ? brief.trim() : undefined,
    }),
    onSuccess: (m) => {
      setLink("")
      setBrief("")
      setTitle("")
      opened(m.id, { title: title.trim() || null, mode })
    },
  })
  const validLink = /^https?:\/\/\S+\.\S+/.test(link.trim())

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="gap-5 rounded-[28px] p-6 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-[20px] font-bold">New call</DialogTitle>
        </DialogHeader>

        <section className="flex flex-col gap-3 rounded-[20px] bg-surface p-4">
          <p className="text-[15px] text-muted-foreground">
            The backend plays a short stand-up through its real pipeline: the transcript streams in, {agentName} answers,
            and a question goes to an expert you can answer here.
          </p>
          <Button className="h-11 rounded-full text-[16px]" disabled={demo.isPending} onClick={() => demo.mutate()}>
            <PlayCircle /> {demo.isPending ? "Starting…" : "Run a demo call"}
          </Button>
        </section>

        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (validLink) join.mutate() }}>
          <p className="text-[15px] font-semibold">Join a real call</p>
          <Input value={link} onChange={(e) => setLink(e.target.value)} placeholder="Meet, Zoom or Teams link" className="h-11 rounded-full px-4" inputMode="url" autoComplete="off" />
          <div className="grid grid-cols-2 gap-1 rounded-full bg-bubble p-1">
            {([["delegate", "Stands in for you"], ["notetaker", "Takes notes"]] as const).map(([value, label]) => (
              <button key={value} type="button" onClick={() => setMode(value)}
                className={cn("h-9 rounded-full text-[15px] font-medium transition-colors", mode === value ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                {label}
              </button>
            ))}
          </div>
          {mode === "delegate" && (
            <Textarea rows={3} value={brief} onChange={(e) => setBrief(e.target.value)} className="rounded-[18px] px-4 py-3"
              placeholder={`Brief: what ${agentName} may say. Done: SDK v2. Blocked: rate limit. Don't agree to deadlines.`} />
          )}
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title (optional)" className="h-11 rounded-full px-4" />
          <Button type="submit" variant="outline" className="h-11 rounded-full text-[16px]" disabled={!validLink || join.isPending}>
            {join.isPending ? "Sending…" : `Send ${agentName} to the call`}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function matches(row: MeetingRow, d: MeetingDetail | undefined, q: string) {
  const has = (s?: string | null) => !!s && s.toLowerCase().includes(q)
  if (has(row.title) || has(platformName(row.platform))) return true
  if (!d) return false
  return has(d.summary) || d.decisions.some(has) || d.action_items.some((a) => has(a.text) || has(a.owner))
    || d.utterances.some((u) => has(u.text)) || speakers(d).some(has)
}

/** Search across titles, summaries, tasks, transcripts and people */
export function SearchDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState("")
  const { rows } = useCalls()
  const details = useCallDetails(rows, 30)
  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    const byId = new Map(details.map((d) => [d.id, d]))
    return q ? rows.filter((r) => matches(r, byId.get(r.id), q)) : rows.slice(0, 8)
  }, [query, rows, details])
  const people = useMemo(() => new Map(details.map((d) => [d.id, speakers(d)])), [details])

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { onClose(); setQuery("") } }}>
      <DialogContent className="top-[12%] translate-y-0 gap-0 overflow-hidden rounded-[24px] p-0 sm:max-w-xl" showCloseButton={false}>
        <DialogTitle className="sr-only">Search calls</DialogTitle>
        <form className="flex items-center gap-3 border-b px-4" onSubmit={(e) => {
          e.preventDefault()
          if (results[0]) { navigate(`/calls/${results[0].id}`); onClose(); setQuery("") }
        }}>
          <Search className="size-5 text-muted-foreground" />
          <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search calls, people, tasks…"
            className="h-14 flex-1 bg-transparent text-[17px] outline-none placeholder:text-placeholder" />
        </form>
        <div className="max-h-[60vh] overflow-y-auto p-2" onClick={() => { onClose(); setQuery("") }}>
          {results.length === 0 && <p className="px-3 py-8 text-center text-[15px] text-muted-foreground">Nothing found for “{query}”.</p>}
          {results.map((r) => <CallRow key={r.id} call={r} people={people.get(r.id)} />)}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function SettingsDialog({ open, onClose, onLogout }: { open: boolean; onClose: () => void; onLogout: () => void }) {
  const { palette } = usePrefs()
  const agentName = useAgentName()
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="gap-5 rounded-[28px] p-6 sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-[20px] font-bold">Settings</DialogTitle>
          <DialogDescription>Calls, answers and the voice come from the Call Crew backend.</DialogDescription>
        </DialogHeader>

        <section className="flex flex-col gap-3">
          <p className="text-[15px] font-semibold">Color</p>
          <div className="flex gap-3">
            {PALETTES.map((p) => (
              <button key={p.id} type="button" title={p.title} aria-label={p.title} aria-pressed={palette === p.id} onClick={() => prefs.setPalette(p.id)}
                className={cn("rounded-full p-[3px] ring-2 transition", palette === p.id ? "ring-brand" : "ring-transparent hover:ring-border")}>
                <span className="flex size-8 items-center justify-center rounded-full text-white" style={{ background: `linear-gradient(135deg, ${p.stops.join(", ")})` }}>
                  {palette === p.id && <Check className="size-4" strokeWidth={3} />}
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="flex flex-col divide-y rounded-[20px] bg-surface text-[15px]">
          <div className="flex items-center justify-between px-4 py-3">
            <span>Assistant</span>
            <span className="text-muted-foreground">{agentName}</span>
          </div>
          <Link to="/test" onClick={onClose} className="flex items-center justify-between px-4 py-3 hover:text-brand">
            <span className="flex items-center gap-2"><FlaskConical className="size-4" /> Testing environment</span>
            <span className="text-muted-foreground">Setup, integrations, debug</span>
          </Link>
        </section>

        <Button variant="outline" className="h-11 rounded-full text-[16px]" onClick={onLogout}><LogOut /> Sign out</Button>
      </DialogContent>
    </Dialog>
  )
}
