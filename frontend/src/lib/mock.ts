/**
 * Fixtures and a fake stream, so the redesign can be reviewed without the
 * agent server running. Enabled by `VITE_MOCK=1` (default in `npm run dev`
 * until the real backend is pointed at via VITE_SERVER_URL).
 */
import type { CompareResult, Health, Source, Stats, StreamHandlers, SweepResult } from './types'

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(t)
      reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
    })
  })

export const mockHealth: Health = {
  status: 'healthy',
  mcp_connected: true,
  model_configured: true,
  supported_uploads: ['.pdf', '.md', '.txt', '.html', '.docx'],
  web_search_enabled: false,
  // Carries a per-user share so the design mode renders that branch too:
  // the bar tracks the asker's own figure, with the box's beside it.
  budget: {
    enabled: true, budget_usd: 2.0, spent_usd: 0.4312, remaining_usd: 1.5688,
    owner_budget_usd: 1.0, owner_spent_usd: 0.3104, owner_remaining_usd: 0.6896,
  },
  mcp_error: null,
  tools_discovered: ['kb_search', 'kb_ingest', 'kb_stats'],
  tools_offered_to_model: ['kb_search', 'kb_stats', 'google_search'],
}

export const mockStats: Stats = {
  documents: 14,
  collection_size: 2_318,
  embedding_model: 'all-MiniLM-L6-v2',
  reranker: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
  chunking: { target_tokens: 200, overlap_tokens: 40 },
}

const SOURCES: Source[] = [
  {
    n: 1, key: 'instructgpt:p3', origin: 'knowledge_base',
    title: 'Training language models to follow instructions with human feedback',
    location: 'p. 3', score: 0.91,
    text: 'We call the resulting models InstructGPT. Starting with a set of labeler-written prompts and prompts submitted through the OpenAI API, we collect a dataset of labeler demonstrations of the desired model behavior, which we use to fine-tune GPT-3 using supervised learning.',
  },
  {
    n: 2, key: 'instructgpt:p8', origin: 'knowledge_base',
    title: 'Training language models to follow instructions with human feedback',
    location: 'p. 8', score: 0.84,
    text: 'We then collect a dataset of rankings of model outputs, which we use to further fine-tune this supervised model using reinforcement learning from human feedback (RLHF).',
  },
  {
    n: 3, key: 'web:openai-blog', origin: 'web',
    title: 'openai.com', url: 'https://openai.com/research/instruction-following',
  },
  {
    n: 4, key: 'rlhf-notes:s2', origin: 'knowledge_base',
    title: 'RLHF reading notes', location: '§2 Reward modelling', score: 0.62,
    text: 'The reward model is a 6B GPT-3 with the unembedding layer removed, trained on comparison data to output a scalar reward.',
  },
]

const ANSWER = `InstructGPT is a family of GPT-3 models fine-tuned to follow a user's instructions rather than merely continue text [1]. It was produced in three stages.

**Supervised fine-tuning.** Labelers wrote demonstrations of the desired behaviour for a set of prompts, and GPT-3 was fine-tuned on those demonstrations [1].

**Reward modelling.** Labelers then ranked several model outputs for the same prompt. Those rankings trained a separate model to predict which output a person would prefer [2, 4].

**Reinforcement learning.** The supervised model was optimised against that reward model with PPO, which is the step the paper calls RLHF [2].

The three stages differ in what a labeler is asked to produce:

| Stage | What labelers do | Trains |
| --- | --- | ---: |
| Supervised fine-tuning | write a demonstration | the policy [1] |
| Reward modelling | rank several outputs | the reward model [2, 4] |
| Reinforcement learning | nothing; PPO optimises | the policy again [2] |

The result: a 1.3B-parameter InstructGPT model was preferred by labelers over the 175B-parameter GPT-3, despite being over 100× smaller [3].`

export async function mockStream(query: string, h: StreamHandlers) {
  const s = h.signal
  const useWeb = !!h.webSearch
  await sleep(350, s)
  h.onToolCall?.({ name: 'kb_search', where: 'mcp', input: { query } })
  await sleep(620, s)
  h.onToolResult?.({ name: 'kb_search', where: 'mcp', summary: { status: 'ok', hits: 3, top_score: 0.91 }, duration_ms: 611 })
  h.onSources(SOURCES.filter((x) => x.origin === 'knowledge_base'))
  if (useWeb) {
    await sleep(200, s)
    h.onToolCall?.({ name: 'google_search', where: 'google', input: { query } })
    await sleep(900, s)
    h.onToolResult?.({ name: 'google_search', where: 'google', summary: { status: 'ok', hits: 1 }, duration_ms: 887 })
    h.onSources(SOURCES)
  }
  await sleep(250, s)
  const text = useWeb ? ANSWER : ANSWER.replace(' [3]', '')
  const words = text.split(/(\s+)/)
  for (const w of words) {
    h.onToken(w)
    await sleep(w.length > 6 ? 28 : 14, s)
  }
  h.onDone?.({
    sources: useWeb ? SOURCES : SOURCES.filter((x) => x.origin === 'knowledge_base'),
    usage: { input_tokens: 4_812, output_tokens: 318, grounded_requests: useWeb ? 1 : 0, cost_usd: useWeb ? 0.0187 : 0.0047 },
    turns: useWeb ? 3 : 2,
  })
}

