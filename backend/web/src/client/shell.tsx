// Shared pieces of the client app's layout
import { createContext, useContext, type ReactNode } from "react"
import { Menu } from "lucide-react"
import { cn } from "@/lib/utils"

export interface Shell {
  openSidebar: () => void
  openNewCall: () => void
  openSearch: () => void
  openSettings: () => void
}

export const ShellContext = createContext<Shell>({
  openSidebar: () => {}, openNewCall: () => {}, openSearch: () => {}, openSettings: () => {},
})

export const useShell = () => useContext(ShellContext)

/** A round icon button with a soft border, like the glass buttons in the app */
export function RoundButton({ label, onClick, children, className, disabled }: {
  label: string; onClick?: () => void; children: ReactNode; className?: string; disabled?: boolean
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-border bg-background/80 text-foreground shadow-[0_1px_2px_rgb(22_18_19/0.06)] backdrop-blur transition-colors hover:bg-bubble disabled:opacity-40 [&_svg]:size-[18px]",
        className,
      )}
    >
      {children}
    </button>
  )
}

/** The bar over a screen: the sidebar button on small screens, actions on the right */
export function TopBar({ title, children }: { title?: string; children?: ReactNode }) {
  const { openSidebar } = useShell()
  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-3 bg-linear-to-b from-background via-background/90 to-background/0 px-4">
      <RoundButton label="Open sidebar" onClick={openSidebar} className="lg:hidden">
        <Menu />
      </RoundButton>
      {title && <span className="truncate text-[17px] font-semibold">{title}</span>}
      <div className="ml-auto flex items-center gap-2">{children}</div>
    </header>
  )
}

/** Calendar, People, Tasks…: a large Druk Wide title over the list, like the app's large titles */
export function SectionPage({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <TopBar>{actions}</TopBar>
      <div className="mx-auto w-full max-w-3xl px-5 pb-16">
        <h1 className="mb-6 font-display-title text-[30px] sm:text-[34px]">{title}</h1>
        {children}
      </div>
    </div>
  )
}

export function ListHeader({ children }: { children: ReactNode }) {
  return <p className="px-3 pt-5 pb-1 text-[15px] font-semibold text-muted-foreground">{children}</p>
}

export function Empty({ title, text, children }: { title: string; text: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-20 text-center">
      <p className="text-[19px] font-semibold">{title}</p>
      <p className="max-w-sm text-[15px] text-muted-foreground">{text}</p>
      {children}
    </div>
  )
}
