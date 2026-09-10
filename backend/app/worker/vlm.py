"""VLM stage — spec §4.7 and the §7.5 prompt contract.

In v1 a **single** Claude call does detection, attribute estimation and
descriptive feedback in one shot (§9). The call receives:

* the working image
* the measured whole-outfit LAB palette (§4.5 — real pixels, not a guess)
* any computed rule signals (§4.7)
* the stated occasion

and must return the ``outfit_feedback`` fields of §5.5. Output shape is
guaranteed by a JSON schema; output *voice* is guaranteed by the system prompt
plus the lint-and-regenerate loop below (§7.5).
"""
import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..models import GARMENT_CATEGORIES, PATTERNS
from .lint import LintReport, lint_feedback

logger = logging.getLogger("stylesignal.worker.vlm")

settings = get_settings()


class VLMUnavailable(Exception):
    """Raised when the model cannot be reached, refuses, or never passes lint.

    The caller falls back to templated text (§7.6) rather than failing the scan.
    """


# --- Output contract (§5.5) ------------------------------------------------
_BBOX_SCHEMA = {
    "type": "object",
    "description": "Normalised 0-1 box around the garment.",
    "properties": {
        "x": {"type": "number", "description": "Left edge, 0-1."},
        "y": {"type": "number", "description": "Top edge, 0-1."},
        "w": {"type": "number", "description": "Width, 0-1."},
        "h": {"type": "number", "description": "Height, 0-1."},
    },
    "required": ["x", "y", "w", "h"],
    "additionalProperties": False,
}

_GARMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "index": {
            "type": "integer",
            "description": "Zero-based position in this array. Used to link notes.",
        },
        "category": {"type": "string", "enum": list(GARMENT_CATEGORIES)},
        "bbox": _BBOX_SCHEMA,
        "pattern": {"type": "string", "enum": list(PATTERNS)},
        "formality": {
            "type": "number",
            "description": (
                "0.0 = fully casual (sweatpants, flip-flops), "
                "1.0 = fully formal (dinner jacket, oxfords)."
            ),
        },
        "material_guess": {
            "type": "string",
            "description": "Best guess, or 'unknown'. Low confidence is fine.",
        },
        "material_confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "colour_names": {
            "type": "array",
            "description": "Plain-language colour names, most dominant first.",
            "items": {"type": "string"},
        },
        "descriptor": {
            "type": "string",
            "description": "Short neutral identifier, e.g. 'navy wool blazer'.",
        },
    },
    "required": [
        "index",
        "category",
        "bbox",
        "pattern",
        "formality",
        "material_guess",
        "material_confidence",
        "colour_names",
        "descriptor",
    ],
    "additionalProperties": False,
}

_QUICK_READ_DIMENSIONS = (
    "colour",
    "formality",
    "proportion",
    "pattern",
    "texture",
    "fit",
)

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "person_present": {
            "type": "boolean",
            "description": "Is a person wearing the clothes visible?",
        },
        "garments": {"type": "array", "items": _GARMENT_SCHEMA},
        "overall_read": {
            "type": "string",
            "description": (
                "One paragraph on the signal the outfit sends, grounded in the "
                "detected garments."
            ),
        },
        "color_note": {"type": "string"},
        "formality_note": {"type": "string"},
        "proportion_note": {
            "type": "string",
            "description": "Empty string if the framing does not support a read.",
        },
        "garment_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "garment_index": {"type": "integer"},
                    "note": {"type": "string"},
                },
                "required": ["garment_index", "note"],
                "additionalProperties": False,
            },
        },
        # --- §7.7 glanceable result screen ---------------------------------
        "verdict_phrase": {
            "type": "string",
            "description": "Five words or fewer. The single loudest signal.",
        },
        "verdict_subtitle": {
            "type": "string",
            "description": (
                "Eight words or fewer. A second, different observation — "
                "not a restatement of verdict_phrase."
            ),
        },
        "focal_point": {
            "type": "string",
            "description": (
                "Twelve words or fewer, one clause. Where attention lands "
                "first in the photograph, and what puts it there. A garment "
                "or a relationship between garments — never the face, hair, "
                "skin, or body."
            ),
        },
        "quick_reads": {
            "type": "array",
            # No minItems/maxItems: Claude's structured-output schema support
            # only allows 0 or 1 there ("minItems values other than 0 or 1
            # are not supported" — a real 400 from every live call until
            # this was caught). Count is enforced by the system prompt
            # ("three or four short bullets") and by _prose_from_analysis's
            # [:4] cap in pipeline.py, not by the schema.
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": list(_QUICK_READ_DIMENSIONS)},
                    "text": {
                        "type": "string",
                        "description": "Fifteen words or fewer, exactly one sentence.",
                    },
                },
                "required": ["dimension", "text"],
                "additionalProperties": False,
            },
        },
        "elevate_suggestion": {
            "type": "string",
            "description": (
                "Fourteen words or fewer, one concrete addition or swap "
                "grounded in this photo — the one deliberate exception to "
                "the no-prescription rule. Empty string if the look is "
                "already complete with nothing worth naming."
            ),
        },
    },
    "required": [
        "person_present",
        "garments",
        "overall_read",
        "color_note",
        "formality_note",
        "proportion_note",
        "garment_notes",
        "verdict_phrase",
        "verdict_subtitle",
        "focal_point",
        "quick_reads",
        "elevate_suggestion",
    ],
    "additionalProperties": False,
}


