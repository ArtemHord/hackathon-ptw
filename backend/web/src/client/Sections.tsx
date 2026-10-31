// Sidebar sections (ios/ChatUI/SectionScreens.swift): Calendar, Projects, People, Tasks
import { useMemo } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, Video } from "lucide-react"
import { toast } from "sonner"
import { Avatar, CallRow, TaskRow } from "@/components/call"
import { api, type MeetingDetail, type MeetingRow } from "@/lib/api"
import { displayTitle, platformName, speakers } from "@/lib/call-state"
import { meetingKey, useCallDetails, useCalls } from "@/lib/live"
import { prefs, taskKey, usePrefs } from "@/lib/prefs"
import { Empty, ListHeader, SectionPage, useShell } from "./shell"

const calls = (n: number) => (n === 1 ? "1 call" : `${n} calls`)

/** Speakers of the calls we have details for, to show avatars in lists */
function usePeopleByCall(rows: MeetingRow[]) {
  const details = useCallDetails(rows, 30)
  return useMemo(() => new Map(details.map((d) => [d.id, speakers(d)])), [details])
}

function dayTitle(day: Date) {
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (day.toDateString() === today.toDateString()) return "Today"
  if (day.toDateString() === yesterday.toDateString()) return "Yesterday"
  return day.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" })
}

export function Calendar() {
  const { rows, isLoading } = useCalls()
  const people = usePeopleByCall(rows)
  const { openNewCall } = useShell()
  const days = useMemo(() => {
    const groups = new Map<string, { day: Date | null; items: MeetingRow[] }>()
    for (const r of rows) {
      const day = r.started_at ? new Date(r.started_at) : null
      const key = day ? day.toDateString() : "none"
      if (!groups.has(key)) groups.set(key, { day, items: [] })
      groups.get(key)!.items.push(r)
    }
    return [...groups.values()].sort((a, b) => (b.day?.getTime() ?? Infinity) - (a.day?.getTime() ?? Infinity))
  }, [rows])

  return (
    <SectionPage title="Calendar">
      {!isLoading && rows.length === 0 && (
        <Empty title="No calls yet" text="Calls appear here by day.">
          <button type="button" onClick={openNewCall} className="mt-3 h-10 rounded-full bg-brand px-5 font-semibold text-white">Run a demo call</button>
        </Empty>
      )}
      {days.map((g) => (
        <div key={g.day?.toDateString() ?? "none"}>
          <ListHeader>{g.day ? dayTitle(g.day) : "Not started"}</ListHeader>
          {g.items.map((c) => <CallRow key={c.id} call={c} people={people.get(c.id)} withDay={false} />)}
        </div>
      ))}
    </SectionPage>
  )
}

export function Projects() {
  const { rows } = useCalls()
  // The backend has no projects yet: calls are grouped by where they happened
  const groups = useMemo(() => {
    const map = new Map<string, number>()
    for (const r of rows) map.set(r.platform ?? "other", (map.get(r.platform ?? "other") ?? 0) + 1)
    return [...map.entries()]
  }, [rows])
  return (
    <SectionPage title="Projects">
      {groups.length === 0 && <Empty title="No projects yet" text="Calls are grouped by Meet, Zoom or Teams." />}
      <div className="flex flex-col">
        {groups.map(([platform, count]) => (
          <Link key={platform} to={`/projects/${encodeURIComponent(platform)}`} className="flex items-center gap-4 rounded-2xl px-3 py-3 hover:bg-bubble">
            <span className="flex size-10 items-center justify-center rounded-full bg-surface"><Video className="size-5" /></span>
            <span className="flex flex-1 flex-col">
              <span className="text-[17px]">{platformName(platform === "other" ? null : platform) ?? "Other"}</span>
              <span className="text-[14px] text-muted-foreground">{calls(count)}</span>
            </span>
            <ChevronRight className="size-5 text-muted-foreground" />
          </Link>
        ))}
      </div>
    </SectionPage>
  )
}

export function ProjectCalls() {
  const { platform = "" } = useParams()
  const { rows } = useCalls()
  const items = rows.filter((r) => (r.platform ?? "other") === platform)
  const people = usePeopleByCall(items)
  return (
    <SectionPage title={platformName(platform === "other" ? null : platform) ?? "Other"}>
      {items.map((c) => <CallRow key={c.id} call={c} people={people.get(c.id)} />)}
    </SectionPage>
  )
}

