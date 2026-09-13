import React, { useState } from 'react'
import { compareIndexes, runBenchmark } from '../api/client'
import SweepChart from './SweepChart'

// Machine index names -> display labels, shared by the sweep table and A/B view.
const INDEX_LABEL = {
  flat: 'Exact',
  hnsw: 'HNSW',
  ivfpq: 'IVF-PQ',
  ivfpq_rerank: 'IVF-PQ + rerank',
  faiss_hnsw: 'FAISS HNSW · C++',
  faiss_ivfpq: 'FAISS IVF-PQ · C++',
}

/**
 * The index lab: where HNSW and IVF-PQ are compared, so "which one, and when"
 * has an answer you can see rather than take on faith.
 *
 * Two modes, the two questions a comparison actually gets asked:
 *
 *   Sweep    -- across a grid of parameters, recall against latency, with build
 *               time and memory. The aggregate tradeoff: which algorithm, tuned
 *               how, for a target recall.
 *   Query    -- one question through every index side by side against exact
 *               search, showing which passages each one missed. The concrete
 *               case: what an approximation cost on *this* retrieval.
 *
 * Both run against the live corpus over the same endpoints the agent's retrieval
 * uses, so the numbers describe the real index, not a synthetic benchmark.
 */

function LatencyMetricToggle({ metric, onChange }) {
  return (
    <div className="metric-toggle" role="group" aria-label="Latency percentile">
      {['p50', 'p90', 'p99'].map((m) => (
        <button
          key={m}
          type="button"
          className={metric === m ? 'is-active' : ''}
          onClick={() => onChange(m)}
        >
          {m}
        </button>
      ))}
    </div>
  )
}

