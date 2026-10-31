// The client-facing app at /ui: what the iOS app does, in the same style.
// The sidebar stays open on wide screens and slides in over the screen on narrow ones, as in ChatGPT.
import { useEffect, useMemo, useState } from "react"
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom"
import { toast } from "sonner"
import { setErrorPresenter } from "@/lib/api"
import { cn } from "@/lib/utils"
import CallScreen from "./CallScreen"
import { NewCallDialog, SearchDialog, SettingsDialog } from "./Dialogs"
import Discuss from "./Discuss"
import Knowledge from "./Knowledge"
import { Calendar, People, PersonCalls, ProjectCalls, Projects, Tasks } from "./Sections"
import { ShellContext, type Shell } from "./shell"
import { Sidebar } from "./Sidebar"

function OldMeetingLink() {
  const { id = "" } = useParams()
  return <Navigate to={`/calls/${id}`} replace />
}

export default function ClientApp({ onLogout }: { onLogout: () => void }) {
  const location = useLocation()
  const [drawerAt, setDrawerAt] = useState<string | null>(null)
  const drawer = drawerAt === location.pathname
  const setDrawer = (open: boolean) => setDrawerAt(open ? location.pathname : null)
  const [dialog, setDialog] = useState<"new" | "search" | "settings" | null>(null)

  // Plain words for errors here; the testing tools show the raw code
  useEffect(() => {
    setErrorPresenter((_code, message) => { toast.error(message) })
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setDialog("search")
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const path = location.pathname
  const shell = useMemo<Shell>(() => ({
    openSidebar: () => setDrawerAt(path),
    openNewCall: () => { setDrawerAt(null); setDialog("new") },
    openSearch: () => { setDrawerAt(null); setDialog("search") },
    openSettings: () => { setDrawerAt(null); setDialog("settings") },
  }), [path])
  const close = () => setDialog(null)

  return (
    <ShellContext.Provider value={shell}>
      <div className="flex h-dvh overflow-hidden bg-background">
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-40 w-[300px] border-r border-sidebar-border transition-transform duration-300 ease-out lg:static lg:z-auto lg:translate-x-0 lg:transition-none",
            drawer ? "translate-x-0 shadow-[10px_0_40px_rgb(0_0_0/0.18)]" : "-translate-x-full",
          )}
        >
          <Sidebar />
        </aside>
        {drawer && <button type="button" aria-label="Close sidebar" className="fixed inset-0 z-30 bg-background/70 lg:hidden" onClick={() => setDrawer(false)} />}

        <main className="flex min-w-0 flex-1 flex-col">
          <Routes>
            <Route index element={<Discuss />} />
            <Route path="calls/:id" element={<CallScreen />} />
            <Route path="calendar" element={<Calendar />} />
            <Route path="projects" element={<Projects />} />
            <Route path="projects/:platform" element={<ProjectCalls />} />
            <Route path="people" element={<People />} />
            <Route path="people/:name" element={<PersonCalls />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="knowledge" element={<Knowledge />} />
            {/* Links from before the split keep working */}
            <Route path="meetings/:id" element={<OldMeetingLink />} />
            <Route path="meetings" element={<Navigate to="/calendar" replace />} />
            <Route path="kb" element={<Navigate to="/knowledge" replace />} />
            <Route path="chat" element={<Navigate to="/" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>

      <NewCallDialog open={dialog === "new"} onClose={close} />
      <SearchDialog open={dialog === "search"} onClose={close} />
      <SettingsDialog open={dialog === "settings"} onClose={close} onLogout={onLogout} />
    </ShellContext.Provider>
  )
}
