// Questions and answers (ios/ChatUI/MessageViews.swift, Composer.swift): the user's bubble on the right,
// the answer full width with its sources and actions, and the field at the bottom.
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react"
import { Link } from "react-router-dom"
import { ArrowUp, Check, Copy, FileText, Loader2, Mic, RotateCw, Square, Volume2 } from "lucide-react"
import { toast } from "sonner"
import { Orb } from "@/components/brand"
import type { Citation } from "@/lib/api"
import { fmtTs } from "@/lib/call-state"
import { chat, type ChatMessage } from "@/lib/chat"
import { useCalls } from "@/lib/live"
import { Markdown } from "@/lib/markdown"
import { speaker, useSpeaker, useVoiceInput } from "@/lib/speech"
import { cn } from "@/lib/utils"

/** Keeps a scroll view at the bottom while new content arrives (`content` changes), unless the user scrolled up */
export function useStickToBottom(ref: RefObject<HTMLElement | null>, content: unknown) {
  const pinned = useRef(true)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const onScroll = () => { pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120 }
    el.addEventListener("scroll", onScroll, { passive: true })
    return () => el.removeEventListener("scroll", onScroll)
  }, [ref])
  useLayoutEffect(() => {
    const el = ref.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [ref, content])
  return {
    toBottom: () => {
      pinned.current = true
      const el = ref.current
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
    },
  }
}

