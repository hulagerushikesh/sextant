"""
The ANN indexes, graded against exact search.

These indexes are the whole point of the phase, and the one thing that makes an
approximate index trustworthy is a test that pins it to the exact answer. So
every test here builds a `FlatIndex` as ground truth and asks whether HNSW and
IVF-PQ recover enough of it. Recall floors, not exact matches: an approximate
index is *allowed* to miss, and a test that demanded perfection would either be
lying about what the index does or forcing parameters so high the approximation
is pointless.

The data is deliberately clustered. Uniform noise has no nearest-neighbour
structure to find, so every index scores badly on it and the test tells you
nothing; real embeddings cluster, and clustered fixtures are where recall
differences are legible.
"""

from __future__ import annotations

import numpy as np
import pytest

from tools.vector_db.ann import FlatIndex, HnswIndex, IvfPqIndex, RerankIndex
from tools.vector_db.ann.base import normalise, similarity
from tools.vector_db.ann.benchmark import Grid, compare_query, recall_at_k, sweep


def clustered(n: int, dim: int, clusters: int, seed: int, spread: float = 0.35):
    """`n` vectors drawn from `clusters` Gaussian blobs. Ids are 'c{i}'."""
    rng = np.random.default_rng(seed)
    centers = rng.standard_normal((clusters, dim)).astype("float32")
    labels = rng.integers(0, clusters, size=n)
    vecs = (centers[labels] + spread * rng.standard_normal((n, dim))).astype("float32")
    return [f"c{i}" for i in range(n)], vecs


def recall(index, flat, queries, k: int) -> float:
    truth = flat.search_many(queries, k)
    found = [index.search(q, k) for q in queries]
    return recall_at_k(found, truth, k)


@pytest.fixture
def corpus():
    return clustered(600, 128, clusters=12, seed=1)


@pytest.fixture
def queries():
    _, vecs = clustered(60, 128, clusters=12, seed=2)
    return vecs


class TestFlat:
    def test_a_vector_is_its_own_nearest_neighbour(self, corpus):
        ids, vecs = corpus
        flat = FlatIndex()
        flat.build(ids, vecs)
        top_id, top_score = flat.search(vecs[42], 1)[0]
        assert top_id == "c42"
        # Unit vectors: a vector against itself is cosine 1, up to float error.
        assert top_score == pytest.approx(1.0, abs=1e-5)

    def test_scores_are_cosine_similarities_in_range(self, corpus, queries):
        ids, vecs = corpus
        flat = FlatIndex()
        flat.build(ids, vecs)
        for _, score in flat.search(queries[0], 10):
            assert -1.0 <= score <= 1.0

    def test_results_are_ranked_best_first(self, corpus, queries):
        ids, vecs = corpus
        flat = FlatIndex()
        flat.build(ids, vecs)
        scores = [s for _, s in flat.search(queries[0], 10)]
        assert scores == sorted(scores, reverse=True)

    def test_batch_matches_single_on_identity(self, corpus, queries):
        ids, vecs = corpus
        flat = FlatIndex()
        flat.build(ids, vecs)
        single = [[i for i, _ in flat.search(q, 5)] for q in queries[:10]]
        batch = [[i for i, _ in hits] for hits in flat.search_many(queries[:10], 5)]
        # Float32 matmul blocking can perturb scores at 1e-7, but the *ranking*
        # must be identical -- the batch path is an optimisation, not a variant.
        assert single == batch

    def test_empty_corpus_returns_nothing(self):
        flat = FlatIndex()
        flat.build([], np.empty((0, 8), dtype="float32"))
        assert flat.search(np.ones(8, dtype="float32"), 5) == []

    def test_k_larger_than_corpus_is_clamped(self, corpus, queries):
        ids, vecs = corpus
        flat = FlatIndex()
        flat.build(ids, vecs)
        assert len(flat.search(queries[0], 10_000)) == len(ids)


