"""Build the Claude Desktop bundle: `dist/sextant-<version>.mcpb`.

    ./.venv/bin/python bundle/build.py

A bundle is a zip with a `manifest.json` at its root. Claude Desktop opens it
with a double-click, shows the install dialog, asks for the one setting the
manifest declares -- the folder to search -- and launches the server with
that folder in `SEXTANT_FOLDER`. `sextant/vector_db/folder.py` does the rest.

It is the `uv` server type: the bundle carries the source and a
`pyproject.toml` naming the dependencies, and the host installs them. That
type is marked experimental by the bundle format's own README (checked
2026-11-15), so whether a given Claude Desktop runs it is something only an
install on a real machine shows.

Why the source travels inside rather than a dependency on `sextant-kb`: the
bundle is then exactly this tree, testable before anything is published, and
it cannot drift onto a different release than the one it was built beside.
The dependencies are read from the root `pyproject.toml`, never written here,
so the two cannot disagree either.

Nothing here needs Node or the bundle CLI. `mcpb pack` is a zip plus a schema
check; the zip is below, and the schema check is `mcpb validate`, which is
worth running by hand after a change to the manifest.
"""

from __future__ import annotations

import json
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sextant import __version__  # noqa: E402

# Skipped inside the package. The bundle searches documents; it does not run
# the web agent, the evaluation corpus or caches from this checkout.
EXCLUDED_DIRS = {"__pycache__", "mcp_server"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}

# Starts the server from the copy of the package beside it. `uv run` installs
# the dependencies into a project environment without installing the project,
# so the package is found on the path, not in site-packages.
ENTRY = '''"""Bundle entry point: the sextant knowledge-base server over stdio."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sextant.vector_db.server import main  # noqa: E402

main()
'''

TOOLS = [
    ("kb_search", "Search your documents and return cited passages"),
    ("kb_list", "List the documents in your library and what each is about"),
    ("kb_stats", "Report how many documents are indexed and any that could not be read"),
    ("kb_ingest", "Add text to the library"),
    ("kb_ann_benchmark", "Benchmark the approximate search indexes"),
    ("kb_ann_compare", "Compare exact and approximate search on one question"),
    ("kb_selftest_sample", "Pick passages for a self-test of search on your library"),
    ("kb_selftest_grade", "Score how often search finds the passage each test question came from"),
]


def project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def manifest() -> dict:
    meta = project()
    return {
        "manifest_version": "0.4",
        "name": "sextant",
        "display_name": "sextant",
        "version": __version__,
        "description": "Search your own documents from Claude, with the source of every passage.",
        "long_description": (
            "Choose a folder of PDF, Markdown or text files. sextant indexes it on "
            "your computer and gives Claude a search tool that answers with the "
            "file and page each passage came from. No account and no key; your "
            "documents are not uploaded anywhere by this extension. The first "
            "start downloads the search models (about 180 MB) and indexes the "
            "folder, which takes a few minutes for a large one. Scanned PDFs are "
            "read with text recognition, which downloads a few MB more the first "
            "time it meets one."
        ),
        "author": {"name": meta["authors"][0]["name"]},
        "repository": {"type": "git", "url": meta["urls"]["Repository"]},
        "homepage": meta["urls"]["Homepage"],
        "license": meta["license"],
        "keywords": ["search", "documents", "rag", "knowledge-base", "pdf"],
        "server": {
            "type": "uv",
            "entry_point": "src/server.py",
            "mcp_config": {
                "command": "uv",
                "args": ["run", "--directory", "${__dirname}", "src/server.py"],
                "env": {
                    "SEXTANT_FOLDER": "${user_config.folder}",
                    "SEXTANT_OCR_LANG": "${user_config.ocr_languages}",
                },
            },
        },
        "user_config": {
            "folder": {
                "type": "directory",
                "title": "Folder to search",
                "description": (
                    "A folder of PDF, Markdown or text files. Sub-folders are included; "
                    "hidden folders are skipped."
                ),
                "required": True,
            },
            "ocr_languages": {
                "type": "string",
                "title": "Languages in scanned files",
                "description": (
                    "Scanned PDFs are read with text recognition. Name the languages "
                    "they are written in, joined by +: eng+mar for English and "
                    "Marathi, eng+hin for English and Hindi. The data for each is "
                    "downloaded once, a few MB."
                ),
                "default": "eng",
                "required": False,
            },
        },
        "tools": [{"name": n, "description": d} for n, d in TOOLS],
        "compatibility": {
            "platforms": ["darwin", "linux", "win32"],
            "runtimes": {"python": meta["requires-python"]},
        },
    }


def pyproject() -> str:
    meta = project()
    deps = "\n".join(f"    {json.dumps(d)}," for d in meta["dependencies"])
    return (
        "# Generated by bundle/build.py from the repository's pyproject.toml.\n"
        "[project]\n"
        'name = "sextant-bundle"\n'
        f'version = "{__version__}"\n'
        f'requires-python = "{meta["requires-python"]}"\n'
        f"dependencies = [\n{deps}\n]\n"
    )


def package_files() -> list[Path]:
    files = []
    for path in sorted((ROOT / "sextant").rglob("*")):
        rel = path.relative_to(ROOT)
        if not path.is_file() or path.suffix in EXCLUDED_SUFFIXES:
            continue
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        # Finder's .DS_Store and any other hidden file: 0.10.0 shipped two.
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(path)
    return files


def build(out_dir: Path = ROOT / "dist") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"sextant-{__version__}.mcpb"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest(), indent=2) + "\n")
        bundle.writestr("pyproject.toml", pyproject())
        bundle.writestr("src/server.py", ENTRY)
        bundle.write(ROOT / "LICENSE", "LICENSE")
        bundle.writestr("src/sextant/_bundle_version.py", f'VERSION = "{__version__}"\n')
        for path in package_files():
            bundle.write(path, "src/" + str(path.relative_to(ROOT)))
    return target


if __name__ == "__main__":
    built = build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist")
    print(f"{built} ({built.stat().st_size // 1024} KB)")
