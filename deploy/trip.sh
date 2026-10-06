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
REMOTE="$INSTANCE.$ZONE.$PROJECT"
APP_DIR="agenticrag"
COMPOSE="docker compose -f docker-compose.prod.yml"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

KEEP_UP=0
DEPLOY=1
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

park() {
  local code=$?
  if [ "$KEEP_UP" = 1 ]; then
    say "NOT parking (--keep-up). The meter is running at ~Rs5.6/hour."
    echo "   park it with: $0 --no-deploy  (or gcloud compute instances stop $INSTANCE --zone=$ZONE --project=$PROJECT)"
    return $code
  fi
  say "parking $INSTANCE (this runs even on failure or Ctrl-C)"
  "${GC[@]}" instances stop "$INSTANCE" --zone="$ZONE" --quiet >/dev/null 2>&1 || true
  "${GC[@]}" instances delete-access-config "$INSTANCE" --zone="$ZONE" \
    --access-config-name="$ACCESS_CONFIG" >/dev/null 2>&1 || true
  # The reserved address bills ~Rs21/day on its own while nothing uses it.
  "${GC[@]}" addresses delete "$ADDRESS" --region="$REGION" --quiet >/dev/null 2>&1 || true
  local state ips
  state=$("${GC[@]}" instances describe "$INSTANCE" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo '?')
  ips=$("${GC[@]}" addresses list --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')
  printf '   %s is %s; reserved addresses: %s\n' "$INSTANCE" "$state" "$ips"
  local mins=$(( ($(date +%s) - started_at) / 60 ))
  printf '   trip took %s min; VM time ~Rs%s\n' "$mins" "$(( (mins * 56 + 599) / 600 ))"
  return $code
}
trap park EXIT

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
for i in $(seq 1 24); do
  ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE" true 2>/dev/null && break
  printf '   waiting for ssh (%s)\n' "$i"; sleep 5
done
ssh -o BatchMode=yes "$REMOTE" true || { echo "ssh never came up"; exit 1; }
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
  tar -czf - --no-xattrs --no-fflags --no-mac-metadata \
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
ssh "$REMOTE" "cd $APP_DIR && $COMPOSE ps --format 'table {{.Name}}\t{{.Status}}'" 2>&1 | quiet
# The api container does not publish 8000 to the host; curl over ssh gets
# HTTP 000. Health goes through docker exec.
echo "   health:"
ssh "$REMOTE" "docker exec $INSTANCE-api-1 curl -s --max-time 30 http://localhost:8000/health" 2>&1 | quiet \
  | python3 -c 'import json, sys
d = json.load(sys.stdin)
b = d["budget"]
print("     status=%s mcp=%s model=%s budget_usd=%s"
      % (d["status"], d["mcp_connected"], d["model_configured"], b["budget_usd"]))
sys.exit(0 if b["budget_usd"] else 1)' \
  || { echo "     BUDGET CAP IS 0 -- the box is uncapped, check SEXTANT_DAILY_BUDGET_USD in its .env" >&2; }
echo "   stats:"
ssh "$REMOTE" "docker exec $INSTANCE-api-1 curl -s --max-time 30 http://localhost:8000/stats" 2>&1 | quiet \
  | python3 -c 'import json, sys
d = json.load(sys.stdin)
print("     %s chunks / %s documents / %s summaries at %s"
      % (d["collection_size"], d["documents"], d.get("summaries", 0), d["persist_dir"]))'
echo "   stale env names in the log (want none):"
ssh "$REMOTE" "cd $APP_DIR && $COMPOSE logs api --tail=120" 2>&1 | quiet | grep -i 'AGENTICRAG_' || echo "     clean"

# A name is only worth anything if a client cannot simply type it. Going
# straight at the api container skips Caddy, so this is exactly the forged
# case: a header with no proof beside it. 403 is the pass.
echo "   a name the proxy did not vouch for:"
code=$(ssh "$REMOTE" "docker exec $INSTANCE-api-1 curl -s -o /dev/null -w '%{http_code}' --max-time 30 -H 'X-Sextant-User: forged' http://localhost:8000/health" 2>/dev/null | tr -d '\r')
if [ "$code" = 403 ]; then
  echo "     refused ($code)"
else
  echo "     got $code, expected 403 -- a client can name itself" >&2
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

say "done - the trap parks the box next"