class TestHnsw:
    def test_recall_is_high_on_clustered_data(self, corpus, queries):
        ids, vecs = corpus
        flat = FlatIndex()
        flat.build(ids, vecs)
        hnsw = HnswIndex(m=16, ef_construction=200, ef_search=100)
        hnsw.build(ids, vecs)
        # A well-tuned graph should recover nearly all of the true top-10.
        assert recall(hnsw, flat, queries, 10) >= 0.90

    def test_ef_search_trades_recall_for_work(self):
        # The whole reason efSearch is exposed: a bigger beam finds more. Proven
        # on harder near-uniform data, where low ef genuinely misses.
        ids, vecs = clustered(1500, 64, clusters=1, seed=7, spread=1.0)
        flat = FlatIndex()
        flat.build(ids, vecs)
        _, q = clustered(50, 64, clusters=1, seed=8, spread=1.0)
        hnsw = HnswIndex(m=8, ef_construction=100)
        hnsw.build(ids, vecs)
        hnsw.ef_search = 10
        low = recall(hnsw, flat, q, 10)
        hnsw.ef_search = 200
        high = recall(hnsw, flat, q, 10)
        assert high > low

    def test_build_is_deterministic_under_seed(self, corpus, queries):
        ids, vecs = corpus
        a = HnswIndex(m=16, ef_construction=100, seed=99)
        a.build(ids, vecs)
        b = HnswIndex(m=16, ef_construction=100, seed=99)
        b.build(ids, vecs)
        # Same seed, same graph, same answers -- a benchmark whose numbers drift
        # between identical runs teaches nothing.
        assert a.search(queries[0], 10) == b.search(queries[0], 10)

    def test_scores_are_on_the_cosine_scale(self, corpus, queries):
        ids, vecs = corpus
        hnsw = HnswIndex(ef_search=50)
        hnsw.build(ids, vecs)
        for _, score in hnsw.search(queries[0], 10):
            assert -1.0 <= score <= 1.0

    def test_a_single_vector_corpus(self):
        hnsw = HnswIndex()
        hnsw.build(["only"], np.ones((1, 16), dtype="float32"))
        hits = hnsw.search(np.ones(16, dtype="float32"), 5)
        assert [i for i, _ in hits] == ["only"]

    def test_empty_corpus_returns_nothing(self):
        hnsw = HnswIndex()
        hnsw.build([], np.empty((0, 16), dtype="float32"))
        assert hnsw.search(np.ones(16, dtype="float32"), 5) == []

    def test_memory_grows_with_M(self, corpus):
        ids, vecs = corpus
        small = HnswIndex(m=4, ef_construction=100)
        small.build(ids, vecs)
        large = HnswIndex(m=32, ef_construction=100)
        large.build(ids, vecs)
        # M is the degree of the graph, so more of it is more links is more bytes.
        assert large.stats().bytes > small.stats().bytes


class TestIvfPq:
    def test_recall_climbs_with_nprobe(self):
        ids, vecs = clustered(1500, 128, clusters=16, seed=3, spread=0.4)
        flat = FlatIndex()
        flat.build(ids, vecs)
        _, q = clustered(80, 128, clusters=16, seed=4, spread=0.4)
        ivf = IvfPqIndex(nlist=64, m=32, nprobe=1)
        ivf.build(ids, vecs)
        ivf.nprobe = 1
        low = recall(ivf, flat, q, 10)
        ivf.nprobe = 32
        high = recall(ivf, flat, q, 10)
        assert high > low

    def test_recall_ceiling_climbs_with_m(self):
        # More sub-quantizers means finer codes means the PQ approximation loses
        # less -- the memory/recall dial, and the reason m is a parameter.
        ids, vecs = clustered(1500, 128, clusters=16, seed=3, spread=0.4)
        flat = FlatIndex()
        flat.build(ids, vecs)
        _, q = clustered(80, 128, clusters=16, seed=4, spread=0.4)
        coarse = IvfPqIndex(nlist=64, m=8, nprobe=16)
        coarse.build(ids, vecs)
        fine = IvfPqIndex(nlist=64, m=64, nprobe=16)
        fine.build(ids, vecs)
        assert recall(fine, flat, q, 10) > recall(coarse, flat, q, 10)

    def test_codes_are_far_smaller_than_full_vectors(self):
        ids, vecs = clustered(4000, 128, clusters=16, seed=3)
        ivf = IvfPqIndex(nlist=64, m=16, nprobe=8)
        ivf.build(ids, vecs)
        stats = ivf.stats().as_json()
        # The per-vector code cost is m bytes (16), a fraction of 128 float32s
        # (512). The fixed codebook overhead is excluded from this figure.
        assert stats["amortised_bytes_per_vector"] == 16
        assert stats["amortised_bytes_per_vector"] < 512

    def test_overhead_is_reported_and_amortises(self):
        ids, vecs = clustered(4000, 128, clusters=16, seed=3)
        ivf = IvfPqIndex(nlist=64, m=16, nprobe=8)
        ivf.build(ids, vecs)
        stats = ivf.stats().as_json()
        # Codebooks and coarse centroids are a fixed cost, reported separately so
        # a tiny corpus does not look like IVF-PQ wastes memory.
        assert stats["overhead_bytes"] > 0
        assert stats["bytes_per_vector"] > stats["amortised_bytes_per_vector"]

    def test_a_dimension_m_does_not_divide_is_rejected(self):
        ids, vecs = clustered(100, 100, clusters=4, seed=3)
        ivf = IvfPqIndex(m=48)  # 48 does not divide 100
        with pytest.raises(ValueError, match="does not divide|must divide"):
            ivf.build(ids, vecs)

    def test_build_is_deterministic_under_seed(self):
        ids, vecs = clustered(500, 64, clusters=8, seed=5)
        _, q = clustered(1, 64, clusters=8, seed=6)
        a = IvfPqIndex(nlist=32, m=16, nprobe=8, seed=11)
        a.build(ids, vecs)
        b = IvfPqIndex(nlist=32, m=16, nprobe=8, seed=11)
        b.build(ids, vecs)
        assert a.search(q[0], 10) == b.search(q[0], 10)

    def test_scores_stay_in_cosine_range(self):
        ids, vecs = clustered(500, 64, clusters=8, seed=5)
        _, q = clustered(1, 64, clusters=8, seed=6)
        ivf = IvfPqIndex(nlist=32, m=16, nprobe=8)
        ivf.build(ids, vecs)
        for _, score in ivf.search(q[0], 10):
            # Reconstructed from quantized distances, so approximate -- but the
            # clip in `similarity` must keep it a valid similarity regardless.
            assert -1.0 <= score <= 1.0

    def test_empty_corpus_returns_nothing(self):
        ivf = IvfPqIndex(m=8)
        ivf.build([], np.empty((0, 64), dtype="float32"))
        assert ivf.search(np.ones(64, dtype="float32"), 5) == []


