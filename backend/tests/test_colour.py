"""Colour extraction and harmony rules — spec §4.5, §4.7.

§2.3 promises deterministic reads: the same look must always read the same way.
That rests on this module being reproducible, so these tests pin both the
conversion maths and the classification boundaries.
"""
import pytest
from PIL import Image

from app.worker.colour import (
    classify_harmony,
    delta_e76,
    describe_contrast,
    dominant_colours,
    hex_to_lab,
    hex_to_rgb,
    hue_distance,
    is_neutral,
    lab_chroma,
    rgb_to_hex,
    rgb_to_lab,
)


# --- Conversions -----------------------------------------------------------
def test_known_lab_values():
    # Reference values for sRGB primaries under D65.
    assert rgb_to_lab((255, 255, 255))[0] == pytest.approx(100.0, abs=0.1)
    assert rgb_to_lab((0, 0, 0)) == (0.0, 0.0, 0.0)

    red = rgb_to_lab((255, 0, 0))
    assert red[0] == pytest.approx(53.24, abs=0.1)
    assert red[1] == pytest.approx(80.09, abs=0.2)
    assert red[2] == pytest.approx(67.20, abs=0.2)


def test_hex_roundtrip():
    assert hex_to_rgb("#1B2A44") == (27, 42, 68)
    assert hex_to_rgb("1B2A44") == (27, 42, 68)
    assert hex_to_rgb("#abc") == (170, 187, 204)
    assert rgb_to_hex((27, 42, 68)) == "#1B2A44"


def test_invalid_hex_raises():
    with pytest.raises(ValueError):
        hex_to_rgb("#12345")


def test_greys_are_neutral_and_saturated_hues_are_not():
    assert is_neutral(hex_to_lab("#808080"))
    assert is_neutral(hex_to_lab("#F4F0E9"))  # Bone, the brand background
    assert not is_neutral(hex_to_lab("#E0A32E"))  # Signal Amber
    assert lab_chroma(hex_to_lab("#FF0000")) > 50


def test_hue_distance_wraps():
    assert hue_distance(10.0, 350.0) == pytest.approx(20.0)
    assert hue_distance(0.0, 180.0) == pytest.approx(180.0)


def test_delta_e_is_zero_for_identical_colours():
    lab = hex_to_lab("#2C4A7C")
    assert delta_e76(lab, lab) == 0.0


# --- Harmony classification (§4.7) ----------------------------------------
def _palette(*hexes):
    weight = 1.0 / len(hexes)
    return [
        {"hex": h, "lab": list(hex_to_lab(h)), "weight": weight} for h in hexes
    ]


def test_all_neutral_palette_is_neutral_anchored():
    result = classify_harmony(_palette("#1A1A1A", "#8A8578", "#F4F0E9"))
    assert result["harmony_class"] == "neutral-anchored"
    assert result["chromatic_count"] == 0


def test_neutrals_plus_one_accent_is_neutral_anchored():
    result = classify_harmony(
        _palette("#1A1A1A", "#F4F0E9", "#8A8578", "#E0A32E")
    )
    assert result["harmony_class"] == "neutral-anchored"
    assert result["neutral_weight"] >= 0.55


def test_adjacent_hues_are_analogous():
    # Orange and yellow-orange — neighbours on the wheel, one cluster.
    result = classify_harmony(_palette("#D2691E", "#E0A32E", "#C86414"))
    assert result["harmony_class"] == "analogous"
    assert result["cluster_count"] == 1


def test_opposing_hues_are_complementary():
    # Strong blue against strong orange: two clusters, far apart.
    result = classify_harmony(_palette("#1F5FBF", "#E07B1F", "#2A6ACF"))
    assert result["harmony_class"] == "complementary"
    assert result["cluster_count"] == 2
    assert result["cluster_separation_degrees"] >= 100.0


def test_scattered_hues_clash():
    # Green, magenta and amber: three separate clusters with no neutral to
    # mediate. Note the raw spread here (~168°) is *wider* than the
    # complementary case above (~136°) — classification is by cluster count,
    # not by spread. This test is the regression guard for that.
    result = classify_harmony(_palette("#00A000", "#C000C0", "#E0A32E"))
    assert result["harmony_class"] == "clash"
    assert result["cluster_count"] == 3
    assert result["hue_spread_degrees"] > 145.0


def test_clash_spread_exceeds_complementary_spread():
    """The trap this classifier is built to avoid, pinned explicitly."""
    complementary = classify_harmony(_palette("#1F5FBF", "#E07B1F", "#2A6ACF"))
    clash = classify_harmony(_palette("#00A000", "#C000C0", "#E0A32E"))

    assert clash["hue_spread_degrees"] > complementary["hue_spread_degrees"]
    assert complementary["harmony_class"] == "complementary"
    assert clash["harmony_class"] == "clash"


def test_hues_wrap_around_zero():
    """350° and 5° are the same family, not opposite ends of the range."""
    result = classify_harmony(_palette("#C4006A", "#C40030", "#B8003C"))
    assert result["cluster_count"] == 1
    assert result["harmony_class"] in ("analogous", "neutral-anchored")


def test_empty_palette_degrades_safely():
    result = classify_harmony([])
    assert result["harmony_class"] == "neutral-anchored"


def test_palette_entries_without_lab_are_derived_from_hex():
    result = classify_harmony([{"hex": "#1A1A1A", "weight": 1.0}])
    assert result["chromatic_count"] == 0


def test_lightness_contrast_bands():
    dark_and_light = classify_harmony(_palette("#000000", "#FFFFFF"))
    assert dark_and_light["max_lightness_contrast"] > 90
    assert describe_contrast(dark_and_light["max_lightness_contrast"]) == (
        "high-contrast"
    )
    assert describe_contrast(5.0) == "low-contrast"
    assert describe_contrast(30.0) == "moderately contrasted"


# --- Pixel extraction ------------------------------------------------------
def test_dominant_colours_finds_the_actual_colour():
    image = Image.new("RGB", (200, 200), (27, 42, 68))
    colours = dominant_colours(image)
    assert colours
    assert colours[0]["weight"] == pytest.approx(1.0, abs=0.05)
    assert delta_e76(colours[0]["lab"], list(rgb_to_lab((27, 42, 68)))) < 6


def test_dominant_colours_respects_the_bbox():
    image = Image.new("RGB", (200, 200), (10, 10, 10))
    image.paste(Image.new("RGB", (200, 60), (224, 163, 46)), (0, 0))

    top_band = dominant_colours(image, bbox={"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.28})
    bottom = dominant_colours(image, bbox={"x": 0.0, "y": 0.5, "w": 1.0, "h": 0.5})

    assert delta_e76(top_band[0]["lab"], list(rgb_to_lab((224, 163, 46)))) < 12
    assert delta_e76(bottom[0]["lab"], list(rgb_to_lab((10, 10, 10)))) < 12


def test_degenerate_bbox_falls_back_to_whole_image():
    image = Image.new("RGB", (200, 200), (100, 100, 100))
    colours = dominant_colours(image, bbox={"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0})
    assert colours  # must not raise or return nothing


def test_extraction_is_deterministic():
    """§2.3: the same photo must always produce the same read."""
    image = Image.new("RGB", (120, 240), (60, 80, 120))
    image.paste(Image.new("RGB", (120, 80), (200, 180, 150)), (0, 0))
    assert dominant_colours(image) == dominant_colours(image)
