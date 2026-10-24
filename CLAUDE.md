# sextant — working rules

Standing rules for anyone (human or agent) working in this repo. They exist
because each one was learned the expensive way.

## Scope

- This project is deliberately separate from `../atlas`. Do not read, copy
  from, or edit atlas as part of sextant work. The differentiator here is
  MCP-native tool servers plus retrieval you can measure; duplicating atlas
  would make the project pointless.
- Infra names (`agenticrag` VM, IP, `agenticrag.hulage.in`, `~/agenticrag` on
  the box) are unchanged after the rename — they name things that exist.

## Git

- `origin` = `github.com/hulagerushikesh/sextant` (public since 2026-09-20, MIT). `upstream` =
  the original course repo; **never push there**.
- **Every `gh` command needs `--repo hulagerushikesh/sextant`.** `gh` picks a
  remote by its own rules and in this checkout it picks `upstream`:
  `gh repo view` answers `SudhanshuR37/AgenticRAG`, with `WRITE`. So `gh run
  list` quietly reports another repository's runs -- the first symptom was an
  empty list for a branch that had just been pushed -- and `gh workflow run`
  would dispatch there. The never-push rule is enforced by naming a remote on
  `git push`; `gh` takes no remote, so it is not covered by it.
- CI triggers on `push` to `main` and on `pull_request` only. A branch push
  runs nothing: dispatch it with
  `gh workflow run ci --repo hulagerushikesh/sextant --ref <branch>`, and
  watch the run -- never report a fix from the commit that attempts it.
- Branch first, commit, fast-forward `main`. Autonomous commits are fine once
  an aim is stated; deploying to `main` in production is not autonomous.
- **Scan staged contents, not filenames, for secrets before every commit**
  and report the result (`git diff --cached | grep -ciE '...'` → 0 hits).

## Secrets

- `GEMINI_API_KEY` is the only key the code reads. `.env` is gitignored.
- Never type credentials. On the VM the owner runs `set-secrets.sh`; the
  gate password and key are never seen by the agent.
- `deploy/env.example` is placeholders only; keep it that way, the repo is
  public.
- Gemini billing is AI Studio **prepay** with a ₹500/month cap: a 402
  "prepayment credits are depleted" means the balance is empty, not that
  the key is bad. The owner tops up; nothing to fix in code.
- `SEXTANT_DAILY_BUDGET_USD=0.60` is set in the local `.env` and belongs on
  the VM's too; it caps the API server only — eval scripts bypass it.

## Cost

- **Ask before anything that turns on a meter** — VM start/resize, new cloud
  resources, paid builds, bulk model calls — and state the ₹ amount. The VM
  is ~₹135/day running; it is parked (stopped) by default, with **no external
  IP** since 2026-09-17 — `deploy.sh start` refuses until one is reattached.
- GCP billing account is INR: budget amounts are rupees (`1700` ≈ $20).
- **Park the box in the same turn it is started.** A trip that ends waiting on
  a human — a key to paste, a decision — parks first and restarts later.
  Restarting costs ₹2; on 2026-09-28 a box left running while waiting for a
  key rotation billed **₹703 over 125.5 hours**, against a ₹50-100/day cap.
- **A report with a gap reads as reassurance.** `deploy.sh HOST status` is named
  above as the command that says what is billing, and until 2026-10-12 it said
  it for **two of GCP's eight instance states**: the billing `case` had arms for
  `RUNNING` and `TERMINATED` and no default, so `STOPPING`, `SUSPENDING`,
  `SUSPENDED`, `STAGING`, `REPAIRING` and `PROVISIONING` printed the instance
  line, nothing after it, and exit 0. All six bill. `STOPPING` is the one that
  matters, because it is what you see when a stop was issued and has not
  finished — the moment right after a trip — and silence there is
  indistinguishable from the parked case. And an **empty** state, which is what
  a failed `describe` leaves behind, printed `agenticrag (, us-central1-a):` and
  exited 0: the check answering nothing and reporting success, which is worse
  than no check. Every state has an arm now, the default says "assume the VM
  meter is on" (wrong in the safe direction, like the grounded-search price),
  and an unreadable state exits 1 with the `describe` to run by hand.
  **A `case` with no default is a list of the states somebody thought of.**
- **The one entry point the README hands a newcomer had never been run.**
  `./start_all_services.sh` backgrounded two servers with `&` and then printed
  four URLs and "Ctrl+C to stop" unconditionally. Both children could die on
  their first line -- no uvicorn, no `dev` script -- and it printed the banner,
  scrolled their errors above it where they read as noise, and **exited 0**.
  `deploy.sh start` saying ">> up at <ip>" regardless, and `trip.sh` ending
  "agenticrag is RUNNING" with exit 0, in the script that is somebody's first
  contact with this project. It waits on `/health` now, names which half failed,
  stops the other, and exits 1. **A banner is a claim; a backgrounded process is
  not evidence for it.**
- **A dev server with no gate does not belong on every interface.** The same
  script bound `--host 0.0.0.0`. The only authentication this project has is
  Caddy's `basic_auth`, which runs on the box -- locally, with no
  `SEXTANT_PROXY_SECRET`, every caller resolves to `shared`, and `shared` owns
  the CLI-ingested corpus and may write it. So anyone who could reach the port
  could read the corpus through `/query`, spending the Gemini key against a
  prepaid cap, and replace a document through `/ingest`. `HOST` defaults to
  `127.0.0.1`; a wider bind is opt-in and says what it means. The loopback case
  prints nothing, because a warning on the documented default is one people
  learn to skip.
- **A check whose answer depends on how fast the step before it finished is not
  a check.** Both of these were found in the *fix*, by running it. The frontend
  liveness test was a single `kill -0` the instant the API came up; with a
  stubbed `curl` that is milliseconds, so a frontend exiting in 400ms was still
  alive when asked and the banner printed anyway -- the defect being fixed,
  reintroduced by the fix. It settles first now. And `cleanup` killed
  `$FRONTEND_PID`, which is the `( cd frontend && npm run dev )` *subshell*, so
  npm and Vite under it survived every stop: `set -m` and `kill -- -$PID` kill
  the group. **An orphan is only visible if something looks for it**, so the
  suite greps for its own stubs -- under a unique sentinel name, because the
  first version matched `sleep 30` and would have killed a bystander's.
- **A verdict with no consequence is not a verdict.** Seven modules define a
  `main()`; only `sextant/eval/harness.py` was ever invoked by a test. `sextant/eval/tenancy.py`
  -- the harness that settled "one filtered collection or one per owner" and
  the one you re-run when the store changes -- computed `A is ACCEPTED` or
  `A is REJECTED`, printed it, and **returned**, so the shell saw exit 0 either
  way. That is item 14 (*the gate on retrieval quality could not fail*) in the
  one eval harness item 14 did not reach. The decision and the sentence now
  come back from one function: a caller that recovered the decision by matching
  `"ACCEPTED"` in the printed line would be deciding twice, and the second
  decision would be a string match on prose the file is free to reword -- the
  same reason `deploy.sh` has one `billing_line`.
