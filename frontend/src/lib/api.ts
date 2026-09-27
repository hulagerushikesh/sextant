/**
 * Agent-server client. A TypeScript port of frontend/src/api/client.js in the
 * main repo — same endpoints, same SSE frames, same contract. Nothing here
 * changes what the server has to do.
 */
import { mockCompare, mockHealth, mockStats, mockStream, mockSweep } from './mock'
import type { CompareResult, Health, Stats, StreamHandlers, SweepResult } from './types'

export const SERVER_URL = import.meta.env.VITE_SERVER_URL || 'http://localhost:8000'
export const MOCK = import.meta.env.VITE_MOCK === '1'

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
    headers: { 'Content-Type': 'application/json' },
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
    return { success: true, message: `Indexed ${files.length} file${files.length === 1 ? '' : 's'} — ${files.length * 37} chunks.` }
  }
  const form = new FormData()
  for (const f of files) form.append('files', f, f.name)
  const response = await fetch(`${SERVER_URL}/upload`, { method: 'POST', body: form })
  if (!response.ok) throw new Error(await describeFailure(response))
  return response.json()
}

export async function fetchStats(): Promise<Stats | null> {
  if (MOCK) return new Promise((r) => setTimeout(() => r(mockStats), 500))
  try {
    const response = await fetch(`${SERVER_URL}/stats`)
    return response.ok ? response.json() : null
  } catch {
    return null
  }
}

export async function checkHealth(): Promise<Health | null> {
  if (MOCK) return new Promise((r) => setTimeout(() => r(mockHealth), 300))
  try {
    const response = await fetch(`${SERVER_URL}/health`)
    return response.ok ? response.json() : null
  } catch {
    return null
  }
}

export async function runBenchmark(body: { k?: number; n_queries?: number; grid?: object }): Promise<SweepResult> {
  if (MOCK) return new Promise((r) => setTimeout(() => r(mockSweep()), 1800))
  const response = await fetch(`${SERVER_URL}/ann/benchmark`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await describeFailure(response))
  return response.json()
}

export async function compareIndexes(query: string, opts: { k?: number; hnsw?: object; ivfpq?: object }): Promise<CompareResult> {
  if (MOCK) return new Promise((r) => setTimeout(() => r(mockCompare(query)), 700))
  const response = await fetch(`${SERVER_URL}/ann/compare`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, ...opts }),
  })
  if (!response.ok) throw new Error(await describeFailure(response))
  return response.json()
}
