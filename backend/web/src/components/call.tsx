// Pieces of a call, as on the iOS call screen (ios/ChatUI/ConversationViews.swift).
import { useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import {
  CheckCircle2, Circle, CircleHelp, Clock, CornerDownLeft, MessageSquareReply, ShieldCheck, ShieldX, Sparkle, TimerOff,
} from "lucide-react"
import { Orb } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { ActionItem, Escalation, FactCheck, MeetingRow } from "@/lib/api"
import { displayTitle, fmtTs, isLive, metaLine } from "@/lib/call-state"
import type { OrbState } from "@/lib/live"
import { cn } from "@/lib/utils"

export function SectionTitle({ children, className }: { children: ReactNode; className?: string }) {
  return <h2 className={cn("text-[20px] font-bold tracking-tight", className)}>{children}</h2>
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3.5">
      <SectionTitle>{title}</SectionTitle>
      {children}
    </section>
  )
}

/** A gray line with an icon: placeholders while something is on its way */
export function Note({ icon: Icon, children }: { icon: typeof Clock; children: ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-[16px] text-muted-foreground">
      <Icon className="size-4 shrink-0" />
      {children}
    </p>
  )
}

export function LiveBadge({ status }: { status: string }) {
  return (
    <span className="inline-flex h-[22px] items-center gap-1.5 rounded-full bg-red-500/10 px-2 text-[11px] font-semibold tracking-wider text-red-600">
      <span className="size-[7px] rounded-full bg-red-500 animate-live" />
      {status === "joining" ? "JOINING" : "LIVE"}
    </span>
  )
}

// The same person gets the same color on the web and on the phone (the iOS app's hash)
const AVATAR_COLORS = ["#F58C33", "#3380F2", "#E6548C", "#29A673", "#9461F2", "#1A99B3", "#6B6B75"]
function avatarColor(name: string) {
  let h = 5381n
  for (const ch of name) h = BigInt.asIntN(64, (h << 5n) + h + BigInt(ch.codePointAt(0)!))
  const abs = h < 0n ? -h : h
  return AVATAR_COLORS[Number(abs % 7n)]
}

export function Avatar({ name, agent = false, size = 24, className }: { name: string; agent?: boolean; size?: number; className?: string }) {
  return (
    <span
      className={cn("inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white", agent && "bg-brand-gradient", className)}
      style={{ width: size, height: size, fontSize: size * 0.45, background: agent ? undefined : avatarColor(name) }}
      title={name}
    >
      {agent ? <Sparkle style={{ width: size * 0.5, height: size * 0.5 }} fill="currentColor" /> : name.slice(0, 1).toUpperCase()}
    </span>
  )
}

export function AvatarStack({ names, size = 24 }: { names: string[]; size?: number }) {
  return (
    <span className="flex">
      {names.map((n, i) => (
        <span key={n} className="flex" style={{ marginLeft: i === 0 ? 0 : -size * 0.3 }}>
          <Avatar name={n} size={size} className="ring-2 ring-background" />
        </span>
      ))}
    </span>
  )
}

/** The agent in the call: the orb follows what it is doing */
export function AgentCard({ status, mode, activity, agentName }: { status: string; mode: string; activity: OrbState; agentName: string }) {
  const title = status === "joining"
    ? `${agentName} is joining the call…`
    : activity === "thinking" ? `${agentName} is thinking…`
    : activity === "speaking" ? `${agentName} is answering…`
    : `${agentName} is listening`
  const detail = mode === "delegate"
    ? `Say “${agentName}, …” in the call to ask. Questions it can't answer go to an expert.`
    : "Taking notes. The summary and tasks appear when the call ends."
  return (
    <div className="flex items-center gap-4 rounded-[22px] bg-surface p-4">
      <Orb state={status === "joining" ? "thinking" : activity} zoom={1.4} className="-m-1.5 size-[64px] shrink-0" />
      <div className="flex min-w-0 flex-col gap-0.5">
        <p className="text-[17px] font-semibold">{title}</p>
        <p className="text-[14px] text-muted-foreground">{detail}</p>
      </div>
    </div>
  )
}

export function TaskRow({
  item, done, onToggle, onCreateJira, creatingJira,
}: { item: ActionItem; done: boolean; onToggle: () => void; onCreateJira?: () => void; creatingJira?: boolean }) {
  const details = [item.owner, item.due && `due ${item.due}`].filter(Boolean).join(" · ")
  return (
    <div className="flex items-start gap-3">
      <button type="button" onClick={onToggle} className="group flex min-w-0 flex-1 items-start gap-3 text-left">
        {done
          ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-brand" />
          : <Circle className="mt-0.5 size-5 shrink-0 text-muted-foreground group-hover:text-foreground" />}
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className={cn("text-[17px]", done && "text-muted-foreground line-through")}>{item.text}</span>
          {details && <span className="text-[14px] text-muted-foreground">{details}</span>}
        </span>
      </button>
      {item.jira_key ? (
        item.jira_url
          ? <a href={item.jira_url} target="_blank" rel="noreferrer" className="mt-0.5 rounded-full bg-bubble px-2.5 py-0.5 text-[13px] font-semibold hover:bg-border">{item.jira_key}</a>
          : <span className="mt-0.5 text-[13px] font-semibold text-muted-foreground">{item.jira_key}</span>
      ) : onCreateJira ? (
        <Button variant="ghost" size="sm" className="mt-0.5 text-muted-foreground" disabled={creatingJira} onClick={onCreateJira}>
          Add to Jira
        </Button>
      ) : null}
    </div>
  )
}

