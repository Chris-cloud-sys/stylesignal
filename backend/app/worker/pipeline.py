"""Pipeline orchestration — spec §3, §4.3-§4.7, §8.

One entry point, :func:`process_outfit`, wired to whichever queue backend is
configured. It is **idempotent** (§8): keyed on ``outfit_id``, it clears any
prior garments/feedback before writing, so a retry or a duplicate delivery can
never double-write.

Stage map (v1 collapses stages 2-4 into the single VLM call, per §9)::

    1  preprocess          §4.3   decode, EXIF strip, normalise, thumbnail
    -  image-hash cache    §8     reuse a prior identical scan, no VLM spend
    2  detect / segment    §4.4   VLM (v2: real segmenter)
    3  attribute extract   §4.5   VLM + pixel-measured LAB palette
    4  style embedding     §4.6   deferred to v2
    5  scoring + feedback  §4.7   rule signals + VLM prose + lint
"""
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    GARMENT_CATEGORIES,
    PATTERNS,
    Garment,
    Outfit,
    OutfitFeedback,
)
from ..quota import is_degraded
from ..storage import get_storage
from .colour import dominant_colours, garment_palette
from .fallback import build_fallback_feedback
from .preprocess import UndecodableImage, preprocess
from .rules import build_signals, compute_meters
from .vlm import VLMUnavailable, analyse_outfit

logger = logging.getLogger("stylesignal.worker.pipeline")

settings = get_settings()


def process_outfit(outfit_id: uuid.UUID) -> None:
    """Run the full pipeline for one outfit. Never raises."""
    started = time.monotonic()
    timings: Dict[str, float] = {}
    db: Session = SessionLocal()
    try:
        outfit = db.get(Outfit, outfit_id)
        if outfit is None:
            logger.warning("outfit %s vanished before processing", outfit_id)
            return
        if outfit.status == "complete":
            logger.info("outfit %s already complete; nothing to do", outfit_id)
            return
        if outfit.deleted_at is not None:
            logger.info("outfit %s was deleted before processing", outfit_id)
            return

        outfit.status = "processing"
        db.commit()

        _clear_previous_results(db, outfit)
        _run_stages(db, outfit, timings)

    except UndecodableImage as exc:
        logger.info("outfit %s undecodable: %s", outfit_id, exc)
        _fail(db, outfit_id, "undecodable")
    except _PipelineFailure as exc:
        logger.info("outfit %s failed: %s", outfit_id, exc.reason)
        _fail(db, outfit_id, exc.reason)
    except Exception:
        logger.exception("outfit %s hit an unhandled error", outfit_id)
        _fail(db, outfit_id, "internal_error")
    finally:
        timings["total"] = round(time.monotonic() - started, 3)
        logger.info(
            "pipeline finished for outfit %s",
            outfit_id,
            extra={"outfit_id": str(outfit_id), "timings": timings},
        )
        db.close()