# --- System prompt (§7.1-§7.4) --------------------------------------------
# Stable across every request so it caches cleanly. Nothing per-request goes in
# here — see docs/prompting.md.
SYSTEM_PROMPT = """\
You are the feedback engine for StyleSignal. You describe how an outfit reads. \
You are not a stylist giving advice and not a judge awarding marks.

# What you produce
For one photograph of an outfit you return: the garments you can identify, and \
a descriptive read of how they combine — colour relationships, formality \
coherence, proportion and line, and the overall signal the look sends.

# The voice: descriptive, never prescriptive or evaluative
Describe what the garments do and how they interact. The reader decides what, \
if anything, to change. Your job is to make the situation legible, not to \
resolve it.

Every observation must carry its own lever: name the tension AND its cause, so \
the reader can act without being told to. Write "the sneakers sit a step more \
casual than the tailoring above them", not "the outfit is inconsistent" and \
not "swap the sneakers for loafers". The first sentence tells the reader \
exactly what is happening and why; what they do about it is theirs.

## Allowed
- Colour relationships: "the palette stays in a warm, low-contrast range".
- Formality coherence: "the pieces largely agree on formality; the footwear \
reads more casual than the rest".
- Proportion and line: "the cropped jacket raises the waistline visually".
- The overall signal: "reads as relaxed weekend", "polished smart-casual", \
"evening-formal".
- Tying a read to the stated occasion: "for a work context, this reads \
appropriately put-together".

## When the occasion match is weak
Judge this from the same formality signals and stated occasion you already \
have — you do not see the computed occasion_match meter, but you can tell \
when the register runs noticeably more casual or more formal than the \
occasion calls for. When it does, sharpen the gap instead of staying vague: \
name the specific thing driving it (an outlier garment, or the register as a \
whole) and how it diverges — "this reads two steps more casual than a \
typical evening look" or "the sneakers sit a full register below the rest \
of the outfit". A comparative line naming the category norm is fine \
("evening looks in this range tend to sit in darker, less casual \
footwear"). What is never acceptable, here more than anywhere else in this \
contract, is turning that gap into a suggested fix — "try loafers instead" \
is exactly the prescriptive move rule 1 below forbids, and a weak match is \
not license to make it. Put this in formality_note or the relevant \
quick_reads item, whichever already carries the formality observation.

## Forbidden — these are hard rules, not preferences
1. NO PRESCRIPTION. Never "you should", "swap the", "add a", "try", \
"consider", "opt for", "I'd recommend", "would look better", "needs a", \
"wear X instead", "next time". Do not issue an instruction in any form, \
including softened ones.
2. NO EVALUATION OF THE PERSON. Never mention the wearer's body, figure, \
height, weight, attractiveness or worth. Never "flattering", "slimming", \
"suits you", "you look". Only the clothes and their relationships are in scope.
3. NO NUMERIC SCORES in anything the reader sees. You receive numeric signals; \
you never repeat them as numbers. Translate them into language.
4. NO NEGATIVE ABSOLUTES. Nothing is bad, wrong, ugly, awful or a mistake, and \
nothing "doesn't work". Reframe as a neutral observation of a tension: "the \
two patterns compete for attention".

# Grounding
Every claim must trace to something visible in the photograph or present in the \
measured signals you are given. The measured palette is extracted from the \
actual pixels — trust it over your own impression when they disagree, and \
describe the colours it reports. If the framing is too tight or too dark to \
support a proportion read, return an empty proportion_note rather than \
inventing one. Prefer "the trousers read as a mid-tone brown" to a confident \
claim about fabric you cannot see.

# Registering that nothing is there
If no person and no wearable garments are visible, set person_present \
correctly and return an empty garments array. Do not invent an outfit.

# Style
Neutral, specific, unhurried. Second person is fine for the outfit ("your \
jacket"), never for the body. Sentence case. No emoji, no exclamation marks, \
no headings inside the fields. Two to four sentences per note; overall_read may \
run to five.

# The glanceable read
Alongside the fields above, you also produce a five-second read — most users \
never scroll to the long-form fields at all, so this is where the product's \
first impression actually lives:
- verdict_phrase: five words or fewer. The single loudest signal.
- verdict_subtitle: eight words or fewer. A second, genuinely different \
observation — never a restatement of verdict_phrase in other words.
- focal_point: twelve words or fewer, one clause. Where attention lands \
first in the photograph, and what puts it there. Always a garment or a \
relationship between garments — never the face, hair, skin, or body. \
StyleSignal reads the outfit, not the person wearing it, and that holds \
here exactly as strictly as it does everywhere else in this contract.
- quick_reads: three or four short bullets, each tagged with a dimension \
(colour, formality, proportion, pattern, texture, or fit). Exactly one \
sentence, fifteen words or fewer, no exceptions.

These four obey every rule above — no prescription, no evaluation of the \
person, no numbers, no negative absolutes. Two more rules specific to them: \
first, do not repeat overall_read verbatim, only shorter — say something \
overall_read does not. Second, do not make a global "this all matches" or \
"this is coherent" claim — that judgment is rendered elsewhere on the screen \
as a separate signal you do not see, so a global claim from you risks \
contradicting it. Your job in these four fields is to name specific, visible \
things, not to summarise the whole look into a verdict on top of a verdict.

# The one exception: elevate_suggestion
Rule 1 (no prescription) governs every field above without exception. \
elevate_suggestion is the sole deliberate carve-out, and it stays narrow: \
one concrete addition or swap, grounded in what is actually visible, framed \
as an opportunity rather than an instruction — "a structured jacket in navy \
would extend the formality range upward" rather than "you should add a \
blazer" or "try a blazer instead". Fourteen words or fewer, exactly one \
sentence. It still obeys rules 2 through 4 — nothing about the wearer, no \
numbers, no negative absolutes about the current look while you describe \
the addition. If the look is already complete and nothing is worth adding \
or swapping, return an empty string; do not manufacture a suggestion to \
fill the field.
"""


