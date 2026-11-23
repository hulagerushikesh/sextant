"""Reading scanned pages: text recognition (OCR) for PDFs with no text layer.

A scanned PDF is pictures of pages. Until 0.12 the loader read no words from
one and the folder pass reported it as "needs OCR before it can be searched"
-- on the owner's own Downloads folder that was 19 of 60 files, and every ID
card and certificate among them.

MuPDF, which already reads every PDF here, has Tesseract built in. What it
does not ship is the per-language data file Tesseract reads (`eng.traineddata`
and so on), so no new Python package is needed, only that file:

- one already on the machine is used as it is: `TESSDATA_PREFIX`, then the
  copy the Mac bundle ships (`settings.model_dir`), then the places a
  Tesseract install puts them;
- otherwise English, Hindi and Marathi are fetched once, from the Tesseract
  project's own "fast" set at a fixed tag, checked against the hashes below,
  and kept in the user's cache. About 4 MB for English.

A page is recognised only when it has no text of its own and does hold an
image, so a PDF that reads normally is read exactly as before and costs
nothing. `SEXTANT_OCR=off` turns recognition off; `SEXTANT_OCR_LANG` picks
the languages, `eng+mar` style, default English.

Recognised text is a reading, not the file: a blurred photo gives wrong
characters, and those are what search will match. The loader records which
pages were recognised, so that is never invisible.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import ssl
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sextant import settings

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGES = "eng"
# High enough for the small print on an ID card; 300 is Tesseract's own advice.
DPI = 300

# tessdata_fast at a tag, never a branch: the hash below is of that file.
_TAG = "4.1.0"
_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{tag}/{lang}.traineddata"
_PINNED = {
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "hin": "4c73ffc59d497c186b19d1e90f5d721d678ea6b2e277b719bee4e2af12271825",
    "mar": "0ba3f2d116972e72fe9e176bc84c38e81dfb6670f4ed1f7f6c8e16a27da7cb61",
}
_FETCH_TIMEOUT_S = 60

# Where Tesseract installs put the files. A launcher such as Claude Desktop
# starts the server with a short PATH, so nothing here may depend on finding
# the `tesseract` program; MuPDF needs only the data files.
_SYSTEM_DIRS = (
    "/opt/homebrew/share/tessdata",
    "/usr/local/share/tessdata",
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/share/tessdata",
    r"C:\Program Files\Tesseract-OCR\tessdata",
)

_LANGUAGE = re.compile(r"^[a-z][a-z0-9_]*$")


class OcrUnavailable(RuntimeError):
    """Text recognition cannot run; the message says why in plain words."""


@dataclass(frozen=True)
class Reader:
    languages: str  # Tesseract's form: "eng+mar"
    tessdata: str


def enabled() -> bool:
    value = (settings.getenv("OCR") or "").strip().lower()
    return value not in ("off", "0", "false", "no")


def languages() -> list[str]:
    """The languages asked for, in order; English when nothing usable was set.

    A placeholder a launcher failed to fill in (`${user_config...}`) counts as
    unset, the same rule `folder.configured` applies to the folder.
    """
    raw = (settings.getenv("OCR_LANG") or "").strip().lower()
    if not raw or raw.startswith("${"):
        raw = DEFAULT_LANGUAGES
    found = [part for part in re.split(r"[+,\s]+", raw) if part]
    good = [part for part in found if _LANGUAGE.match(part)]
    return list(dict.fromkeys(good)) or [DEFAULT_LANGUAGES]


def signature() -> str:
    """What recognition would be asked to do now: `""` when it is off.

    The folder pass records this beside a scan it could not read, and tries
    the file again when it changes -- recognition turned on, a language added.
    """
    return "+".join(languages()) if enabled() else ""


def cache_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "sextant" / "tessdata"


def _candidates() -> list[Path]:
    dirs: list[Path] = []
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix:
        dirs.append(Path(prefix))
    shipped = settings.model_dir()
    if shipped is not None:
        dirs.append(shipped / "tessdata")
    dirs.append(cache_dir())
    dirs.extend(Path(d) for d in _SYSTEM_DIRS)
    return dirs


def _tls() -> ssl.SSLContext:
    """Certificates to check the download with.

    The python.org installer for macOS ships without any until its
    "Install Certificates" step is run, which nobody does, and every https
    download then fails with CERTIFICATE_VERIFY_FAILED. certifi's bundle comes
    with the search dependencies; the system's is the fallback.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch(lang: str, target: Path) -> None:
    """Download one pinned language file into `target`, or raise OcrUnavailable."""
    expected = _PINNED[lang]
    url = _URL.format(tag=_TAG, lang=lang)
    target.mkdir(parents=True, exist_ok=True)
    logger.info("fetching text-recognition data for %r from %s", lang, url)
    try:
        with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_S, context=_tls()) as response:  # noqa: S310
            data = response.read()
    except OSError as e:
        raise OcrUnavailable(
            f"the text-recognition data for '{lang}' could not be downloaded ({e})"
        ) from e
    if hashlib.sha256(data).hexdigest() != expected:
        raise OcrUnavailable(
            f"the text-recognition data downloaded for '{lang}' did not match "
            "its published hash, so it was not used"
        )
    with tempfile.NamedTemporaryFile(dir=target, delete=False) as tmp:
        tmp.write(data)
    Path(tmp.name).replace(target / f"{lang}.traineddata")


