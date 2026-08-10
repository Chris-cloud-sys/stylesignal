"""Templated descriptive fallback — spec §7.6.

When the VLM is unavailable, refuses, or never clears the lint pass, the
product still returns something useful rather than failing the scan. The text
is assembled from the §4.7 rule signals alone, so it is lower resolution than a
model read but every sentence is still evidence-backed (§7.4) and still obeys
the §7.3 rules — ``test_fallback_passes_lint`` enforces that.
"""
from typing import Any, Dict, List, Optional, Sequence

_HARMONY_PHRASES = {
    "analogous": (
        "the colours sit close together on the wheel, so the palette reads as "
        "one continuous range rather than a set of separate blocks"
    ),
    "complementary": (
        "two opposing hues carry the palette, which sets up a deliberate "
        "contrast between the pieces"
    ),
    "neutral-anchored": (
        "neutrals carry most of the palette, so any colour that is present "
        "reads as the accent rather than as competition"
    ),
    "clash": (
        "several hues sit far apart without a neutral to mediate between them, "
        "so they compete for attention"
    ),
}

_CONTRAST_PHRASES = {
    "low-contrast": (
        "The tones stay within a narrow lightness range, which keeps the "
        "silhouette reading as a single block"
    ),
    "moderately contrasted": (
        "There is a visible step in lightness between the pieces, which draws "
        "a line where they meet"
    ),
    "high-contrast": (
        "The lightness gap between the pieces is wide, so the eye lands on the "
        "boundary between them first"
    ),
}

_FORMALITY_PHRASES = {
    "consistent": (
        "The pieces agree on formality; nothing pulls against the register the "
        "rest of the look sets"
    ),
    "mixed": (
        "The pieces mostly agree on formality, with one register sitting apart "
        "from the others"
    ),
    "split": (
        "The look spans two formality registers at once, so it reads as a "
        "deliberate mix rather than a single note"
    ),
    "unknown": (
        "There was not enough detail to read how the pieces compare on "
        "formality"
    ),
}

_LEVEL_PHRASES = (
    (0.25, "relaxed and casual"),
    (0.45, "everyday casual"),
    (0.65, "smart-casual"),
    (0.85, "polished and dressed-up"),
    (1.01, "formal"),
)

_PROPORTION_PHRASES = {
    "cropped_upper_raises_waistline": (
        "the shorter upper piece places the visual waistline higher than the "
        "natural one, which lengthens the line below it"
    ),
    "long_upper_lowers_waistline": (
        "the longer upper piece carries the visual waistline down, which "
        "shortens the line below it"
    ),
    "long_outerwear_over_lower_half": (
        "the outer layer runs past the midpoint of the lower half, drawing one "
        "long vertical line down the middle of the look"
    ),
    "layered_length_contrast": (
        "the layers finish at clearly different lengths, so the hems read as a "
        "stepped edge"
    ),
    "narrow_lower_silhouette": (
        "the lower half holds a narrow silhouette, which concentrates volume "
        "above the waist"
    ),
    "volume_concentrated_upper": (
        "volume gathers in the upper half and tapers below it"
    ),
    "volume_concentrated_lower": (
        "volume gathers in the lower half and stays close above it"
    ),
}

_OCCASION_PHRASES = {
    "casual": "an everyday casual context",
    "work": "a work context",
    "formal": "a formal context",
    "evening": "an evening context",
    "athletic": "an active context",
    "other": "the context given",
}


