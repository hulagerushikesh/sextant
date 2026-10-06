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
# Stands in for gcloud, and unlike the ssh stub it keeps state: the instance
# answers RUNNING until a `stop` succeeds and TERMINATED afterwards, and the
# reserved address exists until a `delete` succeeds. A stub that always says
# TERMINATED would make "the trip parked the box" an assertion that cannot
# fail -- which is how a trip that never parked passed the gate until now.
S="$FAKE_STATE"
case "$*" in
  *"instances describe"*)
    cat "$S" 2>/dev/null || echo RUNNING ;;
  *"instances stop"*)
    if [ "${FAKE_STOP_FAILS:-0}" = 1 ]; then exit 1; fi
    echo TERMINATED > "$S" ;;
  *"addresses describe"*)
    if [ -f "$S.ip" ]; then echo 10.0.0.1; else exit 1; fi ;;
  *"addresses delete"*)
    if [ "${FAKE_ADDRESS_STICKS:-0}" = 1 ]; then exit 1; fi
    rm -f "$S.ip" ;;
  *"addresses list"*)
    if [ -f "$S.ip" ]; then echo agenticrag-ip; fi ;;
esac
exit 0
"""


_CURL_STUB = """#!/usr/bin/env bash
# Stands in for curl in step 6, which runs from the laptop rather than over
# ssh. It reads the config file the script passes so the user:pass arrives the
# same way Caddy would see it, and answers the way a correctly configured gate
# would -- or, under FAKE_GATE_*, the way a broken one would.
if [ "${FAKE_GATE_DOWN:-0}" = 1 ]; then echo 000; exit 7; fi
auth=""; hdrs=""
while [ $# -gt 0 ]; do
  case "$1" in
    --config) auth=$(sed -n 's/^user = "\\(.*\\)"$/\\1/p' "$2"); shift 2 ;;
    -H)       hdrs="$hdrs|$2"; shift 2 ;;
    *)        shift ;;
  esac
done
# Caddy appending the proof header instead of setting it: the app then sees the
# client's forged copy beside the real one and refuses.
case "$hdrs" in
  *X-Sextant-Proxy-Auth*)
    if [ "${FAKE_GATE_APPENDS:-0}" = 1 ]; then echo 403; exit 0; fi ;;
esac
if [ -z "$auth" ]; then
  if [ "${FAKE_GATE_OPEN:-0}" = 1 ]; then echo 200; else echo 401; fi
  exit 0
fi
case "|${FAKE_GATE_USERS:-ada:pw|grace:pw}|" in
  *"|$auth|"*) echo 200 ;;
  *)           echo 401 ;;
