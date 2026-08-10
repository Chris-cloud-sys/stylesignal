"""Signed media route for the local storage backend.

In production the client fetches images straight from S3 via a presigned URL
and this route is never mounted. Locally there is no S3, so this serves the
same role: HMAC-signed, time-limited, and read-only.
"""
from fastapi import APIRouter, Query, Response, status

from ..config import get_settings
from ..errors import APIError, not_found
from ..security import verify_media_signature
from ..storage import get_storage

router = APIRouter(prefix="/v1/media", tags=["media"])

settings = get_settings()

_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@router.get("/{key:path}", summary="Fetch a stored object with a signed token")
def get_media(key: str, token: str = Query(...)) -> Response:
    if settings.storage_backend != "local":
        raise not_found("Media route")

    if not verify_media_signature(key, token):
        raise APIError(
            status.HTTP_403_FORBIDDEN,
            "invalid_signature",
            "This media link is invalid or has expired.",
        )

    try:
        data = get_storage().get(key)
    except (FileNotFoundError, ValueError):
        raise not_found("Object")

    suffix = key[key.rfind(".") :].lower() if "." in key else ""
    return Response(
        content=data,
        media_type=_CONTENT_TYPES.get(suffix, "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=300"},
    )
