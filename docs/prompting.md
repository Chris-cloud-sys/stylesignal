# The prompt contract

`app/worker/vlm.py` holds the §7.5 contract. This is what to know before
changing it.

---

## The shape of the call

One call per scan (§9 v1), carrying:

1. the working image (JPEG, ≤1600px long edge)
2. the **measured** whole-image LAB palette — real pixels, not the model's
   impression
3. any computed rule signals (§4.7)
4. the stated occasion and the wearer's freeform note

and returning the §5.5 fields under a JSON schema, so the *shape* is guaranteed
by the API and only the *voice* needs enforcing.

Two families of output live in that schema: the long-form fields
(`overall_read`, `color_note`, `formality_note`, `proportion_note`,
`garment_notes`) and the §7.7 glanceable fields (`verdict_phrase`,
`verdict_subtitle`, `focal_point`, `quick_reads`). `occasion_match` and
`signal_clarity` — the two meters on the result screen — are **not** in this
schema; they're computed deterministically in `app/worker/rules.py` from the
same signals the fallback uses, never asked of the model. See
spec-deviations.md §11 for why.

The system prompt is a stable cached prefix. Anything per-request goes in the
user turn — putting a timestamp, a user id, or the occasion into the system
prompt would invalidate the cache on every scan and multiply the cost of the
§7 contract by your scan volume.

---

## Changing the voice

The system prompt encodes §7.1–§7.4. Two constraints on editing it:

**The four prohibitions are load-bearing, not stylistic.** §7.3's forbidden
categories are enforced twice — once in the prompt, once in
`app/worker/lint.py`. If you soften the prompt, the lint pass still rejects the
output and you will simply pay for regenerations. If you want to permit
something currently forbidden, change the lint rules *and* the tests first;
`tests/test_lint.py` is the specification.

**The §7.7 copy limits work the same way.** `verdict_phrase` (≤5 words),
`verdict_subtitle` (≤8), `focal_point` (≤12), and each `quick_reads` item
(≤15 words, one sentence) are stated in the prompt but enforced by
`RULE_WORD_LIMIT`/`RULE_MULTI_SENTENCE` in `lint.py`, on the same
regenerate-or-fall-back loop as the four voice prohibitions. A model that
drifts long on `verdict_phrase` costs a regeneration, not a broken UI.

**"Every observation must carry its own lever" is the mitigation for §2.5.**
The spec's own risk register says pure description reads as evasive if a user
wants a verdict. The prompt's instruction to name the tension *and* its cause
is what prevents that. It is the single most important sentence in the file —
if reads start feeling like a dodge, that instruction is what to strengthen,
not the descriptive rule itself.

---

## Tuning

| Knob | Default | Effect |
|---|---|---|
| `STYLESIGNAL_VLM_MODEL` | `claude-opus-5` | |
| `STYLESIGNAL_VLM_EFFORT` | `medium` | Depth of reasoning. Raise if reads feel thin. |
| `STYLESIGNAL_VLM_MAX_TOKENS` | `8000` | Caps thinking + output together. |
| `STYLESIGNAL_VLM_MAX_LINT_RETRIES` | `2` | Regenerations before §7.6 fallback. |
| `STYLESIGNAL_VLM_DISABLED` | `false` | Skip the model entirely; always fallback. |

`medium` effort is a cost choice for a per-scan consumer workload, not a
quality ceiling. If you raise it, re-measure the regeneration rate — deeper
reasoning sometimes produces *more* prescriptive drafts, because the model
reasons its way to an opinion and then wants to share it.

---

## Watching the lint

The regeneration rate is the health metric for the product's voice. It lands in
`outfit_feedback.signals.vlm`:

```json
{
  "used": true,
  "model": "claude-opus-5",
  "degraded": false,
  "lint_attempts": 1,
  "lint_violations": [],
  "usage": { "input_tokens": 2210, "cache_read_input_tokens": 1780 }
}
```

- `lint_attempts: 1` with no violations is the healthy case — first draft
  passed.
- A rising average is the earliest signal a prompt edit has drifted toward
  prescription.
- `lint_violations` accumulates across attempts, so you can see *which* rule
  the model keeps breaking and target the prompt at that rule specifically.

`docs/deployment.md` has the SQL.

---

## False positives

The lint rules are deliberately strict — a false rejection costs one
regeneration, a false accept ships prescriptive copy. But a rule that fires on
legitimate phrasing burns tokens on every scan, so they are written narrowly
where it matters:

- `\bsuggest\b` fires; `suggests` does not — "the cut suggests formality" is a
  legitimate description.
- `\bconsider\b` fires; `considered` does not — "a considered pairing" is fine.
- `instead` only fires next to a garment verb, so "reads warm instead of cool"
  passes.
- `clash` is *not* a violation on its own — it is a §4.7 harmony class. Only
  "clashes badly" and friends are.
- `RULE_WORD_LIMIT` counts words with a plain `str.split()` — "low-contrast"
  is one word, not two, so hyphenated compounds don't cost the model extra
  budget.
- `RULE_MULTI_SENTENCE` only fires on an interior `.`/`!`/`?` after stripping
  one trailing terminator — "Reads controlled, not effortful." passes;
  "The jacket is long. It lengthens the line." does not.

If you add a rule, add both a rejecting case and a nearby passing case to
`tests/test_lint.py`. The passing cases in that file are lifted from §7.2, so
they are the spec's own examples of what must survive.

---

## The fallback is not decorative

`app/worker/fallback.py` runs when the model is unreachable, refuses, or never
clears the lint. It builds prose from rule signals alone — lower resolution,
but every sentence still traces to a measurement (§7.4) and still obeys §7.3.

`test_fallback_passes_lint` runs the fallback across every occasion and
garment-count combination and lints the output. That test matters more than it
looks: the fallback is assembled from numeric signals, so it is the code most
likely to leak a number into user-visible text and break §7.3.
`test_fallback_never_prints_a_number` asserts no digit reaches the reader.
