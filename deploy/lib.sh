#!/usr/bin/env bash
# Shared by trip.sh and deploy.sh: the checks that have to happen on BOTH
# doors to the meter.
#
# This file exists because there were two. `trip.sh` grew a step 0 that reads
# the ssh firewall rule for Rs0 before anything is started, and a park that is
# an EXIT trap rather than a last line of a checklist -- and `deploy.sh start`,
# which is the other command that turns the meter on, had neither. It started
# the box, waited thirty times for an ssh that could not arrive, printed
# ">> up at <ip>" regardless, and left it billing with a reminder to stop it by
# hand. That is the 2026-09-28 Rs703 failure exactly, in the script the fix for
# it did not touch.
#
# One copy, not two: a door check that exists in one of two scripts is a door
# check in neither.

# Port 22 is open to exactly one /32 and a home ISP moves that address whenever
# it likes. The URL is a knob so the check is testable and so a dead service
# can be swapped rather than worked around.
SSH_RULE="${VM_SSH_RULE:-agenticrag-ssh}"
MY_IP_URL="${VM_MY_IP_URL:-https://checkip.amazonaws.com}"

# ssh_door PROJECT GCLOUD...
#
# 0 = open, or could not be determined; 1 = provably shut.
#
# Three outcomes, not two. A flaky address service or an unreadable rule must
# not be able to ground the box: those return 0 and say the door was not
# checked. Only a readable rule that provably excludes this machine returns 1.
ssh_door() {
  local project="$1"; shift
  local gc=("$@")
  local mine allowed verdict=0
  mine=$(curl -s --max-time 15 "$MY_IP_URL" 2>/dev/null | tr -d '[:space:]' || true)
  if [ -z "$mine" ]; then
    echo "   could not learn this machine's address -- door not checked" >&2
    return 0
  fi
  allowed=$("${gc[@]}" firewall-rules describe "$SSH_RULE" \
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
    "$SSH_RULE" "$project" "$mine" >&2
  return 1
}