@dataclass
class VLMResult:
    payload: Dict[str, Any]
    lint_attempts: int = 0
    lint_violations: List[Dict[str, str]] = field(default_factory=list)
    model: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)


# --- Client ----------------------------------------------------------------
_client = None
_supports_server_fallback = True


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.vlm_timeout_seconds,
            # The SDK's own internal retry-on-failure (default max_retries=2)
            # was multiplying silently underneath our own lint-and-regenerate
            # loop — each of *our* attempts could itself balloon into up to
            # 3 real HTTP calls, pushing real-world worst case past 10
            # minutes despite vlm_timeout_seconds x max_attempts suggesting
            # ~360s. We already have our own retry logic at this level;
            # zero out the SDK's so one of our attempts is one HTTP call.
            max_retries=0,
        )
    return _client


def analyse_outfit(
    working_jpeg: bytes,
    measured_palette: List[Dict[str, Any]],
    occasion: Optional[str],
    context_note: Optional[str],
    capture_mode: str = "worn",
    rule_signals: Optional[Dict[str, Any]] = None,
    effort: Optional[str] = None,
    max_lint_retries: Optional[int] = None,
) -> VLMResult:
    """Run the §7.5 call, then lint-and-regenerate until it complies.

    ``effort`` and ``max_lint_retries`` are overridable so a Pro user past the
    soft fair-use ceiling degrades gracefully instead of being refused (§1).

    Raises :class:`VLMUnavailable` if the model is off, refuses, errors, or
    never produces compliant copy — the caller then uses the §7.6 fallback.
    """
    if not settings.vlm_enabled:
        raise VLMUnavailable("VLM disabled or ANTHROPIC_API_KEY not set")

    import anthropic

    client = _get_client()
    messages: List[Dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.standard_b64encode(working_jpeg).decode(
                            "ascii"
                        ),
                    },
                },
                {
                    "type": "text",
                    "text": _build_user_prompt(
                        measured_palette,
                        occasion,
                        context_note,
                        rule_signals,
                        capture_mode,
                    ),
                },
            ],
        }
    ]

    all_violations: List[Dict[str, str]] = []
    attempts = 0
    retries = (
        settings.vlm_max_lint_retries
        if max_lint_retries is None
        else max_lint_retries
    )
    max_attempts = max(1, retries + 1)
    chosen_effort = effort or settings.vlm_effort

    while attempts < max_attempts:
        attempts += 1
        try:
            response = _create(client, messages, chosen_effort)
        except anthropic.APIStatusError as exc:
            raise VLMUnavailable(
                "Claude API error {0}: {1}".format(exc.status_code, exc.message)
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise VLMUnavailable("Could not reach the Claude API") from exc

        # Safety classifiers can decline; content is then empty or partial.
        if response.stop_reason == "refusal":
            category = getattr(
                getattr(response, "stop_details", None), "category", None
            )
            raise VLMUnavailable(
                "Request was declined by safety classifiers "
                "(category={0})".format(category)
            )
        if response.stop_reason == "max_tokens":
            raise VLMUnavailable("Response truncated; raise STYLESIGNAL_VLM_MAX_TOKENS")

        payload = _extract_json(response)
        if payload is None:
            raise VLMUnavailable("Model returned no parseable JSON block")

        report: LintReport = lint_feedback(payload)
        if report.ok:
            return VLMResult(
                payload=payload,
                lint_attempts=attempts,
                lint_violations=all_violations,
                model=getattr(response, "model", settings.vlm_model),
                usage=_usage_dict(response),
            )

        all_violations.extend(v.as_dict() for v in report.violations)
        logger.info(
            "lint rejected VLM draft (attempt %s/%s): %s",
            attempts,
            max_attempts,
            report.rules_broken,
        )
        if attempts >= max_attempts:
            break

        # Echo the assistant turn back unchanged (thinking blocks included) and
        # append the correction as a normal user turn.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": report.correction_prompt()})

    raise VLMUnavailable(
        "Draft never passed the descriptive lint after {0} attempt(s)".format(attempts)
    )


def _create(client, messages: List[Dict[str, Any]], effort: str):
    """One Messages call with structured output + refusal fallback."""
    global _supports_server_fallback

    kwargs: Dict[str, Any] = {
        "model": settings.vlm_model,
        "max_tokens": settings.vlm_max_tokens,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                # Stable prefix — pay the write once, read it on every scan (§8).
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": messages,
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA},
        },
    }

    if _supports_server_fallback:
        try:
            return client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                **kwargs
            )
        except TypeError:
            # SDK predates the parameter — degrade to the plain endpoint and
            # stop trying for the life of the process.
            logger.warning(
                "installed anthropic SDK does not support server-side "
                "fallbacks; continuing without them"
            )
            _supports_server_fallback = False

    return client.messages.create(**kwargs)


