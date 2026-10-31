"""The two halves of identity that cannot be tested together.

Caddy sets the header; the app reads it. Nothing in the test suite runs both,
and nothing in the test suite can -- the proxy only exists on the box, and a
VM trip costs money. So what is pinned here is the seam: the header names in
`deploy/Caddyfile` are the ones `sextant/mcp_server/identity.py` declares, and the
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

from sextant import settings
from sextant.mcp_server.identity import (
    CLIENT_HEADER,
    PROXY_HEADER,
    PROXY_SECRET,
    USER_HEADER,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"
API_CLIENT = FRONTEND / "lib" / "api.ts"


@pytest.fixture(scope="module")
def caddyfile() -> str:
    return (DEPLOY / "Caddyfile").read_text()


@pytest.fixture(scope="module")
def env_example() -> str:
    return (DEPLOY / "env.example").read_text()


@pytest.fixture(scope="module")
def api_client() -> str:
    return API_CLIENT.read_text()


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
#
# The hash is padded to a real bcrypt's 60 characters, and that is load-bearing
# rather than tidiness: step 2 now runs deploy/gate-slots.sh on the box and a
# slot it cannot parse stops the trip before the build. The old 30-character
# sentinel was a value the gate would have refused, so this fixture described a
# box that could not serve -- and every trip test below would have been
# asserting about a run that stopped at step 2. **A fixture has to be something
# the real check accepts**, or the harness tests a state the product rejects.
SENTINELS = {
    "SEXTANT_PROXY_SECRET": "sentinel0proxy0secret0do0not0print",
    "GEMINI_API_KEY": "AIzaSENTINELMODELKEYdonotprint",
    "BASIC_AUTH_HASH": "$2a$14$" + "sentinelhashdonotprint".ljust(53, "x"),
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
# `cd "$FAKE_BOX"` with FAKE_BOX unset is `cd ""`, which bash 5.2 and
# earlier accept as a no-op and bash 5.3 (Ubuntu 26.04) rejects as a null
# directory. `_run_deploy` forgot to set it, so this stub answered every
# command on a Mac and none on the image CI migrates to. `:?` makes a
# missing box the same loud failure on both.
cd "${FAKE_BOX:?the ssh stub was given no box to stand in for}" || exit 90
case "$cmd" in
  # `ssh host VAR=v 'bash -s'` -- the preflight, and the only call here that
  # arrives on stdin. Real ssh joins every argument after the host into one
  # command line, so the env assignments reach the script; reading only the
  # last argument would drop APP_DIR and the preflight would cd to "$HOME/".
  "bash -s")                   shift; HOME="$PWD" exec bash -c "$*" ;;
  # A stub that can only say yes makes "ssh came up" unfalsifiable, and
  # `--keep-up` on a box that never came up is the whole point of one of the
  # tests below.
  true)                        exit "${FAKE_SSH_DEAD:-0}" ;;
  *"X-Sextant-User: forged"*)  echo "${FAKE_FORGED_CODE:-403}" ;;
  # `wc -c`, not `cat >/dev/null`: the stub printed "synced" for whatever
  # arrived, including nothing at all, so a tar that failed still read as a
  # successful ship. The byte count makes it checkable.
  *"tar -xzf"*)                wc -c > "$FAKE_STATE.tarbytes"
                               echo "   synced 1 files" ;;
  *"STEM="*)                   cat >/dev/null
                               sort -u "$FAKE_STATE.corpus" 2>/dev/null \
                                 | sed 's/^/upload:/;s/$/:sextant-trip-probe/' ;;
  *"sextant-forget"*)          if [ "${FAKE_FORGET_FAILS:-0}" != 1 ]; then
                                 : > "$FAKE_STATE.corpus"
                               fi ;;
  *"python -"*)                cat >/dev/null; echo "     audit ran" ;;
  *"up -d --build"*)           echo "built" ;;
  # Two containers, because the real box runs two. The stub printed only the
  # api line, so no test could have noticed that Caddy was never checked --
  # the harness was missing the thing the check is for.
  *" ps --format"*)            printf 'NAME\\tSTATUS\\n'
                               case "${FAKE_API_STATUS-Up 7 minutes (healthy)}" in
                                 gone) ;;
                                 *) printf 'agenticrag-api-1\\t%s\\n' \
                                      "${FAKE_API_STATUS-Up 7 minutes (healthy)}" ;;
                               esac
                               case "${FAKE_CADDY_STATUS-Up 7 minutes}" in
                                 gone) ;;
                                 *) printf 'agenticrag-caddy-1\\t%s\\n' \
                                      "${FAKE_CADDY_STATUS-Up 7 minutes}" ;;
                               esac ;;
  # `down`. The point of the arm is that the containers really do go away and
  # the script still has something to say afterwards, so it prints what compose
  # prints and takes its exit status from a knob -- a stub that could only
  # succeed would make "the exit status survives the epilogue" unfalsifiable.
  *"prod.yml down"*)           echo "Container agenticrag-api-1  Removed"
                               echo "Container agenticrag-caddy-1  Removed"
                               exit "${FAKE_DOWN_RC:-0}" ;;
  *"logs api"*)                echo "${FAKE_LOG_LINE-no stale names}" ;;
  *"/stats"*)                  echo "$FAKE_STATS" ;;
  *"/health"*)                 echo "$FAKE_HEALTH" ;;
  # Step 1c: both calls are run for real against the fixture box, so these
  # tests exercise `deploy/set-secrets.sh` itself rather than a canned answer.
  # The install arrives with the script on stdin; the run arrives with the
  # operator's secrets on stdin.
  *set-secrets.sh*)            HOME="$PWD" bash -c "$cmd" ;;
  *grep*|*"sed -n"*)           bash -c "$cmd" ;;
  *)                           echo "UNHANDLED: $cmd" >&2; exit 97 ;;
esac
"""

_GCLOUD_STUB = """#!/usr/bin/env bash
# Stands in for gcloud, and unlike the ssh stub it keeps state: the instance
# answers RUNNING until a `stop` succeeds and TERMINATED afterwards, and the
# reserved address exists until a `delete` succeeds. A stub that always said
# TERMINATED would make "the trip parked the box" an assertion that cannot
# fail -- which is how a trip that never parked passed the gate until now.
S="$FAKE_STATE"
# The verb is matched on the args with every --flag removed, because the two
# callers interleave flags differently: trip.sh runs `compute instances
# describe ...` and deploy.sh runs `compute instances --project=X describe
# ...`. Matching the raw string meant every branch below silently missed for
# deploy.sh: the stub answered nothing, the box read as neither RUNNING nor
# TERMINATED, and a test asserting `instances start` was ABSENT passed for a
# run that had started the box. A pin that cannot fail, in the harness.
norm=""
for a in "$@"; do case "$a" in --*) ;; *) norm="$norm $a" ;; esac; done
norm="${norm# }"
# Every invocation is logged, normalised, so "the door was shut and nothing was
# started" is a thing a test can read rather than a thing a comment can claim.
echo "$norm" >> "$S.gcloud"
# This one is a question about a --format, so it is asked of the raw args. An
# empty answer is a box whose external address was released; a stub that could
# not be empty made `start`'s refusal untestable.
case "$*" in
  *"accessConfigs[0].name"*)
    if [ "${FAKE_NO_EXTERNAL_IP:-0}" = 1 ]; then echo ""; else echo external-nat; fi
    exit 0 ;;
esac
case "$norm" in
  *"firewall-rules describe"*)
    echo "${FAKE_SSH_RANGES-203.0.113.7/32}" ;;
  *"instances describe"*)
    # Honours the --format, because the two callers ask for different ones and
    # the real gcloud answers each differently: trip.sh asks value(status) and
    # gets one field, deploy.sh asks value(status,machineType,natIP) and gets
    # three, tab separated. This stub answered one field to both, so the
    # machine type and the ip in `status`'s own output line were never produced
    # by anything -- `(, us-central1-a)` was the stub's gap being printed. The
    # curl stub had to learn the same lesson about -o and -w.
    st=$(cat "$S" 2>/dev/null)
    if [ ! -f "$S" ]; then st=RUNNING; fi
    # A describe that fails writes nothing to stdout. A blank state file is how
    # a test asks for that, so emit nothing rather than a row of empty fields.
    if [ -z "$st" ]; then exit 0; fi
    case "$*" in
      *machineType*)
        printf '%s\t%s\t%s\n' "$st" "${FAKE_MACHINE_TYPE:-e2-standard-2}" \
          "${FAKE_NAT_IP:-10.0.0.1}" ;;
      *) echo "$st" ;;
    esac ;;
  *"instances start"*)
    echo RUNNING > "$S" ;;
  *"instances stop"*)
    if [ "${FAKE_STOP_FAILS:-0}" = 1 ]; then exit 1; fi
    # The nastier failure: gcloud answers 0 and the box stays up. Without this
    # the stub could not represent "the command worked and the box did not",
    # which is the whole reason the state is read back.
    if [ "${FAKE_STOP_SILENT:-0}" = 1 ]; then exit 0; fi
    echo TERMINATED > "$S" ;;
  *"addresses describe"*)
    if [ -f "$S.ip" ]; then echo 10.0.0.1; else exit 1; fi ;;
  *"addresses delete"*)
    if [ "${FAKE_ADDRESS_STICKS:-0}" = 1 ]; then exit 1; fi
    rm -f "$S.ip" ;;
  *"addresses list"*)
    if [ "${FAKE_NO_ADDRESS:-0}" = 1 ]; then exit 0; fi
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
  # The preflight asks a different service for the same thing, and without
  # this arm it fell through to the gate logic below and answered `401` --
  # which the DNS compare then read as "this VM is 401".
  *ifconfig.me*) echo "${FAKE_MY_IP-203.0.113.7}"; exit 0 ;;
esac
# Cloudflare's DNS API, as step 1b and the park use it. One file of state --
# the A record's content, or empty for no record -- so that "the trip wrote
# the record" and "the name resolves" are one story and the dig stub below
# cannot agree with a write that never happened.
case "$*" in
  *dns_records*)
    method=GET; data=""
    while [ $# -gt 0 ]; do
      case "$1" in
        -X)     method="$2"; shift 2 ;;
        --data) data="$2";   shift 2 ;;
        *)      shift ;;
      esac
    done
    rec="$FAKE_STATE.dns"
    # A token without Zone:DNS:Edit. 200 with "success": false, which is the
    # answer the verdict function exists to read.
    if [ "${FAKE_CF_REFUSES:-0}" = 1 ]; then
      echo '{"success":false,"errors":[{"message":"Actor is not authorized"}]}'
      exit 0
    fi
    case "$method" in
      GET)
        if [ -s "$rec" ]; then
          one='{"id":"rec1","name":"%s","content":"%s","proxied":false,"ttl":60}'
          printf '{"success":true,"result":['"$one"']}\n' \
            "${FAKE_CF_NAME-example.invalid}" "$(cat "$rec")"
        else
          echo '{"success":true,"result":[]}'
        fi ;;
      DELETE)
        if [ "${FAKE_CF_DELETE_FAILS:-0}" != 1 ]; then : > "$rec"; fi
        echo '{"success":true,"result":{"id":"rec1"}}' ;;
      *)
        ip=$(printf '%s' "$data" | sed -n 's/.*"content": *"\\([^"]*\\)".*/\\1/p')
        # A zone that already had the name pinned somewhere else, or a plan
        # that forces the orange cloud on: the API says success and the record
        # is not what was asked for.
        if [ "${FAKE_CF_WRITES_WRONG:-0}" = 1 ]; then ip=203.0.113.99; fi
        printf '%s' "$ip" > "$rec"
        one='{"id":"rec1","name":"%s","content":"%s","proxied":%s,"ttl":60}'
        printf '{"success":true,"result":'"$one"'}\n' \
          "${FAKE_CF_NAME-example.invalid}" "$ip" "${FAKE_CF_PROXIED:-false}" ;;
    esac
    exit 0 ;;
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


_DIG_STUB = """#!/usr/bin/env bash
# Stands in for dig, and answers out of the same file the Cloudflare stub
# writes -- so a resolve that agrees with a record nobody wrote is not a thing
# this harness can produce. FAKE_DNS_LAGS is the resolver that has not caught
# up yet; FAKE_DNS_ANSWER is a name pointing somewhere else entirely, which is
# the state every trip before this one left behind.
if [ "${FAKE_DNS_LAGS:-0}" = 1 ]; then exit 0; fi
if [ -n "${FAKE_DNS_ANSWER-}" ]; then echo "$FAKE_DNS_ANSWER"; exit 0; fi
cat "$FAKE_STATE.dns" 2>/dev/null
echo
"""


_GNU_TAR_STUB = """#!/usr/bin/env bash
# Stands in for GNU tar, which is what Linux and CI have. It rejects the
# BSD-only flags the way GNU tar does -- by exiting, not by ignoring them.
#
# Without this, every offline run of trip.sh in this module could only pass on a
# Mac: `tar --no-fflags` is a hard error on GNU tar, so step 3 died and ten
# tests failed. That went unseen for 17 days because CI failed at the type check
# and never reached the tests. A harness that only runs on the author's laptop
# is a harness nothing else can check.
case "$1" in
  --version) echo "tar (GNU tar) 1.35"; exit 0 ;;
esac
args=()
for a in "$@"; do
  case "$a" in
    --no-fflags|--no-mac-metadata)
      echo "tar: unrecognized option '$a'" >&2
      echo "Try 'tar --help' or 'tar --usage' for more information." >&2
      exit 64 ;;
    *) args+=("$a") ;;
  esac
done
exec /usr/bin/tar "${args[@]}"
"""


# `caddy hash-password` stands in as python3: the real one needs the caddy
# image, and a stub written against a platform tool is how the `stat` stub
# passed 17/17 locally and read a tmpfs report as permission bits on CI.
# 60 characters with a `$2a$14$` prefix is the shape the real one prints, and
# `gate-slots.sh` is what decides whether that shape is acceptable.
_HASHER_STUB = """#!/usr/bin/env bash
exec python3 -c '
import hashlib, sys
pw = sys.stdin.read()
print("$2a$14$" + hashlib.sha256(pw.encode()).hexdigest()[:53])
'
"""

def _run_trip(
    tmp_path, env_text, args=(), vm_state="RUNNING", gnu_tar=False, **extra_env
):
    """Run the whole script offline. Returns (exit code, stdout+stderr)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = [
        ("ssh", _SSH_STUB),
        ("gcloud", _GCLOUD_STUB),
        ("curl", _CURL_STUB),
        ("dig", _DIG_STUB),
        ("caddy-hash", _HASHER_STUB),
    ]
    if gnu_tar:
        stubs.append(("tar", _GNU_TAR_STUB))
    for name, body in stubs:
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
    # No A record to begin with, which is the real starting point: every trip
    # reserves a new address, so whatever the name said last time is stale.
    pathlib.Path(str(state) + ".dns").write_text("")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_BOX": str(box.parent),
        "FAKE_STATE": str(state),
        "SET_SECRETS_HASHER": str(bin_dir / "caddy-hash"),
        # The DNS wait is a second of nothing in a test, not a minute.
        "VM_DNS_TRIES": "2",
        "VM_DNS_SLEEP": "0",
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


