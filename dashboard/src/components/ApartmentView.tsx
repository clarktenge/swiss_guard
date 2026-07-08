import { motion } from 'framer-motion'
import { Character } from './Character'
import { AGENTS, type AgentMeta, type RoomId } from '@/lib/agents'
import type { AgentStatus, CharacterStatus } from '@/lib/types'

interface Room {
  id: RoomId
  x: number
  y: number
  w: number
  h: number
  /** where the character stands, in apartment coords */
  cx: number
  cy: number
  activity: 'coffee' | 'phone' | 'paper' | 'book' | 'none'
  /** corner the ambient light bleeds from */
  light: { x: number; y: number }
}

// Floor plan, viewBox 0 0 900 720. Walls are drawn as gaps between room floors.
const ROOMS: Room[] = [
  { id: 'kitchen', x: 8, y: 8, w: 434, h: 224, cx: 150, cy: 168, activity: 'coffee', light: { x: 60, y: 40 } },
  { id: 'office', x: 458, y: 8, w: 434, h: 224, cx: 690, cy: 170, activity: 'none', light: { x: 690, y: 90 } },
  { id: 'gym', x: 8, y: 248, w: 224, h: 224, cx: 120, cy: 388, activity: 'phone', light: { x: 40, y: 320 } },
  { id: 'living', x: 248, y: 248, w: 404, h: 224, cx: 430, cy: 392, activity: 'paper', light: { x: 610, y: 300 } },
  { id: 'nook', x: 668, y: 248, w: 224, h: 224, cx: 762, cy: 388, activity: 'book', light: { x: 840, y: 320 } },
  { id: 'bedroom', x: 8, y: 488, w: 884, h: 224, cx: 470, cy: 610, activity: 'none', light: { x: 760, y: 560 } },
]

const roomAgent = (id: RoomId): AgentMeta => AGENTS.find((a) => a.room === id)!

function statusColor(s: CharacterStatus): string {
  switch (s) {
    case 'success':
      return '#22c55e'
    case 'running':
      return '#3b82f6'
    case 'idle':
      return '#f59e0b'
    case 'error':
      return '#ef4444'
    case 'sleeping':
    default:
      return '#6b7280'
  }
}

// ── Per-room furniture, drawn in absolute apartment coords ─────────────────────

function KitchenFurniture() {
  return (
    <g>
      {/* counter along the back wall */}
      <rect x="28" y="30" width="386" height="26" rx="4" fill="#2b2620" />
      <rect x="28" y="30" width="386" height="8" rx="4" fill="#3a332a" />
      {/* dining table */}
      <rect x="96" y="126" width="150" height="86" rx="10" fill="#3c2f26" />
      <rect x="104" y="134" width="134" height="70" rx="8" fill="#4a3a2e" />
      {/* coffee cup on the table */}
      <circle cx="140" cy="150" r="7" fill="#e5e7eb" />
      <circle cx="140" cy="150" r="4" fill="#6f4e37" />
      {/* stack of envelopes */}
      <g>
        <rect x="176" y="150" width="46" height="30" rx="2" fill="#e8e4da" transform="rotate(-8 199 165)" />
        <rect x="180" y="156" width="46" height="30" rx="2" fill="#f3efe6" transform="rotate(4 203 171)" />
        <rect x="184" y="150" width="46" height="30" rx="2" fill="#fbf8f1" />
        <path d="M184 150 L207 168 L230 150" fill="none" stroke="#c9bfa8" strokeWidth="1.5" />
      </g>
    </g>
  )
}

function OfficeFurniture() {
  return (
    <g>
      {/* desk */}
      <rect x="544" y="150" width="292" height="30" rx="4" fill="#241f2b" />
      <rect x="544" y="150" width="292" height="8" rx="4" fill="#322b3d" />
      {/* monitor */}
      <rect x="628" y="60" width="124" height="82" rx="6" fill="#0b1020" stroke="#3b455f" strokeWidth="2" />
      <rect x="636" y="68" width="108" height="66" rx="3" fill="#0f172a" />
      {/* chart on screen — rising line + bars */}
      <polyline
        points="642,124 660,112 676,118 692,96 710,104 728,78 740,84"
        fill="none"
        stroke="#22c55e"
        strokeWidth="2.5"
      />
      <g fill="#3b82f6" opacity="0.55">
        <rect x="644" y="118" width="6" height="10" />
        <rect x="662" y="110" width="6" height="18" />
        <rect x="680" y="114" width="6" height="14" />
        <rect x="698" y="100" width="6" height="28" />
        <rect x="716" y="108" width="6" height="20" />
      </g>
      <rect x="682" y="142" width="16" height="8" fill="#322b3d" />
    </g>
  )
}

