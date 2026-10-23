/**
 * `durable` tells the reader whether the spend figure is the day's or only
 * this process's. The server has sent it since milestone 21 item 15; the UI
 * ignored it and called the figure the day's either way.
 */
import { describe, expect, it } from 'vitest'
import { dayFigure } from './spend'
import type { Budget } from './types'

const budget = (over: Partial<Budget> = {}): Budget => ({
  enabled: true,
  budget_usd: 2,
  spent_usd: 0.43,
  remaining_usd: 1.57,
  resets_in_seconds: 23_400,
  durable: true,
  ...over,
})

describe('a figure nobody can date is not the day', () => {
  it('calls the figure the day when the ledger holds', () => {
    const f = dayFigure(budget())
    expect(f.trustworthy).toBe(true)
    expect(f.caption).toBe('resets 00:00 UTC')
    expect(f.remainingPrefix).toBe('')
    expect(f.note).toBeUndefined()
  })

  it('refuses to call it the day when the ledger does not hold', () => {
    const f = dayFigure(budget({ durable: false }))
    expect(f.trustworthy).toBe(false)
    expect(f.caption).not.toMatch(/resets/i)
    expect(f.note).toBeTruthy()
  })

  it('hedges the headroom too, because it comes off the same number', () => {
    // The bug this guards is a half-fix: caption hedged, "$1.57 left" printed
    // beside it as flat fact. `remaining_usd` is budget minus a spend figure
    // that is too low, so it is an upper bound and nothing else.
    expect(dayFigure(budget({ durable: false })).remainingPrefix).toBe('at most ')
  })

  it('does not accuse a payload that never mentioned durability', () => {
    // A server too old to send the field is unknown, not broken. Treating
    // unknown as broken puts a red warning on every healthy older box.
    const { durable: _d, ...without } = budget()
    const f = dayFigure(without as Budget)
    expect(f.trustworthy).toBe(true)
    expect(f.note).toBeUndefined()
  })
})
