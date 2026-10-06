"""Taking a document back out, and the re-ingest that used to leave half of it in.

Two things are under test. The store: `remove_document` deletes a document's
chunks and its overview and nothing else. And `_store`: re-ingesting a document
whose chunk count has changed must not leave the surplus behind. That one is a
regression test for a real bug -- an upsert replaces ids one for one, so a
document that made eleven chunks and now makes one left ten chunks of deleted
text embedded and searchable, ranking ahead of the document that replaced them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mcp_server.uploads import to_document
from tools.vector_db.forget_cli import _forget, _list
from tools.vector_db.vector_search import KnowledgeBase


@pytest.fixture
async def own_kb(store_dir: Path, request: pytest.FixtureRequest):
    """A collection of this test's own: everything here is destructive."""
    name = f"removal-{request.node.name[:40]}"
    knowledge_base = KnowledgeBase(collection_name=name)
    yield knowledge_base
    knowledge_base.client.delete_collection(name)


async def write(kb: KnowledgeBase, tmp_path: Path, name: str, text: str) -> dict[str, Any]:
    path = tmp_path / f"{name}.md"
    path.write_text(text)
    return await kb.add_file(str(path), category="test")


class TestReIngest:
    async def test_a_document_that_now_makes_fewer_chunks_leaves_none_behind(
        self, own_kb: KnowledgeBase, tmp_path: Path
    ):
        long = "# Note\n\n" + ("Tracking uses a Kalman filter for motion. " * 200)
        await write(own_kb, tmp_path, "note", long)
        assert own_kb.collection.count() > 5

        await write(own_kb, tmp_path, "note", "# Note\n\nShort now.")

        assert own_kb.collection.count() == 1
        # The deleted text is gone from the index, not merely outranked.
        found = own_kb.search_sync("Kalman filter motion", limit=5)["results"]
        assert [hit["id"] for hit in found] == []

    async def test_a_re_ingest_touches_only_the_document_being_written(
        self, own_kb: KnowledgeBase, tmp_path: Path
    ):
        await write(own_kb, tmp_path, "keep", "# Keep\n\nThe Hungarian algorithm assigns.")
        await write(own_kb, tmp_path, "note", "# Note\n\n" + ("Kalman filter. " * 200))
        keep_before = own_kb.collection.get(where={"document_id": "keep"})["ids"]

        await write(own_kb, tmp_path, "note", "# Note\n\nShort.")

        assert own_kb.collection.get(where={"document_id": "keep"})["ids"] == keep_before

    async def test_an_overview_is_replaced_not_kept_from_the_previous_text(
        self, own_kb: KnowledgeBase, tmp_path: Path
    ):
        path = tmp_path / "note.md"
        path.write_text("# Note\n\nThe first version.")
        document = await own_kb.load_file(str(path), category="test")
        await own_kb.add_document(document, summary="An overview of the first version.")
        assert (await own_kb.health_check())["summaries"] == 1

        # Re-ingested without one: a stale overview of text that no longer
        # exists would be worse than no overview.
        await write(own_kb, tmp_path, "note", "# Note\n\nThe second version.")
        assert (await own_kb.health_check())["summaries"] == 0


class TestRemoveDocument:
    async def test_removing_a_document_takes_its_chunks_and_its_overview(
        self, own_kb: KnowledgeBase, tmp_path: Path
    ):
        path = tmp_path / "note.md"
        path.write_text("# Note\n\n" + ("Kalman filter. " * 100))
        document = await own_kb.load_file(str(path), category="test")
        await own_kb.add_document(document, summary="An overview.")
        before = own_kb.collection.count()

        result = await own_kb.remove_document("note")

        assert result["success"] and result["chunks_removed"] == before
        assert own_kb.collection.count() == 0
        assert (await own_kb.health_check())["summaries"] == 0

    async def test_the_other_documents_stay(self, own_kb: KnowledgeBase, tmp_path: Path):
        await write(own_kb, tmp_path, "keep", "# Keep\n\nThe Hungarian algorithm assigns.")
        await write(own_kb, tmp_path, "drop", "# Drop\n\nUnrelated.")

        await own_kb.remove_document("drop")

        listing = await own_kb.list_documents()
        assert [doc["document_id"] for doc in listing["documents"]] == ["keep"]

    async def test_an_unknown_id_is_a_message_not_a_wiped_collection(
        self, own_kb: KnowledgeBase, tmp_path: Path
    ):
        await write(own_kb, tmp_path, "keep", "# Keep\n\nStill here.")

        result = await own_kb.remove_document("never-ingested")

        assert result["success"] is False and result["chunks_removed"] == 0
        assert own_kb.collection.count() == 1

    async def test_the_removed_document_stops_being_searchable(
        self, own_kb: KnowledgeBase, tmp_path: Path
    ):
        await write(own_kb, tmp_path, "keep", "# Keep\n\nThe Hungarian algorithm assigns.")
        await write(own_kb, tmp_path, "secret", "# Secret\n\nA private CV listing employers.")

        await own_kb.remove_document("secret")

        found = own_kb.search_sync("private CV employers", limit=5)["results"]
        assert all(hit["document_id"] != "secret" for hit in found)