function Sources({ citations }: { citations: Citation[] }) {
  const { rows } = useCalls()
  const titles = new Map(rows.map((r) => [r.id, r.title?.trim() || "A call"]))
  const seen = new Set<string>()
  const unique = citations.filter((c) => {
    const key = c.type === "meeting" ? `${c.meeting_id}-${Math.floor(c.ts)}` : `doc-${c.doc_id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 6)
  if (!unique.length) return null
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[13px] font-semibold tracking-wide text-muted-foreground uppercase">Sources</p>
      <div className="flex flex-col gap-1.5">
        {unique.map((c, i) => c.type === "meeting" ? (
          <Link key={i} to={`/calls/${c.meeting_id}`} className="group flex flex-col rounded-2xl bg-surface px-3.5 py-2.5 transition-colors hover:bg-bubble">
            <span className="text-[14px] font-semibold group-hover:text-brand">{titles.get(c.meeting_id) ?? "A call"} · {fmtTs(c.ts)}</span>
            {c.text && <span className="line-clamp-2 text-[14px] text-muted-foreground">{c.speaker ? `${c.speaker}: ` : ""}“{c.text}”</span>}
          </Link>
        ) : (
          <Link key={i} to="/knowledge" className="group flex items-center gap-2 rounded-2xl bg-surface px-3.5 py-2.5 text-[14px] transition-colors hover:bg-bubble">
            <FileText className="size-4 text-muted-foreground" />
            <span className="font-semibold group-hover:text-brand">{c.title}</span>
            <span className="text-muted-foreground">v{c.version}</span>
          </Link>
        ))}
      </div>
    </div>
  )
}

function Answer({ m, isLast, scope, callTitle }: { m: ChatMessage; isLast: boolean; scope: string; callTitle?: string }) {
  const [copied, setCopied] = useState(false)
  const voice = useSpeaker()
  const playing = voice.playingId === m.id
  const loading = voice.loadingId === m.id
  if (m.streaming && !m.text) {
    return <Orb state="thinking" zoom={1.5} className="-my-2 -ml-3.5 size-14" />
  }
  return (
    <div className="flex flex-col gap-4">
      <Markdown text={m.text} className={cn(m.failed && "text-muted-foreground italic")} />
      {!m.streaming && m.citations && <Sources citations={m.citations} />}
      {!m.streaming && !m.failed && (
        <div className="flex items-center gap-1 text-muted-foreground [&_button]:inline-flex [&_button]:size-8 [&_button]:items-center [&_button]:justify-center [&_button]:rounded-full [&_button:hover]:bg-bubble [&_button:hover]:text-foreground [&_svg]:size-4">
          <button type="button" title="Copy" aria-label="Copy" onClick={() => {
            void navigator.clipboard.writeText(m.text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}>{copied ? <Check /> : <Copy />}</button>
          <button type="button" title={playing ? "Stop" : "Listen"} aria-label={playing ? "Stop" : "Listen"}
            onClick={() => (playing || loading ? speaker.stop() : void speaker.speak(m.id, m.text))}>
            {loading ? <Loader2 className="animate-spin" /> : playing ? <Square className="fill-current" /> : <Volume2 />}
          </button>
          {isLast && (
            <button type="button" title="Regenerate" aria-label="Regenerate" onClick={() => chat.regenerate(scope, callTitle)}><RotateCw /></button>
          )}
        </div>
      )}
    </div>
  )
}

export function Messages({ messages, scope, callTitle }: { messages: ChatMessage[]; scope: string; callTitle?: string }) {
  return (
    <div className="flex flex-col gap-7">
      {messages.map((m, i) => m.role === "user" ? (
        <div key={m.id} className="flex justify-end pl-14">
          <p className="rounded-[22px] bg-bubble px-4 py-2.5 text-[16px] leading-relaxed whitespace-pre-wrap">{m.text}</p>
        </div>
      ) : (
        <Answer key={m.id} m={m} isLast={i === messages.length - 1} scope={scope} callTitle={callTitle} />
      ))}
    </div>
  )
}

/** The field: Enter sends, Shift+Enter breaks the line; the mic asks by voice and reads the answer back */
export function Composer({ scope, callTitle, placeholder, busy, onSent }: {
  scope: string; callTitle?: string; placeholder: string; busy: boolean; onSent?: (byVoice: boolean) => void
}) {
  const [text, setText] = useState("")
  const field = useRef<HTMLTextAreaElement>(null)
  const voice = useVoiceInput()

  useLayoutEffect(() => {
    const el = field.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [text, voice.interim])

  const send = (value = text, byVoice = false) => {
    const q = value.trim()
    if (!q || busy) return
    chat.ask(scope, q, callTitle)
    setText("")
    onSent?.(byVoice)
  }

  const toggleVoice = () => {
    if (voice.listening) voice.stop()
    else voice.start((spoken) => send(spoken, true))
  }

  return (
    <div className="flex items-end gap-2 rounded-[28px] border border-border bg-background p-2 shadow-[0_4px_24px_rgb(22_18_19/0.08)]">
      <textarea
        ref={field}
        rows={1}
        value={voice.listening ? voice.interim : text}
        readOnly={voice.listening}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            send()
          }
        }}
        placeholder={voice.listening ? "Listening…" : placeholder}
        className="max-h-[200px] min-h-10 flex-1 resize-none bg-transparent px-3 py-2 text-[16px] leading-6 outline-none placeholder:text-placeholder"
      />
      {voice.supported && (
        <button type="button" onClick={toggleVoice} aria-label={voice.listening ? "Stop listening" : "Ask by voice"} title={voice.listening ? "Stop listening" : "Ask by voice"}
          className={cn("inline-flex size-10 shrink-0 items-center justify-center rounded-full transition-colors",
            voice.listening ? "bg-brand/10 text-brand" : "text-muted-foreground hover:bg-bubble hover:text-foreground")}>
          {voice.listening ? <Orb state="listening" zoom={1.6} className="size-10" /> : <Mic className="size-5" />}
        </button>
      )}
      {busy ? (
        <button type="button" onClick={() => chat.stop(scope)} aria-label="Stop" title="Stop"
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-foreground text-background">
          <Square className="size-3.5 fill-current" />
        </button>
      ) : (
        <button type="button" onClick={() => send()} disabled={!text.trim()} aria-label="Send" title="Send"
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-brand text-white transition-opacity disabled:opacity-30">
          <ArrowUp className="size-5" strokeWidth={2.6} />
        </button>
      )}
    </div>
  )
}

/** Reads the newest answer out loud once it is complete, when the question was asked by voice */
export function useSpeakAnswers(messages: ChatMessage[]) {
  const pending = useRef(false)
  const last = messages[messages.length - 1]
  useEffect(() => {
    if (pending.current && last?.role === "assistant" && !last.streaming) {
      pending.current = false
      if (!last.failed) void speaker.speak(last.id, last.text)
    }
  }, [last])
  return (byVoice: boolean) => { pending.current = byVoice }
}

export const copyText = (text: string, what: string) => {
  void navigator.clipboard.writeText(text).then(() => toast.success(`${what} copied`))
}
