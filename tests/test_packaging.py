"""What `pip install sextant-kb` puts on somebody else's machine.

Nothing in this repository had ever built a wheel. Every check was run
against an editable install, which resolves a directory on disk and so
cannot see the three things a wheel decides:

1. **Which packages are in it.** The hand-written `packages` list named
   four and omitted `tools.vector_db.ann`, so every wheel it would have
   produced was missing the index implementations. Item 21's shape -- a
   list mirroring the tree by hand falls behind the tree silently -- in
   the one file where falling behind ships.

2. **What top level it lands in.** Until 0.9.0 the import packages were
   `tools`, `mcp_server` and `eval`. All three are *already distributions
   on PyPI*, so a release would have dropped three squatted generic names
   into every installer's `site-packages`. A name that is fine inside a
   checkout is not fine inside everybody else's.

3. **What it drags in.** The knowledge base is the part other people want;
   the FastAPI agent server is not. If `fastapi` is a base dependency then
   mounting this in Claude Desktop installs a web framework that is never
   started.

These run offline and in a second. The wheel is also built and launched
by hand -- see `planning/PROGRESS.md` for the measurement -- but a check
that needs a two-gigabyte download is a check nobody runs.
"""

from __future__ import annotations

import ast
import pathlib
import re
import tomllib
from fnmatch import fnmatch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "sextant"
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())

# Needs a network service or an API key, so it may not be a base dependency
# and may not be imported at module level by anything the subprocess loads.
EXTRA_ONLY = {"fastapi", "uvicorn", "google", "faiss"}


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = rel.parts[:-1] if rel.name == "__init__" else rel.parts
    return ".".join(parts)


def _imports(path: pathlib.Path, *, module_level_only: bool) -> set[str]:
    """Top-level package names imported by `path`.

    `module_level_only` keeps the distinction the whole file turns on: an
    import inside a function runs when that function is called, so it is a
    dependency of a feature. An import at module level runs on `import`, so
    it is a dependency of the package.
    """
    tree = ast.parse(path.read_text())
    nodes = tree.body if module_level_only else ast.walk(tree)
    found: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def _closure(entry: str) -> set[str]:
    """Every module in this package that importing `entry` would load."""
    seen: set[str] = set()
    stack = [entry]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        path = ROOT / (name.replace(".", "/") + ".py")
        if not path.exists():
            path = ROOT / name.replace(".", "/") / "__init__.py"
            if not path.exists():
                continue
        seen.add(name)
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.Import):
                stack.extend(a.name for a in node.names if a.name.startswith("sextant"))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module.startswith("sextant"):
                    stack.append(node.module)
                    stack.extend(f"{node.module}.{a.name}" for a in node.names)
    return seen


class TestTheWheelCarriesTheWholeTree:
    def test_every_package_in_the_tree_is_found(self):
        """Found, not listed -- and the found set must be the real one."""
        on_disk = {
            _module_name(p / "__init__.py")
            for p in [PACKAGE, *PACKAGE.rglob("*")]
            if p.is_dir() and (p / "__init__.py").exists()
        }
        include = PYPROJECT["tool"]["setuptools"]["packages"]["find"]["include"]
        assert include == ["sextant*"], include
        # The directories the discarded hand-written list would have missed.
        assert "sextant.vector_db.ann" in on_disk
        assert {"sextant", "sextant.vector_db", "sextant.mcp_server", "sextant.eval"} <= on_disk

    def test_nothing_is_published_under_a_generic_top_level_name(self):
        """`tools`, `eval` and `mcp-server` are all taken on PyPI.

        The claim is about what the wheel *publishes*, not what exists:
        `tests/` is a package in this tree and must stay out of it.
        """
        include = PYPROJECT["tool"]["setuptools"]["packages"]["find"]["include"]
        tops = {
            p.name
            for p in ROOT.iterdir()
            if p.is_dir() and (p / "__init__.py").exists() and not p.name.startswith(".")
        }
        published = {t for t in tops if any(fnmatch(t, pattern) for pattern in include)}
        assert published == {"sextant"}, f"a second published top level: {published}"
        assert "tests" in tops and "tests" not in published
        assert not ({"tools", "eval", "mcp_server"} & tops), "a name PyPI already has"


