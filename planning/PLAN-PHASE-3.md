# sextant — the next phase: from used to trusted

**Status: PROPOSED 2026-11-14. Not approved. Nothing in it is started.**
[`PLAN.md`](PLAN.md) stays the source of direction until the owner approves
this file; on approval its sections 4–6 and 8 are replaced from here.

---

## 1 · What we aimed at, and what happened

The project set out to show three things: your own documents searchable (A),
search quality you can measure (B), and a building block that works outside
this app (C).

| Period | What was done | What it left |
| --- | --- | --- |
| Sep 2026 | Rebuilt from the original AgenticRAG | An agent, a web interface, cited answers |
| Sep–Oct | Search built stage by stage, each kept or dropped on a number | **93%** right passage first on 65 questions; nine ideas rejected with figures |
| Oct–Nov | A hosted, multi-user site | Proven with two test accounts, then five weeks of hardening for no users. Removed 2026-11-13 |
| 12–13 Nov | "Built → used": records cut down, a ten-minute quickstart, one results page, version 0.9.1 published | 11 of 14 items; an empty folder reaches a correct answer in about 2 minutes of machine time |

**What is true today.** A and B are done. C is built and published, and
**nobody outside the project has used it**. No assistant and no person has
yet followed the quickstart end to end.

**What the history teaches.**

1. The measuring habit is the project's real asset. It is the one thing the
   many similar projects do not show.
2. Work drifted whenever there was no outside person to answer to (37 items
   where 3 were planned).
3. The stated weak point of the numbers is still open: the test questions
   were written alongside the test documents, so the figures grade the
   pipeline, not anyone else's library.

## 2 · The field (looked up 2026-11-14)

Local "search your documents from an AI assistant" servers are now common:
a single search turned up more than ten. They compete on file formats and
folder watching. The most popular one found shows 88 stars in a third-party
listing (unverified). **None of those found publishes search-quality numbers,
and none tells a user how well it works on that user's own files.**

That gap is exactly what this project is already good at.

## 3 · The big idea

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

## 4 · The milestones

Seven milestones, **26 items**. Same rules as before: in order, one item at a
time, each milestone's rule written before it starts.

### Milestone 26 — Three outside people · owner-led · ₹0 *(already approved)*

Unchanged, 3 items. It runs **after milestone 27**, so the three people get
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

**Rule:** the three numbers in section 3 are read 30 days after posting and
written down, whatever they are.

### Milestone 32 — The measuring kit for any knowledge base · only if 31 lands

| # | Item | Done when |
| --- | --- | --- |
| 1 | The public-set scorer and the self-test work against any search server that speaks the same protocol, not only sextant | Run against two other open-source servers |
| 2 | A comparison page: five popular servers, same sets, same measure, methods published so each author can reproduce it | Generated, with a test |
| 3 | Authors are told before it is published and may correct their setup | Recorded |

**Rule:** the comparison is reproducible by someone who is not us. This is
the step that makes the project a reference point rather than one more server.

## 5 · Decision points

| After | If | Then |
| --- | --- | --- |
| 26 | None of three people reaches an answer | The next work is that stopping point only |
| 28 | The pipeline is ordinary on public sets | Say so, fix the weakest stage first, and re-plan 29 |
| 29 item 2 | The self-test does not track the truth | Drop the headline; the phase's big idea becomes milestone 32 |
| 31 | Under 25 stars and no stranger writes in | Freeze: maintenance only, written up honestly |

## 6 · What does not change, and what stays parked

- Every stage and feature is kept or dropped on a number, rule first.
- It runs on the user's machine. **No hosted site, no accounts, no usage
  tracking.** Rebuilding a box stays parked.
- The working rules in `PLAN.md` section 7 apply unchanged, including the
  cap of two unplanned fixes per milestone.
- Still parked: multi-user hardening, deploy-script checks, accounts and
  sync, tables in answers, the PDF library's licence review.

## 7 · Cost, effort and risk

- **Money:** about **₹20** in total (model calls to validate the self-test),
  well inside the daily cap. Downloads of the public sets need the owner's OK.
- **Effort:** roughly eight to ten weeks of working sessions; milestones 26
  and 31 move at the owner's pace.
- **Owner's part:** the Desktop try, each release and listing, picking three
  people, the launch posts.
- **Risks, plainly:** the field is crowded; public numbers may be
  unflattering; the self-test may fail its own check; attention cannot be
  planned. Each has a decision point above rather than a hope.

## 8 · To approve

Say **"approve phase 3"**, or name what to change. On approval the scoreboard
restarts at **11 of 37 (30%)** — the 14 current items plus 23 new ones.
