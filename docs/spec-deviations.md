# Spec deviations

Every place this implementation departs from `stylesignal-spec.md`, and why.
Nothing here is silent — if you disagree with a call, this is the list to
argue with.

---

## 1. Schema additions

§5 defines the columns; these are the ones added on top. All are additive, so
the §9 promise that v2 needs no destructive migration still holds.

| Table | Column | Why |
|---|---|---|
| `users` | `password_hash` | §8 requires JWT auth but §5.2 lists no credential column. Auth cannot work without it. |
| `users` | `scans_period` | §5.2 says the scan counter is "reset by monthly cron". Storing the period the counter belongs to makes the reset lazy and idempotent, so a missed cron run cannot silently deny a user their quota. |
| `users` | `rating_credits`, `earned_scans` | §1 puts "earn-more-by-rating" in the free tier. The credit ledger has to live somewhere. |
| `outfits` | `image_sha256` | §8 requires caching by image hash. |
| `outfits` | `deleted_at` | §6.4 requires soft-delete. |
| `garments` | `created_at` | Deterministic ordering, so `garment_notes` indices resolve stably. |

`outfits.working_key` and `outfits.thumb_key` are **not** stored — §5.7 defines
the key layout as a pure function of `outfit_id`, so they are derived
properties on the model.

**`garments.formality` is `Float`, not `Numeric`.** §5.4 says numeric; `Numeric`
round-trips as `Decimal`, which does not serialise to JSON without a custom
encoder, and the value is a 0–1 estimate where float precision is irrelevant.

---

## 2. `POST /v1/outfits` can only be one flow

§6.1 defines two upload flows and puts **both** on `POST /v1/outfits` — Flow A
takes a multipart body, Flow B returns a presigned URL. They cannot share a
route. §6.1 says "pick one for v1", so:

- **Flow A** keeps `POST /v1/outfits` — it is the default and what the mobile
  client uses.
- **Flow B** lives at `POST /v1/outfits/presign`, then `POST
  /v1/outfits/{id}/submit` as specified.

Both are implemented, so switching the client to Flow B at scale is a client
change only.

---

## 3. Create returns `202`, not `201`

§6.6 explicitly permits this: "`202` acceptable alternative to `201` on create
to signal async". Processing genuinely is async, so `202` is the more accurate
code. `POST /v1/outfits/presign` still returns `201` — it creates a row without
starting work.

---

## 4. A missing VLM completes the scan instead of failing it

§4.4 says zero garments detected is a typed failure. §7.6 says that when the
VLM is unavailable the templated fallback "keeps the product functional". In v1
detection *is* the VLM call, so those two rules collide when the model is off.

Resolution: the failure applies only when detection actually **ran** and found
nothing. When the VLM never ran, the scan completes with zero garments and
fallback prose built from the whole-image palette — which still supports a real
colour and contrast read. Failing there would make `STYLESIGNAL_VLM_DISABLED`
useless for UI work and would turn any model outage into a total outage, which
is the opposite of what §7.6 asks for.

---

## 5. Rule signals are built in v1, not deferred

§9 says "Rule-based color/formality signals optional in v1 — the VLM can
approximate them. Add them if feedback feels arbitrary."

They are built. §2.3 sells deterministic reads as a core differentiator against
competitors' re-scan drift, and a VLM approximating its own colour impressions
cannot deliver that — the same photo would drift between scans, which is
precisely the failure mode §2.2 identifies. Extracting the palette from real
pixels is cheap (no extra model call, no extra dependency beyond Pillow) and
makes the guarantee real rather than aspirational.

The pixel-measured palette is also fed *into* the prompt as ground truth, so
the model describes measured colour rather than guessing at it.

---

## 6. Community endpoints ship built but disabled

§6.5 says "schema in v1, endpoints active v2" and §9 lists the community feed
under explicitly deferred. But §1 puts earn-by-rating in the **free tier**, and
§2.3 calls the rating loop the data moat.

Resolution: fully implemented, `STYLESIGNAL_COMMUNITY_ENABLED=false` by
default. Flipping it on activates `GET /v1/feed`, `POST
/v1/outfits/{id}/ratings`, and the earn loop. Disabled, they return `403
feature_disabled` rather than 404, so a client developer gets a useful answer.

Two decisions inside that loop worth flagging:

- **Rating updates earn nothing.** §6.5 says "repeat = update". An update is
  not new training signal, and paying for it would make the earn loop trivially
  farmable by re-rating one outfit.
- **Feed ordering is fewest-ratings-first.** §4.8 asks for active-learning
  selection by model uncertainty, but the preference model does not exist until
  v2. Fewest-ratings-first is its structural stand-in — it is where any model
  would be least confident. Swap the ordering key when §9 step 5 lands; the
  query is one line.

---

## 7. Pro's soft cap degrades quality, not access

