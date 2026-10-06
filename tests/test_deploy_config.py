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

import os
import stat
import subprocess
import sys
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


# --------------------------------------------------------------------------
# The trip script itself.
#
# `deploy/trip.sh` only ever runs with the meter on, which is the worst place
# to discover a bug in it: the 2026-09-28 trip cost ₹703 because the box stayed
# up while a human was asked for something. Its two hard stops both guard
# failures that are invisible until after the build, so they are the part most
# worth exercising -- and they can be exercised for nothing by putting a fake
# `ssh` and `gcloud` on PATH and giving the script a fixture `.env` to read.
#
# What this cannot do is prove the real box behaves this way. It proves the
# script's logic: that each stop fires on the input it is for, that the happy
# path reaches the end, and that no value out of the `.env` is ever printed.
# --------------------------------------------------------------------------

TRIP = DEPLOY / "trip.sh"

# Recognisable strings so "did a secret leak into the output" is a substring
# search rather than a judgement call.
SENTINELS = {
    "SEXTANT_PROXY_SECRET": "sentinel0proxy0secret0do0not0print",
    "GEMINI_API_KEY": "AIzaSENTINELMODELKEYdonotprint",
    "BASIC_AUTH_HASH": "$2a$14$sentinelhashdonotprint",
}

GOOD_ENV = "\n".join(
    [
        "PUBLIC_URL=https://example.invalid",
        f"BASIC_AUTH_USER=ada\nBASIC_AUTH_HASH={SENTINELS['BASIC_AUTH_HASH']}",
        f"BASIC_AUTH_USER_2=grace\nBASIC_AUTH_HASH_2={SENTINELS['BASIC_AUTH_HASH']}",
        "BASIC_AUTH_USER_3=\nBASIC_AUTH_HASH_3=",
        f"SEXTANT_PROXY_SECRET={SENTINELS['SEXTANT_PROXY_SECRET']}",
        f"GEMINI_API_KEY={SENTINELS['GEMINI_API_KEY']}",
        "SEXTANT_DAILY_BUDGET_USD=1.00",
        "",
    ]
)

_SSH_STUB = """#!/usr/bin/env bash
# Stands in for ssh. The last argument is the remote command; anything that
# only reads the box's .env is run for real against the fixture, so the greps
# and the sed under test are the real ones. Everything else is canned.
for a in "$@"; do cmd="$a"; done
cd "$FAKE_BOX" || exit 90
case "$cmd" in
  true)                        exit 0 ;;
  *"X-Sextant-User: forged"*)  echo "${FAKE_FORGED_CODE:-403}" ;;
  *"tar -xzf"*)                cat >/dev/null; echo "   synced 1 files" ;;
  *"python -"*)                cat >/dev/null; echo "     audit ran" ;;
  *"up -d --build"*)           echo "built" ;;
  *" ps --format"*)            printf 'NAME\\tSTATUS\\nagenticrag-api-1\\tUp\\n' ;;
  *"logs api"*)                echo "no stale names" ;;
  *"/stats"*)                  echo "$FAKE_STATS" ;;
  *"/health"*)                 echo "$FAKE_HEALTH" ;;
  *grep*|*"sed -n"*)           bash -c "$cmd" ;;
  *)                           echo "UNHANDLED: $cmd" >&2; exit 97 ;;
esac
"""

_GCLOUD_STUB = """#!/usr/bin/env bash
case "$*" in
  *"instances describe"*) echo "${FAKE_VM_STATUS:-RUNNING}" ;;
esac
exit 0
"""