def _build_user_prompt(
    measured_palette: List[Dict[str, Any]],
    occasion: Optional[str],
    context_note: Optional[str],
    rule_signals: Optional[Dict[str, Any]],
    capture_mode: str = "worn",
) -> str:
    item_mode = capture_mode == "item"
    lines = [
        "Analyse the item(s) in this photograph."
        if item_mode
        else "Analyse the outfit in this photograph.",
        "",
        "## Measured signals",
        "These were computed from the actual pixels and from geometry, not "
        "estimated. Treat them as ground truth and describe them in language; "
        "never quote a number back to the reader.",
        "",
        "Whole-image dominant palette (LAB, most dominant first):",
        json.dumps(measured_palette, indent=2),
    ]

    if rule_signals:
        lines.extend(
            [
                "",
                "Derived rule signals:",
                json.dumps(rule_signals, indent=2),
            ]
        )

    if item_mode:
        lines.extend(
            [
                "",
                "## Capture mode: item, not worn",
                "This is a photo of a garment or garments on their own — a "
                "store listing, an online product shot, a flat lay, a "
                "hanger, a mannequin. Not a person wearing them. This is "
                "expected: set person_present to whatever is actually true "
                "(almost always false here) and do not treat its absence as "
                "a problem. Describe the piece(s) as objects, not as worn: "
                'write "this jacket" or "the two pieces", never "your '
                'jacket" or second-person wearer language, and never claim '
                "how it would drape, fit, or land on a body you cannot see. "
                "Skip proportion and line commentary — waistline, hemline "
                "and silhouette claims only make sense on a body — but "
                "colour, pattern, formality and how multiple pieces "
                "coordinate all still apply exactly as they do for a worn "
                "photo.",
            ]
        )

    lines.extend(["", "## Context"])
    if occasion:
        lines.append(
            'Stated occasion: "{0}". Tie at least one observation to it.'.format(
                occasion
            )
        )
    else:
        lines.append(
            "No occasion was given. Do not guess one — describe the signal the "
            "outfit sends on its own terms."
        )

    if context_note:
        note_source = "They" if item_mode else "The wearer"
        lines.append(
            '{0} added: "{1}". Use it as context for what matters to them; '
            "do not answer it as a question and do not give advice.".format(
                note_source, context_note.replace('"', "'")
            )
        )

    lines.extend(
        [
            "",
            "## Output",
            "Return the structured result. Every garment you list needs a bbox "
            "you can actually see, and every entry in garment_notes must "
            "reference a garment_index that exists in your garments array.",
        ]
    )
    return "\n".join(lines)


def _extract_json(response) -> Optional[Dict[str, Any]]:
    """Structured outputs put valid JSON in the first text block."""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            try:
                parsed = json.loads(block.text)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _usage_dict(response) -> Dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        key: getattr(usage, key, None)
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
        if getattr(usage, key, None) is not None
    }
