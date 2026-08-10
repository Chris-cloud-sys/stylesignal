# Deployment

The dev defaults (SQLite, local disk, thread pool) are real implementations,
not stubs — but they are single-process. This is the swap to the §4.9 stack.

---

## 1. Postgres

```bash
pip install "psycopg[binary]"
```

```bash
STYLESIGNAL_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/stylesignal
```

The models are dialect-neutral: `jsonb` columns already use a Postgres variant,
and UUID primary keys map to native `uuid`. Nothing in the schema changes.

**Introduce Alembic before the first deploy.** v1 ships `create_all` because
§9 requires every v2 table to exist in v1, so the first real migration is
additive columns only (`garments.mask_key` is already there; v2 adds vector
columns). Once real data exists, `create_all` is not enough.

```bash
alembic init alembic
# point alembic/env.py at app.db:Base.metadata, then:
alembic revision --autogenerate -m "baseline"
alembic stamp head          # existing databases already match
```

---

## 2. S3 (or any S3-compatible store)

```bash
pip install boto3
```

```bash
STYLESIGNAL_STORAGE_BACKEND=s3
STYLESIGNAL_S3_BUCKET=stylesignal-prod
STYLESIGNAL_S3_REGION=eu-west-1
STYLESIGNAL_S3_SSE=AES256
# STYLESIGNAL_S3_ENDPOINT_URL=https://...   # R2, MinIO, Backblaze, etc.
```

§8 requires encryption at rest; `S3_SSE` is applied to every `put_object` and
defaults to `AES256`. Use `aws:kms` with a CMK if you need key rotation you
control.

The `/v1/media` route is **not mounted** when the backend is `s3` — clients
fetch presigned URLs directly, which is the point.

Bucket policy essentials:

- Block all public access. Every read goes through a presigned URL.
- Lifecycle rule on `outfits/` matching your documented retention (§8 requires
  the retention be documented; pick the number, then write it down).
- CORS only if a browser client will ever `PUT` via Flow B.

---

## 3. Arq on Redis

```bash
pip install arq
```

```bash
STYLESIGNAL_QUEUE_BACKEND=arq
STYLESIGNAL_REDIS_URL=redis://redis-host:6379/0
```

Then run the gateway and the worker as **separate processes**:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
arq app.jobs.arq_queue.WorkerSettings
```

The Arq job id is derived from the outfit id, so Arq deduplicates re-enqueues;
the pipeline is idempotent on top of that (§8) — it clears any prior garments
and feedback before writing, so a retry cannot double-write.

Scale workers by process count. `WorkerSettings.max_jobs` (default 4) bounds
concurrent scans per worker; size it against your model rate limit, not your
CPU — the pipeline is I/O-bound on the VLM call.

---

## 4. Configuration checklist

| Variable | Must change |
|---|---|
| `STYLESIGNAL_ENV` | `production` — also closes the dev CORS wildcard |
| `STYLESIGNAL_JWT_SECRET` | 32+ random bytes, from a secret manager |
| `STYLESIGNAL_ANTHROPIC_API_KEY` | Otherwise every scan returns §7.6 fallback text |
| `STYLESIGNAL_DATABASE_URL` | Postgres |
| `STYLESIGNAL_STORAGE_BACKEND` | `s3` |
| `STYLESIGNAL_QUEUE_BACKEND` | `arq` |
| `STYLESIGNAL_FREE_MONTHLY_SCANS` | 5 per §1 (the test config uses 3) |
| `STYLESIGNAL_PRO_SOFT_MONTHLY_CAP` | Set from measured COGS, not a guess |

Rotating `STYLESIGNAL_JWT_SECRET` invalidates every session **and** every
outstanding signed media URL — they share the key. That is fine at rotation
time; just expect clients to re-authenticate.

---

## 5. Before real users

These are the §8 items that are wired but not production-grade:

- **Password hashing** — PBKDF2 today. Move to argon2id; `app/security.py` is
  the only file that changes.
- **Rate limiting** — in-process, so it under-counts across workers. Move the
  counter to Redis.
- **Account deletion** — §8 requires hard-delete on account deletion. Outfit
  soft-delete and object cleanup exist (§6.4); the account-level cascade does
  not. Add `DELETE /v1/auth/me` that purges rows and calls
  `storage.delete_prefix` per outfit.
- **Retention policy** — §8 requires it be documented. The S3 lifecycle rule
  and the written policy are both on you.
- **`/health`** — liveness only. Add a readiness probe that touches the
  database and Redis if you deploy behind a load balancer.

---

## 6. Observability (§8)

Logs are JSON lines on stdout outside dev (`app/logging_conf.py`). The fields
§8 asks for are already emitted:

| Signal | Where |
|---|---|
| Per-stage timing | `pipeline finished for outfit …` → `timings` object |
| Failure-reason metrics | `outfit … failed` → `reason`, plus `outfits.failure_reason` |
| VLM lint-rejection rate | `outfit_feedback.signals.vlm.lint_attempts` and `.lint_violations` |
| Cache hit rate | `outfit_feedback.signals.cache.hit` |
| Token spend | `outfit_feedback.signals.vlm.usage` |

Because they land in `signals`, the rates are queryable in SQL without a
metrics pipeline on day one:

```sql
-- lint-rejection rate over the last day
SELECT avg((signals->'vlm'->>'lint_attempts')::int - 1) AS avg_regenerations
FROM outfit_feedback
WHERE created_at > now() - interval '1 day'
  AND signals->'vlm'->>'used' = 'true';
```

Watch that number. §7.5 makes the lint pass the enforcement point for the
product's voice, so a rising regeneration rate is the earliest signal that a
prompt change has drifted toward prescription.
