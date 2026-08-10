# StyleSignal

Descriptive style feedback. Photograph an outfit, get a read on **how it comes
across** — colour relationships, formality coherence, proportion, overall
signal. It never prescribes a change and never rates the wearer.

This repository implements the **v1 scope** of `stylesignal-spec.md` (§9): a
thin vertical slice that proves people want descriptive outfit feedback.

```
mobile/     React Native (Expo) client — capture → upload → poll → render
backend/    FastAPI gateway + async worker pipeline
docs/       Deployment, prompt contract, spec deviations
```

---

## Quickstart

Two terminals. The backend runs with **no Postgres, no Redis and no S3** — see
[Local vs production](#local-vs-production).

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt

copy .env.example .env          # cp on macOS/Linux
# Edit .env: set STYLESIGNAL_JWT_SECRET, and STYLESIGNAL_ANTHROPIC_API_KEY
# to enable real feedback (without it every scan uses the §7.6 fallback).

uvicorn app.main:app --reload --port 8000
```

Check it: <http://127.0.0.1:8000/health> · API docs at `/docs`.

```bash
pytest          # 119 tests, no API key or network needed
```

### 2. Mobile

```bash
cd mobile
npm install
npx expo start
```

Press `a` for an Android emulator, `i` for an iOS simulator, or scan the QR
code with Expo Go. On a physical device, set your machine's LAN IP in
`app.json` → `expo.extra.apiBaseUrl` (an emulator's `localhost` is the
emulator, not your machine — `src/config.ts` already remaps `127.0.0.1` to
`10.0.2.2` for the Android emulator).

---

## What is built

| Spec | Status |
|---|---|
| §4.1 Mobile client — capture, downscale, occasion tag, poll, render | ✅ |
| §4.2 Gateway — auth, validation, upload, enqueue, reads | ✅ |
| §4.3 Preprocess — decode, EXIF strip, orient, normalise, thumbnail | ✅ |
| §4.4–4.5 Detect + attributes — single VLM call, per §9 v1 | ✅ |
| §4.5 LAB colour extraction from real pixels | ✅ (v1 bonus — see below) |
| §4.6 CLIP embeddings + vector DB | ⏸ deferred to v2 per §9 |
| §4.7 Rule signals — colour harmony, formality coherence, proportion | ✅ |
| §4.7 Preference model | ⏸ deferred to v2 per §9 |
| §4.8 Community rating loop | ✅ built, **off by default** per §9 |
| §5 All seven tables, including the v2 ones (empty) | ✅ |
| §6 Every endpoint | ✅ |
| §7 Descriptive contract + lint-and-regenerate + fallback | ✅ |
| §8 Auth, privacy, rate limits, observability, cost control, idempotency | ✅ |

Explicitly deferred to v2, exactly as §9 orders it: custom segmentation, CLIP
embeddings, the preference model, and switching the community endpoints on.

---

## How a scan works

```
POST /v1/outfits  ──►  202 {outfit_id, status: "pending"}   (gateway returns immediately)
                            │
                            └─►  worker
                                   1. preprocess     §4.3  decode, strip EXIF, normalise, thumb
                                   -  hash cache     §8    identical pixels + occasion? reuse, no spend
                                   2. palette        §4.5  dominant LAB colours from real pixels
                                   3. VLM call       §7.5  garments + descriptive prose, one shot
                                   4. lint           §7.5  reject prescriptive/evaluative copy, regenerate
                                   5. rule signals   §4.7  harmony, formality spread, proportion flags
                                   6. persist        §5.5  status → complete

GET /v1/outfits/{id}  ──►  poll at 1.5s backing off to 4s (§6.6)
```

### The lint pass is the product

§2.5 warns that descriptive done badly reads as evasive — worse than a score.
So the voice is enforced mechanically, not just prompted. Every user-visible
string is checked against the four §7.3 prohibitions:

| Rule | Rejects |
|---|---|
| `prescription` | "you should", "swap the", "add a", "try", "consider", "would look better", "needs a" |
| `person_evaluation` | "flattering", "slimming", "suits you", anything about the wearer's body |
| `numeric_score` | "8/10", "scores a 4", "rating of" |
| `negative_absolute` | "is bad/wrong/ugly", "doesn't work", "a mistake" |

A rejected draft is sent back to the model with the offending phrases named and
an instruction to keep the observations but change the phrasing. After
`STYLESIGNAL_VLM_MAX_LINT_RETRIES` failures it falls back to templated text
(§7.6). `tests/test_lint.py` pins both directions — the forbidden phrasings and
the §7.2 allowed ones, which must pass untouched.

### Why colour comes from pixels, not from the model

§2.3 promises deterministic reads, because competitors' re-scan drift is one of
the two failure modes StyleSignal exists to avoid. §9 says rule signals are
optional in v1 — but the promise depends on them, so they are built:
`app/worker/colour.py` extracts dominant colours from the actual pixels,
converts to LAB, and classifies the palette into the §4.7 harmony classes. The
same photo always produces the same palette and the same class.

One thing worth knowing if you touch that classifier: **LAB hue angles are not
evenly spaced.** A genuine blue/orange complementary pair measures ~136° apart,
while three scattered hues (green/magenta/amber) span ~168°. Classifying by
maximum hue spread therefore labels the clash "complementary" and the
complementary pair "clash" — exactly backwards. Classification is by *hue
cluster count* instead: one cluster is analogous, two opposed clusters are
complementary, three or more is a clash.
`test_clash_spread_exceeds_complementary_spread` is the regression guard.

---

## Local vs production

Storage, the queue, and the database all sit behind interfaces, so the same
code runs both ways. Nothing is stubbed — the local backends are real
implementations, just not distributed ones.

| | Local default | Production (`docs/deployment.md`) |
|---|---|---|
| Database | SQLite file | Postgres |
| Object storage | Local disk + signed `/v1/media` route | S3 with SSE (§8) |
| Job queue | Bounded thread pool, in-process | Arq on Redis (§4.2, §10) |
| Rate limiting | In-process fixed window | Same window, shared via Redis (§8) |
| Vector DB | — | pgvector (v2, §10) |

Flip each with one env var; see `.env.example`.

---

## Cost control (§8)

VLM calls are the main variable cost, and §1 is blunt that "unlimited" is a
trap. Four things guard it:

1. **Image-hash cache** — identical normalised pixels *and* the same occasion
   reuse the earlier result with no model spend. Keyed on both because the
   notes are occasion-dependent: the same photo tagged `work` and `evening`
   must not share feedback.
2. **Free-tier allowance** — 5 scans/month, charged before any work so parallel
   uploads cannot overrun it.
3. **Pro soft ceiling** — §1 requires graceful degradation, "not an advertised
   hard limit". Past the ceiling a Pro scan is never refused; it runs at
   reduced effort with a smaller lint-retry budget.
4. **Prompt caching** — the system prompt is a stable cached prefix, so the
   §7 contract is paid for once, not on every scan.

---

## Model configuration

The VLM is Claude (`claude-opus-5` by default, set with
`STYLESIGNAL_VLM_MODEL`). §10 left the provider open; the prompt contract in
`app/worker/vlm.py` is provider-shaped only in its use of structured outputs
and vision, both of which have direct equivalents elsewhere.

Two things enabled by default worth knowing about:

- **Server-side refusal fallbacks.** Claude's safety classifiers can decline a
  request; the call opts into `fallbacks: "default"`, which re-runs a declined
  request on a fallback model server-side instead of failing the scan. Drop the
  `fallbacks`/`betas` arguments in `_create()` if you would rather handle
  refusals yourself. If the installed SDK predates the parameter, the code logs
  once and continues without it.
- **Adaptive thinking at `medium` effort.** Tune with
  `STYLESIGNAL_VLM_EFFORT` (`low`…`max`). `medium` is a deliberate cost choice
  for a per-scan consumer workload, not a quality ceiling — raise it if reads
  feel thin.

Set `STYLESIGNAL_VLM_DISABLED=true` to work on the UI without spending tokens;
every scan then returns templated §7.6 text.

---

## Documentation

- [`docs/deployment.md`](docs/deployment.md) — Postgres, S3, Arq, and what to
  harden before real users
- [`docs/prompting.md`](docs/prompting.md) — the §7 contract, how to change the
  voice safely, and how to watch lint-rejection rate
- [`docs/spec-deviations.md`](docs/spec-deviations.md) — every place this
  implementation departs from the spec, and why

---

## Notes on this environment

- The backend targets **Python 3.9** because that is what is installed here.
  `requirements.txt` pins `greenlet<3.2` for that reason only — greenlet 3.2
  dropped its 3.9 wheels and there is no compiler on this machine. On 3.10+ you
  can delete that line. 3.11+ is a better long-term target.
- Passwords are hashed with argon2id (`argon2-cffi`), which ships a prebuilt
  wheel for this platform — no compiler needed here either.
- The mobile client uses a small hand-rolled screen switcher rather than
  react-navigation. Four screens did not justify the native linking surface,
  and every screen takes plain callback props — swapping in a navigator is a
  change to `App.tsx` alone.
- The mobile app typechecks and its Expo config resolves, but it has **not**
  been run against a simulator here — there is no emulator on this machine.
  That is the one part of the stack I could not verify end-to-end.
