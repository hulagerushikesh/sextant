"""Trimming a tool result to the documents the asker is allowed to see, and
refusing a write that names a document the asker does not own.

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

## Deny by default, and what that turned out to miss

Rather than naming the tools that leak, this trims *anything* in *any* result
that names a document the asker may not see. A tool added later is covered
without having to remember it -- the same reason item 3's refusal is middleware
rather than a line in each route.

0.8.4 shipped that claim with the words "`kb_ann_compare` returns passages too,
and nobody would have thought of it" in this docstring, and it was wrong twice
over: `/ann/compare` did not route through here at all, and if it had, nothing
would have been trimmed. Its payload is

    {"exact":   ["upload:grace:secret#0", …],              # bare ids
     "results": {"hnsw": {"hits": [{"id": "…#0", …}], "missed": [ids]}},
     "passages": {"upload:grace:secret#0": {"title": …, "excerpt": …}}}

-- three shapes, none of them a list entry with a `document_id` field, which
was the only shape 0.8.4 recognised. The excerpt is the document's opening
text. So the lesson is not that one endpoint was missed: **deny by default only
denies the shapes it recognises**, and a rule that reads as general while being
specific is worse than an enumerated list, because nobody re-checks it.

What is recognised now is the *id*, not the field it sits in. An id can reach a
caller three ways, and all three are checked:

1. as a string value anywhere in a result entry (`document_id`, `id`, `source`,
   a field invented next year),
2. as a key of a mapping (`passages`),
3. as a bare string in a list (`exact`, `missed`).

The check is anchored: `owner_of_document` only reports an owner for a string
that *starts* `upload:<owner>:<stem>`, so prose that happens to mention an id
mid-sentence is untouched and only something that is actually an id is dropped.

## Writes: an allow-list, where reads are a deny-list

`identity.writable_by` is not `visible_to`, and the asymmetry is deliberate --
see its docstring. Enforcing it here rather than in the `/ingest` route puts
reads and writes on the same boundary: one object decides what a caller may
touch, in both directions.

A tool this module cannot classify is refused rather than guessed at, and
`READ_TOOLS | WRITE_TOOLS` is pinned against the live server's tool list in
`tests/test_scope.py`, so a tool added later fails a test instead of silently
defaulting to either behaviour. That is the only honest way to keep a list.

## What is deliberately not scoped

`collection_size` riding along on a search result. It is a count of the whole
store, not content, and `agent.py` reads it to tell the model "the knowledge
base is empty" apart from "nothing matched". Recomputing it would cost a
listing on every search; dropping it would make that message wrong. One
integer's worth of disclosure is the honest trade, and it is written down
rather than overlooked. `kb_stats` *is* recomputed, because reporting the
whole store's size to someone who can see a fraction of it is not a leak so
much as a lie, and it is the one tool whose entire job is that number.

The Index Lab's measurements of the indexes themselves -- `recall`,
`latency_ms`, `vectors`, `bytes` -- likewise. Recall is measured against exact
search over every vector in the store, and an index's recall is a property of
the index, not of the asker: the passages behind the numbers are trimmed, the
numbers are not. A lab that scored each index against a different subset per
visitor would be measuring nothing, and the whole point of the view is which
index to build over the corpus that exists.

`shared` is scoped like any other name. It is the fallback for curl, the CLI
and a browser with no storage -- and if it saw everything, every tenant could
read every other tenant's uploads by deleting one header.
"""

from __future__ import annotations

from typing import Any

from mcp_server.identity import DEFAULT_OWNER, visible_to, writable_by

# Fields that count the thing a sibling collection holds. Rewritten when that
# collection is trimmed, and only when the value still matches the untrimmed
# length -- a name alone would catch `limit`, and a length alone would catch any
# integer that happened to collide with it.
COUNT_FIELDS = frozenset({"count", "total", "total_found", "documents", "matches", "chunks"})

# Every tool the knowledge base exposes, classified. Pinned against the running
# server in tests, because an unclassified tool is refused and a test failure is
# a better way to find that out than a 500 in production.
READ_TOOLS = frozenset({"kb_search", "kb_list", "kb_stats", "kb_ann_benchmark", "kb_ann_compare"})
WRITE_TOOLS = frozenset({"kb_ingest"})


class ForbiddenWrite(Exception):
    """A call tried to write a document outside the caller's namespace.

    An exception rather than a silently-renamed id: `/ingest`'s whole premise is
    that the caller states the id outright, so quietly storing their document
    somewhere else would answer success to a request that did not happen.
    """


def _names_other_owner(value: Any, owner: str) -> bool:
    """Whether this string is an id naming a document `owner` may not see.

    Anchored on purpose -- see the module docstring. A string that is not
    shaped like `upload:<someone>:<stem>` belongs to the shared corpus as far
    as `owner_of_document` is concerned, so ordinary text never trips this.
    """
    return isinstance(value, str) and not visible_to(owner, value)


def _allowed(entry: Any, owner: str) -> bool:
    """Whether one entry of a collection survives.

    An entry goes if *anything* in it names another owner's document: the id
    field it was found under is not the point, and in `kb_ann_compare`'s hits
    the field is called `id`, in `kb_list`'s it is `document_id`, and in the
    bare lists there is no field at all.
    """
    if isinstance(entry, str):
        return not _names_other_owner(entry, owner)
    if not isinstance(entry, dict):
        return True
    return not any(_names_other_owner(item, owner) for item in entry.values())


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
        # A mapping keyed by document or chunk id -- `passages` -- leaks the id
        # in the key and the opening text in the value.
        if _names_other_owner(key, owner):
            continue
        if isinstance(item, (list, dict)):
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
        self._guard(name, arguments)
        result = await self._host.call(name, arguments)
        if name == "kb_stats":
            return await self._scoped_stats(result)
        return trim(result, self._owner)

    def _guard(self, name: str, arguments: dict[str, Any]) -> None:
        """Refuse the call outright, before the store is touched.

        Before and not after: `_store` clears a document's existing chunks as
        the first step of writing it, so a write checked on the way back out
        has already deleted what it was supposed to protect.
        """
        if name in READ_TOOLS:
            return
        if name not in WRITE_TOOLS:
            raise ForbiddenWrite(
                f"{name} is neither a read nor a write as far as scope.py knows, so it "
                "is refused. Classify it in READ_TOOLS or WRITE_TOOLS."
            )
        for i, document in enumerate(arguments.get("documents") or []):
            stated = document.get("id") if isinstance(document, dict) else None
            # The same default `_add_documents_sync` applies, so an id left off
            # is judged as the shared id it would actually be stored under
            # rather than waved through for being absent.
            document_id = str(stated or f"doc_{i}")
            if not writable_by(self._owner, document_id):
                raise ForbiddenWrite(
                    f"'{document_id}' is not {self._owner}'s to write: re-using an id "
                    f"replaces that document. Ids {self._owner} may write start with "
                    f"'upload:{self._owner}:'."
                )

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
