#!/usr/bin/env bash
# A VM trip, start to parked, as one command.
#
#   deploy/trip.sh                 # start, deploy, verify, PARK
#   deploy/trip.sh --keep-up       # same, but leave it running (say why out loud)
#   deploy/trip.sh --no-deploy     # start + verify + park, no rebuild
#
# Why this exists: on 2026-09-28 a trip ended waiting for the owner to rotate a
# key. The box stayed RUNNING for 125.5 hours and billed Rs703 against a
# Rs50-100/day cap. The work had taken twenty minutes and about Rs2.
#
# So parking is not a step at the end of a checklist -- a checklist is exactly
# what failed. It is an EXIT trap. The box is parked when this script returns,
# whether it succeeded, failed, or was interrupted with Ctrl-C. Leaving it up
# requires --keep-up, which is a thing you have to decide to type.
#
# Restarting costs about Rs2. Waiting cost Rs700. When a trip needs something
# only a human can do, park and come back.
set -euo pipefail

PROJECT="${VM_PROJECT:-agenticrag-rush}"
ZONE="${VM_ZONE:-us-central1-a}"
INSTANCE="${VM_INSTANCE:-agenticrag}"
REGION="${ZONE%-*}"
ADDRESS="${VM_ADDRESS:-agenticrag-ip}"
ACCESS_CONFIG="external-nat"
# Port 22 is open to exactly one /32, and a home ISP moves that address
# whenever it likes. Hence step 0. The URL is a knob so the check is testable
# and so a dead service can be swapped rather than worked around.
SSH_RULE="${VM_SSH_RULE:-agenticrag-ssh}"
MY_IP_URL="${VM_MY_IP_URL:-https://checkip.amazonaws.com}"
# Two minutes of waiting, as knobs: the offline gate exercises the path where
# ssh never answers, and it cannot spend two minutes doing it.
SSH_TRIES="${VM_SSH_TRIES:-24}"
SSH_SLEEP="${VM_SSH_SLEEP:-5}"
REMOTE="$INSTANCE.$ZONE.$PROJECT"
APP_DIR="agenticrag"
COMPOSE="docker compose -f docker-compose.prod.yml"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

KEEP_UP=0
DEPLOY=1
# Every check that compares something adds to this, and the script exits
# non-zero if it is not 0 at the end. It is initialised here, not in step 6:
# step 5 has a check of its own and step 6 runs after it, so a step-5 failure
# used to be zeroed before anything read it.
GATE_FAILURES=0
# Set the moment ssh answers. `--keep-up` means "leave it up, I am going to
# work on it" -- which presumes you can reach it. A box nobody can reach is
# not kept up, it is abandoned, and that is the Rs703 shape exactly.
SSH_UP=0
for arg in "$@"; do
  case "$arg" in
    --keep-up)   KEEP_UP=1 ;;
    --no-deploy) DEPLOY=0 ;;
    *) echo "unknown flag: $arg (use --keep-up | --no-deploy)" >&2; exit 2 ;;
  esac
done

GC=(gcloud compute --project="$PROJECT")
say()  { printf '\n== %s\n' "$1"; }
# Every compose command on the box prints `The "ubyP" variable is not set` four
# times: compose's YAML pass reading $ubyP out of the bcrypt BASIC_AUTH_HASH.
# The container gets the raw value through `env_file: format: raw`. Noise.
quiet() { grep -v 'ubyP' || true; }

started_at=$(date +%s)

# The instance's status, or `?` when the API could not be asked -- which is
# not "parked" and must never be read as it.
vm_state() {
  "${GC[@]}" instances describe "$INSTANCE" --zone="$ZONE" \
    --format='value(status)' 2>/dev/null || echo '?'
}

