from __future__ import annotations

import time
from collections import defaultdict, deque

from .errors import ProxyError


class RateLimiter:
    """In-memory sliding window per key id. (Single-process; put a real limiter at the reverse proxy for HA.)"""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, key_id: int) -> None:
        if self.per_minute <= 0:
            return
        now = time.monotonic()
        q = self._hits[key_id]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            retry = max(1, int(60 - (now - q[0])))
            raise ProxyError(429, "Rate limit exceeded", "rate_limit_error", "rate_limit_exceeded", {"Retry-After": str(retry)})
        q.append(now)


class RedisRateLimiter:
    """Fixed one-minute window per key id, shared by all instances (INCR + EXPIRE)."""

    def __init__(self, url: str, per_minute: int, *, client=None, prefix: str = "cliproxy"):  # noqa: ANN001
        if client is None:
            import redis  # optional dependency: pip install redis

            client = redis.Redis.from_url(url)
        self._r, self.per_minute, self._prefix = client, per_minute, prefix

    def check(self, key_id: int) -> None:
        if self.per_minute <= 0:
            return
        now = time.time()
        k = f"{self._prefix}:rate:{key_id}:{int(now // 60)}"
        pipe = self._r.pipeline()
        pipe.incr(k)
        pipe.expire(k, 120)
        if pipe.execute()[0] > self.per_minute:
            retry = max(1, int(60 - now % 60))
            raise ProxyError(429, "Rate limit exceeded", "rate_limit_error", "rate_limit_exceeded", {"Retry-After": str(retry)})
