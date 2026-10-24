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
#   deploy/deploy.sh vm-host down       # stop the containers (the VM keeps billing)
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
# The ssh door check, shared with trip.sh. `start` is the other command
# that turns the meter on, so it gets the same Rs0 precondition.
. deploy/lib.sh

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
    # `return`, not `exit`: `down` asks this the same question the lifecycle
    # commands do, but it asks it *after* doing its work, and a command that
    # succeeded must not be turned into a failure by the epilogue that reports
    # on it.
    return 2
  fi
  GC=(gcloud compute instances --project="$PROJECT")
  GC_COMPUTE=(gcloud compute --project="$PROJECT")
}

vm_status() {
  "${GC[@]}" describe "$INSTANCE" --zone="$ZONE" \
    --format='value(status,machineType.basename(),networkInterfaces[0].accessConfigs[0].natIP)'
}

# billing_line STATE -- what that state costs, indented under the caller.
#
# Every state the compute API documents, and a default. These arms used to be
# RUNNING and TERMINATED only, so six states -- all of which bill -- printed
# the instance line and nothing after it. A `case` with no default is a list
# of the states somebody thought of, and silence here reads exactly like the
# parked case.
#
# One copy, because `down`'s epilogue needs the same answer and a second table
# of the same eight states would fall behind this one silently -- which is how
# the preflight came to read seven of the Caddyfile's twelve names.
billing_line() {
  case "$1" in
    RUNNING|REPAIRING)
      echo "   billing: VM $VM_COST_PER_HOUR/hour + disks + IP" ;;
    PROVISIONING|STAGING)
      echo "   billing: starting up -- the VM meter is on from here" ;;
    STOPPING|SUSPENDING)
      echo "   billing: still on at $VM_COST_PER_HOUR/hour until this finishes" ;;
    SUSPENDED)
      echo "   billing: preserved memory + disks (no vCPU, not free)" ;;
    TERMINATED)
      echo "   billing: disks + reserved IP only (VM meter off)" ;;
    *)
      # Wrong in the safe direction, like the grounded-search price in
      # pricing.py: a state name this script has never seen must not read as
      # parked.
      echo "   billing: UNKNOWN state '$1' -- assume the VM meter is on" ;;
  esac
}

# What is still on the meter once the containers are gone.
#
# `down` is the only command here that stops something without stopping the
# box, so it is the only one where "finished" and "not billing" are different
# sentences -- and it is the command whose name sounds the most like both. A
# person who runs it and sees two containers removed has no way to learn from
# this script that an e2-standard-2 is still charging ~Rs5.6/hour behind them.
# That is the 2026-09-28 Rs703 shape with the believing done one level up.
#
# Never fatal, and never changes the caller's exit status: this reports on a
# command that has already decided its own result. An unreadable state says
# the meter is on, which is the direction `status` and pricing.py both round in.
meter_epilogue() {
  local state=''
  if vm_target 2>/dev/null; then
    read -r state _ _ <<<"$(vm_status 2>/dev/null || true)"
  fi
  case "$state" in
    TERMINATED|STOPPED)
      echo ">> containers stopped, and the VM is $state."
      billing_line "$state" ;;
    '')
      # No gcloud, no credentials, or a host this script cannot resolve to an
      # instance. The containers are down either way and the box almost
      # certainly is not, so say the expensive thing rather than nothing.
      echo ">> containers stopped. This does NOT stop the VM, and its state" >&2
      echo ">>   could not be read -- assume it is billing" \
           "$VM_COST_PER_HOUR per hour." >&2
      echo ">>   check:  deploy/deploy.sh $REMOTE status" >&2
      echo ">>   park:   deploy/deploy.sh $REMOTE stop" >&2 ;;
    *)
      echo ">> containers stopped, but the VM is NOT: $INSTANCE is $state."
      billing_line "$state"
      echo ">>   park it:  deploy/deploy.sh $REMOTE stop" ;;
  esac
}