function bytes(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} MB`
  if (n >= 1000) return `${(n / 1000).toFixed(1)} KB`
  return `${n} B`
}

function SweepView() {
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [metric, setMetric] = useState('p50')

  const run = async () => {
    setRunning(true)
    setError(null)
    try {
      // 384-d MiniLM vectors: m=48 divides evenly (dsub=8). A modest sweep so
      // the whole thing returns in a few seconds on a laptop-sized corpus.
      const out = await runBenchmark({
        k: 10,
        n_queries: 100,
        grid: {
          hnsw_ef_search: [10, 20, 40, 80, 160],
          ivf_m: 48,
          ivf_nlist: 32,
          ivf_nprobe: [1, 2, 4, 8, 16, 32],
        },
      })
      if (out.error) setError(out.error)
      else setResult(out)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="lab-view">
      <div className="lab-actions">
        <button type="button" className="button" onClick={run} disabled={running}>
          {running ? 'Building indexes…' : result ? 'Run sweep again' : 'Run benchmark sweep'}
        </button>
        {result && <LatencyMetricToggle metric={metric} onChange={setMetric} />}
        {result && (
          <span className="lab-meta">
            {result.corpus.vectors.toLocaleString()} vectors · {result.corpus.dim}-d ·{' '}
            {result.queries} queries · k={result.k}
          </span>
        )}
      </div>

      {error && <p className="notice error">{error}</p>}

      {result?.notes?.map((note) => (
        <p key={note} className="notice">
          {note}
        </p>
      ))}

      {result && (
        <>
          <SweepChart rows={result.rows} metric={metric} />

          <div className="lab-table-wrap">
            <table className="lab-table">
              <thead>
                <tr>
                  <th>Index</th>
                  <th>Parameters</th>
                  <th className="num">Recall@{result.k}</th>
                  <th className="num">{metric}</th>
                  <th className="num">Build</th>
                  <th className="num">Per vector</th>
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i} className={`row-${row.index}`}>
                    <td className="idx-cell">{INDEX_LABEL[row.index] || row.index}</td>
                    <td className="params-cell">
                      {Object.entries(row.params)
                        .map(([k, v]) => `${k}=${v}`)
                        .join('  ') || '—'}
                    </td>
                    <td className="num">{row.recall.toFixed(3)}</td>
                    <td className="num">{row.latency_ms[metric].toFixed(3)}ms</td>
                    <td className="num">{row.build_seconds.toFixed(2)}s</td>
                    <td className="num" title="Asymptotic cost per vector, fixed overhead excluded">
                      {row.amortised_bytes_per_vector.toFixed(0)} B
                    </td>
                    <td className="num" title="Total resident bytes over the corpus, incl. fixed overhead">
                      {bytes(row.bytes)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="lab-note">
            Recall is measured against exact search over the same vectors, so the exact row scores
            1.000 by definition — it is the yardstick, not a competitor. <strong>Per vector</strong> is
            the cost one more chunk adds; IVF-PQ&rsquo;s codebooks are a fixed overhead a large corpus
            amortises, which is why its <strong>total</strong> can exceed the flat baseline at small
            corpus sizes while its per-vector cost is far lower.
          </p>
        </>
      )}

      {!result && !running && !error && (
        <div className="lab-empty">
          <h3>Compare the approximate indexes over your corpus.</h3>
          <p>
            The sweep builds HNSW and IVF-PQ across a grid of their parameters and measures each
            against exact search: recall, query latency, build time and memory. It runs on whatever
            you have ingested, so the numbers are about your data, not a synthetic set. Building the
            graphs takes a few seconds.
          </p>
        </div>
      )}
    </div>
  )
}

function QueryView() {
  const [draft, setDraft] = useState('')
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  const run = async (question) => {
    setRunning(true)
    setError(null)
    try {
      const out = await compareIndexes(question, {
        k: 10,
        ivfpq: { nlist: 32, nprobe: 8, m: 48 },
      })
      if (out.error) setError(out.error)
      else setResult(out)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const submit = (event) => {
    event.preventDefault()
    const question = draft.trim()
    if (question && !running) run(question)
  }

  const passages = result?.passages || {}
  const ORDER = ['flat', 'hnsw', 'ivfpq', 'ivfpq_rerank']
  const LABEL = INDEX_LABEL

  return (
    <div className="lab-view">
      <form className="lab-query" onSubmit={submit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask something your corpus can answer…"
          aria-label="Query to compare across indexes"
        />
        <button type="submit" className="button" disabled={!draft.trim() || running}>
          {running ? 'Searching…' : 'Compare'}
        </button>
      </form>

      {error && <p className="notice error">{error}</p>}

      {result && (
        <div className="ab-grid">
          {ORDER.filter((name) => result.results[name]).map((name) => {
            const res = result.results[name]
            return (
              <section key={name} className={`ab-col ab-${name}`}>
                <header className="ab-head">
                  <h3>{LABEL[name]}</h3>
                  <div className="ab-stats">
                    {name !== 'flat' && (
                      <span className="ab-recall">recall {res.recall.toFixed(2)}</span>
                    )}
                    <span className="ab-lat">{res.latency_ms.toFixed(2)}ms</span>
                  </div>
                </header>

                <ol className="ab-hits">
                  {res.hits.map((hit) => {
                    const passage = passages[hit.id] || {}
                    const isMiss = name !== 'flat' && !result.exact.includes(hit.id)
                    return (
                      <li key={hit.id} className={isMiss ? 'ab-hit ab-extra' : 'ab-hit'}>
                        <span className="ab-hit-title">{passage.title || hit.id}</span>
                        <span className="ab-hit-score">{hit.score.toFixed(3)}</span>
                      </li>
                    )
                  })}
                </ol>

                {res.missed?.length > 0 && (
                  <div className="ab-missed">
                    <span className="ab-missed-label">Missed vs exact</span>
                    <ul>
                      {res.missed.map((id) => (
                        <li key={id}>{passages[id]?.title || id}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            )
          })}
        </div>
      )}

      {result && (
        <p className="lab-note">
          Each column is the same query, retrieved by a different index. A hit tinted differently is
          one the approximate index returned that exact search did <em>not</em> rank in the top-{result.k};
          <strong> Missed vs exact</strong> lists the true neighbours it dropped. Flat is exact, so it
          neither adds nor misses anything.
        </p>
      )}

      {!result && !running && !error && (
        <div className="lab-empty">
          <h3>Watch one query go through every index.</h3>
          <p>
            Ask a question and see the exact neighbours beside what HNSW and IVF-PQ returned, with
            each one&rsquo;s latency and the passages it missed. The aggregate sweep tells you which
            index to pick; this tells you what picking it costs on a specific question.
          </p>
        </div>
      )}
    </div>
  )
}

export default function Lab() {
  const [mode, setMode] = useState('sweep')

  return (
    <div className="lab">
      <div className="lab-modes" role="tablist" aria-label="Comparison mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'sweep'}
          className={mode === 'sweep' ? 'is-active' : ''}
          onClick={() => setMode('sweep')}
        >
          Benchmark sweep
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'query'}
          className={mode === 'query' ? 'is-active' : ''}
          onClick={() => setMode('query')}
        >
          Per-query A/B
        </button>
      </div>

      {mode === 'sweep' ? <SweepView /> : <QueryView />}
    </div>
  )
}