class TestSimilarityConversion:
    def test_identical_vectors_are_similarity_one(self):
        assert similarity(0.0) == pytest.approx(1.0)

    def test_opposite_vectors_are_similarity_minus_one(self):
        # Squared distance between unit opposites is 4.
        assert similarity(4.0) == pytest.approx(-1.0)

    def test_it_clips_float_overshoot(self):
        # float32 accumulation can produce a distance a hair below 0 or above 4;
        # the conversion must not report a similarity outside [-1, 1].
        assert similarity(-1e-6) <= 1.0
        assert similarity(4.0 + 1e-6) >= -1.0

    def test_normalise_leaves_zero_vectors_alone(self):
        matrix = np.array([[0.0, 0.0, 0.0], [3.0, 4.0, 0.0]], dtype="float32")
        out = normalise(matrix)
        # The zero row stays zero rather than becoming NaN; the real row is unit.
        assert np.allclose(out[0], 0.0)
        assert np.linalg.norm(out[1]) == pytest.approx(1.0, abs=1e-6)


class TestBenchmark:
    def test_sweep_grades_every_index_against_exact(self):
        ids, vecs = clustered(400, 96, clusters=8, seed=1)
        grid = Grid(
            hnsw_ef_search=(10, 80),
            ivf_m=16,
            ivf_nlist=16,
            ivf_nprobe=(1, 8),
        )
        out = sweep(ids, vecs, k=10, n_queries=50, grid=grid)
        names = [row["index"] for row in out["rows"]]
        assert "flat" in names and "hnsw" in names and "ivfpq" in names
        # Flat is ground truth, so it scores itself a perfect recall.
        flat_row = next(r for r in out["rows"] if r["index"] == "flat")
        assert flat_row["recall"] == pytest.approx(1.0)

    def test_sweep_notes_a_bad_ivf_dimension_rather_than_dropping_it(self):
        ids, vecs = clustered(200, 100, clusters=4, seed=1)
        out = sweep(ids, vecs, k=5, n_queries=20, grid=Grid(ivf_m=48))
        assert any("IVF-PQ skipped" in note for note in out["notes"])
        assert not any(r["index"] == "ivfpq" for r in out["rows"])

    def test_compare_lines_up_every_index_on_one_query(self):
        ids, vecs = clustered(300, 64, clusters=8, seed=1)
        out = compare_query(ids, vecs, vecs[10], k=5, ivfpq={"nlist": 16, "nprobe": 8, "m": 16})
        assert set(out["results"]) == {"flat", "hnsw", "ivfpq", "ivfpq_rerank"}
        # Flat is the yardstick: it misses nothing by definition.
        assert out["results"]["flat"]["missed"] == []
        assert out["results"]["flat"]["recall"] == pytest.approx(1.0)


