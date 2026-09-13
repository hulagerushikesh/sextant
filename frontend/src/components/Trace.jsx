import React, { useState } from 'react'

/**
 * What the agent did, in order.
 *
 * Before Phase 7 this listed the calls and nothing else, which made the loop's
 * most interesting behaviour unreadable: a search that came back empty and a
 * search that returned ten passages looked identical, so "the model searched
 * three times" read as a defect rather than as the agent working. Each row now
 * carries its outcome, and an empty result is styled as one.
 */

const WHERE = {
  mcp: { label: 'MCP', title: 'Ran in the knowledge-base subprocess over stdio' },
  google: { label: 'Google', title: "Ran on Google's servers, as a built-in tool" },
}

function describe(summary) {
  if (!summary) return null
  if (summary.status === 'error') return { text: summary.error || 'failed', tone: 'error' }
  if (summary.status === 'empty') return { text: 'nothing found', tone: 'empty' }
  if (typeof summary.hits === 'number') {
    const passages = `${summary.hits} passage${summary.hits === 1 ? '' : 's'}`
    const scored =
      summary.top_score != null ? `, top ${Number(summary.top_score).toFixed(2)}` : ''
    return { text: passages + scored, tone: 'ok' }
  }
  if (summary.documents != null) {
    return { text: `${summary.documents} documents, ${summary.chunks} chunks`, tone: 'ok' }
  }
  return { text: 'done', tone: 'ok' }
}

export default function Trace({ steps, running }) {
  const [open, setOpen] = useState(false)
  if (!steps.length) return null

  const searches = steps.filter((s) => s.name.endsWith('search')).length
  const summary =
    searches > 1
      ? `${steps.length} steps, ${searches} searches`
      : `${steps.length} step${steps.length === 1 ? '' : 's'}`

  return (
    <div className={`trace ${open ? 'is-open' : ''}`}>
      <button type="button" className="trace-toggle" onClick={() => setOpen(!open)}>
        <span className="trace-chevron" aria-hidden="true" />
        {running ? 'Working' : summary}
        {running && <span className="trace-pulse" aria-hidden="true" />}
      </button>

      {open && (
        <ol className="trace-steps">
          {steps.map((step, i) => {
            const outcome = describe(step.summary)
            const where = WHERE[step.where] || WHERE.mcp
            return (
              <li key={i} className="trace-step">
                <span className={`trace-where ${step.where}`} title={where.title}>
                  {where.label}
                </span>
                <code className="trace-tool">{step.name}</code>
                {step.input?.query && <span className="trace-arg">{step.input.query}</span>}
                {outcome ? (
                  <span className={`trace-outcome ${outcome.tone}`}>{outcome.text}</span>
                ) : (
                  <span className="trace-outcome pending">running…</span>
                )}
                {step.duration_ms != null && (
                  <span className="trace-ms">{step.duration_ms} ms</span>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
