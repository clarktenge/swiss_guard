import { motion } from 'framer-motion'
import type { CharacterPalette } from '@/lib/agents'
import type { CharacterStatus } from '@/lib/types'

interface CharacterProps {
  status: CharacterStatus
  animated: boolean
  palette: CharacterPalette
  /** Optional held item / activity accent, drawn near the hands. */
  activity?: 'coffee' | 'phone' | 'paper' | 'book' | 'none'
}

/**
 * A small pixel-art person in the Stardew-Valley key: front-facing, chunky, with
 * visible hair, clothing and a hint of a face. Drawn as an upright "billboard"
 * standing on an isometric floor — feet rest on (0,0), the body rises into
 * negative-y, and the apartment positions it with a single translate().
 *
 * Posture and overlays encode the agent's last-run status:
 *   success  → standing, doing their thing, gentle breathing bob
 *   running  → standing + a warm golden aura pulsing behind them
 *   error    → standing, glancing up at a red "!" alert
 *   idle     → sitting a little slumped, calmer
 *   sleeping → curled on the floor, desaturated, Zzz drifting up
 */
export function Character({ status, animated, palette, activity = 'none' }: CharacterProps) {
  const sitting = status === 'idle'
  const lying = status === 'sleeping'
  const desaturated = lying

  const skinShadow = shade(palette.skin, 0.82)
  const hairShadow = shade(palette.hair, 0.8)
  const shirtShadow = shade(palette.shirt, 0.82)

  // Upright figure, feet at y=0, head near y=-42. Posture transforms wrap it.
  const figure = (
    <g>
      {/* legs + shoes */}
      <rect x="-5.6" y="-13" width="4.8" height="13" rx="2.2" fill={palette.pants} />
      <rect x="0.8" y="-13" width="4.8" height="13" rx="2.2" fill={palette.pants} />
      <rect x="-5.6" y="-3.2" width="4.8" height="3.4" rx="1.4" fill="#2b2620" />
      <rect x="0.8" y="-3.2" width="4.8" height="3.4" rx="1.4" fill="#2b2620" />

      {/* arms (drawn behind torso so hands peek at the sides) */}
      <rect x="-11.2" y="-30" width="4.2" height="15" rx="2.1" fill={shirtShadow} />
      <rect x="7" y="-30" width="4.2" height="15" rx="2.1" fill={shirtShadow} />
      <circle cx="-9.1" cy="-15.5" r="2.4" fill={palette.skin} />
      <circle cx="9.1" cy="-15.5" r="2.4" fill={palette.skin} />

      {/* torso — a rounded smock, with a darker side for a bit of volume */}
      <rect x="-8.2" y="-31" width="16.4" height="20" rx="6" fill={palette.shirt} />
      <rect x="1.4" y="-31" width="6.8" height="20" rx="5" fill={shirtShadow} opacity="0.6" />

      {/* neck */}
      <rect x="-2.6" y="-34.5" width="5.2" height="4.5" rx="1.5" fill={skinShadow} />

      {/* head: hair crown behind, face circle in front, so hair frames the sides */}
      <circle cx="0" cy="-40" r="8" fill={palette.hair} />
      <ellipse cx="0.6" cy="-38" rx="6.6" ry="7.2" fill={palette.skin} />
      <path d="M-6.6 -42 Q0 -50 6.9 -42 Q4 -45 0 -45 Q-3.5 -45 -6.6 -42 Z" fill={hairShadow} />
      {/* eyes */}
      <circle cx="-2.4" cy="-38.2" r="0.95" fill="#2b2620" />
      <circle cx="3.2" cy="-38.2" r="0.95" fill="#2b2620" />

      <ActivityItem activity={activity} />
    </g>
  )

  // Posture transform: sitting settles + compresses the figure; sleeping tips it
  // onto its side near the floor.
  const postureTransform = lying
    ? 'translate(-3 -1) rotate(-74 0 -1)'
    : sitting
      ? 'translate(0 3) scale(1 0.9)'
      : 'translate(0 0)'

  const bob =
    animated && (status === 'success' || status === 'running')
      ? { y: [0, -2.4, 0] }
      : undefined

  return (
    <g>
      {/* soft ground shadow, drawn in world-up space so it stays flat */}
      <ellipse cx="0" cy="0.5" rx="11" ry="3.6" fill="#000000" opacity="0.32" />

      {/* running: a warm golden aura breathing behind the figure */}
      {status === 'running' && (
        <motion.ellipse
          cx="0"
          cy="-18"
          rx="18"
          ry="22"
          fill="url(#char-glow)"
          initial={{ opacity: 0.55, scale: 1 }}
          animate={animated ? { opacity: [0.4, 0.85, 0.4], scale: [1, 1.12, 1] } : undefined}
          transition={{ duration: 1.8, repeat: Infinity, ease: 'easeInOut' }}
          style={{ transformOrigin: '0px -18px' }}
        />
      )}

      <g style={desaturated ? { filter: 'grayscale(0.5)', opacity: 0.7 } : undefined}>
        <motion.g
          transform={postureTransform}
          animate={bob}
          transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
        >
          {figure}
        </motion.g>
      </g>

      {/* error: the character glances up at a red "!" alert bubble */}
      {status === 'error' && (
        <motion.g
          transform="translate(9 -52)"
          initial={{ y: 0, opacity: 0.85 }}
          animate={animated ? { y: [0, -2, 0], opacity: [0.85, 1, 0.85] } : undefined}
          transition={{ duration: 1.1, repeat: Infinity, ease: 'easeInOut' }}
        >
          <circle cx="0" cy="0" r="7.5" fill="#e0563b" stroke="#fff2e8" strokeWidth="1.4" />
          <text
            x="0"
            y="3.6"
            textAnchor="middle"
            fontSize="10"
            fontWeight="800"
            fill="#fff6ef"
            fontFamily="Inter, sans-serif"
          >
            !
          </text>
        </motion.g>
      )}

      {/* sleeping: drifting Zzz */}
      {status === 'sleeping' && (
        <g fill="#d8c9a8" fontFamily="'JetBrains Mono', monospace">
          <motion.text
            x="10"
            y="-16"
            fontSize="7"
            animate={animated ? { y: [-16, -21, -16], opacity: [0.35, 1, 0.35] } : undefined}
            transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut' }}
          >
            z
          </motion.text>
          <motion.text
            x="16"
            y="-22"
            fontSize="10"
            animate={animated ? { y: [-22, -28, -22], opacity: [0.3, 0.9, 0.3] } : undefined}
            transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut', delay: 0.5 }}
          >
            Z
          </motion.text>
        </g>
      )}
    </g>
  )
}