park() {
  local code=$?
  if [ "$KEEP_UP" = 1 ] && [ "${SSH_UP:-0}" = 1 ]; then
    say "NOT parking (--keep-up). The meter is running at ~Rs5.6/hour."
    echo "   park it with: $0 --no-deploy  (or gcloud compute instances stop $INSTANCE --zone=$ZONE --project=$PROJECT)"
    return $code
  fi
  # --keep-up was typed, but ssh never answered. On 2026-10-07 that combination
  # started the box, failed to reach it because the ssh firewall rule still
  # named a previous home address, and left it billing -- the exact 2026-09-28
  # failure, inside the script written to prevent it. "Leave it up so I can
  # work on it" is a sentence about a box you can reach.
  if [ "$KEEP_UP" = 1 ]; then
    say "parking anyway: --keep-up was typed but ssh never answered"
    echo "   there is nothing up to keep. restarting costs ~Rs2; waiting cost Rs703 once." >&2
  fi
  # Step 7 writes two documents into the production corpus. Taking them out
  # again is not a step at the end of step 7, for the same reason parking is
  # not a step at the end of the trip: the run that needs it most is the one
  # that died half way. It happens here, before the box is stopped, and it
  # reports what it removed rather than assuming.
  if [ "${PROBES_UPLOADED:-0}" = 1 ]; then
    say "removing the probe documents step 7 uploaded"
    # Same rule as the park below, for the same reason: documents left in the
    # production corpus are not something a 0 should be able to say happened.
    if ! forget_probes; then
      echo "   probe documents are still in the production corpus." >&2
      if [ "$code" = 0 ]; then code=1; fi
    fi
  fi

  say "parking $INSTANCE (this runs even on failure or Ctrl-C)"
  local state attempt
  # Twice. The readback below is only worth having once the dullest reason for
  # a bad one -- a single transient API error -- has been ruled out, and a
  # second stop costs nothing when the first one worked.
  for attempt in 1 2; do
    "${GC[@]}" instances stop "$INSTANCE" --zone="$ZONE" --quiet >/dev/null 2>&1 || true
    state=$(vm_state)
    case "$state" in TERMINATED|STOPPED) break ;; esac
    if [ "$attempt" = 1 ]; then printf '   stop did not take (%s), retrying\n' "$state"; fi
  done
  "${GC[@]}" instances delete-access-config "$INSTANCE" --zone="$ZONE" \
    --access-config-name="$ACCESS_CONFIG" >/dev/null 2>&1 || true
  # The reserved address bills ~Rs21/day on its own while nothing uses it.
  "${GC[@]}" addresses delete "$ADDRESS" --region="$REGION" --quiet >/dev/null 2>&1 || true
  local ips held=no
  "${GC[@]}" addresses describe "$ADDRESS" --region="$REGION" >/dev/null 2>&1 && held=yes
  ips=$("${GC[@]}" addresses list --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')
  printf '   %s is %s; reserved addresses: %s\n' "$INSTANCE" "$state" "$ips"
  local mins=$(( ($(date +%s) - started_at) / 60 ))
  printf '   trip took %s min; VM time ~Rs%s\n' "$mins" "$(( (mins * 56 + 599) / 600 ))"

  # Reading the state back and printing it is not the same as checking it.
  # This trap exists so that "the script returned" means "the box is parked",
  # and an exit code of 0 is how a caller -- a person, a shell, a later `&&` --
  # reads that claim. On 2026-09-28 the cost was not a wrong command; it was
  # that nobody looked at what happened after it. So a box that is still up,
  # or an address still reserved, takes the 0 away whatever the trip itself did.
  if [ "$state" != TERMINATED ] && [ "$state" != STOPPED ]; then
    echo "   STILL $state -- the meter is running at ~Rs5.6/hour (Rs134/day)." >&2
    echo "   stop it by hand, now:" >&2
    echo "   gcloud compute instances stop $INSTANCE --zone=$ZONE --project=$PROJECT" >&2
    if [ "$code" = 0 ]; then code=1; fi
  # elif, not a second if: deleting an address attached to a running instance
  # fails, so a box that would not stop reports as both. Fix the box first.
  elif [ "$held" = yes ]; then
    echo "   $ADDRESS is still reserved -- ~Rs21/day for an address nothing uses." >&2
    echo "   release it by hand:" >&2
    echo "   gcloud compute addresses delete $ADDRESS --region=$REGION --project=$PROJECT" >&2
    if [ "$code" = 0 ]; then code=1; fi
  fi
  return $code
}
# The filename both gate users upload. Distinctive on purpose: the cleanup
# finds the documents by scanning the store for it rather than reconstructing
# `upload:<owner>:<stem>` here, so `safe_owner()` changing how a name is spelled
# cannot leave documents behind that this script then reports as gone.
PROBE_STEM="sextant-trip-probe"
PROBES_UPLOADED=0

# Every probe id in the store, newline separated. Read off chroma's metadata:
# no embedder, no model, no cost.
probe_ids() {
  ssh "$REMOTE" "docker exec -i -e STEM=$PROBE_STEM $INSTANCE-api-1 python -" <<'PROBES' 2>/dev/null | tr -d '\r'
import os
import chromadb

stem = os.environ["STEM"]
path = os.environ.get("SEXTANT_CHROMA_DIR", "/data/chroma")
rows = chromadb.PersistentClient(path=path).get_collection("documents").get(
    include=["metadatas"]
)["metadatas"]
ids = {(m or {}).get("document_id") for m in rows} - {None}
for doc_id in sorted(i for i in ids if i.endswith(":" + stem)):
    print(doc_id)
PROBES
}

