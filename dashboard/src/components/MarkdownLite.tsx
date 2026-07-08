import { Fragment, type ReactNode } from 'react'

/**
 * A deliberately tiny Markdown renderer for agent output. The agents emit clean,
 * predictable markdown (headers, bullets, bold, the odd table row) — not
 * arbitrary HTML — so parsing headers + bullets + inline bold into styled HTML
 * is enough, and avoids pulling in a full markdown dependency for Phase 1.
 */

// Inline **bold** and `code` within a single line.
function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let last = 0
  let m: RegExpExecArray | null
  let key = 0
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) nodes.push(<Fragment key={key++}>{text.slice(last, m.index)}</Fragment>)
    const tok = m[0]
    if (tok.startsWith('**')) {
      nodes.push(
        <strong key={key++} className="font-semibold text-gray-100">
          {tok.slice(2, -2)}
        </strong>,
      )
    } else {
      nodes.push(
        <code key={key++} className="rounded bg-[#0f1117] px-1 py-0.5 font-mono text-[12px] text-accent">
          {tok.slice(1, -1)}
        </code>,
      )
    }
    last = m.index + tok.length
  }
  if (last < text.length) nodes.push(<Fragment key={key++}>{text.slice(last)}</Fragment>)
  return nodes
}

export function MarkdownLite({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let bullets: string[] = []
  let key = 0

  const flushBullets = () => {
    if (bullets.length === 0) return
    blocks.push(
      <ul key={key++} className="my-2 space-y-1.5 pl-1">
        {bullets.map((b, i) => (
          <li key={i} className="flex gap-2 text-[13px] leading-relaxed text-gray-300">
            <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-accent" />
            <span>{renderInline(b)}</span>
          </li>
        ))}
      </ul>,
    )
    bullets = []
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    const trimmed = line.trim()

    if (trimmed === '') {
      flushBullets()
      continue
    }

    const bullet = /^[-*•]\s+(.*)$/.exec(trimmed)
    if (bullet) {
      bullets.push(bullet[1])
      continue
    }
    flushBullets()

    const header = /^(#{1,6})\s+(.*)$/.exec(trimmed)
    if (header) {
      const level = header[1].length
      const cls =
        level <= 1
          ? 'mt-4 mb-1.5 text-base font-semibold text-gray-100'
          : level === 2
            ? 'mt-3 mb-1 text-sm font-semibold text-gray-200'
            : 'mt-2.5 mb-1 text-[13px] font-semibold uppercase tracking-wide text-gray-400'
      blocks.push(
        <div key={key++} className={cls}>
          {renderInline(header[2])}
        </div>,
      )
      continue
    }

    // horizontal rule
    if (/^(-{3,}|_{3,}|\*{3,})$/.test(trimmed)) {
      blocks.push(<hr key={key++} className="my-3 border-border" />)
      continue
    }

    blocks.push(
      <p key={key++} className="my-1.5 text-[13px] leading-relaxed text-gray-300">
        {renderInline(trimmed)}
      </p>,
    )
  }
  flushBullets()

  return <div>{blocks}</div>
}
