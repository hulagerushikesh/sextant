"""Who a request belongs to, and how much of that is worth believing.

Two names arrive here and they are not the same kind of thing.

`X-Sextant-Client` is a random per-browser id our own frontend keeps in
localStorage. It exists because of a defect, not because the app had users:
upload ids were `upload:<filename stem>`, global across the store, and `_store`
clears a document's existing chunks before writing its new ones. Both are right
on their own -- a re-ingest of a document *should* be a replacement -- but
together, two people behind the one shared Basic-auth password who each upload
`notes.pdf` destroy each other's chunks, with `/upload` returning success and no
symptom but citations that stop appearing. Namespacing the id by owner closes
that. Anything can send the header, so it is a name people pick, not a name
people prove.

`X-Sextant-User` is the other kind. Caddy's `basic_auth` takes more than one
`user hash` line, and `reverse_proxy` can forward `{http.auth.user.id}` -- the
name of whoever actually authenticated. Identity then comes from the transport,
set by the component that did the checking, and never from the client and never
from the model. That last part is the hard constraint behind milestone 20: tool
schemas are discovered at startup and handed straight to the model, so anything
the model can name, a sentence inside an uploaded PDF can name too.

A header is only as trustworthy as the thing that set it, and a header is the
easiest thing in the world to type into a curl. So the proxy proves it spoke:
it also sends `X-Sextant-Proxy-Auth`, a shared secret the box's `.env` gives to
both halves, and an `X-Sextant-User` without it is a forgery and a 403 -- never
a quiet downgrade to the client's own name, which would hide the attempt.

Caddy *sets* both headers rather than appending (checked against the adapted
JSON, and again live: a request authenticating as `ada` while carrying
`X-Sextant-User: grace` reaches the backend as `ada`). So the secret is not the
first line of defence, it is the one that still holds if something ever reaches
the app without going through Caddy.

What this still does **not** do, and is not pretending to:

- It does not hide one owner's chunks from another's search. Everyone behind
  the gate retrieves everything, exactly as before. That is milestone 20
  item 2's question, and it was decided by measurement, not here.
- It does not do signup, sessions, or password reset. Adding a person is two
  lines in the box's `.env` and a reload. For a deployment whose users are
  "people I gave the password to", that is the whole of the correct scope.

**A deploy prerequisite, checked live.** Caddy has no conditionals: once this
tree's Caddyfile is on the box, it forwards `X-Sextant-User` on every proxied
request, and an unset `SEXTANT_PROXY_SECRET` makes it forward an *empty*
`X-Sextant-Proxy-Auth` beside it (confirmed against a running Caddy, not
assumed). Every request then arrives claiming a name it cannot prove, and
every request is refused. So the box's `.env` needs the secret **before** this
tree is built on it -- the same shape of prerequisite as the 0.8.1 rename.

That is deliberate rather than tolerated. The alternative -- ignore an
unprovable name and fall back to the browser's own id -- turns deleting one
line of `.env` into every user silently collapsing back into one namespace,
which is the collision this module was written to fix, returning with no
symptom. A 403 that names the missing setting is recoverable in a minute; a
namespace collapse is discovered weeks later as documents that stopped being
cited.
"""

from __future__ import annotations

import hmac
import re

from tools import settings

# Our own frontend's per-browser id. Untrusted by construction -- anything can
# send it, and nothing checks it.
CLIENT_HEADER = "X-Sextant-Client"

# The authenticated name, set by the proxy from `{http.auth.user.id}`. Believed
# only alongside the secret below.
USER_HEADER = "X-Sextant-User"

# The proxy proving it is the one that set `USER_HEADER`. Shared with the box's
# Caddy through `SEXTANT_PROXY_SECRET` in the same `.env` both read.
PROXY_HEADER = "X-Sextant-Proxy-Auth"
PROXY_SECRET = "PROXY_SECRET"

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


class ForgedIdentity(Exception):
    """A request claimed an authenticated name without coming through the proxy.

    Deliberately not a fallback. Ignoring the claim and using the client's own
    name would serve the request, log nothing anybody reads, and leave the
    caller believing they were someone else -- which is the same outcome as
    succeeding, discovered later.
    """


def safe_owner(value: str | None) -> str:
    """A name that cannot break a document id, or `DEFAULT_OWNER`."""
    cleaned = _UNSAFE.sub("_", (value or "").strip())[:MAX_OWNER_CHARS].strip("._-")
    return cleaned or DEFAULT_OWNER


def proxy_secret() -> str:
    """The shared secret, or empty when no proxy is configured to send one."""
    return (settings.getenv(PROXY_SECRET, "") or "").strip()


def _proxy_spoke(offered: str | None) -> bool:
    """Whether the request carries proof it came through our own proxy.

    Constant-time, because the alternative leaks the secret one byte at a time
    to anyone willing to time a few thousand requests.
    """
    secret = proxy_secret()
    return bool(secret) and hmac.compare_digest(secret, (offered or "").strip())


