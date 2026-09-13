"""Loaders, and the offset-to-location mapping citations depend on."""

from __future__ import annotations

import pytest

from tools.vector_db.loaders import (
    LoadedDocument,
    Locator,
    UnsupportedDocument,
    load_path,
)

MARKDOWN = """# Handbook

Intro text.

## Kalman Filter

Predict then update.

### Tuning

Process noise is tuned by hand.

## Hungarian Algorithm

Cubic time.
"""


@pytest.fixture
def markdown_file(tmp_path):
    path = tmp_path / "handbook.md"
    path.write_text(MARKDOWN)
    return path


class TestMarkdown:
    def test_headings_become_locators(self, markdown_file):
        document = load_path(markdown_file)
        labels = [locator.label for locator in document.locators]
        assert labels == ["Handbook", "Kalman Filter", "Tuning", "Hungarian Algorithm"]

    def test_title_is_the_first_heading(self, markdown_file):
        assert load_path(markdown_file).title == "Handbook"

    def test_doc_id_and_source_come_from_the_filename(self, markdown_file):
        document = load_path(markdown_file)
        assert document.doc_id == "handbook"
        assert document.source == "handbook.md"

    def test_an_offset_resolves_to_the_heading_it_falls_under(self, markdown_file):
        document = load_path(markdown_file)
        offset = document.text.index("Process noise")
        assert document.locate(offset)["section"] == "Tuning"

    def test_a_later_offset_resolves_to_a_later_heading(self, markdown_file):
        document = load_path(markdown_file)
        offset = document.text.index("Cubic time")
        assert document.locate(offset)["section"] == "Hungarian Algorithm"

    def test_text_is_preserved_verbatim(self, markdown_file):
        assert load_path(markdown_file).text == MARKDOWN

    def test_a_file_with_no_headings_falls_back_to_the_stem(self, tmp_path):
        path = tmp_path / "plain.md"
        path.write_text("Just prose, no headings.")
        document = load_path(path)
        assert document.title == "plain"
        assert document.locators == []


class TestPlainText:
    def test_loads_with_no_locators(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("Some notes.")
        document = load_path(path)
        assert document.text == "Some notes."
        assert document.locators == []
        assert document.locate(0) == {}


class TestDispatch:
    def test_an_unsupported_extension_names_what_is_supported(self, tmp_path):
        path = tmp_path / "thing.docx"
        path.write_bytes(b"x")
        with pytest.raises(UnsupportedDocument, match="No loader for"):
            load_path(path)

    def test_a_missing_file(self, tmp_path):
        with pytest.raises(UnsupportedDocument, match="Not a file"):
            load_path(tmp_path / "nope.md")

    def test_a_directory_is_not_a_document(self, tmp_path):
        with pytest.raises(UnsupportedDocument):
            load_path(tmp_path)


class TestLocate:
    @pytest.fixture
    def document(self) -> LoadedDocument:
        return LoadedDocument(
            doc_id="d",
            title="T",
            text="x" * 100,
            source="d.pdf",
            locators=[
                Locator("page", 1, 0, 50),
                Locator("page", 2, 50, 100),
                Locator("section", "Chapter One", 0, 100),
            ],
        )

    def test_page_and_section_are_both_returned(self, document):
        assert document.locate(10) == {"page": 1, "section": "Chapter One"}

    def test_the_page_changes_at_the_boundary(self, document):
        assert document.locate(49)["page"] == 1
        assert document.locate(50)["page"] == 2

    def test_an_offset_past_the_end_resolves_to_nothing(self, document):
        assert document.locate(500) == {}
