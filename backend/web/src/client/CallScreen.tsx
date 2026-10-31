// One call (ios/ChatUI/ConversationViews.swift + ChatScreen.swift): live while it happens,
// then the summary, decisions, tasks, questions to experts, fact-checks and the transcript.
import { useEffect, useMemo, useRef, useState } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, Copy, FileText, Loader2, PhoneOff, TextQuote } from "lucide-react"
import { toast } from "sonner"
import {
  AgentCard, AvatarStack, EscalationCard, FactCheckRow, LiveBadge, Note, Section, SectionTitle, TaskRow, TranscriptLine,
} from "@/components/call"
import { api, type MeetingDetail } from "@/lib/api"
import { displayTitle, isLive, metaLine, shareText, speakers, summaryIsLate } from "@/lib/call-state"
import { callScope, useThread } from "@/lib/chat"
import { meetingKey, useAgentName, useLiveCall } from "@/lib/live"
import { Markdown } from "@/lib/markdown"
import { prefs, taskKey, usePrefs } from "@/lib/prefs"
import { Empty, RoundButton, TopBar } from "./shell"
import { Composer, Messages, copyText, useSpeakAnswers, useStickToBottom } from "./Thread"

/** Re-renders now and then, so "Writing the summary…" can turn into "No summary" */
function useClock(ms: number) {
  const [, setNow] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
}

function Summary({ call }: { call: MeetingDetail }) {
  useClock(10_000)
  if (call.summary) return <Markdown text={call.summary} />
  if (isLive(call.status)) return <Note icon={TextQuote}>The summary, decisions and tasks appear when the call ends.</Note>
  if (call.status === "failed") return <Note icon={AlertTriangle}>The agent couldn't join this call.</Note>
  if (summaryIsLate(call)) return <Note icon={FileText}>No summary for this call.</Note>
  return (
    <p className="flex items-center gap-2.5 text-[16px] text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> Writing the summary…
    </p>
  )
}