function GymFurniture() {
  return (
    <g>
      {/* window with a cool dawn city view */}
      <rect x="22" y="276" width="46" height="120" rx="3" fill="#0a1420" stroke="#33405a" strokeWidth="2" />
      <rect x="26" y="280" width="38" height="112" rx="2" fill="url(#dawn)" />
      {/* skyline */}
      <g fill="#1c2b44" opacity="0.9">
        <rect x="28" y="352" width="8" height="40" />
        <rect x="38" y="338" width="7" height="54" />
        <rect x="47" y="360" width="9" height="32" />
        <rect x="57" y="344" width="6" height="48" />
      </g>
      <line x1="26" y1="336" x2="64" y2="336" stroke="#33405a" strokeWidth="1" />
      {/* yoga mat */}
      <rect x="78" y="366" width="118" height="40" rx="12" fill="#0e7490" />
      <rect x="86" y="374" width="102" height="24" rx="8" fill="#0891b2" opacity="0.6" />
      {/* phone by the mat */}
      <rect x="176" y="340" width="12" height="20" rx="2.5" fill="#0ea5e9" />
    </g>
  )
}

function LivingFurniture() {
  return (
    <g>
      {/* couch */}
      <rect x="300" y="336" width="230" height="70" rx="16" fill="#3a2f45" />
      <rect x="300" y="320" width="230" height="34" rx="14" fill="#473758" />
      <rect x="312" y="352" width="66" height="44" rx="10" fill="#54426a" />
      <rect x="384" y="352" width="66" height="44" rx="10" fill="#54426a" />
      <rect x="456" y="352" width="62" height="44" rx="10" fill="#54426a" />
      {/* newspaper on the seat */}
      <rect x="392" y="360" width="42" height="30" rx="1.5" fill="#e7e3d8" transform="rotate(-6 413 375)" />
      <g stroke="#9a927f" strokeWidth="1.4">
        <line x1="398" y1="366" x2="428" y2="362" />
        <line x1="399" y1="372" x2="429" y2="368" />
        <line x1="400" y1="378" x2="430" y2="374" />
      </g>
      {/* floor lamp casting the warm glow */}
      <rect x="600" y="300" width="6" height="96" rx="2" fill="#4b5563" />
      <path d="M588 300 L618 300 L610 278 L596 278 Z" fill="#fbbf24" opacity="0.9" />
      <circle cx="603" cy="292" r="20" fill="#fbbf24" opacity="0.12" />
    </g>
  )
}

function NookFurniture() {
  return (
    <g>
      {/* bookshelf on the right wall */}
      <rect x="846" y="276" width="36" height="150" rx="3" fill="#241c16" />
      {[280, 320, 360, 400].map((y) => (
        <line key={y} x1="848" y1={y} x2="880" y2={y} stroke="#3a2e22" strokeWidth="2" />
      ))}
      <g>
        {[
          ['#b45309', 282], ['#0e7490', 282], ['#7c3aed', 282],
          ['#be123c', 322], ['#15803d', 322], ['#a16207', 322],
          ['#1d4ed8', 362], ['#b91c1c', 362], ['#0f766e', 362],
        ].map(([c, y], i) => (
          <rect key={i} x={850 + (i % 3) * 10} y={(y as number)} width="8" height="36" fill={c as string} />
        ))}
      </g>
      {/* corkboard with pinned job postings */}
      <rect x="690" y="286" width="96" height="76" rx="4" fill="#a9805a" stroke="#7c5c3b" strokeWidth="3" />
      {[
        [700, 296, -5, '#fef9c3'],
        [736, 300, 4, '#e0f2fe'],
        [704, 330, 3, '#fae8ff'],
        [742, 332, -4, '#dcfce7'],
      ].map(([x, y, r, c], i) => (
        <g key={i} transform={`rotate(${r} ${(x as number) + 16} ${(y as number) + 11})`}>
          <rect x={x as number} y={y as number} width="32" height="22" rx="1.5" fill={c as string} />
          <circle cx={(x as number) + 16} cy={(y as number) + 2} r="2" fill="#ef4444" />
        </g>
      ))}
    </g>
  )
}

function BedroomFurniture() {
  return (
    <g>
      {/* bed */}
      <rect x="120" y="536" width="250" height="156" rx="12" fill="#2a2f3f" />
      <rect x="120" y="560" width="250" height="132" rx="10" fill="#3b4d6b" />
      {/* headboard */}
      <rect x="120" y="536" width="250" height="30" rx="12" fill="#4a3f56" />
      {/* pillow */}
      <rect x="136" y="548" width="88" height="34" rx="8" fill="#cbd5e1" />
      {/* blanket fold */}
      <rect x="120" y="628" width="250" height="30" rx="8" fill="#334155" />
      {/* nightstand + journal */}
      <rect x="388" y="600" width="60" height="60" rx="6" fill="#241f2b" />
      <rect x="398" y="612" width="40" height="28" rx="2" fill="#4f46e5" />
      <line x1="418" y1="612" x2="418" y2="640" stroke="#3730a3" strokeWidth="1.5" />
      {/* desk with lamp on the right */}
      <rect x="648" y="574" width="196" height="28" rx="4" fill="#241f2b" />
      <rect x="700" y="536" width="6" height="42" rx="2" fill="#4b5563" />
      <path d="M690 536 L716 536 L710 518 L696 518 Z" fill="#f59e0b" opacity="0.9" />
      <circle cx="703" cy="530" r="18" fill="#f59e0b" opacity="0.12" />
    </g>
  )
}

