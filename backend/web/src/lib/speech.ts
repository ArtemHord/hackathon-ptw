// Voice: answers read out in the server's ElevenLabs voice (POST /tts), questions asked by voice
// with the browser's speech recognition (Chrome, Edge, Safari; not Firefox).
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"
import { toast } from "sonner"
import { ApiError, api } from "@/lib/api"

// ---- playback ----

// A few samples of silence, played inside the click so Safari lets the real answer play after the request
const SILENCE = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAACAgICA"

let audio: HTMLAudioElement | null = null
let state = { loadingId: null as string | null, playingId: null as string | null }
const listeners = new Set<() => void>()
const set = (next: typeof state) => {
  state = next
  listeners.forEach((l) => l())
}
let currentUrl: string | null = null

/** Markdown markers and links aren't read out loud; /tts takes 1000 characters */
export function plainText(text: string) {
  return text
    .replace(/```[\s\S]*?(```|$)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`#>]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 1000)
}

export const speaker = {
  async speak(id: string, text: string) {
    speaker.stop()
    const spoken = plainText(text)
    if (!spoken) return
    audio ??= new Audio()
    const player = audio
    player.src = SILENCE
    player.play().catch(() => {})
    set({ loadingId: id, playingId: null })
    try {
      const blob = await api.tts(spoken, true)
      if (state.loadingId !== id) return
      currentUrl = URL.createObjectURL(blob)
      player.src = currentUrl
      player.onended = () => speaker.stop()
      await player.play()
      set({ loadingId: null, playingId: id })
    } catch (e) {
      if (state.loadingId !== id) return
      set({ loadingId: null, playingId: null })
      toast.error(e instanceof ApiError && e.status === 502 ? "The server has no voice set up (ElevenLabs)." : "Couldn't play the answer.")
    }
  },
  stop() {
    if (audio) {
      audio.onended = null
      audio.pause()
    }
    if (currentUrl) {
      URL.revokeObjectURL(currentUrl)
      currentUrl = null
    }
    if (state.loadingId || state.playingId) set({ loadingId: null, playingId: null })
  },
}

export function useSpeaker() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => state,
  )
}

// ---- voice input ----

interface RecognitionResult { isFinal: boolean; 0: { transcript: string } }
interface RecognitionEvent { resultIndex: number; results: ArrayLike<RecognitionResult> }
interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((e: RecognitionEvent) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}
type RecognitionCtor = new () => Recognition

const Recognizer: RecognitionCtor | undefined =
  typeof window === "undefined"
    ? undefined
    : ((window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: RecognitionCtor }).webkitSpeechRecognition)

/** Listens once; what was said goes to `onText` when you pause */
export function useVoiceInput() {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState("")
  const rec = useRef<Recognition | null>(null)

  useEffect(() => () => rec.current?.abort(), [])

  const start = useCallback((onText: (text: string) => void) => {
    if (!Recognizer || rec.current) return
    speaker.stop()
    const r = new Recognizer()
    r.lang = "en-US"
    r.interimResults = true
    r.continuous = false
    let final = ""
    r.onresult = (e) => {
      let partial = ""
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const piece = e.results[i]
        if (piece.isFinal) final += piece[0].transcript
        else partial += piece[0].transcript
      }
      setInterim(final + partial)
    }
    r.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") toast.error("Allow the microphone to ask by voice.")
      else if (e.error !== "no-speech" && e.error !== "aborted") toast.error("Couldn't recognize speech.")
    }
    r.onend = () => {
      rec.current = null
      setListening(false)
      setInterim("")
      const text = final.trim()
      if (text) onText(text)
    }
    rec.current = r
    setListening(true)
    r.start()
  }, [])

  const stop = useCallback(() => rec.current?.stop(), [])

  return { supported: !!Recognizer, listening, interim, start, stop }
}
