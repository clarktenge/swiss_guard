import { motion } from 'framer-motion'
import { Character } from './Character'
import { AGENTS, type AgentMeta, type RoomId } from '@/lib/agents'
import type { AgentStatus, CharacterStatus } from '@/lib/types'

/*
 * A cozy isometric apartment, Stardew-Valley key. The whole home is one raised
 * floor split into six rooms, seen from slightly above at a 2:1 iso angle and
 * floating in the dark of a night-time building. Numbers below are in *plan*
 * units (u = toward front-right, v = toward front-left); `iso()` projects them
 * to screen. Everything is painted back-to-front so walls and furniture occlude
 * correctly.
 */

// ── Isometric projection ───────────────────────────────────────────────────────
const TW = 38 // tile half-width
const TH = 19 // tile half-height (2:1)
const OX = 360 // screen origin: the far (0,0) corner of the floor
const OY = 150

const sx = (u: number, v: number) => OX + (u - v) * TW
const sy = (u: number, v: number, h = 0) => OY + (u + v) * TH - h
/** Project a plan point (+ optional height above the floor) to an "x,y" string. */
const pt = (u: number, v: number, h = 0) => `${sx(u, v)},${sy(u, v, h)}`

/** Multiply an #rrggbb colour toward black by `f` (0..1). */
function shade(hex: string, f: number): string {
  const n = parseInt(hex.slice(1), 16)
  const r = Math.min(255, Math.round(((n >> 16) & 255) * f))
  const g = Math.min(255, Math.round(((n >> 8) & 255) * f))
  const b = Math.min(255, Math.round((n & 255) * f))
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`
}

/**
 * An isometric cuboid: footprint (u,v)→(u+wu,v+wv) raised to height `h`. Renders
 * the two viewer-facing side faces plus the top, shaded lightest-on-top. This is
 * the workhorse for tables, beds, walls, shelves — anything box-shaped.
 */
function IsoBox({
  u, v, wu, wv, h, color, opacity = 1,
}: {
  u: number; v: number; wu: number; wv: number; h: number; color: string; opacity?: number
}) {
  const top = `${pt(u, v, h)} ${pt(u + wu, v, h)} ${pt(u + wu, v + wv, h)} ${pt(u, v + wv, h)}`
  const right = `${pt(u + wu, v, h)} ${pt(u + wu, v + wv, h)} ${pt(u + wu, v + wv, 0)} ${pt(u + wu, v, 0)}`
  const left = `${pt(u, v + wv, h)} ${pt(u + wu, v + wv, h)} ${pt(u + wu, v + wv, 0)} ${pt(u, v + wv, 0)}`
  return (
    <g opacity={opacity}>
      <polygon points={left} fill={shade(color, 0.6)} />
      <polygon points={right} fill={shade(color, 0.8)} />
      <polygon points={top} fill={color} />
    </g>
  )
}

/** A flat diamond lying on the floor (rugs, mats, tile pools). */
function Tile({ u, v, wu, wv, fill, opacity = 1 }: { u: number; v: number; wu: number; wv: number; fill: string; opacity?: number }) {
  return <polygon points={`${pt(u, v)} ${pt(u + wu, v)} ${pt(u + wu, v + wv)} ${pt(u, v + wv)}`} fill={fill} opacity={opacity} />
}

// ── Room model ─────────────────────────────────────────────────────────────────
interface Room {
  id: RoomId
  u0: number; v0: number; u1: number; v1: number
  /** character's standing spot, plan coords */
  cu: number; cv: number
  activity: 'coffee' | 'phone' | 'paper' | 'book' | 'none'
  /** ambient light source, plan coords + tint */
  light: { u: number; v: number; color: string }
  floorA: string
  floorB: string
  pattern: 'checker' | 'planks'
  wall: string
}

// 3 columns (u: 0-4-8-12) × 2 rows (v: 0-4-8). Front-row & left-column rooms sit
// on the perimeter, so their back walls become the ones that carry windows.
const ROOMS: Room[] = [
  {
    id: 'kitchen', u0: 0, v0: 0, u1: 4, v1: 4, cu: 2.1, cv: 2.4, activity: 'coffee',
    light: { u: 1, v: 0.7, color: '#ffd27a' },
    floorA: '#e7d3a3', floorB: '#cdae74', pattern: 'checker', wall: '#efe3c2',
  },
  {
    id: 'living', u0: 4, v0: 0, u1: 8, v1: 4, cu: 6, cv: 2.5, activity: 'paper',
    light: { u: 7.2, v: 0.9, color: '#ffb765' },
    floorA: '#9c7548', floorB: '#8a663e', pattern: 'planks', wall: '#e3d3ac',
  },
  {
    id: 'gym', u0: 8, v0: 0, u1: 12, v1: 4, cu: 10, cv: 2.5, activity: 'phone',
    light: { u: 10, v: 0.6, color: '#8fbfe0' },
    floorA: '#baa478', floorB: '#a98f60', pattern: 'planks', wall: '#d8e0dd',
  },
  {
    id: 'bedroom', u0: 0, v0: 4, u1: 4, v1: 8, cu: 2.2, cv: 6.1, activity: 'none',
    light: { u: 0.9, v: 5.9, color: '#f4b96a' },
    floorA: '#8a6a44', floorB: '#79593a', pattern: 'planks', wall: '#c3b394',
  },
  {
    id: 'office', u0: 4, v0: 4, u1: 8, v1: 8, cu: 5.6, cv: 5.4, activity: 'none',
    light: { u: 6.1, v: 4.7, color: '#ffc25a' },
    floorA: '#6f5236', floorB: '#5f4630', pattern: 'planks', wall: '#3d342a',
  },
  {
    id: 'nook', u0: 8, v0: 4, u1: 12, v1: 8, cu: 10, cv: 5.8, activity: 'book',
    light: { u: 10.2, v: 4.8, color: '#ffce78' },
    floorA: '#7a5a38', floorB: '#6b4e30', pattern: 'planks', wall: '#c9b892',
  },
]

const roomAgent = (id: RoomId): AgentMeta => AGENTS.find((a) => a.room === id)!

function statusColor(s: CharacterStatus): string {
  switch (s) {
    case 'success': return '#7fbf7f'
    case 'running': return '#ffcf6b'
    case 'idle': return '#e0a35a'
    case 'error': return '#e0563b'
    case 'sleeping':
    default: return '#8a7c66'
  }
}

// ── Shared bits of room construction ────────────────────────────────────────────

/** Tile the room floor with 1×1 iso diamonds in an alternating pattern. */
function Floor({ room }: { room: Room }) {
  const tiles: JSX.Element[] = []
  for (let i = 0; i < room.u1 - room.u0; i++) {
    for (let j = 0; j < room.v1 - room.v0; j++) {
      const on = room.pattern === 'checker' ? (i + j) % 2 === 0 : i % 2 === 0
      tiles.push(
        <Tile key={`${i}-${j}`} u={room.u0 + i} v={room.v0 + j} wu={1} wv={1} fill={on ? room.floorA : room.floorB} />,
      )
    }
  }
  return <g>{tiles}</g>
}

/**
 * The two *far* walls of a room (its v0 and u0 edges). Perimeter edges get tall
 * outer walls; interior edges get low dividers with real thickness. Because rooms
 * paint back-to-front, drawing only far edges yields clean, single dividers.
 */
function Walls({ room }: { room: Room }) {
  const T = 0.22 // wall thickness, plan units
  const vOuter = room.v0 === 0
  const uOuter = room.u0 === 0
  const shadeSide = shade(room.wall, 0.9)
  return (
    <g>
      {/* wall along v0 (spans u) */}
      <IsoBox u={room.u0} v={room.v0} wu={room.u1 - room.u0} wv={T} h={vOuter ? 58 : 22} color={vOuter ? room.wall : shadeSide} />
      {/* wall along u0 (spans v) */}
      <IsoBox u={room.u0} v={room.v0} wu={T} wv={room.v1 - room.v0} h={uOuter ? 58 : 22} color={uOuter ? room.wall : shadeSide} />
    </g>
  )
}

/** A window set into the v0 (back) wall, with a graded sky and a light spill. */
function WindowV({ room, u1, u2, gradient, beam }: { room: Room; u1: number; u2: number; gradient: string; beam: string }) {
  const v = room.v0 + 0.02
  const frame = `${pt(u1 - 0.12, v, 14)} ${pt(u2 + 0.12, v, 14)} ${pt(u2 + 0.12, v, 46)} ${pt(u1 - 0.12, v, 46)}`
  const glass = `${pt(u1, v, 16)} ${pt(u2, v, 16)} ${pt(u2, v, 44)} ${pt(u1, v, 44)}`
  const mid = (u1 + u2) / 2
  return (
    <g>
      {/* light spilling onto the floor in front of the window */}
      <polygon
        points={`${pt(u1, room.v0)} ${pt(u2, room.v0)} ${pt(u2 + 0.5, room.v0 + 2.6)} ${pt(u1 - 0.5, room.v0 + 2.6)}`}
        fill={beam}
        opacity="0.5"
      />
      <polygon points={frame} fill="#5c4a34" />
      <polygon points={glass} fill={`url(#${gradient})`} />
      <line x1={sx(mid, v)} y1={sy(mid, v, 16)} x2={sx(mid, v)} y2={sy(mid, v, 44)} stroke="#5c4a34" strokeWidth="1.6" />
      <line x1={sx(u1, v)} y1={sy(u1, v, 30)} x2={sx(u2, v)} y2={sy(u2, v, 30)} stroke="#5c4a34" strokeWidth="1.4" />
    </g>
  )
}

