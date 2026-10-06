# Deploying AgenticRAG to GCP Compute Engine

A single warm VM with an attached data disk, behind Caddy (TLS + Basic auth).
This is the correct topology for the workload — the vector store is embedded
ChromaDB (single-writer, local disk), and the image is a heavy warm container,
so one vertically-scaled node beats a cold-starting fleet. The scale-out path
(extract Chroma to client/server, move rate-limiting to Redis) is documented at
the end for when one node stops being enough.

```
agenticrag.hulage.in ─DNS A─► static IP ─► VM (e2-standard-2, 8GB)
                                            ├─ Caddy  : TLS + Basic auth + routing
                                            ├─ api    : FastAPI + KB MCP subprocess
                                            └─ /data  : persistent disk → Chroma store
```

Everything below assumes `gcloud` is installed and authenticated to your own
project. Set these once:

```bash
export PROJECT=your-gcp-project
export ZONE=us-central1-a
export REGION=us-central1
gcloud config set project "$PROJECT"
```

**For a box that already exists, use [`trip.sh`](trip.sh), not the steps
below.** It starts the VM, ships the tree, rebuilds, verifies, and parks —
parking is an `EXIT` trap, so it happens on success, on failure and on Ctrl-C.
The steps below are the first-time build-out.

Two of its checks stop the trip *before* the build, because both failures are
only visible afterwards and both take the box down:

- **`AGENTICRAG_*` names still in the box's `.env`.** The fallback went in
  0.8.1; a container built from this tree against a pre-rename file runs with
  no budget cap and no CORS allowlist.
- **`SEXTANT_PROXY_SECRET` missing or empty.** Caddy has no conditionals — it
  forwards `X-Sextant-User` on every proxied request regardless — so the app
  sees a name it cannot verify and refuses *every* request with a 403.

It then prints, without printing any value: how many `basic_auth` slots are
filled, whether the model key is set, and whether a per-owner share is
configured. After the build it checks that a forged `X-Sextant-User` sent
straight at the api container is refused, and lists the store's document ids
so a pre-0.8.2 `upload:<stem>` leftover shows up by name.

**Step 6 runs from your machine, not the box.** Every other check goes
through `docker exec` at `localhost:8000` — inside the box, behind Caddy — so
until this step existed the trip never touched the gate it exists to deploy,
and a box whose Caddy was misconfigured or not running reported green. Export
the gate credentials before the trip and the step runs:

```bash
export SEXTANT_TRIP_AUTH='ada:her-password'
export SEXTANT_TRIP_AUTH_2='grace:her-password'
```

They go to `curl` through a config file on a pipe, never argv, so they are not
in `ps` while the trip runs, and nothing prints them. Unset, the step says the
gate is unproven rather than passing quietly — supplying them is your call, so
that is a skip. A box with **no `PUBLIC_URL`** is a failure, because that is
the box being wrong rather than you declining to prove something.

It checks: no credentials → 401; a wrong password → 401; a real user → 200; a
**forged `X-Sextant-Proxy-Auth` → 200**; and naming yourself with no password
→ 401. The fourth reads backwards and is the point — `header_up` in Caddy is a
*set*, so the client's copy is replaced before the app sees it. A forged proof
that still succeeds is Caddy working. A 403 would mean it appended instead,
and then anyone can send the header themselves. Any failed check makes the
script exit non-zero: the box is deployed, but it is not proven.

Nothing in step 6 writes to the corpus or calls the model — every request is a
`GET /health`.

**Step 7 proves the isolation, and it is the only part of the trip that
writes.** Step 6 proves the gate; every check in it is a read, so it says
nothing about what is behind the gate. Step 7 runs milestone 21's
pre-registered success criterion — two gate users upload a file of the same
name, both survive, each sees their own and not the other's, a client-supplied
`X-Sextant-User` changes nothing — and then reads the store directly to confirm
there are two probe documents under two different owners.

It only runs when both `SEXTANT_TRIP_AUTH` and `SEXTANT_TRIP_AUTH_2` are
exported. It costs two summaries (~$0.006) when a model key is configured.

**The forged-name check runs between the two uploads, not after.** Once both
users have uploaded, their counts are the same number, and a check whose two
sides agree cannot fail — the first draft of this step passed against a proxy
that forwarded the client's name for exactly that reason.

**The probe documents are removed in the `EXIT` trap, before the box stops** —
not at the end of step 7, because the run that most needs the cleanup is the
one that died half way through. They are found by scanning the store for the
probe filename rather than by rebuilding `upload:<owner>:<stem>` from the
usernames, so a name spelled differently by `safe_owner()` cannot leave
documents behind that the trip reports as gone. If any survive, the trip says
which and exits non-zero: documents left in the production corpus are not
something a 0 should be able to say happened.