def _resolve(wanted: list[str]) -> Reader:
    """Find, or fetch, every language file, all in one folder -- Tesseract
    takes one data folder, so files found in two places are gathered into
    the cache."""
    found: dict[str, Path] = {}
    for lang in wanted:
        for folder in _candidates():
            if (folder / f"{lang}.traineddata").is_file():
                found[lang] = folder
                break

    homes = set(found.values())
    if len(found) == len(wanted) and len(homes) == 1:
        return Reader("+".join(wanted), str(homes.pop()))

    cache = cache_dir()
    for lang in wanted:
        if (cache / f"{lang}.traineddata").is_file():
            continue
        if lang in found:
            cache.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(found[lang] / f"{lang}.traineddata", cache / f"{lang}.traineddata")
        elif lang in _PINNED:
            _fetch(lang, cache)
        else:
            raise OcrUnavailable(
                f"there is no text-recognition data for the language '{lang}'; "
                f"put {lang}.traineddata in {cache} or install it with Tesseract"
            )
    return Reader("+".join(wanted), str(cache))


_lock = threading.Lock()
_resolved: dict[str, Reader | OcrUnavailable] = {}


def reader() -> Reader:
    """The reader for the current settings, resolved once per process.

    A failure is remembered too: a folder of 19 scans must not try a dead
    network 19 times. The next start tries again.
    """
    if not enabled():
        raise OcrUnavailable("text recognition is turned off (SEXTANT_OCR=off)")
    wanted = languages()
    key = "+".join(wanted)
    with _lock:
        if key not in _resolved:
            try:
                _resolved[key] = _resolve(wanted)
            except OcrUnavailable as e:
                _resolved[key] = e
            except OSError as e:
                _resolved[key] = OcrUnavailable(
                    f"the text-recognition data could not be saved ({e})"
                )
        result = _resolved[key]
    if isinstance(result, OcrUnavailable):
        raise result
    return result


def status() -> dict[str, Any]:
    """For `kb_stats`: whether scans can be read, without fetching anything."""
    if not enabled():
        return {"on": False, "note": "text recognition is turned off (SEXTANT_OCR=off)"}
    key = "+".join(languages())
    with _lock:
        result = _resolved.get(key)
    if isinstance(result, OcrUnavailable):
        return {"on": False, "languages": key, "note": str(result)}
    return {"on": True, "languages": key}


def textpage(page: Any) -> Any:
    """MuPDF's recognised text for one page, in the form `get_text` takes.

    Raises OcrUnavailable when recognition cannot run.
    """
    r = reader()
    return page.get_textpage_ocr(language=r.languages, dpi=DPI, full=True, tessdata=r.tessdata)


def _forget() -> None:
    """Drop what was resolved. For tests that change the settings."""
    with _lock:
        _resolved.clear()
