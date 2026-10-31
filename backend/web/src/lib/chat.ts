// Questions to the assistant: the general Discuss thread and one thread per call.
// Answers come from POST /chat (it searches every call and the knowledge base) and type themselves out.
import { useSyncExternalStore } from "react"
import { ApiError, api, type Citation } from "@/lib/api"

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  text: string
  citations?: Citation[]
  /** Still waiting for the answer or typing it out */
  streaming?: boolean
  failed?: boolean
}

export const DISCUSS = "discuss"
export const callScope = (id: string) => `call:${id}`

const KEY = "cta.threads"
const EMPTY: ChatMessage[] = []

function load(): Record<string, ChatMessage[]> {
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) ?? "{}") as Record<string, ChatMessage[]>
    // An answer cut off by a reload is not coming back
    for (const k of Object.keys(saved)) saved[k] = saved[k].filter((m) => !(m.streaming && !m.text)).map((m) => ({ ...m, streaming: false }))
    return saved
  } catch {
    return {}
  }
}

let threads = load()
const listeners = new Set<() => void>()
const running = new Map<string, { abort: AbortController; timer?: ReturnType<typeof setTimeout> }>()

function commit(scope: string, messages: ChatMessage[]) {
  threads = { ...threads, [scope]: messages }
  try {
    sessionStorage.setItem(KEY, JSON.stringify(threads))
  } catch {
    // full or private: keep it in memory
  }
  listeners.forEach((l) => l())
}

const patch = (scope: string, id: string, change: Partial<ChatMessage>) =>
  commit(scope, (threads[scope] ?? EMPTY).map((m) => (m.id === id ? { ...m, ...change } : m)))

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => listeners.delete(l)
}

export function useThread(scope: string): ChatMessage[] {
  return useSyncExternalStore(subscribe, () => threads[scope] ?? EMPTY)
}

const newId = () => Math.random().toString(36).slice(2, 10)

/** Reveals the answer a few words at a time; long answers go faster */
function typeOut(scope: string, id: string, answer: string, citations: Citation[]) {
  const words = answer.match(/\S+\s*/g) ?? [answer]
  const step = Math.max(1, Math.ceil(words.length / 160))
  let shown = 0
  const tick = () => {
    shown = Math.min(words.length, shown + step)
    const done = shown >= words.length
    patch(scope, id, { text: words.slice(0, shown).join(""), ...(done ? { streaming: false, citations } : {}) })
    if (done) running.delete(scope)
    else {
      const entry = running.get(scope)
      if (entry) entry.timer = setTimeout(tick, 16 + Math.random() * 22)
    }
  }
  tick()
}

async function answer(scope: string, question: string, callTitle?: string) {
  const reply: ChatMessage = { id: newId(), role: "assistant", text: "", streaming: true }
  commit(scope, [...(threads[scope] ?? EMPTY), reply])
  const abort = new AbortController()
  running.set(scope, { abort })
  // The backend searches all calls; naming the call keeps the answer about it. /chat takes 500 characters.
  const asked = (callTitle ? `About the call “${callTitle}”: ${question}` : question).slice(0, 500)
  try {
    const res = await api.chat(asked, abort.signal, true)
    if (abort.signal.aborted) return
    typeOut(scope, reply.id, res.answer, res.citations ?? [])
  } catch (e) {
    running.delete(scope)
    if (abort.signal.aborted) {
      commit(scope, (threads[scope] ?? EMPTY).filter((m) => m.id !== reply.id))
      return
    }
    const reason = e instanceof ApiError ? e.message : "The server didn't answer."
    patch(scope, reply.id, { text: `Couldn't get an answer. ${reason}`, streaming: false, failed: true })
  }
}

export const chat = {
  ask(scope: string, question: string, callTitle?: string) {
    if (running.has(scope)) return
    commit(scope, [...(threads[scope] ?? EMPTY), { id: newId(), role: "user", text: question }])
    void answer(scope, question, callTitle)
  },
  /** Stops waiting, or stops typing and keeps what is already shown */
  stop(scope: string) {
    const entry = running.get(scope)
    if (!entry) return
    entry.abort.abort()
    clearTimeout(entry.timer)
    running.delete(scope)
    commit(scope, (threads[scope] ?? EMPTY).filter((m) => !(m.streaming && !m.text)).map((m) => ({ ...m, streaming: false })))
  },
  regenerate(scope: string, callTitle?: string) {
    const list = threads[scope] ?? EMPTY
    const last = list[list.length - 1]
    const question = [...list].reverse().find((m) => m.role === "user")
    if (running.has(scope) || last?.role !== "assistant" || !question) return
    commit(scope, list.slice(0, -1))
    void answer(scope, question.text, callTitle)
  },
  clear(scope: string) {
    chat.stop(scope)
    commit(scope, [])
  },
  clearAll() {
    for (const scope of running.keys()) chat.stop(scope)
    threads = {}
    try {
      sessionStorage.removeItem(KEY)
    } catch {
      // nothing to remove
    }
    listeners.forEach((l) => l())
  },
}
