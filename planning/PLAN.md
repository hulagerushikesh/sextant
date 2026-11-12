# sextant — the plan

**Status: APPROVED by the owner 2026-11-12.** This file is the single source
of direction. Where it disagrees with an older planning file, this file wins.

Read sections 1–5 to know where the project is going. Section 7 is the
working rules for Claude Code. Section 8 is the scoreboard.

---

## 1 · The goal

sextant exists to show three things that a chat model does not give you for
free, in a form other people can use:

| # | Promise | In one line |
| --- | --- | --- |
| A | **Your own documents, searchable** | A knowledge base that keeps your files and finds the right passage |
| B | **Search quality you can measure** | Every retrieval stage is kept or dropped because a number said so |
| C | **Works outside this app** | The knowledge base is a standard MCP server anyone can install and plug into their own AI client |

It is deliberately not a second Atlas. Atlas is the hosted product; sextant is
the reusable, measured building block.

## 2 · Where it stands today (checked 2026-11-12)

**Everything in the build plan is built.** Phases 0–15 and milestones 16–22
are closed. Nothing is running and nothing is billing beyond parked disks.

| Promise | State | Evidence |
| --- | --- | --- |
| A · your documents | Done | 22 documents / about 1,660 passages locally; upload, replace and delete all work |
| B · measured | Done | 65-question test set: right passage first **93%** of the time (87% with plain search); nine ideas tested and rejected with numbers |
| C · works outside | **Built, not proven with a person** | Published as `sextant-kb` 0.9.0; answers a test tool correctly. No record of anyone installing it from the public index and using it in a real AI client by following only the README |

Other facts worth knowing:

- **912 + 72 automated tests**, all passing; the online check is green.
- The tree is at 0.9.1; the public package is 0.9.0 (as far as the repo shows — not checked against the index today).
- The hosted site works and was proven with two test accounts, but it is **off by default** and costs about ₹2 each time it is switched on. Parked disks were last recorded at about ₹270 a month.
- **Outside users so far: none.** The two accounts on the hosted site are test accounts.

## 3 · What went wrong with the old plan

The work was good; the direction drifted.

- Milestone 21 was planned as **3 items and closed with 37**. Thirty-four were
  unplanned fixes found along the way, nearly all hardening the deploy scripts
  and the multi-user gate — for a site that is switched off and has no users.
- The last five weeks (6 Oct → 11 Nov) went to that hardening. None of it moved
  promise C, the one promise still unproven.
- The records became unreadable: the instruction file is **1,068 lines**, the
  queue is **79 KB**, one milestone file is **3,353 lines**. Claude loads the
  instruction file every session, which is also why replies grew long.

## 4 · The new direction: from built to used

**North-star test.** A stranger goes from an empty folder to a cited answer
from their own documents, inside their own AI client, in **ten minutes**,
following only the README.

Everything in the next four milestones serves that test. Anything that does
not is parked (section 6).

| Option | What it means | Verdict |
| --- | --- | --- |
| **A · Built → used** | Make it readable, prove the ten-minute path, show the numbers on one page, put it in front of three people | **Recommended** — it is the only unproven promise |
| B · Research at scale | Grow the library tenfold and test faster indexes | Parked — interesting, but no user has asked for scale |
| C · Freeze | Declare it finished, maintenance only | Reasonable after milestone 26 if nobody engages |

## 5 · The milestones

Four milestones, **14 items**. Each has a rule written before it starts that
says what "done" means. Milestones run in order.

### Milestone 23 — Make the project readable · ₹0 · Claude alone

*Why first:* nobody, the owner included, can currently find the state of the
project in under a minute, and every session pays for the clutter.

| # | Item | Done when |
| --- | --- | --- |
| 1 | Cut `CLAUDE.md` to rules only. Every lesson story moves, unedited, to a new `planning/LESSONS.md`; each rule keeps one line | `CLAUDE.md` ≤ 150 lines; no lesson text lost; tests that read it still pass |
| 2 | `NEXT.md` becomes the queue only: Now / Parked / Decided against. Finished tables for milestones 17–22 move to `planning/archive/` untouched | `NEXT.md` ≤ 60 lines |
| 3 | Fix what is stale in the two front pages: the README's roadmap and status rows, and `planning/README.md`'s status | Every dated claim on both pages is true on the day of the commit |
| 4 | Shrink Claude's saved notes for this project to one short state note | Topic note ≤ 80 lines; index line ≤ 2 lines |

**Rule:** all four limits met, the full check passes locally and online, and a
reader can answer "what is the goal, what is done, what is next" from
`planning/PLAN.md` alone.

### Milestone 24 — A stranger's first ten minutes · ₹0 · needs two owner steps

*Why:* promise C has only been tested from inside this checkout.

