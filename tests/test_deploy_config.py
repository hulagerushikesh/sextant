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
import pathlib
import re
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
  # A stub that can only say yes makes "ssh came up" unfalsifiable, and
  # `--keep-up` on a box that never came up is the whole point of one of the
  # tests below.
  true)                        exit "${FAKE_SSH_DEAD:-0}" ;;
  *"X-Sextant-User: forged"*)  echo "${FAKE_FORGED_CODE:-403}" ;;
  *"tar -xzf"*)                cat >/dev/null; echo "   synced 1 files" ;;
  *"STEM="*)                   cat >/dev/null
                               sort -u "$FAKE_STATE.corpus" 2>/dev/null \
                                 | sed 's/^/upload:/;s/$/:sextant-trip-probe/' ;;
  *"sextant-forget"*)          if [ "${FAKE_FORGET_FAILS:-0}" != 1 ]; then
                                 : > "$FAKE_STATE.corpus"
                               fi ;;
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
# Every invocation is logged, so "the door was shut and nothing was started"
# is a thing a test can read rather than a thing a comment can claim.
echo "$*" >> "$S.gcloud"
case "$*" in
  *"firewall-rules describe"*)
    echo "${FAKE_SSH_RANGES-203.0.113.7/32}" ;;
  *"instances describe"*)
    cat "$S" 2>/dev/null || echo RUNNING ;;
  *"instances start"*)
    echo RUNNING > "$S" ;;
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
# Step 0 asks a public service for this machine's own address, which is not a
# request to the box and must be answered before the gate arguments are read.
case "$*" in
  *checkip*) echo "${FAKE_MY_IP-203.0.113.7}"; exit 0 ;;
esac
if [ "${FAKE_GATE_DOWN:-0}" = 1 ]; then echo 000; exit 7; fi
auth=""; hdrs=""; URL_PATH="/health"; discard_body=0; want_code=0
while [ $# -gt 0 ]; do
  case "$1" in
    --config) auth=$(sed -n 's/^user = "\\(.*\\)"$/\\1/p' "$2"); shift 2 ;;
    -H)       hdrs="$hdrs|$2"; shift 2 ;;
    # Honoured, because `-o /dev/null -w %{http_code}` is precisely how a
    # caller sees only the status and never the body -- and a 200 whose body
    # says `"success": false` is the thing step 7 has to be able to catch.
    -o)       if [ "$2" = /dev/null ]; then discard_body=1; fi; shift 2 ;;
    # Without -w curl prints the body and nothing else, which is how
    # `stats_docs` reads /stats -- appending a status line there would hand
    # json.load trailing junk and make every count -1.
    -w)       want_code=1; shift 2 ;;
    http*)    URL_PATH="/${1#*://*/}"; case "$1" in */health) URL_PATH=/health ;;
                */stats) URL_PATH=/stats ;; */upload) URL_PATH=/upload ;; esac; shift ;;
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
  *"|$auth|"*) ;;
  *)           echo 401; exit 0 ;;
esac

# Past the gate. `who` is the name Caddy would have set from the credentials --
# never the X-Sextant-User the client sent, unless FAKE_HONOURS_NAME models a
# proxy that forwards the client's copy instead of overwriting it.
who="${auth%%:*}"
if [ "${FAKE_HONOURS_NAME:-0}" = 1 ]; then
  case "$hdrs" in *"X-Sextant-User: "*) who="${hdrs##*X-Sextant-User: }"; who="${who%%|*}" ;; esac
fi
corpus="$FAKE_STATE.corpus"
base="${FAKE_BASE_DOCS:-21}"

case "$URL_PATH" in
  /upload)
    # 200 with "success": false is what the real endpoint answers for a file it
    # could not read or an ingest that failed -- the status code only says the
    # request arrived. Nothing is stored in that case.
    if [ "${FAKE_UPLOAD_REJECTS:-0}" = 1 ]; then
      body='{"success":false,"documents_added":0,'
      body="$body"'"error":"No readable files in the upload."}'
    else
      # FAKE_COLLIDING_IDS models the pre-0.8.2 scheme, where the id was
      # `upload:<stem>` and the second upload replaced the first.
      if [ "${FAKE_COLLIDING_IDS:-0}" = 1 ]; then : > "$corpus"; fi
      echo "$who" >> "$corpus"
      body='{"success":true,"documents_added":1,"collection_size":80}'
    fi ;;
  /stats)
    mine=$(grep -cx "$who" "$corpus" 2>/dev/null)
    case "$mine" in ""|0) mine=0 ;; *) mine=1 ;; esac
    body=$(printf '{"collection_size":79,"documents":%s,"summaries":21,' "$((base + mine))")
    body="$body"'"persist_dir":"/data/chroma"}' ;;
  *) body="" ;;
