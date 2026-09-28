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

Kept dependency-free on purpose: both the agent server and the knowledge-base
subprocess import it, and neither may pull the other's heavy imports.
"""

from __future__ import annotations

import os

PREFIX = "SEXTANT_"
LEGACY_PREFIX = "AGENTICRAG_"


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