| # | Item | Done when |
| --- | --- | --- |
| 1 | **Clean-room run.** Empty folder, install the public package, add three documents, plug it into a real AI client, ask one question — following only the README. Time it; write down every stumble | A dated record with the time taken and the list of stumbles. *Downloads the package and ~120 MB of models: owner's OK first* |
| 2 | Fix the **top three** stumbles. The rest go to Parked | Each fix has a test |
| 3 | The README opens with a one-screen quickstart (install, add, plug in, ask) and one screenshot of a real cited answer. Long reference sections move to `docs/` | README ≤ 300 lines |
| 4 | **Release.** Owner publishes the current version (owner's command, always). Claude repeats the clean-room run against the published package | The repeat run meets the rule below |

**Rule:** empty folder → cited answer in a real client in **≤ 10 minutes**,
with **zero** steps that needed knowledge from outside the README.

### Milestone 25 — Proof on one screen · ₹0

*Why:* the numbers behind promise B exist but are spread over 18 notes.

| # | Item | Done when |
| --- | --- | --- |
| 1 | One results page: the four-stage comparison, the nine rejected ideas with one number each, and cost per question. Figures are generated from the measurement files, never typed | A test fails if the page and the files disagree |
| 2 | One command a stranger runs to reproduce the comparison table | Verified in the clean-room setup from milestone 24 |
| 3 | Decide the always-on demo: recorded real answers replayed in the existing interface on free hosting (clearly labelled as recorded), or screenshots only | Owner's decision recorded; if "recorded", it is live at ₹0 a month |

**Rule:** a visitor can answer "how good is it, how do you know, what did you
reject" from one page, and every figure on it is checked automatically.

### Milestone 26 — Three outside people · owner-led

*Why:* Atlas's first two users both left at an empty question box. Features
were not the bottleneck there and probably are not here.

| # | Item | Done when |
| --- | --- | --- |
| 1 | Owner picks three people and sends them the quickstart (Claude drafts the message only if asked) | Sent |
| 2 | Record what happened to each: installed? got an answer? where did they stop? | Three short dated entries |
| 3 | Fix the single most common stopping point, then choose the next phase from that evidence | One fix shipped; next phase written here |

**Rule:** three people tried it and at least **one** reached a cited answer
from their own documents without help. If none did, the next milestone is that
stopping point and nothing else.

## 6 · Parked — not now, and what would un-park each

| Parked | Un-parks when |
| --- | --- |
| Faster index tiers for large libraries | A library ≥ 25,000 passages exists **and** someone needs it |
| More multi-user and gate hardening | The hosted site has a real second user |
| More checks on the deploy scripts | A real trip fails |
| Scanned-PDF reading, tables in answers, accounts and sync | An outside user hits it |
| Licence review of the PDF library | Before any closed-source distribution |
| Keeping the hosted box at all (~₹270/month parked) | Owner decides after milestone 25 item 3 |

A new idea goes here as **one line**. It is not started.

## 7 · Working rules for Claude Code

The cost, secret and git rules in [`../CLAUDE.md`](../CLAUDE.md) still apply
in full. These rules are about direction and length.

### 7.1 Start of every session

1. Read this file's section 8. Say nothing about it; just know the current item.
2. Do **not** open `PROGRESS.md`, `LESSONS.md`, `milestone-*.md` or
   `archive/` unless the current item names them.
3. Work on the current item only.

### 7.2 Staying on direction

- **One item at a time, in order.** Finish it against its "done when", then
  move to the next. "Go next" from the owner means the next row in section 5.
- **Found a defect that is not the current item?** Fix it now only if leaving
  it would (a) cost money, (b) lose or expose someone's data, or (c) block the
  current item. Otherwise add one line to section 6 and carry on.
- **At most two unplanned fixes per milestone.** A third needs the owner's yes.
- **No new milestone, item or direction without the owner.** Propose it in the
  reply's last line; do not start it.
- If the current item turns out to be wrong or impossible, stop and say so in
  one sentence with a recommendation.

### 7.3 Reply shape — every reply, nothing more

The owner's global format applies. For this project it looks like this:

> Completed the **<what>** and pushed <where>. *(or "— nothing pushed.")*
>
> - Three to five bullets, one line each, a **result** in bold in each.
>
> One or two sentences: a link to the record, then what stayed unchanged.
>
> **Next — milestone 23, item 2 of 4 (plan: 1 of 14 done, 7%):** what comes
> next, what it waits on, and one honest sentence on what this work does not
> prove.
>
> **Nothing needed from you right now.** *(or the one thing needed)*

- One message per turn. No text between tool calls.
- **Twelve lines at most.** Plain sentences a non-engineer can read: no commit
  ids, run numbers, file lists, script names or command output unless asked.
- Money is always stated in ₹, even when it is ₹0.
- If the owner must act, ask for **one** thing, last, in bold.

### 7.4 Length limits for the records

| Record | Limit |
| --- | --- |
| A `PROGRESS.md` entry | 8 lines: date, what, the number, cost, what it does not prove |
| A row in `NEXT.md` or section 5 | 2 lines |
| A lesson in `LESSONS.md` | 3 lines |
| A rule in `CLAUDE.md` | 1 line plus a link |
| A code comment | 4 lines saying why; the story of how it was found goes in the commit message |
| A milestone's write-up | It lives in section 5 here; no separate milestone file unless it passes 60 lines |

If a record needs more than its limit, the extra goes in the commit message.

### 7.5 Stop and ask the owner before

- Anything that costs money (state the ₹ amount), any download, any publish.
- Starting the hosted box, changing a firewall rule, typing any secret.
- A third unplanned fix, or anything in section 6.
- Ticking a milestone's rule as met — say what the evidence is and let the
  owner confirm.

## 8 · Scoreboard

**Build goal:** complete (phases 0–15, milestones 16–22).
**Use goal:** **1 of 14 items (7%).**
**Current item:** milestone 23, item 2 — `NEXT.md` becomes the queue only.

| Milestone | Items | Done | State |
| --- | --- | --- | --- |
| 23 · Readable | 4 | 1 | item 1 done 2026-11-12: `CLAUDE.md` 1,068 → 130 lines |
| 24 · Ten minutes | 4 | 0 | — |
| 25 · Proof on one screen | 3 | 0 | — |
| 26 · Three people | 3 | 0 | — |

Update this table and the three lines above it in the same commit that
finishes an item. It is the only place progress is counted.

## 9 · Waiting on the owner

1. ~~Approve this plan~~ — approved 2026-11-12.
2. Later, inside milestone 24: OK the clean-room download, and publish the release.
3. Later, after milestone 25: keep or remove the hosted box.