class _PipelineFailure(Exception):
    """A typed, expected failure that maps to §5.3 ``failure_reason``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _run_stages(db: Session, outfit: Outfit, timings: Dict[str, float]) -> None:
    storage = get_storage()

    # --- Stage 1: preprocess (§4.3) --------------------------------------
    mark = time.monotonic()
    try:
        original = storage.get(outfit.original_key)
    except FileNotFoundError as exc:
        raise UndecodableImage("original object missing") from exc

    prepared = preprocess(original)
    storage.put(outfit.working_key, prepared.working_bytes, "image/jpeg")
    storage.put(outfit.thumb_key, prepared.thumb_bytes, "image/jpeg")
    outfit.image_sha256 = prepared.image_sha256
    db.commit()
    timings["preprocess"] = round(time.monotonic() - mark, 3)

    # --- Image-hash cache (§8) -------------------------------------------
    mark = time.monotonic()
    cached = _find_cached_result(db, outfit)
    if cached is not None:
        _clone_result(db, outfit, cached)
        timings["cache_hit"] = round(time.monotonic() - mark, 3)
        logger.info(
            "outfit %s served from image-hash cache (source=%s); no VLM spend",
            outfit.id,
            cached.id,
        )
        return

    # --- Measured palette, before detection (§4.5) ------------------------
    mark = time.monotonic()
    outfit_palette = dominant_colours(
        prepared.working_image, bbox=None, max_colours=5
    )
    timings["palette"] = round(time.monotonic() - mark, 3)

    # --- Stages 2-4 + feedback (§4.4-§4.7, §7.5) --------------------------
    mark = time.monotonic()
    analysis: Optional[Dict[str, Any]] = None
    vlm_meta: Dict[str, Any] = {"used": False}

    # §1: a Pro user past the quiet fair-use ceiling is never refused — the
    # scan runs at reduced effort with a smaller retry budget instead.
    degraded = is_degraded(outfit.user) if outfit.user is not None else False

    try:
        result = analyse_outfit(
            working_jpeg=prepared.working_bytes,
            measured_palette=outfit_palette,
            occasion=outfit.occasion,
            context_note=outfit.context_note,
            rule_signals=None,
            effort="low" if degraded else None,
            max_lint_retries=1 if degraded else None,
        )
        analysis = result.payload
        vlm_meta = {
            "used": True,
            "model": result.model,
            "degraded": degraded,
            "lint_attempts": result.lint_attempts,
            "lint_violations": result.lint_violations,
            "usage": result.usage,
        }
    except VLMUnavailable as exc:
        logger.warning(
            "VLM unavailable for outfit %s (%s); using templated fallback (§7.6)",
            outfit.id,
            exc,
        )
        vlm_meta = {"used": False, "reason": str(exc)}
    timings["vlm"] = round(time.monotonic() - mark, 3)

    detected = _normalise_garments(analysis)
    failure_reason = _detection_failure_reason(analysis, detected)
    if failure_reason is not None:
        raise _PipelineFailure(failure_reason)
    # When detection never ran (no VLM), we fall through with zero garments.
    # §7.6 requires the fallback to keep the product functional, and the
    # whole-image palette still supports a colour and contrast read.

    # --- Persist garments with pixel-measured colours (§4.5, §5.4) --------
    mark = time.monotonic()
    garment_rows = _persist_garments(db, outfit, detected, prepared.working_image)
    timings["garments"] = round(time.monotonic() - mark, 3)

    garment_dicts = [_garment_as_dict(row) for row in garment_rows]

    # --- Deterministic rule signals (§4.7) --------------------------------
    # §7.8: the displayed palette is garment colours only, not the whole
    # frame (walls/floor are meaningless to the user) — but with zero
    # garments there is nothing garment-level to show, so the whole-image
    # sample is what keeps the §7.6 fallback's colour read alive at all.
    display_palette = (
        garment_palette(garment_dicts, max_colours=5)
        if garment_dicts
        else outfit_palette
    )
    signals = build_signals(garment_dicts, display_palette, outfit.occasion)
    signals["vlm"] = vlm_meta
    signals["engine"] = settings.feedback_engine_version

    # --- §7.7 glanceable meters --------------------------------------------
    # Computed once here and persisted, not recomputed per read — see
    # rules.py's module docstring for why.
    meters = compute_meters(signals, outfit.occasion)
    signals["meters"] = meters

    # --- Feedback prose (§7) ----------------------------------------------
    if analysis is not None:
        prose = _prose_from_analysis(analysis, garment_rows)
    else:
        prose = build_fallback_feedback(
            signals, garment_dicts, outfit.occasion, meters.get("occasion_match")
        )
        signals["fallback_used"] = True

    _enforce_verdict_meter_agreement(prose, meters)

    db.add(
        OutfitFeedback(
            outfit_id=outfit.id,
            overall_read=prose["overall_read"],
            color_note=prose["color_note"],
            formality_note=prose["formality_note"],
            proportion_note=prose.get("proportion_note") or None,
            garment_notes=prose.get("garment_notes") or [],
            verdict_phrase=prose["verdict_phrase"],
            verdict_subtitle=prose["verdict_subtitle"],
            focal_point=prose.get("focal_point") or None,
            quick_reads=prose.get("quick_reads") or [],
            occasion_match=meters.get("occasion_match"),
            signal_clarity=meters.get("signal_clarity"),
            signals=signals,
            model_version=settings.feedback_engine_version,
        )
    )

    outfit.status = "complete"
    outfit.failure_reason = None
    outfit.completed_at = datetime.now(timezone.utc)
    db.commit()


# --- Detection normalisation ----------------------------------------------
def _normalise_garments(analysis: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clamp and sanity-check whatever the model returned.

    Structured outputs guarantee the *shape*; they do not guarantee that
    ``formality`` is inside 0-1 or that a bbox is on the canvas. Everything the
    model produces is treated as untrusted until clamped here.
    """
    if not analysis:
        return []

    cleaned: List[Dict[str, Any]] = []
    for index, raw in enumerate(analysis.get("garments") or []):
        if not isinstance(raw, dict):
            continue
        category = str(raw.get("category") or "").strip()
        if category not in GARMENT_CATEGORIES:
            continue

        pattern = str(raw.get("pattern") or "solid").strip()
        if pattern not in PATTERNS:
            pattern = "other"

        cleaned.append(
            {
                "index": int(raw.get("index", index) or index),
                "category": category,
                "bbox": _clamp_bbox(raw.get("bbox")),
                "pattern": pattern,
                "formality": _clamp01(raw.get("formality"), default=0.5),
                "attributes": {
                    "material_guess": str(raw.get("material_guess") or "unknown"),
                    "material_confidence": str(
                        raw.get("material_confidence") or "low"
                    ),
                    "colour_names": [
                        str(name) for name in (raw.get("colour_names") or [])
                    ][:4],
                    "descriptor": str(raw.get("descriptor") or ""),
                    "source": "vlm_v1",
                },
            }
        )
    return cleaned


