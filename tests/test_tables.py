"""Tables become rows, rows become chunks, and the prose around them is untouched."""

# ruff: noqa: E501 -- the fixtures are real pypdf lines, and pypdf does not wrap.

from tools.vector_db.chunking import chunk_text
from tools.vector_db.loaders import LoadedDocument, Locator
from tools.vector_db.tables import (
    TableSpan,
    find_markdown_tables,
    find_pdf_tables,
    table_rows,
)

PDF_PAGE = """\
of the Transformer are the subject of Section 4.2.
TABLE 5: Model cards of several selected LLMs with public configuration details. Here, PE denotes position embedding,
#L denotes the number of layers, #H denotes the number of attention heads, dmodel denotes the size of hidden states, and
MCL denotes the maximum context length during training.
Model Category Size Normalization PE Activation Bias #L #H dmodel MCL
GPT3 [55] Causal decoder 175B Pre LayerNorm Learned GeLU ✓ 96 96 12288 2048
PaLM [56] Causal decoder 540B Pre LayerNorm RoPE SwiGLU × 118 48 18432 2048
LLaMA [57] Causal decoder 65B Pre RMSNorm RoPE SwiGLU × 80 64 8192 2048
Mainstream architectures are reviewed next, along with the objectives that train them.
It is common practice to stack the decoder blocks with pre-normalization.
"""

GROUPED_PAGE = """\
TABLE 3: A detailed list of available collections for instruc-
tion tuning.
Categories Collections Time #Examples
Task
Nat. Inst. [179] Apr-2021 193K
FLAN [67] Sep-2021 4.4M
Chat
HH-RLHF [183] Apr-2022 160K
3.3 Commonly Used Datasets for Fine-tuning
After pre-training, it requires further fine-tuning to enhance the model.
"""

MARKDOWN = """\
# Config

Defaults below.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `min_hits` | 3 | Consecutive matches before a track is confirmed |
| `max_age` | 30 | Frames a track may go unmatched before deletion |

Trailing prose after the table, long enough to be its own paragraph of text.
"""


def words(text: str) -> int:
    return len(text.split())


class TestPdfDetection:
    def test_finds_rows_after_a_wrapped_caption(self):
        (table,) = find_pdf_tables(PDF_PAGE)
        rows = [PDF_PAGE[s:e] for s, e, _ in table_rows(PDF_PAGE, table)]
        assert [r.split()[0] for r in rows] == ["GPT3", "PaLM", "LLaMA"]

    def test_context_is_caption_opening_plus_header(self):
        (table,) = find_pdf_tables(PDF_PAGE)
        caption, header = table.context.split("\n")
        assert caption.startswith("TABLE 5: Model cards")
        assert "PE denotes position embedding" in caption
        assert header.startswith("Model Category Size Normalization PE")

    def test_stops_at_prose(self):
        (table,) = find_pdf_tables(PDF_PAGE)
        assert "Mainstream architectures" not in PDF_PAGE[table.start : table.end]

    def test_caption_and_header_stay_outside_the_span(self):
        (table,) = find_pdf_tables(PDF_PAGE)
        assert "TABLE 5" not in PDF_PAGE[table.start : table.end]
        assert "Model Category" not in PDF_PAGE[table.start : table.end]

    def test_group_labels_prefix_their_rows(self):
        # "Task" sits directly under the header and is absorbed into it; "Chat"
        # comes after rows and stays a group label.
        (table,) = find_pdf_tables(GROUPED_PAGE)
        groups = [g for _, _, g in table_rows(GROUPED_PAGE, table)]
        assert groups == ["", "", "Chat"]
        assert table.context.endswith("Categories Collections Time #Examples Task")

    def test_section_heading_ends_the_table(self):
        (table,) = find_pdf_tables(GROUPED_PAGE)
        assert "3.3 Commonly" not in GROUPED_PAGE[table.start : table.end]

    def test_short_caption_tail_is_not_a_header(self):
        (table,) = find_pdf_tables(GROUPED_PAGE)
        caption, header = table.context.split("\n")
        assert caption.endswith("instruc- tion tuning.")
        assert header.startswith("Categories Collections")

    def test_wrapped_header_is_joined_until_the_first_row(self):
        page = (
            "TABLE 8: Detailed optimization settings of several existing LLMs.\n"
            "Model Batch Size\n(#tokens)\nLearning\nRate Warmup Decay Method Optimizer\n"
            "GPT3 (175B) 32K 6e-5 yes cosine Adam\n"
            "PaLM (540B) 1M 1e-2 no inverse square root Adafactor\n"
        )
        (table,) = find_pdf_tables(page)
        assert table.context.split("\n")[1] == (
            "Model Batch Size (#tokens) Learning Rate Warmup Decay Method Optimizer"
        )
        assert len(table_rows(page, table)) == 2

    def test_operator_row_is_not_header(self):
        page = (
            "TABLE 6: Comparison of parallelism and complexity of different models.\n"
            "Model Decoding Complexity Training Complexity\n"
            "Transformer O(H(T +H)) O(TH(T +H))\nRWKV O(H2) O(TH2)\n"
        )
        (table,) = find_pdf_tables(page)
        assert table.context.endswith("Model Decoding Complexity Training Complexity")
        assert len(table_rows(page, table)) == 2

    def test_caption_without_rows_is_not_a_table(self):
        text = "TABLE 2: Something described in prose.\nOnly one line here.\nThen prose that is long enough to read as prose again.\n"
        assert find_pdf_tables(text) == []

    def test_plain_prose_has_no_tables(self):
        assert find_pdf_tables("Nothing tabular. " * 50) == []


