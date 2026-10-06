"""Trimming a tool result to the documents the asker is allowed to see.

Milestone 20 item 2 chose **A**: one collection, filtered, rather than a
collection or a deployment per person. The measurement said A's retrieval
holds up. What the measurement also turned up is that the filter was never the
hard part -- `kb_list` and `kb_stats` report the *whole* collection, so under A
every other tenant's document titles, overviews and opening lines are handed
straight to the model in its prompt. A leak, not a recall problem, and no
retrieval experiment would have found it.

## Why the filter lives here and not in the knowledge base

The hard invariant of the milestone: **the corpus is never a tool argument.**
Tool schemas are discovered at startup and handed to the model verbatim, so a
`kb_search(owner=…)` would let a sentence inside an uploaded PDF name somebody
else's documents -- and the model would have no way to know it should not.

That rules out passing the owner down into the knowledge base, because
anything the MCP tool function accepts appears in its schema. The remaining
places to put it are a subprocess per owner -- which is arm B, rejected on its
memory cost -- or here: above the tool boundary, below the model. The knowledge
base stays owner-agnostic and process-global, and nothing the model emits can
change what it is allowed to see, because the model is never asked.

## Deny by default, like the identity middleware

Rather than naming the tools that leak, this trims *anything* in *any* result
that carries a `document_id` the asker may not see. A tool added later is
covered without having to remember it -- the same reason item 3's refusal is
middleware rather than a line in each route. `kb_ann_compare` returns passages
too, and nobody would have thought of it.

## What is deliberately not scoped

`collection_size` riding along on a search result. It is a count of the whole
store, not content, and `agent.py` reads it to tell the model "the knowledge
base is empty" apart from "nothing matched". Recomputing it would cost a
listing on every search; dropping it would make that message wrong. One
integer's worth of disclosure is the honest trade, and it is written down
rather than overlooked. `kb_stats` *is* recomputed, because reporting the
whole store's size to someone who can see a fraction of it is not a leak so
much as a lie, and it is the one tool whose entire job is that number.

`shared` is scoped like any other name. It is the fallback for curl, the CLI
and a browser with no storage -- and if it saw everything, every tenant could
read every other tenant's uploads by deleting one header.
"""

from __future__ import annotations

from typing import Any

from mcp_server.identity import DEFAULT_OWNER, visible_to

# Fields that count the thing a sibling list holds. Rewritten when that list is
# trimmed, and only when the value still matches the untrimmed length -- a name
# alone would catch `limit`, and a length alone would catch any integer that
# happened to collide with it.
COUNT_FIELDS = frozenset({"count", "total", "total_found", "documents", "matches", "chunks"})


def _allowed(entry: Any, owner: str) -> bool:
    """Whether one list entry survives. Anything without a document is not ours to judge."""
    if not isinstance(entry, dict) or "document_id" not in entry:
        return True
    return visible_to(owner, entry.get("document_id"))


def trim(value: Any, owner: str) -> Any:
    """A copy of `value` with every other owner's documents removed."""
    if isinstance(value, list):
        return [trim(item, owner) for item in value if _allowed(item, owner)]
    if not isinstance(value, dict):
        return value

    out: dict[str, Any] = {}
    # Original length -> trimmed length, for the counters that described them.
    shrunk: dict[int, int] = {}
    for key, item in value.items():
        if isinstance(item, list):
            before = len(item)
            item = trim(item, owner)
            if len(item) != before:
                shrunk[before] = len(item)
        else:
            item = trim(item, owner)
        out[key] = item

    for key, item in out.items():
        if key in COUNT_FIELDS and isinstance(item, int) and not isinstance(item, bool):
            if item in shrunk:
                out[key] = shrunk[item]
    return out


class ScopedHost:
    """An `MCPHost` that answers as though the store held only `owner`'s view.

    A wrapper rather than a mode on the host itself, because the host is one
    process-global connection shared by every request and the owner is not.
    """

    def __init__(self, host: Any, owner: str) -> None:
        self._host = host
        self._owner = owner

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Unchanged, and that is the point: no schema mentions an owner."""
        return self._host.tools

    @property
    def connected(self) -> bool:
        return bool(self._host.connected)

    @property
    def error(self) -> str | None:
        return self._host.error

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._host.call(name, arguments)
        if name == "kb_stats":
            return await self._scoped_stats(result)
        return trim(result, self._owner)

    async def _scoped_stats(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Replace the whole-store counts with the ones this owner can see.

        Derived from the listing rather than from a second query, so the
        knowledge base needs no notion of an owner: the listing already gives a
        chunk count per document, and a document carries an overview or it
        does not.
        """
        listing = trim(await self._host.call("kb_list", {}), self._owner)
        documents = listing.get("documents")
        if not isinstance(documents, list):
            # A store that cannot be listed cannot be scoped, and reporting the
            # whole store's numbers instead would be the leak this exists to
            # close. The caller already has `status` to say what went wrong.
            return {k: v for k, v in stats.items() if k not in _WHOLE_STORE_COUNTS}
        summaries = sum(1 for entry in documents if entry.get("overview"))
        return {
            **stats,
            "documents": len(documents),
            "summaries": summaries,
            "collection_size": sum(int(entry.get("chunks") or 0) for entry in documents)
            + summaries,
        }


_WHOLE_STORE_COUNTS = ("documents", "summaries", "collection_size")


def scoped(host: Any, owner: str | None) -> ScopedHost:
    """The host as `owner` sees it."""
    return ScopedHost(host, owner or DEFAULT_OWNER)
