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
library are inside, so installing downloads nothing. The search models are
still fetched from Hugging Face on first start, as with the ordinary bundle.

Two things a real install showed (0.12.4, 2026-11-19), which shape the launch:

- Claude Desktop unpacks a bundle with every file at mode 600, whatever the zip
  says. A Python inside it is therefore not executable, so the server is
  started by `/bin/sh` (present on every Mac) reading `launch.sh`, which marks
  the interpreter executable and then runs it.
- The unpacked files carry no quarantine flag, so Gatekeeper does not stop the
  interpreter; python-build-standalone signs it ad hoc, which Apple silicon
  requires and which `chmod` leaves intact.

It costs size: about 530 MB unpacked against the ordinary bundle's 214 KB, and
it serves one platform. The ordinary bundle stays the default.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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

LAUNCH = f'''#!/bin/sh
# Started by Claude Desktop as `/bin/sh launch.sh`. The bundle is unpacked
# without execute bits, so the interpreter is made runnable first.
here="$(cd "$(dirname "$0")" && pwd)"
py="$here/python/bin/python{PYTHON_MINOR}"
[ -x "$py" ] || chmod u+x "$py"
# -E: no PYTHON* variable from the user's shell; -s: no user site-packages.
# Together they keep a Homebrew or conda setup from leaking in.
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
        "Python and libraries, so installing downloads nothing."
    )
    return data


def install_libraries(python: Path, target: Path, offline: bool) -> None:
    """The package's dependencies, for this interpreter, into `target`."""
    command = ["uv", "pip", "install", "--python", str(python), "--target", str(target),
               "--quiet", *build.project()["dependencies"]]
    if offline:
        command.insert(3, "--offline")
    subprocess.run(command, check=True)


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


def build_bundle(python_dir: Path, out_dir: Path = ROOT / "dist", offline: bool = False) -> Path:
    interpreter = python_dir / "bin" / f"python{PYTHON_MINOR}"
    if not interpreter.is_file() or interpreter.is_symlink():
        raise SystemExit(f"{interpreter} is not a python{PYTHON_MINOR} interpreter file")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"sextant-{build.__version__}-{PLATFORM}.mcpb"
    with tempfile.TemporaryDirectory() as tmp:
        libraries = Path(tmp) / "lib"
        install_libraries(interpreter, libraries, offline)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest(), indent=2) + "\n")
            bundle.writestr("launch.sh", LAUNCH)
            bundle.writestr("src/server.py", ENTRY)
            bundle.write(ROOT / "LICENSE", "LICENSE")
            bundle.writestr("src/sextant/_bundle_version.py", f'VERSION = "{build.__version__}"\n')
            for path in build.package_files():
                bundle.write(path, "src/" + str(path.relative_to(ROOT)))
            _add_tree(bundle, python_dir, "python", PYTHON_SKIPPED)
            _add_tree(bundle, libraries, "lib", {"__pycache__"})
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
