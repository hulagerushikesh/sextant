# sextant — the plan

**Status: APPROVED by the owner 2026-11-12; phase 3 (sections 3–6) approved 2026-11-14.** This file is the single source
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
are closed. Nothing is running and, since the hosted box was removed on
2026-11-13, nothing in the cloud is billing.

| Promise | State | Evidence |
| --- | --- | --- |
| A · your documents | Done | 22 documents / about 1,660 passages locally; upload, replace and delete all work |
| B · measured | Done | 65-question test set: right passage first **93%** of the time (87% with plain search); nine ideas tested and rejected with numbers |
| C · works outside | **Built, not proven with a person** | Published as `sextant-kb` 0.9.1; from an empty folder it answers a test tool correctly in about 2 minutes (2026-11-13). No record of anyone installing it from the public index and using it in a real AI client by following only the README |

Other facts worth knowing:

- **939 + 72 automated tests**, all passing; the online check is green.
- The public package is 0.9.1, the same as the tree (published by the owner and confirmed by installing it, 2026-11-13).
- The hosted site worked and was proven with two test accounts (2026-11-04). The owner **removed the box on 2026-11-13**; the recipe to build one again is `deploy/README.md`.
- **Outside users so far: none.** The two accounts on the hosted site are test accounts.

## 3 · What the history teaches

The first plan (built → used, 2026-11-12) is in
[`archive/plan-built-to-used.md`](archive/plan-built-to-used.md), unedited.

1. The measuring habit is the project's real asset. It is the one thing the
   many similar projects do not show.
2. Work drifted whenever there was no outside person to answer to: milestone
   21 was planned as 3 items and closed with 37, hardening a site with no users.
3. The stated weak point of the numbers is still open: the test questions
   were written alongside the test documents, so the figures grade the
   pipeline, not anyone else's library.

**The field (looked up 2026-11-14).** Local "search your documents from an AI
assistant" servers are now common: a single search turned up more than ten.
They compete on file formats and folder watching. The most popular one found
shows 88 stars in a third-party listing (unverified). None of those found
publishes search-quality numbers, and none tells a user how well it works on
that user's own files.

## 4 · The direction: from used to trusted

> **The knowledge base that shows its working — on public benchmarks, and on
> your own documents.**

Three steps up from where it stands, each one resting on the one before:

| Step | Today | After this phase |
| --- | --- | --- |
| **Install** | Four terminal steps, 530 MB | One click in Claude Desktop; one pasted line elsewhere |
| **Trust** | Numbers on our own 21 documents | The same pipeline scored on public test sets anyone can compare, plus **a report card for the user's own library** |
| **Reach** | Zero outside users | Listed where people look, launched with the measurement story, and its measuring kit usable on *any* such server |

**North-star test.** A stranger installs with one click, points it at a
folder, gets a cited answer, and within five more minutes sees a score for
how well search works on *their* documents.

**What "big" means, as numbers** (checked 30 days after launch): at least
**100 stars**, at least **10 strangers** who wrote an issue or comment, and
at least **3** who say they still use it. These are not in our control; they
are the test of whether the direction was right.

## 5 · The milestones

Seven milestones, **26 items**, after the 11 finished in milestones 23–25. Same rules as before: in order, one item at a
time, each milestone's rule written before it starts.

### Milestone 26 — Three outside people · owner-led · ₹0 *(approved 2026-11-12)*

Three items: the owner picks three people and sends them the quickstart; what happened to each is recorded in a short dated entry; the single most common stopping point is fixed. **Rule:** three people tried it and at least **one** reached a cited answer from their own documents without help. It runs **after milestone 27**, so the three people get
the one-click version. First the owner's own ten-minute try in Claude Desktop.

### Milestone 27 — One click · ₹0

*Why first:* every later step is worth nothing if people stop at a terminal.

