"""The two halves of identity that cannot be tested together.

Caddy sets the header; the app reads it. Nothing in the test suite runs both,
and nothing in the test suite can -- the proxy only exists on the box, and a
VM trip costs money. So what is pinned here is the seam: the header names in
`deploy/Caddyfile` are the ones `mcp_server/identity.py` declares, and the
secret that makes one believe the other is wired to both.

The failure this exists for is quiet. Rename `USER_HEADER` in Python and every
Python test still passes; the proxy then forwards a header nobody reads, every
authenticated user falls back to their browser id, and the only symptom is that
uploads land in the wrong namespace. A string compare catches it in the gate
instead of on the box.

The Caddyfile itself was checked with the real thing, which these tests cannot
do: `caddy validate` accepts it with the optional user slots empty, `caddy
adapt` shows both headers as a `set` rather than an append, and a live proxy
with two users rewrote a request that authenticated as `ada` while carrying
`X-Sextant-User: grace` so that the backend saw `ada`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.identity import PROXY_HEADER, PROXY_SECRET, USER_HEADER
from tools import settings

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


@pytest.fixture(scope="module")
def caddyfile() -> str:
    return (DEPLOY / "Caddyfile").read_text()


@pytest.fixture(scope="module")
def env_example() -> str:
    return (DEPLOY / "env.example").read_text()


class TestTheProxySetsWhatTheAppReads:
    def test_the_authenticated_user_is_forwarded_under_the_name_python_expects(
        self, caddyfile
    ):
        assert f"header_up {USER_HEADER} {{http.auth.user.id}}" in caddyfile

    def test_the_proof_header_matches_too(self, caddyfile):
        secret = f"{{${settings.env_name(PROXY_SECRET)}}}"
        assert f"header_up {PROXY_HEADER} {secret}" in caddyfile

    def test_both_headers_are_set_rather_than_added(self, caddyfile):
        # `header_up +Name` appends, which would leave a client-supplied value
        # in place beside ours and let the app read either one.
        for header in (USER_HEADER, PROXY_HEADER):
            assert f"header_up +{header}" not in caddyfile

    def test_the_gate_has_room_for_more_than_one_person(self, caddyfile):
        # Identity is meaningless behind a single shared password: whoever
        # authenticates is always the same name.
        for slot in ("{$BASIC_AUTH_USER_2} {$BASIC_AUTH_HASH_2}",
                     "{$BASIC_AUTH_USER_3} {$BASIC_AUTH_HASH_3}"):
            assert slot in caddyfile


class TestTheBoxIsToldAboutBoth:
    def test_the_secret_is_documented_for_the_operator(self, env_example):
        assert f"{settings.env_name(PROXY_SECRET)}=" in env_example

    def test_the_extra_user_slots_are_documented(self, env_example):
        for name in ("BASIC_AUTH_USER_2=", "BASIC_AUTH_HASH_2=",
                     "BASIC_AUTH_USER_3=", "BASIC_AUTH_HASH_3="):
            assert name in env_example

    def test_no_example_ships_a_filled_in_secret(self, env_example):
        # This file is in a public repo. Every secret in it is empty, and that
        # is a property worth a test rather than a habit.
        for line in env_example.splitlines():
            name, _, value = line.partition("=")
            if name.strip() in {
                settings.env_name(PROXY_SECRET),
                "BASIC_AUTH_HASH",
                "BASIC_AUTH_HASH_2",
                "BASIC_AUTH_HASH_3",
                "GEMINI_API_KEY",
            }:
                assert value.strip() == "", f"{name} has a value in env.example"