esac
if [ "$discard_body" = 1 ]; then
  echo 200
else
  if [ -n "$body" ]; then echo "$body"; fi
  if [ "$want_code" = 1 ]; then echo 200; fi
fi
"""


def _run_trip(tmp_path, env_text, args=(), vm_state="RUNNING", **extra_env):
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
    # actually finds mid-session: that is what step 1 skips creating and what
    # park has to release. `state="TERMINATED"` is the other real starting
    # point -- a parked box, where step 1 does reserve and start. Without it,
    # "nothing was started" is unfalsifiable, because a box already RUNNING is
    # never started by anything.
    state = tmp_path / "vm-state"
    state.write_text(vm_state + "\n")
    state.with_suffix(".ip").write_text("10.0.0.1\n")
    # The box's corpus, as far as the probe scan is concerned: empty until
    # step 7 uploads into it.
    pathlib.Path(str(state) + ".corpus").write_text("")

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
        assert "check(s) failed -- the box is deployed but not proven" in out
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
        assert "check(s) failed" in out
        assert "agenticrag is TERMINATED" in out
        assert code != 0


class TestTheIsolationIsProvenFromOutside:
    """Step 7 — milestone 21's pre-registered success criterion, run by the
    script rather than by hand with the meter on:

        two different basic_auth users each upload a file of the same name,
        both survive, each sees their own and not the other's, and a
        client-supplied X-Sextant-User is refused.

    Step 6 proves the gate, and every check in it is a read, so it says nothing
    about what is behind the gate. This is the only part of the trip that
    writes: two small text files, removed in the EXIT trap rather than at the
    end of the step, because the run that most needs the cleanup is the one
    that died half way through.
    """

    AUTH = {"SEXTANT_TRIP_AUTH": "ada:pw", "SEXTANT_TRIP_AUTH_2": "grace:pw"}

    def test_a_correct_box_proves_the_whole_criterion(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, **self.AUTH)
        for line in (
            "first user uploads sextant-trip-probe.txt    stored 1",
            "they see one more                            22",
            "the second user sees nothing new             21",
            "naming yourself the other user               22",
            "second user uploads the same filename        stored 1",
            "the first user's copy survived               22",
            "probe documents in the store                 2",
            "owned by distinct names                      2",
        ):
            assert line in out, line
        assert code == 0

    def test_the_pre_0_8_2_id_scheme_is_caught(self, tmp_path):
        # `upload:<stem>` was global, so the second upload replaced the first.
        # That is the defect 0.8.2 fixed and the one this step exists to prove
        # the box does not have.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_COLLIDING_IDS="1", **self.AUTH)
        assert "the first user's copy survived               got 21, wanted 22" in out
        assert "probe documents in the store                 got 1, wanted 2" in out
        assert code != 0

    def test_a_proxy_that_forwards_the_clients_name_is_caught(self, tmp_path):
        # The whole point of the header: if Caddy passes the client's copy
        # through instead of overwriting it, one person reads another's corpus
        # by asking.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_HONOURS_NAME="1", **self.AUTH)
        assert "naming yourself the other user               got 21, wanted 22" in out
        assert code != 0

    def test_the_forged_name_is_checked_while_the_two_views_differ(self, tmp_path):
        # It has to run after the first upload and before the second: afterwards
        # both users are at the same count, and a check whose two sides agree
        # cannot fail. The first draft of this step passed against a proxy that
        # forwarded the name for exactly that reason.
        _, out = _run_trip(tmp_path, GOOD_ENV, **self.AUTH)
        order = out.index("naming yourself the other user")
        assert out.index("first user uploads") < order
        assert order < out.index("second user uploads the same filename")

    def test_the_probes_are_removed_even_when_the_trip_fails(self, tmp_path):
        # Cleanup is in the trap, not at the end of the step.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_COLLIDING_IDS="1", **self.AUTH)
        assert code != 0
        assert "removing the probe documents step 7 uploaded" in out
        assert "the corpus is back to what it was" in out

    def test_probes_left_behind_are_not_a_successful_trip(self, tmp_path):
        # Two documents left in the production corpus is not something an exit
        # code of 0 should be able to say happened -- the same rule as the park.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_FORGET_FAILS="1", **self.AUTH)
        assert "STILL THERE: upload:ada:sextant-trip-probe" in out
        assert "probe documents are still in the production corpus" in out
        assert "remove by hand" in out
        assert code != 0

    def test_nothing_is_uploaded_without_two_gate_users(self, tmp_path):
        # One name cannot demonstrate isolation, so the step must not write to
        # the corpus at all rather than write and prove nothing.
        code, out = _run_trip(tmp_path, GOOD_ENV, SEXTANT_TRIP_AUTH="ada:pw")
        assert "needs both gate users exported -- isolation is unproven" in out
        assert "removing the probe documents" not in out
        assert code == 0

    def test_the_cleanup_finds_documents_by_scanning_not_by_guessing(self, tmp_path):
        # The ids are read back off the store rather than rebuilt from the
        # usernames here, so `safe_owner()` spelling a name differently cannot
        # leave documents behind that the trip then reports as gone.
        _, out = _run_trip(tmp_path, GOOD_ENV, **self.AUTH)
        assert "removing upload:ada:sextant-trip-probe" in out
        assert "removing upload:grace:sextant-trip-probe" in out


class TestAnUploadIsJudgedByWhatItStored:
    """`/upload` answers 200 with `"success": false` when the file was
    unreadable, the tool was unavailable, or the ingest failed. The status code
    says the request arrived, not that anything was stored -- so checking it
    alone makes "the user uploaded a file" a check that passes when they did
    not, and the only symptom is the count assertions failing with no stated
    reason.
    """

    AUTH = {"SEXTANT_TRIP_AUTH": "ada:pw", "SEXTANT_TRIP_AUTH_2": "grace:pw"}

    def test_a_stored_upload_says_what_it_stored(self, tmp_path):
        _, out = _run_trip(tmp_path, GOOD_ENV, **self.AUTH)
        assert "first user uploads sextant-trip-probe.txt    stored 1" in out

    def test_a_refused_upload_is_not_a_pass(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_UPLOAD_REJECTS="1", **self.AUTH)
        assert code != 0
        assert "wanted stored 1" in out

    def test_a_refusal_says_why_on_the_line_that_names_the_action(self, tmp_path):
        # Otherwise the operator reads "200" and then four unexplained count
        # mismatches, with the actual reason nowhere on screen.
        _, out = _run_trip(tmp_path, GOOD_ENV, FAKE_UPLOAD_REJECTS="1", **self.AUTH)
        assert "got refused: No readable files in the upload." in out

    def test_nothing_is_left_behind_when_nothing_was_stored(self, tmp_path):
        _, out = _run_trip(tmp_path, GOOD_ENV, FAKE_UPLOAD_REJECTS="1", **self.AUTH)
        assert "nothing to remove" in out


class TestTheSshDoorIsCheckedBeforeTheMeterStarts:
    """Port 22 is open to one /32, and a home ISP moves that address.

    On 2026-10-07 a trip started the box, waited two minutes for an ssh that
    could not arrive because `agenticrag-ssh` still named a previous day's
    address, printed "ssh never came up" -- naming the symptom and nothing
    about the cause -- and then, because `--keep-up` was on, left the box
    billing. Both halves of the real answer were readable from the laptop for
    nothing, before anything was started.
    """

    def _gcloud_log(self, tmp_path):
        log = pathlib.Path(str(tmp_path / "vm-state") + ".gcloud")
        return log.read_text() if log.exists() else ""

    def test_a_source_range_that_excludes_this_machine_stops_the_trip(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_SSH_RANGES="198.51.100.0/24")
        assert code != 0
        assert "port 22 is NOT open to this machine" in out

    def test_nothing_is_started_when_the_door_is_shut(self, tmp_path):
        """The whole value of step 0 is that it is free. If it runs after the
        start it has already cost Rs2 and a second trip.

        From a *parked* box, which is the only state in which this can fail: a
        box already RUNNING is never started by anything, so asserting against
        the default fixture would pass no matter where step 0 sat.
        """
        _run_trip(
            tmp_path,
            GOOD_ENV,
            vm_state="TERMINATED",
            FAKE_SSH_RANGES="198.51.100.0/24",
        )
        log = self._gcloud_log(tmp_path)
        assert "instances start" not in log
        assert "addresses create" not in log
        # And it did get as far as asking about the door.
        assert "firewall-rules describe" in log

    def test_the_shut_door_prints_the_command_that_opens_it(self, tmp_path):
        _, out = _run_trip(tmp_path, GOOD_ENV, FAKE_SSH_RANGES="198.51.100.0/24")
        assert "firewall-rules update agenticrag-ssh" in out
        # The address it tells you to allow is this machine's, read at run time
        # -- never a value stored anywhere, because this repo is public.
        assert "--source-ranges=203.0.113.7/32" in out

    def test_it_says_which_range_is_allowed_and_which_one_you_are(self, tmp_path):
        _, out = _run_trip(tmp_path, GOOD_ENV, FAKE_SSH_RANGES="198.51.100.0/24")
        assert "198.51.100.0/24" in out
        assert "203.0.113.7" in out

    def test_a_wider_range_than_one_address_is_still_open(self, tmp_path):
        """Containment, not string equality: comparing the text would call a
        /24 that does contain this machine a shut door."""
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_SSH_RANGES="203.0.113.0/24")
        assert "port 22 is open to 203.0.113.7" in out
        assert code == 0

    def test_one_allowed_range_among_several_is_enough(self, tmp_path):
        _, out = _run_trip(
            tmp_path, GOOD_ENV, FAKE_SSH_RANGES="198.51.100.1/32,203.0.113.7/32"
        )
        assert "port 22 is open to" in out

    def test_an_address_service_that_answers_rubbish_does_not_stop_a_trip(self, tmp_path):
        """A flaky third party must not be able to ground the box. The ssh wait
        is still there to catch what this missed."""
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_MY_IP="<html>503</html>")
        assert "door not checked" in out
        assert code == 0

    def test_a_silent_address_service_does_not_stop_a_trip(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_MY_IP="")
        assert "could not learn this machine's address" in out
        assert code == 0

    def test_a_rule_with_no_readable_ranges_does_not_stop_a_trip(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_SSH_RANGES="")
        assert "no source ranges readable on agenticrag-ssh" in out
        assert code == 0

    def test_keep_up_does_not_keep_a_box_that_never_came_up(self, tmp_path):
        """`--keep-up` means "leave it up, I am going to work on it", which
        presumes you can reach it. The 2026-10-07 run typed it, never reached
        the box, and left it billing -- the 2026-09-28 failure inside the
        script written to prevent it."""
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            args=("--keep-up", "--no-deploy"),
            FAKE_SSH_DEAD="1",
            VM_SSH_TRIES="2",
            VM_SSH_SLEEP="0",
        )
        assert "parking anyway" in out
        assert "instances stop" in self._gcloud_log(tmp_path)
        assert (tmp_path / "vm-state").read_text().strip() == "TERMINATED"
        assert code != 0

    def test_keep_up_still_keeps_a_box_that_did_come_up(self, tmp_path):
        """The exemption is not being taken away -- it is being made true."""
        _, out = _run_trip(tmp_path, GOOD_ENV, args=("--keep-up", "--no-deploy"))
        assert "NOT parking (--keep-up)" in out
        assert "instances stop" not in self._gcloud_log(tmp_path)

    def test_a_trip_that_cannot_reach_the_box_says_to_look_at_the_box(self, tmp_path):
        """Once step 0 has confirmed the door is open, "ssh never came up" is
        the right message: the remaining causes are all on the box."""
        _, out = _run_trip(
            tmp_path, GOOD_ENV, FAKE_SSH_DEAD="1", VM_SSH_TRIES="2", VM_SSH_SLEEP="0"
        )
        assert "step 0 said the door was open, so look at the box" in out


class TestTheRepoHoldsNoRealAddresses:
    """This repo is public, and `trip.sh` now handles addresses.

    Step 0 reads the operator's public address at run time precisely so it is
    never stored -- and then the first draft of the write-up for step 0 pasted
    the real pair into three tracked files, because sample output is the one
    place nobody thinks of as a secret. Documentation ranges and private
    ranges are fine; a routable address is not.
    """

    # RFC 5737 documentation, RFC 1918 private, loopback, link-local, the
    # unspecified address, and TEST-NET-style ranges the fixtures use.
    ALLOWED = (
        "192.0.2.",
        "198.51.100.",
        "203.0.113.",
        "10.",
        "127.",
        "169.254.",
        "172.16.",
        "172.17.",
        "172.18.",
        "192.168.",
        "0.0.0.0",
        "255.255.255.",
    )
    SKIP_DIRS = {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        "chroma_db",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
    SUFFIXES = {".md", ".sh", ".py", ".ts", ".tsx", ".yml", ".yaml", ".json", ".example"}

    def _offenders(self):
        pattern = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
        root = pathlib.Path(__file__).resolve().parent.parent
        bad = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in self.SUFFIXES:
                continue
            if self.SKIP_DIRS & set(path.relative_to(root).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                for found in pattern.findall(line):
                    octets = [int(part) for part in found.split(".")]
                    if any(octet > 255 for octet in octets):
                        continue  # a version string, not an address
                    if found.startswith(self.ALLOWED):
                        continue
                    bad.append(f"{path.relative_to(root)}:{line_no}: {found}")
        return bad

    def test_no_routable_address_is_committed(self):
        offenders = self._offenders()
        assert not offenders, "real addresses in a public repo:\n" + "\n".join(offenders)

    def test_the_scan_would_notice_one(self):
        """A pin that cannot fail is a comment: the scan has to actually catch
        the shape that was committed.

        The sample is assembled from parts rather than written out, because a
        routable literal here would be caught by the test above -- which is
        the scan working, but would also mean this file holds the kind of
        address the scan exists to keep out.
        """
        sample = ".".join(["198", "19", "177", "9"])
        pattern = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
        found = pattern.findall(f"agenticrag-ssh allows {sample}/32")
        assert found == [sample]
        assert not found[0].startswith(self.ALLOWED)
        # A version string is not an address, and must not be reported as one.
        assert not pattern.findall("sextant 0.8.7")
        # A number whose octets do not fit matches the regex but is not an
        # address, and `_offenders` drops it on exactly that test.
        oversized = pattern.findall("build 999.999.999.999")
        assert oversized == ["999.999.999.999"]
        assert any(int(part) > 255 for part in oversized[0].split("."))


class TestTheForgedNameCheckCounts:
    """Step 5 asks the api container whether it believes an unvouched name.

    It compared the answer and printed it, and that was all: no counter, no
    effect on the exit code. So a trip could deploy 0.8.3+, find that a client
    can name itself -- the thing the middleware exists to stop -- print it to
    stderr, and still exit 0 with the box reported as shipped. Compared,
    reported, and not counted: items 5 through 9 one more time.

    It must not fail unconditionally, though. On a `--no-deploy` run the box is
    whatever it already was, and on the pre-0.8.3 box still deployed today a
    200 there is the correct answer.
    """

    AUTH = {"SEXTANT_TRIP_AUTH": "ada:pw", "SEXTANT_TRIP_AUTH_2": "grace:pw"}

    def test_a_deploy_that_leaves_the_name_believed_fails_the_trip(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_FORGED_CODE="200")
        assert "a client can name itself" in out
        assert "check(s) failed" in out
        assert code != 0

    def test_the_count_survives_step_6(self, tmp_path):
        """The load-bearing one. `GATE_FAILURES=0` lived inside step 6, which
        runs after step 5 -- so a step-5 failure was zeroed before anything
        read it. With the gate credentials exported step 6 really runs, which
        is the ordering that used to lose the count."""
        code, out = _run_trip(
            tmp_path, GOOD_ENV, FAKE_FORGED_CODE="200", **self.AUTH
        )
        assert "a real user" in out  # step 6 did run
        assert "1 check(s) failed" in out
        assert code != 0

    def test_no_deploy_does_not_fail_on_the_box_as_it_stands(self, tmp_path):
        """The box deployed today is pre-0.8.3 and answers 200 here. A
        preflight run must not report that as this run's failure."""
        code, out = _run_trip(
            tmp_path, GOOD_ENV, args=("--no-deploy",), FAKE_FORGED_CODE="200"
        )
        assert "not a result of this run" in out
        assert "check(s) failed" not in out
        assert code == 0

    def test_a_refused_name_is_a_pass_on_a_deploy(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV)
        assert "refused (403)" in out
        assert "a client can name itself" not in out
        assert code == 0

    def test_a_refused_name_is_a_pass_without_a_deploy_too(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, args=("--no-deploy",))
        assert "refused (403)" in out
        assert code == 0
