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
curl -u rush:PASSWORD https://agenticrag.hulage.in/health
# {"status":"healthy","mcp_connected":true,"model_configured":true,...}
```

---

## B6 · Load the corpus + guardrails

```bash
# Ingest the committed corpus into the VM's Chroma volume, then restart the api
# so it reloads the persisted store (it holds a stale segment after CLI ingest).
ssh USER@IP 'cd ~/agenticrag && \
  docker compose -f docker-compose.prod.yml exec api agenticrag-ingest eval/corpus -r && \
  docker compose -f docker-compose.prod.yml restart api'

# A real gated query end to end:
curl -u rush:PASSWORD -s https://agenticrag.hulage.in/query \
  -H 'content-type: application/json' \
  -d '{"query":"What does the Kalman filter do in tracking?"}' | head
```

**Cost + durability guardrails (do these — they're the difference from a dumb deploy):**

```bash
# Monthly budget alert, scoped to THIS project so other projects on the same
# billing account don't count. Emails billing admins at 50/90/100%.
# (The amount is a bare number -- `20USD` is rejected as an invalid argument.)
gcloud services enable billingbudgets.googleapis.com
gcloud billing budgets create --billing-account=YOUR_BILLING_ID \
  --display-name="agenticrag monthly" --budget-amount=20 \
  --filter-projects="projects/$PROJECT" \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0

# Nightly snapshot of the Chroma disk (retention 14 days).
gcloud compute resource-policies create snapshot-schedule agenticrag-daily \
  --region="$REGION" --max-retention-days=14 \
  --daily-schedule --start-time=03:00 --on-source-disk-delete=apply-retention-policy
gcloud compute disks add-resource-policies agenticrag-data \
  --zone="$ZONE" --resource-policies=agenticrag-daily
```

App-level, the rate limiter (`AGENTICRAG_RATE_LIMIT` / `_WINDOW`) already caps
per-IP request rate; tighten it in `.env` if the gate is shared widely.

---

## Redeploying

```bash
deploy/deploy.sh USER@IP          # rsync changes, rebuild, restart
deploy/deploy.sh USER@IP down     # stop
```

The box `.env` and `/data` are never touched by a redeploy.

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
