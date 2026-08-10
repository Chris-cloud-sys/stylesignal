"""In-process job queue backed by a bounded thread pool.

For local development and tests. It is genuinely asynchronous from the client's
point of view — ``POST /v1/outfits`` still returns ``pending`` immediately (§4.2)
— but the work dies with the process, so it is not a production queue. Set
``STYLESIGNAL_QUEUE_BACKEND=arq`` for that.
"""
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Set

from ..config import get_settings
from . import JobQueue

logger = logging.getLogger("stylesignal.queue")


class InProcessQueue(JobQueue):
    def __init__(self) -> None:
        settings = get_settings()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, settings.inprocess_concurrency),
            thread_name_prefix="stylesignal-worker",
        )
        # Guard against a double-enqueue for the same outfit while one is
        # already in flight. The pipeline is idempotent anyway (§8); this just
        # avoids paying for the VLM call twice.
        self._inflight: Set[uuid.UUID] = set()

    def enqueue_outfit(self, outfit_id: uuid.UUID) -> None:
        if outfit_id in self._inflight:
            logger.info("outfit %s already in flight; skipping enqueue", outfit_id)
            return
        self._inflight.add(outfit_id)
        self._executor.submit(self._run, outfit_id)

    def _run(self, outfit_id: uuid.UUID) -> None:
        # Imported here to keep the queue module free of pipeline imports.
        from ..worker.pipeline import process_outfit

        try:
            process_outfit(outfit_id)
        except Exception:  # pragma: no cover - defensive
            logger.exception("pipeline crashed for outfit %s", outfit_id)
        finally:
            self._inflight.discard(outfit_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)
