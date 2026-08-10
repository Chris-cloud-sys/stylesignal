"""Deterministic rule signals — spec §4.7.

Three families, all computed from what the pipeline actually extracted:

* **colour harmony** from the LAB palette (§4.5 → :mod:`colour`)
* **formality coherence** from the spread of per-garment formality estimates
* **proportion / pairing flags** from the garment bounding boxes

These are internal signals. §7.3 forbids surfacing numbers to the user — they
feed the VLM prompt (§7.5) and the templated fallback (§7.6) as *evidence*, so
every sentence of feedback can be traced to something measured.
"""
from typing import Any, Dict, List, Sequence

from .colour import classify_harmony, describe_contrast

# Formality spread above which the pieces stop agreeing with each other.
FORMALITY_MIXED_THRESHOLD = 0.25
FORMALITY_SPLIT_THRESHOLD = 0.45

UPPER_CATEGORIES = ("top", "outerwear", "dress")
LOWER_CATEGORIES = ("bottom", "dress")


def build_signals(
    garments: Sequence[Dict[str, Any]],
    outfit_palette: Sequence[Dict[str, Any]],
    occasion: str = None,
) -> Dict[str, Any]:
    """Assemble the full internal signal bundle for one outfit."""
    harmony = classify_harmony(outfit_palette)
    formality = _formality_signals(garments)
    proportion = _proportion_flags(garments)

    return {
        "colour": dict(
            harmony,
            contrast_band=describe_contrast(
                float(harmony.get("max_lightness_contrast", 0.0))
            ),
            palette=[
                {"hex": c.get("hex"), "weight": c.get("weight")}
                for c in outfit_palette
            ],
        ),
        "formality": formality,
        "proportion": proportion,
        "occasion": occasion,
        "garment_count": len(garments),
    }


# --- Formality coherence ---------------------------------------------------
def _formality_signals(garments: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    values = [
        _clamp01(float(g.get("formality", 0.5) or 0.0))
        for g in garments
        if g.get("formality") is not None
    ]
    if not values:
        return {
            "mean": None,
            "spread": None,
            "coherence": "unknown",
            "outlier_category": None,
            "outlier_direction": None,
        }

    mean = sum(values) / len(values)
    spread = max(values) - min(values)

    if spread < FORMALITY_MIXED_THRESHOLD:
        coherence = "consistent"
    elif spread < FORMALITY_SPLIT_THRESHOLD:
        coherence = "mixed"
    else:
        coherence = "split"

    outlier_category = None
    outlier_direction = None
    if coherence != "consistent" and len(values) > 1:
        scored = [
            (abs(_clamp01(float(g.get("formality", 0.5) or 0.0)) - mean), g)
            for g in garments
            if g.get("formality") is not None
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        worst = scored[0][1]
        outlier_category = worst.get("category")
        outlier_direction = (
            "more casual"
            if _clamp01(float(worst.get("formality", 0.5) or 0.0)) < mean
            else "more formal"
        )

    return {
        "mean": round(mean, 3),
        "spread": round(spread, 3),
        "coherence": coherence,
        "outlier_category": outlier_category,
        "outlier_direction": outlier_direction,
    }


# --- Proportion / pairing --------------------------------------------------
def _proportion_flags(garments: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Geometry read off the normalised bounding boxes (§5.4).

    Deliberately conservative: a flag is only raised when the boxes clearly
    support it, because §7.4 requires every observation to be defensible.
    """
    flags: List[str] = []
    by_category: Dict[str, Dict[str, Any]] = {}
    for garment in garments:
        category = str(garment.get("category") or "")
        bbox = garment.get("bbox") or {}
        if not bbox:
            continue
        # Keep the largest box per category.
        area = float(bbox.get("w", 0.0) or 0.0) * float(bbox.get("h", 0.0) or 0.0)
        existing = by_category.get(category)
        if existing is None or area > existing["_area"]:
            by_category[category] = dict(bbox, _area=area)

    top = by_category.get("top")
    bottom = by_category.get("bottom")
    outerwear = by_category.get("outerwear")

    waistline = None
    if top:
        waistline = _bottom_edge(top)
        if waistline < 0.45:
            flags.append("cropped_upper_raises_waistline")
        elif waistline > 0.62:
            flags.append("long_upper_lowers_waistline")

    if outerwear and bottom:
        outer_bottom = _bottom_edge(outerwear)
        bottom_mid = float(bottom.get("y", 0.0)) + float(bottom.get("h", 0.0)) / 2.0
        if outer_bottom > bottom_mid:
            flags.append("long_outerwear_over_lower_half")

    if outerwear and top:
        if _bottom_edge(outerwear) - _bottom_edge(top) > 0.18:
            flags.append("layered_length_contrast")

    if bottom and float(bottom.get("w", 1.0) or 1.0) < 0.22:
        flags.append("narrow_lower_silhouette")

    volume_ratio = None
    if top and bottom:
        top_w = float(top.get("w", 0.0) or 0.0)
        bottom_w = float(bottom.get("w", 0.0) or 0.0)
        if bottom_w > 0.01:
            volume_ratio = round(top_w / bottom_w, 2)
            if volume_ratio > 1.35:
                flags.append("volume_concentrated_upper")
            elif volume_ratio < 0.72:
                flags.append("volume_concentrated_lower")

    return {
        "flags": flags,
        "waistline_y": round(waistline, 3) if waistline is not None else None,
        "upper_to_lower_width_ratio": volume_ratio,
        "categories_present": sorted(by_category.keys()),
    }


def _bottom_edge(bbox: Dict[str, Any]) -> float:
    return float(bbox.get("y", 0.0) or 0.0) + float(bbox.get("h", 0.0) or 0.0)


def _clamp01(value: float) -> float:
    if value != value:  # NaN
        return 0.5
    return max(0.0, min(1.0, value))
