// What this browser remembers: the accent color, tasks checked off, demo calls started here.
// The backend has no done flag on action items, so it stays on the device (as in the iOS app).
import { useSyncExternalStore } from "react"

export type Palette = "sunset" | "pink" | "red" | "violet" | "green"

export const PALETTES: { id: Palette; title: string; stops: string[] }[] = [
  { id: "sunset", title: "Sunset (brand)", stops: ["#E0255E", "#E8467A", "#F7764A", "#FFA35C"] },
  { id: "pink", title: "Pink", stops: ["#CF2F7D", "#F04E8C", "#FF7EA1"] },
  { id: "red", title: "Red", stops: ["#C81E3C", "#F23B3B", "#FF6A3D"] },
  { id: "violet", title: "Violet", stops: ["#6E46E5", "#9B5CF6", "#C86BFA"] },
  { id: "green", title: "Green", stops: ["#00A86B", "#1FCB7A", "#8BE36A"] },
]

interface Prefs {
  palette: Palette
  /** `<meeting id>/<action item id>`: item ids repeat across calls */
  doneTasks: string[]
  demoCalls: string[]
}

const KEY = "cta.prefs"
const DEFAULTS: Prefs = { palette: "sunset", doneTasks: [], demoCalls: [] }

function load(): Prefs {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Prefs>
    return { ...DEFAULTS, ...saved }
  } catch {
    return DEFAULTS
  }
}

let state = load()
const listeners = new Set<() => void>()

function update(patch: Partial<Prefs>) {
  state = { ...state, ...patch }
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    // private mode: keep it for this tab only
  }
  applyPalette()
  listeners.forEach((l) => l())
}

export function applyPalette() {
  const root = document.documentElement
  if (state.palette === "sunset") delete root.dataset.palette
  else root.dataset.palette = state.palette
}

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => listeners.delete(l)
}

export function usePrefs(): Prefs {
  return useSyncExternalStore(subscribe, () => state)
}

export const taskKey = (meetingId: string, itemId: string) => `${meetingId}/${itemId}`

export const prefs = {
  setPalette: (palette: Palette) => update({ palette }),
  toggleTask: (key: string) =>
    update({ doneTasks: state.doneTasks.includes(key) ? state.doneTasks.filter((k) => k !== key) : [...state.doneTasks, key] }),
  addDemoCall: (id: string) => update({ demoCalls: [...state.demoCalls.filter((x) => x !== id), id].slice(-50) }),
}