/** A window set into the u0 (left) wall — used by the bedroom. */
function WindowU({ room, v1, v2, gradient, beam }: { room: Room; v1: number; v2: number; gradient: string; beam: string }) {
  const u = room.u0 + 0.02
  const frame = `${pt(u, v1 - 0.12, 14)} ${pt(u, v2 + 0.12, 14)} ${pt(u, v2 + 0.12, 46)} ${pt(u, v1 - 0.12, 46)}`
  const glass = `${pt(u, v1, 16)} ${pt(u, v2, 16)} ${pt(u, v2, 44)} ${pt(u, v1, 44)}`
  return (
    <g>
      <polygon
        points={`${pt(room.u0, v1)} ${pt(room.u0, v2)} ${pt(room.u0 + 2.6, v2 + 0.5)} ${pt(room.u0 + 2.6, v1 - 0.5)}`}
        fill={beam}
        opacity="0.45"
      />
      <polygon points={frame} fill="#5c4a34" />
      <polygon points={glass} fill={`url(#${gradient})`} />
      <line x1={sx(u, (v1 + v2) / 2)} y1={sy(u, (v1 + v2) / 2, 16)} x2={sx(u, (v1 + v2) / 2)} y2={sy(u, (v1 + v2) / 2, 44)} stroke="#5c4a34" strokeWidth="1.6" />
    </g>
  )
}