/** The little prop the resident is holding, tucked in near the hands. */
function ActivityItem({ activity }: { activity: CharacterProps['activity'] }) {
  switch (activity) {
    case 'coffee':
      return (
        <g>
          <rect x="6.6" y="-17" width="6" height="6.5" rx="1.2" fill="#f4efe3" />
          <path d="M12.6 -15.6 q3 0 3 2 t-3 2" fill="none" stroke="#cbb892" strokeWidth="1.2" />
          <ellipse cx="9.6" cy="-17" rx="2.6" ry="1" fill="#6f4e37" />
          <motion.path
            d="M8.4 -18 q-1 -2 0.4 -3.6"
            fill="none"
            stroke="#e9dcc2"
            strokeWidth="1"
            strokeLinecap="round"
            animate={{ opacity: [0.2, 0.7, 0.2] }}
            transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
          />
        </g>
      )
    case 'phone':
      return (
        <g>
          <rect x="-13.6" y="-18.5" width="4.2" height="7.5" rx="1.1" fill="#2b2620" />
          <rect x="-13" y="-18" width="3" height="6" rx="0.6" fill="#bfe3ff" />
        </g>
      )
    case 'paper':
      return (
        <g transform="rotate(-4 0 -18)">
          <rect x="-6.5" y="-21" width="13" height="10" rx="0.6" fill="#ece5d3" />
          <g stroke="#b3a988" strokeWidth="0.9">
            <line x1="-4.5" y1="-18.5" x2="4.5" y2="-18.5" />
            <line x1="-4.5" y1="-16.5" x2="4.5" y2="-16.5" />
            <line x1="-4.5" y1="-14.5" x2="2.5" y2="-14.5" />
          </g>
        </g>
      )
    case 'book':
      return (
        <g>
          <path d="M-6 -12 L0 -14 L0 -20.5 L-6 -18.5 Z" fill="#e9e2d0" />
          <path d="M6 -12 L0 -14 L0 -20.5 L6 -18.5 Z" fill="#f3ecda" />
          <path d="M-6 -12 L0 -14 L6 -12" fill="none" stroke="#8c6f45" strokeWidth="1.2" />
        </g>
      )
    default:
      return null
  }
}

/** Multiply an #rrggbb colour toward black by `f` (0..1). */
function shade(hex: string, f: number): string {
  const n = parseInt(hex.slice(1), 16)
  const r = Math.min(255, Math.round(((n >> 16) & 255) * f))
  const g = Math.min(255, Math.round(((n >> 8) & 255) * f))
  const b = Math.min(255, Math.round((n & 255) * f))
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`
}