class FakeKB:
    """The three calls `sextant-forget` makes, with the removals recorded."""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.removed: list[str] = []

    async def list_documents(self) -> dict[str, Any]:
        return {"documents": self.documents}

    async def remove_document(self, document_id: str) -> dict[str, Any]:
        self.removed.append(document_id)
        self.documents = [d for d in self.documents if d["document_id"] != document_id]
        return {"success": True, "message": f"Removed {document_id} and its 2 chunk(s)"}

    async def health_check(self) -> dict[str, Any]:
        return {"documents": len(self.documents), "collection_size": 2 * len(self.documents)}


def fake(*ids: str) -> Any:
    return FakeKB([{"document_id": i, "title": i.title(), "chunks": 2} for i in ids])


class TestForgetCommand:
    async def test_it_asks_first_and_a_no_removes_nothing(self, monkeypatch, capsys):
        kb = fake("keep", "drop")
        monkeypatch.setattr("builtins.input", lambda _: "n")

        assert await _forget(kb, ["drop"], assume_yes=False) == 0

        assert kb.removed == []
        assert "Nothing removed." in capsys.readouterr().out

    async def test_a_yes_removes_what_it_listed(self, monkeypatch, capsys):
        kb = fake("keep", "drop")
        monkeypatch.setattr("builtins.input", lambda _: "y")

        assert await _forget(kb, ["drop"], assume_yes=False) == 0

        assert kb.removed == ["drop"]
        assert "(2 chunks)" in capsys.readouterr().out

    async def test_yes_skips_the_question_for_a_non_interactive_shell(self, monkeypatch):
        kb = fake("drop")

        def refuse(_: str) -> str:
            raise AssertionError("--yes must not prompt")

        monkeypatch.setattr("builtins.input", refuse)
        assert await _forget(kb, ["drop"], assume_yes=True) == 0
        assert kb.removed == ["drop"]

    async def test_an_unknown_id_is_reported_and_never_prompted_for(self, monkeypatch, capsys):
        kb = fake("keep")

        def refuse(_: str) -> str:
            raise AssertionError("nothing to confirm")

        monkeypatch.setattr("builtins.input", refuse)
        assert await _forget(kb, ["typo"], assume_yes=False) == 1

        assert kb.removed == []
        assert "not in the collection" in capsys.readouterr().out

    async def test_the_listing_prints_an_id_a_count_and_a_title(self, capsys):
        assert await _list(fake("keep", "drop")) == 0
        out = capsys.readouterr().out
        assert "drop" in out and "2 chunks" in out and "Keep" in out


class TestUploadsOfTheSameFilename:
    """The collision that `upload:<owner>:<stem>` exists to stop.

    Ids were `upload:<filename stem>`, global across the store, and `_store`
    clears a document's chunks before writing its new ones -- correct on its
    own, and the right behaviour for a re-ingest. Together, two people behind
    the one shared Basic-auth password who each uploaded `notes.md` destroyed
    each other's chunks, and `/upload` answered success either way.

    Both halves are asserted here, because a fix that only separated the two
    people would have broken the replacement the stable id was for.
    """

    async def test_two_people_uploading_the_same_filename_both_survive(
        self, own_kb: KnowledgeBase
    ):
        ada = to_document("notes.md", b"# Notes\n\nThe Hungarian algorithm assigns.\n", owner="ada")
        grace = to_document("notes.md", b"# Notes\n\nA Kalman filter predicts.\n", owner="grace")

        await own_kb.add_documents([ada])
        await own_kb.add_documents([grace])

        for document in (ada, grace):
            stored = own_kb.collection.get(where={"document_id": document["id"]})["ids"]
            assert stored, f"{document['id']} was destroyed by the other upload"
        # And the text, not just the row: the earlier upload is still findable.
        found = own_kb.search_sync("Hungarian algorithm assignment", limit=5)["results"]
        assert any(hit["id"].startswith("upload:ada:notes") for hit in found)

    async def test_the_same_person_re_uploading_replaces(self, own_kb: KnowledgeBase):
        first = to_document("notes.md", b"# Notes\n\n" + b"Kalman filter. " * 200, owner="ada")
        await own_kb.add_documents([first])
        before = own_kb.collection.get(where={"document_id": first["id"]})["ids"]
        assert len(before) > 1

        second = to_document("notes.md", b"# Notes\n\nShort now.\n", owner="ada")
        await own_kb.add_documents([second])

        assert first["id"] == second["id"]
        assert len(own_kb.collection.get(where={"document_id": second["id"]})["ids"]) == 1
        assert own_kb.search_sync("Kalman filter", limit=5)["results"] == []
