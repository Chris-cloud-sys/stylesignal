"""Processing job queue — spec §4.2.

§10 leaves the queue open (Arq / Celery / RQ). This picks **Arq** for
production, as the spec recommends, and adds an in-process thread-pool backend
so the whole pipeline runs locally without Redis.

Jobs are keyed by ``outfit_id`` and the pipeline is idempotent (§8), so a retry
or a double-enqueue can never duplicate garments or feedback.
"""
import uuid
from abc import ABC, abstractmethod
from typing import Optional

from ..config import get_settings


class JobQueue(ABC):
    @abstractmethod
    def enqueue_outfit(self, outfit_id: uuid.UUID) -> None:
        """Schedule the processing pipeline for one outfit."""

    def shutdown(self) -> None:  # pragma: no cover - optional hook
        """Drain in-flight work on application shutdown."""


_queue: Optional[JobQueue] = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        settings = get_settings()
        if settings.queue_backend == "arq":
            from .arq_queue import ArqQueue

            _queue = ArqQueue()
        elif settings.queue_backend == "inprocess":
            from .inprocess import InProcessQueue

            _queue = InProcessQueue()
        else:
            raise ValueError(
                "Unknown STYLESIGNAL_QUEUE_BACKEND: "
                "{0!r} (expected 'inprocess' or 'arq')".format(settings.queue_backend)
            )
    return _queue


def reset_queue() -> None:
    """Test hook — drops the cached backend."""
    global _queue
    if _queue is not None:
        _queue.shutdown()
    _queue = None


__all__ = ["JobQueue", "get_queue", "reset_queue"]