- **The name a program prints must be a name you can type.** `prog=` is what
  every usage line and every argparse error hands the operator, and
  `sextant/eval/tenancy.py` said `sextant-eval-tenancy`, which is not in
  `[project.scripts]` and never was. It is `python -m sextant.eval.tenancy` now, which
  is what the docs always said, and every `prog=` in the tree is pinned to a
  registered script or an existing module.
- **An unused variable can be load-bearing for a lie.** The module docstring
  said the subset collection goes "to a temporary directory"; it is written
  *into* the caller's store, because `subset()` passes a collection name and no
  directory and the class resolves `CHROMA_DIR`, which `main()` just set to
  `--store`. What made the claim read as true was a `scratch = mkdtemp(...)`
  that nothing was ever written to -- created and deleted empty every run, with
  `shutil` and `tempfile` imported for it alone.
- **`<=` on floats is not "within".** The pre-registered rule is *within 0.02*
  and `gap <= 0.02` rejected a result exactly at it: `0.9 - 0.88` is
  `0.020000000000000018`, so the line printed `gap +0.0200 (tolerance 0.02)`
  and then `REJECTED`, contradicting itself in one sentence. Rounded to the 4
  places `pooled()` already rounds to. Found by the boundary test written for
  the clause above, not by looking. **And a static scan must normalise before
  it matches**: the docstring check passed on the very docstring it was written
  to catch, because the claim was wrapped as `temporary\ndirectory`.
- **A flag the server computes and the UI never reads is a flag that does not
  exist.** `/health` has carried `budget.durable` since item 15, added so that
  *a figure nobody can date is not mistaken for the day's*. It goes false when
  the spend ledger cannot be written -- `/data/chroma` not writable by
  `APP_UID`, the failure `trip.sh` step 5 tells you to watch -- and then
  `spent_usd` restarts with the process while Google's meter keeps counting.
  Nothing in `frontend/` contained the word. `SpendCard` printed the number
  under **Daily cap**, appended `resets 00:00 UTC`, and put `$1.5700 left`
  beside it: three claims about the day, from a figure the server had already
  disclaimed. **And hedge every figure that comes off the number you hedged** --
  `remaining_usd` is the cap minus a spend that is too low, so it is an upper
  bound, and a careful caption beside an unqualified amount is more convincing
  than either lie alone. One `dayFigure()` returns the caption, the `at most `
  prefix and the reason.
- **A message that names a cause must have been told which cause.** `App`
  collapsed `/health` to a tone and the sidebar printed `Degraded -- no model
  key` for **every** degraded box. `model_configured` and `mcp_connected` are
  reported separately on purpose, so a box with a good key and a dead MCP
  subprocess was sent to look at the wrong half of the system -- while
  `mcp_error`, the server's own sentence about the real fault, sat unread in
  the payload and in the type. `healthLine()` returns tone, label and detail
  together; the footer renders what it is handed. **Twice in one item:**
  `checkHealth` returned `null` for a fetch that threw *and* for a 4xx/5xx, so
  `Server unreachable` was printed about a box that had just answered 503 --
  caught reviewing the fix above, which would have shipped it intact.
- **"Mirrors X" is a claim, and a type that makes it needs a test.**
  `frontend/src/lib/types.ts` says it mirrors `sextant/mcp_server/main.py` and had
  dropped `durable`, `resets_in_seconds` and `share`. That omission is the
  *mechanism* of the two bullets above: TypeScript will not let a component
  read a field the interface does not declare, so the honest flag was
  unreachable by construction. `tests/test_frontend_contract.py` asks the live
  endpoint what it sends and the file what it declares.
- **An untested tree is where the untested bugs are.** The count was 767 Python
  tests to zero frontend tests, with no frontend runner at all -- CI linted and
  built it and never executed a line. vitest + jsdom + `@testing-library/react`
  now, `npm test` in the gate and `Frontend test` in CI. The gate pin
  (`TestCiRunsTheGateWithTheSameArguments`) went red the moment the gate
  changed and stayed red until CI was taught the command, which is item 12
  working as built.
- **A function that can keep less than it was given must return what it kept.**
  `saveAll` tried three writes and, when all three threw, returned **the full
  list** -- the same value a clean save returns. `App` did
  `setSaved(saveAll(...))`, so the sidebar showed thirty conversations as kept
  and the next page load had none of them: `deploy.sh start` printing
  `>> up at <ip>` regardless, in the one place where the claim is somebody's
  data. A rung up was quieter and nearly as bad -- a successful ten-item write
  dropped twenty threads and said nothing. It returns `{saved, failed, note}`
  now, and the note sits beside the list rather than in a toast that is gone
  in four seconds.
- **A fallback ladder has to shrink.** The rungs were: everything, then ten,
  then *everything again* with the passage text stripped -- so rung three can
  be bigger than rung two, and the cheapest combination (ten, no text) was
  never reached. A quota only that would have fit lost the lot. Strictly
  shrinking now, with a test that measures each attempt's serialised length.
- **"Must agree with X" is only an instruction if X exists.** Four frontend
  headers cited `client.js` "in the main repo" and `export.js` / `storage.js`
  / `conversations.js` in "the current UI" -- every one of them deleted with
  the UI this code replaced, and "the current UI" is now this code.
  `storage.ts`'s *the two must agree* was the sole assurance on the one-shot
  `agenticrag.*` -> `sextant.*` migration of a person's saved conversations.
  **And a docstring that names its own test is a claim too** -- `export.ts`
  now names `export.test.ts`, so that file exists.
- **A warning may not be responsive.** The one mark saying a `VITE_MOCK=1`
  build is showing invented answers was `<Badge className="hidden ...
  sm:inline-flex">mock</Badge>` -- absent below 640px, on the screen with the
  least room to work it out from context, while the invented spend against
  the daily cap and a toast saying a document was indexed showed normally.
  Everything else in a header can be given up for width; the element saying
  the screen is lying cannot. A survey of every breakpoint-hidden element
  outside `components/ui/` found three: the word "Commands", the `MOD K` hint,
  and this. **And a label is not a warning** -- `mock` names a mode to whoever
  built it and says nothing to anyone else, so the sentence lives in
  `MOCK_NOTICE` and reaches `title` and `sr-only`. **And the fabricated
  response a person acts on is the one that must say so**: a fake chart is
  looked at, `Indexed 2 files -- 74 chunks` is believed.
- **Check the claim before you write it down, including in a "not done"
  note.** Items 25 and 26 both recorded the mock build as "unmarked", neither
  had opened the file, and the badge existed. Going to look is what found the
  real defect. All four places carrying the false claim are corrected in
  place, visibly, because a repository that documents other people's
  unchecked claims should show its own.
- **A detected loss that only reaches a log has not been reported.**
  `loaders._pdf_pages` catches a page whose extraction raises, logs
  `Page %d of %s could not be extracted`, and appends `""`. The comment above
  it is right -- one malformed page must not lose the other ninety-nine --
  but `_load_pdf` then does `if not text: continue`, so **a failed page and a
  blank page reduce to the same value**: no locator, no text, no record. The
  document is stored and the uploader is told `Indexed 1 file -- 240 chunks`.
  Three pages of a hundred are not in the corpus, every later search misses
  them, and the agent says "the corpus does not mention that" about a page in
  the PDF they uploaded. Item 25's `durable` one layer down, and worse: a
  wrong spend figure is at least read. `LoadedDocument.unreadable_pages` now
  carries the numbers, **both** PDF backends fill it (the pypdf fallback runs
  only where the MuPDF wheel is missing -- the one environment nobody is
  watching), and `_store` is the single place that decides and the single
  place that words it, through `unreadable_line()`.
