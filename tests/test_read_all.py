"""A whole-collection read survives a large library.

An unbounded `collection.get()` binds every id as one SQLite variable, and
SQLite stops at 32,766. Scoring the 85,000-chunk FiQA set broke the first
search and the stats call that way, so every whole-collection read is paged.
"""

from __future__ import annotations

import re
from pathlib import Path

import chromadb
import pytest

from sextant.vector_db import vector_search
from sextant.vector_db.vector_search import READ_PAGE, read_all

ROWS = 40_000  # past SQLite's 32,766-variable limit


def _fill(collection, n: int) -> None:
    for start in range(0, n, 5000):
        ids = range(start, min(n, start + 5000))
        collection.add(
            ids=[f"c{i}" for i in ids],
            embeddings=[[float(i), 1.0] for i in ids],
            metadatas=[{"document_id": f"d{i // 2}"} for i in ids],
            documents=[f"text {i}" for i in ids],
        )


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    path = tmp_path_factory.mktemp("big")
    collection = chromadb.PersistentClient(path=str(path)).get_or_create_collection("big")
    _fill(collection, ROWS)
    return collection


def test_an_unbounded_read_fails_at_this_size(big):
    """If Chroma lifts the limit this test says so, and the paging can go."""
    with pytest.raises(Exception, match="too many SQL variables"):
        big.get(include=["metadatas"])


def test_every_row_comes_back_once_with_its_fields(big):
    got = read_all(big, ["documents", "metadatas", "embeddings"])
    assert len(got["ids"]) == len(set(got["ids"])) == ROWS
    assert got["embeddings"].shape == (ROWS, 2)
    for i in (0, READ_PAGE - 1, READ_PAGE, ROWS - 1):
        row = got["ids"].index(f"c{i}")
        assert got["documents"][row] == f"text {i}"
        assert got["metadatas"][row]["document_id"] == f"d{i // 2}"
        assert got["embeddings"][row][0] == float(i)


def test_a_small_or_empty_collection_reads_as_get_does(tmp_path: Path):
    collection = chromadb.PersistentClient(path=str(tmp_path)).get_or_create_collection("small")
    empty = read_all(collection, ["metadatas", "embeddings"])
    assert empty["ids"] == [] and empty["metadatas"] == [] and empty["embeddings"] is None
    _fill(collection, READ_PAGE)  # exactly one page: the loop must stop, not re-read
    got = read_all(collection, ["metadatas"])
    assert got["ids"] == collection.get()["ids"]


def test_no_unbounded_whole_collection_read_is_left():
    source = Path(vector_search.__file__).parent.parent
    offenders = [
        f"{path.name}:{n}"
        for path in source.rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), start=1)
        if re.search(r"collection\.get\(include=", line) and "limit=" not in line
    ]
    assert offenders == [], f"read these with read_all(): {offenders}"
