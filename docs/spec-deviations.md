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

## 11. The glanceable result screen (§7.7)

The updated spec's §7.7 and the accompanying mockup ask for a redesigned
result screen: an always-visible headline (verdict phrase + subtitle, two
meters, a palette strip, a focal point), 3–4 scannable quick reads, and the
pre-existing long-form fields collapsed behind "See full read." Four
decisions made building it, beyond what the spec text says directly:

**`verdict_subtitle` is a new field, not in the spec text.** The mockup shows
a second line under the verdict phrase ("Reads controlled, not effortful.")
that reads as a distinct editorial gloss, not a restyled quick-read bullet.
Confirmed directly rather than guessed. Same voice and lint treatment as
every other user-visible field; capped at 8 words.

**`occasion_match` and `signal_clarity` are computed in `app/worker/rules.py`,
never asked of the VLM.** The spec describes both as *derived from* existing
formality/colour signals — which is exactly what §5's "rule signals are built
in v1" already does for colour harmony and formality coherence (entry #5
above). Keeping them off the VLM does three things a VLM-generated score
couldn't: guarantees the same photo always shows the same meter (§2.3's
core promise), lets the §7.6 templated fallback produce meaningful meters
with no VLM at all, and means a later threshold retune can't silently change
what an *already-completed* scan shows, because the meter is computed once
at pipeline time and persisted — not recomputed on every read.

**Accepted tension: the VLM never sees the meters it sits next to.**
`verdict_phrase`/`verdict_subtitle`/`quick_reads` are written by the same VLM
call that detects the garments, before `signal_clarity`/`occasion_match` are
computed from that call's output — a chicken-and-egg the single-call v1
architecture (§9) doesn't have a clean way around without a second model call.
So a VLM draft could in principle call a look "effortless" the same scan the
meter reads "off." Mitigated, not eliminated: the system prompt (§7.5)
instructs the model not to make a global "this coheres" claim at all — that
judgment is the meter's job — and to stay grounded in specific, visible
things instead. Worth watching for in practice; revisit if it shows up in a
real eval run the way the two bugs in entry #10 did.

**No colour-coded meter, ever.** §2.6 already forbids grading an outfit
through colour ("never use color to deliver the feedback verdict"). A
`strong`/`partial`/`off` meter is exactly the kind of thing that invites a
green/amber/red fill, so the mobile `Meter` primitive renders every level in
Ink, distinguished only by fill length and an adjacent text label — never
hue. Same rule, same reasoning, just a new place it could have been broken.

---

## 12. Client

- **No react-navigation.** Four screens did not justify the native linking
  surface. Every screen takes plain callback props, so swapping a navigator in
  touches `App.tsx` only.
- **Polling, not websockets.** §4.1 and §10 both specify poll for v1, at the
  §6.6 cadence (1.5s → 4s). `useOutfitPolling` is the seam where a socket or
  push channel replaces it without touching any screen.

---

## 13. Free tier raised to 10 scans/month

§1's table sets the free tier at 5 scans/month, priced against where
competitors' free tiers sat at spec-writing time. Raised to 10 — a direct
product call, not a technical constraint — on the view that a thin free tier
undercuts §2.4's own strategy (consumer app as data engine: more scans per
free user means more proprietary read-quality signal per user before they
hit the Pro wall). `STYLESIGNAL_FREE_MONTHLY_SCANS` is still one env var, so
retuning it again is a config change, not a code change.

Every place the old number was written down changed with it: `config.py`'s
default, `.env.example`, the mobile sign-in copy, and this repo's own docs
(README, `docs/deployment.md`). §1's soft-cost-trap warning is about
*unlimited*, not about where the free ceiling sits, so this doesn't touch
any of the cost-control mechanisms in §8 — the free tier is still a hard
cap, just a bigger one.

---

## 14. Share Card export needs a dev client, not Expo Go

Not a spec deviation so much as a client build-tooling one, but the same
principle applies: nothing here is silent.

