"""Descriptive-feedback lint pass — spec §7.3 / §7.5.

This module is the enforcement point for the product's voice. §9 calls for it
"from day one — it's cheap and defines the product voice", and §2.5 warns that
descriptive done badly is worse than a score. So the rules below are strict
about the four forbidden categories and deliberately permissive about
everything else: a false rejection costs one regeneration, a false accept ships
prescriptive copy.

Usage::

    report = lint_feedback(candidate)
    if not report.ok:
        # regenerate with report.correction_prompt(), or fall back to §7.6
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Pattern, Tuple

# Fields of ``outfit_feedback`` (§5.5) that are user-visible prose.
# NOTE: elevate_suggestion is NOT here — it gets every rule below except
# RULE_PRESCRIPTION (see the dedicated block in lint_feedback and
# docs/spec-deviations.md). It is the one deliberate, bounded exception to
# the no-prescription rule anywhere in this contract; every other field
# stays fully prescription-free.
LINTED_FIELDS = (
    "overall_read",
    "color_note",
    "formality_note",
    "proportion_note",
    # §7.7 glanceable fields — same voice rules apply to the five-second
    # read as to the long-form one.
    "verdict_phrase",
    "verdict_subtitle",
    "focal_point",
)

RULE_PRESCRIPTION = "prescription"
RULE_PERSON_EVALUATION = "person_evaluation"
RULE_NUMERIC_SCORE = "numeric_score"
RULE_NEGATIVE_ABSOLUTE = "negative_absolute"
RULE_PROPORTION_HEDGE = "proportion_hedge"
RULE_WORD_LIMIT = "word_limit"
RULE_MULTI_SENTENCE = "multi_sentence"

# §7.7 copy limits. quick_reads text is checked separately (its limit is
# per-item, not per-field) — see the ``quick_reads`` loop in lint_feedback.
WORD_LIMITS = {
    "verdict_phrase": 5,
    "verdict_subtitle": 8,
    "focal_point": 12,
}
QUICK_READ_WORD_LIMIT = 15
ELEVATE_SUGGESTION_WORD_LIMIT = 14

RULE_EXPLANATIONS = {
    RULE_PRESCRIPTION: (
        "Do not tell the wearer what to do or what to change. Describe what the "
        "garments do and let the reader draw the conclusion."
    ),
    RULE_PERSON_EVALUATION: (
        "Never comment on the wearer's body, appearance or worth. Only the "
        "clothes and how they combine are in scope."
    ),
    RULE_NUMERIC_SCORE: (
        "Never surface a numeric score or rating. The output is language."
    ),
    RULE_NEGATIVE_ABSOLUTE: (
        "Do not call anything bad, wrong or ugly. Reframe as a neutral "
        "observation of a tension, e.g. 'the two patterns compete for attention'."
    ),
    RULE_PROPORTION_HEDGE: (
        "proportion_note must be an empty string when the framing does not "
        "support a proportion read. Do not explain that it cannot be assessed "
        "— just return an empty string for this field."
    ),
    RULE_WORD_LIMIT: (
        "This field has a hard word-count limit for the glanceable result "
        "screen (§7.7). Cut it down to fit — say less, not the same thing "
        "in fewer words with ellipses or abbreviations."
    ),
    RULE_MULTI_SENTENCE: (
        "This field must be exactly one sentence. Pick the single strongest "
        "observation and drop the rest, rather than joining two observations "
        "with a comma or semicolon."
    ),
}


def _compile(patterns: List[str]) -> List[Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


# §7.3 "Prescription: no 'you should', 'swap the', 'add a', 'wear X instead'."
_PRESCRIPTION_PATTERNS = _compile(
    [
        r"\byou\s+(?:should|could|might want|need to|ought|may want|want to)\b",
        r"\b(?:i'?d|i\s+would|we'?d|we\s+would)\s+(?:suggest|recommend|go|opt|swap)\b",
        r"\brecommend\w*\b",
        r"\bsuggest\b",                       # 'suggests' stays legal
        r"\bswap(?:ping|ped)?\b",
        r"\bswitch(?:ing|ed)?\s+(?:out|to|the)\b",
        r"\badd(?:ing)?\s+(?:a|an|some|more)\b",
        r"\bremov(?:e|ing)\s+the\b",
        r"\blose\s+the\b",
        r"\bditch\s+the\b",
        r"\btry\b",
        r"\bconsider\b",                      # 'considered' stays legal
        r"\bopt\s+for\b",
        r"\bgo\s+(?:with|for)\b",
        r"\bstick\s+(?:to|with)\b",
        r"\bpair\s+(?:it|them|this|these)\s+with\b",
        r"\b(?:wear|choose|pick|use|style)\b[^.!?]{0,40}\binstead\b",
        r"\bwould\s+(?:look|work|read|sit|feel)\s+better\b",
        r"\bnext\s+time\b",
        r"\bavoid\b",
        r"\bneeds?\s+(?:a|an|some|more|less)\b",
        r"\bcall(?:s)?\s+for\s+(?:a|an)\b",
        r"\bif\s+you\s+(?:want|wanted|prefer)\b",
        r"\bto\s+(?:dress|dial)\s+(?:it|this)\s+(?:up|down)\b",
    ]
)

# §7.3 "Evaluation of the person: never comment on the wearer's body,
# attractiveness, or worth."
_PERSON_EVALUATION_PATTERNS = _compile(
    [
        r"\bflatter(?:s|ing|ed)?\b",
        r"\bunflattering\b",
        r"\bslimming\b",
        r"\byour\s+(?:body|figure|frame|build|shape|skin|complexion|legs|waist|hips|face)\b",
        r"\byour\s+(?:height|weight|proportions)\b",
        r"\byou\s+look\b",
        r"\bsuits?\s+you\b",
        r"\b(?:attractive|beautiful|gorgeous|handsome|pretty|stunning|sexy)\b",
        r"\bgood\s+on\s+you\b",
        r"\bbody\s+type\b",
    ]
)

# §7.3 "Numeric outfit scores shown to the user."
_NUMERIC_SCORE_PATTERNS = _compile(
    [
        r"\b\d{1,3}\s*/\s*(?:5|10|100)\b",
        r"\b\d{1,3}\s+out\s+of\s+(?:five|ten|5|10|100)\b",
        r"\bscores?\s+(?:a\s+)?\d",
        r"\b(?:score|rating|grade)\s+of\b",
        r"\brate[sd]?\s+(?:it\s+)?(?:a\s+)?\d",
        r"\b\d{1,3}\s*(?:%|percent)\s+(?:coherent|formal|cohesive)\b",
    ]
)

# §7.3 "Negative absolutes: avoid 'this is bad/wrong/ugly'."
_NEGATIVE_ABSOLUTE_PATTERNS = _compile(
    [
        r"\b(?:is|are|looks?|reads?|feels?)\s+(?:just\s+|really\s+|very\s+)?"
        r"(?:bad|wrong|ugly|awful|terrible|hideous|tacky|cheap|dreadful|poor)\b",
        r"\b(?:doesn'?t|does\s+not|don'?t|do\s+not)\s+work\b",
        r"\bnever\s+works\b",
        r"\ba\s+mistake\b",
        r"\bclashes?\s+(?:badly|horribly|awfully)\b",
        r"\b(?:fails?|failing)\s+to\b",
        r"\bmess\b",
        r"\bshouldn'?t\s+be\b",
    ]
)

# A non-empty ``proportion_note`` that explains why proportion *can't* be read
# is still an invented field per §7.4 — the contract wants an empty string,
# not a sentence about the limitation. Checked only against proportion_note,
# never the other fields, so it lives outside ``_RULES`` below.
_PROPORTION_HEDGE_PATTERNS = _compile(
    [
        r"\bcan(?:not|'t)\s+be\s+(?:assessed|read|determined|evaluated)\b",
        r"\bcannot\s+be\s+(?:assessed|read|determined|evaluated)\b",
        r"\b(?:is|are|stays?|remains?)\s+(?:outside|out)\s+(?:of\s+)?(?:the\s+)?"
        r"(?:frame|photo|image|shot)\b",
        r"\bnot\s+(?:visible|shown|in\s+frame|in\s+view)\b",
        r"\b(?:frame|framing|photo|image|crop)\s+(?:cuts?\s+off|crops?|does\s+"
        r"not\s+support|doesn'?t\s+support)\b",
        r"\bcannot\s+be\s+supported\b",
        r"\b(?:can'?t|cannot)\s+tell\b",
        r"\bhard\s+to\s+(?:assess|read|tell)\s+(?:here|from\s+this)\b",
    ]
)

_RULES: List[Tuple[str, List[Pattern]]] = [
    (RULE_PRESCRIPTION, _PRESCRIPTION_PATTERNS),
    (RULE_PERSON_EVALUATION, _PERSON_EVALUATION_PATTERNS),
    (RULE_NUMERIC_SCORE, _NUMERIC_SCORE_PATTERNS),
    (RULE_NEGATIVE_ABSOLUTE, _NEGATIVE_ABSOLUTE_PATTERNS),
]

# elevate_suggestion's rule set, deliberately missing RULE_PRESCRIPTION —
# the whole point of the field is to name one concrete addition or swap, so
# "a structured blazer would..." can't be flagged as an instruction here the
# way it would be everywhere else. Still fully bound by the other three: no
# comment on the wearer, no number, no negative absolute.
_ELEVATE_SUGGESTION_RULES: List[Tuple[str, List[Pattern]]] = [
    (RULE_PERSON_EVALUATION, _PERSON_EVALUATION_PATTERNS),
    (RULE_NUMERIC_SCORE, _NUMERIC_SCORE_PATTERNS),
    (RULE_NEGATIVE_ABSOLUTE, _NEGATIVE_ABSOLUTE_PATTERNS),
]


@dataclass
class Violation:
    rule: str
    phrase: str
    field: str

    def as_dict(self) -> Dict[str, str]:
        return {"rule": self.rule, "phrase": self.phrase, "field": self.field}


@dataclass
class LintReport:
    violations: List[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def rules_broken(self) -> List[str]:
        seen: List[str] = []
        for violation in self.violations:
            if violation.rule not in seen:
                seen.append(violation.rule)
        return seen

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "violations": [v.as_dict() for v in self.violations],
        }

    def correction_prompt(self) -> str:
        """A corrective turn for the regenerate loop (§7.5)."""
        lines = [
            "The previous draft broke the descriptive-feedback rules. "
            "Rewrite it so that every field complies. Keep the same "
            "observations and the same evidence — only change how they are "
            "phrased.",
            "",
            "Problems found:",
        ]
        for violation in self.violations:
            lines.append(
                '- In "{0}": the phrase "{1}" is {2}. {3}'.format(
                    violation.field,
                    violation.phrase,
                    violation.rule.replace("_", " "),
                    RULE_EXPLANATIONS[violation.rule],
                )
            )
        lines.extend(
            [
                "",
                "Rewrite every field. Do not add a preamble or explain the "
                "changes — return the corrected structured result only.",
            ]
        )
        return "\n".join(lines)


def _check_word_limit(text: str, field_name: str, limit: int) -> List[Violation]:
    word_count = len(text.split())
    if word_count <= limit:
        return []
    return [
        Violation(
            rule=RULE_WORD_LIMIT,
            phrase="{0} words (limit {1})".format(word_count, limit),
            field=field_name,
        )
    ]


def _check_single_sentence(text: str, field_name: str) -> List[Violation]:
    # One trailing terminator is fine ("Reads controlled, not effortful.");
    # anything left after stripping it means a second sentence is present.
    stripped = text.strip().rstrip(".!?")
    if re.search(r"[.!?]", stripped):
        return [
            Violation(
                rule=RULE_MULTI_SENTENCE,
                phrase=text,
                field=field_name,
            )
        ]
    return []


def lint_text(text: str, field_name: str = "text") -> List[Violation]:
    if not text:
        return []
    found: List[Violation] = []
    for rule, patterns in _RULES:
        for pattern in patterns:
            for match in pattern.finditer(text):
                found.append(
                    Violation(rule=rule, phrase=match.group(0), field=field_name)
                )
    return found


def lint_feedback(feedback: Dict[str, Any]) -> LintReport:
    """Lint every user-visible string in a candidate feedback payload."""
    violations: List[Violation] = []

    for name in LINTED_FIELDS:
        value = feedback.get(name)
        if isinstance(value, str):
            violations.extend(lint_text(value, name))
            limit = WORD_LIMITS.get(name)
            if limit is not None and value.strip():
                violations.extend(_check_word_limit(value, name, limit))

    for index, quick_read in enumerate(feedback.get("quick_reads") or []):
        if not isinstance(quick_read, dict):
            continue
        text = quick_read.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        field_name = "quick_reads[{0}]".format(index)
        violations.extend(lint_text(text, field_name))
        violations.extend(_check_word_limit(text, field_name, QUICK_READ_WORD_LIMIT))
        violations.extend(_check_single_sentence(text, field_name))

    proportion_note = feedback.get("proportion_note")
    if isinstance(proportion_note, str) and proportion_note.strip():
        for pattern in _PROPORTION_HEDGE_PATTERNS:
            match = pattern.search(proportion_note)
            if match:
                violations.append(
                    Violation(
                        rule=RULE_PROPORTION_HEDGE,
                        phrase=match.group(0),
                        field="proportion_note",
                    )
                )
                break  # one flag is enough to trigger a regenerate

    elevate_suggestion = feedback.get("elevate_suggestion")
    if isinstance(elevate_suggestion, str) and elevate_suggestion.strip():
        for rule, patterns in _ELEVATE_SUGGESTION_RULES:
            for pattern in patterns:
                for match in pattern.finditer(elevate_suggestion):
                    violations.append(
                        Violation(rule=rule, phrase=match.group(0), field="elevate_suggestion")
                    )
        violations.extend(
            _check_word_limit(elevate_suggestion, "elevate_suggestion", ELEVATE_SUGGESTION_WORD_LIMIT)
        )
        violations.extend(_check_single_sentence(elevate_suggestion, "elevate_suggestion"))

    for index, note in enumerate(feedback.get("garment_notes") or []):
        if isinstance(note, dict):
            text = note.get("note")
            if isinstance(text, str):
                violations.extend(
                    lint_text(text, "garment_notes[{0}]".format(index))
                )

    return LintReport(violations=violations)