/**
 * A board mounted on the v0 wall (pinboard / corkboard) with pinned notes. Notes
 * are little quads laid on the wall plane at various heights.
 */
function WallBoard({ room, u1, u2, board, notes }: {
  room: Room; u1: number; u2: number; board: string
  notes: { u: number; h: number; w: number; hh: number; color: string }[]
}) {
  const v = room.v0 + 0.03
  const face = `${pt(u1, v, 16)} ${pt(u2, v, 16)} ${pt(u2, v, 44)} ${pt(u1, v, 44)}`
  return (
    <g>
      <polygon points={face} fill={board} stroke={shade(board, 0.75)} strokeWidth="2" />
      {notes.map((n, i) => (
        <g key={i}>
          <polygon
            points={`${pt(n.u, v, n.h)} ${pt(n.u + n.w, v, n.h)} ${pt(n.u + n.w, v, n.h + n.hh)} ${pt(n.u, v, n.h + n.hh)}`}
            fill={n.color}
          />
          <circle cx={sx(n.u + n.w / 2, v)} cy={sy(n.u + n.w / 2, v, n.h + n.hh - 1)} r="1.2" fill="#c0563b" />
        </g>
      ))}
    </g>
  )
}

// ── Per-room furniture ───────────────────────────────────────────────────────────

