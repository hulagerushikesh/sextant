/**
 * What the server's health payload means, and the words for it.
 *
 * One function returning the tone and the sentence together, because the
 * sidebar needs both and must not recover the cause from the tone. It used to:
 * `App` collapsed the payload to `'ok' | 'degraded' | 'down'` and the sidebar
 * printed "Degraded — no model key" for every `degraded`. A box whose model key
 * is fine and whose MCP subprocess failed to start reported a missing key, and
 * `mcp_error` -- the server's own description of the real fault, already in the
 * payload and already in the type -- was never shown to anyone.
 *
 * Same shape as `rule_verdict` in eval/tenancy.py and `billing_line` in
 * deploy.sh, for the same reason: a second place that re-derives the decision
 * is a second place that can be wrong about it.
 */
import type { HealthProbe } from './api'

export type HealthTone = 'ok' | 'degraded' | 'down'

export interface HealthLine {
  tone: HealthTone
  /** One line for the sidebar. Names the fault, never guesses which one. */
  label: string
  /** The server's own words for the fault, when it sent any. */
  detail?: string
}

export function healthLine(probe: HealthProbe): HealthLine {
  if (!probe.reached) {
    // Two different facts, and they send the reader to two different places:
    // nothing answered means look at the network, an answered 503 means look
    // at the server's own log. `checkHealth` used to return null for both.
    return probe.status === null
      ? { tone: 'down', label: 'Server unreachable' }
      : { tone: 'down', label: `Server refused the health check (${probe.status})` }
  }
  const health = probe.health

  const noModel = !health.model_configured
  const noKb = !health.mcp_connected
  const detail = noKb && health.mcp_error ? health.mcp_error : undefined

  if (noModel && noKb)
    return { tone: 'degraded', label: 'Degraded — no model key, knowledge base not connected', detail }
  // Retrieval works without a key; answering does not. The server reports the
  // two separately for exactly this reason, so say which one is missing.
  if (noModel)
    return { tone: 'degraded', label: 'Degraded — no model key, so no answers' }
  if (noKb)
    return { tone: 'degraded', label: 'Degraded — knowledge base not connected', detail }

  return { tone: 'ok', label: 'Server healthy' }
}
