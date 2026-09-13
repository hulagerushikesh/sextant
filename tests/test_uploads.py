"""Parsing an uploaded file into something the knowledge base can store.

The failure this guards against is the one that shipped: a browser reading files
itself, and therefore refusing every format JavaScript cannot read as text --
which is exactly the format people have.
"""

from __future__ import annotations

import pytest

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
        first = to_document("notes.md", MARKDOWN)
        second = to_document("notes.md", MARKDOWN + b"\nmore\n")
        assert first["id"] == second["id"] == "upload:notes"

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
        assert "agenticrag-ingest" in str(caught.value)

    def test_pdf_is_among_the_formats_offered(self):
        # The whole point of moving parsing to the server.
        assert ".pdf" in SUPPORTED_SUFFIXES
