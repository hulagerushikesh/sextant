#!/usr/bin/env bash
# Set the box's secrets, from stdin, on the box.
#
#   cat my-secrets | ssh <box> "cd agenticrag && ./set-secrets.sh"
#
# Each line is KEY=VALUE. A password is given as BASIC_AUTH_PASS[_2|_3] and is
# hashed HERE, by the caddy image already on the box, so the bcrypt hash is
# born on the box and never crosses a shell. Nothing prints a value.
#
# Why this file exists, and why it is this shape:
#
# CLAUDE.md has told every reader since go-live that "on the VM the owner runs
# set-secrets.sh", and `trip.sh` step 3 preserves a file by that name across
# every deploy -- `! -name set-secrets.sh` in the wipe. It had never been
# written. The documented way to put a secret on this box was a file that did
# not exist, so the real way was a hand-edit in vi, and on 2026-10-31 a
# hand-edit is exactly what cost a ten-minute build: slot 2's hash reached
# `.env` with its `$` signs eaten and Caddy crash-looped on
#   base64-decoding password: illegal base64 data at input byte 5
# Byte 5, not byte 0 -- the `$2a$12$` prefix was already gone when Caddy read
# it. A hash that is generated and written by the same script cannot be
# mangled in transit, because there is no transit.
#
# Values arrive on STDIN and never in argv: `trip.sh` step 6 pipes gate
# credentials to curl for the same reason -- argv is world-readable in `ps`,
# on this box and on the laptop that typed the command.
#
# No associative arrays: macOS ships bash 3.2 and the box runs bash 5, so a
# `declare -A` here would pass on CI's Ubuntu and fail on the laptop the
# harness runs on -- the BSD-vs-GNU tar shape, a third time. Keys are held in
# dynamic variable names via `printf -v`, which is what `gate-slots.sh` already
# does for the same reason, and every key reaches that printf only after
# `is_allowed` has vouched for its spelling.
#
# This script does NOT judge what it wrote. `trip.sh` step 2 runs
# `deploy/gate-slots.sh` immediately afterwards, over the same rule
# `deploy.sh`'s preflight uses, and hard-stops before the build. A fixer that
# validates its own output is two readers of one rule -- the shape that made
# `_FORWARDED_ENV` and the preflight key list fall behind -- and worse, it is
# a check whose subject is the thing that wrote it. The writer writes; the gate
# decides.
set -euo pipefail

ENV_FILE="${SET_SECRETS_ENV:-.env}"
# The caddy image the edge is built FROM (deploy/Dockerfile.caddy), so it is
# already pulled on any box that has ever deployed. Overridable for the test
# harness, which has no docker.
HASHER="${SET_SECRETS_HASHER:-docker run --rm -i caddy:2-alpine caddy hash-password}"

say() { printf '   %-8s %s\n' "$1" "$2"; }
die() { printf '   %-8s %s\n' "FAIL" "$1" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "$ENV_FILE is not here -- run this from ~/agenticrag"

# An allow-list, not a deny-list, for the reason writes are an allow-list
# everywhere else in this project: this script edits the file that decides
# whether the box can serve, and a typo'd key name appended as a new line is
# indistinguishable from a setting that does nothing.
is_allowed() {
  case "$1" in
    BASIC_AUTH_USER|BASIC_AUTH_USER_2|BASIC_AUTH_USER_3) return 0 ;;
    BASIC_AUTH_PASS|BASIC_AUTH_PASS_2|BASIC_AUTH_PASS_3) return 0 ;;
    GEMINI_API_KEY|SEXTANT_PROXY_SECRET)                 return 0 ;;
    SEXTANT_DAILY_BUDGET_SHARE)                          return 0 ;;
    *) return 1 ;;
  esac
}

order=""
# want_<KEY> holds the value; a set want_<KEY> is the "present" flag.
got() { eval "[ -n \"\${want_$1+x}\" ]"; }
val_of() { eval "printf '%s' \"\$want_$1\""; }