def _run_trip(tmp_path, env_text, **extra_env):
    """Run the whole script offline. Returns (exit code, stdout+stderr)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("ssh", _SSH_STUB), ("gcloud", _GCLOUD_STUB)):
        f = bin_dir / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)

    box = tmp_path / "box" / "agenticrag"
    box.mkdir(parents=True)
    (box / ".env").write_text(env_text)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_BOX": str(box.parent),
        "FAKE_HEALTH": (
            '{"status":"healthy","mcp_connected":true,'
            '"model_configured":true,"budget":{"budget_usd":0.6}}'
        ),
        "FAKE_STATS": (
            '{"collection_size":79,"documents":21,'
            '"summaries":21,"persist_dir":"/data/chroma"}'
        ),
        **extra_env,
    }
    done = subprocess.run(
        ["bash", str(TRIP)], capture_output=True, text=True, env=env, timeout=300
    )
    return done.returncode, done.stdout + done.stderr


class TestTheTripRefusesToBuildOnABoxThatWouldBreak:
    def test_an_empty_proxy_secret_stops_the_trip_before_the_build(self, tmp_path):
        # Caddy forwards X-Sextant-User whether or not the app can verify it,
        # so an empty secret is not a degraded mode -- it is every request 403.
        code, out = _run_trip(tmp_path, GOOD_ENV.replace(
            f"SEXTANT_PROXY_SECRET={SENTINELS['SEXTANT_PROXY_SECRET']}",
            "SEXTANT_PROXY_SECRET=",
        ))
        assert code != 0
        assert "SEXTANT_PROXY_SECRET is missing or empty" in out
        assert "403" in out
        assert "shipping the working tree" not in out

    def test_the_secret_being_absent_altogether_stops_it_too(self, tmp_path):
        code, out = _run_trip(tmp_path, "\n".join(
            line for line in GOOD_ENV.splitlines()
            if not line.startswith("SEXTANT_PROXY_SECRET")
        ))
        assert code != 0
        assert "SEXTANT_PROXY_SECRET is missing or empty" in out

    def test_the_remediation_generates_the_value_on_the_box(self, tmp_path):
        # The point of printing a command rather than running one is that the
        # secret is created where it is used and never crosses this machine.
        _, out = _run_trip(tmp_path, "SEXTANT_PROXY_SECRET=\n")
        assert "openssl rand -hex 32" in out
        assert "\\$(openssl" in out, "unescaped -- openssl would run locally"

    def test_pre_rename_env_names_still_stop_it(self, tmp_path):
        # 0.8.1 removed the AGENTICRAG_ fallback; a container built against a
        # pre-rename file has no budget cap and no CORS allowlist.
        code, out = _run_trip(tmp_path, GOOD_ENV + "AGENTICRAG_RATE_LIMIT=20\n")
        assert code != 0
        assert "AGENTICRAG_* names" in out
        assert "shipping the working tree" not in out

    def test_the_box_is_parked_even_when_a_check_stops_the_trip(self, tmp_path):
        # Parking is an EXIT trap precisely because a checklist is what failed.
        _, out = _run_trip(tmp_path, "SEXTANT_PROXY_SECRET=\n")
        assert "parking agenticrag" in out


@pytest.fixture(scope="module")
def good_run(tmp_path_factory):
    """One full offline run of the script; the tar of the repo is not free."""
    return _run_trip(tmp_path_factory.mktemp("trip"), GOOD_ENV)


class TestWhatTheTripReportsWithoutEnforcing:
    def test_a_well_formed_box_runs_to_the_end(self, good_run):
        code, out = good_run
        assert "proxy secret set" in out
        assert "safe to build" in out
        assert "done - the trap parks the box next" in out
        assert code == 0

    def test_every_variable_the_box_has_is_listed_by_name(self, good_run):
        # The listing is the operator's only view of the box's .env, and the
        # second and third gate users are the whole point of this trip.
        _, out = good_run
        for name in ("BASIC_AUTH_USER_2", "BASIC_AUTH_HASH_2", "SEXTANT_PROXY_SECRET"):
            assert f"  {name}\n" in out, f"{name} missing from the names listing"

    def test_it_counts_the_gate_slots_that_are_actually_filled(self, good_run):
        # Two users is the minimum that can demonstrate isolation; the third
        # slot is present but empty in the fixture and must not be counted.
        _, out = good_run
        assert "basic_auth users: 2" in out

    def test_a_missing_share_is_a_note_not_a_failure(self, good_run):
        _, out = good_run
        assert "no SEXTANT_DAILY_BUDGET_SHARE" in out

    def test_an_empty_model_key_is_a_note_not_a_failure(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV.replace(
            f"GEMINI_API_KEY={SENTINELS['GEMINI_API_KEY']}", "GEMINI_API_KEY="
        ))
        assert "GEMINI_API_KEY is empty" in out
        assert code == 0, "retrieval still works without a key; this must not stop a deploy"

    def test_no_value_out_of_the_env_is_ever_printed(self, good_run):
        # Step 2 prints the box's variable NAMES on purpose. A sed that lost
        # its capture group would print the file, into a terminal and a
        # scrollback, for a public repo's deploy.
        _, out = good_run
        for name, value in SENTINELS.items():
            assert name in out, f"{name} should be listed by name"
            assert value not in out, f"{name}'s value reached the output"


class TestTheTripChecksTheGateAfterTheBuild:
    def test_a_forged_name_refused_by_the_app_passes(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_FORGED_CODE="403")
        assert "refused (403)" in out
        assert code == 0

    def test_a_forged_name_the_app_accepts_is_called_out(self, tmp_path):
        # Going straight at the api container skips Caddy, so a 200 here means
        # a client can name itself -- the whole of 0.8.3 undone.
        _, out = _run_trip(tmp_path, GOOD_ENV, FAKE_FORGED_CODE="200")
        assert "expected 403" in out
        assert "a client can name itself" in out


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    """A store holding one shared document, one pre-0.8.2 upload id, and two
    owners who uploaded a file of the same name -- the case 0.8.2 exists for."""
    chromadb = pytest.importorskip("chromadb")
    path = tmp_path_factory.mktemp("chroma")
    ids = ["handbook", "upload:notes", "upload:ada:report", "upload:grace:report"]
    chromadb.PersistentClient(path=str(path)).create_collection("documents").add(
        ids=[f"{d}#0" for d in ids],
        documents=["x"] * len(ids),
        embeddings=[[0.1, 0.2]] * len(ids),
        metadatas=[{"document_id": d} for d in ids],
    )
    return path


class TestTheDocumentIdAudit:
    """The audit is a python heredoc inside the script, so it is extracted and
    run for real against a real store -- which also pins that the two stay in
    step. 0.8.2 namespaced upload ids as `upload:<owner>:<stem>`; anything
    still spelled `upload:<stem>` predates it and belongs to nobody in
    particular, and confirming the box holds none is a clause of the trip.
    """

    @staticmethod
    def _audit_source() -> str:
        body = TRIP.read_text().split("<<'AUDIT'", 1)[1]
        return body.split("\nAUDIT\n", 1)[0].split("\n", 1)[1]

    def _run(self, store) -> str:
        done = subprocess.run(
            [sys.executable, "-c", self._audit_source()],
            capture_output=True,
            text=True,
            env={**os.environ, "SEXTANT_CHROMA_DIR": str(store)},
            timeout=120,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    def test_a_pre_0_8_2_id_is_named_not_merely_counted(self, store):
        # "one stale id" sends you looking; the id itself is actionable.
        assert "pre-0.8.2 upload ids: upload:notes" in self._run(store)

    def test_namespaced_ids_are_not_mistaken_for_stale_ones(self, store):
        out = self._run(store)
        assert "upload:ada:report" not in out.split("pre-0.8.2")[1]

    def test_it_says_who_has_uploads(self, store):
        assert "owners with uploads: ada, grace" in self._run(store)

    def test_it_counts_every_document_once_not_every_chunk(self, store):
        assert "4 documents" in self._run(store)

    def test_a_clean_store_says_so_rather_than_printing_nothing(self, tmp_path):
        chromadb = pytest.importorskip("chromadb")
        chromadb.PersistentClient(path=str(tmp_path)).create_collection("documents").add(
            ids=["handbook#0"],
            documents=["x"],
            embeddings=[[0.1, 0.2]],
            metadatas=[{"document_id": "handbook"}],
        )
        assert "pre-0.8.2 upload ids: none" in self._run(tmp_path)

    def test_the_audit_loads_no_embedder(self):
        # It runs inside the api container next to a live process; pulling a
        # sentence-transformer in to list ids would be minutes and memory for
        # metadata chroma already has.
        source = self._audit_source()
        assert "embeddings" not in source
        assert "sentence_transformers" not in source
        assert 'include=["metadatas"]' in source
