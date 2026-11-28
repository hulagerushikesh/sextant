"""`sextant-kb --setup` and `sextant-kb --doctor`.

`--setup` fetches everything the server needs before an assistant starts
it: the two search models and the English text-recognition data. Without it
the first start downloads about 180 MB inside the assistant, which gives up
waiting on a slow network and reports sextant as broken. After it, a start
needs no network at all.

`--doctor` downloads nothing. It says, one plain line per check, whether
sextant would start and what to do when it would not. A check that fails
makes the exit code 1, so a script can use it too.

Both write to stdout: they run in a terminal, never as the MCP server, so
the protocol channel is not involved.
"""

from __future__ import annotations

import os
import sys
import time
from typing import TextIO

from sextant import __version__
from sextant.vector_db import ocr
from sextant.vector_db.onnx_models import (
    EMBEDDER_REPOS,
    ModelMissing,
    OnnxEmbedder,
    OnnxReranker,
    engine,
    no_download,
)

# The installer refuses anything else (`requires-python`); this catches a
# Python reached some other way, such as a copied environment.
PYTHON_RANGE = ((3, 11), (3, 15))

OK = "  ok    "
FIX = "  FIX   "
NOTE = "  note  "


def _mark(good: bool | None) -> str:
    return NOTE if good is None else OK if good else FIX


def _python_line() -> tuple[bool, str]:
    low, high = PYTHON_RANGE
    version = ".".join(str(n) for n in sys.version_info[:3])
    if low <= sys.version_info[:2] < high:
        return True, f"Python {version}"
    return False, (
        f"Python {version} is not supported; sextant needs 3.11 to 3.14. "
        "Install with uv, which picks a supported one: see the README."
    )


def _models() -> tuple[str, str]:
    from sextant.vector_db.embeddings import configured_model
    from sextant.vector_db.retrieval import RERANK_MODEL

    return configured_model(), RERANK_MODEL


def _load_models() -> None:
    """Load both search models and run each once, so 'ready' is proven."""
    embedder_name, reranker_name = _models()
    embedder = OnnxEmbedder(embedder_name)
    if len(embedder.encode_query("is this ready")) == 0:
        raise RuntimeError("the search model returned an empty vector")
    reranker = OnnxReranker(reranker_name)
    reranker.predict([("is this ready", "a test passage")])


def _folder_lines() -> list[tuple[bool | None, str]]:
    """(True: fine, False: needs fixing, None: worth knowing, line)."""
    from sextant.vector_db.folder import configured

    folder = configured()
    if folder is None:
        return [
            (
                None,
                "No folder set: the assistant searches only what was added with "
                "sextant-ingest. Set SEXTANT_FOLDER in the assistant's settings to "
                "keep a folder in sync.",
            )
        ]
    if not folder.exists():
        return [(False, f"The folder {folder} does not exist. Fix the SEXTANT_FOLDER path.")]
    if not folder.is_dir():
        return [(False, f"{folder} is a file, not a folder. Point SEXTANT_FOLDER at a folder.")]
    try:
        next(iter(os.scandir(folder)), None)
    except PermissionError:
        return [
            (
                False,
                f"The folder {folder} cannot be read. On a Mac, give the assistant "
                "access in System Settings → Privacy & Security → Files and Folders.",
            )
        ]
    return [(True, f"Folder to search: {folder}")]


def _library_line() -> tuple[bool, str]:
    from filelock import FileLock, Timeout

    from sextant.vector_db.sharing import lock_path
    from sextant.vector_db.vector_search import persist_dir

    store = persist_dir()
    if not store.exists():
        return True, f"Library: {store} (created on the first start)"
    if not lock_path(store).exists():  # never opened by a server: nobody holds it
        return True, f"Library: {store}"
    lock = FileLock(str(lock_path(store)), thread_local=False)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return True, (
            f"Library: {store}, open in an assistant right now. That is normal; "
            "quit the assistant before running sextant-ingest or sextant-forget."
        )
    lock.release()
    return True, f"Library: {store}"