class TestMarkdownDetection:
    def test_pipe_table_rows_under_a_rule(self):
        (table,) = find_markdown_tables(MARKDOWN)
        rows = [MARKDOWN[s:e] for s, e, _ in table_rows(MARKDOWN, table)]
        assert len(rows) == 2 and rows[0].startswith("| `min_hits`")
        assert table.context == "| Parameter | Default | Meaning |"

    def test_rule_line_alone_is_not_a_table(self):
        assert find_markdown_tables("| a |\n| --- |\n") == []


class TestRowChunks:
    def test_each_row_is_a_chunk_prefixed_with_context(self):
        tables = find_pdf_tables(PDF_PAGE)
        chunks = chunk_text(PDF_PAGE, words, tables=tables, row_tokens=0)
        rows = [c for c in chunks if c.kind == "row"]
        assert len(rows) == 3
        palm = next(c for c in rows if "PaLM" in c.text)
        assert palm.text.startswith("TABLE 5: Model cards")
        assert palm.text.endswith("PaLM [56] Causal decoder 540B Pre LayerNorm RoPE SwiGLU × 118 48 18432 2048")

    def test_row_span_points_at_the_row_alone(self):
        tables = find_pdf_tables(PDF_PAGE)
        chunks = chunk_text(PDF_PAGE, words, tables=tables, row_tokens=0)
        palm = next(c for c in chunks if "PaLM" in c.text)
        assert PDF_PAGE[palm.char_start : palm.char_end].startswith("PaLM [56]")

    def test_rows_pack_under_one_header_up_to_the_budget(self):
        tables = find_pdf_tables(PDF_PAGE)
        # Each row is 14 words; a 30-word budget takes two, then one.
        chunks = chunk_text(PDF_PAGE, words, tables=tables, row_tokens=30)
        rows = [c for c in chunks if c.kind == "row"]
        assert [c.text.count("Causal decoder") for c in rows] == [2, 1]
        assert rows[0].text.count("TABLE 5") == 1
        assert PDF_PAGE[rows[0].char_start : rows[0].char_end].startswith("GPT3 [55]")
        assert PDF_PAGE[rows[0].char_start : rows[0].char_end].endswith("18432 2048")

    def test_a_new_group_starts_a_new_chunk(self):
        tables = find_pdf_tables(GROUPED_PAGE)
        rows = [c for c in chunk_text(GROUPED_PAGE, words, tables=tables) if c.kind == "row"]
        assert len(rows) == 2
        assert rows[1].text.endswith("Chat HH-RLHF [183] Apr-2022 160K")

    def test_prose_on_both_sides_is_kept_and_never_crosses_the_table(self):
        tables = find_pdf_tables(PDF_PAGE)
        chunks = chunk_text(PDF_PAGE, words, tables=tables)
        prose = [c for c in chunks if c.kind == "text"]
        assert any("TABLE 5: Model cards" in c.text for c in prose)
        assert any("Mainstream architectures" in c.text for c in prose)
        assert not any("GPT3 [55]" in c.text for c in prose)

    def test_indices_are_contiguous_in_document_order(self):
        tables = find_pdf_tables(PDF_PAGE)
        chunks = chunk_text(PDF_PAGE, words, tables=tables)
        assert [c.index for c in chunks] == list(range(len(chunks)))
        assert [c.char_start for c in chunks] == sorted(c.char_start for c in chunks)

    def test_group_label_is_written_into_the_row(self):
        tables = find_pdf_tables(GROUPED_PAGE)
        chunks = chunk_text(GROUPED_PAGE, words, tables=tables)
        assert any(c.text.endswith("Chat HH-RLHF [183] Apr-2022 160K") for c in chunks)

    def test_no_tables_means_the_old_behaviour(self):
        assert chunk_text(PDF_PAGE, words) == chunk_text(PDF_PAGE, words, tables=())
        assert all(c.kind == "text" for c in chunk_text(PDF_PAGE, words))

    def test_bad_spans_fall_back_to_prose(self):
        beyond = TableSpan(10, len(PDF_PAGE) + 50, "x")
        chunks = chunk_text(PDF_PAGE, words, tables=[beyond])
        assert all(c.kind == "text" for c in chunks)

    def test_short_row_is_not_merged_as_a_runt(self):
        tables = find_markdown_tables(MARKDOWN)
        text = MARKDOWN.rsplit("\n\nTrailing", 1)[0] + "\n"
        chunks = chunk_text(text, words, tables=find_markdown_tables(text), min_tokens=50)
        assert chunks[-1].kind == "row"
        assert len(tables) == 1


class TestLoadedDocument:
    def test_tables_property_and_locate_ignore_each_other(self):
        doc = LoadedDocument(
            doc_id="d", title="d", text=PDF_PAGE, source="d.pdf",
            locators=[Locator("page", 23, 0, len(PDF_PAGE)), Locator("table", "ctx", 10, 20)],
        )
        assert doc.tables == [TableSpan(10, 20, "ctx")]
        assert doc.locate(15) == {"page": 23}
