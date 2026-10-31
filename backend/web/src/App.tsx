// Two versions of one web app behind one sign-in:
//   /ui/       the client-facing app (the iOS app's features and style)
//   /ui/test/  the testing environment (simulate, debug a call, agent, experts, integrations)
import { Suspense, lazy, useEffect, useState } from "react"
import { Route, Routes } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import ClientApp from "@/client/ClientApp"
import Login from "@/client/Login"
import { clearToken, getToken, setToken, setUnauthorizedHandler } from "@/lib/api"
import { chat } from "@/lib/chat"
import { speaker } from "@/lib/speech"

const TestApp = lazy(() => import("@/test/TestApp"))

export default function App() {
  const [authed, setAuthed] = useState(!!getToken())
  const qc = useQueryClient()

  const signOut = () => {
    speaker.stop()
    chat.clearAll()
    qc.clear()
    setAuthed(false)
  }

  useEffect(() => {
    setUnauthorizedHandler(signOut)
  })

  if (!authed) {
    return <Login onLogin={(t) => { setToken(t); setAuthed(true) }} />
  }

  const logout = () => {
    clearToken()
    signOut()
  }

  return (
    <Routes>
      <Route
        path="/test/*"
        element={
          <Suspense fallback={<p className="p-6 text-muted-foreground">Loading the testing tools…</p>}>
            <TestApp onLogout={logout} />
          </Suspense>
        }
      />
      <Route path="/*" element={<ClientApp onLogout={logout} />} />
    </Routes>
  )
}
