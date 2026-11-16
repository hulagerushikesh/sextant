"""The public-set scorer computes BEIR's measure, worked out by hand."""

from __future__ import annotations

import hashlib
import json
import math
import zipfile
from pathlib import Path

import pytest

from sextant.eval import public_sets
from sextant.eval.public_sets import (
    documents_in_order,
    graded_ndcg_at_k,
    iter_corpus,
    load_qrels,
    load_queries,
    recall_at,
)


class TestGradedNDCG:
    def test_perfect_order_is_one(self):
        assert graded_ndcg_at_k(["a", "b"], {"a": 2, "b": 1}) == pytest.approx(1.0)

    def test_grades_count_linearly_not_exponentially(self):
        # Swapped: DCG = 1 + 2/log2(3); ideal = 2 + 1/log2(3). pytrec_eval's gain is the grade.
        expected = (1 + 2 / math.log2(3)) / (2 + 1 / math.log2(3))
        assert graded_ndcg_at_k(["b", "a"], {"a": 2, "b": 1}) == pytest.approx(expected)

    def test_unretrieved_judged_documents_lower_the_score(self):
        # One of two relevant found, at rank 1: 1 / (1 + 1/log2(3)).
        assert graded_ndcg_at_k(["a", "x"], {"a": 1, "b": 1}) == pytest.approx(
            1 / (1 + 1 / math.log2(3))
        )

    def test_a_document_judged_zero_is_not_relevant(self):
        assert graded_ndcg_at_k(["z"], {"z": 0, "a": 1}) == 0.0
        assert graded_ndcg_at_k(["a"], {"z": 0, "a": 1}) == pytest.approx(1.0)

    def test_only_the_top_k_count(self):
        late = [f"n{i}" for i in range(10)] + ["a"]
        assert graded_ndcg_at_k(late, {"a": 1}, k=10) == 0.0


class TestRecallAndCollapse:
    def test_recall_counts_documents_in_the_top_k(self):
        assert recall_at(["a", "x", "b"], {"a": 1, "b": 2, "c": 1}, k=2) == pytest.approx(1 / 3)

    def test_chunks_collapse_to_documents_in_first_seen_order(self):
        assert documents_in_order(["a", "a", "b", "a", "c"]) == ["a", "b", "c"]


class TestTheFilesAreReadAsBEIRWritesThem:
    def test_qrels_need_the_header(self, tmp_path: Path):
        path = tmp_path / "test.tsv"
        path.write_text("query-id\tcorpus-id\tscore\nq1\td1\t2\nq1\td2\t0\n")
        assert load_qrels(path) == {"q1": {"d1": 2.0, "d2": 0.0}}
        path.write_text("q1\td1\t2\n")
        with pytest.raises(ValueError, match="header"):
            load_qrels(path)

    def test_a_judged_question_without_text_is_refused(self, tmp_path: Path):
        path = tmp_path / "queries.jsonl"
        path.write_text(json.dumps({"_id": "q1", "text": "why"}) + "\n")
        assert load_queries(path, {"q1"}) == {"q1": "why"}
        with pytest.raises(ValueError, match="no text"):
            load_queries(path, {"q1", "q2"})

    def test_title_and_text_are_joined_and_empty_documents_show(self, tmp_path: Path):
        path = tmp_path / "corpus.jsonl"
        rows = [
            {"_id": "1", "title": "T", "text": "body"},
            {"_id": "2", "title": "", "text": "only body"},
            {"_id": "3", "title": "", "text": ""},
        ]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        docs = list(iter_corpus(path))
        assert [d["content"] for d in docs] == ["T\n\nbody", "only body", ""]
        assert docs[1]["title"] == "2"


def _archive(tmp_path: Path, members: dict[str, str]) -> Path:
    path = tmp_path / "source" / "tiny.zip"
    path.parent.mkdir()
    with zipfile.ZipFile(path, "w") as bundle:
        for name, text in members.items():
            bundle.writestr(name, text)
    return path