**The park is checked, not just performed.** `park()` has always read the
instance's state back; it now compares it. If the box is not `TERMINATED` the
stop is retried once — a transient API error is the dullest explanation and
the cheapest to rule out — and if it is still up the script says so on stderr
with the manual command and **exits non-zero**, because 0 is how a person or a
later `&&` reads "parked". The same applies to the reserved address, which
bills ~₹21/day attached to nothing. A trip that otherwise passed but left the
meter running is not a trip that passed.

---

## B1–B2 · Provision (static IP, disk, firewall, VM)

```bash
# Static external IP — reserve it first so the subdomain never has to change.
gcloud compute addresses create agenticrag-ip --region="$REGION"
gcloud compute addresses describe agenticrag-ip --region="$REGION" \
  --format='get(address)'          # ← note this IP, it's the DNS target

# Persistent data disk for the Chroma store (survives VM rebuilds & snapshots).
gcloud compute disks create agenticrag-data \
  --size=20GB --type=pd-balanced --zone="$ZONE"

# Firewall: 80/443 open to the world; SSH locked to your current IP.
gcloud compute firewall-rules create agenticrag-web \
  --allow=tcp:80,tcp:443 --target-tags=agenticrag-web --direction=INGRESS
gcloud compute firewall-rules create agenticrag-ssh \
  --allow=tcp:22 --target-tags=agenticrag-web \
  --source-ranges="$(curl -s ifconfig.me)/32"
# (GCP's default network also has default-allow-ssh from 0.0.0.0/0 — delete or
#  tighten it if you want SSH truly restricted:
#  gcloud compute firewall-rules delete default-allow-ssh )

# The VM, with the static IP and data disk attached.
gcloud compute instances create agenticrag \
  --zone="$ZONE" --machine-type=e2-standard-2 \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB \
  --disk=name=agenticrag-data,device-name=agenticrag-data,mode=rw,boot=no \
  --address=agenticrag-ip \
  --tags=agenticrag-web
```

### On the VM: Docker + mount the data disk (first time only)

```bash
gcloud compute ssh agenticrag --zone="$ZONE"

# Docker + compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"      # then log out and back in

# Format the data disk ONCE (this erases it — skip on a rebuild that reuses it)
sudo mkfs.ext4 -F /dev/disk/by-id/google-agenticrag-data

# Mount at /data and make it persist across reboots
sudo mkdir -p /data
echo '/dev/disk/by-id/google-agenticrag-data /data ext4 discard,defaults,nofail 0 2' \
  | sudo tee -a /etc/fstab
sudo mount /data
sudo mkdir -p /data/chroma
sudo chown -R "$USER":"$USER" /data
```

---

## B3 · ⏸️ ADD THE SUBDOMAIN — handoff step

**This is the step to do together.** Two things depend on the hostname existing
*before* the next step: Caddy can only get a TLS cert once DNS resolves to the
VM, and the frontend bundle bakes the URL in at build time.

At whatever hosts DNS for `hulage.in`, add:

| Type | Name         | Value (the reserved IP) | TTL  |
|------|--------------|-------------------------|------|
| A    | `agenticrag` | `<static IP from B1>`   | 300  |

Then confirm it has propagated:

```bash
dig +short agenticrag.hulage.in     # must return the static IP
```

Don't run B5 until that returns the right IP — a premature `up` makes Caddy hit
Let's Encrypt's rate limit on failed challenges.

---

## B4 · Secrets on the box

```bash
# on the VM
mkdir -p ~/agenticrag && cd ~/agenticrag
# copy deploy/env.example here as .env after the first sync, or hand-write it:
nano .env
chmod 600 .env
```

Fill in `.env` (see [`env.example`](env.example)):

- `BASIC_AUTH_HASH` — generate on the box, paste the hash (never the plaintext):
  ```bash
  docker run --rm caddy caddy hash-password --plaintext 'a-strong-password'
  ```
  Paste it **verbatim** — no quotes, no `$$` escaping. The compose file reads
  `.env` with `format: raw` so the `$` signs survive; the default interpolation
  would truncate it to `$2a$14` and the gate would reject every password.
- `SEXTANT_PROXY_SECRET` — **required**, and the one entry a redeploy is most
  likely to forget. Any long random string, generated on the box:
  ```bash
  openssl rand -hex 32
  ```
  Caddy forwards the authenticated username to the app as `X-Sextant-User`,
  and this is how the app knows that header came from Caddy rather than from
  a client that typed it. Caddy has no conditionals, so it forwards the name
  whether or not this is set — leave it empty and the app refuses every
  request with a 403 that names this variable. Both containers read the same
  `.env`, so one value wires both halves.
