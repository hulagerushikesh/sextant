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

# The largest fraction of the day's cap any one *authenticated* name may spend.
# 1.0 (the default) means no per-owner limit at all, which is the behaviour of
# every version before 0.8.6 and the right default for a box with one user: a
# share below 1 leaves part of a wallet the operator paid for unspendable when
# they are the only person asking. Set it on a deployment that has users --
# `deploy/env.example` explains the arithmetic. Only applied to a name the
# proxy vouched for; see `DailyBudget.check_owner`.
DAILY_BUDGET_SHARE = float(settings.getenv("DAILY_BUDGET_SHARE", "1") or "1")
if not 0 < DAILY_BUDGET_SHARE <= 1:
    logging.getLogger(__name__).warning(
        "%s is %s, which is not a fraction in (0, 1]; no per-owner share will be "
        "applied. The global daily cap is unaffected.",
        settings.env_name("DAILY_BUDGET_SHARE"),
        DAILY_BUDGET_SHARE,
    )
    DAILY_BUDGET_SHARE = 1.0


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

    ## Two guarantees, two checks

    The cap above protects the operator's wallet, and it is the one thing a
    shared or leaked gate can never get past. It does nothing at all for the
    other people behind that gate: the first person to spend the day silences
    everybody until 00:00 UTC, which is a denial of service any authenticated
    user can perform by accident, just by working for an afternoon.

    So there is a second, *per-owner* ceiling at `share` x `budget`, and it
    sits **under** the global one rather than replacing it. `check` is the
    wallet, `check_owner` is the fairness; a query has to pass both. Written
    that way round deliberately -- a per-owner cap that replaced the global one
    would make the bill scale with the number of users, which is exactly the
    guarantee `deploy/env.example` promises it will not do.

    What it does not do is divide the day equally between whoever turns up.
    That needs to know how many people there are, and this process does not:
    the user list lives in Caddy's `.env`. A fixed fraction is a number the
    operator sets with the user list in front of them, and the cost of getting
    it wrong is legible -- too low wastes the wallet, too high lets one person
    take more of it.
    """

    def __init__(
        self, budget_usd: float = DAILY_BUDGET_USD, share: float = DAILY_BUDGET_SHARE
    ):
        self.budget = budget_usd
        self.share = share if 0 < share <= 1 else 1.0
        self._day = self._today()
        self._spent = 0.0
        self._by_owner: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    @property
    def owner_budget(self) -> float:
        """What one name may spend in a day, or 0.0 when there is no share."""
        return 0.0 if self.share >= 1 else self.budget * self.share

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
            self._by_owner.clear()

    def check(self) -> tuple[bool, float, int]:
        """(allowed, spent_today, seconds_until_reset). Always allowed when off."""
        if self.budget <= 0:
            return True, 0.0, 0
        with self._lock:
            self._rollover()
            return self._spent < self.budget, self._spent, self._seconds_to_reset()

    def check_owner(self, owner: str | None) -> tuple[bool, float, int]:
        """(allowed, this owner's spend today, seconds until reset).

        Separate from `check` rather than folded into it, because the two
        refusals mean different things to whoever reads them: one says the box
        is done for the day, the other says *you* are and somebody else is not.

        `owner` is None for a name nothing vouched for. A bucket keyed on a
        header anybody can retype is emptied by retyping it, so an untrusted
        caller is held only by the global cap -- the same protection they had
        before this existed, and no false promise of a second one.
        """
        if self.budget <= 0 or self.share >= 1 or not owner:
            return True, 0.0, 0
        with self._lock:
            self._rollover()
            spent = self._by_owner.get(owner, 0.0)
            return spent < self.owner_budget, spent, self._seconds_to_reset()

    def record(self, cost_usd: float, owner: str | None = None) -> None:
        """Add a finished query's cost to today's tally. No-op when off.

        An untrusted caller's spend still counts against the day -- it is real
        money -- it is simply not attributed to a name, because the name is
        not worth attributing to.
        """
        if self.budget <= 0 or cost_usd <= 0:
            return
        with self._lock:
            self._rollover()
            self._spent += cost_usd
            if owner:
                self._by_owner[owner] += cost_usd

    def status(self, owner: str | None = None) -> dict[str, object]:
        """A snapshot for /health, so the UI can show the day's spend.

        With a trusted `owner` and a share configured, it also reports what is
        left of *their* share -- otherwise someone refused at 20% of a cap they
        can see is unspent has no way to tell why.
        """
        if self.budget <= 0:
            return {"enabled": False}
        with self._lock:
            self._rollover()
            snapshot: dict[str, object] = {
                "enabled": True,
                "budget_usd": round(self.budget, 4),
                "spent_usd": round(self._spent, 6),
                "remaining_usd": round(max(0.0, self.budget - self._spent), 6),
                "resets_in_seconds": self._seconds_to_reset(),
            }
            if self.share < 1:
                snapshot["share"] = round(self.share, 4)
                snapshot["owner_budget_usd"] = round(self.owner_budget, 6)
                if owner:
                    mine = self._by_owner.get(owner, 0.0)
                    snapshot["owner_spent_usd"] = round(mine, 6)
                    snapshot["owner_remaining_usd"] = round(
                        max(0.0, self.owner_budget - mine), 6
                    )
            return snapshot

    def reset(self) -> None:
        with self._lock:
            self._day = self._today()
            self._spent = 0.0
            self._by_owner.clear()
