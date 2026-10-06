import { RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { count, money, type Lifetime } from '@/lib/store'
import type { Budget } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

/**
 * Two figures kept apart on purpose: what this thread cost (comparable between
 * prompts) and what all of testing has cost (the number that matters to a
 * bill). Web searches are called out because they are priced per request.
 */
export function SpendCard({ conversation, lifetime, budget, onReset }: { conversation: Lifetime; lifetime: Lifetime; budget: Budget | null; onReset: () => void }) {
  const capped = !!budget?.enabled
  const dayRatio = capped && budget!.budget_usd > 0 ? budget!.spent_usd / budget!.budget_usd : 0
  // A per-user share, when the box has one, is the figure that actually stops
  // you -- and it stops you while the box-wide bar still shows money left.
  // Showing only the box's would make a refusal look like a bug.
  const share =
    capped && budget!.owner_budget_usd && budget!.owner_spent_usd !== undefined
      ? budget!
      : null
  const ratio = share ? Math.max(dayRatio, share.owner_spent_usd! / share.owner_budget_usd!) : dayRatio
  const left = share ? share.owner_remaining_usd! : budget?.remaining_usd ?? 0
  const level = ratio >= 1 ? 'over' : ratio >= 0.8 ? 'near' : 'ok'
  const since = lifetime.since ? new Date(lifetime.since).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : null

  return (
    <div className="flex flex-col gap-4">
      {capped && (
        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{share ? 'Your daily share' : 'Daily cap'}</span>
            <span className={cn('font-mono text-[11px] tabular', level === 'over' ? 'text-destructive' : level === 'near' ? 'text-warning' : 'text-muted-foreground')}>
              {level === 'over' ? 'answering paused' : `${money(left)} left`}
            </span>
          </div>
          <Progress
            value={Math.min(100, ratio * 100)}
            className={cn('h-1.5', level === 'over' && '[&>[data-slot=progress-indicator]]:bg-destructive', level === 'near' && '[&>[data-slot=progress-indicator]]:bg-warning', level === 'ok' && '[&>[data-slot=progress-indicator]]:bg-success')}
          />
          <p className="mt-1.5 font-mono text-[11px] text-muted-foreground tabular">
            {share
              ? `${money(share.owner_spent_usd!)} of ${money(share.owner_budget_usd!)} · box ${money(budget!.spent_usd)} of ${money(budget!.budget_usd)}`
              : `${money(budget!.spent_usd)} of ${money(budget!.budget_usd)}`} · resets 00:00 UTC
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Figure label="This thread" value={money(conversation.costUsd)} detail={`${count(conversation.questions)} q · ${count(conversation.inputTokens)} in / ${count(conversation.outputTokens)} out`} web={conversation.groundedRequests} />
        <Figure label={since ? `All time · ${since}` : 'All time'} value={money(lifetime.costUsd)} detail={`${count(lifetime.questions)} q · ${count(lifetime.inputTokens)} in / ${count(lifetime.outputTokens)} out`} web={lifetime.groundedRequests} />
      </div>

      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] leading-snug text-muted-foreground">
          Estimated from list prices. Web search charged at $14/1k; your first 5k a month are free.
        </p>
        {lifetime.questions > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-xs" onClick={onReset} aria-label="Reset all-time spend">
                <RotateCcw />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Reset all-time</TooltipContent>
          </Tooltip>
        )}
      </div>
    </div>
  )
}

function Figure({ label, value, detail, web }: { label: string; value: string; detail: string; web: number }) {
  return (
    <div className="rounded-lg bg-muted/60 px-2.5 py-2">
      <p className="text-[10.5px] font-medium tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className="mt-0.5 font-mono text-[15px] font-medium text-foreground tabular">{value}</p>
      <p className="mt-0.5 font-mono text-[10.5px] leading-snug text-muted-foreground tabular">{detail}</p>
      {web > 0 && <p className="mt-0.5 font-mono text-[10.5px] text-web tabular">{web} web search{web === 1 ? '' : 'es'}</p>}
    </div>
  )
}
