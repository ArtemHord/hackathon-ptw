import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { api } from "@/lib/api"

const truthy = (v: string | null | undefined) => !!v && ["true", "1", "yes", "on"].includes(v.toLowerCase())

export default function Agent() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings })
  const [name, setName] = useState("")
  const [owner, setOwner] = useState("")
  const [auto, setAuto] = useState(false)

  useEffect(() => {
    if (!data) return
    setName(data.values.AGENT_NAME?.value ?? "")
    setOwner(data.values.OWNER_NAME?.value ?? "")
    setAuto(truthy(data.values.JIRA_AUTO_CREATE?.value))
  }, [data])

  const profile = data?.values.DEMO_PROFILE?.value || "acme"
  const saveProfile = useMutation({
    mutationFn: (value: string) => api.saveSettings({ DEMO_PROFILE: value }),
    onSuccess: (r) => {
      qc.setQueryData(["settings"], r)
      qc.invalidateQueries({ queryKey: ["experts"] })
      toast.success("Demo profile saved")
    },
  })

  const save = useMutation({
    mutationFn: () => api.saveSettings({ AGENT_NAME: name.trim(), OWNER_NAME: owner.trim(), JIRA_AUTO_CREATE: auto ? "true" : "" }),
    onSuccess: (r) => { qc.setQueryData(["settings"], r); toast.success("Saved") },
  })

  return (
    <div className="flex max-w-xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">Agent</h1>
      <Card>
        <CardHeader>
          <CardTitle>Identity</CardTitle>
          <CardDescription>The wake word is the agent name: say "{name || "Atlas"}, ..." in a call.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="an">Agent name</Label>
            <Input id="an" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="on">Owner name</Label>
            <Input id="on" value={owner} onChange={(e) => setOwner(e.target.value)} />
          </div>
          <div className="flex items-center gap-3">
            <Switch checked={auto} onCheckedChange={setAuto} id="ja" />
            <Label htmlFor="ja">Create Jira issues for action items automatically after a call</Label>
          </div>
          <div><Button disabled={save.isPending || !data} onClick={() => save.mutate()}>Save</Button></div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Demo profile</CardTitle>
          <CardDescription>
            Which demo the agent runs: its documents, experts, tools and the "Simulate call" script.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-1.5">
          <Label htmlFor="dp">Profile</Label>
          <select id="dp" className="h-8 rounded-lg border bg-transparent px-2 text-sm" value={profile}
            disabled={saveProfile.isPending || !data} onChange={(e) => saveProfile.mutate(e.target.value)}>
            <option value="acme">Acme (stand-up demo)</option>
            <option value="msp">MSP incident response (NovaStore INC-024)</option>
          </select>
        </CardContent>
      </Card>
    </div>
  )
}
