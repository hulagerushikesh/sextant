/**
 * The one request in this client that cannot be undone, and the id it carries.
 *
 * `lib/api.ts` is the single file every request to the server goes through —
 * `TestTheBrowserSendsWhatTheAppReads` pins that — and until now not one line
 * of it was executed by a test. The delete is the call where that mattered:
 * the id travels in the URL *path*, half of it is a filename a person chose,
 * and `encodeURI` leaves `#` and `?` alone because to the function writing a
 * URL those are punctuation. To this id they are data.
 *
 * Which makes the failure worse than a refusal. `budget#2.txt` is stored as
 * `upload:<them>:budget#2`; the `#` opened a fragment no browser transmits,
 * so the server was asked to remove `upload:<them>:budget` — a 404 about a
 * document plainly on the screen if they have no such file, and a 200
 * removing a *different* one of their files if they do, reported as success.
 *
 * These assert what the server receives, not what the string looks like: the
 * URL is parsed the way a browser parses it before sending, and the path is
 * decoded the way the server decodes it. A test on the literal would pass on
 * a string that no longer survives transmission.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SERVER_URL, forgetDocument } from './api'

/**
 * Written out rather than imported. `api.ts` holds this name in exactly one
 * place and `TestTheNameIsWrittenOnceSoARenameHasOneSite` keeps it that way;
 * exporting it so a test could read it would make the test agree with the
 * client by construction, which is not the claim worth checking.
 */
const CLIENT_HEADER = 'X-Sextant-Client'

/** The removal body the route answers with; the id is what is under test. */
const REMOVED = {
  success: true,
  message: 'Removed',
  chunks_removed: 3,
  collection_size: 40,
}

/** Captures the request `forgetDocument` makes and answers it. */
const capture = () => {
  const seen: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    seen.push({ url, init })
    return Promise.resolve(
      new Response(JSON.stringify(REMOVED), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
  })
  return seen
}

/**
 * The id the server is handed, derived from the URL rather than asserted
 * about the string: `new URL` splits off the fragment and query a browser
 * would not send, and `decodeURIComponent` is the server's own unquoting.
 */
const idTheServerSees = (url: string) => {
  const parsed = new URL(url)
  return {
    id: decodeURIComponent(parsed.pathname).replace('/documents/', ''),
    dropped: parsed.hash + parsed.search,
  }
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('the id a delete carries', () => {
  // Every one of these is a filename a person can save on a Mac or a Linux
  // box and drop on the upload box, reduced to its stem by `uploads.py`.
  // Only the first two were broken; the rest are here because the list was
  // measured rather than reasoned about, and because the cheapest way for
  // this fix to regress is for the next person to narrow the escaping back
  // down to "the characters that were failing".
  const hostile = [
    ['a hash, which opened a fragment', 'upload:ada:budget#2'],
    ['a question mark, which opened a query', 'upload:ada:report?v2'],
    ['a lone percent, which the URL parser repairs', 'upload:ada:100%2e'],
    ['a space', 'upload:ada:notes v1'],
    ['an ampersand', 'upload:ada:a&b'],
    ['a plus', 'upload:ada:a+b'],
    ['a plain id, which was never the problem', 'upload:ada:notes'],
  ] as const

  it.each(hostile)('survives %s', async (_what, id) => {
    const seen = capture()
    await forgetDocument(id)
    const sent = idTheServerSees(seen[0].url)
    expect(sent.id).toBe(id)
    expect(sent.dropped).toBe('')
  })

  it('keeps a slash a separator, so the path route still resolves', async () => {
    // `{document_id:path}` exists because a stem may contain one. Escaping it
    // would be the opposite bug: correct data, unroutable URL.
    const seen = capture()
    await forgetDocument('upload:ada:notes/2024')
    expect(new URL(seen[0].url).pathname).toBe('/documents/upload%3Aada%3Anotes/2024')
    expect(idTheServerSees(seen[0].url).id).toBe('upload:ada:notes/2024')
  })

  it('is a DELETE to this client server, naming the browser', async () => {
    const seen = capture()
    await forgetDocument('upload:ada:notes')
    expect(seen[0].url.startsWith(`${SERVER_URL}/documents/`)).toBe(true)
    expect(seen[0].init?.method).toBe('DELETE')
    // Leave the header off and the server answers as the anonymous `shared`
    // caller, which owns none of this browser's uploads: a 403 on your own file.
    const headers = seen[0].init?.headers as Record<string, string> | undefined
    expect(headers?.[CLIENT_HEADER]).toBeTruthy()
  })

  it('throws on a refusal rather than returning a flag', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve(
        new Response(JSON.stringify({ detail: 'not yours' }), {
          status: 403,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )
    await expect(forgetDocument('upload:grace:notes')).rejects.toThrow('not yours')
  })
})

describe('the defect these are here about', () => {
  it('is one `encodeURI` would still have', () => {
    // Not a test of the client — a test that the assertions above are not
    // vacuous. If this ever passes with `encodeURI`, the check above has
    // stopped measuring anything.
    const lost = idTheServerSees(`${SERVER_URL}/documents/${encodeURI('upload:ada:budget#2')}`)
    expect(lost.id).toBe('upload:ada:budget')
    expect(lost.dropped).toBe('#2')
  })

  it('removes a real, different document when one exists', () => {
    // The reason this is a defect and not an inconvenience. Both files are
    // this person's, so the truncated id is one they may write to: the server
    // authorises it, removes it, and answers 200 with a chunk count.
    const asked = 'upload:ada:budget#2'
    const removed = idTheServerSees(`${SERVER_URL}/documents/${encodeURI(asked)}`).id
    expect(removed).not.toBe(asked)
    expect(removed).toBe('upload:ada:budget')
  })
})