forget_probes() {
  local ids left
  ids=$(probe_ids)
  if [ -z "$ids" ]; then
    echo "   nothing to remove"
    return 0
  fi
  echo "$ids" | sed 's/^/   removing /'
  # shellcheck disable=SC2086
  ssh "$REMOTE" "docker exec $INSTANCE-api-1 sextant-forget $(echo $ids) --yes" >/dev/null 2>&1 || true
  left=$(probe_ids)
  if [ -n "$left" ]; then
    echo "$left" | sed 's/^/   STILL THERE: /' >&2
    echo "   remove by hand: ssh $REMOTE \"docker exec $INSTANCE-api-1 sextant-forget <id> --yes\"" >&2
    return 1
  fi
  echo "   the corpus is back to what it was"
  return 0
}

# Whether port 22 is open to *this* machine, which is a different question from
# whether the box is up. Both halves are readable from the laptop for nothing:
# the rule's source ranges, and this machine's public address. On 2026-10-07
# neither was read -- the trip started the box, waited two minutes for an ssh
# that could not arrive, and reported "ssh never came up", which names the
# symptom and not one thing about the cause. The cause was a /32 from a
# previous day.
#
# Three outcomes, not two: open, shut, or could-not-tell. A flaky address
# service must not be able to stop a trip, so could-not-tell proceeds and says
# so -- the ssh wait is still there to catch what this missed.
ssh_door() {
  local mine allowed verdict=0
  mine=$(curl -s --max-time 15 "$MY_IP_URL" 2>/dev/null | tr -d '[:space:]' || true)
  if [ -z "$mine" ]; then
    echo "   could not learn this machine's address -- door not checked" >&2
    return 0
  fi
  allowed=$("${GC[@]}" firewall-rules describe "$SSH_RULE" \
    --format='value(sourceRanges.list())' 2>/dev/null | tr -d '[:space:]' || true)
  if [ -z "$allowed" ]; then
    echo "   no source ranges readable on $SSH_RULE -- door not checked" >&2
    return 0
  fi
  # Containment, not string equality: the rule is allowed to be a wider CIDR
  # than one address, and comparing the text would call an open door shut.
  MINE="$mine" ALLOWED="$allowed" python3 -c '
import ipaddress
import os
import sys

try:
    mine = ipaddress.ip_address(os.environ["MINE"])
    nets = [
        ipaddress.ip_network(text, strict=False)
        for text in os.environ["ALLOWED"].split(",")
        if text
    ]
except ValueError:
    sys.exit(2)
sys.exit(0 if any(mine in net for net in nets) else 1)
' || verdict=$?
  case "$verdict" in
    0) printf '   port 22 is open to %s\n' "$mine"; return 0 ;;
    2) echo "   addresses did not parse -- door not checked" >&2; return 0 ;;
  esac
  echo "   port 22 is NOT open to this machine." >&2
  printf '   %s allows %s. this machine is %s.\n' "$SSH_RULE" "$allowed" "$mine" >&2
  echo "   nothing has been started, so this has cost nothing. open the door:" >&2
  printf '   gcloud compute firewall-rules update %s --project=%s --source-ranges=%s/32\n' \
    "$SSH_RULE" "$PROJECT" "$mine" >&2
  return 1
}

trap park EXIT

# Before step 1, because step 1 is where the meter starts. A shut door found
# here costs Rs0; found after the start it costs Rs2 and a second trip.
say "0 - the ssh door, before the meter starts"
ssh_door || exit 1

say "1 - starting $INSTANCE (bills ~Rs5.6/hour until parked)"
if [ "$("${GC[@]}" instances describe "$INSTANCE" --zone="$ZONE" --format='value(status)')" != "RUNNING" ]; then
  "${GC[@]}" addresses describe "$ADDRESS" --region="$REGION" >/dev/null 2>&1 \
    || "${GC[@]}" addresses create "$ADDRESS" --region="$REGION" >/dev/null
  # --address takes the literal IP, not the name of the reservation.
  "${GC[@]}" instances add-access-config "$INSTANCE" --zone="$ZONE" \
    --access-config-name="$ACCESS_CONFIG" \
    --address="$("${GC[@]}" addresses describe "$ADDRESS" --region="$REGION" --format='get(address)')" \
    >/dev/null 2>&1 || true
  "${GC[@]}" instances start "$INSTANCE" --zone="$ZONE" --quiet >/dev/null
