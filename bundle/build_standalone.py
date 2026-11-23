"""Build a Claude Desktop bundle that carries its own Python: macOS, Apple silicon.

    ./.venv/bin/python bundle/build_standalone.py PYTHON_DIR [--offline]

PYTHON_DIR is an unpacked python-build-standalone "install_only" build for
macOS arm64 at the minor version this builds for (uv keeps one per version
under `~/.local/share/uv/python/`). The result is
`dist/sextant-<version>-macos-arm64.mcpb`.

Why it exists: the ordinary bundle (`build.py`) is the `uv` server type, so
Claude Desktop installs Python and the libraries at install time. On a Mac with
no Python 3.11-3.14 that means fetching Python from github.com, and a tester's
network timed out there. This one is the `binary` type: Python and every
library are inside, so installing downloads nothing. Since 0.12.6 the two
search models and English text-recognition data are inside too (`models/`),
so the first start downloads nothing either; the ordinary bundle still
fetches them from Hugging Face and GitHub then.

Two things a real install showed (0.12.4, 2026-11-19), which shape the launch:

- Claude Desktop unpacks a bundle with every file at mode 600, whatever the zip
  says. A Python inside it is therefore not executable, so the server is
  started by `/bin/sh` (present on every Mac) reading `launch.sh`, which marks
  the interpreter executable and then runs it.
- The unpacked files carry no quarantine flag, so Gatekeeper does not stop the
  interpreter; python-build-standalone signs it ad hoc, which Apple silicon
  requires and which `chmod` leaves intact.

It costs size: about 700 MB unpacked against the ordinary bundle's 214 KB, and
it serves one platform. The ordinary bundle stays the default.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PYTHON_MINOR = "3.12"
PLATFORM = "macos-arm64"

_spec = importlib.util.spec_from_file_location("bundle_build", Path(__file__).with_name("build.py"))
assert _spec and _spec.loader
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

# Inside the interpreter's own tree: the standard library's test suite, the
# GUI toolkit and IDLE, which a search server never imports.
PYTHON_SKIPPED = {"test", "idlelib", "tkinter", "turtledemo", "__pycache__", "ensurepip"}
PYTHON_SKIPPED_FILES = {"libtcl9.0.dylib", "libtk9.0.dylib"}

# The two default search models, each at a fixed revision so every build
# ships the same bytes, and only the files the ONNX loaders read
# (`onnx_models.py`); the torch weights beside them are left out. Both are
# Apache-2.0, which allows shipping them with its text and a notice.
MODELS = {
    "sentence-transformers/all-MiniLM-L6-v2": (
        "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        ("modules.json", "1_Pooling/config.json", "sentence_bert_config.json",
         "tokenizer.json", "onnx/model.onnx"),
    ),
    "cross-encoder/ms-marco-MiniLM-L6-v2": (
        "233902d25c440f23af6f7d6e94d2946bac0bee0a",
        ("config.json", "tokenizer.json", "onnx/model.onnx"),
    ),
}
# English only, the default. Another language is a choice made in the
# install dialog and downloads a few MB once, as before.
OCR_LANGUAGES = ("eng",)
MODEL_DIR_ENV = "SEXTANT_MODEL_DIR"

LAUNCH = f'''#!/bin/sh
# Started by Claude Desktop as `/bin/sh launch.sh`. The bundle is unpacked
# without execute bits, so the interpreter is made runnable first.
here="$(cd "$(dirname "$0")" && pwd)"
py="$here/python/bin/python{PYTHON_MINOR}"
[ -x "$py" ] || chmod u+x "$py"
# -E: no PYTHON* variable from the user's shell; -s: no user site-packages.
# Together they keep a Homebrew or conda setup from leaking in.
export {MODEL_DIR_ENV}="$here/models"
exec "$py" -E -s "$here/src/server.py" "$@"
'''

ENTRY = '''"""Bundle entry point: the sextant knowledge-base server over stdio."""

import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path[:0] = [str(here), str(here.parent / "lib")]

from sextant.vector_db.server import main  # noqa: E402

main()
'''


def manifest() -> dict:
    data = build.manifest()
    data["server"] = {
        "type": "binary",
        "entry_point": "launch.sh",
        "mcp_config": {
            "command": "/bin/sh",
            "args": ["${__dirname}/launch.sh"],
            "env": data["server"]["mcp_config"]["env"],
        },
    }
    data["compatibility"] = {"platforms": ["darwin"]}
    long = data["long_description"]
    cut = long.index(" Installing needs Python")
    data["long_description"] = long[:cut] + (
        " This edition is for Macs with Apple silicon and carries its own "
        "Python, libraries and search models, so it downloads nothing, at "
        "install or on its first start. Reading scans in a language other "
        "than English downloads a few MB once."
    )
    return data


def install_libraries(python: Path, target: Path, offline: bool) -> None:
    """The package's dependencies, for this interpreter, into `target`."""
    command = ["uv", "pip", "install", "--python", str(python), "--target", str(target),
               "--quiet", *build.project()["dependencies"]]
    if offline:
        command.insert(3, "--offline")
    subprocess.run(command, check=True)


def _apache_text(libraries: Path) -> str:
    """The Apache-2.0 licence text, from a library already in the bundle."""
    for path in sorted(libraries.glob("*.dist-info/licenses/LICENSE")):
        text = path.read_text(errors="replace")
        if text.lstrip().startswith("Apache License") and "Version 2.0" in text[:200]:
            return text
    raise SystemExit("no Apache-2.0 licence text among the libraries to ship beside the models")