class TestTheBaseInstallIsAKnowledgeBase:
    def test_the_web_framework_is_an_extra(self):
        base = " ".join(PYPROJECT["project"]["dependencies"])
        extras = PYPROJECT["project"]["optional-dependencies"]
        for name in ("fastapi", "uvicorn"):
            assert name not in base, f"{name} is a base dependency"
            assert name in " ".join(extras["app"]), f"{name} is in no extra"

    def test_the_model_client_is_an_extra(self):
        base = " ".join(PYPROJECT["project"]["dependencies"])
        extras = PYPROJECT["project"]["optional-dependencies"]
        assert "google-genai" not in base
        assert "google-genai" in " ".join(extras["gen"])

    def test_nothing_the_subprocess_loads_needs_an_extra(self):
        """The claim behind the split, checked at the import graph.

        `summaries.py` imports `google.genai` *inside* the function that
        needs it and raises `SummariesUnavailable` naming the extra, which
        is why a base install can ingest text. Move that import to the top
        and the base install stops starting -- with no other symptom, and
        only on a machine that is not this one.
        """
        closure = _closure("sextant.vector_db.server")
        assert len(closure) >= 10, f"the scan found only {closure}"
        offenders = {}
        for name in sorted(closure):
            path = ROOT / (name.replace(".", "/") + ".py")
            if not path.exists():
                continue
            bad = _imports(path, module_level_only=True) & EXTRA_ONLY
            if bad:
                offenders[name] = sorted(bad)
        assert not offenders, f"loaded by `sextant-kb`, installed only by an extra: {offenders}"

    def test_the_lazy_import_is_still_lazy(self):
        """Anti-vacuity for the test above: the name is imported somewhere."""
        summaries = PACKAGE / "vector_db" / "summaries.py"
        assert "google" in _imports(summaries, module_level_only=False)
        assert "google" not in _imports(summaries, module_level_only=True)


class TestEveryConsoleScriptResolves:
    @pytest.mark.parametrize("script", sorted(PYPROJECT["project"]["scripts"]))
    def test_the_entry_point_names_something_that_exists(self, script):
        """A rename breaks these silently: the console script is generated at
        install time and nothing imports it, so `sextant-kb` keeps existing
        as a file on PATH and fails only when somebody runs it."""
        target = PYPROJECT["project"]["scripts"][script]
        module_name, _, attribute = target.partition(":")
        path = ROOT / (module_name.replace(".", "/") + ".py")
        assert path.exists(), f"{script} -> {module_name}, which is not a module"
        tree = ast.parse(path.read_text())
        defined = {
            n.name
            for n in tree.body
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        assert attribute in defined, f"{script} -> {target}, which does not exist"


class TestTheTreeShapeIsKnownInOnePlace:
    """Four modules answered "where is the root?" with their own `parents[N]`.

    Moving three packages one level down in 0.9.0 broke two of them and
    left two right, and the suite only caught it because a *different*
    copy disagreed -- `observability.py`, whose own docstring says two
    defaults for one location "is exactly the kind of drift this
    repository keeps paying for". It was one of the two that broke.
    """

    def test_only_settings_computes_the_root(self):
        offenders = []
        for path in sorted(PACKAGE.rglob("*.py")):
            if path == PACKAGE / "settings.py":
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if "parents[" in line or ".parent.parent" in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        assert not offenders, f"computes the tree's shape by hand: {offenders}"

    def test_an_installed_package_does_not_store_documents_in_site_packages(self, tmp_path):
        """No `pyproject.toml` beside the package means no checkout."""
        from sextant import settings

        assert settings.repo_root() == ROOT
        assert settings.default_store() == ROOT / "chroma_db"
        # The installed case, driven through the one function that decides it.
        package = tmp_path / "sextant"
        package.mkdir()
        (package / "settings.py").write_text((PACKAGE / "settings.py").read_text())
        (package / "__init__.py").write_text("")
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c", "from sextant import settings; print(settings.repo_root())"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "None", result.stdout


class TestTheVersionIsNotWrittenTwice:
    """`MCPServer(version=...)` was the literal `"0.4.0"`.

    The project was on 0.8.7. That string is what an MCP client shows the
    person who mounted this server, so for five releases every Claude
    Desktop listing it was wrong -- and nothing could notice, because the
    only other copy of the number lives in `pyproject.toml` and nothing
    compared them. Found by building a wheel and launching it, which is
    also the only way it could have been found.
    """

    def test_the_package_reports_the_distribution_version(self):
        import sextant

        assert sextant.__version__ == PYPROJECT["project"]["version"]

    def test_the_mcp_server_advertises_it_rather_than_a_literal(self):
        from sextant.vector_db.server import mcp

        assert getattr(mcp, "version", None) == PYPROJECT["project"]["version"]

    def test_no_version_literal_is_left_in_the_package(self):
        """A second copy is how the first one fell behind."""
        pattern = re.compile(r'version\s*=\s*["\']\d+\.\d+')
        offenders = [
            f"{path.relative_to(ROOT)}:{number}"
            for path in sorted(PACKAGE.rglob("*.py"))
            for number, line in enumerate(path.read_text().splitlines(), 1)
            if pattern.search(line)
        ]
        assert not offenders, f"a hand-written version: {offenders}"