The redesigned result screen (entry #11) added a "Share this read" action.
Its full form — a composited photo-plus-verdict image sized for
Stories/feed, matching the design canvas's ShareCard direction — needs
`react-native-view-shot` to rasterise a view to a PNG. That's a third-party
native module, never bundled into the public Expo Go app regardless of SDK
version (unlike Expo's own SDK packages, e.g. `expo-sharing`, which Expo Go
does carry). So the mobile project now builds via a custom EAS development
client (`eas.json`'s `development` profile, `expo-dev-client` installed)
instead of running straight in Expo Go — `npx expo start --dev-client`,
scanned with the custom dev client app rather than Expo Go. Every future
native dependency now needs a new client build to pick up; pure JS/TS
changes still hot-reload same as before.

`components/ShareCard.tsx` renders the exportable card off-screen (never
shown to the user), `captureRef` turns it into a PNG, `expo-sharing` hands
that file to the native share sheet. Same two rules as everywhere else: no
numeric score rendered as text, meter badges stay Ink-on-scrim regardless
of level — this surface gets more visual weight (bigger type, a dark scrim,
the wordmark) because it's posted once rather than lived in daily, not
because the verdict rules relax.

**Falls back to a text-only share** (`Share.share`, no image) if capture or
the image share sheet fails for any reason — leaving Expo Go was a one-way
tooling decision worth making deliberately, but the feature itself should
still work if the native module ever misbehaves on a given device.
Not yet verified on a real device at the time of writing: whether a user
*cancelling* the native share sheet also triggers this fallback (i.e.
whether `expo-sharing` rejects on cancel or resolves quietly) — worth
checking in real testing since falling back to a second share prompt right
after a deliberate cancel would be an annoying, not helpful, degradation.

---

## 15. Password reset

§8 requires auth but the spec text has no "forgot password" flow at all —
nothing to deviate from, just something to design from scratch.

**A 6-digit code, not a clickable link.** `POST /v1/auth/password-reset/request`
(email in, always `200` whether or not the account exists — an error would
let a caller enumerate registered emails, same reasoning as login's
same-message-either-way in entry #9) generates a random 6-digit code, hashes
it with SHA-256 (not argon2id — see below), and stores it on the new
`password_reset_codes` table with a 15-minute expiry.
`POST /v1/auth/password-reset/confirm` (email + code + new password) checks
it against every still-valid, unused code for that user, sets the new
password on a match, and burns every other outstanding code for that user at
the same time — a successful reset should leave nothing else usable. Wrong
guesses increment a per-code `attempts` counter capped at 5, independent of
the per-email rate limit on the endpoints themselves (`ratelimit.check`,
3 requests/15 min, 10 confirms/15 min) — a 6-digit code is only 1e6
possibilities, so both limits matter.

**SHA-256, not argon2id, for the code hash.** Passwords need slow,
brute-force-resistant hashing because they're long-lived, low-entropy-in-
practice secrets an attacker can throw offline compute at forever. A 6-digit
code is different: it expires in 15 minutes, works once, and is guarded by
its own attempt cap — the real protection is those three things, not hash
cost. Hashing it at all (rather than storing it plain) is still worth doing
so a DB read alone doesn't hand out live codes; SHA-256 is the right weight
for that job here.

**`app/email.py`: a real interface behind a factory, same shape as
storage/jobs/ratelimit** (`get_email_sender()`, mirroring
`get_storage()`/`get_queue()`), switched by `STYLESIGNAL_EMAIL_BACKEND`
(`console` | `resend`) exactly like `storage_backend`/`queue_backend`/
`ratelimit_backend`. `console` — the default — just logs the code, which is
the whole channel's job in a dev environment with no mail provider
configured, not a stub standing in for something unfinished, the same way
`docs/deployment.md` already treats `local` storage and `inprocess`
queueing as real implementations. `resend` sends a real email via
[Resend](https://resend.com)'s HTTP API (`ResendEmailSender`, plain
`httpx`, no SDK dependency added for one POST). Needs
`STYLESIGNAL_RESEND_API_KEY` set; without it, `get_email_sender()` logs an
error and falls back to `console` rather than breaking the request —
consistent with the rest of this entry's stance that a delivery-channel
failure is never the caller's problem. `STYLESIGNAL_EMAIL_FROM` defaults to
Resend's no-setup sandbox sender (`onboarding@resend.dev`), which only
delivers to the account's own verified email — a verified sending domain
(Resend dashboard → Domains) is needed before this reaches real users.
Tested against `httpx.MockTransport`, never the real API (`tests/test_email.py`).

**No session/refresh-token revocation on reset.** This JWT scheme is
stateless — no server-side session table, nothing to revoke, so a
successful password reset does not invalidate refresh tokens issued before
it (the same is already true of a manual password *change*, which doesn't
exist as a separate authenticated endpoint yet either — reset is the only
password-mutation path today). Worth knowing, not fixed here: closing it
needs a JWT revocation list, which is a bigger feature than "add password
reset" earned on its own.

---

## 16. §7.8 result-screen backend fixes: garment-only palette, focal point, "one verdict only"

Three changes from the August 30 handover's §7.8, all backend-side even
though the handover called the first two "prompt constraints, not code
changes."

**Garment-only palette actually needs a code change, not a prompt tweak.**
"Filter the color palette to garment colors only" can't be a prompt
instruction — the palette was never asked of the VLM in the first place;
`dominant_colours()` measures real pixels from the whole frame (§4.5, and
the README's "why colour comes from pixels, not the model"). The fix is
`colour.garment_palette()`: pools each detected garment's own
already-measured colours (weighted by that garment's bbox area, so a coat
outweighs a belt), merges perceptually-close entries the same way
`dominant_colours` does within one garment, and feeds *that* into
`build_signals` instead of the whole-image sample — both the colour-harmony
classification and the displayed swatches were reading wall/floor tones
before this. One case keeps the whole-image sample on purpose: zero
detected garments (the §7.6 fallback-with-no-VLM path), where there is
nothing garment-level to show and entry #4's reasoning still holds — a
degraded colour read beats no colour read at all.

**Focal point never names the face/body — this one genuinely is
prompt-only**, per the handover's own framing: `focal_point`'s system
prompt line and schema description now say so explicitly. No new lint rule
for it — a regex over "face/hair/skin/body" risks false positives on real
fashion vocabulary (a watch *face*, a *hairline* neckline), and unlike the
§7.3 prohibitions this isn't a phrase blocklist problem, it's a
subject-matter one. Revisit with a real lint rule if it recurs in practice,
the same way entry #10's `RULE_PROPORTION_HEDGE` came from an actual eval
finding rather than a guess.

**"One verdict only" (§7.8): the verdict and the meters must never
disagree.** The concrete bug behind the handover's "two verdicts at once"
report: `fallback.py`'s quick-reads unconditionally asserted "for {occasion},
the register holds" whenever an occasion was set — even when
`formality.coherence` was `"unknown"` (zero garments), directly
contradicting `verdict_phrase`'s own "Hard to place" hedge on the same
screen. Fixed at the source: that quick read only fires when coherence is
actually known. On top of that, `pipeline._enforce_verdict_meter_agreement`
is a general backstop — when both meters come back null (rules.py's own
signal that there is nothing to base a read on), it overwrites
`verdict_phrase`/`verdict_subtitle` with fallback.py's exact hedge
regardless of which path (VLM or fallback) wrote the prose. This is what
actually makes "if confidence is low, the meters cannot read strong" a
guarantee rather than a hope: a real VLM call can in principle write a
confident-sounding verdict for a photo with almost nothing detected, and
now nothing downstream of that call can contradict what the meters show.

---

## 17. Device-testing pass (2026-08-30): quota raised again, community loop switched on early

Two temporary-by-design changes for a testing round on a physical device,
neither a permanent product decision:

**Free-tier scans, 10 → 50.** Same mechanism as entry #13, same caveat: a
testing convenience, not a pricing call. `free_monthly_scans` in
`config.py` and `STYLESIGNAL_FREE_MONTHLY_SCANS` in `.env`/`.env.example`
both moved together so a fresh checkout matches the running server. Revert
to a real number once the redesign is done and Pro pricing is decided (see
below).

**§6.5's community rating loop, switched on ahead of §9's v2 schedule.**
`STYLESIGNAL_COMMUNITY_ENABLED` flipped `true` in `.env` so
`app/routers/feed.py` — complete since entry #1 but dormant — actually has
something to talk to. The gap this closes was on mobile, not the backend:
`CaptureScreen`'s "Share for community feedback" toggle already persisted
`is_public` correctly on upload, but nothing could ever read a public
outfit back, rate it, or earn a scan from doing so. New `FeedScreen.tsx`
fills that in — a card per eligible outfit with three rating rows
(`coherence` / `occasion_fit` / `color`, 1-5 each, matching
`RATING_DIMENSIONS` in `app/models.py`), a "Submit rating" button that
posts whichever dimensions were touched, and a scans-earned notice that
triggers `App.tsx`'s quota refresh. One backend behavior worth knowing
before testing it: `GET /v1/feed` excludes an outfit the moment the caller
has rated it on *any* dimension (`feed.py`'s `already_rated` subquery keys
on outfit, not on outfit+dimension) — so a card always leaves the feed for
good after its first submit, whether one dimension was rated or all three.
`.env.example`'s default stays `false`; this is a per-deployment flip, not
a code default change, since §9 still calls the v2 endpoints deferred.

**The "get more" pill's purchase/upgrade flow is entry #18**, built the same
session after this one — see below for why native IAP over Stripe, and what
still has to happen in App Store Connect / Play Console before it can take
a real payment.

---

## 18. Native in-app purchase — the "get more" pill's real destination

Built after the user chose native IAP over Stripe Checkout (both accounts —
Apple Developer Program and Google Play Console — already exist) and set
$4.99/month as the Pro price. Both stores, one shape throughout: the client
buys through the OS, the backend verifies the finished purchase with
Apple/Google directly, then does the exact same plan mutation either way.
StyleSignal's own servers never see card details.

**Backend — `app/billing.py` + `app/routers/billing.py`.**
`verify_apple_purchase()` posts to Apple's classic `verifyReceipt` endpoint
(shared-secret auth, no JWT signing needed), retrying the sandbox URL on
Apple's documented status 21007 the way Apple's own docs say to.
`verify_google_purchase()` calls the Play Developer API's subscription
endpoint, authenticating via a Google service-account JWT (`google-auth` —
new dependency, wheels-only on Windows/cp39 same as everything else here).
Both return one normalized `VerificationResult`; the router
(`POST /v1/billing/verify-purchase`) is the only place that touches
`user.plan`, so the mutation logic exists exactly once regardless of
platform. A store transaction id can only ever activate the account that
actually paid for it — a second account submitting the same transaction id
gets `purchase_already_claimed`, checked with one query before the plan
flips.

**Pro is now a real subscription that can lapse, not a flag.** `User` gained
`pro_expires_at`, `iap_platform`, `iap_product_id`, `iap_transaction_id`.
`quota.effective_plan(user)` is the one place that decides whether `plan ==
"pro"` still counts — past `pro_expires_at` it silently reverts to free the
next time anything reads quota, lazily, the same non-cron philosophy the
top of `quota.py` already documents for the monthly counter.
`monthly_allowance`, `is_degraded`, and `quota_out` all switched from
reading `user.plan` directly to calling `effective_plan()`. `pro_expires_at
is None` is treated as "no expiry" on purpose — that's an admin/test
override (`plan` set by hand, never through `verify-purchase`), not a real
subscription, and it should keep working exactly as it does today.

**Mobile — `react-native-iap` (Nitro-based, v16), `UpgradeScreen.tsx`.** The
`useIAP()` hook drives the whole flow: `fetchProducts({skus, type:'subs'})`
to read the store's own localized price (falls back to static "$4.99/month"
copy only until a real product exists), `requestPurchase()` to start the
native purchase sheet, and `onPurchaseSuccess` to hand the result to
`verify-purchase`. The two platforms feed the backend the same way it
already expected: iOS calls `getReceiptDataIOS()` for the base64 App Store
receipt `verifyReceipt` wants; Android sends `purchase.purchaseToken`
straight through. `finishTransaction()` — required within 3 days on
Android or Google auto-refunds, and required at all on iOS or the
transaction replays on every launch — only fires *after* the backend
confirms Pro is active, so a network hiccup during verification leaves the
transaction retryable instead of silently dropped. The "get more" pill and
a new "Upgrade to Pro" button on the quota-exceeded error both open this
screen; a "Restore purchases" link is there because App Store review
expects one on any subscription paywall.

**What still can't happen without more from the store consoles.** Code and
tests are real and pass, but nothing here can take an actual dollar yet:
- `stylesignal_pro_monthly` needs to exist as an actual subscription
  product in both App Store Connect and Play Console (same id both places
  — `config.py`'s `iap_product_id_ios`/`iap_product_id_android` and
  mobile's `PRO_SUBSCRIPTION_SKU` all assume that).
- `STYLESIGNAL_APPLE_SHARED_SECRET` (App Store Connect -> App Information)
  and `STYLESIGNAL_GOOGLE_PLAY_SERVICE_ACCOUNT_JSON` (a Google Cloud service
  account with Play Developer API access to this app) are both blank in
  `.env` — `verify-purchase` returns `billing_not_configured` (503) until
  they're set. `STYLESIGNAL_GOOGLE_PLAY_PACKAGE_NAME` is already filled in
  (`com.latencyx.stylesignal`, matching `mobile/app.json`).
- `react-native-iap` is native code — it needs a fresh EAS dev-client build
  before it exists on a device at all, same rebuild-per-native-dependency
  rule as entry #14's dev-client migration.

**Tests.** `tests/test_billing.py`: both verifiers against an
`httpx.MockTransport` (Apple's production→sandbox retry, a rejected
receipt, an expired or cancelled Android subscription, missing config
raising `BillingConfigError`), `effective_plan`/`monthly_allowance`/
`is_degraded` across active/lapsed/no-expiry Pro, and the router end to end
with `app.billing`'s verify functions monkeypatched — including the
replay-protection case, using two registered users against the same
mocked transaction id.

---

## 19. `Button`'s "quiet" variant failed its own AAA contrast note (§2.6)

Caught by actually computing the number §2.6's AAA note only describes:
Slate (`#8A8578`) on Bone (`#F4F0E9`) measures **~3.24:1** — under the 4.5:1
floor the spec cites, confirming the note's instruction to reserve Slate
for "large or secondary text (labels, meta, captions) only" and keep it off
anything load-bearing, explicitly including "button labels."

`primitives.tsx`'s `buttonLabelQuiet` rendered exactly that — Slate — and
the `"quiet"` `Button` variant isn't decorative chrome, it's the only route
to several real actions: "Sign out," "Back" off the result/failure screens,
"Delete" on a history row, "Forgot password?," "I already have an
account." All were sitting under the AA/AAA floor for their type size
(`type.bodyMedium`, 16px — not "large text" by WCAG's own definition, so
the meta/caption carve-out doesn't cover it either).

Fixed by switching `buttonLabelQuiet` to Ink (`colors.text`). The variant
keeps its lighter visual weight from having no fill/border — that was
never what made it fail contrast — so this is a pure compliance fix with
no visible change to which actions read as "primary" vs. "secondary" on
screen, only to whether the secondary ones are legible at their own stated
bar.

---

## 20. Quick-read dimension label didn't match its own icon rhythm

Caught from a device screenshot: a scan whose quick reads included a
proportion observation rendered its section label as "PROPORTION," not
"FIT" as the §7.8 mockup shows — reading as though the "Fit" dimension had
gone missing entirely, when a near-identical read was present under a
different word.

Root cause: `vlm.py`'s `_QUICK_READ_DIMENSIONS` enum is six values wide
(`colour`, `formality`, `proportion`, `pattern`, `texture`, `fit`) — finer-
grained than the four the mockup actually distinguishes. `primitives.tsx`'s
`IconBadge` already collapses this correctly for the icon (`DIMENSION_GLYPH`
maps both `proportion`/`fit` to the ruler glyph and both `pattern`/`texture`
to the dot glyph), but the section label rendered the raw dimension string
verbatim (`<SectionLabel>{item.dimension}</SectionLabel>`, just
`textTransform: uppercase`) — so the icon said "measurement" while the word
next to it didn't agree.

Fixed by adding `dimensionLabel()` next to `DIMENSION_GLYPH` in
`primitives.tsx`, collapsing the same way the icon already does
(`proportion` -> "Fit", `pattern` -> "Texture", `colour`/`formality`
pass through), and using it in `ResultScreen.tsx`'s `QuickReads` instead of
the raw dimension. The backend enum is unchanged — this is purely a
display-layer synonym, so lint, the VLM schema, and stored data all still
speak the six-value vocabulary; only what the user reads on screen
converges to the four the design shows.

---

## 21. §7.7/§7.8 second handover: sharpen a weak occasion match; formality step indicator

Two additions from the August 30 handover's updated PDF, both new relative
to entry #16's build.

**§7.7 — "sharpen the gap, never suggest a fix."** When `occasion_match`
reads `partial`/`off`, the spec now requires naming the *specific* thing
driving the mismatch (an outlier garment, or the register as a whole)
rather than staying vague or — worse — turning it into a suggested fix.

- `vlm.py`: new system-prompt section ("When the occasion match is weak")
  telling the model to reason from the same formality signals + stated
  occasion it already receives (it never sees the computed
  `occasion_match` meter itself, per the existing "computed, not asked of
  the VLM" architecture) and to phrase the gap concretely, using close
  paraphrases of the spec's own examples. No new lint rule needed — the
  existing `RULE_PRESCRIPTION` regex (`swap`, `...instead`, `I'd
  suggest/recommend`, etc.) already covers every forbidden phrasing the
  spec lists, and already runs against `formality_note` and `quick_reads`.
- `fallback.py`: this path previously had no gap-naming text at all — its
  only occasion-related line was a positive "the register holds" template,
  explicitly gated to *not* fire on a weak match (entry #16/#18's fix), so
  a weak match just produced silence on the "fit" dimension. New
  `_occasion_gap_text()` prefers the outlier garment already computed for
  mixed/split coherence (`formality.outlier_category`/`outlier_direction`
  — names an actual piece), and falls back to a band-distance description
  (`OCCASION_FORMALITY_BANDS`, imported from `rules.py` rather than
  duplicated) when the register is internally coherent but sits outside
  the occasion's band entirely. `build_fallback_feedback()` now takes the
  already-computed `occasion_match` meter as a parameter — passed from
  `pipeline.py` (and `scripts/run_eval.py`) rather than recomputed, so the
  fallback text and the persisted meter can never disagree about the
  level, only about how to phrase it.
- Tests: `test_fallback_sharpens_the_gap_with_the_outlier_garment`,
  `test_fallback_sharpens_the_gap_by_band_distance_without_an_outlier`,
  `test_fallback_still_says_register_holds_on_a_strong_match` in
  `test_pipeline.py`.

**§7.8 — formality step indicator.** New `FormalityStepBars` in
`primitives.tsx`: one amber bar per garment, height from that garment's own
`formality` value (§5.4), ordered highest-to-lowest, opacity fading by
*rank* rather than value so the step-down stays legible even when two
garments sit close together. Rendered only under the `formality`
quick-read in `ResultScreen.tsx`'s `QuickReads` — colour, texture, and fit
stay icon + text only, per the spec's explicit "do not add charts to
those three."

One scope decision made with the user rather than assumed: the spec says
"one per garment **mentioned**," but `quick_reads` items aren't tied to
specific `garment_id`s anywhere in the data model, so "mentioned" isn't
computable from what's stored today. Tying it to the actual referenced
subset would mean extending the `quick_reads` schema with a `garment_ids`
list across the VLM schema, prompt, lint, and fallback. Chosen instead:
render bars for *all* garments in the outfit, ordered by formality — no
backend change, and for the typical 3-5 garment outfit this is very likely
the same set the text is describing anyway.

---

## 22. New consumer-side features: occasion re-read, likes, "Try it now" phase 1

From a critique-and-build-order discussion of four proposed features. Full
critique isn't reproduced here — this is the implementation record.

**Occasion nudge + change-occasion re-read.** `CaptureScreen.tsx` nudges
(dismissible, never blocking) when submitting without an occasion tag,
since `occasion_match` has nothing to compare against without one. The
result screen's "change occasion & re-read" was initially proposed as a
free cache hit; that was wrong and got corrected before building it — the
image-hash cache (§8) is keyed on `(image_sha256, occasion)` specifically
so occasion-dependent notes never leak across occasions, and v1's
single-VLM-call architecture can't cheaply redo just the occasion slice.
New `POST /v1/outfits/{id}/reread` charges a real scan, copies the
original photo's bytes server-side (no client re-upload), and does not
carry over `is_public` — re-sharing is a fresh decision each time.

**Likes/favorites (no dislike).** New `Like` model, separate from `Rating`
— ratings stay the structured 1-5 training signal (§5.6); a like is a
lightweight favoriting action, explicitly not wired into the earn-by-rating
loop (`app/quota.py`) so it can't be farmed one-tap-at-a-time the way a
five-way rating call can't. `POST`/`DELETE /v1/outfits/{id}/likes`, both
idempotent. The owner sees an aggregate `like_count` on their own outfit
history/detail — never a list of who liked it, since there's no
profile/follow system yet to make that meaningful. Mobile: heart glyph on
`FeedScreen.tsx` cards renders **amber**, not red, when liked — §2.6's
"amber is the accent, not a verdict colour" rule extends here even though
a like isn't a verdict.

**"Try it now" on shared results — phase 1 only.** The full feature (tap a
shared image, land in the app store or straight into the app if already
installed) needs a Universal/App Link, which needs a real published domain
*and* the app actually being store-distributed — neither exists yet.
Phase 1 ships now: a static "Get your own read — StyleSignal" line baked
into `ShareCard.tsx`'s image (captions don't reliably survive WhatsApp/
iMessage/email shares, so it has to be in the pixels) and the text-share
fallback in `ResultScreen.tsx`. Deliberately brand-only, no domain or store
link, since neither resolves to anything real yet.

**Pinned to-do — Google Play listing.** Chris wants "Get StyleSignal" to
eventually point at the Google Play listing (Apple App Store deferred —
$99/yr recurring vs. Play's $25 one-time, and nothing built so far has
touched iOS). Needs: a Google Play Developer account, a privacy policy URL,
store listing assets, and a `eas build --profile production` +
`eas submit` once ready. Also logged in the `project-stylesignal` memory.
Revisit `ShareCard.tsx` and `buildShareText` once a real listing URL
exists — both are commented as "phase 1, brand-only" pending this.

---

## 23. "Read an item, not worn" (feature #2)

Capture-time toggle, not auto-detection ("On me" / "An item, not worn" on
`CaptureScreen.tsx`) — a mode inferred from pixels alone would misfire
constantly and gives no clean way to legitimately skip signals that don't
apply; an explicit toggle does both.

New `outfits.capture_mode` column (`worn` default | `item`), threaded
through create/presign/reread. Three things change when it's `item`:

- **`_detection_failure_reason`** (pipeline.py) skips the `no_person` check
  entirely — a store/online photo is *expected* to have nobody in it, and
  that gate exists specifically to reject a worn-mode photo missing its
  wearer (the flat-lay/no-person eval set tests exactly that case; this
  doesn't touch it, only adds a bypass for the new mode). `no_garments_detected`
  still applies — an item photo with nothing recognisable as clothing is
  still nothing to read.
- **`rules.build_signals`** zeroes `proportion.flags`/`waistline_y`/
  `upper_to_lower_width_ratio` for item mode — every one of those flags is
  body-relative ("raises the visual waistline") and either meaningless or
  actively misleading without a body. `focal_category` and
  `categories_present` stay: "the biggest garment in frame" and "what's
  present" need no body either way, and `fallback.py`'s focal-point
  fallback depends on `focal_category` surviving.
- **`vlm.py`'s per-request user prompt** (not the system prompt — that's
  explicitly documented as a stable, cross-request-cached prefix, so
  nothing conditional goes there) gets an item-mode section: describe
  piece(s) as objects ("this jacket"), never second-person wearer language
  ("your jacket"), skip proportion/line commentary, keep colour/pattern/
  formality/multi-piece coordination exactly as-is.

`fallback.py` needed no changes — its templates were already third-person
throughout, and the empty `proportion.flags` it now receives already makes
`_proportion_note` return `None` via existing logic.

**Live-DB note:** Render's Postgres already had real rows by the time this
shipped (docs/deployment.md's "once real data exists, create_all is not
enough" threshold), so the new column was added with a direct, additive
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS capture_mode VARCHAR(8) NOT NULL
DEFAULT 'worn'` against the live database before deploying the code that
reads it — safe (nullable-equivalent via server default, no rewrite, no
data loss) but manual, since this project has no Alembic yet.

---

## 24. Stale-processing reaper — an inprocess-queue job orphaned by a deploy

A real production incident, not a hypothetical: a device test (an "item,
not worn" scan — feature #2) got stuck at `status=processing` forever and
the client's poll eventually surfaced as a 502. Root cause: the inprocess
queue (§4.2) isn't durable across a restart — a Render deploy landed while
that job was mid-flight, and the process tearing down mid-job just erased
it, with nothing left to ever mark the outfit `failed`. Not a bug in the
item-mode feature itself; the same thing can happen to any scan if a deploy
lands at the wrong moment, which will keep happening as long as this
project ships iteratively on the inprocess queue.

New `_reap_if_stale()` in `outfits.py`, checked on every `GET
/v1/outfits/{id}` (§6.2): an outfit stuck at `pending`/`processing` past
`STYLESIGNAL_STALE_PROCESSING_TIMEOUT_SECONDS` (default 480s — comfortably
above the worst case of `vlm_timeout_seconds` × (1 + `vlm_max_lint_retries`)
so a genuinely slow-but-alive scan is never mistaken for an orphaned one)
gets marked `failed`/`internal_error` at read time, and its scan is
refunded (§8) — an infrastructure failure isn't a used read, same fairness
as the storage-failure refund in `create_outfit`.

Caught a real portability bug building this: `Outfit.created_at` comes back
timezone-aware from Postgres (production) but naive from SQLite (tests,
despite the column being declared `timezone=True`) — subtracting the two
datetime flavors raises `TypeError`. Normalise to aware UTC before the
subtraction rather than let the dialect decide.

**Not fixed here, flagged for later:** the actual durability gap (jobs
vanishing on restart) is still open — `docs/deployment.md` already
documents the real fix (`STYLESIGNAL_QUEUE_BACKEND=arq` + Redis, jobs
durable across restarts). This reaper is a symptom backstop, not that fix;
worth revisiting once deploys during active development stop being routine.

---

## 25. Moved to the durable Arq/Redis job queue

Real incidents forced this, not a proactive choice: entry #24's reaper was
a symptom backstop, and by the time it shipped, four separate real device
scans had already been orphaned by a restart mid-job — one from a Claude
Code deploy, at least one from what the logs showed was Render's own
infrastructure restarting the instance outside any deploy we triggered.
The inprocess queue losing in-flight work on *any* restart, not just ours,
made the reaper alone not enough.

`app/jobs/arq_queue.py` was already fully built (this session's earlier
`render.yaml` work just hadn't wired it up) — `ArqQueue.enqueue_outfit`,
`process_outfit_job`, and `WorkerSettings` needed zero code changes beyond
bumping `job_timeout` 300s -> 480s to match `stale_processing_timeout_seconds`
(300s was under the worst-case VLM retry sequence of
`vlm_timeout_seconds x (1 + vlm_max_lint_retries)` ~360s, so Arq could have
killed a legitimately-still-working job).

`render.yaml` now provisions three things together: a Render Redis
instance, and a second `worker`-type service (`stylesignal-worker`,
`arq app.jobs.arq_queue.WorkerSettings`) alongside the existing web
service — the actual pipeline execution now happens in the worker, not
inline in a web-service thread pool. The worker only needs the secrets the
pipeline itself touches (DB, object storage, VLM key) — no JWT secret (it
never issues/verifies tokens) and no Resend key (only the auth routes send
email, and those stay in the web service).

The read-time reaper (#24) stays — Arq's own `job_timeout` and retry
handling cover the durability gap, but the reaper is still the backstop
for whatever neither of those catches, and it costs nothing to keep.

---

## 26. The real cause of the item-mode "hangs" — Anthropic SDK's hidden retries

Root cause of the multi-minute stuck scans that entries #24/#25 kept
cleaning up after, finally found: `vlm_timeout_seconds x max_attempts`
(~360s worst case) only accounted for *our own* lint-and-regenerate loop.
The `anthropic.Anthropic` client has its own internal retry-on-failure
(`max_retries=2` by default) that was multiplying silently underneath
every one of our attempts — one call to `client.messages.create` could
itself be up to 3 real HTTP round-trips. Compounded with our own 3
attempts, real worst case was well over 10 minutes, not the ~360s the
reaper/`job_timeout` were sized against. This wasn't specific to item
mode — it's a general VLM-call latency bug that item-mode's real device
tests just happened to trigger a few times in a row.

Fixed by setting `max_retries=0` on the client — we already have retry
logic at the application level (the lint-and-regenerate loop), so the
SDK's own hidden retries were pure redundancy, not resilience. One
attempt in our loop is now genuinely one HTTP call, bounded cleanly by
`vlm_timeout_seconds`.

Diagnosis method worth noting: `debug_last_error` (entry #24's temporary
column) never caught this, because a real network-level hang never raises
an exception — there's nothing for `except Exception` to catch. The
signal that actually pointed here was the *absence* of a caught exception
combined with real-world duration far exceeding the calculated worst case.

---

## 27. The rest of the real cause — worker OOM restarts and an unbounded S3 client

Entry #26 was real but not sufficient — the user's own real photo (a
floral dress on a hanger, item mode) still hung 749s on a retry
afterward, and running that exact file straight through `analyse_outfit()`
outside the API (bypassing storage and the worker entirely) completed in
22s with no issue. That ruled the image itself back out and pointed
at something specific to the deployed worker path.

Two things, found together:

- Render emailed that `stylesignal-worker` "exceeded its memory limit,
  which triggered an automatic restart." `WorkerSettings.max_jobs` was 4,
  and Arq runs concurrent jobs as threads inside one worker *process*
  (`asyncio.to_thread`), not separate processes — so 4 concurrent jobs
  meant 4 full image-decode-plus-VLM-payload working sets stacked on top
  of one shared process baseline (FastAPI/SQLAlchemy/boto3/anthropic-SDK
  imports, connection pools). On Render's `starter` plan that's enough to
  exceed the instance's memory ceiling. A mid-job restart silently
  orphans that job — same "no exception ever raised" shape as #26, which
  is why `debug_last_error` stayed `None` here too, and why only the
  read-time reaper (#24) ever caught it, at whatever multi-hundred-second
  delay it happened to fire at. Fixed by dropping `max_jobs` to 1,
  removing the concurrent-job memory multiplication entirely — cheap at
  current (personal-testing) scan volume; revisit alongside an
  instance-size upgrade if volume grows.
- `S3Storage`'s boto3 client (`app/storage/s3.py`) was constructed with no
  `Config` at all — botocore's own defaults (60s connect timeout, 60s read
  timeout, legacy-mode retries) are the exact same hidden-latency-
  multiplier shape as #26's Anthropic SDK finding, just in the storage
  layer. `storage.get(outfit.original_key)` is the very first thing the
  pipeline does, before any VLM work starts. Not confirmed as having
  fired in the observed incidents, but left unbounded it's a second,
  independent way for a transient R2 hiccup to silently eat minutes with
  no exception raised — fixed preemptively alongside the `max_jobs` fix,
  same reasoning as #26: bound every network call this pipeline makes, not
  just the one already caught in the act. `s3_connect_timeout_seconds`
  (10s), `s3_read_timeout_seconds` (30s), `s3_max_attempts` (2) added to
  `config.py`.

Diagnosis method worth noting: the thing that finally separated "image
content" from "deployment environment" as the cause was reproducing with
the user's *actual* photo file, directly through the pipeline code
(bypassing the API), and having it succeed in 22s — a clean result that
neither of entry #26's synthetic approximations nor any amount of
log-reading had produced. Once the image was cleared, the Render platform
email (not something we went looking for — it arrived mid-session) was
the actual missing piece.
