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
LINTED_FIELDS = (
    "overall_read",
    "color_note",
    "formality_note",
    "proportion_note",
)

RULE_PRESCRIPTION = "prescription"
RULE_PERSON_EVALUATION = "person_evaluation"
RULE_NUMERIC_SCORE = "numeric_score"
RULE_NEGATIVE_ABSOLUTE = "negative_absolute"
RULE_PROPORTION_HEDGE = "proportion_hedge"

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

    for index, note in enumerate(feedback.get("garment_notes") or []):
        if isinstance(note, dict):
            text = note.get("note")
            if isinstance(text, str):
                violations.extend(
                    lint_text(text, "garment_notes[{0}]".format(index))
                )

    return LintReport(violations=violations)
