"""Redis/Arq job queue — the production backend (§4.2, §10).

Run the gateway and the worker as separate processes::

    STYLESIGNAL_QUEUE_BACKEND=arq uvicorn app.main:app
    STYLESIGNAL_QUEUE_BACKEND=arq arq app.jobs.arq_queue.WorkerSettings

The Arq job id is derived from the outfit id, so Arq deduplicates re-enqueues;
the pipeline is idempotent on top of that (§8).

This module imports ``arq`` at module scope — it is only ever imported when
``STYLESIGNAL_QUEUE_BACKEND=arq``.
"""
import asyncio
import logging
import uuid
from typing import Any, Dict

from arq import create_pool
from arq.connections import RedisSettings

from ..config import get_settings
from . import JobQueue

logger = logging.getLogger("stylesignal.queue")


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def _close_pool(pool: Any) -> None:
    """redis-py renamed ``close`` to ``aclose`` in 5.0.1."""
    closer = getattr(pool, "aclose", None) or getattr(pool, "close", None)
    if closer is None:  # pragma: no cover
        return
    result = closer()
    if asyncio.iscoroutine(result):
        await result


class ArqQueue(JobQueue):
    """Enqueue side. Lives in the gateway process."""

    def enqueue_outfit(self, outfit_id: uuid.UUID) -> None:
        # Called from a sync request handler running in FastAPI's threadpool,
        # so we drive the async Redis client on a private event loop. One
        # connection per enqueue is fine at scan volumes; if enqueue latency
        # ever shows up in traces, hoist a shared pool onto app.state instead.
        asyncio.run(self._enqueue(outfit_id))

    async def _enqueue(self, outfit_id: uuid.UUID) -> None:
        pool = await create_pool(_redis_settings())
        try:
            await pool.enqueue_job(
                "process_outfit_job",
                str(outfit_id),
                _job_id="outfit:{0}".format(outfit_id),
            )
        finally:
            await _close_pool(pool)


# --- Worker side -----------------------------------------------------------
async def process_outfit_job(_ctx: Dict[str, Any], outfit_id: str) -> None:
    from ..worker.pipeline import process_outfit

    # The pipeline is synchronous; keep it off the worker's event loop.
    await asyncio.to_thread(process_outfit, uuid.UUID(outfit_id))


async def _startup(_ctx: Dict[str, Any]) -> None:
    from ..db import init_db

    init_db()
    logger.info("arq worker ready")


class WorkerSettings:
    functions = [process_outfit_job]
    on_startup = _startup
    redis_settings = _redis_settings()
    max_jobs = 4
    # Above the worst case of vlm_timeout_seconds x (1 + vlm_max_lint_retries)
    # (~360s) with margin — matches stale_processing_timeout_seconds so Arq
    # and the read-time reaper agree on what "too long" means.
    job_timeout = 480
    keep_result = 60