function KitchenFurniture({ room }: { room: Room }) {
  const { u0, v0 } = room
  return (
    <g>
      {/* morning window in the back wall + a plant on the sill */}
      <WindowV room={room} u1={u0 + 2.3} u2={u0 + 3.6} gradient="sky-morning" beam="#ffd98a" />
      <IsoBox u={u0 + 2.75} v={v0 + 0.05} wu={0.4} wv={0.35} h={16} color="#b9754a" />
      <path d={`M${pt(u0 + 2.95, v0 + 0.22, 16)} Q${sx(u0 + 2.7, v0 + 0.22)},${sy(u0 + 2.7, v0 + 0.22, 26)} ${pt(u0 + 3.05, v0 + 0.22, 24)}`} fill="none" stroke="#5f8a52" strokeWidth="2.2" />
      <path d={`M${pt(u0 + 2.95, v0 + 0.22, 16)} Q${sx(u0 + 3.3, v0 + 0.22)},${sy(u0 + 3.3, v0 + 0.22, 25)} ${pt(u0 + 2.85, v0 + 0.22, 23)}`} fill="none" stroke="#6f9e62" strokeWidth="2.2" />
      {/* counter along the back-left */}
      <IsoBox u={u0 + 0.35} v={v0 + 0.3} wu={1.5} wv={0.7} h={22} color="#8b6b45" />
      {/* dining table */}
      <IsoBox u={u0 + 1.3} v={v0 + 1.7} wu={1.5} wv={1.4} h={15} color="#a0785a" />
      {/* coffee mug + stacked letters on the table */}
      <IsoBox u={u0 + 1.55} v={v0 + 2.0} wu={0.32} wv={0.32} h={4} color="#efe7d6" />
      <Tile u={u0 + 2.05} v={v0 + 2.15} wu={0.7} wv={0.5} fill="#f3ecda" opacity={0.96} />
      <Tile u={u0 + 2.0} v={v0 + 2.05} wu={0.7} wv={0.5} fill="#e7ddc6" opacity={0.9} />
    </g>
  )
}

function LivingFurniture({ room }: { room: Room }) {
  const { u0, v0 } = room
  return (
    <g>
      {/* soft rug */}
      <Tile u={u0 + 0.9} v={v0 + 1.2} wu={2.4} wv={1.9} fill="#7a9e7e" opacity={0.55} />
      <Tile u={u0 + 1.2} v={v0 + 1.5} wu={1.8} wv={1.3} fill="#6b8f6f" opacity={0.5} />
      {/* couch against the back wall — base + backrest + arms */}
      <IsoBox u={u0 + 0.5} v={v0 + 0.5} wu={2.6} wv={0.9} h={16} color="#6b8cae" />
      <IsoBox u={u0 + 0.5} v={v0 + 0.5} wu={2.6} wv={0.35} h={30} color="#5f7d9c" />
      <IsoBox u={u0 + 0.5} v={v0 + 0.5} wu={0.35} wv={0.9} h={24} color="#54728f" />
      <IsoBox u={u0 + 2.75} v={v0 + 0.5} wu={0.35} wv={0.9} h={24} color="#54728f" />
      {/* coffee table with a newspaper + glasses */}
      <IsoBox u={u0 + 1.0} v={v0 + 1.75} wu={1.5} wv={1.0} h={11} color="#8a663e" />
      <Tile u={u0 + 1.25} v={v0 + 2.0} wu={0.9} wv={0.5} fill="#ece5d3" />
      <circle cx={sx(u0 + 2.1, v0 + 2.15)} cy={sy(u0 + 2.1, v0 + 2.15, 11)} r="2.2" fill="none" stroke="#2b2620" strokeWidth="1.2" />
      {/* floor lamp casting the warm glow */}
      <IsoBox u={u0 + 3.25} v={v0 + 0.55} wu={0.12} wv={0.12} h={40} color="#7a6a52" />
      <polygon
        points={`${pt(u0 + 3.05, v0 + 0.35, 40)} ${pt(u0 + 3.55, v0 + 0.85, 40)} ${pt(u0 + 3.4, v0 + 0.7, 52)} ${pt(u0 + 3.2, v0 + 0.5, 52)}`}
        fill="#ffd580"
      />
      {/* bookshelf, colourful spines */}
      <IsoBox u={u0 + 3.35} v={v0 + 1.6} wu={0.4} wv={1.6} h={44} color="#5f4630" />
    </g>
  )
}