case "$CMD" in
  status)
    vm_target || exit 2
    read -r state type ip <<<"$(vm_status)"
    # An empty state is not a state. `describe` leaves one behind whenever it
    # fails -- wrong project, expired credentials, an API error -- and this
    # used to print the instance line with a blank after the colon and exit 0.
    # The command whose job is to say what is billing has to be louder when it
    # does not know than when it does; the Rs703 failure was a box nobody
    # checked, and a check that answers nothing is worse than no check because
    # it looks like an answer.
    if [ -z "$state" ]; then
      echo "$INSTANCE ($ZONE): could not read the instance state" >&2
      echo "   gcloud describe returned nothing. Until this answers, assume the" >&2
      echo "   VM meter is ON and check the console:" >&2
      echo "   gcloud compute instances describe $INSTANCE --zone=$ZONE --project=$PROJECT" >&2
      exit 1
    fi
    echo "$INSTANCE (${type:-machine type unknown}, $ZONE): $state${ip:+  ip $ip}"
    billing_line "$state"
    ;;
  stop)
    vm_target || exit 2
    read -r state _ _ <<<"$(vm_status)"
    if [ "$state" = "TERMINATED" ]; then echo "$INSTANCE already stopped"; exit 0; fi
    echo ">> stopping $INSTANCE (containers restart on their own at next start) ..."
    "${GC[@]}" stop "$INSTANCE" --zone="$ZONE" --quiet
    # Read it back. Printing ">> stopped" after issuing a stop is a claim about
    # the command, not about the box -- the same defect trip.sh had until
    # 2026-10-06, where an offline run ended "agenticrag is RUNNING" and exited
    # 0 because nothing compared the state it had just printed.
    read -r state _ _ <<<"$(vm_status)"
    case "$state" in
      TERMINATED|STOPPED)
        echo ">> stopped ($state). Disks, images and .env are kept." ;;
      *)
        echo ">> NOT STOPPED: $INSTANCE is $state and billing $VM_COST_PER_HOUR" \
             "per hour. Try again, or stop it by hand:" >&2
        echo ">>   gcloud compute instances stop $INSTANCE --zone=$ZONE --project=$PROJECT" >&2
        exit 1 ;;
    esac
    # A stopped box still bills for a reserved address, at roughly twice the
    # in-use rate -- about Rs640/month for nothing. The README prices it; this
    # says it at the moment it starts applying. Not deleted automatically:
    # releasing the address changes the public IP, which is a DNS decision,
    # and trip.sh (which repoints DNS next trip anyway) is where that belongs.
    reserved=$(gcloud compute addresses list --project="$PROJECT" \
      --format='value(name)' 2>/dev/null || true)
    if [ -n "$reserved" ]; then
      echo ">> NOTE: an address is still reserved and bills ~Rs21/day while the"
      echo ">>   box is stopped: $(echo "$reserved" | tr '\n' ' ')"
      echo ">>   release it with:  gcloud compute addresses delete <name> --region=${ZONE%-*} --project=$PROJECT"
      echo ">>   (the public IP changes, so repoint DNS -- README B3)"
    else
      echo ">> no reserved addresses; only disks bill now (~Rs270/month)."
    fi
    ;;
  start)
    vm_target || exit 2
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
    # Before the meter: is port 22 even open to this machine? Reading the
    # firewall rule is free, and on 2026-10-07 a trip that skipped this
    # reserved an address, started the box, waited two minutes for an ssh that
    # could not arrive, and left it billing. Rs0 to find out first.
    echo ">> checking the ssh door (costs nothing)"
    ssh_door "$PROJECT" "${GC_COMPUTE[@]}" || exit 1
    # This is the one command here that turns a meter on. Say so, and wait.
    echo "Starting $INSTANCE bills $VM_COST_PER_HOUR per hour until it is stopped again."
    if [ "${3:-}" != "--yes" ]; then
      read -r -p "Start it? [y/N] " answer
      case "$answer" in y|Y|yes) ;; *) echo "not started"; exit 1 ;; esac
    fi
    "${GC[@]}" start "$INSTANCE" --zone="$ZONE" --quiet
    echo ">> started; waiting for ssh ..."
    for _ in $(seq 1 "${VM_SSH_TRIES:-30}"); do
      ssh -o ConnectTimeout=5 -o BatchMode=yes "$REMOTE" true 2>/dev/null && break
      sleep "${VM_SSH_SLEEP:-5}"
    done
    # The loop above used to be the whole of it: it ended either way and the
    # next line said ">> up at <ip>" regardless, so a box nothing could reach
    # was reported as started and left running. Ask once more, for real, and
    # park it if the answer is no -- an unreachable box is not a started box,
    # it is Rs5.6/hour of nothing.
    if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE" true; then
      echo ">> ssh never came up. The door check passed, so look at the box." >&2
      echo ">> stopping it rather than leaving it billing:" >&2
      "${GC[@]}" stop "$INSTANCE" --zone="$ZONE" --quiet || true
      read -r state _ _ <<<"$(vm_status)"
      case "$state" in
        TERMINATED|STOPPED) echo ">> parked ($state). Restarting costs ~Rs2." >&2 ;;
        *) echo ">> COULD NOT PARK IT: $INSTANCE is $state and billing" \
                "$VM_COST_PER_HOUR per hour. Stop it by hand:" >&2
           echo ">>   gcloud compute instances stop $INSTANCE --zone=$ZONE --project=$PROJECT" >&2 ;;
      esac
      exit 1
    fi
    read -r _ _ ip <<<"$(vm_status)"
    echo ">> up at ${ip:-?}. The stack restarts by itself (restart: unless-stopped)."
    echo ">> if the tree changed:  deploy/deploy.sh $REMOTE"
    echo ">> when finished:        deploy/deploy.sh $REMOTE stop"
    echo ">> nothing parks this for you. deploy/trip.sh parks on exit, including"
    echo ">>   on failure and on Ctrl-C -- prefer it unless you need the box up."
    ;;
  logs)
    exec ssh -t "$REMOTE" "cd $APP_DIR && $COMPOSE logs -f --tail=200"
    ;;
  down)
    # Not `exec`. Until 2026-10-23 this line replaced the shell with ssh, so
    # the command that sounds the most like "I am done paying for this" was
    # structurally incapable of saying anything after the containers went
    # away. `exec` preserved the exit status, which is the only reason to use
    # it here, so the status is preserved by hand instead.
    rc=0
    ssh -t "$REMOTE" "cd $APP_DIR && $COMPOSE down" || rc=$?
    [ "$rc" = 0 ] || echo ">> compose down exited $rc" >&2
    meter_epilogue
    exit "$rc"
    ;;
  preflight|up)
    # Check the box BEFORE spending twenty minutes building torch. Every one of
    # these has a failure mode that only shows up at the very end: a mangled
    # hash rejects every password, a wrong PUBLIC_URL gets baked into the
    # frontend bundle, and a premature start burns Let's Encrypt's failure
    # budget for the domain. Cheap to check, expensive to discover.
    echo ">> preflight on $REMOTE ..."
    # DATA_DIR exists only so this script can be run off the VM, which until
    # 2026-10-12 nothing ever had -- a check nobody can execute is a check
    # nobody has read. The box never passes it; the default is the mount.
    ssh "$REMOTE" APP_DIR="$APP_DIR" DATA_DIR="${DATA_DIR:-/data/chroma}" 'bash -s' <<'PREFLIGHT'
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
  # Every name the deploy interpolates, because a variable this reader skips
  # is a variable no check below can ask about -- which is how an empty
  # SEXTANT_PROXY_SECRET and a half-filled gate slot both got through. The
  # list used to stop after BASIC_AUTH_HASH. It is now held to
  # deploy/Caddyfile and docker-compose.prod.yml by
  # TestEveryDeployTimeVariableReachesThePreflight, so it grows with them
  # rather than with whoever remembers.
  case "$key" in
    SITE_ADDRESS|PUBLIC_URL|ACME_EMAIL|APP_UID|GEMINI_API_KEY|SEXTANT_PROXY_SECRET \
    |BASIC_AUTH_USER|BASIC_AUTH_HASH \
    |BASIC_AUTH_USER_2|BASIC_AUTH_HASH_2 \
    |BASIC_AUTH_USER_3|BASIC_AUTH_HASH_3)
      printf -v "v_$key" '%s' "$val" ;;
  esac
