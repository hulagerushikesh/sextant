"""The TypeScript types the browser reads `/health` through.

`frontend/src/lib/types.ts` opens with "Shapes the agent server sends. Mirrors
sextant/mcp_server/main.py + agent.py." Nothing checked that. It drifted: the server
has shipped `budget.durable` since milestone 21 item 15 -- added so that a
figure nobody can date is not mistaken for the day's -- and the type did not
declare it, so no component could read it without the compiler objecting, and
none did. `resets_in_seconds` and `share` had gone the same way.

A field the server sends and the type omits is a field the UI cannot use. This
asks the running endpoint what it sends and the file what it declares, so the
next one fails here instead of being discovered on the box.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sextant.mcp_server import main
from sextant.mcp_server.observability import DailyBudget
from tests.fakes import FakeHost

TYPES = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "types.ts"


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


def declared(interface: str) -> set[str]:
    """Field names of one `export interface` in types.ts.

    Comments are stripped first, and that is not tidiness. Every field in this
    file is documented, the prose names other fields, and a scan that reads the
    doc comment finds `spent_usd` declared because a sentence about `durable`
    mentions it -- which is the failure mode of a scan that does not normalise
    before it matches, caught the hard way in item 24.
    """
    body = re.search(
        rf"^export interface {interface} \{{\n(.*?)^\}}",
        TYPES.read_text(),
        re.DOTALL | re.MULTILINE,
    )
    assert body, f"no `export interface {interface}` in {TYPES}"
    without_comments = re.sub(r"/\*.*?\*/", "", body.group(1), flags=re.DOTALL)
    without_comments = re.sub(r"//[^\n]*", "", without_comments)
    return set(re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??:", without_comments, re.MULTILINE))


class TestTheTypeMirrorsWhatTheServerSends:
    def test_every_health_field_is_declared(self, client):
        sent = set(client.get("/health").json())
        # `timestamp` is the one field no component reads and the type has
        # never carried. Named here rather than silently subtracted, so the
        # exemption is a decision somebody can see and revisit.
        missing = sent - declared("Health") - {"timestamp"}
        assert not missing, f"/health sends {sorted(missing)}; types.ts Health does not declare it"

    def test_every_budget_field_is_declared(self):
        # The endpoint's own budget is disabled under test, so ask the class
        # directly, with a share configured and an owner named: that is the
        # widest payload `status()` can produce.
        budget = DailyBudget(budget_usd=1.0, share=0.5, ledger=Path("/nonexistent/ledger.json"))
        budget.record(0.01, "ada")
        missing = set(budget.status("ada")) - declared("Budget")
        assert not missing, (
            f"budget.status() sends {sorted(missing)}; types.ts Budget does not declare it"
        )

    def test_the_scan_can_fail(self):
        # A scan that cannot come back empty proves nothing about the file it
        # read. These two names are not in the interface and never will be.
        assert not {"nonesuch_field", "another_absence"} & declared("Budget")
        assert "durable" in declared("Budget")
