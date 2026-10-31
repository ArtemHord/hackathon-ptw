import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, type Expert } from "@/lib/api"

interface Form {
  name: string; role: string; topics: string; channel: "slack" | "telegram"
  email: string; slack_user_id: string; telegram_chat_id: string; is_owner: boolean
}
const EMPTY: Form = { name: "", role: "", topics: "", channel: "slack", email: "", slack_user_id: "", telegram_chat_id: "", is_owner: false }
const toForm = (e: Expert): Form => ({
  name: e.name, role: e.role ?? "", topics: e.topics.join(", "), channel: e.channel, email: e.email ?? "",
  slack_user_id: e.slack_user_id ?? "", telegram_chat_id: e.telegram_chat_id ?? "", is_owner: e.is_owner,
})
const nullable = (s: string) => (s.trim() ? s.trim() : null)

function ExpertDialog({ editing, onClose }: { editing: Expert | "new" | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState<Form>(EMPTY)
  const [seed, setSeed] = useState<typeof editing>(null)
  if (editing !== seed) { setSeed(editing); setF(editing && editing !== "new" ? toForm(editing) : EMPTY) }
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }))

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name.trim(), role: f.role.trim(), channel: f.channel, email: nullable(f.email),
        slack_user_id: nullable(f.slack_user_id), telegram_chat_id: nullable(f.telegram_chat_id), is_owner: f.is_owner,
        topics: f.topics.split(",").map((t) => t.trim()).filter(Boolean),
      }
      return editing && editing !== "new" ? api.updateExpert(editing.id, body) : api.createExpert(body)
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["experts"] }); onClose() },
  })

  const field = (label: string, k: keyof Form, placeholder = "") => (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      <Input value={f[k] as string} placeholder={placeholder} onChange={(e) => set(k, e.target.value as never)} />
    </div>
  )
  return (
    <Dialog open={!!editing} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{editing === "new" ? "Add expert" : "Edit expert"}</DialogTitle></DialogHeader>
        <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
          {field("Name", "name")}
          {field("Role", "role", "Backend lead")}
          {field("Topics (comma separated)", "topics", "api, auth, rate limits")}
          <div className="flex flex-col gap-1.5">
            <Label>Channel</Label>
            <select className="h-8 rounded-lg border bg-transparent px-2 text-sm" value={f.channel}
              onChange={(e) => set("channel", e.target.value as Form["channel"])}>
              <option value="slack">slack</option>
              <option value="telegram">telegram</option>
            </select>
          </div>
          {field("Email", "email")}
          {field("Slack user id", "slack_user_id", "U01234567")}
          {field("Telegram chat id", "telegram_chat_id")}
          <div className="flex items-center gap-2">
            <Checkbox id="own" checked={f.is_owner} onCheckedChange={(c) => set("is_owner", !!c)} />
            <Label htmlFor="own">This is the owner (the person the agent represents)</Label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!f.name.trim() || save.isPending} onClick={() => save.mutate()}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function Experts() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<Expert | "new" | null>(null)
  const { data } = useQuery({ queryKey: ["experts"], queryFn: api.experts })
  const integ = useQuery({ queryKey: ["integrations"], queryFn: api.integrations })
  const del = useMutation({
    mutationFn: (id: string) => api.deleteExpert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experts"] }),
  })
  const test = useMutation({
    mutationFn: (id: string) => api.testExpert(id),
    onSuccess: (r) => (r.ok ? toast.success(r.detail || "Test sent") : toast.error(r.detail || "Test failed")),
  })
  const bot = integ.data?.telegram.bot_username

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Experts</h1>
        <Button onClick={() => setEditing("new")}>Add expert</Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead><TableHead>Role</TableHead><TableHead>Topics</TableHead>
            <TableHead>Channel</TableHead><TableHead>Contact</TableHead><TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {data?.items.map((e) => (
            <TableRow key={e.id}>
              <TableCell className="font-medium">
                {e.name} {e.is_owner && <Badge variant="secondary">owner</Badge>}
              </TableCell>
              <TableCell>{e.role}</TableCell>
              <TableCell className="space-x-1">{e.topics.map((t) => <Badge key={t} variant="outline">{t}</Badge>)}</TableCell>
              <TableCell>{e.channel}</TableCell>
              <TableCell className="text-xs">
                {e.channel === "slack" ? (e.slack_user_id || e.email || "-") : (
                  <>
                    {e.telegram_chat_id || "not linked"}
                    {bot && (
                      <div>
                        <a className="underline" href={`https://t.me/${bot}?start=${e.id}`} target="_blank" rel="noreferrer">
                          {`https://t.me/${bot}?start=${e.id}`}
                        </a>
                      </div>
                    )}
                  </>
                )}
              </TableCell>
              <TableCell className="space-x-1 text-right">
                <Button size="sm" variant="outline" disabled={test.isPending} onClick={() => test.mutate(e.id)}>Send test</Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(e)}>Edit</Button>
                <Button size="sm" variant="destructive" onClick={() => confirm(`Delete ${e.name}?`) && del.mutate(e.id)}>Delete</Button>
              </TableCell>
            </TableRow>
          ))}
          {data?.items.length === 0 && <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground">No experts.</TableCell></TableRow>}
        </TableBody>
      </Table>
      <ExpertDialog editing={editing} onClose={() => setEditing(null)} />
    </div>
  )
}
