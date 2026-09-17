#!/usr/bin/env bash
# Push the local working tree to the VM and (re)build the stack there.
#
# We ship the tree rather than `git clone` on purpose: the git remote is not
# the owner's account, so nothing here ever pushes to it. The box builds from
# exactly what is on this laptop.
#
# Host can be an ssh alias; `gcloud compute config-ssh` writes one per VM
# (agenticrag.us-central1-a.<project>) so plain ssh/tar work without gcloud
# in the loop.
#
# Usage:
#   deploy/deploy.sh vm-host            # preflight + ship + build + up
#   deploy/deploy.sh vm-host preflight  # just check the box is ready
#   deploy/deploy.sh vm-host logs       # tail the stack
#   deploy/deploy.sh vm-host down       # stop the stack (containers only)
#   deploy/deploy.sh vm-host status     # is the VM up? what does it cost?
#   deploy/deploy.sh vm-host stop       # park the VM (disks + images kept)
#   deploy/deploy.sh vm-host start      # unpark it -- asks first, it costs
#
# status/stop/start go through gcloud, not ssh. The instance, zone and
# project are read from the config-ssh alias (`<instance>.<zone>.<project>`)
# or from VM_INSTANCE / VM_ZONE / VM_PROJECT in the environment.
#
# The VM must already have: Docker + compose plugin, /data/chroma on the
# attached persistent disk, and deploy/.env filled in at ~/agenticrag/.env
# (see deploy/env.example). This script never creates or overwrites that .env.
set -euo pipefail

REMOTE="${1:?usage: deploy.sh host [up|preflight|logs|down|status|stop|start]}"
CMD="${2:-up}"
APP_DIR="agenticrag"                       # ~/agenticrag on the VM
COMPOSE="docker compose -f docker-compose.prod.yml"
# What a running e2-standard-2 costs, so `start` can say it out loud. Update
# if the machine type changes; the number is only for the prompt.
VM_COST_PER_HOUR="~INR 5.6 (~USD 0.067)"

cd "$(dirname "$0")/.."                     # repo root

# Resolve the gcloud target for the lifecycle commands. The config-ssh alias
# already carries everything: `agenticrag.us-central1-a.my-project`.
vm_target() {
  INSTANCE="${VM_INSTANCE:-}"; ZONE="${VM_ZONE:-}"; PROJECT="${VM_PROJECT:-}"
  if [ -z "$INSTANCE" ]; then
    host="${REMOTE#*@}"
    IFS=. read -r INSTANCE ZONE PROJECT <<<"$host"
  fi
  if [ -z "$INSTANCE" ] || [ -z "$ZONE" ] || [ -z "$PROJECT" ]; then
    echo "cannot tell instance/zone/project from '$REMOTE';" \
         "set VM_INSTANCE, VM_ZONE and VM_PROJECT" >&2
    exit 2
  fi
  GC=(gcloud compute instances --project="$PROJECT")
}

vm_status() {
  "${GC[@]}" describe "$INSTANCE" --zone="$ZONE" \
    --format='value(status,machineType.basename(),networkInterfaces[0].accessConfigs[0].natIP)'
}

