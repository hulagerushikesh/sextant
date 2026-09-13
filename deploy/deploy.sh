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
#   deploy/deploy.sh user@vm-host            # preflight + rsync + build + up
#   deploy/deploy.sh user@vm-host preflight  # just check the box is ready
#   deploy/deploy.sh user@vm-host logs       # tail the stack
#   deploy/deploy.sh user@vm-host down       # stop the stack
#
# The VM must already have: Docker + compose plugin, /data/chroma on the
# attached persistent disk, and deploy/.env filled in at ~/agenticrag/.env
# (see deploy/env.example). This script never creates or overwrites that .env.
set -euo pipefail

REMOTE="${1:?usage: deploy.sh user@host [logs|down]}"
CMD="${2:-up}"
APP_DIR="agenticrag"                       # ~/agenticrag on the VM
COMPOSE="docker compose -f docker-compose.prod.yml"

cd "$(dirname "$0")/.."                     # repo root

case "$CMD" in
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
  case "$key" in SITE_ADDRESS|PUBLIC_URL|BASIC_AUTH_USER|BASIC_AUTH_HASH|GEMINI_API_KEY|ACME_EMAIL)
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
    echo "unknown command: $CMD (use: up | preflight | logs | down)" >&2
    exit 2
    ;;
esac
