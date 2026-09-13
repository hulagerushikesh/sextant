"""
Numbered, citable sources.

Both retrieval tiers land here. Knowledge-base passages arrive as `kb_search`
hits that this process reads directly; web results arrive as blocks Anthropic's
servers already fetched. They are different in almost every respect except the
one that matters to a reader: each is a thing the answer can point at.

The registry hands out `[n]` labels in first-seen order and keeps them stable for
the length of one *conversation*, not one question. That is what makes citation
work at all -- the model only cites a knowledge-base passage correctly because it
was shown the same number the UI will later print, and a reader scrolling back
through a transcript needs [3] to still mean [3] four questions later.

Continuity across questions is `restore()`. This server holds no session state,
so the client sends back the labels it already knows and the registry resumes
numbering after them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# How many restored labels a single request may carry. A long conversation
# accumulates sources without bound otherwise, and the request would grow with
# it. Past this the oldest labels are dropped and their numbers are not reused --
# a citation to a dropped source resolves to nothing, which is visible, rather
# than to the wrong passage, which is not.
MAX_RESTORED = 60


def _describe_location(hit: dict[str, Any]) -> str | None:
    """Where in the corpus this passage sits, in the shortest useful form.

    A page number when the loader found one, otherwise the section heading it
    fell under, otherwise just the file. Chunks are attributed to wherever they
    start, so a passage running across a page break names the page a reader
    would turn to.
    """
    origin_file = hit.get("source")
    page, section = hit.get("page"), hit.get("section")
    if origin_file and page:
        return f"{origin_file} p.{page}"
    if origin_file and section:
        return f"{origin_file} § {section}"
    return origin_file or None


@dataclass
class Source:
    """One numbered thing the answer is allowed to cite."""

    n: int
    title: str
    content: str
    origin: str  # "knowledge_base" | "web"
    key: str  # chunk id, or URL for web results -- the identity, sent to the UI
    url: str | None = None
    location: str | None = None  # e.g. "notes.md p.3"
    score: float | None = None

    def as_json(self) -> dict[str, Any]:
        """The wire shape. `text` is the whole passage, deliberately.

        It used to be truncated to 400 characters, on the reasoning that the
        browser should not receive a document per frame. Chunking (Phase 4)
        retired that reasoning without retiring the cap: a source is now a chunk
        of about 200 tokens, so the whole thing is roughly the size the excerpt
        used to be, and clicking a citation can show the passage the model
        actually read rather than its first paragraph.
        """
        return {
            "n": self.n,
            "key": self.key,
            "title": self.title,
            "origin": self.origin,
            "url": self.url,
            "location": self.location,
            "score": self.score,
            "text": self.content,
        }


class SourceRegistry:
    """Assigns and remembers `[n]` labels for one conversation.

    Deduplicated by identity, not by content: the model may call `kb_search`
    twice with different phrasings and get the same passage back both times, and
    that passage should keep the number it was given the first time rather than
    appearing twice in the list under two labels.
    """

    def __init__(self) -> None:
        self._sources: list[Source] = []
        self._by_key: dict[tuple[str, str], Source] = {}
        self._next_n = 1

    @property
    def sources(self) -> list[Source]:
        return list(self._sources)

    def __len__(self) -> int:
        return len(self._sources)

    def as_json(self) -> list[dict[str, Any]]:
        return [s.as_json() for s in self._sources]

    def restore(self, payloads: list[dict[str, Any]]) -> None:
        """Re-adopt labels handed out in earlier turns of this conversation.

        Only identity and label are needed: the passage text is not replayed to
        the model, so a restored source exists to reserve its number and to be
        recognised if retrieval returns it again. If it is, `_add` upgrades it
        with the full text at that point.

        Silently ignores entries missing a usable key rather than raising -- this
        is client-supplied and a malformed label should cost a citation, not the
        answer.
        """
        for payload in payloads[-MAX_RESTORED:]:
            origin = payload.get("origin")
            key = payload.get("key") or payload.get("url")
            n = payload.get("n")
            if origin not in ("knowledge_base", "web") or not key or not isinstance(n, int):
                continue
            identity = (origin, str(key))
            if identity in self._by_key:
                continue
            source = Source(
                n=n,
                key=str(key),
                title=str(payload.get("title") or key),
                content="",
                origin=origin,
                url=payload.get("url"),
                location=payload.get("location"),
                score=payload.get("score"),
            )
            self._sources.append(source)
            self._by_key[identity] = source
            self._next_n = max(self._next_n, n + 1)

    def add_kb(self, hit: dict[str, Any]) -> Source:
        """Register one `kb_search` result.

        The identity is the *chunk* id, not the document's: two passages from
        the same PDF are two sources, because they cite different pages.
        """
        chunk_id = str(hit.get("id") or hit.get("title") or len(self._sources))
        return self._add(
            key=chunk_id,
            title=hit.get("title") or "Untitled document",
            content=(hit.get("content") or "").strip(),
            origin="knowledge_base",
            location=_describe_location(hit),
            score=hit.get("score"),
        )

    def add_web(self, title: str | None, url: str, snippet: str = "") -> Source:
        """Register one web search result. The URL is the identity."""
        return self._add(
            key=url,
            title=title or url,
            content=snippet,
            origin="web",
            url=url,
        )

    def find_web(self, url: str) -> Source | None:
        """The source already registered for `url`, if any.

        Used to turn a streamed citation back into the number the UI knows it by.
        """
        return self._by_key.get(("web", url))

    def _add(
        self,
        key: str,
        title: str,
        content: str,
        origin: str,
        url: str | None = None,
        location: str | None = None,
        score: float | None = None,
    ) -> Source:
        existing = self._by_key.get((origin, key))
        if existing is not None:
            # Two ways to hold a source with no text: a web result registered
            # from a citation, and a label restored from an earlier turn. Either
            # is superseded by the real passage the moment it arrives.
            if len(content) > len(existing.content):
                existing.content = content
            if existing.location is None:
                existing.location = location
            if existing.score is None:
                existing.score = score
            return existing

        source = Source(
            n=self._next_n,
            key=key,
            title=title,
            content=content,
            origin=origin,
            url=url,
            location=location,
            score=score,
        )
        self._next_n += 1
        self._sources.append(source)
        self._by_key[(origin, key)] = source
        return source
