# Clean-room run — 2026-11-12

Milestone 24, item 1. An empty folder and an empty home directory on the
owner's laptop (macOS, Python 3.12, fast connection), the **published**
package, no cache, following only the README's quickstart.

## Time taken

| Step | Time | What arrived |
| --- | --- | --- |
| Create the environment | 2 s | — |
| `pip install sextant-kb` (got 0.9.0) | 67 s | 356 MB of libraries |
| Add three documents (PDF, Markdown, text) | 31 s | first search model, 87 MB |
| Connect over MCP, list six tools, first question | 21 s | second search model, 87 MB |
| **Total machine time** | **about 2 minutes** | **about 530 MB** |

The first question returned the right passage with its file name and page.

## What this run did not do

**No AI assistant was involved.** The laptop's only MCP client is Claude
Desktop, and its settings are the owner's to change. The server was started
the way a client starts it — the bare command, a clean environment — and
asked through the protocol by a script. Pasting the config into Claude
Desktop and asking there is still unproven, and so is the ten-minute rule,
which includes a person's typing and reading.

## Stumbles, in the order met

| # | Stumble | Outcome |
| --- | --- | --- |
| 1 | The published `sextant-eval` crashes: its documents and questions were not in the package | **Fixed** in the tree, with a test |
| 2 | The first question waits 20 s in silence while a model downloads | **Fixed**: adding documents now fetches it, with tests |
| 3 | An old Python fails with "no matching distribution"; the config needs a full path the reader had to hunt for | **Fixed** in the quickstart, with tests |
| 4 | Adding documents prints a "set a HF_TOKEN" warning twice and a note about a missing key; both look like errors | README says the key note is expected; the warning is parked |
| 5 | The server logs every model-download request | Parked |
| 6 | The package's page on the index shows the old README until the next release, and its relative links do not work there | Checked on the 0.9.1 page 2026-11-13: the new README shows; the screenshot and 13 links do not work. Parked until the next release |
| 7 | The README said the models were 120 MB; they are about 175 MB | Corrected |

## Repeat run against 0.9.1 — 2026-11-13

Milestone 24, item 4, after the owner published. Same laptop, a new empty
folder and empty home, no cache, the quickstart as written. Python was 3.14
this time.

| Step | Time | What arrived |
| --- | --- | --- |
| Create the environment | 2 s | — |
| `pip install sextant-kb` (got 0.9.1) | 56 s | 356 MB of libraries |
| Add three documents (PDF, Markdown, text) | 42 s | both search models, 175 MB; it ends with "search models ready" |
| Connect over MCP, list six tools, first question | 10 s | nothing — the question itself took 8 s, down from 21 |
| **Total machine time** | **about 2 minutes** | **about 530 MB** |

The first question returned the right passage with its file name and page.
The results page's one command, `sextant-eval`, printed the first table
figure for figure in 18 seconds with no key and no further download; on
0.9.0 it crashed (stumble 1).

**Still not done:** no AI assistant and no person. The rule — ten minutes in
a real client, nothing needed from outside the README — waits on the owner
trying it in Claude Desktop.

**One new stumble, found too late to fix:** the README inside 0.9.1 says
"this tree is 0.9.1, not yet published", and that sentence is now on the
published 0.9.1's page for good. The README no longer states its own release
status, and a test keeps it that way.
