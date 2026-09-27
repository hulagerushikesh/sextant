import React from 'react'
import { cn } from '@/lib/utils'
import type { Source } from '@/lib/types'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

/**
 * Streamed answer renderer. No markdown library: `[3]` is a citation here and
 * a broken link to every markdown parser. Five constructs, one regex, survives
 * being fed half a sentence on every token.
 */

const BULLET = /^\s*[-*•]\s+/
const NUMBERED = /^\s*\d+[.)]\s+/
const HEADING = /^(#{1,4})\s+(.*)$/
// A GFM table: pipe-delimited rows, the second of which is the `|---|:--:|`
// rule. The rule is what makes it a table rather than prose that happens to
// contain a pipe, and while streaming it is also what has not arrived yet --
// so a lone header row renders as a paragraph until the rule follows it.
const TABLE_ROW = /^\s*\|.*\|\s*$/
const TABLE_RULE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[\d{1,3}(?:\s*,\s*\d{1,3})*\])/g
const LABEL = /^\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]$/

type Resolve = (n: number) => Source | undefined

export function Cite({ n, source, onCite, active }: { n: number; source?: Source; onCite: (n: number) => void; active?: boolean }) {
  if (!source) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="mx-0.5 inline-flex h-[1.15em] min-w-[1.4em] items-center justify-center rounded-[4px] border border-dashed border-destructive/60 px-1 align-[0.12em] font-mono text-[0.68em] font-medium text-destructive">
            {n}
          </span>
        </TooltipTrigger>
        <TooltipContent>No source carries label [{n}] — a dangling citation.</TooltipContent>
      </Tooltip>
    )
  }
  const web = source.origin === 'web'
  return (
    <button
      type="button"
      onClick={() => onCite(n)}
      title={source.title}
      data-origin={source.origin}
      className={cn(
        'mx-0.5 inline-flex h-[1.15em] min-w-[1.4em] cursor-pointer items-center justify-center rounded-[4px] border px-1 align-[0.12em] font-mono text-[0.68em] font-medium leading-none transition-[background-color,box-shadow,transform] duration-150 hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-ring/60',
        web
          ? 'border-web/40 bg-web-muted text-web hover:bg-web hover:text-web-foreground'
          : 'border-corpus/40 bg-corpus-muted text-corpus hover:bg-corpus hover:text-corpus-foreground',
        active && (web ? 'bg-web text-web-foreground' : 'bg-corpus text-corpus-foreground'),
      )}
    >
      {n}
    </button>
  )
}

function Inline({ text, resolve, onCite, active }: { text: string; resolve: Resolve; onCite: (n: number) => void; active?: number | null }) {
  return (
    <>
      {text.split(INLINE).map((part, i) => {
        if (!part) return null
        if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
        if (part.startsWith('`') && part.endsWith('`')) return <code key={i}>{part.slice(1, -1)}</code>
        const label = part.match(LABEL)
        if (!label) return <React.Fragment key={i}>{part}</React.Fragment>
        return label[1].split(',').map((raw, j) => {
          const n = Number(raw.trim())
          return <Cite key={`${i}-${j}`} n={n} source={resolve(n)} onCite={onCite} active={active === n} />
        })
      })}
    </>
  )
}

// Cells between the outer pipes; `\|` inside a cell stays a pipe.
const cells = (row: string): string[] =>
  row
    .trim()
    .replace(/^\||\|$/g, '')
    .split(/(?<!\\)\|/)
    .map((cell) => cell.replace(/\\\|/g, '|').trim())

const align = (rule: string): 'center' | 'right' | undefined => {
  const left = rule.startsWith(':')
  const right = rule.endsWith(':')
  if (left && right) return 'center'
  if (right) return 'right'
  return undefined
}

function Table({ lines, ...rest }: { lines: string[]; resolve: Resolve; onCite: (n: number) => void; active?: number | null }) {
  const head = cells(lines[0])
  const aligns = cells(lines[1]).map(align)
  const body = lines.slice(2).map(cells)
  return (
    // The wrapper scrolls, not the page: a wide table must never push the
    // whole answer column sideways.
    <div className="answer-table-wrap">
      <table className="answer-table">
        <thead>
          <tr>
            {head.map((cell, i) => (
              <th key={i} style={aligns[i] ? { textAlign: aligns[i] } : undefined}>
                <Inline text={cell} {...rest} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, r) => (
            <tr key={r}>
              {head.map((_, i) => (
                <td key={i} style={aligns[i] ? { textAlign: aligns[i] } : undefined}>
                  <Inline text={row[i] ?? ''} {...rest} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Block({ lines, ...rest }: { lines: string[]; resolve: Resolve; onCite: (n: number) => void; active?: number | null }) {
  if (lines.length >= 2 && TABLE_RULE.test(lines[1]) && lines.every((l) => TABLE_ROW.test(l) || TABLE_RULE.test(l))) {
    return <Table lines={lines} {...rest} />
  }

  const heading = lines.length === 1 && lines[0].match(HEADING)
  if (heading) {
    const Tag = `h${Math.min(heading[1].length + 2, 6)}` as 'h3' | 'h4' | 'h5' | 'h6'
    return <Tag><Inline text={heading[2]} {...rest} /></Tag>
  }
  if (lines.every((l) => BULLET.test(l)))
    return <ul>{lines.map((l, i) => <li key={i}><Inline text={l.replace(BULLET, '')} {...rest} /></li>)}</ul>
  if (lines.every((l) => NUMBERED.test(l)))
    return <ol>{lines.map((l, i) => <li key={i}><Inline text={l.replace(NUMBERED, '')} {...rest} /></li>)}</ol>
  return (
    <p>
      {lines.map((l, i) => (
        <React.Fragment key={i}>{i > 0 && <br />}<Inline text={l} {...rest} /></React.Fragment>
      ))}
    </p>
  )
}

export function Answer({ text, resolve, onCite, streaming, active }: { text: string; resolve: Resolve; onCite: (n: number) => void; streaming?: boolean; active?: number | null }) {
  const blocks = text
    .split(/\n\s*\n/)
    .map((b) => b.split('\n').filter((l) => l.trim()))
    .filter((b) => b.length)
  return (
    <div className={cn('prose-answer max-w-[68ch] text-foreground', streaming && 'caret')}>
      {blocks.map((lines, i) => <Block key={i} lines={lines} resolve={resolve} onCite={onCite} active={active} />)}
    </div>
  )
}
