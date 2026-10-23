"""The tenancy harness: its verdict, its name, and its docstring.

`eval/tenancy.py` decided milestone 20 item 2 -- one filtered collection or
one per owner -- and it is the harness you re-run when the store changes and
the answer might flip. Nothing had ever executed it. Three claims it makes
are checked here, each of which was false when this file was written:

  the verdict    it prints "A is REJECTED" and returns, so the shell sees
                 exit 0. That is milestone 21 item 14 ("the gate on retrieval
                 quality could not fail") in the one eval harness item 14 did
                 not reach.
  the name       `--help` and every argparse error say `sextant-eval-tenancy`,
                 which is not in `[project.scripts]` and does not exist.
  the docstring  it says the subset collection is "written to a temporary
                 directory", so a reader does not copy their store first. It
                 is written *into* their store: `subset()` builds a
                 `KnowledgeBase` with a collection name and no directory, and
                 that class takes its path from CHROMA_DIR, which `main()` has
                 just pointed at `--store`.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from eval import tenancy
from eval.harness import K_PRIMARY

ROOT = Path(__file__).resolve().parents[1]
_METRIC = f"recall@{K_PRIMARY}"


def _payload(candidate: float, ceiling: float = 0.9) -> dict[str, Any]:
    """A result whose only interesting number is arm A's recall at the rule's budget."""
    return {
        "mode": "rerank",
        "k": K_PRIMARY,
        "per_document_cap": 2,
        "store_chunks": 1660,
        "tenant_documents": 21,
        "tenant_chunks": 52,
        "tenant_share": 0.031,
        "questions": 20,
        "results_returned": [5, 5],
        "first_relevant_rank": {"median": 1, "p90": 4, "max": 9, "never_found": 0},
        "over_fetch": list(tenancy.OVER_FETCH),
        "b": {_METRIC: ceiling, "hit@1": 0.8},
        "a": {str(f): {_METRIC: candidate, "hit@1": 0.1} for f in tenancy.OVER_FETCH},
    }


def _run_main(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], *argv: str) -> int:
    """Run `main()` over a fixed result and return the code the shell would see."""

    async def fake_run(store: Path, mode: str, golden_path: Path) -> dict[str, Any]:
        return payload

    monkeypatch.setattr(tenancy, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["prog", "--store", "/nonexistent", *argv])
    try:
        tenancy.main()
    except SystemExit as e:
        return 0 if e.code is None else int(e.code)
    return 0


class TestAVerdictWithNoConsequence:
    """A command that decides REJECTED must not report success."""

    def test_rejected_is_a_failing_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _run_main(monkeypatch, _payload(candidate=0.1)) != 0

    def test_accepted_is_a_passing_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _run_main(monkeypatch, _payload(candidate=0.9)) == 0

    def test_the_rule_is_within_the_tolerance_not_under_it(self) -> None:
        # "within 0.02" includes 0.02. A gap of exactly the tolerance is the
        # one case where off-by-one in the comparison flips the decision.
        at = 0.9 - tenancy.RULE_TOLERANCE
        accepted, _ = tenancy.rule_verdict(_payload(candidate=at))
        assert accepted is True

    def test_a_hair_past_the_tolerance_is_rejected(self) -> None:
        past = 0.9 - tenancy.RULE_TOLERANCE - 0.0001
        accepted, _ = tenancy.rule_verdict(_payload(candidate=past))
        assert accepted is False

    def test_the_exit_code_agrees_with_the_printed_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The two must never disagree: a sentence saying ACCEPTED over an exit
        # 1, or REJECTED over an exit 0, is worse than either alone.
        for candidate, word in ((0.1, "REJECTED"), (0.9, "ACCEPTED")):
            code = _run_main(monkeypatch, _payload(candidate=candidate))
            printed = capsys.readouterr().out
            assert word in printed
            assert (code == 0) is (word == "ACCEPTED")

    def test_the_decision_is_made_once(self) -> None:
        # The caller that needs the decision must not recover it by matching
        # on the prose -- that is deciding twice, and the second decision is a
        # string match on a sentence this file is free to reword. Same lesson
        # as `billing_line` in deploy.sh: one definition, every caller asks it.
        body = (ROOT / "eval" / "tenancy.py").read_text()
        assert body.count("def rule_verdict(") == 1
        assert body.count('"ACCEPTED"') == 1
        assert "ACCEPTED" not in body.split("def rule_verdict(")[0]


class TestTheNameItTellsYouToType:
    """`prog=` is what every usage line and every argparse error tells you to run."""

    @staticmethod
    def _declared_progs() -> dict[str, str]:
        """Every `prog="..."` in the tree, mapped to the file that declares it."""
        found: dict[str, str] = {}
        for path in sorted(ROOT.glob("*/**/*.py")):
            if ".venv" in path.parts or "node_modules" in path.parts:
                continue
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("prog=") and '"' in stripped:
                    found[stripped.split('"')[1]] = str(path.relative_to(ROOT))
        return found

    def test_there_are_progs_to_check(self) -> None:
        assert len(self._declared_progs()) >= 5

    def test_every_prog_is_a_command_that_exists(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as fh:
            registered = set(tomllib.load(fh)["project"]["scripts"])
        for prog, where in self._declared_progs().items():
            if prog.startswith("python -m "):
                module = prog.removeprefix("python -m ")
                assert (ROOT / Path(module.replace(".", "/") + ".py")).exists(), (
                    f"{where} says `{prog}`, and {module} is not a module"
                )
            else:
                assert prog in registered, (
                    f"{where} tells you to run `{prog}`, which is not in "
                    f"[project.scripts]: {sorted(registered)}"
                )


class TestTheDocstringDescribesThisCode:
    """The subset is written into the caller's store, so the docs must say so."""

    def test_the_subset_inherits_the_callers_store(self) -> None:
        # `subset()` passes a collection name and no directory, so the class
        # resolves the path itself -- from CHROMA_DIR, which main() has just
        # pointed at --store. This is the mechanism; the docstring claim below
        # is the thing it contradicts.
        seen: dict[str, Any] = {}

        class FakeKB:
            def __init__(self, **kwargs: Any) -> None:
                seen.update(kwargs)
                self.collection = self
                self.embedder = type("E", (), {"name": "fake"})()

            def get(self, **_: Any) -> dict[str, Any]:
                raise AssertionError("not reached")

        source = type(
            "Source",
            (),
            {
                "collection": type(
                    "C",
                    (),
                    {
                        "get": staticmethod(
                            lambda **_: {
                                "ids": ["a"],
                                "embeddings": [[0.0]],
                                "documents": ["d"],
                                "metadatas": [{"document_id": "keep"}],
                            }
                        )
                    },
                )()
            },
        )()

        class Recording(FakeKB):
            def add(self, **_: Any) -> None:
                pass

            def _stamp_embedding_model(self, _: str) -> None:
                pass

        tenancy.subset(source, {"keep"}, Recording)
        assert set(seen) == {"collection_name"}, (
            f"subset() passed {sorted(seen)}; anything naming a directory would "
            "mean the subset does NOT land in the caller's store"
        )

    def test_the_docstring_does_not_promise_a_temporary_directory(self) -> None:
        # Normalised first: the claim was wrapped as "temporary\ndirectory",
        # and a scan of the raw text matched nothing and passed on the very
        # docstring it was written to catch.
        doc = re.sub(r"\s+", " ", tenancy.__doc__ or "")
        assert "temporary directory" not in doc, (
            "the subset collection is written into --store, not a temp dir"
        )

    def test_main_creates_no_directory_it_never_uses(self) -> None:
        body = (ROOT / "eval" / "tenancy.py").read_text()
        assert "mkdtemp" not in body, (
            "the scratch tmpdir was never passed to run(); it was the vestige "
            "that made the docstring's claim look true"
        )
