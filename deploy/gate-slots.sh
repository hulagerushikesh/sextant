#!/usr/bin/env bash
# The gate, slot by slot: the one rule both doors to the meter check.
#
# Caddy's basic_auth takes a bcrypt hash per slot and refuses to START on one
# it cannot parse, so a mangled hash is not a degraded box -- it is a box that
# serves nothing, and it refuses AFTER the build. deploy.sh's preflight has
# checked this since 2026-10-12; trip.sh did not, and trip.sh is the script
# that does the building. On 2026-10-31 it counted non-empty hashes instead,
# printed `basic_auth users: 2`, concluded `safe to build`, and spent ten
# minutes producing an image whose Caddy then crash-looped on
#   base64-decoding password: illegal base64 data at input byte 5
# -- slot 2, read by a Caddyfile that had three slots for the first time. The
# check that would have caught it for Rs0 already existed one file over and
# nothing called it. **A rule with two callers lives in one file**, the same
# answer `ssh_door` got when both scripts needed the door checked.
#
# Only the slot rule is shared, deliberately. The rest of the preflight is
# not: its DNS arm fails when SITE_ADDRESS resolves to nothing, which is a
# legitimate trip (step 1b skips when CF_* are unset), so gating the build on
# the whole preflight would refuse to deploy a box that deploys fine.
#
# Runs ON the box, shipped over ssh to `bash -s`, so no name and no hash ever
# leaves it. Only lengths and verdicts are printed.

# deploy.sh's preflight defines these and counts failures in its own `fail`.
# Standalone, we define them and count in GATE_FAIL.
if ! declare -F bad >/dev/null 2>&1; then
  say() { printf '   %-6s %s\n' "$1" "$2"; }
  bad() { say "FAIL" "$1"; GATE_FAIL=1; }
  ok()  { say "ok" "$1"; }
fi

# A bcrypt hash is $2a$14$<53 chars>. If compose or an editor ate the $ signs
# this is where it shows, not on the first login attempt.
gate_bcrypt() {   # gate_bcrypt <name> <value>
  case "$2" in
    '$2'[aby]'$'*) [ "${#2}" -ge 59 ] \
        && ok "$1 looks like bcrypt (${#2} chars)" \
        || bad "$1 is only ${#2} chars -- truncated, re-paste it" ;;
    *)  bad "$1 doesn't start with \$2a\$ -- it was mangled or quoted" ;;
  esac
}

# Read .env without interpolating anything -- the same guarantee compose's
# `format: raw` gives the containers, and the reason a $ in a hash survives.
gate_read_env() {   # gate_read_env <path>
  local line key val
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    key=${line%%=*}; val=${line#*=}
    case "$key" in
      BASIC_AUTH_USER|BASIC_AUTH_HASH \
      |BASIC_AUTH_USER_2|BASIC_AUTH_HASH_2 \
      |BASIC_AUTH_USER_3|BASIC_AUTH_HASH_3) printf -v "g_$key" '%s' "$val" ;;
    esac
  done < "$1"
}

# env.example ships slots 2 and 3 with both halves empty and the Caddyfile
# drops those lines before parsing, so unused is reported as fine: a check
# that fails on the documented default is a check people learn to ignore.
#
# Takes the six values rather than reading them, so the preflight -- which has
# already read .env into its own v_* vars, and is pinned to keep reading every
# name the deploy interpolates -- passes what it has instead of this file
# reading the same file a second time. Two readers of one file is the shape
# the key list and _FORWARDED_ENV both got wrong.
gate_slot_values() {   # gate_slot_values <u1> <h1> <u2> <h2> <u3> <h3>
  local n u h
  for n in '' _2 _3; do
    u=${1-}; h=${2-}; shift 2 2>/dev/null || true
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
      gate_bcrypt "BASIC_AUTH_HASH$n" "$h"
    fi
  done
}

# The standalone path: trip.sh has no reader on the box, so this one reads.
gate_slots() {   # gate_slots [env path]
  gate_read_env "${1:-.env}"
  gate_slot_values "${g_BASIC_AUTH_USER-}" "${g_BASIC_AUTH_HASH-}" \
                   "${g_BASIC_AUTH_USER_2-}" "${g_BASIC_AUTH_HASH_2-}" \
                   "${g_BASIC_AUTH_USER_3-}" "${g_BASIC_AUTH_HASH_3-}"
}

# Sourced by the preflight (which calls gate_slots itself, among its own
# checks); run outright by trip.sh, where the exit status is the whole point.
if [ "${GATE_SLOTS_LIB:-0}" != 1 ]; then
  GATE_FAIL=0
  cd "${GATE_SLOTS_DIR:-.}" || exit 90
  gate_slots
  exit "$GATE_FAIL"
fi
