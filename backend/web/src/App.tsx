import { useEffect, useState } from "react"
import { NavLink, Navigate, Route, Routes } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, Bot, MessageSquare, Phone, Plug, Users } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api, clearToken, getToken, setToken, setUnauthorizedHandler } from "@/lib/api"
import { cn } from "@/lib/utils"
import Login from "@/pages/Login"
import Meetings from "@/pages/Meetings"
import Meeting from "@/pages/Meeting"
import Chat from "@/pages/Chat"
import Kb from "@/pages/Kb"
import Agent from "@/pages/Agent"
import Experts from "@/pages/Experts"
import Integrations from "@/pages/Integrations"

const NAV = [
  { to: "/meetings", label: "Meetings", icon: Phone },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/kb", label: "Knowledge base", icon: BookOpen },
  { to: "/agent", label: "Agent", icon: Bot },
  { to: "/experts", label: "Experts", icon: Users },
  { to: "/integrations", label: "Integrations", icon: Plug },
]

function HealthDot() {
  const { data } = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15000 })
  return (
    <span className="flex items-center gap-2 text-sm text-muted-foreground">
      <span className={cn("size-2.5 rounded-full", data === undefined ? "bg-muted" : data ? "bg-green-500" : "bg-red-500")} />
      {data === undefined ? "checking" : data ? "backend ok" : "backend down"}
    </span>
  )
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken())
  const qc = useQueryClient()

  useEffect(() => {
    setUnauthorizedHandler(() => { qc.clear(); setAuthed(false) })
  }, [qc])

  if (!authed) {
    return <Login onLogin={(t) => { setToken(t); setAuthed(true) }} />
  }

  const logout = () => { clearToken(); qc.clear(); setAuthed(false) }

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r bg-sidebar p-3">
        <div className="mb-4 px-2 text-lg font-semibold">Call Crew</div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn("flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-sidebar-accent",
                  isActive && "bg-sidebar-accent font-medium")
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end gap-4 border-b px-6 py-2">
          <HealthDot />
          <Button variant="outline" size="sm" onClick={logout}>Log out</Button>
        </header>
        <main className="flex-1 p-6">
          <Routes>
            <Route path="/" element={<Navigate to="/meetings" replace />} />
            <Route path="/meetings" element={<Meetings />} />
            <Route path="/meetings/:id" element={<Meeting />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/kb" element={<Kb />} />
            <Route path="/agent" element={<Agent />} />
            <Route path="/experts" element={<Experts />} />
            <Route path="/integrations" element={<Integrations />} />
            <Route path="*" element={<Navigate to="/meetings" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
