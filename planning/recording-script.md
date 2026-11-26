# The 90-second recording — shot list

Milestone 31, item 2. **Done when:** the recording is in the README. Recording
it is the owner's (it needs your screen and your Claude Desktop); this page
is the plan, so the take is short and nothing private shows.

## Before you press record

- **A demo folder, not Downloads.** Make an empty folder (for example
  `~/sextant-demo`) and put in 5–10 documents that are safe to show the
  world: a public report PDF, a few Markdown or text notes, one manual. No
  résumé, marksheet, ID card or anything with your name on it.
- **Remove the installed sextant first** from Claude's Extensions settings, so the install is shown from the start.
- **Set your own library aside.** Uninstalling keeps the library, so your
  Downloads documents would still show in the demo. Quit Claude fully, then
  in Finder rename `~/Library/Application Support/sextant` to
  `sextant-mine`. After recording, quit Claude, delete the new `sextant`
  folder and rename `sextant-mine` back.
- Have `sextant-0.12.9-macos-arm64.mcpb` in Finder, downloaded from the
  [releases page](https://github.com/hulagerushikesh/sextant/releases).
- Hide the Dock and desktop icons, close other windows, turn on Do Not
  Disturb. Record the Claude window only (Cmd-Shift-5 → *Record Selected
  Window*).
- Write down one question whose answer you know is in a demo document,
  with its page, so the citation can be checked on camera.

## The shots

| Time | What happens on screen | Caption, if you add one |
| --- | --- | --- |
| 0–15 s | Double-click the `.mcpb` file; Claude's install dialog opens; choose the demo folder; Install | *One file. No terminal.* |
| 15–30 s | Start a new chat; ask *"what is in my library?"*; the answer lists the demo files | *It reads the folder on your computer* |
| 30–55 s | Ask the question you wrote down; the answer quotes the passage and names the file and page | *Every answer names its file and page* |
| 55–85 s | Ask *"how well does search work on my documents?"*; the report appears: one score with its chance range, any missed questions, files it cannot use, one thing to fix first | *A report card for your own library* |
| 85–90 s | Hold on the report | *sextant · github.com/hulagerushikesh/sextant* |

Cut the waits (the indexing and the self-test take longer than they look
here) and say so in one line under the video: *"Waits cut; indexing took N
seconds on a MacBook Air."* Use the real N.

## Into the README

- GitHub plays an `.mp4` dragged into the README editor on github.com (it
  becomes a `user-attachments` link). **PyPI does not play video**, so the
  package page would show only a bare link.
- A GIF under 10 MB in `docs/` shows on both pages. Send me the `.mov` and I
  will make the GIF, check its size, and put it under the first paragraph
  of the README with the waits line beneath it.
- The README is frozen onto the PyPI page at each upload, so the recording
  reaches PyPI with the next release, not before.
