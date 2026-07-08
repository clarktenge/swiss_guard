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
 * A tiny top-down pixel-art human, Stardew-Valley overhead style: you mostly see
 * hair, shoulders and a hint of face. Everything is drawn centered on (0,0) in a
 * ~28×40 unit box so the apartment can position it with a single translate().
 *
 * Posture and overlays encode the agent's last-run status:
 *   success  → standing, doing their thing, gentle bob
 *   running  → standing + soft pulsing ring
 *   error    → standing + red "!!" alert bubble
 *   idle     → sitting (shorter, calmer)
 *   sleeping → lying down, desaturated, Zzz
 */
export function Character({ status, animated, palette, activity = 'none' }: CharacterProps) {
  const sitting = status === 'idle'
  const lying = status === 'sleeping'
  const desaturated = status === 'sleeping'

  // Base figure, drawn upright. Posture transforms are applied by the wrapper.
  const figure = (
    <g>
      {/* soft ground shadow */}
      <ellipse cx="0" cy="19" rx="11" ry="4" fill="#000000" opacity="0.28" />

      {/* legs / pants */}
      <rect x="-7" y="6" width="6" height="12" rx="2.5" fill={palette.pants} />
      <rect x="1" y="6" width="6" height="12" rx="2.5" fill={palette.pants} />
      {/* shoes */}
      <rect x="-7" y="16" width="6" height="3.5" rx="1.5" fill="#111827" />
      <rect x="1" y="16" width="6" height="3.5" rx="1.5" fill="#111827" />

      {/* torso / shirt */}
      <rect x="-9" y="-4" width="18" height="16" rx="6" fill={palette.shirt} />

      {/* arms (shirt sleeves + skin hands) */}
      <rect x="-12" y="-3" width="4.5" height="12" rx="2.2" fill={palette.shirt} />
      <rect x="7.5" y="-3" width="4.5" height="12" rx="2.2" fill={palette.shirt} />
      <circle cx="-9.7" cy="9" r="2.3" fill={palette.skin} />
      <circle cx="9.7" cy="9" r="2.3" fill={palette.skin} />

      {/* head: hair covers the crown, a sliver of face shows toward the viewer */}
      <circle cx="0" cy="-9" r="8" fill={palette.hair} />
      <ellipse cx="0" cy="-6" rx="5" ry="4" fill={palette.skin} />
      {/* eyes — two little dots to give it a bit of personality */}
      <circle cx="-2" cy="-6" r="0.9" fill="#111827" />
      <circle cx="2" cy="-6" r="0.9" fill="#111827" />

      {/* activity accent held near the hands */}
      {activity === 'coffee' && (
        <>
          <rect x="8" y="7" width="5" height="4.5" rx="1" fill="#e5e7eb" />
          <rect x="8" y="6" width="5" height="1.4" rx="0.7" fill="#9ca3af" />
        </>
      )}
      {activity === 'phone' && (
        <rect x="-13.5" y="6.5" width="3.5" height="6" rx="1" fill="#0ea5e9" opacity="0.9" />
      )}
      {activity === 'paper' && (
        <rect x="-4" y="8" width="8" height="6" rx="0.6" fill="#f3f4f6" opacity="0.95" />
      )}
      {activity === 'book' && (
        <>
          <rect x="-5" y="8.5" width="10" height="6" rx="0.6" fill="#7c3aed" />
          <rect x="-0.4" y="8.5" width="0.8" height="6" fill="#4c1d95" />
        </>
      )}
    </g>
  )

  // Posture transform: sitting compresses & lowers, sleeping tips the whole
  // figure onto its side.
  const postureTransform = lying
    ? 'translate(0 6) rotate(-72)'
    : sitting
      ? 'translate(0 5) scale(1 0.86)'
      : 'translate(0 0)'

  const bob =
    animated && (status === 'success' || status === 'running')
      ? { y: [0, -2.2, 0] }
      : undefined

  return (
    <g style={desaturated ? { filter: 'grayscale(0.55)', opacity: 0.72 } : undefined}>
      {/* running: soft pulsing ring behind the figure */}
      {status === 'running' && (
        <motion.circle
          cx="0"
          cy="2"
          r="15"
          fill="none"
          stroke="#3b82f6"
          strokeWidth="2.5"
          initial={{ scale: 1, opacity: 0.6 }}
          animate={animated ? { scale: [1, 1.35, 1], opacity: [0.6, 0, 0.6] } : undefined}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
          style={{ transformOrigin: '0px 2px' }}
        />
      )}

      <motion.g
        transform={postureTransform}
        animate={bob}
        transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
      >
        {figure}
      </motion.g>

      {/* error: red "!!" alert bubble above the head */}
      {status === 'error' && (
        <g transform="translate(0 -24)">
          <circle cx="0" cy="0" r="7" fill="#ef4444" />
          <text
            x="0"
            y="3.5"
            textAnchor="middle"
            fontSize="9"
            fontWeight="700"
            fill="#ffffff"
            fontFamily="Inter, sans-serif"
          >
            !!
          </text>
        </g>
      )}

      {/* sleeping: drifting Zzz */}
      {status === 'sleeping' && (
        <g fill="#94a3b8" fontFamily="'JetBrains Mono', monospace">
          <motion.text
            x="12"
            y="-14"
            fontSize="7"
            animate={animated ? { y: [-14, -18, -14], opacity: [0.4, 1, 0.4] } : undefined}
            transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
          >
            z
          </motion.text>
          <motion.text
            x="17"
            y="-19"
            fontSize="9"
            animate={animated ? { y: [-19, -24, -19], opacity: [0.3, 0.9, 0.3] } : undefined}
            transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut', delay: 0.4 }}
          >
            Z
          </motion.text>
        </g>
      )}
    </g>
  )
}