- **Enforce a principle at every degree, not only at the easy boundary.**
  `uploads.to_document`'s own docstring says a file that parses to nothing
  "should be reported rather than stored as an empty document that silently
  matches nothing" -- and that is checked at *total* loss, because total loss
  is one `if`. Partial loss is the same sentence and the likelier case, and
  it was not checked at all.
- **A red CI run is a question, not a dice roll.** Item 28's branch failed on
  `test_searching_does_not_block_the_event_loop`, which neither of its
  commits touches; the re-run failed too. **Five workflow runs over trimmed
  branches** settled it: full branch fail x3; `main` untouched pass; `main` +
  the hardened check pass; `main` + item 28's *source only* pass; full branch
  minus three new `test_knowledge_base.py` tests pass. The shipped code is
  innocent by experiment, and the test flips when three unrelated tests are
  added **below** it in the same file. **The mechanism is not understood, and
  is written down as not understood** -- a plausible guess in the record
  becomes true forever.
- **Assert on the property, not a proxy for it.** Three wrong assertions came
  first. `ticks > (elapsed / 0.01) * 0.5` compares against the count a 10ms
  heartbeat reaches *if `asyncio.sleep(0.01)` sleeps exactly 10ms* -- idle on
  a fast machine measures **0.84**, so the whole headroom went to machine
  speed. An idle baseline measured on the same machine was better, and gave
  the number that mattered: CI reported **31.9 ticks/s busy against 98.0
  idle**, a runner at nominal speed with the loop genuinely down to a third.
  Which exposed the real error -- a loop ticking every 31ms answers `/health`
  perfectly well, so throughput was never the property. The regression in the
  test's own comment is *"ticked zero times during half a second"*: **one
  stall spanning the whole search**. `_tick_gaps()` and
  `longest < elapsed * 0.25` say that directly. **A threshold that moves when
  unrelated load is added is measuring the machine** -- scale-free and it
  stops mattering whose runner it lands on. **And a timing assertion needs a
  test that it can fail**: `test_the_starvation_check_can_fail` blocks the
  loop on purpose, the only `ASYNC251` waiver in the repo.
- **The command that sounds like the end of the bill was the one that could
  not speak.** `deploy.sh HOST down` was `exec ssh -t ... compose down`, and
  `exec` replaces this shell -- so the arm whose name reads the most like "I
  am finished paying for this" was *structurally* incapable of printing
  anything after the containers went away. Against a RUNNING box it removed
  two containers, exited 0, and said nothing about the e2-standard-2 still
  charging ~Rs5.6/hour behind them. The 2026-09-28 Rs703 failure with the
  believing one level up: the box was not forgotten, the script reported it
  shut down. `down` now keeps compose's exit status by hand and reads the
  instance state afterwards. It still does not park the box -- `down` stops
  serving, `stop` stops paying, and a `down` that parked would take the next
  deploy's restart away from whoever typed it. **An epilogue must never
  overrule the command it reports on**, so `vm_target` returns where it used
  to `exit 2` and an unreadable state is loud but exits 0.
- **The second place that needs an answer calls the first one, it does not
  copy it.** `status` already held an arm per instance state; the epilogue
  needed the same eight. A hand-written second table is `_FORWARDED_ENV` and
  the preflight key list a third time -- right on the day it is written and
  silently behind afterwards. `billing_line` is one function with two callers,
  pinned both ways: a count that fails if a copy is pasted back, and a
  per-state run of `down` compared against what `status` prints for the same
  state, because a state dropped from one caller's reach fails no count.
- **A check nobody can run is a check nobody has read.** `deploy.sh HOST
  preflight` is the only thing between a misconfigured box and a twenty-minute
  torch build, and until 2026-10-12 nothing had ever *executed* it: it needs
  GNU `stat -c`, `getent hosts`, `docker` and a real `/data/chroma`, none of
  which exist on this laptop. Run for the first time, it reported thirteen
  checks and none of them was about `SEXTANT_PROXY_SECRET` — which
  `env.example` calls REQUIRED, `deploy/README.md` lists as one of two hard
  stops, this file calls a deploy prerequisite and `trip.sh` has refused to
  build without since 2026-10-06. Empty, Caddy still forwards
  `X-Sextant-User`, the app raises `ForgedIdentity`, and the box answers
  **403 to everything** — after `up` has built. Nor was any of them about gate
  slots 2 and 3: the `.env` reader's key list named `BASIC_AUTH_USER` and
  `BASIC_AUTH_HASH` and stopped, so the bcrypt check this script's own comment
  puts first looked at one slot of the Caddyfile's three, and a slot filled on
  one side makes Caddy refuse to *start*. The script now takes a `DATA_DIR`
  override for the gate alone and is run start to finish against fixture
  `.env` files, the key list is held to `deploy/Caddyfile` and
  `docker-compose.prod.yml`, and every slot is checked. **A list of variables
  that mirrors another file by hand falls behind it silently** — second time
  after `_FORWARDED_ENV`, one directory over.
- **A stub that stands in for a GNU tool must not be written with BSD flags.**
  The `stat` stub for the preflight harness delegated to
  `/usr/bin/stat -f '%OLp'`, which on Linux means *file system* status and
  reads `%OLp` as a filename. It passed 17/17 locally and broke on CI, where
  the preflight printed a tmpfs report as the permission bits. Item 13 was
  BSD-only `tar` flags making the trip harness Mac-only; this is the same
  defect **inside the stub whose whole job is to be the GNU tool**. Implement
  that kind of stub in something with no platform flags — `python3` is on both.
- **A harness fault must never be the reason a test is green.** With that stub
  broken, every preflight check FAILed, so every test asserting a non-zero
  exit passed: **14 of 17 were green for the wrong reason** and only the three
  asserting a *pass* noticed. Stubs now print `STUB FAULT` and exit 95 on
  anything they cannot represent, and the runner asserts that string is absent
  before returning — so a broken harness fails every test instead of three.
- **A step's `if:` must not reach past its own prerequisite.** `if: always()`
  sat on CI's `Frontend build` to keep it independent of the lint. It reached
  further: a failing `Unit tests` skipped `Frontend install`, the build ran
  without `node_modules`, and CI reported `Frontend build -> failure` /
  `tsc: not found` for a tree whose frontend was fine — two failures, one
  cause, and the second one a lie. The frontend half of the gate does not
  depend on the Python half, so every frontend step now carries
  `if: ${{ !cancelled() }}`: a gate command skipped because an unrelated step
  failed is a gate command that did not run.
- **A static pin on a list and a test of what the list is used for are two
  different claims.** Deleting `SEXTANT_PROXY_SECRET` from the preflight's key
  list fails the scan; deleting the *check* while leaving the name in the list
  fails nothing the scan can see, and only the behavioural tests catch it.
  Keep both, and when only one is affordable, know which half is uncovered.
