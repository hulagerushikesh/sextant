/**
 * What testing has cost so far.
 *
 * Three different questions, and they want three different answers:
 *
 *   per question      already on every answer, from the `done` frame
 *   per conversation  summed from that conversation's turns, here
 *   all time          a counter that only ever goes up, here
 *
 * The last one deliberately does NOT sum the saved conversations. Storage keeps
 * thirty and evicts the rest, and deleting a thread is a housekeeping action --
 * neither refunds the tokens. A running total that drops when you tidy the
 * sidebar is worse than useless while you are watching spend, so spend is
 * recorded once, when it happens, and never recomputed from history.
 *
 * Everything here is an estimate from published per-token rates, not a bill.
 * `pricing.py` explains where the numbers come from and how grounded search is
 * deliberately overcharged; the panel repeats the important half of that.
 */

import { storageKey } from './storage'

const KEY = storageKey('usage.v1')

const EMPTY = {
  questions: 0,
  inputTokens: 0,
  outputTokens: 0,
  groundedRequests: 0,
  costUsd: 0,
  since: null,
}

/** Sum one conversation's completed answers. Cheap enough to call on render. */
export function totals(messages) {
  return (messages || []).reduce((sum, message) => {
    const usage = message.usage
    if (!usage) return sum
    return {
      questions: sum.questions + 1,
      inputTokens: sum.inputTokens + (usage.input_tokens || 0),
      outputTokens: sum.outputTokens + (usage.output_tokens || 0),
      groundedRequests: sum.groundedRequests + (usage.grounded_requests || 0),
      costUsd: sum.costUsd + (usage.cost_usd || 0),
      since: sum.since,
    }
  }, EMPTY)
}

export function readLifetime() {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return EMPTY
    const parsed = JSON.parse(raw)
    return { ...EMPTY, ...parsed }
  } catch {
    return EMPTY
  }
}

/** Add one finished answer to the lifetime counter and return the new total. */
export function record(usage) {
  if (!usage) return readLifetime()
  const previous = readLifetime()
  const next = {
    questions: previous.questions + 1,
    inputTokens: previous.inputTokens + (usage.input_tokens || 0),
    outputTokens: previous.outputTokens + (usage.output_tokens || 0),
    groundedRequests: previous.groundedRequests + (usage.grounded_requests || 0),
    costUsd: previous.costUsd + (usage.cost_usd || 0),
    since: previous.since || Date.now(),
  }
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // A full quota should cost the counter, not the answer that was just given.
  }
  return next
}

/**
 * Start the counter from conversations that predate it -- once, ever.
 *
 * Those questions were asked and those tokens were spent; showing $0.0000 next
 * to a sidebar full of answers would be the misleading number, not the useful
 * one. It runs only when the counter has never been written, so it cannot
 * double-count and cannot undo a reset.
 */
export function seedFrom(conversations) {
  try {
    if (localStorage.getItem(KEY)) return readLifetime()
  } catch {
    return EMPTY
  }
  const seeded = (conversations || []).reduce(
    (sum, conversation) => {
      const t = totals(conversation.messages)
      return {
        questions: sum.questions + t.questions,
        inputTokens: sum.inputTokens + t.inputTokens,
        outputTokens: sum.outputTokens + t.outputTokens,
        groundedRequests: sum.groundedRequests + t.groundedRequests,
        costUsd: sum.costUsd + t.costUsd,
        since: sum.since,
      }
    },
    { ...EMPTY, since: Date.now() }
  )
  try {
    localStorage.setItem(KEY, JSON.stringify(seeded))
  } catch {
    // The panel still renders; it just starts again next reload.
  }
  return seeded
}

/**
 * Zero the counter.
 *
 * Writes zeroes rather than deleting the key: an absent key means "never
 * counted", which would let the seed above refill it from history on the next
 * reload and quietly undo this.
 */
export function resetLifetime() {
  const cleared = { ...EMPTY, since: Date.now() }
  try {
    localStorage.setItem(KEY, JSON.stringify(cleared))
  } catch {
    // Nothing to do; the caller re-reads either way.
  }
  return cleared
}

/**
 * Money, at four decimals throughout.
 *
 * Two places round differently and both are wrong for this: two decimals turns
 * every query into $0.00, and full float precision reads as false accuracy on a
 * number that is an estimate. A tenth of a cent is the resolution that makes
 * one query and a hundred queries legible on the same line.
 */
export const money = (usd) => `$${(usd || 0).toFixed(4)}`

export const count = (n) => (n || 0).toLocaleString()