esac
"""


def _run_trip(tmp_path, env_text, args=(), **extra_env):
    """Run the whole script offline. Returns (exit code, stdout+stderr)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("ssh", _SSH_STUB), ("gcloud", _GCLOUD_STUB), ("curl", _CURL_STUB)):
        f = bin_dir / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)

    box = tmp_path / "box" / "agenticrag"
    box.mkdir(parents=True)
    (box / ".env").write_text(env_text)

    # The box starts up with its address reserved, which is the state a trip
    # actually finds: that is what step 1 skips creating and what park has to
    # release.
    state = tmp_path / "vm-state"
    state.write_text("RUNNING\n")
    state.with_suffix(".ip").write_text("10.0.0.1\n")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_BOX": str(box.parent),
        "FAKE_STATE": str(state),
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
        ["bash", str(TRIP), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
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


class TestTheTripProvesItParkedTheBox:
    """The trap's own result, which nothing checked until today.

    `park()` has always read the instance's state back and printed it. Printing
    is not checking: an offline run of the whole script ended `agenticrag is
    RUNNING` and exited 0, and so did this module's happy-path test, because
    the stub answered RUNNING to every question and nobody compared the answer
    to anything. That is the 2026-09-28 failure one level down -- the checklist
    became a trap, and then the trap's outcome became the new unread line.
    """

    def test_the_happy_path_actually_terminates_the_box(self, good_run):
        code, out = good_run
        assert "agenticrag is TERMINATED" in out
        assert "reserved addresses: 0" in out
        assert code == 0

    def test_a_box_that_will_not_stop_is_not_a_successful_trip(self, tmp_path):
        # Everything else passes. The exit code must still say "not parked",
        # because 0 is how a person or a later `&&` reads that claim.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_STOP_FAILS="1")
        assert "done - the trap parks the box next" in out, "the trip itself passed"
        assert code != 0
        assert "STILL RUNNING" in out

    def test_the_alarm_says_what_it_costs_and_how_to_end_it(self, tmp_path):
        _, out = _run_trip(tmp_path, GOOD_ENV, FAKE_STOP_FAILS="1")
        assert "Rs134/day" in out
        assert "gcloud compute instances stop agenticrag" in out

    def test_the_stop_is_retried_before_the_alarm(self, tmp_path):
        # One transient API error is the dullest reason for a bad readback and
        # the cheapest to rule out, so the alarm only fires after a second try.
        _, out = _run_trip(tmp_path, GOOD_ENV, FAKE_STOP_FAILS="1")
        assert "stop did not take (RUNNING), retrying" in out

    def test_an_address_left_reserved_also_takes_the_zero_away(self, tmp_path):
        # Rs21/day for an address nothing is attached to -- smaller than a
        # running box and the same kind of silence.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_ADDRESS_STICKS="1")
        assert "agenticrag is TERMINATED" in out, "the box did park"
        assert code != 0
        assert "still reserved" in out
        assert "gcloud compute addresses delete agenticrag-ip" in out

    def test_keep_up_is_a_decision_not_an_alarm(self, tmp_path):
        # --keep-up is something you have to type. A box left up on purpose is
        # not the failure this guards, so it must not start reading as one.
        code, out = _run_trip(tmp_path, GOOD_ENV, args=["--keep-up"])
        assert "NOT parking (--keep-up)" in out
        assert "STILL" not in out
        assert code == 0

    def test_a_trip_that_failed_keeps_its_own_exit_code(self, tmp_path):
        # The park check may only turn a 0 into a 1. A hard stop that already
        # failed must not have its reason overwritten by a successful park.
        code, out = _run_trip(tmp_path, "SEXTANT_PROXY_SECRET=\n")
        assert code != 0
        assert "SEXTANT_PROXY_SECRET is missing or empty" in out
        assert "agenticrag is TERMINATED" in out
        assert "STILL" not in out


class TestTheGateIsCheckedFromOutside:
    """Step 6, which until now did not exist at all.

    Every other check in the trip goes through `docker exec` at
    `localhost:8000` -- inside the box, behind Caddy. So the trip that exists to
    deploy the gate never touched it: a box whose Caddy was misconfigured, or
    not running, passed every check in step 5 and reported green. These run from
    the operator's machine over the public URL.

    The two 200s read backwards and are the point: `header_up` in Caddy is a
    *set*, so a client's own `X-Sextant-Proxy-Auth` is replaced before the app
    sees it. A forged proof that still succeeds is Caddy working. A 403 would
    mean it appended instead -- and then anyone can send the header themselves.
    """

    AUTH = {"SEXTANT_TRIP_AUTH": "ada:pw", "SEXTANT_TRIP_AUTH_2": "grace:pw"}

    def test_a_correctly_configured_gate_passes_every_check(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, **self.AUTH)
        for line in (
            "no credentials                               401",
            "wrong password                               401",
            "a real user                                  200",
            "a forged proof is overwritten                200",
            "naming yourself, no password                 401",
            "a second user                                200",
        ):
            assert line in out, line
        assert code == 0

    def test_a_gate_that_lets_anyone_in_fails_the_trip(self, tmp_path):
        # The deploy itself succeeded. It is still not a trip that passed.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_GATE_OPEN="1", **self.AUTH)
        assert "no credentials" in out and "got 200, wanted 401" in out
        assert "gate check(s) failed -- the box is deployed but not proven" in out
        assert code != 0

    def test_a_caddy_that_appends_the_proof_header_is_caught(self, tmp_path):
        # Appending rather than setting leaves the client's forged copy beside
        # the real one, which is the whole header being worthless.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_GATE_APPENDS="1", **self.AUTH)
        assert "a forged proof is overwritten" in out
        assert "got 403, wanted 200" in out
        assert code != 0

    def test_a_box_with_no_public_url_is_a_failure_not_a_skip(self, tmp_path):
        # Unlike missing credentials, this is the box being wrong, not the
        # operator declining to prove something.
        code, out = _run_trip(
            tmp_path,
            "\n".join(
                x for x in GOOD_ENV.splitlines() if not x.startswith("PUBLIC_URL")
            ),
            **self.AUTH,
        )
        assert "no PUBLIC_URL on the box -- the gate is unproven" in out
        assert code != 0

    def test_no_credentials_exported_is_a_skip_that_says_so(self, tmp_path):
        # Not a failure: supplying them is the operator's call. But it must not
        # read as a pass, because nothing about the gate was exercised.
        code, out = _run_trip(tmp_path, GOOD_ENV)
        assert "SEXTANT_TRIP_AUTH unset -- nothing here ran" in out
        assert "every check above was inside the box, behind Caddy" in out
        assert code == 0

    def test_one_name_at_the_gate_says_isolation_is_unproven(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, SEXTANT_TRIP_AUTH="ada:pw")
        assert "one name at the gate, so isolation is unproven" in out
        assert code == 0

    def test_the_password_never_reaches_the_output(self, tmp_path):
        # It goes to curl through a config file on a pipe, never argv, so it is
        # not in `ps` either while the trip runs.
        secret = "sentinel0gate0password0do0not0print"
        _, out = _run_trip(
            tmp_path, GOOD_ENV, FAKE_GATE_USERS=f"ada:{secret}",
            SEXTANT_TRIP_AUTH=f"ada:{secret}",
        )
        assert secret not in out

    def test_a_failed_gate_still_parks_the_box(self, tmp_path):
        # The gate's verdict is an `exit`, and the park is a trap, so the order
        # is not something either one has to remember.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_GATE_OPEN="1", **self.AUTH)
        assert code != 0
        assert "agenticrag is TERMINATED" in out

    def test_a_box_that_cannot_be_reached_is_a_failed_check_not_a_crash(self, tmp_path):
        # curl exits non-zero on a refused connection, and `set -o pipefail`
        # would turn that into the script dying mid-step with the park never run --
        # except the trap. It is still the check's problem, not the script's:
        # 000 is not the code wanted, so it counts like any other failure.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_GATE_DOWN="1", **self.AUTH)
        assert "got 000, wanted" in out
        assert "gate check(s) failed" in out
        assert "agenticrag is TERMINATED" in out
        assert code != 0
