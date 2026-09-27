/**
 * Saved conversations and the spend counter, in localStorage. Ported from
 * conversations.js + usage.js; same keys, so the redesign reads the threads
 * the current UI already saved.
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

export function saveAll(conversations: Conversation[]): Conversation[] {
  const ordered = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CONVERSATIONS)
  const attempts = [
    ordered,
    ordered.slice(0, 10),
    ordered.map((c) => ({ ...c, sources: c.sources.map(({ text: _t, ...rest }) => rest) })),
  ]
  for (const attempt of attempts) {
    try {
      localStorage.setItem(CONV_KEY, JSON.stringify({ version: 1, conversations: attempt }))
      return attempt
    } catch {
      continue
    }
  }
  return ordered
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
