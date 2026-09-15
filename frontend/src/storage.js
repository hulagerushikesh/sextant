/**
 * localStorage key names, with the pre-rename keys carried over once.
 *
 * The app was called Agentic RAG; its saved conversations, spend ledger and
 * onboarding flag were written under `agenticrag.*`. Renaming the keys without
 * this would present every existing user with an empty sidebar and the
 * first-run card again, which is a data loss from their point of view even
 * though nothing was deleted. Each key is moved on first read and the old
 * name removed, so the migration runs once per browser and never again.
 */

const PREFIX = 'sextant.'
const LEGACY_PREFIX = 'agenticrag.'

/** The current key for a suffix, migrating the legacy value if present. */
export function storageKey(suffix) {
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