- **A stub that answers one field to a `--format` asking for three makes every
  assertion about the other two a comment.** The gcloud stub ignored
  `--format`, so `status`'s machine type and address came from nothing and the
  `(, us-central1-a)` in every test's output *was* the gap being printed. It
  honours the format now: one field for `trip.sh`'s `value(status)`, three
  tab-separated for `deploy.sh`, and nothing at all for a blank state, which is
  what the real thing does when describe fails. Third time in this harness after
  the curl stub's `-o`/`-w` and the ssh stub's `cd ""`.
- **Two doors to the meter, one check.** `deploy/deploy.sh HOST start` is the
  other command that starts the box. It had neither of `trip.sh`'s
  protections: no door check, and an ssh wait that ended either way and then
  printed `>> up at <ip>` regardless, leaving an unreachable box billing with
  a reminder to stop it by hand -- the 2026-09-28 shape in the script the fix
  for it never touched. `ssh_door` now lives in `deploy/lib.sh` and both use
  that one copy; `start` verifies ssh for real and stops the box if it never
  answers. **A door check that exists in one of two scripts is a door check in
  neither.**
- **Use `deploy/trip.sh`, not a sequence of gcloud commands.** It starts the
  box, deploys, verifies and parks — and parking is an `EXIT` trap, so it also
  happens on failure and on Ctrl-C. A checklist is what failed on 2026-09-28;
  this is the same checklist with the last step made unskippable. Leaving the
  box up takes `--keep-up`, which you have to decide to type.
- **A setting read at import time must see `.env`, and only the import graph
  decides whether it does.** `sextant/mcp_server/main.py` called `load_dotenv()` on line
  55, under twenty import lines, and Python runs the imports first -- so
  `agent.MODEL`, `observability.DAILY_BUDGET_USD`, `RATE_LIMIT_REQUESTS`,
  `RATE_WINDOW`, `DAILY_BUDGET_SHARE` and `configure_logging`'s `LOG_FORMAT`
  were every one of them evaluated against an environment the file had not
  reached. **Measured**: with `SEXTANT_DAILY_BUDGET_USD=0.60` in `.env`,
  `os.environ` held `0.60` and `DAILY_BUDGET_USD` held `0.0`, which
  `DailyBudget` documents as *disabled*. A daily spend ceiling set on a prepaid
  key and not in force, with nothing logged and nothing warned, because the
  number that would have told you is the default. The box was unaffected --
  compose's `env_file` makes those real environment variables before Python
  starts -- so this was the local run only, which is item 28's pypdf shape: the
  wrong path is the unwatched one. The load is in `sextant/settings.py` now and
  the three scattered copies are gone. **Fix an ordering by construction, not
  by being careful**: a module cannot call `settings.getenv` without importing
  `settings`, so there is no order left to get wrong. `load_dotenv` never
  overrides, so compose, CI and a shell export still win, and a test says so.
- **`sextant-judge` had never been able to start.** It loads no `.env`, so from
  a checkout it exits `GEMINI_API_KEY is not set` against the key every other
  entry point reads out of that file -- and it is the only measurement of
  faithfulness this project has, *"the failure this project most needs to
  catch"* by its own docstring. Item 21 one directory over: **a check nobody
  can run is a check nobody has read.** Nothing published was wrong; those
  numbers came from `sextant-eval-agent --judge`, which does load `.env`.
- **A measurement whose meaning depends on an environment variable it never
  reports is not a measurement.** The judge inherited `web_search_default()`
  (`SEXTANT_WEB_SEARCH`) where `agent_harness` passes `web_search=False`
  outright. The unanswerable split asks whether the system *declines* when the
  corpus cannot answer; a model allowed to search answers those questions well,
  so `correct_abstention` would have been grading Google's coverage. Loading
  `.env` is what turned a dormant setting into a live one -- **a fix can make
  another defect reachable, and that belongs in the same item.**
- **A scan that cannot tell a read from a write has to exempt files by name,
  and an exemption by name is a hole shaped like whatever is behind it.** The
  pin that no module-level environment read bypasses `settings` matches reads
  only: `faiss_ref.py` *writes* `KMP_DUPLICATE_LIB_OK` at module level and must,
  because it has to beat `import faiss`.
- Kill CPU-heavy local jobs (eval runs, model loads) at the end of a session.

### Where the money shows up

Three places, and only one of them is the bill.

| Where | What it is |
| --- | --- |
| **AI Studio / Google billing** | the **actual** charge. Prepay with a Rs500/month cap; a 402 "prepayment credits are depleted" is an empty balance, not a bad key. The authoritative number for any month. |
| `/health` -> `budget` | sextant's own running total for the UTC day: `spent_usd`, `remaining_usd`, `budget_usd`, `resets_in_seconds`, plus `owner_*` when a share is set. `durable: false` means the ledger could not be read or written, so that figure is this process's spend and **not the day's**. |
| the structured log | `cost_usd` per query (and `agent_cost_usd`, `agent_cached_tokens`) -- the per-query breakdown behind the daily total. |

What `/health` does **not** include, so it always reads low against the bill:

- **CLI ingest and eval runs are separate processes.** `sextant-ingest` and
  `sextant-judge` spend real money and no cap or tally sees it. Summaries cost
  about $0.003/document at upload. `sextant-eval` spends nothing -- retrieval
  is local.
- It is an **estimate** from a hard-coded table, `PRICING_AS_OF` in
  `sextant/mcp_server/pricing.py`, currently `2026-08` and priced for
  gemini-3.1-flash-lite ($0.25 / $1.50 per Mtok). Bump `SEXTANT_MODEL` without
  bumping those and the number understates the bill.
- **Grounded search is priced per request** at $0.014, ignoring the
  5,000/month free allowance, so grounded answers *over*state early in a month.
  Wrong in the safe direction on purpose.
- **VM time is a different line entirely** -- GCP compute, ~Rs5.6/hour running,
  disks while parked. `deploy/deploy.sh HOST status` says what is billing.

The day's tally is persisted to `.sextant-spend.json` in the Chroma directory
so a deploy or a restart does not begin the day again at zero; before
2026-10-08 it was in memory only, which made the cap a limit per process
lifetime rather than per day.

## Packaging

- **One top-level import package: `sextant`.** Until 0.9.0 it was three --
  `tools`, `mcp_server` and `eval` -- and **all three are already
  distributions on PyPI**, so the first release would have dropped three
  squatted generic names into every installer's `site-packages`. A name
  that is fine inside a checkout is not fine inside everybody else's. The
  distribution is `sextant-kb` because `sextant` is taken.
- **Build a wheel and launch it; an editable install cannot see a packaging
  defect.** An editable install resolves a directory on disk, so it is green
  on exactly the things a wheel decides. Running one found three defects in
  an hour: the hand-written `packages` list omitted the ANN subpackage, so
  every wheel it would have produced was missing the index implementations;
  `MCPServer(version=...)` was the literal `"0.4.0"` and `FastAPI(version=)`
  was `"0.3.0"`, five and six releases stale, and both are *displayed* --
  one in an MCP client's server listing, one in the OpenAPI schema at
  `/docs`. **A number with two homes falls behind in the one nobody reads.**
  Versions come from `sextant.__version__`, which reads the installed
  distribution; `TestTheVersionIsNotWrittenTwice` fails on a literal.
