"""Outfit routes — spec §6.1 to §6.4.

The gateway stays thin (§3): validate, store, enqueue, read. No inference here.
"""
import base64
import binascii
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..errors import APIError, bad_request, not_found
from ..jobs import get_queue
from ..models import Outfit, User
from ..quota import consume_scan, refund_scan
from ..schemas import (
    ColourOut,
    FeedbackOut,
    FullReadOut,
    GarmentNoteOut,
    GarmentOut,
    MeterOut,
    OutfitCreateResponse,
    OutfitDetail,
    OutfitListItem,
    OutfitListResponse,
    PresignedUploadResponse,
    QuickReadOut,
    valid_occasion,
)
from ..storage import get_storage

router = APIRouter(prefix="/v1/outfits", tags=["outfits"])

settings = get_settings()

ALLOWED_UPLOAD_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/heic",
    "image/heif",
    "image/webp",
}

UPLOAD_RATE_LIMIT = 20
UPLOAD_RATE_WINDOW = 3600


# --- §6.1 Flow A: direct multipart -----------------------------------------
@router.post(
    "",
    response_model=OutfitCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an outfit and upload its photo (§6.1 Flow A)",
)
def create_outfit(
    image: UploadFile = File(...),
    occasion: Optional[str] = Form(default=None),
    context_note: Optional[str] = Form(default=None),
    is_public: bool = Form(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OutfitCreateResponse:
    ratelimit.check(
        "upload:{0}".format(user.id), UPLOAD_RATE_LIMIT, UPLOAD_RATE_WINDOW
    )

    occasion_value = _parse_occasion(occasion)
    note_value = _parse_note(context_note)
    data = _read_upload(image)

    # Charge the scan before doing any work, so a burst of parallel uploads
    # cannot overrun the allowance (§8).
    consume_scan(db, user)

    outfit = Outfit(
        user_id=user.id,
        status="pending",
        occasion=occasion_value,
        context_note=note_value,
        is_public=is_public,
    )
    db.add(outfit)
    db.flush()
    outfit.original_key = "outfits/{0}/original.jpg".format(outfit.id)

    try:
        get_storage().put(outfit.original_key, data, image.content_type or "image/jpeg")
    except Exception:
        db.rollback()
        refund_scan(db, user)
        raise APIError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "storage_unavailable",
            "Could not store the image. Please try again.",
        )

    db.commit()
    db.refresh(outfit)

    get_queue().enqueue_outfit(outfit.id)
    return OutfitCreateResponse(outfit_id=outfit.id, status=outfit.status)


# --- §6.1 Flow B: presigned ------------------------------------------------
@router.post(
    "/presign",
    response_model=PresignedUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve an outfit and get a direct-upload URL (§6.1 Flow B)",
)
def presign_outfit(
    occasion: Optional[str] = Form(default=None),
    context_note: Optional[str] = Form(default=None),
    is_public: bool = Form(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PresignedUploadResponse:
    """§6.1 puts this on ``POST /v1/outfits``; that path is taken by Flow A, so
    the presign step lives here and both flows can coexist."""
    ratelimit.check(
        "upload:{0}".format(user.id), UPLOAD_RATE_LIMIT, UPLOAD_RATE_WINDOW
    )

    outfit = Outfit(
        user_id=user.id,
        status="pending",
        occasion=_parse_occasion(occasion),
        context_note=_parse_note(context_note),
        is_public=is_public,
    )
    db.add(outfit)
    db.flush()
    outfit.original_key = "outfits/{0}/original.jpg".format(outfit.id)
    db.commit()
    db.refresh(outfit)

    return PresignedUploadResponse(
        outfit_id=outfit.id,
        upload_url=get_storage().signed_url(outfit.original_key),
        storage_key=outfit.original_key,
        expires_in=settings.signed_url_ttl_seconds,
    )


@router.post(
    "/{outfit_id}/submit",
    response_model=OutfitCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue processing after a direct upload (§6.1 Flow B)",
)
def submit_outfit(
    outfit_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OutfitCreateResponse:
    outfit = _owned_outfit(db, outfit_id, user)

    if outfit.status not in ("pending", "failed"):
        # Already queued or done — idempotent no-op (§8).
        return OutfitCreateResponse(outfit_id=outfit.id, status=outfit.status)

    if not get_storage().exists(outfit.original_key):
        raise bad_request(
            "upload_missing",
            "No uploaded image found for this outfit. Complete the upload first.",
        )

    consume_scan(db, user)
    outfit.status = "pending"
    outfit.failure_reason = None
    db.commit()

    get_queue().enqueue_outfit(outfit.id)
    return OutfitCreateResponse(outfit_id=outfit.id, status=outfit.status)


# --- §6.3 history ----------------------------------------------------------
@router.get("", response_model=OutfitListResponse, summary="Caller's history (§6.3)")
def list_outfits(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OutfitListResponse:
    statement = (
        select(Outfit)
        .where(Outfit.user_id == user.id, Outfit.deleted_at.is_(None))
        .order_by(Outfit.created_at.desc(), Outfit.id.desc())
        .limit(limit + 1)
    )

    decoded = _decode_cursor(cursor)
    if decoded is not None:
        created_at, last_id = decoded
        statement = statement.where(
            (Outfit.created_at < created_at)
            | ((Outfit.created_at == created_at) & (Outfit.id < last_id))
        )

    rows = list(db.execute(statement).scalars())
    has_more = len(rows) > limit
    rows = rows[:limit]

    storage = get_storage()
    items = [
        OutfitListItem(
            outfit_id=row.id,
            status=row.status,
            thumb_url=_thumb_url(storage, row),
            occasion=row.occasion,
            created_at=row.created_at,
        )
        for row in rows
    ]

    next_cursor = (
        _encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    )
    return OutfitListResponse(items=items, cursor=next_cursor)


# --- §6.2 status + feedback ------------------------------------------------
@router.get(
    "/{outfit_id}",
    response_model=OutfitDetail,
    response_model_exclude_none=True,
    summary="Status and feedback for one outfit (§6.2)",
)
def get_outfit(
    outfit_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OutfitDetail:
    outfit = _owned_outfit(db, outfit_id, user)
    return build_outfit_detail(outfit)


# --- §6.4 delete -----------------------------------------------------------
@router.delete(
    "/{outfit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete an outfit and schedule object cleanup (§6.4)",
)
def delete_outfit(
    outfit_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    outfit = _owned_outfit(db, outfit_id, user)

    outfit.deleted_at = datetime.now(timezone.utc)
    outfit.is_public = False  # drops it from the community feed immediately
    db.commit()

    # §6.4 says "schedules S3 cleanup". With one small prefix per outfit this
    # is fast enough to do inline; move it to the queue if object counts grow.
    try:
        get_storage().delete_prefix(outfit.prefix)
    except Exception:  # pragma: no cover - cleanup must not fail the request
        pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Shared helpers --------------------------------------------------------
def build_outfit_detail(outfit: Outfit) -> OutfitDetail:
    """The §6.2 payload. Shape is stable from v1 through v2."""
    storage = get_storage()
    detail = OutfitDetail(
        outfit_id=outfit.id,
        status=outfit.status,
        occasion=outfit.occasion,
        context_note=outfit.context_note,
        is_public=outfit.is_public,
        thumb_url=_thumb_url(storage, outfit),
        created_at=outfit.created_at,
    )

    if outfit.status == "failed":
        detail.failure_reason = outfit.failure_reason
        return detail

    if outfit.status != "complete":
        return detail

    detail.completed_at = outfit.completed_at
    detail.garments = [
        GarmentOut(
            garment_id=garment.id,
            category=garment.category,
            colors=[
                ColourOut(
                    hex=str(colour.get("hex")),
                    weight=float(colour.get("weight", 0.0) or 0.0),
                )
                for colour in (garment.colors or [])
                if colour.get("hex")
            ],
            pattern=garment.pattern,
            formality=round(float(garment.formality), 2),
        )
        for garment in outfit.garments
    ]

    if outfit.feedback is not None:
        feedback = outfit.feedback
        palette = (feedback.signals or {}).get("colour", {}).get("palette") or []
        detail.feedback = FeedbackOut(
            verdict_phrase=feedback.verdict_phrase,
            verdict_subtitle=feedback.verdict_subtitle,
            occasion_match=(
                MeterOut(**feedback.occasion_match)
                if feedback.occasion_match
                else None
            ),
            signal_clarity=(
                MeterOut(**feedback.signal_clarity)
                if feedback.signal_clarity
                else None
            ),
            palette=[
                ColourOut(
                    hex=str(colour.get("hex")),
                    weight=float(colour.get("weight", 0.0) or 0.0),
                )
                for colour in palette
                if colour.get("hex")
            ],
            focal_point=feedback.focal_point,
            quick_reads=[
                QuickReadOut(
                    dimension=str(item.get("dimension") or ""),
                    text=str(item.get("text") or ""),
                )
                for item in (feedback.quick_reads or [])
                if item.get("text")
            ],
            full_read=FullReadOut(
                overall_read=feedback.overall_read,
                color_note=feedback.color_note,
                formality_note=feedback.formality_note,
                proportion_note=feedback.proportion_note,
                garment_notes=[
                    GarmentNoteOut(
                        garment_id=_maybe_uuid(note.get("garment_id")),
                        note=str(note.get("note") or ""),
                    )
                    for note in (feedback.garment_notes or [])
                    if note.get("note")
                ],
            ),
        )
    return detail


def _owned_outfit(db: Session, outfit_id: uuid.UUID, user: User) -> Outfit:
    outfit = db.get(Outfit, outfit_id)
    # A deleted or someone else's outfit is a 404, not a 403 — do not confirm
    # that an id exists to a caller who does not own it.
    if outfit is None or outfit.deleted_at is not None or outfit.user_id != user.id:
        raise not_found("Outfit")
    return outfit


def _thumb_url(storage, outfit: Outfit) -> Optional[str]:
    # image_sha256 is written in the same stage as the thumbnail, so it is a
    # free existence check — no per-row HEAD against object storage.
    if not outfit.image_sha256:
        return None
    return storage.signed_url(outfit.thumb_key)


def _read_upload(image: UploadFile) -> bytes:
    content_type = (image.content_type or "").lower().split(";")[0].strip()
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise bad_request(
            "unsupported_media_type",
            "Upload a JPEG, PNG, WebP or HEIC image.",
            {"received": content_type or "unknown"},
        )

    data = image.file.read(settings.max_upload_bytes + 1)
    if not data:
        raise bad_request("empty_upload", "The uploaded file was empty.")
    if len(data) > settings.max_upload_bytes:
        raise APIError(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "payload_too_large",
            "Images must be under {0} MB. The client downscales to "
            "{1}px on the long edge before upload.".format(
                settings.max_upload_bytes // 1_000_000, settings.max_longest_edge
            ),
        )
    return data


def _parse_occasion(value: Optional[str]) -> Optional[str]:
    try:
        return valid_occasion(value)
    except ValueError as exc:
        raise bad_request("invalid_occasion", str(exc))


def _parse_note(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    note = value.strip()
    if not note:
        return None
    if len(note) > 280:
        raise bad_request(
            "context_note_too_long", "context_note must be 280 characters or fewer."
        )
    return note


def _maybe_uuid(value: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _encode_cursor(created_at: datetime, outfit_id: uuid.UUID) -> str:
    raw = "{0}|{1}".format(created_at.isoformat(), outfit_id)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: Optional[str]) -> Optional[Tuple[datetime, uuid.UUID]]:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        timestamp, outfit_id = raw.split("|", 1)
        return datetime.fromisoformat(timestamp), uuid.UUID(outfit_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise bad_request("invalid_cursor", "The pagination cursor is not valid.")
