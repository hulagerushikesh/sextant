import { useMemo } from 'react'
import { CartesianGrid, Line, LineChart, Scatter, XAxis, YAxis } from 'recharts'
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, type ChartConfig } from '@/components/ui/chart'
import type { IndexName, SweepRow } from '@/lib/types'
import { SERIES } from './series'

/**
 * Recall against latency — the tradeoff curve the lab exists to show. Log x:
 * latencies span 0.01ms to several ms and a linear axis smears the fast points
 * into the y-axis. Series colours live in `series.ts`, which `lab.tsx` reads too.
 */

const fmtMs = (ms: number) => (ms >= 1 ? `${ms.toFixed(1)}ms` : `${(ms * 1000).toFixed(0)}µs`)

export function SweepChart({ rows, metric }: { rows: SweepRow[]; metric: 'p50' | 'p90' | 'p99' }) {
  const byIndex = useMemo(() => {
    const m = new Map<IndexName, { x: number; y: number; params: string }[]>()
    for (const r of rows) {
      const pts = m.get(r.index) || []
      pts.push({ x: r.latency_ms[metric], y: r.recall, params: Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(' ') })
      m.set(r.index, pts.sort((a, b) => a.x - b.x))
    }
    return m
  }, [rows, metric])

  const config = Object.fromEntries([...byIndex.keys()].map((k) => [k, { label: SERIES[k].label, color: SERIES[k].color }])) satisfies ChartConfig
  const xs = rows.map((r) => r.latency_ms[metric])
  const domain: [number, number] = [Math.min(...xs) * 0.7, Math.max(...xs) * 1.4]
  // 1-2-5 ticks per decade, clipped to the domain, so a log axis reads as one.
  // `domain` is a fresh array every render, so depending on it would recompute
  // every render and the memo would do nothing. Its two numbers are the inputs.
  // oxlint-disable-next-line react/exhaustive-deps -- deps are domain's values
  const ticks = useMemo(() => {
    const out: number[] = []
    for (let e = Math.floor(Math.log10(domain[0])); e <= Math.ceil(Math.log10(domain[1])); e++)
      for (const m of [1, 2, 5]) { const v = m * 10 ** e; if (v >= domain[0] && v <= domain[1]) out.push(v) }
    return out
    // oxlint-disable-next-line react/exhaustive-deps -- indexing is deliberate
  }, [domain[0], domain[1]])

  return (
    <ChartContainer config={config} className="h-[340px] w-full">
      <LineChart margin={{ top: 12, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="2 4" vertical={false} />
        <XAxis type="number" dataKey="x" scale="log" domain={domain} ticks={ticks} tickFormatter={fmtMs} tickLine={false} axisLine={false} fontSize={11} label={{ value: `latency · ${metric}`, position: 'insideBottomRight', offset: -4, fontSize: 11, fill: 'var(--muted-foreground)' }} />
        <YAxis type="number" dataKey="y" domain={[0, 1]} tickFormatter={(v) => v.toFixed(1)} tickLine={false} axisLine={false} width={34} fontSize={11} />
        <ChartTooltip
          cursor={false}
          content={({ payload }) => {
            const p = payload?.[0]?.payload as { x: number; y: number; params: string } | undefined
            const name = payload?.[0]?.name as IndexName | undefined
            if (!p || !name) return null
            return (
              <div className="rounded-lg border bg-popover px-2.5 py-2 text-xs shadow-md">
                <div className="mb-1 font-medium" style={{ color: SERIES[name]?.color }}>{SERIES[name]?.label}</div>
                <div className="font-mono text-muted-foreground">{p.params || '—'}</div>
                <div className="mt-1 font-mono tabular">recall {p.y.toFixed(3)} · {fmtMs(p.x)}</div>
              </div>
            )
          }}
        />
        <ChartLegend content={<ChartLegendContent nameKey="name" />} />
        {[...byIndex.entries()].map(([name, pts]) =>
          pts.length > 1 ? (
            <Line key={name} name={name} data={pts} dataKey="y" type="monotone" stroke={SERIES[name].color} strokeWidth={1.75} strokeDasharray={SERIES[name].dashed ? '4 4' : undefined} dot={{ r: 3.5, strokeWidth: 0, fill: SERIES[name].color }} activeDot={{ r: 5 }} isAnimationActive={false} />
          ) : (
            <Scatter key={name} name={name} data={pts} dataKey="y" fill={SERIES[name].color} shape="diamond" isAnimationActive={false} />
          ),
        )}
      </LineChart>
    </ChartContainer>
  )
}
