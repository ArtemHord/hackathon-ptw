import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { api, type Mode } from "@/lib/api"

function NewMeeting({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [url, setUrl] = useState("")
  const [mode, setMode] = useState<Mode>("delegate")
  const [brief, setBrief] = useState("")
  const [title, setTitle] = useState("")
  const create = useMutation({
    mutationFn: () =>
      api.createMeeting({
        meeting_url: url.trim(), mode, title: title.trim() || undefined,
        brief: mode === "delegate" && brief.trim() ? brief.trim() : undefined,
      }),
    onSuccess: (m) => { qc.invalidateQueries({ queryKey: ["meetings"] }); onClose(); nav(`/meetings/${m.id}`) },
  })
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>New meeting</DialogTitle></DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>Meeting URL</Label>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://meet.google.com/abc-defg-hij" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Title (optional)</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Mode</Label>
            <select className="h-8 rounded-lg border bg-transparent px-2 text-sm" value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
              <option value="delegate">delegate (answers for you)</option>
              <option value="notetaker">notetaker</option>
            </select>
          </div>
          {mode === "delegate" && (
            <div className="flex flex-col gap-1.5">
              <Label>Brief</Label>
              <Textarea rows={4} value={brief} onChange={(e) => setBrief(e.target.value)}
                placeholder="Done: SDK v2. Blocked: rate limit. Do not agree to deadlines." />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!url.trim() || create.isPending} onClick={() => create.mutate()}>Create</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function Meetings() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const { data, isLoading } = useQuery({ queryKey: ["meetings"], queryFn: api.meetings, refetchInterval: 5000 })
  const sim = useMutation({ mutationFn: api.simulate, onSuccess: (r) => nav(`/meetings/${r.meeting_id}`) })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Meetings</h1>
        <div className="flex gap-2">
          <Button variant="outline" disabled={sim.isPending} onClick={() => sim.mutate()}>Simulate call</Button>
          <Button onClick={() => setOpen(true)}>New meeting</Button>
        </div>
      </div>
      {isLoading ? <Skeleton className="h-40 w-full" /> : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead><TableHead>Platform</TableHead><TableHead>Mode</TableHead>
              <TableHead>Status</TableHead><TableHead>Started</TableHead><TableHead>Duration</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.map((m) => (
              <TableRow key={m.id}>
                <TableCell>
                  <Link className="font-medium underline-offset-4 hover:underline" to={`/meetings/${m.id}`}>{m.title || m.id}</Link>
                  {m.live && <Badge className="ml-2 bg-red-600 text-white">LIVE</Badge>}
                </TableCell>
                <TableCell>{m.platform}</TableCell>
                <TableCell><Badge variant="outline">{m.mode}</Badge></TableCell>
                <TableCell>{m.status}</TableCell>
                <TableCell>{new Date(m.started_at).toLocaleString()}</TableCell>
                <TableCell>{m.duration_min === null ? "-" : `${m.duration_min} min`}</TableCell>
              </TableRow>
            ))}
            {data?.items.length === 0 && (
              <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground">No meetings yet.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      )}
      <NewMeeting open={open} onClose={() => setOpen(false)} />
    </div>
  )
}
