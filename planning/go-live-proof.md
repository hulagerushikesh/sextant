# Go-live proof — 2026-09-15

`https://agenticrag.hulage.in`, single GCP VM (`agenticrag`, e2-standard-2,
us-central1-a), Caddy edge, API container as uid 1001. Everything below was
observed, not assumed.

## Preflight (deploy/deploy.sh … preflight)

All 13 checks `ok`: `.env` 600, all keys set, bcrypt hash intact (60 chars),
`PUBLIC_URL` == `https://SITE_ADDRESS`, DNS → this VM, `/data/chroma`
writable and owned by uid 1001, docker + compose present.

## Ship (deploy/deploy.sh … up)

Tree shipped as tar over ssh; image rebuilt on the box (rename + non-root);
`agenticrag-api-1 Up (healthy)`, `agenticrag-caddy-1 Up`. Caddy log:
`certificate obtained successfully  identifier=agenticrag.hulage.in
issuer=acme-v02.api.letsencrypt.org-directory`.

## Edge, from the laptop

| request | result |
| --- | --- |
| `GET /health`, no credentials | **401**, `WWW-Authenticate: Basic realm="restricted"` |
| `GET /health`, wrong password | **401** |
| `GET /`, no credentials | **401** (the SPA is behind the gate too) |
| `http://…/` | **308** → `https://agenticrag.hulage.in/` |
| TLS | Let's Encrypt (CN=YE1), valid to 2026-12-14, TLS 1.3, h2 |
| headers | `strict-transport-security: max-age=31536000; includeSubDomains`, `x-content-type-options: nosniff`, `x-frame-options: DENY`, `referrer-policy: strict-origin-when-cross-origin` |

## Inside the box (bypassing the gate, `docker compose exec api`)

- `sextant-ingest eval/corpus -r` → `collection: 21 documents, 52 chunks`;
  api restarted to reload the segment.
- `/health` → `healthy`, `mcp_connected: true`, `model_configured: true`,
  daily budget on.
- `POST /query {"query":"What is the Kalman gain?"}` → `success: true`,
  three cited passages from *The Kalman Filter*, 3,351 in / 534 out tokens,
  **$0.0016**, `abstained: false`.

Not exercised from here: an authenticated request through the gate. The
gate password is the owner's and is never handled by the agent; the owner
confirms it from a browser.

## Cost of this session

VM started 06:5x UTC; ~₹5.6/hour while up. Gemini: one free-tier query.
