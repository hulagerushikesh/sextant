# The interface

> Moved here from the README on 2026-11-12 so the front page could open with a
> quickstart. The text is unchanged apart from link paths.

The frontend is not a demo page for the API; it is where the two things this
system claims — that retrieval is real, and that every claim is traceable — are
either visible or unproven.

**Citations are controls, not decoration.** Every `[3]` in an answer opens the
passage the model actually read. A label with nothing behind it renders struck
through in red rather than as plain text: that is the dangling citation
`sextant/eval/judge.py` counts, and it should be as visible to a reader as it is to the
metrics. The passage shipped to the browser is the whole chunk — the old
400-character excerpt was sized for whole documents and outlived the reason for
it by three phases.

**The renderer has five constructs and no markdown library.** Headings, bullets,
numbered lists, paragraphs and GFM tables, because `[3]` is a citation here and a
broken link to every markdown parser. The table rule (`|---|:--:|`) is what makes
a table a table rather than prose containing a pipe — which also makes it the
streaming test: a header row that has arrived without its rule renders as a
paragraph until the rule follows it, so a half-streamed table never flickers as a
broken one.

**The trace reports outcomes, not just calls.** A search that returns nothing is
labelled *nothing found*, in a different colour, next to the search that follows
it. Before this the loop's most interesting behaviour was invisible: rephrasing
after an empty search looked exactly like searching twice for no reason.

**Conversations are real.** A follow-up carries the transcript back to the model,
so "and how are detections assigned?" is a follow-up rather than a fresh
question. What is *not* replayed is the tool transcript — the passages retrieved
in earlier turns stay behind. Replaying them would resend every passage ever
retrieved on every question; the model searches again instead, which is the
cheap half. See [`sextant/mcp_server/conversation.py`](../sextant/mcp_server/conversation.py).

**Citation labels survive the round trip.** `[3]` means the same passage in the
fifth answer as in the first. The server keeps no session state, so the client
sends back the labels it holds and `SourceRegistry.restore` resumes numbering
after them. Without it, one transcript ends up containing two different `[1]`s
and inline citations cannot resolve at all.

**Uploads are parsed server-side.** Drop a PDF into the browser and it keeps its
page numbers. The first version of this panel read files in JavaScript, which
silently limited it to formats a browser can read as text — so PDFs, the format
people actually have, were refused with a note to go and run a terminal command.
`POST /upload` takes the bytes, runs the same loaders `sextant-ingest` uses,
and hands the knowledge base text plus a list of page and section spans. It is
data over the protocol, not a path: a `kb_ingest_file` tool would give every
client that mounts the server the ability to read arbitrary local files.

**And they can be taken back out, by the person who put them in.** The delete
has to happen where the store is, which is the knowledge-base subprocess — so
`kb_forget` is an MCP tool, and this server is published. An unconditional tool
would hand every client that mounts it the ability to delete a corpus, so it is
registered only when the launcher asks (`SEXTANT_REMOVAL_TOOL`, set for the
child this project starts and not by a Claude Desktop config). The authorisation
stays in the parent, where the owner is known: the same allow-list `/ingest`
crosses, because re-using an id already replaced a document and a write is a
delete first.

**Conversations live in the browser.** localStorage, thirty of them, evicting
oldest-first when the quota complains. The trade is stated rather than hidden:
clearing site data loses them and they do not follow you to another machine.
Right for a tool you run yourself, wrong for a hosted product.

**`/health` distinguishes "reachable" from "can answer".** Retrieval works
without an API key and generation does not, so `model_configured` is reported
separately and the UI shows a banner instead of an empty answer box. This exists
because a stubbed model was mistaken for the real one for an afternoon: the
corpus was live, the sources were real, and the prose was hardcoded.
