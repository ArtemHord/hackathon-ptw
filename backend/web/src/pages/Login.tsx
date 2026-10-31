import { useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"

export default function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [token, setToken] = useState("")
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      if (await api.checkToken(token.trim())) onLogin(token.trim())
      else toast.error("Wrong token")
    } catch {
      toast.error("Backend unreachable")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Call Crew</CardTitle>
          <CardDescription>Enter the DEMO_TOKEN to continue.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="token">Token</Label>
              <Input id="token" type="password" autoFocus value={token} onChange={(e) => setToken(e.target.value)} />
            </div>
            <Button type="submit" disabled={!token || busy}>Sign in</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
