"""The Mac bundle that carries its own Python (`bundle/build_standalone.py`).

The full build needs an unpacked python-build-standalone tree, which the gate
does not have; it was built and driven over MCP by hand (2026-11-23, see
PROGRESS.md). These pin what would break it silently on someone's Mac: the
launch from files unpacked without execute bits, the manifest the host reads,
and a symlink stored as a second copy.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "bundle_build_standalone", ROOT / "bundle" / "build_standalone.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


standalone = _load()


class TestTheManifest:
    def test_it_starts_with_the_shell_every_mac_has(self):
        server = standalone.manifest()["server"]
        assert server["type"] == "binary"
        assert server["mcp_config"]["command"] == "/bin/sh"
        assert server["mcp_config"]["args"] == ["${__dirname}/launch.sh"]
        assert server["entry_point"] == "launch.sh"

    def test_it_passes_the_same_settings_as_the_ordinary_bundle(self):
        ordinary = standalone.build.manifest()["server"]["mcp_config"]["env"]
        assert standalone.manifest()["server"]["mcp_config"]["env"] == ordinary

    def test_it_claims_only_the_platform_it_carries(self):
        manifest = standalone.manifest()
        assert manifest["compatibility"] == {"platforms": ["darwin"]}
        text = manifest["long_description"]
        assert "Apple silicon" in text and "downloads nothing" in text
        assert "github.com" not in text


@pytest.mark.skipif(os.name != "posix", reason="the launcher is a POSIX shell script")
class TestTheLauncher:
    def test_it_runs_an_interpreter_unpacked_without_execute_bits(self, tmp_path):
        """Claude Desktop unpacked 0.12.4 with every file at mode 600."""
        minor = standalone.PYTHON_MINOR
        (tmp_path / "python" / "bin").mkdir(parents=True)
        (tmp_path / "src").mkdir()
        fake = tmp_path / "python" / "bin" / f"python{minor}"
        fake.write_text('#!/bin/sh\necho "ran with $*"\n')
        (tmp_path / "launch.sh").write_text(standalone.LAUNCH)
        for path in (fake, tmp_path / "launch.sh"):
            path.chmod(0o600)

        result = subprocess.run(["/bin/sh", str(tmp_path / "launch.sh")],
                                capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})

        assert result.returncode == 0, result.stderr
        assert f"-E -s {tmp_path.resolve()}/src/server.py" in result.stdout
        assert fake.stat().st_mode & stat.S_IXUSR

    def test_the_entry_puts_the_libraries_on_the_path(self):
        assert 'here.parent / "lib"' in standalone.ENTRY


class TestTheCopy:
    def test_links_and_skipped_folders_stay_out(self, tmp_path):
        tree = tmp_path / "python"
        (tree / "bin").mkdir(parents=True)
        (tree / "lib" / "test").mkdir(parents=True)
        (tree / "bin" / "python3.12").write_text("real")
        (tree / "bin" / "python3").symlink_to("python3.12")
        (tree / "lib" / "test" / "big.py").write_text("x")
        (tree / "lib" / "os.py").write_text("x")

        out = tmp_path / "b.zip"
        with zipfile.ZipFile(out, "w") as bundle:
            standalone._add_tree(bundle, tree, "python", standalone.PYTHON_SKIPPED)

        assert sorted(zipfile.ZipFile(out).namelist()) == [
            "python/bin/python3.12", "python/lib/os.py"
        ]

    def test_it_refuses_a_folder_without_the_interpreter(self, tmp_path):
        with pytest.raises(SystemExit):
            standalone.build_bundle(tmp_path, tmp_path / "out")