# The config-ssh alias shape: `<instance>.<zone>.<project>`, which is where
# deploy.sh reads the gcloud target from when the environment does not say.
_HOST = "agenticrag.us-central1-a.test-project"


def _run_deploy(
    tmp_path,
    args=("start", "--yes"),
    vm_state="TERMINATED",
    host=_HOST,
    resolvable=True,
    **extra_env,
):
    """Run `deploy/deploy.sh` offline, the way `_run_trip` runs the trip.

    `deploy.sh start` is the other command in this repository that turns the
    meter on, and until now nothing had ever run it except a person.
    """
    bin_dir = tmp_path / "bin"
    # parents=True so a test that runs this twice can hand each call its own
    # root under the one tmp_path, the way `_run_preflight` does.
    bin_dir.mkdir(parents=True)
    for name, body in (("ssh", _SSH_STUB), ("gcloud", _GCLOUD_STUB), ("curl", _CURL_STUB)):
        f = bin_dir / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)

    box = tmp_path / "box" / "agenticrag"
    box.mkdir(parents=True)

    state = tmp_path / "vm-state"
    state.write_text(vm_state + "\n")
    state.with_suffix(".ip").write_text("10.0.0.1\n")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        # Without this the ssh stub cannot start, and on bash <= 5.2 it failed
        # to start *silently* -- every command answered nothing and the two
        # tests that assert an unreachable box gets parked passed with ssh
        # explicitly alive.
        "FAKE_BOX": str(box.parent),
        "FAKE_STATE": str(state),
        "VM_INSTANCE": "agenticrag",
        "VM_ZONE": "us-central1-a",
        "VM_PROJECT": "test-project",
        # `resolvable=False` removes those three again, so a test can present
        # the case this script cannot answer at all: a plain ssh alias, or a
        # machine with no gcloud on it.
        # Two minutes of real waiting is not a unit test.
        "VM_SSH_TRIES": "1",
        "VM_SSH_SLEEP": "0",
        **extra_env,
    }
    if not resolvable:
        for name in ("VM_INSTANCE", "VM_ZONE", "VM_PROJECT"):
            env.pop(name, None)
    done = subprocess.run(
        ["bash", str(DEPLOY / "deploy.sh"), host, *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    gcloud_log = pathlib.Path(str(state) + ".gcloud")
    calls = gcloud_log.read_text() if gcloud_log.exists() else ""
    return done.returncode, done.stdout + done.stderr, calls


class TestBothDoorsToTheMeterAreChecked:
    """`trip.sh` grew a step 0 and an EXIT-trap park. `deploy.sh start` is the
    other command that starts the box, and it had neither: it waited thirty
    times for an ssh that could not arrive, printed ">> up at <ip>" either way,
    and left the box billing with a reminder to stop it by hand. That is the
    2026-09-28 Rs703 shape, in the script the fix for it never touched."""

    def test_the_door_is_checked_before_the_box_is_started(self, tmp_path):
        code, out, calls = _run_deploy(
            tmp_path, FAKE_MY_IP="198.51.100.9", FAKE_SSH_RANGES="203.0.113.7/32"
        )
        assert code != 0
        assert "port 22 is NOT open to this machine" in out
        assert "instances start" not in calls, "the meter was turned on anyway"
        assert "cost nothing" in out

    def test_an_open_door_lets_it_start(self, tmp_path):
        code, out, calls = _run_deploy(
            tmp_path, FAKE_MY_IP="203.0.113.7", FAKE_SSH_RANGES="203.0.113.0/24"
        )
        assert code == 0, out
        assert "instances start" in calls

    def test_an_unreachable_box_is_parked_not_left_billing(self, tmp_path):
        code, out, calls = _run_deploy(tmp_path, FAKE_SSH_DEAD="1")
        assert code != 0
        assert "ssh never came up" in out
        assert "instances stop" in calls, "the box was left running"
        assert "parked (TERMINATED)" in out

    def test_a_park_that_fails_names_the_rate_and_the_manual_command(self, tmp_path):
        code, out, _ = _run_deploy(tmp_path, FAKE_SSH_DEAD="1", FAKE_STOP_FAILS="1")
        assert code != 0
        assert "COULD NOT PARK IT" in out
        assert "per hour" in out
        assert "gcloud compute instances stop agenticrag" in out

    def test_a_reachable_box_is_reported_up_and_points_at_the_script_that_parks(
        self, tmp_path
    ):
        code, out, _ = _run_deploy(tmp_path)
        assert code == 0, out
        assert "up at 10.0.0.1" in out or "up at" in out
        assert "trip.sh parks on exit" in out

    def test_a_box_with_no_external_address_is_refused_before_starting(self, tmp_path):
        code, out, calls = _run_deploy(tmp_path, FAKE_NO_EXTERNAL_IP="1")
        assert code != 0
        assert "no external IP" in out
        assert "instances start" not in calls

    def test_an_already_running_box_is_left_alone(self, tmp_path):
        code, out, calls = _run_deploy(tmp_path, vm_state="RUNNING")
        assert code == 0
        assert "already running" in out
        assert "instances start" not in calls


class TestStopChecksThePark:
    """`deploy.sh stop` issued the stop and printed ">> stopped." without
    reading the state back -- item 5's defect in the other script -- and said
    nothing about the reserved address, which bills about twice the in-use rate
    while the box is off. The README's own table prices that difference."""

    def test_a_successful_stop_is_confirmed_from_the_box(self, tmp_path):
        code, out, calls = _run_deploy(tmp_path, args=("stop",), vm_state="RUNNING")
        assert code == 0, out
        assert "instances stop" in calls
        assert "stopped (TERMINATED)" in out

    def test_a_stop_that_does_not_take_fails_loudly(self, tmp_path):
        # gcloud returns 0 and the box stays up: the command succeeded and the
        # box did not. Printing ">> stopped" there is a claim about the command.
        code, out, _ = _run_deploy(
            tmp_path, args=("stop",), vm_state="RUNNING", FAKE_STOP_SILENT="1"
        )
        assert code != 0
        assert "NOT STOPPED" in out
        assert "per hour" in out
        assert "gcloud compute instances stop agenticrag" in out

    def test_a_reserved_address_is_named_with_its_rate(self, tmp_path):
        _, out, _ = _run_deploy(tmp_path, args=("stop",), vm_state="RUNNING")
        assert "still reserved" in out
        assert "agenticrag-ip" in out
        assert "addresses delete" in out

    def test_no_reserved_address_says_only_disks_bill(self, tmp_path):
        code, out, _ = _run_deploy(
            tmp_path, args=("stop",), vm_state="RUNNING", FAKE_NO_ADDRESS="1"
        )
        assert code == 0, out
        assert "no reserved addresses" in out

    def test_an_already_stopped_box_is_left_alone(self, tmp_path):
        code, out, calls = _run_deploy(tmp_path, args=("stop",), vm_state="TERMINATED")
        assert code == 0
        assert "already stopped" in out
        assert "instances stop" not in calls


class TestDownSaysWhatIsStillBilling:
    """`down` stops the containers; the VM goes on charging ~Rs5.6/hour.

    Until 2026-10-23 the arm was `exec ssh -t ... compose down`, and `exec`
    replaces this shell -- so the command whose name sounds the most like "I
    am finished paying for this" was *structurally* incapable of saying
    anything after the containers went away. Run against a RUNNING box it
    printed two "Removed" lines and exited 0. That is the 2026-09-28 Rs703
    failure with the believing one level up: the box was not forgotten, it was
    reported shut down by the script.
    """

    def test_a_running_vm_is_named_as_still_billing(self, tmp_path):
        code, out, _ = _run_deploy(tmp_path, args=("down",), vm_state="RUNNING")
        assert code == 0, out
        assert "RUNNING" in out
        assert "billing" in out
        assert f"deploy.sh {_HOST} stop" in out

    def test_down_does_not_park_the_box_by_itself(self, tmp_path):
        """Saying it and doing it are different commands, deliberately.

        `down` means *stop serving*; `stop` means *stop paying*. A `down` that
        silently parked the box would take a deploy's restart away from
        whoever typed it, so the epilogue reports and the operator decides.
        """
        _, out, calls = _run_deploy(tmp_path, args=("down",), vm_state="RUNNING")
        assert "instances stop" not in calls, out

    def test_a_parked_vm_is_not_warned_about(self, tmp_path):
        code, out, _ = _run_deploy(tmp_path, args=("down",), vm_state="TERMINATED")
        assert code == 0, out
        assert "VM meter off" in out
        assert "park it" not in out

    def test_the_compose_exit_status_survives_the_epilogue(self, tmp_path):
        """`exec` preserved it for free; doing this by hand must not lose it."""
        code, out, _ = _run_deploy(
            tmp_path, args=("down",), vm_state="RUNNING", FAKE_DOWN_RC="1"
        )
        assert code == 1, out
        assert "compose down exited 1" in out
        assert "RUNNING" in out, "the epilogue must still run on a failed down"

    def test_an_unreadable_state_is_loud_and_still_exits_zero(self, tmp_path):
        """No gcloud, or a plain ssh alias: the question cannot be answered.

        `vm_target` used to `exit 2` on that, which would turn a `down` that
        worked into a failure -- an epilogue must never overrule the command
        it is reporting on. It returns now, and the unanswered case says the
        expensive thing rather than nothing.
        """
        code, out, _ = _run_deploy(
            tmp_path, args=("down",), vm_state="RUNNING", host="plainbox", resolvable=False
        )
        assert code == 0, out
        assert "does NOT stop the VM" in out
        assert "assume it is billing" in out
        assert "deploy.sh plainbox status" in out

    def test_a_describe_that_answers_nothing_is_the_same_loud_case(self, tmp_path):
        """Item 20's worse half, reached from here: gcloud is present and the
        `describe` fails -- wrong project, expired credentials, an API error --
        so the state comes back empty. `status` exits 1 on that; the epilogue
        must not, because the `down` it is reporting on succeeded. Separately
        pinned from the unresolvable host: that one never reaches `read` at
        all, and `read` on an empty answer is where `set -euo pipefail` would
        abort the script before the warning was printed.
        """
        code, out, _ = _run_deploy(tmp_path, args=("down",), vm_state="")
        assert code == 0, out
        assert "assume it is billing" in out

    def test_the_lifecycle_commands_still_refuse_an_unresolvable_host(self, tmp_path):
        """The same `return` must not make `status` answer about nothing."""
        code, out, _ = _run_deploy(
            tmp_path, args=("status",), host="plainbox", resolvable=False
        )
        assert code == 2, out
        assert "cannot tell instance/zone/project" in out


class TestOneBillingTableAnswersBothCommands:
    """`status` already had an arm per instance state. `down`'s epilogue needs
    the same answer, and a second hand-written table of the same eight states
    is the `_FORWARDED_ENV` and preflight-key-list shape a third time: it
    agrees on the day it is written and falls behind silently after.
    """

    _STATES = (
        "RUNNING",
        "REPAIRING",
        "PROVISIONING",
        "STAGING",
        "STOPPING",
        "SUSPENDING",
        "SUSPENDED",
        "TERMINATED",
    )

    def test_there_is_one_definition(self):
        body = (DEPLOY / "deploy.sh").read_text()
        assert body.count("billing_line() {") == 1
        # Two callers, one function. Counting the calls rather than the
        # string "billing:" is the pin: a copy pasted back into either arm
        # would raise the count of `echo "   billing:` lines, which only the
        # definition is allowed to hold.
        assert body.count('billing_line "') == 3, "status, and both epilogue arms"
        assert body.count('echo "   billing:') == 6, "one per state group, in one place"

    @pytest.mark.parametrize("state", _STATES)
    def test_down_reports_what_status_reports(self, tmp_path, state):
        """The behavioural half. The count above fails if someone writes a
        second table; this fails if they write one that disagrees -- and a
        state removed from `down`'s reach fails neither count nor grep.
        """
        _, status_out, _ = _run_deploy(
            tmp_path / "s", args=("status",), vm_state=state
        )
        _, down_out, _ = _run_deploy(tmp_path / "d", args=("down",), vm_state=state)
        line = next(
            ln.strip() for ln in status_out.splitlines() if ln.strip().startswith("billing:")
        )
        assert line in down_out, f"{state}: status says {line!r}, down does not"


class TestTheDoorCheckHasOneCopy:
    def test_neither_script_defines_its_own(self):
        for name in ("trip.sh", "deploy.sh"):
            text = (DEPLOY / name).read_text()
            assert "ssh_door() {" not in text, f"{name} has its own copy of the check"
            assert "lib.sh" in text, f"{name} does not use the shared check"

    def test_the_shared_copy_is_the_one_with_the_containment_logic(self):
        lib = (DEPLOY / "lib.sh").read_text()
        assert "ssh_door() {" in lib
        assert "ipaddress.ip_network" in lib, "string equality would call an open door shut"


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


class TestTheTripOwnsThePublicName:
    """Step 1b, and the half of the park that goes with it.

    Every trip reserves a *new* external address, and steps 6 and 7 are the
    only checks that go through PUBLIC_URL. So from the day step 6 was written
    until 2026-10-28 it could only pass if a human hand-edited Cloudflare
    inside the twenty minutes the box was up -- and nothing in the script said
    so. Step 6 had never once run against a live box. A check nobody can run
    is a check nobody has read.

    The other half matters more than the convenience: the address goes back to
    GCP's pool when the trip parks. A name left pointing at it is a subdomain
    takeover waiting for whoever reserves that address next.
    """

    CF = {"CF_API_TOKEN": "sentinel0cf0token0do0not0print", "CF_ZONE_ID": "zone1"}

    def test_without_a_token_the_trip_says_the_name_is_not_its_doing(self, tmp_path):
        # And does not fail for it: a build-and-park trip never touches the
        # name. Step 6 is what counts a name that does not answer.
        code, out = _run_trip(tmp_path, GOOD_ENV)
        assert "CF_API_TOKEN/CF_ZONE_ID unset" in out
        assert code == 0

    def test_a_name_pointing_somewhere_else_is_named_with_both_addresses(self, tmp_path):
        # The state every trip before this one left behind, and the reason
        # step 6 reported nothing for three weeks.
        _, out = _run_trip(tmp_path, GOOD_ENV, FAKE_DNS_ANSWER="203.0.113.50")
        assert "it resolves to 203.0.113.50; this trip is at 10.0.0.1" in out
        assert "steps 6 and 7 cannot pass" in out

    def test_with_a_token_the_name_is_pointed_at_this_trips_address(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, **self.CF)
        assert "example.invalid -> 10.0.0.1 (proxied=False" in out
        assert "resolves here" in out
        assert code == 0

    def test_the_name_is_released_before_the_address_it_points_at(self, tmp_path):
        # Order is the whole point. An address handed back to GCP's pool while
        # the name still points at it is somebody else's subdomain.
        _, out = _run_trip(tmp_path, GOOD_ENV, **self.CF)
        assert "example.invalid has no A record now" in out
        assert out.index("releasing example.invalid") < out.index("parking agenticrag")

    def test_the_name_is_released_even_when_the_trip_dies_early(self, tmp_path):
        # Same reason parking is a trap and not a last line: the run that most
        # needs the cleanup is the one that stopped half way.
        # GOOD_ENV with the proxy secret blanked: step 1b has already pointed
        # the name by the time step 2 refuses to build.
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV.replace(SENTINELS["SEXTANT_PROXY_SECRET"], ""),
            **self.CF,
        )
        assert code != 0, "the empty proxy secret still stops the trip"
        assert "every request would 403" in out
        assert "example.invalid has no A record now" in out

    def test_a_delete_that_did_not_take_takes_the_zero_away(self, tmp_path):
        # Read back, not assumed. The API returning is not the record being
        # gone, and only the second one makes the address safe to release.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_CF_DELETE_FAILS="1", **self.CF)
        assert "STILL points at an address this park is releasing" in out
        assert code != 0

    def test_a_token_that_cannot_write_the_zone_fails_the_trip(self, tmp_path):
        # Cloudflare answers 200 with "success": false, which is the same
        # shape as /upload answering 200 for a file it could not read.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_CF_REFUSES="1", **self.CF)
        assert "refused: Actor is not authorized" in out
        assert "the name does not point at this box" in out
        assert code != 0

    def test_a_record_written_to_the_wrong_address_fails_the_trip(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_CF_WRITES_WRONG="1", **self.CF)
        assert "it points at 203.0.113.99, not 10.0.0.1" in out
        assert code != 0

    def test_the_orange_cloud_is_a_failure_and_says_which_check_it_breaks(self, tmp_path):
        # Proxied, Cloudflare terminates TLS and rewrites headers, so step 6's
        # forged X-Sextant-Proxy-Auth never reaches Caddy to be overwritten --
        # and the one check that proves the proxy vouches for names stops
        # meaning anything while still printing a number.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_CF_PROXIED="true", **self.CF)
        assert "step 6 cannot prove the gate through the orange cloud" in out
        assert code != 0

    def test_a_resolver_that_lags_is_reported_and_the_name_still_comes_down(self, tmp_path):
        # Set upstream is not the same as visible here, and the two are worth
        # distinguishing: one is a thing to fix, the other a thing to wait out.
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_DNS_LAGS="1", **self.CF)
        assert "Cloudflare has it, but this machine still resolves nothing" in out
        assert "example.invalid has no A record now" in out
        assert code == 0, "a slow resolver is step 6's failure to count, not step 1b's"

    def test_the_verification_pass_points_the_name_too(self, tmp_path):
        # --no-deploy is steps 5 to 7 and nothing else, so it is the run that
        # needs the name most, not least.
        _, out = _run_trip(tmp_path, GOOD_ENV, args=["--no-deploy"], **self.CF)
        assert "example.invalid -> 10.0.0.1" in out
        assert "shipping the working tree" not in out

    def test_the_token_is_never_printed(self, tmp_path):
        # It is on a curl config file on a pipe, never in argv, so it is not
        # in `ps` on this machine either while the trip runs.
        _, out = _run_trip(tmp_path, GOOD_ENV, FAKE_CF_REFUSES="1", **self.CF)
        assert self.CF["CF_API_TOKEN"] not in out
        assert "--data" not in out

    def test_the_trip_reads_the_name_off_the_box_and_not_out_of_this_repo(self):
        # The same rule step 6 follows for PUBLIC_URL: this repo is public and
        # the name is not something to publish in it.
        text = TRIP.read_text()
        assert "hulage" not in text.lower()
        assert "sed -n 's/^PUBLIC_URL=//p' .env" in text


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