case "$CMD" in
  status)
    vm_target
    read -r state type ip <<<"$(vm_status)"
    echo "$INSTANCE ($type, $ZONE): $state${ip:+  ip $ip}"
    case "$state" in
      RUNNING)    echo "   billing: VM $VM_COST_PER_HOUR/hour + disks + IP" ;;
      TERMINATED) echo "   billing: disks + reserved IP only (VM meter off)" ;;
    esac
    ;;
  stop)
    vm_target
    read -r state _ _ <<<"$(vm_status)"
    if [ "$state" = "TERMINATED" ]; then echo "$INSTANCE already stopped"; exit 0; fi
    echo ">> stopping $INSTANCE (containers restart on their own at next start) ..."
    "${GC[@]}" stop "$INSTANCE" --zone="$ZONE" --quiet
    echo ">> stopped. Disks, images and .env are kept; see README on the external IP."
    ;;
  start)
    vm_target
    read -r state _ _ <<<"$(vm_status)"
    if [ "$state" = "RUNNING" ]; then echo "$INSTANCE already running"; exit 0; fi
    # The static IP was released on 2026-09-17 (it billed ~₹640/month while the
    # VM sat stopped). Starting a VM with no external address gives a box
    # nothing can reach, so refuse until one is attached -- and do not attach
    # one here, because reserving an address is itself a meter.
    if [ -z "$("${GC[@]}" describe "$INSTANCE" --zone="$ZONE" \
        --format='value(networkInterfaces[0].accessConfigs[0].name)' 2>/dev/null)" ]; then
      echo "$INSTANCE has no external IP (released to save cost). Reattach one first:"
      echo "  gcloud compute addresses create agenticrag-ip --region=\${ZONE%-*} --project=$PROJECT"
      echo "  gcloud compute instances add-access-config $INSTANCE --zone=$ZONE --project=$PROJECT \\"
      echo "    --access-config-name=external-nat --address=\$(gcloud compute addresses describe agenticrag-ip --region=\${ZONE%-*} --project=$PROJECT --format='get(address)')"
      echo "then point DNS at the new address (deploy/README.md B3) and run start again."
      exit 1
    fi
    # This is the one command here that turns a meter on. Say so, and wait.
    echo "Starting $INSTANCE bills $VM_COST_PER_HOUR per hour until it is stopped again."
    if [ "${3:-}" != "--yes" ]; then
      read -r -p "Start it? [y/N] " answer
      case "$answer" in y|Y|yes) ;; *) echo "not started"; exit 1 ;; esac
    fi
    "${GC[@]}" start "$INSTANCE" --zone="$ZONE" --quiet
    echo ">> started; waiting for ssh ..."
    for _ in $(seq 1 30); do
      ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE" true 2>/dev/null && break
      sleep 5
    done
    read -r _ _ ip <<<"$(vm_status)"
    echo ">> up at ${ip:-?}. The stack restarts by itself (restart: unless-stopped)."
    echo ">> if the tree changed:  deploy/deploy.sh $REMOTE"
    echo ">> when finished:        deploy/deploy.sh $REMOTE stop"
    ;;
  logs)
    exec ssh -t "$REMOTE" "cd $APP_DIR && $COMPOSE logs -f --tail=200"
    ;;
  down)
    exec ssh -t "$REMOTE" "cd $APP_DIR && $COMPOSE down"
    ;;
  preflight|up)
    # Check the box BEFORE spending twenty minutes building torch. Every one of
    # these has a failure mode that only shows up at the very end: a mangled
    # hash rejects every password, a wrong PUBLIC_URL gets baked into the
    # frontend bundle, and a premature start burns Let's Encrypt's failure
    # budget for the domain. Cheap to check, expensive to discover.
    echo ">> preflight on $REMOTE ..."
    ssh "$REMOTE" APP_DIR="$APP_DIR" 'bash -s' <<'PREFLIGHT'
set -uo pipefail
fail=0
say()  { printf '   %-6s %s\n' "$1" "$2"; }
bad()  { say "FAIL" "$1"; fail=1; }
ok()   { say "ok" "$1"; }

cd "$HOME/$APP_DIR" 2>/dev/null || { bad "no ~/$APP_DIR -- create it and add .env"; exit 1; }
[ -f .env ] || { bad ".env missing (copy deploy/env.example, fill it, chmod 600)"; exit 1; }

perms=$(stat -c '%a' .env)
[ "$perms" = "600" ] && ok ".env is chmod 600" || bad ".env is chmod $perms, want 600"

# Read it without interpolating anything -- the same guarantee compose's
# `format: raw` gives the containers.
while IFS= read -r line; do
  case "$line" in ''|'#'*) continue ;; esac
  key=${line%%=*}; val=${line#*=}
  case "$key" in SITE_ADDRESS|PUBLIC_URL|BASIC_AUTH_USER|BASIC_AUTH_HASH|GEMINI_API_KEY|ACME_EMAIL|APP_UID)
    printf -v "v_$key" '%s' "$val" ;;
  esac
done < .env

for k in SITE_ADDRESS PUBLIC_URL ACME_EMAIL BASIC_AUTH_USER GEMINI_API_KEY; do
  eval "v=\${v_$k-}"
  [ -n "$v" ] && ok "$k set" || bad "$k is empty in .env"
done

