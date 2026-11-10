"""Cost protection: per-IP rate limits, concurrency cap, daily call and spend caps.

Rate limits and the concurrency cap are in memory (per instance). The daily caps live in
SQLite, so they survive restarts. Every trigger is logged and counted for /metrics.
Production would move these to a shared store (Redis) and a provider-side budget (see HANDOFF).
"""

import logging
import threading
import time
from collections import Counter, defaultdict, deque

from app import store
from app.config import settings
from app.logs import log_event

TRIGGERS: Counter = Counter()  # cap/limit triggers since process start (for /metrics)
_TRIGGER_LOCK = threading.Lock()

MSG_RATE = "Too many requests from your network. Please wait a minute and try again."
MSG_BUSY = "The service is busy assessing other claims. Please try again in a moment."
MSG_DAILY = ("The daily usage limit for this demo has been reached, so no new assessments can run today. "
             "Please try again tomorrow (UTC) or contact the administrator.")
MSG_UNAVAILABLE = "Usage limits could not be checked, so the request was refused. Please try again later."


class CapError(Exception):
    """A limit stopped the request before any model call. Message is safe to show the user."""

    def __init__(self, message: str, status: int, kind: str):
        super().__init__(message)
        self.status = status
        self.kind = kind


def trigger(kind: str, **fields) -> None:
    with _TRIGGER_LOCK:
        TRIGGERS[kind] += 1
    log_event("limit_triggered", logging.WARNING, kind=kind, **fields)


class RateLimiter:
    """Sliding 60-second window per key."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, per_minute: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= per_minute:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


LIMITER = RateLimiter()


class ConcurrencyCap:
    def __init__(self):
        self._lock = threading.Lock()
        self.active = 0

    def try_acquire(self) -> bool:
        with self._lock:
            if self.active >= settings.max_concurrent_claims:
                return False
            self.active += 1
            return True

    def release(self) -> None:
        with self._lock:
            self.active = max(0, self.active - 1)


CONCURRENCY = ConcurrencyCap()


class DailyCapGuard:
    """Passed into the pipeline by the API. reserve() runs right before each model call."""

    def __init__(self, request_id: str):
        self.request_id = request_id

    def reserve(self) -> None:
        try:
            ok, usage = store.reserve_call(settings.daily_call_cap, settings.daily_spend_cap_usd)
        except Exception as e:  # fail closed
            trigger("usage_ledger_error", request_id=self.request_id, error=type(e).__name__)
            raise CapError(MSG_UNAVAILABLE, 503, "usage_ledger_error")
        if not ok:
            trigger("daily_cap", request_id=self.request_id, calls=usage["calls"], spend_usd=usage["spend_usd"],
                    call_cap=settings.daily_call_cap, spend_cap_usd=settings.daily_spend_cap_usd)
            raise CapError(MSG_DAILY, 429, "daily_cap")

    def record(self, attempts: int, cost_usd: float) -> None:
        """attempts includes the call already counted by reserve()."""
        store.record_usage(max(0, attempts - 1), cost_usd)
