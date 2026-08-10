"""Rate limiting — spec §8.

Exercises the inprocess backend directly, the same way test_pipeline.py tests
worker functions directly rather than only through the API. The redis backend
needs a live Redis and has no local test here, matching this codebase's
existing precedent for other infra-dependent production backends (ArqQueue,
S3Storage) — see docs/deployment.md before relying on it.
"""
import pytest

from app.errors import APIError
from app.ratelimit.inprocess import InProcessRateLimiter


def test_allows_up_to_the_limit():
    limiter = InProcessRateLimiter()
    for _ in range(5):
        limiter.check("user:1", limit=5, window_seconds=60)


def test_blocks_once_over_the_limit():
    limiter = InProcessRateLimiter()
    for _ in range(5):
        limiter.check("user:1", limit=5, window_seconds=60)
    with pytest.raises(APIError) as excinfo:
        limiter.check("user:1", limit=5, window_seconds=60)
    assert excinfo.value.status_code == 429
    assert excinfo.value.code == "rate_limited"
    assert excinfo.value.details["limit"] == 5


def test_keys_are_independent():
    limiter = InProcessRateLimiter()
    for _ in range(5):
        limiter.check("user:1", limit=5, window_seconds=60)
    # A different key has its own budget, untouched by user:1's usage.
    limiter.check("user:2", limit=5, window_seconds=60)


def test_new_window_resets_the_count(monkeypatch):
    import app.ratelimit.inprocess as inprocess_module

    current = [1_000_000]
    monkeypatch.setattr(inprocess_module.time, "time", lambda: current[0])

    limiter = InProcessRateLimiter()
    for _ in range(5):
        limiter.check("user:1", limit=5, window_seconds=60)
    with pytest.raises(APIError):
        limiter.check("user:1", limit=5, window_seconds=60)

    # Jump forward past the window boundary; the count starts over.
    current[0] += 60
    limiter.check("user:1", limit=5, window_seconds=60)


def test_retry_after_is_time_remaining_in_the_window(monkeypatch):
    import app.ratelimit.inprocess as inprocess_module

    # 60010 is exactly 10s into the [60000, 60060) window (bucket 1000 at
    # window_seconds=60), so 50s should remain until the bucket rolls over.
    monkeypatch.setattr(inprocess_module.time, "time", lambda: 60_010)

    limiter = InProcessRateLimiter()
    limiter.check("user:1", limit=1, window_seconds=60)
    with pytest.raises(APIError) as excinfo:
        limiter.check("user:1", limit=1, window_seconds=60)

    assert excinfo.value.details["retry_after_seconds"] == 50