fi
"${GC[@]}" config-ssh >/dev/null 2>&1
for i in $(seq 1 "$SSH_TRIES"); do
  ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE" true 2>/dev/null && break
  printf '   waiting for ssh (%s)\n' "$i"; sleep "$SSH_SLEEP"
done
# ConnectTimeout, because without one this last attempt inherits the TCP
# default and hangs for minutes after the loop has already given up -- which
# is how a dead trip sat there looking busy on 2026-10-07.
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE" true; then
  echo "ssh never came up -- step 0 said the door was open, so look at the box" >&2
  exit 1
fi
SSH_UP=1
echo "   up"

if [ "$DEPLOY" = 1 ]; then
  say "2 - the box's .env, names only (values are never printed)"
  # [A-Z0-9_] and not [A-Z_]: the second and third gate users are spelled
  # BASIC_AUTH_USER_2 / _3, and a class without digits silently dropped exactly
  # the variables this trip exists to add.
  ssh "$REMOTE" "cd $APP_DIR && sed -n 's/^\([A-Z0-9_]*\)=.*/  \1/p' .env"
  # 0.8.1 removed the AGENTICRAG_ fallback. A container built from this tree
  # against a pre-rename .env runs with no budget cap and no CORS allowlist, so
  # this check is a hard stop, not a warning.
  if ssh "$REMOTE" "grep -q '^AGENTICRAG_' $APP_DIR/.env"; then
    echo "   the box's .env still has AGENTICRAG_* names -- rewrite it BEFORE deploying:" >&2
    echo "   ssh $REMOTE \"cd $APP_DIR && cp -a .env .env.bak && sed -i 's/^AGENTICRAG_/SEXTANT_/' .env\"" >&2
    exit 1
  fi
  echo "   no pre-rename names"

  # 0.8.3 put `header_up X-Sextant-User {http.auth.user.id}` in the Caddyfile,
  # and Caddy has no conditionals: it forwards the authenticated name on every
  # proxied request whether or not the app can verify it came from Caddy. With
  # SEXTANT_PROXY_SECRET empty the app sees a name it cannot trust and refuses
  # -- every request, not some. Deploying this tree without it takes the box
  # down, so this is the same kind of hard stop as the one above.
  if ! ssh "$REMOTE" "grep -q '^SEXTANT_PROXY_SECRET=..*' $APP_DIR/.env"; then
    echo "   SEXTANT_PROXY_SECRET is missing or empty -- every request would 403." >&2
    echo "   generate it ON THE BOX so the value never leaves it:" >&2
    echo "   ssh $REMOTE \"cd $APP_DIR && printf 'SEXTANT_PROXY_SECRET=%s\\n' \\\$(openssl rand -hex 32) >> .env\"" >&2
    exit 1
  fi
  echo "   proxy secret set"

  # Not hard stops -- the box runs fine without any of these. They are printed
  # because each one silently changes what the trip can prove: isolation needs
  # two names at the gate, answers need a key, and a share needs configuring
  # once there is more than one person to share between.
  slots=$(ssh "$REMOTE" "grep -cE '^BASIC_AUTH_HASH(_[23])?=..*' $APP_DIR/.env || true")
  echo "   basic_auth users: $slots (two are needed to prove isolation end to end)"
  if ssh "$REMOTE" "grep -q '^GEMINI_API_KEY=..*' $APP_DIR/.env"; then
    echo "   model key set"
  else
    echo "   GEMINI_API_KEY is empty -- retrieval will work, answers will not"
  fi
  if ssh "$REMOTE" "grep -q '^SEXTANT_DAILY_BUDGET_SHARE=..*' $APP_DIR/.env"; then
    echo "   per-owner share set"
  else
    echo "   no SEXTANT_DAILY_BUDGET_SHARE -- the global cap alone (right for one user)"
  fi
  echo "   safe to build"

  say "3 - shipping the working tree"
  # tar over ssh, not rsync: macOS ships openrsync, which mangles a dotted
  # host:path into a LOCAL directory and silently syncs nothing.
  #
  # Which flags keep macOS metadata out of the tarball depends on which tar
  # this is. BSD tar (macOS) has all three; GNU tar (Linux, and CI) has only
  # --no-xattrs and *exits* on an unknown flag rather than ignoring it. So this
  # line could only ever run on a Mac -- and the offline run of this whole
  # script in the gate therefore could not run on Linux at all. Nobody found
  # out, because CI failed at the type check before it reached the tests.
  if tar --version 2>/dev/null | head -1 | grep -qi gnu; then
    TAR_FLAGS=(--no-xattrs)
  else
    TAR_FLAGS=(--no-xattrs --no-fflags --no-mac-metadata)
  fi
  tar -czf - "${TAR_FLAGS[@]}" \
    --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
    --exclude 'frontend/dist' --exclude '__pycache__' \
    --exclude '.pytest_cache' --exclude '.mypy_cache' --exclude '.ruff_cache' \
    --exclude 'chroma_db' --exclude '.env' --exclude 'frontend/.env.local' \
    --exclude 'graphify-out' \
    -C "$REPO" . \
  | ssh "$REMOTE" "set -e; cd $APP_DIR
      find . -mindepth 1 -maxdepth 1 ! -name '.env*' ! -name set-secrets.sh -exec rm -rf {} +
      tar -xzf - && echo '   synced' \$(find . -type f | wc -l) 'files'"

  say "4 - build and start"
  ssh "$REMOTE" "cd $APP_DIR && $COMPOSE up -d --build" 2>&1 | quiet | tail -12
