"""Request identity, rate limiting and cost accounting."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mcp_server import main
from mcp_server.observability import (
    REQUEST_ID_HEADER,
    DailyBudget,
    JsonFormatter,
    RateLimiter,
    RequestIdFilter,
    request_id,
)
from mcp_server.pricing import estimate_cost
from tests.fakes import FakeHost


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main, "host", FakeHost())
    main.limiter.reset()
    with TestClient(main.app) as test_client:
        yield test_client
    main.limiter.reset()


class TestRequestId:
    def test_every_response_carries_one(self, client):
        assert client.get("/health").headers[REQUEST_ID_HEADER]

    def test_ids_differ_between_requests(self, client):
        first = client.get("/health").headers[REQUEST_ID_HEADER]
        second = client.get("/health").headers[REQUEST_ID_HEADER]
        assert first != second

    def test_a_caller_supplied_id_is_honoured(self, client):
        # So a trace can span the browser, a proxy and this server.
        headers = {REQUEST_ID_HEADER: "trace-from-upstream"}
        response = client.get("/health", headers=headers)
        assert response.headers[REQUEST_ID_HEADER] == "trace-from-upstream"

    def test_the_id_reaches_the_query_response_body(self, client, monkeypatch):
        async def answer(query, host, *_):
            yield {"type": "done", "sources": [], "turns": 1, "truncated": False,
                   "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}}

        monkeypatch.setattr(main, "run_agent", answer)
        headers = {REQUEST_ID_HEADER: "abc123"}
        assert client.post("/query", json={"query": "q"}, headers=headers).json()[
            "request_id"
        ] == "abc123"

    def test_the_stream_reports_it_in_a_header(self, client, monkeypatch):
        async def answer(query, host, *_):
            yield {"type": "done", "sources": [], "turns": 1, "truncated": False,
                   "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}}

        monkeypatch.setattr(main, "run_agent", answer)
        response = client.post("/query/stream", json={"query": "q"})
        assert response.headers[REQUEST_ID_HEADER]

    def test_it_resets_so_it_cannot_leak_between_requests(self, client):
        client.get("/health")
        assert request_id.get() == "-"


class TestRateLimit:
    def test_requests_over_the_limit_are_refused(self, client, monkeypatch):
        monkeypatch.setattr(main.limiter, "limit", 3)

        async def answer(query, host, *_):
            yield {"type": "done", "sources": [], "turns": 1, "truncated": False,
                   "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}}

        monkeypatch.setattr(main, "run_agent", answer)
        codes = [
            client.post("/query", json={"query": "q"}).status_code for _ in range(5)
        ]
        assert codes[:3] == [200, 200, 200]
        assert codes[3:] == [429, 429]

    def test_a_refusal_says_when_to_come_back(self, client, monkeypatch):
        monkeypatch.setattr(main.limiter, "limit", 1)
        client.post("/ingest", json={"documents": [{"content": "x"}]})
        response = client.post("/ingest", json={"documents": [{"content": "x"}]})
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0

    def test_reads_are_not_limited(self, client, monkeypatch):
        # /health is how something else finds out this server is up; rate
        # limiting it would turn a busy minute into a false outage.
        monkeypatch.setattr(main.limiter, "limit", 1)
        assert all(client.get("/health").status_code == 200 for _ in range(5))

    def test_clients_are_counted_separately(self):
        limiter = RateLimiter(limit=1, window=60)
        assert limiter.check("a")[0] is True
        assert limiter.check("a")[0] is False
        assert limiter.check("b")[0] is True

    def test_the_window_expires(self):
        limiter = RateLimiter(limit=1, window=10)
        assert limiter.check("a", now=0.0)[0] is True
        assert limiter.check("a", now=5.0)[0] is False
        assert limiter.check("a", now=11.0)[0] is True

    def test_a_limit_of_zero_disables_it(self):
        limiter = RateLimiter(limit=0, window=60)
        assert all(limiter.check("a")[0] for _ in range(100))


class TestLogging:
    def test_json_records_carry_the_request_id(self):
        record = logging.LogRecord("t", logging.INFO, "f", 1, "hello", None, None)
        RequestIdFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
        assert payload["message"] == "hello"
        assert payload["request_id"] == "-"
        assert payload["level"] == "INFO"

    def test_agent_extras_are_promoted_to_top_level_fields(self):
        record = logging.LogRecord("t", logging.INFO, "f", 1, "done", None, None)
        record.agent_turns = 3
        record.agent_cost_usd = 0.012
        RequestIdFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
        assert payload["turns"] == 3
        assert payload["cost_usd"] == 0.012

    def test_an_exception_is_included(self):
        try:
            raise ValueError("bang")
        except ValueError:
            import sys

            record = logging.LogRecord(
                "t", logging.ERROR, "f", 1, "failed", None, sys.exc_info()
            )
        RequestIdFilter().filter(record)
        assert "bang" in json.loads(JsonFormatter().format(record))["exception"]


class TestCost:
    def test_a_typical_query(self):
        # 10k in, 1k out at $0.25/$1.50 per Mtok (gemini-3.1-flash-lite)
        assert estimate_cost(10_000, 1_000) == pytest.approx(0.004)

    def test_a_grounded_request_costs_more_than_its_tokens(self):
        # Google bills search per request, outside the token budget, which the
        # Anthropic tier this replaces did not do.
        assert estimate_cost(10_000, 1_000, grounded_requests=1) == pytest.approx(0.018)

    def test_zero_usage_is_free(self):
        assert estimate_cost(0, 0) == 0.0

    def test_cached_prompt_tokens_bill_at_a_tenth_and_never_exceed_the_input(self):
        # 10,000 in of which 8,000 cached: 2,000 at $0.25/M + 8,000 at $0.025/M.
        assert estimate_cost(10_000, 0, cached_tokens=8_000) == pytest.approx(0.0007)
        capped = estimate_cost(1_000, 0, cached_tokens=5_000)
        assert capped == estimate_cost(1_000, 0, cached_tokens=1_000)

    def test_output_is_the_expensive_half(self):
        assert estimate_cost(0, 1000) > estimate_cost(1000, 0)


class TestDailyBudget:
    def test_disabled_by_default_never_blocks(self):
        b = DailyBudget(budget_usd=0)
        allowed, spent, _ = b.check()
        assert allowed is True and spent == 0.0
        b.record(999.0)          # no-op while disabled
        assert b.check()[0] is True
        assert b.status() == {"enabled": False}

    def test_spend_accumulates_until_the_cap(self):
        b = DailyBudget(budget_usd=0.10)
        assert b.check()[0] is True
        b.record(0.04)
        b.record(0.05)
        assert b.check()[0] is True          # 0.09 < 0.10
        b.record(0.02)
        assert b.check()[0] is False         # 0.11 >= 0.10, refused

    def test_status_reports_spent_and_remaining(self):
        b = DailyBudget(budget_usd=1.0)
        b.record(0.25)
        s = b.status()
        assert s["enabled"] is True
        assert s["spent_usd"] == pytest.approx(0.25)
        assert s["remaining_usd"] == pytest.approx(0.75)
        resets = s["resets_in_seconds"]
        assert isinstance(resets, int) and resets > 0

    def test_a_new_utc_day_zeroes_the_tally(self):
        import datetime as _dt

        b = DailyBudget(budget_usd=0.10)
        b.record(0.10)
        assert b.check()[0] is False
        b._day = _dt.date(2000, 1, 1)        # pretend the day rolled over
        assert b.check()[0] is True          # fresh day, spend reset
        assert b.status()["spent_usd"] == pytest.approx(0.0)

    def test_reset_clears_spend(self):
        b = DailyBudget(budget_usd=0.10)
        b.record(0.10)
        b.reset()
        assert b.check()[0] is True


class TestBudgetGate:
    def test_a_query_over_the_cap_is_refused(self, client, monkeypatch):
        b = DailyBudget(budget_usd=0.01)
        b.record(0.01)                        # at the cap
        monkeypatch.setattr(main, "budget", b)
        r = client.post("/query", json={"query": "what is a kalman filter"})
        assert r.status_code == 429
        assert "cap" in r.json()["detail"].lower()

    def test_health_reports_the_days_spend(self, client, monkeypatch):
        b = DailyBudget(budget_usd=1.0)
        b.record(0.25)
        monkeypatch.setattr(main, "budget", b)
        got = client.get("/health").json()["budget"]
        assert got["enabled"] is True
        assert got["remaining_usd"] == pytest.approx(0.75)

    def test_disabled_budget_reports_and_does_not_gate(self, client, monkeypatch):
        monkeypatch.setattr(main, "budget", DailyBudget(budget_usd=0))
        assert client.get("/health").json()["budget"] == {"enabled": False}
