import { Construction, type LucideIcon } from 'lucide-react'

interface PlaceholderPageProps {
  title: string
  blurb: string
  icon: LucideIcon
}

/** "Coming soon" state for the data views that get real charts in Phase 2. */
export function PlaceholderPage({ title, blurb, icon: Icon }: PlaceholderPageProps) {
  return (
    <div className="flex h-full items-center justify-center p-10">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-5 grid h-16 w-16 place-items-center rounded-2xl border border-border bg-panel text-accent">
          <Icon size={30} />
        </div>
        <h1 className="text-2xl font-semibold text-gray-100">{title}</h1>
        <div className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-border bg-panel px-3 py-1 text-[11px] font-medium uppercase tracking-wider text-warn">
          <Construction size={13} /> Phase 2
        </div>
        <p className="mt-4 text-sm leading-relaxed text-gray-400">{blurb}</p>
      </div>
    </div>
  )
}