fi

say "5 - verify"

# Until 2026-10-07 this step printed six results and judged one. Everything
# below is now compared, because a line on a terminal is not a check: the
# container table showed whatever compose said and nothing read it, so a box
# whose Caddy had died reported a clean step 5 -- and step 6, which exists for
# exactly that failure, only runs when the operator exported credentials.
echo "   containers:"
ps_out=$(ssh "$REMOTE" "cd $APP_DIR && $COMPOSE ps --format 'table {{.Name}}\t{{.Status}}'" 2>&1 | quiet)
printf '%s\n' "$ps_out" | sed 's/^/     /'
for svc in api caddy; do
  line=$(printf '%s\n' "$ps_out" | grep "^$INSTANCE-$svc-1[[:space:]]" || true)
  case "$line" in
    *Up*) ;;
    "")
      echo "     $svc is not in the table at all" >&2
      GATE_FAILURES=$((GATE_FAILURES + 1)) ;;
    *)
      echo "     $svc is not Up: $line" >&2
      GATE_FAILURES=$((GATE_FAILURES + 1)) ;;
  esac
done

# The api container does not publish 8000 to the host; curl over ssh gets
# HTTP 000. Health goes through docker exec.
echo "   health:"
health=$(ssh "$REMOTE" "docker exec $INSTANCE-api-1 curl -s --max-time 30 http://localhost:8000/health" 2>&1 | quiet)
# `model` is the one the key rotation turns on, and it was printed and never
# read: a box with a bad key answers model=False and the trip said shipped.
if ! printf '%s' "$health" | python3 -c '
import json
import sys

try:
    d = json.load(sys.stdin)
except Exception:
    print("     could not read /health -- the box did not answer with json")
    raise SystemExit(1)
b = d.get("budget") or {}
print(
    "     status=%s mcp=%s model=%s budget_usd=%s durable=%s"
    % (d.get("status"), d.get("mcp_connected"), d.get("model_configured"),
       b.get("budget_usd"), b.get("durable"))
)
wrong = []
if d.get("status") != "healthy":
    wrong.append("status is %s" % d.get("status"))
if not d.get("mcp_connected"):
    wrong.append("the tool server is not connected")
if not d.get("model_configured"):
    wrong.append("no model key resolved, so the box cannot answer anything")
if not b.get("budget_usd"):
    wrong.append("the daily cap is 0, so the box is uncapped")
# Three outcomes. False means the box cannot write its spend ledger, so the cap
# restarts with the container and is a limit per process, not per day. Absent
# means the box predates the ledger -- worth saying, not worth failing a trip.
if b.get("durable") is False:
    wrong.append("the spend ledger is not writable, so the cap resets on restart")
elif b.get("budget_usd") and "durable" not in b:
    print("     (this box predates the spend ledger; the cap resets on restart)")
if wrong:
    print("     NOT RIGHT: %s" % "; ".join(wrong), file=sys.stderr)
    raise SystemExit(1)
'; then
  GATE_FAILURES=$((GATE_FAILURES + 1))
fi

echo "   stats:"
stats=$(ssh "$REMOTE" "docker exec $INSTANCE-api-1 curl -s --max-time 30 http://localhost:8000/stats" 2>&1 | quiet)
# A floor, not a number: the corpus is re-ingested by hand and what it should
# hold is not this script's business, but an empty store after a deploy is.
if ! printf '%s' "$stats" | python3 -c '
import json
import sys

try:
    d = json.load(sys.stdin)
except Exception:
    print("     could not read /stats -- the box did not answer with json")
    raise SystemExit(1)
print(
    "     %s chunks / %s documents / %s summaries at %s"
    % (d.get("collection_size"), d.get("documents"), d.get("summaries", 0),
       d.get("persist_dir"))
)
if not d.get("documents") or not d.get("collection_size"):
    print("     NOT RIGHT: the store is empty", file=sys.stderr)
    raise SystemExit(1)
