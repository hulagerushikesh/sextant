"""`start_all_services.sh` -- the one entry point the README hands a newcomer.

Until 2026-10-23 nothing had ever executed it. Run for the first time with
both children failing on their first line, it printed four URLs, "Ctrl+C to
stop", and exited **0**: `deploy.sh start` saying ">> up at <ip>" regardless
and `trip.sh` ending "agenticrag is RUNNING" with exit 0, in the script that
is somebody's first contact with this project.

It also bound `--host 0.0.0.0`. There is no authentication in front of this
process -- the gate is Caddy's `basic_auth` and Caddy exists only on the box
-- so every interface meant every caller on the network resolving to `shared`,
which owns the CLI-ingested corpus and may write it.

The stubs here stand in for the interpreter, npm and curl. They are written to
be able to *fail*: a stub that can only succeed would make every assertion
below a comment.
"""

from __future__ import annotations

import os
import pathlib
import signal
import stat
import subprocess
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "start_all_services.sh"

# The long-lived stubs rename themselves to _SENTINEL with `exec -a`, so the
# orphan check below can pgrep for something that belongs to this suite. The
# first version matched "sleep 30", which would have found -- and pkill'd --
# any unrelated `sleep 30` the person running the tests happened to have.
_SENTINEL = "sextant-start-script-stub"
_LIVE_PY = """#!/usr/bin/env bash
echo "INFO:     Uvicorn running"
# The marker IS the listening socket, as far as the curl stub is concerned.
# Without it the stub answered 200 whether or not anything had started, so
# `ready=1` for a server that had already exited and the dead-server test
# reached the frontend branch instead -- the harness deciding the outcome.
: > "$STUB_READY"
exec -a "$STUB_SENTINEL" sleep "${STUB_LIFE:-30}"
"""

_DEAD_PY = """#!/usr/bin/env bash
echo "ModuleNotFoundError: No module named 'uvicorn'" >&2
exit 1
"""

_LIVE_NPM = """#!/usr/bin/env bash
echo "VITE ready"
exec -a "$STUB_SENTINEL" sleep "${STUB_LIFE:-30}"
"""

_DEAD_NPM = """#!/usr/bin/env bash
echo "npm ERR! Missing script: dev" >&2
exit 1
"""

# A frontend that dies *after* the API is ready. The first version of the
# frontend check asked once, the instant the API came up, and this case
# answered "alive" -- a check whose result depends on how fast the step before
# it finished. Hence the settle loop, and hence this stub.
_SLOW_DEAD_NPM = """#!/usr/bin/env bash
sleep 0.4
echo "npm ERR! Port 3000 is already in use" >&2
exit 1
"""

_CURL = """#!/usr/bin/env bash
# Nothing started means nothing answers. A stub that cannot say that makes
# every assertion about a failed start a comment.
[ -f "${STUB_READY:?the curl stub was given no marker}" ] || exit 7
exit "${FAKE_HEALTH_RC:-0}"
"""


def _bin(tmp_path: pathlib.Path, py: str, npm: str) -> pathlib.Path:
    d = tmp_path / "bin"
    d.mkdir(parents=True)
    for name, body in (("py", py), ("npm", npm), ("curl", _CURL)):
        f = d / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return d


def _env(tmp_path: pathlib.Path, py: str, npm: str, **extra: str) -> dict[str, str]:
    d = _bin(tmp_path, py, npm)
    return {
        **os.environ,
        "PATH": f"{d}:{os.environ['PATH']}",
        "PY": str(d / "py"),
        # Seconds of real waiting are not a unit test. The settle still has to
        # outlast _SLOW_DEAD_NPM or the race test would pass for the old code.
        "START_TRIES": "3",
        "START_SLEEP": "0.2",
        "FRONTEND_SETTLE_TRIES": "6",
        "STUB_LIFE": "30",
        "STUB_READY": str(tmp_path / "ready"),
        "STUB_SENTINEL": _SENTINEL,
        **extra,
    }


def _run(tmp_path: pathlib.Path, py: str, npm: str, **extra: str) -> tuple[int, str]:
    done = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=_env(tmp_path, py, npm, **extra),
        timeout=60,
    )
    return done.returncode, done.stdout + done.stderr


def _orphans() -> int:
    """Stub processes still alive. The cleanup used to kill the subshell and
    leave npm -- and Vite under it -- running, which this repo has a standing
    rule against and which running the script is the only way to notice."""
    try:
        found = subprocess.run(
            ["pgrep", "-f", _SENTINEL], capture_output=True, text=True
        )
    except FileNotFoundError:  # pragma: no cover - depends on the image
        # Loud, not zero. A missing `pgrep` would make this fixture pass for
        # every run on that machine, which is the shape of defect this file
        # exists to catch -- and exactly how a Mac-only harness goes green on
        # CI (item 13).
        pytest.fail("pgrep is not installed; the orphan check cannot run")
    # pgrep exits 1 when nothing matched, which is the common case here, but
    # anything above that is the tool failing rather than answering.
    if found.returncode > 1:
        pytest.fail(f"pgrep failed ({found.returncode}): {found.stderr}")
    return len([ln for ln in found.stdout.splitlines() if ln.strip()])


