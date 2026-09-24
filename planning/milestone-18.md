# Milestone 18 — production catches up, then 0.8

Milestone 17 closed the retrieval questions this corpus can answer. Five
of the last six candidates were measured and decided against; the two that
shipped (per-document cap, `kb_list`) are in the code and in the baselines.
What is left is not a retrieval question at all: **the deployed store was
built on 2026-09-15**, before table-aware chunking, before the PyMuPDF
extractor and before the cap — so three milestones of measured work are in
the image and not in the answers. That is item 1.

The other two are debts with the numbers already taken: `--summaries` has
been opt-in only because it cost dense recall, and the cap removed that
cost; and the `agenticrag-*` command aliases were promised for 0.8.

Same protocol where there is something to measure. Items 2 and 3 are
decisions on numbers already in `learning/`, not new experiments, and say
so — a decision note is not a measurement note.

## 1 · Re-ingest the deployed store — ₹0 API, ≈₹1 of VM time

The VM's store: 22 documents, 61 chunks, written 2026-09-15. Since then
`learning/table-chunking.md` (survey rerank hit@1 0.818 → 0.909),
`learning/pdf-extraction.md` (lines rebuilt from span baselines) and
`learning/candidate-cap.md` (dense recall@5 +0.02 to +0.07) all changed
what a chunk is or which chunks come back. The embedder is local, so
re-ingest costs no API at all; the cost is the VM being up.

**Not an experiment.** No hypothesis, no rule — it is making production
run what the repo says it runs. What it needs:

- The VM up: re-reserve the IP, `add-access-config`, re-add the Cloudflare
  A record grey-cloud, `deploy.sh HOST start`. ≈₹5.6/hour.
- `docker compose exec api sextant-ingest /data/corpus -r` after a backup
  of `/data/chroma_db`, because a re-ingest rewrites it.
- Drop `upload:Rushikesh_Hulage_Resume_Rubrik` (9 chunks, a personal
  résumé that has no business in a demo corpus) while the store is open.
- Verify: `kb_stats` document and chunk counts before and after, one live
  query with a citation.

Wait on: an explicit go-ahead on the ₹, since it turns the meter on.

## 2 · `--summaries` as the upload default — ₹0 to decide, $0.003/document at upload

**The decision, not a hypothesis.** `learning/summary-chunks.md` shipped
summaries opt-in for one reason: 21 overview chunks crowded the five
graded slots and handbook dense recall@5 fell 0.970 → 0.900. The cap
answered exactly that — `learning/candidate-cap.md` measures the
with-summaries store at **0.900 → 0.973**, which is what the no-summaries
store scores, with rerank hit@1 unchanged (0.964) on every store. The
argument against the default no longer exists; that note already says so.

What the default buys, from the same two notes: global rerank hit@1
**0.6 → 1.0** on both stores, local rerank hit@1 +0.02 on both, and a
`kb_list` listing that reads the model's overview per document instead of
the first 240 characters of its opening.

**Change.** `sextant-ingest` summarises by default when a key resolves:

- tri-state flag — `--summaries` forces it on, `--no-summaries` forces it
  off, neither reads the key;
- `.env` is loaded whether or not the flag was passed, so "a key resolves"
  means the same thing as it does for the agent;
- no key and no explicit `--summaries` → one printed line saying overviews
  were skipped and why, then a normal ingest. **Ingestion without a key
  keeps working**, which is the property the module's own docstring
  promises;
- a model failure mid-run degrades the same way when the default chose
  summaries, and still aborts when the flag asked for them. Asking and not
  getting is an error; not asking and not getting is a line of output.

**Rule.** Nothing retrieval-side moves, so no baseline changes and
`sextant-eval --check` must stay green untouched. It ships if the gate is
green and both paths are covered by tests: no key → ingest succeeds with
zero overviews; key → overviews stored, and `--no-summaries` beats the key.
If either path needs a `try` around a call site outside `ingest_cli`, the
default is more invasive than it is worth and stays opt-in.

## 3 · 0.8 — drop the `agenticrag-*` command aliases — ₹0

Four console scripts (`agenticrag-kb|ingest|eval|judge`) kept since the
rename in milestone 15 so a muscle-memory command would not break. Nothing
in the repo calls them except two historical lines in `learning/README.md`
and `planning/milestone-15.md`.

**Change.** Remove the four entries from `pyproject.toml`, update the
learning references to the `sextant-*` names (the milestone-15 lines are
history and stay as written), bump to `0.8.0`.

**Not removed: the `AGENTICRAG_` environment prefix.** `tools/settings.py`
reads `SEXTANT_*` first and falls back, and the deployed box's `.env`
still uses the legacy names. Removing the fallback silently drops the
deployment's daily budget cap to its default. It goes when the box's
`.env` is rewritten, which is item 1's trip, not this one.

## Also in this milestone

- `planning/README.md` was two milestones stale (320 tests, M17 "in
  progress", a repo-public decision that happened on 2026-09-20).
  Refreshed with this milestone.

## Not in this milestone

- **Per-user upload / multi-corpus** — still a design question, not a
  scheduled one. `category` is a free-text label today; making it mean a
  person is an auth model and a storage decision, and nothing forces it
  yet.
- **Request-level index tier** — needs a corpus past ~25k chunks to mean
  anything (`learning/ivfpq-100k.md`). The store is 1,602.