function GymFurniture({ room }: { room: Room }) {
  const { u0, v0 } = room
  return (
    <g>
      {/* big dawn window across the back wall */}
      <WindowV room={room} u1={u0 + 0.5} u2={u0 + 3.5} gradient="sky-dawn" beam="#9cc6e6" />
      {/* exercise mat */}
      <Tile u={u0 + 1.1} v={v0 + 1.6} wu={2.0} wv={1.1} fill="#4f9d9d" opacity={0.9} />
      <Tile u={u0 + 1.3} v={v0 + 1.8} wu={1.6} wv={0.75} fill="#3f8686" opacity={0.7} />
      {/* phone on the mat, foam roller, water bottle */}
      <Tile u={u0 + 1.5} v={v0 + 2.0} wu={0.35} wv={0.55} fill="#7fd0f0" />
      <IsoBox u={u0 + 2.6} v={v0 + 1.75} wu={0.9} wv={0.32} h={7} color="#8a9fb0" />
      <IsoBox u={u0 + 0.6} v={v0 + 2.5} wu={0.28} wv={0.28} h={12} color="#3f8fb0" />
    </g>
  )
}

function BedroomFurniture({ room }: { room: Room }) {
  const { u0, v0 } = room
  return (
    <g>
      {/* evening window in the left wall */}
      <WindowU room={room} v1={v0 + 0.5} v2={v0 + 1.8} gradient="sky-evening" beam="#7c6f9e" />
      {/* bed: frame + mattress + headboard + pillow + folded blanket */}
      <IsoBox u={u0 + 0.6} v={v0 + 0.7} wu={2.9} wv={1.9} h={11} color="#5f4630" />
      <IsoBox u={u0 + 0.6} v={v0 + 0.7} wu={2.9} wv={1.9} h={16} color="#b6c2d6" />
      <IsoBox u={u0 + 0.6} v={v0 + 0.7} wu={0.35} wv={1.9} h={30} color="#7a5a3c" />
      <IsoBox u={u0 + 0.95} v={v0 + 0.85} wu={0.7} wv={1.5} h={20} color="#eef0f4" />
      <IsoBox u={u0 + 2.4} v={v0 + 0.7} wu={1.1} wv={1.9} h={19} color="#8899b8" />
      {/* scattered notes on the blanket */}
      <Tile u={u0 + 1.7} v={v0 + 1.6} wu={0.6} wv={0.45} fill="#f0e9d8" opacity={0.95} />
      <Tile u={u0 + 2.0} v={v0 + 1.2} wu={0.55} wv={0.4} fill="#e6dcc6" opacity={0.9} />
      {/* nightstand with journal + amber lamp */}
      <IsoBox u={u0 + 0.55} v={v0 + 2.9} wu={0.75} wv={0.75} h={18} color="#4f3a28" />
      <Tile u={u0 + 0.7} v={v0 + 3.05} wu={0.45} wv={0.35} fill="#7a5cc0" />
      <IsoBox u={u0 + 0.55} v={v0 + 2.9} wu={0.28} wv={0.28} h={30} color="#8a6a44" />
      <polygon
        points={`${pt(u0 + 0.5, v0 + 2.85, 30)} ${pt(u0 + 0.95, v0 + 3.3, 30)} ${pt(u0 + 0.82, v0 + 3.15, 40)} ${pt(u0 + 0.63, v0 + 2.98, 40)}`}
        fill="#f4b96a"
      />
    </g>
  )
}

