"""Community feed and ratings — spec §6.5, §4.8.

The schema is live in v1 (§5.6) but §9 explicitly defers these *endpoints* to
v2, so they ship complete and switched off. Set
``STYLESIGNAL_COMMUNITY_ENABLED=true`` to activate them — which also activates
the §1 earn-by-rating hook on the free tier.
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..errors import APIError, bad_request, not_found
from ..models import Favorite, Like, Outfit, Rating, User
from ..quota import credit_rating, quota_out
from ..schemas import (
    FavoriteResponse,
    FeedItem,
    FeedResponse,
    LikeResponse,
    RatingRequest,
    RatingResponse,
)
from ..storage import get_storage

router = APIRouter(tags=["community"])

settings = get_settings()


def _require_community_enabled() -> None:
    if not settings.community_enabled:
        raise APIError(
            status.HTTP_403_FORBIDDEN,
            "feature_disabled",
            "The community rating loop is a v2 feature and is not enabled on "
            "this deployment.",
            {"enable_with": "STYLESIGNAL_COMMUNITY_ENABLED=true"},
        )


@router.get(
    "/v1/feed",
    response_model=FeedResponse,
    summary="Outfits eligible for rating (§6.5)",
)
def get_feed(
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FeedResponse:
    _require_community_enabled()

    # §4.8 asks for active-learning selection: prioritise the outfits the
    # preference model is least confident about. The preference model does not
    # exist until v2, so v1 uses its structural stand-in — fewest ratings
    # first, which is where any model would be least confident. Swap the
    # ordering key for model uncertainty when §9 step 5 lands.
    already_rated = select(Rating.outfit_id).where(Rating.rater_id == user.id)
    rating_count = func.count(Rating.id)
    # Correlated scalar subqueries rather than a second outerjoin — joining
    # both Rating and Like to Outfit in one statement would fan out rows
    # (an outfit with 3 ratings x 2 likes becomes 6 rows before GROUP BY),
    # inflating both counts. Each subquery is independently correct and
    # still functionally depends on Outfit.id, which is the GROUP BY key.
    like_count_subq = (
        select(func.count(Like.id))
        .where(Like.outfit_id == Outfit.id)
        .scalar_subquery()
    )
    liked_by_me_subq = (
        select(func.count(Like.id))
        .where(Like.outfit_id == Outfit.id, Like.liker_id == user.id)
        .scalar_subquery()
    )
    favorited_by_me_subq = (
        select(func.count(Favorite.id))
        .where(Favorite.outfit_id == Outfit.id, Favorite.user_id == user.id)
        .scalar_subquery()
    )

    statement = (
        select(
            Outfit,
            rating_count.label("rating_count"),
            like_count_subq.label("like_count"),
            liked_by_me_subq.label("liked_by_me"),
            favorited_by_me_subq.label("favorited_by_me"),
        )
        .outerjoin(Rating, Rating.outfit_id == Outfit.id)
        .where(
            Outfit.is_public.is_(True),
            Outfit.status == "complete",
            Outfit.deleted_at.is_(None),
            Outfit.user_id != user.id,
            Outfit.id.not_in(already_rated),
        )
        .group_by(Outfit.id)
        .order_by(rating_count.asc(), Outfit.created_at.desc())
        .limit(limit)
    )
    if cursor:
        statement = statement.offset(_decode_offset(cursor))

    storage = get_storage()
    rows = list(db.execute(statement))
    items: List[FeedItem] = [
        FeedItem(
            outfit_id=outfit.id,
            thumb_url=storage.signed_url(outfit.thumb_key)
            if outfit.image_sha256
            else None,
            occasion=outfit.occasion,
            like_count=like_count,
            liked_by_me=bool(liked_by_me),
            favorited_by_me=bool(favorited_by_me),
        )
        for outfit, _rating_count, like_count, liked_by_me, favorited_by_me in rows
    ]

    offset = _decode_offset(cursor) + len(items)
    next_cursor = str(offset) if len(items) == limit else None
    return FeedResponse(items=items, cursor=next_cursor)


@router.post(
    "/v1/outfits/{outfit_id}/ratings",
    response_model=RatingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Rate a community outfit (§6.5)",
)
def rate_outfit(
    outfit_id: uuid.UUID,
    payload: RatingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RatingResponse:
    _require_community_enabled()
    ratelimit.check("rate:{0}".format(user.id), limit=120, window_seconds=3600)

    try:
        dimension = payload.validated_dimension()
    except ValueError as exc:
        raise bad_request("invalid_dimension", str(exc))

    outfit = db.get(Outfit, outfit_id)
    if (
        outfit is None
        or outfit.deleted_at is not None
        or not outfit.is_public
        or outfit.status != "complete"
    ):
        raise not_found("Outfit")

    if outfit.user_id == user.id:
        raise bad_request(
            "cannot_rate_own_outfit", "You cannot rate your own outfit."
        )

    existing = db.execute(
        select(Rating).where(
            Rating.outfit_id == outfit_id,
            Rating.rater_id == user.id,
            Rating.dimension == dimension,
        )
    ).scalar_one_or_none()

    if existing is not None:
        # §6.5: "repeat = update". An update is not new signal, so it earns
        # nothing — otherwise the earn loop is trivially farmable.
        existing.value = payload.value
        db.commit()
        earned = 0
    else:
        db.add(
            Rating(
                outfit_id=outfit_id,
                rater_id=user.id,
                dimension=dimension,
                value=payload.value,
            )
        )
        db.commit()
        earned = credit_rating(db, user)

    return RatingResponse(
        outfit_id=outfit_id,
        dimension=dimension,
        value=payload.value,
        scans_earned=earned,
        quota=quota_out(user),
    )


@router.post(
    "/v1/outfits/{outfit_id}/likes",
    response_model=LikeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Like a community outfit (SPEC+ — no dislike counterpart)",
)
def like_outfit(
    outfit_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LikeResponse:
    _require_community_enabled()
    ratelimit.check("like:{0}".format(user.id), limit=120, window_seconds=3600)

    outfit = _likeable_outfit(db, outfit_id, user)

    existing = db.execute(
        select(Like).where(Like.outfit_id == outfit_id, Like.liker_id == user.id)
    ).scalar_one_or_none()
    if existing is None:
        db.add(Like(outfit_id=outfit_id, liker_id=user.id))
        db.commit()

    return LikeResponse(
        outfit_id=outfit_id, liked=True, like_count=_like_count(db, outfit.id)
    )


@router.delete(
    "/v1/outfits/{outfit_id}/likes",
    response_model=LikeResponse,
    summary="Unlike a community outfit",
)
def unlike_outfit(
    outfit_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LikeResponse:
    _require_community_enabled()

    outfit = _likeable_outfit(db, outfit_id, user)

    existing = db.execute(
        select(Like).where(Like.outfit_id == outfit_id, Like.liker_id == user.id)
    ).scalar_one_or_none()
    if existing is not None:
        db.delete(existing)
        db.commit()

    return LikeResponse(
        outfit_id=outfit_id, liked=False, like_count=_like_count(db, outfit.id)
    )


def _likeable_outfit(db: Session, outfit_id: uuid.UUID, user: User) -> Outfit:
    outfit = db.get(Outfit, outfit_id)
    if (
        outfit is None
        or outfit.deleted_at is not None
        or not outfit.is_public
        or outfit.status != "complete"
    ):
        raise not_found("Outfit")
    if outfit.user_id == user.id:
        raise bad_request(
            "cannot_like_own_outfit", "You cannot like your own outfit."
        )
    return outfit


def _like_count(db: Session, outfit_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count(Like.id)).where(Like.outfit_id == outfit_id)
    ).scalar_one()


def _decode_offset(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except (TypeError, ValueError):
        raise bad_request("invalid_cursor", "The pagination cursor is not valid.")
    return max(0, offset)
