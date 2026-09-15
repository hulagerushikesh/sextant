"""
Request identity, structured logging, and rate limiting.

The thread running through all three is being able to answer "what happened on
that one request?" after the fact. A query fans out into a model call, one or
more MCP tool calls in a subprocess, and an SSE stream, and without a shared id
those are three unrelated log streams.

The id travels in a ContextVar rather than as an argument, because the alternative
is threading a parameter through every function between the HTTP handler and the
agent loop, most of which have no other reason to know about HTTP.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta

from tools import settings

REQUEST_ID_HEADER = "X-Request-ID"
request_id: ContextVar[str] = ContextVar("request_id", default="-")

# Fixed-window rate limit, per client. Deliberately in-process and approximate:
# this protects a single-process demo from a runaway loop or an open tab
# hammering the model, and it is not a substitute for a real gateway in front of
# a deployment that has more than one replica.
RATE_LIMIT_REQUESTS = int(settings.getenv("RATE_LIMIT", "20") or "20")
RATE_LIMIT_WINDOW_SECONDS = int(settings.getenv("RATE_WINDOW", "60") or "60")

# Hard ceiling on estimated model spend per UTC day. Off by default (<= 0): a
# cost cap that fires unexpectedly is worse than none for someone running
# locally. Set it in a public deployment so a leaked URL can never run up a bill.
DAILY_BUDGET_USD = float(settings.getenv("DAILY_BUDGET_USD", "0") or "0")


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so logs can be queried rather than grepped."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Anything passed as `extra=` rides along, which is how the agent
        # reports turn counts and token usage without inventing a metrics tier.
        for key, value in record.__dict__.items():
            if key.startswith("agent_"):
                payload[key[6:]] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None, json_logs: bool | None = None) -> None:
    """Install the formatter and the request-id filter on the root logger."""
    if json_logs is None:
        json_logs = (settings.getenv("LOG_FORMAT", "text") or "text").lower() == "json"

    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter()
        if json_logs
        else logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level or settings.getenv("LOG_LEVEL") or "INFO")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class RateLimiter:
    """A fixed-window counter keyed by client.

    Not a token bucket: the extra precision would not change the behaviour of
    the thing it protects, and a window of timestamps is auditable at a glance.
    """

    def __init__(self, limit: int = RATE_LIMIT_REQUESTS, window: int = RATE_LIMIT_WINDOW_SECONDS):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client: str, now: float | None = None) -> tuple[bool, int]:
        """Returns (allowed, seconds until a slot frees)."""
        if self.limit <= 0:  # disabled
            return True, 0

        now = time.monotonic() if now is None else now
        hits = self._hits[client]
        while hits and now - hits[0] >= self.window:
            hits.popleft()

        if len(hits) >= self.limit:
            return False, max(1, int(self.window - (now - hits[0])))

        hits.append(now)
        return True, 0

    def reset(self) -> None:
        self._hits.clear()


class DailyBudget:
    """A hard ceiling on estimated model spend per UTC day.

    Once a day's summed per-query cost crosses the cap, new queries are refused
    until 00:00 UTC. Same tradeoff as the rate limiter: in-process and
    approximate -- it stops a single process running away, and a multi-replica
    deployment would move the tally to a shared store so replicas share one cap.

    Granularity is one query: the cap is checked before a query starts and the
    query's cost is added when it finishes, so the day can overshoot by at most
    the cost of the one query that crossed the line. On the default Flash-Lite
    tier that overshoot is a fraction of a cent, so per-query is precise enough
    and the loop needs no mid-flight accounting.

    Disabled when the cap is <= 0, which is the default.
    """

    def __init__(self, budget_usd: float = DAILY_BUDGET_USD):
        self.budget = budget_usd
        self._day = self._today()
        self._spent = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _today() -> date:
        return datetime.now(UTC).date()

    @staticmethod
    def _seconds_to_reset() -> int:
        now = datetime.now(UTC)
        midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return int((midnight - now).total_seconds())

    def _rollover(self) -> None:
        """Zero the tally when the UTC day turns over. Caller holds the lock."""
        today = self._today()
        if today != self._day:
            self._day = today
            self._spent = 0.0

    def check(self) -> tuple[bool, float, int]:
        """(allowed, spent_today, seconds_until_reset). Always allowed when off."""
        if self.budget <= 0:
            return True, 0.0, 0
        with self._lock:
            self._rollover()
            return self._spent < self.budget, self._spent, self._seconds_to_reset()

    def record(self, cost_usd: float) -> None:
        """Add a finished query's cost to today's tally. No-op when off."""
        if self.budget <= 0 or cost_usd <= 0:
            return
        with self._lock:
            self._rollover()
            self._spent += cost_usd

    def status(self) -> dict[str, object]:
        """A snapshot for /health, so the UI can show the day's spend."""
        if self.budget <= 0:
            return {"enabled": False}
        with self._lock:
            self._rollover()
            return {
                "enabled": True,
                "budget_usd": round(self.budget, 4),
                "spent_usd": round(self._spent, 6),
                "remaining_usd": round(max(0.0, self.budget - self._spent), 6),
                "resets_in_seconds": self._seconds_to_reset(),
            }

    def reset(self) -> None:
        with self._lock:
            self._day = self._today()
            self._spent = 0.0
