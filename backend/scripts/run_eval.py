"""Run the v1 feedback engine over the eval photo set (docs/StyleSignal-photo-brief.docx).

    python scripts/run_eval.py

Reads every image in evals/photos/, runs it through the same stages the real
pipeline uses (preprocess -> palette -> VLM + lint -> rule signals -> prose),
and writes the results side by side so a human can judge whether the read
lands or reads as evasive. No metric answers that question; this script only
gathers the evidence.

This intentionally does not touch the DB, object storage, or job queue --
those exist to make a scan durable and async in production, and an eval run
is neither. It calls the same worker-stage functions the real pipeline calls.

Costs real API spend: one VLM call per photo (more if a draft fails lint and
regenerates, up to STYLESIGNAL_VLM_MAX_LINT_RETRIES+1 attempts).
"""
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.models import OCCASIONS  # noqa: E402
from app.worker.colour import dominant_colours  # noqa: E402
from app.worker.fallback import build_fallback_feedback  # noqa: E402
from app.worker.pipeline import _normalise_garments  # noqa: E402
from app.worker.preprocess import UndecodableImage, preprocess  # noqa: E402
from app.worker.rules import build_signals  # noqa: E402
from app.worker.vlm import VLMUnavailable, analyse_outfit  # noqa: E402

PHOTOS_DIR = Path(__file__).resolve().parent.parent / "evals" / "photos"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "evals" / "results"


def main() -> int:
    settings = get_settings()
    photos = sorted(
        p for p in PHOTOS_DIR.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")
    )
    if not photos:
        print("No photos found in {0}".format(PHOTOS_DIR))
        return 1

    if settings.vlm_disabled or not settings.anthropic_api_key:
        print(
            "STYLESIGNAL_VLM_DISABLED is true or no API key is set -- every "
            "photo will get the templated §7.6 fallback, not a real read."
        )
        print("Run scripts/check_vlm.py first if that's not what you want.\n")

    print("Running {0} photos through the v1 pipeline (model={1}, effort={2})...\n".format(
        len(photos), settings.vlm_model, settings.vlm_effort
    ))

    results: List[Dict[str, Any]] = []
    for index, path in enumerate(photos, start=1):
        print("[{0}/{1}] {2}".format(index, len(photos), path.name))
        started = time.monotonic()
        try:
            result = _run_one(path)
        except Exception as exc:  # noqa: BLE001 - eval script, record and move on
            result = {"file": path.name, "error": "{0}: {1}".format(type(exc).__name__, exc)}
            print("    ERROR: {0}".format(result["error"]))
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        results.append(result)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = RESULTS_DIR / "eval_{0}.json".format(stamp)
    md_path = RESULTS_DIR / "eval_{0}.md".format(stamp)

    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(results, settings), encoding="utf-8")

    n_fallback = sum(1 for r in results if r.get("vlm_used") is False)
    n_failed = sum(1 for r in results if r.get("failure_reason"))
    n_errored = sum(1 for r in results if r.get("error"))
    print("\nDone. {0} photos, {1} fallback, {2} typed failure, {3} script error.".format(
        len(results), n_fallback, n_failed, n_errored
    ))
    print("JSON:     {0}".format(json_path))
    print("Markdown: {0}".format(md_path))
    return 0


def _run_one(path: Path) -> Dict[str, Any]:
    occasion = _occasion_from_filename(path.name)

    original = path.read_bytes()
    try:
        prepared = preprocess(original)
    except UndecodableImage as exc:
        return {"file": path.name, "occasion": occasion, "failure_reason": "undecodable: {0}".format(exc)}

    outfit_palette = dominant_colours(prepared.working_image, bbox=None, max_colours=5)

    analysis: Optional[Dict[str, Any]] = None
    vlm_meta: Dict[str, Any] = {"used": False}
    try:
        result = analyse_outfit(
            working_jpeg=prepared.working_bytes,
            measured_palette=outfit_palette,
            occasion=occasion,
            context_note=None,
            rule_signals=None,
        )
        analysis = result.payload
        vlm_meta = {
            "used": True,
            "model": result.model,
            "lint_attempts": result.lint_attempts,
            "lint_violations": result.lint_violations,
            "usage": result.usage,
        }
    except VLMUnavailable as exc:
        vlm_meta = {"used": False, "reason": str(exc)}

    detected = _normalise_garments(analysis)

    if analysis is not None and not detected:
        person_present = bool(analysis.get("person_present"))
        return {
            "file": path.name,
            "occasion": occasion,
            "vlm_used": True,
            "vlm": vlm_meta,
            "failure_reason": "no_person" if not person_present else "no_garments_detected",
        }

    garment_dicts = []
    for item in detected:
        colours = dominant_colours(prepared.working_image, bbox=item["bbox"], max_colours=3)
        garment_dicts.append(
            {
                "id": item["index"],
                "category": item["category"],
                "bbox": item["bbox"],
                "colors": colours,
                "pattern": item["pattern"],
                "formality": item["formality"],
                "attributes": item["attributes"],
            }
        )

    signals = build_signals(garment_dicts, outfit_palette, occasion)
    signals["vlm"] = vlm_meta

    if analysis is not None:
        prose = _prose_from_analysis(analysis, garment_dicts)
    else:
        prose = build_fallback_feedback(signals, garment_dicts, occasion)

    return {
        "file": path.name,
        "occasion": occasion,
        "vlm_used": vlm_meta.get("used", False),
        "vlm": vlm_meta,
        "garments": [
            {
                "category": g["category"],
                "pattern": g["pattern"],
                "formality": g["formality"],
                "colors": g["colors"],
                "descriptor": g["attributes"].get("descriptor"),
            }
            for g in garment_dicts
        ],
        "signals": {
            "colour_harmony": signals["colour"].get("harmony_class"),
            "contrast_band": signals["colour"].get("contrast_band"),
            "formality_coherence": signals["formality"].get("coherence"),
            "proportion_flags": signals["proportion"].get("flags"),
        },
        "feedback": prose,
    }