const FURNITURE: Record<RoomId, () => JSX.Element> = {
  kitchen: KitchenFurniture,
  office: OfficeFurniture,
  gym: GymFurniture,
  living: LivingFurniture,
  nook: NookFurniture,
  bedroom: BedroomFurniture,
}

interface ApartmentViewProps {
  statuses: Record<string, AgentStatus>
  selectedAgentId: string | null
  onSelectRoom: (agentId: string) => void
}

export function ApartmentView({ statuses, selectedAgentId, onSelectRoom }: ApartmentViewProps) {
  return (
    <svg viewBox="0 0 900 720" className="h-full w-full" role="img" aria-label="Agent apartment">
      <defs>
        {/* dawn gradient for the gym window */}
        <linearGradient id="dawn" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="#0b1220" />
          <stop offset="55%" stopColor="#1e3a5f" />
          <stop offset="100%" stopColor="#67c3e0" />
        </linearGradient>
        {/* per-room ambient light pools */}
        {ROOMS.map((r) => {
          const a = roomAgent(r.id)
          return (
            <radialGradient
              key={r.id}
              id={`amb-${r.id}`}
              cx={((r.light.x - r.x) / r.w) * 100 + '%'}
              cy={((r.light.y - r.y) / r.h) * 100 + '%'}
              r="85%"
            >
              <stop offset="0%" stopColor={a.ambient} stopOpacity="0.28" />
              <stop offset="55%" stopColor={a.ambient} stopOpacity="0.08" />
              <stop offset="100%" stopColor={a.ambient} stopOpacity="0" />
            </radialGradient>
          )
        })}
        {/* overall vignette */}
        <radialGradient id="vignette" cx="50%" cy="46%" r="72%">
          <stop offset="60%" stopColor="#000000" stopOpacity="0" />
          <stop offset="100%" stopColor="#000000" stopOpacity="0.45" />
        </radialGradient>
      </defs>

      {/* apartment outer shell */}
      <rect x="0" y="0" width="900" height="720" rx="18" fill="#0b0e15" />
      <rect x="2" y="2" width="896" height="716" rx="16" fill="none" stroke="#1e2736" strokeWidth="2" />

      {ROOMS.map((room) => {
        const agent = roomAgent(room.id)
        const st = statuses[agent.agentId]
        const cs: CharacterStatus = st?.characterStatus ?? 'sleeping'
        const selected = selectedAgentId === agent.agentId
        const Furniture = FURNITURE[room.id]
        const dot = statusColor(cs)

        return (
          <g key={room.id}>
            {/* floor */}
            <rect x={room.x} y={room.y} width={room.w} height={room.h} rx="10" fill="#12151d" />
            {/* wood/tile subtle inner panel */}
            <rect
              x={room.x + 4}
              y={room.y + 4}
              width={room.w - 8}
              height={room.h - 8}
              rx="8"
              fill="#141824"
            />
            {/* ambient light pool */}
            <rect
              x={room.x}
              y={room.y}
              width={room.w}
              height={room.h}
              rx="10"
              fill={`url(#amb-${room.id})`}
            />
            {/* room border */}
            <rect
              x={room.x}
              y={room.y}
              width={room.w}
              height={room.h}
              rx="10"
              fill="none"
              stroke="#1e2736"
              strokeWidth="2"
            />

            <Furniture />

            {/* the resident */}
            <g transform={`translate(${room.cx} ${room.cy}) scale(1.35)`}>
              <Character status={cs} animated palette={agent.palette} activity={room.activity} />
            </g>

            {/* status dot in the room corner */}
            <g transform={`translate(${room.x + room.w - 20} ${room.y + 18})`}>
              <circle r="6" fill={dot} />
              {cs === 'running' && (
                <motion.circle
                  r="6"
                  fill="none"
                  stroke={dot}
                  strokeWidth="1.5"
                  animate={{ r: [6, 11], opacity: [0.8, 0] }}
                  transition={{ duration: 1.4, repeat: Infinity, ease: 'easeOut' }}
                />
              )}
            </g>

            {/* selection highlight */}
            {selected && (
              <motion.rect
                x={room.x + 1}
                y={room.y + 1}
                width={room.w - 2}
                height={room.h - 2}
                rx="10"
                fill="none"
                stroke="#3b82f6"
                strokeWidth="3"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
              />
            )}

            {/* whole-room click target (on top so it always wins the click) */}
            <rect
              className="room-hit"
              x={room.x}
              y={room.y}
              width={room.w}
              height={room.h}
              rx="10"
              onClick={() => onSelectRoom(agent.agentId)}
            >
              <title>{agent.name}</title>
            </rect>
          </g>
        )
      })}

      <rect x="0" y="0" width="900" height="720" rx="18" fill="url(#vignette)" pointerEvents="none" />
    </svg>
  )
}