function OfficeFurniture({ room }: { room: Room }) {
  const { u0, v0 } = room
  return (
    <g>
      {/* pinboard of stock tickers on the dark back wall */}
      <WallBoard
        room={room}
        u1={u0 + 2.2}
        u2={u0 + 3.6}
        board="#4a3d2e"
        notes={[
          { u: u0 + 2.35, h: 34, w: 0.34, hh: 6, color: '#dff0d8' },
          { u: u0 + 2.8, h: 33, w: 0.34, hh: 6, color: '#cfe6f5' },
          { u: u0 + 3.25, h: 35, w: 0.34, hh: 6, color: '#f5e6cf' },
          { u: u0 + 2.6, h: 24, w: 0.34, hh: 6, color: '#e8dff5' },
        ]}
      />
      {/* desk with monitor showing green chart lines + a warm desk lamp */}
      <IsoBox u={u0 + 0.5} v={v0 + 0.5} wu={2.6} wv={1.0} h={17} color="#6f5236" />
      {/* monitor */}
      <IsoBox u={u0 + 1.0} v={v0 + 0.6} wu={1.4} wv={0.12} h={44} color="#1b2432" />
      <MonitorChart room={room} u={u0 + 1.1} v={v0 + 0.62} />
      {/* desk lamp */}
      <IsoBox u={u0 + 2.55} v={v0 + 0.7} wu={0.1} wv={0.1} h={22} color="#5a4a34" />
      <polygon
        points={`${pt(u0 + 2.45, v0 + 0.55, 22)} ${pt(u0 + 2.8, v0 + 0.9, 22)} ${pt(u0 + 2.72, v0 + 0.82, 30)} ${pt(u0 + 2.53, v0 + 0.63, 30)}`}
        fill="#ffc25a"
      />
      {/* small finance bookshelf */}
      <IsoBox u={u0 + 0.5} v={v0 + 2.2} wu={0.4} wv={1.2} h={30} color="#4a3826" />
      {[0, 1, 2].map((i) => (
        <IsoBox key={i} u={u0 + 0.52} v={v0 + 2.3 + i * 0.35} wu={0.34} wv={0.28} h={22} color={['#8a3b3b', '#3b5f8a', '#7a6a3b'][i]} />
      ))}
    </g>
  )
}

/** The rising green line + faint blue bars on the office monitor, on its v-plane. */
function MonitorChart({ room, u, v }: { room: Room; u: number; v: number }) {
  void room
  const pts = [
    [u + 0.05, 20], [u + 0.25, 26], [u + 0.5, 24], [u + 0.75, 32], [u + 1.0, 30], [u + 1.25, 40],
  ]
  const line = pts.map(([uu, h]) => `${sx(uu, v)},${sy(uu, v, h)}`).join(' ')
  return (
    <g>
      <polygon points={`${pt(u, v, 18)} ${pt(u + 1.3, v, 18)} ${pt(u + 1.3, v, 42)} ${pt(u, v, 42)}`} fill="#0f1826" />
      <polyline points={line} fill="none" stroke="#6fcf7f" strokeWidth="2" strokeLinejoin="round" />
      {[0.15, 0.45, 0.75, 1.05].map((du, i) => (
        <polygon
          key={i}
          points={`${pt(u + du, v, 19)} ${pt(u + du + 0.12, v, 19)} ${pt(u + du + 0.12, v, 19 + [8, 12, 6, 15][i])} ${pt(u + du, v, 19 + [8, 12, 6, 15][i])}`}
          fill="#4a7fbf"
          opacity="0.5"
        />
      ))}
    </g>
  )
}

