"""
Who an upload belongs to.

This is **namespacing, not isolation.** It exists because of a defect, not
because the app has users yet: upload ids were `upload:<filename stem>`, which
is global across the store, and `_store` clears a document's existing chunks
before writing its new ones. Both are right on their own -- a re-ingest of a
document *should* be a replacement -- but together, two people behind the one
shared Basic-auth password who each upload `notes.pdf` destroy each other's
chunks, with `/upload` returning success and no symptom but citations that
stop appearing.

So an owner is attached to the id and the collision goes away. What it
deliberately does **not** do:

- It does not hide one owner's chunks from another's search. Everyone behind
  the gate can still retrieve everything, exactly as before. Whether that
  should change is milestone 20 item 2, and it is a retrieval question with a
  measurement attached.
- It does not authenticate. The only source today is a header the browser
  sends and therefore anything can send, so an owner is a name people pick,
  not a name people prove. Treating it as a boundary would be worse than
  having no boundary, because it would look like one.

`owner_of` is the seam for milestone 20 item 3. When Caddy grows more than one
`basic_auth` user it can forward `{http.auth.user.id}`, and that name -- set by
the component that actually did the authenticating -- becomes the first source
checked here, above the client's own. The trusted header is deliberately *not*
read yet: reading it before anything sets it would mean any caller could claim
any identity by typing it, which is the hole item 3 exists to close.
"""

from __future__ import annotations

import re

# Sent by our own frontend, which keeps a random per-browser id in
# localStorage. Untrusted by construction -- see the module docstring.
CLIENT_HEADER = "X-Sextant-Client"

# Everyone who does not say otherwise: the CLI, curl, the eval harness, and any
# browser whose storage is unavailable. Named for what it is -- one shared
# namespace -- rather than something like "anonymous" that implies a user.
DEFAULT_OWNER = "shared"

# An owner reaches a document id (`upload:<owner>:<stem>`) and from there a
# chunk id (`<document_id>#<n>`). Both separators have to survive being parsed
# back out, so neither can appear inside the owner, and nor can anything that
# would make the id unreadable in a log line or a citation.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
MAX_OWNER_CHARS = 64


def safe_owner(value: str | None) -> str:
    """A name that cannot break a document id, or `DEFAULT_OWNER`."""
    cleaned = _UNSAFE.sub("_", (value or "").strip())[:MAX_OWNER_CHARS].strip("._-")
    return cleaned or DEFAULT_OWNER


def owner_of(headers: object) -> str:
    """Who this request's uploads belong to.

    Takes anything with a mapping-style `get` -- a Starlette `Headers`, a plain
    dict in a test -- so this stays testable without a request object.
    """
    get = getattr(headers, "get", None)
    if get is None:
        return DEFAULT_OWNER
    return safe_owner(get(CLIENT_HEADER))
