import React from 'react'
import { count, money } from '../usage'

/**
 * The spend panel.
 *
 * Two figures, kept apart because they answer different questions: what this
 * thread has cost (comparable between prompts, resets when you start a new one)
 * and what the whole of testing has cost (the number that matters to a bill).
 *
 * Web searches are called out separately rather than folded into the total.
 * They are priced per request, not per token, so a cheap-looking answer can be
 * the expensive one -- and the first 5,000 a month are free, which the server
 * cannot know about and therefore never assumes.
 */
export default function Usage({ conversation, lifetime, budget, onReset }) {
  const since = lifetime.since
    ? new Date(lifetime.since).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
    : null

  // The server-enforced daily cap. Ratio drives both the bar width and the
  // colour: green with room, amber near the top, red once answering is paused.
  const capped = budget && budget.enabled
  const ratio = capped && budget.budget_usd > 0 ? budget.spent_usd / budget.budget_usd : 0
  const level = ratio >= 1 ? 'over' : ratio >= 0.8 ? 'near' : 'ok'

  return (
    <section className="usage">
      <h2 className="rail-heading">Spend</h2>

      {capped && (
        <div className={`usage-block budget-block budget-${level}`}>
          <p className="usage-label">Daily cap · resets 00:00 UTC</p>
          <div className="budget-bar" role="progressbar" aria-valuenow={Math.round(ratio * 100)}>
            <span style={{ width: `${Math.min(100, ratio * 100)}%` }} />
          </div>
          <p className="usage-detail">
            {money(budget.spent_usd)} of {money(budget.budget_usd)} ·{' '}
            {level === 'over' ? 'answering paused' : `${money(budget.remaining_usd)} left`}
          </p>
        </div>
      )}

      <div className="usage-block">
        <p className="usage-label">This conversation</p>
        <p className="usage-figure">{money(conversation.costUsd)}</p>
        <p className="usage-detail">
          {count(conversation.questions)} question{conversation.questions === 1 ? '' : 's'} ·{' '}
          {count(conversation.inputTokens)} in / {count(conversation.outputTokens)} out
        </p>
        {conversation.groundedRequests > 0 && (
          <p className="usage-detail usage-web">
            {count(conversation.groundedRequests)} web search
            {conversation.groundedRequests === 1 ? '' : 'es'} · {money(conversation.groundedRequests * 0.014)}
          </p>
        )}
      </div>

      <div className="usage-block">
        <p className="usage-label">All time{since ? ` · since ${since}` : ''}</p>
        <p className="usage-figure usage-figure-total">{money(lifetime.costUsd)}</p>
        <p className="usage-detail">
          {count(lifetime.questions)} question{lifetime.questions === 1 ? '' : 's'} ·{' '}
          {count(lifetime.inputTokens)} in / {count(lifetime.outputTokens)} out
        </p>
        {lifetime.groundedRequests > 0 && (
          <p className="usage-detail usage-web">
            {count(lifetime.groundedRequests)} web search
            {lifetime.groundedRequests === 1 ? '' : 'es'}
          </p>
        )}
      </div>

      <p className="usage-note">
        Estimated from list prices, not billed amounts. Web search is charged here at the
        full $14/1,000 rate; your first 5,000 a month are free, so the real figure is lower
        until you pass that.
      </p>

      {lifetime.questions > 0 && (
        <button type="button" className="usage-reset" onClick={onReset}>
          Reset all-time
        </button>
      )}
    </section>
  )
}