def _detection_failure_reason(
    analysis: Optional[Dict[str, Any]], detected: List[Dict[str, Any]]
) -> Optional[str]:
    """§4.4: None if the scan should proceed, else the §5.3 failure reason.

    Checked in this order on purpose: a flat-lay or an empty room can still
    yield detected garments (the VLM correctly names the clothing it sees),
    but if no *person* is wearing them this is not an outfit read and must
    fail as ``no_person`` rather than generate feedback for nobody's outfit —
    exactly the case the photo brief's flat-lay/no-person set exists to catch.
    Only once a person is confirmed present does an empty ``detected`` list
    become ``no_garments_detected``.
    """
    if analysis is None:
        return None
    if not analysis.get("person_present"):
        return "no_person"
    if not detected:
        return "no_garments_detected"
    return None


def _clamp_bbox(raw: Any) -> Dict[str, float]:
    if not isinstance(raw, dict):
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    x = _clamp01(raw.get("x"), default=0.0)
    y = _clamp01(raw.get("y"), default=0.0)
    w = _clamp01(raw.get("w"), default=1.0)
    h = _clamp01(raw.get("h"), default=1.0)
    # Keep the box on the canvas.
    w = min(w, 1.0 - x)
    h = min(h, 1.0 - y)
    return {
        "x": round(x, 4),
        "y": round(y, 4),
        "w": round(max(w, 0.0), 4),
        "h": round(max(h, 0.0), 4),
    }


def _clamp01(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(0.0, min(1.0, number))


def _persist_garments(
    db: Session,
    outfit: Outfit,
    detected: List[Dict[str, Any]],
    working_image: Image.Image,
) -> List[Garment]:
    rows: List[Garment] = []
    for item in detected:
        # §4.5: colours come from the pixels inside the box, not from the
        # model's naming. This is what makes a re-scan reproducible (§2.3).
        colours = dominant_colours(working_image, bbox=item["bbox"], max_colours=3)
        row = Garment(
            outfit_id=outfit.id,
            category=item["category"],
            bbox=item["bbox"],
            colors=colours,
            pattern=item["pattern"],
            formality=item["formality"],
            attributes=item["attributes"],
        )
        db.add(row)
        rows.append(row)
    db.flush()  # assign ids before notes reference them
    return rows


def _garment_as_dict(row: Garment) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "category": row.category,
        "bbox": row.bbox,
        "colors": row.colors,
        "pattern": row.pattern,
        "formality": row.formality,
        "attributes": row.attributes,
    }


def _prose_from_analysis(
    analysis: Dict[str, Any], garment_rows: List[Garment]
) -> Dict[str, Any]:
    """Map the model payload onto §5.5, resolving indices to garment ids."""
    notes: List[Dict[str, Any]] = []
    for note in analysis.get("garment_notes") or []:
        if not isinstance(note, dict):
            continue
        try:
            index = int(note.get("garment_index"))
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(garment_rows):
            notes.append(
                {
                    "garment_id": str(garment_rows[index].id),
                    "note": str(note.get("note") or ""),
                }
            )

    proportion = (analysis.get("proportion_note") or "").strip()

    quick_reads: List[Dict[str, str]] = []
    for item in analysis.get("quick_reads") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        dimension = str(item.get("dimension") or "").strip()
        if text and dimension:
            quick_reads.append({"dimension": dimension, "text": text})
    quick_reads = quick_reads[:4]

    focal_point = str(analysis.get("focal_point") or "").strip()

    return {
        "overall_read": str(analysis.get("overall_read") or "").strip(),
        "color_note": str(analysis.get("color_note") or "").strip(),
        "formality_note": str(analysis.get("formality_note") or "").strip(),
        "proportion_note": proportion or None,
        "garment_notes": notes,
        "verdict_phrase": str(analysis.get("verdict_phrase") or "").strip(),
        "verdict_subtitle": str(analysis.get("verdict_subtitle") or "").strip(),
        "focal_point": focal_point or None,
        "quick_reads": quick_reads,
    }