def _publish(monkeypatch, archive: Path) -> str:
    """Make `tiny` a known set whose published checksum is this archive's."""
    md5 = hashlib.md5(archive.read_bytes(), usedforsecurity=False).hexdigest()
    monkeypatch.setitem(public_sets.ARCHIVES, "tiny", (md5, archive.stat().st_size))
    return archive.parent.as_uri() + "/{name}.zip"


TINY = {"tiny/corpus.jsonl": "{}\n", "tiny/queries.jsonl": "", "tiny/qrels/test.tsv": ""}


class TestOneCommandFetchesASet:
    def test_the_archive_is_fetched_checked_and_unzipped(self, tmp_path, monkeypatch):
        url = _publish(monkeypatch, _archive(tmp_path, TINY))
        folder = public_sets.fetch("tiny", tmp_path / "cache", url=url)
        assert folder == tmp_path / "cache" / "tiny"
        assert (folder / "corpus.jsonl").read_text() == "{}\n"

    def test_a_cached_archive_is_not_fetched_again(self, tmp_path, monkeypatch):
        url = _publish(monkeypatch, _archive(tmp_path, TINY))
        public_sets.fetch("tiny", tmp_path / "cache", url=url)
        (tmp_path / "source" / "tiny.zip").unlink()  # a second fetch would fail
        assert public_sets.fetch("tiny", tmp_path / "cache", url=url).is_dir()

    def test_an_archive_without_the_published_checksum_is_refused(self, tmp_path, monkeypatch):
        url = _publish(monkeypatch, _archive(tmp_path, TINY))
        monkeypatch.setitem(public_sets.ARCHIVES, "tiny", ("0" * 32, 1))
        with pytest.raises(ValueError, match="refused"):
            public_sets.fetch("tiny", tmp_path / "cache", url=url)
        assert not list((tmp_path / "cache").iterdir()), "nothing of it may be kept"

    def test_a_member_outside_the_folder_is_refused(self, tmp_path, monkeypatch):
        url = _publish(monkeypatch, _archive(tmp_path, {"../escaped.txt": "x"}))
        with pytest.raises(ValueError, match="outside"):
            public_sets.fetch("tiny", tmp_path / "cache", url=url)
        assert not (tmp_path / "escaped.txt").exists()

    def test_an_unknown_set_is_refused_before_anything_is_fetched(self, tmp_path):
        with pytest.raises(ValueError, match="unknown set"):
            public_sets.fetch("msmarco", tmp_path)

    def test_every_committed_set_has_a_published_checksum(self):
        committed = json.loads(public_sets.COMMITTED.read_text())["sets"]
        assert set(committed) == set(public_sets.ARCHIVES)


def _run(**ndcg: float) -> dict:
    return {
        "questions": 10,
        "embedding_model": "m",
        "chunk_tokens": 200,
        "candidates_per_stage": 30,
        "rerank_depth": 25,
        "max_per_document": 2,
        "modes": {mode: {"ndcg@10": value} for mode, value in ndcg.items()},
    }


class TestTheCheckAgainstTheCommittedRun:
    def test_a_rerun_within_the_tolerance_reproduces(self):
        assert public_sets.compare(_run(dense=0.304), _run(dense=0.300)) == []

    def test_a_stage_further_off_fails_and_says_which(self):
        got = public_sets.compare(_run(dense=0.3, rerank=0.36), _run(dense=0.3, rerank=0.35))
        assert got == ["rerank: nDCG@10 0.3600, committed 0.3500"]

    def test_a_stage_not_run_fails(self):
        assert public_sets.compare(_run(dense=0.3), _run(dense=0.3, rerank=0.35)) == [
            "rerank: not run"
        ]

    def test_different_settings_are_not_compared_at_all(self):
        other = {**_run(dense=0.3), "embedding_model": "another"}
        got = public_sets.compare(other, _run(dense=0.3))
        assert len(got) == 1 and "embedding_model" in got[0]

    def test_a_committed_run_that_predates_the_passage_size_means_200(self):
        old = _run(dense=0.3)
        del old["chunk_tokens"]
        assert public_sets.compare(_run(dense=0.3), old) == []
        smaller = {**_run(dense=0.3), "chunk_tokens": 150}
        assert "chunk_tokens" in public_sets.compare(smaller, old)[0]
