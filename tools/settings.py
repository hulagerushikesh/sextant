"""Environment variable names, with the old prefix still honoured.

The project was renamed from AgenticRAG to sextant. Every tuning knob is read
through here so `SEXTANT_X` is the documented name while `AGENTICRAG_X` keeps
working -- a `.env` on a running box must not silently fall back to defaults
because the code learned a new name.

Kept dependency-free on purpose: both the agent server and the knowledge-base
subprocess import it, and neither may pull the other's heavy imports.
"""

from __future__ import annotations

import os

PREFIX = "SEXTANT_"
LEGACY_PREFIX = "AGENTICRAG_"


def env_name(key: str) -> str:
    """The documented variable name for a setting, e.g. `SEXTANT_MODEL`."""
    return PREFIX + key


def env_names(key: str) -> tuple[str, str]:
    """Both spellings, preferred first. For forwarding to subprocesses."""
    return (PREFIX + key, LEGACY_PREFIX + key)


def getenv(key: str, default: str | None = None) -> str | None:
    """Read `SEXTANT_<key>`, falling back to `AGENTICRAG_<key>`, then default."""
    for name in env_names(key):
        value = os.environ.get(name)
        if value is not None:
            return value
    return default


def setenv(key: str, value: str) -> None:
    """Set the preferred spelling. Used by the eval harnesses to isolate a store."""
    os.environ[env_name(key)] = value