done < .env

for k in SITE_ADDRESS PUBLIC_URL ACME_EMAIL GEMINI_API_KEY; do
  eval "v=\${v_$k-}"
  [ -n "$v" ] && ok "$k set" || bad "$k is empty in .env"
done

# A bcrypt hash is $2a$14$<53 chars>. If compose or an editor ate the $ signs
# this is where it shows, not on the first login attempt. A function, because
# the Caddyfile has three slots and this used to be run against one of them.
bcrypt() {   # bcrypt <name> <value>
  case "$2" in
    '$2'[aby]'$'*) [ ${#2} -ge 59 ] \
        && ok "$1 looks like bcrypt (${#2} chars)" \
        || bad "$1 is only ${#2} chars -- truncated, re-paste it" ;;
    *)  bad "$1 doesn't start with \$2a\$ -- it was mangled or quoted" ;;
  esac
}

# The gate, slot by slot. Caddy refuses to START on a user with no hash, so a
# half-filled slot is not a degraded box, it is a box that serves nothing --
# and it refuses after the build, which is the one thing this script exists to
# prevent. env.example ships slots 2 and 3 with both halves empty, and the
# Caddyfile drops those lines before parsing, so unused is reported as fine:
# a check that fails on the documented default is a check people learn to
# ignore. No name and no hash is ever printed, only lengths.
for n in '' _2 _3; do
  eval "u=\${v_BASIC_AUTH_USER$n-}"; eval "h=\${v_BASIC_AUTH_HASH$n-}"
  if [ -z "$u" ] && [ -z "$h" ]; then
    if [ -z "$n" ]; then
      bad "BASIC_AUTH_USER and BASIC_AUTH_HASH are both empty -- nobody could log in"
    else
      ok "gate slot ${n#_} unused (both halves empty)"
    fi
    continue
  fi
  if [ -z "$u" ]; then
    bad "BASIC_AUTH_HASH$n is set but BASIC_AUTH_USER$n is empty -- Caddy will refuse to start"
  elif [ -z "$h" ]; then
    bad "BASIC_AUTH_USER$n is set but BASIC_AUTH_HASH$n is empty -- Caddy will refuse to start"
    say "" "  docker run --rm caddy caddy hash-password --plaintext 'pw'"
  else
    ok "BASIC_AUTH_USER$n set"
    bcrypt "BASIC_AUTH_HASH$n" "$h"
  fi
