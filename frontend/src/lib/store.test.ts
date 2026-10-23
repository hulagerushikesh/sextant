/**
 * `saveAll` is the only thing standing between a person's conversations and
 * losing them. It had three ways to report a success it had not achieved.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Conversation } from './types'

/** A localStorage that refuses anything over `limit` characters, like a quota. */
function cappedStorage(limit: number) {
  const data = new Map<string, string>()
  return {
    store: data,
    getItem: (k: string) => data.get(k) ?? null,
    removeItem: (k: string) => { data.delete(k) },
    clear: () => data.clear(),
    setItem: (k: string, v: string) => {
      if (v.length > limit) {
        const e = new Error('QuotaExceededError')
        e.name = 'QuotaExceededError'
        throw e
      }
      data.set(k, v)
    },
  }
}

const thread = (i: number, passageChars: number): Conversation => ({
  id: `c${i}`,
  title: `Thread ${i}`,
  createdAt: i,
  updatedAt: i,
  messages: [{ role: 'user', text: `q${i}` }, { role: 'assistant', text: `a${i}` }],
  sources: [{ n: 1, key: `k${i}`, origin: 'knowledge_base', title: `Doc ${i}`, text: 'x'.repeat(passageChars) }],
})

const threads = (n: number, passageChars = 400) =>
  Array.from({ length: n }, (_, i) => thread(i, passageChars))

const withStorage = async (limit: number) => {
  const fake = cappedStorage(limit)
  vi.stubGlobal('localStorage', fake)
  vi.resetModules()
  return { fake, store: await import('./store') }
}

afterEach(() => vi.unstubAllGlobals())

describe('a save that reports a success it did not achieve', () => {
  it('says so when nothing could be written at all', async () => {
    const { store } = await withStorage(0)
    const result = store.saveAll(threads(3))
    expect(result.failed).toBe(true)
    expect(result.note).toMatch(/not saving/i)
  })

  it('is silent when the whole list went in', async () => {
    const { store } = await withStorage(1_000_000)
    const result = store.saveAll(threads(3))
    expect(result.failed).toBe(false)
    expect(result.note).toBeNull()
    expect(result.saved).toHaveLength(3)
  })

  it('returns what it kept, not what it was handed', async () => {
    // The caller renders this. Handing back the full list after keeping ten
    // is how the sidebar showed thirty conversations that a reload did not
    // have, so the returned list and the stored list must be the same list.
    const { fake, store } = await withStorage(6_000)
    const result = store.saveAll(threads(30))
    const written = JSON.parse(fake.getItem('sextant.conversations.v1')!)
    expect(result.saved.length).toBe(written.conversations.length)
    expect(result.saved.length).toBeLessThan(30)
  })

  it('says what it dropped, every time it drops something', async () => {
    const { store } = await withStorage(6_000)
    const result = store.saveAll(threads(30))
    expect(result.failed).toBe(false)
    expect(result.note).toBeTruthy()
  })
})

describe('a ladder whose last rung is not the smallest', () => {
  it('tries fewer conversations without passages, which the old order never did', async () => {
    // The rungs were: everything, then ten, then *everything again* without
    // the passage text. Rung three can be bigger than rung two, so the
    // cheapest combination -- ten, no text -- was never attempted, and a
    // quota that only that would have fit lost the lot.
    //
    // This limit is chosen to sit exactly there: too small for 30 without
    // text, big enough for 10 without text.
    const all = threads(30)
    const lightTen = all.slice(0, 10).map((c) => ({ ...c, sources: c.sources.map(({ text: _t, ...r }) => r) }))
    const lightAll = all.map((c) => ({ ...c, sources: c.sources.map(({ text: _t, ...r }) => r) }))
    const sizeOf = (list: Conversation[]) => JSON.stringify({ version: 1, conversations: list }).length
    const limit = Math.floor((sizeOf(lightTen) + sizeOf(lightAll)) / 2)
    expect(sizeOf(lightTen)).toBeLessThan(limit)
    expect(sizeOf(lightAll)).toBeGreaterThan(limit)

    const { store } = await withStorage(limit)
    const result = store.saveAll(all)
    expect(result.failed).toBe(false)
    expect(result.saved.length).toBeGreaterThan(0)
  })

  it('shrinks monotonically, so each rung is cheaper than the one above', async () => {
    const sizes: number[] = []
    const fake = cappedStorage(0)
    const spy = { ...fake, setItem: (k: string, v: string) => { sizes.push(v.length); fake.setItem(k, v) } }
    vi.stubGlobal('localStorage', spy)
    vi.resetModules()
    const store = await import('./store')
    store.saveAll(threads(30))
    expect(sizes.length).toBeGreaterThan(1)
    for (let i = 1; i < sizes.length; i++) expect(sizes[i]).toBeLessThan(sizes[i - 1])
  })
})
