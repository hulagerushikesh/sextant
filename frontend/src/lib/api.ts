/**
 * Agent-server client: the endpoints, the SSE frames, the contract. Nothing
 * here changes what the server has to do.
 *
 * It began as a port of a `client.js` that lived beside the UI this replaced.
 * That file is gone, and so is the repo split the old header named, so there
 * is nothing left to be a port *of*. `mcp_server/main.py` is the contract.
 */
import { mockCompare, mockDocuments, mockHealth, mockStats, mockStream, mockSweep } from './mock'
import { clientId } from './storage'
import type {
  CompareResult,
  DocumentListing,
  Health,
  Removal,
  Stats,
  StreamHandlers,
  SweepResult,
} from './types'

export const SERVER_URL = import.meta.env.VITE_SERVER_URL || 'http://localhost:8000'
export const MOCK = import.meta.env.VITE_MOCK === '1'

/**
 * What mock mode actually means, in one sentence, in one place.
 *
 * `.env.development` says it already: "a UI that silently shows invented
 * answers is worse than one that says the server is unreachable." Every mock
 * branch below and the notice in the header read this, so the screen and the
 * toasts cannot disagree about how much of what you are looking at is real.
 */
export const MOCK_NOTICE =
  'Mock mode: every answer, figure and source on this screen is invented. No server is being queried.'

/**
 * Headers every request carries, not just the ones that obviously need to.
 *
 * `X-Sextant-Client` names the namespace this browser's uploads are stored
 * under. Since the server scopes what it returns to that namespace, a request
 * that omits it is answered as the anonymous `shared` caller — so leaving it
 * off /stats or /query/stream would hide this browser's own uploads from its
 * own search results. One helper, used everywhere, so a call site added later
 * does not have to remember. Untrusted by the server: it namespaces, it does
 * not authenticate — see mcp_server/identity.py.
 *
 * It is sent unconditionally, because `shared` is not a namespace this
 * browser may be put in by accident: it owns the corpus the operator
 * ingested, so a request with no name is a request that may delete it.
 * `clientId()` answers `NO_STORAGE_OWNER` instead and cannot return nothing.
 */
const sent = (extra?: Record<string, string>): Record<string, string> => ({
  ...extra,
  'X-Sextant-Client': clientId(),
})

const describeFailure = async (response: Response) => {
  const fallback = `Server returned ${response.status}`
  try {
    const body = await response.json()
    const detail = body.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length)
      return detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
    return fallback
  } catch {
    return fallback
  }
}

export async function streamQuery(query: string, h: StreamHandlers): Promise<void> {
  if (MOCK) return mockStream(query, h)
  const { history = [], sources = [], webSearch = false, signal } = h
  const response = await fetch(`${SERVER_URL}/query/stream`, {
    method: 'POST',
    headers: sent({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      query,
      history,
      sources: sources.map(({ n, key, origin, title, url, location, score }) => ({ n, key, origin, title, url, location, score })),
      web_search: webSearch,
      timestamp: new Date().toISOString(),
      client_id: 'frontend_ui',
    }),
    signal,
  })
  if (!response.ok) throw new Error(await describeFailure(response))
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      if (!frame.trim()) continue
      let event = 'message'
      const data: string[] = []
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).trim())
      }
      if (!data.length) continue
      const payload = JSON.parse(data.join('\n'))
      if (event === 'sources') h.onSources(payload.sources || [])
      else if (event === 'token') h.onToken(payload.text || '')
      else if (event === 'tool_call') h.onToolCall?.(payload)
      else if (event === 'tool_result') h.onToolResult?.(payload)
      else if (event === 'answer') h.onAnswer?.(payload)
      else if (event === 'error') throw new Error(payload.message)
      else if (event === 'done') {
        h.onSources(payload.sources || [])
        h.onDone?.(payload)
        return
      }
    }
  }
}

export async function uploadFiles(files: File[]): Promise<{ success: boolean; message?: string; error?: string }> {
  if (MOCK) {
    await new Promise((r) => setTimeout(r, 1400))
    // Not `Indexed N files -- N chunks.` A success toast for an upload that
    // never happened is the one mock response a person acts on: they close the
    // tab believing the document is in the corpus.
    return {
      success: true,
      message: `Mock: pretended to index ${files.length} file${files.length === 1 ? '' : 's'}. Nothing was stored.`,
    }
  }
  const form = new FormData()
  for (const f of files) form.append('files', f, f.name)
  const response = await fetch(`${SERVER_URL}/upload`, {
    method: 'POST',
    body: form,
    headers: sent(),
  })
  if (!response.ok) throw new Error(await describeFailure(response))
  return response.json()
}

/**
 * What this caller has in the corpus, and which of it is theirs to remove.
 *
 * Returns the listing or null, the same shape `fetchStats` uses: the card
 * beside it already distinguishes "loading" from "unreachable", and a thrown
 * error here would take the upload box down with the list.
 */
