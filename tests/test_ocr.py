"""Scanned PDFs: read by text recognition, and said plainly when they are not.

Found on the owner's own Downloads folder, 2026-11-19: 19 of 60 files were
scans -- ID cards, marksheets, certificates -- and "what is my PAN number?"
had no answer because none of their words were in the library.

The real recognition runs in `TestAScanIsRead` on a PDF built here from a
picture of a page, so it has no text layer at all. It needs the English data
file: from a Tesseract install if there is one, or fetched once into the
user's cache (about 4 MB) -- which is the path a person installing the
bundle takes, so it is not stubbed out.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from sextant import settings
from sextant.vector_db import ocr
from sextant.vector_db.folder import LEDGER_NAME, FolderSync, no_text_reason
from sextant.vector_db.loaders import LoadedDocument, has_picture_pages, load_path
from tests.test_folder import FakeKB, _write

NUMBER = "ABCDE1234F"


def _scan(path: Path, lines: list[str]) -> Path:
    """A PDF whose one page is a picture of `lines`: what a scanner makes."""
    source = pymupdf.open()
    page = source.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + 40 * i), line, fontsize=18)
    picture = page.get_pixmap(dpi=200)
    scan = pymupdf.open()
    target = scan.new_page(width=page.rect.width, height=page.rect.height)
    target.insert_image(target.rect, pixmap=picture)
    scan.save(str(path))
    return path


def _text_pdf(path: Path, line: str) -> Path:
    document = pymupdf.open()
    document.new_page().insert_text((72, 100), line, fontsize=14)
    document.save(str(path))
    return path


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """Each test resolves recognition from its own settings."""
    monkeypatch.delenv(settings.env_name("OCR"), raising=False)
    monkeypatch.delenv(settings.env_name("OCR_LANG"), raising=False)
    ocr._forget()
    yield
    ocr._forget()


class TestAScanIsRead:
    def test_the_words_on_a_scanned_page_are_found(self, tmp_path):
        path = _scan(tmp_path / "PAN_Card.pdf", [f"Permanent Account Number {NUMBER}"])
        assert pymupdf.open(str(path))[0].get_text().strip() == "", "the fixture must be a scan"

        document = load_path(path)

        assert NUMBER in document.text
        assert document.recognised_pages == [1]
        assert document.recognition == "eng"
        assert document.recognition_missing == ""
        # Cited like any other page.
        assert document.locate(document.text.index(NUMBER)) == {"page": 1}

    def test_a_pdf_with_text_is_read_as_before(self, tmp_path, monkeypatch):
        def never(page: Any) -> Any:
            raise AssertionError("a page with text must not be recognised")

        monkeypatch.setattr(ocr, "textpage", never)
        document = load_path(_text_pdf(tmp_path / "notes.pdf", "plain words"))
        assert "plain words" in document.text
        assert document.recognised_pages == [] and document.recognition == ""

    def test_only_the_picture_pages_of_a_mixed_pdf_are_recognised(self, tmp_path):
        text = pymupdf.open(str(_text_pdf(tmp_path / "a.pdf", "typed page")))
        text.insert_pdf(pymupdf.open(str(_scan(tmp_path / "b.pdf", [f"Number {NUMBER}"]))))
        text.save(str(tmp_path / "mixed.pdf"))

        document = load_path(tmp_path / "mixed.pdf")

        assert "typed page" in document.text and NUMBER in document.text
        assert document.recognised_pages == [2]


class TestWhenItCannotRun:
    def test_turned_off_the_scan_is_empty_and_says_why(self, tmp_path, monkeypatch):
        monkeypatch.setenv(settings.env_name("OCR"), "off")
        path = _scan(tmp_path / "scan.pdf", [NUMBER])

        document = load_path(path)

        assert document.text == ""
        assert "turned off" in document.recognition_missing
        reason = no_text_reason(path, document)
        assert reason.startswith("is a scanned PDF, and text recognition could not read it")
        assert "turned off" in reason

    def test_a_scan_with_no_words_says_recognition_found_none(self, tmp_path):
        document = LoadedDocument("s", "s", "", "s.pdf", recognition="eng")
        assert "found no words" in no_text_reason(Path("s.pdf"), document)

    def test_without_a_document_the_old_reason_stands(self):
        assert "probably a scanned PDF" in no_text_reason(Path("s.pdf"))
        assert no_text_reason(Path("s.txt")) == "is empty"


class TestLanguages:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, ["eng"]),
            ("", ["eng"]),
            ("eng+mar", ["eng", "mar"]),
            ("ENG, mar hin", ["eng", "mar", "hin"]),
            ("eng+eng", ["eng"]),
            ("${user_config.ocr_languages}", ["eng"]),
            ("../../etc", ["eng"]),
        ],
    )
    def test_parsed(self, monkeypatch, raw, expected):
        if raw is not None:
            monkeypatch.setenv(settings.env_name("OCR_LANG"), raw)
        assert ocr.languages() == expected

    def test_signature_is_empty_when_off(self, monkeypatch):
        assert ocr.signature() == "eng"
        monkeypatch.setenv(settings.env_name("OCR"), "off")
        assert ocr.signature() == ""


class TestFindingTheData:
    """Where the language files come from, without the network."""

    @pytest.fixture
    def places(self, tmp_path, monkeypatch):
        cache, system = tmp_path / "cache", tmp_path / "system"
        system.mkdir()
        monkeypatch.setattr(ocr, "cache_dir", lambda: cache)
        monkeypatch.setattr(ocr, "_SYSTEM_DIRS", (str(system),))
        monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
        return cache, system

    @staticmethod
    def _network(monkeypatch, body: bytes) -> list[str]:
        asked: list[str] = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self) -> bytes:
                return body

        def urlopen(url: str, timeout: float, context: object = None) -> Response:
            asked.append(url)
            return Response()

        monkeypatch.setattr(ocr.urllib.request, "urlopen", urlopen)
        return asked

    def test_an_installed_file_is_used_where_it_is(self, places, monkeypatch):
        _, system = places
        (system / "eng.traineddata").write_bytes(b"x")
        asked = self._network(monkeypatch, b"")
        assert ocr.reader() == ocr.Reader("eng", str(system))
        assert asked == []

    def test_a_missing_file_is_fetched_and_checked(self, places, monkeypatch):
        cache, _ = places
        body = b"pretend model"
        monkeypatch.setitem(ocr._PINNED, "eng", hashlib.sha256(body).hexdigest())
        asked = self._network(monkeypatch, body)

        assert ocr.reader() == ocr.Reader("eng", str(cache))
        assert (cache / "eng.traineddata").read_bytes() == body
        assert asked == [ocr._URL.format(tag=ocr._TAG, lang="eng")]

    def test_a_file_that_does_not_match_its_hash_is_not_kept(self, places, monkeypatch):
        cache, _ = places
        asked = self._network(monkeypatch, b"not the model")
        with pytest.raises(ocr.OcrUnavailable, match="did not match"):
            ocr.reader()
        assert not (cache / "eng.traineddata").exists()
        # Remembered: a folder of many scans does not ask again for each.
        with pytest.raises(ocr.OcrUnavailable):
            ocr.reader()
        assert len(asked) == 1
        status = ocr.status()
        assert status["on"] is False and "did not match" in status["note"]

    def test_files_in_two_places_are_gathered_into_one(self, places, monkeypatch):
        """Tesseract takes one data folder."""
        cache, system = places
        (system / "eng.traineddata").write_bytes(b"e")
        body = b"marathi"
        monkeypatch.setitem(ocr._PINNED, "mar", hashlib.sha256(body).hexdigest())
        self._network(monkeypatch, body)
        monkeypatch.setenv(settings.env_name("OCR_LANG"), "eng+mar")

        assert ocr.reader() == ocr.Reader("eng+mar", str(cache))
        assert (cache / "eng.traineddata").read_bytes() == b"e"
        assert (cache / "mar.traineddata").read_bytes() == body

    def test_a_language_with_no_file_and_no_pin_is_named(self, places, monkeypatch):
        self._network(monkeypatch, b"")
        monkeypatch.setenv(settings.env_name("OCR_LANG"), "tam")
        with pytest.raises(ocr.OcrUnavailable, match="'tam'"):
            ocr.reader()

    def test_status_never_fetches(self, places, monkeypatch):
        asked = self._network(monkeypatch, b"")
        assert ocr.status() == {"on": True, "languages": "eng"}
        assert asked == []


class RecognisingKB(FakeKB):
    """Loads a scan as the real loader would: words when recognition is on,
    none and the reason when it is off."""

    def __init__(self, typed: set[str] | None = None) -> None:
        super().__init__()
        self.loaded: list[str] = []
        self.typed = typed or set()  # files with text of their own: nothing to recognise

    async def load_file(self, path: str, category: str = "general") -> LoadedDocument:
        name = Path(path).name
        self.loaded.append(name)
        if name in self.typed:
            return LoadedDocument(Path(path).stem, name, "typed words", name)
        if not ocr.enabled():
            self.empty.add(name)
            missing = "text recognition is turned off"
            return LoadedDocument(Path(path).stem, name, "", name, recognition_missing=missing)
        self.empty.discard(name)
        return LoadedDocument(
            Path(path).stem, name, NUMBER, name,
            recognised_pages=[1], recognition=ocr.signature(),
        )


class TestTheFolderTriesAScanAgain:
    async def test_a_scan_skipped_while_off_is_read_once_it_is_on(self, tmp_path, monkeypatch):
        root, store = tmp_path / "library", tmp_path / "store"
        _write(root, "PAN_Card.pdf")
        kb = RecognisingKB()

        monkeypatch.setenv(settings.env_name("OCR"), "off")
        first = FolderSync(root, store)
        await first.run(lambda: kb)
        assert first.status()["not_indexed"] == 1
        assert "turned off" in first.skipped[0]["reason"]
        ledger = json.loads((store / LEDGER_NAME).read_text())
        assert ledger[str(root / "PAN_Card.pdf")]["ocr"] == ""

        monkeypatch.delenv(settings.env_name("OCR"))
        second = FolderSync(root, store)
        await second.run(lambda: kb)
        status = second.status()
        assert status["not_indexed"] == 0 and status["stored_this_run"] == 1
        assert status["read_by_text_recognition"] == 1
        assert kb.docs == {"PAN_Card.pdf"}

    async def test_a_scan_recognition_already_failed_on_is_not_read_again(self, tmp_path):
        root, store = tmp_path / "library", tmp_path / "store"
        _write(root, "blank.pdf")
        kb = FakeKB(empty={"blank.pdf"})  # loads with recognition on, still no words

        await FolderSync(root, store).run(lambda: kb)
        again = FolderSync(root, store)
        await again.run(lambda: kb)

        assert kb.tried == ["blank.pdf"]
        assert again.status()["not_indexed"] == 1

    async def test_a_ledger_from_before_recognition_is_tried_once(self, tmp_path):
        """0.11 recorded scans with no `ocr` field: each is read once more."""
        root, store = tmp_path / "library", tmp_path / "store"
        path = _write(root, "PAN_Card.pdf")
        stat = path.stat()
        store.mkdir()
        (store / LEDGER_NAME).write_text(
            json.dumps(
                {
                    str(path): {
                        "signature": [stat.st_mtime_ns, stat.st_size],
                        "stored": False,
                        "reason": "has no text that can be read",
                        "kind": "no_text",
                    }
                }
            )
        )
        kb = RecognisingKB()
        sync = FolderSync(root, store)
        await sync.run(lambda: kb)
        assert kb.loaded == ["PAN_Card.pdf"]
        assert sync.status()["stored_this_run"] == 1


class TestAStoredScanIsReadAgainInNewLanguages:
    """Found on the owner's Downloads, 2026-11-19: a Maharashtra marksheet
    read in English only came back with the name and subjects garbled, and
    adding Marathi did nothing -- only scans with no words at all were tried
    again. A scan that was read is now read again when the languages change."""

    @staticmethod
    async def _pass(root: Path, store: Path, kb: RecognisingKB) -> FolderSync:
        sync = FolderSync(root, store)
        await sync.run(lambda: kb)
        return sync

    async def test_adding_a_language_reads_the_scan_again_once(self, tmp_path, monkeypatch):
        root, store = tmp_path / "library", tmp_path / "store"
        _write(root, "marksheet.pdf")
        _write(root, "notes.md")
        kb = RecognisingKB(typed={"notes.md"})

        await self._pass(root, store, kb)
        ledger = json.loads((store / LEDGER_NAME).read_text())
        assert ledger[str(root / "marksheet.pdf")]["ocr"] == "eng"
        assert ledger[str(root / "notes.md")]["ocr"] == ""

        monkeypatch.setenv(settings.env_name("OCR_LANG"), "eng+mar")
        kb.loaded.clear()
        again = await self._pass(root, store, kb)
        assert kb.loaded == ["marksheet.pdf"], "only the scan is read again"
        assert again.status()["stored_this_run"] == 1
        assert kb.docs == {"marksheet.pdf", "notes.md"}, "replaced, not added beside"
        ledger = json.loads((store / LEDGER_NAME).read_text())
        assert ledger[str(root / "marksheet.pdf")]["ocr"] == "eng+mar"

        kb.loaded.clear()
        await self._pass(root, store, kb)
        assert kb.loaded == [], "same languages: nothing is read a third time"

    async def test_turning_recognition_off_keeps_what_was_read(self, tmp_path, monkeypatch):
        root, store = tmp_path / "library", tmp_path / "store"
        _write(root, "marksheet.pdf")
        kb = RecognisingKB()
        await self._pass(root, store, kb)

        monkeypatch.setenv(settings.env_name("OCR"), "off")
        kb.loaded.clear()
        await self._pass(root, store, kb)
        assert kb.loaded == [] and kb.docs == {"marksheet.pdf"}

    async def test_a_scan_stored_before_the_ledger_said_how_is_read_once(self, tmp_path):
        """0.12.0 stored scans without recording the languages. The file
        itself is looked at, once: a scan is read again, a typed PDF is not."""
        root, store = tmp_path / "library", tmp_path / "store"
        root.mkdir()
        scan = _scan(root / "PAN_Card.pdf", [NUMBER])
        typed = _text_pdf(root / "letter.pdf", "plain words")
        ledger = {}
        for path in (scan, typed):
            stat = path.stat()
            ledger[str(path)] = {
                "signature": [stat.st_mtime_ns, stat.st_size],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "stored": True,
                "doc_id": path.name,
            }
        store.mkdir()
        (store / LEDGER_NAME).write_text(json.dumps(ledger))
        kb = RecognisingKB(typed={"letter.pdf"})
        kb.docs = {"PAN_Card.pdf", "letter.pdf"}

        await self._pass(root, store, kb)
        assert kb.loaded == ["PAN_Card.pdf"]
        written = json.loads((store / LEDGER_NAME).read_text())
        assert written[str(scan)]["ocr"] == "eng"
        assert written[str(typed)]["ocr"] == ""

        kb.loaded.clear()
        await self._pass(root, store, kb)
        assert kb.loaded == []


class TestFindingPicturePages:
    def test_a_scan_has_them_and_a_typed_pdf_does_not(self, tmp_path):
        assert has_picture_pages(_scan(tmp_path / "scan.pdf", [NUMBER]))
        assert not has_picture_pages(_text_pdf(tmp_path / "typed.pdf", "words"))

    def test_anything_it_cannot_open_is_not_a_scan(self, tmp_path):
        (tmp_path / "broken.pdf").write_bytes(b"not a pdf")
        (tmp_path / "notes.md").write_text("words")
        assert not has_picture_pages(tmp_path / "broken.pdf")
        assert not has_picture_pages(tmp_path / "notes.md")


def test_downloads_check_certificates_from_certifi():
    """python.org's macOS Python has no certificates until a manual step; the
    language download must not depend on it."""
    import certifi

    context = ocr._tls()
    assert context.verify_mode.name == "CERT_REQUIRED"
    assert context.cert_store_stats()["x509_ca"] > 0
    assert certifi.where()
