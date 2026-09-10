"""Personal signal history — SPEC+, see docs/spec-deviations.md.

The unexplored-opportunity answer to "no wardrobe catalog": every scan
already produces structured signal (palette, formality, the two §7.7
meters) that gets persisted once and never looked at again. This reads it
back and aggregates it across a caller's own recent scans — pattern
insight from what has already been read, not a new inventory of what the
caller owns. No new columns, no new per-garment tracking.
"""
from collections import Counter
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Outfit, OutfitFeedback, User
from .schemas import ColourInsight, InsightsOut

# Below this many scans, any "you tend to..." claim is overfit to one or two
# photos — show a plain scan count instead of manufacturing a pattern.
MIN_SCANS_FOR_INSIGHTS = 5
# "Recent style", not "all-time style" — caps the query and keeps the read
# current rather than dominated by scans from months ago.
RECENT_SCAN_WINDOW = 50

# Mirrors fallback.py's _LEVEL_PHRASES (kept separate rather than imported —
# that one is prose for a single scan's verdict; this is a coarser label for
# an aggregate mean, and the two are allowed to diverge without either
# breaking).
_FORMALITY_LABELS: Tuple[Tuple[float, str], ...] = (
    (0.25, "relaxed and casual"),
    (0.45, "everyday casual"),
    (0.65, "smart-casual"),
    (0.85, "polished and dressed-up"),
    (1.01, "formal"),
)


def _formality_label(mean: float) -> str:
    for ceiling, label in _FORMALITY_LABELS:
        if mean < ceiling:
            return label
    return _FORMALITY_LABELS[-1][1]


def compute_insights(db: Session, user: User) -> InsightsOut:
    rows: Sequence[Tuple[Outfit, OutfitFeedback]] = db.execute(
        select(Outfit, OutfitFeedback)
        .join(OutfitFeedback, OutfitFeedback.outfit_id == Outfit.id)
        .where(
            Outfit.user_id == user.id,
            Outfit.status == "complete",
            Outfit.deleted_at.is_(None),
        )
        .order_by(Outfit.created_at.desc())
        .limit(RECENT_SCAN_WINDOW)
    ).all()

    scan_count = len(rows)
    if scan_count < MIN_SCANS_FOR_INSIGHTS:
        return InsightsOut(
            ready=False, scan_count=scan_count, minimum_scans=MIN_SCANS_FOR_INSIGHTS
        )

    formality_values: List[float] = []
    colour_counts: Counter = Counter()
    occasion_match_levels: List[str] = []
    signal_clarity_levels: List[str] = []
    occasion_counts: Counter = Counter()
    worn_count = 0
    item_count = 0

    for outfit, feedback in rows:
        signals = feedback.signals or {}

        formality_mean = (signals.get("formality") or {}).get("mean")
        if formality_mean is not None:
            formality_values.append(float(formality_mean))

        palette = (signals.get("colour") or {}).get("palette") or []
        if palette:
            dominant = max(palette, key=lambda c: c.get("weight") or 0)
            hex_value = dominant.get("hex")
            if hex_value:
                colour_counts[hex_value] += 1

        occasion_match = feedback.occasion_match or {}
        if occasion_match.get("level"):
            occasion_match_levels.append(occasion_match["level"])

        signal_clarity = feedback.signal_clarity or {}
        if signal_clarity.get("level"):
            signal_clarity_levels.append(signal_clarity["level"])

        if outfit.occasion:
            occasion_counts[outfit.occasion] += 1

        if outfit.capture_mode == "item":
            item_count += 1
        else:
            worn_count += 1

    average_formality_label: Optional[str] = None
    if formality_values:
        average_formality_label = _formality_label(
            sum(formality_values) / len(formality_values)
        )

    top_colours = [
        ColourInsight(hex=hex_value, scan_count=count)
        for hex_value, count in colour_counts.most_common(5)
    ]

    occasion_match_strong_rate = (
        occasion_match_levels.count("strong") / len(occasion_match_levels)
        if occasion_match_levels
        else None
    )
    signal_clarity_strong_rate = (
        signal_clarity_levels.count("strong") / len(signal_clarity_levels)
        if signal_clarity_levels
        else None
    )
    most_common_occasion = (
        occasion_counts.most_common(1)[0][0] if occasion_counts else None
    )

    return InsightsOut(
        ready=True,
        scan_count=scan_count,
        minimum_scans=MIN_SCANS_FOR_INSIGHTS,
        average_formality_label=average_formality_label,
        top_colours=top_colours,
        occasion_match_strong_rate=occasion_match_strong_rate,
        signal_clarity_strong_rate=signal_clarity_strong_rate,
        most_common_occasion=most_common_occasion,
        worn_count=worn_count,
        item_count=item_count,
    )