- **`settings.repo_root()` is the only thing that knows the tree's shape.**
  Four modules used to answer "where is the root?" with their own
  `parents[N]`. Moving the packages one level down broke two and left two
  right, and the suite caught it only because a *different* copy disagreed
  -- `observability.py`, whose own docstring says two defaults for one
  location "is exactly the kind of drift this repository keeps paying for".
  It was one of the two that broke.
- **A wheel has no repository around it.** `repo_root()` returns `None` when
  there is no `pyproject.toml` beside the package, and that decides three
  things: `.env` is not read, the subprocess gets no `cwd`, and the
  collection goes to the platform's user-data directory instead of
  `site-packages`, which `pip uninstall` would delete with somebody's
  corpus in it.
- **Splitting the dependencies splits every installer, the image included.**
  Moving `fastapi`, `uvicorn` and `google-genai` into extras is what makes
  `pip install sextant-kb` a knowledge base -- and it silently emptied the
  production image, whose `pip install -e .` then resolved without the web
  framework its own `CMD` launches. Local runs could not see it: the gate
  installs `dev`, which pulls `app`. The Dockerfile asks for `.[app]`, and
  `TestTheImageInstallsWhatItRuns` compares what the install resolves to
  against what the `CMD` needs -- reading the command, never the comment
  above it, which says `pip install -e .` too.
- **A markdown link is not Python either.** The same rename broke thirteen
  relative links -- `README.md` pointed at a directory that had moved, and
  every `../learning/...` inside `sextant/eval/README.md` resolved one level
  too shallow once the file sat a level deeper. Nothing imports a link.
  `TestEveryRelativeDocLinkResolves` walks every `.md` in the tree.
- Publishing is **the owner's command, never the agent's**: a PyPI release
  is irreversible -- a version number cannot be re-used even after a
  delete -- and it needs a token the agent must never hold.

## Local ports

- `:8100` — this project's API (safe to restart).
- `:8000` and `:8001` belong to other projects on this machine. Do not kill.
- `:3000` — Vite dev server via `.claude/launch.json` (`sextant-frontend`).
  `sextant-api` in the same file runs the agent server on `:8100`.

## Gate before a commit that touches code

```bash
./.venv/bin/pytest tests/ -q && ./.venv/bin/mypy sextant tests && ./.venv/bin/ruff check . && (cd frontend && npm run build && npm test)
```

## CI

- **Check CI after a push. The local gate passing is a different claim.** From
  2026-09-20 to 2026-10-07 every push was red on one line, 30 runs, and because
  the type check runs first `pytest` and `sextant-eval --check` never ran in
  those 17 days while five commits reported "gate green" from the local
  commands. `gh run list --repo hulagerushikesh/sextant --limit 5`.
- **An optional dependency must not decide whether the code type-checks.**
  `ignore_missing_imports = true` plus `warn_unused_ignores = true` means a
  `type: ignore` needed when a package is installed is an *error* when it is
  not. That is what broke the 30 runs: `faiss` is the `bench` extra, CI installs
  `[dev]`. Annotate the name `Any` rather than ignoring the assignment --
  `follow_imports = "skip"` types the module as `Module`, not `Any`, and does
  not help. Check both ways: plain `mypy`, and `mypy --no-site-packages`.
- **The frontend linter runs in CI only, and that is not a preference.**
  `npm run lint` (oxlint) was configured and committed at the UI port and
  invoked by nothing until 2026-10-09, so its result was *unknown*, not green.
  The first run said **11 warnings, 0 errors** across 47 files — and oxlint
  exits 0 on warnings, so adding the step as it stood would have bought a tick
  that cannot go red. `denyWarnings` is in `.oxlintrc.json` so a hand run makes
  the same claim CI does, each of the eleven is now a decision (a scoped
  override for the vendored `components/ui` tree, three in-line judgements with
  reasons, one constant moved to `components/lab/series.ts` because the rule
  was right), and `reportUnusedDisableDirectives` reports a suppression that
  stops being needed. It is **not in the local gate**: npm 10.5.0 on this
  machine will not install oxlint's platform binding even though the lockfile
  carries it with matching `os`/`cpu` (npm/cli#4828 — `npm ci`,
  `npm install --save-optional` and a clean reinstall all leave
  `node_modules/@oxlint` absent), and a gate must not claim a check the machine
  cannot run. A new suppression needs a `--` reason or
  `TestTheFrontendLinterRuns` fails.
- **An oxlint suppression goes on the line the rule reports, and the reason
  goes above it.** Established from three CI runs, not from convention. A
  multi-line reason breaks `-disable-next-line` — the "next line" becomes the
  second comment line — so the directive must be the *last* line before the
  code, with any explanation in plain comments above it. And
  `react/exhaustive-deps` reports at the closing `}, [deps])` line, where
  ESLint's convention also puts it, while `react/set-state-in-effect` reports
  at the statement. Put one in the wrong place and
  `reportUnusedDisableDirectives` says so — which is how this was found.
- **The offline `trip.sh` run is cross-platform now, and was not.** Step 3's
  tar used `--no-fflags` / `--no-mac-metadata`, which are BSD-only, and GNU tar
  *exits* on an unknown flag -- so the offline harness added 2026-10-06 could
  only ever pass on a Mac, and ten tests failed the moment CI reached them.
  Flags come from `tar --version`; the Mac ones are still passed there.
  `_run_trip(..., gnu_tar=True)` presents a GNU tar so the gate covers Linux.
- **CI must run every program the gate runs**, pinned by
  `TestCiRunsWhatTheGateRuns`, which reads the gate out of this file. CI ran
  three of its four commands until 2026-10-07: `npm run build` runs `tsc -b`,
  so a frontend type error failed only by hand.
- **And with the same arguments, which is the actual claim.** The pin above
  matches program *names*, so a CI step narrowed from
  `mypy sextant tests` to `mypy sextant` keeps the green tick
  while type-checking **one tree of four** -- checked, that pin passes it. Item
  14's shape exactly: same program, different claim.
  `TestCiRunsTheGateWithTheSameArguments` compares the arguments too. CI may run
  *more* of a command (`npm ci && npm run build`) and may not run less.
