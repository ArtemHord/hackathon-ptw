// A small Markdown renderer for summaries and answers (the same subset as the iOS app's Markdown.swift):
// headings, lists, quotes, code blocks (an unclosed fence while an answer streams is still code),
// **bold**, *italic*, `code` and links. Builds React elements: no innerHTML.
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "quote"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string }

function parse(source: string): Block[] {
  const blocks: Block[] = []
  const lines = source.replace(/\r\n/g, "\n").split("\n")
  let paragraph: string[] = []
  let quote: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null

  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", text: paragraph.join("\n") })
    if (quote.length) blocks.push({ kind: "quote", text: quote.join("\n") })
    if (list) blocks.push({ kind: "list", ...list })
    paragraph = []
    quote = []
    list = null
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    if (trimmed.startsWith("```")) {
      flush()
      const code: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++])
      blocks.push({ kind: "code", text: code.join("\n") })
      continue
    }
    if (!trimmed) {
      flush()
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed)
    if (heading) {
      flush()
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] })
      continue
    }
    const bullet = /^[-*•]\s+(.*)$/.exec(trimmed)
    const ordered = /^\d+[.)]\s+(.*)$/.exec(trimmed)
    if (bullet || ordered) {
      const isOrdered = !bullet
      if (paragraph.length || quote.length || (list && list.ordered !== isOrdered)) flush()
      list ??= { ordered: isOrdered, items: [] }
      list.items.push((bullet ?? ordered)![1])
      continue
    }
    if (trimmed.startsWith(">")) {
      if (paragraph.length || list) flush()
      quote.push(trimmed.replace(/^>\s?/, ""))
      continue
    }
    // A line right after a list item continues it
    if (list && list.items.length && /^\s+/.test(line)) {
      list.items[list.items.length - 1] += " " + trimmed
      continue
    }
    if (quote.length || list) flush()
    paragraph.push(trimmed)
  }
  flush()
  return blocks
}

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\s][^*]*\*)|(_[^_\s][^_]*_)|(\[[^\]]+\]\([^)\s]+\))/g

function safeLink(href: string, label: ReactNode, key: number) {
  if (href.startsWith("/")) return <Link key={key} to={href} className="font-medium text-brand underline-offset-4 hover:underline">{label}</Link>
  if (/^(https?:|mailto:)/i.test(href)) {
    return <a key={key} href={href} target="_blank" rel="noreferrer" className="font-medium text-brand underline-offset-4 hover:underline">{label}</a>
  }
  return <span key={key}>{label}</span>
}

export function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let key = 0
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0
    if (at > last) out.push(text.slice(last, at))
    const token = m[0]
    if (token.startsWith("`")) {
      out.push(<code key={key++} className="rounded-md bg-bubble px-1.5 py-0.5 font-mono text-[0.9em]">{token.slice(1, -1)}</code>)
    } else if (token.startsWith("**") || token.startsWith("__")) {
      out.push(<strong key={key++} className="font-semibold">{inline(token.slice(2, -2))}</strong>)
    } else if (token.startsWith("[")) {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token)
      out.push(link ? safeLink(link[2], inline(link[1]), key++) : token)
    } else {
      out.push(<em key={key++}>{inline(token.slice(1, -1))}</em>)
    }
    last = at + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  // Single line breaks inside a paragraph stay
  return out.flatMap((part, i) =>
    typeof part === "string" && part.includes("\n")
      ? part.split("\n").flatMap((piece, j) => (j === 0 ? [piece] : [<br key={`br-${i}-${j}`} />, piece]))
      : [part],
  )
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const blocks = parse(text)
  return (
    <div className={cn("flex flex-col gap-3 text-[16px] leading-relaxed", className)}>
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "heading":
            return (
              <p key={i} className={cn("font-bold", b.level === 1 ? "text-xl" : b.level === 2 ? "text-lg" : "text-base")}>
                {inline(b.text)}
              </p>
            )
          case "paragraph":
            return <p key={i}>{inline(b.text)}</p>
          case "quote":
            return <blockquote key={i} className="border-l-3 border-brand/50 pl-3 text-muted-foreground">{inline(b.text)}</blockquote>
          case "list":
            return b.ordered ? (
              <ol key={i} className="flex list-decimal flex-col gap-1.5 pl-6 marker:text-muted-foreground">
                {b.items.map((item, j) => <li key={j} className="pl-1">{inline(item)}</li>)}
              </ol>
            ) : (
              <ul key={i} className="flex list-disc flex-col gap-1.5 pl-6 marker:text-muted-foreground">
                {b.items.map((item, j) => <li key={j} className="pl-1">{inline(item)}</li>)}
              </ul>
            )
          case "code":
            return (
              <pre key={i} className="overflow-x-auto rounded-xl bg-bubble px-4 py-3 font-mono text-[13px] leading-normal">
                {b.text}
              </pre>
            )
        }
      })}
    </div>
  )
}
