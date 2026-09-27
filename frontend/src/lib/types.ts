/** Shapes the agent server sends. Mirrors mcp_server/main.py + agent.py. */

export type Origin = 'knowledge_base' | 'web'

export interface Source {
  n: number
  key: string
  origin: Origin
  title: string
  url?: string
  location?: string
  score?: number
  text?: string
}

export interface Usage {
  input_tokens: number
  output_tokens: number
  grounded_requests: number
  cost_usd: number
}

export interface ToolSummary {
  status?: 'ok' | 'empty' | 'error'
  error?: string
  hits?: number
  top_score?: number
  documents?: number
  chunks?: number
}

export interface TraceStep {
  name: string
  where: 'mcp' | 'google'
  input?: { query?: string; [k: string]: unknown }
  summary?: ToolSummary
  duration_ms?: number
}

export interface Message {
  role: 'user' | 'assistant'
  text: string
  trace?: TraceStep[]
  usage?: Usage
  turns?: number
  truncated?: boolean
  stopped?: boolean
  error?: string | null
}

export interface Conversation {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: Message[]
  sources: Source[]
}

export interface Budget {
  enabled: boolean
  budget_usd: number
  spent_usd: number
  remaining_usd: number
}

export interface Health {
  status: 'healthy' | 'degraded'
  mcp_connected: boolean
  model_configured: boolean
  supported_uploads: string[]
  web_search_enabled: boolean
  budget: Budget
  mcp_error?: string | null
  tools_discovered: string[]
  tools_offered_to_model: string[]
}

export interface Stats {
  documents: number
  collection_size: number
  embedding_model: string
  reranker: string
  chunking?: { target_tokens: number; overlap_tokens: number }
  storage_path?: string
}

export interface DoneFrame {
  sources: Source[]
  usage: Usage
  turns: number
  truncated?: boolean
}

export interface StreamHandlers {
  history?: { role: string; content: string }[]
  sources?: Source[]
  webSearch?: boolean
  signal?: AbortSignal
  onSources: (sources: Source[]) => void
  onToken: (text: string) => void
  onToolCall?: (call: TraceStep) => void
  onToolResult?: (r: { name: string; where: string; summary: ToolSummary; duration_ms?: number }) => void
  onAnswer?: (a: { text: string }) => void
  onDone?: (d: DoneFrame) => void
}

/* --- Index Lab ----------------------------------------------------------- */

export type IndexName = 'flat' | 'hnsw' | 'ivfpq' | 'ivfpq_rerank' | 'faiss_hnsw' | 'faiss_ivfpq'

export interface SweepRow {
  index: IndexName
  params: Record<string, number | string>
  recall: number
  latency_ms: { p50: number; p90: number; p99: number }
  build_seconds: number
  amortised_bytes_per_vector: number
  bytes: number
}

export interface SweepResult {
  corpus: { vectors: number; dim: number }
  queries: number
  k: number
  rows: SweepRow[]
  notes?: string[]
  error?: string
}

export interface CompareHit { id: string; score: number }
export interface CompareResult {
  k: number
  exact: string[]
  results: Partial<Record<IndexName, { hits: CompareHit[]; recall: number; latency_ms: number; missed?: string[] }>>
  passages: Record<string, { title?: string; text?: string }>
  error?: string
}