def _prose_from_analysis(analysis: Dict[str, Any], garment_dicts: List[Dict[str, Any]]) -> Dict[str, Any]:
    notes: List[Dict[str, Any]] = []
    for note in analysis.get("garment_notes") or []:
        if not isinstance(note, dict):
            continue
        try:
            gi = int(note.get("garment_index"))
        except (TypeError, ValueError):
            continue
        if 0 <= gi < len(garment_dicts):
            notes.append({"garment": garment_dicts[gi]["category"], "note": str(note.get("note") or "")})

    proportion = (analysis.get("proportion_note") or "").strip()
    return {
        "overall_read": str(analysis.get("overall_read") or "").strip(),
        "color_note": str(analysis.get("color_note") or "").strip(),
        "formality_note": str(analysis.get("formality_note") or "").strip(),
        "proportion_note": proportion or None,
        "garment_notes": notes,
    }


def _occasion_from_filename(name: str) -> Optional[str]:
    prefix = name.split("__", 1)[0].strip().lower()
    if prefix == "none":
        return None
    if prefix in OCCASIONS:
        return prefix
    return None


def _render_markdown(results: List[Dict[str, Any]], settings) -> str:
    lines = [
        "# StyleSignal eval run",
        "",
        "Model: `{0}`  Effort: `{1}`  {2} photos".format(
            settings.vlm_model, settings.vlm_effort, len(results)
        ),
        "",
        "Judge this by one question: does the read land, or does it slip into",
        "evasive hedging? Read each entry next to the actual photo in",
        "`evals/photos/`.",
        "",
        "---",
        "",
    ]

    for r in results:
        lines.append("## {0}".format(r.get("file", "?")))
        lines.append("")

        if r.get("error"):
            lines.append("**Script error:** {0}".format(r["error"]))
            lines.append("")
            lines.append("---")
            lines.append("")
            continue

        occasion = r.get("occasion") or "none"
        lines.append("Occasion: `{0}`".format(occasion))

        if r.get("failure_reason"):
            lines.append("")
            lines.append("**Result: failed cleanly with `{0}`**".format(r["failure_reason"]))
            lines.append("")
            lines.append("---")
            lines.append("")
            continue

        vlm = r.get("vlm", {})
        if vlm.get("used"):
            note = "VLM read (model={0}, lint attempts={1})".format(
                vlm.get("model", "?"), vlm.get("lint_attempts", "?")
            )
            if vlm.get("lint_violations"):
                note += " -- {0} lint violation(s) before it passed".format(len(vlm["lint_violations"]))
        else:
            note = "Templated §7.6 fallback ({0})".format(vlm.get("reason", "VLM unavailable"))
        lines.append(note)
        lines.append("")

        garments = r.get("garments") or []
        if garments:
            lines.append("**Detected garments:**")
            for g in garments:
                colour = g["colors"][0]["hex"] if g.get("colors") else "?"
                lines.append(
                    "- {0} -- {1}, {2}, formality {3:.2f}, lead colour {4}".format(
                        g["category"], g.get("descriptor") or "", g["pattern"], g["formality"], colour
                    )
                )
        else:
            lines.append("**Detected garments:** none")
        lines.append("")

        signals = r.get("signals") or {}
        lines.append(
            "Signals: harmony=`{0}` contrast=`{1}` formality=`{2}` proportion_flags=`{3}`".format(
                signals.get("colour_harmony"),
                signals.get("contrast_band"),
                signals.get("formality_coherence"),
                signals.get("proportion_flags"),
            )
        )
        lines.append("")

        feedback = r.get("feedback") or {}
        lines.append("**Overall read:** {0}".format(feedback.get("overall_read", "")))
        lines.append("")
        lines.append("**Colour:** {0}".format(feedback.get("color_note", "")))
        lines.append("")
        lines.append("**Formality:** {0}".format(feedback.get("formality_note", "")))
        lines.append("")
        proportion_note = feedback.get("proportion_note")
        lines.append("**Proportion:** {0}".format(proportion_note if proportion_note else "(empty)"))
        lines.append("")
        garment_notes = feedback.get("garment_notes") or []
        if garment_notes:
            lines.append("**Per-garment notes:**")
            for gn in garment_notes:
                label = gn.get("garment", gn.get("garment_id", "?"))
                lines.append("- {0}: {1}".format(label, gn.get("note", "")))
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
