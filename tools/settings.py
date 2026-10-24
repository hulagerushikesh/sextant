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

Because an entry point cannot load it early enough. `mcp_server/main.py`
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
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PREFIX = "SEXTANT_"
LEGACY_PREFIX = "AGENTICRAG_"

# The repository root as seen from an editable install. Absent in a wheel
# installed elsewhere, where `load_dotenv` on a missing path is a no-op.
DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"

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