class TestRerank:
    """Two-stage retrieval: an approximate shortlist, then an exact re-scoring.

    The contract that matters is recall recovery -- rerank must lift a base
    index's recall at a fixed nprobe, because gathering the right chunks into an
    oversized shortlist is the easy half and exact re-scoring fixes the order the
    quantized codes got wrong. The rest pins the honesty of the memory story.
    """

    def test_it_lifts_ivfpq_recall_at_fixed_nprobe(self):
        ids, vecs = clustered(1500, 128, clusters=16, seed=3, spread=0.4)
        flat = FlatIndex()
        flat.build(ids, vecs)
        _, q = clustered(80, 128, clusters=16, seed=4, spread=0.4)

        bare = IvfPqIndex(nlist=64, m=16, nprobe=4, seed=7)
        bare.build(ids, vecs)
        rer = RerankIndex(IvfPqIndex(nlist=64, m=16, nprobe=4, seed=7), oversample=8)
        rer.build(ids, vecs)

        # Same candidate generator, same nprobe -- the only difference is the
        # exact pass, and it must recover recall the quantization threw away.
        assert recall(rer, flat, q, 10) > recall(bare, flat, q, 10)

    def test_more_oversample_never_reduces_recall(self):
        ids, vecs = clustered(1200, 128, clusters=16, seed=3, spread=0.4)
        flat = FlatIndex()
        flat.build(ids, vecs)
        _, q = clustered(60, 128, clusters=16, seed=4, spread=0.4)

        narrow = RerankIndex(IvfPqIndex(nlist=64, m=16, nprobe=4, seed=7), oversample=2)
        narrow.build(ids, vecs)
        wide = RerankIndex(IvfPqIndex(nlist=64, m=16, nprobe=4, seed=7), oversample=16)
        wide.build(ids, vecs)
        # A wider shortlist can only add candidates the exact pass may promote,
        # never remove ones it already had.
        assert recall(wide, flat, q, 10) >= recall(narrow, flat, q, 10)

    def test_returned_scores_are_exact_cosines(self):
        ids, vecs = clustered(600, 128, clusters=12, seed=1)
        flat = FlatIndex()
        flat.build(ids, vecs)
        rer = RerankIndex(IvfPqIndex(nlist=32, m=16, nprobe=8, seed=7), oversample=8)
        rer.build(ids, vecs)

        exact = dict(flat.search(vecs[10], 40))
        for cid, score in rer.search(vecs[10], 10):
            # The re-scoring is exact, so a rerank score must match flat's cosine
            # for the same chunk -- not the approximate PQ reconstruction.
            assert score == pytest.approx(exact[cid], abs=1e-4)

    def test_stats_split_hot_codes_from_cold_vectors(self):
        ids, vecs = clustered(2000, 128, clusters=16, seed=3)
        rer = RerankIndex(IvfPqIndex(nlist=64, m=16, nprobe=8, seed=7), oversample=4)
        rer.build(ids, vecs)
        stats = rer.stats().as_json()

        assert stats["name"] == "ivfpq_rerank"
        # The hot tier is the PQ codes (m bytes); the full amortised cost adds the
        # 128 float32 vectors this harness keeps resident. Hot is the number that
        # survives when production moves the vectors to disk.
        assert stats["params"]["hot_bytes_per_vector"] == 16
        assert stats["amortised_bytes_per_vector"] > stats["params"]["hot_bytes_per_vector"]

    def test_it_wraps_any_base_index(self):
        ids, vecs = clustered(400, 64, clusters=8, seed=1)
        flat = FlatIndex()
        flat.build(ids, vecs)
        _, q = clustered(30, 64, clusters=8, seed=2)
        # Generic over the interface: wrapping HNSW must still return exact-ordered
        # top-k over its shortlist.
        rer = RerankIndex(HnswIndex(m=16, ef_construction=200, ef_search=50, seed=7))
        rer.build(ids, vecs)
        assert recall(rer, flat, q, 10) >= 0.9

    def test_empty_corpus_returns_nothing(self):
        rer = RerankIndex(IvfPqIndex(m=8))
        rer.build([], np.empty((0, 64), dtype="float32"))
        assert rer.search(np.ones(64, dtype="float32"), 5) == []

    def test_rejects_a_bad_oversample(self):
        with pytest.raises(ValueError, match="oversample"):
            RerankIndex(IvfPqIndex(m=16), oversample=0)

    def test_sweep_includes_a_rerank_curve_above_bare_ivfpq(self):
        ids, vecs = clustered(800, 96, clusters=10, seed=1, spread=0.4)
        grid = Grid(
            hnsw_ef_search=(20,),
            ivf_m=16,
            ivf_nlist=32,
            ivf_nprobe=(2, 8),
            rerank_oversample=8,
        )
        out = sweep(ids, vecs, k=10, n_queries=60, grid=grid)
        names = [row["index"] for row in out["rows"]]
        assert "ivfpq_rerank" in names

        # At the top nprobe, rerank's recall should be at least the bare index's.
        def recall_at(index_name, nprobe):
            return next(
                r["recall"]
                for r in out["rows"]
                if r["index"] == index_name and r["params"]["nprobe"] == nprobe
            )

        assert recall_at("ivfpq_rerank", 8) >= recall_at("ivfpq", 8)


