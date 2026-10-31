import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "@/components/ui/sonner"
import { applyPalette } from "@/lib/prefs"
import App from "./App"
import "./index.css"

applyPalette()

const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter basename="/ui">
        <App />
      </BrowserRouter>
      <Toaster richColors theme="light" position="top-center" />
    </QueryClientProvider>
  </StrictMode>,
)
