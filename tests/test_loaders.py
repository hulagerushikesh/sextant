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


class TestPdfExtraction:
    """MuPDF gives cells one per line; the loader puts a row back together."""

    @pytest.fixture
    def pdf_file(self, tmp_path):
        import pymupdf

        path = tmp_path / "paper.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 72), "TABLE 1: Numbers for two models.", fontsize=10)
            page.insert_text((72, 90), "Model", fontsize=10)
            page.insert_text((160, 90), "Size", fontsize=10)
            page.insert_text((220, 90), "Layers", fontsize=10)
            page.insert_text((72, 104), "Alpha [1]", fontsize=10)
            page.insert_text((160, 104), "7B", fontsize=10)
            page.insert_text((220, 104), "32", fontsize=10)
            page.insert_text((72, 118), "Beta [2]", fontsize=10)
            page.insert_text((160, 118), "13B", fontsize=10)
            page.insert_text((220, 118), "40", fontsize=10)
            page.insert_text((72, 150), "Epsilon is set to 10", fontsize=10)
            page.insert_text((165, 146), "-8", fontsize=6)  # superscript, above baseline
            page.insert_text((178, 150), "in every run described here.", fontsize=10)
            second = doc.new_page()
            second.insert_text((72, 72), "Second page prose about results.", fontsize=10)
            doc.set_metadata({"title": "Two Model Paper"})
            doc.save(str(path))
        return path

    def test_cells_on_one_baseline_become_one_line(self, pdf_file):
        document = load_path(pdf_file)
        assert "Model Size Layers" in document.text
        assert "Alpha [1] 7B 32" in document.text
        assert "Beta [2] 13B 40" in document.text

    def test_superscript_joins_its_own_line(self, pdf_file):
        document = load_path(pdf_file)
        (line,) = [ln for ln in document.text.split("\n") if "Epsilon" in ln]
        assert "-8" in line and line.endswith("in every run described here.")

    def test_pages_and_tables_are_located(self, pdf_file):
        document = load_path(pdf_file)
        pages = [loc for loc in document.locators if loc.kind == "page"]
        assert [loc.label for loc in pages] == [1, 2]
        assert document.locate(document.text.index("Second page"))["page"] == 2
        (table,) = [loc for loc in document.locators if loc.kind == "table"]
        assert table.label.endswith("Model Size Layers")
        assert document.text[table.start : table.end].startswith("Alpha [1]")

    def test_title_comes_from_metadata(self, pdf_file):
        assert load_path(pdf_file).title == "Two Model Paper"

    def test_pypdf_fallback_still_reads_the_file(self, pdf_file, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def no_mupdf(name, *args, **kwargs):
            if name == "pymupdf":
                raise ImportError("simulated: wheel unavailable")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_mupdf)
        document = load_path(pdf_file)
        assert "Second page prose" in document.text
        assert [loc.label for loc in document.locators if loc.kind == "page"] == [1, 2]
