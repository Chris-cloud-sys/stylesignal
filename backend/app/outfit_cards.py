"""Batch lookups shared by every outfit-grid endpoint that now feeds a
Browse card — SPEC+ (docs/spec-deviations.md). Split out of routers/outfits.py
so routers/users.py can reuse the same queries without importing another
router module. Each function is one query for a whole page of outfits, not
N+1 per row — same shape as outfits.py's pre-existing `_like_counts`.
"""
import uuid
from typing import Dict, List, Optional, Set

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Comment, Favorite, Follow, Like, OutfitFeedback


def batch_comment_counts(db: Session, outfit_ids: List[uuid.UUID]) -> Dict[uuid.UUID, int]:
    if not outfit_ids:
        return {}
    rows = db.execute(
        select(Comment.outfit_id, func.count(Comment.id))
        .where(Comment.outfit_id.in_(outfit_ids))
        .group_by(Comment.outfit_id)
    ).all()
    return {outfit_id: count for outfit_id, count in rows}


def batch_verdict_phrases(db: Session, outfit_ids: List[uuid.UUID]) -> Dict[uuid.UUID, str]:
    if not outfit_ids:
        return {}
    rows = db.execute(
        select(OutfitFeedback.outfit_id, OutfitFeedback.verdict_phrase).where(
            OutfitFeedback.outfit_id.in_(outfit_ids)
        )
    ).all()
    return {outfit_id: phrase for outfit_id, phrase in rows if phrase}


def batch_favorited_by_me(
    db: Session, outfit_ids: List[uuid.UUID], user_id: uuid.UUID
) -> Set[uuid.UUID]:
    if not outfit_ids:
        return set()
    rows = db.execute(
        select(Favorite.outfit_id).where(
            Favorite.outfit_id.in_(outfit_ids), Favorite.user_id == user_id
        )
    ).all()
    return {outfit_id for (outfit_id,) in rows}


def batch_liked_by_me(
    db: Session, outfit_ids: List[uuid.UUID], user_id: uuid.UUID
) -> Set[uuid.UUID]:
    if not outfit_ids:
        return set()
    rows = db.execute(
        select(Like.outfit_id).where(
            Like.outfit_id.in_(outfit_ids), Like.liker_id == user_id
        )
    ).all()
    return {outfit_id for (outfit_id,) in rows}


def batch_following(
    db: Session, owner_ids: List[uuid.UUID], viewer_id: uuid.UUID
) -> Set[uuid.UUID]:
    """Which of `owner_ids` the viewer already follows. Callers still need
    to treat "owner is the viewer themself" separately — following_owner
    for your own outfits should read False (you can't follow yourself),
    which this correctly returns since a self-follow row is never created
    (see users.py's follow_user)."""
    if not owner_ids:
        return set()
    rows = db.execute(
        select(Follow.followee_id).where(
            Follow.followee_id.in_(owner_ids), Follow.follower_id == viewer_id
        )
    ).all()
    return {owner_id for (owner_id,) in rows}
