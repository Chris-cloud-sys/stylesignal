"""Per-user rate limiting — spec §8.

A fixed-window counter kept in process memory. That is correct for a single
gateway process and for tests; with more than one worker it under-counts, so
point it at Redis (``STYLESIGNAL_REDIS_URL`` is already configured) before
running more than one instance.

This is the *request* limiter. The *cost* limiter — the thing that actually
protects the VLM spend — is the scan quota in :mod:`app.quota`.
"""
import threading
import time
from typing import Dict, Tuple

from fastapi import status

from .errors import APIError

_lock = threading.Lock()
_windows: Dict[str, Tuple[int, int]] = {}


def check(key: str, limit: int, window_seconds: int) -> None:
    """Allow ``limit`` events per ``window_seconds`` for ``key``."""
    now = int(time.time())
    bucket = now // window_seconds

    with _lock:
        current_bucket, count = _windows.get(key, (bucket, 0))
        if current_bucket != bucket:
            current_bucket, count = bucket, 0
        count += 1
        _windows[key] = (current_bucket, count)

        if len(_windows) > 10_000:
            _evict(bucket)

    if count > limit:
        retry_after = ((bucket + 1) * window_seconds) - now
        raise APIError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "Too many requests. Try again in {0}s.".format(max(1, retry_after)),
            {"retry_after_seconds": max(1, retry_after), "limit": limit},
        )


def _evict(current_bucket: int) -> None:
    stale = [k for k, (b, _) in _windows.items() if b < current_bucket]
    for key in stale:
        _windows.pop(key, None)


def reset() -> None:
    """Test hook."""
    with _lock:
        _windows.clear()