'; then
  GATE_FAILURES=$((GATE_FAILURES + 1))
fi

echo "   stale env names in the log (want none):"
# A leftover AGENTICRAG_* name is not read since 0.8.1, so the container runs
# with its budget cap and CORS allowlist at defaults. Printing the names it
# found and carrying on is how an uncapped box ships.
stale=$(ssh "$REMOTE" "cd $APP_DIR && $COMPOSE logs api --tail=120" 2>&1 | quiet \
  | grep -i 'AGENTICRAG_' || true)
if [ -n "$stale" ]; then
  printf '%s\n' "$stale" | sed 's/^/     /' >&2
  echo "     NOT RIGHT: the box is running with defaults for those" >&2
  GATE_FAILURES=$((GATE_FAILURES + 1))
else
  echo "     clean"
fi

# A name is only worth anything if a client cannot simply type it. Going
# straight at the api container skips Caddy, so this is exactly the forged
# case: a header with no proof beside it. 403 is the pass.
echo "   a name the proxy did not vouch for:"
code=$(ssh "$REMOTE" "docker exec $INSTANCE-api-1 curl -s -o /dev/null -w '%{http_code}' --max-time 30 -H 'X-Sextant-User: forged' http://localhost:8000/health" 2>/dev/null | tr -d '\r')
if [ "$code" = 403 ]; then
  echo "     refused ($code)"
elif [ "$DEPLOY" = 1 ]; then
  # A deploy just put the 0.8.3+ middleware on the box and the preflight has
  # already refused to build without SEXTANT_PROXY_SECRET, so a name the proxy
  # did not vouch for has to be refused. Until 2026-10-07 this line printed
  # and the trip went on to exit 0 -- compared, reported, and not counted,
  # which is the same defect as items 5 to 9 one more time.
  echo "     got $code, expected 403 -- a client can name itself" >&2
  GATE_FAILURES=$((GATE_FAILURES + 1))
else
  # No deploy happened, so this is whatever the box was already running. On a
  # pre-0.8.3 box a 200 is the correct answer and not a failure -- but it is
  # also not a pass, and saying so is the difference between a known gap and
  # an unread line.
  echo "     got $code, expected 403 -- a client can name itself" >&2
  echo "     (--no-deploy: this is the box as it stands, not a result of this run)" >&2
fi

# 0.8.2 namespaced upload ids as `upload:<owner>:<stem>`. Anything still
# spelled `upload:<stem>` predates it and belongs to nobody in particular --
# a documented one-way break this trip is meant to confirm the box does not
# have. Read straight off chroma's metadata: no embedder, no model, no cost.
echo "   document ids:"
ssh "$REMOTE" "docker exec -i $INSTANCE-api-1 python -" <<'AUDIT' 2>&1 | quiet || echo "     could not audit (not fatal)"
import os
import chromadb

path = os.environ.get("SEXTANT_CHROMA_DIR", "/data/chroma")
rows = chromadb.PersistentClient(path=path).get_collection("documents").get(
    include=["metadatas"]
)["metadatas"]
ids = sorted({(m or {}).get("document_id") for m in rows} - {None})
stale = [i for i in ids if i.startswith("upload:") and i.count(":") < 2]
owners = sorted({i.split(":")[1] for i in ids if i.startswith("upload:") and i.count(":") >= 2})
print("     %d documents; owners with uploads: %s" % (len(ids), ", ".join(owners) or "none"))
print("     pre-0.8.2 upload ids: %s" % (", ".join(stale) if stale else "none"))
AUDIT

# ---------------------------------------------------------------------------
# 6 - the gate, from outside
#
# Everything above went through `docker exec` at localhost:8000 -- inside the
# box, behind Caddy. So until now this trip never once touched the thing it
# exists to deploy. A box whose Caddy is misconfigured, or not running at all,
# passes every check in step 5 and reports green.
#
# These run from here, over the public URL. They need credentials, which only
# you have, so export them before the trip and they run:
#
#   export SEXTANT_TRIP_AUTH='ada:her-password'
#   export SEXTANT_TRIP_AUTH_2='grace:her-password'
#
# Unset, the step says what it could not prove rather than passing quietly.
# Nothing here writes to the corpus and nothing calls the model: every request
# is a GET /health, so this costs nothing beyond the seconds it takes.
#
# What a 200 means in checks 4 and 5 is worth stating, because it reads
# backwards. `header_up` in Caddy is a *set*: the client's own
# X-Sextant-Proxy-Auth is replaced by the real secret before the app sees it.
# So a request that forges the proof and still succeeds is Caddy doing its job.
# If it 403s, Caddy appended instead of replacing, or is not in the path --
# and then anyone can send the header themselves.
# ---------------------------------------------------------------------------
say "6 - the gate, from outside"
# The URL is read off the box rather than hardcoded: this repo is public.
URL=$(ssh "$REMOTE" "cd $APP_DIR && sed -n 's/^PUBLIC_URL=//p' .env" 2>/dev/null | tr -d '\r')