def owner_of(headers: object) -> str:
    """Who this request's uploads belong to.

    Precedence: the proxy's authenticated name, then the browser's own id, then
    the shared namespace. Raises `ForgedIdentity` if the first is claimed and
    not proven -- including when no secret is configured at all, because then
    the only two explanations are a forgery and a half-wired proxy, and both
    should be loud. That is also what keeps a no-proxy development box from
    quietly becoming a no-authentication production one.

    Takes anything with a mapping-style `get` -- a Starlette `Headers`, a plain
    dict in a test -- so this stays testable without a request object.
    """
    get = getattr(headers, "get", None)
    if get is None:
        return DEFAULT_OWNER
    claimed = (get(USER_HEADER) or "").strip()
    if claimed:
        if not _proxy_spoke(get(PROXY_HEADER)):
            # The two cases read identically to the caller but not to whoever
            # is reading the response: one is an attempt, the other is a box
            # that was deployed a line short, and the second should not have
            # to be diagnosed.
            raise ForgedIdentity(
                f"{USER_HEADER} was set by something other than the proxy."
                if proxy_secret()
                else f"{USER_HEADER} was sent but {settings.env_name(PROXY_SECRET)} "
                f"is not set, so no identity can be verified."
            )
        return safe_owner(claimed)
    return safe_owner(get(CLIENT_HEADER))


# The id scheme `upload:<owner>:<stem>` is parseable precisely because
# `safe_owner` cannot emit a colon. Reading the owner back out of the id is
# therefore exact, and -- unlike a new metadata field -- it is already true of
# every document in every store written since 0.8.2, with nothing to migrate.
_UPLOAD_PREFIX = "upload:"


def owner_of_document(document_id: str | None) -> str:
    """Who uploaded this document, or `DEFAULT_OWNER` for the shared corpus.

    The inverse of the id `to_document` builds. Anything that is not an
    owner-namespaced upload -- a document ingested from `/data/corpus` by the
    CLI, one stated outright through `/ingest`, or a pre-0.8.2 `upload:<stem>`
    -- belongs to nobody in particular and is part of what everyone can see.
    """
    text = (document_id or "").strip()
    if not text.startswith(_UPLOAD_PREFIX):
        return DEFAULT_OWNER
    rest = text[len(_UPLOAD_PREFIX) :]
    owner, sep, stem = rest.partition(":")
    if not sep or not stem:
        # `upload:notes` -- the pre-0.8.2 scheme. Nobody's in particular, which
        # is the same answer the store gave before owners existed.
        return DEFAULT_OWNER
    return safe_owner(owner)


def visible_to(owner: str, document_id: str | None) -> bool:
    """Whether `owner` may see this document.

    A deny-list on other people's uploads, not an allow-list on your own. The
    shared corpus is the product -- an allow-list would hide every document the
    operator ingested from everybody, which is the opposite of what the box is
    for. So: everything, minus uploads that name somebody else.
    """
    document_owner = owner_of_document(document_id)
    return document_owner == DEFAULT_OWNER or document_owner == safe_owner(owner)


def writable_by(owner: str, document_id: str | None) -> bool:
    """Whether `owner` may *write* this document id.

    Deliberately not `visible_to`. Reading is a deny-list -- everything minus
    other people's uploads -- because the shared corpus is the product. Writing
    is an allow-list: your own namespace, nothing else. The asymmetry is the
    point. A document everyone may read is not a document everyone may replace,
    and `_store` replaces: re-using an id clears that document's chunks first,
    so a write to somebody else's id is a deletion of their document and a
    forgery under their name in the same call. They keep citing it as theirs.

    `shared` -- curl, the CLI, the eval harness, a box with no identity wired
    up -- owns the shared corpus, which is exactly the behaviour every caller
    had before owners existed. An *authenticated* caller does not inherit it:
    on the box, seeding the shared corpus is `sextant-ingest`, run there.
    """
    return owner_of_document(document_id) == safe_owner(owner)


def describe() -> str:
    """One line at startup saying which of the two worlds this process is in.

    Worth printing because the failure it describes is silent: a box whose
    Caddy forwards an identity to an app that has no secret to check it with
    refuses every request, and a box with neither simply has no identities and
    looks fine. Reading it in `docker compose logs` is cheaper than either.
    """
    if proxy_secret():
        return (
            f"identity: trusting {USER_HEADER} when accompanied by "
            f"{PROXY_HEADER}; uploads are namespaced by the authenticated user"
        )
    return (
        f"identity: no {settings.env_name(PROXY_SECRET)} set, so {USER_HEADER} is "
        f"refused and uploads are namespaced by {CLIENT_HEADER} "
        f"(or '{DEFAULT_OWNER}')"
    )
