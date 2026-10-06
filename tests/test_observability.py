"""Request identity, rate limiting and cost accounting."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mcp_server import main
from mcp_server.identity import CLIENT_HEADER, PROXY_HEADER, PROXY_SECRET, USER_HEADER
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
from tools import settings


@pytest.fixture
def host(monkeypatch) -> FakeHost:
    fake = FakeHost()
    monkeypatch.setattr(main, "host", fake)
    return fake


@pytest.fixture
def client(host) -> Iterator[TestClient]:
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


SECRET = "shared-with-caddy"


@pytest.fixture
def gated(monkeypatch):
    """A box with identity wired up, the way the VM has it."""
    monkeypatch.setenv(settings.env_name(PROXY_SECRET), SECRET)
    return lambda name: {USER_HEADER: name, PROXY_HEADER: SECRET}


def quiet_agent(monkeypatch, cost: float = 0.0):
    async def answer(query, host, *_):
        yield {
            "type": "done", "sources": [], "turns": 1, "truncated": False,
            "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": cost},
        }

    monkeypatch.setattr(main, "run_agent", answer)


class TestWhatTheLimiterCounts:
    """Milestone 21 item 2. The name is the thing being limited; the address
    it arrived from is an accident -- but only once something has checked the
    name."""

    def test_two_users_behind_one_address_do_not_throttle_each_other(
        self, client, monkeypatch, gated
    ):
        # The NAT case, and the reason this was wrong: an office is one
        # address, and one person's open tab stopped everybody else's work.
        monkeypatch.setattr(main.limiter, "limit", 1)
        quiet_agent(monkeypatch)
        assert client.post("/query", json={"query": "q"}, headers=gated("ada")).status_code == 200
        assert client.post("/query", json={"query": "q"}, headers=gated("ada")).status_code == 429
        assert client.post("/query", json={"query": "q"}, headers=gated("grace")).status_code == 200

    def test_an_unproven_name_does_not_buy_a_fresh_bucket(self, client, monkeypatch):
        # The whole hazard of keying on a name: without the proxy's proof the
        # caller picks the key, so keying on it would be weaker than the
        # address it replaced. Changing the client header must not reset it.
        monkeypatch.delenv(settings.env_name(PROXY_SECRET), raising=False)
        monkeypatch.setattr(main.limiter, "limit", 1)
        quiet_agent(monkeypatch)
        first = client.post("/query", json={"query": "q"}, headers={CLIENT_HEADER: "b9"})
        second = client.post("/query", json={"query": "q"}, headers={CLIENT_HEADER: "zz"})
        assert first.status_code == 200
        assert second.status_code == 429

    def test_a_name_cannot_collide_with_an_address(self, client, monkeypatch, gated):
        # The keys are prefixed, so a user called after the test client's own
        # address does not inherit its bucket.
        monkeypatch.setattr(main.limiter, "limit", 1)
        quiet_agent(monkeypatch)
        assert client.post("/query", json={"query": "q"}).status_code == 200
        named = client.post("/query", json={"query": "q"}, headers=gated("testclient"))
        assert named.status_code == 200

    def test_the_index_lab_is_limited_like_everything_else(self, client, host, monkeypatch):
        # Building two ANN indexes over every vector is the heaviest thing the
        # box does, and it was the one route with no limit on it at all.
        monkeypatch.setattr(main.limiter, "limit", 1)
        host.results["kb_ann_benchmark"] = {"rows": []}
        assert client.post("/ann/benchmark", json={}).status_code == 200
        assert client.post("/ann/benchmark", json={}).status_code == 429


class TestPerOwnerShare:
    """The cap protects the wallet; the share protects everybody else's
    access to it. Both, in that order -- a share that replaced the cap would
    make the bill scale with the number of users."""

    def test_disabled_by_default(self):
        b = DailyBudget(budget_usd=1.0)
        assert b.share == 1.0 and b.owner_budget == 0.0
        b.record(0.99, "ada")
        assert b.check_owner("ada")[0] is True

    def test_one_owner_cannot_take_more_than_their_share(self):
        b = DailyBudget(budget_usd=1.0, share=0.5)
        b.record(0.4, "ada")
        assert b.check_owner("ada")[0] is True
        b.record(0.2, "ada")
        assert b.check_owner("ada")[0] is False

    def test_exhausting_a_share_leaves_the_other_owner_able_to_ask(self):
        # Clause 1 of the pre-registered rule, and the entire point.
        b = DailyBudget(budget_usd=1.0, share=0.5)
        b.record(0.9, "ada")
        assert b.check_owner("ada")[0] is False
        assert b.check_owner("grace")[0] is True

    def test_the_global_ceiling_still_holds(self):
        # Clause 2: the wallet guarantee is not traded away for fairness.
        # Three owners, each inside their own third, together over the cap.
        b = DailyBudget(budget_usd=1.0, share=0.4)
        for name in ("ada", "grace", "alan"):
            b.record(0.35, name)
            assert b.check_owner(name)[0] is True
        # 1.05 between them. Each is inside their share and the box is shut.
        assert b.check()[0] is False

    def test_an_untrusted_caller_is_held_by_the_cap_alone(self):
        # None means nothing vouched for the name. Attributing spend to it
        # would promise a limit that is reset by typing a different header.
        b = DailyBudget(budget_usd=1.0, share=0.5)
        b.record(0.9)
        assert b.check_owner(None)[0] is True
        assert b.check()[0] is True
        b.record(0.2)
        assert b.check()[0] is False

    def test_unattributed_spend_still_counts_against_the_day(self):
        b = DailyBudget(budget_usd=1.0, share=0.5)
        b.record(1.0)
        assert b.check()[0] is False

    def test_a_new_day_clears_every_owners_tally(self):
        import datetime as _dt

        b = DailyBudget(budget_usd=1.0, share=0.5)
        b.record(0.9, "ada")
        b._day = _dt.date(2000, 1, 1)
        assert b.check_owner("ada")[0] is True

    def test_a_share_outside_the_range_is_ignored_rather_than_obeyed(self):
        # A share of 0 would refuse everybody, which is not what anybody meant
        # by setting it. Off is the safe reading of a nonsense value.
        for bad in (0.0, -1.0, 1.5):
            assert DailyBudget(budget_usd=1.0, share=bad).share == 1.0

    def test_status_tells_the_asker_about_their_own_share(self):
        # Being refused at 20% of a cap you can see is unspent, with no way to
        # tell why, gets reported as the box being broken.
        b = DailyBudget(budget_usd=1.0, share=0.5)
        b.record(0.3, "ada")
        mine = b.status("ada")
        assert mine["owner_budget_usd"] == pytest.approx(0.5)
        assert mine["owner_remaining_usd"] == pytest.approx(0.2)
        assert "owner_spent_usd" not in b.status()


class TestTheSharedGate:
    """The three pre-registered clauses, at the HTTP edge this time."""

    def test_one_user_spending_their_share_does_not_silence_another(
        self, client, monkeypatch, gated
    ):
        monkeypatch.setattr(main, "budget", DailyBudget(budget_usd=1.0, share=0.5))
        main.budget.record(0.6, "ada")
        quiet_agent(monkeypatch)
        refused = client.post("/query", json={"query": "q"}, headers=gated("ada"))
        assert refused.status_code == 429
        assert "other users are unaffected" in refused.json()["detail"]
        assert client.post("/query", json={"query": "q"}, headers=gated("grace")).status_code == 200

    def test_the_two_refusals_do_not_read_the_same(self, client, monkeypatch, gated):
        # One says the box is done for the day; the other says you are and
        # somebody else is not. Same status code, different thing to do.
        monkeypatch.setattr(main, "budget", DailyBudget(budget_usd=1.0, share=0.5))
        main.budget.record(1.0, "ada")
        quiet_agent(monkeypatch)
        detail = client.post("/query", json={"query": "q"}, headers=gated("grace")).json()["detail"]
        assert "Daily spend cap" in detail

    def test_a_box_with_no_identity_behaves_exactly_as_before(self, client, monkeypatch):
        # Clause 3: a single-user deployment must not acquire a second kind of
        # limit it never asked for.
        monkeypatch.delenv(settings.env_name(PROXY_SECRET), raising=False)
        monkeypatch.setattr(main, "budget", DailyBudget(budget_usd=1.0, share=0.5))
        quiet_agent(monkeypatch, cost=0.9)
        assert client.post("/query", json={"query": "q"}).status_code == 200
        # 0.9 spent, over any share of 0.5, and still served: the share was
        # never applied, because nothing vouched for a name to apply it to.
        assert client.post("/query", json={"query": "q"}).status_code == 200

    def test_spend_is_attributed_to_the_authenticated_name(
        self, client, monkeypatch, gated
    ):
        monkeypatch.setattr(main, "budget", DailyBudget(budget_usd=1.0, share=0.5))
        quiet_agent(monkeypatch, cost=0.6)
        client.post("/query", json={"query": "q"}, headers=gated("ada"))
        assert main.budget.check_owner("ada")[0] is False
        assert main.budget.check_owner("grace")[0] is True

    def test_a_streamed_query_counts_against_the_same_share(
        self, client, monkeypatch, gated
    ):
        # The stream charges the cap from inside a generator that outlives the
        # request object, so the owner has to be captured before it runs.
        monkeypatch.setattr(main, "budget", DailyBudget(budget_usd=1.0, share=0.5))
        quiet_agent(monkeypatch, cost=0.6)
        client.post("/query/stream", json={"query": "q"}, headers=gated("ada"))
        assert main.budget.check_owner("ada")[0] is False

    def test_health_shows_the_asker_their_own_remaining_share(
        self, client, monkeypatch, gated
    ):
        monkeypatch.setattr(main, "budget", DailyBudget(budget_usd=1.0, share=0.5))
        main.budget.record(0.1, "ada")
        got = client.get("/health", headers=gated("ada")).json()["budget"]
        assert got["owner_remaining_usd"] == pytest.approx(0.4)
        assert client.get("/health").json()["budget"].get("owner_remaining_usd") is None


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
