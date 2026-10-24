"""`sextant-judge`: the generation harness, and the `.env` it could not read.

Four claims, in the order they were found.

1. A setting read at import time must see `.env`. `mcp_server/main.py` loaded
   the file twenty lines below the imports that read it, so every module-level
   constant in the application resolved against an environment the file had
   not reached. The load lives in `tools.settings` now, which is the one
   module an environment read cannot avoid importing.

2. `sextant-judge` had never been able to start from a checkout. It is the
   only measurement of faithfulness this project has, and it exited
   `GEMINI_API_KEY is not set` against a key sitting in the file every other
   entry point reads it from.

3. The judge must not let the model search the web. Claim 1 is what made that
   urgent: with `.env` finally reaching the process, `SEXTANT_WEB_SEARCH`
   became a setting that could silently redefine what the unanswerable split
   measures.

4. A truncated answer and a finished one must not reach the grader as the
   same thing.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from eval import judge

ROOT = Path(__file__).resolve().parents[1]


class TestASettingReadAtImportTimeSeesTheFile:
    """The ordering, proved on a copy of the real `settings.py`.

    A copy rather than the repository itself because `.env` is gitignored:
    the machine that most needs this test to run is CI, which has no `.env`
    at all, and a test that skips there is the shape this item exists to
    delete. `settings.py` is stdlib plus `python-dotenv`, so the copy is two
    files and runs anywhere.
    """

    @staticmethod
    def _tree(tmp_path: Path, body: str) -> Path:
        package = tmp_path / "tools"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "settings.py").write_text((ROOT / "tools" / "settings.py").read_text())
        # A module shaped exactly like `observability` and `agent`: a constant
        # evaluated once, at import, from a setting.
        (package / "knob.py").write_text(body)
        (tmp_path / ".env").write_text("SEXTANT_DAILY_BUDGET_USD=0.60\n")
        return tmp_path

    @staticmethod
    def _read(tmp_path: Path, expression: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", f"from tools import knob; print({expression})"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            # The name must be absent from the environment, or `load_dotenv`
            # (which never overrides) would not be the thing under test.
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_a_module_level_constant_resolves_against_the_env_file(self, tmp_path):
        tree = self._tree(
            tmp_path,
            textwrap.dedent(
                """
                from tools import settings

                CAP = float(settings.getenv("DAILY_BUDGET_USD", "0") or "0")
                """
            ),
        )
        # 0.0 is the defect: the environment held 0.60 and the constant held
        # the default, which `DailyBudget` reads as no cap at all.
        assert self._read(tree, "knob.CAP") == "0.6"

    def test_the_file_does_not_override_a_name_already_in_the_environment(self, tmp_path):
        tree = self._tree(
            tmp_path,
            textwrap.dedent(
                """
                from tools import settings

                CAP = float(settings.getenv("DAILY_BUDGET_USD", "0") or "0")
                """
            ),
        )
        result = subprocess.run(
            [sys.executable, "-c", "from tools import knob; print(knob.CAP)"],
            cwd=tree,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": str(tree),
                "SEXTANT_DAILY_BUDGET_USD": "0.10",
            },
        )
        assert result.returncode == 0, result.stderr
        # compose's `env_file`, CI and a shell export all outrank the file.
        assert result.stdout.strip() == "0.1"


class TestTheEnvFileIsLoadedInOnePlace:
    """A second copy is how the ordering came apart in the first place.

    `main.py`, `ingest_cli.py` and `agent_harness.py` each loaded it, and the
    one that mattered loaded it too late. One call, in the module every
    setting is read through, is not a tidier version of three -- it is the
    only arrangement in which there is no order to get wrong.
    """

    def test_only_settings_calls_load_dotenv(self):
        callers = sorted(
            path.relative_to(ROOT).as_posix()
            for tree in ("mcp_server", "tools", "eval")
            for path in (ROOT / tree).rglob("*.py")
            if "load_dotenv(" in path.read_text()
        )
        assert callers == ["tools/settings.py"], callers

    def test_no_module_level_environment_read_bypasses_settings(self):
        """Everything resolved at import goes through `settings.getenv`.

        A bare `os.environ[...]` at module level would be read before
        `tools.settings` had necessarily been imported, which is the defect
        with the fix routed around.

        Reads only. `faiss_ref.py` *writes* `KMP_DUPLICATE_LIB_OK` at module
        level and has to: it must beat `import faiss`, and a flag this
        process sets for a library it is about to load is not a setting the
        operator configures. A scan that cannot tell a read from a write
        would have to exempt that file by name, and an exemption by name is
        a hole shaped like whatever is behind it.
        """
        reads = ("os.getenv(", "os.environ.get(", "os.environ[")
        offenders: list[str] = []
        for tree in ("mcp_server", "tools", "eval"):
            for path in (ROOT / tree).rglob("*.py"):
                if path == ROOT / "tools" / "settings.py":
                    continue
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    if line[:1].isspace() or line.lstrip().startswith("#"):
                        continue
                    if not any(token in line for token in reads):
                        continue
                    if "os.environ[" in line and "=" in line.split("]", 1)[-1]:
                        continue  # a subscript assignment is a write
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        assert not offenders, offenders


class TestTheJudgeDoesNotSearchTheWeb:
    async def test_the_agent_loop_is_called_with_web_search_off(self, monkeypatch):
        """Explicitly off, not merely off by default.

        `web_search_default()` reads `SEXTANT_WEB_SEARCH`, so leaving the
        argument out makes the meaning of `correct_abstention` a property of
        whoever's shell the harness was run from.
        """
        seen: dict[str, object] = {}

        async def fake_run(question, host, **kwargs):
            seen.update(kwargs)
            yield {"type": "done", "sources": [], "turns": 1, "truncated": False, "usage": {}}

        import mcp_server.agent as agent_module

        monkeypatch.setattr(agent_module, "run", fake_run)
        await judge.answer_one(object(), "anything")
        assert seen.get("web_search") is False, seen


class TestWhatTheLoopReportedReachesTheRecord:
    @staticmethod
    def _events(truncated: bool, cost: float):
        async def fake_run(question, host, **kwargs):
            yield {"type": "token", "text": "a partial answ"}
            yield {
                "type": "done",
                "sources": [{"n": 1, "title": "t", "text": "x"}],
                "turns": 4,
                "truncated": truncated,
                "usage": {"cost_usd": cost},
            }

        return fake_run

    async def test_a_cut_off_answer_is_marked_as_one(self, monkeypatch):
        import mcp_server.agent as agent_module

        monkeypatch.setattr(agent_module, "run", self._events(True, 0.0031))
        produced = await judge.answer_one(object(), "q")
        assert produced["truncated"] is True
        assert produced["turns"] == 4
        assert produced["usage"]["cost_usd"] == 0.0031

    async def test_a_finished_answer_is_not(self, monkeypatch):
        import mcp_server.agent as agent_module

        monkeypatch.setattr(agent_module, "run", self._events(False, 0.0012))
        produced = await judge.answer_one(object(), "q")
        assert produced["truncated"] is False

    def test_the_summary_counts_truncation_and_the_run_s_cost(self):
        records = [
            {
                "answerable": True,
                "truncated": True,
                "usage": {"cost_usd": 0.0031},
                "grade": {"faithfulness": 0.5, "relevance": 0.5, "declined": False},
                "citations": {"valid": True, "dangling": []},
            },
            {
                "answerable": False,
                "truncated": False,
                "usage": {"cost_usd": 0.0012},
                "grade": {"faithfulness": 1.0, "relevance": 1.0, "declined": True},
                "citations": {"valid": True, "dangling": []},
            },
        ]
        summary = judge.summarise(records)
        assert summary["truncated"] == 1
        assert summary["cost_usd"] == 0.0043

    def test_a_record_without_usage_does_not_crash_the_summary(self):
        """`done` carries `usage`, but an aborted turn may not have reached it."""
        summary = judge.summarise(
            [
                {
                    "answerable": True,
                    "grade": {"faithfulness": 1.0, "relevance": 1.0, "declined": False},
                    "citations": {"valid": True, "dangling": []},
                }
            ]
        )
        assert summary["truncated"] == 0
        assert summary["cost_usd"] == 0.0


class TestTheEntryPointStartsFromACheckout:
    def test_the_key_check_does_not_fire_when_the_env_file_has_one(self):
        """The symptom, stated as the thing a person would type.

        Skipped where there is no `.env` with a key in it -- on CI there is
        neither, and the claim has no meaning there. The ordering itself is
        covered without a skip by the copied-tree tests above.
        """
        from tools.settings import DOTENV_PATH

        if not DOTENV_PATH.exists() or "GEMINI_API_KEY=" not in DOTENV_PATH.read_text():
            pytest.skip("no .env with a key; the claim is about a developer's checkout")
        # Importing is enough: the key check in `main()` reads `os.getenv`, and
        # what used to be missing is the file reaching the environment at all.
        import os

        assert os.getenv("GEMINI_API_KEY"), (
            f"{DOTENV_PATH} sets GEMINI_API_KEY and it did not reach the process"
        )
