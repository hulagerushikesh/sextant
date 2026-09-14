# API Setup

## The only key this system needs

```bash
# .env at the repo root
ANTHROPIC_API_KEY=sk-ant-...
```

Get one from <https://console.anthropic.com/settings/keys>.

Without it, ingestion and retrieval still work — you can add documents and the
knowledge base will search them — but no answer is generated, because there is no
model to write one. The server says so explicitly rather than failing quietly.

## Web search needs no key of its own

Web search is Anthropic's server-side `web_search_20260209` tool. It runs on
Anthropic's infrastructure, is billed through the same key, and returns citations
the API produces itself. There is nothing else to configure.

## Can I use a Gemini / OpenAI key instead?

Not by renaming the variable. There is no provider abstraction here — every call
to a model goes through the Anthropic SDK, and the parts that make this system
worth having are the parts that are most Anthropic-specific:

| What depends on it | Where |
| --- | --- |
| The agent loop: `messages.stream()`, `tool_use` / `server_tool_use` blocks, `stop_reason`, `pause_turn` resumption | `mcp_server/agent.py` |
| Server-side web search (`web_search_20260209`) — no second key, citations returned by the API | `mcp_server/agent.py` |
| Streamed citation events, which is where web `[n]` labels come from | `mcp_server/agent.py` |
| Structured grading via `messages.parse` | `eval/judge.py` |
| Per-token cost accounting at Anthropic's rates | `mcp_server/pricing.py` |
| The whole agent test suite, which replays real SDK objects through the real loop | `tests/fakes.py` |

Everything *below* generation is provider-independent and would survive a port
untouched: the MCP server, chunking, hybrid retrieval, reranking, the eval
harness and its metrics. The work is confined to the generation layer — but that
is the layer with the most behaviour in it, and the server-side web search tier
has no like-for-like replacement.

## If you are looking for BRAVE_API_KEY, SERPAPI_KEY or EXA_API_KEY

They are gone. This guide used to describe a hand-rolled web-search client that
tried Brave, then SerpAPI, then Exa. Phase 2 deleted it. Nothing in the codebase
reads those three variables any more:

```bash
grep -rn "BRAVE_API_KEY\|SERPAPI_KEY\|EXA_API_KEY" --include='*.py' --include='*.js' .
# no matches
```

Setting them has no effect. If they are still in your `.env`, delete the lines —
and if any of them held a real value, revoke it at the provider, because it was
committed to a working tree that has been shared.

Why the replacement is better: one credential instead of three, citations built
in rather than reconstructed from snippets, and results filtered before they
reach the context window. The old client is in git history if it is ever wanted
back.