# Credentials go through a config file on a pipe, never argv, so they are not
# in `ps` output on this machine while the trip runs.
# `|| true` on both: a refused connection or a DNS failure exits curl non-zero,
# and `set -o pipefail` would make that the script's problem rather than the
# check's. It is the check's -- curl still prints 000, which is not the code
# wanted, so the box being unreachable counts as a gate failure like any other.
gate() {
  local auth="$1"; shift
  if [ -n "$auth" ]; then
    curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
      --config <(printf 'user = "%s"\n' "$auth") "$@" "$URL/health" 2>/dev/null \
      | tr -d '\r' || true
  else
    curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$@" "$URL/health" 2>/dev/null \
      | tr -d '\r' || true
  fi
}

# A check that only prints is the defect item 5 fixed, so each one counts.
expect() {
  local what="$1" want="$2" got="$3"
  if [ "$got" = "$want" ]; then
    printf '   %-44s %s\n' "$what" "$got"
  else
    printf '   %-44s got %s, wanted %s\n' "$what" "$got" "$want" >&2
    GATE_FAILURES=$((GATE_FAILURES + 1))
  fi
}

if [ -z "$URL" ]; then
  echo "   no PUBLIC_URL on the box -- the gate is unproven" >&2
  GATE_FAILURES=$((GATE_FAILURES + 1))
elif [ -z "${SEXTANT_TRIP_AUTH:-}" ]; then
  echo "   SEXTANT_TRIP_AUTH unset -- nothing here ran. The gate is unproven:"
  echo "   every check above was inside the box, behind Caddy."
else
  expect "no credentials"                401 "$(gate '')"
  expect "wrong password"                401 "$(gate 'nobody:wrong')"
  expect "a real user"                   200 "$(gate "$SEXTANT_TRIP_AUTH")"
  # Caddy sets the proof header, so a client's own copy is overwritten and the
  # request still succeeds. A 403 here means it is appending, or absent.
  expect "a forged proof is overwritten"  200 \
    "$(gate "$SEXTANT_TRIP_AUTH" -H 'X-Sextant-Proxy-Auth: forged')"
  # And naming yourself is not a way in: the gate refuses before the app looks.
  expect "naming yourself, no password"  401 \
    "$(gate '' -H 'X-Sextant-User: admin' -H 'X-Sextant-Proxy-Auth: forged')"
  if [ -n "${SEXTANT_TRIP_AUTH_2:-}" ]; then
    expect "a second user"               200 "$(gate "$SEXTANT_TRIP_AUTH_2")"
  else
    echo "   SEXTANT_TRIP_AUTH_2 unset -- one name at the gate, so isolation is unproven"
  fi
fi

# ---------------------------------------------------------------------------
# 7 - isolation, from outside
#
# Step 6 proves the gate. Every check in it is a read, so it says nothing about
# what is behind the gate. This is milestone 21's pre-registered success
# criterion, run by the script instead of by hand:
#
#   two different basic_auth users each upload a file of the same name, both
#   survive, each sees their own and not the other's, and a client-supplied
#   X-Sextant-User is refused.
#
# Only runs with two gate users exported, which is already a deliberate act.
# It is the one part of the trip that WRITES: two small text files, each
# costing a summary (~$0.003) when a model key is configured. They are removed
# in the EXIT trap, not at the end of this step, because the run that most
# needs the cleanup is the one that died half way through.
# ---------------------------------------------------------------------------
say "7 - isolation, from outside"

# `documents` off the scoped /stats -- the same number the asker's own UI shows.
# -1 on any failure, which is never a count anything expects, so a broken read
# fails the check instead of quietly matching.
stats_docs() {
  local auth="$1"; shift
  # The curl is braced with `|| true` so an unreachable box is not `pipefail`'s
  # problem, and python is the only thing that prints -- otherwise a failure
  # produced the fallback twice and the count came out as two lines.
  { curl -s --max-time 60 --config <(printf 'user = "%s"\n' "$auth") "$@" \
      "$URL/stats" 2>/dev/null || true; } \
    | python3 -c 'import json, sys
try:
    print(json.load(sys.stdin)["documents"])
except Exception:
    print(-1)'
}