def _enforce_verdict_meter_agreement(
    prose: Dict[str, Any], meters: Dict[str, Any]
) -> None:
    """§7.8 "one verdict only": the verdict and the meters must never
    disagree. When there is truly nothing to base a meter on (both come
    back null — see rules.py), no phrasing, VLM-authored or templated, is
    allowed to claim more confidence than that. Mutates ``prose`` in place,
    using the same hedge fallback.py already ships (and is already
    lint-covered), so this is enforced once, in one place, regardless of
    which path wrote the prose.
    """
    if meters.get("occasion_match") is None and meters.get("signal_clarity") is None:
        prose["verdict_phrase"] = "Hard to place"
        prose["verdict_subtitle"] = "Too little detail to compare pieces."


# --- Image-hash cache (§8) -------------------------------------------------
def _find_cached_result(db: Session, outfit: Outfit) -> Optional[Outfit]:
    """A previous completed scan of the same pixels in the same context.

    Keyed on (image hash, occasion) because the notes are occasion-dependent —
    the same photo tagged ``work`` and ``evening`` must not share feedback.
    """
    if not outfit.image_sha256:
        return None
    statement = (
        select(Outfit)
        .where(
            Outfit.image_sha256 == outfit.image_sha256,
            Outfit.status == "complete",
            Outfit.id != outfit.id,
            Outfit.deleted_at.is_(None),
        )
        .order_by(Outfit.completed_at.desc())
        .limit(5)
    )
    for candidate in db.execute(statement).scalars():
        if candidate.occasion == outfit.occasion and candidate.feedback is not None:
            return candidate
    return None


def _clone_result(db: Session, outfit: Outfit, source: Outfit) -> None:
    index_map: Dict[str, str] = {}
    for old in source.garments:
        new = Garment(
            outfit_id=outfit.id,
            category=old.category,
            bbox=old.bbox,
            colors=old.colors,
            pattern=old.pattern,
            formality=old.formality,
            attributes=old.attributes,
        )
        db.add(new)
        db.flush()
        index_map[str(old.id)] = str(new.id)

    source_feedback = source.feedback
    remapped_notes = [
        {
            "garment_id": index_map.get(str(note.get("garment_id"))),
            "note": note.get("note"),
        }
        for note in (source_feedback.garment_notes or [])
        if index_map.get(str(note.get("garment_id")))
    ]

    signals = dict(source_feedback.signals or {})
    signals["cache"] = {"hit": True, "source_outfit_id": str(source.id)}

    db.add(
        OutfitFeedback(
            outfit_id=outfit.id,
            overall_read=source_feedback.overall_read,
            color_note=source_feedback.color_note,
            formality_note=source_feedback.formality_note,
            proportion_note=source_feedback.proportion_note,
            garment_notes=remapped_notes,
            # §7.7 glanceable fields — a cache hit is the same photo in the
            # same context, so these carry over verbatim, same as the
            # long-form fields above.
            verdict_phrase=source_feedback.verdict_phrase,
            verdict_subtitle=source_feedback.verdict_subtitle,
            focal_point=source_feedback.focal_point,
            quick_reads=source_feedback.quick_reads,
            occasion_match=source_feedback.occasion_match,
            signal_clarity=source_feedback.signal_clarity,
            signals=signals,
            model_version=source_feedback.model_version,
        )
    )
    outfit.status = "complete"
    outfit.failure_reason = None
    outfit.completed_at = datetime.now(timezone.utc)
    db.commit()


# --- Idempotency + failure -------------------------------------------------
def _clear_previous_results(db: Session, outfit: Outfit) -> None:
    """§8: a retry must not duplicate garments or feedback."""
    for garment in list(outfit.garments):
        db.delete(garment)
    if outfit.feedback is not None:
        db.delete(outfit.feedback)
    db.commit()
    db.refresh(outfit)


def _fail(db: Session, outfit_id: uuid.UUID, reason: str) -> None:
    try:
        db.rollback()
        outfit = db.get(Outfit, outfit_id)
        if outfit is None:
            return
        outfit.status = "failed"
        outfit.failure_reason = reason
        outfit.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:  # pragma: no cover - last resort
        logger.exception("could not record failure for outfit %s", outfit_id)
        db.rollback()