class TestStep5JudgesWhatItPrints:
    """Step 5 printed six results and judged one.

    A line on a terminal is not a check. The container table showed whatever
    compose said and nothing read it, so a box whose Caddy had died reported a
    clean step 5 -- and step 6, which exists for exactly that failure, only
    runs when the operator exported credentials. `model=False`, an empty store,
    an uncapped box and leftover `AGENTICRAG_*` names were all printed and
    stepped over the same way.
    """

    HEALTHY = (
        '{"status":"healthy","mcp_connected":true,'
        '"model_configured":true,"budget":{"enabled":true,"budget_usd":0.6}}'
    )

    def test_a_dead_caddy_fails_the_trip(self, tmp_path):
        """The one that matters most: a stopped Caddy means the gate is not in
        the path, and every other check in step 5 goes through `docker exec`
        and so cannot see that."""
        code, out = _run_trip(
            tmp_path, GOOD_ENV, FAKE_CADDY_STATUS="Exited (1) 2 minutes ago"
        )
        assert "caddy is not Up" in out
        assert "check(s) failed" in out
        assert code != 0

    def test_a_missing_caddy_fails_the_trip(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_CADDY_STATUS="gone")
        assert "caddy is not in the table at all" in out
        assert code != 0

    def test_a_dead_api_fails_the_trip(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_API_STATUS="Restarting")
        assert "api is not Up" in out
        assert code != 0

    def test_both_containers_up_is_a_pass(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV)
        assert "agenticrag-api-1" in out
        assert "agenticrag-caddy-1" in out
        assert "is not Up" not in out
        assert code == 0

    def test_a_box_with_no_model_key_fails_the_trip(self, tmp_path):
        """`model=True` is the key rotation's whole success criterion, and it
        was printed and never read: a box with a bad key answered model=False
        and the trip reported it shipped."""
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            FAKE_HEALTH=self.HEALTHY.replace('"model_configured":true', '"model_configured":false'),
        )
        assert "no model key resolved" in out
        assert code != 0

    def test_an_uncapped_box_fails_the_trip(self, tmp_path):
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            FAKE_HEALTH=self.HEALTHY.replace('"budget_usd":0.6', '"budget_usd":0'),
        )
        assert "the box is uncapped" in out
        assert code != 0

    def test_a_disconnected_tool_server_fails_the_trip(self, tmp_path):
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            FAKE_HEALTH=self.HEALTHY.replace('"mcp_connected":true', '"mcp_connected":false'),
        )
        assert "the tool server is not connected" in out
        assert code != 0

    def test_an_unhealthy_status_fails_the_trip(self, tmp_path):
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            FAKE_HEALTH=self.HEALTHY.replace('"status":"healthy"', '"status":"degraded"'),
        )
        assert "status is degraded" in out
        assert code != 0

    def test_a_box_that_cannot_write_its_spend_ledger_fails_the_trip(self, tmp_path):
        """`durable: false` means the cap restarts with the container, so it is
        a limit per process lifetime and not the daily cap the .env promises."""
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            FAKE_HEALTH=self.HEALTHY.replace(
                '"budget_usd":0.6', '"budget_usd":0.6,"enabled":true,"durable":false'
            ),
        )
        assert "the spend ledger is not writable" in out
        assert code != 0

    def test_a_durable_ledger_passes_and_is_printed(self, tmp_path):
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            FAKE_HEALTH=self.HEALTHY.replace(
                '"budget_usd":0.6', '"budget_usd":0.6,"enabled":true,"durable":true'
            ),
        )
        assert "durable=True" in out
        assert "the spend ledger is not writable" not in out
        assert code == 0

    def test_a_box_predating_the_ledger_is_noted_not_failed(self, tmp_path):
        # The box is on 0.8.1 until the trip that carries this runs, so an
        # absent key is "older box", not "broken box".
        code, out = _run_trip(tmp_path, GOOD_ENV)
        assert "predates the spend ledger" in out
        assert code == 0

    def test_several_wrong_things_are_all_named(self, tmp_path):
        _, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            FAKE_HEALTH='{"status":"degraded","mcp_connected":false,'
            '"model_configured":false,"budget":{"budget_usd":0}}',
        )
        assert "status is degraded" in out
        assert "the tool server is not connected" in out
        assert "no model key resolved" in out
        assert "the box is uncapped" in out

    def test_a_box_that_does_not_answer_json_fails_the_trip(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, FAKE_HEALTH="<html>502</html>")
        assert "could not read /health" in out
        assert code != 0

    def test_an_empty_store_fails_the_trip(self, tmp_path):
        """A floor, not a number: what the corpus should hold is not this
        script's business, but an empty store after a deploy is."""
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            FAKE_STATS='{"collection_size":0,"documents":0,"summaries":0,'
            '"persist_dir":"/data/chroma"}',
        )
        assert "the store is empty" in out
        assert code != 0

    def test_a_leftover_legacy_env_name_fails_the_trip(self, tmp_path):
        """Not read since 0.8.1, so the container runs with its budget cap and
        CORS allowlist at defaults. Printing the names and carrying on is how
        an uncapped box ships."""
        code, out = _run_trip(
            tmp_path,
            GOOD_ENV,
            FAKE_LOG_LINE="AGENTICRAG_DAILY_BUDGET_USD is set; rename it to SEXTANT_",
        )
        assert "AGENTICRAG_DAILY_BUDGET_USD" in out
        assert "running with defaults for those" in out
        assert code != 0

    def test_a_clean_log_is_a_pass(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV)
        assert "clean" in out
        assert code == 0


class TestCiRunsWhatTheGateRuns:
    """The gate in CLAUDE.md and the workflow in CI must not drift apart.

    They had. The gate has four commands; CI ran three. `npm run build` runs
    `tsc -b` first, so a type error in the frontend failed only for whoever
    typed the gate by hand and passed every push.

    The deeper reason to pin it: CI's own green tick is a claim about what was
    checked, and nobody reads the step list to find out which claim it is.
    """

    ROOT = pathlib.Path(__file__).resolve().parent.parent

    def _gate_programs(self):
        """The programs the documented gate invokes, by name."""
        text = (self.ROOT / "CLAUDE.md").read_text()
        marker = "## Gate before a commit"
        assert marker in text, "CLAUDE.md no longer documents a gate"
        block = text.split(marker, 1)[1].split("```")[1]
        block = block.split("\n", 1)[1] if block.startswith("bash") else block
        programs = []
        for segment in re.split(r"&&|\|\||;|\n", block):
            segment = segment.strip().lstrip("(").strip()
            if not segment:
                continue
            first = segment.split()[0].rstrip(")")
            first = first.rsplit("/", 1)[-1]  # ./.venv/bin/pytest -> pytest
            if first in {"cd", "export", "then", "fi", "do", "done"}:
                continue
            if first not in programs:
                programs.append(first)
        return programs

    def _workflow(self):
        found = sorted((self.ROOT / ".github" / "workflows").glob("*.yml"))
        assert found, "no CI workflow at all"
        return "\n".join(p.read_text() for p in found)

    def test_the_gate_is_still_four_commands(self):
        """If this changes, the list below changed with it and the next test is
        checking a different thing than it was written for."""
        assert self._gate_programs() == ["pytest", "mypy", "ruff", "npm"]

    def test_every_program_in_the_gate_is_run_in_ci(self):
        workflow = self._workflow()
        missing = [p for p in self._gate_programs() if p not in workflow]
        assert not missing, (
            f"the gate runs these and CI does not: {', '.join(missing)} -- a "
            "green tick in CI then means less than it looks like"
        )

    def test_ci_builds_the_frontend_not_just_installs_it(self):
        """`npm ci` alone would satisfy the test above while checking nothing:
        the build is what runs `tsc -b`."""
        assert "npm run build" in self._workflow()

    def test_ci_runs_on_a_push_to_main(self):
        """A workflow nothing triggers is not a check. 30 consecutive red runs
        went unseen, but at least they ran."""
        workflow = self._workflow()
        assert "pull_request" in workflow
        assert "branches: [main]" in workflow


