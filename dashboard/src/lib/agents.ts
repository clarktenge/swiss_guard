// Static, presentation-only metadata for each agent: which room it lives in,
// its display name/description, and the character's colour palette + activity.
// The agent_id values MUST match what the Python agents write to Supabase.

export type RoomId =
  | 'kitchen'
  | 'office'
  | 'gym'
  | 'living'
  | 'nook'
  | 'bedroom'

export interface CharacterPalette {
  skin: string
  hair: string
  shirt: string
  pants: string
}

export interface AgentMeta {
  agentId: string
  name: string
  description: string
  room: RoomId
  /** Warm/cool ambient tint that bleeds into the room's corner. */
  ambient: string
  palette: CharacterPalette
}

export const AGENTS: AgentMeta[] = [
  {
    agentId: 'email-triage',
    name: 'Email Triage',
    description:
      'Scans the inbox each morning, ranks what is urgent, and files the noise. Decisions only — never echoes attacker-controlled text.',
    room: 'kitchen',
    ambient: '#f59e0b', // warm morning-coffee amber
    palette: { skin: '#e8b48c', hair: '#3a2a1a', shirt: '#d97706', pants: '#374151' },
  },
  {
    agentId: 'market-report',
    name: 'Market Report',
    description:
      'Pulls quotes for the portfolio, computes P&L in Python, and asks Claude only for the narrative around the numbers.',
    room: 'office',
    ambient: '#3b82f6', // cool monitor-glow blue
    palette: { skin: '#c98d63', hair: '#111827', shirt: '#2563eb', pants: '#1f2937' },
  },
  {
    agentId: 'health-sync',
    name: 'Health Sync',
    description:
      'Syncs Garmin activity and readiness, computes the trends, and writes a short daily check-in.',
    room: 'gym',
    ambient: '#22d3ee', // cool dawn light through the window
    palette: { skin: '#d9a679', hair: '#4b2e13', shirt: '#0891b2', pants: '#111827' },
  },
  {
    agentId: 'email-digest',
    name: 'Email Digest',
    description:
      'Rolls the day’s lower-priority mail into one readable digest so the inbox stays quiet.',
    room: 'living',
    ambient: '#f97316', // warm lamp-lit living room
    palette: { skin: '#b87a52', hair: '#6b4423', shirt: '#65a30d', pants: '#374151' },
  },
  {
    agentId: 'job-scout',
    name: 'Job Scout',
    description:
      'Crawls target company career sites, dedupes against seen_jobs, and pins genuinely new, relevant roles to the board.',
    room: 'nook',
    ambient: '#a855f7', // moody purple reading-nook glow
    palette: { skin: '#e8b48c', hair: '#1f2937', shirt: '#7c3aed', pants: '#111827' },
  },
  {
    agentId: 'weekly-report',
    name: 'Weekly Report',
    description:
      'Once a week, stitches the other agents’ outputs into a single reflection on how the week actually went.',
    room: 'bedroom',
    ambient: '#6366f1', // late-night indigo
    palette: { skin: '#c98d63', hair: '#2a1a0a', shirt: '#4f46e5', pants: '#1f2937' },
  },
]

export const AGENT_IDS = AGENTS.map((a) => a.agentId)

export const agentByRoom = (room: RoomId): AgentMeta =>
  AGENTS.find((a) => a.room === room)!

export const agentById = (id: string): AgentMeta | undefined =>
  AGENTS.find((a) => a.agentId === id)
