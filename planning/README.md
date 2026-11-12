# Planning

Where the project is, what it costs, and what comes next. Learning material
lives in [`../learning/`](../learning/); this folder is only about moving the
product.

| | Read |
| --- | --- |
| **Plan** | [`PLAN.md`](PLAN.md) — the goal, where it stands, the next four milestones and the working rules. Approved 2026-11-12; it outranks everything below |
| **Next** | [`NEXT.md`](NEXT.md) — the queue only: where the current item is, where parked ideas live, and what was decided against |
| **Progress** | [`PROGRESS.md`](PROGRESS.md) — what shipped, by date |
| **Lessons** | [`LESSONS.md`](LESSONS.md) — the story behind each rule in [`../CLAUDE.md`](../CLAUDE.md) |
| **Past plans** | Milestones [22](milestone-22.md) · [21](milestone-21.md) · [20](milestone-20.md) · [19](milestone-19.md) · [18](milestone-18.md) · [17](milestone-17.md) · [16](milestone-16.md) · [15](milestone-15.md) — all closed · [`go-live-proof.md`](go-live-proof.md) — what was observed when the site went live |
| **History** | [`archive/queue-through-milestone-22.md`](archive/queue-through-milestone-22.md) — the finished queue rows, unedited · [`trackers/`](trackers/) — HTML checklists from phases 9–13 · [`archive/`](archive/) — course-era docs describing features never built (`archive/README.md`) |

Operational runbooks stay next to what they operate: [`../deploy/README.md`](../deploy/README.md)
(GCP + Caddy), [`../sextant/eval/README.md`](../sextant/eval/README.md) (golden set + metrics).

## Status (last checked 2026-11-12)

The build is finished; what is unproven is use. Progress is counted in one
place only — [`PLAN.md`](PLAN.md), section 8.

| What | State |
| --- | --- |
| Phases 0–15 and milestones 16–22 | **Done** — the last closed 2026-11-04 |
| Tests | 912 Python + 72 frontend; the online check is green |
| Search quality | 93% first-result hit rate on the 55 answerable questions of 65 (dense alone 87%); 91% on the 144-page set |
| Local library | 22 documents, 1,660 passages |
| Package | this tree is 0.9.1; 0.9.0 is the published one (2026-10-24), as far as the repo records |
| Hosted site | off by default and proven from outside 2026-11-04; switching it on for a session costs about ₹2 |
| Outside users | none yet — milestones 23–26 exist to change that |
| Repository | public since 2026-09-20 (MIT) |

## Cost position

GCP project `agenticrag-rush`, billing account in **INR**.

| Resource | State | ₹/month |
| --- | --- | --- |
| VM `agenticrag` e2-standard-2 | parked (checked 2026-11-12); started only by a trip that parks itself | ≈135/day while up (≈4,100 if left on) |
| Static IP | none reserved (checked 2026-11-12); a trip takes one and releases it | 0 |
| Boot disk 30 GB pd-standard + data disk 20 GB pd-balanced | kept | ≈270 (last recorded) |
| Budget alert "agenticrag monthly" | ₹1,700 (≈$20), 50/90/100 %, as set in 2026-09 | — |
| Gemini | prepaid, capped at ₹500 a month; about ₹0.13 a question when last measured (2026-10) | by use |

**Rule:** nothing that turns a meter on (VM start, resize, new resources, bulk
API calls) happens without an explicit OK on the amount.

## Open decisions

1. ~~**Run policy once live**~~ — decided 2026-09-15: on demand.
   `deploy.sh HOST start|stop`; stop after each testing session.
2. ~~**Keep or release the static IP while parked**~~ — reversed 2026-09-17:
   released. A ₹22 day on a stopped VM traced to the idle IP (~₹21/day, the
   largest line); nothing pointed at it. Re-reserve the day the VM goes live
   (`deploy/README.md`, "Parking the VM"). Parked cost is now disks only,
   ~₹270/mo.
3. ~~**Reranker**~~ — settled 2026-09-15: it stays. Only stage with a
   calibrated abstention score; leads ranking at 1,602 chunks. See
   `../learning/reranker-decision.md`.
4. ~~**Make the repo public**~~ — done 2026-09-20. Secret sweep of 28
   commits found no key-shaped strings; email, gate username, the released
   IP and a home path were scrubbed from tracked files; MIT `LICENSE` and
   upstream attribution added. Left in history knowingly: the released IP,
   the author email, and `node_modules` from the pre-rebuild upstream
   commit `3a19674`. **Consequence, standing:** the VM's current IP never
   goes into a tracked file.
