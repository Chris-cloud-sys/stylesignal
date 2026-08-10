"""Worker pipeline behaviour — spec §4.3-§4.7, §7.6, §8."""
import pytest

from app.worker.fallback import build_fallback_feedback
from app.worker.lint import lint_feedback
from app.worker.pipeline import _detection_failure_reason
from app.worker.preprocess import UndecodableImage, preprocess
from app.worker.rules import build_signals

from .conftest import make_jpeg


# --- §4.3 preprocess -------------------------------------------------------
def test_preprocess_normalises_and_hashes():
    result = preprocess(make_jpeg(2400, 3600))
    assert max(result.width, result.height) == 1600
    assert result.working_bytes.startswith(b"\xff\xd8")  # JPEG SOI
    assert len(result.image_sha256) == 64


def test_preprocess_hash_is_stable_for_identical_pixels():
    """§8 image-hash caching depends on this."""
    source = make_jpeg()
    assert preprocess(source).image_sha256 == preprocess(source).image_sha256


def test_preprocess_produces_a_smaller_thumbnail():
    result = preprocess(make_jpeg(1200, 1800))
    assert len(result.thumb_bytes) < len(result.working_bytes)


def test_preprocess_rejects_junk():
    with pytest.raises(UndecodableImage):
        preprocess(b"this is definitely not an image")


def test_preprocess_rejects_empty_upload():
    with pytest.raises(UndecodableImage):
        preprocess(b"")


def test_preprocess_applies_orientation_then_strips_exif():
    """§4.3: rotate per EXIF, then drop it — it can carry GPS (§8)."""
    import io

    from PIL import Image

    source = Image.new("RGB", (400, 200), (120, 90, 60))
    exif = Image.Exif()
    exif[274] = 6  # orientation: rotate 90° clockwise
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", exif=exif.tobytes())

    result = preprocess(buffer.getvalue())

    # The rotation was applied: a landscape source is now portrait.
    assert result.height > result.width
    # And nothing of the original EXIF survives into the working copy.
    assert not dict(Image.open(io.BytesIO(result.working_bytes)).getexif())


# --- §4.4 detection failure reason ------------------------------------------
def test_no_detection_run_is_not_a_failure():
    """No VLM at all -- falls through to the §7.6 fallback, not a failure."""
    assert _detection_failure_reason(None, []) is None


def test_flat_lay_fails_as_no_person_even_with_garments_detected():
    """The photo brief's own case: a flat-lay or empty room should fail

    cleanly with 'no person', not invent feedback for an outfit nobody is
    wearing -- even though the VLM correctly names the garments it sees.
    """
    analysis = {"person_present": False}
    detected = [{"category": "top"}, {"category": "bottom"}]
    assert _detection_failure_reason(analysis, detected) == "no_person"


def test_no_person_and_no_garments_is_still_no_person():
    analysis = {"person_present": False}
    assert _detection_failure_reason(analysis, []) == "no_person"


def test_person_present_with_no_garments_fails_as_no_garments_detected():
    analysis = {"person_present": True}
    assert _detection_failure_reason(analysis, []) == "no_garments_detected"


def test_person_present_with_garments_is_not_a_failure():
    analysis = {"person_present": True}
    detected = [{"category": "top"}]
    assert _detection_failure_reason(analysis, detected) is None


# --- §4.7 rule signals -----------------------------------------------------
def _garments():
    return [
        {
            "id": "1",
            "category": "outerwear",
            "bbox": {"x": 0.2, "y": 0.15, "w": 0.6, "h": 0.45},
            "colors": [{"hex": "#1B2A44", "lab": [17.4, 5.1, -17.9], "weight": 0.8}],
            "pattern": "solid",
            "formality": 0.75,
        },
        {
            "id": "2",
            "category": "bottom",
            "bbox": {"x": 0.3, "y": 0.5, "w": 0.35, "h": 0.4},
            "colors": [{"hex": "#5A4632", "lab": [32.1, 6.0, 16.5], "weight": 0.9}],
            "pattern": "solid",
            "formality": 0.7,
        },
        {
            "id": "3",
            "category": "footwear",
            "bbox": {"x": 0.3, "y": 0.88, "w": 0.35, "h": 0.1},
            "colors": [{"hex": "#EFEFEF", "lab": [94.8, 0.0, 0.0], "weight": 1.0}],
            "pattern": "solid",
            "formality": 0.2,
        },
    ]