export async function fetchDocuments(): Promise<DocumentListing | null> {
  if (MOCK) return new Promise((r) => setTimeout(() => r(mockDocuments), 400))
  try {
    const response = await fetch(`${SERVER_URL}/documents`, { headers: sent() })
    return response.ok ? response.json() : null
  } catch {
    return null
  }
}

/**
 * A document id as the `{document_id:path}` segment run it is.
 *
 * `encodeURI` was wrong here, and wrong in the direction that removes the
 * wrong file. It leaves `#` and `?` alone because in a URL *it* is writing
 * those are punctuation — but an id is data, and the half of it a person
 * controls is whatever they named their file. `budget#2.txt` is stored as
 * `upload:<them>:budget#2`, and `encodeURI` built
 * `DELETE /documents/upload:<them>:budget#2`, where the `#` opens a fragment
 * no browser transmits. The server was therefore asked to remove
 * `upload:<them>:budget`: a 404 about a document plainly on the screen if
 * they have no such file, and a **200 removing a different one of their
 * files** if they do — the one action in this client that cannot be undone,
 * reported as having worked. `?` truncates the same way into a query string.
 *
 * Measured rather than assumed, because the other candidates are not defects:
 * a space, `&` and `+` cross a path untouched, and a lone `%` is *repaired*
 * to `%25` by the URL parser `fetch` runs before sending, so `100%2e` arrives
 * as `100%2e` and not as `100.`. Two characters, both of which end a path.
 *
 * Slashes stay slashes. The route is `{document_id:path}` precisely because a
 * stem may contain one, so `/` is this id's only punctuation and every other
 * character is escaped.
 */
const asPath = (id: string) => id.split('/').map(encodeURIComponent).join('/')

/**
 * Remove one of this caller's own documents.
 *
 * Throws rather than returning a flag, because the caller asked for something
 * destructive and a silent no-op is the worst of the three outcomes: a 403
 * means the server disagrees about whose document this is, and a 404 means it
 * was already gone. Both are sentences worth showing.
 */
export async function forgetDocument(id: string): Promise<Removal> {
  if (MOCK) {
    await new Promise((r) => setTimeout(r, 400))
    return {
      success: true,
      // Not "Removed". Nothing was, and a person acts on this one.
      message: `Mock: pretended to remove ${id}. Nothing was deleted.`,
      chunks_removed: 0,
      collection_size: mockStats.collection_size,
    }
  }
  const response = await fetch(`${SERVER_URL}/documents/${asPath(id)}`, {
    method: 'DELETE',
    headers: sent(),
  })
  if (!response.ok) throw new Error(await describeFailure(response))
  return response.json()
}

export async function fetchStats(): Promise<Stats | null> {
  if (MOCK) return new Promise((r) => setTimeout(() => r(mockStats), 500))
  try {
    const response = await fetch(`${SERVER_URL}/stats`, { headers: sent() })
    return response.ok ? response.json() : null
  } catch {
    return null
  }
}

/**
 * The outcome of one health check, with the two failures kept apart.
 *
 * This used to be `Health | null`, and `null` meant both "the fetch threw"
 * and "the server answered 4xx/5xx". Those are different facts and the UI
 * printed the first one's words for both: a box answering 503 was reported as
 * unreachable, which sends whoever reads it to the network instead of to the
 * server's own logs.
 */
export type HealthProbe =
  | { reached: true; health: Health }
  /** `status` is null when nothing answered at all. */
  | { reached: false; status: number | null }

export async function checkHealth(): Promise<HealthProbe> {
  if (MOCK) return new Promise((r) => setTimeout(() => r({ reached: true, health: mockHealth }), 300))
  try {
    const response = await fetch(`${SERVER_URL}/health`, { headers: sent() })
    if (!response.ok) return { reached: false, status: response.status }
    return { reached: true, health: await response.json() }
  } catch {
    return { reached: false, status: null }
  }
}

export async function runBenchmark(body: { k?: number; n_queries?: number; grid?: object }): Promise<SweepResult> {
  if (MOCK) return new Promise((r) => setTimeout(() => r(mockSweep()), 1800))
  const response = await fetch(`${SERVER_URL}/ann/benchmark`, {
    method: 'POST', headers: sent({ 'Content-Type': 'application/json' }), body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await describeFailure(response))
  return response.json()
}

export async function compareIndexes(query: string, opts: { k?: number; hnsw?: object; ivfpq?: object }): Promise<CompareResult> {
  if (MOCK) return new Promise((r) => setTimeout(() => r(mockCompare(query)), 700))
  const response = await fetch(`${SERVER_URL}/ann/compare`, {
    method: 'POST', headers: sent({ 'Content-Type': 'application/json' }), body: JSON.stringify({ query, ...opts }),
  })
  if (!response.ok) throw new Error(await describeFailure(response))
  return response.json()
}