def stage_models(target: Path, libraries: Path, offline: bool) -> None:
    """The search models and text-recognition data, laid out for `model_dir`."""
    import hashlib

    from huggingface_hub import hf_hub_download

    from sextant.vector_db import ocr

    notice = ["The search models in this folder are not part of sextant.", ""]
    for repo, (revision, files) in MODELS.items():
        for name in files:
            source = hf_hub_download(repo, name, revision=revision, local_files_only=offline)
            dest = target / repo.replace("/", "--") / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
        notice.append(f"{repo} at revision {revision}, https://huggingface.co/{repo}, "
                      "licensed under the Apache License 2.0 (LICENSE-Apache-2.0.txt).")
    tessdata = target / "tessdata"
    tessdata.mkdir(parents=True, exist_ok=True)
    for lang in OCR_LANGUAGES:
        name = f"{lang}.traineddata"
        found = next((d / name for d in ocr._candidates() if (d / name).is_file()), None)
        if found is None:
            if offline:
                raise SystemExit(f"{name} is not on this machine and --offline forbids fetching it")
            ocr._fetch(lang, tessdata)
        else:
            shutil.copyfile(found, tessdata / name)
        if hashlib.sha256((tessdata / name).read_bytes()).hexdigest() != ocr._PINNED[lang]:
            raise SystemExit(f"{name} does not match its published hash")
    notice.append(f"tessdata/: Tesseract's tessdata_fast {ocr._TAG}, "
                  "https://github.com/tesseract-ocr/tessdata_fast, Apache License 2.0.")
    (target / "NOTICE.txt").write_text("\n".join(notice) + "\n")
    (target / "LICENSE-Apache-2.0.txt").write_text(_apache_text(libraries))


def _add_tree(bundle: zipfile.ZipFile, source: Path, prefix: str, skipped: set[str]) -> None:
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if skipped & set(rel.parts) or path.name in PYTHON_SKIPPED_FILES:
            continue
        # A link would be stored as a second copy of its target; the launcher
        # names the interpreter by its real file, so links are left out.
        if path.is_symlink() or not path.is_file() or path.suffix in {".pyc", ".pyo"}:
            continue
        bundle.write(path, f"{prefix}/{rel.as_posix()}")


# Where python-build-standalone itself says it lives. uv rewrites this to the
# folder it unpacked into, which on the builder's Mac names the builder.
_STANDALONE_PREFIX = "/install"


def detach_from_builder(python_dir: Path, staged: Path) -> None:
    """Copy the interpreter to `staged`, minus every trace of where it was.

    uv stamps its install folder into two places: the build settings module
    and the shared library's own name. The first is text and is put back to
    the standalone build's placeholder; the second is reset to a path
    relative to the interpreter, which changes the library, so it is signed
    again ad hoc as Apple silicon requires.
    """
    shutil.copytree(python_dir, staged, symlinks=True)
    for config in staged.glob(f"lib/python{PYTHON_MINOR}/_sysconfigdata_*.py"):
        config.write_text(config.read_text().replace(str(python_dir), _STANDALONE_PREFIX))
    library = staged / "lib" / f"libpython{PYTHON_MINOR}.dylib"
    if library.exists():
        subprocess.run(["install_name_tool", "-id",
                        f"@executable_path/../lib/{library.name}", str(library)],
                       check=True, capture_output=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(library)],
                       check=True, capture_output=True)


def traces_of(marker: str, bundle_path: Path) -> list[str]:
    """Files in the bundle whose bytes contain `marker`, such as a home folder."""
    needle = marker.encode()
    with zipfile.ZipFile(bundle_path) as bundle:
        return [name for name in bundle.namelist() if needle in bundle.read(name)]


def build_bundle(python_dir: Path, out_dir: Path = ROOT / "dist", offline: bool = False) -> Path:
    interpreter = python_dir / "bin" / f"python{PYTHON_MINOR}"
    if not interpreter.is_file() or interpreter.is_symlink():
        raise SystemExit(f"{interpreter} is not a python{PYTHON_MINOR} interpreter file")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"sextant-{build.__version__}-{PLATFORM}.mcpb"
    with tempfile.TemporaryDirectory() as tmp:
        libraries = Path(tmp) / "lib"
        install_libraries(interpreter, libraries, offline)
        models = Path(tmp) / "models"
        stage_models(models, libraries, offline)
        staged = Path(tmp) / "python"
        detach_from_builder(python_dir.resolve(), staged)
        python_dir = staged
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest(), indent=2) + "\n")
            bundle.writestr("launch.sh", LAUNCH)
            bundle.writestr("src/server.py", ENTRY)
            bundle.write(ROOT / "LICENSE", "LICENSE")
            bundle.writestr("src/sextant/_bundle_version.py", f'VERSION = "{build.__version__}"\n')
            for path in build.package_files():
                bundle.write(path, "src/" + str(path.relative_to(ROOT)))
            _add_tree(bundle, python_dir, "python", PYTHON_SKIPPED)
            # `bin` holds the libraries' command-line scripts, unused here,
            # each starting with the builder's own interpreter path.
            _add_tree(bundle, libraries, "lib", {"__pycache__", "bin"})
            _add_tree(bundle, models, "models", set())
    # The bundle is published: it must not carry the builder's home folder.
    leaked = traces_of(str(Path.home()), target)
    if leaked:
        target.unlink()
        raise SystemExit(f"the builder's home folder is inside {len(leaked)} files: {leaked[:5]}")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("python_dir", type=Path)
    parser.add_argument("--offline", action="store_true", help="use only uv's cache")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    built = build_bundle(args.python_dir, args.out, args.offline)
    print(f"{built} ({built.stat().st_size // (1024 * 1024)} MB)")
    sys.exit(0)