@pytest.fixture(autouse=True)
def _no_orphans_left_behind():
    """Fails the test that leaks, and cleans up so it does not fail the next."""
    before = _orphans()
    yield
    leaked = _orphans() - before
    if leaked > 0:
        subprocess.run(["pkill", "-f", _SENTINEL], capture_output=True)
        pytest.fail(f"{leaked} stub process(es) left running")


class TestABannerIsAClaim:
    def test_a_dead_server_is_not_a_banner(self, tmp_path):
        code, out = _run(tmp_path, _DEAD_PY, _DEAD_NPM)
        assert code == 1, out
        assert "Ctrl+C to stop" not in out, "the banner was printed for nothing"
        assert "agent server exited" in out

    def test_a_dead_frontend_is_not_a_banner_either(self, tmp_path):
        code, out = _run(tmp_path, _LIVE_PY, _DEAD_NPM)
        assert code == 1, out
        assert "Ctrl+C to stop" not in out
        assert "frontend exited" in out
        assert "stopping it too" in out, "half-running is not a state to leave"

    def test_a_frontend_that_dies_a_moment_later_is_still_caught(self, tmp_path):
        """The regression pin for a defect in this fix, found by running it.

        The frontend check was a single `kill -0` immediately after the API
        came up. With a stubbed curl the API is ready in milliseconds, so a
        frontend that exits in 400ms was still alive when asked, the banner
        printed, and the script exited 0 -- the very behaviour being fixed,
        reintroduced by the fix.
        """
        code, out = _run(tmp_path, _LIVE_PY, _SLOW_DEAD_NPM)
        assert code == 1, out
        assert "Ctrl+C to stop" not in out
        assert "frontend exited" in out

    def test_a_server_that_never_answers_health_is_caught(self, tmp_path):
        """Alive is not serving. The process can be up with the port unbound,
        or bound and wedged, and `/health` is the question the app ships an
        endpoint to answer."""
        code, out = _run(tmp_path, _LIVE_PY, _LIVE_NPM, FAKE_HEALTH_RC="7")
        assert code == 1, out
        assert "did not answer" in out
        assert "Ctrl+C to stop" not in out

    def test_a_good_start_earns_the_banner(self, tmp_path):
        """And the happy path has to still work, or the three above are passing
        for the wrong reason -- a script that always failed would satisfy them."""
        out_file = tmp_path / "out"
        with out_file.open("w") as sink:
            proc = subprocess.Popen(
                ["bash", str(SCRIPT)],
                stdout=sink,
                stderr=subprocess.STDOUT,
                env=_env(tmp_path, _LIVE_PY, _LIVE_NPM),
                start_new_session=True,
            )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if "Ctrl+C to stop" in out_file.read_text():
                    break
                time.sleep(0.2)
            text = out_file.read_text()
            assert "Ctrl+C to stop" in text, text
            assert "Agent API   http://127.0.0.1:8000" in text, text
        finally:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=30)


class TestTheDevServerIsNotOnEveryInterface:
    """`--host 0.0.0.0` with no gate in front of it.

    Caddy's `basic_auth` is the only authentication this project has and it
    runs on the box. Locally, with no `SEXTANT_PROXY_SECRET`, every caller
    resolves to `shared` -- which owns the CLI-ingested corpus and, since
    0.8.5, may write it. So a wide bind let anyone who could reach the port
    read the corpus through `/query`, spending the Gemini key against a
    prepaid cap, and replace a document through `/ingest`.
    """

    def test_the_default_bind_is_loopback(self):
        body = SCRIPT.read_text()
        assert 'HOST="${HOST:-127.0.0.1}"' in body
        # Comments stripped first: this script explains the old `--host
        # 0.0.0.0` in prose, and a scan that counts the explanation as the
        # code fails on the fix. Same reason the preflight's variable scan
        # strips `#` before reading the Caddyfile.
        code = "\n".join(
            ln for ln in body.splitlines() if not ln.lstrip().startswith("#")
        )
        assert "0.0.0.0" not in code, "a wide bind must be a decision, not a default"

    def test_binding_wider_says_what_that_means(self, tmp_path):
        _, out = _run(tmp_path, _DEAD_PY, _DEAD_NPM, HOST="0.0.0.0")
        assert "UNAUTHENTICATED" in out
        assert "Gemini key" in out

    def test_loopback_says_nothing(self, tmp_path):
        """A note printed on the documented default is a note people learn to
        skip, which is what makes it useless on the day it matters."""
        _, out = _run(tmp_path, _DEAD_PY, _DEAD_NPM)
        assert "UNAUTHENTICATED" not in out


class TestTheDocumentedSetupTalksToItself:
    """Two files, read by two different people, that have to agree."""

    def test_the_readme_names_the_script_that_exists(self):
        readme = (ROOT / "README.md").read_text()
        assert "./start_all_services.sh" in readme
        assert SCRIPT.exists()

    def test_the_port_the_script_serves_is_the_port_the_ui_calls(self):
        """`lib/api.ts` holds the frontend's default server URL, deliberately
        -- `.env.development` says so and explains why a tracked value there
        would be wrong for somebody. That makes these two the documented pair:
        change one and `./start_all_services.sh` starts a server the UI does
        not call, with nothing failing anywhere a test could see it.
        """
        body = SCRIPT.read_text()
        assert 'PORT="${PORT:-8000}"' in body
        api = (ROOT / "frontend" / "src" / "lib" / "api.ts").read_text()
        assert "'http://localhost:8000'" in api, "the UI's default moved; so must the script's"
