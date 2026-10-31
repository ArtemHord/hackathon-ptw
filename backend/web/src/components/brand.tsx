// Call to Action brand pieces: the logo and the AI orb.
import { useEffect, useRef, useState, useSyncExternalStore } from "react"
import logoUrl from "@/assets/brand/cta-logo.svg"
import markUrl from "@/assets/brand/cta-mark.svg"
import type { OrbState } from "@/lib/live"
import { cn } from "@/lib/utils"

export function Logo({ className }: { className?: string }) {
  return <img src={logoUrl} alt="Call to Action" className={cn("h-7 w-auto select-none", className)} draggable={false} />
}

export function Mark({ className }: { className?: string }) {
  return <img src={markUrl} alt="" className={cn("h-6 w-auto select-none", className)} draggable={false} />
}

// The designer's SMIL animations (ios/Design/Animations): one loop per state, a 0.8 s clip between two states
const CLIPS = Object.fromEntries(
  Object.entries(import.meta.glob("@/assets/orb/*.svg", { eager: true, query: "?url", import: "default" }) as Record<string, string>).map(
    ([path, url]) => [path.split("/").pop()!.replace(/\.svg$/, ""), url],
  ),
)
const TRANSITION_MS = 800

// An <img> with a URL it already loaded shares that animation's clock, so a replay would start mid-way
// (or show a transition's last frame). Every play gets its own blob URL instead.
const blobs = new Map<string, Promise<Blob>>()
function clipBlob(name: string) {
  let blob = blobs.get(name)
  if (!blob) {
    blob = fetch(CLIPS[name]).then((r) => r.blob())
    blobs.set(name, blob)
  }
  return blob
}

const motionQuery = typeof window !== "undefined" ? window.matchMedia("(prefers-reduced-motion: reduce)") : null
function useReducedMotion() {
  return useSyncExternalStore(
    (l) => {
      motionQuery?.addEventListener("change", l)
      return () => motionQuery?.removeEventListener("change", l)
    },
    () => motionQuery?.matches ?? false,
  )
}

interface Layer { id: number; src: string; ready: boolean }
let layerIds = 0

/**
 * The orb follows what the assistant does: idle, listening, thinking, speaking.
 * `zoom` enlarges the artwork inside its box; the faint glow spills over the edges.
 */
export function Orb({ state, zoom = 1, className }: { state: OrbState; zoom?: number; className?: string }) {
  const reduced = useReducedMotion()
  const [layers, setLayers] = useState<Layer[]>([])
  const layersRef = useRef<Layer[]>([])
  useEffect(() => {
    layersRef.current = layers
  })
  const current = useRef<OrbState | null>(null)
  const play = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    if (reduced || current.current === state) return
    const from = current.current
    current.current = state
    clearTimeout(timer.current)
    const token = ++play.current

    const show = async (name: string) => {
      if (!CLIPS[name]) return
      const blob = await clipBlob(name)
      if (token !== play.current) return
      setLayers((ls) => [...ls, { id: ++layerIds, src: URL.createObjectURL(blob), ready: false }])
    }
    const transition = from ? `transition-${from}-to-${state}` : ""
    if (CLIPS[transition]) {
      void show(transition)
      timer.current = setTimeout(() => void show(`orb-${state}`), TRANSITION_MS)
    } else {
      void show(`orb-${state}`)
    }
  }, [state, reduced])

  useEffect(
    () => () => {
      clearTimeout(timer.current)
      layersRef.current.forEach((l) => URL.revokeObjectURL(l.src))
    },
    [],
  )

  // The new clip fades in over the old one, then the old one goes
  const ready = (id: number) => {
    setLayers((ls) => ls.map((l) => (l.id === id ? { ...l, ready: true } : l)))
    setTimeout(() => {
      setLayers((ls) => {
        const at = ls.findIndex((l) => l.id === id)
        if (at <= 0) return ls
        ls.slice(0, at).forEach((l) => URL.revokeObjectURL(l.src))
        return ls.slice(at)
      })
    }, 160)
  }

  return (
    <div className={cn("pointer-events-none relative orb-hue", className)} aria-hidden>
      {reduced ? (
        <img src={markUrl} alt="" className="absolute inset-0 m-auto h-1/2 w-auto" />
      ) : (
        layers.map((l) => (
          <img
            key={l.id}
            src={l.src}
            alt=""
            onLoad={() => ready(l.id)}
            className="absolute inset-0 size-full transition-opacity duration-150"
            style={{ opacity: l.ready ? 1 : 0, transform: `scale(${zoom})` }}
            draggable={false}
          />
        ))
      )}
    </div>
  )
}

export const orbCaption: Record<OrbState, string> = {
  idle: "Ready",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Answering…",
}
