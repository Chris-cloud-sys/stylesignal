"""Worker pipeline behaviour — spec §4.3-§4.7, §7.6, §8."""
import pytest

from app.worker.colour import garment_palette
from app.worker.fallback import build_fallback_feedback
from app.worker.lint import lint_feedback
from app.worker.pipeline import _detection_failure_reason, _enforce_verdict_meter_agreement
from app.worker.preprocess import UndecodableImage, preprocess
from app.worker.rules import build_signals, compute_meters

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

    # §7.7 glanceable fields.
    assert feedback["verdict_phrase"]
    assert feedback["verdict_subtitle"]
    assert feedback["focal_point"]
    assert 3 <= len(feedback["quick_reads"]) <= 4
    for quick_read in feedback["quick_reads"]:
        assert quick_read["dimension"]
        assert quick_read["text"]


def test_fallback_glanceable_fields_respect_copy_limits():
    """Belt-and-braces on top of the lint check — a faster failure signal
    than "some lint rule fired" when a template string runs long."""
    signals = build_signals(_garments(), [{"hex": "#1B2A44", "weight": 1.0}], "work")
    feedback = build_fallback_feedback(signals, _garments(), "work")

    assert len(feedback["verdict_phrase"].split()) <= 5
    assert len(feedback["verdict_subtitle"].split()) <= 8
    assert len(feedback["focal_point"].split()) <= 12
    for quick_read in feedback["quick_reads"]:
        assert len(quick_read["text"].split()) <= 15


def test_fallback_focal_point_is_none_with_no_garments():
    signals = build_signals([], [{"hex": "#8A8578", "weight": 1.0}], None)
    feedback = build_fallback_feedback(signals, [], None)
    assert feedback["focal_point"] is None
    # Still at least colour + formality even with nothing detected.
    assert len(feedback["quick_reads"]) >= 2


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


def test_fallback_fit_read_does_not_claim_register_holds_when_unknown():
    """§7.8 "one verdict only": with zero resolvable formality data, nothing
    — not even a quick read — may assert the occasion register "holds".
    That claim used to fire unconditionally on any stated occasion, directly
    contradicting the verdict_phrase's own "Hard to place" hedge on the same
    screen — the concrete bug behind the client's "two verdicts" report."""
    signals = build_signals([], [{"hex": "#8A8578", "weight": 1.0}], "work")
    feedback = build_fallback_feedback(signals, [], "work")
    assert feedback["verdict_phrase"] == "Hard to place"
    assert not any(read["dimension"] == "fit" for read in feedback["quick_reads"])


def test_fallback_fit_read_appears_when_coherence_is_known():
    """Same occasion, but with real garments this time — the claim is
    earned, so it should appear."""
    signals = build_signals(_garments(), [{"hex": "#1B2A44", "weight": 1.0}], "work")
    feedback = build_fallback_feedback(signals, _garments(), "work")
    assert any(read["dimension"] == "fit" for read in feedback["quick_reads"])


# --- §7.7 "sharpen the gap, never suggest a fix" on a weak occasion_match ---
def test_fallback_sharpens_the_gap_with_the_outlier_garment():
    """_garments() is a split-formality set (footwear pulls casual against a
    work-appropriate outerwear/bottom) whose mean still lands inside the
    "work" band — so the weak match comes from coherence, not band distance,
    and the outlier garment is the honest reason to name."""
    signals = build_signals(_garments(), [], "work")
    meters = compute_meters(signals, "work")
    assert meters["occasion_match"]["level"] == "partial"

    feedback = build_fallback_feedback(
        signals, _garments(), "work", meters["occasion_match"]
    )
    fit_reads = [r["text"] for r in feedback["quick_reads"] if r["dimension"] == "fit"]
    assert fit_reads, feedback["quick_reads"]
    assert "footwear" in fit_reads[0] and "more casual" in fit_reads[0]
    assert "the register holds" not in fit_reads[0]
    assert lint_feedback(feedback).ok


