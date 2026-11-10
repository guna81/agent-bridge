from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncIterator


class QueueTimeout(Exception):
    """Could not obtain a run slot within the queue timeout."""


class JobQueue(ABC):
    """Admission control for CLI runs. A Celery/Redis implementation can be dropped in behind this."""

    @abstractmethod
    def slot(self, user_id: int):  # -> async context manager
        ...

    @abstractmethod
    def stats(self) -> dict: ...


class LocalJobQueue(JobQueue):
    def __init__(self, max_concurrency: int, per_user: int, queue_timeout: float):
        self._global = asyncio.Semaphore(max_concurrency)
        self._per_user_n = per_user
        self._users: dict[int, asyncio.Semaphore] = {}
        self._timeout = queue_timeout
        self._max = max_concurrency
        self._running = 0
        self._waiting = 0

    @asynccontextmanager
    async def slot(self, user_id: int) -> AsyncIterator[None]:
        usem = self._users.setdefault(user_id, asyncio.Semaphore(self._per_user_n))
        deadline = time.monotonic() + self._timeout
        self._waiting += 1
        got_user = got_global = False
        try:
            await asyncio.wait_for(usem.acquire(), max(0.0, deadline - time.monotonic()))
            got_user = True
            await asyncio.wait_for(self._global.acquire(), max(0.0, deadline - time.monotonic()))
            got_global = True
        except asyncio.TimeoutError:
            raise QueueTimeout("server is busy, try again shortly") from None
        finally:
            self._waiting -= 1
            if not got_global:
                if got_user:
                    usem.release()
        self._running += 1
        try:
            yield
        finally:
            self._running -= 1
            self._global.release()
            usem.release()

    def stats(self) -> dict:
        return {"running": self._running, "waiting": self._waiting, "max_concurrency": self._max}


class RedisJobQueue(JobQueue):
    """Same admission rules as LocalJobQueue, shared by every proxy instance that points at one Redis.

    Each limit is a sorted set of slot holders scored by lease expiry (the classic Redis "fair semaphore"):
    add yourself, drop expired holders, and you hold a slot if your rank is below the limit. A holder that
    crashes simply stops renewing, so its slot frees itself after `lease_s`.
    """

    def __init__(self, url: str, max_concurrency: int, per_user: int, queue_timeout: float, *, lease_s: float = 30.0,
                 client=None, prefix: str = "cliproxy"):  # noqa: ANN001  # fmt: skip
        if client is None:
            import redis.asyncio as aioredis  # optional dependency: pip install redis

            client = aioredis.from_url(url)
        self._r = client
        self._max, self._per_user, self._timeout, self._lease = max_concurrency, per_user, queue_timeout, lease_s
        self._global_key = f"{prefix}:slots:global"
        self._prefix = prefix
        self._running = 0
        self._waiting = 0

    async def _try(self, key: str, member: str, limit: int) -> bool:
        now = time.time()
        pipe = self._r.pipeline(transaction=True)
        pipe.zremrangebyscore(key, "-inf", now)
        pipe.zadd(key, {member: now + self._lease})
        pipe.zrank(key, member)
        pipe.expire(key, int(self._lease * 4))
        rank = (await pipe.execute())[2]
        if rank is not None and rank < limit:
            return True
        await self._r.zrem(key, member)
        return False

    async def _acquire(self, key: str, member: str, limit: int, deadline: float) -> None:
        delay = 0.05
        while not await self._try(key, member, limit):
            if time.monotonic() + delay > deadline:
                raise QueueTimeout("server is busy, try again shortly")
            await asyncio.sleep(delay)
            delay = min(0.5, delay * 1.5)

    async def _renew(self, keys: list[str], member: str) -> None:
        while True:
            await asyncio.sleep(self._lease / 3)
            for k in keys:
                await self._r.zadd(k, {member: time.time() + self._lease}, xx=True)

    @asynccontextmanager
    async def slot(self, user_id: int) -> AsyncIterator[None]:
        import uuid

        member = uuid.uuid4().hex
        user_key = f"{self._prefix}:slots:user:{user_id}"
        deadline = time.monotonic() + self._timeout
        held: list[str] = []
        self._waiting += 1
        try:
            await self._acquire(user_key, member, self._per_user, deadline)
            held.append(user_key)
            await self._acquire(self._global_key, member, self._max, deadline)
            held.append(self._global_key)
        except BaseException:
            for k in held:
                await self._r.zrem(k, member)
            raise
        finally:
            self._waiting -= 1
        self._running += 1
        renew = asyncio.create_task(self._renew(held, member))
        try:
            yield
        finally:
            self._running -= 1
            renew.cancel()
            for k in held:
                await asyncio.shield(self._r.zrem(k, member))

    def stats(self) -> dict:
        # this instance's view; the cluster-wide count lives in Redis (ZCARD <prefix>:slots:global)
        return {"running": self._running, "waiting": self._waiting, "max_concurrency": self._max}
