// The testing environment at /ui/test: setup and debug tools for the team, in the same style.
// Loaded only when opened, so the client app stays small.
import { useEffect } from "react"
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { ArrowUpRight, BookOpen, Bot, LogOut, MessageSquare, Phone, Plug, Users } from "lucide-react"
import { Logo } from "@/components/brand"
import { Button } from "@/components/ui/button"
import { KnowledgeContent } from "@/client/Knowledge"
import { api, setErrorPresenter } from "@/lib/api"
import { cn } from "@/lib/utils"
import Agent from "./Agent"
import CallDebug from "./CallDebug"
import Calls from "./Calls"
import Chat from "./Chat"
import Experts from "./Experts"
import Integrations from "./Integrations"

const NAV = [
  { to: "/test/calls", label: "Calls", icon: Phone },
  { to: "/test/chat", label: "Chat", icon: MessageSquare },
  { to: "/test/kb", label: "Knowledge base", icon: BookOpen },
  { to: "/test/agent", label: "Agent", icon: Bot },
  { to: "/test/experts", label: "Experts", icon: Users },
  { to: "/test/integrations", label: "Integrations", icon: Plug },
]

function HealthDot() {
  const { data } = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15000 })
  return (
    <span className="flex items-center gap-2 text-sm text-muted-foreground">
      <span className={cn("size-2.5 rounded-full", data === undefined ? "bg-muted-foreground/30" : data ? "bg-green-500" : "bg-red-500")} />
      {data === undefined ? "checking" : data ? "backend ok" : "backend down"}
    </span>
  )
}

function KbPage() {
  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">Knowledge base</h1>
      <KnowledgeContent callLink={(id) => `/test/calls/${id}`} />
    </div>
  )
}

const navItem = ({ isActive }: { isActive: boolean }) =>
  cn("flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-sidebar-accent", isActive && "bg-sidebar-accent font-semibold")

export default function TestApp({ onLogout }: { onLogout: () => void }) {
  // The raw error code helps when testing
  useEffect(() => {
    setErrorPresenter((code, message) => { toast.error(`${code}: ${message}`) })
  }, [])

  return (
    <div className="flex min-h-dvh">
      <aside className="hidden w-60 shrink-0 flex-col gap-1 border-r bg-sidebar p-3 md:flex">
        <div className="mb-4 flex flex-col gap-2 px-2 pt-2">
          <Logo className="h-6 self-start" />
          <span className="self-start rounded-full bg-amber-400/20 px-2 py-0.5 text-[11px] font-bold tracking-wider text-amber-700">TESTING</span>
        </div>
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={navItem}><Icon className="size-4" />{label}</NavLink>
        ))}
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b px-4 py-2 md:px-6">
          <span className="rounded-full bg-amber-400/20 px-2 py-0.5 text-[11px] font-bold tracking-wider text-amber-700 md:hidden">TESTING</span>
          <HealthDot />
          <div className="ml-auto flex items-center gap-2">
            <Link to="/" className="inline-flex h-8 items-center gap-1 rounded-lg px-2.5 text-sm font-medium text-brand hover:bg-muted">
              Open the app <ArrowUpRight className="size-4" />
            </Link>
            <Button variant="outline" size="sm" onClick={onLogout}><LogOut /> Log out</Button>
          </div>
          {/* Narrow screens: the sections scroll sideways under the bar */}
          <nav className="-mx-1 flex w-full gap-1 overflow-x-auto pb-1 md:hidden">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className={navItem}><Icon className="size-4" />{label}</NavLink>
            ))}
          </nav>
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Routes>
            <Route index element={<Navigate to="/test/calls" replace />} />
            <Route path="calls" element={<Calls />} />
            <Route path="calls/:id" element={<CallDebug />} />
            <Route path="chat" element={<Chat />} />
            <Route path="kb" element={<KbPage />} />
            <Route path="agent" element={<Agent />} />
            <Route path="experts" element={<Experts />} />
            <Route path="integrations" element={<Integrations />} />
            <Route path="*" element={<Navigate to="/test/calls" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
