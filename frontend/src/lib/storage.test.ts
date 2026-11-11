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

/**
 * `identity.DEFAULT_OWNER`, written out rather than imported across a
 * language boundary. It is the name this browser must *not* answer to, so a
 * test that read it from the server would agree with the server by
 * construction and stop being the claim worth checking.
 */
const SHARED_OWNER = 'shared'

/** A browser whose storage refuses both ways: private mode, or quota. */
const denied = () => ({
  getItem: () => {
    throw new Error('denied')
  },
  setItem: () => {
    throw new Error('denied')
  },
  removeItem: () => {
    throw new Error('denied')
  },
})

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

  it('falls back to a namespace of its own, never to the shared one', async () => {
    // Until 2026-11-11 this returned null, `api.ts` then sent no client name,
    // and the server answered as `shared` -- which owns every document the
    // operator ingested. `GET /documents` therefore marked all of them
    // `yours` and `corpus-card.tsx` drew a delete control on each row. The
    // reasoning that was here chose that failure deliberately, and it was
    // written when `shared` meant only a shared namespace; milestone 22 made
    // it mean a delete and nobody came back to this line.
    vi.stubGlobal('localStorage', denied())
    const { clientId } = await load()
    expect(clientId()).toBeTruthy()
    expect(clientId()).not.toBe(SHARED_OWNER)
  })

  it('keeps that fallback stable, which is why it is not a random id', async () => {
    // The original reason for returning null at all: a fresh id per page load
    // makes every re-upload a second document, and this browser cannot write
    // one down to avoid it. A constant keeps the replace-on-re-upload
    // behaviour and gives up only the thing nobody wanted -- two storage-less
    // browsers landing in one namespace, which is the pre-0.8.2 collision
    // confined to callers that cannot be told apart anyway.
    vi.stubGlobal('localStorage', denied())
    const { clientId } = await load()
    const first = clientId()
    const reloaded = await load()
    expect(reloaded.clientId()).toBe(first)
  })
})
