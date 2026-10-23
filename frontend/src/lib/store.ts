/**
 * Saved conversations and the spend counter, in localStorage.
 *
 * The keys are the ones the UI this replaced wrote, which is why the browsers
 * of anyone who used it still find their threads. That reason outlived the
 * files the old header credited it to: `conversations.js` and `usage.js` are
 * gone, and `storage.ts` is where the key names and the migration live now.
 */
import type { Conversation, Message, Source, Usage } from './types'
import { storageKey } from './storage'

// `storageKey` reads through the pre-rename `agenticrag.*` name once and moves
// it, so a browser that used the old UI keeps its threads and its ledger.
const CONV_KEY = storageKey('conversations.v1')
const USAGE_KEY = storageKey('usage.v1')
const MAX_CONVERSATIONS = 30

const now = () => Date.now()
export const newId = () => `c${now().toString(36)}${Math.random().toString(36).slice(2, 7)}`

export const titleFor = (messages: Message[]) => {
  const first = messages.find((m) => m.role === 'user')
  if (!first) return 'New conversation'
  const text = first.text.replace(/\s+/g, ' ').trim()
  return text.length > 48 ? `${text.slice(0, 47)}…` : text
}

export function loadAll(): Conversation[] {
  try {
    const raw = localStorage.getItem(CONV_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed?.conversations) ? parsed.conversations : []
  } catch {
    return []
  }
}

export interface SaveResult {
  /** What is in storage now. The caller renders this, not what it passed in. */
  saved: Conversation[]
  /** True when every attempt threw and nothing was written at all. */
  failed: boolean
  /**
   * One sentence for the person, or null when the save was clean. Decided
   * here with the outcome, so no caller re-derives it by comparing lengths.
   */
  note: string | null
}

/** The source list without passage text: the big half of a conversation. */
const lighten = (list: Conversation[]) =>
  list.map((c) => ({ ...c, sources: c.sources.map(({ text: _t, ...rest }) => rest) }))

export function saveAll(conversations: Conversation[]): SaveResult {
  const ordered = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CONVERSATIONS)
  // Strictly shrinking, which the first version was not: it tried everything,
  // then ten, then *everything again* with the passage text dropped -- a rung
  // that can be larger than the one below it, so the cheapest combination
  // (ten, no text) was never tried at all. A ladder whose last rung is not
  // the smallest is not a ladder.
  const attempts: { list: Conversation[]; note: string | null }[] = [
    { list: ordered, note: null },
    {
      list: lighten(ordered),
      note: 'Storage is nearly full, so the quoted passages were dropped from saved conversations. The answers and the source list are intact.',
    },
    {
      list: lighten(ordered).slice(0, 10),
      note: 'Storage is full. Only the 10 most recent conversations are being kept, without their quoted passages.',
    },
    {
      list: lighten(ordered).slice(0, 3),
      note: 'Storage is full. Only the 3 most recent conversations are being kept, without their quoted passages.',
    },
  ]
  for (const attempt of attempts) {
    try {
      localStorage.setItem(CONV_KEY, JSON.stringify({ version: 1, conversations: attempt.list }))
      return { saved: attempt.list, failed: false, note: attempt.note }
    } catch {
      continue
    }
  }
  // Nothing was written. This used to return the full list, so the sidebar
  // showed thirty conversations as kept and the next page load had none of
  // them -- a save reporting a success it did not achieve, and the one place
  // in the app where that costs the person something they cannot get back.
  return {
    saved: ordered,
    failed: true,
    note: 'This browser is not saving conversations — storage is full or blocked. Anything here is gone when the tab closes.',
  }
}

export const blank = (): Conversation => ({
  id: newId(), title: 'New conversation', createdAt: now(), updatedAt: now(), messages: [], sources: [],
})

export function upsert(list: Conversation[], id: string, patch: { messages: Message[]; sources: Source[] }) {
  const existing = list.find((c) => c.id === id)
  const updated: Conversation = { ...(existing || blank()), id, ...patch, title: titleFor(patch.messages), updatedAt: now() }
  return [updated, ...list.filter((c) => c.id !== id)]
}

export const remove = (list: Conversation[], id: string) => list.filter((c) => c.id !== id)

/* --- spend ----------------------------------------------------------------- */

export interface Lifetime {
  questions: number
  inputTokens: number
  outputTokens: number
  groundedRequests: number
  costUsd: number
  since: number | null
}

const EMPTY: Lifetime = { questions: 0, inputTokens: 0, outputTokens: 0, groundedRequests: 0, costUsd: 0, since: null }

export function totals(messages: Message[]): Lifetime {
  return (messages || []).reduce<Lifetime>((sum, m) => {
    const u = m.usage
    if (!u) return sum
    return {
      questions: sum.questions + 1,
      inputTokens: sum.inputTokens + (u.input_tokens || 0),
      outputTokens: sum.outputTokens + (u.output_tokens || 0),
      groundedRequests: sum.groundedRequests + (u.grounded_requests || 0),
      costUsd: sum.costUsd + (u.cost_usd || 0),
      since: sum.since,
    }
  }, EMPTY)
}

export function readLifetime(): Lifetime {
  try {
    const raw = localStorage.getItem(USAGE_KEY)
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY
  } catch {
    return EMPTY
  }
}

export function record(usage?: Usage): Lifetime {
  if (!usage) return readLifetime()
  const p = readLifetime()
  const next: Lifetime = {
    questions: p.questions + 1,
    inputTokens: p.inputTokens + (usage.input_tokens || 0),
    outputTokens: p.outputTokens + (usage.output_tokens || 0),
    groundedRequests: p.groundedRequests + (usage.grounded_requests || 0),
    costUsd: p.costUsd + (usage.cost_usd || 0),
    since: p.since || now(),
  }
  try { localStorage.setItem(USAGE_KEY, JSON.stringify(next)) } catch { /* quota */ }
  return next
}

export function seedFrom(conversations: Conversation[]): Lifetime {
  try { if (localStorage.getItem(USAGE_KEY)) return readLifetime() } catch { return EMPTY }
  const seeded = conversations.reduce<Lifetime>((sum, c) => {
    const t = totals(c.messages)
    return {
      questions: sum.questions + t.questions,
      inputTokens: sum.inputTokens + t.inputTokens,
      outputTokens: sum.outputTokens + t.outputTokens,
      groundedRequests: sum.groundedRequests + t.groundedRequests,
      costUsd: sum.costUsd + t.costUsd,
      since: sum.since,
    }
  }, { ...EMPTY, since: now() })
  try { localStorage.setItem(USAGE_KEY, JSON.stringify(seeded)) } catch { /* quota */ }
  return seeded
}

export function resetLifetime(): Lifetime {
  const cleared = { ...EMPTY, since: now() }
  try { localStorage.setItem(USAGE_KEY, JSON.stringify(cleared)) } catch { /* quota */ }
  return cleared
}

export const money = (usd?: number) => `$${(usd || 0).toFixed(4)}`
export const count = (n?: number) => (n || 0).toLocaleString()

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
export const MOD = isMac ? '⌘' : 'Ctrl'
