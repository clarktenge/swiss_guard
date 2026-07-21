import {
  Home,
  TrendingUp,
  HeartPulse,
  Briefcase,
  CalendarDays,
  Coins,
  type LucideIcon,
} from 'lucide-react'

export type ViewId = 'home' | 'finance' | 'health' | 'jobs' | 'weekly' | 'cost'

export interface NavItem {
  id: ViewId
  label: string
  icon: LucideIcon
  /** Placeholder copy for the not-yet-built data views. */
  blurb: string
}

export const NAV_ITEMS: NavItem[] = [
  {
    id: 'home',
    label: 'Apartment',
    icon: Home,
    blurb: 'The live view of all six agents at home.',
  },
  {
    id: 'finance',
    label: 'Finance',
    icon: TrendingUp,
    blurb:
      'Portfolio holdings, P&L over time, and the market-report narrative history — charted from the holdings table and market-report outputs.',
  },
  {
    id: 'health',
    label: 'Health',
    icon: HeartPulse,
    blurb:
      'Training load, readiness, and activity trends synced from Garmin by the health-sync agent.',
  },
  {
    id: 'jobs',
    label: 'Jobs',
    icon: Briefcase,
    blurb:
      'The pinned job board: new, relevant roles the job-scout agent surfaced, deduped against seen_jobs.',
  },
  {
    id: 'weekly',
    label: 'Weekly Reports',
    icon: CalendarDays,
    blurb:
      'The archive of weekly reflections stitched together from every agent’s output for the week.',
  },
  {
    id: 'cost',
    label: 'Cost Tracker',
    icon: Coins,
    blurb:
      'Claude token spend per agent and per run, aggregated from agent_runs — the dashboard version of scripts/cost_report.py.',
  },
]

export const navById = (id: ViewId): NavItem => NAV_ITEMS.find((n) => n.id === id)!
