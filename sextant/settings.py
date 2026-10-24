"""Environment variable names.

The project was renamed from AgenticRAG to sextant. Every tuning knob is read
through here, so there is one place that says what a setting is called:
`SEXTANT_X`.

The old `AGENTICRAG_X` spelling was honoured as a fallback from the rename
(2026-09-13) until the deployed box's `.env` was rewritten (2026-09-28). It is
gone now, because a fallback that nothing uses is a second name for every
setting and a second thing to get right. What replaces it is `legacy_names()`:
a stale variable is now a printed warning instead of a silent default, which is
the failure the fallback existed to prevent.

Kept free of *heavy* imports on purpose: both the agent server and the
knowledge-base subprocess import it, and neither may pull the other's model
stack. `python-dotenv` is a hard dependency already and costs a few
milliseconds, which is the price of the paragraph below.

## Why `.env` is loaded here and nowhere else

Because an entry point cannot load it early enough. `sextant/mcp_server/main.py`
called `load_dotenv()` at line 55, under twenty import lines -- and Python
runs the imports first, so by the time the call happened `agent.MODEL`,
`observability.DAILY_BUDGET_USD`, `RATE_LIMIT_REQUESTS`, `RATE_WINDOW` and
`DAILY_BUDGET_SHARE` had already been evaluated against an environment the
file had not reached. Measured, not reasoned about: with
`SEXTANT_DAILY_BUDGET_USD=0.60` in `.env`, importing the app left
`os.environ` holding `0.60` and `DAILY_BUDGET_USD` holding `0.0`, which
`DailyBudget` reads as *no cap at all*. The operator had set a daily spend
ceiling on a prepaid key and did not have one.

It bit only the local run. The box gets those names from compose's
`env_file`, so they are real environment variables before Python starts --
the one environment nobody is watching, again.

Loading it here fixes the ordering by construction rather than by being
careful: a module cannot call `settings.getenv` without importing this
module, so there is no longer an order in which a setting can be read before
the file that sets it. `load_dotenv` does not override a name that is
already in the environment, so compose, CI and a shell export all still win.

## Why a sealed process does not load it

Because one process here does not choose its own environment. The
knowledge-base server runs as a subprocess of the agent, and MCP's stdio
client hands a child only `get_default_environment() | params.env` -- so
`mcp_host._FORWARDED_ENV` *is* that child's environment, and the names in
`_NOT_FORWARDED` are a deliberate refusal with a written reason, one of them
`GEMINI_API_KEY`: "a key that does not cross cannot leak from here."

Loading `.env` in every importer made that false. Measured from a checkout:
the child starts with five names and none of them is the key, imports
`sextant.vector_db.server`, reaches this module through `vector_search`, reads
the repository's `.env`, and has the key. The parent withheld it and the
child fetched it itself.

So the parent seals: `kb_server` sets `SEXTANT_ENV_SEALED`, and a sealed
process takes its environment as given and reads no file. An allowlist that
the listed process can go behind is not an allowlist.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PREFIX = "SEXTANT_"
LEGACY_PREFIX = "AGENTICRAG_"

# Where this package was imported from, and whether there is a repository
# around it. Four modules used to answer that question with their own
# `parents[N]`, which is four copies of one fact about the tree's shape:
# moving the three top-level packages under `sextant/` in 0.9.0 broke two of
# them and left two correct, and the suite caught it because a *different*
# copy disagreed. One function now, and `TestTheTreeShapeIsKnownInOnePlace`
# fails if a second appears.
PACKAGE_ROOT = Path(__file__).resolve().parent


def repo_root() -> Path | None:
    """The checkout this package lives in, or `None` when installed.

    `pyproject.toml` beside the package is the thing that tells the two
    apart. The difference is not cosmetic: a wheel in `site-packages` has no
    repository, so anything that defaults to a path "next to the source" is
    defaulting into a directory `pip uninstall` removes.
    """
    candidate = PACKAGE_ROOT.parent
    return candidate if (candidate / "pyproject.toml").is_file() else None


def default_store() -> Path:
    """Where documents go when `SEXTANT_CHROMA_DIR` is not set.

    In a checkout, `<repo>/chroma_db` -- what every number in `learning/`
    was measured against and what the container bind-mounts. Installed from
    a wheel there is no repository to sit beside, and putting somebody's
    corpus under `site-packages` would hand their documents to the next
    `pip uninstall`. It goes to the platform's user-data directory instead.
    """
    root = repo_root()
    if root is not None:
        return root / "chroma_db"
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "sextant" / "chroma_db"


# Read from the checkout only. In a wheel installed elsewhere `repo_root()`
# is None and there is no `.env` to load.
DOTENV_PATH = (repo_root() or PACKAGE_ROOT) / ".env"

# Set by a parent that has already decided this process's entire environment,
# which today is `mcp_host.kb_server`. Read straight off `os.environ` because
# `getenv` below is the thing being configured, and read before the load so a
# `.env` cannot unseal itself.
SEALED = PREFIX + "ENV_SEALED"

if not os.environ.get(SEALED):
    load_dotenv(DOTENV_PATH)


def env_name(key: str) -> str:
    """The variable name for a setting, e.g. `SEXTANT_MODEL`."""
    return PREFIX + key


def getenv(key: str, default: str | None = None) -> str | None:
    """Read `SEXTANT_<key>`, or `default`."""
    return os.environ.get(env_name(key), default)


def setenv(key: str, value: str) -> None:
    """Set a setting. Used by the eval harnesses to isolate a store."""
    os.environ[env_name(key)] = value


def legacy_names() -> tuple[str, ...]:
    """Any `AGENTICRAG_*` variables still set, sorted.

    Nothing reads them. An entry here means a `.env` somewhere predates the
    rename and that setting is silently running on its default -- so callers
    that own a process (the agent server, the ingest CLI) say so out loud at
    startup rather than letting the box drift.
    """
    return tuple(sorted(n for n in os.environ if n.startswith(LEGACY_PREFIX)))


def legacy_warning() -> str | None:
    """The line to print when a stale `.env` is still in the environment."""
    stale = legacy_names()
    if not stale:
        return None
    renamed = ", ".join(f"{n} -> {PREFIX}{n[len(LEGACY_PREFIX):]}" for n in stale)
    return (
        f"{len(stale)} AGENTICRAG_* variable(s) are set and no longer read; "
        f"these settings are running on their defaults. Rename: {renamed}"
    )
