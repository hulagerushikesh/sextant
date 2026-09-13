import React, { useMemo, useState } from 'react'

/**
 * Recall against latency, the tradeoff curve the whole phase exists to show.
 *
 * A hand-drawn SVG scatter rather than a charting dependency: the shapes are a
 * few polylines and circles, the axes are two scales, and pulling in a library
 * to draw them would be more code than this, not less -- and would fight the
 * token palette. Each index is one series, coloured by the same hues the rest of
 * the app uses for provenance: neutral for the exact baseline, blue for HNSW,
 * ochre for IVF-PQ.
 *
 * The x-axis is logarithmic. Latencies span from ~0.02 ms (a flat scan of a tiny
 * corpus) to several ms (IVF-PQ at high nprobe), and on a linear axis the fast
 * points pile up against the y-axis into an unreadable smear. Log space is where
 * the recall/latency frontier is actually a curve you can read.
 */

const SERIES = {
  flat: { label: 'Exact (flat)', color: 'var(--ink-soft)' },
  hnsw: { label: 'HNSW', color: 'var(--local)' },
  ivfpq: { label: 'IVF-PQ', color: 'var(--web)' },
  ivfpq_rerank: { label: 'IVF-PQ + rerank', color: 'var(--rerank)' },
  // C++ references, drawn dashed and set apart: not under test, just the speed
  // the tested algorithms run at once compiled. The gap is the constant factor.
  faiss_hnsw: { label: 'FAISS HNSW · C++ ref', color: 'var(--faiss)', dashed: true },
  faiss_ivfpq: { label: 'FAISS IVF-PQ · C++ ref', color: 'var(--faiss2)', dashed: true },
}

const WIDTH = 640
const HEIGHT = 380
const PAD = { top: 24, right: 24, bottom: 48, left: 52 }

const niceLatency = (ms) => (ms >= 1 ? `${ms.toFixed(1)}ms` : `${(ms * 1000).toFixed(0)}µs`)

export default function SweepChart({ rows, metric = 'p50' }) {
  const [hover, setHover] = useState(null)

  const points = useMemo(() => {
    return rows
      .map((row) => ({
        ...row,
        latency: row.latency_ms[metric],
        recall: row.recall,
      }))
      // A latency of exactly 0 cannot be placed on a log axis; clamp to a floor
      // that reads as "too fast to time" rather than dropping the point.
      .map((p) => ({ ...p, latency: Math.max(p.latency, 0.005) }))
  }, [rows, metric])

  const bounds = useMemo(() => {
    const latencies = points.map((p) => p.latency)
    const min = Math.min(...latencies)
    const max = Math.max(...latencies)
    // Pad the log range by a factor so points do not sit on the frame.
    return { lo: Math.log10(min / 1.4), hi: Math.log10(max * 1.4) }
  }, [points])

  if (!points.length) return null

  const plotW = WIDTH - PAD.left - PAD.right
  const plotH = HEIGHT - PAD.top - PAD.bottom

  const x = (latency) => {
    const t = (Math.log10(latency) - bounds.lo) / (bounds.hi - bounds.lo || 1)
    return PAD.left + t * plotW
  }
  // Recall is a fraction; fix the axis at 0-1 so two sweeps are comparable and a
  // 0.9 always sits nine-tenths up, never rescaled to fill the box.
  const y = (recall) => PAD.top + (1 - recall) * plotH

  const series = useMemo(() => {
    const byIndex = new Map()
    for (const p of points) {
      if (!byIndex.has(p.index)) byIndex.set(p.index, [])
      byIndex.get(p.index).push(p)
    }
    // Sort each series along the x-axis so the connecting line is monotonic in
    // latency and reads as a frontier, not a scribble.
    for (const list of byIndex.values()) list.sort((a, b) => a.latency - b.latency)
    return byIndex
  }, [points])

  const xTicks = useMemo(() => {
    const ticks = []
    const lo = Math.ceil(bounds.lo)
    const hi = Math.floor(bounds.hi)
    for (let e = lo; e <= hi; e += 1) ticks.push(10 ** e)
    return ticks.length ? ticks : [10 ** bounds.lo, 10 ** bounds.hi]
  }, [bounds])

  return (
    <figure className="sweep-chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="Recall against query latency for each index"
      >
        {/* recall gridlines at 0, .25, .5, .75, 1 */}
        {[0, 0.25, 0.5, 0.75, 1].map((r) => (
          <g key={r}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={y(r)}
              y2={y(r)}
              className="grid"
            />
            <text x={PAD.left - 8} y={y(r) + 4} className="axis-label" textAnchor="end">
              {r.toFixed(2)}
            </text>
          </g>
        ))}

        {xTicks.map((t) => (
          <text key={t} x={x(t)} y={HEIGHT - PAD.bottom + 18} className="axis-label" textAnchor="middle">
            {niceLatency(t)}
          </text>
        ))}

        <text
          className="axis-title"
          x={PAD.left}
          y={HEIGHT - 8}
          textAnchor="start"
        >
          query latency ({metric}, log scale) →
        </text>
        <text
          className="axis-title"
          transform={`translate(14 ${PAD.top + plotH / 2}) rotate(-90)`}
          textAnchor="middle"
        >
          recall@k →
        </text>

        {/* one polyline + markers per index */}
        {[...series.entries()].map(([index, list]) => {
          const meta = SERIES[index] || { color: 'var(--ink)' }
          const path = list.map((p) => `${x(p.latency)},${y(p.recall)}`).join(' ')
          return (
            <g key={index}>
              {list.length > 1 && (
                <polyline
                  points={path}
                  fill="none"
                  stroke={meta.color}
                  strokeDasharray={meta.dashed ? '6 4' : undefined}
                  className="series-line"
                />
              )}
              {list.map((p, i) => (
                <circle
                  key={i}
                  cx={x(p.latency)}
                  cy={y(p.recall)}
                  r={hover === p ? 6 : 4}
                  fill={meta.color}
                  className="series-dot"
                  onMouseEnter={() => setHover(p)}
                  onMouseLeave={() => setHover(null)}
                />
              ))}
            </g>
          )
        })}
      </svg>

      <figcaption className="sweep-legend">
        {[...series.keys()].map((index) => {
          const meta = SERIES[index] || { label: index, color: 'var(--ink)' }
          const swatch = meta.dashed
            ? { background: 'transparent', border: `1.5px dashed ${meta.color}` }
            : { background: meta.color }
          return (
            <span key={index} className="legend-item">
              <span className="legend-swatch" style={swatch} />
              {meta.label}
            </span>
          )
        })}
      </figcaption>

      {hover && (
        <div className="sweep-tip">
          <strong>{SERIES[hover.index]?.label || hover.index}</strong>
          <span>recall {hover.recall.toFixed(3)}</span>
          <span>{niceLatency(hover.latency)} {metric}</span>
          {Object.keys(hover.params || {}).length > 0 && (
            <span className="sweep-tip-params">
              {Object.entries(hover.params)
                .map(([key, value]) => `${key} ${value}`)
                .join(' · ')}
            </span>
          )}
        </div>
      )}
    </figure>
  )
}
