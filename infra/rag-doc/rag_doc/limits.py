"""Anti-abuse guards: per-IP sliding-window rate limit and a global daily call cap."""

import time
from collections import deque
from collections.abc import Callable
from datetime import date

from fastapi import HTTPException, Request, status

from rag_doc.config import get_settings
from rag_doc.texts import DAILY_CAP_ANSWER, RATE_LIMIT_ANSWER


class RateLimiter:
    def __init__(
        self,
        per_minute: int,
        daily_cap: int,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._per_minute = per_minute
        self._daily_cap = daily_cap
        self._clock = clock
        self._today = today
        self._hits: dict[str, deque[float]] = {}
        self._day = today()
        self._day_count = 0

    def check(self, client: str) -> str | None:
        """Return the rejection reason ("rate" or "daily") or None, counting the call if allowed."""
        now = self._clock()
        if self._today() != self._day:
            self._day, self._day_count = self._today(), 0
        if self._day_count >= self._daily_cap:
            return "daily"
        window = self._hits.setdefault(client, deque())
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= self._per_minute:
            return "rate"
        window.append(now)
        self._day_count += 1
        if len(self._hits) > 10_000:
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < 60}
        return None


def client_ip(request: Request, trust_proxy: bool) -> str:
    """Behind NPM the rightmost X-Forwarded-For entry is the one the proxy appended."""
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def enforce_limits(request: Request) -> None:
    settings = get_settings()
    reason = get_rate_limiter(request).check(client_ip(request, settings.trust_proxy_headers))
    if reason == "daily":
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, DAILY_CAP_ANSWER)
    if reason == "rate":
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, RATE_LIMIT_ANSWER, headers={"Retry-After": "60"}
        )