- **The gate's environment is chosen here, not by GitHub.** Items 12 and 13 were
  both the environment deciding whether the check ran. The third instance was
  the only one announced in advance, and announced on every single run: five
  actions targeted the deprecated Node 20 and were being force-run on Node 24,
  and `ubuntu-latest` migrates to Ubuntu 26.04 **gradually from 2026-10-19 to
  2026-11-19** (actions/runner-images#14748) -- which for a month makes the same
  commit pass or fail depending on which image it drew. Both warnings were
  produced by CI and read by nobody, which is item 11 in the repository's own
  check. The runner and every action are pinned to versions the gate has
  actually passed on; `.github/dependabot.yml` turns the next deprecation into a
  pull request rather than a line in a log; and
  `TestTheGatesEnvironmentIsChosenHere` fails the gate if any of that floats
  again. **Bumping is a decision someone records, so the pins are meant to be
  edited, not routed around.**
- **`sextant-eval --check` must grade the whole gate, and now proves it.**
  `--check` guarded `--store` and `--golden` but not `--modes`, so
  `--check --modes dense` graded one mode of four and printed "no regressions";
  and the baseline's `questions` count was never compared, so **deleting 60 of
  the 65 golden questions passed** (a shorter set raises every metric). It fails
  now on an ungraded baseline mode, a no-longer-reported baseline metric, a
  shorter golden set, or a missing `baseline.json` -- **no baseline is a
  failure, not a pass.** `tests/test_eval_gate.py`.
- **Plant the defect, and check the plant fails for the right reason.** A first
  plant here showed 12 of 16 tests failing, which was worthless: the signature
  had changed and most of them were `TypeError`. Revert the *body* behind the
  new signature so the logic is the only difference, then count.
- **A stub that cannot start must say so.** `_run_deploy` never set `FAKE_BOX`,
  so the ssh stub's first line was `cd ""` -- **bash 5.2 accepts that as a
  no-op, bash 5.3 calls it a null directory and fails.** Ubuntu 24.04 ships
  5.2.21, 26.04 ships 5.3.9, so the stub answered every command here and none
  on the image CI is migrating to. Two tests went red, which is how it was
  found; the worse half is the four that stayed **green while the stub was
  dead** -- including the two that assert an unreachable box gets parked rather
  than left billing, which passed with `FAKE_SSH_DEAD` forced to 0. Answering
  nothing is indistinguishable from answering correctly to any test whose
  expectation is a failure. The stub uses `:?` now, and
  `TestTheSshStubCannotFailQuietly` pins that `FAKE_SSH_DEAD` still decides the
  outcome. Third instance of the item 13 shape, after BSD vs GNU tar.
- **A counter that resets is not a cap on a day.** `DailyBudget` kept the UTC
  day's spend in memory, so every deploy and every `restart: unless-stopped`
  bounce began the day at zero. It persists to `.sextant-spend.json` in the
  Chroma directory now -- **inside** it, because the box mounts
  `/data/chroma:/data/chroma`, so `/data` does not survive a rebuild and
  `/data/chroma` does. `/health` reports `budget.durable`; `trip.sh` fails on
  false and only notes an absent key.

## Gotchas that recur

- Chroma segment goes stale after CLI ingest: restart `:8100` to see new
  chunks. To drop one document: `sextant-forget <id>` (`--list` for the ids,
  `-y` to skip the confirmation). To empty the store:
  `rm chroma_db/chroma.sqlite3` and restart.
- Re-ingesting a document is a replacement: `_store` clears its existing
  chunks first. Without that an upsert replaces `<doc>#<n>` one for one and a
  document that now makes fewer chunks leaves the surplus embedded and
  searchable (measured: 11 → 1 left ten stale chunks holding the top hits).
  Removal is a command, never an MCP tool — the model gets read tools only.
- Uploads are stored as `upload:<owner>:<stem>` since 0.8.2, not
  `upload:<stem>`. The owner comes from the `X-Sextant-Client` header the
  frontend sends (a random per-browser id in localStorage), or `shared` when
  nothing sends one — so curl, the eval harness and the CLI all land in one
  namespace, as before. **This is namespacing, not isolation**: it stops two
  people behind the shared gate silently deleting each other's chunks, and it
  hides nothing from anyone's search. That header stays untrusted by
  construction — it is the fallback when nothing better is available.
  `/ingest` is still not *namespaced* — its caller states the id outright —
  but since 0.8.5 the id it states has to be one it owns (see below).
- Since 0.8.3 there is a second, *trusted* name: `X-Sextant-User`, set by
  Caddy from `{http.auth.user.id}` and believed only when
  `X-Sextant-Proxy-Auth` matches `SEXTANT_PROXY_SECRET`. A name without the
  matching secret is a **403**, never a quiet fallback. **`SEXTANT_PROXY_SECRET`
  must be in the box's `.env` before this tree is built on it** — Caddy has no
  conditionals, so it forwards the name regardless and every request is refused
  until the secret exists. Same shape of prerequisite as the 0.8.1 rename, and
  the 403 names the variable. `deploy/Caddyfile` has three `basic_auth` slots;
  empty ones vanish before parsing (`caddy validate`), a user without its hash
  stops Caddy. `tests/test_deploy_config.py` pins the header names on both
  sides, because renaming one in Python breaks nothing a Python test can see.
- Since 0.8.4 what a tool returns is **scoped to the asker**:
  `sextant/mcp_server/scope.ScopedHost` wraps the process-global host per request and
  drops any entry carrying a `document_id` the owner may not see. Deny by
  default — it trims every result, not a named list of tools. A document is
  visible unless it is an `upload:<someone else>:*`, so the CLI-ingested
  corpus stays shared; `shared` is scoped like any other name or the whole
  thing is bypassable by dropping a header. `kb_stats` is *recomputed* from
  the scoped listing (so `/stats` now triggers a listing, which warms the
  index). The filter cannot move into the KB: an MCP tool's parameters become
  its discovered schema, and **the corpus must never be a tool argument** —
  `tests/test_scope.py::TestTheInvariant` pins that. `collection_size` on a
  *search* result is knowingly left whole-store; `agent.py` reads it.
- Since 0.8.5 the scope recognises an **id**, not a field: as a string value
  anywhere in an entry, as a *key* of a mapping (`kb_ann_compare`'s `passages`),
  and as a bare string in a list (`exact`, `missed`). 0.8.4 knew only the first,
  and only when the field was called `document_id` — so `/ann/compare` leaked
  every tenant's titles and opening 200 characters, and routing it through
  `ScopedHost` alone would not have stopped it. The check is anchored on
  `upload:<owner>:<stem>`, so prose mentioning an id is not an id; over-trimming
  would delete content and look like the feature working. Every `/ann/*`,
  `/ingest` and `/upload` call now crosses `ScopedHost`, and a tool it cannot
  classify is **refused** — `READ_TOOLS | WRITE_TOOLS` is pinned against the
  live server in `tests/test_scope.py`.
- **Writes are an allow-list where reads are a deny-list** (`identity.writable_by`
  vs `visible_to`), since 0.8.5. Re-using an id replaces that document, so a
  write is a delete first: before this, any gated user could `/ingest`
  `upload:<someone else>:<stem>` and the victim went on citing the forged text
  as their own file. A caller may write only its own namespace, and the check
  happens *before* the store is touched. `shared` — curl, the eval harness, a
  box with no identity — still owns the unnamespaced corpus, so nothing that
  worked before changed; an *authenticated* caller does not inherit it, and
  seeding the shared corpus stays `sextant-ingest`, which constructs
  `KnowledgeBase` directly on the box and never crosses the host.
- Every frontend request carries `X-Sextant-Client` via the `sent()` helper in
  `lib/api.ts`, not just `/upload`. Leave it off one call and that call is
  answered as the anonymous `shared` caller — which, since 0.8.4, means the
  browser stops seeing its own uploads.
  `tests/test_deploy_config.py::TestTheBrowserSendsWhatTheAppReads` pins it:
  the name `identity.py` declares appears in `api.ts`, in one place, every
  `fetch` in that file routes its headers through `sent()`, and no other
  frontend file calls `fetch` at all.
- **A seam is pinned on the side you can read, which is the side that is not
  the problem.** Three headers cross a process boundary; two had their other
  end in `deploy/Caddyfile` and were pinned the day they shipped.
  `X-Sextant-Client`'s other end is TypeScript, so for three versions it
  existed in exactly two files and no test named it. Renaming `CLIENT_HEADER`
  left 143 tests in `test_api.py`, `test_observability.py` and `test_scope.py`
  green — they take the constant — while every browser silently became
  `shared`, which is the defect 0.8.2 shipped to fix. Pin the seam in whatever
  language the far end is written in, even when that means reading it as text.
- Since 0.8.6 the rate limiter keys on the **authenticated** name
  (`user:<name>`) and on the client address (`ip:<addr>`) otherwise — prefixed
  so the two cannot collide. Not a fallback, a choice: an *unproven* name is a
  bucket the caller can swap by retyping a header, which is weaker than the
  address it would replace. `identity.resolve()` returns `Identity(name,
  trusted)`; `owner_of` is the name half.
- `SEXTANT_DAILY_BUDGET_SHARE` (0.8.6, default `1` = off) is the largest
  fraction of `SEXTANT_DAILY_BUDGET_USD` one authenticated name may spend in a
  day. It sits **under** the global cap, never replacing it — the cap is the
  wallet guarantee a leaked gate cannot get past, the share stops the first
  user of the day silencing everybody else. Applied only to a vouched-for
  name; an untrusted caller's spend still counts against the day but is not
  attributed. A share below 1 leaves part of the cap unspendable when one
  person is asking, which is why the default is off and the value belongs in
  the box's `.env`. `/health` reports the asker's own share, and the spend
  card tracks it — without that, being refused while the card shows money left
  reads as a bug.
- Every HTTP route is pinned on one side of the scope boundary since 0.8.7
  (`TestEveryRouteIsOnOneSideOfTheBoundary`): adding an endpoint fails the
  gate until it is declared as one that reaches the corpus or one that does
  not, and a corpus route must call `scoped(host, owner)` -- never the
  process-global `host` -- and must be rate limited. Both 0.8.5 doors and the
  0.8.6 one were *routes*; only the tool list had been pinned.
- `/stats` is rate limited since 0.8.7: scoping it in 0.8.4 made it recompute
  from a full listing, so it walks the corpus and is no longer the cheap read
  its missing limit assumed. The UI calls it once a page load, never polls.
- `/upload` answers **200 with `"success": false`** for an unreadable file, an
  unavailable tool or a failed ingest. The status code only says the request
  arrived, so anything checking an upload must read `success` /
  `documents_added` out of the body -- `trip.sh` step 7 compared the code and
  reported a tick for uploads that stored nothing.
- `deploy/trip.sh` **step 7 proves the isolation and is the only part that
  writes.** Both gate users upload the same filename through the public URL;
  each must see their own and not the other's; then the store is read directly
  for two probe documents under two distinct owners. **The forged-name check
  runs between the two uploads, never after** -- afterwards both counts are the
  same number and the check cannot fail, which is how the first draft passed
  against a proxy that forwarded the client's name. The probes are removed in
  the EXIT trap before the stop, found by *scanning* for the filename rather
  than rebuilding `upload:<owner>:<stem>`, and anything left behind exits
  non-zero. Needs `SEXTANT_TRIP_AUTH` and `_2`; costs ~$0.006 of summaries.
- `deploy/trip.sh` **checks the gate from outside the box** (step 6, since
  2026-10-06). Every other check in it runs through `docker exec` at
  `localhost:8000`, which is behind Caddy -- so the trip that deploys the gate
  had never gone through it, and a misconfigured or stopped Caddy reported
  green. The row that matters: a real user sending a **forged
  `X-Sextant-Proxy-Auth` must get 200**, because `header_up` is a *set* and the
  client's copy is replaced before the app sees it. A 403 there means Caddy
  appended instead, and the header is worthless. Credentials come from
  `SEXTANT_TRIP_AUTH` / `_2` in the operator's environment, reach curl through
  a pipe not argv, and are never printed; unset is a skip, a missing
  `PUBLIC_URL` is a failure. Still unproven: the isolation *behind* the gate --
  every check in step 6 is a read.
- `deploy/trip.sh` **step 5 judges every result it prints** (since
  2026-10-07). It used to produce six and read one. Both containers must be
  present and `Up` **by name** -- the table was printed and never read, so a box
  whose **Caddy had exited** passed step 5, and every other check there goes
  through `docker exec` at `localhost:8000`, behind Caddy, so none of them can
  see that. Step 6 covers it only when the operator exported credentials, and
  unset is a skip. `status` / `mcp` / `model` / `budget_usd` are each named when
  wrong, all at once rather than the first; `model=` in particular is the key
  rotation's success criterion and was printed and stepped over. The store check
  is a **floor, not a number** (hardcoding 21 would make every ingest a
  failure). A leftover `AGENTICRAG_*` name in the log is a counted failure, not
  a note.
- `deploy/trip.sh` **step 5's forged-name check is counted, not just printed**
  (since 2026-10-07). It asks the api container whether it believes an
  unvouched `X-Sextant-User`; the answer fed no counter, so a trip could deploy
  0.8.3+, find that a client can still name itself, and exit **0** with the box
  reported shipped. Counted only when a deploy happened — on `--no-deploy` the
  answer describes the box as it already is, and a pre-0.8.3 box answering 200
  is correct. `GATE_FAILURES` is initialised at the top of the script, not in
  step 6: step 6 runs *after* step 5 and used to zero the count before anything
  read it.
- `deploy/trip.sh` **step 0 checks the ssh door before the meter starts.**
  Port 22 is open to one `/32` on the `agenticrag-ssh` rule, and a home ISP
  moves that address whenever it likes. On 2026-10-07 a trip reserved an
  address, started the box, waited two minutes for an ssh that could not
  arrive, printed `ssh never came up` — the symptom, and nothing about the
  cause — and then, because `--keep-up` was typed, **left it billing with
  nothing deployed**. Both halves of the answer were readable from the laptop
  for free, before anything was started. Step 0 compares them by *containment*
  (a wider CIDR is still an open door) and prints the `firewall-rules update`
  that fixes it; the address is read at run time from `VM_MY_IP_URL` and never
  stored, because the repo is public. **Three outcomes, not two** — a dead
  address service says `door not checked` and the trip carries on, since a
  flaky third party must not be able to ground the box.
- **`--keep-up` does not keep up a box nothing can reach** (since 2026-10-07).
  It means *leave it up, I am going to work on it*, which presumes you can
  reach it; `SSH_UP` is set when ssh answers and the exemption requires it, so
  Ctrl-C during the ssh wait parks too. Changing a firewall rule is **the
  owner's command, not the agent's** — auto mode refuses it as an infra
  change, which is correct; the script prints the command to run.
- `deploy/trip.sh` **verifies the park, it does not just perform it.** The
  stop is `|| true` (a trap that aborts half way leaves the address reserved),
  so the state is read back, retried once if it is not `TERMINATED`, and then
  *compared*: a box still up, or an address still reserved, prints the rate and
  the manual command on stderr and makes the script exit non-zero. 0 is how a
  person reads "parked". Until 2026-10-06 the readback was only printed, and an
  offline run ended `agenticrag is RUNNING` with exit 0 -- the 2026-09-28 ₹703
  failure one level down. The check may only turn a 0 into a 1, never mask a
  reason. `--keep-up` is exempt: that one is typed on purpose.
- `/ann/benchmark` and `/ann/compare` are rate limited since 0.8.6. They were
  the only routes with no limit, and an index build over every vector is the
  heaviest thing the box does.
- faiss + torch OpenMP: `server.py` must import faiss before anything that
  pulls torch, or the KB subprocess segfaults (exit 139).
- PDFs go through PyMuPDF (`loaders._page_lines`), not pypdf: pypdf guesses
  word spacing from glyph gaps and fused 3% of arXiv 2303.18223v19. pypdf is
  the fallback only. PyMuPDF is AGPL — flag before a closed distribution.
- A Chroma collection is stamped with the embedding model that built it and
  refuses to open under another (`SEXTANT_EMBEDDER`). MiniLM and bge-small
  are both 384-d, so without the stamp a mismatch would be silent.
- Env names are `SEXTANT_*` only since 0.8.1 — the `AGENTICRAG_*` fallback is
  gone. A leftover is not read and not silent: `settings.legacy_warning()` is
  printed by the agent server and the ingest CLI with the name to move it to.
  **The deployed box's `.env` must be rewritten before this tree is built on
  it**, or the container loses its budget cap and CORS allowlist to defaults.
- MCP stdio strips the environment: anything the KB subprocess needs must be
  in `_FORWARDED_ENV` in `mcp_host.py` or it silently no-ops. The client builds
  `get_default_environment() | params.env`, and on POSIX that default is HOME,
  LOGNAME, PATH, SHELL, TERM, USER -- so that list is the whole of what the
  subprocess knows about the box. **The rule above used to read "new `SEXTANT_*`
  knobs", and the test guarding it was called `every_retrieval_knob` and named
  three of seven.** Both were true and both were too narrow, which is how
  `HF_HOME` was dropped for three versions: the image bakes 180 MB of weights
  into `/opt/models` and sets `HF_HUB_OFFLINE=1` so the first query does not
  download them, the models load *in the subprocess*, and neither name crossed
  -- so the child resolved `$HOME/.cache/huggingface`, found it empty, and
  downloaded them into a path that dies with the container. A cache path is not
  a retrieval knob, and the category in the rule decided what got checked.
  Three declared lists now, and `TestEveryVariableTheSubprocessNeedsCrosses`
  scans both sides of the seam: every variable named under `sextant/`, and every
  variable the `Dockerfile` or the compose `api` service sets, must be
  forwarded or be in `_NOT_FORWARDED` **with a reason** -- and an exemption
  whose variable nothing reads or sets any more fails too, so the table cannot
  fossilise.
- **The KB subprocess is sealed: a sealed process reads no `.env`.**
  `kb_server()` sets `SEXTANT_ENV_SEALED=1` in the child's environment and
  `sextant.settings` skips the load when it is set, before the load, so a `.env`
  cannot unseal itself. Without it the allowlist above was advisory from a
  checkout: `sextant.settings` loads `.env` at import, the child reaches it
  through `vector_search`, and every name in that file arrived -- including
  `GEMINI_API_KEY`, whose exemption says *a key that does not cross cannot
  leak from here*. Measured: the key absent from the child at exec and present
  after its first import. The container was never affected (no `/app/.env`;
  compose injects `env_file` as real variables), which is why only the local
  path had it. **A list of nine tests compared names in source files and not
  one ran the process** -- pin the child by launching it.
- **Name a pin after the boundary it guards, not after the kind of thing you
  were thinking about.** `every_retrieval_knob` is a test that cannot grow: the
  next variable to cross that boundary was not a retrieval knob, so nobody
  broke the test and nobody noticed. The same sentence is in `CLAUDE.md`'s own
  history -- `_FORWARDED_ENV` was documented as being for `SEXTANT_*` names.
  A scan driven off the declared list has no category to fall outside of.
- Results are capped at 2 chunks per document (`SEXTANT_MAX_PER_DOCUMENT`,
  dense + rerank only, score-guarded). Set it to `0` for any experiment's
  control, or dense numbers will not match notes written before 2026-09-17.
- Docker Compose interpolates `$` in `env_file` — bcrypt hashes need
  `format: raw` (already set in `docker-compose.prod.yml`). A side effect:
  every compose command on the box prints `The "ubyP" variable is not set`
  four times, because compose's *YAML* interpolation pass still reads `$ubyP`
  out of the hash. The container gets the raw value (checked: 60 chars, `$2a$`
  prefix, gate returns 401). Noise, not damage — pipe it through `grep -v ubyP`.
- The api container does not publish 8000 to the host. Verify it from inside:
  `docker exec agenticrag-api-1 curl -s localhost:8000/health`, not
  `curl localhost:8000` over ssh (that returns HTTP 000).
- `gemini-2.5-flash-lite` passes a one-shot probe and fails the tool loop
  (400 "tool call context circulation"); `gemini-3.1-flash-lite` is the
  cheapest model that actually runs it.
- `FunctionCallingConfigMode.NONE` does not stop gemini-3.1-flash-lite from
  calling a tool: the turn ends `MALFORMED_FUNCTION_CALL` with no text. The
  agent's turn cap uses a user-role note (`LAST_TURN_NOTE`) instead.
- `sextant-ingest` spends money when a key resolves: overviews are the default
  since 0.8 (one model call per document, ~$0.003 each; the 144-page survey is
  ~$0.05). `--no-summaries` for a free ingest; no key is also free, with a note.
- `sextant-eval-agent` spends money (~$0.04 / 29 questions); `sextant-eval`
  does not. Only the latter is in the gate.
- Browser-pane synthetic key presses don't fire the app's key handlers; test
  shortcuts by dispatching `KeyboardEvent`s from `javascript_tool`.
- The frontend is TypeScript + Tailwind v4 + shadcn since 2026-09-27; the gate's
  `npm run build` now runs `tsc -b` first, so a type error fails the gate.
- `frontend/.env.development` sets `VITE_MOCK` only. It deliberately does not set
  `VITE_SERVER_URL`: a tracked value there outranks a developer's gitignored
  `.env.local` and silently points the UI at the wrong port (it pointed this
  machine at `:8000` instead of `:8100` for exactly one commit). The default
  lives in `lib/api.ts`; the override lives in `.env.local`.
- `VITE_MOCK=1` renders the whole UI from `lib/mock.ts` with no server. Useful
  for design work, and the mock answer exercises every renderer construct on
  purpose — including a table — so a construct is never shipped unseen.
- Vite 7 warns `You are using Node.js 20.12.2. Vite requires Node.js version
  20.19+` on this machine. It builds anyway; production builds on
  `node:22-alpine`. The day that warning becomes an error, the gate breaks here
  before production does.
