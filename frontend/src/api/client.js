/**
 * API client for the agent server.
 *
 * Talks to :8000 directly. The old :5001 proxy tier was removed in Phase 2 --
 * it forwarded requests unchanged and could not carry an event stream, so the
 * UI was already bypassing it for anything that mattered.
 *
 * The server holds no session state. Everything a follow-up question needs --
 * the transcript so far, and the citation labels already handed out -- is sent
 * back with it. That is why `history` and `sources` are parameters here rather
 * than a conversation id: a second tab is a second conversation, and a server
 * restart loses nothing.
 */

const SERVER_URL = import.meta.env.VITE_SERVER_URL || 'http://localhost:8000';

/**
 * Ask a question and stream the agent's work back.
 *
 * Note the ordering changed in Phase 3: `onSources` used to fire exactly once,
 * before any text, because retrieval was a single fixed call. Now the model
 * decides what to fetch as it goes, so sources can arrive at any point and more
 * than once. Each call carries the complete list, not a delta.
 *
 * `onAnswer` replaced `onCitation` in Phase 8. Anthropic streamed each web
 * citation the moment it closed, so a `[n]` could be appended mid-sentence.
 * Gemini reports citations as byte ranges over the *finished* text of a turn,
 * so there is no honest way to place them while the text is still arriving:
 * the server relabels the turn once it ends and sends the whole thing back.
 * Replace the streamed text with it rather than appending.
 *
 * @param {string} query
 * `webSearch` is opt-in per question. The server default is off because the
 * web tier is billed per request, not per token; passing true here turns it on
 * for this one question without restarting anything.
 *
 * @param {{history?: {role: string, content: string}[],
 *          sources?: object[],
 *          webSearch?: boolean,
 *          onSources: (sources: object[]) => void,
 *          onToken: (text: string) => void,
 *          onToolCall?: (call: {name: string, where: string, input: object}) => void,
 *          onToolResult?: (result: {name: string, where: string, summary: object,
 *                                   duration_ms?: number}) => void,
 *          onAnswer?: (answer: {text: string}) => void,
 *          onDone?: (summary: object) => void,
 *          signal?: AbortSignal}} handlers
 * @returns {Promise<void>} resolves when the answer is complete
 */
export const streamQuery = async (
  query,
  {
    history = [],
    sources: priorSources = [],
    webSearch = false,
    onSources,
    onToken,
    onToolCall,
    onToolResult,
    onAnswer,
    onDone,
    signal,
  }
) => {
  const response = await fetch(`${SERVER_URL}/query/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      history,
      // Only the label and its identity go back -- not the passage text. The
      // model is not re-shown old passages; these exist so [3] keeps pointing
      // at the same thing four questions later.
      sources: priorSources.map(({ n, key, origin, title, url, location, score }) => ({
        n,
        key,
        origin,
        title,
        url,
        location,
        score,
      })),
      web_search: webSearch,
      timestamp: new Date().toISOString(),
      client_id: 'frontend_ui',
    }),
    signal,
  });

  if (!response.ok) {
    throw new Error(await describeFailure(response));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    const frames = buffer.split('\n\n');
    buffer = frames.pop();

    for (const frame of frames) {
      if (!frame.trim()) continue;

      let event = 'message';
      const dataLines = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;

      const payload = JSON.parse(dataLines.join('\n'));
      if (event === 'sources') onSources(payload.sources || []);
      else if (event === 'token') onToken(payload.text || '');
      else if (event === 'tool_call') onToolCall?.(payload);
      else if (event === 'tool_result') onToolResult?.(payload);
      else if (event === 'answer') onAnswer?.(payload);
      else if (event === 'error') throw new Error(payload.message);
      else if (event === 'done') {
        onSources(payload.sources || []);
        onDone?.(payload);
        return;
      }
    }
  }
};

/**
 * Turn a failed response into something worth showing a person.
 *
 * FastAPI's validation errors arrive as a list of objects; printing
 * "Server returned 422" instead loses the one fact the user needs, which is
 * which field was wrong.
 */
const describeFailure = async (response) => {
  const fallback = `Server returned ${response.status}`;
  try {
    const body = await response.json();
    const detail = body.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
    }
    return fallback;
  } catch {
    return fallback;
  }
};

/**
 * Upload files for the server to parse and index.
 *
 * The bytes go up untouched and the loaders run server-side. The browser used
 * to read files itself, which meant it could only accept formats JavaScript can
 * read as text -- a PDF would have arrived as mojibake, so PDFs were refused and
 * the user was pointed at a terminal command for the one thing they most wanted
 * to index. Parsing on the server also means a PDF keeps its page numbers.
 *
 * @param {File[]} files
 * @returns {Promise<object>}
 */
export const uploadFiles = async (files) => {
  const form = new FormData();
  for (const file of files) form.append('files', file, file.name);

  const response = await fetch(`${SERVER_URL}/upload`, { method: 'POST', body: form });
  if (!response.ok) throw new Error(await describeFailure(response));
  return response.json();
};

/**
 * Store documents that are already text.
 * @param {object[]} documents
 * @returns {Promise<object>}
 */
export const ingestDocuments = async (documents) => {
  const response = await fetch(`${SERVER_URL}/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ documents, client_id: 'frontend_ui' }),
  });
  if (!response.ok) throw new Error(await describeFailure(response));
  return response.json();
};

/**
 * What the collection actually holds.
 * @returns {Promise<object|null>} null if the knowledge base is unreachable
 */
export const fetchStats = async () => {
  try {
    const response = await fetch(`${SERVER_URL}/stats`);
    return response.ok ? response.json() : null;
  } catch {
    return null;
  }
};

/**
 * Tool schemas the server discovered over MCP.
 * @returns {Promise<{count: number, tools: object[]}>}
 */
export const listTools = async () => {
  const response = await fetch(`${SERVER_URL}/tools`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
};

/**
 * @returns {Promise<object|null>} server health, or null if unreachable
 */
export const checkHealth = async () => {
  try {
    const response = await fetch(`${SERVER_URL}/health`);
    return response.ok ? response.json() : null;
  } catch {
    return null;
  }
};

/**
 * Sweep the ANN indexes and return the benchmark rows.
 *
 * Slow on purpose -- it builds real HNSW and IVF-PQ indexes over the whole
 * corpus -- so it is called when the benchmark view is opened, not on a timer.
 * No AbortSignal: a sweep is short enough to let finish, and cancelling it
 * half-built would report meaningless partial numbers.
 *
 * @param {{k?: number, n_queries?: number, grid?: object}} options
 * @returns {Promise<object>} the sweep result, or {error} on an empty corpus
 */
export const runBenchmark = async ({ k = 10, n_queries = 200, grid } = {}) => {
  const response = await fetch(`${SERVER_URL}/ann/benchmark`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ k, n_queries, grid }),
  });
  if (!response.ok) throw new Error(await describeFailure(response));
  return response.json();
};

/**
 * Run one query through every index for the side-by-side view.
 *
 * @param {string} query
 * @param {{k?: number, hnsw?: object, ivfpq?: object}} options
 * @returns {Promise<object>} exact ids, each index's hits, and the passages
 */
export const compareIndexes = async (query, { k = 10, hnsw, ivfpq } = {}) => {
  const response = await fetch(`${SERVER_URL}/ann/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, k, hnsw, ivfpq }),
  });
  if (!response.ok) throw new Error(await describeFailure(response));
  return response.json();
};
