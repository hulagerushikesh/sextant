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
 * Ported from the current UI's `storage.js`; the two must agree, because a
 * browser that has used both reads and writes the same keys either way.
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
 * A stable random name for this browser, sent with uploads.
 *
 * It exists so two people behind the one shared password stop overwriting
 * each other's documents: before 0.8.2 an upload was stored as
 * `upload:<filename>`, so the second `notes.pdf` deleted the first. It is a
 * namespace, not a login — the server treats it as untrusted, and it hides
 * nothing from anyone's search. See `mcp_server/identity.py`.
 *
 * Random rather than anything about the person: it needs to be unique and
 * stable, and nothing more. If storage is unavailable, the server's own
 * default applies and the old shared behaviour is what you get — which is the
 * right failure, because the alternative is a new id per page load and a
 * duplicate document on every re-upload.
 */
export function clientId(): string | null {
  try {
    let id = localStorage.getItem(CLIENT_KEY)
    if (!id) {
      id = `b${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
      localStorage.setItem(CLIENT_KEY, id)
    }
    return id
  } catch {
    return null
  }
}