export function mockSweep(): SweepResult {
  const rows: SweepResult['rows'] = [
    { index: 'flat', params: {}, recall: 1, latency_ms: { p50: 0.41, p90: 0.52, p99: 0.7 }, build_seconds: 0.01, amortised_bytes_per_vector: 1536, bytes: 3_560_000 },
    ...[10, 20, 40, 80, 160].map((ef, i) => ({
      index: 'hnsw' as const, params: { ef_search: ef, M: 16 },
      recall: [0.71, 0.86, 0.95, 0.985, 0.998][i],
      latency_ms: { p50: [0.05, 0.07, 0.11, 0.19, 0.34][i], p90: [0.07, 0.09, 0.14, 0.24, 0.42][i], p99: [0.1, 0.13, 0.2, 0.33, 0.55][i] },
      build_seconds: 2.3, amortised_bytes_per_vector: 1792, bytes: 4_150_000,
    })),
    ...[1, 2, 4, 8, 16, 32].map((np, i) => ({
      index: 'ivfpq' as const, params: { nlist: 32, nprobe: np, m: 48 },
      recall: [0.32, 0.49, 0.66, 0.79, 0.88, 0.93][i],
      latency_ms: { p50: [0.03, 0.04, 0.06, 0.1, 0.18, 0.33][i], p90: [0.04, 0.05, 0.08, 0.13, 0.22, 0.4][i], p99: [0.06, 0.08, 0.11, 0.18, 0.3, 0.52][i] },
      build_seconds: 0.9, amortised_bytes_per_vector: 56, bytes: 620_000,
    })),
    ...[4, 8, 16, 32].map((np, i) => ({
      index: 'ivfpq_rerank' as const, params: { nlist: 32, nprobe: np, m: 48, rerank: 100 },
      recall: [0.84, 0.93, 0.97, 0.99][i],
      latency_ms: { p50: [0.12, 0.17, 0.27, 0.45][i], p90: [0.15, 0.21, 0.33, 0.55][i], p99: [0.2, 0.28, 0.44, 0.7][i] },
      build_seconds: 0.9, amortised_bytes_per_vector: 1592, bytes: 3_700_000,
    })),
    ...[10, 40, 160].map((ef, i) => ({
      index: 'faiss_hnsw' as const, params: { ef_search: ef },
      recall: [0.72, 0.95, 0.998][i],
      latency_ms: { p50: [0.012, 0.022, 0.06][i], p90: [0.015, 0.028, 0.075][i], p99: [0.02, 0.04, 0.1][i] },
      build_seconds: 0.4, amortised_bytes_per_vector: 1792, bytes: 4_150_000,
    })),
  ]
  return {
    corpus: { vectors: 2_318, dim: 384 }, queries: 100, k: 10, rows,
    notes: ['FAISS rows are C++ references, not under test — they show the constant factor a compiled implementation buys.'],
  }
}

export function mockCompare(query: string): CompareResult {
  const ids = Array.from({ length: 10 }, (_, i) => `chunk-${i + 1}`)
  const passages = Object.fromEntries(ids.map((id, i) => [id, { title: `${SOURCES[i % 3].title.slice(0, 42)}… · p. ${i + 2}` }]))
  const hits = (order: number[]) => order.map((i, r) => ({ id: `chunk-${i}`, score: +(0.92 - r * 0.045).toFixed(3) }))
  void query
  return {
    k: 10, exact: ids, passages: { ...passages, 'chunk-14': { title: 'RLHF reading notes · §4' }, 'chunk-17': { title: 'Scaling laws · p. 11' } },
    results: {
      flat: { hits: hits([1,2,3,4,5,6,7,8,9,10]), recall: 1, latency_ms: 0.41 },
      hnsw: { hits: hits([1,2,3,4,5,6,7,8,9,10]), recall: 1, latency_ms: 0.11 },
      ivfpq: { hits: hits([1,2,4,3,6,14,7,9,17,10]), recall: 0.8, latency_ms: 0.09, missed: ['chunk-5', 'chunk-8'] },
      ivfpq_rerank: { hits: hits([1,2,3,4,5,6,7,8,14,10]), recall: 0.9, latency_ms: 0.17, missed: ['chunk-9'] },
    },
  }
}
