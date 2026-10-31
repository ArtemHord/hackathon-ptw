import { useRef } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api } from "@/lib/api"

export default function Kb() {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const docs = useQuery({ queryKey: ["kb-docs"], queryFn: api.kbDocs })
  const props = useQuery({ queryKey: ["kb-proposals"], queryFn: api.proposals })
  const upload = useMutation({
    mutationFn: (f: File) => api.uploadDoc(f),
    onSuccess: (d) => { toast.success(`Uploaded ${d.title} v${d.version}`); qc.invalidateQueries({ queryKey: ["kb-docs"] }) },
  })
  const decide = useMutation({
    mutationFn: (v: { id: string; action: "approve" | "reject" }) => api.decide(v.id, v.action),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["kb-proposals"] }); qc.invalidateQueries({ queryKey: ["kb-docs"] }) },
  })
  const pending = props.data?.items.filter((p) => p.status === "pending").length ?? 0

  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">Knowledge base</h1>
      <Tabs defaultValue="docs">
        <TabsList>
          <TabsTrigger value="docs">Documents</TabsTrigger>
          <TabsTrigger value="proposals">Proposals{pending ? ` (${pending})` : ""}</TabsTrigger>
        </TabsList>

        <TabsContent value="docs" className="flex flex-col gap-3 pt-3">
          <div>
            <input ref={fileRef} type="file" accept=".md,text/markdown" hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = "" }} />
            <Button disabled={upload.isPending} onClick={() => fileRef.current?.click()}>Upload .md</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Title</TableHead><TableHead>Version</TableHead><TableHead>Chunks</TableHead><TableHead>Updated</TableHead></TableRow></TableHeader>
            <TableBody>
              {docs.data?.items.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="font-medium">{d.title}</TableCell>
                  <TableCell>v{d.version}</TableCell>
                  <TableCell>{d.chunks}</TableCell>
                  <TableCell>{new Date(d.updated_at).toLocaleString()}</TableCell>
                </TableRow>
              ))}
              {docs.data?.items.length === 0 && <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground">No documents.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </TabsContent>

        <TabsContent value="proposals" className="flex flex-col gap-3 pt-3">
          {props.data?.items.length === 0 && <p className="text-sm text-muted-foreground">No proposals.</p>}
          {props.data?.items.map((p) => (
            <Card key={p.id}>
              <CardContent className="flex flex-col gap-2 py-4 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{p.doc_title}</span>
                  <Badge variant={p.status === "pending" ? "default" : "secondary"}>{p.status}</Badge>
                  {p.meeting_id && <Link className="text-xs underline" to={`/meetings/${p.meeting_id}`}>from meeting</Link>}
                </div>
                <div className="text-muted-foreground">{p.reason}</div>
                <div className="grid gap-2 md:grid-cols-2">
                  <pre className="whitespace-pre-wrap rounded bg-red-50 p-2 text-xs">- {p.old_text}</pre>
                  <pre className="whitespace-pre-wrap rounded bg-green-50 p-2 text-xs">+ {p.new_text}</pre>
                </div>
                {p.status === "pending" && (
                  <div className="flex gap-2">
                    <Button size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ id: p.id, action: "approve" })}>Approve</Button>
                    <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => decide.mutate({ id: p.id, action: "reject" })}>Reject</Button>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  )
}