def build_fallback_feedback(
    signals: Dict[str, Any],
    garments: Sequence[Dict[str, Any]],
    occasion: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble the §5.5 prose fields from rule signals alone."""
    colour = signals.get("colour") or {}
    formality = signals.get("formality") or {}
    proportion = signals.get("proportion") or {}

    return {
        "overall_read": _overall_read(formality, garments, occasion),
        "color_note": _colour_note(colour),
        "formality_note": _formality_note(formality),
        "proportion_note": _proportion_note(proportion),
        "garment_notes": _garment_notes(garments),
    }


def _overall_read(
    formality: Dict[str, Any],
    garments: Sequence[Dict[str, Any]],
    occasion: Optional[str],
) -> str:
    mean = formality.get("mean")
    if mean is None:
        level = "hard to place on the casual-to-formal range"
    else:
        level = next(
            phrase for ceiling, phrase in _LEVEL_PHRASES if float(mean) < ceiling
        )

    pieces = _describe_pieces(garments)
    sentences = []
    if pieces:
        sentences.append(
            "Taken together, {0} read as {1}.".format(pieces, level)
        )
    else:
        sentences.append("Overall the look reads as {0}.".format(level))

    coherence = formality.get("coherence")
    if coherence == "consistent":
        sentences.append(
            "The pieces hold that register consistently, so the look sends one "
            "clear signal."
        )
    elif coherence in ("mixed", "split"):
        sentences.append(
            "The register is not uniform across the pieces, so the look sends "
            "more than one signal at once."
        )

    if occasion:
        sentences.append(
            "Against {0}, that is the register the look is working in.".format(
                _OCCASION_PHRASES.get(occasion, "the context given")
            )
        )

    sentences.append(
        "This is a reduced read: the detailed model was unavailable, so it "
        "rests on the measured colour and geometry only."
    )
    return " ".join(sentences)


def _colour_note(colour: Dict[str, Any]) -> str:
    harmony = str(colour.get("harmony_class") or "neutral-anchored")
    contrast = str(colour.get("contrast_band") or "low-contrast")

    parts = [
        "The palette is {0}: {1}.".format(
            harmony.replace("-", " "),
            _HARMONY_PHRASES.get(harmony, _HARMONY_PHRASES["neutral-anchored"]),
        ),
        "{0}.".format(
            _CONTRAST_PHRASES.get(contrast, _CONTRAST_PHRASES["low-contrast"])
        ),
    ]

    neutral_weight = colour.get("neutral_weight")
    if isinstance(neutral_weight, (int, float)) and float(neutral_weight) >= 0.7:
        parts.append(
            "Neutrals dominate the surface area, which keeps the colour that is "
            "present in a supporting role."
        )
    return " ".join(parts)


def _formality_note(formality: Dict[str, Any]) -> str:
    coherence = str(formality.get("coherence") or "unknown")
    text = "{0}.".format(
        _FORMALITY_PHRASES.get(coherence, _FORMALITY_PHRASES["unknown"])
    )

    category = formality.get("outlier_category")
    direction = formality.get("outlier_direction")
    if category and direction:
        text += " The {0} reads {1} than the rest of the look, and that gap is " \
                "where the mixed register comes from.".format(category, direction)
    return text


def _proportion_note(proportion: Dict[str, Any]) -> Optional[str]:
    flags: List[str] = list(proportion.get("flags") or [])
    described = [_PROPORTION_PHRASES[f] for f in flags if f in _PROPORTION_PHRASES]
    if not described:
        return None
    if len(described) == 1:
        return "On line and proportion, {0}.".format(described[0])
    return "On line and proportion, {0}; {1}.".format(
        described[0], "; ".join(described[1:3])
    )


def _garment_notes(garments: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    notes = []
    for garment in garments:
        category = str(garment.get("category") or "piece")
        colours = garment.get("colors") or []
        lead = colours[0].get("hex") if colours else None
        formality = garment.get("formality")

        if formality is None:
            register = "sits in the middle of the range"
        elif float(formality) >= 0.7:
            register = "sits at the formal end of the look"
        elif float(formality) <= 0.35:
            register = "sits at the casual end of the look"
        else:
            register = "sits between the casual and formal ends of the look"

        pattern = str(garment.get("pattern") or "solid")
        surface = (
            "a solid surface" if pattern == "solid" else "a {0} surface".format(pattern)
        )

        note = "The {0} carries {1} and {2}.".format(category, surface, register)
        if lead:
            note = "The {0} carries {1} in a {2} tone and {3}.".format(
                category, surface, _tone_word(lead), register
            )

        notes.append({"garment_id": garment.get("id"), "note": note})
    return notes


def _tone_word(hex_value: str) -> str:
    """Coarse lightness word from a hex colour, for the templated notes."""
    try:
        from .colour import hex_to_lab

        lightness = hex_to_lab(hex_value)[0]
    except (ValueError, TypeError):
        return "mid"
    if lightness < 30:
        return "dark"
    if lightness < 60:
        return "mid"
    if lightness < 82:
        return "light"
    return "very light"


def _describe_pieces(garments: Sequence[Dict[str, Any]]) -> str:
    categories = []
    for garment in garments:
        category = garment.get("category")
        if category and category not in categories:
            categories.append(str(category))
    if not categories:
        return ""
    if len(categories) == 1:
        return "the {0}".format(categories[0])
    return "the {0} and {1}".format(", ".join(categories[:-1]), categories[-1])
