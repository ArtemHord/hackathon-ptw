import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { api, fmtTs, type Citation } from "@/lib/api"

interface Turn { q: string; answer: string; citations: Citation[] }

export default function Chat() {
  const [q, setQ] = useState("")
  const [turns, setTurns] = useState<Turn[]>([])
  const ask = useMutation({
    mutationFn: (question: string) => api.chat(question),
    onSuccess: (r, question) => { setTurns((t) => [...t, { q: question, ...r }]); setQ("") },
  })
  const listen = useMutation({
    mutationFn: async (text: string) => {
      const url = URL.createObjectURL(await api.tts(text))
      const audio = new Audio(url)
      audio.onended = () => URL.revokeObjectURL(url)
      await audio.play()
    },
  })
  const send = () => q.trim() && ask.mutate(q.trim())

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">Chat</h1>
      {turns.map((t, i) => (
        <Card key={i}>
          <CardContent className="flex flex-col gap-3 py-4 text-sm">
            <div className="font-medium">{t.q}</div>
            <div className="whitespace-pre-wrap">{t.answer}</div>
            <div>
              <Button size="sm" variant="outline" disabled={listen.isPending} onClick={() => listen.mutate(t.answer)}>Listen</Button>
            </div>
            {t.citations.length > 0 && (
              <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
                {t.citations.map((c, j) => (
                  <li key={j}>
                    {c.type === "meeting" ? (
                      <Link className="underline" to={`/meetings/${c.meeting_id}`}>
                        {c.meeting_id} @ {fmtTs(c.ts)} - {c.speaker}: {c.text}
                      </Link>
                    ) : (
                      <span>{c.title} v{c.version}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      ))}
      <div className="flex gap-2">
        <Textarea rows={2} value={q} placeholder="Ask about meetings and documents..." onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() } }} />
        <Button disabled={ask.isPending || !q.trim()} onClick={send}>{ask.isPending ? "Thinking..." : "Ask"}</Button>
      </div>
    </div>
  )
}
