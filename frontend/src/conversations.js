/**
 * Saved conversations, in localStorage.
 *
 * The server is stateless by design -- every request carries the transcript and
 * the labels it needs -- which means "where do conversations live?" had no
 * answer, and "New conversation" simply threw the previous one away.
 *
 * They live here. That keeps the server unchanged, works with no account and no
 * database, and means a conversation belongs to the browser that had it. The
 * cost is honest and worth stating: clearing site data loses them, and they do
 * not follow you to another machine. Both are the right trade for a tool you
 * run yourself; neither would be for a hosted product.
 */

import { storageKey } from './storage'

const KEY = storageKey('conversations.v1')

// Old threads are cheap to keep and impossible to keep forever. Thirty is well
// inside a 5MB quota even with passage text attached, and the writer evicts
// further if the browser disagrees.
const MAX_CONVERSATIONS = 30

const now = () => Date.now()

export const newId = () => `c${now().toString(36)}${Math.random().toString(36).slice(2, 7)}`

/** A conversation's name is its first question, trimmed to fit a sidebar. */
export const titleFor = (messages) => {
  const first = messages.find((message) => message.role === 'user')
  if (!first) return 'New conversation'
  const text = first.text.replace(/\s+/g, ' ').trim()
  return text.length > 48 ? `${text.slice(0, 47)}…` : text
}

export function loadAll() {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed?.conversations) ? parsed.conversations : []
  } catch {
    // Corrupt or half-written storage should cost the history, not the app.
    return []
  }
}

/**
 * Persist, shedding data rather than failing when the quota is reached.
 *
 * Three levels, each losing something less important than the app breaking:
 * evict the oldest conversations, then drop stored passage text (an old thread
 * still reads, its citations just cannot be expanded), then give up quietly.
 */
export function saveAll(conversations) {
  const ordered = [...conversations]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_CONVERSATIONS)

  const attempts = [
    ordered,
    ordered.slice(0, 10),
    ordered.map((c) => ({ ...c, sources: c.sources.map(({ text, ...rest }) => rest) })),
  ]

  for (const attempt of attempts) {
    try {
      localStorage.setItem(KEY, JSON.stringify({ version: 1, conversations: attempt }))
      return attempt
    } catch {
      continue
    }
  }
  return ordered
}

export function blank() {
  return { id: newId(), title: 'New conversation', createdAt: now(), updatedAt: now(), messages: [], sources: [] }
}

/** Replace one conversation's contents, stamping it as the most recent. */
export function upsert(conversations, id, { messages, sources }) {
  const existing = conversations.find((c) => c.id === id)
  const updated = {
    ...(existing || blank()),
    id,
    messages,
    sources,
    title: titleFor(messages),
    updatedAt: now(),
  }
  return [updated, ...conversations.filter((c) => c.id !== id)]
}

export function remove(conversations, id) {
  return conversations.filter((c) => c.id !== id)
}