export default function CallScreen() {
  const { id = "" } = useParams()
  const agentName = useAgentName()
  const { call, isLoading, isError, activity } = useLiveCall(id, agentName)
  const { doneTasks, demoCalls } = usePrefs()
  const qc = useQueryClient()
  const scope = callScope(id)
  const messages = useThread(scope)
  const scroller = useRef<HTMLDivElement>(null)
  const lines = (call?.utterances.length ?? 0) + (call?.agent_said.length ?? 0)
  const { toBottom } = useStickToBottom(scroller, `${messages.length}:${messages[messages.length - 1]?.text.length ?? 0}:${isLive(call?.status) ? lines : 0}`)
  const markVoice = useSpeakAnswers(messages)

  // Open a call at the top
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 })
  }, [id])

  const leave = useMutation({
    mutationFn: () => api.leave(id),
    onSuccess: () => {
      toast.success(`${agentName} is leaving the call`)
      void qc.invalidateQueries({ queryKey: meetingKey(id) })
    },
  })
  const jira = useMutation({
    mutationFn: (itemId: string) => api.createJira(id, itemId),
    onSuccess: (r) => {
      toast.success(`Created ${r.jira_key}`)
      void qc.invalidateQueries({ queryKey: meetingKey(id) })
    },
  })

  const transcript = useMemo(() => call ? [
    ...call.utterances.map((u) => ({ key: `u-${u.id}`, speaker: u.speaker?.trim() || "Participant", text: u.text, ts: u.ts, agent: false })),
    ...call.agent_said.map((a) => ({ key: `a-${a.id}`, speaker: agentName, text: a.text, ts: a.ts, agent: true })),
  ].sort((a, b) => a.ts - b.ts) : [], [call, agentName])

  if (isError && !call) {
    return (
      <div className="flex flex-1 flex-col">
        <TopBar />
        <Empty title="Couldn't open this call" text="It may have been removed, or the server is unreachable." />
      </div>
    )
  }
  if (isLoading || !call) {
    return (
      <div className="flex flex-1 flex-col">
        <TopBar />
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-5 pt-4">
          <div className="h-8 w-2/3 animate-pulse rounded-xl bg-bubble" />
          <div className="h-4 w-1/3 animate-pulse rounded-lg bg-bubble" />
        </div>
      </div>
    )
  }

  const live = isLive(call.status)
  const title = displayTitle(call)
  const people = speakers(call)
  const busy = !!messages[messages.length - 1]?.streaming
  const isDemo = demoCalls.includes(id)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scroller} className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <TopBar>
          <RoundButton label="Copy the call as text" onClick={() => copyText(shareText(call, agentName), "Call")}><Copy /></RoundButton>
          {/* A demo call is replayed by the backend: there is no bot to remove */}
          {live && !isDemo && (
            <RoundButton label={`Remove ${agentName} from the call`} onClick={() => leave.mutate()} disabled={leave.isPending} className="text-red-600">
              <PhoneOff />
            </RoundButton>
          )}
        </TopBar>

        <article className="mx-auto flex w-full max-w-3xl flex-col gap-7 px-5 pt-1 pb-10">
          <header className="flex flex-col gap-2.5">
            <h1 className="text-[26px] leading-tight font-bold sm:text-[30px]">{title}</h1>
            <p className="flex flex-wrap items-center gap-2 text-[15px] text-muted-foreground">
              {live && <LiveBadge status={call.status} />}
              {metaLine(call)}
            </p>
            {people.length > 0 && (
              <p className="flex items-center gap-2.5 text-[15px] text-muted-foreground">
                <AvatarStack names={people.slice(0, 6)} size={26} />
                <span className="truncate">{people.join(", ")}</span>
              </p>
            )}
          </header>

          {live && <AgentCard status={call.status} mode={call.mode} activity={activity} agentName={agentName} />}

          <Section title="Summary"><Summary call={call} /></Section>

          {call.decisions.length > 0 && (
            <Section title="Decisions">
              <Markdown text={call.decisions.map((d) => `- ${d}`).join("\n")} />
            </Section>
          )}

          {call.action_items.length > 0 && (
            <Section title="Tasks to check">
              <div className="flex flex-col gap-3.5">
                {call.action_items.map((a) => {
                  const key = taskKey(id, a.id)
                  return (
                    <TaskRow key={a.id} item={a} done={doneTasks.includes(key)} onToggle={() => prefs.toggleTask(key)}
                      onCreateJira={() => jira.mutate(a.id)} creatingJira={jira.isPending && jira.variables === a.id} />
                  )
                })}
              </div>
            </Section>
          )}

          {call.escalations.length > 0 && (
            <Section title="Asked experts">
              <div className="flex flex-col gap-3">
                {call.escalations.map((e) => (
                  <EscalationCard key={e.id} e={e} onReply={async (text) => {
                    await api.expertReply(e.id, text)
                    toast.success(live ? `${agentName} will say it in the call` : "Answer saved with the call")
                    // A finished call has no WebSocket: fetch the answer
                    setTimeout(() => void qc.invalidateQueries({ queryKey: meetingKey(id) }), 800)
                  }} />
                ))}
              </div>
            </Section>
          )}

          {call.fact_checks.length > 0 && (
            <Section title="Fact checks">
              <div className="flex flex-col gap-4">
                {call.fact_checks.map((f) => <FactCheckRow key={f.id} f={f} />)}
              </div>
            </Section>
          )}

          <Section title="Transcript">
            {transcript.length === 0 ? (
              <Note icon={TextQuote}>{live ? "Waiting for the first words…" : "No transcript."}</Note>
            ) : (
              <div className="flex flex-col gap-5">
                {transcript.map((l) => <TranscriptLine key={l.key} speaker={l.speaker} text={l.text} ts={l.ts} agent={l.agent} />)}
              </div>
            )}
          </Section>

          {messages.length > 0 && (
            <section className="flex flex-col gap-5 pt-2">
              <SectionTitle>Discussion</SectionTitle>
              <Messages messages={messages} scope={scope} callTitle={title} />
            </section>
          )}
        </article>
      </div>
      <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4">
        <Composer scope={scope} callTitle={title} placeholder="Ask about this call" busy={busy}
          onSent={(byVoice) => { markVoice(byVoice); toBottom() }} />
      </div>
    </div>
  )
}