function NookFurniture({ room }: { room: Room }) {
  const { u0, v0 } = room
  return (
    <g>
      {/* corkboard of pinned job postings + string */}
      <WallBoard
        room={room}
        u1={u0 + 0.5}
        u2={u0 + 2.2}
        board="#b08a5a"
        notes={[
          { u: u0 + 0.65, h: 34, w: 0.36, hh: 6, color: '#fef3c3' },
          { u: u0 + 1.15, h: 35, w: 0.36, hh: 6, color: '#dff0fb' },
          { u: u0 + 1.7, h: 33, w: 0.36, hh: 6, color: '#f7e0fb' },
          { u: u0 + 0.9, h: 24, w: 0.36, hh: 6, color: '#dff5e2' },
          { u: u0 + 1.45, h: 24, w: 0.36, hh: 6, color: '#fde6d8' },
        ]}
      />
      {/* small desk with a laptop + focused desk lamp */}
      <IsoBox u={u0 + 0.6} v={v0 + 1.3} wu={2.2} wv={1.0} h={16} color="#6b4e30" />
      <IsoBox u={u0 + 1.1} v={v0 + 1.5} wu={0.9} wv={0.7} h={17} color="#2b3240" opacity={0.95} />
      <polygon points={`${pt(u0 + 1.1, v0 + 1.5, 17)} ${pt(u0 + 2.0, v0 + 1.5, 17)} ${pt(u0 + 2.0, v0 + 1.5, 27)} ${pt(u0 + 1.1, v0 + 1.5, 27)}`} fill="#3a4658" />
      {/* stacked books + folders */}
      <IsoBox u={u0 + 2.2} v={v0 + 1.45} wu={0.5} wv={0.5} h={7} color="#8a5a3b" />
      <IsoBox u={u0 + 2.25} v={v0 + 1.5} wu={0.42} wv={0.42} h={12} color="#3b6f5a" />
      {/* green plant in the corner */}
      <IsoBox u={u0 + 3.15} v={v0 + 2.5} wu={0.5} wv={0.5} h={12} color="#a4642f" />
      <ellipse cx={sx(u0 + 3.4, v0 + 2.75)} cy={sy(u0 + 3.4, v0 + 2.75, 24)} rx="12" ry="14" fill="#5f8a52" />
      <ellipse cx={sx(u0 + 3.4, v0 + 2.75)} cy={sy(u0 + 3.4, v0 + 2.75, 30)} rx="8" ry="10" fill="#6f9e62" />
    </g>
  )
}

const FURNITURE: Record<RoomId, (props: { room: Room }) => JSX.Element> = {
  kitchen: KitchenFurniture,
  living: LivingFurniture,
  gym: GymFurniture,
  bedroom: BedroomFurniture,
  office: OfficeFurniture,
  nook: NookFurniture,
}

// ── The view ─────────────────────────────────────────────────────────────────────
interface ApartmentViewProps {
  statuses: Record<string, AgentStatus>
  selectedAgentId: string | null
  onSelectRoom: (agentId: string) => void
}

