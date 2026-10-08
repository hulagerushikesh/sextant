"""The daily cap is a promise about a day, so it has to survive a restart.

`DailyBudget` kept the day's tally in memory only. Every `docker compose up -d
--build` -- so every deploy -- and every `restart: unless-stopped` bounce began
the day again at zero while Google's meter kept counting, which makes the cap a
speed bump per process lifetime rather than a cap on a day.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from mcp_server import observability
from mcp_server.observability import DailyBudget, spend_ledger_path


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


class TestTheDayTallySurvivesARestart:
    def test_a_fresh_budget_resumes_todays_spend(self, tmp_path):
        ledger = tmp_path / "spend.json"
        first = DailyBudget(budget_usd=1.0, ledger=ledger)
        first.record(0.40)
        first.record(0.30)

        restarted = DailyBudget(budget_usd=1.0, ledger=ledger)
        allowed, spent, _ = restarted.check()
        assert spent == 0.70, "the restart began the day again at zero"
        assert allowed is True

    def test_a_restart_cannot_spend_the_cap_twice(self, tmp_path):
        ledger = tmp_path / "spend.json"
        spender = DailyBudget(budget_usd=1.0, ledger=ledger)
        spender.record(1.0)
        assert spender.check()[0] is False

        restarted = DailyBudget(budget_usd=1.0, ledger=ledger)
        assert restarted.check()[0] is False, "a bounce handed out the cap again"

    def test_per_owner_shares_survive_too(self, tmp_path):
        ledger = tmp_path / "spend.json"
        first = DailyBudget(budget_usd=1.0, share=0.5, ledger=ledger)
        first.record(0.50, owner="ana")
        assert first.check_owner("ana")[0] is False

        restarted = DailyBudget(budget_usd=1.0, share=0.5, ledger=ledger)
        assert restarted.check_owner("ana")[0] is False
        assert restarted.check_owner("bo")[0] is True, "bo never spent anything"

    def test_a_previous_days_ledger_is_not_resumed(self, tmp_path):
        ledger = tmp_path / "spend.json"
        yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
        ledger.write_text(
            json.dumps({"day": yesterday, "spent_usd": 0.99, "by_owner": {"ana": 0.99}})
        )
        budget = DailyBudget(budget_usd=1.0, share=0.5, ledger=ledger)
        assert budget.check()[1] == 0.0
        assert budget.check_owner("ana")[0] is True

    def test_the_tally_is_written_where_it_can_be_read_back(self, tmp_path):
        ledger = tmp_path / "nested" / "spend.json"
        DailyBudget(budget_usd=1.0, ledger=ledger).record(0.25, owner="ana")
        written = json.loads(ledger.read_text())
        assert written == {
            "day": _today(),
            "spent_usd": 0.25,
            "by_owner": {"ana": 0.25},
        }


class TestTheLedgerNeverBreaksAQuery:
    def test_an_unreadable_ledger_starts_at_zero_and_says_so(self, tmp_path):
        ledger = tmp_path / "spend.json"
        ledger.write_text("{not json")
        budget = DailyBudget(budget_usd=1.0, ledger=ledger)
        assert budget.check()[1] == 0.0
        assert budget.status()["durable"] is False

    def test_a_ledger_missing_its_fields_starts_at_zero_and_says_so(self, tmp_path):
        ledger = tmp_path / "spend.json"
        ledger.write_text(json.dumps({"day": _today()}))
        budget = DailyBudget(budget_usd=1.0, ledger=ledger)
        assert budget.check()[1] == 0.0
        assert budget.status()["durable"] is False

    def test_an_unwritable_ledger_still_caps_in_memory(self, tmp_path):
        # The directory is taken by a file, so mkdir and write both fail.
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory")
        budget = DailyBudget(budget_usd=1.0, ledger=blocker / "spend.json")
        budget.record(1.0)
        assert budget.check()[0] is False, "the cap must hold even with no disk"
        assert budget.status()["durable"] is False

    def test_a_working_ledger_reports_durable(self, tmp_path):
        ledger = tmp_path / "spend.json"
        budget = DailyBudget(budget_usd=1.0, ledger=ledger)
        budget.record(0.1)
        # Both halves, or the flag passes on a budget that never wrote anything.
        assert ledger.exists()
        assert budget.status()["durable"] is True

    def test_nothing_is_written_when_the_cap_is_off(self, tmp_path):
        ledger = tmp_path / "spend.json"
        budget = DailyBudget(budget_usd=0.0, ledger=ledger)
        budget.record(5.0)
        assert not ledger.exists()
        assert budget.status() == {"enabled": False}


class TestTheLedgerLivesWhereTheCorpusDoes:
    """One location, resolved twice, is the drift this repository keeps paying for."""

    def test_it_defaults_beside_the_collection_directory(self, monkeypatch):
        from tools.vector_db.vector_search import persist_dir

        monkeypatch.delenv("SEXTANT_SPEND_LEDGER", raising=False)
        monkeypatch.delenv("SEXTANT_CHROMA_DIR", raising=False)
        assert spend_ledger_path() == persist_dir() / observability.SPEND_LEDGER_NAME

    def test_it_follows_the_collection_override(self, monkeypatch, tmp_path):
        from tools.vector_db.vector_search import persist_dir

        monkeypatch.delenv("SEXTANT_SPEND_LEDGER", raising=False)
        monkeypatch.setenv("SEXTANT_CHROMA_DIR", str(tmp_path / "elsewhere"))
        assert spend_ledger_path() == persist_dir() / observability.SPEND_LEDGER_NAME

    def test_an_explicit_path_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SEXTANT_SPEND_LEDGER", str(tmp_path / "mine.json"))
        monkeypatch.setenv("SEXTANT_CHROMA_DIR", str(tmp_path / "elsewhere"))
        assert spend_ledger_path() == tmp_path / "mine.json"

    def test_it_is_hidden_so_it_cannot_be_mistaken_for_a_document(self):
        assert observability.SPEND_LEDGER_NAME.startswith(".")