def test_fallback_sharpens_the_gap_by_band_distance_without_an_outlier():
    """Three consistently-formal garments against a casual occasion: no
    single outlier to name, so the gap has to come from the register as a
    whole sitting outside the occasion's band."""
    garments = [
        {"id": "1", "category": "outerwear", "formality": 0.9},
        {"id": "2", "category": "bottom", "formality": 0.85},
        {"id": "3", "category": "footwear", "formality": 0.88},
    ]
    signals = build_signals(garments, [], "casual")
    assert signals["formality"]["coherence"] == "consistent"
    meters = compute_meters(signals, "casual")
    assert meters["occasion_match"]["level"] == "off"

    feedback = build_fallback_feedback(
        signals, garments, "casual", meters["occasion_match"]
    )
    fit_reads = [r["text"] for r in feedback["quick_reads"] if r["dimension"] == "fit"]
    assert fit_reads, feedback["quick_reads"]
    assert fit_reads[0] == "This reads more formal than a typical casual look."
    assert lint_feedback(feedback).ok


def test_fallback_still_says_register_holds_on_a_strong_match():
    """The positive phrasing is still correct — and still gated the same
    way — when the match is actually strong; this isn't a regression of
    entries #16/#18, just the new branch's sibling case."""
    garments = _garments()[:2]  # consistent, formality 0.75/0.7
    signals = build_signals(garments, [], "formal")
    meters = compute_meters(signals, "formal")
    assert meters["occasion_match"]["level"] == "strong"

    feedback = build_fallback_feedback(
        signals, garments, "formal", meters["occasion_match"]
    )
    fit_reads = [r["text"] for r in feedback["quick_reads"] if r["dimension"] == "fit"]
    assert fit_reads == ["For a formal context, the register holds."]


# --- §7.8 garment-only palette ----------------------------------------------
def _garment(hex_value: str, weight: float, w: float, h: float) -> dict:
    from app.worker.colour import hex_to_lab

    return {
        "bbox": {"x": 0.0, "y": 0.0, "w": w, "h": h},
        "colors": [{"hex": hex_value, "lab": list(hex_to_lab(hex_value)), "weight": weight}],
    }


def test_garment_palette_empty_with_no_garments():
    assert garment_palette([]) == []


def test_garment_palette_weights_by_garment_area():
    """A coat-sized garment should outrank a belt-sized one even if their
    own internal weight is identical — §7.8 wants the *displayed* palette to
    reflect what actually dominates the look, not treat every detected
    piece as equally prominent regardless of size."""
    coat = _garment("#1B2A44", weight=1.0, w=0.6, h=0.8)  # navy, large
    belt = _garment("#D4A017", weight=1.0, w=0.05, h=0.03)  # gold, tiny

    palette = garment_palette([coat, belt], max_colours=5)

    assert palette[0]["hex"] == "#1B2A44"
    assert palette[0]["weight"] > palette[1]["weight"]


def test_garment_palette_merges_perceptually_close_colours():
    """Navy jacket + navy trousers should collapse into one swatch, not two
    near-identical ones — same merge behaviour dominant_colours applies
    within a single garment."""
    jacket = _garment("#1B2A44", weight=1.0, w=0.5, h=0.5)
    trousers = _garment("#1C2B45", weight=1.0, w=0.4, h=0.4)  # a hair off navy

    palette = garment_palette([jacket, trousers])

    assert len(palette) == 1


def test_garment_palette_ignores_environment_colours():
    """The whole point: a wall/floor tone from the old whole-image sample
    must not appear just because it was never passed in — garment_palette
    only ever sees what garments/_persist_garments actually measured."""
    top = _garment("#1B2A44", weight=1.0, w=0.5, h=0.4)
    palette = garment_palette([top])
    assert all(entry["hex"] == "#1B2A44" for entry in palette)


# --- §7.8 "one verdict only" ------------------------------------------------
def test_enforce_verdict_meter_agreement_hedges_when_both_meters_are_null():
    prose = {"verdict_phrase": "Quiet, tidy weekend", "verdict_subtitle": "Reads controlled."}
    meters = {"occasion_match": None, "signal_clarity": None}

    _enforce_verdict_meter_agreement(prose, meters)

    assert prose["verdict_phrase"] == "Hard to place"
    assert prose["verdict_subtitle"] == "Too little detail to compare pieces."


def test_enforce_verdict_meter_agreement_leaves_prose_alone_when_a_meter_exists():
    prose = {"verdict_phrase": "Quiet, tidy weekend", "verdict_subtitle": "Reads controlled."}
    meters = {"occasion_match": None, "signal_clarity": {"level": "strong", "score": 0.8}}

    _enforce_verdict_meter_agreement(prose, meters)

    assert prose["verdict_phrase"] == "Quiet, tidy weekend"
    assert prose["verdict_subtitle"] == "Reads controlled."