| # | Item | Done when |
| --- | --- | --- |
| 1 | A Claude Desktop bundle: double-click, choose a folder, ask | Installed on the owner's machine from the file alone |
| 2 | A no-setup line for other assistants (Claude Code, Cursor, VS Code) | One pasted line works in two of them |
| 3 | **Slim engine.** Run the two search models without the 900 MB library they need today. Pass rule: no figure on the results page drops by more than 0.02 | Install under 200 MB, first answer under 10 seconds, the quality check still green — or the idea is rejected with its numbers, like the other nine |
| 4 | A quiet first run: no warnings that read as errors *(un-parks two parked lines)* | A clean-room run prints nothing alarming |
| 5 | Release 0.10 with working links on the package page; listed in the official MCP registry. *Owner's commands* | The listing and the page are checked from outside |

**Rule:** empty machine → cited answer in Claude Desktop in **3 minutes** of
a person's time, with **no terminal**.

### Milestone 28 — Numbers anyone can compare · ₹0 · one download to approve

*Why:* it answers the honest caveat on the results page.

| # | Item | Done when |
| --- | --- | --- |
| 1 | Score all four search stages on three public test sets (about 3,600, 5,000 and 57,000 documents) with the field's standard measure | Figures sit beside the published baseline for each set |
| 2 | Speed and memory at 57,000 documents *(un-parks the faster-index line if it is slow)* | Search time and memory on the results page |
| 3 | Re-test the two closest rejected ideas on the public sets | Each is kept rejected or adopted, by the same kind of rule |
| 4 | The results page and its one command cover the public sets | A stranger reproduces one public set with one command |

**Rule:** every figure is generated and checked automatically, and **if the
pipeline loses to a plain baseline anywhere, the page says so in its first
screen.**

### Milestone 29 — A report card for your own library · about ₹20

*Why:* this is the feature nobody else has, and the reason to choose sextant.

| # | Item | Done when |
| --- | --- | --- |
| 1 | A self-test: the user's own assistant writes a question for each of a sample of passages; sextant checks whether search finds the passage it came from. No key, nothing sent anywhere new | Works in Claude Desktop on a fresh library |
| 2 | **Prove the self-test is honest.** On the public sets, where the true answers are known, the self-test score must rise and fall with the true score. Pass rule written first | It passes, or the feature ships labelled "rough guide" or is dropped |
| 3 | The report: one score, the questions it missed, and documents that cannot be searched at all (scanned, empty, duplicated) | Readable by a non-engineer in one screen |
| 4 | One suggestion the report can back with a number (for example "these 4 files are scanned") | Each suggestion links to its evidence |

**Rule:** a stranger gets a score for their own library within **5 minutes**
of the first answer, and the results page shows how far that score can be
trusted.

### Milestone 30 — What the first users stopped at · ₹0

Three items, **chosen from milestone 26's evidence, not now.** Likely
candidates: keeping a folder in sync as files change, Word and web-page
files, scanned PDFs. **Rule:** the two most common stopping points are gone.

### Milestone 31 — Launch · owner-led · ₹0

| # | Item | Done when |
| --- | --- | --- |
| 1 | One write-up: "nine ideas measured and rejected, and what the public numbers said" | Published by the owner |
| 2 | A 90-second screen recording: install, ask, report card | In the README |
| 3 | The owner posts it in three places where such tools are discussed | Posted |
| 4 | Every question answered for two weeks; each one recorded in one line | A dated list |

**Rule:** the three numbers in section 4 are read 30 days after posting and
written down, whatever they are.

### Milestone 32 — The measuring kit for any knowledge base · only if 31 lands

| # | Item | Done when |
| --- | --- | --- |
| 1 | The public-set scorer and the self-test work against any search server that speaks the same protocol, not only sextant | Run against two other open-source servers |
| 2 | A comparison page: five popular servers, same sets, same measure, methods published so each author can reproduce it | Generated, with a test |
| 3 | Authors are told before it is published and may correct their setup | Recorded |

**Rule:** the comparison is reproducible by someone who is not us. This is
the step that makes the project a reference point rather than one more server.

### Decision points

| After | If | Then |
| --- | --- | --- |
| 26 | None of three people reaches an answer | The next work is that stopping point only |
| 28 | The pipeline is ordinary on public sets | Say so, fix the weakest stage first, and re-plan 29 |
| 29 item 2 | The self-test does not track the truth | Drop the headline; the phase's big idea becomes milestone 32 |
| 31 | Under 25 stars and no stranger writes in | Freeze: maintenance only, written up honestly |

