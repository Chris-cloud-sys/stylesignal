"""In-process fixed-window limiter — the local/single-process backend.

Correct for one gateway process and for tests. Each worker process holds its
own counters, so this under-counts across more than one process — see
:mod:`app.ratelimit.redis_backend` for the backend that doesn't.
"""
import threading
import time
from typing import Dict, Tuple

from fastapi import status

from ..errors import APIError
from . import RateLimiter


class InProcessRateLimiter(RateLimiter):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: Dict[str, Tuple[int, int]] = {}

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = int(time.time())
        bucket = now // window_seconds

        with self._lock:
            current_bucket, count = self._windows.get(key, (bucket, 0))
            if current_bucket != bucket:
                current_bucket, count = bucket, 0
            count += 1
            self._windows[key] = (current_bucket, count)

            if len(self._windows) > 10_000:
                self._evict(bucket)

        if count > limit:
            retry_after = ((bucket + 1) * window_seconds) - now
            raise APIError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate_limited",
                "Too many requests. Try again in {0}s.".format(max(1, retry_after)),
                {"retry_after_seconds": max(1, retry_after), "limit": limit},
            )

    def _evict(self, current_bucket: int) -> None:
        stale = [k for k, (b, _) in self._windows.items() if b < current_bucket]
        for key in stale:
            self._windows.pop(key, None)
