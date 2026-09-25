"""
Knowledge-base storage and retrieval.

A persistent ChromaDB collection of *chunks*, searched by dense vectors and BM25
together, fused, then reranked. `tools/vector_db/server.py` fronts this over MCP;
nothing else should import it directly.

Every public method is async, and every one of them hands its real work to a
thread. That is not decoration: embedding, reranking, the BM25 scan and ChromaDB
are all synchronous CPU or disk work, and calling them straight from a coroutine
pins the event loop for the whole duration. Measured before this change, a 10 ms
heartbeat ticked *zero* times during 558 ms of searching -- meaning the MCP
server could not have answered another request and the agent server could not
have streamed a token while any query was in flight.

Two things this file refuses to do, both learned the hard way here.

It has no fallback path. An earlier version dropped to difflib string ratios over
seven hard-coded fixtures whenever the embedding stack failed to import, so a
broken install returned plausible-looking results instead of an error.

And it never reports a number without saying what produced it. The scores this
class used to return were computed as `1 - distance` against an l2 collection and
labelled "similarity", which they were not. Every hit now carries `scored_by`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from tools import settings
from tools.vector_db.chunking import (
    CHUNK_TOKENS_ENV,
    chunk_text,
    configured_chunk_sizes,
)
from tools.vector_db.embeddings import (
    EMBEDDER_ENV,
    LOCAL_MODEL,
    EmbeddingsUnavailable,
    get_embedder,
)
from tools.vector_db.loaders import LoadedDocument, Locator, load_path
from tools.vector_db.retrieval import (
    BM25Index,
    CrossEncoderReranker,
    Fused,
    RerankerUnavailable,
    reciprocal_rank_fusion,
)
from tools.vector_db.summaries import SUMMARY_KIND, summary_chunk_id, summary_text

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "documents"

# Where the on-disk collection lives: <repo root>/chroma_db, unless overridden.
# The override exists so the evaluation harness and CI can build a throwaway
# corpus without touching whatever the user has actually indexed.
DEFAULT_PERSIST_DIR = Path(__file__).resolve().parents[2] / "chroma_db"
PERSIST_DIR_ENV = settings.env_name("CHROMA_DIR")


def persist_dir() -> Path:
    """The collection directory for this process, honouring the override."""
    override = settings.getenv("CHROMA_DIR")
    return Path(override).expanduser() if override else DEFAULT_PERSIST_DIR

# Cosine, not Chroma's l2 default. Dense scores are computed as `1 - distance`,
# which is only a similarity if the distance is cosine: under l2 the distance is
# unbounded, so `1 - distance` runs negative for anything mildly unrelated and is
# not comparable across queries.
DISTANCE_SPACE = "cosine"

# How many chunks each retriever proposes before fusion. Wider than the caller's
# `limit` on purpose -- fusion and reranking can only reorder what they are given,
# so the shortlist is where recall is won or lost.
CANDIDATES = 30

# Which index answers the *dense* half of retrieval. "chroma" is ChromaDB's own
# vector search -- the default, and what every deployment has always used. The
# rest swap in one of the hand-written indexes from `tools.vector_db.ann`, so the
# HNSW-vs-IVF-PQ comparison stops being a benchmark you read and becomes a switch
# that changes what the live pipeline actually retrieves. Lexical (BM25), fusion
# and reranking are unchanged either way; only the dense candidate source moves.
ANN_BACKEND_ENV = settings.env_name("ANN_INDEX")
ANN_BACKENDS = ("chroma", "flat", "hnsw", "ivfpq", "ivfpq_rerank")

# How many fused candidates the cross-encoder actually scores. It reads every
# pair, so this is the cost knob.
RERANK_DEPTH = 25

# Measured against the Phase 5 golden set, not guessed. On 60 questions, a floor
# of 0.01 blocks 8 of 10 unanswerable queries and costs 2 of 50 answerable ones;
# 0.1 blocks the same 8 and costs 3; 0.3 costs 8 for no further benefit. So the
# floor is deliberately small -- it removes the near-zero tail, and nothing more.
#
# It cannot do better than 8 of 10, and that is not a tuning failure. The two
# survivors ask for a fact that is absent from a passage genuinely about that
# subject ("what does error code TRK-150 mean?" against the error-code
# reference, 0.9730). No score separates "this passage is on topic" from "this
# passage contains the answer"; only reading it does, which is the model's job
# and is what the abstention rule in the agent prompt is for.
#
# Re-derive with: sextant-eval
DEFAULT_MIN_SCORE = 0.01

# At most this many chunks of one document in the returned list, with the
# chunks it cuts backfilling the remaining slots in score order -- so a corpus
# of one document gets exactly what it would have without the cap. Milestone 16
# lost dense recall@5 three times to the same crowding (a found document's
# siblings filling the slots a second document needed); `0` turns it off.
# Measured in `learning/candidate-cap.md`.
MAX_PER_DOCUMENT_ENV = settings.env_name("MAX_PER_DOCUMENT")
MAX_PER_DOCUMENT = int(settings.getenv("MAX_PER_DOCUMENT", "2") or 0)

# Below DEFAULT_MIN_SCORE the cross-encoder has said "nothing here", and its
# order among those chunks is noise -- ties at 0.000 broken by fusion rank.
# Dense similarity still carries signal there (q48 in `learning/hyde.md`: both
# documents in the dense top-7, one dropped by the cross-encoder). "dense"
# orders the sub-floor chunks by their cosine, keyed below the floor so none
# crosses it and the reported score is untouched; "none" keeps the
# cross-encoder's order. Only callers that lower `min_score` ever see the
# difference; the product floor removes those chunks either way. Measured in
# `learning/subfloor-order.md`: handbook rerank recall@5 0.964 -> 0.982,
# survey unchanged, nothing above the floor moves.
SUBFLOOR_ORDER_ENV = settings.env_name("SUBFLOOR_ORDER")
SUBFLOOR_ORDER = settings.getenv("SUBFLOOR_ORDER", "dense") or "dense"

# What a cross-encoder search returns when *nothing* clears `min_score`. "none"
# returns the empty list: the floor is the abstention signal and the caller
# (the agent) rephrases or declines. "dense" returns the chunks the dense pass
# found, ordered by cosine and reported as such -- `scored_by: cosine`, the
# cosine as the score, `below_floor: true` on the result -- so the reader knows
# these are nearest-by-embedding, not relevant. The cosines are not calibrated
# across questions (an unanswerable question's nearest chunk can sit above an
# answerable one's), so the flag is the only thing separating the two; whether
# a model reading them can tell is what `learning/floor-fallback.md` measures.
FLOOR_FALLBACK_ENV = settings.env_name("FLOOR_FALLBACK")
FLOOR_FALLBACK = settings.getenv("FLOOR_FALLBACK", "none") or "none"

# A document over the cap keeps its slot unless the next document waiting
# scores at least this fraction of it. Dense siblings that crowd a list score
# within a few percent of the chunk they push out; the chunks a hard cap let in
# under the cross-encoder scored a thirtieth of the page they displaced.
MIN_DISPLACE_RATIO = 0.5

# Retrieval modes. Only "rerank" is meant for production use; the other three
# exist because `eval/harness.py` has to be able to ablate the pipeline, and a
# claim that reranking helps is worth nothing without the run that shows it.
RetrievalMode = Literal["dense", "lexical", "rrf", "rerank"]
RETRIEVAL_MODES: tuple[RetrievalMode, ...] = ("dense", "lexical", "rrf", "rerank")
DEFAULT_MODE: RetrievalMode = "rerank"


def _locators(doc: dict[str, Any], length: int) -> list[Locator]:
    """Where in `doc` its pages or sections begin.

    Two callers, two levels of detail. `kb_ingest` from a person pasting text
    knows at most one page number for the whole thing. The upload endpoint has
    already parsed the file and knows exactly where every page starts, so it
    sends the full list -- which is what lets a PDF dropped into the browser
    cite "p. 14" the way a `sextant-ingest` one does.

    Note this takes structured locators, not a path. A `kb_ingest_file` tool
    would be simpler and would hand every client that mounts this server the
    ability to read arbitrary files on the machine; parsing stays on the caller's
    side of the protocol for that reason.
    """
    supplied = doc.get("locators")
    if isinstance(supplied, list) and supplied:
        found = []
        for item in supplied:
            if not isinstance(item, dict):
                continue
            kind, label = item.get("kind"), item.get("label")
            if kind not in ("page", "section", "table") or label is None:
                continue
            start = int(item.get("start", 0))
            end = int(item.get("end", length))
            # Clamp rather than reject: a locator running past the text it
            # describes should cost precision, not the whole document.
            found.append(Locator(kind, label, max(0, start), min(length, end)))
        return found

    page = doc.get("page")
    # Without a locator list, a caller-supplied page applies to the whole
    # document -- the best that can be done without knowing where pages break.
    return [Locator("page", page, 0, length)] if page else []


class KnowledgeBaseUnavailable(RuntimeError):
    """Raised when the store cannot be opened. Never swallowed."""


def configured_ann_backend() -> str:
    """The dense backend for this process, validated. Defaults to 'chroma'.

    Read once at construction. An unknown value is a configuration mistake, not
    something to paper over with a silent fallback -- the whole reason to set it
    is to change what retrieval does, so a typo that quietly kept the default
    would be the worst outcome.
    """
    name = (settings.getenv("ANN_INDEX", "chroma") or "chroma").strip().lower()
    if name not in ANN_BACKENDS:
        raise KnowledgeBaseUnavailable(
            f"{ANN_BACKEND_ENV}={name!r} is not a known dense backend; "
            f"choose one of: {', '.join(ANN_BACKENDS)}"
        )
    return name


class KnowledgeBase:
    """A persistent collection of document chunks with hybrid retrieval."""

    def __init__(self, collection_name: str = DEFAULT_COLLECTION) -> None:
        self.collection_name = collection_name

        try:
            import chromadb
        except ImportError as e:
            raise KnowledgeBaseUnavailable(
                f"chromadb is not importable ({e}). Run: pip install -e '.[dev]'"
            ) from e

        try:
            self.embedder = get_embedder()
        except EmbeddingsUnavailable as e:
            raise KnowledgeBaseUnavailable(str(e)) from e

        self.persist_dir = persist_dir()
        try:
            self.client = chromadb.PersistentClient(path=str(self.persist_dir))
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                # cast: chroma types this as a TypedDict the plain literal does
                # not match, though it is exactly what the API documents.
                configuration=cast(Any, {"hnsw": {"space": DISTANCE_SPACE}}),
                metadata={"description": "Agentic RAG document collection"},
            )
        except Exception as e:
            raise KnowledgeBaseUnavailable(
                f"Could not open the ChromaDB collection at {self.persist_dir}: {e}"
            ) from e

        # get_or_create silently keeps an existing collection's space, so a store
        # created before the cosine switch would still be l2 and would keep
        # reporting scores that aren't similarities. Fail loudly instead.
        space = self._configured_space()
        if space is not None and space != DISTANCE_SPACE:
            raise KnowledgeBaseUnavailable(
                f"The collection at {self.persist_dir} was built with '{space}' distance, but "
                "this code reports dense scores as cosine similarity. Delete "
                f"{self.persist_dir} and re-ingest."
            )
        self._check_embedding_model()

        # Chunk sizes are a setting so a corpus can be re-ingested at another
        # size without a code change; the embedder's window is still the wall.
        self.target_tokens, self.overlap_tokens = configured_chunk_sizes()
        if self.target_tokens > self.embedder.max_tokens:
            raise KnowledgeBaseUnavailable(
                f"{CHUNK_TOKENS_ENV}={self.target_tokens} exceeds the embedder's window "
                f"({self.embedder.name}: {self.embedder.max_tokens} tokens); the tail of "
                "every chunk would be embedded as nothing."
            )

        self.reranker = CrossEncoderReranker()
        self._bm25: BM25Index | None = None
        self._corpus: dict[str, tuple[str, dict[str, Any]]] = {}

        # Which index answers the dense half of retrieval. Validated here so a
        # bad value fails at startup, not on the first query.
        self._ann_backend = configured_ann_backend()
        # The hand-written dense index, built lazily from the whole corpus and
        # cached until a write invalidates it. Stays None on the default path.
        self._ann_index: Any = None
        self._ann_lock = threading.Lock()

        # Reads run concurrently across worker threads, so the lexical index
        # must be built at most once no matter how many arrive together.
        self._index_lock = threading.Lock()
        # Writes are serialised: two ingests interleaving would race on the
        # index invalidation and leave the lexical index missing a document.
        self._write_lock = asyncio.Lock()

        logger.info(
            "Knowledge base ready: collection=%s chunks=%d embedder=%s path=%s",
            collection_name,
            self.collection.count(),
            self.embedder.name,
            self.persist_dir,
        )

    def _check_embedding_model(self) -> None:
        """Refuse a store whose vectors came from a different embedding model.

        Two models can share a dimension (MiniLM and bge-small are both 384-d),
        so a mismatch does not error -- every query just scores against
        vectors from another space and retrieval quietly degrades. The model
        name is stamped on the collection when it is first written to; a
        store from before the stamp existed is assumed to be MiniLM, the only
        model there was.
        """
        stored = (self.collection.metadata or {}).get("embedding_model")
        if stored is None:
            if self.collection.count() == 0:
                return  # stamped on first write, when the model is certain
            stored = LOCAL_MODEL
            self._stamp_embedding_model(stored)
        if stored != self.embedder.name:
            raise KnowledgeBaseUnavailable(
                f"The collection at {self.persist_dir} was embedded with '{stored}', but "
                f"this process is configured for '{self.embedder.name}'. Point "
                f"{EMBEDDER_ENV} at the model that built the store, or re-ingest into "
                "a new directory."
            )

    def _stamp_embedding_model(self, name: str) -> None:
        metadata = dict(self.collection.metadata or {})
        metadata["embedding_model"] = name
        self.collection.modify(metadata=metadata)

    def _configured_space(self) -> str | None:
        """Read the collection's actual distance space, or None if unreported."""
        config = getattr(self.collection, "configuration_json", None)
        if not isinstance(config, dict):
            return None
        hnsw = config.get("hnsw")
        return hnsw.get("space") if isinstance(hnsw, dict) else None

    # -- lexical index -----------------------------------------------------

    def _ensure_index(self) -> BM25Index:
        """Build the BM25 index and text cache from the collection, once.

        Held in memory rather than persisted: the chunks already live in Chroma,
        and a second on-disk index is one more thing that can drift out of step
        with the first. The cost is that the corpus text is resident -- fine at
        this scale, and the thing to revisit when it stops being fine.
        """
        # Read into a local at each step: the attribute can change under us
        # between the two checks, which is the whole point of the double check.
        index = self._bm25
        if index is not None:
            return index

        with self._index_lock:
            index = self._bm25  # another thread may have built it while we waited
            return index if index is not None else self._build_index()

    def _build_index(self) -> BM25Index:
        stored = self.collection.get(include=["documents", "metadatas"])
        ids = stored.get("ids") or []
        documents = stored.get("documents") or []
        metadatas = stored.get("metadatas") or []

        self._corpus = {
            chunk_id: (text, dict(meta or {}))
            for chunk_id, text, meta in zip(ids, documents, metadatas, strict=True)
        }
        self._bm25 = BM25Index(list(ids), list(documents))
        logger.info("Lexical index built over %d chunks", len(self._bm25))
        return self._bm25

    def _invalidate_index(self) -> None:
        self._bm25 = None
        self._corpus = {}
        # The dense ANN cache is built from the corpus too, so a write makes it
        # stale in the same breath as the lexical index. Rebuilt on next query.
        self._ann_index = None

    # -- retrieval ---------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 5,
        min_score: float = DEFAULT_MIN_SCORE,
        mode: str = DEFAULT_MODE,
    ) -> dict[str, Any]:
        """Rank chunks against `query`. See RETRIEVAL_MODES for the ablations."""
        if mode not in RETRIEVAL_MODES:
            raise ValueError(f"mode must be one of {RETRIEVAL_MODES}, got {mode!r}")
        return await asyncio.to_thread(self.search_sync, query, limit, min_score, mode)

    def search_sync(
        self,
        query: str,
        limit: int = 5,
        min_score: float = DEFAULT_MIN_SCORE,
        mode: str = DEFAULT_MODE,
    ) -> dict[str, Any]:
        """The synchronous body of `search`, for callers already on a thread."""
        start = time.time()
        results, scored_by, below_floor = self._search(query, limit, min_score, mode)

        return {
            "success": True,
            "query": query,
            "results": results,
            "total_found": len(results),
            "mode": mode,
            "scored_by": scored_by,
            "min_score": min_score,
            "below_floor": below_floor,
            "processing_time": time.time() - start,
            "collection": self.collection_name,
            "collection_size": self.collection.count(),
            "timestamp": datetime.now().isoformat(),
        }

    def _search(
        self, query: str, limit: int, min_score: float, mode: str
    ) -> tuple[list[dict[str, Any]], str, bool]:
        """Hits, what scored them, and whether they are the sub-floor fallback."""
        if self.collection.count() == 0:
            return [], "none", False

        # Always built: even a dense-only search needs the chunk text cache to
        # assemble its hits.
        index = self._ensure_index()

        dense_ids, dense_scores = ([], {}) if mode == "lexical" else self._dense(query)
        lexical = [] if mode == "dense" else index.search(query, CANDIDATES)

        candidates, scores, scored_by = self._rank(query, mode, dense_ids, dense_scores, lexical)
        if not candidates:
            return [], "none", False

        # `keys` orders; `scores` is what a hit reports and what the floor
        # tests. They differ only under the floor, and only when asked to.
        keys = list(scores)
        if scored_by == "cross-encoder" and SUBFLOOR_ORDER == "dense":
            keys = [
                score
                if score >= DEFAULT_MIN_SCORE
                else DEFAULT_MIN_SCORE * max(0.0, dense_scores.get(candidates[i].id, 0.0))
                for i, score in enumerate(scores)
            ]
        order = sorted(range(len(candidates)), key=lambda i: keys[i], reverse=True)
        # An RRF score is a rank artefact with no meaning on a 0-1 scale, so
        # thresholding it would repeat exactly the mistake this project
        # already made once with l2 distances.
        below_floor = False
        if scored_by == "cross-encoder":
            kept = [i for i in order if scores[i] >= min_score]
            if not kept and min_score > 0 and FLOOR_FALLBACK == "dense":
                # Nothing cleared the floor. Hand back what the dense pass
                # found, in its own order and with its own score, and say so:
                # the cross-encoder's verdict was "no", and the hit must not
                # carry a cross-encoder score that pretends otherwise.
                below_floor = True
                scored_by = "cosine"
                scores = [dense_scores.get(c.id, 0.0) for c in candidates]
                keys = scores
                order = sorted(
                    (i for i in range(len(candidates)) if scores[i] > 0.0),
                    key=lambda i: keys[i],
                    reverse=True,
                )
            else:
                order = kept

        # Only where a score is a relevance and not a rank: the guard inside
        # compares magnitudes, and an RRF or BM25 score has none to compare.
        if scored_by in ("cosine", "cross-encoder"):
            chosen = self._diversify(order, [c.id for c in candidates], keys, limit)
        else:
            chosen = order[:limit]
        return [
            self._hit(candidates[i], scores[i], scored_by, dense_scores.get(candidates[i].id))
            for i in chosen
        ], scored_by, below_floor

    def _diversify(
        self, order: list[int], ids: list[str], scores: list[float], limit: int
    ) -> list[int]:
        """The first `limit` of `order`, holding each document to MAX_PER_DOCUMENT.

        Two passes: take while the document is under the cap, then fill what is
        left from the ones that were skipped, still in score order. The second
        pass is what makes the cap safe -- it can only reorder, never return
        fewer hits than the uncapped list would. A chunk over the cap is only
        skipped when the document that would take its place is competitive
        (MIN_DISPLACE_RATIO); a cap that hands a slot to a chunk scoring zero
        is not diversity, it is noise.
        """
        cap = MAX_PER_DOCUMENT
        if cap <= 0:
            return order[:limit]
        document = {
            i: self._corpus.get(ids[i], ("", {}))[1].get("document_id", ids[i]) for i in order
        }
        chosen: list[int] = []
        skipped: list[int] = []
        per_document: dict[str, int] = {}
        for position, i in enumerate(order):
            if len(chosen) >= limit:
                break
            if per_document.get(document[i], 0) >= cap:
                challenger = next(
                    (j for j in order[position + 1 :] if per_document.get(document[j], 0) < cap),
                    None,
                )
                if challenger is not None and scores[challenger] >= MIN_DISPLACE_RATIO * scores[i]:
                    skipped.append(i)
                    continue
            per_document[document[i]] = per_document.get(document[i], 0) + 1
            chosen.append(i)
        chosen.extend(skipped[: limit - len(chosen)])
        return chosen

    def _rank(
        self,
        query: str,
        mode: str,
        dense_ids: list[str],
        dense_scores: dict[str, float],
        lexical: list[tuple[str, float]],
    ) -> tuple[list[Fused], list[float], str]:
        """Produce the candidate list and its scores for the requested mode."""
        if mode == "dense":
            candidates = [
                Fused(id=i, rrf_score=dense_scores[i], dense_rank=rank)
                for rank, i in enumerate(dense_ids, start=1)
            ]
            return candidates, [dense_scores[c.id] for c in candidates], "cosine"

        if mode == "lexical":
            candidates = [
                Fused(id=i, rrf_score=score, lexical_rank=rank)
                for rank, (i, score) in enumerate(lexical, start=1)
            ]
            return candidates, [c.rrf_score for c in candidates], "bm25"

        fused = reciprocal_rank_fusion(dense_ids, [i for i, _ in lexical])[:RERANK_DEPTH]
        if mode == "rrf" or not fused:
            return fused, [f.rrf_score for f in fused], "rrf"

        try:
            passages = [self._corpus.get(f.id, ("", {}))[0] for f in fused]
            return fused, self.reranker.score(query, passages), "cross-encoder"
        except RerankerUnavailable as e:
            # Not a silent fallback: every hit reports `scored_by`, so the
            # caller can see that these are fusion ranks and not relevance.
            logger.warning("Reranker unavailable, returning fused ranks: %s", e)
            return fused, [f.rrf_score for f in fused], "rrf"

    def _dense(self, query: str) -> tuple[list[str], dict[str, float]]:
        """Vector search: ids in rank order, plus their cosine similarities."""
        embedding = self.embedder.encode_query(query)
        if self._ann_backend != "chroma":
            return self._ann_dense(embedding)
        raw = self.collection.query(
            query_embeddings=cast(Any, [embedding]),
            n_results=min(CANDIDATES, self.collection.count()),
            include=["distances"],
        )
        ids = (raw.get("ids") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        # strict: Chroma returns these as parallel lists; a length mismatch is a
        # bug in the driver, not something to silently truncate.
        return list(ids), {i: 1 - d for i, d in zip(ids, distances, strict=True)}

    def _ann_dense(self, embedding: Any) -> tuple[list[str], dict[str, float]]:
        """The dense half through a hand-written index instead of Chroma.

        Returns exactly what the Chroma path does -- ids in rank order and their
        cosine similarities on the same 0-1 scale -- so fusion and reranking
        downstream cannot tell which backend produced the shortlist. The index is
        exact (`flat`) or approximate (`hnsw`/`ivfpq`/`ivfpq_rerank`) per config.
        """
        count = self.collection.count()
        if count == 0:
            return [], {}
        index = self._ensure_ann_index()
        hits = index.search(embedding, min(CANDIDATES, count))
        ids = [chunk_id for chunk_id, _ in hits]
        return ids, {chunk_id: float(sim) for chunk_id, sim in hits}

    def _ensure_ann_index(self) -> Any:
        """Build the dense ANN index once, then reuse it. Double-checked."""
        index = self._ann_index
        if index is not None:
            return index
        with self._ann_lock:
            if self._ann_index is not None:
                return self._ann_index
            self._ann_index = self._build_ann_index()
            return self._ann_index

    def _build_ann_index(self) -> Any:
        """Construct the configured index over the whole corpus.

        Deferred import so the ANN package never loads on the default Chroma
        path. The embeddings already exist in the store -- built from them, not a
        re-encode, so this index searches exactly what Chroma does.
        """
        from tools.vector_db.ann import INDEX_TYPES
        from tools.vector_db.ann.ivfpq import IvfPqIndex
        from tools.vector_db.ann.rerank import RerankIndex

        stored = self.collection.get(include=["embeddings"])
        ids = list(stored.get("ids") or [])
        embeddings = stored.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            ids, embeddings = [], []

        if self._ann_backend == "ivfpq_rerank":
            index: Any = RerankIndex(IvfPqIndex())
        else:
            index = INDEX_TYPES[self._ann_backend]()
        index.build(ids, embeddings)
        logger.info(
            "Dense ANN index (%s) built over %d chunks", self._ann_backend, len(ids)
        )
        return index

    def _hit(
        self, fused: Fused, score: float, scored_by: str, dense_score: float | None
    ) -> dict[str, Any]:
        text, meta = self._corpus.get(fused.id, ("", {}))
        return {
            "id": fused.id,
            "document_id": meta.get("document_id", fused.id),
            "title": meta.get("title", "Untitled document"),
            "content": text,
            "source": meta.get("source", "unknown"),
            "page": meta.get("page"),
            "section": meta.get("section"),
            "category": meta.get("category", "general"),
            "score": round(float(score), 4),
            "scored_by": scored_by,
            "dense_score": round(dense_score, 4) if dense_score is not None else None,
            "matched": fused.matched,
            "chunk_index": meta.get("chunk_index", 0),
        }

    # -- ingestion ---------------------------------------------------------

    async def add_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        """Chunk, embed and store documents. Ingested content survives a restart."""
        async with self._write_lock:
            return await asyncio.to_thread(self._add_documents_sync, documents)

    def _add_documents_sync(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        if not documents:
            return self._ingest_failure("No documents provided")

        loaded: list[LoadedDocument] = []
        for i, doc in enumerate(documents):
            content = doc.get("content")
            if not content:
                return self._ingest_failure(f"Every document needs a 'content' field (item {i})")

            loaded.append(
                LoadedDocument(
                    doc_id=str(doc.get("id") or f"doc_{i}"),
                    title=doc.get("title") or "Untitled",
                    text=content,
                    source=doc.get("source") or "unknown",
                    category=doc.get("category") or "general",
                    locators=_locators(doc, len(content)),
                )
            )
        return self._store(loaded)

    async def add_file(self, path: str, category: str = "general") -> dict[str, Any]:
        """Load a PDF, Markdown or text file and store its chunks."""
        async with self._write_lock:
            return await asyncio.to_thread(self._add_file_sync, path, category)

    async def remove_document(self, document_id: str) -> dict[str, Any]:
        """Delete a document and every chunk of it, overview included.

        A corpus is something a person curates, so it needs a way back out:
        a document ingested by mistake, one that should never have been in a
        shared store, one whose source file is gone. Like ingestion this is a
        command and never an MCP tool -- the model is offered read tools only,
        and "search my notes" must not carry "delete my notes" with it.
        """
        async with self._write_lock:
            return await asyncio.to_thread(self._remove_document_sync, document_id)

    def _remove_document_sync(self, document_id: str) -> dict[str, Any]:
        stored = self.collection.get(where={"document_id": document_id})
        ids = stored.get("ids") or []
        if not ids:
            return {
                "success": False,
                "message": f"No document {document_id!r} in the collection",
                "chunks_removed": 0,
                "collection_size": self.collection.count(),
            }
        self.collection.delete(ids=list(ids))
        self._invalidate_index()
        return {
            "success": True,
            "message": f"Removed {document_id} and its {len(ids)} chunk(s)",
            "chunks_removed": len(ids),
            "collection_size": self.collection.count(),
        }

    def _add_file_sync(self, path: str, category: str) -> dict[str, Any]:
        # Parsing a 144-page PDF is seconds of blocking work before any
        # embedding starts, so the load belongs on the thread too.
        return self._store([load_path(path, category=category)])

    async def load_file(self, path: str, category: str = "general") -> LoadedDocument:
        """Load a file without storing it -- for callers that want to read it
        first, like `sextant-ingest --summaries`, which sends the text to a
        model before `add_document` stores it with the summary."""
        return await asyncio.to_thread(load_path, path, category=category)

    async def add_document(
        self, document: LoadedDocument, summary: str | None = None
    ) -> dict[str, Any]:
        """Store a loaded document, with an optional model-written summary.

        The summary becomes one more chunk of the document (`kind: summary`,
        id `<doc>#summary`) in the same collection, ranked by the same three
        stages as every other chunk. See `summaries.py` for why.
        """
        async with self._write_lock:
            return await asyncio.to_thread(
                self._store, [document], {document.doc_id: summary} if summary else {}
            )

    def _store(
        self, documents: list[LoadedDocument], summaries: dict[str, str] | None = None
    ) -> dict[str, Any]:
        ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        summaries = summaries or {}

        for document in documents:
            chunks = chunk_text(
                document.text,
                self.embedder.count_tokens,
                target_tokens=self.target_tokens,
                overlap_tokens=self.overlap_tokens,
                tables=document.tables,
            )
            if not chunks:
                logger.warning("%s produced no chunks -- empty after stripping", document.doc_id)
                continue

            for chunk in chunks:
                ids.append(f"{document.doc_id}#{chunk.index}")
                texts.append(chunk.text)
                meta: dict[str, Any] = {
                    "document_id": document.doc_id,
                    "title": document.title,
                    "source": document.source,
                    "category": document.category,
                    "chunk_index": chunk.index,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "tokens": chunk.tokens,
                    "kind": chunk.kind,
                }
                # A chunk is attributed to wherever it *starts*, so one that runs
                # across a page break cites the page a reader would turn to.
                meta.update(document.locate(chunk.char_start))
                # Chroma rejects None-valued metadata outright.
                metadatas.append({k: v for k, v in meta.items() if v is not None})

            summary = summaries.get(document.doc_id)
            if summary:
                text = summary_text(document.title, summary)
                ids.append(summary_chunk_id(document.doc_id))
                texts.append(text)
                metadatas.append(
                    {
                        "document_id": document.doc_id,
                        "title": document.title,
                        "source": document.source,
                        "category": document.category,
                        # After the last real chunk, so anything that orders a
                        # document's chunks puts the overview at the end rather
                        # than in the middle of the text.
                        "chunk_index": len(chunks),
                        "char_start": 0,
                        "char_end": 0,
                        "tokens": self.embedder.count_tokens(text),
                        "kind": SUMMARY_KIND,
                        "section": "Overview",
                    }
                )

        if not ids:
            return self._ingest_failure("Nothing to store: all documents were empty")

        try:
            if (self.collection.metadata or {}).get("embedding_model") is None:
                self._stamp_embedding_model(self.embedder.name)
            embeddings = self.embedder.encode(texts)
            # Clear what each document holds now, before writing what it holds
            # next. An upsert alone replaces chunk ids one for one, and the
            # number of chunks a document makes is not stable: change the
            # chunker, the target size or the file and a document that used to
            # make eleven chunks makes one, leaving ten chunks of deleted text
            # in the index -- still embedded, still searchable, and ranking
            # ahead of the document that replaced them. Only the documents
            # actually being written are touched.
            for doc_id in {meta["document_id"] for meta in metadatas}:
                existing = self.collection.get(where={"document_id": doc_id}).get("ids") or []
                stale = [chunk_id for chunk_id in existing if chunk_id not in set(ids)]
                if stale:
                    logger.info("Replacing %s: dropping %d stale chunk(s)", doc_id, len(stale))
                    self.collection.delete(ids=stale)
            # upsert, not add: re-ingesting the same id replaces it rather than
            # raising, which is what you want when re-running an ingest script.
            self.collection.upsert(
                embeddings=cast(Any, embeddings),
                documents=texts,
                metadatas=cast(Any, metadatas),
                ids=ids,
            )
        except Exception as e:
            logger.exception("Ingestion failed")
            return self._ingest_failure(f"Error adding documents: {e}")

        self._invalidate_index()
        return {
            "success": True,
            "message": (
                f"Stored {len(documents)} document(s) as {len(ids)} chunk(s)"
            ),
            "documents_added": len(documents),
            "chunks_added": len(ids),
            "collection_size": self.collection.count(),
        }

    def _ingest_failure(self, message: str) -> dict[str, Any]:
        return {
            "success": False,
            "message": message,
            "documents_added": 0,
            "chunks_added": 0,
            "collection_size": self.collection.count(),
        }

    # -- introspection -----------------------------------------------------

    async def get_document_by_id(self, chunk_id: str) -> dict[str, Any] | None:
        """Fetch one stored chunk by id, or None if it isn't there."""
        return await asyncio.to_thread(self._get_document_sync, chunk_id)

    def _get_document_sync(self, chunk_id: str) -> dict[str, Any] | None:
        result = self.collection.get(ids=[chunk_id], include=["documents", "metadatas"])
        if not result.get("ids"):
            return None

        meta = (result.get("metadatas") or [{}])[0] or {}
        return {
            "id": chunk_id,
            "document_id": meta.get("document_id", chunk_id),
            "title": meta.get("title", "Untitled document"),
            "content": (result.get("documents") or [""])[0],
            "source": meta.get("source", "unknown"),
            "page": meta.get("page"),
            "section": meta.get("section"),
            "category": meta.get("category", "general"),
        }

    # -- ANN benchmark -----------------------------------------------------

    def _all_vectors(self) -> tuple[list[str], Any]:
        """Every stored chunk id and its embedding, straight from Chroma.

        The vectors already exist -- they were computed at ingestion and are what
        `_dense` queries against. The ANN indexes are built from these, not from
        a re-embedding: re-encoding the corpus would measure the embedder, not
        the index, and would let the benchmark drift from what production
        actually searches.
        """
        stored = self.collection.get(include=["embeddings"])
        ids = stored.get("ids") or []
        embeddings = stored.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            return list(ids), []
        return list(ids), embeddings

    async def ann_benchmark(
        self, k: int = 10, n_queries: int = 200, grid: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Sweep HNSW and IVF-PQ against exact search over the live corpus."""
        return await asyncio.to_thread(self._ann_benchmark_sync, k, n_queries, grid)

    def _ann_benchmark_sync(
        self, k: int, n_queries: int, grid: dict[str, Any] | None
    ) -> dict[str, Any]:
        # Imported here, not at module top: the ANN package pulls in nothing the
        # MCP server needs on the ingest path, and a store that is only written
        # to should not pay to import three index implementations.
        from tools.vector_db.ann.benchmark import Grid, sweep

        ids, vectors = self._all_vectors()
        if len(ids) < 2:
            return {
                "error": "The corpus has fewer than two chunks; there is nothing to "
                "compare an index against. Ingest some documents first.",
                "corpus": {"vectors": len(ids)},
            }
        return sweep(ids, vectors, k=k, n_queries=n_queries, grid=Grid(**(grid or {})))

    async def ann_compare(
        self,
        query: str,
        k: int = 10,
        hnsw: dict[str, Any] | None = None,
        ivfpq: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one query through every index, side by side against exact search."""
        return await asyncio.to_thread(self._ann_compare_sync, query, k, hnsw, ivfpq)

    def _ann_compare_sync(
        self,
        query: str,
        k: int,
        hnsw: dict[str, Any] | None,
        ivfpq: dict[str, Any] | None,
    ) -> dict[str, Any]:
        from tools.vector_db.ann.benchmark import compare_query

        ids, vectors = self._all_vectors()
        if len(ids) < 2:
            return {
                "error": "The corpus has fewer than two chunks; there is nothing to "
                "compare. Ingest some documents first.",
                "corpus": {"vectors": len(ids)},
            }

        # The query is embedded with the same encoder the corpus was, so the
        # comparison runs in the space the vectors actually live in.
        query_vector = self.embedder.encode_query(query)
        result = compare_query(ids, vectors, query_vector, k=k, hnsw=hnsw, ivfpq=ivfpq)

        # Attach the human-readable title and text to each id so the frontend can
        # show which passage an index found or missed, not just an opaque id.
        index = self._ensure_index()  # noqa: F841 -- ensures _corpus is populated
        wanted = set(result["exact"])
        for res in result["results"].values():
            for hit in res["hits"]:
                wanted.add(hit["id"])
        result["passages"] = {
            cid: {
                "title": (self._corpus.get(cid, ("", {}))[1] or {}).get(
                    "title", "Untitled document"
                ),
                "excerpt": self._corpus.get(cid, ("", {}))[0][:200],
            }
            for cid in wanted
        }
        return result

    async def list_documents(self) -> dict[str, Any]:
        """Every document in the collection, with what it is about.

        "What do my documents cover?" is a listing, not a retrieval: no chunk
        answers it, at any level of a summary tree (`learning/summary-chunks.md`).
        Each entry carries the model-written overview when the document was
        ingested with `--summaries`, and its opening text either way -- for a
        short document the first chunk already says what it is.
        """
        return await asyncio.to_thread(self._list_documents_sync)

    # How much of a document's opening travels with its listing. Enough for a
    # title and first heading or two; a listing of twenty documents should
    # still fit in one tool result.
    LEAD_CHARS = 240

    def _list_documents_sync(self) -> dict[str, Any]:
        self._ensure_index()
        by_document: dict[str, dict[str, Any]] = {}
        for chunk_id, (text, meta) in self._corpus.items():
            doc_id = meta.get("document_id", chunk_id)
            entry = by_document.setdefault(
                doc_id,
                {
                    "document_id": doc_id,
                    "title": meta.get("title", "Untitled document"),
                    "source": meta.get("source", "unknown"),
                    "category": meta.get("category", "general"),
                    "chunks": 0,
                    "pages": None,
                    "overview": None,
                    "lead": None,
                    "_first": None,
                },
            )
            if meta.get("kind") == SUMMARY_KIND:
                entry["overview"] = text.split("\n", 1)[-1].strip() if "\n" in text else text
                continue
            entry["chunks"] += 1
            page = meta.get("page")
            if isinstance(page, int):
                entry["pages"] = max(entry["pages"] or 0, page)
            index = meta.get("chunk_index", 0)
            if entry["_first"] is None or index < entry["_first"]:
                entry["_first"] = index
                lead = " ".join(text.split())
                cut = len(lead) > self.LEAD_CHARS
                entry["lead"] = lead[: self.LEAD_CHARS] + ("…" if cut else "")
        documents = sorted(by_document.values(), key=lambda d: (d["category"], d["title"].lower()))
        for entry in documents:
            entry.pop("_first")
        return {"documents": documents, "count": len(documents)}

    async def health_check(self) -> dict[str, Any]:
        """Report what the store actually contains."""
        return await asyncio.to_thread(self._health_check_sync)

    def _health_check_sync(self) -> dict[str, Any]:
        stored = self.collection.get(include=["metadatas"])
        metadatas = [meta or {} for meta in (stored.get("metadatas") or [])]
        documents = {meta.get("document_id") for meta in metadatas}
        summaries = sum(1 for meta in metadatas if meta.get("kind") == SUMMARY_KIND)
        return {
            "status": "healthy",
            "database": "chromadb",
            "embedding_model": self.embedder.name,
            "embedding_max_tokens": self.embedder.max_tokens,
            "chunking": {
                "target_tokens": self.target_tokens,
                "overlap_tokens": self.overlap_tokens,
            },
            "retrieval": "dense + BM25, fused with RRF, reranked by cross-encoder",
            "dense_backend": self._ann_backend,
            "reranker": self.reranker.model_name,
            "collection": self.collection_name,
            "collection_size": self.collection.count(),
            "documents": len(documents - {None}),
            # Documents that carry a model-written overview chunk. Zero unless
            # ingested with `--summaries`.
            "summaries": summaries,
            "persist_dir": str(self.persist_dir),
            "timestamp": datetime.now().isoformat(),
        }