class TestFaissReference:
    """The C++ reference indexes. Skipped entirely where faiss is not installed.

    These are not the thing under test -- they are the yardstick the hand-written
    indexes are measured against. So the tests here check the *interface* holds
    (same contract, same cosine scale, recovers recall on clustered data) rather
    than asserting latency, which is the whole point but is environment-dependent
    and not a thing a unit test should pin.
    """

    def test_faiss_hnsw_recovers_recall(self):
        pytest.importorskip("faiss")
        from tools.vector_db.ann import FaissHnswIndex

        ids, vecs = clustered(600, 128, clusters=12, seed=1)
        flat = FlatIndex()
        flat.build(ids, vecs)
        _, q = clustered(60, 128, clusters=12, seed=2)
        fh = FaissHnswIndex(m=16, ef_construction=200, ef_search=100)
        fh.build(ids, vecs)
        assert recall(fh, flat, q, 10) >= 0.90
        for _, score in fh.search(q[0], 10):
            assert -1.0 <= score <= 1.0

    def test_faiss_ivfpq_builds_and_scores_in_range(self):
        pytest.importorskip("faiss")
        from tools.vector_db.ann import FaissIvfPqIndex

        ids, vecs = clustered(1500, 128, clusters=16, seed=3, spread=0.4)
        fi = FaissIvfPqIndex(nlist=64, nprobe=8, m=16)
        fi.build(ids, vecs)
        hits = fi.search(vecs[0], 10)
        assert hits  # returns something
        for _, score in hits:
            assert -1.0 <= score <= 1.0

    def test_faiss_indexes_handle_empty_corpus(self):
        pytest.importorskip("faiss")
        from tools.vector_db.ann import FaissHnswIndex, FaissIvfPqIndex

        for index in (FaissHnswIndex(), FaissIvfPqIndex(m=8)):
            index.build([], np.empty((0, 64), dtype="float32"))
            assert index.search(np.ones(64, dtype="float32"), 5) == []

    def test_sweep_includes_faiss_reference_rows(self):
        pytest.importorskip("faiss")
        ids, vecs = clustered(800, 96, clusters=10, seed=1, spread=0.4)
        grid = Grid(
            hnsw_ef_search=(20,),
            ivf_m=16,
            ivf_nlist=32,
            ivf_nprobe=(4,),
        )
        out = sweep(ids, vecs, k=10, n_queries=50, grid=grid)
        names = {row["index"] for row in out["rows"]}
        assert "faiss_hnsw" in names and "faiss_ivfpq" in names
        for row in out["rows"]:
            if row["index"].startswith("faiss_"):
                assert row["params"].get("impl") == "faiss"

    def test_faiss_can_be_turned_off(self):
        # No faiss required: the flag must omit the rows regardless of install.
        ids, vecs = clustered(400, 96, clusters=8, seed=1)
        grid = Grid(
            hnsw_ef_search=(20,),
            ivf_m=16,
            ivf_nlist=16,
            ivf_nprobe=(4,),
            include_faiss=False,
        )
        out = sweep(ids, vecs, k=10, n_queries=40, grid=grid)
        assert not any(r["index"].startswith("faiss_") for r in out["rows"])