def _shared_note() -> str:
    return (
        "Every assistant on this computer shares this one library, whatever folder "
        "each is given: a document added from one can answer a question in another."
    )


def setup(out: TextIO | None = None) -> int:
    """Fetch everything, prove the models run, say where things are."""
    out = out or sys.stdout

    def say(line: str) -> None:
        out.write(line + "\n")
        out.flush()

    say(f"sextant {__version__}: getting ready. The first time downloads about 180 MB.")
    good, line = _python_line()
    say((OK if good else FIX) + line)
    if not good:
        return 1

    if engine() == "torch":
        say(NOTE + "SEXTANT_ENGINE=torch: the models download on the first start instead.")
    else:
        embedder_name, _ = _models()
        if embedder_name not in EMBEDDER_REPOS:
            say(NOTE + f"{embedder_name} downloads on the first start instead.")
        else:
            started = time.monotonic()
            try:
                _load_models()
            except Exception as e:  # noqa: BLE001 - any failure is the same advice
                say(
                    FIX
                    + f"The search models could not be downloaded ({e}). Check the "
                    "internet connection and run this again."
                )
                return 1
            say(OK + f"Search models ready ({time.monotonic() - started:.0f} s)")

    if ocr.enabled():
        try:
            reader = ocr.reader()
        except ocr.OcrUnavailable as e:
            say(NOTE + f"Scanned PDFs: {e}. Text PDFs and notes still work.")
        else:
            say(OK + f"Scanned PDFs can be read ({reader.languages})")

    checks: list[tuple[bool | None, str]] = [*_folder_lines(), _library_line()]
    for state, line in checks:
        say(_mark(state) + line)
    say(NOTE + _shared_note())
    if any(state is False for state, _ in checks):
        say("Almost ready: fix the line marked FIX, then start your assistant.")
        return 1
    say("Ready. Start your assistant; sextant now starts without the internet.")
    return 0


def doctor(out: TextIO | None = None) -> int:
    """Check, download nothing, name one fix per problem."""
    out = out or sys.stdout
    failed = False

    def say(good: bool | None, line: str) -> None:
        nonlocal failed
        failed = failed or good is False
        out.write(_mark(good) + line + "\n")

    out.write(f"sextant {__version__}: checking this computer. Nothing is downloaded.\n")
    say(*_python_line())

    embedder_name, _ = _models()
    if engine() == "torch" or embedder_name not in EMBEDDER_REPOS:
        out.write(NOTE + "Search models: not checked for this engine or model.\n")
    else:
        try:
            with no_download():
                _load_models()
        except Exception as e:  # noqa: BLE001
            missing = isinstance(e, ModelMissing) or isinstance(e.__cause__, ModelMissing)
            say(
                False,
                "The search models are not downloaded yet. Run: sextant-kb --setup"
                if missing
                else f"The search models are present but did not load ({e}). "
                "Run: sextant-kb --setup",
            )
        else:
            say(True, "Search models downloaded and working")

    if not ocr.enabled():
        out.write(NOTE + "Scanned PDFs: text recognition is turned off (SEXTANT_OCR=off)\n")
    else:
        missing_langs = [lang for lang in ocr.languages() if ocr.present(lang) is None]
        if missing_langs:
            out.write(
                NOTE
                + f"Scanned PDFs: data for {', '.join(missing_langs)} downloads the "
                "first time a scan is read (or run sextant-kb --setup now)\n"
            )
        else:
            say(True, f"Scanned PDFs can be read ({'+'.join(ocr.languages())})")

    for good, line in [*_folder_lines(), _library_line()]:
        say(good, line)
    out.write(NOTE + _shared_note() + "\n")
    out.write(
        "Something needs fixing: see the lines marked FIX.\n" if failed else "All good.\n"
    )
    return 1 if failed else 0


def run(flag: str) -> int:
    """Entry for `sextant-kb --setup` / `--doctor`."""
    return setup() if flag == "--setup" else doctor()

