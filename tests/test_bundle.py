"""The Claude Desktop bundle: what `bundle/build.py` puts in the file.

The bundle is installed by a person who has no terminal open, so nothing in it
can be fixed after the double-click. These pin the parts that would fail
silently there: a manifest the host rejects, a dependency list that has
drifted from the package's, a folder setting that never reaches the server,
and a server that imports something the bundle does not carry.

The manifest is also checked against the format's own schema with
`mcpb validate` by hand -- that tool is an npm download and not in the gate.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from sextant import __version__, settings

ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    spec = importlib.util.spec_from_file_location("bundle_build", ROOT / "bundle" / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_builder()


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> zipfile.ZipFile:
    path = build.build(tmp_path_factory.mktemp("dist"))
    return zipfile.ZipFile(path)


def _manifest(bundle: zipfile.ZipFile) -> dict:
    return json.loads(bundle.read("manifest.json"))


class TestTheManifest:
    def test_it_carries_the_package_version(self, bundle):
        assert _manifest(bundle)["version"] == __version__

    def test_it_has_what_the_format_requires(self, bundle):
        manifest = _manifest(bundle)
        for key in ("manifest_version", "name", "version", "description", "author", "server"):
            assert manifest.get(key), key
        server = manifest["server"]
        assert server["type"] == "uv" and manifest["manifest_version"] == "0.4"
        assert server["entry_point"] in bundle.namelist()

    def test_the_chosen_folder_reaches_the_server_under_the_name_it_reads(self, bundle):
        manifest = _manifest(bundle)
        assert manifest["user_config"]["folder"]["type"] == "directory"
        assert manifest["user_config"]["folder"]["required"] is True
        env = manifest["server"]["mcp_config"]["env"]
        assert env == {
            settings.env_name("FOLDER"): "${user_config.folder}",
            settings.env_name("OCR_LANG"): "${user_config.ocr_languages}",
        }

    def test_the_scan_languages_are_optional_and_default_to_english(self, bundle):
        """Left empty, or passed through unfilled, it must still mean English
        (`ocr.languages`), never no recognition at all."""
        field = _manifest(bundle)["user_config"]["ocr_languages"]
        assert field["type"] == "string" and field["required"] is False
        assert field["default"] == "eng"

    def test_the_tools_it_lists_are_the_tools_the_server_registers(self, bundle):
        """The install dialog shows this list; a tool listed and not served,
        or served and not listed, is a claim the person cannot check."""
        source = (ROOT / "sextant" / "vector_db" / "server.py").read_text()
        registered = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.AsyncFunctionDef) and any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"
                for d in node.decorator_list
            ):
                registered.add(node.name)
        listed = {tool["name"] for tool in _manifest(bundle)["tools"]}
        assert listed == registered

    def test_the_python_it_asks_for_is_the_one_the_package_requires(self, bundle):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        asked = _manifest(bundle)["compatibility"]["runtimes"]["python"]
        assert asked == project["requires-python"]


class TestTheDependencies:
    def test_they_are_the_package_dependencies_exactly(self, bundle):
        root = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        inner = tomllib.loads(bundle.read("pyproject.toml").decode())["project"]
        assert inner["dependencies"] == root["dependencies"]
        assert inner["requires-python"] == root["requires-python"]


class TestTheSource:
    def test_the_folder_indexer_and_the_server_are_inside(self, bundle):
        names = set(bundle.namelist())
        for module in ("vector_db/server.py", "vector_db/folder.py", "settings.py"):
            assert f"src/sextant/{module}" in names, module

    def test_the_web_agent_and_caches_are_not(self, bundle):
        names = bundle.namelist()
        assert not [n for n in names if "/mcp_server/" in n]
        assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]

    def test_no_hidden_file_rides_along(self, tmp_path):
        """A Finder `.DS_Store` sits in this checkout and shipped in 0.10.0.
        Plant one so the test does not depend on what Finder left behind."""
        planted = ROOT / "sextant" / "eval" / ".planted-hidden"
        planted.write_text("x")
        try:
            names = zipfile.ZipFile(build.build(tmp_path)).namelist()
        finally:
            planted.unlink()
        assert not [n for n in names if any(p.startswith(".") for p in n.split("/"))]

    def test_nothing_the_server_loads_needs_what_was_left_out(self, bundle):
        """Walk the server's module-level imports through the copy in the
        bundle. A module it loads that is not in the file is an install that
        dies on its first start, where nobody can see why."""
        names = set(bundle.namelist())
        seen: set[str] = set()
        stack = ["sextant.vector_db.server"]
        missing: list[str] = []
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            base = "src/" + name.replace(".", "/")
            path = base + ".py" if base + ".py" in names else base + "/__init__.py"
            if path not in names:
                missing.append(name)
                continue
            for node in ast.parse(bundle.read(path)).body:
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    if node.module.startswith("sextant"):
                        stack.append(node.module)
                        stack.extend(
                            f"{node.module}.{a.name}"
                            for a in node.names
                            if "src/" + f"{node.module}.{a.name}".replace(".", "/") + ".py" in names
                        )
                elif isinstance(node, ast.Import):
                    stack.extend(a.name for a in node.names if a.name.startswith("sextant"))
        assert not missing, f"loaded by the server, absent from the bundle: {missing}"
        assert "sextant.vector_db.folder" in seen, "the walk should reach the folder indexer"

    def test_the_server_reports_the_bundle_version_without_package_metadata(
        self, bundle, tmp_path
    ):
        """The host installs the bundle's dependencies, never sextant itself,
        so the version cannot come from package metadata. `-S` hides this
        checkout's installed copy the same way."""
        bundle.extractall(tmp_path)
        out = subprocess.run(
            [sys.executable, "-I", "-S", "-c",
             f"import sys; sys.path.insert(0, {str(tmp_path / 'src')!r}); "
             "import sextant; print(sextant.__version__)"],
            capture_output=True, text=True, check=True,
        )
        assert out.stdout.strip() == __version__

    def test_the_entry_point_starts_the_server(self, bundle):
        entry = bundle.read("src/server.py").decode()
        assert "from sextant.vector_db.server import main" in entry
        assert entry.rstrip().endswith("main()")
