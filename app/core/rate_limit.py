"""Rate limiting for the doors strangers can knock on (login, register, forgot-password, public RSVP).

In memory and per process: compose runs one API worker, which is what this is sized for (several workers would each
count on their own; Redis would be the fix). A sliding window per key; `hit` answers 429 with `Retry-After`.
The client IP comes from X-Forwarded-For only as far as TRUSTED_PROXY_HOPS says (see `client_ip`).
"""

import math
import time
from collections import deque

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self.enabled = get_settings().rate_limit_enabled
        self._hits: dict[str, deque[float]] = {}
        self._clock = time.monotonic

    def reset(self) -> None:
        self._hits.clear()

    def check(self, key: str, limit: int, window: float) -> deque[float] | None:
        """Raise 429 when `key` already made `limit` attempts in the last `window` seconds; nothing is counted."""
        if not self.enabled:
            return None
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, math.ceil(hits[0] + window - now))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many attempts, try again later",
                headers={"Retry-After": str(retry_after)},
            )
        return hits

    def count(self, key: str, window: float) -> int:
        """How many attempts `key` made in the last `window` seconds (0 when the limiter is off)."""
        if not self.enabled:
            return 0
        now = self._clock()
        return sum(1 for t in self._hits.get(key, ()) if t > now - window)

    def record(self, key: str) -> None:
        if not self.enabled:
            return
        now = self._clock()
        self._hits.setdefault(key, deque()).append(now)
        if len(self._hits) > 20000:  # bounded memory: drop keys whose attempts are all old
            for stale in [k for k, v in self._hits.items() if not v or v[-1] <= now - 3600]:
                del self._hits[stale]

    def hit(self, key: str, limit: int, window: float) -> None:
        """Count one attempt, refusing it (429) when the key is already at its limit."""
        self.check(key, limit, window)
        self.record(key)


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    """The caller's address. X-Forwarded-For is trusted only `trusted_proxy_hops` entries from the right (each trusted
    proxy appends the address it saw), so a client cannot invent its own address by sending the header itself."""
    hops = get_settings().trusted_proxy_hops
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if hops > 0 and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else "unknown"


#: Without a trusted proxy every request reaches the API from the web container (Next.js's /api proxy passes the
#: visitor's address on only if a real reverse proxy in front of it sent one), so the "address" is shared by everybody and
#: the per-address limits would throttle the whole family. They are loosened by this factor in that case; the per-account
#: failure limit on login is what stops password guessing either way.
SHARED_ADDRESS_FACTOR = 5


def limit_by_ip(request: Request, bucket: str, limit: int, window: float) -> None:
    if get_settings().trusted_proxy_hops == 0:
        limit *= SHARED_ADDRESS_FACTOR
    limiter.hit(f"{bucket}:ip:{client_ip(request)}", limit, window)