export function ApartmentView({ statuses, selectedAgentId, onSelectRoom }: ApartmentViewProps) {
  // Paint back-to-front so nearer rooms and their walls occlude farther ones.
  const ordered = [...ROOMS].sort((a, b) => a.u0 + a.v0 - (b.u0 + b.v0) || a.u0 - b.u0)

  return (
    <svg viewBox="0 0 900 720" className="h-full w-full" role="img" aria-label="Agent apartment">
      <defs>
        <linearGradient id="sky-morning" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="#ffb347" />
          <stop offset="55%" stopColor="#ffd98a" />
          <stop offset="100%" stopColor="#fff2cf" />
        </linearGradient>
        <linearGradient id="sky-dawn" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="#243b57" />
          <stop offset="55%" stopColor="#5c86ab" />
          <stop offset="100%" stopColor="#a9d6ec" />
        </linearGradient>
        <linearGradient id="sky-evening" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="#1c2438" />
          <stop offset="60%" stopColor="#3a3a5f" />
          <stop offset="100%" stopColor="#6b6a8e" />
        </linearGradient>

        {/* warm golden aura behind a running character */}
        <radialGradient id="char-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ffe0a0" stopOpacity="0.9" />
          <stop offset="55%" stopColor="#ffbe57" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#ffbe57" stopOpacity="0" />
        </radialGradient>

        {/* per-room ambient light pools, centred on each light source */}
        {ROOMS.map((r) => (
          <radialGradient
            key={r.id}
            id={`light-${r.id}`}
            gradientUnits="userSpaceOnUse"
            cx={sx(r.light.u, r.light.v)}
            cy={sy(r.light.u, r.light.v, 26)}
            r="185"
          >
            <stop offset="0%" stopColor={r.light.color} stopOpacity="0.5" />
            <stop offset="45%" stopColor={r.light.color} stopOpacity="0.22" />
            <stop offset="100%" stopColor={r.light.color} stopOpacity="0" />
          </radialGradient>
        ))}

        {/* floating drop shadow under the whole apartment */}
        <radialGradient id="floor-shadow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#000000" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#000000" stopOpacity="0" />
        </radialGradient>

        {/* night vignette outside the apartment */}
        <radialGradient id="night" cx="50%" cy="42%" r="75%">
          <stop offset="55%" stopColor="#231a12" stopOpacity="0" />
          <stop offset="100%" stopColor="#0d0906" stopOpacity="0.85" />
        </radialGradient>
      </defs>

      {/* the dark building exterior at night */}
      <rect x="0" y="0" width="900" height="720" fill="#1a1410" />
      <rect x="0" y="0" width="900" height="720" fill="url(#night)" pointerEvents="none" />

      {/* soft shadow so the apartment reads as floating */}
      <ellipse cx="440" cy="560" rx="360" ry="90" fill="url(#floor-shadow)" />

      {ordered.map((room) => {
        const agent = roomAgent(room.id)
        const st = statuses[agent.agentId]
        const cs: CharacterStatus = st?.characterStatus ?? 'sleeping'
        const selected = selectedAgentId === agent.agentId
        const Furniture = FURNITURE[room.id]
        const dot = statusColor(cs)

        const floorPoly = `${pt(room.u0, room.v0)} ${pt(room.u1, room.v0)} ${pt(room.u1, room.v1)} ${pt(room.u0, room.v1)}`
        const cxs = sx(room.cu, room.cv)
        const cys = sy(room.cu, room.cv)

        return (
          <g key={room.id} className="iso-room">
            <Walls room={room} />
            <Floor room={room} />

            {/* ambient light pool tinting the floor */}
            <polygon points={floorPoly} fill={`url(#light-${room.id})`} pointerEvents="none" />

            <Furniture room={room} />

            {/* the resident */}
            <g transform={`translate(${cxs} ${cys}) scale(1.15)`}>
              <Character status={cs} animated palette={agent.palette} activity={room.activity} />
            </g>

            {/* status dot at the room's front corner */}
            <g transform={`translate(${sx(room.u1 - 0.35, room.v1 - 0.35)} ${sy(room.u1 - 0.35, room.v1 - 0.35)})`}>
              <circle r="5.5" fill={dot} stroke="#1a1410" strokeWidth="1.4" />
              {cs === 'running' && (
                <motion.circle
                  r="5.5"
                  fill="none"
                  stroke={dot}
                  strokeWidth="1.5"
                  animate={{ r: [5.5, 11], opacity: [0.85, 0] }}
                  transition={{ duration: 1.5, repeat: Infinity, ease: 'easeOut' }}
                />
              )}
            </g>

            {/* hover outline (CSS-driven) */}
            <polygon className="room-outline" points={floorPoly} fill="none" strokeWidth="2.5" pointerEvents="none" />

            {/* selection outline */}
            {selected && (
              <motion.polygon
                points={floorPoly}
                fill="none"
                stroke="#ffd580"
                strokeWidth="3"
                pointerEvents="none"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
              />
            )}

            {/* whole-room click target */}
            <polygon className="iso-hit" points={floorPoly} onClick={() => onSelectRoom(agent.agentId)}>
              <title>{agent.name}</title>
            </polygon>
          </g>
        )
      })}
    </svg>
  )
}