- `BASIC_AUTH_USER_2` / `BASIC_AUTH_HASH_2` (and `_3`) — optional, one person
  per slot, hashed the same way as the first. An empty slot vanishes from the
  Caddyfile before it is parsed; a user set without its hash stops Caddy from
  starting. The name that authenticates is the namespace that person's uploads
  are stored under, so renaming one orphans what they already uploaded.
- `GEMINI_API_KEY` — your key. For v1 this file is the secret store (chmod 600).
  To harden later, pull it from Secret Manager at deploy time instead:
  ```bash
  gcloud secrets create gemini-key --data-file=- <<< "$KEY"
  # then fetch into .env in a deploy hook rather than storing it at rest
  ```

`SITE_ADDRESS`, `PUBLIC_URL`, `ACME_EMAIL` are already correct in the example
for `agenticrag.hulage.in`.

Then, from the laptop, check the box before building anything on it:

```bash
deploy/deploy.sh USER@IP preflight
```

It verifies the `.env` (perms, every key present, the hash is intact bcrypt,
`PUBLIC_URL` is exactly `https://$SITE_ADDRESS`), that DNS already resolves to
this VM, that `/data/chroma` is mounted and writable, and that Docker + compose
are present. Every line it checks is a failure that would otherwise appear
only *after* the twenty-minute torch build.

---

## B5 · Ship it

From the laptop (repo root). The script runs the preflight, ships the working
tree as a tar stream over ssh (not rsync: macOS's `openrsync` mangles a dotted
`host:path` into a local folder and syncs nothing) — it never `git push`es,
since the remote isn't yours — then builds and starts on the VM:

```bash
deploy/deploy.sh "$USER@$(gcloud compute addresses describe agenticrag-ip \
  --region="$REGION" --format='get(address)')"
```

