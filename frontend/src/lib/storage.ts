/**
 * localStorage key names, with the pre-rename keys carried over once.
 *
 * The app was called Agentic RAG; its saved conversations, spend ledger and
 * onboarding flag were written under `agenticrag.*`. Renaming the keys without
 * this would present every existing user with an empty sidebar and the
 * first-run card again, which is a data loss from their point of view even
 * though nothing was deleted. Each key is moved on first read and the old
 * name removed, so the migration runs once per browser and never again.
 *
 * There was a `storage.js` beside the UI this replaced, and the header here
 * told the reader the two "must agree" -- an instruction to go and diff
 * against a file that no longer exists. What has to hold is stated directly
 * instead, and `storage.test.ts` holds it: the legacy value moves across
 * once, the old name is gone afterwards, a value already under the new name
 * is never overwritten, and an unavailable localStorage costs nothing but
 * the migration.
 */

const PREFIX = 'sextant.'
const LEGACY_PREFIX = 'agenticrag.'

/** The current key for a suffix, migrating the legacy value if present. */
export function storageKey(suffix: string): string {
  const key = PREFIX + suffix
  const legacy = LEGACY_PREFIX + suffix
  try {
    if (localStorage.getItem(key) === null) {
      const old = localStorage.getItem(legacy)
      if (old !== null) {
        localStorage.setItem(key, old)
        localStorage.removeItem(legacy)
      }
    }
  } catch {
    // Storage unavailable (private mode, quota): the caller already handles a
    // missing value, and a failed migration must not take the page down.
  }
  return key
}

const CLIENT_KEY = PREFIX + 'client.v1'

/**
 * The namespace a browser falls into when it cannot write its own name down.
 *
 * Deliberately **not** the server's `shared` default. Omitting the header
 * sends a request there instead, and `shared` owns every document the
 * operator ingested — `identity.writable_by` says so, which is what lets the
 * CLI and curl seed a box. That was harmless while a namespace only kept two
 * people's uploads apart. Since 0.9.1 it is also a delete: `GET /documents`
 * answers `yours` with `writable_by`, so a storage-less browser was told the
 * whole corpus was its own and `corpus-card.tsx` drew a remove control on
 * every row of it. Behind the gate Caddy names every caller and the client
 * id is never consulted, so the reachable case is any box run without the
 * gate, which is every development box.
 *
 * A constant rather than a per-load random id, for the reason the null it
 * replaces was chosen: a fresh name each load makes every re-upload a second
 * document, and this browser cannot remember one to avoid it. The cost is
 * that two storage-less browsers share this namespace and can replace each
 * other's uploads — the pre-0.8.2 collision, confined to callers that have
 * no way to be told apart, and no longer reaching anybody else's documents.
 */
export const NO_STORAGE_OWNER = 'no-storage'

/**
 * A stable random name for this browser, sent with uploads.
 *
 * It exists so two people behind the one shared password stop overwriting
 * each other's documents: before 0.8.2 an upload was stored as
 * `upload:<filename>`, so the second `notes.pdf` deleted the first. It is a
 * namespace, not a login — the server treats it as untrusted, and it hides
 * nothing from anyone's search. See `mcp_server/identity.py`.
 *
 * Random rather than anything about the person: it needs to be unique and
 * stable, and nothing more. If storage is unavailable this answers
 * `NO_STORAGE_OWNER` rather than nothing — see that constant for why the
 * server's own default is the one answer this must never give.
 *
 * Never null, so there is no call site left that can decide to send no name.
 */
export function clientId(): string {
  try {
    let id = localStorage.getItem(CLIENT_KEY)
    if (!id) {
      id = `b${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
      // A `getItem` that works and a `setItem` that does not is the quota
      // case; the id above was never written down, so returning it would be
      // the new-name-per-load failure. The catch below is the right arm.
      localStorage.setItem(CLIENT_KEY, id)
    }
    return id
  } catch {
    return NO_STORAGE_OWNER
  }
}
