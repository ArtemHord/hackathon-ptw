// Knowledge: the documents the agent answers and fact-checks from, and the changes it proposes.
// The agent never edits a document on its own: a person approves or rejects each change.
import { useRef, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, FileText, Upload, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Empty, SectionPage } from "./shell"

export function KnowledgeContent({ callLink = (id: string) => `/calls/${id}` }: { callLink?: (id: string) => string }) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [tab, setTab] = useState<"review" | "docs">("review")
  const docs = useQuery({ queryKey: ["kb-docs"], queryFn: api.kbDocs })
  const proposals = useQuery({ queryKey: ["kb-proposals"], queryFn: api.proposals })
  const upload = useMutation({
    mutationFn: (f: File) => api.uploadDoc(f),
    onSuccess: (d) => {
      toast.success(`Added ${d.title} (v${d.version})`)
      void qc.invalidateQueries({ queryKey: ["kb-docs"] })
    },
  })
  const decide = useMutation({
    mutationFn: (v: { id: string; action: "approve" | "reject" }) => api.decide(v.id, v.action),
    onSuccess: (_r, v) => {
      toast.success(v.action === "approve" ? "Change applied: the document has a new version" : "Change rejected")
      void qc.invalidateQueries({ queryKey: ["kb-proposals"] })
      void qc.invalidateQueries({ queryKey: ["kb-docs"] })
    },
  })
  const items = proposals.data?.items ?? []
  const pending = items.filter((p) => p.status === "pending")
  const decided = items.filter((p) => p.status !== "pending")

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-2">
        {(["review", "docs"] as const).map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={cn("h-9 rounded-full px-4 text-[15px] font-medium transition-colors", tab === t ? "bg-foreground text-background" : "bg-bubble hover:bg-border")}>
            {t === "review" ? `Changes to review${pending.length ? ` · ${pending.length}` : ""}` : "Documents"}
          </button>
        ))}
        {tab === "docs" && (
          <>
            <input ref={fileRef} type="file" accept=".md,text/markdown" hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = "" }} />
            <Button className="ml-auto h-9 rounded-full px-4" disabled={upload.isPending} onClick={() => fileRef.current?.click()}>
              <Upload /> Add a .md file
            </Button>
          </>
        )}
      </div>

      {tab === "review" ? (
        <div className="flex flex-col gap-3">
          {!proposals.isLoading && items.length === 0 && (
            <Empty title="Nothing to review" text="When a fact-check finds a document out of date, the proposed fix waits here for you." />
          )}
          {[...pending, ...decided].map((p) => (
            <div key={p.id} className="flex flex-col gap-3 rounded-[20px] bg-surface p-4">
              <div className="flex flex-wrap items-center gap-2 text-[15px]">
                <FileText className="size-4 text-muted-foreground" />
                <span className="font-semibold">{p.doc_title}</span>
                {p.status !== "pending" && (
                  <span className={cn("rounded-full px-2 text-[12px] font-semibold leading-5", p.status === "approved" ? "bg-green-600/10 text-green-700" : "bg-foreground/8 text-muted-foreground")}>
                    {p.status === "approved" ? "Applied" : "Rejected"}
                  </span>
                )}
                {p.meeting_id && <Link to={callLink(p.meeting_id)} className="text-[14px] text-brand hover:underline">from a call{p.speaker ? ` · ${p.speaker}` : ""}</Link>}
              </div>
              {p.reason && <p className="text-[15px] text-muted-foreground">{p.reason}</p>}
              <div className="grid gap-2 md:grid-cols-2">
                <p className="rounded-xl bg-red-500/8 px-3 py-2 text-[14px] whitespace-pre-wrap"><span className="font-semibold text-red-700">Now: </span>{p.old_text}</p>
                <p className="rounded-xl bg-green-600/8 px-3 py-2 text-[14px] whitespace-pre-wrap"><span className="font-semibold text-green-700">Proposed: </span>{p.new_text}</p>
              </div>
              {p.status === "pending" && (
                <div className="flex gap-2">
                  <Button className="h-9 rounded-full px-4" disabled={decide.isPending} onClick={() => decide.mutate({ id: p.id, action: "approve" })}><Check /> Apply</Button>
                  <Button variant="outline" className="h-9 rounded-full px-4" disabled={decide.isPending} onClick={() => decide.mutate({ id: p.id, action: "reject" })}><X /> Reject</Button>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col">
          {!docs.isLoading && (docs.data?.items.length ?? 0) === 0 && <Empty title="No documents" text="Add the docs the agent should know: API limits, runbooks, decisions." />}
          {docs.data?.items.map((d) => (
            <div key={d.id} className="flex items-center gap-4 rounded-2xl px-3 py-3">
              <span className="flex size-10 items-center justify-center rounded-full bg-surface"><FileText className="size-5" /></span>
              <span className="flex flex-1 flex-col">
                <span className="text-[17px]">{d.title}</span>
                <span className="text-[14px] text-muted-foreground">
                  v{d.version} · {d.chunks} {d.chunks === 1 ? "part" : "parts"} · updated {new Date(d.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Knowledge() {
  return (
    <SectionPage title="Knowledge">
      <KnowledgeContent />
    </SectionPage>
  )
}
