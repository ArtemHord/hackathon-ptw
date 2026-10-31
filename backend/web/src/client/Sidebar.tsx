// The sidebar (ios/ChatUI/SidebarView.swift): sections, recent calls with a live dot, Discuss and Settings.
import { NavLink, useNavigate } from "react-router-dom"
import { AudioLines, BookOpen, CalendarDays, Folder, ListChecks, PlayCircle, Plus, Search, Settings, SquarePen, Users } from "lucide-react"
import { Logo } from "@/components/brand"
import { displayTitle, isLive } from "@/lib/call-state"
import { useCalls } from "@/lib/live"
import { cn } from "@/lib/utils"
import { RoundButton, useShell } from "./shell"

const SECTIONS = [
  { to: "/calendar", label: "Calendar", icon: CalendarDays },
  { to: "/projects", label: "Projects", icon: Folder },
  { to: "/people", label: "People", icon: Users },
  { to: "/tasks", label: "Tasks", icon: ListChecks },
  { to: "/knowledge", label: "Knowledge", icon: BookOpen },
]

const row = ({ isActive }: { isActive: boolean }) =>
  cn("flex h-11 items-center gap-3 rounded-[14px] px-3 text-[16px] transition-colors hover:bg-sidebar-accent", isActive && "bg-sidebar-accent")

export function Sidebar() {
  const { rows, isLoading, isError } = useCalls()
  const { openNewCall, openSearch, openSettings } = useShell()
  const navigate = useNavigate()

  return (
    <div className="flex h-full flex-col bg-sidebar">
      <div className="flex h-16 shrink-0 items-center justify-between pr-4 pl-6">
        <NavLink to="/" aria-label="Call to Action, Discuss"><Logo className="h-[26px]" /></NavLink>
        <RoundButton label="Search calls (⌘K)" onClick={openSearch}><Search /></RoundButton>
      </div>

      <nav className="flex min-h-0 flex-1 flex-col overflow-y-auto px-3 pb-4">
        {SECTIONS.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={row}>
            <Icon className="size-[19px] shrink-0" />
            {label}
          </NavLink>
        ))}

        {isError && (
          <p className="mx-1 mt-3 flex items-center gap-2.5 rounded-[14px] bg-background px-3 py-2.5 text-[14px] font-medium">
            <span className="size-2 rounded-full bg-orange-500" />
            Offline <span className="font-normal text-muted-foreground">Retrying…</span>
          </p>
        )}

        <div className="mt-5 flex h-11 items-center justify-between pr-1 pl-3">
          <span className="text-[16px] font-semibold">Recents</span>
          <button type="button" onClick={openNewCall} aria-label="New call" title="New call"
            className="inline-flex size-9 items-center justify-center rounded-full hover:bg-sidebar-accent">
            <Plus className="size-[19px]" />
          </button>
        </div>

        {isLoading && <p className="px-3 py-2 text-[15px] text-muted-foreground">Loading calls…</p>}
        {!isLoading && rows.length === 0 && !isError && (
          <button type="button" onClick={openNewCall} className={row({ isActive: false })}>
            <PlayCircle className="size-[19px] shrink-0" /> Run a demo call
          </button>
        )}
        {/* Each item is a recorded call; live ones get a red dot */}
        {rows.map((c) => (
          <NavLink key={c.id} to={`/calls/${c.id}`} className={row}>
            <AudioLines className="size-[19px] shrink-0" />
            <span className="min-w-0 flex-1 truncate">{displayTitle(c)}</span>
            {isLive(c.status) && <span className="size-2 shrink-0 rounded-full bg-red-500" aria-label="Live" />}
          </NavLink>
        ))}
      </nav>

      <div className="flex shrink-0 items-center justify-between border-t border-sidebar-border/60 px-5 py-4">
        {/* One color and the new-chat icon, like ChatGPT's button */}
        <button type="button" onClick={() => navigate("/")}
          className="inline-flex h-11 items-center gap-2.5 rounded-full bg-brand px-5 text-[17px] font-semibold text-white transition-opacity hover:opacity-90">
          <SquarePen className="size-[18px]" strokeWidth={2.4} /> Discuss
        </button>
        <RoundButton label="Settings" onClick={openSettings} className="size-11"><Settings /></RoundButton>
      </div>
    </div>
  )
}
