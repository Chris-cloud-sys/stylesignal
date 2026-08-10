"""Object storage — spec §4.9, key layout §5.7.

One interface, two backends. ``local`` writes to disk and serves through the
signed ``/v1/media`` route so the whole stack runs with no cloud account;
``s3`` is the production path with SSE enabled per §8.
"""
from abc import ABC, abstractmethod
from typing import Optional

from ..config import get_settings


class ObjectStorage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Write (or overwrite) an object."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Read an object. Raises FileNotFoundError if absent."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under ``prefix``. Returns the count removed."""

    @abstractmethod
    def signed_url(self, key: str, ttl_seconds: Optional[int] = None) -> str:
        """A time-limited URL the mobile client can fetch directly."""


_storage: Optional[ObjectStorage] = None


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.storage_backend == "s3":
            from .s3 import S3Storage

            _storage = S3Storage()
        elif settings.storage_backend == "local":
            from .local import LocalStorage

            _storage = LocalStorage()
        else:
            raise ValueError(
                "Unknown STYLESIGNAL_STORAGE_BACKEND: "
                "{0!r} (expected 'local' or 's3')".format(settings.storage_backend)
            )
    return _storage


def reset_storage() -> None:
    """Test hook — drops the cached backend."""
    global _storage
    _storage = None


__all__ = ["ObjectStorage", "get_storage", "reset_storage"]
