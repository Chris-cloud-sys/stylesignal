"""§7.7 glanceable meters — computed deterministically, not asked of the VLM.

See app/worker/rules.py's module docstring and spec-deviations.md for why:
same photo must always produce the same meter (§2.3), and the §7.6 fallback
needs to be able to produce one too.
"""
from app.worker.rules import compute_meters


def _signals(mean, coherence, harmony_class="neutral-anchored"):
    return {
        "formality": {"mean": mean, "coherence": coherence},
        "colour": {"harmony_class": harmony_class},
    }


# --- occasion_match ----------------------------------------------------------
def test_occasion_match_strong_when_mean_centred_in_band():
    signals = _signals(mean=0.15, coherence="consistent")
    meter = compute_meters(signals, "casual")["occasion_match"]
    assert meter is not None
    assert meter["level"] == "strong"


def test_occasion_match_off_when_mean_far_outside_band():
    signals = _signals(mean=0.95, coherence="consistent")
    meter = compute_meters(signals, "casual")["occasion_match"]
    assert meter["level"] == "off"


def test_occasion_match_degraded_by_split_coherence():
    """Same mean, worse coherence must never score higher."""
    consistent = compute_meters(_signals(0.5, "consistent"), "work")["occasion_match"]
    split = compute_meters(_signals(0.5, "split"), "work")["occasion_match"]
    assert split["score"] < consistent["score"]


def test_occasion_match_none_when_occasion_has_no_band():
    for occasion in (None, "other"):
        signals = _signals(mean=0.5, coherence="consistent")
        assert compute_meters(signals, occasion)["occasion_match"] is None


def test_occasion_match_none_when_formality_mean_missing():
    signals = _signals(mean=None, coherence="unknown")
    assert compute_meters(signals, "casual")["occasion_match"] is None


# --- signal_clarity ------------------------------------------------------------
def test_signal_clarity_strong_when_consistent_and_not_clash():
    signals = _signals(mean=0.5, coherence="consistent", harmony_class="analogous")
    meter = compute_meters(signals, None)["signal_clarity"]
    assert meter["level"] == "strong"


def test_signal_clarity_off_when_split_and_clash():
    signals = _signals(mean=0.5, coherence="split", harmony_class="clash")
    meter = compute_meters(signals, None)["signal_clarity"]
    assert meter["level"] == "off"


def test_signal_clarity_partial_when_signals_disagree():
    # Coherent formality but a clashing palette — the two signals disagree.
    signals = _signals(mean=0.5, coherence="consistent", harmony_class="clash")
    meter = compute_meters(signals, None)["signal_clarity"]
    assert meter["level"] in ("partial", "off")
    assert meter["level"] != "strong"


def test_signal_clarity_none_when_coherence_unknown():
    signals = _signals(mean=None, coherence="unknown")
    assert compute_meters(signals, None)["signal_clarity"] is None


def test_meters_are_deterministic():
    """Same signals in, same meters out — every time (§2.3)."""
    signals = _signals(mean=0.42, coherence="mixed", harmony_class="complementary")
    first = compute_meters(signals, "evening")
    second = compute_meters(signals, "evening")
    assert first == second
