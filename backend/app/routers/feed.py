"""Community feed and ratings — spec §6.5, §4.8.

The schema is live in v1 (§5.6) but §9 explicitly defers these *endpoints* to
v2, so they ship complete and switched off. Set
``STYLESIGNAL_COMMUNITY_ENABLED=true`` to activate them — which also activates
the §1 earn-by-rating hook on the free tier.
"""
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..errors import APIError, bad_request, not_found
from ..models import (
    COMMENT_BODY_MAX_LENGTH,
    Comment,
    CommentLike,
    Favorite,
    Follow,
    Like,
    Outfit,
    Rating,
    User,
)
from ..quota import credit_rating, quota_out
from ..schemas import (
    CommentCreateRequest,
    CommentLikeResponse,
    CommentListResponse,
    CommentOut,
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
    comment_count_subq = (
        select(func.count(Comment.id))
        .where(Comment.outfit_id == Outfit.id)
        .scalar_subquery()
    )
    following_owner_subq = (
        select(func.count(Follow.id))
        .where(Follow.follower_id == user.id, Follow.followee_id == Outfit.user_id)
        .scalar_subquery()
    )

    statement = (
        select(
            Outfit,
            rating_count.label("rating_count"),
            like_count_subq.label("like_count"),
            liked_by_me_subq.label("liked_by_me"),
            favorited_by_me_subq.label("favorited_by_me"),
            comment_count_subq.label("comment_count"),
            following_owner_subq.label("following_owner"),
            User.display_name.label("owner_display_name"),
            User.email.label("owner_email"),
            User.avatar_key.label("owner_avatar_key"),
        )
        .outerjoin(Rating, Rating.outfit_id == Outfit.id)
        # Owner is 1:1 with Outfit — unlike Rating/Like above, this join
        # cannot fan out rows before the GROUP BY.
        .join(User, User.id == Outfit.user_id)
        .where(
            Outfit.is_public.is_(True),
            Outfit.status == "complete",
            Outfit.deleted_at.is_(None),
            Outfit.user_id != user.id,
            Outfit.id.not_in(already_rated),
        )
        .group_by(Outfit.id, User.id)
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
            comment_count=comment_count,
            following_owner=bool(following_owner),
            owner_id=outfit.user_id,
            owner_display_name=(owner_display_name or "").strip() or owner_email.split("@")[0],
            owner_avatar_url=storage.signed_url(owner_avatar_key) if owner_avatar_key else None,
        )
        for (
            outfit, _rating_count, like_count, liked_by_me, favorited_by_me,
            comment_count, following_owner, owner_display_name, owner_email, owner_avatar_key,
        ) in rows
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


# --- Comments (SPEC+ — see docs/spec-deviations.md) -------------------------
# No delete — deliberately left out (not merely hidden client-side). Threads
# are one level deep (top-level comments + their replies), matching how
# TikTok actually renders nested replies: flattened one level, not infinite.
def _comment_out(
    comment: Comment,
    display_name: Optional[str],
    email: str,
    avatar_key: Optional[str],
    user: User,
    like_count: int,
    liked_by_me: int,
    reply_count: int = 0,
) -> CommentOut:
    return CommentOut(
        comment_id=comment.id,
        author_id=comment.author_id,
        author_display_name=(display_name or "").strip() or email.split("@")[0],
        author_avatar_url=get_storage().signed_url(avatar_key) if avatar_key else None,
        body=comment.body,
        created_at=comment.created_at,
        is_mine=comment.author_id == user.id,
        like_count=like_count,
        liked_by_me=bool(liked_by_me),
        reply_count=reply_count,
    )


@router.get(
    "/v1/outfits/{outfit_id}/comments",
    response_model=CommentListResponse,
    summary="Top-level comments on a shared outfit",
)
def list_comments(
    outfit_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CommentListResponse:
    _require_community_enabled()
    _commentable_outfit(db, outfit_id, user)

    like_count_subq = (
        select(func.count(CommentLike.id))
        .where(CommentLike.comment_id == Comment.id)
        .scalar_subquery()
    )
    liked_by_me_subq = (
        select(func.count(CommentLike.id))
        .where(CommentLike.comment_id == Comment.id, CommentLike.user_id == user.id)
        .scalar_subquery()
    )

    statement = (
        select(
            Comment,
            User.display_name,
            User.email,
            User.avatar_key,
            like_count_subq.label("like_count"),
            liked_by_me_subq.label("liked_by_me"),
        )
        .join(User, User.id == Comment.author_id)
        .where(Comment.outfit_id == outfit_id, Comment.parent_id.is_(None))
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .offset(_decode_offset(cursor))
        .limit(limit)
    )
    rows = list(db.execute(statement))

    reply_counts = _reply_counts(db, [comment.id for comment, *_ in rows])
    items = [
        _comment_out(
            comment, display_name, email, avatar_key, user, like_count, liked_by_me,
            reply_count=reply_counts.get(comment.id, 0),
        )
        for comment, display_name, email, avatar_key, like_count, liked_by_me in rows
    ]

    total_count = db.execute(
        select(func.count(Comment.id)).where(Comment.outfit_id == outfit_id)
    ).scalar_one()

    offset = _decode_offset(cursor) + len(items)
    next_cursor = str(offset) if len(items) == limit else None
    return CommentListResponse(items=items, cursor=next_cursor, total_count=total_count)


@router.get(
    "/v1/outfits/{outfit_id}/comments/{comment_id}/replies",
    response_model=CommentListResponse,
    summary="Replies to one top-level comment",
)
def list_replies(
    outfit_id: uuid.UUID,
    comment_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CommentListResponse:
    _require_community_enabled()
    _commentable_outfit(db, outfit_id, user)

    like_count_subq = (
        select(func.count(CommentLike.id))
        .where(CommentLike.comment_id == Comment.id)
        .scalar_subquery()
    )
    liked_by_me_subq = (
        select(func.count(CommentLike.id))
        .where(CommentLike.comment_id == Comment.id, CommentLike.user_id == user.id)
        .scalar_subquery()
    )

    statement = (
        select(
            Comment, User.display_name, User.email, User.avatar_key,
            like_count_subq, liked_by_me_subq,
        )
        .join(User, User.id == Comment.author_id)
        .where(Comment.outfit_id == outfit_id, Comment.parent_id == comment_id)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .offset(_decode_offset(cursor))
        .limit(limit)
    )
    rows = list(db.execute(statement))
    items = [
        _comment_out(comment, display_name, email, avatar_key, user, like_count, liked_by_me)
        for comment, display_name, email, avatar_key, like_count, liked_by_me in rows
    ]

    offset = _decode_offset(cursor) + len(items)
    next_cursor = str(offset) if len(items) == limit else None
    return CommentListResponse(items=items, cursor=next_cursor)


@router.post(
    "/v1/outfits/{outfit_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment or a reply to a shared outfit",
)
def add_comment(
    outfit_id: uuid.UUID,
    payload: CommentCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CommentOut:
    _require_community_enabled()
    ratelimit.check("comment:{0}".format(user.id), limit=60, window_seconds=3600)
    _commentable_outfit(db, outfit_id, user)

    body = payload.body.strip()
    if not body:
        raise bad_request("empty_comment", "A comment cannot be empty.")

    if payload.parent_id is not None:
        parent = db.get(Comment, payload.parent_id)
        if (
            parent is None
            or parent.outfit_id != outfit_id
            or parent.parent_id is not None
        ):
            raise bad_request(
                "invalid_parent_comment",
                "Replies can only be added to a top-level comment on this outfit.",
            )

    comment = Comment(
        outfit_id=outfit_id,
        author_id=user.id,
        parent_id=payload.parent_id,
        body=body[:COMMENT_BODY_MAX_LENGTH],
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    display_name = (user.display_name or "").strip() or user.email.split("@")[0]
    return CommentOut(
        comment_id=comment.id,
        author_id=user.id,
        author_display_name=display_name,
        author_avatar_url=get_storage().signed_url(user.avatar_key) if user.avatar_key else None,
        body=comment.body,
        created_at=comment.created_at,
        is_mine=True,
    )


@router.post(
    "/v1/outfits/{outfit_id}/comments/{comment_id}/likes",
    response_model=CommentLikeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Like a comment",
)
def like_comment(
    outfit_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CommentLikeResponse:
    _require_community_enabled()
    comment = _commentable_comment(db, outfit_id, comment_id)

    existing = db.execute(
        select(CommentLike).where(
            CommentLike.comment_id == comment_id, CommentLike.user_id == user.id
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(CommentLike(comment_id=comment.id, user_id=user.id))
        db.commit()

    return CommentLikeResponse(
        comment_id=comment_id, liked=True, like_count=_comment_like_count(db, comment.id)
    )


@router.delete(
    "/v1/outfits/{outfit_id}/comments/{comment_id}/likes",
    response_model=CommentLikeResponse,
    summary="Unlike a comment",
)
def unlike_comment(
    outfit_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CommentLikeResponse:
    _require_community_enabled()
    comment = _commentable_comment(db, outfit_id, comment_id)

    existing = db.execute(
        select(CommentLike).where(
            CommentLike.comment_id == comment_id, CommentLike.user_id == user.id
        )
    ).scalar_one_or_none()
    if existing is not None:
        db.delete(existing)
        db.commit()

    return CommentLikeResponse(
        comment_id=comment_id, liked=False, like_count=_comment_like_count(db, comment.id)
    )


def _commentable_comment(db: Session, outfit_id: uuid.UUID, comment_id: uuid.UUID) -> Comment:
    comment = db.get(Comment, comment_id)
    if comment is None or comment.outfit_id != outfit_id:
        raise not_found("Comment")
    return comment


def _comment_like_count(db: Session, comment_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count(CommentLike.id)).where(CommentLike.comment_id == comment_id)
    ).scalar_one()


def _reply_counts(db: Session, comment_ids: List[uuid.UUID]) -> Dict[uuid.UUID, int]:
    if not comment_ids:
        return {}
    rows = db.execute(
        select(Comment.parent_id, func.count(Comment.id))
        .where(Comment.parent_id.in_(comment_ids))
        .group_by(Comment.parent_id)
    ).all()
    return {parent_id: count for parent_id, count in rows}


def _commentable_outfit(db: Session, outfit_id: uuid.UUID, user: User) -> Outfit:
    # Unlike _likeable_outfit: the owner CAN comment on their own outfit —
    # only the visibility rule (public, or your own) carries over.
    outfit = db.get(Outfit, outfit_id)
    if (
        outfit is None
        or outfit.deleted_at is not None
        or outfit.status != "complete"
        or (not outfit.is_public and outfit.user_id != user.id)
    ):
        raise not_found("Outfit")
    return outfit


def _decode_offset(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except (TypeError, ValueError):
        raise bad_request("invalid_cursor", "The pagination cursor is not valid.")
    return max(0, offset)
