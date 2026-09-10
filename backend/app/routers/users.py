"""Public profiles and the follow graph — SPEC+, see docs/spec-deviations.md.

Gives the community loop an identity beyond an anonymous rating/liking
queue: a specific member's public reads, discoverable and revisitable, not
just whatever the feed's ordering surfaces next.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import bad_request, not_found
from ..models import Follow, Outfit, User
from ..schemas import FollowResponse, OutfitListItem, UserProfileOut
from ..storage import get_storage

router = APIRouter(prefix="/v1/users", tags=["users"])


def _display_name(user: User) -> str:
    return user.display_name.strip() or user.email.split("@")[0]


def _follower_count(db: Session, user_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count(Follow.id)).where(Follow.followee_id == user_id)
    ).scalar_one()


@router.get("/{user_id}/profile", response_model=UserProfileOut)
def get_user_profile(
    user_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileOut:
    target = db.get(User, user_id)
    if target is None:
        raise not_found("User")

    following_count = db.execute(
        select(func.count(Follow.id)).where(Follow.follower_id == user_id)
    ).scalar_one()
    is_following = (
        db.execute(
            select(Follow.id).where(
                Follow.follower_id == user.id, Follow.followee_id == user_id
            )
        ).scalar_one_or_none()
        is not None
    )

    # A profile is always the *public* face of an account, even to its own
    # owner — private/in-progress scans stay in History, not here.
    base = (
        select(Outfit)
        .where(
            Outfit.user_id == user_id,
            Outfit.is_public.is_(True),
            Outfit.status == "complete",
            Outfit.deleted_at.is_(None),
        )
    )
    outfit_count = db.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    offset = _decode_offset(cursor)
    rows = list(
        db.execute(
            base.order_by(Outfit.created_at.desc()).offset(offset).limit(limit)
        ).scalars()
    )

    storage = get_storage()
    items = [
        OutfitListItem(
            outfit_id=outfit.id,
            status=outfit.status,
            thumb_url=storage.signed_url(outfit.thumb_key) if outfit.image_sha256 else None,
            occasion=outfit.occasion,
            created_at=outfit.created_at,
        )
        for outfit in rows
    ]
    next_cursor = str(offset + len(items)) if len(items) == limit else None

    return UserProfileOut(
        user_id=target.id,
        display_name=_display_name(target),
        follower_count=_follower_count(db, user_id),
        following_count=following_count,
        outfit_count=outfit_count,
        is_following=is_following,
        is_self=target.id == user.id,
        outfits=items,
        cursor=next_cursor,
    )


@router.post(
    "/{user_id}/follow",
    response_model=FollowResponse,
    status_code=status.HTTP_201_CREATED,
)
def follow_user(
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FollowResponse:
    if user_id == user.id:
        raise bad_request("cannot_follow_yourself", "You cannot follow your own account.")
    if db.get(User, user_id) is None:
        raise not_found("User")

    existing = db.execute(
        select(Follow).where(
            Follow.follower_id == user.id, Follow.followee_id == user_id
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(Follow(follower_id=user.id, followee_id=user_id))
        db.commit()

    return FollowResponse(
        user_id=user_id, following=True, follower_count=_follower_count(db, user_id)
    )


@router.delete("/{user_id}/follow", response_model=FollowResponse)
def unfollow_user(
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FollowResponse:
    existing = db.execute(
        select(Follow).where(
            Follow.follower_id == user.id, Follow.followee_id == user_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        db.delete(existing)
        db.commit()

    return FollowResponse(
        user_id=user_id, following=False, follower_count=_follower_count(db, user_id)
    )


def _decode_offset(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except (TypeError, ValueError):
        raise bad_request("invalid_cursor", "The pagination cursor is not valid.")
    return max(0, offset)
