"""`sextant-kb --setup` and `--doctor`: get ready ahead of time, and say what is wrong."""

from __future__ import annotations

import io
import socket
import sys
from pathlib import Path

import pytest

from sextant.vector_db import onnx_models, setup


@pytest.fixture
def quiet_library(monkeypatch, tmp_path) -> Path:
    """A library and folder of the test's own, so the owner's are never read."""
    monkeypatch.setenv("SEXTANT_CHROMA_DIR", str(tmp_path / "store" / "chroma_db"))
    monkeypatch.delenv("SEXTANT_FOLDER", raising=False)
    monkeypatch.delenv("SEXTANT_ENGINE", raising=False)
    monkeypatch.setenv("SEXTANT_OCR", "off")
    return tmp_path


def _no_download(*args, **kwargs):
    raise AssertionError("the doctor must never download")


def test_doctor_names_the_fix_when_the_models_are_missing(monkeypatch, quiet_library) -> None:
    import huggingface_hub

    monkeypatch.setattr(onnx_models, "cached", lambda repo, filename: None)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _no_download)
    out = io.StringIO()
    assert setup.doctor(out) == 1
    fix = "FIX   The search models are not downloaded yet. Run: sextant-kb --setup"
    assert fix in out.getvalue()


def test_doctor_names_a_missing_folder(monkeypatch, quiet_library) -> None:
    monkeypatch.setattr(setup, "_load_models", lambda: None)
    monkeypatch.setenv("SEXTANT_FOLDER", str(quiet_library / "not-here"))
    out = io.StringIO()
    assert setup.doctor(out) == 1
    assert "does not exist. Fix the SEXTANT_FOLDER path." in out.getvalue()


def test_doctor_is_happy_when_everything_is_there(monkeypatch, quiet_library) -> None:
    monkeypatch.setattr(setup, "_load_models", lambda: None)
    folder = quiet_library / "docs"
    folder.mkdir()
    monkeypatch.setenv("SEXTANT_FOLDER", str(folder))
    out = io.StringIO()
    assert setup.doctor(out) == 0
    text = out.getvalue()
    assert f"Folder to search: {folder}" in text
    assert "shares this one library" in text
    assert text.endswith("All good.\n")


def test_no_folder_is_worth_knowing_not_a_failure(monkeypatch, quiet_library) -> None:
    monkeypatch.setattr(setup, "_load_models", lambda: None)
    out = io.StringIO()
    assert setup.doctor(out) == 0
    assert "  note  No folder set" in out.getvalue()


def test_setup_says_ready_once_the_models_run(monkeypatch, quiet_library) -> None:
    loaded = []
    monkeypatch.setattr(setup, "_load_models", lambda: loaded.append(True))
    out = io.StringIO()
    assert setup.setup(out) == 0
    assert loaded == [True]
    assert out.getvalue().rstrip().endswith("sextant now starts without the internet.")


def test_setup_is_not_ready_while_the_folder_is_wrong(monkeypatch, quiet_library) -> None:
    monkeypatch.setattr(setup, "_load_models", lambda: None)
    monkeypatch.setenv("SEXTANT_FOLDER", str(quiet_library / "not-here"))
    out = io.StringIO()
    assert setup.setup(out) == 1
    assert "Ready." not in out.getvalue()


def test_setup_fails_plainly_without_a_network(monkeypatch, quiet_library) -> None:
    def offline() -> None:
        raise OSError("network unreachable")

    monkeypatch.setattr(setup, "_load_models", offline)
    out = io.StringIO()
    assert setup.setup(out) == 1
    assert "Check the internet connection and run this again." in out.getvalue()
    assert "Ready." not in out.getvalue()


def test_the_server_command_runs_them(monkeypatch) -> None:
    from sextant.vector_db import server

    ran = []
    def run(flag: str) -> int:
        ran.append(flag)
        return 0

    monkeypatch.setattr(setup, "run", run)
    monkeypatch.setattr(sys, "argv", ["sextant-kb", "--doctor"])
    with pytest.raises(SystemExit) as stopped:
        server.main()
    assert stopped.value.code == 0
    assert ran == ["--doctor"]


def test_a_cached_start_never_touches_the_network(monkeypatch) -> None:
    """The models load from disk with every socket refused.

    huggingface_hub 2.x asks huggingface.co which AI tool is running it, even
    for `local_files_only`; this is what keeps that off a start.
    """
    name = "all-MiniLM-L6-v2"
    repo = onnx_models.EMBEDDER_REPOS[name]
    if onnx_models.cached(repo, onnx_models.ONNX_FILE) is None:
        pytest.skip("the search model is not downloaded on this machine")

    _detect_agent = pytest.importorskip("huggingface_hub.utils._detect_agent")

    # Recorded, not only raised: the hub swallows errors from its own lookup.
    attempts: list[str] = []

    def refuse(*args, **kwargs):
        attempts.append(repr(args[:2]))
        raise OSError("network refused by the test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(_detect_agent, "_registry", None, raising=False)
    monkeypatch.setattr(_detect_agent, "_load_registry", refuse)
    with onnx_models.no_download():
        embedder = onnx_models.OnnxEmbedder(name)
        reranker = onnx_models.OnnxReranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
    assert attempts == []
    assert len(embedder.encode_query("offline")) == 384
    assert len(reranker.predict([("a", "b")])) == 1
