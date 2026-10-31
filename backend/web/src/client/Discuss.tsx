// Discuss: questions across all calls and documents (the app's general thread)
import { useRef } from "react"
import { SquarePen } from "lucide-react"
import { Orb } from "@/components/brand"
import { chat, DISCUSS, useThread } from "@/lib/chat"
import type { OrbState } from "@/lib/live"
import { useSpeaker } from "@/lib/speech"
import { RoundButton, TopBar } from "./shell"
import { Composer, Messages, useSpeakAnswers, useStickToBottom } from "./Thread"

const SUGGESTIONS = ["What did we decide this week?", "Which tasks are still open?", "What did the experts answer?"]

export default function Discuss() {
  const messages = useThread(DISCUSS)
  const scroller = useRef<HTMLDivElement>(null)
  const { toBottom } = useStickToBottom(scroller, messages)
  const markVoice = useSpeakAnswers(messages)
  const voice = useSpeaker()
  const last = messages[messages.length - 1]
  const busy = !!last?.streaming

  // Every orb on the screen follows the assistant
  const orb: OrbState = busy ? (last.text ? "speaking" : "thinking") : voice.loadingId ? "thinking" : voice.playingId ? "speaking" : "idle"

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scroller} className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <TopBar>
          <RoundButton label="New discussion" onClick={() => chat.clear(DISCUSS)} disabled={!messages.length}><SquarePen /></RoundButton>
        </TopBar>
        {messages.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-6 px-6 pb-10 text-center">
            <Orb state={orb} zoom={1.35} className="-my-6 size-[230px]" />
            <h1 className="max-w-md text-[26px] leading-tight font-bold">
              {orb === "idle" ? "What would you like to discuss?" : orb === "thinking" ? "Thinking…" : "Answering…"}
            </h1>
            <div className="flex flex-col items-center gap-2.5">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => chat.ask(DISCUSS, s)}
                  className="h-[42px] rounded-full border border-border bg-background px-5 text-[16px] shadow-[0_1px_2px_rgb(22_18_19/0.06)] transition-colors hover:bg-bubble">
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto w-full max-w-3xl flex-1 px-5 pt-2 pb-8">
            <Messages messages={messages} scope={DISCUSS} />
          </div>
        )}
      </div>
      <div className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4">
        <Composer scope={DISCUSS} placeholder="Ask about your calls" busy={busy} onSent={(byVoice) => { markVoice(byVoice); toBottom() }} />
      </div>
    </div>
  )
}