Expect a few `warning: The "Zx9..." variable is not set` lines from compose —
that's its `${...}` interpolator reading the bcrypt hash out of `.env` and
misparsing the `$`s. Harmless: the containers get the hash via `format: raw`
(the preflight already verified it's intact), and nothing in the compose file
references `${BASIC_AUTH_HASH}`.

First boot: Caddy requests the cert (a few seconds once DNS is right). Watch it:

```bash
deploy/deploy.sh USER@IP logs
```

Verify — the gate should challenge, and `/health` should be `healthy`:

```bash
curl -u USER:PASSWORD https://agenticrag.hulage.in/health
# {"status":"healthy","mcp_connected":true,"model_configured":true,...}
```

---

## B6 · Load the corpus + guardrails

Re-running this is a replacement, not an overlay: each document's existing
chunks are cleared before its new ones are written, so re-ingesting a corpus
after a chunker change leaves nothing of the old chunking behind.

Since 0.8 this spends money: the box's `.env` has `GEMINI_API_KEY`, so the
ingest writes one model-written overview per document (~$0.003 each, ~$0.07
for this corpus). That is the `kb_list` listing's overview text and worth it
here. Add `--no-summaries` for a free ingest.

```bash
# Ingest the committed corpus into the VM's Chroma volume, then restart the api
# so it reloads the persisted store (it holds a stale segment after CLI ingest).
ssh USER@IP 'cd ~/agenticrag && \
  docker compose -f docker-compose.prod.yml exec api sextant-ingest eval/corpus -r && \
  docker compose -f docker-compose.prod.yml restart api'

# Take a document back out (the confirmation needs -T off, so pass -y):
ssh USER@IP 'cd ~/agenticrag && \
  docker compose -f docker-compose.prod.yml exec api sextant-forget --list'

# A real gated query end to end:
curl -u USER:PASSWORD -s https://agenticrag.hulage.in/query \
  -H 'content-type: application/json' \
  -d '{"query":"What does the Kalman filter do in tracking?"}' | head
```

**Cost + durability guardrails (do these — they're the difference from a dumb deploy):**

```bash
# Monthly budget alert, scoped to THIS project so other projects on the same
# billing account don't count. Emails billing admins at 50/90/100%.
# The amount is a bare number in the BILLING ACCOUNT'S currency -- `20USD` is
# rejected, and on an INR account `20` means twenty rupees (this bit us: the
# first budget was ₹2). ~$20 on an INR account is 1700.
gcloud services enable billingbudgets.googleapis.com
gcloud billing budgets create --billing-account=YOUR_BILLING_ID \
  --display-name="agenticrag monthly" --budget-amount=1700 \
  --filter-projects="projects/$PROJECT" \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0

# Nightly snapshot of the Chroma disk (retention 14 days).
gcloud compute resource-policies create snapshot-schedule agenticrag-daily \
  --region="$REGION" --max-retention-days=14 \
  --daily-schedule --start-time=03:00 --on-source-disk-delete=apply-retention-policy
gcloud compute disks add-resource-policies agenticrag-data \
  --zone="$ZONE" --resource-policies=agenticrag-daily
```

App-level, the rate limiter (`SEXTANT_RATE_LIMIT` / `_WINDOW`) caps the
request rate per **authenticated user** where Caddy supplies one, and per
client address otherwise; tighten it in `.env` if the gate is shared widely.
Keying on the name is why an office behind one address no longer shares a
bucket -- and why an unauthenticated box still keys on the address, since a
name the caller types is a bucket the caller can swap.

`SEXTANT_DAILY_BUDGET_SHARE` is the other half: the largest fraction of
`SEXTANT_DAILY_BUDGET_USD` any one authenticated user may spend in a day. The
cap protects your wallet, the share protects everybody else's access to it --
without it the first person to spend the day's allowance silences the rest
until 00:00 UTC. Default 1 (no per-user limit); `env.example` has the
arithmetic for a gate with three users.

### Uptime check (only if the VM runs 24/7)

Pointless while the VM is parked on purpose — it would page you for a
stop you chose. If the site is meant to stay up, one Cloud Monitoring
uptime check on `/health` through the gate is free (the free tier covers
far more than one check a minute) and emails on two consecutive failures.
The password goes in the console or a local shell, never in a file:

```bash
gcloud monitoring uptime create sextant-health \
  --resource-type=uptime-url --monitored-resource-labels=host=agenticrag.hulage.in \
  --protocol=https --port=443 --path=/health --period=5 --timeout=10 \
  --username=USER --password="$(read -rsp 'gate password: ' p; echo "$p")" \
  --matcher-content='"status":"healthy"' --matcher-type=contains-string
# then an alert policy on it (console: Monitoring -> Alerting -> Create,
# condition "Uptime check failed", notification = your email).
```

`/health` is exempt from the rate limiter for exactly this reason.

### The container is not root

The API process runs as uid `APP_UID` (default 1001), the box user that
owns `/data/chroma`. The preflight checks the two agree. If `id -u` on the
box is not 1001, put `APP_UID=<uid>` in `.env` before the first build.

---

## Redeploying

```bash
deploy/deploy.sh HOST          # ship changes, rebuild, restart
deploy/deploy.sh HOST down     # stop the containers
```

The box `.env` and `/data` are never touched by a redeploy.

## Parking the VM (cost)

Running, the VM bills ~₹135/day whether or not anyone uses it. When the
site is not needed, stop the instance — disks, the built images and `.env`
all survive a stop. Only the meters change:

| State | ₹/month (approx.) |
| --- | --- |
| running e2-standard-2 | 4,100 + 300 (IP) + 270 (disks) |
| stopped, IP reserved | 640 (an idle IP bills ~2× in-use) + 270 (disks) |
| stopped, IP released (**current state**, since 2026-09-17) | 270 (disks) |

```bash
deploy/deploy.sh HOST status    # RUNNING / TERMINATED, and what is billing
deploy/deploy.sh HOST stop      # park
deploy/deploy.sh HOST start     # resume -- states the hourly cost and asks first
deploy/deploy.sh HOST preflight # DNS/.env/disk still right?
deploy/deploy.sh HOST           # only if the tree changed; the containers
                                # come back with the VM on their own
```

`HOST` is the config-ssh alias (`agenticrag.us-central1-a.<project>`); the
lifecycle commands read instance, zone and project out of it.

**The static IP is released.** The old address is gone; while the VM was
parked it was the largest line on the bill (~₹21/day) for an address no DNS
record pointed at. The instance now has no external access config at all,
and `deploy.sh start` refuses to start it until one is attached. To go
live again:

```bash
gcloud compute addresses create agenticrag-ip --region="$REGION"
gcloud compute instances add-access-config agenticrag --zone="$ZONE" \
  --access-config-name=external-nat \
  --address="$(gcloud compute addresses describe agenticrag-ip --region="$REGION" --format='get(address)')"
```

then B3 (DNS to the new address) and `deploy.sh HOST start`. Reserving the
address turns the ₹640/month back on the moment it exists, so do it the
same day the VM starts, not before. The old firewall rules, disks and
`.env` on the box are untouched.

---

## When one node isn't enough (the scale-out path — not needed now)

The single-node limit is the embedded store, nothing else (HTTP is stateless,
conversation state lives in the browser). To go horizontal:

1. **Extract Chroma to client/server mode** — run `chroma run` as its own
   service (or a managed vector DB), point `vector_search.py` at it over HTTP.
   Now the API is stateless and replicable.
2. **Move rate-limiting to Redis** — the in-process fixed-window counter
   (`observability.py`) is per-instance; a shared store makes the limit real
   across replicas.
3. **Put the replicas behind a managed load balancer**; Caddy's role shrinks to
   the static UI + a health-checked upstream pool, or moves to the LB.

Until the corpus and traffic actually justify it, one node is simpler, cheaper,
and — given embedded Chroma — more correct.
