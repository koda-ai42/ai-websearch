from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from urllib.parse import urlsplit


class DomainRateLimiter:
    """Bound concurrency and start rate independently for every destination host."""

    def __init__(self, concurrency: int, min_interval_seconds: float) -> None:
        if concurrency < 1 or min_interval_seconds < 0:
            raise ValueError("concurrency must be positive and min interval cannot be negative")
        self._concurrency = concurrency
        self._min_interval = min_interval_seconds
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._next_start: defaultdict[str, float] = defaultdict(float)

    @staticmethod
    def key(url: str) -> str:
        parsed = urlsplit(url)
        return (parsed.hostname or "unknown").casefold().rstrip(".")

    @asynccontextmanager
    async def acquire(self, url: str):
        key = self.key(url)
        semaphore = self._semaphores.setdefault(key, asyncio.Semaphore(self._concurrency))
        await semaphore.acquire()
        try:
            async with self._locks[key]:
                wait_for = self._next_start[key] - time.monotonic()
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
                self._next_start[key] = time.monotonic() + self._min_interval
            yield
        finally:
            semaphore.release()
