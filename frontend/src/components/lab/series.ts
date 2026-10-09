import type { IndexName } from '@/lib/types'

/**
 * Series hues and labels for the lab's charts and tables.
 *
 * Its own module rather than an export beside `SweepChart`, because `lab.tsx`
 * imports it for the legend and the per-index cards: a non-component export
 * in a component file costs Vite's fast refresh the whole module on every
 * edit, which is what `react/only-export-components` is for.
 *
 * The app's provenance colours; FAISS rows are C++ references, drawn dashed
 * and set apart.
 */
export const SERIES: Record<IndexName, { label: string; color: string; dashed?: boolean }> = {
  flat: { label: 'Exact (flat)', color: 'var(--muted-foreground)' },
  hnsw: { label: 'HNSW', color: 'var(--corpus)' },
  ivfpq: { label: 'IVF-PQ', color: 'var(--web)' },
  ivfpq_rerank: { label: 'IVF-PQ + rerank', color: 'var(--success)' },
  faiss_hnsw: { label: 'FAISS HNSW · C++', color: 'var(--chart-5)', dashed: true },
  faiss_ivfpq: { label: 'FAISS IVF-PQ · C++', color: 'oklch(0.7 0.2 330)', dashed: true },
}
