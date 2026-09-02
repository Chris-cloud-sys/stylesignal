"""The descriptive-feedback contract — spec §7.3 / §7.5.

These are the tests that defend the product's differentiation. §2.2 says the
market fails by handing out a meaningless score or the wrong prescription, and
§2.5 warns that descriptive done badly is worse than a score — so the lint pass
has to actually catch both.
"""
import pytest

from app.worker.lint import (
    RULE_MULTI_SENTENCE,
    RULE_NEGATIVE_ABSOLUTE,
    RULE_NUMERIC_SCORE,
    RULE_PERSON_EVALUATION,
    RULE_PRESCRIPTION,
    RULE_PROPORTION_HEDGE,
    RULE_WORD_LIMIT,
    lint_feedback,
    lint_text,
)


def rules_for(text: str):
    return {violation.rule for violation in lint_text(text)}


# --- §7.3 forbidden: prescription -----------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "You should swap the sneakers for something darker.",
        "Try a leather belt to tie the browns together.",
        "Consider a slimmer trouser here.",
        "I'd recommend a mid-tone shirt instead.",
        "The look needs a third colour.",
        "Add a structured jacket and it lifts the whole thing.",
        "Pair it with a darker shoe.",
        "Next time, go with a warmer neutral.",
        "A darker shoe would look better against the trousers.",
        "Wear the tan boots instead of the white trainers.",
        "Avoid mixing the two patterns.",
        "Stick to one pattern across the look.",
    ],
)
def test_prescription_is_rejected(text):
    assert RULE_PRESCRIPTION in rules_for(text), text


# --- §7.3 forbidden: evaluation of the person -----------------------------
@pytest.mark.parametrize(
    "text",
    [
        "The cut is flattering on your frame.",
        "This is unflattering across the shoulders.",
        "The vertical line is slimming.",
        "You look great in this.",
        "The colour really suits you.",
        "It works well for your body type.",
    ],
)
def test_person_evaluation_is_rejected(text):
    assert RULE_PERSON_EVALUATION in rules_for(text), text


# --- §7.3 forbidden: numeric scores ---------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "Overall this is an 8/10 look.",
        "It lands at 7 out of 10 for coherence.",
        "The outfit scores 4 on formality agreement.",
        "A rating of four for colour harmony.",
    ],
)
def test_numeric_scores_are_rejected(text):
    assert RULE_NUMERIC_SCORE in rules_for(text), text


# --- §7.3 forbidden: negative absolutes -----------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "The pattern mix is bad.",
        "That colour pairing is just wrong.",
        "The proportions are ugly here.",
        "The belt doesn't work with the shoes.",
        "Pairing those two is a mistake.",
    ],
)
def test_negative_absolutes_are_rejected(text):
    assert RULE_NEGATIVE_ABSOLUTE in rules_for(text), text


# --- §7.2 allowed: these must pass untouched ------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "The palette stays in a warm, low-contrast range.",
        "The pieces largely agree on formality; the sneakers read more casual "
        "than the rest.",
        "The cropped jacket raises the waistline visually.",
        "This reads as polished smart-casual.",
        "For a work context, this reads appropriately put-together.",
        "The navy and warm brown sit in a low-contrast, analogous-adjacent "
        "range, so the two halves read as one block rather than as separate "
        "pieces.",
        "The two patterns compete for attention, and the competition comes "
        "from their similar scale rather than from their colours.",
        "The blazer anchors the formality of the look.",
        "The considered pairing of textures suggests a deliberate choice.",
        "The longer jacket over slim trousers creates a lengthening vertical "
        "line.",
    ],
)
def test_allowed_phrasing_passes(text):
    assert lint_text(text) == [], text


def test_lint_walks_every_visible_field():
    report = lint_feedback(
        {
            "overall_read": "This reads as relaxed weekend.",
            "color_note": "The palette is warm and low-contrast.",
            "formality_note": "The pieces agree on formality.",
            "proportion_note": "You should try a longer jacket.",
            "garment_notes": [{"garment_id": "x", "note": "The shirt is ugly."}],
        }
    )
    assert not report.ok
    assert set(report.rules_broken) == {RULE_PRESCRIPTION, RULE_NEGATIVE_ABSOLUTE}
    assert {v.field for v in report.violations} == {
        "proportion_note",
        "garment_notes[0]",
    }


def test_clean_feedback_passes():
    report = lint_feedback(
        {
            "overall_read": "Taken together, the pieces read as smart-casual.",
            "color_note": "The palette is neutral-anchored.",
            "formality_note": "The pieces agree on formality.",
            "proportion_note": "The jacket carries the waistline higher.",
            "garment_notes": [
                {"garment_id": "x", "note": "The blazer anchors the register."}
            ],
        }
    )
    assert report.ok
    assert report.as_dict()["violations"] == []


