"""Templated descriptive fallback — spec §7.6.

When the VLM is unavailable, refuses, or never clears the lint pass, the
product still returns something useful rather than failing the scan. The text
is assembled from the §4.7 rule signals alone, so it is lower resolution than a
model read but every sentence is still evidence-backed (§7.4) and still obeys
the §7.3 rules — ``test_fallback_passes_lint`` enforces that.
"""
from typing import Any, Dict, List, Optional, Sequence

from .rules import OCCASION_FORMALITY_BANDS

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

# --- §7.7 glanceable fields --------------------------------------------------
# Every string below is hand-length-checked against the lint word limits at
# authoring time (verdict_phrase <=5 words, verdict_subtitle <=8, quick_reads
# text <=15 and one sentence) rather than measured at runtime — same approach
# as the phrase dicts above, just shorter. test_fallback_passes_its_own_lint
# is what actually proves it.

_VERDICT_SUBTITLES = {
    "consistent": "The pieces agree with each other.",
    "mixed": "One piece sits apart from the rest.",
    "split": "The pieces pull in different directions.",
    "unknown": "Too little detail to compare pieces.",
}

_QUICK_COLOUR_PHRASES = {
    "analogous": "The colours sit close together, reading as one range.",
    "complementary": "Two opposing hues carry the palette for deliberate contrast.",
    "neutral-anchored": "Neutrals dominate, so any colour present reads as accent.",
    "clash": "Several hues sit far apart and compete for attention.",
}

_QUICK_FORMALITY_PHRASES = {
    "consistent": "The pieces agree on formality throughout the look.",
    "mixed": "One piece reads a step more casual than the rest.",
    "split": "The look spans two formality registers at once.",
    "unknown": "There wasn't enough detail to read formality here.",
}

_QUICK_PROPORTION_PHRASES = {
    "cropped_upper_raises_waistline": "The shorter top raises the visual waistline.",
    "long_upper_lowers_waistline": "The longer top lowers the visual waistline.",
    "long_outerwear_over_lower_half": "The outer layer draws one long vertical line.",
    "layered_length_contrast": "The layers finish at different lengths.",
    "narrow_lower_silhouette": "The lower half holds a narrow silhouette.",
    "volume_concentrated_upper": "Volume gathers above the waist.",
    "volume_concentrated_lower": "Volume gathers below the waist.",
}

QUICK_READS_MAX = 4


def build_fallback_feedback(
    signals: Dict[str, Any],
    garments: Sequence[Dict[str, Any]],
    occasion: Optional[str] = None,
    occasion_match: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the §5.5 prose fields from rule signals alone.

    ``occasion_match`` is the already-computed §7.7 meter (see
    ``rules.compute_meters``, called before this in pipeline.py) — passed in
    rather than recomputed so the fallback path and the persisted meter can
    never disagree about the level, only reused to decide *how* to phrase the
    occasion quick-read (§7.7 "sharpen the gap, never suggest a fix").
    """
    colour = signals.get("colour") or {}
    formality = signals.get("formality") or {}
    proportion = signals.get("proportion") or {}

    return {
        "overall_read": _overall_read(formality, garments, occasion),
        "color_note": _colour_note(colour),
        "formality_note": _formality_note(formality),
        "proportion_note": _proportion_note(proportion),
        "garment_notes": _garment_notes(garments),
        "verdict_phrase": _verdict_phrase(formality),
        "verdict_subtitle": _verdict_subtitle(formality),
        "focal_point": _focal_point(formality, proportion, garments),
        "quick_reads": _quick_reads(
            colour, formality, proportion, occasion, occasion_match
        ),
    }


def _verdict_phrase(formality: Dict[str, Any]) -> str:
    mean = formality.get("mean")
    if mean is None:
        return "Hard to place"
    phrase = next(p for ceiling, p in _LEVEL_PHRASES if float(mean) < ceiling)
    return phrase[0].upper() + phrase[1:]


def _verdict_subtitle(formality: Dict[str, Any]) -> str:
    coherence = str(formality.get("coherence") or "unknown")
    return _VERDICT_SUBTITLES.get(coherence, _VERDICT_SUBTITLES["unknown"])


def _focal_point(
    formality: Dict[str, Any],
    proportion: Dict[str, Any],
    garments: Sequence[Dict[str, Any]],
) -> Optional[str]:
    if not garments:
        return None
    category = formality.get("outlier_category") or proportion.get("focal_category")
    if not category:
        return None
    return "Eye lands on the {0}.".format(category)


def _occasion_gap_text(formality: Dict[str, Any], occasion: str) -> Optional[str]:
    """§7.7 "sharpen the gap, never suggest a fix" for a weak occasion_match.

    Prefers the outlier garment already identified for the mixed/split
    coherence read (names an actual piece); falls back to a band-distance
    description when the register is coherent but sits outside the
    occasion's band entirely. Never proposes a replacement — only what
    §7.3/§7.7 already allow: a description of the gap, or a category-norm
    comparison.
    """
    category = formality.get("outlier_category")
    direction = formality.get("outlier_direction")
    if category and direction:
        return "The {0} reads {1} than the rest of the look.".format(
            category, direction
        )

    mean = formality.get("mean")
    band = OCCASION_FORMALITY_BANDS.get(occasion)
    if mean is None or band is None:
        return None
    lo, hi = band
    if mean < lo:
        return "This reads more casual than a typical {0} look.".format(occasion)
    if mean > hi:
        return "This reads more formal than a typical {0} look.".format(occasion)
    return None


def _quick_reads(
    colour: Dict[str, Any],
    formality: Dict[str, Any],
    proportion: Dict[str, Any],
    occasion: Optional[str],
    occasion_match: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    reads: List[Dict[str, str]] = []

    harmony = str(colour.get("harmony_class") or "neutral-anchored")
    reads.append(
        {
            "dimension": "colour",
            "text": _QUICK_COLOUR_PHRASES.get(
                harmony, _QUICK_COLOUR_PHRASES["neutral-anchored"]
            ),
        }
    )

    coherence = str(formality.get("coherence") or "unknown")
    reads.append(
        {
            "dimension": "formality",
            "text": _QUICK_FORMALITY_PHRASES.get(
                coherence, _QUICK_FORMALITY_PHRASES["unknown"]
            ),
        }
    )

    for flag in proportion.get("flags") or []:
        text = _QUICK_PROPORTION_PHRASES.get(flag)
        if text:
            reads.append({"dimension": "proportion", "text": text})
            break  # one proportion read is enough

    if occasion and occasion in _OCCASION_PHRASES and occasion != "other":
        level = (occasion_match or {}).get("level")
        if level in ("partial", "off"):
            # §7.7 "sharpen the gap, never suggest a fix" — a real reason,
            # not the generic "the register holds" positive phrasing below,
            # which would contradict a meter that's reading weak.
            gap_text = _occasion_gap_text(formality, occasion)
            if gap_text:
                reads.append({"dimension": "fit", "text": gap_text})
        elif coherence != "unknown":
            # §7.8 "one verdict only": asserting the register "holds" is
            # itself a confidence claim, so it must not fire when coherence
            # is unknown — that would contradict a verdict_phrase/meters
            # that are hedging in the same breath for the exact same reason
            # (too little formality data).
            reads.append(
                {
                    "dimension": "fit",
                    "text": "For {0}, the register holds.".format(
                        _OCCASION_PHRASES[occasion]
                    ),
                }
            )

    return reads[:QUICK_READS_MAX]


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