interface PersonEntry { name: string; role: string | null; owner: boolean }

/** Who took part in a call: spoke, owns a task, or was asked a question */
function involves(d: MeetingDetail, name: string) {
  return speakers(d).includes(name)
    || d.action_items.some((a) => a.owner === name)
    || d.escalations.some((e) => e.expert === name)
}

function usePeople() {
  const { rows } = useCalls()
  const details = useCallDetails(rows, 30)
  const experts = useQuery({ queryKey: ["experts"], queryFn: api.experts, staleTime: 60_000 })
  const people = useMemo(() => {
    const byName = new Map<string, PersonEntry>()
    for (const e of experts.data?.items ?? []) byName.set(e.name, { name: e.name, role: e.role || null, owner: e.is_owner })
    for (const d of details) for (const n of speakers(d)) if (!byName.has(n)) byName.set(n, { name: n, role: null, owner: false })
    return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name))
  }, [experts.data, details])
  return { people, details, rows }
}

export function People() {
  const { people, details } = usePeople()
  return (
    <SectionPage title="People">
      {people.length === 0 && <Empty title="No people yet" text="Experts and everyone who speaks in a call." />}
      <div className="flex flex-col">
        {people.map((p) => {
          const count = details.filter((d) => involves(d, p.name)).length
          return (
            <Link key={p.name} to={`/people/${encodeURIComponent(p.name)}`} className="flex items-center gap-4 rounded-2xl px-3 py-3 hover:bg-bubble">
              <Avatar name={p.name} size={40} />
              <span className="flex flex-1 flex-col">
                <span className="text-[17px]">{p.name}</span>
                <span className="text-[14px] text-muted-foreground">{[p.owner ? "Owner" : p.role, calls(count)].filter(Boolean).join(" · ")}</span>
              </span>
              <ChevronRight className="size-5 text-muted-foreground" />
            </Link>
          )
        })}
      </div>
    </SectionPage>
  )
}

export function PersonCalls() {
  const { name = "" } = useParams()
  const { details, rows } = usePeople()
  const ids = new Set(details.filter((d) => involves(d, name)).map((d) => d.id))
  const items = rows.filter((r) => ids.has(r.id))
  const people = usePeopleByCall(items)
  return (
    <SectionPage title={name}>
      {items.length === 0 && <Empty title="No calls yet" text={`Calls ${name} takes part in show up here.`} />}
      {items.map((c) => <CallRow key={c.id} call={c} people={people.get(c.id)} />)}
    </SectionPage>
  )
}

/** Tasks to check from every call; checked off on this device */
export function Tasks() {
  const { rows } = useCalls()
  const details = useCallDetails(rows, 30)
  const { doneTasks } = usePrefs()
  const qc = useQueryClient()
  const jira = useMutation({
    mutationFn: (v: { meetingId: string; itemId: string }) => api.createJira(v.meetingId, v.itemId),
    onSuccess: (r, v) => {
      toast.success(`Created ${r.jira_key}`)
      void qc.invalidateQueries({ queryKey: meetingKey(v.meetingId) })
    },
  })
  const withTasks = details.filter((d) => d.action_items.length > 0)
  return (
    <SectionPage title="Tasks">
      {withTasks.length === 0 && <Empty title="No tasks yet" text="Action items appear here after each call." />}
      {withTasks.map((d) => (
        <div key={d.id} className="mb-2">
          <ListHeader><Link to={`/calls/${d.id}`} className="hover:text-foreground">{displayTitle(d)}</Link></ListHeader>
          <div className="flex flex-col gap-3.5 px-3 py-2">
            {d.action_items.map((a) => {
              const key = taskKey(d.id, a.id)
              return (
                <TaskRow key={a.id} item={a} done={doneTasks.includes(key)} onToggle={() => prefs.toggleTask(key)}
                  onCreateJira={() => jira.mutate({ meetingId: d.id, itemId: a.id })}
                  creatingJira={jira.isPending && jira.variables?.itemId === a.id && jira.variables.meetingId === d.id} />
              )
            })}
          </div>
        </div>
      ))}
    </SectionPage>
  )
}