# --- §7.4 forbidden: a hedge instead of an empty proportion_note -----------
@pytest.mark.parametrize(
    "text",
    [
        "The proportion cannot be assessed from this framing.",
        "Footwear is outside the frame, so this cannot be determined.",
        "The crop cuts off below the waist, so it is hard to tell here.",
        "That detail is not visible in this photo.",
        "The framing does not support a proportion read here.",
    ],
)
def test_proportion_hedge_is_rejected(text):
    report = lint_feedback({"proportion_note": text})
    assert not report.ok, text
    assert RULE_PROPORTION_HEDGE in report.rules_broken
    assert {v.field for v in report.violations} == {"proportion_note"}


def test_empty_proportion_note_is_not_a_hedge_violation():
    for value in ("", None):
        report = lint_feedback({"proportion_note": value})
        assert report.ok, value


def test_real_proportion_observation_passes():
    """A genuine read must not get caught by the hedge patterns."""
    report = lint_feedback(
        {"proportion_note": "The cropped jacket raises the waistline visually."}
    )
    assert report.ok


# --- §7.7 glanceable fields: word limits and single-sentence rule ---------
def test_verdict_phrase_over_five_words_is_rejected():
    report = lint_feedback({"verdict_phrase": "This reads as a very relaxed weekend look"})
    assert not report.ok
    assert RULE_WORD_LIMIT in report.rules_broken
    assert report.violations[0].field == "verdict_phrase"


def test_verdict_phrase_at_five_words_passes():
    report = lint_feedback({"verdict_phrase": "Quiet, tidy weekend look overall"})
    assert report.ok


def test_verdict_subtitle_over_eight_words_is_rejected():
    report = lint_feedback(
        {"verdict_subtitle": "The pieces here all agree with each other closely and consistently"}
    )
    assert not report.ok
    assert RULE_WORD_LIMIT in report.rules_broken


def test_focal_point_over_twelve_words_is_rejected():
    report = lint_feedback(
        {
            "focal_point": (
                "The eye lands somewhere around the middle of the outfit near "
                "the waistline where the belt sits"
            )
        }
    )
    assert not report.ok
    assert RULE_WORD_LIMIT in report.rules_broken


def test_quick_read_over_fifteen_words_is_rejected():
    report = lint_feedback(
        {
            "quick_reads": [
                {
                    "dimension": "colour",
                    "text": (
                        "The navy and warm brown sit in a low-contrast range "
                        "that reads as one continuous block rather than separate pieces"
                    ),
                }
            ]
        }
    )
    assert not report.ok
    assert RULE_WORD_LIMIT in report.rules_broken
    assert report.violations[0].field == "quick_reads[0]"


def test_quick_read_at_fifteen_words_passes():
    report = lint_feedback(
        {
            "quick_reads": [
                {
                    "dimension": "formality",
                    "text": "The sneakers read a step more casual than the tailoring worn above them right now",
                }
            ]
        }
    )
    # 15 words exactly — must pass the word-limit check (may still fail on
    # other rules, but not this one).
    assert RULE_WORD_LIMIT not in report.rules_broken


def test_quick_read_with_two_sentences_is_rejected():
    report = lint_feedback(
        {
            "quick_reads": [
                {
                    "dimension": "proportion",
                    "text": "The jacket is long. It lengthens the line.",
                }
            ]
        }
    )
    assert not report.ok
    assert RULE_MULTI_SENTENCE in report.rules_broken


def test_quick_read_single_sentence_passes():
    report = lint_feedback(
        {
            "quick_reads": [
                {"dimension": "colour", "text": "The palette stays warm and low-contrast throughout."}
            ]
        }
    )
    assert RULE_MULTI_SENTENCE not in report.rules_broken


def test_quick_read_inherits_general_voice_rules():
    """A prescriptive phrase inside a quick_read must still be caught."""
    report = lint_feedback(
        {"quick_reads": [{"dimension": "fit", "text": "You should swap the shoes."}]}
    )
    assert not report.ok
    assert RULE_PRESCRIPTION in report.rules_broken


def test_verdict_phrase_inherits_general_voice_rules():
    report = lint_feedback({"verdict_phrase": "Looks bad today"})
    assert RULE_NEGATIVE_ABSOLUTE in report.rules_broken


def test_correction_prompt_names_the_offending_phrase():
    report = lint_feedback({"overall_read": "You should swap the shoes."})
    prompt = report.correction_prompt()
    assert "prescription" in prompt
    assert "swap" in prompt
    # It must ask for a rewrite, not a deletion — the observation is fine, the
    # phrasing is not (§7.5).
    assert "Keep the same" in prompt
