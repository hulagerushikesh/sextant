/**
 * The sidebar used to print "Degraded — no model key" for every degraded box.
 * Two different faults land in that state and the server reports them
 * separately on purpose, so these pin which one the words may name.
 */
import { describe, expect, it } from 'vitest'
import { healthLine } from './health'
import type { HealthProbe } from './api'
import type { Health } from './types'

const reached = (over: Partial<Health> = {}): HealthProbe => ({ reached: true, health: healthy(over) })

const healthy = (over: Partial<Health> = {}): Health => ({
  status: 'healthy',
  mcp_connected: true,
  model_configured: true,
  supported_uploads: ['.md'],
  web_search_enabled: false,
  budget: { enabled: false } as Health['budget'],
  mcp_error: null,
  tools_discovered: ['kb_search'],
  tools_offered_to_model: ['kb_search'],
  ...over,
})

describe('the fault it names must be the fault there is', () => {
  it('does not blame the model key when the key is fine', () => {
    const line = healthLine(reached({ mcp_connected: false, status: 'degraded' }))
    expect(line.tone).toBe('degraded')
    expect(line.label).not.toMatch(/model key/i)
    expect(line.label).toMatch(/knowledge base/i)
  })

  it('blames the model key when that is what is missing', () => {
    const line = healthLine(reached({ model_configured: false, status: 'degraded' }))
    expect(line.tone).toBe('degraded')
    expect(line.label).toMatch(/model key/i)
    expect(line.label).not.toMatch(/knowledge base/i)
  })

  it('names both when both are down', () => {
    const line = healthLine(reached({ model_configured: false, mcp_connected: false, status: 'degraded' }))
    expect(line.label).toMatch(/model key/i)
    expect(line.label).toMatch(/knowledge base/i)
  })

  it('carries the server own words for the fault', () => {
    const line = healthLine(reached({ mcp_connected: false, mcp_error: "spawn ./.venv/bin/python ENOENT" }))
    expect(line.detail).toBe('spawn ./.venv/bin/python ENOENT')
  })

  it('does not attach an mcp_error to a box whose mcp is connected', () => {
    // The server leaves `mcp_error` set after a reconnect in some paths; a
    // stale string shown beside a healthy knowledge base is a fault report
    // for something that is working.
    const line = healthLine(reached({ mcp_error: 'an error from an earlier attempt' }))
    expect(line.tone).toBe('ok')
    expect(line.detail).toBeUndefined()
  })

  it('reports an unreachable server as down, not as degraded', () => {
    expect(healthLine({ reached: false, status: null })).toEqual({
      tone: 'down', label: 'Server unreachable',
    })
  })

  it('does not call a server that answered unreachable', () => {
    // Nothing answering and a 503 are different facts and send the reader to
    // different places -- the network, or the server's own log. `checkHealth`
    // returned null for both, and this said "unreachable" about a box that
    // had just replied.
    const line = healthLine({ reached: false, status: 503 })
    expect(line.tone).toBe('down')
    expect(line.label).not.toMatch(/unreachable/i)
    expect(line.label).toContain('503')
  })

  it('says nothing is wrong when nothing is', () => {
    const line = healthLine(reached())
    expect(line.tone).toBe('ok')
    expect(line.label).toBe('Server healthy')
  })
})