class TestTheTripRunsOnALinuxTar:
    """The offline run of `trip.sh` could only ever pass on a Mac.

    Step 3 shipped the tree with `tar --no-xattrs --no-fflags
    --no-mac-metadata`. The last two are BSD-only, and GNU tar -- Linux, and CI
    -- *exits* on an unknown flag rather than ignoring it. So step 3 died on
    Linux and took ten tests in this module with it.

    Nobody found out for 17 days, because CI failed at the type check and never
    reached the tests. A harness that only runs on the author's machine is a
    harness nothing else can check, which is the whole value of having it.
    """

    def test_the_trip_completes_with_a_gnu_tar(self, tmp_path):
        code, out = _run_trip(tmp_path, GOOD_ENV, gnu_tar=True)
        assert "unrecognized option" not in out
        assert "done - the trap parks the box next" in out
        assert code == 0

    def test_the_tree_is_still_shipped(self, tmp_path):
        """Not just "did not crash": the tar has to have produced something the
        far side could unpack.

        Asserting on the "synced" line would prove nothing -- the stub prints it
        for whatever arrives, including an empty stream from a tar that just
        died. The byte count is the falsifiable part.
        """
        _, out = _run_trip(tmp_path, GOOD_ENV, gnu_tar=True)
        assert "synced 1 files" in out
        received = pathlib.Path(str(tmp_path / "vm-state") + ".tarbytes")
        assert received.exists(), "the far side was never piped anything"
        assert int(received.read_text().strip()) > 1000, (
            "the tarball was empty or near-empty, so nothing was shipped"
        )

    def test_macos_metadata_is_still_excluded_on_a_bsd_tar(self, tmp_path):
        """The BSD-only flags are not being dropped for everyone -- on a Mac
        they are still passed, or .DS_Store and resource forks ride along to the
        box. This machine has BSD tar, so the default run exercises that."""
        code, out = _run_trip(tmp_path, GOOD_ENV)
        assert "unrecognized option" not in out
        assert code == 0

    def test_the_stub_really_rejects_the_bsd_flags(self, tmp_path):
        """A stub that cannot say no makes the test above a comment. This is the
        fourth time that has bitten in this milestone, so it gets its own pin."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "tar"
        fake.write_text(_GNU_TAR_STUB)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        refused = subprocess.run(
            [str(fake), "-czf", "-", "--no-fflags", "-C", str(tmp_path), "."],
            capture_output=True,
            text=True,
        )
        assert refused.returncode != 0
        assert "unrecognized option '--no-fflags'" in refused.stderr
        # And it answers --version the way the detection in trip.sh reads it.
        version = subprocess.run(
            [str(fake), "--version"], capture_output=True, text=True
        )
        assert "GNU tar" in version.stdout


class TestTheGatesEnvironmentIsChosenHere:
    """CI's environment was chosen by GitHub, and GitHub said so on every run.

    Items 12 and 13 were both the same failure: something about the
    *environment* decided whether the check ran. An optional dependency decided
    whether the code type-checked (30 red runs, 17 days, `pytest` and
    `sextant-eval --check` never executing once); and the offline trip harness
    used BSD-only tar flags, so it could only ever pass on the machine that
    wrote it.

    This is the third instance, and the only one that was announced in advance:

    * Five actions targeted Node 20, which is deprecated, and the runner has
      been **force-running them on Node 24** -- printed as an annotation on
      every run since.
    * `runs-on: ubuntu-latest` migrates from Ubuntu 24.04 to 26.04 **gradually
      between 2026-10-19 and 2026-11-19** (actions/runner-images#14748). A
      gradual migration is worse than a dated one: for a month the same commit
      can pass or fail depending on which image it drew, and a gate that is
      sometimes red teaches people that red means nothing. Thirty unread red
      runs is what that costs here.

    Both warnings were produced by CI and read by nobody -- step 5's defect
    (item 11) in the repository's own check. The fix is not to read them harder:
    the runner is pinned to an image the gate has actually passed on, the
    actions are pinned to majors that were reviewed, and Dependabot turns the
    next deprecation into a pull request instead of a line in a log.
    """

    ROOT = pathlib.Path(__file__).resolve().parent.parent

    # Bumped deliberately, never by a float. Every one of these was checked
    # against its release notes for a change that touches this workflow:
    # setup-node v6 limited automatic caching to npm (we ask for npm),
    # setup-python v7 removed the `pip-install` input (we never set it),
    # checkout v7 blocks fork checkouts for `pull_request_target` and
    # `workflow_run` (we trigger on neither), and upload-artifact v7 added an
    # opt-in `archive: false` that changes nothing by default. All five run on
    # node24 and need runner >= 2.327.1; run 37779188732 was on 2.337.0.
    EXPECTED_ACTIONS = {
        "actions/checkout": "v7",
        "actions/setup-python": "v7",
        "actions/setup-node": "v7",
        "actions/cache": "v6",
        "actions/upload-artifact": "v7",
    }

    def _workflows(self):
        found = sorted((self.ROOT / ".github" / "workflows").glob("*.yml"))
        assert found, "no CI workflow at all"
        return found

    def _workflow_text(self):
        return "\n".join(p.read_text() for p in self._workflows())

    def test_the_runner_image_is_pinned_to_a_version(self):
        """A floating label means the gate cannot say what it passed on.

        `ubuntu-latest` is not one environment, it is whichever one GitHub is
        rolling out this week. During a migration window it is both.
        """
        floating = re.findall(r"runs-on:\s*(\S*-latest\S*)", self._workflow_text())
        assert not floating, (
            f"the gate runs on a floating label: {', '.join(floating)} -- "
            "pin the image so a rollout is a decision, not an event"
        )

    def test_the_runner_image_is_one_the_gate_has_passed_on(self):
        """Pinning to an untested image would only move the surprise.

        `ubuntu-26.04` was run start to finish on this workflow before it was
        pinned, on branch `pin-the-gates-environment`, so the 2026-10-19
        rollout is a no-op here rather than a month of nondeterminism.
        """
        images = re.findall(r"runs-on:\s*(\S+)", self._workflow_text())
        assert images, "nothing says what the gate runs on"
        assert set(images) == {"ubuntu-26.04"}, (
            f"the gate runs on {sorted(set(images))}; if that is a deliberate "
            "change, run the workflow on it first and update this pin"
        )

    def test_no_action_floats(self):
        """`@main` is someone else's main branch deciding whether this repo's
        gate passes."""
        for action, ref in re.findall(r"uses:\s*([\w.-]+/[\w.-]+)@(\S+)", self._workflow_text()):
            assert re.fullmatch(r"v\d+(\.\d+)*", ref), (
                f"{action} is pinned to '{ref}', which is not a version"
            )

    def test_every_action_is_on_a_major_that_was_reviewed(self):
        """Not 'is it recent' -- 'was this one looked at'. Dependabot will
        propose the next bump; this makes merging it a decision someone records
        rather than a diff that rides along."""
        found = {
            action: ref.split(".")[0]
            for action, ref in re.findall(
                r"uses:\s*([\w.-]+/[\w.-]+)@(\S+)", self._workflow_text()
            )
        }
        assert found == self.EXPECTED_ACTIONS, (
            f"the workflow uses {found}, this test expects "
            f"{self.EXPECTED_ACTIONS} -- read the release notes, then update "
            "both"
        )

    def test_something_watches_the_actions_for_the_next_deprecation(self):
        """The Node 20 warning was on every run for months. The answer to a
        result nobody reads is not a louder result."""
        config = self.ROOT / ".github" / "dependabot.yml"
        assert config.exists(), (
            "nothing watches the actions: the last deprecation was announced "
            "on every run and read by no one"
        )
        text = config.read_text()
        assert "github-actions" in text, (
            "dependabot.yml does not watch github-actions, which is the "
            "ecosystem that just deprecated five of ours"
        )


class TestCiRunsTheGateWithTheSameArguments:
    """`TestCiRunsWhatTheGateRuns` pins the program names. That is not the claim.

    It asks whether the string `mypy` appears in the workflow, so a CI step
    narrowed from `mypy sextant tests` to `mypy sextant` keeps
    the tick and type-checks **one tree of four** -- verified, that pin passes
    it. Item 14 was this exact shape one level out: `sextant-eval --check`
    guarded `--store` and `--golden` but not `--modes`, so grading one
    retrieval mode of four printed "no regressions".

    Same program, different claim. The arguments are the claim.
    """

    ROOT = pathlib.Path(__file__).resolve().parent.parent

    # What the gate runs, as the commands a reader of CLAUDE.md would type,
    # with the virtualenv prefix removed because CI has the tools on PATH.
    EXPECTED_COMMANDS = [
        "pytest tests/ -q",
        "mypy sextant tests",
        "ruff check .",
        "npm run build",
        "npm test",
    ]

    def _gate_commands(self):
        text = (self.ROOT / "CLAUDE.md").read_text()
        marker = "## Gate before a commit"
        assert marker in text, "CLAUDE.md no longer documents a gate"
        block = text.split(marker, 1)[1].split("```")[1]
        block = block.split("\n", 1)[1] if block.startswith("bash") else block
        commands = []
        for segment in re.split(r"&&|\|\||;|\n", block):
            segment = segment.strip().lstrip("(").rstrip(")").strip()
            if not segment:
                continue
            words = segment.split()
            if words[0] in {"cd", "export", "then", "fi", "do", "done"}:
                continue
            words[0] = words[0].rsplit("/", 1)[-1]  # ./.venv/bin/pytest -> pytest
            commands.append(" ".join(words))
        return commands

    def _workflow(self):
        found = sorted((self.ROOT / ".github" / "workflows").glob("*.yml"))
        assert found, "no CI workflow at all"
        return "\n".join(p.read_text() for p in found)

    def test_the_gate_is_still_the_commands_this_pin_was_written_for(self):
        """If the gate changes, the list above has to change with it, or the
        test below is checking something it was not written for."""
        assert self._gate_commands() == self.EXPECTED_COMMANDS

    def test_ci_runs_each_gate_command_with_its_arguments(self):
        """The arguments are what the tick is a claim about.

        CI may add to a command -- it runs `npm ci && npm run build`, and the
        `cd frontend` is a `working-directory:` -- but it may not quietly run
        less of one.
        """
        workflow = self._workflow()
        narrowed = [c for c in self._gate_commands() if c not in workflow]
        assert not narrowed, (
            "CI runs these with different arguments than the gate: "
            f"{'; '.join(narrowed)} -- the program name matching is not the "
            "claim, the arguments are"
        )


class TestTheSshStubCannotFailQuietly:
    """The probe on `ubuntu-26.04` found this, 11 days before the rollout.

    `_run_deploy` never set `FAKE_BOX`, so the ssh stub's first line was
    `cd ""`. **bash 5.2 and earlier accept that as a no-op; bash 5.3 rejects it
    as a null directory** -- 24.04 ships 5.2.21, 26.04 ships 5.3.9. So on this
    laptop and on 24.04 the stub answered every command, and on 26.04 it exited
    before reading its first argument.

    Two of item 16's tests went red there, which is how it was found. The worse
    half is the four that stayed green: with the stub dead, the two that assert
    *an unreachable box is parked rather than left billing* -- the Rs703
    protection, the most expensive guarantee in this repository -- **passed with
    `FAKE_SSH_DEAD` forced to 0, meaning ssh explicitly alive.** They were
    insensitive to the one variable they are built on.

    Third instance of the item 13 shape: the harness depended on a platform's
    tolerance (BSD vs GNU tar, then bash 5.2 vs 5.3). The lesson is narrower
    than "test on Linux": **a stub that cannot start must say so.** Answering
    nothing is indistinguishable from answering correctly for any test whose
    expectation is a failure.
    """

    def test_the_stub_refuses_to_run_without_a_box(self, tmp_path):
        fake = tmp_path / "ssh"
        fake.write_text(_SSH_STUB)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        env = {k: v for k, v in os.environ.items() if k != "FAKE_BOX"}
        refused = subprocess.run(
            [str(fake), "box", "true"], capture_output=True, text=True, env=env
        )
        assert refused.returncode != 0, (
            "the stub started with no box; on bash <= 5.2 it then answers "
            "nothing to everything, and a test expecting a failure cannot tell "
            "that apart from a pass"
        )
        assert "no box" in refused.stderr, (
            f"it failed without saying why: {refused.stderr!r}"
        )

    def test_the_stub_still_answers_when_it_has_one(self, tmp_path):
        """A refusal that fires always would make every deploy test a comment."""
        box = tmp_path / "box" / "agenticrag"
        box.mkdir(parents=True)
        fake = tmp_path / "ssh"
        fake.write_text(_SSH_STUB)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        ok = subprocess.run(
            [str(fake), "box", "true"],
            capture_output=True,
            text=True,
            env={**os.environ, "FAKE_BOX": str(box.parent)},
        )
        assert ok.returncode == 0, ok.stderr

    def test_an_unreachable_box_is_still_judged_by_the_variable_it_names(
        self, tmp_path
    ):
        """The pin for the four that stayed green on 26.04.

        `FAKE_SSH_DEAD` has to decide the outcome. If the stub is broken in any
        way that makes ssh fail regardless, this passes while the test above it
        reports a park that was never tested.
        """
        dead, live = tmp_path / "dead", tmp_path / "live"
        dead.mkdir()
        live.mkdir()
        dead_code, dead_out, _ = _run_deploy(dead, FAKE_SSH_DEAD="1")
        live_code, live_out, _ = _run_deploy(live, FAKE_SSH_DEAD="0")
        assert dead_code != 0 and "ssh never came up" in dead_out
        assert live_code == 0 and "ssh never came up" not in live_out, (
            "ssh fails whatever FAKE_SSH_DEAD says, so every assertion about an "
            "unreachable box is vacuous"
        )


def _calls_without_headers(source: str) -> list[str]:
    """Exported functions that reach the server without routing headers
    through the one helper that adds the browser's name.

    Split per exported function rather than per `fetch(`: each call site in
    `api.ts` lives in one exported function, and its options object sits
    between the `fetch(` and the end of that function. Counting both inside
    the block catches the two ways this comes apart -- a function added later
    that builds its own headers object, and a second `fetch` added to a
    function that already had one -- without needing to parse TypeScript.
    """
    offenders = []
    for block in source.split("\nexport "):
        calls = block.count("fetch(")
        if not calls:
            continue
        protected = block.count("sent(")
        if protected != calls:
            name = block.split("(")[0].split()[-1] if "(" in block else "?"
            offenders.append(f"{name}: {calls} fetch, {protected} through sent()")
    return offenders


class TestTheBrowserSendsWhatTheAppReads:
    """The third header, whose other end is TypeScript.

    `TestTheProxySetsWhatTheAppReads` pins two of the three names
    `identity.py` declares against the file that writes them, and this one
    was left out -- for exactly the reason that class's docstring gives about
    the other two. Its other end is not Python, so no test in the suite reads
    it. Before this class, `X-Sextant-Client` appeared in two places in the
    whole repository, `sextant/mcp_server/identity.py` and
    `frontend/src/lib/api.ts`, and no test named it at all.

    Renaming `CLIENT_HEADER` is green in every check there is: the Python
    tests take the constant, `tsc -b` and `vite build` do not know the server,
    and the browser keeps sending a header nobody reads. Every browser then
    falls back to `shared`, which is not a feature going missing but the
    return of the defect 0.8.2 shipped against: two people behind one
    password storing `notes.pdf` over each other, and an upload that anybody
    may overwrite because an unnamespaced id is writable by `shared`.

    The second half is the same failure one step earlier. `sent()` carries a
    comment saying it is used everywhere "so a call site added later does not
    have to remember" -- a convention held up by prose, which is what every
    item of this milestone has been about.
    """

    def test_the_client_module_is_where_this_expects_it(self):
        # Everything below reads one file. If it moves, these tests must fail
        # rather than pass over an empty string.
        assert API_CLIENT.is_file(), f"{API_CLIENT} is the file this pins"

    def test_the_browser_sends_the_name_python_reads(self, api_client):
        assert f"'{CLIENT_HEADER}'" in api_client, (
            f"the frontend does not send {CLIENT_HEADER}, so every request is "
            "answered as the shared owner"
        )

    def test_the_name_is_written_once_so_a_rename_has_one_site(self, api_client):
        keys = [
            line
            for line in api_client.splitlines()
            if f"'{CLIENT_HEADER}':" in line
        ]
        assert len(keys) == 1, (
            "the header name belongs in one helper; copies are how one of them "
            f"gets renamed and the other does not: {keys}"
        )

    def test_the_server_is_reached_through_the_one_module(self):
        others = sorted(
            str(path.relative_to(FRONTEND))
            for path in FRONTEND.rglob("*.ts*")
            if path != API_CLIENT and "fetch(" in path.read_text()
        )
        assert not others, (
            "a request built outside api.ts does not go through sent() and is "
            f"answered as the shared owner: {others}"
        )

    def test_every_call_to_the_server_carries_the_browser_name(self, api_client):
        assert not _calls_without_headers(api_client), _calls_without_headers(
            api_client
        )

    def test_the_scan_is_looking_at_the_call_sites(self, api_client):
        """Anti-vacuity: `_calls_without_headers` returns nothing for a file
        with no `fetch` in it at all, so the count has to be checked too."""
        calls = api_client.count("fetch(")
        assert calls >= 5, f"only {calls} call sites found -- has api.ts moved?"
        assert calls == api_client.count("${SERVER_URL}"), (
            "every fetch addresses SERVER_URL and every SERVER_URL is fetched; "
            "if that stops being true this scan is reading the wrong thing"
        )

    def test_the_scan_would_notice_a_call_site_that_forgot(self):
        forgot = (
            "export async function fetchSpend(): Promise<unknown> {\n"
            "  const response = await fetch(`${SERVER_URL}/spend`, {\n"
            "    headers: { 'Content-Type': 'application/json' },\n"
            "  })\n"
            "  return response.json()\n"
            "}\n"
        )
        kept = (
            "export async function fetchSpend(): Promise<unknown> {\n"
            "  const response = await fetch(`${SERVER_URL}/spend`, {\n"
            "    headers: sent({ 'Content-Type': 'application/json' }),\n"
            "  })\n"
            "  return response.json()\n"
            "}\n"
        )
        assert _calls_without_headers("\n" + forgot) == [
            "fetchSpend: 1 fetch, 0 through sent()"
        ]
        assert _calls_without_headers("\n" + kept) == []
        # A second call added to a function that already had one.
        twice = kept.replace(
            "  return response.json()",
            "  await fetch(`${SERVER_URL}/spend`)\n  return response.json()",
        )
        assert _calls_without_headers("\n" + twice) == [
            "fetchSpend: 2 fetch, 1 through sent()"
        ]


class TestTheFrontendLinterRuns:
    """A linter configured, committed, and never once invoked.

    `frontend/package.json` has defined `npm run lint` since the UI port and
    `.oxlintrc.json` is committed with a rules block someone chose. Neither the
    gate nor the workflow ever called it, so the lint result for this tree was
    not green -- it was **unknown**. Nobody could have said whether it was zero
    problems or a hundred.

    Probed on CI rather than guessed (`workflow_dispatch` on
    `the-client-half-of-the-boundary`): **11 warnings, 0 errors, 47 files, 116
    rules.** None of the eleven was a defect -- six were shadcn's own files
    exporting a `cva` variants object beside the component, two were
    mount-time reads of `window` and of the server, and three were a
    deliberately by-value dependency array. The eleventh, `SERIES` exported
    from `sweep-chart.tsx` and imported by `lab.tsx`, was the rule being right,
    and it moved to `series.ts`.

    So the finding is not a pile of unfixed problems. It is that **the step
    exits 0 on eleven warnings**: adding it as it stood would have bought a
    green tick that cannot go red, which is this milestone's whole subject. The
    strictness lives in the committed config (`denyWarnings`) so that running
    the linter by hand makes the same claim CI does, each of the eleven is a
    recorded decision rather than a silence, and
    `reportUnusedDisableDirectives` means a suppression that stops being needed
    is itself reported.

    It is CI-only, and that is not a preference. npm 10.5.0 on this machine
    does not install oxlint's platform binding even though the lockfile carries
    it with matching `os`/`cpu`; oxlint's own error names npm/cli#4828. `npm
    ci`, `npm install --save-optional` and a clean reinstall all leave
    `node_modules/@oxlint` absent, so the laptop cannot run it and the gate
    must not claim to. CI's newer npm installs it fine.
    """

    ROOT = pathlib.Path(__file__).resolve().parent.parent

    def _package(self) -> dict:
        import json

        return json.loads((self.ROOT / "frontend" / "package.json").read_text())

    def _config(self) -> dict:
        import json

        return json.loads((self.ROOT / "frontend" / ".oxlintrc.json").read_text())

    def _workflow(self) -> str:
        found = sorted((self.ROOT / ".github" / "workflows").glob("*.yml"))
        assert found, "no CI workflow at all"
        return "\n".join(path.read_text() for path in found)

    def _suppressions(self) -> list[str]:
        out = []
        for path in (self.ROOT / "frontend" / "src").rglob("*.ts*"):
            for line_no, line in enumerate(path.read_text().splitlines(), 1):
                if "oxlint-disable" in line or "eslint-disable" in line:
                    out.append(f"{path.relative_to(self.ROOT)}:{line_no}: {line.strip()}")
        return out

    def test_the_script_exists_to_be_run(self):
        assert "lint" in self._package()["scripts"]

    def test_ci_runs_it(self):
        assert "npm run lint" in self._workflow(), (
            "the linter is configured and invoked by nothing, which is how its "
            "result stayed unknown for three versions"
        )

    def test_a_warning_is_allowed_to_fail_the_step(self):
        """Without this the step is a tick that cannot go red: oxlint exits 0
        on warnings, and the probe found eleven of them."""
        assert self._config()["options"]["denyWarnings"] is True

    def test_a_suppression_that_stops_being_needed_is_reported(self):
        """Otherwise the decisions below rot into comments -- a result produced
        and never compared, in the suppressions themselves."""
        setting = self._config()["options"]["reportUnusedDisableDirectives"]
        assert setting in {"warn", "error", "deny"}, setting

    def test_every_suppression_says_why(self):
        unexplained = [s for s in self._suppressions() if " -- " not in s]
        assert not unexplained, (
            "a silenced rule without a reason is a silence, not a decision:\n"
            + "\n".join(unexplained)
        )

    def test_there_are_suppressions_to_check(self):
        """Anti-vacuity: the test above passes an empty list, and the three
        recorded judgements are the thing it exists to hold to a standard."""
        assert len(self._suppressions()) >= 3, self._suppressions()

    def test_the_rule_is_only_off_where_the_code_is_not_ours(self):
        """`react/only-export-components` is off for the vendored shadcn tree
        and on everywhere else. Turning it off globally would have been the
        cheaper way to reach zero, and would have lost the one warning that was
        right."""
        rules = self._config()["rules"]
        assert rules["react/only-export-components"][0] == "warn"
        overrides = self._config()["overrides"]
        scoped = [
            o
            for o in overrides
            if o.get("rules", {}).get("react/only-export-components") == "off"
        ]
        assert len(scoped) == 1, scoped
        assert scoped[0]["files"] == ["src/components/ui/**"], scoped[0]["files"]


class TestEveryVariableTheSubprocessNeedsCrosses:
    """The third seam in this file, and the one with two readable sides.

    MCP's stdio client does not give its child this process's environment: it
    builds `get_default_environment() | params.env`, and on POSIX that default
    is six names, none of them ours. So `mcp_host._FORWARDED_ENV` is not a
    convenience -- it is the entire list of things the knowledge-base
    subprocess knows about the box it is running on.

    The failure is silent in both directions. Everything the subprocess reads
    has a default, so a dropped name means the wrong store, the wrong index or
    the wrong model cache, answered confidently. And the list is hand-written,
    so the only thing that connects it to the code that reads those names, or
    to the Dockerfile that sets them, is somebody remembering.

    `HF_HOME` is what that costs. The image bakes 180 MB of weights into
    `/opt/models` and the subprocess never looked there, because a cache path
    is not a retrieval knob and the one test guarding this boundary was called
    `every_retrieval_knob`. A category in a test name decided what got checked.
    """

    ROOT = pathlib.Path(__file__).resolve().parent.parent

    # Files that set the api container's runtime environment. Both are read,
    # rather than one standing in for the other, because they set different
    # names: the image bakes the model cache, compose adds the mount path and
    # the CORS origin.
    DEPLOY_SOURCES = ("Dockerfile", "docker-compose.prod.yml")

    @staticmethod
    def _declared() -> tuple[set[str], dict[str, str]]:
        from sextant.mcp_server.mcp_host import _FORWARDED_ENV, _NOT_FORWARDED

        return set(_FORWARDED_ENV), dict(_NOT_FORWARDED)

    def _subprocess_reads(self) -> set[str]:
        """Every environment variable named by code the subprocess imports.

        `sextant/vector_db/` is the subprocess's half: `python -m sextant.vector_db.server`
        imports from nowhere else. Settings arrive through `sextant.settings`, so
        they are matched by key and prefixed here; a vendor name like
        GEMINI_API_KEY is read straight off `os`, so it is matched whole.
        """
        found: set[str] = set()
        sources = sorted((self.ROOT / "sextant" / "vector_db").rglob("*.py"))
        assert len(sources) >= 8, f"expected the KB package, found {len(sources)}"
        for path in sources:
            if path.name == "settings.py":
                continue  # the module that defines the mechanism, not a reader
            try:
                text = path.read_text()
            except OSError as e:  # pragma: no cover - fails closed
                pytest.fail(f"cannot read {path}: {e}")
            for key in re.findall(r'settings\.(?:getenv|env_name|setenv)\(\s*"([A-Z_0-9]+)"', text):
                found.add(settings.env_name(key))
            for name in re.findall(r'os\.(?:getenv|environ\.get)\(\s*"([A-Z_0-9]+)"', text):
                found.add(name)
            for name in re.findall(r'os\.environ\[\s*"([A-Z_0-9]+)"\s*\]', text):
                found.add(name)
        return found

    @staticmethod
    def _api_service(compose: str) -> str:
        """The `api:` block of a compose file, and only that.

        Scanning the whole file would drag in the frontend's build args and
        Caddy's own names, and every one of those would then need an entry in
        the exemption table -- which is how a table of real decisions turns
        into a list nobody reads. The question here is narrower and worth
        keeping narrow: what does the api container get.
        """
        lines = compose.splitlines()
        starts = [i for i, line in enumerate(lines) if line.startswith("  api:")]
        # Fails closed, and on an assertion rather than a StopIteration: a
        # renamed service would otherwise make this an error nobody reads as a
        # scan that found nothing.
        assert len(starts) == 1, f"expected one `api:` service, found {len(starts)}"
        start = starts[0]
        end = next(
            (
                i
                for i in range(start + 1, len(lines))
                if lines[i][:3].strip() and not lines[i].startswith("   ")
            ),
            len(lines),
        )
        return "\n".join(lines[start:end])

    def _deploy_sets(self) -> set[str]:
        """Every variable the image or the production compose file sets for the
        api container -- `ENV X=`, `ENV X= Y=`, and compose's `environment:`
        mapping. This is the side someone edits when they add a knob to the
        box, so it is the side that has to force a decision."""
        found: set[str] = set()
        for name in self.DEPLOY_SOURCES:
            path = self.ROOT / name
            try:
                text = path.read_text()
            except OSError as e:  # pragma: no cover - fails closed
                pytest.fail(f"cannot read {path}: {e}")
            if name.endswith((".yml", ".yaml")):
                text = self._api_service(text)
            for line in text.splitlines():
                bare = line.strip()
                if bare.startswith("ENV "):
                    found.update(re.findall(r"\b([A-Z][A-Z_0-9]*)=", bare))
                elif re.match(r"^[A-Z][A-Z_0-9]*:\s*\S", bare):
                    found.add(bare.split(":", 1)[0])
        # APP_UID is a build arg: the uid the image is built for, not something
        # the running process reads.
        return found - {"APP_UID"}

    def test_forwarding_is_necessary_at_all(self):
        """The premise. If MCP inherited the whole environment this list would
        be dead weight, and the right fix would be to delete it rather than to
        keep adding to it."""
        from mcp.client.stdio import get_default_environment

        inherited = set(get_default_environment())
        forwarded, _ = self._declared()
        assert not (inherited & forwarded), inherited & forwarded
        assert "PATH" in inherited, "the default set is not what this assumes"

    def test_the_child_keeps_the_defaults_as_well(self, monkeypatch):
        """`env=` on StdioServerParameters is merged over the default set, not
        substituted for it. If that ever changes, forwarding one name would
        take PATH and HOME away from the subprocess, and the symptom would be
        a knowledge base that cannot start rather than one that answers
        wrongly -- a different failure, worth knowing about separately."""
        from mcp.client.stdio import get_default_environment

        from sextant.mcp_server.mcp_host import kb_server

        monkeypatch.setenv(settings.env_name("CHROMA_DIR"), "/tmp/elsewhere")
        child = get_default_environment() | (kb_server().env or {})
        assert child[settings.env_name("CHROMA_DIR")] == "/tmp/elsewhere"
        assert "PATH" in child and "HOME" in child

    def test_every_variable_the_subprocess_reads_is_decided(self):
        """Fail closed: a name read under `sextant/vector_db/` is forwarded, or it is in
        `_NOT_FORWARDED` with a reason. Adding a setting and forgetting the
        host is the defect this replaces guessing about."""
        forwarded, exempt = self._declared()
        undecided = sorted(self._subprocess_reads() - forwarded - set(exempt))
        assert not undecided, f"read by the subprocess, never decided: {undecided}"

    def test_every_variable_the_deploy_sets_is_decided(self):
        """The same question from the other side. `HF_HOME` was set by the
        Dockerfile, needed by the subprocess, and in neither list."""
        forwarded, exempt = self._declared()
        undecided = sorted(self._deploy_sets() - forwarded - set(exempt))
        assert not undecided, f"set for the container, never decided: {undecided}"

    def test_the_scans_are_looking_at_something(self):
        """Anti-vacuity. Both tests above pass against an empty set, and a
        regex that quietly stops matching is the way this check dies."""
        reads = self._subprocess_reads()
        sets = self._deploy_sets()
        assert len(reads) >= 9, sorted(reads)
        assert len(sets) >= 4, sorted(sets)
        for name in (
            settings.env_name("CHROMA_DIR"),
            settings.env_name("MAX_PER_DOCUMENT"),
            settings.env_name("MODEL"),
            "GEMINI_API_KEY",
        ):
            assert name in reads, f"{name} should be found by the reads scan"
        for name in ("HF_HOME", "HF_HUB_OFFLINE", settings.env_name("LOG_FORMAT")):
            assert name in sets, f"{name} should be found by the deploy scan"

    def test_an_exemption_that_stopped_being_needed_is_reported(self):
        """The lesson oxlint taught in the frontend half: a suppression nobody
        needs any more is a claim nobody checks. Every exempt name is still
        named by one of the two scans, so deleting the code that reads one
        turns its exemption into a failure rather than a fossil."""
        _, exempt = self._declared()
        live = self._subprocess_reads() | self._deploy_sets()
        stale = sorted(set(exempt) - live)
        assert not stale, f"exempted but no longer read or set anywhere: {stale}"

    def test_nothing_is_both_forwarded_and_exempt(self):
        forwarded, exempt = self._declared()
        both = sorted(forwarded & set(exempt))
        assert not both, both

    def test_every_exemption_says_why(self):
        _, exempt = self._declared()
        assert exempt, "an empty exemption table makes the two scans vacuous"
        for name, reason in exempt.items():
            assert len(reason) > 40, f"{name}: {reason!r} is not a reason"

    def test_the_model_cache_names_are_the_ones_the_loader_reads(self):
        """Not a guess: each verbatim name is resolved by the installed library
        that the subprocess imports. A name nobody reads would make the list
        look careful while fixing nothing."""
        import huggingface_hub.constants as hub
        from sentence_transformers.base import model as st_model

        from sextant.mcp_server.mcp_host import _FORWARDED_VERBATIM

        sources = []
        for module in (hub, st_model):
            path = getattr(module, "__file__", None)
            assert path, f"{module.__name__} has no source to read"
            sources.append(pathlib.Path(path).read_text())
        constants, st = sources
        for name in _FORWARDED_VERBATIM:
            assert f'"{name}"' in constants or f'"{name}"' in st, (
                f"{name} is forwarded but no loader reads it"
            )


class TestTheChildCannotGoBehindTheAllowlist:
    """The class above checks the list. This one runs the process.

    Every test in `TestEveryVariableTheSubprocessNeedsCrosses` compares sets
    of names read out of source files, and all nine of them passed while the
    thing they describe was not happening. `_NOT_FORWARDED` says of
    `GEMINI_API_KEY` that "a key that does not cross cannot leak from here",
    and from a checkout the key crossed: the child starts with the six names
    MCP inherits, imports `sextant.vector_db.server`, reaches `sextant.settings`
    through `vector_search`, and that module loads the repository's `.env`.
    Measured before the fix -- child environment without the key at exec,
    with it after the first import.

    A seam pinned on the side you can read is pinned on the side that is not
    the problem, which is item 18's finding; here the readable side was a
    dictionary and the problem was a file read two imports away. So these
    tests launch a real interpreter and ask it what it can see.

    The container was never affected: the image copies `pyproject.toml`,
    `sextant/mcp_server/`, `sextant/vector_db/` and `sextant/eval/`, and compose
    injects `env_file` as
    real environment variables, so `/app/.env` does not exist and the load is
    a no-op there. The unwatched path again -- and the watched one is where
    the agent is mounted in a desktop client.
    """

    ENV_FILE = ROOT / ".env"

    @staticmethod
    def _tree(tmp_path: pathlib.Path) -> pathlib.Path:
        """A copy of the real `settings.py` with a `.env` beside it.

        Copied for the reason `test_judge.py` copies it: `.env` is gitignored,
        CI has none, and the machine with no `.env` is the one that must still
        run this. The name is invented so that finding it in the child can
        only mean the file was read.
        """
        package = tmp_path / "sextant"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "settings.py").write_text((ROOT / "sextant" / "settings.py").read_text())
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "stand-in"\n')
        (tmp_path / ".env").write_text("SEXTANT_NOT_FORWARDED_PROBE=leaked\n")
        return tmp_path

    @staticmethod
    def _probe(tree: pathlib.Path, env: dict[str, str]) -> str:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; from sextant import settings; "
                "print(os.environ.get('SEXTANT_NOT_FORWARDED_PROBE'))",
            ],
            cwd=tree,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(tree), **env},
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_an_unsealed_process_reads_the_file(self, tmp_path):
        """Anti-vacuity, and the defect itself. Without the seal the child
        takes a name its parent never gave it -- which is what made the
        exemption table a description of an intention."""
        assert self._probe(self._tree(tmp_path), {}) == "leaked"

    def test_a_sealed_process_reads_no_file(self, tmp_path):
        assert self._probe(self._tree(tmp_path), {settings.SEALED: "1"}) == "None"

    def test_the_seal_is_read_before_the_file_is_loaded(self, tmp_path):
        """A `.env` cannot seal the process that is about to read it. The
        order matters the other way round too: were the check made after the
        load, a file setting the name would hide every other name in it."""
        tree = self._tree(tmp_path)
        (tree / ".env").write_text(
            f"{settings.SEALED}=1\nSEXTANT_NOT_FORWARDED_PROBE=leaked\n"
        )
        assert self._probe(tree, {}) == "leaked"

    def test_kb_server_seals_its_child(self):
        from sextant.mcp_server.mcp_host import kb_server

        assert (kb_server().env or {}).get(settings.SEALED) == "1"

    def test_the_child_environment_is_never_the_client_default_alone(self, monkeypatch):
        """`env=` used to be `forwarded or None`, and an empty forwarding set
        is the common case: nothing in this shell overrides a retrieval knob.
        The seal has to survive that case, so the dictionary is never empty."""
        from sextant.mcp_server.mcp_host import _FORWARDED_ENV, kb_server

        for name in _FORWARDED_ENV:
            monkeypatch.delenv(name, raising=False)
        env = kb_server().env
        assert env and settings.SEALED in env

    def test_every_stdio_child_in_the_repository_is_sealed(self):
        """The next subprocess, not this one. A second MCP server added later
        would inherit the hole in full, and nothing else in the tree would
        notice."""
        launchers = [
            path
            for path in sorted((ROOT / "sextant").rglob("*.py"))
            if "StdioServerParameters(" in path.read_text()
        ]
        assert launchers, "the scan found no stdio launcher at all"
        for path in launchers:
            text = path.read_text()
            assert "settings.SEALED" in text, f"{path} launches a child it does not seal"

    @pytest.mark.skipif(
        not ENV_FILE.exists(), reason="no .env in this checkout; the copied tree covers it"
    )
    def test_the_real_child_cannot_see_what_the_host_withheld(self):
        """The whole thing, on this machine, against the real file.

        Names only: the values in `.env` are never read into the test, and the
        assertion is about presence. Skipped where there is no `.env`, which
        is the one environment the defect could not occur in.
        """
        from mcp.client.stdio import get_default_environment

        from sextant.mcp_server.mcp_host import _NOT_FORWARDED, kb_server

        present = {
            line.split("=", 1)[0].strip()
            for line in self.ENV_FILE.read_text().splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
        withheld = sorted(present & set(_NOT_FORWARDED))
        if not withheld:
            pytest.skip("this .env sets none of the withheld names")

        params = kb_server()
        reader = "; ".join(
            f"print({name!r}, os.environ.get({name!r}) is not None)" for name in withheld
        )
        result = subprocess.run(
            [params.command, "-c", f"import sextant.vector_db.server, os; {reader}"],
            cwd=params.cwd,
            env={**get_default_environment(), **(params.env or {})},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        for name in withheld:
            assert f"{name} False" in result.stdout, (
                f"{name} is in _NOT_FORWARDED and the child has it:\n{result.stdout}"
            )


class TestStatusSaysWhatIsBilling:
    """`CLAUDE.md` says `deploy/deploy.sh HOST status` "says what is billing".
    It said it for two of GCP's eight instance states.

    The billing line was a `case` with arms for `RUNNING` and `TERMINATED` and
    no default, so `STOPPING`, `SUSPENDED`, `STAGING`, `REPAIRING`,
    `PROVISIONING` and `SUSPENDING` printed the instance line and nothing else,
    and exited 0. Every one of those bills. The one that reads worst is
    `STOPPING`: it is what you see when a stop was issued and has not finished,
    which is exactly the moment after a trip when a person checks — and silence
    there is indistinguishable from the parked case.

    Worse, a `describe` that fails — wrong project, expired credentials, an API
    error — leaves `state` empty, so the command whose job is to say what is
    billing printed `agenticrag (, us-central1-a):` and exited 0. The 2026-09-28
    ₹703 failure was a box nobody checked; this is the check answering nothing
    and calling it success.
    """

    # Every state the compute API documents an instance can be in. The script
    # has to have a verdict for each, which is the point: a `case` with no
    # default is a list of the states somebody thought of.
    BILLING_STATES = (
        "PROVISIONING",
        "STAGING",
        "RUNNING",
        "STOPPING",
        "SUSPENDING",
        "SUSPENDED",
        "REPAIRING",
    )
    PARKED_STATE = "TERMINATED"

    def test_every_state_that_bills_says_so(self, tmp_path):
        for i, state in enumerate(self.BILLING_STATES):
            work = tmp_path / f"s{i}"
            work.mkdir()
            code, out, _ = _run_deploy(work, args=("status",), vm_state=state)
            assert "billing" in out, f"{state}: no billing verdict in {out!r}"
            assert code == 0, f"{state}: exit {code}"

    def test_the_parked_state_says_the_meter_is_off(self, tmp_path):
        code, out, _ = _run_deploy(tmp_path, args=("status",), vm_state=self.PARKED_STATE)
        assert "billing" in out
        assert "meter off" in out, out
        assert code == 0

    def test_a_state_nobody_thought_of_is_assumed_to_be_billing(self, tmp_path):
        """Wrong in the safe direction, like the grounded-search price. A new
        state name must not read as parked."""
        code, out, _ = _run_deploy(tmp_path, args=("status",), vm_state="HIBERNATED")
        assert "billing" in out, out
        assert "meter off" not in out, out

    def _billing_block(self) -> str:
        """`billing_line`, as text.

        Read rather than executed because what is being pinned is the *shape*
        of the decision -- that there is a default at all -- and no run can
        show the absence of one.

        This used to read the `status)` arm, where the arms lived until
        2026-10-23. They moved into a function when `down`'s epilogue needed
        the same eight answers, and these two tests failed on the move, which
        is the pin working: the decision is still being read, at its one
        address. `test_status_still_calls_it` below is the other half --
        without it this pins a function nothing has to use.
        """
        text = (DEPLOY / "deploy.sh").read_text()
        start = text.index("\nbilling_line() {")
        end = text.index("\n}\n", start)
        return text[start:end]

    def test_status_still_calls_it(self):
        text = (DEPLOY / "deploy.sh").read_text()
        start = text.index("\n  status)")
        end = text.index("\n  stop)", start)
        assert 'billing_line "$state"' in text[start:end], "status prints no verdict"

    def test_the_billing_case_keeps_a_default(self):
        """The arms are a list of the states somebody thought of; the default
        is the part that holds when the next one is invented. Removing it puts
        this straight back to printing nothing for a box that bills."""
        block = self._billing_block()
        assert "*)" in block, "the billing case has no default arm"
        tail = block[block.index("*)") :]
        assert "UNKNOWN" in tail and "meter is on" in tail, tail[:200]

    def test_the_states_this_test_knows_are_the_states_the_script_knows(self):
        """Anti-drift, and anti-vacuity: the run-every-state test above would
        keep passing on the default arm alone, reporting UNKNOWN for states the
        script used to name. Each one has to still be named."""
        block = self._billing_block()
        missing = [s for s in (*self.BILLING_STATES, self.PARKED_STATE) if s not in block]
        assert not missing, f"named by the test, not by the script: {missing}"

    def test_the_line_carries_the_machine_type_and_the_address(self, tmp_path):
        """What `status` prints, printed by something.

        The stub answered one field to a `--format` asking for three, so
        `status` rendered `agenticrag (, us-central1-a): RUNNING` in every test
        and the two fields a person reads it for came from nowhere. A stub that
        cannot produce them makes every assertion about them a comment -- the
        lesson the curl stub learned about `-o` and `-w` in item 8.
        """
        code, out, _ = _run_deploy(
            tmp_path,
            args=("status",),
            vm_state="RUNNING",
            FAKE_MACHINE_TYPE="e2-standard-4",
            FAKE_NAT_IP="198.51.100.9",
        )
        assert code == 0, out
        assert "e2-standard-4" in out, out
        assert "198.51.100.9" in out, out
        assert "(, " not in out, f"an empty field is being printed: {out!r}"

    def test_a_describe_that_failed_is_not_a_parked_box(self, tmp_path):
        """The failure that reads as reassurance. An unreadable state has to be
        louder than any state, not quieter than all of them."""
        code, out, _ = _run_deploy(tmp_path, args=("status",), vm_state="")
        assert code != 0, f"exit 0 for an unreadable state: {out!r}"
        assert "could not read" in out.lower() or "unknown" in out.lower(), out


# --- The preflight ----------------------------------------------------------
#
# `deploy.sh preflight` is the only thing standing between a misconfigured box
# and twenty minutes of building torch on two vCPUs, and until now nothing had
# ever executed it -- not once, in any harness. It could not be: it calls GNU
# `stat -c`, `getent hosts` and `docker`, and it tests `/data/chroma`, none of
# which exist on the laptop that wrote it. So the three stubs below are not
# decoration, they are the reason any assertion about this script is worth
# more than a comment.

_STAT_STUB = """#!/usr/bin/env bash
# GNU `stat -c`, which the box and CI have and macOS does not. The preflight
# asks for two formats and nothing else; anything beyond them fails loudly
# here rather than being quietly answered wrong.
#
# The first version of this delegated to `/usr/bin/stat -f '%OLp'` -- BSD
# syntax. On Linux `-f` means *file system* status and `%OLp` is read as a
# filename, so the stub answered a whole tmpfs report, the preflight printed
# it as the permission bits, and every check that reads a `stat` failed. Item
# 13 was BSD-only `tar` flags making the trip harness Mac-only; this is the
# same defect inside a stub whose entire job is to stand in for the GNU tool.
# python3 is on both platforms and has no flags to get wrong.
fmt=""
while [ $# -gt 0 ]; do
  case "$1" in -c) fmt="$2"; shift 2 ;; *) break ;; esac
done
bits='import os,sys; print(format(os.stat(sys.argv[1]).st_mode & 0o7777, "o"))'
uid='import os,sys; print(os.stat(sys.argv[1]).st_uid)'
case "$fmt" in
  '%a') python3 -c "$bits" "$1" ;;
  '%u') python3 -c "$uid"  "$1" ;;
  *)    echo "STUB FAULT: stat was asked for format '$fmt'" >&2; exit 95 ;;
esac
"""

_GETENT_STUB = """#!/usr/bin/env bash
# `getent hosts <name>`, which is glibc and so is not on macOS at all. The
# preflight takes the first field of the first line, so that is what this
# prints. FAKE_DNS_A=none models a name that resolves to nothing, which is the
# state a subdomain is in before it is created -- the failure the DNS check is
# there for.
[ "$1" = hosts ] || { echo "STUB FAULT: getent was asked for '$1'" >&2; exit 95; }
case "${FAKE_DNS_A-203.0.113.7}" in
  none) exit 2 ;;
  *)    echo "${FAKE_DNS_A-203.0.113.7} $2" ;;
esac
"""

_DOCKER_STUB = """#!/usr/bin/env bash
# `command -v docker` finds this file; `docker compose version` decides whether
# the plugin is reported present. FAKE_NO_COMPOSE=1 is a box with docker and no
# compose plugin, which is what a plain `apt install docker.io` leaves behind.
case "$1" in
  compose) exit "${FAKE_NO_COMPOSE:-0}" ;;
  *)       exit 0 ;;
esac
"""

# 60 characters, which is the shape `caddy hash-password` prints: `$2a$14$`
# and 53 more. The preflight's length floor is 59, so this is the first length
# that passes rather than a comfortable one.
_GOOD_HASH = "$2a$14$" + "u" * 53


def _env_fixture(**over: str | None) -> str:
    """A box `.env` that passes every preflight check, plus overrides.

    A key set to `None` is left out of the file altogether. That is a different
    failure from an empty value and both have to be separately checkable: the
    trip learned the same distinction for `SEXTANT_PROXY_SECRET` in item 3.
    """
    rows: dict[str, str | None] = {
        "SITE_ADDRESS": "agenticrag.example.in",
        "PUBLIC_URL": "https://agenticrag.example.in",
        "ACME_EMAIL": "you@example.com",
        "BASIC_AUTH_USER": "admin",
        "BASIC_AUTH_HASH": _GOOD_HASH,
        "BASIC_AUTH_USER_2": "",
        "BASIC_AUTH_HASH_2": "",
        "BASIC_AUTH_USER_3": "",
        "BASIC_AUTH_HASH_3": "",
        "SEXTANT_PROXY_SECRET": "f" * 64,
        "GEMINI_API_KEY": "AIza-fixture-not-a-key",
        "APP_UID": str(os.getuid()),
    }
    rows.update(over)
    return "".join(f"{k}={v}\n" for k, v in rows.items() if v is not None)


def _run_preflight(tmp_path, env_text: str, **extra_env: str):
    """Run the real `deploy/deploy.sh ... preflight`. Returns (code, output).

    The box is a fixture directory; `DATA_DIR` points the data-mount checks at
    one too. That override exists only so this script can be executed off the
    VM -- it defaults to `/data/chroma` and the box never passes it, the same
    arrangement `VM_SSH_TRIES` already has.
    """
    # Its own root per call, so one test can run the script more than once --
    # which the last test in the class does, because a harness that can only
    # show a pass is a harness that proves nothing about the checks.
    root = tmp_path / f"run{len(list(tmp_path.iterdir()))}"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    for name, body in (
        ("ssh", _SSH_STUB),
        ("gcloud", _GCLOUD_STUB),
        ("curl", _CURL_STUB),
        ("stat", _STAT_STUB),
        ("getent", _GETENT_STUB),
        ("docker", _DOCKER_STUB),
    ):
        f = bin_dir / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)

    box = root / "box" / "agenticrag"
    box.mkdir(parents=True)
    env_file = box / ".env"
    env_file.write_text(env_text)
    env_file.chmod(0o600)

    data = root / "data"
    data.mkdir()

    state = root / "vm-state"
    state.write_text("RUNNING\n")
    state.with_suffix(".ip").write_text("10.0.0.1\n")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_BOX": str(box.parent),
        "FAKE_STATE": str(state),
        "DATA_DIR": str(data),
        "VM_INSTANCE": "agenticrag",
        "VM_ZONE": "us-central1-a",
        "VM_PROJECT": "test-project",
        **extra_env,
    }
    done = subprocess.run(
        [
            "bash",
            str(DEPLOY / "deploy.sh"),
            "agenticrag.us-central1-a.test-project",
            "preflight",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    out = done.stdout + done.stderr
    # A broken stub makes every check FAIL, so every test that asserts a
    # non-zero exit passes -- and on CI, before the `stat` stub was fixed,
    # fourteen of the seventeen below did exactly that. Only the three that
    # assert a *pass* noticed. A stub fault can never be the reason a test is
    # green, so it stops the test here instead.
    assert "STUB FAULT" not in out, f"the harness failed, not the script:\n{out}"
    return done.returncode, out


class TestThePreflightChecksWhatTheDeployActuallyNeeds:
    """The check that passed a box which could not answer a single request.

    `deploy.sh up` runs this, prints `-- preflight passed`, ships the tree and
    builds for twenty minutes. Two configurations got all the way through it
    and then took the box down:

    `SEXTANT_PROXY_SECRET` empty. Caddy has no conditionals -- `header_up
    X-Sextant-User {http.auth.user.id}` goes out on every proxied request
    whether or not the app can verify where it came from -- so the app raises
    `ForgedIdentity` and answers **403 to everything**. `deploy/env.example`
    calls it REQUIRED, `deploy/README.md` lists it as one of two hard stops,
    `CLAUDE.md` calls it a deploy prerequisite and `trip.sh` has refused to
    build without it since 2026-10-06. The one command whose entire stated job
    is "check the box BEFORE spending twenty minutes building torch" never
    read the name.

    A gate slot filled on one side. The Caddyfile has had three `basic_auth`
    slots since 0.8.3 and Caddy refuses to *start* on a user with no hash, so
    the box serves nothing at all -- after the build. The preflight's `.env`
    reader named `BASIC_AUTH_USER` and `BASIC_AUTH_HASH` and stopped, so slots
    2 and 3 were never captured and no check could have asked about them. The
    bcrypt-shape check that the script's own comment puts first ("a mangled
    hash rejects every password ... Cheap to check, expensive to discover")
    looked at one slot of three. Same shape as item 19: a list named after the
    variables somebody had in mind cannot grow with the file it mirrors.

    And the open row's own criterion needs slot 2 -- `trip.sh` step 7 uploads
    as two gate users to prove the isolation. So this is not a slot nobody
    will fill; it is the next one to be filled.
    """

    def test_a_good_box_passes(self, tmp_path):
        """The baseline, and the first time this script has ever run."""
        code, out = _run_preflight(tmp_path, _env_fixture())
        assert code == 0, out
        assert "preflight passed" in out, out
        assert "FAIL" not in out, out

    def test_an_empty_proxy_secret_fails_before_the_build(self, tmp_path):
        code, out = _run_preflight(tmp_path, _env_fixture(SEXTANT_PROXY_SECRET=""))
        assert code != 0, f"a box that would 403 every request passed: {out!r}"
        assert "SEXTANT_PROXY_SECRET" in out, out
        assert "403" in out, out

    def test_a_missing_proxy_secret_line_fails_too(self, tmp_path):
        """Absent is not the same as empty, and both reach the same box."""
        code, out = _run_preflight(tmp_path, _env_fixture(SEXTANT_PROXY_SECRET=None))
        assert code != 0, f"a .env with no secret line passed: {out!r}"
        assert "SEXTANT_PROXY_SECRET" in out, out

    def test_the_remediation_generates_the_value_on_the_box(self, tmp_path):
        """The same remedy `trip.sh` prints: generated there, so the value
        never crosses a laptop and nothing has to be pasted."""
        _, out = _run_preflight(tmp_path, _env_fixture(SEXTANT_PROXY_SECRET=""))
        assert "openssl rand -hex 32" in out, out
        assert ">> .env" in out, out

    def test_a_user_without_its_hash_is_caught(self, tmp_path):
        """Caddy refuses to start on this, so the box serves nothing -- and it
        refuses after the build, which is the one thing this script prevents."""
        code, out = _run_preflight(tmp_path, _env_fixture(BASIC_AUTH_USER_2="second"))
        assert code != 0, f"a box Caddy would refuse to start passed: {out!r}"
        assert "BASIC_AUTH_HASH_2" in out, out

    def test_a_hash_without_its_user_is_caught_too(self, tmp_path):
        code, out = _run_preflight(
            tmp_path, _env_fixture(BASIC_AUTH_HASH_3=_GOOD_HASH)
        )
        assert code != 0, f"a half-filled third slot passed: {out!r}"
        assert "BASIC_AUTH_USER_3" in out, out

    def test_a_truncated_hash_in_a_later_slot_is_caught(self, tmp_path):
        """The failure the script's own comment names first, in a slot it had
        never read. 20 characters is what survives compose eating the `$`."""
        code, out = _run_preflight(
            tmp_path,
            _env_fixture(BASIC_AUTH_USER_2="second", BASIC_AUTH_HASH_2="$2a$14$short"),
        )
        assert code != 0, f"a truncated hash in slot 2 passed: {out!r}"
        assert "BASIC_AUTH_HASH_2" in out, out

    def test_a_mangled_hash_in_a_later_slot_is_caught(self, tmp_path):
        code, out = _run_preflight(
            tmp_path,
            _env_fixture(
                BASIC_AUTH_USER_2="second", BASIC_AUTH_HASH_2="2a14" + "u" * 56
            ),
        )
        assert code != 0, f"a hash with its $ signs eaten passed: {out!r}"
        assert "BASIC_AUTH_HASH_2" in out, out

    def test_three_filled_slots_pass(self, tmp_path):
        """What the box looks like on the trip that proves the isolation."""
        code, out = _run_preflight(
            tmp_path,
            _env_fixture(
                BASIC_AUTH_USER_2="second",
                BASIC_AUTH_HASH_2=_GOOD_HASH,
                BASIC_AUTH_USER_3="third",
                BASIC_AUTH_HASH_3=_GOOD_HASH,
            ),
        )
        assert code == 0, out
        assert "preflight passed" in out, out

    def test_an_unused_slot_is_not_a_failure(self, tmp_path):
        """Both halves empty is how env.example ships, and the Caddyfile drops
        the line before parsing it. A check that fails on the documented
        default is a check that gets ignored."""
        code, out = _run_preflight(tmp_path, _env_fixture())
        assert code == 0, out

    def test_a_gate_with_nobody_in_it_is_a_failure(self, tmp_path):
        code, out = _run_preflight(
            tmp_path, _env_fixture(BASIC_AUTH_USER="", BASIC_AUTH_HASH="")
        )
        assert code != 0, f"a gate nobody can pass was reported ready: {out!r}"

    def test_no_value_out_of_the_env_is_ever_printed(self, tmp_path):
        """The invariant item 5 pinned for the trip, now that this script reads
        a secret and three hashes. Lengths are reported; values are not."""
        secret = "deadbeef" * 8
        _, out = _run_preflight(
            tmp_path,
            _env_fixture(
                SEXTANT_PROXY_SECRET=secret,
                BASIC_AUTH_USER_2="second",
                BASIC_AUTH_HASH_2=_GOOD_HASH,
            ),
        )
        for value in (secret, _GOOD_HASH, "AIza-fixture-not-a-key", "admin", "second"):
            assert value not in out, f"{value[:6]}... was printed: {out!r}"

    def test_the_checks_can_still_fail_for_the_old_reasons(self, tmp_path):
        """The harness is new, so the checks that were already here get run
        through it once -- otherwise a stub that answers everything `ok` would
        make this whole class green against any script at all."""
        code, out = _run_preflight(tmp_path, _env_fixture(), FAKE_DNS_A="none")
        assert code != 0, out
        assert "fix DNS" in out, out
        code, out = _run_preflight(tmp_path, _env_fixture(), FAKE_NO_COMPOSE="1")
        assert code != 0, out
        assert "compose plugin" in out, out
        code, out = _run_preflight(
            tmp_path, _env_fixture(PUBLIC_URL="https://elsewhere.example.in")
        )
        assert code != 0, out
        assert "PUBLIC_URL" in out, out


class TestEveryDeployTimeVariableReachesThePreflight:
    """The list that cannot fall behind the files it mirrors.

    The preflight can only check a variable it captured, and what it captures
    is one hand-written `case` alternation. That list sat at seven names while
    the Caddyfile grew to nine and compose to two, and nothing noticed -- the
    same failure as item 19's `_FORWARDED_ENV`, one directory over. So the
    check here is not "are these particular names present": it is that the
    set of names the deploy interpolates is a subset of the set the preflight
    reads, computed from the files each time. Add a `{$VAR}` to the Caddyfile
    and this fails until the preflight knows about it.
    """

    PREFLIGHT_START = "<<'PREFLIGHT'"
    PREFLIGHT_END = "\nPREFLIGHT\n"

    @staticmethod
    def _preflight() -> str:
        body = (DEPLOY / "deploy.sh").read_text()
        start = body.index(TestEveryDeployTimeVariableReachesThePreflight.PREFLIGHT_START)
        end = body.index(
            TestEveryDeployTimeVariableReachesThePreflight.PREFLIGHT_END, start
        )
        return body[start:end]

    @staticmethod
    def _uncommented(text: str) -> str:
        """Lines with the `#` comments stripped. The Caddyfile's own prose
        mentions `{$VAR}` as an example, and a scan that counts prose finds a
        variable nobody interpolates."""
        return "\n".join(line.split("#", 1)[0] for line in text.splitlines())

    @classmethod
    def _caddy_vars(cls) -> set[str]:
        text = cls._uncommented((DEPLOY / "Caddyfile").read_text())
        return set(re.findall(r"\{\$([A-Z_][A-Z0-9_]*)\}", text))

    @classmethod
    def _compose_vars(cls) -> set[str]:
        compose = DEPLOY.parent / "docker-compose.prod.yml"
        text = cls._uncommented(compose.read_text())
        return set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)[:}]", text))

    @classmethod
    def _captured(cls) -> set[str]:
        """The names the preflight's `.env` reader keeps."""
        block = cls._preflight()
        match = re.search(r'case "\$key" in\s*(.*?)\)\s*\n', block, re.S)
        assert match, f"cannot find the .env reader's key list in:\n{block}"
        return set(re.findall(r"[A-Z_][A-Z0-9_]*", match.group(1)))

    def test_every_variable_the_proxy_interpolates_is_read(self):
        missing = self._caddy_vars() - self._captured()
        assert not missing, (
            f"the Caddyfile interpolates {sorted(missing)} and the preflight "
            "never reads them, so no check about them can exist"
        )

    def test_every_variable_the_compose_interpolates_is_read(self):
        missing = self._compose_vars() - self._captured()
        assert not missing, (
            f"docker-compose.prod.yml interpolates {sorted(missing)} and the "
            "preflight never reads them"
        )

    def test_the_scans_are_looking_at_something(self):
        """Rename the `basic_auth` block or the api service and the scans go
        quiet rather than red; an empty set is a subset of everything."""
        caddy = self._caddy_vars()
        assert "SEXTANT_PROXY_SECRET" in caddy, caddy
        assert "BASIC_AUTH_HASH_3" in caddy, caddy
        assert len(caddy) >= 9, caddy
        compose = self._compose_vars()
        assert {"PUBLIC_URL", "APP_UID"} <= compose, compose

    def test_the_reader_is_the_list_the_tests_above_measure(self):
        """If `_captured` silently matched the whole heredoc, both subset tests
        would pass against any script."""
        captured = self._captured()
        assert "SITE_ADDRESS" in captured, captured
        assert "PREFLIGHT" not in captured, captured
        assert len(captured) <= 20, f"this is matching more than the key list: {captured}"