const CHANNELS: Record<string, string> = { slack: "Slack", telegram: "Telegram" }

/** A question the agent couldn't answer and sent to an expert */
export function EscalationCard({ e, onReply }: { e: Escalation; onReply?: (text: string) => Promise<unknown> }) {
  const [replying, setReplying] = useState(false)
  const [text, setText] = useState("")
  const [sending, setSending] = useState(false)
  const who = e.expert || "an expert"
  const channel = CHANNELS[e.channel] ?? e.channel ?? "chat"
  const line = e.status === "waiting" ? `Waiting for ${who} on ${channel}`
    : e.status === "answered" ? `${who} answered on ${channel}` : `${who} didn't answer in time`
  const Icon = e.status === "waiting" ? Clock : e.status === "answered" ? MessageSquareReply : TimerOff
  const send = async () => {
    if (!onReply || !text.trim()) return
    setSending(true)
    try {
      await onReply(text.trim())
      setReplying(false)
      setText("")
    } finally {
      setSending(false)
    }
  }
  return (
    <div className="flex flex-col gap-2.5 rounded-[20px] bg-surface p-4">
      <p className="flex items-center gap-1.5 text-[14px] font-medium text-muted-foreground">
        <Icon className={cn("size-4", e.status === "waiting" ? "text-amber-500" : e.status === "answered" ? "text-green-600" : "")} />
        {line}
      </p>
      <p className="text-[17px]">“{e.question}”</p>
      {e.answer && (
        <p className="flex items-start gap-2 text-[16px]">
          <CornerDownLeft className="mt-1 size-4 shrink-0 text-brand" />
          {e.answer}
        </p>
      )}
      {e.status === "waiting" && onReply && (replying ? (
        <form className="flex gap-2" onSubmit={(ev) => { ev.preventDefault(); void send() }}>
          <Input autoFocus value={text} onChange={(ev) => setText(ev.target.value)} placeholder={`${e.expert ?? "Expert"}'s answer`} className="h-10 rounded-full bg-background px-4" />
          <Button type="submit" className="h-10 rounded-full px-4" disabled={sending || !text.trim()}>Send</Button>
          <Button type="button" variant="ghost" className="h-10 rounded-full" onClick={() => setReplying(false)}>Cancel</Button>
        </form>
      ) : (
        <div>
          <Button className="h-9 rounded-full px-4 text-[15px]" onClick={() => setReplying(true)}>
            <MessageSquareReply /> Reply as {e.expert ?? "expert"}
          </Button>
        </div>
      ))}
    </div>
  )
}

/** A claim from the call checked against the knowledge base */
export function FactCheckRow({ f }: { f: FactCheck }) {
  const label = f.verdict === "confirmed" ? "Confirmed" : f.verdict === "contradicted" ? "Contradicted" : "Not verified"
  const Icon = f.verdict === "confirmed" ? ShieldCheck : f.verdict === "contradicted" ? ShieldX : CircleHelp
  return (
    <div className="flex items-start gap-3">
      <Icon className={cn("mt-0.5 size-5 shrink-0", f.verdict === "confirmed" ? "text-green-600" : f.verdict === "contradicted" ? "text-red-600" : "text-muted-foreground")} />
      <div className="flex flex-col gap-1">
        <p className="text-[17px]">{f.claim}</p>
        {f.correction && <p className="text-[15px] text-foreground/80">{f.correction}</p>}
        <p className="text-[14px] text-muted-foreground">{[label, f.source].filter(Boolean).join(" · ")}</p>
      </div>
    </div>
  )
}

/** One line of the transcript; the agent's lines are marked AI */
export function TranscriptLine({ speaker, text, ts, agent }: { speaker: string; text: string; ts: number; agent?: boolean }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <Avatar name={speaker} agent={agent} size={22} />
        <span className="text-[15px] font-semibold">{speaker}</span>
        {agent && <span className="rounded-full bg-brand/12 px-1.5 text-[11px] font-bold leading-[18px] text-brand">AI</span>}
        <span className="text-[13px] tabular-nums text-muted-foreground">{fmtTs(ts)}</span>
      </div>
      <p className="pl-[30px] text-[17px] leading-relaxed">{text}</p>
    </div>
  )
}

/** A call in lists: title, time, duration and who spoke */
export function CallRow({ call, people = [], withDay = true }: { call: MeetingRow; people?: string[]; withDay?: boolean }) {
  return (
    <Link to={`/calls/${call.id}`} className="flex items-center gap-3 rounded-2xl px-3 py-3 transition-colors hover:bg-bubble">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-[17px]">{displayTitle(call)}</span>
        <span className="flex items-center gap-2 text-[14px] text-muted-foreground">
          {isLive(call.status) && <LiveBadge status={call.status} />}
          {metaLine(call, withDay)}
        </span>
      </div>
      {people.length > 0 && <AvatarStack names={people.slice(0, 4)} size={22} />}
    </Link>
  )
}
