"""Parsing an uploaded file into something the knowledge base can store.

The failure this guards against is the one that shipped: a browser reading files
itself, and therefore refusing every format JavaScript cannot read as text --
which is exactly the format people have.
"""

from __future__ import annotations

import pytest

from mcp_server.identity import CLIENT_HEADER, DEFAULT_OWNER, owner_of, safe_owner
from mcp_server.uploads import MAX_UPLOAD_BYTES, SUPPORTED_SUFFIXES, safe_name, to_document
from tools.vector_db.loaders import UnsupportedDocument

MARKDOWN = b"# Tuning\n\nSet the gate to 9.4877.\n\n## Noise\n\nQ absorbs model error.\n"


class TestSafeName:
    @pytest.mark.parametrize(
        "given, expected",
        [
            ("notes.md", "notes.md"),
            ("../../etc/passwd", "passwd"),
            ("/absolute/path.txt", "path.txt"),
            ("wei rd$$name!.md", "wei rd_name_.md"),
            ("", "upload"),
            ("...", "upload"),
        ],
    )
    def test_a_name_cannot_escape_the_directory_it_lands_in(self, given, expected):
        assert safe_name(given) == expected


class TestParsing:
    def test_markdown_keeps_its_section_headings(self):
        document = to_document("notes.md", MARKDOWN)
        kinds = {loc["kind"] for loc in document["locators"]}
        assert kinds == {"section"}
        assert [loc["label"] for loc in document["locators"]] == ["Tuning", "Noise"]

    def test_the_whole_file_is_one_document(self):
        # Not one per section: chunking runs over the whole text, so a heading
        # with two lines under it is not silently dropped for being too short.
        document = to_document("notes.md", MARKDOWN)
        assert document["content"].count("Set the gate") == 1
        assert document["source"] == "notes.md"

    def test_the_id_is_stable_so_a_re_upload_replaces(self):
        first = to_document("notes.md", MARKDOWN, owner="ada")
        second = to_document("notes.md", MARKDOWN + b"\nmore\n", owner="ada")
        assert first["id"] == second["id"] == "upload:ada:notes"

    def test_the_same_filename_from_two_people_is_two_documents(self):
        # The defect this fixes: ids were `upload:<stem>`, global across the
        # store, and `_store` clears a document's chunks before rewriting them.
        # So the second `notes.md` silently deleted the first one's chunks and
        # /upload still answered success.
        ada = to_document("notes.md", MARKDOWN, owner="ada")
        grace = to_document("notes.md", MARKDOWN, owner="grace")
        assert ada["id"] != grace["id"]

    def test_an_upload_with_no_owner_lands_in_the_shared_namespace(self):
        # curl, the eval harness, a browser with storage switched off.
        assert to_document("notes.md", MARKDOWN)["id"] == f"upload:{DEFAULT_OWNER}:notes"

    def test_an_owner_cannot_forge_a_different_document(self):
        # `:` separates the id and `#` separates the chunk, so an owner that
        # carried either could name a document that is not theirs.
        forged = to_document("notes.md", MARKDOWN, owner="ada:evil#9")
        assert forged["id"] == "upload:ada_evil_9:notes"

    def test_plain_text_has_no_locators_and_that_is_fine(self):
        assert to_document("log.txt", b"nothing structured here")["locators"] == []

    def test_an_unreadable_format_says_what_is_readable(self):
        with pytest.raises(UnsupportedDocument) as caught:
            to_document("photo.jpeg", b"\xff\xd8\xff")
        assert ".pdf" in str(caught.value)

    def test_a_file_that_parses_to_nothing_is_reported_not_stored(self):
        # A scanned PDF is the real case: it loads, and yields no text. Storing
        # it would leave a document in the corpus that can never match anything.
        with pytest.raises(UnsupportedDocument) as caught:
            to_document("empty.md", b"   \n\n  \n")
        assert "no text" in str(caught.value)

    def test_an_oversized_upload_points_at_the_command_that_handles_it(self):
        with pytest.raises(UnsupportedDocument) as caught:
            to_document("huge.txt", b"x" * (MAX_UPLOAD_BYTES + 1))
        assert "sextant-ingest" in str(caught.value)

    def test_pdf_is_among_the_formats_offered(self):
        # The whole point of moving parsing to the server.
        assert ".pdf" in SUPPORTED_SUFFIXES


class TestOwner:
    """Namespacing, not isolation -- see `mcp_server/identity.py`."""

    @pytest.mark.parametrize(
        "given, expected",
        [
            ("ada", "ada"),
            ("  ada  ", "ada"),
            ("ada:evil", "ada_evil"),
            ("ada#9", "ada_9"),
            ("../../etc", "etc"),
            ("", DEFAULT_OWNER),
            (None, DEFAULT_OWNER),
            ("___", DEFAULT_OWNER),
            ("x" * 200, "x" * 64),
        ],
    )
    def test_an_owner_is_cleaned_to_something_an_id_can_hold(self, given, expected):
        assert safe_owner(given) == expected

    def test_the_owner_comes_from_the_client_header(self):
        assert owner_of({CLIENT_HEADER: "ada"}) == "ada"

    def test_no_header_is_the_shared_namespace(self):
        assert owner_of({}) == DEFAULT_OWNER
        assert owner_of(None) == DEFAULT_OWNER
