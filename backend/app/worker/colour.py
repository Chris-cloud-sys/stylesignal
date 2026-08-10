"""Perceptual colour extraction and relationships — spec §4.5.

§4.5 asks for dominant colours clustered in **LAB** space, stored as hex + LAB.
Doing this from real pixels (rather than asking the VLM to name colours) is
what makes a read reproducible: the same photo always yields the same palette,
which is the §2.3 promise that competitors' re-scan drift breaks.

Pure stdlib maths + Pillow. No numpy, no scikit-learn.
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

# D65 reference white, 2° observer.
_WHITE_X, _WHITE_Y, _WHITE_Z = 95.047, 100.000, 108.883

# Below this LAB chroma a colour reads as a neutral (black/white/grey/beige)
# rather than as a hue that can clash with anything.
NEUTRAL_CHROMA_THRESHOLD = 14.0

# Hues within this many degrees read as one colour family. Measured against
# real palettes: a set of oranges spans ~22°, so 35° groups them without
# swallowing a genuinely separate hue.
HUE_CLUSTER_THRESHOLD = 35.0

# Two hue clusters at least this far apart read as deliberate opposition. In
# LAB a blue/orange pair measures ~136° and navy/tan ~147°, so the practical
# floor sits well below the 180° an even colour wheel would suggest.
OPPOSITION_THRESHOLD = 100.0

# Above this share of surface area, neutrals are carrying the outfit and any
# hue present reads as an accent rather than as competition.
NEUTRAL_DOMINANCE_THRESHOLD = 0.55


# --- Conversions -----------------------------------------------------------
def hex_to_rgb(value: str) -> Tuple[int, int, int]:
    text = value.lstrip("#").strip()
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError("Not a hex colour: {0!r}".format(value))
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def rgb_to_hex(rgb: Sequence[int]) -> str:
    return "#{0:02X}{1:02X}{2:02X}".format(
        max(0, min(255, int(rgb[0]))),
        max(0, min(255, int(rgb[1]))),
        max(0, min(255, int(rgb[2]))),
    )


def rgb_to_lab(rgb: Sequence[int]) -> Tuple[float, float, float]:
    """sRGB (0-255) to CIE L*a*b* under D65."""

    def _linearise(channel: float) -> float:
        c = channel / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_linearise(float(c)) for c in rgb[:3])

    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) * 100.0
    y = (r * 0.2126729 + g * 0.7151522 + b * 0.0721750) * 100.0
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) * 100.0

    def _f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t) + (16.0 / 116.0)

    fx, fy, fz = _f(x / _WHITE_X), _f(y / _WHITE_Y), _f(z / _WHITE_Z)
    return (
        round((116.0 * fy) - 16.0, 2),
        round(500.0 * (fx - fy), 2),
        round(200.0 * (fy - fz), 2),
    )


def hex_to_lab(value: str) -> Tuple[float, float, float]:
    return rgb_to_lab(hex_to_rgb(value))


def lab_chroma(lab: Sequence[float]) -> float:
    return math.sqrt(lab[1] ** 2 + lab[2] ** 2)


def lab_hue_degrees(lab: Sequence[float]) -> float:
    return math.degrees(math.atan2(lab[2], lab[1])) % 360.0


def delta_e76(lab_a: Sequence[float], lab_b: Sequence[float]) -> float:
    return math.sqrt(sum((lab_a[i] - lab_b[i]) ** 2 for i in range(3)))


def hue_distance(a: float, b: float) -> float:
    """Shortest angular distance between two hues, 0-180."""
    diff = abs(a - b) % 360.0
    return diff if diff <= 180.0 else 360.0 - diff


def is_neutral(lab: Sequence[float]) -> bool:
    return lab_chroma(lab) < NEUTRAL_CHROMA_THRESHOLD


# --- Dominant colour extraction -------------------------------------------
def dominant_colours(
    image: Image.Image,
    bbox: Optional[Dict[str, float]] = None,
    max_colours: int = 3,
    sample_edge: int = 96,
) -> List[Dict[str, object]]:
    """Top ``max_colours`` colours of a region, as ``{hex, lab, weight}``.

    ``bbox`` is normalised 0-1 (§5.4). Colours within a small LAB distance are
    merged so that a lit and a shadowed fold of the same jumper do not occupy
    two slots.
    """
    region = image.convert("RGB")
    if bbox:
        region = _crop_normalised(region, bbox)
    if region.width == 0 or region.height == 0:
        return []

    region.thumbnail((sample_edge, sample_edge), Image.Resampling.LANCZOS)

    # Median-cut into a small palette, then merge perceptually-close entries.
    palette_size = 8
    quantised = region.quantize(colors=palette_size, method=Image.Quantize.MEDIANCUT)
    palette = quantised.getpalette() or []
    counts = quantised.getcolors() or []
    if not counts:
        return []

    total = float(sum(count for count, _ in counts)) or 1.0
    raw: List[Tuple[float, Tuple[int, int, int]]] = []
    for count, index in counts:
        base = index * 3
        if base + 2 >= len(palette):
            continue
        raw.append(
            (count / total, (palette[base], palette[base + 1], palette[base + 2]))
        )
    raw.sort(key=lambda item: item[0], reverse=True)

    merged: List[Dict[str, object]] = []
    for weight, rgb in raw:
        lab = rgb_to_lab(rgb)
        for entry in merged:
            if delta_e76(lab, entry["lab"]) < 12.0:
                entry["weight"] = float(entry["weight"]) + weight
                break
        else:
            merged.append({"hex": rgb_to_hex(rgb), "lab": list(lab), "weight": weight})

    merged.sort(key=lambda entry: float(entry["weight"]), reverse=True)
    top = merged[:max_colours]
    for entry in top:
        entry["weight"] = round(float(entry["weight"]), 4)
    return top


def _crop_normalised(image: Image.Image, bbox: Dict[str, float]) -> Image.Image:
    width, height = image.size
    x = _clamp01(float(bbox.get("x", 0.0)))
    y = _clamp01(float(bbox.get("y", 0.0)))
    w = _clamp01(float(bbox.get("w", 1.0)))
    h = _clamp01(float(bbox.get("h", 1.0)))

    left = int(x * width)
    top = int(y * height)
    right = int(min(1.0, x + w) * width)
    bottom = int(min(1.0, y + h) * height)

    # A degenerate box from the model must not produce a zero-area crop.
    if right - left < 4 or bottom - top < 4:
        return image
    return image.crop((left, top, right, bottom))


def _clamp01(value: float) -> float:
    if value != value:  # NaN
        return 0.0
    return max(0.0, min(1.0, value))


# --- Palette relationships (§4.7 colour harmony) --------------------------
HARMONY_CLASSES = ("analogous", "complementary", "neutral-anchored", "clash")


def classify_harmony(colours: Sequence[Dict[str, object]]) -> Dict[str, object]:
    """Classify a whole-outfit palette into one of the §4.7 harmony classes.

    Returns the class plus the evidence behind it, so feedback can cite a
    reason rather than assert a verdict (§7.4).

    The discriminator is **how the hues cluster**, not how far apart the two
    most distant ones are. That matters because LAB hue angles are not evenly
    spaced: a genuine blue/orange complementary pair measures ~136° apart,
    while three scattered hues (green/magenta/amber) span ~168°. Ranking by
    maximum spread therefore labels the clash "complementary" and the
    complementary pair "clash" — exactly backwards. Two opposed clusters is
    complementary; three or more clusters is a clash.
    """
    entries = []
    for colour in colours:
        lab = colour.get("lab")
        if not lab:
            try:
                lab = list(hex_to_lab(str(colour.get("hex"))))
            except (ValueError, TypeError):
                continue
        weight = float(colour.get("weight", 0.0) or 0.0)
        entries.append({"lab": [float(v) for v in lab], "weight": weight})

    if not entries:
        return {
            "harmony_class": "neutral-anchored",
            "chromatic_count": 0,
            "cluster_count": 0,
            "neutral_weight": 1.0,
            "hue_spread_degrees": 0.0,
            "cluster_separation_degrees": 0.0,
            "max_lightness_contrast": 0.0,
        }

    total_weight = sum(entry["weight"] for entry in entries) or 1.0
    chromatic = [e for e in entries if not is_neutral(e["lab"])]
    neutral_weight = round(
        sum(e["weight"] for e in entries if is_neutral(e["lab"])) / total_weight, 3
    )

    lightnesses = [e["lab"][0] for e in entries]
    lightness_contrast = round(max(lightnesses) - min(lightnesses), 2)

    hues = [lab_hue_degrees(e["lab"]) for e in chromatic]
    spread = _max_pairwise_hue_distance(hues)
    centroids = _cluster_hues(hues)
    separation = _max_pairwise_hue_distance(centroids)

    if not chromatic:
        harmony = "neutral-anchored"
    elif neutral_weight >= NEUTRAL_DOMINANCE_THRESHOLD and len(centroids) <= 1:
        # Neutrals carry the surface area and a single hue accents them.
        harmony = "neutral-anchored"
    elif len(centroids) <= 1:
        harmony = "analogous"
    elif len(centroids) == 2:
        harmony = (
            "complementary" if separation >= OPPOSITION_THRESHOLD else "analogous"
        )
    else:
        harmony = "clash"

    return {
        "harmony_class": harmony,
        "chromatic_count": len(chromatic),
        "cluster_count": len(centroids),
        "neutral_weight": neutral_weight,
        "hue_spread_degrees": round(spread, 1),
        "cluster_separation_degrees": round(separation, 1),
        "max_lightness_contrast": lightness_contrast,
    }


def _cluster_hues(hues: Sequence[float], threshold: float = None) -> List[float]:
    """Group hues that read as "the same colour family"; return their centroids.

    Clustering is on a circle, so the first and last groups are merged when
    they wrap around 0°/360°.
    """
    if not hues:
        return []
    gap = HUE_CLUSTER_THRESHOLD if threshold is None else threshold

    ordered = sorted(hues)
    groups: List[List[float]] = [[ordered[0]]]
    for hue in ordered[1:]:
        if hue - groups[-1][-1] <= gap:
            groups[-1].append(hue)
        else:
            groups.append([hue])

    # Wrap-around: 350° and 5° belong together.
    if len(groups) > 1 and (360.0 - groups[-1][-1]) + groups[0][0] <= gap:
        groups[0] = groups.pop() + groups[0]

    return [_circular_mean(group) for group in groups]


def _circular_mean(hues: Sequence[float]) -> float:
    if len(hues) == 1:
        return hues[0]
    x = sum(math.cos(math.radians(h)) for h in hues)
    y = sum(math.sin(math.radians(h)) for h in hues)
    return math.degrees(math.atan2(y, x)) % 360.0


def _max_pairwise_hue_distance(hues: Sequence[float]) -> float:
    if len(hues) < 2:
        return 0.0
    return max(
        hue_distance(hues[i], hues[j])
        for i in range(len(hues))
        for j in range(i + 1, len(hues))
    )


def describe_contrast(lightness_contrast: float) -> str:
    """Plain-language contrast band, for the templated fallback (§7.6)."""
    if lightness_contrast < 20.0:
        return "low-contrast"
    if lightness_contrast < 45.0:
        return "moderately contrasted"
    return "high-contrast"
