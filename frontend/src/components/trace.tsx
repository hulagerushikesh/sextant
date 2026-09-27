import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ToolSummary, TraceStep } from '@/lib/types'
import { Badge } from '@/components/ui/badge'

/**
 * What the agent did, in order — each row a tool call with its outcome. An
 * empty search is styled as one, so "searched three times" reads as the agent
 * working rather than as a defect.
 */

const WHERE = {
  mcp: { label: 'MCP', title: 'Ran in the knowledge-base subprocess over stdio' },
  google: { label: 'Google', title: "Ran on Google's servers as a built-in tool" },
}

function describe(s?: ToolSummary): { text: string; tone: 'ok' | 'empty' | 'error' } | null {
  if (!s) return null
  if (s.status === 'error') return { text: s.error || 'failed', tone: 'error' }
  if (s.status === 'empty') return { text: 'nothing found', tone: 'empty' }
  if (typeof s.hits === 'number') {
    const p = `${s.hits} passage${s.hits === 1 ? '' : 's'}`
    return { text: s.top_score != null ? `${p} · top ${s.top_score.toFixed(2)}` : p, tone: 'ok' }
  }
  if (s.documents != null) return { text: `${s.documents} documents, ${s.chunks} chunks`, tone: 'ok' }
  return { text: 'done', tone: 'ok' }
}

export function Trace({ steps, running }: { steps: TraceStep[]; running: boolean }) {
  const [open, setOpen] = useState(running)
  if (!steps.length && !running) return null

  const searches = steps.filter((s) => s.name.endsWith('search')).length
  const summary = searches > 1 ? `${steps.length} steps · ${searches} searches` : `${steps.length} step${steps.length === 1 ? '' : 's'}`

  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="group inline-flex h-7 items-center gap-1.5 rounded-md pr-2 pl-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ChevronRight className={cn('size-3.5 transition-transform duration-200', open && 'rotate-90')} />
        {running ? (
          <span className="inline-flex items-center gap-2">
            <span className="relative flex size-1.5">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-corpus opacity-70" />
              <span className="relative inline-flex size-1.5 rounded-full bg-corpus" />
            </span>
            Working
          </span>
        ) : summary}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.ol
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
            className="ml-[9px] overflow-hidden border-l border-border pl-4"
          >
            {steps.map((step, i) => {
              const outcome = describe(step.summary)
              const where = WHERE[step.where] || WHERE.mcp
              const web = step.where === 'google'
              return (
                <motion.li
                  key={i}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.18, delay: i * 0.03 }}
                  className="relative flex flex-wrap items-center gap-x-2 gap-y-1 py-1.5 text-xs"
                >
                  <span className={cn('absolute top-[13px] -left-[21px] size-[7px] rounded-full ring-2 ring-background', web ? 'bg-web' : 'bg-corpus')} />
                  <Badge variant="outline" title={where.title} className={cn('h-5 rounded px-1.5 font-mono text-[10px] tracking-wide uppercase', web ? 'border-web/40 text-web' : 'border-corpus/40 text-corpus')}>
                    {where.label}
                  </Badge>
                  <code className="font-mono text-[11.5px] text-foreground">{step.name}</code>
                  {step.input?.query && <span className="truncate text-muted-foreground italic max-w-[36ch]">“{step.input.query}”</span>}
                  {outcome ? (
                    <span className={cn('font-mono text-[11px]', outcome.tone === 'ok' && 'text-success', outcome.tone === 'empty' && 'text-muted-foreground', outcome.tone === 'error' && 'text-destructive')}>
                      {outcome.text}
                    </span>
                  ) : (
                    <span className="font-mono text-[11px] text-muted-foreground animate-pulse">running…</span>
                  )}
                  {step.duration_ms != null && <span className="ml-auto font-mono text-[11px] text-muted-foreground tabular">{step.duration_ms} ms</span>}
                </motion.li>
              )
            })}
            {running && !steps.length && <li className="py-1.5 text-xs text-muted-foreground">Choosing a tool…</li>}
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  )
}
