// One sign-in for both versions: the backend's DEMO_TOKEN, checked with GET /meetings
import { useState } from "react"
import { Logo, Orb } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"

export default function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [token, setToken] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      if (await api.checkToken(token.trim())) onLogin(token.trim())
      else setError("Wrong token.")
    } catch {
      setError("The server is unreachable.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-background px-5 py-10">
      <div className="flex w-full max-w-sm flex-col items-center gap-6">
        <Orb state={busy ? "thinking" : "idle"} zoom={1.35} className="-my-8 size-[180px]" />
        <Logo className="h-9" />
        <form onSubmit={submit} className="flex w-full flex-col gap-3 rounded-[28px] bg-surface p-5">
          <label htmlFor="token" className="text-[15px] font-semibold">Sign in</label>
          <Input id="token" type="password" autoFocus value={token} onChange={(e) => setToken(e.target.value)}
            placeholder="Demo token" className="h-11 rounded-full bg-background px-4" autoComplete="current-password" />
          {error && <p className="px-1 text-[14px] text-red-600">{error}</p>}
          <Button type="submit" className="h-11 rounded-full text-[16px]" disabled={!token.trim() || busy}>
            {busy ? "Checking…" : "Continue"}
          </Button>
          <p className="px-1 text-[13px] text-muted-foreground">The DEMO_TOKEN of the Call Crew backend (Railway → Variables).</p>
        </form>
      </div>
    </div>
  )
}