# A bcrypt hash is $2a$14$<53 chars>. If compose or an editor ate the $ signs
# this is where it shows, not on the first login attempt.
eval "h=\${v_BASIC_AUTH_HASH-}"
case "$h" in
  '$2'[aby]'$'*) [ ${#h} -ge 59 ] \
      && ok "BASIC_AUTH_HASH looks like bcrypt (${#h} chars)" \
      || bad "BASIC_AUTH_HASH is only ${#h} chars -- truncated, re-paste it" ;;
  '') bad "BASIC_AUTH_HASH is empty -- run: docker run --rm caddy caddy hash-password --plaintext 'pw'" ;;
  *)  bad "BASIC_AUTH_HASH doesn't start with \$2a\$ -- it was mangled or quoted" ;;
esac

# The frontend bakes PUBLIC_URL in at build time; a mismatch here ships a UI
# that calls the wrong origin and cannot be fixed without a rebuild.
eval "s=\${v_SITE_ADDRESS-}"; eval "p=\${v_PUBLIC_URL-}"
[ "$p" = "https://$s" ] && ok "PUBLIC_URL matches SITE_ADDRESS" \
  || bad "PUBLIC_URL ($p) should be exactly https://$s"

# DNS must already point here or Caddy's ACME challenge fails, and repeated
# failures rate-limit the domain for hours.
mine=$(curl -s --max-time 5 ifconfig.me || echo '?')
seen=$(getent hosts "$s" | awk '{print $1; exit}')
[ -n "$seen" ] && [ "$seen" = "$mine" ] && ok "$s resolves to this VM ($mine)" \
  || bad "$s resolves to '${seen:-nothing}' but this VM is $mine -- fix DNS before starting Caddy"

[ -w /data/chroma ] && ok "/data/chroma is writable" \
  || bad "/data/chroma missing or not writable -- mount the data disk (README B2)"

# The container drops to APP_UID; the bind mount keeps the host's ownership,
# so a mismatch here is a crash loop on the first ingest, not a warning.
eval "u=\${v_APP_UID-1001}"
owner=$(stat -c '%u' /data/chroma 2>/dev/null || echo '?')
[ "$owner" = "$u" ] && ok "/data/chroma owned by uid $u (APP_UID)" \
  || bad "/data/chroma owned by uid $owner but the container runs as $u -- chown it or set APP_UID=$owner in .env"

command -v docker >/dev/null && ok "docker present" || bad "docker not installed"
docker compose version >/dev/null 2>&1 && ok "compose plugin present" \
  || bad "docker compose plugin missing"

[ "$fail" = 0 ] && echo "   -- preflight passed" || echo "   -- preflight FAILED"
exit "$fail"
PREFLIGHT

    [ "$CMD" = "preflight" ] && exit 0

    echo ">> syncing working tree to $REMOTE:$APP_DIR ..."
    # tar over ssh rather than rsync: macOS ships `openrsync`, which mangles a
    # dotted `host:path` into a LOCAL directory and silently syncs nothing to
    # the box. tar is on every machine and has no such surprise. The box's
    # .env and set-secrets.sh are never in the archive, so a filled-in .env is
    # never clobbered; everything else is replaced wholesale so the box is in
    # step with this working tree (the rsync --delete semantics, by hand).
    # --no-xattrs/--no-fflags/--no-mac-metadata: macOS tar otherwise ships
    # Apple provenance attrs the Linux side warns about, line by line.
    tar -czf - --no-xattrs --no-fflags --no-mac-metadata \
      --exclude '.git' \
      --exclude '.venv' \
      --exclude 'node_modules' \
      --exclude 'frontend/dist' \
      --exclude '__pycache__' \
      --exclude '.pytest_cache' --exclude '.mypy_cache' --exclude '.ruff_cache' \
      --exclude 'chroma_db' \
      --exclude '.env' \
      --exclude 'frontend/.env.local' \
      --exclude 'graphify-out' \
      . \
    | ssh "$REMOTE" "set -e; cd $APP_DIR
        find . -mindepth 1 -maxdepth 1 ! -name .env ! -name set-secrets.sh -exec rm -rf {} +
        tar -xzf - && echo '   synced' \$(find . -type f | wc -l) 'files'"

    echo ">> building and starting on $REMOTE ..."
    ssh -t "$REMOTE" "cd $APP_DIR && $COMPOSE up -d --build"
    echo ">> done. Caddy will fetch a cert on first boot if DNS + ports are ready."
    echo ">> tail logs with:  deploy/deploy.sh $REMOTE logs"
    ;;
  *)
    echo "unknown command: $CMD (use: up | preflight | logs | down | status | stop | start)" >&2
    exit 2
    ;;
esac
