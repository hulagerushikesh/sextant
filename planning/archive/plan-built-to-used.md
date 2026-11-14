# The plan's sections 3–5 as approved 2026-11-12 (built → used)

Moved here unedited on 2026-11-14 when phase 3 was approved. Milestones 23–25
are finished; milestone 26 carries over into the current plan.

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
| 1 | **Clean-room run.** Empty folder, install the public package, add three documents, plug it into a real AI client, ask one question — following only the README. Time it; write down every stumble | A dated record with the time taken and the list of stumbles. *Downloads the package and ~180 MB of models: owner's OK first* |
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
