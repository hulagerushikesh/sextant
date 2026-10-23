/**
 * The one-shot migration that carries a person's saved conversations, spend
 * ledger and first-run flag from the `agenticrag.*` keys to `sextant.*`.
 *
 * Its header used to say it "must agree" with a `storage.js` that no longer
 * exists, which is the entire assurance it had: nothing executed a line of
 * it. These say what has to hold, in a place that can fail.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const load = async () => {
  vi.resetModules()
  return import('./storage')
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('the migration nobody ran', () => {
  it('carries the old value across', async () => {
    localStorage.setItem('agenticrag.conversations.v1', '{"conversations":[1]}')
    const { storageKey } = await load()
    expect(storageKey('conversations.v1')).toBe('sextant.conversations.v1')
    expect(localStorage.getItem('sextant.conversations.v1')).toBe('{"conversations":[1]}')
  })

  it('removes the old name, so it runs once and not on every read', async () => {
    localStorage.setItem('agenticrag.usage.v1', '{"questions":4}')
    const { storageKey } = await load()
    storageKey('usage.v1')
    expect(localStorage.getItem('agenticrag.usage.v1')).toBeNull()
  })

  it('never overwrites a value already under the new name', async () => {
    // A browser that used both would otherwise have its current threads
    // replaced by whatever the old UI last left behind.
    localStorage.setItem('sextant.conversations.v1', 'current')
    localStorage.setItem('agenticrag.conversations.v1', 'stale')
    const { storageKey } = await load()
    storageKey('conversations.v1')
    expect(localStorage.getItem('sextant.conversations.v1')).toBe('current')
  })

  it('leaves an empty string alone, because something wrote it', async () => {
    localStorage.setItem('sextant.onboarded', '')
    localStorage.setItem('agenticrag.onboarded', '1')
    const { storageKey } = await load()
    storageKey('onboarded')
    expect(localStorage.getItem('sextant.onboarded')).toBe('')
  })

  it('still returns the key when storage throws', async () => {
    // Private mode. A failed migration may not take the page down; the
    // callers all handle a missing value already.
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('denied') },
      setItem: () => { throw new Error('denied') },
      removeItem: () => { throw new Error('denied') },
    })
    const { storageKey } = await load()
    expect(storageKey('conversations.v1')).toBe('sextant.conversations.v1')
  })
})

describe('the browser name that stops two people overwriting each other', () => {
  it('is stable across calls, or every re-upload is a duplicate document', async () => {
    // Before 0.8.2 an upload was stored as `upload:<filename>`, so the second
    // notes.pdf deleted the first. A fresh id per call would trade that for a
    // duplicate per page load, and nothing checked which one happened.
    const { clientId } = await load()
    const first = clientId()
    expect(first).toBeTruthy()
    expect(clientId()).toBe(first)
  })

  it('survives a reload, which is the whole point of writing it down', async () => {
    const { clientId } = await load()
    const first = clientId()
    const reloaded = await load()
    expect(reloaded.clientId()).toBe(first)
  })

  it('returns null rather than a fresh id when storage is unavailable', async () => {
    // The server's shared default is the right failure here; a new id each
    // load is the wrong one.
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('denied') },
      setItem: () => { throw new Error('denied') },
    })
    const { clientId } = await load()
    expect(clientId()).toBeNull()
  })
})
