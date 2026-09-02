"""Scan quotas and the earn-by-rating loop — spec §1, §8.

Two things live here:

* **Free tier** — a hard monthly allowance (§1 said 5/month; raised to 10 per
  entry #13 of ``docs/spec-deviations.md``, then to 50 for the testing pass
  in entry #17) plus scans earned by rating other people's outfits. The earn
  loop is the free-tier engagement hook *and* the training-data source
  (§2.3), so it is quota logic, not a bolt-on.
* **Pro tier** — §1 is explicit that "unlimited" is a cost trap and must carry a
  *soft* fair-use ceiling with graceful degradation, "not an advertised hard
  limit". So Pro is never refused: past the ceiling the scan still runs, at
  reduced VLM effort. :func:`is_degraded` is what the pipeline reads. Since
  entry #18, Pro is a real native subscription (``app.billing`` verifies it
  with Apple/Google) that can lapse — :func:`effective_plan` is what
  everything below actually checks, never the raw ``user.plan`` column.

The monthly reset is lazy rather than a cron (§5.2): the counter carries the
period it belongs to, so a missed cron run cannot silently deny a user quota.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .config import get_settings
from .errors import quota_exceeded
from .models import User
from .schemas import QuotaOut

settings = get_settings()


def current_period(now: Optional[datetime] = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return "{0:04d}-{1:02d}".format(moment.year, moment.month)


def roll_period(db: Session, user: User) -> None:
    """Zero the counter if we have crossed into a new calendar month."""
    period = current_period()
    if user.scans_period != period:
        user.scans_period = period
        user.scans_used_this_month = 0
        db.commit()


def effective_plan(user: User) -> str:
    """The plan that actually governs quota right now.

    A native-IAP subscription (docs/spec-deviations.md #18) can lapse
    without anything telling the server — there's no cron here, same as
    the monthly counter above. ``pro_expires_at`` is the real source of
    truth, not the raw ``plan`` column: past its expiry, a user reverts to
    free the next time anything reads their quota, lazily, exactly like
    ``roll_period`` above. ``pro_expires_at is None`` means no expiry at
    all — an admin/test override, not a real subscription — so it stays
    Pro.
    """
    if user.plan == "pro" and (
        user.pro_expires_at is None or user.pro_expires_at > datetime.now(timezone.utc)
    ):
        return "pro"
    return "free"


def monthly_allowance(user: User) -> Optional[int]:
    """Hard allowance for the plan, or ``None`` when there is no hard cap."""
    if effective_plan(user) == "pro":
        return None  # soft ceiling only — see is_degraded()
    return settings.free_monthly_scans


def scans_remaining(user: User) -> Optional[int]:
    allowance = monthly_allowance(user)
    if allowance is None:
        return None
    return max(0, allowance + user.earned_scans - user.scans_used_this_month)


def is_degraded(user: User) -> bool:
    """Pro user past the quiet fair-use ceiling (§1)."""
    return (
        effective_plan(user) == "pro"
        and user.scans_used_this_month >= settings.pro_soft_monthly_cap
    )


def consume_scan(db: Session, user: User) -> None:
    """Charge one scan, or raise the §6 error envelope for a free user at zero."""
    roll_period(db, user)

    remaining = scans_remaining(user)
    if remaining is not None and remaining <= 0:
        raise quota_exceeded(
            "You have used all {0} scans in your free monthly allowance. "
            "Rate {1} community outfits to earn another scan, or upgrade to "
            "Pro.".format(
                settings.free_monthly_scans, settings.ratings_per_earned_scan
            ),
            {
                "plan": effective_plan(user),
                "monthly_allowance": monthly_allowance(user),
                "scans_used_this_month": user.scans_used_this_month,
                "earned_scans": user.earned_scans,
                "ratings_per_earned_scan": settings.ratings_per_earned_scan,
            },
        )

    user.scans_used_this_month += 1
    db.commit()


def refund_scan(db: Session, user: User) -> None:
    """Give the scan back when the upload never made it into the queue."""
    if user.scans_used_this_month > 0:
        user.scans_used_this_month -= 1
        db.commit()


def credit_rating(db: Session, user: User) -> int:
    """Record one rating toward the earn-by-rating loop. Returns scans earned."""
    roll_period(db, user)
    user.rating_credits += settings.scans_earned_per_rating

    earned = 0
    threshold = max(1, settings.ratings_per_earned_scan)
    while user.rating_credits >= threshold:
        user.rating_credits -= threshold
        user.earned_scans += 1
        earned += 1

    db.commit()
    return earned


def quota_out(user: User) -> QuotaOut:
    threshold = max(1, settings.ratings_per_earned_scan)
    return QuotaOut(
        plan=effective_plan(user),
        scans_used_this_month=user.scans_used_this_month,
        monthly_allowance=monthly_allowance(user),
        earned_scans=user.earned_scans,
        scans_remaining=scans_remaining(user),
        rating_credits=user.rating_credits,
        ratings_until_next_scan=threshold - (user.rating_credits % threshold),
        pro_expires_at=user.pro_expires_at if effective_plan(user) == "pro" else None,
    )
