/**
 * The card is where a person reads the day's spend against the cap this whole
 * project is built around. These assert the words on it, not the helper
 * behind it: a correct `dayFigure` that the card never calls would leave the
 * screen saying exactly what it said before.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SpendCard } from './spend-card'
import type { Budget } from '@/lib/types'
import type { Lifetime } from '@/lib/store'

const nothing: Lifetime = {
  questions: 0, inputTokens: 0, outputTokens: 0, groundedRequests: 0, costUsd: 0, since: null,
}

const budget = (over: Partial<Budget> = {}): Budget => ({
  enabled: true,
  budget_usd: 2,
  spent_usd: 0.43,
  remaining_usd: 1.57,
  resets_in_seconds: 23_400,
  durable: true,
  ...over,
})

const show = (b: Budget | null) =>
  render(<SpendCard conversation={nothing} lifetime={nothing} budget={b} onReset={() => {}} />)

describe('what the card calls the number', () => {
  it('calls it the day when the ledger holds', () => {
    show(budget())
    expect(screen.getByText(/resets 00:00 UTC/)).toBeTruthy()
    expect(screen.getByText(/\$1\.5700 left/)).toBeTruthy()
    expect(screen.queryByText(/at most/)).toBeNull()
  })

  it('stops calling it the day when the ledger does not hold', () => {
    show(budget({ durable: false }))
    expect(screen.queryByText(/resets 00:00 UTC/)).toBeNull()
    expect(screen.getByText(/since this server started/)).toBeTruthy()
  })

  it('hedges the headroom on the same screen as the caption', () => {
    show(budget({ durable: false }))
    expect(screen.getByText(/at most \$1\.5700 left/)).toBeTruthy()
  })

  it('says why the figure cannot be trusted, not only that it cannot', () => {
    show(budget({ durable: false }))
    expect(screen.getByText(/ledger cannot be read or written/i)).toBeTruthy()
  })

  it('renders nothing about a cap when the box has none', () => {
    show({ enabled: false } as Budget)
    expect(screen.queryByText(/resets 00:00 UTC/)).toBeNull()
    expect(screen.queryByText(/since this server started/)).toBeNull()
  })

  it('warns even while the share branch is the one on the bar', () => {
    // A per-owner share makes the bar track `owner_spent_usd`, which comes off
    // the same ledger. The first version of this fix hedged only the box-wide
    // branch.
    show(budget({ durable: false, share: 0.5, owner_budget_usd: 1, owner_spent_usd: 0.21, owner_remaining_usd: 0.79 }))
    expect(screen.getByText(/at most \$0\.7900 left/)).toBeTruthy()
    expect(screen.getByText(/since this server started/)).toBeTruthy()
  })
})
