/**
 * Whether the daily spend figure is the day's, and the words for either case.
 *
 * `/health` carries `durable`, and it has since milestone 21 item 15, which
 * added it so that "a figure nobody can date is not mistaken for the day's".
 * Nothing in this UI read it. When the ledger cannot be written -- a full
 * disk, or `/data/chroma` not writable by `APP_UID`, which is the failure
 * `trip.sh` step 5 tells the operator to watch for -- the cap still holds for
 * this process and `spent_usd` restarts at zero on every deploy and every
 * `restart: unless-stopped` bounce. The card printed that number under "Daily
 * cap" and "resets 00:00 UTC" regardless.
 *
 * One function owns every word that depends on the answer, so the card cannot
 * hedge the caption and then print an unhedged "left" beside it.
 */
import type { Budget } from './types'

export interface DayFigure {
  /** True when `spent_usd` really is the day's spend across restarts. */
  trustworthy: boolean
  /** Printed after the figures, under the bar. */
  caption: string
  /** Goes in front of the remaining amount: the headroom is an upper bound. */
  remainingPrefix: string
  /** Why the figure cannot be trusted. Absent when it can. */
  note?: string
}

export function dayFigure(budget: Budget): DayFigure {
  // Only an explicit `false` is an accusation. A server too old to send the
  // field, or a payload that dropped it, is unknown -- and treating unknown as
  // broken would put a warning on every healthy box that predates the field.
  if (budget.durable !== false)
    return { trustworthy: true, caption: 'resets 00:00 UTC', remainingPrefix: '' }

  return {
    trustworthy: false,
    caption: 'since this server started — not the day',
    remainingPrefix: 'at most ',
    note:
      'The spend ledger cannot be read or written, so this restarted with the ' +
      'server. The day really spent at least this much.',
  }
}
