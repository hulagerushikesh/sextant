import { useState } from 'react'
import { motion } from 'motion/react'
import { Play, Search } from 'lucide-react'
import { cn } from '@/lib/utils'
import { compareIndexes, runBenchmark } from '@/lib/api'
import type { CompareResult, IndexName, SweepResult } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { SERIES } from './series'
import { SweepChart } from './sweep-chart'

const bytes = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} KB` : `${n} B`)
type Metric = 'p50' | 'p90' | 'p99'

/**
 * Where HNSW and IVF-PQ are compared over the live corpus, so "which one, and
 * when" has an answer you can see. Sweep = the aggregate tradeoff; Query = what
 * an approximation cost on one specific retrieval.
 */
export function Lab() {
  const [mode, setMode] = useState<'sweep' | 'query'>('sweep')
  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-6">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-serif text-[26px] leading-tight tracking-tight">Index Lab</h1>
          <p className="mt-1 max-w-[60ch] text-[13.5px] text-muted-foreground">
            Approximate indexes measured against exact search over your own vectors — recall, latency, build time, memory.
          </p>
        </div>
        <Tabs value={mode} onValueChange={(v) => setMode(v as 'sweep' | 'query')}>
          <TabsList>
            <TabsTrigger value="sweep">Benchmark sweep</TabsTrigger>
            <TabsTrigger value="query">Per-query A/B</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      {mode === 'sweep' ? <SweepView /> : <QueryView />}
    </div>
  )
}

function SweepView() {
  const [result, setResult] = useState<SweepResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [metric, setMetric] = useState<Metric>('p50')

  const run = async () => {
    setRunning(true); setError(null)
    try {
      const out = await runBenchmark({ k: 10, n_queries: 100, grid: { hnsw_ef_search: [10, 20, 40, 80, 160], ivf_m: 48, ivf_nlist: 32, ivf_nprobe: [1, 2, 4, 8, 16, 32] } })
      if (out.error) setError(out.error); else setResult(out)
    } catch (e) { setError((e as Error).message) } finally { setRunning(false) }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={run} disabled={running} className="gap-1.5">
          <Play className="size-3.5" /> {running ? 'Building indexes…' : result ? 'Run sweep again' : 'Run benchmark sweep'}
        </Button>
        {result && (
          <Tabs value={metric} onValueChange={(v) => setMetric(v as Metric)}>
            <TabsList className="h-8">{(['p50', 'p90', 'p99'] as Metric[]).map((m) => <TabsTrigger key={m} value={m} className="font-mono text-xs">{m}</TabsTrigger>)}</TabsList>
          </Tabs>
        )}
        {result && (
          <span className="font-mono text-[11.5px] text-muted-foreground tabular">
            {result.corpus.vectors.toLocaleString()} vectors · {result.corpus.dim}-d · {result.queries} queries · k={result.k}
          </span>
        )}
      </div>

      {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] text-destructive">{error}</p>}
      {result?.notes?.map((n) => <p key={n} className="text-[12.5px] text-muted-foreground">{n}</p>)}

      {running && !result && (
        <div className="rounded-xl border bg-card p-5"><Skeleton className="h-[320px] w-full" /></div>
      )}

      {result && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="flex flex-col gap-5">
          <div className="rounded-xl border bg-card p-4 shadow-xs">
            <SweepChart rows={result.rows} metric={metric} />
          </div>

          <div className="overflow-x-auto rounded-xl border bg-card shadow-xs">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Index</TableHead>
                  <TableHead>Parameters</TableHead>
                  <TableHead className="text-right">Recall@{result.k}</TableHead>
                  <TableHead className="text-right font-mono">{metric}</TableHead>
                  <TableHead className="text-right">Build</TableHead>
                  <TableHead className="text-right">Per vector</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.rows.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="whitespace-nowrap">
                      <span className="mr-2 inline-block size-2 rounded-full align-middle" style={{ background: SERIES[r.index]?.color }} />
                      {SERIES[r.index]?.label || r.index}
                    </TableCell>
                    <TableCell className="font-mono text-[12px] text-muted-foreground">{Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join('  ') || '—'}</TableCell>
                    <TableCell className="text-right font-mono tabular">{r.recall.toFixed(3)}</TableCell>
                    <TableCell className="text-right font-mono tabular">{r.latency_ms[metric].toFixed(3)}ms</TableCell>
                    <TableCell className="text-right font-mono tabular">{r.build_seconds.toFixed(2)}s</TableCell>
                    <TableCell className="text-right font-mono tabular" title="Asymptotic cost per vector, fixed overhead excluded">{r.amortised_bytes_per_vector.toFixed(0)} B</TableCell>
                    <TableCell className="text-right font-mono tabular" title="Total resident bytes incl. fixed overhead">{bytes(r.bytes)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <p className="max-w-[80ch] text-[12.5px] leading-relaxed text-muted-foreground">
            Recall is measured against exact search over the same vectors, so the exact row scores 1.000 by definition — it is the yardstick, not a competitor.{' '}
            <strong className="text-foreground">Per vector</strong> is the cost one more chunk adds; IVF-PQ's codebooks are a fixed overhead a large corpus amortises, which is why its total can exceed flat at small sizes while its per-vector cost is far lower.
          </p>
        </motion.div>
      )}

      {!result && !running && !error && (
        <div className="rounded-xl border border-dashed p-8">
          <h3 className="font-serif text-[20px] tracking-tight">Compare the approximate indexes over your corpus.</h3>
          <p className="mt-2 max-w-[64ch] text-[13.5px] leading-relaxed text-muted-foreground">
            The sweep builds HNSW and IVF-PQ across a grid of their parameters and measures each against exact search. It runs on whatever you have ingested, so the numbers are about your data. Building the graphs takes a few seconds.
          </p>
        </div>
      )}
    </div>
  )
}

function QueryView() {
  const [draft, setDraft] = useState('')
  const [result, setResult] = useState<CompareResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (q: string) => {
    setRunning(true); setError(null)
    try {
      const out = await compareIndexes(q, { k: 10, ivfpq: { nlist: 32, nprobe: 8, m: 48 } })
      if (out.error) setError(out.error); else setResult(out)
    } catch (e) { setError((e as Error).message) } finally { setRunning(false) }
  }

  const ORDER: IndexName[] = ['flat', 'hnsw', 'ivfpq', 'ivfpq_rerank']
  const passages = result?.passages || {}

  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={(e) => { e.preventDefault(); if (draft.trim() && !running) run(draft.trim()) }} className="flex max-w-2xl gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask something your corpus can answer…" aria-label="Query to compare across indexes" className="pl-8" />
        </div>
        <Button type="submit" disabled={!draft.trim() || running}>{running ? 'Searching…' : 'Compare'}</Button>
      </form>

      {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] text-destructive">{error}</p>}

      {result && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {ORDER.filter((n) => result.results[n]).map((name) => {
            const res = result.results[name]!
            return (
              <section key={name} className="rounded-xl border bg-card shadow-xs">
                <header className="flex items-center justify-between border-b px-3 py-2.5" style={{ borderTopColor: SERIES[name].color }}>
                  <h3 className="flex items-center gap-2 text-[13px] font-medium"><span className="size-2 rounded-full" style={{ background: SERIES[name].color }} />{SERIES[name].label}</h3>
                  <div className="flex gap-2 font-mono text-[11px] text-muted-foreground tabular">
                    {name !== 'flat' && <span className={cn(res.recall < 1 && 'text-warning')}>recall {res.recall.toFixed(2)}</span>}
                    <span>{res.latency_ms.toFixed(2)}ms</span>
                  </div>
                </header>
                <ol className="divide-y">
                  {res.hits.map((hit, i) => {
                    const miss = name !== 'flat' && !result.exact.includes(hit.id)
                    return (
                      <li key={hit.id} className={cn('flex items-center gap-2 px-3 py-1.5 text-[12.5px]', miss && 'bg-web-muted/60')}>
                        <span className="w-4 shrink-0 font-mono text-[10.5px] text-muted-foreground tabular">{i + 1}</span>
                        <span className="min-w-0 flex-1 truncate">{passages[hit.id]?.title || hit.id}</span>
                        <span className="font-mono text-[11px] text-muted-foreground tabular">{hit.score.toFixed(3)}</span>
                      </li>
                    )
                  })}
                </ol>
                {res.missed && res.missed.length > 0 && (
                  <div className="border-t px-3 py-2">
                    <p className="mb-1 text-[10.5px] font-medium tracking-wide text-destructive uppercase">Missed vs exact</p>
                    <ul className="flex flex-col gap-0.5 text-[12px] text-muted-foreground">{res.missed.map((id) => <li key={id} className="truncate">{passages[id]?.title || id}</li>)}</ul>
                  </div>
                )}
              </section>
            )
          })}
        </motion.div>
      )}

      {result && (
        <p className="max-w-[80ch] text-[12.5px] leading-relaxed text-muted-foreground">
          Each column is the same query through a different index. A tinted row is one the approximate index returned that exact search did <em>not</em> rank in the top-{result.k}; <strong className="text-foreground">Missed vs exact</strong> lists the true neighbours it dropped.
        </p>
      )}

      {!result && !running && !error && (
        <div className="rounded-xl border border-dashed p-8">
          <h3 className="font-serif text-[20px] tracking-tight">Watch one query go through every index.</h3>
          <p className="mt-2 max-w-[64ch] text-[13.5px] leading-relaxed text-muted-foreground">
            Ask a question and see the exact neighbours beside what HNSW and IVF-PQ returned, with each one's latency and the passages it missed. The sweep tells you which index to pick; this tells you what picking it costs on a specific question.
          </p>
        </div>
      )}
    </div>
  )
}
