// Calls from the backend, kept in sync: the list every 5 s, the open call over its WebSocket.
// The query cache is the one source of truth; REST answers and WS events are merged into it.
import { useEffect, useRef, useState } from "react"
import { useQueries, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { api, tokenRejected, wsUrl, type MeetingDetail, type MeetingRow } from "@/lib/api"
import { applyEvent, isEnded, isLive, mergeDetail, summaryIsLate, type LiveMessage } from "@/lib/call-state"

export type OrbState = "idle" | "listening" | "thinking" | "speaking"

export const meetingKey = (id: string) => ["meeting", id] as const

/** The cache is read after the request returns, so events that arrived meanwhile stay */
function meetingQuery(qc: QueryClient, id: string) {
  return {
    queryKey: meetingKey(id),
    queryFn: async () => mergeDetail(qc.getQueryData<MeetingDetail>(meetingKey(id)), await api.meeting(id)),
  }
}

/** The agent's name is its wake word ("Atlas, …"), editable in the testing tools */
export function useAgentName() {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: 5 * 60_000 })
  return data?.values.AGENT_NAME?.value?.trim() || "Atlas"
}

export function useCalls() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ["meetings"], queryFn: api.meetings, refetchInterval: 5000 })
  // The list can lag behind the open call's WebSocket: an ended call never shows as live again
  const rows: MeetingRow[] = (q.data?.items ?? []).map((r) => {
    const d = qc.getQueryData<MeetingDetail>(meetingKey(r.id))
    return d && isEnded(d.status) && !isEnded(r.status) ? { ...r, status: d.status, live: false } : r
  })
  return { rows, isLoading: q.isLoading, isError: q.isError }
}

/** Full details of the newest calls, for Tasks, People and search */
export function useCallDetails(rows: MeetingRow[], limit = 15): MeetingDetail[] {
  const qc = useQueryClient()
  const results = useQueries({
    queries: rows.slice(0, limit).map((r) => ({ ...meetingQuery(qc, r.id), staleTime: isEnded(r.status) ? 60_000 : 10_000 })),
  })
  return results.flatMap((r) => (r.data ? [r.data] : []))
}

/** A row put into the list right away, before the next sync brings the real one */
export function addPendingCall(qc: QueryClient, row: MeetingRow) {
  qc.setQueryData<{ items: MeetingRow[] }>(["meetings"], (d) => ({ items: [row, ...(d?.items ?? []).filter((x) => x.id !== row.id)] }))
}

/**
 * The open call. While it is joining or live: WebSocket (reconnects after 3 s, 4401 = wrong token),
 * plus a 4 s poll whenever the socket is down. After it ends: a 4 s poll until the summary is written
 * or clearly isn't coming. `activity` drives the orb: "Atlas" in a line → thinking, its answer → speaking.
 */
export function useLiveCall(id: string, agentName: string) {
  const qc = useQueryClient()
  const [wsOpen, setWsOpen] = useState(false)
  const wsOpenRef = useRef(false)
  const [activity, setActivity] = useState<OrbState>("listening")
  const activityTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const nameRef = useRef(agentName)
  useEffect(() => {
    nameRef.current = agentName
  })

  const query = useQuery({
    ...meetingQuery(qc, id),
    refetchInterval: (q) => {
      const m = q.state.data
      if (!m) return 4000
      if (isLive(m.status)) return wsOpenRef.current ? false : 4000
      return m.status === "done" && !m.summary && !summaryIsLate(m) ? 4000 : false
    },
  })
  const live = isLive(query.data?.status)

  useEffect(() => {
    if (!live) return
    let closed = false
    let ws: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined

    const pulse = (state: OrbState, seconds: number) => {
      setActivity(state)
      clearTimeout(activityTimer.current)
      activityTimer.current = setTimeout(() => setActivity("listening"), seconds * 1000)
    }
    const setOpen = (open: boolean) => {
      wsOpenRef.current = open
      setWsOpen(open)
    }

    const connect = () => {
      const socket = new WebSocket(wsUrl(id))
      ws = socket
      socket.onopen = () => {
        setOpen(true)
        // Catch up on anything said while the socket was down
        qc.invalidateQueries({ queryKey: meetingKey(id) })
      }
      socket.onmessage = (ev) => {
        let msg: LiveMessage
        try {
          msg = JSON.parse(ev.data)
        } catch {
          return
        }
        qc.setQueryData<MeetingDetail>(meetingKey(id), (prev) => (prev ? applyEvent(prev, msg) : prev))
        if (msg.type === "utterance") {
          const text = String(msg.data.text ?? "").toLowerCase()
          if (text.includes(nameRef.current.toLowerCase())) pulse("thinking", 20)
        } else if (msg.type === "agent_said") {
          pulse("speaking", 5)
        } else if (msg.type === "meeting_ended") {
          // The summary is written after the call: fetch now, the interval keeps asking
          qc.invalidateQueries({ queryKey: meetingKey(id) })
          qc.invalidateQueries({ queryKey: ["meetings"] })
        }
      }
      socket.onclose = (ev) => {
        setOpen(false)
        if (closed) return
        if (ev.code === 4401) tokenRejected()
        else retry = setTimeout(connect, 3000)
      }
    }
    connect()

    return () => {
      closed = true
      clearTimeout(retry)
      clearTimeout(activityTimer.current)
      setActivity("listening")
      if (ws) {
        // StrictMode runs this twice: the dead socket must not touch state afterwards
        ws.onopen = ws.onmessage = ws.onclose = null
        ws.close()
      }
      setOpen(false)
    }
  }, [id, live, qc])

  return { call: query.data, isLoading: query.isLoading, isError: query.isError, wsOpen, activity: live ? activity : ("idle" as OrbState) }
}
