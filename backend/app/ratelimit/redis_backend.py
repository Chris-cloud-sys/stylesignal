"""Redis-backed fixed-window limiter — the production backend (§8, §10).

Same fixed-window scheme as :mod:`app.ratelimit.inprocess` (a bucket per
``now // window_seconds``), just shared across every gateway process through
one Redis key instead of an in-process dict, so the limit is the limit no
matter how many workers are running.

This module imports ``redis`` at call time (not at module scope), same as
``arq_queue`` treats ``arq`` — it is only ever needed when
``STYLESIGNAL_RATELIMIT_BACKEND=redis``.
"""
import logging
import time

from fastapi import status

from ..errors import APIError
from . import RateLimiter

logger = logging.getLogger("stylesignal.ratelimit")


class RedisRateLimiter(RateLimiter):
    def __init__(self, redis_url: str) -> None:
        import redis

        # A single shared connection pool for the process; redis-py is
        # thread-safe and each request only needs one round trip.
        self._client = redis.Redis.from_url(redis_url)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = int(time.time())
        bucket = now // window_seconds
        redis_key = "stylesignal:ratelimit:{0}:{1}".format(key, bucket)

        try:
            pipe = self._client.pipeline()
            pipe.incr(redis_key)
            count, _ = pipe.execute()
            if count == 1:
                # Only the request that created this window's key sets its
                # TTL. Not perfectly atomic with the INCR above — a crash in
                # this exact gap could leave a key without a TTL — but the
                # bucket suffix changes every window regardless, so a stray
                # key is a harmless few bytes, never a correctness problem.
                self._client.expire(redis_key, window_seconds)
        except Exception:  # noqa: BLE001 - a limiter must not become an outage
            logger.warning(
                "Redis unreachable for rate limiting (key=%s); allowing the "
                "request rather than failing the gateway on it.",
                key,
            )
            return

        if count > limit:
            retry_after = ((bucket + 1) * window_seconds) - now
            raise APIError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate_limited",
                "Too many requests. Try again in {0}s.".format(max(1, retry_after)),
                {"retry_after_seconds": max(1, retry_after), "limit": limit},
            )