def test_formality_split_is_detected_and_attributed():
    signals = build_signals(_garments(), [], occasion="work")
    formality = signals["formality"]
    assert formality["coherence"] == "split"
    # The trainers are the piece pulling against the rest.
    assert formality["outlier_category"] == "footwear"
    assert formality["outlier_direction"] == "more casual"


def test_consistent_formality_reports_no_outlier():
    garments = _garments()[:2]
    signals = build_signals(garments, [], occasion=None)
    assert signals["formality"]["coherence"] == "consistent"
    assert signals["formality"]["outlier_category"] is None


def test_missing_formality_is_unknown_not_zero():
    signals = build_signals([{"category": "top", "formality": None}], [], None)
    assert signals["formality"]["coherence"] == "unknown"
    assert signals["formality"]["mean"] is None


def test_proportion_flags_come_from_geometry():
    garments = [
        {
            "category": "top",
            "bbox": {"x": 0.3, "y": 0.1, "w": 0.4, "h": 0.28},
            "formality": 0.5,
        },
        {
            "category": "bottom",
            "bbox": {"x": 0.35, "y": 0.38, "w": 0.18, "h": 0.5},
            "formality": 0.5,
        },
    ]
    proportion = build_signals(garments, [], None)["proportion"]
    assert "cropped_upper_raises_waistline" in proportion["flags"]
    assert "narrow_lower_silhouette" in proportion["flags"]
    assert proportion["upper_to_lower_width_ratio"] > 1.35


def test_garments_without_boxes_produce_no_flags():
    proportion = build_signals(
        [{"category": "top", "formality": 0.5}], [], None
    )["proportion"]
    assert proportion["flags"] == []


# --- §7.6 templated fallback ----------------------------------------------
def test_fallback_produces_every_required_field():
    signals = build_signals(_garments(), [{"hex": "#1B2A44", "weight": 1.0}], "work")
    feedback = build_fallback_feedback(signals, _garments(), "work")

    assert feedback["overall_read"]
    assert feedback["color_note"]
    assert feedback["formality_note"]
    assert len(feedback["garment_notes"]) == 3


def test_fallback_passes_its_own_lint():
    """The fallback ships when the model is down — it cannot break §7.3."""
    for occasion in (None, "work", "formal", "evening", "casual", "athletic"):
        for garments in (_garments(), _garments()[:1], []):
            signals = build_signals(
                garments, [{"hex": "#E0A32E", "weight": 1.0}], occasion
            )
            report = lint_feedback(
                build_fallback_feedback(signals, garments, occasion)
            )
            assert report.ok, (occasion, len(garments), report.as_dict())


def test_fallback_never_prints_a_number():
    """§7.3 forbids surfacing numeric signals, and the fallback is built
    directly from numeric signals — so this is the risky path."""
    signals = build_signals(_garments(), [{"hex": "#1B2A44", "weight": 1.0}], "work")
    feedback = build_fallback_feedback(signals, _garments(), "work")

    prose = " ".join(
        [
            feedback["overall_read"],
            feedback["color_note"],
            feedback["formality_note"],
            feedback.get("proportion_note") or "",
        ]
        + [note["note"] for note in feedback["garment_notes"]]
    )
    assert not any(character.isdigit() for character in prose), prose


def test_fallback_with_no_garments_still_reads():
    """No VLM means no detection, but the palette still supports a read."""
    signals = build_signals([], [{"hex": "#8A8578", "weight": 1.0}], None)
    feedback = build_fallback_feedback(signals, [], None)
    assert feedback["overall_read"]
    assert feedback["color_note"]
    assert lint_feedback(feedback).ok
