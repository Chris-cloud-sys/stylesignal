"""Wardrobe catalog — SPEC+, see docs/spec-deviations.md and models.py's
WardrobeItem docstring for why this exists and why it's scoped to
item-mode scans specifically.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import bad_request, not_found
from ..models import Garment, Outfit, User, WardrobeItem
from ..schemas import WardrobeAddRequest, WardrobeItemOut, WardrobeListResponse
from ..storage import get_storage

router = APIRouter(tags=["wardrobe"])


def _owned_outfit(db: Session, outfit_id: uuid.UUID, user: User) -> Outfit:
    outfit = db.get(Outfit, outfit_id)
    if outfit is None or outfit.deleted_at is not None or outfit.user_id != user.id:
        raise not_found("Outfit")
    return outfit


def _bbox_area(bbox: dict) -> float:
    return float(bbox.get("w", 0.0) or 0.0) * float(bbox.get("h", 0.0) or 0.0)


def _to_out(db: Session, item: WardrobeItem) -> WardrobeItemOut:
    storage = get_storage()
    outfit = db.get(Outfit, item.outfit_id)
    thumb_url = None
    if outfit is not None and outfit.image_sha256:
        thumb_url = storage.signed_url(outfit.thumb_key)
    return WardrobeItemOut(
        item_id=item.id,
        outfit_id=item.outfit_id,
        category=item.category,
        colors=item.colors or [],
        pattern=item.pattern,
        formality=item.formality,
        note=item.note,
        thumb_url=thumb_url,
        created_at=item.created_at,
    )


@router.post(
    "/v1/outfits/{outfit_id}/wardrobe",
    response_model=WardrobeItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an item-mode scan to the wardrobe catalog",
)
def add_to_wardrobe(
    outfit_id: uuid.UUID,
    payload: WardrobeAddRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WardrobeItemOut:
    outfit = _owned_outfit(db, outfit_id, user)
    if outfit.status != "complete":
        raise bad_request(
            "outfit_not_complete", "This scan has not finished reading yet."
        )
    if outfit.capture_mode != "item":
        raise bad_request(
            "not_item_mode",
            "Only an 'item, not worn' scan can be added to the wardrobe — a "
            "worn outfit photo does not decompose into a single piece.",
        )

    existing = db.execute(
        select(WardrobeItem).where(WardrobeItem.outfit_id == outfit_id)
    ).scalar_one_or_none()
    if existing is not None:
        return _to_out(db, existing)

    garments = list(
        db.execute(select(Garment).where(Garment.outfit_id == outfit_id)).scalars()
    )
    if not garments:
        raise bad_request(
            "no_garment_detected", "No garment was detected in this scan."
        )
    # Item mode is meant to produce exactly one garment; if more than one
    # was detected anyway, snapshot the most prominent one rather than
    # guessing which the caller meant.
    primary = max(garments, key=lambda g: _bbox_area(g.bbox))

    item = WardrobeItem(
        user_id=user.id,
        outfit_id=outfit_id,
        category=primary.category,
        colors=primary.colors,
        pattern=primary.pattern,
        formality=primary.formality,
        note=payload.note,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_out(db, item)


@router.get(
    "/v1/wardrobe",
    response_model=WardrobeListResponse,
    summary="The caller's wardrobe catalog",
)
def list_wardrobe(
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WardrobeListResponse:
    offset = _decode_offset(cursor)
    rows = list(
        db.execute(
            select(WardrobeItem)
            .where(WardrobeItem.user_id == user.id)
            .order_by(WardrobeItem.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).scalars()
    )
    items = [_to_out(db, item) for item in rows]
    next_cursor = str(offset + len(items)) if len(items) == limit else None
    return WardrobeListResponse(items=items, cursor=next_cursor)


@router.delete(
    "/v1/wardrobe/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an item from the wardrobe catalog",
)
def remove_from_wardrobe(
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    item = db.execute(
        select(WardrobeItem).where(
            WardrobeItem.id == item_id, WardrobeItem.user_id == user.id
        )
    ).scalar_one_or_none()
    if item is not None:
        db.delete(item)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _decode_offset(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except (TypeError, ValueError):
        raise bad_request("invalid_cursor", "The pagination cursor is not valid.")
    return max(0, offset)