class TestTheGateSlotsAreCheckedBeforeTheBuild:
    """`deploy.sh`'s preflight has validated every gate slot since 2026-10-12,
    and `trip.sh` -- the script that does the twenty-minute build -- never
    called it. Step 4 is `compose up -d --build` straight over ssh, so the one
    check standing between a misconfigured box and that build was not in the
    path. Step 2 counted non-empty hashes instead and printed
    `basic_auth users: 2`.

    On 2026-10-31 that sentence was true and the gate it describes served
    nothing: slot 2 had sat unread in the box's `.env` because the deployed
    0.8.1 Caddyfile had no slot to read it with, the three-slot Caddyfile
    reached it for the first time, and Caddy crash-looped on `base64-decoding
    password: illegal base64 data at input byte 5`. Ten minutes of build to
    discover something readable for Rs0 before the meter started.

    The rule now lives in `deploy/gate-slots.sh` and both doors run it.
    """

    _MANGLED = "ubyPq5Z.abcdefghijklmnopqrstuvwxyz0123456789ABCDEF"

    def _env(self, **slot):
        env = GOOD_ENV
        for name, value in slot.items():
            old = f"{name}={SENTINELS['BASIC_AUTH_HASH']}"
            assert old in env, old
            env = env.replace(old, f"{name}={value}")
        return env

    def test_a_mangled_hash_stops_the_trip(self, tmp_path):
        """The 2026-10-31 failure itself: the $ signs eaten, so what Caddy
        gets is not a bcrypt hash at all."""
        code, out = _run_trip(tmp_path, self._env(BASIC_AUTH_HASH_2=self._MANGLED))
        assert "BASIC_AUTH_HASH_2 doesn't start with $2a$" in out
        assert code != 0

    def test_a_mangled_hash_stops_it_BEFORE_anything_is_built(self, tmp_path):
        """The whole point is the order. A check that fires after the build has
        not saved the build, and the build is the expensive half."""
        _, out = _run_trip(tmp_path, self._env(BASIC_AUTH_HASH_2=self._MANGLED))
        assert "shipping the working tree" not in out
        assert "4 - build and start" not in out
        assert "safe to build" not in out

    def test_a_truncated_hash_stops_the_trip(self, tmp_path):
        """A hash that starts right and ends short -- the paste that lost its
        tail. Caddy refuses this too, and the prefix arm alone would pass it."""
        code, out = _run_trip(tmp_path, self._env(BASIC_AUTH_HASH_2="$2a$14$tooshort"))
        assert "BASIC_AUTH_HASH_2 is only" in out
        assert code != 0

    def test_a_user_with_no_hash_stops_the_trip(self, tmp_path):
        """Caddy refuses to START on a half-filled slot, so this is not a
        degraded box either -- it is a box that serves nothing."""
        code, out = _run_trip(tmp_path, self._env(BASIC_AUTH_HASH_2=""))
        assert "BASIC_AUTH_USER_2 is set but BASIC_AUTH_HASH_2 is empty" in out
        assert code != 0

    def test_the_check_actually_runs_on_a_good_box(self, tmp_path):
        """The stub answers `bash -s` by running it for real, and a stub that
        answered nothing would be indistinguishable from one that answered
        correctly to every test above -- all four assert a failure. This one
        asserts the passing verdict is printed, so a dead check fails here.
        """
        code, out = _run_trip(tmp_path, GOOD_ENV)
        assert "BASIC_AUTH_HASH looks like bcrypt (60 chars)" in out
        assert "gate slot 3 unused (both halves empty)" in out
        assert code == 0

    def test_no_hash_is_printed_by_the_check(self, tmp_path):
        """Lengths and verdicts only. The check runs on the box precisely so
        the value never crosses back."""
        _, out = _run_trip(tmp_path, GOOD_ENV)
        assert SENTINELS["BASIC_AUTH_HASH"] not in out

    def test_the_fixture_is_a_hash_the_real_gate_would_accept(self, tmp_path):
        """The sentinel was 30 characters until this item. A fixture the
        product refuses describes a box that cannot serve, and every trip test
        in this module would have been asserting about a run that stopped at
        step 2."""
        h = SENTINELS["BASIC_AUTH_HASH"]
        assert len(h) == 60, len(h)
        assert h.startswith("$2a$")

    def test_the_gate_rule_has_exactly_one_home(self):
        """`billing_line`, `_FORWARDED_ENV` and the preflight's key list are
        all the same lesson: the second place that needs an answer calls the
        first one, it does not copy it. A second bcrypt rule in deploy/ would
        be right the day it is written and behind the other one afterwards."""
        rule = DEPLOY / "gate-slots.sh"
        assert "'$2'[aby]" in rule.read_text()
        others = [
            p
            for p in DEPLOY.glob("*.sh")
            if p != rule and "'$2'[aby]" in p.read_text()
        ]
        assert others == [], f"a second copy of the bcrypt rule: {others}"

    def test_both_doors_run_the_shared_rule(self):
        """trip.sh ships it over ssh; deploy.sh's preflight sends it down the
        same pipe as its own body and calls it with what it already read."""
        assert "gate-slots.sh" in (DEPLOY / "trip.sh").read_text()
        deploy = (DEPLOY / "deploy.sh").read_text()
        assert "cat deploy/gate-slots.sh" in deploy
        assert "gate_slot_values" in deploy


