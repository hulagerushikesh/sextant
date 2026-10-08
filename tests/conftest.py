"""Shared fixtures.

The knowledge-base fixture is session-scoped and deliberately small: it loads
two real models and builds a real ChromaDB collection, which costs about ten
seconds, and doing that per test would make the suite something nobody runs.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

CORPUS = {
    "kalman": (
        "# Kalman Filter\n\n"
        "A Kalman filter estimates hidden state from noisy measurements by alternating "
        "a predict step and an update step. The Kalman gain decides how much to trust "
        "the measurement over the prediction.\n\n"
        "## Tuning\n\n"
        "Process noise Q is a modelling choice and is almost always tuned by hand.\n"
    ),
    "hungarian": (
        "# Hungarian Algorithm\n\n"
        "The Hungarian algorithm solves the assignment problem in cubic time. "
        "Error code TRK-104 is raised when the solve exceeds its time budget.\n"
    ),
}


@pytest.fixture(autouse=True)
def isolate_the_spend_ledger(tmp_path_factory, monkeypatch):
    """Give every test its own spend ledger.

    `DailyBudget` persists the day's tally since 2026-10-08, and its default
    path is inside the collection directory. Without this the suite wrote a
    real ledger into the repository's `chroma_db/` and every later
    `DailyBudget()` resumed it, so one test's spend decided another's cap --
    found by eight pre-existing tests failing at once, which is the only
    pleasant way to find shared mutable state.

    Autouse on purpose: a test that wants persistence passes `ledger=` itself.
    """
    ledger = tmp_path_factory.mktemp("spend") / ".sextant-spend.json"
    monkeypatch.setenv("SEXTANT_SPEND_LEDGER", str(ledger))


@pytest.fixture(scope="session")
def corpus_dir() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="sextant-test-corpus-"))
    for name, text in CORPUS.items():
        (directory / f"{name}.md").write_text(text)
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture(scope="session")
def store_dir() -> Iterator[Path]:
    """An isolated ChromaDB directory, so tests never touch a real corpus."""
    from tools.vector_db.vector_search import PERSIST_DIR_ENV

    directory = Path(tempfile.mkdtemp(prefix="sextant-test-store-"))
    previous = os.environ.get(PERSIST_DIR_ENV)
    os.environ[PERSIST_DIR_ENV] = str(directory)
    yield directory
    if previous is None:
        os.environ.pop(PERSIST_DIR_ENV, None)
    else:
        os.environ[PERSIST_DIR_ENV] = previous
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture(scope="session")
def embedder():
    from tools.vector_db.embeddings import get_embedder

    return get_embedder()


@pytest.fixture(scope="session")
def corpus_files(corpus_dir: Path) -> list[str]:
    return sorted(str(path) for path in corpus_dir.glob("*.md"))


@pytest.fixture(scope="session")
async def kb(store_dir: Path, corpus_files: list[str]):
    """A knowledge base with the small corpus already ingested."""
    from tools.vector_db.vector_search import KnowledgeBase

    knowledge_base = KnowledgeBase()
    for path in corpus_files:
        await knowledge_base.add_file(path, category="test")
    return knowledge_base