# Read the whole of stdin first. Hashing happens after, so a rejected key
# stops the run before docker is invoked even once.
lineno=0
while IFS= read -r line || [ -n "$line" ]; do
  lineno=$((lineno + 1))
  case "$line" in ''|'#'*) continue ;; esac
  case "$line" in
    *=*) ;;
    *) die "line $lineno is not KEY=VALUE" ;;
  esac
  key=${line%%=*}
  val=${line#*=}
  case "$key" in
    BASIC_AUTH_HASH|BASIC_AUTH_HASH_*)
      die "give $key as ${key/HASH/PASS} and let this script hash it on the box -- a hash pasted through two shells is how slot 2 was mangled" ;;
  esac
  is_allowed "$key" || die "$key is not a secret this script sets (see is_allowed)"
  [ -n "$val" ] || die "$key has an empty value -- remove the line instead"
  got "$key" || order="$order $key"
  printf -v "want_$key" '%s' "$val"
done

[ -n "$order" ] || die "nothing arrived on stdin"

# Hash every password into the hash variable Caddy actually reads, then forget
# the plaintext. `-i` on docker run, and the plaintext on the container's
# stdin: `--plaintext` would put it in the box's process list.
for key in $order; do
  case "$key" in
    BASIC_AUTH_PASS|BASIC_AUTH_PASS_*) ;;
    *) continue ;;
  esac
  hash_key="${key/PASS/HASH}"
  if ! hash=$(val_of "$key" | $HASHER 2>/dev/null); then
    die "$HASHER failed -- is docker running on this box?"
  fi
  hash=${hash%$'\n'}
  [ -n "$hash" ] || die "the hasher returned nothing for $key"
  printf -v "want_$hash_key" '%s' "$hash"
  order="$order $hash_key"
  unset "want_$key"
  say "hashed" "$key -> $hash_key (${#hash} chars, on the box)"
done

NEW=$(mktemp "${TMPDIR:-/tmp}/set-secrets.XXXXXX")
trap 'rm -f "$NEW"' EXIT
chmod 600 "$NEW"

written=""
changed=0
done_with() { case " $written " in *" $1 "*) return 0 ;; esac; return 1; }

# Rewrite in place, preserving order and every comment: this file is read by a
# human in vi more often than by anything else, and a script that reorders it
# makes the next hand-edit harder than the one before.
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ''|'#'*) printf '%s\n' "$line" >> "$NEW"; continue ;;
  esac
  key=${line%%=*}
  if got "$key" && ! done_with "$key"; then
    printf '%s=%s\n' "$key" "$(val_of "$key")" >> "$NEW"
    written="$written $key"
    old=${line#*=}
    if [ "$old" = "$(val_of "$key")" ]; then
      say "same" "$key was already this value"
    else
      say "set" "$key"
      changed=1
    fi
  else
    printf '%s\n' "$line" >> "$NEW"
  fi
done < "$ENV_FILE"

# A key the file did not have yet. Appended, because the alternative is
# guessing where it belongs.
for key in $order; do
  case "$key" in BASIC_AUTH_PASS|BASIC_AUTH_PASS_*) continue ;; esac
  done_with "$key" && continue
  printf '%s=%s\n' "$key" "$(val_of "$key")" >> "$NEW"
  say "added" "$key (was not in $ENV_FILE)"
  changed=1
done

if [ "$changed" = 0 ]; then
  say "ok" "$ENV_FILE already said all of this -- not rewriting it"
  exit 0
fi

# A dated backup, not `.env.bak`: the second run of this script would
# otherwise overwrite the only copy of what the box had before the first.
backup="$ENV_FILE.bak.$(date -u +%Y%m%dT%H%M%SZ)"
cp -a "$ENV_FILE" "$backup"
cat "$NEW" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
say "ok" "$ENV_FILE rewritten; previous copy at $backup"
say "next" "trip.sh step 2 checks the slots with deploy/gate-slots.sh"