class TestTheBoxsSecretsAreSetByAScriptAndNotByHand:
    """`CLAUDE.md` has told every reader since go-live that "on the VM the
    owner runs `set-secrets.sh`", and `trip.sh` step 3 preserves a file by
    that name across every deploy (`! -name set-secrets.sh` in the wipe).
    **The file had never been written.** So the documented way to put a secret
    on this box was a file that did not exist, and the real way was a hand-edit
    in vi.

    On 2026-10-31 that hand-edit is what cost the build: slot 2's bcrypt hash
    reached `.env` with its `$` signs eaten and Caddy crash-looped on
    `base64-decoding password: illegal base64 data at input byte 5` -- byte 5,
    not byte 0, so the `$2a$12$` prefix was already gone when Caddy read it.

    The script exists now and runs ON the box: plaintexts arrive on stdin
    (never argv, which `ps` publishes), the hash is generated where it will be
    used, and there is no transit left to mangle it in. It does not judge what
    it wrote -- step 2's `gate-slots.sh` does, immediately afterwards.
    """

    _MANGLED = "ubyPq5Z.abcdefghijklmnopqrstuvwxyz0123456789ABCDEF"
    _PASSWORD = "plaintext0that0must0never0be0printed"

    def _box_env(self, tmp_path):
        return (tmp_path / "box" / "agenticrag" / ".env").read_text()

    def _secrets(self, tmp_path, body):
        f = tmp_path / "operator-secrets.env"
        f.write_text(body)
        return str(f)

    def _broken_env(self):
        """The box as it actually was on 2026-10-31: slot 2 filled on one side
        with a hash whose `$` signs are gone."""
        return GOOD_ENV.replace(
            f"BASIC_AUTH_HASH_2={SENTINELS['BASIC_AUTH_HASH']}",
            f"BASIC_AUTH_HASH_2={self._MANGLED}",
        )

    def test_the_file_claude_md_names_exists(self):
        """The claim and the file, checked against each other. Writing the
        file is the honest resolution; deleting the sentence would have been
        the other one."""
        script = DEPLOY / "set-secrets.sh"
        assert script.is_file(), "CLAUDE.md names a script that does not exist"
        assert os.access(script, os.X_OK), "it is documented as something you run"
        claude = (ROOT / "CLAUDE.md").read_text()
        assert "set-secrets.sh" in claude

    def test_without_a_secrets_file_the_box_is_not_touched(self, tmp_path):
        """Most trips change no secret. Unset is a skip that says what it did
        not do -- the shape step 1b already uses -- not a prompt and not a
        failure."""
        before = self._broken_env()
        code, out = _run_trip(tmp_path, before, args=("--no-deploy",))
        assert "SEXTANT_SECRETS_FILE unset" in out
        assert "not changing the box's .env" in out
        assert self._box_env(tmp_path) == before, "a skip wrote to .env"
        assert code == 0

    def test_a_mangled_hash_is_replaced_and_the_gate_then_passes(self, tmp_path):
        """End to end on the real failure: the box starts in the state that
        crash-looped Caddy, and the trip gets past the gate check that would
        otherwise have stopped it."""
        secrets = self._secrets(
            tmp_path,
            f"BASIC_AUTH_USER_2=grace\nBASIC_AUTH_PASS_2={self._PASSWORD}\n",
        )
        code, out = _run_trip(tmp_path, self._broken_env(), SEXTANT_SECRETS_FILE=secrets)
        assert "hashed" in out and "BASIC_AUTH_PASS_2 -> BASIC_AUTH_HASH_2" in out
        # The judge, not the writer, is what says the slot is acceptable.
        assert "BASIC_AUTH_HASH_2 looks like bcrypt (60 chars)" in out
        assert "safe to build" in out
        written = self._box_env(tmp_path)
        assert self._MANGLED not in written, "the mangled hash survived"
        line = [
            row
            for row in written.splitlines()
            if row.startswith("BASIC_AUTH_HASH_2=")
        ]
        assert len(line) == 1, line
        assert line[0].startswith("BASIC_AUTH_HASH_2=$2a$"), line[0]
        assert code == 0

    def test_the_plaintext_is_never_printed(self, tmp_path):
        """The password crosses two machines in this step. The only thing that
        may come back is a length and a verdict."""
        secrets = self._secrets(
            tmp_path,
            f"BASIC_AUTH_USER_2=grace\nBASIC_AUTH_PASS_2={self._PASSWORD}\n",
        )
        _, out = _run_trip(tmp_path, self._broken_env(), SEXTANT_SECRETS_FILE=secrets)
        assert self._PASSWORD not in out
        # Nor the hash it became: `gate-slots.sh` prints lengths for the same
        # reason, and a hash in a terminal scrollback is a hash in a log.
        hash_line = [
            row
            for row in self._box_env(tmp_path).splitlines()
            if row.startswith("BASIC_AUTH_HASH_2=")
        ][0]
        fresh = hash_line.split("=", 1)[1]
        # Assert the write happened before asserting what it did not print:
        # without this the test passes when step 1c does nothing at all, which
        # is a fixture that disables the feature it is checking.
        assert fresh.startswith("$2a$") and len(fresh) == 60, hash_line
        assert fresh != self._MANGLED
        assert fresh not in out

    def test_a_hash_pasted_instead_of_a_password_is_refused(self, tmp_path):
        """Accepting a ready-made hash would reopen the exact path that
        mangled slot 2: a `$2a$...` string retyped through two shells. The
        refusal names the key to use instead."""
        secrets = self._secrets(tmp_path, "BASIC_AUTH_HASH_2=$2a$14$whatever\n")
        code, out = _run_trip(
            tmp_path, self._broken_env(), SEXTANT_SECRETS_FILE=secrets
        )
        assert "give BASIC_AUTH_HASH_2 as BASIC_AUTH_PASS_2" in out
        assert "4 - build and start" not in out, "it built on a refused secret"
        assert code != 0

    def test_a_key_the_script_does_not_set_is_refused(self, tmp_path):
        """An allow-list, for the reason writes are an allow-list everywhere
        else here: a typo'd name appended as a new line is indistinguishable
        from a setting that does nothing."""
        secrets = self._secrets(tmp_path, "SEXTANT_WHATEVER=1\n")
        code, out = _run_trip(tmp_path, GOOD_ENV, SEXTANT_SECRETS_FILE=secrets)
        assert "SEXTANT_WHATEVER is not a secret this script sets" in out
        assert "4 - build and start" not in out
        assert code != 0

    def test_an_unreadable_secrets_file_stops_the_trip(self, tmp_path):
        """Named and missing is a typo, not a decision to change nothing --
        the skip above is what "change nothing" looks like."""
        code, out = _run_trip(
            tmp_path, GOOD_ENV, SEXTANT_SECRETS_FILE=str(tmp_path / "nope.env")
        )
        assert "cannot read" in out
        assert "4 - build and start" not in out
        assert code != 0

    def test_the_gate_credentials_come_from_the_same_file(self, tmp_path):
        """Steps 6 and 7 log in with the plaintext the operator has just
        stated here. Making them state it twice is a chance to state it
        differently, and the symptom would be a 401 at step 6 read as a fault
        in the hash step 1c had just written."""
        secrets = self._secrets(
            tmp_path,
            "BASIC_AUTH_USER=ada\nBASIC_AUTH_PASS=pw-one\n"
            "BASIC_AUTH_USER_2=grace\nBASIC_AUTH_PASS_2=pw-two\n",
        )
        _, out = _run_trip(tmp_path, self._broken_env(), SEXTANT_SECRETS_FILE=secrets)
        assert "step 6 will log in as the first gate user" in out
        assert "step 7 will prove isolation with the second user" in out
        # And the proof that it took effect: those steps skip when unset.
        assert "SEXTANT_TRIP_AUTH unset" not in out
        assert "SEXTANT_TRIP_AUTH_2 unset" not in out

    def test_an_exported_credential_wins_over_the_file(self, tmp_path):
        """The operator may be testing a password the file does not carry.
        Deriving is a default, not an override."""
        secrets = self._secrets(
            tmp_path, "BASIC_AUTH_USER=ada\nBASIC_AUTH_PASS=pw-one\n"
        )
        _, out = _run_trip(
            tmp_path,
            self._broken_env(),
            SEXTANT_SECRETS_FILE=secrets,
            SEXTANT_TRIP_AUTH="someone:else",
        )
        assert "step 6 will log in as the first gate user" not in out

    def test_the_script_is_shipped_on_every_trip(self, tmp_path):
        """Step 3 preserves `set-secrets.sh` across the wipe, so a copy left on
        the box would outlive the tree it came from -- the `_FORWARDED_ENV`
        shape, in a file on another machine. It is sent every time."""
        secrets = self._secrets(tmp_path, "GEMINI_API_KEY=AIzaNEWKEYdonotprint\n")
        _run_trip(tmp_path, GOOD_ENV, SEXTANT_SECRETS_FILE=secrets)
        shipped = tmp_path / "box" / "agenticrag" / "set-secrets.sh"
        assert shipped.is_file(), "the box never received the script"
        assert shipped.read_text() == (DEPLOY / "set-secrets.sh").read_text()

    def test_the_writer_does_not_carry_the_rule_that_judges_it(self):
        """The other direction of `test_the_gate_rule_has_exactly_one_home`.
        A fixer that validated its own output would be a second reader of a
        rule with one home, and a check whose subject is the thing that wrote
        it."""
        script = (DEPLOY / "set-secrets.sh").read_text()
        assert "'$2'[aby]" not in script
        assert "gate-slots.sh" in script, "it should say who does judge it"
        trip = (DEPLOY / "trip.sh").read_text()
        assert trip.index("1c - the box's secrets") < trip.index(
            "gate-slots.sh"
        ), "the gate check must run after the write, not before"

    def test_the_model_key_can_be_rotated_without_a_hand_edit(self, tmp_path):
        """The other half of what kept the box on a leaked key: rotating it
        meant editing `.env` on a running box, which is a turn that ends with
        the meter on. 2026-09-28 cost Rs703 that way."""
        secrets = self._secrets(tmp_path, "GEMINI_API_KEY=AIzaROTATEDdonotprint\n")
        code, out = _run_trip(tmp_path, GOOD_ENV, SEXTANT_SECRETS_FILE=secrets)
        assert "AIzaROTATEDdonotprint" not in out, "the new key was printed"
        written = self._box_env(tmp_path)
        assert "GEMINI_API_KEY=AIzaROTATEDdonotprint" in written
        assert SENTINELS["GEMINI_API_KEY"] not in written, "the old key survived"
        assert "model key set" in out
        assert code == 0
