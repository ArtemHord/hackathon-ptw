import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, type TestResult } from "@/lib/api"

type Name = "slack" | "telegram" | "jira"

const CARDS: { name: Name; title: string; keys: string[]; hint: string }[] = [
  {
    name: "slack", title: "Slack", keys: ["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET"],
    hint: "Bot scopes: chat:write, im:write, im:history, users:read.email. Subscribe to the event message.im and set the Request URL below.",
  },
  {
    name: "telegram", title: "Telegram", keys: ["TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET"],
    hint: "Create a bot with @BotFather. Test also registers the webhook with Telegram (needs PUBLIC_BASE_URL).",
  },
  {
    name: "jira", title: "Jira", keys: ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"],
    hint: "Use an Atlassian API token (id.atlassian.com). Base URL looks like https://yourteam.atlassian.net.",
  },
]

function IntegrationCard({ c }: { c: (typeof CARDS)[number] }) {
  const qc = useQueryClient()
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings })
  const { data: integ } = useQuery({ queryKey: ["integrations"], queryFn: api.integrations })
  // edits: only keys the user touched; "" = clear
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [result, setResult] = useState<TestResult | null>(null)

  const save = useMutation({
    mutationFn: () => api.saveSettings(edits),
    onSuccess: (r) => {
      qc.setQueryData(["settings"], r)
      qc.invalidateQueries({ queryKey: ["integrations"] })
      setEdits({})
      toast.success(`${c.title} saved`)
    },
  })
  const test = useMutation({
    mutationFn: () => api.testIntegration(c.name),
    onSuccess: (r) => { setResult(r); qc.invalidateQueries({ queryKey: ["integrations"] }) },
  })

  const info = integ?.[c.name]
  const webhook = info && "webhook_url" in info ? info.webhook_url : null
  const dirty = Object.keys(edits).length > 0

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle>{c.title}</CardTitle>
          {info && <Badge variant={info.configured ? "default" : "secondary"}>{info.configured ? "configured" : "not configured"}</Badge>}
          {result && <Badge className={result.ok ? "bg-green-600 text-white" : "bg-red-600 text-white"}>{result.ok ? "ok" : "fail"}</Badge>}
        </div>
        <CardDescription>{c.hint}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {c.keys.map((k) => {
          const s = settings?.values[k]
          const touched = k in edits
          return (
            <div key={k} className="flex flex-col gap-1.5">
              <Label htmlFor={k}>{k}{s?.source === "env" && <span className="ml-2 text-xs text-muted-foreground">(from env)</span>}</Label>
              <div className="flex gap-2">
                <Input
                  id={k}
                  type={s?.secret ? "password" : "text"}
                  autoComplete="off"
                  placeholder={s?.secret ? (s.set ? (s.hint ?? "set") : "not set") : ""}
                  value={touched ? edits[k] : s?.secret ? "" : (s?.value ?? "")}
                  onChange={(e) => setEdits((x) => ({ ...x, [k]: e.target.value }))}
                />
                {s?.set && <Button variant="outline" onClick={() => setEdits((x) => ({ ...x, [k]: "" }))}>Clear</Button>}
              </div>
              {touched && edits[k] === "" && <span className="text-xs text-amber-600">Will be cleared on save</span>}
            </div>
          )
        })}
        {webhook && (
          <div className="flex flex-col gap-1.5">
            <Label>Webhook URL</Label>
            <div className="flex gap-2">
              <Input readOnly value={webhook} />
              <Button variant="outline" onClick={() => { navigator.clipboard.writeText(webhook); toast.success("Copied") }}>Copy</Button>
            </div>
          </div>
        )}
        {result && <p className="text-sm text-muted-foreground">{result.detail}{result.bot_username ? ` (@${result.bot_username})` : ""}</p>}
        <div className="flex gap-2">
          <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>Save</Button>
          <Button variant="outline" disabled={test.isPending || dirty} onClick={() => test.mutate()}>Test</Button>
        </div>
      </CardContent>
    </Card>
  )
}

export default function Integrations() {
  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">Integrations</h1>
      {CARDS.map((c) => <IntegrationCard key={c.name} c={c} />)}
    </div>
  )
}
