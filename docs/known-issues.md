# Known issues

Limits and deliberate trade-offs, stated plainly.

> Moved here from the README on 2026-11-12 so the front page could open with a
> quickstart. The text is unchanged apart from link paths.

- `min_score` is `0.01`, set from the golden set: it blocks 8 of 10 unanswerable
  queries and costs 3 of 55 answerable ones. It cannot do better than 8 in 10,
  and no threshold can — the two survivors ask for a fact absent from a passage
  genuinely about that subject. Only reading the passage catches those, which is
  why the agent prompt carries an abstention rule.

  This corrects a claim made in Phase 4. On five queries over one PDF the
  reranker looked like it separated relevant from irrelevant cleanly; across 65
  questions it does not. That is what the golden set was for.
- The BM25 index is rebuilt in memory from the collection on first search and
  the chunk text is held resident. Fine at this scale (1,568 chunks from a
  144-page PDF), and the thing to revisit when it stops being fine.
- Cold start is a few seconds: from launch to a first answer over a small
  folder took 7 s on a MacBook Air (2026-11-15). Warm searches run in about 0.1 s.
- Both models run on ONNX Runtime without torch, but the install is still
  about 480 MB on disk: the vector store and the PDF reader account for most
  of it. A model with no ONNX export needs the `torch` extra (~900 MB).
- The source list shows everything the agent retrieved, including passages the
  answer never cited. That is deliberate — it is a record of what was looked at.
- Web results have no excerpt in the panel. The API returns page content
  encrypted for the model's use, not for display; only title and URL are ours.
- The rate limiter is in-process and approximate. It protects a single-process
  deployment from a runaway loop; it is not a substitute for a gateway once
  there is more than one replica.
- An unbroken token longer than 100 characters — a base64 blob, a long URL —
  becomes `[UNK]` to the tokenizer and contributes nothing to its chunk's
  embedding. A property of the model, not something chunking can fix.
- `ruff format` is not enforced. Line length is already checked by the linter,
  and adopting a formatter would rewrite sixteen files whose wrapping was chosen
  for readability.
- Conversations are per-browser. There is no account and no sync; clearing
  site data clears them. "Export as Markdown" in the palette is the way out.
- A follow-up cannot re-read a passage from two turns ago without searching for
  it again. Deliberate — see `conversation.py` — but it means an unusually
  specific follow-up may retrieve rather than remember.
- A scanned PDF is read with text recognition (since 0.12), which is a reading
  of a picture: a blurred or tilted scan gives wrong characters, and search
  matches those. English is the default; other languages are named in
  `SEXTANT_OCR_LANG` (`eng+mar`), and only English, Hindi and Marathi are
  fetched by themselves -- any other needs its Tesseract data installed. A
  scan recognition cannot read is reported with the reason, not stored empty.
  Changing the languages reads every stored scan again on the next start
  (since 0.12.1); scans in a printed form that mixes English and Marathi
  read badly in English alone.
- A question written in Marathi or Hindi is matched by its words only (since
  0.12.2): the meaning-based models read English, and on another script they
  ranked unrelated passages as near-certain matches. So a Marathi question
  finds passages sharing its words, spelled the same way, and not paraphrases;
  the answer says so in a `note`. Asking in English also searches by meaning.
- A result's dates (since 0.12.3) are the dates written in the text, not
  when the paper was issued: a resume reading "July 2023 - Present" is dated
  July 2023, and a date of birth counts like any other. Dates after today are
  left out, so a passport's expiry and a bill's due date never make a paper
  look newer. Two-digit years (12/03/24) are not read. Which address is
  current is still the reader's call; the dates only say which paper is newer.
- The answer renderer handles paragraphs, lists, headings, tables, bold and
  inline code. It is not a markdown parser. Gemini reaches for LaTeX
  unprompted, so the system prompt asks for equations as inline code instead.
- A web source's title is the site's domain and its link is a Google redirect.
  That is the shape of the grounding metadata, not a choice.
- The judge and the agent now share one model family, so `sextant-judge`
  grades Gemini's answers with Gemini. Same-family grading is a known bias; the
  deterministic citation check is unaffected by it, and is the half that catches
  the failure that matters most.
