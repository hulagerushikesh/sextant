# Milestone 19 — the redesigned UI becomes the UI

`ui-redesign/sextant` has been finished and unmerged since 2026-09-13, with
one instruction on it: *"port only after review."* This milestone is that
review and that port.

Nothing here costs money. The port is local, the gate is local, and the
deploy is deliberately **not** in this milestone — putting it on the box
needs a VM trip, and that trip should carry the `.env` rewrite and the key
rotation with it rather than being spent on a UI alone.

## What is actually being ported

| | Current `frontend/` | `ui-redesign/sextant` |
| --- | --- | --- |
| Stack | Vite 4, React 18, **JavaScript** | Vite 7, React 19, **TypeScript** |
| Styling | 1,952 lines of hand-written `App.css` | Tailwind v4 + shadcn (radix-nova), OKLCH tokens |
| Charts | hand-drawn SVG (`SweepChart.jsx`, 200 lines) | Recharts via shadcn `chart` |
| Palette | hand-rolled ⌘K (`Palette.jsx`, 147 lines) | cmdk |
| Bundle | **190 kB JS / 61.5 kB gzip** | **1,017 kB JS / 314 kB gzip** |

Both build clean today. The redesign mirrors the backend contract in
`src/lib/types.ts` and reads `VITE_SERVER_URL`, which is the one value
`deploy/Dockerfile.caddy` passes as a build arg — so the production build
path needs no change. `VITE_MOCK` lives only in `.env.development`, which
Vite does not load in build mode, so a production bundle is mock-free by
construction rather than by remembering.

## 1 · Close the four post-scan gaps — ₹0

**This is the whole risk of the milestone.** The redesign was scanned on
2026-09-13 and four things shipped to `frontend/` afterwards. Porting
without them is a silent feature regression, which is the one way a
redesign that looks better is worse.

| Gap | Shipped in | Where it is missing |
| --- | --- | --- |
| GFM table rendering in answers | `fc84ebd` | `answer.tsx` has no table construct; `Answer.jsx` has `TABLE_ROW`/`TABLE_RULE`, alignment from the rule, and the streaming rule that a lone header row stays a paragraph until `\|---\|` arrives |
| Conversation → Markdown export | `fc84ebd` | `export.js` (77 lines) has no counterpart at all |
| `sextant.*` storage keys with a one-time migration | `13e5c24` | `store.ts` hardcodes `agenticrag.conversations.v1` / `agenticrag.usage.v1`; `storage.js` moves each key on first read and deletes the old name |
| Docked composer that grows | `948ffdb` | `composer.tsx` takes `hasMessages`, so the shape is there — confirm the grow-and-dock behaviour matches before calling it done |

Also check `1d81c7d` (floor-fallback knob) for any surface it added.

**Decision rule, pre-registered:** the port does not land until every one of
the four is closed. A gap that turns out to be genuinely unwanted gets
written down as a removal with a reason, not dropped silently.

## 2 · A bundle budget — ₹0

314 kB gzip against 61.5 kB is **5.1×**, and it buys a design system, not a
feature. Most of it is Recharts, which exists for the Lab view alone — a
benchmark sweep nobody opens on the way to asking a question.

**Change.** Lazy-load the Lab route so the first paint does not pay for the
benchmark view.

**Decision rule, pre-registered:** initial gzip ≤ **120 kB**. If lazy-loading
Lab does not get there, the number goes in this file with what is left in
the chunk, and the port still lands — the budget is a target, and shipping
a stale UI to protect it would be the wrong trade.

**Result: missed, 186.8 kB. The port lands anyway, under the rule above.**

| Step | Initial JS (gzip) |
| --- | --- |
| as found | 315.3 kB |
| Lab lazy-loaded (Recharts into its own 123.4 kB chunk) | 192.7 kB |
| ⌘K palette lazy-loaded (cmdk, 7.0 kB chunk) | **186.8 kB** |

The Lab split was the whole win; the palette bought 6 kB. What is left is
React 19, Radix, Motion and the shadcn primitives themselves — a design
system, which is what was chosen, not an accident to be optimised away. It
is **3.0× the hand-written UI's 61.5 kB**, and that is the honest price of
the trade. Two further levers exist if the number ever matters: auditing
which Radix primitives the `radix-ui` barrel actually tree-shakes, and
dropping Motion for CSS transitions. Neither is worth doing on a hunch, and
neither is in this milestone.

**Node note, found during the build:** Vite 7 now prints *"You are using
Node.js 20.12.2. Vite requires Node.js version 20.19+ or 22.12+"* on this
machine. It warns and builds. Production is unaffected —
`deploy/Dockerfile.caddy` builds on `node:22-alpine` — but the local gate
runs here, so the day that warning becomes an error the gate breaks before
production does.

## 3 · The port itself — ₹0

`frontend/` is replaced wholesale, not merged file by file: the two trees
share no styling system, and a half-ported app is worse than either.

- `package-lock.json` comes across — `Dockerfile.caddy` runs `npm ci`.
- The container builds on `node:22-alpine`, so the Vite 7 pin is a *local*
  constraint (this machine is on Node 20.12), not a production one. It
  stays pinned anyway, because the gate runs here.
- `npm run build` is already in the gate and must stay green; `tsc -b` now
  runs as part of it.

**Shipped 2026-09-27.** Verified live against the agent server on `:8100`, not
just built: health and stats 200, the rail showing 22 documents / 2,318 chunks,
a conversation asked and saved, the table construct rendering with its `---:`
alignment and citation chips inside cells, the ⌘K palette lazy-loading and
carrying *Export as Markdown*, the composer growing with its content, and both
themes.

Three things the port turned up that the review would otherwise have shipped:

1. **A stale CLI name.** The onboarding card told a first-time user to run
   `agenticrag-ingest -r ./docs` — a command 0.8 deleted. Found by reading the
   running page, not the diff.
2. **A tracked env file outranking an untracked one.** The `.env.development`
   this milestone added set `VITE_SERVER_URL`, which takes precedence over
   nothing but still beat the developer's gitignored `.env.local`, pointing the
   UI at `:8000` instead of `:8100`. It now sets `VITE_MOCK` alone.
3. **A mock that never rendered a table.** `lib/mock.ts` exercises every
   construct the renderer supports now, so design work cannot miss one.

## Not in this milestone

- **Deploying it.** ≈₹3 of VM time, and it should ride with the `.env`
  rewrite (`SEXTANT_*` names) and rotating the `GEMINI_API_KEY` that was
  exposed in a pasted screenshot on 2026-09-23 and confirmed still live on
  2026-09-27. Three jobs, one trip.

  *The fourth — dropping the `AGENTICRAG_` fallback — was done locally on
  2026-09-28 (0.8.1) instead, because it costs nothing and needs no box. The
  deploy order is now load-bearing: the `.env` rewrite happens **before** this
  tree is built on the box, or the running container loses its budget cap and
  CORS allowlist to defaults. `settings.legacy_warning()` prints exactly which
  names are stale at startup, so a missed one is visible in `docker logs`
  rather than silent.*
- **Multi-corpus / per-user upload.** Still a design question.
- **Request-level index tier.** Needs ≥25k chunks; the store holds 79.