done

# Caddy has no conditionals: `header_up X-Sextant-User {http.auth.user.id}`
# goes out on every proxied request whether or not the app can verify where it
# came from. With this empty the app raises ForgedIdentity and answers 403 to
# EVERY request -- not some, and not only the authenticated ones. trip.sh has
# hard-stopped on it since 2026-10-06; the command whose stated job is to find
# this out before twenty minutes of building torch never read the name.
eval "ps=\${v_SEXTANT_PROXY_SECRET-}"
if [ -n "$ps" ]; then
  ok "SEXTANT_PROXY_SECRET set (${#ps} chars)"
else
  bad "SEXTANT_PROXY_SECRET is empty -- Caddy forwards the name anyway, so every request would 403"
  say "" 'generate it here, so the value never leaves the box:'
  say "" '  printf "SEXTANT_PROXY_SECRET=%s\n" $(openssl rand -hex 32) >> .env'
fi

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

[ -w "$DATA_DIR" ] && ok "$DATA_DIR is writable" \
  || bad "$DATA_DIR missing or not writable -- mount the data disk (README B2)"

# The container drops to APP_UID; the bind mount keeps the host's ownership,
# so a mismatch here is a crash loop on the first ingest, not a warning.
eval "u=\${v_APP_UID-1001}"
owner=$(stat -c '%u' "$DATA_DIR" 2>/dev/null || echo '?')
[ "$owner" = "$u" ] && ok "$DATA_DIR owned by uid $u (APP_UID)" \
  || bad "$DATA_DIR owned by uid $owner but the container runs as $u -- chown it or set APP_UID=$owner in .env"

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
      --exclude 'dist' --exclude '*.egg-info' \
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
