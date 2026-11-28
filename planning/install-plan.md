# Proposal: one clean install for every AI tool

> **Status: proposal, 2026-11-28. Not approved.** Nothing here is in
> [`PLAN.md`](PLAN.md) until the owner says yes. It comes before the
> 90-second recording, because the recording should show the install people
> will actually use.

## Who it is for

People who already use an AI coding tool — Claude Code, Codex, VS Code,
Cursor, the Claude desktop app. Mostly technical, but none of them should need
to know what Python version, model files or text-recognition data sextant
needs. One step per tool, and it either works or says in one sentence what to
do.

## What sextant needs on a computer, and where it comes from today

| Need | Size | Where it comes from today | Problem |
| --- | --- | --- | --- |
| Python 3.11–3.14 | ~20 MB | The user's own (pip route); picked or downloaded by `uv` (one-line route); carried inside the Mac Apple-silicon bundle | pip route fails on 3.10 or 3.15 with an unclear error |
| Libraries | ~170 MB | Downloaded at install | First install inside a tool can hit the tool's start-up time limit; the one-line routes run `--version` first to avoid it |
| Two search models | ~180 MB | Downloaded from Hugging Face on the **first start**, then offline; carried inside the Mac Apple-silicon bundle | The first start happens inside the tool, which may give up waiting; no way to fetch them ahead of time |
| Text recognition (Tesseract) | none | **Not needed as a program**: the PDF reader has it built in | — |
| Text-recognition language data | ~4 MB per language | Downloaded the first time a scanned PDF appears | Fails offline the first time; fine after |

So Tesseract is already solved, and Python is solved on the one-line route. The
real gap is the **first start**: models download inside the AI tool, where a
slow network looks like "sextant is broken".

## Which tools are known to work

| Tool | How it installs | Tried by a real person |
| --- | --- | --- |
| Claude desktop app (Mac, Apple silicon) | `.mcpb` file, double-click | Yes — three testers and a friend's laptop |
| Claude desktop app (other computers) | `.mcpb` file; downloads Python and libraries | Partly — two of three got stuck on the Python download |
| Claude Code (terminal) | One pasted line | Yes — the owner |
| VS Code | One pasted line | **No** |
| Cursor | Config snippet | **No** |
| Codex | Not written down yet | **No** |
| Windows, Linux, Intel Mac | — | **No** — no one has run it there |

### What the `.mcpb` file is for

A `.mcpb` file is an MCP bundle. Today it opens only in the **Claude desktop
app** — the one with Chat and Code tabs, which is why double-clicking it opened
"Claude Code" there. The format is open and meant for other apps too, but no
other tool was found that opens it (checked 2026-11-28). The terminal Claude
Code, Codex, VS Code and Cursor do not use it; they get the one pasted line.

## The proposal: five items

1. **A setup command that fetches everything ahead of time.**
   `sextant-kb --setup` downloads the libraries (by running), both search
   models and the English text-recognition data, then prints "ready" and the
   folder it will search. The one-line routes run it instead of `--version`,
   so the tool's first start downloads nothing and works offline. **Done
   when:** with the network off after setup, a fresh tool starts sextant and
   answers a search.
2. **A check command for when it does not work.** `sextant-kb --doctor`
   answers in plain sentences: which Python, whether the models are present,
   whether the folder exists and can be read, whether another program holds
   the library. Each failure names the one fix. **Done when:** each of those
   four failures, set up on purpose, prints its fix.
3. **One "pick your tool" table in the README.** Claude desktop app → the
   `.mcpb` file. Claude Code, Codex, VS Code, Cursor → one line each,
   including **Codex** (`codex mcp add`, or a `~/.codex/config.toml` block
   with a longer start-up time limit). Each row says whether a real person has
   tried it, with the date. **Done when:** every row is tried or marked "not
   tried".
4. **Install tested on Windows, Linux and Intel Mac by CI.** GitHub's runners
   for public repositories cost ₹0. One job per system installs the package
   from the built wheel, runs `--setup`, indexes the test documents and
   answers one search through the MCP protocol. **Done when:** all three are
   green, or a red one is written down as a known limit in the README.
5. **The owner tries VS Code and Codex** (today) and the results go in a dated
   list. A failure becomes a fix before the recording.

### Found in the first Codex test (2026-11-28)

- **Codex started sextant correctly**: it indexed the 21 demo documents in
  about 6 seconds. The model then answered that it could not reach the tool.
  The question was asked one second after Codex opened, before sextant had
  finished starting. **Re-tried in a Codex task: it worked.** Asking in the
  ChatGPT app's plain chat does not reach it at all — that chat runs no
  program on the computer (see below).
- **Every tool shares one library.** Codex was pointed at a demo folder, but
  searched the same library as the owner's Claude setup (5,657 passages), so
  private documents can answer a question asked from any tool. The README
  does not say so. Decide: say it plainly, or give each folder its own
  library.
- **sextant contacted huggingface.co at start** with the models already
  downloaded. The README says it works offline after the first run. A newer
  Hugging Face library is the likely cause; not yet checked. Item 1 must
  include a start with the network off.

### ChatGPT's plain chat

The Claude desktop app runs sextant in both its Chat and Code tabs. The
ChatGPT app runs it only in Codex tasks: its plain chat accepts only servers
reachable over the internet. Making that work would mean a sextant running
online, or a tunnel from the internet to the laptop, either of which sends
private documents through a public address. **Not proposed**; the README
says "Codex tasks, not ChatGPT chat".

Not proposed: more standalone `.mcpb` bundles for Windows, Linux or Intel Mac.
Each is a few hundred MB per release. Decide after item 4 shows whether the
plain route works there.

## What this does not prove

CI machines are clean machines. A real laptop has corporate proxies, antivirus
and old Pythons that CI never sees, so item 4 shows the install can work on
each system, not that it will work on every laptop.
