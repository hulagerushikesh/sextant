import { AnimatePresence, motion } from 'motion/react'
import { ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Source } from '@/lib/types'

const host = (url: string) => { try { return new URL(url).hostname } catch { return url } }

/**
 * Conversation-scoped source list. Numbers persist across turns: [2] in the
 * fifth answer is the same passage [2] in the first. Selecting a chip in the
 * answer opens the matching card here, and vice-versa.
 */
export function SourceList({ sources, active, onSelect }: { sources: Source[]; active: number | null; onSelect: (n: number | null) => void }) {
  if (!sources.length) {
    return (
      <p className="px-1 text-[13px] leading-relaxed text-muted-foreground">
        Sources appear here as the agent retrieves them, numbered the way the answer cites them.
      </p>
    )
  }
  return (
    <ol className="flex flex-col gap-1">
      {sources.map((s) => {
        const web = s.origin === 'web'
        const isActive = active === s.n
        return (
          <li key={s.n} id={`source-${s.n}`}>
            <div
              className={cn(
                'rounded-lg border border-transparent transition-colors',
                isActive ? 'border-border bg-card shadow-xs' : 'hover:bg-muted/60',
              )}
            >
              <button
                type="button"
                onClick={() => onSelect(isActive ? null : s.n)}
                aria-expanded={isActive}
                className="flex w-full items-start gap-2.5 px-2.5 py-2 text-left"
              >
                <span
                  className={cn(
                    'mt-px inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-[5px] px-1 font-mono text-[11px] font-semibold',
                    web ? 'bg-web text-web-foreground' : 'bg-corpus text-corpus-foreground',
                  )}
                >
                  {s.n}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 text-[13px] leading-snug font-medium text-foreground">{s.title}</span>
                  <span className="mt-0.5 flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
                    <span className={cn('uppercase tracking-wider', web ? 'text-web' : 'text-corpus')}>{web ? 'web' : 'corpus'}</span>
                    {s.location && <><span>·</span><span>{s.location}</span></>}
                    {s.score != null && <><span>·</span><span title="Cross-encoder relevance, 0–1" className="tabular">{s.score.toFixed(2)}</span></>}
                  </span>
                </span>
              </button>

              <AnimatePresence initial={false}>
                {isActive && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="px-2.5 pb-2.5">
                      <div className={cn('rounded-md border-l-2 pl-3', web ? 'border-web' : 'border-corpus')}>
                        {s.text ? (
                          <p className="font-serif text-[14px] leading-relaxed text-foreground/90">{s.text}</p>
                        ) : (
                          <p className="text-[12.5px] leading-relaxed text-muted-foreground italic">
                            {web
                              ? 'Google returns the site and a link, not the passage the model read. Follow the link to see the page.'
                              : 'Retrieved in an earlier turn. Ask again to pull the passage back.'}
                          </p>
                        )}
                        {s.url && (
                          <a href={s.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[12px] text-web hover:underline">
                            {host(s.url)} <ExternalLink className="size-3" />
                          </a>
                        )}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