### Cost, effort and risk

- **Money:** about **₹20** in total (model calls to validate the self-test),
  well inside the daily cap. Downloads of the public sets need the owner's OK.
- **Effort:** roughly eight to ten weeks of working sessions; milestones 26
  and 31 move at the owner's pace.
- **Owner's part:** the Desktop try, each release and listing, picking three
  people, the launch posts.
- **Risks, plainly:** the field is crowded; public numbers may be
  unflattering; the self-test may fail its own check; attention cannot be
  planned. Each has a decision point above rather than a hope.

## 6 · Parked — not now, and what would un-park each

What does not change: every stage and feature is kept or dropped on a number,
rule first. It runs on the user's machine — **no hosted site, no accounts, no
usage tracking.**

| Parked | Un-parks when |
| --- | --- |
| Faster index tiers for large libraries | Milestone 28 item 2 measures search as slow at 57,000 documents |
| More multi-user and gate hardening | A hosted site exists again **and** has a real second user |
| More checks on the deploy scripts | A box is rebuilt and a real trip fails |
| Scanned-PDF reading, Word and web-page files, folder sync | Milestone 30 picks it from what the first users stopped at |
| Tables in answers, accounts and sync between machines | An outside user hits it |
| Licence review of the PDF library | Before any closed-source distribution |
| Rebuilding a hosted box (removed by the owner 2026-11-13; it cost ~₹270/month parked) | An outside user needs a shared deployment |
| Two assistants (e.g. Claude Desktop and Claude Code) sharing one store at once — untested | Anyone reports a store error with both running |

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
  move to the next. "Go next" from the owner means the next row in section 5, with milestones in the order of the scoreboard (27 before 26).
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
> **Next — milestone 27, item 4 of 5 (plan: 14 of 37 done, 38%):** what comes
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
**Plan:** **14 of 37 items (38%).**
**Current item:** milestone 27, item 4 — a quiet first run: no warnings that read as errors.

| Milestone | Items | Done | State |
| --- | --- | --- | --- |
| 23 · Readable | 4 | 4 | done 2026-11-12. **Rule not yet ticked — the owner confirms** |
| 24 · Ten minutes | 4 | 4 | done 2026-11-13: an empty folder reaches a correct answer in about 2 minutes of machine time ([`clean-room.md`](clean-room.md)). **Rule not yet ticked: it needs the owner's own try in Claude Desktop** |
| 25 · Proof on one screen | 3 | 3 | done 2026-11-13: [`docs/RESULTS.md`](../docs/RESULTS.md) is generated and tested; the owner chose screenshots only. **Rule not yet ticked — the owner confirms** |
| 27 · One click | 5 | 3 | items 1–3 done 2026-11-15; item 3: no torch, 166 MB download (476 MB on disk), first answer 7 s, every figure unchanged. Item 4 built: quiet with the models cached; the cold-download run waits on the owner's yes to a 181 MB download |
| 26 · Three people | 3 | 0 | runs after 27, so they get the one-click version |
| 28 · Numbers anyone can compare | 4 | 0 | — |
| 29 · Report card for your library | 4 | 0 | — |
| 30 · What the first users stopped at | 3 | 0 | items chosen from milestone 26's evidence |
| 31 · Launch | 4 | 0 | — |
| 32 · Measuring kit for any knowledge base | 3 | 0 | only if 31 lands |

Update this table and the three lines above it in the same commit that
finishes an item. It is the only place progress is counted.

## 9 · Waiting on the owner

1. Reinstall the rebuilt bundle (`dist/sextant-0.9.1.mcpb`) so the rest of Downloads indexes; say if anything is reported as not indexed.
2. Confirm the rules for milestones 23 and 25 are met.
3. Milestone 27: OK each download it needs when asked; publish 0.10 and the registry listing when item 5 is reached.
4. Milestone 26: pick three people — after milestone 27.