§1: "'Unlimited' must carry a soft fair-use ceiling with graceful degradation
(not an advertised hard limit)". §1 does not say what degradation means, so:
past `STYLESIGNAL_PRO_SOFT_MONTHLY_CAP`, a Pro scan still runs, at `effort:
low` with the lint-retry budget cut to one. The user is never refused and never
sees a limit; the marginal scan costs materially less.

---

## 8. Infrastructure substitutions

Nothing is stubbed — these are real implementations behind the same interface.

| Spec | Local default | Why |
|---|---|---|
| Postgres | SQLite | Same SQLAlchemy models. Docker is not installed on the dev machine; `STYLESIGNAL_DATABASE_URL` switches it. |
| S3 | Local disk + HMAC-signed `/v1/media` route | Same `ObjectStorage` interface. The signed route is time-limited, so it is not an open file server. |
| Redis + Arq | Bounded thread pool | Same `JobQueue` interface; uploads are still async from the client's view. Work dies with the process, so it is not a production queue. |
| Alembic | `create_all` | §9 requires every v2 table to exist in v1, so the first real migration is additive columns only. Introduce Alembic before the first production deploy. |

---

## 9. Security choices

- **Argon2id, not PBKDF2.** `app/security.py` originally used PBKDF2-HMAC-SHA256
  from the standard library on the assumption that bcrypt/argon2 need a
  compiler this dev machine doesn't have. That assumption turned out to be
  wrong — `argon2-cffi` ships a prebuilt wheel for cp39-abi3-win_amd64 (and
  every other common platform), so there was no reason to stay on PBKDF2 once
  checked. Swapped before this had any real users; `app/security.py` was the
  only file that changed, exactly as originally planned.
- **Rate limiting is inprocess by default, redis available.** `app/ratelimit/`
  is now a `storage`/`jobs`-shaped interface with two backends:
  `inprocess` (a fixed-window dict, correct for one gateway process and for
  tests, but under-counts across multiple workers because each process only
  sees its own share of requests) and `redis` (the same fixed window shared
  across every worker via one Redis key). `STYLESIGNAL_RATELIMIT_BACKEND=redis`
  switches it, reusing `STYLESIGNAL_REDIS_URL`. Still defaults to `inprocess`
  for the same reason storage defaults to `local` and the queue defaults to
  `inprocess` — nothing here needs Redis installed to run. The redis backend
  fails *open* (logs and allows the request) if Redis is unreachable, on the
  view that a rate limiter should never become a bigger outage than what it
  protects against; `app/quota.py`'s scan quota is the limiter that actually
  guards VLM spend; and it has no local test, matching this repo's existing
  precedent for other infra-dependent production backends (`ArqQueue`,
  `S3Storage`) — see `docs/deployment.md` before relying on it.
- **Another user's outfit returns 404, not 403.** A 403 confirms the id exists.

---

## 10. Detection failure ordering, and a hedge treated as invented text

Two related fixes made after running the 30-photo eval set for the first time
(`backend/evals/`) surfaced both gaps — this is what "the eval harness will
run the whole set and lay the reads out side by side" (photo brief) is for.

**Flat-lay/no-person now fails even when garments are detected.** §4.4 says
zero garments detected is a typed failure, and the original code only checked
`person_present` to *choose* which failure reason applied once `detected` was
already empty. A flat-lay photo breaks that assumption: the VLM correctly
names the garments laid out on a surface, so `detected` is non-empty even
though no one is wearing them, and the scan used to complete with generated
feedback for an outfit that does not exist on a body. `_detection_failure_reason`
(`app/worker/pipeline.py`) now checks `person_present` first, independent of
`detected`, so a flat-lay fails cleanly as `no_person` — exactly what the
brief's own flat-lay test case expects ("should fail cleanly with 'no person',
not crash or invent an outfit").

**A hedged proportion_note is lint-rejected, not just discouraged.** §7.4 asks
for an empty `proportion_note` when the framing does not support a read,
enforced only in the system prompt. In the eval run this was followed
inconsistently — one cropped photo returned an empty string as instructed,
another returned a sentence explaining that proportion "cannot be assessed"
from the framing. That sentence is not empty, so it is exactly the invented
field §7.4 rules out, just spelled as a caveat instead of a claim. `lint.py`
now has a `RULE_PROPORTION_HEDGE` check, scoped to `proportion_note` only, that
sends a draft like that back through the regenerate loop the same way a
prescriptive or evaluative phrase would be. Worst case — retries exhausted —
the scan falls through to the §7.6 fallback, which only ever writes a
proportion note when geometry flags actually exist, so the hedge can never
reach the user even on the unlucky path.

---

## 11. Client

- **No react-navigation.** Four screens did not justify the native linking
  surface. Every screen takes plain callback props, so swapping a navigator in
  touches `App.tsx` only.
- **Polling, not websockets.** §4.1 and §10 both specify poll for v1, at the
  §6.6 cadence (1.5s → 4s). `useOutfitPolling` is the seam where a socket or
  push channel replaces it without touching any screen.
