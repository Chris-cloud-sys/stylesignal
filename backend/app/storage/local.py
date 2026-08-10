"""Filesystem-backed object storage for local development."""
import os
import shutil
from typing import Optional
from urllib.parse import quote

from ..config import get_settings
from ..security import sign_media_key
from . import ObjectStorage


class LocalStorage(ObjectStorage):
    def __init__(self, root: Optional[str] = None) -> None:
        settings = get_settings()
        self.root = os.path.abspath(root or settings.local_storage_dir)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key: str) -> str:
        # Keys are server-generated (§5.7), but never trust one blindly: a key
        # containing '..' must not escape the storage root.
        target = os.path.abspath(os.path.join(self.root, key))
        if target != self.root and not target.startswith(self.root + os.sep):
            raise ValueError("Storage key escapes root: {0!r}".format(key))
        return target

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)

    def get(self, key: str) -> bytes:
        with open(self._path(key), "rb") as handle:
            return handle.read()

    def exists(self, key: str) -> bool:
        return os.path.isfile(self._path(key))

    def delete_prefix(self, prefix: str) -> int:
        path = self._path(prefix.rstrip("/"))
        if os.path.isdir(path):
            count = sum(len(files) for _, _, files in os.walk(path))
            shutil.rmtree(path, ignore_errors=True)
            return count
        if os.path.isfile(path):
            os.remove(path)
            return 1
        return 0

    def signed_url(self, key: str, ttl_seconds: Optional[int] = None) -> str:
        token = sign_media_key(key, ttl_seconds)
        return "/v1/media/{0}?token={1}".format(quote(key), token)
