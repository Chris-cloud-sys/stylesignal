"""Per-user rate limiting — spec §8.

One interface, two backends, mirroring ``storage`` and ``jobs``. ``inprocess``
keeps a fixed-window counter in process memory — correct for a single gateway
process and for tests, but it under-counts once you run more than one worker,
because each process only sees its own share of requests. ``redis`` shares the
same counters across every worker via a single INCR+EXPIRE window, so the
limit means what it says once the gateway is scaled out.

This is the *request* limiter. The *cost* limiter — the thing that actually
protects the VLM spend — is the scan quota in :mod:`app.quota`.
"""
from abc import ABC, abstractmethod
from typing import Optional

from ..config import get_settings


class RateLimiter(ABC):
    @abstractmethod
    def check(self, key: str, limit: int, window_seconds: int) -> None:
        """Allow ``limit`` events per ``window_seconds`` for ``key``.

        Raises the §6 ``rate_limited`` envelope (429) once the window's count
        exceeds ``limit``.
        """


_limiter: Optional[RateLimiter] = None


def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        if settings.ratelimit_backend == "redis":
            from .redis_backend import RedisRateLimiter

            _limiter = RedisRateLimiter(settings.redis_url)
        elif settings.ratelimit_backend == "inprocess":
            from .inprocess import InProcessRateLimiter

            _limiter = InProcessRateLimiter()
        else:
            raise ValueError(
                "Unknown STYLESIGNAL_RATELIMIT_BACKEND: "
                "{0!r} (expected 'inprocess' or 'redis')".format(
                    settings.ratelimit_backend
                )
            )
    return _limiter


def check(key: str, limit: int, window_seconds: int) -> None:
    """Module-level convenience so call sites stay ``ratelimit.check(...)``."""
    get_limiter().check(key, limit, window_seconds)


def reset_limiter() -> None:
    """Test hook — drops the cached backend."""
    global _limiter
    _limiter = None


# Old name, kept so nothing importing ``ratelimit.reset`` breaks.
reset = reset_limiter

__all__ = ["RateLimiter", "get_limiter", "check", "reset_limiter", "reset"]