# `/upload` answers 200 with `"success": false` when the file was unreadable,
# the tool was unavailable, or the ingest failed -- the status code says the
# request arrived, not that anything was stored. Checking the code alone makes
# "the user uploaded a file" a check that passes when they did not, and the
# only symptom would be the count assertions below failing for no stated
# reason. So the verdict comes out of the body, and a refusal says why.
upload_probe() {
  local auth="$1" body="$2" dir file answer code
  dir=$(mktemp -d)
  file="$dir/$PROBE_STEM.txt"
  printf '%s\n' "$body" > "$file"
  answer=$({ curl -s -w '\n%{http_code}' --max-time 120 \
      --config <(printf 'user = "%s"\n' "$auth") -F "files=@$file" \
      "$URL/upload" 2>/dev/null || true; })
  rm -rf "$dir"
  code=$(printf '%s' "$answer" | tail -1 | tr -d '\r')
  printf '%s' "$answer" | sed '$d' | CODE="$code" python3 -c 'import json, os, sys

code = os.environ["CODE"]
if code != "200":
    print("http %s" % (code or "000"))
    raise SystemExit
try:
    body = json.load(sys.stdin)
except Exception:
    print("200 with an unreadable body")
    raise SystemExit
if not body.get("success"):
    print("refused: %s" % (body.get("error") or "no reason given"))
    raise SystemExit
print("stored %s" % body.get("documents_added", 0))'
}

if [ -z "$URL" ] || [ -z "${SEXTANT_TRIP_AUTH:-}" ] || [ -z "${SEXTANT_TRIP_AUTH_2:-}" ]; then
  echo "   needs both gate users exported -- isolation is unproven."
  echo "   this is the half of the criterion that is otherwise done by hand."
else
  name_b="${SEXTANT_TRIP_AUTH_2%%:*}"
  a0=$(stats_docs "$SEXTANT_TRIP_AUTH")
  b0=$(stats_docs "$SEXTANT_TRIP_AUTH_2")
  printf '   starting from: first user %s documents, second user %s\n' "$a0" "$b0"

  # From here on the corpus has been written to, so the trap has work to do
  # whatever happens next.
  PROBES_UPLOADED=1
  expect "first user uploads $PROBE_STEM.txt" "stored 1" \
    "$(upload_probe "$SEXTANT_TRIP_AUTH" 'Probe from the first gate user.')"
  expect "they see one more"            "$((a0 + 1))" "$(stats_docs "$SEXTANT_TRIP_AUTH")"
  expect "the second user sees nothing new" "$b0"     "$(stats_docs "$SEXTANT_TRIP_AUTH_2")"

  # The forged name goes HERE, in the only window where the two users disagree.
  # After the second upload both counts are a0+1 and b0+1, which for two users
  # starting level are the same number -- and a check whose two sides agree
  # cannot fail. That is how the first draft of this step passed against a proxy
  # that forwarded the client's name.
  if [ "$((a0 + 1))" != "$b0" ]; then
    expect "naming yourself the other user" "$((a0 + 1))" \
      "$(stats_docs "$SEXTANT_TRIP_AUTH" -H "X-Sextant-User: $name_b")"
  else
    echo "   the two users' counts coincide here -- forged name not provable" >&2
    GATE_FAILURES=$((GATE_FAILURES + 1))
  fi

  expect "second user uploads the same filename" "stored 1" \
    "$(upload_probe "$SEXTANT_TRIP_AUTH_2" 'Probe from the second gate user.')"
  expect "they see one more"            "$((b0 + 1))" "$(stats_docs "$SEXTANT_TRIP_AUTH_2")"
  # The one that matters. Before 0.8.2 the id was `upload:<stem>`, so the second
  # upload replaced the first and this number went back to $a0.
  expect "the first user's copy survived" "$((a0 + 1))" "$(stats_docs "$SEXTANT_TRIP_AUTH")"

  # What /stats counts is what the asker can see. This is what is actually in
  # the store: two ids, same stem, different owners.
  found=$(probe_ids | wc -l | tr -d ' ')
  expect "probe documents in the store" 2 "$found"
  owners=$(probe_ids | awk -F: '{print $2}' | sort -u | wc -l | tr -d ' ')
  expect "owned by distinct names" 2 "$owners"
fi

say "done - the trap parks the box next"
# The park happens either way -- it is a trap, not a step. But a box whose
# gate did not hold is not a successful trip, and 0 would say it was.
if [ "${GATE_FAILURES:-0}" != 0 ]; then
  echo "$GATE_FAILURES check(s) failed -- the box is deployed but not proven." >&2
  exit 1
fi
