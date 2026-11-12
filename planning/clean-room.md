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
| 6 | The package's page on the index shows the old README until the next release, and its relative links do not work there | Parked until the owner publishes |
| 7 | The README said the models were 120 MB; they are about 175 MB | Corrected |
