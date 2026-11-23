"""The Mac bundle that carries its own Python (`bundle/build_standalone.py`).

The full build needs an unpacked python-build-standalone tree, which the gate
does not have; it was built and driven over MCP by hand (2026-11-23, see
PROGRESS.md). These pin what would break it silently on someone's Mac: the
launch from files unpacked without execute bits, the manifest the host reads,
a symlink stored as a second copy, and a model file missing from `models/`,
which would turn "downloads nothing" back into a download on the first start.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

from sextant import settings
from sextant.vector_db import embeddings, ocr, onnx_models
from sextant.vector_db.retrieval import RERANK_MODEL

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
        fake.write_text('#!/bin/sh\necho "ran with $*"\necho "models in $SEXTANT_MODEL_DIR"\n')
        (tmp_path / "launch.sh").write_text(standalone.LAUNCH)
        for path in (fake, tmp_path / "launch.sh"):
            path.chmod(0o600)

        result = subprocess.run(["/bin/sh", str(tmp_path / "launch.sh")],
                                capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})

        assert result.returncode == 0, result.stderr
        assert f"-E -s {tmp_path.resolve()}/src/server.py" in result.stdout
        assert fake.stat().st_mode & stat.S_IXUSR
        assert f"models in {tmp_path.resolve()}/models" in result.stdout

    def test_it_names_the_setting_the_program_reads(self):
        assert standalone.MODEL_DIR_ENV == settings.env_name("MODEL_DIR")

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


class TestNothingOfTheBuilderShips:
    """The bundle is a public download; the first build carried the builder's
    home folder in 6 files (uv's install path, script headers)."""

    def test_the_build_settings_lose_the_install_folder(self, tmp_path):
        minor = standalone.PYTHON_MINOR
        source = tmp_path / "home" / "someone" / "uv-python"
        config = source / "lib" / f"python{minor}" / "_sysconfigdata__darwin_darwin.py"
        config.parent.mkdir(parents=True)
        config.write_text(f"build_time_vars = {{'prefix': '{source}', 'LIBDIR': '{source}/lib'}}\n")

        staged = tmp_path / "staged"
        standalone.detach_from_builder(source, staged)

        text = (staged / config.relative_to(source)).read_text()
        assert str(source) not in text
        assert "'prefix': '/install'" in text and "'/install/lib'" in text

    def test_a_trace_is_found_wherever_it_is(self, tmp_path):
        out = tmp_path / "b.zip"
        with zipfile.ZipFile(out, "w") as bundle:
            bundle.writestr("clean.py", "x = 1")
            bundle.writestr("lib/bin/tool", "#!/Users/someone/venv/bin/python")
        assert standalone.traces_of("/Users/someone", out) == ["lib/bin/tool"]


def _apache_libraries(tmp_path: Path) -> Path:
    licence = tmp_path / "lib" / "some_library-1.0.dist-info" / "licenses" / "LICENSE"
    licence.parent.mkdir(parents=True)
    licence.write_text("                Apache License\n          Version 2.0, January 2004\n")
    return tmp_path / "lib"


class TestTheProgramReadsTheShippedCopy:
    def test_a_shipped_model_file_is_used_without_asking_the_hub(self, tmp_path, monkeypatch):
        shipped = tmp_path / "cross-encoder--ms-marco-MiniLM-L6-v2" / "config.json"
        shipped.parent.mkdir()
        shipped.write_text("{}")
        monkeypatch.setenv(settings.env_name("MODEL_DIR"), str(tmp_path))

        def no_hub(*args, **kwargs):
            raise AssertionError("asked the hub for a file the bundle ships")

        monkeypatch.setattr("huggingface_hub.hf_hub_download", no_hub)
        assert onnx_models._fetch("cross-encoder/ms-marco-MiniLM-L6-v2", "config.json") == shipped

    def test_a_file_it_does_not_ship_still_comes_from_the_hub(self, tmp_path, monkeypatch):
        monkeypatch.setenv(settings.env_name("MODEL_DIR"), str(tmp_path))
        asked: list[str] = []

        def hub(repo: str, name: str, **kwargs: object) -> str:
            asked.append(name)
            return str(tmp_path / name)

        monkeypatch.setattr("huggingface_hub.hf_hub_download", hub)
        onnx_models._fetch("someone/other-model", "config.json")
        assert asked == ["config.json"]

    def test_the_shipped_scan_data_comes_before_the_cache(self, tmp_path, monkeypatch):
        (tmp_path / "models" / "tessdata").mkdir(parents=True)
        (tmp_path / "models" / "tessdata" / "eng.traineddata").write_bytes(b"x")
        monkeypatch.setenv(settings.env_name("MODEL_DIR"), str(tmp_path / "models"))
        monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
        monkeypatch.setattr(ocr, "cache_dir", lambda: tmp_path / "empty-cache")
        monkeypatch.setattr(ocr, "_fetch", lambda *a: pytest.fail("downloaded shipped data"))
        assert ocr._resolve(["eng"]).tessdata == str(tmp_path / "models" / "tessdata")


class TestTheModels:
    def test_it_carries_the_two_default_models(self):
        assert onnx_models.EMBEDDER_REPOS[embeddings.LOCAL_MODEL] in standalone.MODELS
        assert onnx_models.RERANKER_REPOS[RERANK_MODEL] in standalone.MODELS
        assert len(standalone.MODELS) == 2

    def test_search_starts_from_the_shipped_copy_alone(self, tmp_path, monkeypatch):
        """Stage `models/` as the build does, then load both search models
        and the English scan data with the hub and the download cut off: a
        file the loaders read and the build left out fails here, not on the
        first start of somebody's install."""
        models = tmp_path / "models"
        standalone.stage_models(models, _apache_libraries(tmp_path), offline=False)

        def no_network(*args, **kwargs):
            raise AssertionError("a search model was asked for outside the shipped copy")

        monkeypatch.setenv(settings.env_name("MODEL_DIR"), str(models))
        monkeypatch.setattr("huggingface_hub.hf_hub_download", no_network)
        monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
        monkeypatch.setattr(ocr, "cache_dir", lambda: tmp_path / "empty-cache")
        monkeypatch.setattr(ocr, "_fetch", no_network)

        embedder = onnx_models.OnnxEmbedder(embeddings.LOCAL_MODEL)
        reranker = onnx_models.OnnxReranker(RERANK_MODEL)
        assert len(embedder.encode_query("who keeps the lighthouse")) == 384
        assert len(reranker.predict([("lighthouse", "The keeper lit the lamp.")])) == 1
        assert ocr._resolve(["eng"]).tessdata == str(models / "tessdata")

        notice = (models / "NOTICE.txt").read_text()
        for repo, (revision, _files) in standalone.MODELS.items():
            assert f"{repo} at revision {revision}" in notice
        assert (models / "LICENSE-Apache-2.0.txt").read_text().lstrip().startswith("Apache")
        embedder_dir = models / "sentence-transformers--all-MiniLM-L6-v2"
        assert not (embedder_dir / "model.safetensors").exists()

    def test_scan_data_that_does_not_match_its_hash_is_refused(self, tmp_path, monkeypatch):
        planted = tmp_path / "planted"
        planted.mkdir()
        (planted / "eng.traineddata").write_bytes(b"not the published file")
        monkeypatch.setenv("TESSDATA_PREFIX", str(planted))
        monkeypatch.setattr(standalone, "MODELS", {})
        with pytest.raises(SystemExit, match="published hash"):
            standalone.stage_models(tmp_path / "models", _apache_libraries(tmp_path), offline=True)

    def test_it_will_not_ship_the_models_without_their_licence(self, tmp_path):
        with pytest.raises(SystemExit, match="Apache"):
            standalone._apache_text(tmp_path)
